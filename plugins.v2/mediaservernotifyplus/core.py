"""MoviePilot V2/V3 共用的媒体服务器通知业务核心。

本模块只使用 Python 标准库，宿主差异由各代 ``__init__.py`` 中的适配方法处理。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple


ACTION_LABELS: Dict[str, str] = {
    "library_added": "已入库",
    "library_deleted": "已删除",
    "playback_started": "开始播放",
    "playback_stopped": "停止播放",
    "playback_paused": "暂停播放",
    "playback_resumed": "继续播放",
    "auth_success": "登录成功",
    "auth_failed": "登录失败",
    "rated": "已标记",
    "test": "测试",
}

ACTION_ICONS: Dict[str, str] = {
    "library_added": "📂",
    "library_deleted": "🗑️",
    "playback_started": "▶️",
    "playback_stopped": "⏹️",
    "playback_paused": "⏸️",
    "playback_resumed": "▶️",
    "auth_success": "🔐",
    "auth_failed": "⚠️",
    "rated": "⭐",
    "test": "🧪",
}

ACTION_DESCRIPTIONS: Dict[str, str] = {
    "library_added": "媒体文件加入媒体库时通知",
    "library_deleted": "媒体文件从媒体库移除时通知",
    "playback_started": "用户开始播放媒体时通知",
    "playback_stopped": "用户停止播放媒体时通知",
    "playback_paused": "用户暂停播放媒体时通知",
    "playback_resumed": "用户继续播放媒体时通知",
    "auth_success": "用户成功登录媒体服务器时通知",
    "auth_failed": "媒体服务器登录失败时通知",
    "rated": "用户标记已看、未看或评分时通知",
    "test": "用于检查当前通知样式",
}

FIELD_CATALOG: Dict[str, Dict[str, str]] = {
    "time": {"label": "时间", "icon": "🕐"},
    "server": {"label": "服务器", "icon": "🖥️"},
    "library": {"label": "媒体库分类", "icon": "🗂️"},
    "season_episode": {"label": "季集", "icon": "📺"},
    "rating": {"label": "评分", "icon": "⭐"},
    "region": {"label": "地区", "icon": "🏳️"},
    "actors": {"label": "演员", "icon": "🎬"},
    "overview": {"label": "剧情简介", "icon": "📖", "style": "block"},
    "user": {"label": "用户", "icon": "👤"},
    "device": {"label": "设备", "icon": "📱"},
    "ip": {"label": "IP", "icon": "🌐"},
    "progress": {"label": "播放进度", "icon": "⏱️"},
}

COMMON_MEDIA_FIELDS: Tuple[str, ...] = (
    "season_episode", "user", "device", "progress", "server", "library",
    "rating", "actors", "region", "ip", "time", "overview",
)
LIBRARY_MEDIA_FIELDS: Tuple[str, ...] = tuple(
    field for field in COMMON_MEDIA_FIELDS
    if field not in {"user", "device", "progress", "ip"}
)

ACTION_FIELDS: Dict[str, Tuple[str, ...]] = {
    "library_added": LIBRARY_MEDIA_FIELDS,
    "library_deleted": LIBRARY_MEDIA_FIELDS,
    "playback_started": COMMON_MEDIA_FIELDS,
    "playback_stopped": COMMON_MEDIA_FIELDS,
    "playback_paused": COMMON_MEDIA_FIELDS,
    "playback_resumed": COMMON_MEDIA_FIELDS,
    "auth_success": ("user", "device", "ip", "server", "time"),
    "auth_failed": ("user", "device", "ip", "server", "time"),
    "rated": COMMON_MEDIA_FIELDS,
    "test": ("server", "time"),
}

DEFAULT_ENABLED_FIELDS: Dict[str, Tuple[str, ...]] = {
    "library_added": ("season_episode", "rating", "server", "time", "overview"),
    "library_deleted": ("season_episode", "library", "server", "time"),
    "playback_started": ("season_episode", "user", "device", "ip", "progress", "server", "time"),
    "playback_stopped": ("season_episode", "user", "device", "ip", "progress", "server", "time"),
    "playback_paused": ("season_episode", "user", "device", "ip", "progress", "time"),
    "playback_resumed": ("season_episode", "user", "device", "ip", "progress", "time"),
    "auth_success": ("user", "device", "ip", "server", "time"),
    "auth_failed": ("user", "device", "ip", "server", "time"),
    "rated": ("season_episode", "user", "rating", "server", "time"),
    "test": ("server", "time"),
}

ACTION_ALIASES: Dict[str, str] = {
    "library.new": "library_added",
    "itemadded": "library_added",
    "library.deleted": "library_deleted",
    "itemdeleted": "library_deleted",
    "playback.start": "playback_started",
    "playbackstart": "playback_started",
    "media.play": "playback_started",
    "playback.stop": "playback_stopped",
    "playbackstop": "playback_stopped",
    "media.stop": "playback_stopped",
    "playback.pause": "playback_paused",
    "media.pause": "playback_paused",
    "playback.unpause": "playback_resumed",
    "media.resume": "playback_resumed",
    "user.authenticated": "auth_success",
    "authenticationsuccess": "auth_success",
    "user.authenticationfailed": "auth_failed",
    "authenticationfailure": "auth_failed",
    "item.rate": "rated",
    "item.markplayed": "rated",
    "item.markunplayed": "rated",
    "system.webhooktest": "test",
    "system.notificationtest": "test",
}

def default_field_configs() -> Dict[str, List[Dict[str, Any]]]:
    """返回可直接序列化的默认字段顺序、名称和启用状态。"""
    result: Dict[str, List[Dict[str, Any]]] = {}
    for action, fields in ACTION_FIELDS.items():
        enabled = set(DEFAULT_ENABLED_FIELDS[action])
        result[action] = [
            {
                "key": field,
                "label": FIELD_CATALOG[field]["label"],
                "enabled": field in enabled,
            }
            for field in fields
        ]
    return result


def normalize_field_configs(value: Any) -> Dict[str, List[Dict[str, Any]]]:
    """清洗前端字段配置，拒绝未知字段并补齐新版本增加的字段。"""
    defaults = default_field_configs()
    if not isinstance(value, dict):
        return defaults
    normalized: Dict[str, List[Dict[str, Any]]] = {}
    for action, default_rows in defaults.items():
        allowed = {row["key"] for row in default_rows}
        source_rows = value.get(action)
        source_rows = source_rows if isinstance(source_rows, list) else []
        rows: List[Dict[str, Any]] = []
        seen = set()
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "")
            if key not in allowed or key in seen:
                continue
            label = str(row.get("label") or FIELD_CATALOG[key]["label"]).strip()
            if key == "device" and label in {"设备 / 客户端", "设备/客户端"}:
                label = FIELD_CATALOG[key]["label"]
            if key == "library" and label in {"媒体库", "媒体类别"}:
                label = FIELD_CATALOG[key]["label"]
            rows.append({
                "key": key,
                "label": (label or FIELD_CATALOG[key]["label"])[:30],
                "enabled": bool(row.get("enabled")),
            })
            seen.add(key)
        for row in default_rows:
            if row["key"] not in seen:
                rows.append(dict(row))
        normalized[action] = rows
    return normalized


def merge_ip_location(ip: Any, location: Any) -> str:
    """把 IP 与归属地合成一个可通知字段，避免界面出现两个重复选项。"""
    address = str(ip or "").strip()
    place = str(location or "").strip()
    if not address:
        return ""
    if not place or place in address:
        return address
    return f"{address} {place}"


def build_library_records(
    server_name: str,
    libraries: Any,
    virtual_libraries: Any = None,
) -> List[Dict[str, Any]]:
    """合并媒体库概要与 VirtualFolders 路径，生成稳定的库匹配记录。"""

    def value(item: Any, *names: str) -> Any:
        if isinstance(item, Mapping):
            for name in names:
                if item.get(name) not in (None, ""):
                    return item.get(name)
            return None
        for name in names:
            current = getattr(item, name, None)
            if current not in (None, ""):
                return current
        return None

    def paths(item: Any) -> List[str]:
        raw_paths = value(item, "path", "Path", "paths", "Paths") or []
        if not isinstance(raw_paths, (list, tuple, set)):
            raw_paths = [raw_paths]
        return [str(path) for path in raw_paths if path]

    virtual_by_id: Dict[str, List[str]] = {}
    virtual_by_name: Dict[str, List[str]] = {}
    for folder in virtual_libraries if isinstance(virtual_libraries, list) else []:
        folder_paths = paths(folder)
        folder_id = str(value(folder, "id", "Id", "item_id", "ItemId") or "")
        folder_name = str(value(folder, "name", "Name") or "").strip().casefold()
        if folder_id:
            virtual_by_id.setdefault(folder_id, []).extend(folder_paths)
        if folder_name:
            virtual_by_name.setdefault(folder_name, []).extend(folder_paths)

    records: List[Dict[str, Any]] = []
    for library in libraries if isinstance(libraries, list) else []:
        library_id = value(library, "id", "Id", "item_id", "ItemId")
        if library_id in (None, ""):
            continue
        library_id = str(library_id)
        name = str(value(library, "name", "Name") or library_id)
        merged_paths = paths(library)
        merged_paths.extend(virtual_by_id.get(library_id, []))
        merged_paths.extend(virtual_by_name.get(name.strip().casefold(), []))
        merged_paths = list(dict.fromkeys(path for path in merged_paths if path))
        records.append({
            "server": server_name,
            "id": library_id,
            "name": name,
            "paths": merged_paths,
        })
    return records


class FieldTemplateRenderer:
    """按照用户选择的字段顺序生成通知正文。"""

    def __init__(self, field_configs: Mapping[str, List[Mapping[str, Any]]]) -> None:
        self._field_configs = normalize_field_configs(dict(field_configs))

    def render(self, action: str, context: Mapping[str, Any]) -> Tuple[str, str]:
        if action not in ACTION_LABELS:
            raise TemplateError(f"未知通知类型：{action}")
        title = self._event_heading(action, context)
        display_name = str(context.get("display_name") or "").strip()
        if display_name and action not in {"auth_success", "auth_failed", "test"}:
            # MoviePilot 会以大号标题样式渲染 title；媒体名放在第二行即可
            # 获得与事件标题一致的醒目层级，同时保留正文的自定义字段布局。
            title = f"{title}\n{display_name}"
        detail_lines: List[str] = []
        for row in self._field_configs[action]:
            if not row.get("enabled"):
                continue
            key = str(row["key"])
            value = str(context.get(key) or "").strip()
            if not value:
                continue
            meta = FIELD_CATALOG[key]
            label = str(row.get("label") or meta["label"]).strip()
            if meta.get("style") == "block":
                detail_lines.append(f"{meta['icon']} {label}\n{value}")
            else:
                detail_lines.append(f"{meta['icon']} {label}：{value}")
        return title, "\n".join(detail_lines).strip()

    @staticmethod
    def _event_heading(action: str, context: Mapping[str, Any]) -> str:
        label = ACTION_LABELS[action]
        if action == "library_added":
            count = str(context.get("file_count") or "1").strip()
            label = f"已入库 {count} 个文件"
        return f"{ACTION_ICONS[action]} {label}"


class TemplateError(ValueError):
    """通知字段配置不合法。"""


class MediaServerNotifyCore:
    """V2/V3 共用的事件路由、去重、聚合和字段排版逻辑。"""

    DEFAULT_AGGREGATE_TIME = 15
    DEFAULT_DEDUPE_TIME = 30
    SHUTDOWN_TIMEOUT = 3.0

    def _initialize_core(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._accepting_events = False
        self._generation = 0
        self._active_operations = 0
        self._owned_timers: set[threading.Timer] = set()
        self._aggregate_timers: Dict[str, threading.Timer] = {}
        self._pending_messages: Dict[str, List[Dict[str, Any]]] = {}
        self._dedupe_cache: Dict[str, float] = {}
        self._enabled = False
        self._types: List[str] = []
        self._mediaservers: List[str] = []
        self._library_records: List[Dict[str, Any]] = []
        self._field_configs = default_field_configs()
        self._renderer = FieldTemplateRenderer(self._field_configs)

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """可重复调用地读取配置并重建运行状态。"""
        if not self._quiesce(flush=False):
            self._log_debug("旧通知任务停止超时，已隔离旧任务并重建配置")
        config = config or {}
        field_configs = normalize_field_configs(config.get("field_configs"))
        with self._condition:
            self._enabled = bool(config.get("enabled"))
            if "types" in config:
                self._types = [item for item in list(config.get("types") or []) if item in ACTION_LABELS]
            else:
                self._types = [
                    action for action in ACTION_LABELS
                    if bool(config.get(f"event_enabled_{action}", True))
                ]
            self._mediaservers = list(config.get("mediaservers") or [])
            self._aggregate_enabled = bool(config.get("aggregate_enabled", True))
            self._aggregate_time = max(1, int(config.get("aggregate_time") or self.DEFAULT_AGGREGATE_TIME))
            self._dedupe_library = max(0, int(
                self.DEFAULT_DEDUPE_TIME if config.get("dedupe_library") in (None, "") else config["dedupe_library"]
            ))
            self._dedupe_playback = max(0, int(
                self.DEFAULT_DEDUPE_TIME if config.get("dedupe_playback") in (None, "") else config["dedupe_playback"]
            ))
            self._flush_on_stop = bool(config.get("flush_on_stop", False))
            self._field_configs = field_configs
            self._renderer = FieldTemplateRenderer(field_configs)
            self._accepting_events = True
        self._refresh_library_records()
        if config.get("send_test"):
            self._send_template_test(str(config.get("preview_type") or "library_added"))
            saved_config = dict(config)
            saved_config["send_test"] = False
            self.update_config(saved_config)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_page(self) -> List[dict]:
        # 非空返回值兼容通过页面内容判断插件卡片是否可点击的 V2 前端。
        return [{"component": "div", "text": "媒体库通知"}]

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """使用 Vue 联邦组件实现卡片、弹窗和拖动排序。"""
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 配置组件读取默认值、字段元数据和媒体服务器列表。"""
        defaults: Dict[str, Any] = {
            "enabled": False,
            "mediaservers": [],
            "types": list(ACTION_LABELS),
            "field_configs": default_field_configs(),
            "_default_field_configs": default_field_configs(),
            "aggregate_enabled": True,
            "aggregate_time": self.DEFAULT_AGGREGATE_TIME,
            "dedupe_library": self.DEFAULT_DEDUPE_TIME,
            "dedupe_playback": self.DEFAULT_DEDUPE_TIME,
            "flush_on_stop": False,
            "preview_type": "library_added",
            "send_test": False,
            "_server_options": self._server_options(),
            "_action_meta": {
                action: {
                    "label": label,
                    "description": ACTION_DESCRIPTIONS[action],
                    "icon": ACTION_ICONS[action],
                }
                for action, label in ACTION_LABELS.items()
            },
            "_field_catalog": {key: dict(value) for key, value in FIELD_CATALOG.items()},
        }
        return None, defaults

    def _refresh_library_records(self) -> None:
        try:
            records = self._discover_libraries()
            if isinstance(records, list):
                self._library_records = records
        except Exception as error:
            self._log_debug(f"读取具体媒体库失败：{error}")

    def _match_library(self, info: Any, context: Dict[str, Any]) -> bool:
        """从事件中的库 ID 或文件路径匹配配置页列出的具体媒体库。"""
        raw = self._raw_object(info)
        item = self._raw_item(info)
        candidates = {
            str(value)
            for value in (
                item.get("CollectionFolderId"), item.get("LibrarySectionId"),
                item.get("librarySectionID"), item.get("topParentId"),
                raw.get("CollectionFolderId"), raw.get("LibrarySectionId"),
                raw.get("librarySectionID"), raw.get("topParentId"),
            )
            if value not in (None, "")
        }
        names = {
            str(value).strip().casefold()
            for value in (
                item.get("CollectionName"), item.get("LibraryName"),
                item.get("librarySectionTitle"), raw.get("CollectionName"),
                raw.get("LibraryName"), raw.get("librarySectionTitle"),
            )
            if value not in (None, "")
        }
        item_path = str(
            getattr(info, "item_path", "") or item.get("Path") or raw.get("Path") or ""
        ).replace("\\", "/").rstrip("/").lower()
        server_name = str(context.get("server") or "")
        for record in self._library_records:
            if server_name and str(record.get("server") or "") != server_name:
                continue
            if str(record.get("id") or "") in candidates:
                context["library"] = str(record.get("name") or "")
                return True
            if str(record.get("name") or "").strip().casefold() in names:
                context["library"] = str(record.get("name") or "")
                return True
            paths = record.get("paths") or []
            if isinstance(paths, str):
                paths = [paths]
            for path in paths:
                normalized = str(path or "").replace("\\", "/").rstrip("/").lower()
                if item_path and normalized and (
                    item_path == normalized or item_path.startswith(normalized + "/")
                ):
                    context["library"] = str(record.get("name") or "")
                    return True
        return False

    def _field_enabled(self, action: str, field: str) -> bool:
        return any(
            row.get("key") == field and row.get("enabled")
            for row in self._field_configs.get(action, [])
        )

    def handle_webhook(self, event: Any) -> None:
        """标准化并处理 MoviePilot WebhookMessage 事件。"""
        generation = self._begin_operation()
        if generation is None:
            return
        try:
            if not self._enabled:
                return
            info = getattr(event, "event_data", None)
            raw_event = str(getattr(info, "event", "") or "")
            action = ACTION_ALIASES.get(raw_event.lower())
            if not info or not action or action not in self._types:
                return
            if not self._service_allowed(info):
                return
            context = self._base_context(info, action)
            context["_generation"] = generation
            if action not in {"auth_success", "auth_failed", "test"}:
                self._match_library(info, context)
            if self._is_duplicate(info, action, context):
                return
            try:
                self._enrich_context(info, context)
            except Exception as error:
                self._log_debug(f"元数据增强失败，将使用 Webhook 原始字段：{error}")
            if self._should_aggregate(info, action):
                self._queue_aggregate(info, context)
                return
            self._send_context(action, context)
        except Exception as error:
            self._log_error(f"处理 Webhook 失败：{error}")
        finally:
            self._finish_operation()

    def _begin_operation(self) -> Optional[int]:
        with self._condition:
            if not self._accepting_events:
                return None
            self._active_operations += 1
            return self._generation

    def _context_is_current(self, context: Mapping[str, Any]) -> bool:
        """拒绝停止或重载前创建的事件；显式测试消息不携带运行代际。"""
        generation = context.get("_generation")
        return generation is None or (
            self._enabled and self._accepting_events and generation == self._generation
        )

    def _finish_operation(self) -> None:
        with self._condition:
            self._active_operations = max(0, self._active_operations - 1)
            self._condition.notify_all()

    @staticmethod
    def _raw_object(info: Any) -> dict:
        raw = getattr(info, "json_object", None)
        return raw if isinstance(raw, dict) else {}

    @classmethod
    def _raw_item(cls, info: Any) -> dict:
        raw = cls._raw_object(info)
        item = raw.get("Item") or raw.get("Metadata") or {}
        return item if isinstance(item, dict) else {}

    @classmethod
    def _base_context(cls, info: Any, action: str) -> Dict[str, Any]:
        raw = cls._raw_object(info)
        item = cls._raw_item(info)
        title = (
            item.get("SeriesName") or item.get("grandparentTitle") or raw.get("SeriesName")
            or item.get("Name") or item.get("title") or raw.get("Name")
            or getattr(info, "item_name", None) or "未知媒体"
        )
        year = item.get("ProductionYear") or raw.get("Year") or item.get("year") or ""
        season = item.get("ParentIndexNumber", item.get("parentIndex"))
        episode = item.get("IndexNumber", item.get("index"))
        season = season if season is not None else getattr(info, "season_id", None)
        episode = episode if episode is not None else getattr(info, "episode_id", None)
        season_episode = ""
        if season is not None and episode is not None:
            try:
                season_episode = f"S{int(season):02d}E{int(episode):02d}"
            except (TypeError, ValueError):
                season_episode = f"S{season}E{episode}"
            episode_name = item.get("Name") or item.get("title") or raw.get("Name")
            if episode_name and str(episode_name) not in str(title):
                season_episode += f" - {episode_name}"
        client = (
            getattr(info, "client", None) or raw.get("ClientName")
            or raw.get("Client") or raw.get("App") or raw.get("AppName") or ""
        )
        device_name = getattr(info, "device_name", None) or raw.get("DeviceName") or ""
        percentage = getattr(info, "percentage", None)
        progress = ""
        if percentage is not None:
            try:
                progress = f"{float(percentage):.2f}".rstrip("0").rstrip(".") + "%"
            except (TypeError, ValueError):
                progress = str(percentage)
        raw_server = raw.get("Server")
        raw_server_name = raw_server.get("Name", "") if isinstance(raw_server, dict) else ""
        return {
            "_action": action,
            "channel": getattr(info, "channel", ""),
            "server": getattr(info, "server_name", "") or raw.get("ServerName") or raw_server_name,
            "title": title,
            "display_name": f"{title} ({year})" if year and str(year) not in str(title) else title,
            "year": year,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "library": "",
            "season_episode": season_episode,
            "rating": "",
            "region": "",
            "actors": "",
            "overview": getattr(info, "overview", "") or raw.get("Overview") or item.get("Overview") or "",
            "user": (
                getattr(info, "user_name", None) or raw.get("NotificationUsername")
                or raw.get("Username") or raw.get("UserName") or ""
            ),
            "device": " · ".join(
                value for value in (str(device_name).strip(), str(client).strip()) if value
            ),
            "client": client,
            "ip": (
                getattr(info, "ip", None) or raw.get("RemoteEndPoint")
                or raw.get("DeviceIP") or raw.get("DeviceIp") or ""
            ),
            "progress": progress,
            "tmdb_url": "",
            "media_source": "",
            "media_id": "",
            "_image": getattr(info, "image_url", None),
            "_link": None,
        }

    def _dedupe_key(self, info: Any, action: str, context: Mapping[str, Any]) -> str:
        raw = self._raw_object(info)
        raw_session = raw.get("Session")
        raw_session_id = raw_session.get("Id") if isinstance(raw_session, dict) else None
        session = getattr(info, "session_id", None) or raw_session_id
        parts = [
            context.get("server"), context.get("channel"), action,
            getattr(info, "item_id", None),
        ]
        if action.startswith("playback_"):
            parts.extend([session, context.get("user"), context.get("client"), context.get("device")])
        elif action in {"auth_success", "auth_failed"}:
            parts.extend([
                context.get("user"), context.get("ip"),
                context.get("client"), context.get("device"), session,
            ])
        return "|".join(str(part or "") for part in parts)

    def _is_duplicate(self, info: Any, action: str, context: Mapping[str, Any]) -> bool:
        ttl = self._dedupe_playback if action.startswith("playback_") else self._dedupe_library
        if ttl <= 0:
            return False
        key = self._dedupe_key(info, action, context)
        now = time.monotonic()
        with self._condition:
            if not self._context_is_current(context):
                return True
            expired = [item for item, expiry in self._dedupe_cache.items() if expiry <= now]
            for item in expired:
                self._dedupe_cache.pop(item, None)
            if self._dedupe_cache.get(key, 0) > now:
                return True
            self._dedupe_cache[key] = now + ttl
        return False

    def _should_aggregate(self, info: Any, action: str) -> bool:
        return bool(
            self._aggregate_enabled
            and action == "library_added"
            and str(getattr(info, "item_type", "")) in {"TV", "SHOW"}
        )

    def _aggregate_key(self, info: Any, context: Mapping[str, Any]) -> str:
        item = self._raw_item(info)
        series_id = item.get("SeriesId") or item.get("grandparentRatingKey")
        identity = series_id or context.get("media_id") or item.get("SeriesName") or context.get("title")
        return "|".join(str(value or "") for value in (
            context.get("server"), context.get("channel"), context.get("media_source"), identity,
        ))

    def _queue_aggregate(self, info: Any, context: Dict[str, Any]) -> None:
        key = self._aggregate_key(info, context)
        with self._condition:
            if not self._accepting_events or not self._context_is_current(context):
                return
            self._owned_timers = {timer for timer in self._owned_timers if timer.is_alive()}
            self._pending_messages.setdefault(key, []).append(dict(context))
            previous = self._aggregate_timers.get(key)
            if previous:
                previous.cancel()
            timer = threading.Timer(self._aggregate_time, self._aggregate_timer_callback, [key, self._generation])
            timer.daemon = True
            self._aggregate_timers[key] = timer
            self._owned_timers.add(timer)
            timer.start()

    def _aggregate_timer_callback(self, key: str, generation: int) -> None:
        timer = threading.current_thread()
        try:
            with self._condition:
                if not self._accepting_events or self._aggregate_timers.get(key) is not timer:
                    return
            self._flush_aggregate(key, expected_generation=generation)
        finally:
            with self._condition:
                if self._aggregate_timers.get(key) is timer:
                    self._aggregate_timers.pop(key, None)
                self._condition.notify_all()

    def _flush_aggregate(
        self, key: str, *, expected_generation: Optional[int] = None, allow_stopped: bool = False
    ) -> None:
        with self._condition:
            if expected_generation is not None and expected_generation != self._generation:
                return
            messages = self._pending_messages.pop(key, [])
        if not messages:
            return
        context = dict(messages[0])
        episodes = []
        for message in messages:
            value = str(message.get("season_episode") or "").strip()
            if value and value not in episodes:
                episodes.append(value)
        context["season_episode"] = "、".join(episodes)
        context["file_count"] = str(len(messages))
        self._send_context("library_added", context, allow_stopped=allow_stopped)

    def _send_context(self, action: str, context: Dict[str, Any], *, allow_stopped: bool = False) -> None:
        with self._condition:
            if not allow_stopped and not self._context_is_current(context):
                return
            renderer = self._renderer
        title, body = renderer.render(action, context)
        # 登录和测试通知不属于媒体卡片，不附带 TMDB 跳转。
        if action in {"auth_success", "auth_failed", "test"}:
            context["_link"] = None
        else:
            # MoviePilot 的 link 会让整张消息卡片可点击；优先跳转 TMDB。
            context["_link"] = context.get("tmdb_url") or context.get("_link")
        with self._condition:
            if not allow_stopped and not self._context_is_current(context):
                return
        self.post_message(
            mtype=self._notification_type,
            title=title,
            text=body,
            image=context.get("_image"),
            link=context.get("_link"),
        )

    def _send_template_test(self, action: str) -> None:
        """使用稳定的示例字段测试指定通知排版。"""
        if action not in ACTION_LABELS:
            action = "library_added"
        sample = {
            "channel": "emby", "server": "家庭媒体库", "title": "示例影片",
            "display_name": "示例影片 (2026)", "year": "2026",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "season_episode": "S01E02 - 示例集",
            "rating": "8.6/10", "region": "中国大陆", "actors": "演员甲、演员乙",
            "overview": "这是一段用于检查自定义通知排版的示例简介。", "user": "测试用户",
            "device": "MoviePilot 测试设备 · Emby", "client": "Emby",
            "ip": "192.0.2.1 中国 上海",
            "progress": "36%", "tmdb_url": "https://www.themoviedb.org/movie/1",
            "media_source": "themoviedb", "media_id": "1", "file_count": "3",
            "library": "电影库",
            "_image": "https://image.tmdb.org/t/p/w500/1E5baAaEse26fej7uHcjOgEE2t2.jpg",
            "_link": None,
        }
        self._send_context(action, sample)

    def _quiesce(self, flush: Optional[bool] = None) -> bool:
        if not hasattr(self, "_condition"):
            return True
        should_flush = self._flush_on_stop if flush is None and hasattr(self, "_flush_on_stop") else bool(flush)
        deadline = time.monotonic() + self.SHUTDOWN_TIMEOUT
        with self._condition:
            self._accepting_events = False
            self._generation += 1
            timers = set(self._owned_timers) | set(self._aggregate_timers.values())
            pending_keys = list(self._pending_messages)
            for timer in timers:
                timer.cancel()
        for timer in timers:
            if timer is threading.current_thread():
                continue
            try:
                timer.join(timeout=max(0.0, deadline - time.monotonic()))
            except RuntimeError:
                pass
        if should_flush:
            for key in pending_keys:
                self._flush_aggregate(key, allow_stopped=True)
        with self._condition:
            while self._active_operations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            alive = {timer for timer in timers if timer.is_alive()}
            self._aggregate_timers.clear()
            self._pending_messages.clear()
            self._dedupe_cache.clear()
            if alive or self._active_operations:
                self._owned_timers = alive
                return False
            self._owned_timers.clear()
        return True

    def close(self) -> bool:
        return self._quiesce()

    def stop_service(self) -> bool:
        return self._quiesce()

    # 以下方法由 V2/V3 适配入口实现。
    def _server_options(self) -> List[Dict[str, str]]:
        raise NotImplementedError

    def _discover_libraries(self) -> List[Dict[str, Any]]:
        return []

    def _service_allowed(self, info: Any) -> bool:
        raise NotImplementedError

    def _enrich_context(self, info: Any, context: Dict[str, Any]) -> None:
        raise NotImplementedError

    def _log_debug(self, message: str) -> None:
        raise NotImplementedError

    def _log_error(self, message: str) -> None:
        raise NotImplementedError
