"""签到不能由已登录、脚本文案、错误状态或缺失按钮推断成功。"""

import json
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.result import (
    SiteResult,
    has_login_evidence,
    has_signin_evidence,
)
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.plugins.autosignin.sites.btschool import BTSchool
from app.plugins.autosignin.sites.hares import Hares
from app.plugins.autosignin.sites.hdchina import HDChina
from app.plugins.autosignin.sites.hdsky import HDSky
from app.plugins.autosignin.sites.hdupt import HDUpt
from app.plugins.autosignin.sites.mteam import MTorrent
from app.plugins.autosignin.sites.opencd import Opencd
from app.plugins.autosignin.sites.pterclub import PTerClub
from app.plugins.autosignin.sites.rousipro import RousiPro
from app.plugins.autosignin.sites.yema import YemaPT

_LOGIN = '<a href="logout.php">退出</a>'
_SIGNED = _LOGIN + '<span>今日已签到</span>'


def site_info(**overrides):
    """生成测试站点，所有 HTTP 和浏览器调用均由用例替换。"""
    return {"name": "测试站", "url": "https://pt.example/", "cookie": "uid=test",
            "ua": "test", "timeout": 15, "render": False, "proxy": False, **overrides}


def response(text="", status=200, payload=None):
    """构造可读文本及 JSON 的站点响应，保留 HTTP 状态码与 Cookie 接口。"""
    if payload is not None:
        text = json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(status_code=status, text=text, content=text.encode(),
                           json=lambda: payload, cookies=SimpleNamespace(get_dict=lambda: {"hdchina": "test"}))


@pytest.mark.parametrize("render", [False, True])
@pytest.mark.parametrize("page", [
    _LOGIN,
    _LOGIN + '<a href="attendance.php">签到</a>',
    _LOGIN + '<form action="attendance.php"><input type="submit" value="立即签到"></form>',
    _LOGIN + '<script>const message="签到成功";</script>',
    _LOGIN + '<!-- 今日已签到 --><style>.signed:after{content:"签到成功"}</style>',
    _LOGIN + '<template><p>签到成功</p></template>',
    _LOGIN + '<span hidden>签到成功</span>',
    _LOGIN + '<span style="display: none">今日已签到</span>',
    '<html><head><title>签到成功</title></head><body>' + _LOGIN + '</body></html>',
    _LOGIN + '<textarea>签到成功</textarea>',
    _LOGIN + '<input type="text" value="签到成功">',
    _LOGIN + '<p>未签到</p><span>今日已签到</span>',
    _LOGIN + '<p>签到成功后可获得奖励</p>',
    _LOGIN + '<p>未签到成功</p>',
    '<form><input type="password"></form><p>签到成功</p>',
    '<html><title>Just a moment...</title><p>Checking your browser</p></html>',
    "",
])
def test_generic_requires_signin_evidence(monkeypatch, render, page):
    """登录、表单、模板、失败页和 Cloudflare 页面都不能返回签到成功。"""
    requests = Mock(return_value=SimpleNamespace(get_res=Mock(return_value=response(page))))
    browser = Mock(return_value=SimpleNamespace(get_page_source=Mock(return_value=page)))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", requests)
    monkeypatch.setattr("app.plugins.autosignin.PlaywrightHelper", browser)
    result = AutoSignIn._AutoSignIn__signin_base(site_info(render=render))
    assert result.success is False
    assert result.logged_in is (_LOGIN in page)
    if result.logged_in:
        assert result.message == "登录成功，签到未确认"
    else:
        assert "失败" in result.message


@pytest.mark.parametrize("render", [False, True])
@pytest.mark.parametrize("page", [
    _SIGNED,
    _SIGNED + '<nav><a href="attendance.php">签到</a></nav><p>昨天未签到</p>',
    _LOGIN + '<h2>签到成功</h2>',
    _LOGIN + '<p>您今天已经签到过了，请勿重复刷新。</p>',
    _LOGIN + '<p>本次签到获得 <b>20</b> 个魔力值。</p>',
    _LOGIN + '<span>今日已簽到</span>',
    _LOGIN + '<span>签到已得20魔力</span>',
    _LOGIN + '<p>You have already attend, no refresh please.</p>',
    _LOGIN + '<p>You have already attended <b>20</b> days, Continuous <b>2</b> days, this time you will get <b>10</b> bonus.</p>',
])
def test_generic_preserves_confirmed_results(monkeypatch, render, page):
    """当前用户的完成标签和明确奖励回执仍能被普通请求及浏览器识别。"""
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=SimpleNamespace(
        get_res=Mock(return_value=response(page)))))
    monkeypatch.setattr("app.plugins.autosignin.PlaywrightHelper", Mock(return_value=SimpleNamespace(
        get_page_source=Mock(return_value=page))))
    assert AutoSignIn._AutoSignIn__signin_base(site_info(render=render)) == SiteResult("测试站", "签到成功", True, True)


@pytest.mark.parametrize("status", [302, 403, 404, 500])
def test_http_error_falls_back_to_login_without_claiming_signin(monkeypatch, status):
    """签到接口错误时访问首页保号，首页登录成功仍不能冒充签到完成。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = []
    stats = SimpleNamespace(success=Mock(), fail=Mock())
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=stats))
    request = SimpleNamespace(get_res=Mock(side_effect=[response(_SIGNED, status), response(_LOGIN)]))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=request))
    result = plugin.signin_site(site_info())
    assert result == SiteResult("测试站", "登录成功，签到未确认", False, True)
    assert [call.kwargs["url"] for call in request.get_res.call_args_list] == [
        "https://pt.example/attendance.php", "https://pt.example/",
    ]
    stats.success.assert_called_once()
    stats.fail.assert_not_called()


@pytest.mark.parametrize("page", [
    _LOGIN,
    '<shark-icon-button href="logout.php">退出</shark-icon-button>',
    '<button onclick="logout()">退出</button>',
    '<form action="/signout"><button>退出</button></form>',
    '<button>退出登录</button>',
    '<a role="button">Sign out</a>',
    _LOGIN + '<div hidden><input type="password"></div>',
])
def test_visible_user_controls_confirm_login(page):
    """退出按钮、新版模板及隐藏登录弹窗不应导致已登录站点误判失效。"""
    assert has_login_evidence(page)


@pytest.mark.parametrize("page", [
    "", '<p>登录成功后可以签到</p>',
    '<script>const logout = \'<a href="logout.php">退出</a>\';</script>',
    '<template>' + _LOGIN + '</template>',
    '<div hidden>' + _LOGIN + '</div>',
    _LOGIN + '<input type="password">',
    _LOGIN + '<input type="PASSWORD">',
])
def test_public_or_login_pages_do_not_confirm_login(page):
    """登录页、公开文案、隐藏控件不能用作保号访问成功的证据。"""
    assert not has_login_evidence(page)


@pytest.mark.parametrize("render", [False, True])
def test_unrecognized_attendance_page_checks_homepage_with_same_options(monkeypatch, render):
    """签到页不带用户导航时，使用同一 Cookie、UA、代理和超时访问首页确认登录。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = []
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock())
    request = SimpleNamespace(get_res=Mock(side_effect=[response("签到页面"), response(_LOGIN)]))
    browser = SimpleNamespace(get_page_source=Mock(side_effect=["签到页面", _LOGIN]))
    requests = Mock(return_value=request)
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", requests)
    monkeypatch.setattr("app.plugins.autosignin.PlaywrightHelper", Mock(return_value=browser))
    monkeypatch.setattr("app.plugins.autosignin.settings", SimpleNamespace(
        PROXY={"https": "http://proxy.example"}, PROXY_SERVER={"server": "http://proxy.example"}))
    result = plugin.signin_site(site_info(url="https://pt.example/tracker/attendance.php?action=sign", render=render, proxy=True))
    assert result == SiteResult("测试站", "登录成功，签到未确认", False, True)
    getter = browser.get_page_source if render else request.get_res
    assert getter.call_args.kwargs["url"] == "https://pt.example/tracker/"
    options = getter.call_args.kwargs if render else requests.call_args.kwargs
    assert options["cookies"] == "uid=test"
    assert options["ua"] == "test" and options["timeout"] == 15
    assert options["proxies"] == ({"server": "http://proxy.example"} if render else {"https": "http://proxy.example"})


@pytest.mark.parametrize("render", [False, True])
def test_confirmed_login_does_not_need_second_request(monkeypatch, render):
    """签到页已有登录凭据时完成保号访问，不增加首页请求。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = []
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock())
    request = SimpleNamespace(get_res=Mock(return_value=response(_LOGIN)))
    browser = SimpleNamespace(get_page_source=Mock(return_value=_LOGIN))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=request))
    monkeypatch.setattr("app.plugins.autosignin.PlaywrightHelper", Mock(return_value=browser))
    assert plugin.signin_site(site_info(render=render)).logged_in
    getter = browser.get_page_source if render else request.get_res
    getter.assert_called_once()


@pytest.mark.parametrize("page, error", [
    ('<form><input type="password"></form>', "Cookie已失效"),
    ("维护中", "未识别到登录状态"),
    ('<html><title>Just a moment...</title><p>Checking your browser</p></html>', "Cloudflare"),
    ("", "空页面"),
    ('<template>' + _LOGIN + '</template>', "未识别到登录状态"),
])
@pytest.mark.parametrize("render", [False, True])
def test_login_fallback_must_verify_homepage(monkeypatch, render, page, error):
    """首页也没有登录凭据时保留失败，不把可访问的公开页面当作保号成功。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = []
    stats = SimpleNamespace(success=Mock(), fail=Mock())
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=stats))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=SimpleNamespace(
        get_res=Mock(side_effect=[response("", 404), response(page)]))))
    monkeypatch.setattr("app.plugins.autosignin.PlaywrightHelper", Mock(return_value=SimpleNamespace(
        get_page_source=Mock(side_effect=["404 Not Found", page]))))
    result = plugin.signin_site(site_info(render=render))
    assert not result.success and not result.logged_in and not result.completed
    assert error in result.message
    if error != "Cookie已失效":
        assert "Cookie已失效" not in result.message
    stats.success.assert_not_called()
    stats.fail.assert_called_once()


@pytest.mark.parametrize("status", [302, 403, 404, 468, 500])
def test_login_rejects_http_error_even_with_user_navigation(monkeypatch, status):
    """错误响应中出现退出导航不能证明本次首页访问成功。"""
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=SimpleNamespace(
        get_res=Mock(return_value=response(_LOGIN, status)))))
    assert AutoSignIn._AutoSignIn__login_base(site_info())[0] is False


@pytest.mark.parametrize("signin_message", ["签到失败，未确认签到结果", "签到失败，Cookie已失效", "签到失败，验证码错误"])
def test_dedicated_login_recovers_visit_but_api_keeps_signin_false(monkeypatch, signin_message):
    """专用签到失败后可用登录接口确认访问，签到 API 分别返回两种状态且统计只累计一次。"""
    plugin = object.__new__(AutoSignIn)
    login = Mock(return_value=(True, "模拟登录成功"))
    handler = Mock(spec=["signin", "login"], return_value=SimpleNamespace(
        signin=Mock(return_value=(False, signin_message)), login=login))
    monkeypatch.setattr(plugin, "_AutoSignIn__build_class", Mock(return_value=handler))
    stats = SimpleNamespace(success=Mock(), fail=Mock())
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=stats))
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", Mock(return_value=SimpleNamespace(
        get_indexer=Mock(return_value=site_info()))))
    monkeypatch.setattr("app.plugins.autosignin.settings.API_TOKEN", "test")
    result = plugin.signin_by_domain("https://pt.example/", "test")
    assert result.success is False
    assert result.data == {"signin_success": False, "login_success": True}
    assert "登录成功，签到未确认" in result.message and "失败" not in result.message
    login.assert_called_once()
    stats.success.assert_called_once()
    stats.fail.assert_not_called()


def test_login_only_adapter_is_not_signin_success():
    """馒头等仅模拟登录的适配器明确记录已登录，不能成为签到成功。"""
    result = AutoSignIn._site_result("馒头", True, "模拟登录成功", "签到")
    assert result == SiteResult("馒头", "模拟登录成功（未执行签到）", False, True)
    assert result.completed


@pytest.mark.parametrize("login_message, expected_message", [
    ("访问失败，接口未确认结果", "访问失败，接口未确认结果"),
    ("模拟登录失败，Cookie已失效", "访问失败，接口未确认结果；模拟登录失败，Cookie已失效"),
])
def test_login_fallback_preserves_distinct_errors_without_repeating_identical_errors(
        monkeypatch, login_message, expected_message):
    """普通站点仍执行登录回退，相同错误只保留一次，不同原因均保留。"""
    plugin = object.__new__(AutoSignIn)
    login = Mock(return_value=(False, login_message))
    handler = Mock(spec=["signin", "login"], return_value=SimpleNamespace(
        signin=Mock(return_value=(False, "访问失败，接口未确认结果")), login=login))
    monkeypatch.setattr(plugin, "_AutoSignIn__build_class", Mock(return_value=handler))
    stats = SimpleNamespace(success=Mock(), fail=Mock())
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=stats))

    result = plugin.signin_site(site_info())

    assert result == SiteResult("测试站", expected_message, False, False)
    login.assert_called_once()
    stats.success.assert_not_called()
    stats.fail.assert_called_once()


@pytest.mark.parametrize("action", ["signin_site", "login_site"])
@pytest.mark.parametrize("reply, completed, message", [
    (response(payload={"code": 0}), True, "模拟登录成功"),
    (response(payload={"code": 403}), False, "模拟登录失败，接口未确认访问时间更新"),
    (response(status=401), False, "模拟登录失败，状态码：401"),
    (None, False, "模拟登录失败，无法打开网站"),
])
def test_mteam_visit_calls_shared_endpoint_once(monkeypatch, action, reply, completed, message):
    """馒头的签到与登录共用访问接口，每轮只请求一次并保留真实失败或登录状态。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = [MTorrent]
    stats = SimpleNamespace(success=Mock(), fail=Mock())
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=stats))
    post = Mock(return_value=reply)
    monkeypatch.setattr("app.plugins.autosignin.sites.mteam.RequestUtils", Mock(return_value=SimpleNamespace(
        post_res=post)))

    result = getattr(plugin, action)(site_info(name="馒头", url="https://kp.m-team.cc/", token="test-token"))

    post.assert_called_once_with(url="https://api.m-team.cc/api/member/updateLastBrowse")
    assert result.completed is completed
    assert result.logged_in is completed
    assert result.success is (completed and action == "login_site")
    assert result.message == (message + "（未执行签到）" if completed and action == "signin_site" else message)
    if completed:
        stats.success.assert_called_once()
        stats.fail.assert_not_called()
    else:
        stats.success.assert_not_called()
        stats.fail.assert_called_once()


def test_btschool_unconfirmed_attendance_preserves_login_visit(monkeypatch):
    """学校适配器没有独立登录接口时，回退首页仍可确认登录保号。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = [BTSchool]
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock())
    monkeypatch.setattr(BTSchool, "get_page_source", Mock(return_value=_LOGIN))
    request = SimpleNamespace(get_res=Mock(return_value=response(_LOGIN)))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=request))
    assert plugin.signin_site(site_info(url="https://pt.btschool.club/")) == SiteResult(
        "测试站", "登录成功，签到未确认", False, True)
    request.get_res.assert_called_once_with(url="https://pt.btschool.club/")


@pytest.mark.parametrize("url", ["https://pt.example/", "https://pt.example/tracker", "https://pt.example/index.php?view=user"])
def test_login_preserves_configured_non_attendance_url(monkeypatch, url):
    """仅去掉签到页面及其查询参数，其他自定义站点入口保持原样。"""
    request = SimpleNamespace(get_res=Mock(return_value=response(_LOGIN)))
    monkeypatch.setattr("app.plugins.autosignin.RequestUtils", Mock(return_value=request))
    assert AutoSignIn._AutoSignIn__login_base(site_info(url=url)) == (True, "模拟登录成功")
    request.get_res.assert_called_once_with(url=url)


@pytest.mark.parametrize("page", [
    '<script>const html=\'<a href="attendance.php">今日已签到</a>\';</script>',
    '<!-- <a href="attendance.php">今日已签到</a> -->',
    '<div hidden><a href="attendance.php">今日已签到</a></div>',
    '<a onclick="alert(\'已签到\')">签到</a>',
    '<p>未签到成功</p>',
])
def test_site_patterns_ignore_inactive_success_markup(page):
    """站点专用正则仍保留 DOM 标签匹配能力，但不能命中隐藏模板。"""
    assert not _ISiteSigninHandler.sign_in_result(page, ['已签到'])
    assert _ISiteSigninHandler.sign_in_result('<a href="attendance.php">今日已签到</a>',
                                               ['<a href="attendance.php">今日已签到</a>'])


@pytest.mark.parametrize("status", [403, 500])
def test_site_page_loader_rejects_error_responses(monkeypatch, status):
    """站点适配器读取错误页时不能把其中的文本当作正常接口回执。"""
    monkeypatch.setattr("app.plugins.autosignin.sites.RequestUtils", Mock(return_value=SimpleNamespace(
        get_res=Mock(return_value=response(_SIGNED, status)))))
    assert _ISiteSigninHandler.get_page_source("https://pt.example", "test", "test", False, False) == ""


@pytest.mark.parametrize("page", [_LOGIN, '<html>维护中 2026</html>', _LOGIN + '<script>const done="已签到"</script>'])
def test_btschool_missing_button_is_not_already_signed(monkeypatch, page):
    """学校首页或签到响应缺少按钮，不代表已签到；错误页也必须失败。"""
    monkeypatch.setattr(BTSchool, "get_page_source", Mock(return_value=page))
    assert BTSchool().signin(site_info())[0] is False


def test_btschool_confirms_result_after_request(monkeypatch):
    """学校需要在签到请求后读到明确已签到状态。"""
    page = Mock(side_effect=[_LOGIN + '<a href="index.php?action=addbonus">每日签到</a>', _SIGNED])
    monkeypatch.setattr(BTSchool, "get_page_source", page)
    assert BTSchool().signin(site_info()) == (True, "签到成功")
    assert page.call_count == 2


@pytest.mark.parametrize("handler, module, payload, success", [
    (Hares, "hares", {"code": 0, "msg": "签到成功"}, True),
    (Hares, "hares", {"code": 1, "msg": "您今天已经签到过了"}, True),
    (Hares, "hares", {"code": 1, "msg": "CSRF 错误"}, False),
    (Hares, "hares", {"code": 403, "msg": "权限不足"}, False),
    (Hares, "hares", {"code": False}, False),
    (PTerClub, "pterclub", {"status": "1"}, True),
    (PTerClub, "pterclub", {"status": "0", "message": "您今天已经签到过了，请勿重复刷新。"}, True),
    (PTerClub, "pterclub", {"status": "0", "message": "请先登录"}, False),
    (PTerClub, "pterclub", {"status": "error", "message": "签到失败"}, False),
])
def test_business_errors_are_not_duplicate_signins(monkeypatch, handler, module, payload, success):
    """猫站和白兔仅接受明确业务成功或重复签到信息，其他错误不能成功。"""
    if handler is Hares:
        monkeypatch.setattr(handler, "get_page_source", Mock(return_value=_LOGIN))
        monkeypatch.setattr(f"app.plugins.autosignin.sites.{module}.RequestUtils", Mock(return_value=SimpleNamespace(
            get_res=Mock(return_value=response(payload=payload)))))
    else:
        monkeypatch.setattr(handler, "get_page_source", Mock(return_value=json.dumps(payload)))
    assert handler().signin(site_info())[0] is success


@pytest.mark.parametrize("state, success", [("success", True), ("error", False), ("false", False), (False, False), (True, False)])
@pytest.mark.parametrize("handler, module", [(HDChina, "hdchina"), (Opencd, "opencd")])
def test_state_string_must_equal_success(monkeypatch, handler, module, state, success):
    """非空 error/false 字符串和非约定布尔值都不能作为 state=success 使用。"""
    request = SimpleNamespace(
        get_res=Mock(return_value=response(_LOGIN + '<meta name="x-csrf" content="test">')),
        post_res=Mock(return_value=response(payload={"state": state})),
    )
    monkeypatch.setattr(f"app.plugins.autosignin.sites.{module}.RequestUtils", Mock(return_value=request))
    if handler is Opencd:
        form = '<form id="frmSignin"><img src="code.png"><input name="imagehash" value="test"></form>'
        # 签到日志链接可能始终存在，不能仅凭该链接跳过真正签到请求。
        monkeypatch.setattr(handler, "get_page_source", Mock(side_effect=[
            _LOGIN + '<a href="/plugin_sign-in.php?cmd=show-log">签到日志</a>', form,
        ]))
        monkeypatch.setattr("app.plugins.autosignin.sites.opencd.OcrHelper", Mock(return_value=SimpleNamespace(
            get_captcha_text=Mock(return_value="ABCDEF"))))
    assert handler().signin(site_info(cookie="hdchina=test"))[0] is success
    request.post_res.assert_called_once()


@pytest.mark.parametrize("payload, success", [({"success": True}, True), ({"success": "false"}, False),
                                            ({"success": "error"}, False), ({"success": False}, False)])
def test_hdsky_boolean_result_is_not_string_truthiness(monkeypatch, payload, success):
    """天空签到接口严格读取布尔值，字符串 false 不能冒充成功。"""
    monkeypatch.setattr(HDSky, "get_page_source", Mock(return_value=_LOGIN))
    request = SimpleNamespace(post_res=Mock(side_effect=[
        response(payload={"success": True, "code": "image-hash"}),
        response(payload={**payload, "message": "invalid_imagehash"}),
    ]))
    monkeypatch.setattr("app.plugins.autosignin.sites.hdsky.RequestUtils", Mock(return_value=request))
    monkeypatch.setattr("app.plugins.autosignin.sites.hdsky.OcrHelper", Mock(return_value=SimpleNamespace(
        get_captcha_text=Mock(return_value="ABCDEF"))))
    assert HDSky().signin(site_info())[0] is success


@pytest.mark.parametrize("body, checked_page, success", [
    ("<html>错误 500</html>", _SIGNED, False),
    (".23", _LOGIN, False),
    (".23", _LOGIN + '<span id="yiqiandao">已签到</span>', True),
])
def test_hdupt_numeric_response_requires_state_readback(monkeypatch, body, checked_page, success):
    """HDU 仅在纯数字回执后回读到完成状态才成功，页面里的任意数字不是证据。"""
    monkeypatch.setattr(HDUpt, "get_page_source", Mock(side_effect=[_LOGIN, body, checked_page]))
    assert HDUpt().signin(site_info())[0] is success


@pytest.mark.parametrize("payload, success", [({"success": True}, True), ({"success": "false"}, False)])
def test_yema_requires_boolean_success(monkeypatch, payload, success):
    """Yema 的成功字段必须是 JSON 布尔真。"""
    monkeypatch.setattr("app.plugins.autosignin.sites.yema.RequestUtils", Mock(return_value=SimpleNamespace(
        get_res=Mock(return_value=response(payload=payload)))))
    assert YemaPT().signin(site_info())[0] is success


@pytest.mark.parametrize("message, success", [("权限不足", False), ("", False), ("您今天已经签到过了", True)])
def test_rousi_error_code_alone_is_not_a_duplicate(monkeypatch, message, success):
    """Rousi 的通用 400/code=1 必须附带已签到证据才能作为重复签到成功。"""
    monkeypatch.setattr("app.plugins.autosignin.sites.rousipro.RequestUtils", Mock(return_value=SimpleNamespace(
        post_res=Mock(return_value=response(status=400, payload={"code": 1, "message": message})))))
    assert RousiPro().signin(site_info(apikey="test"))[0] is success


@pytest.mark.parametrize("code, success", [(0, True), ("0", True), (403, False), (False, False)])
def test_mteam_visit_requires_business_success(monkeypatch, code, success):
    """没有签到功能的馒头仍只报告模拟登录，HTTP 200 内的错误也不能成功。"""
    monkeypatch.setattr("app.plugins.autosignin.sites.mteam.RequestUtils", Mock(return_value=SimpleNamespace(
        post_res=Mock(return_value=response(payload={"code": code})))))
    result = MTorrent().signin(site_info())
    assert result[0] is success
    assert "签到成功" not in result[1]


def test_reward_rules_are_not_current_attendance():
    """通用奖励规则不等同于本次实际获得奖励。"""
    assert not has_signin_evidence("首次签到获得 10 个魔力值；每次连续签到可额外获得 5 个魔力值。")


@pytest.mark.parametrize("state, message, success", [
    (False, "签到成功", False), (False, "今日已签到", False),
    (True, "", False), (None, None, False),
    (True, "签到成功", True), (True, "今日已签到", True),
])
def test_result_boolean_reaches_api_and_site_statistics(monkeypatch, state, message, success):
    """处理器的布尔结果必须传到 API 和站点统计，失败文案中的成功字样不能翻转状态。"""
    plugin = object.__new__(AutoSignIn)
    handler = Mock(return_value=SimpleNamespace(signin=Mock(return_value=(state, message))))
    monkeypatch.setattr(plugin, "_AutoSignIn__build_class", Mock(return_value=handler))
    monkeypatch.setattr(plugin, "_login_result", Mock(return_value=SiteResult("测试站", "登录失败", False)))
    stats = SimpleNamespace(success=Mock(), fail=Mock())
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=stats))
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", Mock(return_value=SimpleNamespace(
        get_indexer=Mock(return_value=site_info()))))
    monkeypatch.setattr("app.plugins.autosignin.settings.API_TOKEN", "test")

    result = plugin.signin_by_domain("https://pt.example/", "test")

    assert result.success is success
    assert stats.success.call_count == int(success)
    assert stats.fail.call_count == int(not success)
    if not success:
        assert "签到失败" in result.message


def test_api_unknown_site_is_not_success(monkeypatch):
    """不存在的站点不能用 success=true 响应。"""
    plugin = object.__new__(AutoSignIn)
    monkeypatch.setattr("app.plugins.autosignin.settings.API_TOKEN", "test")
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", Mock(return_value=SimpleNamespace(
        get_indexer=Mock(return_value=None))))
    assert plugin.signin_by_domain("https://missing.example/", "test").success is False


@pytest.mark.parametrize("module_name, class_name", [("52pt", "Pt52"), ("chdbits", "CHDBits")])
@pytest.mark.parametrize("checked_page, success", [
    (_LOGIN + "答对即可获得20点魔力值", False),
    (_LOGIN + "今天已经签过到了", True),
])
def test_quiz_reward_text_requires_completed_state(monkeypatch, module_name, class_name, checked_page, success):
    """答题奖励说明也包含数字与魔力值，必须回读到已完成签到的状态。"""
    module = import_module(f"app.plugins.autosignin.sites.{module_name}")
    handler = getattr(module, class_name)
    monkeypatch.setattr(handler, "get_page_source", Mock(return_value=checked_page))
    monkeypatch.setattr(module, "RequestUtils", Mock(return_value=SimpleNamespace(
        post_res=Mock(return_value=response("答对即可获得20点魔力值")))))
    kwargs = {"questionid": "1", "choice": ["2"], "site": "测试", "site_cookie": "test", "ua": "test", "proxy": False}
    if module_name == "52pt":
        kwargs["timeout"] = 15
    assert getattr(handler(), f"_{class_name}__signin")(**kwargs)[0] is success
