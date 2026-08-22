"""MoviePilot V3 plugin for MoonTV/LunaTV Apple CMS sources.

The first implementation deliberately keeps the source adapter independent from
MoviePilot internals.  The host integration is optional at import time so the
pure search, naming and queue code can be tested outside a running MoviePilot.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # MoviePilot V3 runtime imports
    from app.plugins import _PluginBase
    from app.sdk.events import Event, eventmanager
    from app.schemas.types import EventType
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

try:  # Optional V3 native media-source/organize bridge.
    from app import schemas as _schemas
    from app.chain.mediaserver import MediaServerChain as _HostMediaServerChain
    from app.chain.storage import StorageChain as _HostStorageChain
    from app.chain.transfer import TransferChain as _HostTransferChain
    from app.schemas.event import DiscoverSourceEventData as _DiscoverSourceEventData
    from app.schemas.types import ChainEventType as _HostChainEventType
    from app.schemas.types import MediaSource as _HostMediaSource
    from app.schemas.types import MediaType as _HostMediaType
except Exception:  # pragma: no cover - standalone tests
    _schemas = None
    _HostMediaServerChain = None
    _HostStorageChain = None
    _HostTransferChain = None
    _DiscoverSourceEventData = Any
    _HostChainEventType = None
    _HostMediaSource = None
    _HostMediaType = None

try:
    from apscheduler.triggers.cron import CronTrigger
except Exception:  # pragma: no cover - standalone tests
    CronTrigger = None  # type: ignore[assignment,misc]

from .ai import AiTitleNormalizer
from .cms import AppleCmsClient, CmsEpisode, CmsResult, CmsSource, load_sources_from_url
from .downloader import DownloadQueue, DownloadTask
from .naming import media_path


LOGGER = logging.getLogger("LunaTVSource")


DEFAULT_CONFIG_URL = (
    "https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json"
)
DEFAULT_SOURCE_ALLOWLIST = (
    "suonizy.net,suoniapi.com,kuaichezy.com,caiji.kuaichezy.org,"
    "www.hongniuzy.com,www.hongniuzy2.com,wujinzy.net,wujinzy.me,"
    "api.wujinapi.me,wujinapi.me,guangsuzy.com,api.guangsuapi.com,"
    "ukuzy0.com,api.ukuapi88.com,www.xinlangzy.com,xinlangapi.com,okzyw.cc"
)
PLUGIN_MEDIA_SOURCE = "lunatv"


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


class LunaTVSource(_PluginBase):
    """第三方苹果 CMS/m3u8 订阅下载插件。"""

    plugin_name = "LunaTV 资源订阅"
    plugin_desc = "接入 LunaTV/MoonTV 苹果 CMS 资源，注册 V3 媒体源，串行下载到指定目录并可刷新 Emby/原生整理链。"
    plugin_icon = "lunatvsource.svg"
    plugin_version = "0.2.0"
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

    def __init__(self) -> None:
        super().__init__()
        self._logger = LOGGER

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = dict(config or {})
        self._enabled = _bool(self._config.get("enabled"), False)
        self._ai = AiTitleNormalizer(_bool(self._config.get("ai_enabled"), False), LOGGER)
        self._queue = DownloadQueue(
            load=lambda key, default=None: self.get_data(key, default),
            save=lambda key, value: self.save_data(key, value),
            notify=self._notify,
            on_complete=self._record_completion,
        )

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        return [
            {
                "nav_key": "main",
                "title": "LunaTV 订阅",
                "icon": "mdi-play-network",
                "section": "subscribe",
                "permission": "manage",
                "order": 55,
            }
        ]

    def get_page(self) -> List[Dict[str, Any]]:
        """Keep the standard plugin detail page useful when the Vue workbench is unavailable."""

        root = str(self._config.get("download_root") or "").strip()
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info" if root else "warning",
                    "variant": "tonal",
                    "text": (
                        f"已启用，下载目录：{root}。任务按队列串行执行，完成后可刷新 Emby。"
                        if root
                        else "请先在插件设置中填写容器内下载目录，再创建 MoviePilot 订阅；未填写时不会接管下载。"
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
            {"path": "/history", "endpoint": self.api_history, "methods": ["GET"], "auth": "bear"},
            {"path": "/sync", "endpoint": self.api_sync, "methods": ["POST"], "auth": "bear"},
            {"path": "/tasks/{task_id}/retry", "endpoint": self.api_retry, "methods": ["POST"], "auth": "bear"},
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                            "label": "下载目录（容器内路径）",
                            "placeholder": "/media/incoming/lunatv",
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
                            "text": "订阅任务串行执行；完成下载后才进入整理。目录内没有正在下载的缓存文件时，媒体库才会显示完整文件夹。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "config_url": DEFAULT_CONFIG_URL,
            "source_allowlist": DEFAULT_SOURCE_ALLOWLIST,
            "mode": "download",
            "source_strategy": "first",
            "download_root": "",
            "ffmpeg_path": "ffmpeg",
            "request_timeout": 15,
            "poll_minutes": 30,
            "queue_minutes": 1,
            "ai_enabled": False,
            "moviepilot_organize": False,
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
        if self._queue:
            self._queue.stop()

    def _client(self) -> AppleCmsClient:
        config_url = str(self._config.get("config_url") or DEFAULT_CONFIG_URL)
        allowlist = _source_keys(self._config.get("source_allowlist") or DEFAULT_SOURCE_ALLOWLIST)
        sources = load_sources_from_url(
            config_url,
            timeout=float(self._config.get("request_timeout") or 15),
            allowlist=allowlist,
        )
        return AppleCmsClient(sources=sources, timeout=float(self._config.get("request_timeout") or 15))

    @staticmethod
    def _host_media_source() -> Any:
        if _HostMediaSource is None:
            return PLUGIN_MEDIA_SOURCE
        try:
            return _HostMediaSource(PLUGIN_MEDIA_SOURCE)
        except Exception:
            return PLUGIN_MEDIA_SOURCE

    @staticmethod
    def _host_media_type(media_type: str) -> Any:
        if _HostMediaType is None:
            return media_type
        try:
            return _HostMediaType.TV if media_type == "tv" else _HostMediaType.MOVIE
        except Exception:
            return media_type

    def _media_info(self, result: CmsResult) -> Any:
        """将 CMS 结果转换成 V3 原生 MediaInfo，供探索/订阅/整理链复用。"""
        if _schemas is None or not hasattr(_schemas, "MediaInfo"):
            return result.to_dict()
        seasons: Dict[int, List[int]] = {}
        for episode in result.episodes:
            seasons.setdefault(episode.season, []).append(episode.episode)
        title_year = f"{result.title} ({result.year})" if result.year else result.title
        return _schemas.MediaInfo(
            type="电视剧" if result.media_type == "tv" else "电影",
            title=result.title,
            year=result.year or None,
            title_year=title_year,
            media_source=self._host_media_source(),
            media_id=f"{result.source_key}:{result.vod_id}",
            seasons={key: sorted(set(value)) for key, value in seasons.items()},
            detail_link=result.detail or None,
        )

    def _sdk_media_info(self, result: CmsResult) -> Any:
        """构造识别链使用的旧式 SDK MediaInfo（与探索 API 的 schema 分开）。"""
        try:
            from app.sdk.media import MediaInfo as SdkMediaInfo

            seasons: Dict[int, List[int]] = {}
            for episode in result.episodes:
                seasons.setdefault(episode.season, []).append(episode.episode)
            return SdkMediaInfo(
                type=self._host_media_type(result.media_type),
                title=result.title,
                year=result.year or None,
                media_source=self._host_media_source(),
                media_id=f"{result.source_key}:{result.vod_id}",
                seasons={key: sorted(set(value)) for key, value in seasons.items()},
            )
        except Exception:
            return self._media_info(result)

    def _effective_root(self, subscribe: Any = None) -> str:
        return str(
            self._config.get("download_root")
            or getattr(subscribe, "save_path", "")
            or ""
        ).strip()

    def _local_episode_exists(self, task: DownloadTask) -> bool:
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
            return path.exists() and path.stat().st_size > 0
        except (OSError, ValueError):
            return False

    def _native_transfer(self, task: DownloadTask, output: str) -> str:
        """让 MoviePilot 原生整理链接管已下载文件；不可用时保留直写结果。"""
        if not _bool(self._config.get("moviepilot_organize"), False):
            return "direct"
        if _HostStorageChain is None or _HostTransferChain is None:
            return "fallback:host-chain-unavailable"
        if task.mode == "strm":
            return "strm-direct"
        try:
            fileitem = _HostStorageChain().get_file_item(storage="local", path=Path(output))
            if not fileitem:
                return "fallback:file-not-found"
            state, message = _HostTransferChain().manual_transfer(
                fileitem=fileitem,
                target_storage="local",
                target_path=Path(task.root),
                media_source=self._host_media_source(),
                media_id=task.media_id,
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
        """把成功文件写入 MoviePilot 整理历史；数据库不可用时不影响下载。"""
        try:
            from app.db.oper.transferhistory import TransferHistoryOper

            TransferHistoryOper().add(
                src=output,
                src_storage="local",
                dest=output,
                dest_storage="local",
                mode="copy" if task.mode == "download" else "strm",
                type="电视剧" if task.media_type == "tv" else "电影",
                title=task.title,
                year=task.year or None,
                media_source=PLUGIN_MEDIA_SOURCE,
                media_id=task.media_id,
                seasons=str(task.season) if task.media_type == "tv" else None,
                episodes=str(task.episode) if task.media_type == "tv" else None,
                status=True,
                files=[output],
            )
        except Exception as exc:
            self._logger.debug("写入 MoviePilot 整理历史失败：%s", exc)

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
        return {
            "success": True,
            "data": {
                "enabled": self._enabled,
                "queue": queue.summary(),
                "ai": (self._ai or AiTitleNormalizer(False)).status(),
                "media_source": PLUGIN_MEDIA_SOURCE,
                "media_server_sync_running": self._media_sync_running,
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
            results = self._client().search(search_query)
            return {"success": True, "data": [item.to_dict() for item in results]}
        except Exception as exc:
            self._logger.warning("LunaTV search failed: %s", exc)
            return {"success": False, "message": f"搜索失败：{exc}", "data": []}

    def api_discover(self, query: str = "", title: str = "", page: int = 1, count: int = 30) -> Dict[str, Any]:
        """V3 探索数据源接口，返回宿主统一 MediaInfo，而非插件自定义播放器。"""
        del page
        query = str(query or title or "").strip()
        if not query:
            return {"success": True, "data": []}
        try:
            search_query, _ = (self._ai or AiTitleNormalizer(False)).normalize(query)
            results = self._client().search(search_query, limit=max(1, min(int(count or 30), 50)))
            return {"success": True, "data": [self._media_info(result) for result in results]}
        except Exception as exc:
            self._logger.warning("LunaTV discover failed: %s", exc)
            return {"success": False, "message": f"探索失败：{exc}", "data": []}

    def api_tasks(self) -> Dict[str, Any]:
        queue = self._queue or DownloadQueue(lambda *_: None, lambda *_: None, self._notify)
        return {"success": True, "data": queue.list_tasks()}

    def api_history(self) -> Dict[str, Any]:
        history = self.get_data("download_history_v1", []) or []
        return {"success": True, "data": list(reversed(history[-500:]))}

    def api_download(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        queue = self._queue
        if queue is None:
            return {"success": False, "message": "插件尚未初始化", "data": {}}
        episode_payload = payload.get("episode") or {}
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
        )
        task = DownloadTask.from_episode(
            episode,
            title=str(payload.get("title") or "未命名"),
            year=str(payload.get("year") or ""),
            media_type=str(payload.get("media_type") or "tv"),
            root=str(payload.get("root") or self._config.get("download_root") or ""),
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
        self._record_native_history(task, output)
        history = self.get_data("download_history_v1", []) or []
        history.append(
            {
                "task_id": task.task_id,
                "source_key": task.source_key,
                "media_id": task.media_id,
                "title": task.title,
                "year": task.year,
                "media_type": task.media_type,
                "season": task.season,
                "episode": task.episode,
                "mode": task.mode,
                "output": output,
                "organize": organize_state,
                "completed_at": task.completed_at or 0,
            }
        )
        self.save_data("download_history_v1", history[-500:])
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
            try:
                from app.db.oper.subscribe import SubscribeOper
            except ImportError:
                from app.sdk._legacy.subscribe import SubscribeOper
        except Exception:
            self._logger.debug("SubscribeOper unavailable; refresh skipped")
            return {"subscriptions": 0, "queued": 0}

        queue = self._queue
        if queue is None:
            return {"subscriptions": 0, "queued": 0}
        try:
            try:
                subscribes = SubscribeOper().list(state="R")
            except TypeError:
                subscribes = SubscribeOper().list()
        except Exception as exc:
            self._logger.warning("读取 MoviePilot 订阅失败：%s", exc)
            return {"subscriptions": 0, "queued": 0, "error": str(exc)}

        client = self._client()
        queued = 0
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
                identity_source = str(getattr(subscribe, "media_source", "") or "").strip().lower()
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
            for result in results:
                if target_type and result.media_type and target_type not in {result.media_type, "电视剧" if result.media_type == "tv" else "电影"}:
                    continue
                if any(season <= 0 or episode.season == season for episode in result.episodes):
                    matching_results.append(result)
            if str(self._config.get("source_strategy") or "first") != "all":
                matching_results = matching_results[:1]
            for result in matching_results:
                for episode in result.episodes:
                    if season > 0 and episode.season != season:
                        continue
                    task = DownloadTask.from_episode(
                        episode,
                        title=normalized_title if normalized_title != title else result.title,
                        year=result.year,
                        media_type=result.media_type,
                        root=self._effective_root(subscribe),
                        mode=str(self._config.get("mode") or "download"),
                        ffmpeg_path=str(self._config.get("ffmpeg_path") or "ffmpeg"),
                        media_source="lunatv",
                        media_id=f"{result.source_key}:{result.vod_id}",
                    )
                    if self._local_episode_exists(task):
                        continue
                    if queue.enqueue(task):
                        queued += 1
        return {"subscriptions": len(active_subscribes), "queued": queued}

    def run_queue(self) -> Dict[str, Any]:
        if not self._queue:
            return {"processed": 0}
        return self._queue.run_one()

    def get_media_source(self) -> List[Dict[str, Any]]:
        """声明 V3 全局媒体搜索可选的 LunaTV 来源。"""
        return [
            {
                "name": "LunaTV / 苹果 CMS",
                "media_source": self._host_media_source(),
                "media_types": [
                    getattr(_HostMediaType, "MOVIE", "电影"),
                    getattr(_HostMediaType, "TV", "电视剧"),
                ],
            }
        ] if self._enabled else []

    def get_module(self) -> Dict[str, Any]:
        """把已声明的媒体来源接到 V3 识别链；只认 lunatv 自身身份。"""
        if not self._enabled or not _bool(self._config.get("native_recognize"), True):
            return {}
        return {
            "recognize_media": self.recognize_media,
            "async_recognize_media": self.async_recognize_media,
        }

    def recognize_media(
        self,
        meta: Any = None,
        mtype: Any = None,
        media_source: Any = None,
        media_id: Optional[str] = None,
        **_: Any,
    ) -> Any:
        if not self._enabled or str(media_source or "") != PLUGIN_MEDIA_SOURCE:
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
                    result = (client.search(title, limit=1) or [None])[0]
            return self._sdk_media_info(result) if result else None
        except Exception as exc:
            self._logger.debug("LunaTV 原生识别失败：%s", exc)
            return None

    async def async_recognize_media(self, *args: Any, **kwargs: Any) -> Any:
        return self.recognize_media(*args, **kwargs)

    @eventmanager.register(getattr(_HostChainEventType, "DiscoverSource", "discover.source"))
    def _discover_source(self, event: Event) -> None:
        """把 LunaTV 注册到 V3“探索”数据源，搜索结果可直接进入订阅。"""
        if not self._enabled or _schemas is None or _HostMediaSource is None:
            return
        event_data = getattr(event, "event_data", None)
        if not event_data:
            return
        try:
            source = _schemas.DiscoverMediaSource(
                name="LunaTV / 苹果 CMS",
                media_source=self._host_media_source(),
                mediaid_prefix=PLUGIN_MEDIA_SOURCE,
                api_path="plugin/LunaTVSource/discover",
            )
            if isinstance(event_data, dict):
                event_data.setdefault("extra_sources", []).append(source)
            elif hasattr(event_data, "extra_sources"):
                event_data.extra_sources = list(event_data.extra_sources or []) + [source]
        except Exception as exc:
            self._logger.debug("注册 LunaTV 探索源失败：%s", exc)

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
