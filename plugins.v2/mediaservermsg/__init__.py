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
from app.schemas import WebhookEventInfo, ServiceInfo
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

    # 插件基本信息
    plugin_name = "媒体库服务器通知"
    # 插件描述
    plugin_desc = "发送Emby/Jellyfin/Plex服务器的播放、入库等通知消息。"
    # 插件图标
    plugin_icon = "mediaplay.png"
    # 插件版本
    plugin_version = "1.7.1"
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
    _pending_messages = {}                     # 待聚合的消息 {series_key: [event_info, ...]}
    _aggregate_timers = {}                     # 聚合定时器 {series_key: timer}

    # Webhook事件映射配置
    _webhook_actions = {
        "library.new": "新入库",
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
            self._aggregate_time = int(config.get("aggregate_time", self.DEFAULT_AGGREGATE_TIME))


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

        services = MediaServerHelper().get_services(type_filter=type_filter, name_filters=self._mediaservers)
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
            {"title": "新入库", "value": "library.new"},
            {"title": "开始播放", "value": "playback.start|media.play|PlaybackStart"},
            {"title": "停止播放", "value": "playback.stop|media.stop|PlaybackStop"},
            {"title": "用户标记", "value": "item.rate"},
            {"title": "测试", "value": "system.webhooktest"},
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
        # 检查插件是否启用
        if not self._enabled:
            logger.debug("插件未启用")
            return

        # 获取事件数据
        event_info: WebhookEventInfo = event.event_data
        if not event_info:
            logger.debug("事件数据为空")
            return

        # 打印event_info用于调试
        logger.debug(f"收到Webhook事件: {event_info}")

        # 检查事件类型是否在支持范围内
        if not self._webhook_actions.get(event_info.event):
            logger.debug(f"事件类型 {event_info.event} 不在支持范围内")
            return

        # 检查事件类型是否在用户配置的允许范围内
        # 将配置的类型预处理为一个扁平集合，提高查找效率
        allowed_types = set()
        for _type in self._types:
            allowed_types.update(_type.split("|"))

        if event_info.event not in allowed_types:
            logger.info(f"未开启 {event_info.event} 类型的消息通知")
            return

        # 验证媒体服务器配置
        if not self.service_infos():
            logger.info(f"未开启任一媒体服务器的消息通知")
            return

        if event_info.server_name and not self.service_info(name=event_info.server_name):
            logger.info(f"未开启媒体服务器 {event_info.server_name} 的消息通知")
            return

        if event_info.channel and not self.service_infos(type_filter=event_info.channel):
            logger.info(f"未开启媒体服务器类型 {event_info.channel} 的消息通知")
            return

        # TV剧集结入库聚合处理
        logger.debug("检查是否需要进行TV剧集聚合处理")
        logger.debug(f"event_info.event={event_info.event}, item_type={event_info.item_type}")
        logger.debug(f"json_object存在: {bool(event_info.json_object)}, 类型: {type(event_info.json_object)}")

        # 判断是否需要进行TV剧集入库聚合处理
        if (self._aggregate_enabled and
                event_info.event == "library.new" and
                event_info.item_type in ["TV", "SHOW"] and
                event_info.json_object and
                isinstance(event_info.json_object, dict)):

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
        expiring_key = f"{event_info.item_id}-{event_info.client}-{event_info.user_name}"
        # 过滤停止播放重复消息
        if str(event_info.event) == "playback.stop" and expiring_key in self._webhook_msg_keys.keys():
            # 刷新过期时间
            self.__add_element(expiring_key)
            return

        # 构造消息标题
        if event_info.item_type in ["TV", "SHOW"]:
            message_title = f"{self._webhook_actions.get(event_info.event)}剧集 {event_info.item_name}"
        elif event_info.item_type == "MOV":
            message_title = f"{self._webhook_actions.get(event_info.event)}电影 {event_info.item_name}"
        elif event_info.item_type == "AUD":
            message_title = f"{self._webhook_actions.get(event_info.event)}有声书 {event_info.item_name}"
        else:
            message_title = f"{self._webhook_actions.get(event_info.event)}"

        # 构造消息内容
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

        # 消息内容
        message_content = "\n".join(message_texts)

        # 处理消息图片
        image_url = event_info.image_url
        if not image_url and event_info.tmdb_id: 
            # 查询电影图片
            if event_info.item_type == "MOV" :
                image_url = self.chain.obtain_specific_image(
                    mediaid=event_info.tmdb_id,
                    mtype=MediaType.MOVIE,
                    image_type=MediaImageType.Poster
                )

            # 查询剧集图片
            elif event_info.item_type in ["TV", "SHOW"]:
                season_id = event_info.season_id if event_info.season_id else None
                episode_id = event_info.episode_id if event_info.episode_id else None

                specific_image = self.chain.obtain_specific_image(
                    mediaid=event_info.tmdb_id,
                    mtype=MediaType.TV,
                    image_type=MediaImageType.Backdrop,
                    season=season_id,
                    episode=episode_id
                )
                if specific_image:
                    image_url = specific_image
        # 使用默认图片
        if not image_url:
            image_url = self._webhook_images.get(event_info.channel)

        # 处理播放链接
        play_link = None
        if self._add_play_link:
            play_link = self._get_play_link(event_info)

        # 更新播放状态缓存
        if str(event_info.event) == "playback.stop":
            # 停止播放消息，添加到过期字典
            self.__add_element(expiring_key)
        if str(event_info.event) == "playback.start":
            # 开始播放消息，删除过期字典
            self.__remove_element(expiring_key)

        # 发送消息
        self.post_message(mtype=NotificationType.MediaServer,
                          title=message_title, text=message_content, image=image_url, link=play_link)

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
        # 从json_object中提取series_id
        if event_info.json_object and isinstance(event_info.json_object, dict):
            item = event_info.json_object.get("Item", {})
            series_id = item.get("SeriesId") or item.get("SeriesName")
            if series_id:
                return series_id

        # fallback到event_info中的series_id
        return getattr(event_info, "series_id", None)

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
                self._aggregate_timers[series_id].cancel()

            # 设置新的定时器
            logger.debug(f"设置新的定时器，将在 {self._aggregate_time} 秒后触发")
            timer = threading.Timer(self._aggregate_time, self._send_aggregated_message, [series_id])
            self._aggregate_timers[series_id] = timer
            timer.start()

            logger.debug(f"已添加剧集 {series_id} 的消息到聚合队列，当前队列长度: {len(self._pending_messages[series_id])}，定时器将在 {self._aggregate_time} 秒后触发")
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
            if series_id in self._aggregate_timers:
                del self._aggregate_timers[series_id]
            return

        events = self._pending_messages.pop(series_id)
        logger.debug(f"从队列中获取 {len(events)} 条消息: {series_id}")
        # 清除定时器引用
        if series_id in self._aggregate_timers:
            del self._aggregate_timers[series_id]

        # 构造聚合消息
        if not events:
            logger.debug(f"事件列表为空: {series_id}")
            return

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
        # 通过TMDB ID获取详细信息
        tmdb_info = None
        overview = None
        try:
            if not first_event.tmdb_id:
                logger.debug("tmdb_id为空，使用原有逻辑发送消息")
                # 使用原有逻辑构造消息
                message_title = f"📺 {self._webhook_actions.get(first_event.event)}剧集：{first_event.item_name}"
                message_texts = []
                message_texts.append(f"⏰ 时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

                # 收集集数信息
                episode_details = []
                for event in events:
                    if event.season_id is not None and event.episode_id is not None:
                        episode_details.append(f"S{int(event.season_id):02d}E{int(event.episode_id):02d}")

                if episode_details:
                    message_texts.append(f"📺 季集：{', '.join(episode_details)}")

                message_content = "\n".join(message_texts)

                # 使用默认图片
                image_url = first_event.image_url or self._webhook_images.get(first_event.channel)

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
            logger.debug(f"获取TMDB信息时出错: {str(e)}")

        if first_event.overview:
            overview = first_event.overview
        elif tmdb_info:
            if is_multiple_episodes:
                if tmdb_info.get('overview'):
                    overview = tmdb_info.get('overview')
                    logger.debug(f"从TMDB获取到overview: {overview}")
                else:
                    logger.debug("未能从TMDB获取到有效的overview信息")
            else:
                if (tmdb_info.get('episodes') and tmdb_info.get('episodes')[int(first_event.episode_id)-1]
                        and tmdb_info.get('episodes')[int(first_event.episode_id)-1].get('overview')):
                    overview = tmdb_info.get('episodes')[int(first_event.episode_id)-1].get('overview')
                elif tmdb_info.get('overview'):
                    overview = tmdb_info.get('overview')
                else:
                    logger.debug("未能从TMDB获取到有效的overview信息")
        else:
            logger.debug("未能从TMDB获取到有效的overview信息")

        events[0] = first_event
        # 消息标题
        message_title = f"📺 {self._webhook_actions.get(first_event.event)}剧集：{first_event.item_name.split(' ', 1)[0]}"

        if is_multiple_episodes:
            message_title += f" 等{events_count}个文件"

        logger.debug(f"构建消息标题: {message_title}")

        # 消息内容
        message_texts = []
        # 时间信息放在最前面
        message_texts.append(f"⏰ 时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
        # 添加每个集数的信息并合并连续集数
        episodes_detail = self._merge_continuous_episodes(events)
        message_texts.append(f"📺 季集：{episodes_detail}")
        # 确定二级分类
        cat = None
        if tmdb_info.get('media_type') == MediaType.TV:
            cat = self.category.get_tv_category(tmdb_info)
        else:
            cat = self.category.get_movie_category(tmdb_info)
        if cat:
            message_texts.append(f"📚 分类：{cat}")
        # 评分信息
        if tmdb_info and tmdb_info.get('vote_average'):
            rating = round(float(tmdb_info.get('vote_average')), 1)
            message_texts.append(f"⭐ 评分：{rating}/10")
            # 类型信息 - genres可能是字典列表或字符串列表
            if tmdb_info.get('genres'):
                genres_list = []
                for genre in tmdb_info.get('genres')[:3]:
                    if isinstance(genre, dict):
                        genres_list.append(genre.get('name', ''))
                    else:
                        genres_list.append(str(genre))
                if genres_list:
                    genre_text = '、'.join(genres_list)
                    message_texts.append(f"🎭 类型：{genre_text}")
        if overview:
            # 限制overview只显示前100个字符，超出部分用...代替
            if len(overview) > 100:
                overview = overview[:100] + "..."
            message_texts.append(f"📖 剧情：{overview}")

        # 消息内容
        message_content = "\n".join(message_texts)
        logger.debug(f"构建消息内容: {message_content}")

        # 消息图片
        image_url = first_event.image_url
        logger.debug(f"初始图片URL: {image_url}")

        if not image_url and tmdb_info and tmdb_info.get('poster_path') and not is_multiple_episodes:
            # 剧集图片
            image_url = self.backdrop_path = f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{tmdb_info.get('poster_path')}"
            logger.debug(f"使用剧集图片URL: {image_url}")
        elif not image_url and tmdb_info and tmdb_info.get('backdrop_path') and is_multiple_episodes:
            # 使用TMDB背景
            image_url = self.backdrop_path = f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{tmdb_info.get('backdrop_path')}"
            logger.debug(f"使用TMDB背景URL: {image_url}")
        # 使用默认图片
        if not image_url:
            image_url = self._webhook_images.get(first_event.channel)
            logger.debug(f"使用默认图片URL: {image_url}")

        # 处理播放链接
        play_link = None
        if self._add_play_link:
            play_link = self._get_play_link(first_event)

        # 发送聚合消息
        logger.debug(f"准备发送消息 - 标题: {message_title}, 内容: {message_content}, 图片: {image_url}")
        self.post_message(mtype=NotificationType.MediaServer,
                          title=message_title, text=message_content, image=image_url, link=play_link)

        logger.info(f"已发送聚合消息：{message_title}")

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
        tmdb_info = self._get_tmdb_info(
            tmdb_id=events[0].tmdb_id,
            mtype=MediaType.TV,
            season=events[0].season_id
        )
        for event in events:
            # 提取季号和集号
            season, episode = None, None
            episode_name = ""

            if event.json_object and isinstance(event.json_object, dict):
                item = event.json_object.get("Item", {})
                season = item.get("ParentIndexNumber")
                episode = item.get("IndexNumber")
                if episode is not None and int(episode) <= len(tmdb_info.get('episodes')):
                    episode_name = tmdb_info.get("episodes")[int(episode)-1].get('name')
                else:
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
                if season not in season_episodes:
                    season_episodes[season] = []
                season_episodes[season].append({
                    "episode": episode,
                    "name": episode_name
                })


        # 对每季的集数进行排序并合并连续区间
        merged_details = []
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
                        merged_details.append(f"S{season:02d}E{start:02d} {episode_names[0]}")
                    else:
                        # 合并区间
                        merged_details.append(f"S{season:02d}E{start:02d}-E{end:02d}")
                    # 开始新区间
                    start = end = current
                    episode_names = [episodes[i]["name"]]

            # 添加最后一个区间
            if start == end:
                merged_details.append(f"S{season:02d}E{start:02d} {episode_names[-1]}")
            else:
                merged_details.append(f"S{season:02d}E{start:02d}-E{end:02d}")

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
        self._webhook_msg_keys = {k: v for k, v in self._webhook_msg_keys.items() if k != key}

    def __get_elements(self):
        """
        获取所有未过期的元素键值列表，并清理过期元素

        Returns:
            List[str]: 未过期的元素键值列表
        """
        current_time = time.time()
        # 创建新的字典，只保留未过期的元素
        valid_keys = []
        expired_keys = []

        for key, expiration_time in self._webhook_msg_keys.items():
            if expiration_time > current_time:
                valid_keys.append(key)
            else:
                expired_keys.append(key)

        # 从字典中移除过期元素
        for key in expired_keys:
            del self._webhook_msg_keys[key]

        return valid_keys

    def _get_play_link(self, event_info: WebhookEventInfo) -> Optional[str]:
        """
        获取媒体项目的播放链接

        Args:
            event_info (WebhookEventInfo): 事件信息

        Returns:
            Optional[str]: 播放链接，如果无法获取则返回None
        """
        play_link = None
        if event_info.server_name:
            service = self.service_infos().get(event_info.server_name)
            if service:
                play_link = service.instance.get_play_url(event_info.item_id)
        elif event_info.channel:
            services = MediaServerHelper().get_services(type_filter=event_info.channel)
            for service in services.values():
                play_link = service.instance.get_play_url(event_info.item_id)
                if play_link:
                    break

        return play_link

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
            tmdb_info = self.chain.tmdb_info(tmdbid=tmdb_id, mtype=mtype, season=season)
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
        # 发送所有待处理的聚合消息
        for series_id in list(self._pending_messages.keys()):
            # 直接发送消息而不依赖定时器
            self._send_aggregated_message(series_id)

        # 取消所有定时器
        for timer in self._aggregate_timers.values():
            timer.cancel()
        self._aggregate_timers.clear()
        self._pending_messages.clear()
        self._get_tmdb_info.cache_clear()
