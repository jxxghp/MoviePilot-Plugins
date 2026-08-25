import http.server
import shutil
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

    persisted = data[queue.DATA_KEY]
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
        for item in data[queue.DATA_KEY]
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

    assert queue.retry(task.task_id) is True
    retried = queue.list_tasks()[0]
    assert retried["state"] == "pending"
    assert retried["progress"] == 0.0
    assert retried["error"] == ""


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
    assert queue.list_tasks()[0]["state"] == "pending"
    assert queue.remove(task.task_id) is True
    assert queue.list_tasks() == []


def test_queue_clears_stale_progress_during_pending_pause_and_resume(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="pending-stale",
        source_key="lunatv",
        media_id="site:pending-stale",
        title="排队示例",
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

    data["download_tasks_v1"][0]["progress"] = 0.3846
    assert queue.resume(task.task_id) is True
    assert queue.list_tasks()[0]["state"] == "pending"
    assert queue.list_tasks()[0]["progress"] == 0.0


def test_queue_safely_pauses_running_task(tmp_path: Path, monkeypatch):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="running-control", source_key="lunatv", media_id="site:running",
        title="示例", year="2026", media_type="movie", season=1, episode=1,
        url="https://example.test/running.m3u8", root=str(tmp_path),
    )
    assert queue.enqueue(task) is True
    executing = threading.Event()

    def controlled_ffmpeg(_ffmpeg_path, _url, output, control_event, progress_callback):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("partial", encoding="utf-8")
        assert progress_callback is not None
        progress_callback(0.3846)
        executing.set()
        assert control_event is not None
        assert control_event.wait(timeout=2)
        raise downloader_module._QueueControl("controlled")

    monkeypatch.setattr(DownloadQueue, "_run_ffmpeg", staticmethod(controlled_ffmpeg))
    result = {}
    worker = threading.Thread(target=lambda: result.update(queue.run_one()))
    worker.start()
    assert executing.wait(timeout=2)
    assert queue.pause(task.task_id) is True
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result["state"] == "pause"
    paused_task = queue.list_tasks()[0]
    assert paused_task["state"] == "paused"
    assert paused_task["progress"] == 0.0
    assert list(tmp_path.rglob("*.part")) == []


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


def test_queue_persists_active_ffmpeg_progress(tmp_path: Path):
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
    raw[0]["state"] = "running"
    data[queue.DATA_KEY] = raw
    queue._update_progress(task.task_id, 0.42)
    assert queue.list_tasks()[0]["progress"] == 0.42
    queue._update_progress(task.task_id, 1.5)
    assert queue.list_tasks()[0]["progress"] == 0.99


def test_ffmpeg_explicitly_sets_mp4_muxer_for_part_file(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(downloader_module.subprocess, "run", fake_run)
    monkeypatch.setattr(DownloadQueue, "_prepare_hls_input", lambda url, _temp, *_args: url)
    DownloadQueue._run_ffmpeg("ffmpeg", "https://example.test/video.m3u8", tmp_path / "movie.mp4.part")
    command = captured["command"]
    assert command[command.index("-f") + 1] == "mp4"
    assert command[command.index("-allowed_segment_extensions") + 1] == "ALL"
    assert command[command.index("-extension_picky") + 1] == "0"
    assert command[command.index("-seg_max_retry") + 1] == "2"


def test_playlist_duration_estimates_media_playlist_for_progress(tmp_path: Path):
    playlist = tmp_path / "index.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXTINF:10.5,\nsegment-1.ts\n#EXTINF:12,\nsegment-2.ts\n",
        encoding="utf-8",
    )
    assert DownloadQueue._playlist_duration(playlist) == 22.5


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
        with _SegmentProxy() as proxy, urllib.request.urlopen(proxy.url_for(remote), timeout=5) as response:
            assert response.headers.get_content_type() == "video/mp2t"
            assert response.read() == packet * 3
    finally:
        source.shutdown()
        source.server_close()
        thread.join(timeout=2)


def test_prepare_hls_input_decodes_zstd_and_absolutizes_urls(monkeypatch, tmp_path: Path):
    class Headers:
        @staticmethod
        def get(name):
            return "zstd" if name == "Content-Encoding" else None

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def read():
            return b"compressed"

    playlist = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:10,\nsegment.ts\n'
    monkeypatch.setattr(downloader_module.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(DownloadQueue, "_decompress_zstd", lambda payload: playlist)

    local = DownloadQueue._prepare_hls_input("https://media.example/path/index.m3u8", tmp_path)
    content = Path(local).read_text(encoding="utf-8")
    assert 'URI="https://media.example/path/key.bin"' in content
    assert "https://media.example/path/segment.ts" in content


def test_failed_download_removes_only_new_empty_directories(tmp_path: Path, monkeypatch):
    root = tmp_path / "incoming"
    root.mkdir()
    task = DownloadTask(
        task_id="failed-cleanup", source_key="lunatv", media_id="site:4",
        title="测试电影", year="2026", media_type="movie", season=1, episode=1,
        url="https://example.test/video.m3u8", root=str(root),
    )
    queue = DownloadQueue(lambda *_: [], lambda *_: None, lambda *_: None)

    def fail(*_args, **_kwargs):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(queue, "_run_ffmpeg", fail)
    with pytest.raises(RuntimeError, match="source unavailable"):
        queue._execute(task)

    assert root.exists()
    assert list(root.iterdir()) == []


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
        if not any(item["task_id"] == task.task_id for item in value):
            if persist_before_error:
                data[key] = value
            raise RuntimeError("simulated removal persistence failure")
        data[key] = value

    queue._save = fail_removal_write

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
        if fail_running_save and any(item["state"] == "running" for item in value):
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
    assert data[queue.DATA_KEY][0]["state"] == "pending"

    assert queue.wake() is True
    assert completed.wait(timeout=2)
    assert queue.summary()["completed"] == 1

def test_queue_wake_during_drain_failure_is_not_lost(tmp_path: Path):
    data = {}
    completed = threading.Event()
    queue = DownloadQueue(
        data.get,
        data.__setitem__,
        lambda *_: None,
        on_complete=lambda *_: completed.set(),
    )
    task = DownloadTask(
        task_id="wake-during-drain-failure",
        source_key="lunatv",
        media_id="site:wake-during-drain-failure",
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
    original_drain = queue._drain_until_idle
    attempts = 0

    def flaky_drain() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_attempt.set()
            assert release_failure.wait(timeout=2)
            raise RuntimeError("temporary drain failure")
        retried.set()
        original_drain()

    queue._drain_until_idle = flaky_drain
    assert queue.wake() is True
    assert first_attempt.wait(timeout=2)
    assert queue.wake() is True
    release_failure.set()

    assert retried.wait(timeout=2)
    assert completed.wait(timeout=2)
    assert queue.summary()["completed"] == 1

def test_ffmpeg_uses_hls_http_options_and_mp4_muxer(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(downloader_module.subprocess, "run", fake_run)
    monkeypatch.setattr(DownloadQueue, "_prepare_hls_input", lambda url, _temp, *_args: url)
    DownloadQueue._run_ffmpeg("ffmpeg", "https://example.test/video.m3u8", tmp_path / "movie.mp4.part")
    command = captured["command"]
    assert command[command.index("-f") + 1] == "mp4"
    assert command[command.index("-allowed_segment_extensions") + 1] == "ALL"
    assert command[command.index("-extension_picky") + 1] == "0"
    assert command[command.index("-seg_max_retry") + 1] == "2"
    assert command[command.index("-http_persistent") + 1] == "1"
    assert command[command.index("-http_multiple") + 1] == "1"
    assert command[command.index("-http_seekable") + 1] == "0"
    assert "-multiple_requests" not in command
    assert "-seekable" not in command

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")
def test_run_ffmpeg_materializes_http_playlist_with_hls_http_options(
    monkeypatch,
    tmp_path: Path,
):
    ffmpeg_path = shutil.which("ffmpeg")
    assert ffmpeg_path is not None
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_playlist = source_dir / "index.m3u8"
    created = downloader_module.subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "0.25",
            "-c:a",
            "aac",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            str(source_playlist),
        ],
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr

    class SourceHandler(http.server.SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(source_dir), **kwargs)

        def log_message(self, _format: str, *_args) -> None:
            return

    source = _LoopbackHTTPServer(("127.0.0.1", 0), SourceHandler)
    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    captured = {}
    original_run = downloader_module.subprocess.run

    def capture_run(command, **kwargs):
        captured["command"] = list(command)
        return original_run(command, **kwargs)

    monkeypatch.setattr(downloader_module.subprocess, "run", capture_run)
    output = tmp_path / "output.mp4"
    try:
        remote_url = f"http://127.0.0.1:{source.server_address[1]}/index.m3u8"
        DownloadQueue._run_ffmpeg(ffmpeg_path, remote_url, output)
    finally:
        source.shutdown()
        source.server_close()
        source_thread.join(timeout=2)

    command = captured["command"]
    input_url = command[command.index("-i") + 1]
    assert Path(input_url).name.startswith("playlist-")
    assert input_url.endswith(".m3u8")
    assert command[command.index("-http_persistent") + 1] == "1"
    assert command[command.index("-http_multiple") + 1] == "1"
    assert command[command.index("-http_seekable") + 1] == "0"
    assert "-multiple_requests" not in command
    assert "-seekable" not in command
    assert output.stat().st_size > 0

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
        with _SegmentProxy() as proxy, urllib.request.urlopen(proxy.url_for(remote), timeout=5) as response:
            assert response.version == 11
            assert response.headers.get("Content-Length") is None
            assert response.headers.get("Connection") == "close"
            assert response.read() == payload
    finally:
        source.shutdown()
        source.server_close()
        thread.join(timeout=2)

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
        current = next((item for item in value if item["task_id"] == task_id), None)
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
        current = next((item for item in value if item["task_id"] == task_id), None)
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
