"""MoviePilot V3 plugin for MoonTV/LunaTV Apple CMS sources.

The first implementation deliberately keeps the source adapter independent from
MoviePilot internals.  The host integration is optional at import time so the
pure search, naming and queue code can be tested outside a running MoviePilot.
"""

from __future__ import annotations

import json
import base64
import hashlib
import logging
import asyncio
import threading
import time
import urllib.parse
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:  # MoviePilot V3 runtime imports
    from app.plugins import _PluginBase
    from app.sdk.events import Event, eventmanager
    from app.schemas.types import ChainEventType, EventType
except Exception:  # pragma: no cover - standalone tests
    Event = Any  # type: ignore[misc,assignment]

    class _PluginBase:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._data: Dict[str, Any] = {}
            self._config: Dict[str, Any] = {}

        def get_data(self, key: str, default: Any = None) -> Any:
            return self._data.get(key, default)

        def save_data(self, key: str, value: Any) -> None:
            self._data[key] = value

        def update_config(self, config: Dict[str, Any]) -> None:
            self._config.update(config)

    class _EventManager:
        @staticmethod
        def register(*_: Any, **__: Any):
            def decorator(fn):
                return fn

            return decorator

    eventmanager = _EventManager()  # type: ignore[assignment]

    class EventType:  # type: ignore[no-redef]
        SubscribeAdded = "subscribe.added"
        SubscribeModified = "subscribe.modified"

    class ChainEventType:  # type: ignore[no-redef]
        ResourceDownload = "resource.download"

try:  # Optional V3 native schemas used by download-task projection.
    from app import schemas as _schemas
except Exception:  # pragma: no cover - standalone tests
    _schemas = None

try:  # Stable V3 SDK export for plugin resource results.
    from app.sdk.media import TorrentInfo as _HostTorrentInfo
except Exception:  # pragma: no cover - standalone tests
    _HostTorrentInfo = None

try:  # Optional V3 media identity enums.
    from app.schemas.types import MediaSource as _HostMediaSource
    from app.schemas.types import MediaType as _HostMediaType
except Exception:  # pragma: no cover - standalone tests
    _HostMediaSource = None
    _HostMediaType = None

# Keep optional host chains isolated: one unavailable compatibility import must
# not disable native search result schemas or the remaining host bridges.
try:  # pragma: no cover - exercised in a MoviePilot runtime
    from app.chain.mediaserver import MediaServerChain as _HostMediaServerChain
except Exception:
    _HostMediaServerChain = None

try:  # pragma: no cover - exercised in a MoviePilot runtime
    from app.chain.storage import StorageChain as _HostStorageChain
except Exception:
    _HostStorageChain = None

try:  # pragma: no cover - exercised in a MoviePilot runtime
    from app.chain.transfer import TransferChain as _HostTransferChain
except Exception:
    _HostTransferChain = None

try:
    from apscheduler.triggers.cron import CronTrigger
except Exception:  # pragma: no cover - standalone tests
    CronTrigger = None  # type: ignore[assignment,misc]

from .ai import AiTitleNormalizer
from .cms import (
    AppleCmsClient,
    CmsEpisode,
    CmsResult,
    CmsSource,
    apply_season_counts,
    load_sources_from_url,
)
from .downloader import DownloadQueue, DownloadTask
from .naming import media_path, normalize_media_title, normalize_search_title

try:  # Optional host services used for directory and TMDB association hints.
    from app.application.directory import DirectoryHelper as _HostDirectoryHelper
    from app.chain.media import MediaChain as _HostMediaChain
    from app.sdk.media import MetaInfo as _HostMetaInfo
except Exception:  # pragma: no cover - standalone tests
    _HostDirectoryHelper = None
    _HostMediaChain = None
    _HostMetaInfo = None


LOGGER = logging.getLogger("LunaTVSource")


DEFAULT_CONFIG_URL = (
    "https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json"
)
FALLBACK_CONFIG_PATH = Path(__file__).with_name("fallback_sources.json")
SOURCE_CACHE_KEY = "luna_source_config_v1"
DEFAULT_SOURCE_ALLOWLIST = (
    "suonizy.net,suoniapi.com,kuaichezy.com,caiji.kuaichezy.org,"
    "www.hongniuzy.com,www.hongniuzy2.com,wujinzy.net,wujinzy.me,"
    "api.wujinapi.me,wujinapi.me,guangsuzy.com,api.guangsuapi.com,"
    "ukuzy0.com,api.ukuapi88.com,www.xinlangzy.com,xinlangapi.com,okzyw.cc"
)
PLUGIN_MEDIA_SOURCE = "lunatv"


# MoviePilot 3.0.0 returns before module resource providers are called when no
# PT/indexer site is enabled. Keep this compatibility bridge inside the plugin.
# Existing MoviePilot plugins use the same reversible runtime-wrapper pattern.
_SEARCH_BRIDGE: Dict[str, Any] = {"owner": None, "chain": None, "originals": {}}


class _CompatDownloaderTorrent:
    """在独立测试环境中保持下载任务投影的最小对象接口。"""

    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)

    def model_dump(self, **_: Any) -> Dict[str, Any]:
        return dict(self.__dict__)

    def dict(self, **_: Any) -> Dict[str, Any]:
        return self.model_dump()


def _bridge_owner() -> Optional["LunaTVSource"]:
    owner = _SEARCH_BRIDGE.get("owner")
    return owner if owner and getattr(owner, "_enabled", False) else None


def _bridge_search_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    mediainfo = kwargs.get("mediainfo")
    return {
        "site": {},
        "keyword": str(kwargs.get("keyword") or ""),
        "mtype": getattr(mediainfo, "type", None) or kwargs.get("mtype"),
        "page": kwargs.get("page") or 0,
    }


def _install_search_bridge(owner: "LunaTVSource") -> None:
    _SEARCH_BRIDGE["owner"] = owner
    try:
        from app.chain.search import SearchChain
    except Exception as exc:  # pragma: no cover - MoviePilot runtime only
        owner._logger.warning("LunaTV 原生资源搜索桥接不可用：%s", exc)
        return
    # Newer MoviePilot V3 releases dispatch plugin resource providers once via
    # SearchChain.search_plugin_torrents/async_search_plugin_torrents. Wrapping
    # the private fan-out methods there would query this plugin twice. Keep the
    # reversible wrapper only for early V3 releases that lacked that native
    # dispatch path.
    if (
        callable(getattr(SearchChain, "search_plugin_torrents", None))
        and callable(getattr(SearchChain, "async_search_plugin_torrents", None))
    ):
        _restore_search_bridge(owner, force=True)
        owner._logger.info("MoviePilot 已原生支持插件资源搜索，无需启用兼容桥")
        return
    if _SEARCH_BRIDGE.get("chain") is SearchChain and _SEARCH_BRIDGE.get("originals"):
        return

    originals: Dict[str, Callable[..., Any]] = {}
    sync_name = "_SearchChain__search_all_sites"
    async_name = "_SearchChain__async_search_all_sites"
    stream_name = "_SearchChain__async_search_all_sites_stream"

    sync_original = getattr(SearchChain, sync_name, None)
    if callable(sync_original):
        originals[sync_name] = sync_original

        @wraps(sync_original)
        def sync_wrapper(chain, *args, **kwargs):
            native = list(sync_original(chain, *args, **kwargs) or [])
            plugin = _bridge_owner()
            if plugin:
                try:
                    native.extend(plugin.search_torrents(**_bridge_search_kwargs(kwargs)))
                except Exception as exc:
                    plugin._logger.warning("LunaTV 原生资源搜索追加失败：%s", exc)
            return native

        setattr(SearchChain, sync_name, sync_wrapper)

    async_original = getattr(SearchChain, async_name, None)
    if callable(async_original):
        originals[async_name] = async_original

        @wraps(async_original)
        async def async_wrapper(chain, *args, **kwargs):
            native = list(await async_original(chain, *args, **kwargs) or [])
            plugin = _bridge_owner()
            if plugin:
                try:
                    native.extend(await plugin.async_search_torrents(**_bridge_search_kwargs(kwargs)))
                except Exception as exc:
                    plugin._logger.warning("LunaTV 原生异步资源搜索追加失败：%s", exc)
            return native

        setattr(SearchChain, async_name, async_wrapper)

    stream_original = getattr(SearchChain, stream_name, None)
    if callable(stream_original):
        originals[stream_name] = stream_original

        @wraps(stream_original)
        async def stream_wrapper(chain, *args, **kwargs):
            done_event = None
            async for event in stream_original(chain, *args, **kwargs):
                if event.get("type") == "done":
                    done_event = event
                    continue
                yield event
            plugin = _bridge_owner()
            plugin_items = []
            if plugin:
                try:
                    plugin_items = await plugin.async_search_torrents(
                        **_bridge_search_kwargs(kwargs)
                    )
                except Exception as exc:
                    plugin._logger.warning("LunaTV 原生流式资源搜索追加失败：%s", exc)
            if plugin_items:
                yield {
                    "type": "append", "stage": "searching", "value": 100,
                    "text": f"LunaTV 返回 {len(plugin_items)} 条资源",
                    "items": plugin_items, "site": "LunaTV", "site_id": None,
                    "page": kwargs.get("page") or 0, "finished": 0, "total": 0,
                    "total_items": len(plugin_items),
                }
            final = dict(done_event or {})
            final.update({"type": "done", "stage": final.get("stage", "searching"),
                          "value": 100, "items": []})
            if plugin_items:
                final["text"] = f"资源搜索完成，LunaTV 返回 {len(plugin_items)} 条资源"
            yield final

        setattr(SearchChain, stream_name, stream_wrapper)

    _SEARCH_BRIDGE.update({"chain": SearchChain, "originals": originals})
    if originals:
        owner._logger.info("LunaTV 原生资源搜索桥接已启用（%s）", ", ".join(originals))


def _restore_search_bridge(owner: "LunaTVSource", force: bool = False) -> None:
    if not force and _SEARCH_BRIDGE.get("owner") is not owner:
        return
    chain = _SEARCH_BRIDGE.get("chain")
    for name, original in dict(_SEARCH_BRIDGE.get("originals") or {}).items():
        if chain is not None:
            setattr(chain, name, original)
    _SEARCH_BRIDGE.update({"owner": None, "chain": None, "originals": {}})


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"0", "false", "off", "no", ""}:
            return False
        if lowered in {"1", "true", "on", "yes"}:
            return True
        return default
    return bool(value) if value is not None else default


def _source_keys(value: Any) -> Tuple[str, ...]:
    if isinstance(value, str):
        values = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return tuple(dict.fromkeys(str(item).strip().lower() for item in values if str(item).strip()))


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _media_type_value(value: Any) -> str:
    text = _enum_value(value)
    if text in {"电视剧", "tv", "series", "show", "tvshow"}:
        return "tv"
    return "movie"


def _coerce_media_identity_source(media_source: Any) -> str:
    return _enum_value(media_source) or PLUGIN_MEDIA_SOURCE


class LunaTVSource(_PluginBase):
    """第三方苹果 CMS/m3u8 订阅下载插件。"""

    plugin_name = "LunaTV 资源订阅"
    plugin_desc = "接入 LunaTV/MoonTV 苹果 CMS 资源，复用 MoviePilot 原生搜索、订阅、目录、整理与媒体库链路。"
    plugin_icon = "lunatvsource.png"
    plugin_version = "0.4.27"
    plugin_author = "OneBigMoon"
    author_url = "https://github.com/OneBigMoon"
    plugin_config_prefix = "lunatvsource_"
    plugin_order = 55
    auth_level = 1

    _enabled = False
    _config: Dict[str, Any] = {}
    _queue: Optional[DownloadQueue] = None
    _ai: Optional[AiTitleNormalizer] = None
    _refresh_lock = threading.Lock()
    _refresh_running = False
    _media_sync_lock = threading.Lock()
    _media_sync_running = False
    _tmdb_cache_lock = threading.RLock()
    _tmdb_cache: Dict[str, Dict[str, Any]] = {}
    _resource_search_lock = threading.RLock()
    _resource_search_cache: Dict[str, Tuple[float, List[Any]]] = {}
    _source_config_origin = "未加载"
    _source_config_error = ""

    def __init__(self) -> None:
        super().__init__()
        self._logger = LOGGER

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = dict(config or {})
        self._enabled = _bool(self._config.get("enabled"), False)
        self._source_config_origin = "未加载"
        self._source_config_error = ""
        # 智能助手始终读取 MoviePilot 全局配置；没有配置时由 AiTitleNormalizer 自动回退。
        # 保留旧版 ai_enabled 仅为兼容历史配置，不再让插件设置覆盖宿主设置。
        self._ai = AiTitleNormalizer(True, LOGGER)
        self._queue = DownloadQueue(
            load=lambda key, default=None: self.get_data(key) or default,
            save=lambda key, value: self.save_data(key, value),
            notify=self._notify,
            on_complete=self._record_completion,
        )
        with self._tmdb_cache_lock:
            self._tmdb_cache = dict(self.get_data("tmdb_match_cache_v1") or {})
        with self._resource_search_lock:
            self._resource_search_cache = {}
        if self._enabled:
            _install_search_bridge(self)
        else:
            # A disabled replacement instance must also remove a bridge owned
            # by the previously loaded instance.
            _restore_search_bridge(self, force=True)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """Do not add a parallel subscription page; use MoviePilot's native one."""
        return []

    def get_page(self) -> List[Dict[str, Any]]:
        """Keep the standard plugin detail page useful when the Vue workbench is unavailable."""

        root = str(self._config.get("download_root") or "").strip()
        if not root:
            root = self._effective_root(media_type="tv")
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info" if root else "warning",
                    "variant": "tonal",
                    "text": (
                        f"已启用，下载目录：{root}。任务按队列串行执行，完成后可刷新 Emby。"
                        if root
                        else "未找到下载目录。可在插件设置填写目录，或在 MoviePilot 目录设置中配置本地下载目录。"
                    ),
                },
            }
        ]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/lunatv_sync",
                "event": getattr(EventType, "PluginAction", "plugin.action"),
                "desc": "刷新 LunaTV 订阅并排队下载",
                "category": "LunaTV 资源订阅",
                "data": {"action": "sync"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/status", "endpoint": self.api_status, "methods": ["GET"], "auth": "bear"},
            {"path": "/sources", "endpoint": self.api_sources, "methods": ["GET"], "auth": "bear"},
            {"path": "/search", "endpoint": self.api_search, "methods": ["POST"], "auth": "bear"},
            {"path": "/tmdb/search", "endpoint": self.api_tmdb_search, "methods": ["POST"], "auth": "bear"},
            {
                "path": "/discover",
                "endpoint": self.api_discover,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "LunaTV V3 探索数据源",
                "response_model": (
                    _schemas.Response[List[_schemas.MediaInfo]]
                    if _schemas is not None and hasattr(_schemas, "Response") and hasattr(_schemas, "MediaInfo")
                    else None
                ),
            },
            {"path": "/download", "endpoint": self.api_download, "methods": ["POST"], "auth": "bear"},
            {"path": "/tasks", "endpoint": self.api_tasks, "methods": ["GET"], "auth": "bear"},
            {"path": "/sync", "endpoint": self.api_sync, "methods": ["POST"], "auth": "bear"},
            {"path": "/tasks/{task_id}/retry", "endpoint": self.api_retry, "methods": ["POST"], "auth": "bear"},
        ]

    def get_form_legacy(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VSwitch",
                        "props": {"model": "enabled", "label": "启用插件"},
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "config_url",
                            "label": "LunaTV 配置地址",
                            "placeholder": DEFAULT_CONFIG_URL,
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "source_allowlist",
                            "label": "启用资源站（逗号分隔）",
                            "placeholder": DEFAULT_SOURCE_ALLOWLIST,
                        },
                    },
                    {
                        "component": "VSelect",
                        "props": {
                            "model": "mode",
                            "label": "处理方式",
                            "items": [
                                {"title": "下载到本地并整理", "value": "download"},
                                {"title": "生成 STRM", "value": "strm"},
                            ],
                        },
                    },
                    {
                        "component": "VSelect",
                        "props": {
                            "model": "source_strategy",
                            "label": "订阅资源站策略",
                            "items": [
                                {"title": "按配置顺序选一个（推荐）", "value": "first"},
                                {"title": "所有匹配源都排队", "value": "all"},
                            ],
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "download_root",
                            "label": "下载目录（可留空，自动复用 MoviePilot）",
                            "placeholder": "/media/incoming/lunatv",
                            "hint": "填写后优先使用此目录；留空则按媒体类型读取 MoviePilot 的本地下载目录。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "use_moviepilot_dirs",
                            "label": "自动读取 MoviePilot 目录设置",
                            "hint": "按电影/电视剧匹配已配置的本地下载目录；远程存储不会直接写入。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "ffmpeg_path",
                            "label": "ffmpeg 路径",
                            "placeholder": "ffmpeg",
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "queue_minutes",
                            "label": "队列间隔（分钟）",
                            "placeholder": "1",
                            "type": "number",
                        },
                    },
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "ai_enabled",
                            "label": "启用系统智能助手识别",
                            "hint": "复用 MoviePilot 智能助手配置（DeepSeek 等），自动清理片名后再查 TMDB/CMS；未配置时自动回退原名称。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "tmdb_association",
                            "label": "搜索后自动关联 TMDB",
                            "hint": "使用 MoviePilot 原生识别链给资源预选作品和季数；未匹配时仍可手动处理。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "moviepilot_organize",
                            "label": "下载后调用 MoviePilot 整理链",
                            "hint": "关闭时直接写入上面的下载目录；开启后由 MoviePilot 原生整理规则接管。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "native_recognize",
                            "label": "允许 MoviePilot 识别 LunaTV 媒体",
                            "hint": "让 V3 全局媒体链按 lunatv 媒体身份读取详情；只处理本插件来源，不影响 TMDB 等其它来源。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "mediaserver_name",
                            "label": "完成后刷新媒体服务器（可选）",
                            "placeholder": "Emby",
                            "hint": "留空则刷新所有已启用媒体服务器；播放仍在 Emby/Jellyfin 页面完成。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                        "text": "订阅任务串行执行；目录、智能助手、TMDB、整理链和媒体库均复用 MoviePilot 设置。目录内没有正在下载的缓存文件后，媒体库才会显示完整文件夹。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "config_url": DEFAULT_CONFIG_URL,
            "source_allowlist": "",
            "mode": "download",
            "source_strategy": "first",
            "download_root": "",
            "use_moviepilot_dirs": True,
            "ffmpeg_path": "ffmpeg",
            "request_timeout": 15,
            "poll_minutes": 30,
            "queue_minutes": 1,
            "ai_enabled": True,
            "tmdb_association": True,
            "moviepilot_organize": True,
            "native_recognize": True,
            "mediaserver_name": "",
        }

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """Expose only source-specific options; host services stay authoritative."""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "enabled",
                            "label": "启用原生桥接",
                            "hint": "启用后，LunaTV 将以 MoviePilot 原生搜索、订阅与下载入口出现。",
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "config_url",
                            "label": "LunaTV 配置地址",
                            "placeholder": DEFAULT_CONFIG_URL,
                        },
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "无需重复配置 DeepSeek、TMDB、下载目录、整理规则、Emby 或链接权限；订阅地址内的资源站全部读取。任务串行执行，目录内没有正在下载的缓存文件后才显示完整文件夹。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "config_url": DEFAULT_CONFIG_URL,
            "source_allowlist": "",
            "source_strategy": "first",
            "download_root": "",
            "use_moviepilot_dirs": True,
            "mode": "download",
            "ffmpeg_path": "ffmpeg",
            "request_timeout": 15,
            "poll_minutes": 30,
            "queue_minutes": 1,
            "ai_enabled": True,
            "tmdb_association": True,
            "moviepilot_organize": True,
            "native_recognize": True,
            "mediaserver_name": "",
        }

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        refresh_minutes = max(5, int(self._config.get("poll_minutes") or 30))
        queue_minutes = max(1, int(self._config.get("queue_minutes") or 1))
        refresh_trigger: Any
        queue_trigger: Any
        if CronTrigger is not None:
            refresh_trigger = CronTrigger(minute=f"*/{refresh_minutes}")
            queue_trigger = CronTrigger(minute=f"*/{queue_minutes}")
        else:  # pragma: no cover - fallback for standalone tests
            refresh_trigger = queue_trigger = "interval"
        return [
            {
                "id": "LunaTVSource.Refresh",
                "name": "LunaTV 订阅刷新",
                "trigger": refresh_trigger,
                "func": self.refresh_subscriptions,
                "kwargs": {},
            },
            {
                "id": "LunaTVSource.DownloadQueue",
                "name": "LunaTV 下载队列",
                "trigger": queue_trigger,
                "func": self.run_queue,
                "kwargs": {},
            },
        ]

    def stop_service(self) -> None:
        _restore_search_bridge(self)
        if self._queue:
            self._queue.stop()

    def _client(self) -> AppleCmsClient:
        config_url = str(self._config.get("config_url") or DEFAULT_CONFIG_URL)
        # 空白表示直接使用订阅地址内全部资源站；只有用户明确填写白名单时才过滤。
        # 旧版默认白名单也视为未配置，避免升级后继续隐式过滤订阅内容。
        configured_allowlist = str(self._config.get("source_allowlist") or "").strip()
        allowlist = (
            ()
            if not configured_allowlist or configured_allowlist == DEFAULT_SOURCE_ALLOWLIST
            else _source_keys(configured_allowlist)
        )
        sources = self._load_sources(
            config_url,
            timeout=float(self._config.get("request_timeout") or 15),
            allowlist=allowlist,
        )
        return AppleCmsClient(sources=sources, timeout=float(self._config.get("request_timeout") or 15))

    @staticmethod
    def _sources_from_cache(value: Any, allowlist: Tuple[str, ...]) -> List[CmsSource]:
        if not isinstance(value, list):
            return []
        allowed = {item.strip().lower() for item in allowlist if item.strip()}
        sources: List[CmsSource] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip().lower()
            api = str(item.get("api") or "").strip()
            if not key or not api:
                continue
            host = urllib.parse.urlparse(api).hostname or key
            if allowed and not ({key, host.lower()} & allowed):
                continue
            sources.append(
                CmsSource(
                    key=key,
                    name=str(item.get("name") or key),
                    api=api,
                    detail=str(item.get("detail") or ""),
                    comment=str(item.get("comment") or ""),
                )
            )
        return sources

    @staticmethod
    def _bundled_sources(allowlist: Tuple[str, ...]) -> List[CmsSource]:
        try:
            payload = json.loads(FALLBACK_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        from .cms import parse_config

        return parse_config(payload, allowlist=allowlist)

    def _load_sources(
        self,
        config_url: str,
        *,
        timeout: float,
        allowlist: Tuple[str, ...],
    ) -> List[CmsSource]:
        """Load sources with a persistent cache and bundled offline fallback.

        UGREEN deployments can run without outbound access to GitHub. A failed
        refresh must not make the plugin appear to have zero sources when a
        previous or bundled configuration is available.
        """

        try:
            sources = load_sources_from_url(config_url, timeout=timeout, allowlist=allowlist)
            if not sources:
                raise ValueError("远程配置未包含有效资源站")
            self.save_data(SOURCE_CACHE_KEY, [source.to_dict() for source in sources])
            self._source_config_origin = "远程配置"
            self._source_config_error = ""
            return sources
        except Exception as exc:
            self._source_config_error = str(exc)
            cached = self._sources_from_cache(self.get_data(SOURCE_CACHE_KEY), allowlist)
            if cached:
                self._source_config_origin = "本地缓存"
                self._logger.warning("LunaTV config unavailable; using %s cached sources", len(cached))
                return cached
            bundled = self._bundled_sources(allowlist)
            if bundled:
                self._source_config_origin = "内置快照"
                self._logger.warning("LunaTV config unavailable; using %s bundled sources", len(bundled))
                return bundled
            self._source_config_origin = "加载失败"
            raise

    @staticmethod
    def _host_media_source() -> Any:
        if _HostMediaSource is None:
            return PLUGIN_MEDIA_SOURCE
        try:
            return _HostMediaSource(PLUGIN_MEDIA_SOURCE)
        except Exception:
            return PLUGIN_MEDIA_SOURCE

    @staticmethod
    def _host_media_source_value(media_source: str) -> Any:
        if _HostMediaSource is None:
            return media_source
        try:
            return _HostMediaSource(media_source)
        except Exception:
            return media_source

    @staticmethod
    def _host_media_type(media_type: str) -> Any:
        if _HostMediaType is None:
            return media_type
        try:
            return _HostMediaType.TV if media_type == "tv" else _HostMediaType.MOVIE
        except Exception:
            return media_type

    @classmethod
    def _task_media_identity(cls, task: DownloadTask) -> Tuple[str, str]:
        source = _coerce_media_identity_source(
            getattr(task, "host_media_source", None) if getattr(task, "host_media_source", None) else task.source_key
        )
        media_id = str(
            getattr(task, "host_media_id", None)
            or task.media_id
            or ""
        ).strip()
        return source, media_id

    @staticmethod
    def _host_meta_info(title: str, year: str = "") -> Any:
        """Build MetaInfo across V3 runtimes (the SDK export is a function)."""

        if _HostMetaInfo is None:
            return None
        query = str(title or "").strip()
        year_text = str(year or "").strip()
        if year_text and year_text not in query:
            query = f"{query} ({year_text})"
        try:
            return _HostMetaInfo(title=query)
        except TypeError:
            # Standalone host stubs and older V3 snapshots may expose a
            # constructor accepting year separately.
            return _HostMetaInfo(title=query, year=year_text or None)

    def _media_info(self, result: CmsResult, association: Optional[Dict[str, Any]] = None) -> Any:
        """将 CMS 结果转换成 V3 原生 MediaInfo，供探索/订阅/整理链复用。"""
        if _schemas is None or not hasattr(_schemas, "MediaInfo"):
            return result.to_dict()
        seasons: Dict[int, List[int]] = {}
        for episode in result.episodes:
            if episode.season_known:
                seasons.setdefault(episode.season, []).append(episode.episode)
        association = association or {}
        title = normalize_media_title(result.title)
        title_year = f"{title} ({result.year})" if result.year else title
        fields: Dict[str, Any] = {
            "type": "电视剧" if result.media_type == "tv" else "电影",
            "title": title,
            "year": result.year or None,
            "title_year": title_year,
            "media_source": self._host_media_source(),
            "media_id": f"{result.source_key}:{result.vod_id}",
            "seasons": {key: sorted(set(value)) for key, value in seasons.items()},
            "detail_link": result.detail or None,
        }
        if association.get("status") == "matched" and association.get("tmdb_id"):
            fields["tmdb_id"] = association["tmdb_id"]
        for field in (
            "poster_path",
            "backdrop_path",
            "overview",
            "vote_average",
            "release_date",
        ):
            if association.get(field) not in (None, ""):
                fields[field] = association[field]
        try:
            return _schemas.MediaInfo(**fields)
        except TypeError:
            fields.pop("tmdb_id", None)
            return _schemas.MediaInfo(**fields)

    def _sdk_media_info(self, result: CmsResult) -> Any:
        """构造识别链使用的旧式 SDK MediaInfo（与探索 API 的 schema 分开）。"""
        try:
            from app.sdk.media import MediaInfo as SdkMediaInfo

            seasons: Dict[int, List[int]] = {}
            for episode in result.episodes:
                if episode.season_known:
                    seasons.setdefault(episode.season, []).append(episode.episode)
            return SdkMediaInfo(
                type=self._host_media_type(result.media_type),
                title=normalize_media_title(result.title),
                year=result.year or None,
                media_source=self._host_media_source(),
                media_id=f"{result.source_key}:{result.vod_id}",
                seasons={key: sorted(set(value)) for key, value in seasons.items()},
            )
        except Exception:
            return self._media_info(result)

    @staticmethod
    def _media_type_matches(configured: Any, media_type: str) -> bool:
        value = str(getattr(configured, "value", configured) or "").strip().lower()
        if not value:
            return True
        if media_type == "tv":
            return value in {"电视剧", "tv", "series", "tvshow"}
        return value in {"电影", "movie", "film"}

    def _system_directory_infos(self, media_type: str = "") -> List[Dict[str, Any]]:
        """Read local MoviePilot directory settings without copying them.

        The plugin only consumes configured local download roots.  Remote
        storage entries are intentionally omitted because this adapter writes
        with ffmpeg/``.strm`` directly inside the MoviePilot container.
        """

        if _HostDirectoryHelper is None:
            return []
        try:
            entries = _HostDirectoryHelper().get_download_dirs()
        except Exception as exc:
            self._logger.debug("读取 MoviePilot 目录设置失败：%s", exc)
            return []
        result: List[Dict[str, Any]] = []
        for item in entries or []:
            storage = str(getattr(item, "storage", "local") or "local").strip().lower()
            path = str(getattr(item, "download_path", "") or "").strip()
            if storage not in {"local", ""} or not path.startswith("/"):
                continue
            if media_type and not self._media_type_matches(getattr(item, "media_type", ""), media_type):
                continue
            result.append(
                {
                    "name": str(getattr(item, "name", "") or ""),
                    "priority": int(getattr(item, "priority", 0) or 0),
                    "download_path": path,
                    "library_path": str(getattr(item, "library_path", "") or "").strip(),
                    "media_type": str(getattr(getattr(item, "media_type", ""), "value", getattr(item, "media_type", "")) or ""),
                }
            )
        return sorted(result, key=lambda item: (item["priority"], item["download_path"]))

    def _system_directory_info(self, media_type: str, root: str = "") -> Optional[Dict[str, Any]]:
        infos = self._system_directory_infos(media_type)
        target = str(root or "").strip()
        if target:
            try:
                target_path = Path(target).expanduser().resolve()
                for item in infos:
                    if Path(item["download_path"]).expanduser().resolve() == target_path:
                        return item
            except OSError:
                pass
        return infos[0] if infos else None

    def _effective_root(self, subscribe: Any = None, media_type: str = "tv") -> str:
        explicit = str(self._config.get("download_root") or "").strip()
        if explicit:
            return explicit
        save_path = str(getattr(subscribe, "save_path", "") or "").strip()
        if save_path:
            return save_path
        directory = self._system_directory_info(media_type)
        return str(directory.get("download_path") if directory else "").strip()

    @staticmethod
    def _tmdb_source() -> Any:
        if _HostMediaSource is None:
            return None
        return getattr(_HostMediaSource, "TMDB", None)

    @staticmethod
    def _season_counts(media: Any) -> Dict[int, int]:
        raw = getattr(media, "seasons", None) or {}
        counts: Dict[int, int] = {}
        if isinstance(raw, dict):
            for season, episodes in raw.items():
                try:
                    season_number = int(season)
                except (TypeError, ValueError):
                    continue
                if isinstance(episodes, (list, tuple, set)):
                    count = len(episodes)
                else:
                    try:
                        count = int(episodes)
                    except (TypeError, ValueError):
                        count = 0
                if season_number > 0 and count > 0:
                    counts[season_number] = count
        return counts

    def _associate_tmdb(
        self,
        result: CmsResult,
        include_candidates: bool = True,
    ) -> Dict[str, Any]:
        """Find the default TMDB identity through MoviePilot's native chain."""

        query = normalize_search_title(result.title)
        cache_key = f"{query}|{result.year}|{result.media_type}"
        with self._tmdb_cache_lock:
            cached = self._tmdb_cache.get(cache_key)
        if cached is not None and (
            cached.get("status") != "matched"
            or cached.get("poster_path")
            # 原生资源搜索只需要默认关联，不需要给插件详情页准备候选
            # 下拉项。即使宿主没有返回海报，也直接复用该关联，避免
            # 每个 CMS 条目都再次触发 MoviePilot 的 TMDB 链。
            or not include_candidates
        ):
            association = dict(cached)
            if (
                include_candidates
                and association.get("status") == "matched"
                and not association.get("candidates")
            ):
                candidates = self._search_tmdb_candidates(query, result.year, result.media_type)
                if candidates:
                    association["candidates"] = candidates
                    with self._tmdb_cache_lock:
                        self._tmdb_cache[cache_key] = dict(association)
                        self.save_data("tmdb_match_cache_v1", dict(self._tmdb_cache))
            return association
        if _HostMediaChain is None or _HostMetaInfo is None or self._tmdb_source() is None:
            return {"status": "unavailable", "query": query}
        try:
            media = _HostMediaChain().recognize_media(
                meta=self._host_meta_info(query, result.year),
                mtype=self._host_media_type(result.media_type),
                media_source=self._tmdb_source(),
                cache=True,
            )
            if not media:
                association = {"status": "unmatched", "query": query}
            else:
                media_id = str(getattr(media, "media_id", "") or "")
                tmdb_id = getattr(media, "tmdb_id", None)
                if not tmdb_id and media_id.isdigit():
                    tmdb_id = int(media_id)
                association = {
                    "status": "matched",
                    "query": query,
                    "media_source": str(getattr(getattr(media, "media_source", None), "value", getattr(media, "media_source", "themoviedb")) or "themoviedb"),
                    "media_id": media_id or (str(tmdb_id) if tmdb_id else ""),
                    "tmdb_id": tmdb_id,
                    "title": str(getattr(media, "title", "") or ""),
                    "year": str(getattr(media, "year", "") or ""),
                    "season_counts": self._season_counts(media),
                    "poster_path": getattr(media, "poster_path", None),
                    "backdrop_path": getattr(media, "backdrop_path", None),
                    "overview": getattr(media, "overview", None),
                    "vote_average": getattr(media, "vote_average", None),
                    "release_date": getattr(media, "release_date", None),
                }
                if include_candidates:
                    candidates = self._search_tmdb_candidates(
                        query, result.year, result.media_type
                    )
                    if candidates:
                        association["candidates"] = candidates
        except Exception as exc:
            self._logger.debug("TMDB 默认关联失败 title=%s: %s", query, exc)
            association = {"status": "error", "query": query, "message": str(exc)}
        with self._tmdb_cache_lock:
            self._tmdb_cache[cache_key] = dict(association)
            self.save_data("tmdb_match_cache_v1", dict(self._tmdb_cache))
        return association

    @staticmethod
    def _media_candidate(media: Any) -> Optional[Dict[str, Any]]:
        """Convert a host MediaInfo candidate to a compact selectable payload."""

        media_id = str(getattr(media, "media_id", "") or "").strip()
        tmdb_id = getattr(media, "tmdb_id", None)
        if not tmdb_id and media_id.isdigit():
            tmdb_id = int(media_id)
        if not media_id and not tmdb_id:
            return None
        source = str(
            getattr(getattr(media, "media_source", None), "value", getattr(media, "media_source", "themoviedb"))
            or "themoviedb"
        )
        return {
            "media_source": source,
            "media_id": media_id or str(tmdb_id),
            "tmdb_id": tmdb_id,
            "title": str(getattr(media, "title", "") or ""),
            "year": str(getattr(media, "year", "") or ""),
            "type": _enum_value(getattr(media, "type", "")),
            "season": getattr(media, "season", None),
            "season_counts": LunaTVSource._season_counts(media),
        }

    def _search_tmdb_candidates(self, query: str, year: str = "", media_type: str = "") -> List[Dict[str, Any]]:
        """Search selectable TMDB candidates through MoviePilot's native chain."""

        if _HostMediaChain is None or _HostMetaInfo is None or self._tmdb_source() is None:
            return []
        try:
            meta = self._host_meta_info(query, year)
            if meta is None:
                return []
            if hasattr(meta, "type") and _HostMediaType is not None:
                meta.type = self._host_media_type(media_type)
            medias = _HostMediaChain().search_medias(meta=meta, media_source=self._tmdb_source()) or []
            candidates: List[Dict[str, Any]] = []
            seen = set()
            for media in medias:
                candidate = self._media_candidate(media)
                if not candidate:
                    continue
                identity = (candidate["media_source"], candidate["media_id"])
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append(candidate)
                if len(candidates) >= 8:
                    break
            return candidates
        except Exception as exc:
            self._logger.debug("TMDB 候选搜索失败 title=%s: %s", query, exc)
            return []

    def _prepare_result(self, result: CmsResult) -> Tuple[CmsResult, Dict[str, Any]]:
        association = self._associate_tmdb(result)
        if association.get("status") == "matched":
            result = apply_season_counts(result, association.get("season_counts") or {})
        return result, association

    def _result_payload(self, result: CmsResult) -> Dict[str, Any]:
        prepared, association = self._prepare_result(result)
        payload = prepared.to_dict()
        payload["normalized_title"] = normalize_media_title(prepared.title)
        payload["search_title"] = normalize_search_title(prepared.title)
        payload["association"] = association
        return payload

    def _local_episode_path(self, task: DownloadTask) -> Optional[Path]:
        """Return the completed local artifact for an episode, if it exists.

        ``media_path`` is also used by the downloader, so this returns the
        actual MP4/STRM artifact rather than merely treating the media
        directory as completed.  In particular, an empty directory or a
        transient download cache must not suppress a real download.
        """
        try:
            relative_dir, filename = media_path(
                task.root,
                task.title,
                task.year,
                task.media_type,
                task.season,
                task.episode,
                task.url,
                task.mode,
            )
            path = Path(task.root).expanduser() / relative_dir / filename
            return path if path.is_file() and path.stat().st_size > 0 else None
        except (OSError, ValueError):
            return None

    def _local_episode_exists(self, task: DownloadTask) -> bool:
        """Compatibility predicate for callers that only need completion state."""
        return self._local_episode_path(task) is not None

    @staticmethod
    def _history_numbers(value: Any) -> set[int]:
        """Parse MoviePilot season/episode fields such as ``S01`` or ``1-3,5``."""

        normalized = str(value or "").strip().upper()
        for marker in ("S", "E", "第", "季", "集", " "):
            normalized = normalized.replace(marker, "")
        normalized = (
            normalized.replace("～", "-")
            .replace("~", "-")
            .replace("至", "-")
            .replace("，", ",")
            .replace("、", ",")
        )
        numbers: set[int] = set()
        for token in normalized.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                start_text, _, end_text = token.partition("-")
                try:
                    start, end = int(start_text), int(end_text)
                except ValueError:
                    continue
                if 0 <= start <= end and end - start <= 10000:
                    numbers.update(range(start, end + 1))
                continue
            try:
                numbers.add(int(token))
            except ValueError:
                continue
        return numbers

    def _native_history_has_episode(self, task: DownloadTask) -> bool:
        """Use MoviePilot's durable download history to prevent subscription repeats.

        Queue persistence intentionally keeps only the latest 500 tasks. When
        MoviePilot moves a completed source file into the media library, the
        local download path can disappear; native TMDB download history is the
        durable completion record for older subscription items.
        """

        media_source, media_id = self._task_media_identity(task)
        if not media_source or not media_id:
            return False
        try:
            from app.db.oper.downloadhistory import DownloadHistoryOper

            oper = DownloadHistoryOper()
            get_by_identity = getattr(oper, "get_by_media_identity", None)
            if not callable(get_by_identity):
                return False
            histories = get_by_identity(
                media_source=self._host_media_source_value(media_source),
                media_id=media_id,
            ) or []
            get_files = getattr(oper, "get_files_by_hash", None)
            for history in histories:
                download_hash = str(getattr(history, "download_hash", "") or "").strip()
                if callable(get_files):
                    if not download_hash or not (get_files(download_hash, state=1) or []):
                        continue
                if task.media_type != "tv":
                    return True
                seasons = self._history_numbers(getattr(history, "seasons", ""))
                episodes = self._history_numbers(getattr(history, "episodes", ""))
                if task.season in seasons and task.episode in episodes:
                    return True
        except Exception as exc:
            self._logger.debug("读取 MoviePilot 下载历史失败：%s", exc)
        return False

    def _native_transfer(self, task: DownloadTask, output: str) -> str:
        """让 MoviePilot 原生整理链接管已下载文件；不可用时保留直写结果。"""
        if _HostStorageChain is None or _HostTransferChain is None:
            return "fallback:host-chain-unavailable"
        if task.mode == "strm":
            return "strm-direct"
        try:
            fileitem = _HostStorageChain().get_file_item(storage="local", path=Path(output))
            if not fileitem:
                return "fallback:file-not-found"
            media_source, media_id = self._task_media_identity(task)
            directory = self._system_directory_info(task.media_type, task.root)
            target_path = str((directory or {}).get("library_path") or task.root).strip()
            state, message = _HostTransferChain().manual_transfer(
                fileitem=fileitem,
                target_storage="local",
                target_path=Path(target_path),
                media_source=self._host_media_source_value(media_source),
                media_id=media_id,
                mtype=self._host_media_type(task.media_type),
                season=task.season if task.media_type == "tv" else None,
                force=False,
                background=False,
            )
            if state:
                return "moviepilot"
            return f"fallback:{message}"
        except Exception as exc:
            self._logger.warning("MoviePilot 原生整理失败，保留直写文件：%s", exc)
            return f"fallback:{exc}"

    def _record_native_history(self, task: DownloadTask, output: str) -> None:
        """把成功文件写入 MoviePilot 下载历史，供订阅详情读取。数据库不可用时不影响下载。"""
        media_source, media_id = self._task_media_identity(task)
        if not media_id:
            self._logger.debug("MoviePilot 下载历史缺少媒体身份，跳过下载历史写入")
            return
        output_path = str(Path(output)) if output else ""
        if not output_path:
            return
        download_hash = hashlib.sha1(f"{task.task_id}|{output_path}".encode("utf-8")).hexdigest()
        try:
            from app.db.oper.downloadhistory import DownloadHistoryOper
        except Exception as exc:
            self._logger.debug("MoviePilot 下载历史操作器不可用，跳过下载历史写入：%s", exc)
            return

        try:
            downloadhis = DownloadHistoryOper()
            get_by_hash = getattr(downloadhis, "get_by_hash", None)
            get_files_by_hash = getattr(downloadhis, "get_files_by_hash", None)
            get_file_by_fullpath = getattr(downloadhis, "get_file_by_fullpath", None)
            add_history = getattr(downloadhis, "add", None)
            add_files = getattr(downloadhis, "add_files", None)

            # V3 的订阅详情依赖这两个表；先验证可查询，避免重试时在旧宿主
            # 或异常数据库中重复写入。宿主缺少必要 ABI 时仅跳过历史，不影响文件。
            if (
                not callable(get_by_hash)
                or not (callable(get_files_by_hash) or callable(get_file_by_fullpath))
                or not callable(add_history)
                or not callable(add_files)
            ):
                self._logger.debug("MoviePilot 下载历史操作器不支持幂等写入，跳过下载历史写入")
                return

            existing_history = get_by_hash(download_hash)
            existing_files: List[Any] = []
            if callable(get_files_by_hash):
                try:
                    existing_files = list(get_files_by_hash(download_hash, state=1) or [])
                except TypeError:
                    existing_files = list(get_files_by_hash(download_hash) or [])
            existing_path_file = (
                get_file_by_fullpath(output_path)
                if callable(get_file_by_fullpath)
                else None
            )

            def _field(item: Any, key: str, default: Any = None) -> Any:
                if isinstance(item, dict):
                    return item.get(key, default)
                return getattr(item, key, default)

            def _active(item: Any) -> bool:
                state = _field(item, "state", 1)
                return str(state).lower() not in {"0", "false", "none", ""}

            has_same_hash_file = any(
                _active(item) and str(_field(item, "fullpath", "")) == output_path
                for item in existing_files
            )
            path_has_active_file = bool(existing_path_file and _active(existing_path_file))
            path_hash = str(_field(existing_path_file, "download_hash", "") or "")
            if path_has_active_file and path_hash != download_hash:
                # A refresh creates a new in-memory task id.  If the existing
                # path already belongs to this same native media identity, it
                # is an idempotent backfill/retry rather than a collision.
                existing_path_history = get_by_hash(path_hash) if path_hash else None
                if existing_path_history:
                    existing_source = _coerce_media_identity_source(
                        _field(existing_path_history, "media_source", "")
                    )
                    existing_media_id = str(
                        _field(existing_path_history, "media_id", "") or ""
                    ).strip()
                    if existing_source == media_source and existing_media_id == media_id:
                        self._logger.debug(
                            "MoviePilot 下载历史已记录本地文件，跳过重复写入：%s",
                            output_path,
                        )
                        return
                self._logger.warning(
                    "MoviePilot 下载历史文件路径已被其他任务记录，跳过重复写入：%s",
                    output_path,
                )
                return

            if not existing_history:
                add_history(
                    path=output_path,
                    type="电视剧" if task.media_type == "tv" else "电影",
                    title=task.title,
                    year=task.year or None,
                    media_source=media_source,
                    media_id=media_id,
                    seasons=str(task.season) if task.media_type == "tv" else None,
                    episodes=str(task.episode) if task.media_type == "tv" else None,
                    downloader="LunaTVSource",
                    download_hash=download_hash,
                    torrent_name=task.title,
                    torrent_description="LunaTV m3u8 下载",
                    torrent_site=str(
                        getattr(task, "source_name", "")
                        or getattr(task, "source_key", "")
                        or PLUGIN_MEDIA_SOURCE
                    ),
                    date=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                )
            if not has_same_hash_file and not path_has_active_file:
                add_files([
                    {
                        "download_hash": download_hash,
                        "downloader": "LunaTVSource",
                        "fullpath": output_path,
                        "savepath": str(Path(output_path).parent),
                        "filepath": Path(output_path).name,
                        "torrentname": task.title,
                        "state": 1,
                    }
                ])
        except Exception as exc:
            self._logger.warning("写入 MoviePilot 下载历史失败，文件下载不受影响：%s", exc)

    def _sync_media_server(self) -> bool:
        """后台刷新 Emby/Jellyfin，使新文件出现在既有媒体库。"""
        if _HostMediaServerChain is None:
            return False
        with self._media_sync_lock:
            if self._media_sync_running:
                return False
            self._media_sync_running = True

        server = str(self._config.get("mediaserver_name") or "").strip() or None

        def runner() -> None:
            try:
                _HostMediaServerChain().sync(server=server)
            except Exception as exc:
                self._logger.warning("媒体服务器同步失败：%s", exc)
            finally:
                with self._media_sync_lock:
                    self._media_sync_running = False

        threading.Thread(target=runner, name="lunatvsource-mediaserver-sync", daemon=True).start()
        return True

    def _notify(self, title: str, text: str) -> None:
        post_message = getattr(self, "post_message", None)
        if callable(post_message):
            try:
                post_message(title=title, text=text)
                return
            except TypeError:
                try:
                    post_message(text, title=title)
                    return
                except Exception:
                    pass
            except Exception:
                pass
        self._logger.info("%s: %s", title, text)

    def api_status(self) -> Dict[str, Any]:
        queue = self._queue or DownloadQueue(lambda *_: None, lambda *_: None, self._notify)
        directories = self._system_directory_infos()
        configured_root = str(self._config.get("download_root") or "").strip()
        return {
            "success": True,
            "data": {
                "enabled": self._enabled,
                "queue": queue.summary(),
                "ai": (self._ai or AiTitleNormalizer(False)).status(),
                "media_source": PLUGIN_MEDIA_SOURCE,
                "media_server_sync_running": self._media_sync_running,
                "directories": {
                    "configured_root": configured_root,
                    "auto_roots": directories,
                    "source": "插件设置" if configured_root else ("MoviePilot 目录设置" if directories else "未配置"),
                },
                "tmdb_association": True,
                "source_config": {
                    "origin": self._source_config_origin,
                    "error": self._source_config_error,
                },
            },
        }

    def api_sources(self) -> Dict[str, Any]:
        try:
            sources = self._client().sources
            return {"success": True, "data": [source.to_dict() for source in sources]}
        except Exception as exc:
            return {"success": False, "message": f"读取 LunaTV 配置失败：{exc}", "data": []}

    def api_search(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        query = str(payload.get("query") or payload.get("title") or "").strip()
        if not query:
            return {"success": False, "message": "请输入电影或剧集名称", "data": []}
        try:
            search_query, _ = (self._ai or AiTitleNormalizer(False)).normalize(
                query,
                str(payload.get("year") or ""),
                str(payload.get("media_type") or ""),
            )
            results = self._client().search(search_query, stop_after_first_source=True)
            return {"success": True, "data": [self._result_payload(item) for item in results]}
        except Exception as exc:
            self._logger.warning("LunaTV search failed: %s", exc)
            return {"success": False, "message": f"搜索失败：{exc}", "data": []}

    def api_tmdb_search(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Search selectable TMDB candidates for a normalized CMS title."""

        payload = payload or {}
        query = normalize_search_title(str(payload.get("query") or payload.get("title") or "").strip())
        if not query:
            return {"success": False, "message": "缺少搜索名称", "data": []}
        try:
            candidates = self._search_tmdb_candidates(
                query,
                str(payload.get("year") or ""),
                str(payload.get("media_type") or ""),
            )
            return {"success": True, "data": candidates}
        except Exception as exc:
            self._logger.warning("LunaTV TMDB candidate search failed: %s", exc)
            return {"success": False, "message": f"TMDB 搜索失败：{exc}", "data": []}

    def api_discover(
        self,
        keyword: str = "",
        query: str = "",
        title: str = "",
        page: int = 1,
        count: int = 30,
    ) -> Dict[str, Any]:
        """V3 探索数据源接口，返回宿主统一 MediaInfo，而非插件自定义播放器。"""
        del page
        query = str(keyword or query or title or "").strip()
        if not query:
            return {"success": True, "data": []}
        try:
            search_query, _ = (self._ai or AiTitleNormalizer(False)).normalize(query)
            results = self._client().search(
                search_query,
                limit=max(1, min(int(count or 30), 50)),
                stop_after_first_source=True,
                # 探索页只展示元数据；播放地址在原生资源搜索/下载时再读取。
                # 避免列表结果缺少 vod_play_url 时逐条请求详情，导致界面长时间骨架屏。
                enrich=False,
            )
            data = []
            for result in results:
                prepared, association = self._prepare_result(result)
                data.append(self._media_info(prepared, association))
            return {"success": True, "data": data}
        except Exception as exc:
            self._logger.warning("LunaTV discover failed: %s", exc)
            return {"success": False, "message": f"探索失败：{exc}", "data": []}

    def api_tasks(self) -> Dict[str, Any]:
        queue = self._queue or DownloadQueue(lambda *_: None, lambda *_: None, self._notify)
        return {"success": True, "data": queue.list_tasks()}

    def api_download(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        queue = self._queue
        if queue is None:
            return {"success": False, "message": "插件尚未初始化", "data": {}}
        episode_payload = payload.get("episode") or {}
        if not isinstance(episode_payload, dict):
            episode_payload = {}
        url = str(episode_payload.get("url") or payload.get("url") or "").strip()
        if not url:
            return {"success": False, "message": "缺少 m3u8 地址", "data": {}}
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"success": False, "message": "只允许 http/https m3u8 地址", "data": {}}
        episode = CmsEpisode(
            season=int(episode_payload.get("season") or payload.get("season") or 1),
            episode=int(episode_payload.get("episode") or payload.get("episode") or 1),
            label=str(episode_payload.get("label") or ""),
            url=url,
            season_known=bool(episode_payload.get("season_known", True)),
        )
        media_type = _media_type_value(payload.get("media_type") or "tv")
        root = str(payload.get("root") or "").strip()
        if not root:
            root = self._effective_root(media_type=media_type)
        if not root:
            return {"success": False, "message": "未找到下载目录，请先配置插件目录或 MoviePilot 目录设置", "data": {}}
        task = DownloadTask.from_episode(
            episode,
            title=normalize_media_title(str(payload.get("title") or "未命名")),
            year=str(payload.get("year") or ""),
            media_type=media_type,
            root=root,
            mode=str(payload.get("mode") or self._config.get("mode") or "download"),
            ffmpeg_path=str(payload.get("ffmpeg_path") or self._config.get("ffmpeg_path") or "ffmpeg"),
            media_source="lunatv",
            media_id=str(payload.get("media_id") or payload.get("vod_id") or "manual"),
        )
        if not queue.enqueue(task):
            return {"success": False, "message": "任务重复，或未配置下载目录", "data": {}}
        return {"success": True, "message": "已加入串行下载队列", "data": {"task_id": task.task_id}}

    def _record_completion(self, task: DownloadTask, output: str) -> None:
        organize_state = self._native_transfer(task, output)
        # 下载历史始终记录 ffmpeg 的原始产物。若原生整理成功，TransferChain
        # 会自行记录 TransferHistory；这里不能把整理目标伪装成下载源文件。
        self._record_native_history(task, output)
        self._sync_media_server()

    def api_sync(self) -> Dict[str, Any]:
        if not self._enabled:
            return {"success": False, "message": "请先启用插件", "data": {}}
        started = self._start_background(self.refresh_subscriptions)
        return {"success": True, "message": "已加入刷新队列" if started else "刷新正在执行", "data": {"started": started}}

    def api_retry(self, task_id: str) -> Dict[str, Any]:
        queue = self._queue
        if not queue or not queue.retry(task_id):
            return {"success": False, "message": "任务不存在或不可重试", "data": {}}
        return {"success": True, "data": {"task_id": task_id}}

    def _start_background(self, func) -> bool:
        with self._refresh_lock:
            if self._refresh_running:
                return False
            self._refresh_running = True

        def runner() -> None:
            try:
                func()
            finally:
                with self._refresh_lock:
                    self._refresh_running = False

        threading.Thread(target=runner, name="lunatvsource-refresh", daemon=True).start()
        return True

    def refresh_subscriptions(self) -> Dict[str, Any]:
        """读取 MoviePilot 活跃订阅；宿主缺少订阅操作器时安全返回。"""
        try:
            from app.db.oper.subscribe import SubscribeOper
        except Exception:
            self._logger.debug("SubscribeOper unavailable; refresh skipped")
            return {"subscriptions": 0, "queued": 0, "reconciled": 0}

        queue = self._queue
        if queue is None:
            return {"subscriptions": 0, "queued": 0, "reconciled": 0}
        try:
            try:
                subscribes = SubscribeOper().list(state="R")
            except TypeError:
                subscribes = SubscribeOper().list()
        except Exception as exc:
            self._logger.warning("读取 MoviePilot 订阅失败：%s", exc)
            return {"subscriptions": 0, "queued": 0, "reconciled": 0, "error": str(exc)}

        client = self._client()
        queued = 0
        reconciled = 0
        skipped_ambiguous = 0
        skipped_no_directory = 0
        active_subscribes = []
        for subscribe in subscribes or []:
            state = str(getattr(getattr(subscribe, "state", None), "value", getattr(subscribe, "state", "R")) or "R")
            if state not in {"R", "1", "active", "enabled"}:
                continue
            active_subscribes.append(subscribe)
        for subscribe in active_subscribes:
            title = str(getattr(subscribe, "name", "") or getattr(subscribe, "keyword", "")).strip()
            if not title:
                continue
            normalized_title = title
            try:
                identity_source = _coerce_media_identity_source(getattr(subscribe, "media_source", ""))
                identity_id = str(getattr(subscribe, "media_id", "") or "").strip()
                identity_result: Optional[CmsResult] = None
                if identity_source == PLUGIN_MEDIA_SOURCE and ":" in identity_id:
                    source_key, vod_id = identity_id.split(":", 1)
                    identity_result = client.detail(source_key, vod_id)
                if identity_result:
                    results = [identity_result]
                else:
                    search_query, _ = (self._ai or AiTitleNormalizer(False)).normalize(
                        title,
                        str(getattr(subscribe, "year", "") or ""),
                        str(getattr(subscribe, "type", "") or ""),
                    )
                    normalized_title = search_query or title
                    results = client.search(search_query)
                prepared_results = []
                for result in results:
                    prepared, association = self._prepare_result(result)
                    prepared_results.append((prepared, association))
                results = prepared_results
            except Exception as exc:
                self._logger.warning("订阅搜索失败 title=%s error=%s", title, exc)
                continue
            target_type = str(
                getattr(
                    getattr(subscribe, "type", None),
                    "value",
                    getattr(subscribe, "media_type", getattr(subscribe, "type", "")),
                )
                or ""
            )
            season = int(getattr(subscribe, "season", 0) or 0)
            matching_results = []
            for result, association in results:
                if target_type and result.media_type and target_type not in {result.media_type, "电视剧" if result.media_type == "tv" else "电影"}:
                    continue
                season_in_range = result.season_range[0] <= season <= result.season_range[1]
                if any(season <= 0 or episode.season == season for episode in result.episodes) or (
                    result.season_ambiguous and season > 0 and season_in_range
                ):
                    matching_results.append((result, association))
            if str(self._config.get("source_strategy") or "first") != "all":
                matching_results = matching_results[:1]
            for result, association in matching_results:
                if result.season_ambiguous:
                    # A flat 1-8 season bundle cannot be named safely without
                    # exact season counts.  TMDB mapping above resolves the
                    # common case; otherwise leave it for manual selection.
                    skipped_ambiguous += 1
                    continue
                root = self._effective_root(subscribe, result.media_type)
                if not root:
                    skipped_no_directory += 1
                    continue
                for episode in result.episodes:
                    if season > 0 and episode.season != season:
                        continue
                    tmdb_source = _coerce_media_identity_source(association.get("media_source"))
                    tmdb_id = str(association.get("media_id") or association.get("tmdb_id") or "").strip()
                    task_title = str(
                        association.get("title")
                        or (normalized_title if normalized_title != title else result.title)
                        or "未命名"
                    )
                    task = DownloadTask.from_episode(
                        episode,
                        title=normalize_media_title(task_title),
                        year=result.year,
                        media_type=result.media_type,
                        root=root,
                        mode=str(self._config.get("mode") or "download"),
                        ffmpeg_path=str(self._config.get("ffmpeg_path") or "ffmpeg"),
                        source_name=result.source_name or None,
                        media_source=result.source_key or PLUGIN_MEDIA_SOURCE,
                        media_id=f"{result.source_key}:{result.vod_id}",
                    )
                    if identity_source != PLUGIN_MEDIA_SOURCE and identity_id:
                        task.host_media_source = identity_source
                        task.host_media_id = identity_id
                    elif association.get("status") == "matched" and tmdb_id:
                        # A subscription created from the plugin source may
                        # not carry a host TMDB identity.  Reuse the same
                        # native association used by the search result so the
                        # completion transfer can scrape and file the media.
                        task.host_media_source = tmdb_source
                        task.host_media_id = tmdb_id
                    existing_path = self._local_episode_path(task)
                    if existing_path is not None:
                        # Older plugin versions could leave a correctly
                        # downloaded MP4/STRM without the V3 download-history
                        # rows.  Reconcile only that original artifact: do not
                        # run transfer again or fabricate TransferHistory.
                        self._record_native_history(task, str(existing_path))
                        reconciled += 1
                        continue
                    if self._native_history_has_episode(task):
                        reconciled += 1
                        continue
                    if queue.enqueue(task):
                        queued += 1
        return {
            "subscriptions": len(active_subscribes),
            "queued": queued,
            "reconciled": reconciled,
            "skipped_ambiguous": skipped_ambiguous,
            "skipped_no_directory": skipped_no_directory,
        }

    def run_queue(self) -> Dict[str, Any]:
        if not self._queue:
            return {"processed": 0}
        return self._queue.run_one()

    def get_media_source(self) -> List[Dict[str, Any]]:
        """LunaTV participates in the global search instead of adding an empty Explore tab."""
        return []

    def _active_download_torrent(self, task: DownloadTask) -> Any:
        """将串行队列中的活跃任务归一为 MoviePilot 下载器任务。"""
        media_source, media_id = self._task_media_identity(task)
        season_episode = None
        if task.media_type == "tv":
            try:
                season_episode = f"S{int(task.season):02d}E{int(task.episode):02d}"
            except (TypeError, ValueError):
                pass
        values = {
            "downloader": "LunaTVSource",
            "hash": str(task.task_id),
            "title": task.title,
            "name": task.title,
            "site_name": task.source_name or task.source_key or PLUGIN_MEDIA_SOURCE,
            "year": task.year or None,
            "season_episode": season_episode,
            "state": "paused" if task.state == "paused" else "downloading",
            # Queue persistence uses a 0..1 fraction; MoviePilot's
            # DownloaderTorrent contract expects a 0..100 percentage.
            "progress": max(0.0, min(100.0, float(getattr(task, "progress", 0.0) or 0.0) * 100.0)),
            "save_path": task.root or None,
            "media": {
                "type": "电视剧" if task.media_type == "tv" else "电影",
                "title": task.title,
                "season": task.season if task.media_type == "tv" else None,
                "episode": task.episode if task.media_type == "tv" else None,
                "media_source": self._host_media_source_value(media_source),
                "media_id": media_id or None,
            },
        }
        torrent_type = (
            getattr(_schemas, "DownloaderTorrent", None)
            if _schemas is not None
            else None
        )
        if callable(torrent_type):
            try:
                return torrent_type(**values)
            except Exception as exc:
                self._logger.debug("构造 MoviePilot 下载任务投影失败，使用兼容对象：%s", exc)
        return _CompatDownloaderTorrent(**values)

    def list_torrents(
        self,
        status: Any = None,
        hashs: Any = None,
        downloader: Optional[str] = None,
        include_all_tags: bool = False,
    ) -> Optional[List[Any]]:
        """提供 LunaTV 队列中的活跃任务，由宿主继续合并系统下载器结果。"""
        del include_all_tags
        if not self._enabled:
            return None
        # MoviePilot 的原生下载页始终携带当前系统下载器名称；模块调度器会把
        # 本列表与该系统下载器的结果继续合并，因此这里不能按名称排除插件任务。
        del downloader

        if isinstance(hashs, str):
            requested_hashes = {hashs.strip()} if hashs.strip() else set()
        elif hashs:
            try:
                requested_hashes = {
                    str(value).strip() for value in hashs if str(value).strip()
                }
            except TypeError:
                requested_hashes = {str(hashs).strip()} if str(hashs).strip() else set()
        else:
            requested_hashes = set()

        status_value = _enum_value(status)
        if not requested_hashes and status_value in {
            "transfer",
            "可转移",
            "completed",
            "complete",
            "seeding",
            "完成",
            "已完成",
        }:
            return []

        queue = self._queue
        if queue is None:
            return []
        try:
            raw_tasks = queue.list_tasks()
        except Exception as exc:
            self._logger.debug("读取 LunaTV 活跃下载任务失败：%s", exc)
            return []

        torrents: List[Any] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                continue
            try:
                task = DownloadTask(**raw_task)
            except TypeError:
                continue
            task_hash = str(task.task_id or "").strip()
            task_state = str(task.state or "").lower()
            if not task_hash or task_state not in {"pending", "running", "paused"}:
                continue
            if requested_hashes and task_hash not in requested_hashes:
                continue
            if not requested_hashes:
                if status_value in {"paused", "pause", "暂停", "已暂停"} and task_state != "paused":
                    continue
                if status_value in {"downloading", "下载中"} and task_state == "paused":
                    continue
            torrents.append(self._active_download_torrent(task))
        return torrents

    @staticmethod
    def _torrent_hashes(hashs: Any) -> List[str]:
        if isinstance(hashs, str):
            return [hashs.strip()] if hashs.strip() else []
        if hashs:
            try:
                return [str(value).strip() for value in hashs if str(value).strip()]
            except TypeError:
                value = str(hashs).strip()
                return [value] if value else []
        return []

    def _control_queue_tasks(self, hashs: Any, operation: str) -> Optional[bool]:
        """Handle native controls only when every requested hash belongs to LunaTV."""
        queue = self._queue
        requested = self._torrent_hashes(hashs)
        if queue is None or not requested:
            return None
        try:
            known = {
                str(item.get("task_id") or "")
                for item in queue.list_tasks()
                if isinstance(item, dict)
            }
        except Exception:
            return None
        if any(task_id not in known for task_id in requested):
            return None
        handler = getattr(queue, operation, None)
        if not callable(handler):
            return False
        return all(bool(handler(task_id)) for task_id in requested)

    def start_torrents(
        self, hashs: Any, downloader: Optional[str] = None
    ) -> Optional[bool]:
        """Continue paused LunaTV tasks from MoviePilot's native download page."""
        del downloader
        return self._control_queue_tasks(hashs, "resume")

    def stop_torrents(
        self, hashs: Any, downloader: Optional[str] = None
    ) -> Optional[bool]:
        """Pause queued or running LunaTV tasks from the native download page."""
        del downloader
        return self._control_queue_tasks(hashs, "pause")

    def remove_torrents(
        self,
        hashs: Any,
        delete_file: bool = True,
        downloader: Optional[str] = None,
    ) -> Optional[bool]:
        """Remove LunaTV tasks without forwarding their synthetic hashes to qBittorrent."""
        del delete_file, downloader
        return self._control_queue_tasks(hashs, "remove")

    def get_module(self) -> Dict[str, Any]:
        """接入 V3 媒体识别、资源搜索、下载和活跃任务查询入口。"""
        if not self._enabled:
            return {}
        return {
            "recognize_media": self.recognize_media,
            "async_recognize_media": self.async_recognize_media,
            "search_medias": self.search_medias,
            "async_search_medias": self.async_search_medias,
            "search_torrents": self.search_torrents,
            "async_search_torrents": self.async_search_torrents,
            "download": self.download,
            "list_torrents": self.list_torrents,
            "start_torrents": self.start_torrents,
            "stop_torrents": self.stop_torrents,
            "remove_torrents": self.remove_torrents,
        }

    @staticmethod
    def _search_source_enabled(media_source: Any) -> bool:
        """Run for an unrestricted global search, or when LunaTV is explicitly selected."""
        if media_source in (None, "", (), []):
            return True
        values = media_source if isinstance(media_source, (list, tuple, set)) else (media_source,)
        return any(_enum_value(value) == PLUGIN_MEDIA_SOURCE for value in values)

    def search_medias(self, meta: Any, media_source: Any = None, **_: Any) -> List[Any]:
        """Add CMS media cards to MoviePilot's native global media search."""
        if not self._enabled or not self._search_source_enabled(media_source):
            return []
        query = str(
            getattr(meta, "name", "")
            or getattr(meta, "title", "")
            or getattr(meta, "cn_name", "")
            or ""
        ).strip()
        if not query:
            return []
        try:
            search_query, _ = (self._ai or AiTitleNormalizer(False)).normalize(
                query,
                str(getattr(meta, "year", "") or ""),
                _media_type_value(getattr(meta, "type", "")),
            )
            results = self._client().search(
                search_query,
                limit=8,
                stop_after_first_source=True,
                enrich=False,
            )
            medias = []
            for result in results:
                prepared, association = self._prepare_result(result)
                medias.append(self._media_info(prepared, association))
            return medias
        except Exception as exc:
            self._logger.warning("LunaTV 全局媒体搜索失败：%s", exc)
            return []

    async def async_search_medias(self, **kwargs: Any) -> List[Any]:
        return await asyncio.to_thread(self.search_medias, **kwargs)

    @staticmethod
    def _resource_token(payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        digest = hashlib.sha1(raw).hexdigest()
        return f"magnet:?xt=urn:btih:{digest}&x.lunatv={encoded}"

    @staticmethod
    def _decode_resource_token(content: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(content, str) or not content.startswith("magnet:"):
            return None
        encoded = (urllib.parse.parse_qs(urllib.parse.urlparse(content).query).get("x.lunatv") or [""])[0]
        if not encoded:
            return None
        try:
            encoded += "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _resource_search_context(
        search_query: str,
        results: List[CmsResult],
        mtype: Any = None,
    ) -> CmsResult:
        """Build one TMDB lookup context for an entire CMS resource search.

        A native resource search fans out to several CMS sources.  Those
        sources often return the same title with different IDs, so associating
        every row separately serializes the MoviePilot TMDB chain after the
        parallel CMS work has already completed.  The native keyword is the
        user-selected media context; use it once and reuse that identity for
        every returned playable resource.
        """

        first = results[0] if results else None
        requested_type = _enum_value(mtype)
        media_type = (
            _media_type_value(mtype)
            if requested_type
            else (first.media_type if first else "movie")
        )
        return CmsResult(
            source_key="",
            source_name="",
            vod_id="",
            title=normalize_search_title(search_query),
            year=first.year if first else "",
            media_type=media_type,
            remark="",
        )

    @staticmethod
    def _apply_resource_association(
        result: CmsResult,
        association: Dict[str, Any],
    ) -> CmsResult:
        """Apply the one search-context association without re-querying TMDB."""

        if association.get("status") == "matched":
            return apply_season_counts(result, association.get("season_counts") or {})
        return result

    def _resource_torrents(self, keyword: str, mtype: Any = None) -> List[Any]:
        """把 CMS m3u8 条目投影为 MoviePilot 原生 TorrentInfo。"""
        torrent_info_type = _HostTorrentInfo or (
            getattr(_schemas, "TorrentInfo", None) if _schemas is not None else None
        )
        if torrent_info_type is None:
            return []
        requested_type = _enum_value(mtype)
        cache_key = "|".join(
            (
                normalize_search_title(keyword).casefold(),
                requested_type,
            )
        )
        now = time.monotonic()
        with self._resource_search_lock:
            cached = self._resource_search_cache.get(cache_key)
            if cached and now - cached[0] < 30:
                return list(cached[1])

        # 第三方 CMS、AI 与 TMDB 请求可能较慢，不能在请求期间占用缓存锁；
        # 否则插件更新/停用时会一直等待正在进行的原生资源搜索。
        search_query, _ = (self._ai or AiTitleNormalizer(False)).normalize(keyword)
        results = self._client().search(
            search_query,
            limit=50,
            source_limit=3,
            stop_after_first_source=False,
            require_playable=True,
            max_workers=8,
        )
        # The resource search is one user-selected native media context, not
        # one TMDB lookup per CMS source/result.  AI normalization and the
        # default TMDB association therefore run exactly once here; the same
        # host media identity is embedded in every returned download token.
        association: Dict[str, Any] = {}
        if results:
            context = self._resource_search_context(search_query, results, mtype)
            association = self._associate_tmdb(context, include_candidates=False)
        # TV resources are presented as one native download item per
        # source/season.  The enclosure carries the ordered episode list and
        # ``download`` expands it back into the plugin's serial queue.  This
        # matches how an Apple CMS result is published (for example,
        # “小猪佩奇 第一季 第52集”), while still keeping every source selectable.
        season_groups: Dict[Tuple[str, str, str, str, int], Dict[str, Any]] = {}
        single_rows: List[Dict[str, Any]] = []
        seen_single_urls: set[Tuple[str, str]] = set()

        def episode_payload(
            result: CmsResult,
            episode: CmsEpisode,
            identity: str,
            host_media_source: str,
            host_media_id: str,
        ) -> Dict[str, Any]:
            return {
                "url": episode.url,
                "title": normalize_media_title(result.title),
                "year": result.year,
                "media_type": result.media_type,
                "season": int(episode.season or 1),
                "episode": int(episode.episode or 1),
                "label": episode.label,
                "season_known": bool(episode.season_known),
                "source_key": result.source_key,
                "source_name": result.source_name,
                "media_id": identity,
                "host_media_source": host_media_source,
                "host_media_id": host_media_id,
            }

        for result in results:
            result = self._apply_resource_association(result, association)
            identity = f"{result.source_key}:{result.vod_id}"
            host_media_source = str(
                association.get("media_source") or PLUGIN_MEDIA_SOURCE
            )
            host_media_id = str(association.get("media_id") or identity)
            episodes = result.episodes or [CmsEpisode(1, 1, "正片", "")]
            for episode in episodes:
                if not episode.url:
                    continue
                payload = episode_payload(
                    result, episode, identity, host_media_source, host_media_id
                )
                if result.media_type == "tv" and episode.season_known:
                    group_key = (
                        result.source_key,
                        result.source_name,
                        normalize_media_title(result.title),
                        result.year,
                        int(episode.season or 1),
                    )
                    group = season_groups.setdefault(
                        group_key,
                        {
                            "site_name": result.source_name or "LunaTV",
                            "title": normalize_media_title(result.title),
                            "year": result.year,
                            "season": int(episode.season or 1),
                            "source_key": result.source_key,
                            "source_name": result.source_name,
                            "media_id": identity,
                            "host_media_source": host_media_source,
                            "host_media_id": host_media_id,
                            "page_url": result.detail,
                            "episodes": [],
                            "urls": set(),
                        },
                    )
                    if episode.url not in group["urls"]:
                        group["urls"].add(episode.url)
                        group["episodes"].append(payload)
                    continue

                # A flat multi-season bundle without reliable TMDB counts is
                # deliberately kept as an episode-level fallback.  It is
                # safer than silently assigning an episode to the wrong season.
                single_key = (result.source_key, episode.url)
                if single_key in seen_single_urls:
                    continue
                seen_single_urls.add(single_key)
                single_rows.append({
                    "site_name": result.source_name or "LunaTV",
                    "title": normalize_media_title(result.title),
                    "year": result.year,
                    "payload": payload,
                    "page_url": result.detail,
                })

        torrents: List[Any] = []
        for group in season_groups.values():
            group_episodes = sorted(
                group["episodes"],
                key=lambda item: (int(item["season"]), int(item["episode"]), item["url"]),
            )
            season = int(group["season"])
            count = len(group_episodes)
            first = group_episodes[0]
            payload = dict(first)
            payload["episodes"] = group_episodes
            title = group["title"]
            if group["year"]:
                title = f"{title} ({group['year']})"
            title = f"{title} · S{season:02d} · {count}集"
            torrents.append(torrent_info_type(
                site_name=group["site_name"],
                title=title,
                description=f"LunaTV · m3u8 · {count}集",
                media_source=group["host_media_source"],
                media_id=group["host_media_id"],
                enclosure=self._resource_token(payload),
                page_url=group["page_url"],
                size=0,
                seeders=1,
                category="电视剧",
                labels=["LunaTV", "m3u8", f"S{season:02d}", f"{count}集"],
            ))

        for row in single_rows:
            payload = row["payload"]
            title = row["title"]
            if row["year"]:
                title = f"{title} ({row['year']})"
            if payload["media_type"] == "tv":
                title = f"{title} S{int(payload['season']):02d}E{int(payload['episode']):02d}"
            torrents.append(torrent_info_type(
                site_name=row["site_name"],
                title=title,
                description="LunaTV · m3u8",
                media_source=payload["host_media_source"],
                media_id=payload["host_media_id"],
                enclosure=self._resource_token(payload),
                page_url=row["page_url"],
                size=0,
                seeders=1,
                category="电视剧" if payload["media_type"] == "tv" else "电影",
                labels=["LunaTV", "m3u8"],
            ))
        with self._resource_search_lock:
            self._resource_search_cache[cache_key] = (time.monotonic(), torrents)
        return list(torrents)

    def search_torrents(
        self,
        site: Dict[str, Any],
        keyword: str,
        mtype: Any = None,
        page: Optional[int] = 0,
        **_: Any,
    ) -> List[Any]:
        """参与每次原生站点搜索；固定站点名使多站点调用结果可由宿主去重。"""
        del site
        if not self._enabled or int(page or 0) > 0 or not str(keyword or "").strip():
            return []
        try:
            return self._resource_torrents(str(keyword).strip(), mtype=mtype)
        except Exception as exc:
            self._logger.warning("LunaTV 原生资源搜索失败：%s", exc)
            return []

    async def async_search_torrents(self, **kwargs: Any) -> List[Any]:
        return await asyncio.to_thread(self.search_torrents, **kwargs)

    def download(
        self,
        content: Any,
        download_dir: Path,
        cookie: str = "",
        episodes: Any = None,
        category: Optional[str] = None,
        label: Optional[str] = None,
        downloader: Optional[str] = None,
        **_: Any,
    ) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], str]]:
        """接管带 LunaTV 标记的原生下载，转入插件持久化串行队列。"""
        del cookie, episodes, category, label, downloader
        payload = self._decode_resource_token(content)
        if payload is None:
            return None
        queue = self._queue
        root = str(download_dir or "").strip()
        url = str(payload.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if queue is None or not root or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "LunaTVSource", None, None, "LunaTV 下载参数无效"
        raw_episodes = payload.get("episodes")
        entries = raw_episodes if isinstance(raw_episodes, list) and raw_episodes else [payload]
        enqueued_ids: List[str] = []
        duplicate_count = 0
        invalid_count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                invalid_count += 1
                continue
            entry_url = str(entry.get("url") or "").strip()
            entry_parsed = urllib.parse.urlparse(entry_url)
            if entry_parsed.scheme not in {"http", "https"} or not entry_parsed.netloc:
                invalid_count += 1
                continue
            try:
                season = int(entry.get("season") or 1)
                episode_number = int(entry.get("episode") or 1)
            except (TypeError, ValueError):
                invalid_count += 1
                continue
            episode = CmsEpisode(
                season=max(1, season),
                episode=max(1, episode_number),
                label=str(entry.get("label") or ""),
                url=entry_url,
                season_known=bool(entry.get("season_known", True)),
            )
            resource_identity = str(entry.get("media_id") or payload.get("media_id") or "").strip()
            source_key = str(entry.get("source_key") or payload.get("source_key") or "").strip()
            if not source_key and ":" in resource_identity:
                source_key = resource_identity.split(":", 1)[0].strip()
            source_key = source_key or PLUGIN_MEDIA_SOURCE
            task = DownloadTask.from_episode(
                episode,
                title=normalize_media_title(str(entry.get("title") or payload.get("title") or "未命名")),
                year=str(entry.get("year") or payload.get("year") or ""),
                media_type=_media_type_value(entry.get("media_type") or payload.get("media_type")),
                root=root,
                mode=str(self._config.get("mode") or "download"),
                ffmpeg_path=str(self._config.get("ffmpeg_path") or "ffmpeg"),
                source_name=str(entry.get("source_name") or payload.get("source_name") or "") or None,
                media_source=source_key,
                media_id=resource_identity or "native",
            )
            task.host_media_source = _coerce_media_identity_source(
                entry.get("host_media_source") or payload.get("host_media_source")
            )
            task.host_media_id = str(
                entry.get("host_media_id")
                or payload.get("host_media_id")
                or resource_identity
                or "native"
            ).strip()
            task.task_id = hashlib.sha1(
                f"{content}:{task.season}:{task.episode}:{entry_url}".encode("utf-8")
            ).hexdigest()
            if queue.enqueue(task):
                enqueued_ids.append(task.task_id)
            else:
                duplicate_count += 1
        if not enqueued_ids:
            if invalid_count:
                return "LunaTVSource", None, None, "LunaTV 下载参数无效"
            return "LunaTVSource", None, None, "任务已在串行队列或历史记录中"
        total = len(enqueued_ids)
        message = f"已排队 {total} 集" if total > 1 else ""
        if duplicate_count:
            message += f"，{duplicate_count} 集已在队列"
        if invalid_count:
            message += f"，{invalid_count} 集参数无效"
        return "LunaTVSource", enqueued_ids[0], "NoSubfolder", message

    def recognize_media(
        self,
        meta: Any = None,
        mtype: Any = None,
        media_source: Any = None,
        media_id: Optional[str] = None,
        **_: Any,
    ) -> Any:
        if not self._enabled or _enum_value(media_source) != PLUGIN_MEDIA_SOURCE:
            return None
        try:
            client = self._client()
            result: Optional[CmsResult] = None
            identity_id = str(media_id or "").strip()
            if ":" in identity_id:
                source_key, vod_id = identity_id.split(":", 1)
                result = client.detail(source_key, vod_id)
            if result is None and meta is not None:
                title = str(getattr(meta, "title", "") or "").strip()
                if title:
                    result = (client.search(normalize_search_title(title), limit=1) or [None])[0]
            if not result:
                return None
            result, association = self._prepare_result(result)
            # 原生详情页需要统一 MediaInfo 的完整展示字段；仅返回 SDK 最小对象
            # 会导致自定义来源详情页无法渲染。
            return self._media_info(result, association)
        except Exception as exc:
            self._logger.debug("LunaTV 原生识别失败：%s", exc)
            return None

    async def async_recognize_media(self, *args: Any, **kwargs: Any) -> Any:
        return self.recognize_media(*args, **kwargs)

    @eventmanager.register(getattr(ChainEventType, "ResourceDownload", "resource.download"))
    def _on_resource_download(self, event: Event) -> None:
        """保留事件兼容入口，但不取消 MoviePilot 的原生下载链。

        V3 会在事件之后调用插件模块提供的 ``download`` 方法。若在这里把
        ``event_data.cancel`` 设为 ``True``，宿主会把已经入队的任务仍判定为
        “任务添加失败”，并且不会记录原生下载历史。真正的接管由
        :meth:`download` 完成，这里只识别 LunaTV 标记后放行。
        """

        if not self._enabled or not event:
            return
        event_data = getattr(event, "event_data", None)
        context = getattr(event_data, "context", None)
        torrent = getattr(context, "torrent_info", None)
        if self._decode_resource_token(getattr(torrent, "enclosure", None)) is None:
            return
        event_data.source = "LunaTVSource-原生下载模块"

    @eventmanager.register(getattr(EventType, "SubscribeAdded", "subscribe.added"))
    def _on_subscribe_added(self, event: Event) -> None:
        if self._enabled:
            self._start_background(self.refresh_subscriptions)

    @eventmanager.register(getattr(EventType, "SubscribeModified", "subscribe.modified"))
    def _on_subscribe_modified(self, event: Event) -> None:
        if self._enabled:
            self._start_background(self.refresh_subscriptions)

    @eventmanager.register(getattr(EventType, "PluginAction", "plugin.action"))
    def _on_plugin_action(self, event: Event) -> None:
        """Handle the registered remote command without claiming other actions."""

        event_data = getattr(event, "event_data", None) or {}
        if isinstance(event_data, dict) and event_data.get("action") == "sync":
            if self._enabled:
                self._start_background(self.refresh_subscriptions)
