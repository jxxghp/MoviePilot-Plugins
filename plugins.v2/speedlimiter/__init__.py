import ipaddress
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any, Optional

from app.core.event import eventmanager, Event
from app.helper.downloader import DownloaderHelper
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType, WebhookEventInfo, ServiceInfo
from app.schemas.types import EventType
from app.utils.ip import IpUtils


class SpeedLimiter(_PluginBase):
    """根据外网媒体播放状态动态调整下载器限速。"""

    # 插件名称
    plugin_name = "播放限速"
    # 插件描述
    plugin_desc = "外网播放媒体库视频时，自动对下载器进行限速。"
    # 插件图标
    plugin_icon = "Librespeed_A.png"
    # 插件版本
    plugin_version = "2.2"
    # 插件作者
    plugin_author = "Shurelol"
    # 作者主页
    author_url = "https://github.com/Shurelol"
    # 插件配置项ID前缀
    plugin_config_prefix = "speedlimit_"
    # 加载顺序
    plugin_order = 11
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler = None
    _enabled: bool = False
    _notify: bool = False
    _interval: int = 60
    # Jellyfin 客户端通常会持续上报播放进度；超过该时间未上报的残留会话视为脏数据。
    _jellyfin_session_timeout: int = 120
    _downloader: list = []
    _play_up_speed: float = 0
    _play_down_speed: float = 0
    _noplay_up_speed: float = 0
    _noplay_down_speed: float = 0
    _bandwidth: float = 0
    _allocation_ratio: str = ""
    _auto_limit: bool = False
    _limit_enabled: bool = False
    # 不限速地址
    _unlimited_ips = {}
    # 当前限速状态
    _current_state = ""
    _exclude_path = ""

    def init_plugin(self, config: dict = None):
        """读取插件配置并初始化限速状态。"""

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._play_up_speed = float(config.get("play_up_speed")) if config.get("play_up_speed") else 0
            self._play_down_speed = float(config.get("play_down_speed")) if config.get("play_down_speed") else 0
            self._noplay_up_speed = float(config.get("noplay_up_speed")) if config.get("noplay_up_speed") else 0
            self._noplay_down_speed = float(config.get("noplay_down_speed")) if config.get("noplay_down_speed") else 0
            self._current_state = f"U:{self._noplay_up_speed},D:{self._noplay_down_speed}"
            self._exclude_path = config.get("exclude_path")

            try:
                # 总带宽
                self._bandwidth = int(float(config.get("bandwidth") or 0)) * 1000000
                # 自动限速开关
                if self._bandwidth > 0:
                    self._auto_limit = True
                else:
                    self._auto_limit = False
            except Exception as e:
                logger.error(f"智能限速上行带宽设置错误：{str(e)}")
                self._bandwidth = 0

            # 限速服务开关
            self._limit_enabled = True if (self._play_up_speed
                                           or self._play_down_speed
                                           or self._auto_limit) else False
            self._allocation_ratio = config.get("allocation_ratio") or ""
            # 不限速地址
            self._unlimited_ips["ipv4"] = config.get("ipv4") or ""
            self._unlimited_ips["ipv6"] = config.get("ipv6") or ""

            self._downloader = config.get("downloader") or []

    def get_state(self) -> bool:
        """返回插件是否已启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件命令定义；当前插件未注册命令。"""
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 定义；当前插件未暴露 API。"""
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._limit_enabled and self._interval:
            return [
                {
                    "id": "SpeedLimiter",
                    "name": "播放限速检查服务",
                    "trigger": "interval",
                    "func": self.check_playing_sessions,
                    "kwargs": {"seconds": self._interval}
                }
            ]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回播放限速配置表单及默认值。"""
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
                                            'model': 'notify',
                                            'label': '发送通知',
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
                                            'model': 'downloader',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in DownloaderHelper().get_configs().values()]
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
                                            'model': 'play_up_speed',
                                            'label': '播放限速（上传）',
                                            'placeholder': 'KB/s'
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
                                            'model': 'play_down_speed',
                                            'label': '播放限速（下载）',
                                            'placeholder': 'KB/s'
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
                                            'model': 'noplay_up_speed',
                                            'label': '未播放限速（上传）',
                                            'placeholder': 'KB/s'
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
                                            'model': 'noplay_down_speed',
                                            'label': '未播放限速（下载）',
                                            'placeholder': 'KB/s'
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
                                            'model': 'bandwidth',
                                            'label': '智能限速上行带宽',
                                            'placeholder': 'Mbps'
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'allocation_ratio',
                                            'label': '智能限速分配比例',
                                            'items': [
                                                {'title': '平均', 'value': ''},
                                                {'title': '1：9', 'value': '1:9'},
                                                {'title': '2：8', 'value': '2:8'},
                                                {'title': '3：7', 'value': '3:7'},
                                                {'title': '4：6', 'value': '4:6'},
                                                {'title': '6：4', 'value': '6:4'},
                                                {'title': '7：3', 'value': '7:3'},
                                                {'title': '8：2', 'value': '8:2'},
                                                {'title': '9：1', 'value': '9:1'},
                                            ]
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
                                            'model': 'ipv4',
                                            'label': '不限速地址范围（ipv4）',
                                            'placeholder': '留空默认不限速内网ipv4'
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
                                            'model': 'ipv6',
                                            'label': '不限速地址范围（ipv6）',
                                            'placeholder': '留空默认不限速内网ipv6'
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
                                            'model': 'exclude_path',
                                            'label': '不限速路径',
                                            'placeholder': '包含该路径的媒体不限速,多个请换行'
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
            "notify": True,
            "downloader": [],
            "play_up_speed": None,
            "play_down_speed": None,
            "noplay_up_speed": None,
            "noplay_down_speed": None,
            "bandwidth": None,
            "allocation_ratio": "",
            "ipv4": "",
            "ipv6": "",
            "exclude_path": ""
        }

    def get_page(self) -> List[dict]:
        """返回插件详情页；当前插件未提供详情页。"""
        pass

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._downloader:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        services = DownloaderHelper().get_services(name_filters=self._downloader)
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    @eventmanager.register(EventType.WebhookMessage)
    def check_playing_sessions(self, event: Event = None):
        """
        检查播放会话；Webhook 仅用于加速触发，定时轮询始终作为兼容兜底。
        """
        if not self.service_infos:
            return
        if not self._enabled:
            return
        if event:
            event_data: WebhookEventInfo = event.event_data
            if event_data.event not in [
                "playback.start",
                "PlaybackStart",
                "media.play",
                "media.stop",
                "PlaybackStop",
                "playback.stop"
            ]:
                return
        # 播放状态与比特率必须分开统计，避免 Jellyfin 未返回比特率时误判为未播放。
        has_remote_playback = False
        total_bit_rate = 0
        media_servers = MediaServerHelper().get_services()
        if not media_servers:
            return
        # 查询所有媒体服务器状态
        for server, service in media_servers.items():
            # 查询播放中会话
            playing_sessions = []
            if service.type == "emby":
                req_url = "[HOST]emby/Sessions?api_key=[APIKEY]"
                try:
                    res = service.instance.get_data(req_url)
                    if res and res.status_code == 200:
                        sessions = res.json()
                        for session in sessions:
                            if session.get("NowPlayingItem") and not session.get("PlayState", {}).get("IsPaused"):
                                if not self.__path_excluded(session.get("NowPlayingItem").get("Path")):
                                    playing_sessions.append(session)

                except Exception as e:
                    logger.error(f"获取Emby播放会话失败：{str(e)}")
                    continue
                # 计算有效比特率
                for session in playing_sessions:
                    # 设置了不限速范围则判断session ip是否在不限速范围内
                    if self._unlimited_ips["ipv4"] or self._unlimited_ips["ipv6"]:
                        if not self.__allow_access(self._unlimited_ips, session.get("RemoteEndPoint")) \
                                and session.get("NowPlayingItem", {}).get("MediaType") == "Video":
                            has_remote_playback = True
                            total_bit_rate += int(session.get("NowPlayingItem", {}).get("Bitrate") or 0)
                    # 未设置不限速范围，则默认不限速内网ip
                    elif not IpUtils.is_private_ip(session.get("RemoteEndPoint")) \
                            and session.get("NowPlayingItem", {}).get("MediaType") == "Video":
                        has_remote_playback = True
                        total_bit_rate += int(session.get("NowPlayingItem", {}).get("Bitrate") or 0)
            elif service.type == "jellyfin":
                req_url = (f"[HOST]Sessions?api_key=[APIKEY]&"
                           f"activeWithinSeconds={self._jellyfin_session_timeout}")
                try:
                    res = service.instance.get_data(req_url)
                    if res and res.status_code == 200:
                        sessions = self.__extract_jellyfin_sessions(res.json())
                        for session in sessions:
                            bit_rate = self.__jellyfin_session_bitrate(session)
                            if bit_rate is None:
                                continue
                            has_remote_playback = True
                            total_bit_rate += bit_rate
                except Exception as e:
                    logger.error(f"获取Jellyfin播放会话失败：{str(e)}")
                    continue
            elif service.type == "plex":
                _plex = service.instance.get_plex()
                if _plex:
                    sessions = _plex.sessions()
                    for session in sessions:
                        bitrate = sum([m.bitrate or 0 for m in session.media])
                        playing_sessions.append({
                            "type": session.TAG,
                            "bitrate": bitrate,
                            "address": session.player.address
                        })
                    # 计算有效比特率
                    for session in playing_sessions:
                        # 设置了不限速范围则判断session ip是否在不限速范围内
                        if self._unlimited_ips["ipv4"] or self._unlimited_ips["ipv6"]:
                            if not self.__allow_access(self._unlimited_ips, session.get("address")) \
                                    and session.get("type") == "Video":
                                has_remote_playback = True
                                total_bit_rate += int(session.get("bitrate") or 0)
                        # 未设置不限速范围，则默认不限速内网ip
                        elif not IpUtils.is_private_ip(session.get("address")) \
                                and session.get("type") == "Video":
                            has_remote_playback = True
                            total_bit_rate += int(session.get("bitrate") or 0)

        if has_remote_playback:
            logger.debug(f"外网播放总比特率：{total_bit_rate}")
            # 开启智能限速计算上传限速
            if self._auto_limit:
                play_up_speed = self.__calc_limit(total_bit_rate)
            else:
                play_up_speed = self._play_up_speed

            # 当前正在播放，开始限速
            self.__set_limiter(limit_type="播放", upload_limit=play_up_speed,
                               download_limit=self._play_down_speed)
        else:
            # 当前没有播放，取消限速
            self.__set_limiter(limit_type="未播放", upload_limit=self._noplay_up_speed,
                               download_limit=self._noplay_down_speed)

    @staticmethod
    def __get_compatible_value(data: dict, *keys: str) -> Any:
        """按候选字段名读取 Jellyfin 数据，兼容 PascalCase 与 camelCase 序列化。"""
        if not isinstance(data, dict):
            return None
        for key in keys:
            if key in data:
                return data.get(key)
        return None

    @classmethod
    def __extract_jellyfin_sessions(cls, payload: Any) -> List[dict]:
        """从列表或常见包装对象中提取 Jellyfin 会话列表。"""
        if isinstance(payload, list):
            return [session for session in payload if isinstance(session, dict)]
        if not isinstance(payload, dict):
            return []
        sessions = cls.__get_compatible_value(payload, "Items", "items", "Sessions", "sessions", "Data", "data")
        if not isinstance(sessions, list):
            return []
        return [session for session in sessions if isinstance(session, dict)]

    @staticmethod
    def __parse_jellyfin_datetime(value: Any) -> Optional[datetime]:
        """解析 Jellyfin 的 ISO 时间，无法识别时返回空以保留旧版本兼容。"""
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def __as_bool(value: Any) -> bool:
        """兼容布尔值及字符串形式的 Jellyfin 状态字段。"""
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def __normalize_remote_ip(remote_endpoint: Any) -> str:
        """去除 Jellyfin 远端地址中的端口和 IPv6 方括号。"""
        if not isinstance(remote_endpoint, str):
            return ""
        endpoint = remote_endpoint.strip()
        if not endpoint:
            return ""
        try:
            return str(ipaddress.ip_address(endpoint.split("%", 1)[0]))
        except ValueError:
            pass
        if endpoint.startswith("[") and "]" in endpoint:
            endpoint = endpoint[1:endpoint.index("]")]
        elif endpoint.count(":") == 1 and "." in endpoint:
            endpoint = endpoint.rsplit(":", 1)[0]
        try:
            return str(ipaddress.ip_address(endpoint.split("%", 1)[0]))
        except ValueError:
            return ""

    @classmethod
    def __is_video_item(cls, item: dict) -> bool:
        """判断 Jellyfin 当前媒体是否为视频，兼容字符串与枚举数值。"""
        media_type = cls.__get_compatible_value(item, "MediaType", "mediaType")
        if isinstance(media_type, str):
            normalized = media_type.strip().lower()
            if normalized in {"video", "1"}:
                return True
            if normalized:
                return False
        elif media_type is not None:
            return media_type == 1
        item_type = cls.__get_compatible_value(item, "Type", "type")
        return str(item_type or "").lower() in {"movie", "episode", "video", "trailer", "musicvideo"}

    @staticmethod
    def __coerce_bitrate(value: Any) -> int:
        """把 Jellyfin 不同层级返回的比特率安全转换为非负整数。"""
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def __sum_media_stream_bitrate(cls, streams: Any) -> int:
        """汇总音视频流比特率，忽略字幕等非传输码率字段。"""
        if not isinstance(streams, list):
            return 0
        total = 0
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            stream_type = cls.__get_compatible_value(stream, "Type", "type")
            if stream_type is not None and str(stream_type).lower() not in {"video", "audio", "0", "1"}:
                continue
            total += cls.__coerce_bitrate(
                cls.__get_compatible_value(stream, "BitRate", "bitRate", "Bitrate", "bitrate")
            )
        return total

    @classmethod
    def __get_jellyfin_bitrate(cls, session: dict, item: dict) -> int:
        """按转码信息、媒体源和媒体流的优先级提取当前播放比特率。"""
        transcoding = cls.__get_compatible_value(session, "TranscodingInfo", "transcodingInfo")
        if isinstance(transcoding, dict):
            bit_rate = cls.__coerce_bitrate(
                cls.__get_compatible_value(transcoding, "Bitrate", "bitrate", "BitRate", "bitRate")
            )
            if bit_rate:
                return bit_rate

        bit_rate = cls.__coerce_bitrate(
            cls.__get_compatible_value(item, "Bitrate", "bitrate", "BitRate", "bitRate")
        )
        if bit_rate:
            return bit_rate

        play_state = cls.__get_compatible_value(session, "PlayState", "playState") or {}
        media_source_id = cls.__get_compatible_value(play_state, "MediaSourceId", "mediaSourceId")
        media_sources = cls.__get_compatible_value(item, "MediaSources", "mediaSources") or []
        if isinstance(media_sources, list):
            selected_sources = [source for source in media_sources if isinstance(source, dict)]
            if media_source_id:
                selected_sources.sort(
                    key=lambda source: cls.__get_compatible_value(source, "Id", "id") != media_source_id
                )
            for source in selected_sources:
                bit_rate = cls.__coerce_bitrate(
                    cls.__get_compatible_value(source, "Bitrate", "bitrate", "BitRate", "bitRate")
                )
                if bit_rate:
                    return bit_rate
                bit_rate = cls.__sum_media_stream_bitrate(
                    cls.__get_compatible_value(source, "MediaStreams", "mediaStreams")
                )
                if bit_rate:
                    return bit_rate

        return cls.__sum_media_stream_bitrate(
            cls.__get_compatible_value(item, "MediaStreams", "mediaStreams")
        )

    def __jellyfin_session_bitrate(self, session: dict) -> Optional[int]:
        """校验 Jellyfin 会话是否为新鲜的外网视频播放，并返回其比特率。"""
        item = self.__get_compatible_value(session, "NowPlayingItem", "nowPlayingItem", "Item", "item")
        if not isinstance(item, dict):
            return None

        is_active = self.__get_compatible_value(session, "IsActive", "isActive")
        if is_active is not None and not self.__as_bool(is_active):
            return None

        play_state = self.__get_compatible_value(session, "PlayState", "playState") or {}
        if self.__as_bool(self.__get_compatible_value(play_state, "IsPaused", "isPaused")):
            return None

        last_check_in_value = self.__get_compatible_value(
            session, "LastPlaybackCheckIn", "lastPlaybackCheckIn"
        ) or self.__get_compatible_value(session, "LastActivityDate", "lastActivityDate")
        last_check_in = self.__parse_jellyfin_datetime(last_check_in_value)
        if last_check_in:
            elapsed = (datetime.now(timezone.utc) - last_check_in).total_seconds()
            if elapsed > self._jellyfin_session_timeout:
                logger.debug(f"忽略超过 {self._jellyfin_session_timeout} 秒未上报的 Jellyfin 残留会话")
                return None

        if not self.__is_video_item(item):
            return None
        if self.__path_excluded(self.__get_compatible_value(item, "Path", "path")):
            return None

        remote_ip = self.__normalize_remote_ip(
            self.__get_compatible_value(
                session, "RemoteEndPoint", "remoteEndPoint", "RemoteEndpoint", "remoteEndpoint"
            )
        )
        if not remote_ip:
            logger.debug("Jellyfin 播放会话缺少有效远端地址，跳过限速")
            return None
        if self._unlimited_ips.get("ipv4") or self._unlimited_ips.get("ipv6"):
            if self.__allow_access(self._unlimited_ips, remote_ip):
                return None
        elif IpUtils.is_private_ip(remote_ip):
            return None

        bit_rate = self.__get_jellyfin_bitrate(session, item)
        if not bit_rate:
            logger.debug("检测到 Jellyfin 外网视频播放，但当前会话未提供可用比特率")
        return bit_rate

    def __path_excluded(self, path: Optional[str]) -> bool:
        """
        判断是否在不限速路径内
        """
        if not self._exclude_path or not path:
            return False
        exclude_paths = [exclude_path.strip() for exclude_path in self._exclude_path.splitlines()
                         if exclude_path.strip()]
        for exclude_path in exclude_paths:
            if exclude_path in path:
                logger.info(f"{path} 在不限速路径：{exclude_path} 内，跳过限速")
                return True
        return False
    
    def __calc_limit(self, total_bit_rate: float) -> float:
        """
        计算智能上传限速
        """
        if not self._bandwidth or total_bit_rate > self._bandwidth:
            return 10
        return round((self._bandwidth - total_bit_rate) / 8 / 1024, 2)

    def __set_limiter(self, limit_type: str, upload_limit: float, download_limit: float):
        """
        设置限速
        """
        if not self.service_infos:
            return
        state = f"U:{upload_limit},D:{download_limit}"
        if self._current_state == state:
            # 限速状态没有改变
            return
        else:
            self._current_state = state
            
        try:
            cnt = 0
            for download in self._downloader:
                service = self.service_infos.get(download)
                if self._auto_limit and limit_type == "播放":
                    # 开启了播放智能限速
                    if len(self._downloader) == 1:
                        # 只有一个下载器
                        upload_limit = int(upload_limit)
                    else:
                        # 多个下载器
                        if not self._allocation_ratio:
                            # 平均
                            upload_limit = int(upload_limit / len(self._downloader))
                        else:
                            # 按比例
                            allocation_count = sum([int(i) for i in self._allocation_ratio.split(":")])
                            upload_limit = int(upload_limit * int(self._allocation_ratio.split(":")[cnt]) / allocation_count)
                            cnt += 1
                if upload_limit:
                    text = f"上传：{upload_limit} KB/s"
                else:
                    text = f"上传：未限速"
                if download_limit:
                    text = f"{text}\n下载：{download_limit} KB/s"
                else:
                    text = f"{text}\n下载：未限速"
                if service.type == 'qbittorrent':
                    service.instance.set_speed_limit(download_limit=download_limit, upload_limit=upload_limit)
                    # 发送通知
                    if self._notify:
                        title = "【播放限速】"
                        if upload_limit or download_limit:
                            subtitle = f"Qbittorrent 开始{limit_type}限速"
                            self.post_message(
                                mtype=NotificationType.MediaServer,
                                title=title,
                                text=f"{subtitle}\n{text}"
                            )
                        else:
                            self.post_message(
                                mtype=NotificationType.MediaServer,
                                title=title,
                                text=f"Qbittorrent 已取消限速"
                            )
                else:
                    service.instance.set_speed_limit(download_limit=download_limit, upload_limit=upload_limit)
                    # 发送通知
                    if self._notify:
                        title = "【播放限速】"
                        if upload_limit or download_limit:
                            subtitle = f"Transmission 开始{limit_type}限速"
                            self.post_message(
                                mtype=NotificationType.MediaServer,
                                title=title,
                                text=f"{subtitle}\n{text}"
                            )
                        else:
                            self.post_message(
                                mtype=NotificationType.MediaServer,
                                title=title,
                                text=f"Transmission 已取消限速"
                            )
        except Exception as e:
            logger.error(f"设置限速失败：{str(e)}")

    @staticmethod
    def __allow_access(allow_ips: dict, ip: str) -> bool:
        """
        判断IP是否合法
        :param allow_ips: 充许的IP范围 {"ipv4":, "ipv6":}
        :param ip: 需要检查的ip
        """
        if not allow_ips:
            return True
        try:
            normalized_ip = SpeedLimiter.__normalize_remote_ip(ip)
            if not normalized_ip:
                return False
            ipaddr = ipaddress.ip_address(normalized_ip)
            if ipaddr.version == 4:
                if not allow_ips.get('ipv4'):
                    return True
                allow_ipv4s = allow_ips.get('ipv4').split(",")
                for allow_ipv4 in allow_ipv4s:
                    if allow_ipv4.strip() and ipaddr in ipaddress.ip_network(allow_ipv4.strip(), strict=False):
                        return True
            elif ipaddr.ipv4_mapped:
                if not allow_ips.get('ipv4'):
                    return True
                allow_ipv4s = allow_ips.get('ipv4').split(",")
                for allow_ipv4 in allow_ipv4s:
                    if allow_ipv4.strip() and ipaddr.ipv4_mapped in ipaddress.ip_network(allow_ipv4.strip(), strict=False):
                        return True
            else:
                if not allow_ips.get('ipv6'):
                    return True
                allow_ipv6s = allow_ips.get('ipv6').split(",")
                for allow_ipv6 in allow_ipv6s:
                    if allow_ipv6.strip() and ipaddr in ipaddress.ip_network(allow_ipv6.strip(), strict=False):
                        return True
        except (TypeError, ValueError) as err:
            logger.debug(f"解析不限速地址失败：{str(err)}")
            return False
        return False

    def stop_service(self):
        """停止插件服务；当前没有需要主动释放的资源。"""
        pass
