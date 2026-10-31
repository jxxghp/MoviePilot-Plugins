import hmac
import ipaddress
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Header, HTTPException

from app import schemas
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MessageType

try:
    # V3：插件 SDK 事件接口
    from app.sdk.events import Event, eventmanager
except ImportError:  # 旧版主程序兼容
    from app.core.event import Event, eventmanager

# =====================================================================
# 下载器适配层
#
# 插件核心（在线判定、记录归属、恢复确认）只通过 DownloaderAdapter 的 5 个方法
# 操作下载器，不直接调用任何下载器客户端 API。适配其它下载器（如 Transmission）
# 只需：1) 继承 DownloaderAdapter 实现 5 个方法；2) 在 DOWNLOADER_ADAPTERS 中
# 以 MoviePilot 下载器类型（DownloaderHelper.get_services 的 type_filter 值）
# 登记。详见 README“开发者：适配其他下载器”。
# =====================================================================

# 规范化种子状态：适配器必须把客户端原生状态映射为以下之一
TORRENT_STATUSES = ("active", "paused", "errored", "other", "unknown")


class DownloaderAdapter:
    """
    下载器适配器基类（契约）。

    - list_torrents() -> Optional[List[dict]]
        返回 [{"hash": str, "status": TORRENT_STATUSES 之一,
               "upspeed": 字节/秒（数值，无法获取时为 None）}]；
        读取失败必须返回 None（不得返回空列表冒充“没有任务”）。
    - pause(hashes) -> bool
        请求成功返回 True、明确失败返回 False；无法确认是否已执行（超时、
        连接中断等）时应抛出异常，插件会把这些任务保留为“待确认”且不自动恢复。
    - resume(hashes) -> bool
        语义同 pause；插件随后会再调用 list_torrents 读回确认。
    - read_limits() -> Optional[Dict[str, float]]
        返回 {"download": KB/s, "upload": KB/s}，0 = 不限速；读取失败必须返回
        None，绝不能把失败当作 0（否则恢复时会把限速误还原为“不限速”）。
    - write_limits(download, upload) -> bool
        写入全局限速（KB/s，0 = 不限速）；任一项失败返回 False。

    适配器不保存任何插件状态，也不需要处理锁、持久化或下载器归属。
    """

    # MoviePilot 下载器类型标识（与 DownloaderHelper.get_services(type_filter=...) 一致）
    type_name = ""
    # 面板/日志中展示的名称
    display_name = "下载器"

    def __init__(self, instance):
        self.instance = instance

    def list_torrents(self) -> Optional[List[Dict[str, Any]]]:
        raise NotImplementedError

    def pause(self, hashes: List[str]) -> bool:
        raise NotImplementedError

    def resume(self, hashes: List[str]) -> bool:
        raise NotImplementedError

    def read_limits(self) -> Optional[Dict[str, float]]:
        raise NotImplementedError

    def write_limits(self, download: float, upload: float) -> bool:
        raise NotImplementedError


class QbittorrentAdapter(DownloaderAdapter):
    """qBittorrent 适配器：封装 MoviePilot 的 Qbittorrent 模块实例。"""

    type_name = "qbittorrent"
    display_name = "qBittorrent"

    # 活动状态白名单（state_enum 不可用时的字符串兜底）
    ACTIVE_STATES = (
        "downloading", "uploading", "stalledDL", "stalledUP",
        "queuedDL", "queuedUP", "checkingDL", "checkingUP",
        "metaDL", "forcedDL", "forcedUP", "allocating", "moving",
        "checkingResumeData",
    )
    # 暂停状态
    PAUSED_STATES = ("pausedDL", "pausedUP", "stoppedDL", "stoppedUP")

    def list_torrents(self) -> Optional[List[Dict[str, Any]]]:
        torrents, error = self.instance.get_torrents()
        if error:
            return None
        items = []
        for torrent in torrents or []:
            try:
                h = torrent.get("hash")
                if not h:
                    continue
                items.append({
                    "hash": h,
                    "status": self.torrent_status(torrent),
                    "upspeed": torrent.get("upspeed"),
                })
            except Exception as e:
                logger.debug(f"解析种子状态失败: {type(e).__name__}")
        return items

    def pause(self, hashes: List[str]) -> bool:
        return bool(self.instance.stop_torrents(ids=list(hashes)))

    def resume(self, hashes: List[str]) -> bool:
        return bool(self.instance.start_torrents(ids=list(hashes)))

    def read_limits(self) -> Optional[Dict[str, float]]:
        """
        仅通过底层 transfer 属性直接读取（字节/秒 -> KB/s）：读取异常、属性
        不可用或返回值无效时一律返回 None。get_speed_limit() 读取异常时返回
        (0,0)，无法区分失败与无限制，故不使用。
        """
        qbc = getattr(self.instance, "qbc", None)
        if qbc is None:
            logger.error("qBittorrent 底层实例(qbc)不可用，无法可靠读取限速")
            return None
        try:
            download_raw = qbc.transfer.download_limit
            upload_raw = qbc.transfer.upload_limit
            if download_raw is None or upload_raw is None:
                logger.error("读取qBittorrent限速失败: 返回值为None")
                return None
            download_limit = float(download_raw) / 1024
            upload_limit = float(upload_raw) / 1024
            if not (math.isfinite(download_limit) and math.isfinite(upload_limit)):
                logger.error("读取qBittorrent限速失败: 数值无效(NaN/无穷)")
                return None
            # 负值语义未经接口确认，不得擅自当作"无限制"，按读取失败处理
            if download_limit < 0 or upload_limit < 0:
                logger.error("读取qBittorrent限速失败: 数值为负，语义未经确认")
                return None
        except Exception as e:
            logger.error(f"读取qBittorrent限速失败: {type(e).__name__}")
            return None
        return {"download": download_limit, "upload": upload_limit}

    def write_limits(self, download: float, upload: float) -> bool:
        """优先逐项写底层 transfer 属性；任一项失败返回 False（可能已部分生效）。"""
        qbc = getattr(self.instance, "qbc", None)
        if qbc is not None:
            try:
                qbc.transfer.upload_limit = int(round(upload * 1024))
            except Exception as e:
                logger.error(f"设置上传限速失败: {type(e).__name__}")
                return False
            try:
                qbc.transfer.download_limit = int(round(download * 1024))
            except Exception as e:
                logger.error(f"设置下载限速失败: {type(e).__name__}")
                return False
            return True
        try:
            return bool(self.instance.set_speed_limit(download_limit=download, upload_limit=upload))
        except Exception as e:
            logger.error(f"设置qBittorrent限速失败: {type(e).__name__}")
            return False

    @classmethod
    def torrent_status(cls, torrent) -> str:
        """优先使用 state_enum，不可用时按 state 字符串白名单判断"""
        state_enum = None
        try:
            state_enum = torrent.state_enum
        except Exception:
            state_enum = None
        if state_enum is not None:
            try:
                if state_enum.is_errored:
                    return "errored"
                if state_enum.is_paused:
                    return "paused"
                if (
                    state_enum.is_downloading
                    or state_enum.is_uploading
                    or state_enum.is_checking
                ):
                    return "active"
                return "other"
            except Exception:
                pass
        try:
            state = str(torrent.get("state") or "")
        except Exception:
            return "unknown"
        if not state:
            return "unknown"
        if state in cls.PAUSED_STATES:
            return "paused"
        if state.startswith("error") or state == "missingFiles":
            return "errored"
        if state in cls.ACTIVE_STATES:
            return "active"
        return "other"


# 已登记的下载器适配器：键 = MoviePilot 下载器类型（type_filter 值）。
# 适配 Transmission 时在此加入 "transmission": TransmissionAdapter 即可，
# 表单的下载器列表、实例获取、恢复绑定都会自动支持该类型。
DOWNLOADER_ADAPTERS: Dict[str, type] = {
    QbittorrentAdapter.type_name: QbittorrentAdapter,
}


def list_downloader_services() -> Optional[Dict[str, Tuple[str, Any]]]:
    """
    列出 MoviePilot 中所有已登记类型的下载器：{名称: (类型, 原生实例)}。
    宿主 SDK 不可用（旧版主程序）时返回 None；同名服务以先登记的类型为准。
    """
    try:
        from app.sdk.services import DownloaderHelper
    except ImportError:
        return None
    helper = DownloaderHelper()
    found: Dict[str, Tuple[str, Any]] = {}
    for type_name in DOWNLOADER_ADAPTERS:
        services = helper.get_services(type_filter=type_name) or {}
        for name, info in services.items():
            instance = getattr(info, "instance", None)
            if instance is not None and name not in found:
                found[name] = (type_name, instance)
    return found


def make_adapter(type_name: str, instance) -> Optional[DownloaderAdapter]:
    """按下载器类型创建适配器；未登记的类型或空实例返回 None"""
    adapter_cls = DOWNLOADER_ADAPTERS.get(type_name)
    if adapter_cls is None or instance is None:
        return None
    return adapter_cls(instance)


# =====================================================================
# 快照格式（轮询查询 / Webhook 推送共用，与采集端 tunnel_api.py 的契约）
# 详见 README“开发者：快照格式”。schema 缺省视为 1；其它值拒绝。
# =====================================================================
SNAPSHOT_SCHEMA = 1
# 采集端与插件之间的通信密钥请求头（推送与查询共用同一密钥）
SECRET_HEADER = "X-Tunnel-Secret"


# =====================================================================
# Jellyfin / Emby 播放监测
#
# 直接使用 MoviePilot 中已登记的 Jellyfin/Emby 媒体服务器（不需要单独填写地址/密钥），
# 查询播放会话：排除不限速地址与不限速路径后，只要存在正在播放（未暂停）的会话，
# 就与“监控主机在线”一样执行让位（暂停上传任务 / 全局限速）。不受监控主机列表影响。
# =====================================================================
MEDIA_SERVER_TYPES = ("emby", "jellyfin")
# 触发即时检测的媒体服务器 Webhook 事件（其余事件忽略，周期检测兜底）
MEDIA_PLAY_EVENTS = (
    "playback.start", "PlaybackStart", "media.play",
    "playback.unpause", "media.resume",
)
MEDIA_STOP_EVENTS = (
    "playback.stop", "PlaybackStop", "media.stop",
    "playback.pause", "media.pause",
)
# 会话接口
MEDIA_SESSION_URLS = {
    "emby": "[HOST]emby/Sessions?api_key=[APIKEY]",
    "jellyfin": "[HOST]Sessions?api_key=[APIKEY]",
}


def parse_unlimited_ips(raw: str) -> Tuple[List[Any], List[str]]:
    """
    解析不限速地址范围：单个 IPv4/IPv6、CIDR 网段或 起始-结束 区间，
    多个用逗号分隔（兼容中文逗号/分号/换行）。返回 (规则列表, 无效条目列表)。
    规则为 ip_network 或 (起始地址, 结束地址) 元组。
    """
    rules: List[Any] = []
    invalid: List[str] = []
    for token in re.split(r"[,，;；\s]+", str(raw or "")):
        token = token.strip()
        if not token:
            continue
        try:
            if "-" in token and "/" not in token:
                start_s, end_s = token.split("-", 1)
                start = ipaddress.ip_address(start_s.strip())
                end = ipaddress.ip_address(end_s.strip())
                if start.version != end.version or start > end:
                    raise ValueError("区间无效")
                rules.append((start, end))
            else:
                rules.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            invalid.append(token)
    return rules, invalid


def parse_client_ip(value) -> Optional[Any]:
    """
    解析媒体服务器会话的客户端地址（RemoteEndPoint）：兼容 IPv4、IPv6、
    带端口写法（1.2.3.4:5678、[::1]:5678）与 IPv6 区域标识（fe80::1%eth0）。
    无法解析返回 None。
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("["):
        text = text[1:].split("]", 1)[0]
    elif text.count(":") == 1:
        # 仅 IPv4 带端口时只有一个冒号
        text = text.split(":", 1)[0]
    text = text.split("%", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def ip_unlimited(value, rules: List[Any]) -> bool:
    """
    判断客户端地址是否属于不限速地址：
    - 已填写规则：命中任一规则即不限速（IPv4 映射的 IPv6 地址按其 IPv4 判断）
    - 未填写规则：默认内网 / 本机 / 链路本地地址不限速
    - 地址无法解析：按外部地址处理（参与让位）
    """
    addr = parse_client_ip(value)
    if addr is None:
        return False
    candidates = [addr]
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)
    if not rules:
        return any(a.is_private or a.is_loopback or a.is_link_local for a in candidates)
    for a in candidates:
        for rule in rules:
            if isinstance(rule, tuple):
                start, end = rule
                if a.version == start.version and start <= a <= end:
                    return True
            elif a.version == rule.version and a in rule:
                return True
    return False


def list_media_services() -> Dict[str, Tuple[str, Any]]:
    """
    列出 MoviePilot 中已登记的 Jellyfin/Emby 媒体服务器：{名称: (类型, 原生实例)}。
    获取失败抛出异常（调用方按“查询失败”处理，不当作“无播放”）。
    """
    try:
        from app.sdk.services import MediaServerHelper
    except ImportError:  # 旧版主程序兼容
        from app.helper.mediaserver import MediaServerHelper
    services = MediaServerHelper().get_services() or {}
    found: Dict[str, Tuple[str, Any]] = {}
    for name, info in services.items():
        type_name = str(getattr(info, "type", "") or "").lower()
        instance = getattr(info, "instance", None)
        if type_name in MEDIA_SERVER_TYPES and instance is not None and name:
            found[str(name)] = (type_name, instance)
    return found


def fetch_media_sessions(type_name: str, instance) -> Optional[List[dict]]:
    """读取媒体服务器会话列表；请求失败/非200/格式异常返回 None。"""
    url = MEDIA_SESSION_URLS.get(type_name)
    if not url:
        return None
    res = instance.get_data(url)
    if res is None:
        return None
    try:
        if res.status_code != 200:
            return None
        data = res.json()
        return data if isinstance(data, list) else None
    finally:
        try:
            res.close()
        except Exception:
            pass


class TunnelYield(_PluginBase):
    """
    隧道在线带宽让位插件

    通过采集端 tunnel_api.py（内置 EasyTier，提供 WireGuard 参考实现，
    可扩展 IKEv2 等）监控指定主机在线状态：
    - 任一监控主机在线：暂停下载器中有上传流量的任务 或 开启全局限速，腾出上传带宽
    - 全部监控主机离线：恢复本插件暂停的任务，并还原限速原值
    - 主机上线时发送通知（同一主机 1 小时内最多 1 次，离线不通知，可开关）

    检测方式：
    - Webhook推送（默认）：采集端在节点状态变化时推送，插件被动接收；保留
      周期性"补偿检查"（在线期间补暂停新产生上传流量的任务、重试失败的
      暂停/恢复/限速操作）和低频心跳查询兜底（防推送丢失，可关闭）
    - 轮询：按检测周期主动查询采集端 API

    分层：
    - 采集端 TunnelProvider（tunnel_api.py）：把各隧道原生状态转为统一快照
    - 插件核心：快照校验、乱序保护、在线判定、通知、记录归属与恢复确认
    - 下载器适配层 DownloaderAdapter：暂停/恢复/限速的具体客户端调用

    保护机制：
    1. API 查询失败/超时/解析失败 != 主机离线，保持当前状态不动；推送报文
       格式异常/密钥不符/非布尔在线状态一律拒绝，不当作离线处理
    2. 多主机统一判断：任一在线则保持让位，全部明确离线才恢复；存在未知状态不恢复
    3. 只恢复本插件暂停的任务（hash 持久化、暂停成功才归属，重启安全）
    4. 限速前先记录原值（读取失败不修改），恢复时还原并读回确认
    5. 通知冷却按主机独立记录，与在线状态解耦；仅上线时通知
    6. 快照携带采集端单调递增版本号seq（缺失时退回时间戳）：同秒快照、时钟
       回拨、采集端重启都不会让旧快照回滚新状态；同seq同内容按重新同步处理，
       同seq不同内容拒绝
    7. 推送模式下补偿检查带三重防护：成功同步过（同步失败即时撤销）、
       判定绑定当前监控配置、判定未过期

    Jellyfin/Emby 播放监测（可选，不受监控主机列表影响）：
    - 直接使用 MoviePilot 已登记的 Jellyfin/Emby 媒体服务器查询播放会话
    - 排除不限速地址（留空默认排除内网/本机地址）与不限速路径后，只要有播放就让位
    - 与隧道判定是“或”关系：任一来源需要让位即保持让位；监控主机全部离线且
      无播放后才恢复。媒体服务器查询失败 != 无播放：若此前在播放则保持现状
      （最长 MEDIA_UNKNOWN_HOLD 秒）
    """

    # 插件名称
    plugin_name = "隧道在线带宽释放"
    # 插件描述
    plugin_desc = (
        "监控隧道/组网EasyTier内指定主机在线时"
        "暂停下载器有上传流量的任务或开启全局限速（需配合采集端）；"
        "也可监测 Jellyfin/Emby 外部播放自动限速"
    )
    # 插件图标
    plugin_icon = "Librespeed_A.png"
    # 插件版本
    plugin_version = "0.1"
    # 插件作者
    plugin_author = "RamenRa"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "tunnelyield_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 2

    # 通知冷却（秒）：同一主机 1 小时内最多通知 1 次
    NOTIFY_COOLDOWN = 3600
    # 状态文件名
    STATE_FILE = "state.json"
    # 只影响判序/时效的易变字段：单独变化时节流落盘
    VOLATILE_FIELDS = ("seq", "snapshot_ts", "decision_ts", "contact_ts")
    VOLATILE_SAVE_INTERVAL = 600
    # 采集端失联释放：最短时长（分钟，须大于采集端最长保活间隔 25 分钟）与检查间隔（秒）
    LOST_RELEASE_MIN = 30
    LOST_CHECK_INTERVAL = 300
    # 媒体服务器查询失败时（此前在播放/状态未知）保持让位的最长时长（秒）
    MEDIA_UNKNOWN_HOLD = 1800
    # 播放暂停/停止事件后延迟查询（秒）：部分媒体服务器会话状态更新有延迟
    MEDIA_STOP_DELAY = 3
    # 媒体播放通知冷却键（存放于 last_notify，与主机通知冷却相互独立）
    MEDIA_NOTIFY_KEY = "__media__"

    # 类级锁：配置重载、检测、恢复共用同一把锁串行化，避免重载后旧锁失效
    _lock = threading.Lock()
    # 推送版本回退告警的节流时间戳（类级，跨实例共享）
    _last_stale_log = 0.0
    # 进程内只输出一次启动日志（配置重载不重复输出）
    _startup_logged = False
    # 配置代次（类级）：锁外查询媒体服务器期间若配置重载，旧结果作废
    _config_gen = 0

    # ----------------------------------- 私有属性 -----------------------------------
    _enabled: bool = False
    _notify: bool = True
    _api_url: str = ""
    _hosts: str = ""
    _downloader: str = ""
    _downloaders: List[str] = []
    _multi_mode: bool = False
    _root_state = None
    _active_downloader = None
    ACTION_FIELDS = ("released", "paused_hashes", "pending_hashes", "orig_limits", "qb_key")
    _cron: str = "*/1 * * * *"
    _action: str = "pause"  # pause / limit
    _upload_limit: float = 0
    _download_limit: float = 0
    _timeout: int = 10
    _lost_release: int = 60  # 采集端失联释放（分钟），0 = 关闭
    _onlyonce: bool = False
    _detect_mode: str = "webhook"    # webhook（默认） / poll
    _secret: str = ""
    _heartbeat: int = 300
    # Jellyfin/Emby 播放监测
    _media_enabled: bool = False
    _unlimited_ips: str = ""
    _exclude_path: str = ""
    _ip_rules: List[Any] = []
    _exclude_paths: List[str] = []

    # 运行时
    _qb = None
    _qb_key: Optional[str] = None
    _scheduler = None
    _state: Dict[str, Any] = {}
    _last_check_info: Dict[str, Any] = {}
    # 本轮运行期间是否已成功同步过至少一份快照（重启后补偿检查须等待首次同步）
    _synced: bool = False
    # 补偿检查最近一次跳过原因（日志去重，避免周期性刷屏）
    _comp_skip_last: Optional[str] = None
    # 本轮运行中最近一次已执行的下载器动作对应的判定（online/offline/None）：
    # 推送模式下"在线 -> 在线"的保活/心跳快照不再重复扫描下载器，交由补偿检查维护
    _acted_decision: Optional[str] = None
    # 推送模式补偿检查是否已注册（检测周期有效）；未注册时保活快照仍需执行让位
    _comp_scheduled: bool = False
    # 状态落盘去重：上次写入内容（完整/去除易变字段）与时间
    _saved_full: Optional[str] = None
    _saved_stable: Optional[str] = None
    _saved_at: float = 0.0
    # 已提示过的"仅剩待确认暂停"记录签名（空闲时只提示一次）
    _pending_warned: Optional[str] = None
    # 本轮运行开始时间：失联计时的下限（插件自身停机期间不计入采集端失联）
    _run_started: float = 0.0
    # 采集端失联释放已执行（避免重复日志/通知）
    _lost_released: bool = False
    # 播放监测运行时：playing / idle / unknown
    _media_state: str = "unknown"
    # 最近一次成功查询的结论（playing / idle / None=本轮尚未成功）
    _media_last_known: Optional[str] = None
    _media_unknown_since: float = 0.0
    _media_sessions: List[Dict[str, Any]] = []
    _media_info: Dict[str, Any] = {}
    # 已应用的最新查询开始时间（单调时钟）：晚到的旧查询结果不覆盖新结果
    _media_applied_at: float = 0.0
    _gen: int = 0

    def init_plugin(self, config: dict = None):
        # 先在锁外停止旧的一次性调度器：其 shutdown 会等待正在执行的任务结束，
        # 若已持锁再等待（任务又在等这把锁）会形成跨线程等待环导致死锁
        self.__stop_onlyonce_scheduler()
        # 与 check() 通过类级锁串行化：配置重载（含停用恢复）不会与进行中的检测并发，
        # 避免旧检测使用被替换的客户端/状态导致恢复记录丢失或操作错客户端
        with self._lock:
            self.__init_plugin_locked(config)

    def __init_plugin_locked(self, config: dict = None):
        self._last_check_info = {}
        # 配置重载视为新一轮运行：同步标记复位（等待初始同步/推送/心跳刷新）
        self._synced = False
        self._comp_skip_last = None
        self._acted_decision = None
        self._saved_full = None
        self._saved_stable = None
        self._saved_at = 0.0
        self._pending_warned = None
        self._run_started = time.time()
        self._lost_released = False
        TunnelYield._config_gen += 1
        self._gen = TunnelYield._config_gen
        self._media_state = "unknown"
        self._media_last_known = None
        self._media_unknown_since = time.time()
        self._media_sessions = []
        self._media_info = {}
        self._media_applied_at = 0.0

        # 读取配置
        if config:
            self._enabled = bool(config.get("enabled"))
            self._notify = bool(config.get("notify"))
            self._api_url = str(config.get("api_url") or "").strip()
            self._hosts = str(config.get("hosts") or "")
            selection = config.get("downloader", [])
            self._multi_mode = isinstance(selection, list)
            if self._multi_mode:
                self._downloaders = list(dict.fromkeys(
                    value.strip() for value in selection
                    if isinstance(value, str) and value.strip()
                ))
                self._downloader = self._downloaders[0] if self._downloaders else ""
            else:
                # 字符串配置：指定单台，空字符串使用默认下载器。
                self._downloader = str(selection or "").strip()
                self._downloaders = [self._downloader] if self._downloader else []
            self._cron = str(config.get("cron") or "*/1 * * * *").strip()
            action = str(config.get("action") or "pause").strip()
            if action not in ("pause", "limit"):
                # 非法值：按"暂停任务"处理并提示重新选择
                logger.warning(
                    f"带宽释放方式 {action or '(空)'} 不受支持（仅支持 暂停任务/全局限速），"
                    f"已按\"暂停任务\"处理，请在配置中重新选择"
                )
                action = "pause"
            self._action = action
            self._upload_limit = self.__to_num(config.get("upload_limit"), 0)
            self._download_limit = self.__to_num(config.get("download_limit"), 0)
            self._timeout = self.__to_int(config.get("timeout"), 10) or 10
            lost = self.__to_int(config.get("lost_release"), 60)
            if lost < 0:
                lost = 0
            if 0 < lost < self.LOST_RELEASE_MIN:
                logger.warning(
                    f"采集端失联释放时长 {lost} 分钟过短（采集端保活最长 25 分钟一次），"
                    f"已按 {self.LOST_RELEASE_MIN} 分钟处理"
                )
                lost = self.LOST_RELEASE_MIN
            self._lost_release = lost
            self._onlyonce = bool(config.get("onlyonce"))
            # 默认 Webhook推送；未填写或非法值均回退为 Webhook推送
            detect_mode = str(config.get("detect_mode") or "webhook").strip()
            if detect_mode not in ("poll", "webhook"):
                logger.warning(
                    f"检测方式 {detect_mode or '(空)'} 不受支持（仅支持 Webhook推送/轮询），"
                    f"已按\"Webhook推送\"处理，请在配置中重新选择"
                )
                detect_mode = "webhook"
            self._detect_mode = detect_mode
            self._secret = str(config.get("secret") or "").strip()
            self._heartbeat = self.__to_int(config.get("heartbeat"), 300)
            if self._heartbeat < 0:
                self._heartbeat = 0
            self._media_enabled = bool(config.get("media_monitor"))
            self._unlimited_ips = str(config.get("unlimited_ips") or "").strip()
            self._exclude_path = str(config.get("exclude_path") or "")

        # 解析播放监测排除规则
        self._ip_rules, invalid_ips = parse_unlimited_ips(self._unlimited_ips)
        self._exclude_paths = [
            line.strip() for line in (self._exclude_path or "").splitlines() if line.strip()
        ]
        if self._enabled and self._media_enabled and invalid_ips:
            logger.warning(
                f"不限速地址范围中以下条目无法识别，已忽略：{'、'.join(invalid_ips[:10])}"
                "（支持单个IPv4/IPv6、CIDR网段或 起始-结束 区间，多个用逗号分隔）"
            )

        # 推送模式补偿检查是否会被注册（与 get_service 判定一致）
        self._comp_scheduled = False
        if self._enabled and self._detect_mode == "webhook" and self._cron:
            try:
                CronTrigger.from_crontab(self._cron)
                self._comp_scheduled = True
            except Exception:
                self._comp_scheduled = False

        # 获取下载器适配器与持久化状态
        self._root_state = None
        self._active_downloader = None
        # 限速写入失败、待重试的下载器（仅内存，面板展示用；"" = 单台）
        self._limit_failed = set()
        self._qb = self.__init_qb() if not self._multi_mode or self._downloaders else None
        self._state = self.__load_state()
        if self._multi_mode or self._state.get("multi_schema") == 1:
            if not self._multi_mode:
                self._downloaders = [self._qb_key] if self._qb_key else (
                    [self._downloader] if self._downloader else []
                )
                self._multi_mode = True
            if not self.__migrate_downloader_state():
                # 迁移未落盘：本次绝不操作下载器，后续重载再尝试。
                self._enabled = False
                return

        # 启动日志：进程内只输出一次；正常检测周期不再输出常规日志，
        # 仅状态变化（暂停/恢复/限速生效）与异常才有日志
        if self._enabled and not TunnelYield._startup_logged:
            TunnelYield._startup_logged = True
            mode_desc = "Webhook推送（状态变化被动接收+周期补偿）" if self._detect_mode == "webhook" else "轮询"
            logger.info(
                f"隧道在线带宽让位插件已启动并守护运行：检测方式 {mode_desc}，"
                f"检测/补偿周期 {self._cron}，"
                f"监控主机在线时{self.__action_desc()}，全部离线后自动恢复"
                + ("；Jellyfin/Emby 播放监测已开启" if self._media_enabled else "")
            )
            logger.info(
                f"插件所在目录配备README.md文档，详细的使用可以直接把文档交给ai读取"
            )
        if self._enabled and not self._secret and self.__parse_hosts():
            logger.warning(
                "未配置通信密钥：推送报文将被拒绝，查询采集端也会认证失败，"
                "请填写与 tunnel_api.py 配置中 SECRET 一致的通信密钥"
            )

        # 停用插件时恢复现场（暂停的任务 + 限速原值）
        # （init_plugin 已持有类级锁，此处直接恢复，不可重复加锁）
        if not self._enabled:
            self.__restore()

        # 立即检测一次（隧道 + 播放监测）
        if self._enabled and self._onlyonce:
            self._onlyonce = False
            self.__update_config()
            self.__schedule_once(self.sync_once, "立即执行一次检测", 3)
        # 推送模式：插件启动/重载后可能错过停机期间的推送，延迟做一次主动查询同步初始状态；
        # 开启播放监测（或未配置监控主机、需清理遗留记录）时同步一次播放状态
        elif self._enabled and (
            self._detect_mode == "webhook"
            or self._media_enabled
            or not self.__parse_hosts()
        ):
            self.__schedule_once(self.sync_once, "同步初始状态", 3)

    # ----------------------------------- 下载器实例 -----------------------------------

    def __init_qb(self) -> Optional[DownloaderAdapter]:
        """
        获取所选下载器的适配器（DownloaderAdapter），并记录下载服务标识到 self._qb_key。
        V3 通过 app.sdk.services.DownloaderHelper 获取运行中的实例（覆盖
        DOWNLOADER_ADAPTERS 中登记的全部类型）；宿主 SDK 不可用时回退为按系统
        配置自行实例化 qBittorrent 模块（旧版主程序兼容）。
        """
        self._qb_key = None
        try:
            services = list_downloader_services()
        except Exception as e:
            logger.error(f"获取下载器实例失败: {type(e).__name__}")
            return None
        if services is not None:
            if services:
                if self._downloader:
                    found = services.get(self._downloader)
                    if found is None:
                        logger.error(f"未找到名为 {self._downloader} 的受支持下载器")
                        return None
                    key = self._downloader
                else:
                    key = next(iter(services))
                    found = services[key]
                self._qb_key = key
                return make_adapter(*found)
            if self._downloader:
                logger.error(f"未找到名为 {self._downloader} 的受支持下载器")
            else:
                logger.error("未找到已启用的受支持下载器")
            return None
        # 兜底：按系统配置自行实例化 qBittorrent 模块
        try:
            from app.modules.qbittorrent import QbittorrentModule
            module = QbittorrentModule()
            module.init_module()
            self._qb_key = f"module:{self._downloader or 'default'}"
            return make_adapter(QbittorrentAdapter.type_name,
                                module.get_instance(self._downloader or None))
        except Exception as e:
            logger.error(f"初始化 qBittorrent 模块失败: {type(e).__name__}")
            self._qb_key = None
            return None

    def __qb_for_key(self, key: str) -> Optional[DownloaderAdapter]:
        """
        获取指定下载服务标识对应的下载器适配器（用于恢复绑定在其它下载器上的记录），
        不可用时返回 None。
        """
        if not key:
            return None
        if key == self._qb_key and self._qb is not None:
            return self._qb
        try:
            services = list_downloader_services()
            found = services.get(key) if services else None
            return make_adapter(*found) if found else None
        except Exception:
            return None

    @staticmethod
    def __to_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def __to_num(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def __update_config(self):
        """保存插件配置（重置一次性开关）"""
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "api_url": self._api_url,
            "hosts": self._hosts,
            "downloader": self._downloaders if self._multi_mode else self._downloader,
            "cron": self._cron,
            "action": self._action,
            "upload_limit": self._upload_limit,
            "download_limit": self._download_limit,
            "timeout": self._timeout,
            "lost_release": self._lost_release,
            "detect_mode": self._detect_mode,
            "secret": self._secret,
            "heartbeat": self._heartbeat,
            "media_monitor": self._media_enabled,
            "unlimited_ips": self._unlimited_ips,
            "exclude_path": self._exclude_path,
            "onlyonce": False,
        })

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册 Webhook 接收端点（供 tunnel_api.py 推送节点状态）。
        路由最终挂载于 /api/v1/plugin/TunnelYield/webhook（PluginID=插件类名），
        认证 auth=apikey：外部调用需携带 X-API-KEY 头（值为 MoviePilot 的
        API_TOKEN），另加通信密钥双重校验。两种检测模式下均注册（轮询模式下
        报文会被拒绝），避免依赖配置变更时的动态路由刷新。
        """
        return [
            {
                "path": "/webhook",
                "endpoint": self.api_webhook,
                "methods": ["POST"],
                "auth": "apikey",
                "summary": "隧道节点状态推送接收",
                "response_model": schemas.Response[None],
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册周期服务：
        - 轮询模式：按检测周期查询隧道状态API
        - Webhook推送模式：隧道状态由推送驱动，检测周期改为"补偿检查"
          （不查询采集端：在线期间补暂停新产生上传流量的任务、重试失败的
          暂停/恢复/限速操作）；另按心跳间隔注册低频查询兜底（可配0关闭）
        """
        if not self._enabled:
            return []
        services: List[Dict[str, Any]] = []
        trigger = None
        if self._cron:
            try:
                trigger = CronTrigger.from_crontab(self._cron)
            except Exception as e:
                logger.error(f"检测周期配置错误: {type(e).__name__}")
        if trigger is not None and self._detect_mode != "webhook":
            services.append({
                "id": "TunnelYieldCheck",
                "name": "隧道主机在线检测",
                "trigger": trigger,
                "func": self.check,
                "kwargs": {},
            })
        if trigger is not None and self._detect_mode == "webhook":
            services.append({
                "id": "TunnelYieldCompensate",
                "name": "让位补偿检查",
                "trigger": trigger,
                "func": self.compensate,
                "kwargs": {},
            })
        if self._detect_mode == "webhook" and self._heartbeat > 0 and self._api_url:
            services.append({
                "id": "TunnelYieldHeartbeat",
                "name": "推送心跳兜底",
                "trigger": IntervalTrigger(seconds=self._heartbeat),
                "func": self.check,
                "kwargs": {},
            })
        if self._media_enabled:
            # 播放监测：沿用检测周期（无效时每 60 秒），另由媒体服务器 Webhook 事件即时触发
            services.append({
                "id": "TunnelYieldMediaCheck",
                "name": "Jellyfin/Emby 播放检测",
                "trigger": trigger if trigger is not None else IntervalTrigger(seconds=60),
                "func": self.media_check,
                "kwargs": {},
            })
        if self._lost_release > 0 and self.__parse_hosts():
            # 失联检查：无可恢复记录时只比较时间戳，不访问下载器
            services.append({
                "id": "TunnelYieldLostCheck",
                "name": "采集端失联检查",
                "trigger": IntervalTrigger(seconds=self.LOST_CHECK_INTERVAL),
                "func": self.lost_check,
                "kwargs": {},
            })
        return services

    # ----------------------------------- 状态持久化 -----------------------------------

    def __state_file(self) -> str:
        return str(self.get_data_path() / self.STATE_FILE)

    def __load_state(self) -> Dict[str, Any]:
        """加载持久化状态（失败时返回全新状态）"""
        path = self.__state_file()
        state = {
            "released": False,
            "paused_hashes": [],
            "pending_hashes": [],
            "orig_limits": None,
            "qb_key": None,
            "prev_online": {},
            "last_notify": {},
            "alias": {},
            "decision": None,
            "snapshot_ts": None,
            "seq": None,
            "decision_hosts": None,
            "decision_ts": None,
            "snapshot_key": None,
            "contact_ts": None,
        }
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    state.update({
                        "released": bool(data.get("released")),
                        "paused_hashes": list(data.get("paused_hashes") or []),
                        "pending_hashes": list(data.get("pending_hashes") or []),
                        "orig_limits": data.get("orig_limits"),
                        "qb_key": data.get("qb_key"),
                        "prev_online": dict(data.get("prev_online") or {}),
                        "last_notify": dict(data.get("last_notify") or {}),
                        "alias": dict(data.get("alias") or {}),
                        "decision": data.get("decision"),
                        "snapshot_ts": data.get("snapshot_ts"),
                        "seq": data.get("seq"),
                        "decision_hosts": data.get("decision_hosts"),
                        "decision_ts": data.get("decision_ts"),
                        "snapshot_key": data.get("snapshot_key"),
                        "contact_ts": data.get("contact_ts"),
                    })
                    if data.get("multi_schema") == 1:
                        records = data.get("downloaders")
                        if not isinstance(records, dict) or any(
                            not isinstance(k, str) or not isinstance(v, dict)
                            for k, v in records.items()
                        ):
                            raise ValueError("下载器状态记录格式错误")
                        state["multi_schema"] = 1
                        state["downloaders"] = records
        except Exception as e:
            logger.error(f"加载让位状态失败: {type(e).__name__}")
        return state

    def __save_state(self) -> bool:
        """原子化保存状态（临时文件 + 替换），失败返回 False 且调用方不得继续操作下载器"""
        target = self._state
        if self._root_state is not None:
            # 单台操作仍沿用原有安全逻辑，但每次意图/原值落盘都写完整根状态，
            # 不能让其他下载器尚未恢复的记录被当前台覆盖。
            self._root_state["downloaders"][self._active_downloader] = {
                field: self._state.get(field) for field in self.ACTION_FIELDS
            }
            self.__summarize_downloaders(self._root_state)
            target = self._root_state
        path = self.__state_file()
        try:
            # 落盘去重（降低空闲/保活期间的磁盘写入）：
            # - 内容与上次写入完全一致：不写
            # - 仅易变字段（seq/snapshot_ts/decision_ts）变化：最多每 VOLATILE_SAVE_INTERVAL 秒写一次。
            #   安全性：快照内容指纹、判定、下载器记录任何变化都会立即落盘；重启后磁盘上的
            #   seq 至多落后于"最后一次内容变化"之后的同内容快照，此区间内的晚到快照内容与
            #   已落盘内容相同，应用它不会改变判定。decision_ts 仅在本轮已同步时使用，重启后不依赖。
            full = json.dumps(target, ensure_ascii=False, sort_keys=True)
            stable = json.dumps(
                {k: v for k, v in target.items() if k not in self.VOLATILE_FIELDS},
                ensure_ascii=False, sort_keys=True,
            )
            now = time.time()
            if full == self._saved_full:
                return True
            if (
                stable == self._saved_stable
                and 0 <= now - self._saved_at < self.VOLATILE_SAVE_INTERVAL  # 时钟回拨视为已到期
            ):
                return True
            data_dir = os.path.dirname(path)
            if data_dir and not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(full)
            os.replace(tmp, path)
            self._saved_full, self._saved_stable, self._saved_at = full, stable, now
            return True
        except Exception as e:
            logger.error(f"保存让位状态失败: {type(e).__name__}")
            return False

    # ----------------------------------- 主检测流程 -----------------------------------

    def check(self):
        """
        周期检测入口（也用于一次性检测）。
        _enabled 判断放在锁内：等待锁的旧任务在插件停用后不会再执行检测。
        """
        with self._lock:
            if not self._enabled:
                return
            try:
                self.__check()
            except Exception as e:
                logger.error(f"隧道在线检测异常: {type(e).__name__}")

    def __check(self):
        hosts = self.__parse_hosts()
        if not hosts and self._media_enabled:
            # 仅使用播放监测：未配置监控主机时隧道检测静默跳过
            return
        if not self._api_url or not hosts:
            logger.warning("隧道在线带宽让位：未配置API地址或监控主机列表，跳过检测")
            return

        peers, ts, seq, source = self.__query_peers()
        if peers is None:
            # 保护机制1：查询失败/超时/解析失败 != 离线，保持当前状态
            # 同步失败同时撤销补偿检查的动作授权（旧判定不再授权释放/恢复，
            # 等待新的有效快照；恢复记录仍持久化，不丢失）
            self._synced = False
            logger.error("隧道状态API查询失败，本次跳过，保持当前带宽释放状态")
            self._last_check_info = {
                "time": self.__now_str(),
                "result": "API查询失败，保持现状",
                "online": [],
                "error": True,
            }
            return

        self.__apply_peers(peers, ts, seq, source)

    def compensate(self):
        """
        Webhook推送模式的周期补偿检查（不查询采集端）：
        按最近一次已确认的在线判定重执行释放/恢复——在线期间补暂停新产生
        上传流量的任务，失败操作（暂停/恢复/限速）自动重试。
        隧道状态变化仍由推送/心跳负责，此处不重复查询。

        持久化的判定只在同时满足以下条件时才授权补偿动作（判定必须与
        当前配置、当前同步状态绑定，不能无条件相信旧判定）：
        1. 本轮运行期间已成功同步过至少一次（重启后等待初始同步/推送/心跳）
        2. 判定对应的监控主机配置与当前配置一致（清空/修改列表后等待重新判定）
        3. 判定未过期（默认超过1800秒无刷新则不再执行，推送/心跳/保活会刷新）
        """
        with self._lock:
            if not self._enabled or self._detect_mode != "webhook":
                return
            try:
                decision = self._state.get("decision")
                if decision not in ("online", "offline"):
                    return
                if decision == "offline" and not self.__has_recoverable():
                    # 空闲：已确认离线且没有可自动恢复的记录 -> 不访问下载器、不写状态、
                    # 不刷新面板（仅检查内存字段）
                    self.__warn_pending_once()
                    return
                skip = None
                if not self._synced:
                    skip = "尚无成功同步（等待初始同步/推送/心跳），跳过补偿检查"
                else:
                    hosts_now = self.__parse_hosts()
                    bound = self._state.get("decision_hosts")
                    if not isinstance(bound, list) or bound != hosts_now:
                        skip = "监控主机配置已变更，等待推送/心跳重新判定"
                    else:
                        max_age = self.__decision_max_age()
                        if not self.__decision_fresh(self._state.get("decision_ts")):
                            skip = (
                                f"在线判定已超过{max_age}秒未刷新"
                                "（推送/心跳/保活失联），跳过补偿检查"
                            )
                if skip:
                    # 跳过原因记录到面板；日志仅在原因变化时输出一次（不刷屏）
                    self._last_check_info = {
                        "time": self.__now_str(),
                        "result": f"补偿检查跳过：{skip}",
                        "online": [],
                        "error": False,
                    }
                    if skip != self._comp_skip_last:
                        logger.warning(f"隧道在线带宽让位：{skip}")
                        self._comp_skip_last = skip
                    return
                if self._comp_skip_last is not None:
                    self._comp_skip_last = None
                if decision == "online":
                    self.__release()
                elif decision == "offline":
                    # 监控主机全部离线，但 Jellyfin/Emby 仍在播放：保持让位（由播放检测维护）
                    if not self.__media_holds():
                        self.__restore()
                # 未知/无判定：保持现状
            except Exception as e:
                logger.error(f"让位补偿检查异常: {type(e).__name__}")

    def lost_check(self):
        """
        采集端失联释放：超过设定时长没有收到任何有效快照（推送/保活/心跳/轮询均算），
        视为采集端长期离线，恢复本插件暂停的全部任务并还原限速，释放所有操作。
        - 计时起点 = max(最近一次有效联络, 本轮插件启动)，插件自身停机期间不计入
        - 无可恢复记录时只比较时间戳，不访问下载器
        - 释放后判定置为 lost：补偿检查不再按旧判定让位；采集端恢复后由新快照重新判定
        - 恢复失败的记录保留，下一次失联检查继续重试
        """
        with self._lock:
            if not self._enabled or self._lost_release <= 0:
                return
            try:
                self.__lost_check()
            except Exception as e:
                logger.error(f"采集端失联检查异常: {type(e).__name__}")

    def __lost_check(self):
        if not self.__parse_hosts():
            # 未配置监控主机：隧道不参与判定，失联释放不适用（播放监测自行恢复）
            return
        base = self._run_started
        contact = self._state.get("contact_ts")
        if (
            isinstance(contact, (int, float))
            and not isinstance(contact, bool)
            and math.isfinite(contact)
        ):
            base = max(base, contact)
        if time.time() - base < self._lost_release * 60:
            return
        if not self.__has_recoverable():
            if self._state.get("decision") in ("online", "offline"):
                # 无需恢复，但旧判定不再可信：置为 lost，避免之后按旧判定让位
                self._state["decision"] = "lost"
                self._synced = False
                self._acted_decision = None
                self.__save_state()
            self.__warn_pending_once()
            return
        first = not self._lost_released
        self._lost_released = True
        if self.__media_holds():
            # Jellyfin/Emby 仍在播放（或查询失败保持中）：只撤销隧道判定，
            # 让位记录保留，播放结束后由播放检测恢复
            if first:
                logger.warning(
                    f"采集端已超过 {self._lost_release} 分钟没有有效快照，隧道判定已失效；"
                    "Jellyfin/Emby 仍在播放，暂不恢复，播放结束后自动恢复"
                )
            self._state["decision"] = "lost"
            self._synced = False
            self._acted_decision = None
            self.__save_state()
            self._last_check_info = {
                "time": self.__now_str(),
                "result": "采集端失联；Jellyfin/Emby 播放中，保持让位",
                "online": [],
                "error": True,
            }
            return
        msg = (
            f"采集端已超过 {self._lost_release} 分钟没有有效快照，视为长期离线："
            "已恢复本插件暂停的任务并还原限速，等待采集端恢复后重新判定"
        )
        if first:
            logger.warning(msg)
        self._state["decision"] = "lost"
        self._synced = False
        self._acted_decision = None
        self.__save_state()
        self.__restore()
        self.__save_state()
        self._last_check_info = {
            "time": self.__now_str(),
            "result": (
                "采集端失联，已释放全部让位"
                if not self.__has_recoverable()
                else "采集端失联，释放未全部完成，下次失联检查重试"
            ),
            "online": [],
            "error": True,
        }
        if first and self._notify:
            try:
                self.post_message(
                    mtype=MessageType.Plugin,
                    title="【隧道在线带宽让位】",
                    text=msg,
                )
            except Exception as e:
                logger.error(f"发送失联通知失败: {type(e).__name__}")

    # ----------------------------------- Jellyfin/Emby 播放监测 -----------------------------------

    def sync_once(self):
        """一次性同步（启动/重载/立即检测）：先同步隧道状态，再同步播放状态。"""
        if not self._enabled:
            return
        if self.__parse_hosts():
            self.check()
        self.media_check()

    @eventmanager.register(EventType.WebhookMessage)
    def on_media_webhook(self, event: Event = None):
        """
        MoviePilot 收到媒体服务器 Webhook（播放开始/暂停/继续/停止）时即时检测一次；
        需在 Jellyfin/Emby 中配置 MoviePilot 的 Webhook，未配置时由周期检测兜底。
        """
        if not self._enabled or not self._media_enabled or event is None:
            return
        data = getattr(event, "event_data", None)
        name = data.get("event") if isinstance(data, dict) else getattr(data, "event", None)
        if name not in MEDIA_PLAY_EVENTS and name not in MEDIA_STOP_EVENTS:
            return
        if name in MEDIA_STOP_EVENTS:
            # 暂停/停止后会话状态可能稍后才更新，延迟片刻再查询
            time.sleep(self.MEDIA_STOP_DELAY)
        self.media_check()

    def media_check(self):
        """
        播放检测入口（周期 / Webhook 事件 / 一次性同步）。
        媒体服务器查询在锁外进行（避免慢请求阻塞隧道检测），结论在锁内应用：
        配置已重载或结果晚于更新的查询到达时作废。
        """
        if not self._enabled:
            return
        if not self._media_enabled:
            # 播放监测关闭且未配置监控主机：没有任何来源需要让位，清理遗留记录
            with self._lock:
                if self._enabled and not self._media_enabled and not self.__parse_hosts():
                    try:
                        self.__restore()
                    except Exception as e:
                        logger.error(f"恢复遗留让位记录异常: {type(e).__name__}")
            return
        gen = self._gen
        started = time.monotonic()
        try:
            result = self.__query_media()
        except Exception as e:
            logger.error(f"查询 Jellyfin/Emby 播放状态异常: {type(e).__name__}")
            result = {"sessions": None, "servers": [], "failed": [], "error": type(e).__name__}
        with self._lock:
            if (
                not self._enabled
                or not self._media_enabled
                or gen != TunnelYield._config_gen
                or started < self._media_applied_at
            ):
                return
            self._media_applied_at = started
            try:
                self.__apply_media(result)
            except Exception as e:
                logger.error(f"播放监测处理异常: {type(e).__name__}")

    def __query_media(self) -> Dict[str, Any]:
        """
        查询全部已登记 Jellyfin/Emby 的播放会话（锁外执行，不修改插件状态）。
        返回 {"sessions": 需要让位的播放会话列表，查询失败且无播放时为 None,
              "servers": 已查询的服务器名, "failed": 查询失败的服务器名, "error": 错误}
        - 任一服务器有需要让位的播放：sessions 非空（其它服务器失败不影响让位）
        - 无播放但有服务器查询失败：sessions = None（未知，不能当作“无播放”）
        - 未登记任何 Jellyfin/Emby：sessions = []（没有可播放的来源）
        """
        rules = list(self._ip_rules)
        paths = list(self._exclude_paths)
        try:
            services = list_media_services()
        except Exception as e:
            return {"sessions": None, "servers": [], "failed": [],
                    "error": f"获取媒体服务器失败: {type(e).__name__}"}
        playing: List[Dict[str, Any]] = []
        failed: List[str] = []
        for name, (type_name, instance) in services.items():
            try:
                sessions = fetch_media_sessions(type_name, instance)
            except Exception as e:
                logger.debug(f"查询媒体服务器 {name} 会话异常: {type(e).__name__}")
                sessions = None
            if sessions is None:
                failed.append(name)
                continue
            for session in sessions:
                entry = self.__playing_entry(session, name, type_name, rules, paths)
                if entry:
                    playing.append(entry)
        return {
            "sessions": playing if (playing or not failed) else None,
            "servers": list(services),
            "failed": failed,
            "error": None,
        }

    @staticmethod
    def __playing_entry(session, server: str, type_name: str,
                        rules: List[Any], paths: List[str]) -> Optional[Dict[str, Any]]:
        """
        判断单个会话是否需要让位：正在播放（有 NowPlayingItem 且未暂停）、
        客户端地址不在不限速地址内、播放文件路径不含不限速路径。
        需要让位时返回展示信息，否则返回 None。
        """
        if not isinstance(session, dict):
            return None
        item = session.get("NowPlayingItem")
        if not isinstance(item, dict) or not item:
            return None
        media_type = str(item.get("MediaType") or "").strip().lower()
        item_type = str(item.get("Type") or "").strip().lower()
        is_video = (
            media_type == "video"
            or item_type in ("movie", "episode", "video", "trailer", "musicvideo")
            )
        if not is_video:
            return None
        play_state = session.get("PlayState")
        if isinstance(play_state, dict) and play_state.get("IsPaused"):
            return None
        ip = str(session.get("RemoteEndPoint") or "").strip()
        if ip_unlimited(ip, rules):
            return None
        path = str(item.get("Path") or "")
        if path and paths:
            normalized = path.replace("\\", "/")
            for exclude in paths:
                if exclude in path or exclude.replace("\\", "/") in normalized:
                    return None
        title = str(item.get("Name") or "未知条目")
        series = item.get("SeriesName")
        if series:
            title = f"{series} {title}"
        return {
            "server": server,
            "type": type_name,
            "user": str(session.get("UserName") or "未知用户"),
            "device": str(session.get("DeviceName") or session.get("Client") or "未知设备"),
            "ip": ip or "未知地址",
            "item": title,
        }

    def __apply_media(self, result: Dict[str, Any]):
        """应用一次播放查询结论，并据此执行让位 / 恢复（已持有类级锁）。"""
        now = time.time()
        sessions = result.get("sessions")
        servers = result.get("servers") or []
        failed = result.get("failed") or []
        prev_state = self._media_state
        prev_known = self._media_last_known

        if sessions is None:
            # 查询失败 != 无播放：进入未知（此前在播放时保持让位，有时限）
            if prev_state != "unknown":
                self._media_unknown_since = now
                logger.error(
                    "查询 Jellyfin/Emby 播放状态失败"
                    + (f"（{'、'.join(failed)}）" if failed else "")
                    + (f"：{result.get('error')}" if result.get("error") else "")
                    + "，保持当前让位状态"
                )
            self._media_state = "unknown"
            result_text = "查询失败，保持现状"
        else:
            new_state = "playing" if sessions else "idle"
            if new_state == "playing" and prev_known != "playing":
                desc = "；".join(
                    f"{s['user']}@{s['device']}（{s['ip']}）{s['item']}" for s in sessions[:5]
                )
                logger.info(
                    f"检测到 {len(sessions)} 个 Jellyfin/Emby 外部播放，开始让位"
                    f"（{self.__action_desc()}）：{desc}"
                )
                self.__notify_media(sessions)
            elif new_state == "idle" and prev_known == "playing":
                logger.info("Jellyfin/Emby 外部播放已全部结束")
            elif prev_state == "unknown" and prev_known is not None:
                logger.info("Jellyfin/Emby 播放状态查询已恢复")
            if not servers and prev_known is None:
                logger.warning("播放监测：MoviePilot 中未登记 Jellyfin/Emby 媒体服务器")
            self._media_state = new_state
            self._media_last_known = new_state
            self._media_sessions = list(sessions)
            if sessions:
                result_text = f"播放中 {len(sessions)} 个会话"
            elif servers:
                result_text = "无需要让位的播放"
            else:
                result_text = "未登记 Jellyfin/Emby 媒体服务器"
            if failed:
                result_text += f"（{'、'.join(failed)} 查询失败）"

        self._media_info = {
            "time": self.__now_str(),
            "result": result_text,
            "servers": servers,
            "failed": failed,
            "error": sessions is None,
        }

        if self.__media_wants_release():
            # 隧道判定在线且已由轮询/补偿检查维护时不重复扫描下载器
            if not self.__tunnel_maintaining():
                self.__release()
        elif not self.__media_holds() and not self.__tunnel_holds():
            # 无播放 且 隧道不需要让位：恢复（无可恢复记录时不访问下载器）
            self.__restore()

    def __media_wants_release(self) -> bool:
        """播放监测是否要求让位：开启且查询确认存在需要让位的播放。"""
        return bool(self._media_enabled and self._media_state == "playing")

    def __media_holds(self) -> bool:
        """
        播放监测是否阻止恢复：正在播放；或查询失败且此前不是“确认无播放”
        （此前在播放/本轮尚未成功查询），在 MEDIA_UNKNOWN_HOLD 秒内保持现状。
        """
        if not self._media_enabled:
            return False
        if self._media_state == "playing":
            return True
        if self._media_state == "unknown" and self._media_last_known != "idle":
            return time.time() - self._media_unknown_since < self.MEDIA_UNKNOWN_HOLD
        return False

    def __tunnel_holds(self) -> bool:
        """
        隧道判定是否阻止恢复（供播放检测在无播放时判断能否恢复）：
        未配置监控主机 -> 不参与；判定为在线/存在未知主机 -> 阻止；
        离线/失联/尚无判定 -> 不阻止。
        """
        if not self.__parse_hosts():
            return False
        return self._state.get("decision") in ("online", "unknown")

    def __tunnel_maintaining(self) -> bool:
        """隧道判定在线且本轮正由轮询检测 / 推送补偿检查周期性维护让位。"""
        if self._state.get("decision") != "online" or self._acted_decision != "online":
            return False
        if not self._synced or not self.__decision_fresh(self._state.get("decision_ts")):
            return False
        if self._state.get("decision_hosts") != self.__parse_hosts():
            return False
        return self._detect_mode != "webhook" or self._comp_scheduled

    def __notify_media(self, sessions: List[Dict[str, Any]]):
        """播放开始通知：受“上线通知”开关控制，1 小时内最多 1 次（冷却持久化）。"""
        if not self._notify:
            return
        now = time.time()
        last_notify = dict(self._state.get("last_notify") or {})
        if now - float(last_notify.get(self.MEDIA_NOTIFY_KEY) or 0) < self.NOTIFY_COOLDOWN:
            return
        lines = [
            f"{s['user']} @ {s['device']}（{s['ip']}）：{s['item']}" for s in sessions[:5]
        ]
        if len(sessions) > 5:
            lines.append(f"…… 共 {len(sessions)} 个会话")
        try:
            self.post_message(
                mtype=MessageType.Plugin,
                title="【隧道在线带宽让位】",
                text=(
                    "检测到 Jellyfin/Emby 外部播放\n"
                    + "\n".join(lines)
                    + f"\n带宽释放方式：{self.__action_desc()}"
                ),
            )
            last_notify[self.MEDIA_NOTIFY_KEY] = now
            self._state["last_notify"] = last_notify
            self.__save_state()
        except Exception as e:
            logger.error(f"发送播放通知失败: {type(e).__name__}")

    def __decision_max_age(self) -> int:
        """补偿检查判定有效期（秒）：max(心跳×2, 1800)。"""
        return max((self._heartbeat or 0) * 2, 1800)

    def __decision_fresh(self, decision_ts) -> bool:
        return (
            isinstance(decision_ts, (int, float))
            and not isinstance(decision_ts, bool)
            and math.isfinite(decision_ts)
            and time.time() - decision_ts <= self.__decision_max_age()
        )

    def __apply_peers(
        self, peers: Dict[str, Dict[str, Any]], ts: Optional[float],
        seq: Optional[int] = None, source: Optional[str] = None,
    ):
        """
        将一份隧道节点快照应用为带宽释放/恢复动作（轮询与推送共用核心）。
        - seq 为 tunnel_api.py 的单调递增快照版本号：优先用它做乱序保护（同秒快照、
          时钟回拨、采集端重启都不会让旧快照回滚新状态）
        - 同版本（seq 相等）分两种情况：内容一致 -> 按"重新同步"处理（配置变更、
          重启后允许同一份快照在当前配置下重算判定、刷新时效与同步标记）；
          内容不一致 -> 拒绝（不能冒充普通重复消息）
        - 无 seq（采集端未提供）时退回 ts（采集端时间戳）保护：ts < 已应用时间戳的
          旧快照不回滚；两者皆无时直接应用
        返回值：None = 已应用；"stale" = 版本旧于已处理快照，已忽略；
        "conflict" = 同版本不同内容，已忽略；"no_hosts" = 未配置监控主机，未应用
        """
        # 保活跳过让位的前提（在任何状态更新之前记录）：本次推送之前已处于同步状态、
        # 且上一份判定仍在补偿检查的有效期内——否则补偿检查此前可能一直被跳过，
        # 本次必须完整执行一次让位维护
        prior_maintained = self._synced and self.__decision_fresh(self._state.get("decision_ts"))
        # 内容指纹覆盖别名映射的完整信息：peers 索引中同一节点会以 ip 与
        # 主机名多个键出现，同名节点的顺序调换会改变"哪个键指向哪个节点"
        # （影响匹配判定），必须纳入指纹。同版本下主机名变化/映射变化属于
        # 不同内容，按拒绝处理，由新版本号承载。
        content_key = json.dumps(
            sorted((alias, v["ip"], v["hostname"], v["is_online"])
                   for alias, v in peers.items()),
            ensure_ascii=False,
        )
        if seq is not None:
            last_seq = self._state.get("seq")
            if (
                isinstance(last_seq, int)
                and not isinstance(last_seq, bool)
            ):
                if seq < last_seq:
                    # 乱序保护：旧版本快照不回滚新状态
                    return "stale"
                if seq == last_seq:
                    if content_key != self._state.get("snapshot_key"):
                        # 同版本不同内容：拒绝（不能冒充普通重复消息）
                        return "conflict"
                    # 同版本同内容：按重新同步处理（继续应用，
                    # 在当前配置下重算判定并刷新时效/同步标记）
        elif ts is not None:
            last_ts = self._state.get("snapshot_ts")
            if (
                isinstance(last_ts, (int, float))
                and not isinstance(last_ts, bool)
                and math.isfinite(last_ts)
                and ts < last_ts
            ):
                # 乱序保护：晚到的旧快照（如心跳查询先发出、推送后到达）不回滚
                return "stale"

        hosts = self.__parse_hosts()
        if not hosts:
            return "no_hosts"
        # 本轮成功应用：标记已同步（重启后补偿检查须等待首次同步成功），
        # 并刷新采集端最近一次有效联络时间（失联释放计时）
        self._synced = True
        self._state["contact_ts"] = time.time()
        if self._lost_released:
            self._lost_released = False
            logger.info("采集端已恢复联络，按最新快照重新判定")

        # 解析每台主机的在线状态（稳定监控身份：通知/冷却以首个匹配的配置项为身份键，
        # peer 的IP/主机名只作别名——同一主机换IP不会重置通知冷却；
        # 缺失时经别名映射找回同一身份，避免"在线用IP、缺失用配置项"的身份漂移）
        alias = dict(self._state.get("alias") or {})
        alias_changed = False
        resolved: Dict[str, bool] = {}
        display: Dict[str, str] = {}
        has_unknown = False
        for entry in hosts:
            peer = peers.get(entry)
            if peer is None:
                # 在线与否由采集端判定：快照中没有该主机即按离线处理
                # （采集端失败时不会推送/返回快照，不会走到这里）。
                # 身份经别名映射解析，保证与该主机在线时使用同一身份键
                identity = alias.get(entry, entry)
                flag = False
            else:
                # peer 的稳定身份 = 首个匹配它的配置项（持久化），IP/主机名均为其别名
                pkey = peer["key"]
                if pkey not in alias:
                    alias[pkey] = entry
                    alias_changed = True
                identity = alias[pkey]
                if peer.get("ip") and alias.get(peer["ip"]) != identity:
                    alias[peer["ip"]] = identity
                    alias_changed = True
                if peer.get("hostname") and alias.get(peer["hostname"]) != identity:
                    alias[peer["hostname"]] = identity
                    alias_changed = True
                flag = peer["is_online"]
            if flag is None:
                has_unknown = True
                display.setdefault(identity, entry)
                continue
            if identity in resolved:
                resolved[identity] = resolved[identity] or flag
            else:
                resolved[identity] = flag
            display.setdefault(identity, entry)

        online_keys = [k for k, v in resolved.items() if v]
        offline_count = len(resolved) - len(online_keys)

        # 在线判定持久化：推送模式的补偿检查据此重执行，无需重新查询
        if online_keys:
            decision = "online"
        elif not has_unknown and resolved:
            decision = "offline"
        else:
            decision = "unknown"
        state_changed = alias_changed
        if self._state.get("decision") != decision:
            self._state["decision"] = decision
            state_changed = True
        if ts is not None and self._state.get("snapshot_ts") != ts:
            self._state["snapshot_ts"] = ts
            state_changed = True
        if seq is not None and self._state.get("seq") != seq:
            self._state["seq"] = seq
            state_changed = True
        if seq is not None and self._state.get("snapshot_key") != content_key:
            # 已应用快照的内容指纹（同版本重同步的判别依据）
            self._state["snapshot_key"] = content_key
            state_changed = True
        # 判定与当前监控配置绑定：清空/修改监控列表后，补偿检查暂停，等待重新判定
        if self._state.get("decision_hosts") != hosts:
            self._state["decision_hosts"] = list(hosts)
            state_changed = True
        # 判定时效：补偿检查只信任"新鲜"的判定（推送/心跳/保活会持续刷新），
        # 采集端长期失联时不再凭旧判定继续执行释放/恢复
        self._state["decision_ts"] = time.time()
        state_changed = True
        if alias_changed:
            self._state["alias"] = alias
        if state_changed:
            self.__save_state()

        # 上线通知（边沿检测 + 冷却，与在线状态解耦）
        self.__handle_notify(resolved, display)

        self._last_check_info = {
            "time": self.__now_str(),
            "result": (
                f"在线 {len(online_keys)} 台，离线 {offline_count} 台"
                + ("，存在未知状态主机" if has_unknown else "")
            ),
            "online": [display.get(k, k) for k in online_keys],
            "error": False,
            "source": source,
        }

        # 保护机制2：多主机统一判断
        # （常规周期不输出任何例行日志——包括 debug 级别；仅状态变化与异常才有日志）
        if online_keys:
            if (
                self._detect_mode == "webhook"
                and self._comp_scheduled
                and self._acted_decision == "online"
                and prior_maintained
            ):
                # 推送模式下"在线 -> 在线"（保活/心跳/重复推送）：判定未变，
                # 不重复扫描下载器，补暂停/限速维护交给补偿检查
                pass
            else:
                self.__release()
            self._acted_decision = "online"
        elif not has_unknown and resolved:
            # 无可恢复记录时 __restore 直接返回，不访问下载器；
            # Jellyfin/Emby 仍在播放时保持让位（由播放检测维护，播放结束后恢复）
            if not self.__media_holds():
                self.__restore()
            self._acted_decision = "offline"
        else:
            # 存在状态未知的主机：保持当前状态，不输出例行日志；
            # 下一份明确快照到来时重新执行动作
            self._acted_decision = None

    # ----------------------------------- 隧道状态API -----------------------------------

    def __parse_hosts(self) -> List[str]:
        """
        解析监控主机列表：每行一个，支持 IP 或主机名，支持 "IP,主机名" 写法
        """
        hosts: List[str] = []
        for line in (self._hosts or "").splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            for part in line.split(","):
                part = part.strip()
                if part and part not in hosts:
                    hosts.append(part)
        return hosts

    def __safe_err(self, e: Exception) -> str:
        """错误信息脱敏（避免API地址含token泄露到日志）"""
        msg = str(e)
        if self._api_url:
            msg = msg.replace(self._api_url, "***")
        return msg[:200]

    def __query_peers(self) -> Tuple[Optional[Dict[str, Dict[str, Any]]], Optional[float],
                                     Optional[int], Optional[str]]:
        """
        查询采集端 API（轮询/心跳），返回 (peers索引, 采集端时间戳, 快照版本号seq, 来源)：
        - peers：{ip或主机名: {"key": 身份键, "ip": ip, "hostname": 主机名,
          "is_online": True/False/None}}
        - ts：tunnel_api.py 查询接口返回的采集时间戳（采集端未提供时为 None）
        - seq：tunnel_api.py 的单调递增快照版本号（采集端未提供时为 None）
        - 来源：快照的 source 字段（如 easytier/wireguard，仅用于面板展示）
        查询失败、超时、返回无法解析、schema 不受支持、peer_list 为空或包含非法条目时
        返回 (None, None, None, None)
        （调用方必须视为"未知"而非"离线"，防止目标被误判缺失而触发恢复）
        """
        fail = (None, None, None, None)
        try:
            resp = requests.get(
                self._api_url, timeout=self._timeout,
                headers={SECRET_HEADER: self._secret} if self._secret else None,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.Timeout:
            logger.error(f"隧道状态API请求超时（{self._timeout}秒）")
            return fail
        except Exception as e:
            logger.error(f"隧道状态API请求失败: {type(e).__name__} {self.__safe_err(e)}")
            return fail
        if not isinstance(data, dict):
            logger.error("隧道状态API返回格式异常（非JSON对象）")
            return fail
        if not self.__schema_supported(data.get("schema")):
            logger.error("隧道状态API返回的快照 schema 版本不受支持，本次按失败处理")
            return fail
        peer_list = data.get("peer_list")
        if not isinstance(peer_list, list) or not peer_list:
            logger.error("隧道状态API返回peer_list为空或格式异常")
            return fail

        peers = self.__build_peer_index(peer_list, strict=False)
        if peers is None:
            return fail
        return peers, self.__parse_snapshot_ts(data.get("timestamp")), \
            self.__parse_seq(data.get("seq")), self.__parse_source(data.get("source"))

    def __secret_ok(self, value) -> bool:
        """通信密钥校验：两侧均非空且一致才通过（空对空不放行，常数时间比较）"""
        if not self._secret or not isinstance(value, str) or not value:
            return False
        return hmac.compare_digest(value.encode("utf-8"), self._secret.encode("utf-8"))

    @staticmethod
    def __schema_supported(value) -> bool:
        """快照格式版本：缺省视为 1；仅接受整数 SNAPSHOT_SCHEMA"""
        if value is None:
            return True
        return type(value) is int and value == SNAPSHOT_SCHEMA

    @staticmethod
    def __parse_source(value) -> Optional[str]:
        """快照来源（仅展示用，不参与判定）：1~32 位字母/数字/._-，其余忽略"""
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not 0 < len(value) <= 32:
            return None
        if not all(c.isascii() and (c.isalnum() or c in "._-") for c in value):
            return None
        return value

    @staticmethod
    def __parse_seq(value) -> Optional[int]:
        """解析快照版本号：仅接受正整数（布尔排除），其余视为缺失"""
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if value > 0 else None

    @staticmethod
    def __parse_snapshot_ts(value) -> Optional[float]:
        """解析采集端时间戳：仅接受有限正数（秒），其余视为缺失"""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        return float(value)

    def __build_peer_index(
        self, peer_list: list, strict: bool
    ) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        将 peer_list 构建为 {ip或主机名: peer信息} 索引。
        非法条目不能被静默跳过：否则目标会被误判为"缺失->离线"而触发恢复，
        整份报文按失败处理（返回 None）。
        strict=True（webhook推送路径）：is_online 必须为布尔，其余类型一律拒绝；
        strict=False（API查询路径）：经 __parse_online 宽松解析（兼容旧API）。
        """
        peers: Dict[str, Dict[str, Any]] = {}
        for p in peer_list:
            if not isinstance(p, dict):
                logger.error("快照peer_list包含非法条目，本次报文按失败处理")
                return None
            ip = str(p.get("ipv4") or "").split("/")[0].strip()
            hostname = str(p.get("hostname") or "").strip()
            key = ip or hostname
            if not key:
                logger.error("快照peer条目缺少身份信息（ipv4/hostname），本次报文按失败处理")
                return None
            if strict:
                online = p.get("is_online")
                if not isinstance(online, bool):
                    logger.error("推送条目is_online非布尔，本次报文按失败处理")
                    return None
            else:
                online = self.__parse_online(p.get("is_online"))
            info = {
                "key": key,
                "ip": ip,
                "hostname": hostname,
                "is_online": online,
            }
            if ip:
                peers[ip] = info
            if hostname:
                peers[hostname] = info
        return peers

    # ----------------------------------- Webhook 接收 -----------------------------------

    def api_webhook(
        self,
        payload: Dict[str, Any],
        x_webhook_secret: Optional[str] = Header(None, alias=SECRET_HEADER),
    ):
        """
        接收 tunnel_api.py 的节点状态推送（同步端点：由宿主线程池执行，不阻塞事件循环）。
        双重校验：宿主层 X-API-KEY（MoviePilot API_TOKEN）+ 插件层通信密钥。
        报文格式异常（缺 peer_list/非布尔在线状态/非法条目）一律拒绝，
        绝不当作"全部离线"处理。
        """
        if not self._enabled or self._detect_mode != "webhook":
            return schemas.Response(
                success=False,
                message="插件未启用或非Webhook推送模式，报文已忽略",
            )
        # 密钥校验：两侧均非空且一致才通过（空对空不放行）
        if not self.__secret_ok(x_webhook_secret):
            raise HTTPException(status_code=401, detail="通信密钥校验不通过")

        if not isinstance(payload, dict):
            return schemas.Response(success=False, message="推送报文不是JSON对象，已忽略")
        if not self.__schema_supported(payload.get("schema")):
            return schemas.Response(success=False, message="推送报文schema版本不受支持，已忽略")
        peer_list = payload.get("peer_list")
        if not isinstance(peer_list, list) or not peer_list:
            return schemas.Response(success=False, message="推送报文缺少peer_list，已忽略")
        peers = self.__build_peer_index(peer_list, strict=True)
        if peers is None:
            return schemas.Response(success=False, message="推送报文格式异常，已忽略")
        # 推送协议强制携带快照版本号 seq（乱序保护不允许缺失）；
        # 时间戳可选，但携带时必须合法（非法值不得绕过保护）
        seq = self.__parse_seq(payload.get("seq"))
        if seq is None:
            return schemas.Response(success=False, message="推送报文缺少有效seq版本号，已忽略")
        raw_ts = payload.get("timestamp")
        ts = self.__parse_snapshot_ts(raw_ts)
        if raw_ts is not None and ts is None:
            return schemas.Response(success=False, message="推送报文时间戳非法，已忽略")

        # 与轮询/心跳路径共用核心逻辑，类级锁串行化
        with self._lock:
            if not self._enabled or self._detect_mode != "webhook":
                return schemas.Response(success=False, message="插件状态已变更，报文已忽略")
            try:
                outcome = self.__apply_peers(peers, ts, seq, self.__parse_source(payload.get("source")))
            except Exception as e:
                logger.error(f"处理隧道状态推送异常: {type(e).__name__}")
                return schemas.Response(success=False, message="处理推送异常")
        # success=True 表示报文已接收（采集端无需重试）；未应用的原因通过 message 区分。
        # 版本回退/冲突通常意味着采集端 seq 回退（如多个采集器并存、状态文件丢失），
        # 重试同一版本也无济于事，故不返回失败，但需让运维可见。
        notes = {
            "stale": "推送已接收但未应用：seq 小于已处理版本（采集端 seq 可能回退）",
            "conflict": "推送已接收但未应用：同 seq 内容不同（采集端 seq 可能回退或多采集器并存）",
            "no_hosts": "推送已接收但未应用：插件未配置监控主机",
        }
        if outcome in ("stale", "conflict"):
            now = time.time()
            if now - TunnelYield._last_stale_log >= 600:
                TunnelYield._last_stale_log = now
                logger.warning(notes[outcome] + "，请检查采集端（10分钟内仅提示一次）")
        if outcome in notes:
            return schemas.Response(success=True, message=notes[outcome])
        return schemas.Response(success=True, message="推送已处理")

    @staticmethod
    def __parse_online(value) -> Optional[bool]:
        """
        严格解析在线状态，避免字符串 "false"、非法数值被误判：
        - bool：直接返回
        - 数值：仅 1/0 有效，其余为未知
        - 字符串：true/false/1/0/yes/no/online/offline（不区分大小写）
        - 其它：未知（None）
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value == 1:
                return True
            if value == 0:
                return False
            return None
        if isinstance(value, float):
            if value == 1.0:
                return True
            if value == 0.0:
                return False
            return None
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes", "online"):
                return True
            if v in ("false", "0", "no", "offline"):
                return False
        return None

    # ----------------------------------- 通知 -----------------------------------

    def __handle_notify(self, resolved: Dict[str, bool], display: Dict[str, str]):
        """
        保护机制5：仅上线时通知（离线不通知），同一主机1小时内最多1次。
        - 冷却记录按主机独立保存，查询失败时不会清空
        - 在线状态查询成功才更新（离线回写False，供下次边沿检测）
        - 未知状态的主机保持原记录不变
        """
        now = time.time()
        prev_online = dict(self._state.get("prev_online") or {})
        last_notify = dict(self._state.get("last_notify") or {})
        state_changed = False

        for key, online in resolved.items():
            was = prev_online.get(key)
            if online:
                if was is not True:
                    prev_online[key] = True
                    state_changed = True
                    # 上线边沿 + 冷却检查
                    if now - last_notify.get(key, 0) >= self.NOTIFY_COOLDOWN:
                        if self._notify:
                            try:
                                self.post_message(
                                    mtype=MessageType.Plugin,
                                    title="【隧道上线带宽限速】",
                                    text=(
                                        f"监控主机 {display.get(key, key)} 已上线\n"
                                        f"带宽限速方式：{self.__action_desc()}"
                                    ),
                                )
                                # 仅实际发送成功才消耗冷却：关闭通知/发送失败
                                # 不占用本次冷却窗口
                                last_notify[key] = now
                            except Exception as e:
                                logger.error(f"发送主机上线通知失败: {type(e).__name__}")
            else:
                if was is not False:
                    prev_online[key] = False
                    state_changed = True

        if state_changed:
            self._state["prev_online"] = prev_online
            self._state["last_notify"] = last_notify
            self.__save_state()

    def __action_desc(self) -> str:
        return {
            "pause": "暂停有上传流量的任务",
            "limit": "开启全局限速",
        }.get(self._action, self._action)

    # ----------------------------------- 带宽释放 -----------------------------------

    @staticmethod
    def __empty_downloader_state():
        return {"released": False, "paused_hashes": [], "pending_hashes": [],
                "orig_limits": None, "qb_key": None}

    @staticmethod
    def __has_downloader_records(record):
        return bool(record.get("released") or record.get("paused_hashes")
                    or record.get("pending_hashes") or record.get("orig_limits") is not None)

    @staticmethod
    def __summarize_downloaders(state):
        records = state.get("downloaders", {}).values()
        state["released"] = any(r.get("released") for r in records)
        # 根层仅为兼容详情汇总；真实任务归属始终以 downloaders[name] 为准。
        state["paused_hashes"] = []
        state["pending_hashes"] = []
        state["orig_limits"] = None
        state["qb_key"] = None

    def __migrate_downloader_state(self):
        if self._state.get("multi_schema") != 1:
            record = {field: self._state.get(field) for field in self.ACTION_FIELDS}
            key = record.get("qb_key") or self._qb_key
            if self.__has_downloader_records(record) and not key:
                logger.error("旧记录无法确定下载器归属，停止迁移，请恢复原配置后重试")
                return False
            self._state["downloaders"] = {key: record} if key else {}
            self._state["multi_schema"] = 1
        self.__summarize_downloaders(self._state)
        return self.__save_state()

    def __run_downloaders(self, release):
        """已持有类级锁；单台失败隔离；取消勾选的旧记录保留到离线/停用后恢复。"""
        root = self._state
        selected = list(self._downloaders)
        # 有记录但取消勾选：沿用原有“在线仍让位，离线后恢复”的切换保护。
        if release:
            keys = list(dict.fromkeys(selected + [
                key for key, record in root.get("downloaders", {}).items()
                if self.__has_downloader_records(record)
            ]))
        else:
            # 恢复只处理有可自动恢复记录的下载器，其余下载器不访问
            keys = [
                key for key, record in root.get("downloaders", {}).items()
                if isinstance(record, dict) and self.__recoverable(record)
            ]
        old_qb, old_key, old_name = self._qb, self._qb_key, self._downloader
        try:
            for key in keys:
                record = root["downloaders"].setdefault(key, self.__empty_downloader_state())
                self._state = dict(root)
                self._state.update(record)
                self._root_state = root
                self._active_downloader = key
                self._downloader = key
                self._qb_key = key
                # 每次重新从宿主获取，避免某台重连/重载后持有旧实例。
                self._qb = None
                try:
                    self._qb = self.__qb_for_key(key)
                    if self._qb is None:
                        logger.error(f"下载器 {key} 不可用，保留其记录，继续处理其他下载器")
                        continue
                    if release:
                        self.__release_one()
                    else:
                        self.__restore_one()
                except Exception as e:
                    logger.error(f"下载器 {key} 操作异常: {type(e).__name__}，继续处理其他下载器")
                finally:
                    root["downloaders"][key] = {
                        field: self._state.get(field) for field in self.ACTION_FIELDS
                    }
        finally:
            self._state = root
            self._root_state = None
            self._active_downloader = None
            self._qb, self._qb_key, self._downloader = old_qb, old_key, old_name
            self.__summarize_downloaders(root)
            self.__save_state()

    def __release(self):
        if self._multi_mode:
            self.__run_downloaders(release=True)
        else:
            self.__release_one()

    @staticmethod
    def __recoverable(record) -> bool:
        """记录中是否有可自动恢复的内容（待确认暂停不会自动恢复，不计入）"""
        return bool(record.get("released") or record.get("paused_hashes")
                    or record.get("orig_limits") is not None)

    def __record_items(self) -> List[Tuple[str, dict]]:
        if self._multi_mode:
            return [(k, r) for k, r in (self._state.get("downloaders") or {}).items()
                    if isinstance(r, dict)]
        return [("", self._state)]

    def __has_recoverable(self) -> bool:
        return any(self.__recoverable(r) for _, r in self.__record_items())

    def __warn_pending_once(self):
        """空闲但仍有待确认暂停：同一组记录只提示一次"""
        pending = sorted(
            f"{k}:{h}" for k, r in self.__record_items() for h in (r.get("pending_hashes") or [])
        )
        sig = json.dumps(pending) if pending else None
        if sig != self._pending_warned:
            self._pending_warned = sig
            if pending:
                logger.warning(
                    f"存在 {len(pending)} 个未确认的暂停意图"
                    f"（暂停请求结果未知或可能为用户手动暂停），插件不会自动恢复，请手动处理"
                )

    def __restore(self):
        if not self.__has_recoverable():
            # 空闲：没有可自动恢复的记录 -> 不获取下载器实例、不访问下载器
            # （仅清理遗留的空下载器绑定，纯状态操作，无变化不写盘）
            changed = False
            for _, record in self.__record_items():
                if record.get("qb_key") is not None and not (record.get("pending_hashes") or []):
                    record["qb_key"] = None
                    changed = True
            if changed:
                self.__save_state()
            self.__warn_pending_once()
            return
        if self._multi_mode:
            self.__run_downloaders(release=False)
        else:
            self.__restore_one()

    def __release_one(self):
        """
        执行带宽释放（幂等，可重入）：
        - pause：暂停有上传流量的任务（空闲做种不动，产生流量后下次检测补暂停）
        - limit：记录原限速后设置新限速（设置失败下次重试）
        只要存在已落盘的释放记录（paused_hashes 或 orig_limits），即标记为释放状态，
        确保后续离线时能够恢复。
        释放记录绑定下载器标识（qb_key）：存在未恢复记录时若用户切换了下载器，
        继续管理原下载器（目标在线不中断让位），待全部离线恢复完成后再切换到新下载器。
        """
        if self._qb is None:
            self._qb = self.__init_qb()
        if self._qb is None:
            logger.error("下载器实例不可用，跳过带宽让位")
            return

        # 下载器绑定只在真正存在释放记录（pending/paused/orig_limits）时有效：
        # 空绑定（无任何记录）在使用前清除，避免其阻塞当前下载器或误在原下载器上创建新记录
        rec_key = self._state.get("qb_key")
        if rec_key and not (
            (self._state.get("paused_hashes") or [])
            or (self._state.get("pending_hashes") or [])
            or self._state.get("orig_limits") is not None
        ):
            rec_key = None
            self._state["qb_key"] = None
            self.__save_state()

        qb = self._qb
        if rec_key and rec_key != self._qb_key:
            # 有效记录 + 下载器已切换：继续管理原下载器（不中断让位）。
            # 不输出例行提示日志——这是延后切换的正常状态，仅事件/异常才有日志
            qb = self.__qb_for_key(rec_key)
            if qb is None:
                logger.error(
                    f"下载器已切换（{rec_key} -> {self._qb_key}），"
                    f"但原下载器不可用，保留记录暂不释放，待全部离线恢复"
                )
                return
        # 注意：qb_key 不在此处预先绑定——仅当真正产生释放记录
        # （pending/paused/orig_limits）时才绑定，避免"无任务可暂停"时
        # 留下空绑定，阻塞后续切换下载器

        if self._action == "pause":
            self.__release_pause(qb)

        if self._action == "limit":
            self.__release_limit(qb)

        if (self._state.get("paused_hashes") or []) or self._state.get("orig_limits") is not None:
            self._state["released"] = True
            self.__save_state()
        elif (
            not (self._state.get("pending_hashes") or [])
            and self._state.get("qb_key") is not None
        ):
            # 无任何释放记录：清除可能遗留的空绑定
            self._state["qb_key"] = None
            self.__save_state()

    def __release_pause(self, qb=None):
        """
        暂停有上传流量的任务（意图与确认归属分离）：
        - 暂停意图先落盘为 pending_hashes（崩溃安全），此时不算"插件已暂停"
        - 停止请求成功才确认为插件暂停归属（paused_hashes，可自动恢复）
        - 停止请求失败：撤销新增意图；请求抛异常（无法区分是否已执行）时
          保留为 pending 并提示用户处理，绝不自动恢复
        - 每次重入先调和旧 pending：已变活动的意图说明暂停未执行，丢弃后重新暂停；
          仍处于暂停的意图无法区分是插件暂停还是用户手动暂停，保留为 pending 不自动恢复
        qb 参数用于下载器切换后继续管理原下载器（记录绑定的下载器）。
        """
        qb = qb or self._qb
        state = self._state
        torrents = self.__list_torrents(qb)
        if torrents is None:
            logger.error("获取下载器种子列表失败，跳过本次暂停操作")
            return

        existing, paused_now = self.__index_torrents(torrents)
        active = self.__active_hashes(torrents)

        # 调和旧 pending 意图
        pending = list(state.get("pending_hashes") or [])
        dropped = [h for h in pending if not (h in existing and h in paused_now)]
        if dropped:
            pending = [h for h in pending if h not in dropped]
            state["pending_hashes"] = pending
            self.__save_state()
            logger.info(f"{len(dropped)} 个未执行的暂停意图已丢弃，将重新暂停")

        tracked = list(state.get("paused_hashes") or [])
        tracked_set = set(tracked)
        pending_set = set(pending)
        new_hashes = [h for h in active if h not in tracked_set and h not in pending_set]

        if new_hashes:
            # 产生暂停意图时绑定下载器标识（仅当尚无绑定时）
            if state.get("qb_key") is None:
                state["qb_key"] = self._qb_key
            # 先落盘暂停意图（崩溃安全）；停止成功后才确认归属
            state["pending_hashes"] = pending + new_hashes
            if not self.__save_state():
                state["pending_hashes"] = pending
                logger.error("状态保存失败，本次不执行暂停")
                return

        if not active:
            return

        try:
            stopped = qb.pause(list(active))
        except Exception as e:
            # 请求异常：无法区分是否已执行，保留 pending 提示用户处理，不自动恢复
            logger.error(
                f"暂停请求异常: {type(e).__name__}，意图保留为待确认，不会自动恢复，请检查"
            )
            return

        if stopped:
            logger.info(f"已暂停 {len(active)} 个有上传流量的任务")
            # 停止请求成功：确认归属
            state["paused_hashes"] = tracked + new_hashes
            state["pending_hashes"] = [
                h for h in (state.get("pending_hashes") or [])
                if h not in set(new_hashes)
            ]
            self.__save_state()
        else:
            # 暂停请求失败：撤销新增意图，避免误恢复用户手动暂停的任务
            if new_hashes:
                state["pending_hashes"] = pending
                self.__save_state()
            logger.error("暂停下载器任务失败，将在下次检测时重试")

    def __release_limit(self, qb=None):
        """
        设置全局限速：先读取并落盘原值，再修改。
        - 读取失败（None）则不修改，下次重试
        - 设置失败保留原值快照，恢复时会尝试还原（可能部分生效，必须还原）
        - 限速值 0 = 不限速（写入0即取消限速）；已生效时跳过重复写入
        qb 参数用于下载器切换后继续管理原下载器（记录绑定的下载器）。
        """
        qb = qb or self._qb
        if self._state.get("orig_limits") is None:
            limits = self.__read_limits_raw(qb=qb)
            if limits is None:
                logger.error("读取下载器当前限速失败，跳过限速操作")
                return
            # 保护机制4：先记录原值并落盘，再修改；产生快照时绑定下载器标识
            if self._state.get("qb_key") is None:
                self._state["qb_key"] = self._qb_key
            self._state["orig_limits"] = limits
            if not self.__save_state():
                self._state["orig_limits"] = None
                logger.error("状态保存失败，本次不执行限速")
                return

        orig = self._state["orig_limits"]
        # 0 = 不限速：上传/下载限速值按配置原样写入（下载0即取消下载限速）
        new_upload = float(self._upload_limit)
        new_download = float(self._download_limit)

        # 已生效则跳过：避免每个检测周期重复写入与刷日志
        current = self.__read_limits_raw(qb=qb)
        if current is not None and (
            abs(current["upload"] - new_upload) < 1 / 1024
            and abs(current["download"] - new_download) < 1 / 1024
        ):
            self._limit_failed.discard(self._active_downloader or "")
            return

        if self.__write_limits_raw(new_download, new_upload, qb=qb):
            self._limit_failed.discard(self._active_downloader or "")
            logger.info(
                f"已设置全局限速: 上传 {new_upload} KB/s，下载 {new_download} KB/s（0=不限速）"
                f"（原值: 上传 {orig['upload']} KB/s，下载 {orig['download']} KB/s）"
            )
        else:
            self._limit_failed.add(self._active_downloader or "")
            logger.error("设置下载器限速失败，已保留原值快照，恢复时会尝试还原")

    def __read_limits_raw(self, qb=None) -> Optional[Dict[str, float]]:
        """
        经适配器读取当前全局限速（KB/s，0=无限制），并在核心侧再次校验：
        异常、非字典、缺字段、非数字/布尔/NaN/无穷/负值一律返回 None，
        调用方不得据此修改限速，也绝不能把读取失败误判为"无限制"。
        """
        adapter = qb or self._qb
        try:
            limits = adapter.read_limits()
        except Exception as e:
            logger.error(f"读取下载器限速失败: {type(e).__name__}")
            return None
        if not isinstance(limits, dict):
            return None
        result = {}
        for field in ("download", "upload"):
            value = limits.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                logger.error("读取下载器限速失败: 适配器返回值无效")
                return None
            if not math.isfinite(value) or value < 0:
                logger.error("读取下载器限速失败: 数值无效(负数/NaN/无穷)")
                return None
            result[field] = float(value)
        return result

    def __write_limits_raw(self, download: float, upload: float, qb=None) -> bool:
        """
        经适配器设置全局限速（KB/s）。失败或异常返回 False（可能已部分生效，
        调用方必须保留原值快照以便恢复时还原）。
        """
        adapter = qb or self._qb
        try:
            return adapter.write_limits(download, upload) is True
        except Exception as e:
            logger.error(f"设置下载器限速失败: {type(e).__name__}")
            return False

    # ----------------------------------- 恢复 -----------------------------------

    def __restore_one(self):
        """
        恢复带宽（全部主机离线或停用插件时调用）：
        - 只恢复本插件暂停且当前仍处于暂停状态的任务（恢复后重新查询确认）
        - 限速还原为记录的原值，并读回确认后才清除快照（原值0=还原为无限制）
        - 任务恢复与限速恢复相互独立，各自确认成功后才清理对应记录
        - 任一步骤失败则保留记录，下次检测重试
        - 依据待处理记录（而非单一 released 标志）判断是否需要恢复，
          避免崩溃窗口导致无法恢复
        """
        state = self._state
        has_records = bool(
            state.get("released")
            or (state.get("paused_hashes") or [])
            or (state.get("pending_hashes") or [])
            or state.get("orig_limits") is not None
        )
        if not has_records:
            # 无任何记录：清除可能遗留的空绑定（状态文件中可能留下），
            # 避免其阻塞后续切换下载器（改选新下载器后仍按旧绑定管理）
            if state.get("qb_key") is not None:
                state["qb_key"] = None
                self.__save_state()
            return

        # 存在未确认的暂停意图：无法区分是插件暂停还是用户手动暂停，不自动恢复
        pending = list(state.get("pending_hashes") or [])
        if pending:
            logger.warning(
                f"存在 {len(pending)} 个未确认的暂停意图"
                f"（暂停请求结果未知或可能为用户手动暂停），插件不会自动恢复，请手动处理"
            )

        # 恢复使用记录绑定的下载器（与当前所选无关，即使当前下载器不可用也能恢复原下载器），
        # 避免把 A 下载器的限速原值写入 B、或误启动 B 上同 hash 的手动暂停任务
        rec_key = state.get("qb_key")
        qb = None
        if rec_key:
            if rec_key == self._qb_key and self._qb is not None:
                qb = self._qb
            else:
                qb = self.__qb_for_key(rec_key)
                if qb is None:
                    logger.error(
                        f"下载器 {rec_key} 不可用，无法恢复其记录，保留待下次重试"
                    )
                    return
        if qb is None:
            qb = self._qb
        if qb is None:
            qb = self.__init_qb()
        if qb is None:
            logger.error("下载器实例不可用，暂无法恢复，保留记录待下次重试")
            return

        # ---- 限速恢复（独立确认） ----
        orig = state.get("orig_limits")
        if orig is not None:
            if self.__write_limits_raw(orig["download"], orig["upload"], qb=qb):
                current = self.__read_limits_raw(qb=qb)
                if current is None:
                    logger.warning("限速还原后读回失败，保留原值快照待下次确认")
                elif (
                    abs(current["download"] - orig["download"]) < 1 / 1024
                    and abs(current["upload"] - orig["upload"]) < 1 / 1024
                ):
                    # 精确到 1 B/s：换算回字节后完全一致才算还原成功
                    state["orig_limits"] = None
                    logger.info(
                        f"已恢复原有全局限速: 上传 {orig['upload']} KB/s，"
                        f"下载 {orig['download']} KB/s"
                    )
                else:
                    logger.warning("限速还原读回不一致，保留快照待下次重试")
            else:
                logger.error("恢复下载器限速失败，将在下次检测时重试")

        # ---- 任务恢复（独立确认） ----
        hashes = list(state.get("paused_hashes") or [])
        if hashes:
            torrents = self.__list_torrents(qb)
            if torrents is None:
                logger.error("获取下载器种子列表失败，暂不恢复任务，下次检测重试")
            else:
                existing, paused_now = self.__index_torrents(torrents)
                to_resume = [h for h in hashes if h in paused_now]
                if to_resume:
                    if qb.resume(to_resume):
                        logger.info(f"已恢复 {len(to_resume)} 个任务")
                        # 重新查询确认实际状态；仍处于暂停的保留待下次重试
                        torrents2 = self.__list_torrents(qb)
                        if torrents2 is not None:
                            existing, paused_now = self.__index_torrents(torrents2)
                    else:
                        logger.error("恢复下载器任务失败，将在下次检测时重试")
                # 保留：仍存在 且 仍处于暂停状态 的记录
                # （已删除/已被用户处理/已确认恢复的都会被清理）
                state["paused_hashes"] = [
                    h for h in hashes if h in existing and h in paused_now
                ]

        # ---- 收尾：无待处理记录才算恢复完成 ----
        # pending 仍是未处理记录：保留其下载器归属（qb_key），不得跨下载器重新解释
        if not (state.get("paused_hashes") or []) and state.get("orig_limits") is None:
            state["released"] = False
            if not (state.get("pending_hashes") or []):
                state["qb_key"] = None
        else:
            state["released"] = True
        self.__save_state()

    # ----------------------------------- 种子工具方法（下载器无关） -----------------------------------

    @staticmethod
    def __list_torrents(adapter) -> Optional[List[Dict[str, Any]]]:
        """
        经适配器读取种子列表并在核心侧校验：异常或非列表返回 None（读取失败）；
        单个条目缺少 hash 时跳过，status 不在 TORRENT_STATUSES 中按 unknown 处理
        （unknown 既不会被暂停，也不会被当作“仍在暂停”而恢复）。
        """
        try:
            items = adapter.list_torrents()
        except Exception as e:
            logger.error(f"读取下载器种子列表异常: {type(e).__name__}")
            return None
        if not isinstance(items, list):
            return None
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            h = item.get("hash")
            if not isinstance(h, str) or not h:
                continue
            status = item.get("status")
            if status not in TORRENT_STATUSES:
                status = "unknown"
            normalized.append({"hash": h, "status": status, "upspeed": item.get("upspeed")})
        return normalized

    @staticmethod
    def __active_hashes(torrents: List[Dict[str, Any]]) -> List[str]:
        """
        收集需要暂停的种子hash：处于活动状态 且 当前有上传流量（upspeed > 0）。
        只暂停正在上传的任务，空闲做种（上传速度为0）的任务不动，
        待其真正产生上传流量后会在后续检测中被补暂停。
        upspeed 严格校验：仅接受有限的正数；缺失/非数字/布尔/NaN/无穷一律视为
        无法确认有上传流量，跳过不暂停。
        """
        hashes = []
        for torrent in torrents:
            if torrent["status"] != "active":
                continue
            upspeed = torrent.get("upspeed")
            if isinstance(upspeed, bool) or not isinstance(upspeed, (int, float)):
                continue
            if not math.isfinite(upspeed) or upspeed <= 0:
                continue
            hashes.append(torrent["hash"])
        return hashes

    @staticmethod
    def __index_torrents(torrents: List[Dict[str, Any]]) -> Tuple[set, set]:
        """返回 (全部种子hash集合, 当前暂停种子hash集合)"""
        existing = {t["hash"] for t in torrents}
        paused_now = {t["hash"] for t in torrents if t["status"] == "paused"}
        return existing, paused_now

    @staticmethod
    def __now_str() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def __downloader_items(self):
        """获取受支持的下载器选项，失败时仍保持多选列表类型。"""
        try:
            services = list_downloader_services()
            return [
                {"title": name, "value": name}
                for name in services or {}
            ]
        except Exception:
            return []

    @staticmethod
    def __media_server_desc() -> str:
        """表单展示用：MoviePilot 中已登记的 Jellyfin/Emby 名称（获取失败不影响表单）。"""
        try:
            names = [f"{name}（{t}）" for name, (t, _) in list_media_services().items()]
        except Exception:
            return "获取媒体服务器列表失败"
        return "当前已登记：" + "、".join(names) if names else "当前未登记 Jellyfin/Emby 媒体服务器"

    def get_form(self):
        def field(component, model, label, **props):
            base = {
                "model": model,
                "label": label,
                "density": "compact",
            }
            if component != "VSwitch":
                base.update({
                    "variant": "outlined",
                    "hide-details": "auto",
                })
            base.update(props)
            return {"component": component, "props": base}

        def col(item, md=6):
            return {
                "component": "VCol",
                "props": {"cols": 12, "md": md},
                "content": [item],
            }

        def row(*items):
            return {
                "component": "VRow",
                "props": {"class": "mt-0"},
                "content": list(items),
            }

        def section(title, subtitle, rows):
            return {
                "component": "VCard",
                "props": {
                    "variant": "outlined",
                    "class": "mb-4",
                },
                "content": [
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "div",
                                "props": {
                                    "class": (
                                        "text-subtitle-1 "
                                        "font-weight-medium mb-1"
                                    )
                                },
                                "text": title,
                            },
                            {
                                "component": "div",
                                "props": {
                                    "class": (
                                        "text-caption "
                                        "text-medium-emphasis mb-3"
                                    )
                                },
                                "text": subtitle,
                            },
                            *rows,
                        ],
                    }
                ],
            }

        sections = [
            section(
                "基本设置",
                "启用插件、上线通知与临时检测",
                [
                    row(
                        col(
                            field(
                                "VSwitch",
                                "enabled",
                                "启用插件",
                                color="primary",
                                **{"hide-details": True},
                            ),
                            4,
                        ),
                        col(
                            field(
                                "VSwitch",
                                "notify",
                                "上线通知",
                                color="primary",
                                **{"hide-details": True},
                            ),
                            4,
                        ),
                        col(
                            field(
                                "VSwitch",
                                "onlyonce",
                                "立即检测一次",
                                color="primary",
                                **{"hide-details": True},
                            ),
                            4,
                        ),
                    )
                ],
            ),
            section(
                "连接与认证",
                "推送与查询使用相同通信密钥；采集端地址用于轮询、心跳及初始查询",
                [
                    row(
                        col(
                            field(
                                "VSelect",
                                "detect_mode",
                                "检测方式",
                                items=[
                                    {
                                        "title": "Webhook 推送",
                                        "value": "webhook",
                                    },
                                    {
                                        "title": "轮询查询",
                                        "value": "poll",
                                    },
                                ],
                            )
                        ),
                        col(
                            field(
                                "VTextField",
                                "secret",
                                "通信密钥",
                                type="password",
                                autocomplete="new-password",
                                placeholder="与采集端 SECRET 一致",
                            )
                        ),
                    ),
                    row(
                        col(
                            field(
                                "VTextField",
                                "api_url",
                                "采集端 API 地址",
                                placeholder="http://192.168.1.10:8080/",
                            ),
                            8,
                        ),
                        col(
                            field(
                                "VTextField",
                                "timeout",
                                "API 超时",
                                suffix="秒",
                                placeholder="10",
                            ),
                            4,
                        ),
                    ),
                ],
            ),
            section(
                "调度与失联保护",
                "轮询按 Cron 查询；推送按 Cron 补偿。主动心跳仅用于推送模式",
                [
                    row(
                        col(
                            field(
                                "VTextField",
                                "cron",
                                "检测 / 补偿周期",
                                placeholder="*/1 * * * *",
                            ),
                            4,
                        ),
                        col(
                            field(
                                "VTextField",
                                "heartbeat",
                                "主动心跳间隔",
                                suffix="秒",
                                placeholder="300",
                                hint="0 关闭；需填写采集端 API 地址",
                                **{"persistent-hint": True},
                            ),
                            4,
                        ),
                        col(
                            field(
                                "VTextField",
                                "lost_release",
                                "采集端失联释放",
                                suffix="分钟",
                                placeholder="60",
                                hint="0 关闭；启用时最小 30 分钟",
                                **{"persistent-hint": True},
                            ),
                            4,
                        ),
                    )
                ],
            ),
            section(
                "监控与下载器",
                "按隧道虚拟 IP 或主机名精确匹配；不要填写采集端本机节点",
                [
                    row(
                        col(
                            field(
                                "VSelect",
                                "downloader",
                                "下载器（qBittorrent，可多选）",
                                items=self.__downloader_items(),
                                multiple=True,
                                chips=True,
                                clearable=True,
                                placeholder="选择下载器；清空后不新增管理",
                            ),
                            12,
                        )
                    ),
                    row(
                        col(
                            field(
                                "VTextarea",
                                "hosts",
                                "监控主机列表",
                                rows=3,
                                placeholder=(
                                    "10.100.0.3\n"
                                    "MatePad Pro\n"
                                    "# 每行一个，也可填写 IP,主机名"
                                ),
                                **{"auto-grow": True},
                            ),
                            12,
                        )
                    ),
                ],
            ),
            section(
                "Jellyfin/Emby 播放监测",
                (
                    "自动使用 MoviePilot 中已登记的 Jellyfin/Emby，无需另填地址与密钥；"
                    + self.__media_server_desc()
                ),
                [
                    row(
                        col(
                            field(
                                "VSwitch",
                                "media_monitor",
                                "监测Jellyfin/Emby",
                                color="primary",
                                hint=(
                                    "不受监控主机列表影响：排除不限速地址和不限速路径后，"
                                    "只要有播放就限速/停止任务"
                                ),
                                **{"persistent-hint": True},
                            ),
                            12,
                        )
                    ),
                    row(
                        col(
                            field(
                                "VTextField",
                                "unlimited_ips",
                                "不限速地址范围",
                                placeholder="192.168.1.0/24,10.0.0.8,fd00::/8,2408:8000::1",
                                hint=(
                                    "单个 IPv4/IPv6 或网段，多个用逗号分隔；"
                                    "留空默认排除常见内网/本机地址，填写后仅排除所填地址"
                                ),
                                **{"persistent-hint": True},
                            ),
                            12,
                        )
                    ),
                    row(
                        col(
                            field(
                                "VTextarea",
                                "exclude_path",
                                "不限速路径",
                                rows=2,
                                placeholder="/media/音乐\n/media/儿童",
                                hint="播放文件路径包含任一行即不让位，每行一个",
                                **{"auto-grow": True, "persistent-hint": True},
                            ),
                            12,
                        )
                    ),
                ],
            ),
            section(
                "带宽让位策略",
                "暂停模式仅处理正在上传的任务；限速模式在恢复时还原原值",
                [
                    row(
                        col(
                            field(
                                "VSelect",
                                "action",
                                "让位方式",
                                items=[
                                    {
                                        "title": "暂停上传任务",
                                        "value": "pause",
                                    },
                                    {
                                        "title": "全局限速",
                                        "value": "limit",
                                    },
                                ],
                            ),
                            4,
                        ),
                        col(
                            field(
                                "VTextField",
                                "upload_limit",
                                "上传限速",
                                suffix="KB/s",
                                placeholder="512",
                                hint="仅全局限速使用；0 为不限速",
                                **{"persistent-hint": True},
                            ),
                            4,
                        ),
                        col(
                            field(
                                "VTextField",
                                "download_limit",
                                "下载限速",
                                suffix="KB/s",
                                placeholder="0",
                                hint="仅全局限速使用；0 为不限速",
                                **{"persistent-hint": True},
                            ),
                            4,
                        ),
                    )
                ],
            ),
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-3",
                },
                "text": (
                    "任一监控主机在线、或（开启播放监测时）Jellyfin/Emby 有播放即让位；"
                    "监控主机全部离线且无播放后恢复。"
                    "上线通知同一主机每小时最多一次。"
                    "停用插件时会尝试撤销对下载器的所有操作。"
                ),
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "density": "compact",
                },
                "text": (
                    "失联释放是独立的超时策略，并不代表主机已离线；"
                    "启用后会在长时间无有效快照时会撤销对下载器的所有操作。"
                    "暂停结果待确认的任务仍需手动核对。"
                ),
            },
        ]

        defaults = {
            "enabled": False,
            "notify": True,
            "api_url": "",
            "hosts": "",
            "downloader": [],
            "cron": "*/1 * * * *",
            "action": "pause",
            "upload_limit": 512,
            "download_limit": 0,
            "timeout": 10,
            "lost_release": 60,
            "detect_mode": "webhook",
            "secret": "",
            "heartbeat": 300,
            "media_monitor": False,
            "unlimited_ips": "",
            "exclude_path": "",
            "onlyonce": False,
        }

        return [{"component": "VForm", "content": sections}], defaults

    def get_page(self):
        """仅根据已有状态生成详情页，不查询或操作下载器。"""
        state = self._state or {}
        info = self._last_check_info or {}
        multi = state.get("multi_schema") == 1
        records = (
            list((state.get("downloaders") or {}).items())
            if multi
            else [("默认下载器", state)]
        )
        online = info.get("online") or []
        limit_failed = getattr(self, "_limit_failed", set())
        decision = state.get("decision")
        lost_release = getattr(self, "_lost_release", 0)
        downloaders = self._downloaders or []

        def fmt_limit(value):
            try:
                value = float(value or 0)
                if not math.isfinite(value) or value < 0:
                    return "未知"
                if value == 0:
                    return "不限速"
                number = (
                    str(int(value))
                    if value.is_integer()
                    else f"{value:.1f}"
                )
                return f"{number} KB/s"
            except (TypeError, ValueError, OverflowError):
                return "未知"

        def describe(named_recs):
            paused = sum(
                len(record.get("paused_hashes") or [])
                for _, record in named_recs
            )
            pending = sum(
                len(record.get("pending_hashes") or [])
                for _, record in named_recs
            )
            limited = [
                (name, record)
                for name, record in named_recs
                if record.get("orig_limits") is not None
            ]
            failed = [
                name
                for name, _ in limited
                if (name if multi else "") in limit_failed
            ]

            parts = []

            if paused:
                parts.append(f"已记录暂停 {paused} 个上传任务")

            if len(failed) < len(limited):
                parts.append(
                    "限速让位记录存在"
                    f"（当前配置目标：上传 {fmt_limit(self._upload_limit)} / "
                    f"下载 {fmt_limit(self._download_limit)}）"
                )

            if failed:
                names = "、".join(name for name in failed if name)
                prefix = (
                    f"{names}："
                    if names and len(named_recs) > 1
                    else ""
                )
                parts.append(f"{prefix}限速写入失败，待重试")

            if pending:
                parts.append(
                    f"{pending} 个暂停待确认，不会自动恢复"
                )

            if parts:
                return "；".join(parts), True

            return (
                "无插件暂停记录"
                if self._action == "pause"
                else "无限速恢复记录"
            ), False

        def node(component, text=None, props=None, content=None):
            result = {"component": component}
            if text is not None:
                result["text"] = str(text)
            if props:
                result["props"] = props
            if content is not None:
                result["content"] = content
            return result

        def column(content, md=6, cols=12):
            return node(
                "VCol",
                props={"cols": cols, "md": md},
                content=content,
            )

        def card(title, content):
            return node(
                "VCard",
                props={
                    "variant": "outlined",
                    "class": "mb-4",
                },
                content=[
                    node(
                        "VCardText",
                        content=[
                            node(
                                "div",
                                title,
                                {
                                    "class": (
                                        "text-subtitle-1 "
                                        "font-weight-medium mb-3"
                                    )
                                },
                            ),
                            *content,
                        ],
                    )
                ],
            )

        def metric(label, value, color="primary"):
            return column(
                [
                    node(
                        "VCard",
                        props={
                            "variant": "tonal",
                            "color": color,
                            "class": "h-100",
                        },
                        content=[
                            node(
                                "VCardText",
                                content=[
                                    node(
                                        "div",
                                        label,
                                        {"class": "text-caption mb-1"},
                                    ),
                                    node(
                                        "div",
                                        value,
                                        {
                                            "class": (
                                                "text-h6 "
                                                "font-weight-medium"
                                            ),
                                            "style": {
                                                "overflowWrap": "anywhere",
                                            },
                                        },
                                    ),
                                ],
                            )
                        ],
                    )
                ],
                md=3,
                cols=6,
            )

        def detail(label, value):
            return node(
                "div",
                props={"class": "mb-3"},
                content=[
                    node(
                        "div",
                        label,
                        {
                            "class": (
                                "text-caption "
                                "text-medium-emphasis mb-1"
                            )
                        },
                    ),
                    node(
                        "div",
                        value,
                        {
                            "class": "text-body-2",
                            "style": {
                                "overflowWrap": "anywhere",
                            },
                        },
                    ),
                ],
            )

        status_text, yielding = describe(records)
        recoverable = any(
            self.__recoverable(record)
            for _, record in records
        )

        current_hosts = self.__parse_hosts()
        hosts_match = (
            state.get("decision_hosts") == current_hosts
        )
        decision_fresh = self.__decision_fresh(
            state.get("decision_ts")
        )
        snapshot_known = (
            self._enabled
            and self._synced
            and not info.get("error")
            and decision in ("online", "offline")
            and hosts_match
            and decision_fresh
        )

        media_on = self._enabled and self._media_enabled
        media_playing = media_on and self._media_state == "playing"
        if not self._enabled:
            phase = "已停用：保留历史检测与控制记录"
        elif media_playing:
            phase = "Jellyfin/Emby 播放中：让位维护中"
        elif not current_hosts:
            phase = (
                "仅播放监测：无播放时空闲"
                if media_on
                else "未配置监控主机，也未开启播放监测"
            )
        elif decision == "lost":
            phase = (
                "采集端失联，释放重试中"
                if recoverable
                else "采集端失联，已完成可自动恢复记录的释放"
            )
        elif not self._synced:
            phase = "等待首次有效同步"
        elif decision in ("online", "offline") and not hosts_match:
            phase = "监控配置已变更，等待重新判定"
        elif info.get("error"):
            phase = "上次同步失败，保持现状并等待有效快照"
        elif (
            decision in ("online", "offline")
            and not decision_fresh
        ):
            phase = "判定已过期，等待有效快照重新同步"
        elif self._detect_mode != "webhook":
            phase = "按周期查询并协调下载器"
        elif not self._comp_scheduled:
            phase = "补偿未启用：检测周期无效"
        elif decision == "online":
            phase = "让位维护中：按补偿周期检查下载器"
        elif decision == "offline" and recoverable:
            phase = "恢复重试中：完成后进入空闲"
        elif decision == "offline":
            phase = "空闲：不访问下载器"
        else:
            phase = "状态未知：保持现状"

        mode = (
            "Webhook 推送"
            if self._detect_mode == "webhook"
            else "轮询查询"
        )

        heartbeat = "不适用"
        if self._detect_mode == "webhook":
            if self._heartbeat > 0 and self._api_url:
                heartbeat = f"每 {self._heartbeat} 秒"
            elif self._heartbeat > 0:
                heartbeat = (
                    f"未生效（已设 {self._heartbeat} 秒，"
                    "缺少 API 地址）"
                )
            else:
                heartbeat = "已关闭"

        online_value = (
            f"{len(online)} 台"
            if snapshot_known
            else ("未配置" if not current_hosts else "待确认")
        )
        online_color = (
            "primary"
            if snapshot_known
            else "secondary"
        )
        online_hosts = (
            ("、".join(str(item) for item in online) or "无")
            if snapshot_known
            else "暂无可信判定"
        )

        if info.get("error") and current_hosts:
            alert_type = "error"
        elif media_playing:
            alert_type = "warning"
        elif decision == "lost":
            alert_type = "warning"
        elif not snapshot_known:
            alert_type = "info"
        elif yielding:
            alert_type = "warning"
        else:
            alert_type = "success"

        children = [
            node(
                "VRow",
                content=[
                    metric(
                        "插件状态",
                        "运行中" if self._enabled else "已停用",
                        "success" if self._enabled else "secondary",
                    ),
                    metric(
                        "最近判定在线",
                        online_value,
                        online_color,
                    ),
                    metric("检测方式", mode, "info"),
                    metric(
                        "让位策略",
                        (
                            "全局限速"
                            if self._action == "limit"
                            else "暂停上传"
                        ),
                        "warning",
                    ),
                ],
            )
        ]

        if not self._enabled:
            children.append(
                node(
                    "VAlert",
                    "插件已停用；以下为保留的检测与控制记录。",
                    {
                        "type": "info",
                        "variant": "tonal",
                        "class": "mt-4",
                    },
                )
            )

        children.append(
            node(
                "VAlert",
                status_text,
                {
                    "type": alert_type,
                    "variant": "tonal",
                    "class": "my-4",
                },
            )
        )

        if info.get("error") and current_hosts:
            children.append(
                node(
                    "VAlert",
                    (
                        "上次检测失败："
                        f"{info.get('result') or '请查看日志'}。"
                        "本页显示保留记录，不代表下载器实时读回状态。"
                    ),
                    {
                        "type": "error",
                        "variant": "tonal",
                        "class": "mb-4",
                    },
                )
            )
        elif decision == "lost":
            children.append(
                node(
                    "VAlert",
                    (
                        "采集端长时间未提供有效快照。"
                        "失联释放不代表监控主机已离线；"
                        "恢复有效同步后，将按新的节点状态重新判定。"
                    ),
                    {
                        "type": "warning",
                        "variant": "tonal",
                        "class": "mb-4",
                    },
                )
            )

        children.append(
            node(
                "VRow",
                content=[
                    column(
                        [
                            card(
                                "监控与同步",
                                [
                                    detail(
                                        "上次检测",
                                        info.get("time") or "尚未检测",
                                    ),
                                    detail(
                                        "检测结果",
                                        info.get("result") or "暂无结果",
                                    ),
                                    detail("在线主机", online_hosts),
                                    detail(
                                        "数据来源",
                                        info.get("source") or "未知",
                                    ),
                                ],
                            )
                        ]
                    ),
                    column(
                        [
                            card(
                                "调度与保护",
                                [
                                    detail("运行阶段", phase),
                                    detail(
                                        "检测 / 补偿周期",
                                        self._cron or "未配置",
                                    ),
                                    detail("主动心跳", heartbeat),
                                    detail(
                                        "失联释放",
                                        (
                                            f"{lost_release} 分钟"
                                            "无有效快照后尝试解除插件让位"
                                            if lost_release > 0
                                            else "已关闭"
                                        ),
                                    ),
                                ],
                            )
                        ]
                    ),
                ],
            )
        )

        media_info = self._media_info or {}
        if not self._media_enabled:
            media_status = "已关闭"
        elif not media_info:
            media_status = "等待首次检测"
        else:
            media_status = media_info.get("result") or "暂无结果"
        if media_on and self._media_state == "unknown" and self.__media_holds():
            media_status += "（保持让位中）"
        media_sessions = (
            "；".join(
                f"{s.get('user')} @ {s.get('device')}（{s.get('ip')}）"
                f"{s.get('item')} [{s.get('server')}]"
                for s in (self._media_sessions or [])[:10]
            )
            if media_playing
            else "无"
        )
        media_servers = media_info.get("servers") or []
        if self._media_enabled:
            children.append(card(
                "Jellyfin/Emby 播放监测",
                [
                    node(
                        "VRow",
                        content=[
                            column([
                                detail("监测状态", media_status),
                                detail("上次检测", media_info.get("time") or "尚未检测"),
                                detail(
                                    "媒体服务器",
                                    "、".join(str(n) for n in media_servers) or "—",
                                ),
                            ]),
                            column([
                                detail("需要让位的播放", media_sessions),
                                detail(
                                    "不限速地址",
                                    self._unlimited_ips or "留空：默认排除内网/本机地址",
                                ),
                                detail(
                                    "不限速路径",
                                    "、".join(self._exclude_paths) or "无",
                                ),
                            ]),
                        ],
                    ),
                    node(
                        "div",
                        (
                            "不受监控主机列表影响；与隧道判定任一需要让位即保持让位。"
                            "查询失败不等于无播放：此前在播放时最多保持 "
                            f"{self.MEDIA_UNKNOWN_HOLD // 60} 分钟。"
                        ),
                        {
                            "class": (
                                "text-caption "
                                "text-medium-emphasis"
                            )
                        },
                    ),
                ],
            ))

        headers = [
            "下载器",
            "管理范围",
            "让位记录",
            "恢复目标（原限速）",
        ]
        rows = []

        for name, record in records:
            selected = (
                name in downloaders
                if multi
                else True
            )
            original = record.get("orig_limits")
            original_text = (
                f"上传 {fmt_limit(original.get('upload'))} / "
                f"下载 {fmt_limit(original.get('download'))}"
                if isinstance(original, dict)
                else "—"
            )
            cells = [
                name or "默认下载器",
                "已勾选" if selected else "历史记录",
                describe([(name, record)])[0],
                original_text,
            ]

            rows.append(
                node(
                    "tr",
                    content=[
                        node(
                            "td",
                            value,
                            {
                                "class": "text-body-2",
                                "style": {
                                    "overflowWrap": "anywhere",
                                    "minWidth": "120px",
                                },
                            },
                        )
                        for value in cells
                    ],
                )
            )

        if not rows:
            rows.append(
                node(
                    "tr",
                    content=[
                        node(
                            "td",
                            "暂无下载器记录",
                            {
                                "colspan": 4,
                                "class": (
                                    "text-center "
                                    "text-medium-emphasis"
                                ),
                            },
                        )
                    ],
                )
            )

        table = node(
            "VTable",
            props={
                "hover": True,
                "density": "compact",
            },
            content=[
                node(
                    "thead",
                    content=[
                        node(
                            "tr",
                            content=[
                                node(
                                    "th",
                                    name,
                                    {
                                        "class": (
                                            "text-start text-no-wrap"
                                        )
                                    },
                                )
                                for name in headers
                            ],
                        )
                    ],
                ),
                node("tbody", content=rows),
            ],
        )

        selected_text = (
            "、".join(downloaders)
            if multi
            else (self._downloader or "默认下载器")
        )

        children.append(
            card(
                "下载器状态",
                [
                    node(
                        "div",
                        "已勾选：" + (selected_text or "无"),
                        {
                            "class": (
                                "text-caption "
                                "text-medium-emphasis mb-3"
                            )
                        },
                    ),
                    node(
                        "div",
                        props={
                            "style": {
                                "overflowX": "auto",
                            }
                        },
                        content=[table],
                    ),
                    node(
                        "div",
                        (
                            "本表依据插件保存的控制记录展示，"
                            "打开页面不会查询下载器。"
                            "限速目标为当前配置值，不代表实时读回值；"
                            "待确认暂停不会自动恢复。"
                        ),
                        {
                            "class": (
                                "text-caption "
                                "text-medium-emphasis mt-3"
                            )
                        },
                    ),
                ],
            )
        )

        if self._detect_mode == "webhook":
            children.append(
                card(
                    "Webhook 接入",
                    [
                        detail(
                            "推送路径",
                            "/api/v1/plugin/TunnelYield/webhook",
                        ),
                        node(
                            "div",
                            (
                                "宿主认证使用 "
                                "X-API-KEY=MoviePilot API_TOKEN；"
                                "通信密钥请与采集端保持一致。"
                                "此处不展示密钥。"
                            ),
                            {
                                "class": (
                                    "text-caption "
                                    "text-medium-emphasis"
                                )
                            },
                        ),
                    ],
                )
            )

        legacy = getattr(self, "_legacy_warning", None)
        if legacy:
            children.append(
                node(
                    "VAlert",
                    legacy,
                    {
                        "type": "warning",
                        "variant": "tonal",
                        "class": "mt-3",
                    },
                )
            )

        return [
            node(
                "div",
                props={"class": "pa-2"},
                content=children,
            )
        ]

    def __stop_onlyonce_scheduler(self):
        """停止一次性检测调度器（回退方案遗留）。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
        except Exception as e:
            logger.error(
                f"停止一次性检测任务失败: {type(e).__name__}"
            )
        finally:
            self._scheduler = None

        # 取消宿主调度器上的一次性任务（若已登记）。
        try:
            from app.sdk import scheduler as scheduler_sdk

            remove_once = getattr(
                scheduler_sdk,
                "remove_plugin_once_job",
                None,
            )
            if callable(remove_once):
                remove_once(
                    self.__class__.__name__,
                    "TunnelYieldOnce",
                )
        except ImportError:
            pass
        except Exception as e:
            logger.error(
                f"取消一次性检测任务失败: {type(e).__name__}"
            )

    def __schedule_once(self, func, desc: str, delay: int = 3):
        """
        注册一次性延迟任务（立即检测 / 初始同步）。

        优先使用宿主调度器；宿主未提供接口或登记失败时，
        回退为自建一次性 BackgroundScheduler。
        """
        try:
            from app.sdk import scheduler as scheduler_sdk

            add_once = getattr(
                scheduler_sdk,
                "add_plugin_once_job",
                None,
            )
            if callable(add_once):
                ret = add_once(
                    self.__class__.__name__,
                    "TunnelYieldOnce",
                    func,
                    f"隧道在线带宽让位：{desc}",
                    delay_seconds=delay,
                )
                if ret is not False:
                    logger.info(
                        f"隧道在线带宽让位：{delay}秒后{desc}"
                    )
                    return

                logger.warning(
                    "隧道在线带宽让位：宿主一次性任务登记失败"
                    "（add_plugin_once_job返回False），"
                    f"回退自建调度器：{desc}"
                )
        except ImportError:
            pass
        except Exception as e:
            logger.error(
                f"注册一次性任务失败: {type(e).__name__}"
            )

        # 回退：自建一次性调度器（旧主程序兼容）。
        try:
            self._scheduler = BackgroundScheduler(
                timezone=settings.TZ
            )
            self._scheduler.add_job(
                func,
                "date",
                run_date=(
                    datetime.now(
                        tz=pytz.timezone(settings.TZ)
                    )
                    + timedelta(seconds=delay)
                ),
            )
            self._scheduler.start()
        except Exception as e:
            logger.error(
                f"启动一次性任务失败: {type(e).__name__}"
            )
            self._scheduler = None

    def stop_service(self):
        """
        退出插件：仅停止一次性任务调度器。

        常规配置重载也会经过这里，因此不做恢复动作；
        恢复动作在 init_plugin 检测到 enabled=False 时执行。
        """
        self.__stop_onlyonce_scheduler()





