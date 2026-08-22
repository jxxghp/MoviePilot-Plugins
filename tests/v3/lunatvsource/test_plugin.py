from app.plugins.lunatvsource import LunaTVSource
import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource.cms import CmsSource, _result_from_item
from pathlib import Path


def test_status_exposes_serial_queue_and_ai_fallback():
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "ai_enabled": False})
    status = plugin.api_status()["data"]
    assert status["enabled"] is True
    assert status["queue"]["pending"] == 0
    assert status["ai"]["enabled"] is True
    assert status["ai"]["available"] is False
    assert status["media_source"] == "lunatv"
    assert plugin.get_sidebar_nav() == []


def test_manual_download_rejects_non_http_url():
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "download_root": "/tmp/lunatv-test"})
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
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "use_moviepilot_dirs": False})
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
    plugin = LunaTVSource()
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
    plugin = LunaTVSource()
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


def test_host_meta_info_uses_v3_function_signature(monkeypatch):
    calls = []

    def meta_info(*, title):
        calls.append(title)
        return type("Meta", (), {"type": "电影"})()

    monkeypatch.setattr(plugin_module, "_HostMetaInfo", meta_info)
    plugin = LunaTVSource()
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

    plugin = LunaTVSource()
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

    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(plugin, "_media_info", lambda result, association: result)
    meta = type("Meta", (), {"name": "示例电影", "year": "", "type": "电影"})()
    results = plugin.search_medias(meta=meta)
    assert len(results) == 1
    assert results[0].title == "示例电影"
    assert plugin.get_media_source() == []


def test_global_media_search_respects_explicit_other_source():
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    meta = type("Meta", (), {"name": "示例电影"})()
    assert plugin.search_medias(meta=meta, media_source=("themoviedb",)) == []


def test_native_resource_search_returns_marked_download_items(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

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

    monkeypatch.setattr(plugin_module, "_schemas", type("Schemas", (), {"TorrentInfo": TorrentInfo}))
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    items = plugin.search_torrents(site={"id": 1}, keyword="示例剧", page=0)
    assert len(items) == 1
    assert items[0].site_name == "LunaTV"
    assert items[0].title.endswith("S01E01")
    assert plugin._decode_resource_token(items[0].enclosure)["url"].endswith("01.m3u8")


def test_native_download_is_enqueued_into_serial_queue(tmp_path: Path):
    plugin = LunaTVSource()
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
    result = plugin.download(token, tmp_path)
    assert result[0] == "LunaTVSource"
    assert result[1]
    tasks = plugin._queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["url"] == "https://example.test/movie.m3u8"
    assert tasks[0]["root"] == str(tmp_path)


def test_native_download_reports_duplicate_instead_of_fake_success(tmp_path: Path):
    plugin = LunaTVSource()
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
