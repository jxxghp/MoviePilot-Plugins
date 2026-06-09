import re
import threading
import time
from typing import Any, List, Dict, Tuple, Optional

from app.core.cache import cached
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.modules.themoviedb import CategoryHelper
from app.plugins import _PluginBase
from app.schemas import WebhookEventInfo, ServiceInfo, MediaServerItem
from app.schemas.types import EventType, MediaType, MediaImageType, NotificationType
from app.utils.web import WebUtils


class MediaServerMsg(_PluginBase):
    """
    媒体服务器通知插件

    功能：
    1. 监听Emby/Jellyfin/Plex等媒体服务器的Webhook事件
    2. 根据配置发送播放、入库等通知消息
    3. 对TV剧集入库事件进行智能聚合，避免消息轰炸
    4. 支持多种媒体服务器和丰富的消息类型配置
    """

    # 常量定义
    DEFAULT_EXPIRATION_TIME = 600                  # 默认过期时间（秒）
    DEFAULT_AGGREGATE_TIME = 15                   # 默认聚合时间（秒）
    DEDUPE_EXPIRATION_TIME = 30                    # 去重缓存过期时间（秒）

    # 插件基本信息
    plugin_name = "媒体库服务器通知"
    # 插件描述
    plugin_desc = "发送Emby/Jellyfin/Plex服务器的播放、入库等通知消息。"
    # 插件图标
    plugin_icon = "mediaplay.png"
    # 插件版本
    plugin_version = "1.8.2.3"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediaservermsg_"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 1

    # 插件运行时状态配置
    _enabled = False                           # 插件是否启用
    _add_play_link = False                     # 是否添加播放链接
    _mediaservers = None                       # 媒体服务器列表
    _types = []                                # 启用的消息类型
    _webhook_msg_keys = {}                     # Webhook消息去重缓存
    _aggregate_enabled = True                   # 是否启用TV剧集聚合功能

    # TV剧集消息聚合配置
    _aggregate_time = DEFAULT_AGGREGATE_TIME   # 聚合时间窗口（秒）
    # 待聚合的消息 {series_key: [event_info, ...]}
    _pending_messages = {}
    _aggregate_timers = {}                     # 聚合定时器 {series_key: timer}

    # Webhook事件映射配置
    _webhook_actions = {
        "library.new": "新入库",
        "ItemAdded": "新入库",
        "system.notificationtest": "测试",
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

    # Jellyfin Webhook 新增媒体事件使用 ItemAdded，与通用入库事件按同一类型处理。
    _webhook_event_aliases = {
        "ItemAdded": "library.new"
    }

    # 媒体服务器默认图标
    _webhook_images = {
        "emby": "https://emby.media/notificationicon.png",
        "plex": "https://www.plex.tv/wp-content/uploads/2022/04/new-logo-process-lines-gray.png",
        "jellyfin": "https://play-lh.googleusercontent.com/SCsUK3hCCRqkJbmLDctNYCfehLxsS4ggD1ZPHIFrrAN1Tn9yhjmGMPep2D9lMaaa9eQi"
    }

    def __init__(self):
        super().__init__()
        self.category = CategoryHelper()
        logger.debug("媒体服务器消息插件初始化完成")

    def init_plugin(self, config: dict = None):
        """
        初始化插件配置

        Args:
            config (dict, optional): 插件配置参数
        """
        if config:
            self._enabled = config.get("enabled")
            self._types = config.get("types") or []
            self._mediaservers = config.get("mediaservers") or []
            self._add_play_link = config.get("add_play_link", False)
            self._aggregate_enabled = config.get("aggregate_enabled", False)
            self._aggregate_time = int(config.get(
                "aggregate_time", self.DEFAULT_AGGREGATE_TIME))

    def service_infos(self, type_filter: Optional[str] = None) -> Optional[Dict[str, ServiceInfo]]:
        """
        获取媒体服务器信息服务信息

        Args:
            type_filter (str, optional): 媒体服务器类型过滤器

        Returns:
            Dict[str, ServiceInfo]: 活跃的媒体服务器服务信息字典
        """
        if not self._mediaservers:
            logger.warning("尚未配置媒体服务器，请检查配置")
            return None

        services = MediaServerHelper().get_services(
            type_filter=type_filter, name_filters=self._mediaservers)
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

    def service_info(self, name: str) -> Optional[ServiceInfo]:
        """
        根据名称获取特定媒体服务器服务信息

        Args:
            name (str): 媒体服务器名称

        Returns:
            ServiceInfo: 媒体服务器服务信息
        """
        service_infos = self.service_infos() or {}
        return service_infos.get(name)

    def get_state(self) -> bool:
        """
        获取插件状态

        Returns:
            bool: 插件是否启用
        """
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        获取插件命令
        （当前未实现）

        Returns:
            List[Dict[str, Any]]: 空列表
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        （当前未实现）

        Returns:
            List[Dict[str, Any]]: 空列表
        """
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        types_options = [
            {"title": "新入库", "value": "library.new|ItemAdded"},
            {"title": "开始播放", "value": "playback.start|media.play|PlaybackStart"},
            {"title": "停止播放", "value": "playback.stop|media.stop|PlaybackStop"},
            {"title": "用户标记", "value": "item.rate"},
            {"title": "测试", "value": "system.notificationtest"},
            {"title": "登录成功", "value": "user.authenticated"},
            {"title": "登录失败", "value": "user.authenticationfailed"},
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
                                                      for config in MediaServerHelper().get_configs().values()]
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'aggregate_enabled',
                                            'label': '启用TV剧集结入库聚合',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {'show': '{{aggregate_enabled}}'},
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
                                            'model': 'aggregate_time',
                                            'label': 'TV剧集结入库聚合时间（秒）',
                                            'placeholder': '15'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {'show': '{{aggregate_enabled}}'},
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
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '请在整理刮削设置中添加tmdbid,以保证准确性。仅保证在Emby和整理刮削添加tmdbid后功能正常。'
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
            "types": [],
            "aggregate_enabled": False,
            "aggregate_time": 15
        }

    def get_page(self) -> List[dict]:
        """
        获取插件页面
        （当前未实现）

        Returns:
            List[dict]: 空列表
        """
        pass

    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event):
        """
        发送通知消息主入口函数
        处理来自媒体服务器的Webhook事件，并根据配置决定是否发送通知消息

        处理流程：
        1. 检查插件是否启用
        2. 验证事件数据有效性
        3. 检查事件类型是否在支持范围内
        4. 检查事件类型是否在用户配置的允许范围内
        5. 验证媒体服务器配置
        6. 特殊处理TV剧集入库事件（聚合处理）
        7. 处理常规消息事件
        8. 构造并发送通知消息

        Args:
            event (Event): Webhook事件对象
        """
        try:
            # 检查插件是否启用
            if not self._enabled:
                logger.debug("插件未启用")
                return

            # 获取事件数据
            event_info: WebhookEventInfo = getattr(event, 'event_data', None)
            if not event_info:
                logger.debug("事件数据为空")
                return

            # 打印event_info用于调试
            logger.debug(f"收到Webhook事件: {event_info}")

            # 检查事件类型是否在支持范围内
            event_type = getattr(event_info, 'event', None)
            event_action_type = self._get_event_action_type(event_type)
            event_match_types = self._get_event_match_types(event_type)
            if not event_type or not self._webhook_actions.get(event_action_type):
                logger.debug(f"事件类型 {event_type} 不在支持范围内")
                return

            # 检查事件类型是否在用户配置的允许范围内
            # 将配置的类型预处理为一个扁平集合，提高查找效率
            allowed_types = set()
            for _type in self._types:
                allowed_types.update(_type.split("|"))

            if not event_match_types.intersection(allowed_types):
                logger.debug(f"事件类型 {event_type} 不在用户配置的允许范围内{allowed_types}")
                logger.info(f"未开启 {event_type} 类型的消息通知")
                return

            # 验证媒体服务器配置
            if not self.service_infos():
                logger.info(f"未开启任一媒体服务器的消息通知")
                return

            server_name = getattr(event_info, 'server_name', None)
            if server_name and not self.service_info(name=server_name):
                logger.info(f"未开启媒体服务器 {server_name} 的消息通知")
                return

            channel = getattr(event_info, 'channel', None)
            if channel and not self.service_infos(type_filter=channel):
                logger.info(f"未开启媒体服务器类型 {channel} 的消息通知")
                return

            # 通用去重：构造去重键
            item_id = getattr(event_info, 'item_id', '')
            if item_id:
                # 使用标准化后的事件类型去重，避免同类事件别名造成重复通知。
                dedupe_key = f"{server_name}-{event_action_type}-{item_id}" if server_name else f"{event_action_type}-{item_id}"
                # 检查是否已处理过该事件
                if dedupe_key in self.__get_elements():
                    logger.debug(f"检测到重复Webhook事件，已处理过: {dedupe_key}")
                    return
                # 添加到去重缓存（30秒过期）
                self.__add_element(dedupe_key, duration=self.DEDUPE_EXPIRATION_TIME)

            # TV剧集结入库聚合处理
            logger.debug("检查是否需要进行TV剧集聚合处理")

            def should_aggregate_tv() -> bool:
                """判断是否需要进行TV剧集聚合处理"""
                if not self._aggregate_enabled:
                    return False

                if event_action_type != "library.new":
                    return False

                item_type = getattr(event_info, 'item_type', None)
                if item_type not in ["TV", "SHOW"]:
                    return False

                json_object = getattr(event_info, 'json_object', None)
                if not json_object or not isinstance(json_object, dict):
                    return False

                return True

            # 判断是否需要进行TV剧集入库聚合处理
            if should_aggregate_tv():
                logger.debug("满足TV剧集聚合条件，尝试获取series_id")
                series_id = self._get_series_id(event_info)
                logger.debug(f"获取到的series_id: {series_id}")
                if series_id:
                    logger.debug(f"开始聚合处理，series_id={series_id}")
                    self._aggregate_tv_episodes(series_id, event_info)
                    logger.debug("TV剧集消息已处理并返回")
                    return  # TV剧集消息已处理，直接返回
                else:
                    logger.debug("未能获取到有效的series_id")

            logger.debug("未进行聚合处理，继续普通消息处理流程")
            item_id = getattr(event_info, 'item_id', '')
            client = getattr(event_info, 'client', '')
            user_name = getattr(event_info, 'user_name', '')
            expiring_key = f"{item_id}-{client}-{user_name}"

            # 过滤停止播放重复消息
            if str(event_type) == "playback.stop" and expiring_key in self._webhook_msg_keys.keys():
                # 刷新过期时间
                self.__add_element(expiring_key)
                return

            # 构造消息标题
            item_type = getattr(event_info, 'item_type', '')
            item_name = getattr(event_info, 'item_name', '')

            message_title = ""
            event_action = self._webhook_actions.get(event_action_type, event_type)
            if item_type in ["TV", "SHOW"]:
                message_title = f"{event_action}剧集 {item_name}"
            elif item_type == "MOV":
                message_title = f"{event_action}电影 {item_name}"
            elif item_type == "AUD":
                message_title = f"{event_action}有声书 {item_name}"
            else:
                message_title = f"{event_action}"

            # 构造消息内容
            message_texts = []
            user_name = getattr(event_info, 'user_name', None)
            if user_name:
                message_texts.append(f"用户：{user_name}")

            device_name = getattr(event_info, 'device_name', None)
            client = getattr(event_info, 'client', None)
            if device_name:
                message_texts.append(f"设备：{client or ''} {device_name}")
            elif client:
                message_texts.append(f"设备：{client}")

            ip = getattr(event_info, 'ip', None)
            if ip:
                try:
                    location = WebUtils.get_location(ip)
                    message_texts.append(f"IP地址：{ip} {location}")
                except Exception as e:
                    logger.debug(f"获取IP位置信息时出错: {str(e)}")
                    message_texts.append(f"IP地址：{ip}")

            percentage = getattr(event_info, 'percentage', None)
            if percentage:
                try:
                    percentage_val = round(float(percentage), 2)
                    message_texts.append(f"进度：{percentage_val}%")
                except (ValueError, TypeError):
                    pass

            overview = getattr(event_info, 'overview', None)
            if overview:
                message_texts.append(f"剧情：{overview}")

            message_texts.append(
                f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

            # 消息内容
            message_content = "\n".join(message_texts)

            # 处理消息图片
            image_url = getattr(event_info, 'image_url', None)
            tmdb_id = getattr(event_info, 'tmdb_id', None)
            season_id = getattr(event_info, 'season_id', None)
            episode_id = getattr(event_info, 'episode_id', None)

            # 查询电影图片
            if item_type == "MOV" and tmdb_id:
                try:
                    image_url = self.chain.obtain_specific_image(
                        mediaid=tmdb_id,
                        mtype=MediaType.MOVIE,
                        image_type=MediaImageType.Poster
                    )
                except Exception as e:
                    logger.debug(f"获取电影图片时出错: {str(e)}")

            # 查询剧集图片
            elif tmdb_id:
                try:
                    specific_image = self.chain.obtain_specific_image(
                        mediaid=tmdb_id,
                        mtype=MediaType.TV,
                        image_type=MediaImageType.Backdrop,
                        season=season_id,
                        episode=episode_id
                    )
                    if specific_image:
                        image_url = specific_image
                except Exception as e:
                    logger.debug(f"获取剧集图片时出错: {str(e)}")

            # 使用默认图片
            if not image_url:
                channel = getattr(event_info, 'channel', '')
                image_url = self._webhook_images.get(channel)

            # 处理播放链接
            play_link = None
            if self._add_play_link:
                play_link = self._get_play_link(event_info)

            # 更新播放状态缓存
            if str(event_type) == "playback.stop":
                # 停止播放消息，添加到过期字典
                self.__add_element(expiring_key)
            if str(event_type) == "playback.start":
                # 开始播放消息，删除过期字典
                self.__remove_element(expiring_key)

            # 发送消息
            self.post_message(mtype=NotificationType.MediaServer,
                              title=message_title, text=message_content, image=image_url, link=play_link)

        except Exception as e:
            logger.error(f"处理Webhook事件时发生错误: {str(e)}", exc_info=True)

    def _get_series_id(self, event_info: WebhookEventInfo) -> Optional[str]:
        """
        获取剧集ID，用于TV剧集消息聚合

        优先级顺序：
        1. 从JSON对象的Item中获取SeriesId
        2. 从JSON对象的Item中获取SeriesName（作为备选）
        3. 从event_info中直接获取series_id（fallback方案）

        Args:
            event_info (WebhookEventInfo): Webhook事件信息

        Returns:
            Optional[str]: 剧集ID或None（如果无法获取）
        """
        try:
            # 从json_object中提取series_id
            json_object = getattr(event_info, 'json_object', None)
            if json_object and isinstance(json_object, dict):
                item = json_object.get("Item", {})
                series_id = item.get("SeriesId") or item.get("SeriesName")
                if series_id:
                    return str(series_id)

            # fallback到event_info中的series_id
            series_id = getattr(event_info, "series_id", None)
            if series_id:
                return str(series_id)
        except Exception as e:
            logger.debug(f"获取剧集ID时出错: {str(e)}")

        return None

    def _aggregate_tv_episodes(self, series_id: str, event_info: WebhookEventInfo):
        """
        聚合TV剧集结入库消息

        当同一剧集的多集在短时间内入库时，将它们聚合为一条消息发送，
        避免消息轰炸。通过设置定时器实现延迟发送，定时器时间内到达的
        同剧集消息会被聚合在一起。

        Args:
            series_id (str): 剧集ID
            event_info (WebhookEventInfo): Webhook事件信息
        """
        try:
            logger.debug(f"开始执行聚合处理: series_id={series_id}")

            # 参数校验
            if not series_id:
                logger.warning("无效的series_id")
                return

            # 初始化该series_id的消息列表
            if series_id not in self._pending_messages:
                logger.debug(f"为series_id={series_id}初始化消息列表")
                self._pending_messages[series_id] = []

            # 添加消息到待处理列表
            logger.debug(f"添加消息到待处理列表: series_id={series_id}")
            self._pending_messages[series_id].append(event_info)

            # 如果已经有定时器，取消它并重新设置
            if series_id in self._aggregate_timers:
                logger.debug(f"取消已存在的定时器: {series_id}")
                try:
                    self._aggregate_timers[series_id].cancel()
                except Exception as e:
                    logger.debug(f"取消定时器时出错: {str(e)}")

            # 设置新的定时器
            logger.debug(f"设置新的定时器，将在 {self._aggregate_time} 秒后触发")
            try:
                timer = threading.Timer(
                    self._aggregate_time, self._send_aggregated_message, [series_id])
                self._aggregate_timers[series_id] = timer
                timer.start()
            except Exception as e:
                logger.error(f"设置定时器时出错: {str(e)}")
                # 如果定时器设置失败，直接发送消息
                self._send_aggregated_message(series_id)

            logger.debug(
                f"已添加剧集 {series_id} 的消息到聚合队列，当前队列长度: {len(self._pending_messages.get(series_id, []))}，定时器将在 {self._aggregate_time} 秒后触发")
            logger.debug(f"完成聚合处理: series_id={series_id}")
        except Exception as e:
            logger.error(f"聚合处理过程中出现异常: {str(e)}", exc_info=True)

    def _send_aggregated_message(self, series_id: str):
        """
        发送聚合后的TV剧集消息

        当聚合定时器到期或插件退出时调用此方法，将累积的同剧集消息
        合并为一条消息发送给用户。

        Args:
            series_id (str): 剧集ID
        """
        logger.debug(f"定时器触发，准备发送聚合消息: {series_id}")

        # 获取该series_id的所有待处理消息
        if series_id not in self._pending_messages or not self._pending_messages[series_id]:
            logger.debug(f"消息队列为空或不存在: {series_id}")
            # 清除定时器引用
            self._aggregate_timers.pop(series_id, None)
            return

        events = self._pending_messages.pop(series_id)
        logger.debug(f"从队列中获取 {len(events)} 条消息: {series_id}")
        # 清除定时器引用
        self._aggregate_timers.pop(series_id, None)

        # 构造聚合消息
        if not events:
            logger.debug(f"事件列表为空: {series_id}")
            return

        try:
            # 使用第一个事件的信息作为基础
            first_event = events[0]

            # 预计算事件数量，避免重复调用len(events)
            events_count = len(events)
            is_multiple_episodes = events_count > 1

            # 尝试从item_path中提取tmdb_id
            tmdb_pattern = r'[\[{](?:tmdbid|tmdb)[=-](\d+)[\]}]'
            if match := re.search(tmdb_pattern, first_event.item_path):
                first_event.tmdb_id = match.group(1)
                logger.info(f"从路径提取到tmdb_id: {first_event.tmdb_id}")
            else:
                logger.info(f"未从路径中提取到tmdb_id: {first_event.item_path}")
                logger.info(f"尝试从媒体服务获取tmdb_id")
                # 获取渠道并尝试获取媒体服务
                media_service = self.service_info(name=first_event.server_name)
                if media_service:
                    service = media_service.instance
                    # 从first_event中获取item_id
                    item_id = first_event.item_id
                    if service and item_id:
                        info: MediaServerItem = service.get_iteminfo(item_id)
                        if info and info.tmdbid:
                            logger.info(f"从媒体服务器中获取到tmdb_id: {info.tmdbid}")
                            first_event.tmdb_id = info.tmdbid
                        else:
                            logger.info(f"从媒体服务器中未获取到tmdb_id")

            # 通过TMDB ID获取详细信息
            tmdb_info = None
            overview = None

            # 安全地获取概述信息
            def safe_get_overview(tmdb_data, event_data, multiple_eps):
                """
                安全地获取剧集概述信息

                该函数按照以下优先级获取剧情概述：
                1. 首先尝试使用来自webhook事件的overview（event_data.overview）
                2. 如果webhook事件中没有overview，则从TMDB数据中获取
                   - 如果是多集入库（multiple_eps=True），则返回剧集整体概述
                   - 如果是单集入库（multiple_eps=False），则优先返回该集的概述
                     如果该集概述为空，则回退到剧集整体概述

                Args:
                    tmdb_data (dict): TMDB API返回的剧集数据
                    event_data (WebhookEventInfo): Webhook事件数据
                    multiple_eps (bool): 是否为多集入库（多个episode聚合发送）

                Returns:
                    str: 剧情概述信息，如果无法获取则返回空字符串
                """
                # 优先使用来自webhook事件的概述信息
                if event_data.overview:
                    return event_data.overview

                # 如果webhook事件中没有概述，则尝试从TMDB数据中获取
                elif tmdb_data:
                    # 多集入库情况下，返回剧集整体概述
                    if multiple_eps:
                        return tmdb_data.get('overview', '')
                    else:
                        # 单集入库情况下，优先获取具体集数的概述
                        episodes = tmdb_data.get('episodes', [])

                        # 检查是否有episode_id，并且episodes数据存在
                        if (episodes and
                                hasattr(event_data, 'episode_id') and
                                event_data.episode_id is not None):
                            try:
                                # 将episode_id转换为数组索引（集数从1开始，数组从0开始）
                                ep_index = int(event_data.episode_id) - 1

                                # 确保索引在有效范围内
                                if 0 <= ep_index < len(episodes):
                                    episode_info = episodes[ep_index]
                                    episode_overview = episode_info.get(
                                        'overview', '')

                                    # 如果该集的概述存在且非空，则返回该集概述
                                    if episode_overview:
                                        return episode_overview
                            except (ValueError, TypeError):
                                # 如果转换episode_id为整数失败，跳过异常，回退到剧集整体概述
                                pass

                        # 如果无法获取该集概述，或episode_id不存在，回退到剧集整体概述
                        return tmdb_data.get('overview', '')

                # 如果以上都失败，返回空字符串
                return ''
            try:
                if not first_event.tmdb_id:
                    logger.debug("tmdb_id为空，使用原有逻辑发送消息")
                    # 使用原有逻辑构造消息
                    message_title = f"📺 {self._get_event_action(first_event.event)}剧集：{first_event.item_name}"
                    message_texts = []
                    message_texts.append(
                        f"⏰ 时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

                    # 收集集数信息
                    episode_details = []
                    for event in events:
                        if (hasattr(event, 'season_id') and event.season_id is not None and
                                hasattr(event, 'episode_id') and event.episode_id is not None):
                            try:
                                episode_details.append(
                                    f"S{int(event.season_id):02d}E{int(event.episode_id):02d}")
                            except (ValueError, TypeError):
                                pass

                    if episode_details:
                        message_texts.append(
                            f"📺 季集：{', '.join(episode_details)}")

                    message_content = "\n".join(message_texts)

                    # 使用默认图片
                    image_url = getattr(first_event, 'image_url', None) or self._webhook_images.get(
                        getattr(first_event, 'channel', ''))

                    # 处理播放链接
                    play_link = None
                    if self._add_play_link:
                        play_link = self._get_play_link(first_event)

                    # 发送消息
                    self.post_message(mtype=NotificationType.MediaServer,
                                      title=message_title,
                                      text=message_content,
                                      image=image_url,
                                      link=play_link)
                    return

                if first_event.item_type in ["TV", "SHOW"]:
                    logger.debug("查询TV类型的TMDB信息")
                    tmdb_info = self._get_tmdb_info(
                        tmdb_id=first_event.tmdb_id,
                        mtype=MediaType.TV,
                        season=first_event.season_id
                    )
                logger.debug(f"从TMDB获取到的信息: {tmdb_info}")
            except Exception as e:
                logger.error(f"获取TMDB信息时出错: {str(e)}")

            overview = safe_get_overview(
                tmdb_info, first_event, is_multiple_episodes)

            # 消息标题
            show_name = first_event.item_name
            # 从json_object中提取SeriesName作为剧集名称
            try:
                if (hasattr(first_event, 'json_object') and
                        first_event.json_object and
                        isinstance(first_event.json_object, dict)):
                    item = first_event.json_object.get("Item", {})
                    series_name = item.get("SeriesName")
                    if series_name:
                        show_name = series_name
            except Exception as e:
                logger.error(f"从json_object提取SeriesName时出错: {str(e)}")

            message_title = f"📺 {self._get_event_action(first_event.event) or '新入库'}剧集：{show_name}"

            if is_multiple_episodes:
                message_title += f" {events_count}个文件"

            logger.debug(f"构建消息标题: {message_title}")

            # 消息内容
            message_texts = []
            # 时间信息放在最前面
            message_texts.append(
                f"⏰ 时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
            # 添加每个集数的信息并合并连续集数
            episodes_detail = self._merge_continuous_episodes(events)
            message_texts.append(f"📺 季集：{episodes_detail}")

            # 确定二级分类
            cat = None
            if tmdb_info:
                try:
                    if tmdb_info.get('media_type') == MediaType.TV:
                        cat = self.category.get_tv_category(tmdb_info)
                    else:
                        cat = self.category.get_movie_category(tmdb_info)
                except Exception as e:
                    logger.debug(f"获取分类时出错: {str(e)}")

            if cat:
                message_texts.append(f"📚 分类：{cat}")

            # 评分信息
            if tmdb_info and tmdb_info.get('vote_average'):
                try:
                    rating = round(float(tmdb_info.get('vote_average')), 1)
                    message_texts.append(f"⭐ 评分：{rating}/10")
                except (ValueError, TypeError):
                    pass

                # 类型信息 - genres可能是字典列表或字符串列表
                genres = tmdb_info.get('genres', [])
                if genres:
                    try:
                        genres_list = []
                        for genre in genres[:3]:
                            if isinstance(genre, dict):
                                genre_name = genre.get('name', '')
                                if genre_name:
                                    genres_list.append(genre_name)
                            else:
                                genre_str = str(genre)
                                if genre_str:
                                    genres_list.append(genre_str)
                        if genres_list:
                            genre_text = '、'.join(genres_list)
                            message_texts.append(f"🎭 类型：{genre_text}")
                    except Exception as e:
                        logger.debug(f"处理类型信息时出错: {str(e)}")

            if overview:
                # 限制overview只显示前100个字符，超出部分用...代替
                try:
                    if len(overview) > 100:
                        overview = overview[:100] + "..."
                    message_texts.append(f"📖 剧情：{overview}")
                except Exception as e:
                    logger.debug(f"处理剧情简介时出错: {str(e)}")

            # 消息内容
            message_content = "\n".join(message_texts)
            logger.debug(f"构建消息内容: {message_content}")

            # 消息图片
            image_url = getattr(first_event, 'image_url', None)
            logger.debug(f"初始图片URL: {image_url}")

            if not image_url and tmdb_info:
                try:
                    if not is_multiple_episodes:
                        # 单集时优先使用poster_path
                        if tmdb_info.get('poster_path'):
                            image_url = f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{tmdb_info.get('poster_path')}"
                            logger.debug(f"使用剧集海报URL: {image_url}")
                        elif tmdb_info.get('backdrop_path'):
                            # 如果海报为空，则使用背景
                            image_url = f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{tmdb_info.get('backdrop_path')}"
                            logger.debug(f"使用TMDB背景URL: {image_url}")
                    else:
                        # 多集时优先使用backdrop_path
                        if tmdb_info.get('backdrop_path'):
                            image_url = f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{tmdb_info.get('backdrop_path')}"
                            logger.debug(f"使用TMDB背景URL: {image_url}")
                        elif tmdb_info.get('poster_path'):
                            # 如果背景为空，则使用海报
                            image_url = f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{tmdb_info.get('poster_path')}"
                            logger.debug(f"使用剧集海报URL: {image_url}")
                except Exception as e:
                    logger.debug(f"处理图片URL时出错: {str(e)}")

            # 使用默认图片
            if not image_url:
                channel = getattr(first_event, 'channel', '')
                image_url = self._webhook_images.get(channel)
                logger.debug(f"使用默认图片URL: {image_url}")

            # 处理播放链接
            play_link = None
            if self._add_play_link:
                play_link = self._get_play_link(first_event)

            # 发送聚合消息
            logger.debug(
                f"准备发送消息 - 标题: {message_title}, 内容: {message_content}, 图片: {image_url}")
            self.post_message(mtype=NotificationType.MediaServer,
                              title=message_title, text=message_content, image=image_url, link=play_link)

            logger.info(f"已发送聚合消息：{message_title}")
        except Exception as e:
            logger.error(f"发送聚合消息时发生错误: {str(e)}", exc_info=True)

    def _merge_continuous_episodes(self, events: List[WebhookEventInfo]) -> str:
        """
        合并连续的集数信息，使消息展示更美观

        将同一季中连续的集数合并为一个区间显示，例如：
        S01E01-E03 而不是 S01E01, S01E02, S01E03

        Args:
            events (List[WebhookEventInfo]): Webhook事件信息列表

        Returns:
            str: 合并后的集数信息字符串
        """
        # 按季分组集数信息
        season_episodes = {}

        # 安全获取tmdb_info
        tmdb_info = {}
        try:
            if events and hasattr(events[0], 'tmdb_id') and events[0].tmdb_id:
                tmdb_info = self._get_tmdb_info(
                    tmdb_id=events[0].tmdb_id,
                    mtype=MediaType.TV,
                    season=events[0].season_id
                ) or {}
        except Exception as e:
            logger.debug(f"获取TMDB信息时出错: {str(e)}")

        for event in events:
            # 提取季号和集号
            season, episode = None, None
            episode_name = ""

            try:
                if (hasattr(event, 'json_object') and
                        event.json_object and
                        isinstance(event.json_object, dict)):
                    item = event.json_object.get("Item", {})
                    season = item.get("ParentIndexNumber")
                    episode = item.get("IndexNumber")

                    # 安全地获取剧集名称
                    if episode is not None:
                        try:
                            episodes_list = tmdb_info.get('episodes', [])
                            ep_index = int(episode) - 1
                            if 0 <= ep_index < len(episodes_list):
                                episode_data = episodes_list[ep_index]
                                episode_name = episode_data.get('name', '')
                        except (ValueError, TypeError, IndexError):
                            pass

                    if not episode_name:
                        episode_name = item.get("Name", "")

                # 如果无法从json_object获取信息，则尝试从event_info直接获取
                if season is None:
                    season = getattr(event, "season_id", None)
                if episode is None:
                    episode = getattr(event, "episode_id", None)
                if not episode_name:
                    episode_name = getattr(event, "item_name", "")

                # 确保季号和集号都存在
                if season is not None and episode is not None:
                    season_key = int(season)
                    episode_key = int(episode)

                    if season_key not in season_episodes:
                        season_episodes[season_key] = []
                    season_episodes[season_key].append({
                        "episode": episode_key,
                        "name": episode_name or ""
                    })
            except Exception as e:
                logger.debug(f"处理事件信息时出错: {str(e)}")
                continue

        # 对每季的集数进行排序并合并连续区间
        merged_details = []
        try:
            for season in sorted(season_episodes.keys()):
                episodes = season_episodes[season]
                # 按集号排序
                episodes.sort(key=lambda x: x["episode"])

                # 合并连续集数
                if not episodes:
                    continue

                # 初始化第一个区间
                start = episodes[0]["episode"]
                end = episodes[0]["episode"]
                episode_names = [episodes[0]["name"]]

                for i in range(1, len(episodes)):
                    current = episodes[i]["episode"]
                    # 如果当前集号与上一集连续
                    if current == end + 1:
                        end = current
                        episode_names.append(episodes[i]["name"])
                    else:
                        # 保存当前区间
                        if start == end:
                            merged_details.append(
                                f"S{season:02d}E{start:02d} {episode_names[0]}")
                        else:
                            # 合并区间
                            merged_details.append(
                                f"S{season:02d}E{start:02d}-E{end:02d}")
                        # 开始新区间
                        start = end = current
                        episode_names = [episodes[i]["name"]]

                # 添加最后一个区间
                if start == end:
                    merged_details.append(
                        f"S{season:02d}E{start:02d} {episode_names[-1] if episode_names else ''}")
                else:
                    merged_details.append(
                        f"S{season:02d}E{start:02d}-E{end:02d}")
        except Exception as e:
            logger.error(f"合并集数信息时出错: {str(e)}")
            # 出错时返回简单的集数列表
            simple_details = []
            for season in sorted(season_episodes.keys()):
                for episode_info in season_episodes[season]:
                    simple_details.append(
                        f"S{season:02d}E{episode_info['episode']:02d}")
            return ", ".join(simple_details)

        return ", ".join(merged_details)

    def __add_element(self, key, duration=DEFAULT_EXPIRATION_TIME):
        """
        添加元素到过期字典中，用于过滤短时间内的重复消息

        Args:
            key (str): 元素键值
            duration (int, optional): 过期时间（秒），默认DEFAULT_EXPIRATION_TIME秒
        """
        expiration_time = time.time() + duration
        # 如果元素已经存在，更新其过期时间
        self._webhook_msg_keys[key] = expiration_time

    def __remove_element(self, key):
        """
        从过期字典中移除指定元素

        Args:
            key (str): 要移除的元素键值
        """
        self._webhook_msg_keys = {
            k: v for k, v in self._webhook_msg_keys.items() if k != key}

    def __get_elements(self):
        """
        获取所有未过期的元素键值列表，并清理过期元素

        Returns:
            List[str]: 未过期的元素键值列表
        """
        try:
            current_time = time.time()
            # 创建新的字典，只保留未过期的元素
            valid_keys = []
            expired_keys = []

            for key, expiration_time in self._webhook_msg_keys.items():
                try:
                    if expiration_time > current_time:
                        valid_keys.append(key)
                    else:
                        expired_keys.append(key)
                except Exception as e:
                    logger.debug(f"检查过期时间时出错: {str(e)}")
                    # 出错时保守处理，认为已过期
                    expired_keys.append(key)

            # 从字典中移除过期元素
            for key in expired_keys:
                self._webhook_msg_keys.pop(key, None)

            return valid_keys
        except Exception as e:
            logger.error(f"获取有效元素时出错: {str(e)}")
            return []

    def _get_event_action_type(self, event_type: Optional[str]) -> Optional[str]:
        """
        获取用于消息文案和去重的标准事件类型。
        """
        if event_type is None:
            return None
        return self._webhook_event_aliases.get(str(event_type), str(event_type))

    def _get_event_match_types(self, event_type: Optional[str]) -> set:
        """
        获取配置匹配时允许命中的事件类型，兼容历史配置和媒体服务器原始事件。
        """
        if event_type is None:
            return set()
        normalized_type = self._get_event_action_type(event_type)
        return {str(event_type), normalized_type}

    def _get_event_action(self, event_type: Optional[str]) -> Optional[str]:
        """
        获取事件对应的消息动作文案。
        """
        return self._webhook_actions.get(self._get_event_action_type(event_type))

    def _get_play_link(self, event_info: WebhookEventInfo) -> Optional[str]:
        """
        获取媒体项目的播放链接

        Args:
            event_info (WebhookEventInfo): 事件信息

        Returns:
            Optional[str]: 播放链接，如果无法获取则返回None
        """
        try:
            server_name = getattr(event_info, 'server_name', None)
            item_id = getattr(event_info, 'item_id', None)

            if not item_id:
                return None

            if server_name:
                service = self.service_infos().get(server_name) if self.service_infos() else None
                if service:
                    try:
                        return service.instance.get_play_url(item_id)
                    except Exception as e:
                        logger.debug(f"获取播放链接时出错: {str(e)}")

            channel = getattr(event_info, 'channel', None)
            if channel:
                try:
                    services = MediaServerHelper().get_services(type_filter=channel)
                    for service in services.values():
                        try:
                            play_link = service.instance.get_play_url(item_id)
                            if play_link:
                                return play_link
                        except Exception as e:
                            logger.debug(f"从{service}获取播放链接时出错: {str(e)}")
                            continue
                except Exception as e:
                    logger.debug(f"获取媒体服务器服务时出错: {str(e)}")

        except Exception as e:
            logger.debug(f"获取播放链接时发生未知错误: {str(e)}")

        return None

    @cached(
        region="MediaServerMsg",           # 缓存区域，用于隔离不同插件的缓存
        maxsize=128,                  # 最大缓存条目数（仅内存缓存有效）
        ttl=600,                     # 缓存存活时间（秒）
        skip_none=True,               # 是否跳过None值缓存
        skip_empty=False              # 是否跳过空值缓存（空列表、空字典等）
    )
    def _get_tmdb_info(self, tmdb_id: str, mtype: MediaType, season: Optional[int] = None):
        """
        获取TMDB信息

        Args:
            tmdb_id: TMDB ID
            mtype: 媒体类型
            season: 季数（仅电视剧需要）

        Returns:
            dict: TMDB信息
        """
        if mtype == MediaType.MOVIE:
            return self.chain.tmdb_info(tmdbid=tmdb_id, mtype=mtype)
        else:  # TV类型
            tmdb_info = self.chain.tmdb_info(
                tmdbid=tmdb_id, mtype=mtype, season=season)
            tmdb_info2 = self.chain.tmdb_info(tmdbid=tmdb_id, mtype=mtype)
            return tmdb_info | tmdb_info2

    def stop_service(self):
        """
        退出插件时的清理工作

        在插件被停用或系统关闭时调用，确保：
        1. 所有待处理的聚合消息被立即发送出去
        2. 所有正在进行的定时器被取消
        3. 清空所有内部缓存数据
        """
        try:
            # 发送所有待处理的聚合消息
            pending_series_ids = list(self._pending_messages.keys())
            for series_id in pending_series_ids:
                # 直接发送消息而不依赖定时器
                try:
                    self._send_aggregated_message(series_id)
                except Exception as e:
                    logger.error(f"发送聚合消息时出错: {str(e)}")

            # 取消所有定时器
            for timer in self._aggregate_timers.values():
                try:
                    timer.cancel()
                except Exception as e:
                    logger.debug(f"取消定时器时出错: {str(e)}")

            self._aggregate_timers.clear()
            self._pending_messages.clear()

            # 清理缓存
            try:
                self._get_tmdb_info.cache_clear()
            except Exception as e:
                logger.debug(f"清理缓存时出错: {str(e)}")
        except Exception as e:
            logger.error(f"插件停止时发生错误: {str(e)}", exc_info=True)
