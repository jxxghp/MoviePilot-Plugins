import json
import paho.mqtt.client as mqtt

from typing import Any, List, Dict, Tuple

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class MqttClient:

    def __init__(self, server: str, port: int, topic: str, user: str = "", password: str = ""):
        self.server = server
        self.port = port
        self.topic = topic
        self.client = mqtt.Client()
        if user and password:
            self.client.username_pw_set(user, password)

    def send(self, message: str, title: str = None, format_as_markdown: bool = False):
        full_message = {
            "title": title,
            "message": message,
            "markdown": format_as_markdown
        }
        self.client.connect(self.server, self.port, 60)
        self.client.publish(self.topic, json.dumps(full_message))
        self.client.disconnect()


class MqttMsg(_PluginBase):
    # 插件名称
    plugin_name = "mqtt 消息通知"
    # 插件描述
    plugin_desc = "支持使用 MQTT 发送消息通知。"
    # 插件图标
    plugin_icon = "Mosquitto_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "blacklips"
    # 作者主页
    author_url = "https://github.com/blacklips"
    # 插件配置项ID前缀
    plugin_config_prefix = "mqttmsg_"
    # 加载顺序
    plugin_order = 26
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _server = None
    _port = None
    _topic = None
    _user = None
    _password = None
    _msgtypes = []

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._msgtypes = config.get("msgtypes") or []
            self._server = config.get("server")
            self._port = config.get("port")
            self._topic = config.get("topic")
            self._user = config.get("user")
            self._password = config.get("password")

    def get_state(self) -> bool:
        return self._enabled and (True if self._server and self._port and self._topic else False)

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
                                            'placeholder': 'mqtt.example.com',
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
                                            'model': 'port',
                                            'label': '端口',
                                            'placeholder': '1883',
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
                                            'placeholder': 'mqttuser',
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
                                            'placeholder': 'mqttpassword',
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
                ]
            }
        ], {
            "enabled": False,
            'msgtypes': [],
            'server': 'mqtt.example.com',
            'port': 1883,
            'topic': 'MoviePilot',
            'user': '',
            'password': '',
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
            if not self._server or not self._port or not self._topic:
                return False, "参数未配置"
            mqtt_client = MqttClient(server=self._server, port=self._port, topic=self._topic, user=self._user, password=self._password)
            mqtt_client.send(title=title, message=text, format_as_markdown=True)

        except Exception as msg_e:
            logger.error(f"MQTT消息发送失败，错误信息：{str(msg_e)}")

    def stop_service(self):
        """
        退出插件
        """
        pass
