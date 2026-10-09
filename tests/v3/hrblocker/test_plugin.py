"""H&R Blocker V3 的元数据合同与拦截逻辑测试。"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/hrblocker/__init__.py"


def _load_plugin():
    return importlib.import_module("app.plugins.hrblocker")


def _make_plugin(module):
    """绕过运行时组装实例化插件（裸测试进程无组合根），并打桩持久化。"""
    plugin = object.__new__(module.HRBlocker)
    plugin._enabled = True
    plugin._block_marked = True
    plugin._sync_assistant = False
    plugin._block_manual = True
    plugin._notify = False
    plugin._records = []
    plugin.save_data = lambda *args, **kwargs: None
    return plugin


def _context(title, hit_and_run=False):
    torrent = SimpleNamespace(title=title, hit_and_run=hit_and_run, site=None, site_name="测试站")
    return SimpleNamespace(torrent_info=torrent)


def test_v3_metadata_and_legacy_indexes_are_aligned() -> None:
    """V3 版本、宿主下限、release 标记和旧索引禁用标记必须一致。"""
    module = _load_plugin()
    v3 = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))

    assert module.HRBlocker.plugin_version == "2.0.0"
    assert v3["HRBlocker"]["version"] == "2.0.0"
    assert v3["HRBlocker"]["system_version"] == ">=3.0.0"
    assert v3["HRBlocker"]["release"] is True
    assert v3["HRBlocker"]["history"]["v2.0.0"]
    assert v2["HRBlocker"]["v3"] is False


def test_plugin_does_not_import_host_orm_models() -> None:
    """插件数据只能通过 PluginBase 合同访问，不能导入宿主 ORM 模型。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("app.db.models")
        for node in ast.walk(tree)
    )


def test_apis_use_bearer_auth() -> None:
    """插件 API 使用宿主登录态（bear），源码不得出现 apikey。"""
    module = _load_plugin()
    plugin = _make_plugin(module)

    apis = plugin.get_api()

    assert apis
    assert all(api.get("auth") == "bear" for api in apis)
    assert "apikey" not in SOURCE.read_text(encoding="utf-8")


def test_marked_torrent_blocked_and_normal_passes() -> None:
    """站点标记 H&R 的种子被判定拦截，普通种子放行。"""
    module = _load_plugin()
    plugin = _make_plugin(module)

    blocked, reason = plugin._HRBlocker__is_hr_context(_context("HR 种子", True))
    assert blocked is True and reason == "站点标记H&R"

    blocked, _ = plugin._HRBlocker__is_hr_context(_context("普通种子", False))
    assert blocked is False


def test_selection_event_filters_and_records_subscribe_stage() -> None:
    """订阅来源的选择事件剔除 H&R 候选，并记录为「订阅拦截」。"""
    module = _load_plugin()
    plugin = _make_plugin(module)
    from app.schemas.event import ResourceSelectionEventData

    data = ResourceSelectionEventData(
        contexts=[_context("普通种子"), _context("HR 种子", True)],
        origin="Subscribe",
    )
    plugin.on_resource_selection(event=SimpleNamespace(event_data=data))

    assert data.updated is True
    assert [c.torrent_info.title for c in data.updated_contexts] == ["普通种子"]
    assert plugin._records[0]["stage"] == "订阅拦截"
    assert plugin._records[0]["title"] == "HR 种子"


def test_selection_event_other_origin_keeps_generic_stage() -> None:
    """非订阅来源的选择事件记录为「资源选择」。"""
    module = _load_plugin()
    plugin = _make_plugin(module)
    from app.schemas.event import ResourceSelectionEventData

    data = ResourceSelectionEventData(contexts=[_context("HR 种子", True)], origin="消息搜索")
    plugin.on_resource_selection(event=SimpleNamespace(event_data=data))

    assert plugin._records[0]["stage"] == "资源选择"


def test_download_event_cancels_marked_torrent() -> None:
    """下载事件兜底拦截 H&R 种子（含手动下载），记录为「下载拦截」。"""
    module = _load_plugin()
    plugin = _make_plugin(module)
    from app.schemas.event import ResourceDownloadEventData

    data = ResourceDownloadEventData(context=_context("HR 种子", True), origin="Manual")
    plugin.on_resource_download(event=SimpleNamespace(event_data=data))

    assert data.cancel is True
    assert data.source == "H&R Blocker"
    assert plugin._records[0]["stage"] == "下载拦截"

    # 普通种子不拦截
    data2 = ResourceDownloadEventData(context=_context("普通种子"), origin="Manual")
    plugin.on_resource_download(event=SimpleNamespace(event_data=data2))
    assert data2.cancel is False


def test_search_event_filters_items_and_rewrites_totals() -> None:
    """渐进式搜索事件剔除 H&R 条目并同步扣减 total_items。"""
    module = _load_plugin()
    plugin = _make_plugin(module)

    event, cum = plugin.hr_filter_event({
        "type": "append",
        "items": [
            {"torrent_info": {"title": "HR 种子", "hit_and_run": True}},
            {"torrent_info": {"title": "普通种子", "hit_and_run": False}},
        ],
        "total_items": 5,
    }, 0)

    assert [i["torrent_info"]["title"] for i in event["items"]] == ["普通种子"]
    assert event["total_items"] == 4
    assert cum == 1
    assert plugin._records[0]["stage"] == "显示拦截"

    # replace 事件按最终全量重算并改写文案
    event2, _ = plugin.hr_filter_event({
        "type": "replace",
        "text": "过滤匹配完成，共 9 个资源",
        "items": [{"torrent_info": {"title": "普通种子", "hit_and_run": False}}],
        "total_items": 9,
    }, cum)
    assert event2["total_items"] == 1
    assert "共 1 个资源" in event2["text"]


def test_display_records_deduplicate_same_title() -> None:
    """显示拦截记录按标题+分类去重，避免重复搜索刷屏。"""
    module = _load_plugin()
    plugin = _make_plugin(module)

    for _ in range(3):
        plugin.hr_filter_event({
            "type": "append",
            "items": [{"torrent_info": {"title": "HR 种子", "hit_and_run": True}}],
            "total_items": 1,
        }, 0)

    assert len([r for r in plugin._records if r["title"] == "HR 种子" and r["stage"] == "显示拦截"]) == 1


def test_clear_records_empties_memory() -> None:
    """清除记录接口清空内存与持久化数据。"""
    module = _load_plugin()
    plugin = _make_plugin(module)
    plugin._records = [{"time": "t", "title": "x", "site": "", "reason": "", "source": "", "stage": ""}]

    result = plugin.api_clear_records()

    assert result["total"] == 0
    assert plugin._records == []
