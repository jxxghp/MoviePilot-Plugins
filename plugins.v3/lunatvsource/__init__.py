"""MoviePilot V3 plugin for MoonTV/LunaTV Apple CMS sources.

The first implementation deliberately keeps the source adapter independent from
MoviePilot internals.  The host integration is optional at import time so the
pure search, naming and queue code can be tested outside a running MoviePilot.
"""

from __future__ import annotations

import json
import base64
import hashlib
import inspect
import logging
import asyncio
from contextvars import ContextVar
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    probe_stream_height,
    stream_quality_label,
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
_TMDB_CACHE_MAX_ENTRIES = 512
_QUALITY_CACHE_MAX_ENTRIES = 512
_RESOURCE_SEARCH_CACHE_MAX_ENTRIES = 128
_RESOURCE_SEARCH_CACHE_TTL = 30.0


def _resource_sort_priority(height: int) -> int:
    """Keep resolution order inside MoviePilot's three-digit sort slot."""
    return min(999, max(0, int(height or 0) // 10))


def _field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


# MoviePilot 3.0.0 returns before module resource providers are called when no
# PT/indexer site is enabled. Keep this compatibility bridge inside the plugin.
# Existing MoviePilot plugins use the same reversible runtime-wrapper pattern.
_SEARCH_BRIDGE: Dict[str, Any] = {
    "owner": None,
    "chain": None,
    "originals": {},
    "mode": None,
}
_SEARCH_PROGRESS_CALLBACK: ContextVar[Optional[Callable[..., None]]] = ContextVar(
    "lunatv_search_progress_callback",
    default=None,
)


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
        "media_source": _field(mediainfo, "media_source"),
        "media_id": _field(mediainfo, "media_id"),
        "media_title": _field(mediainfo, "title"),
        "media_year": _field(mediainfo, "year"),
    }


def _progress_stream_event(
    *,
    finished: int,
    total: int,
    text: str,
    page: Any,
) -> Optional[Dict[str, Any]]:
    try:
        total_value = max(0, int(total))
        finished_value = max(0, int(finished))
    except (TypeError, ValueError):
        return None
    if total_value:
        finished_value = min(finished_value, total_value)
        value = min(100, int(finished_value * 100 / total_value))
    else:
        finished_value = 0
        value = 100
    return {
        "type": "progress",
        "stage": "searching",
        "value": value,
        "text": str(text or f"LunaTV 正在搜索源 {finished_value}/{total_value}"),
        "items": [],
        "site": "LunaTV",
        "site_id": None,
        "page": page,
        "finished": finished_value,
        "total": total_value,
    }


def _is_compatible_search_stream(callback: Any) -> bool:
    return callable(callback) and inspect.isasyncgenfunction(callback)


def _make_search_stream_wrapper(
    owner: "LunaTVSource",
    stream_original: Callable[..., Any],
    *,
    native_plugin_fanout: bool,
) -> Callable[..., Any]:
    @wraps(stream_original)
    async def stream_wrapper(chain: Any, *args: Any, **kwargs: Any):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        state = {"active": True, "closed": False}
        page = kwargs.get("page") or 0
        legacy_plugin = _bridge_owner() if not native_plugin_fanout else None

        def progress_callback(*, finished: int, total: int, text: str) -> None:
            if not state["active"] or state["closed"]:
                return
            event = _progress_stream_event(
                finished=finished,
                total=total,
                text=text,
                page=page,
            )
            if event is None:
                return

            def enqueue() -> None:
                if state["active"] and not state["closed"]:
                    queue.put_nowait(("event", event))

            try:
                loop.call_soon_threadsafe(enqueue)
            except RuntimeError:
                # The event loop may already be closed during shutdown.
                return

        async def flush_progress_callbacks() -> None:
            # CMS callbacks come from asyncio.to_thread. Yield once before a
            # host event so every already-scheduled X/N remains ordered ahead
            # of append/done.
            await asyncio.sleep(0)

        async def emit(event: Any, *, close_progress: bool = False) -> None:
            await flush_progress_callbacks()
            if close_progress:
                state["active"] = False
            queue.put_nowait(("event", event))

        async def pump() -> None:
            token = _SEARCH_PROGRESS_CALLBACK.set(progress_callback)
            try:
                if native_plugin_fanout:
                    async for event in stream_original(chain, *args, **kwargs):
                        await emit(
                            event,
                            close_progress=isinstance(event, dict)
                            and event.get("type") == "done",
                        )
                else:
                    done_event = None
                    async for event in stream_original(chain, *args, **kwargs):
                        if isinstance(event, dict) and event.get("type") == "done":
                            done_event = event
                            continue
                        await emit(event)

                    plugin_items: List[Any] = []
                    if legacy_plugin:
                        try:
                            plugin_items = await legacy_plugin.async_search_torrents(
                                **_bridge_search_kwargs(kwargs)
                            )
                        except Exception as exc:
                            legacy_plugin._logger.warning(
                                "LunaTV 原生流式资源搜索追加失败：%s",
                                exc,
                            )

                    if plugin_items:
                        await emit(
                            {
                                "type": "append",
                                "stage": "searching",
                                "value": 100,
                                "text": f"LunaTV 返回 {len(plugin_items)} 条资源",
                                "site": "LunaTV",
                                "site_id": None,
                                "page": page,
                                "finished": 0,
                                "total": 0,
                                "total_items": len(plugin_items),
                                "items": plugin_items,
                            }
                        )
                    final = dict(done_event or {})
                    final.update(
                        {
                            "type": "done",
                            "stage": final.get("stage", "searching"),
                            "value": 100,
                            "items": [],
                        }
                    )
                    if plugin_items:
                        final["text"] = (
                            f"资源搜索完成，LunaTV 返回 {len(plugin_items)} 条资源"
                        )
                    await emit(final, close_progress=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                owner._logger.warning("LunaTV 原生流式资源搜索失败：%s", exc)
                queue.put_nowait(("error", exc))
            finally:
                _SEARCH_PROGRESS_CALLBACK.reset(token)
                state["active"] = False
                queue.put_nowait(("end", None))

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "end":
                    break
                if kind == "error":
                    raise payload
                yield payload
        finally:
            state["active"] = False
            state["closed"] = True
            if not pump_task.done():
                pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass

    return stream_wrapper


def _install_search_bridge(owner: "LunaTVSource") -> None:
    try:
        from app.chain.search import SearchChain
    except Exception as exc:  # pragma: no cover - MoviePilot runtime only
        owner._logger.warning("LunaTV 原生资源搜索桥接不可用：%s", exc)
        return

    native_plugin_fanout = (
        callable(getattr(SearchChain, "search_plugin_torrents", None))
        and callable(getattr(SearchChain, "async_search_plugin_torrents", None))
    )
    mode = "native_stream" if native_plugin_fanout else "legacy"
    if _SEARCH_BRIDGE.get("chain") is SearchChain and _SEARCH_BRIDGE.get("originals"):
        if _SEARCH_BRIDGE.get("mode") == mode:
            _SEARCH_BRIDGE["owner"] = owner
            return
        _restore_search_bridge(owner, force=True)
    elif _SEARCH_BRIDGE.get("chain") is not None and _SEARCH_BRIDGE.get("originals"):
        _restore_search_bridge(owner, force=True)

    _SEARCH_BRIDGE["owner"] = owner
    sync_name = "_SearchChain__search_all_sites"
    async_name = "_SearchChain__async_search_all_sites"
    stream_name = "_SearchChain__async_search_all_sites_stream"
    stream_original = getattr(SearchChain, stream_name, None)

    if native_plugin_fanout:
        if not _is_compatible_search_stream(stream_original):
            owner._logger.info(
                "MoviePilot 原生插件资源搜索已启用，但搜索流接口不兼容；保持原生行为"
            )
            return
        originals = {stream_name: stream_original}
        setattr(
            SearchChain,
            stream_name,
            _make_search_stream_wrapper(
                owner,
                stream_original,
                native_plugin_fanout=True,
            ),
        )
        _SEARCH_BRIDGE.update(
            {
                "chain": SearchChain,
                "originals": originals,
                "mode": mode,
            }
        )
        owner._logger.info("LunaTV 已接入 MoviePilot 原生搜索流进度")
        return

    originals: Dict[str, Callable[..., Any]] = {}
    sync_original = getattr(SearchChain, sync_name, None)
    if callable(sync_original):
        originals[sync_name] = sync_original

        @wraps(sync_original)
        def sync_wrapper(chain: Any, *args: Any, **kwargs: Any) -> List[Any]:
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
        async def async_wrapper(chain: Any, *args: Any, **kwargs: Any) -> List[Any]:
            native = list(await async_original(chain, *args, **kwargs) or [])
            plugin = _bridge_owner()
            if plugin:
                try:
                    native.extend(
                        await plugin.async_search_torrents(
                            **_bridge_search_kwargs(kwargs)
                        )
                    )
                except Exception as exc:
                    plugin._logger.warning("LunaTV 原生异步资源搜索追加失败：%s", exc)
            return native

        setattr(SearchChain, async_name, async_wrapper)

    if _is_compatible_search_stream(stream_original):
        originals[stream_name] = stream_original
        setattr(
            SearchChain,
            stream_name,
            _make_search_stream_wrapper(
                owner,
                stream_original,
                native_plugin_fanout=False,
            ),
        )
    elif callable(stream_original):
        owner._logger.warning(
            "LunaTV 原生流式资源搜索桥接未安装：目标不是异步生成器"
        )

    if not originals:
        return
    _SEARCH_BRIDGE.update(
        {
            "chain": SearchChain,
            "originals": originals,
            "mode": mode,
        }
    )
    owner._logger.info("LunaTV 已启用 MoviePilot 搜索兼容桥：%s", ", ".join(originals))


def _restore_search_bridge(owner: "LunaTVSource", force: bool = False) -> None:
    if not force and _SEARCH_BRIDGE.get("owner") is not owner:
        return
    chain = _SEARCH_BRIDGE.get("chain")
    originals = dict(_SEARCH_BRIDGE.get("originals") or {})
    if chain:
        for name, original in originals.items():
            setattr(chain, name, original)
    _SEARCH_BRIDGE.update(
        {
            "owner": None,
            "chain": None,
            "originals": {},
            "mode": None,
        }
    )

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
    plugin_icon = "https://raw.githubusercontent.com/OneBigMoon/moviepilot-v3-lunatv-source/master/icons/lunatvsource.png"
    plugin_version = "0.4.47"
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
        self._download_metrics_lock = threading.Lock()
        self._download_metrics: Dict[str, Tuple[float, int]] = {}
        self._quality_cache_lock = threading.Lock()
        self._quality_cache: Dict[str, Tuple[float, int]] = {}
        self._quality_probe_ms: Dict[str, int] = {}

    def _queue_data_path(self) -> Optional[Path]:
        """Use MoviePilot's plugin-owned data directory for managed binaries/cache."""
        getter = getattr(self, "get_data_path", None)
        if not callable(getter):
            return None
        try:
            value = getter()
            return Path(value).expanduser() if value else None
        except (OSError, TypeError, ValueError):
            return None

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
            data_path=self._queue_data_path(),
        )
        with self._tmdb_cache_lock:
            loaded_tmdb_cache = dict(self.get_data("tmdb_match_cache_v1") or {})
            self._tmdb_cache = dict(
                list(loaded_tmdb_cache.items())[-_TMDB_CACHE_MAX_ENTRIES:]
            )
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
                        "component": "VTextField",
                        "props": {
                            "model": "probe_allowed_private_ranges",
                            "label": "清晰度探测允许网段（可选）",
                            "placeholder": "10.0.0.0/8,192.168.0.0/16",
                            "hint": "默认拒绝内网播放地址；仅当可信 CMS 返回内网媒体时填写 CIDR。",
                            "persistentHint": True,
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
            "probe_allowed_private_ranges": "",
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
                        "component": "VTextField",
                        "props": {
                            "model": "probe_allowed_private_ranges",
                            "label": "清晰度探测允许网段（可选）",
                            "placeholder": "10.0.0.0/8,192.168.0.0/16",
                            "hint": "默认拒绝内网播放地址；仅当可信 CMS 返回内网媒体时填写 CIDR。",
                            "persistentHint": True,
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
            "probe_allowed_private_ranges": "",
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

    def _media_info(
        self,
        result: CmsResult,
        association: Optional[Dict[str, Any]] = None,
        season_only: bool = False,
    ) -> Any:
        """将 CMS 结果转换成 V3 原生 MediaInfo，供探索/订阅/整理链复用。"""
        seasons: Dict[int, List[int]] = {}
        for episode in result.episodes:
            if episode.season_known:
                seasons.setdefault(episode.season, []).append(episode.episode)
        if season_only and not seasons:
            season_start, season_end = result.season_range
            if season_start > 0 and season_start == season_end:
                seasons[season_start] = []
        if _schemas is None or not hasattr(_schemas, "MediaInfo"):
            payload = result.to_dict()
            if season_only:
                payload["episodes"] = []
                payload["seasons"] = {season: [] for season in sorted(seasons)}
            return payload
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
            "seasons": {
                key: [] if season_only else sorted(set(value))
                for key, value in seasons.items()
            },
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

    @staticmethod
    def _search_result_seasons(result: CmsResult) -> List[int]:
        """Return only season numbers that are safe to project onto search cards."""
        if result.media_type == "tv" and result.season_ambiguous:
            season_start, season_end = result.season_range
            if season_start > 0 and season_end >= season_start:
                return list(range(season_start, season_end + 1))
        seasons = sorted(
            {
                max(1, int(episode.season or 1))
                for episode in result.episodes
                if episode.season_known
            }
        )
        if seasons or result.media_type != "tv":
            return seasons

        title = str(result.title or "")
        match = re.search(
            r"(?:第\s*(?P<season>\d{1,3})\s*季|\bS\s*(?P<s_season>\d{1,3})(?:\s*E\s*\d{1,4})?\b)",
            title,
            re.IGNORECASE,
        )
        if match:
            return [int(match.group("season") or match.group("s_season"))]

        chinese = re.search(r"第\s*(?P<season>[一二两三四五六七八九十]+)\s*季", title)
        if not chinese:
            return []
        value = chinese.group("season").replace("两", "二")
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if value == "十":
            return [10]
        if "十" in value:
            tens, ones = value.split("十", 1)
            return [(digits.get(tens, 1) if tens else 1) * 10 + digits.get(ones, 0)]
        return [digits[value]] if value in digits else []

    @classmethod
    def _season_media_cards(cls, results: List[CmsResult]) -> List[CmsResult]:
        """Collapse episode-indexed CMS rows into one non-episode card per season."""
        groups: Dict[Tuple[str, str, str, str, int], Dict[str, Any]] = {}
        order: List[Tuple[str, Any]] = []

        for result in results:
            if result.media_type != "tv":
                order.append(("result", result))
                continue

            title = normalize_media_title(result.title)
            seasons = cls._search_result_seasons(result) or [0]
            for season in seasons:
                key = (result.source_key, result.source_name, title, result.year, season)
                group = groups.get(key)
                if group is None:
                    group = {
                        "result": result,
                        "episodes": {},
                        "season_ambiguous": bool(result.season_ambiguous),
                    }
                    groups[key] = group
                    order.append(("group", key))
                else:
                    group["season_ambiguous"] = bool(
                        group["season_ambiguous"] and result.season_ambiguous
                    )
                for episode in result.episodes:
                    if season and (not episode.season_known or episode.season != season):
                        continue
                    if not season and episode.season_known:
                        continue
                    group["episodes"].setdefault(
                        (episode.season, episode.episode, episode.url), episode
                    )

        cards: List[CmsResult] = []
        for kind, value in order:
            if kind == "result":
                cards.append(value)
                continue
            source_key, source_name, title, year, season = value
            group = groups[value]
            base = group["result"]
            episodes = tuple(
                sorted(
                    group["episodes"].values(),
                    key=lambda episode: (episode.season, episode.episode, episode.url),
                )
            )
            cards.append(
                CmsResult(
                    source_key=source_key,
                    source_name=source_name,
                    vod_id=base.vod_id,
                    title=title,
                    year=year,
                    media_type="tv",
                    remark=base.remark,
                    episodes=episodes,
                    detail=base.detail,
                    season_range=(season, season) if season else (0, 0),
                    season_ambiguous=bool(group["season_ambiguous"]),
                )
            )
        return cards

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
                    self._store_tmdb_cache_entry(cache_key, association)
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
        self._store_tmdb_cache_entry(cache_key, association)
        return association

    def _store_tmdb_cache_entry(
        self,
        cache_key: str,
        association: Dict[str, Any],
    ) -> None:
        with self._tmdb_cache_lock:
            self._tmdb_cache.pop(cache_key, None)
            self._tmdb_cache[cache_key] = dict(association)
            overflow = len(self._tmdb_cache) - _TMDB_CACHE_MAX_ENTRIES
            for key in list(self._tmdb_cache)[:max(0, overflow)]:
                self._tmdb_cache.pop(key, None)
            snapshot = dict(self._tmdb_cache)
            self.save_data("tmdb_match_cache_v1", snapshot)

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
            results = self._season_media_cards(
                self._client().search(
                    search_query,
                    stop_after_first_source=True,
                    expand_tv_episode_rows=True,
                )
            )
            data = []
            for result in results:
                item = self._result_payload(result)
                if result.media_type == "tv":
                    seasons = sorted(
                        {
                            int(episode.season or 1)
                            for episode in result.episodes
                            if episode.season_known
                        }
                    )
                    if len(seasons) == 1:
                        item["title"] = (
                            f"{normalize_media_title(result.title)} · 第{seasons[0]}季"
                        )
                data.append(item)
            return {"success": True, "data": data}
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
            for result in self._season_media_cards(results):
                prepared, association = self._prepare_result(result)
                if prepared.media_type == "tv":
                    data.append(self._media_info(prepared, association, season_only=True))
                else:
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
        content = payload.get("content") or payload.get("enclosure")
        raw_episodes = payload.get("episodes")
        has_episodes = isinstance(raw_episodes, list) and bool(raw_episodes)
        if content or has_episodes:
            resource_payload = (
                self._decode_resource_token(content) if content else dict(payload)
            )
            if resource_payload is None:
                return {
                    "success": False,
                    "message": "无效的 LunaTV 资源令牌",
                    "data": {"task_id": None},
                }
            resource_episodes = resource_payload.get("episodes")
            if isinstance(resource_episodes, list) and not resource_episodes:
                resource_payload.pop("episodes", None)
                content = None
            if not content:
                content = self._resource_token(resource_payload)
            media_type = _media_type_value(
                resource_payload.get("media_type") or payload.get("media_type") or "tv"
            )
            root = str(payload.get("root") or "").strip() or self._effective_root(
                media_type=media_type
            )
            if not root:
                return {
                    "success": False,
                    "message": "未找到下载目录，请先配置插件目录或 MoviePilot 目录设置",
                    "data": {"task_id": None},
                }
            native_result = self.download(content, Path(root))
            if native_result is None:
                return {
                    "success": False,
                    "message": "无效的 LunaTV 资源令牌",
                    "data": {"task_id": None},
                }
            _, task_id, _, message = native_result
            return {
                "success": bool(task_id),
                "message": message,
                "data": {"task_id": task_id},
            }
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
        self._start_queue()
        return {"success": True, "message": "已加入串行下载队列", "data": {"task_id": task.task_id}}

    def _record_completion(self, task: DownloadTask, output: str) -> None:
        if self._config.get("moviepilot_organize", True):
            self._native_transfer(task, output)
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
                # Match MoviePilot's native subscription search semantics:
                # both resolved (R) and pending (P) subscriptions remain searchable.
                subscribes = SubscribeOper().list(state="R,P")
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
            if state not in {"R", "P", "1", "active", "enabled"}:
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
                is_plugin_season = (
                    identity_source == PLUGIN_MEDIA_SOURCE
                    and int(getattr(subscribe, "season", 0) or 0) > 0
                )
                identity_result: Optional[CmsResult] = None
                if (
                    identity_source == PLUGIN_MEDIA_SOURCE
                    and not is_plugin_season
                    and ":" in identity_id
                ):
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
                    results = client.search(search_query, expand_tv_episode_rows=True)
                prepared_results = []
                for result in results:
                    prepared, association = self._prepare_result(result)
                    prepared_results.append((prepared, association))
                if is_plugin_season:
                    associations = {
                        (result.source_key, result.vod_id): association
                        for result, association in prepared_results
                    }
                    prepared_results = [
                        (
                            result,
                            associations.get((result.source_key, result.vod_id), {}),
                        )
                        for result in self._season_media_cards(
                            [result for result, _ in prepared_results]
                        )
                    ]
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
                matching_results = self._rank_subscription_results(
                    matching_results,
                    season=season,
                )
                matching_results = matching_results[:1]
            if is_plugin_season:
                selected_results: List[Tuple[CmsResult, Dict[str, Any]]] = []
                ambiguous_results: List[Tuple[CmsResult, Dict[str, Any]]] = []
                for result, association in matching_results:
                    if result.season_ambiguous:
                        ambiguous_results.append((result, association))
                        continue

                    episode_candidates: Dict[Tuple[int, int], List[CmsEpisode]] = {}
                    for episode in result.episodes:
                        if season > 0 and episode.season != season:
                            continue
                        episode_candidates.setdefault(
                            (int(episode.season), int(episode.episode)), []
                        ).append(episode)

                    conflict_urls: List[str] = []
                    unique_candidates: Dict[Tuple[int, int], List[CmsEpisode]] = {}
                    for key, candidates in episode_candidates.items():
                        seen_urls: set[str] = set()
                        unique_candidates[key] = []
                        for candidate in candidates:
                            url = candidate.url
                            if not url or url in seen_urls:
                                continue
                            seen_urls.add(url)
                            unique_candidates[key].append(candidate)
                        if len(unique_candidates[key]) > 1:
                            conflict_urls.extend(
                                candidate.url for candidate in unique_candidates[key]
                            )

                    conflict_heights = self._probe_resource_urls(conflict_urls)
                    selected_episodes: List[CmsEpisode] = []
                    for candidates in unique_candidates.values():
                        if not candidates:
                            continue
                        _, episode = max(
                            enumerate(candidates),
                            key=lambda item: (
                                conflict_heights.get(item[1].url, 0),
                                -item[0],
                            ),
                        )
                        selected_episodes.append(episode)

                    if not selected_episodes:
                        continue
                    selected_results.append(
                        (
                            CmsResult(
                                source_key=result.source_key,
                                source_name=result.source_name,
                                vod_id=result.vod_id,
                                title=result.title,
                                year=result.year,
                                media_type=result.media_type,
                                remark=result.remark,
                                episodes=tuple(selected_episodes),
                                detail=result.detail,
                                season_range=result.season_range,
                                season_ambiguous=False,
                            ),
                            association,
                        )
                    )
                matching_results = ambiguous_results + selected_results
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
        if queued:
            self._start_queue()
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
        return {"processed": 0, "scheduled": self._queue.wake()}

    def _start_queue(self) -> bool:
        """立即唤醒一次串行队列，避免原生继续操作等待下个定时周期。"""
        queue = self._queue
        if queue is None:
            return False
        return queue.wake()

    def get_media_source(self) -> List[Dict[str, Any]]:
        """LunaTV participates in the global search instead of adding an empty Explore tab."""
        return []

    def _active_download_torrent(self, task: DownloadTask) -> Any:
        """将串行队列中的活跃任务归一为 MoviePilot 下载器任务。"""
        media_source, media_id = self._task_media_identity(task)
        size, dlspeed = self._active_download_metrics(task)
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
            "size": size,
            "dlspeed": dlspeed,
            "upspeed": "0.0B",
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

    @staticmethod
    def _format_download_speed(value: float) -> str:
        units = ("B", "K", "M", "G")
        amount = max(0.0, float(value or 0.0))
        unit = units[0]
        for candidate in units:
            unit = candidate
            if amount < 1024 or candidate == units[-1]:
                break
            amount /= 1024
        return f"{amount:.1f}{unit}"

    def _active_download_metrics(self, task: DownloadTask) -> Tuple[float, Optional[str]]:
        """根据 ffmpeg 临时文件为原生下载页补充大小和实时速度。"""
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
            root = Path(task.root).expanduser().resolve()
            output = (root / relative_dir / filename).resolve()
            if root not in output.parents:
                raise ValueError("目标路径越界")
            partial = Path(f"{output}.part")
            current_size = partial.stat().st_size if partial.is_file() else 0
        except (OSError, RuntimeError, TypeError, ValueError):
            current_size = 0

        now = time.monotonic()
        speed = 0.0
        task_id = str(task.task_id or "")
        with self._download_metrics_lock:
            previous = self._download_metrics.get(task_id)
            if current_size > 0:
                self._download_metrics[task_id] = (now, current_size)
                if previous and current_size >= previous[1] and now > previous[0]:
                    speed = (current_size - previous[1]) / (now - previous[0])
            else:
                self._download_metrics.pop(task_id, None)

        progress = max(0.0, min(0.99, float(getattr(task, "progress", 0.0) or 0.0)))
        estimated_size = float(current_size)
        if current_size > 0 and progress > 0:
            estimated_size = max(estimated_size, current_size / progress)
        return estimated_size, self._format_download_speed(speed) if current_size > 0 else None

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

    def _control_queue_tasks(
        self,
        hashs: Any,
        operation: str,
        *,
        delete_file: bool = False,
    ) -> Optional[bool]:
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
        if operation == "remove":
            return all(
                bool(handler(task_id, delete_file=delete_file))
                for task_id in requested
            )
        return all(bool(handler(task_id)) for task_id in requested)

    def start_torrents(
        self, hashs: Any, downloader: Optional[str] = None
    ) -> Optional[bool]:
        """Continue paused LunaTV tasks from MoviePilot's native download page."""
        del downloader
        resumed = self._control_queue_tasks(hashs, "resume")
        if resumed:
            self._start_queue()
        return resumed

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
        """Remove LunaTV tasks locally and honor MoviePilot's delete-file choice."""
        del downloader
        return self._control_queue_tasks(hashs, "remove", delete_file=delete_file)

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
            for result in self._season_media_cards(results):
                prepared, association = self._prepare_result(result)
                if prepared.media_type == "tv":
                    medias.append(self._media_info(prepared, association, season_only=True))
                else:
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
        explicit_type = requested_type in {
            "电视剧",
            "tv",
            "series",
            "show",
            "tvshow",
            "电影",
            "movie",
            "film",
            "movies",
        }
        media_type = (
            _media_type_value(mtype)
            if explicit_type
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

    def _probe_quality(self, url: str) -> int:
        """Return cached HLS video height, probing the first stream when needed."""

        now = time.monotonic()
        with self._quality_cache_lock:
            self._prune_quality_cache(now)
            cached = self._quality_cache.get(url)
            if cached and now - cached[0] < (3600 if cached[1] else 300):
                return cached[1]
        try:
            timeout = min(max(float(self._config.get("request_timeout") or 6), 3.0), 6.0)
        except (TypeError, ValueError):
            timeout = 8.0
        height = probe_stream_height(
            url,
            ffmpeg_path=str(self._config.get("ffmpeg_path") or "ffmpeg"),
            timeout=timeout,
            allowed_private_ranges=self._probe_allowed_private_ranges(),
        )
        finished_at = time.monotonic()
        probe_ms = max(1, round((finished_at - now) * 1000))
        with self._quality_cache_lock:
            self._quality_cache[url] = (finished_at, height)
            self._quality_probe_ms[url] = probe_ms
            self._prune_quality_cache(finished_at)
        return height

    def _probe_latency_ms(self, url: str) -> int:
        with self._quality_cache_lock:
            return max(0, int(self._quality_probe_ms.get(url, 0) or 0))

    def _probe_allowed_private_ranges(self) -> Tuple[str, ...]:
        configured = self._config.get("probe_allowed_private_ranges")
        if isinstance(configured, str):
            values = re.split(r"[,;\s]+", configured)
        elif isinstance(configured, (list, tuple, set)):
            values = list(configured)
        else:
            values = []
        return tuple(str(value).strip() for value in values if str(value).strip())

    def _prune_quality_cache(self, now: float) -> None:
        expired = [
            key
            for key, (created_at, height) in self._quality_cache.items()
            if now - created_at >= (3600 if height else 300)
        ]
        for key in expired:
            self._quality_cache.pop(key, None)
            self._quality_probe_ms.pop(key, None)
        overflow = len(self._quality_cache) - _QUALITY_CACHE_MAX_ENTRIES
        if overflow > 0:
            oldest = sorted(
                self._quality_cache,
                key=lambda key: self._quality_cache[key][0],
            )[:overflow]
            for key in oldest:
                self._quality_cache.pop(key, None)
                self._quality_probe_ms.pop(key, None)
        for key in tuple(self._quality_probe_ms):
            if key not in self._quality_cache:
                self._quality_probe_ms.pop(key, None)

    def _prune_resource_search_cache(self, now: float) -> None:
        expired = [
            key
            for key, (created_at, _) in self._resource_search_cache.items()
            if now - created_at >= _RESOURCE_SEARCH_CACHE_TTL
        ]
        for key in expired:
            self._resource_search_cache.pop(key, None)
        overflow = len(self._resource_search_cache) - _RESOURCE_SEARCH_CACHE_MAX_ENTRIES
        if overflow > 0:
            oldest = sorted(
                self._resource_search_cache,
                key=lambda key: self._resource_search_cache[key][0],
            )[:overflow]
            for key in oldest:
                self._resource_search_cache.pop(key, None)

    def _probe_resource_urls(self, urls: List[str]) -> Dict[str, int]:
        unique_urls = list(dict.fromkeys(url for url in urls if url))
        if not unique_urls:
            return {}
        heights: Dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(unique_urls))) as executor:
            futures = {executor.submit(self._probe_quality, url): url for url in unique_urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    heights[url] = max(0, int(future.result() or 0))
                except Exception as exc:
                    self._logger.debug("清晰度探测失败 url=%s: %s", url, exc)
                    heights[url] = 0
        return heights

    @staticmethod
    def _result_probe_url(result: CmsResult, season: int = 0) -> str:
        return next(
            (
                episode.url
                for episode in result.episodes
                if episode.url and (season <= 0 or episode.season == season)
            ),
            "",
        )

    def _rank_subscription_results(
        self,
        results: List[Tuple[CmsResult, Dict[str, Any]]],
        season: int = 0,
    ) -> List[Tuple[CmsResult, Dict[str, Any]]]:
        """Prefer a verified higher-resolution source while keeping ties stable."""

        if len(results) < 2:
            return results
        urls = [self._result_probe_url(result, season) for result, _ in results]
        heights = self._probe_resource_urls(urls)
        ranked = sorted(
            enumerate(results),
            key=lambda item: (
                -heights.get(self._result_probe_url(item[1][0], season), 0),
                item[0],
            ),
        )
        return [item for _, item in ranked]

    def _resource_torrents(
        self,
        keyword: str,
        mtype: Any = None,
        progress_callback: Optional[Callable[..., None]] = None,
        target_media_source: Optional[str] = None,
        target_media_id: Optional[str] = None,
        target_media_title: Optional[str] = None,
        target_media_year: Optional[Any] = None,
    ) -> List[Any]:
        """把 CMS m3u8 条目投影为 MoviePilot 原生 TorrentInfo。"""
        torrent_info_type = _HostTorrentInfo or (
            getattr(_schemas, "TorrentInfo", None) if _schemas is not None else None
        )
        if torrent_info_type is None:
            return []
        configured_root = str(self._config.get("download_root") or "").strip()

        def build_torrent(**kwargs: Any) -> Any:
            item = torrent_info_type(**kwargs)
            item.site_downloader = "LunaTVSource"
            if configured_root:
                try:
                    item.download_path = configured_root
                except (AttributeError, ValueError):
                    # 旧版宿主未声明展示字段时，仍可使用 LunaTV 下载器。
                    pass
            return item

        requested_type = _enum_value(mtype)
        requested_media_type = (
            "tv"
            if requested_type in {"电视剧", "tv", "series", "show", "tvshow"}
            else "movie"
            if requested_type in {"电影", "movie", "film", "movies"}
            else ""
        )
        target_media_source_value = (
            _coerce_media_identity_source(target_media_source)
            if target_media_source is not None
            else None
        )
        target_media_id_value = (
            str(target_media_id).strip() if target_media_id is not None else None
        )
        target_media_title_value = (
            normalize_media_title(str(target_media_title).strip())
            if target_media_title is not None
            else ""
        )
        target_media_title_provided = bool(target_media_title_value)
        target_media_year_value = (
            str(target_media_year).strip() if target_media_year is not None else ""
        )
        use_target_tv_identity = (
            requested_media_type == "tv"
            and target_media_source_value is not None
            and target_media_id_value
        )
        cache_key = "|".join(
            (
                normalize_search_title(keyword).casefold(),
                requested_type,
                target_media_source_value or "",
                target_media_id_value or "",
                target_media_title_value,
                target_media_year_value,
            )
        )
        now = time.monotonic()
        with self._resource_search_lock:
            self._prune_resource_search_cache(now)
            cached = self._resource_search_cache.get(cache_key)
            # A progress callback requires a real source pass; cached results
            # cannot truthfully report per-source completion.
            if (
                progress_callback is None
                and cached
                and now - cached[0] < _RESOURCE_SEARCH_CACHE_TTL
            ):
                return list(cached[1])

        # 第三方 CMS、AI 与 TMDB 请求可能较慢，不能在请求期间占用缓存锁；
        # 否则插件更新/停用时会一直等待正在进行的原生资源搜索。
        search_query, _ = (self._ai or AiTitleNormalizer(False)).normalize(keyword)
        progress_state = {"finished": 0, "total": 0}

        def on_progress(*, finished: int, total: int, text: str) -> None:
            progress_state["finished"] = int(finished)
            progress_state["total"] = int(total)
            if progress_callback is None:
                return
            try:
                progress_callback(
                    finished=int(finished),
                    total=int(total),
                    text=(
                        text
                        if text.startswith("LunaTV ")
                        else f"LunaTV 正在搜索源 {int(finished)}/{int(total)}"
                    ),
                )
            except Exception:
                # Host progress handlers must never break CMS search.
                pass

        search_kwargs: Dict[str, Any] = {
            "limit": 50,
            "source_limit": 3,
            "stop_after_first_source": False,
            "require_playable": True,
            "expand_tv_episode_rows": True,
            "max_workers": 8,
        }
        if progress_callback is not None:
            search_kwargs["progress_callback"] = on_progress
        client = self._client()
        try:
            source_count = len(getattr(client, "sources", ()) or ())
        except TypeError:
            source_count = 0
        search_kwargs["limit"] = max(
            int(search_kwargs["limit"]),
            max(0, source_count) * int(search_kwargs["source_limit"]),
        )
        if requested_media_type:
            search_kwargs["media_type_filter"] = requested_media_type
        results = client.search(search_query, **search_kwargs)
        completed_sources = progress_state["finished"] or source_count
        total_sources = progress_state["total"] or source_count
        on_progress(
            finished=completed_sources,
            total=total_sources,
            text="LunaTV 正在汇总资源并检测清晰度",
        )
        if requested_media_type:
            results = [
                result for result in results if result.media_type == requested_media_type
            ]
        # The resource search is one user-selected native media context, not
        # one TMDB lookup per CMS source/result.  AI normalization and the
        # default TMDB association therefore run exactly once here; the same
        # host media identity is embedded in every returned download token.
        association: Dict[str, Any] = {}
        if results:
            context = self._resource_search_context(search_query, results, mtype)
            association = self._associate_tmdb(context, include_candidates=False)
        canonical_tv_title = ""
        canonical_tv_year = ""
        if requested_media_type == "tv":
            if use_target_tv_identity:
                canonical_tv_title = target_media_title_value
                canonical_tv_year = target_media_year_value
            elif association.get("status") == "matched":
                canonical_tv_title = normalize_media_title(
                    str(association.get("title") or "").strip()
                )
                canonical_tv_year = str(association.get("year") or "").strip()
        # TV resources are presented as one native download item per
        # source/season.  The enclosure carries the ordered episode list and
        # ``download`` expands it back into the plugin's serial queue.  This
        # matches how an Apple CMS result is published (for example,
        # “小猪佩奇 第一季 第52集”), while still keeping every source selectable.
        season_groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
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
            group_title = normalize_media_title(result.title)
            group_year = result.year
            if result.media_type == "tv":
                group_title = canonical_tv_title or group_title
                group_year = canonical_tv_year or group_year
            episodes = result.episodes or [CmsEpisode(1, 1, "正片", "")]
            season_episode_numbers: Dict[int, set[int]] = {}
            season_urls: Dict[int, set[str]] = {}
            for candidate in episodes:
                if not candidate.url or not candidate.season_known:
                    continue
                candidate_season = int(candidate.season or 1)
                season_episode_numbers.setdefault(candidate_season, set()).add(
                    int(candidate.episode or 1)
                )
                season_urls.setdefault(candidate_season, set()).add(candidate.url)
            for episode in episodes:
                if not episode.url:
                    continue
                payload = episode_payload(
                    result, episode, identity, host_media_source, host_media_id
                )
                if result.media_type == "tv" and not episode.season_known:
                    continue
                if result.media_type == "tv" and episode.season_known:
                    season = int(episode.season or 1)
                    season_variant: Tuple[Any, ...] = ()
                    if len(season_episode_numbers.get(season, set())) > 1:
                        season_variant = (
                            result.vod_id,
                            *tuple(sorted(season_urls.get(season, set()))),
                        )
                    group_key = (
                        result.source_key,
                        result.source_name,
                        normalize_media_title(result.title),
                        result.year,
                        season,
                        season_variant,
                    )
                    group = season_groups.setdefault(
                        group_key,
                        {
                            "site_name": result.source_name or "LunaTV",
                            "title": group_title,
                            "year": group_year,
                            "season": season,
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

        group_rows = list(season_groups.values())
        conflict_probe_urls: List[str] = []
        for group in group_rows:
            episode_candidates: Dict[int, List[Dict[str, Any]]] = {}
            for episode in group["episodes"]:
                episode_candidates.setdefault(int(episode["episode"]), []).append(episode)
            group["episode_candidates"] = episode_candidates
            sample_episode = min(episode_candidates, default=None)
            sample_candidates = (
                episode_candidates.get(sample_episode, [])
                if sample_episode is not None
                else []
            )
            if len(sample_candidates) > 1:
                conflict_probe_urls.extend(
                    candidate["url"] for candidate in sample_candidates
                )
        conflict_heights = self._probe_resource_urls(conflict_probe_urls)
        for group in group_rows:
            group["sorted_episodes"] = []
            for episode_number in sorted(group["episode_candidates"]):
                candidates = group["episode_candidates"][episode_number]
                _, selected = max(
                    enumerate(candidates),
                    key=lambda item: (
                        conflict_heights.get(item[1]["url"], 0),
                        -item[0],
                    ),
                )
                group["sorted_episodes"].append(selected)
        for row in single_rows:
            row["probe_url"] = row["payload"]["url"]

        season_probe_urls: List[str] = []
        for group in group_rows:
            # A season resource is ranked from one representative episode.
            # Probing every episode makes large seasons unnecessarily slow.
            first_episode = group["sorted_episodes"][0] if group["sorted_episodes"] else None
            if first_episode and first_episode["url"]:
                season_probe_urls.append(first_episode["url"])

        quality_heights = dict(conflict_heights)
        quality_heights.update(
            self._probe_resource_urls(
                [
                    url
                    for url in dict.fromkeys(season_probe_urls)
                    if url not in quality_heights
                ]
            )
        )
        quality_heights.update(
            self._probe_resource_urls(
                [
                    row["probe_url"]
                    for row in single_rows
                    if row["probe_url"] not in quality_heights
                ]
            )
        )

        for group in group_rows:
            sampled_episode = group["sorted_episodes"][0] if group["sorted_episodes"] else None
            sampled_url = sampled_episode["url"] if sampled_episode else ""
            sampled_height = quality_heights.get(sampled_url, 0) if sampled_url else 0
            probed_episodes: List[int] = []
            for episode in group["sorted_episodes"]:
                is_sampled_episode = episode is sampled_episode
                episode_height = sampled_height if is_sampled_episode else 0
                episode["resolution"] = stream_quality_label(episode_height)
                episode["resolution_height"] = episode_height
                if is_sampled_episode and episode_height > 0:
                    probed_episodes.append(int(episode["episode"]))
            group["resolution_height"] = sampled_height
            group["resolution_scope"] = "sample"
            group["resolution_probed_episode_count"] = len(probed_episodes)
            group["resolution_probed_episodes"] = probed_episodes

        torrents: List[Any] = []
        torrent_heights: Dict[int, int] = {}
        for group in group_rows:
            group_episodes = group["sorted_episodes"]
            season = int(group["season"])
            count = len(group_episodes)
            first = group_episodes[0]
            payload = dict(first)
            payload["episodes"] = group_episodes
            height = int(group["resolution_height"])
            quality = stream_quality_label(height)
            payload["resolution"] = quality
            payload["resolution_height"] = height
            payload["resolution_scope"] = group["resolution_scope"]
            payload["resolution_probed_episode_count"] = group[
                "resolution_probed_episode_count"
            ]
            payload["resolution_probed_episodes"] = group["resolution_probed_episodes"]
            title = group["title"]
            if (
                payload["media_type"] == "tv"
                and use_target_tv_identity
                and target_media_title_provided
            ):
                title = target_media_title_value
                if target_media_year_value:
                    title = f"{title} ({target_media_year_value})"
                elif group["year"]:
                    title = f"{title} ({group['year']})"
            elif group["year"]:
                title = f"{title} ({group['year']})"
            title = f"{title} · 第{season}季 · {quality}"
            first_height = int(first.get("resolution_height") or 0)
            latency_ms = self._probe_latency_ms(first["url"]) if first_height > 0 else 0
            site_name = group["site_name"]
            labels = ["LunaTV", "m3u8", f"第{season}季"]
            if latency_ms:
                site_name = f"{site_name} · {latency_ms}ms"
                labels.append(f"{latency_ms}ms")
            info_media_source = group["host_media_source"]
            info_media_id = group["host_media_id"]
            if payload["media_type"] == "tv" and use_target_tv_identity:
                info_media_source = target_media_source_value
                info_media_id = target_media_id_value
            item = build_torrent(
                site_name=site_name,
                title=title,
                description=(
                    f"LunaTV · 第{season}季 · {quality} · m3u8 · 共{count}集"
                ),
                media_source=info_media_source,
                media_id=info_media_id,
                enclosure=self._resource_token(payload),
                page_url=group["page_url"],
                size=0,
                seeders=1,
                uploadvolumefactor=1.0,
                downloadvolumefactor=1.0,
                pri_order=_resource_sort_priority(height),
                category="电视剧",
                labels=labels,
            )
            torrents.append(item)
            torrent_heights[id(item)] = height

        for row in single_rows:
            payload = row["payload"]
            if payload["media_type"] == "tv":
                continue
            height = quality_heights.get(row["probe_url"], 0)
            quality = stream_quality_label(height)
            payload["resolution"] = quality
            payload["resolution_height"] = height
            title = row["title"]
            if row["year"]:
                title = f"{title} ({row['year']})"
            if payload["media_type"] == "tv":
                title = f"{title} S{int(payload['season']):02d}E{int(payload['episode']):02d}"
            title = f"{title} · {quality}"
            latency_ms = self._probe_latency_ms(row["probe_url"]) if height > 0 else 0
            site_name = row["site_name"]
            labels = ["LunaTV", "m3u8"]
            if latency_ms:
                site_name = f"{site_name} · {latency_ms}ms"
                labels.append(f"{latency_ms}ms")
            torrents.append(build_torrent(
                site_name=site_name,
                title=title,
                description=f"LunaTV · {quality} · m3u8",
                media_source=payload["host_media_source"],
                media_id=payload["host_media_id"],
                enclosure=self._resource_token(payload),
                page_url=row["page_url"],
                size=0,
                seeders=1,
                uploadvolumefactor=1.0,
                downloadvolumefactor=1.0,
                pri_order=_resource_sort_priority(height),
                category="电视剧" if payload["media_type"] == "tv" else "电影",
                labels=labels,
            ))
            torrent_heights[id(torrents[-1])] = height
        # Keep exact height as the tie-breaker when three-digit priorities collide.
        on_progress(
            finished=completed_sources,
            total=total_sources,
            text="LunaTV 正在按清晰度排序",
        )
        torrents.sort(
            key=lambda item: (
                int(getattr(item, "pri_order", 0) or 0),
                torrent_heights.get(id(item), 0),
            ),
            reverse=True,
        )
        with self._resource_search_lock:
            self._resource_search_cache[cache_key] = (time.monotonic(), torrents)
            self._prune_resource_search_cache(time.monotonic())
        return list(torrents)

    def search_torrents(
        self,
        site: Dict[str, Any],
        keyword: str,
        mtype: Any = None,
        page: Optional[int] = 0,
        progress_callback: Optional[Callable[..., None]] = None,
        media_source: Optional[str] = None,
        media_id: Optional[str] = None,
        media_title: Optional[str] = None,
        media_year: Optional[Any] = None,
        **_: Any,
    ) -> List[Any]:
        """参与每次原生站点搜索；固定站点名使多站点调用结果可由宿主去重。"""
        del site
        if not self._enabled or int(page or 0) > 0 or not str(keyword or "").strip():
            return []
        try:
            if progress_callback is None:
                return self._resource_torrents(
                    str(keyword).strip(),
                    mtype=mtype,
                    target_media_source=media_source,
                    target_media_id=media_id,
                    target_media_title=media_title,
                    target_media_year=media_year,
                )
            return self._resource_torrents(
                str(keyword).strip(),
                mtype=mtype,
                progress_callback=progress_callback,
                target_media_source=media_source,
                target_media_id=media_id,
                target_media_title=media_title,
                target_media_year=media_year,
            )
        except Exception as exc:
            self._logger.warning("LunaTV 原生资源搜索失败：%s", exc)
            return []

    async def async_search_torrents(self, **kwargs: Any) -> List[Any]:
        if "progress_callback" not in kwargs:
            progress_callback = _SEARCH_PROGRESS_CALLBACK.get()
            if progress_callback is not None:
                kwargs["progress_callback"] = progress_callback
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
        del cookie, category, label, downloader
        payload = self._decode_resource_token(content)
        if payload is None:
            return None
        queue = self._queue
        configured_root = str(self._config.get("download_root") or "").strip()
        root = configured_root or str(download_dir or "").strip()
        if queue is None or not root:
            return "LunaTVSource", None, None, "LunaTV 下载参数无效"
        raw_episodes = episodes if isinstance(episodes, list) else payload.get("episodes")
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
        self._start_queue()
        total = len(enqueued_ids)
        message = f"已排队 {total} 集" if total > 1 or duplicate_count or invalid_count else ""
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
