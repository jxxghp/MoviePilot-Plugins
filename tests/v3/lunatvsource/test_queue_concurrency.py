import threading
import time
from pathlib import Path

import pytest

import app.plugins.lunatvsource.downloader as downloader_module
from app.plugins.lunatvsource.downloader import DownloadQueue, DownloadTask


def make_task(task_id: str, root: Path) -> DownloadTask:
    return DownloadTask(
        task_id=task_id,
        source_key="lunatv",
        media_id=f"site:{task_id}",
        title=f"任务 {task_id}",
        year="2026",
        media_type="movie",
        season=1,
        episode=1,
        url=f"https://example.test/{task_id}.m3u8",
        root=str(root),
    )


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def test_queue_runs_bounded_parallel_tasks_and_leaves_third_pending(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, max_concurrent_tasks=2)
    for task_id in ("a", "b", "c"):
        assert queue.enqueue(make_task(task_id, tmp_path))

    started: set[str] = set()
    release = threading.Event()
    started_lock = threading.Lock()

    def execute(task: DownloadTask) -> str:
        with started_lock:
            started.add(task.task_id)
        assert release.wait(2)
        return str(tmp_path / f"{task.task_id}.mp4")

    queue._execute = execute  # type: ignore[method-assign]
    assert queue.wake()
    wait_until(lambda: len(started) == 2)
    assert queue.summary()["running"] == 2
    assert queue.summary()["pending"] == 1
    assert "c" not in started
    release.set()
    wait_until(lambda: queue.summary()["completed"] == 3)


def test_queue_serializes_tasks_that_share_one_destination(tmp_path: Path):
    data = {}
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        max_concurrent_tasks=2,
    )
    first = make_task("same-one", tmp_path)
    second = make_task("same-two", tmp_path)
    second.title = first.title
    second.year = first.year
    second.media_type = first.media_type
    second.season = first.season
    second.episode = first.episode
    assert queue.enqueue(first)
    assert queue.enqueue(second)

    started: list[str] = []
    started_lock = threading.Lock()
    leader_started = threading.Event()
    follower_started = threading.Event()
    release_leader = threading.Event()

    def execute(task: DownloadTask) -> str:
        with started_lock:
            started.append(task.task_id)
            is_leader = len(started) == 1
            if is_leader:
                leader_started.set()
            else:
                follower_started.set()
        if is_leader:
            assert release_leader.wait(timeout=2)
        return str(tmp_path / "shared.mp4")

    queue._execute = execute  # type: ignore[method-assign]
    assert queue.wake()
    assert leader_started.wait(timeout=2)
    time.sleep(0.05)
    assert not follower_started.is_set()
    assert queue.summary()["running"] == 1
    assert queue.summary()["pending"] == 1

    release_leader.set()
    assert follower_started.wait(timeout=2)
    wait_until(lambda: queue.summary()["completed"] == 2)


def test_queue_max_four_refills_a_slot_when_one_task_finishes(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, max_concurrent_tasks=4)
    for task_id in ("a", "b", "c", "d", "e"):
        assert queue.enqueue(make_task(task_id, tmp_path))
    started: list[str] = []
    started_lock = threading.Lock()
    finish_first = threading.Event()
    release_rest = threading.Event()

    def execute(task: DownloadTask) -> str:
        with started_lock:
            started.append(task.task_id)
        if task.task_id == "a":
            assert finish_first.wait(2)
        else:
            assert release_rest.wait(2)
        return str(tmp_path / f"{task.task_id}.mp4")

    queue._execute = execute  # type: ignore[method-assign]
    assert queue.wake()
    wait_until(lambda: len(started) == 4)
    assert set(started) == {"a", "b", "c", "d"}
    finish_first.set()
    wait_until(lambda: "e" in started)
    release_rest.set()
    wait_until(lambda: queue.summary()["completed"] == 5)


def test_queue_pause_and_remove_are_isolated_per_running_task(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, max_concurrent_tasks=2)
    assert queue.enqueue(make_task("pause", tmp_path))
    assert queue.enqueue(make_task("remove", tmp_path))
    started = threading.Event()
    running = 0
    running_lock = threading.Lock()

    def execute(_task: DownloadTask) -> str:
        nonlocal running
        with running_lock:
            running += 1
            if running == 2:
                started.set()
        assert queue._control_event.wait(2)
        raise downloader_module._QueueControl("controlled")

    queue._execute = execute  # type: ignore[method-assign]
    assert queue.wake()
    assert started.wait(2)
    assert queue.pause("pause")
    assert queue.remove("remove")
    wait_until(lambda: queue.summary()["paused"] == 1 and len(queue.list_tasks()) == 1)
    remaining = queue.list_tasks()[0]
    assert remaining["task_id"] == "pause"
    assert remaining["state"] == "paused"


def test_queue_concurrent_completion_rereads_persisted_tasks(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, max_concurrent_tasks=2)
    assert queue.enqueue(make_task("one", tmp_path))
    assert queue.enqueue(make_task("two", tmp_path))
    both_executing = threading.Barrier(2)
    release = threading.Event()

    def execute(task: DownloadTask) -> str:
        both_executing.wait(timeout=2)
        assert release.wait(2)
        return str(tmp_path / f"{task.task_id}.mp4")

    queue._execute = execute  # type: ignore[method-assign]
    first = threading.Thread(target=queue.run_one)
    second = threading.Thread(target=queue.run_one)
    first.start()
    second.start()
    wait_until(lambda: queue.summary()["running"] == 2)
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive() and not second.is_alive()
    tasks = {item["task_id"]: item for item in queue.list_tasks()}
    assert set(tasks) == {"one", "two"}
    assert {item["state"] for item in tasks.values()} == {"completed"}


def test_queue_stop_broadcasts_only_active_tasks_and_never_starts_pending(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, max_concurrent_tasks=2)
    for task_id in ("one", "two", "three"):
        assert queue.enqueue(make_task(task_id, tmp_path))
    started = threading.Event()
    active = 0
    active_lock = threading.Lock()

    def execute(_task: DownloadTask) -> str:
        nonlocal active
        with active_lock:
            active += 1
            if active == 2:
                started.set()
        assert queue._control_event.wait(2)
        raise downloader_module._QueueControl("controlled")

    queue._execute = execute  # type: ignore[method-assign]
    assert queue.wake()
    assert started.wait(2)
    assert queue.stop_and_wait(timeout=2)
    assert queue.summary()["paused"] == 2
    tasks = {item["task_id"]: item for item in queue.list_tasks()}
    assert tasks["three"]["state"] == "pending"
    assert queue.wake() is False


def test_queue_n_engine_failure_never_falls_back_to_plugin_ffmpeg(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, data_path=tmp_path)
    task = make_task("n-fails", tmp_path / "library")
    assert queue.enqueue(task)
    queue._run_m3u8_engines = lambda *_: False  # type: ignore[method-assign]
    assert not hasattr(queue, "_run_ffmpeg")
    result = queue.run_one()
    assert result["state"] == "failed"
    stored = queue.list_tasks()[0]
    assert stored["download_engine"] == "N_m3u8DL-RE"
    assert "N_m3u8DL-RE" in stored["error"]


def test_queue_counts_only_its_controlled_task_cache(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None, data_path=tmp_path)
    engine = queue._m3u8_engines[0]
    controlled = engine.task_cache_dir("safe-size")
    controlled.mkdir(parents=True)
    (controlled / "piece.bin").write_bytes(b"12345")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    (controlled / "outside-link").symlink_to(outside)
    assert queue.task_cache_size("safe-size") == 5
    assert queue.task_cache_size("") == 0


def test_queue_clamps_invalid_concurrency_and_segment_settings(tmp_path: Path):
    queue = DownloadQueue(
        lambda *_: [],
        lambda *_: None,
        lambda *_: None,
        data_path=tmp_path,
        max_concurrent_tasks="not-a-number",
        segment_thread_count=None,
    )
    assert queue.max_concurrent_tasks == 2
    assert queue.segment_thread_count == 16

    clamped = DownloadQueue(
        lambda *_: [],
        lambda *_: None,
        lambda *_: None,
        max_concurrent_tasks=999,
        segment_thread_count=1,
    )
    assert clamped.max_concurrent_tasks == 4
    assert clamped.segment_thread_count == 4

    budgeted = DownloadQueue(
        lambda *_: [],
        lambda *_: None,
        lambda *_: None,
        max_concurrent_tasks=4,
        segment_thread_count=32,
    )
    assert budgeted.max_concurrent_tasks == 4
    assert budgeted.segment_thread_count == 16


def test_queue_worker_start_failure_releases_reserved_slot(monkeypatch, tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = make_task("start-failure", tmp_path)
    assert queue.enqueue(task)
    queue._execute = lambda current: str(tmp_path / f"{current.task_id}.mp4")  # type: ignore[method-assign]

    original_thread = downloader_module.threading.Thread

    class StartFailsForWorker:
        def __init__(self, *args, **kwargs):
            self._thread = original_thread(*args, **kwargs)

        def start(self):
            if self._thread.name == "lunatvsource-download-worker":
                raise RuntimeError("worker start failed")
            return self._thread.start()

    monkeypatch.setattr(downloader_module.threading, "Thread", StartFailsForWorker)
    assert queue.wake()
    wait_until(lambda: not queue._drain_running)
    assert queue.wait_until_idle(timeout=0.5)
    with queue._lock:
        assert queue._dispatching == 0
        assert not queue._active

    monkeypatch.setattr(downloader_module.threading, "Thread", original_thread)
    assert queue.wake()
    wait_until(lambda: queue.summary()["completed"] == 1)


@pytest.mark.parametrize("transition", ["retry", "resume"])
def test_queue_retry_and_resume_wake_scheduler(tmp_path: Path, transition: str):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = make_task(f"wake-{transition}", tmp_path)
    assert queue.enqueue(task)

    if transition == "retry":
        queue._execute = lambda _task: (_ for _ in ()).throw(RuntimeError("failed"))  # type: ignore[method-assign]
        assert queue.run_one()["state"] == "failed"
        queue._execute = lambda current: str(tmp_path / f"{current.task_id}.mp4")  # type: ignore[method-assign]
        assert queue.retry(task.task_id)
    else:
        assert queue.pause(task.task_id)
        queue._execute = lambda current: str(tmp_path / f"{current.task_id}.mp4")  # type: ignore[method-assign]
        assert queue.resume(task.task_id)

    wait_until(lambda: queue.summary()["completed"] == 1)


def test_terminal_replay_failure_does_not_self_wake_or_release_destination(
    monkeypatch,
    tmp_path: Path,
):
    queue = DownloadQueue(lambda *_: [], lambda *_: None, lambda *_: None)
    task = make_task("terminal-wait", tmp_path)
    control = downloader_module._TaskControl()
    queue._pending_terminal[task.task_id] = downloader_module._TerminalIntent(
        task=task,
        control=control,
        state="completed",
        output=str(tmp_path / "done.mp4"),
    )
    destination_key = queue._destination_key(task)
    queue._active_destinations[task.task_id] = destination_key
    queue._drain_wakeup.clear()

    def fail_persist(_intent):
        raise RuntimeError("terminal persistence unavailable")

    monkeypatch.setattr(queue, "_persist_terminal_intent", fail_persist)
    queue._replay_terminal_intents()

    assert task.task_id in queue._pending_terminal
    assert queue._active_destinations[task.task_id] == destination_key
    assert not queue._drain_wakeup.is_set()


def test_deferred_completion_holds_destination_until_callback_finishes(
    monkeypatch,
    tmp_path: Path,
):
    data = {}
    callback_entered = threading.Event()
    release_callback = threading.Event()

    def on_complete(_task: DownloadTask, _output: str) -> None:
        callback_entered.set()
        assert release_callback.wait(timeout=2)

    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        on_complete=on_complete,
        max_concurrent_tasks=2,
    )
    first = make_task("deferred-first", tmp_path)
    second = make_task("deferred-second", tmp_path)
    second.title = first.title
    second.year = first.year
    second.media_type = first.media_type
    second.season = first.season
    second.episode = first.episode
    data[queue.DATA_KEY] = [second.to_dict()]

    control = downloader_module._TaskControl()
    queue._pending_terminal[first.task_id] = downloader_module._TerminalIntent(
        task=first,
        control=control,
        state="completed",
        output=str(tmp_path / "done.mp4"),
    )
    queue._active_destinations[first.task_id] = queue._destination_key(first)
    monkeypatch.setattr(queue, "_persist_terminal_intent", lambda _intent: None)

    replay = threading.Thread(target=queue._replay_terminal_intents)
    replay.start()
    assert callback_entered.wait(timeout=2)
    assert queue._claim_next() is None

    release_callback.set()
    replay.join(timeout=2)
    assert not replay.is_alive()
    claimed = queue._claim_next()
    assert claimed is not None
    assert claimed[0].task_id == second.task_id


@pytest.mark.parametrize(
    ("terminal", "expected_state"),
    [
        ("pause", "paused"),
        ("remove", "removed"),
        ("failed", "failed"),
        ("completed", "completed"),
    ],
)
def test_queue_replays_unpersisted_terminal_without_rerunning_task(
    tmp_path: Path,
    terminal: str,
    expected_state: str,
):
    data = {}
    persist_terminal = False
    first_id = f"terminal-{terminal}"

    def save(key, value):
        first = next((item for item in value if item["task_id"] == first_id), None)
        terminal_write = (
            first is None
            if terminal == "remove"
            else first is not None and first["state"] == expected_state
        )
        if terminal_write and not persist_terminal:
            raise RuntimeError("terminal persistence unavailable")
        data[key] = value

    queue = DownloadQueue(data.get, save, lambda *_: None)
    first = make_task(first_id, tmp_path)
    second = make_task(f"after-{terminal}", tmp_path)
    assert queue.enqueue(first)
    assert queue.enqueue(second)
    runs = {first.task_id: 0, second.task_id: 0}

    def execute(task: DownloadTask) -> str:
        runs[task.task_id] += 1
        if task.task_id != first.task_id:
            return str(tmp_path / f"{task.task_id}.mp4")
        if terminal in {"pause", "remove"}:
            raise downloader_module._QueueControl(terminal)
        if terminal == "failed":
            raise RuntimeError("download failed")
        return str(tmp_path / f"{task.task_id}.mp4")

    queue._execute = execute  # type: ignore[method-assign]
    assert queue.wake()
    wait_until(lambda: queue.summary()["completed"] == 1)
    wait_until(lambda: first.task_id in queue._pending_terminal)
    assert runs[first.task_id] == 1
    assert queue.wait_until_idle(timeout=0.05) is False

    # A failed hot-reload shutdown must retain a usable queue for replay.
    assert queue.stop_and_wait(timeout=0.05) is False
    with queue._lock:
        assert queue._stop is False
        assert first.task_id in queue._pending_terminal

    persist_terminal = True
    assert queue.wake()
    wait_until(lambda: first.task_id not in queue._pending_terminal)
    assert queue.wait_until_idle(timeout=1)
    assert runs[first.task_id] == 1

    tasks = {item["task_id"]: item for item in queue.list_tasks()}
    if terminal == "remove":
        assert first.task_id not in tasks
    else:
        assert tasks[first.task_id]["state"] == expected_state


def test_failed_task_reenqueue_reuses_existing_record(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    failed = make_task("retry-same", tmp_path)
    failed.state = "failed"
    failed.progress = 0.4
    failed.error = "first attempt failed"
    data[queue.DATA_KEY] = [failed.to_dict()]

    replacement = make_task("retry-same", tmp_path / "new-root")
    assert queue.enqueue(replacement) is True

    tasks = queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == failed.task_id
    assert tasks[0]["state"] == "pending"
    assert tasks[0]["progress"] == 0.0
    assert tasks[0]["error"] == ""
    assert tasks[0]["root"] == replacement.root


def test_startup_recovery_removes_duplicate_task_ids_and_keeps_completion(
    tmp_path: Path,
):
    completed = make_task("duplicate", tmp_path)
    completed.state = "completed"
    completed.progress = 1.0
    completed.output = str(tmp_path / "duplicate.mp4")
    completed.error = "stale error"
    completed.completed_at = time.time()

    ghost = make_task("duplicate", tmp_path)
    ghost.state = "running"
    ghost.created_at = completed.created_at + 1
    data = {
        DownloadQueue.DATA_KEY: [completed.to_dict(), ghost.to_dict()],
    }

    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)

    tasks = queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == completed.task_id
    assert tasks[0]["state"] == "completed"
    assert tasks[0]["progress"] == 1.0
    assert tasks[0]["output"] == completed.output
    assert tasks[0]["error"] == ""


def test_failed_reenqueue_racing_claim_keeps_one_task_record(tmp_path: Path):
    data = {}
    failed = make_task("retry-race", tmp_path)
    failed.state = "failed"
    failed.error = "temporary failure"
    data[DownloadQueue.DATA_KEY] = [failed.to_dict()]
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    start = threading.Barrier(3)
    results = {}

    def reenqueue() -> None:
        start.wait()
        results["enqueued"] = queue.enqueue(make_task("retry-race", tmp_path))

    def claim() -> None:
        start.wait()
        results["claimed"] = queue._claim_next()

    enqueue_thread = threading.Thread(target=reenqueue)
    claim_thread = threading.Thread(target=claim)
    enqueue_thread.start()
    claim_thread.start()
    start.wait()
    enqueue_thread.join(timeout=2)
    claim_thread.join(timeout=2)

    assert not enqueue_thread.is_alive()
    assert not claim_thread.is_alive()
    assert results["enqueued"] is True
    tasks = queue._read()
    assert len(tasks) == 1
    assert tasks[0].task_id == failed.task_id
    assert tasks[0].state in {"pending", "running"}
    claimed = results["claimed"]
    if claimed is not None:
        assert claimed[0].task_id == failed.task_id


def test_startup_recovery_collapses_different_ids_for_same_episode(tmp_path: Path):
    completed = make_task("completed-id", tmp_path)
    completed.source_key = "cms-demo"
    completed.media_id = "cms-demo:old-row"
    completed.host_media_source = "themoviedb"
    completed.host_media_id = "1234"
    completed.media_type = "tv"
    completed.season = 1
    completed.episode = 3
    completed.state = "completed"
    completed.progress = 1.0
    completed.output = str(tmp_path / "completed.mp4")

    ghost = make_task("ghost-id", tmp_path)
    ghost.source_key = "cms-demo"
    ghost.media_id = "cms-demo:new-row"
    ghost.host_media_source = "themoviedb"
    ghost.host_media_id = "1234"
    ghost.media_type = "tv"
    ghost.season = 1
    ghost.episode = 3
    ghost.state = "running"
    ghost.created_at = completed.created_at + 1

    data = {DownloadQueue.DATA_KEY: [completed.to_dict(), ghost.to_dict()]}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_args: None)

    tasks = queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == completed.task_id
    assert tasks[0]["state"] == "completed"
