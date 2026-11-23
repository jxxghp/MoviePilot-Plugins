"""验证可信IP更新：多应用逐个校验、结果通知与记录时间戳。"""

from types import SimpleNamespace

from app.plugins.updatewechatip import UpdateWeChatIp


class FakeResponse:
    """最小响应替身，覆盖插件用到的 status_code/text/json/content。"""

    def __init__(self, status_code=200, text='{"data":{}}', payload=None, content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content
        self._payload = {"data": {}} if payload is None else payload

    def json(self):
        """返回预置 JSON。"""
        return self._payload


def make_plugin(session, app_id="app1", ip="1.2.3.4") -> UpdateWeChatIp:
    """构造只带被测依赖的插件实例。"""
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._se = session
    plugin._app_id = app_id
    plugin._ip = ip
    plugin._headers = {}
    plugin._saved = None
    plugin.save_data = lambda key, value: setattr(plugin, "_saved", (key, value))
    plugin.get_data = lambda key: []
    return plugin


def build_check_plugin(session, app_id="app1,app2", white_lists=None, ip="1.2.3.4"):
    """构造可直接执行 check() 的插件实例，外部接口全部替换为替身。"""
    plugin = make_plugin(session, app_id=app_id, ip=None)
    plugin._enabled = True
    plugin._is_login = True
    plugin._party_cache = lambda: True
    plugin.get_ip_from_url = lambda: ip
    white_lists = white_lists if white_lists is not None else {}
    plugin._get_corp_app_v2 = lambda app_id=None: {
        "app": {"white_ip_list": {"ip": list(white_lists.get(app_id, []))}}
    }
    plugin.messages = []
    plugin.post_message = lambda **kwargs: plugin.messages.append(kwargs)
    return plugin


def test_save_ip_config_shares_one_timestamp_for_all_apps():
    """同一次更新的所有应用记录必须共用更新时间，避免详情页按秒拆组。"""
    plugin = make_plugin(SimpleNamespace(post_res=lambda *args, **kwargs: FakeResponse()),
                         app_id="app1, app2")

    results = plugin._save_ip_config()

    assert [row.app_id for row in results] == ["app1", "app2"]
    assert len({row.UpdateTime for row in results}) == 1
    assert {row["UpdateTime"] for row in plugin._saved[1]} == {results[0].UpdateTime.isoformat()}


def test_save_ip_config_writes_only_requested_apps():
    """显式指定应用时只写这些应用，不触碰其它应用。"""
    plugin = make_plugin(SimpleNamespace(post_res=lambda *args, **kwargs: FakeResponse()),
                         app_id="app1,app2")

    results = plugin._save_ip_config(["app2"])

    assert [row.app_id for row in results] == ["app2"]


def test_check_updates_only_apps_missing_current_ip():
    """应用 A 已登记当前 IP 时不应重复写入，只补写缺少 IP 的应用 B。"""
    plugin = build_check_plugin(
        SimpleNamespace(post_res=lambda *args, **kwargs: FakeResponse()),
        white_lists={"app1": ["1.2.3.4"], "app2": []},
    )
    captured = {}

    def fake_save(app_ids=None):
        captured["app_ids"] = app_ids
        return []

    plugin._save_ip_config = fake_save

    plugin.check()

    assert captured["app_ids"] == ["app2"]


def test_check_skips_update_when_all_apps_have_current_ip():
    """所有应用都已登记当前 IP 时不写配置也不通知。"""
    plugin = build_check_plugin(
        SimpleNamespace(post_res=lambda *args, **kwargs: FakeResponse()),
        white_lists={"app1": ["1.2.3.4"], "app2": ["1.2.3.4"]},
    )
    plugin._save_ip_config = lambda app_ids=None: pytest_fail("不应写入配置")

    plugin.check()

    assert plugin.messages == []


def pytest_fail(message: str):
    """在属性替身里显式失败，避免测试静默通过。"""
    raise AssertionError(message)


def test_check_reports_failure_instead_of_success():
    """所有应用写入失败时通知必须报失败，不能提示触发更新成功。"""
    payload = {"errCode": -4, "errMsg": "invalid ip"}
    plugin = build_check_plugin(
        SimpleNamespace(post_res=lambda *args, **kwargs: FakeResponse(
            text='{"errCode":-4,"errMsg":"invalid ip"}', payload=payload
        ))
    )

    plugin.check()

    assert len(plugin.messages) == 1
    assert plugin.messages[0]["text"].startswith("IP更新失败")
    assert "app1" in plugin.messages[0]["text"]
    assert "app2" in plugin.messages[0]["text"]


def test_check_reports_partial_failure():
    """部分应用失败时通知要区分成功与失败。"""
    payloads = {"app1": {"data": {}}, "app2": {"errCode": -4, "errMsg": "invalid ip"}}

    def fake_post(url, **kwargs):
        app_id = kwargs["data"]["app_id"]
        payload = payloads[app_id]
        return FakeResponse(text="{}", payload=payload)

    plugin = build_check_plugin(SimpleNamespace(post_res=fake_post))

    plugin.check()

    assert len(plugin.messages) == 1
    assert "部分失败" in plugin.messages[0]["text"]
    assert "成功 1 个" in plugin.messages[0]["text"]


def test_qrcode_log_does_not_leak_image_token(caplog):
    """二维码日志只记录地址形式，不写入带令牌的完整地址。"""
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    plugin = make_plugin(SimpleNamespace(get_res=lambda *args, **kwargs: FakeResponse(content=png)))

    with caplog.at_level("INFO"):
        url = plugin._qrcode("qrcode-key", channel=None)

    assert url and "?t=" in url
    assert "?t=" not in caplog.text
