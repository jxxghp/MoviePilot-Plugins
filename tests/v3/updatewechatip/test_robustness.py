"""按外部代码审查结论逐条验证插件行为。"""

import json
from types import SimpleNamespace

import pytest
import requests

from app.plugins.updatewechatip import UpdateLogDto, UpdateWeChatIp


class FakeResponse:
    """最小响应替身，覆盖插件用到的 status_code/text/json/content。"""

    def __init__(self, status_code=200, text="", payload=None, content=b"", url="https://example"):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.content = content
        self.url = url

    def json(self):
        """返回预置 JSON，未提供时模拟非 JSON 响应。"""
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def make_plugin(session):
    """构造只带被测依赖的插件实例。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._se = session
    plugin._app_id = "app1"
    plugin._ip = "1.2.3.4"
    plugin._update_log = []
    plugin.save_data = lambda key, value: setattr(plugin, "_saved", (key, value))
    plugin.get_data = lambda key: []
    plugin._headers = {}
    return plugin


def test_save_ip_success_payload_is_recorded_as_success():
    """真实成功响应 {"data": ...} 不含 err，应记录为成功。"""
    plugin = make_plugin(SimpleNamespace(
        post=lambda *args, **kwargs: FakeResponse(
            text='{"data":{"reject_subadmin_ids":[]}}',
            payload={"data": {"reject_subadmin_ids": []}},
        )
    ))

    plugin._save_ip_config()

    assert plugin._saved[1][0]["status"] is True


def test_save_ip_error_payload_is_recorded_as_failure():
    """errCode 失败响应应记录为失败。"""
    plugin = make_plugin(SimpleNamespace(
        post=lambda *args, **kwargs: FakeResponse(
            text='{"errCode":-4,"errMsg":"invalid ip"}',
            payload={"errCode": -4, "errMsg": "invalid ip"},
        )
    ))

    plugin._save_ip_config()

    assert plugin._saved[1][0]["status"] is False


def test_party_cache_accepts_zero_err_code():
    """成功响应即使带 errCode=0 也应判定为已登录。"""
    payload = {"errCode": 0, "data": {"party_list": {"list": [{"name": "corp"}]}}}
    session = SimpleNamespace(
        cookies=SimpleNamespace(set=lambda *args: None),
        post=lambda *args, **kwargs: FakeResponse(text=json.dumps(payload), payload=payload),
    )
    plugin = make_plugin(session)
    plugin._wwrtx_sid = "sid"

    assert plugin._party_cache() is True


def test_update_log_accepts_legacy_record_without_time():
    """历史记录缺少 UpdateTime 时不应抛异常。"""
    record = UpdateLogDto.from_dict(
        {"status": True, "ip": "1.2.3.4", "app_id": "app1", "result": "ok"}
    )

    assert record.UpdateTime is not None


def test_save_ip_without_app_id_does_not_crash():
    """未配置应用 ID 时不应抛 AttributeError。"""
    plugin = make_plugin(SimpleNamespace(post=lambda *args, **kwargs: FakeResponse()))
    plugin._app_id = None

    plugin._save_ip_config()


def test_get_key_returns_none_on_network_error():
    """获取二维码 key 网络失败应返回 None 而不是抛异常。"""

    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    plugin = make_plugin(SimpleNamespace(get=boom))

    assert plugin._get_key() is None


def test_qrcode_rejects_error_page():
    """二维码接口返回错误页时不应把它当作图片缓存。"""
    plugin = make_plugin(SimpleNamespace(
        get=lambda *args, **kwargs: FakeResponse(status_code=403, content=b"<html>403</html>")
    ))

    assert plugin._qrcode("key", channel=None) is None


def test_login_success_preserves_unknown_config_keys():
    """保存登录态时应保留配置里的其它字段。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._clear_fail = lambda: None
    plugin.get_config = lambda: {"onlyonce": False, "_cron": "*/10 * * * *", "custom": "keep"}
    plugin.update_config = lambda config: setattr(plugin, "_config", config)

    plugin._login_success()

    assert plugin._config["custom"] == "keep"
