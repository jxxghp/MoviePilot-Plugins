import os
import re
from datetime import datetime, timedelta
from threading import Event
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.core.event import eventmanager
from app.db.site_oper import SiteOper
from app.helper.downloader import DownloaderHelper
from app.helper.sites import SitesHelper
from app.helper.torrent import TorrentHelper
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.iyuuautoseed.iyuu_helper import IyuuHelper
from app.schemas import NotificationType, ServiceInfo
from app.schemas.types import EventType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class IYUUAutoSeed(_PluginBase):
    # 插件名称
    plugin_name = "IYUU自动辅种"
    # 插件描述
    plugin_desc = "基于IYUU官方Api实现自动辅种。"
    # 插件图标
    plugin_icon = "IYUU.png"
    # 插件版本
    plugin_version = "2.14"
    # 插件作者
    plugin_author = "jxxghp,CKun"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "iyuuautoseed_"
    # 加载顺序
    plugin_order = 17
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _scheduler = None
    iyuu_helper = None
    # 开关
    _enabled = False
    _cron = None
    _skipverify = False
    _onlyonce = False
    _token = None
    _downloaders = []
    # 辅种下载器
    _auto_downloader = None
    # 自动分类
    _auto_category = False
    _sites = []
    _notify = False
    _nolabels = None
    _nopaths = None
    _labelsafterseed = None
    _categoryafterseed = None
    _addhosttotag = False
    _size = None
    _clearcache = False
    _auto_start = False
    # 退出事件
    _event = Event()
    # 种子链接xpaths
    _torrent_xpaths = [
        "//form[contains(@action, 'download.php?id=')]/@action",
        "//a[contains(@href, 'download.php?hash=')]/@href",
        "//a[contains(@href, 'download.php?id=')]/@href",
        "//a[@class='index'][contains(@href, '/dl/')]/@href",
    ]
    # 待校全种子hash清单
    _recheck_torrents = {}
    _is_recheck_running = False
    # 辅种缓存，出错的种子不再重复辅种，可清除
    _error_caches = []
    # 辅种缓存，辅种成功的种子，可清除
    _success_caches = []
    # 辅种缓存，出错的种子不再重复辅种，且无法清除。种子被删除404等情况
    _permanent_error_caches = []
    # 辅种计数
    total = 0
    realtotal = 0
    success = 0
    exist = 0
    fail = 0
    cached = 0

    def init_plugin(self, config: dict = None):

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._skipverify = config.get("skipverify")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._token = config.get("token")
            self._downloaders = config.get("downloaders")
            self._auto_downloader = config.get("auto_downloader")
            self._sites = config.get("sites") or []
            self._notify = config.get("notify")
            self._nolabels = config.get("nolabels")
            self._nopaths = config.get("nopaths")
            self._labelsafterseed = config.get("labelsafterseed") if config.get("labelsafterseed") else "已整理,辅种"
            self._categoryafterseed = config.get("categoryafterseed")
            self._auto_category = config.get("auto_category")
            self._auto_start = config.get("auto_start")
            self._addhosttotag = config.get("addhosttotag")
            self._size = float(config.get("size")) if config.get("size") else 0
            self._clearcache = config.get("clearcache")
            self._permanent_error_caches = [] if self._clearcache else config.get("permanent_error_caches") or []
            self._error_caches = [] if self._clearcache else config.get("error_caches") or []
            self._success_caches = [] if self._clearcache else config.get("success_caches") or []

            # 过滤掉已删除的站点
            all_sites = [site.id for site in SiteOper().list_order_by_pri()] + [site.get("id") for site in
                                                                                self.__custom_sites()]
            self._sites = [site_id for site_id in all_sites if site_id in self._sites]
            self.__update_config()

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self.get_state() or self._onlyonce:
            self.iyuu_helper = IyuuHelper(token=self._token)
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            if self._onlyonce:
                logger.info(f"辅种服务启动，立即运行一次")
                self._scheduler.add_job(self.auto_seed, 'date',
                                        run_date=datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                                        )
                # 关闭一次性开关
                self._onlyonce = False

            if self._clearcache:
                # 关闭清除缓存开关
                self._clearcache = False
            # 保存配置
            self.__update_config()

            # 追加种子校验服务
            self._scheduler.add_job(self.check_recheck, 'interval', minutes=3)
            # 启动服务
            self._scheduler.print_jobs()
            self._scheduler.start()

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
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
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    @property
    def auto_service_info(self) -> ServiceInfo | None:
        """
        服务信息
        """
        if not self._auto_downloader:
            logger.debug("尚未配置主辅分离下载器，辅种不分离")
            return None

        service = DownloaderHelper().get_service(name=self._auto_downloader)
        if not service:
            logger.warning("获取主辅分离下载器实例失败，请检查配置")
            return None

        if service.instance.is_inactive():
            logger.warning(f"下载器 {service.name} 未连接，请检查配置")
            return None
        return service

    def get_state(self) -> bool:
        return True if self._enabled and self._cron and self._token and self._downloaders else False

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
                "id": "IYUUAutoSeed",
                "name": "IYUU自动辅种服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.auto_seed,
                "kwargs": {}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 站点的可选项（内置站点 + 自定义站点）
        customSites = self.__custom_sites()

        # 站点的可选项
        site_options = ([{"title": site.name, "value": site.id}
                         for site in SiteOper().list_order_by_pri()]
                        + [{"title": site.get("name"), "value": site.get("id")}
                           for site in customSites])
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
                                    'md': 3
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
                                    'md': 3
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
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clearcache',
                                            'label': '清除缓存后运行',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'token',
                                            'label': 'IYUU Token',
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
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '0 0 0 ? *'
                                        }
                                    }
                                ]
                            },
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
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in DownloaderHelper().get_configs().values()]
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
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'auto_downloader',
                                            'label': '主辅分离',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in DownloaderHelper().get_configs().values()]
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'size',
                                            'label': '辅种体积大于(GB)',
                                            'placeholder': '只有大于该值的才辅种'
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
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'sites',
                                            'label': '辅种站点',
                                            'items': site_options
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'nolabels',
                                            'label': '不辅种标签',
                                            'placeholder': '使用,分隔多个标签'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'labelsafterseed',
                                            'label': '辅种后增加标签',
                                            'placeholder': '使用,分隔多个标签,不填写则默认为(已整理,辅种)'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'categoryafterseed',
                                            'label': '辅种后增加分类',
                                            'placeholder': '设置辅种的种子分类'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'nopaths',
                                            'label': '不辅种数据文件目录',
                                            'rows': 3,
                                            'placeholder': '每一行一个目录'
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
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'addhosttotag',
                                            'label': '将站点名添加到标签中',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'skipverify',
                                            'label': '跳过校验(仅QB有效)',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'auto_start',
                                            'label': '自动开始(跳过校验有效)',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'auto_category',
                                            'label': '分类复用(仅QB有效)',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {
                            'style': {
                                'margin-top': '12px'
                            },
                        },
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
                                            'type': 'error',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                                'component': 'span',
                                                'text': '注意：详细配置说明和注意事项请参考：'
                                            },
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': 'https://github.com/jxxghp/MoviePilot-Plugins/tree/main/plugins.v2/iyuuautoseed/README.md',
                                                    'target': '_blank'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'u',
                                                        'text': 'README'
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "skipverify": False,
            "onlyonce": False,
            "notify": False,
            "clearcache": False,
            "addhosttotag": False,
            "auto_category": False,
            "auto_start": False,
            "cron": "",
            "token": "",
            "downloaders": [],
            "auto_downloader": "",
            "sites": [],
            "nopaths": "",
            "nolabels": "",
            "labelsafterseed": "",
            "categoryafterseed": "",
            "size": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "skipverify": self._skipverify,
            "onlyonce": self._onlyonce,
            "clearcache": self._clearcache,
            "cron": self._cron,
            "token": self._token,
            "downloaders": self._downloaders,
            "auto_downloader": self._auto_downloader,
            "sites": self._sites,
            "notify": self._notify,
            "nolabels": self._nolabels,
            "nopaths": self._nopaths,
            "labelsafterseed": self._labelsafterseed,
            "categoryafterseed": self._categoryafterseed,
            "addhosttotag": self._addhosttotag,
            "auto_category": self._auto_category,
            "auto_start": self._auto_start,
            "size": self._size,
            "success_caches": self._success_caches,
            "error_caches": self._error_caches,
            "permanent_error_caches": self._permanent_error_caches
        })

    def auto_seed(self):
        """
        开始辅种
        """
        if not self.iyuu_helper or not self.service_infos:
            return
        logger.info("开始辅种任务 ...")

        # 计数器初始化
        self.total = 0
        self.realtotal = 0
        self.success = 0
        self.exist = 0
        self.fail = 0
        self.cached = 0
        # 扫描下载器辅种
        for service in self.service_infos.values():
            downloader = service.name
            downloader_obj = service.instance
            logger.info(f"开始扫描下载器 {downloader} ...")
            # 获取下载器中已完成的种子
            torrents = downloader_obj.get_completed_torrents()
            if torrents:
                logger.info(f"下载器 {downloader} 已完成种子数：{len(torrents)}")
            else:
                logger.info(f"下载器 {downloader} 没有已完成种子")
                continue
            hash_strs = []
            for torrent in torrents:
                if self._event.is_set():
                    logger.info(f"辅种服务停止")
                    return
                # 获取种子hash
                hash_str = self.__get_hash(torrent=torrent, dl_type=service.type)
                if hash_str in self._error_caches or hash_str in self._permanent_error_caches:
                    logger.info(f"种子 {hash_str} 辅种失败且已缓存，跳过 ...")
                    continue
                save_path = self.__get_save_path(torrent=torrent, dl_type=service.type)

                if self._nopaths and save_path:
                    # 过滤不需要转移的路径
                    nopath_skip = False
                    for nopath in self._nopaths.split('\n'):
                        if os.path.normpath(save_path).startswith(os.path.normpath(nopath)):
                            logger.info(f"种子 {hash_str} 保存路径 {save_path} 不需要辅种，跳过 ...")
                            nopath_skip = True
                            break
                    if nopath_skip:
                        continue

                # 获取种子标签
                torrent_labels = self.__get_label(torrent=torrent, dl_type=service.type)
                if torrent_labels and self._nolabels:
                    is_skip = False
                    for label in self._nolabels.split(','):
                        if label in torrent_labels:
                            logger.info(f"种子 {hash_str} 含有不辅种标签 {label}，跳过 ...")
                            is_skip = True
                            break
                    if is_skip:
                        continue
                # 体积排除辅种
                torrent_size = self.__get_torrent_size(torrent=torrent, dl_type=service.type) / 1024 / 1024 / 1024
                if self._size and torrent_size < self._size:
                    logger.info(f"种子 {hash_str} 大小:{torrent_size:.2f}GB，小于设定 {self._size}GB，跳过 ...")
                    continue
                category = self.__get_category(torrent=torrent, dl_type=service.type) if self._auto_category else None
                hash_strs.append({
                    "hash": hash_str,
                    "save_path": save_path,
                    "category": category or self._categoryafterseed
                })
            if hash_strs:
                logger.info(f"总共需要辅种的种子数：{len(hash_strs)}")
                # 分组处理，减少IYUU Api请求次数
                chunk_size = 200
                for i in range(0, len(hash_strs), chunk_size):
                    # 切片操作
                    chunk = hash_strs[i:i + chunk_size]
                    # 处理分组
                    self.__seed_torrents(hash_strs=chunk,
                                         service=service)
                # 触发校验检查
                self.check_recheck()
            else:
                logger.info(f"没有需要辅种的种子")

        # 保存缓存
        self.__update_config()
        # 发送消息
        if self._notify:
            if self.success or self.fail:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title="【IYUU自动辅种任务完成】",
                    text=f"服务器返回可辅种总数：{self.total}\n"
                         f"实际可辅种数：{self.realtotal}\n"
                         f"已存在：{self.exist}\n"
                         f"成功：{self.success}\n"
                         f"失败：{self.fail}\n"
                         f"{self.cached} 条失败记录已加入缓存"
                )
        logger.info("辅种任务执行完成")

    def check_recheck(self):
        """
        定时检查下载器中种子是否校验完成，校验完成且完整的自动开始辅种
        """
        if not self._recheck_torrents:
            return
        if self._is_recheck_running:
            return
        self._is_recheck_running = True
        if self.auto_service_info:
            # 检查指定下载器
            self.check_recheck_service(self.auto_service_info)
            self._is_recheck_running = False
            return
        if not self.service_infos:
            return
        for service in self.service_infos.values():
            # 需要检查的种子
            self.check_recheck_service(service)
        self._is_recheck_running = False

    def check_recheck_service(self, service: ServiceInfo):
        """
        检查指定下载器中种子是否校验完成，校验完成且完整的自动开始辅种
        """
        # 需要检查的种子
        downloader = service.name
        downloader_obj = service.instance
        recheck_torrents = self._recheck_torrents.get(downloader) or []
        if not recheck_torrents:
            return
        logger.info(f"开始检查下载器 {downloader} 的校验任务 ...")
        # 获取下载器中的种子状态
        torrents, _ = downloader_obj.get_torrents(ids=recheck_torrents)
        if torrents:
            can_seeding_torrents = []
            for torrent in torrents:
                # 获取种子hash
                hash_str = self.__get_hash(torrent=torrent, dl_type=service.type)
                if self.__can_seeding(torrent=torrent, dl_type=service.type):
                    can_seeding_torrents.append(hash_str)
            if can_seeding_torrents:
                logger.info(f"共 {len(can_seeding_torrents)} 个任务校验完成，开始辅种 ...")
                # 开始任务
                downloader_obj.start_torrents(ids=can_seeding_torrents)
                # 去除已经处理过的种子
                self._recheck_torrents[downloader] = list(
                    set(recheck_torrents).difference(set(can_seeding_torrents)))
        elif torrents is None:
            logger.info(f"下载器 {downloader} 查询校验任务失败，将在下次继续查询 ...")
            return
        else:
            logger.info(f"下载器 {downloader} 中没有需要检查的校验任务，清空待处理列表 ...")
            self._recheck_torrents[downloader] = []

    def __seed_torrents(self, hash_strs: list, service: ServiceInfo):
        """
        执行一批种子的辅种
        """
        if not hash_strs:
            return
        logger.info(f"下载器 {service.name} 开始查询辅种，数量：{len(hash_strs)} ...")
        # 下载器中的Hashs
        hashs = [item.get("hash") for item in hash_strs]
        # 每个Hash的保存目录
        save_paths = {}
        save_category = {}
        for item in hash_strs:
            save_paths[item.get("hash")] = item.get("save_path")
            save_category[item.get("hash")] = item.get("category")
        # 查询可辅种数据
        seed_list, msg = self.iyuu_helper.get_seed_info(hashs)
        if not isinstance(seed_list, dict):
            # 判断辅种异常是否是由于Token未认证导致的，由于没有解决接口，只能从返回值来判断
            if self._token and msg == '请求缺少token':
                logger.warn(f'IYUU辅种失败，疑似站点未绑定插件配置不完整，请先检查是否完成站点绑定！{msg}')
            else:
                logger.warn(f"当前种子列表没有可辅种的站点：{msg}")
            return
        else:
            logger.info(f"IYUU返回可辅种数：{len(seed_list)}")
        # 遍历
        for current_hash, seed_info in seed_list.items():
            if not seed_info:
                continue
            seed_torrents = seed_info.get("torrent")
            if not isinstance(seed_torrents, list):
                seed_torrents = [seed_torrents]

            # 本次辅种成功的种子
            success_torrents = []

            for seed in seed_torrents:
                if not seed:
                    continue
                if not isinstance(seed, dict):
                    continue
                if not seed.get("sid") or not seed.get("info_hash"):
                    continue
                if seed.get("info_hash") in hashs:
                    logger.info(f"{seed.get('info_hash')} 已在下载器中，跳过 ...")
                    continue
                if seed.get("info_hash") in self._success_caches:
                    logger.info(f"{seed.get('info_hash')} 已处理过辅种，跳过 ...")
                    continue
                if seed.get("info_hash") in self._error_caches or seed.get("info_hash") in self._permanent_error_caches:
                    logger.info(f"种子 {seed.get('info_hash')} 辅种失败且已缓存，跳过 ...")
                    continue
                # 添加任务 如果配置了主辅分离使用辅种下载器
                if self._auto_downloader:
                    success = self.__download_torrent(seed=seed,
                                                      service=self.auto_service_info,
                                                      save_path=save_paths.get(current_hash),
                                                      save_category=save_category.get(current_hash))
                else:
                    success = self.__download_torrent(seed=seed,
                                                      service=service,
                                                      save_path=save_paths.get(current_hash),
                                                      save_category=save_category.get(current_hash))
                if success:
                    success_torrents.append(seed.get("info_hash"))

            # 辅种成功的去重放入历史
            if len(success_torrents) > 0:
                self.__save_history(current_hash=current_hash,
                                    downloader=service.name,
                                    success_torrents=success_torrents)

        logger.info(f"下载器 {service.name} 辅种完成")

    def __save_history(self, current_hash: str, downloader: str, success_torrents: []):
        """
        [
            {
                "downloader":"2",
                "torrents":[
                    "248103a801762a66c201f39df7ea325f8eda521b",
                    "bd13835c16a5865b01490962a90b3ec48889c1f0"
                ]
            },
            {
                "downloader":"3",
                "torrents":[
                    "248103a801762a66c201f39df7ea325f8eda521b",
                    "bd13835c16a5865b01490962a90b3ec48889c1f0"
                ]
            }
        ]
        """
        try:
            # 查询当前Hash的辅种历史
            seed_history = self.get_data(key=current_hash) or []

            new_history = True
            if len(seed_history) > 0:
                for history in seed_history:
                    if not history:
                        continue
                    if not isinstance(history, dict):
                        continue
                    if not history.get("downloader"):
                        continue
                    # 如果本次辅种下载器之前有过记录则继续添加
                    if str(history.get("downloader")) == downloader:
                        history_torrents = history.get("torrents") or []
                        history["torrents"] = list(set(history_torrents + success_torrents))
                        new_history = False
                        break

            # 本次辅种下载器之前没有成功记录则新增
            if new_history:
                seed_history.append({
                    "downloader": downloader,
                    "torrents": list(set(success_torrents))
                })

            # 保存历史
            self.save_data(key=current_hash,
                           value=seed_history)
        except Exception as e:
            print(str(e))

    def __download(self, service: ServiceInfo, content: bytes,
                   save_path: str, save_category: str, site_name: str) -> Optional[str]:

        torrent_tags = self._labelsafterseed.split(',')

        # 辅种 tag 叠加站点名
        if self._addhosttotag:
            torrent_tags.append(site_name)

        """
        添加下载任务
        """
        if service.type == "qbittorrent":
            # 生成随机Tag
            tag = StringUtils.generate_random_str(10)

            torrent_tags.append(tag)

            state = service.instance.add_torrent(content=content,
                                                 download_dir=save_path,
                                                 is_paused=True,
                                                 tag=torrent_tags,
                                                 category=save_category,
                                                 is_skip_checking=self._skipverify)
            if not state:
                return None
            else:
                # 获取种子Hash
                torrent_hash = service.instance.get_torrent_id_by_tag(tags=tag)
                if not torrent_hash:
                    logger.error(f"{service.name} 下载任务添加成功，但获取任务信息失败！")
                    return None
            return torrent_hash
        elif service.type == "transmission":
            # 添加任务
            torrent = service.instance.add_torrent(content=content,
                                                   download_dir=save_path,
                                                   is_paused=True,
                                                   labels=torrent_tags)
            if not torrent:
                return None
            else:
                return torrent.hashString

        logger.error(f"不支持的下载器：{service.type}")
        return None

    def __download_torrent(self, seed: dict, service: ServiceInfo, save_path: str, save_category: str):
        """
        下载种子
        torrent: {
                    "sid": 3,
                    "torrent_id": 377467,
                    "info_hash": "a444850638e7a6f6220e2efdde94099c53358159"
                }
        """

        def __is_special_site(url):
            """
            判断是否为特殊站点（是否需要添加https）
            """
            if "hdsky.me" in url:
                return False
            return True

        self.total += 1
        # 获取种子站点及下载地址模板
        site_url, download_page = self.iyuu_helper.get_torrent_url(seed.get("sid"))
        if not site_url or not download_page:
            # 加入缓存
            self._error_caches.append(seed.get("info_hash"))
            self.fail += 1
            self.cached += 1
            return False
        # 查询站点
        site_domain = StringUtils.get_url_domain(site_url)
        # 站点信息
        sites_helper = SitesHelper()
        site_info = sites_helper.get_indexer(site_domain)
        if not site_info or not site_info.get('url'):
            logger.debug(f"没有维护种子对应的站点：{site_url}")
            return False
        if self._sites and site_info.get('id') not in self._sites:
            logger.info("当前站点不在选择的辅种站点范围，跳过 ...")
            return False
        self.realtotal += 1
        # 查询hash值是否已经在下载器中
        downloader_obj = service.instance
        torrent_info, _ = downloader_obj.get_torrents(ids=[seed.get("info_hash")])
        if torrent_info:
            logger.info(f"{seed.get('info_hash')} 已在下载器中，跳过 ...")
            self.exist += 1
            return False
        # 站点流控
        check, checkmsg = sites_helper.check(site_domain)
        if check:
            logger.warn(checkmsg)
            self.fail += 1
            return False
        # 下载种子
        torrent_url = self.__get_download_url(seed=seed,
                                              site=site_info,
                                              base_url=download_page)
        if not torrent_url:
            # 加入失败缓存
            self._error_caches.append(seed.get("info_hash"))
            self.fail += 1
            self.cached += 1
            return False
        # 强制使用Https
        if __is_special_site(torrent_url):
            if "?" in torrent_url:
                torrent_url += "&https=1"
            else:
                torrent_url += "?https=1"
        # 下载种子文件
        _, content, _, _, error_msg = TorrentHelper().download_torrent(
            url=torrent_url,
            cookie=site_info.get("cookie"),
            ua=site_info.get("ua") or settings.USER_AGENT,
            proxy=site_info.get("proxy"))
        if not content:
            # 下载失败
            self.fail += 1
            # 加入失败缓存
            if error_msg and ('无法打开链接' in error_msg or '触发站点流控' in error_msg):
                self._error_caches.append(seed.get("info_hash"))
            else:
                # 种子不存在的情况
                self._permanent_error_caches.append(seed.get("info_hash"))
            logger.error(f"下载种子文件失败：{torrent_url}")
            return False
        # 添加下载，辅种任务默认暂停
        logger.info(f"添加下载任务：{torrent_url} ...")
        download_id = self.__download(service=service,
                                      content=content,
                                      save_path=save_path,
                                      save_category=save_category,
                                      site_name=site_info.get("name"))
        if not download_id:
            # 下载失败
            self.fail += 1
            # 加入失败缓存
            self._error_caches.append(seed.get("info_hash"))
            return False
        else:
            self.success += 1
            if service.type == "qbittorrent":
                if self._skipverify:
                    if self._auto_start:
                        logger.info(f"{download_id} 跳过校验，开启自动开始，注意观察种子的完整性")
                        self.__add_recheck_torrents(service, download_id)
                    else:
                        # 跳过校验
                        logger.info(f"{download_id} 跳过校验，请自行检查手动开始任务...")
                else:
                    # 开始校验种子
                    downloader_obj.recheck_torrents(ids=[download_id])
                    self.__add_recheck_torrents(service, download_id)
            else:
                self.__add_recheck_torrents(service, download_id)
            # 下载成功
            logger.info(f"成功添加辅种下载，站点：{site_info.get('name')}，种子链接：{torrent_url}")
            # 成功也加入缓存，有一些改了路径校验不通过的，手动删除后，下一次又会辅上
            self._success_caches.append(seed.get("info_hash"))
            return True

    def __add_recheck_torrents(self, service: ServiceInfo, download_id: str):
        # 追加校验任务
        logger.info(f"添加校验检查任务：{download_id} ...")
        if not self._recheck_torrents.get(service.name):
            self._recheck_torrents[service.name] = []
        self._recheck_torrents[service.name].append(download_id)

    @staticmethod
    def __get_hash(torrent: Any, dl_type: str):
        """
        获取种子hash
        """
        try:
            return torrent.get("hash") if dl_type == "qbittorrent" else torrent.hashString
        except Exception as e:
            print(str(e))
            return ""

    @staticmethod
    def __get_label(torrent: Any, dl_type: str):
        """
        获取种子标签
        """
        try:
            return [str(tag).strip() for tag in torrent.get("tags").split(',')] \
                if dl_type == "qbittorrent" else torrent.labels or []
        except Exception as e:
            print(str(e))
            return []

    @staticmethod
    def __get_category(torrent: Any, dl_type: str):
        """
        获取种子分类
        """
        try:
            return torrent.get("category") if dl_type == "qbittorrent" else None
        except Exception as e:
            print(str(e))
            return []

    @staticmethod
    def __can_seeding(torrent: Any, dl_type: str):
        """
        判断种子是否可以做种并处于暂停状态
        """
        try:
            return torrent.get("state") in ["pausedUP", "stoppedUP"] if dl_type == "qbittorrent" \
                else (torrent.status.stopped and torrent.percent_done == 1)
        except Exception as e:
            print(str(e))
            return False

    @staticmethod
    def __get_save_path(torrent: Any, dl_type: str):
        """
        获取种子保存路径
        """
        try:
            return torrent.get("save_path") if dl_type == "qbittorrent" else torrent.download_dir
        except Exception as e:
            print(str(e))
            return ""

    @staticmethod
    def __get_torrent_size(torrent: Any, dl_type: str):
        """
        获取种子大小 int bytes
        """
        try:
            return torrent.get("total_size") if dl_type == "qbittorrent" else torrent.total_size
        except Exception as e:
            print(str(e))
            return ""

    def __get_download_url(self, seed: dict, site: CommentedMap, base_url: str):
        """
        拼装种子下载链接
        """

        def __is_mteam(url: str):
            """
            判断是否为mteam站点
            """
            return True if "m-team." in url else False

        def __is_monika(url: str):
            """
            判断是否为monika站点
            """
            return True if "monikadesign." in url else False

        def __get_mteam_enclosure(tid: str, apikey: str):
            """
            获取mteam种子下载链接
            """
            if not apikey:
                logger.error("m-team站点的apikey未配置")
                return None

            """
            将mteam种子下载链接域名替换为使用API
            """
            api_url = re.sub(r'//[^/]+\.m-team', '//api.m-team', site.get('url'))
            ua = site.get("ua") or settings.USER_AGENT
            res = RequestUtils(
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'User-Agent': f'{ua}',
                    'Accept': 'application/json, text/plain, */*',
                    'x-api-key': apikey
                }
            ).post_res(f"{api_url}api/torrent/genDlToken", params={
                'id': tid
            })
            if not res:
                logger.warn(f"m-team 获取种子下载链接失败：{tid}")
                return None
            return res.json().get("data")

        def __get_monika_torrent(tid: str, rssurl: str):
            """
            Monika下载需要使用rsskey从站点配置中获取并拼接下载链接
            """
            if not rssurl:
                logger.error("Monika站点的rss链接未配置")
                return None

            rss_match = re.search(r'/rss/\d+\.(\w+)', rssurl)
            rsskey = rss_match.group(1)
            return f"{site.get('url')}torrents/download/{tid}.{rsskey}"

        def __is_special_site(url: str):
            """
            判断是否为特殊站点
            """
            spec_params = ["hash=", "authkey="]
            if any(field in base_url for field in spec_params):
                return True
            if "hdchina.org" in url:
                return True
            if "hdsky.me" in url:
                return True
            if "hdcity.in" in url:
                return True
            if "totheglory.im" in url:
                return True
            return False

        try:
            if __is_mteam(site.get('url')):
                # 调用mteam接口获取下载链接
                return __get_mteam_enclosure(tid=seed.get("torrent_id"), apikey=site.get("apikey"))
            if __is_monika(site.get('url')):
                # 返回种子id和站点配置中所Monika的rss链接
                return __get_monika_torrent(tid=seed.get("torrent_id"), rssurl=site.get("rss"))
            elif __is_special_site(site.get('url')):
                # 从详情页面获取下载链接
                return self.__get_torrent_url_from_page(seed=seed, site=site)
            else:
                download_url = base_url.replace(
                    "id={}",
                    "id={id}"
                ).replace(
                    "/{}",
                    "/{id}"
                ).replace(
                    "/{torrent_key}",
                    ""
                ).format(
                    **{
                        "id": seed.get("torrent_id"),
                        "passkey": site.get("passkey") or '',
                        "uid": site.get("uid") or '',
                    }
                )
                if download_url.count("{"):
                    logger.warn(f"当前不支持该站点的辅助任务，Url转换失败：{seed}")
                    return None
                download_url = re.sub(r"[&?]passkey=", "",
                                      re.sub(r"[&?]uid=", "",
                                             download_url,
                                             flags=re.IGNORECASE),
                                      flags=re.IGNORECASE)
                return f"{site.get('url')}{download_url}"
        except Exception as e:
            logger.warn(
                f"{site.get('name')} Url转换失败，{str(e)}：site_url={site.get('url')}，base_url={base_url}, seed={seed}")
            return self.__get_torrent_url_from_page(seed=seed, site=site)

    def __get_torrent_url_from_page(self, seed: dict, site: dict):
        """
        从详情页面获取下载链接
        """
        if not site.get('url'):
            logger.warn(f"站点 {site.get('name')} 未获取站点地址，无法获取种子下载链接")
            return None
        try:
            page_url = f"{site.get('url')}details.php?id={seed.get('torrent_id')}&hit=1"
            logger.info(f"正在获取种子下载链接：{page_url} ...")
            res = RequestUtils(
                cookies=site.get("cookie"),
                ua=site.get("ua") or settings.USER_AGENT,
                proxies=settings.PROXY if site.get("proxy") else None
            ).get_res(url=page_url)
            if res is not None and res.status_code in (200, 500):
                if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                    res.encoding = "UTF-8"
                else:
                    res.encoding = res.apparent_encoding
                if not res.text:
                    logger.warn(f"获取种子下载链接失败，页面内容为空：{page_url}")
                    return None
                # 使用xpath从页面中获取下载链接
                html = etree.HTML(res.text)
                for xpath in self._torrent_xpaths:
                    download_url = html.xpath(xpath)
                    if download_url:
                        download_url = download_url[0]
                        logger.info(f"获取种子下载链接成功：{download_url}")
                        if not download_url.startswith("http"):
                            if download_url.startswith("/"):
                                download_url = f"{site.get('url')}{download_url[1:]}"
                            else:
                                download_url = f"{site.get('url')}{download_url}"
                        return download_url
                logger.warn(f"获取种子下载链接失败，未找到下载链接：{page_url}")
                return None
            else:
                logger.error(f"获取种子下载链接失败，请求失败：{page_url}，{res.status_code if res else ''}")
                return None
        except Exception as e:
            logger.warn(f"获取种子下载链接失败：{str(e)}")
            return None

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

    def __custom_sites(self) -> List[Any]:
        custom_sites = []
        custom_sites_config = self.get_config("CustomSites")
        if custom_sites_config and custom_sites_config.get("enabled"):
            custom_sites = custom_sites_config.get("sites")
        return custom_sites

    @eventmanager.register(EventType.SiteDeleted)
    def site_deleted(self, event):
        """
        删除对应站点选中
        """
        site_id = event.event_data.get("site_id")
        config = self.get_config()
        if config:
            sites = config.get("sites")
            if sites:
                if isinstance(sites, str):
                    sites = [sites]

                # 删除对应站点
                if site_id:
                    sites = [site for site in sites if int(site) != int(site_id)]
                else:
                    # 清空
                    sites = []

                # 若无站点，则停止
                if len(sites) == 0:
                    self._enabled = False

                self._sites = sites
                # 保存配置
                self.__update_config()
