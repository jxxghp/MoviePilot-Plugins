"""PTZONE 升级后的 POST 签到及结果验证回归。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.result import SiteResult
from app.plugins.autosignin.sites.ptzone import PTZone
from ruamel.yaml import CommentedMap


_LOGIN = '<a href="logout.php">退出</a>'


@pytest.fixture
def http_request(monkeypatch):
    """隔离实际站点请求，保留请求方式和配置供断言。"""
    client = SimpleNamespace(post_res=Mock())
    factory = Mock(return_value=client)
    monkeypatch.setattr("app.plugins.autosignin.sites.ptzone.RequestUtils", factory)
    monkeypatch.setattr("app.plugins.autosignin.sites.ptzone.settings", SimpleNamespace(
        PROXY={"https": "http://proxy.example"}))
    return factory, client


def site_info(**kwargs):
    """生成不包含真实凭据的站点配置。"""
    return CommentedMap(dict(name="PTZONE", url="https://ptzone.xyz/", cookie="uid=test",
                            ua="MoviePilot-Test", timeout=15), **kwargs)


@pytest.mark.parametrize("url", ["https://ptzone.xyz/", "https://www.ptzone.xyz/",
                                 "http://ptzone.xyz:8080/attendance.php"])
def test_dispatches_ptzone_to_post_handler(url):
    """配置首页或签到页都必须命中专用处理器，避免退回通用 GET。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = [PTZone]
    assert plugin._AutoSignIn__build_class(url) is PTZone


@pytest.mark.parametrize("url", ["https://other.example/", "https://ptzone.xyz.example/",
                                 "https://fakeptzone.xyz/"])
def test_does_not_match_other_sites(url):
    """只处理 PTZONE，其他站点继续遵循原有签到方式。"""
    assert not PTZone.match(url)


@pytest.mark.parametrize("url", ["https://ptzone.xyz/", "https://www.ptzone.xyz/attendance.php",
                                 "http://ptzone.xyz:8080/attendance.php?action=old"])
@pytest.mark.parametrize("proxy", [False, True])
@pytest.mark.parametrize("render", [False, True])
def test_posts_attendance_with_site_options(http_request, url, proxy, render):
    """启用仿真也必须提交 POST，并沿用配置地址、Cookie、UA、代理和超时。"""
    factory, client = http_request
    client.post_res.return_value = SimpleNamespace(status_code=200, text=_LOGIN + '<h2>簽到成功</h2>')
    assert PTZone().signin(site_info(url=url, proxy=proxy, render=render)) == (True, "签到成功")
    attendance_url = url.split("/attendance.php")[0].rstrip("/") + "/attendance.php"
    factory.assert_called_once_with(
        cookies="uid=test", ua="MoviePilot-Test", referer=attendance_url,
        proxies={"https": "http://proxy.example"} if proxy else None, timeout=15,
    )
    client.post_res.assert_called_once_with(url=attendance_url, data={})


@pytest.mark.parametrize("page", [
    '<h2>签到成功</h2>',
    '<p>您今天已經簽到過了，請勿重複刷新。</p>',
    '<p>本次簽到獲得 <b>20</b> 個魔力值。</p>',
    '<p>You have already attend, no refresh please.</p>',
])
def test_accepts_only_confirmed_attendance(http_request, page):
    """明确的成功、奖励和重复签到回执可确认完成。"""
    _, client = http_request
    client.post_res.return_value = SimpleNamespace(status_code=200, text=_LOGIN + page)
    assert PTZone().signin(site_info()) == (True, "签到成功")


@pytest.mark.parametrize("page, message", [
    (_LOGIN, "未确认签到结果"),
    (_LOGIN + '<script>alert("签到成功")</script>', "未确认签到结果"),
    (_LOGIN + '<div hidden>签到成功</div>', "未确认签到结果"),
    (_LOGIN + '<p>签到失败</p>', "未确认签到结果"),
    (_LOGIN + '<form method="post" action="attendance.php"><input type="submit" value="立即簽到"></form>'
     '<p>签到成功</p>', "未确认签到结果"),
    ('<input type="password"><p>签到成功</p>', "Cookie已失效"),
    ('<h2>签到成功</h2>', "未识别到登录状态"),
    ('<html><title>Just a moment...</title><p>Checking your browser</p></html>', "Cloudflare"),
    ("", "空页面"),
])
def test_rejects_unconfirmed_pages(http_request, page, message):
    """HTTP 200、登录、待提交表单和隐藏成功提示均不能冒充已签到。"""
    _, client = http_request
    client.post_res.return_value = SimpleNamespace(status_code=200, text=page)
    success, result = PTZone().signin(site_info())
    assert not success and message in result


@pytest.mark.parametrize("status", [302, 403, 404, 500])
def test_rejects_http_errors(http_request, status):
    """错误响应中的成功文案不构成有效回执。"""
    _, client = http_request
    client.post_res.return_value = SimpleNamespace(status_code=status, text=_LOGIN + '<h2>签到成功</h2>')
    assert PTZone().signin(site_info()) == (False, f"签到失败，状态码：{status}")


def test_rejects_missing_response_and_uses_default_timeout(http_request):
    """连接失败保留失败，未配置超时时使用插件默认值。"""
    factory, client = http_request
    client.post_res.return_value = None
    assert PTZone().signin(site_info(timeout=None)) == (False, "签到失败，无法打开网站")
    assert factory.call_args.kwargs["timeout"] == 60


@pytest.mark.parametrize("missing", ["url", "cookie"])
def test_missing_config_does_not_send_request(http_request, missing):
    """缺少地址或凭据时不提交匿名签到请求。"""
    factory, _ = http_request
    assert PTZone().signin(site_info(**{missing: ""})) == (False, "签到失败，未配置站点地址或Cookie")
    factory.assert_not_called()


@pytest.mark.parametrize("signed", [False, True])
def test_plugin_keeps_signin_separate_from_login(http_request, monkeypatch, signed):
    """插件入口必须执行 POST；仅确认登录时 API 结果仍不能报告签到成功。"""
    _, client = http_request
    client.post_res.return_value = SimpleNamespace(
        status_code=200, text=_LOGIN + ('<h2>簽到成功</h2>' if signed else ""))
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = [PTZone]
    stats = SimpleNamespace(success=Mock(), fail=Mock())
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=stats))
    homepage = SimpleNamespace(get_res=Mock(return_value=SimpleNamespace(status_code=200, text=_LOGIN)))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=homepage))
    result = plugin.signin_site(site_info())
    assert result == SiteResult("PTZONE", "签到成功" if signed else "登录成功，签到未确认", signed, True)
    client.post_res.assert_called_once_with(url="https://ptzone.xyz/attendance.php", data={})
    assert homepage.get_res.call_count == (0 if signed else 1)
    if not signed:
        homepage.get_res.assert_called_once_with(url="https://ptzone.xyz/")
    stats.success.assert_called_once()
    stats.fail.assert_not_called()
