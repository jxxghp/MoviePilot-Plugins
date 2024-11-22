import json
import requests

from typing import Any, List, Dict, Tuple

from pypushdeer import PushDeer

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class ExternalMessageForwarding(_PluginBase):
    # 插件名称
    plugin_name = "外部消息转发"
    # 插件描述
    plugin_desc = "外部应用使用apikey 推送mp消息（密钥认证）。"
    # 插件图标
    plugin_icon = "forward.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "KoWming"
    # 作者主页
    author_url = "https://github.com/KoWming/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "externalmessageforwarding_"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 1


    # 私有属性
    _enabled = False
    _server = None
    _apikey = None
    _msgtypes = []

    # 读取JSON文件
    with open('api_spec.json', 'r') as file:
        api_spec = json.load(file)

    def send_external_push_message(self, title, text="", image=""):
        """
          	外部应用使用apikey 推送ms消息
        :param title: 标题 （必填）
        :param text: 内容 （选填）
        :param image: 图片URL （选填）
        :return: 
        """
        self.send_message(title=title, app_switch='external_push', client_switch='external_push', text=text, image=image)

    def get_message_client_info(self, cid=None):
        """
        	获取消息端信息
        """
        if cid:
            return self._client_configs.get(str(cid))
        return self._client_configs

    def get_interactive_client(self, client_type=None):
        """
        	查询当前可以交互的渠道
        """
        if client_type:
            return self._active_interactive_clients.get(client_type)
        else:
            return [client for client in self._active_interactive_clients.values()]

    @staticmethod
    def get_search_types():
        """
        	查询可交互的渠道
        """
        return [info.get("search_type")
                for info in ModuleConf.MESSAGE_CONF.get('client').values()
                if info.get('search_type')]


    def delete_message_client(self, cid):
        """
        	删除消息端
        """
        ret = self.dbhelper.delete_message_client(cid=cid)
        self.init_config()
        return ret

    def check_message_client(self, cid=None, interactive=None, enabled=None, ctype=None):
        """
        	设置消息端
        """
        ret = self.dbhelper.check_message_client(
            cid=cid,
            interactive=interactive,
            enabled=enabled,
            ctype=ctype
        )
        self.init_config()
        return ret

    def insert_message_client(self,
                              name,
                              ctype,
                              config,
                              switchs: list,
                              plugin_switchs: list,
                              interactive,
                              enabled,
                              note=''):
        """
        	插入消息端
        """
        ret = self.dbhelper.insert_message_client(
            name=name,
            ctype=ctype,
            config=config,
            switchs=switchs,
            plugin_switchs=plugin_switchs,
            interactive=interactive,
            enabled=enabled,
            note=note
        )
        self.init_config()
        return ret


    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._msgtypes = config.get("msgtypes") or []
            self._server = config.get("server")
            self._apikey = config.get("apikey")

    def get_state(self) -> bool:
        return self._enabled and (True if self._server and self._apikey else False)

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
                                            'placeholder': 'https://api2.pushdeer.com',
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
                                            'model': 'apikey',
                                            'label': '密钥',
                                            'placeholder': 'PDUxxx',
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
            'server': 'https://api2.pushdeer.com',
            'apikey': ''
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
            if not self._server or not self._apikey:
                return False, "参数未配置"
            pushdeer = PushDeer(server=self._server, pushkey=self._apikey)
            res = pushdeer.send_markdown(title, desp=text)
            if res:
                logger.info(f"PushDeer消息发送成功")
            else:
                logger.warn(f"PushDeer消息发送失败！")
        except Exception as msg_e:
            logger.error(f"PushDeer消息发送失败，错误信息：{str(msg_e)}")

    def stop_service(self):
        """
        退出插件
        """
        pass
