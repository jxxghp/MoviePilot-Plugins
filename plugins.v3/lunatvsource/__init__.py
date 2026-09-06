"""MoviePilot V3 plugin for MoonTV/LunaTV Apple CMS sources.

The first implementation deliberately keeps the source adapter independent from
MoviePilot internals.  The host integration is optional at import time so the
pure search, naming and queue code can be tested outside a running MoviePilot.
"""

from __future__ import annotations

try:
    import fcntl
except ImportError:  # pragma: no cover - MoviePilot production runs on Linux.
    fcntl = None  # type: ignore[assignment]

import json
import base64
import hashlib
import inspect
import logging
import sys
import asyncio
import weakref
from collections import deque
from contextvars import ContextVar
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

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
    from app.sdk.services import MediaServerHelper as _HostMediaServerHelper
except Exception:
    try:  # pragma: no cover - compatibility with early V3 runtimes
        from app.application.mediaserver import (
            MediaServerHelper as _HostMediaServerHelper,
        )
    except Exception:
        _HostMediaServerHelper = None

try:  # pragma: no cover - exercised in a MoviePilot runtime
    from app.chain.subscribe import SubscribeChain as _HostSubscribeChain
except Exception:
    _HostSubscribeChain = None

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
    from apscheduler.triggers.interval import IntervalTrigger
except Exception:  # pragma: no cover - standalone tests
    CronTrigger = None  # type: ignore[assignment,misc]
    IntervalTrigger = None  # type: ignore[assignment,misc]

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
from .downloader import (
    DEFAULT_HLS_AD_FILTER_REGEX,
    DEFAULT_MAX_CONCURRENT_TASKS,
    DEFAULT_SEGMENT_THREAD_COUNT,
    MAX_MAX_CONCURRENT_TASKS,
    MAX_SEGMENT_THREAD_COUNT,
    MAX_TOTAL_SEGMENT_THREADS,
    MIN_MAX_CONCURRENT_TASKS,
    MIN_SEGMENT_THREAD_COUNT,
    DownloadQueue,
    DownloadTask,
    normalize_download_concurrency,
)
from .naming import (
    extension_for_url,
    media_path,
    normalize_media_title,
    normalize_search_title,
)

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
FRONTEND_REMOTE_ENTRY = (
    Path(__file__).resolve().parent / "dist" / "assets" / "remoteEntry.js"
)
FALLBACK_CONFIG_PATH = Path(__file__).with_name("fallback_sources.json")
SOURCE_CACHE_KEY = "luna_source_config_v1"
SOURCE_HEALTH_KEY = "luna_source_health_v1"
SOURCE_HEALTH_META_KEY = "luna_source_health_meta_v1"
FOLLOWUP_STATUS_KEY = "luna_followup_status_v1"
DEFAULT_SOURCE_CHECK_MINUTES = 60
MIN_SOURCE_CHECK_MINUTES = 15
MAX_SOURCE_CHECK_MINUTES = 1440
SOURCE_HEALTH_QUERY = "1"
SOURCE_HEALTH_WORKERS = 8
DEFAULT_SOURCE_ALLOWLIST = (
    "suonizy.net,suoniapi.com,kuaichezy.com,caiji.kuaichezy.org,"
    "www.hongniuzy.com,www.hongniuzy2.com,wujinzy.net,wujinzy.me,"
    "api.wujinapi.me,wujinapi.me,guangsuzy.com,api.guangsuapi.com,"
    "ukuzy0.com,api.ukuapi88.com,www.xinlangzy.com,xinlangapi.com,okzyw.cc"
)
PLUGIN_MEDIA_SOURCE = "lunatv"
_AUTO_LIBRARY_DIR_NAMES: Dict[str, Tuple[str, ...]] = {
    "movie": ("movies", "movie", "电影"),
    "tv": ("tv", "tvshows", "tv-shows", "shows", "series", "电视剧"),
}
_AUTO_TRANSFER_TYPE = "move"
_TMDB_CACHE_MAX_ENTRIES = 512
_QUALITY_CACHE_MAX_ENTRIES = 512
_RESOURCE_SEARCH_CACHE_MAX_ENTRIES = 128
_RESOURCE_SEARCH_CACHE_TTL = 30.0
_QUEUE_RELOAD_STOP_TIMEOUT_SECONDS = 2.0
_QUEUE_LOCK_FILENAME = ".lunatv-download-queue.lock"
_QUEUE_OWNER_REGISTRY = sys.__dict__.setdefault(
    "_lunatvsource_queue_owners",
    weakref.WeakValueDictionary(),
)
_QUEUE_OWNER_REGISTRY_LOCK = sys.__dict__.setdefault(
    "_lunatvsource_queue_owner_lock",
    threading.RLock(),
)
_MEDIA_SYNC_RETRY_LIMIT = 1
_MEDIA_SYNC_RETRY_DELAY_SECONDS = 2.0
_SUBSCRIPTION_PROGRESS_EVENT_SCENE = "lunatvsource_media_sync"
_SUBSCRIPTION_PASSIVE_EVENT_SCENES = frozenset(
    {
        _SUBSCRIPTION_PROGRESS_EVENT_SCENE,
        "backfill",
        "download",
        "download_note",
        "episode_refresh",
        "movie_download",
        "precheck",
        "progress",
        "search_reset",
    }
)
_MEDIA_SYNC_VISIBILITY_TIMEOUT_SECONDS = 60.0
_MEDIA_SYNC_VISIBILITY_POLL_SECONDS = 1.0


def _resource_sort_priority(height: int) -> int:
    """Keep resolution order inside MoviePilot's three-digit sort slot."""
    return min(999, max(0, int(height or 0) // 10))


def _tv_resource_sort_priority(season: int, height: int) -> int:
    """Sort numbered seasons ascending, then quality descending."""
    season_order = 1000 - min(999, max(0, int(season or 0)))
    return season_order * 1000 + _resource_sort_priority(height)


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
_DOWNLOAD_CLIENTS_BRIDGE: Dict[str, Any] = {
    "owner": None,
    "module": None,
    "original": None,
    "wrapper": None,
}
_DOWNLOAD_CHAIN_BRIDGE: Dict[str, Any] = {
    "owner": None,
    "chain": None,
    "original": None,
    "wrapper": None,
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


def _is_downloaders_config_key(key: Any) -> bool:
    """兼容 SystemConfigKey 枚举和值字符串，避免绑定宿主的具体枚举实现。"""
    return (
        getattr(key, "name", None) == "Downloaders"
        or _enum_value(key) == "downloaders"
        or str(key).rsplit(".", 1)[-1] == "Downloaders"
    )


class _DownloadersConfigProxy:
    """只为下载器读取投影插件客户端，其余配置保持由宿主对象负责。"""

    def __init__(self, config: Any) -> None:
        object.__setattr__(self, "_config", config)

    def get(self, key: Any, default: Any = None) -> Any:
        # MoviePilot v3 的 SystemConfigService.get() 仅接受 key；这里不能按
        # dict.get(key, default) 调用，否则 /download/clients 会直接返回 500。
        value = self._config.get(key)
        if value is None and default is not None:
            value = default
        if not _is_downloaders_config_key(key):
            return value
        clients: List[Dict[str, Any]] = []
        found = False
        for client in value if isinstance(value, (list, tuple)) else []:
            if not isinstance(client, dict):
                continue
            projected = dict(client)
            if str(projected.get("name") or "").strip().casefold() == "lunatvsource":
                # /download/clients 会再次过滤 enabled；同名旧配置不能遮蔽插件投影。
                projected.update(
                    {"name": "LunaTVSource", "type": "plugin", "enabled": True}
                )
                found = True
            clients.append(projected)
        if not found:
            clients.append({"name": "LunaTVSource", "type": "plugin", "enabled": True})
        return clients

    def __getattr__(self, name: str) -> Any:
        return getattr(self._config, name)

    def __getitem__(self, key: Any) -> Any:
        return self._config[key]


def _install_download_clients_bridge(owner: "LunaTVSource") -> None:
    """在内存中给下载页补充插件客户端，不写入 SystemConfig。"""
    try:
        from app.api.endpoints import download as download_endpoint
    except Exception as exc:  # pragma: no cover - MoviePilot runtime only
        owner._logger.warning("LunaTV 下载器兼容桥不可用：%s", exc)
        return

    current = getattr(download_endpoint, "get_configured_system_config", None)
    bridge_module = _DOWNLOAD_CLIENTS_BRIDGE.get("module")
    wrapper = _DOWNLOAD_CLIENTS_BRIDGE.get("wrapper")
    if bridge_module is download_endpoint and wrapper is current:
        _DOWNLOAD_CLIENTS_BRIDGE["owner"] = owner
        return
    if bridge_module is not None:
        _restore_download_clients_bridge(owner, force=True)

    current = getattr(download_endpoint, "get_configured_system_config", None)
    original = current
    seen: set[int] = set()
    while getattr(original, "_lunatv_download_clients_bridge", False):
        if id(original) in seen:
            owner._logger.warning("LunaTV 下载器兼容桥不可用：检测到 wrapper 循环")
            return
        seen.add(id(original))
        original = getattr(original, "_lunatv_download_clients_original", None)
    if not callable(original):
        owner._logger.warning("LunaTV 下载器兼容桥不可用：未找到宿主配置读取函数")
        return

    @wraps(original)
    def config_wrapper(*args: Any, **kwargs: Any) -> Any:
        # 下载页只经此函数读取 Downloaders；代理让插件显示为内存客户端，
        # 避免把运行时兼容状态写回用户的 SystemConfig。
        config = original(*args, **kwargs)
        active_owner = _DOWNLOAD_CLIENTS_BRIDGE.get("owner")
        if not active_owner or not getattr(active_owner, "_enabled", False):
            return config
        return _DownloadersConfigProxy(config)

    setattr(config_wrapper, "_lunatv_download_clients_bridge", True)
    setattr(config_wrapper, "_lunatv_download_clients_original", original)

    setattr(download_endpoint, "get_configured_system_config", config_wrapper)
    _DOWNLOAD_CLIENTS_BRIDGE.update(
        {
            "owner": owner,
            "module": download_endpoint,
            "original": original,
            "wrapper": config_wrapper,
        }
    )
    owner._logger.info("LunaTV 已启用下载器客户端兼容桥")


def _restore_download_clients_bridge(owner: "LunaTVSource", force: bool = False) -> None:
    """仅撤销仍由本插件持有的 wrapper，避免覆盖热更新后的宿主实现。"""
    if not force and _DOWNLOAD_CLIENTS_BRIDGE.get("owner") is not owner:
        return
    module = _DOWNLOAD_CLIENTS_BRIDGE.get("module")
    original = _DOWNLOAD_CLIENTS_BRIDGE.get("original")
    wrapper = _DOWNLOAD_CLIENTS_BRIDGE.get("wrapper")
    if module is not None and getattr(module, "get_configured_system_config", None) is wrapper:
        setattr(module, "get_configured_system_config", original)
    _DOWNLOAD_CLIENTS_BRIDGE.update(
        {"owner": None, "module": None, "original": None, "wrapper": None}
    )


def _download_chain_bridge_owner() -> Optional["LunaTVSource"]:
    owner = _DOWNLOAD_CHAIN_BRIDGE.get("owner")
    return owner if owner and getattr(owner, "_enabled", False) else None


def _install_download_chain_bridge(owner: "LunaTVSource") -> None:
    """让 MoviePilot 原生下载接口把 LunaTV 令牌交给插件队列。"""
    try:
        from app.chain.download import DownloadChain
    except Exception as exc:  # pragma: no cover - MoviePilot runtime only
        owner._logger.warning("LunaTV 原生下载桥接不可用：%s", exc)
        return

    current = getattr(DownloadChain, "download_single", None)
    bridge_chain = _DOWNLOAD_CHAIN_BRIDGE.get("chain")
    wrapper = _DOWNLOAD_CHAIN_BRIDGE.get("wrapper")
    if bridge_chain is DownloadChain and wrapper is current:
        _DOWNLOAD_CHAIN_BRIDGE["owner"] = owner
        return
    if bridge_chain is not None:
        _restore_download_chain_bridge(owner, force=True)

    original = current
    seen: set[int] = set()
    while getattr(original, "_lunatv_download_chain_bridge", False):
        if id(original) in seen:
            owner._logger.warning("LunaTV 原生下载桥接不可用：检测到 wrapper 循环")
            return
        seen.add(id(original))
        original = getattr(original, "_lunatv_download_chain_original", None)
    if not callable(original):
        owner._logger.warning("LunaTV 原生下载桥接不可用：未找到 download_single")
        return

    @wraps(original)
    def download_single_wrapper(chain: Any, *args: Any, **kwargs: Any) -> Any:
        active_owner = _download_chain_bridge_owner()
        if active_owner is None:
            return original(chain, *args, **kwargs)

        return_detail = bool(
            kwargs.get(
                "return_detail",
                args[11] if len(args) > 11 else False,
            )
        )

        def bridge_result(task_id: Optional[str], error: Optional[str] = None) -> Any:
            return (task_id, error) if return_detail else task_id

        context = kwargs.get("context")
        if context is None and args:
            context = args[0]
        torrent = getattr(context, "torrent_info", None)
        content = getattr(torrent, "enclosure", None)
        payload = active_owner._decode_resource_token(content)
        if payload is None:
            return original(chain, *args, **kwargs)

        requested_root = kwargs.get("save_path")
        if requested_root is None and len(args) > 7:
            requested_root = args[7]
        configured_root = str(
            active_owner._config.get("download_root") or ""
        ).strip()
        configured_root = (
            configured_root
            or str(requested_root or "").strip()
            or active_owner._effective_root(
                media_type=_media_type_value(payload.get("media_type"))
            )
        )
        if not configured_root:
            active_owner._logger.warning("LunaTV 原生下载未接管：未配置下载目录")
            return original(chain, *args, **kwargs)

        try:
            result = active_owner.download(
                content,
                Path(configured_root),
                downloader="LunaTVSource",
            )
        except Exception as exc:
            active_owner._logger.error("LunaTV 原生下载入队失败：%s", exc)
            return bridge_result(None, f"LunaTV 下载入队失败：{exc}")

        if not result:
            active_owner._logger.warning("LunaTV 原生下载入队失败：未返回任务")
            return bridge_result(None, "LunaTV 下载任务未入队")
        downloader, task_id, _, message = result
        if not task_id:
            active_owner._logger.warning(
                "LunaTV 原生下载未生成任务：%s", message or "未知原因"
            )
            return bridge_result(None, message or "LunaTV 下载任务未入队")

        if torrent is not None:
            try:
                torrent.site_downloader = downloader or "LunaTVSource"
                torrent.download_path = configured_root
            except (AttributeError, TypeError):
                pass
        active_owner._logger.info(
            "LunaTV 原生下载已入队：%s (%s)",
            task_id,
            message or "已加入下载队列",
        )
        return bridge_result(task_id)

    setattr(download_single_wrapper, "_lunatv_download_chain_bridge", True)
    setattr(download_single_wrapper, "_lunatv_download_chain_original", original)
    setattr(DownloadChain, "download_single", download_single_wrapper)
    _DOWNLOAD_CHAIN_BRIDGE.update(
        {
            "owner": owner,
            "chain": DownloadChain,
            "original": original,
            "wrapper": download_single_wrapper,
        }
    )
    owner._logger.info("LunaTV 已启用 MoviePilot 原生下载兼容桥")


def _restore_download_chain_bridge(owner: "LunaTVSource", force: bool = False) -> None:
    """仅撤销仍由本插件持有的下载链 wrapper。"""
    if not force and _DOWNLOAD_CHAIN_BRIDGE.get("owner") is not owner:
        return
    chain = _DOWNLOAD_CHAIN_BRIDGE.get("chain")
    original = _DOWNLOAD_CHAIN_BRIDGE.get("original")
    wrapper = _DOWNLOAD_CHAIN_BRIDGE.get("wrapper")
    if chain is not None and getattr(chain, "download_single", None) is wrapper:
        setattr(chain, "download_single", original)
    _DOWNLOAD_CHAIN_BRIDGE.update(
        {"owner": None, "chain": None, "original": None, "wrapper": None}
    )


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


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Coerce persisted plugin configuration without trusting old UI values."""
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


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
    plugin_version = "0.4.81"
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
    _media_server_sync_lock = threading.Lock()
    _tmdb_cache_lock = threading.RLock()
    _tmdb_cache: Dict[str, Dict[str, Any]] = {}
    _resource_search_lock = threading.RLock()
    _resource_search_cache: Dict[str, Tuple[float, List[Any]]] = {}
    _source_config_origin = "未加载"
    _source_config_error = ""

    def __init__(self) -> None:
        super().__init__()
        self._logger = LOGGER
        self._queue_lock_file: Optional[Any] = None
        self._queue_lock_path: Optional[Path] = None
        self._queue_lock_error = ""
        self._download_metrics_lock = threading.Lock()
        self._download_metrics: Dict[str, Deque[Tuple[float, int]]] = {}
        self._completed_download_sizes: Dict[str, int] = {}
        self._media_sync_lock = threading.Lock()
        self._media_sync_running = False
        self._media_sync_requested = False
        self._media_sync_refresh_ids: set[int] = set()
        self._media_sync_backfill: Dict[int, set[int]] = {}
        self._media_sync_probes: Dict[
            Tuple[str, str, str, int, int], Dict[str, Any]
        ] = {}
        self._media_sync_generation = 0
        self._media_sync_stop = threading.Event()
        self._media_sync_thread: Optional[threading.Thread] = None
        self._followup_status_lock = threading.Lock()
        self._followup_status: Dict[str, Dict[str, Any]] = {}
        self._followup_generations = {
            "subscription_refresh": 0,
            "media_server_sync": 0,
        }
        self._subscription_refresh_active: set[int] = set()
        # ponytail: completion volume is low; one lock avoids stale subscription
        # snapshots overwriting each other. Split per subscription only if measured.
        self._subscription_progress_lock = threading.Lock()
        self._quality_cache_lock = threading.Lock()
        self._quality_cache: Dict[str, Tuple[float, int]] = {}
        self._quality_probe_ms: Dict[str, int] = {}
        self._source_health_lock = threading.RLock()
        self._source_health_running = False
        self._source_health: Dict[str, Dict[str, Any]] = {}
        self._source_health_stop = threading.Event()
        self._source_health_thread: Optional[threading.Thread] = None
        self._source_health_pending_keys: set[str] = set()
        self._source_health_pending_full = False
        self._source_health_run_keys: set[str] = set()
        self._source_health_completed_keys: set[str] = set()
        self._source_health_last_error = ""
        self._source_health_last_finished = 0.0
        self._source_health_revision = 0

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

    def _acquire_queue_lock(self, data_path: Optional[Path]) -> bool:
        """Keep one download queue owner per persistent plugin data path."""
        self._queue_lock_error = ""
        if data_path is None or fcntl is None:
            return True
        try:
            data_path.mkdir(parents=True, exist_ok=True)
            lock_path = data_path.resolve() / _QUEUE_LOCK_FILENAME
        except OSError as exc:
            self._queue_lock_error = f"无法准备下载队列锁：{exc}"
            self._logger.warning("无法准备 LunaTV 下载队列锁：%s", exc)
            return False
        lock_key = str(lock_path)
        with _QUEUE_OWNER_REGISTRY_LOCK:
            owner = _QUEUE_OWNER_REGISTRY.get(lock_key)
        if owner is not None and owner is not self:
            try:
                owner.stop_service()
            except Exception as exc:
                self._queue_lock_error = f"停止同进程旧实例失败：{exc}"
                self._logger.warning("停止旧 LunaTV 实例失败：%s", exc)
                return False
            if getattr(owner, "_queue_lock_file", None) is not None:
                self._queue_lock_error = (
                    "下载队列锁定失败：其他实例占用；"
                    "同进程旧实例停止后仍未释放下载队列锁"
                )
                self._logger.warning("旧 LunaTV 实例未释放下载队列锁：%s", lock_path)
                return False
        if self._queue_lock_file is not None:
            if self._queue_lock_path == lock_path:
                with _QUEUE_OWNER_REGISTRY_LOCK:
                    _QUEUE_OWNER_REGISTRY[lock_key] = self
                return True
            self._release_queue_lock()
        lock_file: Any = None
        try:
            lock_file = lock_path.open("a+b")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            self._queue_lock_error = (
                f"下载队列锁定失败（errno={getattr(exc, 'errno', None)}）：{exc}"
            )
            self._logger.warning(
                "LunaTV 下载队列数据目录已被其他实例占用或无法锁定：%s",
                exc,
            )
            return False
        self._queue_lock_file = lock_file
        self._queue_lock_path = lock_path
        with _QUEUE_OWNER_REGISTRY_LOCK:
            _QUEUE_OWNER_REGISTRY[lock_key] = self
        return True

    def _release_queue_lock(self) -> None:
        lock_file = self._queue_lock_file
        lock_path = self._queue_lock_path
        self._queue_lock_file = None
        self._queue_lock_path = None
        if lock_file is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                lock_file.close()
            except OSError:
                pass
        if lock_path is not None:
            with _QUEUE_OWNER_REGISTRY_LOCK:
                if _QUEUE_OWNER_REGISTRY.get(str(lock_path)) is self:
                    _QUEUE_OWNER_REGISTRY.pop(str(lock_path), None)

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        previous_queue = self._queue
        if previous_queue is not None:
            try:
                stopped = previous_queue.stop_and_wait(
                    timeout=_QUEUE_RELOAD_STOP_TIMEOUT_SECONDS
                )
            except Exception as exc:
                self._logger.warning("停止旧 LunaTV 下载队列失败，保留当前实例：%s", exc)
                return
            if not stopped:
                self._logger.warning(
                    "旧 LunaTV 下载队列未在 %.1f 秒内退出，保留当前实例以避免重复下载",
                    _QUEUE_RELOAD_STOP_TIMEOUT_SECONDS,
                )
                return
        self._cancel_media_sync()
        with self._source_health_lock:
            self._source_health_stop.set()
            self._source_health_stop = threading.Event()
            self._source_health_running = False
            self._source_health_thread = None
            self._source_health_pending_keys.clear()
            self._source_health_pending_full = False
            self._source_health_run_keys.clear()
            self._source_health_completed_keys.clear()
        self._config = dict(config or {})
        loaded_followup_status = self.get_data(FOLLOWUP_STATUS_KEY) or {}
        with self._followup_status_lock:
            self._followup_status = {
                name: dict(value)
                for name, value in loaded_followup_status.items()
                if name in {"subscription_refresh", "media_server_sync"}
                and isinstance(value, dict)
            } if isinstance(loaded_followup_status, dict) else {}
            for name in self._followup_generations:
                self._followup_generations[name] += 1
            self._subscription_refresh_active.clear()
        max_concurrent_tasks, segment_thread_count = normalize_download_concurrency(
            self._config.get(
                "max_concurrent_tasks",
                DEFAULT_MAX_CONCURRENT_TASKS,
            ),
            self._config.get(
                "segment_thread_count",
                DEFAULT_SEGMENT_THREAD_COUNT,
            ),
        )
        self._config["max_concurrent_tasks"] = max_concurrent_tasks
        self._config["segment_thread_count"] = segment_thread_count
        if "hls_ad_filter_regex" not in self._config:
            self._config["hls_ad_filter_regex"] = DEFAULT_HLS_AD_FILTER_REGEX
        else:
            self._config["hls_ad_filter_regex"] = str(
                self._config.get("hls_ad_filter_regex") or ""
            ).strip()
        try:
            source_check_minutes = int(
                self._config.get("source_check_minutes")
                or DEFAULT_SOURCE_CHECK_MINUTES
            )
        except (TypeError, ValueError):
            source_check_minutes = DEFAULT_SOURCE_CHECK_MINUTES
        self._config["source_check_minutes"] = max(
            MIN_SOURCE_CHECK_MINUTES,
            min(MAX_SOURCE_CHECK_MINUTES, source_check_minutes),
        )
        self._enabled = _bool(self._config.get("enabled"), False)
        self._source_config_origin = "未加载"
        self._source_config_error = ""
        # 智能助手始终读取 MoviePilot 全局配置；没有配置时由 AiTitleNormalizer 自动回退。
        # 保留旧版 ai_enabled 仅为兼容历史配置，不再让插件设置覆盖宿主设置。
        self._ai = AiTitleNormalizer(True, LOGGER)
        queue_data_path = self._queue_data_path()
        if False and not self._enabled:
            if self._acquire_queue_lock(queue_data_path):
                try:
                    DownloadQueue(
                        load=lambda key, default=None: (
                            default
                            if (value := self.get_data(key)) is None
                            else value
                        ),
                        save=lambda key, value: self.save_data(key, value),
                        notify=self._notify,
                        on_complete=self._record_completion,
                        data_path=queue_data_path,
                        max_concurrent_tasks=self._config[
                            "max_concurrent_tasks"
                        ],
                        segment_thread_count=self._config[
                            "segment_thread_count"
                        ],
                        allowed_private_ranges=self._probe_allowed_private_ranges(),
                        ad_filter_regex=self._config["hls_ad_filter_regex"],
                    )
                finally:
                    self._release_queue_lock()
            self._queue = None
        elif not self._acquire_queue_lock(queue_data_path):
            self._queue = None
            self._enabled = False
            self._source_config_error = self._queue_lock_error or "下载队列锁定失败"
            _restore_search_bridge(self)
            _restore_download_clients_bridge(self)
            _restore_download_chain_bridge(self)
            return
        else:
            try:
                self._queue = DownloadQueue(
                    load=lambda key, default=None: (
                        default
                        if (value := self.get_data(key)) is None
                        else value
                    ),
                    save=lambda key, value: self.save_data(key, value),
                    notify=self._notify,
                    on_complete=self._record_completion,
                    data_path=queue_data_path,
                    max_concurrent_tasks=self._config["max_concurrent_tasks"],
                    segment_thread_count=self._config["segment_thread_count"],
                    allowed_private_ranges=self._probe_allowed_private_ranges(),
                    ad_filter_regex=self._config["hls_ad_filter_regex"],
                )
            except Exception:
                self._queue = None
                self._release_queue_lock()
                raise
        with self._tmdb_cache_lock:
            loaded_tmdb_cache = dict(self.get_data("tmdb_match_cache_v1") or {})
            self._tmdb_cache = dict(
                list(loaded_tmdb_cache.items())[-_TMDB_CACHE_MAX_ENTRIES:]
            )
        with self._resource_search_lock:
            self._resource_search_cache = {}
        with self._source_health_lock:
            loaded_source_health = self.get_data(SOURCE_HEALTH_KEY) or {}
            if isinstance(loaded_source_health, dict):
                self._source_health = {
                    str(key).strip().lower(): dict(value)
                    for key, value in loaded_source_health.items()
                    if str(key).strip() and isinstance(value, dict)
                }
            else:
                self._source_health = {}
            loaded_source_health_meta = self.get_data(SOURCE_HEALTH_META_KEY) or {}
            if isinstance(loaded_source_health_meta, dict):
                self._source_health_last_error = str(
                    loaded_source_health_meta.get("last_error") or ""
                )
                try:
                    self._source_health_last_finished = float(
                        loaded_source_health_meta.get("last_finished") or 0
                    )
                except (TypeError, ValueError):
                    self._source_health_last_finished = 0.0
            else:
                self._source_health_last_error = ""
                self._source_health_last_finished = 0.0
            self._source_health_revision += 1
        if self._enabled:
            _install_search_bridge(self)
            _install_download_clients_bridge(self)
            _install_download_chain_bridge(self)
            if _HostMediaSource is not None and self._source_health_due():
                self._start_source_health_refresh()
        else:
            # A disabled replacement instance must also remove a bridge owned
            # by the previously loaded instance.
            _restore_search_bridge(self, force=True)
            _restore_download_clients_bridge(self, force=True)
            _restore_download_chain_bridge(self, force=True)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """仅在安装目录存在联邦入口时启用 Vue 工作台。"""
        if FRONTEND_REMOTE_ENTRY.is_file():
            return "vue", "dist/assets"
        return "vuetify", None

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
                            f"已启用，下载目录：{root}。任务按设置并发执行，完成后可刷新 Emby。"
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
            {"path": "/sources/refresh", "endpoint": self.api_source_refresh, "methods": ["POST"], "auth": "bear"},
            {"path": "/sources/state", "endpoint": self.api_source_state, "methods": ["POST"], "auth": "bear"},
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
                            "model": "source_check_minutes",
                            "label": "来源健康检查间隔（分钟）",
                            "type": "number",
                            "min": MIN_SOURCE_CHECK_MINUTES,
                            "max": MAX_SOURCE_CHECK_MINUTES,
                            "step": 1,
                            "hint": (
                                f"范围 {MIN_SOURCE_CHECK_MINUTES}–{MAX_SOURCE_CHECK_MINUTES}，"
                                f"默认 {DEFAULT_SOURCE_CHECK_MINUTES}；打开插件页仅读取缓存。"
                            ),
                            "persistentHint": True,
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
                            "label": "可信网络 CIDR（可选）",
                            "placeholder": "10.0.0.0/8,192.168.0.0/16",
                            "hint": "默认拒绝私网配置、CMS 和媒体地址；Fake-IP 或可信内网环境才填写 CIDR。",
                        "persistentHint": True,
                    },
                },
                {
                    "component": "VTextField",
                    "props": {
                        "model": "hls_ad_filter_regex",
                        "label": "HLS 广告分片 URL 正则（可选）",
                        "placeholder": DEFAULT_HLS_AD_FILTER_REGEX,
                        "hint": "匹配到的分片由 N_m3u8DL-RE 跳过；留空仅按闭合 CUE-OUT/CUE-IN 去除。",
                        "persistentHint": True,
                    },
                },
                    {
                        "component": "VSelect",
                        "props": {
                            "model": "mode",
                            "label": "处理方式",
                            "hint": "只有“下载到本地并整理”会执行 HLS 广告分片过滤；STRM 是原始直链，不去广告。",
                            "persistentHint": True,
                            "items": [
                                {"title": "下载到本地并整理（去广告）", "value": "download"},
                                {"title": "生成 STRM（原始直链，不去广告）", "value": "strm"},
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
                        "component": "VTextField",
                        "props": {
                            "model": "max_concurrent_tasks",
                            "label": "同时下载任务数",
                            "type": "number",
                            "min": MIN_MAX_CONCURRENT_TASKS,
                            "max": MAX_MAX_CONCURRENT_TASKS,
                            "step": 1,
                            "hint": (
                                f"范围 {MIN_MAX_CONCURRENT_TASKS}–{MAX_MAX_CONCURRENT_TASKS}，"
                                f"默认 {DEFAULT_MAX_CONCURRENT_TASKS}。"
                            ),
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "segment_thread_count",
                            "label": "单任务分片线程数",
                            "type": "number",
                            "min": MIN_SEGMENT_THREAD_COUNT,
                            "max": MAX_SEGMENT_THREAD_COUNT,
                            "step": 1,
                            "hint": (
                                f"范围 {MIN_SEGMENT_THREAD_COUNT}–{MAX_SEGMENT_THREAD_COUNT}，"
                                f"默认 {DEFAULT_SEGMENT_THREAD_COUNT}；总分片并发不超过 "
                                f"{MAX_TOTAL_SEGMENT_THREADS}。"
                            ),
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
                            "text": "订阅任务按设置并发执行；目录、智能助手、TMDB、整理链和媒体库均复用 MoviePilot 设置。目录内没有正在下载的缓存文件后，媒体库才会显示完整文件夹。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "config_url": DEFAULT_CONFIG_URL,
            "source_allowlist": "",
            "probe_allowed_private_ranges": "",
            "hls_ad_filter_regex": DEFAULT_HLS_AD_FILTER_REGEX,
            "mode": "download",
            "source_strategy": "first",
            "download_root": "",
            "use_moviepilot_dirs": True,
            "ffmpeg_path": "ffmpeg",
            "request_timeout": 15,
            "poll_minutes": 30,
            "source_check_minutes": DEFAULT_SOURCE_CHECK_MINUTES,
            "queue_minutes": 1,
            "max_concurrent_tasks": DEFAULT_MAX_CONCURRENT_TASKS,
            "segment_thread_count": DEFAULT_SEGMENT_THREAD_COUNT,
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
                        "component": "VSwitch",
                        "props": {
                            "model": "generate_nfo",
                            "label": "生成 NFO 元数据",
                            "hint": "开启后，下载完成并由 MoviePilot 原生整理时生成 NFO。",
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
                            "model": "source_check_minutes",
                            "label": "来源健康检查间隔（分钟）",
                            "type": "number",
                            "min": MIN_SOURCE_CHECK_MINUTES,
                            "max": MAX_SOURCE_CHECK_MINUTES,
                            "step": 1,
                            "hint": (
                                f"范围 {MIN_SOURCE_CHECK_MINUTES}–{MAX_SOURCE_CHECK_MINUTES}，"
                                f"默认 {DEFAULT_SOURCE_CHECK_MINUTES}；打开插件页仅读取缓存。"
                            ),
                            "persistentHint": True,
                        },
                    },
                {
                    "component": "VTextField",
                    "props": {
                        "model": "probe_allowed_private_ranges",
                            "label": "可信网络 CIDR（可选）",
                            "placeholder": "10.0.0.0/8,192.168.0.0/16",
                            "hint": "默认拒绝私网配置、CMS 和媒体地址；Fake-IP 或可信内网环境才填写 CIDR。",
                        "persistentHint": True,
                    },
                },
                {
                    "component": "VTextField",
                    "props": {
                        "model": "hls_ad_filter_regex",
                        "label": "HLS 广告分片 URL 正则（可选）",
                        "placeholder": DEFAULT_HLS_AD_FILTER_REGEX,
                        "hint": "匹配到的分片由 N_m3u8DL-RE 跳过；留空仅按闭合 CUE-OUT/CUE-IN 去除。",
                        "persistentHint": True,
                    },
                },
                {
                    "component": "VSelect",
                    "props": {
                        "model": "mode",
                        "label": "处理方式",
                        "hint": "只有“下载到本地并整理”会执行 HLS 广告分片过滤；STRM 是原始直链，不去广告。",
                        "persistentHint": True,
                        "items": [
                            {"title": "下载到本地并整理（去广告）", "value": "download"},
                            {"title": "生成 STRM（原始直链，不去广告）", "value": "strm"},
                        ],
                    },
                },
                {
                    "component": "VTextField",
                        "props": {
                            "model": "max_concurrent_tasks",
                            "label": "同时下载任务数",
                            "type": "number",
                            "min": MIN_MAX_CONCURRENT_TASKS,
                            "max": MAX_MAX_CONCURRENT_TASKS,
                            "step": 1,
                            "hint": (
                                f"范围 {MIN_MAX_CONCURRENT_TASKS}–{MAX_MAX_CONCURRENT_TASKS}，"
                                f"默认 {DEFAULT_MAX_CONCURRENT_TASKS}。"
                            ),
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "segment_thread_count",
                            "label": "单任务分片线程数",
                            "type": "number",
                            "min": MIN_SEGMENT_THREAD_COUNT,
                            "max": MAX_SEGMENT_THREAD_COUNT,
                            "step": 1,
                            "hint": (
                                f"范围 {MIN_SEGMENT_THREAD_COUNT}–{MAX_SEGMENT_THREAD_COUNT}，"
                                f"默认 {DEFAULT_SEGMENT_THREAD_COUNT}；总分片并发不超过 "
                                f"{MAX_TOTAL_SEGMENT_THREADS}。"
                            ),
                            "persistentHint": True,
                        },
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                        "text": "无需重复配置 DeepSeek、TMDB、下载目录、整理规则、Emby 或链接权限；订阅地址内的资源站全部读取。任务按设置并发执行，目录内没有正在下载的缓存文件后才显示完整文件夹。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "generate_nfo": False,
            "config_url": DEFAULT_CONFIG_URL,
        "source_allowlist": "",
        "probe_allowed_private_ranges": "",
        "hls_ad_filter_regex": DEFAULT_HLS_AD_FILTER_REGEX,
            "source_strategy": "first",
            "download_root": "",
            "use_moviepilot_dirs": True,
            "mode": "download",
            "ffmpeg_path": "ffmpeg",
            "request_timeout": 15,
            "poll_minutes": 30,
            "source_check_minutes": DEFAULT_SOURCE_CHECK_MINUTES,
            "queue_minutes": 1,
            "max_concurrent_tasks": DEFAULT_MAX_CONCURRENT_TASKS,
            "segment_thread_count": DEFAULT_SEGMENT_THREAD_COUNT,
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
        source_check_minutes = int(
            self._config.get("source_check_minutes")
            or DEFAULT_SOURCE_CHECK_MINUTES
        )
        queue_minutes = max(1, int(self._config.get("queue_minutes") or 1))
        refresh_trigger: Any
        source_trigger: Any
        queue_trigger: Any
        if CronTrigger is not None:
            refresh_trigger = CronTrigger(minute=f"*/{refresh_minutes}")
            queue_trigger = CronTrigger(minute=f"*/{queue_minutes}")
            source_trigger = (
                IntervalTrigger(minutes=source_check_minutes)
                if IntervalTrigger is not None
                else "interval"
            )
        else:  # pragma: no cover - fallback for standalone tests
            refresh_trigger = source_trigger = queue_trigger = "interval"
        return [
            {
                "id": "LunaTVSource.Refresh",
                "name": "LunaTV 订阅刷新",
                "trigger": refresh_trigger,
                "func": self.refresh_subscriptions,
                "kwargs": {},
            },
            {
                "id": "LunaTVSource.SourceHealth",
                "name": "LunaTV 来源健康检查",
                "trigger": source_trigger,
                "func": self.refresh_source_health,
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
        with self._source_health_lock:
            self._enabled = False
            self._source_health_stop.set()
            self._source_health_running = False
            self._source_health_thread = None
            self._source_health_pending_keys.clear()
            self._source_health_pending_full = False
            self._source_health_run_keys.clear()
            self._source_health_completed_keys.clear()
            self._source_health_revision += 1
        _restore_search_bridge(self)
        _restore_download_clients_bridge(self)
        _restore_download_chain_bridge(self)
        self._cancel_media_sync()
        with self._resource_search_lock:
            self._resource_search_cache.clear()
        if self._queue:
            try:
                stopped = self._queue.stop_and_wait(
                    timeout=_QUEUE_RELOAD_STOP_TIMEOUT_SECONDS
                )
            except Exception as exc:
                self._logger.warning("停止 LunaTV 下载队列失败：%s", exc)
            else:
                if not stopped:
                    self._logger.warning(
                        "LunaTV 下载队列未在 %.1f 秒内退出",
                        _QUEUE_RELOAD_STOP_TIMEOUT_SECONDS,
                    )
                else:
                    self._release_queue_lock()
        else:
            self._release_queue_lock()
        self._cancel_media_sync()

    def _source_allowlist(self) -> Tuple[str, ...]:
        # 空白表示直接使用订阅地址内全部资源站；只有用户明确填写白名单时才过滤。
        # 旧版默认白名单也视为未配置，避免升级后继续隐式过滤订阅内容。
        configured_allowlist = str(self._config.get("source_allowlist") or "").strip()
        return (
            ()
            if not configured_allowlist or configured_allowlist == DEFAULT_SOURCE_ALLOWLIST
            else _source_keys(configured_allowlist)
        )

    def _cached_source_catalog(self) -> List[CmsSource]:
        """Read the persisted catalog without contacting the remote config URL."""

        allowlist = self._source_allowlist()
        cached = self._sources_from_cache(self.get_data(SOURCE_CACHE_KEY), allowlist)
        if cached:
            self._source_config_origin = "本地缓存"
            return cached
        bundled = self._bundled_sources(allowlist)
        if bundled:
            self._source_config_origin = "内置快照"
        else:
            self._source_config_origin = "未加载"
        return bundled

    @staticmethod
    def _configured_source_searchable(source: CmsSource) -> bool:
        payload = source.to_dict()
        return (
            payload.get("status") != "error"
            and payload.get("search_status") == "supported"
        )

    @staticmethod
    def _source_health_generation(record: Dict[str, Any]) -> int:
        try:
            return max(0, int(record.get("generation") or 0))
        except (TypeError, ValueError):
            return 0

    def _source_health_record(self, source: CmsSource) -> Dict[str, Any]:
        with self._source_health_lock:
            record = dict(self._source_health.get(source.key.lower()) or {})
            if record and str(record.get("api") or "") != source.api:
                # Keep an explicit manual disable across endpoint changes, but a
                # previous endpoint's health result must not leak to the new URL.
                return {
                    "manual_disabled": bool(record.get("manual_disabled")),
                    "generation": self._source_health_generation(record),
                }
            return record

    def _source_payload(self, source: CmsSource) -> Dict[str, Any]:
        payload = source.to_dict()
        source_key = source.key.lower()
        with self._source_health_lock:
            record = self._source_health_record(source)
            check_running = self._source_health_running
            check_targeted = source_key in self._source_health_run_keys
            check_complete = source_key in self._source_health_completed_keys
        if check_running and check_targeted:
            check_state = "checked" if check_complete else "pending"
        else:
            check_state = "idle"

        configured_searchable = self._configured_source_searchable(source)
        manual_disabled = bool(record.get("manual_disabled"))
        search_forbidden = bool(record.get("search_forbidden"))
        health_status = str(record.get("health_status") or "unchecked")
        display_health_status = "pending" if check_state == "pending" else health_status

        # 网络失败只表示本轮探测失败，不代表人工配置禁用；来源仍可参与调用。
        enabled = (
            configured_searchable
            and not manual_disabled
        )
        network_successes = max(0, int(record.get("network_successes") or 0))
        network_failures = max(0, int(record.get("network_failures") or 0))

        payload.update(
            {
                "configured_status": payload.get("status"),
                "configured_status_label": payload.get("status_label"),
                "configured_search_status": payload.get("search_status"),
                "configured_search_label": payload.get("search_label"),
                "enabled": enabled,
                "manual_disabled": manual_disabled,
                "auto_disabled": False,
                "health_status": display_health_status,
                "check_state": check_state,
                "network_status": display_health_status,
                "network_label": (
                    "配置禁用"
                    if manual_disabled or not configured_searchable
                    else "网络正常"
                    if health_status == "healthy"
                    else "网络不通"
                    if health_status == "failed"
                    else "待检查"
                ),
                "last_checked": float(record.get("last_checked") or 0),
                "last_error": str(record.get("last_error") or ""),
                "failures": max(0, int(record.get("failures") or 0)),
                "network_successes": network_successes,
                "network_failures": network_failures,
            }
        )

        if manual_disabled or not configured_searchable:
            health_label = "配置禁用"
            disabled_reason = "configured"
        elif display_health_status == "pending":
            health_label = "待检查"
            disabled_reason = ""
        elif health_status == "failed":
            health_label = "网络不通"
            disabled_reason = "network"
        elif health_status == "healthy":
            health_label = "正常"
            disabled_reason = ""
        else:
            health_label = "待检查"
            disabled_reason = ""

        payload.update(
            {
                "health_label": health_label,
                "disabled_reason": disabled_reason,
                "status": "ready" if enabled else "error",
                "status_label": "已启用" if enabled else health_label,
                "search_status": "supported" if enabled else "disabled",
                "search_label": "支持" if enabled else health_label,
            }
        )
        return payload

    def _searchable_sources(self, sources: List[CmsSource]) -> List[CmsSource]:
        return [source for source in sources if self._source_payload(source)["enabled"]]

    def _client(self) -> AppleCmsClient:
        with self._source_health_lock:
            sources = self._searchable_sources(self._cached_source_catalog())
            health_revision = self._source_health_revision
        client = AppleCmsClient(
            sources=sources,
            timeout=float(self._config.get("request_timeout") or 15),
            allowed_private_ranges=self._probe_allowed_private_ranges(),
        )
        client._lunatv_health_revision = health_revision
        return client

    def _current_searchable_source_keys(self) -> set[str]:
        with self._source_health_lock:
            return {
                source.key.lower()
                for source in self._searchable_sources(
                    self._cached_source_catalog()
                )
            }

    def _filter_currently_searchable_results(
        self, results: List[CmsResult], client: Any
    ) -> List[CmsResult]:
        expected_revision = getattr(client, "_lunatv_health_revision", None)
        if expected_revision is None:
            return list(results)
        with self._source_health_lock:
            if self._source_health_revision != expected_revision:
                return []
            enabled_keys = self._current_searchable_source_keys()
            return [
                result
                for result in results
                if str(result.source_key or "").strip().lower() in enabled_keys
            ]

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
        stop_event: Optional[threading.Event] = None,
    ) -> List[CmsSource]:
        """Load sources with a persistent cache and bundled offline fallback.

        UGREEN deployments can run without outbound access to GitHub. A failed
        refresh must not make the plugin appear to have zero sources when a
        previous or bundled configuration is available.
        """

        def set_status(origin: str, error: str) -> bool:
            if stop_event is None:
                self._source_config_origin = origin
                self._source_config_error = error
                return True
            with self._source_health_lock:
                if (
                    stop_event.is_set()
                    or self._source_health_stop is not stop_event
                ):
                    return False
                self._source_config_origin = origin
                self._source_config_error = error
                return True

        try:
            sources = load_sources_from_url(
                config_url,
                timeout=timeout,
                allowlist=allowlist,
                allowed_private_ranges=self._probe_allowed_private_ranges(),
            )
            if not sources:
                raise ValueError("远程配置未包含有效资源站")
            if stop_event is not None:
                with self._source_health_lock:
                    if (
                        stop_event.is_set()
                        or self._source_health_stop is not stop_event
                    ):
                        return []
                    self.save_data(
                        SOURCE_CACHE_KEY,
                        [source.to_dict() for source in sources],
                    )
                    self._source_config_origin = "远程配置"
                    self._source_config_error = ""
            else:
                self.save_data(
                    SOURCE_CACHE_KEY,
                    [source.to_dict() for source in sources],
                )
                self._source_config_origin = "远程配置"
                self._source_config_error = ""
            return sources
        except Exception as exc:
            if stop_event is not None:
                with self._source_health_lock:
                    if (
                        stop_event.is_set()
                        or self._source_health_stop is not stop_event
                    ):
                        return []
            error = str(exc)
            cached = self._sources_from_cache(self.get_data(SOURCE_CACHE_KEY), allowlist)
            if cached:
                if not set_status("本地缓存", error):
                    return []
                self._logger.warning("LunaTV config unavailable; using %s cached sources", len(cached))
                return cached
            bundled = self._bundled_sources(allowlist)
            if bundled:
                if not set_status("内置快照", error):
                    return []
                self._logger.warning("LunaTV config unavailable; using %s bundled sources", len(bundled))
                return bundled
            set_status("加载失败", error)
            raise

    @staticmethod
    def _source_health_error(exc: Exception) -> str:
        message = str(exc or exc.__class__.__name__).strip()
        return (message or exc.__class__.__name__)[:240]

    def _persist_source_health_locked(
        self, updates: Dict[str, Dict[str, Any]]
    ) -> None:
        merged = {key: dict(value) for key, value in self._source_health.items()}
        for key, update in updates.items():
            current = dict(merged.get(key) or {})
            current.update(update)
            merged[key] = current
        self.save_data(SOURCE_HEALTH_KEY, merged)
        self._source_health = merged
        self._source_health_revision += 1
        with self._resource_search_lock:
            self._resource_search_cache.clear()

    def _record_source_health_run(
        self,
        error: str = "",
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        with self._source_health_lock:
            if stop_event is not None and (
                stop_event.is_set() or self._source_health_stop is not stop_event
            ):
                return
            self._source_health_last_error = str(error or "")[:240]
            self._source_health_last_finished = time.time()
            try:
                self.save_data(
                    SOURCE_HEALTH_META_KEY,
                    {
                        "last_error": self._source_health_last_error,
                        "last_finished": self._source_health_last_finished,
                    },
                )
            except Exception as exc:
                self._logger.warning("保存 LunaTV 来源健康检查状态失败：%s", exc)

    def _finish_source_health_run(self, stop_event: threading.Event) -> None:
        next_source_key = ""
        next_is_full = False
        run_next = False
        with self._source_health_lock:
            if self._source_health_stop is not stop_event:
                return
            self._source_health_running = False
            self._source_health_thread = None
            if not stop_event.is_set() and self._source_health_pending_full:
                self._source_health_pending_full = False
                self._source_health_pending_keys.clear()
                next_is_full = True
                run_next = True
            elif not stop_event.is_set() and self._source_health_pending_keys:
                next_source_key = sorted(self._source_health_pending_keys)[0]
                self._source_health_pending_keys.remove(next_source_key)
                run_next = True
        if run_next:
            if not self._start_source_health_refresh(next_source_key):
                with self._source_health_lock:
                    should_retry = (
                        self._source_health_stop is stop_event
                        and not stop_event.is_set()
                        and self._enabled
                    )
                    if should_retry:
                        if next_is_full:
                            self._source_health_pending_full = True
                        else:
                            self._source_health_pending_keys.add(next_source_key)
                if should_retry:
                    self._record_source_health_run(
                        "排队的来源健康检查启动失败，将在下次任务中重试",
                        stop_event=stop_event,
                    )

    def _run_source_health_refresh(
        self,
        source_key: str = "",
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        source_key = str(source_key or "").strip().lower()
        stop_event = stop_event or self._source_health_stop

        def cancelled() -> bool:
            with self._source_health_lock:
                return (
                    stop_event.is_set()
                    or self._source_health_stop is not stop_event
                    or not self._enabled
                )

        if cancelled():
            return {
                "success": False,
                "cancelled": True,
                "checked": 0,
                "message": "来源健康检查已停止",
            }
        if source_key:
            catalog = self._cached_source_catalog()
        else:
            catalog = self._load_sources(
                str(self._config.get("config_url") or DEFAULT_CONFIG_URL),
                timeout=float(self._config.get("request_timeout") or 15),
                allowlist=self._source_allowlist(),
                stop_event=stop_event,
            )
        if cancelled():
            return {
                "success": False,
                "cancelled": True,
                "checked": 0,
                "message": "来源健康检查已停止",
            }
        if source_key:
            catalog = [source for source in catalog if source.key.lower() == source_key]
            if not catalog:
                return {
                    "success": False,
                    "checked": 0,
                    "message": "来源不存在或已从配置中移除",
                }

        checked_at = time.time()
        updates: Dict[str, Dict[str, Any]] = {}
        expected_generations: Dict[str, int] = {}
        expected_record_apis: Dict[str, str] = {}
        candidates: List[CmsSource] = []
        skipped_manual = 0
        for source in catalog:
            key = source.key.lower()
            with self._source_health_lock:
                persisted_record = dict(self._source_health.get(key) or {})
                record = self._source_health_record(source)
            if bool(record.get("manual_disabled")) and key != source_key:
                skipped_manual += 1
                continue
            expected_generations[key] = self._source_health_generation(record)
            expected_record_apis[key] = str(persisted_record.get("api") or "")
            if not self._configured_source_searchable(source):
                configured = source.to_dict()
                updates[key] = {
                    "api": source.api,
                    "health_status": "failed",
                    "last_checked": checked_at,
                    "last_error": (
                        f"配置标记：{configured.get('search_label') or configured.get('status_label') or '不可搜索'}"
                    ),
                    "failures": max(1, int(record.get("failures") or 0)),
                }
                continue
            candidates.append(source)

        applied_updates: Dict[str, Dict[str, Any]] = {}

        def persist_progress(
            candidate_updates: Dict[str, Dict[str, Any]],
        ) -> Dict[str, Dict[str, Any]]:
            with self._source_health_lock:
                if stop_event.is_set() or self._source_health_stop is not stop_event:
                    return {}
                valid_updates = {
                    key: update
                    for key, update in candidate_updates.items()
                    if (
                        key == source_key
                        or not bool(
                            (self._source_health.get(key) or {}).get("manual_disabled")
                        )
                    )
                    and self._source_health_generation(
                        self._source_health.get(key) or {}
                    )
                    == expected_generations.get(key, 0)
                    and str(
                        (self._source_health.get(key) or {}).get("api") or ""
                    )
                    == expected_record_apis.get(key, "")
                }
                completed_keys = set(candidate_updates).intersection(
                    self._source_health_run_keys
                )
                progress_changed = not completed_keys.issubset(
                    self._source_health_completed_keys
                )
                if valid_updates:
                    self._persist_source_health_locked(valid_updates)
                self._source_health_completed_keys.update(completed_keys)
                if progress_changed and not valid_updates:
                    self._source_health_revision += 1
                return valid_updates

        with self._source_health_lock:
            if stop_event.is_set() or self._source_health_stop is not stop_event:
                return {
                    "success": False,
                    "cancelled": True,
                    "checked": 0,
                    "message": "来源健康检查已停止",
                }
            self._source_health_run_keys = set(expected_generations)
            self._source_health_completed_keys.clear()
            self._source_health_revision += 1

        applied_updates.update(persist_progress(updates))

        timeout = min(
            10.0,
            max(2.0, float(self._config.get("request_timeout") or 15)),
        )
        client = AppleCmsClient(
            sources=candidates,
            timeout=timeout,
            allowed_private_ranges=self._probe_allowed_private_ranges(),
        )

        def check(source: CmsSource) -> Tuple[CmsSource, str]:
            if cancelled():
                return source, ""
            try:
                client.verify_search(source, SOURCE_HEALTH_QUERY)
                return source, ""
            except Exception as exc:
                return source, self._source_health_error(exc)

        if candidates:
            with ThreadPoolExecutor(
                max_workers=min(SOURCE_HEALTH_WORKERS, len(candidates)),
                thread_name_prefix="lunatv-source-health",
            ) as executor:
                futures = [executor.submit(check, source) for source in candidates]
                for future in as_completed(futures):
                    source, error = future.result()
                    key = source.key.lower()
                    previous = self._source_health_record(source)
                    failures = max(0, int(previous.get("failures") or 0))
                    network_successes = max(
                        0, int(previous.get("network_successes") or 0)
                    )
                    network_failures = max(
                        0, int(previous.get("network_failures") or 0)
                    )
                    search_forbidden = bool(
                        error and "禁止关键词搜索" in error
                    )
                    update = {
                        "api": source.api,
                        "health_status": "failed" if error else "healthy",
                        "last_checked": time.time(),
                        "last_error": error,
                        "failures": failures + 1 if error else 0,
                        "search_forbidden": search_forbidden,
                        "network_successes": network_successes
                        + (0 if error else 1),
                        "network_failures": network_failures
                        + (1 if error else 0),
                    }
                    applied_updates.update(persist_progress({key: update}))

        if cancelled():
            return {
                "success": False,
                "cancelled": True,
                "checked": 0,
                "message": "来源健康检查已停止",
            }
        failed = sum(
            1
            for update in applied_updates.values()
            if update.get("health_status") == "failed"
        )
        healthy = sum(
            1
            for update in applied_updates.values()
            if update.get("health_status") == "healthy"
        )
        return {
            "success": True,
            "checked": len(applied_updates),
            "healthy": healthy,
            "disabled": failed,
            "skipped_manual": skipped_manual,
        }

    def refresh_source_health(self, source_key: str = "") -> Dict[str, Any]:
        """Refresh the remote catalog and persist per-source search health."""
        source_key = str(source_key or "").strip().lower()

        with self._source_health_lock:
            if not self._enabled or self._source_health_stop.is_set():
                return {"success": False, "message": "插件未启用"}
            if self._source_health_running:
                if source_key:
                    self._source_health_pending_keys.add(source_key)
                else:
                    self._source_health_pending_full = True
                return {
                    "success": True,
                    "started": False,
                    "running": True,
                    "queued": True,
                }
            self._source_health_running = True
            self._source_health_run_keys.clear()
            self._source_health_completed_keys.clear()
            stop_event = self._source_health_stop
        try:
            result = self._run_source_health_refresh(
                source_key,
                stop_event=stop_event,
            )
            if not result.get("cancelled"):
                self._record_source_health_run(
                    "" if result.get("success") else str(result.get("message") or "检查失败"),
                    stop_event=stop_event,
                )
            return result
        except Exception as exc:
            self._logger.warning("LunaTV 来源健康检查失败：%s", exc)
            error = self._source_health_error(exc)
            self._record_source_health_run(error, stop_event=stop_event)
            return {"success": False, "message": error}
        finally:
            self._finish_source_health_run(stop_event)

    def _start_source_health_refresh(self, source_key: str = "") -> bool:
        source_key = str(source_key or "").strip().lower()
        with self._source_health_lock:
            if not self._enabled or self._source_health_stop.is_set():
                return False
            if self._source_health_running:
                if source_key:
                    self._source_health_pending_keys.add(source_key)
                else:
                    self._source_health_pending_full = True
                return True
            self._source_health_running = True
            self._source_health_run_keys.clear()
            self._source_health_completed_keys.clear()
            stop_event = self._source_health_stop

        def runner() -> None:
            try:
                result = self._run_source_health_refresh(
                    source_key,
                    stop_event=stop_event,
                )
                if not result.get("cancelled"):
                    self._record_source_health_run(
                        "" if result.get("success") else str(result.get("message") or "检查失败"),
                        stop_event=stop_event,
                    )
            except Exception as exc:
                self._logger.warning("LunaTV 来源健康检查失败：%s", exc)
                self._record_source_health_run(
                    self._source_health_error(exc),
                    stop_event=stop_event,
                )
            finally:
                self._finish_source_health_run(stop_event)

        try:
            thread = threading.Thread(
                target=runner,
                name="lunatvsource-source-health",
                daemon=True,
            )
            with self._source_health_lock:
                if self._source_health_stop is not stop_event or stop_event.is_set():
                    self._source_health_running = False
                    return False
                self._source_health_thread = thread
            thread.start()
            return True
        except RuntimeError:
            with self._source_health_lock:
                if self._source_health_stop is stop_event:
                    self._source_health_running = False
                    self._source_health_thread = None
            self._logger.exception("LunaTV 来源健康检查线程启动失败")
            return False

    def _source_health_due(self) -> bool:
        interval = int(
            self._config.get("source_check_minutes")
            or DEFAULT_SOURCE_CHECK_MINUTES
        )
        cutoff = time.time() - interval * 60
        active_sources = 0
        for source in self._cached_source_catalog():
            record = self._source_health_record(source)
            if bool(record.get("manual_disabled")):
                continue
            active_sources += 1
            try:
                last_checked = float(record.get("last_checked") or 0)
            except (TypeError, ValueError):
                last_checked = 0.0
            if (
                str(record.get("api") or "") != source.api
                or str(record.get("health_status") or "") not in {"healthy", "failed"}
                or last_checked < cutoff
            ):
                return True
        with self._source_health_lock:
            last_finished = self._source_health_last_finished
        return active_sources == 0 and last_finished < cutoff

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
                max(0, int(episode.season if episode.season is not None else 1))
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
                    "transfer_type": str(getattr(item, "transfer_type", "") or "").strip(),
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
                    download_path = Path(item["download_path"]).expanduser().resolve()
                    if target_path == download_path or target_path.is_relative_to(download_path):
                        return item
            except OSError:
                pass
            return None
        return infos[0] if infos else None

    def _auto_library_target(self, media_type: str, root: str) -> Tuple[str, str]:
        """Find an existing local library without adding another plugin setting."""

        normalized_type = "tv" if media_type == "tv" else "movie"
        expected_names = _AUTO_LIBRARY_DIR_NAMES[normalized_type]

        if _HostDirectoryHelper is not None:
            try:
                get_library_dirs = getattr(_HostDirectoryHelper(), "get_library_dirs", None)
                entries = get_library_dirs() if callable(get_library_dirs) else []
                for item in entries or []:
                    storage = str(getattr(item, "library_storage", "local") or "local").strip().lower()
                    path = str(getattr(item, "library_path", "") or "").strip()
                    if storage not in {"local", ""} or not path.startswith("/"):
                        continue
                    if not self._media_type_matches(getattr(item, "media_type", ""), normalized_type):
                        continue
                    if Path(path).is_dir():
                        transfer_type = str(getattr(item, "transfer_type", "") or "").strip()
                        return path, transfer_type or _AUTO_TRANSFER_TYPE
            except Exception as exc:
                self._logger.debug("读取 MoviePilot 媒体库目录失败：%s", exc)

        try:
            root_path = Path(root).expanduser().resolve()
            parents = [root_path.parent]
            if root_path.parent.parent != root_path.parent:
                parents.append(root_path.parent.parent)
            for parent in parents:
                if not parent.is_dir():
                    continue
                children = {
                    child.name.casefold(): child
                    for child in parent.iterdir()
                    if child.is_dir()
                }
                for name in expected_names:
                    candidate = children.get(name.casefold())
                    if candidate is not None:
                        return str(candidate), _AUTO_TRANSFER_TYPE
        except OSError as exc:
            self._logger.debug("自动检测本地媒体库目录失败：%s", exc)

        if _HostMediaServerChain is not None:
            try:
                server = str(self._config.get("mediaserver_name") or "").strip() or None
                libraries = _HostMediaServerChain().librarys(server=server) or []
                candidates: List[str] = []
                for library in libraries:
                    if not self._media_type_matches(getattr(library, "type", ""), normalized_type):
                        continue
                    paths = getattr(library, "path", None) or []
                    if isinstance(paths, str):
                        paths = [paths]
                    for path in paths:
                        value = str(path or "").strip()
                        if value.startswith("/") and Path(value).is_dir():
                            candidates.append(value)
                if candidates:
                    expected_names_casefold = {name.casefold() for name in expected_names}
                    candidates.sort(
                        key=lambda value: (
                            Path(value).name.casefold() not in expected_names_casefold,
                            value,
                        )
                    )
                    return candidates[0], _AUTO_TRANSFER_TYPE
            except Exception as exc:
                self._logger.debug("读取媒体服务器目录失败：%s", exc)

        return "", ""

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
            desired_mode = (
                "strm"
                if str(getattr(task, "mode", "download") or "download").casefold()
                == "strm"
                else "download"
            )

            def _artifact_mode(item: Any) -> Optional[str]:
                for key in ("fullpath", "file_path", "filepath", "path"):
                    raw_path = str(_field(item, key, "") or "").strip()
                    if not raw_path:
                        continue
                    path_without_query = raw_path.split("?", 1)[0].lower()
                    if path_without_query.endswith(".strm"):
                        return "strm"
                    if extension_for_url(path_without_query, default=""):
                        return "download"
                return None

            for history in histories:
                download_hash = str(
                    _field(history, "download_hash", "") or ""
                ).strip()
                if callable(get_files):
                    if not download_hash:
                        continue
                    try:
                        completed_files = list(get_files(download_hash, state=1) or [])
                    except TypeError:
                        completed_files = [
                            item
                            for item in (get_files(download_hash) or [])
                            if str(
                                item.get("state", 1)
                                if isinstance(item, dict)
                                else getattr(item, "state", 1)
                            ).lower()
                            not in {"0", "false", "none", ""}
                        ]
                    if not completed_files:
                        continue
                    known_modes = {
                        artifact_mode
                        for artifact_mode in (
                            _artifact_mode(item) for item in completed_files
                        )
                        if artifact_mode
                    }
                    if known_modes and desired_mode not in known_modes:
                        self._logger.debug(
                            "跳过不同处理方式的 MoviePilot 下载历史：mode=%s, files=%s",
                            desired_mode,
                            sorted(known_modes),
                        )
                        continue
                if task.media_type != "tv":
                    return True
                seasons = self._history_numbers(_field(history, "seasons", ""))
                episodes = self._history_numbers(_field(history, "episodes", ""))
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
            target_path = str((directory or {}).get("library_path") or "").strip()
            transfer_type = str((directory or {}).get("transfer_type") or "").strip()
            if not target_path:
                target_path, inferred_transfer_type = self._auto_library_target(task.media_type, task.root)
                transfer_type = transfer_type or inferred_transfer_type
            elif not transfer_type:
                transfer_type = _AUTO_TRANSFER_TYPE
            if not target_path:
                return "fallback:no-library-target"
            try:
                if Path(target_path).expanduser().resolve() == Path(task.root).expanduser().resolve():
                    return "fallback:library-equals-download-root"
            except OSError:
                pass
            transfer_chain = _HostTransferChain()
            host_media_source = self._host_media_source_value(media_source)
            host_media_type = self._host_media_type(task.media_type)
            scrape = _bool(self._config.get("generate_nfo"), False)
            movie_meta = (
                self._host_meta_info(
                    getattr(task, "title", ""),
                    getattr(task, "year", ""),
                )
                if task.media_type != "tv"
                else None
            )
            direct_transfer = getattr(transfer_chain, "do_transfer", None)
            if movie_meta is not None and callable(direct_transfer) and transfer_type:
                # MoviePilot's generic manual entrypoint reparses the source
                # path.  Some host/parser combinations synthesize S01/E01 for
                # an otherwise season-free movie and therefore select the TV
                # rename template.  Supply authoritative movie metadata to
                # the stable transfer entrypoint so only TV tasks can carry
                # season/episode information into the library layout.
                if hasattr(movie_meta, "type"):
                    movie_meta.type = host_media_type
                for field_name in (
                    "begin_season",
                    "end_season",
                    "total_season",
                    "begin_episode",
                    "end_episode",
                    "total_episode",
                ):
                    if hasattr(movie_meta, field_name):
                        setattr(movie_meta, field_name, None)
                state, message = direct_transfer(
                    fileitem=fileitem,
                    meta=movie_meta,
                    target_storage="local",
                    target_path=Path(target_path),
                    transfer_type=transfer_type,
                    media_source=host_media_source,
                    media_id=media_id,
                    mtype=host_media_type,
                    season=None,
                    force=False,
                    background=False,
                    manual=True,
                    scrape=scrape,
                    sync_extra_files=True,
                )
            else:
                state, message = transfer_chain.manual_transfer(
                    fileitem=fileitem,
                    target_storage="local",
                    target_path=Path(target_path),
                    transfer_type=transfer_type,
                    media_source=host_media_source,
                    media_id=media_id,
                    mtype=host_media_type,
                    season=task.season if task.media_type == "tv" else None,
                    force=False,
                    background=False,
                    scrape=scrape,
                )
            if state:
                if transfer_type.casefold() == "move":
                    source_path = Path(output)
                    for _ in range(20):
                        if not source_path.exists():
                            break
                        time.sleep(0.05)
                    if source_path.exists():
                        return "fallback:move-source-still-exists"
                return "moviepilot"
            self._logger.warning("MoviePilot 原生整理未完成，保留直写文件：%s", message)
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

    def _cancel_media_sync(self) -> None:
        """Invalidate pending work so an old/reloaded instance cannot mutate progress."""

        with self._media_sync_lock:
            self._media_sync_stop.set()
            self._media_sync_generation += 1
            with self._followup_status_lock:
                self._followup_generations["media_server_sync"] += 1
            self._media_sync_requested = False
            self._media_sync_refresh_ids.clear()
            self._media_sync_backfill.clear()
            self._media_sync_probes.clear()
            self._media_sync_running = False
            self._media_sync_thread = None
            self._media_sync_stop = threading.Event()

    def _record_followup_status(
        self,
        name: str,
        *,
        started_at: float,
        success: bool,
        error: str = "",
        details: Optional[Dict[str, Any]] = None,
        generation: Optional[int] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "started_at": started_at,
            "finished_at": time.time(),
            "success": bool(success),
            "error": str(error or "")[:240],
        }
        entry.update(details or {})
        with self._followup_status_lock:
            if generation is not None and generation != self._followup_generations.get(
                name
            ):
                return
            self._followup_status[name] = entry
            snapshot = {
                key: dict(value) for key, value in self._followup_status.items()
            }
        try:
            self.save_data(FOLLOWUP_STATUS_KEY, snapshot)
        except Exception as exc:
            self._logger.warning("保存 LunaTV 追更状态失败：%s", exc)

    def _native_subscription_ids(self, task: DownloadTask) -> set[int]:
        """Resolve active MoviePilot subscriptions by exact media identity and season."""

        if (
            _HostSubscribeChain is None
            or _media_type_value(getattr(task, "media_type", "")) != "tv"
        ):
            return set()
        identities: set[Tuple[str, str]] = set()
        for source, media_id in (
            (
                getattr(task, "host_media_source", None),
                getattr(task, "host_media_id", None),
            ),
            (getattr(task, "source_key", None), getattr(task, "media_id", None)),
        ):
            normalized_source = _enum_value(source)
            normalized_id = str(media_id or "").strip()
            if normalized_source and normalized_id:
                identities.add((normalized_source, normalized_id))
        if not identities:
            return set()

        try:
            repository = getattr(_HostSubscribeChain(), "subscription_repository", None)
            list_subscriptions = getattr(repository, "list", None)
            if not callable(list_subscriptions):
                return set()
            try:
                subscriptions = list_subscriptions("R,P")
            except TypeError:
                subscriptions = list_subscriptions()
        except Exception as exc:
            self._logger.debug("读取 MoviePilot 订阅快照失败：%s", exc)
            return set()

        raw_task_season = getattr(task, "season", None)
        try:
            task_season = int(raw_task_season) if raw_task_season is not None else None
        except (TypeError, ValueError):
            task_season = None
        matched: set[int] = set()
        for subscribe in subscriptions or []:
            if _media_type_value(getattr(subscribe, "type", "")) != "tv":
                continue
            state = _enum_value(getattr(subscribe, "state", "R"))
            if state not in {"r", "p", "1", "active", "enabled"}:
                continue
            identity = (
                _enum_value(getattr(subscribe, "media_source", "")),
                str(getattr(subscribe, "media_id", "") or "").strip(),
            )
            if identity not in identities:
                continue
            raw_subscribe_season = getattr(subscribe, "season", None)
            try:
                subscribe_season = (
                    int(raw_subscribe_season)
                    if raw_subscribe_season is not None
                    else None
                )
            except (TypeError, ValueError):
                subscribe_season = None
            if task_season is None or subscribe_season != task_season:
                continue
            try:
                subscribe_id = int(getattr(subscribe, "id", 0) or 0)
            except (TypeError, ValueError):
                subscribe_id = 0
            if subscribe_id:
                matched.add(subscribe_id)
        return matched

    def _backfill_native_subscription_progress(
        self, episodes_by_subscription: Dict[int, set[int]]
    ) -> set[int]:
        """Use MoviePilot's idempotent episode-fact mutation when the host supports it."""

        if not episodes_by_subscription or _HostSubscribeChain is None:
            return set()
        try:
            chain = _HostSubscribeChain()
            repository = getattr(chain, "subscription_repository", None)
            get_subscription = getattr(repository, "get", None)
            backfill = getattr(chain, "backfill_existing_episodes", None)
            if not callable(get_subscription) or not callable(backfill):
                return set()
        except Exception as exc:
            self._logger.debug("MoviePilot 订阅回填接口不可用：%s", exc)
            return set()

        handled: set[int] = set()
        with self._subscription_progress_lock:
            for subscribe_id, episodes in sorted(episodes_by_subscription.items()):
                normalized = sorted(
                    {
                        int(episode)
                        for episode in episodes
                        if str(episode).strip().isdigit() and int(episode) > 0
                    }
                )
                if not normalized:
                    continue
                try:
                    subscribe = get_subscription(subscribe_id)
                    if subscribe is None:
                        continue
                    summary = self._call_native_subscription_progress(
                        backfill, subscribe, normalized
                    ) or {}
                    accepted = {
                        int(episode)
                        for episode in (summary.get("accepted") or [])
                        if str(episode).strip().isdigit()
                    } if isinstance(summary, dict) else set()
                    duplicates = {
                        int(item.get("episode"))
                        for item in (summary.get("ignored") or [])
                        if isinstance(item, dict)
                        and item.get("reason") == "duplicate"
                        and str(item.get("episode")).strip().isdigit()
                    } if isinstance(summary, dict) else set()
                    if set(normalized).issubset(accepted | duplicates):
                        handled.add(subscribe_id)
                    if isinstance(summary, dict) and summary.get("accepted"):
                        self._logger.info(
                            "MoviePilot 订阅进度已回填：subscription=%s episodes=%s",
                            subscribe_id,
                            len(summary["accepted"]),
                        )
                except Exception as exc:
                    self._logger.warning(
                        "回填 MoviePilot 订阅进度失败 subscription=%s：%s",
                        subscribe_id,
                        exc,
                    )
        return handled

    @staticmethod
    def _call_native_subscription_progress(func, *args):
        """Tag plugin-owned progress mutations so their events are not re-consumed."""

        try:
            parameters = inspect.signature(func).parameters
        except (TypeError, ValueError):
            parameters = {}
        supports_scene = "scene" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if supports_scene:
            return func(*args, scene=_SUBSCRIPTION_PROGRESS_EVENT_SCENE)
        return func(*args)

    def _refresh_native_subscription_progress(
        self, subscription_ids: set[int]
    ) -> set[int]:
        """Recompute native progress after the media-server repository is synchronized."""

        if not subscription_ids or _HostSubscribeChain is None:
            return set()
        try:
            chain = _HostSubscribeChain()
            repository = getattr(chain, "subscription_repository", None)
            get_subscription = getattr(repository, "get", None)
            refresh = getattr(chain, "refresh_subscribe_progress", None)
            if not callable(get_subscription) or not callable(refresh):
                return set()
        except Exception as exc:
            self._logger.debug("MoviePilot 订阅刷新接口不可用：%s", exc)
            return set()

        refreshed: set[int] = set()
        with self._subscription_progress_lock:
            for subscribe_id in sorted(subscription_ids):
                try:
                    subscribe = get_subscription(subscribe_id)
                    if subscribe is None:
                        continue
                    self._call_native_subscription_progress(refresh, subscribe)
                    refreshed.add(subscribe_id)
                except Exception as exc:
                    self._logger.warning(
                        "刷新 MoviePilot 订阅进度失败 subscription=%s：%s",
                        subscribe_id,
                        exc,
                    )
        return refreshed

    def _media_server_services(self, server: Optional[str]) -> Dict[str, Any]:
        """读取 MoviePilot 已配置且正在运行的媒体服务器实例。"""
        if _HostMediaServerHelper is None:
            self._logger.warning("MoviePilot 媒体服务器服务目录不可用，未请求媒体库刷新")
            return {}
        try:
            helper = _HostMediaServerHelper()
            try:
                services = helper.get_services(
                    name_filters=[server] if server else None
                ) or {}
            except TypeError:
                services = helper.get_services() or {}
                if server:
                    services = {
                        name: service
                        for name, service in services.items()
                        if str(name).strip() == server
                    }
        except Exception as exc:
            self._logger.warning(
                "获取 MoviePilot 媒体服务器实例失败：%s",
                type(exc).__name__,
            )
            return {}
        if not services:
            self._logger.warning("未找到可刷新的 MoviePilot 媒体服务器实例")
        return services

    def _refresh_media_server_library(
        self, server: Optional[str]
    ) -> Tuple[Dict[str, Any], bool]:
        """请求扫描媒体库，并返回已接受请求的服务及是否全部成功。"""

        services = self._media_server_services(server)
        if not services:
            return {}, False

        accepted_services: Dict[str, Any] = {}
        all_succeeded = True
        for name, service in services.items():
            instance = getattr(service, "instance", None)
            refresh = getattr(instance, "refresh_root_library", None)
            if not callable(refresh):
                self._logger.warning("媒体服务器 %s 不支持主动刷新媒体库", name)
                all_succeeded = False
                continue
            try:
                result = refresh()
            except Exception as exc:
                self._logger.warning(
                    "媒体服务器 %s 刷新请求失败：%s",
                    name,
                    type(exc).__name__,
                )
                all_succeeded = False
                continue
            if result is False:
                self._logger.warning("媒体服务器 %s 未接受媒体库刷新请求", name)
                all_succeeded = False
                continue
            accepted_services[name] = service

        return accepted_services, bool(accepted_services) and all_succeeded

    def _wait_for_media_server_item(
        self,
        server: Optional[str],
        media_probe: Dict[str, Any],
        stop_event: threading.Event,
        generation: int,
        services: Optional[Dict[str, Any]] = None,
        single_check: bool = False,
    ) -> bool:
        """等待媒体服务器实际返回本轮新整理的电影或剧集。"""

        media_type = str(media_probe.get("media_type") or "").strip().lower()
        title = str(media_probe.get("title") or "").strip()
        year = str(media_probe.get("year") or "").strip() or None
        if media_type not in {"movie", "tv"} or not title:
            return True
        target_services = (
            services if services is not None else self._media_server_services(server)
        )
        if not target_services:
            return False

        try:
            season = int(media_probe.get("season") or 0) or None
        except (TypeError, ValueError):
            season = None
        try:
            episode = int(media_probe.get("episode") or 0) or None
        except (TypeError, ValueError):
            episode = None
        deadline = time.monotonic() + _MEDIA_SYNC_VISIBILITY_TIMEOUT_SECONDS

        while True:
            if stop_event.is_set() or generation != self._media_sync_generation:
                return False
            all_visible = True
            for service in target_services.values():
                instance = getattr(service, "instance", None)
                try:
                    if media_type == "movie":
                        query = getattr(instance, "get_movies", None)
                        visible = bool(
                            callable(query) and query(title=title, year=year)
                        )
                    else:
                        query = getattr(instance, "get_tv_episodes", None)
                        result = (
                            query(title=title, year=year, season=season)
                            if callable(query)
                            else None
                        )
                        season_episodes = (
                            result[1]
                            if isinstance(result, tuple) and len(result) > 1
                            else {}
                        ) or {}
                        if episode is None:
                            visible = bool(season_episodes)
                        else:
                            values = season_episodes.get(season or 0) or season_episodes.get(
                                str(season or 0)
                            ) or []
                            visible = episode in {
                                int(value)
                                for value in values
                                if str(value).strip().isdigit()
                            }
                except Exception:
                    visible = False
                if not visible:
                    all_visible = False
                    break
            if all_visible:
                return True
            if single_check:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            wait_seconds = min(_MEDIA_SYNC_VISIBILITY_POLL_SECONDS, remaining)
            if stop_event.wait(max(0.0, wait_seconds)):
                return False

        self._logger.warning("媒体服务器刷新后仍未发现新媒体：%s (%s)", title, year or "")
        return False

    def _sync_media_server(
        self,
        subscription_ids: Optional[set[int]] = None,
        episode: Optional[int] = None,
        media_probe: Optional[Dict[str, Any]] = None,
        episodes_by_subscription: Optional[Dict[int, set[int]]] = None,
    ) -> bool:
        """后台刷新媒体服务器并同步索引，再提交原生订阅进度。"""

        if not self._enabled:
            return False
        normalized_ids: set[int] = set()
        for value in subscription_ids or set():
            try:
                subscribe_id = int(value)
            except (TypeError, ValueError):
                continue
            if subscribe_id > 0:
                normalized_ids.add(subscribe_id)
        normalized_backfill: Dict[int, set[int]] = {}
        for raw_subscribe_id, raw_episodes in (
            episodes_by_subscription or {}
        ).items():
            try:
                subscribe_id = int(raw_subscribe_id)
            except (TypeError, ValueError):
                continue
            if subscribe_id <= 0:
                continue
            episodes: set[int] = set()
            for raw_episode in raw_episodes or set():
                try:
                    episode_value = int(raw_episode)
                except (TypeError, ValueError):
                    continue
                if episode_value > 0:
                    episodes.add(episode_value)
            if not episodes:
                continue
            normalized_ids.add(subscribe_id)
            normalized_backfill[subscribe_id] = episodes
        try:
            episode_number = int(episode) if episode is not None else None
        except (TypeError, ValueError):
            episode_number = None
        if episode_number is not None and episode_number <= 0:
            episode_number = None
        normalized_probe: Optional[Dict[str, Any]] = None
        if isinstance(media_probe, dict):
            media_type = str(media_probe.get("media_type") or "").strip().lower()
            title = str(media_probe.get("title") or "").strip()
            if media_type in {"movie", "tv"} and title:
                probe_numbers: Dict[str, Optional[int]] = {}
                for key in ("season", "episode"):
                    try:
                        number = int(media_probe.get(key) or 0)
                    except (TypeError, ValueError):
                        number = 0
                    probe_numbers[key] = number if number > 0 else None
                normalized_probe = {
                    "media_type": media_type,
                    "title": title,
                    "year": str(media_probe.get("year") or "").strip(),
                    "season": probe_numbers["season"],
                    "episode": probe_numbers["episode"],
                }

        def probe_key(probe: Dict[str, Any]) -> Tuple[str, str, str, int, int]:
            return (
                str(probe.get("media_type") or ""),
                str(probe.get("title") or "").casefold(),
                str(probe.get("year") or ""),
                int(probe.get("season") or 0),
                int(probe.get("episode") or 0),
            )

        if (
            _HostMediaServerChain is None
            and not normalized_ids
            and not normalized_backfill
        ):
            return False

        started_at = time.time()

        with self._media_sync_lock:
            if not self._enabled:
                return False
            if _HostMediaServerChain is not None:
                self._media_sync_requested = True
                if normalized_probe is not None:
                    self._media_sync_probes[probe_key(normalized_probe)] = normalized_probe
            self._media_sync_refresh_ids.update(normalized_ids)
            for subscribe_id, episodes in normalized_backfill.items():
                self._media_sync_backfill.setdefault(subscribe_id, set()).update(
                    episodes
                )
            if episode_number is not None:
                for subscribe_id in normalized_ids:
                    self._media_sync_backfill.setdefault(subscribe_id, set()).add(
                        episode_number
                    )
            if self._media_sync_running:
                return False
            self._media_sync_running = True
            with self._followup_status_lock:
                self._followup_generations["media_server_sync"] += 1
                followup_generation = self._followup_generations[
                    "media_server_sync"
                ]
            generation = self._media_sync_generation
            stop_event = self._media_sync_stop

        server = str(self._config.get("mediaserver_name") or "").strip() or None

        def runner() -> None:
            retry_count = 0
            completed_backfill_ids: set[int] = set()
            completed_refresh_ids: set[int] = set()
            media_server_refresh_requested = False
            media_server_refreshed = False
            moviepilot_index_synced = False
            media_server_synced = False
            runner_failed = False
            runner_error = ""
            failed_probe_keys: set[Tuple[str, str, str, int, int]] = set()
            successful_media_batches = 0
            failed_media_batches = 0
            retry_sync_requested = False
            retry_backfill: Dict[int, set[int]] = {}
            retry_refresh_ids: set[int] = set()
            retry_probes: List[Dict[str, Any]] = []
            while True:
                if stop_event.is_set() or generation != self._media_sync_generation:
                    return
                with self._media_sync_lock:
                    if generation != self._media_sync_generation:
                        return
                    if (
                        retry_sync_requested
                        or retry_backfill
                        or retry_refresh_ids
                        or retry_probes
                    ):
                        sync_requested = retry_sync_requested
                        pending_backfill = {
                            subscribe_id: set(episodes)
                            for subscribe_id, episodes in retry_backfill.items()
                        }
                        refresh_ids = set(retry_refresh_ids)
                        pending_probes = list(retry_probes)
                        retry_sync_requested = False
                        retry_backfill = {}
                        retry_refresh_ids = set()
                        retry_probes = []
                    else:
                        sync_requested = self._media_sync_requested
                        self._media_sync_requested = False
                        pending_backfill = {
                            subscribe_id: set(episodes)
                            for subscribe_id, episodes in self._media_sync_backfill.items()
                        }
                        self._media_sync_backfill.clear()
                        refresh_ids = set(self._media_sync_refresh_ids)
                        self._media_sync_refresh_ids.clear()
                        pending_probes = list(self._media_sync_probes.values())
                        self._media_sync_probes.clear()

                refresh_requested = False
                refresh_succeeded = False
                refresh_request_succeeded = False
                index_sync_succeeded = False
                unresolved_probes: Dict[
                    Tuple[str, str, str, int, int], Dict[str, Any]
                ] = {}
                if sync_requested and _HostMediaServerChain is not None:
                    with self._media_server_sync_lock:
                        if stop_event.is_set() or generation != self._media_sync_generation:
                            return
                        refresh_result = self._refresh_media_server_library(server)
                        accepted_services: Optional[Dict[str, Any]] = None
                        if isinstance(refresh_result, tuple) and len(refresh_result) == 2:
                            accepted_services = (
                                refresh_result[0]
                                if isinstance(refresh_result[0], dict)
                                else {}
                            )
                            refresh_requested = bool(accepted_services)
                            refresh_succeeded = bool(refresh_result[1])
                        else:
                            refresh_requested = bool(refresh_result)
                            refresh_succeeded = refresh_requested
                        refresh_request_succeeded = refresh_succeeded
                        unresolved_probes = {
                            probe_key(pending_probe): pending_probe
                            for pending_probe in pending_probes
                        }
                        if refresh_requested and unresolved_probes:
                            visibility_deadline = (
                                time.monotonic()
                                + _MEDIA_SYNC_VISIBILITY_TIMEOUT_SECONDS
                            )
                            while unresolved_probes:
                                for key, pending_probe in list(
                                    unresolved_probes.items()
                                ):
                                    if self._wait_for_media_server_item(
                                        server,
                                        pending_probe,
                                        stop_event,
                                        generation,
                                        services=accepted_services,
                                        single_check=True,
                                    ):
                                        unresolved_probes.pop(key, None)
                                if not unresolved_probes:
                                    break
                                if (
                                    stop_event.is_set()
                                    or generation != self._media_sync_generation
                                ):
                                    return
                                remaining = visibility_deadline - time.monotonic()
                                if remaining <= 0:
                                    for pending_probe in unresolved_probes.values():
                                        self._logger.warning(
                                            "媒体服务器刷新后仍未发现新媒体：%s （%s）",
                                            pending_probe.get("title") or "",
                                            pending_probe.get("year") or "",
                                        )
                                    break
                                if stop_event.wait(
                                    min(_MEDIA_SYNC_VISIBILITY_POLL_SECONDS, remaining)
                                ):
                                    return
                            refresh_succeeded = (
                                refresh_succeeded and not unresolved_probes
                            )
                        if stop_event.is_set() or generation != self._media_sync_generation:
                            return
                        try:
                            _HostMediaServerChain().sync(server=server)
                            index_sync_succeeded = True
                        except Exception as exc:
                            self._logger.warning(
                                "MoviePilot 媒体服务器索引同步失败：%s",
                                type(exc).__name__,
                            )
                sync_succeeded = refresh_succeeded and index_sync_succeeded
                batch_failed_probe_keys: set[
                    Tuple[str, str, str, int, int]
                ] = set()
                if sync_requested and pending_probes:
                    if not refresh_request_succeeded or not index_sync_succeeded:
                        batch_failed_probe_keys.update(
                            probe_key(pending_probe)
                            for pending_probe in pending_probes
                        )
                    else:
                        batch_failed_probe_keys.update(unresolved_probes)

                if stop_event.is_set() or generation != self._media_sync_generation:
                    return

                handled_ids = self._backfill_native_subscription_progress(
                    pending_backfill
                )
                completed_backfill_ids.update(handled_ids)
                remaining_refresh_ids = refresh_ids.difference(handled_ids)
                refreshed_ids: set[int] = set()
                can_refresh_progress = (
                    sync_succeeded or _HostMediaServerChain is None
                )
                if can_refresh_progress and remaining_refresh_ids:
                    refreshed_ids = (
                        self._refresh_native_subscription_progress(
                            remaining_refresh_ids
                        )
                        or set()
                    )
                    completed_refresh_ids.update(refreshed_ids)
                media_server_refresh_requested = (
                    media_server_refresh_requested or refresh_requested
                )
                media_server_refreshed = (
                    media_server_refreshed or refresh_succeeded
                )
                moviepilot_index_synced = (
                    moviepilot_index_synced or index_sync_succeeded
                )
                media_server_synced = media_server_synced or sync_succeeded

                failed_backfill_ids = set(pending_backfill).difference(handled_ids)
                failed_refresh_ids = remaining_refresh_ids.difference(refreshed_ids)
                retry_needed = (sync_requested and not sync_succeeded) or bool(
                    can_refresh_progress and failed_refresh_ids
                ) or bool(failed_backfill_ids)
                if retry_needed and retry_count < _MEDIA_SYNC_RETRY_LIMIT:
                    retry_count += 1
                    if stop_event.is_set() or generation != self._media_sync_generation:
                        return
                    retry_sync_requested = _HostMediaServerChain is not None
                    retry_refresh_ids = set(failed_refresh_ids)
                    retry_backfill = {
                        subscribe_id: set(episodes)
                        for subscribe_id, episodes in pending_backfill.items()
                        if subscribe_id not in handled_ids
                    }
                    retry_probes = [
                        pending_probe
                        for pending_probe in pending_probes
                        if probe_key(pending_probe) in batch_failed_probe_keys
                    ]
                    if stop_event.wait(_MEDIA_SYNC_RETRY_DELAY_SECONDS):
                        return
                    continue
                if sync_requested:
                    if sync_succeeded:
                        successful_media_batches += 1
                    else:
                        failed_media_batches += 1
                if retry_needed:
                    runner_failed = True
                    if sync_requested and not sync_succeeded:
                        failed_probe_keys.update(batch_failed_probe_keys)
                    if not runner_error:
                        runner_error = (
                            "媒体库或订阅进度刷新重试仍失败，将由下一轮订阅刷新自愈"
                        )
                    self._logger.warning(runner_error)

                with self._media_sync_lock:
                    if generation != self._media_sync_generation:
                        return
                    if (
                            self._media_sync_requested
                            or self._media_sync_backfill
                            or self._media_sync_refresh_ids
                            or self._media_sync_probes
                        ):
                        retry_count = 0
                        continue
                    self._media_sync_running = False
                    self._media_sync_thread = None
                self._record_followup_status(
                    "media_server_sync",
                    started_at=started_at,
                    success=not runner_failed,
                    error=runner_error,
                    details={
                        "media_server_synced": media_server_synced,
                        "media_server_refresh_requested": media_server_refresh_requested,
                        "media_server_refreshed": media_server_refreshed,
                        "moviepilot_index_synced": moviepilot_index_synced,
                        "failed_media_probes": len(failed_probe_keys),
                        "successful_media_batches": successful_media_batches,
                        "failed_media_batches": failed_media_batches,
                        "all_media_batches_synced": (
                            successful_media_batches > 0
                            and failed_media_batches == 0
                        ),
                        "backfilled_subscriptions": len(completed_backfill_ids),
                        "refreshed_subscriptions": len(completed_refresh_ids),
                    },
                    generation=followup_generation,
                )
                break

        thread = threading.Thread(
            target=runner,
            name="lunatvsource-mediaserver-sync",
            daemon=True,
        )
        with self._media_sync_lock:
            if stop_event.is_set() or generation != self._media_sync_generation:
                self._media_sync_running = False
                return False
            self._media_sync_thread = thread
        try:
            thread.start()
        except Exception as exc:
            with self._media_sync_lock:
                if generation == self._media_sync_generation:
                    self._media_sync_running = False
                    self._media_sync_thread = None
            self._logger.warning("启动媒体服务器同步失败：%s", exc)
            self._record_followup_status(
                "media_server_sync",
                started_at=started_at,
                success=False,
                error=f"启动媒体服务器同步失败：{exc}",
                details={
                    "media_server_synced": False,
                    "media_server_refresh_requested": False,
                    "media_server_refreshed": False,
                    "moviepilot_index_synced": False,
                    "failed_media_probes": 0,
                    "successful_media_batches": 0,
                    "failed_media_batches": 0,
                    "all_media_batches_synced": False,
                    "backfilled_subscriptions": 0,
                    "refreshed_subscriptions": 0,
                },
                generation=followup_generation,
            )
            return False
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

    def _source_health_summary(self) -> Dict[str, Any]:
        sources = self._cached_source_catalog()
        payloads = [self._source_payload(source) for source in sources]
        with self._source_health_lock:
            running = self._source_health_running
            last_error = self._source_health_last_error
            last_finished = self._source_health_last_finished
            check_total = len(self._source_health_run_keys)
            checked = len(self._source_health_completed_keys)
        return {
            "interval_minutes": int(
                self._config.get("source_check_minutes")
                or DEFAULT_SOURCE_CHECK_MINUTES
            ),
            "running": running,
            "last_error": last_error,
            "last_finished": last_finished,
            "check_total": check_total,
            "checked": checked,
            "pending": max(0, check_total - checked),
            "last_checked": max(
                (float(item.get("last_checked") or 0) for item in payloads),
                default=0.0,
            ),
            "total": len(payloads),
            "enabled": sum(1 for item in payloads if item.get("enabled")),
            "disabled": sum(1 for item in payloads if not item.get("enabled")),
            "manual_disabled": sum(
                1 for item in payloads if item.get("manual_disabled")
            ),
            "auto_disabled": sum(
                1 for item in payloads if item.get("auto_disabled")
            ),
            "configured_disabled": sum(
                1 for item in payloads if item.get("disabled_reason") == "configured"
            ),
        }

    def api_status(self) -> Dict[str, Any]:
        queue = self._queue or DownloadQueue(
            lambda _key, default=None: default,
            lambda *_: None,
            self._notify,
        )
        directories = self._system_directory_infos()
        configured_root = str(self._config.get("download_root") or "").strip()
        source_health = self._source_health_summary()
        with self._media_sync_lock:
            media_server_sync_running = self._media_sync_running
        with self._followup_status_lock:
            followup_status = {
                key: dict(value) for key, value in self._followup_status.items()
            }
            current_refresh_generation = self._followup_generations.get(
                "subscription_refresh", 0
            )
            subscription_refresh_running = (
                current_refresh_generation in self._subscription_refresh_active
            )
        followup_status.setdefault("subscription_refresh", {})["running"] = (
            subscription_refresh_running
        )
        followup_status.setdefault("media_server_sync", {})["running"] = (
            media_server_sync_running
        )
        return {
            "success": True,
            "data": {
                "enabled": self._enabled,
                "queue": queue.summary(),
                "download_settings": {
                    "max_concurrent_tasks": self._config.get(
                        "max_concurrent_tasks",
                        DEFAULT_MAX_CONCURRENT_TASKS,
                    ),
                    "segment_thread_count": self._config.get(
                        "segment_thread_count",
                        DEFAULT_SEGMENT_THREAD_COUNT,
                    ),
                },
                "engine": queue.engine_status(),
                "subscription": {
                    "refresh_minutes": max(
                        5, int(self._config.get("poll_minutes") or 30)
                    ),
                },
                "ai": (self._ai or AiTitleNormalizer(False)).status(),
                "media_source": PLUGIN_MEDIA_SOURCE,
                "media_server_sync_running": media_server_sync_running,
                "followup_status": followup_status,
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
                "source_health": source_health,
            },
        }

    def api_sources(self) -> Dict[str, Any]:
        try:
            sources = self._cached_source_catalog()
            return {
                "success": True,
                "data": [self._source_payload(source) for source in sources],
            }
        except Exception as exc:
            return {"success": False, "message": f"读取 LunaTV 配置失败：{exc}", "data": []}

    def api_source_refresh(
        self, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self._enabled:
            return {
                "success": False,
                "message": "请先启用 LunaTV 插件",
                "data": {"started": False, "running": False},
            }
        source_key = str((payload or {}).get("source_key") or "").strip().lower()
        started = self._start_source_health_refresh(source_key)
        with self._source_health_lock:
            running = self._source_health_running
        if not started and not running:
            return {
                "success": False,
                "message": "来源健康检查启动失败",
                "data": {"started": False, "running": False},
            }
        return {
            "success": True,
            "message": "来源健康检查已启动" if started else "来源健康检查正在运行",
            "data": {"started": started, "running": running},
        }

    def api_source_state(
        self, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = payload or {}
        source_key = str(payload.get("source_key") or "").strip().lower()
        if not source_key or "enabled" not in payload:
            return {
                "success": False,
                "message": "请提供来源标识和启用状态",
                "data": {},
            }
        source = next(
            (
                item
                for item in self._cached_source_catalog()
                if item.key.lower() == source_key
            ),
            None,
        )
        if source is None:
            return {"success": False, "message": "来源不存在", "data": {}}
        enabled = _bool(payload.get("enabled"), False)
        with self._source_health_lock:
            record = dict(self._source_health.get(source_key) or {})
            if record and str(record.get("api") or "") != source.api:
                record = {}
            manual_disabled = not enabled
            generation = self._source_health_generation(record)
            if bool(record.get("manual_disabled")) != manual_disabled:
                generation += 1
            if enabled and bool(record.get("manual_disabled")):
                record.update(
                    {
                        "health_status": "unchecked",
                        "last_checked": 0.0,
                        "last_error": "",
                        "failures": 0,
                    }
                )
            record.update(
                {
                    "api": source.api,
                    "manual_disabled": manual_disabled,
                    "generation": generation,
                }
            )
            try:
                self._persist_source_health_locked({source_key: record})
            except Exception as exc:
                return {
                    "success": False,
                    "message": f"保存来源状态失败：{self._source_health_error(exc)}",
                    "data": {},
                }
        started = self._start_source_health_refresh(source_key) if enabled else False
        if not enabled:
            message = "来源已永久禁用"
        elif started:
            message = "来源已启用并开始检查"
        elif not self._enabled:
            message = "来源状态已保存；插件启用后将自动检查"
        else:
            message = "来源状态已保存，但检查未能启动"
        return {
            "success": True,
            "message": message,
            "data": {
                "source": self._source_payload(source),
                "check_started": started,
            },
        }

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
            client = self._client()
            results = self._season_media_cards(
                self._filter_currently_searchable_results(
                    client.search(
                        search_query,
                        stop_after_first_source=True,
                        expand_tv_episode_rows=True,
                    ),
                    client,
                )
            )
            data = []
            for result in results:
                item = self._result_payload(result)
                if result.media_type == "tv":
                    seasons = sorted(
                        {
                    int(episode.season if episode.season is not None else 1)
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
            client = self._client()
            results = self._filter_currently_searchable_results(
                client.search(
                    search_query,
                    limit=max(1, min(int(count or 30), 50)),
                    stop_after_first_source=True,
                    # 探索页只展示元数据；播放地址在原生资源搜索/下载时再读取。
                    # 避免列表结果缺少 vod_play_url 时逐条请求详情，导致界面长时间骨架屏。
                    enrich=False,
                ),
                client,
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
        if self._queue is None:
            return {"success": True, "data": []}
        raw_tasks = self._queue.list_tasks()
        self._sweep_download_metrics(raw_tasks)
        tasks: List[Dict[str, Any]] = []
        for raw_task in raw_tasks:
            try:
                tasks.append(DownloadTask(**raw_task).public_dict())
            except (TypeError, ValueError):
                continue
        return {"success": True, "data": tasks}

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
            root = self._effective_root(media_type=media_type)
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
        season_value = episode_payload.get("season")
        if season_value in (None, ""):
            season_value = payload.get("season")
        episode = CmsEpisode(
            season=int(season_value) if season_value not in (None, "") else 1,
            episode=int(episode_payload.get("episode") or payload.get("episode") or 1),
            label=str(episode_payload.get("label") or ""),
            url=url,
            season_known=bool(episode_payload.get("season_known", True)),
        )
        media_type = _media_type_value(payload.get("media_type") or "tv")
        root = self._effective_root(media_type=media_type)
        if not root:
            return {"success": False, "message": "未找到下载目录，请先配置插件目录或 MoviePilot 目录设置", "data": {}}
        media_id = str(payload.get("media_id") or payload.get("vod_id") or "").strip()
        if not media_id:
            normalized_url = parsed._replace(
                scheme=parsed.scheme.lower(),
                netloc=parsed.netloc.lower(),
                path=parsed.path or "/",
                fragment="",
            ).geturl()
            media_id = f"manual:{hashlib.sha256(normalized_url.encode('utf-8')).hexdigest()}"
        task = DownloadTask.from_episode(
            episode,
            title=normalize_media_title(str(payload.get("title") or "未命名")),
            year=str(payload.get("year") or ""),
            media_type=media_type,
            root=root,
            mode=str(payload.get("mode") or self._config.get("mode") or "download"),
            ffmpeg_path=str(self._config.get("ffmpeg_path") or "ffmpeg"),
            source_sensitive=True,
            media_source="lunatv",
            media_id=media_id,
        )
        if not queue.enqueue(task):
            return {"success": False, "message": "任务重复，或未配置下载目录", "data": {}}
        self._start_queue()
        return {"success": True, "message": "已加入下载队列", "data": {"task_id": task.task_id}}

    def _record_completion(self, task: DownloadTask, output: str) -> None:
        self._remember_completed_download_size(task, output)
        self._clear_download_metrics(getattr(task, "task_id", ""))
        replayed = bool(self._config.get("moviepilot_organize", True)) and (
            self._native_history_has_episode(task)
        )
        organized = False
        if replayed:
            self._logger.info(
                "LunaTV 完成回调重放：原生下载历史已存在，跳过重复整理 task=%s",
                getattr(task, "task_id", ""),
            )
        elif self._config.get("moviepilot_organize", True):
            try:
                transfer_result = self._native_transfer(task, output)
                organized = transfer_result == "moviepilot"
                if transfer_result.startswith("fallback:"):
                    self._logger.warning(
                        "LunaTV 下载完成但未整理，文件保留在 %s：%s",
                        output,
                        transfer_result.removeprefix("fallback:"),
                    )
            except Exception as exc:
                # The host may finish a move and then lose its response. Keep
                # the durable completion/history path running so a later
                # subscription refresh cannot download the same episode again.
                self._logger.warning(
                    "MoviePilot 原生整理返回异常，继续记录下载完成：%s", exc
                )
            finally:
                self._remove_empty_download_parents(task, output)
        # 下载历史始终记录 ffmpeg 的原始产物。若原生整理成功，TransferChain
        # 会自行记录 TransferHistory；这里不能把整理目标伪装成下载源文件。
        self._record_native_history(task, output)
        media_probe = (
            {
                "media_type": getattr(task, "media_type", None),
                "title": getattr(task, "title", None),
                "year": getattr(task, "year", None),
                "season": getattr(task, "season", None),
                "episode": getattr(task, "episode", None),
            }
            if organized
            else None
        )
        subscription_ids = self._native_subscription_ids(task)
        if subscription_ids:
            sync_args = (
                subscription_ids,
                getattr(task, "episode", None) if organized else None,
            )
            if media_probe:
                self._sync_media_server(*sync_args, media_probe=media_probe)
            else:
                self._sync_media_server(*sync_args)
        elif media_probe:
            self._sync_media_server(media_probe=media_probe)
        else:
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
        self._clear_download_metrics(task_id)
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

    @staticmethod
    def _subscription_result_matches(
        result: CmsResult,
        association: Dict[str, Any],
        *,
        title: str,
        year: str,
        identity_source: str,
        identity_id: str,
        expected_identity: Optional[Tuple[str, str]] = None,
    ) -> bool:
        """Reject a different work before freshness/quality ranking."""

        if identity_source == PLUGIN_MEDIA_SOURCE and ":" in identity_id:
            source_key, vod_id = identity_id.split(":", 1)
            if result.source_key == source_key and result.vod_id == vod_id:
                return True

        association_source = _coerce_media_identity_source(
            association.get("media_source")
        )
        association_id = str(
            association.get("media_id") or association.get("tmdb_id") or ""
        ).strip()
        if (
            expected_identity
            and association.get("status") == "matched"
            and association_source
            and association_id
        ):
            return (association_source, association_id) == expected_identity

        requested_title = normalize_search_title(title).casefold()
        result_title = normalize_search_title(result.title).casefold()
        if requested_title and result_title and requested_title != result_title:
            return False

        requested_year = re.search(r"(?:19|20)\d{2}", str(year or ""))
        result_year = re.search(r"(?:19|20)\d{2}", str(result.year or ""))
        if (
            requested_year
            and result_year
            and requested_year.group(0) != result_year.group(0)
        ):
            return False
        return True

    @staticmethod
    def _subscription_episode_bounds(
        subscribe: Any,
        association: Dict[str, Any],
        season: int,
    ) -> Tuple[int, int]:
        """Mirror MoviePilot's start/manual-total episode boundaries."""

        try:
            start_episode = max(1, int(getattr(subscribe, "start_episode", 1) or 1))
        except (TypeError, ValueError):
            start_episode = 1
        try:
            total_episode = max(0, int(getattr(subscribe, "total_episode", 0) or 0))
        except (TypeError, ValueError):
            total_episode = 0

        manual_value = getattr(subscribe, "manual_total_episode", False)
        manual_total = manual_value is True or str(manual_value).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not manual_total:
            season_counts = association.get("season_counts") or {}
            if isinstance(season_counts, dict):
                try:
                    media_total = int(
                        season_counts.get(season, season_counts.get(str(season), 0))
                        or 0
                    )
                except (TypeError, ValueError):
                    media_total = 0
                total_episode = max(total_episode, media_total)
        return start_episode, total_episode

    def refresh_subscriptions(self) -> Dict[str, Any]:
        started_at = time.time()
        with self._followup_status_lock:
            self._followup_generations["subscription_refresh"] += 1
            followup_generation = self._followup_generations[
                "subscription_refresh"
            ]
            self._subscription_refresh_active.add(followup_generation)
        try:
            result = self._refresh_subscriptions_once()
        except Exception as exc:
            self._record_followup_status(
                "subscription_refresh",
                started_at=started_at,
                success=False,
                error=str(exc),
                generation=followup_generation,
            )
            raise
        else:
            error = str(result.get("error") or "")
            self._record_followup_status(
                "subscription_refresh",
                started_at=started_at,
                success=not error,
                error=error,
                details={
                    key: int(result.get(key) or 0)
                    for key in (
                        "subscriptions",
                        "queued",
                "reconciled",
                "skipped_ambiguous",
                "skipped_no_directory",
                "unrefreshed_subscriptions",
            )
        },
        generation=followup_generation,
            )
            return result
        finally:
            with self._followup_status_lock:
                self._subscription_refresh_active.discard(followup_generation)

    def _refresh_subscriptions_once(self) -> Dict[str, Any]:
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
            state = str(
                getattr(
                    getattr(subscribe, "state", None),
                    "value",
                    getattr(subscribe, "state", "R"),
                )
                or "R"
            ).strip().lower()
            if state not in {"r", "p", "1", "active", "enabled"}:
                continue
            active_subscribes.append(subscribe)
        native_progress_ids: set[int] = set()
        native_progress_episodes: Dict[int, set[int]] = {}
        for subscribe in active_subscribes:
            subscribe_id = 0
            if _media_type_value(getattr(subscribe, "type", "")) == "tv":
                try:
                    subscribe_id = int(getattr(subscribe, "id", 0) or 0)
                except (TypeError, ValueError):
                    subscribe_id = 0
                if subscribe_id:
                    native_progress_ids.add(subscribe_id)
            title = str(getattr(subscribe, "name", "") or getattr(subscribe, "keyword", "")).strip()
            if not title:
                continue
            normalized_title = title
            raw_subscription_season = getattr(subscribe, "season", 0)
            try:
                subscription_season = int(raw_subscription_season or 0)
            except (TypeError, ValueError):
                parsed_seasons = self._history_numbers(raw_subscription_season)
                subscription_season = min(parsed_seasons) if parsed_seasons else 0
            subscription_type = getattr(
                getattr(subscribe, "type", None),
                "value",
                getattr(subscribe, "media_type", getattr(subscribe, "type", "")),
            )
            is_season_subscription = (
                subscription_season > 0
                and _media_type_value(subscription_type) == "tv"
            )
            try:
                identity_source = _coerce_media_identity_source(getattr(subscribe, "media_source", ""))
                identity_id = str(getattr(subscribe, "media_id", "") or "").strip()
                is_plugin_season = (
                    identity_source == PLUGIN_MEDIA_SOURCE
                    and subscription_season > 0
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
                    results = client.search(
                        search_query,
                        expand_tv_episode_rows=True,
                        max_workers=8,
                    )
                results = self._filter_currently_searchable_results(results, client)
                prepared_results = []
                for result in results:
                    prepared, association = self._prepare_result(result)
                    prepared_results.append((prepared, association))
                expected_identity: Optional[Tuple[str, str]] = None
                if identity_source != PLUGIN_MEDIA_SOURCE and identity_id:
                    expected_identity = (identity_source, identity_id)
                elif identity_source == PLUGIN_MEDIA_SOURCE and ":" in identity_id:
                    source_key, vod_id = identity_id.split(":", 1)
                    for prepared, association in prepared_results:
                        if prepared.source_key != source_key or prepared.vod_id != vod_id:
                            continue
                        association_source = _coerce_media_identity_source(
                            association.get("media_source")
                        )
                        association_id = str(
                            association.get("media_id")
                            or association.get("tmdb_id")
                            or ""
                        ).strip()
                        if (
                            association.get("status") == "matched"
                            and association_source
                            and association_id
                        ):
                            expected_identity = (
                                association_source,
                                association_id,
                            )
                        break
                if is_season_subscription:
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
            target_type = (
                _media_type_value(target_type)
                if _enum_value(target_type)
                else ""
            )
            season = subscription_season
            matching_results = []
            for result, association in results:
                if target_type and result.media_type and target_type not in {result.media_type, "电视剧" if result.media_type == "tv" else "电影"}:
                    continue
                if not self._subscription_result_matches(
                    result,
                    association,
                    title=normalized_title,
                    year=str(getattr(subscribe, "year", "") or ""),
                    identity_source=identity_source,
                    identity_id=identity_id,
                    expected_identity=expected_identity,
                ):
                    self._logger.debug(
                        "跳过订阅身份不匹配的 LunaTV 结果：subscription=%s result=%s (%s)",
                        normalized_title,
                        result.title,
                        result.year,
                    )
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
                    subscribe=subscribe,
                )
                matching_results = matching_results[:1]
            if is_season_subscription:
                selected_results: List[Tuple[CmsResult, Dict[str, Any]]] = []
                ambiguous_results: List[Tuple[CmsResult, Dict[str, Any]]] = []
                for result, association in matching_results:
                    if result.season_ambiguous:
                        ambiguous_results.append((result, association))
                        continue

                    episode_candidates: Dict[Tuple[int, int], List[CmsEpisode]] = {}
                    start_episode, total_episode = self._subscription_episode_bounds(
                        subscribe,
                        association,
                        season,
                    )
                    for episode in result.episodes:
                        if season > 0 and episode.season != season:
                            continue
                        if episode.episode < start_episode:
                            continue
                        if total_episode > 0 and episode.episode > total_episode:
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
                result_episodes = result.episodes
                if result.media_type == "movie" and len(result_episodes) > 1:
                    heights = self._probe_resource_urls(
                        [episode.url for episode in result_episodes if episode.url]
                    )
                    _, best_episode = max(
                        enumerate(result_episodes),
                        key=lambda item: (
                            heights.get(item[1].url, 0),
                            -item[0],
                        ),
                    )
                    result_episodes = (best_episode,)
                for episode in result_episodes:
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
                        source_sensitive=False,
                        media_source=(
                            result.source_key or PLUGIN_MEDIA_SOURCE
                            if str(self._config.get("source_strategy") or "first")
                            == "all"
                            else PLUGIN_MEDIA_SOURCE
                        ),
                        media_id=(
                            identity_id
                            if is_plugin_season
                            and (
                                str(
                                    self._config.get("source_strategy") or "first"
                                )
                                != "all"
                                or identity_id.partition(":")[0]
                                == result.source_key
                            )
                            else f"{result.source_key}:{result.vod_id}"
                        ),
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
                        try:
                            task.downloaded_bytes = max(0, existing_path.stat().st_size)
                        except OSError:
                            task.downloaded_bytes = 0
                        queue.reconcile_completed(task, output=str(existing_path))
                        reconciled += 1
                        if subscribe_id and int(task.episode or 0) > 0:
                            native_progress_episodes.setdefault(
                                subscribe_id, set()
                            ).add(int(task.episode))
                        continue
                    if self._native_history_has_episode(task):
                        queue.reconcile_completed(task)
                        reconciled += 1
                        if subscribe_id and int(task.episode or 0) > 0:
                            native_progress_episodes.setdefault(
                                subscribe_id, set()
                            ).add(int(task.episode))
                        continue
                    with self._source_health_lock:
                        expected_revision = getattr(
                            client, "_lunatv_health_revision", None
                        )
                        source_still_enabled = (
                            expected_revision is None
                            or (
                                self._source_health_revision == expected_revision
                                and result.source_key.lower()
                                in self._current_searchable_source_keys()
                            )
                        )
                        enqueued = source_still_enabled and queue.enqueue(task)
                    if enqueued:
                        queued += 1
        if queued:
            self._start_queue()
        unrefreshed_subscriptions: set[int] = set()
        if native_progress_ids:
            if _HostMediaServerChain is None:
                handled_ids = (
                    self._backfill_native_subscription_progress(
                        native_progress_episodes
                    )
                    or set()
                )
                remaining_ids = set(native_progress_ids).difference(handled_ids)
                if remaining_ids:
                    refreshed_ids = (
                        self._refresh_native_subscription_progress(remaining_ids)
                        or set()
                    )
                    unrefreshed_subscriptions = remaining_ids.difference(
                        refreshed_ids
                    )
            else:
                # MoviePilot may perform media recognition and library queries while
                # backfilling subscription progress. Keep that work on the existing
                # coalescing media-sync worker so a slow host lookup cannot leave the
                # subscription refresh UI stuck in "running" after search is done.
                try:
                    self._sync_media_server(
                        native_progress_ids,
                        episodes_by_subscription=native_progress_episodes,
                    )
                except TypeError as exc:
                    # Keep compatibility with older host/test adapters that only
                    # accept the original positional subscription-id argument.
                    if "episodes_by_subscription" not in str(exc):
                        raise
                    self._sync_media_server(native_progress_ids)

        result = {
            "subscriptions": len(active_subscribes),
            "queued": queued,
            "reconciled": reconciled,
            "skipped_ambiguous": skipped_ambiguous,
            "skipped_no_directory": skipped_no_directory,
        }
        if unrefreshed_subscriptions:
            result["unrefreshed_subscriptions"] = len(unrefreshed_subscriptions)
            result["error"] = (
                "MoviePilot 未能刷新 "
                f"{len(unrefreshed_subscriptions)} 个订阅进度"
            )
        return result

    def run_queue(self) -> Dict[str, Any]:
        if not self._queue:
            return {"processed": 0}
        return {"processed": 0, "scheduled": self._queue.wake()}

    def _start_queue(self) -> bool:
        """立即唤醒下载队列，避免原生继续操作等待下个定时周期。"""
        queue = self._queue
        if queue is None:
            return False
        return queue.wake()

    def get_media_source(self) -> List[Dict[str, Any]]:
        """LunaTV participates in the global search instead of adding an empty Explore tab."""
        return []

    def _active_download_torrent(
        self, task: DownloadTask, *, finalizing: bool = False
    ) -> Any:
        """将队列中的活跃任务归一为 MoviePilot 下载器任务。"""
        media_source, media_id = self._task_media_identity(task)
        size, dlspeed = self._active_download_metrics(task)
        task_state = str(task.state or "").strip().lower()
        display_state = {
            "paused": "paused",
            "failed": "failed",
        }.get(task_state, "downloading")
        download_engine = str(getattr(task, "download_engine", "") or "").strip()
        site_name = task.source_name or task.source_key or PLUGIN_MEDIA_SOURCE
        if download_engine:
            site_name = f"{site_name} · {download_engine}"
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
            "site_name": site_name,
            "year": task.year or None,
            "season_episode": season_episode,
            "state": display_state,
            # Queue persistence uses a 0..1 fraction; MoviePilot's
            # DownloaderTorrent contract expects a 0..100 percentage.
            "progress": (
                99.0
                if finalizing
                else max(
                    0.0,
                    min(
                        100.0,
                        float(getattr(task, "progress", 0.0) or 0.0) * 100.0,
                    ),
                )
            ),
            "size": size,
            "dlspeed": dlspeed,
            "upspeed": None,
            "save_path": task.root or None,
            "left_time": (
                "下载失败"
                if task_state == "failed"
                else "下载完成，正在整理" if finalizing else None
            ),
            "media": {
                "type": "电视剧" if task.media_type == "tv" else "电影",
                "title": task.title,
                "season": task.season if task.media_type == "tv" else None,
                "episode": task.episode if task.media_type == "tv" else None,
                "media_source": self._host_media_source_value(media_source),
                "media_id": media_id or None,
            },
        }
        return self._downloader_torrent(values)

    def _downloader_torrent(self, values: Dict[str, Any]) -> Any:
        """使用宿主模型构造下载任务；独立测试环境回退为兼容对象。"""
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
    def _tv_season_group_key(task: DownloadTask) -> Optional[Tuple[str, ...]]:
        """返回整季任务的稳定分组键；电影不参与聚合。"""
        if str(task.media_type or "").strip().casefold() != "tv":
            return None
        try:
            season = str(int(task.season))
        except (TypeError, ValueError):
            season = str(task.season or "")
        host_source = str(task.host_media_source or "").strip().casefold()
        host_id = str(task.host_media_id or "").strip()
        media_identity = (
            f"{host_source}:{host_id}"
            if host_source and host_id
            else str(task.media_id or "").strip()
        )
        if not media_identity:
            media_identity = "|".join(
                (
                    str(task.host_media_source or "").strip(),
                    str(task.host_media_id or "").strip(),
                    str(task.title or "").strip(),
                    str(task.year or "").strip(),
                )
            )
        return (
            str(task.source_key or "").strip(),
            media_identity,
            season,
            str(task.mode or "").strip(),
            str(task.root or "").strip(),
        )

    @staticmethod
    def _download_speed_bytes(value: Optional[str]) -> float:
        """把插件自身的 B/K/M/G 速度文本还原为字节数，供整季求和。"""
        match = re.fullmatch(
            r"\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?)(?:B)?(?:/S)?\s*",
            str(value or "").upper(),
        )
        if not match:
            return 0.0
        unit = match.group(2)
        factor = {"": 1.0, "K": 1024.0, "M": 1024.0**2, "G": 1024.0**3, "T": 1024.0**4}
        return float(match.group(1)) * factor[unit]

    def _active_tv_season_torrent(
        self,
        tasks: List[DownloadTask],
        *,
        finalizing_task_ids: Optional[set[str]] = None,
    ) -> Any:
        """把同一电视剧、同一季的逐集执行单元投影成一个原生下载任务。"""
        finalizing_task_ids = finalizing_task_ids or set()
        active_states = {"pending", "running", "paused", "failed"}
        active_tasks = [
            task
            for task in tasks
            if str(task.state or "").lower() in active_states
            or str(task.task_id or "") in finalizing_task_ids
        ]
        if not active_tasks:
            raise ValueError("整季没有活跃下载任务")
        representative = next(
            (
                task
                for state in ("running", "pending", "paused")
                for task in active_tasks
                if str(task.state or "").lower() == state
            ),
            active_tasks[0],
        )
        try:
            season_number = int(representative.season)
        except (TypeError, ValueError):
            season_number = representative.season
        season_text = f"第{season_number}季"
        total_count = len(tasks)
        completed_count = sum(
            1
            for task in tasks
            if str(task.state or "").lower() == "completed"
            and str(task.task_id or "") not in finalizing_task_ids
        )
        progress_units = 0.0
        total_size = 0.0
        total_speed = 0.0
        finalizing_count = 0
        for task in tasks:
            task_state = str(task.state or "").lower()
            is_finalizing = str(task.task_id or "") in finalizing_task_ids
            if is_finalizing:
                progress_units += 0.99
                finalizing_count += 1
                total_size += self._completed_download_size(task)
            elif task_state == "completed":
                progress_units += 1.0
                total_size += self._completed_download_size(task)
            else:
                task_progress = max(
                    0.0,
                    min(1.0, float(getattr(task, "progress", 0.0) or 0.0)),
                )
                progress_units += task_progress
                if task_state == "running" and task_progress >= 0.99:
                    finalizing_count += 1
            if task_state in active_states:
                size, dlspeed = self._active_download_metrics(task)
                total_size += max(0.0, float(size or 0.0))
                total_speed += self._download_speed_bytes(dlspeed)

        detail = f"{season_text} · 共{total_count}集 · 已下载{completed_count}/{total_count}"
        media_source, media_id = self._task_media_identity(representative)
        download_engine = next(
            (
                str(getattr(task, "download_engine", "") or "").strip()
                for task in active_tasks + tasks
                if str(getattr(task, "download_engine", "") or "").strip()
            ),
            "",
        )
        site_name = (
            representative.source_name
            or representative.source_key
            or PLUGIN_MEDIA_SOURCE
        )
        if download_engine:
            site_name = f"{site_name} · {download_engine}"
        failed_count = sum(
            1
            for task in active_tasks
            if str(task.state or "").lower() == "failed"
        )
        group_state = (
            "downloading"
            if finalizing_task_ids
            or any(str(task.state or "").lower() in {"pending", "running"} for task in active_tasks)
            else "failed" if failed_count == len(active_tasks) else "paused"
        )
        projected_progress = max(
            0.0,
            min(100.0, progress_units * 100.0 / total_count),
        )
        if completed_count < total_count:
            projected_progress = min(99.0, projected_progress)
        left_time = (
            f"下载失败 {failed_count} 集"
            if group_state == "failed"
            else f"已下载 {completed_count}/{total_count} 集"
        )
        if finalizing_count == 1:
            left_time += (
                f" · 正在整理第 {min(total_count, completed_count + 1)}/{total_count} 集"
            )
        elif finalizing_count > 1:
            left_time += f" · 正在整理 {finalizing_count} 集"

        values = {
            "downloader": "LunaTVSource",
            # 使用一个真实成员 ID，原生控制接口收到后会扩展到整季全部成员。
            "hash": str(active_tasks[0].task_id),
            "title": f"{representative.title} {season_text}（共{total_count}集）",
            "name": representative.title,
            "site_name": site_name,
            "year": representative.year or None,
            "season_episode": detail,
            "state": group_state,
            "progress": projected_progress,
            "size": total_size,
            "dlspeed": self._format_download_speed(total_speed),
            "upspeed": None,
            "save_path": representative.root or None,
            "left_time": left_time,
            "media": {
                "type": "电视剧",
                "title": representative.title,
                "season": detail,
                "episode": None,
                "media_source": self._host_media_source_value(media_source),
                "media_id": media_id or None,
            },
        }
        return self._downloader_torrent(values)

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

    def _clear_download_metrics(self, *task_ids: Any) -> None:
        ids = {str(task_id).strip() for task_id in task_ids if str(task_id).strip()}
        if not ids:
            return
        with self._download_metrics_lock:
            for task_id in ids:
                self._download_metrics.pop(task_id, None)

    def _remember_completed_download_size(
        self, task: DownloadTask, output: str
    ) -> None:
        task_id = str(getattr(task, "task_id", "") or "").strip()
        if not task_id:
            return
        try:
            root = Path(task.root).expanduser().resolve()
            path = Path(output).expanduser().resolve()
            info = path.lstat()
            if root not in path.parents or path.is_symlink() or not path.is_file():
                return
            size = max(0, int(info.st_size))
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        with self._download_metrics_lock:
            self._completed_download_sizes[task_id] = size

    def _completed_download_size(self, task: DownloadTask) -> float:
        task_id = str(getattr(task, "task_id", "") or "").strip()
        try:
            persisted_size = max(0, int(getattr(task, "downloaded_bytes", 0) or 0))
        except (TypeError, ValueError):
            persisted_size = 0
        if persisted_size:
            return float(persisted_size)
        with self._download_metrics_lock:
            cached = self._completed_download_sizes.get(task_id)
        if cached is not None:
            return float(cached)
        output = str(getattr(task, "output", "") or "").strip()
        if output:
            self._remember_completed_download_size(task, output)
            with self._download_metrics_lock:
                return float(self._completed_download_sizes.get(task_id, 0))
        return 0.0

    @staticmethod
    def _remove_empty_download_parents(task: DownloadTask, output: str) -> None:
        """Remove only empty source directories after MoviePilot moved a file."""
        try:
            root = Path(task.root).expanduser().resolve()
            path = Path(output).expanduser().resolve()
            if root not in path.parents or path.exists():
                return
            current = path.parent
            while current != root and root in current.parents:
                current.rmdir()
                current = current.parent
        except (OSError, RuntimeError, TypeError, ValueError):
            return

    def _sweep_download_metrics(self, raw_tasks: List[Any]) -> None:
        known_task_ids = {
            str(item.get("task_id") or "").strip()
            for item in raw_tasks
            if isinstance(item, dict) and str(item.get("task_id") or "").strip()
        }
        live_task_ids = {
            str(item.get("task_id") or "").strip()
            for item in raw_tasks
            if isinstance(item, dict)
            and str(item.get("task_id") or "").strip()
            and str(item.get("state") or "").strip().lower()
            not in {"completed", "failed"}
        }
        with self._download_metrics_lock:
            for task_id in list(self._download_metrics):
                if task_id not in live_task_ids:
                    self._download_metrics.pop(task_id, None)
            for task_id in list(self._completed_download_sizes):
                if task_id not in known_task_ids:
                    self._completed_download_sizes.pop(task_id, None)

    def _active_download_metrics(self, task: DownloadTask) -> Tuple[float, Optional[str]]:
        """Project safe task-owned bytes and a rolling 20-second download speed."""
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

        # N_m3u8DL-RE writes its live bytes into a queue-controlled cache/stage
        # directory rather than the final ``.part`` path.  The queue owns the
        # path validation, so this never scans a task-provided root or arbitrary
        # filesystem location.
        if str(getattr(task, "download_engine", "") or "").strip().casefold() == "n_m3u8dl-re":
            queue = self._queue
            cache_size = getattr(queue, "task_cache_size", None)
            if callable(cache_size):
                try:
                    current_size = max(current_size, max(0, int(cache_size(task.task_id))))
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass

        now = time.monotonic()
        speed = 0.0
        task_id = str(task.task_id or "")
        with self._download_metrics_lock:
            samples = self._download_metrics.setdefault(task_id, deque())
            # A restarted/truncated file is a new transfer: never retain the
            # old larger byte count, which would otherwise produce a negative
            # or inflated speed.
            if samples and current_size < samples[-1][1]:
                samples.clear()
            samples.append((now, current_size))
            while samples and now - samples[0][0] > 20.0:
                samples.popleft()
            if len(samples) > 1:
                first_time, first_size = samples[0]
                if current_size >= first_size and now > first_time:
                    speed = (current_size - first_size) / (now - first_time)

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
        # 原生下载页按当前客户端名称分栏；LunaTV 任务只投影到自己的标签。
        if not self._is_lunatv_downloader(downloader):
            # None 让插件不参与该客户端投影，宿主仍会继续查询系统下载器。
            return None

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
        self._sweep_download_metrics(raw_tasks)
        finalizing_reader = getattr(queue, "finalizing_task_ids", None)
        try:
            finalizing_task_ids = (
                set(finalizing_reader()) if callable(finalizing_reader) else set()
            )
        except Exception:
            finalizing_task_ids = set()

        tasks: List[DownloadTask] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                continue
            try:
                task = DownloadTask(**raw_task)
            except TypeError:
                continue
            task_hash = str(task.task_id or "").strip()
            if not task_hash:
                continue
            tasks.append(task)

        tv_groups: Dict[Tuple[str, ...], List[DownloadTask]] = {}
        for task in tasks:
            group_key = self._tv_season_group_key(task)
            if group_key is not None:
                tv_groups.setdefault(group_key, []).append(task)

        torrents: List[Any] = []
        emitted_groups = set()
        for task in tasks:
            task_hash = str(task.task_id or "").strip()
            task_state = str(task.state or "").lower()
            group_key = self._tv_season_group_key(task)
            if group_key is not None:
                if group_key in emitted_groups:
                    continue
                emitted_groups.add(group_key)
                group_tasks = tv_groups[group_key]
                active_tasks = [
                    item
                    for item in group_tasks
                    if str(item.state or "").lower()
                    in {"pending", "running", "paused", "failed"}
                    or str(item.task_id or "") in finalizing_task_ids
                ]
                if not active_tasks:
                    continue
                member_hashes = {str(item.task_id or "").strip() for item in group_tasks}
                if requested_hashes and not requested_hashes.intersection(member_hashes):
                    continue
                torrent = self._active_tv_season_torrent(
                    group_tasks,
                    finalizing_task_ids=finalizing_task_ids,
                )
                if (
                    not requested_hashes
                    and status_value in {"paused", "pause", "暂停", "已暂停"}
                    and torrent.state != "paused"
                ):
                    continue
                torrents.append(torrent)
                continue

            is_finalizing = task_hash in finalizing_task_ids
            if task_state not in {"pending", "running", "paused", "failed"} and not is_finalizing:
                continue
            if requested_hashes and task_hash not in requested_hashes:
                continue
            if (
                not requested_hashes
                and status_value in {"paused", "pause", "暂停", "已暂停"}
                and task_state != "paused"
            ):
                continue
            torrents.append(
                self._active_download_torrent(task, finalizing=is_finalizing)
            )
        return torrents

    def downloader_info(
        self, downloader: Optional[str] = None
    ) -> Optional[List[Any]]:
        """向 MoviePilot 首页汇总 LunaTV 活跃任务的下载统计。"""
        if not self._enabled or not self._is_lunatv_downloader(downloader):
            return None

        download_speed = 0.0
        download_size = 0.0
        try:
            raw_tasks = self._queue.list_tasks() if self._queue else []
        except Exception as exc:
            self._logger.debug("读取 LunaTV 首页下载统计失败：%s", exc)
            raw_tasks = []
        for raw_task in raw_tasks:
            try:
                task = (
                    raw_task
                    if isinstance(raw_task, DownloadTask)
                    else DownloadTask(**raw_task)
                )
            except TypeError:
                continue
            state = str(task.state or "").strip().casefold()
            if state in {"pending", "running", "paused"}:
                _, dlspeed = self._active_download_metrics(task)
                download_speed += self._download_speed_bytes(dlspeed)
                with self._download_metrics_lock:
                    samples = self._download_metrics.get(str(task.task_id or ""))
                    if samples:
                        download_size += max(0.0, float(samples[-1][1]))
            elif state == "completed":
                download_size += self._completed_download_size(task)

        values = {
            "download_speed": download_speed,
            "upload_speed": 0.0,
            "download_size": download_size,
            "upload_size": 0.0,
            "free_space": 0.0,
        }
        info_type = (
            getattr(_schemas, "DownloaderInfo", None)
            if _schemas is not None
            else None
        )
        if callable(info_type):
            try:
                return [info_type(**values)]
            except Exception as exc:
                self._logger.debug(
                    "构造 MoviePilot 下载器统计失败，使用兼容对象：%s", exc
                )
        return [_CompatDownloaderTorrent(**values)]

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
            raw_tasks = queue.list_tasks()
        except Exception:
            return None
        tasks: List[DownloadTask] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                continue
            try:
                tasks.append(DownloadTask(**raw_task))
            except TypeError:
                continue
        by_id = {str(task.task_id or ""): task for task in tasks}
        expanded: List[str] = []
        for task_id in requested:
            task = by_id.get(task_id)
            if task is None:
                return None
            group_key = self._tv_season_group_key(task)
            members = (
                [item for item in tasks if self._tv_season_group_key(item) == group_key]
                if group_key is not None
                else [task]
            )
            for member in members:
                member_state = str(member.state or "").lower()
                if operation == "resume" and member_state not in {"paused", "failed"}:
                    continue
                if operation == "pause" and member_state not in {"pending", "running", "paused"}:
                    continue
                member_id = str(member.task_id or "").strip()
                if member_id and member_id not in expanded:
                    expanded.append(member_id)
        if not expanded:
            return False
        if operation == "remove":
            finalizing_reader = getattr(queue, "finalizing_task_ids", None)
            try:
                finalizing_ids = (
                    set(finalizing_reader()) if callable(finalizing_reader) else set()
                )
            except Exception:
                finalizing_ids = set()
            if finalizing_ids.intersection(expanded):
                return False
        batch_handler = getattr(queue, "control_many", None)
        if callable(batch_handler):
            handled = bool(
                batch_handler(expanded, operation, delete_file=delete_file)
            )
            if handled and operation == "remove":
                self._clear_download_metrics(*expanded)
            return handled
        handler = getattr(queue, operation, None)
        if not callable(handler):
            return False
        if operation == "remove":
            removed_ids = [
                task_id
                for task_id in expanded
                if handler(task_id, delete_file=delete_file)
            ]
            self._clear_download_metrics(*removed_ids)
            return len(removed_ids) == len(expanded)
        results = [bool(handler(task_id)) for task_id in expanded]
        return all(results)

    @staticmethod
    def _is_lunatv_downloader(downloader: Optional[str]) -> bool:
        """未指定下载器时参与聚合；指定时只响应 LunaTV 标签页。"""
        return downloader is None or str(downloader).strip().casefold() in {
            "",
            "lunatvsource",
        }

    def start_torrents(
        self, hashs: Any, downloader: Optional[str] = None
    ) -> Optional[bool]:
        """Continue paused LunaTV tasks from MoviePilot's native download page."""
        if not self._is_lunatv_downloader(downloader):
            return None
        resumed = self._control_queue_tasks(hashs, "resume")
        if resumed:
            self._start_queue()
        return resumed

    def stop_torrents(
        self, hashs: Any, downloader: Optional[str] = None
    ) -> Optional[bool]:
        """Pause queued or running LunaTV tasks from the native download page."""
        if not self._is_lunatv_downloader(downloader):
            return None
        return self._control_queue_tasks(hashs, "pause")

    def remove_torrents(
        self,
        hashs: Any,
        delete_file: bool = False,
        downloader: Optional[str] = None,
    ) -> Optional[bool]:
        """Remove LunaTV tasks locally and honor MoviePilot's delete-file choice."""
        if not self._is_lunatv_downloader(downloader):
            return None
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
            "downloader_info": self.downloader_info,
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
            client = self._client()
            results = self._filter_currently_searchable_results(
                client.search(
                    search_query,
                    limit=8,
                    stop_after_first_source=True,
                    enrich=False,
                ),
                client,
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
                    parsed = urllib.parse.urlsplit(url)
                    self._logger.debug(
                        "清晰度探测失败 host=%s path=%s error=%s",
                        parsed.hostname or "",
                        parsed.path,
                        type(exc).__name__,
                    )
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
        subscribe: Any = None,
    ) -> List[Tuple[CmsResult, Dict[str, Any]]]:
        """Prefer the newest season content, then verified resolution."""

        if len(results) < 2:
            return results

        def eligible_episodes(
            result: CmsResult,
            association: Dict[str, Any],
        ) -> List[CmsEpisode]:
            start_episode, total_episode = (1, 0)
            if subscribe is not None:
                start_episode, total_episode = self._subscription_episode_bounds(
                    subscribe,
                    association,
                    season,
                )
            return [
                episode
                for episode in result.episodes
                if int(episode.episode) > 0
                and (season <= 0 or int(episode.season) == season)
                and int(episode.episode) >= start_episode
                and (total_episode <= 0 or int(episode.episode) <= total_episode)
            ]

        def episode_freshness(
            result: CmsResult,
            association: Dict[str, Any],
        ) -> Tuple[int, int, int]:
            episodes = {
                (int(episode.season), int(episode.episode))
                for episode in eligible_episodes(result, association)
            }
            if not episodes:
                return 0, 0, 0
            latest_season, latest_episode = max(episodes)
            return latest_season, latest_episode, len(episodes)

        def probe_url(result: CmsResult, association: Dict[str, Any]) -> str:
            return next(
                (
                    episode.url
                    for episode in eligible_episodes(result, association)
                    if episode.url
                ),
                "",
            )

        urls = [probe_url(result, association) for result, association in results]
        heights = self._probe_resource_urls(urls)
        ranked = sorted(
            enumerate(results),
            key=lambda item: (
                -episode_freshness(item[1][0], item[1][1])[0],
                -episode_freshness(item[1][0], item[1][1])[1],
                -episode_freshness(item[1][0], item[1][1])[2],
                -heights.get(probe_url(item[1][0], item[1][1]), 0),
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

        def build_torrent(**kwargs: Any) -> Any:
            root = self._effective_root(
                media_type=(
                    "tv"
                    if str(kwargs.get("category") or "") == "电视剧"
                    else "movie"
                )
            )
            if root:
                description = str(kwargs.get("description") or "").strip()
                download_summary = f"下载器：LunaTVSource · 保存目录：{root}"
                kwargs["description"] = (
                    f"{description} · {download_summary}"
                    if description
                    else download_summary
                )
            item = torrent_info_type(**kwargs)
            item.site_downloader = "LunaTVSource"
            if root:
                try:
                    item.download_path = root
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
        use_target_media_identity = (
            requested_media_type in {"movie", "tv"}
            and target_media_source_value is not None
            and target_media_id_value
        )
        with self._source_health_lock:
            source_health_revision = self._source_health_revision
            cache_key = "|".join(
                (
                    normalize_search_title(keyword).casefold(),
                    requested_type,
                    target_media_source_value or "",
                    target_media_id_value or "",
                    target_media_title_value,
                    target_media_year_value,
                    str(source_health_revision),
                )
            )
            now = time.monotonic()
            with self._resource_search_lock:
                self._prune_resource_search_cache(now)
                cached = self._resource_search_cache.get(cache_key)
                # A progress callback requires a real source pass; cached
                # results cannot truthfully report per-source completion.
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
        if use_target_media_identity:
            match_titles = tuple(
                dict.fromkeys(
                    title
                    for title in (target_media_title_value, search_query)
                    if str(title or "").strip()
                )
            )
            results = [
                result
                for result in results
                if result.media_type == requested_media_type
                and any(
                    self._subscription_result_matches(
                        result,
                        {},
                        title=title,
                        year=target_media_year_value,
                        identity_source="",
                        identity_id="",
                    )
                    for title in match_titles
                )
            ]
        # The resource search is one user-selected native media context, not
        # one TMDB lookup per CMS source/result.  AI normalization and the
        # default TMDB association therefore run exactly once here.  Only CMS
        # rows matching that context inherit its host identity.
        association: Dict[str, Any] = {}
        association_context: Optional[CmsResult] = None
        association_match_titles: Tuple[str, ...] = ()
        if results and not (
            requested_media_type == "movie" and use_target_media_identity
        ):
            association_context = self._resource_search_context(search_query, results, mtype)
            association_match_titles = tuple(
                dict.fromkeys(
                    title
                    for title in (association_context.title, keyword)
                    if str(title or "").strip()
                )
            )
            association = self._associate_tmdb(
                association_context,
                include_candidates=False,
            )
        # TV resources are presented as one native download item per
        # source/season.  The enclosure carries the ordered episode list and
        # ``download`` expands it back into the plugin's download queue.  This
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
            canonical_title: str,
            canonical_year: str,
        ) -> Dict[str, Any]:
            return {
                "url": episode.url,
                "title": canonical_title,
                "year": canonical_year,
                "media_type": result.media_type,
                "season": int(episode.season if episode.season is not None else 1),
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
            result_association = association
            if not use_target_media_identity and not (
                association_context
                and result.media_type == association_context.media_type
                and any(
                    self._subscription_result_matches(
                        result,
                        {},
                        title=title,
                        year=str(
                            association.get("year") or association_context.year
                            if association.get("status") == "matched"
                            else association_context.year
                        ),
                        identity_source="",
                        identity_id="",
                    )
                    for title in association_match_titles
                )
            ):
                result_association = {}
            result = self._apply_resource_association(result, result_association)
            identity = f"{result.source_key}:{result.vod_id}"
            if use_target_media_identity:
                host_media_source = str(target_media_source_value)
                host_media_id = str(target_media_id_value)
            else:
                host_media_source = str(
                    result_association.get("media_source") or PLUGIN_MEDIA_SOURCE
                )
                host_media_id = str(result_association.get("media_id") or identity)
            group_title = normalize_media_title(result.title)
            group_year = result.year
            if (
                use_target_media_identity
                and result.media_type == requested_media_type
            ):
                group_title = target_media_title_value or group_title
                group_year = target_media_year_value or group_year
            elif (
                result.media_type == "tv"
                and result_association.get("status") == "matched"
            ):
                group_title = normalize_media_title(
                    str(result_association.get("title") or "").strip()
                ) or group_title
                group_year = (
                    str(result_association.get("year") or "").strip()
                    or group_year
                )
            episodes = result.episodes or [CmsEpisode(1, 1, "正片", "")]
            season_episode_numbers: Dict[int, set[int]] = {}
            season_urls: Dict[int, set[str]] = {}
            for candidate in episodes:
                if not candidate.url or not candidate.season_known:
                    continue
                candidate_season = int(
                    candidate.season if candidate.season is not None else 1
                )
                season_episode_numbers.setdefault(candidate_season, set()).add(
                    int(candidate.episode or 1)
                )
                season_urls.setdefault(candidate_season, set()).add(candidate.url)
            for episode in episodes:
                if not episode.url:
                    continue
                payload = episode_payload(
                    result,
                    episode,
                    identity,
                    host_media_source,
                    host_media_id,
                    group_title,
                    group_year,
                )
                if result.media_type == "tv" and not episode.season_known:
                    continue
                if result.media_type == "tv" and episode.season_known:
                    season = int(episode.season if episode.season is not None else 1)
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
                    "title": group_title,
                    "year": group_year,
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
                and use_target_media_identity
                and target_media_title_provided
            ):
                title = target_media_title_value
                if target_media_year_value:
                    title = f"{title} ({target_media_year_value})"
                elif group["year"]:
                    title = f"{title} ({group['year']})"
            elif group["year"]:
                title = f"{title} ({group['year']})"
            # MoviePilot derives the native-card key from title/meta fields.
            # Do not put the actual resolution in TV title/description, or a
            # 1080P and 720P line becomes separate cards. The selectable line
            # still carries its true quality in site_name/labels and keeps its
            # independent enclosure for whole-season download.
            title = f"{title} · 第{season}季"
            first_height = int(first.get("resolution_height") or 0)
            latency_ms = self._probe_latency_ms(first["url"]) if first_height > 0 else 0
            site_name = f"{group['site_name']} · {quality}"
            labels = ["LunaTV", "m3u8", f"第{season}季", quality]
            if latency_ms:
                site_name = f"{site_name} · {latency_ms}ms"
                labels.append(f"{latency_ms}ms")
            info_media_source = group["host_media_source"]
            info_media_id = group["host_media_id"]
            if payload["media_type"] == "tv" and use_target_media_identity:
                info_media_source = target_media_source_value
                info_media_id = target_media_id_value
            canonical_title = str(group["title"] or payload.get("title") or "")
            canonical_year = str(group["year"] or payload.get("year") or "")
            # The token feeds the later LunaTV queue, while the TorrentInfo
            # feeds MoviePilot's card grouping. Keep both identities exactly
            # aligned, including every episode in a season token.
            for episode_payload in group_episodes:
                episode_payload["title"] = canonical_title
                episode_payload["year"] = canonical_year
                episode_payload["host_media_source"] = info_media_source
                episode_payload["host_media_id"] = info_media_id
            payload["title"] = canonical_title
            payload["year"] = canonical_year
            payload["host_media_source"] = info_media_source
            payload["host_media_id"] = info_media_id
            payload["latency_ms"] = latency_ms
            payload["page_url"] = group["page_url"]
            payload["episode_count"] = count
            item = build_torrent(
                site_name=site_name,
                title=title,
                description=(
                    f"LunaTV · 第{season}季 · m3u8 · 共{count}集"
                ),
                media_source=info_media_source,
                media_id=info_media_id,
                enclosure=self._resource_token(payload),
                page_url=group["page_url"],
                size=0,
                seeders=1,
                uploadvolumefactor=1.0,
                downloadvolumefactor=1.0,
                pri_order=_tv_resource_sort_priority(season, height),
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
            payload["latency_ms"] = latency_ms
            payload["page_url"] = row["page_url"]
            payload["episode_count"] = 1
            site_name = f"{row['site_name']} · {quality}"
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
        with self._source_health_lock:
            if source_health_revision != self._source_health_revision:
                return []
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
        """接管带 LunaTV 标记的原生下载，转入插件持久化下载队列。"""
        payload = self._decode_resource_token(content)
        if payload is None:
            return None
        # MoviePilot 会优先传入全局或站点下载器；LunaTV 资源令牌才是
        # 接管依据，不能让该默认值将其转交给其他下载器。
        del cookie, category, label, downloader
        queue = self._queue
        configured_root = str(self._config.get("download_root") or "").strip()
        root = (
            configured_root
            or str(download_dir or "").strip()
            or self._effective_root(media_type=_media_type_value(payload.get("media_type")))
        )
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
                season_value = entry.get("season")
                season = int(season_value) if season_value not in (None, "") else 1
                episode_number = int(entry.get("episode") or 1)
            except (TypeError, ValueError):
                invalid_count += 1
                continue
            episode = CmsEpisode(
                season=max(0, season),
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
                source_sensitive=True,
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
            if queue.enqueue(task):
                enqueued_ids.append(task.task_id)
            else:
                duplicate_count += 1
        if not enqueued_ids:
            if invalid_count:
                return "LunaTVSource", None, None, "LunaTV 下载参数无效"
            return "LunaTVSource", None, None, "任务已在下载队列或历史记录中"
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
            if result:
                current_results = self._filter_currently_searchable_results(
                    [result], client
                )
                result = current_results[0] if current_results else None
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
        """在宿主目录校验前为 LunaTV 资源补充下载目录。"""

        if not self._enabled or not event:
            return
        event_data = getattr(event, "event_data", None)
        context = getattr(event_data, "context", None)
        torrent = getattr(context, "torrent_info", None)
        content = getattr(torrent, "enclosure", None)
        payload = self._decode_resource_token(content)
        if payload is None:
            return
        event_data.source = "LunaTVSource"

        configured_root = str(self._config.get("download_root") or "").strip() or self._effective_root(
            media_type=_media_type_value(payload.get("media_type"))
        )
        if not configured_root:
            event_data.reason = "未配置 LunaTV 下载目录，继续交由 MoviePilot 处理"
            return

        options = getattr(event_data, "options", None)
        if not isinstance(options, dict):
            options = {}
            event_data.options = options
        options["save_path"] = configured_root
        event_data.reason = "已准备 LunaTV 下载目录，继续交由 MoviePilot 下载链处理"

    @eventmanager.register(getattr(EventType, "SubscribeAdded", "subscribe.added"))
    def _on_subscribe_added(self, event: Event) -> None:
        if self._enabled:
            self._start_background(self.refresh_subscriptions)

    @eventmanager.register(getattr(EventType, "SubscribeModified", "subscribe.modified"))
    def _on_subscribe_modified(self, event: Event) -> None:
        event_data = getattr(event, "event_data", None) or {}
        scene = (
            event_data.get("scene")
            if isinstance(event_data, dict)
            else getattr(event_data, "scene", "")
        )
        if scene in _SUBSCRIPTION_PASSIVE_EVENT_SCENES:
            return
        if self._enabled:
            self._start_background(self.refresh_subscriptions)

    @eventmanager.register(getattr(EventType, "PluginAction", "plugin.action"))
    def _on_plugin_action(self, event: Event) -> None:
        """Handle the registered remote command without claiming other actions."""

        event_data = getattr(event, "event_data", None) or {}
        if isinstance(event_data, dict) and event_data.get("action") == "sync":
            if self._enabled:
                self._start_background(self.refresh_subscriptions)
