import os
import threading
import time
import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from watchfiles import Change, watch
from app.db.transferhistory_oper import TransferHistoryOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.core.event import eventmanager
from app.schemas.types import EventType

state_lock = threading.Lock()


class WatchfilesEvent:
    """
    watchfiles 目录监控事件。
    """

    def __init__(self, src_path: str, is_directory: bool):
        """
        初始化目录监控事件。
        :param src_path: 事件路径
        :param is_directory: 是否为目录
        """
        self.src_path = src_path
        self.dest_path = src_path
        self.is_directory = is_directory


class WatchfilesObserver:
    """
    基于 watchfiles 的目录监控适配器。
    """

    def __init__(self, timeout: int = 10, force_polling: Optional[bool] = None):
        """
        初始化目录监控适配器。
        :param timeout: 兼容模式轮询间隔秒数
        :param force_polling: 是否强制轮询，None 表示自动选择平台原生模式
        """
        self._force_polling = force_polling
        self._poll_delay_ms = max(int(timeout * 1000), 300)
        self._stop_event = threading.Event()
        self._thread = None
        self._handler = None
        self._path = None
        self._recursive = True

    def schedule(self, handler: Any, path: str, recursive: bool = True):
        """
        设置监控处理器和路径。
        :param handler: 事件处理器
        :param path: 监控路径
        :param recursive: 是否递归监控
        """
        self._handler = handler
        self._path = path
        self._recursive = recursive

    def start(self):
        """
        启动目录监控线程。
        """
        if not self._handler or not self._path:
            raise ValueError("目录监控处理器或路径未设置")
        if not Path(self._path).exists():
            raise FileNotFoundError(f"监控目录不存在：{self._path}")
        if not Path(self._path).is_dir():
            raise NotADirectoryError(f"监控路径不是目录：{self._path}")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """
        停止目录监控线程。
        """
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None):
        """
        等待目录监控线程退出。
        :param timeout: 最大等待秒数
        """
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self):
        """
        运行 watchfiles 监控循环，快速模式异常时回退到轮询。
        """
        try:
            self._run_watch(force_polling=self._force_polling)
        except Exception as err:
            if self._stop_event.is_set():
                return
            if self._force_polling is True:
                logger.error(f"{self._path} 目录监控发生错误：{err}")
                logger.debug(traceback.format_exc())
                return
            logger.warn(f"{self._path} 快速模式监控失败，自动切换到兼容模式：{err}")
            try:
                self._run_watch(force_polling=True)
            except Exception as fallback_err:
                if not self._stop_event.is_set():
                    logger.error(f"{self._path} 兼容模式监控失败：{fallback_err}")
                    logger.debug(traceback.format_exc())

    def _run_watch(self, force_polling: Optional[bool]):
        """
        执行 watchfiles 监控。
        :param force_polling: 是否强制轮询
        """
        for changes in watch(
                self._path,
                stop_event=self._stop_event,
                rust_timeout=1000,
                yield_on_timeout=True,
                force_polling=force_polling,
                poll_delay_ms=self._poll_delay_ms,
                recursive=self._recursive,
                ignore_permission_denied=True):
            if self._stop_event.is_set():
                break
            if not changes:
                continue
            if hasattr(self._handler, "dispatch_changes"):
                self._handler.dispatch_changes(changes=changes)
            else:
                for change_type, event_path in sorted(changes, key=lambda item: item[1]):
                    self._handler.dispatch(change_type=change_type, event_path=event_path)


class FileMonitorHandler:
    """
    目录监控处理。
    """

    def __init__(self, monpath: str, sync: Any):
        """
        初始化目录监控处理器。
        :param monpath: 监控目录
        :param sync: 插件实例
        """
        self._watch_path = monpath
        self.sync = sync

    def dispatch_changes(self, changes: set[tuple[Change, str]]):
        """
        批量分发 watchfiles 事件，避免同批次移动事件被误判为删除。
        :param changes: watchfiles 事件集合
        """
        sorted_changes = sorted(changes, key=lambda item: item[1])
        added_inodes = set()
        for change_type, event_path in sorted_changes:
            if change_type not in {Change.added, Change.modified}:
                continue
            self.dispatch(change_type=change_type, event_path=event_path)
            inode = self.sync.state_set.get(str(Path(event_path)))
            if inode:
                added_inodes.add(inode)
        for change_type, event_path in sorted_changes:
            if change_type != Change.deleted:
                continue
            file_path = Path(event_path)
            deleted_inode = self.sync.state_set.get(str(file_path))
            if deleted_inode and deleted_inode in added_inodes:
                logger.info(f"监测到文件移动：{file_path}，跳过删除联动")
                with state_lock:
                    self.sync.state_set.pop(str(file_path), None)
                continue
            self.dispatch(change_type=change_type, event_path=event_path)

    def dispatch(self, change_type: Change, event_path: str):
        """
        分发 watchfiles 事件。
        :param change_type: 事件类型
        :param event_path: 事件路径
        """
        if change_type in {Change.added, Change.modified}:
            path = Path(event_path)
            if not path.exists():
                return
            event = WatchfilesEvent(src_path=event_path, is_directory=path.is_dir())
            self.on_created(event)
        elif change_type == Change.deleted:
            event = WatchfilesEvent(
                src_path=event_path,
                is_directory=self.sync.is_known_directory(event_path)
            )
            self.on_deleted(event)

    def on_created(self, event):
        """
        处理新增或修改事件，维护文件 inode 状态。
        :param event: 目录监控事件
        """
        if event.is_directory:
            self.sync.dir_state_set.add(str(Path(event.src_path)))
            return
        file_path = Path(event.src_path)
        if file_path.suffix in [".!qB", ".part", ".mp"]:
            return
        logger.info(f"监测到新增文件：{file_path}")
        if self.sync.exclude_keywords:
            for keyword in self.sync.exclude_keywords.split("\n"):
                if keyword and keyword in str(file_path):
                    logger.info(f"{file_path} 命中过滤关键字 {keyword}，不处理")
                    return
        # 新增文件记录
        with state_lock:
            try:
                self.sync.state_set[str(file_path)] = file_path.stat().st_ino
            except Exception as e:
                logger.error(f"新增文件记录失败：{str(e)}")

    def on_moved(self, event):
        """
        处理移动事件，兼容旧事件调用语义。
        :param event: 目录监控事件
        """
        if event.is_directory:
            return
        file_path = Path(event.dest_path)
        if file_path.suffix in [".!qB", ".part", ".mp"]:
            return
        logger.info(f"监测到新增文件：{file_path}")
        if self.sync.exclude_keywords:
            for keyword in self.sync.exclude_keywords.split("\n"):
                if keyword and keyword in str(file_path):
                    logger.info(f"{file_path} 命中过滤关键字 {keyword}，不处理")
                    return
        # 新增文件记录
        with state_lock:
            self.sync.state_set[str(file_path)] = file_path.stat().st_ino

    def on_deleted(self, event):
        """
        处理删除事件。
        :param event: 目录监控事件
        """
        file_path = Path(event.src_path)
        if event.is_directory:
            self.sync.dir_state_set.discard(str(file_path))
            # 单独处理文件夹删除触发删除种子
            if self.sync._delete_torrents:
                # 发送事件
                logger.info(f"监测到删除文件夹：{file_path}")
                eventmanager.send_event(
                    EventType.DownloadFileDeleted, {"src": str(file_path)}
                )
            return
        if file_path.suffix in [".!qB", ".part", ".mp"]:
            return
        logger.info(f"监测到删除文件：{file_path}")
        # 命中过滤关键字不处理
        if self.sync.exclude_keywords:
            for keyword in self.sync.exclude_keywords.split("\n"):
                if keyword and keyword in str(file_path):
                    logger.info(f"{file_path} 命中过滤关键字 {keyword}，不处理")
                    return
        # 删除硬链接文件
        self.sync.handle_deleted(file_path)


def updateState(monitor_dirs: List[str]) -> Tuple[Dict[str, int], set[str]]:
    """
    更新监控目录的文件列表
    """
    # 记录开始时间
    start_time = time.time()
    state_set = {}
    dir_state_set = set()
    for mon_path in monitor_dirs:
        for root, dirs, files in os.walk(mon_path):
            dir_state_set.add(str(Path(root)))
            for directory in dirs:
                dir_state_set.add(str(Path(root) / directory))
            for file in files:
                file = Path(root) / file
                if not file.exists():
                    continue
                # 记录文件inode
                state_set[str(file)] = file.stat().st_ino
    # 记录结束时间
    end_time = time.time()
    # 计算耗时
    elapsed_time = end_time - start_time
    logger.info(f"更新文件列表完成，共计{len(state_set)}个文件，耗时：{elapsed_time}秒")

    return state_set, dir_state_set


class RemoveLink(_PluginBase):
    # 插件名称
    plugin_name = "清理硬链接"
    # 插件描述
    plugin_desc = "监控目录内文件被删除时，同步删除监控目录内所有和它硬链接的文件"
    # 插件图标
    plugin_icon = "Ombi_A.png"
    # 插件版本
    plugin_version = "2.3"
    # 插件作者
    plugin_author = "DzAvril"
    # 作者主页
    author_url = "https://github.com/DzAvril"
    # 插件配置项ID前缀
    plugin_config_prefix = "linkdeleted_"
    # 加载顺序
    plugin_order = 0
    # 可使用的用户级别
    auth_level = 1

    # preivate property
    monitor_dirs = ""
    exclude_dirs = ""
    exclude_keywords = ""
    _enabled = False
    _notify = False
    _delete_scrap_infos = False
    _delete_torrents = False
    _delete_history = False
    _observer = []
    # 监控目录的文件列表
    state_set: Dict[str, int] = {}
    # 监控目录的目录列表，用于删除事件识别目录
    dir_state_set: set[str] = set()

    def init_plugin(self, config: dict = None):
        logger.info(f"Hello, RemoveLink! config {config}")
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self.monitor_dirs = config.get("monitor_dirs")
            self.exclude_dirs = config.get("exclude_dirs") or ""
            self.exclude_keywords = config.get("exclude_keywords") or ""
            self._delete_scrap_infos = config.get("delete_scrap_infos")
            self._delete_torrents = config.get("delete_torrents")
            self._delete_history = config.get("delete_history")

        # 停止现有任务
        self.stop_service()

        if self._enabled:
            # 读取目录配置
            monitor_dirs = self.monitor_dirs.split("\n")
            logger.info(f"监控目录：{monitor_dirs}")
            if not monitor_dirs:
                return
            for mon_path in monitor_dirs:
                # 格式源目录:目的目录
                if not mon_path:
                    continue
                try:
                    observer = WatchfilesObserver(timeout=10, force_polling=None)
                    self._observer.append(observer)
                    observer.schedule(
                        FileMonitorHandler(mon_path, self), mon_path, recursive=True
                    )
                    observer.daemon = True
                    observer.start()
                    logger.info(f"{mon_path} 的目录监控服务启动")
                except Exception as e:
                    err_msg = str(e)
                    logger.error(f"{mon_path} 启动目录监控失败：{err_msg}")
                    self.systemmessage.put(f"{mon_path} 启动目录监控失败：{err_msg}", title="清理硬链接")
            # 更新监控集合
            with state_lock:
                self.state_set, self.dir_state_set = updateState(monitor_dirs)

    def __update_config(self):
        """
        更新配置
        """
        self.update_config(
            {
                "enabled": self._enabled,
                "notify": self._notify,
                "monitor_dirs": self.monitor_dirs,
                "exclude_keywords": self.exclude_keywords,
            }
        )

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_scrap_infos",
                                            "label": "清理刮削文件(beta)",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_torrents",
                                            "label": "联动删除种子",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_history",
                                            "label": "删除历史记录",
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
                                            "model": "monitor_dirs",
                                            "label": "监控目录",
                                            "rows": 5,
                                            "placeholder": "源目录及硬链接目录均需加入监控，每一行一个目录",
                                        },
                                    }
                                ],
                            }
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
                                            "model": "exclude_dirs",
                                            "label": "不删除目录",
                                            "rows": 5,
                                            "placeholder": "该目录下的文件不会被动删除，一行一个目录",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_keywords",
                                            "label": "排除关键词",
                                            "rows": 2,
                                            "placeholder": "每一行一个关键词",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "联动删除种子需安装插件[下载器助手]并打开监听源文件事件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "清理刮削文件为测试功能，请谨慎开启。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "监控目录如有多个需换行，源目录和硬链接目录都需要添加到监控目录中；如需实现删除硬链接时不删除源文件，可把源文件目录配置到不删除目录中。",
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
            "monitor_dirs": "",
            "exclude_keywords": "",
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    print(str(e))
                    logger.error(f"停止目录监控失败：{str(e)}")
        self._observer = []

    def __is_excluded(self, file_path: Path) -> bool:
        """
        是否排除目录
        """
        for exclude_dir in self.exclude_dirs.split("\n"):
            if exclude_dir and exclude_dir in str(file_path):
                return True
        return False

    def is_known_directory(self, event_path: str) -> bool:
        """
        判断删除事件路径是否为已知目录。
        :param event_path: 事件路径
        """
        return str(Path(event_path)) in self.dir_state_set

    @staticmethod
    def scrape_files_left(path):
        """
        检查path目录是否只包含刮削文件
        """
        # 检查path下是否有目录
        for dir_path in os.listdir(path):
            if os.path.isdir(os.path.join(path, dir_path)):
                return False

        # 检查path下是否有非刮削文件
        for file in path.iterdir():
            if not file.suffix.lower() in [
                ".jpg",
                ".nfo",
            ]:
                return False
        return True

    def delete_scrap_infos(self, path):
        """
        清理path相关的刮削文件
        """
        if not self._delete_scrap_infos:
            return
        # 文件所在目录已被删除则退出
        if not os.path.exists(path.parent):
            return
        try:
            if not path.suffix.lower() in [
                ".jpg",
                ".nfo",
            ]:
                # 清理与path相关的刮削文件
                name_prefix = path.stem
                for file in path.parent.iterdir():
                    if file.name.startswith(name_prefix):
                        file.unlink()
                        logger.info(f"删除刮削文件：{file}")
        except Exception as e:
            logger.error(f"清理刮削文件发生错误：{str(e)}.")
        # 清理空目录
        self.delete_empty_folders(path)

    def delete_history(self, path):
        """
        清理path相关的历史记录
        """
        if not self._delete_history:
            return
        # 查找历史记录
        _transferhistory = TransferHistoryOper()
        transfer_history = _transferhistory.get_by_src(path)
        if transfer_history:
            # 删除历史记录
            _transferhistory.delete(transfer_history.id)
            logger.info(f"删除历史记录：{transfer_history.id}")

    def delete_empty_folders(self, path):
        """
        从指定路径开始，逐级向上层目录检测并删除空目录，直到遇到非空目录或到达指定监控目录为止
        """
        # logger.info(f"清理空目录: {path}")
        while True:
            parent_path = path.parent
            if self.__is_excluded(parent_path):
                break
            # parent_path如已被删除则退出检查
            if not os.path.exists(parent_path):
                break
            # 如果当前路径等于监控目录之一，停止向上检查
            if parent_path in self.monitor_dirs.split("\n"):
                break

            # 若目录下只剩刮削文件，则清空文件夹
            try:
                if self.scrape_files_left(parent_path):
                    # 清除目录下所有文件
                    for file in parent_path.iterdir():
                        file.unlink()
                        logger.info(f"删除刮削文件：{file}")
            except Exception as e:
                logger.error(f"清理刮削文件发生错误：{str(e)}.")

            try:
                if not os.listdir(parent_path):
                    os.rmdir(parent_path)
                    logger.info(f"清理空目录：{parent_path}")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title=f"【清理硬链接】",
                            text=f"清理空文件夹：[{parent_path}]\n",
                        )
                else:
                    break
            except Exception as e:
                logger.error(f"清理空目录发生错误：{str(e)}")

            # 更新路径为父目录，准备下一轮检查
            path = parent_path

    def handle_deleted(self, file_path: Path):
        """
        处理删除事件
        """
        # 删除的文件对应的监控信息
        with state_lock:
            # 清理刮削文件
            self.delete_scrap_infos(file_path)
            if self._delete_torrents:
                # 发送事件
                eventmanager.send_event(
                    EventType.DownloadFileDeleted, {"src": str(file_path)}
                )
            # 删除历史记录
            self.delete_history(str(file_path))
            # 删除的文件inode
            deleted_inode = self.state_set.get(str(file_path))
            if not deleted_inode:
                logger.info(f"文件 {file_path} 未在监控列表中，不处理")
                return
            else:
                self.state_set.pop(str(file_path))
            try:
                # 在current_set中查找与deleted_inode有相同inode的文件并删除
                for path, inode in self.state_set.copy().items():
                    if inode == deleted_inode:
                        file = Path(path)
                        if self.__is_excluded(file):
                            logger.info(f"文件 {file} 在不删除目录中，不处理")
                            continue
                        # 删除硬链接文件
                        logger.info(f"删除硬链接文件：{path}， inode: {inode}")
                        file.unlink()
                        # 清理刮削文件
                        self.delete_scrap_infos(file_path)
                        if self._delete_torrents:
                            # 发送事件
                            eventmanager.send_event(
                                EventType.DownloadFileDeleted, {"src": str(file_path)}
                            )
                        # 删除历史记录
                        self.delete_history(str(file_path))
                        if self._notify:
                            self.post_message(
                                mtype=NotificationType.SiteMessage,
                                title=f"【清理硬链接】",
                                text=f"监控到删除源文件：[{file_path}]\n"
                                     f"同步删除硬链接文件：[{path}]",
                            )
            except Exception as e:
                logger.error(
                    "删除硬链接文件发生错误：%s - %s" % (str(e), traceback.format_exc())
                )
