"""海胆之家新域名、打卡请求顺序与结果确认回归。"""

from unittest.mock import call, patch

import pytest
from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.sites.haidan import HaiDan
from ruamel.yaml import CommentedMap


@pytest.mark.parametrize("url", ["https://haidan.cc/", "https://www.haidan.cc/",
                                 "https://www.haidan.cc/attendance.php"])
def test_current_domain_selects_special_handler(url):
    """当前域名必须在插件分派入口命中海胆专用处理器。"""
    plugin = object.__new__(AutoSignIn)
    plugin._site_schema = [HaiDan]
    assert plugin._AutoSignIn__build_class(url) is HaiDan


@pytest.mark.parametrize("url", ["https://www.haidan.video/", "https://other.example/",
                                 "https://haidan.cc.example/"])
def test_unrelated_or_retired_domain_does_not_match(url):
    """旧域名和无关域名不能触发海胆打卡。"""
    assert HaiDan.match(url) is False


@pytest.mark.parametrize("base_url", ["https://www.haidan.cc/", "https://haidan.cc",
                                      "http://www.haidan.cc:8080/attendance.php"])
@pytest.mark.parametrize("render", [False, True])
def test_signin_then_confirm_on_configured_host(base_url, render):
    """先访问打卡接口，再带相同凭据回读首页；保留配置的域名、协议和端口。"""
    site_info = CommentedMap(name="海胆之家", url=base_url, cookie="uid=test",
                             ua="MoviePilot-Test", proxy=True, render=render, timeout=15)
    with patch.object(HaiDan, "get_page_source", side_effect=[
        "", '<input type="submit" disabled value="已经打卡" />',
    ]) as get_page:
        assert HaiDan().signin(site_info) == (True, "签到成功")
    origin = base_url.split("/attendance.php")[0].rstrip("/")
    options = dict(cookie="uid=test", ua="MoviePilot-Test", proxy=True,
                   render=render, timeout=15)
    assert get_page.call_args_list == [
        call(url=origin + "/signin.php", **options),
        call(url=origin + "/index.php", **options),
    ]


@pytest.mark.parametrize(("page", "message"), [
    ('<script>daily_attendance("已经打卡")</script>'
     '<input type="submit" value="打卡" />', "签到失败"),
    ('<a href="logout.php">退出</a>', "签到失败"),
    ('<form action="login.php"></form>', "签到失败，Cookie已失效"),
    ("", "签到失败，请检查站点连通性"),
])
def test_homepage_without_confirmed_attendance_is_failure(page, message):
    """脚本文案、仅登录、登录页和空响应均不能确认已打卡。"""
    site_info = CommentedMap(name="海胆之家", url="https://www.haidan.cc/", cookie="uid=test")
    with patch.object(HaiDan, "get_page_source", side_effect=["", page]):
        assert HaiDan().signin(site_info) == (False, message)
