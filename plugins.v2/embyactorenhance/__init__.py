import re
import time
import pytz
import json
import difflib
from dateutil.parser import isoparse
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler

from app.log import logger
from app.core.cache import Cache
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.plugins import _PluginBase
from app.utils.string import StringUtils
from app.modules.douban import DoubanApi
from app.modules.themoviedb import TmdbApi
from app.schemas import WebhookEventInfo, ServiceInfo
from app.schemas.types import EventType, MediaType
from app.helper.mediaserver import MediaServerHelper


class EmbyActorEnhance(_PluginBase):
    # 插件名称
    plugin_name = "Emby演职人员增强"
    # 插件描述
    plugin_desc = "媒体元数据刷新，演职人员角色中文，导入季演职人员，更新节目系列演职人员为各季合并。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/xiaoQQya/MoviePilot-Plugins/refs/heads/main/icons/actor.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "xiaoQQya"
    # 作者主页
    author_url = "https://github.com/xiaoQQya"
    # 插件配置项ID前缀
    plugin_config_prefix = "embyactorenhance_"
    # 加载顺序
    plugin_order = 100
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _onlyonce = False
    _mediaservers = None
    _num = None
    _cron = None

    _scheduler = None
    _tmdbapi = TmdbApi()
    _doubanapi = DoubanApi()
    _cache = Cache("ttl", 2000, 7 * 24 * 60 * 60)

    def init_plugin(self, config: Optional[dict] = None):
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._mediaservers = config.get("mediaservers") or []
            self._num = config.get("num")
            self._cron = config.get("cron")

        if self._onlyonce:
            logger.info(f"Emby 演职人员增强服务启动，立即运行一次")
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(func=self.run, trigger="date",
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=1),
                                    name="Emby 演职人员增强")
            self._scheduler.start()

            # 取消立即运行一次配置
            self._onlyonce = False
            self.update_config({
                "enabled": self._enabled,
                "onlyonce": False,
                "mediaservers": self._mediaservers,
                "num": self._num,
                "cron": self._cron
            })

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
            return [{
                "id": "EmbyActorEnhance",
                "name": self.plugin_name,
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.run,
                "kwargs": {}
            }]
        return []

    @eventmanager.register(EventType.WebhookMessage)
    def hook(self, event: Event):
        """
        监听媒体入库事件
        """
        if not self._enabled:
            return

        event_info: WebhookEventInfo = event.event_data
        if not event_info:
            return
        
        if "emby" != event_info.channel:
            return
        
        if "library.new" != event_info.event:
            return
        
        mediaserver: ServiceInfo = self.service_infos.get(event_info.server_name)
        if not mediaserver:
            return
        
        media = event_info.json_object["Item"]
        self._handle_media(mediaserver, media)

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._mediaservers:
            logger.warning("尚未配置媒体服务器，请检查配置")
            return {}

        services = MediaServerHelper().get_services(name_filters=self._mediaservers)
        if not services:
            logger.warning("获取媒体服务器实例失败，请检查配置")
            return {}

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"媒体服务器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的媒体服务器，请检查配置")
            return {}

        return active_services

    def run(self) -> None:
        if not self.service_infos:
            return

        for name, service in self.service_infos.items():
            logger.info(f"开始获取媒体服务器 {name} 最近 {self._num} 天的媒体数据")
            medias = self._get_latest_medias(service)
            logger.info(f"获取媒体服务器 {name} 最近 {self._num} 天的媒体数据共 {len(medias)} 条")

            for media in medias:
                self._handle_media(service, media)
            
            logger.info(f"媒体服务器 {name} 演职人员增强完成")

    def _handle_media(self, mediaserver: ServiceInfo, media: dict):
        media_type = MediaType("电视剧" if media.get("Type") == "Episode" else "电影")
        series_id = media["SeriesId"] if media_type == MediaType.TV else media["Id"]
        season_id = media.get("SeasonId", None)
        series_name = media.get("SeriesName") if media_type == MediaType.TV else media.get("Name")
        season_name = media.get("SeasonName", None)
        media_name = f"{series_name}-{season_name}-{media['Name']}" if media_type == MediaType.TV else f"{series_name}"

        # 刷新媒体元信息
        self._auto_refresh_item(mediaserver, media)

        # 处理缓存信息
        key = f"{mediaserver.name}:handled_medias"
        region = "embyactorenhance"
        if self._cache.exists(key, region):
            handled_medias = self._cache.get(key, region)
            if (season_id or series_id) in handled_medias:
                logger.info(f"<{media_name}> 媒体演职人员信息已更新，跳过更新")
                return

        # 获取系列元信息
        series_info = self._get_item_info(mediaserver, series_id)
        if not series_info:
            logger.warning(f"<{series_name}> 获取系列元信息失败，请检查配置")
            return

        # 获取季元信息
        season_info = None
        if media_type == MediaType.TV and season_id:
            season_info = self._get_item_info(mediaserver, season_id)
            if not season_info:
                logger.warning(f"<{series_name}-{season_name}> 获取季元信息失败，请检查配置")
                return

            # 更新季演职人员信息
            season_info = self._update_season_credits(mediaserver, series_info, season_info)
            if not season_info:
                return

        # 演职人员角色信息中文
        series_info, season_info = self._update_chinese_role(mediaserver, media_type, series_info, season_info)
        if not series_info:
            return

        # 更新系列演职人员信息
        if media_type == MediaType.TV and season_info:
            series_info = self._update_tv_credits(mediaserver, series_info, season_info)

        # 缓存处理信息
        if self._cache.exists(key, region):
            handled_medias = self._cache.get(key, region)
            handled_medias.append(season_id or series_id)
            self._cache.set(key, handled_medias, None, region)
        else:
            self._cache.set(key, [season_id or series_id], None, region)

        time.sleep(3)

    def _get_latest_medias(self, mediaserver: ServiceInfo):
        """
        获取最新媒体数据
        """
        url = "[HOST]emby/Users/[USER]/Items?Limit=1000&api_key=[APIKEY]&SortBy=DateCreated,SortName&SortOrder=Descending&IncludeItemTypes=Episode,Movie&Recursive=true&Fields=DateCreated,Overview,PrimaryImageAspectRatio,ProductionYear"
        res = mediaserver.instance.get_data(url=url)
        if res and res.status_code == 200:
            items = res.json().get("Items", [])
            medias = []
            update_date = datetime.now(tz=pytz.utc) - timedelta(days=int(self._num))
            for item in items:
                item_date = item.get("DateCreated")
                item_date = isoparse(item_date)
                if item_date > update_date:
                    medias.append(item)
                else:
                    break
            return medias
        return []

    def _get_item_info(self, mediaserver: ServiceInfo, item_id: int):
        """
        获取单个项目详情
        """
        url = f"[HOST]emby/Users/[USER]/Items/{item_id}?X-Emby-Token=[APIKEY]&Fields=ChannelMappingInfo&ExcludeFields=Chapters,MediaSources,MediaStreams,Subviews"
        res = mediaserver.instance.get_data(url=url)
        if res and res.status_code == 200:
            return res.json()
        return None

    def _auto_refresh_item(self, mediaserver: ServiceInfo, media: dict):
        """
        自动刷新单个项目信息
        """
        item_id = media["Id"]
        type = MediaType("电视剧" if media.get("Type") == "Episode" else "电影")
        series_name = media.get("SeriesName") if type == MediaType.TV else media.get("Name")
        season_name = media.get("SeasonName", None)
        episode_name = media["Name"]
        media_name = f"{series_name}-{season_name}-{episode_name}" if type == MediaType.TV else f"{series_name}-{episode_name}"
        overview = media.get("Overview")
        image = media.get("ImageTags", {}).get("Primary")

        pattern = re.compile(r'第\s*([0-9]|[十|一|二|三|四|五|六|七|八|九|零])+\s*集')
        refresh_meta = bool(pattern.search(episode_name)) or not overview
        refresh_image = not image

        if refresh_meta or refresh_image:
            if self._refresh_item_info(mediaserver, item_id, refresh_meta, refresh_image):
                logger.info(f"<{media_name}> 媒体元信息刷新成功")
            else:
                logger.warning(f"<{media_name}> 媒体元信息刷新失败，请检查配置")
        else:
            logger.info(f"<{media_name}> 媒体元信息无需刷新")

    def _refresh_item_info(self, mediaserver: ServiceInfo, item_id: int, refresh_meta: bool = True, refresh_image: bool = True):
        """
        刷新单个项目信息
        """
        url = f"[HOST]emby/Items/{item_id}/Refresh?Recursive=true&MetadataRefreshMode=FullRefresh&ImageRefreshMode=FullRefresh&ReplaceAllMetadata={refresh_meta}&ReplaceAllImages={refresh_image}&ReplaceThumbnailImages=false&api_key=[APIKEY]"
        res = mediaserver.instance.post_data(url=url)
        if res and res.status_code in [200, 204]:
            return True
        return False

    def _update_season_credits(self, mediaserver: ServiceInfo, series_info: dict, season_info: dict):
        """
        更新季演职人员
        """
        item_id = season_info["Id"]
        series_name = series_info["Name"]
        season_name = season_info["Name"]
        media_name = f"{series_name}-{season_name}"
        if len(season_info["People"]) > 0:
            logger.info(f"<{media_name}> 季演职人员已存在，跳过更新演职人员")
            return season_info

        tmdb_id = series_info.get("ProviderIds", {}).get("Tmdb")
        season = season_info.get("IndexNumber")
        if not tmdb_id:
            logger.warning(f"<{media_name}> 媒体未获取到 TMDB ID，跳过更新演职人员")
            return None
        credits = self._tmdbapi.season_obj.credits(tv_id=tmdb_id, season_num=season)
        if not credits or len(credits.get("cast", [])) == 0:
            logger.warning(f"<{media_name}> 媒体未找到季演职人员信息，跳过更新演职人员")
            return None

        peoples = []
        for cast in credits.get("cast", []):
            people = {"Name": cast.get("name"), "Role": cast.get("character")}
            if cast.get("known_for_department") == "Acting":
                people["Type"] = "Actor"
            elif cast.get("known_for_department") == "Directing":
                people["Type"] = "Director"
            elif cast.get("known_for_department") == "Writing":
                people["Type"] = "Writer"
            else:
                continue
            peoples.append(people)
        season_info["People"] = peoples
        if "Cast" not in season_info["LockedFields"]:
            season_info["LockedFields"].append("Cast")

        if self._update_item_info(mediaserver, item_id, season_info):
            logger.info(f"<{media_name}> 季演职人员信息更新成功")
        else:
            logger.warning(f"<{media_name}> 季演职人员信息更新失败")
            return None

        # 刮削演职人员信息
        casts = {cast.get("name"): cast.get("id") for cast in credits.get("cast", [])}
        updated_season_info = self._get_item_info(mediaserver, item_id)
        if not updated_season_info:
            logger.warning(f"<{media_name}> 季演职人员信息刷新失败")
            return None
        peoples = updated_season_info.get("People", [])
        for people in peoples:
            people_id = people.get("Id", None)
            people_name = people.get("Name", None)
            people_info = self._get_item_info(mediaserver, people_id)
            if not people_info:
                logger.warning(f"<{media_name}> 季演职人员 {people_name} 信息刷新失败")
                continue

            people_tmdb_id = people_info.get("ProviderIds", {}).get("Tmdb")
            people_overview = people_info.get("Overview")
            people_image = people_info.get("ImageTags", {}).get("Primary")
            if not people_overview or not people_image:
                if not people_tmdb_id:
                    people_info["ProviderIds"]["Tmdb"] = casts.get(people_name)
                    self._update_item_info(mediaserver, people_id, people_info)
                if self._refresh_item_info(mediaserver, people_id, not people_overview, not people_image):
                    logger.info(f"<{media_name}> 季演职人员 <{people_name}> 信息刷新成功")
                else:
                    logger.warning(f"<{media_name}> 季演职人员 <{people_name}> 信息刷新失败")

        return updated_season_info

    def _update_tv_credits(self, mediaserver: ServiceInfo, series_info: dict, season_info: dict):
        """
        更新系列演职人员
        """
        item_id = series_info["Id"]
        series_name = series_info["Name"]

        series_peoples = {people["Name"]: people for people in series_info["People"]}
        season_peoples = {people["Name"]: people for people in season_info["People"]}
        updated_series_peoples = []
        for series_people in series_peoples.values():
            if not StringUtils.is_chinese(series_people.get("Role")):
                series_people["Role"] = season_peoples.get(
                    series_people["Name"], {}).get("Role", series_people.get("Role"))
            updated_series_peoples.append(series_people)
        for season_people in season_peoples.values():
            if season_people["Name"] not in series_peoples:
                updated_series_peoples.append(season_people)

        series_info["People"] = updated_series_peoples
        if "Cast" not in series_info["LockedFields"]:
            series_info["LockedFields"].append("Cast")
        if self._update_item_info(mediaserver, item_id, series_info):
            logger.info(f"<{series_name}> 系列演职人员信息更新成功")
            return series_info
        else:
            logger.warning(f"<{series_name}> 系列演职人员信息更新失败")
            return None

    def _update_item_info(self, mediaserver: ServiceInfo, item_id: int, item_info: dict):
        """
        更新媒体信息
        """
        url = f"[HOST]emby/Items/{item_id}?reqformat=json&api_key=[APIKEY]"
        headers = {"Content-Type": "application/json"}
        res = mediaserver.instance.post_data(url=url, data=json.dumps(item_info), headers=headers)
        if res and res.status_code in [200, 204]:
            return True
        return False

    def _update_chinese_role(self, mediaserver: ServiceInfo, media_type: MediaType, series_info: dict, season_info: Optional[dict]):
        """
        更新演职人员角色中文
        """
        if media_type == MediaType.TV and season_info:
            peoples = season_info["People"]
            media_name = f"{series_info['Name']}-{season_info['Name']}"
        else:
            peoples = series_info["People"]
            media_name = series_info["Name"]

        if all(StringUtils.is_chinese(people.get("Role")) for people in peoples):
            logger.info(f"<{media_name}> 媒体演职人员角色已全为中文，跳过更新")
            return series_info, season_info

        douban_info = self._get_douban_info(media_type, series_info, season_info)
        if not douban_info:
            logger.warning(f"<{media_name}> 获取豆瓣媒体信息失败，请检查配置")
            return None, None
        douban_peoples = {}
        for people in (douban_info.get("actors", [])):
            character = people["character"]
            character = re.sub(r"饰\s+", "", character)
            character = re.sub(r"饰演\s+", "", character)
            character = re.sub(r"配\s+", "（配音）", character)
            character = re.sub(r"演员", "", character)
            character = re.sub(r"自己", "", character)
            character = re.sub(r"voice", "（配音）", character)
            character = re.sub(r"Director", "（导演）", character)
            douban_peoples[people["name"]] = character
        for people in peoples:
            if not StringUtils.is_chinese(people.get("Role")):
                if people["Name"] in douban_peoples:
                    people["Role"] = douban_peoples[people["Name"]]
                else:
                    people_info = self._get_item_info(mediaserver, people["Id"])
                    if people_info and people_info.get("ProviderIds", {}).get("Tmdb"):
                        people_tmdb_info = self._tmdbapi.get_person_detail(
                            people_info.get("ProviderIds", {}).get("Tmdb"))
                        also_known_as = people_tmdb_info.get("also_known_as", [])
                        for name in also_known_as:
                            if name in douban_peoples:
                                people["Role"] = douban_peoples[name]
                                break
                    else:
                        logger.warning(f"<{people["Name"]}> 获取人员信息失败，请检查配置")

        if media_type == MediaType.TV and season_info:
            if "Cast" not in season_info["LockedFields"]:
                season_info["LockedFields"].append("Cast")
            updated = self._update_item_info(mediaserver, season_info["Id"], season_info)
        else:
            if "Cast" not in series_info["LockedFields"]:
                series_info["LockedFields"].append("Cast")
            updated = self._update_item_info(mediaserver, series_info["Id"], series_info)
        if updated:
            logger.info(f"<{media_name}> 媒体演职人员角色中文更新成功")
            return series_info, season_info
        else:
            logger.warning(f"<{media_name}> 媒体演职人员角色中文更新失败")
            return None, None

    def _get_douban_info(self, media_type: MediaType, series_info: dict, season_info: Optional[dict]):
        """
        匹配豆瓣媒体信息
        """
        series_name = series_info["Name"]
        season_name = season_info["Name"] if season_info else ""
        year = season_info["PremiereDate"][:4] if season_info else series_info["PremiereDate"][:4]
        result = self._doubanapi.search(series_name)
        if not result or not result.get("items"):
            return None

        douban_id = None
        for item in result["items"]:
            if item.get("type_name") != media_type.value:
                continue
            target = item["target"]
            if target.get("year") != str(year):
                continue

            item_name = target["title"]
            score_series = self.sequence_matcher(item_name, series_name)
            score_season = self.sequence_matcher(item_name, season_name)
            score_all = self.sequence_matcher(item_name, series_name + season_name)
            score = max(score_series, score_season, score_all)
            if score < 0.8:
                continue

            douban_id = target["id"]
            break

        if not douban_id:
            return None

        douban_info = self.chain.douban_info(douban_id, media_type)
        if not douban_info:
            return None
        return douban_info

    @staticmethod
    def sequence_matcher(s1: str, s2: str) -> float:
        def normalize(text):
            if text is None:
                return ""

            text = text.lower()
            text = text.replace(" ", "")

            zh_num_map = {
                "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10
            }
            for k, v in zh_num_map.items():
                text = text.replace(k, str(v))
            return text

        return difflib.SequenceMatcher(None, normalize(s1), normalize(s2)).ratio()

    def get_state(self) -> bool:
        return self._enabled

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "auth: "apikey",  # 鉴权类型：apikey/bear
            "summary": "API名称",
            "description": "API说明"
        }]
        """
        pass

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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'mediaservers',
                                            'label': '媒体服务器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in MediaServerHelper().get_configs().values()
                                                      if config.type == "emby"]
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
                                            'model': 'num',
                                            'label': '最新入库天数',
                                            'placeholder': '更新多少天之内的入库记录（天）'
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
                                            'placeholder': '0 1 * * *'
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
                                            'text': '支持媒体服务器 Webhook 实时更新演职人员信息，需要设置媒体服务器 Webhook 地址为 http://HOST:PORT/api/v1/webhook?token=API_TOKEN&source=SERVER_NAME，其中 HOST 为 MoviePilot 服务地址，PORT 为 MoviePilot 服务端口（默认 3001），API_TOKEN 为 MoviePilot API Token，SERVER_NAME 为发送 Webhook 的媒体服务器在 MoviePilot 中的名称。'
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
            "onlyonce": False,
            "mediaservers": [],
            "num": 3,
            "cron": "0 1 * * *"
        }

    def get_page(self) -> Optional[List[dict]]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        插件详情页面使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        :return: 页面配置（vuetify模式）或 None（vue模式）
        """
        pass

    def stop_service(self):
        """
        退出插件
        """
        if self._scheduler:
            self._scheduler.shutdown()
