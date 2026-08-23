"""Persistent, serial m3u8 download/STRM queue."""

from __future__ import annotations

import ctypes
import ctypes.util
import http.server
import os
import re
import selectors
import socketserver
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


class _QueueControl(RuntimeError):
    """Internal signal used to stop the active ffmpeg process safely."""

    def __init__(self, action: str) -> None:
        super().__init__(action)
        self.action = action


def _mpegts_payload_offset(data: bytes) -> int:
    """Return the start of an MPEG-TS payload hidden behind a JPEG header."""

    if not data.startswith(b"\xff\xd8\xff"):
        return 0
    limit = max(0, min(len(data) - 376, 4096))
    for offset in range(limit + 1):
        if data[offset] == 0x47 and data[offset + 188] == 0x47 and data[offset + 376] == 0x47:
            return offset
    return 0


class _LoopbackHTTPServer(http.server.ThreadingHTTPServer):
    """HTTP server without a reverse-DNS lookup during loopback binding."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class _SegmentProxy:
    """Loopback-only streaming proxy that removes fake JPEG segment headers."""

    def __init__(self) -> None:
        self._urls: Dict[str, str] = {}
        self._reverse: Dict[str, str] = {}
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "_SegmentProxy":
        return self

    def _start(self) -> None:
        if self._server is not None:
            return
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
                token = self.path.partition("?")[0].removeprefix("/segment/")
                remote_url = proxy._urls.get(token)
                if not remote_url:
                    self.send_error(404)
                    return
                try:
                    request = urllib.request.Request(
                        remote_url,
                        headers={"User-Agent": "MoviePilot-LunaTV/1.0", "Accept-Encoding": "identity"},
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        prefix = response.read(4096)
                        offset = _mpegts_payload_offset(prefix)
                        length = response.headers.get("Content-Length")
                        self.send_response(200)
                        self.send_header("Content-Type", "video/mp2t" if offset else (
                            response.headers.get("Content-Type") or "application/octet-stream"
                        ))
                        if length and str(length).isdigit():
                            self.send_header("Content-Length", str(max(0, int(length) - offset)))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.write(prefix[offset:])
                        while True:
                            chunk = response.read(256 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception:
                    try:
                        self.send_error(502)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self._server = _LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url_for(self, remote_url: str) -> str:
        self._start()
        token = self._reverse.get(remote_url)
        if token is None:
            token = uuid.uuid4().hex
            self._reverse[remote_url] = token
            self._urls[token] = remote_url
        if self._server is None:
            raise RuntimeError("分片代理尚未启动")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/segment/{token}"

    def __exit__(self, *_args: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


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
    host_media_source: Optional[str] = None
    host_media_id: Optional[str] = None
    source_name: Optional[str] = None
    mode: str = "download"
    ffmpeg_path: str = "ffmpeg"
    state: str = "pending"
    error: str = ""
    output: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    attempts: int = 0
    # MoviePilot's native download projection uses a 0..1 value.  Older
    # persisted tasks do not have this field and are restored with 0.0.
    progress: float = 0.0

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
        source_name: Optional[str] = None,
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
            source_name=source_name,
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
        self._current_task_id = ""
        self._control_action = ""
        self._control_event = threading.Event()
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

    def pause(self, task_id: str) -> bool:
        """Pause a queued task, or request safe termination of active ffmpeg."""
        with self._lock:
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None:
                return False
            if task.state == "paused":
                return True
            if task.state == "pending":
                task.state = "paused"
                task.error = ""
                self._write(tasks)
                return True
            if task.state == "running" and self._current_task_id == task_id:
                self._control_action = "pause"
                self._control_event.set()
                return True
        return False

    def resume(self, task_id: str) -> bool:
        """Return a paused task to the serial queue."""
        with self._lock:
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None:
                return False
            if task.state in {"pending", "running"}:
                return True
            if task.state == "paused":
                task.state = "pending"
                task.error = ""
                self._write(tasks)
                return True
        return False

    def remove(self, task_id: str) -> bool:
        """Remove a non-completed task and stop ffmpeg first when necessary."""
        with self._lock:
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None or task.state == "completed":
                return False
            if task.state == "running" and self._current_task_id == task_id:
                self._control_action = "remove"
                self._control_event.set()
                return True
            self._write([item for item in tasks if item.task_id != task_id])
            return True

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
            task.progress = max(0.0, min(1.0, float(task.progress or 0.0)))
            task.attempts += 1
            self._running = True
            self._current_task_id = task.task_id
            self._control_action = ""
            self._control_event.clear()
            self._write(tasks)
        try:
            output = self._execute(task)
        except _QueueControl as exc:
            with self._lock:
                action = self._control_action or exc.action
                tasks = self._read()
                current = next((item for item in tasks if item.task_id == task.task_id), None)
                if action == "remove":
                    tasks = [item for item in tasks if item.task_id != task.task_id]
                elif current is not None:
                    current.state = "paused"
                    current.error = ""
                self._write(tasks)
                self._running = False
                self._current_task_id = ""
                self._control_action = ""
                self._control_event.clear()
            return {"processed": 1, "task_id": task.task_id, "state": action}
        except Exception as exc:
            with self._lock:
                tasks = self._read()
                current = next((item for item in tasks if item.task_id == task.task_id), task)
                current.state = "failed"
                current.error = str(exc)
                self._write(tasks)
                self._running = False
                self._current_task_id = ""
                self._control_action = ""
                self._control_event.clear()
            self._notify("LunaTV 下载失败", f"{task.title} S{task.season:02d}E{task.episode:02d}：{exc}")
            return {"processed": 1, "task_id": task.task_id, "state": "failed", "error": str(exc)}

        with self._lock:
            tasks = self._read()
            current = next((item for item in tasks if item.task_id == task.task_id), task)
            current.state = "completed"
            current.progress = 1.0
            current.output = output
            current.completed_at = time.time()
            task.state = current.state
            task.output = output
            task.completed_at = current.completed_at
            self._write(tasks)
            self._running = False
            self._current_task_id = ""
            self._control_action = ""
            self._control_event.clear()
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
            self._run_ffmpeg(
                task.ffmpeg_path,
                task.url,
                temp_path,
                self._control_event,
                lambda progress: self._update_progress(task.task_id, progress),
            )
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

    def _update_progress(self, task_id: str, progress: float) -> None:
        """Persist ffmpeg's current VOD progress for the native download page."""

        value = max(0.0, min(0.99, float(progress or 0.0)))
        with self._lock:
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None or task.state != "running":
                return
            task.progress = value
            self._write(tasks)

    @staticmethod
    def _playlist_duration(path: Path, visited: Optional[set[str]] = None) -> float:
        """Estimate VOD duration from a materialized HLS playlist.

        A master playlist generally contains local child playlist paths after
        ``_prepare_hls_input``.  Use the longest child duration so adaptive
        variants do not make progress jump past 100%; for a media playlist the
        sum of ``#EXTINF`` values is the exact VOD duration.
        """

        visited = visited or set()
        try:
            resolved = str(path.resolve())
            if resolved in visited:
                return 0.0
            visited.add(resolved)
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return 0.0

        durations = []
        child_durations = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#EXTINF:"):
                value = stripped.partition(":")[2].partition(",")[0]
                try:
                    durations.append(float(value))
                except ValueError:
                    continue
            elif stripped and not stripped.startswith("#"):
                child = Path(stripped)
                if child.is_file() and child.suffix.lower() in {".m3u8", ".m3u"}:
                    child_durations.append(DownloadQueue._playlist_duration(child, visited))
        if durations:
            return max(0.0, sum(durations))
        return max(child_durations, default=0.0)

    @staticmethod
    def _run_ffmpeg(
        ffmpeg_path: str,
        url: str,
        output: Path,
        control_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="lunatv-hls-") as temp_dir, _SegmentProxy() as proxy:
            input_url = DownloadQueue._prepare_hls_input(url, Path(temp_dir), proxy.url_for)
            duration = DownloadQueue._playlist_duration(Path(input_url))
            progress_args = ["-nostats", "-progress", "pipe:1"] if progress_callback is not None else []
            command = [
                ffmpeg_path or "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                *progress_args,
                "-y",
                "-protocol_whitelist",
                "file,http,https,tcp,tls,crypto",
                "-allowed_extensions",
                "ALL",
                "-allowed_segment_extensions",
                "ALL",
                "-extension_picky",
                "0",
                "-seg_max_retry",
                "2",
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
            if control_event is None:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=6 * 60 * 60,
                )
                if completed.returncode != 0:
                    detail = (completed.stderr or completed.stdout or "ffmpeg 执行失败").strip()
                    raise RuntimeError(detail[-1200:])
                return

            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            started_at = time.monotonic()
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []
            selector = selectors.DefaultSelector()
            if process.stdout is not None:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            if process.stderr is not None:
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while True:
                if control_event is not None and control_event.is_set():
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise _QueueControl("controlled")
                if time.monotonic() - started_at > 6 * 60 * 60:
                    process.kill()
                    process.communicate()
                    raise TimeoutError("ffmpeg 下载超时")
                events = selector.select(timeout=0.5)
                for key, _ in events:
                    line = key.fileobj.readline()
                    if not line:
                        try:
                            selector.unregister(key.fileobj)
                        except Exception:
                            pass
                        continue
                    if key.data == "stderr":
                        stderr_lines.append(line)
                        continue
                    stdout_lines.append(line)
                    if progress_callback is not None and duration > 0:
                        name, _, raw_value = line.strip().partition("=")
                        if name == "out_time_ms":
                            try:
                                progress_callback(float(raw_value) / 1_000_000 / duration)
                            except (TypeError, ValueError):
                                pass
                if process.poll() is not None and not selector.get_map():
                    break
            selector.close()
            process.wait(timeout=5)
            if process.returncode != 0:
                detail = ("".join(stderr_lines) or "".join(stdout_lines) or "ffmpeg 执行失败").strip()
                raise RuntimeError(detail[-1200:])

    @staticmethod
    def _prepare_hls_input(
        url: str,
        temp_dir: Path,
        segment_url_mapper: Optional[Callable[[str], str]] = None,
    ) -> str:
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
                        rewritten.append(segment_url_mapper(absolute) if segment_url_mapper else absolute)
                    child_playlist = False
                    continue

                def replace_uri(match: re.Match[str]) -> str:
                    absolute = urllib.parse.urljoin(playlist_url, match.group(1))
                    if stripped.startswith("#EXT-X-MEDIA"):
                        absolute = materialize(absolute)
                    elif stripped.startswith("#EXT-X-MAP") and segment_url_mapper:
                        absolute = segment_url_mapper(absolute)
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
            if self._running:
                self._control_action = "pause"
                self._control_event.set()
