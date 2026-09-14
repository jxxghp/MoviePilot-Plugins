"""AutoSignIn V2 的 U2 登录检测与 CSRF 签到回归测试。"""

from types import SimpleNamespace
from unittest.mock import patch

from app.plugins.autosignin.sites.u2 import U2
from ruamel.yaml import CommentedMap


def _site_info() -> CommentedMap:
    """构造 U2 签到处理器需要的最小站点配置。"""
    return CommentedMap(
        {
            "name": "幼儿园",
            "cookie": "u2=test-cookie",
            "ua": "MoviePilot-Test",
            "proxy": False,
            "render": False,
            "timeout": 15,
        }
    )


def _logged_in_page() -> str:
    """构造含 maxlogin.php 权限数据和签到表单的已登录页面。"""
    return """
    <html>
      <body>
        <a href="logout.php">退出</a>
        <script>var permissions = {"maxlogin.php": []};</script>
        <form action="showup.php?action=show" method="post">
          <table><tr>
            <td><input type="hidden" name="req" value="req-token"></td>
            <td><input type="hidden" name="hash" value="hash-token"></td>
            <td><input type="hidden" name="form" value="form-token"></td>
            <td><input type="hidden" name="_csrf" value="csrf-token"></td>
            <td><input type="submit" name="answer0" value="0"></td>
            <td><input type="submit" name="answer1" value="1"></td>
            <td><input type="submit" name="answer2" value="2"></td>
            <td><input type="submit" name="answer3" value="3"></td>
          </tr></table>
        </form>
      </body>
    </html>
    """


def test_signin_accepts_maxlogin_permission_data_and_submits_csrf():
    """已登录页面包含 maxlogin.php 时仍应提交带 CSRF 的签到请求。"""
    response = SimpleNamespace(
        status_code=200,
        text="<script>window.location.href = 'showup.php';</script>",
    )
    with (
        patch.object(U2, "get_page_source", return_value=_logged_in_page()),
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.random.randint", return_value=0),
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
    ):
        datetime.now.return_value.hour = 12
        request_utils.return_value.post_res.return_value = response

        result = U2().signin(_site_info())

    assert result == (True, "签到成功")
    request_utils.assert_called_once_with(
        cookies="u2=test-cookie",
        ua="MoviePilot-Test",
        proxies=None,
        headers={
            "User-Agent": "MoviePilot-Test",
            "Referer": "https://u2.dmhy.org/showup.php",
            "Origin": "https://u2.dmhy.org",
        },
    )
    request_utils.return_value.post_res.assert_called_once_with(
        url="https://u2.dmhy.org/showup.php?action=show",
        data={
            "req": "req-token",
            "hash": "hash-token",
            "form": "form-token",
            "_csrf": "csrf-token",
            "message": "一切随缘~",
            "answer0": "0",
        },
    )


def test_signin_reports_expired_cookie_for_login_form():
    """真正的登录表单仍应被识别为 Cookie 失效。"""
    login_page = '<html><body><form><input type="password" name="password"></form></body></html>'
    with (
        patch.object(U2, "get_page_source", return_value=login_page),
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
    ):
        datetime.now.return_value.hour = 12

        result = U2().signin(_site_info())

    assert result == (False, "签到失败，Cookie已失效")
    request_utils.assert_not_called()
