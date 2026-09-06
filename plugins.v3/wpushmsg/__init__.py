"""WPUSH 消息通知插件。"""

from typing import Any, Dict, List, Optional, Tuple

from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.network import RequestUtils

# WPUSH Open API：https://wpush.cn/docs
WPUSH_SEND_URL = "https://api.wpush.cn/api/v1/send"
WPUSH_CHANNELS = [
    {"title": "微信公众号", "value": "wechat"},
    {"title": "App 推送", "value": "app"},
    {"title": "短信", "value": "sms"},
    {"title": "邮件", "value": "mail"},
    {"title": "Webhook", "value": "webhook"},
    {"title": "钉钉", "value": "dingtalk"},
    {"title": "飞书", "value": "feishu"},
    {"title": "企业微信", "value": "wechat_work"},
    {"title": "ClawBot", "value": "clawbot"},
    {"title": "QQBot", "value": "qqbot"},
]


class WPushMsg(_PluginBase):
    """WPUSH 多渠道消息通知插件。

    监听 ``EventType.NoticeMessage``，在未指定专用通知渠道时通过 WPUSH
    Open API 推送消息。接口成功仅以响应 JSON ``code === 0`` 判定，
    不能仅凭 HTTP 2xx。
    """

    # 插件名称
    plugin_name = "WPUSH消息推送"
    # 插件描述
    plugin_desc = "支持使用 WPUSH 发送消息通知（多渠道：微信/App/短信/邮件/钉钉/飞书等）。"
    # 插件图标
    plugin_icon = "WPush_A.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "Alone88"
    # 作者主页
    author_url = "https://github.com/anhao"
    # 插件配置项ID前缀
    plugin_config_prefix = "wpushmsg_"
    # 加载顺序
    plugin_order = 31
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _apikey: Optional[str] = None
    _channel = "wechat"
    _topic_code: Optional[str] = None
    _msgtypes: List[str] = []

    def init_plugin(self, config: dict = None) -> None:
        """根据插件配置初始化运行状态。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._apikey = (config.get("apikey") or "").strip() or None
        self._channel = (config.get("channel") or "wechat").strip() or "wechat"
        self._topic_code = (config.get("topic_code") or "").strip() or None
        self._msgtypes = config.get("msgtypes") or []

    def get_state(self) -> bool:
        """获取插件启用状态（需启用且已配置 apikey）。"""
        return self._enabled and bool(self._apikey)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """当前插件不注册后端 API。"""
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面：启用开关、API Key、渠道、主题编码与消息类型。"""
        msg_type_options = [
            {"title": item.value, "value": item.name}
            for item in NotificationType
        ]
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "apikey",
                                            "label": "WPUSH API Key",
                                            "placeholder": "WPUSHxxxx",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "channel",
                                            "label": "推送渠道",
                                            "items": WPUSH_CHANNELS,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "topic_code",
                                            "label": "主题编码（可选）",
                                            "placeholder": "topic_code，可选",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "multiple": True,
                                            "chips": True,
                                            "model": "msgtypes",
                                            "label": "消息类型",
                                            "items": msg_type_options,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": (
                                                "请在 https://wpush.cn/settings 获取 API Key，"
                                                "并在 https://wpush.cn/channels 绑定至少一个推送渠道。"
                                                "接口成功以响应 JSON code===0 判定（并非仅 HTTP 2xx）。"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "apikey": "",
            "channel": "wechat",
            "topic_code": "",
            "msgtypes": [],
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回插件详情页。"""
        return [
            {
                "component": "VCard",
                "props": {"class": "mb-4", "variant": "tonal"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": "d-flex align-center"},
                        "content": [
                            {
                                "component": "VIcon",
                                "props": {
                                    "icon": "mdi-bell-ring-outline",
                                    "class": "mr-2",
                                },
                            },
                            "插件介绍",
                        ],
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "text": (
                                        "WPUSH 消息推送插件通过 https://api.wpush.cn/api/v1/send "
                                        "发送通知，支持微信、App、短信、邮件、钉钉、飞书等渠道。"
                                        "成功判定以接口返回 JSON 的 code===0 为准。"
                                    ),
                                },
                            }
                        ],
                    },
                ],
            }
        ]

    def _send_wpush(self, title: str, content: str) -> bool:
        """调用 WPUSH Open API 发送消息。

        :param title: 通知标题
        :param content: 通知正文
        :return: 是否发送成功（仅 JSON code===0）
        """
        if not self._apikey:
            logger.warn("WPUSH 消息发送失败：未配置 API Key")
            return False

        payload: Dict[str, Any] = {
            "apikey": self._apikey,
            "title": title or content,
            "content": content or title,
            "channel": self._channel or "wechat",
        }
        if self._topic_code:
            payload["topic_code"] = self._topic_code

        # 凭证 POST 禁用重定向，避免 apikey 随跳转泄露；日志不输出 apikey
        res = RequestUtils(content_type="application/json").post_res(
            WPUSH_SEND_URL,
            json=payload,
            allow_redirects=False,
        )
        if res is None:
            logger.warn("WPUSH 消息发送失败，未获取到返回信息")
            return False
        if res.status_code != 200:
            logger.warn(
                f"WPUSH 消息发送失败，HTTP 状态码：{res.status_code}，原因：{res.reason}"
            )
            return False

        try:
            ret_json = res.json()
        except Exception as err:
            logger.warn(f"WPUSH 消息发送失败，响应非 JSON：{err}")
            return False

        code = ret_json.get("code")
        # WPUSH 成功仅当 code === 0（不同于 PushPlus 的 200）
        if code == 0:
            logger.info("WPUSH 消息发送成功")
            return True

        message = ret_json.get("message") or ret_json.get("msg") or "未知错误"
        logger.warn(f"WPUSH 消息发送失败，接口 code={code}，原因：{message}")
        return False

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event) -> None:
        """消息发送事件：未指定专用渠道时走 WPUSH。"""
        if not self.get_state():
            return

        if not event.event_data:
            return

        msg_body = event.event_data
        # 已指定专用通知渠道时不处理
        channel = msg_body.get("channel")
        if channel:
            return

        msg_type: NotificationType = msg_body.get("type")
        title = msg_body.get("title")
        text = msg_body.get("text")

        if not title and not text:
            logger.warn("标题和内容不能同时为空")
            return

        if msg_type and self._msgtypes and msg_type.name not in self._msgtypes:
            logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
            return

        try:
            self._send_wpush(title or "", text or "")
        except Exception as msg_e:
            logger.error(f"WPUSH 消息发送异常，{str(msg_e)}")

    def stop_service(self) -> None:
        """退出插件。"""
        return None
