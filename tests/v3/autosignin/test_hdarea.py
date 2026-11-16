"""
验证高清视界的 API 签到、登录确认和无密钥时的 Cookie 兼容。
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests import Response
from ruamel.yaml import CommentedMap

import app.plugins.autosignin.sites.hdarea as hdarea
from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.sites.hdarea import HDArea


def _site(**changes):
    """
    提供不对应真实账号的 API Key、Cookie 和网络配置。
    """
    site = CommentedMap({"name": "高清视界", "url": "https://hdarea.club/", "apikey": " synthetic-key ",
                         "cookie": "unused-cookie", "ua": "HDArea-Test", "timeout": 25, "proxy": True})
    site.update(changes)
    return site


def _response(data, status=200, code=0, success=True, message="OK"):
    """
    构造真实 HTTP 布尔语义的响应并记录关闭动作。
    """
    response = Response()
    response.status_code = status
    payload = {"success": success, "code": code, "message": message, "data": data}
    response._content = json.dumps(payload).encode() if not isinstance(data, str) else data.encode()
    response.encoding = "utf-8"
    response.close = Mock()
    return response


@pytest.fixture
def boundary(monkeypatch):
    """
    所有传输均由本用例替身处理，不加载真实配置或访问真实站点。
    """
    monkeypatch.setattr(hdarea, "settings", SimpleNamespace(PROXY={"https": "proxy"}))
    response = _response({"signed_in_today": True})
    client = Mock(post_res=Mock(return_value=response), get_res=Mock(return_value=response))
    factory = Mock(return_value=client)
    monkeypatch.setattr(hdarea, "RequestUtils", factory)
    return SimpleNamespace(response=response, client=client, factory=factory)


def test_signin_uses_key_only_and_json(boundary):
    """
    配置密钥时只提交官方签到 API，并保留 UA、代理、超时，不发送 Cookie。
    """
    assert HDArea().signin(_site()) == (True, "签到成功")
    boundary.client.post_res.assert_called_once_with(url="https://hdarea.club/api/v1/user/signin",
                                                     json={}, allow_redirects=False)
    assert boundary.factory.call_args.kwargs == {
        "headers": {"X-API-Key": "synthetic-key", "Accept": "application/json", "Content-Type": "application/json"},
        "ua": "HDArea-Test", "proxies": {"https": "proxy"}, "timeout": 25,
    }
    boundary.response.close.assert_called_once()


@pytest.mark.parametrize("data,message", [({"already_signed": True}, "OK"), ({}, "今日已签到"),
                                          ({}, "请不要重复签到哦")])
def test_confirmed_repeat_signin_is_success(boundary, data, message):
    """
    接口成功并明确表示已签到时，重复执行仍记为今日已签到。
    """
    boundary.client.post_res.return_value = _response(data, message=message)
    assert HDArea().signin(_site()) == (True, "今日已签到")


@pytest.mark.parametrize("status,code,success,expected", [
    (401, 401, False, "API Key"), (403, 403, False, "白名单"), (429, 429, False, "HTTP 429"),
    (500, 0, True, "HTTP 500"), (200, 1, True, "已隐藏"), (200, 0, False, "已隐藏"),
])
def test_api_failure_never_falls_back_to_cookie(boundary, status, code, success, expected):
    """
    API 失败不访问网页，也不被响应中的成功文字误导；密钥回显被移除。
    """
    response = _response({}, status, code, success, "签到成功 synthetic-key")
    boundary.client.post_res.return_value = response
    state, message = HDArea().signin(_site())
    assert state is False and expected in message and "synthetic-key" not in message
    boundary.factory.assert_called_once()
    assert "cookies" not in boundary.factory.call_args.kwargs
    response.close.assert_called_once()


@pytest.mark.parametrize("response", [None, _response("<html>synthetic-key</html>"), _response([])])
def test_missing_or_invalid_response_is_not_signin_success(boundary, response):
    """
    无响应、非 JSON 和无效 data 不构成签到完成证据。
    """
    boundary.client.post_res.return_value = response
    state, message = HDArea().signin(_site())
    assert state is False and "synthetic-key" not in message


def test_login_uses_profile_api_and_honors_custom_endpoint(boundary):
    """
    API 登录确认只读取用户资料，即使仍有 Cookie 也不访问网页。
    """
    boundary.client.get_res.return_value = _response({"id": 42, "enabled": True})
    assert HDArea().login(_site(api_url="https://api.custom.test/v1/")) == (True, "模拟登录成功")
    boundary.client.get_res.assert_called_once_with(url="https://api.custom.test/v1/user/profile", allow_redirects=False)
    assert "cookies" not in boundary.factory.call_args.kwargs


@pytest.mark.parametrize("data", [{}, {"id": 0}, {"id": True}, {"id": 42, "enabled": False}])
def test_login_requires_valid_identity(boundary, data):
    """
    缺少身份或账号被禁用时不能报告 API 登录成功。
    """
    boundary.client.get_res.return_value = _response(data)
    assert HDArea().login(_site())[0] is False


@pytest.mark.parametrize("text,expected", [("此次签到您获得100魔力值", "签到成功"),
                                          ("请不要重复签到哦", "今日已签到")])
def test_without_key_preserves_cookie_signin(boundary, text, expected):
    """
    未配置密钥的存量站点保持原 Cookie 表单及签到结果判断。
    """
    response = _response(text)
    boundary.client.post_res.return_value = response
    assert HDArea().signin(_site(apikey=" ")) == (True, expected)
    assert boundary.factory.call_args.kwargs["cookies"] == "unused-cookie"
    boundary.client.post_res.assert_called_once_with(url="https://hdarea.club/sign_in.php", data={"action": "sign_in"})
    response.close.assert_called_once()


def test_signin_orchestration_confirms_api_login_without_claiming_signin(boundary, monkeypatch):
    """
    API 签到失败后的资料检测仍只用密钥，登录可用不能改写签到成功。
    """
    boundary.client.post_res.return_value = _response({}, 500)
    boundary.client.get_res.return_value = _response({"id": 42})
    plugin = object.__new__(AutoSignIn)
    monkeypatch.setattr(plugin, "_AutoSignIn__build_class", Mock(return_value=HDArea))
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", Mock(return_value=Mock()))
    result = plugin.signin_site(_site())
    assert result.success is False and result.logged_in is True
    assert result.message == "登录成功，签到未确认"
    assert boundary.client.get_res.call_args.kwargs["url"] == "https://hdarea.club/api/v1/user/profile"
    assert all("cookies" not in call.kwargs for call in boundary.factory.call_args_list)


def test_cookie_login_and_missing_credentials_are_explicit(boundary):
    """
    没有密钥时只用既有 Cookie 检测登录，缺少两种凭据时不发请求。
    """
    boundary.client.get_res.return_value = _response('<a href="logout.php">退出</a>')
    assert HDArea().login(_site(apikey="")) == (True, "模拟登录成功")
    assert boundary.factory.call_args.kwargs["cookies"] == "unused-cookie"
    boundary.factory.reset_mock()
    assert HDArea().login(_site(apikey="", cookie=""))[0] is False
    boundary.factory.assert_not_called()


def test_cookie_login_preserves_browser_rendering(boundary, monkeypatch):
    """
    未配置 API Key 时，旧 Cookie 登录的浏览器仿真开关仍然生效。
    """
    source = Mock(return_value='<a href="logout.php">退出</a>')
    monkeypatch.setattr(HDArea, "get_page_source", source)
    assert HDArea().login(_site(apikey="", render=True)) == (True, "模拟登录成功")
    assert source.call_args.kwargs["cookie"] == "unused-cookie"
    assert source.call_args.kwargs["render"] is True
    boundary.factory.assert_not_called()
