import os
import threading
import time
import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Notification, NotificationType
from app.utils.timer import TimerUtils

state_lock = threading.Lock()


class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控处理
    """

    def __init__(self, monpath: str, sync: Any, **kwargs):
        super(FileMonitorHandler, self).__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        if event.is_directory:
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
            self.sync.state_set[str(file_path)] = file_path.stat().st_ino

    def on_deleted(self, event):
        if event.is_directory:
            return
        file_path = Path(event.src_path)
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


def updateState(monitor_dirs: List[str]):
    """
    更新监控目录的文件列表
    """
    # 记录开始时间
    start_time = time.time()
    state_set = {}
    for mon_path in monitor_dirs:
        for root, dirs, files in os.walk(mon_path):
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

    return state_set


class RemoveLink(_PluginBase):
    # 插件名称
    plugin_name = "清理硬链接"
    # 插件描述
    plugin_desc = "监控目录内文件被删除时，同步删除监控目录内所有和它硬链接的文件"
    # 插件图标
    plugin_icon = "Ombi_A.png"
    # 插件版本
    plugin_version = "1.8"
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
    _observer = []
    # 监控目录的文件列表
    state_set: Dict[str, int] = {}

    def init_plugin(self, config: dict = None):
        logger.info(f"Hello, RemoveLink! config {config}")
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self.monitor_dirs = config.get("monitor_dirs")
            self.exclude_dirs = config.get("exclude_dirs") or ""
            self.exclude_keywords = config.get("exclude_keywords") or ""

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
                    observer = Observer(timeout=10)
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
                    self.systemmessage.put(f"{mon_path} 启动目录监控失败：{err_msg}")
            # 更新监控集合
            with state_lock:
                self.state_set = updateState(monitor_dirs)

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

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled:
            # 随机时间
            triggers = TimerUtils.random_scheduler(
                num_executions=1,
                begin_hour=0,
                end_hour=1,
                min_interval=1,
                max_interval=60,
            )
            ret_jobs = []
            for trigger in triggers:
                ret_jobs.append(
                    {
                        "id": f"RemoveLink|{trigger.hour}:{trigger.minute}",
                        "name": "清理空文件夹",
                        "trigger": "cron",
                        "func": self.delete_empty_folders,
                        "kwargs": {"hour": trigger.hour, "minute": trigger.minute},
                    }
                )
            return ret_jobs
        return []

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
                                            "text": "监控目录如有多个需换行，源目录和硬链接目录都需要添加到监控目录中；如需实现删除硬链接时不删除源文件，可把源文件目录配置到不删除目录中。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
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

    def delete_empty_folders(self):
        """
        删除空目录
        """
        for mon_path in self.monitor_dirs.split("\n"):
            for subdir, dirs, files in os.walk(mon_path, topdown=False):
                for dir in dirs:
                    dir_path = os.path.join(subdir, dir)
                    # 检查当前目录是否为空
                    if not os.listdir(dir_path) and not self.__is_excluded(dir_path):
                        os.rmdir(dir_path)
                        logger.info(f"删除空目录：{dir_path}")
                        if self._notify:
                            self.post_message(
                                mtype=NotificationType.SiteMessage,
                                title=f"【清理硬链接】",
                                text=f"清理空文件夹：[{dir_path}]\n",
                            )

    def handle_deleted(self, file_path: Path):
        """
        处理删除事件
        """
        # 删除的文件对应的监控信息
        with state_lock:
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
