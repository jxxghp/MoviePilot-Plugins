"""AutoSignIn V2 的 U2 登录检测、当天状态与 CSRF 签到回归测试。"""

from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest
from app.plugins.autosignin.sites.u2 import U2
from ruamel.yaml import CommentedMap


@pytest.fixture
def confirmation_sleep():
    """隔离确认重试的等待，并保留调用顺序与间隔供断言。"""
    with patch("time.sleep") as sleep:
        yield sleep


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


def _history_form() -> str:
    """历史查询与答题共用签到脚本，但查询表单不含一次性答题参数。"""
    return """
    <form action="showup.php" method="get">
      查询历史签到信息 <input type="date" name="date">
      <table><tr><td><input type="submit" name="query" value="查询"></td></tr></table>
    </form>
    """


def _signed_page(message="感谢，今天已签到。") -> str:
    """当天完成提示与固定导航、历史查询表单同时存在。"""
    return f"""
    <html><body>
      <a href="logout.php">退出</a><a href="showup.php">已签到</a>
      <p>{message}</p>{_history_form()}
    </body></html>
    """


def _logged_in_page() -> str:
    """构造固定导航、历史查询和真实答题表单共存的已登录页面。"""
    return f"""
    <html>
      <body>
        <a href="logout.php">退出</a>
        <a href="showup.php">已签到</a>
        <script>var permissions = {{"maxlogin.php": []}};</script>
        {_history_form()}
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


@pytest.mark.parametrize("redirect_url", ["showup.php", "https://u2.dmhy.org/showup.php"])
def test_signin_accepts_success_redirect_variants(redirect_url, confirmation_sleep):
    """相对或绝对跳转后，必须回读到已签到状态才确认成功。"""
    response = SimpleNamespace(
        status_code=200,
        text=f"<script>window.location.href = '{redirect_url}';</script>",
    )
    with (
        patch.object(U2, "get_page_source", side_effect=[
            _logged_in_page(), _signed_page(),
        ]) as get_page,
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.random.randint", return_value=0),
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
    ):
        datetime.now.return_value.hour = 12
        request_utils.return_value.post_res.return_value = response

        result = U2().signin(_site_info())

    assert result == (True, "签到成功")
    assert get_page.call_count == 2
    confirmation_sleep.assert_not_called()
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


@pytest.mark.parametrize("checked_page", [
    _logged_in_page(), _signed_page(""), "", '<form><input type="password"></form>',
])
@pytest.mark.parametrize("response_text", [
    "<script>window.location.href='showup.php';</script>",
    '<p>回答错误，请返回签到页。</p>',
])
def test_submission_without_confirmed_state_is_not_success(checked_page, response_text, confirmation_sleep):
    """无论提交页有无跳转，三次回读均缺少当天凭据时仍返回未确认。"""
    response = SimpleNamespace(status_code=200, text=response_text)
    with (
        patch.object(U2, "get_page_source", side_effect=[_logged_in_page(), *[checked_page] * 3]) as get_page,
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.random.randint", return_value=0),
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
    ):
        datetime.now.return_value.hour = 12
        request_utils.return_value.post_res.return_value = response
        result = U2().signin(_site_info())
    assert result == (False, "签到失败，未确认签到结果")
    assert get_page.call_count == 4
    assert confirmation_sleep.call_args_list == [call(1), call(1)]
    request_utils.return_value.post_res.assert_called_once()


@pytest.mark.parametrize("response_text", [
    '<p>回答错误，正确答案为 1。</p><a href="showup.php">返回签到页</a>',
    '<meta http-equiv="refresh" content="0;url=showup.php">',
    "<script>window.location='showup.php';</script>",
    "<script>window.location.href='index.php';</script>",
    "<script>window.location.href='https://example.com/showup.php';</script>",
    "",
])
def test_submission_without_expected_redirect_still_checks_signed_state(response_text, confirmation_sleep):
    """答错页、其他跳转及空响应均回读固定签到页，不能跳过确认或跟随外站。"""
    with (
        patch.object(U2, "get_page_source", side_effect=[_logged_in_page(), _signed_page()]) as get_page,
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.random.randint", return_value=0),
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
        patch("app.plugins.autosignin.sites.u2.logger") as logger,
    ):
        datetime.now.return_value.hour = 12
        request_utils.return_value.post_res.return_value = SimpleNamespace(status_code=200, text=response_text)
        result = U2().signin(_site_info())

    assert result == (True, "签到成功")
    assert get_page.call_args_list == [call(
        url="https://u2.dmhy.org/showup.php", cookie="u2=test-cookie", ua="MoviePilot-Test",
        proxy=False, render=False, timeout=15,
    )] * 2
    request_utils.return_value.post_res.assert_called_once()
    confirmation_sleep.assert_not_called()
    logger.info.assert_any_call("幼儿园 签到提交未匹配到签到页跳转脚本，仍将回读确认")


@pytest.mark.parametrize("pending_pages", [
    [_logged_in_page()],
    [_logged_in_page(), ""],
])
def test_delayed_confirmation_retries_reads_without_resubmitting(pending_pages, confirmation_sleep):
    """站点延迟更新时只重试 GET，首次确认立即停止等待且不重复提交答题。"""
    timeline = Mock()
    with (
        patch.object(U2, "get_page_source", side_effect=[
            _logged_in_page(), *pending_pages, _signed_page(),
        ]) as get_page,
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.random.randint", return_value=0),
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
    ):
        datetime.now.return_value.hour = 12
        post = request_utils.return_value.post_res
        post.return_value = SimpleNamespace(status_code=200, text="<p>回答错误。</p>")
        timeline.attach_mock(get_page, "get")
        timeline.attach_mock(post, "post")
        timeline.attach_mock(confirmation_sleep, "sleep")
        result = U2().signin(_site_info())

    assert result == (True, "签到成功")
    assert [item[0] for item in timeline.mock_calls] == [
        "get", "post", "get", *["sleep", "get"] * len(pending_pages),
    ]
    assert confirmation_sleep.call_args_list == [call(1)] * len(pending_pages)
    post.assert_called_once()


@pytest.mark.parametrize("response", [None, SimpleNamespace(status_code=403), SimpleNamespace(status_code=503)])
def test_failed_submission_does_not_start_confirmation(response, confirmation_sleep):
    """提交请求失败时保留接口错误，不开始状态重试或重复 POST。"""
    with (
        patch.object(U2, "get_page_source", return_value=_logged_in_page()) as get_page,
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.random.randint", return_value=0),
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
    ):
        datetime.now.return_value.hour = 12
        request_utils.return_value.post_res.return_value = response
        result = U2().signin(_site_info())

    assert result == (False, "签到失败，签到接口请求失败")
    get_page.assert_called_once()
    request_utils.return_value.post_res.assert_called_once()
    confirmation_sleep.assert_not_called()


@pytest.mark.parametrize("message", ["感谢，今天已签到。", "感謝，今天已簽到。"])
def test_today_signed_state_ignores_history_query_form(message):
    """历史查询表单不能否定已登录页面上的明确当天完成提示。"""
    assert U2._has_signed_state(_signed_page(message))


@pytest.mark.parametrize("time", ["01:57", "09:22"])
@pytest.mark.parametrize("navigation", ["已签到", "已簽到", "Show Up", "Показать"])
def test_navigation_and_previous_reward_are_not_today_evidence(time, navigation):
    """站点签到窗口前后，导航与前一天的奖励记录都不能证明今日已签到。"""
    page = _signed_page(
        f'当前时间: {time}<table><tr><td>2026-11-16</td>'
        '<td>奖励UCoin: <b>1</b></td></tr></table>'
    ).replace('>已签到</a>', f'>{navigation}</a>')
    assert not U2._has_signed_state(page)


@pytest.mark.parametrize("navigation", ["已签到", "已簽到", "Show Up", "Показать"])
def test_navigation_alone_is_not_today_evidence(navigation):
    """即使没有历史查询表单，固定导航也不能作为已签到凭据。"""
    assert not U2._has_signed_state(
        f'<a href="logout.php">退出</a><a href="showup.php">{navigation}</a>',
    )


@pytest.mark.parametrize("message", [
    '<script>"感谢，今天已签到。"</script>',
    '<div hidden>感谢，今天已签到。</div>',
    '<template>感谢，今天已签到。</template>',
    '<!-- 感谢，今天已签到。 -->',
    '<span title="感谢，今天已签到。">签到说明</span>',
])
def test_hidden_or_attribute_message_is_not_today_evidence(message):
    """脚本、模板、隐藏内容及属性里的完成文案仍不构成当天证据。"""
    assert not U2._has_signed_state(_signed_page(message))


def test_pending_question_still_prevents_signed_confirmation():
    """仍有一次性答题参数时不能用页面上的完成文案跳过提交。"""
    assert not U2._has_signed_state(_logged_in_page().replace(
        '</body>', '<p>感谢，今天已签到。</p></body>',
    ))


def test_today_message_without_login_evidence_is_not_signed():
    """当天完成文案不能替代当前会话的登录证据。"""
    assert not U2._has_signed_state(_signed_page().replace('<a href="logout.php">退出</a>', ''))


def test_today_signed_page_does_not_submit_again():
    """已有明确当天结果时直接返回，不把历史查询表单误当答题入口。"""
    with (
        patch.object(U2, "get_page_source", return_value=_signed_page()),
        patch("app.plugins.autosignin.sites.u2.RequestUtils") as request_utils,
        patch("app.plugins.autosignin.sites.u2.datetime.datetime") as datetime,
    ):
        datetime.now.return_value.hour = 12
        result = U2().signin(_site_info())

    assert result == (True, "今日已签到")
    request_utils.assert_not_called()
