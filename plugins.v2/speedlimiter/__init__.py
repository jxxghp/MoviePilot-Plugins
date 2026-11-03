import ipaddress
import math
import os
import subprocess
import threading
import time
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
    plugin_version = "2.3.2"
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

    def __init__(self):
        """隔离实例状态，串行处理轮询、Webhook 和停用。"""
        super().__init__()
        self._lock = threading.RLock()
        self._original = {}
        self._applied = {}
        self._last_playing = None
        self._playback_started = None
        self._session_positions = {}
        self._recovering = False
        self._last_raise = 0
        self._recovery_step = 256
        self._unlimited_ips = {}
        self._downloader = []
        self._caps = {}
        self._allocation_mode = "ratio"
        self._headroom = 0
        self._overhead = 1.25
        self._recovery_delay = 30
        self._stopping = False
        self._segment_prediction = False
        self._media_paths = ""
        self._probe_cache = {}
        self._probe_pending = False
        self._probe_generation = 0

    def init_plugin(self, config: dict = None):
        """串行更新配置，保留未恢复的快照供失败重试。"""
        with self._lock:
            self._configure(config)

    def _configure(self, config: dict = None):
        """读取限速和分配设置。"""
        self._original = self._original or self.get_data("original_limits") or {}
        self._applied = self._applied or self.get_data("applied_limits") or {}
        self._downloader = list(dict.fromkeys(self._downloader + list(self._original)))
        self.stop_service()
        self._stopping = False
        self._caps = {}
        config = config or {}
        self._segment_prediction = bool(config.get("segment_prediction"))
        self._media_paths = config.get("media_paths") or ""
        self._enabled = bool(config.get("enabled"))
        self._allocation_mode = config.get("allocation_mode") or "ratio"
        self._interval = max(3, int(config.get("interval") or 60))
        self._headroom = max(0, float(config.get("headroom") or 0)) * 1000000
        self._overhead = max(1, float(config.get("overhead") or 1.25))
        self._recovery_delay = max(0, int(config.get("recovery_delay", 30)))
        self._recovery_step = max(1, min(4096, int(config.get("recovery_step") or 256)))
        for line in (config.get("downloader_limits") or "").splitlines():
            if not line.strip():
                continue
            name, sep, raw = line.rpartition("=")
            try:
                value = float(raw) if sep else -1
            except ValueError:
                value = -1
            if not name.strip() or not math.isfinite(value) or value < 1:
                self._enabled = False
                logger.error("下载器上传上限格式错误，应为 名称=KB/s，且不小于1")
                return
            self._caps[name.strip()] = value

        # 读取配置
        if config:
            self._enabled = bool(config.get("enabled"))
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
            if set(self._caps) - set(self._downloader):
                self._enabled = False
                logger.error("上传上限中有未选择的下载器")
            self._limit_enabled = self._limit_enabled or bool(self._caps)

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
        ] + self._allocation_form(), {
            "enabled": False,
            "recovery_step": 256,
            "segment_prediction": False,
            "media_paths": "",
            "allocation_mode": "ratio",
            "downloader_limits": "",
            "interval": 60,
            "headroom": 0,
            "overhead": 1.25,
            "recovery_delay": 30,
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

    @staticmethod
    def _allocation_form() -> list:
        """追加带宽分配和恢复设置，沿用插件表单组件。"""
        fields = [
            ("VSelect", "allocation_mode", "分配方式", {"items": [
                {"title": "按比例", "value": "ratio"},
                {"title": "按下载器顺序", "value": "priority"}]}),
            ("VTextField", "interval", "检查间隔（秒）", {"type": "number", "min": 3}),
            ("VTextField", "headroom", "预留带宽（Mbps）", {"type": "number", "min": 0}),
            ("VTextField", "overhead", "播放带宽系数", {"type": "number", "min": 1, "step": .05}),
            ("VSwitch", "segment_prediction", "按播放片段预留", {}),
            ("VTextarea", "media_paths", "媒体路径映射", {"placeholder": "媒体服务器路径=MP路径", "rows": 2}),
            ("VTextField", "recovery_step", "每次恢复上传（KB/s）", {"type": "number", "min": 1, "max": 4096}),
            ("VTextField", "recovery_delay", "停止后等待（秒）", {"type": "number", "min": 0}),
            ("VTextarea", "downloader_limits", "下载器上传上限（KB/s）", {
                "placeholder": "下载器名称=3000", "rows": 2}),
        ]
        return [{"component": "VRow", "content": [
            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                {"component": component, "props": {"model": model, "label": label, **props}}]}
            for component, model, label, props in fields]}]

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
        """避免轮询和 Webhook 同时写入不同的限速。"""
        if not self._lock.acquire(blocking=False):
            return
        try:
            if not self._stopping:
                self._check_playing_sessions(event)
        finally:
            self._lock.release()

    def _check_playing_sessions(self, event: Event = None):
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
                "playback.stop", "playback.pause", "playback.unpause",
                "PlaybackPause", "PlaybackUnpause", "media.pause", "media.resume"
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
                    if not res or res.status_code != 200:
                        return
                    if res.status_code == 200:
                        sessions = res.json()
                        for session in sessions:
                            if session.get("NowPlayingItem") and not session.get("PlayState", {}).get("IsPaused"):
                                if not self.__path_excluded(session.get("NowPlayingItem").get("Path")):
                                    playing_sessions.append(session)

                except Exception as e:
                    logger.error(f"获取Emby播放会话失败：{str(e)}")
                    return
                # 计算有效比特率
                for session in playing_sessions:
                    # 设置了不限速范围则判断session ip是否在不限速范围内
                    if self._unlimited_ips["ipv4"] or self._unlimited_ips["ipv6"]:
                        if not self.__allow_access(self._unlimited_ips, session.get("RemoteEndPoint")) \
                                and session.get("NowPlayingItem", {}).get("MediaType") == "Video":
                            has_remote_playback = True
                            self._note_playback(server, session)
                            total_bit_rate += self._playback_bitrate(session) or self._bandwidth
                    # 未设置不限速范围，则默认不限速内网ip
                    elif not IpUtils.is_private_ip(session.get("RemoteEndPoint")) \
                            and session.get("NowPlayingItem", {}).get("MediaType") == "Video":
                        has_remote_playback = True
                        self._note_playback(server, session)
                        total_bit_rate += self._playback_bitrate(session) or self._bandwidth
            elif service.type == "jellyfin":
                req_url = (f"[HOST]Sessions?api_key=[APIKEY]&"
                           f"activeWithinSeconds={self._jellyfin_session_timeout}")
                try:
                    res = service.instance.get_data(req_url)
                    if not res or res.status_code != 200:
                        return
                    if res.status_code == 200:
                        sessions = self.__extract_jellyfin_sessions(res.json())
                        for session in sessions:
                            bit_rate = self.__jellyfin_session_bitrate(session)
                            if bit_rate is None:
                                continue
                            has_remote_playback = True
                            self._note_playback(server, session)
                            total_bit_rate += bit_rate or self._bandwidth
                except Exception as e:
                    logger.error(f"获取Jellyfin播放会话失败：{str(e)}")
                    return
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
                                total_bit_rate += int(session.get("bitrate") or 0) * 1000
                        # 未设置不限速范围，则默认不限速内网ip
                        elif not IpUtils.is_private_ip(session.get("address")) \
                                and session.get("type") == "Video":
                            has_remote_playback = True
                            total_bit_rate += int(session.get("bitrate") or 0) * 1000

        now = time.monotonic()
        if has_remote_playback:
            if self._last_playing is None or now - self._last_playing > self._recovery_delay + self._interval:
                self._playback_started = now
            self._last_playing = now
            self._recovering = True
            # 刚开播或缺少码率时先让出带宽，避免缓存不足反过来低估需求。
            if self._auto_limit and (not total_bit_rate or now - self._playback_started < 15):
                total_bit_rate = max(total_bit_rate, self._bandwidth)
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
            if self._last_playing is not None and now - self._last_playing < self._recovery_delay:
                return
            # 暂停或换集保留限速一段时间，再逐步恢复。
            self.__set_limiter(limit_type="未播放", upload_limit=self._noplay_up_speed,
                               download_limit=self._noplay_down_speed)

    @staticmethod
    def segment_rate(buckets: list, offset: float) -> float:
        """按未来一分钟内的30秒窗口预留，覆盖片段峰值。"""
        start = max(0, int(offset))
        if start + 60 > len(buckets):
            return 0
        return max(sum(buckets[i:i + 30]) * 8 / 30
                   for i in range(start, start + 31))

    def _mapped_media_path(self, path: str) -> Optional[str]:
        if not isinstance(path, str) or not os.path.isabs(path):
            return None
        mappings = []
        for line in self._media_paths.splitlines():
            source, sep, target = line.partition("=")
            if sep and os.path.isabs(source.strip()) and os.path.isabs(target.strip()):
                mappings.append((source.strip().rstrip("/"), target.strip().rstrip("/")))
        for source, target in sorted(mappings, key=lambda row: len(row[0]), reverse=True):
            if path == source or path.startswith(source + "/"):
                return target + path[len(source):]
        return path

    @staticmethod
    def _probe_segment(path: str, start: int, duration: float) -> list:
        """只读取附近压缩包；不解码，不启动网络请求。"""
        result = subprocess.run([
            "ffprobe", "-v", "error", "-read_intervals", f"{start}%+120",
            "-show_packets", "-show_entries", "packet=pts_time,size",
            "-of", "compact=p=0:nk=0", path,
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=20,
            check=True)
        buckets = [0] * 120
        valid = False
        last_timestamp = float(start)
        for line in result.stdout.splitlines():
            values = dict(part.split("=", 1) for part in line.split("|") if "=" in part)
            try:
                timestamp, size = float(values["pts_time"]), int(values["size"])
                index = math.floor(timestamp - start)
                if 0 <= index < 120 and size >= 0:
                    buckets[index] += size
                    valid = True
                    last_timestamp = max(last_timestamp, timestamp)
            except (KeyError, ValueError, OverflowError):
                continue
        if not valid:
            raise ValueError("没有可用的片段数据")
        # seek可能落在前一个关键帧，read_intervals的时长也从那里计算。
        # 未覆盖的尾部不得按零码率处理；片尾之外才允许补零。
        covered = min(120, max(0, math.floor(last_timestamp - start) + 1))
        if duration and duration <= start + covered:
            covered = 120
        return buckets[:covered]

    def _playback_bitrate(self, session: dict) -> float:
        item = session.get("NowPlayingItem") or {}
        fallback = self.__get_jellyfin_bitrate(session, item)
        state = session.get("PlayState") or {}
        # 转码、未知传输方式和不可读文件沿用媒体服务器码率。
        if (not self._segment_prediction or not self._auto_limit
                or session.get("TranscodingInfo")
                or state.get("PlayMethod") not in ("DirectPlay", "DirectStream")):
            return fallback
        try:
            position = float(state["PositionTicks"]) / 10000000
            duration = float(item.get("RunTimeTicks") or 0) / 10000000
            path = self._mapped_media_path(item.get("Path"))
            if not path or not os.path.isfile(path) or position < 0 or not duration:
                return fallback
            stat = os.stat(path)
            start = int(position // 30) * 30
            key = (path, stat.st_size, stat.st_mtime_ns, start)
            cached = self._probe_cache.get(key)
            estimate = fallback
            # 新区间尚未扫描完时，复用仍覆盖未来一分钟的相邻区间。
            candidates = sorted((k for k in self._probe_cache
                                 if k[:3] == key[:3] and k[3] <= position),
                                key=lambda k: k[3], reverse=True)
            for candidate in candidates:
                rate = self.segment_rate(self._probe_cache[candidate], position - candidate[3])
                if rate:
                    estimate = rate * 1.15 / self._overhead
                    break
            if cached is not None or self._probe_pending:
                return estimate
            self._probe_pending = True
            generation = self._probe_generation
            def probe():
                try:
                    buckets = self._probe_segment(path, start, duration)
                except (OSError, ValueError, subprocess.SubprocessError):
                    buckets = []
                with self._lock:
                    if generation != self._probe_generation:
                        return
                    self._probe_pending = False
                    self._probe_cache[key] = buckets
                    while len(self._probe_cache) > 32:
                        self._probe_cache.pop(next(iter(self._probe_cache)))
            threading.Thread(target=probe, name="playback-bitrate", daemon=True).start()
            return estimate
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return fallback

    def _note_playback(self, server: str, session: dict):
        """新会话、恢复播放或明显跳转时重新预留缓存带宽。"""
        state = self.__get_compatible_value(session, "PlayState", "playState") or {}
        item = self.__get_compatible_value(session, "NowPlayingItem", "nowPlayingItem") or {}
        key = (server, session.get("Id") or session.get("DeviceId") or session.get("RemoteEndPoint"),
               item.get("Id") or item.get("Path"))
        position = self.__get_compatible_value(state, "PositionTicks", "positionTicks")
        now = time.monotonic()
        previous = self._session_positions.get(key)
        if position is not None:
            position = float(position) / 10000000
        if (previous is None or now - previous[0] > self._interval * 2.5
                or (position is not None and previous[1] is not None
                    and abs(position - previous[1] - (now - previous[0])) > 10)):
            self._playback_started = now
        self._session_positions[key] = (now, position)
        self._session_positions = {k: v for k, v in self._session_positions.items() if now - v[0] < 300}

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
        """扣除播放预算及预留带宽，返回 KiB/s；零预算也不能写成不限速。"""
        return max(0, (self._bandwidth - total_bit_rate * self._overhead - self._headroom) / 8192)

    @staticmethod
    def allocate_uploads(budget: float, ceilings: list, weights: list = None, priority: bool = False) -> list:
        """在字节预算内分配额度；按顺序时先满足靠前的下载器。"""
        if not ceilings:
            return []
        # 每个下载器至少1字节/s；调用方负责转换到其最小有效单位。
        floors = [min(10240, cap) for cap in ceilings]
        if budget < sum(floors):
            floors = [min(1024, cap) for cap in ceilings]
        remaining = max(0, budget - sum(floors))
        result = list(floors)
        if priority:
            for i, cap in enumerate(ceilings):
                extra = min(remaining, cap - result[i])
                result[i] += extra
                remaining -= extra
            return result
        weights = weights or [1] * len(ceilings)
        result = [0] * len(ceilings)
        active = set(range(len(ceilings)))
        remaining = max(budget, sum(floors))
        while active:
            total = sum(weights[i] for i in active)
            shares = {i: remaining * weights[i] / total for i in active}
            fixed = {i: min(ceilings[i], max(floors[i], shares[i])) for i in active
                     if shares[i] < floors[i] or shares[i] >= ceilings[i]}
            if not fixed:
                for i, value in shares.items():
                    result[i] = value
                break
            for i, value in fixed.items():
                result[i] = value
                remaining -= value
                active.remove(i)
        return result

    @staticmethod
    def _read_limits(service) -> dict:
        """读取实际启用的限速，失败时抛错，不将失败解释为不限速。"""
        if service.type == "qbittorrent":
            transfer = service.instance.qbc.transfer
            down, up = transfer.download_limit, transfer.upload_limit
            unit = 1024
        elif service.type == "transmission":
            session = service.instance.trc.get_session()
            down = session.speed_limit_down if session.speed_limit_down_enabled else 0
            up = session.speed_limit_up if session.speed_limit_up_enabled else 0
            unit = 1000
        else:
            raise ValueError("不支持的下载器")
        if down is None or up is None or min(down, up) < 0:
            raise ValueError("下载器未返回有效限速")
        # qB 原生单位是字节/s；TR 原生单位是十进制 KB/s。
        return {"download": down / 1024 if unit == 1024 else down,
                "upload": up / 1024 if unit == 1024 else up}

    @staticmethod
    def _write_limits(service, down: float, up: float):
        """按下载器原生单位写入，再读回确认；下载参数为空时保持原值。"""
        if service.type == "qbittorrent":
            service.instance.qbc.transfer.upload_limit = int(up * 1024)
            if down is not None:
                service.instance.qbc.transfer.download_limit = int(down * 1024)
        else:
            args = {"speed_limit_up": int(up), "speed_limit_up_enabled": bool(up)}
            if down is not None:
                args.update(speed_limit_down=int(down), speed_limit_down_enabled=bool(down))
            service.instance.trc.set_session(**args)
        actual = SpeedLimiter._read_limits(service)
        if abs(actual["upload"] - up) > 1 or (down is not None and abs(actual["download"] - down) > 1):
            raise RuntimeError("下载器未应用限速")
        return actual

    def __set_limiter(self, limit_type: str, upload_limit: float, download_limit: float):
        """保留各下载器上限，逐个确认写入；失败项留待下轮重试。"""
        services = self.service_infos or {}
        names = [name for name in self._downloader if name in services]
        if not names:
            return
        ceilings, units, valid = [], [], []
        for name in names:
            service = services[name]
            try:
                actual = self._read_limits(service)
                if name not in self._original:
                    original = {**self._original, name: actual}
                    self.save_data("original_limits", original)
                    self._original = original
                cap = self._caps.get(name, self._original[name]["upload"] or self._noplay_up_speed)
                unit = 1000 if service.type == "transmission" else 1024
                # 没有原始上限时以本轮总预算作为该下载器的上限。
                ceilings.append(cap * unit if cap else max(upload_limit * 1024, 1024))
                units.append(unit)
                valid.append(name)
            except Exception:
                logger.warning(f"读取下载器 {name} 限速失败，保持当前设置")
        if not valid:
            return
        if len(valid) != len(self._downloader):
            logger.warning("下载器状态不完整，暂不重新分配带宽")
            return
        if self._auto_limit and limit_type == "播放":
            weights = None
            if self._allocation_ratio and self._allocation_mode != "priority":
                try:
                    ratios = [int(x) for x in self._allocation_ratio.split(":")]
                    if len(ratios) != len(self._downloader) or min(ratios) <= 0:
                        raise ValueError()
                    weights = [ratios[self._downloader.index(name)] for name in valid]
                except ValueError:
                    logger.error("分配比例与下载器数量不匹配")
                    return
            targets = self.allocate_uploads(upload_limit * 1024, ceilings, weights,
                                            self._allocation_mode == "priority")
        else:
            targets = []
            for name, cap, unit in zip(valid, ceilings, units):
                if limit_type == "未播放":
                    value = self._caps.get(name, upload_limit or self._original[name]["upload"])
                else:
                    value = min(upload_limit, cap / unit) if upload_limit else self._caps.get(name, self._original[name]["upload"])
                targets.append(value * unit)
        can_raise = time.monotonic() - self._last_raise >= self._interval * .9
        raised = False
        all_restored = True
        for name, target, unit in zip(valid, targets, units):
            service = services[name]
            up = int(target / unit)
            if limit_type == "播放" and self._auto_limit:
                up = max(1, up)  # 0 在两个下载器中都表示不限速。
            previous = self._applied.get(name)
            if previous and self._recovering and previous["upload"] > 0 and (up == 0 or up > previous["upload"]):
                unlimited = up == 0
                ceiling = up or self._bandwidth / 8 / unit
                next_up = min(ceiling, previous["upload"] + self._recovery_step) if can_raise else previous["upload"]
                up = 0 if unlimited and next_up >= ceiling else int(next_up)
                raised |= up == 0 or up > previous["upload"]
            all_restored &= int(target / unit) == up
            # 未配置下载限速时保留现有下载设置。
            down = download_limit if download_limit else None
            desired = {"upload": up, "download": down}
            try:
                actual = self._read_limits(service)
                if abs(actual["upload"] - up) < 1 and (down is None or abs(actual["download"] - down) < 1):
                    continue
                self._applied[name] = desired
                self.save_data("applied_limits", self._applied)
                self._write_limits(service, down, up)
                logger.info(f"{name} {limit_type}上传限速：{up} KB/s")
                if self._notify:
                    self.post_message(mtype=NotificationType.MediaServer, title="【播放限速】",
                                      text=f"{name} 上传：{up} KB/s")
            except Exception:
                logger.warning(f"设置下载器 {name} 限速失败，下轮重试")
        if raised:
            self._last_raise = time.monotonic()
        if limit_type == "未播放" and all_restored:
            self._recovering = False

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
        """恢复本插件修改的限速；保留失败项，供重载后继续恢复。"""
        with self._lock:
            self._stopping = True
            self._probe_generation += 1
            self._probe_pending = False
            self._probe_cache.clear()
            services = self.service_infos if self._downloader else {}
            for name in list(self._original):
                if name not in (services or {}):
                    continue
                try:
                    actual = self._read_limits(services[name])
                    applied = self._applied.get(name)
                    original = self._original[name]
                    # 不覆盖用户在插件之外修改的设置。
                    if applied and abs(actual["upload"] - applied["upload"]) < 1:
                        down = original["download"] if (applied.get("download") is not None
                                and abs(actual["download"] - applied["download"]) < 1) else None
                        self._write_limits(services[name], down, original["upload"])
                    self._original.pop(name)
                    self._applied.pop(name, None)
                except Exception:
                    logger.warning(f"恢复下载器 {name} 限速失败，保留恢复记录")
            self.save_data("original_limits", self._original)
            self.save_data("applied_limits", self._applied)
