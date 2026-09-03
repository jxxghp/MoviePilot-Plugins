import threading
from pathlib import Path
from types import SimpleNamespace

from app.plugins.lunatvsource import LunaTVSource
import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource.cms import CmsSource, _result_from_item
from app.plugins.lunatvsource.downloader import DownloadQueue, DownloadTask


class _PluginData:
    def __init__(self):
        self.values = {}

    def get_data(self, _plugin_id, key):
        return self.values.get(key)

    def save(self, _plugin_id, key, value):
        self.values[key] = value


def _plugin(config=None):
    plugin = object.__new__(LunaTVSource)
    plugin.plugindata = _PluginData()
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
    plugin.init_plugin(config)
    return plugin


def test_api_search_collapses_tv_episode_rows_into_season_result(monkeypatch):
    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    rows = [
        _result_from_item(
            source,
            {
                "vod_id": f"episode-{episode}",
                "vod_name": f"示例剧 第{episode}集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": (
                    f"第{episode}集$https://video.example/s01e{episode:02d}.m3u8"
                ),
            },
        )
        for episode in (1, 2)
    ]

    class Client:
        def search(self, *_args, **_kwargs):
            return rows

    plugin = _plugin({"enabled": True, "ai_enabled": False})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})

    response = plugin.api_search({"query": "示例剧", "media_type": "tv"})

    assert response["success"] is True
    assert len(response["data"]) == 1
    assert response["data"][0]["title"].endswith("第1季")
    assert "集" not in response["data"][0]["title"]
    assert [item["episode"] for item in response["data"][0]["episodes"]] == [1, 2]


def test_record_completion_respects_disabled_moviepilot_organize(monkeypatch):
    plugin = _plugin({"enabled": True, "moviepilot_organize": False})
    calls = []

    monkeypatch.setattr(
        plugin,
        "_native_transfer",
        lambda *_args: calls.append("transfer") or "moviepilot",
    )
    monkeypatch.setattr(
        plugin,
        "_record_native_history",
        lambda _task, output: calls.append(("history", output)),
    )
    monkeypatch.setattr(plugin, "_sync_media_server", lambda: calls.append("sync"))

    plugin._record_completion(SimpleNamespace(), "/downloads/movie.mp4")

    assert calls == [("history", "/downloads/movie.mp4"), "sync"]


def test_queue_holds_slot_during_completion_callback(tmp_path: Path):
    data = {}
    callback_entered = threading.Event()
    release_callback = threading.Event()
    completed = []

    def load(key, default=None):
        return data.get(key, default)

    def save(key, value):
        data[key] = value

    def on_complete(task, _output):
        completed.append(task.episode)
        if task.episode == 1:
            callback_entered.set()
            assert release_callback.wait(timeout=2)

    queue = DownloadQueue(load, save, lambda *_args: None, on_complete=on_complete)
    for episode in (1, 2):
        assert queue.enqueue(
            DownloadTask(
                task_id=f"task-{episode}",
                source_key="demo",
                media_id="demo:series",
                title="示例剧",
                year="2026",
                media_type="tv",
                season=1,
                episode=episode,
                url=f"https://video.example/s01e{episode:02d}.m3u8",
                root=str(tmp_path),
            )
        )

    queue._execute = lambda task: str(tmp_path / f"episode-{task.episode}.mp4")
    first_result = []
    first_thread = threading.Thread(target=lambda: first_result.append(queue.run_one()))
    first_thread.start()

    assert callback_entered.wait(timeout=2)
    overlapping_result = queue.run_one()
    assert overlapping_result == {"processed": 0}

    release_callback.set()
    first_thread.join(timeout=2)
    assert not first_thread.is_alive()
    assert first_result[0]["state"] == "completed"

    assert queue.run_one()["state"] == "completed"
    assert completed == [1, 2]
