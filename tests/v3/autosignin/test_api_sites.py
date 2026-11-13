"""回归宿主 API 站点的认证复用、结果记录及重试，所有传输使用替身。"""

import json
from contextlib import closing
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests import Response
from ruamel.yaml import CommentedMap

from app.application.site.protocol import SiteConnectionResult
from app.modules.indexer import IndexerModule
from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.result import SiteResult


def _site(**changes):
    """构造只含虚构 API 凭据且不含 Cookie 的站点配置。"""
    site = CommentedMap({
        "id": 1, "name": "高清杜比", "url": "https://www.uhddolby.com/", "schema": "HDDolby",
        "domain": "https://old.example/", "api_url": "https://api.custom.test/api/v1/",
        "apikey": "synthetic-key", "cookie": "", "ua": "AutoSignIn-Test", "proxy": True, "timeout": 25,
    })
    site.update(changes)
    return site


def _response(payload, status=200):
    """构造保留 HTTP 错误布尔语义的 JSON 响应并跟踪关闭。"""
    response = Response()
    response.status_code = status
    response.reason = "Test Error" if status != 200 else "OK"
    response._content = json.dumps(payload).encode()
    response.encoding = "utf-8"
    response.close = Mock()
    return response


@pytest.fixture
def plugin(monkeypatch):
    """隔离站点统计、网页传输与宿主分发，不创建真实插件数据。"""
    instance = object.__new__(AutoSignIn)
    instance._site_schema = []
    instance.chain = SimpleNamespace(run_module=Mock(return_value=SiteConnectionResult(True, True, "连接成功")))
    instance.stats = Mock()
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=instance.stats))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(side_effect=AssertionError("不应访问网页")))
    monkeypatch.setattr("app.plugins.autosignin.PlaywrightHelper", Mock(side_effect=AssertionError("不应启动浏览器")))
    return instance


@pytest.mark.parametrize("action", ["signin_site", "login_site"])
@pytest.mark.parametrize("schema", ["HDDolby", "Piggo"])
@pytest.mark.parametrize("resource_key", ["schema", "parser"])
@pytest.mark.parametrize("cookie", ["", "unused-cookie"])
def test_api_access_reuses_host_configuration_without_cookie(plugin, action, schema, resource_key, cookie):
    """两种资源协议字段均保留完整配置，API 鉴权由宿主适配器负责。"""
    site = _site(schema=None, render=True, cookie=cookie)
    site[resource_key] = schema
    result = getattr(plugin, action)(site)
    assert result.logged_in is True
    assert result.success is (action == "login_site")
    assert result.message == ("模拟登录成功" if action == "login_site" else "登录成功，签到未确认")
    plugin.chain.run_module.assert_called_once_with(
        "test_site", site={**site, "domain": site["url"]}, raise_exception=True,
    )
    plugin.stats.success.assert_called_once()
    plugin.stats.fail.assert_not_called()


@pytest.mark.parametrize("action", ["signin_site", "login_site"])
@pytest.mark.parametrize("message", [
    "APIKEY已过期", "猪猪存取令牌已过期或无效", "未配置 API Key", "站点限流：HTTP 429",
    "HDDolby API 主机 api.custom.test 返回 HTTP 503", "有未读必读公告，请到猪猪网页端阅读后重试",
])
def test_supported_api_failure_is_preserved_and_requested_once(plugin, action, message):
    """凭据、网络和业务失败只执行一次检测，保留真实原因供历史和通知分类。"""
    plugin.chain.run_module.return_value = SiteConnectionResult(True, False, message)
    result = getattr(plugin, action)(_site())
    assert result.success is False and result.logged_in is False
    assert message in result.message and "Cookie" not in result.message
    plugin.chain.run_module.assert_called_once()
    plugin.stats.fail.assert_called_once()
    plugin.stats.success.assert_not_called()


@pytest.mark.parametrize("action", ["signin_site", "login_site"])
@pytest.mark.parametrize("connection", [None, SiteConnectionResult(False)])
def test_missing_module_result_remains_explicit_failure(plugin, action, connection):
    """模块未装配或没有回执时报告检测失败，避免再次误报 Cookie 缺失。"""
    plugin.chain.run_module.return_value = connection
    result = getattr(plugin, action)(_site())
    assert not result.completed and "检测" in result.message and "Cookie" not in result.message
    plugin.chain.run_module.assert_called_once()


def test_module_exception_hides_credentials_and_does_not_retry(plugin):
    """传输异常保留可诊断原因并移除可能回显的各类认证值。"""
    plugin.chain.run_module.side_effect = ValueError("HTTP 503 synthetic-key synthetic-token synthetic-cookie")
    result = plugin.signin_site(_site(token="synthetic-token", cookie="synthetic-cookie"))
    assert not result.completed and "HTTP 503" in result.message
    assert "synthetic-" not in result.message
    plugin.chain.run_module.assert_called_once()


@pytest.mark.parametrize("action,base", [("signin_site", "__signin_base"), ("login_site", "__login_base")])
def test_other_protocols_preserve_web_signin_and_login(plugin, monkeypatch, action, base):
    """普通网页协议继续执行原路径，即使宿主也提供连接检测也会执行网页签到。"""
    expected = SiteResult("网页站点", "签到成功", True, True)
    handler = Mock(return_value=expected if action == "signin_site" else (True, "模拟登录成功"))
    monkeypatch.setattr(plugin, f"_AutoSignIn{base}", handler)
    site = _site(name="网页站点", cookie="synthetic-cookie", schema="NexusPhp")
    assert getattr(plugin, action)(site).success is True
    handler.assert_called_once_with(site)
    plugin.chain.run_module.assert_not_called()


@pytest.mark.parametrize("action", ["signin_site", "login_site"])
def test_dedicated_signin_and_login_handlers_keep_priority(plugin, monkeypatch, action):
    """已有专用签到和登录接口始终优先，防止仅登录回执覆盖真正的签到能力。"""
    handler = SimpleNamespace(signin=Mock(return_value=(True, "签到成功")),
                              login=Mock(return_value=(True, "模拟登录成功")))
    monkeypatch.setattr(plugin, "_AutoSignIn__build_class", Mock(return_value=Mock(return_value=handler)))
    result = getattr(plugin, action)(_site())
    assert result.success is True and result.logged_in is True
    getattr(handler, "signin" if action == "signin_site" else "login").assert_called_once()
    plugin.chain.run_module.assert_not_called()


def _dispatch(method, *, site, raise_exception):
    """将插件链请求交给生产索引模块，传输仍由用例替身完成。"""
    assert method == "test_site" and raise_exception is True
    return IndexerModule.test_site(site)


@pytest.mark.parametrize("domain", ["hddolby.com", "uhddolby.com", "mirror.test"])
@pytest.mark.parametrize("action", ["signin_site", "login_site"])
def test_hddolby_real_adapter_uses_resource_api_and_network_options(plugin, monkeypatch, domain, action):
    """高清杜比新旧域名和资源别名均复用宿主 GET 用户接口及 API Key 认证。"""
    import app.modules.indexer.spider.hddolby as hddolby

    response = _response({"status": 0, "data": [{"id": "42"}]})
    request = Mock(response_manager=Mock(return_value=closing(response)))
    factory = Mock(return_value=request)
    monkeypatch.setattr(hddolby, "RequestUtils", factory)
    monkeypatch.setattr(hddolby, "get_configured_system_config", lambda: None)
    monkeypatch.setattr(hddolby, "get_runtime_setting", lambda key: {"PROXY": {"https": "proxy"}}[key])
    plugin.chain.run_module.side_effect = _dispatch
    result = getattr(plugin, action)(_site(url=f"https://{domain}/"))
    assert result.logged_in is True and result.success is (action == "login_site")
    request.response_manager.assert_called_once_with(
        method="GET", url="https://api.custom.test/api/v1/user/data", allow_redirects=False,
    )
    options = factory.call_args.kwargs
    assert options["headers"]["x-api-key"] == "synthetic-key"
    assert options["ua"] == "AutoSignIn-Test" and options["timeout"] == 25
    assert options["proxies"] == {"https": "proxy"} and "cookies" not in options
    response.close.assert_called_once()


@pytest.mark.parametrize("apikey,token,expected", [
    (" synthetic-key ", "unused-token", "synthetic-key"), (" ", " synthetic-token ", "synthetic-token"),
])
@pytest.mark.parametrize("action", ["signin_site", "login_site"])
def test_piggo_real_adapter_uses_bearer_and_shared_throttle(plugin, monkeypatch, apikey, token, expected, action):
    """猪猪复用实验室 POST JSON、长期令牌优先级、资源 API 地址及共享流控。"""
    import app.modules.indexer.spider.piggo as piggo

    response = _response({"code": 0, "data": {"user": {"id": 42, "enabled": True}}})
    request = Mock(post_res=Mock(return_value=response))
    factory = Mock(return_value=request)
    wait = Mock()
    monkeypatch.setattr(piggo, "RequestUtils", factory)
    monkeypatch.setattr(piggo, "wait_for_site_request", wait)
    monkeypatch.setattr(piggo, "get_runtime_setting", lambda key: {
        "PROXY": {"https": "proxy"}, "USER_AGENT": "Default-UA",
    }[key])
    plugin.chain.run_module.side_effect = _dispatch
    site = _site(name="猪猪", url="https://piggo.me/", schema="Piggo", apikey=apikey, token=token, render=True)
    result = getattr(plugin, action)(site)
    assert result.logged_in is True and result.success is (action == "login_site")
    request.post_res.assert_called_once_with(url="https://api.custom.test/api/v1/me", json={}, allow_redirects=False)
    options = factory.call_args.kwargs
    assert options["headers"]["Authorization"] == f"Bearer {expected}"
    assert options["headers"]["User-Agent"] == "AutoSignIn-Test" and options["timeout"] == 25
    assert options["proxies"] == {"https": "proxy"} and "cookies" not in options
    wait.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize("status,code,data,reason", [
    (401, 401, {}, "令牌"), (429, 429, {}, "限流"),
    (200, 0, {"code": "notice_unread", "notice_gate": {"title": "必读公告"}}, "网页端阅读"),
    (200, 0, {"user": {"id": 42, "enabled": False}}, "禁用"),
])
def test_piggo_real_business_failures_remain_failures(plugin, monkeypatch, status, code, data, reason):
    """猪猪真实协议的内外层错误码和账号状态均通过宿主回传并关闭响应。"""
    import app.modules.indexer.spider.piggo as piggo

    response = _response({"code": code, "data": data}, status)
    request = Mock(post_res=Mock(return_value=response))
    monkeypatch.setattr(piggo, "RequestUtils", Mock(return_value=request))
    monkeypatch.setattr(piggo, "wait_for_site_request", Mock())
    monkeypatch.setattr(piggo, "defer_site_request", Mock())
    monkeypatch.setattr(piggo, "get_runtime_setting", lambda _key: {})
    plugin.chain.run_module.side_effect = _dispatch
    result = plugin.signin_site(_site(name="猪猪", url="https://piggo.me/", schema="Piggo"))
    assert not result.completed and reason in result.message
    plugin.chain.run_module.assert_called_once()
    request.post_res.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize("success", [False, True])
def test_scheduled_signin_and_login_share_api_result_and_history(plugin, monkeypatch, success):
    """正常任务入口保存两类历史并复用 API 回执，失败自动重试，成功归入仅登录。"""
    site = _site()
    data = {}
    plugin.chain.run_module.return_value = SiteConnectionResult(True, success, "APIKEY已过期")
    plugin._sign_sites = [1]
    plugin._login_sites = [1]
    plugin._notify = True
    plugin._retry_keyword = "错误|失败"
    plugin._queue_cnt = 1
    plugin._clean = False
    plugin._auto_cf = 0
    plugin.get_data = Mock(side_effect=lambda key=None: data.get(key) if key else [])
    plugin.save_data = Mock(side_effect=lambda key, value: data.update({key: value}))
    plugin.update_config = Mock()
    plugin.post_message = Mock()
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(get_indexers=lambda: [site]))
    monkeypatch.setattr(plugin, "_AutoSignIn__custom_sites", Mock(return_value=[]))
    plugin.sign_in()
    today = datetime.today().strftime("%Y-%m-%d")
    signin = data[f"签到-{today}"]
    login = data[f"登录-{today}"]
    assert signin["results"]["1"]["success"] is False
    assert signin["results"]["1"]["logged_in"] is success
    assert login["results"]["1"]["success"] is success
    assert signin["retry"] == login["retry"] == ([] if success else [1])
    plugin.chain.run_module.assert_called_once()
    plugin.post_message.assert_called_once()


def test_signin_api_reports_login_separately(plugin, monkeypatch):
    """公开签到接口继续分别返回签到和登录状态，API 访问通过只确认登录。"""
    site = _site()
    monkeypatch.setattr("app.plugins.autosignin.settings", SimpleNamespace(API_TOKEN="unit-test-token"))
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(get_indexer=lambda _domain: site))
    result = plugin.signin_by_domain(site["url"], "unit-test-token")
    assert result.success is False
    assert result.data == {"signin_success": False, "login_success": True}
    plugin.chain.run_module.assert_called_once()
