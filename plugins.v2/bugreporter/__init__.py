from typing import List, Tuple, Dict, Any

import sentry_sdk

from app.plugins import _PluginBase


class BugReporter(_PluginBase):
    # 插件名称
    plugin_name = "Bug反馈"
    # 插件描述
    plugin_desc = "自动上报异常，协助开发者发现和解决问题。"
    # 插件图标
    plugin_icon = "Alist_encrypt_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "bugreporter_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False

    def init_plugin(self, config: dict = None):
        self._enable = config.get("enable")
        if self._enable:
            sentry_sdk.init("https://88da01ad33b4423cb0380620de53efa8@glitchtip.movie-pilot.org/1")

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
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '注意：开启插件即代表你同意将部分异常信息自动发送给开发者，以帮助改进软件；如果你不希望自动发送任何数据，请关闭或卸载此插件；仅上报系统异常信息，不会包含任何个人隐私信息或敏感数据；异常信息采集为使用开源项目解决方案：GlitchTip。',
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
        pass

    def get_state(self) -> bool:
        return self._enable

    def stop_service(self):
        pass
