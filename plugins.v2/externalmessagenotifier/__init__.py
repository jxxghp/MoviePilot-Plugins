import time
from typing import Any, List, Dict, Tuple, Optional
from app.core.event import eventmanager, Event
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import WebhookEventInfo, ServiceInfo
from app.schemas.types import EventType, MediaType, MediaImageType, NotificationType
from app.utils.web import WebUtils

class ExternalMessageNotifier(_PluginBase):
    # 插件名称
    plugin_name = "通用Webhook消息通知"
    # 插件描述
    plugin_desc = "发送来自任意webhook的消息通知，支持添加播放链接。"
    # 插件图标
    plugin_icon = "forward.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "jxxghp,KoWming"
    # 作者主页
    author_url = "https://github.com/KoWming/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "externalmessagenotifier_"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 1
    # 私有属性
    mediaserver_helper = None
    _enabled = False
    _add_play_link = False
    _mediaservers = None
    _types = []
    _webhook_msg_keys = {}
    # 拼装消息内容
    _webhook_actions = {
        "library.new": "新入库",
        "system.webhooktest": "测试",
        "playback.start": "开始播放",
        "playback.stop": "停止播放",
        "user.authenticated": "登录成功",
        "user.authenticationfailed": "登录失败",
        "media.play": "开始播放",
        "media.stop": "停止播放",
        "PlaybackStart": "开始播放",
        "PlaybackStop": "停止播放",
        "item.rate": "标记了",
        # 默认值
        "其他": "其他"
    }
    _webhook_images = {
        "emby": "https://emby.media/notificationicon.png",
        "plex": "https://www.plex.tv/wp-content/uploads/2022/04/new-logo-process-lines-gray.png",
        "jellyfin": "https://play-lh.googleusercontent.com/SCsUK3hCCRqkJbmLDctNYCfehLxsS4ggD1ZPHIFrrAN1Tn9yhjmGMPep2D9lMaaa9eQi"
    }

    def init_plugin(self, config: dict = None):
        self.mediaserver_helper = MediaServerHelper()
        if config:
            self._enabled = config.get("enabled")
            self._types = config.get("types") or []
            self._mediaservers = config.get("mediaservers") or []
            self._add_play_link = config.get("add_play_link", False)

    def service_infos(self, type_filter: Optional[str] = None) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._mediaservers:
            logger.warning("尚未配置媒体服务器，请检查配置")
            return None
        services = self.mediaserver_helper.get_services(type_filter=type_filter, name_filters=self._mediaservers)
        if not services:
            logger.warning("获取媒体服务器实例失败，请检查配置")
            return None
        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"媒体服务器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info
        if not active_services:
            logger.warning("没有已连接的媒体服务器，请检查配置")
            return None
        return active_services

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
        types_options = [
            {"title": "新入库", "value": "library.new"},
            {"title": "开始播放", "value": "playback.start|media.play|PlaybackStart"},
            {"title": "停止播放", "value": "playback.stop|media.stop|PlaybackStop"},
            {"title": "用户标记", "value": "item.rate"},
            {"title": "测试", "value": "system.webhooktest"},
            {"title": "登录成功", "value": "user.authenticated"},
            {"title": "登录失败", "value": "user.authenticationfailed"},
            {"title": "其他", "value": "其他"},  # 新增选项
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
                                            'model': 'add_play_link',
                                            'label': '添加播放链接',
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
                                            'clearable': True,
                                            'model': 'mediaservers',
                                            'label': '媒体服务器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in self.mediaserver_helper.get_configs().values()]
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
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'types',
                                            'label': '消息类型',
                                            'items': types_options
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
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '需要设置媒体服务器Webhook，回调相对路径为 /api/v1/webhook?token=API_TOKEN&source=媒体服务器名（3001端口），其中 API_TOKEN 为设置的 API_TOKEN。'
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
            "types": []
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event):
        """
        发送通知消息
        """
        if not self._enabled:
            return
        event_info: WebhookEventInfo = event.event_data
        if not event_info:
            return

        # 获取消息类型，如果未在配置中指定，则默认为 "其他"
        message_type = self._webhook_actions.get(event_info.event, "其他")

        # 如果没有选中任何类型，或者当前事件不在选中的类型中，则不处理
        if not self._types or message_type not in self._types:
            logger.info(f"未开启 {event_info.event} 类型的消息通知")
            return

        # 构建消息标题
        message_title = f"{message_type} {event_info.item_name}" if event_info.item_name else message_type

        # 构建消息内容
        message_texts = []
        if event_info.user_name:
            message_texts.append(f"用户：{event_info.user_name}")
        if event_info.device_name:
            message_texts.append(f"设备：{event_info.client} {event_info.device_name}")
        if event_info.ip:
            message_texts.append(f"IP地址：{event_info.ip} {WebUtils.get_location(event_info.ip)}")
        if event_info.percentage:
            percentage = round(float(event_info.percentage), 2)
            message_texts.append(f"进度：{percentage}%")
        if event_info.overview:
            message_texts.append(f"详情：{event_info.overview}")
        message_texts.append(f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

        # 消息内容
        message_content = "\n".join(message_texts)

        # 消息图片
        image_url = event_info.image_url
        if not image_url and event_info.channel:
            image_url = self._webhook_images.get(event_info.channel, "")

        # 添加播放链接
        play_link = None
        if self._add_play_link and event_info.item_id:
            for service in self.service_infos().values():
                play_link = service.instance.get_play_url(event_info.item_id)
                if play_link:
                    break

        # 发送消息
        self.post_message(mtype=NotificationType.Webhook,
                          title=message_title, text=message_content, image=image_url, link=play_link)

    def __add_element(self, key, duration=600):
        expiration_time = time.time() + duration
        # 如果元素已经存在，更新其过期时间
        self._webhook_msg_keys[key] = expiration_time

    def __remove_element(self, key):
        self._webhook_msg_keys = {k: v for k, v in self._webhook_msg_keys.items() if k != key}

    def __get_elements(self):
        current_time = time.time()
        # 过滤掉过期的元素
        self._webhook_msg_keys = {k: v for k, v in self._webhook_msg_keys.items() if v > current_time}
        return list(self._webhook_msg_keys.keys())

    def stop_service(self):
        """
        退出插件
        """
        pass