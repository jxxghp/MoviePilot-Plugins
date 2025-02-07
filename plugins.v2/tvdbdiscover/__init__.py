from typing import Any, List, Dict, Tuple, Optional

from cachetools import cached, TTLCache

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import DiscoverSourceEventData
from app.schemas.types import ChainEventType
from app.utils.http import RequestUtils


class TvdbDiscover(_PluginBase):
    # 插件名称
    plugin_name = "TheTVDB探索"
    # 插件描述
    plugin_desc = "让探索支持TheTVDB的数据浏览。"
    # 插件图标
    plugin_icon = "TheTVDB_A.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "tvdbdiscover_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _base_api = "https://api4.thetvdb.com/v4"
    _enabled = False
    _proxy = False
    _api_key = None

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._api_key = config.get("api_key")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
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
        return [{
            "path": "/tvdb_discover",
            "endpoint": self.tvdb_discover,
            "methods": ["GET"],
            "summary": "TheTVDB探索数据源",
            "description": "获取TheTVDB探索数据",
        }]

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
                                            'model': 'proxy',
                                            'label': '使用代理服务器',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'api_key',
                                            'label': 'API Key'
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
            "proxy": False,
            "api_key": "ed2aa66b-7899-4677-92a7-67bc9ce3d93a"
        }

    def get_page(self) -> List[dict]:
        pass

    @cached(cache=TTLCache(maxsize=1, ttl=30 * 24 * 3600))
    def __get_token(self) -> Optional[str]:
        """
        根据APIKEY获取token使用
        """
        api_url = f"{self._base_api}/login"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        data = {
            "apikey": self._api_key
        }
        res = RequestUtils(headers=headers).post_res(
            api_url,
            json=data,
            proxies=settings.PROXY if self._proxy else None
        )
        if not res:
            logger.error("获取TheMovieDB token失败")
            return None
        return res.json().get("data", {}).get("token")

    @cached(cache=TTLCache(maxsize=32, ttl=1800))
    def __request(self, mtype: str, **kwargs):
        """
        请求TheTVDB API
        """
        api_url = f"{self._base_api}/{mtype}/filter"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.__get_token()}"
        }
        res = RequestUtils(headers=headers).get_res(
            api_url,
            params=kwargs,
            proxies=settings.PROXY if self._proxy else None
        )
        if res is None:
            raise Exception("无法连接TheTVDB，请检查网络连接！")
        if not res.ok:
            raise Exception(f"请求TheTVDB API失败：{res.text}")
        return res.json().get("data")

    def tvdb_discover(self, apikey: str, mtype: str = "series",
                      company: int = None, contentRating: int = None, country: str = "usa",
                      genre: int = None, lang: str = "eng", sort: str = "score", sortType: str = "desc",
                      status: int = None, year: int = None,
                      page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
        """
        获取TheTVDB探索数据
        """

        def __movie_to_media(movie_info: dict) -> schemas.MediaInfo:
            """
            电影数据转换为MediaInfo
            {
              "id": 353554,
              "name": "I Am: Celine Dion",
              "slug": "i-am-celine-dion",
              "image": "/banners/v4/movie/353554/posters/6656173b5167f.jpg",
              "nameTranslations": null,
              "overviewTranslations": null,
              "aliases": null,
              "score": 22669,
              "runtime": 102,
              "status": {
                "id": 5,
                "name": "Released",
                "recordType": "movie",
                "keepUpdated": true
              },
              "lastUpdated": "2024-08-10 10:37:05",
              "year": "2024"
            }
            """
            return schemas.MediaInfo(
                type="电影",
                title=movie_info.get("name"),
                year=movie_info.get("year"),
                title_year=f"{movie_info.get('name')} ({movie_info.get('year')})",
                mediaid_prefix="tvdb",
                media_id=str(movie_info.get("id")),
                poster_path=f"https://www.thetvdb.com{movie_info.get('image')}",
                vote_average=movie_info.get("score"),
                runtime=movie_info.get("runtime"),
                overview=movie_info.get("overview")
            )

        def __series_to_media(series_info: dict) -> schemas.MediaInfo:
            """
            电视剧数据转换为MediaInfo
            {
              "id": 79399,
              "name": "Who Wants to Be a Superhero?",
              "slug": "who-wants-to-be-a-superhero",
              "image": "https://artworks.thetvdb.com/banners/posters/79399-1.jpg",
              "nameTranslations": null,
              "overviewTranslations": null,
              "aliases": null,
              "firstAired": "2006-07-27",
              "lastAired": "2007-09-06",
              "nextAired": "",
              "score": 190,
              "status": {
                "id": 2,
                "name": "Ended",
                "recordType": "series",
                "keepUpdated": false
              },
              "originalCountry": "usa",
              "originalLanguage": "eng",
              "defaultSeasonType": 1,
              "isOrderRandomized": false,
              "lastUpdated": "2022-01-16 03:32:39",
              "averageRuntime": 45,
              "episodes": null,
              "overview": "",
              "year": "2006"
            }
            """
            return schemas.MediaInfo(
                type="电视剧",
                title=series_info.get("name"),
                year=series_info.get("year"),
                title_year=f"{series_info.get('name')} ({series_info.get('year')})",
                mediaid_prefix="tvdb",
                media_id=str(series_info.get("id")),
                release_date=series_info.get("firstAired"),
                poster_path=series_info.get("image"),
                vote_average=series_info.get("score"),
                runtime=series_info.get("averageRuntime"),
                overview=series_info.get("overview")
            )

        if apikey != settings.API_TOKEN:
            return []
        try:
            # 计算页码，TVDB为固定每页500条
            if page * count > 500:
                req_page = 500 // count
            else:
                req_page = page - 1
            result = self.__request(
                mtype,
                company=company,
                contentRating=contentRating,
                country=country,
                genre=genre,
                lang=lang,
                sort=sort,
                sortType=sortType,
                status=status,
                year=year,
                page=req_page
            )
        except Exception as err:
            logger.error(str(err))
            return []
        if not result:
            return []
        if mtype == "movies":
            results = [__movie_to_media(movie) for movie in result]
        else:
            results = [__series_to_media(series) for series in result]
        return results[(page - 1) * count:page * count]

    @staticmethod
    def tvdb_filter_ui() -> List[dict]:
        """
        TheTVDB过滤参数UI配置
        """
        # 国家字典
        country_dict = {
            "usa": "美国",
            "chn": "中国",
            "jpn": "日本",
            "kor": "韩国",
            "ind": "印度",
            "fra": "法国",
            "ger": "德国",
            "ita": "意大利",
            "esp": "西班牙",
            "uk": "英国",
            "aus": "澳大利亚",
            "can": "加拿大",
            "rus": "俄罗斯",
            "bra": "巴西",
            "mex": "墨西哥",
            "arg": "阿根廷",
            "other": "其他"
        }

        cuntry_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in country_dict.items()
        ]

        # 原始语种字典
        lang_dict = {
            "eng": "英语",
            "chi": "中文",
            "jpn": "日语",
            "kor": "韩语",
            "hin": "印地语",
            "fra": "法语",
            "deu": "德语",
            "ita": "意大利语",
            "spa": "西班牙语",
            "por": "葡萄牙语",
            "rus": "俄语",
            "other": "其他"
        }

        lang_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in lang_dict.items()
        ]

        # 风格字典
        genre_dict = {
            "1": "Soap",
            "2": "Science Fiction",
            "3": "Reality",
            "4": "News",
            "5": "Mini-Series",
            "6": "Horror",
            "7": "Home and Garden",
            "8": "Game Show",
            "9": "Food",
            "10": "Fantasy",
            "11": "Family",
            "12": "Drama",
            "13": "Documentary",
            "14": "Crime",
            "15": "Comedy",
            "16": "Children",
            "17": "Animation",
            "18": "Adventure",
            "19": "Action",
            "21": "Sport",
            "22": "Suspense",
            "23": "Talk Show",
            "24": "Thriller",
            "25": "Travel",
            "26": "Western",
            "27": "Anime",
            "28": "Romance",
            "29": "Musical",
            "30": "Podcast",
            "31": "Mystery",
            "32": "Indie",
            "33": "History",
            "34": "War",
            "35": "Martial Arts",
            "36": "Awards Show"
        }

        genre_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in genre_dict.items()
        ]

        # 排序字典
        sort_dict = {
            "score": "评分",
            "firstAired": "首播日期",
            "name": "名称"
        }

        sort_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in sort_dict.items()
        ]

        return [
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center"
                },
                "content": [
                    {
                        "component": "div",
                        "props": {
                            "class": "mr-5"
                        },
                        "content": [
                            {
                                "component": "VLabel",
                                "text": "类型"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "mtype"
                        },
                        "content": [
                            {
                                "component": "VChip",
                                "props": {
                                    "filter": True,
                                    "tile": True,
                                    "value": "movies"
                                },
                                "text": "电影"
                            },
                            {
                                "component": "VChip",
                                "props": {
                                    "filter": True,
                                    "tile": True,
                                    "value": "series"
                                },
                                "text": "电视剧"
                            }
                        ]
                    }
                ]
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center"
                },
                "content": [
                    {
                        "component": "div",
                        "props": {
                            "class": "mr-5"
                        },
                        "content": [
                            {
                                "component": "VLabel",
                                "text": "风格"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "genre"
                        },
                        "content": genre_ui
                    }
                ]
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center"
                },
                "content": [
                    {
                        "component": "div",
                        "props": {
                            "class": "mr-5"
                        },
                        "content": [
                            {
                                "component": "VLabel",
                                "text": "国家"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "country"
                        },
                        "content": cuntry_ui
                    }
                ]
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center"
                },
                "content": [
                    {
                        "component": "div",
                        "props": {
                            "class": "mr-5"
                        },
                        "content": [
                            {
                                "component": "VLabel",
                                "text": "语言"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "lang"
                        },
                        "content": lang_ui
                    }
                ]
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center"
                },
                "content": [
                    {
                        "component": "div",
                        "props": {
                            "class": "mr-5"
                        },
                        "content": [
                            {
                                "component": "VLabel",
                                "text": "排序"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "sort"
                        },
                        "content": sort_ui
                    }
                ]
            }
        ]

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        """
        监听识别事件，使用ChatGPT辅助识别名称
        """
        if not self._enabled or not self._api_key:
            return
        event_data: DiscoverSourceEventData = event.event_data
        tvdb_source = schemas.DiscoverMediaSource(
            name="TheTVDB",
            mediaid_prefix="tvdb",
            api_path=f"plugin/TvdbDiscover/tvdb_discover?apikey={settings.API_TOKEN}",
            filter_params={
                "mtype": "series",
                "company": None,
                "contentRating": None,
                "country": "usa",
                "genre": None,
                "lang": "eng",
                "sort": "score",
                "sortType": "desc",
                "status": None,
                "year": None,
            },
            filter_ui=self.tvdb_filter_ui()
        )
        if not event_data.extra_sources:
            event_data.extra_sources = [tvdb_source]
        else:
            event_data.extra_sources.append(tvdb_source)

    def stop_service(self):
        """
        退出插件
        """
        pass
