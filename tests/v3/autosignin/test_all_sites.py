"""动态全选的配置、执行、历史和站点删除回归。"""
from collections import Counter
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.result import SiteResult


@pytest.fixture
def plugin(monkeypatch):
    """隔离存储与站点访问，不向真实站点发送请求。"""
    instance = object.__new__(AutoSignIn)
    for name in ("update_config", "save_data", "del_data", "post_message", "stop_service"):
        monkeypatch.setattr(instance, name, Mock())
    monkeypatch.setattr(instance, "get_data", Mock(return_value=None))
    monkeypatch.setattr(instance, "get_config", Mock(return_value=None))
    monkeypatch.setattr(instance, "_AutoSignIn__custom_sites", Mock(return_value=[{"id": "custom", "name": "自定义"}]))
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", lambda: SimpleNamespace(
        list_order_by_pri=lambda: [SimpleNamespace(id=1, name="站点一")]))
    instance._sign_sites = ["all"]
    instance._login_sites = ["all"]
    instance._notify = True
    instance._clean = False
    instance._retry_keyword = "失败"
    instance._auto_cf = 0
    monkeypatch.setattr(instance, "signin_site", Mock(side_effect=lambda site: SiteResult(site["name"], "签到成功", True, True)))
    monkeypatch.setattr(instance, "login_site", Mock(side_effect=lambda site: SiteResult(site["name"], "登录成功", True, True)))
    return instance


def test_all_survives_config_and_deletion(plugin):
    """保存和删除站点时保留全选；原有逐个选择仍过滤已删除项。"""
    plugin.init_plugin({"sign_sites": ["all", 1], "login_sites": [1, 999]})
    assert plugin._sign_sites == ["all"]
    assert plugin._login_sites == [1]
    assert plugin.update_config.call_args.args[0]["sign_sites"] == ["all"]
    assert plugin._AutoSignIn__remove_site_id(["all"], 1) == ["all"]
    assert plugin._AutoSignIn__remove_site_id(["all"], None) == ["all"]
    assert plugin._resolve_site_ids(["all"]) == [1, "custom"]


def test_form_has_all_in_both_selectors(plugin):
    """两个站点选择器均提供全部选项。"""
    form, _ = plugin.get_form()
    selectors = {}

    def visit(nodes):
        """遍历声明式表单并提取两个站点选择器。"""
        for node in nodes:
            props = node.get("props", {})
            if props.get("model") in ("sign_sites", "login_sites"):
                selectors[props["model"]] = props["items"]
            visit(node.get("content", []))

    visit(form)
    assert len(selectors) == 2
    for items in selectors.values():
        assert items[0] == {"title": "全部", "value": "all"}


@pytest.mark.parametrize("type_str, method", [("签到", "signin_site"), ("登录", "login_site")])
@pytest.mark.parametrize("retry_keyword", ["失败", None])
def test_all_expands_each_run_and_records_real_ids(plugin, monkeypatch, type_str, method, retry_keyword):
    """全选动态纳入新增站点，按真实ID去重和重试，通知数量不把all当作站点。"""
    sites = [{"id": 1, "name": "站点一"}, {"id": 9, "name": "公开", "public": True}]
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(get_indexers=lambda: sites))
    plugin._retry_keyword = retry_keyword
    today = datetime.today()
    key = type_str + "-" + today.strftime("%Y-%m-%d")
    plugin._AutoSignIn__do(today, type_str, ["all", 1])
    calls = getattr(plugin, method).call_args_list
    assert Counter(call.args[0]["id"] for call in calls) == Counter([1, "custom"])
    history = next(call.kwargs["value"] for call in plugin.save_data.call_args_list if call.kwargs.get("key") == key)
    assert history == {
        "do": [1, "custom"], "retry": [1, "custom"] if retry_keyword is None else [],
        "results": {str(site_id): {"success": True, "message": f"{type_str}成功", "logged_in": True} for site_id in [1, "custom"]},
    }
    assert f"全部{type_str}数量: 2" in plugin.post_message.call_args.kwargs["text"]
    assert plugin.update_config.call_args.args[0]["sign_sites"] == ["all"]
    plugin.get_data.side_effect = lambda key=None: history if key == type_str + "-" + today.strftime("%Y-%m-%d") else None
    sites.append({"id": 2, "name": "新增"})
    getattr(plugin, method).reset_mock()
    plugin._AutoSignIn__do(today, type_str, ["all"])
    expected = [2] if retry_keyword else [1, 2, "custom"]
    assert Counter(call.args[0]["id"] for call in getattr(plugin, method).call_args_list) == Counter(expected)


def test_explicit_selection_stays_limited(plugin, monkeypatch):
    """未选择全部时仅执行指定站点。"""
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(
        get_indexers=lambda: [{"id": 1, "name": "站点一"}, {"id": 2, "name": "站点二"}]))
    plugin._AutoSignIn__do(datetime.today(), "签到", [1])
    assert [call.args[0]["id"] for call in plugin.signin_site.call_args_list] == [1]
