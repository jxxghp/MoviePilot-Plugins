import re
import time
import hmac
import hashlib
import base64
import urllib.parse

from app.plugins import _PluginBase
from app.core.event import eventmanager, Event
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from typing import Any, List, Dict, Tuple
from app.log import logger


class DingdingMsg(_PluginBase):
    # 插件名称
    plugin_name = "钉钉机器人"
    # 插件描述
    plugin_desc = "支持使用钉钉机器人发送消息通知。"
    # 插件图标
    plugin_icon = "Dingding_A.png"
    # 插件版本
    plugin_version = "1.13"
    # 插件作者
    plugin_author = "nnlegenda"
    # 作者主页
    author_url = "https://github.com/nnlegenda"
    # 插件配置项ID前缀
    plugin_config_prefix = "dingdingmsg_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _token = None
    _secret = None
    _msgtypes = []

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._token = config.get("token")
            self._secret = config.get("secret")
            self._msgtypes = config.get("msgtypes") or []

    def get_state(self) -> bool:
        return self._enabled and (True if self._token else False) and (True if self._secret else False)

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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'token',
                                            'label': '钉钉机器人token',
                                            'placeholder': 'xxxxxx',
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
                                            'model': 'secret',
                                            'label': '加签',
                                            'placeholder': 'SECxxx',
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
            'token': '',
            'msgtypes': []
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
        # 封面
        cover = msg_body.get("image")

        if not title and not text:
            logger.warn("标题和内容不能同时为空")
            return

        if (msg_type and self._msgtypes
                and msg_type.name not in self._msgtypes):
            logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
            return

        sc_url = self.url_sign(self._token, self._secret)

        try:

            if text:
                # 对text进行Markdown特殊字符转义
                text = re.sub(r"([_`])", r"\\\1", text)
                # 钉钉中需要在换行前有两个空格，才能够正常换行
                text = re.sub(r"\n", r"  \n", text)
            else:
                text = ""

            if cover:
                data = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,
                        "text": "### %s\n\n"
                                "![Cover](%s)\n\n"
                                "> %s\n\n > MoviePilot %s\n" % (title, cover, text, msg_type.value)
                    }
                }
            else:
                data = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,
                        "text": "### %s\n\n"
                                "> %s\n\n > MoviePilot %s\n" % (title, text, msg_type.value)
                    }
                }
            res = RequestUtils(content_type="application/json").post_res(sc_url, json=data)
            if res and res.status_code == 200:
                ret_json = res.json()
                errno = ret_json.get('errcode')
                error = ret_json.get('errmsg')
                if errno == 0:
                    logger.info("钉钉机器人消息发送成功")
                else:
                    logger.warn(f"钉钉机器人消息发送失败，错误码：{errno}，错误原因：{error}")
            elif res is not None:
                logger.warn(f"钉钉机器人消息发送失败，错误码：{res.status_code}，错误原因：{res.reason}")
            else:
                logger.warn("钉钉机器人消息发送失败，未获取到返回信息")
        except Exception as msg_e:
            logger.error(f"钉钉机器人消息发送失败，{str(msg_e)}")

    def stop_service(self):
        """
        退出插件
        """
        pass

    def url_sign(self, access_token: str, secret: str) -> str:
        """
        加签
        """
        # 生成时间戳和签名
        timestamp = str(round(time.time() * 1000))
        secret_enc = secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        # 组合请求的完整 URL
        full_url = f'https://oapi.dingtalk.com/robot/send?access_token={access_token}&timestamp={timestamp}&sign={sign}'
        return full_url
