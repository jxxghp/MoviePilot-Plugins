import re
import threading
import time
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType, ServiceInfo
from app.utils.string import StringUtils

lock = threading.Lock()


class TorrentRemover(_PluginBase):
    # 插件名称
    plugin_name = "自动删种"
    # 插件描述
    plugin_desc = "自动删除下载器中的下载任务。"
    # 插件图标
    plugin_icon = "delete.jpg"
    # 插件版本
    plugin_version = "2.2"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "torrentremover_"
    # 加载顺序
    plugin_order = 8
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    downloader_helper = None
    _event = threading.Event()
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _notify = False
    # pause/delete
    _downloaders = []
    _action = "pause"
    _cron = None
    _samedata = False
    _mponly = False
    _size = None
    _ratio = None
    _time = None
    _upspeed = None
    _labels = None
    _pathkeywords = None
    _trackerkeywords = None
    _errorkeywords = None
    _torrentstates = None
    _torrentcategorys = None

    def init_plugin(self, config: dict = None):
        self.downloader_helper = DownloaderHelper()
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify")
            self._downloaders = config.get("downloaders") or []
            self._action = config.get("action")
            self._cron = config.get("cron")
            self._samedata = config.get("samedata")
            self._mponly = config.get("mponly")
            self._size = config.get("size") or ""
            self._ratio = config.get("ratio")
            self._time = config.get("time")
            self._upspeed = config.get("upspeed")
            self._labels = config.get("labels") or ""
            self._pathkeywords = config.get("pathkeywords") or ""
            self._trackerkeywords = config.get("trackerkeywords") or ""
            self._errorkeywords = config.get("errorkeywords") or ""
            self._torrentstates = config.get("torrentstates") or ""
            self._torrentcategorys = config.get("torrentcategorys") or ""

        self.stop_service()

        if self.get_state() or self._onlyonce:
            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"自动删种服务启动，立即运行一次")
                self._scheduler.add_job(func=self.delete_torrents, trigger='date',
                                        run_date=datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                                        )
                # 关闭一次性开关
                self._onlyonce = False
                # 保存设置
                self.update_config({
                    "enabled": self._enabled,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                    "action": self._action,
                    "cron": self._cron,
                    "downloaders": self._downloaders,
                    "samedata": self._samedata,
                    "mponly": self._mponly,
                    "size": self._size,
                    "ratio": self._ratio,
                    "time": self._time,
                    "upspeed": self._upspeed,
                    "labels": self._labels,
                    "pathkeywords": self._pathkeywords,
                    "trackerkeywords": self._trackerkeywords,
                    "errorkeywords": self._errorkeywords,
                    "torrentstates": self._torrentstates,
                    "torrentcategorys": self._torrentcategorys

                })
                if self._scheduler.get_jobs():
                    # 启动服务
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def get_state(self) -> bool:
        return True if self._enabled and self._cron and self._downloaders else False

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
        if self.get_state():
            return [{
                "id": "TorrentRemover",
                "name": "自动删种服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.delete_torrents,
                "kwargs": {}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '0 */12 * * *'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'action',
                                            'label': '动作',
                                            'items': [
                                                {'title': '暂停', 'value': 'pause'},
                                                {'title': '删除种子', 'value': 'delete'},
                                                {'title': '删除种子和文件', 'value': 'deletefile'}
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
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
                                                      for config in self.downloader_helper.get_configs().values()]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'size',
                                            'label': '种子大小（GB）',
                                            'placeholder': '例如1-10'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'ratio',
                                            'label': '分享率',
                                            'placeholder': ''
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'time',
                                            'label': '做种时间（小时）',
                                            'placeholder': ''
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'upspeed',
                                            'label': '平均上传速度',
                                            'placeholder': ''
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'labels',
                                            'label': '标签',
                                            'placeholder': '用,分隔多个标签'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pathkeywords',
                                            'label': '保存路径关键词',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'trackerkeywords',
                                            'label': 'Tracker关键词',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'errorkeywords',
                                            'label': '错误信息关键词（TR）',
                                            'placeholder': '支持正式表达式，仅适用于TR'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'torrentstates',
                                            'label': '任务状态（QB）',
                                            'placeholder': '用,分隔多个状态，仅适用于QB'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'torrentcategorys',
                                            'label': '任务分类',
                                            'placeholder': '用,分隔多个分类'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'samedata',
                                            'label': '处理辅种',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'mponly',
                                            'label': '仅MoviePilot任务',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
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
                                            'text': '自动删种存在风险，如设置不当可能导致数据丢失！建议动作先选择暂停，确定条件正确后再改成删除。'
                                        }
                                    }
                                ]
                            }
                        ]
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
                                            'text': '任务状态（QB）字典：'
                                                    'downloading：正在下载-传输数据，'
                                                    'stalledDL：正在下载_未建立连接，'
                                                    'uploading：正在上传-传输数据，'
                                                    'stalledUP：正在上传-未建立连接，'
                                                    'error：暂停-发生错误，'
                                                    'pausedDL：暂停-下载未完成，'
                                                    'pausedUP：暂停-下载完成，'
                                                    'missingFiles：暂停-文件丢失，'
                                                    'checkingDL：检查中-下载未完成，'
                                                    'checkingUP：检查中-下载完成，'
                                                    'checkingResumeData：检查中-启动时恢复数据，'
                                                    'forcedDL：强制下载-忽略队列，'
                                                    'queuedDL：等待下载-排队，'
                                                    'forcedUP：强制上传-忽略队列，'
                                                    'queuedUP：等待上传-排队，'
                                                    'allocating：分配磁盘空间，'
                                                    'metaDL：获取元数据，'
                                                    'moving：移动文件，'
                                                    'unknown：未知状态'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "action": 'pause',
            'downloaders': [],
            "cron": '0 */12 * * *',
            "samedata": False,
            "mponly": False,
            "size": "",
            "ratio": "",
            "time": "",
            "upspeed": "",
            "labels": "",
            "pathkeywords": "",
            "trackerkeywords": "",
            "errorkeywords": "",
            "torrentstates": "",
            "torrentcategorys": ""
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
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._downloaders:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        services = self.downloader_helper.get_services(name_filters=self._downloaders)
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    def __get_downloader(self, name: str):
        """
        根据类型返回下载器实例
        """
        return self.service_infos.get(name).instance

    def __get_downloader_config(self, name: str):
        """
        根据类型返回下载器实例配置
        """
        return self.service_infos.get(name).config

    def delete_torrents(self):
        """
        定时删除下载器中的下载任务
        """
        for downloader in self._downloaders:
            try:
                with lock:
                    # 获取需删除种子列表
                    torrents = self.get_remove_torrents(downloader)
                    logger.info(f"自动删种任务 获取符合处理条件种子数 {len(torrents)}")
                    # 下载器
                    downlader_obj = self.__get_downloader(downloader)
                    if self._action == "pause":
                        message_text = f"{downloader.title()} 共暂停{len(torrents)}个种子"
                        for torrent in torrents:
                            if self._event.is_set():
                                logger.info(f"自动删种服务停止")
                                return
                            text_item = f"{torrent.get('name')} " \
                                        f"来自站点：{torrent.get('site')} " \
                                        f"大小：{StringUtils.str_filesize(torrent.get('size'))}"
                            # 暂停种子
                            downlader_obj.stop_torrents(ids=[torrent.get("id")])
                            logger.info(f"自动删种任务 暂停种子：{text_item}")
                            message_text = f"{message_text}\n{text_item}"
                    elif self._action == "delete":
                        message_text = f"{downloader.title()} 共删除{len(torrents)}个种子"
                        for torrent in torrents:
                            if self._event.is_set():
                                logger.info(f"自动删种服务停止")
                                return
                            text_item = f"{torrent.get('name')} " \
                                        f"来自站点：{torrent.get('site')} " \
                                        f"大小：{StringUtils.str_filesize(torrent.get('size'))}"
                            # 删除种子
                            downlader_obj.delete_torrents(delete_file=False,
                                                          ids=[torrent.get("id")])
                            logger.info(f"自动删种任务 删除种子：{text_item}")
                            message_text = f"{message_text}\n{text_item}"
                    elif self._action == "deletefile":
                        message_text = f"{downloader.title()} 共删除{len(torrents)}个种子及文件"
                        for torrent in torrents:
                            if self._event.is_set():
                                logger.info(f"自动删种服务停止")
                                return
                            text_item = f"{torrent.get('name')} " \
                                        f"来自站点：{torrent.get('site')} " \
                                        f"大小：{StringUtils.str_filesize(torrent.get('size'))}"
                            # 删除种子
                            downlader_obj.delete_torrents(delete_file=True,
                                                          ids=[torrent.get("id")])
                            logger.info(f"自动删种任务 删除种子及文件：{text_item}")
                            message_text = f"{message_text}\n{text_item}"
                    else:
                        continue
                    if torrents and message_text and self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title=f"【自动删种任务完成】",
                            text=message_text
                        )
            except Exception as e:
                logger.error(f"自动删种任务异常：{str(e)}")

    def __get_qb_torrent(self, torrent: Any) -> Optional[dict]:
        """
        检查QB下载任务是否符合条件
        """
        # 完成时间
        date_done = torrent.completion_on if torrent.completion_on > 0 else torrent.added_on
        # 现在时间
        date_now = int(time.mktime(datetime.now().timetuple()))
        # 做种时间
        torrent_seeding_time = date_now - date_done if date_done else 0
        # 平均上传速度
        torrent_upload_avs = torrent.uploaded / torrent_seeding_time if torrent_seeding_time else 0
        # 大小 单位：GB
        sizes = self._size.split('-') if self._size else []
        minsize = float(sizes[0]) * 1024 * 1024 * 1024 if sizes else 0
        maxsize = float(sizes[-1]) * 1024 * 1024 * 1024 if sizes else 0
        # 分享率
        if self._ratio and torrent.ratio <= float(self._ratio):
            return None
        # 做种时间 单位：小时
        if self._time and torrent_seeding_time <= float(self._time) * 3600:
            return None
        # 文件大小
        if self._size and (torrent.size >= int(maxsize) or torrent.size <= int(minsize)):
            return None
        if self._upspeed and torrent_upload_avs >= float(self._upspeed) * 1024:
            return None
        if self._pathkeywords and not re.findall(self._pathkeywords, torrent.save_path, re.I):
            return None
        if self._trackerkeywords and not re.findall(self._trackerkeywords, torrent.tracker, re.I):
            return None
        if self._torrentstates and torrent.state not in self._torrentstates:
            return None
        if self._torrentcategorys and (not torrent.category or torrent.category not in self._torrentcategorys):
            return None
        return {
            "id": torrent.hash,
            "name": torrent.name,
            "site": StringUtils.get_url_sld(torrent.tracker),
            "size": torrent.size
        }

    def __get_tr_torrent(self, torrent: Any) -> Optional[dict]:
        """
        检查TR下载任务是否符合条件
        """
        # 完成时间
        date_done = torrent.date_done or torrent.date_added
        # 现在时间
        date_now = int(time.mktime(datetime.now().timetuple()))
        # 做种时间
        torrent_seeding_time = date_now - int(time.mktime(date_done.timetuple())) if date_done else 0
        # 上传量
        torrent_uploaded = torrent.ratio * torrent.total_size
        # 平均上传速茺
        torrent_upload_avs = torrent_uploaded / torrent_seeding_time if torrent_seeding_time else 0
        # 大小 单位：GB
        sizes = self._size.split('-') if self._size else []
        minsize = float(sizes[0]) * 1024 * 1024 * 1024 if sizes else 0
        maxsize = float(sizes[-1]) * 1024 * 1024 * 1024 if sizes else 0
        # 分享率
        if self._ratio and torrent.ratio <= float(self._ratio):
            return None
        if self._time and torrent_seeding_time <= float(self._time) * 3600:
            return None
        if self._size and (torrent.total_size >= int(maxsize) or torrent.total_size <= int(minsize)):
            return None
        if self._upspeed and torrent_upload_avs >= float(self._upspeed) * 1024:
            return None
        if self._pathkeywords and not re.findall(self._pathkeywords, torrent.download_dir, re.I):
            return None
        if self._trackerkeywords:
            if not torrent.trackers:
                return None
            else:
                tacker_key_flag = False
                for tracker in torrent.trackers:
                    if re.findall(self._trackerkeywords, tracker.get("announce", ""), re.I):
                        tacker_key_flag = True
                        break
                if not tacker_key_flag:
                    return None
        if self._errorkeywords and not re.findall(self._errorkeywords, torrent.error_string, re.I):
            return None
        return {
            "id": torrent.hashString,
            "name": torrent.name,
            "site": torrent.trackers[0].get("sitename") if torrent.trackers else "",
            "size": torrent.total_size
        }

    def get_remove_torrents(self, downloader: str):
        """
        获取自动删种任务种子
        """
        remove_torrents = []
        # 下载器对象
        downloader_obj = self.__get_downloader(downloader)
        downloader_config = self.__get_downloader_config(downloader)
        # 标题
        if self._labels:
            tags = self._labels.split(',')
        else:
            tags = []
        if self._mponly:
            tags.append(settings.TORRENT_TAG)
        # 查询种子
        torrents, error_flag = downloader_obj.get_torrents(tags=tags or None)
        if error_flag:
            return []
        # 处理种子
        for torrent in torrents:
            if downloader_config.type == "qbittorrent":
                item = self.__get_qb_torrent(torrent)
            else:
                item = self.__get_tr_torrent(torrent)
            if not item:
                continue
            remove_torrents.append(item)
        # 处理辅种
        if self._samedata and remove_torrents:
            remove_ids = [t.get("id") for t in remove_torrents]
            remove_torrents_plus = []
            for remove_torrent in remove_torrents:
                name = remove_torrent.get("name")
                size = remove_torrent.get("size")
                for torrent in torrents:
                    if downloader_config.type == "qbittorrent":
                        plus_id = torrent.hash
                        plus_name = torrent.name
                        plus_size = torrent.size
                        plus_site = StringUtils.get_url_sld(torrent.tracker)
                    else:
                        plus_id = torrent.hashString
                        plus_name = torrent.name
                        plus_size = torrent.total_size
                        plus_site = torrent.trackers[0].get("sitename") if torrent.trackers else ""
                    # 比对名称和大小
                    if plus_name == name \
                            and plus_size == size \
                            and plus_id not in remove_ids:
                        remove_torrents_plus.append(
                            {
                                "id": plus_id,
                                "name": plus_name,
                                "site": plus_site,
                                "size": plus_size
                            }
                        )
            if remove_torrents_plus:
                remove_torrents.extend(remove_torrents_plus)
        return remove_torrents
