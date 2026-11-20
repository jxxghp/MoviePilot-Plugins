"""
验证登录二维码统一走宿主原图协议，并对客户端抓图的渠道补一行地址兜底。
"""

from app.modules.dingtalk.dingtalk import DingTalk
from app.plugins.updatewechatip import UpdateWeChatIp
from app.schemas.notification import ChannelCapabilityManager, ChannelCapability
from app.schemas.types import NotificationChannel

PUBLIC_URL = "https://mp.example/api/v1/plugin/UpdateWeChatIp/img/token?t=abc"
LOOPBACK_URL = "http://127.0.0.1:3001/api/v1/plugin/UpdateWeChatIp/img/token?t=abc"
RELATIVE_URL = "/api/v1/plugin/UpdateWeChatIp/img/token?t=abc"

SAME_ORIGIN = (NotificationChannel.Web, NotificationChannel.WebAgent)


def _supports(channel, capability: ChannelCapability) -> bool:
    return ChannelCapabilityManager.supports_capability(channel, capability)


# 客户端自行抓图的渠道：有图片能力但没有原图上传能力
CLIENT_FETCH_CHANNELS = [
    channel for channel in NotificationChannel
    if channel not in SAME_ORIGIN
    and _supports(channel, ChannelCapability.IMAGES)
    and not _supports(channel, ChannelCapability.NATIVE_IMAGES)
]
# 连图片能力都没有的渠道，由宿主自行给出提示
NO_IMAGE_CHANNELS = [
    channel for channel in NotificationChannel
    if channel not in SAME_ORIGIN and not _supports(channel, ChannelCapability.IMAGES)
]
NATIVE_CHANNELS = [
    channel for channel in NotificationChannel
    if channel not in SAME_ORIGIN and _supports(channel, ChannelCapability.NATIVE_IMAGES)
]


def _build_plugin() -> UpdateWeChatIp:
    """
    构造不初始化网络会话的插件实例。
    """
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._qrcode_key = "qrcode-key"
    return plugin


def test_channel_sets_are_not_empty() -> None:
    """
    宿主能力表应同时存在三类渠道，避免用例空跑。
    """
    assert NATIVE_CHANNELS
    assert CLIENT_FETCH_CHANNELS
    assert NO_IMAGE_CHANNELS


def test_all_remote_channels_use_native_image_contract() -> None:
    """
    非页面渠道统一表达原图意图，上传与降级交给宿主。
    """
    plugin = _build_plugin()
    for channel in (*NATIVE_CHANNELS, *CLIENT_FETCH_CHANNELS, *NO_IMAGE_CHANNELS):
        payload = plugin._qrcode_message(channel, "member", PUBLIC_URL)

        assert payload["image"] == PUBLIC_URL
        assert payload["native_image"] is True
        assert not payload.get("link")
        assert payload["buttons"][0][0]["callback_data"].endswith("|扫码完成|qrcode-key")


def test_client_fetch_channels_carry_address_fallback() -> None:
    """
    客户端抓图的渠道在正文补一行可打开的地址，抓图失败时仍能看二维码。
    """
    plugin = _build_plugin()
    for channel in CLIENT_FETCH_CHANNELS:
        payload = plugin._qrcode_message(channel, "member", PUBLIC_URL)

        assert f"二维码地址（图片未显示时可打开）：{PUBLIC_URL}" in payload["text"]


def test_native_and_push_channels_do_not_duplicate_address() -> None:
    """
    原图渠道不需要兜底地址，推送渠道由宿主补提示，避免正文重复。
    """
    plugin = _build_plugin()
    for channel in (*NATIVE_CHANNELS, *NO_IMAGE_CHANNELS):
        payload = plugin._qrcode_message(channel, "member", PUBLIC_URL)

        assert PUBLIC_URL not in payload["text"]


def test_same_origin_channels_keep_relative_image() -> None:
    """
    页面内渲染的渠道用相对地址展示图片，不带原图标记也不带兜底地址。
    """
    plugin = _build_plugin()
    for channel in SAME_ORIGIN:
        payload = plugin._qrcode_message(channel, "member", RELATIVE_URL)

        assert payload["image"] == RELATIVE_URL
        assert not payload.get("native_image")
        assert not payload.get("link")


def test_unreachable_url_falls_back_to_hint() -> None:
    """
    地址不可对外访问时不发图片，只在正文说明该渠道无法展示。
    """
    plugin = _build_plugin()
    for channel in (*NATIVE_CHANNELS, *CLIENT_FETCH_CHANNELS, *NO_IMAGE_CHANNELS):
        payload = plugin._qrcode_message(channel, "member", LOOPBACK_URL)

        assert not payload.get("image")
        assert not payload.get("link")
        assert "没有配置可对外访问的地址" in payload["text"]


def test_unspecified_channel_keeps_native_contract() -> None:
    """
    未指定渠道时按原图意图投递，由宿主决定降级。
    """
    payload = _build_plugin()._qrcode_message(None, "member", PUBLIC_URL)

    assert payload["image"] == PUBLIC_URL
    assert payload["native_image"] is True


def test_dingtalk_renders_image_then_address_line() -> None:
    """
    钉钉最终 markdown：正文带兜底地址，图片紧随其后；两者都在。
    """
    payload = _build_plugin()._qrcode_message(NotificationChannel.DingTalk, "member", PUBLIC_URL)
    _, body = DingTalk.build_markdown(
        title=payload["title"], text=payload["text"],
        image=payload["image"], link=payload.get("link"),
    )

    assert f"![图片]({PUBLIC_URL})" in body
    assert f"二维码地址（图片未显示时可打开）：{PUBLIC_URL}" in body
    assert body.index(f"二维码地址（图片未显示时可打开）") < body.index(f"![图片]({PUBLIC_URL})")


def test_shareable_image_url_rejects_local_addresses() -> None:
    """
    回环、相对与非 HTTP 地址都不能交给外部客户端。
    """
    for candidate in (LOOPBACK_URL, "http://localhost:3001/img", RELATIVE_URL, "file:///tmp/a.png"):
        assert UpdateWeChatIp._shareable_image_url(candidate) is None
    assert UpdateWeChatIp._shareable_image_url(PUBLIC_URL) == PUBLIC_URL


def test_shareable_image_url_rejects_reserved_address_families() -> None:
    """
    整个 127/8、未指定地址、link-local 与 .localhost 子域同样不可分享，内网地址仍放行。
    """
    for candidate in (
        "http://127.0.0.2:3001/img/a.png",
        "http://127.255.255.254:3001/img/a.png",
        "http://0.0.0.0:3001/img/a.png",
        "http://[::1]:3001/img/a.png",
        "http://169.254.1.1:3001/img/a.png",
        "http://[fe80::1]:3001/img/a.png",
        "http://qr.localhost:3001/img/a.png",
    ):
        assert UpdateWeChatIp._shareable_image_url(candidate) is None

    for candidate in ("http://192.168.1.100:3001/img/a.png", PUBLIC_URL):
        assert UpdateWeChatIp._shareable_image_url(candidate) == candidate


def test_image_media_type_detects_png() -> None:
    """
    按文件头把 PNG 二维码识别为 image/png。
    """
    content = b"\x89PNG\r\n\x1a\n" + b"0" * 8

    assert UpdateWeChatIp._image_media_type(content) == "image/png"


def test_image_media_type_defaults_to_jpeg() -> None:
    """
    其它编码按 JPEG 回退，避免声明与服务端解析不一致。
    """
    assert UpdateWeChatIp._image_media_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
