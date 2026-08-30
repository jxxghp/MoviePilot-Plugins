from app.plugins.lunatvsource import LunaTVSource
import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource.cms import (
    AppleCmsClient,
    CmsEpisode,
    CmsResult,
    CmsSource,
    _result_from_item,
)
from app.plugins.lunatvsource.downloader import DownloadTask
from app.plugins.lunatvsource.naming import media_path
from pathlib import Path
from collections.abc import Mapping
import hashlib
import pytest
import sys
import threading
from enum import Enum
from types import ModuleType, SimpleNamespace


class PluginData:
    def __init__(self):
        self.values = {}

    def get_data(self, _plugin_id, key):
        return self.values.get(key)

    def save(self, _plugin_id, key, value):
        self.values[key] = value


def _plugin(config=None):
    """Build the plugin without requiring a fully composed MoviePilot chain."""

    plugin = object.__new__(LunaTVSource)
    plugin.plugindata = PluginData()
    plugin._logger = plugin_module.LOGGER
    plugin._download_metrics_lock = threading.Lock()
    plugin._download_metrics = {}
    plugin._quality_cache_lock = threading.Lock()
    plugin._quality_cache = {}
    plugin._quality_probe_ms = {}
    plugin._completed_download_sizes = {}
    plugin._source_health_lock = threading.RLock()
    plugin._source_health_running = False
    plugin._source_health = {}
    plugin._source_health_stop = threading.Event()
    plugin._source_health_thread = None
    plugin._source_health_pending_keys = set()
    plugin._source_health_pending_full = False
    plugin._source_health_last_error = ""
    plugin._source_health_last_finished = 0.0
    plugin._source_health_revision = 0
    plugin._start_source_health_refresh = lambda *_args, **_kwargs: False
    plugin.init_plugin(config)
    return plugin


def _field(item, name, default=None):
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


@pytest.fixture(autouse=True)
def _disable_external_quality_probe(monkeypatch):
    monkeypatch.setattr(
        plugin_module,
        "probe_stream_height",
        lambda *_args, **_kwargs: 0,
    )


@pytest.fixture(scope="module", autouse=True)
def _disable_background_download_execution():
    """Plugin tests exercise queue wiring, never a real HLS transfer."""
    original_execute = plugin_module.DownloadQueue._execute
    plugin_module.DownloadQueue._execute = (
        lambda _queue, task: str(Path(task.root) / f"{task.task_id}.mp4")
    )
    yield
    plugin_module.DownloadQueue._execute = original_execute


def test_status_exposes_serial_queue_and_ai_fallback():
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "ai_enabled": False})
    status = plugin.api_status()["data"]
    assert status["enabled"] is True
    assert status["queue"]["pending"] == 0
    assert status["ai"]["enabled"] is True
    assert status["ai"]["available"] is False
    assert status["media_source"] == "lunatv"
    assert plugin.get_sidebar_nav() == []


def test_service_registers_subscription_refresh_and_serial_queue():
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "poll_minutes": 15, "queue_minutes": 2})
    services = plugin.get_service()
    assert {item["id"] for item in services} == {
        "LunaTVSource.Refresh",
        "LunaTVSource.SourceHealth",
        "LunaTVSource.DownloadQueue",
    }
    assert {item["func"] for item in services} == {
        plugin.refresh_subscriptions,
        plugin.refresh_source_health,
        plugin.run_queue,
    }


def test_refresh_subscriptions_does_not_use_legacy_operator_when_v3_operator_is_missing(monkeypatch):
    legacy_calls = []

    class LegacySubscribeOper:
        def list(self, state=None):
            legacy_calls.append(state)
            return []

    app_module = ModuleType("app")
    app_module.__path__ = []
    sdk_module = ModuleType("app.sdk")
    sdk_module.__path__ = []
    legacy_package = ModuleType("app.sdk._legacy")
    legacy_package.__path__ = []
    legacy_subscribe_module = ModuleType("app.sdk._legacy.subscribe")
    legacy_subscribe_module.SubscribeOper = LegacySubscribeOper
    app_module.sdk = sdk_module
    sdk_module._legacy = legacy_package
    legacy_package.subscribe = legacy_subscribe_module

    for module_name in (
        "app.db.oper.subscribe",
        "app.db.oper",
        "app.db",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.sdk", sdk_module)
    monkeypatch.setitem(sys.modules, "app.sdk._legacy", legacy_package)
    monkeypatch.setitem(sys.modules, "app.sdk._legacy.subscribe", legacy_subscribe_module)

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

    assert plugin.refresh_subscriptions() == {
        "subscriptions": 0,
        "queued": 0,
        "reconciled": 0,
    }
    assert legacy_calls == []


def test_sources_use_cached_snapshot_before_bundled_fallback(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("network unreachable")

    monkeypatch.setattr(plugin_module, "load_sources_from_url", unavailable)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    plugin.save_data(
        plugin_module.SOURCE_CACHE_KEY,
        [{"key": "cached", "name": "缓存源", "api": "https://cached.example/vod"}],
    )

    response = plugin.api_sources()

    assert response["success"] is True
    assert len(response["data"]) == 1
    assert {
        "key": "cached",
        "name": "缓存源",
        "api": "https://cached.example/vod",
        "url": "https://cached.example/vod",
        "enabled": False,
        "manual_disabled": False,
        "health_status": "unchecked",
    }.items() <= response["data"][0].items()
    assert plugin._source_config_origin == "本地缓存"


def test_sources_page_reads_bundled_snapshot_without_remote_request(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise AssertionError("opening the source page must not fetch remote config")

    monkeypatch.setattr(plugin_module, "load_sources_from_url", unavailable)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

    response = plugin.api_sources()

    assert response["success"] is True
    assert len(response["data"]) == 72
    assert {
        "url",
        "status",
        "status_label",
        "search_status",
        "search_label",
    }.issubset(response["data"][0])
    assert plugin._source_config_origin == "内置快照"
    assert plugin.api_status()["data"]["source_config"]["error"] == ""


def test_sources_page_uses_cached_snapshot_without_remote_request(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise AssertionError("opening the source page must not fetch remote config")

    monkeypatch.setattr(plugin_module, "load_sources_from_url", unavailable)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    plugin.save_data(
        plugin_module.SOURCE_CACHE_KEY,
        [{"key": "cached", "name": "缓存源", "api": "https://cached.example/vod"}],
    )

    response = plugin.api_sources()

    assert response["success"] is True
    assert len(response["data"]) == 1
    assert {
        "key": "cached",
        "name": "缓存源",
        "api": "https://cached.example/vod",
        "url": "https://cached.example/vod",
        "enabled": False,
        "manual_disabled": False,
        "health_status": "unchecked",
    }.items() <= response["data"][0].items()
    assert plugin._source_config_origin == "本地缓存"


def test_manual_download_rejects_non_http_url():
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": "/tmp/lunatv-test"})
    result = plugin.api_download({"url": "file:///tmp/movie.m3u8"})
    assert result["success"] is False
    assert "http/https" in result["message"]


def test_directory_settings_are_used_when_plugin_root_is_empty(monkeypatch):
    class Directory:
        storage = "local"
        download_path = "/media/courses"
        library_path = "/media/library/courses"
        transfer_type = "copy"
        media_type = "电视剧"
        priority = 1
        name = "课程目录"

    class DirectoryHelper:
        def get_download_dirs(self):
            return [Directory()]

    monkeypatch.setattr(plugin_module, "_HostDirectoryHelper", DirectoryHelper)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "use_moviepilot_dirs": False})
    assert plugin._effective_root(media_type="tv") == "/media/courses"
    assert plugin.api_status()["data"]["directories"]["source"] == "MoviePilot 目录设置"


def test_system_directory_info_matches_nested_root_without_using_unrelated_rule(monkeypatch):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(
        plugin,
        "_system_directory_infos",
        lambda _media_type: [
            {
                "download_path": "/media/incoming",
                "library_path": "/media/movies",
                "transfer_type": "move",
            }
        ],
    )

    assert plugin._system_directory_info("movie", "/media/incoming/lunatv")["library_path"] == "/media/movies"
    assert plugin._system_directory_info("movie", "/downloads/other") is None


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
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "tmdb_association": False})
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
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "tmdb_association": True})
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


def test_resource_tmdb_association_skips_candidate_lookup_and_reuses_cache(monkeypatch):
    class Source:
        TMDB = "themoviedb"

    class Meta:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Media:
        media_id = "456"
        tmdb_id = 456
        media_source = "themoviedb"
        title = "示例电影"
        year = "2024"
        seasons = {}

    recognize_calls = []
    candidate_calls = []

    class MediaChain:
        def recognize_media(self, **kwargs):
            recognize_calls.append(kwargs)
            return Media()

        def search_medias(self, **kwargs):
            candidate_calls.append(kwargs)
            return [Media()]

    monkeypatch.setattr(plugin_module, "_HostMediaSource", Source)
    monkeypatch.setattr(plugin_module, "_HostMetaInfo", Meta)
    monkeypatch.setattr(plugin_module, "_HostMediaChain", MediaChain)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    result = CmsResult(
        source_key="demo",
        source_name="演示",
        vod_id="42",
        title="示例电影",
        year="2024",
        media_type="movie",
        remark="",
    )

    first = plugin._associate_tmdb(result, include_candidates=False)
    second = plugin._associate_tmdb(result, include_candidates=False)

    assert first["media_id"] == "456"
    assert second["media_id"] == "456"
    assert len(recognize_calls) == 1
    assert candidate_calls == []


def test_host_meta_info_uses_v3_function_signature(monkeypatch):
    calls = []

    def meta_info(*, title):
        calls.append(title)
        return type("Meta", (), {"type": "电影"})()

    monkeypatch.setattr(plugin_module, "_HostMetaInfo", meta_info)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    meta = plugin._host_meta_info("示例作品", "2024")
    assert calls == ["示例作品 (2024)"]
    assert meta.type == "电影"


def test_discover_accepts_native_keyword_and_stops_after_first_source(monkeypatch):
    calls = []

    class Client:
        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return []

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(plugin, "_probe_resource_urls", lambda _urls: {})
    monkeypatch.setattr(plugin, "_media_info", lambda result, association: result)
    meta = type("Meta", (), {"name": "示例电影", "year": "", "type": "电影"})()
    results = plugin.search_medias(meta=meta)
    assert len(results) == 1
    assert results[0].title == "示例电影"
    assert plugin.get_media_source() == []


def test_global_media_search_respects_explicit_other_source():
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": "/media/incoming"})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    association_calls = []

    def associate(context, include_candidates=True):
        association_calls.append((context, include_candidates))
        return {"media_source": "themoviedb", "media_id": "123"}

    monkeypatch.setattr(plugin, "_associate_tmdb", associate)
    items = plugin.search_torrents(site={"id": 1}, keyword="示例剧", page=0)
    assert len(items) == 1
    assert items[0].site_name == "演示源 · 未知"
    assert items[0].to_dict()["site_name"] == "演示源 · 未知"
    assert items[0].media_source == "themoviedb"
    assert items[0].media_id == "123"
    assert items[0].title.endswith("第1季")
    assert "集" not in items[0].title
    assert items[0].description == (
        "LunaTV · 第1季 · m3u8 · 共1集 · "
        "下载器：LunaTVSource · 保存目录：/media/incoming"
    )
    assert items[0].download_path == "/media/incoming"
    assert "未知" in items[0].labels
    payload = plugin._decode_resource_token(items[0].enclosure)
    assert payload["url"].endswith("01.m3u8")
    assert len(payload["episodes"]) == 1
    assert payload["episodes"][0]["episode"] == 1
    assert payload["source_key"] == "demo"
    assert payload["source_name"] == "演示源"
    assert payload["host_media_source"] == "themoviedb"
    assert payload["host_media_id"] == "123"
    assert [(item.title, item.year, item.media_type, include_candidates)
            for item, include_candidates in association_calls] == [
        ("示例剧", "2024", "tv", False),
    ]


def test_bridge_search_kwargs_forwards_media_identity():
    mediainfo = SimpleNamespace(
        type="电视剧",
        media_source="anilist",
        media_id="anilist:anime_123",
        title="進擊的巨人",
        year="2013",
    )
    kwargs = plugin_module._bridge_search_kwargs({
        "keyword": "进击的巨人",
        "mtype": "电影",
        "page": 3,
        "mediainfo": mediainfo,
    })
    assert kwargs == {
        "site": {},
        "keyword": "进击的巨人",
        "mtype": "电视剧",
        "page": 3,
        "media_source": "anilist",
        "media_id": "anilist:anime_123",
        "media_title": "進擊的巨人",
        "media_year": "2013",
    }


def test_resource_torrents_targets_native_identity_for_tv_and_movie(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    source = CmsSource("demo", "演示源", "https://cms.example/vod", "https://cms.example")
    tv_result = _result_from_item(
        source,
        {
            "vod_id": "tv",
            "vod_name": "进击的巨人",
            "vod_year": "2013",
            "type_name": "电视剧",
            "vod_play_url": (
                "01$https://example.test/s01e01.m3u8#"
                "02$https://example.test/s01e02.m3u8"
            ),
        },
    )
    movie_result = _result_from_item(
        source,
        {
            "vod_id": "movie",
            "vod_name": "进击的巨人",
            "vod_year": "2013",
            "type_name": "电影",
            "vod_play_url": "正片$https://example.test/movie.m3u8",
        },
    )

    class Client:
        def search(self, _query, **_kwargs):
            return [tv_result, movie_result]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(
        plugin,
        "_associate_tmdb",
        lambda *_args, **_kwargs: {
            "media_source": "themoviedb",
            "media_id": "tt123456",
        },
    )

    tv_items = plugin.search_torrents(
        site={"id": 1},
        keyword="进击的巨人",
        page=0,
        mtype="电视剧",
        media_source="anilist",
        media_id="anilist:anime_123",
        media_title="進擊的巨人",
        media_year="2013",
    )
    assert len(tv_items) == 1
    tv_payload = plugin._decode_resource_token(tv_items[0].enclosure)
    assert tv_items[0].title == "進擊的巨人 (2013) · 第1季"
    assert tv_items[0].media_source == "anilist"
    assert tv_items[0].media_id == "anilist:anime_123"
    assert tv_payload["title"] == "進擊的巨人"
    assert tv_payload["media_id"] == "demo:tv"
    assert tv_payload["source_key"] == "demo"
    assert tv_payload["source_name"] == "演示源"
    assert tv_payload["host_media_source"] == "anilist"
    assert tv_payload["host_media_id"] == "anilist:anime_123"
    assert [episode["url"] for episode in tv_payload["episodes"]] == [
        "https://example.test/s01e01.m3u8",
        "https://example.test/s01e02.m3u8",
    ]

    movie_items = plugin.search_torrents(
        site={"id": 1},
        keyword="进击的巨人",
        page=0,
        mtype="movie",
        media_source="anilist",
        media_id="anilist:anime_123",
        media_title="進擊的巨人",
        media_year="2013",
    )
    assert len(movie_items) == 1
    assert movie_items[0].title == "進擊的巨人 (2013) · 未知"
    assert movie_items[0].media_source == "anilist"
    assert movie_items[0].media_id == "anilist:anime_123"
    movie_payload = plugin._decode_resource_token(movie_items[0].enclosure)
    assert movie_payload["title"] == "進擊的巨人"
    assert movie_payload["year"] == "2013"
    assert movie_payload["media_id"] == "demo:movie"
    assert movie_payload["source_key"] == "demo"
    assert movie_payload["source_name"] == "演示源"
    assert movie_payload["host_media_source"] == "anilist"
    assert movie_payload["host_media_id"] == "anilist:anime_123"


def test_resource_torrents_groups_by_source_and_season(monkeypatch):
    calls = []
    ai_calls = []
    association_calls = []

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
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())

    class Ai:
        def normalize(self, title, year="", media_type=""):
            ai_calls.append((title, year, media_type))
            return "标准示例剧", "ai"

    def associate(context, include_candidates=True):
        association_calls.append((context, include_candidates))
        return {
            "status": "matched",
            "media_source": "themoviedb",
            "media_id": "123",
            "season_counts": {1: 2},
        }

    plugin._ai = Ai()
    monkeypatch.setattr(plugin, "_associate_tmdb", associate)
    items = plugin.search_torrents(site={"id": 1}, keyword="示例剧", page=0, mtype="tv")
    assert len(items) == 2
    payloads = [plugin._decode_resource_token(item.enclosure) for item in items]
    assert [item.site_name for item in items] == ["源A · 未知", "源B · 未知"]
    assert [len(payload["episodes"]) for payload in payloads] == [2, 1]
    assert [
        [episode["url"] for episode in payload["episodes"]]
        for payload in payloads
    ] == [["https://example.test/01.m3u8", "https://example.test/02.m3u8"],
          ["https://example.test/01.m3u8"]]
    assert all(item.title.endswith("· 第1季") and "集" not in item.title for item in items)
    assert calls == [{
        "limit": 50,
        "source_limit": 3,
        "stop_after_first_source": False,
        "require_playable": True,
        "expand_tv_episode_rows": True,
        "max_workers": 8,
        "media_type_filter": "tv",
    }]
    assert ai_calls == [("示例剧", "", "")]
    assert [(item.title, item.year, item.media_type, include_candidates)
            for item, include_candidates in association_calls] == [
        ("标准示例剧", "", "tv", False),
    ]
    assert {(payload["host_media_source"], payload["host_media_id"])
            for payload in payloads} == {("themoviedb", "123")}


def test_resource_torrents_collapses_episode_named_cms_rows_into_one_season(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    source = CmsSource("peppa", "极速资源", "https://cms.example/vod", "https://cms.example")
    rows = [
        _result_from_item(source, {
            "vod_id": "1",
            "vod_name": "小猪佩奇 第一季 第1集",
            "type_name": "欧美动漫",
            "vod_play_url": "第1集$https://example.test/peppa-01.m3u8",
        }),
        _result_from_item(source, {
            "vod_id": "2",
            "vod_name": "小猪佩奇 第一季 第2集",
            "type_name": "欧美动漫",
            "vod_play_url": "第2集$https://example.test/peppa-02.m3u8",
        }),
    ]

    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: type("Client", (), {
        "search": lambda self, *_args, **_kwargs: rows,
    })())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})

    items = plugin.search_torrents(site={"id": 1}, keyword="小猪佩奇", page=0, mtype="tv")
    assert len(items) == 1
    assert items[0].title == "小猪佩奇 · 第1季"
    payload = plugin._decode_resource_token(items[0].enclosure)
    assert [episode["episode"] for episode in payload["episodes"]] == [1, 2]


def test_resource_torrents_label_and_prefer_verified_resolution(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    low = _result_from_item(
        CmsSource("low", "标清源", "https://low.example/vod"),
        {
            "vod_id": "1",
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_url": "正片$https://video.example/480.m3u8",
        },
    )
    high = _result_from_item(
        CmsSource("high", "高清源", "https://high.example/vod"),
        {
            "vod_id": "2",
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_url": "正片$https://video.example/1080.m3u8",
        },
    )

    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(
        plugin_module,
        "probe_stream_height",
        lambda url, **_kwargs: 1080 if "1080" in url else 480,
    )
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    cached_at = plugin_module.time.monotonic()
    plugin._quality_cache = {
        "https://video.example/480.m3u8": (cached_at, 480),
        "https://video.example/1080.m3u8": (cached_at, 1080),
    }
    plugin._quality_probe_ms = {
        "https://video.example/480.m3u8": 320,
        "https://video.example/1080.m3u8": 128,
    }
    monkeypatch.setattr(plugin, "_client", lambda: type("Client", (), {
        "search": lambda self, *_args, **_kwargs: [low, high],
    })())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})

    items = plugin.search_torrents(site={"id": 1}, keyword="示例电影", page=0, mtype="movie")

    assert [item.site_name for item in items] == ["高清源 · 128ms", "标清源 · 320ms"]
    assert [item.pri_order for item in items] == [108, 48]
    assert items[0].title.endswith("· 1080P")
    assert items[0].description == "LunaTV · 1080P · m3u8"
    assert "1080P" not in items[0].labels
    assert "128ms" in items[0].labels
    assert items[0].uploadvolumefactor == 1.0
    assert items[0].downloadvolumefactor == 1.0
    assert plugin._decode_resource_token(items[0].enclosure)["resolution"] == "1080P"


def test_global_media_search_collapses_episode_rows_into_season_cards(monkeypatch):
    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    rows = [
        _result_from_item(
            source,
            {
                "vod_id": "s1e1",
                "vod_name": "小猪佩奇 第一季 第1集",
                "vod_year": "2004",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://video.example/s1e1.m3u8",
            },
        ),
        _result_from_item(
            source,
            {
                "vod_id": "s1e2",
                "vod_name": "小猪佩奇 第一季 第2集",
                "vod_year": "2004",
                "type_name": "电视剧",
                "vod_play_url": "第2集$https://video.example/s1e2.m3u8",
            },
        ),
        _result_from_item(
            source,
            {
                "vod_id": "s2e1",
                "vod_name": "小猪佩奇 第二季 第1集",
                "vod_year": "2004",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://video.example/s2e1.m3u8",
            },
        ),
    ]

    class Client:
        def search(self, *_args, **_kwargs):
            return rows

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))

    meta = type("Meta", (), {"name": "小猪佩奇", "year": "", "type": "电视剧"})()
    cards = plugin.search_medias(meta=meta)
    discovered = plugin.api_discover(keyword="小猪佩奇")["data"]

    for projected in (cards, discovered):
        assert len(projected) == 2
    assert [_field(item, "title") for item in projected] == ["小猪佩奇", "小猪佩奇"]
    assert [_field(item, "seasons") for item in projected] == [{1: []}, {2: []}]
    assert all(_field(item, "episodes", []) == [] for item in projected)


def test_global_media_search_keeps_each_ambiguous_range_season(monkeypatch):
    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    flat = _result_from_item(
        source,
        {
            "vod_id": "bundle",
            "vod_name": "示例剧 1-3季",
            "vod_year": "2024",
            "type_name": "电视剧",
            "vod_play_url": (
                "01$https://video.example/01.m3u8#"
                "02$https://video.example/02.m3u8#"
                "03$https://video.example/03.m3u8"
            ),
        },
    )
    assert flat.season_ambiguous is True

    class Client:
        def search(self, *_args, **_kwargs):
            return [flat]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))

    meta = type("Meta", (), {"name": "示例剧", "year": "", "type": "电视剧"})()
    cards = plugin.search_medias(meta=meta)

    assert [_field(item, "seasons") for item in cards] == [{1: []}, {2: []}, {3: []}]
    assert all(_field(item, "episodes", []) == [] for item in cards)


def test_media_info_keeps_precise_episode_details_outside_search_projection(monkeypatch):
    monkeypatch.setattr(plugin_module, "_schemas", None)
    result = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="42",
        title="示例剧",
        year="2024",
        media_type="tv",
        remark="",
        episodes=(
            CmsEpisode(1, 1, "第1集", "https://video.example/s1e1.m3u8"),
            CmsEpisode(2, 3, "第3集", "https://video.example/s2e3.m3u8"),
        ),
    )

    projected = _plugin()._media_info(result)

    assert [(item["season"], item["episode"]) for item in projected["episodes"]] == [
        (1, 1),
        (2, 3),
    ]


def test_resource_torrents_skip_unknown_tv_season_instead_of_episode_fallback(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    unknown = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="unknown",
        title="未知季剧集",
        year="2024",
        media_type="tv",
        remark="",
        episodes=(
            CmsEpisode(
                season=1,
                episode=1,
                label="第1集",
                url="https://video.example/unknown-s01e01.m3u8",
                season_known=False,
            ),
        ),
        season_range=(0, 0),
    )

    class Client:
        def search(self, *_args, **_kwargs):
            return [unknown]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})

    assert plugin._resource_torrents("未知季剧集") == []


def test_resource_torrents_keep_movie_single_and_season_free(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    movie = _result_from_item(
        CmsSource("demo", "演示源", "https://cms.example/vod"),
        {
            "vod_id": "movie",
            "vod_name": "示例电影",
            "vod_year": "2024",
            "type_name": "电影",
            "vod_play_url": "正片$https://video.example/movie.m3u8",
        },
    )

    class Client:
        def search(self, *_args, **_kwargs):
            return [movie]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})

    items = plugin._resource_torrents("示例电影")

    assert len(items) == 1
    assert items[0].category == "电影"
    assert "季" not in items[0].title
    assert all("季" not in label for label in items[0].labels)
    assert plugin._decode_resource_token(items[0].enclosure)["url"].endswith("movie.m3u8")


def test_resource_torrents_filters_by_requested_media_type(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    tv = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="tv",
        title="示例剧",
        year="2024",
        media_type="tv",
        remark="",
        episodes=(CmsEpisode(1, 1, "第1集", "https://video.example/tv.m3u8"),),
    )
    movie = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="movie",
        title="示例电影",
        year="2024",
        media_type="movie",
        remark="",
        episodes=(CmsEpisode(1, 1, "正片", "https://video.example/movie.m3u8"),),
    )

    class Client:
        def search(self, *_args, **_kwargs):
            return [tv, movie]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        plugin, "_probe_resource_urls", lambda urls: {url: 720 for url in urls}
    )

    tv_items = plugin._resource_torrents("类型过滤", mtype="tv")
    movie_items = plugin._resource_torrents("类型过滤", mtype="movie")
    unknown_items = plugin._resource_torrents("类型过滤", mtype="unknown")

    assert [
        plugin._decode_resource_token(item.enclosure)["media_type"] for item in tv_items
    ] == ["tv"]
    assert [
        plugin._decode_resource_token(item.enclosure)["media_type"] for item in movie_items
    ] == ["movie"]
    assert sorted(
        plugin._decode_resource_token(item.enclosure)["media_type"]
        for item in unknown_items
    ) == ["movie", "tv"]


def test_resource_torrents_keep_complete_season_quality_variants_as_more_sources(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    low = _result_from_item(
        source,
        {
            "vod_id": "low",
            "vod_name": "示例剧 第一季",
            "type_name": "电视剧",
            "vod_play_url": (
                "第1集$https://video.example/480-e1.m3u8#"
                "第2集$https://video.example/480-e2.m3u8"
            ),
        },
    )
    high = _result_from_item(
        source,
        {
            "vod_id": "high",
            "vod_name": "示例剧 第一季",
            "type_name": "电视剧",
            "vod_play_url": (
                "第1集$https://video.example/1080-e1.m3u8#"
                "第2集$https://video.example/1080-e2.m3u8"
            ),
        },
    )

    class Client:
        def search(self, *_args, **_kwargs):
            return [low, high]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {url: 1080 if "/1080-" in url else 480 for url in urls},
    )

    items = plugin._resource_torrents("示例剧")
    payloads = [plugin._decode_resource_token(item.enclosure) for item in items]

    assert [item.pri_order for item in items] == [108, 48]
    assert [payload["resolution"] for payload in payloads] == ["1080P", "480P"]
    assert [len(payload["episodes"]) for payload in payloads] == [2, 2]
    assert all("1080-" in item["url"] for item in payloads[0]["episodes"])
    assert all("480-" in item["url"] for item in payloads[1]["episodes"])
    assert all(
        len({episode["url"] for episode in payload["episodes"]}) == 2
        for payload in payloads
    )


def test_resource_torrents_tv_sources_share_matched_identity_card_and_rank_resolution(
    monkeypatch,
):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    results = [
        CmsResult(
            source_key="shared",
            source_name="同源",
            vod_id="high-s04",
            title="侠探杰克",
            year="0",
            media_type="tv",
            remark="",
            episodes=(
                CmsEpisode(4, 1, "第1集", "https://video.example/1080-s04e01.m3u8"),
            ),
            detail="https://high.example/detail/high-s04",
        ),
        CmsResult(
            source_key="shared",
            source_name="同源",
            vod_id="middle-s04",
            title="侠探杰克",
            year="2026",
            media_type="tv",
            remark="",
            episodes=(
                CmsEpisode(4, 1, "第1集", "https://video.example/960-s04e01.m3u8"),
            ),
            detail="https://middle.example/detail/middle-s04",
        ),
        CmsResult(
            source_key="low",
            source_name="标清源",
            vod_id="low-s04",
            title="侠探杰克",
            year="0",
            media_type="tv",
            remark="",
            episodes=(
                CmsEpisode(4, 1, "第1集", "https://video.example/720-s04e01.m3u8"),
            ),
            detail="https://low.example/detail/low-s04",
        ),
    ]

    class Client:
        def search(self, *_args, **_kwargs):
            return results

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(
        plugin,
        "_associate_tmdb",
        lambda *_args, **_kwargs: {
            "status": "matched",
            "media_source": "themoviedb",
            "media_id": "343611",
            "title": "侠探杰克",
            "year": "2022",
        },
    )
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {
            url: 1080 if "/1080-" in url else 960 if "/960-" in url else 720
            for url in urls
        },
    )

    items = plugin._resource_torrents("侠探杰克", mtype="tv")

    assert [item.pri_order for item in items] == [108, 96, 72]
    assert [
        item.title.rsplit(" · ", 1)[0]
        for item in items
    ] == ["侠探杰克 (2022)"] * 3
    assert [
        plugin._decode_resource_token(item.enclosure)["resolution"]
        for item in items
    ] == ["1080P", "960P", "720P"]
    assert [item.media_id for item in items] == ["343611"] * 3


def test_resource_torrents_choose_highest_url_for_conflicting_episode(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    rows = [
        _result_from_item(
            source,
            {
                "vod_id": "e1-low",
                "vod_name": "示例剧 第一季 第1集",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://video.example/480-e1.m3u8",
            },
        ),
        _result_from_item(
            source,
            {
                "vod_id": "e1-high",
                "vod_name": "示例剧 第一季 第1集",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://video.example/1080-e1.m3u8",
            },
        ),
        _result_from_item(
            source,
            {
                "vod_id": "e2",
                "vod_name": "示例剧 第一季 第2集",
                "type_name": "电视剧",
                "vod_play_url": "第2集$https://video.example/480-e2.m3u8",
            },
        ),
    ]

    class Client:
        def search(self, *_args, **_kwargs):
            return rows

    probed = []

    def probe(urls):
        probed.extend(urls)
        return {url: 1080 if "/1080-" in url else 480 for url in urls}

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(plugin, "_probe_resource_urls", probe)
    plugin._quality_probe_ms["https://video.example/1080-e1.m3u8"] = 86

    item = plugin._resource_torrents("示例剧")[0]
    payload = plugin._decode_resource_token(item.enclosure)

    assert item.site_name == "演示源 · 1080P · 86ms"
    assert item.title == "示例剧 · 第1季"
    assert payload["resolution_height"] == 1080
    assert item.pri_order == 108
    assert payload["resolution"] not in item.description
    assert payload["resolution"] in item.labels
    assert "86ms" in item.labels
    assert item.uploadvolumefactor == 1.0
    assert item.downloadvolumefactor == 1.0
    assert [episode["url"] for episode in payload["episodes"]] == [
        "https://video.example/1080-e1.m3u8",
        "https://video.example/480-e2.m3u8",
    ]
    assert "https://video.example/480-e1.m3u8" not in [
        episode["url"] for episode in payload["episodes"]
    ]
    assert [
        (episode["resolution"], episode["resolution_height"])
        for episode in payload["episodes"]
    ] == [("1080P", 1080), ("未知", 0)]
    assert payload["resolution_scope"] == "sample"
    assert payload["resolution_probed_episode_count"] == 1
    assert payload["resolution_probed_episodes"] == [1]
    assert "https://video.example/480-e2.m3u8" not in probed
    assert "全2集实测" not in item.description
    assert "已测" not in item.description


def test_resource_torrents_marks_sample_unknown_when_probe_fails(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    result = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="s1",
        title="示例剧",
        year="2024",
        media_type="tv",
        remark="",
        episodes=(
            CmsEpisode(1, 1, "第1集", "https://video.example/unprobed-e1.m3u8"),
            CmsEpisode(1, 2, "第2集", "https://video.example/1080-e2.m3u8"),
        ),
    )

    class Client:
        def search(self, *_args, **_kwargs):
            return [result]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {url: 1080 for url in urls if "1080" in url},
    )

    item = plugin._resource_torrents("示例剧")[0]
    payload = plugin._decode_resource_token(item.enclosure)

    assert payload["resolution"] == "未知"
    assert payload["resolution_height"] == 0
    assert item.pri_order == 0
    assert "未知" in item.site_name
    assert "全2集实测" not in item.description
    assert "已测" not in item.description
    assert payload["resolution_scope"] == "sample"
    assert payload["resolution_probed_episode_count"] == 0
    assert payload["resolution_probed_episodes"] == []
    assert [
        (episode["resolution"], episode["resolution_height"])
        for episode in payload["episodes"]
    ] == [("未知", 0), ("未知", 0)]


def test_resource_torrents_probes_one_episode_in_large_seasons(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Client:
        def __init__(self, result):
            self._result = result

        def search(self, *_args, **_kwargs):
            return [self._result]

    for count in (52, 208):
        result = CmsResult(
            source_key=f"sample-{count}",
            source_name="抽样源",
            vod_id=f"sample-{count}",
            title=f"抽样剧{count}",
            year="2024",
            media_type="tv",
            remark="",
            episodes=tuple(
                CmsEpisode(
                    1,
                    episode,
                    f"第{episode}集",
                    f"https://video.example/sample-{count}-e{episode}.m3u8",
                )
                for episode in range(1, count + 1)
            ),
        )
        probe_calls = []

        def probe(urls):
            probe_calls.append(list(urls))
            return {url: 1080 for url in urls}

        plugin = _plugin()
        plugin.init_plugin({"enabled": True})
        monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
        monkeypatch.setattr(plugin, "_client", lambda: Client(result))
        monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(plugin, "_probe_resource_urls", probe)

        item = plugin._resource_torrents(f"抽样剧{count}")[0]
        payload = plugin._decode_resource_token(item.enclosure)
        expected_episodes = [1]
        expected_urls = [
            f"https://video.example/sample-{count}-e{episode}.m3u8"
            for episode in expected_episodes
        ]

        assert [urls for urls in probe_calls if urls] == [expected_urls]
        assert len(expected_urls) == 1
        assert item.pri_order == 108
        assert f"全{count}集实测" not in item.description
        assert "已测" not in item.description
        assert payload["resolution_scope"] == "sample"
        assert payload["resolution_probed_episode_count"] == 1
        assert payload["resolution_probed_episodes"] == [1]
        assert [
            (payload["episodes"][episode - 1]["resolution"],
             payload["episodes"][episode - 1]["resolution_height"])
            for episode in expected_episodes
        ] == [("1080P", 1080)]


def test_resource_torrents_probes_all_conflicts_and_large_seasons(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    low_url = "https://video.example/conflict-low-e1.m3u8"
    high_url = "https://video.example/conflict-high-e1.m3u8"
    rows = [
        CmsResult(
            source_key="demo",
            source_name="演示源",
            vod_id="e1-low",
            title="冲突剧",
            year="2024",
            media_type="tv",
            remark="",
            episodes=(CmsEpisode(1, 1, "第1集", low_url),),
        ),
        CmsResult(
            source_key="demo",
            source_name="演示源",
            vod_id="e1-high",
            title="冲突剧",
            year="2024",
            media_type="tv",
            remark="",
            episodes=(CmsEpisode(1, 1, "第1集", high_url),),
        ),
    ] + [
        CmsResult(
            source_key="demo",
            source_name="演示源",
            vod_id=f"e{episode}",
            title="冲突剧",
            year="2024",
            media_type="tv",
            remark="",
            episodes=(
                CmsEpisode(
                    1,
                    episode,
                    f"第{episode}集",
                    f"https://video.example/conflict-e{episode}.m3u8",
                ),
            ),
        )
        for episode in range(2, 53)
    ]

    class Client:
        def search(self, *_args, **_kwargs):
            return rows

    probe_calls = []

    def probe(urls):
        probe_calls.append(list(urls))
        return {
            url: (
                1080
                if url == high_url
                else 480
                if url == low_url
                else 0
                if url.endswith("conflict-e27.m3u8")
                else 720
            )
            for url in urls
        }

    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(plugin, "_probe_resource_urls", probe)

    item = plugin._resource_torrents("冲突剧")[0]
    payload = plugin._decode_resource_token(item.enclosure)
    probed_urls = [url for urls in probe_calls for url in urls]

    assert probed_urls.count(low_url) == 1
    assert probed_urls.count(high_url) == 1
    assert payload["episodes"][0]["url"] == high_url
    assert payload["resolution"] == "1080P"
    assert payload["resolution_height"] == 1080
    assert item.pri_order == 108
    assert "1080P" in item.site_name
    assert "全52集实测" not in item.description
    assert "已测" not in item.description
    assert payload["resolution_scope"] == "sample"
    assert payload["resolution_probed_episode_count"] == 1
    assert payload["resolution_probed_episodes"] == [1]
    assert (
        payload["episodes"][1]["resolution"],
        payload["episodes"][1]["resolution_height"],
    ) == ("未知", 0)
    assert (
        payload["episodes"][26]["resolution"],
        payload["episodes"][26]["resolution_height"],
    ) == ("未知", 0)


def test_resource_torrents_sort_actual_heights_and_keep_ties_stable(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    qualities = [
        ("1080-first", 1080),
        ("1088", 1088),
        ("2160", 2160),
        ("1440", 1440),
        ("1200", 1200),
        ("1080-second", 1080),
        ("720", 720),
        ("480", 480),
        ("unknown", 0),
    ]
    results = [
        _result_from_item(
            source,
            {
                "vod_id": name,
                "vod_name": f"质量 {name}",
                "type_name": "电影",
                "vod_play_url": f"正片$https://video.example/{name}.m3u8",
            },
        )
        for name, _ in qualities
    ]
    heights = {
        f"https://video.example/{name}.m3u8": height for name, height in qualities
    }

    class Client:
        def search(self, *_args, **_kwargs):
            return results

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(plugin, "_probe_resource_urls", lambda urls: {url: heights[url] for url in urls})

    items = plugin._resource_torrents("质量")

    assert [item.pri_order for item in items] == [216, 144, 120, 108, 108, 108, 72, 48, 0]
    host_sorted = sorted(
        items,
        key=lambda item: str(item.pri_order or 0).rjust(3, "0"),
        reverse=True,
    )
    assert [
        plugin._decode_resource_token(item.enclosure)["url"] for item in host_sorted
    ] == [
        plugin._decode_resource_token(item.enclosure)["url"] for item in items
    ]
    assert [plugin._decode_resource_token(item.enclosure)["url"] for item in items] == [
        "https://video.example/2160.m3u8",
        "https://video.example/1440.m3u8",
        "https://video.example/1200.m3u8",
        "https://video.example/1088.m3u8",
        "https://video.example/1080-first.m3u8",
        "https://video.example/1080-second.m3u8",
        "https://video.example/720.m3u8",
        "https://video.example/480.m3u8",
        "https://video.example/unknown.m3u8",
    ]
    for item in items:
        payload = plugin._decode_resource_token(item.enclosure)
        quality = payload["resolution"]
        assert item.title.endswith(f"· {quality}")
        assert quality in item.description
        assert quality not in item.labels
        assert item.pri_order == plugin_module._resource_sort_priority(
            payload["resolution_height"]
        )


def test_subscription_candidates_prefer_verified_resolution(monkeypatch):
    low = _result_from_item(
        CmsSource("low", "标清源", "https://low.example/vod"),
        {
            "vod_id": "1",
            "vod_name": "示例剧",
            "type_name": "电视剧",
            "vod_play_url": "01$https://video.example/480.m3u8",
        },
    )
    high = _result_from_item(
        CmsSource("high", "高清源", "https://high.example/vod"),
        {
            "vod_id": "2",
            "vod_name": "示例剧",
            "type_name": "电视剧",
            "vod_play_url": "01$https://video.example/1080.m3u8",
        },
    )
    monkeypatch.setattr(
        plugin_module,
        "probe_stream_height",
        lambda url, **_kwargs: 1080 if "1080" in url else 480,
    )
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

    ranked = plugin._rank_subscription_results([(low, {}), (high, {})], season=1)

    assert [result.source_name for result, _ in ranked] == ["高清源", "标清源"]


def test_resource_search_does_not_hold_cache_lock_during_network_request(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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


def _install_download_endpoint_module(monkeypatch, configured_system_config):
    app_module = ModuleType("app")
    app_module.__path__ = []
    api_module = ModuleType("app.api")
    api_module.__path__ = []
    endpoints_module = ModuleType("app.api.endpoints")
    endpoints_module.__path__ = []
    download_module = ModuleType("app.api.endpoints.download")

    def get_configured_system_config():
        return configured_system_config

    download_module.get_configured_system_config = get_configured_system_config
    app_module.api = api_module
    api_module.endpoints = endpoints_module
    endpoints_module.download = download_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.api", api_module)
    monkeypatch.setitem(sys.modules, "app.api.endpoints", endpoints_module)
    monkeypatch.setitem(sys.modules, "app.api.endpoints.download", download_module)
    return download_module, get_configured_system_config


def _install_download_chain_module(monkeypatch, download_chain):
    app_module = ModuleType("app")
    app_module.__path__ = []
    chain_module = ModuleType("app.chain")
    chain_module.__path__ = []
    download_module = ModuleType("app.chain.download")
    download_module.DownloadChain = download_chain
    app_module.chain = chain_module
    chain_module.download = download_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.chain", chain_module)
    monkeypatch.setitem(sys.modules, "app.chain.download", download_module)
    return download_module


def test_download_clients_bridge_augments_only_downloaders_and_restores(monkeypatch):
    class Config:
        marker = object()

        def __init__(self):
            self.values = {
                "Downloaders": [
                    {"name": "qBittorrent", "type": "qbittorrent", "enabled": True},
                    {"name": "LunaTVSource", "type": "legacy", "enabled": False},
                ],
                "Other": "unchanged",
            }

        def get(self, key=None):
            return self.values.get(key)

    plugin_module._DOWNLOAD_CLIENTS_BRIDGE.update(
        {"owner": None, "module": None, "original": None, "wrapper": None}
    )
    config = Config()
    download_module, original = _install_download_endpoint_module(monkeypatch, config)
    plugin = _plugin({"enabled": True})
    wrapper = download_module.get_configured_system_config
    proxied = wrapper()
    clients = proxied.get("Downloaders")
    assert [client["name"] for client in clients].count("LunaTVSource") == 1
    luna_client = next(client for client in clients if client["name"] == "LunaTVSource")
    assert luna_client == {"name": "LunaTVSource", "type": "plugin", "enabled": True}
    assert [client["name"] for client in clients if client.get("enabled")] == [
        "qBittorrent",
        "LunaTVSource",
    ]
    assert proxied.get("Other") == "unchanged"
    assert proxied.get("Missing", "fallback") == "fallback"
    assert proxied.marker is config.marker

    config.values["Downloaders"] = "malformed"
    assert proxied.get("Downloaders") == [
        {"name": "LunaTVSource", "type": "plugin", "enabled": True}
    ]

    replacement = _plugin({"enabled": True})
    assert download_module.get_configured_system_config is wrapper
    plugin.stop_service()
    assert download_module.get_configured_system_config is wrapper

    plugin_module._DOWNLOAD_CLIENTS_BRIDGE.update(
        {"owner": None, "module": None, "original": None, "wrapper": None}
    )
    reloaded = _plugin({"enabled": True})
    reloaded_wrapper = download_module.get_configured_system_config
    assert reloaded_wrapper is not wrapper
    assert reloaded_wrapper._lunatv_download_clients_original is original
    replacement.stop_service()
    assert download_module.get_configured_system_config is reloaded_wrapper
    reloaded.init_plugin({"enabled": False})
    assert download_module.get_configured_system_config is original


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
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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

    disabled = _plugin()
    disabled.init_plugin({"enabled": False})
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
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

    assert SearchChain._SearchChain__search_all_sites is original
    assert plugin_module._SEARCH_BRIDGE["owner"] is plugin
    assert plugin_module._SEARCH_BRIDGE["chain"] is None
    assert plugin_module._SEARCH_BRIDGE["originals"] == {}
    assert plugin_module._SEARCH_BRIDGE["mode"] is None


def test_native_download_is_enqueued_into_serial_queue(tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    token = plugin._resource_token({
        "url": "https://example.test/movie.m3u8",
        "title": "示例电影",
        "year": "2024",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
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


@pytest.mark.parametrize("host_downloader", ["qBittorrent", "Transmission"])
def test_native_download_lunatv_token_overrides_host_selected_downloader(
    tmp_path: Path, host_downloader: str
):
    plugin = _plugin({"enabled": True})
    token = plugin._resource_token(
        {
            "url": "https://example.test/movie.m3u8",
            "title": "示例电影",
            "media_type": "movie",
            "season": 1,
            "episode": 1,
            "media_id": "demo:42",
        }
    )

    result = plugin.download(token, tmp_path, downloader=host_downloader)

    assert result is not None
    assert result[0] == "LunaTVSource"
    assert result[1]
    assert len(plugin._queue.list_tasks()) == 1
    assert plugin.start_torrents(["unknown"], downloader=host_downloader) is None
    assert plugin.stop_torrents(["unknown"], downloader=host_downloader) is None
    assert plugin.remove_torrents(["unknown"], downloader=host_downloader) is None


def test_native_download_prefers_configured_download_root(tmp_path: Path):
    configured_root = tmp_path / "未整理"
    moviepilot_root = tmp_path / "moviepilot-selected"
    plugin = _plugin({"enabled": True, "download_root": str(configured_root)})
    token = plugin._resource_token({
        "url": "https://example.test/movie.m3u8",
        "title": "示例电影",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "media_id": "demo:42",
    })

    result = plugin.download(token, moviepilot_root)

    assert result[1]
    assert plugin._queue.list_tasks()[0]["root"] == str(configured_root)


def test_native_season_download_expands_to_serial_episode_tasks(tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    token = plugin._resource_token({
        "url": "https://example.test/s01e01.m3u8",
        "title": "小猪佩奇",
        "year": "2004",
        "media_type": "tv",
        "season": 1,
        "episode": 1,
        "media_id": "demo:42",
        "source_key": "demo",
        "source_name": "演示源",
        "host_media_source": "themoviedb",
        "host_media_id": "123",
        "episodes": [
            {
                "url": "https://example.test/s01e01.m3u8",
                "title": "小猪佩奇",
                "year": "2004",
                "media_type": "tv",
                "season": 1,
                "episode": 1,
                "source_key": "demo",
                "source_name": "演示源",
                "media_id": "demo:42",
                "host_media_source": "themoviedb",
                "host_media_id": "123",
            },
            {
                "url": "https://example.test/s01e02.m3u8",
                "title": "小猪佩奇",
                "year": "2004",
                "media_type": "tv",
                "season": 1,
                "episode": 2,
                "source_key": "demo",
                "source_name": "演示源",
                "media_id": "demo:42",
                "host_media_source": "themoviedb",
                "host_media_id": "123",
            },
        ],
    })

    result = plugin.download(token, tmp_path)
    assert result[0] == "LunaTVSource"
    assert result[1]
    assert "已排队 2 集" in result[3]
    tasks = sorted(plugin._queue.list_tasks(), key=lambda task: (task["season"], task["episode"]))
    assert [(task["season"], task["episode"], task["url"]) for task in tasks] == [
        (1, 1, "https://example.test/s01e01.m3u8"),
        (1, 2, "https://example.test/s01e02.m3u8"),
    ]


def test_native_download_reports_duplicate_instead_of_fake_success(tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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


def test_native_download_requeues_failed_task_in_place(monkeypatch, tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    token = plugin._resource_token({
        "url": "https://example.test/retry-movie.m3u8",
        "title": "重试电影",
        "year": "2026",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "media_id": "demo:retry-movie",
    })

    first = plugin.download(token, tmp_path)
    with plugin._queue._lock:
        tasks = plugin._queue._read()
        tasks[0].state = "failed"
        tasks[0].progress = 0.5
        tasks[0].error = "temporary failure"
        plugin._queue._write(tasks)

    retried = plugin.download(token, tmp_path)

    assert retried[1] == first[1]
    tasks = plugin._queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["state"] == "pending"
    assert tasks[0]["progress"] == 0.0
    assert tasks[0]["error"] == ""


def test_active_queue_tasks_project_to_native_download_list_and_filter(monkeypatch):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin._queue, "wake", lambda: False)
    monkeypatch.setattr(plugin, "_start_queue", lambda: True)
    pending = DownloadTask(
        task_id="pending-task",
        source_key="cms-demo",
        media_id="cms-demo:42",
        title="排队电视剧",
        year="2026",
        media_type="tv",
        season=2,
        episode=3,
        url="https://example.test/pending.m3u8",
        root="/downloads/tv",
        host_media_source="themoviedb",
        host_media_id="123",
        state="pending",
    )
    running = DownloadTask(
        task_id="running-task",
        source_key="cms-demo",
        media_id="cms-demo:43",
        title="下载中电影",
        year="2025",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/running.m3u8",
        root="/downloads/movie",
        state="running",
        progress=0.42,
    )
    completed = DownloadTask(
        task_id="completed-task",
        source_key="cms-demo",
        media_id="cms-demo:44",
        title="已完成电影",
        year="2024",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/completed.m3u8",
        root="/downloads/movie",
        state="completed",
    )
    paused = DownloadTask(
        task_id="paused-task",
        source_key="cms-demo",
        media_id="cms-demo:45",
        title="已暂停电影",
        year="2024",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/paused.m3u8",
        root="/downloads/movie",
        state="paused",
    )
    plugin.save_data(plugin._queue.DATA_KEY, [
        pending.to_dict(),
        running.to_dict(),
        completed.to_dict(),
        paused.to_dict(),
    ])

    module = plugin.get_module()
    assert "list_torrents" in module
    torrents = module["list_torrents"](status=SimpleNamespace(value="下载中"))
    assert [torrent.hash for torrent in torrents] == ["paused-task", "running-task", "pending-task"]
    assert all(torrent.downloader == "LunaTVSource" for torrent in torrents)
    assert next(torrent for torrent in torrents if torrent.hash == "paused-task").state == "paused"
    assert all(torrent.state == "downloading" for torrent in torrents if torrent.hash != "paused-task")
    assert next(torrent for torrent in torrents if torrent.hash == "running-task").progress == 42.0
    pending_torrent = next(torrent for torrent in torrents if torrent.hash == "pending-task")
    assert pending_torrent.progress == 0.0
    assert pending_torrent.title == "排队电视剧 第2季（共1集）"
    assert pending_torrent.name == "排队电视剧"
    assert pending_torrent.save_path == "/downloads/tv"
    assert pending_torrent.season_episode == "第2季 · 共1集 · 已下载0/1"
    assert pending_torrent.left_time == "已下载 0/1 集"
    assert _field(pending_torrent.media, "season") == "第2季 · 共1集 · 已下载0/1"
    assert _field(pending_torrent.media, "episode") is None
    assert _field(pending_torrent.media, "media_source") == "themoviedb"
    assert _field(pending_torrent.media, "media_id") == "123"

    # 其他标签页不投影 LunaTV 任务，并把查询继续交给对应的系统下载器。
    assert plugin.list_torrents(downloader="qBittorrent") is None
    assert plugin.list_torrents(downloader="下载器1") is None
    assert plugin.list_torrents(downloader="我的自定义客户端") is None
    assert sorted(
        torrent.hash for torrent in plugin.list_torrents(downloader=" lunatvsource ")
    ) == ["paused-task", "pending-task", "running-task"]
    assert plugin.list_torrents(status="completed") == []
    assert plugin.list_torrents(status="transfer") == []
    assert [torrent.hash for torrent in plugin.list_torrents(
        downloader="LunaTVSource", hashs=["pending-task"]
    )] == ["pending-task"]
    paused_torrents = plugin.list_torrents(status="paused")
    assert [torrent.hash for torrent in paused_torrents] == ["paused-task"]
    assert paused_torrents[0].state == "paused"
    assert module["start_torrents"](["paused-task"], downloader="LunaTVSource") is True
    assert next(item for item in plugin._queue.list_tasks() if item["task_id"] == "paused-task")["state"] == "pending"
    assert next(
        torrent
        for torrent in plugin.list_torrents(status="downloading")
        if torrent.hash == "paused-task"
    ).state == "downloading"

    assert {"start_torrents", "stop_torrents", "remove_torrents"} <= module.keys()
    assert module["stop_torrents"](["pending-task"], downloader="LunaTVSource") is True
    assert next(item for item in plugin._queue.list_tasks() if item["task_id"] == "pending-task")["state"] == "paused"
    assert module["start_torrents"](["pending-task"], downloader="LunaTVSource") is True
    assert next(item for item in plugin._queue.list_tasks() if item["task_id"] == "pending-task")["state"] == "pending"
    assert module["remove_torrents"](
        ["pending-task"], delete_file=True, downloader="LunaTVSource"
    ) is True
    assert all(item["task_id"] != "pending-task" for item in plugin._queue.list_tasks())
    assert module["stop_torrents"](["native-qbt-hash"], downloader="下载器1") is None


def test_tv_season_projects_one_row_and_native_controls_apply_to_whole_season(monkeypatch):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin._queue, "wake", lambda: False)

    def task(task_id: str, episode: int, state: str, *, season: int = 1, progress: float = 0.0):
        return DownloadTask(
            task_id=task_id,
            source_key="cms-demo",
            media_id="cms-demo:season-resource",
            title="整季测试剧",
            year="2026",
            media_type="tv",
            season=season,
            episode=episode,
            url=f"https://example.test/s{season:02d}e{episode:02d}.m3u8",
            root="/downloads/tv",
            host_media_source="themoviedb",
            host_media_id="456",
            source_name="光速资源",
            state=state,
            progress=progress,
        )

    plugin.save_data(plugin._queue.DATA_KEY, [
        task("season-1-completed", 1, "completed", progress=1.0).to_dict(),
        task("season-1-pending", 2, "pending", progress=0.5).to_dict(),
        task("season-1-paused", 3, "paused").to_dict(),
        task("season-2-pending", 1, "pending", season=2).to_dict(),
    ])

    torrents = plugin.list_torrents(downloader="LunaTVSource")
    assert len(torrents) == 2
    season_one = next(
        torrent for torrent in torrents if torrent.season_episode.startswith("第1季")
    )
    assert season_one.hash in {"season-1-pending", "season-1-paused"}
    assert season_one.title == "整季测试剧 第1季（共3集）"
    assert season_one.name == "整季测试剧"
    assert season_one.season_episode == "第1季 · 共3集 · 已下载1/3"
    assert season_one.left_time == "已下载 1/3 集"
    assert season_one.progress == pytest.approx(50.0)
    assert _field(season_one.media, "season") == "第1季 · 共3集 · 已下载1/3"
    assert _field(season_one.media, "episode") is None

    assert plugin.stop_torrents([season_one.hash], downloader="LunaTVSource") is True
    states = {item["task_id"]: item["state"] for item in plugin._queue.list_tasks()}
    assert states["season-1-completed"] == "completed"
    assert states["season-1-pending"] == "paused"
    assert states["season-1-paused"] == "paused"
    assert states["season-2-pending"] == "pending"

    assert plugin.start_torrents([season_one.hash], downloader="LunaTVSource") is True
    states = {item["task_id"]: item["state"] for item in plugin._queue.list_tasks()}
    assert states["season-1-pending"] == "pending"
    assert states["season-1-paused"] == "pending"
    assert states["season-2-pending"] == "pending"

    assert plugin.remove_torrents(
        [season_one.hash], delete_file=False, downloader="LunaTVSource"
    ) is True
    remaining = {item["task_id"] for item in plugin._queue.list_tasks()}
    assert remaining == {"season-2-pending"}


def test_native_resume_wakes_serial_queue(monkeypatch, tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    task = DownloadTask(
        task_id="paused-native-task",
        source_key="cms-demo",
        media_id="cms-demo:46",
        title="继续下载电影",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/resume.m3u8",
        root=str(tmp_path),
        state="paused",
    )
    plugin.save_data(plugin._queue.DATA_KEY, [task.to_dict()])
    started = threading.Event()

    def run_one():
        started.set()
        return {"processed": 1}

    monkeypatch.setattr(plugin._queue, "wake", run_one)

    assert plugin.start_torrents([task.task_id], downloader="LunaTVSource") is True
    assert started.wait(timeout=1)
    assert plugin._queue.list_tasks()[0]["state"] == "pending"


def test_active_queue_projection_uses_host_downloader_torrent_when_available(monkeypatch):
    class HostDownloaderTorrent:
        def __init__(self, **values):
            self.__dict__.update(values)

    monkeypatch.setattr(
        plugin_module,
        "_schemas",
        SimpleNamespace(DownloaderTorrent=HostDownloaderTorrent),
    )
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    task = DownloadTask(
        task_id="host-torrent-task",
        source_key="cms-demo",
        media_id="cms-demo:45",
        title="宿主投影",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/host.m3u8",
        root="/downloads/movie",
    )
    plugin.save_data(plugin._queue.DATA_KEY, [task.to_dict()])

    torrents = plugin.list_torrents()
    assert len(torrents) == 1
    assert isinstance(torrents[0], HostDownloaderTorrent)


def test_active_queue_projection_reports_partial_size_and_speed(monkeypatch, tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    task = DownloadTask(
        task_id="metrics-task",
        source_key="cms-demo",
        media_id="cms-demo:47",
        title="进度电影",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/metrics.m3u8",
        root=str(tmp_path),
        state="running",
        progress=0.5,
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
    partial = tmp_path / relative_dir / f"{filename}.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"x" * 1024)
    timestamps = iter([100.0, 102.0])
    monkeypatch.setattr(plugin_module.time, "monotonic", lambda: next(timestamps))

    first = plugin._active_download_torrent(task)
    partial.write_bytes(b"x" * 3072)
    second = plugin._active_download_torrent(task)

    assert first.size == 2048.0
    assert first.dlspeed == "0.0B"
    assert second.size == 6144.0
    assert second.dlspeed == "1.0K"


def test_active_queue_projection_clamps_fractional_progress_to_percent():
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    task = DownloadTask(
        task_id="overreported-progress",
        source_key="cms-demo",
        media_id="cms-demo:46",
        title="进度边界",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/progress.m3u8",
        root="/downloads/movie",
        state="running",
        progress=1.2,
    )

    assert plugin._active_download_torrent(task).progress == 100.0
    task.progress = -0.1
    assert plugin._active_download_torrent(task).progress == 0.0


def test_resource_download_event_prepares_host_chain_before_directory_validation(
    monkeypatch, tmp_path: Path
):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    wakeups = []
    monkeypatch.setattr(plugin, "_start_queue", lambda: wakeups.append(True))
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

    assert event_data.cancel is False
    assert event_data.source == "LunaTVSource"
    assert event_data.reason == "已准备 LunaTV 下载目录，继续交由 MoviePilot 下载链处理"
    assert event_data.options["save_path"] == str(tmp_path)
    assert plugin._queue.list_tasks() == []
    assert wakeups == []

    result = plugin.download(token, Path(event_data.options["save_path"]))

    assert result is not None
    assert result[0] == "LunaTVSource"
    assert result[1]
    tasks = plugin._queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["url"] == "https://example.test/event.m3u8"
    assert tasks[0]["root"] == str(tmp_path)
    assert wakeups == [True]


def test_resource_download_event_uses_moviepilot_local_root(monkeypatch):
    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(
        plugin,
        "_system_directory_info",
        lambda media_type: {
            "download_path": "/media/incoming",
            "media_type": media_type,
        },
    )
    token = plugin._resource_token(
        {
            "url": "https://example.test/event-system-root.m3u8",
            "title": "系统目录电影",
            "media_type": "movie",
            "season": 1,
            "episode": 1,
            "media_id": "demo:system-root",
        }
    )
    event_data = SimpleNamespace(
        context=SimpleNamespace(torrent_info=SimpleNamespace(enclosure=token)),
        cancel=False,
        source=None,
        reason=None,
    )

    plugin._on_resource_download(SimpleNamespace(event_data=event_data))

    assert event_data.cancel is False
    assert event_data.source == "LunaTVSource"
    assert event_data.options["save_path"] == "/media/incoming"
    assert plugin._queue.list_tasks() == []


def test_resource_download_event_ignores_non_lunatv_resource():
    plugin = _plugin({"enabled": True, "download_root": "/media/incoming"})
    event_data = SimpleNamespace(
        context=SimpleNamespace(
            torrent_info=SimpleNamespace(enclosure="https://example.test/native.torrent")
        ),
        cancel=False,
        source="native",
        reason="unchanged",
    )

    plugin._on_resource_download(SimpleNamespace(event_data=event_data))

    assert event_data.cancel is False
    assert event_data.source == "native"
    assert event_data.reason == "unchanged"
    assert plugin._queue.list_tasks() == []


def test_resource_download_event_without_plugin_root_keeps_host_chain():
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    token = plugin._resource_token({
        "url": "https://example.test/event-no-root.m3u8",
        "title": "事件电影",
        "media_type": "movie",
    })
    event_data = SimpleNamespace(
        context=SimpleNamespace(torrent_info=SimpleNamespace(enclosure=token)),
        cancel=False,
        source="",
        reason="",
    )

    plugin._on_resource_download(SimpleNamespace(event_data=event_data))

    assert event_data.cancel is False
    assert event_data.source == "LunaTVSource"
    assert event_data.reason == "未配置 LunaTV 下载目录，继续交由 MoviePilot 处理"
    assert plugin._queue.list_tasks() == []


def test_native_transfer_uses_host_identity(monkeypatch, tmp_path: Path):
    captured = {}

    class MediaSource(str, Enum):
        TMDB = "themoviedb"

    class MediaType(str, Enum):
        MOVIE = "电影"
        TV = "电视剧"

    class MetaInfo:
        def __init__(self, title=None, year=None):
            self.title = title
            self.year = year

    class StorageChain:
        def get_file_item(self, **kwargs):
            return object()

    class TransferChain:
        def manual_transfer(self, **kwargs):
            captured.update(kwargs)
            return True, ""

    monkeypatch.setattr(plugin_module, "_HostMediaSource", MediaSource)
    monkeypatch.setattr(plugin_module, "_HostMediaType", MediaType)
    monkeypatch.setattr(plugin_module, "_HostMetaInfo", MetaInfo)
    monkeypatch.setattr(plugin_module, "_HostStorageChain", StorageChain)
    monkeypatch.setattr(plugin_module, "_HostTransferChain", TransferChain)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "generate_nfo": True})
    monkeypatch.setattr(
        plugin,
        "_system_directory_info",
        lambda *_args, **_kwargs: {
            "library_path": str(tmp_path / "library"),
            "transfer_type": "move",
        },
    )
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
    assert captured["transfer_type"] == "move"
    assert captured["scrape"] is True


def test_native_movie_transfer_clears_season_metadata(monkeypatch, tmp_path: Path):
    captured = {}

    class MediaSource(str, Enum):
        TMDB = "themoviedb"

    class MediaType(str, Enum):
        MOVIE = "电影"
        TV = "电视剧"

    class MetaInfo:
        def __init__(self, title=None, year=None):
            self.title = title
            self.year = year
            # Reproduce a host parser/default that would otherwise leak a
            # synthetic first season into a movie transfer.
            self.type = MediaType.TV
            self.begin_season = 1
            self.end_season = 1
            self.total_season = 1
            self.begin_episode = 1
            self.end_episode = 1
            self.total_episode = 1

    class StorageChain:
        def get_file_item(self, **kwargs):
            return object()

    class TransferChain:
        def manual_transfer(self, **kwargs):
            raise AssertionError("电影不应交给会重新推断季集的 manual_transfer")

        def do_transfer(self, **kwargs):
            captured.update(kwargs)
            return True, ""

    monkeypatch.setattr(plugin_module, "_HostMediaSource", MediaSource)
    monkeypatch.setattr(plugin_module, "_HostMediaType", MediaType)
    monkeypatch.setattr(plugin_module, "_HostMetaInfo", MetaInfo)
    monkeypatch.setattr(plugin_module, "_HostStorageChain", StorageChain)
    monkeypatch.setattr(plugin_module, "_HostTransferChain", TransferChain)
    plugin = _plugin()
    monkeypatch.setattr(
        plugin,
        "_system_directory_info",
        lambda *_args, **_kwargs: {
            "library_path": str(tmp_path / "library"),
            "transfer_type": "copy",
        },
    )
    task = SimpleNamespace(
        mode="download",
        media_type="movie",
        title="出入平安",
        year="2024",
        root=str(tmp_path),
        source_key="cms-demo",
        media_id="cms-demo:42",
        host_media_source="themoviedb",
        host_media_id="1241918",
        season=1,
        episode=1,
    )

    assert plugin._native_transfer(task, str(tmp_path / "movie.mp4")) == "moviepilot"
    assert captured["mtype"] is MediaType.MOVIE
    assert captured["season"] is None
    assert captured["target_path"] == tmp_path / "library"
    assert captured["transfer_type"] == "copy"
    assert captured["manual"] is True
    assert captured["scrape"] is False
    assert captured["sync_extra_files"] is True
    meta = captured["meta"]
    assert meta.type is MediaType.MOVIE
    assert meta.begin_season is None
    assert meta.end_season is None
    assert meta.total_season is None
    assert meta.begin_episode is None
    assert meta.end_episode is None
    assert meta.total_episode is None


def test_native_movie_transfer_detects_sibling_library_without_season(monkeypatch, tmp_path: Path):
    captured = {}

    class MediaSource(str, Enum):
        TMDB = "themoviedb"

    class MediaType(str, Enum):
        MOVIE = "电影"
        TV = "电视剧"

    class MetaInfo:
        def __init__(self, title=None, year=None):
            self.title = title
            self.year = year
            self.type = MediaType.TV
            self.begin_season = 1
            self.end_season = 1
            self.total_season = 1
            self.begin_episode = 1
            self.end_episode = 1
            self.total_episode = 1

    class StorageChain:
        def get_file_item(self, **kwargs):
            return object()

    class TransferChain:
        def manual_transfer(self, **kwargs):
            raise AssertionError("电影不应交给会重新推断季集的 manual_transfer")

        def do_transfer(self, **kwargs):
            captured.update(kwargs)
            return True, ""

    media_root = tmp_path / "media"
    incoming = media_root / "incoming"
    movies = media_root / "movies"
    incoming.mkdir(parents=True)
    movies.mkdir()

    monkeypatch.setattr(plugin_module, "_HostMediaSource", MediaSource)
    monkeypatch.setattr(plugin_module, "_HostMediaType", MediaType)
    monkeypatch.setattr(plugin_module, "_HostMetaInfo", MetaInfo)
    monkeypatch.setattr(plugin_module, "_HostStorageChain", StorageChain)
    monkeypatch.setattr(plugin_module, "_HostTransferChain", TransferChain)
    monkeypatch.setattr(plugin_module, "_HostDirectoryHelper", None)
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", None)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_system_directory_info", lambda *_args, **_kwargs: None)
    task = SimpleNamespace(
        mode="download",
        media_type="movie",
        title="鹬",
        year="2016",
        root=str(incoming),
        source_key="cms-demo",
        media_id="cms-demo:42",
        host_media_source="themoviedb",
        host_media_id="399106",
        season=1,
        episode=1,
    )

    assert plugin._native_transfer(task, str(incoming / "鹬 (2016).mp4")) == "moviepilot"
    assert captured["target_path"] == movies
    assert captured["transfer_type"] == "move"
    assert captured["season"] is None
    assert captured["meta"].type is MediaType.MOVIE
    assert captured["meta"].begin_season is None
    assert captured["meta"].begin_episode is None


def test_task_media_identity_prefers_host_fields():
    task = SimpleNamespace(
        source_key="lunatv",
        media_id="not-used",
        host_media_source="themoviedb",
        host_media_id="98765",
    )
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

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

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

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
            assert state in {None, "R,P"}
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
        def search(self, query, **_kwargs):
            assert query == "疯狂动物城2"
            return [result]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
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


def test_refresh_plugin_subscription_reuses_tmdb_identity_for_organize(monkeypatch, tmp_path: Path):
    result = _result_from_item(
        CmsSource("cms-demo", "演示源", "https://cms.example/vod"),
        {
            "vod_id": "42",
            "vod_name": "示例剧",
            "vod_year": "2026",
            "type_name": "电视剧",
            "vod_play_url": "S01E01$https://example.test/s01e01.m3u8",
        },
    )
    subscribe = SimpleNamespace(
        state="R",
        name="示例剧",
        year="2026",
        type="电视剧",
        season=1,
        media_source="lunatv",
        media_id="cms-demo:42",
        save_path=str(tmp_path),
    )
    subscribe_module = ModuleType("app.db.oper.subscribe")

    class FakeSubscribeOper:
        def list(self, state=None):
            return [subscribe]

    subscribe_module.SubscribeOper = FakeSubscribeOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_module.__path__ = []
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.subscribe = subscribe_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.subscribe", subscribe_module)

    class Client:
        def search(self, _query, **_kwargs):
            return [result]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda item: (item, {
            "status": "matched",
            "media_source": "themoviedb",
            "media_id": "999",
            "title": "TMDB 示例剧",
        }),
    )

    response = plugin.refresh_subscriptions()
    assert response["queued"] == 1
    task = plugin._queue.list_tasks()[0]
    assert task["title"] == "TMDB 示例剧"
    assert task["host_media_source"] == "themoviedb"
    assert task["host_media_id"] == "999"
    assert task["root"] == str(tmp_path)


def test_refresh_plugin_season_subscription_researches_and_queues_whole_season(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-demo", "演示源", "https://cms.example/vod")
    rows = [
        _result_from_item(
            source,
            {
                "vod_id": "episode-1",
                "vod_name": "示例剧 第一季 第1集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://example.test/s01e01.m3u8",
            },
        ),
        _result_from_item(
            source,
            {
                "vod_id": "episode-2",
                "vod_name": "示例剧 第一季 第2集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": "第2集$https://example.test/s01e02.m3u8",
            },
        ),
    ]
    subscribe = SimpleNamespace(
        state="R",
        name="示例剧",
        year="2026",
        type="电视剧",
        season=1,
        media_source="lunatv",
        media_id="cms-demo:episode-1",
        save_path=str(tmp_path),
    )
    subscribe_module = ModuleType("app.db.oper.subscribe")

    class FakeSubscribeOper:
        def list(self, state=None):
            assert state == "R,P"
            return [subscribe]

    subscribe_module.SubscribeOper = FakeSubscribeOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_module.__path__ = []
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.subscribe = subscribe_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.subscribe", subscribe_module)

    searches = []

    class Client:
        def detail(self, *_args):
            raise AssertionError("season subscription must re-search, not detail one episode")

        def search(self, query, **_kwargs):
            searches.append(query)
            return rows

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_start_queue", lambda: True)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))

    response = plugin.refresh_subscriptions()
    tasks = sorted(plugin._queue.list_tasks(), key=lambda task: task["episode"])

    assert searches
    assert response["queued"] == 2
    assert [(task["season"], task["episode"]) for task in tasks] == [(1, 1), (1, 2)]


def test_refresh_plugin_season_subscription_queues_highest_resolution_for_same_episode(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-demo", "演示源", "https://cms.example/vod")
    rows = [
        _result_from_item(
            source,
            {
                "vod_id": "episode-1-low",
                "vod_name": "示例剧 第一季 第1集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://example.test/480-s01e01.m3u8",
            },
        ),
        _result_from_item(
            source,
            {
                "vod_id": "episode-1-high",
                "vod_name": "示例剧 第一季 第1集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://example.test/1080-s01e01.m3u8",
            },
        ),
    ]
    subscribe = SimpleNamespace(
        state="R",
        name="示例剧",
        year="2026",
        type="电视剧",
        season=1,
        media_source="lunatv",
        media_id="cms-demo:episode-1-low",
        save_path=str(tmp_path),
    )
    subscribe_module = ModuleType("app.db.oper.subscribe")

    class FakeSubscribeOper:
        def list(self, state=None):
            assert state == "R,P"
            return [subscribe]

    subscribe_module.SubscribeOper = FakeSubscribeOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_module.__path__ = []
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.subscribe = subscribe_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.subscribe", subscribe_module)

    class Client:
        def search(self, _query, **_kwargs):
            return rows

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_start_queue", lambda: True)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {url: 1080 if "1080" in url else 480 for url in urls},
    )

    response = plugin.refresh_subscriptions()
    tasks = plugin._queue.list_tasks()

    assert response["queued"] == 1
    assert len(tasks) == 1
    assert tasks[0]["url"] == "https://example.test/1080-s01e01.m3u8"


def test_refresh_plugin_season_subscription_keeps_all_sources_seasons_separate(
    monkeypatch, tmp_path: Path
):
    source_a = CmsSource("cms-a", "源A", "https://a.example/vod")
    source_b = CmsSource("cms-b", "源B", "https://b.example/vod")
    rows = [
        _result_from_item(
            source_a,
            {
                "vod_id": "a-e1",
                "vod_name": "示例剧 第一季 第1集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://a.example/480-s01e01.m3u8",
            },
        ),
        _result_from_item(
            source_a,
            {
                "vod_id": "a-e2",
                "vod_name": "示例剧 第一季 第2集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": "第2集$https://a.example/480-s01e02.m3u8",
            },
        ),
        _result_from_item(
            source_b,
            {
                "vod_id": "b-e1",
                "vod_name": "示例剧 第一季 第1集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": "第1集$https://b.example/1080-s01e01.m3u8",
            },
        ),
    ]
    subscribe = SimpleNamespace(
        state="R",
        name="示例剧",
        year="2026",
        type="电视剧",
        season=1,
        media_source="lunatv",
        media_id="cms-a:a-e1",
        save_path=str(tmp_path),
    )
    subscribe_module = ModuleType("app.db.oper.subscribe")

    class FakeSubscribeOper:
        def list(self, state=None):
            assert state == "R,P"
            return [subscribe]

    subscribe_module.SubscribeOper = FakeSubscribeOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_module.__path__ = []
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.subscribe = subscribe_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.subscribe", subscribe_module)

    class Client:
        def search(self, _query, **_kwargs):
            return rows

    probe_calls = []

    def probe(urls):
        probe_calls.append(list(urls))
        return {url: 1080 if "1080" in url else 480 for url in urls}

    plugin = _plugin()
    plugin.init_plugin(
        {
            "enabled": True,
            "download_root": str(tmp_path),
            "source_strategy": "all",
        }
    )
    monkeypatch.setattr(plugin, "_start_queue", lambda: True)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(plugin, "_probe_resource_urls", probe)

    response = plugin.refresh_subscriptions()
    tasks = plugin._queue.list_tasks()

    assert response["queued"] == 3
    assert all(not urls for urls in probe_calls)
    assert sorted(
        (task["media_id"], task["episode"], task["url"]) for task in tasks
    ) == [
        ("cms-a:a-e1", 1, "https://a.example/480-s01e01.m3u8"),
        ("cms-a:a-e1", 2, "https://a.example/480-s01e02.m3u8"),
        ("cms-b:b-e1", 1, "https://b.example/1080-s01e01.m3u8"),
    ]


def test_native_history_number_parser_supports_ranges_and_native_markers():
    assert LunaTVSource._history_numbers("S02") == {2}
    assert LunaTVSource._history_numbers("E01-E03, E05") == {1, 2, 3, 5}
    assert LunaTVSource._history_numbers("第8至10集、12") == {8, 9, 10, 12}


def test_native_history_reader_supports_legacy_file_lookup(monkeypatch, tmp_path: Path):
    file_calls = []

    class FakeDownloadHistoryOper:
        def get_by_media_identity(self, **_kwargs):
            return [
                SimpleNamespace(
                    download_hash="inactive-history",
                    seasons="S02",
                    episodes="E03",
                ),
                SimpleNamespace(
                    download_hash="active-history",
                    seasons="S02",
                    episodes="E04",
                ),
            ]

        def get_files_by_hash(self, download_hash):
            file_calls.append(download_hash)
            return [SimpleNamespace(state=0 if download_hash == "inactive-history" else 1)]

    download_module = ModuleType("app.db.oper.downloadhistory")
    download_module.DownloadHistoryOper = FakeDownloadHistoryOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_module.__path__ = []
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.downloadhistory = download_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.downloadhistory", download_module)

    plugin = _plugin()

    def task(episode):
        return DownloadTask(
            task_id=f"legacy-history-{episode}",
            source_key="cms-demo",
            media_id="cms-demo:42",
            title="示例剧",
            year="2026",
            media_type="tv",
            season=2,
            episode=episode,
            url="https://example.test/episode.m3u8",
            root=str(tmp_path),
            host_media_source="themoviedb",
            host_media_id="999",
        )

    assert plugin._native_history_has_episode(task(3)) is False
    assert plugin._native_history_has_episode(task(4)) is True
    assert file_calls == [
        "inactive-history",
        "active-history",
        "inactive-history",
        "active-history",
    ]


def test_refresh_does_not_requeue_episode_kept_in_native_tmdb_history(monkeypatch, tmp_path: Path):
    result = _result_from_item(
        CmsSource("cms-demo", "演示源", "https://cms.example/vod"),
        {
            "vod_id": "42",
            "vod_name": "示例剧",
            "vod_year": "2026",
            "type_name": "电视剧",
            "vod_play_url": "S02E03$https://example.test/s02e03.m3u8",
        },
    )
    subscribe = SimpleNamespace(
        state="R",
        name="示例剧",
        year="2026",
        type="电视剧",
        season=2,
        media_source="lunatv",
        media_id="cms-demo:42",
        save_path=str(tmp_path),
    )
    identity_calls = []
    file_calls = []

    class FakeSubscribeOper:
        def list(self, state=None):
            assert state == "R,P"
            return [subscribe]

    class FakeDownloadHistoryOper:
        def get_by_media_identity(self, media_source, media_id):
            identity_calls.append((str(getattr(media_source, "value", media_source)), media_id))
            return [
                SimpleNamespace(
                    download_hash="",
                    seasons="S02",
                    episodes="E01-E03,E05",
                ),
                SimpleNamespace(
                    download_hash="native-history",
                    seasons="S02",
                    episodes="E01-E03,E05",
                ),
            ]

        def get_files_by_hash(self, download_hash, state=None):
            file_calls.append((download_hash, state))
            return [SimpleNamespace(fullpath="/library/示例剧/Season 02/S02E03.mp4", state=1)]

    subscribe_module = ModuleType("app.db.oper.subscribe")
    subscribe_module.SubscribeOper = FakeSubscribeOper
    download_module = ModuleType("app.db.oper.downloadhistory")
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
        def search(self, _query, **_kwargs):
            return [result]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_start_queue", lambda: True)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda item: (item, {
            "status": "matched",
            "media_source": "themoviedb",
            "media_id": "999",
            "title": "TMDB 示例剧",
        }),
    )

    response = plugin.refresh_subscriptions()
    assert response["queued"] == 0
    assert response["reconciled"] == 1
    tasks = plugin._queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["episode"] == 3
    assert tasks[0]["state"] == "completed"
    assert tasks[0]["host_media_id"] == "999"
    assert plugin.list_torrents() == []
    assert identity_calls == [("themoviedb", "999")]
    assert file_calls == [("native-history", 1)]


def test_refresh_routes_movie_and_tv_subscriptions_to_native_media_directories(monkeypatch):
    movie = _result_from_item(
        CmsSource("movie-source", "电影源", "https://movie.example/vod"),
        {
            "vod_id": "m1",
            "vod_name": "示例电影",
            "vod_year": "2026",
            "type_name": "电影",
            "vod_play_url": "正片$https://example.test/movie.m3u8",
        },
    )
    show = _result_from_item(
        CmsSource("tv-source", "电视剧源", "https://tv.example/vod"),
        {
            "vod_id": "t1",
            "vod_name": "示例剧",
            "vod_year": "2026",
            "type_name": "电视剧",
            "vod_play_from": "在线播放",
            "vod_play_url": "S01E01$https://example.test/show-s01e01.m3u8",
        },
    )
    subscriptions = [
        SimpleNamespace(state="R", name="示例电影", year="2026", type="电影", season=0,
                        media_source="lunatv", media_id="", save_path=""),
        SimpleNamespace(state="P", name="示例剧", year="2026", type="电视剧", season=1,
                        media_source="lunatv", media_id="", save_path=""),
    ]
    subscribe_module = ModuleType("app.db.oper.subscribe")

    class FakeSubscribeOper:
        def list(self, state=None):
            return subscriptions

    subscribe_module.SubscribeOper = FakeSubscribeOper
    app_module = ModuleType("app")
    app_module.__path__ = []
    app_db_module = ModuleType("app.db")
    app_db_module.__path__ = []
    app_db_oper_module = ModuleType("app.db.oper")
    app_db_oper_module.__path__ = []
    app_module.db = app_db_module
    app_db_module.oper = app_db_oper_module
    app_db_oper_module.subscribe = subscribe_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", app_db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", app_db_oper_module)
    monkeypatch.setitem(sys.modules, "app.db.oper.subscribe", subscribe_module)

    class Directory:
        def __init__(self, media_type, path):
            self.storage = "local"
            self.download_path = path
            self.library_path = path.replace("incoming", "library")
            self.media_type = media_type
            self.priority = 1
            self.name = media_type

    class DirectoryHelper:
        def get_download_dirs(self):
            return [Directory("电影", "/media/incoming/movies"), Directory("电视剧", "/media/incoming/tv")]

    class Client:
        def search(self, query, **_kwargs):
            return [movie if query == "示例电影" else show]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_start_queue", lambda: True)
    monkeypatch.setattr(plugin_module, "_HostDirectoryHelper", DirectoryHelper)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda item: (item, {}))
    monkeypatch.setattr(plugin._ai, "normalize", lambda title, *_args: (title, False))

    first = plugin.refresh_subscriptions()
    second = plugin.refresh_subscriptions()
    assert first["queued"] == 2
    assert second["queued"] == 0
    tasks = sorted(plugin._queue.list_tasks(), key=lambda item: item["media_type"])
    assert [(task["media_type"], task["root"]) for task in tasks] == [
        ("movie", "/media/incoming/movies"),
        ("tv", "/media/incoming/tv"),
    ]


def test_local_episode_path_requires_completed_download_or_strm_artifact(tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

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
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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


def test_resource_torrents_mark_lunatv_movie_and_season_dialog_contract(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    movie = _result_from_item(
        CmsSource("movie", "电影源", "https://movie.example/vod"),
        {
            "vod_id": "movie-1",
            "vod_name": "示例电影",
            "vod_year": "2026",
            "type_name": "电影",
            "vod_play_url": "正片$https://video.example/movie.m3u8",
        },
    )
    show = _result_from_item(
        CmsSource("show", "电视剧源", "https://show.example/vod"),
        {
            "vod_id": "show-1",
            "vod_name": "示例剧",
            "vod_year": "2026",
            "type_name": "电视剧",
            "vod_play_from": "在线播放",
            "vod_play_url": (
                "01$https://video.example/show-s01e01.m3u8#"
                "02$https://video.example/show-s01e02.m3u8"
            ),
        },
    )

    class Client:
        def search(self, *_args, **_kwargs):
            return [movie, show]

    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(
        plugin,
        "_system_directory_info",
        lambda media_type: {
            "download_path": "/media/incoming",
            "media_type": media_type,
        },
    )
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_probe_resource_urls", lambda _urls: {})

    items = plugin._resource_torrents("示例资源")
    movie_item = next(item for item in items if item.category == "电影")
    season_item = next(item for item in items if item.category == "电视剧")

    for item in (movie_item, season_item):
        assert item.site_downloader == "LunaTVSource"
        assert item.download_path == "/media/incoming"
    assert len(plugin._decode_resource_token(season_item.enclosure)["episodes"]) == 2


def test_resource_torrents_falls_back_for_legacy_torrent_info_without_download_path(monkeypatch):
    class LegacyTorrentInfo:
        def __init__(
            self,
            *,
            site_name,
            title,
            description,
            media_source,
            media_id,
            enclosure,
            page_url,
            size,
            seeders,
            uploadvolumefactor,
            downloadvolumefactor,
            pri_order,
            category,
            labels,
        ):
            self.site_name = site_name
            self.title = title
            self.description = description
            self.media_source = media_source
            self.media_id = media_id
            self.enclosure = enclosure
            self.page_url = page_url
            self.size = size
            self.seeders = seeders
            self.uploadvolumefactor = uploadvolumefactor
            self.downloadvolumefactor = downloadvolumefactor
            self.pri_order = pri_order
            self.category = category
            self.labels = labels

        def __setattr__(self, name, value):
            if name == "download_path":
                raise AttributeError(name)
            object.__setattr__(self, name, value)

    movie = _result_from_item(
        CmsSource("legacy", "旧版源", "https://legacy.example/vod"),
        {
            "vod_id": "legacy-1",
            "vod_name": "旧版电影",
            "type_name": "电影",
            "vod_play_url": "正片$https://video.example/legacy.m3u8",
        },
    )

    class Client:
        def search(self, *_args, **_kwargs):
            return [movie]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": "/media/incoming"})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", LegacyTorrentInfo)
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_probe_resource_urls", lambda _urls: {})

    item = plugin._resource_torrents("旧版电影")[0]

    assert item.site_downloader == "LunaTVSource"
    assert not hasattr(item, "download_path")


def test_sync_media_server_runs_async_and_deduplicates_active_sync(monkeypatch):
    sync_calls = []
    started_threads = []

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)

    class DeferredThread:
        def __init__(self, target, **_kwargs):
            self.target = target
            started_threads.append(self)

        def start(self):
            return None

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module.threading, "Thread", DeferredThread)

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})

    assert plugin._sync_media_server() is True
    assert sync_calls == []
    assert len(started_threads) == 1
    assert plugin._media_sync_running is True

    assert plugin._sync_media_server() is False
    assert len(started_threads) == 1

    started_threads[0].target()
    assert sync_calls == ["Emby"]
    assert plugin._media_sync_running is False


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

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
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

def test_season_media_cards_are_not_order_dependent_when_precise_row_exists():
    ambiguous = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="bundle",
        title="示例剧",
        year="2024",
        media_type="tv",
        remark="",
        episodes=(),
        season_range=(1, 1),
        season_ambiguous=True,
    )
    precise = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="episode-1",
        title="示例剧",
        year="2024",
        media_type="tv",
        remark="",
        episodes=(
            CmsEpisode(1, 1, "第1集", "https://video.example/s01e01.m3u8"),
        ),
        season_range=(0, 0),
        season_ambiguous=False,
    )

    for rows in ([ambiguous, precise], [precise, ambiguous]):
        cards = LunaTVSource._season_media_cards(rows)

        assert len(cards) == 1
        assert cards[0].season_ambiguous is False
        assert [(item.season, item.episode) for item in cards[0].episodes] == [(1, 1)]



def test_quality_cache_prunes_expired_entries_and_enforces_capacity(monkeypatch):
    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin_module.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(plugin_module, "probe_stream_height", lambda *_args, **_kwargs: 1080)
    plugin._quality_cache = {
        "expired": (0.0, 1080),
        **{
            f"https://video.example/{index}.m3u8": (999.0 - index / 10000, 1080)
            for index in range(plugin_module._QUALITY_CACHE_MAX_ENTRIES + 20)
        },
    }
    plugin._quality_probe_ms = {
        key: 100 for key in plugin._quality_cache
    }

    assert plugin._probe_quality("https://video.example/new.m3u8") == 1080
    assert "expired" not in plugin._quality_cache
    assert "expired" not in plugin._quality_probe_ms
    assert len(plugin._quality_cache) <= plugin_module._QUALITY_CACHE_MAX_ENTRIES
    assert set(plugin._quality_probe_ms) <= set(plugin._quality_cache)


def test_quality_probe_caches_latency_with_height(monkeypatch):
    probe_calls = []
    monotonic_values = iter((100.0, 100.123, 101.0))
    monkeypatch.setattr(plugin_module.time, "monotonic", lambda: next(monotonic_values))

    def probe(url, **_kwargs):
        probe_calls.append(url)
        return 1080

    monkeypatch.setattr(plugin_module, "probe_stream_height", probe)
    plugin = _plugin({"enabled": True})
    url = "https://video.example/cached-latency.m3u8"

    assert plugin._probe_quality(url) == 1080
    assert plugin._probe_latency_ms(url) == 123
    assert plugin._probe_quality(url) == 1080
    assert plugin._probe_latency_ms(url) == 123
    assert probe_calls == [url]



def test_quality_probe_passes_explicit_private_network_allowlist(monkeypatch):
    captured = {}

    def probe(*_args, **kwargs):
        captured.update(kwargs)
        return 1080

    plugin = _plugin(
        {
            "enabled": True,
            "probe_allowed_private_ranges": "10.0.0.0/8, 192.168.0.0/16",
        }
    )
    monkeypatch.setattr(plugin_module, "probe_stream_height", probe)

    assert plugin._probe_quality("http://10.0.0.8/video.m3u8") == 1080
    assert captured["allowed_private_ranges"] == (
        "10.0.0.0/8",
        "192.168.0.0/16",
    )



def test_resource_search_cache_prunes_expired_entries_and_enforces_capacity():
    plugin = _plugin({"enabled": True})
    plugin._resource_search_cache = {
        "expired": (0.0, []),
        **{
            f"fresh-{index}": (999.0 - index / 10000, [])
            for index in range(plugin_module._RESOURCE_SEARCH_CACHE_MAX_ENTRIES + 20)
        },
    }

    plugin._prune_resource_search_cache(1000.0)

    assert "expired" not in plugin._resource_search_cache
    assert (
        len(plugin._resource_search_cache)
        <= plugin_module._RESOURCE_SEARCH_CACHE_MAX_ENTRIES
    )



def test_tmdb_cache_enforces_capacity_and_keeps_latest_entry():
    plugin = _plugin()
    plugin._tmdb_cache = {
        f"old-{index}": {"status": "matched", "media_id": str(index)}
        for index in range(plugin_module._TMDB_CACHE_MAX_ENTRIES + 20)
    }

    plugin._store_tmdb_cache_entry(
        "latest",
        {"status": "matched", "media_id": "latest"},
   )

    assert len(plugin._tmdb_cache) == plugin_module._TMDB_CACHE_MAX_ENTRIES
    assert "old-0" not in plugin._tmdb_cache
    assert plugin._tmdb_cache["latest"]["media_id"] == "latest"


def test_manual_download_wakes_queue_once_only_for_new_task(monkeypatch, tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    wakeups = []
    monkeypatch.setattr(plugin, "_start_queue", lambda: wakeups.append(True))
    payload = {
        "url": "https://example.test/manual.m3u8",
        "title": "手动下载",
        "year": "2026",
        "media_type": "movie",
    }

    assert plugin.api_download(payload)["success"] is True
    assert plugin.api_download(payload)["success"] is False
    assert wakeups == [True]

def test_resource_torrents_forwards_lunatv_progress_callback(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    calls = []

    class Client:
        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            callback = kwargs["progress_callback"]
            callback(finished=1, total=2, text="CMS 1/2")
            callback(finished=2, total=2, text="CMS 2/2")
            return []

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    progress = []

    def on_progress(**event):
        progress.append(event)
        if event["finished"] == 1:
            raise RuntimeError("broken host callback")

    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})

    assert plugin._resource_torrents("progress demo", progress_callback=on_progress) == []
    assert calls[0][0] == "progress demo"
    assert set(calls[0][1]) == {
        "limit",
        "source_limit",
        "stop_after_first_source",
        "require_playable",
        "expand_tv_episode_rows",
        "max_workers",
        "progress_callback",
    }
    assert [(event["finished"], event["total"], event["text"]) for event in progress] == [
        (1, 2, "LunaTV 正在搜索源 1/2"),
        (2, 2, "LunaTV 正在搜索源 2/2"),
        (2, 2, "LunaTV 正在汇总资源并检测清晰度"),
        (2, 2, "LunaTV 正在按清晰度排序"),
    ]

def test_search_torrent_entrypoints_forward_progress_callback(monkeypatch):
    import asyncio

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    received = []
    callback = lambda **_event: None

    def resource_torrents(
        keyword,
        mtype=None,
        progress_callback=None,
        target_media_source=None,
        target_media_id=None,
        target_media_title=None,
        target_media_year=None,
    ):
        received.append(
            (
                keyword,
                mtype,
                progress_callback,
                target_media_source,
                target_media_id,
                target_media_title,
                target_media_year,
            )
        )
        return ["luna"]

    monkeypatch.setattr(plugin, "_resource_torrents", resource_torrents)

    assert plugin.search_torrents(
        site={},
        keyword="sync demo",
        mtype="tv",
        progress_callback=callback,
    ) == ["luna"]
    assert asyncio.run(
        plugin.async_search_torrents(
            site={},
            keyword="async demo",
            mtype="movie",
            progress_callback=callback,
        )
    ) == ["luna"]
    assert received == [
        ("sync demo", "tv", callback, None, None, None, None),
        ("async demo", "movie", callback, None, None, None, None),
    ]

@pytest.mark.parametrize(
    ("mtype", "first_media_type", "expected_media_type"),
    [
        ("欧美剧", "tv", "tv"),
        ("韩剧", "tv", "tv"),
        ("movie", "tv", "movie"),
        ("tv", "movie", "tv"),
    ],
)
def test_resource_search_context_uses_first_result_for_noncanonical_type(
    mtype: str,
    first_media_type: str,
    expected_media_type: str,
):
    first = CmsResult(
        source_key="demo",
        source_name="演示源",
        vod_id="42",
        title="示例作品",
        year="2024",
        media_type=first_media_type,
        remark="",
        episodes=(),
    )

    context = LunaTVSource._resource_search_context("示例作品", [first], mtype)

    assert context.media_type == expected_media_type

def _install_search_chain_module(monkeypatch, search_chain):
    app_module = ModuleType("app")
    app_module.__path__ = []
    chain_module = ModuleType("app.chain")
    chain_module.__path__ = []
    search_module = ModuleType("app.chain.search")
    search_module.SearchChain = search_chain
    app_module.chain = chain_module
    chain_module.search = search_module
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.chain", chain_module)
    monkeypatch.setitem(sys.modules, "app.chain.search", search_module)

def test_download_chain_bridge_enqueues_lunatv_and_preserves_native_downloads(
    monkeypatch, tmp_path: Path
):
    native_calls = []

    class DownloadChain:
        def download_single(self, context, *args, return_detail=False, **kwargs):
            native_calls.append((context, args, kwargs))
            return ("native-task", None) if return_detail else "native-task"

    original = DownloadChain.download_single
    _install_download_chain_module(monkeypatch, DownloadChain)

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    token = plugin._resource_token({
        "url": "https://example.test/movie-1080.m3u8",
        "title": "桥接电影",
        "year": "2026",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "media_id": "demo:bridge-movie",
    })
    context = SimpleNamespace(
        torrent_info=SimpleNamespace(
            enclosure=token,
            site_downloader="LunaTVSource",
            download_path=str(tmp_path),
        )
    )

    task_id, error = DownloadChain().download_single(
        context,
        username="tester",
        return_detail=True,
    )

    assert error is None
    assert task_id and task_id != "native-task"
    assert native_calls == []
    tasks = plugin._queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == task_id
    assert tasks[0]["url"] == "https://example.test/movie-1080.m3u8"
    assert tasks[0]["root"] == str(tmp_path)

    native_context = SimpleNamespace(
        torrent_info=SimpleNamespace(enclosure="magnet:?xt=urn:btih:native")
    )
    assert DownloadChain().download_single(native_context) == "native-task"
    assert DownloadChain().download_single(
        native_context,
        return_detail=True,
    ) == ("native-task", None)
    assert [call[0] for call in native_calls] == [native_context, native_context]

    monkeypatch.setattr(
        plugin,
        "download",
        lambda *_args, **_kwargs: (
            "LunaTVSource",
            None,
            None,
            "任务已在下载队列或历史记录中",
        ),
    )
    assert DownloadChain().download_single(context) is None
    assert DownloadChain().download_single(
        context,
        return_detail=True,
    ) == (None, "任务已在下载队列或历史记录中")

    plugin.stop_service()
    assert DownloadChain.download_single is original


def test_download_chain_bridge_honors_host_path_positional_detail_and_hot_reload(
    monkeypatch, tmp_path: Path
):
    native_calls = []

    class DownloadChain:
        def download_single(self, context, *args, return_detail=False, **kwargs):
            native_calls.append((context, args, kwargs))
            return ("native-task", None) if return_detail else "native-task"

    original = DownloadChain.download_single
    _install_download_chain_module(monkeypatch, DownloadChain)

    first = _plugin()
    first.init_plugin({"enabled": True})
    monkeypatch.setattr(first, "_start_queue", lambda: None)

    replacement = _plugin()
    replacement.init_plugin({"enabled": True})
    monkeypatch.setattr(replacement, "_start_queue", lambda: None)
    wrapped = DownloadChain.download_single
    assert wrapped is not original

    # A stale instance must not remove the bridge now owned by the replacement.
    first.stop_service()
    assert DownloadChain.download_single is wrapped

    token = replacement._resource_token({
        "url": "https://example.test/movie-positional.m3u8",
        "title": "位置参数电影",
        "year": "2026",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "media_id": "demo:positional-movie",
    })
    context = SimpleNamespace(
        torrent_info=SimpleNamespace(
            enclosure=token,
            site_downloader="LunaTVSource",
            download_path=None,
        )
    )
    host_root = tmp_path / "host-selected"

    task_id, error = DownloadChain().download_single(
        context,
        None,
        None,
        None,
        None,
        None,
        None,
        str(host_root),
        None,
        None,
        None,
        True,
    )

    assert error is None
    assert task_id
    assert native_calls == []
    tasks = replacement._queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["root"] == str(host_root)
    assert context.torrent_info.download_path == str(host_root)

    replacement.stop_service()
    assert DownloadChain.download_single is original


def test_plugin_search_bridge_augments_legacy_search_and_restores(monkeypatch):
    import asyncio

    class SearchChain:
        def __search_all_sites(self, **_kwargs):
            return ["native-sync"]

        async def __async_search_all_sites(self, **_kwargs):
            return ["native-async"]

        async def __async_search_all_sites_stream(self, **_kwargs):
            yield {"type": "heartbeat", "items": [], "text": "native heartbeat"}
            yield {
                "type": "done",
                "stage": "searching",
                "items": [],
                "text": "native done",
            }

    _install_search_chain_module(monkeypatch, SearchChain)
    plugin_module._SEARCH_BRIDGE.update(
        {"owner": None, "chain": None, "originals": {}, "mode": None}
    )
    sync_original = SearchChain._SearchChain__search_all_sites
    async_original = SearchChain._SearchChain__async_search_all_sites
    stream_original = SearchChain._SearchChain__async_search_all_sites_stream
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "search_torrents", lambda **_kwargs: ["plugin-sync"])

    async def plugin_async_search(**_kwargs):
        return ["plugin-async"]

    monkeypatch.setattr(plugin, "async_search_torrents", plugin_async_search)
    try:
        chain = SearchChain()
        assert chain._SearchChain__search_all_sites(keyword="demo") == [
            "native-sync",
            "plugin-sync",
        ]
        assert asyncio.run(
            chain._SearchChain__async_search_all_sites(keyword="demo")
        ) == ["native-async", "plugin-async"]

        async def collect_stream():
            return [
                event
                async for event in chain._SearchChain__async_search_all_sites_stream(
                    keyword="demo"
                )
            ]

        events = asyncio.run(collect_stream())
        assert [event["type"] for event in events] == ["heartbeat", "append", "done"]
        assert events[1]["items"] == ["plugin-async"]
        assert events[1]["text"] == "LunaTV 返回 1 条资源"
        assert events[-1]["text"] == "资源搜索完成，LunaTV 返回 1 条资源"
    finally:
        plugin.init_plugin({"enabled": False})

    assert SearchChain._SearchChain__search_all_sites is sync_original
    assert SearchChain._SearchChain__async_search_all_sites is async_original
    assert SearchChain._SearchChain__async_search_all_sites_stream is stream_original

def test_async_search_torrents_uses_context_callback_unless_explicit(monkeypatch):
    import asyncio

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    callbacks = []
    context_callback = lambda **_event: None
    explicit_callback = lambda **_event: None

    def fake_search_torrents(**kwargs):
        callbacks.append(kwargs.get("progress_callback"))
        return []

    monkeypatch.setattr(plugin, "search_torrents", fake_search_torrents)

    async def run():
        token = plugin_module._SEARCH_PROGRESS_CALLBACK.set(context_callback)
        try:
            await plugin.async_search_torrents(site={}, keyword="context")
            await plugin.async_search_torrents(
                site={},
                keyword="explicit",
                progress_callback=explicit_callback,
            )
        finally:
            plugin_module._SEARCH_PROGRESS_CALLBACK.reset(token)

    asyncio.run(run())
    assert callbacks == [context_callback, explicit_callback]

def test_native_search_stream_progress_precedes_native_append_and_done(monkeypatch):
    import asyncio

    native_calls = []
    plugin_search_calls = []

    class SearchChain:
        def search_plugin_torrents(self, **_kwargs):
            return ["native-plugin-sync"]

        async def async_search_plugin_torrents(self, **kwargs):
            native_calls.append(kwargs["keyword"])
            return await plugin.async_search_torrents(
                site={},
                keyword=kwargs["keyword"],
                page=kwargs.get("page", 0),
            )

        def __search_all_sites(self, **_kwargs):
            return ["native-sync"]

        async def __async_search_all_sites(self, **_kwargs):
            return ["native-async"]

        async def __async_search_all_sites_stream(self, **kwargs):
            items = await self.async_search_plugin_torrents(**kwargs)
            yield {"type": "append", "items": items, "text": "native append"}
            yield {"type": "done", "items": [], "text": "native done"}

    _install_search_chain_module(monkeypatch, SearchChain)
    plugin_module._SEARCH_BRIDGE.update(
        {"owner": None, "chain": None, "originals": {}, "mode": None}
    )
    native_sync_original = SearchChain.search_plugin_torrents
    native_async_original = SearchChain.async_search_plugin_torrents
    sync_original = SearchChain._SearchChain__search_all_sites
    async_original = SearchChain._SearchChain__async_search_all_sites
    stream_original = SearchChain._SearchChain__async_search_all_sites_stream
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

    def fake_search_torrents(**kwargs):
        plugin_search_calls.append(kwargs["keyword"])
        callback = kwargs["progress_callback"]
        callback(finished=1, total=2, text="LunaTV 正在搜索源 1/2")
        callback(finished=2, total=2, text="LunaTV 正在搜索源 2/2")
        return ["luna"]

    monkeypatch.setattr(plugin, "search_torrents", fake_search_torrents)
    try:
        wrapped_stream = SearchChain._SearchChain__async_search_all_sites_stream
        plugin.init_plugin({"enabled": True})
        assert SearchChain._SearchChain__async_search_all_sites_stream is wrapped_stream
        assert SearchChain.search_plugin_torrents is native_sync_original
        assert SearchChain.async_search_plugin_torrents is native_async_original
        assert SearchChain._SearchChain__search_all_sites is sync_original
        assert SearchChain._SearchChain__async_search_all_sites is async_original

        async def collect_stream():
            return [
                event
                async for event in SearchChain()._SearchChain__async_search_all_sites_stream(
                    keyword="demo",
                    page=3,
                )
            ]

        events = asyncio.run(collect_stream())
        assert native_calls == ["demo"]
        assert plugin_search_calls == ["demo"]
        assert [event["type"] for event in events] == [
            "progress",
            "progress",
            "append",
            "done",
        ]
        assert [
            (
                event["finished"],
                event["total"],
                event["value"],
                event["text"],
                event["stage"],
                event["items"],
                event["site"],
                event["site_id"],
                event["page"],
            )
            for event in events[:2]
        ] == [
            (1, 2, 50, "LunaTV 正在搜索源 1/2", "searching", [], "LunaTV", None, 3),
            (2, 2, 100, "LunaTV 正在搜索源 2/2", "searching", [], "LunaTV", None, 3),
        ]
        assert events[2] == {
            "type": "append",
            "items": ["luna"],
            "text": "native append",
        }
        assert events[3] == {"type": "done", "items": [], "text": "native done"}
    finally:
        plugin.init_plugin({"enabled": False})

    assert SearchChain.search_plugin_torrents is native_sync_original
    assert SearchChain.async_search_plugin_torrents is native_async_original
    assert SearchChain._SearchChain__search_all_sites is sync_original
    assert SearchChain._SearchChain__async_search_all_sites is async_original
    assert SearchChain._SearchChain__async_search_all_sites_stream is stream_original

def test_native_search_stream_progress_isolated_between_requests(monkeypatch):
    import asyncio

    rendezvous = threading.Barrier(2, timeout=1)
    plugin_search_calls = []

    class SearchChain:
        def search_plugin_torrents(self, **_kwargs):
            return []

        async def async_search_plugin_torrents(self, **kwargs):
            return await plugin.async_search_torrents(
                site={},
                keyword=kwargs["keyword"],
                page=kwargs.get("page", 0),
            )

        async def __async_search_all_sites_stream(self, **kwargs):
            items = await self.async_search_plugin_torrents(**kwargs)
            yield {"type": "append", "items": items, "text": kwargs["keyword"]}
            yield {"type": "done", "items": [], "text": kwargs["keyword"]}

    _install_search_chain_module(monkeypatch, SearchChain)
    plugin_module._SEARCH_BRIDGE.update(
        {"owner": None, "chain": None, "originals": {}, "mode": None}
    )
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

    def fake_search_torrents(**kwargs):
        keyword = kwargs["keyword"]
        plugin_search_calls.append(keyword)
        callback = kwargs["progress_callback"]
        callback(finished=1, total=2, text=f"{keyword} 1/2")
        rendezvous.wait()
        callback(finished=2, total=2, text=f"{keyword} 2/2")
        return [keyword]

    monkeypatch.setattr(plugin, "search_torrents", fake_search_torrents)
    try:
        async def collect(keyword):
            return [
                event
                async for event in SearchChain()._SearchChain__async_search_all_sites_stream(
                    keyword=keyword
                )
            ]

        async def collect_both():
            return await asyncio.gather(collect("first"), collect("second"))

        first, second = asyncio.run(collect_both())
    finally:
        plugin.init_plugin({"enabled": False})

    assert sorted(plugin_search_calls) == ["first", "second"]
    for keyword, events in (("first", first), ("second", second)):
        assert [event["type"] for event in events] == [
            "progress",
            "progress",
            "append",
            "done",
        ]
        assert [event["text"] for event in events[:2]] == [
            f"{keyword} 1/2",
            f"{keyword} 2/2",
        ]
        assert events[2]["items"] == [keyword]

def test_native_search_stream_discards_late_progress_after_cancellation(monkeypatch):
    import asyncio
    from threading import Event

    slow_started = Event()
    release_slow = Event()
    slow_finished = Event()

    class SearchChain:
        def search_plugin_torrents(self, **_kwargs):
            return []

        async def async_search_plugin_torrents(self, **kwargs):
            return await plugin.async_search_torrents(
                site={},
                keyword=kwargs["keyword"],
            )

        async def __async_search_all_sites_stream(self, **kwargs):
            items = await self.async_search_plugin_torrents(**kwargs)
            yield {"type": "append", "items": items}
            yield {"type": "done", "items": []}

    _install_search_chain_module(monkeypatch, SearchChain)
    plugin_module._SEARCH_BRIDGE.update(
        {"owner": None, "chain": None, "originals": {}, "mode": None}
    )
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})

    def fake_search_torrents(**kwargs):
        callback = kwargs["progress_callback"]
        callback(finished=1, total=2, text="LunaTV 正在搜索源 1/2")
        slow_started.set()
        release_slow.wait(1)
        callback(finished=2, total=2, text="LunaTV 正在搜索源 2/2")
        slow_finished.set()
        return ["luna"]

    monkeypatch.setattr(plugin, "search_torrents", fake_search_torrents)
    try:
        async def collect_until_cancelled():
            events = []

            async def consume():
                async for event in SearchChain()._SearchChain__async_search_all_sites_stream(
                    keyword="demo"
                ):
                    events.append(event)

            consumer = asyncio.create_task(consume())
            for _ in range(100):
                if slow_started.is_set() and events:
                    break
                await asyncio.sleep(0.01)
            assert [event["type"] for event in events] == ["progress"]
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass
            release_slow.set()
            assert await asyncio.to_thread(slow_finished.wait, 1)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return events

        events = asyncio.run(collect_until_cancelled())
    finally:
        release_slow.set()
        plugin.init_plugin({"enabled": False})

    assert [event["type"] for event in events] == ["progress"]
