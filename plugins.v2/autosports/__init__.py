import base64
import json
from copy import deepcopy
from dataclasses import fields, dataclass
from platform import machine
from re import match
from types import NoneType
from typing import List, Tuple, Dict, Any, Union

from cachetools import cached, TTLCache
from langsmith import expect
from six import reraise

from app.api.endpoints.dashboard import downloader
from app.api.endpoints.media import seasons
from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.search import SearchChain
from app.chain.subscribe import SubscribeChain
from app.chain.transfer import job_lock
from app.core.config import settings
from app.core.meta import MetaVideo, MetaBase
from app.core.metainfo import MetaInfo
from app.core.context import MediaInfo, Context, TorrentInfo
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import MediaType, ServiceInfo
import datetime
import re
import traceback
from typing import Optional, Any, List, Dict, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.context import MediaInfo, TorrentInfo, Context
from app.core.metainfo import MetaInfo
from app.helper.rss import RssHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ExistMediaInfo
from app.schemas.types import SystemConfigKey, MediaType
from app.helper.sites import SitesHelper

from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from downloader import DownloaderHelper


class AutoSports(_PluginBase):
    # 插件名称
    plugin_name = "Sportscult 比赛自动下载及简单刮削"
    # 插件描述
    plugin_desc = "根据设置的球队名自动下载最新比赛，进行文件整理及简单的刮削"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Sinterdial/MoviePilot-Plugins/main/icons/shortcut.png"
    # 插件版本
    plugin_version = "0.2.0"
    # 插件作者
    plugin_author = "Sinterdial"
    # 作者主页
    author_url = "https://github.com/Sinterdial"
    # 插件配置项ID前缀
    plugin_config_prefix = "AutoSports_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    __enabled: bool = False
    __teams_info: str = ""
    __football_apikey: str = ""
    __cron: str = ""
    __notify: bool = False
    __onlyonce: bool = False
    __include: str = ""
    __exclude: str = ""
    __proxy: bool = False
    __filter: bool = False
    __force_en: bool = False
    __lowest_pix: int = 0
    __clear: bool = False
    __clearflag: bool = False
    __action: str = "download"
    __save_path: str = ""
    __category: str = ""
    __tags: list[str] = []
    __size_range: str = ""
    __downloaders = None
    __scheduler: BackgroundScheduler = None

    # 赛事刮削信息
    # 自定义映射关系
    __match_parses = [
        {
            "names": ["西甲", "La Liga", "LaLiga", "Laliga"],
            "shortname": "PD",
            "title": "西班牙足球甲级联赛",
            "en_title": "La Liga",
            "year": 1929,
            "overview": "西班牙足球甲级联赛（西班牙语：Primera División de España或La Liga，由于赞助原因，正式名称为LALIGA EA SPORTS），通常简称西甲或西甲联赛，是西班牙足球联赛系统的第 1 级别，亦是职业联赛的最高级别、联赛系统的最高级别和西班牙顶级足球联赛，目前有 20 支球队。皇家马德里是历史上夺得最多冠军的球队（36次），其次是巴塞罗那（28次），以及马德里竞技（11次）。 ",
            "season_years": list(range(1929, 2101)),
            "homepage": "https://www.laliga.com/en-GB",
            "languages": "Spanish",
            "origin_country": "Spain",
            "original_name": "La Liga",
            "production_companies": "UEFA（欧洲）",
            "production_countries": "Spain",
            "spoken_languages": "Spanish",
            "runtime": 9000,
        },
        {
            "names": ["欧洲冠军联赛", "Champions League", "UCL"],
            "title": "欧洲冠军联赛",
        },
        {
            "names": ["西班牙国王杯", "Copa Del Rey"],
            "title": "西班牙国王杯",
        },
        {
            "names": ["西班牙超级杯", "Supercopa de España"],
            "title": "西班牙超级杯",
        },
    ]

    downloadchain: DownloadChain = None
    subscribechain: SubscribeChain = None
    mediachain: MediaChain = None
    searchchain: SearchChain = None

    torrents_list = []

    @property
    def __downloader(self) -> Optional[Union[Qbittorrent, Transmission]]:
        """
        下载器实例
        """
        return self.__service_info.instance if self.__service_info else None

    @property
    def __service_info(self) -> Optional[ServiceInfo]:
        """
        服务信息
        """
        service = DownloaderHelper().get_service(name=self.__downloaders)
        if not service:
            self.__log_and_notify_error("站点刷流任务出错，获取下载器实例失败，请检查配置")
            return None

        if service.instance.is_inactive():
            self.__log_and_notify_error("站点刷流任务出错，下载器未连接")
            return None

        return service

    @staticmethod
    def add_site() -> dict:
        """
            添加 Sportscult 站点索引
        """
        indexer: dict = {
            "id": "sportscult",
            "name": "Sportscult",
            "domain": "https://sportscult.org/",
            "encoding": "UTF-8",
            "public": False,
            "result_num": 30,
            "timeout": 30,
            "search": {
                "paths": [
                    {
                        "path": "index.php?page=torrents&active=1&gold=0&search=barcelona&&order=3&by=2",
                        "method": "get"
                    }
                ]
            },
            "browse": {
                "path": "?p={page}",
                "start": 1
            },
            "category": {
                "movie": [

                ],
                "tv": [
                    {
                        "id": 43,
                        "cat": "La Liga",
                        "desc": "西甲"
                    },
                    {
                        "id": 60,
                        "cat": "Champions League",
                        "desc": "欧冠"
                    },
                ]
            },
            "torrents": {
                "list": {
                    "selector": "table.lista > tr:has(\"td.lista.specialPadding\")"
                },
                "fields": {
                    "id": {
                        "selector": "a[href*=\"torrent-details&id=\"]",
                        "attribute": "href",
                        "filters": [
                            {
                                "name": "re_search",
                                "args": [
                                    "\\d+",
                                    0
                                ]
                            }
                        ]
                    },
                    "title_optional": {
                        "selector": "a[href*=\"torrent-details&id=\"]"
                    },
                    "title_default": {
                        "optional": True,
                        "selector": "a[title][href*=\"torrent-details&id=\"]",
                        "attribute": "title"
                    },
                    "title": {
                        "text": "{% if fields['title_optional'] %}{{ fields['title_optional'] }}{% else %}{{ fields['title_default'] }}{% endif %}"
                    },
                    "details": {
                        "selector": "a[href*=\"torrent-details&id=\"]",
                        "attribute": "href"
                    },
                    "download": {
                        "selector": "a[href*=\"download.php?id=\"]",
                        "attribute": "href"
                    },
                    "imdbid": {
                        "optional": True,
                        "selector": "div.imdb_100 > a",
                        "attribute": "href",
                        "filters": [
                            {
                                "name": "re_search",
                                "args": [
                                    "tt\\d+",
                                    0
                                ]
                            }
                        ]
                    },
                    "date_elapsed": {
                        "selector": "td:nth-child(5)",
                        "optional": True
                    },
                    "date_added": {
                        "selector": "td:nth-child(5)",
                        "optional": True
                    },
                    "size": {
                        "selector": "td:nth-child(4)"
                    },
                    "seeders": {
                        "selector": "td:nth-child(6) > a"
                    },
                    "leechers": {
                        "selector": "td:nth-child(7) > a"
                    },
                    "grabs": {
                        "selector": "td:nth-child(8) > a"
                    },
                    "downloadvolumefactor": {
                        "case": {
                            "img[alt=\"silver\"]": 0.5,
                            "img[alt=\"gold\"]": 0,
                            "*": 1
                        }
                    },
                    "uploadvolumefactor": {
                        "case": {
                            "img[alt=\"silver\"]": 1,
                            "img[alt=\"gold\"]": 1,
                            "*": 1
                        }
                    },
                    "description": {
                        "optional": True,
                        "selector": "a[href*=\"torrent-details&id=\"]",
                        "contents": -1
                    },
                    "labels": {
                        "optional": True,
                        "selector": "td:nth-child(8) > a",
                        "attribute": "alt"
                    },
                    "category": {
                        "optional": True,
                        "selector": "td:nth-child(8) > a",
                        "attribute": "alt"
                    }
                }
            }
        }

        return indexer


    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()

        sportscult_json = self.add_site()
        # 添加 SportsCult 站点
        # TODO: 如果已存在该站点，不再添加
        SitesHelper().add_indexer(domain="sportscult.org", indexer=sportscult_json)


        # 配置
        if config:
            self.__validate_and_fix_config(config=config)
            self.__football_apikey = config.get("football_apikey")
            self.__teams_info = config.get("teams_info")
            self.__enabled = config.get("enabled")
            self.__cron = config.get("cron")
            self.__notify = config.get("notify")
            self.__onlyonce = config.get("onlyonce")
            self.__include = config.get("include")
            self.__exclude = config.get("exclude")
            self.__proxy = config.get("proxy")
            self.__force_en = config.get("force_en") or False
            self.__lowest_pix = int(config.get("lowest_pix"))
            self.__filter = config.get("filter")
            self.__clear = config.get("clear")
            self.__action = config.get("action")
            self.__save_path = config.get("save_path")
            self.__downloaders = config.get("downloaders")
            # 如果未设置下载器，使用默认的下载器
            if not self.__downloaders:
                for downloader_config in DownloaderHelper().get_configs().values():
                    if downloader_config.default:
                        self.__downloaders = downloader_config.name
                        break

            try:
                category_gotten = config.get("category")
                self.__category = category_gotten
            except AttributeError:
                self.__category = ""
            try:
                tags_gotten = config.get("tags")
                self.__tags = tags_gotten.split(",")
            except AttributeError:
                self.__tags = []
            self.__size_range = config.get("size_range")

        if not self.__football_apikey:
            logger.error("无法对比赛进行刮削，请填入有效的 football-data.org API key")
            self.stop_service()

        if self.__onlyonce:
            self.__scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"自定义订阅服务启动，立即运行一次")
            self.__scheduler.add_job(func=self.check, trigger='date',
                                     run_date=datetime.datetime.now(
                                         tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                     )

            # 启动任务
            if self.__scheduler.get_jobs():
                self.__scheduler.print_jobs()
                self.__scheduler.start()

        if self.__onlyonce or self.__clear:
            # 关闭一次性开关
            self.__onlyonce = False
            # 记录清理缓存设置
            self.__clearflag = self.__clear
            # 关闭清理缓存开关
            self.__clear = False
            # 保存设置
            self.__update_config()

    def get_state(self) -> bool:
        return self.__enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        return [
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除自定义订阅历史记录"
            }
        ]

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
        if self.__enabled and self.__cron:
            return [{
                "id": "RssSubscribe",
                "name": "自定义订阅服务",
                "trigger": CronTrigger.from_crontab(self.__cron),
                "func": self.check,
                "kwargs": {}
            }]
        elif self.__enabled:
            return [{
                "id": "RssSubscribe",
                "name": "自定义订阅服务",
                "trigger": "interval",
                "func": self.check,
                "kwargs": {"minutes": 30}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
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
                                    'md': 4
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
                                    'md': 4
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
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
                                                {'title': '订阅（暂不支持）', 'value': 'subscribe'},
                                                {'title': '下载', 'value': 'download'}
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'teams_info',
                                            'label': '关注球队名',
                                            'rows': 3,
                                            'placeholder': '请输入关注球队的名称，一行一个（英文，关键字即可）'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'football_apikey',
                                            'label': '比赛元数据 API key',
                                            'rows': 3,
                                            'placeholder': '请输入 football-data.org 上有效的 API key'
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
                                            'model': 'include',
                                            'label': '包含',
                                            'placeholder': '支持正则表达式'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude',
                                            'label': '排除',
                                            'placeholder': '支持正则表达式'
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
                                            'model': 'force_en',
                                            'label': '是否只下载英文解说版本',
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'size_range',
                                            'label': '种子大小(GB)',
                                            'placeholder': '如：3 或 3-5'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'lowest_pix',
                                            'label': '最低清晰度(p)',
                                            'placeholder': '如：720'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category',
                                            'label': '种子分类，留空为不设置',
                                            'placeholder': '如：Sports'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tags',
                                            'label': '种子标签，以逗号隔开，留空为不设置',
                                            'placeholder': '如：Sportscult,AutoSports'
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
                                            'multiple': False,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [
                                                {"title": config.name, "value": config.name} for config in DownloaderHelper().get_configs().values()
                                            ]
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'save_path',
                                            'label': '保存目录',
                                            'placeholder': '下载时有效，留空自动'
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
                                            'model': 'proxy',
                                            'label': '使用代理服务器',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'filter',
                                            'label': '使用订阅优先级规则',
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
                                            'model': 'clear',
                                            'label': '清理历史记录',
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
            "football_apikey": "",
            "teams_info": "",
            "notify": True,
            "onlyonce": False,
            "cron": "*/30 * * * *",
            "include": "",
            "exclude": "",
            "proxy": False,
            "clear": False,
            "filter": False,
            "action": "download",
            "save_path": "",
            "category": "",
            "tags": [],
            "size_range": "",
            "force_en": False,
            "lowest_px": "720",
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询同步详情
        historys = self.get_data('history')
        if not historys:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        # 数据按时间降序排序
        historys = sorted(historys, key=lambda x: x.get('time'), reverse=True)
        # 拼装页面
        contents = []
        for history in historys:
            title = history.get("title")
            poster = history.get("poster")
            mtype = history.get("type")
            time_str = history.get("time")
            contents.append(
                {
                    'component': 'VCard',
                    'content': [
                        {
                            "component": "VDialogCloseBtn",
                            "props": {
                                'innerClass': 'absolute top-0 right-0',
                            },
                            'events': {
                                'click': {
                                    'api': 'plugin/RssSubscribe/delete_history',
                                    'method': 'get',
                                    'params': {
                                        'key': title,
                                        'apikey': settings.API_TOKEN
                                    }
                                }
                            },
                        },
                        {
                            'component': 'div',
                            'props': {
                                'class': 'd-flex justify-space-start flex-nowrap flex-row',
                            },
                            'content': [
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VImg',
                                            'props': {
                                                'src': poster,
                                                'height': 120,
                                                'width': 80,
                                                'aspect-ratio': '2/3',
                                                'class': 'object-cover shadow ring-gray-500',
                                                'cover': True
                                            }
                                        }
                                    ]
                                },
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VCardTitle',
                                            'props': {
                                                'class': 'pa-1 pe-5 break-words whitespace-break-spaces'
                                            },
                                            'text': title
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'类型：{mtype}'
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'时间：{time_str}'
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            )

        return [
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-3 grid-info-card',
                },
                'content': contents
            }
        ]

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self.__scheduler:
                self.__scheduler.remove_all_jobs()
                if self.__scheduler.running:
                    self.__scheduler.shutdown()
                self.__scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    def delete_history(self, key: str, apikey: str):
        """
        删除同步历史记录
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        # 历史记录
        historys = self.get_data('history')
        if not historys:
            return schemas.Response(success=False, message="未找到历史记录")
        # 删除指定记录
        historys = [h for h in historys if h.get("title") != key]
        self.save_data('history', historys)
        return schemas.Response(success=True, message="删除成功")

    def __update_config(self):
        """
        更新设置
        """
        self.update_config({
            "enabled": self.__enabled,
            "football_apikey": self.__football_apikey,
            "teams_info": self.__teams_info,
            "notify": self.__notify,
            "onlyonce": self.__onlyonce,
            "cron": self.__cron,
            "include": self.__include,
            "exclude": self.__exclude,
            "proxy": self.__proxy,
            "filter": self.__filter,
            "clear": self.__clear,
            "action": self.__action,
            "save_path": self.__save_path,
            "category": self.__category,
            "tags": self.__tags,
            "size_range": self.__size_range,
            "downloaders": self.__downloaders,
            "force_en": self.__force_en,
            "lowest_pix": self.__lowest_pix,
        })

    def check(self):
        """
        自动下载 SportsCult 球队最新内容
        """
        if not self.__teams_info:
            logger.error(f"未输入球队名，不会进行任何操作，请输入球队名再试")
            return
        # 读取历史记录
        if self.__clearflag:
            history = []
        else:
            history: List[dict] = self.get_data('history') or []

        searchchain = SearchChain()
        downloadchain = DownloadChain()
        subscribechain = SubscribeChain()

        # sportscult_indexer: dict = {}

        for indexer in SitesHelper().get_indexers():
            # 检查站点索引开关
            if indexer.get("is_active"):
                # sportscult_indexer = indexer
                sportscult_indexer_id: int = indexer.get("id")
            else:
                logger.error(f"Sportscults站点未启用，请检查站点设置")
                return

        for team_info in self.__teams_info.split("\n"):
            # 在 SportsCult 搜索种子
            if not team_info:
                continue
            logger.info(f"开始在 Sportscult 搜索 {team_info} 的比赛...")

            results = searchchain.search_by_title(title=team_info, sites=[sportscult_indexer_id])

            if not results:
                logger.error(f"未获取到该球队相关比赛种子，请更换关键词再试试：{team_info}")
                return

            # 保存搜索到且成功刮削的种子
            matchesinfo = []

            # 解析数据
            for result in results:
                try:
                    title = result.torrent_info.title
                    logger.info(f"找到种子：{title}，开始处理......")
                    description = result.torrent_info.description
                    enclosure = result.torrent_info.enclosure
                    link = result.torrent_info.page_url
                    size = result.torrent_info.size
                    pubdate: datetime.datetime = result.torrent_info.pubdate
                    # 检查是否处理过
                    if not title or title in [h.get("key") for h in history]:
                        continue
                    # 检查规则
                    if self.__include and not re.search(r"%s" % self.__include,
                                                        f"{title} {description}", re.IGNORECASE):
                        logger.info(f"{title} - {description} 不符合包含规则")
                        continue
                    if self.__exclude and re.search(r"%s" % self.__exclude,
                                                    f"{title} {description}", re.IGNORECASE):
                        logger.info(f"{title} - {description} 不符合排除规则")
                        continue
                    if self.__size_range:
                        sizes = [float(_size) * 1024 ** 3 for _size in self.__size_range.split("-")]
                        if len(sizes) == 1 and float(size) < sizes[0]:
                            logger.info(f"{title} - 种子大小不符合条件")
                            continue
                        elif len(sizes) > 1 and not sizes[0] <= float(size) <= sizes[1]:
                            logger.info(f"{title} - 种子大小不在指定范围")
                            continue

                    # 种子
                    gotten_torrentinfo = result.torrent_info
                    gotten_metainfo = result.meta_info
                    # 识别体育比赛信息
                    gotten_match_mediainfo = self.recognize_competition_mediainfo(gotten_torrentinfo, gotten_metainfo)
                    if not gotten_match_mediainfo:
                        # 如果未识别成功，跳过
                        continue
                    gotten_match_metainfo = self.recognized_match_metainfo(gotten_match_mediainfo, gotten_metainfo)
                    if not gotten_match_metainfo:
                        # 如果未识别成功，跳过
                        continue

                    filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)

                    # 过滤种子
                    if self.__filter:
                        result = self.chain.filter_torrents(
                            rule_groups=filter_groups,
                            torrent_list=[gotten_torrentinfo],
                            mediainfo=gotten_match_mediainfo
                        )
                        if not result:
                            logger.info(f"{title} {description} 不匹配过滤规则")
                            continue

                    # 判断媒体库是否已存在该场比赛
                    exist_info: Optional[ExistMediaInfo] = self.chain.media_exists(mediainfo=gotten_match_mediainfo)
                    if exist_info:
                        exist_season = exist_info.seasons
                        if exist_season:
                            exist_episodes = exist_season.get(gotten_metainfo.begin_season)
                            if exist_episodes and set(gotten_metainfo.episode_list).issubset(set(exist_episodes)):
                                logger.info(f'{gotten_match_mediainfo.title_year} {gotten_metainfo.season_episode} 己存在')
                                continue

                    # 判断新搜索到的种子是否比之前的种子更好
                    gotten_matchinfo = self.Matchinfo(gotten_torrentinfo, gotten_match_mediainfo, gotten_match_metainfo)
                    gotten_matchinfo.language = self.recognize_language(gotten_match_metainfo)
                    if gotten_metainfo.resource_pix:
                        gotten_matchinfo.pix = int(gotten_metainfo.resource_pix[0:-1])
                    self.find_best(force_en=self.__force_en, lowest_pix=self.__lowest_pix, matchesinfo=matchesinfo,
                                   new_matchinfo=gotten_matchinfo)
                except Exception as err:
                    logger.error(f'自动下载体育数据出错：{str(err)} - {traceback.format_exc()}')

            for final_matchinfo in matchesinfo:
                torrentinfo = final_matchinfo.torrentinfo
                match_mediainfo = final_matchinfo.mediainfo
                match_metainfo = final_matchinfo.metainfo
                title = torrentinfo.title
                # 下载或订阅
                if self.__action == "download":
                    # 添加下载
                    is_existed, torrent_hash = self.__download(torrentinfo)
                    if not torrent_hash:
                        logger.error(f'{title} 下载失败')
                        # 调试用，找到就退出
                        return
                        # continue
                    elif is_existed:
                        logger.info(f'{title} 已存在，种子 HASH 值为：{torrent_hash}')
                    else:
                        logger.info(f'{title} 下载成功，种子 HASH 值为：{torrent_hash}')
                    # 调试用，找到就退出
                    return
                else:
                    # TODO: 支持订阅功能
                    logger.error(f'暂不支持订阅功能，请等待适配')
                    # 保存历史记录
                    self.save_data('history', history)
                    # 缓存只清理一次
                    self.__clearflag = False
                    return
                    # 检查是否在订阅中
                    subflag = subscribechain.exists(mediainfo=match_mediainfo, meta=match_metainfo)
                    if subflag:
                        logger.info(f'{match_mediainfo.title_year} {metainfo.season} 正在订阅中')
                        continue
                    # 添加订阅
                    subscribechain.add(title=match_mediainfo.title,
                                       year=match_mediainfo.year,
                                       mtype=match_mediainfo.type,
                                       tmdbid=match_mediainfo.tmdb_id,
                                       season=metainfo.begin_season,
                                       exist_ok=True,
                                       username="AutoSports")
                # 存储历史记录
                history.append({
                    "title": f"{match_mediainfo.title} {match_metainfo.season}",
                    "key": f"{title}",
                    "type": match_mediainfo.type.value,
                    "year": match_mediainfo.year,
                    "poster": match_mediainfo.get_poster_image(),
                    "overview": match_mediainfo.overview,
                    "tmdbid": match_mediainfo.tmdb_id,
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            logger.info(f"体育比赛刷新完成")
        # 保存历史记录
        self.save_data('history', history)
        # 缓存只清理一次
        self.__clearflag = False


    def scrape_competition(self, matchinfo: MediaInfo, match_parse: {}):
        """
          根据给定的 JSON 规则刮削体育比赛
        """
        for f in fields(matchinfo):
            if f.name in match_parse:
                setattr(matchinfo, f.name, match_parse[f.name])
        pass

    def get_match_raw_metadata(self, competition_name:str = '', season:int = 0, home_team: list[str] = '', away_team: list[str] = ''):
        """
          从 football-data.org 获取比赛信息
        """
        import requests

        if not competition_name or not season or not home_team or not away_team:
            logger.error(f'缺少必须比赛信息，无法进行刮削，competition_name: {competition_name}，season: {season}, home_team: {home_team}, away_team: {away_team}')
            return None

        # 寻找比赛缩写
        for match_parse in self.__match_parses:
            if competition_name == match_parse["title"]:
                competition_shortname = match_parse["shortname"]
                break
            else:
                continue

        headers = {"X-Auth-Token": self.__football_apikey}

        timeout = (30, 30)

        url = f"https://api.football-data.org/v4/competitions/{competition_shortname}/matches"
        params = {
            "season": season
        }

        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        data = resp.json()

        for match in data["matches"]:
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]

            if any(home_team_i in home for home_team_i in home_team) and any(away_team_i in away for away_team_i in away_team):
                return match

        logger.error(f'未匹配到相关比赛，请检查输入信息，competition_name: {competition_name}，season: {season}, home_team: {home_team}, away_team: {away_team}')
        return None

    def recognized_match_metainfo(self, match_mediainfo: MediaInfo, metainfo: MetaBase) -> MetaVideo | None:
        """
          根据给定的规则刮削单场比赛信息
        """
        match_metainfo = deepcopy(metainfo)

        competition_cn_name = match_mediainfo.title
        competition_en_name = match_mediainfo.en_title

        org_str = metainfo.org_string
        # 获取赛季信息
        try:
            season_name = metainfo.year
            if not season_name:
                # 尝试在原标题中找到年份
                match_date = self.extract_date(org_str)
                if match_date[1] < 7:
                    # 如果比赛日期在七月之前，是上一年开始的赛季
                    season = match_date[0] - 1
                else:
                    season = match_date[0]
            else:
                season = int(season_name)
            season_shortname = season % 100
            # 解析赛季信息
            season_cn_name = f"{season_shortname:02d}-{(season_shortname + 1):02d} 赛季"
            season_en_name = f"Season {season_shortname:02d}-{(season_shortname + 1):02d}"
            logger.info(f"成功匹配到赛季信息：{season_cn_name}")
        except Exception as err:
            logger.warn("未成功匹配到赛季信息，跳过")
            return None

        # 分析主客场球队
        try:
            if "|" in org_str:
                matchup = re.search( r"([A-Za-z0-9 .'-]+)\s+vs\s+([A-Za-z0-9 .'-]+)", org_str, re.IGNORECASE)
            else:
                matchup = re.search( r'\d+\s+(.+?)\s+vs\s+(.+?)\s+\d+', org_str, re.IGNORECASE)

            home_team = re.findall(r'\D+', matchup.group(1))
            away_team =  re.findall(r'\D+', matchup.group(2))
            # 去掉多余的前后空格
            home_team = [home_team_str_i.strip() for home_team_str_i in home_team]
            away_team = [away_team_str_i.strip() for away_team_str_i in away_team]
            # 去掉长度过短的字符串
            min_len = 4
            home_team = [home_team_str_i for home_team_str_i in home_team if len(home_team_str_i) >= min_len]
            away_team = [away_team_str_i for away_team_str_i in away_team if len(away_team_str_i) >= min_len]
            logger.info(f"成功匹配到对阵信息：{home_team} vs {away_team}")
        except Exception as err:
            logger.warn("未成功匹配到对阵信息，跳过")
            return None

        # 获取比赛相关元数据
        raw_matchdata = self.get_match_raw_metadata(competition_cn_name, season, home_team, away_team)
        if not raw_matchdata:
            logger.warn("未获取到比赛元数据，跳过")
            return None

        # 解析轮次信息
        try:
            round_info = raw_matchdata['matchday']
            round_cn_name = f"第{self.number_to_chinese(round_info)}轮"
            round_en_name = f"Round {round_info}"
            logger.info(f"成功匹配到轮次信息：{round_cn_name}")
        except Exception as err:
            logger.warn("未成功匹配到轮次信息，跳过")
            return None

        # 解析对阵信息
        home_team = raw_matchdata['homeTeam']['name']
        away_team = raw_matchdata['awayTeam']['name']
        matchmake_en_name = matchmake_cn_name = f"{home_team} vs {away_team}"

        # 刮削比赛信息
        match_metainfo.cn_name = " - ".join([competition_cn_name, season_cn_name, round_cn_name, matchmake_cn_name])
        match_metainfo.en_name = " - ".join([competition_en_name, season_en_name, round_en_name, matchmake_en_name])
        match_metainfo.set_season(season)
        match_metainfo.set_episode(round_info)
        match_metainfo.set_episodes(round_info,round_info)
        match_metainfo.subtitle = ""
        match_metainfo.title = competition_cn_name

        return match_metainfo

    def recognize_competition_mediainfo(self, torrent_info: TorrentInfo, meta_info: MetaBase) -> MediaInfo | None:
        """
          根据自定义规则刮削赛事信息
        """
        competition_mediainfo = MediaInfo()

        title = torrent_info.title

        for match_parse in self.__match_parses:
            if any(alia in title for alia in match_parse["names"]):
                # 匹配任意一个别名，开始解析
                self.scrape_competition(competition_mediainfo, match_parse)
                competition_mediainfo.type = MediaType.TV
                competition_mediainfo.season = meta_info.year
                competition_mediainfo.category = self.__category
                break
            else:
                continue

        if not competition_mediainfo.title:
            # 未成功刮削，返回空对象
            logger.info(f"未识别到赛事信息")
            return None

        # 成功刮削，返回刮削后对象
        logger.info(f"成功匹配到赛事信息：{competition_mediainfo.title}")
        return competition_mediainfo

    @dataclass
    class Matchinfo:
        """
          比赛相关信息
        """
        torrentinfo: TorrentInfo = None
        mediainfo: MediaInfo = None
        metainfo: MetaVideo = None
        language: str = None
        pix: int = 0

    @staticmethod
    def find_best(force_en: bool = False, lowest_pix: int = 0, matchesinfo: list[Matchinfo] = None, new_matchinfo: Matchinfo = None):
        """
          判断传入的种子是否比现有的优先级更高
        """
        if (force_en and new_matchinfo.language != "en") or new_matchinfo.pix < lowest_pix:
            # 不满足约束条件，直接退出
            return

        # 判断之前是否已搜索到该场比赛的种子
        for i, old_matchinfo in enumerate(matchesinfo):
            if new_matchinfo.metainfo.name == old_matchinfo.metainfo.name:
                if new_matchinfo.language == "en" and old_matchinfo.language != "en":
                    matchesinfo[i] = new_matchinfo
                    logger.info(f"新种子 ({new_matchinfo.torrentinfo.title}) 的解说语言为英语，而之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) 不是，替换")
                elif new_matchinfo.pix > old_matchinfo.pix:
                    matchesinfo[i] = new_matchinfo
                    logger.info(f"新种子 ({new_matchinfo.torrentinfo.title})的清晰度高于之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) ，替换")
                else:
                    logger.info(f"新种子 ({new_matchinfo.torrentinfo.title}) 不如之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) ，不替换")
                return

        # 如果已有种子列表中没有该场比赛，则添加之
        matchesinfo.append(new_matchinfo)
        return


    @staticmethod
    def extract_date(s: str):
        """
            从种子名中提取日期
        """
        date_re = re.compile(
            r"""
            \b
            (?:                                  # 非捕获组：两种顺序
                ((?:19|20)\d{2})\s+(\d{1,2})\s+(\d{1,2})   # YYYY MM DD
              |
                (\d{1,2})\s+(\d{1,2})\s+((?:19|20)\d{2})   # DD MM YYYY
            )
            \b
            """,
            re.VERBOSE
        )

        m = date_re.search(s)
        if not m:
            return None

        if m.group(1):  # YYYY MM DD
            year, month, day = m.group(1), m.group(2), m.group(3)
        else:  # DD MM YYYY
            year, month, day = m.group(6), m.group(5), m.group(4)

        return int(year), int(month), int(day)


    @staticmethod
    def recognize_language(metainfo: MetaVideo) -> str:
        if "EN" in metainfo.name:
            return "en"
        elif "PL" in metainfo.name or "Polilsh" in metainfo.name:
            return "pl"
        elif "Spanish" in metainfo.name:
            return "sp"
        # 默认英语
        return "en"


    @staticmethod
    def chinese_to_number(chinese_num: str) -> int:
        """
        将中文大写数字（如 第二十三季）转换为阿拉伯数字
        """
        char_to_digit = {
            '零': 0,
            '一': 1,
            '二': 2,
            '两': 2,
            '三': 3,
            '四': 4,
            '五': 5,
            '六': 6,
            '七': 7,
            '八': 8,
            '九': 9,
            '十': 10,
            '百': 100,
            '千': 1000,
            '万': 10000,
            '亿': 100000000
        }

        # 去除“第X季”的格式
        if chinese_num.startswith("第") and chinese_num.endswith("季"):
            chinese_num = chinese_num[1:-1]

        current_value = 0
        prev_value = 0

        i = 0
        while i < len(chinese_num):
            char = chinese_num[i]
            value = char_to_digit.get(char, None)

            if value is None:
                raise ValueError(f"不支持的字符：{char}")

            if value in [10, 100, 1000]:  # 处理“十百千”
                if prev_value == 0:
                    prev_value = 1  # 如“十五”中“十”前无数字，默认为1
                current_value += prev_value * value
                prev_value = 0
            else:
                prev_value = value
            i += 1

        current_value += prev_value  # 加上最后的个位数
        return current_value

    @staticmethod
    def number_to_chinese(num: int) -> str:
        """
        将阿拉伯数字转换为中文大写数字表示

        支持将整数转换为对应的中文字符表达，包括零、一到九的基础数字，
        以及十、百、千、万、亿等单位组合。适用于需要将数字以中文形式展示的场景。

        参数:
            num (int): 需要转换的整数

        返回:
            str: 转换后的中文大写数字字符串

        示例:
            输入: 1234
            输出: "一千二百三十四"
        """
        if num == 0:
            return "零"

        # 定义基础数字和单位
        digits = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
        units = ["", "十", "百", "千"]  # 十进制单位
        large_units = ["", "万", "亿", "万亿"]  # 大单位

        def chunk(number: int) -> str:
            """
            将小于10000的数字分解并转换为中文表示

            参数:
                number (int): 小于10000的整数

            返回:
                str: 中文表示的字符串片段
            """
            res = ""
            count = 0
            while number > 0:
                digit = number % 10
                if digit != 0:
                    res = digits[digit] + units[count] + res
                else:
                    # 处理连续的零，避免出现多个“零”
                    if res and res[0] != '零':
                        res = '零' + res
                number //= 10
                count += 1
            return res

        result = ""
        chunk_index = 0
        while num > 0:
            part = num % 10000
            if part != 0:
                # 对每个不超过10000的部分进行处理，并加上对应的大单位
                result = chunk(part) + large_units[chunk_index] + result
            num //= 10000
            chunk_index += 1

        # 特殊情况处理，如"一十"应简化为"十"
        if result.startswith("一十"):
            result = result[1:]

        return result

    @staticmethod
    def __get_redict_url(url: str, proxies: str = None, ua: str = None, cookie: str = None) -> Optional[str]:
        """
        获取下载链接， url格式：[base64]url
        """
        # 获取[]中的内容
        m = re.search(r"\[(.*)](.*)", url)
        if m:
            # 参数
            base64_str = m.group(1)
            # URL
            url = m.group(2)
            if not base64_str:
                return url
            # 解码参数
            req_str = base64.b64decode(base64_str.encode('utf-8')).decode('utf-8')
            req_params: Dict[str, dict] = json.loads(req_str)
            # 是否使用cookie
            if not req_params.get('cookie'):
                cookie = None
            # 请求头
            if req_params.get('header'):
                headers = req_params.get('header')
            else:
                headers = None
            if req_params.get('method') == 'get':
                # GET请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).get_res(url, params=req_params.get('params'))
            else:
                # POST请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).post_res(url, params=req_params.get('params'))
            if not res:
                return None
            if not req_params.get('result'):
                return res.text
            else:
                data = res.json()
                for key in str(req_params.get('result')).split("."):
                    data = data.get(key)
                    if not data:
                        return None
                logger.debug(f"获取到下载地址：{data}")
                return data
        return None

    def __download(self, torrent: TorrentInfo) -> tuple[bool, Optional[str]]:
        """
        添加下载任务

        return: (下载器中是否已存在，已存在/新创建的下载任务的 Hash 值)
        """
        if not torrent.enclosure:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return False, None

        # 保存地址
        download_dir = self.__save_path or None
        # 获取下载链接
        torrent_content = torrent.enclosure
        # proxies
        proxies = settings.PROXY if torrent.site_proxy else None
        # cookie
        cookies = torrent.site_cookie
        if torrent_content.startswith("["):
            torrent_content = self.__get_redict_url(url=torrent_content,
                                                    proxies=proxies,
                                                    ua=torrent.site_ua,
                                                    cookie=cookies)
            # 目前馒头请求实际种子时，不能传入Cookie
            cookies = False, None
        if not torrent_content:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return False, None

        # TODO: 支持多下载器
        downloader = self.__downloader
        if not downloader:
            return False, None

        downloader_helper = DownloaderHelper()
        if downloader_helper.is_downloader("qbittorrent", service=self.__service_info):
            # 生成随机Tag
            random_tag = StringUtils.generate_random_str(10)
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            if not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=cookies,
                                        proxies=proxies,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error("尝试通过 MP 下载种子失败，继续尝试传递种子地址到下载器进行下载")
            if torrent_content:
                existed_torrents = downloader.get_torrents(tags=["AutoSports"])
                # 判断是否已添加该任务
                if existed_torrents:
                    for torrent_data in existed_torrents[0]:
                        torrent_name = torrent_data.get("name")
                        if torrent.title in torrent_name:
                            torrent_hash = torrent_data.get("hash")
                            return True, torrent_hash
                state = downloader.add_torrent(content=torrent_content,
                                               download_dir=download_dir,
                                               is_paused=True,  # 调试用
                                               cookie=cookies,
                                               category=self.__category,
                                               tag=self.__tags + ["AutoSports"] + [random_tag], )
                if not state:
                    return False, None
                else:
                    # 获取种子Hash
                    torrent_hash = downloader.get_torrent_id_by_tag(tags=random_tag)
                    if not torrent_hash:
                        logger.error(f"{self.__downloaders} 获取种子 Hash 失败")
                        return False, None
                    downloader.remove_torrents_tag([torrent_hash], random_tag)
                    return False, torrent_hash
            return False, None

        elif downloader_helper.is_downloader("transmission", service=self.__service_info):
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            if not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=cookies,
                                        proxies=proxies,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error("尝试通过 MP 下载种子失败，继续尝试传递种子地址到下载器进行下载")
            if torrent_content:
                torrent = downloader.add_torrent(content=torrent_content,
                                                 download_dir=download_dir,
                                                 is_paused=True,  # 调试用
                                                 cookie=cookies,
                                                 labels=self.__tags)
                if not torrent:
                    return None
        return None

    def __log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message, title="自定义订阅")

    def __validate_and_fix_config(self, config: dict = None) -> bool:
        """
        检查并修正配置值
        """
        size_range = config.get("size_range")
        if size_range and not self.__is_number_or_range(str(size_range)):
            self.__log_and_notify_error(f"自定义订阅出错，种子大小设置错误：{size_range}")
            config["size_range"] = None
            return False
        return True

    @staticmethod
    def __is_number_or_range(value):
        """
        检查字符串是否表示单个数字或数字范围（如'5', '5.5', '5-10' 或 '5.5-10.2'）
        """
        return bool(re.match(r"^\d+(\.\d+)?(-\d+(\.\d+)?)?$", value))

