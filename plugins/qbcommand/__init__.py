from typing import List, Tuple, Dict, Any
from enum import Enum
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import EventType
from apscheduler.triggers.cron import CronTrigger
from app.core.event import eventmanager, Event
import time


class QbCommand(_PluginBase):
    # 插件名称
    plugin_name = "QB远程操作"
    # 插件描述
    plugin_desc = "通过定时任务或交互命令远程操作QB暂停/开始/限速等"
    # 插件图标
    plugin_icon = "Qbittorrent_A.png"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "DzAvril"
    # 作者主页
    author_url = "https://github.com/DzAvril"
    # 插件配置项ID前缀
    plugin_config_prefix = "qbcommand_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _qb = None
    _enabled: bool = False
    _notify: bool = False
    _pause_cron = None
    _resume_cron = None
    _only_pause_once = False
    _only_resume_once = False
    _only_pause_upload = False
    _only_pause_download = False
    _only_pause_checking = False
    _upload_limit = 0
    _enable_upload_limit = False
    _download_limit = 0
    _enable_download_limit = False

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._pause_cron = config.get("pause_cron")
            self._resume_cron = config.get("resume_cron")
            self._only_pause_once = config.get("onlypauseonce")
            self._only_resume_once = config.get("onlyresumeonce")
            self._only_pause_upload = config.get("onlypauseupload")
            self._only_pause_download = config.get("onlypausedownload")
            self._only_pause_checking = config.get("onlypausechecking")
            self._download_limit = config.get("download_limit")
            self._upload_limit = config.get("upload_limit")
            self._enable_download_limit = config.get("enable_download_limit")
            self._enable_upload_limit = config.get("enable_upload_limit")
            self._qb = Qbittorrent()

        if self._only_pause_once or self._only_resume_once:
            if self._only_pause_once and self._only_resume_once:
                logger.warning("只能选择一个: 立即暂停或立即开始所有任务")
            elif self._only_pause_once:
                self.pause_torrent()
            elif self._only_resume_once:
                self.resume_torrent()

            self._only_resume_once = False
            self._only_pause_once = False
            self.update_config(
                {
                    "onlypauseonce": False,
                    "onlyresumeonce": False,
                    "enabled": self._enabled,
                    "notify": self._notify,
                    "pause_cron": self._pause_cron,
                    "resume_cron": self._resume_cron,
                }
            )

        if self._only_pause_upload or self._only_pause_download or self._only_pause_checking:
            if self._only_pause_upload:
                self.pause_torrent(self.TorrentType.UPLOADING)
            if self._only_pause_download:
                self.pause_torrent(self.TorrentType.DOWNLOADING)
            if self._only_pause_checking:
                self.pause_torrent(self.TorrentType.CHECKING)

            self._only_pause_upload = False
            self._only_pause_download = False
            self._only_pause_checking = False
            self.update_config(
                {
                    "onlypauseupload": False,
                    "onlypausedownload": False,
                    "onlypausechecking": False,
                    "enabled": self._enabled,
                    "notify": self._notify,
                    "pause_cron": self._pause_cron,
                    "resume_cron": self._resume_cron,
                }
            )

        self.set_limit(self._upload_limit, self._download_limit)

    def get_state(self) -> bool:
        return self._enabled

    class TorrentType(Enum):
        ALL = 1
        DOWNLOADING = 2
        UPLOADING = 3
        CHECKING = 4

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/pause_torrents",
                "event": EventType.PluginAction,
                "desc": "暂停QB所有任务",
                "category": "QB",
                "data": {"action": "pause_torrents"},
            },
            {
                "cmd": "/pause_upload_torrents",
                "event": EventType.PluginAction,
                "desc": "暂停QB上传任务",
                "category": "QB",
                "data": {"action": "pause_upload_torrents"},
            },
            {
                "cmd": "/pause_download_torrents",
                "event": EventType.PluginAction,
                "desc": "暂停QB下载任务",
                "category": "QB",
                "data": {"action": "pause_download_torrents"},
            },
            {
                "cmd": "/pause_checking_torrents",
                "event": EventType.PluginAction,
                "desc": "暂停QB检查任务",
                "category": "QB",
                "data": {"action": "pause_checking_torrents"},
            },
            {
                "cmd": "/resume_torrents",
                "event": EventType.PluginAction,
                "desc": "开始QB所有任务",
                "category": "QB",
                "data": {"action": "resume_torrents"},
            },
            {
                "cmd": "/qb_status",
                "event": EventType.PluginAction,
                "desc": "QB当前任务状态",
                "category": "QB",
                "data": {"action": "qb_status"},
            },
            {
                "cmd": "/toggle_upload_limit",
                "event": EventType.PluginAction,
                "desc": "QB切换上传限速状态",
                "category": "QB",
                "data": {"action": "toggle_upload_limit"},
            },
            {
                "cmd": "/toggle_download_limit",
                "event": EventType.PluginAction,
                "desc": "QB切换下载限速状态",
                "category": "QB",
                "data": {"action": "toggle_download_limit"},
            },
        ]

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
        if self._enabled and self._pause_cron and self._resume_cron:
            return [
                {
                    "id": "QbPause",
                    "name": "暂停QB所有任务",
                    "trigger": CronTrigger.from_crontab(self._pause_cron),
                    "func": self.pause_torrent,
                    "kwargs": {},
                },
                {
                    "id": "QbResume",
                    "name": "开始QB所有任务",
                    "trigger": CronTrigger.from_crontab(self._resume_cron),
                    "func": self.resume_torrent,
                    "kwargs": {},
                },
            ]
        if self._enabled and self._pause_cron:
            return [
                {
                    "id": "QbPause",
                    "name": "暂停QB所有任务",
                    "trigger": CronTrigger.from_crontab(self._pause_cron),
                    "func": self.pause_torrent,
                    "kwargs": {},
                }
            ]
        if self._enabled and self._resume_cron:
            return [
                {
                    "id": "QbResume",
                    "name": "开始QB所有任务",
                    "trigger": CronTrigger.from_crontab(self._resume_cron),
                    "func": self.resume_torrent,
                    "kwargs": {},
                }
            ]
        return []

    def get_all_torrents(self):
        all_torrents, error = self._qb.get_torrents()
        if error:
            logger.error(f"获取QB种子失败: {error}")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=f"获取QB种子失败，请检查QB配置",
                )
            return []

        if not all_torrents:
            logger.warning("QB没有种子")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=f"QB中没有种子",
                )
            return []
        return all_torrents

    @staticmethod
    def get_torrents_status(torrents):
        downloading_torrents = []
        uploading_torrents = []
        paused_torrents = []
        checking_torrents = []
        error_torrents = []
        for torrent in torrents:
            if torrent.state_enum.is_uploading and not torrent.state_enum.is_paused:
                uploading_torrents.append(torrent.get("hash"))
            elif (
                torrent.state_enum.is_downloading
                and not torrent.state_enum.is_paused
                and not torrent.state_enum.is_checking
            ):
                downloading_torrents.append(torrent.get("hash"))
            elif torrent.state_enum.is_checking:
                checking_torrents.append(torrent.get("hash"))
            elif torrent.state_enum.is_paused:
                paused_torrents.append(torrent.get("hash"))
            elif torrent.state_enum.is_errored:
                error_torrents.append(torrent.get("hash"))

        return (
            downloading_torrents,
            uploading_torrents,
            paused_torrents,
            checking_torrents,
            error_torrents,
        )

    @eventmanager.register(EventType.PluginAction)
    def handle_pause_torrent(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "pause_torrents":
                return
        self.pause_torrent()

    @eventmanager.register(EventType.PluginAction)
    def handle_pause_upload_torrent(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "pause_upload_torrents":
                return
        self.pause_torrent(self.TorrentType.UPLOADING)

    @eventmanager.register(EventType.PluginAction)
    def handle_pause_download_torrent(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "pause_download_torrents":
                return
        self.pause_torrent(self.TorrentType.DOWNLOADING)

    @eventmanager.register(EventType.PluginAction)
    def handle_pause_checking_torrent(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "pause_checking_torrents":
                return
        self.pause_torrent(self.TorrentType.CHECKING)

    def pause_torrent(self, type: TorrentType = TorrentType.ALL):
        if not self._enabled:
            return

        all_torrents = self.get_all_torrents()
        hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
            self.get_torrents_status(all_torrents)
        )
        if type == self.TorrentType.DOWNLOADING:
            to_be_paused = hash_downloading
        elif type == self.TorrentType.UPLOADING:
            to_be_paused = hash_uploading
        elif type == self.TorrentType.CHECKING:
            to_be_paused = hash_checking
        else:
            to_be_paused = hash_downloading + hash_uploading + hash_checking

        logger.info(
            f"暂定任务启动 \n"
            f"种子总数:  {len(all_torrents)} \n"
            f"做种数量:  {len(hash_uploading)}\n"
            f"下载数量:  {len(hash_downloading)}\n"
            f"检查数量:  {len(hash_checking)}\n"
            f"暂停数量:  {len(hash_paused)}\n"
            f"错误数量:  {len(hash_error)}\n"
            f"暂停操作中请稍等...\n",
        )
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB暂停任务启动】",
                text=f"种子总数:  {len(all_torrents)} \n"
                f"做种数量:  {len(hash_uploading)}\n"
                f"下载数量:  {len(hash_downloading)}\n"
                f"检查数量:  {len(hash_checking)}\n"
                f"暂停数量:  {len(hash_paused)}\n"
                f"错误数量:  {len(hash_error)}\n"
                f"暂停操作中请稍等...\n",
            )
        if len(to_be_paused) > 0:
            if self._qb.stop_torrents(ids=to_be_paused):
                logger.info(f"暂停了{len(to_be_paused)}个种子")
            else:
                logger.error(f"暂停种子失败")
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title=f"【QB远程操作】",
                        text=f"暂停种子失败",
                    )
        # 每个种子等待1ms以让状态切换成功,至少等待1S
        wait_time = 0.001 * len(to_be_paused) + 1
        time.sleep(wait_time)

        all_torrents = self.get_all_torrents()
        hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
            self.get_torrents_status(all_torrents)
        )
        logger.info(
            f"暂定任务完成 \n"
            f"种子总数:  {len(all_torrents)} \n"
            f"做种数量:  {len(hash_uploading)}\n"
            f"下载数量:  {len(hash_downloading)}\n"
            f"检查数量:  {len(hash_checking)}\n"
            f"暂停数量:  {len(hash_paused)}\n"
            f"错误数量:  {len(hash_error)}\n"
        )
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB暂停任务完成】",
                text=f"种子总数:  {len(all_torrents)} \n"
                f"做种数量:  {len(hash_uploading)}\n"
                f"下载数量:  {len(hash_downloading)}\n"
                f"检查数量:  {len(hash_checking)}\n"
                f"暂停数量:  {len(hash_paused)}\n"
                f"错误数量:  {len(hash_error)}\n",
            )

    @eventmanager.register(EventType.PluginAction)
    def handle_resume_torrent(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "resume_torrents":
                return
        self.resume_torrent()

    def resume_torrent(self):
        if not self._enabled:
            return

        all_torrents = self.get_all_torrents()
        hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
            self.get_torrents_status(all_torrents)
        )
        logger.info(
            f"QB开始任务启动 \n"
            f"种子总数:  {len(all_torrents)} \n"
            f"做种数量:  {len(hash_uploading)}\n"
            f"下载数量:  {len(hash_downloading)}\n"
            f"检查数量:  {len(hash_checking)}\n"
            f"暂停数量:  {len(hash_paused)}\n"
            f"错误数量:  {len(hash_error)}\n"
            f"开始操作中请稍等...\n",
        )
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB开始任务启动】",
                text=f"种子总数:  {len(all_torrents)} \n"
                f"做种数量:  {len(hash_uploading)}\n"
                f"下载数量:  {len(hash_downloading)}\n"
                f"检查数量:  {len(hash_checking)}\n"
                f"暂停数量:  {len(hash_paused)}\n"
                f"错误数量:  {len(hash_error)}\n"
                f"开始操作中请稍等...\n",
            )
        if not self._qb.start_torrents(ids=hash_paused):
            logger.error(f"开始种子失败")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=f"开始种子失败",
                )
        # 每个种子等待1ms以让状态切换成功,至少等待1S
        wait_time = 0.001 * len(hash_paused) + 1
        time.sleep(wait_time)

        all_torrents = self.get_all_torrents()
        hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
            self.get_torrents_status(all_torrents)
        )
        logger.info(
            f"开始任务完成 \n"
            f"种子总数:  {len(all_torrents)} \n"
            f"做种数量:  {len(hash_uploading)}\n"
            f"下载数量:  {len(hash_downloading)}\n"
            f"检查数量:  {len(hash_checking)}\n"
            f"暂停数量:  {len(hash_paused)}\n"
            f"错误数量:  {len(hash_error)}\n"
        )
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB开始任务完成】",
                text=f"种子总数:  {len(all_torrents)} \n"
                f"做种数量:  {len(hash_uploading)}\n"
                f"下载数量:  {len(hash_downloading)}\n"
                f"检查数量:  {len(hash_checking)}\n"
                f"暂停数量:  {len(hash_paused)}\n"
                f"错误数量:  {len(hash_error)}\n",
            )

    @eventmanager.register(EventType.PluginAction)
    def handle_qb_status(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "qb_status":
                return
        self.qb_status()

    def qb_status(self):
        if not self._enabled:
            return

        all_torrents = self.get_all_torrents()
        hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
            self.get_torrents_status(all_torrents)
        )
        logger.info(
            f"QB开始任务启动 \n"
            f"种子总数:  {len(all_torrents)} \n"
            f"做种数量:  {len(hash_uploading)}\n"
            f"下载数量:  {len(hash_downloading)}\n"
            f"检查数量:  {len(hash_checking)}\n"
            f"暂停数量:  {len(hash_paused)}\n"
            f"错误数量:  {len(hash_error)}\n"
            f"开始操作中请稍等...\n",
        )
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB开始任务启动】",
                text=f"种子总数:  {len(all_torrents)} \n"
                f"做种数量:  {len(hash_uploading)}\n"
                f"下载数量:  {len(hash_downloading)}\n"
                f"检查数量:  {len(hash_checking)}\n"
                f"暂停数量:  {len(hash_paused)}\n"
                f"错误数量:  {len(hash_error)}\n"
                f"开始操作中请稍等...\n",
            )

    @eventmanager.register(EventType.PluginAction)
    def handle_toggle_upload_limit(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "toggle_upload_limit":
                return
        self.set_limit(self._upload_limit, self._download_limit)

    @eventmanager.register(EventType.PluginAction)
    def handle_toggle_download_limit(self, event: Event):
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "toggle_download_limit":
                return
        self.set_limit(self._upload_limit, self._download_limit)

    def set_both_limit(self, upload_limit, download_limit):
        if not self._enable_upload_limit or not self._enable_upload_limit:
            return True

        if (
            not upload_limit
            or not upload_limit.isdigit()
            or not download_limit
            or not download_limit.isdigit()
        ):
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB远程操作】",
                text=f"设置QB限速失败,download_limit或upload_limit不是一个数值",
            )
            return False

        return self._qb.set_speed_limit(
            download_limit=int(download_limit), upload_limit=int(upload_limit)
        )

    def set_upload_limit(self, upload_limit):
        if not self._enable_upload_limit:
            return True

        if not upload_limit or not upload_limit.isdigit():
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB远程操作】",
                text=f"设置QB限速失败,upload_limit不是一个数值",
            )
            return False

        download_limit_current_val, _ = self._qb.get_speed_limit()
        return self._qb.set_speed_limit(
            download_limit=int(download_limit_current_val),
            upload_limit=int(upload_limit),
        )

    def set_download_limit(self, download_limit):
        if not self._enable_download_limit:
            return True

        if not download_limit or not download_limit.isdigit():
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【QB远程操作】",
                text=f"设置QB限速失败,download_limit不是一个数值",
            )
            return False

        _, upload_limit_current_val = self._qb.get_speed_limit()
        return self._qb.set_speed_limit(
            download_limit=int(download_limit),
            upload_limit=int(upload_limit_current_val),
        )

    def set_limit(self, upload_limit, download_limit):
        # 限速，满足以下三种情况设置限速
        # 1. 插件启用 && download_limit启用
        # 2. 插件启用 && upload_limit启用
        # 3. 插件启用 && download_limit启用 && upload_limit启用

        flag = None
        if self._enabled and self._enable_download_limit and self._enable_upload_limit:
            flag = self.set_both_limit(upload_limit, download_limit)

        elif flag is None and self._enabled and self._enable_download_limit:
            flag = self.set_download_limit(download_limit)

        elif flag is None and self._enabled and self._enable_upload_limit:
            flag = self.set_upload_limit(upload_limit)

        if flag:
            logger.info(f"设置QB限速成功")
            if self._notify:
                if upload_limit == 0:
                    text = f"上传无限速"
                else:
                    text = f"上传限速：{upload_limit} KB/s"
                if download_limit == 0:
                    text += f"\n下载无限速"
                else:
                    text += f"\n下载限速：{download_limit} KB/s"
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=text,
                )
        elif not flag:
            logger.error(f"QB设置限速失败")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=f"设置QB限速失败",
                )

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
                                "props": {"cols": 12, "md": 6},
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
                                "props": {"cols": 12, "md": 6},
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
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlypauseonce",
                                            "label": "立即暂停所有任务",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyresumeonce",
                                            "label": "立即开始所有任务",
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
                                        "component": "VTextField",
                                        "props": {
                                            "model": "pause_cron",
                                            "label": "暂停周期",
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
                                            "model": "resume_cron",
                                            "label": "开始周期",
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
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_upload_limit",
                                            "label": "上传限速",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_download_limit",
                                            "label": "下载限速",
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
                                        "component": "VTextField",
                                        "props": {
                                            "model": "upload_limit",
                                            "label": "上传限速 KB/s",
                                            "placeholder": "KB/s",
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
                                            "model": "download_limit",
                                            "label": "下载限速 KB/s",
                                            "placeholder": "KB/s",
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
                                            "model": "onlypauseupload",
                                            "label": "暂停上传任务",
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
                                            "model": "onlypausedownload",
                                            "label": "暂停下载任务",
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
                                            "model": "onlypausechecking",
                                            "label": "暂停检查任务",
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
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "开始周期和暂停周期使用Cron表达式，如：0 0 0 * *，仅针对开始/暂定全部任务",
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
                                            "text": "交互命令有暂停QB种子、开始QB种子、QB切换上传限速状态、QB切换下载限速状态",
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
                                            "text": "PT精神重在分享，请勿恶意限速，因此导致账号被封禁作者概不负责",
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
            "notify": True,
            "onlypauseonce": False,
            "onlyresumeonce": False,
            "onlypauseupload": False,
            "onlypausedownload": False,
            "onlypausechecking": False,
            "upload_limit": 0,
            "download_limit": 0,
            "enable_upload_limit": False,
            "enable_download_limit": False,
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        pass
