"""
验证 Sunny 新版 API 签到：Cookie 换会话令牌、今日状态、重复签到、令牌失效与高延迟重试。
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout
from ruamel.yaml import CommentedMap

import app.plugins.autosignin.sites.sunnypt as sunnypt
from app.plugins.autosignin.sites.sunnypt import SunnyPT

_SESSION = "https://sunnypt.top/api/auth/session"
_STATUS = "https://api.sunnypt.top/api/v1/attendance/status"
_CHECK_IN = "https://api.sunnypt.top/api/v1/attendance/check-in"
_SESSION_HEADERS = {"Accept": "application/json", "User-Agent": "Sunny-Test"}


def _site(**changes) -> CommentedMap:
    """提供不对应真实账号的 Cookie 与网络配置。"""
    site = CommentedMap({"name": "Sunny", "url": "https://sunnypt.top/", "cookie": "AuthSession=test",
                         "ua": "Sunny-Test", "timeout": 90, "proxy": True})
    site.update(changes)
    return site


def _response(payload, status=200) -> Response:
    """构造真实 HTTP 布尔语义的响应并记录关闭动作。"""
    response = Response()
    response.status_code = status
    response._content = (json.dumps(payload) if not isinstance(payload, str) else payload).encode()
    response.encoding = "utf-8"
    response.close = Mock()
    return response


@pytest.fixture
def api(monkeypatch):
    """会话与签到接口均由替身处理，不访问真实站点、不真正等待重试间隔。"""
    monkeypatch.setattr(sunnypt, "settings", SimpleNamespace(PROXY={"https": "proxy"}))
    responses = {
        _SESSION: _response({"data": {"accessToken": "header.payload.signature", "userId": 10410}}),
        _STATUS: _response({"code": 0, "data": {"checked_in": False, "days": 17}, "msg": "ok"}),
        _CHECK_IN: _response({"code": 0, "data": {"points": 45, "days": 18}, "msg": "ok"}),
    }
    client = Mock()
    client.get_res.side_effect = lambda url, **kwargs: responses[url]
    client.post_res.side_effect = lambda url, **kwargs: responses[url]
    factory = Mock(return_value=client)
    monkeypatch.setattr(sunnypt, "RequestUtils", factory)
    sleep = Mock()
    monkeypatch.setattr(sunnypt.time, "sleep", sleep)
    return SimpleNamespace(responses=responses, client=client, factory=factory, sleep=sleep)


def test_signin_exchanges_cookie_and_reports_points(api):
    """Cookie 先换令牌，签到成功后回读接口返回的魔力与连续天数。"""
    assert SunnyPT().signin(_site()) == (True, "签到成功，获得 45 魔力，连续 18 天")
    assert [call.kwargs["url"] for call in api.client.get_res.call_args_list] == [_SESSION, _STATUS]
    assert api.client.get_res.call_args_list[0].kwargs == {"url": _SESSION, "raise_exception": True}
    assert api.client.post_res.call_args.kwargs == {"url": _CHECK_IN, "json": {}, "raise_exception": True}
    headers = [call.kwargs["headers"] for call in api.factory.call_args_list]
    assert headers[0] == _SESSION_HEADERS
    assert headers[1]["Authorization"] == "Bearer header.payload.signature"
    assert headers[2]["Authorization"] == "Bearer header.payload.signature"
    assert api.factory.call_args.kwargs == {"cookies": "AuthSession=test", "headers": headers[2],
                                            "timeout": 90, "proxies": {"https": "proxy"}}
    api.sleep.assert_not_called()


def test_site_timeout_is_lifted_to_minimum(api):
    """站点默认 15 秒不足以覆盖该站抖动，实际请求按 60 秒保底。"""
    assert SunnyPT().signin(_site(timeout=15)) == (True, "签到成功，获得 45 魔力，连续 18 天")
    assert api.factory.call_args.kwargs["timeout"] == 60


def test_checked_in_today_skips_submit(api):
    """状态已确认今天签到时不重复提交。"""
    api.responses[_STATUS] = _response({"code": 0, "data": {"checked_in": True, "days": 17}, "msg": "ok"})
    assert SunnyPT().signin(_site()) == (True, "签到成功，今日已签到，连续 17 天")
    api.client.post_res.assert_not_called()


def test_duplicate_code_is_success(api):
    """接口返回已签到业务码时按成功处理，不当作失败上报。"""
    api.responses[_CHECK_IN] = _response({"code": 400001, "data": None, "msg": "今天已经签到过了"})
    assert SunnyPT().signin(_site()) == (True, "签到成功，今日已签到")


def test_expired_session_token_fails(api):
    """提交阶段令牌失效时提示重新登录，不掩盖为签到成功。"""
    api.responses[_CHECK_IN] = _response({"code": 401000, "data": None, "msg": "用户未登录"})
    state, message = SunnyPT().signin(_site())
    assert state is False and "会话令牌已失效" in message


def test_business_error_keeps_site_message(api):
    """未识别的业务码保留站点返回的原因。"""
    api.responses[_CHECK_IN] = _response({"code": 500001, "data": None, "msg": "签到服务维护中"})
    assert SunnyPT().signin(_site()) == (False, "签到失败，签到服务维护中")


def test_missing_cookie_returns_early(api):
    """未配置 Cookie 时不发起任何请求。"""
    assert SunnyPT().signin(_site(cookie="")) == (False, "签到失败，未配置站点Cookie")
    api.factory.assert_not_called()


@pytest.mark.parametrize("payload", [{"data": None}, {"data": {}}, {"data": {"accessToken": "opaque"}}])
def test_session_without_jwt_fails(api, payload):
    """会话接口没有返回 JWT 时按 Cookie 失效处理。"""
    api.responses[_SESSION] = _response(payload)
    state, message = SunnyPT().signin(_site())
    assert state is False and "请重新登录站点更新Cookie" in message
    api.client.post_res.assert_not_called()


def test_session_rejected_fails(api):
    """会话接口明确返回 401 时给出 Cookie 失效提示。"""
    api.responses[_SESSION] = _response({"data": None}, status=401)
    assert SunnyPT().signin(_site()) == (False, "签到失败，Cookie 已失效，请重新登录站点更新Cookie")


def test_session_forbidden_is_not_cookie_invalid(api):
    """403 可能来自站点防护，不能一律当成 Cookie 失效。"""
    api.responses[_SESSION] = _response("<html>forbidden</html>", status=403)
    assert SunnyPT().signin(_site()) == (False, "签到失败，站点访问被拒绝（HTTP 403）")


def test_session_http_error_reports_status(api):
    """会话接口非 200/401/403 时保留状态码，交由通知归类。"""
    api.responses[_SESSION] = _response({"error": "boom"}, status=500)
    assert SunnyPT().signin(_site()) == (False, "签到失败，站点会话接口状态码：500！")


def test_session_timeout_reports_timeout(api):
    """会话请求超时需重试一次并报超时，不能伪装成 Cookie 失效。"""
    api.client.get_res.side_effect = ReadTimeout("read timed out")
    state, message = SunnyPT().signin(_site())
    assert state is False and message == "签到失败，无法访问站点会话接口，请求超时"
    assert api.client.get_res.call_count == 2
    api.sleep.assert_called_once()
    api.client.post_res.assert_not_called()


def test_session_connection_error_reports_network(api):
    """连接失败与会话失效区分开，文案命中网络连接失败分类。"""
    api.client.get_res.side_effect = RequestsConnectionError("connection refused")
    assert SunnyPT().signin(_site()) == (False, "签到失败，无法访问站点会话接口，网络连接失败")


def test_status_timeout_retries_once(api):
    """状态接口超时后重试成功，仍能继续提交签到。"""
    status = api.responses[_STATUS]
    api.client.get_res.side_effect = [api.responses[_SESSION], ReadTimeout("read timed out"), status]
    assert SunnyPT().signin(_site()) == (True, "签到成功，获得 45 魔力，连续 18 天")
    api.sleep.assert_called_once()
    api.client.post_res.assert_called_once()


def test_status_timeout_twice_reports_timeout(api):
    """两次读取都超时时报超时，不提交签到。"""
    api.client.get_res.side_effect = [api.responses[_SESSION], ReadTimeout("1"), ReadTimeout("2")]
    assert SunnyPT().signin(_site()) == (False, "签到失败，签到状态接口请求超时")
    assert api.client.get_res.call_count == 3
    assert api.sleep.call_count == 1
    api.client.post_res.assert_not_called()


def test_check_in_timeout_verified_as_success(api):
    """提交超时后回查当日状态，服务端已受理则判成功且不重复提交。"""
    pending = _response({"code": 0, "data": {"checked_in": False, "days": 17}, "msg": "ok"})
    checked = _response({"code": 0, "data": {"checked_in": True, "days": 18}, "msg": "ok"})
    api.client.get_res.side_effect = [api.responses[_SESSION], pending, checked]
    api.client.post_res.side_effect = ReadTimeout("read timed out")
    assert SunnyPT().signin(_site()) == (True, "签到成功，今日已签到，连续 18 天")
    api.client.post_res.assert_called_once()


def test_check_in_timeout_unverified_reports_timeout(api):
    """提交超时且回查仍未签到时保留超时原因，交由下次重试。"""
    api.client.post_res.side_effect = ReadTimeout("read timed out")
    assert SunnyPT().signin(_site()) == (False, "签到失败，签到接口请求超时")
    assert api.client.post_res.call_count == 1


def test_status_network_error_converts_to_failure(api):
    """状态接口非超时异常时转换为失败回执，不抛出到调度器。"""
    session = api.responses[_SESSION]
    calls = {"count": 0}

    def get(url, **_):
        calls["count"] += 1
        if calls["count"] == 1:
            return session
        raise RuntimeError("boom")

    api.client.get_res.side_effect = get
    state, message = SunnyPT().signin(_site())
    assert state is False and message == "签到失败，签到状态接口返回异常"


def test_status_error_keeps_message(api):
    """状态接口业务错误时按失败返回，不提交签到。"""
    api.responses[_STATUS] = _response({"code": 401000, "data": None, "msg": "用户未登录"})
    assert SunnyPT().signin(_site()) == (False, "签到失败，用户未登录")
    api.client.post_res.assert_not_called()


@pytest.mark.parametrize("url, matched", [("https://sunnypt.top/", True),
                                          ("https://sunnypt.top", True),
                                          ("https://api.sunnypt.top/", False),
                                          ("https://sunnypt.top.cn/", False)])
def test_match_only_site_domain(url, matched):
    """只匹配站点主域，API 子域与相近域名都不接手。"""
    assert SunnyPT.match(url) is matched
