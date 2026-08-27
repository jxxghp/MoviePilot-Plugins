"""Persistent m3u8 download/STRM queue."""

from __future__ import annotations

import ctypes
import ctypes.util
import http.server
import logging
import os
import re
import socketserver
import stat
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .m3u8_engine import (
    M3U8EngineCancelled,
    M3U8EngineError,
    N_m3u8DLEngine,
)
from .naming import media_path


LOGGER = logging.getLogger("LunaTVSource")

DEFAULT_MAX_CONCURRENT_TASKS = 2
MIN_MAX_CONCURRENT_TASKS = 1
MAX_MAX_CONCURRENT_TASKS = 4
DEFAULT_SEGMENT_THREAD_COUNT = 16
MIN_SEGMENT_THREAD_COUNT = 4
MAX_SEGMENT_THREAD_COUNT = 32
MAX_TOTAL_SEGMENT_THREADS = 64


def normalize_download_concurrency(
    max_concurrent_tasks: object,
    segment_thread_count: object,
) -> tuple[int, int]:
    """Bound per-task work and keep aggregate segment concurrency predictable."""
    try:
        max_tasks = int(max_concurrent_tasks)
    except (TypeError, ValueError):
        max_tasks = DEFAULT_MAX_CONCURRENT_TASKS
    max_tasks = max(
        MIN_MAX_CONCURRENT_TASKS,
        min(MAX_MAX_CONCURRENT_TASKS, max_tasks),
    )

    try:
        segment_threads = int(segment_thread_count)
    except (TypeError, ValueError):
        segment_threads = DEFAULT_SEGMENT_THREAD_COUNT
    segment_threads = max(
        MIN_SEGMENT_THREAD_COUNT,
        min(MAX_SEGMENT_THREAD_COUNT, segment_threads),
    )
    segment_threads = min(
        segment_threads,
        max(MIN_SEGMENT_THREAD_COUNT, MAX_TOTAL_SEGMENT_THREADS // max_tasks),
    )
    return max_tasks, segment_threads


class _QueueControl(RuntimeError):
    """Internal signal used to stop the active download process safely."""

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
            protocol_version = "HTTP/1.1"

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
                        content_length = (
                            int(length)
                            if length is not None and str(length).isdigit()
                            else None
                        )
                        self.send_response(200)
                        self.send_header("Content-Type", "video/mp2t" if offset else (
                            response.headers.get("Content-Type") or "application/octet-stream"
                        ))
                        if content_length is not None and content_length >= offset:
                            self.send_header("Content-Length", str(content_length - offset))
                        else:
                            # HTTP/1.1 responses without a length must close so
                            # ffmpeg can delimit the segment body.
                            self.send_header("Connection", "close")
                            self.close_connection = True
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
    # Empty keeps persisted tasks created before engine attribution compatible.
    download_engine: str = ""

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


class _SerialDownloadQueue:
    """One-at-a-time queue; no worker fan-out or parallel download."""

    DATA_KEY = "download_tasks_v1"

    def __init__(
        self,
        load: Callable[..., Any],
        save: Callable[..., Any],
        notify: Callable[[str, str], None],
        on_complete: Optional[Callable[[DownloadTask, str], None]] = None,
        data_path: Optional[Path] = None,
    ) -> None:
        self._load = load
        self._save = save
        self._notify = notify
        self._on_complete = on_complete
        self._lock = threading.RLock()
        self._stop = False
        self._running = False
        self._drain_running = False
        self._drain_wakeup = threading.Event()
        self._current_task_id = ""
        self._active_owner_id: Optional[int] = None
        self._control_action = ""
        self._control_event = threading.Event()
        self._idle_event = threading.Event()
        self._idle_event.set()
        self._delete_file_tasks: set[str] = set()
        # Standalone/legacy hosts retain the historical N-only behavior.
        # MoviePilot passes its plugin data directory and enables the managed
        # N_m3u8DL-RE is the sole VOD download engine.
        self._m3u8_engines = (
            (N_m3u8DLEngine(Path(data_path)),)
            if data_path is not None
            else ()
        )
        self._recover_interrupted_tasks()

    def _recover_interrupted_tasks(self) -> None:
        """Put tasks left in ``running`` back into the download queue.

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
                    task.progress = 0.0
                    task.error = "上次进程中断，已恢复排队"
                    changed = True
                elif task.state == "paused" and task.progress:
                    task.progress = 0.0
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
        terminal_states = {"completed", "failed"}
        terminal_to_discard = max(
            0,
            sum(task.state in terminal_states for task in tasks) - 500,
        )
        persisted = []
        for task in tasks:
            if task.state in terminal_states and terminal_to_discard:
                terminal_to_discard -= 1
                continue
            persisted.append(task.to_dict())
        self._save(self.DATA_KEY, persisted)

    def _persist_removal(
        self,
        tasks: List[DownloadTask],
        task: DownloadTask,
        *,
        delete_file: bool,
    ) -> None:
        """Persist task removal before deleting its local artifacts.

        Some MoviePilot data stores may durably apply a write and still raise
        while reporting the result.  Re-read in that case: delete files only
        when the task is already absent, otherwise leave both state and files
        intact so a restart cannot resurrect a task whose file was removed.
        This method must be called while ``_lock`` is held.
        """

        remaining = [item for item in tasks if item.task_id != task.task_id]
        try:
            self._write(remaining)
        except Exception:
            try:
                removal_persisted = not any(
                    item.task_id == task.task_id for item in self._read()
                )
            except Exception:
                removal_persisted = False
            if removal_persisted:
                self._cleanup_m3u8_cache(task)
                if delete_file:
                    self._delete_task_files(task)
            raise
        self._cleanup_m3u8_cache(task)
        if delete_file:
            self._delete_task_files(task)

    def enqueue(self, task: DownloadTask) -> bool:
        if not task.url or not task.root:
            return False
        with self._lock:
            tasks = self._read()
            for existing in tasks:
                if existing.identity_key == task.identity_key and existing.state in {"pending", "running", "paused", "completed"}:
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
                    task.progress = 0.0
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
                task.progress = 0.0
                task.error = ""
                self._write(tasks)
                return True
            if task.state == "running" and self._current_task_id == task_id:
                if self._control_action == "remove":
                    return True
                self._control_action = "pause"
                self._control_event.set()
                return True
        return False

    def resume(self, task_id: str) -> bool:
        """Return a paused task to the pending queue."""
        with self._lock:
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None:
                return False
            if task.state in {"pending", "running"}:
                return True
            if task.state == "paused":
                task.state = "pending"
                task.progress = 0.0
                task.error = ""
                self._write(tasks)
                return True
        return False

    def remove(self, task_id: str, delete_file: bool = False) -> bool:
        """Remove a task, optionally deleting its safe local files."""
        with self._lock:
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None:
                return False
            if task.state == "running" and self._current_task_id == task_id:
                if delete_file:
                    self._delete_file_tasks.add(task_id)
                self._control_action = "remove"
                self._control_event.set()
                return True
            self._persist_removal(tasks, task, delete_file=delete_file)
            return True

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [task.to_dict() for task in reversed(self._read())]

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for task in self._read():
            counts[task.state] = counts.get(task.state, 0) + 1
        return counts

    @staticmethod
    def _notification_text(task: DownloadTask) -> str:
        if str(task.media_type or "").lower() == "tv":
            return f"{task.title} S{int(task.season):02d}E{int(task.episode):02d}"
        return task.title

    def _clear_active_state(self, *, keep_control: bool = False) -> None:
        """Clear transient active-task state while ``_lock`` is held."""
        self._running = False
        self._active_owner_id = None
        if not keep_control:
            self._current_task_id = ""
            self._control_action = ""
        self._control_event.clear()
        self._idle_event.set()

    def wake(self) -> bool:
        """Run pending tasks in one background worker without fan-out."""
        with self._lock:
            if self._stop:
                return False
            self._drain_wakeup.set()
            if self._drain_running:
                return True
            self._drain_running = True
        try:
            threading.Thread(
                target=self._drain,
                name="lunatvsource-download",
                daemon=True,
            ).start()
        except RuntimeError:
            with self._lock:
                self._drain_running = False
                self._drain_wakeup.clear()
            return False
        return True

    def _drain(self) -> None:
        control_retry_used = False
        while True:
            self._drain_wakeup.clear()
            failed = False
            try:
                self._drain_until_idle()
            except Exception:
                # A wake arriving during a transient persistence failure must
                # get one retry instead of being lost behind the live worker.
                failed = True

            with self._lock:
                if self._drain_wakeup.is_set():
                    continue
                pending_control = (
                    self._control_action in {"pause", "remove"}
                    and bool(self._current_task_id)
                )
                if failed and pending_control and not control_retry_used:
                    control_retry_used = True
                    continue
                self._drain_running = False
                if self._stop:
                    self._drain_wakeup.clear()
                return

    def _drain_until_idle(self) -> None:
        """Continue legacy single-worker processing until no task remains.

        The idle check and worker hand-off share ``_lock`` with enqueue(), so
        a task added as another task finishes cannot lose its wake-up.
        """
        while True:
            result = self.run_one()
            if result.get("processed"):
                continue

            with self._lock:
                stopped = self._stop
                active_elsewhere = self._running
            if stopped:
                return
            if active_elsewhere:
                # A legacy/direct run_one() call owns the active task. Keep
                # this worker alive until it finishes, then drain its wake-up.
                self._idle_event.wait()
                continue

            with self._lock:
                if any(task.state == "pending" for task in self._read()):
                    continue
                return

    def _replay_control_intent(
        self,
        tasks: List[DownloadTask],
    ) -> Optional[Dict[str, Any]]:
        """Persist an interrupted pause/remove before any task can restart.

        Must be called with ``_lock`` held. The intent is cleared only after
        its durable state transition succeeds, so a transient save failure
        cannot resurrect a paused or removed download.
        """
        action = self._control_action
        task_id = self._current_task_id
        if action not in {"pause", "remove"} or not task_id:
            return None

        task = next((item for item in tasks if item.task_id == task_id), None)
        if action == "remove":
            delete_file = task_id in self._delete_file_tasks
            if task is not None:
                self._persist_removal(tasks, task, delete_file=delete_file)
            self._delete_file_tasks.discard(task_id)
        else:
            if task is not None:
                task.state = "paused"
                task.progress = 0.0
                task.error = ""
                self._write(tasks)

        self._clear_active_state()
        return {
            "processed": 1 if task is not None else 0,
            "task_id": task_id,
            "state": action,
        }

    def run_one(self) -> Dict[str, Any]:
        owner_id = threading.get_ident()
        try:
            return self._run_one(owner_id)
        except Exception:
            with self._lock:
                if self._active_owner_id == owner_id:
                    keep_control = (
                        self._control_action in {"pause", "remove"}
                        and bool(self._current_task_id)
                    )
                    self._clear_active_state(keep_control=keep_control)
            raise

    def _run_one(self, owner_id: int) -> Dict[str, Any]:
        with self._lock:
            if self._running:
                return {"processed": 0, "stopped": True}
            tasks = self._read()
            replayed = self._replay_control_intent(tasks)
            if replayed is not None:
                return replayed
            if self._stop:
                return {"processed": 0, "stopped": True}
            task = next(
                (
                    item
                    for item in tasks
                    if item.state == "pending" and item.task_id not in self._pending_terminal
                ),
                None,
            )
            if task is None:
                task = next((item for item in tasks if item.state == "running"), None)
                if task is not None:
                    task.progress = 0.0
                    task.error = "上次队列执行异常，已恢复排队"
            if task is None:
                return {"processed": 0}
            task.state = "running"
            task.progress = max(0.0, min(1.0, float(task.progress or 0.0)))
            task.attempts += 1
            self._running = True
            self._current_task_id = task.task_id
            self._active_owner_id = owner_id
            self._control_action = ""
            self._control_event.clear()
            self._idle_event.clear()
            self._write(tasks)
        try:
            output = self._execute(task)
        except _QueueControl as exc:
            with self._lock:
                action = self._control_action or exc.action
                tasks = self._read()
                current = next((item for item in tasks if item.task_id == task.task_id), None)
                if action == "remove":
                    delete_file = task.task_id in self._delete_file_tasks
                    self._persist_removal(tasks, task, delete_file=delete_file)
                elif current is not None:
                    current.state = "paused"
                    current.progress = 0.0
                    current.error = ""
                    self._write(tasks)
                self._delete_file_tasks.discard(task.task_id)
                self._clear_active_state()
                return {"processed": 1, "task_id": task.task_id, "state": action}
        except Exception as exc:
            with self._lock:
                tasks = self._read()
                if (
                    self._control_action == "remove"
                    and self._current_task_id == task.task_id
                ):
                    delete_file = task.task_id in self._delete_file_tasks
                    self._persist_removal(tasks, task, delete_file=delete_file)
                    self._delete_file_tasks.discard(task.task_id)
                    self._clear_active_state()
                    return {
                        "processed": 1,
                        "task_id": task.task_id,
                        "state": "remove",
                    }
                if (
                    self._control_action == "pause"
                    and self._current_task_id == task.task_id
                ):
                    current = next(
                        (item for item in tasks if item.task_id == task.task_id),
                        None,
                    )
                    if current is not None:
                        current.state = "paused"
                        current.progress = 0.0
                        current.error = ""
                        self._write(tasks)
                    self._delete_file_tasks.discard(task.task_id)
                    self._clear_active_state()
                    return {
                        "processed": 1,
                        "task_id": task.task_id,
                        "state": "pause",
                    }
                self._delete_file_tasks.discard(task.task_id)
                current = next((item for item in tasks if item.task_id == task.task_id), task)
                current.state = "failed"
                current.error = str(exc)
                self._write(tasks)
                self._clear_active_state()
            self._notify("LunaTV 下载失败", f"{self._notification_text(task)}：{exc}")
            return {"processed": 1, "task_id": task.task_id, "state": "failed", "error": str(exc)}

        with self._lock:
            tasks = self._read()
            if (
                self._control_action == "remove"
                and self._current_task_id == task.task_id
            ):
                task.output = output
                delete_file = task.task_id in self._delete_file_tasks
                self._persist_removal(tasks, task, delete_file=delete_file)
                self._delete_file_tasks.discard(task.task_id)
                self._clear_active_state()
                return {
                    "processed": 1,
                    "task_id": task.task_id,
                    "state": "remove",
                }
            self._delete_file_tasks.discard(task.task_id)
            current = next((item for item in tasks if item.task_id == task.task_id), task)
            current.state = "completed"
            current.progress = 1.0
            current.output = output
            current.completed_at = time.time()
            task.state = current.state
            task.output = output
            task.completed_at = current.completed_at
            self._write(tasks)
        if self._on_complete is not None:
            try:
                self._on_complete(task, output)
            except Exception:
                # History/host integration must never turn a completed file
                # into a failed download.
                pass
        with self._lock:
            self._clear_active_state()
        self._notify("LunaTV 已完成", self._notification_text(task))
        return {"processed": 1, "task_id": task.task_id, "state": "completed", "output": output}

    def _execute(self, task: DownloadTask) -> str:
        root, destination = self._destination_for_task(task)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 0:
            self._cleanup_m3u8_cache(task, destination.parent)
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
            self._cleanup_m3u8_cache(task, destination.parent)
            return str(destination)

        temp_path = destination.with_suffix(destination.suffix + ".part")
        try:
            if not self._run_m3u8_engines(task, temp_path):
                raise RuntimeError("N_m3u8DL-RE 不可用或下载失败")
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
            raise IOError("N_m3u8DL-RE 未生成有效文件")
        os.replace(temp_path, destination)
        self._cleanup_m3u8_cache(task, destination.parent)
        return str(destination)

    def _cleanup_m3u8_cache(
        self, task: DownloadTask, destination_parent: Optional[Path] = None
    ) -> None:
        """Clear controlled engine cache only after success or durable deletion."""
        if not self._m3u8_engines:
            return
        parent = destination_parent
        if parent is None:
            try:
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
                if root in destination.parents:
                    parent = destination.parent
            except (OSError, TypeError, ValueError):
                parent = None
        for engine in self._m3u8_engines:
            cleanup = getattr(engine, "cleanup_task", None)
            if callable(cleanup):
                try:
                    cleanup(task.task_id, parent)
                except Exception:
                    pass

    @staticmethod
    def _playlist_segment_count(path: Path, visited: Optional[set[str]] = None) -> int:
        """Count materialized HLS media segments for conservative cache progress."""
        visited = visited or set()
        try:
            resolved = str(path.resolve())
        except OSError:
            return 0
        if resolved in visited:
            return 0
        visited.add(resolved)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return 0
        count = 0
        for line in lines:
            value = line.strip()
            if value.startswith("#EXTINF:"):
                count += 1
            elif value and not value.startswith("#"):
                child = Path(value)
                if child.is_file() and child.suffix.lower() in {".m3u8", ".m3u"}:
                    count += DownloadQueue._playlist_segment_count(child, visited)
        return count

    def _run_m3u8_engines(self, task: DownloadTask, output: Path) -> bool:
        """Run N_m3u8DL-RE through the established HLS proxy seam."""
        if self._control_event.is_set():
            raise _QueueControl("controlled")
        if not self._m3u8_engines:
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="lunatv-hls-") as temp_dir, _SegmentProxy() as proxy:
                if self._control_event.is_set():
                    raise _QueueControl("controlled")
                input_url = self._prepare_hls_input(
                    task.url, Path(temp_dir), proxy.url_for
                )
                if self._control_event.is_set():
                    raise _QueueControl("controlled")
                segments = self._playlist_segment_count(Path(input_url))
                for engine in self._m3u8_engines:
                    if self._control_event.is_set():
                        raise _QueueControl("controlled")
                    try:
                        engine.download(
                            input_url,
                            output,
                            task_id=task.task_id,
                            ffmpeg_path=task.ffmpeg_path,
                            control_event=self._control_event,
                            progress_callback=lambda progress: self._update_progress(
                                task.task_id, progress
                            ),
                            expected_segments=segments,
                        )
                        return True
                    except M3U8EngineCancelled as exc:
                        raise _QueueControl("controlled") from exc
                    except (M3U8EngineError, OSError):
                        if self._control_event.is_set():
                            raise _QueueControl("controlled")
                        LOGGER.warning(
                    "LunaTV %s M3U8 engine failed", engine.name
                        )
        except _QueueControl:
            raise
        except Exception as exc:
            if self._control_event.is_set():
                raise _QueueControl("controlled") from exc
            # Avoid logging a source URL, which can contain an access token.
            LOGGER.warning("LunaTV M3U8 engine preparation failed; using ffmpeg")
            return False

    def _delete_task_files(self, task: DownloadTask) -> None:
        """Delete only the task output and cache paths below its configured root."""
        try:
            root = Path(task.root).expanduser().resolve()
        except (OSError, RuntimeError):
            return
        candidates: List[Path] = []
        if task.output:
            output = Path(task.output).expanduser()
            candidates.append(output if output.is_absolute() else root / output)
        try:
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
        except (TypeError, ValueError, OSError):
            relative_dir = ""
            filename = ""
        if filename and not task.output:
            candidates.append(root / relative_dir / filename)

        seen: set[Path] = set()
        for candidate in candidates:
            try:
                output = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            if root not in output.parents or output in seen:
                continue
            seen.add(output)
            for path in (output, Path(f"{output}.part")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
                self._remove_empty_parents(path.parent, root)

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
        """Persist N_m3u8DL-RE progress for the native download page."""

        value = max(0.0, min(0.99, float(progress or 0.0)))
        with self._lock:
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None or task.state != "running":
                return
            task.progress = value
            self._write(tasks)

    @staticmethod
    def _validate_hls_remote_uri(uri: str) -> str:
        """Accept only remote HTTP(S) HLS references before materializing them."""
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("M3U8 URI 仅支持 http/https")
        return uri

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
            playlist_url = DownloadQueue._validate_hls_remote_uri(playlist_url)
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
                    absolute = DownloadQueue._validate_hls_remote_uri(
                        urllib.parse.urljoin(playlist_url, stripped)
                    )
                    if child_playlist or urllib.parse.urlparse(absolute).path.lower().endswith(".m3u8"):
                        rewritten.append(materialize(absolute))
                    else:
                        rewritten.append(segment_url_mapper(absolute) if segment_url_mapper else absolute)
                    child_playlist = False
                    continue

                def replace_uri(match: re.Match[str]) -> str:
                    absolute = DownloadQueue._validate_hls_remote_uri(
                        urllib.parse.urljoin(playlist_url, match.group(1))
                    )
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


@dataclass
class _TaskControl:
    """Control plane owned by exactly one running task."""

    event: threading.Event = field(default_factory=threading.Event)
    action: str = ""
    delete_file: bool = False


@dataclass
class _TerminalIntent:
    """A terminal transition that could not yet be made durable."""

    task: DownloadTask
    control: _TaskControl
    state: str
    output: str = ""
    error: str = ""


class DownloadQueue(_SerialDownloadQueue):
    """Persistent bounded-concurrency queue with task-local cancellation."""

    def __init__(
        self,
        load: Callable[[str, Any], Any],
        save: Callable[[str, Any], None],
        notify: Callable[[str, str], None],
        on_complete: Optional[Callable[[DownloadTask, str], None]] = None,
        data_path: Optional[Path] = None,
        max_concurrent_tasks: int = 1,
        segment_thread_count: int = DEFAULT_SEGMENT_THREAD_COUNT,
    ) -> None:
        self._load = load
        self._save = save
        self._notify = notify
        self._on_complete = on_complete
        self._lock = threading.RLock()
        self._stop = False
        (
            self.max_concurrent_tasks,
            self.segment_thread_count,
        ) = normalize_download_concurrency(
            max_concurrent_tasks,
            segment_thread_count,
        )
        self._drain_running = False
        self._drain_failed = False
        self._wake_generation = 0
        self._drain_wakeup = threading.Event()
        self._active: Dict[str, _TaskControl] = {}
        self._active_destinations: Dict[str, str] = {}
        self._pending_terminal: Dict[str, _TerminalIntent] = {}
        self._dispatching = 0
        self._execution = threading.local()
        self._compat_control_event = threading.Event()
        # Legacy attributes remain observable, but are not the source of truth.
        self._running = False
        self._current_task_id = ""
        self._active_owner_id: Optional[int] = None
        self._control_action = ""
        self._idle_event = threading.Event()
        self._idle_event.set()
        self._delete_file_tasks: set[str] = set()
        self._data_path = Path(data_path).resolve() if data_path is not None else None
        self._m3u8_engines = (self._new_n_engine(self._data_path),) if self._data_path else ()
        self._recover_interrupted_tasks()

    def _new_n_engine(self, data_path: Path) -> N_m3u8DLEngine:
        try:
            return N_m3u8DLEngine(data_path, thread_count=self.segment_thread_count)
        except TypeError as exc:
            if "thread_count" not in str(exc):
                raise
            return N_m3u8DLEngine(data_path)

    @staticmethod
    def _destination_for_task(task: DownloadTask) -> tuple[Path, Path]:
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
        return root, destination

    @classmethod
    def _destination_key(cls, task: DownloadTask) -> str:
        try:
            _, destination = cls._destination_for_task(task)
        except (OSError, TypeError, ValueError):
            return f"invalid:{task.task_id}"
        return os.path.normcase(str(destination))

    def _next_claimable_task(
        self,
        tasks: List[DownloadTask],
    ) -> Optional[DownloadTask]:
        active_destinations = set(self._active_destinations.values())
        return next(
            (
                item
                for item in tasks
                if item.state == "pending"
                and self._destination_key(item) not in active_destinations
            ),
            None,
        )

    @property
    def _control_event(self) -> threading.Event:
        control = getattr(self._execution, "control", None)
        return control.event if control is not None else self._compat_control_event

    def _claim_next(self) -> Optional[tuple[DownloadTask, _TaskControl]]:
        with self._lock:
            if self._stop or len(self._active) >= self.max_concurrent_tasks:
                return None
            tasks = self._read()
            task = self._next_claimable_task(tasks)
            if task is None:
                return None
            task.state = "running"
            task.progress = max(0.0, min(1.0, float(task.progress or 0.0)))
            task.attempts += 1
            task.download_engine = "N_m3u8DL-RE"
            control = _TaskControl()
            self._active[task.task_id] = control
            self._active_destinations[task.task_id] = self._destination_key(task)
            self._running = True
            self._current_task_id = task.task_id
            self._active_owner_id = threading.get_ident()
            self._idle_event.clear()
            if getattr(self._execution, "dispatched", False):
                self._dispatching -= 1
                self._execution.dispatched = False
            try:
                self._write(tasks)
            except Exception:
                self._active.pop(task.task_id, None)
                self._active_destinations.pop(task.task_id, None)
                self._running = bool(self._active)
                # A failed running-state write must not strand the persisted
                # task or let this drain execute it from an in-memory claim.
                rollback = self._read()
                current = next((item for item in rollback if item.task_id == task.task_id), None)
                if current is not None and current.state == "running":
                    current.state = "pending"
                    current.progress = 0.0
                    current.error = ""
                    current.attempts = max(0, current.attempts - 1)
                    current.download_engine = ""
                    try:
                        self._write(rollback)
                    except Exception:
                        LOGGER.exception("LunaTV queue claim rollback failed")
                if not self._running:
                    self._current_task_id = ""
                    self._active_owner_id = None
                    self._idle_event.set()
                raise
            return task, control

    def run_one(self) -> Dict[str, Any]:
        claimed = self._claim_next()
        if claimed is None:
            return {"processed": 0, "stopped": True} if self._stop else {"processed": 0}
        return self._run_claimed(*claimed)

    def enqueue(self, task: DownloadTask) -> bool:
        """Persist a new task while preserving the legacy boolean contract."""
        if not task.url or not task.root:
            return False
        with self._lock:
            tasks = self._read()
            for existing in tasks:
                if existing.identity_key == task.identity_key and existing.state in {
                    "pending", "running", "paused", "completed",
                }:
                    return False
            tasks.append(task)
            self._write(tasks)
        return True

    def summary(self) -> Dict[str, int]:
        counts = {"pending": 0, "running": 0, "paused": 0, "completed": 0, "failed": 0}
        with self._lock:
            for task in self._read():
                counts[task.state] = counts.get(task.state, 0) + 1
        return counts

    def retry(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._pending_terminal:
                return False
            retried = super().retry(task_id)
        if retried:
            self.wake()
        return retried

    def resume(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._pending_terminal:
                return False
            resumed = super().resume(task_id)
        if resumed:
            self.wake()
        return resumed

    def _run_claimed(self, task: DownloadTask, control: _TaskControl) -> Dict[str, Any]:
        self._execution.control = control
        try:
            output = self._execute(task)
        except _QueueControl as exc:
            action = control.action or exc.action
            if action not in {"pause", "remove"}:
                action = "pause"
            return self._finish_controlled(task, control, action)
        except Exception as exc:
            return self._finish_failed(task, control, exc)
        finally:
            self._execution.control = None
        return self._finish_completed(task, control, output)

    def _finish_controlled(
        self, task: DownloadTask, control: _TaskControl, action: str
    ) -> Dict[str, Any]:
        with self._lock:
            try:
                self._persist_control_transition(task, control, action)
            except Exception as exc:
                self._defer_terminal(task, control, action, error=str(exc))
            else:
                self._release(task.task_id)
        return {"processed": 1, "task_id": task.task_id, "state": action or "pause"}

    def _persist_control_transition(
        self, task: DownloadTask, control: _TaskControl, action: str
    ) -> None:
        """Durably apply pause/remove without allowing a second execution."""
        last_error: Optional[Exception] = None
        for _attempt in range(2):
            tasks = self._read()
            current = next((item for item in tasks if item.task_id == task.task_id), None)
            try:
                if action == "remove":
                    if current is not None:
                        current.output = task.output
                        self._persist_removal(tasks, current, delete_file=control.delete_file)
                elif current is not None:
                    if current.state == "paused":
                        return
                    current.state = "paused"
                    current.progress = 0.0
                    current.error = ""
                    self._write(tasks)
                return
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _persist_state_transition(
        self,
        task: DownloadTask,
        state: str,
        *,
        output: str = "",
        error: str = "",
    ) -> None:
        """Persist a failed/completed transition, tolerating an applied write."""
        last_error: Optional[Exception] = None
        for _attempt in range(2):
            tasks = self._read()
            current = next((item for item in tasks if item.task_id == task.task_id), None)
            if current is None:
                return
            if state == "failed" and current.state == "failed":
                return
            if state == "completed" and current.state == "completed" and current.output == output:
                return
            try:
                current.state = state
                if state == "failed":
                    current.error = error
                else:
                    current.progress = 1.0
                    current.output = output
                    current.completed_at = time.time()
                    task.state = current.state
                    task.progress = current.progress
                    task.output = current.output
                    task.completed_at = current.completed_at
                self._write(tasks)
                return
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _persist_terminal_intent(self, intent: _TerminalIntent) -> None:
        if intent.state in {"pause", "remove"}:
            if intent.state == "remove" and intent.output:
                intent.task.output = intent.output
            self._persist_control_transition(intent.task, intent.control, intent.state)
            return
        self._persist_state_transition(
            intent.task,
            intent.state,
            output=intent.output,
            error=intent.error,
        )

    def _defer_terminal(
        self,
        task: DownloadTask,
        control: _TaskControl,
        state: str,
        *,
        output: str = "",
        error: str = "",
    ) -> None:
        """Release execution capacity while retaining the durable transition intent."""
        self._pending_terminal[task.task_id] = _TerminalIntent(
            task=task,
            control=control,
            state=state,
            output=output,
            error=error,
        )
        self._release(task.task_id, release_destination=False)

    def _replay_terminal_intents(self) -> None:
        completed: List[_TerminalIntent] = []
        failed: List[_TerminalIntent] = []
        with self._lock:
            for task_id, intent in list(self._pending_terminal.items()):
                try:
                    self._persist_terminal_intent(intent)
                except Exception:
                    LOGGER.warning("LunaTV terminal transition replay failed for %s", task_id)
                    continue
                self._pending_terminal.pop(task_id, None)
                if intent.state == "completed":
                    completed.append(intent)
                elif intent.state == "failed":
                    failed.append(intent)
                if intent.state != "completed":
                    self._active_destinations.pop(task_id, None)
        for intent in completed:
            try:
                try:
                    if self._on_complete is not None:
                        self._on_complete(intent.task, intent.output)
                except Exception:
                    LOGGER.exception("LunaTV completion hook failed")
                self._notify("LunaTV 已完成", self._notification_text(intent.task))
            finally:
                with self._lock:
                    self._active_destinations.pop(intent.task.task_id, None)
                    self._drain_wakeup.set()
        for intent in failed:
            self._notify(
                "LunaTV 下载失败",
                f"{self._notification_text(intent.task)}：{intent.error}",
            )

    def _finish_failed(
        self, task: DownloadTask, control: _TaskControl, exc: Exception
    ) -> Dict[str, Any]:
        with self._lock:
            if control.action == "remove":
                state = "remove"
            elif control.action == "pause":
                state = "pause"
            else:
                state = "failed"
            try:
                self._persist_terminal_intent(
                    _TerminalIntent(
                        task=task,
                        control=control,
                        state=state,
                        error=str(exc),
                    )
                )
            except Exception:
                self._defer_terminal(task, control, state, error=str(exc))
                persisted = False
            else:
                self._release(task.task_id)
                persisted = True
        if state == "failed" and persisted:
            self._notify("LunaTV 下载失败", f"{self._notification_text(task)}：{exc}")
            return {"processed": 1, "task_id": task.task_id, "state": state, "error": str(exc)}
        return {"processed": 1, "task_id": task.task_id, "state": state}

    def _finish_completed(
        self, task: DownloadTask, control: _TaskControl, output: str
    ) -> Dict[str, Any]:
        with self._lock:
            if control.action == "remove":
                state = "remove"
            elif control.action == "pause":
                state = "pause"
            else:
                state = "completed"
            final_output = task.output or output if state == "remove" else output
            try:
                self._persist_terminal_intent(
                    _TerminalIntent(
                        task=task,
                        control=control,
                        state=state,
                        output=final_output,
                    )
                )
            except Exception as exc:
                self._defer_terminal(
                    task,
                    control,
                    state,
                    output=final_output,
                    error=str(exc),
                )
                persisted = False
            else:
                persisted = True
                if state != "completed":
                    self._release(task.task_id)

        if state != "completed":
            return {"processed": 1, "task_id": task.task_id, "state": state}
        if not persisted:
            return {"processed": 1, "task_id": task.task_id, "state": state, "output": output}
        try:
            try:
                if self._on_complete is not None:
                    self._on_complete(task, output)
            except Exception:
                LOGGER.exception("LunaTV completion hook failed")
            self._notify("LunaTV 已完成", self._notification_text(task))
        finally:
            with self._lock:
                self._release(task.task_id)
        return {"processed": 1, "task_id": task.task_id, "state": "completed", "output": output}

    def _release(self, task_id: str, *, release_destination: bool = True) -> None:
        self._active.pop(task_id, None)
        if release_destination:
            self._active_destinations.pop(task_id, None)
        self._delete_file_tasks.discard(task_id)
        self._running = bool(self._active)
        self._current_task_id = next(iter(self._active), "")
        self._active_owner_id = None
        if not self._running:
            self._idle_event.set()
        self._drain_wakeup.set()

    def pause(self, task_id: str) -> bool:
        with self._lock:
            intent = self._pending_terminal.get(task_id)
            if intent is not None:
                return intent.state in {"pause", "remove"}
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None or task.state == "completed":
                return False
            if task.state == "paused":
                return True
            control = self._active.get(task_id)
            if task.state == "running" and control is not None:
                if control.action == "remove":
                    return True
                control.action = "pause"
                control.event.set()
                return True
            if task.state == "pending":
                task.state = "paused"
                task.progress = 0.0
                task.error = ""
                self._write(tasks)
                return True
            return False

    def remove(self, task_id: str, delete_file: bool = False) -> bool:
        with self._lock:
            intent = self._pending_terminal.get(task_id)
            if intent is not None:
                intent.state = "remove"
                intent.control.action = "remove"
                intent.control.delete_file = intent.control.delete_file or delete_file
                self._drain_wakeup.set()
                return True
            tasks = self._read()
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None:
                return False
            control = self._active.get(task_id)
            if task.state == "running" and control is not None:
                control.action = "remove"
                control.delete_file = control.delete_file or delete_file
                control.event.set()
                return True
            self._persist_removal(tasks, task, delete_file=delete_file)
            return True

    def wake(self) -> bool:
        with self._lock:
            if self._stop:
                return False
            self._wake_generation += 1
            self._drain_failed = False
            self._drain_wakeup.set()
            if self._drain_running:
                return True
            self._drain_running = True
        try:
            threading.Thread(target=self._drain, name="lunatvsource-download", daemon=True).start()
        except RuntimeError:
            with self._lock:
                self._drain_running = False
            return False
        return True

    def _drain(self) -> None:
        try:
            while True:
                self._replay_terminal_intents()
                with self._lock:
                    if self._stop or self._drain_failed:
                        return
                    tasks = self._read()
                    pending = any(task.state == "pending" for task in tasks)
                    can_dispatch = (
                        pending
                        and self._next_claimable_task(tasks) is not None
                        and len(self._active) + self._dispatching < self.max_concurrent_tasks
                    )
                    if can_dispatch:
                        self._dispatching += 1
                        dispatch_generation = self._wake_generation
                if can_dispatch:
                    try:
                        threading.Thread(
                            target=self._run_dispatched,
                            args=(dispatch_generation,),
                            name="lunatvsource-download-worker",
                            daemon=True,
                        ).start()
                    except RuntimeError:
                        with self._lock:
                            self._dispatching -= 1
                            self._drain_failed = self._wake_generation <= dispatch_generation
                            self._drain_wakeup.set()
                        LOGGER.exception("LunaTV queue worker start failed")
                    continue
                with self._lock:
                    active = bool(self._active)
                    pending = any(task.state == "pending" for task in self._read())
                    terminal_pending = bool(self._pending_terminal)
                    stopped = self._stop
                if stopped:
                    return
                if not active and not pending and not terminal_pending:
                    return
                self._drain_wakeup.wait(timeout=0.25)
                self._drain_wakeup.clear()
        finally:
            with self._lock:
                self._drain_running = False
                if (
                    not self._stop
                    and not self._drain_failed
                    and (
                        self._active
                        or self._pending_terminal
                        or any(task.state == "pending" for task in self._read())
                    )
                ):
                    self.wake()

    def _run_dispatched(self, dispatch_generation: int) -> None:
        self._execution.dispatched = True
        try:
            # Keep wake()/run_one() monkeypatch compatibility for host tests
            # and integrations while the scheduler owns only the slot count.
            self.run_one()
        except Exception:
            with self._lock:
                # A wake requested while this worker was failing is an
                # explicit retry intent; do not discard it with this failure.
                self._drain_failed = self._wake_generation <= dispatch_generation
            LOGGER.exception("LunaTV queue worker failed")
        finally:
            with self._lock:
                if getattr(self._execution, "dispatched", False):
                    self._dispatching -= 1
                    self._execution.dispatched = False
                self._drain_wakeup.set()

    def stop(self, wait: bool = False, timeout: Optional[float] = None) -> bool:
        with self._lock:
            self._stop = True
            for control in self._active.values():
                if not control.action:
                    control.action = "pause"
                control.event.set()
            self._drain_wakeup.set()
        return self.wait_until_idle(timeout) if wait else True

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        """Wait for active workers and the scheduler to exit without polling callers."""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                if (
                    not self._active
                    and not self._pending_terminal
                    and not self._dispatching
                    and not self._drain_running
                ):
                    return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            self._drain_wakeup.wait(timeout=0.02)
            self._drain_wakeup.clear()

    def stop_and_wait(self, timeout: float = 5.0) -> bool:
        """Compatibility-friendly bounded shutdown for plugin hot reload."""
        stopped = self.stop(wait=True, timeout=timeout)
        if stopped:
            return True
        with self._lock:
            self._stop = False
            self._drain_failed = False
            self._drain_wakeup.set()
        self.wake()
        return False

    def _execute(self, task: DownloadTask) -> str:
        relative_dir, filename = media_path(
            task.root, task.title, task.year, task.media_type, task.season,
            task.episode, task.url, task.mode,
        )
        root = Path(task.root).expanduser().resolve()
        destination = (root / relative_dir / filename).resolve()
        if root not in destination.parents:
            raise ValueError("目标路径越界")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 0:
            self._cleanup_m3u8_cache(task, destination.parent)
            return str(destination)
        if task.mode == "strm":
            temp_path = destination.with_suffix(destination.suffix + ".part")
            try:
                temp_path.write_text(task.url + "\n", encoding="utf-8")
                os.replace(temp_path, destination)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
            self._cleanup_m3u8_cache(task, destination.parent)
            return str(destination)
        temp_path = destination.with_suffix(destination.suffix + ".part")
        try:
            if not self._run_m3u8_engines(task, temp_path):
                raise RuntimeError("N_m3u8DL-RE 不可用或下载失败")
        except Exception:
            # Never invoke a plugin fallback. Keep engine cache for retry.
            temp_path.unlink(missing_ok=True)
            self._remove_empty_parents(destination.parent, root)
            raise
        if not temp_path.exists() or temp_path.stat().st_size <= 0:
            temp_path.unlink(missing_ok=True)
            self._remove_empty_parents(destination.parent, root)
            raise IOError("N_m3u8DL-RE 未生成有效文件")
        os.replace(temp_path, destination)
        self._cleanup_m3u8_cache(task, destination.parent)
        return str(destination)

    def _run_m3u8_engines(self, task: DownloadTask, output: Path) -> bool:
        if self._control_event.is_set():
            raise _QueueControl("controlled")
        if not self._m3u8_engines:
            return False
        with tempfile.TemporaryDirectory(prefix="lunatv-hls-") as temp_dir, _SegmentProxy() as proxy:
            input_url = self._prepare_hls_input(task.url, Path(temp_dir), proxy.url_for)
            segments = self._playlist_segment_count(Path(input_url))
            engine = self._m3u8_engines[0]
            kwargs = dict(
                task_id=task.task_id,
                ffmpeg_path=task.ffmpeg_path,
                control_event=self._control_event,
                progress_callback=lambda progress: self._update_progress(task.task_id, progress),
                expected_segments=segments,
            )
            try:
                engine.download(input_url, output, thread_count=self.segment_thread_count, **kwargs)
            except TypeError as exc:
                if "thread_count" not in str(exc):
                    raise
                engine.download(input_url, output, **kwargs)
            except M3U8EngineCancelled:
                raise _QueueControl("controlled")
            except (M3U8EngineError, OSError) as exc:
                if self._control_event.is_set():
                    raise _QueueControl("controlled") from exc
                LOGGER.warning("LunaTV N_m3u8DL-RE failed for %s: %s", task.task_id, exc)
                return False
        return True

    def task_cache_size(self, task_id: str) -> int:
        """Return bytes in the controlled cache/stage tree for one task only."""
        if not task_id or self._data_path is None or not self._m3u8_engines:
            return 0
        try:
            cache_base_path = self._data_path / "m3u8-cache"
            task_root_path = self._m3u8_engines[0]._cache_root(task_id)
            cache_base_path.lstat()
            task_root_path.lstat()
            if cache_base_path.is_symlink() or task_root_path.is_symlink() or not task_root_path.is_dir():
                return 0
            cache_base = cache_base_path.resolve(strict=True)
            task_root = task_root_path.resolve(strict=True)
            task_root.relative_to(cache_base)
            if task_root == cache_base:
                return 0
        except (AttributeError, OSError, ValueError):
            return 0
        total = 0
        for current, dirs, files in os.walk(task_root, followlinks=False):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if not (current_path / name).is_symlink()]
            for name in files:
                path = current_path / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    total += info.st_size
        return total
