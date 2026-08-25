"""Managed VOD M3U8 download-engine adapters.

The plugin deliberately keeps the executable download/install boundary here so
the queue can retain its serial scheduling, MoviePilot projection and ffmpeg
seam.  Only pinned, verified release archives are installed under the plugin
data directory; an unavailable engine is a normal signal for the next fallback.
"""

from __future__ import annotations

import codecs
import errno
import hashlib
import hmac
import logging
import os
import platform
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterator, Optional, Sequence, Tuple


LOGGER = logging.getLogger("LunaTVSource")


class M3U8EngineError(RuntimeError):
    """An engine could not complete the requested VOD download."""


class M3U8EngineUnavailable(M3U8EngineError):
    """No verified executable is available for the current host."""


class M3U8EngineCancelled(M3U8EngineError):
    """The queue requested a safe subprocess termination."""


class M3U8EngineInstallError(M3U8EngineUnavailable):
    """A pinned executable could not be installed safely."""


@dataclass(frozen=True)
class ReleaseAsset:
    """Pinned official release artifact for one host platform."""

    filename: str
    sha256: str
    url: str


@dataclass(frozen=True)
class EngineSpec:
    """The fixed executable contract for one external engine."""

    name: str
    executable: str
    assets: Dict[Tuple[str, str], ReleaseAsset]


N_M3U8DL_RE_VERSION = "v0.5.1-beta"
VSD_VERSION = "0.5.0"


def _github_release_url(repository: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{filename}"


N_M3U8DL_RE_SPEC = EngineSpec(
    name="N_m3u8DL-RE",
    executable="N_m3u8DL-RE",
    assets={
        ("linux", "x86_64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz",
            "2acce91b64af3ee676a32d1002e1382840d81f430e1b7f8d5b151ce1eb6fb590",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz",
            ),
        ),
        ("linux", "aarch64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_linux-arm64_20251029.tar.gz",
            "b9cce9978e94fd8ce509ee86a6543cccffeb0ee5b7b7aeff1314104265ac65ad",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_linux-arm64_20251029.tar.gz",
            ),
        ),
        ("darwin", "x86_64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_osx-x64_20251029.tar.gz",
            "fb0d9fd6c18b08a5c55e49f60d3c219471196bd05bf15e58f318a44da500f65a",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_osx-x64_20251029.tar.gz",
            ),
        ),
        ("darwin", "aarch64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_osx-arm64_20251029.tar.gz",
            "537866d7d03c9aed04c910014bceae26a3db494c1d1edae9c59ddaaa29b0a1c7",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_osx-arm64_20251029.tar.gz",
            ),
        ),
    },
)


VSD_SPEC = EngineSpec(
    name="vsd",
    executable="vsd",
    assets={
        ("linux", "x86_64"): ReleaseAsset(
            "vsd-0.5.0-x86_64-unknown-linux-musl.tar.xz",
            "bab9b5b1a02b30afdbf44b58aa9b245d54caf8f723189bb9cc4dca4872c1455b",
            _github_release_url(
                "clitic/vsd",
                "vsd-0.5.0",
                "vsd-0.5.0-x86_64-unknown-linux-musl.tar.xz",
            ),
        ),
        ("linux", "aarch64"): ReleaseAsset(
            "vsd-0.5.0-aarch64-unknown-linux-musl.tar.xz",
            "c435f822f11da61dee85732a8eadf93a3e138041100c552c6826addee53951c6",
            _github_release_url(
                "clitic/vsd",
                "vsd-0.5.0",
                "vsd-0.5.0-aarch64-unknown-linux-musl.tar.xz",
            ),
        ),
        ("darwin", "aarch64"): ReleaseAsset(
            "vsd-0.5.0-aarch64-apple-darwin.tar.xz",
            "55fa01823ca3566e91080e9965e1d75fa53626d6be60b10671f250de8cd34f64",
            _github_release_url(
                "clitic/vsd",
                "vsd-0.5.0",
                "vsd-0.5.0-aarch64-apple-darwin.tar.xz",
            ),
        ),
    },
)


_ARCH_ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}
_INSTALL_LOCKS: Dict[str, threading.Lock] = {}
_INSTALL_LOCKS_GUARD = threading.Lock()
_PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_FRACTION_RE = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
_SECRET_RE = re.compile(
    r"(?i)(cookie|authorization|token|access[_-]?key|signature)\s*([=:])\s*([^\s&;,]+)"
)


def normalized_platform(
    system: Optional[str] = None, machine: Optional[str] = None
) -> Tuple[str, str]:
    """Return the release-map key for a host without guessing unsupported OSes."""

    normalized_system = (system or platform.system()).strip().lower()
    normalized_machine = _ARCH_ALIASES.get(
        (machine or platform.machine()).strip().lower(),
        (machine or platform.machine()).strip().lower(),
    )
    return normalized_system, normalized_machine


def asset_for_spec(
    spec: EngineSpec, system: Optional[str] = None, machine: Optional[str] = None
) -> Optional[ReleaseAsset]:
    return spec.assets.get(normalized_platform(system, machine))


def _safe_error_text(value: object) -> str:
    """Do not surface credentials that an external program might echo."""

    text = _SECRET_RE.sub(r"\1\2<redacted>", str(value or ""))
    return text[-1200:]


class ManagedBinaryInstaller:
    """Install one pinned archive into a plugin-owned ``bin`` directory."""

    _MAX_MEMBER_BYTES = 1024 * 1024 * 1024

    def __init__(self, data_path: Path, spec: EngineSpec) -> None:
        self.data_path = Path(data_path)
        self.spec = spec

    @property
    def bin_dir(self) -> Path:
        return self.data_path / "bin"

    @property
    def managed_path(self) -> Path:
        return self.bin_dir / self.spec.executable

    @property
    def manifest_path(self) -> Path:
        """Digest recorded at install time for the managed executable."""
        return self.bin_dir / f".{self.spec.executable}.sha256"

    def asset(
        self, system: Optional[str] = None, machine: Optional[str] = None
    ) -> Optional[ReleaseAsset]:
        return asset_for_spec(self.spec, system, machine)

    @staticmethod
    def _is_executable(path: Path) -> bool:
        """Return true only for an executable, unlinked regular file."""
        try:
            file_stat = path.lstat()
        except OSError:
            return False
        return (
            stat.S_ISREG(file_stat.st_mode)
            and file_stat.st_nlink == 1
            and os.access(path, os.X_OK)
        )

    @staticmethod
    def _digest_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)

    def _require_safe_bin_dir(self) -> Path:
        """Create the plugin bin directory without following a symlink."""
        directory = self.bin_dir
        if directory.exists() or directory.is_symlink():
            if directory.is_symlink() or not directory.is_dir():
                raise M3U8EngineInstallError("managed binary directory is unsafe")
        else:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise M3U8EngineInstallError(
                    "managed binary directory is unavailable"
                ) from exc
        if directory.is_symlink() or not directory.is_dir():
            raise M3U8EngineInstallError("managed binary directory is unsafe")
        return directory

    def _read_manifest_digest(self) -> Optional[str]:
        manifest = self.manifest_path
        try:
            file_stat = manifest.lstat()
        except OSError:
            return None
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            return None
        try:
            digest = manifest.read_text(encoding="ascii")[:129].strip().lower()
        except (OSError, UnicodeDecodeError):
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        return digest

    def _managed_binary_is_verified(self) -> bool:
        if not self._is_executable(self.managed_path):
            return False
        expected = self._read_manifest_digest()
        if expected is None:
            return False
        try:
            return hmac.compare_digest(self._digest_file(self.managed_path), expected)
        except OSError:
            return False

    @contextmanager
    def _installation_lock(self) -> Iterator[None]:
        """Serialize installers in-process and, where available, cross-process."""

        directory = self._require_safe_bin_dir()
        key = str(directory.absolute())
        with _INSTALL_LOCKS_GUARD:
            lock = _INSTALL_LOCKS.setdefault(key, threading.Lock())
        lock.acquire()
        lock_file = None
        try:
            lock_path = directory / f".{self.spec.executable}.install.lock"
            if lock_path.is_symlink():
                raise M3U8EngineInstallError("managed install lock is unsafe")
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(lock_path, flags, 0o600)
            except OSError as exc:
                raise M3U8EngineInstallError(
                    "managed install lock is unavailable"
                ) from exc
            lock_file = os.fdopen(descriptor, "a+b")
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            yield
        finally:
            if lock_file is not None:
                try:
                    try:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except (ImportError, OSError):
                        pass
                    lock_file.close()
                except OSError:
                    pass
            lock.release()

    def _download_archive(self, asset: ReleaseAsset) -> Path:
        """Stream an archive to a private temp file while checking its digest."""

        directory = self._require_safe_bin_dir()
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{self.spec.executable}-", suffix=".download", dir=directory
        )
        archive_path = Path(raw_path)
        digest = hashlib.sha256()
        response = None
        complete = False
        try:
            request = urllib.request.Request(
                asset.url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": "MoviePilot-LunaTV/1.0",
                },
            )
            response = urllib.request.urlopen(request, timeout=60)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    stream.write(chunk)
            if digest.hexdigest().lower() != asset.sha256.lower():
                raise M3U8EngineInstallError("release checksum mismatch")
            complete = True
            return archive_path
        except M3U8EngineInstallError:
            raise
        except Exception as exc:
            raise M3U8EngineInstallError("release download failed") from exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if not complete:
                try:
                    archive_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _write_manifest(self, digest: str) -> None:
        """Atomically record the digest of the installed executable."""
        directory = self._require_safe_bin_dir()
        manifest = self.manifest_path
        if manifest.is_symlink():
            raise M3U8EngineInstallError("managed checksum manifest is unsafe")
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{self.spec.executable}-",
            suffix=".sha256",
            dir=directory,
        )
        temporary_path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                descriptor = -1
                stream.write(f"{digest}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            if manifest.is_symlink():
                raise M3U8EngineInstallError("managed checksum manifest is unsafe")
            os.replace(temporary_path, manifest)
        except M3U8EngineInstallError:
            raise
        except OSError as exc:
            raise M3U8EngineInstallError(
                "managed checksum manifest could not be written"
            ) from exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _extract_executable(self, archive_path: Path) -> None:
        """Safely extract exactly the advertised executable and replace atomically."""

        directory = self._require_safe_bin_dir()
        if archive_path.is_symlink() or not archive_path.is_file():
            raise M3U8EngineInstallError("release archive is unsafe")
        temporary_path: Optional[Path] = None
        try:
            with tarfile.open(archive_path, mode="r:*") as archive:
                candidates = []
                for member in archive.getmembers():
                    member_path = PurePosixPath(member.name)
                    if (
                        not member.name
                        or member_path.is_absolute()
                        or ".." in member_path.parts
                    ):
                        raise M3U8EngineInstallError("unsafe release archive path")
                    if member.issym() or member.islnk():
                        raise M3U8EngineInstallError("unsafe release archive link")
                    if member.isdir():
                        continue
                    if not member.isfile() or member.size < 0:
                        raise M3U8EngineInstallError("unsafe release archive content")
                    if member.size > self._MAX_MEMBER_BYTES:
                        raise M3U8EngineInstallError("release executable is too large")
                    if member_path.name == self.spec.executable:
                        candidates.append(member)
                if len(candidates) != 1:
                    raise M3U8EngineInstallError(
                        "release archive lacks one expected executable"
                    )
                source = archive.extractfile(candidates[0])
                if source is None:
                    raise M3U8EngineInstallError("release executable could not be read")
                descriptor, raw_path = tempfile.mkstemp(
                    prefix=f".{self.spec.executable}-", suffix=".install", dir=directory
                )
                temporary_path = Path(raw_path)
                with source, os.fdopen(descriptor, "wb") as target:
                    while True:
                        chunk = source.read(256 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                os.chmod(temporary_path, 0o755)
                if not self._is_executable(temporary_path):
                    raise M3U8EngineInstallError("release executable is not runnable")
                executable_digest = self._digest_file(temporary_path)
                if self.managed_path.is_symlink():
                    raise M3U8EngineInstallError("managed executable path is unsafe")
                os.replace(temporary_path, self.managed_path)
                temporary_path = None
                self._write_manifest(executable_digest)
        except M3U8EngineInstallError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise M3U8EngineInstallError("release archive could not be unpacked") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def ensure_binary(self) -> Path:
        """Return only a verified, fixed-version managed executable."""

        asset = self.asset()
        if asset is None:
            raise M3U8EngineUnavailable("unsupported platform")
        self._require_safe_bin_dir()
        if self._managed_binary_is_verified():
            return self.managed_path
        with self._installation_lock():
            if self._managed_binary_is_verified():
                return self.managed_path
            archive_path: Optional[Path] = None
            try:
                archive_path = self._download_archive(asset)
                self._extract_executable(archive_path)
                if not self._managed_binary_is_verified():
                    raise M3U8EngineInstallError(
                        "installed executable checksum verification failed"
                    )
                return self.managed_path
            finally:
                if archive_path is not None:
                    try:
                        archive_path.unlink(missing_ok=True)
                    except OSError:
                        pass


class _BaseM3U8Engine:
    """Common process, cache and cleanup behavior for a VOD engine."""

    name = "m3u8"
    spec: EngineSpec
    PROCESS_TOTAL_TIMEOUT_SECONDS = 6 * 60 * 60
    PROCESS_NO_PROGRESS_TIMEOUT_SECONDS = 15 * 60
    PROCESS_POLL_INTERVAL_SECONDS = 0.25

    def __init__(self, data_path: Path, logger: Optional[logging.Logger] = None) -> None:
        self.data_path = Path(data_path)
        self._logger = logger or LOGGER
        self._installer = ManagedBinaryInstaller(self.data_path, self.spec)

    @classmethod
    def asset_for_current_platform(
        cls, system: Optional[str] = None, machine: Optional[str] = None
    ) -> Optional[ReleaseAsset]:
        return asset_for_spec(cls.spec, system, machine)

    @staticmethod
    def _task_digest(task_id: str) -> str:
        return hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()

    def task_cache_dir(self, task_id: str) -> Path:
        return self.data_path / "m3u8-cache" / self._task_digest(task_id) / self.name

    def _cache_root(self, task_id: str) -> Path:
        return self.task_cache_dir(task_id).parent

    @staticmethod
    def _ensure_real_directory(path: Path, label: str) -> Path:
        """Create a direct child only when it is a real directory."""
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_dir():
                raise M3U8EngineError(f"{label} is unsafe")
        else:
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise M3U8EngineError(f"{label} is unavailable") from exc
        if path.is_symlink() or not path.is_dir():
            raise M3U8EngineError(f"{label} is unsafe")
        return path

    def _prepare_task_cache(self, task_id: str) -> Path:
        base = self.data_path / "m3u8-cache"
        task_root = base / self._task_digest(task_id)
        self._ensure_real_directory(base, "M3U8 cache directory")
        self._ensure_real_directory(task_root, "M3U8 task cache directory")
        return self._ensure_real_directory(
            task_root / self.name,
            "M3U8 engine cache directory",
        )

    @staticmethod
    def _is_safe_regular_file(path: Path) -> bool:
        try:
            file_stat = path.lstat()
        except OSError:
            return False
        return stat.S_ISREG(file_stat.st_mode) and file_stat.st_nlink == 1

    def cleanup_task(self, task_id: str, output_parent: Optional[Path] = None) -> None:
        """Delete exactly one completed/removed task's controlled cache."""

        cache_dir = self.task_cache_dir(task_id)
        cache_root = self._cache_root(task_id)
        self._remove_controlled_tree(cache_dir, cache_root)
        try:
            cache_root.rmdir()
        except OSError:
            pass

    @staticmethod
    def _remove_controlled_tree(path: Path, parent: Path) -> None:
        """Remove only a lexical child and never resolve a symlink target."""
        try:
            relative = path.relative_to(parent)
        except ValueError:
            return
        if not relative.parts or any(part == ".." for part in relative.parts):
            return
        if parent.is_symlink():
            return
        try:
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            pass

    @staticmethod
    def parse_progress(line: str) -> Optional[float]:
        """Parse a conventional engine percentage or segment fraction."""

        matches = _PERCENT_RE.findall(line)
        if matches:
            try:
                return max(0.0, min(1.0, float(matches[-1]) / 100.0))
            except ValueError:
                return None
        match = _FRACTION_RE.search(line)
        if match:
            try:
                current, total = int(match.group(1)), int(match.group(2))
                if total > 0:
                    return max(0.0, min(0.99, current / total))
            except ValueError:
                return None
        return None

    @staticmethod
    def _cache_progress(cache_dir: Path, expected_segments: int) -> Optional[float]:
        if (
            expected_segments <= 0
            or cache_dir.is_symlink()
            or not cache_dir.is_dir()
        ):
            return None
        try:
            count = 0
            for current_root, directories, filenames in os.walk(
                cache_dir, followlinks=False
            ):
                root_path = Path(current_root)
                directories[:] = [
                    name
                    for name in directories
                    if not (root_path / name).is_symlink()
                ]
                count += sum(
                    1
                    for name in filenames
                    if _BaseM3U8Engine._is_safe_regular_file(root_path / name)
                )
        except OSError:
            return None
        if count <= 0:
            return None
        return min(0.95, count / max(expected_segments, 1))

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        """Terminate the engine and, on POSIX, its entire process group."""
        if process.poll() is not None:
            return

        def signal_group(signal_number: int) -> bool:
            if os.name != "posix":
                return False
            try:
                os.killpg(process.pid, signal_number)
                return True
            except (AttributeError, OSError, ProcessLookupError):
                return False

        if not signal_group(signal.SIGTERM):
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        if not signal_group(signal.SIGKILL):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _raise_if_cancelled(control_event: Optional[threading.Event]) -> None:
        if control_event is not None and control_event.is_set():
            raise M3U8EngineCancelled("download cancelled")

    def _run_command(
        self,
        command: Sequence[str],
        *,
        cache_dir: Path,
        control_event: Optional[threading.Event],
        progress_callback: Optional[Callable[[float], None]],
        expected_segments: int = 0,
    ) -> None:
        """Run an engine with nonblocking CR/LF parsing and watchdogs."""
        self._raise_if_cancelled(control_event)
        selector = selectors.DefaultSelector()
        process: Optional[subprocess.Popen] = None
        output_tail = ""
        buffers = {"stdout": "", "stderr": ""}
        decoders = {
            "stdout": codecs.getincrementaldecoder("utf-8")("replace"),
            "stderr": codecs.getincrementaldecoder("utf-8")("replace"),
        }
        started_at = time.monotonic()
        last_activity = started_at
        last_cache_check = started_at
        last_cache_progress = 0.0
        last_progress = 0.0

        def record_line(stream_name: str, line: str) -> None:
            del stream_name
            nonlocal last_activity, last_progress, output_tail
            if not line:
                return
            last_activity = time.monotonic()
            output_tail = (output_tail + line + "\n")[-12000:]
            parsed = self.parse_progress(line)
            if progress_callback is not None and parsed is not None:
                value = max(last_progress, parsed)
                if value > last_progress:
                    last_progress = value
                    progress_callback(value)

        def consume(stream_name: str, data: bytes, *, final: bool = False) -> None:
            nonlocal last_activity
            if data:
                last_activity = time.monotonic()
            decoded = decoders[stream_name].decode(data, final=final)
            text = buffers[stream_name] + decoded
            if not text:
                return
            if final:
                lines = [text]
                buffers[stream_name] = ""
            elif text[-1:] in {"\r", "\n"}:
                lines = re.split(r"[\r\n]+", text)
                buffers[stream_name] = ""
            else:
                parts = re.split(r"[\r\n]+", text)
                lines = parts[:-1]
                buffers[stream_name] = parts[-1]
            for line in lines:
                record_line(stream_name, line)

        try:
            popen_kwargs: Dict[str, object] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "bufsize": 0,
            }
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(list(command), **popen_kwargs)
            streams = {
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
            for stream_name, stream in streams.items():
                if stream is None:
                    continue
                try:
                    os.set_blocking(stream.fileno(), False)
                except (AttributeError, OSError):
                    pass
                selector.register(stream, selectors.EVENT_READ, stream_name)
            if progress_callback is not None:
                progress_callback(0.0)

            while True:
                now = time.monotonic()
                returncode = process.poll()
                if returncode is None:
                    self._raise_if_cancelled(control_event)
                    if now - started_at > self.PROCESS_TOTAL_TIMEOUT_SECONDS:
                        self._terminate(process)
                        raise M3U8EngineError(f"{self.name} process timed out")
                    if now - last_activity > self.PROCESS_NO_PROGRESS_TIMEOUT_SECONDS:
                        self._terminate(process)
                        raise M3U8EngineError(
                            f"{self.name} process made no progress"
                        )

                for key, _ in selector.select(timeout=self.PROCESS_POLL_INTERVAL_SECONDS):
                    stream = key.fileobj
                    try:
                        data = os.read(stream.fileno(), 64 * 1024)
                    except BlockingIOError:
                        continue
                    except OSError:
                        data = b""
                    if data:
                        consume(key.data, data)
                        continue
                    try:
                        selector.unregister(stream)
                    except Exception:
                        pass
                    consume(key.data, b"", final=True)

                now = time.monotonic()
                if now - last_cache_check >= 1.0:
                    last_cache_check = now
                    cache_progress = self._cache_progress(cache_dir, expected_segments)
                    if cache_progress is not None:
                        if cache_progress > last_cache_progress:
                            last_activity = now
                            last_cache_progress = cache_progress
                        if progress_callback is not None and cache_progress > last_progress:
                            last_progress = cache_progress
                            progress_callback(cache_progress)

                if process.poll() is not None and not selector.get_map():
                    break

            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate(process)
                raise M3U8EngineError(f"{self.name} process did not exit")

            # Exit code 0 is authoritative if a pause arrives after the child exits.
            if process.returncode == 0:
                return
            if control_event is not None and control_event.is_set():
                raise M3U8EngineCancelled("download cancelled")
            detail = _safe_error_text(output_tail)
            raise M3U8EngineError(detail or f"{self.name} exited {process.returncode}")
        except M3U8EngineCancelled:
            if process is not None:
                self._terminate(process)
            raise
        except M3U8EngineError:
            raise
        except OSError as exc:
            raise M3U8EngineUnavailable(f"{self.name} could not start") from exc
        finally:
            if process is not None and process.poll() is None:
                self._terminate(process)
            selector.close()


class N_m3u8DLEngine(_BaseM3U8Engine):
    """Pinned N_m3u8DL-RE v0.5.1-beta adapter for VOD HLS."""

    name = "n_m3u8dl_re"
    spec = N_M3U8DL_RE_SPEC
    _MEDIA_SUFFIXES = {".mp4", ".mkv", ".ts", ".m4a", ".mov", ".webm"}

    def stage_dir(
        self, task_id: str, output_parent: Optional[Path] = None
    ) -> Path:
        """Stage only below the plugin task cache, never in the media tree."""
        del output_parent
        return self._cache_root(task_id) / "n_m3u8dl-re-stage"

    def _prepare_stage_dir(self, task_id: str) -> Path:
        self._prepare_task_cache(task_id)
        return self._ensure_real_directory(
            self.stage_dir(task_id),
            "N_m3u8DL-RE stage directory",
        )

    def cleanup_task(self, task_id: str, output_parent: Optional[Path] = None) -> None:
        del output_parent
        cache_root = self._cache_root(task_id)
        self._remove_controlled_tree(self.stage_dir(task_id), cache_root)
        super().cleanup_task(task_id)

    def _output_from_stage(self, stage_dir: Path) -> Path:
        if stage_dir.is_symlink() or not stage_dir.is_dir():
            raise M3U8EngineError("N_m3u8DL-RE stage directory is unsafe")
        candidates = []
        candidate = stage_dir / "media.mp4"
        if candidate.exists() or candidate.is_symlink():
            if (
                not self._is_safe_regular_file(candidate)
                or candidate.stat().st_size <= 0
            ):
                raise M3U8EngineError("N_m3u8DL-RE stage output is unsafe")
            candidates.append(candidate)
        if len(candidates) != 1:
            raise M3U8EngineError(
                "N_m3u8DL-RE did not produce one expected output"
            )
        return candidates[0]

    @staticmethod
    def _move_stage_output(candidate: Path, output: Path) -> None:
        """Move stage output atomically, including cross-filesystem media roots."""
        try:
            os.replace(candidate, output)
            return
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".transfer",
            dir=output.parent,
        )
        temporary_path = Path(raw_path)
        try:
            source_mode = stat.S_IMODE(candidate.stat().st_mode)
            with candidate.open("rb") as source, os.fdopen(descriptor, "wb") as target:
                descriptor = -1
                shutil.copyfileobj(source, target, length=1024 * 1024)
                os.fchmod(target.fileno(), source_mode)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_path, output)
            temporary_path = None
            candidate.unlink()
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def command(
        self,
        binary: Path,
        url: str,
        cache_dir: Path,
        stage_dir: Path,
        ffmpeg_path: str,
    ) -> Sequence[str]:
        return [
            str(binary),
            url,
            "--auto-select",
            "--thread-count",
            "16",
            "--download-retry-count",
            "3",
            "--tmp-dir",
            str(cache_dir),
            "--save-dir",
            str(stage_dir),
            "--save-name",
            "media",
            "--mux-after-done",
            "format=mp4",
            "--ffmpeg-binary-path",
            ffmpeg_path or "ffmpeg",
            "--no-ansi-color",
        ]

    def download(
        self,
        url: str,
        output: Path,
        *,
        task_id: str,
        ffmpeg_path: str,
        control_event: Optional[threading.Event],
        progress_callback: Optional[Callable[[float], None]],
        expected_segments: int = 0,
    ) -> Path:
        self._raise_if_cancelled(control_event)
        binary = self._installer.ensure_binary()
        self._raise_if_cancelled(control_event)
        cache_dir = self._prepare_task_cache(task_id)
        stage_dir = self._prepare_stage_dir(task_id)
        self._raise_if_cancelled(control_event)
        self._run_command(
            self.command(binary, url, cache_dir, stage_dir, ffmpeg_path),
            cache_dir=cache_dir,
            control_event=control_event,
            progress_callback=progress_callback,
            expected_segments=expected_segments,
        )
        candidate = self._output_from_stage(stage_dir)
        self._move_stage_output(candidate, output)
        return output


class VSDEngine(_BaseM3U8Engine):
    """Pinned VSD 0.5.0 adapter used only after N_m3u8DL-RE fails."""

    name = "vsd"
    spec = VSD_SPEC
    _PT_RE = re.compile(r"PT\s*:\s*(\d+)\s*/\s*(\d+).*?%\s*:\s*(\d+(?:\.\d+)?)", re.I)

    @staticmethod
    def parse_progress(line: str) -> Optional[float]:
        match = VSDEngine._PT_RE.search(line)
        if match:
            try:
                percent = float(match.group(3)) / 100.0
                return max(0.0, min(1.0, percent))
            except ValueError:
                return None
        return _BaseM3U8Engine.parse_progress(line)

    def command(
        self, binary: Path, url: str, output: Path, cache_dir: Path
    ) -> Sequence[str]:
        return [
            str(binary),
            "save",
            url,
            "--output",
            str(output),
            "--directory",
            str(cache_dir),
            "--threads",
            "16",
            "--retries",
            "10",
        ]

    def _prepare_stage_output(self, task_id: str) -> Path:
        """Give VSD an MP4 suffix so its internal ffmpeg can select a muxer."""
        self._prepare_task_cache(task_id)
        stage_dir = self._ensure_real_directory(
            self._cache_root(task_id) / "vsd-stage",
            "vsd stage directory",
        )
        output = stage_dir / "media.mp4"
        if output.exists() or output.is_symlink():
            if not self._is_safe_regular_file(output):
                raise M3U8EngineError("vsd stage output is unsafe")
            try:
                output.unlink()
            except OSError as exc:
                raise M3U8EngineError("vsd stage output is unavailable") from exc
        return output

    def cleanup_task(self, task_id: str, output_parent: Optional[Path] = None) -> None:
        del output_parent
        cache_root = self._cache_root(task_id)
        self._remove_controlled_tree(cache_root / "vsd-stage", cache_root)
        super().cleanup_task(task_id)

    def download(
        self,
        url: str,
        output: Path,
        *,
        task_id: str,
        ffmpeg_path: str,
        control_event: Optional[threading.Event],
        progress_callback: Optional[Callable[[float], None]],
        expected_segments: int = 0,
    ) -> Path:
        del ffmpeg_path
        self._raise_if_cancelled(control_event)
        binary = self._installer.ensure_binary()
        self._raise_if_cancelled(control_event)
        cache_dir = self._prepare_task_cache(task_id)
        stage_output = self._prepare_stage_output(task_id)
        self._raise_if_cancelled(control_event)
        self._run_command(
            self.command(binary, url, stage_output, cache_dir),
            cache_dir=cache_dir,
            control_event=control_event,
            progress_callback=progress_callback,
            expected_segments=expected_segments,
        )
        if not self._is_safe_regular_file(stage_output) or stage_output.stat().st_size <= 0:
            raise M3U8EngineError("vsd did not produce a safe output")
        N_m3u8DLEngine._move_stage_output(stage_output, output)
        return output
