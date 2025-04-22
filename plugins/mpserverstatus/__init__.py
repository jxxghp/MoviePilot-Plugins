import re
import time
from typing import List, Tuple, Dict, Any, Optional

from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils


class MPServerStatus(_PluginBase):
    # 插件名称
    plugin_name = "MoviePilot服务监控"
    # 插件描述
    plugin_desc = "在仪表板中实时显示MoviePilot公共服务器状态。"
    # 插件图标
    plugin_icon = "Duplicati_A.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "MPServer_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False
    _server_base = "https://movie-pilot.org/status"

    def init_plugin(self, config: dict = None):
        self._enable = config.get("enable") if config.get("enable") else False

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
                    }
                ]
            }
        ], {
            "enable": self._enable,
        }

    def get_page(self) -> List[dict]:
        """
        获取插件页面
        """
        if not self._enable:
            return [
                {
                    'component': 'div',
                    'text': '插件未启用',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        _, _, elements = self.get_dashboard()
        return elements

    def get_dashboard(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
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
        cols = {
            "cols": 12,
            "md": 8
        }
        # 全局配置
        attrs = {
            "refresh": 10
        }
        # 读取服务器文本
        start_time = time.time()
        logger.info(f"请求服务器状态 {self._server_base}...")
        res = RequestUtils().get_res(self._server_base)
        seconds = time.time() - start_time
        logger.info(f"请求耗时：{seconds}秒")
        if not res:
            logger.warn(f"请求服务器状态失败：{res.status_code if res is not None else '网络错误'}")
            elements = [
                {
                    'component': 'div',
                    'text': '无法连接服务器',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        else:
            """
            Active connections: 62 
            server accepts handled requests
             468843 468843 1368256 
            Reading: 0 Writing: 1 Waiting: 61 
            """
            status_lines = res.text.strip().split('\n')
            active_connections = int(status_lines[0].split(':')[1].strip())
            accepts, handled, requests = map(int, status_lines[2].split())
            reading, writing, waiting = map(int, re.findall(r'\d+', status_lines[3]))
            elements = [
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 6,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VCard',
                                    'props': {
                                        'variant': 'tonal',
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'd-flex align-center',
                                            },
                                            'content': [
                                                {
                                                    'component': 'div',
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-caption'
                                                            },
                                                            'text': '连接耗时'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-center flex-wrap'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'props': {
                                                                        'class': 'text-h6'
                                                                    },
                                                                    'text': f"{seconds:.2f} 秒"
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                },
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 6,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VCard',
                                    'props': {
                                        'variant': 'tonal',
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'd-flex align-center',
                                            },
                                            'content': [
                                                {
                                                    'component': 'div',
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-caption'
                                                            },
                                                            'text': '活跃连接'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-center flex-wrap'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'props': {
                                                                        'class': 'text-h6'
                                                                    },
                                                                    'text': active_connections
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                },
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 6,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VCard',
                                    'props': {
                                        'variant': 'tonal',
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'd-flex align-center',
                                            },
                                            'content': [
                                                {
                                                    'component': 'div',
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-caption'
                                                            },
                                                            'text': '等待连接'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-center flex-wrap'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'props': {
                                                                        'class': 'text-h6'
                                                                    },
                                                                    'text': waiting
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                },
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 6,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VCard',
                                    'props': {
                                        'variant': 'tonal',
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'd-flex align-center',
                                            },
                                            'content': [
                                                {
                                                    'component': 'div',
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-caption'
                                                            },
                                                            'text': '处理中连接'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-center flex-wrap'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'props': {
                                                                        'class': 'text-h6'
                                                                    },
                                                                    'text': reading + writing
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                },
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 6,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VCard',
                                    'props': {
                                        'variant': 'tonal',
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'd-flex align-center',
                                            },
                                            'content': [
                                                {
                                                    'component': 'div',
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-caption'
                                                            },
                                                            'text': '总请求数'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-center flex-wrap'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'props': {
                                                                        'class': 'text-h6'
                                                                    },
                                                                    'text': f"{requests:,}"
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                },
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 6,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VCard',
                                    'props': {
                                        'variant': 'tonal',
                                    },
                                    'content': [
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'd-flex align-center',
                                            },
                                            'content': [
                                                {
                                                    'component': 'div',
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-caption'
                                                            },
                                                            'text': '总连接数'
                                                        },
                                                        {
                                                            'component': 'div',
                                                            'props': {
                                                                'class': 'd-flex align-center flex-wrap'
                                                            },
                                                            'content': [
                                                                {
                                                                    'component': 'span',
                                                                    'props': {
                                                                        'class': 'text-h6'
                                                                    },
                                                                    'text': f"{accepts:,}"
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                },
                            ]
                        }
                    ]
                }]

        return cols, attrs, elements

    def get_state(self) -> bool:
        return self._enable

    def stop_service(self):
        pass
