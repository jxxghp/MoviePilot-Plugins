import json
from typing import Any, List, Dict, Optional, Tuple
from pathlib import Path

from app.core.event import eventmanager, Event
from app.plugins import _PluginBase
from app.log import logger
from app.schemas.types import ChainEventType
from app.schemas.event import ResourceDownloadEventData


class InterceptDownload(_PluginBase):
    # 插件名称
    plugin_name = "用户下载拦截"
    # 插件描述
    plugin_desc = "拦截用户下载资源(自用，可能有bug)"
    # 插件图标
    plugin_icon = ""
    # 插件版本
    plugin_version = "0.1"
    # 插件作者
    plugin_author = "Sunhang"
    # 作者主页
    author_url = "https://github.com/2662419405"
    # 插件配置项ID前缀
    plugin_config_prefix = "interceptdownload"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _user_name = {}
    _enable_invert = False

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        if config:
            self._enabled = config.get("enabled", False)
            self._enable_invert = config.get("_enable_invert", False)

            # 解析用户路径配置文本
            user_name_text = config.get("user_name_text", "")
            self._user_name = user_name_text.strip().split('\n')

    def get_state(self) -> bool:
        return self._enabled

    @eventmanager.register(ChainEventType.ResourceDownload)
    def intercept_download(self, event: Event) -> Event:
        """
        拦截资源下载事件，修改下载路径
        """
        if not self._enabled:
            return event

        if not event or not event.event_data:
            return event

        event_data: ResourceDownloadEventData = event.event_data

        # 获取用户信息
        options = event_data.options or {}
        username = options.get("username")
        userid = options.get("userid")
        
        if username in self._user_name or userid in self._user_name:
            
            is_paused = True
            
            if self._enable_invert:
                is_paused = False
            
            event_data.options["is_paused"] = is_paused
            logger.info(f"[用户目录配置] {'拦截' if is_paused else '未拦截'}下载请求 - 暂停下载")
            return event
        
        else:
            logger.info(f"[用户目录配置] 未拦截下载请求 - 用户: {username}, ID: {userid}")

        return event

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
                                            'model': '_enable_invert',
                                            'label': '是否反选',
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
                                            'model': 'user_name_text',
                                            'label': '用户下载配置',
                                            'placeholder': '示例\n\nSunhang\nadmin\n',
                                            'rows': 10
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
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '使用说明：\n1. 插件会拦截所有下载请求，根据用户身份设置来判断是否自动下载 2:每行输入一个用户名，也可以输入用户id 3:勾选反选后，输入的用户信息为白名单，不会被拦截'
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
            "_enable_invert": False,
            "user_name_text": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass