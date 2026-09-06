import http.server
import shutil
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

import app.plugins.lunatvsource.downloader as downloader_module
from app.plugins.lunatvsource.downloader import (
    DownloadQueue,
    DownloadTask,
    _LoopbackHTTPServer,
    _SegmentProxy,
    _mpegts_payload_offset,
)


def _payload_items(payload):
    return payload["items"] if isinstance(payload, dict) else payload


def test_download_task_public_dict_redacts_private_error_url(tmp_path: Path):
    task = DownloadTask(
        task_id="public-task",
        source_key="lunatv",
        media_id="site:public",
        title="公开任务",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://source.example/video.m3u8?token=source-secret",
        root=str(tmp_path),
        state="failed",
        error=(
            "下载失败 https://alice:password@example.test/video.m3u8"
            "?token=error-secret#fragment"
        ),
    )

    assert task.public_dict() == {
        "task_id": "public-task",
        "title": "公开任务",
        "state": "failed",
        "error": "下载失败 https://example.test/video.m3u8",
    }
    task.error = "下载失败 HTTPS://alice:password@example.test/video.m3u8?token=secret"
    assert task.public_dict()["error"] == "下载失败 https://example.test/video.m3u8"
    assert task.to_dict()["url"].endswith("token=source-secret")


def test_queue_disables_invalid_ad_filter_regex(caplog):
    with caplog.at_level("WARNING", logger="LunaTVSource"):
        queue = DownloadQueue(
            {}.get,
            lambda *_args: None,
            lambda *_args: None,
            ad_filter_regex="[",
        )

    assert queue._ad_filter_regex == ""
    assert "广告正则无效" in caplog.text


def test_queue_default_ad_filter_matches_decoded_path_only():
    default_queue = DownloadQueue(
        {}.get,
        lambda *_args: None,
        lambda *_args: None,
        ad_filter_regex=downloader_module.DEFAULT_HLS_AD_FILTER_REGEX,
    )
    custom_queue = DownloadQueue(
        {}.get,
        lambda *_args: None,
        lambda *_args: None,
        ad_filter_regex=r"customer_ad_id",
    )

    assert not default_queue._is_ad_segment_url(
        "https://cdn.example/show/part.ts?customer_ad_id=123"
    )
    assert default_queue._is_ad_segment_url("https://cdn.example/ads/spot.ts")
    assert custom_queue._is_ad_segment_url(
        "https://cdn.example/show/part.ts?customer_ad_id=123"
    )


def test_download_queue_passes_combined_ad_keyword_to_engine(
    monkeypatch, tmp_path: Path, caplog
):
    playlist = tmp_path / "input.m3u8"
    playlist.write_text("#EXTM3U\n#EXTINF:1,\nsegment.ts\n", encoding="utf-8")
    captured = {}
    prepared = {}

    class Engine:
        def download(self, input_url, output, **kwargs):
            captured.update(input_url=input_url, output=output, **kwargs)

    queue = DownloadQueue(
        {}.get,
        lambda *_args: None,
        lambda *_args: None,
        ad_filter_regex=r"/ads/",
    )
    queue._m3u8_engines = (Engine(),)

    def prepare(*args, **_kwargs):
        prepared["ad_url_matcher"] = args[5]
        args[6](
            {
                "cue_segments": 2,
                "cue_seconds": 30.0,
                "regex_segments": 1,
                "total_segments": 3,
                "unclosed_cue": 1,
                "daterange_candidates": 2,
                "discontinuity": 1,
            }
        )
        return str(playlist)

    monkeypatch.setattr(queue, "_prepare_hls_input", prepare)
    task = DownloadTask(
        task_id="ad-filter",
        source_key="source",
        media_id="media",
        title="title",
        year="2026",
        media_type="电影",
        season=1,
        episode=1,
        url="https://media.example/index.m3u8",
        root=str(tmp_path),
    )

    with caplog.at_level("INFO", logger="LunaTVSource"):
        assert queue._run_m3u8_engines(task, tmp_path / "movie.mp4.part") is True
    assert captured["ad_keyword"] == "lunatv-cue-ad"
    assert prepared["ad_url_matcher"]("https://cdn.example/ads/spot.ts") is True
    assert prepared["ad_url_matcher"]("https://cdn.example/show/part.ts") is False
    assert "task_id=ad-filter" in caplog.text
    assert "title=title" in caplog.text
    assert "总计待过滤=3分片" in caplog.text


def test_queue_is_serial_and_deduplicates(tmp_path: Path):
    data = {}
    notifications = []
    queue = DownloadQueue(data.get, data.__setitem__, lambda title, text: notifications.append((title, text)))
    first = DownloadTask(
        task_id="1", source_key="lunatv", media_id="site:1", title="示例", year="2024",
        media_type="tv", season=1, episode=1, url="https://example.test/a.m3u8", root=str(tmp_path),
    )
    second = DownloadTask(
        task_id="2", source_key="lunatv", media_id="site:1", title="示例", year="2024",
        media_type="tv", season=1, episode=1, url="https://example.test/a.m3u8", root=str(tmp_path),
    )
    assert queue.enqueue(first) is True
    assert queue.enqueue(second) is False
    assert queue.summary()["pending"] == 1

    assert queue.pause(first.task_id) is True
    paused_duplicate = DownloadTask(**{**second.to_dict(), "task_id": "3"})
    assert queue.enqueue(paused_duplicate) is False
    assert queue.summary()["paused"] == 1


def test_queue_persistence_keeps_non_terminal_tasks_and_caps_terminal_history(
    tmp_path: Path, monkeypatch
):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)

    def make_task(task_id: str, state: str) -> DownloadTask:
        return DownloadTask(
            task_id=task_id,
            source_key="lunatv",
            media_id=f"site:{task_id}",
            title=task_id,
            year="2026",
            media_type="movie",
            season=1,
            episode=1,
            url=f"https://example.test/{task_id}.m3u8",
            root=str(tmp_path),
            state=state,
        )

    terminal_tasks = [
        make_task(
            f"terminal-{index}", "completed" if index % 2 else "failed"
        )
        for index in range(501)
    ]
    pending_ids = [f"pending-{index}" for index in range(501)]
    pending_tasks = [make_task(task_id, "pending") for task_id in pending_ids]
    preserved_non_terminal_ids = ["paused", "future-state"]

    queue._write(
        terminal_tasks
        + pending_tasks
        + [
            make_task("paused", "paused"),
            make_task("future-state", "waiting_for_network"),
        ]
    )

    persisted = _payload_items(data[queue.DATA_KEY])
    assert [item["task_id"] for item in persisted] == (
        [f"terminal-{index}" for index in range(1, 501)]
        + pending_ids
        + preserved_non_terminal_ids
    )
    assert sum(
        item["state"] in {"completed", "failed"} for item in persisted
    ) == 500

    executed = []

    def execute(task: DownloadTask) -> str:
        executed.append(task.task_id)
        return str(tmp_path / f"{task.task_id}.mp4")

    monkeypatch.setattr(queue, "_execute", execute)
    for task_id in pending_ids:
        assert queue.run_one()["task_id"] == task_id

    assert executed == pending_ids
    assert sum(
        item["state"] in {"completed", "failed"}
        for item in _payload_items(data[queue.DATA_KEY])
    ) == 500


def test_queue_runs_one_task_and_records_completion(tmp_path: Path):
    data = {}
    completed = []
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        on_complete=lambda task, output: completed.append((task.task_id, output)),
    )
    task = DownloadTask(
        task_id="one", source_key="lunatv", media_id="site:2", title="示例", year="2024",
        media_type="movie", season=1, episode=1, url="https://example.test/a.m3u8", root=str(tmp_path),
    )
    queue.enqueue(task)
    queue._execute = lambda current: str(tmp_path / "示例.mp4")
    result = queue.run_one()
    assert result["state"] == "completed"
    assert completed == [("one", str(tmp_path / "示例.mp4"))]
    assert queue.summary()["pending"] == 0
    assert queue.summary()["completed"] == 1


def test_queue_wake_drains_task_enqueued_while_run_one_is_active(tmp_path: Path):
    data = {}
    completed_second = threading.Event()
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        on_complete=lambda task, _output: completed_second.set()
        if task.task_id == "added-while-running" else None,
    )
    active_task = DownloadTask(
        task_id="active",
        source_key="lunatv",
        media_id="site:active",
        title="示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/active.m3u8",
        root=str(tmp_path),
    )
    added_task = DownloadTask(
        task_id="added-while-running",
        source_key="lunatv",
        media_id="site:added",
        title="示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=2,
        url="https://example.test/added.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(active_task) is True
    active_started = threading.Event()
    allow_active_finish = threading.Event()
    execution_lock = threading.Lock()
    active_count = 0
    max_active_count = 0
    executed = []

    def execute(task: DownloadTask) -> str:
        nonlocal active_count, max_active_count
        with execution_lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
            executed.append(task.task_id)
        try:
            if task.task_id == active_task.task_id:
                active_started.set()
                assert allow_active_finish.wait(timeout=2)
            return str(tmp_path / f"{task.task_id}.mp4")
        finally:
            with execution_lock:
                active_count -= 1

    queue._execute = execute
    direct_worker = threading.Thread(target=queue.run_one)
    direct_worker.start()
    assert active_started.wait(timeout=2)
    assert queue.enqueue(added_task) is True
    assert queue.wake() is True
    allow_active_finish.set()
    direct_worker.join(timeout=2)

    assert not direct_worker.is_alive()
    assert completed_second.wait(timeout=2)
    assert executed == ["active", "added-while-running"]
    assert max_active_count == 1
    assert queue.summary()["completed"] == 2


def test_queue_recovers_after_running_state_persistence_failure(tmp_path: Path):
    data = {}
    running_save_failed = threading.Event()
    completed = threading.Event()
    fail_running_save = True

    def save(key, value):
        nonlocal fail_running_save
        if fail_running_save and any(
            item["state"] == "running" for item in _payload_items(value)
        ):
            fail_running_save = False
            running_save_failed.set()
            raise RuntimeError("temporary persistence failure")
        data[key] = value

    queue = DownloadQueue(
        data.get,
        save,
        lambda *_: None,
        on_complete=lambda *_: completed.set(),
    )
    task = DownloadTask(
        task_id="recover-after-save-failure",
        source_key="lunatv",
        media_id="site:recover",
        title="示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/recover.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(task) is True
    queue._execute = lambda current: str(tmp_path / f"{current.task_id}.mp4")

    assert queue.wake() is True
    assert running_save_failed.wait(timeout=2)
    for _ in range(100):
        with queue._lock:
            if not queue._drain_running:
                break
        threading.Event().wait(0.01)

    with queue._lock:
        assert queue._drain_running is False
        assert queue._running is False
        assert queue._current_task_id == ""
        assert queue._control_action == ""
        assert queue._idle_event.is_set()
    assert _payload_items(data[queue.DATA_KEY])[0]["state"] == "pending"

    assert queue.wake() is True
    assert completed.wait(timeout=2)
    assert queue.summary()["completed"] == 1


def test_queue_wake_during_worker_failure_is_not_lost(tmp_path: Path):
    data = {}
    completed = threading.Event()
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        on_complete=lambda *_: completed.set(),
    )
    task = DownloadTask(
        task_id="wake-during-worker-failure",
        source_key="lunatv",
        media_id="site:wake-during-worker-failure",
        title="示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/recover.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(task) is True
    queue._execute = lambda current: str(tmp_path / f"{current.task_id}.mp4")

    first_attempt = threading.Event()
    release_failure = threading.Event()
    retried = threading.Event()
    original_run_one = queue.run_one
    attempts = 0

    def flaky_run_one():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_attempt.set()
            assert release_failure.wait(timeout=2)
            raise RuntimeError("temporary worker failure")
        retried.set()
        return original_run_one()

    queue.run_one = flaky_run_one
    assert queue.wake() is True
    assert first_attempt.wait(timeout=2)
    assert queue.wake() is True
    release_failure.set()

    assert retried.wait(timeout=2)
    assert completed.wait(timeout=2)
    assert queue.summary()["completed"] == 1



@pytest.mark.parametrize(
    ("media_type", "season", "episode", "expected_text"),
    [
        ("movie", 1, 1, "电影标题"),
        ("tv", 2, 3, "电视剧标题 S02E03"),
    ],
)
def test_queue_notifications_distinguish_movies_and_tv(
    tmp_path: Path,
    media_type: str,
    season: int,
    episode: int,
    expected_text: str,
):
    data = {}
    notifications = []
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda title, text: notifications.append((title, text)),
    )

    def make_task(task_id: str) -> DownloadTask:
        return DownloadTask(
            task_id=task_id,
            source_key="lunatv",
            media_id=f"site:{task_id}",
            title="电视剧标题" if media_type == "tv" else "电影标题",
            year="2026",
            media_type=media_type,
            season=season,
            episode=episode,
            url=f"https://example.test/{task_id}.m3u8",
            root=str(tmp_path),
        )

    completed_task = make_task("completed-notification")
    assert queue.enqueue(completed_task) is True
    queue._execute = lambda _task: str(tmp_path / "completed.mp4")
    assert queue.run_one()["state"] == "completed"

    failed_task = make_task("failed-notification")
    assert queue.enqueue(failed_task) is True

    def fail_download(_task):
        raise RuntimeError("source unavailable")

    queue._execute = fail_download
    assert queue.run_one()["state"] == "failed"
    assert notifications == [
        ("LunaTV 已完成", expected_text),
        ("LunaTV 下载失败", f"{expected_text}：source unavailable"),
    ]


def test_queue_recovers_interrupted_running_task(tmp_path: Path):
    data = {
        "download_tasks_v1": [
            DownloadTask(
                task_id="stale", source_key="lunatv", media_id="site:3", title="示例", year="2024",
                media_type="movie", season=1, episode=1, url="https://example.test/a.m3u8",
                root=str(tmp_path), state="running", progress=0.3846,
            ).to_dict()
        ]
    }
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    tasks = queue.list_tasks()
    assert tasks[0]["state"] == "pending"
    assert tasks[0]["progress"] == 0.0
    assert "恢复" in tasks[0]["error"]


def test_queue_clears_stale_progress_from_paused_task(tmp_path: Path):
    data = {
        "download_tasks_v1": [
            DownloadTask(
                task_id="paused-stale",
                source_key="lunatv",
                media_id="site:paused",
                title="暂停示例",
                year="2024",
                media_type="movie",
                season=1,
                episode=1,
                url="https://example.test/paused.m3u8",
                root=str(tmp_path),
                state="paused",
                progress=0.3846,
            ).to_dict()
        ]
    }

    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    tasks = queue.list_tasks()

    assert tasks[0]["state"] == "paused"
    assert tasks[0]["progress"] == 0.0


def test_queue_retry_clears_stale_failed_progress(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="failed-stale",
        source_key="lunatv",
        media_id="site:failed-stale",
        title="失败示例",
        year="2024",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/failed-stale.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(task) is True

    def fail_download(current_task):
        queue._update_progress(current_task.task_id, 0.3846)
        raise RuntimeError("source unavailable")

    queue._execute = fail_download
    assert queue.run_one()["state"] == "failed"
    assert queue.list_tasks()[0]["progress"] == pytest.approx(0.3846)

    retry_started = threading.Event()
    release_retry = threading.Event()

    def retry_download(current_task):
        retry_started.set()
        assert release_retry.wait(timeout=2)
        return str(tmp_path / f"{current_task.task_id}.mp4")

    queue._execute = retry_download
    assert queue.retry(task.task_id) is True
    assert retry_started.wait(timeout=2)
    retried = queue.list_tasks()[0]
    assert retried["state"] == "running"
    assert retried["progress"] == 0.0
    assert retried["error"] == ""
    release_retry.set()
    assert queue.wait_until_idle(timeout=2)
    assert queue.list_tasks()[0]["state"] == "completed"



def test_queue_pause_resume_and_remove_pending_task(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="controlled", source_key="lunatv", media_id="site:control",
        title="示例", year="2026", media_type="movie", season=1, episode=1,
        url="https://example.test/control.m3u8", root=str(tmp_path),
    )
    assert queue.enqueue(task) is True
    assert queue.pause(task.task_id) is True
    assert queue.list_tasks()[0]["state"] == "paused"
    assert queue.list_tasks()[0]["progress"] == 0.0
    assert queue.run_one() == {"processed": 0}
    assert queue.resume(task.task_id) is True
    assert queue.list_tasks()[0]["state"] in {"pending", "running"}
    assert queue.remove(task.task_id) is True
    assert queue.wait_until_idle(timeout=2)
    assert queue.list_tasks() == []


def test_queue_clears_stale_progress_during_pending_pause_and_resume(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="pending-stale",
        source_key="lunatv",
        media_id="site:pending-stale",
        title="暂停示例",
        year="2024",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/pending-stale.m3u8",
        root=str(tmp_path),
        progress=0.3846,
    )
    assert queue.enqueue(task) is True
    assert queue.pause(task.task_id) is True
    assert queue.list_tasks()[0]["state"] == "paused"
    assert queue.list_tasks()[0]["progress"] == 0.0

    _payload_items(data["download_tasks_v1"])[0]["progress"] = 0.3846
    resume_started = threading.Event()
    release_resume = threading.Event()

    def resumed_download(current_task):
        resume_started.set()
        assert release_resume.wait(timeout=2)
        return str(tmp_path / f"{current_task.task_id}.mp4")

    queue._execute = resumed_download
    assert queue.resume(task.task_id) is True
    assert resume_started.wait(timeout=2)
    resumed = queue.list_tasks()[0]
    assert resumed["state"] == "running"
    assert resumed["progress"] == 0.0
    release_resume.set()
    assert queue.wait_until_idle(timeout=2)
    assert queue.list_tasks()[0]["state"] == "completed"



def test_queue_safely_pauses_running_task(tmp_path: Path, monkeypatch):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="running-control",
        source_key="lunatv",
        media_id="site:running",
        title="示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/running.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(task) is True
    executing = threading.Event()

    def controlled_engine(current, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("partial", encoding="utf-8")
        queue._update_progress(current.task_id, 0.3846)
        executing.set()
        assert queue._control_event.wait(timeout=2)
        raise downloader_module._QueueControl("controlled")

    monkeypatch.setattr(queue, "_run_m3u8_engines", controlled_engine)
    result = {}
    worker = threading.Thread(target=lambda: result.update(queue.run_one()))
    worker.start()
    assert executing.wait(timeout=2)
    assert queue.pause(task.task_id) is True
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result["state"] == "pause"
    stored = queue.list_tasks()[0]
    assert stored["state"] == "paused"
    assert stored["progress"] == 0.0
    assert not list(tmp_path.rglob("*.part"))



def test_queue_safely_removes_running_task(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="running-remove", source_key="lunatv", media_id="site:remove",
        title="示例", year="2026", media_type="movie", season=1, episode=1,
        url="https://example.test/running.m3u8", root=str(tmp_path),
    )
    assert queue.enqueue(task) is True
    executing = threading.Event()

    def controlled_execute(_task):
        executing.set()
        assert queue._control_event.wait(timeout=2)
        raise downloader_module._QueueControl("controlled")

    queue._execute = controlled_execute
    result = {}
    worker = threading.Thread(target=lambda: result.update(queue.run_one()))
    worker.start()
    assert executing.wait(timeout=2)
    assert queue.remove(task.task_id) is True
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result["state"] == "remove"
    assert queue.list_tasks() == []


@pytest.mark.parametrize("action", ["pause", "remove"])
def test_running_control_intent_survives_restart(tmp_path: Path, action: str):
    data = {}
    data_path = tmp_path / "queue-data"
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        data_path=data_path,
    )
    task = DownloadTask(
        task_id=f"restart-{action}",
        source_key="lunatv",
        media_id=f"site:restart-{action}",
        title="重启控制",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/restart-control.m3u8",
        root=str(tmp_path / "downloads"),
    )
    assert queue.enqueue(task)
    assert queue._claim_next() is not None

    _root, destination = queue._destination_for_task(task)
    if action == "remove":
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("media", encoding="utf-8")
        Path(f"{destination}.part").write_text("partial", encoding="utf-8")
        assert queue.remove(task.task_id, delete_file=True)
    else:
        assert queue.pause(task.task_id)

    stored = _payload_items(data[queue.DATA_KEY])[0]
    assert stored["state"] == "running"
    assert stored["control_action"] == action
    assert stored["delete_file"] is (action == "remove")

    restarted = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        data_path=data_path,
    )
    if action == "pause":
        recovered = restarted.list_tasks()
        assert len(recovered) == 1
        assert recovered[0]["state"] == "paused"
        assert recovered[0]["control_action"] == ""
        assert recovered[0]["delete_file"] is False
    else:
        assert restarted.list_tasks() == []
        assert not destination.exists()
        assert not Path(f"{destination}.part").exists()


def test_queue_persists_active_engine_progress(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="progress-task", source_key="lunatv", media_id="site:progress",
        title="进度电影", year="2026", media_type="movie", season=1, episode=1,
        url="https://example.test/progress.m3u8", root=str(tmp_path), state="running",
    )
    queue.enqueue(task)
    # enqueue() normally stores pending; emulate the active worker state.
    raw = data[queue.DATA_KEY]
    raw_items = _payload_items(raw)
    raw_items[0]["state"] = "running"
    data[queue.DATA_KEY] = raw
    queue._update_progress(task.task_id, 0.42)
    assert queue.list_tasks()[0]["progress"] == 0.42
    queue._update_progress(task.task_id, 1.5)
    assert queue.list_tasks()[0]["progress"] == 0.99




@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")




def test_mpegts_payload_offset_removes_fake_jpeg_header():
    payload = b"\x47" + (b"a" * 187)
    wrapped = b"\xff\xd8\xff\xe0" + (b"j" * 71) + payload * 3
    assert _mpegts_payload_offset(wrapped) == 75
    assert _mpegts_payload_offset(payload * 3) == 0


def test_segment_proxy_streams_unwrapped_mpegts():
    packet = b"\x47" + (b"a" * 187)
    wrapped = b"\xff\xd8\xff\xe0" + (b"j" * 71) + packet * 3

    class SourceHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler contract
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(wrapped)))
            self.end_headers()
            self.wfile.write(wrapped)

        def log_message(self, *_args):
            return

    source = _LoopbackHTTPServer(("127.0.0.1", 0), SourceHandler)
    thread = threading.Thread(target=source.serve_forever, daemon=True)
    thread.start()
    try:
        remote = f"http://127.0.0.1:{source.server_address[1]}/segment.jpeg"
        with _SegmentProxy(("127.0.0.0/8",)) as proxy, urllib.request.urlopen(
            proxy.url_for(remote), timeout=5
        ) as response:
            assert response.version == 11
            assert response.headers.get_content_type() == "video/mp2t"
            assert response.headers.get("Content-Length") == str(len(packet) * 3)
            assert response.headers.get("Connection") is None
            assert response.read() == packet * 3
    finally:
        source.shutdown()
        source.server_close()
        thread.join(timeout=2)


def test_segment_proxy_closes_http11_response_without_upstream_length():
    payload = (b"\x47" + (b"a" * 187)) * 3

    class SourceHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler contract
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return

    source = _LoopbackHTTPServer(("127.0.0.1", 0), SourceHandler)
    thread = threading.Thread(target=source.serve_forever, daemon=True)
    thread.start()
    try:
        remote = f"http://127.0.0.1:{source.server_address[1]}/segment.ts"
        with _SegmentProxy(("127.0.0.0/8",)) as proxy, urllib.request.urlopen(
            proxy.url_for(remote), timeout=5
        ) as response:
            assert response.version == 11
            assert response.headers.get("Content-Length") is None
            assert response.headers.get("Connection") == "close"
            assert response.read() == payload
    finally:
        source.shutdown()
        source.server_close()
        thread.join(timeout=2)


def test_segment_proxy_exposes_only_sanitized_source_hint():
    proxy = _SegmentProxy()
    proxy._server = type("Server", (), {"server_address": ("127.0.0.1", 1234)})()
    remote = "https://cdn.example/ads/spot.ts?token=secret&signature=private"

    normal = proxy.url_for(remote)
    advertised = proxy.url_for(remote, ad=True)

    for value in (normal, advertised):
        assert "cdn.example" not in value
        assert "/ads/" not in value
        assert "secret" not in value
        assert "private" not in value
        assert "source=" not in value
    assert "lunatv-cue-ad" not in normal
    assert "lunatv-cue-ad" in advertised


def test_prepare_hls_input_marks_regex_ad_urls_in_python(monkeypatch, tmp_path: Path):
    playlist = b"""#EXTM3U
#EXTINF:10,
show/main.ts
#EXTINF:5,
ads/spot.ts
#EXT-X-ENDLIST
"""
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    normal_urls = []
    ad_urls = []
    scan_summaries = []
    pattern = downloader_module.re.compile(
        downloader_module.DEFAULT_HLS_AD_FILTER_REGEX
    )

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/path/index.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
        lambda url: bool(pattern.search(url)),
        scan_summaries.append,
    )

    content = Path(local).read_text(encoding="utf-8")
    assert normal_urls == ["https://media.example/path/show/main.ts"]
    assert ad_urls == ["https://media.example/path/ads/spot.ts"]
    assert "normal:1" in content
    assert "lunatv-cue-ad:1" in content
    assert scan_summaries == [
        {
            "cue_segments": 0,
            "cue_seconds": 0.0,
            "regex_segments": 1,
            "total_segments": 1,
            "unclosed_cue": 0,
            "daterange_candidates": 0,
            "discontinuity": 0,
        }
    ]


def test_prepare_hls_input_marks_foreign_discontinuity_block_as_ad(
    monkeypatch, tmp_path: Path
):
    playlist = b"""#EXTM3U
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-a.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://cdn.example/20260902/slot/1000kb/hls/insert-a.ts
#EXTINF:5,
https://cdn.example/20260902/slot/1000kb/hls/insert-b.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-b.ts
#EXT-X-ENDLIST
"""
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    normal_urls = []
    ad_urls = []
    scans = []

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/index.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
        lambda _url: False,
        scans.append,
    )

    content = Path(local).read_text(encoding="utf-8")
    assert normal_urls == [
        "https://cdn.example/20260901/show/2000kb/hls/main-a.ts",
        "https://cdn.example/20260901/show/2000kb/hls/main-b.ts",
    ]
    assert ad_urls == [
        "https://cdn.example/20260902/slot/1000kb/hls/insert-a.ts",
        "https://cdn.example/20260902/slot/1000kb/hls/insert-b.ts",
    ]
    assert content.count("lunatv-cue-ad:") == 2
    assert scans == [
        {
            "cue_segments": 0,
            "cue_seconds": 0.0,
            "regex_segments": 0,
            "total_segments": 2,
            "unclosed_cue": 0,
            "daterange_candidates": 0,
            "discontinuity": 2,
            "splice_segments": 2,
            "splice_seconds": 10.0,
        }
    ]


def test_prepare_hls_input_keeps_same_asset_discontinuity_blocks(
    monkeypatch, tmp_path: Path
):
    playlist = b"""#EXTM3U
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-a.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://cdn.example/20260901/show/2000kb/hls/main-b.ts
#EXTINF:5,
https://cdn.example/20260901/show/2000kb/hls/main-c.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-d.ts
#EXT-X-ENDLIST
"""
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    normal_urls = []
    ad_urls = []
    scans = []

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/index.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
        lambda _url: False,
        scans.append,
    )

    assert len(normal_urls) == 4
    assert ad_urls == []
    assert "lunatv-cue-ad:" not in Path(local).read_text(encoding="utf-8")
    assert scans == [
        {
            "cue_segments": 0,
            "cue_seconds": 0.0,
            "regex_segments": 0,
            "total_segments": 0,
            "unclosed_cue": 0,
            "daterange_candidates": 0,
            "discontinuity": 2,
        }
    ]


def test_prepare_hls_input_marks_same_asset_discontinuity_block_on_resolution_change(
    monkeypatch, tmp_path: Path
):
    playlist = b"""#EXTM3U
#EXTINF:4,
https://cdn.example/a326662f8c5000073.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://cdn.example/a326662f8c50621221.ts
#EXTINF:5,
https://cdn.example/a326662f8c50621222.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/a326662f8c5000074.ts
#EXT-X-ENDLIST
"""
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    heights = {
        "a326662f8c5000073.ts": 576,
        "a326662f8c50621221.ts": 1080,
        "a326662f8c50621222.ts": 1080,
        "a326662f8c5000074.ts": 576,
    }
    probed_urls = []
    normal_urls = []
    ad_urls = []
    scans = []

    def probe(url: str) -> int:
        probed_urls.append(url)
        return heights[url.rsplit("/", 1)[-1]]

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/index.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
        lambda _url: False,
        scans.append,
        segment_height_probe=probe,
    )

    content = Path(local).read_text(encoding="utf-8")
    assert len(probed_urls) == 3
    assert len(normal_urls) == 2
    assert len(ad_urls) == 2
    assert "a326662f8c50621221.ts" not in content
    assert "a326662f8c50621222.ts" not in content
    assert content.count("lunatv-cue-ad:") == 2
    assert scans[0]["splice_segments"] == 2
    assert scans[0]["splice_seconds"] == 10.0
    assert scans[0]["same_asset_splice_segments"] == 2
    assert scans[0]["same_asset_splice_seconds"] == 10.0


def test_prepare_hls_input_uses_sequence_fallback_when_probe_unavailable(
    monkeypatch, tmp_path: Path
):
    candidate_urls = [
        f"https://v.cdnlz19.com/20240509/33191_c7cd13b5/a326662f8c{number}.ts"
        for number in range(50621221, 50621228)
    ]
    playlist_lines = [
        "#EXTM3U",
        "#EXTINF:4,",
        "https://v.cdnlz19.com/20240509/33191_c7cd13b5/a326662f8c5000073.ts",
        "#EXT-X-DISCONTINUITY",
    ]
    for index, url in enumerate(candidate_urls):
        playlist_lines.extend([f"#EXTINF:{4 if index < 5 else 3},", url])
    playlist_lines.extend(
        [
            "#EXT-X-DISCONTINUITY",
            "#EXTINF:4,",
            "https://v.cdnlz19.com/20240509/33191_c7cd13b5/a326662f8c5000074.ts",
            "#EXT-X-ENDLIST",
        ]
    )
    playlist = ("\n".join(playlist_lines) + "\n").encode()
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    normal_urls = []
    ad_urls = []
    scans = []

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/index.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
        lambda _url: False,
        scans.append,
        segment_height_probe=lambda _url: 0,
    )

    content = Path(local).read_text(encoding="utf-8")
    assert len(normal_urls) == 2
    assert len(ad_urls) == 7
    assert all(url not in content for url in candidate_urls)
    assert scans[0]["splice_segments"] == 7
    assert scans[0]["splice_seconds"] == 26.0
    assert scans[0]["same_asset_splice_segments"] == 7
    assert scans[0]["same_asset_splice_seconds"] == 26.0


def test_same_asset_discontinuity_uses_strong_sequence_fallback_when_probe_unavailable():
    lines = """#EXTM3U
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/segment-0073.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://cdn.example/20260901/show/2000kb/hls/segment-621221.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/segment-0074.ts
#EXT-X-ENDLIST
""".splitlines()
    stats = {}

    def unavailable(_url: str) -> int:
        return 0

    assert DownloadQueue._closed_discontinuity_ad_segments(
        lines,
        lambda url: url,
        unavailable,
        stats,
    ) == (
        {lines.index("https://cdn.example/20260901/show/2000kb/hls/segment-621221.ts")},
        1,
        5.0,
    )
    assert stats == {"segments": 1, "seconds": 5.0}


def test_same_asset_discontinuity_fallback_matches_lunatv_inserted_run():
    candidate_urls = [
        f"https://v.cdnlz19.com/20240509/33191_c7cd13b5/a326662f8c{number}.ts"
        for number in range(50621221, 50621228)
    ]
    lines = [
        "#EXTM3U",
        "#EXTINF:4,",
        "https://v.cdnlz19.com/20240509/33191_c7cd13b5/a326662f8c5000073.ts",
        "#EXT-X-DISCONTINUITY",
    ]
    for index, url in enumerate(candidate_urls):
        lines.extend([f"#EXTINF:{4 if index < 5 else 3},", url])
    lines.extend(
        [
            "#EXT-X-DISCONTINUITY",
            "#EXTINF:4,",
            "https://v.cdnlz19.com/20240509/33191_c7cd13b5/a326662f8c5000074.ts",
            "#EXT-X-ENDLIST",
        ]
    )
    stats = {}

    marked, segment_count, seconds = (
        DownloadQueue._closed_discontinuity_ad_segments(
            lines, lambda url: url, lambda _url: 0, stats
        )
    )

    assert marked == {lines.index(url) for url in candidate_urls}
    assert segment_count == 7
    assert seconds == pytest.approx(26.0)
    assert stats == {"segments": 7, "seconds": 26.0}


def test_same_asset_discontinuity_with_contiguous_numbers_is_not_probed():
    lines = """#EXTM3U
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/segment-0073.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://cdn.example/20260901/show/2000kb/hls/segment-0074.ts
#EXTINF:5,
https://cdn.example/20260901/show/2000kb/hls/segment-0075.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/segment-0076.ts
#EXT-X-ENDLIST
""".splitlines()

    def unexpected_probe(_url: str) -> int:
        raise AssertionError("contiguous media segments must not be probed")

    assert DownloadQueue._closed_discontinuity_ad_segments(
        lines,
        lambda url: url,
        unexpected_probe,
    ) == (set(), 0, 0.0)


def test_discontinuity_ad_detection_marks_repeated_foreign_asset_blocks():
    lines = """#EXTM3U
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-a.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://ads.example/20260902/slot-one/1000kb/hls/ad-a.ts
#EXTINF:5.5,
https://ads.example/20260902/slot-one/1000kb/hls/ad-b.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-middle.ts
#EXT-X-DISCONTINUITY
#EXTINF:6,
https://cdn.example/20260902/slot-two/1000kb/hls/ad-c.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-b.ts
#EXT-X-ENDLIST
""".splitlines()

    marked, segment_count, seconds = (
        DownloadQueue._closed_discontinuity_ad_segments(lines, lambda url: url)
    )

    assert marked == {
        lines.index("https://ads.example/20260902/slot-one/1000kb/hls/ad-a.ts"),
        lines.index("https://ads.example/20260902/slot-one/1000kb/hls/ad-b.ts"),
        lines.index("https://cdn.example/20260902/slot-two/1000kb/hls/ad-c.ts"),
    }
    assert segment_count == 3
    assert seconds == pytest.approx(16.5)


def test_discontinuity_ad_detection_keeps_consecutive_foreign_assets():
    lines = """#EXTM3U
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-a.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://ads.example/20260902/slot-one/1000kb/hls/ad-a.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://cdn.example/20260902/slot-two/1000kb/hls/ad-b.ts
#EXT-X-DISCONTINUITY
#EXTINF:4,
https://cdn.example/20260901/show/2000kb/hls/main-b.ts
#EXT-X-ENDLIST
""".splitlines()

    assert DownloadQueue._closed_discontinuity_ad_segments(
        lines, lambda url: url
    ) == (set(), 0, 0.0)


def test_discontinuity_ad_detection_keeps_unclosed_foreign_tail():
    lines = """#EXTM3U
#EXTINF:4,
https://cdn.example/show/main-a.ts
#EXT-X-DISCONTINUITY
#EXTINF:5,
https://ads.example/slot/ad-a.ts
#EXTINF:5,
https://ads.example/slot/ad-b.ts
#EXT-X-ENDLIST
""".splitlines()

    assert DownloadQueue._closed_discontinuity_ad_segments(
        lines, lambda url: url
    ) == (set(), 0, 0.0)


def test_discontinuity_ad_detection_does_not_cross_long_foreign_block():
    lines = [
        "#EXTM3U",
        "#EXTINF:4,",
        "https://cdn.example/20260901/show-a/2000kb/hls/main-a.ts",
        "#EXT-X-DISCONTINUITY",
    ]
    for index in range(4):
        lines.extend(
            [
                "#EXTINF:5,",
                f"https://ads.example/20260902/slot/1000kb/hls/ad-{index}.ts",
            ]
        )
    lines.append("#EXT-X-DISCONTINUITY")
    for index in range(31):
        lines.extend(
            [
                "#EXTINF:2,",
                f"https://cdn.example/20260901/show-b/2000kb/hls/main-{index}.ts",
            ]
        )
    lines.extend(
        [
            "#EXT-X-DISCONTINUITY",
            "#EXTINF:4,",
            "https://cdn.example/20260901/show-a/2000kb/hls/main-b.ts",
            "#EXT-X-ENDLIST",
        ]
    )

    assert DownloadQueue._closed_discontinuity_ad_segments(
        lines, lambda url: url
    ) == (set(), 0, 0.0)


def test_segment_proxy_forwards_byte_ranges_and_preserves_partial_response():
    payload = b"abcdef"
    seen_ranges = []

    class SourceHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler contract
            seen_ranges.append(self.headers.get("Range"))
            self.send_response(206)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", "bytes 2-4/6")
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(payload[2:5])

        def log_message(self, *_args):
            return

    source = _LoopbackHTTPServer(("127.0.0.1", 0), SourceHandler)
    thread = threading.Thread(target=source.serve_forever, daemon=True)
    thread.start()
    try:
        remote = f"http://127.0.0.1:{source.server_address[1]}/segments.ts"
        with _SegmentProxy(("127.0.0.0/8",)) as proxy:
            request = urllib.request.Request(
                proxy.url_for(remote), headers={"Range": "bytes=2-4"}
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 206
                assert response.headers.get("Accept-Ranges") == "bytes"
                assert response.headers.get("Content-Range") == "bytes 2-4/6"
                assert response.headers.get("Content-Length") == "3"
                assert response.read() == b"cde"
        assert seen_ranges == ["bytes=2-4"]
    finally:
        source.shutdown()
        source.server_close()
        thread.join(timeout=2)


def test_prepare_hls_input_marks_closed_cues_before_unclosed_tail(
    monkeypatch, tmp_path: Path, caplog
):
    playlist = b'''#EXTM3U
#EXT-X-CUE-OUT-CONT:ElapsedTime=3,Duration=30
#EXT-X-CUE-OUT:DURATION=30
#EXTINF:10,
a.ts
#EXT-X-CUE-OUT-CONT:ElapsedTime=10,Duration=30
#EXTINF:20,
b.ts
#EXT-X-CUE-IN
#EXT-X-CUE-OUT:15
#EXTINF:5,
c.ts
#EXT-X-DATERANGE:ID="ad",CLASS="com.apple.hls.interstitial"
#EXT-X-DATERANGE:ID="scte",SCTE35-OUT=0xFC
#EXT-X-DATERANGE:ID="program",CLASS="program-transition"
#EXT-X-DISCONTINUITY
#EXT-X-ENDLIST
'''

    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    report = DownloadQueue._detect_hls_markers(playlist.decode())
    assert report == {
        "cue_out": 2,
        "cue_out_cont": 2,
        "cue_in": 1,
        "cue_ranges": [(0.0, 30.0)],
        "unclosed_cue": 1,
        "daterange": 3,
        "daterange_candidates": 2,
        "discontinuity": 1,
    }

    with caplog.at_level("INFO", logger="LunaTVSource"):
        normal_urls = []
        ad_urls = []
        local = DownloadQueue._prepare_hls_input(
            "https://media.example/path/index.m3u8",
            tmp_path,
            lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
            (),
            lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
        )
    content = Path(local).read_text(encoding="utf-8")
    for marker in (
        "#EXT-X-CUE-OUT-CONT:ElapsedTime=3,Duration=30",
        "#EXT-X-CUE-OUT:DURATION=30",
        "#EXT-X-CUE-IN",
        "#EXT-X-CUE-OUT:15",
        '#EXT-X-DATERANGE:ID="ad",CLASS="com.apple.hls.interstitial"',
        "#EXT-X-DISCONTINUITY",
    ):
        assert marker in content
    assert "闭合候选=1 [0-30s]" in caplog.text
    assert ad_urls == [
        "https://media.example/path/a.ts",
        "https://media.example/path/b.ts",
    ]
    assert normal_urls == ["https://media.example/path/c.ts"]
    assert "待过滤=2分片/30.0秒" in caplog.text
    assert "未闭合=1" in caplog.text
    assert "DATERANGE广告候选=2/3" in caplog.text


def test_prepare_hls_input_marks_only_closed_cue_segments_for_engine_filter(
    monkeypatch, tmp_path: Path, caplog
):
    playlist = b'''#EXTM3U
#EXTINF:10,
main-a.ts
#EXT-X-CUE-OUT:20
#EXTINF:5,
ad-a.ts
#EXT-X-CUE-OUT-CONT:ElapsedTime=5,Duration=20
#EXTINF:15,
ad-b.ts
#EXT-X-CUE-IN
#EXT-X-DATERANGE:ID="program",CLASS="program-transition"
#EXT-X-DISCONTINUITY
#EXTINF:10,
main-b.ts
#EXT-X-ENDLIST
'''
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    normal_urls = []
    ad_urls = []

    with caplog.at_level("INFO", logger="LunaTVSource"):
        local = DownloadQueue._prepare_hls_input(
            "https://media.example/path/index.m3u8",
            tmp_path,
            lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
            (),
            lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
        )

    content = Path(local).read_text(encoding="utf-8")
    assert normal_urls == [
        "https://media.example/path/main-a.ts",
        "https://media.example/path/main-b.ts",
    ]
    assert ad_urls == [
        "https://media.example/path/ad-a.ts",
        "https://media.example/path/ad-b.ts",
    ]
    assert "ad-a.ts" not in content
    assert "ad-b.ts" not in content
    assert "normal:1" in content
    assert "normal:2" in content
    assert "lunatv-cue-ad:1" in content
    assert "lunatv-cue-ad:2" in content
    assert "#EXT-X-CUE-OUT" in content
    assert "#EXT-X-CUE-IN" in content
    assert '#EXT-X-DATERANGE:ID="program"' in content
    assert "#EXT-X-DISCONTINUITY" in content
    assert "待过滤=2分片/20.0秒" in caplog.text


def test_prepare_hls_input_marks_closed_cue_segments_in_master_variant(
    monkeypatch, tmp_path: Path
):
    playlists = {
        "https://media.example/master.m3u8": b"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1
variant.m3u8
""",
        "https://media.example/variant.m3u8": b"""#EXTM3U
#EXTINF:10,
main.ts
#EXT-X-CUE-OUT:10
#EXTINF:10,
ad.ts
#EXT-X-CUE-IN
#EXTINF:10,
tail.ts
#EXT-X-ENDLIST
""",
    }
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlists[url], url),
    )
    normal_urls = []
    ad_urls = []

    root = DownloadQueue._prepare_hls_input(
        "https://media.example/master.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
    )

    variant = Path(
        next(
            line
            for line in Path(root).read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )
    )
    content = variant.read_text(encoding="utf-8")
    assert normal_urls == [
        "https://media.example/main.ts",
        "https://media.example/tail.ts",
    ]
    assert ad_urls == ["https://media.example/ad.ts"]
    assert "lunatv-cue-ad:1" in content
    assert "normal:1" in content
    assert "normal:2" in content


def test_prepare_hls_input_preserves_key_map_and_byte_ranges_around_cue(
    monkeypatch, tmp_path: Path
):
    playlist = b'''#EXTM3U
#EXT-X-MAP:URI="init.mp4",BYTERANGE="720@0"
#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin",IV=0x01
#EXT-X-CUE-OUT:12
#EXT-X-BYTERANGE:1000@720
#EXTINF:6,
ad-a.m4s
#EXT-X-BYTERANGE:1000
#EXTINF:6,
ad-b.m4s
#EXT-X-CUE-IN
#EXTINF:6,
main.m4s
#EXT-X-ENDLIST
'''
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    normal_urls = []
    ad_urls = []

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/path/index.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
    )

    content = Path(local).read_text(encoding="utf-8")
    assert 'URI="normal:1",BYTERANGE="720@0"' in content
    assert 'URI="normal:2",IV=0x01' in content
    assert content.count("#EXT-X-BYTERANGE:1000") == 2
    assert ad_urls == [
        "https://media.example/path/ad-a.m4s",
        "https://media.example/path/ad-b.m4s",
    ]
    assert normal_urls == [
        "https://media.example/path/init.mp4",
        "https://media.example/path/keys/key.bin",
        "https://media.example/path/main.m4s",
    ]
    assert content.count("lunatv-cue-ad:") == 2
    assert "normal:3" in content


def test_prepare_hls_input_fails_open_for_unclosed_cue_daterange_and_discontinuity(
    monkeypatch, tmp_path: Path
):
    playlist = b'''#EXTM3U
#EXT-X-CUE-OUT:20
#EXTINF:10,
first.ts
#EXT-X-DATERANGE:ID="ad",CLASS="com.apple.hls.interstitial"
#EXT-X-DISCONTINUITY
#EXTINF:10,
second.ts
#EXT-X-ENDLIST
'''
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlist, url),
    )
    normal_urls = []
    ad_urls = []

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/path/index.m3u8",
        tmp_path,
        lambda url: normal_urls.append(url) or f"normal:{len(normal_urls)}",
        (),
        lambda url: ad_urls.append(url) or f"lunatv-cue-ad:{len(ad_urls)}",
    )

    content = Path(local).read_text(encoding="utf-8")
    assert normal_urls == [
        "https://media.example/path/first.ts",
        "https://media.example/path/second.ts",
    ]
    assert ad_urls == []
    assert "lunatv-cue-ad:" not in content
    assert '#EXT-X-DATERANGE:ID="ad",CLASS="com.apple.hls.interstitial"' in content
    assert "#EXT-X-DISCONTINUITY" in content


def test_strip_closed_cue_segments_preserves_unclosed_tail():
    playlist = """#EXTM3U
#EXTINF:10,
main.ts
#EXT-X-CUE-OUT:5
#EXTINF:5,
ad.ts
#EXT-X-CUE-IN
#EXT-X-CUE-OUT:5
#EXTINF:5,
tail.ts
#EXT-X-ENDLIST
"""

    stripped, segments, seconds = DownloadQueue._strip_closed_cue_segments(playlist)

    assert segments == 1
    assert seconds == 5.0
    assert "ad.ts" not in stripped
    assert "main.ts" in stripped
    assert "#EXT-X-CUE-OUT:5\n#EXTINF:5,\ntail.ts" in stripped


def test_prepare_hls_input_rejects_open_media_but_recurses_from_master(
    monkeypatch, tmp_path: Path
):
    playlists = {
        "https://media.example/open.m3u8": b"#EXTM3U\n#EXTINF:1,\npart.ts\n",
        "https://media.example/ll-open.m3u8": (
            b'#EXTM3U\n#EXT-X-PART:DURATION=0.333,URI="part.ts"\n'
            b'#EXT-X-PRELOAD-HINT:TYPE=PART,URI="next.ts"\n'
        ),
        "https://media.example/master.m3u8": b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nvariant.m3u8\n",
        "https://media.example/variant.m3u8": b"#EXTM3U\n#EXTINF:1,\npart.ts\n#EXT-X-ENDLIST\n",
    }
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlists[url], url),
    )

    with pytest.raises(RuntimeError, match="缺少 EXT-X-ENDLIST"):
        DownloadQueue._prepare_hls_input("https://media.example/open.m3u8", tmp_path)
    with pytest.raises(RuntimeError, match="缺少 EXT-X-ENDLIST"):
        DownloadQueue._prepare_hls_input("https://media.example/ll-open.m3u8", tmp_path)
    assert Path(
        DownloadQueue._prepare_hls_input("https://media.example/master.m3u8", tmp_path)
    ).exists()


def test_prepare_hls_input_decodes_zstd_and_absolutizes_urls(monkeypatch, tmp_path: Path):
    playlist = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:10,\nsegment.ts\n#EXT-X-ENDLIST\n'
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda *_args, **_kwargs: (
            b"\x28\xb5\x2f\xfdcompressed",
            "https://cdn.example/final/index.m3u8",
        ),
    )
    monkeypatch.setattr(
        DownloadQueue,
        "_decompress_zstd",
        lambda payload, _max_output_bytes: playlist,
    )
    mapped = []

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/path/index.m3u8",
        tmp_path,
        lambda url: mapped.append(url) or f"http://127.0.0.1/segment/{len(mapped)}",
    )
    content = Path(local).read_text(encoding="utf-8")
    assert mapped == [
        "https://cdn.example/final/key.bin",
        "https://cdn.example/final/segment.ts",
    ]
    assert "https://" not in content
    assert 'URI="http://127.0.0.1/segment/1"' in content
    assert "http://127.0.0.1/segment/2" in content


def test_decompress_zstd_enforces_python_output_limit(monkeypatch):
    limits = []

    class Decoder:
        @staticmethod
        def decompress(_payload, max_output_size):
            limits.append(max_output_size)
            return b"12345"

    class ZstandardModule:
        CONTENTSIZE_UNKNOWN = 0xFFFFFFFFFFFFFFFF
        CONTENTSIZE_ERROR = 0xFFFFFFFFFFFFFFFE

        @staticmethod
        def frame_content_size(_payload):
            return ZstandardModule.CONTENTSIZE_UNKNOWN

        @staticmethod
        def ZstdDecompressor():
            return Decoder()

    monkeypatch.setitem(sys.modules, "zstandard", ZstandardModule())

    with pytest.raises(RuntimeError, match="解压后过大"):
        DownloadQueue._decompress_zstd(b"compressed", 4)

    assert limits == [4]


def test_decompress_zstd_rejects_native_declared_oversize_before_allocation(monkeypatch):
    class NativeFunction:
        def __init__(self, result):
            self.result = result

        def __call__(self, *_args):
            return self.result

    class NativeLibrary:
        ZSTD_getFrameContentSize = NativeFunction(5)
        ZSTD_decompress = NativeFunction(0)
        ZSTD_isError = NativeFunction(0)

    allocations = []
    create_string_buffer = downloader_module.ctypes.create_string_buffer
    monkeypatch.setitem(sys.modules, "zstandard", None)
    monkeypatch.setattr(downloader_module.ctypes.util, "find_library", lambda _name: "libzstd")
    monkeypatch.setattr(downloader_module.ctypes, "CDLL", lambda _name: NativeLibrary())
    monkeypatch.setattr(
        downloader_module.ctypes,
        "create_string_buffer",
        lambda value: allocations.append(value) or create_string_buffer(value),
    )

    with pytest.raises(RuntimeError, match="解压后过大"):
        DownloadQueue._decompress_zstd(b"compressed", 4)

    assert allocations == [b"compressed"]


def test_prepare_hls_input_rejects_oversized_playlist(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(downloader_module, "_HLS_PLAYLIST_MAX_BYTES", 16)
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (b"#EXTM3U\n" + b"x" * 16, url),
    )

    with pytest.raises(RuntimeError, match="响应过大"):
        DownloadQueue._prepare_hls_input("https://example.test/index.m3u8", tmp_path)


def test_prepare_hls_input_caps_aggregate_playlist_bytes(monkeypatch, tmp_path: Path):
    root = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nchild.m3u8\n"
    child = b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n"
    monkeypatch.setattr(downloader_module, "_HLS_PLAYLIST_MAX_BYTES", 1024)
    monkeypatch.setattr(
        downloader_module,
        "_HLS_PLAYLIST_TOTAL_BYTES",
        len(root) + len(child) - 1,
    )
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (child if url.endswith("child.m3u8") else root, url),
    )

    with pytest.raises(RuntimeError, match="累计大小过大"):
        DownloadQueue._prepare_hls_input("https://example.test/index.m3u8", tmp_path)


def test_prepare_hls_input_caps_playlist_count(monkeypatch, tmp_path: Path):
    root = b"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1
one.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2
two.m3u8
"""
    child = b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n"
    monkeypatch.setattr(downloader_module, "_HLS_PLAYLIST_MAX_COUNT", 2)
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (root if url.endswith("index.m3u8") else child, url),
    )

    with pytest.raises(RuntimeError, match="数量过多"):
        DownloadQueue._prepare_hls_input("https://example.test/index.m3u8", tmp_path)


def test_prepare_hls_input_caps_playlist_depth(monkeypatch, tmp_path: Path):
    playlists = {
        "index.m3u8": b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\none.m3u8\n",
        "one.m3u8": b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\ntwo.m3u8\n",
        "two.m3u8": b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n",
    }
    monkeypatch.setattr(downloader_module, "_HLS_PLAYLIST_MAX_DEPTH", 1)
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlists[url.rsplit("/", 1)[-1]], url),
    )

    with pytest.raises(RuntimeError, match="嵌套层级过深"):
        DownloadQueue._prepare_hls_input("https://example.test/index.m3u8", tmp_path)


@pytest.mark.parametrize("uri", ["file:///tmp/playlist.m3u8", "ftp://example.test/x.m3u8"])
def test_prepare_hls_input_rejects_non_http_top_level_uri(monkeypatch, tmp_path: Path, uri: str):
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )

    with pytest.raises(RuntimeError, match="http/https"):
        DownloadQueue._prepare_hls_input(uri, tmp_path)


@pytest.mark.parametrize("uri", ["file:///tmp/segment.ts", "ftp://example.test/segment.ts"])
def test_prepare_hls_input_rejects_non_http_nested_uri(monkeypatch, tmp_path: Path, uri: str):
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (
            f"#EXTM3U\n#EXTINF:1,\n{uri}\n#EXT-X-ENDLIST\n".encode("utf-8"),
            url,
        ),
    )

    with pytest.raises(RuntimeError, match="http/https"):
        DownloadQueue._prepare_hls_input("https://example.test/index.m3u8", tmp_path)


def test_prepare_hls_input_rejects_private_top_level_uri(tmp_path: Path):
    with pytest.raises(ValueError, match="non-public"):
        DownloadQueue._prepare_hls_input("http://127.0.0.1/index.m3u8", tmp_path)


def test_failed_download_removes_only_new_empty_directories(tmp_path: Path, monkeypatch):
    root = tmp_path / "incoming"
    root.mkdir()
    task = DownloadTask(
        task_id="failed-cleanup",
        source_key="lunatv",
        media_id="site:4",
        title="测试电影",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/video.m3u8",
        root=str(root),
    )
    queue = DownloadQueue(lambda *_: [], lambda *_: None, lambda *_: None)
    monkeypatch.setattr(queue, "_run_m3u8_engines", lambda *_args, **_kwargs: False)

    with pytest.raises(RuntimeError, match="N_m3u8DL-RE"):
        queue._execute(task)

    assert root.exists()
    assert not list(root.iterdir())



def test_queue_remove_delete_file_flag_and_root_boundary(tmp_path: Path):
    root = tmp_path / "downloads"
    preserved = root / "Preserved 2026.mp4"
    preserved.parent.mkdir(parents=True)
    preserved.write_text("media", encoding="utf-8")
    preserved_part = Path(f"{preserved}.part")
    preserved_part.write_text("partial", encoding="utf-8")
    output = root / "Movie" / "Season 01" / "Movie 2026.mp4"
    output.parent.mkdir(parents=True)
    output.write_text("media", encoding="utf-8")
    part = Path(f"{output}.part")
    part.write_text("partial", encoding="utf-8")
    outside = tmp_path / "organized" / "Movie 2026.mp4"
    outside.parent.mkdir()
    outside.write_text("organized", encoding="utf-8")
    preserved_task = DownloadTask(
        task_id="preserve-file",
        source_key="lunatv",
        media_id="site:preserve-file",
        title="Preserved",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/preserved.m3u8",
        root=str(root),
        state="completed",
        output=str(preserved),
    )
    task = DownloadTask(
        task_id="delete-file",
        source_key="lunatv",
        media_id="site:delete-file",
        title="Movie",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(root),
        state="completed",
        output=str(output),
    )
    outside_task = DownloadTask(
        task_id="outside-file",
        source_key="lunatv",
        media_id="site:outside-file",
        title="Movie",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(root),
        state="completed",
        output=str(outside),
    )
    data = {
        DownloadQueue.DATA_KEY: [
            preserved_task.to_dict(),
            task.to_dict(),
            outside_task.to_dict(),
        ]
    }
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)

    assert queue.remove(preserved_task.task_id, delete_file=False) is True
    assert preserved.exists()
    assert preserved_part.exists()

    assert output.exists()
    assert part.exists()
    assert queue.remove(task.task_id, delete_file=True) is True
    assert not output.exists()
    assert not part.exists()
    assert not output.parent.exists()
    assert root.exists()

    assert queue.remove(outside_task.task_id, delete_file=True) is True
    assert outside.exists()


def test_strm_write_does_not_follow_precreated_part_symlink(tmp_path: Path):
    root = tmp_path / "downloads"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    task = DownloadTask(
        task_id="safe-strm",
        source_key="lunatv",
        media_id="site:safe-strm",
        title="Safe STRM",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://media.example/watch",
        root=str(root),
        mode="strm",
    )
    queue = DownloadQueue({}.get, lambda *_args: None, lambda *_args: None)
    _, destination = queue._destination_for_task(task)
    destination.parent.mkdir(parents=True, exist_ok=True)
    legacy_part = Path(f"{destination}.part")
    legacy_part.symlink_to(outside)

    assert queue._execute(task) == str(destination)

    assert destination.read_text(encoding="utf-8") == task.url + "\n"
    assert outside.read_text(encoding="utf-8") == "keep"
    assert not legacy_part.is_symlink()


def test_delete_task_unlinks_output_symlink_without_deleting_target(tmp_path: Path):
    root = tmp_path / "downloads"
    root.mkdir()
    target = root / "keep.mp4"
    target.write_text("keep", encoding="utf-8")
    output = root / "task.mp4"
    output.symlink_to(target)
    task = DownloadTask(
        task_id="safe-delete-link",
        source_key="lunatv",
        media_id="site:safe-delete-link",
        title="Other",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://media.example/index.m3u8",
        root=str(root),
        output=str(output),
    )
    queue = DownloadQueue({}.get, lambda *_args: None, lambda *_args: None)

    queue._delete_task_files(task)

    assert target.read_text(encoding="utf-8") == "keep"
    assert not output.is_symlink()


def test_delete_task_refuses_symlinked_parent_directory(tmp_path: Path):
    root = tmp_path / "downloads"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.mp4"
    victim.write_text("keep", encoding="utf-8")
    linked_parent = root / "linked"
    linked_parent.symlink_to(outside, target_is_directory=True)
    task = DownloadTask(
        task_id="safe-delete-parent",
        source_key="lunatv",
        media_id="site:safe-delete-parent",
        title="Other",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://media.example/index.m3u8",
        root=str(root),
        output=str(linked_parent / victim.name),
    )
    queue = DownloadQueue({}.get, lambda *_args: None, lambda *_args: None)

    queue._delete_task_files(task)

    assert victim.read_text(encoding="utf-8") == "keep"
    assert linked_parent.is_symlink()


@pytest.mark.parametrize("persist_before_error", [False, True])
def test_queue_remove_deletes_only_after_durable_state_removal(
    tmp_path: Path,
    persist_before_error: bool,
):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    output = tmp_path / "Movie (2026)" / "Movie (2026).mp4"
    output.parent.mkdir(parents=True)
    output.write_text("media", encoding="utf-8")
    task = DownloadTask(
        task_id=f"durable-remove-{int(persist_before_error)}",
        source_key="lunatv",
        media_id=f"site:durable-remove-{int(persist_before_error)}",
        title="Movie",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(tmp_path),
        output=str(output),
    )
    assert queue.enqueue(task) is True

    def fail_removal_write(key, value):
        if not any(
            item["task_id"] == task.task_id for item in _payload_items(value)
        ):
            if persist_before_error:
                data[key] = value
            raise RuntimeError("simulated removal persistence failure")
        data[key] = value

    queue._save = fail_removal_write

    if persist_before_error:
        assert queue.remove(task.task_id, delete_file=True) is True
    else:
        with pytest.raises(RuntimeError, match="removal persistence failure"):
            queue.remove(task.task_id, delete_file=True)

    restarted = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    if persist_before_error:
        assert restarted.list_tasks() == []
        assert not output.exists()
    else:
        assert [item["task_id"] for item in restarted.list_tasks()] == [task.task_id]
        assert output.exists()


def test_queue_remove_running_task_cleans_part_after_safe_stop(tmp_path: Path):
    root = tmp_path / "downloads"
    output = root / "Movie 2026.mp4"
    part = Path(f"{output}.part")
    started = threading.Event()

    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="running-delete-file",
        source_key="lunatv",
        media_id="site:running-delete-file",
        title="Movie",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(root),
    )
    queue.enqueue(task)

    def controlled_execute(current: DownloadTask) -> str:
        current.output = str(output)
        output.parent.mkdir(parents=True)
        output.write_text("media", encoding="utf-8")
        part.write_text("partial", encoding="utf-8")
        started.set()
        assert queue._control_event.wait(timeout=2)
        raise downloader_module._QueueControl("remove")

    queue._execute = controlled_execute
    result = {}
    worker = threading.Thread(target=lambda: result.update(queue.run_one()))
    worker.start()
    assert started.wait(timeout=2)
    assert queue.remove(task.task_id, delete_file=True) is True
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result["state"] == "remove"
    assert not output.exists()
    assert not part.exists()
    assert queue.list_tasks() == []


def test_queue_remove_running_task_wins_over_immediate_pause(tmp_path: Path):
    root = tmp_path / "downloads"
    output = root / "Movie 2026.mp4"
    part = Path(f"{output}.part")
    started = threading.Event()
    allow_control = threading.Event()

    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="running-remove-pause-race",
        source_key="lunatv",
        media_id="site:running-remove-pause-race",
        title="Movie",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(root),
    )
    assert queue.enqueue(task)

    def controlled_execute(current: DownloadTask) -> str:
        current.output = str(output)
        output.parent.mkdir(parents=True)
        output.write_text("media", encoding="utf-8")
        part.write_text("partial", encoding="utf-8")
        started.set()
        assert queue._control_event.wait(timeout=2)
        assert allow_control.wait(timeout=2)
        raise downloader_module._QueueControl("controlled")

    queue._execute = controlled_execute
    result = {}
    worker = threading.Thread(target=lambda: result.update(queue.run_one()))
    worker.start()
    assert started.wait(timeout=2)
    assert queue.remove(task.task_id, delete_file=True)
    assert queue.pause(task.task_id)
    allow_control.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result["state"] == "remove"
    assert not output.exists()
    assert not part.exists()
    assert queue.list_tasks() == []
    assert task.task_id not in queue._delete_file_tasks


def test_queue_remove_running_task_wins_success_race(tmp_path: Path):
    root = tmp_path / "downloads"
    output = root / "Movie 2026.mp4"
    started = threading.Event()
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="running-success-race",
        source_key="lunatv",
        media_id="site:running-success-race",
        title="Movie",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(root),
    )
    queue.enqueue(task)

    def completes_after_remove(current: DownloadTask) -> str:
        output.parent.mkdir(parents=True)
        output.write_text("media", encoding="utf-8")
        current.output = str(output)
        started.set()
        assert queue._control_event.wait(timeout=2)
        return str(output)

    queue._execute = completes_after_remove
    result = {}
    worker = threading.Thread(target=lambda: result.update(queue.run_one()))
    worker.start()
    assert started.wait(timeout=2)
    assert queue.remove(task.task_id, delete_file=True) is True
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result["state"] == "remove"
    assert not output.exists()
    assert queue.list_tasks() == []


@pytest.mark.parametrize(
    ("action", "persist_before_error"),
    [
        ("pause", False),
        ("pause", True),
        ("remove", False),
        ("remove", True),
    ],
    ids=[
        "pause-write-before-error",
        "pause-write-then-error",
        "remove-write-before-error",
        "remove-write-then-error",
    ],
)
def test_queue_replays_control_after_target_persistence_failure(
    tmp_path: Path,
    action: str,
    persist_before_error: bool,
):
    data = {}
    started = threading.Event()
    target_write_failed = threading.Event()
    execute_calls = 0
    task_id = f"control-save-{action}-{int(persist_before_error)}"

    def targets_control_state(value):
        current = next(
            (
                item
                for item in _payload_items(value)
                if item["task_id"] == task_id
            ),
            None,
        )
        if action == "pause":
            return current is not None and current["state"] == "paused"
        return current is None

    def save(key, value):
        if targets_control_state(value) and not target_write_failed.is_set():
            if persist_before_error:
                data[key] = value
            target_write_failed.set()
            raise RuntimeError("temporary control-state persistence failure")
        data[key] = value

    queue = DownloadQueue(data.get, save, lambda *_: None)
    task = DownloadTask(
        task_id=task_id,
        source_key="lunatv",
        media_id=f"site:{task_id}",
        title="示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/control.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(task) is True

    def controlled_execute(_current: DownloadTask) -> str:
        nonlocal execute_calls
        execute_calls += 1
        started.set()
        assert queue._control_event.wait(timeout=2)
        raise downloader_module._QueueControl(action)

    queue._execute = controlled_execute
    assert queue.wake() is True
    assert started.wait(timeout=2)
    if action == "pause":
        assert queue.pause(task.task_id) is True
    else:
        assert queue.remove(task.task_id, delete_file=True) is True
    assert target_write_failed.wait(timeout=2)

    for _ in range(200):
        with queue._lock:
            if not queue._drain_running:
                break
        threading.Event().wait(0.01)

    with queue._lock:
        assert queue._drain_running is False
        assert queue._running is False
        assert queue._control_action == ""
        assert queue._current_task_id == ""
        assert task.task_id not in queue._delete_file_tasks
    assert execute_calls == 1
    if action == "pause":
        tasks = queue.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["state"] == "paused"
    else:
        assert queue.list_tasks() == []


def test_queue_stop_retries_interrupted_pause_persistence(tmp_path: Path):
    data = {}
    started = threading.Event()
    pause_write_failed = threading.Event()
    execute_calls = 0
    task_id = "stop-save-failure"

    def save(key, value):
        current = next(
            (
                item
                for item in _payload_items(value)
                if item["task_id"] == task_id
            ),
            None,
        )
        if (
            current is not None
            and current["state"] == "paused"
            and not pause_write_failed.is_set()
        ):
            pause_write_failed.set()
            raise RuntimeError("temporary stop persistence failure")
        data[key] = value

    queue = DownloadQueue(data.get, save, lambda *_: None)
    task = DownloadTask(
        task_id=task_id,
        source_key="lunatv",
        media_id=f"site:{task_id}",
        title="示例",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/stop.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(task) is True

    def controlled_execute(_current: DownloadTask) -> str:
        nonlocal execute_calls
        execute_calls += 1
        started.set()
        assert queue._control_event.wait(timeout=2)
        raise downloader_module._QueueControl("pause")

    queue._execute = controlled_execute
    assert queue.wake() is True
    assert started.wait(timeout=2)
    queue.stop()
    assert pause_write_failed.wait(timeout=2)

    for _ in range(200):
        with queue._lock:
            if not queue._drain_running:
                break
        threading.Event().wait(0.01)

    with queue._lock:
        assert queue._drain_running is False
        assert queue._control_action == ""
        assert queue._current_task_id == ""
    assert execute_calls == 1
    tasks = queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["state"] == "paused"


def test_queue_remove_running_task_wins_failure_race(tmp_path: Path):
    root = tmp_path / "downloads"
    output = root / "Movie 2026.mp4"
    part = Path(f"{output}.part")
    started = threading.Event()
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="running-failure-race",
        source_key="lunatv",
        media_id="site:running-failure-race",
        title="Movie",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/movie.m3u8",
        root=str(root),
    )
    queue.enqueue(task)

    def fails_after_remove(current: DownloadTask) -> str:
        output.parent.mkdir(parents=True)
        output.write_text("media", encoding="utf-8")
        part.write_text("partial", encoding="utf-8")
        current.output = str(output)
        started.set()
        assert queue._control_event.wait(timeout=2)
        raise RuntimeError("late ffmpeg failure")

    queue._execute = fails_after_remove
    result = {}
    worker = threading.Thread(target=lambda: result.update(queue.run_one()))
    worker.start()
    assert started.wait(timeout=2)
    assert queue.remove(task.task_id, delete_file=True) is True
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result["state"] == "remove"
    assert not output.exists()
    assert not part.exists()
    assert queue.list_tasks() == []




def test_queue_engine_cache_lifecycle_and_resume(monkeypatch, tmp_path: Path):
    playlist = tmp_path / "input.m3u8"
    playlist.write_text("#EXTM3U\\n#EXTINF:1,\\nsegment.ts\\n", encoding="utf-8")

    class CacheEngine:
        name = "cache-engine"

        def __init__(self, cache: Path, outcome: str):
            self.cache = cache
            self.outcome = outcome
            self.cleaned = 0

        def download(self, _url, output, **kwargs):
            self.cache.mkdir(parents=True, exist_ok=True)
            (self.cache / "segment-1").write_bytes(b"partial")
            if self.outcome == "failure":
                raise downloader_module.M3U8EngineError("failed")
            if self.outcome == "pause":
                kwargs["control_event"].set()
                raise downloader_module.M3U8EngineCancelled("paused")
            output.write_bytes(b"complete")
            return output

        def cleanup_task(self, *_args):
            self.cleaned += 1
            shutil.rmtree(self.cache, ignore_errors=True)

    def setup(outcome: str):
        data = {}
        queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, data_path=tmp_path / "data")
        task = DownloadTask(
            task_id="stable-cache-id",
            source_key="lunatv",
            media_id=f"site:{outcome}",
            title=f"Cache {outcome}",
            year="2026",
            media_type="movie",
            season=1,
            episode=1,
            url="https://example.test/cache.m3u8",
            root=str(tmp_path / outcome),
        )
        cache = tmp_path / "data" / "m3u8-cache" / task.task_id
        engine = CacheEngine(cache, outcome)
        queue._m3u8_engines = (engine,)
        monkeypatch.setattr(queue, "_prepare_hls_input", lambda *_args: str(playlist))
        return queue, task, engine, cache

    queue, task, engine, cache = setup("failure")
    assert queue.enqueue(task) is True
    assert queue.run_one()["state"] == "failed"
    assert cache.is_dir()
    assert engine.cleaned == 0
    assert queue.retry(task.task_id) is True
    assert cache.is_dir()

    queue, task, engine, cache = setup("pause")
    assert queue.enqueue(task) is True
    assert queue.run_one()["state"] == "pause"
    assert queue.list_tasks()[0]["state"] == "paused"
    assert cache.is_dir()
    assert engine.cleaned == 0

    queue, task, engine, cache = setup("success")
    assert queue.enqueue(task) is True
    assert queue.run_one()["state"] == "completed"
    assert not cache.exists()
    assert engine.cleaned == 1

    queue, task, engine, cache = setup("delete")
    cache.mkdir(parents=True)
    assert queue.enqueue(task) is True
    assert queue.remove(task.task_id) is True
    assert not cache.exists()
    assert engine.cleaned == 1


@pytest.mark.parametrize(
    ("store_key", "quarantine_key", "payload"),
    [
        (
            DownloadQueue.DATA_KEY,
            DownloadQueue.DATA_QUARANTINE_KEY,
            {"schema": 2, "items": []},
        ),
        (
            DownloadQueue.DATA_KEY,
            DownloadQueue.DATA_QUARANTINE_KEY,
            {"schema": 1, "items": [{"task_id": "broken"}]},
        ),
        (
            DownloadQueue.COMPLETION_OUTBOX_KEY,
            DownloadQueue.COMPLETION_OUTBOX_QUARANTINE_KEY,
            {"schema": 2, "items": []},
        ),
        (
            DownloadQueue.COMPLETION_OUTBOX_KEY,
            DownloadQueue.COMPLETION_OUTBOX_QUARANTINE_KEY,
            {"schema": 1, "items": [{"task": "broken"}]},
        ),
    ],
)
def test_corrupt_persistence_is_quarantined_and_fails_closed(
    store_key: str,
    quarantine_key: str,
    payload,
):
    data = {store_key: payload}

    with pytest.raises(ValueError, match="持久化数据损坏"):
        DownloadQueue(data.get, data.__setitem__, lambda *_args: None)

    assert data[store_key] == payload
    quarantine = data[quarantine_key]
    assert quarantine["schema"] == 1
    assert quarantine["source_key"] == store_key
    assert quarantine["payload"] == payload


def test_legacy_task_and_outbox_lists_remain_readable(tmp_path: Path):
    task = DownloadTask(
        task_id="legacy-outbox",
        source_key="lunatv",
        media_id="site:legacy-outbox",
        title="Legacy",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/legacy.m3u8",
        root=str(tmp_path),
        state="completed",
        progress=1.0,
        output=str(tmp_path / "legacy.mp4"),
    )
    data = {
        DownloadQueue.DATA_KEY: [task.to_dict()],
        DownloadQueue.COMPLETION_OUTBOX_KEY: [
            {"task": task.to_dict(), "output": task.output}
        ],
    }

    queue = DownloadQueue(data.get, data.__setitem__, lambda *_args: None)

    assert queue.list_tasks()[0]["task_id"] == task.task_id
    assert queue.finalizing_task_ids() == {task.task_id}
    assert DownloadQueue.DATA_QUARANTINE_KEY not in data
    assert DownloadQueue.COMPLETION_OUTBOX_QUARANTINE_KEY not in data


def test_terminal_pruning_cleans_cache_only_after_successful_save(tmp_path: Path):
    data = {}
    cleaned: list[str] = []

    class Engine:
        def cleanup_task(self, task_id: str, _parent=None):
            cleaned.append(task_id)

    def save(key, value):
        assert cleaned == []
        data[key] = value

    queue = DownloadQueue(data.get, save, lambda *_args: None)
    queue._m3u8_engines = (Engine(),)
    tasks = [
        DownloadTask(
            task_id=f"terminal-{index}",
            source_key="lunatv",
            media_id=f"site:terminal-{index}",
            title=f"Terminal {index}",
            year="2026",
            media_type="movie",
            season=1,
            episode=index + 1,
            url=f"https://example.test/{index}.m3u8",
            root=str(tmp_path),
            state="completed",
        )
        for index in range(501)
    ]

    queue._write(tasks)

    assert data[queue.DATA_KEY]["schema"] == 1
    assert len(data[queue.DATA_KEY]["items"]) == 500
    assert cleaned == ["terminal-0"]

    cleaned.clear()
    queue._save = lambda *_args: (_ for _ in ()).throw(RuntimeError("save failed"))
    with pytest.raises(RuntimeError, match="save failed"):
        queue._write(tasks)
    assert cleaned == []


def test_startup_removes_only_unreferenced_controlled_cache(tmp_path: Path):
    data_path = tmp_path / "data"
    engine = downloader_module.N_m3u8DLEngine(data_path)
    task = DownloadTask(
        task_id="referenced-cache",
        source_key="lunatv",
        media_id="site:referenced-cache",
        title="Referenced",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/referenced.m3u8",
        root=str(tmp_path),
    )
    referenced = engine.task_cache_dir(task.task_id)
    orphan = engine.task_cache_dir("orphan-cache")
    unmanaged = data_path / "m3u8-cache" / "notes"
    referenced.mkdir(parents=True)
    orphan.mkdir(parents=True)
    unmanaged.mkdir(parents=True)
    data = {DownloadQueue.DATA_KEY: [task.to_dict()]}

    DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_args: None,
        data_path=data_path,
    )

    assert referenced.is_dir()
    assert not orphan.parent.exists()
    assert unmanaged.is_dir()


def test_startup_recovery_finishes_applied_remove_after_save_error(tmp_path: Path):
    data_path = tmp_path / "data"
    output = tmp_path / "downloads" / "removed.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"media")
    task = DownloadTask(
        task_id="startup-applied-remove",
        source_key="lunatv",
        media_id="site:startup-applied-remove",
        title="Removed",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/remove.m3u8",
        root=str(tmp_path / "downloads"),
        state="running",
        control_action="remove",
        delete_file=True,
        output=str(output),
    )
    cache = downloader_module.N_m3u8DLEngine(data_path).task_cache_dir(task.task_id)
    cache.mkdir(parents=True)
    (cache / "segment.ts").write_bytes(b"partial")
    data = {DownloadQueue.DATA_KEY: [task.to_dict()]}
    failed = False

    def save(key, value):
        nonlocal failed
        data[key] = value
        if key == DownloadQueue.DATA_KEY and not _payload_items(value) and not failed:
            failed = True
            raise RuntimeError("save reported failure after commit")

    queue = DownloadQueue(
        data.get,
        save,
        lambda *_args: None,
        data_path=data_path,
    )

    assert queue.list_tasks() == []
    assert not output.exists()
    assert not cache.exists()


def test_failed_task_redacts_persisted_notified_and_returned_error(tmp_path: Path):
    data = {}
    notifications = []
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda title, body: notifications.append((title, body)),
    )
    task = DownloadTask(
        task_id="redacted-failure",
        source_key="lunatv",
        media_id="site:redacted-failure",
        title="Redacted",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://example.test/redacted.m3u8",
        root=str(tmp_path),
    )
    assert queue.enqueue(task)
    queue._execute = lambda _task: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError(
            "failed https://alice:password@example.test/video.m3u8"
            "?token=secret#fragment"
        )
    )

    result = queue.run_one()

    expected = "failed https://example.test/video.m3u8"
    assert result["error"] == expected
    assert queue.list_tasks()[0]["error"] == expected
    assert _payload_items(data[queue.DATA_KEY])[0]["error"] == expected
    assert notifications == [("LunaTV 下载失败", f"Redacted：{expected}")]


def test_prepare_hls_input_skips_bad_variant_and_reports_all_failures(
    monkeypatch, tmp_path: Path
):
    playlists = {
        "https://media.example/master.m3u8": b"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1
bad.m3u8?token=variant-secret
#EXT-X-STREAM-INF:BANDWIDTH=2
good.m3u8
""",
        "https://media.example/bad.m3u8?token=variant-secret": b"not a playlist",
        "https://media.example/good.m3u8": (
            b"#EXTM3U\n#EXTINF:1,\ngood.ts\n#EXT-X-ENDLIST\n"
        ),
    }
    monkeypatch.setattr(
        downloader_module,
        "_fetch_public_url",
        lambda url, *_args, **_kwargs: (playlists[url], url),
    )

    local = DownloadQueue._prepare_hls_input(
        "https://media.example/master.m3u8", tmp_path
    )
    content = Path(local).read_text(encoding="utf-8")
    assert "BANDWIDTH=1" not in content
    assert "BANDWIDTH=2" in content

    playlists["https://media.example/master.m3u8"] = b"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1
bad.m3u8?token=variant-secret
"""
    with pytest.raises(RuntimeError, match="所有 variant.*bad.m3u8.*不是有效 m3u8") as exc:
        DownloadQueue._prepare_hls_input(
            "https://media.example/master.m3u8", tmp_path
        )
    assert "variant-secret" not in str(exc.value)


def test_prepare_hls_input_expands_define_variables_before_safe_url_mapping(
    monkeypatch, tmp_path: Path
):
    playlists = {
        "https://media.example/master.m3u8": b"""#EXTM3U
#EXT-X-DEFINE:NAME="variant",VALUE="video"
#EXT-X-DEFINE:NAME="asset",VALUE="assets"
#EXT-X-STREAM-INF:BANDWIDTH=1
{$variant}/index.m3u8
""",
        "https://media.example/video/index.m3u8": b"""#EXTM3U
#EXT-X-DEFINE:IMPORT="asset"
#EXT-X-KEY:METHOD=AES-128,URI="{$asset}/key.bin"
#EXT-X-MAP:URI="{$asset}/init.mp4"
#EXT-X-PART:DURATION=0.5,URI="{$asset}/part.m4s"
#EXTINF:1,
{$asset}/segment.m4s
#EXT-X-ENDLIST
""",
    }
    fetched = []
    mapped = []

    def fetch(url, *_args, **_kwargs):
        fetched.append(url)
        return playlists[url], url

    monkeypatch.setattr(downloader_module, "_fetch_public_url", fetch)
    DownloadQueue._prepare_hls_input(
        "https://media.example/master.m3u8",
        tmp_path,
        lambda url: mapped.append(url) or f"mapped:{len(mapped)}",
    )

    assert fetched == [
        "https://media.example/master.m3u8",
        "https://media.example/video/index.m3u8",
    ]
    assert mapped == [
        "https://media.example/video/assets/key.bin",
        "https://media.example/video/assets/init.mp4",
        "https://media.example/video/assets/part.m4s",
        "https://media.example/video/assets/segment.m4s",
    ]

    playlists["https://media.example/master.m3u8"] = (
        b"#EXTM3U\n#EXTINF:1,\n{$missing}/segment.ts\n#EXT-X-ENDLIST\n"
    )
    fetched.clear()
    with pytest.raises(RuntimeError, match="未定义变量.*missing"):
        DownloadQueue._prepare_hls_input(
            "https://media.example/master.m3u8", tmp_path
        )
    assert fetched == ["https://media.example/master.m3u8"]

    playlists["https://media.example/master.m3u8"] = (
        b'#EXTM3U\n#EXT-X-DEFINE:IMPORT="missing"\n'
        b'#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n'
    )
    with pytest.raises(RuntimeError, match="未定义 IMPORT.*missing"):
        DownloadQueue._prepare_hls_input(
            "https://media.example/master.m3u8", tmp_path
        )


def test_prepare_hls_input_retries_only_transient_fetch_failures(
    monkeypatch, tmp_path: Path
):
    attempts = []

    def transient(url, *_args, **_kwargs):
        attempts.append(url)
        if len(attempts) == 1:
            raise TimeoutError("temporary timeout")
        return b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n", url

    monkeypatch.setattr(downloader_module, "_fetch_public_url", transient)
    assert Path(
        DownloadQueue._prepare_hls_input(
            "https://media.example/retry.m3u8", tmp_path
        )
    ).exists()
    assert len(attempts) == 2

    attempts.clear()

    def wrapped_dns(url, *_args, **_kwargs):
        attempts.append(url)
        if len(attempts) == 1:
            raise ValueError("probe host cannot resolved") from OSError(
                "temporary DNS failure"
            )
        return b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n", url

    monkeypatch.setattr(downloader_module, "_fetch_public_url", wrapped_dns)
    assert Path(
        DownloadQueue._prepare_hls_input(
            "https://media.example/dns-retry.m3u8", tmp_path
        )
    ).exists()
    assert len(attempts) == 2

    attempts.clear()

    def permanent(url, *_args, **_kwargs):
        attempts.append(url)
        raise OSError("probe request returned HTTP 404")

    monkeypatch.setattr(downloader_module, "_fetch_public_url", permanent)
    with pytest.raises(OSError, match="HTTP 404"):
        DownloadQueue._prepare_hls_input(
            "https://media.example/missing.m3u8", tmp_path
        )
    assert len(attempts) == 1

    attempts.clear()

    def unsafe_value_error(url, *_args, **_kwargs):
        attempts.append(url)
        raise ValueError("non-public redirect target")

    monkeypatch.setattr(
        downloader_module, "_fetch_public_url", unsafe_value_error
    )
    with pytest.raises(ValueError, match="non-public"):
        DownloadQueue._prepare_hls_input(
            "https://media.example/unsafe.m3u8", tmp_path
        )
    assert len(attempts) == 1


def test_media_commit_rejects_parent_swapped_to_symlink(
    monkeypatch, tmp_path: Path
):
    root = tmp_path / "downloads"
    outside = tmp_path / "outside"
    outside.mkdir()
    stage = tmp_path / "data" / "m3u8-cache" / "task" / "stage" / "media.mp4"
    stage.parent.mkdir(parents=True)
    stage.write_bytes(b"media")
    queue = DownloadQueue({}.get, lambda *_args: None, lambda *_args: None)
    task = DownloadTask(
        task_id="commit-symlink-swap",
        source_key="lunatv",
        media_id="site:commit-symlink-swap",
        title="Swap",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url="https://media.example/index.m3u8",
        root=str(root),
    )
    monkeypatch.setattr(queue, "_run_m3u8_engines", lambda *_args: stage)
    _root, destination = queue._destination_for_task(task)
    detached = tmp_path / "detached-parent"
    real_replace = downloader_module.os.replace
    swapped = False

    def replace(source, target, *args, **kwargs):
        nonlocal swapped
        if kwargs.get("dst_dir_fd") is not None and not swapped:
            swapped = True
            destination.parent.rename(detached)
            destination.parent.symlink_to(outside, target_is_directory=True)
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(downloader_module.os, "replace", replace)

    with pytest.raises(OSError, match="目标目录.*变化"):
        queue._execute(task)

    assert stage.read_bytes() == b"media"
    assert not (outside / destination.name).exists()
    assert not (detached / destination.name).exists()
