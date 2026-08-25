from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource.cms import AppleCmsClient, CmsSource
from tests.v3.lunatvsource.test_plugin import _plugin


def test_api_search_expands_episode_rows_for_downloadable_results(monkeypatch):
    calls = []

    class Client:
        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return []

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())

    response = plugin.api_search({"query": "示例剧"})

    assert response == {"success": True, "data": []}
    assert calls and calls[0][1]["expand_tv_episode_rows"] is True


def test_api_download_enqueues_lunatv_season_token_once(monkeypatch, tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    wakeups = []
    monkeypatch.setattr(plugin, "_start_queue", lambda: wakeups.append(True))
    monkeypatch.setattr(
        plugin,
        "_client",
        lambda: (_ for _ in ()).throw(AssertionError("API download must not search CMS")),
    )
    token = plugin._resource_token(
        {
            "url": "https://example.test/s01e01.m3u8",
            "title": "小猪佩奇",
            "year": "2004",
            "media_type": "tv",
            "season": 1,
            "episode": 1,
            "media_id": "demo:42",
            "source_key": "demo",
            "episodes": [
                {
                    "url": "https://example.test/s01e01.m3u8",
                    "season": 1,
                    "episode": 1,
                },
                {
                    "url": "https://example.test/s01e02.m3u8",
                    "season": 1,
                    "episode": 2,
                },
            ],
        }
    )

    first = plugin.api_download({"content": token})
    duplicate = plugin.api_download({"enclosure": token})

    assert first["success"] is True
    assert first["data"]["task_id"]
    assert "已排队 2 集" in first["message"]
    assert duplicate["success"] is False
    assert duplicate["data"]["task_id"] is None
    assert [(task["season"], task["episode"], task["url"])
            for task in sorted(plugin._queue.list_tasks(), key=lambda item: item["episode"])] == [
        (1, 1, "https://example.test/s01e01.m3u8"),
        (1, 2, "https://example.test/s01e02.m3u8"),
    ]
    assert wakeups == [True]


def test_tmdb_cache_persists_newer_same_key_snapshot_after_race(monkeypatch):
    """The snapshot that is written last must not be older than the cache."""

    plugin = _plugin()
    plugin._tmdb_cache = {}
    first_lock_exit = threading.Event()
    new_snapshot_saved = threading.Event()
    writes = {}
    thread_errors = []

    class FirstExitWaitsForNewSnapshot:
        """Let the old implementation expose its post-lock save window.

        The first cache mutation releases this lock before it may continue to
        ``save_data``.  A second mutation then persists a newer snapshot.  If
        saving occurs outside the cache lock, the first mutation overwrites it
        afterwards; with the save inside the lock, the newer snapshot is last.
        """

        def __init__(self):
            self._lock = threading.RLock()
            self._exit_lock = threading.Lock()
            self._exit_count = 0

        def __enter__(self):
            self._lock.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            with self._exit_lock:
                first_exit = self._exit_count == 0
                self._exit_count += 1
            self._lock.release()
            if first_exit:
                first_lock_exit.set()
                if not new_snapshot_saved.wait(timeout=2):
                    raise AssertionError("newer TMDB cache snapshot was not saved")
            return False

    def save_data(key, snapshot):
        marker = snapshot["same-key"]["marker"]
        writes[key] = dict(snapshot)
        if marker == "new":
            new_snapshot_saved.set()

    def store(marker):
        try:
            plugin._store_tmdb_cache_entry(
                "same-key", {"status": "matched", "marker": marker}
            )
        except BaseException as error:
            thread_errors.append(error)

    monkeypatch.setattr(plugin, "_tmdb_cache_lock", FirstExitWaitsForNewSnapshot())
    monkeypatch.setattr(plugin, "save_data", save_data)

    old_thread = threading.Thread(target=store, args=("old",), daemon=True)
    old_thread.start()
    assert first_lock_exit.wait(timeout=2)

    new_thread = threading.Thread(target=store, args=("new",), daemon=True)
    new_thread.start()
    assert new_snapshot_saved.wait(timeout=2)
    old_thread.join(timeout=2)
    new_thread.join(timeout=2)

    assert not old_thread.is_alive()
    assert not new_thread.is_alive()
    assert thread_errors == []
    assert writes["tmdb_match_cache_v1"]["same-key"]["marker"] == "new"


def test_tmdb_cache_lock_recovers_after_save_data_error(monkeypatch):
    plugin = _plugin()
    plugin._tmdb_cache = {}
    calls = 0
    writes = {}

    def save_data(key, snapshot):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("persistent store unavailable")
        writes[key] = dict(snapshot)

    monkeypatch.setattr(plugin, "save_data", save_data)

    with pytest.raises(RuntimeError, match="persistent store unavailable"):
        plugin._store_tmdb_cache_entry(
            "same-key", {"status": "matched", "marker": "failed"}
        )

    completed = threading.Event()
    thread_errors = []

    def store_after_failure():
        try:
            plugin._store_tmdb_cache_entry(
                "same-key", {"status": "matched", "marker": "recovered"}
            )
        except BaseException as error:
            thread_errors.append(error)
        finally:
            completed.set()

    recovery_thread = threading.Thread(target=store_after_failure, daemon=True)
    recovery_thread.start()
    assert completed.wait(timeout=2)
    recovery_thread.join(timeout=2)

    assert not recovery_thread.is_alive()
    assert thread_errors == []
    assert writes["tmdb_match_cache_v1"]["same-key"]["marker"] == "recovered"


def test_resource_torrents_expands_limit_for_each_configured_source(monkeypatch):
    calls = []

    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Client:
        sources = [object() for _ in range(65)]

        def search(self, *_args, **kwargs):
            calls.append(kwargs)
            return []

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())

    assert plugin._resource_torrents("长剧") == []
    assert calls and calls[0]["source_limit"] == 3
    assert calls[0]["limit"] == 65 * 3


def test_native_download_uses_explicit_episodes_without_valid_top_level_url(
    monkeypatch, tmp_path: Path
):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    wakeups = []
    monkeypatch.setattr(plugin, "_start_queue", lambda: wakeups.append(True))
    token = plugin._resource_token(
        {
            "url": "file:///tmp/not-a-stream.m3u8",
            "title": "示例剧",
            "media_type": "tv",
        }
    )

    result = plugin.download(
        token,
        tmp_path,
        episodes=[
            None,
            {"url": "file:///tmp/not-an-http-stream.m3u8", "season": 1, "episode": 1},
            {"url": "https://example.test/s01e02.m3u8", "season": 1, "episode": 2},
        ],
    )

    assert result[1]
    assert "2 集参数无效" in result[3]
    assert [task["url"] for task in plugin._queue.list_tasks()] == [
        "https://example.test/s01e02.m3u8"
    ]
    assert wakeups == [True]


def test_refresh_plugin_season_subscription_expands_52_cms_episode_rows(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-demo", "演示源", "https://cms.example/vod")
    client = AppleCmsClient([source])
    pages = []

    def fake_request(_source, **params):
        assert params.get("ac") == "list"
        page = int(params["pg"])
        pages.append(page)
        first = (page - 1) * 20 + 1
        last = min(first + 20, 53)
        return {
            "pagecount": "3",
            "list": [
                {
                    "vod_id": f"episode-{episode}",
                    "vod_name": f"示例剧 S01E{episode:03d}",
                    "vod_year": "2026",
                    "type_name": "电视剧",
                    "vod_play_url": (
                        f"第{episode}集$https://example.test/s01e{episode:03d}.m3u8"
                    ),
                }
                for episode in range(first, last)
            ],
        }

    client._request = fake_request
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

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(plugin, "_client", lambda: client)
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))

    response = plugin.refresh_subscriptions()
    tasks = sorted(plugin._queue.list_tasks(), key=lambda task: task["episode"])

    assert pages == [1, 2, 3]
    assert response["queued"] == 52
    assert [(task["season"], task["episode"]) for task in tasks] == [
        (1, episode) for episode in range(1, 53)
    ]
