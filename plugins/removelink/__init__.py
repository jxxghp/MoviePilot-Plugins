import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Any
import os
import re

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Notification, NotificationType
import time


class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控处理
    """

    def __init__(self, monpath: str, sync: Any, **kwargs):
        super(FileMonitorHandler, self).__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        logger.info("监测到新增文件：%s" % event.src_path)
        if self.sync._exclude_keywords:
            for keyword in self.sync._exclude_keywords.split("\n"):
                if keyword and re.findall(keyword, event.src_path):
                    logger.info(f"{event.src_path} 命中过滤关键字 {keyword}，不处理")
                    print(f"{event.src_path} 命中过滤关键字 {keyword}，不处理")
                    return
        new_file = Path(event.src_path)
        try:
            self.sync._state_set.add((Path(event.src_path), new_file.stat().st_ino))
        except Exception as e:
            logger.error("文件丢失：%s" % event.src_path)

    def on_deleted(self, event):
        if Path(event.src_path) in self.sync._ignored_files:
            self.sync._ignored_files.remove(Path(event.src_path))
            return
        logger.info("监测到删除：%s" % event.src_path)
        # 命中过滤关键字不处理
        if self.sync._exclude_keywords:
            for keyword in self.sync._exclude_keywords.split("\n"):
                if keyword and re.findall(keyword, event.src_path):
                    logger.info(f"{event.src_path} 命中过滤关键字 {keyword}，不处理")
                    print(f"{event.src_path} 命中过滤关键字 {keyword}，不处理")
                    return
        self.sync.event_handler()


def updateState(monitor_dirs: List[str]):
    """
    更新监控目录的文件列表
    """
    start_time = time.time()  # 记录开始时间
    state_set = set()
    for mon_path in monitor_dirs:
        for root, dirs, files in os.walk(mon_path):
            for file in files:
                file = Path(root) / file
                if not file.exists():
                    continue
                state_set.add((file, file.stat().st_ino))
    end_time = time.time()  # 记录结束时间
    elapsed_time = end_time - start_time  # 计算耗时
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
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "DzAvril"
    # 作者主页
    author_url = "https://github.com/DzAvril"
    # 插件配置项ID前缀
    plugin_config_prefix = "linkdeleted_"
    # 加载顺序
    plugin_order = 27
    # 可使用的用户级别
    auth_level = 1

    # preivate property
    _monitor_dirs = ""
    _exclude_keywords = ""
    _enabled = False
    _notify = False
    _observer = []
    _state_set = set()
    _ignored_files = set()

    def init_plugin(self, config: dict = None):
        logger.info(f"Hello, RemoveLink! config {config}")
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._monitor_dirs = config.get("monitor_dirs")
            self._exclude_keywords = config.get("exclude_keywords") or ""
        self.__update_config()
        # 停止现有任务
        self.stop_service()
        if self._enabled:
            # 读取目录配置
            monitor_dirs = self._monitor_dirs.split("\n")
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
            self._state_set = updateState(monitor_dirs)

    def __update_config(self):
        """
        更新配置
        """
        self.update_config(
            {
                "enabled": self._enabled,
                "notify": self._notify,
                "monitor_dirs": self._monitor_dirs,
                "exclude_keywords": self._exclude_keywords,
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "monitor_dirs",
                                            "label": "监控目录",
                                            "rows": 5,
                                            "placeholder": "每一行一个目录",
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
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '监控目录如有多个请换行，源目录和硬链接目录都需要添加到监控目录中。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
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

    def event_handler(self):
        """
        处理删除事件
        """
        current_set = updateState(self._monitor_dirs.split("\n"))
        deleted_set = self._state_set - current_set
        deleted_inode = [x[1] for x in deleted_set]
        try:
            # 在current_set中查找与deleted_inode有相同inode的文件并删除
            for path, inode in current_set:
                if inode in deleted_inode:
                    file = Path(path)
                    self._ignored_files.add(file)
                    file.unlink()
                    logger.info(f"删除硬链接文件：{path}")
                    if self._notify:
                        for d_path, d_inode in deleted_set:
                            if d_inode == inode:
                                self.chain.post_message(
                                    Notification(
                                        mtype=NotificationType.SiteMessage,
                                        title=f"【清理硬链接】",
                                        text=f"监控到删除源文件：\n"
                                        f"[{d_path}]\n"
                                        f"同步删除硬链接文件：\n"
                                        f"[{path}]",
                                    )
                                )
        except Exception as e:
            logger.error("目录监控发生错误：%s - %s" % (str(e), traceback.format_exc()))

        self._state_set = updateState(self._monitor_dirs.split("\n"))
