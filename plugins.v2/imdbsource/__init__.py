from typing import Any, Callable, Coroutine, Dict, Optional, List, Tuple
from datetime import datetime
import re
import urllib.parse

from apscheduler.schedulers.background import BackgroundScheduler
import zhconv

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.chain import ChainBase
from app.plugins import _PluginBase
from app.schemas import DiscoverSourceEventData, MediaRecognizeConvertEventData, RecommendSourceEventData
from app.schemas.types import ChainEventType
from app.plugins.imdbsource.imdbhelper import ImdbHelper
from app import schemas
from app.utils.http import AsyncRequestUtils, RequestUtils
from app.schemas.types import MediaType
from app.core.meta import MetaBase
from app.core.context import MediaInfo
from app.log import logger


class ImdbSource(_PluginBase):
    # 插件名称
    plugin_name = "IMDb源"
    # 插件描述
    plugin_desc = "让探索，推荐和媒体识别支持IMDb数据源。"
    # 插件图标
    plugin_icon = "IMDb_IOS-OSX_App.png"
    # 插件版本
    plugin_version = "1.5.8"
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
    _recognize_media: bool = False
    _interests: List[str] = []
    _component_size: str = 'medium'
    _recognition_mode: str = 'auxiliary'

    # 私有属性
    _imdb_helper: Optional[ImdbHelper] = None
    _cache: Dict[str, Any] = {"discover": [], "trending": [], "imdb_top_250": [], "staff_picks": {}}
    _img_proxy_prefix: str = ''
    _scheduler: Optional[BackgroundScheduler] = None
    _original_method: Optional[Callable] = None
    _original_async_method: Optional[Callable[..., Coroutine[Any, Any, Optional[MediaInfo]]]] = None

    def init_plugin(self, config: dict = None):

        plugin_instance: ImdbSource = self

        def patched_recognize_media(chain_self, meta: MetaBase = None,
                                    mtype: Optional[MediaType] = None,
                                    tmdbid: Optional[int] = None,
                                    doubanid: Optional[str] = None,
                                    bangumiid: Optional[int] = None,
                                    episode_group: Optional[str] = None,
                                    cache: bool = True):
            # 调用原始方法
            if not plugin_instance._original_method:
                return None
            result = plugin_instance._original_method(chain_self, meta, mtype, tmdbid, doubanid, bangumiid,
                                                      episode_group, cache)
            if result is None and plugin_instance._enabled and plugin_instance._recognize_media:
                logger.info(f"通过插件 {plugin_instance.plugin_name} 执行：recognize_media ...")
                return plugin_instance.recognize_media(meta, mtype)
            return result

        async def patched_async_recognize_media(chain_self, meta: MetaBase = None,
                                                mtype: Optional[MediaType] = None,
                                                tmdbid: Optional[int] = None,
                                                doubanid: Optional[str] = None,
                                                bangumiid: Optional[int] = None,
                                                episode_group: Optional[str] = None,
                                                cache: bool = True):
            # 调用原始方法
            if not plugin_instance._original_async_method:
                return None
            result = await plugin_instance._original_async_method(chain_self, meta, mtype, tmdbid, doubanid, bangumiid,
                                                            episode_group, cache)
            if result is None and plugin_instance._enabled and plugin_instance._recognize_media:
                logger.info(f"通过插件 {plugin_instance.plugin_name} 执行：async_recognize_media ...")
                return await plugin_instance.async_recognize_media(meta, mtype)
            return result

        # 给 patch 函数加唯一标记
        patched_recognize_media._patched_by = id(self)
        # 保存原始方法
        if not (hasattr(ChainBase.recognize_media, "_patched_by") and
                ChainBase.recognize_media._patched_by == id(self)):
            self._original_method = getattr(ChainBase, "recognize_media", None)

        patched_async_recognize_media._patched_by = id(self)
        # 保存原始方法
        if not (hasattr(ChainBase.async_recognize_media, "_patched_by") and
                ChainBase.async_recognize_media._patched_by == id(self)):
            self._original_async_method = getattr(ChainBase, "async_recognize_media", None)

        if config:
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._staff_picks = config.get("staff_picks")
            self._recognize_media = config.get("recognize_media")
            if 'interests' not in config:
                self._interests = ['Anime', 'Documentary', 'Sitcom']
            else:
                self._interests = config.get("interests")
                if isinstance(self._interests, str):
                    self._interests = [self._interests]
            self._component_size = config.get("component_size") or "medium"
            self._recognition_mode = config.get("recognition_mode") or "auxiliary"
            self.__update_config()
        self._imdb_helper = ImdbHelper(proxies=settings.PROXY if self._proxy else None)
        if "media-amazon.com" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("media-amazon.com")
        if "media-imdb.com" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("media-imdb.com")
        if self._enabled:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.start()
            self._scheduler.add_job(self.__cache_staff_picks, trigger='date', run_date=None)
            if self._recognize_media and self._recognition_mode == 'auxiliary':
                # 替换 ChainBase.recognize_media
                if not (hasattr(ChainBase.recognize_media, "_patched_by") and
                        ChainBase.recognize_media._patched_by == id(self)):
                    ChainBase.recognize_media = patched_recognize_media
                # 替换 ChainBase.async_recognize_media
                if not (hasattr(ChainBase.async_recognize_media, "_patched_by") and
                        ChainBase.async_recognize_media._patched_by == id(self)):
                    ChainBase.async_recognize_media = patched_async_recognize_media
            else:
                # 恢复 ChainBase.recognize_media
                if (hasattr(ChainBase.recognize_media, "_patched_by") and
                        ChainBase.recognize_media._patched_by == id(self) and
                        self._original_method):
                    ChainBase.recognize_media = self._original_method
                # 恢复 ChainBase.async_recognize_media
                if (hasattr(ChainBase.async_recognize_media, "_patched_by") and
                        ChainBase.async_recognize_media._patched_by == id(self) and
                        self._original_async_method):
                    ChainBase.async_recognize_media = self._original_async_method
        else:
            self.stop_service()

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

        def year_and_type(imdb_entry: Dict) -> Tuple[MediaType, str, str]:
            title = next((t for t in titles if t.get("id") == imdb_entry.get('ttconst')), None)
            if not title:
                return MediaType.MOVIE, datetime.now().date().strftime("%Y"), ''
            media_id = title.get('titleType', {}).get('id')
            release_year = title.get('releaseYear', {}).get('year') or datetime.now().date().strftime("%Y")
            media_type = ImdbHelper.type_to_mtype(media_id)
            media_plot = title.get("plot", {}).get("plotText", {}).get("plainText", '')
            return media_type, release_year, media_plot

        # 列配置
        size_config = {
            "small": {"cols": {"cols": 12, "md": 4}, "height": 335},
            "medium-small": {"cols": {"cols": 12, "md": 6}, "height": 335},
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
        entries = self._cache['staff_picks'].get('entries')
        imdb_items = self._cache['staff_picks'].get('imdb_items')
        if not entries or not imdb_items:
            self.__cache_staff_picks()
            entries = self._cache['staff_picks'].get('entries')
            imdb_items = self._cache['staff_picks'].get('imdb_items')
        else:
            self._scheduler.add_job(self.__cache_staff_picks, trigger='date', run_date=None)
        if not entries or not imdb_items:
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
        images = imdb_items.get('images') or []
        names = imdb_items.get('names') or []
        titles = imdb_items.get('titles') or []
        contents = []
        for entry in entries:
            cast = [name for related in entry.get('relatedconst', []) for name in names if name.get('id') == related]
            mtype, year, plot = year_and_type(entry)
            mp_url = f"/media?mediaid=imdb:{entry.get('ttconst')}&title={entry.get('name')}&year={year}&type={mtype.value}"
            primary_img_url = next((f"{image.get('url')}" for image in images
                                    if image.get("id") == entry.get('rmconst')), '')
            primary_img_url = f'{self._img_proxy_prefix}{primary_img_url}'
            item1 = {
                'component': 'VCarouselItem',
                'props': {
                    'src': primary_img_url,
                    'cover': True,
                    'position': 'top',
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
                                                        'src': f"{self._img_proxy_prefix}"
                                                               f"{cs.get('primaryImage', {}).get('url', '')}",
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
            poster_url = next((f"{title.get('primaryImage', {}).get('url')}" for title in titles if
                               title.get("id") == entry.get('ttconst')), None)
            poster_url = f"{self._img_proxy_prefix}{poster_url}"
            poster_com = {
                'component': 'VImg',
                'props': {
                    'src': poster_url,
                    'alt': '海报',
                    'cover': True,
                    'class': 'rounded',
                    'max-width': '160',
                    'max-height': '240',
                    'style': 'height: auto; aspect-ratio: 2/3;',
                }
            }

            poster_ui = {
                'component': 'div',
                'props': {
                    'class': 'd-flex justify-center mt-2'
                },
                'content': [
                    {
                        'component': 'a',
                        'props': {
                            'href': f'#{mp_url}',
                            'class': 'no-underline w-100',
                            'style': 'display: flex; justify-content: center;'
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
                    'src': primary_img_url,
                    'cover': True,
                    'position': 'top'
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
                                            'md': 3
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
        option_groups = []
        for i, v in self._imdb_helper.interests.items():
            options = []
            for name, in_id in v.items():
                option = {
                    'component': 'VCol',
                    'props': {'cols': 12, 'md': 3},
                    'content': [
                        {
                            'component': 'VCheckbox',
                            'props': {'label': name, 'value': name, 'model': 'interests'},
                        }
                    ]
                }
                options.append(option)
            group = {
                'component': 'VExpansionPanel',
                'content': [
                    {
                        'component': 'VExpansionPanelTitle',
                        'text': i
                    },
                    {
                        'component': 'VExpansionPanelText',
                        'content': [
                            {
                                'component': 'VRow',
                                'content': options
                            }
                        ]
                    }
                ]
            }
            option_groups.append(group)
        interests_ui = {
            'component': 'VExpansionPanels',
            'props': {
                'multiple': False,
                'popout': True
            },
            'content': [
                {
                    'component': 'VExpansionPanel',
                    'content': [
                        {
                            'component': 'VExpansionPanelTitle',
                            'text': '推荐'
                        },
                        {
                            'component': 'VExpansionPanelText',
                            'content': [
                                {
                                    'component': 'VRow',
                                    'content': [
                                        {
                                            'component': 'VExpansionPanels',
                                            'props': {
                                                'multiple': True,
                                                'popout': True
                                            },
                                            'content': option_groups
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件"
                                        },
                                    }
                                ],
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
                                            'model': 'proxy',
                                            'label': '使用代理服务器'
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
                                            'model': 'staff_picks',
                                            'label': 'IMDb 编辑精选组件'
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
                                            'model': 'recognize_media',
                                            'label': '媒体识别'
                                        }
                                    }
                                ]
                            }
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
                                                {"title": "中小型", "value": "medium-small"},
                                                {"title": "中型", "value": "medium"}
                                            ]
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'recognition_mode',
                                            'label': '媒体识别工作模式',
                                            'items': [
                                                {"title": "仅当系统无法识别", "value": "auxiliary"},
                                                {"title": "正常", "value": "hijacking"}
                                            ]
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
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 12
                                },
                                'content': [
                                    interests_ui
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
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'title': '代理设置',
                                            'text': '可能需要通过代理访问的域名：「media-amazon.com」「media-imdb.com」「imdbapi.dev」「imdb.com」'
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
                                        'component': 'VAlert',
                                        'props': {
                                            'border': 'start',
                                            'border-color': 'info',
                                            'variant': 'tonal',
                                            'title': 'About IMDbAPI'
                                        },
                                        'content': [
                                            {
                                                'component': 'span',
                                                'text': 'This plugin makes partial use of the Free IMDb API (imdbapi.dev), courtesy of '
                                            },
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': 'https://t.me/imdbapi',
                                                    'target': '_blank'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'u',
                                                        'text': '@reflect pprof'
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'span',
                                                'text': '. Huge thanks for this fantastic API!'
                                            },
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "proxy": False,
            "staff_picks": False,
            "recognize_media": False,
            "interests": ['Anime', 'Documentary', 'Sitcom'],
            "component_size": "medium",
            "recognition_mode": "auxiliary"
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        if (hasattr(ChainBase.recognize_media, "_patched_by") and
                ChainBase.recognize_media._patched_by == id(self) and
                self._original_method):
            ChainBase.recognize_media = self._original_method
        if (hasattr(ChainBase.async_recognize_media, "_patched_by") and
                ChainBase.async_recognize_media._patched_by == id(self) and
                self._original_async_method):
            ChainBase.async_recognize_media = self._original_async_method
        if self._scheduler:
            try:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
            except Exception as e:
                logger.error(f"退出插件失败：{e}")

    def get_module(self) -> Dict[str, Any]:
        """
        获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）
        {
            "id1": self.xxx1,
            "id2": self.xxx2,
        }
        """
        modules = {}
        if self._recognize_media and self._recognition_mode == 'hijacking':
            modules['async_recognize_media'] = self.async_recognize_media
            modules['recognize_media'] = self.recognize_media
        return modules

    def __update_config(self):
        self.update_config(
            {
                "enabled": self._enabled,
                "proxy": self._proxy,
                "staff_picks": self._staff_picks,
                "recognize_media": self._recognize_media,
                "interests": self._interests,
                "component_size": self._component_size,
                "recognition_mode": self._recognition_mode,
            }
        )

    def __cache_staff_picks(self):
        entries = self._imdb_helper.staff_picks()
        imdb_items = None
        if entries:
            imdb_items = self._imdb_helper.vertical_list_page_items(
                titles=[entry.get('ttconst', '') for entry in entries],
                names=[item for entry in entries for item in entry.get("relatedconst", []) if item.startswith("nm")],
                images=[entry.get('rmconst', '') for entry in entries],
            )
        if not entries or not imdb_items:
            return
        self._cache['staff_picks'] = {'entries': entries, 'imdb_items': imdb_items}

    def __movie_to_media(self, movie_info: dict) -> schemas.MediaInfo:
        title = ""
        if movie_info.get("titleText"):
            title = movie_info.get("titleText", {}).get("text", "")
        release_year = ''
        if movie_info.get("releaseYear"):
            release_year = movie_info.get("releaseYear", {}).get("year")
        if not release_year and movie_info.get("releaseDate"):
            release_year = movie_info.get("releaseDate", {}).get("year")
        poster_path = None
        if movie_info.get("primaryImage"):
            primary_image = movie_info.get("primaryImage").get("url")
            if primary_image:
                poster_path = primary_image.replace('@._V1', '@._V1_QL75_UY414_CR6,0,280,414_')
                poster_path = f"{self._img_proxy_prefix}{poster_path}"
        vote_average = 0
        if movie_info.get("ratingsSummary"):
            vote_average = movie_info.get("ratingsSummary").get("aggregateRating")
        runtime = 0
        if movie_info.get("runtime"):
            runtime = movie_info.get("runtime").get("seconds")
        overview = ''
        if movie_info.get("plot"):
            if movie_info.get("plot", {}).get("plotText"):
                overview = movie_info.get("plot").get("plotText").get("plainText")
        return schemas.MediaInfo(
            type="电影",
            title=title,
            year=f'{release_year}',
            title_year=f"{title} ({release_year})" if release_year else title,
            mediaid_prefix="imdb",
            media_id=str(movie_info.get("id")),
            poster_path=poster_path,
            vote_average=vote_average,
            runtime=runtime,
            overview=overview,
            imdb_id=movie_info.get("id")
        )

    def __series_to_media(self, series_info: dict) -> schemas.MediaInfo:
        title = ""
        if series_info.get("titleText"):
            title = series_info.get("titleText", {}).get("text", "")
        release_year = ''
        if series_info.get("releaseYear"):
            release_year = series_info.get("releaseYear", {}).get("year")
        if not release_year and series_info.get("releaseDate"):
            release_year = series_info.get("releaseDate", {}).get("year")
        poster_path = None
        if series_info.get("primaryImage"):
            primary_image = series_info.get("primaryImage").get("url")
            if primary_image:
                poster_path = primary_image.replace('@._V1', '@._V1_QL75_UY414_CR6,0,280,414_')
                poster_path = f"{self._img_proxy_prefix}{poster_path}"
        vote_average = 0
        if series_info.get("ratingsSummary"):
            vote_average = series_info.get("ratingsSummary").get("aggregateRating")
        runtime = 0
        if series_info.get("runtime"):
            runtime = series_info.get("runtime").get("seconds")
        overview = ''
        if series_info.get("plot"):
            if series_info.get("plot", {}).get("plotText"):
                overview = series_info.get("plot").get("plotText").get("plainText")
        release_date_str = '0000-00-00'
        if series_info.get("releaseDate"):
            release_date = series_info.get('releaseDate')
            release_date_str = ImdbHelper.release_date_string(release_date)
        return schemas.MediaInfo(
            type="电视剧",
            title=title,
            year=f'{release_year}',
            title_year=f"{title} ({release_year})" if release_year else title,
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
    def is_mobile(user_agent):
        mobile_keywords = [
            'Mobile', 'iPhone', 'Android', 'Kindle', 'Opera Mini', 'Opera Mobi'
        ]
        for keyword in mobile_keywords:
            if re.search(keyword, user_agent, re.IGNORECASE):
                return True
        return False

    async def trending(self, interest: str, page: int = 1) -> List[schemas.MediaInfo]:
        if not self._imdb_helper:
            return []
        if interest not in self._imdb_helper.interest_id:
            return []
        count = 30
        title_types = ("tvSeries", "tvMiniSeries", "tvShort", 'tvMovie', 'movie')
        first_page = False
        if page == 1:
            first_page = True
            self._cache[interest] = []  # 清空缓存
        results = []
        if len(self._cache[interest]) >= count:
            results = self._cache[interest][:count]
            self._cache[interest] = self._cache[interest][count:]
        else:
            results.extend(self._cache[interest])
            remaining = count - len(results)
            self._cache[interest] = []  # 清空缓存
            data = await self._imdb_helper.async_advanced_title_search(first_page=first_page,
                                                                       title_types=title_types,
                                                                       sort_by="POPULARITY",
                                                                       sort_order="ASC",
                                                                       interests=(interest,)
                                                                       )
            if not data:
                new_results = []
            else:
                new_results = data.get("edges")
            if new_results:
                results.extend(new_results[:remaining])
                self._cache[interest] = new_results[remaining:]
        res = []
        for item in results:
            title_type_id = item.get('node').get("title").get("titleType", {}).get("id")
            mtype = ImdbHelper.type_to_mtype(title_type_id)
            if mtype == MediaType.MOVIE:
                res.append(self.__movie_to_media(item.get('node').get("title")))
            elif mtype == MediaType.TV:
                res.append(self.__series_to_media(item.get('node').get("title")))
        return res

    async def imdb_top_250(self, page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
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
            data = await self._imdb_helper.async_advanced_title_search(
                first_page=first_page,
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
            mtype = ImdbHelper.type_to_mtype(title_type_id)
            if mtype == MediaType.MOVIE:
                res.append(self.__movie_to_media(item.get('node').get("title")))
        return res

    async def imdb_trending(self, page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:
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
            data = await self._imdb_helper.async_advanced_title_search(
                first_page=first_page,
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
            mtype = ImdbHelper.type_to_mtype(title_type_id)
            if mtype == MediaType.MOVIE:
                res.append(self.__movie_to_media(item.get('node').get("title")))
            elif mtype == MediaType.TV:
                res.append(self.__series_to_media(item.get('node').get("title")))
        return res

    async def imdb_discover(self, mtype: str = "series",
                            country: str = None,
                            lang: str = None,
                            genre: str = None,
                            sort_by: str = 'POPULARITY',
                            sort_order: str = 'DESC',
                            using_rating: bool = False,
                            user_rating: str = None,
                            year: str = None,
                            award: str = None,
                            ranked_list: str = None,
                            page: int = 1, count: int = 30) -> List[schemas.MediaInfo]:

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
        if sort_by == 'POPULARITY':
            sort_order = 'ASC' if sort_order == 'DESC' else 'DESC'
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
            self._cache["discover"] = []
            data = await self._imdb_helper.async_advanced_title_search(
                first_page=first_page,
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
        apis = [
            {
                "path": "/imdb-discover",
                "endpoint": self.imdb_discover,
                "methods": ["GET"],
                "auth": 'bear',
                "summary": "IMDb探索数据源",
                "description": "获取 IMDb探索 数据",
            },
            {
                "path": "/imdb-trending",
                "endpoint": self.imdb_trending,
                "methods": ["GET"],
                "auth": 'bear',
                "summary": "IMDb Trending",
                "description": "获取 IMDb Trending 数据",
            },
            {
                "path": "/imdb-top-250",
                "endpoint": self.imdb_top_250,
                "methods": ["GET"],
                "auth": 'bear',
                "summary": "IMDb Top 250 Movies",
                "description": "获取 IMDb Top 250 Movies 数据",
            },
            {
                "path": "/trending",
                "endpoint": self.trending,
                "methods": ["GET"],
                "auth": 'bear',
                "summary": f"Trending on IMDb",
                "description": f"获取 Trending on IMDb 数据",
            }
        ]
        return apis

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
            "DESC": "降序",
            "ASC": "升序"
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
            api_path=f"plugin/ImdbSource/imdb-discover",
            filter_params={
                "mtype": "series",
                "company": None,
                "contentRating": None,
                "country": None,
                "genre": None,
                "lang": None,
                "sort_by": "POPULARITY",
                "sort_order": "DESC",
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
    async def async_media_recognize_covert(self, event: Event) -> Optional[dict]:
        if not self._enabled:
            return
        event_data: MediaRecognizeConvertEventData = event.event_data
        if not event_data:
            return
        if event_data.convert_type != "themoviedb":
            return
        if not event_data.mediaid.startswith("imdb"):
            return
        imdb_id = event_data.mediaid[5:]
        tmdb_id = await self.async_imdb_to_tmdb(imdb_id)
        if tmdb_id is not None:
            event_data.media_dict["id"] = tmdb_id

    @eventmanager.register(ChainEventType.RecommendSource)
    def recommend_source(self, event: Event):
        if not self._enabled:
            return
        event_data: RecommendSourceEventData = event.event_data
        if not event_data:
            return
        imdb_trending: schemas.RecommendMediaSource = schemas.RecommendMediaSource(
            name="IMDb Trending",
            api_path=f"plugin/ImdbSource/imdb-trending",
            type='Rankings'
        )
        imdb_top_250: schemas.RecommendMediaSource = schemas.RecommendMediaSource(
            name="IMDb Top 250 Movies",
            api_path=f"plugin/ImdbSource/imdb-top-250",
            type='Movies'
        )
        trending_source = [imdb_trending, imdb_top_250]
        for interest in self._interests:
            source_type = 'Rankings'
            if interest in self._imdb_helper.interests['Anime']:
                source_type = 'Anime'
            elif interest in ['Sitcom']:
                source_type = 'TV Shows'
            source = schemas.RecommendMediaSource(
                name=f"Trending {interest} on IMDb",
                api_path=f"plugin/ImdbSource/trending?interest={urllib.parse.quote(interest)}",
                type=source_type
            )
            trending_source.append(source)
        if not event_data.extra_sources:
            event_data.extra_sources = trending_source
        else:
            event_data.extra_sources.extend(trending_source)

    def recognize_media(self, meta: MetaBase = None,
                        mtype: MediaType = None,
                        **kwargs) -> Optional[MediaInfo]:
        """
        识别媒体信息
        :param meta: 识别的元数据
        :param mtype: 识别的媒体类型
        :return: 识别的媒体信息，包括剧集信息
        """
        if not self._enabled:
            return None
        if kwargs.get('tmdbid') or kwargs.get('doubanid') or kwargs.get('bangumiid'):
            return None
        if not meta:
            return None
        elif not meta.name:
            logger.warn("识别媒体信息时未提供元数据名称")
            return None
        else:
            if mtype:
                meta.type = mtype
        info = {}
        # 简体名称
        zh_name = zhconv.convert(meta.cn_name, 'zh-hans') if meta.cn_name else None
        names = list(dict.fromkeys([k for k in [meta.cn_name, zh_name, meta.en_name] if k]))
        for name in names:
            if meta.begin_season:
                logger.info(f"正在识别 {name} 第{meta.begin_season}季 ...")
            else:
                logger.info(f"正在识别 {name} ...")
            if meta.type == MediaType.UNKNOWN and not meta.year:
                info = self._imdb_helper.match_by(name)
            else:
                if meta.type == MediaType.TV:
                    info = self._imdb_helper.match(name=name, year=meta.year, mtype=meta.type, season_year=meta.year,
                                                   season_number=meta.begin_season)
                    if not info:
                        # 去掉年份再查一次
                        info = self._imdb_helper.match(name=name, mtype=meta.type)
                else:
                    # 有年份先按电影查
                    info = self._imdb_helper.match(name=name, year=meta.year, mtype=MediaType.MOVIE)
                    # 没有再按电视剧查
                    if not info:
                        info = self._imdb_helper.match(name=name, year=meta.year, mtype=MediaType.TV)
                    if not info:
                        # 去掉年份和类型再查一次
                        info = self._imdb_helper.match_by(name=name)
            if info:
                break
        if info:
            info = self._imdb_helper.update_info(info.get('id'), info=info) or info
            mediainfo = ImdbSource._convert_mediainfo(info)
            mediainfo.tmdb_id = self.imdb_to_tmdb(info.get('id'), mediainfo)
            cat = ImdbHelper.get_category(info.get('media_type'), info)
            mediainfo.set_category(cat)
            logger.info(f"{meta.name} IMDb 识别结果：{mediainfo.type.value} "
                        f"{mediainfo.title_year} "
                        f"{mediainfo.imdb_id}")
            return mediainfo
        return None

    async def async_recognize_media(self, meta: MetaBase = None,
                                    mtype: MediaType = None,
                                    **kwargs) -> Optional[MediaInfo]:
        """
        异步识别媒体信息
        :param meta: 识别的元数据
        :param mtype: 识别的媒体类型
        :return: 识别的媒体信息，包括剧集信息
        """
        if not self._enabled:
            return None
        # when external id exists
        if kwargs.get('tmdbid') or kwargs.get('doubanid') or kwargs.get('bangumiid'):
            return None
        if not meta:
            return None
        elif not meta.name:
            logger.warn("识别媒体信息时未提供元数据名称")
            return None
        else:
            if mtype:
                meta.type = mtype
        info = {}
        # 简体名称
        zh_name = zhconv.convert(meta.cn_name, 'zh-hans') if meta.cn_name else None
        names = list(dict.fromkeys([k for k in [meta.cn_name, zh_name, meta.en_name] if k]))
        for name in names:
            if meta.begin_season:
                logger.info(f"正在识别 {name} 第{meta.begin_season}季 ...")
            else:
                logger.info(f"正在识别 {name} ...")
            if meta.type == MediaType.UNKNOWN and not meta.year:
                info = await self._imdb_helper.async_match_by(name)
            else:
                if meta.type == MediaType.TV:
                    info = await self._imdb_helper.async_match(name=name, year=meta.year, mtype=meta.type,
                                                               season_year=meta.year,
                                                               season_number=meta.begin_season)
                    if not info:
                        # 去掉年份再查一次
                        info = await self._imdb_helper.async_match(name=name, mtype=meta.type)
                else:
                    # 有年份先按电影查
                    info = await self._imdb_helper.async_match(name=name, year=meta.year, mtype=MediaType.MOVIE)
                    # 没有再按电视剧查
                    if not info:
                        info = await self._imdb_helper.async_match(name=name, year=meta.year, mtype=MediaType.TV)
                    if not info:
                        # 去掉年份和类型再查一次
                        info = await self._imdb_helper.async_match_by(name=name)
            if info:
                break
        if info:
            info = await self._imdb_helper.async_update_info(info.get('id'), info=info) or info
            mediainfo = ImdbSource._convert_mediainfo(info)
            mediainfo.tmdb_id = await self.async_imdb_to_tmdb(info.get('id'), mediainfo)
            cat = ImdbHelper.get_category(info.get('media_type'), info)
            mediainfo.set_category(cat)
            logger.info(f"{meta.name} IMDb 识别结果：{mediainfo.type.value} "
                        f"{mediainfo.title_year} "
                        f"{mediainfo.imdb_id}")
            return mediainfo
        return None

    @staticmethod
    def _convert_mediainfo(info: Dict[str, Any]) -> MediaInfo:
        mediainfo = MediaInfo()
        mediainfo.source = 'imdb'
        mediainfo.type = info.get('media_type')
        mediainfo.title = info.get('primaryTitle', '')
        mediainfo.year = f"{info.get('startYear', 0)}"
        mediainfo.imdb_id = info.get('id')
        mediainfo.overview = info.get('plot') or ''
        spoken_languages = info.get('spokenLanguages') or []
        mediainfo.original_language = spoken_languages[0].get('code') if spoken_languages else None
        mediainfo.original_title = info.get('originalTitle')
        mediainfo.names = [aka.get('text', '') for aka in (info.get('akas') or [])]
        origin_countries = info.get('originCountries') or []
        mediainfo.origin_country = [origin_country.get('code', '') for origin_country in origin_countries]
        mediainfo.poster_path = (info.get('primaryImage') or {}).get('url')
        mediainfo.genres = [{"id": genre, "name": genre} for genre in info.get("genres") or []]
        directors = []
        actors = []
        for credit in (info.get('credits') or []):
            name = credit.get('name') or {}
            if credit.get('category') == 'DIRECTOR':
                directors.append({'name': name.get('displayName')})
            elif credit.get('category') in ['CAST', 'ACTOR', 'ACTRESS']:
                actors.append({'name': name.get('displayName')})
        mediainfo.director = directors
        mediainfo.actor = actors
        mediainfo.vote_average = round(float((info.get('rating') or {}).get('aggregateRating') or 0), 1)
        if mediainfo.type == MediaType.TV:
            for season, season_info in info.get('seasons', {}).items():
                episode_count = season_info.get("episode_count")
                mediainfo.seasons[season] = list(range(1, episode_count + 1))
                air_date = season_info.get("air_date")
                if air_date:
                    mediainfo.season_years[season] = air_date[:4]
                if not mediainfo.release_date:
                    mediainfo.release_date = air_date
        return mediainfo

    @staticmethod
    def _match_results(data: dict, media_info: Optional[MediaInfo] = None) -> Optional[int]:
        # 合并两种结果
        all_results = []
        for key in ["movie_results", "tv_results"]:
            all_results.extend(data.get(key, []))
        if not all_results:
            return None  # 无匹配结果

        def pick_most_popular(results):
            return max(results, key=lambda x: x.get("popularity", -1), default=None)

        # 未提供 media_info：直接返回人气最高的
        if not media_info:
            most_popular = pick_most_popular(all_results)
            return most_popular.get("id") if most_popular else None
        # 按类型过滤
        type_map = {
            MediaType.TV: ['tv'],
            MediaType.MOVIE: ['movie'],
            None: ['tv', 'movie']
        }
        allowed_types = type_map.get(media_info.type, ['tv', 'movie'])
        filtered = [res for res in all_results if res.get('media_type') in allowed_types]

        # 定义一个过滤链：每次过滤后如果只剩一个结果就返回
        def filter_and_return(results, predicate):
            filtered_res = [res for res in results if predicate(res)]
            if not filtered_res:
                return None, []
            if len(filtered_res) == 1:
                return filtered_res[0].get("id"), []
            return None, filtered_res

        # 通过年份过滤
        if media_info.year:
            def match_year(res):
                date = res.get('first_air_date') or res.get('release_date') or ''
                return date[:4] == media_info.year

            result_id, filtered = filter_and_return(filtered, match_year)
            if result_id:
                return result_id
            if not filtered:
                return None
        # 通过名称过滤
        if media_info.names:
            def match_name(res):
                name = res.get('name') or res.get('title') or ''
                return ImdbHelper.compare_names(name, media_info.names)

            result_id, filtered = filter_and_return(filtered, match_name)
            if result_id:
                return result_id
            if not filtered:
                return None
        # 最终按人气返回
        most_popular = pick_most_popular(filtered)
        return most_popular.get("id") if most_popular else None

    def imdb_to_tmdb(self, imdb_id: str, media_info: Optional[MediaInfo] = None) -> Optional[int]:
        api_key = settings.TMDB_API_KEY
        api_url = (
            f"https://{settings.TMDB_API_DOMAIN}/3/find/{imdb_id}"
            f"?api_key={api_key}&external_source=imdb_id"
        )
        data = RequestUtils(accept_type="application/json", proxies=settings.PROXY if self._proxy else None
                            ).get_json(api_url)
        if not data:
            return None
        return self._match_results(data, media_info)

    async def async_imdb_to_tmdb(self, imdb_id: str, media_info: Optional[MediaInfo] = None) -> Optional[int]:
        api_key = settings.TMDB_API_KEY
        api_url = (
            f"https://{settings.TMDB_API_DOMAIN}/3/find/{imdb_id}"
            f"?api_key={api_key}&external_source=imdb_id"
        )
        data = await AsyncRequestUtils(accept_type="application/json", proxies=settings.PROXY if self._proxy else None
                                       ).get_json(api_url)
        if not data:
            return None
        return self._match_results(data, media_info)
