from pathlib import Path

import pytest

import app.plugins.lunatvsource.downloader as downloader_module
from app.plugins.lunatvsource.downloader import DownloadQueue, DownloadTask


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


def test_queue_recovers_interrupted_running_task(tmp_path: Path):
    data = {
        "download_tasks_v1": [
            DownloadTask(
                task_id="stale", source_key="lunatv", media_id="site:3", title="示例", year="2024",
                media_type="movie", season=1, episode=1, url="https://example.test/a.m3u8",
                root=str(tmp_path), state="running",
            ).to_dict()
        ]
    }
    queue = DownloadQueue(data.get, data.__setitem__, lambda *_: None)
    tasks = queue.list_tasks()
    assert tasks[0]["state"] == "pending"
    assert "恢复" in tasks[0]["error"]


def test_ffmpeg_explicitly_sets_mp4_muxer_for_part_file(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(downloader_module.subprocess, "run", fake_run)
    monkeypatch.setattr(DownloadQueue, "_prepare_hls_input", lambda url, _temp: url)
    DownloadQueue._run_ffmpeg("ffmpeg", "https://example.test/video.m3u8", tmp_path / "movie.mp4.part")
    command = captured["command"]
    assert command[command.index("-f") + 1] == "mp4"
    assert command[command.index("-allowed_segment_extensions") + 1] == "ALL"
    assert command[command.index("-extension_picky") + 1] == "0"


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
