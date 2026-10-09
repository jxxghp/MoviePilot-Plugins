"""AutoSignIn V2 的 Rousi Pro 认证与回退测试。"""

from types import SimpleNamespace
from unittest.mock import patch

from ruamel.yaml import CommentedMap

from app.plugins.autosignin.sites.rousipro import RousiPro


def _response(status_code: int, code: int):
    """构造包含 HTTP 状态码和 Rousi Pro 业务状态码的响应。"""
    return SimpleNamespace(status_code=status_code, json=lambda: {"code": code})


def _site_info(**overrides) -> CommentedMap:
    """构造 Rousi Pro 签到处理器需要的站点配置。"""
    site_info = CommentedMap({
        "name": "Rousi Pro",
        "url": "https://rousi.pro/",
        "ua": "MoviePilot-Test",
        "apikey": "stable-api-key",
        "token": "short-lived-jwt",
        "timeout": 15,
        "proxy": False,
    })
    site_info.update(overrides)
    return site_info


def test_signin_prefers_api_key_when_supported():
    """个人 API Key 签到成功时不应再发送 Authorization 请求。"""
    with patch("app.plugins.autosignin.sites.rousipro.RequestUtils") as request_utils:
        request_utils.return_value.post_res.return_value = _response(200, 0)

        result = RousiPro().signin(_site_info())

    assert result == (True, "签到成功")
    assert request_utils.call_count == 1
    headers = request_utils.call_args.kwargs["headers"]
    assert headers["api-token"] == "stable-api-key"
    assert "Authorization" not in headers


def test_signin_falls_back_to_authorization_when_api_key_is_rejected():
    """站点拒绝个人 API Key 签到时应自动使用短期 Authorization Token。"""
    with patch("app.plugins.autosignin.sites.rousipro.RequestUtils") as request_utils:
        request_utils.return_value.post_res.side_effect = [
            _response(401, -1),
            _response(200, 0),
        ]

        result = RousiPro().signin(_site_info())

    assert result == (True, "签到成功")
    assert request_utils.call_count == 2
    first_headers = request_utils.call_args_list[0].kwargs["headers"]
    second_headers = request_utils.call_args_list[1].kwargs["headers"]
    assert first_headers["api-token"] == "stable-api-key"
    assert second_headers["Authorization"] == "Bearer short-lived-jwt"
    assert "api-token" not in second_headers


def test_login_uses_api_key_profile_without_authorization_token():
    """模拟登录应允许只配置个人 API Key，并通过 profile 接口完成认证。"""
    with patch("app.plugins.autosignin.sites.rousipro.RequestUtils") as request_utils:
        request_utils.return_value.get_res.return_value = _response(200, 0)

        result = RousiPro().login(_site_info(token=""))

    assert result == (True, "模拟登录成功")
    assert request_utils.call_args.kwargs["headers"]["Authorization"] == "Bearer stable-api-key"
    request_utils.return_value.get_res.assert_called_once_with(
        url="https://rousi.pro/api/v1/profile"
    )


def test_login_falls_back_to_attendance_stats_with_authorization():
    """个人 API Key 登录检测失败时应回退原有 Authorization 统计接口。"""
    with patch("app.plugins.autosignin.sites.rousipro.RequestUtils") as request_utils:
        request_utils.return_value.get_res.side_effect = [
            _response(401, -1),
            _response(200, 0),
        ]

        result = RousiPro().login(_site_info())

    assert result == (True, "模拟登录成功")
    assert request_utils.call_count == 2
    assert request_utils.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer short-lived-jwt"
    assert request_utils.return_value.get_res.call_args_list[1].kwargs["url"] == (
        "https://rousi.pro/api/points/attendance/stats"
    )


def test_missing_credentials_fails_without_request():
    """个人 API Key 和 Authorization 均缺失时应直接返回明确错误。"""
    with patch("app.plugins.autosignin.sites.rousipro.RequestUtils") as request_utils:
        signin_result = RousiPro().signin(_site_info(apikey="", token=""))
        login_result = RousiPro().login(_site_info(apikey="", token=""))

    assert signin_result == (False, "签到失败，缺少个人 API Key 或兼容 Authorization 信息")
    assert login_result == (False, "模拟登录失败，缺少个人 API Key 或兼容 Authorization 信息")
    request_utils.assert_not_called()


def test_signin_reports_personal_api_key_permission_error():
    """个人 API Key 缺少 attendance:claim 权限时应返回明确提示。"""
    with patch("app.plugins.autosignin.sites.rousipro.RequestUtils") as request_utils:
        request_utils.return_value.post_res.return_value = _response(403, -1)

        result = RousiPro().signin(_site_info(token=""))

    assert result == (False, "签到失败，个人 API Key 已失效或权限不足")


def test_login_reports_personal_api_key_permission_error():
    """个人 API Key 缺少 profile:read 权限时应返回明确提示。"""
    with patch("app.plugins.autosignin.sites.rousipro.RequestUtils") as request_utils:
        request_utils.return_value.get_res.return_value = _response(403, -1)

        result = RousiPro().login(_site_info(token=""))

    assert result == (False, "模拟登录失败，个人 API Key 已失效或权限不足")
