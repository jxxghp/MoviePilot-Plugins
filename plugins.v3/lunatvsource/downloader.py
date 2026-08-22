"""Persistent, serial m3u8 download/STRM queue."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .naming import media_path


@dataclass
class DownloadTask:
    task_id: str
    source_key: str
    media_id: str
    title: str
    year: str
    media_type: str
    season: int
    episode: int
    url: str
    root: str
    mode: str = "download"
    ffmpeg_path: str = "ffmpeg"
    state: str = "pending"
    error: str = ""
    output: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    attempts: int = 0

    @classmethod
    def from_episode(
        cls,
        episode: Any,
        *,
        title: str,
        year: str,
        media_type: str,
        root: str,
        mode: str,
        ffmpeg_path: str,
        media_source: str,
        media_id: str,
    ) -> "DownloadTask":
        return cls(
            task_id=str(uuid.uuid4()),
            source_key=media_source,
            media_id=media_id,
            title=title,
            year=year,
            media_type=media_type,
            season=int(getattr(episode, "season", 1) or 1),
            episode=int(getattr(episode, "episode", 1) or 1),
            url=str(getattr(episode, "url", "")),
            root=root,
            mode=mode,
            ffmpeg_path=ffmpeg_path,
        )

    @property
    def identity_key(self) -> str:
        return f"{self.source_key}|{self.media_id}|{self.season}|{self.episode}|{self.mode}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DownloadQueue:
    """One-at-a-time queue; no worker fan-out or parallel download."""

    DATA_KEY = "download_tasks_v1"

    def __init__(
        self,
        load: Callable[..., Any],
        save: Callable[..., Any],
        notify: Callable[[str, str], None],
        on_complete: Optional[Callable[[DownloadTask, str], None]] = None,
    ) -> None:
        self._load = load
        self._save = save
        self._notify = notify
        self._on_complete = on_complete
        self._lock = threading.RLock()
        self._stop = False
        self._running = False
        self._recover_interrupted_tasks()

    def _recover_interrupted_tasks(self) -> None:
        """Put tasks left in ``running`` back into the serial queue.

        MoviePilot may restart while ffmpeg is running.  Persisting the
        transient state is useful for UI feedback, but it must not strand a
        task forever after the process comes back.
        """

        with self._lock:
            tasks = self._read()
            changed = False
            for task in tasks:
                if task.state == "running":
                    task.state = "pending"
                    task.error = "上次进程中断，已恢复排队"
                    changed = True
            if changed:
                self._write(tasks)

    def _read(self) -> List[DownloadTask]:
        raw = self._load(self.DATA_KEY, []) or []
        tasks: List[DownloadTask] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    tasks.append(DownloadTask(**item))
                except TypeError:
                    continue
        return tasks

    def _write(self, tasks: List[DownloadTask]) -> None:
        self._save(self.DATA_KEY, [task.to_dict() for task in tasks[-500:]])

    def enqueue(self, task: DownloadTask) -> bool:
        if not task.url or not task.root:
            return False
        with self._lock:
            tasks = self._read()
            for existing in tasks:
                if existing.identity_key == task.identity_key and existing.state in {"pending", "running", "completed"}:
                    return False
            tasks.append(task)
            self._write(tasks)
            return True

    def retry(self, task_id: str) -> bool:
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.task_id == task_id and task.state == "failed":
                    task.state = "pending"
                    task.error = ""
                    self._write(tasks)
                    return True
        return False

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [task.to_dict() for task in reversed(self._read())]

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for task in self._read():
            counts[task.state] = counts.get(task.state, 0) + 1
        return counts

    def run_one(self) -> Dict[str, Any]:
        with self._lock:
            tasks = self._read()
            if self._stop or self._running:
                return {"processed": 0, "stopped": True}
            task = next((item for item in tasks if item.state == "pending"), None)
            if task is None:
                return {"processed": 0}
            task.state = "running"
            task.attempts += 1
            self._running = True
            self._write(tasks)
        try:
            output = self._execute(task)
        except Exception as exc:
            with self._lock:
                tasks = self._read()
                current = next((item for item in tasks if item.task_id == task.task_id), task)
                current.state = "failed"
                current.error = str(exc)
                self._write(tasks)
                self._running = False
            self._notify("LunaTV 下载失败", f"{task.title} S{task.season:02d}E{task.episode:02d}：{exc}")
            return {"processed": 1, "task_id": task.task_id, "state": "failed", "error": str(exc)}

        with self._lock:
            tasks = self._read()
            current = next((item for item in tasks if item.task_id == task.task_id), task)
            current.state = "completed"
            current.output = output
            current.completed_at = time.time()
            task.state = current.state
            task.output = output
            task.completed_at = current.completed_at
            self._write(tasks)
            self._running = False
        if self._on_complete is not None:
            try:
                self._on_complete(task, output)
            except Exception:
                # History/host integration must never turn a completed file
                # into a failed download.
                pass
        self._notify("LunaTV 已完成", f"{task.title} S{task.season:02d}E{task.episode:02d}")
        return {"processed": 1, "task_id": task.task_id, "state": "completed", "output": output}

    def _execute(self, task: DownloadTask) -> str:
        relative_dir, filename = media_path(
            task.root,
            task.title,
            task.year,
            task.media_type,
            task.season,
            task.episode,
            task.url,
            task.mode,
        )
        root = Path(task.root).expanduser().resolve()
        destination = (root / relative_dir / filename).resolve()
        if root not in destination.parents:
            raise ValueError("目标路径越界")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 0:
            return str(destination)

        if task.mode == "strm":
            temp_path = destination.with_suffix(destination.suffix + ".part")
            try:
                temp_path.write_text(task.url + "\n", encoding="utf-8")
                os.replace(temp_path, destination)
            except Exception:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            return str(destination)

        temp_path = destination.with_suffix(destination.suffix + ".part")
        try:
            self._run_ffmpeg(task.ffmpeg_path, task.url, temp_path)
        except Exception:
            # 失败任务不把残留缓存留在媒体库目录，避免 Emby/监控把半成品当成文件夹内容。
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._remove_empty_parents(destination.parent, root)
            raise
        if not temp_path.exists() or temp_path.stat().st_size <= 0:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._remove_empty_parents(destination.parent, root)
            raise IOError("ffmpeg 未生成有效文件")
        os.replace(temp_path, destination)
        return str(destination)

    @staticmethod
    def _remove_empty_parents(path: Path, root: Path) -> None:
        """Remove only empty directories below the configured download root."""
        current = path
        while current != root and root in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    @staticmethod
    def _run_ffmpeg(ffmpeg_path: str, url: str, output: Path) -> None:
        with tempfile.TemporaryDirectory(prefix="lunatv-hls-") as temp_dir:
            input_url = DownloadQueue._prepare_hls_input(url, Path(temp_dir))
            command = [
                ffmpeg_path or "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-protocol_whitelist",
                "file,http,https,tcp,tls,crypto",
                "-allowed_extensions",
                "ALL",
                "-allowed_segment_extensions",
                "ALL",
                "-extension_picky",
                "0",
                "-i",
                input_url,
                "-c",
                "copy",
                "-bsf:a",
                "aac_adtstoasc",
                "-f",
                "mp4",
                str(output),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=6 * 60 * 60)
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "ffmpeg 执行失败").strip()
                raise RuntimeError(detail[-1200:])

    @staticmethod
    def _prepare_hls_input(url: str, temp_dir: Path) -> str:
        """Materialize playlists locally so ffmpeg can read zstd HTTP responses.

        Some Apple CMS CDNs apply ``Content-Encoding: zstd`` even when the
        client did not request it. ffmpeg does not decode that HTTP content
        encoding, so passing the remote URL directly makes a valid playlist
        look like corrupt binary data.
        """

        visited: Dict[str, str] = {}

        def materialize(playlist_url: str) -> str:
            if playlist_url in visited:
                return visited[playlist_url]
            request = urllib.request.Request(
                playlist_url,
                headers={"User-Agent": "MoviePilot-LunaTV/1.0", "Accept-Encoding": "identity"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
            if encoding == "zstd" or payload.startswith(b"\x28\xb5\x2f\xfd"):
                payload = DownloadQueue._decompress_zstd(payload)
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise RuntimeError("m3u8 响应不是可识别的文本格式") from exc
            if "#EXTM3U" not in text[:100]:
                raise RuntimeError("资源站返回的不是有效 m3u8")

            local_path = temp_dir / f"playlist-{len(visited)}.m3u8"
            visited[playlist_url] = str(local_path)
            lines = text.splitlines()
            rewritten: List[str] = []
            child_playlist = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#EXT-X-STREAM-INF"):
                    child_playlist = True
                    rewritten.append(line)
                    continue
                if stripped and not stripped.startswith("#"):
                    absolute = urllib.parse.urljoin(playlist_url, stripped)
                    if child_playlist or urllib.parse.urlparse(absolute).path.lower().endswith(".m3u8"):
                        rewritten.append(materialize(absolute))
                    else:
                        rewritten.append(absolute)
                    child_playlist = False
                    continue

                def replace_uri(match: re.Match[str]) -> str:
                    absolute = urllib.parse.urljoin(playlist_url, match.group(1))
                    if stripped.startswith("#EXT-X-MEDIA"):
                        absolute = materialize(absolute)
                    return f'URI="{absolute}"'

                rewritten.append(re.sub(r'URI="([^"]+)"', replace_uri, line))
            local_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
            return str(local_path)

        return materialize(url)

    @staticmethod
    def _decompress_zstd(payload: bytes) -> bytes:
        try:
            import zstandard  # type: ignore[import-not-found]

            return zstandard.ZstdDecompressor().decompress(payload)
        except ImportError:
            pass

        candidates = [
            ctypes.util.find_library("zstd"),
            "libzstd.so.1",
            "libzstd.so",
            "/opt/homebrew/lib/libzstd.dylib",
            "libzstd.dylib",
        ]
        library = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                library = ctypes.CDLL(candidate)
                break
            except OSError:
                continue
        if library is None:
            raise RuntimeError("资源站使用 zstd 压缩，但运行环境缺少 zstd 解码库")

        library.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        library.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        library.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        library.ZSTD_decompress.restype = ctypes.c_size_t
        library.ZSTD_isError.argtypes = [ctypes.c_size_t]
        library.ZSTD_isError.restype = ctypes.c_uint
        source = ctypes.create_string_buffer(payload)
        size = int(library.ZSTD_getFrameContentSize(source, len(payload)))
        if size in {0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFE} or size <= 0:
            raise RuntimeError("无法确定 zstd m3u8 的解压大小")
        target = ctypes.create_string_buffer(size)
        result = int(library.ZSTD_decompress(target, size, source, len(payload)))
        if library.ZSTD_isError(result):
            raise RuntimeError("zstd m3u8 解压失败")
        return target.raw[:result]

    def stop(self) -> None:
        with self._lock:
            self._stop = True
