from typing import Optional, Any, List, Dict, Tuple
from datetime import datetime
import re

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.plugins import _PluginBase
from app.schemas import DiscoverSourceEventData, MediaRecognizeConvertEventData, RecommendSourceEventData
from app.schemas.types import ChainEventType, MediaType
from app.plugins.imdbsource.imdbhelper import ImdbHelper
from app import schemas
from app.utils.http import RequestUtils


class ImdbSource(_PluginBase):
    # 插件名称
    plugin_name = "IMDb源"
    # 插件描述
    plugin_desc = "让探索和推荐支持IMDb数据源。"
    # 插件图标
    plugin_icon = "IMDb_IOS-OSX_App.png"
    # 插件版本
    plugin_version = "1.4.2"
    # 插件作者
    plugin_author = "wumode"
    # 作者主页
    author_url = "https://github.com/wumode"
    # 插件配置项ID前缀
    plugin_config_prefix = "imdbsource_"
    # 加载顺序
    plugin_order = 22
    # 可使用的用户级别
    auth_level = 1

    # 插件配置
    _enabled: bool = False
    _proxy: bool = False
    _staff_picks: bool = False
    _component_size: str = 'medium'

    # 私有属性
    _imdb_helper = None
    _cache = {"discover": [], "trending": [], "trending_in_anime": [], "trending_in_sitcom": [],
              "trending_in_documentary": [], "imdb_top_250": []}

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._staff_picks = config.get("staff_picks")
            self._component_size = config.get("component_size", "medium")
            self._imdb_helper = ImdbHelper()
            self._imdb_helper = ImdbHelper(proxies=settings.PROXY if self._proxy else None)
        if "media-amazon.com" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("media-amazon.com")
        if "media-imdb.com" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("media-imdb.com")

    def get_state(self) -> bool:
        return self._enabled

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        if not self._staff_picks:
            return []
        return [
            {
                "key": "Staff Picks",
                "name": "IMDb 编辑精选"
            },
        ]

    def get_dashboard(self, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、全局配置参考：
        {
            "refresh": 10 // 自动刷新时间，单位秒
        }
        3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        """
        if not self._staff_picks:
            return None

        def year_and_type(entry: Dict) -> Tuple[MediaType, str, str]:
            title = next((t for t in titles if t.get("id") == entry.get('ttconst')), None)
            if not title:
                return MediaType.MOVIE, datetime.now().date().strftime("%Y"), ''
            media_id = title.get('titleType', {}).get('id')
            release_year = title.get('releaseYear', {}).get('year') or datetime.now().date().strftime("%Y")
            media_type = ImdbSource.title_id_to_mtype(media_id)
            plot = title.get("plot", {}).get("plotText", {}).get("plainText", '')
            return media_type, release_year, plot

        # 列配置
        size_config = {
            "small": {"cols": {"cols": 12, "md": 4}, "height": 335},
            "medium": {"cols": {"cols": 12, "md": 8}, "height": 335},
        }
        config = size_config.get(self._component_size, 'medium')

        cols = config["cols"]
        height = config["height"]
        is_mobile = ImdbSource.is_mobile(kwargs.get('user_agent'))
        if is_mobile:
            height *= 2
        # 全局配置
        attrs = {
            "border": False
        }
        # 获取流行越势数据
        entries = self._imdb_helper.staff_picks()
        items = None
        if entries:
            items = self._imdb_helper.vertical_list_page_items(
                titles=[entry.get('ttconst', '') for entry in entries],
                names=[item for entry in entries for item in entry.get("relatedconst", [])],
                images=[entry.get('rmconst', '') for entry in entries],
            )

        if not entries or not items:
            elements = [
                {
                    'component': 'VCard',
                    'content': [
                        {
                            'component': 'VCardText',
                            'props': {
                                'class': 'text-center',
                            },
                            'content': [
                                {
                                    'component': 'span',
                                    'props': {
                                        'class': 'text-h6'
                                    },
                                    'text': '无数据'
                                }
                            ]
                        }
                    ]
                }
            ]
            return cols, attrs, elements
        images = items.get('images') or []
        names = items.get('names') or []
        titles = items.get('titles') or []
        contents = []
        for entry in entries:
            cast = [name for related in entry.get('relatedconst', []) for name in names if name.get('id') == related]
            mtype, year, plot = year_and_type(entry)
            mp_url = f"/media?mediaid=imdb:{entry.get('ttconst')}&title='{entry.get('name')}'&year={year}&type={mtype.value}"
            item1 = {
                'component': 'VCarouselItem',
                'props': {
                    'src': next((f"{image.get('url')}" for image in images
                                 if image.get("id") == entry.get('rmconst')), None),
                    'cover': True,
                    'position': 'center',
                },
                'content': [
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'w-full flex flex-col flex-wrap justify-end align-left text-white absolute bottom-0 pa-4',
                        },
                        'content': [
                            {
                                'component': 'RouterLink',
                                'props': {
                                    'to': mp_url,
                                    'class': 'no-underline'
                                },
                                'content': [{
                                    'component': 'h1',
                                    'props': {
                                        'class': 'mb-1 text-white text-shadow font-extrabold text-2xl line-clamp-2 overflow-hidden text-ellipsis ...'
                                    },
                                    'html': f"{entry.get('name', '')} <span class='text-base font-normal'>{year_and_type(entry)[1]}</span>",
                                },
                                    {
                                        'component': 'span',
                                        'props': {
                                            'class': 'text-shadow line-clamp-2 overflow-hidden text-ellipsis ...'
                                        },
                                        'html': plot,
                                    }
                                ]
                            },
                        ]
                    }
                ]
            }
            cast_ui = {
                'component': 'div',
                'props': {
                    'class': 'd-flex flex-row align-center mt-4 gap-4',
                    'style': 'overflow: hidden; white-space: nowrap; max-width: 100%;',
                },
                'content':
                    [
                        {
                            'component': 'div',
                            'props': {'class': 'd-flex flex-column align-center'},
                            'content': [
                                {
                                    'component': 'a',
                                    'props': {
                                        'href': f"https://www.imdb.com/name/{cs.get('id', '')}",
                                        'target': '_blank',
                                        'rel': 'noopener noreferrer',
                                        'class': 'text-h4 font-weight-bold mb-2 d-flex align-center',
                                    },
                                    'content': [
                                        {
                                            'component': 'VAvatar',
                                            'props': {
                                                'size': f'{48 if is_mobile else 64}',
                                                'class': 'mb-1'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VImg',
                                                    'props': {
                                                        'src': cs.get('primaryImage', {}).get('url',
                                                                                              ''),
                                                        'alt': cs.get('nameText', {}).get('text', 'Avatar'),
                                                        'cover': True
                                                    }
                                                }
                                            ]
                                        },
                                    ]
                                },

                                {
                                    'component': 'span',
                                    'props': {
                                        'class': 'text-caption text-center d-inline-block text-truncate',
                                        'style': 'max-width: 72px;'
                                    },
                                    'html': cs.get('nameText', {}).get('text', ''),
                                }
                            ]
                        } for cs in cast
                    ]

            }
            poster_com = {
                'component': 'VImg',
                'props': {
                    'src': next(
                        (f"{title.get('primaryImage', {}).get('url')}" for title in titles if
                         title.get("id") == entry.get('ttconst')), None),
                    'class': 'rounded-lg  aspect-[9/16]',
                    'contain': True,
                    'max-height': '250px',
                }
            }
            poster_ui = {
                'component': 'div',
                'props': {
                    'class': 'align-center mt-2',
                },
                'content': [
                    {
                        'component': 'a',
                        'props': {
                            'href': f"#{mp_url}",
                            'class': 'no-underline d-flex w-100 h-100',
                        },
                        'content': [
                            poster_com
                        ]
                    }
                ]
            }
            title_ui = {
                'component': 'div',
                'props': {
                    'class': 'd-flex flex-column justify-end',
                    'style': 'max-width: 100%; overflow: hidden;'
                },
                'content': [
                    {
                        'component': 'a',
                        'props': {
                            'href': f"https://www.imdb.com/title/{entry.get('ttconst', '')}",
                            'target': '_blank',
                            'rel': 'noopener noreferrer',
                            'class': 'text-h4 font-weight-bold mb-2 d-flex text-white align-center',
                        },
                        'content': [
                            {
                                'component': 'span',
                                'html': f"{entry.get('name', '')}"
                            },
                            {
                                'component': 'v-icon',
                                'props': {
                                    'class': 'ml-2',
                                    'size': 'small'
                                },
                                'text': 'mdi-chevron-right'
                            }
                        ]
                    },
                    {
                        'component': 'div',
                        'props': {
                            'class': 'text-yellow font-weight-bold mb-2',
                        },
                        'html': entry.get('detail', '')
                    },
                    {
                        'component': 'span',
                        'props': {
                            'class': 'text-body-2 line-clamp-4 overflow-hidden',
                            'style': 'text-align: justify; hyphens: auto; color: rgba(231, 227, 252, 0.7);'
                        },
                        'html': entry.get('description', '')
                    },
                ]
            }
            if cast:
                title_ui['content'].append(cast_ui)
            item2 = {
                'component': 'VCarouselItem',
                'props': {
                    'src': next((f"{image.get('url')}" for image in images
                                 if image.get("id") == entry.get('rmconst')), None),
                    'cover': True,
                    'position': 'center'
                },
                'content': [
                    {
                        'component': 'div',
                        'props': {
                            'class': 'absolute top-0 left-0 right-0 bottom-0 bg-black opacity-70',
                            'style': 'z-index: 1;'
                        }
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'd-flex flex-row absolute pa-4 text-white',
                            'style': 'z-index: 2; bottom: 0; max-width: 100%;',
                        },
                        'content': [
                            {
                                'component': 'VRow',
                                'props': {
                                    'class': 'w-100'
                                },
                                'content': [
                                    # 左图：海报
                                    {
                                        'component': 'VCol',
                                        'props': {
                                            'cols': 12,
                                            'md': 3,
                                        },
                                        'content': [
                                            poster_ui
                                        ]
                                    },
                                    # 右侧内容区域
                                    {
                                        'component': 'VCol',
                                        'props': {
                                            'cols': 12,
                                            'md': 9,
                                            'class': 'd-flex',
                                        },
                                        'content': [
                                            title_ui
                                        ]
                                    }
                                ]
                            },
                        ]
                    }
                ]
            }

            contents.append(item1)
            contents.append(item2)
        elements = [
            {
                'component': 'VCard',
                'props': {
                    'class': 'p-0'
                },
                'content': [
                    {
                        'component': 'VCarousel',
                        'props': {
                            'continuous': True,
                            'show-arrows': 'hover',
                            'hide-delimiters': True,
                            'cycle': True,
                            'interval': 10000,
                            'height': height
                        },
                        'content': contents
                    }
                ]
            }]

        return cols, attrs, elements

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
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
                                            'model': 'staff_picks',
                                            'label': 'IMDb 编辑精选组件',
                                        }
                                    }
                                ]
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'component_size',
                                            'label': '组件规格',
                                            'items': [
                                                {"title": "小型", "value": "small"},
                                                {"title": "中型", "value": "medium"},
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
        ], {
            "enabled": False,
            "proxy": False,
            "staff_picks": False,
            "component_size": "medium"
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    def get_module(self) -> Dict[str, Any]:
        """
        获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）
        {
            "id1": self.xxx1,
            "id2": self.xxx2,
        }
        """
        pass

    @staticmethod
    def __movie_to_media(movie_info: dict) -> schemas.MediaInfo:
        title = ""
        if movie_info.get("titleText"):
            title = movie_info.get("titleText", {}).get("text", "")
        release_year = 0
        if movie_info.get("releaseYear"):
            release_year = movie_info.get("releaseYear", {}).get("year")
        poster_path = None
        if movie_info.get("primaryImage"):
            primary_image = movie_info.get("primaryImage").get("url")
            if primary_image:
                poster_path = primary_image.replace('@._V1', '@._V1_QL75_UY414_CR6,0,280,414_')
        vote_average = 0
        if movie_info.get("ratingsSummary"):
            vote_average = movie_info.get("ratingsSummary").get("aggregateRating")
        runtime = 0
        if movie_info.get("runtime"):
            runtime = movie_info.get("runtime").get("seconds")
        overview = ''
        if movie_info.get("plot"):
            overview = movie_info.get("plot").get("plotText").get("plainText")
        return schemas.MediaInfo(
            type="电影",
            title=title,
            year=f'{release_year}',
            title_year=f"{title} ({release_year})",
            mediaid_prefix="imdb",
            media_id=str(movie_info.get("id")),
            poster_path=poster_path,
            vote_average=vote_average,
            runtime=runtime,
            overview=overview,
            imdb_id=movie_info.get("id")
        )

    @staticmethod
    def __series_to_media(series_info: dict) -> schemas.MediaInfo:
        title = ""
        if series_info.get("titleText"):
            title = series_info.get("titleText", {}).get("text", "")
        release_year = 0
        if series_info.get("releaseYear"):
            release_year = series_info.get("releaseYear", {}).get("year")
        poster_path = None
        if series_info.get("primaryImage"):
            primary_image = series_info.get("primaryImage").get("url")
            if primary_image:
                poster_path = primary_image.replace('@._V1', '@._V1_QL75_UY414_CR6,0,280,414_')
        vote_average = 0
        if series_info.get("ratingsSummary"):
            vote_average = series_info.get("ratingsSummary").get("aggregateRating")
        runtime = 0
        if series_info.get("runtime"):
            runtime = series_info.get("runtime").get("seconds")
        overview = ''
        if series_info.get("plot"):
            if series_info.get("plot").get("plotText"):
                overview = series_info.get("plot").get("plotText").get("plainText")
        release_date_str = '0000-00-00'
        if series_info.get("releaseDate"):
            release_date = series_info.get('releaseDate')
            release_date_str = f"{release_date.get('year')}-{release_date.get('month')}-{release_date.get('day')}"
        return schemas.MediaInfo(
            type="电视剧",
            title=title,
            year=f'{release_year}',
            title_year=f"{title} ({release_year})",
            mediaid_prefix="imdb",
            media_id=str(series_info.get("id")),
            release_date=release_date_str,
            poster_path=poster_path,
            vote_average=vote_average,
            runtime=runtime,
            overview=overview,
            imdb_id=series_info.get("id")
        )

    @staticmethod
    def title_id_to_mtype(title_id: str) -> MediaType:
        if title_id in ["tvSeries", "tvMiniSeries", "tvShort", "tvEpisode"]:
            return MediaType.TV
        elif title_id in ["movie", "tvMovie"]:
            return MediaType.MOVIE
        return MediaType.UNKNOWN

    @staticmethod
    def is_mobile(user_agent):
        mobile_keywords = [
            'Mobile', 'iPhone', 'Android', 'Kindle', 'Opera Mini', 'Opera Mobi'
        ]
        for keyword in mobile_keywords:
            if re.search(keyword, user_agent, re.IGNORECASE):
                return True
        return False

    def trending_in_documentary(self, apikey: str, page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
        if apikey != settings.API_TOKEN:
            return []
        if not self._imdb_helper:
            return []
        title_types = ("tvSeries", "tvMiniSeries", "tvShort", 'movie')
        first_page = False
        if page == 1:
            first_page = True
            self._cache["trending_in_documentary"] = []  # 清空缓存
        results = []
        if len(self._cache["trending_in_documentary"]) >= count:
            results = self._cache["trending_in_documentary"][:count]
            self._cache["trending_in_documentary"] = self._cache["trending_in_documentary"][count:]
        else:
            results.extend(self._cache["trending_in_documentary"])
            remaining = count - len(results)
            self._cache["trending_in_documentary"] = []  # 清空缓存
            data = self._imdb_helper.advanced_title_search(first_page=first_page,
                                                           title_types=title_types,
                                                           sort_by="POPULARITY",
                                                           sort_order="ASC",
                                                           interests=("Documentary",)
                                                           )
            if not data:
                new_results = []
            else:
                new_results = data.get("edges")
            if new_results:
                results.extend(new_results[:remaining])
                self._cache["trending_in_documentary"] = new_results[remaining:]
        res = []
        for item in results:
            title_type_id = item.get('node').get("title").get("titleType", {}).get("id")
            mtype = self.title_id_to_mtype(title_type_id)
            if mtype == MediaType.MOVIE:
                res.append(self.__movie_to_media(item.get('node').get("title")))
            elif mtype == MediaType.TV:
                res.append(self.__series_to_media(item.get('node').get("title")))
        return res

    def imdb_top_250(self, apikey: str, page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
        if apikey != settings.API_TOKEN:
            return []
        if not self._imdb_helper:
            return []
        title_types = ("movie",)
        first_page = False
        if page == 1:
            first_page = True
            self._cache["imdb_top_250"] = []  # 清空缓存
        results = []
        if len(self._cache["imdb_top_250"]) >= count:
            results = self._cache["imdb_top_250"][:count]
            self._cache["imdb_top_250"] = self._cache["imdb_top_250"][count:]
        else:
            results.extend(self._cache["imdb_top_250"])
            remaining = count - len(results)
            self._cache["imdb_top_250"] = []  # 清空缓存
            data = self._imdb_helper.advanced_title_search(first_page=first_page,
                                                           title_types=title_types,
                                                           sort_by="USER_RATING",
                                                           sort_order="DESC",
                                                           ranked=("TOP_RATED_MOVIES-250",)
                                                           )
            if not data:
                new_results = []
            else:
                new_results = data.get("edges")
            if new_results:
                results.extend(new_results[:remaining])
                self._cache["imdb_top_250"] = new_results[remaining:]
        res = []
        for item in results:
            title_type_id = item.get('node').get("title").get("titleType", {}).get("id")
            mtype = self.title_id_to_mtype(title_type_id)
            if mtype == MediaType.MOVIE:
                res.append(self.__movie_to_media(item.get('node').get("title")))
        return res

    def trending_in_sitcom(self, apikey: str, page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
        if apikey != settings.API_TOKEN:
            return []
        if not self._imdb_helper:
            return []
        title_types = ("tvSeries", "tvMiniSeries", "tvShort")
        first_page = False
        if page == 1:
            first_page = True
            self._cache["trending_in_sitcom"] = []  # 清空缓存
        results = []
        if len(self._cache["trending_in_sitcom"]) >= count:
            results = self._cache["trending_in_sitcom"][:count]
            self._cache["trending_in_sitcom"] = self._cache["trending_in_sitcom"][count:]
        else:
            results.extend(self._cache["trending_in_sitcom"])
            remaining = count - len(results)
            self._cache["trending_in_sitcom"] = []  # 清空缓存
            data = self._imdb_helper.advanced_title_search(first_page=first_page,
                                                           title_types=title_types,
                                                           sort_by="POPULARITY",
                                                           sort_order="ASC",
                                                           interests=("Sitcom",)
                                                           )
            if not data:
                new_results = []
            else:
                new_results = data.get("edges")
            if new_results:
                results.extend(new_results[:remaining])
                self._cache["trending_in_sitcom"] = new_results[remaining:]
        res = []
        for item in results:
            title_type_id = item.get('node').get("title").get("titleType", {}).get("id")
            mtype = self.title_id_to_mtype(title_type_id)
            if mtype == MediaType.TV:
                res.append(self.__series_to_media(item.get('node').get("title")))
        return res

    def trending_in_anime(self, apikey: str, page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
        if apikey != settings.API_TOKEN:
            return []
        if not self._imdb_helper:
            return []
        title_types = ("tvSeries", "tvMiniSeries", "tvShort", 'movie')
        first_page = False
        if page == 1:
            first_page = True
            self._cache["trending_in_anime"] = []  # 清空缓存
        results = []
        if len(self._cache["trending_in_anime"]) >= count:
            results = self._cache["trending_in_anime"][:count]
            self._cache["trending_in_anime"] = self._cache["trending_in_anime"][count:]
        else:
            results.extend(self._cache["trending_in_anime"])
            remaining = count - len(results)
            self._cache["trending_in_anime"] = []  # 清空缓存
            data = self._imdb_helper.advanced_title_search(first_page=first_page,
                                                           title_types=title_types,
                                                           sort_by="POPULARITY",
                                                           sort_order="ASC",
                                                           interests=("Anime",)
                                                           )
            if not data:
                new_results = []
            else:
                new_results = data.get("edges")
            if new_results:
                results.extend(new_results[:remaining])
                self._cache["trending_in_anime"] = new_results[remaining:]
        res = []
        for item in results:
            title_type_id = item.get('node').get("title").get("titleType", {}).get("id")
            mtype = self.title_id_to_mtype(title_type_id)
            if mtype == MediaType.MOVIE:
                res.append(self.__movie_to_media(item.get('node').get("title")))
            elif mtype == MediaType.TV:
                res.append(self.__series_to_media(item.get('node').get("title")))
        return res

    def imdb_trending(self, apikey: str, page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
        if apikey != settings.API_TOKEN:
            return []
        if not self._imdb_helper:
            return []
        title_types = ("tvSeries", "tvMiniSeries", "tvShort", 'movie')
        first_page = False
        if page == 1:
            first_page = True
            self._cache["discover"] = []  # 清空缓存
        results = []
        if len(self._cache["discover"]) >= count:
            results = self._cache["discover"][:count]
            self._cache["discover"] = self._cache["discover"][count:]
        else:
            results.extend(self._cache["discover"])
            remaining = count - len(results)
            self._cache["discover"] = []  # 清空缓存
            data = self._imdb_helper.advanced_title_search(first_page=first_page,
                                                           title_types=title_types,
                                                           sort_by="POPULARITY",
                                                           sort_order="ASC",
                                                           )
            if not data:
                new_results = []
            else:
                new_results = data.get("edges")
            if new_results:
                results.extend(new_results[:remaining])
                self._cache["discover"] = new_results[remaining:]
        res = []
        for item in results:
            title_type_id = item.get('node').get("title").get("titleType", {}).get("id")
            mtype = self.title_id_to_mtype(title_type_id)
            if mtype == MediaType.MOVIE:
                res.append(self.__movie_to_media(item.get('node').get("title")))
            elif mtype == MediaType.TV:
                res.append(self.__series_to_media(item.get('node').get("title")))
        return res

    def imdb_discover(self, apikey: str, mtype: str = "series",
                      country: str = None,
                      lang: str = None,
                      genre: str = None,
                      sort_by: str = 'POPULARITY',
                      sort_order: str = 'ASC',
                      using_rating: bool = False,
                      user_rating: str = None,
                      year: str = None,
                      award: str = None,
                      ranked_list: str = None,
                      page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:

        if apikey != settings.API_TOKEN:
            return []
        if not self._imdb_helper:
            return []
        title_type = ("tvSeries", "tvMiniSeries", "tvShort")
        if mtype == 'movies':
            title_type = ("movie",)
        if user_rating and using_rating:
            user_rating = float(user_rating)
        else:
            user_rating = None
        genres = (genre,) if genre else None
        countries = (country,) if country else None
        languages = (lang,) if lang else None
        release_date_start = None
        release_date_end = None
        if year:
            if year == "2025":
                release_date_start = "2025-01-01"
            elif year == "2024":
                release_date_start = "2024-01-01"
                release_date_end = "2024-12-31"
            elif year == "2023":
                release_date_start = "2023-01-01"
                release_date_end = "2023-12-31"
            elif year == "2022":
                release_date_start = "2022-01-01"
                release_date_end = "2022-12-31"
            elif year == "2021":
                release_date_start = "2021-01-01"
                release_date_end = "2021-12-31"
            elif year == "2020":
                release_date_start = "2020-01-01"
                release_date_end = "2020-12-31"
            elif year == "2020s":
                release_date_start = "2020-01-01"
                release_date_end = "2029-12-31"
            elif year == "2010s":
                release_date_start = "2010-01-01"
                release_date_end = "2019-12-31"
            elif year == "2000s":
                release_date_start = "2000-01-01"
                release_date_end = "2009-12-31"
            elif year == "1990s":
                release_date_start = "1990-01-01"
                release_date_end = "1999-12-31"
            elif year == "1980s":
                release_date_start = "1980-01-01"
                release_date_end = "1989-12-31"
            elif year == "1970s":
                release_date_start = "1970-01-01"
                release_date_end = "1979-12-31"
        if not release_date_end:
            release_date_end = datetime.now().date().strftime("%Y-%m-%d")
        awards = (award,) if award else None
        ranked_lists = (ranked_list,) if ranked_list else None
        first_page = False
        if page == 1:
            first_page = True
            self._cache["discover"] = []  # 清空缓存
        results = []
        if len(self._cache["discover"]) >= count:
            results = self._cache["discover"][:count]
            self._cache["discover"] = self._cache["discover"][count:]
        else:
            results.extend(self._cache["discover"])
            remaining = count - len(results)
            self._cache["discover"] = []  # 清空缓存
            data = self._imdb_helper.advanced_title_search(first_page=first_page,
                                                           title_types=title_type,
                                                           genres=genres,
                                                           sort_by=sort_by,
                                                           sort_order=sort_order,
                                                           rating_min=user_rating,
                                                           countries=countries,
                                                           languages=languages,
                                                           release_date_end=release_date_end,
                                                           release_date_start=release_date_start,
                                                           award_constraint=awards,
                                                           ranked=ranked_lists)
            if not data:
                new_results = []
            else:
                new_results = data.get("edges")
            if new_results:
                results.extend(new_results[:remaining])
                self._cache["discover"] = new_results[remaining:]
        res = []
        if mtype == "movies":
            for movie in results:
                movie_info = movie.get('node').get("title")
                res.append(self.__movie_to_media(movie_info))

        else:
            for tv in results:
                tv_info = tv.get('node').get('title')
                res.append(self.__series_to_media(tv_info))

        return res

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
                "path": "/imdb_discover",
                "endpoint": self.imdb_discover,
                "methods": ["GET"],
                "summary": "IMDb探索数据源",
                "description": "获取 IMDb探索 数据",
            },
            {
                "path": "/imdb_trending",
                "endpoint": self.imdb_trending,
                "methods": ["GET"],
                "summary": "IMDb Trending",
                "description": "获取 IMDb Trending 数据",
            },
            {
                "path": "/trending_in_anime",
                "endpoint": self.trending_in_anime,
                "methods": ["GET"],
                "summary": "IMDb Trending in Anime",
                "description": "获取 IMDb Trending in Anime 数据",
            },
            {
                "path": "/trending_in_sitcom",
                "endpoint": self.trending_in_sitcom,
                "methods": ["GET"],
                "summary": "IMDb Trending in Sitcom",
                "description": "获取 IMDb Trending in Sitcom 数据",
            },
            {
                "path": "/imdb_top_250",
                "endpoint": self.imdb_top_250,
                "methods": ["GET"],
                "summary": "IMDb Top 250 Movies",
                "description": "获取 IMDb Top 250 Movies 数据",
            },
            {
                "path": "/trending_in_documentary",
                "endpoint": self.trending_in_documentary,
                "methods": ["GET"],
                "summary": "IMDb Trending in Documentary",
                "description": "获取 IMDb Trending in Documentary 数据",
            }
        ]

    @staticmethod
    def imdb_filter_ui() -> List[dict]:
        """
        IMDb过滤参数UI配置
        """
        # 国家字典
        country_dict = {
            "US": "美国",
            "CN": "中国",
            "JP": "日本",
            "KR": "韩国",
            "IN": "印度",
            "FR": "法国",
            "DE": "德国",
            "IT": "意大利",
            "ES": "西班牙",
            "UK": "英国",
            "AU": "澳大利亚",
            "CA": "加拿大",
            "RU": "俄罗斯",
            "BR": "巴西",
            "MX": "墨西哥",
            "AR": "阿根廷"
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
            "en": "英语",
            "zh": "中文",
            "ja": "日语",
            "ko": "韩语",
            "fr": "法语",
            "de": "德语",
            "it": "意大利语",
            "es": "西班牙语",
            "pt": "葡萄牙语",
            "ru": "俄语"
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
            "Action": "动作",
            "Adventure": "冒险",
            "Animation": "动画",
            "Biography": "传记",
            "Comedy": "喜剧",
            "Crime": "犯罪",
            "Documentary": "纪录片",
            "Drama": "剧情",
            "Family": "家庭",
            "Fantasy": "奇幻",
            "Game-Show": "游戏节目",
            "History": "历史",
            "Horror": "恐怖",
            "Music": "音乐",
            "Musical": "歌舞",
            "Mystery": "悬疑",
            "News": "新闻",
            "Reality-TV": "真人秀",
            "Romance": "爱情",
            "Sci-Fi": "科幻",
            "Short": "短片",
            "Sport": "体育",
            "Talk-Show": "脱口秀",
            "Thriller": "惊悚",
            "War": "战争",
            "Western": "西部片"
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
            "POPULARITY": "人气",
            "USER_RATING": "评分",
            "RELEASE_DATE": "发布日期",
            "TITLE_REGIONAL": "A-Z"
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

        sort_order_dict = {
            "ASC": "升序",
            "DESC": "降序",
        }

        sort_order_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in sort_order_dict.items()
        ]

        year_dict = {
            "2025": "2025",
            "2024": "2024",
            "2023": "2023",
            "2022": "2022",
            "2021": "2021",
            "2020": "2020",
            "2020s": "2020s",
            "2010s": "2010s",
            "2000s": "2000s",
            "1990s": "1990s",
            "1980s": "1980s",
            "1970s": "1970s",
        }

        year_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in year_dict.items()
        ]

        award_dict = {
            "ev0000003-Winning": "奥斯卡奖",
            "ev0000223-Winning": "艾美奖",
            "ev0000292-Winning": "金球奖",
            "ev0000003-Nominated": "奥斯卡提名",
            "ev0000223-Nominated": "艾美奖提名",
            "ev0000292-Nominated": "金球奖提名",
            "ev0000003-bestPicture-Winning": "最佳影片",
            "ev0000003-bestPicture-Nominated": "最佳影片提名",
            "ev0000003-bestDirector-Winning": "最佳导演",
            "ev0000003-bestDirector-Nominated": "最佳导演提名",
            "ev0000558-Winning": "金酸莓奖",
            "ev0000558-Nominated": "金酸莓奖提名"
        }

        award_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in award_dict.items()
        ]

        ranked_list_dict = {
            "TOP_RATED_MOVIES-100": "IMDb Top 100",
            "TOP_RATED_MOVIES-250": "IMDb Top 250",
            "TOP_RATED_MOVIES-1000": "IMDb Top 1000",
            "LOWEST_RATED_MOVIES-100": "IMDb Bottom 100",
            "LOWEST_RATED_MOVIES-250": "IMDb Bottom 250",
            "LOWEST_RATED_MOVIES-1000": "IMDb Bottom 1000",
        }

        ranked_list_ui = [
            {
                "component": "VChip",
                "props": {
                    "filter": True,
                    "tile": True,
                    "value": key
                },
                "text": value
            } for key, value in ranked_list_dict.items()
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
                                    "value": "series"
                                },
                                "text": "电视剧"
                            },
                            {
                                "component": "VChip",
                                "props": {
                                    "filter": True,
                                    "tile": True,
                                    "value": "movies"
                                },
                                "text": "电影"
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
                                "text": "年份"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "year"
                        },
                        "content": year_ui
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
                                "text": "奖项"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "award"
                        },
                        "content": award_ui
                    }
                ]
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == 'movies'}}"
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
                                "text": "排名"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "ranked_list"
                        },
                        "content": ranked_list_ui
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
                                "text": "排序依据"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "sort_by"
                        },
                        "content": sort_ui
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
                                "text": "排序方式"
                            }
                        ]
                    },
                    {
                        "component": "VChipGroup",
                        "props": {
                            "model": "sort_order"
                        },
                        "content": sort_order_ui
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
                                "text": "评分"
                            }
                        ]
                    },
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "using_rating",
                            "label": "启用",
                        },
                    },
                    {
                        "component": "VDivider",
                        "props": {
                            "class": "my-3"
                        }
                    },
                    {
                        "component": "VSlider",
                        "props": {
                            "v-model": "user_rating",
                            "thumb-label": True,
                            "max": "10",
                            "min": "1",
                            "step": "1",
                            "hide-details": True,
                        }
                    }
                ]
            }
        ]

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        """
        监听识别事件
        """
        if not self._enabled:
            return
        event_data: DiscoverSourceEventData = event.event_data
        imdb_source = schemas.DiscoverMediaSource(
            name="IMDb",
            mediaid_prefix="imdb",
            api_path=f"plugin/ImdbSource/imdb_discover?apikey={settings.API_TOKEN}",
            filter_params={
                "mtype": "series",
                "company": None,
                "contentRating": None,
                "country": None,
                "genre": None,
                "lang": None,
                "sort_by": "POPULARITY",
                "sort_order": "ASC",
                "status": None,
                "year": None,
                "user_rating": 1,
                "using_rating": False,
                "award": None,
                "ranked_list": None
            },
            depends={
                "ranked_list": ["mtype"]
            },
            filter_ui=self.imdb_filter_ui()
        )
        if not event_data.extra_sources:
            event_data.extra_sources = [imdb_source]
        else:
            event_data.extra_sources.append(imdb_source)

    @eventmanager.register(ChainEventType.MediaRecognizeConvert)
    def media_recognize_covert(self, event: Event) -> Optional[dict]:
        if not self._enabled:
            return
        event_data: MediaRecognizeConvertEventData = event.event_data
        if not event_data:
            return
        api_key = settings.TMDB_API_KEY
        if event_data.convert_type != "themoviedb" or not api_key:
            return
        if not event_data.mediaid.startswith("imdb"):
            return
        imdb_id = event_data.mediaid[5:]
        api_url = f"https://{settings.TMDB_API_DOMAIN}/3/find/{imdb_id}?api_key={api_key}&external_source=imdb_id"
        ret = RequestUtils(accept_type="application/json").get_res(api_url)
        if ret:
            data = ret.json()
            all_results = []
            for result_type in ["movie_results", "tv_results"]:
                if data.get(result_type):
                    all_results.extend(data[result_type])
            if not all_results:
                return  # 无匹配结果
            # 按 popularity 降序排序，取最高人气的条目
            most_popular_item = max(all_results, key=lambda x: x.get("popularity", -1))
            event_data.media_dict["id"] = most_popular_item.get("id")

    @eventmanager.register(ChainEventType.RecommendSource)
    def recommend_source(self, event: Event):
        if not self._enabled:
            return
        event_data: RecommendSourceEventData = event.event_data
        if not event_data:
            return
        imdb_trending: schemas.RecommendMediaSource = schemas.RecommendMediaSource(
            name="IMDb Trending",
            api_path=f"plugin/ImdbSource/imdb_trending?apikey={settings.API_TOKEN}",
            type='Rankings'
        )
        trending_in_anime: schemas.RecommendMediaSource = schemas.RecommendMediaSource(
            name="IMDb Trending in Anime",
            api_path=f"plugin/ImdbSource/trending_in_anime?apikey={settings.API_TOKEN}",
            type='Anime'
        )
        trending_in_sitcom: schemas.RecommendMediaSource = schemas.RecommendMediaSource(
            name="IMDb Trending in Sitcom",
            api_path=f"plugin/ImdbSource/trending_in_sitcom?apikey={settings.API_TOKEN}",
            type='TV Shows'
        )

        imdb_top_250: schemas.RecommendMediaSource = schemas.RecommendMediaSource(
            name="IMDb Top 250 Movies",
            api_path=f"plugin/ImdbSource/imdb_top_250?apikey={settings.API_TOKEN}",
            type='Movies'
        )
        imdb_documentary: schemas.RecommendMediaSource = schemas.RecommendMediaSource(
            name="IMDb Trending in Documentary",
            api_path=f"plugin/ImdbSource/trending_in_documentary?apikey={settings.API_TOKEN}",
            type='Rankings'
        )
        trending_source = [imdb_trending, trending_in_anime, trending_in_sitcom, imdb_top_250, imdb_documentary]
        if not event_data.extra_sources:
            event_data.extra_sources = trending_source
        else:
            event_data.extra_sources.extend(trending_source)
