import asyncio
import websockets
import json
import struct
from typing import Any, List, Dict, Tuple

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType

class MqttClient:
    def __init__(
            self,
            topic: str,
            server: str = "ws://mqtt.example.com:8083/mqtt",
            username: str = "",
            password: str = "",
    ):
        self._server = server
        self._topic = topic
        self._username = username
        self._password = password
    def __set_url(self, server, topic):
        self.url = server.strip("/") + "/" + topic

    def _build_mqtt_connect_packet(self, client_id, keep_alive=60):
        # 构建 MQTT 连接报文
        protocol_name = b"MQTT"
        protocol_level = 4
        connect_flags = 0x02 | 0x80 | 0x40  # 设置用户名和密码标志
        payload = (
            struct.pack("!H4sBBH", len(protocol_name), protocol_name, protocol_level, connect_flags, keep_alive) +
            struct.pack("!H%dsH%dsH%ds" % (len(client_id), len(self._username), len(self._password)),
                        len(client_id), client_id.encode('utf-8'),
                        len(self._username), self._username.encode('utf-8'),
                        len(self._password), self._password.encode('utf-8'))
        )
        return b'\x10' + struct.pack('!B', len(payload)) + payload

    def _build_mqtt_publish_packet(self, topic, message):
        # 构建 MQTT 发布报文
        payload = message.encode('utf-8')
        packet = (
            struct.pack("!BBH%ds" % len(topic), 0x30, 2 + len(topic) + len(payload), len(topic), topic.encode('utf-8')) +
            payload
        )
        return packet

    async def send(self, message: str, title: str = None, format_as_markdown: bool = False):
        async with websockets.connect(self._server) as websocket:
            client_id = "mqtt_client"
            connect_packet = self._build_mqtt_connect_packet(client_id)
            await websocket.send(connect_packet)
            connack = await websocket.recv()
            print(f"收到 CONNACK 报文: {connack}")

            payload = {
                "message": message,
                "title": title,
                "markdown": format_as_markdown
            }
            payload_str = json.dumps(payload)
            publish_packet = self._build_mqtt_publish_packet(self._topic, payload_str)
            await websocket.send(publish_packet)
            print("MQTT PUBLISH 报文已发送")

            disconnect_packet = b'\xe0\x00'
            await websocket.send(disconnect_packet)
            print("MQTT DISCONNECT 报文已发送")

class MqttMsg(_PluginBase):
    # 插件名称
    plugin_name = "MQTT 消息通知"
    # 插件描述
    plugin_desc = "支持使用 MQTT 发送消息通知。"
    # 插件图标
    plugin_icon = "Mqtt_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "lethargicScribe"
    # 作者主页
    author_url = "https://github.com/lethargicScribe"
    # 插件配置项ID前缀
    plugin_config_prefix = "mqttmsg_"
    # 加载顺序
    plugin_order = 27
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _broker = None
    _port = None
    _topic = None
    _username = None
    _password = None
    _msgtypes = []

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._msgtypes = config.get("msgtypes") or []
            self._broker = config.get("broker")
            self._port = config.get("port")
            self._topic = config.get("topic")
            self._username = config.get("username")
            self._password = config.get("password")

    def get_state(self) -> bool:
        return self._enabled and (True if self._broker and self._port and self._topic else False)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
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
                                            'model': 'broker',
                                            'label': 'MQTT Broker',
                                            'placeholder': 'broker.example.com',
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
                                            'placeholder': 'example/topic',
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
                                            'model': 'username',
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
            'broker': 'broker.example.com',
            'port': 1883,
            'topic': 'example/topic',
            'username': '',
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
            if not self._broker or not self._port or not self._topic:
                return False, "参数未配置"

            mqtt_client = MqttClient(
                topic=self._topic,
                server=f"ws://{self._broker}:{self._port}/mqtt",
                username=self._username,
                password=self._password
            )
            asyncio.run(mqtt_client.send(message=text))

        except Exception as msg_e:
            logger.error(f"MQTT消息发送失败，错误信息：{str(msg_e)}")

    def stop_service(self):
        """
        退出插件
        """
        pass
