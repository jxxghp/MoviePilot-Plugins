from typing import Any, List, Dict, Tuple, Optional
from urllib.parse import parse_qs

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils

class MeoWMsg(_PluginBase):
    # 插件名称
    plugin_name = "MeoW消息通知"
    # 插件描述
    plugin_desc = "支持使用MeoW发送消息通知。"
    # 插件图标
    plugin_icon = "MeoW_A.png"
    # 插件版本
    plugin_version = "1.0.1"
    # 插件作者
    plugin_author = "Licardo"
    # 作者主页
    author_url = "https://github.com/l1cardo"
    # 插件配置项ID前缀
    plugin_config_prefix = "meowmsg_"
    # 加载顺序
    plugin_order = 27
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _onlyonce = False
    _server = None
    _nickname = None
    _msgtypes = []

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._msgtypes = config.get("msgtypes") or []
            self._server = config.get("server")
            self._nickname = config.get("nickname")

        if self._onlyonce:
            logger.info(f"测试插件，立即运行一次")
            self._onlyonce = False
            self.update_config({
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "msgtypes": self._msgtypes,
                "server": self._server,
                "nickname": self._nickname
            })
            self._send("MeoW消息测试通知", "MeoW消息通知插件已启用")

    def get_state(self) -> bool:
        return self._enabled and (self._server is not None and self._nickname is not None)

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
                            },
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
                                            'model': 'onlyonce',
                                            'label': '测试插件（立即运行）',
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'server',
                                            'label': '服务器',
                                            'placeholder': 'https://api.chuckfang.com',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'nickname',
                                            'label': '昵称',
                                            'placeholder': 'MeoW昵称',
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
            'server': 'https://api.chuckfang.com',
            'nickname': '',
        }

    def get_page(self) -> List[dict]:
        pass

    def _send(self, title: str, text: str) -> Optional[Tuple[bool, str]]:
        """
        发送消息
        :param title: 标题
        :param text: 内容
        """
        try:
            if not self._server or not self._nickname:
                return False, "参数未配置"
            req_body = {"title": title, "msg": text}
            res = RequestUtils().post_res(f"{self._server.rstrip('/')}/{self._nickname}", data=req_body)
            if res and res.status_code == 200:
                res_json = res.json()
                code = res_json.get("status")
                message = res_json.get("msg")
                if code == 200:
                    logger.info(f"{self._nickname} MeoW消息发送成功，消息内容：{title} - {text}")
                else:
                    logger.warn(f"{self._nickname} MeoW消息发送失败：{message}")
            elif res is not None:
                logger.warn(
                    f"{self._nickname} MeoW消息发送失败，错误码：{res.status_code}，错误原因：{res.reason}"
                )
            else:
                logger.warn(f"{self._nickname} MeoW消息发送失败：未获取到返回信息")
        except Exception as e:
            logger.error(f"MeoW消息发送失败：{str(e)}")

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

        return self._send(title, text)

    def stop_service(self):
        """
        退出插件
        """
        pass
