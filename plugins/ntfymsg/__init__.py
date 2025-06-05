import base64
import json
import requests

from typing import Any, List, Dict, Tuple

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class NtfyClient:

    def send(self, message: str, title: str = None, format_as_markdown: bool = False):
        headers = {
            "Title": title.encode(encoding='utf-8'),
            "Markdown": "true" if format_as_markdown else "false",
            "Icon": "https://movie-pilot.org/images/logo.png",
        }

        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        elif self._user and self._password:
            authStr = self._user + ":" + self._password
            headers["Authorization"] = "Basic " + base64.b64encode(authStr.encode('utf-8')).decode('utf-8')

        if self._actions:
            headers["Actions"] = self._actions.encode('utf-8')

        response = json.loads(
            requests.post(url=self.url, data=message.encode(encoding='utf-8'), headers=headers).text
        )
        return response

    def __init__(
            self,
            topic: str,
            server: str = "https://ntfy.sh",
            user: str = "",
            password: str = "",
            token: str = "",
            actions: str = "",
    ):
        self._server = server
        self._topic = topic
        self.__set_url(server, topic)
        self._user = user
        self._password = password
        self._token = token
        self._actions = actions

    def __set_url(self, server, topic):
        self.url = server.strip("/") + "/" + topic


class NtfyMsg(_PluginBase):
    # 插件名称
    plugin_name = "ntfy 消息通知"
    # 插件描述
    plugin_desc = "支持使用 ntfy 发送消息通知。"
    # 插件图标
    plugin_icon = "Ntfy_A.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "lethargicScribe"
    # 作者主页
    author_url = "https://github.com/lethargicScribe"
    # 插件配置项ID前缀
    plugin_config_prefix = "ntfymsg_"
    # 加载顺序
    plugin_order = 26
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _server = None
    _topic = None
    _user = None
    _password = None
    _token = None
    _actions = None
    _msgtypes = []

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._msgtypes = config.get("msgtypes") or []
            self._server = config.get("server")
            self._topic = config.get("topic")
            self._user = config.get("user")
            self._password = config.get("password")
            self._token = config.get("token")
            self._actions = config.get("actions")

    def get_state(self) -> bool:
        return self._enabled and (True if self._server and self._topic else False)

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
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.name
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
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'server',
                                            'label': '服务器',
                                            'placeholder': 'https://ntfy.sh',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'topic',
                                            'label': '主题',
                                            'placeholder': 'MoviePilot',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'user',
                                            'label': '用户名',
                                            'placeholder': 'ntfyuser',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'password',
                                            'label': '密码',
                                            'placeholder': 'ntfypassword',
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'token',
                                            'label': '访问令牌',
                                            'placeholder': 'ntfytoken',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'actions',
                                            'label': '用户动作',
                                            'placeholder': 'ntfyactions',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'model': 'msgtypes',
                                            'label': '消息类型',
                                            'items': MsgTypeOptions
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
                                            'text': '用户或Token创建参考：https://docs.ntfy.sh/config/#access-control'
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
                                            'text': '用户动作创建参考：https://docs.ntfy.sh/publish/?h=action#using-a-header'
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
            'msgtypes': [],
            'server': 'https://ntfy.sh',
            'topic': 'MoviePilot',
            'user': '',
            'password': '',
            'token': '',
            'actions': '',
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event):
        """
        消息发送事件
        """
        if not self.get_state():
            return

        if not event.event_data:
            return

        msg_body = event.event_data
        # 渠道
        channel = msg_body.get("channel")
        if channel:
            return
        # 类型
        msg_type: NotificationType = msg_body.get("type")
        # 标题
        title = msg_body.get("title")
        # 文本
        text = msg_body.get("text")

        if not title and not text:
            logger.warn("标题和内容不能同时为空")
            return

        if (msg_type and self._msgtypes
                and msg_type.name not in self._msgtypes):
            logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
            return

        try:
            if not self._server or not self._topic:
                return False, "参数未配置"
            ntfy = NtfyClient(
                server=self._server, topic=self._topic,
                user=self._user, password=self._password,
                token=self._token, actions=self._actions
            )
            ntfy.send(title=title, message=text, format_as_markdown=True)

        except Exception as msg_e:
            logger.error(f"ntfy消息发送失败，错误信息：{str(msg_e)}")

    def stop_service(self):
        """
        退出插件
        """
        pass
