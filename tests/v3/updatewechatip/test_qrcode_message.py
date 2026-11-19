"""
验证登录二维码只表达原图意图，不再由插件判断消息渠道。
"""

import pytest

from app.plugins.updatewechatip import UpdateWeChatIp
from app.schemas.types import NotificationChannel


def _build_plugin() -> UpdateWeChatIp:
    """
    构造不初始化网络会话的插件实例。
    """
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._qrcode_key = "qrcode-key"
    return plugin


@pytest.mark.parametrize("channel", [*NotificationChannel, None])
def test_all_channels_use_same_native_image_contract(channel) -> None:
    """
    所有渠道和未指定渠道的通知均使用相同原图参数，保留按钮和说明。
    """
    payload = _build_plugin()._qrcode_message(
        channel, "member", "https://mp.example/img"
    )

    assert payload["image"] == "https://mp.example/img"
    assert payload["native_image"] is True
    assert "识别或扫描" in payload["text"]
    assert payload["buttons"][0][0]["callback_data"].endswith("|扫码完成|qrcode-key")


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
