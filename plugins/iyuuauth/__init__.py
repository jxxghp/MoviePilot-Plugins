import os
from typing import Any, List, Dict, Tuple

from app.log import logger
from app.plugins import _PluginBase
from app.plugins.iyuuauth.iyuu_helper import IyuuHelper


class IyuuAuth(_PluginBase):
    # 插件名称
    plugin_name = "IYUU站点绑定"
    # 插件描述
    plugin_desc = "为IYUU账号绑定认证站点，以便用于用户认证和辅种。"
    # 插件图标
    plugin_icon = "Iyuu_A.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "iyuuauth_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    iyuu = None
    _enabled = False
    _token = None
    _site = None
    _passkey = None
    _uid = None

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._token = config.get("token") or os.environ.get("IYUU_SIGN")
            self._site = config.get("site")
            self._passkey = config.get("passkey")
            self._uid = config.get("uid")
            if self._token:
                self.iyuu = IyuuHelper(self._token)
            # 开始绑定站点
            if self._enabled:
                if not self._token or not self._passkey or not self._uid:
                    logger.warn("IYUU站点绑定插件配置不完整，请检查配置！")
                    self.systemmessage.put("IYUU站点绑定插件配置不完整，请检查配置！", title="IYUU站点绑定")
                    return
                state, message = self.iyuu.bind_site(site=self._site, passkey=self._passkey, uid=self._uid)
                if not state:
                    logger.warn(f"IYUU站点绑定失败，错误信息：{message}")
                    self.systemmessage.put(f"IYUU站点绑定失败，错误信息：{message}", title="IYUU站点绑定")
                else:
                    logger.info("IYUU站点绑定成功！")
                    self.systemmessage.put("IYUU站点绑定成功！", title="IYUU站点绑定")
                    self._enabled = False
                    self.update_config({
                        "enabled": self._enabled,
                        "token": self._token,
                        "site": self._site,
                        "passkey": self._passkey,
                        "uid": self._uid
                    })

    def get_state(self) -> bool:
        return self._enabled and (True if self._token else False)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 编历 NotificationType 枚举，生成消息类型选项
        SiteOptions = []
        if self.iyuu:
            for item in self.iyuu.get_auth_sites() or []:
                SiteOptions.append({
                    "title": item.get("site"),
                    "value": item.get("site")
                })
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'token',
                                            'label': 'IYUU令牌',
                                            'placeholder': 'IYUUxxx',
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
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'site',
                                            'label': '绑定站点',
                                            'items': SiteOptions
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'passkey',
                                            'label': '站点密钥',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'uid',
                                            'label': '用户UID',
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
                                            'text': '如果设置了`IYUU_SIGN`环境变量则会自动读取，否则需要先填写 IYUU令牌。需要先保存IYUU令牌后，重新打开插件才能选择绑定站点。'
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
            "token": os.environ.get("IYUU_SIGN")
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
