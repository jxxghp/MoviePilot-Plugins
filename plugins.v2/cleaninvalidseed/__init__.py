import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas import ServiceInfo
from app.schemas.types import EventType
from app.utils.string import StringUtils


class CleanInvalidSeed(_PluginBase):
    # 插件名称
    plugin_name = "清理QB无效做种"
    # 插件描述
    plugin_desc = "清理已经被站点删除的种子及源文件，仅支持QB"
    # 插件图标
    plugin_icon = "clean_a.png"
    # 插件版本
    plugin_version = "2.0"
    # 插件作者
    plugin_author = "DzAvril"
    # 作者主页
    author_url = "https://github.com/DzAvril"
    # 插件配置项ID前缀
    plugin_config_prefix = "cleaninvalidseed"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _cron = None
    _notify = False
    _onlyonce = False
    _detect_invalid_files = False
    _delete_invalid_files = False
    _delete_invalid_torrents = False
    _notify_all = False
    _label_only = False
    _label = ""
    _download_dirs = ""
    _exclude_keywords = ""
    _exclude_categories = ""
    _exclude_labels = ""
    _more_logs = False
    _downloaders = []
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    _error_msg = [
        "torrent not registered with this tracker",
        "Torrent not registered with this tracker",
        "torrent banned",
        "err torrent banned",
    ]
    _custom_error_msg = ""

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._delete_invalid_torrents = config.get("delete_invalid_torrents")
            self._delete_invalid_files = config.get("delete_invalid_files")
            self._detect_invalid_files = config.get("detect_invalid_files")
            self._notify_all = config.get("notify_all")
            self._label_only = config.get("label_only")
            self._label = config.get("label")
            self._download_dirs = config.get("download_dirs")
            self._exclude_keywords = config.get("exclude_keywords")
            self._exclude_categories = config.get("exclude_categories")
            self._exclude_labels = config.get("exclude_labels")
            self._custom_error_msg = config.get("custom_error_msg")
            self._more_logs = config.get("more_logs")
            self._downloaders = config.get("downloaders")

            # 加载模块
        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"清理无效种子服务启动，立即运行一次")
            self._scheduler.add_job(
                func=self.clean_invalid_seed,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="清理无效种子",
            )
            # 关闭一次性开关
            self._onlyonce = False
            self._update_config()

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def _update_config(self):
        self.update_config(
            {
                "onlyonce": False,
                "cron": self._cron,
                "enabled": self._enabled,
                "notify": self._notify,
                "delete_invalid_torrents": self._delete_invalid_torrents,
                "delete_invalid_files": self._delete_invalid_files,
                "detect_invalid_files": self._detect_invalid_files,
                "notify_all": self._notify_all,
                "label_only": self._label_only,
                "label": self._label,
                "download_dirs": self._download_dirs,
                "exclude_keywords": self._exclude_keywords,
                "exclude_categories": self._exclude_categories,
                "exclude_labels": self._exclude_labels,
                "custom_error_msg": self._custom_error_msg,
                "more_logs": self._more_logs,
                "downloaders": self._downloaders,
            }
        )

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

        return False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/detect_invalid_torrents",
                "event": EventType.PluginAction,
                "desc": "检测无效做种",
                "category": "QB",
                "data": {"action": "detect_invalid_torrents"},
            },
            {
                "cmd": "/delete_invalid_torrents",
                "event": EventType.PluginAction,
                "desc": "清理无效做种",
                "category": "QB",
                "data": {"action": "delete_invalid_torrents"},
            },
            {
                "cmd": "/detect_invalid_files",
                "event": EventType.PluginAction,
                "desc": "检测无效源文件",
                "category": "QB",
                "data": {"action": "detect_invalid_files"},
            },
            {
                "cmd": "/delete_invalid_files",
                "event": EventType.PluginAction,
                "desc": "清理无效源文件",
                "category": "QB",
                "data": {"action": "delete_invalid_files"},
            },
            {
                "cmd": "/toggle_notify_all",
                "event": EventType.PluginAction,
                "desc": "QB清理插件切换全量通知",
                "category": "QB",
                "data": {"action": "toggle_notify_all"},
            },
        ]

    @eventmanager.register(EventType.PluginAction)
    def handle_commands(self, event: Event):
        if event:
            event_data = event.event_data
            if event_data:
                if not (
                        event_data.get("action") == "detect_invalid_torrents"
                        or event_data.get("action") == "delete_invalid_torrents"
                        or event_data.get("action") == "detect_invalid_files"
                        or event_data.get("action") == "delete_invalid_files"
                        or event_data.get("action") == "toggle_notify_all"
                ):
                    return
                self.post_message(
                    channel=event.event_data.get("channel"),
                    title="开始执行远程命令...",
                    userid=event.event_data.get("user"),
                )
                old_delete_invalid_torrents = self._delete_invalid_torrents
                old_detect_invalid_files = self._detect_invalid_files
                old_delete_invalid_files = self._delete_invalid_files
                if event_data.get("action") == "detect_invalid_torrents":
                    logger.info("收到远程命令，开始检测无效做种")
                    self._delete_invalid_torrents = False
                    self._detect_invalid_files = False
                    self._delete_invalid_files = False
                    self.clean_invalid_seed()
                elif event_data.get("action") == "delete_invalid_torrents":
                    logger.info("收到远程命令，开始清理无效做种")
                    self._delete_invalid_torrents = True
                    self._detect_invalid_files = False
                    self._delete_invalid_files = False
                    self.clean_invalid_seed()
                elif event_data.get("action") == "detect_invalid_files":
                    logger.info("收到远程命令，开始检测无效源文件")
                    self._delete_invalid_files = False
                    self.detect_invalid_files()
                elif event_data.get("action") == "delete_invalid_files":
                    logger.info("收到远程命令，开始清理无效源文件")
                    self._delete_invalid_files = True
                    self.detect_invalid_files()
                elif event_data.get("action") == "toggle_notify_all":
                    self._notify_all = not self._notify_all
                    self._update_config()
                    if self._notify_all:
                        self.post_message(
                            channel=event.event_data.get("channel"),
                            title="已开启全量通知",
                            userid=event.event_data.get("user"),
                        )
                    else:
                        self.post_message(
                            channel=event.event_data.get("channel"),
                            title="已关闭全量通知",
                            userid=event.event_data.get("user"),
                        )
                    return
                else:
                    logger.error("收到未知远程命令")
                    return
                self._delete_invalid_torrents = old_delete_invalid_torrents
                self._detect_invalid_files = old_detect_invalid_files
                self._delete_invalid_files = old_delete_invalid_files
                self.post_message(
                    channel=event.event_data.get("channel"),
                    title="远程命令执行完成！",
                    userid=event.event_data.get("user"),
                )

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
        if self._enabled and self._cron:
            return [
                {
                    "id": "CleanInvalidSeed",
                    "name": "清理QB无效做种",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.clean_invalid_seed,
                    "kwargs": {},
                }
            ]

    def get_all_torrents(self, service):
        downloader_name = service.name
        downloader_obj = service.instance
        all_torrents, error = downloader_obj.get_torrents()

        if error:
            logger.error(f"获取下载器:{downloader_name}种子失败: {error}")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【清理QB无效做种】",
                    text=f"获取下载器:{downloader_name}种子失败，请检查下载器配置",
                )
            return []

        if not all_torrents:
            logger.warning(f"下载器:{downloader_name}")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【清理QB无效做种】",
                    text=f"下载器:{downloader_name}中没有种子",
                )
            return []
        return all_torrents

    def clean_invalid_seed(self):
        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            logger.info(f"开始清理 {downloader_name} 无效做种...")
            all_torrents = self.get_all_torrents(service)
            temp_invalid_torrents = []
            # tracker未工作，但暂时不能判定为失效做种，需人工判断
            tracker_not_working_torrents = []
            working_tracker_set = set()
            exclude_categories = (
                self._exclude_categories.split("\n") if self._exclude_categories else []
            )
            exclude_labels = (
                self._exclude_labels.split("\n") if self._exclude_labels else []
            )
            custom_msgs = (
                self._custom_error_msg.split("\n") if self._custom_error_msg else []
            )
            error_msgs = self._error_msg + custom_msgs
            # 第一轮筛选出所有未工作的种子
            for torrent in all_torrents:
                trackers = torrent.trackers
                is_invalid = True
                is_tracker_working = False
                for tracker in trackers:
                    if tracker.get("tier") == -1:
                        continue
                    tracker_domian = StringUtils.get_url_netloc((tracker.get("url")))[1]
                    # 有一个tracker工作即为有效做种
                    if (tracker.get("status") == 2) or (tracker.get("status") == 3):
                        is_tracker_working = True

                    if not (
                            (tracker.get("status") == 4) and (tracker.get("msg") in error_msgs)
                    ):
                        is_invalid = False
                        working_tracker_set.add(tracker_domian)

                    if self._more_logs:
                        logger.info(
                            f"处理 [{torrent.name}] tracker [{tracker_domian}]: 分类: [{torrent.category}], 标签: [{torrent.tags}], 状态: [{tracker.get('status')}], msg: [{tracker.get('msg')}], is_invalid: [{is_invalid}], is_working: [{is_tracker_working}]")
                if is_invalid:
                    temp_invalid_torrents.append(torrent)
                elif not is_tracker_working:
                    # 排除已暂停的种子
                    if not torrent.state_enum.is_paused:
                        tracker_not_working_torrents.append(torrent)

            logger.info(f"初筛共有{len(temp_invalid_torrents)}个无效做种")
            # 第二轮筛选出tracker有正常工作种子而当前种子未工作的，避免因临时关站或tracker失效导致误删的问题
            # 失效做种但通过种子分类排除的种子
            invalid_torrents_exclude_categories = []
            # 失效做种但通过种子标签排除的种子
            invalid_torrents_exclude_labels = []
            # 将invalid_torrents基本信息保存起来，在种子被删除后依然可以打印这些信息
            invalid_torrent_tuple_list = []
            deleted_torrent_tuple_list = []
            for torrent in temp_invalid_torrents:
                trackers = torrent.trackers
                for tracker in trackers:
                    if tracker.get("tier") == -1:
                        continue
                    tracker_domian = StringUtils.get_url_netloc((tracker.get("url")))[1]
                    if tracker_domian in working_tracker_set:
                        # tracker是正常的，说明该种子是无效的
                        invalid_torrent_tuple_list.append(
                            (
                                torrent.name,
                                torrent.category,
                                torrent.tags,
                                torrent.size,
                                tracker_domian,
                                tracker.msg,
                            )
                        )
                        if self._delete_invalid_torrents or self._label_only:
                            # 检查种子分类和标签是否排除
                            is_excluded = False
                            if torrent.category in exclude_categories:
                                is_excluded = True
                                invalid_torrents_exclude_categories.append(torrent)
                            torrent_labels = [
                                tag.strip() for tag in torrent.tags.split(",")
                            ]
                            for label in torrent_labels:
                                if label in exclude_labels:
                                    is_excluded = True
                                    invalid_torrents_exclude_labels.append(torrent)
                            if not is_excluded:
                                if self._label_only:
                                    # 仅标记
                                    downloader_obj.set_torrents_tag(ids=torrent.get("hash"), tags=[
                                        self._label if self._label != "" else "无效做种"])
                                else:
                                    # 只删除种子不删除文件，以防其它站点辅种
                                    downloader_obj.delete_torrents(False, torrent.get("hash"))
                                # 标记已处理种子信息
                                deleted_torrent_tuple_list.append(
                                    (
                                        torrent.name,
                                        torrent.category,
                                        torrent.tags,
                                        torrent.size,
                                        tracker_domian,
                                        tracker.msg,
                                    )
                                )
                        break
            invalid_msg = f"检测到{len(invalid_torrent_tuple_list)}个失效做种\n"
            tracker_not_working_msg = f"检测到{len(tracker_not_working_torrents)}个tracker未工作做种，请检查种子状态\n"

            exclude_categories_msg = ""
            exclude_labels_msg = ""
            deleted_msg = ""

            if self._label_only or self._delete_invalid_torrents:
                if self._label_only:
                    deleted_msg = f"标记了{len(deleted_torrent_tuple_list)}个失效种子\n"
                else:
                    deleted_msg = f"删除了{len(deleted_torrent_tuple_list)}个失效种子\n"
                if len(exclude_categories) != 0:
                    exclude_categories_msg = f"分类排除{len(invalid_torrents_exclude_categories)}个失效种子未删除，请手动处理\n"
                if len(exclude_labels) != 0:
                    exclude_labels_msg = f"标签排除{len(invalid_torrents_exclude_labels)}个失效种子未删除，请手动处理\n"
            for index in range(len(invalid_torrent_tuple_list)):
                torrent = invalid_torrent_tuple_list[index]
                invalid_msg += f"{index + 1}. {torrent[0]}，分类：{torrent[1]}，标签：{torrent[2]}, 大小：{StringUtils.str_filesize(torrent[3])}，Trackers: {torrent[4]}：{torrent[5]}\n"

            for index in range(len(tracker_not_working_torrents)):
                torrent = tracker_not_working_torrents[index]
                trackers = torrent.trackers
                tracker_msg = ""
                for tracker in trackers:
                    if tracker.get("tier") == -1:
                        continue
                    tracker_domian = StringUtils.get_url_netloc((tracker.get("url")))[1]
                    tracker_msg += f" {tracker_domian}：{tracker.msg} "
                tracker_not_working_msg += f"{index + 1}. {torrent.name}，分类：{torrent.category}，标签：{torrent.tags}, 大小：{StringUtils.str_filesize(torrent.size)}，Trackers: {tracker_msg}\n"

            for index in range(len(invalid_torrents_exclude_categories)):
                torrent = invalid_torrents_exclude_categories[index]
                trackers = torrent.trackers
                tracker_msg = ""
                for tracker in trackers:
                    if tracker.get("tier") == -1:
                        continue
                    tracker_domian = StringUtils.get_url_netloc((tracker.get("url")))[1]
                    tracker_msg += f" {tracker_domian}：{tracker.msg} "
                exclude_categories_msg += f"{index + 1}. {torrent.name}，分类：{torrent.category}，标签：{torrent.tags}, 大小：{StringUtils.str_filesize(torrent.size)}，Trackers: {tracker_msg}\n"

            for index in range(len(invalid_torrents_exclude_labels)):
                torrent = invalid_torrents_exclude_labels[index]
                trackers = torrent.trackers
                tracker_msg = ""
                for tracker in trackers:
                    if tracker.get("tier") == -1:
                        continue
                    tracker_domian = StringUtils.get_url_netloc((tracker.get("url")))[1]
                    tracker_msg += f" {tracker_domian}：{tracker.msg} "
                exclude_labels_msg += f"{index + 1}. {torrent.name}，分类：{torrent.category}，标签：{torrent.tags}, 大小：{StringUtils.str_filesize(torrent.size)}，Trackers: {tracker_msg}\n"

            for index in range(len(deleted_torrent_tuple_list)):
                torrent = deleted_torrent_tuple_list[index]
                deleted_msg += f"{index + 1}. {torrent[0]}，分类：{torrent[1]}，标签：{torrent[2]}, 大小：{StringUtils.str_filesize(torrent[3])}，Trackers: {torrent[4]}：{torrent[5]}\n"

            # 日志
            logger.info(invalid_msg)
            logger.info(tracker_not_working_msg)
            if self._delete_invalid_torrents:
                logger.info(deleted_msg)
                if len(exclude_categories) != 0:
                    logger.info(exclude_categories_msg)
                if len(exclude_labels) != 0:
                    logger.info(exclude_labels_msg)
            # 通知
            if self._notify:
                invalid_msg = invalid_msg.replace("_", "\\_")
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【清理无效做种】",
                    text=invalid_msg,
                )
                if self._notify_all:
                    tracker_not_working_msg = tracker_not_working_msg.replace("_", "\\_")
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title=f"【清理无效做种】",
                        text=tracker_not_working_msg,
                    )
                if self._label_only or self._delete_invalid_torrents:
                    deleted_msg = deleted_msg.replace("_", "\\_")
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title=f"【清理无效做种】",
                        text=deleted_msg,
                    )
                    if self._notify_all:
                        exclude_categories_msg = exclude_categories_msg.replace("_", "\\_")
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title=f"【清理无效做种】",
                            text=exclude_categories_msg,
                        )
                        exclude_labels_msg = exclude_labels_msg.replace("_", "\\_")
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title=f"【清理无效做种】",
                            text=exclude_labels_msg,
                        )
            logger.info("检测无效做种任务结束")
            if self._detect_invalid_files:
                self.detect_invalid_files()

    def detect_invalid_files(self):
        logger.info("开始检测未做种的无效源文件")

        all_torrents = []

        for service in self.service_info.values():
            downloader_name = service.name
            downloader_obj = service.instance
            if not downloader_obj:
                logger.error(f"获取下载器失败 {downloader_name}")
                continue
            all_torrents += self.get_all_torrents(service)

        source_path_map = {}
        source_paths = []
        total_size = 0
        deleted_file_cnt = 0
        exclude_key_words = (
            self._exclude_keywords.split("\n") if self._exclude_keywords else []
        )
        if not self._download_dirs:
            logger.error("未配置下载目录，无法检测未做种无效源文件")
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【检测无效源文件】",
                text="未配置下载目录，无法检测未做种无效源文件",
            )
            return
        for path in self._download_dirs.split("\n"):
            mp_path, qb_path = path.split(":")
            source_path_map[mp_path] = qb_path
            source_paths.append(mp_path)
        # 所有做种源文件路径
        content_path_set = set()
        for torrent in all_torrents:
            content_path_set.add(torrent.content_path)

        message = "检测未做种无效源文件：\n"
        for source_path_str in source_paths:
            source_path = Path(source_path_str)
            # 判断source_path是否存在
            if not source_path.exists():
                logger.error(f"{source_path} 不存在，无法检测未做种无效源文件")
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【检测无效源文件】",
                    text=f"{source_path} 不存在，无法检测未做种无效源文件",
                )
                continue
            source_files = []
            # 获取source_path下的所有文件包括文件夹
            for file in source_path.iterdir():
                source_files.append(file)
            for source_file in source_files:
                skip = False
                for key_word in exclude_key_words:
                    if key_word in source_file.name:
                        logger.info(f"{str(source_file)}命中关键字{key_word}，不做处理")
                        skip = True
                        break
                if skip:
                    continue
                # 将mp_path替换成 qb_path
                qb_path = (str(source_file)).replace(
                    source_path_str, source_path_map[source_path_str]
                )
                # todo: 优化性能
                is_exist = False
                for content_path in content_path_set:
                    if qb_path in content_path:
                        is_exist = True
                        break

                if not is_exist:
                    deleted_file_cnt += 1
                    message += f"{deleted_file_cnt}. {str(source_file)}\n"
                    total_size += self.get_size(source_file)
                    if self._delete_invalid_files:
                        if source_file.is_file():
                            source_file.unlink()
                        elif source_file.is_dir():
                            shutil.rmtree(source_file)

        message += f"检测到{deleted_file_cnt}个未做种的无效源文件，共占用{StringUtils.str_filesize(total_size)}空间。\n"
        if self._delete_invalid_files:
            message += f"***已删除无效源文件，释放{StringUtils.str_filesize(total_size)}空间!***\n"
        logger.info(message)
        if self._notify:
            message = message.replace("_", "\\_")
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【清理无效做种】",
                text=message,
            )
        logger.info("检测无效源文件任务结束")

    @staticmethod
    def get_size(path: Path):
        total_size = 0
        if path.is_file():
            return path.stat().st_size
        # rglob 方法用于递归遍历所有文件和目录
        for entry in path.rglob("*"):
            if entry.is_file():
                total_size += entry.stat().st_size
        return total_size

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
                                            "label": "开启通知",
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
                                            "model": "onlyonce",
                                            "label": "立即运行一次",
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
                                            "model": "delete_invalid_torrents",
                                            "label": "删除无效种子(确认无误后再开启)",
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
                                            "model": "detect_invalid_files",
                                            "label": "检测无效源文件",
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
                                            "model": "delete_invalid_files",
                                            "label": "删除无效源文件(确认无误后再开启)",
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
                                            "model": "notify_all",
                                            "label": "全量通知",
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
                                            "model": "label_only",
                                            "label": "仅标记模式(开启后不会删种)",
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
                                            "model": "more_logs",
                                            "label": "打印更多日志",
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
                                            'label': '请选择下载器',
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
                                            "model": "cron",
                                            "label": "执行周期",
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
                                            "model": "label",
                                            "label": "增加标签",
                                            "placeholder": "仅标记模式下生效，给待处理的种子打标签",
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
                                            "model": "download_dirs",
                                            "label": "下载目录映射",
                                            "rows": 2,
                                            "placeholder": "填写要监控的源文件目录，并设置MP和QB的目录映射关系，如/mp/download:/qb/download，多个目录请换行",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "props": {"style": {"margin-top": "0px"}},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_keywords",
                                            "label": "过滤删源文件关键字",
                                            "rows": 2,
                                            "placeholder": "多个关键字请换行，仅针对删除源文件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_categories",
                                            "label": "过滤删种分类",
                                            "rows": 2,
                                            "placeholder": "多个分类请换行，仅针对删除种子",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_labels",
                                            "label": "过滤删种标签",
                                            "rows": 2,
                                            "placeholder": "多个标签请换行，仅针对删除种子",
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
                                            "model": "custom_error_msg",
                                            "label": "自定义无效做种tracker错误信息",
                                            "rows": 5,
                                            "placeholder": "填入想要清理的种子的tracker错误信息，如'skipping tracker announce (unreachable)',多个信息请换行",
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
                                            "type": "error",
                                            "variant": "tonal",
                                            "text": "谨慎起见删除种子/源文件功能做了开关，请确认无误后再开启删除功能",
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
                                            "text": "下载目录映射填入源文件根目录，并设置MP和QB的目录映射关系。如某种子下载的源文件A存放路径为/qb/download/A，则目录映射填入/mp/download:/qb/download，多个目录请换行。注意映射目录不要有多余的'/'",
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
            "download_dirs": "",
            "delete_invalid_torrents": False,
            "delete_invalid_files": False,
            "detect_invalid_files": False,
            "notify_all": False,
            "onlyonce": False,
            "cron": "0 0 * * *",
            "label_only": False,
            "label": "",
            "more_logs": False,
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
