import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import CmsEpisode, CmsResult, CmsSource, _result_from_item
from app.plugins.lunatvsource.downloader import DownloadQueue, DownloadTask
from app.plugins.lunatvsource.m3u8_engine import M3U8EngineInstallError
from app.plugins.lunatvsource.naming import media_path


class PluginData:
    def __init__(self):
        self.values = {}

    def get_data(self, _plugin_id, key):
        return self.values.get(key)

    def save(self, _plugin_id, key, value):
        self.values[key] = value


def _plugin(config=None):
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
    plugin.init_plugin(config or {})
    return plugin


def _install_subscription_operator(monkeypatch, subscribe):
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


def _episode_row(source: CmsSource, episode: int):
    return _result_from_item(
        source,
        {
            "vod_id": f"episode-{episode}",
            "vod_name": f"追更示例 第一季 第{episode}集",
            "vod_year": "2026",
            "type_name": "电视剧",
            "vod_play_url": (
                f"第{episode}集$https://example.test/s01e{episode:02d}.m3u8"
            ),
        },
    )


def test_subscription_drops_source_disabled_before_enqueue(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-race", "并发源", "https://cms.example/vod")
    result = _episode_row(source, 1)
    subscribe = SimpleNamespace(
        state="R",
        name="追更示例",
        year="2026",
        type="电视剧",
        season=1,
        media_source="",
        media_id="",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    plugin.save_data(plugin_module.SOURCE_CACHE_KEY, [source.to_dict()])
    with plugin._source_health_lock:
        plugin._source_health[source.key] = {
            "api": source.api,
            "health_status": "healthy",
            "last_checked": 1.0,
        }
        plugin._source_health_revision += 1
        initial_revision = plugin._source_health_revision

    class Client:
        _lunatv_health_revision = initial_revision

        @staticmethod
        def search(_query, **_kwargs):
            return [result]

    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda item: (item, {}))
    monkeypatch.setattr(plugin, "_native_history_has_episode", lambda _task: False)

    def disable_before_enqueue(_task):
        response = plugin.api_source_state(
            {"source_key": source.key, "enabled": False}
        )
        assert response["success"] is True
        return None

    monkeypatch.setattr(plugin, "_local_episode_path", disable_before_enqueue)

    response = plugin.refresh_subscriptions()

    assert response["queued"] == 0
    assert plugin._queue.list_tasks() == []
    assert plugin.api_sources()["data"][0]["manual_disabled"] is True


def test_subscription_skips_source_disabled_before_search(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-disabled", "禁用源", "https://cms.example/disabled")
    subscribe = SimpleNamespace(
        state="R",
        name="追更示例",
        year="2026",
        type="电视剧",
        season=1,
        media_source="",
        media_id="",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    plugin.save_data(plugin_module.SOURCE_CACHE_KEY, [source.to_dict()])
    with plugin._source_health_lock:
        plugin._source_health[source.key] = {
            "api": source.api,
            "health_status": "failed",
            "last_checked": 1.0,
            "failures": 1,
        }

    class Client:
        @staticmethod
        def search(*_args, **_kwargs):
            raise AssertionError("disabled source must not be searched")

    monkeypatch.setattr(plugin, "_client", lambda: Client())

    response = plugin.refresh_subscriptions()

    assert response["queued"] == 0
    assert plugin._queue.list_tasks() == []


def test_unfinished_subscription_queues_only_new_episode_when_result_order_changes(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-demo", "演示源", "https://cms.example/vod")
    first = _episode_row(source, 1)
    second = _episode_row(source, 2)
    rows = [first]
    subscribe = SimpleNamespace(
        state="R",
        name="追更示例",
        year="2026",
        type=SimpleNamespace(value="TV"),
        season=1,
        media_source="lunatv",
        media_id="cms-demo:episode-1",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        def search(self, _query, **_kwargs):
            return list(rows)

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(
        plugin,
        "_native_history_has_episode",
        lambda task: task.episode == 1,
    )

    assert plugin.refresh_subscriptions()["queued"] == 0
    rows[:] = [second, first]
    assert plugin.refresh_subscriptions()["queued"] == 1
    tasks = sorted(plugin._queue.list_tasks(), key=lambda item: item["episode"])
    assert [(task["episode"], task["state"]) for task in tasks] == [
        (1, "completed"),
        (2, "pending"),
    ]
    torrents = plugin.list_torrents()
    assert len(torrents) == 1
    assert "共2集" in str(getattr(torrents[0], "title", ""))
    assert "已下载1/2" in str(getattr(torrents[0], "season_episode", ""))

    # CMS result ordering is not stable. A later refresh must still recognize
    # the pending episode as the same subscription item.
    rows[:] = [first, second]
    assert plugin.refresh_subscriptions()["queued"] == 0
    assert sorted(task["episode"] for task in plugin._queue.list_tasks()) == [1, 2]


def test_subscription_refresh_normalizes_active_state_and_season_text(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-demo", "演示源", "https://cms.example/vod")
    subscribe = SimpleNamespace(
        state=" p ",
        name="追更示例",
        year="2026",
        type="电视剧",
        season="S01",
        media_source="lunatv",
        media_id="cms-demo:season-1",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        def search(self, _query, **_kwargs):
            return [_episode_row(source, 1)]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(plugin, "_native_history_has_episode", lambda _task: False)

    assert plugin.refresh_subscriptions()["queued"] == 1
    task = plugin._queue.list_tasks()[0]
    assert task["season"] == 1
    assert task["episode"] == 1


def test_failed_subscription_refresh_reuses_identity_and_updates_stream(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_args: None)
    failed = DownloadTask(
        task_id="failed-old",
        source_key="cms-demo",
        media_id="cms-demo:series",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=3,
        url="https://example.test/old-s01e03.m3u8",
        root=str(tmp_path),
        host_media_source="themoviedb",
        host_media_id="1234",
        state="failed",
        error="temporary source failure",
        progress=0.6,
        downloaded_bytes=123,
    )
    data[queue.DATA_KEY] = [failed.to_dict()]
    replacement = DownloadTask(
        task_id="new-random-id",
        source_key="cms-demo",
        media_id="cms-demo:new-row-id",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=3,
        url="https://example.test/new-s01e03.m3u8",
        root=str(tmp_path),
        host_media_source="themoviedb",
        host_media_id="1234",
    )

    assert queue.enqueue(replacement) is True
    tasks = queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "failed-old"
    assert tasks[0]["state"] == "pending"
    assert tasks[0]["url"] == replacement.url
    assert tasks[0]["error"] == ""
    assert tasks[0]["progress"] == 0.0
    assert tasks[0]["downloaded_bytes"] == 0


def test_tv_season_projection_keeps_completed_size_and_shows_finalizing(
    monkeypatch, tmp_path: Path
):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)

    tasks = []
    for episode, state, progress in ((1, "completed", 1.0), (2, "running", 0.99)):
        task = DownloadTask(
            task_id=f"episode-{episode}",
            source_key="cms-demo",
            media_id="cms-demo:series",
            title="追更示例",
            year="2026",
            media_type="tv",
            season=1,
            episode=episode,
            url=f"https://example.test/s01e{episode:02d}.m3u8",
            root=str(tmp_path),
            state=state,
            progress=progress,
            download_engine="N_m3u8DL-RE",
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
        output = tmp_path / relative_dir / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        if state == "completed":
            output.write_bytes(b"c" * 1000)
            task.output = str(output)
        else:
            Path(f"{output}.part").write_bytes(b"r" * 990)
        tasks.append(task)

    plugin.save_data(plugin._queue.DATA_KEY, [task.to_dict() for task in tasks])
    torrents = plugin.list_torrents()

    assert len(torrents) == 1
    torrent = torrents[0]
    assert torrent.size == pytest.approx(2000.0)
    assert torrent.progress == 99.0
    assert torrent.upspeed in {None, ""}
    assert torrent.left_time == "已下载 1/2 集 · 正在整理第 2/2 集"


def test_queue_persists_completed_size_before_native_move(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_args: None)
    task = DownloadTask(
        task_id="completed-size",
        source_key="cms-demo",
        media_id="cms-demo:series",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=1,
        url="https://example.test/s01e01.m3u8",
        root=str(tmp_path),
    )
    data[queue.DATA_KEY] = [task.to_dict()]
    output = tmp_path / "episode.mp4"
    output.write_bytes(b"x" * 1234)

    queue._persist_state_transition(task, "completed", output=str(output))

    persisted = queue.list_tasks()[0]
    assert persisted["downloaded_bytes"] == 1234


def test_tv_projection_uses_persisted_completed_size_after_restart(
    monkeypatch, tmp_path: Path
):
    completed = DownloadTask(
        task_id="completed-before-restart",
        source_key="cms-demo",
        media_id="cms-demo:series",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=1,
        url="https://example.test/s01e01.m3u8",
        root=str(tmp_path),
        state="completed",
        progress=1.0,
        output=str(tmp_path / "already-moved.mp4"),
        downloaded_bytes=1000,
    )
    active = DownloadTask(
        task_id="active-after-restart",
        source_key="cms-demo",
        media_id="cms-demo:series",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=2,
        url="https://example.test/s01e02.m3u8",
        root=str(tmp_path),
        state="running",
        progress=0.5,
        download_engine="N_m3u8DL-RE",
    )
    relative_dir, filename = media_path(
        active.root,
        active.title,
        active.year,
        active.media_type,
        active.season,
        active.episode,
        active.url,
        active.mode,
    )
    partial = Path(f"{tmp_path / relative_dir / filename}.part")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"r" * 500)

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    plugin.save_data(
        plugin._queue.DATA_KEY,
        [completed.to_dict(), active.to_dict()],
    )

    torrents = plugin.list_torrents()
    assert len(torrents) == 1
    assert torrents[0].size == pytest.approx(2000.0)


def test_record_completion_removes_empty_download_tree_after_native_move(
    monkeypatch, tmp_path: Path
):
    root = tmp_path / "incoming"
    task = DownloadTask(
        task_id="organized-episode",
        source_key="cms-demo",
        media_id="cms-demo:series",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=1,
        url="https://example.test/s01e01.m3u8",
        root=str(root),
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
    output = root / relative_dir / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"downloaded")

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(root)})

    def move_with_moviepilot(_task, original):
        Path(original).unlink()
        return "moviepilot"

    monkeypatch.setattr(plugin, "_native_transfer", move_with_moviepilot)
    monkeypatch.setattr(plugin, "_record_native_history", lambda *_args: None)
    monkeypatch.setattr(plugin, "_sync_media_server", lambda: True)

    plugin._record_completion(task, str(output))

    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_last_tv_episode_remains_visible_while_completion_hook_is_organizing(
    monkeypatch, tmp_path: Path
):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    task = DownloadTask(
        task_id="finalizing-episode",
        source_key="cms-demo",
        media_id="cms-demo:series",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=4,
        url="https://example.test/s01e04.m3u8",
        root=str(tmp_path),
    )
    callback_started = threading.Event()
    release_callback = threading.Event()

    def execute(_task):
        output = tmp_path / "追更示例 (2026)" / "Season 01" / "追更示例 (2026) - S01E04.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"completed")
        return str(output)

    def organize(_task, _output):
        callback_started.set()
        assert release_callback.wait(timeout=2)

    monkeypatch.setattr(plugin._queue, "_execute", execute)
    plugin._queue._on_complete = organize
    assert plugin._queue.enqueue(task) is True
    assert plugin._queue.wake() is True
    assert callback_started.wait(timeout=2)

    torrents = plugin.list_torrents()
    assert len(torrents) == 1
    assert torrents[0].progress == 99.0
    assert torrents[0].season_episode == "第1季 · 共1集 · 已下载0/1"
    assert torrents[0].left_time == "已下载 0/1 集 · 正在整理第 1/1 集"

    release_callback.set()
    assert plugin._queue.wait_until_idle(timeout=2)
    assert plugin.list_torrents() == []


def test_subscription_refresh_rejects_mismatched_host_identity_before_ranking(
    monkeypatch, tmp_path: Path
):
    def season_result(source_key: str, title: str, episode_count: int) -> CmsResult:
        return CmsResult(
            source_key=source_key,
            source_name=f"{source_key}源",
            vod_id=f"{source_key}-series",
            title=title,
            year="2026",
            media_type="tv",
            remark="",
            episodes=tuple(
                CmsEpisode(
                    1,
                    episode,
                    f"第{episode}集",
                    f"https://{source_key}.example/s01e{episode:02d}.m3u8",
                )
                for episode in range(1, episode_count + 1)
            ),
            season_range=(1, 1),
            season_ambiguous=False,
        )

    wrong = season_result("wrong", "目标剧 外传", 4)
    correct = season_result("correct", "Target Show", 2)
    subscribe = SimpleNamespace(
        state="R",
        name="目标剧",
        year="2026",
        type=SimpleNamespace(value="TV"),
        season=1,
        media_source="themoviedb",
        media_id="100",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        @staticmethod
        def search(_query, **_kwargs):
            return [wrong, correct]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(plugin, "_probe_resource_urls", lambda urls: {url: 1080 for url in urls})
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda result: (
            result,
            {
                "status": "matched",
                "media_source": "themoviedb",
                "media_id": "100" if result.source_key == "correct" else "200",
                "title": result.title,
                "year": result.year,
            },
        ),
    )

    response = plugin.refresh_subscriptions()
    tasks = plugin._queue.list_tasks()

    assert response["queued"] == 2
    assert sorted(task["episode"] for task in tasks) == [1, 2]
    assert all("correct.example" in task["url"] for task in tasks)


def test_subscription_refresh_falls_back_to_exact_title_and_year_when_unmatched(
    monkeypatch, tmp_path: Path
):
    def season_result(source_key: str, title: str, year: str, count: int) -> CmsResult:
        return CmsResult(
            source_key=source_key,
            source_name=f"{source_key}源",
            vod_id=f"{source_key}-series",
            title=title,
            year=year,
            media_type="tv",
            remark="",
            episodes=tuple(
                CmsEpisode(
                    1,
                    episode,
                    f"第{episode}集",
                    f"https://{source_key}.example/s01e{episode:02d}.m3u8",
                )
                for episode in range(1, count + 1)
            ),
            season_range=(1, 1),
            season_ambiguous=False,
        )

    wrong = season_result("wrong", "同名剧", "2025", 4)
    correct = season_result("correct", "同名剧 第一季", "2026", 2)
    subscribe = SimpleNamespace(
        state="P",
        name="同名剧",
        year="2026",
        type="电视剧",
        season="S01",
        media_source="lunatv",
        media_id="missing:series",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        @staticmethod
        def search(_query, **_kwargs):
            return [wrong, correct]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(plugin, "_probe_resource_urls", lambda urls: {url: 1080 for url in urls})
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {"status": "unmatched"}))

    response = plugin.refresh_subscriptions()
    tasks = plugin._queue.list_tasks()

    assert response["queued"] == 2
    assert sorted(task["episode"] for task in tasks) == [1, 2]
    assert all("correct.example" in task["url"] for task in tasks)


def test_subscription_refresh_honors_native_start_and_manual_total_episode(
    monkeypatch, tmp_path: Path
):
    result = CmsResult(
        source_key="cms-demo",
        source_name="演示源",
        vod_id="bounded-series",
        title="边界示例",
        year="2026",
        media_type="tv",
        remark="",
        episodes=tuple(
            CmsEpisode(
                1,
                episode,
                f"第{episode}集",
                f"https://example.test/s01e{episode:02d}.m3u8",
            )
            for episode in range(1, 7)
        ),
        season_range=(1, 1),
        season_ambiguous=False,
    )
    subscribe = SimpleNamespace(
        state="R",
        name="边界示例",
        year="2026",
        type="电视剧",
        season=1,
        start_episode=3,
        total_episode=4,
        manual_total_episode=True,
        media_source="",
        media_id="300",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        @staticmethod
        def search(_query, **_kwargs):
            return [result]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    assert plugin._subscription_episode_bounds(
        SimpleNamespace(
            start_episode=2,
            total_episode=4,
            manual_total_episode=False,
        ),
        {"season_counts": {"1": 6}},
        1,
    ) == (2, 6)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda item: (
            item,
            {
                "status": "matched",
                "media_source": "themoviedb",
                "media_id": "300",
                "season_counts": {1: 6},
            },
        ),
    )

    response = plugin.refresh_subscriptions()
    tasks = plugin._queue.list_tasks()

    assert response["queued"] == 2
    assert sorted(task["episode"] for task in tasks) == [3, 4]


def test_subscription_ranking_ignores_episodes_outside_manual_bounds(
    monkeypatch, tmp_path: Path
):
    def result(source_key: str, episodes: tuple[int, ...]) -> CmsResult:
        return CmsResult(
            source_key=source_key,
            source_name=f"{source_key}源",
            vod_id=f"{source_key}-series",
            title="边界选源",
            year="2026",
            media_type="tv",
            remark="",
            episodes=tuple(
                CmsEpisode(
                    1,
                    episode,
                    f"第{episode}集",
                    f"https://{source_key}.example/s01e{episode:02d}.m3u8",
                )
                for episode in episodes
            ),
            season_range=(1, 1),
            season_ambiguous=False,
        )

    future = result("future", (5, 6))
    valid = result("valid", (3, 4))
    subscribe = SimpleNamespace(
        state="R",
        name="边界选源",
        year="2026",
        type="电视剧",
        season=1,
        start_episode=3,
        total_episode=4,
        manual_total_episode=True,
        media_source="themoviedb",
        media_id="400",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        @staticmethod
        def search(_query, **_kwargs):
            return [future, valid]

    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda item: (
            item,
            {
                "status": "matched",
                "media_source": "themoviedb",
                "media_id": "400",
            },
        ),
    )

    response = plugin.refresh_subscriptions()
    tasks = plugin._queue.list_tasks()

    assert response["queued"] == 2
    assert sorted(task["episode"] for task in tasks) == [3, 4]
    assert all("valid.example" in task["url"] for task in tasks)


def test_tv_projection_groups_changed_cms_rows_by_host_media_identity(tmp_path: Path):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    tasks = [
        DownloadTask(
            task_id=f"row-{episode}",
            source_key="cms-demo",
            media_id=f"cms-demo:episode-{episode}",
            title="追更示例",
            year="2026",
            media_type="tv",
            season=1,
            episode=episode,
            url=f"https://example.test/s01e{episode:02d}.m3u8",
            root=str(tmp_path),
            host_media_source="themoviedb",
            host_media_id="1234",
        )
        for episode in (2, 3)
    ]
    plugin.save_data(plugin._queue.DATA_KEY, [task.to_dict() for task in tasks])

    torrents = plugin.list_torrents()

    assert len(torrents) == 1
    assert torrents[0].title == "追更示例 第1季（共2集）"


def test_completion_records_history_when_transfer_raises_after_move(
    monkeypatch, tmp_path: Path
):
    root = tmp_path / "incoming"
    task = DownloadTask(
        task_id="partial-transfer",
        source_key="cms-demo",
        media_id="cms-demo:series",
        title="追更示例",
        year="2026",
        media_type="tv",
        season=1,
        episode=5,
        url="https://example.test/s01e05.m3u8",
        root=str(root),
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
    output = root / relative_dir / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"downloaded")
    recorded = []

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(root)})

    def partial_move(_task, original):
        Path(original).unlink()
        raise RuntimeError("host response lost after move")

    monkeypatch.setattr(plugin, "_native_transfer", partial_move)
    monkeypatch.setattr(
        plugin,
        "_record_native_history",
        lambda _task, original: recorded.append(original),
    )
    monkeypatch.setattr(plugin, "_sync_media_server", lambda: True)

    plugin._record_completion(task, str(output))

    assert recorded == [str(output)]
    assert list(root.iterdir()) == []


def test_subscription_source_ranking_prefers_newest_episode_before_resolution(
    monkeypatch,
):
    high_but_stale = CmsResult(
        source_key="high-stale",
        source_name="高清但较慢",
        vod_id="stale",
        title="追更示例",
        year="2026",
        media_type="tv",
        remark="",
        episodes=tuple(
            CmsEpisode(
                1,
                episode,
                f"第{episode}集",
                f"https://high.example/1080-e{episode}.m3u8",
            )
            for episode in (1, 2)
        ),
        season_range=(1, 1),
        season_ambiguous=False,
    )
    current_but_lower = CmsResult(
        source_key="current-lower",
        source_name="更新更快",
        vod_id="current",
        title="追更示例",
        year="2026",
        media_type="tv",
        remark="",
        episodes=tuple(
            CmsEpisode(
                1,
                episode,
                f"第{episode}集",
                f"https://current.example/720-e{episode}.m3u8",
            )
            for episode in (1, 2, 3)
        ),
        season_range=(1, 1),
        season_ambiguous=False,
    )
    plugin = _plugin()
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {
            url: 1080 if "high.example" in url else 720 for url in urls
        },
    )

    ranked = plugin._rank_subscription_results(
        [(high_but_stale, {}), (current_but_lower, {})],
        season=1,
    )

    assert ranked[0][0].source_key == "current-lower"


def test_subscription_source_ranking_uses_requested_season_resolution(monkeypatch):
    def multi_season_result(source_key: str, season_two_height: int) -> CmsResult:
        return CmsResult(
            source_key=source_key,
            source_name=source_key,
            vod_id=source_key,
            title="追更示例",
            year="2026",
            media_type="tv",
            remark="",
            episodes=(
                CmsEpisode(
                    1,
                    1,
                    "第一季第1集",
                    f"https://{source_key}.example/s01e01.m3u8",
                ),
                CmsEpisode(
                    2,
                    1,
                    "第二季第1集",
                    f"https://{source_key}.example/{season_two_height}p-s02e01.m3u8",
                ),
            ),
            season_range=(1, 2),
            season_ambiguous=False,
        )

    low = multi_season_result("low", 720)
    high = multi_season_result("high", 1080)
    plugin = _plugin()
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {url: 1080 if "1080p" in url else 720 for url in urls},
    )

    ranked = plugin._rank_subscription_results(
        [(low, {}), (high, {})],
        season=2,
    )

    assert ranked[0][0].source_key == "high"


def test_engine_status_and_install_failure_are_actionable(monkeypatch, tmp_path: Path):
    queue = DownloadQueue(
        lambda *_args: [],
        lambda *_args: None,
        lambda *_args: None,
        data_path=tmp_path / "plugin-data",
    )
    status = queue.engine_status()
    assert status["name"] == "N_m3u8DL-RE"
    assert status["supported"] is True
    assert status["ready"] is False
    assert status["install_source"] == "插件内置官方固定版本（缺失时 GitHub）"

    playlist = tmp_path / "input.m3u8"
    playlist.write_text("#EXTM3U\n", encoding="utf-8")

    class OfflineEngine:
        def download(self, *_args, **_kwargs):
            raise M3U8EngineInstallError("release download failed")

        @staticmethod
        def cleanup_task(*_args, **_kwargs):
            return None

    queue._m3u8_engines = (OfflineEngine(),)
    monkeypatch.setattr(
        queue,
        "_prepare_hls_input",
        lambda *_args, **_kwargs: str(playlist),
    )
    task = DownloadTask(
        task_id="offline-engine",
        source_key="cms-demo",
        media_id="cms-demo:movie",
        title="离线安装示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(tmp_path / "incoming"),
    )

    with pytest.raises(RuntimeError, match="GitHub Release"):
        queue._execute(task)


def test_status_reports_real_concurrency_engine_and_followup_interval(monkeypatch):
    plugin = _plugin()
    plugin.init_plugin(
        {
            "enabled": True,
            "poll_minutes": 20,
            "max_concurrent_tasks": 3,
            "segment_thread_count": 16,
        }
    )
    engine = {
        "name": "N_m3u8DL-RE",
        "version": "0.5.1-beta",
        "supported": True,
        "ready": True,
        "install_source": "插件内置官方固定版本（缺失时 GitHub）",
        "managed_path": "/config/plugins/LunaTVSource/bin/N_m3u8DL-RE",
    }
    monkeypatch.setattr(plugin._queue, "engine_status", lambda: engine)

    status = plugin.api_status()["data"]

    assert status["download_settings"] == {
        "max_concurrent_tasks": 3,
        "segment_thread_count": 16,
    }
    assert status["engine"] == engine
    assert status["subscription"]["refresh_minutes"] == 20


def test_native_tmdb_season_subscription_queues_all_new_episode_rows(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("cms-demo", "演示源", "https://cms.example/vod")
    rows = [_episode_row(source, episode) for episode in (1, 2, 3)]
    subscribe = SimpleNamespace(
        state="R",
        name="追更示例",
        year="2026",
        type="电视剧",
        season=1,
        media_source="themoviedb",
        media_id="1234",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        def search(self, _query, **_kwargs):
            return rows

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(
        plugin,
        "_prepare_result",
        lambda result: (
            result,
            {
                "status": "matched",
                "media_source": "themoviedb",
                "media_id": "1234",
                "title": "追更示例",
            },
        ),
    )
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(
        plugin,
        "_native_history_has_episode",
        lambda task: task.episode == 1,
    )

    response = plugin.refresh_subscriptions()
    tasks = sorted(plugin._queue.list_tasks(), key=lambda item: item["episode"])

    assert response["queued"] == 2
    assert [(task["episode"], task["state"]) for task in tasks] == [
        (1, "completed"),
        (2, "pending"),
        (3, "pending"),
    ]
    torrents = plugin.list_torrents()
    assert len(torrents) == 1
    assert "共3集" in str(getattr(torrents[0], "title", ""))
    assert "已下载1/3" in str(getattr(torrents[0], "season_episode", ""))
    assert plugin.refresh_subscriptions()["queued"] == 0


def test_default_subscription_dedupes_pending_episodes_when_best_source_changes(
    monkeypatch, tmp_path: Path
):
    def season_result(source_key, source_name, host, episodes):
        return CmsResult(
            source_key=source_key,
            source_name=source_name,
            vod_id=f"{source_key}-series",
            title="追更示例",
            year="2026",
            media_type="tv",
            remark="",
            episodes=tuple(
                CmsEpisode(
                    1,
                    episode,
                    f"第{episode}集",
                    f"https://{host}/s01e{episode:02d}.m3u8",
                )
                for episode in episodes
            ),
            season_range=(1, 1),
            season_ambiguous=False,
        )

    high_stale = season_result("high", "高清源", "high.example", (1, 2))
    lower_current = season_result(
        "current", "更新源", "current.example", (1, 2, 3)
    )
    rows = [high_stale]
    subscribe = SimpleNamespace(
        state="R",
        name="追更示例",
        year="2026",
        type="电视剧",
        season=1,
        media_source="lunatv",
        media_id="high:high-series",
        save_path=str(tmp_path),
    )
    _install_subscription_operator(monkeypatch, subscribe)

    class Client:
        def search(self, _query, **_kwargs):
            return list(rows)

    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "download_root": str(tmp_path)})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_prepare_result", lambda result: (result, {}))
    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    monkeypatch.setattr(plugin, "_native_history_has_episode", lambda _task: False)
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {
            url: 1080 if "high.example" in url else 720 for url in urls
        },
    )

    assert plugin.refresh_subscriptions()["queued"] == 2
    rows[:] = [high_stale, lower_current]
    assert plugin.refresh_subscriptions()["queued"] == 1
    tasks = sorted(plugin._queue.list_tasks(), key=lambda item: item["episode"])
    assert [task["episode"] for task in tasks] == [1, 2, 3]
    assert tasks[-1]["url"] == "https://current.example/s01e03.m3u8"
    torrents = plugin.list_torrents()
    assert len(torrents) == 1
    assert "共3集" in str(getattr(torrents[0], "title", ""))
    assert "已下载0/3" in str(getattr(torrents[0], "season_episode", ""))


def test_remove_whole_season_is_rejected_atomically_while_organizing(
    monkeypatch, tmp_path: Path
):
    plugin = _plugin()
    plugin.init_plugin(
        {
            "enabled": True,
            "download_root": str(tmp_path),
            "max_concurrent_tasks": 1,
        }
    )
    tasks = [
        DownloadTask(
            task_id=f"organizing-{episode}",
            source_key="lunatv",
            media_id="themoviedb:1234",
            title="追更示例",
            year="2026",
            media_type="tv",
            season=1,
            episode=episode,
            url=f"https://example.test/s01e{episode:02d}.m3u8",
            root=str(tmp_path),
            host_media_source="themoviedb",
            host_media_id="1234",
        )
        for episode in (1, 2)
    ]
    callback_started = threading.Event()
    release_callback = threading.Event()

    def execute(task):
        output = tmp_path / f"episode-{task.episode}.mp4"
        output.write_bytes(b"completed")
        return str(output)

    def organize(_task, _output):
        callback_started.set()
        assert release_callback.wait(timeout=2)

    monkeypatch.setattr(plugin._queue, "_execute", execute)
    plugin._queue._on_complete = organize
    assert all(plugin._queue.enqueue(task) for task in tasks)
    assert plugin._queue.wake() is True
    assert callback_started.wait(timeout=2)

    assert (
        plugin.remove_torrents(
            [tasks[0].task_id],
            delete_file=False,
            downloader="LunaTVSource",
        )
        is False
    )
    assert {item["task_id"] for item in plugin._queue.list_tasks()} == {
        task.task_id for task in tasks
    }

    release_callback.set()
    assert plugin._queue.wait_until_idle(timeout=2)


def test_subscription_events_request_immediate_refresh_only_while_enabled(monkeypatch):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    refresh_calls = []
    monkeypatch.setattr(
        plugin,
        "_start_background",
        lambda func: refresh_calls.append(func) or True,
    )

    plugin._on_subscribe_added(SimpleNamespace())
    plugin._on_subscribe_modified(SimpleNamespace())

    assert refresh_calls == [plugin.refresh_subscriptions, plugin.refresh_subscriptions]

    plugin._enabled = False
    plugin._on_subscribe_added(SimpleNamespace())
    plugin._on_subscribe_modified(SimpleNamespace())
    assert refresh_calls == [plugin.refresh_subscriptions, plugin.refresh_subscriptions]


def test_reconcile_completed_episode_replaces_failure_but_not_active_task(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_args: None)

    def task(task_id: str, state: str) -> DownloadTask:
        return DownloadTask(
            task_id=task_id,
            source_key="lunatv",
            media_id="themoviedb:1234",
            title="追更示例",
            year="2026",
            media_type="tv",
            season=1,
            episode=1,
            url="https://example.test/s01e01.m3u8",
            root=str(tmp_path),
            host_media_source="themoviedb",
            host_media_id="1234",
            state=state,
            error="previous failure" if state == "failed" else "",
        )

    failed = task("failed-old", "failed")
    data[queue.DATA_KEY] = [failed.to_dict()]
    observed = task("new-random-id", "pending")
    observed.downloaded_bytes = 321

    assert queue.reconcile_completed(observed, output="/media/tv/episode-1.mp4")
    completed = queue.list_tasks()
    assert len(completed) == 1
    assert completed[0]["task_id"] == "failed-old"
    assert completed[0]["state"] == "completed"
    assert completed[0]["progress"] == 1.0
    assert completed[0]["error"] == ""
    assert completed[0]["output"] == "/media/tv/episode-1.mp4"
    assert completed[0]["downloaded_bytes"] == 321

    active = task("active", "pending")
    data[queue.DATA_KEY] = [active.to_dict()]
    assert not queue.reconcile_completed(observed)
    assert queue.list_tasks()[0]["state"] == "pending"
