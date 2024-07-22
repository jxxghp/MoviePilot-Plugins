import re

from app.core.event import eventmanager, Event
from app.core.context import MediaInfo
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType, MediaImageType, NotificationType
from typing import List, Tuple, Dict, Any, Optional


class MediaMessageDiy(_PluginBase):
    # 插件名称
    plugin_name = "自定义媒体消息"
    # 插件描述
    plugin_desc = "自定义发送的媒体消息的格式"
    # 插件图标
    plugin_icon = "Themeengine_A.png"
    # 插件版本
    plugin_version = "0.1.5"
    # 插件作者
    plugin_author = "JerryGeng"
    # 作者主页
    author_url = "https://github.com/Jerry-Geng"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediamessagediv_"
    # 加载顺序
    # plugin_order = 14
    # 可使用的用户级别
    auth_level = 1

    _enable = False
    _pattern = None

    def init_plugin(self, config: dict = None):
        logger.info('自定义媒体消息插件初始化')
        self._enable = config.get("enable")
        self._pattern = config.get("pattern")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    @eventmanager.register(EventType.MediaMessage)
    def deal_event(self, event: Event):
        logger.info("收到MediaMessage事件")
        logger.info("0")
        if not self._enable or not self._pattern:
            logger.info("1")
            logger.info('enabled: %s, pattern: %s' % (self._enable, self._pattern))
            return
        logger.info("2")
        event_info = event.event_data
        logger.info("3")
        if not event_info:
            logger.info('no event data')
            return
        logger.info("4")
        medias: List[MediaInfo] = event_info.medias
        logger.info("5")
        if not medias:
            logger.info('no medias')
            return
        logger.info("6")
        result = ''
        logger.info("7")
        for media in medias:
            result = result + self.formatMedia(media) + '\n'
        logger.info('返回内容：%s' % result)
        return result

    def format_media(self, media: MediaInfo):
        return re.sub('%&%(\\w+)%%%', lambda match: media[match[1]], self._pattern)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                            'model': 'enable',
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
                                            'model': 'pattern',
                                            'label': '格式模板',
                                            'placeholder': '使用markdown语法，另：使用形如%&%field%%%的形式引用媒体内容，具体字段解释请看插件的README\n例如：%&%title%%%表示媒体标题',
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
                                        'component': 'VLabel',
                                        'props': {
                                            'text': '格式模板说明：'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enable": self._enable,
            "pattern": self._pattern
        }

    def get_page(self) -> List[dict]:
        pass

    def get_state(self) -> bool:
        return self._enable

    def stop_service(self):
        pass
