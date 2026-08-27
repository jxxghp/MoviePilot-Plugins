from pathlib import Path

from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import AppleCmsClient, CmsSource
from app.plugins.lunatvsource.downloader import DownloadQueue
import app.plugins.lunatvsource.downloader as downloader_module


def test_discover_accepts_native_keyword_and_stops_after_first_source(monkeypatch):
    calls = []

    class Client:
        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return []

    plugin = object.__new__(LunaTVSource)
    plugin._enabled = True
    plugin._ai = type("Ai", (), {"normalize": lambda self, query, *args: (query, {})})()
    plugin._logger = type("Logger", (), {"warning": lambda *args: None})()
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    assert plugin.api_discover(keyword="示例电影") == {"success": True, "data": []}
    assert calls == [(
        "示例电影",
        {"limit": 30, "stop_after_first_source": True, "enrich": False},
    )]


def test_search_can_stop_after_first_source_with_results():
    client = AppleCmsClient([
        CmsSource(key="first", name="首选", api="https://first.example/vod"),
        CmsSource(key="second", name="备用", api="https://second.example/vod"),
    ])
    called = []

    def fake_request(source, **params):
        called.append(source.key)
        return {"list": [{
            "vod_id": source.key,
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_from": "在线播放",
            "vod_play_url": "正片$https://example.test/movie.m3u8",
        }]}

    client._request = fake_request
    assert [item.source_key for item in client.search(
        "示例电影", stop_after_first_source=True
    )] == ["first"]
    assert set(called) == {"first"}
