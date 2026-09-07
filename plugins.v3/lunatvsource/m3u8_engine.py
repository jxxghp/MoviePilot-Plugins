"""Managed VOD M3U8 download-engine adapters.

The plugin deliberately keeps the executable download/install boundary here so
the queue can retain its serial scheduling, MoviePilot projection and ffmpeg
seam.  Only pinned, verified release archives are installed under the plugin
data directory; no alternate downloader or unverified mirror is used.
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
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterator, Optional, Sequence, Tuple


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
    executable_sha256: str
    url: str


@dataclass(frozen=True)
class EngineSpec:
    """The fixed executable contract for one external engine."""

    name: str
    executable: str
    assets: Dict[Tuple[str, str], ReleaseAsset]


N_M3U8DL_RE_VERSION = "v0.5.1-beta"
BUNDLED_ASSET_DIR = Path(__file__).resolve().parent / "vendor" / "n_m3u8dl_re"


def _github_release_url(repository: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{filename}"


N_M3U8DL_RE_SPEC = EngineSpec(
    name="N_m3u8DL-RE",
    executable="N_m3u8DL-RE",
    assets={
        ("linux", "x86_64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz",
            "2acce91b64af3ee676a32d1002e1382840d81f430e1b7f8d5b151ce1eb6fb590",
            "d2fa5b4b79f243320c509a85835327a520d8c160c600d99921e764bfc519fec7",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz",
            ),
        ),
        ("linux", "aarch64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_linux-arm64_20251029.tar.gz",
            "b9cce9978e94fd8ce509ee86a6543cccffeb0ee5b7b7aeff1314104265ac65ad",
            "9cd4ef3923701cc96efb4ef4e4dc7000b42b54995a3aa27f0e363d84e1816a35",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_linux-arm64_20251029.tar.gz",
            ),
        ),
        ("darwin", "x86_64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_osx-x64_20251029.tar.gz",
            "fb0d9fd6c18b08a5c55e49f60d3c219471196bd05bf15e58f318a44da500f65a",
            "5c8c8b7f0794f9d4350cdcf2eb662993d8ec23a967c5e8b230a431144eca87e3",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_osx-x64_20251029.tar.gz",
            ),
        ),
        ("darwin", "aarch64"): ReleaseAsset(
            "N_m3u8DL-RE_v0.5.1-beta_osx-arm64_20251029.tar.gz",
            "537866d7d03c9aed04c910014bceae26a3db494c1d1edae9c59ddaaa29b0a1c7",
            "90f5b7a86182c1c985ea842936ccb1e6313cd771231b9c7adade255af74dead7",
            _github_release_url(
                "nilaoda/N_m3u8DL-RE",
                N_M3U8DL_RE_VERSION,
                "N_m3u8DL-RE_v0.5.1-beta_osx-arm64_20251029.tar.gz",
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
_CREDENTIAL_LINE_RE = re.compile(
    r"(?im)((?:\b(?:proxy-)?authorization|set-cookie|cookie)\b[\"']?\s*[=:]\s*[\"']?)[^\r\n]*"
)
_INLINE_SECRET_RE = re.compile(
    r"(?im)((?:\b(?:token|access[_-]?key|signature)\b[\"']?\s*[=:]\s*[\"']?))[^\r\n]*"
)
_AD_KEYWORD_LINE_RE = re.compile(
    r"(?im)^(\s*(?:User customed Ad keyword|用户自定义广告分片URL关键字|"
    r"用戶自定義廣告分片URL關鍵字)\s*[:：]\s*).*?$"
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

    text = str(value or "")
    text = _CREDENTIAL_LINE_RE.sub(r"\1<redacted>", text)
    text = _INLINE_SECRET_RE.sub(r"\1<redacted>", text)
    text = _AD_KEYWORD_LINE_RE.sub(r"\1<redacted>", text)
    return text[-1200:]


def _raise_if_cancelled(control_event: Optional[threading.Event]) -> None:
    if control_event is not None and control_event.is_set():
        raise M3U8EngineCancelled("download cancelled")


class ManagedBinaryInstaller:
    """Install one pinned archive into a plugin-owned ``bin`` directory."""

    _MAX_MEMBER_BYTES = 1024 * 1024 * 1024
    DOWNLOAD_TOTAL_TIMEOUT_SECONDS = 15 * 60
    DOWNLOAD_IO_TIMEOUT_SECONDS = 10.0
    DOWNLOAD_CONNECT_ATTEMPTS = 3
    DOWNLOAD_RETRY_DELAY_SECONDS = 0.5
    DOWNLOAD_CHUNK_BYTES = 64 * 1024
    INSTALL_LOCK_POLL_SECONDS = 0.1

    def __init__(
        self,
        data_path: Path,
        spec: EngineSpec,
        bundled_asset_dir: Optional[Path] = None,
    ) -> None:
        self.data_path = Path(data_path)
        self.spec = spec
        self.bundled_asset_dir = Path(bundled_asset_dir or BUNDLED_ASSET_DIR)

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
        asset = self.asset()
        if asset is None:
            return False
        try:
            return hmac.compare_digest(self._digest_file(self.managed_path), asset.executable_sha256)
        except OSError:
            return False


    @contextmanager
    def _installation_lock(
        self, control_event: Optional[threading.Event] = None
    ) -> Iterator[None]:
        """Serialize installers while allowing cancelled waiters to leave."""

        directory = self._require_safe_bin_dir()
        key = str(directory.absolute())
        while True:
            _raise_if_cancelled(control_event)
            if _INSTALL_LOCKS_GUARD.acquire(timeout=self.INSTALL_LOCK_POLL_SECONDS):
                try:
                    lock = _INSTALL_LOCKS.setdefault(key, threading.Lock())
                finally:
                    _INSTALL_LOCKS_GUARD.release()
                break

        lock_acquired = False
        lock_file = None
        flock_acquired = False
        try:
            while not lock_acquired:
                _raise_if_cancelled(control_event)
                lock_acquired = lock.acquire(timeout=self.INSTALL_LOCK_POLL_SECONDS)

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
            except ImportError:
                fcntl = None
            if fcntl is not None:
                while True:
                    _raise_if_cancelled(control_event)
                    try:
                        fcntl.flock(
                            lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                        )
                        flock_acquired = True
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN):
                            break
                        time.sleep(self.INSTALL_LOCK_POLL_SECONDS)
            _raise_if_cancelled(control_event)
            yield
        finally:
            if lock_file is not None:
                try:
                    if flock_acquired:
                        try:
                            import fcntl

                            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                        except (ImportError, OSError):
                            pass
                    lock_file.close()
                except OSError:
                    pass
            if lock_acquired:
                lock.release()

    def _download_io_timeout(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise M3U8EngineInstallError("release download timed out")
        return min(self.DOWNLOAD_IO_TIMEOUT_SECONDS, remaining)

    def _download_archive(
        self,
        asset: ReleaseAsset,
        control_event: Optional[threading.Event] = None,
    ) -> Path:
        """Stream an archive to a private temp file while checking its digest."""

        _raise_if_cancelled(control_event)
        deadline = time.monotonic() + self.DOWNLOAD_TOTAL_TIMEOUT_SECONDS
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
            for attempt in range(self.DOWNLOAD_CONNECT_ATTEMPTS):
                _raise_if_cancelled(control_event)
                try:
                    response = urllib.request.urlopen(
                        request, timeout=self._download_io_timeout(deadline)
                    )
                    break
                except urllib.error.HTTPError:
                    raise
                except (urllib.error.URLError, TimeoutError, OSError):
                    if attempt + 1 >= self.DOWNLOAD_CONNECT_ATTEMPTS:
                        raise
                    delay = min(
                        self.DOWNLOAD_RETRY_DELAY_SECONDS,
                        max(0.0, deadline - time.monotonic()),
                    )
                    if delay <= 0:
                        self._download_io_timeout(deadline)
                    if control_event is None:
                        time.sleep(delay)
                    elif control_event.wait(delay):
                        raise M3U8EngineCancelled("download cancelled")
            if response is None:
                raise M3U8EngineInstallError("release download failed")
            read_chunk = getattr(response, "read1", None)
            if not callable(read_chunk):
                read_chunk = response.read
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                while True:
                    _raise_if_cancelled(control_event)
                    self._download_io_timeout(deadline)
                    chunk = read_chunk(self.DOWNLOAD_CHUNK_BYTES)
                    _raise_if_cancelled(control_event)
                    self._download_io_timeout(deadline)
                    if not chunk:
                        break
                    digest.update(chunk)
                    stream.write(chunk)
            if digest.hexdigest().lower() != asset.sha256.lower():
                raise M3U8EngineInstallError("release checksum mismatch")
            complete = True
            return archive_path
        except (M3U8EngineCancelled, M3U8EngineInstallError):
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

    def _bundled_archive(self, asset: ReleaseAsset) -> Optional[Path]:
        """Return a verified plugin-bundled archive, or none when not shipped."""

        archive_path = self.bundled_asset_dir / asset.filename
        try:
            file_stat = archive_path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise M3U8EngineInstallError(
                "bundled release archive is unavailable"
            ) from exc
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise M3U8EngineInstallError("bundled release archive is unsafe")
        try:
            archive_digest = self._digest_file(archive_path)
        except OSError as exc:
            raise M3U8EngineInstallError(
                "bundled release archive could not be read"
            ) from exc
        if not hmac.compare_digest(archive_digest.lower(), asset.sha256.lower()):
            raise M3U8EngineInstallError("bundled release checksum mismatch")
        return archive_path

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

    def ensure_binary(
        self, control_event: Optional[threading.Event] = None
    ) -> Path:
        """Return only a verified, fixed-version managed executable."""

        _raise_if_cancelled(control_event)
        asset = self.asset()
        if asset is None:
            raise M3U8EngineUnavailable("unsupported platform")
        self._require_safe_bin_dir()
        if self._managed_binary_is_verified():
            return self.managed_path
        with self._installation_lock(control_event):
            _raise_if_cancelled(control_event)
            if self._managed_binary_is_verified():
                return self.managed_path
            archive_path: Optional[Path] = None
            remove_archive = False
            try:
                archive_path = self._bundled_archive(asset)
                if archive_path is None:
                    archive_path = self._download_archive(asset, control_event)
                    remove_archive = True
                _raise_if_cancelled(control_event)
                self._extract_executable(archive_path)
                if not self._managed_binary_is_verified():
                    raise M3U8EngineInstallError(
                        "installed executable checksum verification failed"
                    )
                _raise_if_cancelled(control_event)
                return self.managed_path
            finally:
                if remove_archive and archive_path is not None:
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
    def has_entered_finalize_stage(line: str) -> bool:
        """Return whether engine output confirms final muxing has begun."""
        del line
        return False

    @staticmethod
    def _cache_activity(
        cache_dir: Path, expected_segments: int
    ) -> Optional[tuple[int, float]]:
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
        return count, min(0.95, count / max(expected_segments, 1))

    @staticmethod
    def _cache_progress(cache_dir: Path, expected_segments: int) -> Optional[float]:
        activity = _BaseM3U8Engine._cache_activity(cache_dir, expected_segments)
        if activity is None:
            return None
        return activity[1]

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        """Terminate engine and, on POSIX, its entire process group."""
        _TERMINATE_WINDOW_SECONDS = 5.0
        _TERMINATE_POLL_SECONDS = 0.1

        def _group_exists(pgid: int) -> bool:
            """Return True when process group still exists."""
            if os.name != "posix":
                return True
            try:
                os.killpg(pgid, 0)
                return True
            except ProcessLookupError:
                return False
            except OSError as error:
                if error.errno == errno.ESRCH:
                    return False
                if error.errno == errno.EPERM:
                    return True
                return True

        def _signal_group(signal_number: int) -> bool:
            if os.name != "posix":
                return False
            try:
                os.killpg(process.pid, signal_number)
                return True
            except (AttributeError, ProcessLookupError):
                return False
            except OSError as error:
                if error.errno == errno.ESRCH:
                    return False
                if error.errno == errno.EPERM:
                    return True
                return False

        def _wait_group(deadline: float) -> bool:
            """Return True when group is gone before deadline."""
            while True:
                # Reap the session leader when it exits; otherwise a zombie
                # can keep killpg(..., 0) reporting the group as alive.
                process.poll()
                if not _group_exists(process.pid):
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(min(_TERMINATE_POLL_SECONDS, max(0.0, deadline - time.monotonic())))

        if os.name != "posix":
            try:
                process.terminate()
                process.wait(timeout=_TERMINATE_WINDOW_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
            return

        if _signal_group(signal.SIGTERM):
            if _wait_group(time.monotonic() + _TERMINATE_WINDOW_SECONDS):
                return
        if not _signal_group(signal.SIGKILL):
            return
        _wait_group(time.monotonic() + _TERMINATE_WINDOW_SECONDS)


    @staticmethod
    def _raise_if_cancelled(control_event: Optional[threading.Event]) -> None:
        _raise_if_cancelled(control_event)

    def _run_command(
        self,
        command: Sequence[str],
        *,
        cache_dir: Path,
        control_event: Optional[threading.Event],
        progress_callback: Optional[Callable[[float], None]],
        expected_segments: int = 0,
        use_pty: bool = False,
    ) -> None:
        """Run an engine with nonblocking CR/LF parsing and watchdogs."""
        self._raise_if_cancelled(control_event)
        selector = selectors.DefaultSelector()
        process: Optional[subprocess.Popen] = None
        streams: Dict[str, Any] = {}
        pty_master_fd: Optional[int] = None
        pty_slave_fd: Optional[int] = None
        output_tail = ""
        buffers = {"stdout": "", "stderr": ""}
        decoders = {
            "stdout": codecs.getincrementaldecoder("utf-8")("replace"),
            "stderr": codecs.getincrementaldecoder("utf-8")("replace"),
        }
        started_at = time.monotonic()
        last_progress_at = started_at
        last_cache_check = started_at - 1.0
        last_cache_count = 0
        last_cache_progress = 0.0
        last_parsed_progress = 0.0
        last_progress = 0.0
        download_stage_complete = False

        def process_group_alive() -> bool:
            if process is None:
                return False
            if os.name != "posix":
                return process.poll() is None
            try:
                os.killpg(process.pid, 0)
                return True
            except ProcessLookupError:
                return False
            except OSError as error:
                return error.errno != errno.ESRCH

        def record_line(stream_name: str, line: str) -> None:
            del stream_name
            nonlocal download_stage_complete
            nonlocal last_parsed_progress, last_progress_at, last_progress, output_tail
            if not line:
                return
            output_tail = (output_tail + line + "\n")[-12000:]
            if self.has_entered_finalize_stage(line):
                download_stage_complete = True
            parsed = self.parse_progress(line)
            if parsed is None:
                return
            if parsed <= last_parsed_progress:
                return
            last_parsed_progress = parsed
            last_progress_at = time.monotonic()
            value = max(last_progress, parsed)
            if value <= last_progress:
                return
            last_progress = value
            if progress_callback is not None:
                progress_callback(value)

        def consume(stream_name: str, data: bytes, *, final: bool = False) -> None:
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
            popen_kwargs: Dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "bufsize": 0,
            }
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
                if use_pty:
                    pty_master_fd, pty_slave_fd = os.openpty()
                    try:
                        import fcntl
                        import struct
                        import termios

                        fcntl.ioctl(
                            pty_slave_fd,
                            termios.TIOCSWINSZ,
                            struct.pack("HHHH", 24, 160, 0, 0),
                        )
                    except (ImportError, OSError):
                        pass
                    popen_kwargs["stdout"] = pty_slave_fd
                    popen_kwargs["stderr"] = pty_slave_fd
            elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(list(command), **popen_kwargs)
            if pty_slave_fd is not None:
                os.close(pty_slave_fd)
                pty_slave_fd = None
            if pty_master_fd is not None:
                streams = {
                    "stdout": os.fdopen(pty_master_fd, "rb", buffering=0),
                }
                pty_master_fd = None
            else:
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
                command_finished = (
                    process.poll() is not None
                    and not process_group_alive()
                    and not selector.get_map()
                )
                if not command_finished:
                    self._raise_if_cancelled(control_event)
                    if now - started_at > self.PROCESS_TOTAL_TIMEOUT_SECONDS:
                        self._terminate(process)
                        raise M3U8EngineError(f"{self.name} process timed out")

                for key, _ in selector.select(timeout=self.PROCESS_POLL_INTERVAL_SECONDS):
                    stream = key.fileobj
                    try:
                        data = os.read(stream.fileno(), 64 * 1024)
                    except BlockingIOError:
                        continue
                    except OSError:
                        # Linux PTY masters report EIO when the slave closes.
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
                    cache_activity = self._cache_activity(
                        cache_dir, expected_segments
                    )
                    if cache_activity is not None:
                        cache_count, cache_progress = cache_activity
                        if cache_count > last_cache_count:
                            last_progress_at = now
                        last_cache_count = cache_count
                        if cache_progress > last_cache_progress:
                            last_progress_at = now
                        last_cache_progress = cache_progress
                        if progress_callback is not None and cache_progress > last_progress:
                            last_progress = cache_progress
                            progress_callback(cache_progress)

                if (
                    not download_stage_complete
                    and now - last_progress_at
                    > self.PROCESS_NO_PROGRESS_TIMEOUT_SECONDS
                ):
                    self._terminate(process)
                    raise M3U8EngineError(f"{self.name} process made no progress")

                if (
                    process.poll() is not None
                    and not process_group_alive()
                    and not selector.get_map()
                ):
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
            if process_group_alive():
                self._terminate(process)
            raise
        except M3U8EngineError:
            raise
        except OSError as exc:
            raise M3U8EngineUnavailable(f"{self.name} could not start") from exc
        finally:
            if process_group_alive():
                self._terminate(process)
            selector.close()
            for stream in streams.values():
                try:
                    stream.close()
                except (AttributeError, OSError):
                    pass
            if pty_master_fd is not None:
                os.close(pty_master_fd)
            if pty_slave_fd is not None:
                os.close(pty_slave_fd)


class N_m3u8DLEngine(_BaseM3U8Engine):
    """Pinned N_m3u8DL-RE v0.5.1-beta adapter for VOD HLS."""

    name = "n_m3u8dl_re"
    spec = N_M3U8DL_RE_SPEC
    DEFAULT_THREAD_COUNT = 16
    MIN_THREAD_COUNT = 4
    MAX_THREAD_COUNT = 32
    _MEDIA_SUFFIXES = {".mp4", ".mkv", ".ts", ".m4a", ".mov", ".webm"}
    _FINALIZE_STAGE_RE = re.compile(r"\bmuxing\s+to\b", re.I)

    def __init__(
        self,
        data_path: Path,
        logger: Optional[logging.Logger] = None,
        thread_count: object = DEFAULT_THREAD_COUNT,
    ) -> None:
        super().__init__(data_path, logger)
        self.thread_count = self._normalized_thread_count(thread_count)

    @classmethod
    def _normalized_thread_count(cls, value: object) -> int:
        """Coerce configuration to the engine's safe supported range."""

        try:
            requested = int(value)
        except (TypeError, ValueError):
            requested = cls.DEFAULT_THREAD_COUNT
        return max(cls.MIN_THREAD_COUNT, min(cls.MAX_THREAD_COUNT, requested))

    @staticmethod
    def has_entered_finalize_stage(line: str) -> bool:
        return bool(N_m3u8DLEngine._FINALIZE_STAGE_RE.search(line))

    def stage_dir(
        self, task_id: str, output_parent: Optional[Path] = None
    ) -> Path:
        """Stage only below the plugin task cache, never in the media tree."""
        del output_parent
        return self._cache_root(task_id) / "n_m3u8dl-re-stage"

    def _prepare_stage_dir(self, task_id: str) -> Path:
        self._prepare_task_cache(task_id)
        stage_dir = self._ensure_real_directory(
            self.stage_dir(task_id),
            "N_m3u8DL-RE stage directory",
        )
        self._clear_stale_stage_outputs(stage_dir)
        return stage_dir

    @staticmethod
    def _open_stage_directory_fd(stage_dir: Path) -> Optional[int]:
        """Open a real stage directory without following its final path component."""

        supports_dir_fd = getattr(os, "supports_dir_fd", ())
        supports_follow_symlinks = getattr(os, "supports_follow_symlinks", ())
        if (
            os.name != "posix"
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or os.stat not in supports_dir_fd
            or os.stat not in supports_follow_symlinks
            or os.unlink not in supports_dir_fd
        ):
            return None
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            return os.open(stage_dir, flags)
        except OSError as exc:
            raise M3U8EngineError("N_m3u8DL-RE stage directory is unsafe") from exc

    def _clear_stale_stage_outputs(self, stage_dir: Path) -> None:
        """Remove only fixed-name final mux outputs from this controlled stage."""

        stage_fd = self._open_stage_directory_fd(stage_dir)
        if stage_fd is None:
            self._clear_stale_stage_outputs_fallback(stage_dir)
            return
        try:
            for suffix in sorted(self._MEDIA_SUFFIXES):
                filename = f"media{suffix}"
                try:
                    file_stat = os.stat(
                        filename, dir_fd=stage_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise M3U8EngineError(
                        "N_m3u8DL-RE stage output is unavailable"
                    ) from exc
                if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_nlink != 1
                ):
                    raise M3U8EngineError("N_m3u8DL-RE stage output is unsafe")
                try:
                    os.unlink(filename, dir_fd=stage_fd)
                except OSError as exc:
                    raise M3U8EngineError(
                        "N_m3u8DL-RE stage output is unavailable"
                    ) from exc
        finally:
            try:
                os.close(stage_fd)
            except OSError:
                pass

    def _clear_stale_stage_outputs_fallback(self, stage_dir: Path) -> None:
        """Use the existing path-based safe cleanup on unsupported platforms."""

        for suffix in sorted(self._MEDIA_SUFFIXES):
            candidate = stage_dir / f"media{suffix}"
            try:
                file_stat = candidate.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise M3U8EngineError(
                    "N_m3u8DL-RE stage output is unavailable"
                ) from exc
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
                raise M3U8EngineError("N_m3u8DL-RE stage output is unsafe")
            try:
                candidate.unlink()
            except OSError as exc:
                raise M3U8EngineError(
                    "N_m3u8DL-RE stage output is unavailable"
                ) from exc

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
            prefix=".lunatv-transfer-",
            suffix=".tmp",
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
            try:
                candidate.unlink()
            except OSError as exc:
                LOGGER.warning(
                    "stage output cleanup failed after committing %s; leaving %s: %s",
                    output,
                    candidate,
                    exc,
                )
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
        thread_count: Optional[object] = None,
        ad_keyword: str = "",
    ) -> Sequence[str]:
        selected_thread_count = self._normalized_thread_count(
            self.thread_count if thread_count is None else thread_count
        )
        # ffmpeg is used exclusively by N_m3u8DL-RE's final mux step.
        ffmpeg_binary = ffmpeg_path or "ffmpeg"
        ffmpeg_binary = shutil.which(ffmpeg_binary) or ffmpeg_binary
        command = [
            str(binary),
            url,
            "--auto-select",
            "--thread-count",
            str(selected_thread_count),
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
            ffmpeg_binary,
            "--no-ansi-color",
        ]
        if ad_keyword:
            command.extend(["--ad-keyword", ad_keyword])
        return command

    def download(
        self,
        url: str,
        output: Optional[Path],
        *,
        task_id: str,
        ffmpeg_path: str,
        control_event: Optional[threading.Event],
        progress_callback: Optional[Callable[[float], None]],
        expected_segments: int = 0,
        thread_count: Optional[object] = None,
        ad_keyword: str = "",
    ) -> Path:
        self._raise_if_cancelled(control_event)
        binary = self._installer.ensure_binary(control_event=control_event)
        self._raise_if_cancelled(control_event)
        cache_dir = self._prepare_task_cache(task_id)
        stage_dir = self._prepare_stage_dir(task_id)
        self._raise_if_cancelled(control_event)
        self._run_command(
            self.command(
                binary,
                url,
                cache_dir,
                stage_dir,
                ffmpeg_path,
                thread_count,
                ad_keyword,
            ),
            cache_dir=cache_dir,
            control_event=control_event,
            progress_callback=progress_callback,
            expected_segments=expected_segments,
            use_pty=True,
        )
        candidate = self._output_from_stage(stage_dir)
        if output is None:
            return candidate
        self._move_stage_output(candidate, output)
        return output
