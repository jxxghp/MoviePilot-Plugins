"""MoviePilotUpdateNotify V3 导入、版本线和生命周期合同测试。"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/moviepilotupdatenotify/__init__.py"


def test_manifest_and_plugin_are_v3_aligned() -> None:
    """V3 索引、实现版本和稳定宿主入口必须保持一致。"""
    manifest = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["MoviePilotUpdateNotify"]
    source = SOURCE.read_text(encoding="utf-8")
    modules = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }

    assert manifest["version"] == "3.0.0"
    assert manifest["system_version"] == ">=3.0.0"
    assert "plugin_version = \"3.0.0\"" in source
    assert {"app.sdk.config", "app.sdk.logging", "app.sdk.network", "app.sdk.services"} <= modules
    assert not any(module.startswith(("app.core.", "app.helper.", "app.utils.", "app.log")) for module in modules)


def test_latest_version_uses_v3_release_line(monkeypatch) -> None:
    """更新检查不能把 V2 发布误报为当前 V3 更新。"""
    module = importlib.import_module("app.plugins.moviepilotupdatenotify")

    class Response:
        def json(self):
            return [
                {"tag_name": "v2.99.0"},
                {"tag_name": "v3.9.0"},
                {"tag_name": "v3.10.0"},
            ]

    class Request:
        def __init__(self, **_kwargs):
            pass

        def get_res(self, _url):
            return Response()

    monkeypatch.setattr(module, "RequestUtils", Request)
    latest = module.MoviePilotUpdateNotify._MoviePilotUpdateNotify__get_latest_version("https://example.test/releases")

    assert latest["tag_name"] == "v3.10.0"


def test_stop_service_is_idempotent() -> None:
    """热重载和卸载重复触发时必须释放调度器且不抛错。"""
    module = importlib.import_module("app.plugins.moviepilotupdatenotify")
    plugin = object.__new__(module.MoviePilotUpdateNotify)
    calls: list[str] = []
    plugin._scheduler = SimpleNamespace(
        running=True,
        remove_all_jobs=lambda: calls.append("remove"),
        shutdown=lambda: calls.append("shutdown"),
    )

    plugin.stop_service()
    plugin.stop_service()

    assert calls == ["remove", "shutdown"]
    assert plugin._scheduler is None


def test_notification_converts_github_utc_timestamp_to_configured_timezone(monkeypatch) -> None:
    """GitHub 的 UTC 发布时间应按宿主时区显示，避免通知时间偏移。"""
    module = importlib.import_module("app.plugins.moviepilotupdatenotify")
    plugin = object.__new__(module.MoviePilotUpdateNotify)
    plugin._notify = True
    messages = []
    plugin.post_message = lambda **kwargs: messages.append(kwargs)
    monkeypatch.setattr(module.settings, "TZ", "Asia/Shanghai")

    plugin._MoviePilotUpdateNotify__notify_update(
        "2026-08-31T10:00:00Z", "v3.10.0", "修复更新检查", "后端"
    )

    assert messages[0]["text"].endswith("2026-08-31 18:00:00")
