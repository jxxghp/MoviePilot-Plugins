"""TvFirstWatch V3 导入、RSS 解析和生命周期合同测试。"""

from __future__ import annotations

import ast
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/tvfirstwatch/__init__.py"


def _load_plugin(monkeypatch):
    """在未安装插件可选依赖的后端测试环境中，仅为导入探针提供最小模块垫片。"""
    try:
        import feedparser  # noqa: F401
    except ModuleNotFoundError:
        fake_feedparser = types.ModuleType("feedparser")
        fake_feedparser.parse = lambda _text: SimpleNamespace(entries=[])
        monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)
    return importlib.import_module("app.plugins.tvfirstwatch")


def test_manifest_and_plugin_are_v3_aligned() -> None:
    """V3 副本使用现代依赖清单并从公开 SDK 读取媒体上下文。"""
    manifest = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["TvFirstWatch"]
    source = SOURCE.read_text(encoding="utf-8")
    modules = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }

    assert manifest["version"] == "2.0.0"
    assert manifest["system_version"] == ">=3.0.0"
    assert "plugin_version = \"2.0.0\"" in source
    assert "app.sdk.media" in modules
    assert "app.sdk.config" in modules
    assert "app.sdk.logging" in modules
    assert "app.sdk.events" in modules
    assert not any(module.startswith(("app.core.", "app.helper.", "app.utils.", "app.log")) for module in modules)
    assert (ROOT / "plugins.v3/tvfirstwatch/pyproject.toml").is_file()
    assert not (ROOT / "plugins.v3/tvfirstwatch/requirements.txt").exists()


def test_feed_line_and_episode_helpers_preserve_business_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """RSS 行、集号和去重键应保持可重复且无网络副作用。"""
    module = _load_plugin(monkeypatch)
    plugin = object.__new__(module.TvFirstWatch)

    url, headers = plugin._parse_feed_line("https://rss.example/feed | cookie: sid=abc")

    assert url == "https://rss.example/feed"
    assert headers["Cookie"] == "sid=abc"
    assert module._extract_episodes("Example S01E02 1080p") == [2]
    assert module._guess_series_name("Example S01E02 1080p") == "Example"
    assert module._make_key("Example", 2) == "example__ep002"


def test_stop_service_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """调度器停止必须清理任务并允许重复调用。"""
    module = _load_plugin(monkeypatch)
    plugin = object.__new__(module.TvFirstWatch)
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


def test_download_builds_public_context_and_forwards_save_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """下载路径应通过公开 Context/媒体/种子对象传给 DownloadChain。"""
    module = _load_plugin(monkeypatch)

    class FakeMeta:
        def __init__(self, **kwargs):
            self.name = ""
            self.title = kwargs["title"]

    class FakeMedia:
        def __init__(self):
            self.type = None
            self.title = None

    class FakeTorrent:
        def __init__(self, **kwargs):
            self.values = kwargs

    class FakeContext:
        def __init__(self, **kwargs):
            self.values = kwargs

    monkeypatch.setattr(module, "MetaInfo", FakeMeta)
    monkeypatch.setattr(module, "MediaInfo", FakeMedia)
    monkeypatch.setattr(module, "TorrentInfo", FakeTorrent)
    monkeypatch.setattr(module, "Context", FakeContext)

    class Chain:
        def recognize_media(self, **_kwargs):
            return None

    class Download:
        def __init__(self):
            self.kwargs = None

        def download_single(self, **kwargs):
            self.kwargs = kwargs
            return "download-id"

    downloader = Download()
    plugin = object.__new__(module.TvFirstWatch)
    plugin.chain = Chain()
    plugin._downloadchain = downloader
    plugin._save_path = "/downloads"
    entry = {"link": "https://rss.example/item.torrent"}

    assert plugin._do_download(entry, "Example S01E01", "Example") is True
    assert downloader.kwargs["save_path"] == "/downloads"
    assert downloader.kwargs["context"].values["torrent_info"].values["enclosure"] == entry["link"]
