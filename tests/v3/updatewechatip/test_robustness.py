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


def test_fail_hint_recognizes_lowercase_errcode():
    """小写 errcode 的登录失效响应也应给出重新扫码提示。"""
    res = FakeResponse(text='{"errcode":-4,"errmsg":"outsession"}')

    assert "登录已失效" in UpdateWeChatIp._fail_hint(res)


def test_submit_captcha_without_tl_key_prompts_rescan():
    """没有 tl_key 时提交验证码应提示重新扫码，而不是调用接口。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._tl_key = None
    plugin._captcha = {"key1": "123456"}
    sent = []
    called = []
    plugin.post_message = lambda **kwargs: sent.append(kwargs)
    plugin._confirm_captcha = lambda *args: called.append(args)

    plugin._submit_captcha("Wechat", "member", "key1")

    assert not called
    assert sent[0]["title"] == "验证码不可用"


def test_login_reports_loginpage_exception():
    """登录页请求异常时应回执失败，而不是抛到事件处理层。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._qrcode_key = "key1"
    plugin._check = lambda *args: {"auth_code": "code1"}
    sent = []
    plugin.post_message = lambda **kwargs: sent.append(kwargs)

    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    plugin._loginpage_wx = boom

    plugin._login("Wechat", "member")

    assert sent[0]["title"] == "登录失败"
    assert "异常" in sent[0]["text"]


def test_get_buttons_use_passed_qrcode_key():
    """验证码按钮应携带本次登录的 qrcode_key，而不是实例上的旧值。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._qrcode_key = "old-key"

    buttons = plugin._get_buttons("new-key")
    callbacks = [button["callback_data"] for row in buttons for button in row]

    assert callbacks and all(callback.endswith("|new-key") for callback in callbacks)


def test_confirm_captcha_passes_tl_key_as_params():
    """tl_key 应作为查询参数交给 requests 编码，避免特殊字符破坏 URL。"""
    calls = {}

    def get(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return FakeResponse()

    plugin = make_plugin(SimpleNamespace(post=lambda *args, **kwargs: FakeResponse(), get=get))

    plugin._confirm_captcha("a+b&c", "123456")

    assert calls["url"].endswith("/login/choose_corp")
    assert calls["kwargs"]["params"] == {"tl_key": "a+b&c"}
