import base64
import json
import math
import os
import threading
from copy import deepcopy
from dataclasses import fields, dataclass
from pathlib import Path
from platform import machine
from re import match
from threading import Lock
from types import NoneType
from typing import List, Tuple, Dict, Any, Union
from xml.dom import minidom

from PIL import Image
from cachetools import cached, TTLCache
from docker.utils.config import home_dir
from langsmith import expect
from six import reraise

from app.api.endpoints.dashboard import downloader
from app.api.endpoints.media import seasons
from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.search import SearchChain
from app.chain.storage import StorageChain
from app.chain.subscribe import SubscribeChain
from app.chain.transfer import job_lock
from app.core.config import settings
from app.core.meta import MetaVideo, MetaBase
from app.core.meta.words import WordsMatcher
from app.core.metainfo import MetaInfo, MetaInfoPath
from app.core.context import MediaInfo, Context, TorrentInfo
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import MediaType, ServiceInfo, TransferDirectoryConf, TmdbEpisode, TransferInfo, FileURI, FileItem
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

from app.utils.dom import DomUtils
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.utils.system import SystemUtils
from directory import DirectoryHelper
from downloader import DownloaderHelper

lock = Lock()
ffmpeg_lock = threading.Lock()

class AutoSports(_PluginBase):
    # 插件名称
    plugin_name = "Sportscult 比赛自动下载及简单刮削"
    # 插件描述
    plugin_desc = "根据设置的球队名自动下载最新比赛，进行文件整理及简单的刮削"
    # 插件图标
    plugin_icon = "https://cdn-icons-png.flaticon.com/512/857/857492.png"
    # 插件版本
    plugin_version = "0.8.0"
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
    __start_pause: bool = True  # 添加种子后暂停下载
    __max_download: int = 0  # 单次最多下多少场比赛
    # 转移与刮削相关
    __target_path: str = ""
    __transfer_type: str = ""
    __need_rename: bool = True
    __downloaders = None
    __scheduler: BackgroundScheduler = None
    __timeline = "00:00:10"
    __matches = {}
    # 订阅缓存信息
    __cached_matches = {}

    # 赛事刮削信息
    # 自定义映射关系
    __competitions_parses = [
        {
            "names": ["西甲", "La Liga", "LaLiga", "Laliga"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "PD",  # 缩写
            "title": "西班牙足球甲级联赛",  # 中文名
            "en_title": "La Liga",  # 英文名
            "year": 1929,  # 创办年份
            "overview": "西班牙足球甲级联赛（西班牙语：Primera División de España或La Liga，由于赞助原因，正式名称为LALIGA EA SPORTS），通常简称西甲或西甲联赛，是西班牙足球联赛系统的第 1 级别，亦是职业联赛的最高级别、联赛系统的最高级别和西班牙顶级足球联赛，目前有 20 支球队。皇家马德里是历史上夺得最多冠军的球队（36次），其次是巴塞罗那（28次），以及马德里竞技（11次）。 ",  # 赛事介绍
            "season_years": {x: x for x in range(1929, 2101)},  # 赛季
            "homepage": "https://www.laliga.com",  # 官网
            "languages": "Spanish",  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": "西班牙皇家足球协会 (RFEF)",  # 创办协会
            "production_countries": "Spain",  # 国家
            "spoken_languages": "Spanish",  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["欧洲冠军联赛", "Champions League", "UCL", "UEFA Champions League"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "CL",  # 缩写
            "title": "欧洲冠军联赛",  # 中文名
            "en_title": "UEFA Champions League",  # 英文名
            "year": 1955,  # 创办年份
            "overview": "欧洲冠军联赛（英语：UEFA Champions League，缩写：UCL；简称欧冠联赛、欧冠）是欧洲足联主办的年度俱乐部足球比赛，该赛事由欧洲顶级联赛的俱乐部队伍参加，通过联赛阶段和双回合淘汰赛，以及单场决赛的形式决出冠军。代表欧洲俱乐部足球最高荣誉，被誉为全世界最高竞技水平的俱乐部杯赛，估计每届赛事约有超过十亿电视观众观看赛事，现与欧洲联赛和欧协联并称“欧洲俱乐部三大杯”。 "
                        "欧洲冠军联赛始创于1955年，被称为“欧洲俱乐部冠军杯”（法语：Coupe des Clubs Champions Européens），通称欧洲冠军杯（英语：European Cup）。最初，该赛事以直接淘汰制形式进行，并仅对欧洲各国的联赛冠军开放。随后在1991年引入小组赛环节，并于1992年更为现名。自1997-98赛季起，部分国家可派出最多4支球队参赛。目前，大部分欧洲国家仅能派出其联赛冠军参赛，而实力较强的联赛最多可派出四支球队。未能晋级欧冠的俱乐部有资格参加欧洲联赛及自2021年起举办的欧洲协会联赛。"
                        "现行赛制从六月下旬开始，包括三轮资格赛和一轮附加赛，均采用双回合制。六支晋级球队进入联赛阶段，与提前获得资格的30支球队会合。36支球队会透过以瑞士制为基础的联赛模式定出晋级淘汰赛阶段的球队（在联赛阶段取得首八名的球队直接晋级，余下八队会经淘汰附加赛决定）最终在五月底或六月初的决赛中决出冠军。赛事冠军将自动获得参加下一年度欧洲冠军联赛、欧洲超级杯及俱乐部世界杯的参赛资格。"
                        "在欧冠历史上，西班牙俱乐部以20次冠军居于榜首，英格兰和意大利分别以15次和12次获胜紧随其后。英格兰拥有最多的获胜球队，共六家俱乐部赢得冠军。迄今为止，共有23家俱乐部夺冠，其中13家俱乐部多次夺冠，8家成功卫冕。皇家马德里是该赛事历史上最成功的俱乐部，共赢得了15次冠军，包括首五届赛事冠军和最近十一届中的六次。只有拜仁慕尼黑以全胜战绩（2019–20赛季）夺得冠军。巴黎圣日耳曼是现任冠军，他们在2025年5月31日决赛中以5–0击败国际米兰，首次赢得冠军。",
            "season_years": {x: x for x in range(1955, 2101)},  # 赛季
            "homepage": "https://www.uefa.com",  # 官网
            "languages": "English",  # 解说源语言
            "origin_country": "Europa",  # 国家
            "original_name": "UEFA Champions League",  # 原名
            "production_companies": "欧洲足球协会联盟 (UEFA)",  # 创办协会
            "production_countries": "Europa",  # 国家
            "spoken_languages": "English",  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["西班牙国王杯", "Copa Del Rey", "Campeonato de España – Copa de Su Majestad el Rey"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "CDR",  # 缩写
            "title": "西班牙国王杯",  # 中文名
            "en_title": "Copa Del Rey",  # 英文名
            "year": 1903,  # 创办年份
            "overview": "西班牙冠军–国王陛下杯（西班牙语：Campeonato de España – Copa de Su Majestad el Rey），通称国王杯（Copa del Rey）或西班牙杯，是西班牙一项每年举办的淘汰制足球赛事。赛事开办起因于皇家马德里前主席卡洛斯·帕德罗斯提议举办一项足球赛事以庆祝西班牙国王阿方索十三世登基，而于1902年举行首届比赛。"
                        "赛事最早叫做“马德里市议会杯”（Copa del Ayuntamiento de Madrid），1905至1932年间称为“阿方索十三世杯”（Copa de S.M. El Rey Alfonso XIII），在西班牙第二共和国期间则称为“共和国总统杯”Copa del Presidente de la República），简称“西班牙杯” （Copa de España），在佛朗哥执政期间又改称为 “大元帅阁下杯”（Copa de Su Excelencia El Generalísimo） ，简称“大元帅杯”（Copa del Generalísimo)。",
            "season_years": {x: x for x in range(1903, 2101)},  # 赛季
            "homepage": "https://www.laliga.com/en-GB/other-competitions/copa-del-rey",  # 官网
            "languages": "Spanish",  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": "西班牙皇家足球协会 (RFEF)",  # 创办协会
            "production_countries": "Spain",  # 国家
            "spoken_languages": "Spanish",  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {  # 本地刮削信息（空表示不进行本地刮削）
                "group": 0,  # 小组赛比赛场次
                "knockout_single": 32,  # 单场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
                "knockout_double": 4  # 主客场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
            },
        },
        {
            "names": ["西班牙超级杯", "Supercopa de España", "Spanish Super Cup", "SuperCopa"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "SE",  # 缩写
            "title": "西班牙超级杯",  # 中文名
            "en_title": "Spanish Super Cup",  # 英文名
            "year": 1982,  # 创办年份
            "overview": "西班牙超级杯（西班牙语：Supercopa de España）是西班牙每年一度由甲级联赛冠军对国王杯盟主的足球锦标赛，如果有一支球队同时夺得联赛及国王杯冠军，对赛球队则由国王杯亚军补上，2019年起增设联赛及国王杯亚军席位，如果有一支球队同时夺得联赛及国王杯冠亚军，对赛球队则由联赛排名较佳一方补上，改制成单场淘汰赛模式。首届赛事于1940年举行，作为每年球季开始前的揭幕战。 "
                        "赛事早期曾经有过多个名称，首届赛事举行时名称为西班牙冠军杯（Copa de Campeones），但比赛直到1945年才又再举办，这时由于来自阿根廷的大使欲与西班牙打好友谊关系，遂以阿根廷金杯（Copa de Oro Argentina）为名举行比赛。1947年，为了庆祝胡安·裴隆成为阿根廷总统，而以其妻子伊娃·裴隆为名举行伊娃杯（Copa Eva Duarte）。可惜1953年之后球赛因为不受重视而停办，一直到1983年才又重新复办赛事，并正式将球赛命名为西班牙超级杯至今。 ",
            "season_years": {x: x for x in range(1982, 2101)},  # 赛季
            "homepage": "https://www.laliga.com/en-GB/other-competitions/supercopa-de-espana",  # 官网
            "languages": "Spanish",  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": "西班牙皇家足球协会 (RFEF)",  # 创办协会
            "production_countries": "Spain",  # 国家
            "spoken_languages": "Spanish",  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {  # 本地刮削信息（空表示不进行本地刮削）
                "group": 0,  # 小组赛比赛场次
                "knockout_single": 4,  # 单场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
                "knockout_double": 0  # 主客场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
            },

        },
    ]

    knockout_parse = {  # 杯赛 -> 参赛球队数映射表
        # Final
        r"\bfinal\b": 2,

        # Semi Final
        r"\bsemi[\s-]?final\b|\bsf\b": 4,

        # Quarter Final
        r"\bquarter[\s-]?final\b|\bqf\b": 8,

        # Round of 16
        r"\br16\b|\bround\s+of\s+16\b": 16,

        # Round of 32
        r"\br32\b|\bround\s+of\s+32\b": 32,
    }

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
            self.__dest_path = config.get("dest_path")
            self.__downloaders = config.get("downloaders")
            self.__transfer_type = config.get("transfer_type") or "link"
            self.__start_paused = config.get("start_paused")
            self.__max_download = int(config.get("max_download")) if config.get("max_download") else 0
            if config.get("need_rename"):
                self.__need_rename = config.get("need_rename")
            else:
                self.__need_rename = True
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
                "id": "AutoSports",
                "name": "自动下载体育比赛服务",
                "trigger": CronTrigger.from_crontab(self.__cron),
                "func": self.check,
                "kwargs": {}
            }]
        elif self.__enabled:
            return [{
                "id": "AutoSports",
                "name": "自动下载体育比赛服务",
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
                                            'model': 'force_en',
                                            'label': '是否只下载英文解说版本',
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
                                            'model': 'need_rename',
                                            'label': '是否开启自动重命名',
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
                                            'model': 'start_paused',
                                            'label': '以暂停状态添加种子（推荐首次使用时先看看有没有问题）',
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
                                            'model': 'football_apikey',
                                            'label': '比赛元数据 API key (请前往 football-data.org 自行获取)',
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'teams_info',
                                            'label': '关注球队名，请输入关注球队的名称，只能输一个（英文，关键字即可）',
                                            'rows': 3,
                                            'placeholder': 'Barcelona'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'max_download',
                                            'label': '单次运行最大下载比赛场数',
                                            'rows': 3,
                                            'placeholder': '3'
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
                                            'label': '最低清晰度(p)，请输入整数',
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
                                            'label': '种子额外标签，以逗号隔开，留空为不设置（默认有 AutoSports 标签）',
                                            'placeholder': '如：Sportscult,Football'
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'transfer_type',
                                            'label': '转移方式',
                                            'items': [
                                                {'title': '移动', 'value': 'move'},
                                                {'title': '复制', 'value': 'copy'},
                                                {'title': '硬链接', 'value': 'link'},
                                                {'title': '软链接', 'value': 'softlink'},
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
                                            'label': '下载目录',
                                            'placeholder': '下载时有效'
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
                                            'model': 'dest_path',
                                            'label': '转移目录',
                                            'placeholder': '下载时有效'
                                        }
                                    }
                                ]
                            },
                        ]
                    },
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
            "dest_path": "",
            "category": "",
            "tags": [],
            "size_range": "",
            "force_en": False,
            "lowest_px": "720",
            "transfer_type": "link",
            "need_rename": True,
            "max_download": 3,
            "start_paused": True
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
                                    'api': 'plugin/AutoSports/delete_history',
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

    def delete_history(self, key: str, apikey: Optional[str]):
        """
        删除同步历史记录
        """
        # if apikey != settings.API_TOKEN:
        #     return schemas.Response(success=False, message="API密钥错误")
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
            "dest_path": self.__dest_path,
            "category": self.__category,
            "tags": self.__tags,
            "size_range": self.__size_range,
            "downloaders": self.__downloaders,
            "force_en": self.__force_en,
            "lowest_pix": self.__lowest_pix,
            "transfer_type": self.__transfer_type,
            "need_rename": self.__need_rename,
            "start_paused": self.__start_paused,
            "max_download": self.__max_download,
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

        # 开始全量同步目录中所有体育比赛文件
        self.sync_all()
        logger.info("文件同步结束")
        # return

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

            # 清空比赛元数据缓存
            if not self.__cached_matches:
                self.__cached_matches = {}

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
                        logger.info("已处理过该种子，请清除记录后重试")
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
                    gotten_match_metainfo, _ = self.recognized_match_metainfo(gotten_match_mediainfo, gotten_metainfo)
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
                    logger.error(f'自动下载体育比赛出错：{str(err)} - {traceback.format_exc()}')

            # 新增处理的比赛场数计数
            added_num = 0

            for final_matchinfo in matchesinfo:
                if self.__max_download and added_num >= self.__max_download:
                    logger.info(f"已添加种子数量超过最大限制 {self.__max_download}，不再添加新的种子")
                    break
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
                        continue
                        # continue
                    elif is_existed:
                        logger.info(f'{title} 已存在，种子 HASH 值为：{torrent_hash}')
                        added_num += 1
                    else:
                        logger.info(f'{title} 下载成功，种子 HASH 值为：{torrent_hash}')
                        added_num += 1
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
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            logger.info(f"体育比赛下载刷新完成")
        # 保存历史记录
        self.save_data('history', history)

        # 缓存只清理一次
        self.__clearflag = False


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


    def sync_all(self):
        """
        立即运行一次，全量同步目录中所有文件
        """
        logger.info(f"开始全量同步体育比赛监控目录 {self.__save_path} ...")
        # 遍历下载目录
        for file_path in SystemUtils.list_files(Path(self.__save_path), settings.RMT_MEDIAEXT):
            logger.info(f"开始处理文件 {file_path} ...")
            self.__handle_file(is_directory=Path(file_path).is_dir(),
                               event_path=str(file_path),
                               source_dir=self.__save_path)
        logger.info("全量同步体育比赛监控目录完成！")


    def gen_file_thumb(self, title: str, file_path: Path, rename_conf: bool):
        """
        处理一个文件
        """
        # 单线程处理
        if rename_conf:
            with ffmpeg_lock:
                try:
                    thumb_path = file_path.with_name(f"{title}_thumb.jpg")
                    if thumb_path.exists():
                        logger.info(f"缩略图已存在：{title}_thumb.jpg")
                        return
                    self.get_thumb(video_path=str(file_path),
                                   image_path=str(thumb_path),
                                   frames=self.__timeline)
                    if Path(thumb_path).exists():
                        logger.info(f"{file_path} 缩略图已生成：{title}_thumb.jpg")
                        return thumb_path
                except Exception as err:
                    logger.error(f"FFmpeg处理文件 {file_path} 时发生错误：{str(err)}")
                    return None


    def scrape_competition(self, matchinfo: MediaInfo, competition_parse: {}):
        """
          根据给定的 JSON 规则刮削体育比赛
        """
        for f in fields(matchinfo):
            if f.name in competition_parse:
                setattr(matchinfo, f.name, competition_parse[f.name])
        pass


    def get_match_raw_metadata_offline(self, metainfo: MetaVideo = None, matched_competition_parse: json = None,
                                       season:int = 0, home_team: str = '', away_team: str = ''):
        """
            从本地定义的元数据中获取比赛信息
        """
        match = {
            "competition":{
                "type": matched_competition_parse.get("type"),
            },
            "stage": 'KNOCKOUT_STAGE',
            "matchday": 0,
            "round_cn_name": "",
            "round_en_name": "",
            "homeTeam": {
                "name": "",
            },
            "awayTeam": {
                "name": "",
            },
        }

        match_org_title = metainfo.org_string
        match_org_title = match_org_title.lower()
        offline_info = matched_competition_parse.get("offline_info")

        # 包装比赛日信息
        # 计算比赛轮次
        match_org_title = match_org_title.lower()

        for pattern, team_count in self.knockout_parse.items():
            if re.search(pattern, match_org_title, re.IGNORECASE):
                single_start_num = offline_info.get("knockout_single")
                double_start_num = offline_info.get("knockout_double")
                if offline_info.get('knockout_double') < team_count:
                    # 还没到主客场淘汰赛阶段
                    match["matchday"] = int(math.sqrt(single_start_num / team_count))
                    match["round_cn_name"] = f"{self.number_to_chinese(team_count)}强赛"
                    match["round_en_name"] = f"R{self.number_to_chinese(team_count)}"
                    if team_count == 4:
                        # 判断是否为半决赛
                        match["round_cn_name"] = f"半决赛"
                        match["round_en_name"] = f"Semi Finals"
                    if team_count == 2:
                        # 决赛
                        match["round_cn_name"] = f"决赛"
                        match["round_en_name"] = f"The Final"
                else:
                    # 到了主客场双淘汰赛阶段
                    match["matchday"] = (int(math.sqrt(single_start_num / double_start_num)) +
                                         int(math.sqrt(double_start_num / team_count)) * 2 - 1)
                    match["round_cn_name"] = f"{self.number_to_chinese(team_count)}强赛"
                    match["round_en_name"] = f"R{self.number_to_chinese(team_count)}"
                    if team_count == 4:
                        # 判断是否为半决赛
                        match["round_cn_name"] = f"半决赛 首回合"
                        match["round_en_name"] = f"Semi Finals 1st Round"
                        if re.search(pattern, r'\b(?:leg\s*(?:2|2nd)|(?:2|2nd)\s*leg)\b', re.IGNORECASE):
                            match["matchday"] += 1
                            match["round_cn_name"] = f"半决赛 次回合"
                            match["round_en_name"] = f"Semi Finals 2st Round"
                    if team_count == 2:
                        # 决赛
                        match["round_cn_name"] = f"决赛"
                        match["round_en_name"] = f"The Final"

        if match["matchday"] == 0:
            logger.warning(f"轮次未识别成功，建议手动修订: {metainfo.title}")
        logger.info(f"识别到轮次：{match["matchday"]}")


        # 包装对阵信息
        match['homeTeam']['name'] = home_team
        match['awayTeam']['name'] = away_team

        return match



    def get_match_raw_metadata_online(self, competition_shortname: str = '', season:int = 0, home_team: list[str] = '', away_team: list[str] = ''):
        """
            从 football-data.org 获取比赛信息
        """
        import requests

        headers = {"X-Auth-Token": self.__football_apikey}

        timeout = (30, 30)

        url = f"https://api.football-data.org/v4/competitions/{competition_shortname}/matches"
        params = {
            "season": season
        }

        requests_key = competition_shortname + "_" + str(season)
        # 判断当前订阅是否已经在缓存中，如果已经处理过，那么这里直接跳过
        if requests_key in self.__cached_matches.keys():
            data = self.__cached_matches.get(requests_key)
            logger.info(f"从缓存 {requests_key} 中读取 football-data.org 赛事数据...")
        else:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            logger.info(f"从 {url} 中读取 football-data.org 赛事数据...")
            data = resp.json()
            self.__cached_matches[requests_key] = data

        for match in data["matches"]:
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]

            if any(home_team_i in home for home_team_i in home_team) and any(
                away_team_i in away for away_team_i in away_team):
                return match

        return None


    def get_match_raw_metadata(self, metainfo: MetaVideo = None, competition_name:str = '', season:int = 0, home_team: list[str] = '', away_team: list[str] = ''):
        """
          刮削单场比赛元数据
        """
        if not metainfo or not competition_name or not season or not home_team or not away_team:
            logger.error(f'缺少必须比赛信息，无法进行刮削，'
                         f'metainfo: {metainfo}, competition_name: {competition_name}，'
                         f'season: {season}, home_team: {home_team}, away_team: {away_team}')
            return None

        matched_competition_parse = {}
        competition_shortname = ''
        competition_offline_info = {}

        # 寻找比赛缩写
        for competition_parse in self.__competitions_parses:
            if competition_name == competition_parse["title"]:
                matched_competition_parse = competition_parse
                competition_shortname = competition_parse.get("shortname")
                competition_offline_info = competition_parse.get("offline_info")
                break
            else:
                continue

        # 判断是进行在线刮削还是离线刮削
        if not competition_offline_info:
            # 未定义离线信息，在线刮削
            logger.info(f"在线刮削赛事 {competition_name} 中的比赛")
            match_result = self.get_match_raw_metadata_online(competition_shortname, season, home_team, away_team)
        else:
            # 定义离线信息，离线刮削
            logger.info(f"离线刮削赛事 {competition_name} 中的比赛")
            match_result = self.get_match_raw_metadata_offline(metainfo, matched_competition_parse, season, home_team[0], away_team[0])

        if match_result:
            return match_result
        else:
            logger.error(f'未匹配到相关比赛，请检查输入信息，competition_name: {competition_name}，season: {season}, home_team: {home_team}, away_team: {away_team}')
            return None


    def recognized_match_metainfo(self, match_mediainfo: MediaInfo, metainfo: MetaBase) -> (MetaVideo | None, TmdbEpisode | None) :
        """
          根据给定的规则刮削单场比赛信息
        """
        match_metainfo = deepcopy(metainfo)
        episode_metainfo = TmdbEpisode()

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
                if match_mediainfo.title == "西班牙超级杯":
                    season -= 1
            # 年份信息回填赛事元数据
            metainfo.year = str(season)

            season_shortname = season % 100
            # 解析赛季信息
            season_cn_name = f"{season_shortname:02d}-{(season_shortname + 1):02d}赛季"
            season_en_name = f"Season {season_shortname:02d}-{(season_shortname + 1):02d}"
            logger.info(f"成功匹配到赛季信息：{season_cn_name}")
        except Exception as err:
            logger.warn("未成功匹配到赛季信息，跳过")
            return None, None

        # 分析主客场球队
        try:
            # 匹配对阵信息
            # matchup = re.search( r"([A-Za-zÀ-ÿ. ]+?)\s+vs\s+([A-Za-zÀ-ÿ. ]+?)(?=\s*\||\s+\d|$)", org_str, re.IGNORECASE)
            # matchup = re.search( r"([A-Za-zÀ-ÿ. ]+?)\s+vs\s+([A-Za-zÀ-ÿ. ]+?)(?=\s*\||\s+\d|$)", org_str, re.IGNORECASE)
            matchup = re.search( r'([A-Za-zÀ-ÿ ]+?)\s+vs\s+([A-Za-zÀ-ÿ ]+?)(?=\s*\||\s+\d|\.|$)', org_str, re.IGNORECASE)

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
            return None, None

        # 获取比赛相关元数据
        raw_matchdata = self.get_match_raw_metadata(metainfo, competition_cn_name, season, home_team, away_team)
        if not raw_matchdata:
            logger.warn("未获取到比赛元数据，跳过")
            return None, None

        # 解析轮次信息
        # 根据赛事类型决定解析方式
        if raw_matchdata['competition']['type'] != 'CUP':
            # 联赛，比赛日即为轮次
            try:
                round_info = raw_matchdata['matchday']
                round_cn_name = f"第{self.number_to_chinese(round_info)}轮"
                round_en_name = f"Round {round_info}"
                logger.info(f"成功匹配到轮次信息：{round_cn_name}")
            except Exception as err:
                logger.warn("未成功匹配到轮次信息，跳过")
                return None, None
        else:
            round_info = raw_matchdata['matchday']
            if raw_matchdata['stage'] == 'LEAGUE_STAGE':
                # 小组赛阶段
                round_cn_name = f"小组赛 第{self.number_to_chinese(round_info)}轮"
                round_en_name = f"Group Stage Round {round_info}"
            else:
                # 淘汰赛阶段
                round_cn_name_list = [
                    "32强赛 首回合", "32强赛 次回合",
                    "16强赛 首回合", "16强赛 次回合",
                    "8强赛 首回合", "8强赛 次回合",
                    "半决赛 首回合", "半决赛 次回合",
                    "决赛"
                ]
                round_en_name_list = [
                    "R32 1st Round", "R32 2nd Round",
                    "R16 1st Round", "R16 2nd Round",
                    "R8 1st Round", "R8 2nd Round",
                    "Semi Finals 1st Round", "Semi Finals 2nd Round",
                    "Final"
                ]
                if competition_cn_name == "欧洲冠军联赛":
                    # 欧冠赛制特殊处理
                    if raw_matchdata['matchday'] == 9:
                        round_cn_name = f"小组赛附加赛 首回合"
                        round_en_name = f"Play-off 1st Round"
                    elif raw_matchdata['matchday'] == 10:
                        round_cn_name = f"小组赛附加赛 次回合"
                        round_en_name = f"Play-off 2nd Round"
                    else:
                        round_idx = raw_matchdata['matchday'] - 10 + 2 - 1
                        round_cn_name = round_cn_name_list[round_idx]
                        round_en_name = round_en_name_list[round_idx]
                else:
                    round_cn_name = raw_matchdata['round_cn_name']
                    round_en_name = raw_matchdata['round_en_name']

        # 解析对阵信息
        home_team = raw_matchdata['homeTeam']['name']
        away_team = raw_matchdata['awayTeam']['name']
        matchmake_en_name = matchmake_cn_name = f"{home_team} vs {away_team}"

        # 刮削比赛信息
        match_metainfo.cn_name = " - ".join([season_cn_name, round_cn_name, matchmake_cn_name])
        match_metainfo.en_name = " - ".join([season_en_name, round_en_name, matchmake_en_name])
        match_metainfo.set_season(season)
        match_metainfo.set_episode(round_info)
        match_metainfo.subtitle = ""
        match_metainfo.title = competition_cn_name

        # 刮削集信息

        match_date = raw_matchdata.get('utcDate')
        if match_date:
            match_date_utc = datetime.datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            match_date = match_date_utc.astimezone(tz=None)
        episode_metainfo.air_date = match_date
        episode_metainfo.episode_number = round_info
        episode_metainfo.name = match_metainfo.cn_name
        episode_metainfo.overview = match_metainfo.cn_name
        episode_metainfo.runtime = 90
        episode_metainfo.season_number = season

        return match_metainfo, episode_metainfo

    def recognize_competition_mediainfo(self, torrent_info: TorrentInfo = None, meta_info: MetaBase = None) -> MediaInfo | None:
        """
          根据自定义规则刮削赛事信息
        """
        competition_mediainfo = MediaInfo()

        if torrent_info:
            # 若传入了种子信息，从其中获取种子标题
            title = torrent_info.title
        else:
            # 否则，从文件元数据中获取文件标题
            title = meta_info.org_string

        # 获取赛季信息
        try:
            season_name = meta_info.year
            if not season_name:
                # 尝试在原标题中找到年份
                match_date = self.extract_date(title)
                if match_date[1] < 7:
                    # 如果比赛日期在七月之前，是上一年开始的赛季
                    season = match_date[0] - 1
                else:
                    season = match_date[0]
            else:
                season = int(season_name)
            # 年份信息回填赛事元数据
            meta_info.year = str(season)
        except Exception as err:
            logger.error(f"解析种子 {title} 赛事的赛季时出现问题，{err}")

        for competition_parse in self.__competitions_parses:
            if any(alia.lower() in title.lower() for alia in competition_parse["names"]):
                # 匹配任意一个别名，开始解析
                self.scrape_competition(competition_mediainfo, competition_parse)
                competition_mediainfo.type = MediaType.TV
                competition_mediainfo.season = int(meta_info.year)
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

    @staticmethod
    def find_best(force_en: bool = False, lowest_pix: int = 0, matchesinfo: list[Matchinfo] = None,
                  new_matchinfo: Matchinfo = None):
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
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title}) 的解说语言为英语，而之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) 不是，替换")
                elif new_matchinfo.pix > old_matchinfo.pix:
                    matchesinfo[i] = new_matchinfo
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title})的清晰度高于之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) ，替换")
                else:
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title}) 不如之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) ，不替换")
                return

        # 如果已有种子列表中没有该场比赛，则添加之
        matchesinfo.append(new_matchinfo)
        return


    @staticmethod
    def get_thumb(video_path: str, image_path: str, frames: str = None):
        """
        使用ffmpeg从视频文件中截取缩略图
        """
        if not frames:
            frames = "00:00:10"
        if not video_path or not image_path:
            return False
        cmd = 'ffmpeg -y -i "{video_path}" -ss {frames} -frames 1 "{image_path}"'.format(
            video_path=video_path,
            frames=frames,
            image_path=image_path)
        # 1573
        result = SystemUtils.execute(cmd)
        # if not result:
        #     import subprocess
        #     proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        #     logger.debug(f"ffmpeg returncode={proc.returncode} stdout={proc.stdout[:1000]!r} stderr={proc.stderr[:1000]!r}")
        #     # ffmpeg 常把信息写到 stderr，优先使用 stderr 再用 stdout
        #     result = proc.stderr if proc.stderr else proc.stdout
        if result:
            return True
        return False


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
              |
                (\d{2})\.(\d{2})\.(\d{4})   # DD MM YYYY  
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
        elif m.group(2):  # DD MM YYYY
            year, month, day = m.group(6), m.group(5), m.group(4)
        elif m.group(3):
            year, month, day = m.group(9), m.group(8), m.group(7)
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

    def __handle_file(self, is_directory: bool, event_path: str, source_dir: str):
        """
        同步一个文件
        :event.is_directory
        :param event_path: 事件文件路径
        :param source_dir: 监控目录
        """

        # 初始化媒体刮削工具类
        storagechain = StorageChain()
        mediachain = MediaChain()

        try:
            # 转移路径
            dest_dir = self.__dest_path
            # 是否重命名
            rename_conf = self.__need_rename

            # 元数据
            file_meta = MetaInfoPath(Path(event_path))

            if not file_meta.name:
                logger.error(f"{Path(event_path).name} 无法根据文件名识别有效信息")
                return

            # 识别赛事信息
            mediainfo: MediaInfo = self.recognize_competition_mediainfo(meta_info=file_meta)
            # 识别比赛信息
            file_meta, episode_info = self.recognized_match_metainfo(match_mediainfo=mediainfo, metainfo=file_meta)

            # mediainfo: MediaInfo = self.chain.recognize_media(meta=file_meta)
            transfer_flag = False
            title = None

            # 进行转移
            if mediainfo and episode_info:
                try:
                    # 查询转移目的目录
                    target_dir = DirectoryHelper().get_dir(mediainfo, dest_path=dest_dir)
                    if not target_dir or not target_dir.library_path:
                        target_dir = TransferDirectoryConf()
                        target_dir.library_path = dest_dir
                        target_dir.transfer_type = self.__transfer_type
                        target_dir.renaming = True
                        target_dir.notify = False
                        target_dir.overwrite_mode = 'never'
                        target_dir.library_storage = "local"
                    else:
                        target_dir.transfer_type = self.__transfer_type

                    if not target_dir.library_path:
                        logger.error(f"未配置监控目录 {dest_dir} 的目的目录")
                        return

                    # 更新媒体图片
                    self.chain.obtain_images(mediainfo=mediainfo)

                    # episodes_info = self.tmdbchain.tmdb_episodes(tmdbid=mediainfo.tmdb_id,
                    #                                              season=file_meta.begin_season or 1)
                    mediainfo.category = ""
                    # 转移
                    episodes_info = [episode_info]
                    source_path = Path(event_path)
                    source_fileitem = FileItem.from_uri(event_path)
                    source_fileitem.path = source_path.as_posix()
                    source_fileitem.type = "file"
                    source_fileitem.name = source_path.name
                    source_fileitem.basename = source_path.stem
                    source_fileitem.extension = source_path.suffix[1:]

                    transferinfo: TransferInfo = self.chain.transfer(mediainfo=mediainfo,
                                                                     fileitem=source_fileitem,
                                                                     target_directory=target_dir,
                                                                     meta=file_meta,
                                                                     episodes_info=episodes_info)
                    if not transferinfo:
                        logger.error("文件整理/重命名模块运行失败")
                        transfer_flag = False
                    else:
                        # 重命名比赛文件
                        # storagechain.rename_file(fileitem=transferinfo.target_diritem,
                        #                          name=file_meta.title)
                        # mediachain.scrape_metadata(fileitem=transferinfo.target_diritem,
                        #                            meta=file_meta,
                        #                            mediainfo=mediainfo)
                        # 转移后的文件路径
                        target_path_str = transferinfo.target_item.path
                        logger.info(f"文件整理/重命名模块运行成功：{event_path} -> {target_path_str}")
                        transfer_flag = True
                except Exception as err:
                    print(str(err))
                    transfer_flag = False
                    logger.error(f"{event_path} 体育比赛刮削失败")

            if transfer_flag:
                # 生成刮削信息
                # 生成 tvshow.nfo
                target_file = Path(target_path_str)
                target_file_name = target_file.name
                title = str.split(target_file_name, ".")[0]
                if not (target_file.parent / f"{title}.nfo").exists():
                    self.__gen_tv_nfo_file(dir_path=target_file.parent,
                                           title=title)

                # 生成缩略图
                if not (target_file.parent / f"{title}_poster.jpg").exists():
                    thumb_path = self.gen_file_thumb(title=title,
                                                     rename_conf=rename_conf,
                                                     file_path=target_file)
                    if thumb_path and Path(thumb_path).exists():
                        self.__save_poster(input_path=thumb_path,
                                           poster_path=target_file.parent / f"{title}_poster.jpg",
                                           cover_conf="16:9")
                        if (target_file.parent / f"{title}_poster.jpg").exists():
                            logger.info(f"{target_file.parent / 'poster.jpg'} 缩略图已生成")
                        thumb_path.unlink()
                    else:
                        # 检查是否有缩略图
                        thumb_files = SystemUtils.list_files(directory=target_file.parent,
                                                             extensions=[".jpg"])
                        if thumb_files:
                            # 生成poster
                            for thumb in thumb_files:
                                self.__save_poster(input_path=thumb,
                                                   poster_path=target_file.parent / f"{title}_poster.jpg",
                                                   cover_conf="16:9")
                                break
                            # 删除多余jpg
                            for thumb in thumb_files:
                                Path(thumb).unlink()
            else:
                logger.error(f"文件 {event_path} 整理/重命名失败，不进行刮削动作")
            if self.__notify:
                # 发送消息汇总
                matches_list = self.__matches.get(mediainfo.title_year if mediainfo else title) or {}
                if matches_list:
                    match_files = matches_list.get("files") or []
                    if match_files:
                        if str(event_path) not in match_files:
                            match_files.append(str(event_path))
                    else:
                        match_files = [str(event_path)]
                    matches_list = {
                        "files": match_files,
                        "time": datetime.datetime.now()
                    }
                else:
                    matches_list = {
                        "files": [str(event_path)],
                        "time": datetime.datetime.now()
                    }
                self.__matches[mediainfo.title_year if mediainfo else title] = matches_list
        except Exception as e:
            logger.error(f"event_handler_created error: {e}")
            print(str(e))


    def __save_nfo(self, doc, file_path: Path):
        """
        保存NFO
        """
        xml_str = doc.toprettyxml(indent="  ", encoding="utf-8")
        file_path.write_bytes(xml_str)
        logger.info(f"NFO文件已保存：{file_path}")


    def __save_poster(self, input_path, poster_path, cover_conf):
        """
        截取图片做封面
        """
        try:
            image = Image.open(input_path)

            # 需要截取的长宽比（比如 16:9）
            if not cover_conf:
                target_ratio = 2 / 3
            else:
                covers = cover_conf.split(":")
                target_ratio = int(covers[0]) / int(covers[1])

            # 获取原始图片的长宽比
            original_ratio = image.width / image.height

            # 计算截取后的大小
            if original_ratio > target_ratio:
                new_height = image.height
                new_width = int(new_height * target_ratio)
            else:
                new_width = image.width
                new_height = int(new_width / target_ratio)

            # 计算截取的位置
            left = (image.width - new_width) // 2
            top = (image.height - new_height) // 2
            right = left + new_width
            bottom = top + new_height

            # 截取图片
            cropped_image = image.crop((left, top, right, bottom))

            # 保存截取后的图片
            cropped_image.save(poster_path)
        except Exception as e:
            print(str(e))


    def __gen_tv_nfo_file(self, dir_path: Path, title: str):
        """
        生成电视剧的NFO描述文件
        :param dir_path: 电视剧根目录
        """
        # 开始生成XML
        logger.info(f"正在生成电视剧NFO文件：{dir_path.name}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "tvshow")

        # 标题
        DomUtils.add_node(doc, root, "title", title)
        DomUtils.add_node(doc, root, "originaltitle", title)
        DomUtils.add_node(doc, root, "season", "-1")
        DomUtils.add_node(doc, root, "episode", "-1")
        # 保存
        self.__save_nfo(doc, dir_path.joinpath(f"{title}.nfo"))


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

                if self.__start_paused:
                    logger.info("根据设置，添加下载任务后暂停")
                state = downloader.add_torrent(content=torrent_content,
                                               download_dir=download_dir,
                                               is_paused=self.__start_paused,  # 调试用
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
    def __transfer_command(file_item: Path, target_file: Path, transfer_type: str) -> int:
        """
        使用系统命令处理单个文件
        :param file_item: 文件路径
        :param target_file: 目标文件路径
        :param transfer_type: RmtMode转移方式
        """
        with lock:

            # 转移
            if transfer_type == 'link':
                # 硬链接
                retcode, retmsg = SystemUtils.link(file_item, target_file)
            elif transfer_type == 'softlink':
                # 软链接
                retcode, retmsg = SystemUtils.softlink(file_item, target_file)
            elif transfer_type == 'move':
                # 移动
                retcode, retmsg = SystemUtils.move(file_item, target_file)
            else:
                # 复制
                retcode, retmsg = SystemUtils.copy(file_item, target_file)

        if retcode != 0:
            logger.error(retmsg)

        return retcode

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


    @staticmethod
    def __is_number_or_range(value):
        """
        检查字符串是否表示单个数字或数字范围（如'5', '5.5', '5-10' 或 '5.5-10.2'）
        """
        return bool(re.match(r"^\d+(\.\d+)?(-\d+(\.\d+)?)?$", value))

