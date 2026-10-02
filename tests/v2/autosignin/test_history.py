"""签到和登录历史的保留窗口、跨日执行及详情页回显回归。"""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.result import SiteResult


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
    monkeypatch.setattr(plugin, "signin_site", Mock(return_value=SiteResult("签到站", "签到成功", True, True)))
    monkeypatch.setattr(plugin, "login_site", Mock(return_value=SiteResult("登录站", "模拟登录成功", True, True)))
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
        f"签到-{day:%Y-%m-%d}": {"do": [1], "retry": [], "results": {"1": {"success": True, "message": "签到成功", "logged_in": True}}},
        f"登录-{day:%Y-%m-%d}": {"do": [2], "retry": [], "results": {"2": {"success": True, "message": "模拟登录成功", "logged_in": True}}},
        f"{day.month}月{day.day}日": [
            {"site": "签到站", "status": "签到成功", "site_id": 1, "type": "签到", "success": True, "logged_in": True},
            {"site": "登录站", "status": "模拟登录成功", "site_id": 2, "type": "登录", "success": True, "logged_in": True},
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
    assert len(dots) == 21
    assert all(node["props"]["class"].endswith("--success") for node in dots)
    for age in range(7):
        day = today - timedelta(days=age)
        label = f"{day.month}月{day.day}日"
        assert sorted(node["props"]["title"] for node in dots if node["props"]["title"].startswith(label + " ")) == sorted([
            f"{label} 签到成功", f"{label} 登录成功", f"{label} 模拟登录成功",
        ])
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
    task.side_effect = [SiteResult(site_name, "请求失败", False), task.return_value, task.return_value]
    key = f"{type_str}-{today:%Y-%m-%d}"

    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert storage[key] == {"do": [site_id], "retry": [site_id],
                            "results": {str(site_id): {"success": False, "message": "请求失败", "logged_in": False}}}
    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert storage[key] == {"do": [site_id], "retry": [],
                            "results": {str(site_id): {"success": True, "message": task.return_value.message, "logged_in": True}}}
    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert task.call_count == 2
    plugin._clean = True
    plugin._AutoSignIn__do(today, type_str, [site_id])
    assert task.call_count == 3
    assert plugin._clean is False
    assert {key: storage[key] for key in yesterday} == yesterday


@pytest.mark.parametrize("retry_keyword", ["超时", None])
def test_failed_result_is_retried_and_never_rendered_as_success(history_plugin, monkeypatch, retry_keyword):
    """失败未命中关键词也必须重试，通知、历史和详情页均保持失败。"""
    plugin, storage, clock = history_plugin
    today = datetime(2026, 10, 2)
    clock.now.return_value = today
    plugin._notify = True
    plugin._retry_keyword = retry_keyword
    notify = Mock()
    monkeypatch.setattr(plugin, "post_message", notify)
    plugin.signin_site.return_value = SiteResult("签到站", "签到失败，未确认签到结果", False)

    plugin._AutoSignIn__do(today, "签到", [1])

    assert storage["签到-2026-10-02"]["retry"] == [1]
    text = notify.call_args.kwargs["text"]
    assert "未确认签到结果" in text and "【签到站】签到成功" not in text and "下次签到数量: 1" in text
    nodes = list(page_nodes(plugin.get_page()))
    dots = [node for node in nodes if node.get("props", {}).get("title", "").startswith("10月2日 ")]
    assert any(node["props"].get("class", "").endswith("--error") for node in dots)
    assert not any(node["props"].get("class", "").endswith("--success") for node in dots)
    plugin._AutoSignIn__do(today, "签到", [1])
    assert plugin.signin_site.call_count == 2


def test_old_attempt_without_evidence_is_rechecked(history_plugin):
    """升级后的当日旧 do 记录可能是假成功，缺少明确结果时重新执行。"""
    plugin, storage, clock = history_plugin
    today = datetime(2026, 10, 2)
    clock.now.return_value = today
    storage["签到-2026-10-02"] = {"do": [1], "retry": []}
    plugin._AutoSignIn__do(today, "签到", [1])
    plugin.signin_site.assert_called_once()
    assert storage["签到-2026-10-02"]["results"]["1"]["success"] is True


@pytest.mark.parametrize("detail", [None, "签到失败，验证码错误", "仿真签到成功", "签到成功"])
def test_legacy_history_does_not_invent_success(history_plugin, detail):
    """旧 do 不能覆盖失败明细；没有明细或仅有仿真登录证据时也不能显示签到成功。"""
    plugin, storage, clock = history_plugin
    clock.now.return_value = datetime(2026, 10, 2)
    storage["签到-2026-10-02"] = {"do": [1], "retry": []}
    if detail:
        storage["10月2日"] = [{"site": "签到站", "status": detail}]
    nodes = list(page_nodes(plugin.get_page()))
    dots = [node for node in nodes if node.get("props", {}).get("title", "").startswith("10月2日 ")]
    assert not any(node["props"].get("class", "").endswith("--success") for node in dots)


def test_login_only_result_is_not_counted_as_signin(history_plugin):
    """仅模拟登录的站点可以完成访问任务，但不能在签到矩阵中显示绿色签到成功。"""
    plugin, _storage, clock = history_plugin
    today = datetime(2026, 10, 2)
    clock.now.return_value = today
    plugin.signin_site.return_value = SiteResult("签到站", "模拟登录成功（未执行签到）", False, True)
    plugin._AutoSignIn__do(today, "签到", [1])
    nodes = list(page_nodes(plugin.get_page()))
    dots = [node for node in nodes if "未执行签到" in node.get("props", {}).get("title", "")]
    assert dots and all(node["props"]["class"].endswith("--warning") for node in dots)


@pytest.mark.parametrize("retry_keyword, should_retry", [("错误|失败", False), ("未确认", True), (None, True)])
def test_confirmed_login_is_preserved_without_becoming_signin_success(history_plugin, monkeypatch, retry_keyword, should_retry):
    """已登录但签到未确认单独显示登录成功，默认不重试；保留用户主动重试配置。"""
    plugin, storage, clock = history_plugin
    today = datetime(2026, 10, 2)
    clock.now.return_value = today
    plugin._notify = True
    plugin._retry_keyword = retry_keyword
    plugin._login_sites = []
    notify = Mock()
    summary = Mock(wraps=plugin._build_summary)
    monkeypatch.setattr(plugin, "post_message", notify)
    monkeypatch.setattr(plugin, "_build_summary", summary)
    monkeypatch.setattr(plugin, "eventmanager", SimpleNamespace(send_event=Mock()), raising=False)
    plugin.signin_site.return_value = SiteResult("签到站", "登录成功，签到未确认", False, True)

    plugin._AutoSignIn__do(today, "签到", [1])

    history = storage["签到-2026-10-02"]
    assert history["retry"] == ([1] if should_retry else [])
    assert history["results"]["1"] == {"success": False, "logged_in": True, "message": "登录成功，签到未确认"}
    text = notify.call_args.kwargs["text"]
    assert "确认签到成功: 0" in text and "仅确认登录: 1" in text and "登录或访问失败: 0" in text
    assert "【签到站】登录成功，签到未确认" in text
    nodes = list(page_nodes(plugin.get_page()))
    stats = summary.call_args.kwargs
    assert stats["signin_stats"]["success"] == 0 and stats["signin_stats"]["error"] == 0
    assert stats["signin_stats"]["warning"] == 1
    assert stats["login_stats"]["success"] == 1
    dots = [node for node in nodes if node.get("props", {}).get("class", "").startswith("autosignin-dot ")]
    assert any(node["props"]["title"] == "10月2日 登录成功" and node["props"]["class"].endswith("--success") for node in dots)
    assert any(node["props"]["title"] == "10月2日 登录成功，签到未确认" and node["props"]["class"].endswith("--warning") for node in dots)
    plugin.eventmanager.send_event.assert_not_called()
    plugin._AutoSignIn__do(today, "签到", [1])
    assert plugin.signin_site.call_count == (2 if should_retry else 1)


def test_mixed_signin_login_and_failure_counts_are_separate(history_plugin, monkeypatch):
    """混合结果按三类计数，后续任务仅重试真正没有完成访问的站点。"""
    plugin, storage, clock = history_plugin
    today = datetime(2026, 10, 2)
    clock.now.return_value = today
    plugin._notify = True
    notify = Mock()
    monkeypatch.setattr(plugin, "post_message", notify)
    sites = [{"id": site_id, "name": f"站点{site_id}"} for site_id in (1, 2, 3)]
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(get_indexers=lambda: sites))
    outcomes = {
        1: SiteResult("站点1", "签到成功", True, True),
        2: SiteResult("站点2", "登录成功，签到未确认", False, True),
        3: SiteResult("站点3", "签到失败，状态码：404；模拟登录失败，状态码：468", False),
    }
    plugin.signin_site.side_effect = lambda site: outcomes[site["id"]]
    plugin._AutoSignIn__do(today, "签到", [1, 2, 3])
    text = notify.call_args.kwargs["text"]
    assert "确认签到成功: 1" in text and "仅确认登录: 1" in text and "登录或访问失败: 1" in text
    assert "下次签到数量: 1" in text
    assert storage["签到-2026-10-02"]["retry"] == [3]
    plugin.signin_site.reset_mock()
    plugin._AutoSignIn__do(today, "签到", [1, 2, 3])
    assert [call.args[0]["id"] for call in plugin.signin_site.call_args_list] == [3]


def test_retry_preserves_other_site_results_and_uses_real_ids(history_plugin, monkeypatch):
    """同名站点、自定义站点按 ID 分别记录；仅重试失败项时保留其他站点成功证据。"""
    plugin, storage, clock = history_plugin
    today = datetime(2026, 10, 2)
    clock.now.return_value = today
    sites = [{"id": 1, "name": "同名"}, {"id": 2, "name": "同名"}]
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(get_indexers=lambda: sites))
    monkeypatch.setattr(plugin, "_AutoSignIn__custom_sites", lambda: [{"id": "custom", "name": "自定义"}])
    plugin._retry_keyword = "超时"
    plugin.signin_site.side_effect = lambda site: SiteResult(
        site["name"], "签到成功" if site["id"] == 1 else "签到失败", site["id"] == 1)
    plugin._AutoSignIn__do(today, "签到", [1, 2, "custom"])
    assert storage["签到-2026-10-02"]["retry"] == [2, "custom"]
    nodes = list(page_nodes(plugin.get_page()))
    assert any(node.get("text") == "同名（1）" for node in nodes)
    assert any(node.get("text") == "同名（2）" for node in nodes)
    plugin.signin_site.reset_mock()
    plugin.signin_site.side_effect = lambda site: SiteResult(site["name"], "签到成功", True)
    plugin._AutoSignIn__do(today, "签到", [1, 2, "custom"])
    assert {call.args[0]["id"] for call in plugin.signin_site.call_args_list} == {2, "custom"}
    history = storage["签到-2026-10-02"]
    assert history["retry"] == []
    assert all(history["results"][site_id]["success"] for site_id in ("1", "2", "custom"))
