import http.server
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


def test_queue_pause_resume_and_remove_pending_task(tmp_path: Path):
    data = {}
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    task = DownloadTask(
        task_id="pending-control", source_key="lunatv", media_id="site:pending",
        title="示例", year="2026", media_type="movie", season=1, episode=1,
        url="https://example.test/pending.m3u8", root=str(tmp_path),
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
