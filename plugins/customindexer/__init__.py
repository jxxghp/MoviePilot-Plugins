import base64
import json
from typing import List, Tuple, Dict, Any

from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase


class CustomIndexer(_PluginBase):
    # 插件名称
    plugin_name = "自定义索引站点"
    # 插件描述
    plugin_desc = "修改或扩展内建索引器支持的站点。"
    # 插件图标
    plugin_icon = "spider.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "customindexer_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _enabled = False
    _confstr = ""

    def init_plugin(self, config: dict = None):

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._confstr = config.get("confstr") or ""
            if self._enabled and self._confstr:
                # 配置生效
                indexers = self._confstr.split("\n")
                for indexer in indexers:
                    if not indexer:
                        continue
                    try:
                        [domain, jsonstr] = indexer.split("|")
                        if not domain or not jsonstr:
                            continue
                        jsonstr = base64.b64decode(jsonstr).decode('utf-8')
                        SitesHelper().add_indexer(domain, json.loads(jsonstr))
                    except Exception as err:
                        logger.error(f"自定义索引站点配置错误：{err}")
                        self.systemmessage.put(f"自定义索引站点配置错误：{err}", title="自定义索引站点")
                        continue

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
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'confstr',
                                            'label': '站点索引配置',
                                            'rows': 10,
                                            'placeholder': '一行一个站点，配置格式：域名|配置json的base64编码（utf-8）'
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
                                            'text': '域名只取后两段，如：www.baidu.com，只需填写baidu.com；索引配置Json需使用utf-8进行base64编码；如站点域名已被内建索引器支持，则会覆盖内建配置；索引配置的格式请参考README。'
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
            "hosts": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
