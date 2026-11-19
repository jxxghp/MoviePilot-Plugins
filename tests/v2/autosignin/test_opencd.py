"""皇后（open.cd）V2 签到接口状态与失败原因回归。"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ruamel.yaml import CommentedMap

from app.plugins.autosignin.sites import opencd
from app.plugins.autosignin.sites.opencd import Opencd

_HOME = '<a href="logout.php">退出</a><a href="plugin_sign-in.php">签到</a>'
_FORM = ('<form id="frmSignin"><img src="code.png">'
         '<input name="imagehash" value="image-hash"></form>')


def _site_info() -> CommentedMap:
    """构造皇后签到需要的最小站点配置。"""
    return CommentedMap(name="皇后", url="https://open.cd/", cookie="uid=test",
                        ua="MoviePilot-Test", proxy=False, render=False, timeout=15)


def _response(text, status=200) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, text=text)


def _context(monkeypatch, pages=None, post=None, captcha="ABCDEF") -> SimpleNamespace:
    """隔离页面读取、验证码识别与重试等待，返回签到接口调用记录。"""
    request = SimpleNamespace(post_res=Mock(return_value=post))
    monkeypatch.setattr(Opencd, "get_page_source",
                        Mock(side_effect=pages if pages is not None else [_HOME, _FORM]))
    monkeypatch.setattr(opencd, "RequestUtils", Mock(return_value=request))
    monkeypatch.setattr(opencd, "OcrHelper", Mock(return_value=SimpleNamespace(
        get_captcha_text=Mock(return_value=captcha))))
    monkeypatch.setattr(opencd.time, "sleep", Mock())
    return request


@pytest.mark.parametrize("payload, expected", [
    ({"state": "success"}, (True, "签到成功")),
    ({"state": False}, (True, "今日已签到（接口未返回原因）")),
    ({"state": "false"}, (True, "今日已签到（接口未返回原因）")),
    ({"state": "false", "msg": "验证码错误"}, (False, "签到失败，验证码错误")),
    ({"state": "error"}, (False, "签到失败，未返回成功状态")),
    ({"state": True}, (False, "签到失败，未返回成功状态")),
])
def test_state_false_without_reason_is_duplicate_signin(monkeypatch, payload, expected):
    """实测：验证码错误带 msg，当日已签到只回不带原因的 state=false；其余状态仍不算成功。"""
    request = _context(monkeypatch, post=_response(json.dumps(payload, ensure_ascii=False)))
    assert Opencd().signin(_site_info()) == expected
    request.post_res.assert_called_once()


def test_non_json_response_reports_format_error(monkeypatch):
    """接口回吐页面或异常内容时给出格式原因，不崩溃也不报验证码失败。"""
    _context(monkeypatch, post=_response("<html>系统错误</html>"))
    assert Opencd().signin(_site_info()) == (False, "签到失败，签到接口响应格式异常")


def test_http_error_reports_request_failure(monkeypatch):
    """签到接口非 200 时保留接口请求失败原因。"""
    _context(monkeypatch, post=_response("{}", status=500))
    assert Opencd().signin(_site_info()) == (False, "签到失败，签到接口请求失败")


def test_captcha_failure_is_the_only_missing_captcha_case(monkeypatch):
    """“未获取到验证码”只用于验证码识别失败，且不提交签到。"""
    request = _context(monkeypatch, captcha="")
    assert Opencd().signin(_site_info()) == (False, "签到失败：未获取到验证码")
    request.post_res.assert_not_called()


def test_today_signed_homepage_skips_submit(monkeypatch):
    """首页已有当天完成凭据时直接确认，不再重复提交验证码。"""
    request = _context(monkeypatch, pages=[_HOME + "<span>今日已签到</span>"])
    assert Opencd().signin(_site_info()) == (True, "今日已签到")
    request.post_res.assert_not_called()


def test_login_page_is_cookie_failure(monkeypatch):
    """首页出现登录表单时判 Cookie 失效，不走签到接口。"""
    request = _context(monkeypatch, pages=['<form action="login.php">'
                                           '<input type="password" name="pid"></form>'])
    assert Opencd().signin(_site_info()) == (False, "签到失败，Cookie已失效")
    request.post_res.assert_not_called()
