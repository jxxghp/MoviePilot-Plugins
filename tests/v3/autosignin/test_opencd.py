"""皇后签到的 CSRF 会话、配置地址与真实失败原因回归。"""

import json
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs

import pytest
from requests import Response
from ruamel.yaml import CommentedMap

from app.plugins.autosignin.sites import opencd
from app.sdk.network import RequestUtils


def _response(text="", status=200, payload=None, cookies=None):
    """构造真实响应对象，使 HTTP 403 等失败状态保留 requests 的假值语义。"""
    response = Response()
    response.status_code = status
    response.encoding = "utf-8"
    response._content = (json.dumps(payload, ensure_ascii=False) if payload is not None else text).encode()
    response.cookies.update(cookies or {})
    return response


def _signin_form():
    """重放含一次性 CSRF 字段和验证码参数的签到表单。"""
    return """
    <form id="frmSignin" action="plugin_sign-in.php?cmd=signin" enctype="multipart/form-data">
      <input name="csrf_token" value="form-csrf-token">
      <input name="imagehash" value="image-hash">
      <input name="imagestring">
      <img src="image.php?action=regimage&amp;imagehash=image-hash">
    </form>
    """


def _form_revision(csrf_token: str, image_hash: str):
    """构造指定 token 的签到表单，用于确认每轮重试都取到新表单。"""
    return (
        f'<form id="frmSignin" action="plugin_sign-in.php?cmd=signin">'
        f'<input name="csrf_token" value="{csrf_token}">'
        f'<input name="imagehash" value="{image_hash}">'
        f'<input name="imagestring">'
        f'<img src="image.php?action=regimage&amp;imagehash={image_hash}"></form>'
    )


@pytest.fixture
def signin_context(monkeypatch):
    """隔离站点、OCR 和等待，保留页面响应新 Cookie 与提交结果。"""
    site = CommentedMap(
        name="皇后", url="https://open.cd/", cookie="uid=test; pass=a=b; c_csrf=old-cookie",
        ua="MoviePilot-Test", proxy=True, render=False, timeout=15,
    )
    page = _response(_signin_form(), cookies={"c_csrf": "new-cookie", "session": "new-session"})
    request = SimpleNamespace(
        get_res=Mock(return_value=page),
        post_res=Mock(return_value=_response(payload={"state": "success"})),
    )
    factory = Mock(return_value=request)
    homepage = Mock(return_value='<a href="logout.php">退出</a><a href="plugin_sign-in.php">签到</a>')
    ocr = Mock(return_value="ABCDEF")
    logger = Mock()
    monkeypatch.setattr(opencd, "RequestUtils", factory)
    monkeypatch.setattr(opencd.Opencd, "get_page_source", homepage)
    monkeypatch.setattr(opencd, "OcrHelper", Mock(return_value=SimpleNamespace(get_captcha_text=ocr)))
    monkeypatch.setattr(opencd.time, "sleep", Mock())
    monkeypatch.setattr(opencd, "logger", logger)
    monkeypatch.setattr(opencd, "settings", SimpleNamespace(PROXY={"https": "http://proxy.test"}))
    return SimpleNamespace(
        site=site, page=page, request=request, factory=factory, homepage=homepage, ocr=ocr, logger=logger,
    )


@pytest.mark.parametrize("base_url", [
    "https://open.cd/", "https://www.open.cd", "http://open.cd:8080/index.php",
])
@pytest.mark.parametrize("render", [False, True])
def test_signin_preserves_page_csrf_session_and_configured_origin(signin_context, base_url, render):
    """同次页面的 token 与新 Cookie 必须一起提交，并保留配置及认证 Cookie。"""
    context = signin_context
    context.site.update(url=base_url, render=render)
    timeline = Mock()
    timeline.attach_mock(context.request.get_res, "page")
    timeline.attach_mock(context.ocr, "ocr")
    timeline.attach_mock(context.request.post_res, "post")

    assert opencd.Opencd().signin(context.site) == (True, "签到成功")

    origin = base_url.split("/index.php")[0].rstrip("/")
    signin_url = origin + "/plugin_sign-in.php"
    assert context.homepage.call_args.kwargs["url"] == base_url
    context.request.get_res.assert_called_once_with(url=signin_url)
    assert [item[0] for item in timeline.mock_calls] == ["page", "ocr", "post"]
    context.request.post_res.assert_called_once_with(
        url=signin_url + "?cmd=signin",
        data={"csrf_token": "form-csrf-token", "imagehash": "image-hash", "imagestring": "ABCDEF"},
    )
    options = context.factory.call_args.kwargs
    cookies = dict(item.strip().split("=", 1) for item in options["cookies"].split(";"))
    assert cookies == {"uid": "test", "pass": "a=b", "c_csrf": "new-cookie", "session": "new-session"}
    assert options["ua"] == "MoviePilot-Test"
    assert options["proxies"] == {"https": "http://proxy.test"}
    assert options["timeout"] == 15
    assert options["referer"] == signin_url
    assert context.factory.call_args_list[0].kwargs["cookies"] == context.site["cookie"]
    assert context.factory.call_args_list[0].kwargs["timeout"] == 15
    context.ocr.assert_called_once_with(
        image_url=origin + "/image.php?action=regimage&imagehash=image-hash",
        cookie=options["cookies"], ua="MoviePilot-Test",
    )
    assert context.site["cookie"] == "uid=test; pass=a=b; c_csrf=old-cookie"


@pytest.mark.parametrize("response, expected, submits", [
    (None, "签到失败，签到接口请求失败：未收到响应", 1),
    (_response("CSRF token verification failed", 403),
     "签到失败，签到接口返回 HTTP 403：CSRF token verification failed", 1),
    (_response("<html><body>Service unavailable</body></html>", 503),
     "签到失败，签到接口返回 HTTP 503：Service unavailable", 1),
    (_response(payload={"state": "false", "msg": "验证码错误"}),
     "签到失败，签到接口返回 HTTP 200：验证码错误", 3),
    (_response("<html>Unexpected response</html>"), "签到失败，签到接口响应不是有效JSON（HTTP 200）", 1),
    (_response(payload=[{"state": "success"}]), "签到失败，签到接口响应格式异常（HTTP 200）", 1),
])
def test_submission_failures_report_actual_reason(signin_context, response, expected, submits):
    """提交失败明确区分 HTTP、业务与响应格式；只有验证码错误才换表重试。"""
    context = signin_context
    context.request.post_res.return_value = response

    assert opencd.Opencd().signin(context.site) == (False, expected)

    context.logger.error.assert_called_once_with(f"皇后 {expected}")
    assert context.request.post_res.call_count == submits
    assert "未获取到验证码" not in expected


@pytest.mark.parametrize("field", ["csrf_token", "imagehash", "img"])
def test_incomplete_form_does_not_run_ocr_or_submit(signin_context, field):
    """关键参数缺失时返回解析原因，不抛索引异常或发送不完整表单。"""
    context = signin_context
    context.request.get_res.return_value = _response(_signin_form().replace(field, "missing-field"))

    result = opencd.Opencd().signin(context.site)

    assert result[0] is False
    assert "签到参数" in result[1]
    context.ocr.assert_not_called()
    context.request.post_res.assert_not_called()


@pytest.mark.parametrize("response, expected", [
    (None, "签到失败，签到页面请求失败：未收到响应"),
    (_response("Forbidden", 403), "签到失败，签到页面返回 HTTP 403：Forbidden"),
])
def test_page_request_failure_keeps_http_reason(signin_context, response, expected):
    """页面请求失败保留其 HTTP 原因，不开始验证码或提交阶段。"""
    context = signin_context
    context.request.get_res.return_value = response

    assert opencd.Opencd().signin(context.site) == (False, expected)

    context.ocr.assert_not_called()
    context.request.post_res.assert_not_called()


@pytest.mark.parametrize("captcha", ["", "ABCDE", "ABCDEFG"])
def test_invalid_captcha_is_not_submitted(signin_context, captcha):
    """每张图最多识别四次；读不出就换新图，识别总次数封顶后不再提交。"""
    context = signin_context
    context.ocr.return_value = captcha

    assert opencd.Opencd().signin(context.site) == (False, "签到失败：未获取到验证码")

    assert context.ocr.call_count == opencd.MAX_CAPTCHA_CALLS
    assert context.request.get_res.call_count == opencd.MAX_CAPTCHA_CALLS // opencd.CAPTCHA_ATTEMPTS_PER_IMAGE
    context.request.post_res.assert_not_called()


def test_captcha_unreadable_refreshes_form_and_submits(signin_context):
    """一张图四次都读不出时换新图，第二轮识别成功才提交。"""
    context = signin_context
    context.request.get_res.side_effect = [
        _response(_form_revision("csrf-0", "hash-0")),
        _response(_form_revision("csrf-1", "hash-1")),
    ]
    context.ocr.side_effect = ["", "", "", "", "ABCDEF"]

    assert opencd.Opencd().signin(context.site) == (True, "签到成功")

    assert context.request.get_res.call_count == 2
    assert context.ocr.call_count == 5
    context.request.post_res.assert_called_once()
    assert context.request.post_res.call_args.kwargs["data"]["imagehash"] == "hash-1"


def test_duration_budget_stops_before_form_request(signin_context, monkeypatch):
    """首页耗时已用尽单站预算时不再取表单、识别或提交。"""
    context = signin_context
    budget = max(opencd.MAX_DURATION, 15 + 30)
    monkeypatch.setattr(opencd.time, "monotonic", Mock(side_effect=[0.0, float(budget + 1)]))

    expected = f"签到失败，单站签到超时（超过 {budget} 秒）"
    assert opencd.Opencd().signin(context.site) == (False, expected)

    context.request.get_res.assert_not_called()
    context.ocr.assert_not_called()
    context.request.post_res.assert_not_called()
    context.logger.error.assert_called_once_with(f"皇后 {expected}")


def test_slow_homepage_still_attempts_first_round(signin_context, monkeypatch):
    """首页耗掉基础预算但站点超时较长时，预算放宽后首轮仍会取表并提交。"""
    context = signin_context
    context.site["timeout"] = 90
    ticks = iter([0.0, float(opencd.MAX_DURATION + 5)])
    monkeypatch.setattr(opencd.time, "monotonic", Mock(side_effect=lambda: next(ticks, float(opencd.MAX_DURATION + 5))))

    assert opencd.Opencd().signin(context.site) == (True, "签到成功")

    assert context.request.get_res.call_count == 1
    context.request.post_res.assert_called_once()


def test_explicit_signed_homepage_skips_requests(signin_context):
    """首页明确显示今日已签到时不再读取表单或重复签到。"""
    context = signin_context
    context.homepage.return_value = '<a href="logout.php">退出</a><p>今日已签到</p>'

    assert opencd.Opencd().signin(context.site) == (True, "今日已签到")

    context.factory.assert_not_called()
    context.ocr.assert_not_called()


def test_serialized_request_contains_matching_csrf_pair(signin_context, monkeypatch):
    """使用真实 HTTP 工具和 requests 编码，仅替换传输层验证最终表单与 Cookie。"""
    context = signin_context
    context.site["proxy"] = False
    sent = []

    def send(_session, request, **_kwargs):
        """在传输边界重放签到页，并检查实际编码后的请求才返回签到成功。"""
        sent.append(request)
        if request.method == "GET":
            return context.page
        cookies = SimpleCookie(request.headers["Cookie"])
        assert cookies["c_csrf"].value == "new-cookie"
        assert cookies["uid"].value == "test"
        assert cookies["pass"].value == "a=b"
        assert parse_qs(request.body) == {
            "csrf_token": ["form-csrf-token"], "imagehash": ["image-hash"], "imagestring": ["ABCDEF"],
        }
        assert request.headers["Referer"] == "https://open.cd/plugin_sign-in.php"
        assert request.headers["User-Agent"] == "MoviePilot-Test"
        return _response(payload={"state": "success"})

    monkeypatch.setattr(opencd, "RequestUtils", RequestUtils)
    monkeypatch.setattr("requests.sessions.Session.send", send)

    assert opencd.Opencd().signin(context.site) == (True, "签到成功")
    assert [request.method for request in sent] == ["GET", "POST"]


def test_error_summary_is_bounded_and_excludes_form_fields(signin_context):
    """错误摘要去掉 HTML、脚本及隐藏字段属性，并限制长度。"""
    context = signin_context
    context.request.post_res.return_value = _response(
        '<html><script>secret-script</script><input name="csrf_token" value="secret-token">'
        '<body>Forbidden ' + 'x' * 300 + '</body></html>', 403,
    )

    success, message = opencd.Opencd().signin(context.site)

    assert success is False
    assert message == '签到失败，签到接口返回 HTTP 403：' + ('Forbidden ' + 'x' * 300)[:200]
    assert 'secret' not in message
    assert '<' not in message


@pytest.mark.parametrize("payload", [{"state": False}, {"state": "false"}])
def test_state_false_without_message_is_today_already_signed(signin_context, payload):
    """当日已签到时接口只回不带 msg 的 state=false，应按今日已签到确认，并标注为依据推断。"""
    context = signin_context
    context.request.post_res.return_value = _response(payload=payload)

    assert opencd.Opencd().signin(context.site) == (True, "今日已签到（接口未返回原因）")

    context.request.post_res.assert_called_once()
    context.logger.error.assert_not_called()


def test_captcha_error_resubmits_with_fresh_form(signin_context):
    """验证码被站点判错后重取整张表单，前两次失败第三次提交成功。"""
    context = signin_context
    context.request.get_res.side_effect = [
        _response(_form_revision(f"csrf-{index}", f"hash-{index}"), cookies={"c_csrf": f"page-{index}"})
        for index in range(3)
    ]
    context.request.post_res.side_effect = [
        _response(payload={"state": "false", "msg": "验证码错误"}),
        _response(payload={"state": "false", "msg": "验证码错误"}),
        _response(payload={"state": "success"}),
    ]

    assert opencd.Opencd().signin(context.site) == (True, "签到成功")

    assert context.request.get_res.call_count == 3
    assert context.request.post_res.call_count == 3
    assert context.ocr.call_count == 3
    submitted = [call.kwargs["data"] for call in context.request.post_res.call_args_list]
    assert [data["csrf_token"] for data in submitted] == ["csrf-0", "csrf-1", "csrf-2"]
    assert [data["imagehash"] for data in submitted] == ["hash-0", "hash-1", "hash-2"]
    ocr_cookies = [call.kwargs["cookie"] for call in context.ocr.call_args_list]
    assert ocr_cookies[0].endswith("c_csrf=page-0")
    assert ocr_cookies[2].endswith("c_csrf=page-2")
    context.logger.error.assert_not_called()


def test_captcha_error_stops_after_three_submits(signin_context):
    """三次提交都被判验证码错误时返回最后一次原因，不再提交第四次。"""
    context = signin_context
    context.request.post_res.return_value = _response(payload={"state": "false", "msg": "验证码错误"})

    assert opencd.Opencd().signin(context.site) == (False, "签到失败，签到接口返回 HTTP 200：验证码错误")

    assert context.request.post_res.call_count == 3
    assert context.request.get_res.call_count == 3
    context.logger.error.assert_called_once_with("皇后 签到失败，签到接口返回 HTTP 200：验证码错误")


def test_page_request_missing_retries_once(signin_context):
    """签到页未收到响应时原地重试一次，第二次取到表单后正常提交。"""
    context = signin_context
    context.request.get_res.side_effect = [None, context.page]

    assert opencd.Opencd().signin(context.site) == (True, "签到成功")

    assert context.request.get_res.call_count == 2
    context.request.post_res.assert_called_once()


def test_page_request_missing_twice_stops_before_captcha(signin_context):
    """连续两次未收到签到页时按页面请求失败结束，不进入验证码或提交阶段。"""
    context = signin_context
    context.request.get_res.return_value = None

    assert opencd.Opencd().signin(context.site) == (False, "签到失败，签到页面请求失败：未收到响应")

    assert context.request.get_res.call_count == 2
    context.ocr.assert_not_called()
    context.request.post_res.assert_not_called()


def test_page_request_server_error_retries_once(signin_context):
    """签到页返回服务端 5xx 时原地重试一次，仍失败则保留最后一次 HTTP 原因。"""
    context = signin_context
    context.request.get_res.side_effect = [
        _response("Bad gateway", 502),
        _response("Service unavailable", 503),
    ]

    assert opencd.Opencd().signin(context.site) == (
        False, "签到失败，签到页面返回 HTTP 503：Service unavailable")

    assert context.request.get_res.call_count == 2
    context.ocr.assert_not_called()
    context.request.post_res.assert_not_called()
