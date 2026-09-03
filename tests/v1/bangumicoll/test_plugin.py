"""BangumiColl 插件加载与新版订阅统计入口回归测试。"""

from __future__ import annotations

import importlib
import sys
import types


def test_import_without_legacy_subscribe_helper() -> None:
    """新版 MoviePilot 已移除 app.helper.subscribe，插件导入不应再依赖旧模块。"""
    sys.modules.pop("bangumicoll", None)
    sys.modules.pop("app.helper.subscribe", None)

    plugin_module = importlib.import_module("bangumicoll")

    assert plugin_module.BangumiColl.plugin_version == "1.5.9"
    assert not hasattr(plugin_module, "SubscribeHelper")


def test_delete_subscribe_reports_done_via_server_helper(monkeypatch) -> None:
    """删除订阅后通过 MoviePilotServerHelper 同步订阅统计。"""
    plugin_module = importlib.import_module("bangumicoll")
    plugin = object.__new__(plugin_module.BangumiColl)
    subscribe = types.SimpleNamespace(
        tmdbid=12345,
        doubanid="67890",
        name="测试番剧",
        year="2026",
        season=1,
        username="tester",
        date="2026-06-18 00:00:00",
        backdrop="",
    )
    calls = []

    class FakeSubscribeOper:
        """隔离数据库访问，只记录插件删除订阅时的行为。"""

        def get(self, subscribe_id):
            return subscribe if subscribe_id == 1 else None

        def delete(self, subscribe_id):
            calls.append(("delete", subscribe_id))

    monkeypatch.setattr(plugin_module, "SubscribeOper", FakeSubscribeOper)
    monkeypatch.setattr(
        plugin_module.MoviePilotServerHelper,
        "sub_done_async",
        lambda payload: calls.append(("sub_done_async", payload)),
    )
    monkeypatch.setattr(
        plugin,
        "post_message",
        lambda **kwargs: calls.append(("post_message", kwargs)),
    )

    plugin.delete_subscribe({1: 3})

    assert ("delete", 1) in calls
    assert ("sub_done_async", {"tmdbid": 12345, "doubanid": "67890"}) in calls
    assert any(call[0] == "post_message" for call in calls)
