from __future__ import annotations

import hashlib
import io
import os
import errno
import stat
import sys
import tarfile
import subprocess
import threading
import time
import signal
import urllib.error
from pathlib import Path

import pytest

from app.plugins.lunatvsource.m3u8_engine import (
    EngineSpec,
    M3U8EngineCancelled,
    M3U8EngineError,
    M3U8EngineInstallError,
    ManagedBinaryInstaller,
    N_m3u8DLEngine,
    ReleaseAsset,
    _safe_error_text,
    normalized_platform,
)

# Shared process/watchdog tests exercise the common base implementation.
ENGINE_UNDER_TEST = N_m3u8DLEngine


def _spec(executable: str = "tool", executable_digest: str | None = None) -> EngineSpec:
    expected_payload = b"tool"
    asset = ReleaseAsset(
        filename="tool.tar.gz",
        sha256=hashlib.sha256(expected_payload).hexdigest(),
        executable_sha256=executable_digest
        or hashlib.sha256(expected_payload).hexdigest(),
        url="https://example.test/tool.tar.gz",
    )
    return EngineSpec("test-tool", executable, {normalized_platform(): asset})


def _archive(path: Path, member_name: str, payload: bytes = b"tool") -> Path:
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = len(payload)
        member.mode = 0o755
        archive.addfile(member, io.BytesIO(payload))
    return path


def test_installer_prefers_verified_bundled_archive_without_network(
    monkeypatch, tmp_path: Path
):
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    archive = _archive(bundled_dir / "tool.tar.gz", "tool")
    asset = ReleaseAsset(
        filename=archive.name,
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        executable_sha256=hashlib.sha256(b"tool").hexdigest(),
        url="https://example.test/tool.tar.gz",
    )
    installer = ManagedBinaryInstaller(
        tmp_path / "data",
        EngineSpec("test-tool", "tool", {normalized_platform(): asset}),
        bundled_asset_dir=bundled_dir,
    )
    monkeypatch.setattr(
        installer,
        "_download_archive",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("verified bundled archive must avoid the network")
        ),
    )

    assert installer.ensure_binary().read_bytes() == b"tool"
    assert archive.is_file()


def test_installer_rejects_tampered_bundled_archive_without_network(
    monkeypatch, tmp_path: Path
):
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    archive = _archive(bundled_dir / "tool.tar.gz", "tool")
    asset = ReleaseAsset(
        filename=archive.name,
        sha256="0" * 64,
        executable_sha256=hashlib.sha256(b"tool").hexdigest(),
        url="https://example.test/tool.tar.gz",
    )
    installer = ManagedBinaryInstaller(
        tmp_path / "data",
        EngineSpec("test-tool", "tool", {normalized_platform(): asset}),
        bundled_asset_dir=bundled_dir,
    )
    monkeypatch.setattr(
        installer,
        "_download_archive",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tampered bundled archive must fail closed")
        ),
    )

    with pytest.raises(M3U8EngineInstallError, match="bundled release checksum mismatch"):
        installer.ensure_binary()

    assert archive.is_file()
    assert not installer.managed_path.exists()


def test_engine_platform_assets():
    assert N_m3u8DLEngine.asset_for_current_platform("Linux", "amd64")
    assert N_m3u8DLEngine.asset_for_current_platform("Linux", "arm64")
    assert N_m3u8DLEngine.asset_for_current_platform("Darwin", "x86_64")
    assert N_m3u8DLEngine.asset_for_current_platform("Darwin", "arm64")
    assert N_m3u8DLEngine.asset_for_current_platform("Windows", "x86_64") is None


def test_installer_removes_hash_mismatch_download(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())

    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.urllib.request.urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b"wrong-content"),
    )

    with pytest.raises(M3U8EngineInstallError, match="checksum"):
        installer._download_archive(installer.asset())

    assert not list((tmp_path / "bin").glob("*.download"))


def test_installer_rejects_unsafe_archive_path(tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    archive = _archive(tmp_path / "unsafe.tar.gz", "../tool")

    with pytest.raises(M3U8EngineInstallError, match="unsafe"):
        installer._extract_executable(archive)

    assert not installer.managed_path.exists()


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_installer_rejects_archive_links(tmp_path: Path, link_type: bytes):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    archive = tmp_path / "linked.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        member = tarfile.TarInfo("tool")
        member.type = link_type
        member.linkname = "other"
        handle.addfile(member)

    with pytest.raises(M3U8EngineInstallError, match="link"):
        installer._extract_executable(archive)

    assert not installer.managed_path.exists()


def test_installer_atomically_replaces_expected_executable(monkeypatch, tmp_path: Path):
    archive = _archive(tmp_path / "tool.tar.gz", "tool", b"new-tool")
    installer = ManagedBinaryInstaller(
        tmp_path,
        _spec(executable_digest=hashlib.sha256(b"new-tool").hexdigest()),
    )
    installer.bin_dir.mkdir(parents=True)
    installer.managed_path.write_bytes(b"old-tool")
    os.chmod(installer.managed_path, 0o644)
    monkeypatch.setattr(
        installer, "_download_archive", lambda _asset, _control_event=None: archive
    )

    binary = installer.ensure_binary()

    assert binary == installer.managed_path
    assert binary.read_bytes() == b"new-tool"
    assert not list(installer.bin_dir.glob("*.install"))



def test_installer_serializes_concurrent_install(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    archive = _archive(tmp_path / "tool.tar.gz", "tool", b"tool")
    calls = 0
    calls_lock = threading.Lock()

    def download(_asset, _control_event=None):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return archive

    monkeypatch.setattr(installer, "_download_archive", download)
    results = []

    def install() -> None:
        results.append(installer.ensure_binary())

    workers = [threading.Thread(target=install) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert calls == 1
def test_installer_rehashes_managed_binary_even_if_manifest_is_forged(monkeypatch, tmp_path: Path) -> None:
    managed_payload = b"managed"
    managed_digest = hashlib.sha256(managed_payload).hexdigest()
    downloaded_payload = b"expected"
    installer = ManagedBinaryInstaller(
        tmp_path,
        _spec(executable_digest=hashlib.sha256(downloaded_payload).hexdigest()),
    )
    installer.bin_dir.mkdir(parents=True)
    installer.managed_path.write_bytes(managed_payload + b"-tampered")
    os.chmod(installer.managed_path, 0o755)
    installer.manifest_path.write_text(managed_digest + "\n", encoding="ascii")

    downloaded = {"count": 0}

    def download(_asset, _control_event=None):
        downloaded["count"] += 1
        return _archive(tmp_path / "tool.tar.gz", "tool", downloaded_payload)

    monkeypatch.setattr(installer, "_download_archive", download)

    assert installer.ensure_binary() == installer.managed_path
    assert installer.managed_path.read_bytes() == downloaded_payload
    assert downloaded["count"] == 1


    assert installer.ensure_binary() == installer.managed_path
    assert installer.managed_path.read_bytes() == b"expected"
    assert downloaded["count"] == 1


def test_installer_skips_download_when_managed_binary_digest_matches(monkeypatch, tmp_path: Path) -> None:
    executable = b"managed"
    executable_digest = hashlib.sha256(executable).hexdigest()
    installer = ManagedBinaryInstaller(tmp_path, _spec(executable_digest=executable_digest))
    installer.bin_dir.mkdir(parents=True)
    installer.managed_path.write_bytes(executable)
    os.chmod(installer.managed_path, 0o755)
    installer.manifest_path.write_text("not-the-manifest", encoding="ascii")

    monkeypatch.setattr(
        installer,
        "_download_archive",
        lambda _asset, _control_event=None: (_ for _ in ()).throw(
            AssertionError("must not download")
        ),
    )

    assert installer.ensure_binary() == installer.managed_path
def test_installer_never_falls_back_to_a_path_binary(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    monkeypatch.setattr(
        installer,
        "_download_archive",
        lambda _asset, _control_event=None: (_ for _ in ()).throw(
            M3U8EngineInstallError("offline")
        ),
    )
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.shutil.which",
        lambda _name: (_ for _ in ()).throw(AssertionError("PATH must not be used")),
    )

    with pytest.raises(M3U8EngineInstallError, match="offline"):
        installer.ensure_binary()


def test_engine_commands_and_progress_parsing(tmp_path: Path):
    n_engine = N_m3u8DLEngine(tmp_path)
    assert n_engine.task_cache_dir("same-task") == n_engine.task_cache_dir("same-task")
    assert n_engine.task_cache_dir("same-task") != n_engine.task_cache_dir("other-task")
    n_command = n_engine.command(
        Path("/bin/n_m3u8dl"),
        "playlist.m3u8",
        tmp_path / "cache",
        tmp_path / "stage",
        "/bin/ffmpeg",
    )
    assert n_command[n_command.index("--thread-count") + 1] == "16"
    assert "--concurrent-download" not in n_command
    assert n_command[n_command.index("--download-retry-count") + 1] == "3"
    assert n_command[n_command.index("--tmp-dir") + 1] == str(tmp_path / "cache")
    assert n_command[n_command.index("--save-dir") + 1] == str(tmp_path / "stage")
    assert n_command[n_command.index("--ffmpeg-binary-path") + 1] == "/bin/ffmpeg"
    assert n_command[n_command.index("--mux-after-done") + 1] == "format=mp4"
    assert "--auto-select" in n_command
    assert "--no-ansi-color" in n_command

    assert N_m3u8DLEngine.parse_progress("completed 64.7%") == pytest.approx(0.647)


def test_n_engine_resolves_bare_ffmpeg_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.shutil.which",
        lambda executable: "/resolved/bin/ffmpeg" if executable == "ffmpeg" else None,
    )
    engine = N_m3u8DLEngine(tmp_path)

    command = engine.command(
        Path("/bin/n_m3u8dl"),
        "playlist.m3u8",
        tmp_path / "cache",
        tmp_path / "stage",
        "ffmpeg",
    )

    assert command[command.index("--ffmpeg-binary-path") + 1] == "/resolved/bin/ffmpeg"


def test_engine_reads_carriage_return_progress_and_enforces_watchdog(
    monkeypatch, tmp_path: Path
):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    progress = []
    engine._run_command(
        [
            sys.executable,
            "-c",
            "import sys, time; sys.stdout.write('PT: 8/20 speed %:40.0\\r'); sys.stdout.flush(); time.sleep(0.05)",
        ],
        cache_dir=cache_dir,
        control_event=None,
        progress_callback=progress.append,
    )
    assert max(progress) == pytest.approx(0.4)

    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(M3U8EngineError, match="timed out|no progress"):
        engine._run_command(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            cache_dir=cache_dir,
            control_event=None,
            progress_callback=None,
        )



def test_engine_no_progress_watchdog_ignores_logs_and_repeated_progress(
    monkeypatch, tmp_path: Path
):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 0.15)
    monkeypatch.setattr(engine, "PROCESS_POLL_INTERVAL_SECONDS", 0.02)

    started_at = time.monotonic()
    with pytest.raises(M3U8EngineError, match="made no progress"):
        engine._run_command(
            [
                sys.executable,
                "-c",
                "import time; exec(\"while True:\\n    print('still working', flush=True)\\n    print('PT: 1/2', flush=True)\\n    time.sleep(0.01)\")",
            ],
            cache_dir=cache_dir,
            control_event=None,
            progress_callback=None,
        )
    assert time.monotonic() - started_at < 0.8


def test_engine_progress_growth_resets_stall_watchdog(monkeypatch, tmp_path: Path):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(engine, "PROCESS_POLL_INTERVAL_SECONDS", 0.02)

    started_at = time.monotonic()
    engine._run_command(
        [
            sys.executable,
            "-c",
            "import time; exec(\"for current in range(1, 5):\\n    print(f'PT: {current}/4', flush=True)\\n    time.sleep(0.12)\")",
        ],
        cache_dir=cache_dir,
        control_event=None,
        progress_callback=None,
    )

    assert time.monotonic() - started_at > 0.3


@pytest.mark.parametrize(
    ("line", "should_timeout"),
    [
        ("PT: 2/2 speed %:100.0\r", False),
        ("ordinary status line\r", True),
    ],
)
def test_engine_processes_ready_output_before_stall_timeout(
    monkeypatch, tmp_path: Path, line: str, should_timeout: bool
):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    clock = {"value": 0.0}
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb", buffering=0)
    os.write(write_fd, line.encode())
    os.close(write_fd)

    class Process:
        pid = 43210
        returncode = None

        def __init__(self):
            self.poll_calls = 0
            self.stdout = stream
            self.stderr = None

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls > 1:
                self.returncode = 0
            return self.returncode

        def wait(self, timeout=None):
            del timeout
            self.returncode = 0
            return 0

    class Selector:
        def __init__(self):
            self.streams = {}
            self.select_calls = 0

        def register(self, registered_stream, _event, stream_name):
            self.streams[registered_stream] = stream_name
            clock["value"] = 2.0

        def select(self, timeout=None):
            del timeout
            if self.streams and self.select_calls < 2:
                self.select_calls += 1
                registered_stream, stream_name = next(iter(self.streams.items()))

                class Key:
                    fileobj = registered_stream
                    data = stream_name

                return [(Key(), None)]
            return []

        def unregister(self, registered_stream):
            self.streams.pop(registered_stream, None)

        def get_map(self):
            return self.streams

        def close(self):
            pass

    process = Process()

    def killpg(*_args):
        raise ProcessLookupError(3, "gone")

    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.selectors.DefaultSelector", Selector
    )
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.os.killpg", killpg)
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.time.monotonic", lambda: clock["value"]
    )
    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 1.0)

    try:
        if should_timeout:
            with pytest.raises(M3U8EngineError, match="made no progress"):
                engine._run_command(
                    ["engine"],
                    cache_dir=cache_dir,
                    control_event=None,
                    progress_callback=None,
                )
        else:
            engine._run_command(
                ["engine"],
                cache_dir=cache_dir,
                control_event=None,
                progress_callback=None,
            )
    finally:
        stream.close()


def test_engine_processes_due_cache_activity_before_stall_timeout(
    monkeypatch, tmp_path: Path
):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "segment.ts").write_bytes(b"segment")
    clock = {"value": 0.0}

    class Process:
        pid = 43211
        returncode = None

        def __init__(self):
            self.poll_calls = 0
            self.stdout = None
            self.stderr = None

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls > 1:
                self.returncode = 0
            return self.returncode

        def wait(self, timeout=None):
            del timeout
            self.returncode = 0
            return 0

    class Selector:
        def register(self, *_args):
            raise AssertionError("no stream should be registered")

        def select(self, timeout=None):
            del timeout
            return []

        def get_map(self):
            return {}

        def close(self):
            pass

    process = Process()

    def popen(*_args, **_kwargs):
        clock["value"] = 2.0
        return process

    def killpg(*_args):
        raise ProcessLookupError(3, "gone")

    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.subprocess.Popen", popen)
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.selectors.DefaultSelector", Selector
    )
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.os.killpg", killpg)
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.time.monotonic", lambda: clock["value"]
    )
    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 1.0)

    engine._run_command(
        ["engine"],
        cache_dir=cache_dir,
        control_event=None,
        progress_callback=None,
        expected_segments=1,
    )


def test_engine_single_track_progress_completion_keeps_watchdog(
    monkeypatch, tmp_path: Path
):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    command = [
        sys.executable,
        "-c",
        "import time; print('track 1 100%', flush=True); time.sleep(0.25)",
    ]

    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(engine, "PROCESS_POLL_INTERVAL_SECONDS", 0.02)

    with pytest.raises(M3U8EngineError, match="made no progress"):
        engine._run_command(
            command,
            cache_dir=cache_dir,
            control_event=None,
            progress_callback=None,
            expected_segments=0,
        )


@pytest.mark.parametrize(
    ("engine_type", "finalize_line"),
    [
        (N_m3u8DLEngine, "INFO : Muxing to /tmp/media.mp4"),
    ],
)
def test_engine_allows_finalize_after_reliable_engine_signal(
    monkeypatch, tmp_path: Path, engine_type, finalize_line: str
):
    engine = engine_type(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    command = [
        sys.executable,
        "-c",
        f"import time; print({finalize_line!r}, flush=True); time.sleep(0.25)",
    ]
    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(engine, "PROCESS_POLL_INTERVAL_SECONDS", 0.02)

    engine._run_command(
        command,
        cache_dir=cache_dir,
        control_event=None,
        progress_callback=None,
        expected_segments=0,
    )


def test_engine_cache_file_count_does_not_mark_download_complete(
    monkeypatch, tmp_path: Path
):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "key.bin").write_bytes(b"key")
    (cache_dir / "init.mp4").write_bytes(b"init")
    monkeypatch.setattr(engine, "PROCESS_TOTAL_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(engine, "PROCESS_POLL_INTERVAL_SECONDS", 0.02)

    with pytest.raises(M3U8EngineError, match="made no progress"):
        engine._run_command(
            [sys.executable, "-c", "import time; time.sleep(0.25)"],
            cache_dir=cache_dir,
            control_event=None,
            progress_callback=None,
            expected_segments=2,
        )


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize(
    ("cancel_after", "error_type", "message"),
    [
        (0.15, M3U8EngineCancelled, "download cancelled"),
        (None, M3U8EngineError, "process timed out"),
    ],
)
def test_engine_watchdogs_exited_leader_with_child_holding_pipes(
    monkeypatch,
    tmp_path: Path,
    cancel_after: float | None,
    error_type: type[Exception],
    message: str,
):
    engine = ENGINE_UNDER_TEST(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(
        engine,
        "PROCESS_TOTAL_TIMEOUT_SECONDS",
        2.0 if cancel_after is not None else 0.2,
    )
    monkeypatch.setattr(engine, "PROCESS_NO_PROGRESS_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(engine, "PROCESS_POLL_INTERVAL_SECONDS", 0.02)

    control_event = threading.Event()
    timer = None
    if cancel_after is not None:
        timer = threading.Timer(cancel_after, control_event.set)
        timer.start()

    started_at = time.monotonic()
    try:
        with pytest.raises(error_type, match=message):
            engine._run_command(
                [
                    sys.executable,
                    "-c",
                    "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); sys.exit(0)",
                ],
                cache_dir=cache_dir,
                control_event=control_event,
                progress_callback=None,
            )
    finally:
        if timer is not None:
            timer.cancel()

    assert time.monotonic() - started_at < 1.0


def test_terminate_uses_process_group_even_if_leader_exited(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 321
            self.terminated = False
            self.killed = False
            self.waited = 0

        def poll(self):
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> None:
            self.waited += 1

    monotonic_state = {"value": 0.0}

    def fake_monotonic() -> float:
        value = monotonic_state["value"]
        monotonic_state["value"] += 0.1
        return value

    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    seen: list[int] = []

    def fake_killpg(_pid: int, signal_number: int) -> None:
        seen.append(signal_number)
        if signal_number == 0:
            raise ProcessLookupError(3, "disappeared")

    process = FakeProcess()
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.time.sleep", fake_sleep)
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.os.killpg", fake_killpg)

    N_m3u8DLEngine._terminate(process)

    assert seen == [signal.SIGTERM, 0]
    assert process.terminated is False
    assert process.killed is False
    assert sleep_calls == []


def test_terminate_escalates_to_sigkill_when_group_lingers(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 333
            self.terminated = False
            self.killed = False
            self.wait_calls = 0
            self.poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> None:
            self.wait_calls += 1
            raise subprocess.TimeoutExpired("cmd", timeout if timeout is not None else 0)

    seen: list[int] = []
    sleep_calls: list[float] = []
    monotonic_state = {"value": 0.0}
    kill_state = {"sigkill": False}

    def fake_monotonic() -> float:
        value = monotonic_state["value"]
        monotonic_state["value"] += 0.25
        return value

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def fake_killpg(_pid: int, signal_number: int) -> None:
        seen.append(signal_number)
        if signal_number == signal.SIGTERM:
            return
        if signal_number == signal.SIGKILL:
            kill_state["sigkill"] = True
        if signal_number == 0 and kill_state["sigkill"]:
            raise ProcessLookupError(3, "disappeared")

    process = FakeProcess()
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.time.sleep", fake_sleep)
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.os.killpg", fake_killpg)

    N_m3u8DLEngine._terminate(process)

    assert seen[0] == signal.SIGTERM
    assert signal.SIGKILL in seen
    assert seen.count(signal.SIGKILL) == 1
    assert seen[-1] == 0
    assert sleep_calls
    assert process.terminated is False
    assert process.killed is False
    assert process.wait_calls == 0
    assert process.poll_calls > 0


def test_engine_cancellation_prevents_binary_install(monkeypatch, tmp_path: Path):
    engine = N_m3u8DLEngine(tmp_path)
    control_event = threading.Event()
    control_event.set()
    monkeypatch.setattr(
        engine._installer,
        "ensure_binary",
        lambda: (_ for _ in ()).throw(AssertionError("must not install")),
    )

    with pytest.raises(M3U8EngineCancelled):
        engine.download(
            "https://example.test/index.m3u8",
            tmp_path / "movie.mp4.part",
            task_id="cancelled",
            ffmpeg_path="ffmpeg",
            control_event=control_event,
            progress_callback=None,
        )


def test_n_stage_is_plugin_cache_and_accepts_only_fixed_output(tmp_path: Path):
    engine = N_m3u8DLEngine(tmp_path / "plugin-data")
    stage_dir = engine.stage_dir("task", tmp_path / "media")
    assert str(stage_dir).startswith(str(tmp_path / "plugin-data"))
    assert "media" not in stage_dir.parts
    stage_dir.mkdir(parents=True)
    (stage_dir / "unrelated.mp4").write_bytes(b"not an output")
    with pytest.raises(M3U8EngineError, match="expected output"):
        engine._output_from_stage(stage_dir)

    (stage_dir / "media.mkv").write_bytes(b"wrong container")
    with pytest.raises(M3U8EngineError, match="expected output"):
        engine._output_from_stage(stage_dir)
    (stage_dir / "media.mkv").unlink()

    (stage_dir / "media.mp4").write_bytes(b"output")
    assert engine._output_from_stage(stage_dir) == stage_dir / "media.mp4"



def test_cross_filesystem_move_preserves_source_permissions(monkeypatch, tmp_path: Path):
    candidate = tmp_path / "stage" / "media.mp4"
    output = tmp_path / "media" / "movie.mp4.part"
    candidate.parent.mkdir()
    output.parent.mkdir()
    candidate.write_bytes(b"media")
    candidate.chmod(0o640)
    real_replace = os.replace
    calls = 0

    def replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", replace)

    N_m3u8DLEngine._move_stage_output(candidate, output)

    assert stat.S_IMODE(output.stat().st_mode) == 0o640


def test_cross_filesystem_move_keeps_committed_output_when_cleanup_fails(
    monkeypatch, tmp_path: Path, caplog
):
    candidate = tmp_path / "stage" / "media.mp4"
    output = tmp_path / "media" / "movie.mp4.part"
    candidate.parent.mkdir()
    output.parent.mkdir()
    candidate.write_bytes(b"media")
    candidate.chmod(0o640)

    real_replace = os.replace
    calls = 0

    def replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(source, destination)

    original_unlink = Path.unlink

    def unlink(path: Path, *args, **kwargs):
        if path == candidate:
            raise OSError(errno.EACCES, "stage cleanup denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(Path, "unlink", unlink)

    N_m3u8DLEngine._move_stage_output(candidate, output)

    assert output.read_bytes() == b"media"
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert "stage output cleanup failed after committing" in caplog.text


def test_error_tail_redacts_complete_http_credential_values():
    detail = _safe_error_text(
        "engine request failed\n"
        "Authorization: Bearer bearer-secret-token\n"
        "Proxy-Authorization: Basic cHJveHktc2VjcmV0\n"
        "Cookie: session=cookie-secret; preference=private\n"
        "Set-Cookie: auth=set-cookie-secret; Path=/; HttpOnly\n"
        "authorization=Bearer inline-secret\n"
        'headers={"Authorization": "Basic json-secret"}\n'
        "metadata={'token': 'json-token-secret; trailing-secret'}\n"
        "HTTP status=403"
    )

    for secret in (
        "bearer-secret-token",
        "cHJveHktc2VjcmV0",
        "cookie-secret",
        "private",
        "set-cookie-secret",
        "inline-secret",
        "json-secret",
        "json-token-secret",
        "trailing-secret",
    ):
        assert secret not in detail
    assert "engine request failed" in detail
    assert "HTTP status=403" in detail
    assert "Authorization: <redacted>" in detail
    assert "Cookie: <redacted>" in detail
    assert "Set-Cookie: <redacted>" in detail


def test_installer_download_cancels_and_removes_partial_archive(
    monkeypatch, tmp_path: Path
):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    asset = installer.asset()
    assert asset is not None
    control_event = threading.Event()

    class Response:
        def __init__(self) -> None:
            self.read_calls = 0
            self.closed = False

        def read(self, _size: int) -> bytes:
            self.read_calls += 1
            control_event.set()
            return b"partial"

        def close(self) -> None:
            self.closed = True

    response = Response()
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(M3U8EngineCancelled):
        installer._download_archive(asset, control_event)

    assert response.read_calls == 1
    assert response.closed
    assert not list(installer.bin_dir.glob("*.download"))


def test_installer_download_total_deadline_removes_partial_archive(
    monkeypatch, tmp_path: Path
):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    asset = installer.asset()
    assert asset is not None

    class Response:
        def __init__(self) -> None:
            self.read_calls = 0
            self.closed = False

        def read(self, _size: int) -> bytes:
            self.read_calls += 1
            return b"slow"

        def close(self) -> None:
            self.closed = True

    response = Response()
    clock_values = iter((0.0, 0.0, 0.0, 2.0))

    def monotonic() -> float:
        return next(clock_values, 2.0)

    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.time.monotonic", monotonic
    )
    monkeypatch.setattr(installer, "DOWNLOAD_TOTAL_TIMEOUT_SECONDS", 1.0)

    with pytest.raises(M3U8EngineInstallError, match="timed out"):
        installer._download_archive(asset)

    assert response.read_calls == 1
    assert response.closed
    assert not list(installer.bin_dir.glob("*.download"))


def test_installer_passes_control_event_to_archive_download(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    control_event = threading.Event()
    archive = _archive(tmp_path / "tool.tar.gz", "tool")
    seen = []

    def download(_asset, event=None):
        seen.append(event)
        return archive

    monkeypatch.setattr(installer, "_download_archive", download)

    assert installer.ensure_binary(control_event) == installer.managed_path
    assert seen == [control_event]


def test_n_download_clears_stale_mux_outputs_but_preserves_segment_cache(
    monkeypatch, tmp_path: Path
):
    engine = N_m3u8DLEngine(tmp_path / "plugin-data")
    task_id = "stale-stage"
    cache_dir = engine.task_cache_dir(task_id)
    stage_dir = engine.stage_dir(task_id)
    cache_dir.mkdir(parents=True)
    stage_dir.mkdir(parents=True)
    (cache_dir / "segment.ts").write_bytes(b"segment")
    (stage_dir / "media.mp4").write_bytes(b"old mp4")
    (stage_dir / "media.mkv").write_bytes(b"old mkv")
    (stage_dir / "unrelated.mp4").write_bytes(b"keep")

    monkeypatch.setattr(
        engine._installer, "ensure_binary", lambda control_event=None: Path("/bin/n_m3u8dl")
    )
    monkeypatch.setattr(engine, "_run_command", lambda *_args, **_kwargs: None)

    with pytest.raises(M3U8EngineError, match="did not produce"):
        engine.download(
            "https://example.test/index.m3u8",
            tmp_path / "movie.mp4.part",
            task_id=task_id,
            ffmpeg_path="ffmpeg",
            control_event=None,
            progress_callback=None,
        )

    assert not (stage_dir / "media.mp4").exists()
    assert not (stage_dir / "media.mkv").exists()
    assert (stage_dir / "unrelated.mp4").read_bytes() == b"keep"
    assert (cache_dir / "segment.ts").read_bytes() == b"segment"


def test_n_stage_cleanup_rejects_symlinked_output_without_following_it(
    tmp_path: Path,
):
    engine = N_m3u8DLEngine(tmp_path / "plugin-data")
    task_id = "unsafe-stage"
    stage_dir = engine.stage_dir(task_id)
    stage_dir.mkdir(parents=True)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    (stage_dir / "media.mp4").symlink_to(outside)

    with pytest.raises(M3U8EngineError, match="unsafe"):
        engine._prepare_stage_dir(task_id)

    assert (stage_dir / "media.mp4").is_symlink()
    assert outside.read_bytes() == b"outside"


def test_error_tail_redacts_whole_inline_secret_lines():
    detail = _safe_error_text(
        "request failed\n"
        "token: token-secret trailing words; semicolon-secret\n"
        "access_key = access-secret after-space; after-semicolon\n"
        "signature=sig-secret trailing signature data; still-secret\n"
        "HTTP status=401"
    )

    for secret in (
        "token-secret",
        "trailing words",
        "semicolon-secret",
        "access-secret",
        "after-space",
        "after-semicolon",
        "sig-secret",
        "trailing signature data",
        "still-secret",
    ):
        assert secret not in detail
    assert "request failed" in detail
    assert "HTTP status=401" in detail
    assert "token: <redacted>" in detail
    assert "access_key = <redacted>" in detail
    assert "signature=<redacted>" in detail


def test_installer_cancellation_after_download_skips_extraction(
    monkeypatch, tmp_path: Path
):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    control_event = threading.Event()
    archive = tmp_path / "downloaded.tar.gz"
    archive.write_bytes(b"archive")
    extracted = []

    def download(_asset, _event=None):
        control_event.set()
        return archive

    monkeypatch.setattr(installer, "_download_archive", download)
    monkeypatch.setattr(
        installer, "_extract_executable", lambda _archive: extracted.append(_archive)
    )

    with pytest.raises(M3U8EngineCancelled):
        installer.ensure_binary(control_event)

    assert extracted == []
    assert not archive.exists()


def test_installer_cancellation_after_validation_prevents_return(
    monkeypatch, tmp_path: Path
):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    control_event = threading.Event()
    archive = tmp_path / "downloaded.tar.gz"
    archive.write_bytes(b"archive")
    verified_calls = 0

    def verified() -> bool:
        nonlocal verified_calls
        verified_calls += 1
        if verified_calls == 3:
            control_event.set()
            return True
        return False

    monkeypatch.setattr(
        installer, "_download_archive", lambda _asset, _event=None: archive
    )
    monkeypatch.setattr(installer, "_extract_executable", lambda _archive: None)
    monkeypatch.setattr(installer, "_managed_binary_is_verified", verified)

    with pytest.raises(M3U8EngineCancelled):
        installer.ensure_binary(control_event)

    assert verified_calls == 3
    assert not archive.exists()


def test_installer_limits_io_timeout_and_prefers_read1(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    asset = installer.asset()
    assert asset is not None
    installer.DOWNLOAD_TOTAL_TIMEOUT_SECONDS = 5.0

    class Response:
        def __init__(self) -> None:
            self.read1_sizes = []
            self.read_calls = 0

        def read1(self, size: int) -> bytes:
            self.read1_sizes.append(size)
            return b"tool" if len(self.read1_sizes) == 1 else b""

        def read(self, _size: int) -> bytes:
            self.read_calls += 1
            raise AssertionError("read1 should be preferred")

        def close(self) -> None:
            pass

    response = Response()
    timeouts = []
    clock_values = iter((0.0, 1.0))

    def monotonic() -> float:
        return next(clock_values, 1.0)

    def urlopen(_request, *, timeout):
        timeouts.append(timeout)
        return response

    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.time.monotonic", monotonic
    )
    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.urllib.request.urlopen", urlopen
    )

    archive = installer._download_archive(asset)

    assert timeouts == [pytest.approx(4.0)]
    assert response.read1_sizes == [installer.DOWNLOAD_CHUNK_BYTES] * 2
    assert response.read_calls == 0
    assert 0 < timeouts[0] <= installer.DOWNLOAD_IO_TIMEOUT_SECONDS <= 10
    archive.unlink()


def test_installer_retries_transient_connection_failures(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    asset = installer.asset()
    assert asset is not None
    installer.DOWNLOAD_RETRY_DELAY_SECONDS = 0
    attempts = []

    def urlopen(_request, *, timeout):
        attempts.append(timeout)
        if len(attempts) < installer.DOWNLOAD_CONNECT_ATTEMPTS:
            raise urllib.error.URLError("temporary TLS timeout")
        return io.BytesIO(b"tool")

    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.urllib.request.urlopen", urlopen
    )

    archive = installer._download_archive(asset)

    assert archive.read_bytes() == b"tool"
    assert len(attempts) == installer.DOWNLOAD_CONNECT_ATTEMPTS
    assert all(0 < timeout <= installer.DOWNLOAD_IO_TIMEOUT_SECONDS for timeout in attempts)
    archive.unlink()


def test_installer_does_not_retry_http_errors(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    asset = installer.asset()
    assert asset is not None
    attempts = []

    def urlopen(_request, *, timeout):
        attempts.append(timeout)
        raise urllib.error.HTTPError(asset.url, 404, "not found", None, None)

    monkeypatch.setattr(
        "app.plugins.lunatvsource.m3u8_engine.urllib.request.urlopen", urlopen
    )

    with pytest.raises(M3U8EngineInstallError, match="release download failed"):
        installer._download_archive(asset)

    assert len(attempts) == 1
    assert not list(installer.bin_dir.glob("*.download"))


def test_installer_in_process_lock_wait_is_cancellable(tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    holder_ready = threading.Event()
    holder_release = threading.Event()
    control_event = threading.Event()

    def hold_lock() -> None:
        with installer._installation_lock():
            holder_ready.set()
            holder_release.wait(2)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert holder_ready.wait(1)
    cancel_timer = threading.Timer(0.05, control_event.set)
    release_timer = threading.Timer(0.5, holder_release.set)
    cancel_timer.start()
    release_timer.start()
    started_at = time.monotonic()
    try:
        with pytest.raises(M3U8EngineCancelled):
            with installer._installation_lock(control_event):
                pass
        assert time.monotonic() - started_at < 0.4
    finally:
        cancel_timer.cancel()
        release_timer.cancel()
        holder_release.set()
        holder.join(timeout=2)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX flock")
def test_installer_flock_wait_is_cancellable(tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    installer.bin_dir.mkdir(parents=True)
    lock_path = installer.bin_dir / ".tool.install.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, os, sys, time; "
            "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600); "
            "fcntl.flock(fd, fcntl.LOCK_EX); "
            "print('locked', flush=True); time.sleep(5)",
            str(lock_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"
    control_event = threading.Event()
    cancel_timer = threading.Timer(0.05, control_event.set)
    stop_timer = threading.Timer(0.5, holder.terminate)
    cancel_timer.start()
    stop_timer.start()
    started_at = time.monotonic()
    try:
        with pytest.raises(M3U8EngineCancelled):
            with installer._installation_lock(control_event):
                pass
        assert time.monotonic() - started_at < 0.4
    finally:
        cancel_timer.cancel()
        stop_timer.cancel()
        if holder.poll() is None:
            holder.terminate()
        holder.wait(timeout=2)
        holder.stdout.close()


def test_n_stage_cleanup_rejects_hardlinked_output_without_touching_target(
    tmp_path: Path,
):
    engine = N_m3u8DLEngine(tmp_path / "plugin-data")
    stage_dir = engine.stage_dir("hardlink-stage")
    stage_dir.mkdir(parents=True)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    os.link(outside, stage_dir / "media.mp4")

    with pytest.raises(M3U8EngineError, match="unsafe"):
        engine._prepare_stage_dir("hardlink-stage")

    assert outside.read_bytes() == b"outside"
    assert (stage_dir / "media.mp4").exists()


def test_n_stage_cleanup_rejects_directory_output(tmp_path: Path):
    engine = N_m3u8DLEngine(tmp_path / "plugin-data")
    stage_dir = engine.stage_dir("directory-stage")
    stage_dir.mkdir(parents=True)
    (stage_dir / "media.mp4").mkdir()

    with pytest.raises(M3U8EngineError, match="unsafe"):
        engine._prepare_stage_dir("directory-stage")

    assert (stage_dir / "media.mp4").is_dir()


@pytest.mark.skipif(
    os.name != "posix"
    or not hasattr(os, "O_DIRECTORY")
    or not hasattr(os, "O_NOFOLLOW")
    or os.stat not in os.supports_dir_fd
    or os.stat not in os.supports_follow_symlinks
    or os.unlink not in os.supports_dir_fd,
    reason="requires POSIX dir_fd cleanup support",
)
def test_n_stage_cleanup_fd_resists_parent_symlink_replacement(
    monkeypatch, tmp_path: Path
):
    engine = N_m3u8DLEngine(tmp_path / "plugin-data")
    stage_dir = engine.stage_dir("parent-swap")
    stage_dir.mkdir(parents=True)
    (stage_dir / "media.mp4").write_bytes(b"stale")
    stage_parent = stage_dir.parent
    moved_parent = tmp_path / "moved-parent"
    outside_parent = tmp_path / "outside-parent"
    outside_stage = outside_parent / stage_dir.name
    outside_stage.mkdir(parents=True)
    outside_output = outside_stage / "media.mp4"
    outside_output.write_bytes(b"outside")
    original_stat = os.stat
    swapped = False

    def stat_with_parent_swap(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == "media.mp4" and kwargs.get("dir_fd") is not None:
            stage_parent.rename(moved_parent)
            stage_parent.symlink_to(outside_parent, target_is_directory=True)
            swapped = True
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(
        os, "supports_dir_fd", os.supports_dir_fd | {stat_with_parent_swap}
    )
    monkeypatch.setattr(
        os,
        "supports_follow_symlinks",
        os.supports_follow_symlinks | {stat_with_parent_swap},
    )
    monkeypatch.setattr("app.plugins.lunatvsource.m3u8_engine.os.stat", stat_with_parent_swap)

    engine._clear_stale_stage_outputs(stage_dir)

    assert swapped
    assert outside_output.read_bytes() == b"outside"
    assert not (moved_parent / stage_dir.name / "media.mp4").exists()


def test_cross_filesystem_move_accepts_name_max_output_without_temp_residue(
    monkeypatch, tmp_path: Path
):
    candidate = tmp_path / "stage" / "media.mp4"
    output_parent = tmp_path / "media"
    candidate.parent.mkdir()
    output_parent.mkdir()
    try:
        name_max = os.pathconf(output_parent, "PC_NAME_MAX")
    except (AttributeError, OSError):
        pytest.skip("filesystem does not expose NAME_MAX")
    candidate.write_bytes(b"media")
    candidate.chmod(0o640)
    output = output_parent / ("m" * name_max)
    real_replace = os.replace
    replace_calls = 0

    def replace(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", replace)

    N_m3u8DLEngine._move_stage_output(candidate, output)

    assert output.read_bytes() == b"media"
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert not candidate.exists()
    assert not list(output_parent.glob(".lunatv-transfer-*"))
