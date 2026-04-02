from typing import Any, List, Dict, Tuple

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class AppPushMsg(_PluginBase):
    # 插件名称
    plugin_name = "App推送消息通知"
    # 插件描述
    plugin_desc = "支持使用 App Push 接口发送消息通知。"
    # 插件图标
    plugin_icon = "WxPusherMsg_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "Codex"
    # 作者主页
    author_url = "https://github.com/openai"
    # 插件配置项ID前缀
    plugin_config_prefix = "apppushmsg_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _token = None
    _msgtypes = []

    _api_url = "http://106.14.89.6/api/push"
    _api_key = "pPfr3wS97oviEGT111"

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._token = config.get("token")
            self._msgtypes = config.get("msgtypes") or []

    def get_state(self) -> bool:
        return bool(self._enabled and self._token)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/run",
            "endpoint": self.run_once,
            "methods": ["GET"],
            "summary": "发送测试消息",
            "description": "发送一条本地测试通知"
        }]

    def run_once(self) -> Dict[str, Any]:
        success, message = self._send_message(
            title="测试消息",
            content="这是一条本地测试通知"
        )
        return {
            "code": 0 if success else 500,
            "msg": message
        }

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        msg_type_options = []
        for item in NotificationType:
            msg_type_options.append({
                "title": item.value,
                "value": item.name
            })

        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 8
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "token",
                                            "label": "App Push Token",
                                            "placeholder": "请输入推送 token"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 4,
                                    "class": "d-flex align-end"
                                },
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "block": True,
                                            "color": "primary",
                                            "variant": "tonal"
                                        },
                                        "text": "发送测试消息",
                                        "events": {
                                            "click": {
                                                "api": "plugin/AppPushMsg/run",
                                                "method": "get",
                                                "params": {
                                                    "apikey": settings.API_TOKEN
                                                }
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "multiple": True,
                                            "chips": True,
                                            "model": "msgtypes",
                                            "label": "消息类型",
                                            "items": msg_type_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "请先保存 token，再点击测试按钮。测试按钮会使用已保存的配置发送消息。"
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
            "token": "",
            "msgtypes": []
        }

    def get_page(self) -> List[dict]:
        return [
            {
                "component": "VCard",
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "App Push 测试"
                    },
                    {
                        "component": "VCardText",
                        "text": "请先在配置页保存 token，然后点击下方按钮发送一条测试消息。"
                    },
                    {
                        "component": "VCardActions",
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "primary",
                                    "variant": "tonal",
                                    "disabled": not bool(self._token)
                                },
                                "text": "发送测试消息",
                                "events": {
                                    "click": {
                                        "api": "plugin/AppPushMsg/run",
                                        "method": "get",
                                        "params": {
                                            "apikey": settings.API_TOKEN
                                        }
                                    }
                                }
                            }
                        ]
                    }
                ]
            }
        ]

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event):
        if not self.get_state() or not event.event_data:
            return

        msg_body = event.event_data
        channel = msg_body.get("channel")
        if channel:
            return

        msg_type: NotificationType = msg_body.get("type")
        if msg_type and self._msgtypes and msg_type.name not in self._msgtypes:
            logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
            return

        title, content = self._build_message(msg_body)
        if not title and not content:
            logger.warn("标题和内容不能同时为空")
            return

        success, message = self._send_message(title=title, content=content)
        if success:
            logger.info("App Push消息发送成功")
        else:
            logger.warn(f"App Push消息发送失败：{message}")

    @staticmethod
    def _build_message(msg_body: Dict[str, Any]) -> Tuple[str, str]:
        title = str(msg_body.get("title") or "").strip()
        content = str(msg_body.get("text") or msg_body.get("summary") or "").strip()
        image = str(msg_body.get("image") or "").strip()

        if image:
            content = f"{content}\n\n图片：{image}" if content else f"图片：{image}"

        if not title:
            title = content[:50] if content else "MoviePilot 消息通知"
        if not content:
            content = title

        return title, content

    def _send_message(self, title: str, content: str) -> Tuple[bool, str]:
        if not self._token:
            return False, "请先配置 token 并保存"

        payload = {
            "token": self._token,
            "title": title or "MoviePilot 消息通知",
            "content": content or title or "MoviePilot 消息通知"
        }

        try:
            res = RequestUtils(
                content_type="application/json",
                headers={"X-API-Key": self._api_key}
            ).post_res(self._api_url, json=payload)

            if res is None:
                return False, "未获取到接口返回信息"

            if 200 <= res.status_code < 300:
                try:
                    ret_json = res.json()
                except Exception:
                    return True, "消息发送成功"

                if isinstance(ret_json, dict):
                    code = ret_json.get("code")
                    success = ret_json.get("success")
                    message = ret_json.get("message") or ret_json.get("msg") or "消息发送成功"

                    if success is False:
                        return False, str(message)

                    if code not in (None, 0, 200, "0", "200"):
                        return False, str(message)

                    return True, str(message)

                return True, "消息发送成功"

            return False, f"HTTP {res.status_code}: {res.reason}"
        except Exception as err:
            logger.error(f"App Push消息发送失败：{err}")
            return False, str(err)

    def stop_service(self):
        pass
