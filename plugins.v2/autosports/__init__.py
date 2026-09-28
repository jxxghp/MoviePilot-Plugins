import base64
import datetime
import json
import math
import re
import threading
import traceback
from copy import deepcopy
from dataclasses import fields, dataclass
from pathlib import Path
from threading import Lock
from typing import Optional, Any, List, Dict, Tuple
from typing import Union
from xml.dom import minidom

import pytz
from PIL import Image
from app.helper.sites import SitesHelper
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import false
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from app import schemas
from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.search import SearchChain
from app.chain.subscribe import SubscribeChain
from app.core.cache import TTLCache
from app.core.config import settings
from app.core.context import MediaInfo, TorrentInfo, Context
from app.core.event import eventmanager, Event
from app.core.meta import MetaVideo, MetaBase
from app.core.metainfo import MetaInfoPath, MetaInfo
from app.helper.directory import DirectoryHelper
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import ServiceInfo, TransferDirectoryConf, TmdbEpisode, TransferInfo, FileItem
from app.schemas.types import SystemConfigKey, MediaType, ChainEventType, NotificationType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.utils.system import SystemUtils

lock = Lock()
ffmpeg_lock = threading.Lock()


class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控响应类
    """
    def __init__(self, watching_path: str, file_change: Any, **kwargs):
        super(FileMonitorHandler, self).__init__(**kwargs)
        self.__watch_path = watching_path
        self.file_change = file_change

    def on_created(self, event):
        self.file_change.event_handler(event=event, source_dir=self.__watch_path, event_path=event.src_path)

    def on_moved(self, event):
        self.file_change.event_handler(event=event, source_dir=self.__watch_path, event_path=event.dest_path)


def get_raw_competitions_parse() -> list[dict]:
    return [
        {
            "names": ["西甲", "La Liga", "LaLiga", "Laliga", "西班牙足球甲级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "PD",  # 缩写
            "title": "西班牙足球甲级联赛",  # 中文名
            "en_title": "La Liga",  # 英文名
            "original_title": "La Liga",  # 原名
            "year": 1929,  # 创办年份
            "overview": "西班牙足球甲级联赛（西班牙语：Primera División de España或La Liga，由于赞助原因，正式名称为LALIGA EA SPORTS），通常简称西甲或西甲联赛，是西班牙足球联赛系统的第 1 级别，亦是职业联赛的最高级别、联赛系统的最高级别和西班牙顶级足球联赛，目前有 20 支球队。皇家马德里是历史上夺得最多冠军的球队（36次），其次是巴塞罗那（28次），以及马德里竞技（11次）。 ",  # 赛事介绍
            "season_years": {x: x for x in range(1929, 2101)},  # 赛季
            "homepage": "https://www.laliga.com",  # 官网
            "languages": ["Spanish"],  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": ["西班牙皇家足球协会 (RFEF)"],  # 创办协会
            "production_countries": ["Spain"],  # 国家
            "spoken_languages": ["Spanish"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["欧洲冠军联赛", "Champions League", "UCL", "UEFA Champions League", "UEFA"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "CL",  # 缩写
            "title": "欧洲冠军联赛",  # 中文名
            "en_title": "UEFA Champions League",  # 英文名
            "original_title": "UEFA Champions League",  # 原名
            "year": 1955,  # 创办年份
            "overview": "欧洲冠军联赛（英语：UEFA Champions League，缩写：UCL；简称欧冠联赛、欧冠）是欧洲足联主办的年度俱乐部足球比赛，该赛事由欧洲顶级联赛的俱乐部队伍参加，通过联赛阶段和双回合淘汰赛，以及单场决赛的形式决出冠军。代表欧洲俱乐部足球最高荣誉，被誉为全世界最高竞技水平的俱乐部杯赛，估计每届赛事约有超过十亿电视观众观看赛事，现与欧洲联赛和欧协联并称“欧洲俱乐部三大杯”。\n"
                        "欧洲冠军联赛始创于1955年，被称为“欧洲俱乐部冠军杯”（法语：Coupe des Clubs Champions Européens），通称欧洲冠军杯（英语：European Cup）。最初，该赛事以直接淘汰制形式进行，并仅对欧洲各国的联赛冠军开放。随后在1991年引入小组赛环节，并于1992年更为现名。自1997-98赛季起，部分国家可派出最多4支球队参赛。目前，大部分欧洲国家仅能派出其联赛冠军参赛，而实力较强的联赛最多可派出四支球队。未能晋级欧冠的俱乐部有资格参加欧洲联赛及自2021年起举办的欧洲协会联赛。\n"
                        "现行赛制从六月下旬开始，包括三轮资格赛和一轮附加赛，均采用双回合制。六支晋级球队进入联赛阶段，与提前获得资格的30支球队会合。36支球队会透过以瑞士制为基础的联赛模式定出晋级淘汰赛阶段的球队（在联赛阶段取得首八名的球队直接晋级，余下八队会经淘汰附加赛决定）最终在五月底或六月初的决赛中决出冠军。赛事冠军将自动获得参加下一年度欧洲冠军联赛、欧洲超级杯及俱乐部世界杯的参赛资格。\n"
                        "在欧冠历史上，西班牙俱乐部以20次冠军居于榜首，英格兰和意大利分别以15次和12次获胜紧随其后。英格兰拥有最多的获胜球队，共六家俱乐部赢得冠军。迄今为止，共有23家俱乐部夺冠，其中13家俱乐部多次夺冠，8家成功卫冕。皇家马德里是该赛事历史上最成功的俱乐部，共赢得了15次冠军，包括首五届赛事冠军和最近十一届中的六次。只有拜仁慕尼黑以全胜战绩（2019–20赛季）夺得冠军。",
            "season_years": {x: x for x in range(1955, 2101)},  # 赛季
            "homepage": "https://www.uefa.com",  # 官网
            "languages": ["English"],  # 解说源语言
            "origin_country": "Europa",  # 国家
            "original_name": "UEFA Champions League",  # 原名
            "production_companies": ["欧洲足球协会联盟 (UEFA)"],  # 创办协会
            "production_countries": ["Europa"],  # 国家
            "spoken_languages": ["English"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["西班牙国王杯", "Copa Del Rey", "Campeonato de España – Copa de Su Majestad el Rey", "国王杯"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "CDR",  # 缩写
            "title": "西班牙国王杯",  # 中文名
            "en_title": "Copa Del Rey",  # 英文名
            "original_title": "Copa Del Rey",  # 原名
            "year": 1903,  # 创办年份
            "overview": "西班牙冠军–国王陛下杯（西班牙语：Campeonato de España – Copa de Su Majestad el Rey），通称国王杯（Copa del Rey）或西班牙杯，是西班牙一项每年举办的淘汰制足球赛事。赛事开办起因于皇家马德里前主席卡洛斯·帕德罗斯提议举办一项足球赛事以庆祝西班牙国王阿方索十三世登基，而于1902年举行首届比赛。\n"
                        "赛事最早叫做“马德里市议会杯”（Copa del Ayuntamiento de Madrid），1905至1932年间称为“阿方索十三世杯”（Copa de S.M. El Rey Alfonso XIII），在西班牙第二共和国期间则称为“共和国总统杯”Copa del Presidente de la República），简称“西班牙杯” （Copa de España），在佛朗哥执政期间又改称为 “大元帅阁下杯”（Copa de Su Excelencia El Generalísimo） ，简称“大元帅杯”（Copa del Generalísimo)。",
            "season_years": {x: x for x in range(1903, 2101)},  # 赛季
            "homepage": "https://www.laliga.com/en-GB/other-competitions/copa-del-rey",  # 官网
            "languages": ["Spanish"],  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": ["西班牙皇家足球协会 (RFEF)"],  # 创办协会
            "production_countries": ["Spain"],  # 国家
            "spoken_languages": ["Spanish"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {  # 本地刮削信息（空表示不进行本地刮削）
                "group": 0,  # 小组赛比赛场次
                "knockout_single": 32,  # 单场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
                "knockout_double": 4  # 主客场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
            },
        },
        {
            "names": ["西班牙超级杯", "Supercopa de España", "Spanish Super Cup", "SuperCopa", "超级杯"],
            "type": "CUP",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "SE",  # 缩写
            "title": "西班牙超级杯",  # 中文名
            "en_title": "Spanish Super Cup",  # 英文名
            "original_title": "Supercopa de España",  # 原名
            "year": 1982,  # 创办年份
            "overview": "西班牙超级杯（西班牙语：Supercopa de España）是西班牙每年一度由甲级联赛冠军对国王杯盟主的足球锦标赛，如果有一支球队同时夺得联赛及国王杯冠军，对赛球队则由国王杯亚军补上，2019年起增设联赛及国王杯亚军席位，如果有一支球队同时夺得联赛及国王杯冠亚军，对赛球队则由联赛排名较佳一方补上，改制成单场淘汰赛模式。首届赛事于1940年举行，作为每年球季开始前的揭幕战。\n"
                        "赛事早期曾经有过多个名称，首届赛事举行时名称为西班牙冠军杯（Copa de Campeones），但比赛直到1945年才又再举办，这时由于来自阿根廷的大使欲与西班牙打好友谊关系，遂以阿根廷金杯（Copa de Oro Argentina）为名举行比赛。1947年，为了庆祝胡安·裴隆成为阿根廷总统，而以其妻子伊娃·裴隆为名举行伊娃杯（Copa Eva Duarte）。可惜1953年之后球赛因为不受重视而停办，一直到1983年才又重新复办赛事，并正式将球赛命名为西班牙超级杯至今。",
            "season_years": {x: x for x in range(1982, 2101)},  # 赛季
            "homepage": "https://www.laliga.com/en-GB/other-competitions/supercopa-de-espana",  # 官网
            "languages": ["Spanish"],  # 解说源语言
            "origin_country": "Spain",  # 国家
            "original_name": "Primera División de España",  # 原名
            "production_companies": ["西班牙皇家足球协会 (RFEF)"],  # 创办协会
            "production_countries": ["Spain"],  # 国家
            "spoken_languages": ["Spanish"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {  # 本地刮削信息（空表示不进行本地刮削）
                "group": 0,  # 小组赛比赛场次
                "knockout_single": 4,  # 单场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
                "knockout_double": 0  # 主客场淘汰赛起始轮次（例如 32 表示第一轮是 32 进 16）
            },

        },
        {
            "names": ["英超", "Premier League", "PremierLeague", "Premier league", "英格兰足球超级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "PL",  # 缩写
            "title": "英格兰足球超级联赛",  # 中文名
            "en_title": "Premier League",  # 英文名
            "original_title": "Premier League",  # 原名
            "year": 1992,  # 创办年份
            "overview": "英格兰足球超级联赛（英语：Premier League），通称“英超”，是英格兰足球最高等级的赛事类别亦是世上最顶级的足球联赛，由英格兰足球协会于1992年2月20日确立，首个赛季于1992–93年正式面世。作为英格兰足球联赛系统的组成部分，英超的每支球队均需与同级别的全部其它球队进行主客场制对赛。威尔士球队在英格兰足球联赛系统参赛，亦有资格成为英超球队，但不能再以威尔士国家地区身份参与欧洲赛事。\n"
                        "虽然英超是1992创立，但英格兰早在1888年就已经成立世界上最早的足球联赛，100多年来已有24队夺得顶级联赛的冠军(包含1992年以前的英甲时代与英超)，详细可参考英格兰足球联赛与英格兰足球冠军的页面。\n"
                        "英超共有20支参赛球队，运作模式为一所以20间俱乐部共同拥有的有限公司。赛季于每年8月至次年5月进行，每队共有38场比赛，20支球队相互对赛两次，其中主、客场各一次。每个赛季，英超共有380场比赛。大部分英超的比赛于周末下午开赛，亦有一部分在周中的傍晚举行。\n"
                        "英超是全世界最多人观看的体育联赛。在全球各地，212个地区有电视转播英超赛事，潜在观众约有47亿人。2014–15赛季，英超俱乐部的球场平均入场人数超过3.6万人，仅次于德国足球甲级联赛的4.35万人。 欧洲足联于2018年1月初发表一份126页的欧洲各大俱乐部统计报告，记录不同联赛与及俱乐部的数据。而于2016/2017赛季最多人入场联赛的统计中，英超以累积超过1300万人次入场成为第一。\n"
                        "自1992年成立以来，共有7队曾夺得联赛冠军，分别是曼联（13次）、曼城（8次）、切尔西（5次）、阿森纳（3次）、利物浦（2次）以及布莱克本流浪者和莱斯特城（各1次）。",  # 赛事介绍
            "season_years": {x: x for x in range(1992, 2101)},  # 赛季
            "homepage": "https://www.premierleague.com",  # 官网
            "languages": ["English"],  # 解说源语言
            "origin_country": "England",  # 国家
            "original_name": "Premier League",  # 原名
            "production_companies": ["英格兰足球协会 (The FA)"],  # 创办协会
            "production_countries": ["England"],  # 国家
            "spoken_languages": ["English"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["意甲", "Serie A", "SerieA", "serie A", "意大利足球甲级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "SA",  # 缩写
            "title": "意大利足球甲级联赛",  # 中文名
            "en_title": "Serie A",  # 英文名
            "original_title": "Scudetto",  # 原名
            "year": 1897,  # 创办年份
            "overview": "意大利足球甲级联赛（意大利语：Serie A，简称“意甲”），昵称“小盾牌”（意大利语：Scudetto，因为意甲卫冕冠军徽章外型类似盾牌），是意大利足球联赛系统的第 1 级别 ，亦是职业联赛的最高级别，联赛系统的最高级别和意大利顶级足球联赛，由意大利足球协会（Federazione Italiana Gioco Calcio，FIGC）所管理，意甲职业联盟（Lega Nazionale Professionisti Serie A，Lega Serie A）营运。尤文图斯是最成功的俱乐部，获得（36 次）冠军，其次是国际米兰（20 次）和AC米兰（19 次）。",  # 赛事介绍
            "season_years": {x: x for x in range(1897, 2101)},  # 赛季
            "homepage": "https://www.legaseriea.it",  # 官网
            "languages": ["Italian"],  # 解说源语言
            "origin_country": "Italy",  # 国家
            "original_name": "Scudetto",  # 原名
            "production_companies": ["意大利足球协会 (FIGC)"],  # 创办协会
            "production_countries": ["Italy"],  # 国家
            "spoken_languages": ["Italian"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["德甲", "Bundesliga", "bundesliga", "Fußball-Bundesliga", "德国足球甲级联赛", "足球联邦联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "BL1",  # 缩写
            "title": "德国足球甲级联赛",  # 中文名
            "en_title": "Bundesliga",  # 英文名
            "original_title": "Bundesliga",  # 原名
            "year": 1962,  # 创办年份
            "overview": "足球联邦联赛（德语：Fußball-Bundesliga，简称Bundesliga [ˈbʊndəsˌliːɡa]），中文通称为德国足球甲级联赛，或简称德甲，是德国足球最高等级的赛事类别，由德国足球协会于1962年7月28日在多特蒙德确立，自1963–64赛季面世。德甲的每支球队均需与同级别的全部其它球队进行主客场制对赛，最终的德国足球冠军可获得欧洲冠军联赛的参赛资格；而排名最末的两支球队将降级至德国足球乙级联赛（德乙）。排名倒数第三的球队则需要与德乙第三名进行保级附加赛，胜者可获准留在德甲。此外，所有德甲球队都可直接入围德国足协杯比赛，两者冠军将参加德国超级杯的争夺。\n"
                        "作为欧洲五大联赛之一，德甲在欧洲足联的联赛系数排名中目前位居全欧第4。德甲也是全球现场观战人数最高的足球联赛，其于2013年至2018年间的场均上座率高达43,302人次，同时还在全球209个国家和地区进行电视转播。拜仁慕尼黑是德甲最为成功的球队，共获得33次德国冠军。",  # 赛事介绍
            "season_years": {x: x for x in range(1962, 2101)},  # 赛季
            "homepage": "https://www.bundesliga.de",  # 官网
            "languages": ["German"],  # 解说源语言
            "origin_country": "Germany",  # 国家
            "original_name": "Fußball-Bundesliga",  # 原名
            "production_companies": ["德国足球协会 (DFB)"],  # 创办协会
            "production_countries": ["Germany"],  # 国家
            "spoken_languages": ["German"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
        {
            "names": ["法甲", "Championnat de France de football", "Ligue 1", "Ligue1", "Ligue 1 McDonald's", "法国足球甲级联赛"],  # 别名
            "type": "LEAGUE",  # 赛事类型（联赛：league/杯赛：cup）
            "shortname": "FL1",  # 缩写
            "title": "法国足球甲级联赛",  # 中文名
            "en_title": "Ligue 1",  # 英文名
            "original_title": "Ligue 1",  # 原名
            "year": 1932,  # 创办年份
            "overview": "法国足球甲级联赛（法语：Championnat de France de football [ʃɑ̃pjɔna də fʁɑ̃s də futbol]，简称Ligue 1 [liɡ œ̃]，因得到赞助商麦当劳冠名而又称为Ligue 1 McDonald's），简称法甲，是法国足球联赛系统的第1级别，亦是职业联赛的最高级别，联赛系统的最高级别和法国顶级足球联赛，由法国足球协会监管下的法国职业足球联赛所负责监督、组织及管理。截至2021年，法甲作为欧洲五大联赛之一，在欧洲足联的联赛系数排名中目前位居全欧第五，仅次于英格兰的英格兰足球超级联赛、西班牙的西班牙足球甲级联赛、意大利的意大利足球甲级联赛和德国的德国足球甲级联赛。\n"
                        "法甲联赛于1932年9月11日成立，最初以“国家联赛”（National）的名称开始运作，一年后改名为“一级联赛”（Division 1）；直到2002年，联赛采用现在的名称。\n"
                        "在 20 世纪时期，法甲联赛较少产生一支长期雄霸联赛的超级强队；即使是法国本土球星，亦是外流至其他欧洲豪门居多；但在九十年代，多支法甲俱乐部在欧洲赛场上冒起，如巴黎圣日耳曼于1996年赢过欧洲杯赛冠军杯，马赛更在1993年赢过欧冠杯。\n"
                        "现在法甲联赛水准已大为提升，并成为了非洲和南美球员向欧洲发展的重要跳板之一。",  # 赛事介绍
            "season_years": {x: x for x in range(1932, 2101)},  # 赛季
            "homepage": "https://www.ligue1.com/",  # 官网
            "languages": ["French"],  # 解说源语言
            "origin_country": "France",  # 国家
            "original_name": "Championnat de France de football",  # 原名
            "production_companies": ["法国足球协会 (FFF)"],  # 创办协会
            "production_countries": ["France"],  # 国家
            "spoken_languages": ["French"],  # 语言
            "runtime": 9000,  # 比赛时长
            "offline_info": {},  # 本地刮削信息（空表示不进行本地刮削）
        },
    ]


def get_demo_competitions_config() -> str:
    desc = (
        "// 以下为配置示例，请参考：https://github.com/Sinterdial/MoviePilot-Plugins/blob/main/docs/Self_Defined_Competitions_Guide.md 进行配置\n"
        "// 插件已内置五大联赛+欧冠+国王杯+西超杯，请勿重复配置\n"
        "// 注意无关内容需使用 // 注释，但行内不要使用 // 注释\n"
        "// 只有标注【必填】的字段是必须有的，其它可以省略\n"
        "// 必须严格遵循 json 格式，最后一个字段后面不要有逗号\n")
    config = """[{
    // 示例一：在 football-data.org 有数据的联赛或杯赛（在线刮削）
    // // 【必填】别名（区分大小写）
    // "names": ["西甲", "La Liga", "LaLiga", "Laliga","西班牙足球甲级联赛"], 
    // // 【必填】赛事类型（联赛：LEAGUE/杯赛：CUP）
    // "type": "LEAGUE", 
    // // 【在线刮削必填】唯一缩写 (需要与 football-data.org 上的缩写对应)，
    // //              该项不要与插件内已有的重复（PD、CL、CDR、SE、PL、SA、BL1、FL1）
    // "shortname": "PD",
    // // 【必填】中文名
    // "title": "西班牙足球甲级联赛",
    // // 英文名
    // "en_title": "La Liga", 
    // // 原名
    // "original_title": "La Liga",  
    // // 创办年份
    // "year": 1929, 
    // // 赛事简介
    // "overview": "赛事简介",
    // // 官网
    // "homepage": "www.laliga.com", 
    // // 解说源语言
    // "languages": ["Spanish"], 
    // // 国家
    // "origin_country": "Spain",  
    // // 原名
    // "original_name": "Primera División de España", 
    // // 创办协会
    // "production_companies": ["西班牙皇家足球协会 (RFEF)"],  
    // // 国家
    // "production_countries": ["Spain"], 
    // // 语言
    // "spoken_languages": ["Spanish"],  
    // // 比赛时长
    // "runtime": 9000,
    // // 【离线刮削必填】本地刮削信息（空表示 football-data.org 上提供该赛事信息，不进行本地刮削)
    // "offline_info": {}
}, 
{
    // // 示例二：football-data.org 没有数据的杯赛（离线刮削）
    // // 【必填】别名（区分大小写）
    // "names": ["西班牙国王杯", "Copa Del Rey", "Campeonato de España – Copa de Su Majestad el Rey", "国王杯"], 
    // // 【必填】赛事类型（联赛：LEAGUE/杯赛：CUP）
    // "type": "CUP", 
    // // 缩写
    // "shortname": "CDR",
    // // 【必填】中文名
    // "title": "西班牙国王杯",
    // // 英文名
    // "en_title": "Copa Del Rey", 
    // // 原名
    // "original_title": "Copa Del Rey",  
    // // 创办年份
    // "year": 1903, 
    // // 赛事简介
    // "overview": "赛事简介",
    // // 官网
    // "homepage": "www.laliga.com/en-GB/other-competitions/copa-del-rey", 
    // // 解说源语言
    // "languages": ["Spanish"], 
    // // 国家
    // "origin_country": "Spain",  
    // // 原名
    // "original_name": "Primera División de España", 
    // // 创办协会
    // "production_companies": ["西班牙皇家足球协会 (RFEF)"],  
    // // 国家
    // "production_countries": ["Spain"], 
    // // 语言
    // "spoken_languages": ["Spanish"],  
    // // 比赛时长
    // "runtime": 9000,
    // // 【必填】
    // "offline_info": {
            // // 【必填】 小组赛比赛场次
            // "group": 0,  
            // // 【必填】 单场淘汰赛起始轮次（例如 32 表示从 32 进 16 这一轮开始），0 表示没有
            // "knockout_single": 32,
            // // 【必填】 主客场淘汰赛起始轮次（例如 32 表示从 32 进 16 这一轮开始），0 表示没有
            // "knockout_double": 4
    // }
}]"""

    return desc + config


class AutoSports(_PluginBase):
    # 插件名称
    plugin_name = "AutoSports"
    # 插件描述
    plugin_desc = "根据设置的球队名自动下载最新比赛，进行文件整理及简单的刮削"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Sinterdial/MoviePilot-Plugins/main/icons/autosports.png"
    # 插件版本
    plugin_version = "2.0.6"
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

    name = "AutoSports"
    __enabled: bool = False
    __teams_info: str = ""
    __football_apikey: str = ""
    __cron: str = "27 6-8 * * *"
    __notify: bool = False
    __onlyonce: bool = False
    __include: str = ""
    __exclude: str = ""
    __proxy: bool = False
    __filter: bool = False
    __force_en: bool = False
    __lowest_pix: int = 720
    __clear: bool = False
    __clearflag: bool = False
    __action: str = "download"
    __save_path: str = ""  # 下载路径
    __dest_path: str = ""  # 媒体库路径
    __category: str = ""
    __tags: list[str] = []
    __size_range: str = ""
    __start_paused: bool = True  # 添加种子后暂停下载
    __max_download: int = 2  # 单次最多下多少场比赛
    # 转移与刮削相关
    __sync_all: bool = False
    __monitor_mode: str = 'normal'  # 增量监控目录模式
    __observer: list[Observer | PollingObserver] = []  # 目录监控工具对象
    __transfer_type: str = "link"
    __need_rename: bool = True
    __downloaders = None
    __scheduler: BackgroundScheduler | None = None
    __timeline = "00:00:10"
    __matches = {}
    __competitions_config = get_demo_competitions_config()  # 自定义赛事信息
    # 订阅缓存信息
    __cached_matches = {}
    __system_cache = None  # 系统缓存，默认12小时过期

    # 赛事刮削信息
    # 自定义映射关系
    __competitions_parses = get_raw_competitions_parse()

    knockout_parse = {  # 杯赛 -> 参赛球队数映射表
        # Round of 32
        r"\br32\b|\bround\s+of\s+32\b": 32,

        # Round of 16
        r"\br16\b|\bround\s+of\s+16\b": 16,

        # Quarter Final
        r"\bquarter[\s-]?final\b|\bqf\b": 8,

        # Semi Final
        r"\bsemi[\s-]?final\b|\bsf\b": 4,

        # Final
        r"\bfinal\b": 2,

        # Round of 32
        r"\b三十二强赛\b": 32,

        # Round of 16
        r"\b十六强赛\b": 16,

        # Quarter Final
        r"\b八强赛\b": 8,

        # Semi Final
        r"\b半决赛\b": 4,

        # Final
        r"\b决赛\b": 2,
    }

    downloadchain: DownloadChain = None
    subscribechain: SubscribeChain = None
    mediachain: MediaChain = None
    searchchain: SearchChain = None

    torrents_list = []

    def __init__(self):
        super().__init__()


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
            self.__log_and_notify_error("自动下载/整理体育比赛任务出错，获取下载器实例失败，请检查配置")
            return None

        if service.instance.is_inactive():
            self.__log_and_notify_error("自动下载/整理体育比赛任务出错，下载器未连接")
            return None

        return service

    @staticmethod
    def add_site() -> dict:
        """
            添加 Sportscult 站点索引
            TODO: 现在在 MP 里搜到之后不能直接下载，说是无法刮削信息，尝试用get_module重写识别方法失败，需要探求可行的方案
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
                        "path": "index.php?page=torrents&active=1&gold=0&search={keyword}&&order=3&by=2",
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
        # 创建缓存实例
        self.__system_cache = TTLCache(region='autosports', maxsize=128, ttl=43200)

        # 载入配置
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
            self.__competitions_config = config.get("competitions_config", "[]")
            self.__monitor_mode = config.get("monitor_mode")
            self.__sync_all = config.get("sync_all")
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

        if (self.__enabled or self.__onlyonce) and not self.__football_apikey:
            logger.error("无法对比赛进行刮削，请填入有效的 football-data.org API key")
            self.stop_service()

        # 启用目录监控
        if self.__enabled:
            # 检查媒体库目录是不是下载目录的子目录
            try:
                if self.__dest_path and Path(self.__dest_path).is_relative_to(Path(self.__save_path)):
                    logger.warn(f"{self.__dest_path} 是下载目录 {self.__save_path} 的子目录，无法监控")
                    self.systemmessage.put(f"{self.__dest_path} 是下载目录 {self.__save_path} 的子目录，无法监控")
            except Exception as e:
                logger.debug(str(e))
                pass

            try:
                if self.__monitor_mode == "compatibility":
                    # 兼容模式，目录同步性能降低且NAS不能休眠，但可以兼容挂载的远程共享目录如SMB
                    observer = PollingObserver(timeout=10)
                else:
                    # 内部处理系统操作类型选择最优解
                    observer = Observer(timeout=10)
                self.__observer.append(observer)
                observer.schedule(FileMonitorHandler(self.__save_path, self), path=self.__save_path, recursive=True)
                observer.daemon = True
                observer.start()
                logger.info(f"{self.__save_path} 的目录监控服务启动")
            except Exception as e:
                err_msg = str(e)
                if "inotify" in err_msg and "reached" in err_msg:
                    logger.warn(
                        f"目录监控服务启动出现异常：{err_msg}，请在宿主机上（不是docker容器内）执行以下命令并重启："
                        + """
                                     echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
                                     echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf
                                     sudo sysctl -p
                                     """)
                else:
                    logger.error(f"{self.__save_path} 启动目录监控失败：{err_msg}")
                self.systemmessage.put(f"{self.__save_path} 启动目录监控失败：{err_msg}")
        else:
            # 未启用插件，关闭目录监控服务
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
                "summary": "删除体育比赛自动下载整理历史记录"
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
                "kwargs": {"hours": 12}
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
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 3
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "dialog_opened",
                                            "label": "自定义赛事元数据",
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
                                    'md': 3
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
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'filter',
                                            'label': '(暂不支持)订阅优先级规则',
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
                                            'model': 'monitor_mode',
                                            'label': '是否启用兼容模式监控下载目录（远程目录需打开）',
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
                                    'md': 3
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
                                    'md': 3
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
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'sync_all',
                                            'label': '是否进行下载目录全量扫描整理',
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
                                            'model': 'start_paused',
                                            'label': '以暂停状态添加种子',
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
                                            'placeholder': '5位cron表达式，留空自动，设定的运行时间间隔不要小于1h'
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
                                            'label': '运行模式',
                                            'items': [
                                                {'title': '下载+整理（默认）', 'value': 'download'},
                                                {'title': '仅（全量）整理', 'value': 'transfer'},
                                                {'title': '订阅（暂不支持）', 'value': 'subscribe'},
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
                                    'cols': 12,
                                    # 'md': 6
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
                                            'label': '球队名关键词（英文），只支持单球队，一行一个',
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
                                            'label': '种子除AutoSports外的额外标签，逗号分隔',
                                            'placeholder': '如：Match,Football'
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
                                            'placeholder': '必须是设置中已添加的目录设置的子集'
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
                                            'placeholder': '必须是设置中已添加的目录设置的子集'
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        "component": "VDialog",
                        "props": {
                            "model": "dialog_opened",
                            "max-width": "65rem",
                            "overlay-class": "v-dialog--scrollable v-overlay--scroll-blocked",
                            "content-class": "v-card v-card--density-default v-card--variant-elevated rounded-t"
                        },
                        "content": [
                            {
                                "component": "VCard",
                                "props": {
                                    "title": "设置自定义赛事"
                                },
                                "content": [
                                    {
                                        "component": "VDialogCloseBtn",
                                        "props": {
                                            "model": "dialog_opened"
                                        }
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {},
                                        "content": [
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
                                                                'component': 'VAceEditor',
                                                                'props': {
                                                                    'modelvalue': 'competitions_config',
                                                                    'lang': 'json',
                                                                    'theme': 'monokai',
                                                                    'style': 'height: 30rem',
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
                                                                    'variant': 'tonal'
                                                                },
                                                                'content': [
                                                                    {
                                                                        'component': 'span',
                                                                        'text': '该配置可以在插件内已有元数据的基础上新增自定义扩展，配置规则请参考：'
                                                                    },
                                                                    {
                                                                        'component': 'a',
                                                                        'props': {
                                                                            'href': 'https://github.com/Sinterdial/MoviePilot-Plugins/blob/main/docs/Self_Defined_Competitions_Guide.md',
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
            "cron": "27 6-8 * * *",
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
            "start_paused": True,
            "competitions_config": get_demo_competitions_config(),
            "monitor_mode": "normal",
            "sync_all": False
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询同步详情
        histories = self.get_data('history')
        if not histories:
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
        histories = sorted(histories, key=lambda x: x.get('time'), reverse=True)
        # 拼装页面
        contents = []
        for history in histories:
            competition_name = history.get("competition_name")
            roundinfo = history.get("roundinfo")
            round_cn_name = history.get("round_cn_name")
            matchmake = history.get("matchmake")
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
                                        'key': competition_name,
                                        'roundinfo': roundinfo,
                                        'apikey': settings.API_TOKEN,
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
                                                'src': "https://media.posterlounge.com/img/products/760000/756250/756250_poster.jpg",
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
                                            'text': competition_name,
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'轮次：{round_cn_name}',
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'对阵：{matchmake}'
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'处理时间：{time_str}'
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


    # 声明重新实现的方法
    def get_module(self) -> Dict[str, Any]:
        """
        # 不知道为啥用不了
            获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）
            {
                "id1": self.xxx1,
                "id2": self.xxx2,
            }
        """
        return {
            # "media_exists": self.__exists_match,
            "async_search_by_title": self.plugin_async_search_by_title,
        }
        pass


    # 声明扩展 MP 内部的识别请求
    # @eventmanager.register(ChainEventType.NameRecognize)
    # def recognize(self, event: Event):
    #     """
    #     监听识别事件，使用ChatGPT辅助识别名称
    #     """
    #     if not event.event_data:
    #         return
    #     title = event.event_data.get("title")
    #     if not title:
    #         return
    #
    #
    #     # 保底识别信息
    #     match_metainfo = MetaInfo(title)
    #
    #     match_mediainfo = self.recognize_competition_mediainfo(meta_info=match_metainfo)
    #
    #     match_metainfo, match_episodeinfo = self.recognized_match_metainfo(match_mediainfo=match_mediainfo, metainfo=match_metainfo)
    #
    #     if match_mediainfo and match_metainfo:
    #         # 成功获取结果
    #         event.event_data = {
    #             'title': title,
    #             'name': match_mediainfo.title,
    #             'year': match_mediainfo.year,
    #             'season': match_metainfo.season,
    #             'episode': match_metainfo.episode,
    #         }
    #         return
    #     else:
    #         logger.error(f"无法识别标题 {title}，请添加自定义赛事索引")


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

        if self.__observer:
            for observer in self.__observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    print(str(e))
        self.__observer = []

    def delete_history(self, key: str, roundinfo: str, apikey: str):
        """
        删除同步历史记录
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        # 历史记录
        histories = self.get_data('history')
        if not histories:
            return schemas.Response(success=False, message="未找到历史记录")
        # 删除指定记录
        histories = [h for h in histories if (
            h.get("competition_name") != key or h.get("roundinfo") != roundinfo)]
        self.save_data('history', histories)
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
            "tags": ",".join(self.__tags),
            "size_range": self.__size_range,
            "downloaders": self.__downloaders,
            "force_en": self.__force_en,
            "lowest_pix": self.__lowest_pix,
            "transfer_type": self.__transfer_type,
            "need_rename": self.__need_rename,
            "start_paused": self.__start_paused,
            "max_download": self.__max_download,
            "competitions_config": self.__competitions_config,
            "monitor_mode": self.__monitor_mode,
            "sync_all": False,
        })

        # 组装赛事识别器（内置加用户自定义）
        self.__initialize_competition_config()


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

        sportscult_indexer_id = self.get_sportscult_indexer()

        if not sportscult_indexer_id:
            logger.error("Sportscult 站点配置错误，不再继续执行插件相关功能")
            return

        # 识别本地已入库所有比赛的信息
        exist_matches: Dict[str, Dict[int, list]] = self.__exists_match()
        if self.__sync_all:
            # 如果启用了全量扫描，开始全量同步目录中所有体育比赛文件
            self.sync_all(exist_matches=exist_matches)
            logger.info("文件同步结束")
            if exist_matches:
                logger.info(f"文件同步后，已入库媒体信息为:")
                for competition_name in exist_matches.keys():
                    logger.info(f"{competition_name} {exist_matches[competition_name]}")

        elif self.__action == "transfer":
            # 仅作整理，不下载
            logger.info(f"仅整理文件，不下载新种子")
            self.sync_all(exist_matches=exist_matches)
            logger.info("文件同步结束")
            if exist_matches:
                logger.info(f"文件同步后，已入库媒体信息为:")
                for competition_name in exist_matches.keys():
                    logger.info(f"{competition_name} {exist_matches[competition_name]}")
            self.__clearflag = False
            # 保存历史记录
            self.save_data('history', history)
            return

        # 搜索模块
        results = []
        for team_info in self.__teams_info.split("\n"):
            # 在 SportsCult 搜索种子
            if not team_info:
                continue
            logger.info(f"开始在 Sportscult 以关键词 {team_info} 搜索比赛...")

            search_results = searchchain.search_by_title(title=team_info, sites=[sportscult_indexer_id])
            if not search_results:
                logger.error(f"未获取到该球队相关比赛种子，请更换关键词再试试：{team_info}")
                continue
            else:
                results.extend(search_results)
        if not results:
            logger.error(f"所有关键词 ({'/'.join(self.__teams_info.split('\n'))}) 都未搜索到任何结果，请检查球队关键词设置")

        # 清空比赛元数据缓存
        if not self.__cached_matches:
            self.__cached_matches = {}

        # 初始化搜索到的比赛信息的储存对象
        matchesinfo = []

        # 解析数据
        for result in results:
            try:
                title = result.torrent_info.title
                logger.info(f"找到种子：{title}，开始处理......")
                description = result.torrent_info.description
                size = result.torrent_info.size
                # 检查是否处理过
                if not title or title in [h.get("torrent_title") for h in history]:
                    logger.info("已处理过该种子，请清除记录后重试")
                    continue
                # 默认排除篮球等其它比赛的关键词
                not_football = ['basketball', 'baseball', 'hockey']
                if any (x in f'{title.lower()} {description.lower()}' for x in not_football):
                    logger.info(f"该种子不是足球比赛，跳过")
                    continue
                # 检查规则
                if self.__include and not re.search(r"%s" % self.__include,
                                                    f"{title} {description}", re.IGNORECASE):
                    logger.info(f"该种子不符合包含规则，跳过")
                    continue
                if self.__exclude and re.search(r"%s" % self.__exclude,
                                                f"{title} {description}", re.IGNORECASE):
                    logger.info(f"该种子不符合排除规则，跳过")
                    continue
                if self.__size_range:
                    sizes = [float(_size) * 1024 ** 3 for _size in self.__size_range.split("-")]
                    if len(sizes) == 1 and float(size) < sizes[0]:
                        logger.info(f"该种子大小不符合条件")
                        continue
                    elif len(sizes) > 1 and not sizes[0] <= float(size) <= sizes[1]:
                        logger.info(f"该种子大小不在指定范围")
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
                        logger.info(f"{title} 不匹配过滤规则")
                        continue

                # 判断媒体库是否已存在该场比赛
                is_in = self.is_match_in_vault(exist_matches, gotten_match_metainfo)
                if is_in:
                    logger.info(
                        f'处理搜索到的种子时，发现 '
                        f'{gotten_match_metainfo.title_year} {gotten_match_metainfo.season_episode} 己入库，不再处理')
                    continue
                else:
                    logger.info(
                        f'处理搜索到的种子时，发现 '
                        f'{gotten_match_metainfo.title_year} {gotten_match_metainfo.season_episode} 未入库，继续处理')

                # 判断新搜索到的种子是否比之前的种子更好
                gotten_matchinfo = self.Matchinfo(gotten_torrentinfo, gotten_match_mediainfo, gotten_match_metainfo)
                gotten_matchinfo.language = self.recognize_language(gotten_match_metainfo)
                if gotten_metainfo.resource_pix:
                    if gotten_metainfo.resource_pix == '4k':
                        gotten_matchinfo.pix = 2160
                    elif gotten_metainfo.resource_pix == '2k':
                        gotten_matchinfo.pix = 1440
                    else:
                        gotten_matchinfo.pix = int(gotten_metainfo.resource_pix[0:-1])
                self.find_best(force_en=self.__force_en, lowest_pix=self.__lowest_pix, matchesinfo=matchesinfo,
                               new_matchinfo=gotten_matchinfo)
            except Exception as err:
                logger.error(f'自动寻找种子模块出错：{str(err)} - {traceback.format_exc()}')

        # 新增处理的比赛场数计数
        processed_num = 0

        for final_matchinfo in matchesinfo:
            if self.__max_download and processed_num >= self.__max_download:
                logger.info(f"已处理种子数量超过最大限制 {self.__max_download}，不再添加新的种子")
                break
            torrentinfo = final_matchinfo.torrentinfo
            match_mediainfo = final_matchinfo.mediainfo
            match_metainfo = final_matchinfo.metainfo
            title = torrentinfo.title
            # 下载或订阅
            if self.__action == "download":
                if match_metainfo.episode == 'E00':
                    logger.warning(f"种子 {torrentinfo.title} 未识别到轮次，将以暂停状态添加该种")
                    is_existed, torrent_hash = self.__download(torrentinfo, True, metainfo=match_metainfo)
                # 添加下载
                else:
                    is_existed, torrent_hash = self.__download(torrentinfo, self.__start_paused, metainfo=match_metainfo)
                if not torrent_hash:
                    logger.warning(f'{title} 下载失败')
                    processed_num += 1
                elif is_existed:
                    logger.info(f'{title} 已存在，种子 HASH 值为：{torrent_hash}')
                    # 存储历史记录
                    history.append({
                        "torrent_title": torrentinfo.title,
                        "competition_name": match_metainfo.title,
                        "roundinfo": match_metainfo.season_episode,
                        "round_cn_name": match_metainfo.cn_name.split(' - ')[0] + ' - ' + match_metainfo.cn_name.split(' - ')[1],
                        "matchmake": match_metainfo.subtitle,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    processed_num += 1
                else:
                    logger.info(f'{title} 下载成功，种子 HASH 值为：{torrent_hash}')
                    # 发送消息
                    self.post_message(mtype=NotificationType.Download,
                                      title=f"体育比赛种子【{title}】已开始下载",
                                      text=f"赛事：{match_mediainfo.title}\n"
                                           f"轮次: {match_metainfo.cn_name.split(' - ')[0] + ' - ' + match_metainfo.cn_name.split(' - ')[1]}\n"
                                           f"对阵: {match_metainfo.subtitle}")
                    # 存储历史记录
                    history.append({
                        "torrent_title": torrentinfo.title,
                        "competition_name": match_metainfo.title,
                        "roundinfo": match_metainfo.season_episode,
                        "round_cn_name": match_metainfo.cn_name.split(' - ')[0] + ' - ' + match_metainfo.cn_name.split(' - ')[1],
                        "matchmake": match_metainfo.subtitle,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    processed_num += 1
            else:
                # TODO: 支持订阅功能
                # logger.error(f'暂不支持订阅功能，请等待适配')
                # # 保存历史记录
                # self.save_data('history', history)
                # # 缓存只清理一次
                # self.__clearflag = False
                # return
                # # 检查是否在订阅中
                # subflag = subscribechain.exists(mediainfo=match_mediainfo, meta=match_metainfo)
                # if subflag:
                #     logger.info(f'{match_mediainfo.title_year} {metainfo.season} 正在订阅中')
                #     continue
                # # 添加订阅
                # subscribechain.add(title=match_mediainfo.title,
                #                    year=match_mediainfo.year,
                #                    mtype=match_mediainfo.type,
                #                    tmdbid=match_mediainfo.tmdb_id,
                #                    season=metainfo.begin_season,
                #                    exist_ok=True,
                #                    username="AutoSports")
                pass

        if not processed_num:
            logger.info(f"未找到任何种子或所有比赛已入库，不进行添加任何下载")
        logger.info(f"AutoSports 下载任务刷新完成")
        # 保存历史记录
        self.save_data('history', history)


        # 30 分钟后分别尝试再次整理 (已用增量监控目录服务替代)
        # logger.info(f"等待 30 分钟后再次尝试进行比赛整理")
        # transfer_scheduler = BackgroundScheduler(timezone=settings.TZ)
        # transfer_scheduler.add_job(func=self.sync_all, trigger='date',
        #                          run_date=datetime.datetime.now(
        #                              tz=pytz.timezone(settings.TZ)) + datetime.timedelta(minutes=30)
        #                          )
        # # 挂载刮削任务
        # if transfer_scheduler.get_jobs():
        #     transfer_scheduler.print_jobs()
        #     transfer_scheduler.start()

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


    def process_data(self, key: str = '', value = None):
        """
        使用系统级缓存处理事件
        @param key: 要保存到的键
        @param value: 要保存的值
        @return: 若查询到，返回查询到的值，否则返回空
        """
        # 检查缓存
        if key in self.__system_cache:
            # 若有值则返回查询到的值
            return self.__system_cache[key]
        # 如果对应key且未传入任何要缓存的value，则返回空
        if not value:
            return None
        # 否则，存储传入的对象
        self.__system_cache[key] = value
        return value


    def event_handler(self, event, source_dir: str, event_path: str):
        """
        处理文件变化
        :param event: 事件
        :param source_dir: 监控目录
        :param event_path: 事件文件路径
        """

        # 回收站及隐藏的文件不处理
        if (event_path.find("/@Recycle") != -1
            or event_path.find("/#recycle") != -1
            or event_path.find("/.") != -1
            or event_path.find("/@eaDir") != -1):
            logger.info(f"{event_path} 是回收站或隐藏的文件，跳过处理")
            return

        # 命中过滤关键字不处理
        if self.__exclude:
            for keyword in self.__exclude.split("\n"):
                if keyword and re.findall(keyword, event_path):
                    logger.info(f"{event_path} 命中过滤关键字 {keyword}，不处理")
                    return

        # 不是媒体文件不处理
        if Path(event_path).suffix not in settings.RMT_MEDIAEXT:
            logger.debug(f"{event_path} 不是媒体文件")
            return

        # 文件发生变化
        logger.debug(f"变动类型 {event.event_type} 变动路径 {event_path}")

        exist_matches = self.__exists_match()

        self.__handle_file(event_path=event_path, exist_matches=exist_matches)


    def sync_all(self, exist_matches: Dict[str, Dict[int, list]] = None):
        """
        全量同步目录中所有文件
        """
        # 如果未传入已入库比赛信息，进行已入库媒体判断
        if not exist_matches:
            exist_matches = self.__exists_match()

        logger.info(f"开始全量整理体育比赛监控目录 {self.__save_path} ...")
        # 遍历下载目录
        for file_path in SystemUtils.list_files(Path(self.__save_path), settings.RMT_MEDIAEXT):
            logger.info(f"开始处理文件 {file_path} ...")
            self.__handle_file(event_path=str(file_path), exist_matches=exist_matches)
        logger.info("全量整理体育比赛监控目录完成！")


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
                        logger.debug(f"缩略图已存在：{title}_thumb.jpg")
                        return
                    self.get_thumb(video_path=str(file_path),
                                   image_path=str(thumb_path),
                                   frames=self.__timeline)
                    if Path(thumb_path).exists():
                        logger.debug(f"{file_path} 缩略图已生成：{title}_thumb.jpg")
                        return thumb_path
                except Exception as err:
                    logger.error(f"FFmpeg 处理文件 {file_path} 时发生错误：{str(err)}")
                    return None


    async def plugin_async_search_by_title(self, title: str, page: Optional[int] = 0,
                                    sites: List[int] = None, cache_local: Optional[bool] = False) -> List[Context]:
        """
        重载搜索种子方法，以正确识别 Sportscult 网站种子
        :param title: 标题，为空时返回所有站点首页内容
        :param page: 页码
        :param sites: 站点ID列表
        :param cache_local: 是否缓存到本地
        """
        self.searchchain = SearchChain()

        if title:
            logger.info(f'开始搜索资源，关键词：{title} ...')
        else:
            logger.info(f'开始浏览资源，站点：{sites} ...')
        # 搜索
        torrents = await self.searchchain.__async_search_all_sites(keyword=title, sites=sites, page=page) or []
        if not torrents:
            logger.warn(f'{title} 未搜索到资源')
            return []
        # 组装上下文
        sportscult_indexer = self.get_sportscult_indexer()
        if len(sites) == 1 and sportscult_indexer in sites:
            logger.info("使用 AutoSports 插件重载的方法识别 Sportscult 站点资源")
            contexts = []
            for torrent in torrents:
                raw_metainfo = MetaInfo(title=torrent.title, subtitle=torrent.description)
                match_mediainfo = self.recognize_competition_mediainfo(meta_info=raw_metainfo)
                if match_mediainfo:
                    match_metainfo, match_episodeinfo = self.recognized_match_metainfo(match_mediainfo=match_mediainfo, metainfo=raw_metainfo)
                    if match_metainfo and  match_episodeinfo:
                        contexts.append(Context(meta_info=match_metainfo, torrent_info=torrent))
                    else:
                        contexts.append(Context(meta_info=raw_metainfo, torrent_info=torrent))
                else:
                    contexts.append(Context(meta_info=raw_metainfo, torrent_info=torrent))
        else:
            contexts = [Context(meta_info=MetaInfo(title=torrent.title, subtitle=torrent.description),
                                torrent_info=torrent) for torrent in torrents]

        # 如果是 Sportscult 站点，对得到的上下文进行精修

        # 保存到本地文件
        if cache_local:
            await self.searchchain.async_save_cache(contexts, self.searchchain.__result_temp_file)
        return contexts


    def get_match_raw_metadata_offline(self, metainfo: MetaVideo = None, matched_competition_parse: json = None,
                                       home_team: str = '', away_team: str = ''):
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
                    match["matchday"] = int(math.log2(single_start_num / team_count)) + 1
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
                    match["matchday"] = (int(math.log2(single_start_num / double_start_num)) + 1 +
                                         int(math.log2(double_start_num / team_count)) * 2)
                    match["round_cn_name"] = f"{self.number_to_chinese(team_count)}强赛"
                    match["round_en_name"] = f"R{team_count}"
                    if team_count == 4:
                        # 判断是否为半决赛
                        match["round_cn_name"] = f"半决赛 首回合"
                        match["round_en_name"] = f"Semi Finals 1st Leg"
                        if re.search(r'\b(?:leg\s*(?:2|2nd)|(?:2|2nd)\s*leg)\b', match_org_title, re.IGNORECASE):
                            match["matchday"] += 1
                            match["round_cn_name"] = f"半决赛 次回合"
                            match["round_en_name"] = f"Semi Finals 2nd Leg"
                    if team_count == 2:
                        # 决赛
                        match["round_cn_name"] = f"决赛"
                        match["round_en_name"] = f"The Final"
                break

        if match["matchday"] == 0:
            logger.warning(f"轮次未识别成功，建议手动修订: {metainfo.title}")
        else:
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
            logger.debug(f"从缓存 {requests_key} 中读取 football-data.org 赛事数据...")
        else:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            logger.debug(f"从 {url} 中读取 football-data.org 赛事数据...")
            data = resp.json()
            self.__cached_matches[requests_key] = data

        if "matches" not in data:
            logger.warning(f"未在 football-data.org 上获取到比赛信息，请检查"
                           f"输入信息，competition_shortname: {competition_shortname}，"
                           f"season: {season}")
            return None

        for match in data["matches"]:
            # 全名 (优先匹配)
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]
            # 简称
            home_short = match["homeTeam"]["shortName"]
            away_short = match["awayTeam"]["shortName"]
            if not home or not away:
                # 该比赛还未排期，后面的比赛也同样没排期，直接退出循环
                break

            if any(home_team_i in home for home_team_i in home_team) and any(
                away_team_i in away for away_team_i in away_team):
                # 优先匹配全名
                return match
            elif any(home_short in home_team_i for home_team_i in home_team) and any(
                away_short in away_team_i for away_team_i in away_team):
                # 否则尝试匹配简称
                return match

        return None


    def get_match_raw_metadata(self, metainfo: MetaBase = None, competition_name:str = '', season:int = 0, home_team: list[str] = '', away_team: list[str] = ''):
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
            logger.debug(f"在线刮削赛事 {competition_name} 中的比赛")
            match_result = self.get_match_raw_metadata_online(competition_shortname, season, home_team, away_team)
        else:
            # 定义离线信息，离线刮削
            logger.debug(f"离线刮削赛事 {competition_name} 中的比赛")
            match_result = self.get_match_raw_metadata_offline(metainfo, matched_competition_parse, home_team[0], away_team[0])

        if match_result:
            return match_result
        else:
            logger.warning(f'未匹配到相关比赛，请检查输入信息，competition_name: {competition_name}，season: {season}, home_team: {home_team}, away_team: {away_team}')
            return None


    def recognized_match_metainfo(self, match_mediainfo: MediaInfo, metainfo: MetaBase) -> (MetaBase | None, TmdbEpisode | None) :
        """
          根据给定的规则刮削单场比赛信息
        """
        match_metainfo = deepcopy(metainfo)
        episode_metainfo = TmdbEpisode()

        competition_cn_name = match_mediainfo.title

        org_str = metainfo.org_string
        # 获取赛季信息
        try:
            season_name = metainfo.year
            if not season_name:
                # 尝试在原标题中找到年份
                match_date = self.extract_date(org_str)
                if not match_date:
                    logger.warning("未获取到比赛日期")
                    logger.warning("未成功匹配到赛季信息，跳过")
                    return None, None
                else:
                    if match_date[1] < 7:
                        # 如果比赛日期在七月之前，是上一年开始的赛季
                        season = match_date[0] - 1
                    else:
                        season = match_date[0]
            else:
                season = int(season_name)

            # 赛季数修正
            if any(
                season_str in org_str for season_str in
                [
                    str(season - 1) + "." + str(season),
                    str(season - 1) + "/" + str(season)
                ]):
                # 适配特殊格式的西甲比赛
                season -= 1
                match_mediainfo.season = season
            if (match_mediainfo.title in ["西班牙超级杯", "西班牙国王杯"]
                and season == datetime.date.today().year):
                # 杯赛特殊处理
                season -= 1
                match_mediainfo.season = season
            if season == datetime.date.today().year and datetime.date.today().month < 8:
                # 联赛前九月视为上一个赛季
                season -= 1
                match_mediainfo.season = season

            # 年份信息回填赛事元数据
            metainfo.year = str(season)

            season_shortname = season % 100
            # 解析赛季信息
            season_cn_name = f"{season_shortname:02d}-{(season_shortname + 1):02d}赛季"
            season_en_name = f"Season {season_shortname:02d}-{(season_shortname + 1):02d}"
            match_mediainfo.season = int(metainfo.year)
            logger.info(f"成功匹配到赛季信息：{season_cn_name}")
        except AttributeError:
            logger.warn("未成功匹配到赛季信息，跳过")
            return None, None

        # 分析主客场球队
        try:
            # 匹配对阵信息
            matchup = re.search( r'([A-Za-zÀ-ÿ ]+?)\s+vs\s+([A-Za-zÀ-ÿ ]+?)(?=\s*\||\s+\d|\.|$)', org_str, re.IGNORECASE)
            if not matchup:
                # 适配种子名里有 '.' 的格式
                matchup = re.search(r'([A-Za-zÀ-ÿ ]+?)\s*\.?\s*v\.?\s*s\.?\s*\.?\s*([A-Za-zÀ-ÿ ]+?)(?=\s*\||\s+\d|\.|$)', org_str, re.IGNORECASE)
            if not matchup:
                # 适配种子名里有 ',' 的格式
                matchup = re.search(r'([A-Za-zÀ-ÿ ]+?)\s+vs\s+([A-Za-zÀ-ÿ ]+?)(?=\s*\||\s+\d|\.|,|$)', org_str, re.IGNORECASE)
            if not matchup:
                # 匹配带有转播信息，压制信息等后缀的格式
                matchup = re.search(
                    r'(.+?)\s+vs\s+(.+?)(?=\s+(?:WEB|HDTV|UHD|BluRay|\d{3,4}p)|$)',
                    org_str,
                    re.IGNORECASE
                )

            home_team: list[str] = re.findall(r'\D+', matchup.group(1))
            away_team: list[str] =  re.findall(r'\D+', matchup.group(2))

            # 组装名称中的非法字符排除器
            illegal_fix = []
            # 各赛事名
            for competition_parse in self.__competitions_parses:
                illegal_fix.extend(competition_parse.get("names"))
            # 赛事阶段标识
            illegal_fix.extend(["League Phase", "st leg", "st Leg", "WEB", "STAN"])

            # 处理主队名
            # 去掉多余的前后空格
            home_team = [home_team_str_i.strip() for home_team_str_i in home_team]
            # 去掉多余的前缀
            for p in illegal_fix:
                for i, home_team_str_i in enumerate(home_team):
                    if home_team_str_i.startswith(p):
                        home_team[i] = home_team_str_i[len(p):]
            # 去掉多余的前后空格
            home_team = [home_team_str_i.strip() for home_team_str_i in home_team]

            # 处理客队名
            # 去掉多余的前后空格
            away_team = [away_team_str_i.strip() for away_team_str_i in away_team]
            # 去掉多余的后缀
            for p in illegal_fix:
                for i, home_team_str_i in enumerate(home_team):
                    if home_team_str_i.endswith(p):
                        home_team[i] = home_team_str_i[:-len(p)]
            # 去掉多余的前后空格
            away_team = [away_team_str_i.strip() for away_team_str_i in away_team]

            # 去掉长度过短的字符串
            min_len = 3
            home_team = [home_team_str_i for home_team_str_i in home_team if len(home_team_str_i) >= min_len]
            away_team = [away_team_str_i for away_team_str_i in away_team if len(away_team_str_i) >= min_len]
            logger.info(f"成功匹配到对阵信息：{home_team} vs {away_team}")
        except AttributeError:
            logger.warning("未成功匹配到对阵信息，跳过")
            return None, None

        # 获取比赛相关元数据
        raw_matchdata = self.get_match_raw_metadata(metainfo, competition_cn_name, season, home_team, away_team)
        if not raw_matchdata:
            logger.warning("未获取到比赛元数据，跳过")
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
            except AttributeError:
                logger.warn("未成功匹配到轮次信息，跳过")
                return None, None
        else:
            round_info = raw_matchdata['matchday']
            if raw_matchdata['stage'] == 'LEAGUE_STAGE':
                # 小组赛阶段
                round_cn_name = f"联赛阶段 第{self.number_to_chinese(round_info)}轮"
                round_en_name = f"Group Stage Round {round_info}"
            else:
                if competition_cn_name == "欧洲冠军联赛":
                    # 欧冠赛制特殊处理
                    # football-data.org stage 字段映射
                    stage_parse = {
                        'PLAYOFFS': 0,
                        'LAST_16': 1,
                        # 'LAST_8': 2,
                        'QUARTER_FINALS': 2,
                        'SEMI_FINALS': 3,
                        'FINAL': 4,
                    }
                    round_cn_name_list = [
                        "联赛阶段附加赛 首回合", "联赛阶段附加赛 次回合",
                        # "32强赛 首回合", "32强赛 次回合",
                        "十六强赛 首回合", "十六强赛 次回合",
                        "八强赛 首回合", "八强赛 次回合",
                        "半决赛 首回合", "半决赛 次回合",
                        "决赛"
                    ]
                    round_en_name_list = [
                        "联赛阶段附加赛 次回合", "联赛阶段附加赛 次回合",
                        # "R32 1st Round", "R32 2nd Round",
                        "R16 1st Round", "R16 2nd Round",
                        "R8 1st Round", "R8 2nd Round",
                        "Semi Finals 1st Round", "Semi Finals 2nd Round",
                        "Final"
                    ]
                    # 淘汰赛
                    round_idx = stage_parse.get(raw_matchdata['stage']) * 2 + raw_matchdata.get('matchday', 0) - 1
                    round_info = 8 + stage_parse.get(raw_matchdata['stage']) * 2 + raw_matchdata.get('matchday', 0)
                    round_cn_name = round_cn_name_list[round_idx]
                    round_en_name = round_en_name_list[round_idx]
                else:
                    round_cn_name = raw_matchdata['round_cn_name']
                    round_en_name = raw_matchdata['round_en_name']
            logger.info(f"成功匹配到轮次信息：{round_cn_name}")

        # 解析对阵信息
        home_team = raw_matchdata['homeTeam']['name']
        away_team = raw_matchdata['awayTeam']['name']
        matchmake_en_name = matchmake_cn_name = f"{home_team} vs {away_team}"

        # 刮削比赛信息
        match_metainfo.cn_name = " - ".join([season_cn_name, round_cn_name, matchmake_cn_name])
        match_metainfo.en_name = " - ".join([season_en_name, round_en_name, matchmake_en_name])
        match_metainfo.type = MediaType.TV
        match_metainfo.set_season(season)
        match_metainfo.set_episode(round_info)
        match_metainfo.subtitle = matchmake_cn_name
        match_metainfo.title = competition_cn_name
        match_metainfo.title_year = f"{competition_cn_name} ({season_cn_name})"
        match_metainfo.begin_episode = round_info
        match_metainfo.begin_season = season

        # 解析清晰度信息
        if any(pix_alia in org_str for pix_alia in ['4k', '4K', '2160p']):
            match_metainfo.resource_pix = '2160p'
        elif any(pix_alia in org_str for pix_alia in ['2k', '2K', '1440p']):
            match_metainfo.resource_pix = '1440p'

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

        for competition_parse in self.__competitions_parses:
            if any(alia.lower() in title.lower() for alia in competition_parse["names"]):
                # 匹配任意一个别名，开始解析
                self.scrape_competition(competition_mediainfo, competition_parse)
                competition_mediainfo.type = MediaType.TV
                # competition_mediainfo.season = int(meta_info.year)
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
    def get_sportscult_indexer() -> int | None:
        for indexer in SitesHelper().get_indexers():
            if indexer.get("name") == "Sportscult":
                # 检查站点索引开关
                if indexer.get("is_active"):
                    # sportscult_indexer = indexer
                    sportscult_indexer_id: int = indexer.get("id")
                    return sportscult_indexer_id
                else:
                    logger.error(f"Sportscult 站点未启用，请检查站点设置")
                    return None

        # 遍历所有站点没有找到，返回 None
        logger.error(f"Sportscult 站点未正确添加，请检查站点设置")
        return None


    @staticmethod
    def is_match_in_vault(exist_matches: Dict[str, Dict[int, list]] = None, gotten_match_metainfo: MetaVideo = None) -> bool:
        logger.debug(f"开始判断该场比赛是否已入库")
        if exist_matches:
            exist_competitions = exist_matches.keys()
            for exist_competition in exist_competitions:
                if exist_competition == gotten_match_metainfo.title:
                    exist_seasons = exist_matches.get(exist_competition)
                    if exist_seasons:
                        exist_episodes = exist_seasons.get(gotten_match_metainfo.begin_season)
                        if exist_episodes and set(gotten_match_metainfo.episode_list).issubset(set(exist_episodes)):
                            return True
        return False


    @staticmethod
    def add_match_to_vault(exist_matches: Dict[str, Dict[int, list]] = None,
                          gotten_match_metainfo: MetaVideo = None) -> bool:
        logger.debug(f"开始添加已整理比赛到已入库列表中")

        if exist_matches:
            exist_competitions = exist_matches.keys()
            if gotten_match_metainfo.title not in exist_competitions:
                # 赛事不存在，添加该赛事的该赛季的该场比赛
                exist_matches.update({gotten_match_metainfo.title: {gotten_match_metainfo.begin_season: gotten_match_metainfo.episode_list}})
            elif gotten_match_metainfo.begin_season not in exist_matches.get(gotten_match_metainfo.title):
                # 赛季不存在，添加该赛季的该场比赛
                exist_matches[gotten_match_metainfo.title].update({gotten_match_metainfo.begin_season: gotten_match_metainfo.episode_list})
            else:
                # 比赛不存在，添加比赛
                exist_matches[gotten_match_metainfo.title][gotten_match_metainfo.begin_season].extend(gotten_match_metainfo.episode_list)
            return True
        else:
            return False


    @staticmethod
    def find_best(force_en: bool = False, lowest_pix: int = 0, matchesinfo: list[Matchinfo] = None,
                  new_matchinfo: Matchinfo = None):
        """
          判断传入的种子是否比现有的优先级更高
        """
        if (force_en and new_matchinfo.language != "en") or new_matchinfo.pix < lowest_pix:
            # 不满足约束条件，直接退出
            logger.info(
                f"不满足约束条件，直接退出")
            return

        # 判断之前是否已搜索到该场比赛的种子
        for i, old_matchinfo in enumerate(matchesinfo):
            if new_matchinfo.metainfo.title != old_matchinfo.metainfo.title:
                # 如果赛事不匹配，直接跳过
                continue
            if new_matchinfo.metainfo.season_episode == old_matchinfo.metainfo.season_episode:
                if new_matchinfo.language == "en" and old_matchinfo.language != "en":
                    matchesinfo[i] = new_matchinfo
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title}) 的解说语言为英语，而之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) 不是，替换")
                    return
                elif new_matchinfo.pix > old_matchinfo.pix:
                    matchesinfo[i] = new_matchinfo
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title})的清晰度高于之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) ，替换")
                    return
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

        result = SystemUtils.execute(cmd)

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
              |
                ((?:19|20)\d{2})\s*(\d{1,2})\s*(\d{1,2})   # YYYY MM DD 忽略空格
              |
                (\d{1,2})\s*(\d{1,2})\s*((?:19|20)\d{2})   # DD MM YYYY 忽略空格
            )
            \b
            """,
            re.VERBOSE
        )

        m = date_re.search(s)
        if not m:
            return None

        year, month, day = (2026, 1, 1)
        if m.group(1):  # YYYY MM DD
            year, month, day = m.group(1), m.group(2), m.group(3)
        elif m.group(2):  # DD MM YYYY
            year, month, day = m.group(6), m.group(5), m.group(4)
        elif m.group(3):
            year, month, day = m.group(9), m.group(8), m.group(7)
        return int(year), int(month), int(day)


    @staticmethod
    def recognize_language(metainfo: MetaVideo) -> str:
        if any(lang in metainfo.name for lang in ["EN", "English"]):
            return "en"
        elif any(lang in metainfo.name for lang in ["PL", "Polish", "POLISH"]):
            return "pl"
        elif any(lang in metainfo.name for lang in ["Spanish", "SPANISH", "spanish"]):
            return "sp"
        elif any(lang in metainfo.name for lang in ["French", "FRENCH", "french"]):
            return "fr"
        elif any(lang in metainfo.name for lang in ["Dutch", "DUTCH", "drench"]):
            return "dt"

        # 默认英语
        return "en"


    @staticmethod
    def scrape_competition(matchinfo: MediaInfo, competition_parse: {}):
        """
          根据给定的 JSON 规则刮削体育比赛
        """
        for f in fields(matchinfo):
            if f.name in competition_parse:
                setattr(matchinfo, f.name, competition_parse[f.name])
        pass


    @staticmethod
    def recognized_saved_match_metainfo(metainfo: MetaBase) -> (MetaVideo | None, TmdbEpisode | None):
        """
          根据给定的规则刮削已入库的单场比赛的元数据
        """
        match_metainfo = deepcopy(metainfo)
        episode_metainfo = TmdbEpisode()

        competition_cn_name = metainfo.name

        org_str = metainfo.org_string

        # 解析集数信息
        season_round_info = re.search(r'\bS(\d+)E(\d+)\b', org_str, re.I)
        season = int(season_round_info.group(1))
        round_info = int(season_round_info.group(2))
        match_metainfo.set_season(season)
        match_metainfo.set_episode(round_info)
        match_metainfo.subtitle = ""
        match_metainfo.title = competition_cn_name
        match_metainfo.begin_episode = round_info
        match_metainfo.begin_season = season

        return match_metainfo, episode_metainfo


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


    def __parse_file_metadata(self, filepath: str, saved: bool = False):
        """
        根据路径识别体育媒体信息
        saved: 是否要刮削已入库的文件
        """
        match_filemeta = MetaInfoPath(Path(filepath))
        if not match_filemeta.name:
            logger.warning(f"{Path(filepath).name} 无法根据文件名识别有效信息")
            return None, None, None
        # 提取文件名
        filepath_name = match_filemeta.title
        if not saved:
            # 在缓存中查找文件名到种子名的映射关系
            cache_result = self.process_data(filepath_name)
            if cache_result:
                # 如果查询到了任何值，则替换要处理的文件名
                logger.debug(
                    f"使用缓存的文件名到种子名映射关系，处理文件：{filepath_name} -> {cache_result}")
                match_filemeta.org_string = cache_result

        match_mediainfo: MediaInfo = self.recognize_competition_mediainfo(meta_info=match_filemeta)
        if not match_mediainfo:
            # 未识别到赛事信息，返回 None
            return None, None, None
        if saved:
            match_filemeta, match_episode_info = self.recognized_saved_match_metainfo(metainfo=match_filemeta)
        else:
            match_filemeta, match_episode_info = self.recognized_match_metainfo(match_mediainfo=match_mediainfo,
                                                                              metainfo=match_filemeta)
        return match_filemeta, match_mediainfo, match_episode_info


    def __exists_match(self) -> Dict[str, Dict[int, list]]:
        """
        判断比赛文件是否存在于文件系统（网盘或本地文件），只支持标准媒体库结构
        :return: 如不存在返回None，存在时返回信息，包括每季已存在所有集{type: movie/tv, seasons: {season: [episodes]}}
        """
        if not settings.LOCAL_EXISTS_SEARCH:
            logger.info("MP 全局文件扫描设置未开启，无法进行本地比赛入库检查")
            return {}

        logger.info(f"正在转移目录中查找已入库所有比赛的信息...")

        # 检索本地所有集数
        matches: Dict[str, Dict[int, list]] = dict()
        for file_path in SystemUtils.list_files(Path(self.__dest_path), settings.RMT_MEDIAEXT):
            # 刮削已入库比赛的元数据
            file_meta, mediainfo, episode_info = self.__parse_file_metadata(Path(file_path).as_posix(), True)

            if not file_meta or not mediainfo or not episode_info:
                # 未识别到有效信息，跳过
                continue

            competition_name = mediainfo.title
            season_index = file_meta.begin_season or 1
            episode_index = file_meta.begin_episode
            if not competition_name:
                continue
            if not episode_index:
                continue
            matches.setdefault(competition_name, {})
            matches[competition_name].setdefault(season_index, [])
            if season_index not in matches[competition_name]:
                matches[competition_name][season_index] = []
            if episode_index not in matches[competition_name][season_index]:
                matches[competition_name][season_index].append(episode_index)

        # 返回已入库比赛情况
        if matches:
            for competition_name in matches.keys():
                # 赛季排序
                matches[competition_name] = {
                    k: v for k, v in sorted(matches[competition_name].items(), key=lambda item: item[0])
                }
                # 比赛轮次排序
                for season in matches[competition_name].keys():
                    # 比赛轮次排序
                    matches[competition_name][season].sort()
                logger.info(f"{competition_name} 在转移目录中找到了这些赛季/轮次：{matches[competition_name]}")
        else:
            logger.info(f"转移目录中未找到任何比赛的任何赛季/轮次")

        return matches


    def __handle_file(self, event_path: str, exist_matches: Dict[str, Dict[int, list]] = None):
        """
        同步一个文件
        :event.is_directory
        :param event_path: 事件文件路径
        """
        try:
            # 转移路径
            dest_dir = self.__dest_path
            # 是否重命名
            rename_conf = self.__need_rename

            logger.info(f'检测到文件变更，开始处理文件：{Path(event_path).name}')

            file_meta, mediainfo, episode_info = self.__parse_file_metadata(event_path)
            if not file_meta or not mediainfo or not episode_info:
                logger.error(f"{Path(event_path).name} 无法根据文件名识别有效信息")
                return

            # mediainfo: MediaInfo = self.chain.recognize_media(meta=file_meta)
            transfer_flag = False
            target_path_str = ''

            # 进行转移
            if mediainfo and episode_info:
                try:
                    # 查询转移目的目录
                    target_dir = DirectoryHelper().get_dir(mediainfo, dest_path=Path(dest_dir))
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

                    is_in = self.is_match_in_vault(exist_matches=exist_matches, gotten_match_metainfo=file_meta)

                    if not is_in:
                        logger.info(
                            f'在进行文件转移时，发现 '
                            f'{file_meta.title_year} {file_meta.season_episode} 未入库，继续整理')
                        transferinfo: TransferInfo = self.chain.transfer(mediainfo=mediainfo,
                                                                     fileitem=source_fileitem,
                                                                     target_directory=target_dir,
                                                                     meta=file_meta,
                                                                     episodes_info=episodes_info)
                        if not transferinfo:
                            logger.error(f"单场比赛文件整理/重命名失败：{event_path}，不进行刮削动作")
                            transfer_flag = False
                        else:
                            target_path_str = transferinfo.target_item.path
                            logger.info(f"单场比赛文件整理/重命名成功：{event_path} -> {target_path_str}")
                            # 添加新转移的媒体到已入库比赛列表中
                            self.add_match_to_vault(exist_matches=exist_matches, gotten_match_metainfo=file_meta)
                            transfer_flag = True
                    else:
                        # 该场比赛已入库，不进行处理
                        logger.info(
                            f'在进行文件转移时，发现 '
                            f'{file_meta.title_year} {file_meta.season_episode} 己入库，不再处理')
                        transfer_flag = False
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
                # 生成赛事的NFO文件
                if not (target_file.parent.parent / "tvshow.nfo").exists():
                    self.__gen_competition_nfo_file(dir_path=target_file.parent.parent, mediainfo=mediainfo)
                # 生成单场比赛的NFO文件
                if not (target_file.parent / f"{title}.nfo").exists():
                    self.__gen_match_nfo_file(dir_path=target_file.parent, title=title,
                                              file_meta=file_meta, episode_meta=episode_info)

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
                            logger.debug(f"{target_file.parent} / {title}_poster.jpg 缩略图已生成")
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
                            if (target_file.parent / f"{title}_poster.jpg").exists():
                                logger.debug(f"{target_file.parent} / {title}_poster.jpg 缩略图已生成")
                            # 删除多余jpg
                            for thumb in thumb_files:
                                Path(thumb).unlink()

                if self.__notify:
                    # 发送消息
                    # TODO: 发送消息添加缓存机制
                    # if title not in self.__cached_messages:
                    # 发送消息
                    self.post_message(mtype=NotificationType.Organize,
                                      title=f"体育比赛【{title}】已入库",
                                      text=f"赛事：{file_meta.title}\n"
                                           f"轮次: {file_meta.cn_name.split(' - ')[0] + file_meta.cn_name.split(' - ')[1]}\n"
                                           f"对阵: {file_meta.subtitle}")
                        # self.__cached_messages.append(title)
        except Exception as e:
            logger.error(f"文件整理/重命名模块运行错误，详细信息: {e}")
            print(str(e))


    def __gen_competition_nfo_file(self, dir_path: Path, mediainfo: MediaInfo = None):
        """
        生成赛事的 NFO 描述文件
        @param dir_path: 目标目录
        @param mediainfo: 赛事元数据
        """
        # 开始生成XML
        logger.debug(f"正在生成赛事NFO文件：{mediainfo.title}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "tvshow")

        # 各种信息
        DomUtils.add_node(doc, root, "title", mediainfo.title)
        DomUtils.add_node(doc, root, "sorttitle", mediainfo.en_title or '')
        DomUtils.add_node(doc, root, "status", 'Continuing')
        DomUtils.add_node(doc, root, "originaltitle", mediainfo.original_name or '')
        DomUtils.add_node(doc, root, "year", mediainfo.year or '')
        DomUtils.add_node(doc, root, "plot", mediainfo.overview or '')
        DomUtils.add_node(doc, root, "genre", 'Sport')
        DomUtils.add_node(doc, root, "genre", 'Soccer')
        if mediainfo.production_companies:
            for production_company in mediainfo.production_companies:
                DomUtils.add_node(doc, root, "studio", production_company or '')
        # 保存
        self.__save_nfo(doc, dir_path.joinpath(f"tvshow.nfo"))


    def __gen_match_nfo_file(self, dir_path: Path, title: str = '', file_meta: MetaBase = None,
                             episode_meta: TmdbEpisode = None):
        """
        生成单场比赛的 NFO 描述文件
        :param dir_path: 比赛根目录
        """
        # 开始生成XML
        logger.debug(f"正在生成比赛NFO文件：{title}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "episodedetails")

        # 各种信息
        DomUtils.add_node(doc, root, "title", file_meta.cn_name or '')
        DomUtils.add_node(doc, root, "originaltitle", file_meta.en_name or '')
        DomUtils.add_node(doc, root, "season", file_meta.begin_season or '')
        DomUtils.add_node(doc, root, "episode", file_meta.begin_episode or '')
        DomUtils.add_node(doc, root, "aired", str(episode_meta.air_date).split(' ')[0] or '')
        # 保存
        self.__save_nfo(doc, dir_path.joinpath(f"{title}.nfo"))


    def __download(self, torrent: TorrentInfo, is_paused: bool,
                   metainfo: MetaBase = None) -> tuple[bool, Optional[str]]:
        """
        添加下载任务
        torrent: TorrentInfo 要添加下载的种子的信息
        is_paused: bool 是否以暂停状态添加种子
        match_title: MetaBase 识别后的比赛元数据
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
                    logger.warning("尝试通过 MP 下载种子失败，继续尝试传递种子地址到下载器进行下载")
            if torrent_content:
                existed_torrents = downloader.get_torrents(tags=["AutoSports"])
                # 判断是否已添加该任务
                if existed_torrents:
                    for torrent_data in existed_torrents[0]:
                        torrent_name = torrent_data.get("name")
                        if torrent.title in torrent_name:
                            torrent_hash = torrent_data.get("hash")
                            return True, torrent_hash
                        else:
                            # 尝试从缓存中找替代名
                            cached_name = self.process_data(torrent_name)
                            if cached_name and metainfo.title + ' - ' + metainfo.cn_name == cached_name:
                                torrent_hash = torrent_data.get("hash")
                                return True, torrent_hash

                state = downloader.add_torrent(content=torrent_content,
                                           download_dir=download_dir,
                                           is_paused=is_paused,  # 调试用
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
                    # 关联种子名和文件名并储存到缓存中
                    torrent_files = downloader.get_files(torrent_hash)
                    if len(torrent_files) <= 1:
                        # 单文件，直接存储种子名-文件名映射关系到缓存中
                        file_name_str = torrent_files[0].get("name")
                        file_name = file_name_str.split('/')[-1]
                        self.process_data(file_name, metainfo.title + ' - ' + metainfo.cn_name)
                        logger.debug(f"在缓存中成功建立映射关系：{file_name} -> {metainfo.title + ' - ' + metainfo.cn_name}")
                    if is_paused:
                        logger.info("根据设置，添加下载任务后即刻暂停")
                    else:
                        logger.info("根据设置，添加下载任务后即刻开始")
                    return False, torrent_hash
            return False, None

        elif downloader_helper.is_downloader("transmission", service=self.__service_info):
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            # 生成随机Tag
            random_tag = StringUtils.generate_random_str(10)

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
                                               is_paused=is_paused,  # 调试用
                                               cookie=cookies,
                                               labels=self.__tags + ["AutoSports"] + [random_tag],)

                if not state:
                    return False, None
                else:
                    # 获取种子Hash
                    torrent_hash = downloader.get_torrent_id_by_tag(tags=random_tag)
                    if not torrent_hash:
                        logger.error(f"{self.__downloaders} 获取种子 Hash 失败")
                        return False, None
                    downloader.remove_torrents_tag([torrent_hash], random_tag)
                    if is_paused:
                        logger.info("根据设置，添加下载任务后暂停")
                    else:
                        logger.info("根据设置，添加下载任务后开始")
                    return False, torrent_hash
            return False, None
        return False, None


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


    def __initialize_competition_config(self):
        """
        整合自定义赛事信息和内置赛事信息
        @return:
        """
        # 重置赛事元数据信息
        self.__competitions_parses = get_raw_competitions_parse()

        # 自定义赛事信息中去掉以//开始的行
        selfdefined_competitions_config = re.sub(r'//.*?\n', '', self.__competitions_config).strip()
        selfdefined_competitions_config = json.loads(selfdefined_competitions_config)
        for selfdefined_config in selfdefined_competitions_config:
            if not selfdefined_config:
                # 自定义配置为空，跳过
                continue
            if selfdefined_config.get("homepage"):
                # 用户自定义了赛事配置
                selfdefined_config["homepage"] = f"https://{selfdefined_config["homepage"]}"
            self.__competitions_parses.append(selfdefined_config)


    @staticmethod
    def __save_nfo(doc, file_path: Path):
        """
        保存NFO
        """
        xml_str = doc.toprettyxml(indent="  ", encoding="utf-8")
        file_path.write_bytes(xml_str)
        logger.debug(f"NFO文件已保存：{file_path}")


    @staticmethod
    def __save_poster(input_path, poster_path, cover_conf):
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

