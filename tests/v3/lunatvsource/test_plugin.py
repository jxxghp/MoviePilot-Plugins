from app.plugins.lunatvsource import LunaTVSource
import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource.cms import CmsSource, _result_from_item
from app.plugins.lunatvsource.naming import media_path
import hashlib
from pathlib import Path
import sys
from enum import Enum
from types import ModuleType, SimpleNamespace


def _plugin(config):
    class PluginData:
        def __init__(self):
            self.values = {}

        def get_data(self, _plugin_id, key):
            return self.values.get(key)

        def save(self, _plugin_id, key, value):
            self.values[key] = value

    plugin = object.__new__(LunaTVSource)
    plugin.plugindata = PluginData()
    plugin._logger = plugin_module.LOGGER
    plugin.init_plugin(config)
    return plugin


def test_status_exposes_serial_queue_and_ai_fallback():
    plugin = _plugin({"enabled": True, "ai_enabled": False})
    status = plugin.api_status()["data"]
    assert status["enabled"] is True
    assert status["queue"]["pending"] == 0
    assert status["ai"]["enabled"] is True
    assert status["ai"]["available"] is False
    assert status["media_source"] == "lunatv"
    assert plugin.get_sidebar_nav() == []


def test_manual_download_rejects_non_http_url():
    plugin = _plugin({"enabled": True, "download_root": "/tmp/lunatv-test"})
    result = plugin.api_download({"url": "file:///tmp/movie.m3u8"})
    assert result["success"] is False
    assert "http/https" in result["message"]


def test_directory_settings_are_used_when_plugin_root_is_empty(monkeypatch):
    class Directory:
        storage = "local"
        download_path = "/media/courses"
        library_path = "/media/library/courses"
        media_type = "电视剧"
        priority = 1
        name = "课程目录"

    class DirectoryHelper:
        def get_download_dirs(self):
            return [Directory()]

    monkeypatch.setattr(plugin_module, "_HostDirectoryHelper", DirectoryHelper)
    plugin = _plugin({"enabled": True, "use_moviepilot_dirs": False})
    assert plugin._effective_root(media_type="tv") == "/media/courses"
    assert plugin.api_status()["data"]["directories"]["source"] == "MoviePilot 目录设置"


def test_tmdb_association_can_map_flat_seasons(monkeypatch):
    class Source:
        TMDB = "themoviedb"

    class Meta:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Media:
        media_id = "123"
        tmdb_id = 123
        media_source = "themoviedb"
        title = "示例剧"
        year = "2024"
        seasons = {1: [1, 2], 2: [1]}

    class MediaChain:
        def recognize_media(self, **kwargs):
            return Media()

        def search_medias(self, **kwargs):
            return [Media()]

    monkeypatch.setattr(plugin_module, "_HostMediaSource", Source)
    monkeypatch.setattr(plugin_module, "_HostMetaInfo", Meta)
    monkeypatch.setattr(plugin_module, "_HostMediaChain", MediaChain)
    plugin = _plugin({"enabled": True, "tmdb_association": False})
    result = _result_from_item(
        CmsSource("demo", "演示", "https://cms.example/vod"),
        {
            "vod_id": "1",
            "vod_name": "示例剧 1-2季",
            "type_name": "电视剧",
            "vod_play_from": "在线播放",
            "vod_play_url": "01$https://example.test/01.m3u8#02$https://example.test/02.m3u8#03$https://example.test/03.m3u8",
        },
    )
    prepared, association = plugin._prepare_result(result)
    assert association["status"] == "matched"
    assert association["candidates"][0]["media_id"] == "123"
    assert [(episode.season, episode.episode) for episode in prepared.episodes] == [(1, 1), (1, 2), (2, 1)]


def test_tmdb_candidate_search_returns_compact_choices(monkeypatch):
    class Source:
        TMDB = "themoviedb"

    class Meta:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Media:
        media_id = "456"
        tmdb_id = 456
        media_source = "themoviedb"
        title = "候选作品"
        year = "2023"
        type = "电影"
        season = None
        seasons = {}

    class MediaChain:
        def search_medias(self, **kwargs):
            return [Media(), Media()]

    monkeypatch.setattr(plugin_module, "_HostMediaSource", Source)
    monkeypatch.setattr(plugin_module, "_HostMetaInfo", Meta)
    monkeypatch.setattr(plugin_module, "_HostMediaChain", MediaChain)
    plugin = _plugin({"enabled": True, "tmdb_association": True})
    response = plugin.api_tmdb_search({"title": "候选作品", "media_type": "movie"})
    assert response["success"] is True
    assert response["data"] == [{
        "media_source": "themoviedb",
        "media_id": "456",
        "tmdb_id": 456,
        "title": "候选作品",
        "year": "2023",
        "type": "电影",
        "season": None,
        "season_counts": {},
    }]


def test_host_meta_info_uses_v3_function_signature(monkeypatch):
    calls = []

    def meta_info(*, title):
        calls.append(title)
        return type("Meta", (), {"type": "电影"})()

    monkeypatch.setattr(plugin_module, "_HostMetaInfo", meta_info)
    plugin = _plugin({"enabled": True})
    meta = plugin._host_meta_info("示例作品", "2024")
    assert calls == ["示例作品 (2024)"]
    assert meta.type == "电影"


def test_discover_accepts_native_keyword_and_stops_after_first_source(monkeypatch):
    calls = []

    class Client:
        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return []

    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    response = plugin.api_discover(keyword="示例电影")
    assert response == {"success": True, "data": []}
    assert calls == [
        (
            "示例电影",
            {"limit": 30, "stop_after_first_source": True, "enrich": False},
        )
    ]


def test_global_media_search_returns_lunatv_cards_without_explore_tab(monkeypatch):
    class Client:
        def search(self, query, **kwargs):
            assert query == "示例电影"
            assert kwargs == {"limit": 8, "stop_after_first_source": True, "enrich": False}
            return [_result_from_item(
                CmsSource("demo", "演示源", "https://cms.example/vod"),
                {"vod_id": "42", "vod_name": "示例电影", "type_name": "电影"},
            )]

    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(plugin, "_media_info", lambda result, association: result)
    meta = type("Meta", (), {"name": "示例电影", "year": "", "type": "电影"})()
    results = plugin.search_medias(meta=meta)
    assert len(results) == 1
    assert results[0].title == "示例电影"
    assert plugin.get_media_source() == []


def test_global_media_search_respects_explicit_other_source():
    plugin = _plugin({"enabled": True})
    meta = type("Meta", (), {"name": "示例电影"})()
    assert plugin.search_medias(meta=meta, media_source=("themoviedb",)) == []


def test_native_resource_search_returns_marked_download_items(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def to_dict(self):
            return dict(self.__dict__)

    class Client:
        def search(self, query, **kwargs):
            return [_result_from_item(
                CmsSource("demo", "演示源", "https://cms.example/vod", "https://cms.example"),
                {
                    "vod_id": "42",
                    "vod_name": "示例剧",
                    "vod_year": "2024",
                    "type_name": "电视剧",
                    "vod_play_from": "在线播放",
                    "vod_play_url": "01$https://example.test/01.m3u8",
                },
            )]

    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda result: (result, {"media_source": "themoviedb", "media_id": "123"}),
    )
    items = plugin.search_torrents(site={"id": 1}, keyword="示例剧", page=0)
    assert len(items) == 1
    assert items[0].site_name == "演示源"
    assert items[0].to_dict()["site_name"] == "演示源"
    assert items[0].media_source == "themoviedb"
    assert items[0].media_id == "123"
    assert items[0].title.endswith("S01E01")
    payload = plugin._decode_resource_token(items[0].enclosure)
    assert payload["url"].endswith("01.m3u8")
    assert payload["source_key"] == "demo"
    assert payload["source_name"] == "演示源"
    assert payload["host_media_source"] == "themoviedb"
    assert payload["host_media_id"] == "123"


def test_resource_torrents_dedupes_play_urls_from_multiple_sources(monkeypatch):
    calls = []

    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def to_dict(self):
            return dict(self.__dict__)

    class Client:
        def search(self, query, **kwargs):
            calls.append(kwargs)
            return [
                _result_from_item(
                    CmsSource("first", "源A", "https://cms.example/vod", "https://cms.example"),
                    {
                        "vod_id": "1",
                        "vod_name": "示例剧",
                        "type_name": "电视剧",
                        "vod_play_from": "在线播放",
                        "vod_play_url": "01$https://example.test/01.m3u8",
                    },
                ),
                _result_from_item(
                    CmsSource("second", "源B", "https://cms2.example/vod", "https://cms2.example"),
                    {
                        "vod_id": "2",
                        "vod_name": "示例剧",
                        "type_name": "电视剧",
                        "vod_play_from": "在线播放",
                        "vod_play_url": "01$https://example.test/01.m3u8",
                    },
                ),
                _result_from_item(
                    CmsSource("first", "源A", "https://cms.example/vod", "https://cms.example"),
                    {
                        "vod_id": "3",
                        "vod_name": "示例剧",
                        "type_name": "电视剧",
                        "vod_play_from": "在线播放",
                        "vod_play_url": "02$https://example.test/02.m3u8",
                    },
                ),
            ]

    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda result: (result, {"media_source": "themoviedb", "media_id": "123"}),
    )
    items = plugin.search_torrents(site={"id": 1}, keyword="示例剧", page=0, mtype="tv")
    assert len(items) == 2
    urls = sorted([plugin._decode_resource_token(item.enclosure)["url"] for item in items])
    assert urls == ["https://example.test/01.m3u8", "https://example.test/02.m3u8"]
    assert [item.site_name for item in items] == ["源A", "源A"]
    assert calls == [{
        "limit": 50,
        "source_limit": 3,
        "stop_after_first_source": False,
        "require_playable": True,
        "max_workers": 8,
    }]


def test_resource_search_does_not_hold_cache_lock_during_network_request(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    plugin = _plugin({"enabled": True})
    lock_available = []

    class Client:
        def search(self, query, **kwargs):
            acquired = plugin._resource_search_lock.acquire(blocking=False)
            lock_available.append(acquired)
            if acquired:
                plugin._resource_search_lock.release()
            return []

    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())

    assert plugin.search_torrents(site={"id": 1}, keyword="示例剧", page=0) == []
    assert lock_available == [True]


def test_plugin_search_bridge_augments_native_search_and_restores(monkeypatch):
    class SearchChain:
        def __search_all_sites(self, **kwargs):
            return ["native-sync"]

        async def __async_search_all_sites(self, **kwargs):
            return ["native-async"]

        async def __async_search_all_sites_stream(self, **kwargs):
            yield {"type": "done", "text": "native done", "items": []}

    app_module = ModuleType("app")
    chain_module = ModuleType("app.chain")
    search_module = ModuleType("app.chain.search")
    search_module.SearchChain = SearchChain
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.chain", chain_module)
    monkeypatch.setitem(sys.modules, "app.chain.search", search_module)
    plugin_module._SEARCH_BRIDGE.update({"owner": None, "chain": None, "originals": {}})

    sync_original = SearchChain._SearchChain__search_all_sites
    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin, "search_torrents", lambda **kwargs: ["plugin-sync"])

    async def async_plugin_search(**kwargs):
        return ["plugin-async"]

    monkeypatch.setattr(plugin, "async_search_torrents", async_plugin_search)
    chain = SearchChain()
    assert chain._SearchChain__search_all_sites(keyword="demo") == [
        "native-sync", "plugin-sync"
    ]

    import asyncio

    assert asyncio.run(chain._SearchChain__async_search_all_sites(keyword="demo")) == [
        "native-async", "plugin-async"
    ]

    async def collect_stream():
        return [
            event async for event in chain._SearchChain__async_search_all_sites_stream(
                keyword="demo"
            )
        ]

    events = asyncio.run(collect_stream())
    assert [event["type"] for event in events] == ["append", "done"]
    assert events[0]["items"] == ["plugin-async"]

    disabled = _plugin({"enabled": False})
    assert SearchChain._SearchChain__search_all_sites is sync_original


def test_plugin_search_bridge_defers_to_new_native_dispatch(monkeypatch):
    class SearchChain:
        def search_plugin_torrents(self, **kwargs):
            return ["native-plugin-sync"]

        async def async_search_plugin_torrents(self, **kwargs):
            return ["native-plugin-async"]

        def __search_all_sites(self, **kwargs):
            return ["native-sync"]

    app_module = ModuleType("app")
    chain_module = ModuleType("app.chain")
    search_module = ModuleType("app.chain.search")
    search_module.SearchChain = SearchChain
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.chain", chain_module)
    monkeypatch.setitem(sys.modules, "app.chain.search", search_module)
    plugin_module._SEARCH_BRIDGE.update({"owner": None, "chain": None, "originals": {}})

    original = SearchChain._SearchChain__search_all_sites
    plugin = _plugin({"enabled": True})

    assert SearchChain._SearchChain__search_all_sites is original
    assert plugin_module._SEARCH_BRIDGE == {"owner": None, "chain": None, "originals": {}}


def test_native_download_is_enqueued_into_serial_queue(tmp_path: Path):
    plugin = _plugin({"enabled": True})
    token = plugin._resource_token({
        "url": "https://example.test/movie.m3u8",
        "title": "示例电影",
        "year": "2024",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "source_key": "demo",
        "source_name": "演示源",
        "media_id": "demo:42",
        "host_media_source": "themoviedb",
        "host_media_id": "123",
    })
    result = plugin.download(token, tmp_path)
    assert result[0] == "LunaTVSource"
    assert result[1]
    tasks = plugin._queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["url"] == "https://example.test/movie.m3u8"
    assert tasks[0]["root"] == str(tmp_path)
    assert tasks[0]["source_key"] == "demo"
    assert tasks[0]["media_id"] == "demo:42"
    assert tasks[0]["host_media_source"] == "themoviedb"
    assert tasks[0]["host_media_id"] == "123"


def test_native_download_reports_duplicate_instead_of_fake_success(tmp_path: Path):
    plugin = _plugin({"enabled": True})
    token = plugin._resource_token({
        "url": "https://example.test/movie.m3u8",
        "title": "示例电影",
        "year": "2024",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "media_id": "demo:42",
    })

    first = plugin.download(token, tmp_path)
    duplicate = plugin.download(token, tmp_path)

    assert first[1]
    assert duplicate[:3] == ("LunaTVSource", None, None)
    assert "已在" in duplicate[3]
    assert len(plugin._queue.list_tasks()) == 1


def test_resource_download_event_routes_lunatv_token_to_serial_queue(tmp_path: Path):
    plugin = _plugin({"enabled": True})
    token = plugin._resource_token({
        "url": "https://example.test/event.m3u8",
        "title": "事件电影",
        "year": "2024",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "media_id": "demo:99",
        "host_media_source": "themoviedb",
        "host_media_id": "999",
    })
    event_data = SimpleNamespace(
        context=SimpleNamespace(torrent_info=SimpleNamespace(enclosure=token)),
        options={"save_path": f"local:{tmp_path}"},
        cancel=False,
        source="",
        reason="",
    )

    plugin._on_resource_download(SimpleNamespace(event_data=event_data))

    assert event_data.cancel is True
    assert "串行下载队列" in event_data.reason
    assert plugin._queue.list_tasks()[0]["root"] == str(tmp_path)


def test_native_transfer_uses_host_media_identity(monkeypatch, tmp_path: Path):
    captured = {}

    class MediaSource(str, Enum):
        TMDB = "themoviedb"

    class StorageChain:
        def get_file_item(self, **kwargs):
            return object()

    class TransferChain:
        def manual_transfer(self, **kwargs):
            captured.update(kwargs)
            return True, ""

    monkeypatch.setattr(plugin_module, "_HostMediaSource", MediaSource)
    monkeypatch.setattr(plugin_module, "_HostStorageChain", StorageChain)
    monkeypatch.setattr(plugin_module, "_HostTransferChain", TransferChain)
    plugin = _plugin({"enabled": True})
    task = SimpleNamespace(
        mode="download",
        media_type="movie",
        root=str(tmp_path),
        source_key="cms-demo",
        media_id="cms-demo:42",
        host_media_source="themoviedb",
        host_media_id="1084242",
        season=1,
    )

    assert plugin._native_transfer(task, str(tmp_path / "movie.mp4")) == "moviepilot"
    assert captured["media_source"] is MediaSource.TMDB
    assert captured["media_id"] == "1084242"


def test_task_media_identity_prefers_host_fields():
    task = SimpleNamespace(
        source_key="lunatv",
        media_id="not-used",
        host_media_source="themoviedb",
        host_media_id="98765",
    )
    plugin = _plugin({"enabled": True})

    source, media_id = plugin._task_media_identity(task)
    assert source == "themoviedb"
    assert media_id == "98765"


def test_record_native_history_uses_source_output_and_is_idempotent(monkeypatch, tmp_path: Path):
    histories: list[dict] = []
    files: list[dict] = []
    transfer_calls: list[dict] = []
    download_module = ModuleType("app.db.oper.downloadhistory")

    class FakeDownloadHistoryOper:
        def get_by_hash(self, download_hash):
            return next(
                (item for item in histories if item["download_hash"] == download_hash),
                None,
            )

        def get_files_by_hash(self, download_hash, state=None):
            return [
                item
                for item in files
                if item["download_hash"] == download_hash
                and (state is None or item["state"] == state)
            ]

        def get_file_by_fullpath(self, fullpath):
            return next(
                (item for item in reversed(files) if item["fullpath"] == fullpath),
                None,
            )

        def add(self, **kwargs):
            histories.append(kwargs)

        def add_files(self, items):
            files.extend(items)

    download_module.DownloadHistoryOper = FakeDownloadHistoryOper

    transfer_module = ModuleType("app.db.oper.transferhistory")

    class FakeTransferHistoryOper:
        def add(self, **kwargs):
            transfer_calls.append(kwargs)

    transfer_module.TransferHistoryOper = FakeTransferHistoryOper

    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_module.__path__ = []
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.transferhistory = transfer_module
    app_db_oper_module.downloadhistory = download_module

    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.transferhistory", transfer_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.downloadhistory", download_module)

    plugin = _plugin({"enabled": True})

    output = str(tmp_path / "movie.mp4")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("x")

    task = SimpleNamespace(
        task_id="tid-01",
        source_key="cms-demo",
        source_name="演示源",
        media_id="cms-demo:42",
        host_media_source="themoviedb",
        host_media_id="tt112233",
        media_type="movie",
        title="测试电影",
        year="2026",
        season=1,
        episode=1,
        mode="download",
    )
    plugin._record_native_history(task, output)
    plugin._record_native_history(task, output)

    expected_hash = hashlib.sha1(f"{task.task_id}|{output}".encode("utf-8")).hexdigest()
    assert len(histories) == 1
    assert histories[0]["media_source"] == "themoviedb"
    assert histories[0]["media_id"] == "tt112233"
    assert histories[0]["path"] == output
    assert histories[0]["torrent_site"] == "演示源"
    assert files == [{
        "download_hash": expected_hash,
        "downloader": "LunaTVSource",
        "fullpath": output,
        "savepath": str(tmp_path),
        "filepath": "movie.mp4",
        "torrentname": "测试电影",
        "state": 1,
    }]
    assert transfer_calls == []


def test_refresh_reconciles_existing_episode_without_enqueue_or_transfer(monkeypatch, tmp_path: Path):
    """An older direct-write artifact must appear in native subscription history."""
    histories: list[dict] = []
    files: list[dict] = []
    result = _result_from_item(
        CmsSource("cms-demo", "演示源", "https://cms.example/vod"),
        {
            "vod_id": "42",
            "vod_name": "疯狂动物城2",
            "vod_year": "2025",
            "type_name": "电影",
            "vod_play_url": "正片$https://example.test/zootopia-2.m3u8",
        },
    )
    episode = result.episodes[0]
    relative_dir, filename = media_path(
        str(tmp_path),
        result.title,
        result.year,
        result.media_type,
        episode.season,
        episode.episode,
        episode.url,
        "download",
    )
    output = tmp_path / relative_dir / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"completed movie")

    download_module = ModuleType("app.db.oper.downloadhistory")

    class FakeDownloadHistoryOper:
        def get_by_hash(self, download_hash):
            return next(
                (item for item in histories if item["download_hash"] == download_hash),
                None,
            )

        def get_files_by_hash(self, download_hash, state=None):
            return [
                item
                for item in files
                if item["download_hash"] == download_hash
                and (state is None or item["state"] == state)
            ]

        def get_file_by_fullpath(self, fullpath):
            return next(
                (item for item in reversed(files) if item["fullpath"] == fullpath),
                None,
            )

        def add(self, **kwargs):
            histories.append(kwargs)

        def add_files(self, items):
            files.extend(items)

    subscribe = SimpleNamespace(
        state="R",
        name="疯狂动物城2",
        year="2025",
        type="电影",
        season=0,
        media_source="themoviedb",
        media_id="1084242",
        save_path=str(tmp_path),
    )
    subscribe_module = ModuleType("app.db.oper.subscribe")

    class FakeSubscribeOper:
        def list(self, state=None):
            assert state in {None, "R"}
            return [subscribe]

    subscribe_module.SubscribeOper = FakeSubscribeOper
    download_module.DownloadHistoryOper = FakeDownloadHistoryOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_module.__path__ = []
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.subscribe = subscribe_module
    app_db_oper_module.downloadhistory = download_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.subscribe", subscribe_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.downloadhistory", download_module)

    class Client:
        def search(self, query):
            assert query == "疯狂动物城2"
            return [result]

    plugin = _plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda item: (item, {}))
    monkeypatch.setattr(plugin._ai, "normalize", lambda *_args: ("疯狂动物城2", False))
    monkeypatch.setattr(
        plugin,
        "_native_transfer",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not transfer existing file")),
    )

    first = plugin.refresh_subscriptions()
    second = plugin.refresh_subscriptions()

    assert first["queued"] == 0
    assert first["reconciled"] == 1
    assert second["queued"] == 0
    assert second["reconciled"] == 1
    assert plugin._queue is not None
    assert plugin._queue.summary()["pending"] == 0
    assert len(histories) == 1
    assert histories[0]["media_source"] == "themoviedb"
    assert histories[0]["media_id"] == "1084242"
    assert histories[0]["path"] == str(output)
    assert histories[0]["torrent_site"] == "演示源"
    assert len(files) == 1
    assert files[0]["fullpath"] == str(output)


def test_local_episode_path_requires_completed_download_or_strm_artifact(tmp_path: Path):
    plugin = _plugin({"enabled": True})

    for mode in ("download", "strm"):
        task = SimpleNamespace(
            root=str(tmp_path),
            title="示例作品",
            year="2026",
            media_type="movie",
            season=1,
            episode=1,
            url="https://example.test/movie.m3u8",
            mode=mode,
        )
        relative_dir, filename = media_path(
            task.root,
            task.title,
            task.year,
            task.media_type,
            task.season,
            task.episode,
            task.url,
            task.mode,
        )
        output = Path(task.root) / relative_dir / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        assert plugin._local_episode_path(task) is None

        output.write_text("#EXTM3U" if mode == "strm" else "completed", encoding="utf-8")
        assert plugin._local_episode_path(task) == output


def test_record_completion_writes_original_download_output(monkeypatch, tmp_path: Path):
    plugin = _plugin({"enabled": True})
    task = SimpleNamespace(
        task_id="tid-02",
        mode="download",
        source_key="lunatv",
        media_id="lunatv:1",
        media_type="movie",
        title="电影",
        year="2026",
        season=1,
        episode=1,
        root=str(tmp_path),
        completed_at=0,
    )
    captured: list[str] = []
    output = str(tmp_path / "source.mp4")

    monkeypatch.setattr(plugin, "_native_transfer", lambda _task, _output: "moviepilot")
    monkeypatch.setattr(plugin, "_record_native_history", lambda _task, path: captured.append(path))

    plugin._record_completion(task, output)

    assert captured == [output]


def test_record_native_history_skips_missing_idempotency_abi(monkeypatch, tmp_path: Path):
    writes: list[dict] = []
    download_module = ModuleType("app.db.oper.downloadhistory")

    class IncompleteDownloadHistoryOper:
        def add(self, **kwargs):
            writes.append(kwargs)

        def add_files(self, items):
            writes.extend(items)

    download_module.DownloadHistoryOper = IncompleteDownloadHistoryOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_module.__path__ = []
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.downloadhistory = download_module

    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.downloadhistory", download_module)

    plugin = _plugin({"enabled": True})
    task = SimpleNamespace(
        task_id="tid-missing-abi",
        source_key="cms-demo",
        media_id="cms-demo:42",
        media_type="movie",
        title="测试电影",
        year="2026",
        season=1,
        episode=1,
        mode="download",
    )

    plugin._record_native_history(task, str(tmp_path / "movie.mp4"))
    assert writes == []


def test_record_native_history_ignores_database_errors(monkeypatch, tmp_path: Path):
    download_module = ModuleType("app.db.oper.downloadhistory")

    class BrokenDownloadHistoryOper:
        def get_by_hash(self, _download_hash):
            raise RuntimeError("database unavailable")

        def get_files_by_hash(self, _download_hash, state=None):
            del state
            raise AssertionError("query should stop at the first database failure")

        def add(self, **_kwargs):
            raise AssertionError("must not write after a database failure")

        def add_files(self, _items):
            raise AssertionError("must not write after a database failure")

    download_module.DownloadHistoryOper = BrokenDownloadHistoryOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_module.__path__ = []
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.downloadhistory = download_module

    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.downloadhistory", download_module)

    plugin = _plugin({"enabled": True})
    task = SimpleNamespace(
        task_id="tid-db-error",
        source_key="cms-demo",
        media_id="cms-demo:42",
        media_type="movie",
        title="测试电影",
        year="2026",
        season=1,
        episode=1,
        mode="download",
    )

    plugin._record_native_history(task, str(tmp_path / "movie.mp4"))
