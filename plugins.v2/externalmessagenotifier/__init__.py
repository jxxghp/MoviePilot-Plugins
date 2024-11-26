import time
from typing import Any, List, Dict, Tuple, Optional
from app.core.event import eventmanager, Event
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import WebhookEventInfo, ServiceInfo
from app.schemas.types import EventType, MediaType, MediaImageType, NotificationType
from app.utils.web import WebUtils
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()

class WebhookRequest(BaseModel):
    title: str
    text: str

class ExternalMessageNotifier(_PluginBase):
    # 插件基本信息
    plugin_name = "外部消息通知"  # 插件名称
    plugin_desc = "接收外部消息并通过当前通知渠道发送消息。"  # 插件描述
    plugin_icon = "forward.png"  # 插件图标
    plugin_version = "1.1"  # 插件版本
    plugin_author = "jxxghp,KoWming"  # 插件作者
    author_url = "https://github.com/KoWming/MoviePilot-Plugins"  # 作者主页
    plugin_config_prefix = "externalmessagenotifier_"  # 插件配置项ID前缀
    plugin_order = 14  # 加载顺序
    auth_level = 1  # 可使用的用户级别

    # 私有属性定义
    mediaserver_helper = None  # 媒体服务器辅助对象
    _enabled = False  # 是否启用插件
    _add_play_link = False  # 是否添加播放链接
    _mediaservers = None  # 配置的媒体服务器列表
    _types = []  # 支持的消息类型
    _webhook_msg_keys = {}  # webhook消息键值对，用于过滤重复消息

    # 消息动作映射表
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
        "item.rate": "标记了"
    }

    # 媒体服务器图标URL映射表
    _webhook_images = {
        "emby": "https://emby.media/notificationicon.png",
        "plex": "https://www.plex.tv/wp-content/uploads/2022/04/new-logo-process-lines-gray.png",
        "jellyfin": "https://play-lh.googleusercontent.com/SCsUK3hCCRqkJbmLDctNYCfehLxsS4ggD1ZPHIFrrAN1Tn9yhjmGMPep2D9lMaaa9eQi"
    }

    # 初始化插件方法
    def init_plugin(self, config: dict = None):
        self.mediaserver_helper = MediaServerHelper()  # 初始化媒体服务器辅助对象
        if config:
            self._enabled = config.get("enabled")  # 从配置中读取是否启用插件
            self._types = config.get("types") or []  # 从配置中读取消息类型列表
            self._mediaservers = config.get("mediaservers") or []  # 从配置中读取媒体服务器列表
            self._add_play_link = config.get("add_play_link", False)  # 从配置中读取是否添加播放链接

    # 获取服务信息
    def service_infos(self, type_filter: Optional[str] = None) -> Optional[Dict[str, ServiceInfo]]:
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

    # 获取插件状态
    def get_state(self) -> bool:
        return self._enabled

    # 获取命令列表
    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    # 获取API列表
    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/webhook",
                "endpoint": self.handle_webhook,
                "method": "POST",
                "summary": "处理Webhook消息",
                "description": "接收并处理来自媒体服务器的Webhook消息"
            }
        ]

    # 获取表单配置
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        # 消息类型选项
        types_options = [
            {"title": "新入库", "value": "library.new"},
            {"title": "开始播放", "value": "playback.start|media.play|PlaybackStart"},
            {"title": "停止播放", "value": "playback.stop|media.stop|PlaybackStop"},
            {"title": "用户标记", "value": "item.rate"},
            {"title": "测试", "value": "system.webhooktest"},
            {"title": "登录成功", "value": "user.authenticated"},
            {"title": "登录失败", "value": "user.authenticationfailed"},
        ]
        # 返回表单配置和数据结构
        return [
            {
                'component': 'VForm',
                'content': [
                    # 启用插件开关
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
                            # 添加播放链接开关
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
                    # 选择媒体服务器
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
                    # 选择消息类型
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
                    # 设置说明
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

    # 获取页面配置
    def get_page(self) -> List[dict]:
        pass

    # 注册事件处理器
    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event):
        if not self._enabled:
            return
        event_info: WebhookEventInfo = event.event_data
        if not event_info:
            return
        # 检查是否支持该类型的消息
        if not self._webhook_actions.get(event_info.event):
            return
        # 检查是否选择了该类型的消息
        msgflag = False
        for _type in self._types:
            if event_info.event in _type.split("|"):
                msgflag = True
                break
        if not msgflag:
            logger.info(f"未开启 {event_info.event} 类型的消息通知")
            return
        # 构建消息标题
        if event_info.item_type in ["TV", "SHOW"]:
            message_title = f"{self._webhook_actions.get(event_info.event)}剧集 {event_info.item_name}"
        elif event_info.item_type == "MOV":
            message_title = f"{self._webhook_actions.get(event_info.event)}电影 {event_info.item_name}"
        elif event_info.item_type == "AUD":
            message_title = f"{self._webhook_actions.get(event_info.event)}有声书 {event_info.item_name}"
        else:
            message_title = f"{self._webhook_actions.get(event_info.event)}"
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
            message_texts.append(f"剧情：{event_info.overview}")
        message_texts.append(f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
        message_content = "\n".join(message_texts)

        # 获取消息图片
        image_url = event_info.image_url
        if (event_info.tmdb_id
                and event_info.season_id
                and event_info.episode_id):
            specific_image = self.chain.obtain_specific_image(
                mediaid=event_info.tmdb_id,
                mtype=MediaType.TV,
                image_type=MediaImageType.Backdrop,
                season=event_info.season_id,
                episode=event_info.episode_id
            )
            if specific_image:
                image_url = specific_image
        if not image_url:
            image_url = self._webhook_images.get(event_info.channel)

        # 获取播放链接
        play_link = None
        if self._add_play_link:
            if event_info.server_name:
                service = self.service_infos().get(event_info.server_name)
                if service:
                    play_link = service.instance.get_play_url(event_info.item_id)
            elif event_info.channel:
                services = self.mediaserver_helper.get_services(type_filter=event_info.channel)
                for service in services.values():
                    play_link = service.instance.get_play_url(event_info.item_id)
                    if play_link:
                        break
        # 处理开始和停止播放消息
        if str(event_info.event) == "playback.stop":
            self.__add_element(expiring_key)
        if str(event_info.event) == "playback.start":
            self.__remove_element(expiring_key)

        # 发送消息
        self.post_message(mtype=NotificationType.MediaServer,
                          title=message_title, text=message_content, image=image_url, link=play_link)

    # 处理Webhook请求
    async def handle_webhook(self, request: Request):
        try:
            data = await request.json()
            webhook_request = WebhookRequest(**data)
            event_info = WebhookEventInfo(
                event="custom",  # 自定义事件类型
                item_id=None,
                item_name=None,
                item_type=None,
                user_name=None,
                client=None,
                device_name=None,
                ip=None,
                percentage=None,
                overview=None,
                image_url=None,
                tmdb_id=None,
                season_id=None,
                episode_id=None,
                server_name=None,
                channel=None,
                title=webhook_request.title,
                text=webhook_request.text
            )
            event = Event(event_type=EventType.WebhookMessage, event_data=event_info)
            self.send(event)
            return {"status": "success"}
        except Exception as e:
            logger.error(f"处理Webhook请求时出错：{str(e)}")
            raise HTTPException(status_code=400, detail=str(e))

    # 添加元素到过期字典
    def __add_element(self, key, duration=600):
        expiration_time = time.time() + duration
        self._webhook_msg_keys[key] = expiration_time

    # 从过期字典移除元素
    def __remove_element(self, key):
        self._webhook_msg_keys = {k: v for k, v in self._webhook_msg_keys.items() if k != key}

    # 获取所有未过期的元素
    def __get_elements(self):
        current_time = time.time()
        self._webhook_msg_keys = {k: v for k, v in self._webhook_msg_keys.items() if v > current_time}
        return list(self._webhook_msg_keys.keys())

    # 停止服务
    def stop_service(self):
        pass