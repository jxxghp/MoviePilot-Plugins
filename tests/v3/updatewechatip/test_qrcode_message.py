"""验证企微渠道的登录二维码改用原生图片消息。"""

from app.plugins.updatewechatip import UpdateWeChatIp
from app.schemas.types import NotificationChannel


def _build_plugin() -> UpdateWeChatIp:
    """构造不初始化网络会话的插件实例。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._qrcode_key = "qrcode-key"
    return plugin


def test_wechat_channel_uses_native_image() -> None:
    """企微渠道请求原生图片，并提示可长按识别。"""
    payload = _build_plugin()._qrcode_message(
        NotificationChannel.Wechat, "member", "https://mp.example/img"
    )

    assert payload["image"] == "https://mp.example/img"
    assert payload["native_image"] is True
    assert "长按识别" in payload["text"]
    assert payload["buttons"][0][0]["callback_data"].endswith("|扫码完成|qrcode-key")


def test_other_channel_keeps_news_card() -> None:
    """其它渠道保持图文卡片，不请求原生图片。"""
    payload = _build_plugin()._qrcode_message(
        NotificationChannel.Telegram, "member", "https://mp.example/img"
    )

    assert payload["image"] == "https://mp.example/img"
    assert payload["native_image"] is False
    assert "长按识别" not in payload["text"]


def test_image_media_type_detects_png() -> None:
    """按文件头把 PNG 二维码识别为 image/png。"""
    content = b"\x89PNG\r\n\x1a\n" + b"0" * 8

    assert UpdateWeChatIp._image_media_type(content) == "image/png"


def test_image_media_type_defaults_to_jpeg() -> None:
    """其它编码按 JPEG 回退，避免声明与服务端解析不一致。"""
    assert UpdateWeChatIp._image_media_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
