from pathlib import Path

from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import AppleCmsClient, CmsSource
from app.plugins.lunatvsource.downloader import DownloadQueue
import app.plugins.lunatvsource as plugin_module
import app.plugins.lunatvsource.downloader as downloader_module


def test_discover_accepts_native_keyword_and_stops_after_first_source(monkeypatch):
    calls = []

    class Client:
        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return []

    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    assert plugin.api_discover(keyword="示例电影") == {"success": True, "data": []}
    assert calls == [("示例电影", {"limit": 30, "stop_after_first_source": True})]


def test_discover_source_declares_native_search_field(monkeypatch):
    class DiscoverMediaSource:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    schemas = type("Schemas", (), {"DiscoverMediaSource": DiscoverMediaSource})
    monkeypatch.setattr(plugin_module, "_schemas", schemas)
    monkeypatch.setattr(plugin_module, "_HostMediaSource", type("MediaSource", (), {}))
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    event_data = type("EventData", (), {"extra_sources": []})()
    plugin._discover_source(type("Event", (), {"event_data": event_data})())
    source = event_data.extra_sources[0]
    assert source.filter_params == {"keyword": ""}
    assert source.filter_ui[0]["props"]["model"] == "keyword"


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


def test_ffmpeg_explicitly_sets_mp4_muxer_for_part_file(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(downloader_module.subprocess, "run", fake_run)
    DownloadQueue._run_ffmpeg(
        "ffmpeg", "https://example.test/video.m3u8", tmp_path / "movie.mp4.part"
    )
    command = captured["command"]
    assert command[command.index("-f") + 1] == "mp4"
