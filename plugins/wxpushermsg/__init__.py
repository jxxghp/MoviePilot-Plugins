from typing import Any, List, Dict, Tuple, Optional

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils

class WxPusherMsg(_PluginBase):
    """
    WxPusher 消息通知插件
    支持微信(暂时停止)、APP(无后台)、浏览器插件通知。
    """
    plugin_name: str = "WxPusher消息推送"
    plugin_desc: str = "支持微信(暂时停止)、APP(无后台)、浏览器插件通知。"
    plugin_icon: str = "WxPusherMsg_A.png"
    plugin_version: str = "1.0"
    plugin_author: str = "zhjay"
    author_url: str = "https://github.com/Jie795"
    plugin_config_prefix: str = "wxpushermsg_"
    plugin_order: int = 30
    auth_level: int = 1
    api_url: str = "https://wxpusher.zjiecode.com/api/send/message"
    default_content_type: int = 1

    # 插件配置属性
    _enabled: bool = False
    _appToken: Optional[str] = None
    _contentType: int = default_content_type
    _uids: Optional[str] = None
    _topicIds: Optional[str] = None
    _msgtypes: List[str] = []
    _onlyonce: bool = False

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """
        插件初始化，加载配置。
        """
        if config:
            self._enabled = config.get("enabled", False)
            self._appToken = config.get("appToken")
            self._contentType = config.get("contentType", self.default_content_type)
            self._uids = config.get("uids")
            self._topicIds = config.get("topicIds")
            self._msgtypes = config.get("msgtypes") or []
            self._onlyonce = config.get("onlyonce", False)
            # 立即运行一次逻辑
            if self._onlyonce:
                try:
                    event = Event(EventType.NoticeMessage, {
                        "type": NotificationType.SiteMessage,
                        "title": "测试消息",
                        "text": "这是一条测试消息，用于验证WxPusher消息发送功能是否正常。",
                        "summary": "测试消息",
                        "force_send": True
                    })
                    self.send(event)
                except Exception as e:
                    logger.error(f"WxPusher立即运行一次失败：{str(e)}")
                # 关闭一次性开关并保存配置
                self._onlyonce = False
                if hasattr(self, 'update_config'):
                    self.update_config({
                        "enabled": self._enabled,
                        "appToken": self._appToken,
                        "contentType": self._contentType,
                        "uids": self._uids,
                        "topicIds": self._topicIds,
                        "msgtypes": self._msgtypes,
                        "onlyonce": False
                    })

    def get_state(self) -> bool:
        """
        获取插件当前启用状态。
        """
        return bool(self._enabled and self._appToken)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        获取插件命令定义。
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API定义。
        """
        return [{
            "path": "/run",
            "endpoint": self.run_once,
            "methods": ["GET"],
            "summary": "运行一次",
            "description": "运行一次WxPusher消息发送"
        }]

    def run_once(self) -> Dict[str, Any]:
        """
        运行一次WxPusher消息发送测试。
        """
        if not self.get_state():
            return {"code": 500, "msg": "插件未启用或未配置"}
        try:
            event = Event(EventType.NoticeMessage, {
                "type": NotificationType.SiteMessage,
                "title": "测试消息",
                "text": "这是一条测试消息，用于验证WxPusher消息发送功能是否正常。",
                "summary": "测试消息",
                "force_send": True
            })
            self.send(event)
            return {"code": 0, "msg": "运行成功"}
        except Exception as e:
            logger.error(f"运行失败：{str(e)}")
            return {"code": 500, "msg": f"运行失败：{str(e)}"}

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        获取插件配置表单及默认值。
        """
        msg_type_options = [
            {"title": item.value, "value": item.name}
            for item in NotificationType
        ]
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用插件'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'onlyonce', 'label': '立即运行一次'}
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {'model': 'appToken', 'label': 'WxPusher应用Token', 'placeholder': 'AT_xxx'}
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'uids',
                                            'label': '用户UID(逗号分隔)',
                                            'placeholder': 'UID1,UID2',
                                            'hint': '用户UID和主题ID不能同时为空，至少填写一项'
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'topicIds',
                                            'label': '主题ID(逗号分隔)',
                                            'placeholder': '123,456',
                                            'hint': '用户UID和主题ID不能同时为空，至少填写一项'
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'model': 'msgtypes',
                                            'label': '消息类型',
                                            'items': msg_type_options
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'contentType',
                                            'label': '内容类型',
                                            'items': [
                                                {'title': '文字', 'value': 1},
                                                {'title': 'HTML', 'value': 2},
                                                {'title': 'Markdown', 'value': 3}
                                            ]
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
            'appToken': '',
            'uids': '',
            'topicIds': '',
            'contentType': self.default_content_type,
            'msgtypes': [],
            'onlyonce': False
        }

    @staticmethod
    def get_page() -> List[dict]:
        """
        获取插件页面定义。
        """
        pass

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event) -> None:
        """
        发送WxPusher消息。
        """
        if not self.get_state():
            return
        if not event or not event.event_data:
            return
        msg_body = event.event_data
        channel = msg_body.get("channel")
        if channel:
            return
        msg_type: Optional[NotificationType] = msg_body.get("type")
        title: Optional[str] = msg_body.get("title")
        text: Optional[str] = msg_body.get("text")
        summary: str = msg_body.get("summary", "")
        content_type: int = msg_body.get("contentType", self._contentType)
        uids: Optional[str] = msg_body.get("uids", self._uids)
        topic_ids: Optional[str] = msg_body.get("topicIds", self._topicIds)
        if not title and not text:
            logger.warn("标题和内容不能同时为空")
            return
        # 立即运行一次时不做类型判断
        if not msg_body.get("force_send"):
            if msg_type and (not self._msgtypes or msg_type.name not in self._msgtypes):
                logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
                return
        try:
            payload = {
                "appToken": self._appToken,
                "content": text or title,
                "summary": summary or title,
                "contentType": content_type,
            }
            if uids:
                payload["uids"] = [i.strip() for i in uids.split(",") if i.strip()]
            if topic_ids:
                payload["topicIds"] = [i.strip() for i in topic_ids.split(",") if i.strip()]
            res = RequestUtils(content_type="application/json").post_res(self.api_url, json=payload)
            if res and res.status_code == 200:
                ret_json = res.json()
                code = ret_json.get('code')
                msg = ret_json.get('msg')
                if code == 1000:
                    logger.info("WxPusher消息发送成功")
                else:
                    logger.warn(f"WxPusher消息发送失败，错误码：{code}，原因：{msg}")
            elif res is not None:
                logger.warn(f"WxPusher消息发送失败，HTTP错误码：{res.status_code}，原因：{res.reason}")
            else:
                logger.warn("WxPusher消息发送失败，未获取到返回信息")
        except Exception as e:
            logger.error(f"WxPusher消息发送异常，{str(e)}")

    @staticmethod
    def stop_service() -> None:
        """
        停止插件服务（如需实现）。
        """
        # 如需实现停止服务逻辑，补充此方法
        pass