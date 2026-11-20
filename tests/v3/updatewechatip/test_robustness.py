"""按外部代码审查结论逐条验证插件行为。"""

import json
import threading
from types import SimpleNamespace

import pytest
import requests
from fastapi import HTTPException

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


def find_model(node, model):
    """在表单 JSON 中按 model 查找组件节点。"""
    if isinstance(node, dict):
        if node.get("props", {}).get("model") == model:
            return node
        for value in node.values():
            found = find_model(value, model)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_model(item, model)
            if found:
                return found
    return None


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


def test_save_ip_nested_result_error_is_recorded_as_failure():
    """真实接口把 errCode 放在 result 内，也必须判定为失败。"""
    payload = {"statusCode": 200, "result": {"errCode": -80037, "humanMessage": "应用不存在"}}
    plugin = make_plugin(SimpleNamespace(
        post=lambda *args, **kwargs: FakeResponse(text=json.dumps(payload), payload=payload)
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


def test_login_returns_immediately_and_runs_worker():
    """扫码确认后应先回执，再交给后台线程完成登录。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._qrcode_key = "key1"
    sent = []
    plugin.post_message = lambda **kwargs: sent.append(kwargs)
    done = threading.Event()
    plugin._login_worker = lambda *args, **kwargs: done.set()

    plugin._login("Wechat", "member")

    assert sent[0]["title"] == "登录中"
    assert done.wait(5)


def test_login_worker_reports_loginpage_exception():
    """登录页请求异常时应回执失败，而不是抛到事件处理层。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._check = lambda *args: {"auth_code": "code1"}
    sent = []
    plugin.post_message = lambda **kwargs: sent.append(kwargs)

    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    plugin._loginpage_wx = boom

    plugin._login_worker("Wechat", "member", "key1")

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


def test_parse_ip_urls_ignores_blank_and_invalid_items():
    """英文逗号分隔的接口配置只保留 HTTP(S) 地址。"""
    value = "https://one.example/ip, ftp://bad, ,http://two.example/ip,"

    assert UpdateWeChatIp._parse_ip_urls(value) == [
        "https://one.example/ip",
        "http://two.example/ip",
    ]


def test_get_ip_from_url_returns_none_when_all_candidates_fail(monkeypatch):
    """所有接口失败时返回 None，不再使用中文占位字符串。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._ip_urls = ["https://one.example/ip"]

    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", boom)

    assert plugin.get_ip_from_url() is None


def test_get_ip_from_url_skips_invalid_ipv4(monkeypatch):
    """正则命中但不是合法 IPv4 时继续尝试下一个接口。"""
    plugin = make_plugin(SimpleNamespace())
    plugin._ip_urls = ["https://bad.example/ip", "https://good.example/ip"]
    plugin._headers = {"User-Agent": "test"}

    def fake_get(url, **kwargs):
        text = "999.999.999.999" if "bad" in url else "当前 IP：1.2.3.4"
        return FakeResponse(text=text)

    monkeypatch.setattr(requests, "get", fake_get)

    assert plugin.get_ip_from_url() == "1.2.3.4"


def test_form_exposes_optional_ip_urls_field():
    """设置页底部应提供选填的 IPv4 查询接口，默认留空。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)

    form, defaults = plugin.get_form()

    assert defaults["_ip_urls"] == ""
    assert find_model(form, "_ip_urls")["component"] == "VTextField"


def test_form_uses_single_line_field_for_app_id():
    """应用ID使用单行输入框，避免长提示文字换行后被裁切。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)

    form, _ = plugin.get_form()

    field = find_model(form, "_app_id")
    assert field["component"] == "VTextField"
    assert "rows" not in field["props"]


def test_form_shows_persistent_hints_for_cron_and_app_id():
    """检测周期和应用ID都应显示常驻说明。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)

    form, _ = plugin.get_form()

    cron = find_model(form, "_cron")["props"]
    assert cron["hint"].startswith("5位 cron 表达式")
    assert cron["persistent-hint"] is True
    app_id = find_model(form, "_app_id")["props"]
    assert app_id["hint"] == "在企业微信应用页面 URL 末尾获取"
    assert app_id["persistent-hint"] is True


def test_page_only_shows_app_id_in_records_table():
    """状态栏不再展示应用ID，仅记录表头使用中文应用ID。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._app_id = "app1, app2"
    plugin._is_login = True
    plugin._ip = "1.2.3.4"
    plugin._party_cache_data = {"party_list": {"list": [{"name": "小螺号"}]}}
    plugin.get_data = lambda key: []

    page = plugin.get_page()

    texts = []

    def collect(node):
        if isinstance(node, dict):
            if "text" in node:
                texts.append(node["text"])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(page)
    assert all("应用ID：" not in text for text in texts)
    assert "应用ID" in texts
    assert "appId" not in texts


def test_page_groups_same_check_app_ids_in_one_cell():
    """同一次检测的多个应用ID合并到一行，并在单元格内分行展示。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._app_id = "app1,app2"
    plugin._is_login = True
    plugin._ip = "1.2.3.4"
    plugin._party_cache_data = {"party_list": {"list": [{"name": "小螺号"}]}}
    plugin.get_data = lambda key: [
        {"status": True, "ip": "1.2.3.4", "app_id": "app1",
         "result": "{}", "UpdateTime": "2026-11-20T01:00:00.100000"},
        {"status": True, "ip": "1.2.3.4", "app_id": "app2",
         "result": "{}", "UpdateTime": "2026-11-20T01:00:00.900000"},
    ]

    page = plugin.get_page()

    texts = []

    def collect(node):
        if isinstance(node, dict):
            if "text" in node:
                texts.append(node["text"])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(page)
    assert "最近 2 条" in texts
    assert "同次检测已合并" in texts
    assert "app2," in texts
    assert "app1" in texts


def test_page_shows_each_app_result_and_mixed_status():
    """同一检测行内成功与失败并存时，结果列按应用逐条显示，状态为部分失败。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._is_login = True
    plugin._ip = "1.2.3.4"
    plugin._party_cache_data = {"party_list": {"list": [{"name": "小螺号"}]}}
    plugin.get_data = lambda key: [
        {"status": True, "ip": "1.2.3.4", "app_id": "app1",
         "result": "{}", "UpdateTime": "2026-11-20T01:00:00.100000"},
        {"status": False, "ip": "1.2.3.4", "app_id": "app2",
         "result": '{"result":{"errCode":-80037,"humanMessage":"应用不存在"}}',
         "UpdateTime": "2026-11-20T01:00:00.900000"},
    ]

    page = plugin.get_page()
    texts = []

    def collect(node):
        if isinstance(node, dict):
            if "text" in node:
                texts.append(node["text"])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(page)
    assert "部分失败" in texts
    assert "已更新" in texts
    assert "应用不存在" in texts


def test_log_result_text_hides_success_payload():
    """成功记录不再把原始 JSON 当作结果展示。"""
    assert UpdateWeChatIp._log_result_text(
        True, '{"data":{"reject_subadmin_ids":[]}}'
    ) == "已更新"


def test_log_result_text_shows_failure_message():
    """失败记录优先展示中文化的错误原因。"""
    assert UpdateWeChatIp._log_result_text(
        False, '{"errCode":-4,"errmsg":"invalid ip"}'
    ) == "不安全的访问IP"


def test_log_result_text_uses_message_field():
    """企业微信常见的 message 字段同样映射为中文原因。"""
    assert UpdateWeChatIp._log_result_text(
        False, '{"errCode":-3,"message":"outsession","etype":"otherLogin"}'
    ) == "登录已失效，请重新登录"


def test_log_result_text_maps_error_codes_without_message():
    """没有原文说明时按错误码映射，-4 缺省按登录失效处理。"""
    assert UpdateWeChatIp._log_result_text(False, '{"errCode":-4}') == "登录已失效，请重新登录"
    assert UpdateWeChatIp._log_result_text(False, '{"errcode":-80037}') == "应用不存在"
    assert UpdateWeChatIp._log_result_text(False, '{"errCode":60020}') == "不安全的访问IP"


def test_log_result_text_handles_empty_response():
    """失败响应为空时给出明确占位文本。"""
    assert UpdateWeChatIp._log_result_text(False, "") == "无返回内容"


def test_log_result_text_truncates_long_error_message():
    """过长的接口错误信息要截断，避免撑开记录表格。"""
    result = '{"errcode":1,"errmsg":"%s"}' % ("x" * 120)

    text = UpdateWeChatIp._log_result_text(False, result)

    assert text.endswith("…")
    assert len(text) <= 81


def test_save_ip_records_http_status_for_empty_error_response():
    """空响应的 HTTP 错误应记录状态码，而不是留下空结果。"""
    plugin = make_plugin(SimpleNamespace(
        post=lambda *args, **kwargs: FakeResponse(status_code=403, text="")
    ))

    plugin._save_ip_config()

    assert plugin._saved[1][0]["result"] == "HTTP 403"


def test_ip_urls_have_class_level_default():
    """未执行 init_plugin 时也能直接使用内置接口列表。"""
    assert UpdateWeChatIp._ip_urls == UpdateWeChatIp._default_ip_urls


def test_update_ip_rejects_invalid_ipv4():
    """接口传入非法地址时返回 400，不向企微发请求。"""
    plugin = make_plugin(SimpleNamespace())
    called = []
    plugin._save_ip_config = lambda: called.append(True)

    with pytest.raises(HTTPException) as exc_info:
        plugin.UpdateIp("999.999.999.999")

    assert exc_info.value.status_code == 400
    assert not called


def test_update_ip_accepts_valid_ipv4_and_trims():
    """合法地址去掉首尾空格后写入。"""
    plugin = make_plugin(SimpleNamespace())
    called = []
    plugin._save_ip_config = lambda app_ids=None: called.append(app_ids) or [
        SimpleNamespace(status=True, app_id="app1")
    ]

    result = plugin.UpdateIp(" 1.2.3.4 ")

    assert plugin._ip == "1.2.3.4"
    assert called
    assert result["success"] is True
    assert result["updated"] == 1
