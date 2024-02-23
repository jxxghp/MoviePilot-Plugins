from app.plugins import _PluginBase
from app.core.event import eventmanager, Event
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from typing import Any, List, Dict, Tuple
from app.log import logger
import time

class WeChat(_PluginBase):
    # 插件名称
    plugin_name = "微信消息推送"
    # 插件描述
    plugin_desc = "仅限Hook方式"
    # 插件图标
    plugin_icon = "Wechat_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "叉叉"
    # 作者主页
    author_url = "https://github.com/lhlxx2010"
    # 插件配置项ID前缀
    plugin_config_prefix = "wechat_"
    # 加载顺序
    plugin_order = 36
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _wechat_url = None
    _chatroomid = None
    # _method = None
    _enabled = False

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._wechat_url = config.get("wechat_url")
            self._chatroomid = config.get('chatroomid')
            self.timestamp = int(time.time())
    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # request_options = ["POST", "GET"]
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'chatroomid',
                                            'label': '群聊ID',
                                            # 'items': request_options
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'wechat_url',
                                            'label': 'wechat_hook_Url:http:ip:端口'
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
            "chatroomid": "",
            "wechat_url": ""
        }

    def get_page(self) -> List[dict]:
        pass


@eventmanager.register(EventType.NoticeMessage)
def send(self, event: Event):
    """
    消息发送事件
    """
    if not self._enabled or not self._wechat_url or not self._chatroomid:
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
    # 图像
    image = msg_body.get("image")

    if not title and not text:
        logger.warn("标题和内容不能同时为空")
        return

    if (msg_type and self._msgtypes
            and msg_type.name not in self._msgtypes):
        logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
        return



    try:
        if not image:
            payload = {
                "para": {
                    "id": str(self.timestamp),
                    "type": 555,
                    "roomid": "",
                    "wxid": self._chatroomid,
                    "content": title + "\n" + text,
                    "nickname": "",
                    "ext": "",
                }
                # "text": {
                #     "content": title + "\n" + text,
                # }
            }
        # else:
        #     payload = {
        #         "msgtype": "news",
        #         "news": {
        #             "articles": [
        #                 {
        #                     "title": title,
        #                     "description": text,
        #                     "url": "moviepilot",
        #                     "picurl": image
        #                 }
        #             ]
        #         }
        #     }

        res = RequestUtils().post_res(url=self._wechat_url, json=payload)
        if res and res.status_code == 200:
            ret_json = res.json()
            errno = ret_json.get('errcode')
            error = ret_json.get('errmsg')
            if errno == 0:
                logger.info("企业微信机器人消息发送成功")
            else:
                logger.warn(f"企业微信机器人消息发送失败，错误码：{errno}，错误原因：{error}")
        elif res is not None:
            logger.warn(f"企业微信机器人消息发送失败，错误码：{res.status_code}，错误原因：{res.reason}")
        else:
            logger.warn("企业微信机器人消息发送失败，未获取到返回信息")
    except Exception as msg_e:
        logger.error(f"企业微信机器人消息发送失败，{str(msg_e)}")

def stop_service(self):
    """
    退出插件
    """
    pass