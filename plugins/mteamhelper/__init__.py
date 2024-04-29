import os
import re
from datetime import datetime, timedelta
from threading import Event
from typing import Any, List, Dict, Tuple, Optional

from app.log import logger
from app.plugins import _PluginBase

class MTeamHelper(_PluginBase):
    # 插件名称
    plugin_name = "馒头辅助工具"
    # 插件描述
    plugin_desc = "用于解决MP不支持馒头新架构更新导致的一些异常。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/goo4it/MoviePilot-Plugins/main/icons/m-team.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "goo4it"
    # 作者主页
    author_url = "https://github.com/goo4it/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "mteamhelper_"
    # 加载顺序
    plugin_order = 17
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler = None
    # 开关
    _enabled = False
    _apikey = ""

    def init_plugin(self, config: dict = None):
        if not config:
            return
        logger.info(f"正在应用馒头配置：{config}")
        self._enabled = config.get("enabled")
        self._apikey = config.get("apiKey")
        if not self._enabled:
            return

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
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
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "apiKey",
                                            "label": "APIKEY"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "apiKey": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
