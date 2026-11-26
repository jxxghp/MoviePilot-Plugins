"""
验证签到与登录请求的 UA 解析：站点配置 > 站点默认 UA > 全局默认 UA。
"""

from types import SimpleNamespace

from ruamel.yaml import CommentedMap

import app.plugins.autosignin as autosignin
from app.plugins.autosignin import AutoSignIn

_GLOBAL_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/158.0"
_DEFAULT_UA = "MoviePilot/3.2.13 (Linux; x86_64)"


def _site(**changes) -> CommentedMap:
    site = CommentedMap({"name": "Site", "url": "https://example.test/", "cookie": "c=1", "ua": ""})
    site.update(changes)
    return site


def _settings(monkeypatch, global_ua: str = _GLOBAL_UA) -> None:
    monkeypatch.setattr(autosignin, "settings",
                        SimpleNamespace(SITE_USER_AGENT=global_ua, USER_AGENT=_DEFAULT_UA))


def test_site_ua_kept(monkeypatch):
    """站点自配 UA 时原样使用，并返回原对象。"""
    _settings(monkeypatch)
    site = _site(ua="SiteUA/1.0")
    assert AutoSignIn._site_request_ua(site) == "SiteUA/1.0"
    assert AutoSignIn._with_site_ua(site) is site


def test_global_ua_used_when_site_absent(monkeypatch):
    """站点未配置时使用站点默认 UA，且不改动缓存中的站点数据。"""
    _settings(monkeypatch)
    site = _site()
    assert AutoSignIn._site_request_ua(site) == _GLOBAL_UA
    injected = AutoSignIn._with_site_ua(site)
    assert injected["ua"] == _GLOBAL_UA
    assert site["ua"] == ""
    assert injected is not site


def test_default_ua_used_when_all_absent(monkeypatch):
    """站点与站点默认 UA 都为空时回落到宿主默认 UA。"""
    _settings(monkeypatch, global_ua="")
    assert AutoSignIn._with_site_ua(_site())["ua"] == _DEFAULT_UA


def test_site_value_equal_default_treated_as_unset(monkeypatch):
    """站点值为宿主默认 UA 时视为未配置，与核心解析一致。"""
    _settings(monkeypatch)
    assert AutoSignIn._with_site_ua(_site(ua=_DEFAULT_UA))["ua"] == _GLOBAL_UA


def test_host_without_site_ua_setting_falls_back(monkeypatch):
    """宿主没有站点默认 UA 设置时不影响解析。"""
    monkeypatch.setattr(autosignin, "settings", SimpleNamespace(USER_AGENT=_DEFAULT_UA))
    assert AutoSignIn._with_site_ua(_site())["ua"] == _DEFAULT_UA


def test_empty_site_info_kept(monkeypatch):
    """空站点信息原样返回。"""
    _settings(monkeypatch)
    assert not AutoSignIn._with_site_ua(CommentedMap())
