from pathlib import Path

import pytest

from app.plugins.lunatvsource.m3u8_engine import M3U8EngineError, N_m3u8DLEngine


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (None, 16),
        ("invalid", 16),
        (1, 4),
        (4, 4),
        (16, 16),
        (40, 32),
        (64, 32),
        (1000, 32),
    ],
)
def test_thread_count_is_clamped_for_engine_and_command(
    tmp_path: Path, requested: object, expected: int
) -> None:
    engine = N_m3u8DLEngine(tmp_path, thread_count=requested)

    command = engine.command(
        Path("/bin/N_m3u8DL-RE"),
        "https://example.test/index.m3u8",
        tmp_path / "cache",
        tmp_path / "stage",
        "/bin/ffmpeg",
    )

    assert command[command.index("--thread-count") + 1] == str(expected)
    assert "--concurrent-download" not in command
    assert command[command.index("--ffmpeg-binary-path") + 1] == "/bin/ffmpeg"


def test_download_override_is_clamped_and_failure_keeps_only_task_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = N_m3u8DLEngine(tmp_path / "plugin-data")
    task_id = "retryable-task"
    other_task_id = "other-task"
    cache_dir = engine.task_cache_dir(task_id)
    other_cache = engine.task_cache_dir(other_task_id)
    cache_dir.mkdir(parents=True)
    other_cache.mkdir(parents=True)
    (cache_dir / "segment.ts").write_bytes(b"segment")
    (other_cache / "segment.ts").write_bytes(b"other")
    captured: list[list[str]] = []

    monkeypatch.setattr(
        engine._installer,
        "ensure_binary",
        lambda control_event=None: Path("/bin/N_m3u8DL-RE"),
    )

    def fail(command: object, **_kwargs: object) -> None:
        captured.append(list(command))
        raise M3U8EngineError("download failed")

    monkeypatch.setattr(engine, "_run_command", fail)

    with pytest.raises(M3U8EngineError, match="download failed"):
        engine.download(
            "https://example.test/index.m3u8",
            tmp_path / "movie.mp4.part",
            task_id=task_id,
            ffmpeg_path="/bin/ffmpeg",
            control_event=None,
            progress_callback=None,
            thread_count=1,
        )

    assert captured[0][captured[0].index("--thread-count") + 1] == "4"
    assert (cache_dir / "segment.ts").read_bytes() == b"segment"
    assert (other_cache / "segment.ts").read_bytes() == b"other"
