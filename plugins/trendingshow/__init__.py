import re
from typing import List, Tuple, Dict, Any, Optional

from app.chain.tmdb import TmdbChain
from app.plugins import _PluginBase


class TrendingShow(_PluginBase):
    # 插件名称
    plugin_name = "流行趋势轮播"
    # 插件描述
    plugin_desc = "在仪表板中显示流行趋势海报轮播图。"
    # 插件图标
    plugin_icon = "TrendingShow.jpg"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "trendingshow_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False
    _small_dev_size: str = "small"
    _big_dev_size: str = "large"

    def init_plugin(self, config: dict = None):
        self._enable = config.get("enable")
        self._small_dev_size = config.get("small_dev_size") or "small"
        self._big_dev_size = config.get("big_dev_size") or "large"

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

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
                                            'model': 'enable',
                                            'label': '启用插件',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'small_dev_size',
                                            'label': '小屏幕组件规格',
                                            'items': [
                                                {"title": "迷你", "value": "mini"},
                                                {"title": "小型", "value": "small"},
                                                {"title": "中型", "value": "medium"},
                                                {"title": "大型", "value": "large"}
                                            ]
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'big_dev_size',
                                            'label': '大屏幕组件规格',
                                            'items': [
                                                {"title": "迷你", "value": "mini"},
                                                {"title": "小型", "value": "small"},
                                                {"title": "中型", "value": "medium"},
                                                {"title": "大型", "value": "large"}
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enable": self._enable,
            "small_dev_size": self._small_dev_size,
            "big_dev_size": self._big_dev_size
        }

    def get_page(self) -> List[dict]:
        pass

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
        # 列配置
        size_config = {
            "mini": {"cols": {"cols": 12, "md": 4}, "height": 160},
            "small": {"cols": {"cols": 12, "md": 6}, "height": 262},
            "medium": {"cols": {"cols": 12, "md": 8}, "height": 335},
            "large": {"cols": {"cols": 12, "md": 12}, "height": 500}
        }

        if self.is_mobile(kwargs.get('user_agent')):
            config = size_config.get(self._small_dev_size, size_config["large"])
        else:
            config = size_config.get(self._big_dev_size, size_config["small"])

        cols = config["cols"]
        height = config["height"]
        # 全局配置
        attrs = {
            "border": False
        }
        # 获取流行越势数据
        medias = TmdbChain().tmdb_trending()
        if not medias:
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
        else:
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
                            'content': [
                                {
                                    'component': 'VCarouselItem',
                                    'props': {
                                        'src': media.get_backdrop_image() if (
                                                self.is_mobile(kwargs.get('user_agent')) and
                                                self._small_dev_size == "mini") else media.backdrop_path,
                                        'cover': True,
                                        'position': 'top'
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'w-full flex flex-col flex-wrap justify-end align-left text-white absolute bottom-0 pa-4',
                                            },
                                            'content': [
                                                {
                                                    'component': 'h1',
                                                    'props': {
                                                        'class': 'mb-1 text-white text-shadow font-extrabold text-xl line-clamp-2 overflow-hidden text-ellipsis ...'
                                                    },
                                                    'html': f"{media.title} <span class='text-sm font-normal'>{media.year}</span>",
                                                },
                                                {
                                                    'component': 'span',
                                                    'props': {
                                                        'class': 'text-shadow line-clamp-2 overflow-hidden text-ellipsis ...'
                                                    },
                                                    'text': media.overview,
                                                }
                                            ]
                                        }
                                    ]
                                } for media in medias[:10]
                            ]
                        }
                    ]
                }]

        return cols, attrs, elements

    def get_state(self) -> bool:
        return self._enable

    def stop_service(self):
        pass

    @staticmethod
    def is_mobile(user_agent):
        mobile_keywords = [
            'Mobile', 'iPhone', 'Android', 'Kindle', 'Opera Mini', 'Opera Mobi'
        ]
        for keyword in mobile_keywords:
            if re.search(keyword, user_agent, re.IGNORECASE):
                return True
        return False
