# -*- coding: utf-8 -*-
"""
源文件联动清理插件 (MoviePilot V2)
==================================

监控源文件（下载目录）中的文件删除事件，当源文件被删除后，自动联动删除
媒体库中对应的硬链接文件、刮削文件（元数据、图片、字幕）与转移记录，
并支持空目录清理、延迟删除（防止媒体重整理导致误删）与通知。

设计参考：https://github.com/DzAvril/MoviePilot-Plugins/tree/main/plugins/removelink
本插件为独立实现，聚焦硬链接联动清理场景。

工作方式：
- 通过 watchdog/watchfiles 监控源目录与媒体库目录，记录每个文件路径对应的
  (dev, inode)；
- 当源文件被删除时，在监控集合中查找相同 (dev, inode) 的其他路径（即硬链接），
  联动删除硬链接、刮削文件与转移记录，并通过 DownloadFileDeleted 事件联动
  下载器助手删除种子（可选）；
- 延迟删除模式下，删除事件会先进入队列，等待一段时间后再校验执行，防止
  媒体重整理/重命名导致的误删。
"""
import os
import platform
import shutil
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from app.core.event import eventmanager
from app.db.transferhistory_oper import TransferHistoryOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import EventType

# 全局状态锁，保护 file_state 的读写
state_lock = threading.Lock()
# 延迟删除队列锁
deletion_queue_lock = threading.Lock()
# 临时文件后缀：不进入监控状态，也不触发清理流程（全量扫描与增量监控共用）
TEMP_FILE_SUFFIXES = (".!qb", ".part", ".mp", ".tmp", ".temp")


class FileInfo(NamedTuple):
    """监控文件信息"""

    dev: int
    inode: int
    add_time: datetime


@dataclass
class DeletionTask:
    """延迟删除任务"""

    file_path: Path
    deleted_dev: int
    deleted_inode: int
    deleted_add_time: datetime
    timestamp: datetime
    # 删除事件发生时已存在的同实体路径（正常硬链接），用于延迟到期后
    # 区分“原有硬链接”与“重新整理产生的新路径”
    known_paths: Optional[List[str]] = None
    processed: bool = False


# ---------------------------------------------------------------
# watchfiles 兼容层：当环境未安装 watchdog 时，退化为 watchfiles
# ---------------------------------------------------------------
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers.polling import PollingObserver
except ImportError:  # pragma: no cover
    class FileSystemEventHandler:
        """watchdog 事件处理器占位"""

        def __init__(self, *args, **kwargs):
            pass

    class _WatchfilesEvent:
        """watchfiles 事件包装"""

        def __init__(self, src_path: str, is_directory: bool = False):
            self.src_path = src_path
            self.is_directory = is_directory

    class _WatchfilesMoveEvent:
        """watchfiles 移动事件包装（重命名）"""

        def __init__(self, src_path: str, dest_path: str, is_directory: bool = False):
            self.src_path = src_path
            self.dest_path = dest_path
            self.is_directory = is_directory

    class _WatchfilesObserver:
        """基于 watchfiles 的简易观察器"""

        def __init__(self):
            self.daemon = False
            self._watches = []
            self._threads = []
            self._stop_event = threading.Event()

        def schedule(self, event_handler, path, recursive=True):
            """注册目录监控任务。"""
            self._watches.append((event_handler, path, recursive))

        def start(self):
            """启动所有监控线程。"""
            for event_handler, path, recursive in self._watches:
                thread = threading.Thread(
                    target=self._watch,
                    args=(event_handler, path, recursive),
                    daemon=self.daemon,
                )
                self._threads.append(thread)
                thread.start()

        def stop(self):
            """停止监控。"""
            self._stop_event.set()

        def join(self, timeout=None):
            """等待所有监控线程退出。"""
            for thread in self._threads:
                thread.join(timeout)

        def _watch(self, event_handler, path, recursive):
            """watchfiles 监控循环，将变更事件转发给事件处理器。"""
            from watchfiles import Change, watch

            # 记录已观察路径 -> (dev, inode)，用于把同一批次中 inode 相同的
            # added + deleted 事件配对为移动（重命名），避免重命名被当作删除处理
            known_identities: Dict[str, Tuple[int, int]] = {}
            # 初始建表：为监控启动前已存在的文件建立身份快照，
            # 否则回退模式下重命名既有文件仍会被误判为删除
            try:
                for root, _, files in os.walk(path):
                    for file_name in files:
                        file_path = Path(root) / file_name
                        try:
                            stat_info = file_path.stat()
                            known_identities[str(file_path)] = (stat_info.st_dev, stat_info.st_ino)
                        except OSError:
                            continue
            except OSError as e:
                logger.warning(f"watchfiles 回退：初始身份建表失败：{e}")

            for changes in watch(path, recursive=recursive, stop_event=self._stop_event):
                added_paths = [str(p) for c, p in changes if c == Change.added]
                for changed_path in added_paths:
                    try:
                        stat_info = Path(changed_path).stat()
                        known_identities[changed_path] = (stat_info.st_dev, stat_info.st_ino)
                    except OSError:
                        known_identities.pop(changed_path, None)
                    event_handler.on_created(
                        _WatchfilesEvent(changed_path, Path(changed_path).is_dir())
                    )
                for change, changed_path in changes:
                    changed_path = str(changed_path)
                    if change != Change.deleted:
                        continue
                    old_identity = known_identities.pop(changed_path, None)
                    moved = False
                    if old_identity is not None:
                        for new_path in added_paths:
                            if new_path == changed_path or known_identities.get(new_path) != old_identity:
                                continue
                            logger.debug(f"watchfiles 回退：{changed_path} -> {new_path} 识别为移动，不进入删除流程")
                            event_handler.on_moved(
                                _WatchfilesMoveEvent(changed_path, new_path, Path(new_path).is_dir())
                            )
                            moved = True
                            break
                    if not moved:
                        event_handler.on_deleted(_WatchfilesEvent(changed_path))

    PollingObserver = _WatchfilesObserver


class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控处理：维护文件状态集合，并响应创建/删除事件。
    """

    def __init__(self, monpath: str, sync: "ScrapeFileClean", **kwargs):
        super(FileMonitorHandler, self).__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def _is_excluded_file(self, file_path: Path) -> bool:
        """检查文件是否命中排除规则（临时文件 / 关键字）"""
        if file_path.suffix.lower() in TEMP_FILE_SUFFIXES:
            return True
        if self.sync.exclude_keywords:
            for keyword in self.sync.exclude_keywords.split("\n"):
                if keyword and keyword in str(file_path):
                    logger.debug(f"{file_path} 命中过滤关键字 {keyword}，不处理")
                    return True
        return False

    def _is_within_monitor(self, file_path: Path) -> bool:
        """判断路径是否在任一监控目录内"""
        for mon_dir in self.sync.monitor_dirs.split("\n"):
            mon_dir = mon_dir.strip()
            if mon_dir and self.sync._is_same_or_child_path(file_path, mon_dir):
                return True
        return False

    def _add_file_to_state(self, file_path: Path):
        """把新增文件加入监控状态"""
        if self._is_excluded_file(file_path):
            return
        with state_lock:
            try:
                if not file_path.exists() or file_path.is_dir() or file_path.is_symlink():
                    return
                stat_info = file_path.stat()
                self.sync.file_state[str(file_path)] = FileInfo(
                    dev=stat_info.st_dev,
                    inode=stat_info.st_ino,
                    add_time=datetime.now(),
                )
                logger.debug(f"添加文件到监控：{file_path}")
            except (OSError, PermissionError) as e:
                logger.debug(f"无法访问文件 {file_path}：{e}")
            except Exception as e:
                logger.error(f"新增文件记录失败：{str(e)}")

    def on_created(self, event):
        """处理文件创建事件，将新增文件加入监控状态。"""
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        logger.debug(f"监测到新增文件：{file_path}")
        self._add_file_to_state(file_path)

    def on_moved(self, event):
        """处理文件移动事件，目标未进入监控时按删除处理源文件。"""
        if event.is_directory:
            return
        src_path = Path(event.src_path)
        dest_path = Path(event.dest_path)
        logger.info(f"监测到文件移动：{src_path} -> {dest_path}")

        # 取出源路径的监控信息，同时取出目标路径原记录（可能被新实体覆盖）
        with state_lock:
            src_file_info = self.sync.file_state.pop(str(src_path), None)
            old_dest_file_info = self.sync.file_state.pop(str(dest_path), None)

        # 目标路径原本存在且实体与源不一致：旧实体已被替换删除，进入清理流程
        if old_dest_file_info is not None and (
            src_file_info is None
            or not self.sync._same_file_identity(old_dest_file_info, src_file_info.dev, src_file_info.inode)
        ):
            if self.sync._delayed_deletion:
                # 延迟模式：入队后由延迟校验处理，执行时路径已被新实体占用，只清理旧实体硬链接
                with state_lock:
                    self.sync.file_state[str(dest_path)] = old_dest_file_info
                logger.info(f"移动目标 {dest_path} 的原文件实体已被覆盖，按删除处理旧实体")
                self.sync.handle_deleted(dest_path)
                with state_lock:
                    self.sync.file_state.pop(str(dest_path), None)
            else:
                # 立即模式：路径已被新实体占用，只清理旧实体硬链接，不做路径关联副作用
                logger.info(f"移动目标 {dest_path} 的原文件实体已被覆盖，仅清理旧实体硬链接")
                self.sync._execute_deletion(
                    dest_path, old_dest_file_info.dev, old_dest_file_info.inode, skip_path_effects=True
                )

        # 尝试接管目标路径
        self._add_file_to_state(dest_path)

        with state_lock:
            dest_file_info = self.sync.file_state.get(str(dest_path))

        # 目标未进入监控，或文件实体不一致（如整目录删除时目标瞬时消失），
        # 则把源路径按删除事件处理，避免残留硬链接和转移记录。
        if src_file_info and (
            not dest_file_info
            or not self.sync._same_file_identity(dest_file_info, src_file_info.dev, src_file_info.inode)
        ):
            # 目标仍在监控目录内但未被跟踪（临时文件/过滤关键字等忽略目标）：
            # 这是重命名而非删除，不触发源文件清理
            if self._is_within_monitor(dest_path):
                logger.info(f"移动目标 {dest_path} 仍在监控范围内但被忽略，按重命名处理，不触发清理")
                return
            logger.info(f"移动目标未进入监控或文件实体不一致，按删除处理源文件：{src_path}")
            with state_lock:
                self.sync.file_state[str(src_path)] = src_file_info
            self.sync.handle_deleted(src_path)

    def on_deleted(self, event):
        """处理文件删除事件，联动清理硬链接、刮削文件与转移记录。"""
        file_path = Path(event.src_path)
        if event.is_directory:
            # 文件夹被整体删除：触发下载器助手联动删除种子
            if self.sync._delete_torrents:
                if self.sync.exclude_keywords:
                    for keyword in self.sync.exclude_keywords.split("\n"):
                        if keyword and keyword in str(file_path):
                            logger.info(f"{file_path} 命中过滤关键字 {keyword}，不处理")
                            return
                logger.info(f"监测到删除文件夹：{file_path}")
                eventmanager.send_event(EventType.DownloadFileDeleted, {"src": str(file_path)})
            return
        if file_path.suffix.lower() in TEMP_FILE_SUFFIXES:
            return
        if self.sync.exclude_keywords:
            for keyword in self.sync.exclude_keywords.split("\n"):
                if keyword and keyword in str(file_path):
                    logger.info(f"{file_path} 命中过滤关键字 {keyword}，不处理")
                    return
        logger.info(f"监测到删除文件：{file_path}")
        self.sync.handle_deleted(file_path)

def update_state(monitor_dirs: List[str]) -> Dict[str, FileInfo]:
    """
    全量扫描监控目录，重建文件状态集合。
    """
    start_time = time.time()
    file_state: Dict[str, FileInfo] = {}
    init_time = datetime.now()
    error_count = 0

    for mon_path in monitor_dirs:
        if not mon_path or not os.path.exists(mon_path):
            logger.warning(f"监控目录不存在：{mon_path}")
            continue
        try:
            for root, _, files in os.walk(mon_path):
                for file_name in files:
                    file_path = Path(root) / file_name
                    if file_path.suffix.lower() in TEMP_FILE_SUFFIXES:
                        continue
                    try:
                        if not file_path.exists() or file_path.is_symlink():
                            continue
                        stat_info = file_path.stat()
                        file_state[str(file_path)] = FileInfo(
                            dev=stat_info.st_dev,
                            inode=stat_info.st_ino,
                            add_time=init_time,
                        )
                    except (OSError, PermissionError) as e:
                        error_count += 1
                        logger.debug(f"无法访问文件 {file_path}：{e}")
        except Exception as e:
            logger.error(f"扫描目录 {mon_path} 时发生错误：{e}")

    elapsed = time.time() - start_time
    logger.info(f"更新文件列表完成，共计 {len(file_state)} 个文件，耗时 {elapsed:.2f} 秒")
    if error_count > 0:
        logger.warning(f"扫描过程中有 {error_count} 个文件无法访问")
    return file_state


class ScrapeFileClean(_PluginBase):
    """
    源文件联动清理插件主类
    """

    # 插件元信息
    plugin_name = "源文件联动清理"
    plugin_desc = "为手动清理下载目录设计：手动删除源文件后，自动联动清理媒体库中对应的硬链接文件、刮削文件（元数据、图片、字幕）与转移记录，支持延迟删除防止误删"
    plugin_icon = "clean.png"
    plugin_version = "1.0.7"
    plugin_author = "xlmc"
    author_url = "https://github.com/xlmc"
    plugin_config_prefix = "scrapefileclean_"
    plugin_order = 0
    auth_level = 1

    # 内置刮削文件后缀（元数据 / 图片 / 字幕）
    SCRAP_EXTENSIONS = [
        ".nfo", ".xml",
        ".jpg", ".jpeg", ".png", ".webp", ".tbn", ".fanart", ".gif", ".bmp",
        ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup", ".pgs",
        ".smi", ".rt", ".sbv", ".csf-bk", ".csf-tmp",
    ]
    # 刮削/媒体服务器生成的关联目录后缀
    SCRAP_DIR_SUFFIXES = [".trickplay"]

    # 配置项
    monitor_dirs = ""
    exclude_dirs = ""
    exclude_keywords = ""
    custom_scrap_extensions = ""

    _enabled = False
    _notify = False
    _delete_scrap_infos = False
    _delete_torrents = False
    _delete_history = False
    _delayed_deletion = True
    _delay_seconds = 30
    _custom_scrap_extensions: List[str] = []

    _transferhistory: Optional[TransferHistoryOper] = None
    _observer: List[Any] = []
    # 监控文件状态 {路径: FileInfo}
    file_state: Dict[str, FileInfo] = {}
    # 延迟删除队列
    deletion_queue: List[DeletionTask] = []
    _deletion_timer: Optional[threading.Timer] = None

    # -----------------------------------------------------------
    # 观察器选择
    # -----------------------------------------------------------
    @staticmethod
    def __choose_observer():
        """根据操作系统选择最优观察器，无 watchdog 时回退 watchfiles"""
        system = platform.system()
        try:
            if system == "Linux":
                from watchdog.observers.inotify import InotifyObserver
                return InotifyObserver()
            elif system == "Darwin":
                from watchdog.observers.fsevents import FSEventsObserver
                return FSEventsObserver()
            elif system == "Windows":
                from watchdog.observers.read_directory_changes import WindowsApiObserver
                return WindowsApiObserver()
        except ImportError:
            pass
        return PollingObserver()

    # -----------------------------------------------------------
    # 插件生命周期
    # -----------------------------------------------------------
    def init_plugin(self, config: dict = None):
        """根据配置初始化插件，启动目录监控并重建文件状态。"""
        self.stop_service()

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._notify = bool(config.get("notify"))
        self._delete_scrap_infos = bool(config.get("delete_scrap_infos"))
        self._delete_torrents = bool(config.get("delete_torrents"))
        self._delete_history = bool(config.get("delete_history"))
        self._delayed_deletion = bool(config.get("delayed_deletion", True))
        self.monitor_dirs = config.get("monitor_dirs") or ""
        self.exclude_dirs = config.get("exclude_dirs") or ""
        self.exclude_keywords = config.get("exclude_keywords") or ""
        self.custom_scrap_extensions = config.get("custom_scrap_extensions") or ""
        self._custom_scrap_extensions = self._parse_custom_scrap_extensions(self.custom_scrap_extensions)

        # 延迟时间：10 秒 ~ 24 小时
        delay_seconds = config.get("delay_seconds", 30)
        try:
            self._delay_seconds = max(10, min(86400, int(delay_seconds)))
        except (TypeError, ValueError):
            self._delay_seconds = 30

        # 初始化组件
        self._transferhistory = TransferHistoryOper()
        self.deletion_queue = []
        self.file_state = {}

        if not self._enabled:
            logger.info("源文件联动清理插件未启用")
            return

        if self._delayed_deletion:
            logger.info(f"延迟删除功能已启用，延迟时间: {self._delay_seconds} 秒")
        else:
            logger.info("延迟删除功能已禁用，将使用立即删除模式")

        # 读取监控目录配置（源目录 + 媒体库目录）
        monitor_dirs = [d.strip() for d in self.monitor_dirs.split("\n") if d.strip()]
        logger.info(f"监控目录：{monitor_dirs}")

        # 启动监控
        for mon_path in monitor_dirs:
            self._start_observer(mon_path)

        # 全量重建文件状态
        with state_lock:
            self.file_state = update_state(monitor_dirs)

    def _start_observer(self, mon_path: str):
        """启动单个目录监控"""
        if not mon_path:
            return
        try:
            observer = self.__choose_observer()
            self._observer.append(observer)
            observer.schedule(
                FileMonitorHandler(mon_path, self),
                mon_path,
                recursive=True,
            )
            observer.daemon = True
            observer.start()
            logger.info(f"{mon_path} 的目录监控服务启动")
        except Exception as e:
            err_msg = str(e)
            if "inotify" in err_msg and "reached" in err_msg:
                logger.warn(
                    f"目录监控服务启动出现异常：{err_msg}，请在宿主机上执行以下命令并重启：\n"
                    "echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf\n"
                    "echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf\n"
                    "sudo sysctl -p"
                )
            else:
                logger.error(f"{mon_path} 启动目录监控失败：{err_msg}")
            self.systemmessage.put(f"{mon_path} 启动目录监控失败：{err_msg}", title="源文件联动清理")

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """没有远程命令，返回空列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """没有插件 API，返回空列表。"""
        return []

    def get_page(self) -> Optional[List[dict]]:
        """没有详情页，返回 None。"""
        return None

    def stop_service(self):
        """停止监控、定时器，放弃未到期的延迟删除任务"""
        logger.debug("开始停止服务")

        # 停止文件监控
        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    logger.error(f"停止目录监控失败：{str(e)}")
        self._observer = []
        logger.debug("文件监控已停止")

        # 停止延迟删除定时器
        if self._deletion_timer:
            try:
                self._deletion_timer.cancel()
            except Exception as e:
                logger.error(f"停止延迟删除定时器失败：{str(e)}")
            self._deletion_timer = None

        # 未到期的延迟删除任务不做提前执行：停止服务时保留文件原状，
        # 避免媒体重整理期间误删硬链接，重新启用后由全量扫描重建状态
        with deletion_queue_lock:
            pending = [t for t in self.deletion_queue if not t.processed]
            if pending:
                logger.info(f"放弃 {len(pending)} 个未到期的延迟删除任务（停止服务时不提前执行）")
            self.deletion_queue.clear()

        logger.debug("服务停止完成")

    # -----------------------------------------------------------
    # 删除事件处理
    # -----------------------------------------------------------
    def handle_deleted(self, file_path: Path):
        """处理文件删除事件：查找相同 inode 的硬链接并联动清理"""
        logger.debug(f"处理删除事件: {file_path}")

        with state_lock:
            file_info = self.file_state.get(str(file_path))
            if not file_info:
                logger.debug(f"文件 {file_path} 未在监控列表中，跳过处理")
                return
            deleted_inode = file_info.inode
            deleted_dev = file_info.dev
            deleted_add_time = file_info.add_time
            self.file_state.pop(str(file_path))

        if self._delayed_deletion:
            # 延迟删除模式：入队，稍后统一校验执行
            logger.info(f"文件 {file_path.name} 加入延迟删除队列，延迟 {self._delay_seconds} 秒")
            # 记录删除事件发生时已存在的同实体路径（正常硬链接），
            # 延迟到期后用于区分“原有硬链接”与“重新整理产生的新路径”
            with state_lock:
                known_paths = [
                    path
                    for path, file_info in self.file_state.items()
                    if self._same_file_identity(file_info, deleted_dev, deleted_inode)
                ]
            task = DeletionTask(
                file_path=file_path,
                deleted_dev=deleted_dev,
                deleted_inode=deleted_inode,
                deleted_add_time=deleted_add_time,
                timestamp=datetime.now(),
                known_paths=known_paths,
            )
            with deletion_queue_lock:
                self.deletion_queue.append(task)
                if not self._deletion_timer:
                    self._start_deletion_timer()
                    logger.debug("启动延迟删除定时器")
        else:
            # 立即删除模式
            self._execute_deletion(file_path, deleted_dev, deleted_inode)

    def _execute_deletion(self, file_path: Path, deleted_dev: int, deleted_inode: int, skip_path_effects: bool = False):
        """
        执行删除动作：清理刮削文件、联动删除种子、删除转移记录、删除硬链接。

        skip_path_effects=True 时仅清理旧实体硬链接，不做任何路径关联的副作用
        （路径已被新实体占用时使用，避免误伤现存的新文件）。
        """
        deleted_files: List[str] = []

        # 源文件侧清理（路径关联副作用；路径已被新实体占用时跳过）
        if not skip_path_effects:
            self.delete_scrap_infos(file_path)
            if self._delete_torrents and not self._is_scrap_file(file_path):
                eventmanager.send_event(EventType.DownloadFileDeleted, {"src": str(file_path)})
            self.delete_history(str(file_path))

        try:
            with state_lock:
                for path, file_info in self.file_state.copy().items():
                    if self._same_file_identity(file_info, deleted_dev, deleted_inode):
                        file = Path(path)
                        if not self._unlink_tracked_file(file, path, "删除"):
                            continue
                        deleted_files.append(path)

                        # 硬链接侧清理
                        self.delete_scrap_infos(file)
                        if self._delete_torrents and not self._is_scrap_file(file):
                            eventmanager.send_event(EventType.DownloadFileDeleted, {"src": str(file)})
                        self.delete_history(str(file))
        except Exception as e:
            logger.error(f"删除硬链接文件发生错误：{str(e)} - {traceback.format_exc()}")

        # 通知
        if self._notify and deleted_files:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title="🧹 源文件联动清理",
                text=self._build_notification_text(file_path, deleted_files, delayed=False),
            )

    def _build_notification_text(self, src_path: Path, deleted_files: List[str], delayed: bool) -> str:
        """组装清理结果通知文本"""
        parts = [f"🗂️ 源文件：{src_path}"]
        if len(deleted_files) == 1:
            parts.append(f"🔗 硬链接：{deleted_files[0]}")
        elif deleted_files:
            parts.append(f"🔗 删除了 {len(deleted_files)} 个硬链接文件")
        if self._delete_history:
            parts.append("📝 已清理转移记录")
        if self._delete_torrents:
            parts.append("🌱 已联动删除种子")
        if self._delete_scrap_infos:
            parts.append("🖼️ 已清理刮削文件")
        prefix = "⏰ 延迟删除完成" if delayed else "⚡ 立即删除完成"
        return f"{prefix}\n\n" + "\n".join(parts)

    # -----------------------------------------------------------
    # 延迟删除
    # -----------------------------------------------------------
    def _start_deletion_timer(self, delay_time: Optional[float] = None):
        """启动延迟删除定时器（调用前需持有 deletion_queue_lock 或确认无运行中定时器）"""
        if delay_time is None:
            delay_time = self._delay_seconds
        self._deletion_timer = threading.Timer(delay_time, self._process_deletion_queue)
        self._deletion_timer.daemon = True
        self._deletion_timer.start()

    def _process_deletion_queue(self):
        """处理延迟删除队列"""
        try:
            current_time = datetime.now()
            tasks_to_process: List[DeletionTask] = []

            with deletion_queue_lock:
                for task in self.deletion_queue:
                    if not task.processed:
                        elapsed = (current_time - task.timestamp).total_seconds()
                        if elapsed >= self._delay_seconds:
                            tasks_to_process.append(task)

            for task in tasks_to_process:
                try:
                    self._execute_delayed_deletion(task)
                except Exception as e:
                    logger.error(f"处理延迟删除任务失败：{task.file_path} - {e}")

            with deletion_queue_lock:
                self.deletion_queue = [t for t in self.deletion_queue if not t.processed]

                if self.deletion_queue:
                    next_task_time = min(
                        (t.timestamp.timestamp() + self._delay_seconds)
                        for t in self.deletion_queue
                        if not t.processed
                    )
                    wait_time = max(1, next_task_time - current_time.timestamp())
                    logger.debug(f"还有 {len(self.deletion_queue)} 个任务待处理，{wait_time:.1f} 秒后重新检查")
                    self._start_deletion_timer(wait_time)
                else:
                    self._deletion_timer = None
                    logger.debug("延迟删除队列已清空，定时器停止")
        except Exception as e:
            logger.error(f"处理延迟删除队列失败：{str(e)} - {traceback.format_exc()}")
            with deletion_queue_lock:
                self._deletion_timer = None

    def _execute_delayed_deletion(self, task: DeletionTask):
        """执行延迟删除任务：先校验再执行"""
        try:
            # 文件已重新创建：仅当仍是原文件实体（同 dev/inode）时才视为误删/重整并跳过；
            # 若同路径被不同 inode 的文件占用，说明旧文件实体确实已删除，继续清理
            if task.file_path.exists():
                try:
                    stat_info = task.file_path.stat()
                except OSError:
                    stat_info = None
                if stat_info is not None and (
                    stat_info.st_dev == task.deleted_dev and stat_info.st_ino == task.deleted_inode
                ):
                    logger.info(f"文件 {task.file_path} 已重新创建为原文件实体，跳过删除操作")
                    return
                # 路径被不同 inode 的新文件占用：旧实体确实已删除，
                # 但路径上的新文件不能误伤，只清理旧实体的剩余硬链接
                logger.info(f"路径 {task.file_path} 已被其他文件实体占用，仅清理旧实体硬链接")
                self._execute_deletion(task.file_path, task.deleted_dev, task.deleted_inode, skip_path_effects=True)
                return

            # 检查延迟期间是否出现“删除事件时并不存在”的同 inode 新路径
            # （重新整理/重命名产生的硬链接）：仅删除后新增的路径判定为重整理，
            # 删除前已存在的正常硬链接不受影响
            with state_lock:
                known_paths = set(task.known_paths or [])
                for path, file_info in self.file_state.items():
                    if self._same_file_identity(file_info, task.deleted_dev, task.deleted_inode) and path != str(task.file_path):
                        if path not in known_paths:
                            logger.info(f"检测到删除后新增的同文件实体路径 {path}，可能是重新硬链接，跳过硬链接删除")
                            # 只清理旧路径同名刮削文件，不删除新硬链接/转移记录/种子
                            self.delete_scrap_infos(task.file_path)
                            return

            # 执行删除
            self._execute_deletion(task.file_path, task.deleted_dev, task.deleted_inode)
        except Exception as e:
            logger.error(f"执行延迟删除任务失败：{str(e)} - {traceback.format_exc()}")
        finally:
            task.processed = True

    # -----------------------------------------------------------
    # 文件工具
    # -----------------------------------------------------------
    @staticmethod
    def _same_file_identity(file_info: FileInfo, dev: int, inode: int) -> bool:
        """判断是否为同一文件实体（硬链接）"""
        return file_info.dev == dev and file_info.inode == inode

    @staticmethod
    def _normalize_config_path(config_path: str) -> str:
        """规范化配置目录路径（保留不存在路径的可比较形式）"""
        return os.path.normcase(os.path.normpath(str(Path(config_path).expanduser())))

    @classmethod
    def _is_same_or_child_path(cls, path: Path, base_path: str) -> bool:
        """判断 path 是否等于 base_path 或在 base_path 之下（避免子串误匹配）"""
        if not base_path:
            return False
        normalized_path = cls._normalize_config_path(str(path))
        normalized_base = cls._normalize_config_path(base_path)
        try:
            return os.path.commonpath([normalized_path, normalized_base]) == normalized_base
        except ValueError:
            return False

    def __is_excluded(self, file_path: Path) -> bool:
        """是否命中不删除目录"""
        for exclude_dir in self.exclude_dirs.split("\n"):
            exclude_dir = exclude_dir.strip()
            if exclude_dir and self._is_same_or_child_path(file_path, exclude_dir):
                return True
        return False

    def __is_keyword_excluded(self, file_path: Path) -> bool:
        """路径包含过滤关键字的文件不处理（与事件过滤语义一致）"""
        if not self.exclude_keywords:
            return False
        for keyword in self.exclude_keywords.split("\n"):
            if keyword and keyword in str(file_path):
                logger.debug(f"文件 {file_path} 命中过滤关键字 {keyword}，不处理")
                return True
        return False

    def _unlink_tracked_file(self, file: Path, state_key: str, action: str) -> bool:
        """
        删除 file_state 中记录的硬链接文件。
        若文件已被外部删除（FileNotFoundError），清理过期记录后继续，不中断批次。
        """
        if self.__is_excluded(file):
            logger.debug(f"文件 {file} 在不删除目录中，跳过")
            return False
        if self.__is_keyword_excluded(file):
            logger.debug(f"文件 {file} 命中过滤关键字，跳过")
            return False
        try:
            logger.info(f"{action}硬链接文件：{state_key}")
            file.unlink()
        except FileNotFoundError:
            logger.warning(f"硬链接文件已不存在，清理过期监控记录：{state_key}")
            self.file_state.pop(state_key, None)
            return False
        except OSError as e:
            logger.error(f"删除硬链接文件失败：{state_key} - {e}")
            return False
        self.file_state.pop(state_key, None)
        return True

    # -----------------------------------------------------------
    # 刮削文件清理
    # -----------------------------------------------------------
    @staticmethod
    def _parse_custom_scrap_extensions(custom_extensions: str) -> List[str]:
        """解析自定义刮削文件后缀，支持换行、逗号、中文逗号分隔"""
        if not custom_extensions:
            return []
        extensions: List[str] = []
        for item in custom_extensions.replace("，", ",").replace("\n", ",").split(","):
            extension = item.strip().lower()
            if not extension:
                continue
            if not extension.startswith(".") and not extension.startswith("-"):
                extension = f".{extension}"
            if extension not in extensions:
                extensions.append(extension)
        return extensions

    def _scrap_extensions(self) -> List[str]:
        """内置 + 自定义刮削后缀"""
        extensions = list(self.SCRAP_EXTENSIONS)
        for extension in self._custom_scrap_extensions:
            if extension not in extensions:
                extensions.append(extension)
        return extensions

    def _is_scrap_file(self, path: Path) -> bool:
        """判断文件是否为刮削文件"""
        name = path.name.lower()
        return any(name.endswith(extension) for extension in self._scrap_extensions())

    def scrape_files_left(self, path: Path) -> bool:
        """检查目录是否只包含刮削文件（及刮削目录）"""
        try:
            for file in path.iterdir():
                if file.is_dir():
                    if file.suffix.lower() not in self.SCRAP_DIR_SUFFIXES:
                        return False
                    continue
                if not self._is_scrap_file(file):
                    return False
            return True
        except OSError:
            return False

    @staticmethod
    def _same_media_scrap_name(file: Path, media_stem: str) -> bool:
        """刮削文件是否属于该媒体：名称以媒体名为前缀且紧跟非字母数字边界，
        避免 S01E01 误匹配 S01E010 等其他媒体的文件"""
        name = file.name
        if not name.startswith(media_stem):
            return False
        if len(name) == len(media_stem):
            return True
        return not name[len(media_stem)].isalnum()

    @classmethod
    def _belongs_to_other_media(cls, scrap_name: str, media_stem: str, other_media_stems: set) -> bool:
        """判断刮削文件名是否属于同目录中的其他媒体文件。

        仅当其他媒体名比当前媒体名更长、且刮削文件名以该媒体名为前缀并紧跟
        非字母数字边界时，才认为刮削文件属于其他媒体（如 Film-2.nfo 属于
        Film-2 而非 Film），避免误删其他媒体关联的元数据。
        """
        for stem in other_media_stems:
            # 同 stem 的其他媒体文件：刮削文件为两者共享，删除当前媒体时不能清理
            if stem == media_stem:
                return True
            if len(stem) <= len(media_stem):
                continue
            if not scrap_name.startswith(stem):
                continue
            if len(scrap_name) == len(stem):
                continue
            if not scrap_name[len(stem)].isalnum():
                return True
        return False

    def delete_scrap_infos(self, path: Path):
        """清理与 path 相关的刮削文件（同名前缀 + 刮削目录）"""
        if not self._delete_scrap_infos:
            return
        if self.__is_keyword_excluded(path) or self.__is_excluded(path):
            return
        if not os.path.exists(path.parent):
            return
        try:
            if not self._is_scrap_file(path):
                name_prefix = path.stem
                # 同目录中其他媒体文件名（非刮削文件），用于排除属于其他媒体的刮削文件
                other_media_stems = {
                    f.stem
                    for f in path.parent.iterdir()
                    if not f.is_dir() and f.name != path.name and not self._is_scrap_file(f)
                }
                for file in path.parent.iterdir():
                    if not self._same_media_scrap_name(file, name_prefix):
                        continue
                    if self.__is_keyword_excluded(file) or self.__is_excluded(file):
                        continue
                    if self._belongs_to_other_media(file.name, name_prefix, other_media_stems):
                        logger.debug(f"刮削文件 {file} 属于同目录其他媒体，跳过")
                        continue
                    if file.is_dir() and file.suffix.lower() in self.SCRAP_DIR_SUFFIXES:
                        shutil.rmtree(file)
                        logger.info(f"删除刮削目录：{file}")
                    elif self._is_scrap_file(file):
                        file.unlink()
                        logger.info(f"删除刮削文件：{file}")
        except Exception as e:
            logger.error(f"清理刮削文件发生错误：{str(e)}")
        self.delete_empty_folders(path)

    def delete_empty_folders(self, path: Path):
        """从指定路径向上逐级删除空目录，直到遇到非空目录或监控目录为止"""
        monitor_dirs = [d.strip() for d in self.monitor_dirs.split("\n") if d.strip()]
        normalized_roots = [self._normalize_config_path(d) for d in monitor_dirs]
        while True:
            parent_path = path.parent
            if self.__is_excluded(parent_path) or self.__is_keyword_excluded(parent_path):
                break
            if not os.path.exists(parent_path):
                break
            # 规范化后再比较，避免配置带尾斜杠时误删监控根目录并继续向上清理
            if self._normalize_config_path(str(parent_path)) in normalized_roots:
                break

            # 目录只包含刮削文件时，清空整个目录
            try:
                if self.scrape_files_left(parent_path):
                    for file in parent_path.iterdir():
                        if self.__is_keyword_excluded(file) or self.__is_excluded(file):
                            continue
                        if file.is_dir():
                            shutil.rmtree(file)
                            logger.info(f"删除刮削目录：{file}")
                        else:
                            file.unlink()
                            logger.info(f"删除刮削文件：{file}")
            except Exception as e:
                logger.error(f"清理刮削文件发生错误：{str(e)}")

            try:
                if not os.listdir(parent_path):
                    os.rmdir(parent_path)
                    logger.info(f"清理空目录：{parent_path}")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="📁 目录清理",
                            text=f"🗑️ 清理空目录：{parent_path}",
                        )
                else:
                    break
            except Exception as e:
                logger.error(f"清理空目录发生错误：{str(e)}")

            path = parent_path

    # -----------------------------------------------------------
    # 转移记录清理
    # -----------------------------------------------------------
    def delete_history(self, path: str):
        """清理 path 相关的转移记录"""
        if not self._delete_history or not self._transferhistory:
            return
        try:
            transfer_history = self._transferhistory.get_by_dest(path)
            if not transfer_history:
                transfer_history = self._transferhistory.get_by_src(path)
            if transfer_history:
                self._transferhistory.delete(transfer_history.id)
                logger.info(f"删除转移记录：{transfer_history.id} - {path}")
        except Exception as e:
            logger.error(f"删除转移记录失败：{path} - {e}")

    # -----------------------------------------------------------
    # 配置页面
    # -----------------------------------------------------------
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        插件配置页面（Vuetify JSON 配置）
        """
        return [
            {
                "component": "VForm",
                "content": [
                    # 总体说明
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "title": "🧹 源文件联动清理插件",
                                            "text": "监控源文件（下载目录）中的文件删除事件，当源文件被删除后，自动联动删除媒体库中对应的硬链接文件、刮削文件（元数据、图片、字幕）与转移记录。建议开启延迟删除，防止媒体重整理导致误删。",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # 功能开关
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "notify", "label": "发送通知"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "delete_scrap_infos", "label": "清理刮削文件"},
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "delete_torrents", "label": "联动删除种子"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "delete_history", "label": "删除转移记录"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "delayed_deletion", "label": "启用延迟删除"},
                                    }
                                ],
                            },
                        ],
                    },
                    # 监控目录配置
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "title": "🔗 监控目录配置",
                                            "text": "源目录和硬链接目录都需要添加到监控目录中；如需实现删除硬链接时不删除源文件，可把源文件目录配置到不删除目录中。",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "monitor_dirs",
                                            "label": "监控目录",
                                            "rows": 4,
                                            "placeholder": "每行一个目录\n/downloads\n/media/library",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_dirs",
                                            "label": "不删除目录",
                                            "rows": 4,
                                            "placeholder": "每行一个目录，命中后不会删除其中的文件",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_keywords",
                                            "label": "过滤关键字",
                                            "rows": 3,
                                            "placeholder": "每行一个关键字，路径包含关键字的文件不处理",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "delay_seconds",
                                            "label": "延迟删除时间（秒）",
                                            "type": "number",
                                            "hint": "10 ~ 86400 秒，默认 30 秒",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "custom_scrap_extensions",
                                            "label": "自定义刮削文件后缀",
                                            "rows": 2,
                                            "placeholder": "每行或逗号分隔一个后缀，例如：.txt\n.json\n-mediainfo.json",
                                            "hint": "开启清理刮削文件后生效，会与内置 .nfo/.jpg/.srt 等后缀一起联动清理",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # 使用说明
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "text": "联动删除种子需安装插件[下载器助手]并打开监听源文件事件。清理刮削文件功能会删除相关的.nfo、.jpg等元数据文件，请谨慎开启。",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": False,
            "delete_scrap_infos": False,
            "delete_torrents": False,
            "delete_history": False,
            "delayed_deletion": True,
            "delay_seconds": 30,
            "monitor_dirs": "",
            "exclude_dirs": "",
            "exclude_keywords": "",
            "custom_scrap_extensions": "",
        }

