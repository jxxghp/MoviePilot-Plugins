import os
import re
from datetime import datetime, timedelta
from threading import Event
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

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

try:
    from app.domain.site import resolve_site_user_agent as _resolve_site_user_agent
except ImportError:  # 旧宿主无统一解析函数
    def _resolve_site_user_agent(site_ua, configured_ua, default_ua):
        ua = site_ua.strip() if isinstance(site_ua, str) else ""
        return ua or (configured_ua or "").strip() or default_ua


class IYUUAutoSeed(_PluginBase):
    # 插件名称
    plugin_name = "IYUU自动辅种"
    # 插件描述
    plugin_desc = "基于IYUU官方Api实现自动辅种。"
    # 插件图标
    plugin_icon = "IYUU.png"
    # 插件版本
    plugin_version = "2.27"
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
    # 站点用户ID缓存，按域名索引，取种需要
    _site_user_ids = {}
    # 已扫描种子的名称，按 info_hash 索引
    _hash_names = {}
    # 站点 RSS 的 rsskey 缓存，按域名索引
    _rss_keys = {}
    # 各站点可用的 API 端点，按域名索引；本次任务内失败的记为空，避免逐个种子重复试探
    _api_bases = {}
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
    # 已自动补发校验的种子hash，避免重复补发
    _auto_rechecked = set()
    # 辅种缓存，出错的种子不再重复辅种，可清除
    _error_caches = []
    # 辅种缓存，辅种成功的种子，可清除
    _success_caches = []
    # 辅种缓存，出错的种子不再重复辅种，且无法清除。种子被删除404等情况
    _permanent_error_caches = []
    # 辅种缓存最大保存条数，避免长期运行时配置缓存无限增长
    _seed_cache_max_items = 10000
    # 辅种计数
    total = 0
    realtotal = 0
    success = 0
    exist = 0
    fail = 0
    cached = 0

    def init_plugin(self, config: dict = None):
        self._error_caches = []
        self._success_caches = []
        self._permanent_error_caches = []

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
            self._reuse_save_path = config.get("reuse_save_path", True)
            self._addhosttotag = config.get("addhosttotag")
            self._size = float(config.get("size")) if config.get("size") else 0
            self._clearcache = config.get("clearcache")
            self._permanent_error_caches = (
                [] if self._clearcache else list(config.get("permanent_error_caches") or [])
            )
            self._error_caches = [] if self._clearcache else list(config.get("error_caches") or [])
            self._success_caches = [] if self._clearcache else list(config.get("success_caches") or [])
            self.__trim_seed_cache(self._permanent_error_caches)
            self.__trim_seed_cache(self._error_caches)
            self.__trim_seed_cache(self._success_caches)

            # 过滤掉已删除的站点
            all_sites = [site.id for site in SiteOper().list_order_by_pri()] + [site.get("id") for site in
                                                                                self.__custom_sites()]
            self._sites = [site_id for site_id in all_sites if site_id in self._sites]
            self.__update_config()

        # 停止现有任务
        self.stop_service()
        # 重新初始化运行期校验队列，避免类级字典跨插件重载残留。
        self._recheck_torrents = {}
        self._auto_rechecked = set()
        self._site_user_ids = {}
        self._hash_names = {}
        self._api_bases = {}

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
                                            'model': 'reuse_save_path',
                                            'label': '沿用原种路径(仅QB有效)',
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
            "reuse_save_path": True,
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
            "reuse_save_path": self._reuse_save_path,
            "size": self._size,
            "success_caches": self._success_caches,
            "error_caches": self._error_caches,
            "permanent_error_caches": self._permanent_error_caches
        })

    def __trim_seed_cache(self, cache: list):
        """
        去重并限制辅种缓存大小，避免长期任务把配置缓存无限撑大。
        """
        if not cache:
            return
        unique_cache = []
        seen = set()
        for item in reversed(cache):
            if not item or item in seen:
                continue
            seen.add(item)
            unique_cache.append(item)
        unique_cache.reverse()
        cache[:] = unique_cache[-self._seed_cache_max_items:]

    def __append_seed_cache(self, cache: list, value: str):
        """
        写入辅种缓存并保持上限，重复值只保留一份。
        """
        if not value:
            return
        if value not in cache:
            cache.append(value)
        self.__trim_seed_cache(cache)

    def auto_seed(self):
        """
        开始辅种
        """
        if not self.iyuu_helper or not self.service_infos:
            return
        logger.info("开始辅种任务 ...")
        # 站点清单每次任务重拉，IYUU 更新站点地址后无需重载插件
        self.iyuu_helper.reset_sites()
        # 端点失败与 rsskey 缓存只在单次任务内有效，避免一次失败固化为长期失败
        self._api_bases = {key: value for key, value in self._api_bases.items() if isinstance(value, str)}
        self._rss_keys = {}

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
            # 当前下载器中所有已完成种子
            completed_hashes_downloader = set()
            for torrent in torrents:
                if self._event.is_set():
                    logger.info(f"辅种服务停止")
                    return
                # 获取种子hash
                hash_str = self.__get_hash(torrent=torrent, dl_type=service.type)
                completed_hashes_downloader.add(hash_str)
                # 记录种子名称，站点API按标题换取下载凭证时使用
                torrent_name = self.__get_torrent_name(torrent=torrent, dl_type=service.type)
                if hash_str and torrent_name:
                    self._hash_names[hash_str] = torrent_name
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
                # 拆包种子排除辅种
                if service.type == "qbittorrent":
                    if torrent.availability != -1 and torrent.availability < 1:
                        logger.info(f"种子 {hash_str} 下载不完整，跳过 ...")
                        continue
                    if torrent.total_size != torrent.completed:
                        logger.info(f"种子 {hash_str} 完成字节数与总体积不一致，跳过 ...")
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
                                         service=service,
                                         completed_hashes_downloader=completed_hashes_downloader)
                # 触发校验检查
                logger.info(f"下载器 {downloader} 辅种全部完成。")
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
            need_recheck_torrents = []
            for torrent in torrents:
                # 获取种子hash
                hash_str = self.__get_hash(torrent=torrent, dl_type=service.type)
                if self.__can_seeding(torrent=torrent, dl_type=service.type):
                    can_seeding_torrents.append(hash_str)
                elif (service.type == "qbittorrent"
                      and torrent.get("state") in ("stoppedDL", "pausedDL")
                      and not torrent.get("progress")
                      and hash_str not in self._auto_rechecked):
                    # qBittorrent 5.3+ 的 WebAPI 移除了 skip_checking 参数，
                    # 跳过校验添加的种子不再被标记为已完成，而是停在未校验状态；
                    # 此处主动补发一次校验，校验完成后即可自动开始辅种
                    need_recheck_torrents.append(hash_str)
            if can_seeding_torrents:
                logger.info(f"共 {len(can_seeding_torrents)} 个任务校验完成，开始辅种 ...")
                # 开始任务
                downloader_obj.start_torrents(ids=can_seeding_torrents)
                # 去除已经处理过的种子
                self._recheck_torrents[downloader] = list(
                    set(recheck_torrents).difference(set(can_seeding_torrents)))
            if need_recheck_torrents:
                logger.info(f"共 {len(need_recheck_torrents)} 个任务未校验，自动补发校验 ...")
                self._auto_rechecked.update(need_recheck_torrents)
                downloader_obj.recheck_torrents(ids=need_recheck_torrents)
        elif torrents is None:
            logger.info(f"下载器 {downloader} 查询校验任务失败，将在下次继续查询 ...")
            return
        else:
            logger.info(f"下载器 {downloader} 中没有需要检查的校验任务，清空待处理列表 ...")
            self._recheck_torrents[downloader] = []

    def __seed_torrents(self, hash_strs: list, service: ServiceInfo, completed_hashes_downloader: set[str]):
        """
        执行一批种子的辅种，排除当前下载器全部已完成种子。

        :param hash_strs: 本批次参与查询的源种子。
        :param service: 当前扫描的下载器服务。
        :param completed_hashes_downloader: 当前下载器中所有的已完成种子
        """
        if not hash_strs:
            return
        logger.info(f"下载器 {service.name} 开始查询辅种，数量：{len(hash_strs)} ...")
        # 下载器中的本批次 Hashs
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
                if seed.get("info_hash") in completed_hashes_downloader:
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

        logger.info(f"下载器 {service.name} 辅种本批次完成")

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

            # 沿用原种保存路径：强制关闭 qB 自动种子管理(ATM)。
            # 开启自动分类管理时 ATM 会覆盖 save_path，辅种落到分类目录而非原种路径，
            # 原种文件不复用即表现为“文件丢失”。
            force_reuse = bool(self._reuse_save_path)
            state = service.instance.add_torrent(content=content,
                                                 download_dir=save_path,
                                                 is_paused=True,
                                                 tag=torrent_tags,
                                                 category=None if force_reuse else save_category,
                                                 is_skip_checking=self._skipverify,
                                                 ignore_category_check=not force_reuse)
            if not state:
                return None
            else:
                # 获取种子Hash
                torrent_hash = service.instance.get_torrent_id_by_tag(tags=tag)
                if not torrent_hash:
                    logger.error(f"{service.name} 下载任务添加成功，但获取任务信息失败！")
                    return None
                # 强制复用路径时分类未在添加时下发(ATM已关闭)，此处补设；
                # ATM 关闭下修改分类不会触发文件移动，save_path 保持不变
                if force_reuse and save_category:
                    service.instance.set_torrent_category(hash_string=torrent_hash,
                                                          category=save_category)
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

        self.total += 1
        # 获取种子站点及下载地址模板
        site_url, download_page = self.iyuu_helper.get_torrent_url(seed.get("sid"))
        if not site_url or not download_page:
            # 加入缓存
            self.__append_seed_cache(self._error_caches, seed.get("info_hash"))
            self.fail += 1
            self.cached += 1
            return False
        # 查询站点
        site_domain = StringUtils.get_url_domain(site_url)
        # 站点信息
        sites_helper = SitesHelper()
        site_info = sites_helper.get_indexer(site_domain)
        if not site_info or not site_info.get('url'):
            # 域名对不上时按 IYUU 站点信息兜底，站点改名换域名后无需改代码
            site_info = self.__get_site_by_iyuu(seed.get("sid"), sites_helper)
            if site_info and site_info.get('url'):
                site_domain = site_info.get('domain')
                logger.debug(f"辅种站点按IYUU站点信息匹配：{site_domain}")
            else:
                site_info = None
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
        torrent_url, use_cookie = self.__get_download_url(seed=seed,
                                                          site=site_info,
                                                          base_url=download_page)
        if not torrent_url:
            # 加入失败缓存
            self.__append_seed_cache(self._error_caches, seed.get("info_hash"))
            self.fail += 1
            self.cached += 1
            return False
        # 下载种子文件
        _, content, _, _, error_msg = TorrentHelper().download_torrent(
            url=torrent_url,
            cookie=site_info.get("cookie") if use_cookie else None,
            ua=self.__site_ua(site_info),
            proxy=site_info.get("proxy"))
        if not content:
            # 下载失败
            self.fail += 1
            # 加入失败缓存
            if error_msg and ('无法打开链接' in error_msg or '触发站点流控' in error_msg):
                self.__append_seed_cache(self._error_caches, seed.get("info_hash"))
            else:
                # 种子不存在的情况
                self.__append_seed_cache(self._permanent_error_caches, seed.get("info_hash"))
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
            self.__append_seed_cache(self._error_caches, seed.get("info_hash"))
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
            self.__append_seed_cache(self._success_caches, seed.get("info_hash"))
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

    @staticmethod
    def __get_torrent_name(torrent: Any, dl_type: str):
        """
        获取种子名称
        """
        try:
            return torrent.get("name") if dl_type == "qbittorrent" else torrent.name
        except Exception as e:
            print(str(e))
            return ""

    def __get_download_url(self, seed: dict, site: CommentedMap, base_url: str) -> Tuple[Optional[str], bool]:
        """
        按 IYUU 返回的下载地址模板拼装种子下载链接

        取种方式由模板形态决定，不判断站点域名，站点更换域名时无需改代码。

        :return: 下载链接与下载时是否需要携带站点 Cookie
        """
        template = base_url or ""
        if not template:
            logger.warn(f"未获取到站点 {site.get('name')} 的下载地址模板")
            return None, True
        # IYUU 声明的站点入口：API 类模板的次选端点，其子域前缀也用来拼换域名后的端点
        iyuu_base_url = (self.iyuu_helper.get_torrent_url(seed.get("sid")) or (None, None))[0]
        iyuu_api_base = self.__api_base(iyuu_base_url, seed.get("sid")) if iyuu_base_url else ""

        def __placeholders(text: str) -> set:
            """
            模板中的占位符集合，裸占位符 {} 视为种子ID
            """
            return {found.strip("{}") or "id" for found in re.findall(r"\{\w*\}", text or "")}

        def __fill(values: dict) -> Tuple[str, set]:
            """
            替换已知占位符，返回链接与仍未填充的占位符
            """
            url = template.replace("id={}", "id={id}")
            # 这类模板只要 id 即可取种，旧版同样整段丢弃
            url = url.replace("/{torrent_key}", "")
            if values.get("id"):
                url = url.replace("{}", str(values.get("id")))
            for key in ("id", "uid", "passkey", "hash", "downHash", "rsskey"):
                url = url.replace("{%s}" % key, str(values.get(key) or ""))
            return url, __placeholders(url)

        def __page_torrent_url():
            """
            从详情页面取种，需要站点 Cookie
            """
            return self.__get_torrent_url_from_page(seed=seed, site=site), True

        def __dedupe(bases: list) -> list:
            """
            候选端点去末尾斜杠后按小写去重，跳过空白项
            """
            uniq = []
            for base in bases:
                if base and base.rstrip("/").lower() not in [item.rstrip("/").lower() for item in uniq]:
                    uniq.append(base)
            return uniq

        def __get_token_enclosure(tid: str, apikey: str, token: str, path: str):
            """
            对带 download-link 的模板，用站点存取令牌换取签名下载链接，端点按候选依次尝试
            """
            access_token = (apikey or "").strip() or (token or "").strip()
            if not access_token:
                logger.error("站点存取令牌未配置")
                return None
            site_key = site.get("domain") or site.get("url") or ""
            known_base = self._api_bases.get(site_key)
            if known_base is None and site_key in self._api_bases:
                # 本次任务内已确认该站点的 API 端点不可用，不再逐个种子重试
                return None
            for api_base in __dedupe(([known_base] if known_base else [])
                                     + self.__api_base_candidates(site, iyuu_api_base)):
                res = RequestUtils(
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'User-Agent': self.__site_ua(site),
                        'Authorization': f'Bearer {access_token}'
                    }
                ).post_res(f"{api_base}/{path.lstrip('/').replace('{}', str(tid))}", json={})
                if not res:
                    logger.warn(f"站点获取签名下载链接失败：{tid}（{api_base}）")
                    continue
                try:
                    data = (res.json().get("data") or {}).get("url")
                except ValueError:
                    logger.warn(f"站点获取签名下载链接失败，响应解析失败：{tid}（{api_base}）")
                    continue
                if data:
                    self._api_bases[site_key] = api_base
                    return data
            self._api_bases[site_key] = None
            return None

        def __get_api_enclosure(tid: str, apikey: str, path: str):
            """
            对无占位符的 API 模板，用站点 apikey 换取种子下载链接
            """
            if not apikey:
                logger.error("站点的apikey未配置")
                return None
            site_key = site.get("domain") or site.get("url") or ""
            known_base = self._api_bases.get(site_key)
            if known_base is None and site_key in self._api_bases:
                # 本次任务内已确认该站点的 API 端点不可用，不再逐个种子重试
                return None
            # 依次试 MP 站点地址、IYUU 主机、跟随 IYUU 前缀的站点域名与站点注册域名
            for api_base in __dedupe(([known_base] if known_base else [])
                                     + self.__api_base_candidates(site, iyuu_api_base)):
                # UA 走请求库参数，写进 headers 会被部分站点判为浏览器访问
                res = RequestUtils(ua=self.__site_ua(site),
                                   headers={'Accept': 'application/json, text/plain, */*',
                                            'x-api-key': apikey}
                                   ).post_res(f"{api_base}/{path.lstrip('/')}", params={'id': tid})
                if not res:
                    logger.warn(f"获取种子下载链接失败：{tid}（{api_base}）")
                    continue
                try:
                    data = res.json().get("data")
                except ValueError:
                    logger.warn(f"获取种子下载链接失败，响应解析失败：{tid}（{api_base}）")
                    continue
                if data:
                    self._api_bases[site_key] = api_base
                    return data
            self._api_bases[site_key] = None
            return None

        try:
            placeholders = __placeholders(template)
            if "download-link" in template:
                # 用站点存取令牌换取签名下载链接
                return __get_token_enclosure(tid=seed.get("torrent_id"),
                                             apikey=site.get("apikey"),
                                             token=site.get("token"),
                                             path=template), True
            if not placeholders:
                # 没有占位符的模板是 API 端点，需要用站点 apikey 换取下载链接
                return __get_api_enclosure(tid=seed.get("torrent_id"),
                                           apikey=site.get("apikey"),
                                           path=template), True
            if "rsskey" in placeholders:
                # 用站点 RSS 的 rsskey 拼装下载链接，RSS 空白时从站点页面提取
                rsskey = self.__get_rss_key(site)
                if not rsskey:
                    logger.info(f"{site.get('name')} 取不到rsskey，回退详情页取种：{seed.get('torrent_id')}")
                    return __page_torrent_url()
                download_url, rest = __fill({"id": seed.get("torrent_id"), "rsskey": rsskey})
                if rest:
                    return __page_torrent_url()
                return urljoin(site.get('url') or "", download_url), True
            if placeholders & {"hash", "downHash"}:
                # 没有 id 的模板，hash 只能从详情页取，本地无法构造
                if "id" not in placeholders:
                    return __page_torrent_url()
                # 模板要求站点下载凭证，先用站点API换取，换到即免 Cookie 取种
                api_url = self.__get_downhash_torrent_url(seed=seed, site=site, base_url=template)
                if api_url:
                    return api_url, False
                if "uid" in placeholders:
                    # 退到站点用户ID + Cookie 取种，模板里空的凭证参数必须去掉
                    download_url, rest = __fill({"id": seed.get("torrent_id"),
                                                 "uid": self.__get_site_user_id(site),
                                                 "hash": "", "downHash": ""})
                    if not rest:
                        download_url = re.sub(r"[&?](?:downHash|hash)=", "", download_url, flags=re.IGNORECASE)
                        logger.info(f"{site.get('name')} 未取得下载凭证，改用站点用户ID取种：{seed.get('torrent_id')}")
                        return urljoin(site.get('url') or "", download_url), True
                return __page_torrent_url()
            if placeholders & {"sign", "cuhash", "authkey", "torrent_pass"}:
                # 模板带站点侧签名参数，本地生成不了，只能从详情页取种
                return __page_torrent_url()
            if "passkey" in placeholders and "download" not in template:
                # 非 download 形态的模板要带 passkey，而 v3 站点配置不保存 passkey，只能从详情页取种
                return __page_torrent_url()
            download_url, rest = __fill({
                "id": seed.get("torrent_id"),
                "uid": site.get("uid"),
                "passkey": site.get("passkey"),
            })
            if rest:
                logger.warn(f"当前不支持该站点的辅助任务，Url转换失败：{seed}")
                return None
            download_url = re.sub(r"[&?](?:passkey|uid)=", "", download_url, flags=re.IGNORECASE)
            return urljoin(site.get('url') or "", download_url), True
        except Exception as e:
            logger.warn(
                f"{site.get('name')} Url转换失败，{str(e)}：site_url={site.get('url')}，base_url={base_url}, seed={seed}")
            return self.__get_torrent_url_from_page(seed=seed, site=site), True

    def __api_base(self, host: Any, sid: Any = None) -> str:
        """
        按 IYUU 站点声明拼 API 基地址

        IYUU 清单的 is_https 标明站点入口协议：0 走 http，其余（1/2）走 https。

        :param host: IYUU 返回的站点入口，可能不带协议
        :param sid: IYUU 站点 ID
        :return: 带协议的基地址
        """
        host = str(host or "").strip().strip("/")
        if not host:
            return ""
        if re.match(r"^https?://", host, flags=re.IGNORECASE):
            return host
        meta = self.iyuu_helper.get_site_info(sid) if sid is not None and self.iyuu_helper else {}
        return f"{'http' if (meta or {}).get('is_https') == 0 else 'https'}://{host}"

    def __api_base_candidates(self, site: dict, iyuu_api_base: str) -> list:
        """
        返回换取下载链接时依次尝试的 API 基地址

        MP 站点地址优先，其次 IYUU 清单主机；站点地址填的就是注册域名时，再按 IYUU 主机的
        子域前缀换到站点域名，覆盖站点已换域名、IYUU 清单尚未跟上的窗口期。

        :param site: MoviePilot 维护的站点信息，需包含 url 与 domain
        :param iyuu_api_base: 按 IYUU 清单拼出的带协议基地址
        :return: 候选基地址列表，去重由调用方处理
        """
        site_url = (site.get("url") or "").rstrip("/")
        registered = self.__registered_domain(site.get("domain") or site_url)
        scheme = iyuu_api_base.split("://")[0].lower() if "://" in (iyuu_api_base or "") else "https"
        # 前缀候选跟随 IYUU 声明的协议，注册域名兜底仍用 https
        candidates = [site_url, iyuu_api_base]
        iyuu_host = re.sub(r"^https?://", "", (iyuu_api_base or "").lower()).strip("/")
        iyuu_registered = self.__registered_domain(iyuu_host)
        prefix = ""
        if iyuu_host and iyuu_registered and iyuu_host != iyuu_registered \
                and iyuu_host.endswith(f".{iyuu_registered}"):
            prefix = iyuu_host[:-len(iyuu_registered) - 1]
        # 站点地址带镜像或入口子域时以用户填的为准，不再拼新主机
        labels = [label for label in re.sub(r"^https?://", "", site_url.lower()).split("/")[0].split(".")
                  if label]
        while len(labels) > 1 and labels[0] in ("api", "www"):
            labels = labels[1:]
        if prefix and registered and ".".join(labels) == registered:
            candidates.append(f"{scheme}://{prefix}.{registered}")
        if registered:
            candidates.append(f"https://{registered}")
        return candidates

    @staticmethod
    def __registered_domain(url: Optional[str]) -> str:
        """
        取注册域名，忽略协议与子域并保留多级公共后缀

        :param url: 站点地址、域名或站点标识
        :return: 注册域名，无法解析时为空字符串
        """
        labels = [label for label in re.sub(r"^https?://", "", (url or "").lower()).split("/")[0].split(".")
                  if label]
        # api./www. 是常见入口前缀，去掉后 api.m-team.cc 与 m-team.cc 归一到同一注册域
        while len(labels) > 1 and labels[0] in ("api", "www"):
            labels = labels[1:]
        if len(labels) < 2:
            return "".join(labels)
        # 二级公共后缀（com.cn / co.uk / com.au…）要多取一段，ccTLD 固定为两字母
        suffix = 3 if len(labels) >= 3 and len(labels[-1]) == 2 \
            and labels[-2] in ("com", "net", "org", "edu", "co") else 2
        return ".".join(labels[-suffix:])

    @classmethod
    def __domain_body(cls, url: Optional[str]) -> str:
        """
        取域名主体，忽略协议、子域和公共后缀，便于跨后缀匹配同一站点

        :param url: 站点地址、域名或站点标识
        :return: 归一化后的域名主体，无法解析时为空字符串
        """
        registered = cls.__registered_domain(url)
        return registered.rsplit(".", 1)[0] if "." in registered else registered

    @staticmethod
    def __site_ua(site: Optional[dict]) -> str:
        """
        按 站点配置 > 通用站点配置 > 全局默认值 解析请求 User-Agent

        :param site: 站点配置
        :return: 实际使用的 User-Agent
        """
        return _resolve_site_user_agent(
            (site or {}).get("ua"),
            getattr(settings, "SITE_USER_AGENT", None),
            settings.USER_AGENT,
        )

    def __get_site_by_iyuu(self, sid: Any, sites_helper: Any) -> Optional[dict]:
        """
        按 IYUU 站点信息匹配 MoviePilot 站点，站点名称不同也能对上

        依次比较注册域名、域名主体、IYUU 站点标识、站点昵称，命中需唯一。

        :param sid: IYUU 返回的站点 ID
        :param sites_helper: 站点助手
        :return: 命中的站点配置，未命中或命中不唯一时返回 None
        """
        meta = self.iyuu_helper.get_site_info(sid) or {}
        if not meta:
            return None
        indexers = sites_helper.get_indexers() or []
        base_url = meta.get("base_url") or ""
        slug = meta.get("site") or ""
        keys = {
            "domain": self.__domain_body(base_url),
            "slug": self.__domain_body(slug),
            "name": str(meta.get("nickname") or "").strip().lower(),
            "compact": self.__compact(slug),
        }
        for key, getter in (
                (keys["domain"], lambda site: self.__domain_body(site.get("domain"))),
                (keys["slug"], lambda site: self.__domain_body(site.get("domain"))),
                (keys["name"], lambda site: str(site.get("name") or "").strip().lower()),
                # 站点名常写成 M-Team 这类，去掉分隔符后与 IYUU 标识比对
                (keys["compact"], lambda site: self.__compact(site.get("name"))),
        ):
            if not key:
                continue
            matched = [site for site in indexers if getter(site) == key]
            if len(matched) == 1:
                logger.debug(f"辅种站点匹配：{meta.get('nickname')} {base_url} -> {matched[0].get('domain')}")
                return matched[0]
        return None

    @staticmethod
    def __compact(text: Optional[str]) -> str:
        """
        去掉分隔符并小写，用于站点名与 IYUU 站点标识的宽松比对

        :param text: 站点名或站点标识
        :return: 归一化后的文本
        """
        return re.sub(r"[^a-z0-9]", "", (text or "").lower())

    def __get_rss_key(self, site: dict) -> Optional[str]:
        """
        取站点的 rsskey：优先读配置的 RSS 链接，空白时从站点页面提取

        :param site: MoviePilot 维护的站点信息，需包含 rss、url
        :return: rsskey，取不到时返回 None
        """
        rssurl = site.get("rss") or ""
        for pattern in (r"/rss/\d+\.(\w+)", r"rsskey=(\w{8,})"):
            match = re.search(pattern, rssurl)
            if match:
                return match.group(1)
        domain = site.get("domain") or ""
        if domain and domain in self._rss_keys:
            return self._rss_keys.get(domain)
        site_url = (site.get("url") or "").rstrip("/")
        if not site_url:
            return None
        res = RequestUtils(cookies=site.get("cookie"),
                           ua=self.__site_ua(site),
                           proxies=settings.PROXY if site.get("proxy") else None
                           ).get_res(url=f"{site_url}/")
        text = getattr(res, "text", "") or ""
        # 页面上的下载链接形如 torrents/download/123.<rsskey>
        for pattern in (r"/rss/\d+\.(\w+)", r"rsskey=(\w{8,})", r"download/\d+\.(\w{8,})"):
            match = re.search(pattern, text)
            if match:
                if domain:
                    self._rss_keys[domain] = match.group(1)
                return match.group(1)
        return None

    def __get_downhash_torrent_url(self, seed: dict, site: dict, base_url: str) -> Optional[str]:
        """
        用站点API按种子标题换取下载凭证（downhash），换到即可免 Cookie 取种

        详情页被站点两步验证拦截时，这条链路仍可用。

        :param seed: IYUU 返回的种子信息，需包含 torrent_id 与 info_hash
        :param site: MoviePilot 维护的站点信息，需包含 url 与 apikey
        :param base_url: IYUU 返回的种子下载地址模板
        :return: 下载链接，换取失败时返回 None
        """
        apikey = (site.get("apikey") or "").strip()
        site_url = (site.get("url") or "").rstrip("/")
        keyword = self._hash_names.get(seed.get("info_hash") or "") or seed.get("name")
        if not apikey or not site_url or not keyword:
            return None
        # 检索按标题匹配，长标题经常搜不到，从完整标题逐级缩到首个词
        keywords = [keyword, keyword[:40], keyword[:24], re.split(r"[.\s\[]", keyword)[0]]
        keywords = [item for item in dict.fromkeys(keywords) if item and len(item) >= 4]
        info_hash = str(seed.get("info_hash") or "").lower()
        for keyword in keywords:
            res = RequestUtils(
                headers={
                    "x-api-key": apikey,
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                },
                ua=self.__site_ua(site)
            ).post_res(f"{site_url}/api/v1/torrent/search",
                       json={"keyword": keyword, "page_number": 0, "page_size": 50, "visible": 1})
            if not res:
                logger.warn(f"{site.get('name')} 下载凭证接口无响应：{seed.get('torrent_id')}")
                return None
            try:
                torrents = res.json().get("data") or []
            except ValueError:
                logger.warn(f"{site.get('name')} 下载凭证接口响应解析失败：{seed.get('torrent_id')}")
                return None
            for torrent in torrents:
                if str(torrent.get("info_hash") or "").lower() != info_hash or not torrent.get("downhash"):
                    continue
                download_url = (base_url or "").replace("id={}", "id={id}")
                for placeholder, value in (("{id}", torrent.get("id")),
                                           ("{hash}", torrent.get("downhash")),
                                           ("{downHash}", torrent.get("downhash")),
                                           ("{uid}", ""),
                                           ("{passkey}", "")):
                    download_url = download_url.replace(placeholder, str(value))
                if "{" in download_url:
                    return None
                download_url = re.sub(r"([&?])hash=", r"\1downhash=", download_url, flags=re.IGNORECASE)
                download_url = re.sub(r"[&?](?:uid|passkey)=", "", download_url, flags=re.IGNORECASE)
                return urljoin(f"{site_url}/", download_url)
        return None

    def __get_site_user_id(self, site: dict) -> Optional[str]:
        """
        取站点的用户ID，优先读站点配置，缺失时按域名查站点数据。

        :param site: MoviePilot 维护的站点信息
        :return: 纯数字的用户ID，取不到时返回 None
        """
        user_id = str(site.get("uid") or "").strip()
        if user_id.isdigit():
            return user_id
        if not self._site_user_ids:
            self._site_user_ids = {
                row.domain: row.userid
                for row in SiteOper().get_userdata_latest() or []
                if row.domain and row.userid
            }
        # 站点数据里的域名可能不带 www 或带子域，按域名后缀比对
        for host in (site.get("domain"), urlparse(site.get("url") or "").hostname):
            host = str(host or "").strip().lower()
            if not host:
                continue
            for domain, userid in self._site_user_ids.items():
                domain = str(domain or "").strip().lower()
                if domain and (host == domain or host.endswith(f".{domain}") or domain.endswith(f".{host}")):
                    found = str(userid or "").strip()
                    if found.isdigit():
                        return found
        return None

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
                ua=self.__site_ua(site),
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
