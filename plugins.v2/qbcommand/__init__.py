from typing import List, Tuple, Dict, Any, Optional
from enum import Enum
from urllib.parse import urlparse
import urllib
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType, ServiceInfo
from app.schemas.types import EventType
from apscheduler.triggers.cron import CronTrigger
from app.core.event import eventmanager, Event
from apscheduler.schedulers.background import BackgroundScheduler
from app.core.config import settings
from app.helper.sites import SitesHelper
from app.db.site_oper import SiteOper
from app.utils.string import StringUtils
from app.helper.downloader import DownloaderHelper
from datetime import datetime, timedelta

import pytz
import time


class QbCommand(_PluginBase):
    # 插件名称
    plugin_name = "QB远程操作"
    # 插件描述
    plugin_desc = "通过定时任务或交互命令远程操作QB暂停/开始/限速等"
    # 插件图标
    plugin_icon = "Qbittorrent_A.png"
    # 插件版本
    plugin_version = "2.1"
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
    _op_site_ids = []
    _op_sites = []
    _multi_level_root_domain = ["edu.cn", "com.cn", "net.cn", "org.cn"]
    _scheduler = None
    _exclude_dirs = ""
    _downloaders = []

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

            self._op_site_ids = config.get("op_site_ids") or []
            self._downloaders = config.get("downloaders")
            # 查询所有站点
            all_sites = [site for site in SitesHelper().get_indexers() if not site.get("public")] + self.__custom_sites()
            # 过滤掉没有选中的站点
            self._op_sites = [site for site in all_sites if site.get("id") in self._op_site_ids]
            self._exclude_dirs = config.get("exclude_dirs") or ""

        if self._only_pause_once or self._only_resume_once:
            if self._only_pause_once and self._only_resume_once:
                logger.warning("只能选择一个: 立即暂停或立即开始所有任务")
            elif self._only_pause_once:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"立即运行一次暂停所有任务")
                self._scheduler.add_job(
                    self.pause_torrent,
                    "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                )
            elif self._only_resume_once:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"立即运行一次开始所有任务")
                self._scheduler.add_job(
                    self.resume_torrent,
                    "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                )

            self._only_resume_once = False
            self._only_pause_once = False
            self.update_config(
                {
                    "onlypauseonce": False,
                    "onlyresumeonce": False,
                    "enabled": self._enabled,
                    "notify": self._notify,
                    "downloaders": self._downloaders,
                    "pause_cron": self._pause_cron,
                    "resume_cron": self._resume_cron,
                    "op_site_ids": self._op_site_ids,
                    "exclude_dirs": self._exclude_dirs,
                }
            )

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

        if (
                self._only_pause_upload
                or self._only_pause_download
                or self._only_pause_checking
        ):
            if self._only_pause_upload:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"立即运行一次暂停所有上传任务")
                self._scheduler.add_job(
                    self.pause_torrent,
                    "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    kwargs={
                        'type': self.TorrentType.UPLOADING
                    }
                )
            if self._only_pause_download:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"立即运行一次暂停所有下载任务")
                self._scheduler.add_job(
                    self.pause_torrent,
                    "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    kwargs={
                        'type': self.TorrentType.DOWNLOADING
                    }
                )
            if self._only_pause_checking:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"立即运行一次暂停所有检查任务")
                self._scheduler.add_job(
                    self.pause_torrent,
                    "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    kwargs={
                        'type': self.TorrentType.CHECKING
                    }
                )

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
                    "op_site_ids": self._op_site_ids,
                }
            )

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

        self.set_limit(self._upload_limit, self._download_limit)

    @property
    def service_info(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._downloaders:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        services = DownloaderHelper().get_services(name_filters=self._downloaders)

        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            elif not self.check_is_qb(service_info):
                logger.warning(f"不支持的下载器类型 {service_name}，仅支持QB，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    @staticmethod
    def check_is_qb(service_info) -> bool:
        """
        检查下载器类型是否为 qbittorrent 或 transmission
        """
        if DownloaderHelper().is_downloader(service_type="qbittorrent", service=service_info):
            return True
        elif DownloaderHelper().is_downloader(service_type="transmission", service=service_info):
            return False
        return False

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

    def __custom_sites(self) -> List[Any]:
        custom_sites = []
        custom_sites_config = self.get_config("CustomSites")
        if custom_sites_config and custom_sites_config.get("enabled"):
            custom_sites = custom_sites_config.get("sites")
        return custom_sites

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

    def get_all_torrents(self, service):
        downloader_name = service.name
        downloader_obj = service.instance
        all_torrents, error = downloader_obj.get_torrents()
        if error:
            logger.error(f"获取下载器:{downloader_name}种子失败: {error}")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=f"获取下载器:{downloader_name}种子失败，请检查下载器配置",
                )
            return []

        if not all_torrents:
            logger.warning(f"下载器:{downloader_name}没有种子")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=f"下载器:{downloader_name}中没有种子",
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
        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            all_torrents = self.get_all_torrents(service)
            hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
                self.get_torrents_status(all_torrents)
            )

            logger.info(
                f"下载器{downloader_name}暂定任务启动 \n"
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
                    title=f"【下载器{downloader_name}暂停任务启动】",
                    text=f"种子总数:  {len(all_torrents)} \n"
                         f"做种数量:  {len(hash_uploading)}\n"
                         f"下载数量:  {len(hash_downloading)}\n"
                         f"检查数量:  {len(hash_checking)}\n"
                         f"暂停数量:  {len(hash_paused)}\n"
                         f"错误数量:  {len(hash_error)}\n"
                         f"暂停操作中请稍等...\n",
                )
            pause_torrents = self.filter_pause_torrents(all_torrents)
            hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
                self.get_torrents_status(pause_torrents)
            )
            if type == self.TorrentType.DOWNLOADING:
                to_be_paused = hash_downloading
            elif type == self.TorrentType.UPLOADING:
                to_be_paused = hash_uploading
            elif type == self.TorrentType.CHECKING:
                to_be_paused = hash_checking
            else:
                to_be_paused = hash_downloading + hash_uploading + hash_checking

            if len(to_be_paused) > 0:
                if downloader_obj.stop_torrents(ids=to_be_paused):
                    logger.info(f"暂停了{len(to_be_paused)}个种子")
                else:
                    logger.error(f"下载器{downloader_name}暂停种子失败")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title=f"【远程操作】",
                            text=f"下载器{downloader_name}暂停种子失败",
                        )
            # 每个种子等待1ms以让状态切换成功,至少等待1S
            wait_time = 0.001 * len(to_be_paused) + 1
            time.sleep(wait_time)

            all_torrents = self.get_all_torrents(service)
            hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
                self.get_torrents_status(all_torrents)
            )
            logger.info(
                f"下载器{downloader_name}暂定任务完成 \n"
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
                    title=f"【下载器{downloader_name}暂停任务完成】",
                    text=f"种子总数:  {len(all_torrents)} \n"
                         f"做种数量:  {len(hash_uploading)}\n"
                         f"下载数量:  {len(hash_downloading)}\n"
                         f"检查数量:  {len(hash_checking)}\n"
                         f"暂停数量:  {len(hash_paused)}\n"
                         f"错误数量:  {len(hash_error)}\n",
                )

    def __is_excluded(self, file_path) -> bool:
        """
        是否排除目录
        """
        for exclude_dir in self._exclude_dirs.split("\n"):
            if exclude_dir and exclude_dir in str(file_path):
                return True
        return False

    def filter_pause_torrents(self, all_torrents):
        torrents = []
        for torrent in all_torrents:
            if self.__is_excluded(torrent.get("content_path")):
                continue
            torrents.append(torrent)
        return torrents

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

        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            all_torrents = self.get_all_torrents(service)
            hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
                self.get_torrents_status(all_torrents)
            )
            logger.info(
                f"下载器{downloader_name}开始任务启动 \n"
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
                    title=f"【下载器{downloader_name}开始任务启动】",
                    text=f"种子总数:  {len(all_torrents)} \n"
                         f"做种数量:  {len(hash_uploading)}\n"
                         f"下载数量:  {len(hash_downloading)}\n"
                         f"检查数量:  {len(hash_checking)}\n"
                         f"暂停数量:  {len(hash_paused)}\n"
                         f"错误数量:  {len(hash_error)}\n"
                         f"开始操作中请稍等...\n",
                )

            resume_torrents = self.filter_resume_torrents(all_torrents)
            hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
                self.get_torrents_status(resume_torrents)
            )
            if not downloader_obj.start_torrents(ids=hash_paused):
                logger.error(f"下载器{downloader_name}开始种子失败")
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title=f"【QB远程操作】",
                        text=f"下载器{downloader_name}开始种子失败",
                    )
            # 每个种子等待1ms以让状态切换成功,至少等待1S
            wait_time = 0.001 * len(hash_paused) + 1
            time.sleep(wait_time)

            all_torrents = self.get_all_torrents(service)
            hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
                self.get_torrents_status(all_torrents)
            )
            logger.info(
                f"下载器{downloader_name}开始任务完成 \n"
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
                    title=f"【下载器{downloader_name}开始任务完成】",
                    text=f"种子总数:  {len(all_torrents)} \n"
                         f"做种数量:  {len(hash_uploading)}\n"
                         f"下载数量:  {len(hash_downloading)}\n"
                         f"检查数量:  {len(hash_checking)}\n"
                         f"暂停数量:  {len(hash_paused)}\n"
                         f"错误数量:  {len(hash_error)}\n",
                )

    def filter_resume_torrents(self, all_torrents):
        """
        过滤掉不参与保种的种子
        """
        if len(self._op_sites) == 0:
            return all_torrents

        urls = [site.get("url") for site in self._op_sites]
        op_sites_main_domains = []
        for url in urls:
            domain = StringUtils.get_url_netloc(url)
            main_domain = self.get_main_domain(domain[1])
            op_sites_main_domains.append(main_domain)

        torrents = []
        for torrent in all_torrents:
            if torrent.get("state") in ["pausedUP", "stoppedUP"]:
                tracker_url = self.get_torrent_tracker(torrent)
                if not tracker_url:
                    logger.info(f"获取种子 {torrent.name} Tracker失败，不过滤该种子")
                    torrents.append(torrent)
                _, tracker_domain = StringUtils.get_url_netloc(tracker_url)
                if not tracker_domain:
                    logger.info(f"获取种子 {torrent.name} Tracker失败，不过滤该种子")
                    torrents.append(torrent)
                tracker_main_domain = self.get_main_domain(domain=tracker_domain)
                if tracker_main_domain in op_sites_main_domains:
                    logger.info(
                        f"种子 {torrent.name} 属于站点{tracker_main_domain}，不执行操作"
                    )
                    continue

            torrents.append(torrent)
        return torrents

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
        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            all_torrents = self.get_all_torrents(service)
            hash_downloading, hash_uploading, hash_paused, hash_checking, hash_error = (
                self.get_torrents_status(all_torrents)
            )
            logger.info(
                f"下载器{downloader_name}任务状态 \n"
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
                    title=f"【下载器{downloader_name}任务状态】",
                    text=f"种子总数:  {len(all_torrents)} \n"
                         f"做种数量:  {len(hash_uploading)}\n"
                         f"下载数量:  {len(hash_downloading)}\n"
                         f"检查数量:  {len(hash_checking)}\n"
                         f"暂停数量:  {len(hash_paused)}\n"
                         f"错误数量:  {len(hash_error)}\n"
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

        flag = True
        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            flag = flag and downloader_obj.set_speed_limit(
                download_limit=int(download_limit), upload_limit=int(upload_limit)
            )
        return flag

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
        flag = True
        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            download_limit_current_val, _ = downloader_obj.get_speed_limit()
            flag = flag and downloader_obj.set_speed_limit(
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

        flag = True
        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            _, upload_limit_current_val = downloader_obj.get_speed_limit()
            flag = flag and downloader_obj.set_speed_limit(
                download_limit=int(download_limit),
                upload_limit=int(upload_limit_current_val),
            )
        return flag

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

        if flag is True:
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
        elif flag is False:
            logger.error(f"QB设置限速失败")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【QB远程操作】",
                    text=f"设置QB限速失败",
                )

    @staticmethod
    def get_torrent_tracker(torrent):
        """
        qb解析 tracker
        :return: tracker url
        """
        if not torrent:
            return None
        tracker = torrent.get("tracker")
        if tracker and len(tracker) > 0:
            return tracker
        magnet_uri = torrent.get("magnet_uri")
        if not magnet_uri or len(magnet_uri) <= 0:
            return None
        magnet_uri_obj = urlparse(magnet_uri)
        query = urllib.parse.parse_qs(magnet_uri_obj.query)
        tr = query["tr"]
        if not tr or len(tr) <= 0:
            return None
        return tr[0]

    def get_main_domain(self, domain):
        """
        获取域名的主域名
        :param domain: 原域名
        :return: 主域名
        """
        if not domain:
            return None
        domain_arr = domain.split(".")
        domain_len = len(domain_arr)
        if domain_len < 2:
            return None
        root_domain, root_domain_len = self.match_multi_level_root_domain(domain=domain)
        if root_domain:
            return f"{domain_arr[-root_domain_len - 1]}.{root_domain}"
        else:
            return f"{domain_arr[-2]}.{domain_arr[-1]}"

    def match_multi_level_root_domain(self, domain):
        """
        匹配多级根域名
        :param domain: 被匹配的域名
        :return: 匹配的根域名, 匹配的根域名长度
        """
        if not domain or not self._multi_level_root_domain:
            return None, 0
        for root_domain in self._multi_level_root_domain:
            if domain.endswith("." + root_domain):
                root_domain_len = len(root_domain.split("."))
                return root_domain, root_domain_len
        return None, 0

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        customSites = self.__custom_sites()

        site_options = [
                           {"title": site.name, "value": site.id}
                           for site in SiteOper().list_order_by_pri()
                       ] + [
                           {"title": site.get("name"), "value": site.get("id")} for site in customSites
                       ]
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
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in DownloaderHelper().get_configs().values()]
                                        }
                                    }
                                ]
                            }
                        ]
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "chips": True,
                                            "multiple": True,
                                            "model": "op_site_ids",
                                            "label": "停止保种站点(暂停保种后不会被恢复)",
                                            "items": site_options,
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
                                            "label": "不暂停保种目录",
                                            "rows": 5,
                                            "placeholder": "该目录下的做种不会暂停，一行一个目录",
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
            "op_site_ids": [],
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
