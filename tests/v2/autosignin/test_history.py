"""签到和登录历史的保留窗口、跨日执行及详情页回显回归。"""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins.autosignin import AutoSignIn


@pytest.fixture
def history_plugin(monkeypatch):
    """模拟插件存储接口与站点结果，冻结时钟且禁止真实站点访问。"""
    plugin = object.__new__(AutoSignIn)
    storage = {}
    clock = Mock(wraps=datetime)
    monkeypatch.setattr("app.plugins.autosignin.datetime", clock)

    def get_data(key=None):
        """无键时返回宿主的数据行，有键时返回独立的持久化值副本。"""
        if key is None:
            return [SimpleNamespace(key=name, value=deepcopy(value)) for name, value in storage.items()]
        return deepcopy(storage.get(key))

    def save_data(key, value):
        """按宿主 JSON 存储语义保存副本，防止测试共享引用掩盖漏写。"""
        storage[key] = deepcopy(value)

    monkeypatch.setattr(plugin, "get_data", get_data)
    monkeypatch.setattr(plugin, "save_data", save_data)
    monkeypatch.setattr(plugin, "del_data", lambda key: storage.pop(key, None))
    monkeypatch.setattr(plugin, "update_config", Mock())
    monkeypatch.setattr(plugin, "_AutoSignIn__custom_sites", lambda: [])
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(
        get_indexers=lambda: [{"id": 1, "name": "签到站"}, {"id": 2, "name": "登录站"}]))
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", lambda: SimpleNamespace(
        list_order_by_pri=lambda: []))
    monkeypatch.setattr(plugin, "signin_site", Mock(return_value=("签到站", "签到成功")))
    monkeypatch.setattr(plugin, "login_site", Mock(return_value=("登录站", "模拟登录成功")))
    plugin._sign_sites = [1]
    plugin._login_sites = [2]
    plugin._notify = False
    plugin._clean = False
    plugin._retry_keyword = "失败"
    plugin._auto_cf = 0
    return plugin, storage, clock


def day_records(day):
    """构造同一天的签到、登录状态与共享明细。"""
    return {
        f"签到-{day:%Y-%m-%d}": {"do": [1], "retry": []},
        f"登录-{day:%Y-%m-%d}": {"do": [2], "retry": []},
        f"{day.month}月{day.day}日": [
            {"site": "签到站", "status": "签到成功"},
            {"site": "登录站", "status": "模拟登录成功"},
        ],
    }


def page_nodes(nodes):
    """遍历声明式详情页，检查最终供前端渲染的状态节点。"""
    for node in nodes:
        yield node
        yield from page_nodes(node.get("content", []))


@pytest.mark.parametrize("type_str, site_id", [("签到", 1), ("登录", 2)])
def test_cleanup_after_gap_preserves_window_and_unrelated_data(history_plugin, type_str, site_id):
    """停跑后删除全部过期历史，保留第14天、昨天及非历史数据；已完成时仍清理。"""
    plugin, storage, clock = history_plugin
    today = datetime(2026, 10, 1, 14)
    clock.now.return_value = today
    expected = {"note": {"value": "保留"}, "签到-invalid": {}, "签到-2026-02-30": {}}
    for age in (0, 1, 2, 6, 13):
        expected.update(day_records(today - timedelta(days=age)))
    storage.update(deepcopy(expected))
    for age in (14, 15, 45):
        storage.update(day_records(today - timedelta(days=age)))

    plugin._AutoSignIn__do(today, type_str, [site_id])

    assert storage == expected
    plugin.signin_site.assert_not_called()
    plugin.login_site.assert_not_called()


@pytest.mark.parametrize("today", [datetime(2026, 10, 1), datetime(2027, 1, 2), datetime(2028, 3, 1)])
def test_daily_execution_retains_fourteen_days_and_renders_matrix(history_plugin, today):
    """连续签到和登录跨月、跨年或闰日时保留14天，并向矩阵提供最近7天成功状态。"""
    plugin, storage, clock = history_plugin
    for age in reversed(range(20)):
        day = today - timedelta(days=age)
        clock.now.return_value = day
        for _ in range(2):
            plugin._AutoSignIn__do(day, "签到", [1])
            plugin._AutoSignIn__do(day, "登录", [2])

    expected = {}
    for age in range(14):
        expected.update(day_records(today - timedelta(days=age)))
    assert storage == expected
    assert plugin.signin_site.call_count == 20
    assert plugin.login_site.call_count == 20

    nodes = list(page_nodes(plugin.get_page()))
    dots = [node for node in nodes if node.get("props", {}).get("class", "").startswith("autosignin-dot ")]
    assert len(dots) == 14
    assert all(node["props"]["class"].endswith("--success") for node in dots)
    for age in range(7):
        day = today - timedelta(days=age)
        label = f"{day.month}月{day.day}日"
        assert [node["props"]["title"] for node in dots if node["props"]["title"].startswith(label + " ")] == [
            f"{label} 已签到", f"{label} 登录成功",
        ]
    assert any(node.get("text") == "14天" for node in nodes)


@pytest.mark.parametrize("type_str, site_id, method", [("签到", 1, "signin_site"), ("登录", 2, "login_site")])
def test_retry_and_forced_run_preserve_previous_days(history_plugin, type_str, site_id, method):
    """当天失败重试和强制重跑仅更新当天状态，不删除已有历史。"""
    plugin, storage, clock = history_plugin
    today = datetime(2026, 10, 1)
    clock.now.return_value = today
    yesterday = day_records(today - timedelta(days=1))
    storage.update(deepcopy(yesterday))
    task = getattr(plugin, method)
    site_name = task.return_value[0]
    task.side_effect = [(site_name, "请求失败"), task.return_value, task.return_value]
    key = f"{type_str}-{today:%Y-%m-%d}"

    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert storage[key] == {"do": [site_id], "retry": [site_id]}
    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert storage[key] == {"do": [site_id], "retry": []}
    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert task.call_count == 2
    plugin._clean = True
    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert task.call_count == 3
    assert plugin._clean is False
    assert {key: storage[key] for key in yesterday} == yesterday
