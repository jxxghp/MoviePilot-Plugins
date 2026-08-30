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


def test_api_uses_host_bearer_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    """页面 API 使用宿主登录态认证，避免把 API token 拼进页面请求。"""
    module = _load_plugin(monkeypatch)
    plugin = object.__new__(module.TvFirstWatch)
    plugin._history_path = None

    apis = plugin.get_api()

    assert [api["auth"] for api in apis] == ["bear", "bear"]
    assert all("token" not in api for api in apis)


def test_api_declares_exact_response_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """动态路由应声明与实际 JSON 字段一致的输出模型。"""
    module = _load_plugin(monkeypatch)
    plugin = object.__new__(module.TvFirstWatch)
    plugin._history_path = None

    apis = {api["path"]: api for api in plugin.get_api()}

    assert apis["/clear_history"]["response_model"] is module.ClearHistoryResponse
    assert apis["/storage_status"]["response_model"] is module.StorageStatusResponse

    assert module.ClearHistoryResponse.model_validate(
        plugin._clear_history()
    ).model_dump() == {"success": True, "message": "历史已清空"}


def test_storage_status_response_model_matches_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """存储状态接口返回值应可被声明模型完整校验。"""
    module = _load_plugin(monkeypatch)
    plugin = object.__new__(module.TvFirstWatch)
    plugin._history_path = None
    plugin._max_storage_gb = 12

    response = plugin._storage_status()

    assert module.StorageStatusResponse.model_validate(response).model_dump() == {
        "success": True,
        "total_bytes": 0,
        "total_gb": 0.0,
        "max_gb": 12,
        "count": 0,
    }


def test_rss_logs_never_include_passkey_or_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """RSS 凭据只能用于请求，日志只允许出现来源 host 和异常类型。"""
    module = _load_plugin(monkeypatch)
    records: list[str] = []

    class Logger:
        def info(self, message, *args):
            records.append(str(message) % args if args else str(message))

        def error(self, message, *args):
            records.append(str(message) % args if args else str(message))

        def warning(self, message, *args):
            records.append(str(message) % args if args else str(message))

    monkeypatch.setattr(module, "logger", Logger())
    plugin = object.__new__(module.TvFirstWatch)
    plugin._rss_urls = "https://alice:secret@rss.example/feed?passkey=secret|Cookie: sid=private"
    plugin._process_feed = lambda _line: (_ for _ in ()).throw(RuntimeError("sid=private"))

    plugin._check_all_feeds()

    output = "\n".join(records)
    assert "rss.example" in output
    assert "alice" not in output
    assert "secret" not in output
    assert "private" not in output


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
