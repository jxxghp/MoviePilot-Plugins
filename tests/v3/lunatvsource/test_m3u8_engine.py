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
    VSDEngine,
    normalized_platform,
)


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


def test_engine_platform_assets_and_vsd_macos_x64_limit():
    assert N_m3u8DLEngine.asset_for_current_platform("Linux", "amd64")
    assert N_m3u8DLEngine.asset_for_current_platform("Linux", "arm64")
    assert N_m3u8DLEngine.asset_for_current_platform("Darwin", "x86_64")
    assert N_m3u8DLEngine.asset_for_current_platform("Darwin", "arm64")
    assert VSDEngine.asset_for_current_platform("Linux", "x86_64")
    assert VSDEngine.asset_for_current_platform("Darwin", "arm64")
    assert VSDEngine.asset_for_current_platform("Darwin", "x86_64") is None
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
    monkeypatch.setattr(installer, "_download_archive", lambda _asset: archive)

    binary = installer.ensure_binary()

    assert binary == installer.managed_path
    assert binary.read_bytes() == b"new-tool"
    assert not list(installer.bin_dir.glob("*.install"))



def test_installer_serializes_concurrent_install(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    archive = _archive(tmp_path / "tool.tar.gz", "tool", b"tool")
    calls = 0
    calls_lock = threading.Lock()

    def download(_asset):
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

    def download(_asset):
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
        lambda _asset: (_ for _ in ()).throw(AssertionError("must not download")),
    )

    assert installer.ensure_binary() == installer.managed_path
def test_installer_never_falls_back_to_a_path_binary(monkeypatch, tmp_path: Path):
    installer = ManagedBinaryInstaller(tmp_path, _spec())
    monkeypatch.setattr(
        installer,
        "_download_archive",
        lambda _asset: (_ for _ in ()).throw(M3U8EngineInstallError("offline")),
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
    assert n_command[n_command.index("--download-retry-count") + 1] == "3"
    assert n_command[n_command.index("--tmp-dir") + 1] == str(tmp_path / "cache")
    assert n_command[n_command.index("--save-dir") + 1] == str(tmp_path / "stage")
    assert n_command[n_command.index("--ffmpeg-binary-path") + 1] == "/bin/ffmpeg"
    assert n_command[n_command.index("--mux-after-done") + 1] == "format=mp4"
    assert "--auto-select" in n_command
    assert "--no-ansi-color" in n_command

    vsd_engine = VSDEngine(tmp_path)
    vsd_command = vsd_engine.command(
        Path("/bin/vsd"), "playlist.m3u8", tmp_path / "movie.mp4.part", tmp_path / "cache"
    )
    assert vsd_command[:3] == ["/bin/vsd", "save", "playlist.m3u8"]
    assert vsd_command[vsd_command.index("--threads") + 1] == "16"
    assert vsd_command[vsd_command.index("--retries") + 1] == "10"
    assert vsd_command[vsd_command.index("--output") + 1] == str(tmp_path / "movie.mp4.part")
    assert VSDEngine.parse_progress("PT: 8/20 speed %:40.0") == pytest.approx(0.4)
    assert N_m3u8DLEngine.parse_progress("completed 64.7%") == pytest.approx(0.647)


def test_engine_reads_carriage_return_progress_and_enforces_watchdog(
    monkeypatch, tmp_path: Path
):
    engine = VSDEngine(tmp_path)
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
            return None

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> None:
            self.wait_calls += 1
            raise subprocess.TimeoutExpired("cmd", timeout if timeout is not None else 0)

    seen: list[int] = []
    monotonic_state = {"value": 0.0}
    kill_state = {"sigkill": False}

    def fake_monotonic() -> float:
        value = monotonic_state["value"]
        monotonic_state["value"] += 0.25
        return value

    def fake_sleep(seconds: float) -> None:
        pass

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


def test_vsd_download_uses_mp4_stage_before_part_output(monkeypatch, tmp_path: Path):
    engine = VSDEngine(tmp_path / "plugin-data")
    requested_output = tmp_path / "movie.mp4.part"
    captured = {}

    monkeypatch.setattr(engine._installer, "ensure_binary", lambda: Path("/bin/vsd"))

    def run_command(command, **_kwargs):
        stage_output = Path(command[command.index("--output") + 1])
        captured["stage_output"] = stage_output
        assert stage_output.name == "media.mp4"
        assert str(stage_output).startswith(str(tmp_path / "plugin-data"))
        stage_output.write_bytes(b"muxed")

    monkeypatch.setattr(engine, "_run_command", run_command)

    result = engine.download(
        "https://example.test/index.m3u8",
        requested_output,
        task_id="vsd-stage",
        ffmpeg_path="ffmpeg",
        control_event=None,
        progress_callback=None,
    )

    assert result == requested_output
    assert requested_output.read_bytes() == b"muxed"
    assert not captured["stage_output"].exists()


def test_vsd_cleanup_removes_stage_and_download_cache(tmp_path: Path):
    engine = VSDEngine(tmp_path / "plugin-data")
    stage = engine._cache_root("task") / "vsd-stage"
    cache = engine.task_cache_dir("task")
    stage.mkdir(parents=True)
    cache.mkdir(parents=True)
    (stage / "media.mp4").write_bytes(b"stage")
    (cache / "segment.ts").write_bytes(b"cache")

    engine.cleanup_task("task")

    assert not engine._cache_root("task").exists()


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
