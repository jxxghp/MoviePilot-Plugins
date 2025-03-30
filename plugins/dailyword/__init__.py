from datetime import datetime
from functools import lru_cache
from typing import List, Tuple, Dict, Any, Optional

from app.plugins import _PluginBase
from app.utils.http import RequestUtils


class DailyWord(_PluginBase):
    # 插件名称
    plugin_name = "每日一言"
    # 插件描述
    plugin_desc = "在仪表板中显示每日一言卡片。"
    # 插件图标
    plugin_icon = "Calibre_B.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "dailyowrd_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False
    _size: str = "mini"

    def init_plugin(self, config: dict = None):
        self._enable = config.get("enable")
        self._size = config.get("size")

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
                                            'model': 'size',
                                            'label': '组件规格',
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
            "size": self._size
        }

    def get_page(self) -> List[dict]:
        pass

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """
        获取插件仪表盘元信息
        返回示例：
            [{
                "key": "dashboard1", // 仪表盘的key，在当前插件范围唯一
                "name": "仪表盘1" // 仪表盘的名称
            }, {
                "key": "dashboard2",
                "name": "仪表盘2"
            }]
        """
        return [{
            "key": "dailyword_dashboard",
            "name": "每日一言"
        }]

    @lru_cache(maxsize=1)
    def __get_youngam(self, **kwargs) -> Optional[dict]:
        """
        获取每日一言，缓存24小时
        """
        # 1. 获取前十天的图文id数组集合 data 数组中的第一项是今天的图文id，最后一项是10天前的图文id。
        res = RequestUtils().get_res("http://v3.wufazhuce.com:8000/api/onelist/idlist")
        if res:
            data_id = res.json().get("data")[0]
            # 2. 根据id获取某一天的图文列表
            res2 = RequestUtils().get_res(f"http://v3.wufazhuce.com:8000/api/onelist/{data_id}/0")
            if res2:
                content_list = res2.json().get("data", {}).get("content_list")
                content = next((item for item in content_list if item.get("category") == "0"), None)
                if content:
                    return {
                        "src": content.get("img_url"),
                        "text": content.get("forward"),
                        "year": content.get("post_date")[:4],
                        "month": content.get("post_date")[5:7],
                        "day": content.get("post_date")[8:10]
                    }
        return {}

    def get_dashboard(self, key: str = None, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
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
        if self._size == "mini":
            cols = {
                "cols": 12,
                "md": 4
            }
            height = 160
        elif self._size == "small":
            cols = {
                "cols": 12,
                "md": 6
            }
            height = 262
        elif self._size == "medium":
            cols = {
                "cols": 12,
                "md": 8
            }
            height = 335
        else:
            cols = {
                "cols": 12,
                "md": 12
            }
            height = 500
        # 全局配置
        attrs = {
            "border": False
        }
        # 获取流行越势数据
        data = self.__get_youngam(today=datetime.now().strftime("%Y-%m-%d"))
        if not data:
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
                            'component': 'VImg',
                            'props': {
                                'src': data.get('src'),
                                'cover': True,
                                'height': height
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
                                                'class': 'mb-1 text-white text-shadow text-xl line-clamp-4 overflow-hidden text-ellipsis ...'
                                            },
                                            'html': data.get('text'),
                                        },
                                        {
                                            'component': 'span',
                                            'props': {
                                                'class': 'text-right text-shadow line-clamp-2 overflow-hidden text-ellipsis ...'
                                            },
                                            'text': f"{data.get('year')}年{data.get('month')}月{data.get('day')}日",
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }]

        return cols, attrs, elements

    def get_state(self) -> bool:
        return self._enable

    def stop_service(self):
        pass
