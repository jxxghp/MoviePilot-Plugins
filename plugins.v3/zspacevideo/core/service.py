"""插件业务编排：分类缓存、整理事件 -> 刷新目标、后台提交与查询终态、记录与提醒。

与 MoviePilot 解耦：日志、通知、持久化都通过构造参数注入，单测里用假的。
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence

from . import pathmap
from .batcher import Batch, Batcher
from .cli import Cli, CliError, LoginSession
from .router import Library, Target, attach_dirs, parse_manual_dirs, read_zvideo_dirs, resolve_targets

# rescan_result.task_status：官方验收记录「扫描任务终态2」；0/1 视为排队/进行中。
TASK_DONE = 2
TASK_RUNNING = {0, 1}
AUTH_ERROR_CODES = {"E_AUTH", "E_OAUTH", "E_NOT_LOGGED_IN", "E_LOGIN_REQUIRED", "E_TOKEN", "E_UNAUTHORIZED"}


@dataclass
class Settings:
    enabled: bool = False
    connection_mode: str = "cloud"
    lan_host: str = ""
    path_mapping: str = ""
    library_dirs: str = ""
    zvideo_db: str = "/zvideo/zvideo.db"
    quiet_seconds: int = 60
    max_wait_seconds: int = 300
    poll_timeout_seconds: int = 1800
    notify: bool = True

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "Settings":
        config = config or {}
        base = cls()
        def _int(key: str, default: int, low: int, high: int) -> int:
            try:
                value = int(config.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(low, min(high, value))
        mode = str(config.get("connection_mode") or "cloud")
        return cls(
            enabled=bool(config.get("enabled", base.enabled)),
            connection_mode=mode if mode in ("cloud", "lan") else "cloud",
            lan_host=str(config.get("lan_host") or ""),
            path_mapping=str(config.get("path_mapping") or ""),
            library_dirs=str(config.get("library_dirs") or ""),
            zvideo_db=str(config.get("zvideo_db") or base.zvideo_db),
            quiet_seconds=_int("quiet_seconds", base.quiet_seconds, 0, 3600),
            max_wait_seconds=_int("max_wait_seconds", base.max_wait_seconds, 0, 7200),
            poll_timeout_seconds=_int("poll_timeout_seconds", base.poll_timeout_seconds, 60, 86400),
            notify=bool(config.get("notify", base.notify)),
        )

    def to_config(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RefreshRecord:
    id: str
    trigger: str
    library_id: str
    library_name: str
    paths: List[str]
    sources: List[str] = field(default_factory=list)
    task_id: str = ""
    status: str = "pending"  # pending / running / done / failed
    task_status: Optional[int] = None
    message: str = ""
    created_at: float = 0.0
    finished_at: float = 0.0


class Service:
    HISTORY_LIMIT = 100

    def __init__(self, cli: Cli, settings: Settings, *,
                 log: Any, notify: Callable[[str, str], None],
                 load_history: Callable[[], List[Dict[str, Any]]] = lambda: [],
                 save_history: Callable[[List[Dict[str, Any]]], None] = lambda _: None,
                 mountinfo_reader: Callable[[], str] = lambda: Path("/proc/self/mountinfo").read_text(),
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep,
                 poll_interval: float = 5.0) -> None:
        self.cli = cli
        self.settings = settings
        self.log = log
        self._notify = notify
        self._save_history = save_history
        self._mountinfo_reader = mountinfo_reader
        self._clock = clock
        self._sleep = sleep
        self.poll_interval = poll_interval
        self.login = LoginSession(cli)
        self.batcher = Batcher(quiet=settings.quiet_seconds,
                               max_wait=max(settings.quiet_seconds, settings.max_wait_seconds))
        self._history: Deque[Dict[str, Any]] = deque(load_history() or [], maxlen=self.HISTORY_LIMIT)
        self._libraries: List[Library] = []
        self._libraries_at = 0.0
        self._libraries_source = ""
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._alerted: Optional[str] = None
        self._seq = 0

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="zspacevideo-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self.login.cancel()
        dropped = self.batcher.pop_due(force=True)
        if dropped:
            self.log.warning(f"极空间影视：插件停止，丢弃 {len(dropped)} 个未提交的刷新批次")
        if self._thread:
            self._thread.join(timeout=10)
        self._thread = None

    # ------------------------------------------------------------------ 路径映射
    def mappings(self) -> List[pathmap.Mapping]:
        manual = pathmap.parse_manual(self.settings.path_mapping)
        if manual:
            return manual
        try:
            return pathmap.infer_mappings(self._mountinfo_reader())
        except OSError as error:
            self.log.warning(f"极空间影视：读取挂载信息失败：{error}")
            return []

    # ------------------------------------------------------------------ 分类
    def libraries(self, force: bool = False) -> List[Library]:
        with self._lock:
            if not force and self._libraries and self._clock() - self._libraries_at < 600:
                return self._libraries
        raw = self.cli.libraries()
        libs = [Library(id=str(x.get("id")), name=str(x.get("name") or ""), is_system=bool(x.get("is_system")))
                for x in raw if x.get("id")]
        dirs: Dict[str, List[str]] = {}
        source = ""
        if self.settings.library_dirs.strip():
            dirs = parse_manual_dirs(self.settings.library_dirs, libs)
            source = "manual"
        elif self.settings.zvideo_db and Path(self.settings.zvideo_db).exists():
            try:
                dirs = read_zvideo_dirs(self.settings.zvideo_db)
                source = "zvideo.db"
            except Exception as error:  # noqa: BLE001
                self.log.warning(f"极空间影视：读取极影视库目录失败：{error}")
        known = {lib.id for lib in libs}
        dirs = {k: v for k, v in dirs.items() if k in known}
        # 只保留当前账号确实能看到的目录（dirs 返回全部分类目录并集）
        try:
            visible = set(pathmap.normalize(p) for p in self.cli.all_dirs())
            if visible:
                dirs = {k: [p for p in v if p in visible] for k, v in dirs.items()}
        except CliError as error:
            self.log.warning(f"极空间影视：读取分类目录并集失败：{error}")
        libs = attach_dirs(libs, dirs)
        with self._lock:
            self._libraries = libs
            self._libraries_at = self._clock()
            self._libraries_source = source or "none"
        return libs

    @property
    def libraries_source(self) -> str:
        return self._libraries_source

    # ------------------------------------------------------------------ 事件入口
    def resolve(self, container_path: str) -> Dict[str, Any]:
        zspace = pathmap.to_zspace(container_path, self.mappings())
        if not zspace:
            return {"container_path": container_path, "zspace_path": None, "targets": [],
                    "reason": "路径不在任何已映射的极空间目录下"}
        targets = resolve_targets(zspace, self.libraries())
        return {"container_path": container_path, "zspace_path": zspace,
                "targets": [asdict(t) for t in targets],
                "reason": "" if targets else "没有分类包含这个目录"}

    def on_transfer(self, container_path: str, source: str = "") -> List[Target]:
        """整理完成：登记刷新目标，返回命中的目标（不会立刻提交）。"""
        if not self.settings.enabled:
            return []
        try:
            info = self.resolve(container_path)
        except CliError as error:
            # 整理事件里第一次发现授权失效也要提醒（否则这次整理既不刷新也没人知道）
            if error.code in AUTH_ERROR_CODES or "登录" in error.message or "授权" in error.message:
                self._alert(f"极空间授权失效，请到插件页重新授权（{error.code}）", key="auth")
            else:
                self._alert(f"读取极影视分类失败，{container_path} 没有刷新：{error}", key=f"err:{error.code}")
            return []
        targets = [Target(**t) for t in info["targets"]]
        if not targets:
            self.log.info(f"极空间影视：{container_path} 不刷新（{info['reason']}）")
            return []
        for target in targets:
            self.batcher.add(target, source=source)
        self.log.info("极空间影视：已登记刷新 " + "；".join(
            f"{t.library_name} <- {t.path}" for t in targets))
        self._wake.set()
        return targets

    def refresh_library(self, library_id: str) -> Dict[str, Any]:
        """手动立即刷新一个分类的全部目录。"""
        lib = next((x for x in self.libraries(force=True) if x.id == library_id), None)
        if lib is None:
            raise CliError("E_PARAM", "找不到这个分类")
        if not lib.dirs:
            raise CliError("E_PARAM", f"分类「{lib.name}」没有已知目录，请在配置里补「分类目录」")
        batch = Batch(library_id=lib.id, library_name=lib.name, paths=pathmap.merge_paths(lib.dirs),
                      sources=["手动刷新"])
        record = self._new_record(batch, trigger="manual")
        threading.Thread(target=self._execute, args=(batch, record), daemon=True,
                         name="zspacevideo-manual").start()
        return record

    def refresh_paths(self, container_paths: Sequence[str], source: str) -> List[Dict[str, Any]]:
        """同步刷新若干容器目录（按所属分类合并），等到终态后返回刷新记录。删除后核对用。"""
        grouped: Dict[str, Batch] = {}
        for path in container_paths:
            info = self.resolve(path)
            for raw in info["targets"]:
                target = Target(**raw)
                batch = grouped.setdefault(target.library_id, Batch(library_id=target.library_id,
                                                                    library_name=target.library_name,
                                                                    paths=[], sources=[source]))
                batch.paths.append(target.path)
        records = []
        for batch in grouped.values():
            batch.paths = pathmap.merge_paths(batch.paths)
            record = self._new_record(batch, trigger="watched")
            self._execute(batch, record)
            records.append(dict(record))
        return records

    # ------------------------------------------------------------------ 后台
    def _loop(self) -> None:
        while not self._stop.is_set():
            wait = self.batcher.next_due_in()
            self._wake.wait(timeout=30 if wait is None else max(0.5, wait))
            self._wake.clear()
            if self._stop.is_set():
                break
            for batch in self.batcher.pop_due():
                record = self._new_record(batch, trigger="transfer")
                try:
                    self._execute(batch, record)
                except Exception:  # noqa: BLE001
                    self.log.error("极空间影视：刷新出错\n" + traceback.format_exc())

    def _new_record(self, batch: Batch, trigger: str) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            record = RefreshRecord(id=f"{int(self._clock())}-{self._seq}", trigger=trigger,
                                   library_id=batch.library_id, library_name=batch.library_name,
                                   paths=list(batch.paths), sources=list(batch.sources),
                                   created_at=self._clock())
            data = asdict(record)
            self._history.appendleft(data)
        self._persist()
        return data

    def _update(self, record: Dict[str, Any], **changes: Any) -> None:
        with self._lock:
            record.update(changes)
        self._persist()

    def _persist(self) -> None:
        try:
            with self._lock:
                snapshot = list(self._history)
            self._save_history(snapshot)
        except Exception as error:  # noqa: BLE001
            self.log.warning(f"极空间影视：保存刷新记录失败：{error}")

    def history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(x) for x in self._history]

    def _wait_login_done(self) -> None:
        """登录事务进行中 CLI 会锁住 profile（E_PROFILE_BUSY），先等它结束。"""
        while self.login.active() and not self._stop.is_set():
            self._sleep(self.poll_interval or 1.0)

    def _execute(self, batch: Batch, record: Dict[str, Any]) -> None:
        try:
            self._wait_login_done()
            self._wait_idle(batch.library_id)
            if self._stop.is_set():  # 插件已停止：不再提交，记为取消
                self._update(record, status="cancelled", finished_at=self._clock(), message="插件已停止，未提交")
                return
            task_id = self.cli.rescan(batch.library_id, batch.paths)
            self._update(record, task_id=task_id, status="running")
            self.log.info(f"极空间影视：已提交 {batch.library_name} 刷新 {batch.paths}，任务 {task_id}")
            status = self._poll(task_id)
            if status == TASK_DONE:
                self._update(record, status="done", task_status=status, finished_at=self._clock(),
                             message="完成")
                self.log.info(f"极空间影视：{batch.library_name} 刷新完成（任务 {task_id}）")
                self._alerted = None
            else:
                msg = "查询超时，任务未到终态" if status is None else f"任务状态 {status}"
                self._update(record, status="failed", task_status=status, finished_at=self._clock(),
                             message=msg)
                self._alert(f"{batch.library_name} 刷新没有完成：{msg}", key=f"task:{batch.library_id}")
        except CliError as error:
            self._update(record, status="failed", finished_at=self._clock(), message=str(error))
            if error.code in AUTH_ERROR_CODES or "登录" in error.message or "授权" in error.message:
                self._alert(f"极空间授权失效，请到插件页重新授权（{error.code}）", key="auth")
            else:
                self._alert(f"{batch.library_name} 刷新失败：{error}", key=f"err:{error.code}")
        except Exception as error:  # noqa: BLE001
            self._update(record, status="failed", finished_at=self._clock(), message=repr(error))
            self._alert(f"{batch.library_name} 刷新异常：{error!r}", key="exception")

    def _wait_idle(self, library_id: str, limit: float = 300.0) -> None:
        deadline = self._clock() + limit
        while not self._stop.is_set():
            try:
                if self.cli.scan_status(library_id) == 0:
                    return
            except CliError:
                return
            if self._clock() >= deadline:
                self.log.info("极空间影视：分类一直在扫描，仍然提交刷新")
                return
            self._sleep(self.poll_interval)

    def _poll(self, task_id: str) -> Optional[int]:
        deadline = self._clock() + self.settings.poll_timeout_seconds
        status: Optional[int] = None
        while True:
            try:
                status = self.cli.rescan_result(task_id)
            except CliError as error:
                if error.code in AUTH_ERROR_CODES:
                    raise
                status = None
            if status is not None and status not in TASK_RUNNING:
                return status
            if self._clock() >= deadline or self._stop.is_set():
                return None
            self._sleep(self.poll_interval)

    def _alert(self, text: str, key: str) -> None:
        """同一类问题只提醒一次，直到出现一次成功刷新。"""
        self.log.error(f"极空间影视：{text}")
        if self._alerted == key or not self.settings.notify:
            return
        self._alerted = key
        try:
            self._notify("极空间影视刷新失败", text)
        except Exception as error:  # noqa: BLE001
            self.log.warning(f"极空间影视：发送提醒失败：{error}")

    # ------------------------------------------------------------------ 状态
    def auth_status(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {"binary": self.cli.binary.status(),
                                "connection_mode": self.settings.connection_mode}
        if self.login.active():
            # 登录进程占着 profile 锁，此时调 status 会得到 E_PROFILE_BUSY
            info.update({"logged_in": None, "login_pending": True, "login_url": self.login.url,
                         "login_remaining": self.login.remaining()})
            return info
        try:
            status = self.cli.status()
            info.update({
                "logged_in": bool(status.get("logged_in")),
                "expires_at": status.get("expires_at"),
                "nas_id": status.get("nas_id"),
                "credential_store": status.get("credential_store"),
            })
        except CliError as error:
            info.update({"logged_in": False, "error": str(error)})
        info["login_pending"] = self.login.active()
        info["login_url"] = self.login.url if self.login.active() else None
        info["login_remaining"] = self.login.remaining()
        return info
