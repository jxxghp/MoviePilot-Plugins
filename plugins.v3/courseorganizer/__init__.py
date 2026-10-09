import logging
import ctypes
import errno
import hashlib
import json
import os
import stat
import re
import shutil
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ORIGINAL_LINK = os.link

try:
    from fastapi import Body
    from fastapi import Depends
    from fastapi import HTTPException
except Exception:
    class HTTPException(Exception):
        def __init__(self, *_, status_code: int = 500, detail: str = "") -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    def Body(default: Any = None, **_: Any) -> Any:
        return default

    def Depends(default: Any = None) -> Any:
        return default

try:
    from app.api.deps import get_current_active_superuser
except Exception:
    get_current_active_superuser = None


def _review_auth_unavailable_dependency() -> Any:
    raise HTTPException(
        status_code=503,
        detail="课程人工复核权限依赖未就绪",
    )

REVIEW_AUTH_DEPENDENCY = (
    get_current_active_superuser
    if get_current_active_superuser is not None
    else _review_auth_unavailable_dependency
)

try:
    from app.sdk.logging import logger as _logger
except Exception:
    _logger = logging.getLogger("CourseOrganizer")

try:
    from app.plugins import _PluginBase
except Exception:

    class _PluginBase:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._config: Dict[str, Any] = kwargs.get("config", {})
            self._data: Dict[str, Any] = {}

        def get_config(self) -> Dict[str, Any]:
            return self._config

        def get_data(self, key: str, default: Any = None) -> Any:
            return self._data.get(key, default)

        def save_data(self, key: str, value: Any) -> None:
            if value is None:
                self._data.pop(key, None)
            else:
                self._data[key] = value

        def update_config(self, config: Dict[str, Any]) -> None:
            self._config.update(config)

try:
    from app import schemas as _schemas
except Exception:
    _schemas = None

try:
    from app.chain.storage import StorageChain as _HostStorageChain
    from app.chain.transfer import TransferChain as _HostTransferChain
    from app.db.oper.systemconfig import SystemConfigOper as _HostSystemConfigOper
    from app.schemas.types import (
        ChainEventType as _HostChainEventType,
        MediaSource as _HostMediaSource,
        MediaType as _HostMediaType,
        SystemConfigKey as _HostSystemConfigKey,
    )
    from app.sdk.events import eventmanager as _host_eventmanager
except Exception:
    _HostStorageChain = None
    _HostTransferChain = None
    _HostSystemConfigOper = None
    _HostChainEventType = None
    _HostMediaSource = None
    _HostMediaType = None
    _HostSystemConfigKey = None
    _host_eventmanager = None

from . import naming
from .providers import (
    LibraryRouteResult,
    MoviePilotAIReviewer,
    MoviePilotLibraryClassifier,
    MoviePilotMetadataProvider,
)
from .resolver import NamingConfig, NamingDecision, SmartNamingResolver


_NATURAL_SPLIT_RE = re.compile(r"(\d+)")
_INVALID_NAME_RE = re.compile(r"[\\/:*?\"<>|]+")
_LEADING_EPISODE_RE = re.compile(r"^(0*\d+)(?=[\s._\-、，—–·．・]|$)")
_RANGE_BOUNDARY = r"(?=$|[\s._\-、，—–·．・])"
_LEADING_BARE_RANGE_RE = re.compile(
    rf"^(?P<start>0*\d+)\s*-\s*(?P<end>0*\d+){_RANGE_BOUNDARY}"
)
_LEADING_EN_RANGE_RE = re.compile(
    rf"^(?:EP?|ep?)\s*(?P<start>0*\d+)\s*-\s*(?:EP?|ep?)?\s*(?P<end>0*\d+){_RANGE_BOUNDARY}"
)
_LEADING_CN_RANGE_RE = re.compile(
    r"^第\s*(?P<start>0*\d+)\s*-\s*(?P<end>0*\d+)\s*集"
)
_LEADING_RANGE_CANDIDATE_RE = re.compile(
    r"^(?:(?:EP?|ep?)\s*)?(?P<start>0*\d+)\s*-\s*(?:(?:EP?|ep?)\s*)?(?P<end>0*\d+)"
)
_CHINESE_NUMERAL_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_CHILD_AUDIENCE_TERMS = ("儿童", "少儿", "幼儿", "早教", "宝宝", "亲子")
_CHILD_AUDIENCE_RE = re.compile("|".join(re.escape(term) for term in _CHILD_AUDIENCE_TERMS))
_MANUAL_DATA_UNSET = object()
_NATIVE_ADAPTER_UNSET = object()


class _MoviePilotNativeAdapter:
    """MoviePilot V3 bridge using public chains, SDK events and config storage."""

    def __init__(
        self,
        system_config_oper: Any,
        storage_chain: Any,
        transfer_chain: Any,
        chain_event_type: Any,
        event_manager: Any,
        media_source: Any,
        media_type: Any,
        system_config_key: Any,
        directory_model: Any,
    ) -> None:
        self.system_config_oper = system_config_oper
        self.storage_chain = storage_chain
        self.transfer_chain = transfer_chain
        self.chain_event_type = chain_event_type
        self.event_manager = event_manager
        self.media_source = media_source
        self.media_type = media_type
        self.system_config_key = system_config_key
        self.directory_model = directory_model
        self._rename_local = threading.local()

    @classmethod
    def load(cls) -> Optional["_MoviePilotNativeAdapter"]:
        directory_model = (
            getattr(_schemas, "TransferDirectoryConf", None)
            if _schemas is not None
            else None
        )
        if any(
            item is None
            for item in (
                _HostStorageChain,
                _HostTransferChain,
                _HostSystemConfigOper,
                _HostChainEventType,
                _HostMediaSource,
                _HostMediaType,
                _HostSystemConfigKey,
                _host_eventmanager,
                directory_model,
            )
        ):
            return None
        return cls(
            system_config_oper=_HostSystemConfigOper,
            storage_chain=_HostStorageChain,
            transfer_chain=_HostTransferChain,
            chain_event_type=_HostChainEventType,
            event_manager=_host_eventmanager,
            media_source=_HostMediaSource,
            media_type=_HostMediaType,
            system_config_key=_HostSystemConfigKey,
            directory_model=directory_model,
        )

    def get_directory_rules(self) -> List[Any]:
        raw_rules = self.system_config_oper().get(self.system_config_key.Directories) or []
        return [
            self.directory_model(**rule) if isinstance(rule, dict) else rule
            for rule in raw_rules
        ]

    def get_file_item(self, source_path: str, source_storage: str = "local") -> Any:
        chain = self.storage_chain()
        return chain.get_file_item(storage=source_storage, path=Path(source_path))

    def manual_transfer(self, **kwargs: Any) -> Any:
        chain = self.transfer_chain()
        if isinstance(kwargs.get("media_source"), str):
            kwargs["media_source"] = self.media_source(kwargs["media_source"])
        if self.media_type is not None and isinstance(kwargs.get("mtype"), str):
            try:
                kwargs["mtype"] = (
                    self.media_type.MOVIE
                    if kwargs["mtype"] == "movie"
                    else self.media_type.TV
                )
            except Exception:
                pass
        return chain.manual_transfer(**kwargs)

    @contextmanager
    def rename_context(self, source_tree: str, final_title: str):
        if self.event_manager is None or self.chain_event_type is None:
            raise RuntimeError("MoviePilot rename event unavailable")
        event_type = getattr(self.chain_event_type, "TransferRenameBuild", None)
        if event_type is None:
            raise RuntimeError("MoviePilot TransferRenameBuild unavailable")
        previous = getattr(self._rename_local, "context", None)
        context = {
            "thread_id": threading.get_ident(),
            "source_tree": os.path.realpath(os.path.abspath(source_tree)),
            "title": final_title,
        }
        self._rename_local.context = context

        def handler(event: Any) -> None:
            active = getattr(self._rename_local, "context", None)
            if active is not context or active["thread_id"] != threading.get_ident():
                return
            data = getattr(event, "event_data", None)
            rename_dict = getattr(data, "rename_dict", None)
            source_path = getattr(data, "source_path", None)
            if not isinstance(rename_dict, dict) or not isinstance(
                source_path, (str, os.PathLike)
            ):
                return
            try:
                source_path = os.fspath(source_path)
                inside = os.path.commonpath(
                    (active["source_tree"], os.path.realpath(os.path.abspath(source_path)))
                ) == active["source_tree"]
            except (OSError, ValueError):
                inside = False
            if inside:
                rename_dict["title"] = active["title"]
                rename_dict.pop("year", None)

        # MoviePilot invokes dotted qualnames through its object registry. A unique
        # top-level-style qualname keeps this scoped callback direct and collision-free.
        handler.__qualname__ = (
            f"_courseorganizer_rename_{id(self)}_{threading.get_ident()}"
        )

        try:
            self.event_manager.add_event_listener(event_type, handler)
        except Exception as exc:
            self._rename_local.context = previous
            raise RuntimeError("MoviePilot rename event registration failed") from exc
        try:
            yield
        finally:
            try:
                self.event_manager.remove_event_listener(event_type, handler)
            finally:
                self._rename_local.context = previous


def _cn_num(token: str) -> int:
    """把中文数字（一二三…十/百）或阿拉伯数字字符串转成 int。"""
    t = str(token or "").strip()
    if not t:
        return 1
    if t.isdigit():
        return int(t)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if t in digits:
        return digits[t]
    if t == "十":
        return 10
    # 十几 / 几十
    if len(t) == 2:
        if t[0] == "十":
            return 10 + digits.get(t[1], 0)
        return digits.get(t[0], 0) * 10 + digits.get(t[1], 0)
    try:
        return int(t)
    except (TypeError, ValueError):
        return 1


def _assert_no_symlink_entries(source: str) -> None:
    """Fail closed when a direct-transfer source tree contains a symlink."""
    def _raise_walk_error(error: OSError) -> None:
        raise error

    if os.path.islink(source):
        raise ValueError("source_symlink")
    for root, dirs, files in os.walk(
        source, followlinks=False, onerror=_raise_walk_error
    ):
        for name in (*dirs, *files):
            if os.path.islink(os.path.join(root, name)):
                raise ValueError("source_tree_symlink")


def _link_files_recursive(source: str, dest: str) -> None:
    """递归地把源目录的内容硬链（优先）或复制到目标目录；用于 hardlink/softlink 搬运。"""
    _assert_no_symlink_entries(source)
    dest = os.path.abspath(dest)
    os.makedirs(dest, exist_ok=True)
    for root, dirs, files in os.walk(source):
        rel = os.path.relpath(root, source)
        target_dir = dest if rel == "." else os.path.join(dest, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            src_file = os.path.join(root, name)
            dst_file = os.path.join(target_dir, name)
            linked = False
            try:
                os.link(src_file, dst_file)
                linked = True
            except OSError:
                linked = False
            if not linked:
                shutil.copy2(src_file, dst_file)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"false", "0", "no", "off", ""}:
            return False
        if lower in {"true", "1", "yes", "on", "y", "t"}:
            return True
        return default
    if value is None:
        return default
    return bool(value)
_EN_SEASON_RE = re.compile(r"(?i)\bseason\s*([0-9]{1,3})\b|\bs\s*([0-9]{1,3})\b")
_CN_SEASON_RE = re.compile(r"第\s*([0-9零一二三四五六七八九十]+)\s*季")


class CourseOrganizer(_PluginBase):
    plugin_name = "按文件夹分类整理"
    plugin_config_prefix = "courseorganizer_"
    auth_level = 1
    plugin_order = 90
    plugin_version = "2.0.10"
    plugin_desc = "稳定后识别、分类并整理到电视剧、电影或儿童媒体库"
    plugin_author = "OneBigMoon"
    author_url = "https://github.com/OneBigMoon"
    project_url = "https://github.com/OneBigMoon/moviepilot-v2-course-organizer"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/courseorganizer.png"
    plugin_repo = "https://github.com/OneBigMoon/moviepilot-v2-course-organizer"

    MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".m4a"}
    SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".vtt"}
    INCOMPLETE_SUFFIXES = (".partial", ".part", ".tmp", ".crdownload", ".incomplete", ".!qb")
    SYSTEM_SCAN_ENTRY_NAMES = frozenset({"#recycle", "@eadir", ".ds_store", "thumbs.db", "desktop.ini"})
    DEFAULT_INTERVAL = 300
    DEFAULT_INCOMING = "/volume1/未整理"
    DEFAULT_TV_OUTPUT = "/volume1/TV"
    DEFAULT_MOVIE_OUTPUT = "/volume1/Movies"
    DEFAULT_CHILDREN_OUTPUT = "/volume1/儿童"
    MANUAL_DECISIONS_KEY = "naming_manual_decisions_v1"
    MANUAL_DECISIONS_SCHEMA = 1
    MANUAL_DECISIONS_MAX = 500
    MANUAL_PERSIST_ATTEMPTS = 2

    _thread_lock = threading.RLock()
    # Protects the manual-decisions read-modify-write sequence; independent from the
    # move lock so that TMDB search/associate never block a running confirmation move.
    _review_data_lock = threading.RLock()
    # MoviePilot update_config persists only; this lock linearizes persistence and cancellation.
    _run_once_lock = threading.Lock()
    _run_once_timer: Optional[threading.Timer] = None
    _run_once_owner: Optional["CourseOrganizer"] = None
    _run_once_claimed = False
    _run_once_generation = 0
    _run_once_token: Optional[int] = None

    def __init__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self._metadata_provider_override = kwargs.pop("metadata_provider", None)
        self._ai_reviewer_override = kwargs.pop("ai_reviewer", None)
        self._library_classifier_override = kwargs.pop("library_classifier", None)
        self._native_adapter_override = kwargs.pop(
            "native_adapter", _NATIVE_ADAPTER_UNSET
        )
        self._native_adapter: Any = None
        self._native_adapter_loaded = False
        self._clock = kwargs.pop("clock", time.time)
        super().__init__(*args, **kwargs)
        self._config_snapshot: Dict[str, Any] = self._normalize_config(kwargs.get("config", {}))
        self._resolver: Optional[SmartNamingResolver] = None
        self._resolver_signature: Tuple[Any, ...] = ()
        self._library_classifier: Optional[MoviePilotLibraryClassifier] = None
        self._logger = _logger
        self._run_config_local = threading.local()

    def _get_native_adapter(self) -> Any:
        if self._native_adapter_override is not _NATIVE_ADAPTER_UNSET:
            return self._native_adapter_override
        if not self._native_adapter_loaded:
            self._native_adapter = _MoviePilotNativeAdapter.load()
            self._native_adapter_loaded = True
        return self._native_adapter

    def _moviepilot_host_present(self) -> bool:
        if self._native_adapter_override is not _NATIVE_ADAPTER_UNSET:
            return True
        return all(
            item is not None
            for item in (
                _HostStorageChain,
                _HostTransferChain,
                _HostSystemConfigOper,
            )
        )

    def _load_plugin_data(self, key: str, default: Any) -> Any:
        try:
            value = self.get_data(key)
        except Exception:
            return default
        return default if value is None else value

    def _build_resolver(self, config: Dict[str, Any]) -> SmartNamingResolver:
        provider = self._metadata_provider_override or MoviePilotMetadataProvider()
        reviewer = None
        if config.get("naming_ai_review"):
            reviewer = self._ai_reviewer_override or MoviePilotAIReviewer()

        return SmartNamingResolver(
            load_data=self._load_plugin_data,
            save_data=self.save_data,
            provider=provider,
            ai_reviewer=reviewer,
            clock=self._clock,
        )

    def init_plugin(self, config: Optional[Dict[str, Any]] = None):
        self._config_snapshot = self._normalize_config(config)
        plugin_cls = type(self)

        if bool(self._config_snapshot.get("naming_clear_cache_once")):
            self._build_resolver(self._config_snapshot).clear()
            self.save_data("library_routing_cache_v1", {})
            reset = dict(self._config_snapshot)
            reset["naming_clear_cache_once"] = False
            self._persist_config(reset)
            self._config_snapshot = reset

        if self._config_snapshot.get("run_once"):
            with plugin_cls._run_once_lock:
                timer = plugin_cls._run_once_timer
                pending_config = dict(self._config_snapshot)
                pending_config["run_once"] = True
                if timer is not None and timer.is_alive():
                    if not self._persist_config(pending_config):
                        self._logger.error(
                            "CourseOrganizer[event=run_once_persist_failed] phase=pending"
                        )
                        return
                    plugin_cls._run_once_owner = self
                    self._config_snapshot = pending_config
                    self._logger.info(
                        "CourseOrganizer[event=run_once_coalesced] pending=true"
                    )
                    return

                if not self._persist_config(pending_config):
                    plugin_cls._invalidate_run_once_locked()
                    self._logger.error(
                        "CourseOrganizer[event=run_once_persist_failed] phase=pending"
                    )
                    return
                self._config_snapshot = pending_config
                plugin_cls._run_once_owner = self
                plugin_cls._run_once_claimed = False
                plugin_cls._run_once_generation += 1
                token = plugin_cls._run_once_generation
                plugin_cls._run_once_token = token
                self._logger.info(
                    "CourseOrganizer[event=run_once_scheduled] delay=0.2"
                )
                timer = None
                try:
                    timer = threading.Timer(
                        0.2,
                        lambda token=token: plugin_cls._run_once_dispatch(token),
                    )
                    timer.daemon = True
                    plugin_cls._run_once_timer = timer
                    timer.start()
                except Exception as exc:
                    plugin_cls._run_once_timer = None
                    plugin_cls._run_once_owner = None
                    plugin_cls._run_once_claimed = False
                    plugin_cls._run_once_token = None
                    if timer is not None:
                        try:
                            timer.cancel()
                        except Exception:
                            pass
                    self._logger.error(
                        "CourseOrganizer[event=run_once_schedule_failed] phase=%s error=%s",
                        "start" if timer is not None else "construct",
                        exc.__class__.__name__,
                    )
            return

        with plugin_cls._run_once_lock:
            timer = plugin_cls._run_once_timer
            if timer is not None and timer.is_alive():
                pending_config = dict(self._config_snapshot)
                pending_config["run_once"] = True
                if not self._persist_config(pending_config):
                    self._logger.error(
                        "CourseOrganizer[event=run_once_persist_failed] phase=pending"
                    )
                    return
                plugin_cls._run_once_owner = self
                self._config_snapshot = pending_config

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_api(self) -> List[Dict[str, Any]]:
        routes = [
            {
                "path": "/review",
                "endpoint": self.get_review_route,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取课程人工复核预览",
            },
            {
                "path": "/review",
                "endpoint": self.save_review_route,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存课程人工复核决定",
            },
            {
                "path": "/review/refresh",
                "endpoint": self.refresh_review_route,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "重新扫描课程人工复核预览",
            },
            {
                "path": "/review/tmdb/search",
                "endpoint": self.search_tmdb_route,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "按课程名称搜索 TMDB 候选",
            },
            {
                "path": "/review/tmdb/associate",
                "endpoint": self.associate_tmdb_route,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存人工 TMDB 关联",
            },
        ]
        if _schemas is not None and hasattr(_schemas, "Response"):
            response_model = _schemas.Response[Dict[str, Any]]
            for route in routes:
                route["response_model"] = response_model
        return routes

    @staticmethod
    def _review_response(success: bool, data: Any = None, message: str = "") -> Any:
        if _schemas is not None and hasattr(_schemas, "Response"):
            return _schemas.Response(success=success, data=data, message=message)
        return {"success": success, "data": data, "message": message}

    @staticmethod
    def _is_active_superuser(user: Any) -> bool:
        if isinstance(user, dict):
            return bool(user.get("is_superuser")) and bool(user.get("is_active", True))
        return bool(getattr(user, "is_superuser", False)) and bool(
            getattr(user, "is_active", True)
        )

    @classmethod
    def _require_review_superuser(cls, user: Any) -> None:
        if not cls._is_active_superuser(user):
            raise HTTPException(status_code=403, detail="需要超级管理员权限")

    def get_review_route(self, user: Any = Depends(REVIEW_AUTH_DEPENDENCY)) -> Any:
        self._require_review_superuser(user)
        return self.get_review()

    def refresh_review_route(self, user: Any = Depends(REVIEW_AUTH_DEPENDENCY)) -> Any:
        self._require_review_superuser(user)
        return self.refresh_review()

    def save_review_route(
        self,
        payload: Optional[Dict[str, Any]] = Body(default=None),
        user: Any = Depends(REVIEW_AUTH_DEPENDENCY),
    ) -> Any:
        self._require_review_superuser(user)
        return self.save_review(payload)

    def search_tmdb_route(
        self,
        payload: Optional[Dict[str, Any]] = Body(default=None),
        user: Any = Depends(REVIEW_AUTH_DEPENDENCY),
    ) -> Any:
        self._require_review_superuser(user)
        return self.search_tmdb(payload)

    def associate_tmdb_route(
        self,
        payload: Optional[Dict[str, Any]] = Body(default=None),
        user: Any = Depends(REVIEW_AUTH_DEPENDENCY),
    ) -> Any:
        self._require_review_superuser(user)
        return self.associate_tmdb(payload)

    @classmethod
    def _review_revision(cls, row: Dict[str, Any]) -> str:
        material = {
            key: row.get(key)
            for key in (
                "raw_title",
                "final_title",
                "target_library",
                "target_output_root",
                "status",
                "reason_codes",
                "source",
                "media_id",
                "media_type",
                "source_path",
                "source_identity",
                "source_snapshot_digest",
                "source_manifest_digest",
                "source_directory_manifest_digest",
            )
        }
        payload = json.dumps(
            material,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _review_status_label(status: str, target_library: str = "") -> str:
        if status == "ignore":
            return "已跳过"
        if status in {"auto_external", "local_fallback"} and target_library:
            return "可以整理"
        return "需要确认"

    @staticmethod
    def _recognition_source_label(
        source: str,
        reason_codes: Any = (),
        manual_action: str = "",
    ) -> str:
        if manual_action == "confirm":
            return "人工"
        if manual_action == "candidate":
            return "TMDB"
        reasons = {
            str(item).strip().lower()
            for item in (reason_codes if isinstance(reason_codes, (list, tuple, set)) else ())
        }
        if "ai_review" in reasons:
            return "DeepSeek"
        normalized = str(source or "").strip().lower()
        if normalized == "themoviedb":
            return "TMDB"
        if normalized == "douban":
            return "豆瓣"
        return "本地"

    @staticmethod
    def _directory_rule_value(rule: Any, key: str, default: Any = None) -> Any:
        if isinstance(rule, dict):
            return rule.get(key, default)
        return getattr(rule, key, default)

    @staticmethod
    def _paths_overlap(first: Any, second: Any) -> bool:
        """Return whether two local paths are equal or one contains the other."""
        if not first or not second:
            return False
        try:
            first_path = os.path.normcase(
                os.path.realpath(os.path.abspath(os.path.expanduser(str(first))))
            )
            second_path = os.path.normcase(
                os.path.realpath(os.path.abspath(os.path.expanduser(str(second))))
            )
            return os.path.commonpath((first_path, second_path)) in {
                first_path,
                second_path,
            }
        except (OSError, TypeError, ValueError):
            return False

    @staticmethod
    def _monitoring_conflict_message(context: Dict[str, Any]) -> str:
        if not context.get("monitoring_enabled"):
            return ""
        incoming = str(context.get("incoming", "") or "").strip()
        rules = [str(item) for item in context.get("monitoring_rules", []) if item]
        rule_text = "、".join(rules) or "相关目录规则"
        source_text = f"来源目录 {incoming}" if incoming else "当前来源目录"
        return (
            f"已自动检测到 {source_text} 与 MoviePilot 自动监控规则（{rule_text}）重叠；"
            "为避免两个任务竞争文件，本插件已强制保持安全预览并禁止自动整理。"
        )

    def _load_moviepilot_directory_rules(self) -> Tuple[List[Any], str]:
        """Read MoviePilot's directory rules without making them a plugin setting."""
        try:
            adapter = self._get_native_adapter()
            if adapter is None or not hasattr(adapter, "get_directory_rules"):
                raise RuntimeError("native adapter unavailable")
            return list(adapter.get_directory_rules() or []), ""
        except Exception as exc:
            self._logger.warning(
                "CourseOrganizer[event=directory_rules_unavailable] reason=%s",
                exc.__class__.__name__,
            )
            return [], "MoviePilot 目录规则暂时不可读取"

    @classmethod
    def _directory_rule_library(cls, rule: Any) -> str:
        name = str(cls._directory_rule_value(rule, "name", "") or "")
        media_type = str(
            cls._directory_rule_value(rule, "media_type", "") or ""
        ).strip()
        if media_type == "电影":
            return "movie"
        category = str(
            cls._directory_rule_value(
                rule,
                "media_category",
                cls._directory_rule_value(rule, "category", ""),
            )
            or ""
        ).strip()
        # MoviePilot already has a media-category field. Prefer that system
        # declaration and retain alias matching only for older directory data.
        descriptor = f"{category} {name}".lower()
        if any(
            token in descriptor
            for token in ("儿童", "少儿", "幼儿", "课程", "早教", "宝宝", "亲子")
        ):
            return "children"
        if media_type == "电视剧":
            return "tv"
        return ""

    def _moviepilot_directory_context(self) -> Dict[str, Any]:
        rules, load_error = self._load_moviepilot_directory_rules()
        labels = {"tv": "电视剧", "movie": "电影", "children": "儿童课程"}
        grouped: Dict[str, List[Dict[str, Any]]] = {key: [] for key in labels}
        summaries: List[Dict[str, Any]] = []
        issues: List[str] = []

        for rule in rules:
            library = self._directory_rule_library(rule)
            if not library:
                continue
            download_path = str(
                self._directory_rule_value(rule, "download_path", "") or ""
            ).strip()
            library_path = str(
                self._directory_rule_value(rule, "library_path", "") or ""
            ).strip()
            storage = str(
                self._directory_rule_value(rule, "storage", "local") or "local"
            ).strip()
            library_storage = str(
                self._directory_rule_value(rule, "library_storage", "local")
                or "local"
            ).strip()
            if not download_path or not library_path:
                issues.append(f"{labels[library]}规则缺少来源或目标目录")
                continue
            if storage != "local" or library_storage != "local":
                issues.append(f"{labels[library]}规则不是本地存储，当前复核台不能处理")
                continue
            rule_alias = str(
                self._directory_rule_value(rule, "name", "") or labels[library]
            )
            media_category = str(
                self._directory_rule_value(
                    rule,
                    "media_category",
                    self._directory_rule_value(rule, "category", ""),
                )
                or ""
            ).strip()
            summary = {
                "title": rule_alias,
                "value": library,
                "name": rule_alias,
                "media_category": media_category,
                "download_path": download_path,
                "path": library_path,
                "monitor_type": str(
                    self._directory_rule_value(rule, "monitor_type", "") or ""
                ),
                "storage": storage,
                "library_storage": library_storage,
                "transfer_type": str(
                    self._directory_rule_value(rule, "transfer_type", "") or ""
                ),
                "renaming": bool(self._directory_rule_value(rule, "renaming", False)),
                "scraping": bool(self._directory_rule_value(rule, "scraping", False)),
                "notify": bool(self._directory_rule_value(rule, "notify", True)),
                "library_type_folder": bool(
                    self._directory_rule_value(rule, "library_type_folder", False)
                ),
                "library_category_folder": bool(
                    self._directory_rule_value(rule, "library_category_folder", False)
                ),
                "naming_format": str(
                    self._directory_rule_value(rule, "naming_format", "") or ""
                ).strip(),
                "movie_naming_format": str(
                    self._directory_rule_value(rule, "movie_naming_format", "") or ""
                ).strip(),
            }
            grouped[library].append(summary)
            summaries.append(summary)
            if not summary["renaming"]:
                issues.append(f"{rule_alias}规则未开启智能重命名")

        selected: Dict[str, Dict[str, Any]] = {}
        for library, candidates in grouped.items():
            if not candidates:
                issues.append(f"缺少{labels[library]}目录规则")
            elif len(candidates) > 1:
                issues.append(f"{labels[library]}存在多条匹配规则，请在 MoviePilot 中保留一条明确规则")
            else:
                selected[library] = candidates[0]

        source_paths = {
            item["download_path"] for item in selected.values() if item["download_path"]
        }
        incoming = next(iter(source_paths)) if len(source_paths) == 1 else ""
        if len(source_paths) > 1:
            issues.append("三类规则的来源目录不一致，无法确定唯一待处理目录")

        monitoring_conflicts: List[Dict[str, str]] = []
        if incoming:
            for rule in rules:
                monitor_type = str(
                    self._directory_rule_value(rule, "monitor_type", "") or ""
                ).strip()
                monitor_path = str(
                    self._directory_rule_value(rule, "download_path", "") or ""
                ).strip()
                storage = str(
                    self._directory_rule_value(rule, "storage", "local") or "local"
                ).strip()
                if (
                    monitor_type
                    and storage == "local"
                    and self._paths_overlap(incoming, monitor_path)
                ):
                    monitoring_conflicts.append(
                        {
                            "title": str(
                                self._directory_rule_value(rule, "name", "")
                                or monitor_path
                                or "未命名规则"
                            ),
                            "path": monitor_path,
                            "monitor_type": monitor_type,
                        }
                    )

        if load_error:
            issues.insert(0, load_error)
        libraries = [selected[key] for key in ("tv", "movie", "children") if key in selected]
        return {
            "available": not load_error,
            "incoming": incoming,
            "libraries": libraries,
            "rules": summaries,
            "selected": selected,
            "ready": not issues and len(selected) == len(labels) and bool(incoming),
            "issues": list(dict.fromkeys(issues)),
            "message": "；".join(dict.fromkeys(issues)),
            "settings_url": "#/setting",
            "monitoring_enabled": bool(monitoring_conflicts),
            "monitoring_rules": list(
                dict.fromkeys(item["title"] for item in monitoring_conflicts)
            ),
            "monitoring_conflicts": monitoring_conflicts,
        }

    def _review_path_config(
        self, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        config = self._get_config()
        directory_context = context or self._moviepilot_directory_context()
        if not directory_context.get("available"):
            if config.get("auto_organize"):
                config["auto_organize"] = False
                config["naming_mode"] = "preview"
                config["monitoring_conflict"] = (
                    "无法读取 MoviePilot 目录监控配置；为避免重复整理，"
                    "本插件已强制保持安全预览并禁止自动整理。"
                )
            return config
        selected = directory_context.get("selected", {})
        config["incoming"] = str(directory_context.get("incoming", ""))
        for library, key in (
            ("tv", "tv_output"),
            ("movie", "movie_output"),
            ("children", "children_output"),
        ):
            config[key] = str(selected.get(library, {}).get("path", ""))
        conflict_message = self._monitoring_conflict_message(directory_context)
        if conflict_message and config.get("auto_organize"):
            config["auto_organize"] = False
            config["naming_mode"] = "preview"
            config["monitoring_conflict"] = conflict_message
        return config

    def _review_source_directory_ok(self, raw_title: str) -> bool:
        if not raw_title:
            return False
        config = self._review_path_config()
        return any(
            os.path.isdir(os.path.join(incoming, raw_title))
            for incoming in self._download_paths(config)
        )

    @staticmethod
    def _source_identity(path: str) -> Optional[Dict[str, int]]:
        try:
            info = os.stat(path, follow_symlinks=False)
        except (OSError, TypeError, ValueError):
            return None
        if not stat.S_ISDIR(info.st_mode):
            return None
        try:
            ctime_ns = int(info.st_ctime_ns)
        except AttributeError:
            ctime_ns = int(float(info.st_ctime) * 1_000_000_000)
        return {
            "st_dev": int(info.st_dev),
            "st_ino": int(info.st_ino),
            "st_ctime_ns": ctime_ns,
        }

    @staticmethod
    def _safe_log_value(value: Any) -> str:
        text = str(value)
        valid, _ = naming.validate_manual_raw_title(text)
        return text if valid else ascii(text)

    @staticmethod
    def _is_system_scan_entry(entry: str) -> bool:
        return str(entry).strip().casefold() in CourseOrganizer.SYSTEM_SCAN_ENTRY_NAMES

    @classmethod
    def _is_ignored_scan_entry(cls, entry: str) -> bool:
        """Return whether a top-level incoming entry is a system/hidden item."""
        name = str(entry).strip()
        return name.startswith(".") or cls._is_system_scan_entry(name)

    @staticmethod
    def _manifest_stat_tuple(
        relative_path: str, info: os.stat_result
    ) -> Tuple[str, int, int, int, int, int]:
        try:
            ctime_ns = int(info.st_ctime_ns)
            mtime_ns = int(info.st_mtime_ns)
        except AttributeError:
            ctime_ns = int(float(info.st_ctime) * 1_000_000_000)
            mtime_ns = int(float(info.st_mtime) * 1_000_000_000)
        return (
            relative_path,
            int(info.st_dev),
            int(info.st_ino),
            ctime_ns,
            int(info.st_size),
            mtime_ns,
        )

    @classmethod
    def _manifest_stat_matches(
        cls, info: os.stat_result, expected: Tuple[str, int, int, int, int, int]
    ) -> bool:
        return cls._manifest_stat_tuple(expected[0], info) == expected

    @staticmethod
    def _file_stat_matches(left: os.stat_result, right: os.stat_result) -> bool:
        try:
            return (
                stat.S_ISREG(left.st_mode)
                and stat.S_ISREG(right.st_mode)
                and int(left.st_dev) == int(right.st_dev)
                and int(left.st_ino) == int(right.st_ino)
                and int(left.st_ctime_ns) == int(right.st_ctime_ns)
                and int(left.st_size) == int(right.st_size)
                and int(left.st_mtime_ns) == int(right.st_mtime_ns)
            )
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _file_stat_matches_without_ctime(
        left: os.stat_result, right: os.stat_result
    ) -> bool:
        try:
            return (
                stat.S_ISREG(left.st_mode)
                and stat.S_ISREG(right.st_mode)
                and int(left.st_dev) == int(right.st_dev)
                and int(left.st_ino) == int(right.st_ino)
                and int(left.st_size) == int(right.st_size)
                and int(left.st_mtime_ns) == int(right.st_mtime_ns)
            )
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    @classmethod
    def _scan_manifest_dir(
        cls,
        directory_fd: int,
        relative_prefix: str = "",
        excluded_root: Optional[Tuple[str, Tuple[int, int]]] = None,
        diagnostic: Optional[List[str]] = None,
    ) -> Optional[
        Tuple[
            List[Tuple[str, int, int, int, int, int]],
            List[Tuple[str, int, int]],
        ]
    ]:
        """Build a no-follow regular-file manifest while rejecting read races."""
        def _note(reason: str) -> None:
            if diagnostic is not None:
                diagnostic.append(reason)

        try:
            before = os.fstat(directory_fd)
            if not stat.S_ISDIR(before.st_mode):
                _note(f"not-directory:{relative_prefix or '.'}")
                return None
            with os.scandir(directory_fd) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
            manifest: List[Tuple[str, int, int, int, int, int]] = []
            directories: List[Tuple[str, int, int]] = []
            if relative_prefix:
                directories.append(
                    (
                        relative_prefix,
                        int(before.st_dev),
                        int(before.st_ino),
                    )
                )
            open_flags = (
                getattr(os, "O_NOFOLLOW", 0)
                | os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            for entry in children:
                if cls._is_system_scan_entry(entry.name):
                    continue
                relative_path = (
                    f"{relative_prefix}/{entry.name}"
                    if relative_prefix
                    else entry.name
                ).replace(os.sep, "/")
                info = entry.stat(follow_symlinks=False)
                if (
                    not relative_prefix
                    and excluded_root is not None
                    and entry.name == excluded_root[0]
                    and stat.S_ISDIR(info.st_mode)
                    and (info.st_dev, info.st_ino) == excluded_root[1]
                ):
                    continue
                if stat.S_ISLNK(info.st_mode):
                    _note(f"symlink:{relative_path}")
                    return None
                if stat.S_ISDIR(info.st_mode):
                    child_fd = None
                    try:
                        child_fd = os.open(
                            entry.name,
                            open_flags | getattr(os, "O_DIRECTORY", 0),
                            dir_fd=directory_fd,
                        )
                        child_manifest = cls._scan_manifest_dir(
                            child_fd, relative_path, diagnostic=diagnostic
                        )
                    finally:
                        if child_fd is not None:
                            os.close(child_fd)
                    if child_manifest is None:
                        return None
                    manifest.extend(child_manifest[0])
                    directories.extend(child_manifest[1])
                    continue
                if not stat.S_ISREG(info.st_mode):
                    _note(f"non-regular:{relative_path}")
                    return None
                file_fd = None
                try:
                    file_fd = os.open(entry.name, open_flags, dir_fd=directory_fd)
                    first = os.fstat(file_fd)
                    expected = cls._manifest_stat_tuple(relative_path, info)
                    if not stat.S_ISREG(first.st_mode) or not cls._manifest_stat_matches(
                        first, expected
                    ):
                        _note(f"file-race:{relative_path}")
                        return None
                    second = os.fstat(file_fd)
                    if not cls._manifest_stat_matches(second, expected):
                        _note(f"file-race:{relative_path}")
                        return None
                finally:
                    if file_fd is not None:
                        os.close(file_fd)
                manifest.append(expected)
            after = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(after.st_mode)
                or (before.st_dev, before.st_ino, before.st_ctime_ns, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_ctime_ns, after.st_mtime_ns)
            ):
                _note(f"directory-race:{relative_prefix or '.'}")
                return None
            return manifest, directories
        except (OSError, TypeError, NotImplementedError, ValueError, UnicodeError) as exc:
            _note(f"error:{relative_prefix or '.'}:{exc.__class__.__name__}")
            return None

    def _source_tree_manifest(
        self, source_path: str
    ) -> Optional[
        Tuple[
            Tuple[Tuple[str, int, int, int, int, int], ...],
            Tuple[Tuple[str, int, int], ...],
        ]
    ]:
        bound = self._open_bound_root(source_path)
        if bound is None:
            self._logger.warning(
                "CourseOrganizer[event=source_manifest_open_failed] source_path=%s",
                self._safe_log_value(source_path),
            )
            return None
        try:
            diagnostic: List[str] = []
            tree = self._scan_manifest_dir(bound["fd"], diagnostic=diagnostic)
            if tree is None or not self._bound_root_is_current(bound):
                if diagnostic:
                    self._logger.warning(
                        "CourseOrganizer[event=source_manifest_rejected] source_path=%s reasons=%s",
                        self._safe_log_value(source_path),
                        ",".join(diagnostic[-8:]),
                    )
                else:
                    self._logger.warning(
                        "CourseOrganizer[event=source_manifest_rejected] source_path=%s reasons=bound_root_changed",
                        self._safe_log_value(source_path),
                    )
                return None
            manifest, directories = tree
            manifest.sort(key=lambda item: item[0])
            directories.sort(key=lambda item: item[0])
            return tuple(manifest), tuple(directories)
        except (OSError, TypeError, NotImplementedError, ValueError, UnicodeError):
            return None
        finally:
            for fd in (bound.get("parent_fd"), bound.get("fd")):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def _source_manifest(
        self, source_path: str
    ) -> Optional[Tuple[Tuple[str, int, int, int, int, int], ...]]:
        tree = self._source_tree_manifest(source_path)
        return tree[0] if tree is not None else None

    @staticmethod
    def _manifest_digest(
        manifest: Tuple[Tuple[str, int, int, int, int, int], ...]
    ) -> str:
        payload = json.dumps(
            [list(item) for item in manifest],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _directory_manifest_digest(
        manifest: Tuple[Tuple[str, int, int], ...]
    ) -> str:
        payload = json.dumps(
            [list(item) for item in manifest],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _coerce_source_manifest(
        cls, value: Any
    ) -> Optional[Tuple[Tuple[str, int, int, int, int, int], ...]]:
        if not isinstance(value, (list, tuple)):
            return None
        result: List[Tuple[str, int, int, int, int, int]] = []
        for item in value:
            if isinstance(item, dict):
                fields = (
                    item.get("relative_path"),
                    item.get("st_dev"),
                    item.get("st_ino"),
                    item.get("st_ctime_ns"),
                    item.get("st_size"),
                    item.get("st_mtime_ns"),
                )
            elif isinstance(item, (list, tuple)) and len(item) == 6:
                fields = tuple(item)
            else:
                return None
            relative_path = fields[0]
            if (
                not isinstance(relative_path, str)
                or not relative_path
                or os.path.isabs(relative_path)
                or relative_path in {".", ".."}
                or relative_path.startswith("../")
                or "\\" in relative_path
            ):
                return None
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in fields[1:]
            ):
                return None
            numbers = tuple(fields[1:])
            if any(value < 0 for value in numbers):
                return None
            result.append((relative_path, *numbers))
        normalized = tuple(sorted(result, key=lambda item: item[0]))
        if len({item[0] for item in normalized}) != len(normalized):
            return None
        return normalized

    @classmethod
    def _coerce_source_directory_manifest(
        cls, value: Any
    ) -> Optional[Tuple[Tuple[str, int, int], ...]]:
        if not isinstance(value, (list, tuple)):
            return None
        result: List[Tuple[str, int, int]] = []
        for item in value:
            if isinstance(item, dict):
                fields = (
                    item.get("relative_path"),
                    item.get("st_dev"),
                    item.get("st_ino"),
                )
            elif isinstance(item, (list, tuple)) and len(item) == 3:
                fields = tuple(item)
            else:
                return None
            relative_path = fields[0]
            if (
                not isinstance(relative_path, str)
                or not relative_path
                or os.path.isabs(relative_path)
                or relative_path in {".", ".."}
                or relative_path.startswith("../")
                or "\\" in relative_path
            ):
                return None
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in fields[1:]
            ):
                return None
            if any(value < 0 for value in fields[1:]):
                return None
            result.append((relative_path, fields[1], fields[2]))
        normalized = tuple(sorted(result, key=lambda item: item[0]))
        if len({item[0] for item in normalized}) != len(normalized):
            return None
        return normalized

    @staticmethod
    def _snapshot_digest(signature: Any) -> str:
        payload = json.dumps(
            signature if isinstance(signature, (list, tuple)) else [],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _current_source_binding(self, raw_title: str) -> Optional[Dict[str, Any]]:
        if not raw_title:
            return None
        config = self._review_path_config()
        for incoming in self._download_paths(config):
            if not os.path.isdir(incoming):
                continue
            source_path = os.path.join(incoming, raw_title)
            if not self._is_within_realpath(incoming, source_path):
                continue
            source_realpath = os.path.realpath(os.path.abspath(source_path))
            incoming_realpath = os.path.realpath(os.path.abspath(incoming))
            if source_realpath == incoming_realpath:
                continue
            identity = self._source_identity(source_path)
            if identity is None:
                continue
            tree = self._source_tree_manifest(source_realpath)
            if tree is None:
                continue
            manifest, directory_manifest = tree
            signature = [
                (item[0], item[4], item[5])
                for item in sorted(manifest, key=lambda item: self._natural_key(item[0]))
            ]
            return {
                "source_path": source_realpath,
                "source_identity": identity,
                "source_snapshot_digest": self._snapshot_digest(signature),
                "source_manifest": manifest,
                "source_manifest_digest": self._manifest_digest(manifest),
                "source_directory_manifest": directory_manifest,
                "source_directory_manifest_digest": self._directory_manifest_digest(
                    directory_manifest
                ),
            }
        return None

    @staticmethod
    def _source_bindings_equal(
        current: Optional[Dict[str, Any]], expected: Dict[str, Any]
    ) -> bool:
        keys = (
            "source_path",
            "source_identity",
            "source_snapshot_digest",
            "source_manifest_digest",
            "source_manifest",
            "source_directory_manifest_digest",
            "source_directory_manifest",
        )
        if (
            not isinstance(current, dict)
            or not isinstance(expected, dict)
            or any(key not in current or key not in expected for key in keys)
        ):
            return False
        return all(current[key] == expected[key] for key in keys)

    def _source_binding_matches(
        self,
        raw_title: str,
        expected: Dict[str, Any],
        current: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self._source_bindings_equal(
            current if current is not None else self._current_source_binding(raw_title),
            expected,
        )

    @staticmethod
    def _manual_binding(decision: naming.ManualOverride) -> Dict[str, Any]:
        return {
            "source_path": decision.source_path,
            "source_identity": dict(decision.source_identity),
            "source_snapshot_digest": decision.source_snapshot_digest,
            "source_manifest": tuple(decision.source_manifest),
            "source_manifest_digest": decision.source_manifest_digest,
            "source_directory_manifest": tuple(decision.source_directory_manifest),
            "source_directory_manifest_digest": decision.source_directory_manifest_digest,
        }

    def _consume_manual_decision(
        self, raw_title: str, expected_binding: Dict[str, Any]
    ) -> bool:
        try:
            payload = self.get_data(self.MANUAL_DECISIONS_KEY)
        except Exception:
            payload = None
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != self.MANUAL_DECISIONS_SCHEMA
            or not isinstance(payload.get("items"), dict)
        ):
            self._logger.error(
                "CourseOrganizer[event=manual_review_consume_failed] item_course_repr=%s reason=invalid_store",
                ascii(raw_title),
            )
            return False
        entry = payload["items"].get(raw_title)
        if not isinstance(entry, dict) or entry.get("action") != "confirm":
            self._logger.warning(
                "CourseOrganizer[event=manual_review_consume_skipped] item_course_repr=%s reason=decision_changed",
                ascii(raw_title),
            )
            return False
        stored_binding = {
            "source_path": entry.get("source_path"),
            "source_identity": entry.get("source_identity"),
            "source_snapshot_digest": entry.get("source_snapshot_digest"),
            "source_manifest": self._coerce_source_manifest(entry.get("source_manifest")),
            "source_manifest_digest": entry.get("source_manifest_digest"),
            "source_directory_manifest": self._coerce_source_directory_manifest(
                entry.get("source_directory_manifest")
            ),
            "source_directory_manifest_digest": entry.get(
                "source_directory_manifest_digest"
            ),
        }
        if stored_binding != expected_binding:
            self._logger.warning(
                "CourseOrganizer[event=manual_review_consume_skipped] item_course_repr=%s reason=identity_mismatch",
                ascii(raw_title),
            )
            return False
        items = dict(payload["items"])
        del items[raw_title]
        next_payload = {"schema": self.MANUAL_DECISIONS_SCHEMA, "items": items}
        for attempt in range(self.MANUAL_PERSIST_ATTEMPTS):
            try:
                self.save_data(self.MANUAL_DECISIONS_KEY, next_payload)
            except Exception as exc:
                self._logger.warning(
                    "CourseOrganizer[event=manual_review_consume_retry] item_course_repr=%s attempt=%d reason=%s",
                    ascii(raw_title),
                    attempt + 1,
                    exc.__class__.__name__,
                )
            if self._manual_decision_consumed(raw_title):
                self._logger.info(
                    "CourseOrganizer[event=manual_review_consumed] item_course_repr=%s",
                    ascii(raw_title),
                )
                return True
            if attempt + 1 < self.MANUAL_PERSIST_ATTEMPTS:
                self._logger.warning(
                    "CourseOrganizer[event=manual_review_consume_retry] item_course_repr=%s attempt=%d reason=not_verified",
                    ascii(raw_title),
                    attempt + 1,
                )
        self._logger.error(
            "CourseOrganizer[event=manual_review_consume_failed] item_course_repr=%s reason=not_verified",
            ascii(raw_title),
        )
        return False

    def _manual_decision_consumed(self, raw_title: str) -> bool:
        try:
            payload = self.get_data(self.MANUAL_DECISIONS_KEY)
        except Exception:
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("schema") == self.MANUAL_DECISIONS_SCHEMA
            and isinstance(payload.get("items"), dict)
            and raw_title not in payload["items"]
        )

    def _legacy_review_override(self, raw_title: str) -> Optional[naming.ManualOverride]:
        config = self._get_config()
        parsed = naming.parse_manual_overrides(
            config.get("naming_manual_overrides", ""),
            target_libraries=self._manual_target_libraries(),
        )
        for item in parsed.overrides:
            if item.raw_title == raw_title:
                return item
        return None

    def _manual_decision_for(
        self, raw_title: str, payload: Any = _MANUAL_DATA_UNSET
    ) -> Optional[naming.ManualOverride]:
        """Load structured review data; malformed matching entries fail closed."""
        if payload is _MANUAL_DATA_UNSET:
            try:
                payload = self.get_data(self.MANUAL_DECISIONS_KEY)
            except Exception:
                return naming.ManualOverride(raw_title, "invalid")
        if payload is None:
            return None
        if not isinstance(payload, dict) or payload.get("schema") != self.MANUAL_DECISIONS_SCHEMA:
            return naming.ManualOverride(raw_title, "invalid")
        items = payload.get("items")
        if not isinstance(items, dict):
            return naming.ManualOverride(raw_title, "invalid")
        entry = items.get(raw_title)
        if entry is None:
            return None
        if not isinstance(entry, dict):
            return naming.ManualOverride(raw_title, "invalid")
        action = entry.get("action")
        source_revision = entry.get("source_revision")
        if action not in {"confirm", "ignore", "candidate"} or not isinstance(source_revision, str) or not source_revision:
            return naming.ManualOverride(raw_title, "invalid")
        source_path = entry.get("source_path")
        source_identity = entry.get("source_identity")
        source_snapshot_digest = entry.get("source_snapshot_digest")
        source_manifest = self._coerce_source_manifest(entry.get("source_manifest"))
        source_manifest_digest = entry.get("source_manifest_digest")
        source_directory_manifest = self._coerce_source_directory_manifest(
            entry.get("source_directory_manifest")
        )
        source_directory_manifest_digest = entry.get(
            "source_directory_manifest_digest"
        )
        if (
            not isinstance(source_path, str)
            or not os.path.isabs(source_path)
            or not isinstance(source_identity, dict)
            or not isinstance(source_snapshot_digest, str)
            or not source_snapshot_digest
            or source_manifest is None
            or not isinstance(source_manifest_digest, str)
            or not source_manifest_digest
            or source_manifest_digest != self._manifest_digest(source_manifest)
            or source_directory_manifest is None
            or not isinstance(source_directory_manifest_digest, str)
            or not source_directory_manifest_digest
            or source_directory_manifest_digest
            != self._directory_manifest_digest(source_directory_manifest)
        ):
            return naming.ManualOverride(raw_title, "invalid")
        try:
            identity_values = {
                key: source_identity[key]
                for key in ("st_dev", "st_ino", "st_ctime_ns")
            }
        except (KeyError, TypeError):
            return naming.ManualOverride(raw_title, "invalid")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in identity_values.values()
        ):
            return naming.ManualOverride(raw_title, "invalid")
        normalized_identity = identity_values
        if any(value < 0 for value in normalized_identity.values()):
            return naming.ManualOverride(raw_title, "invalid")
        try:
            updated_at = int(entry.get("updated_at"))
        except (TypeError, ValueError):
            return naming.ManualOverride(raw_title, "invalid")
        if updated_at < 0:
            return naming.ManualOverride(raw_title, "invalid")
        if action == "ignore":
            if any(key in entry for key in ("final_title", "target_library")) and (
                entry.get("final_title", "") or entry.get("target_library", "")
            ):
                return naming.ManualOverride(raw_title, "invalid")
            return naming.ManualOverride(
                raw_title,
                "ignore",
                source_revision=source_revision,
                source_path=source_path,
                source_identity=tuple(sorted(normalized_identity.items())),
                source_snapshot_digest=source_snapshot_digest,
                source_manifest=source_manifest,
                source_manifest_digest=source_manifest_digest,
                source_directory_manifest=source_directory_manifest,
                source_directory_manifest_digest=source_directory_manifest_digest,
            )
        if action == "candidate":
            candidate = self._manual_candidate_for(raw_title, payload)
            target_library = entry.get("target_library", "")
            if target_library is None:
                target_library = ""
            if not isinstance(target_library, str) or (
                target_library and target_library not in self._manual_target_libraries()
            ):
                return naming.ManualOverride(raw_title, "invalid")
            candidate_key = entry.get("candidate_key")
            if candidate is None or not isinstance(candidate_key, str):
                return naming.ManualOverride(raw_title, "invalid")
            return naming.ManualOverride(
                raw_title,
                "candidate",
                candidate_key,
                target_library,
                source_revision,
                source_path=source_path,
                source_identity=tuple(sorted(normalized_identity.items())),
                source_snapshot_digest=source_snapshot_digest,
                source_manifest=source_manifest,
                source_manifest_digest=source_manifest_digest,
                source_directory_manifest=source_directory_manifest,
                source_directory_manifest_digest=source_directory_manifest_digest,
            )
        final_title = entry.get("final_title")
        target_library = entry.get("target_library")
        valid_name, _ = naming.validate_manual_name(final_title)
        if not valid_name or target_library not in self._manual_target_libraries():
            return naming.ManualOverride(raw_title, "invalid")
        return naming.ManualOverride(
            raw_title,
            "confirm",
            final_title,
            target_library,
            source_revision,
            source_path=source_path,
            source_identity=tuple(sorted(normalized_identity.items())),
            source_snapshot_digest=source_snapshot_digest,
            source_manifest=source_manifest,
            source_manifest_digest=source_manifest_digest,
            source_directory_manifest=source_directory_manifest,
            source_directory_manifest_digest=source_directory_manifest_digest,
        )

    def _manual_candidate_for(
        self,
        raw_title: str,
        payload: Any = _MANUAL_DATA_UNSET,
    ) -> Optional[naming.MetadataCandidate]:
        if payload is _MANUAL_DATA_UNSET:
            try:
                payload = self.get_data(self.MANUAL_DECISIONS_KEY)
            except Exception:
                return None
        if not isinstance(payload, dict) or payload.get("schema") != self.MANUAL_DECISIONS_SCHEMA:
            return None
        items = payload.get("items")
        entry = items.get(raw_title) if isinstance(items, dict) else None
        if not isinstance(entry, dict) or entry.get("action") not in {"candidate", "confirm"}:
            return None
        candidate_payload = entry.get("candidate")
        candidate_key = entry.get("candidate_key")
        if not isinstance(candidate_payload, dict) or not isinstance(candidate_key, str):
            return None
        try:
            candidate = naming.MetadataCandidate.from_dict(candidate_payload)
        except Exception:
            return None
        if (
            candidate.key != candidate_key
            or candidate.source != "themoviedb"
            or not candidate.key.startswith("themoviedb:")
            or not candidate.media_id
            or not candidate.title
            or candidate.media_type not in {"tv", "movie", "unknown"}
            or candidate.key != f"themoviedb:{candidate.media_id}:{candidate.media_type}"
        ):
            return None
        return candidate

    def _review_rows(
        self,
        *,
        include_internal: bool = False,
        raw_title: Optional[str] = None,
        directory_context: Optional[Dict[str, Any]] = None,
        hide_missing_source: bool = False,
    ) -> List[Dict[str, Any]]:
        directory_context = directory_context or self._moviepilot_directory_context()
        config = self._review_path_config(directory_context)
        rows = self._get_resolver().preview_rows()
        selected = directory_context.get("selected", {})
        labels = {
            str(key): str(rule.get("title") or rule.get("name") or key)
            for key, rule in selected.items()
            if isinstance(rule, dict)
        }
        roots = {
            str(key): str(rule.get("path", "") or "")
            for key, rule in selected.items()
            if isinstance(rule, dict)
        }
        requested_raw_title = raw_title
        try:
            manual_payload = self.get_data(self.MANUAL_DECISIONS_KEY)
        except Exception:
            manual_payload = {"_load_error": True}
        output: List[Dict[str, Any]] = []
        for source in rows:
            if not isinstance(source, dict):
                continue
            raw_value = source.get("raw_title", "")
            if self._is_ignored_scan_entry(raw_value):
                continue
            if requested_raw_title is not None and raw_value != requested_raw_title:
                continue
            if source.get("completed_at") is not None:
                continue
            raw_title_valid, _ = naming.validate_manual_raw_title(raw_value)
            if not raw_title_valid:
                self._logger.warning(
                    "CourseOrganizer[event=review_row_rejected] item_course_repr=%s",
                    ascii(str(raw_value)),
                )
                continue
            raw_title = raw_value
            item = {
                "raw_title": raw_title,
                "final_title": str(source.get("final_title") or source.get("local_title") or raw_title),
                "target_library": str(source.get("target_library", "")).lower(),
                "target_output_root": str(source.get("target_output_root") or ""),
                "status": str(source.get("status", "")),
                "reason_codes": list(source.get("reason_codes", ())),
                "source": str(source.get("source", "")).lower(),
                "media_id": str(source.get("media_id", "") or ""),
                "media_type": str(source.get("media_type", "unknown")).lower(),
                "timestamp": source.get("timestamp"),
            }
            source_binding = self._current_source_binding(raw_title)
            if not source_binding:
                directory_present = self._review_source_directory_ok(raw_title)
                if not directory_present and hide_missing_source:
                    self._logger.debug(
                        "CourseOrganizer[event=review_row_filtered] item_course_repr=%s reason=source_missing",
                        ascii(raw_title),
                    )
                    continue
                item["source_pending"] = True
                self._logger.info(
                    "CourseOrganizer[event=review_row_pending] item_course_repr=%s reason=source_binding_unavailable",
                    ascii(raw_title),
                )
            else:
                item.update(source_binding or {})
            if source_binding and source_binding.get("source_manifest"):
                media_by_season, _, _ = self._collect_course_files(
                    source_binding["source_path"]
                )
                if not media_by_season:
                    self._logger.debug(
                        "CourseOrganizer[event=review_row_filtered] item_course_repr=%s reason=no_media",
                        ascii(raw_title),
                    )
                    continue
            source_revision = self._review_revision(item)
            structured = self._manual_decision_for(raw_title, manual_payload)
            if (
                source_binding is not None
                and structured is not None
                and structured.action in {"confirm", "ignore", "candidate"}
            ):
                expected_binding = self._manual_binding(structured)
                if not self._source_bindings_equal(source_binding, expected_binding):
                    structured = naming.ManualOverride(raw_title, "invalid")
            override = structured if structured is not None else self._legacy_review_override(raw_title)
            selected_candidate: Optional[naming.MetadataCandidate] = None
            if override is not None and override.action == "invalid":
                item["status"] = "invalid_manual_decision"
                item["target_library"] = ""
                item["target_output_root"] = ""
                item["reason_codes"] = ["invalid_manual_decision"]
            elif override is not None and override.action == "ignore":
                item["status"] = "ignore"
                item["blocked_reason"] = "manual_ignore"
                item["target_library"] = ""
                item["target_output_root"] = ""
            elif override is not None and override.action == "confirm":
                item["status"] = "local_fallback"
                item["final_title"] = override.value
                item["target_library"] = override.target_library
                selected_candidate = self._manual_candidate_for(raw_title, manual_payload)
                if selected_candidate is not None:
                    item["source"] = selected_candidate.source
                    item["media_id"] = selected_candidate.media_id
                    item["media_type"] = selected_candidate.media_type
                elif isinstance(manual_payload, dict):
                    entry = manual_payload.get("items", {}).get(raw_title, {})
                    if isinstance(entry, dict):
                        item["source"] = str(entry.get("media_source", item["source"]))
                        item["media_id"] = str(entry.get("media_id", item["media_id"]))
                        item["media_type"] = str(
                            entry.get("media_type", item["media_type"])
                        )
                item["target_output_root"] = os.path.join(
                    str(roots[override.target_library]), self._safe_name(override.value)
                )
                item["reason_codes"] = list(item.get("reason_codes", ())) + [
                    "manual_confirm"
                ]
            elif override is not None and override.action == "candidate":
                selected_candidate = self._manual_candidate_for(raw_title, manual_payload)
                if selected_candidate is None:
                    item["status"] = "invalid_manual_decision"
                    item["target_library"] = ""
                    item["target_output_root"] = ""
                    item["reason_codes"] = ["invalid_manual_decision"]
                else:
                    item["source"] = selected_candidate.source
                    item["media_id"] = selected_candidate.media_id
                    item["media_type"] = selected_candidate.media_type
                    entry = (
                        manual_payload.get("items", {}).get(raw_title, {})
                        if isinstance(manual_payload, dict)
                        else {}
                    )
                    selected_title = entry.get("final_title") if isinstance(entry, dict) else None
                    valid_selected_title, _ = naming.validate_manual_name(selected_title)
                    if not valid_selected_title:
                        item["status"] = "invalid_manual_decision"
                        item["target_library"] = ""
                        item["reason_codes"] = ["invalid_manual_decision"]
                    else:
                        item["final_title"] = selected_title
                    item["target_output_root"] = ""
                    item["reason_codes"] = list(item.get("reason_codes", ())) + [
                        "manual_candidate"
                    ]

            target_library = str(item.get("target_library", "")).lower()
            if target_library not in labels:
                target_library = ""
            final_title = str(
                item.get("final_title") or item.get("local_title") or raw_title
            )
            target_root = str(item.get("target_output_root") or "")
            if target_library and not target_root:
                target_root = os.path.join(str(roots[target_library]), self._safe_name(final_title))
            item.update(
                {
                    "raw_title": raw_title,
                    "final_title": final_title,
                    "target_library": target_library,
                    "target_label": labels.get(target_library, "待确认"),
                    "target_library_label": labels.get(target_library, "待确认"),
                    "target_output_root": target_root,
                    "target_position": target_root or "待确认",
                }
            )
            if item.get("source_pending"):
                item["status_label"] = "源目录待稳定"
            else:
                item["status_label"] = self._review_status_label(
                    str(item.get("status", "")), target_library
                )
            media_source = str(item.get("source", "")).strip().lower()
            media_id = str(item.get("media_id", "") or "").strip()
            association_required = media_source not in {"themoviedb", "douban"} or not media_id
            revision = self._review_revision(item)
            result = {
                    "raw_title": raw_title,
                    "revision": revision,
                    "source_revision": source_revision,
                    "final_title": final_title,
                    "target_library": target_library,
                    "target_label": labels.get(target_library, "待确认"),
                    "target_library_label": labels.get(target_library, "待确认"),
                    "target_output_root": target_root,
                    "target_path": target_root,
                    "target_position": target_root or "待确认",
                    "status": str(item.get("status", "")),
                    "status_label": item["status_label"],
                    "association_required": association_required,
                    "source_pending": bool(item.get("source_pending", False)),
                    "recognition_source_label": self._recognition_source_label(
                        item.get("source", ""),
                        item.get("reason_codes", ()),
                        override.action if override is not None else "",
                    ),
                    "selected_candidate_key": (
                        selected_candidate.key if selected_candidate is not None else ""
                    ),
                    "selected_candidate": (
                        self._tmdb_candidate_response(selected_candidate)
                        if selected_candidate is not None
                        else None
                    ),
                }
            if include_internal:
                result["_source_binding"] = source_binding
                result["_media_source"] = media_source
                result["_media_id"] = media_id
                result["_media_type"] = str(item.get("media_type", "unknown"))
            output.append(result)
        return output

    def get_review(self) -> Any:
        directory_context = self._moviepilot_directory_context()
        return self._review_response(
            True,
            {
                "items": self._review_rows(
                    directory_context=directory_context,
                    hide_missing_source=True,
                ),
                "libraries": list(directory_context.get("libraries", []) or []),
                "directory_rules": list(directory_context.get("rules", []) or []),
                "download_directories": list(
                    directory_context.get("download_directories", []) or []
                ),
                "archive_directories": list(
                    directory_context.get("archive_directories", []) or []
                ),
                "rules_ready": bool(directory_context.get("ready")),
                "rules_message": str(directory_context.get("message", "") or ""),
                "monitoring_enabled": False,
                "monitoring_rules": [],
                "incoming_path": str(directory_context.get("incoming", "") or ""),
                "settings_url": "",
            },
        )

    def refresh_review(self) -> Any:
        """Rescan preview data without allowing a refresh to move media."""
        with self._thread_lock:
            original_config = getattr(self._run_config_local, "config", _MANUAL_DATA_UNSET)
            refresh_config = dict(self._get_config())
            refresh_config["naming_mode"] = "preview"
            self._run_config_local.config = refresh_config
            self._resolver = None
            self._resolver_signature = None
            try:
                self._run(force=True)
            finally:
                if original_config is _MANUAL_DATA_UNSET:
                    try:
                        del self._run_config_local.config
                    except AttributeError:
                        pass
                else:
                    self._run_config_local.config = original_config
            return self.get_review()

    def _save_manual_decision(
        self,
        raw_title: str,
        action: str,
        final_title: str,
        target_library: str,
        source_revision: str,
        source_binding: Dict[str, Any],
        candidate: Optional[naming.MetadataCandidate] = None,
        media_source: str = "",
        media_id: str = "",
        media_type: str = "unknown",
    ) -> bool:
        with self._review_data_lock:
            if not self._source_binding_matches(raw_title, source_binding):
                return False
            try:
                existing = self.get_data(self.MANUAL_DECISIONS_KEY)
            except Exception:
                return False
            if existing is None:
                payload: Dict[str, Any] = {
                    "schema": self.MANUAL_DECISIONS_SCHEMA,
                    "items": {},
                }
            elif (
                isinstance(existing, dict)
                and existing.get("schema") == self.MANUAL_DECISIONS_SCHEMA
                and isinstance(existing.get("items"), dict)
            ):
                payload = {"schema": self.MANUAL_DECISIONS_SCHEMA, "items": dict(existing["items"])}
            else:
                return False
            items = payload["items"]
            if raw_title not in items and len(items) >= self.MANUAL_DECISIONS_MAX:
                return False
            try:
                updated_at = int(self._clock())
            except (TypeError, ValueError, OverflowError):
                return False
            items[raw_title] = {
                "action": action,
                "final_title": final_title,
                "target_library": target_library,
                "updated_at": updated_at,
                "source_revision": source_revision,
                "source_path": source_binding["source_path"],
                "source_identity": dict(source_binding["source_identity"]),
                "source_snapshot_digest": source_binding["source_snapshot_digest"],
                "source_manifest": [
                    {
                        "relative_path": item[0],
                        "st_dev": item[1],
                        "st_ino": item[2],
                        "st_ctime_ns": item[3],
                        "st_size": item[4],
                        "st_mtime_ns": item[5],
                    }
                    for item in source_binding["source_manifest"]
                ],
                "source_manifest_digest": source_binding["source_manifest_digest"],
                "source_directory_manifest": [
                    {
                        "relative_path": item[0],
                        "st_dev": item[1],
                        "st_ino": item[2],
                    }
                    for item in source_binding["source_directory_manifest"]
                ],
                "source_directory_manifest_digest": source_binding[
                    "source_directory_manifest_digest"
                ],
            }
            if action == "candidate" and candidate is None:
                return False
            if action in {"candidate", "confirm"} and candidate is not None:
                if candidate.source != "themoviedb":
                    return False
                items[raw_title]["candidate_key"] = candidate.key
                items[raw_title]["candidate"] = candidate.to_dict()
            if action == "confirm":
                media_source = str(media_source or "").strip().lower()
                media_id = str(media_id or "").strip()
                media_type = str(media_type or "unknown").strip().lower()
                if media_source or media_id:
                    if (
                        media_source not in {"themoviedb", "douban"}
                        or not media_id
                        or media_type not in {"tv", "movie", "unknown"}
                    ):
                        return False
                    items[raw_title]["media_source"] = media_source
                    items[raw_title]["media_id"] = media_id
                    items[raw_title]["media_type"] = media_type
            try:
                result = self.save_data(self.MANUAL_DECISIONS_KEY, payload)
            except Exception:
                self._logger.error(
                    "CourseOrganizer[event=manual_review_persist_failed] item_course_repr=%s reason=exception",
                    ascii(raw_title),
                )
                return False
            if result is False:
                self._logger.error(
                    "CourseOrganizer[event=manual_review_persist_failed] item_course_repr=%s reason=save_data_false",
                    ascii(raw_title),
                )
                return False
            if not self._source_binding_matches(raw_title, source_binding):
                try:
                    self.save_data(self.MANUAL_DECISIONS_KEY, existing)
                except Exception:
                    self._logger.error(
                        "CourseOrganizer[event=manual_review_persist_failed] item_course_repr=%s reason=rollback_exception",
                        ascii(raw_title),
                    )
                return False
            return True

    def _restore_ignored_decision(
        self, raw_title: str, expected_binding: Dict[str, Any]
    ) -> bool:
        """Remove only a matching ignore decision; never apply or move media."""
        with self._review_data_lock:
            try:
                existing = self.get_data(self.MANUAL_DECISIONS_KEY)
            except Exception:
                return False
            decision = self._manual_decision_for(raw_title, existing)
            if (
                decision is None
                or decision.action != "ignore"
                or self._manual_binding(decision) != expected_binding
                or not isinstance(existing, dict)
                or not isinstance(existing.get("items"), dict)
            ):
                return False
            items = dict(existing["items"])
            items.pop(raw_title, None)
            try:
                result = self.save_data(
                    self.MANUAL_DECISIONS_KEY,
                    {"schema": self.MANUAL_DECISIONS_SCHEMA, "items": items},
                )
            except Exception:
                return False
            return result is not False and self._manual_decision_consumed(raw_title)

    def save_review(self, payload: Optional[Dict[str, Any]] = Body(default=None)) -> Any:
        if not isinstance(payload, dict):
            return self._review_response(False, message="请求参数无效")
        raw_title = payload.get("raw_title")
        raw_title_valid, _ = naming.validate_manual_raw_title(raw_title)
        if not raw_title_valid:
            return self._review_response(False, message="课程名称无效")
        revision = payload.get("revision")
        if not isinstance(revision, str) or not revision:
            return self._review_response(False, message="缺少预览版本")
        action = str(payload.get("action", "")).strip().lower()
        if action not in {"confirm", "ignore", "restore"}:
            return self._review_response(False, message="操作无效")

        with self._thread_lock:
            rows = self._review_rows(include_internal=True, raw_title=raw_title)
            current = next((item for item in rows if item.get("raw_title") == raw_title), None)
            if current is None:
                return self._review_response(False, message="预览记录不存在或已失效")
            if revision != current.get("revision"):
                return self._review_response(False, message="预览已更新，请刷新后再确认")
            expected_binding = current.get("_source_binding")
            if not isinstance(expected_binding, dict):
                return self._review_response(False, message="源目录已不存在或已变化，请刷新预览")

            if action == "restore":
                if current.get("status") != "ignore" or not self._restore_ignored_decision(
                    raw_title, expected_binding
                ):
                    return self._review_response(False, message="恢复待处理状态失败，请刷新后重试")
                self._resolver = None
                self._resolver_signature = ()
                latest = next(
                    (
                        item
                        for item in self._review_rows(raw_title=raw_title)
                        if item.get("raw_title") == raw_title
                    ),
                    None,
                )
                return self._review_response(True, latest or {}, "已恢复为待处理")

            final_title = payload.get("final_title", "")
            target_library = str(payload.get("target_library", "")).strip().lower()
            linked_candidate: Optional[naming.MetadataCandidate] = None
            media_source = ""
            media_id = ""
            media_type = "unknown"
            if action == "confirm":
                valid_name, _ = naming.validate_manual_name(final_title)
                if not valid_name:
                    return self._review_response(False, message="建议名称无效")
                if target_library not in self._manual_target_libraries():
                    return self._review_response(False, message="目标媒体库无效")
                directory_context = self._moviepilot_directory_context()
                selected_rule = directory_context.get("selected", {}).get(target_library)
                if not isinstance(selected_rule, dict):
                    return self._review_response(
                        False,
                        message="MoviePilot 目标目录规则缺失或不唯一，请到设置 → 存储 & 目录修正",
                    )
                if not selected_rule.get("renaming"):
                    return self._review_response(
                        False,
                        message="请先在 MoviePilot 设置 → 存储 & 目录为该规则开启智能重命名",
                    )
                linked_candidate = self._manual_candidate_for(raw_title)
                if linked_candidate is not None:
                    media_source = linked_candidate.source
                    media_id = linked_candidate.media_id
                    media_type = linked_candidate.media_type
                else:
                    media_source = str(current.get("_media_source", "")).strip().lower()
                    media_id = str(current.get("_media_id", "")).strip()
                    media_type = str(current.get("_media_type", "unknown")).strip().lower()
                # 允许"未关联可靠媒体 ID 也手动整理"：有 ID 用之，无 ID 时由
                # _apply_manual_decision_locked 走 MoviePilot 文件识别/按标题整理路径。
                # 这是用户明确要求的"无论搜索结果如何都能保存并整理"。
            else:
                final_title = ""
                target_library = ""

            if not self._save_manual_decision(
                raw_title,
                action,
                final_title,
                target_library,
                str(current.get("source_revision", "")),
                expected_binding,
                candidate=linked_candidate,
                media_source=media_source,
                media_id=media_id,
                media_type=media_type,
            ):
                return self._review_response(False, message="保存人工决定失败")
            self._logger.info(
                "CourseOrganizer[event=manual_review_saved] item_course_repr=%s item_action=%s item_library=%s",
                ascii(raw_title),
                action,
                target_library,
            )
            if action == "confirm":
                apply_status = self._apply_manual_decision_locked(
                    raw_title,
                    expected_binding["source_path"],
                    expected_binding,
                )
                if apply_status == "no_media":
                    self._resolver = None
                    self._resolver_signature = ()
                    return self._review_response(
                        False,
                        message="源目录中没有可整理的视频文件，可能已经整理过，请刷新列表",
                    )
                if apply_status == "failed":
                    self._resolver = None
                    self._resolver_signature = ()
                    return self._review_response(
                        False,
                        message="人工决定已保存，但单条整理失败，请检查源目录和目标媒体库后重试",
                    )
                if apply_status == "partial":
                    self._resolver = None
                    self._resolver_signature = ()
                    return self._review_response(
                        False,
                        {
                            "moved": True,
                            "record_incomplete": True,
                        },
                        "文件已移动，但人工复核记录未完整保存，请勿重复确认；请检查记录后处理",
                    )
                self._logger.info(
                    "CourseOrganizer[event=manual_review_applied] item_course_repr=%s item_library=%s",
                    ascii(raw_title),
                    target_library,
                )
            self._resolver = None
            self._resolver_signature = ()
            latest = next(
                (
                    item
                    for item in self._review_rows(raw_title=raw_title)
                    if item.get("raw_title") == raw_title
                ),
                None,
            )
            return self._review_response(
                True,
                latest or {},
                "已确认并整理" if action == "confirm" else "已保存",
            )

    def _legacy_apply_manual_decision_locked(
        self,
        course_name: str,
        course_path: str,
        expected_binding: Dict[str, Any],
    ) -> str:
        """Apply one saved confirmation through the existing locked move chain."""
        if not isinstance(course_path, str) or not os.path.isabs(course_path):
            return "failed"
        current_binding = self._current_source_binding(course_name)
        if not self._source_bindings_equal(current_binding, expected_binding):
            self._logger.warning(
                "CourseOrganizer[event=manual_review_apply_rejected] item_course_repr=%s reason=source_changed",
                ascii(course_name),
            )
            return "failed"

        signature = self._coerce_signature(self._snapshot_signature(course_path))
        if not signature:
            self._logger.warning(
                "CourseOrganizer[event=manual_review_apply_rejected] item_course_repr=%s reason=empty_snapshot",
                ascii(course_name),
            )
            return "failed"
        state_key = self._state_key(course_name)
        state = self._load_plugin_data(state_key, {})
        persisted_signature = (
            self._coerce_signature(state.get("signature"))
            if isinstance(state, dict)
            else ()
        )
        try:
            stable_count = int(state.get("stable_count", 0)) if isinstance(state, dict) else 0
        except (TypeError, ValueError, OverflowError):
            stable_count = 0
        if persisted_signature != signature or stable_count < 1:
            if self.save_data(state_key, {"signature": signature, "stable_count": 1}) is False:
                self._logger.error(
                    "CourseOrganizer[event=manual_review_apply_rejected] item_course_repr=%s reason=state_persist_failed",
                    ascii(course_name),
                )
                return "failed"

        original_config = getattr(self._run_config_local, "config", _MANUAL_DATA_UNSET)
        apply_config = dict(self._get_config())
        apply_config["naming_mode"] = "apply"
        apply_result: Dict[str, Any] = {
            "moved": False,
            "decision_consumed": False,
        }
        self._run_config_local.config = apply_config
        try:
            try:
                moved = self._process_course_locked(
                    course_name,
                    course_path,
                    source_root=apply_config.get("incoming"),
                    apply_result=apply_result,
                )
            except Exception as exc:
                self._logger.error(
                    "CourseOrganizer[event=manual_review_apply_failed] item_course_repr=%s reason=%s",
                    ascii(course_name),
                    exc.__class__.__name__,
                )
                moved = False
        finally:
            if original_config is _MANUAL_DATA_UNSET:
                try:
                    del self._run_config_local.config
                except AttributeError:
                    pass
            else:
                self._run_config_local.config = original_config
        if not moved or not apply_result.get("moved"):
            return "failed"
        if not apply_result.get("decision_consumed"):
            self._logger.error(
                "CourseOrganizer[event=moved_but_record_incomplete] item_course_repr=%s phase=manual_decision",
                ascii(course_name),
            )
            return "partial"
        resolver = self._get_resolver()
        try:
            completed = resolver.mark_completed(course_name)
        except Exception:
            completed = False
        if not completed:
            self._logger.error(
                "CourseOrganizer[event=moved_but_record_incomplete] item_course_repr=%s phase=completed_at",
                ascii(course_name),
            )
            return "partial"
        return "success"

    def _confirmed_media_identity(
        self, course_name: str
    ) -> Optional[Tuple[str, str, str]]:
        try:
            payload = self.get_data(self.MANUAL_DECISIONS_KEY)
        except Exception:
            return None
        candidate = self._manual_candidate_for(course_name, payload)
        if candidate is not None:
            return candidate.source, candidate.media_id, candidate.media_type
        items = payload.get("items") if isinstance(payload, dict) else None
        entry = items.get(course_name) if isinstance(items, dict) else None
        if not isinstance(entry, dict) or entry.get("action") != "confirm":
            return None
        media_source = str(entry.get("media_source", "")).strip().lower()
        media_id = str(entry.get("media_id", "")).strip()
        media_type = str(entry.get("media_type", "unknown")).strip().lower()
        if (
            media_source not in {"themoviedb", "douban"}
            or not media_id
            or media_type not in {"tv", "movie", "unknown"}
        ):
            return None
        return media_source, media_id, media_type

    def _apply_manual_decision_locked(
        self,
        course_name: str,
        course_path: str,
        expected_binding: Dict[str, Any],
    ) -> str:
        """Apply one confirmed item through MoviePilot's native manual transfer."""
        if not isinstance(course_path, str) or not os.path.isabs(course_path):
            return "failed"
        current_binding = self._current_source_binding(course_name)
        if not self._source_bindings_equal(current_binding, expected_binding):
            self._logger.warning(
                "CourseOrganizer[event=native_transfer_rejected] item_course_repr=%s reason=source_changed",
                ascii(course_name),
            )
            return "failed"

        decision = self._manual_decision_for(course_name)
        if decision is None or decision.action != "confirm":
            return "failed"
        if self._manual_binding(decision) != expected_binding:
            return "failed"
        identity = self._confirmed_media_identity(course_name)
        if identity is not None:
            media_source, media_id, recognized_media_type = identity
        else:
            media_source, media_id, recognized_media_type = "", "", "unknown"
        # 原生"识别+整理"只对可靠的 TMDB/豆瓣 身份有效；课程等本地/空身份走直接搬移。
        native_valid = media_source in {"themoviedb", "douban"} and bool(media_id)

        directory_context = self._moviepilot_directory_context()
        rule = directory_context.get("selected", {}).get(decision.target_library)
        if not isinstance(rule, dict):
            self._logger.warning(
                "CourseOrganizer[event=native_transfer_rejected] item_course_repr=%s reason=directory_rule_missing",
                ascii(course_name),
            )
            return "failed"
        rule = dict(rule)
        source_root = self._download_root_for_path(course_path)
        if not source_root:
            self._logger.warning(
                "CourseOrganizer[event=native_transfer_rejected] item_course_repr=%s reason=download_root_missing",
                ascii(course_name),
            )
            return "failed"
        rule["download_path"] = source_root
        if not rule.get("renaming"):
            self._logger.warning(
                "CourseOrganizer[event=native_transfer_rejected] item_course_repr=%s reason=renaming_disabled",
                ascii(course_name),
            )
            return "failed"

        # 无可靠媒体 ID（课程等不在 TMDB 上的条目）：绕过 MoviePilot 的媒体识别，
        # 直接按标题把源目录搬到"用户选择的目标媒体库"。
        if not native_valid:
            self._logger.info(
                "CourseOrganizer[event=direct_transfer_started] item_course_repr=%s target_library=%s",
                ascii(course_name),
                decision.target_library,
            )
            return self._apply_direct_transfer(
                course_name, course_path, expected_binding, decision, rule
            )

        adapter = self._get_native_adapter()
        if adapter is None:
            self._logger.error(
                "CourseOrganizer[event=native_transfer_failed] item_course_repr=%s reason=adapter_unavailable",
                ascii(course_name),
            )
            return "failed"
        try:
            fileitem = adapter.get_file_item(
                course_path,
                source_storage=str(rule.get("storage") or "local"),
            )
        except Exception as exc:
            self._logger.error(
                "CourseOrganizer[event=native_transfer_failed] item_course_repr=%s phase=file_item reason=%s",
                ascii(course_name),
                exc.__class__.__name__,
            )
            return "failed"
        if fileitem is None:
            return "failed"

        if media_source == "themoviedb":
            if not media_id.isdigit() or int(media_id) <= 0:
                return "failed"
        media_type = (
            recognized_media_type
            if recognized_media_type in {"movie", "tv"}
            else ("movie" if decision.target_library == "movie" else "tv")
        )
        try:
            with adapter.rename_context(course_path, decision.value):
                result = adapter.manual_transfer(
                    fileitem=fileitem,
                    target_storage=str(rule.get("library_storage") or "local"),
                    target_path=Path(str(rule["path"])),
                    media_source=media_source,
                    media_id=media_id,
                    mtype=media_type,
                    transfer_type=str(rule.get("transfer_type") or "") or None,
                    scrape=bool(rule.get("scraping")),
                    library_type_folder=bool(rule.get("library_type_folder")),
                    library_category_folder=bool(
                        rule.get("library_category_folder")
                    ),
                    force=False,
                    background=False,
                    preview=False,
                    sync_extra_files=True,
                )
        except Exception as exc:
            self._logger.error(
                "CourseOrganizer[event=native_transfer_failed] item_course_repr=%s phase=transfer reason=%s",
                ascii(course_name),
                exc.__class__.__name__,
            )
            return "failed"
        if not isinstance(result, tuple) or len(result) != 2:
            self._logger.warning(
                "CourseOrganizer[event=native_transfer_failed] item_course_repr=%s phase=result",
                ascii(course_name),
            )
            return "failed"
        if result[0] is not True:
            if result[0] is False and isinstance(result[1], str) and "没有找到可整理的媒体文件" in result[1]:
                self._logger.warning(
                    "CourseOrganizer[event=native_transfer_failed] item_course_repr=%s phase=result reason=no_media",
                    ascii(course_name),
                )
                return "no_media"
            self._logger.warning(
                "CourseOrganizer[event=native_transfer_failed] item_course_repr=%s phase=result reason=transfer_failed",
                ascii(course_name),
            )
            return "failed"

        if not self._consume_manual_decision(course_name, expected_binding):
            self._logger.error(
                "CourseOrganizer[event=moved_but_record_incomplete] item_course_repr=%s phase=manual_decision",
                ascii(course_name),
            )
            return "partial"
        try:
            completed = self._get_resolver().mark_completed(course_name)
        except Exception:
            completed = False
        if not completed:
            self._logger.error(
                "CourseOrganizer[event=moved_but_record_incomplete] item_course_repr=%s phase=completed_at",
                ascii(course_name),
            )
            return "partial"
        return "success"

    @staticmethod
    def _direct_safe_name(final_title: str) -> Optional[str]:
        """把用户最终名称转成安全的目录名：去路径分隔符/控制符/前导点，长度受限。"""
        if not isinstance(final_title, str):
            return None
        name = final_title.strip()
        for ch in ("/", "\\", "\x00"):
            name = name.replace(ch, "")
        name = name.lstrip(".").strip()
        name = re.sub(r"[\u0001-\u001f\u007f]", "", name)
        name = name.strip()
        if not name or name in {".", ".."}:
            return None
        name = name[:120]
        return name

    def _apply_direct_transfer(
        self,
        course_name: str,
        course_path: str,
        expected_binding: Dict[str, Any],
        decision: naming.ManualOverride,
        rule: Dict[str, Any],
    ) -> str:
        """无媒体 ID 时，按标题直接把源目录搬到目标媒体库（绕过 MoviePilot 媒体识别）。

        配合目录规则的搬运方式（move/copy/hardlink 等）。失败时不消费决定，保留记录可重试。
        """
        raw_source = os.path.abspath(str(course_path if isinstance(course_path, str) else ""))
        if os.path.islink(raw_source):
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=source_symlink",
                ascii(course_name),
            )
            return "failed"
        source = os.path.realpath(raw_source)
        if not source or not os.path.isdir(source):
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=source_missing",
                ascii(course_name),
            )
            return "no_media"
        try:
            _assert_no_symlink_entries(source)
        except (OSError, ValueError):
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=source_tree_symlink",
                ascii(course_name),
            )
            return "failed"
        incoming = str(rule.get("download_path") or "")
        if incoming and not self._is_within_realpath(incoming, source):
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=source_outside_incoming",
                ascii(course_name),
            )
            return "failed"
        final_name = self._direct_safe_name(str(getattr(decision, "value", "") or course_name))
        if not final_name:
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=invalid_final_name",
                ascii(course_name),
            )
            return "failed"
        target_root = os.path.realpath(os.path.abspath(str(rule.get("path") or "")))
        if not target_root or not os.path.isdir(target_root) or not os.access(target_root, os.W_OK):
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=target_root_missing",
                ascii(course_name),
            )
            return "failed"
        sub = ""
        if rule.get("library_category_folder") and decision.target_library == "children":
            sub = os.path.join(sub, "儿童课程")
        elif rule.get("library_type_folder"):
            sub = os.path.join(sub, "电视剧" if decision.target_library != "movie" else "电影")
        dest_dir = os.path.realpath(os.path.join(target_root, sub, final_name))
        if not self._is_within_realpath(os.path.join(target_root, sub), dest_dir):
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=target_escape",
                ascii(course_name),
            )
            return "failed"
        if os.path.exists(dest_dir):
            self._logger.warning(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s reason=target_exists",
                ascii(course_name),
            )
            return "failed"

        transfer_type = str(rule.get("transfer_type") or "").strip().lower()
        try:
            if transfer_type in {"", "move"} or transfer_type.startswith("rclone_move"):
                try:
                    shutil.move(source, dest_dir)
                except shutil.Error:
                    shutil.copytree(source, dest_dir)
                    self._safe_remove_tree(source)
                except OSError:
                    shutil.copytree(source, dest_dir)
                    self._safe_remove_tree(source)
            elif transfer_type in {"copy", "rclone_copy"} or transfer_type.startswith("copy"):
                shutil.copytree(source, dest_dir)
            elif "hardlink" in transfer_type or transfer_type in {"softlink", "soft_link"}:
                try:
                    _link_files_recursive(source, dest_dir)
                except Exception:
                    self._logger.warning(
                        "CourseOrganizer[event=direct_transfer_fallback] item_course_repr=%s",
                        ascii(course_name),
                    )
                    shutil.copytree(source, dest_dir)
            else:
                # 未知搬运方式回退到移动
                shutil.move(source, dest_dir)
        except Exception as exc:
            if os.path.exists(dest_dir) and not transfer_type.startswith("move"):
                self._safe_remove_tree(dest_dir)
            self._logger.error(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s phase=transfer reason=%s",
                ascii(course_name),
                exc.__class__.__name__,
            )
            return "failed"

        if not os.path.exists(dest_dir):
            self._logger.error(
                "CourseOrganizer[event=direct_transfer_failed] item_course_repr=%s phase=verify",
                ascii(course_name),
            )
            return "failed"
        self._logger.info(
            "CourseOrganizer[event=direct_transfer_ok] item_course_repr=%s path=%s",
            ascii(course_name),
            dest_dir,
        )
        # 搬移后把媒体文件重组为 MoviePilot 配置的重命名格式（按目标媒体库电视剧/电影选模板）；
        # 无配置时回退为 Season N/S01E01 标准结构。
        try:
            naming_template = ""
            if isinstance(rule, dict):
                media_is_movie = str(decision.target_library) == "movie"
                naming_template = str(
                    rule.get("movie_naming_format") if media_is_movie else rule.get("naming_format")
                    or ""
                ).strip()
            self._normalize_episode_tree(
                dest_dir,
                naming_template=naming_template,
                final_title=str(getattr(decision, "value", "") or course_name),
            )
        except Exception as exc:
            self._logger.error(
                "CourseOrganizer[event=direct_transfer_reorg_failed] item_course_repr=%s reason=%s",
                ascii(course_name),
                exc.__class__.__name__,
            )
        if not self._consume_manual_decision(course_name, expected_binding):
            self._logger.error(
                "CourseOrganizer[event=moved_but_record_incomplete] item_course_repr=%s phase=direct_manual_decision",
                ascii(course_name),
            )
            return "partial"
        try:
            completed = self._get_resolver().mark_completed(course_name)
        except Exception:
            completed = False
        if not completed:
            self._logger.error(
                "CourseOrganizer[event=moved_but_record_incomplete] item_course_repr=%s phase=direct_completed_at",
                ascii(course_name),
            )
            return "partial"
        return "success"

    @staticmethod
    def _safe_remove_tree(path: str) -> None:
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    @staticmethod
    def _parse_season_episode(name: str) -> Optional[Tuple[int, int, Optional[int]]]:
        """从文件名解析 (季, 起始集, 结束集)。结束集可为 None。"""
        s = str(name)
        # S01E01 或 S01E01-02 / S01E01-E002（英文）
        m = re.search(r"(?i)\bs(\d{1,2})\s*e(\d{1,3})(?:[\s\-_.]*e?(\d{1,3}))?\b", s)
        if m:
            season = int(m.group(1))
            start = int(m.group(2))
            end = int(m.group(3)) if m.group(3) is not None else None
            if end is not None and end <= start:
                end = None
            return season, start, end
        # 第1季第1集 / 第一季 第一集（中文）
        cn = re.search(r"第\s*([0-9零一二三四五六七八九十百]+)\s*季.*?第\s*([0-9零一二三四五六七八九十百]+)\s*集", s)
        if cn:
            season = _cn_num(cn.group(1))
            start = _cn_num(cn.group(2))
            return season, start, None
        return None

    @staticmethod
    def _parse_bare_episode(name: str) -> Optional[int]:
        """从文件名开头的序号解析集号，如 '10.标题'、'01-标题'、'10 标题'、或纯 '10'。"""
        s = str(name).strip()
        m = re.match(r"^\s*(\d{1,3})(?:[.\s_\-]+|$)", s)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999:
                return n
        return None

    @classmethod
    def _folder_season(cls, path: str) -> Optional[int]:
        """从父目录名判断季（Season 1 / 第1季）。"""
        base = os.path.basename(os.path.normpath(path))
        m = re.search(r"(?i)season\s*(\d{1,2})\b", base)
        if m:
            return int(m.group(1))
        cn = re.search(r"第\s*([0-9零一二三四五六七八九十百]+)\s*季", base)
        if cn:
            return _cn_num(cn.group(1))
        return None

    @staticmethod
    def _subst_naming_template(template: str, ctx: Dict[str, Any]) -> str:
        """把 MoviePilot 重命名模板里的 {{field}} 替换为 ctx 值，未知字段留空。"""
        def _rep(m):
            key = m.group(1).strip()
            return str(ctx.get(key, "") or "")
        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", _rep, template)

    def _normalize_episode_tree(self, dest_dir: str, naming_template: str = "", final_title: str = "") -> None:
        """把目标目录下的媒体文件重组为 MoviePilot 配置的重命名格式；
        无模板时回退为 Season N/S01E01 标准结构。多集合并文件保留。"""
        # 从最终名称解析 (title, year)，year 形如 "标题 (2018)"
        t_title = final_title
        t_year = ""
        m_year = re.search(r"\((\d{4})\)\s*$", final_title)
        if m_year:
            t_year = m_year.group(1)
            t_title = final_title[: m_year.start()].rstrip(" (）")
        files = []
        for root, _, fnames in os.walk(dest_dir):
            rel_root = os.path.relpath(root, dest_dir)
            folder_season = self._folder_season(root)
            for fn in fnames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in self.MEDIA_EXTENSIONS:
                    continue
                files.append((root, rel_root, fn, folder_season))
        seen_targets = set()
        for root, rel_root, fn, folder_season in files:
            stem = os.path.splitext(fn)[0]
            parsed = self._parse_season_episode(stem)
            if parsed is None:
                bare_ep = self._parse_bare_episode(stem)
                if bare_ep is not None:
                    parsed = (folder_season if folder_season is not None else 1, bare_ep, None)
            season = parsed[0] if parsed else folder_season
            if parsed is None and season is None:
                season = 1
                start = None
            else:
                start = parsed[1] if parsed else None
            end = parsed[2] if parsed and parsed[2] is not None else None

            ext = os.path.splitext(fn)[1]
            if naming_template and start is not None:
                ctx = {
                    "title": t_title,
                    "name": t_title,
                    "year": t_year,
                    "season": season,
                    "episode": start,
                    "season2": season,
                    "episode2": end if end is not None else start,
                }
                rendered = self._subst_naming_template(naming_template, ctx)
                segs = [s for s in rendered.split("/") if s.strip() != ""]
                if segs:
                    # 模板第一段通常是 "{{title}} {{year}}" 标题文件夹，由最终名称文件夹承担，故剥离；
                    # 其余段（如 Season N）作为子目录，最后一段为文件名校验模板。
                    file_pat = segs[-1]
                    folder_segs = segs[1:-1] if len(segs) > 1 else []
                    folder_rel = "/".join(folder_segs)
                    pat_ext = os.path.splitext(file_pat)[1]
                    base = file_pat[: -len(pat_ext)] if pat_ext else file_pat
                    new_name = base + ext
                    target = os.path.join(dest_dir, folder_rel, new_name) if folder_rel else os.path.join(dest_dir, new_name)
                else:
                    season_dir = os.path.join(dest_dir, "Season {}".format(season))
                    new_name = "S{:02d}E{:02d}".format(season, start)
                    if end is not None:
                        new_name += "-E{:02d}".format(end)
                    new_name += ext
                    target = os.path.join(season_dir, new_name)
            else:
                season_dir = os.path.join(dest_dir, "Season {}".format(season))
                os.makedirs(season_dir, exist_ok=True)
                new_name = stem
                if start is not None:
                    new_name = "S{:02d}E{:02d}".format(season, start)
                    if end is not None:
                        new_name += "-E{:02d}".format(end)
                new_name += ext
                target = os.path.join(season_dir, new_name)

            n = 1
            base_t = target
            while target in seen_targets or os.path.exists(target):
                base_noext, _ = os.path.splitext(base_t)
                target = "{}-{}{}".format(base_noext, n, os.path.splitext(base_t)[1])
                n += 1
            src = os.path.join(root, fn)
            if os.path.abspath(src) != os.path.abspath(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(src, target)
            seen_targets.add(target)
        # 清理空目录
        for root, dirs, fnames in os.walk(dest_dir, topdown=False):
            if root == dest_dir:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass

    @staticmethod
    def _tmdb_candidate_response(candidate: naming.MetadataCandidate) -> Dict[str, Any]:
        media_type = candidate.media_type if candidate.media_type in {"tv", "movie"} else "unknown"
        media_label = {"tv": "电视剧", "movie": "电影"}.get(media_type, "未知类型")
        return {
            "candidate_key": candidate.key,
            "title": candidate.title,
            "year": candidate.year,
            "media_type": media_type,
            "label": media_label,
        }

    def _review_row_for_request(
        self, payload: Optional[Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]], str]:
        if not isinstance(payload, dict):
            return None, None, None, "请求参数无效"
        raw_title = payload.get("raw_title")
        raw_title_valid, _ = naming.validate_manual_raw_title(raw_title)
        if not raw_title_valid:
            return None, None, None, "课程名称无效"
        revision = payload.get("revision")
        if not isinstance(revision, str) or not revision:
            return None, None, None, "缺少预览版本"
        rows = self._review_rows(include_internal=True, raw_title=raw_title)
        current = next((item for item in rows if item.get("raw_title") == raw_title), None)
        if current is None:
            return raw_title, revision, None, "预览记录不存在或已失效"
        if revision != current.get("revision"):
            return raw_title, revision, None, "预览已更新，请刷新后再操作"
        binding = current.get("_source_binding")
        if not isinstance(binding, dict):
            return raw_title, revision, None, "源目录已不存在或已变化，请刷新预览"
        return raw_title, revision, current, ""

    def search_tmdb(self, payload: Optional[Dict[str, Any]] = Body(default=None)) -> Any:
        # Read-only search: never holds the move lock, so other rows keep working
        # while a single confirmation is moving files.
        raw_title, _revision, current, message = self._review_row_for_request(payload)
        if message:
            return self._review_response(False, message=message)
        config = self._get_config()
        if config.get("naming_mode") == "off":
            return self._review_response(False, message="请先启用命名预览后再搜索 TMDB")
        # 优先使用用户修改后的新名称进行搜索；未提供时回退到原始目录名。
        search_name = str(payload.get("search_name") or raw_title) if isinstance(payload, dict) else str(raw_title)
        result = self._get_resolver().search_tmdb_candidates(
            search_name, NamingConfig.sanitize(config), limit=10
        )
        candidates = [
            candidate
            for candidate in result.candidates[:10]
            if candidate.source == "themoviedb"
        ]
        if not candidates:
            if result.all_failed or result.errors:
                return self._review_response(
                    False,
                    message="TMDB 连接失败，请检查 MoviePilot 网络或 TMDB API 服务地址",
                )
            return self._review_response(
                False,
                message="未找到 TMDB 候选，请检查名称或 TMDB 数据源配置",
            )
        return self._review_response(
            True,
            {
                "raw_title": raw_title,
                "revision": current.get("revision"),
                "items": [self._tmdb_candidate_response(candidate) for candidate in candidates],
            },
            "已按目录名称找到 TMDB 候选",
        )

    def associate_tmdb(self, payload: Optional[Dict[str, Any]] = Body(default=None)) -> Any:
        # The store write is protected by _review_data_lock inside _save_manual_decision;
        # the move lock is intentionally not taken here.
        raw_title, _revision, current, message = self._review_row_for_request(payload)
        if message:
            return self._review_response(False, message=message)
        candidate_key = payload.get("candidate_key") if isinstance(payload, dict) else None
        if (
            not isinstance(candidate_key, str)
            or not candidate_key
            or len(candidate_key) > 255
            or any(ord(char) < 0x20 or ord(char) in {0x7F, 0x85} for char in candidate_key)
        ):
            return self._review_response(False, message="TMDB 候选无效")
        config = self._get_config()
        if config.get("naming_mode") == "off":
            return self._review_response(False, message="请先启用命名预览后再关联 TMDB")
        result = self._get_resolver().search_tmdb_candidates(
            str(payload.get("search_name") or raw_title), NamingConfig.sanitize(config), limit=10
        )
        candidate = next(
            (
                item
                for item in result.candidates[:10]
                if item.key == candidate_key and item.source == "themoviedb"
            ),
            None,
        )
        if candidate is None:
            if result.all_failed or result.errors:
                return self._review_response(
                    False,
                    message="TMDB 连接失败，请检查 MoviePilot 网络或 TMDB API 服务地址",
                )
            return self._review_response(False, message="TMDB 候选已失效，请重新搜索")
        binding = current.get("_source_binding") if isinstance(current, dict) else None
        if not isinstance(binding, dict):
            return self._review_response(False, message="源目录已不存在或已变化，请刷新预览")
        target_library = str(current.get("target_library", "")).lower()
        if target_library not in self._manual_target_libraries():
            target_library = ""
        final_title = naming.format_selected_candidate_name(
            candidate,
            append_tmdb_id=False,
        )
        if not self._save_manual_decision(
            str(raw_title),
            "candidate",
            final_title,
            target_library,
            str(current.get("source_revision", "")),
            binding,
            candidate=candidate,
        ):
            return self._review_response(False, message="保存 TMDB 关联失败")
        self._logger.info(
            "CourseOrganizer[event=manual_tmdb_associated] item_course_repr=%s",
            ascii(str(raw_title)),
        )
        self._resolver = None
        self._resolver_signature = ()
        latest = next(
            (
                item
                for item in self._review_rows(raw_title=str(raw_title))
                if item.get("raw_title") == raw_title
            ),
            None,
        )
        return self._review_response(True, latest or {}, "已保存 TMDB 关联")

    def get_page(self) -> List[Dict[str, Any]]:
        config = self._review_path_config()
        naming_mode = str(config["naming_mode"])
        rows: List[Dict[str, Any]] = []
        if naming_mode != "off":
            rows = self._review_rows()

        target_labels = {"tv": "电视剧", "movie": "电影", "children": "儿童"}
        display_rows: List[Dict[str, Any]] = []
        status_counts = {"可以整理": 0, "需要确认": 0, "已跳过": 0}
        for source_row in rows:
            if not isinstance(source_row, dict):
                continue
            stored_status = str(source_row.get("status", "")).strip().lower()
            target_library = str(source_row.get("target_library", "")).lower()
            if stored_status == "ignore":
                display_status = "已跳过"
            elif stored_status in {"auto_external", "local_fallback"} and target_library in target_labels:
                display_status = "可以整理"
            else:
                display_status = "需要确认"

            display_rows.append(
                {
                    "raw_title": str(source_row.get("raw_title", "")),
                    "final_title": str(
                        source_row.get("final_title")
                        or source_row.get("local_title")
                        or source_row.get("raw_title", "")
                    ),
                    "target_position": str(
                        source_row.get("target_output_root")
                        or target_labels.get(target_library, "待确认")
                    ),
                    "status": display_status,
                }
            )
            status_counts[display_status] += 1

        headers = [
            {"title": title, "text": title, "key": key, "value": key}
            for key, title in (
                ("raw_title", "原始名称"),
                ("final_title", "建议名称"),
                ("target_position", "目标位置"),
                ("status", "状态"),
            )
        ]
        preview_subtitle = (
            "命名已关闭，仍会整理；此页未读取预览记录"
            if naming_mode == "off"
            else (
                f"{len(display_rows)} 条记录 · 符合条件的项目将自动整理"
                if naming_mode == "apply"
                else f"{len(display_rows)} 条记录 · 只记录建议，不移动文件"
            )
        )
        preview_table = {
            "component": "VDataTableVirtual",
            "props": {
                "class": "course-preview-table text-sm",
                "headers": headers,
                "items": display_rows,
                "height": "min(52vh, 30rem)",
                "density": "compact",
                "fixed-header": True,
                "hide-no-data": True,
                "hover": True,
            },
        }
        status_chips = [
            {
                "component": "VChip",
                "props": {
                    "color": color,
                    "size": "small",
                    "variant": "tonal",
                    "aria-label": f"{label} {status_counts[label]} 条",
                },
                "text": f"{label} {status_counts[label]}",
            }
            for label, color in (
                ("可以整理", "success"),
                ("需要确认", "warning"),
                ("已跳过", "default"),
            )
        ]
        preview_content: List[Dict[str, Any]] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "comfortable",
                    "class": "ma-3 mb-2",
                },
                "text": "只记录建议，不移动文件。先核对名称和目标位置，再决定是否开启自动整理。",
            },
            {
                "component": "VSheet",
                "props": {
                    "class": "course-status-summary d-flex flex-wrap align-center ga-2 px-4 py-2 border-b",
                    "color": "transparent",
                    "aria-label": "预览状态统计",
                },
                "content": status_chips,
            },
        ]
        if not display_rows:
            preview_content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "class": "mx-3 mb-3",
                        "role": "status",
                    },
                    "text": "暂无可预览记录。选择目录并开启安全预览后，这里会显示建议。",
                }
            )
        preview_content.append(
            {
                "component": "VSheet",
                "props": {
                    "class": "course-preview-table-wrap overflow-x-auto",
                    "color": "transparent",
                },
                "content": [preview_table],
            }
        )
        preview_card = {
            "component": "VCard",
            "props": {
                "title": "安全预览",
                "subtitle": preview_subtitle,
                "variant": "outlined",
                "class": "course-preview-card",
            },
            "content": preview_content,
        }

        enabled_text = "已启用" if config["enabled"] else "已停用"
        run_once_text = "已请求一次性运行" if config["run_once"] else "未请求一次性运行"
        policy_text = (
            "低置信度时保留本地名"
            if config["naming_uncertain_policy"] == "local"
            else "低置信度时暂停整理"
        )
        return [
            {
                "component": "VCol",
                "props": {"cols": 12, "class": "pt-0"},
                "content": [preview_card],
            },
            {
                "component": "VRow",
                "props": {"align": "stretch", "class": "mt-2 ga-2"},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4, "class": "pa-0"},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {
                                    "title": "运行状态",
                                    "text": (
                                        f"{enabled_text} · 每 {config['interval']} 秒扫描 · {run_once_text} · "
                                        f"{policy_text}"
                                    ),
                                    "variant": "tonal",
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 8, "class": "pa-0"},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {
                                    "title": "目录流向",
                                    "text": (
                                        f"{config['incoming']} → 电视剧 {config['tv_output']} · "
                                        f"电影 {config['movie_output']} · 儿童 {config['children_output']}"
                                    ),
                                    "variant": "tonal",
                                    "class": "text-break",
                                },
                            }
                        ],
                    },
                ],
            },
        ]

    def get_state(self) -> bool:
        return bool(self._get_config().get("enabled"))

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        config = self._get_config()
        defaults = dict(config)
        context = self._moviepilot_directory_context()
        content: List[Dict[str, Any]] = [
            {
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal", "class": "mb-3"},
                "text": (
                    "插件独立维护下载目录和归档目录，可添加多个目录。"
                    "自动识别仅映射现有 tv/movie/children 内置 key；"
                    "其他归档目录可在人工确认时选择。"
                ),
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "warning" if not context.get("ready") else "success",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-3",
                },
                "text": context.get("message")
                or "已使用插件配置的下载目录和归档目录。",
            },
            {
                "component": "VSwitch",
                "props": {
                    "model": "auto_organize",
                    "label": "自动整理符合条件的项目",
                    "hint": "目录未完整配置或下载目录不可读取时，将自动保持安全预览。",
                    "persistent-hint": True,
                    "color": "primary",
                },
            },
        ]
        return [
            {
                "component": "VForm",
                "props": {
                    "class": "courseorganizer-form",
                    "aria-label": "整理识别设置",
                },
                "content": content,
            }
        ], defaults

    def get_service(self) -> List[Dict[str, Any]]:
        config = self._get_config()
        if not bool(config.get("enabled")):
            return []
        interval = int(config.get("interval", self.DEFAULT_INTERVAL))
        return [
            {
                "id": self.__class__.__name__,
                "name": "CourseOrganizer 课程整理服务",
                "trigger": "interval",
                "func": self.run,
                "kwargs": {
                    "seconds": interval,
                },
            }
        ]

    def stop_service(self) -> None:
        plugin_cls = type(self)
        with plugin_cls._run_once_lock:
            owner = plugin_cls._run_once_owner
            plugin_cls._invalidate_run_once_locked()
            reset_target = owner or self
            reset_config = reset_target._normalize_config(reset_target._get_config())
            reset_config["run_once"] = False
            if not reset_target._persist_config(reset_config):
                reset_target._logger.error(
                    "CourseOrganizer[event=run_once_persist_failed] phase=stop"
                )
            reset_target._config_snapshot = reset_config
            if reset_target is not self:
                reset_config = self._normalize_config(self._get_config())
                reset_config["run_once"] = False
                if not self._persist_config(reset_config):
                    self._logger.error(
                        "CourseOrganizer[event=run_once_persist_failed] phase=stop"
                    )
                self._config_snapshot = reset_config

    def run(self) -> None:
        with self._thread_lock:
            self._run()

    def _run(self, force: bool = False) -> None:
        run_config_local = getattr(self, "_run_config_local", None)
        if run_config_local is None:
            run_config_local = threading.local()
            self._run_config_local = run_config_local
        original_config = getattr(run_config_local, "config", _MANUAL_DATA_UNSET)
        runtime_config = self._review_path_config()
        run_config_local.config = dict(runtime_config)
        try:
            self._run_with_config(force)
        finally:
            if original_config is _MANUAL_DATA_UNSET:
                try:
                    del run_config_local.config
                except AttributeError:
                    pass
            else:
                run_config_local.config = original_config

    def _run_with_config(self, force: bool = False) -> None:
        config = self._get_config()
        if not force and not config.get("enabled"):
            self._logger.debug("CourseOrganizer[event=wait] plugin disabled")
            return

        if config.get("monitoring_conflict"):
            self._logger.warning(
                "CourseOrganizer[event=directory_config_blocked] action=preview_only message=%s",
                config["monitoring_conflict"],
            )

        downloads = self._download_paths(config)
        output_roots = self._archive_output_roots(config)
        if not downloads:
            self._logger.error("download directories missing")
            return
        if not output_roots:
            self._logger.error("archive directories missing")
            return

        def canonical(path: Any) -> str:
            return os.path.realpath(os.path.abspath(str(path)))

        normalized_downloads = [(path, canonical(path)) for path in downloads]
        normalized_outputs = {
            key: canonical(path)
            for key, path in output_roots.items()
            if str(path or "").strip()
        }
        if len(normalized_outputs) != len(output_roots):
            self._logger.error("archive directory paths missing")
            return
        if len(set(normalized_outputs.values())) != len(normalized_outputs):
            self._logger.error("archive directory paths overlap")
            return
        for _source_root, incoming in normalized_downloads:
            if not os.path.isdir(incoming):
                self._logger.error("download path invalid: %s", incoming)
                return
            if any(self._paths_overlap(incoming, output) for output in normalized_outputs.values()):
                self._logger.error("download path overlaps archive directory: %s", incoming)
                return

        for source_root, incoming in normalized_downloads:
            try:
                entries = sorted(os.listdir(incoming), key=self._natural_key)
            except OSError as exc:
                self._logger.error(
                    "CourseOrganizer[event=download_scan_failed] directory=%s reason=%s",
                    self._safe_log_value(incoming),
                    exc.__class__.__name__,
                )
                continue
            for entry in entries:
                if self._is_ignored_scan_entry(entry):
                    continue
                course_dir = os.path.join(incoming, entry)
                if not os.path.isdir(course_dir):
                    continue
                try:
                    self._process_course(
                    entry,
                    course_dir,
                        source_root=source_root,
                )
                except Exception as exc:
                    self._logger.exception(
                        "CourseOrganizer[event=course_process_failed] item_course_repr=%s reason=%s",
                        ascii(entry),
                        exc.__class__.__name__,
                    )

    @classmethod
    def _run_once_dispatch(cls, token: int) -> None:
        cls._run_once_and_reset(token)

    @classmethod
    def _invalidate_run_once_locked(cls) -> None:
        timer = cls._run_once_timer
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        cls._run_once_timer = None
        cls._run_once_owner = None
        cls._run_once_claimed = False
        cls._run_once_generation += 1
        cls._run_once_token = None

    @classmethod
    def _run_once_and_reset(cls, token: Optional[int] = None) -> None:
        with cls._thread_lock:
            with cls._run_once_lock:
                if token is None:
                    token = cls._run_once_token
                if token is None or cls._run_once_token != token:
                    return
                owner = cls._run_once_owner
                if owner is None or cls._run_once_claimed:
                    return
                cls._run_once_claimed = True
                latest_config = owner._normalize_config(owner._get_config())
                latest_config["run_once"] = False
                if not owner._persist_config(latest_config):
                    cls._invalidate_run_once_locked()
                    owner._logger.error(
                        "CourseOrganizer[event=run_once_persist_failed] phase=claim"
                    )
                    return
                owner._config_snapshot = latest_config
                owner._run_config_local.config = dict(latest_config)
                cls._run_once_timer = None
                cls._run_once_owner = None
                cls._run_once_claimed = False
                cls._run_once_generation += 1
                cls._run_once_token = None
            try:
                owner._run(force=True)
            finally:
                try:
                    del owner._run_config_local.config
                except AttributeError:
                    pass

    def _resolve_naming(
        self,
        course_name: str,
        directory_hints: naming.DirectoryHints,
        legacy_output_root: str,
        target_output_root: str,
        manual_decision: Optional[naming.ManualOverride] = None,
    ) -> NamingDecision:
        config = NamingConfig.sanitize(self._get_config())
        if config.mode == "off":
            return self._decision_from_config_off(course_name)

        resolver = self._get_resolver()
        decision = resolver.resolve(
            course_name,
            directory_hints,
            config,
            legacy_output_root=legacy_output_root,
            target_output_root=target_output_root,
            manual_decision=manual_decision,
        )
        return decision

    def _decision_from_config_off(self, course_name: str) -> NamingDecision:
        return NamingDecision(
            status="local_fallback",
            raw_title=course_name,
            local_title=course_name,
            final_root=course_name,
            final_prefix=course_name,
        )

    @staticmethod
    def _decision_from_resolver(
        source: NamingDecision,
        status: str,
        blocked_reason: str,
    ) -> NamingDecision:
        return NamingDecision(
            status=status,
            raw_title=source.raw_title,
            local_title=source.local_title,
            final_root=source.final_root,
            final_prefix=source.final_prefix,
            source=source.source,
            media_id=source.media_id,
            media_type=source.media_type,
            score=source.score,
            margin=source.margin,
            candidate_key=source.candidate_key,
            reason_codes=tuple(source.reason_codes),
            source_errors=tuple(source.source_errors),
            blocked_reason=blocked_reason,
            legacy_output_root=source.legacy_output_root,
            target_output_root=source.target_output_root,
            target_library=source.target_library,
        )

    def _get_resolver(self) -> SmartNamingResolver:
        config = self._get_config()
        signature = (
            config.get("naming_mode"),
            config.get("naming_ai_review"),
            config.get("naming_auto_threshold"),
            config.get("naming_min_margin"),
            config.get("naming_uncertain_policy"),
            config.get("naming_manual_overrides"),
        )
        if self._resolver is None or self._resolver_signature != signature:
            self._resolver = self._build_resolver(config)
            self._resolver_signature = signature
        return self._resolver

    def _get_library_classifier(self) -> MoviePilotLibraryClassifier:
        if self._library_classifier_override is not None:
            return self._library_classifier_override
        if self._library_classifier is None:
            self._library_classifier = MoviePilotLibraryClassifier()
        return self._library_classifier

    def _resolve_library_route(
        self,
        course_name: str,
        decision: NamingDecision,
        directory_hints: naming.DirectoryHints,
    ) -> LibraryRouteResult:
        if self._get_config().get("naming_mode") == "off":
            return LibraryRouteResult(
                accepted=False,
                library="hold",
                confidence=0.0,
                reason_codes=("naming_off",),
                error="",
            )
        if not self._get_config().get("naming_ai_review"):
            return LibraryRouteResult(
                accepted=False,
                library="hold",
                confidence=0.0,
                reason_codes=("ai_routing_disabled",),
                error="",
            )

        cache_key = "\x1f".join(
            (
                "library-routing-v1",
                course_name,
                decision.final_root,
                decision.media_type,
                "1" if directory_hints.episodic else "0",
            )
        )
        cache = self._load_plugin_data("library_routing_cache_v1", {})
        if not isinstance(cache, dict):
            cache = {}
        now = int(self._clock())
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            ttl = 30 * 24 * 60 * 60 if cached.get("accepted") else 60 * 60
            try:
                fresh = now - int(cached.get("updated", 0)) < ttl
            except (TypeError, ValueError):
                fresh = False
            if fresh:
                return LibraryRouteResult(
                    accepted=bool(cached.get("accepted")),
                    library=str(cached.get("library", "hold")),
                    confidence=float(cached.get("confidence", 0.0)),
                    reason_codes=tuple(cached.get("reason_codes", ())),
                    error=str(cached.get("error", "")),
                )

        result = self._get_library_classifier().classify(
            raw_title=course_name,
            final_title=decision.final_root,
            media_type=decision.media_type,
            episodic=directory_hints.episodic,
        )
        cache[cache_key] = {
            "updated": now,
            "accepted": result.accepted,
            "library": result.library,
            "confidence": result.confidence,
            "reason_codes": list(result.reason_codes),
            "error": result.error,
        }
        if len(cache) > 500:
            oldest = sorted(
                cache,
                key=lambda key: int(cache[key].get("updated", 0))
                if isinstance(cache.get(key), dict)
                else 0,
            )
            for key in oldest[: len(cache) - 500]:
                cache.pop(key, None)
        self.save_data("library_routing_cache_v1", cache)
        return result

    def _process_course(
        self,
        course_name: str,
        course_path: str,
        output_root: Optional[str] = None,
        source_root: Optional[str] = None,
    ) -> bool:
        with self._thread_lock:
            return self._process_course_locked(
                course_name,
                course_path,
                output_root=output_root,
                source_root=source_root,
            )

    def _process_course_locked(
        self,
        course_name: str,
        course_path: str,
        output_root: Optional[str] = None,
        source_root: Optional[str] = None,
        apply_result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        valid_title, _ = naming.validate_manual_raw_title(course_name)
        if not valid_title:
            self._logger.warning(
                "CourseOrganizer[event=scan_entry_rejected] item_course_repr=%s",
                ascii(course_name),
            )
            return False
        course_log = self._safe_log_value(course_name)
        state_key = self._state_key(course_name)
        if source_root is not None and not self._is_within_realpath(source_root, course_path):
            self.save_data(state_key, None)
            self._logger.error(
                "CourseOrganizer[event=source_path_escape] item_course=%s",
                course_log,
            )
            return False
        signature = self._coerce_signature(self._snapshot_signature(course_path))
        state = self._load_plugin_data(state_key, {})
        persisted_signature = self._coerce_signature(state.get("signature")) if isinstance(state, dict) else ()

        if self._has_incomplete_file(course_path):
            self.save_data(
                state_key,
                {
                    "signature": signature,
                    "stable_count": 0,
                    "blocked": True,
                },
            )
            self._logger.info(
                "CourseOrganizer[event=item_deferred] item_course=%s item_reason=initial_incomplete",
                course_log,
            )
            self._logger.debug(
                "CourseOrganizer[event=incomplete_blocked] item_phase=initial item_course=%s",
                course_log,
            )
            return False

        if not state:
            self.save_data(state_key, {"signature": signature, "stable_count": 1})
            self._logger.debug(
                "CourseOrganizer[event=item_deferred] item_course=%s "
                "item_reason=first_snapshot item_stable_count=1",
                course_log,
            )
            return False

        if signature != persisted_signature:
            self.save_data(state_key, {"signature": signature, "stable_count": 1})
            self._logger.debug(
                "CourseOrganizer[event=item_deferred] item_course=%s "
                "item_reason=changed_before_stabilization item_stable_count=1",
                course_log,
            )
            return False

        stable_count = int(state.get("stable_count", 0)) if isinstance(state, dict) else 0
        if stable_count < 1:
            next_stable_count = stable_count + 1
            self.save_data(state_key, {"signature": signature, "stable_count": next_stable_count})
            self._logger.debug(
                "CourseOrganizer[event=item_deferred] item_course=%s "
                "item_reason=stable_count_pending item_stable_count=%d",
                course_log,
                next_stable_count,
            )
            return False

        latest_signature = self._coerce_signature(self._snapshot_signature(course_path))
        if latest_signature != signature:
            self.save_data(state_key, {"signature": latest_signature, "stable_count": 1})
            self._logger.debug(
                "CourseOrganizer[event=item_deferred] item_course=%s "
                "item_reason=changed_before_final_confirmation item_stable_count=1",
                course_log,
            )
            return False

        if self._has_incomplete_file(course_path):
            self._logger.debug(
                "CourseOrganizer[event=incomplete_blocked] item_phase=final item_course=%s",
                course_log,
            )
            self.save_data(state_key, {"signature": latest_signature, "stable_count": 0, "blocked": True})
            return False

        media_by_season, subtitle_by_season, has_explicit_season = self._collect_course_files(course_path)
        if not media_by_season:
            self._logger.debug("CourseOrganizer[event=no_media] item_course=%s", course_log)
            self.save_data(state_key, None)
            return False

        parse_hints = naming.parse_title(course_name)
        media_count = sum(len(items) for items in media_by_season.values())
        directory_hints = naming.DirectoryHints(
            media_count=media_count,
            seasons=tuple(sorted(media_by_season)) if has_explicit_season else (),
            episodic=(media_count > 1 or len(media_by_season) > 1 or bool(parse_hints.season_hints)),
        )

        mode = self._get_config().get("naming_mode")
        manual_decision: Optional[naming.ManualOverride] = None
        manual_binding: Optional[Dict[str, Any]] = None
        if mode == "off":
            decision = self._decision_from_config_off(course_name)
        else:
            manual_decision = self._manual_decision_for(course_name)
            if manual_decision is not None and manual_decision.action in {"confirm", "ignore", "candidate"}:
                expected_binding = self._manual_binding(manual_decision)
                if not self._source_binding_matches(course_name, expected_binding):
                    self._logger.warning(
                        "CourseOrganizer[event=manual_decision_stale] item_course_repr=%s",
                        ascii(course_name),
                    )
                    manual_decision = naming.ManualOverride(course_name, "invalid")
                elif manual_decision.action in {"confirm", "candidate"}:
                    manual_binding = expected_binding
            resolve_kwargs = (
                {"manual_decision": manual_decision}
                if manual_decision is not None
                else {}
            )
            decision = self._resolve_naming(
                course_name,
                directory_hints,
                "",
                "",
                **resolve_kwargs,
            )

        route_result: Optional[LibraryRouteResult] = None
        target_library = "legacy"
        if output_root is None:
            if not decision.allowed_to_move:
                if mode != "off":
                    decision = self._get_resolver().record_decision(
                        decision,
                        target_library="hold",
                        library_confidence=0.0,
                        library_reason_codes=("naming_blocked",),
                    )
                if mode == "preview":
                    self._logger.info(
                        "CourseOrganizer[event=preview] item_course=%s item_final=%s item_library=%s",
                        course_log,
                        self._safe_log_value(decision.final_root),
                        "hold",
                    )
                    return False
                self._logger.debug(
                    "CourseOrganizer[event=naming_blocked] item_course=%s item_reason=%s",
                    course_log,
                    decision.status,
                )
                return False

            manual_target = str(decision.target_library or "").lower()
            archive = self._archive_directory_by_key(manual_target)
            if archive is not None:
                target_library = manual_target
                output_root = archive.get("path")
                route_result = LibraryRouteResult(
                    accepted=True,
                    library=target_library,
                    confidence=1.0,
                    reason_codes=("manual_confirm",),
                    error="",
                )
            else:
                route_result = self._resolve_library_route(course_name, decision, directory_hints)
                target_library = route_result.library
            if not route_result.accepted:
                self._logger.debug(
                    "CourseOrganizer[event=library_hold] item_course=%s item_confidence=%.3f item_reasons=%s",
                    course_log,
                    route_result.confidence,
                    ",".join(route_result.reason_codes),
                )
                held = self._decision_from_resolver(
                    source=decision,
                    status="library_hold",
                    blocked_reason="library_hold",
                )
                if mode != "off":
                    self._get_resolver().record_decision(
                        held,
                        target_library="hold",
                        library_confidence=route_result.confidence,
                        library_reason_codes=route_result.reason_codes,
                    )
                self._logger.debug(
                    "CourseOrganizer: %s held by library classification %s",
                    course_log,
                    ",".join(route_result.reason_codes),
                )
                return False
            archive = self._archive_directory_by_key(target_library)
            output_root = archive.get("path") if archive is not None else None
        if not output_root:
            self._logger.error("output path missing for library: %s", target_library)
            return False

        output_root = os.path.realpath(os.path.abspath(str(output_root)))
        if not os.path.isdir(output_root):
            if mode != "preview":
                if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0):
                    self._logger.error(
                        "CourseOrganizer[event=secure_move_unsupported] item_course=%s",
                        course_log,
                    )
                    return False
                try:
                    os.makedirs(output_root, exist_ok=True)
                except OSError:
                    self._logger.error(
                        "CourseOrganizer[event=destination_root_create_failed] item_course=%s",
                        course_log,
                    )
                    return False

        legacy_output_root = os.path.join(output_root, self._safe_name(course_name))
        target_output_root = os.path.join(output_root, self._safe_name(decision.final_root))
        if mode != "off":
            decision = self._get_resolver().record_decision(
                decision,
                legacy_output_root=legacy_output_root,
                target_output_root=target_output_root,
                target_library=target_library,
                library_confidence=route_result.confidence if route_result else 1.0,
                library_reason_codes=route_result.reason_codes if route_result else ("legacy_override",),
            )

        if self._safe_name(decision.final_root) != self._safe_name(course_name) and os.path.isdir(legacy_output_root):
            self._logger.debug(
                "CourseOrganizer[event=legacy_conflict] item_course=%s item_final=%s item_library=%s",
                course_log,
                self._safe_log_value(decision.final_root),
                target_library,
            )
            decision = self._decision_from_resolver(
                source=decision,
                status="legacy_output_conflict",
                blocked_reason="legacy_output_conflict",
            )
            if mode != "off":
                decision = self._get_resolver().record_output_conflict(
                    decision,
                    legacy_output_root=legacy_output_root,
                    target_output_root=os.path.join(output_root, self._safe_name(decision.final_root)),
                    target_library=target_library,
                    library_confidence=route_result.confidence if route_result else 1.0,
                    library_reason_codes=route_result.reason_codes if route_result else ("legacy_override",),
                )
            return False

        if mode == "preview":
            self._logger.info(
                "CourseOrganizer[event=preview] item_course=%s item_final=%s item_library=%s",
                course_log,
                self._safe_log_value(decision.final_root),
                target_library,
            )
            return False

        if not decision.allowed_to_move:
            self._logger.debug(
                "CourseOrganizer[event=naming_blocked] item_course=%s item_reason=%s",
                course_log,
                decision.status,
            )
            return False

        output_course_root = os.path.join(output_root, self._safe_name(decision.final_root))
        if not self._is_within_realpath(output_root, output_course_root):
            self._logger.error(
                "CourseOrganizer[event=destination_path_escape] item_course=%s",
                course_log,
            )
            return False

        self._logger.info(
            "CourseOrganizer[event=move_started] item_course=%s item_final=%s item_library=%s item_media_count=%d",
            course_log,
            self._safe_log_value(decision.final_root),
            target_library,
            media_count,
        )
        if not self._is_within_realpath(output_root, output_course_root):
            self._logger.error(
                "CourseOrganizer[event=destination_path_escape] item_course=%s",
                course_log,
            )
            return False

        move_context = self._create_move_context(
            course_path,
            output_root,
            expected_manifest=(manual_binding or {}).get("source_manifest"),
            expected_directories=(manual_binding or {}).get("source_directory_manifest"),
        )
        if move_context is None:
            self.save_data(state_key, None)
            return False

        move_plan: List[Tuple[str, str, List[Tuple[str, str]]]] = []
        planned_targets: set[str] = set()
        season_roots: List[str] = []
        safe_course_name = self._safe_name(decision.final_prefix)

        def _reserve_plan_path(path: str) -> str:
            base, ext = os.path.splitext(path)
            candidate = path
            index = 1
            while os.path.exists(candidate) or candidate in planned_targets:
                candidate = f"{base}_{index}{ext}"
                index += 1
            return candidate

        for season in sorted(media_by_season.keys()):
            season_files = sorted(media_by_season[season], key=lambda file_path: self._course_sort_key(file_path, course_path))
            season_root = os.path.join(output_course_root, f"Season {season}")
            season_roots.append(season_root)
            leading_spans = [self._extract_leading_episode_span(media_file) for media_file in season_files]

            used_episodes = set(self._collect_existing_episodes(season_root, safe_course_name, season))
            next_episode = max(
                self._next_episode_number(season_root, safe_course_name, season) - 1,
                max((span[1] for span in leading_spans if span is not None), default=0),
            )
            next_episode += 1

            for media_file, leading_span in zip(season_files, leading_spans):
                if leading_span is not None:
                    requested_start, requested_end = leading_span
                    requested_width = requested_end - requested_start + 1
                    if all(
                        requested_index not in used_episodes
                        for requested_index in range(requested_start, requested_end + 1)
                    ):
                        assigned_start = requested_start
                        assigned_end = requested_end
                    else:
                        assigned_start = next_episode
                        while True:
                            requested_window = range(
                                assigned_start,
                                assigned_start + requested_width,
                            )
                            if all(index not in used_episodes for index in requested_window):
                                assigned_end = assigned_start + requested_width - 1
                                break
                            assigned_start += 1
                else:
                    assigned_start = next_episode
                    assigned_end = next_episode

                next_episode = max(next_episode, assigned_end + 1)
                used_episodes.update(range(assigned_start, assigned_end + 1))

                ext = self._lower_extension(media_file)
                episode_name = (
                    f"{safe_course_name} - "
                    f"{self._format_episode_token(season, assigned_start, assigned_end)}{ext}"
                )
                target_media = _reserve_plan_path(os.path.join(season_root, episode_name))
                planned_targets.add(target_media)

                media_key = os.path.splitext(os.path.basename(media_file))[0].lower()
                target_subtitles: List[Tuple[str, str]] = []
                for subtitle_file in subtitle_by_season.get(season, {}).get(media_key, []):
                    subtitle_ext = self._lower_extension(subtitle_file)
                    subtitle_name = (
                        f"{safe_course_name} - "
                        f"{self._format_episode_token(season, assigned_start, assigned_end)}{subtitle_ext}"
                    )
                    target_subtitle = _reserve_plan_path(os.path.join(season_root, subtitle_name))
                    planned_targets.add(target_subtitle)
                    target_subtitles.append((subtitle_file, target_subtitle))

                move_plan.append((media_file, target_media, target_subtitles))

        for season_root in season_roots:
            if not self._is_within_realpath(output_root, season_root):
                self._logger.error(
                    "CourseOrganizer[event=destination_path_escape] item_course=%s",
                    course_log,
                )
                self._rollback_move_context(move_context)
                self._close_move_context(move_context)
                return False

        for media_file, target_media, subtitle_pairs in move_plan:
            if not self._is_within_realpath(course_path, media_file):
                self._logger.error(
                    "CourseOrganizer[event=source_path_escape] item_course=%s",
                    course_log,
                )
                self._rollback_move_context(move_context)
                self._close_move_context(move_context)
                return False
            if not self._is_within_realpath(output_root, target_media):
                self._logger.error(
                    "CourseOrganizer[event=destination_path_escape] item_course=%s",
                    course_log,
                )
                self._rollback_move_context(move_context)
                self._close_move_context(move_context)
                return False

            for subtitle_file, target_subtitle in subtitle_pairs:
                if not self._is_within_realpath(course_path, subtitle_file):
                    self._logger.error(
                        "CourseOrganizer[event=source_path_escape] item_course=%s",
                        course_log,
                    )
                    self._rollback_move_context(move_context)
                    self._close_move_context(move_context)
                    return False
                if not self._is_within_realpath(output_root, target_subtitle):
                    self._logger.error(
                        "CourseOrganizer[event=destination_path_escape] item_course=%s",
                        course_log,
                    )
                    self._rollback_move_context(move_context)
                    self._close_move_context(move_context)
                    return False

        try:
            move_counts = self._execute_move_plan(
                move_plan,
                course_path,
                output_root,
                move_context=move_context,
            )
        finally:
            self._close_move_context(move_context)
        if move_counts is None:
            self.save_data(state_key, None)
            return False
        moved_files, moved_subtitles = move_counts

        if moved_files:
            self._delete_if_empty_recursive(course_path)
            decision_consumed = True
            if manual_decision is not None and manual_decision.action == "confirm":
                decision_consumed = self._consume_manual_decision(
                    course_name,
                    self._manual_binding(manual_decision),
                )
            if apply_result is not None:
                apply_result["moved"] = True
                apply_result["decision_consumed"] = decision_consumed
            self._logger.info(
                "CourseOrganizer[event=move_completed] item_course=%s item_final=%s item_library=%s item_moved=%d item_subtitles=%d",
                course_log,
                self._safe_log_value(decision.final_root),
                target_library,
                moved_files,
                moved_subtitles,
            )
            self.save_data(state_key, None)
            return True

        self.save_data(state_key, None)
        return False

    def _collect_course_files(self, course_path: str) -> Tuple[Dict[int, List[str]], Dict[int, Dict[str, List[str]]], bool]:
        media_files: Dict[int, List[str]] = {}
        subtitle_map: Dict[int, Dict[str, List[str]]] = {}
        has_explicit_season = False

        for root, dirnames, filenames in os.walk(course_path):
            dirnames[:] = [
                name for name in dirnames if not self._is_ignored_scan_entry(name)
            ]
            for filename in filenames:
                if self._is_ignored_scan_entry(filename):
                    continue
                if self._is_incomplete(filename):
                    continue

                extension = self._lower_extension(filename)
                season, explicit = self._detect_season_from_path(os.path.join(root, filename), course_path)
                has_explicit_season = has_explicit_season or explicit
                if extension in self.MEDIA_EXTENSIONS:
                    media_files.setdefault(season, []).append(os.path.join(root, filename))
                    continue
                if extension in self.SUBTITLE_EXTENSIONS:
                    base = os.path.splitext(filename)[0].lower()
                    subtitle_map.setdefault(season, {}).setdefault(base, []).append(os.path.join(root, filename))

        for season, subtitles in subtitle_map.items():
            for key, subtitle_files in subtitles.items():
                subtitle_map[season][key] = sorted(subtitle_files, key=self._natural_path_key)

        return media_files, subtitle_map, has_explicit_season

    @classmethod
    def _detect_season_from_path(cls, file_path: str, course_path: str) -> Tuple[int, bool]:
        relative = os.path.relpath(file_path, course_path)
        directories = os.path.dirname(relative).split(os.sep)
        season = 1
        found = False
        for directory in directories:
            if not directory:
                continue
            parsed = cls._parse_season_from_component(directory)
            if parsed is not None:
                season = parsed
                found = True
        return season, found

    @staticmethod
    def _is_within_realpath(root: str, path: str) -> bool:
        root_real = os.path.realpath(os.path.abspath(root))
        path_real = os.path.realpath(os.path.abspath(path))
        try:
            return os.path.commonpath([path_real, root_real]) == root_real
        except ValueError:
            return False

    @classmethod
    def _parse_season_from_component(cls, component: str) -> Optional[int]:
        match = _EN_SEASON_RE.search(component)
        if match:
            raw = match.group(1) or match.group(2)
            try:
                season = int(raw)
            except (TypeError, ValueError):
                season = None
            else:
                if season > 0:
                    return season

        match = _CN_SEASON_RE.search(component)
        if match:
            season = cls._chinese_numeral_to_int(match.group(1))
            if season and season > 0:
                return season

        return None

    @staticmethod
    def _chinese_numeral_to_int(value: str) -> Optional[int]:
        if not value:
            return None
        if value.isdigit():
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        chars = list(value)
        if not chars:
            return None
        if "十" in value:
            if value == "十":
                return 10
            before, after = value.split("十", 1)
            tens = 1 if not before else _CHINESE_NUMERAL_MAP.get(before, 0)
            ones = _CHINESE_NUMERAL_MAP.get(after, 0) if after else 0
            return tens * 10 + ones

        total = 0
        for char in chars:
            if char not in _CHINESE_NUMERAL_MAP:
                return None
            total += _CHINESE_NUMERAL_MAP[char]

        return total if total > 0 else None

    def _snapshot_signature(self, course_path: str) -> List[Tuple[str, int, int]]:
        snapshot: List[Tuple[str, int, int]] = []
        for root, dirnames, filenames in os.walk(course_path):
            dirnames[:] = [
                name
                for name in dirnames
                if not self._is_system_scan_entry(name)
            ]
            for filename in filenames:
                if self._is_system_scan_entry(filename):
                    continue
                file_path = os.path.join(root, filename)
                try:
                    stats = os.stat(file_path)
                except FileNotFoundError:
                    continue
                relative_path = os.path.relpath(file_path, course_path).replace(os.sep, "/")
                snapshot.append((relative_path, int(stats.st_size), int(stats.st_mtime_ns)))
        snapshot.sort(key=lambda item: self._natural_key(item[0]))
        return snapshot

    @staticmethod
    def _coerce_signature(signature: Any) -> Tuple[Tuple[str, int, int], ...]:
        if not isinstance(signature, (list, tuple)):
            return ()

        normalized = []
        for item in signature:
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                return ()
            path, size, mtime = item
            try:
                normalized.append((str(path), int(size), int(mtime)))
            except (TypeError, ValueError):
                return ()
        return tuple(normalized)

    def _delete_if_empty_recursive(self, course_path: str) -> None:
        for root, _, files in os.walk(course_path, topdown=False):
            if files:
                return
            if os.path.isdir(root):
                try:
                    os.rmdir(root)
                except OSError:
                    return

    @staticmethod
    def _is_incomplete(filename: str) -> bool:
        lower = filename.lower()
        return any(lower.endswith(suffix) for suffix in CourseOrganizer.INCOMPLETE_SUFFIXES)

    @classmethod
    def _has_incomplete_file(cls, course_path: str) -> bool:
        for root, dirnames, filenames in os.walk(course_path):
            dirnames[:] = [
                name
                for name in dirnames
                if not cls._is_system_scan_entry(name)
            ]
            for filename in filenames:
                if cls._is_incomplete(filename):
                    return True
        return False

    @classmethod
    def _safe_name(cls, value: str) -> str:
        normalized = _INVALID_NAME_RE.sub("_", value).strip()
        if normalized in {"", ".", ".."}:
            normalized = "Course"
        return normalized[:160]

    @staticmethod
    def _lower_extension(filename: str) -> str:
        return os.path.splitext(filename)[1].lower()

    @classmethod
    def _extract_leading_episode(cls, file_path: str) -> Optional[int]:
        span = cls._extract_leading_episode_span(file_path)
        if span is None:
            return None
        return span[0]

    @classmethod
    def _extract_leading_episode_span(cls, file_path: str) -> Optional[Tuple[int, int]]:
        stem = os.path.splitext(os.path.basename(file_path))[0].strip()

        def _parse_range(start_text: str, end_text: str) -> Optional[Tuple[int, int]]:
            try:
                start = int(start_text)
                end = int(end_text)
            except (TypeError, ValueError):
                return None
            if start <= 0:
                return None
            if end <= start:
                return None
            if end - start + 1 > 1000:
                return None
            return start, end

        for pattern in (_LEADING_CN_RANGE_RE, _LEADING_EN_RANGE_RE, _LEADING_BARE_RANGE_RE):
            match = pattern.match(stem)
            if match:
                start_text = match.group("start")
                end_text = match.group("end")
                if (
                    pattern is _LEADING_BARE_RANGE_RE
                    and len(start_text) == 4
                    and len(end_text) == 4
                ):
                    return None
                parsed = _parse_range(start_text, end_text)
                if parsed is not None:
                    return parsed
                return None

        if _LEADING_RANGE_CANDIDATE_RE.match(stem):
            return None

        match = _LEADING_EPISODE_RE.match(stem)
        if not match:
            return None

        try:
            value = int(match.group(1))
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None

        return value, value

    @staticmethod
    def _format_episode_token(season: int, start: int, end: int) -> str:
        token = f"S{season:02d}E{start:03d}"
        if end > start:
            token += f"-E{end:03d}"
        return token

    @classmethod
    def _collect_existing_episodes(
        cls, season_root: str, safe_course_name: str, season: int
    ) -> List[int]:
        if not os.path.isdir(season_root):
            return []

        episode_pattern = re.compile(
            rf"^{re.escape(safe_course_name)} - S{season:02d}E([0-9]+)(?:-E([0-9]+))?(?:_[0-9]+)?$"
        )
        episodes: List[int] = []
        for filename in os.listdir(season_root):
            episode_path = os.path.join(season_root, filename)
            if not os.path.isfile(episode_path):
                continue
            stem, extension = os.path.splitext(filename)
            if extension.lower() not in cls.MEDIA_EXTENSIONS:
                continue
            match = episode_pattern.fullmatch(stem)
            if match:
                try:
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) is not None else start
                    if start <= 0 or end < start or (end - start + 1) > 1000:
                        continue
                    episodes.extend(range(start, end + 1))
                except (TypeError, ValueError):
                    continue

        return episodes

    @classmethod
    def _next_episode_number(cls, season_root: str, safe_course_name: str, season: int) -> int:
        if not os.path.isdir(season_root):
            return 1

        return max(cls._collect_existing_episodes(season_root, safe_course_name, season), default=0) + 1

    @classmethod
    def _state_key(cls, course_name: str) -> str:
        return f"courseorganizer_state_{course_name}"

    @staticmethod
    def _reserve_path(path: str) -> str:
        if not os.path.exists(path):
            return path

        base, ext = os.path.splitext(path)
        index = 1
        while True:
            candidate = f"{base}_{index}{ext}"
            if not os.path.exists(candidate):
                return candidate
            index += 1

    @staticmethod
    def _safe_relative_path(root: str, path: str) -> Optional[str]:
        root_abs = os.path.abspath(root)
        candidate_abs = os.path.abspath(path)
        relative = os.path.relpath(candidate_abs, root_abs)
        normalized = os.path.normpath(relative)
        if normalized in {"", "."}:
            return None
        if normalized == ".." or normalized.startswith(f"..{os.sep}"):
            return None
        return normalized

    @classmethod
    def _open_nofollow_dir_chain(
        cls,
        base_dir_fd: int,
        relative_path: str,
        create: bool = False,
        created: Optional[List[Tuple[str, Tuple[int, int]]]] = None,
    ) -> int:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        dir_chain_flags = no_follow | os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            dir_chain_flags |= os.O_DIRECTORY
        flags = dir_chain_flags
        current_fd = os.dup(base_dir_fd)
        components: List[str] = []
        try:
            for component in (part for part in relative_path.split(os.sep) if part and part != "."):
                if component == "..":
                    raise ValueError("directory path escapes bound root")
                components.append(component)
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(component, 0o755, dir_fd=current_fd)
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                    created_path = os.sep.join(components)
                    created_stat = os.fstat(next_fd)
                    if created is not None:
                        created.append(
                            (
                                created_path,
                                (int(created_stat.st_dev), int(created_stat.st_ino)),
                            )
                        )
                if current_fd != base_dir_fd:
                    os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except Exception:
            if current_fd is not None:
                os.close(current_fd)
            raise

    @staticmethod
    def _entry_lstat(parent_fd: Optional[int], name: str) -> Optional[os.stat_result]:
        if parent_fd is None:
            return None
        try:
            return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except (OSError, TypeError, NotImplementedError, ValueError):
            return None

    @classmethod
    def _regular_entry_stat(cls, parent_fd: Optional[int], name: str) -> Optional[os.stat_result]:
        current = cls._entry_lstat(parent_fd, name)
        if current is None or not stat.S_ISREG(current.st_mode):
            return None
        return current

    @classmethod
    def _unlink_if_identity(
        cls,
        parent_fd: Optional[int],
        name: str,
        expected: Optional[Tuple[int, int]],
    ) -> bool:
        current = cls._entry_lstat(parent_fd, name)
        if current is None or expected is None or (current.st_dev, current.st_ino) != expected:
            return False
        try:
            os.unlink(name, dir_fd=parent_fd)
        except (OSError, TypeError, NotImplementedError, ValueError):
            return False
        return True

    @staticmethod
    def _fsync_dir(directory_fd: Optional[int]) -> None:
        if directory_fd is None:
            return
        try:
            os.fsync(directory_fd)
        except (OSError, TypeError, NotImplementedError, ValueError):
            pass

    @staticmethod
    def _rename_noreplace(
        source_parent_fd: Optional[int],
        source_name: str,
        target_parent_fd: Optional[int],
        target_name: str,
    ) -> bool:
        """Use a native atomic no-replace rename; unsupported means no-op."""
        if source_parent_fd is None or target_parent_fd is None:
            return False
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            source = os.fsencode(source_name)
            target = os.fsencode(target_name)
            if sys.platform == "darwin":
                renameatx_np = getattr(libc, "renameatx_np", None)
                if renameatx_np is None:
                    return False
                renameatx_np.argtypes = [
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_uint,
                ]
                renameatx_np.restype = ctypes.c_int
                return (
                    renameatx_np(
                        source_parent_fd,
                        source,
                        target_parent_fd,
                        target,
                        4,
                    )
                    == 0
                )
            if sys.platform != "linux":
                return False
            renameat2 = getattr(libc, "renameat2", None)
            if renameat2 is not None:
                renameat2.argtypes = [
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_uint,
                ]
                renameat2.restype = ctypes.c_int
                if renameat2(
                    source_parent_fd,
                    source,
                    target_parent_fd,
                    target,
                    1,
                ) == 0:
                    return True
                if ctypes.get_errno() != errno.ENOSYS:
                    return False

            syscall_numbers = {
                "x86_64": 316,
                "amd64": 316,
                "aarch64": 276,
                "arm64": 276,
                "i386": 353,
                "i686": 353,
                "armv7l": 382,
                "ppc64": 357,
                "ppc64le": 357,
                "s390x": 347,
                "riscv64": 276,
            }
            machine = os.uname().machine
            syscall_number = syscall_numbers.get(machine)
            syscall = getattr(libc, "syscall", None)
            if syscall_number is None or syscall is None:
                return False
            syscall.restype = ctypes.c_long
            return (
                syscall(
                    syscall_number,
                    source_parent_fd,
                    source,
                    target_parent_fd,
                    target,
                    1,
                )
                == 0
            )
        except (AttributeError, OSError, TypeError, ValueError, UnicodeError):
            return False

    def _open_bound_root(self, root: str) -> Optional[Dict[str, Any]]:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        if not no_follow or not directory_flag or not root:
            return None
        flags = no_follow | directory_flag | os.O_RDONLY
        root_abs = os.path.abspath(str(root))
        base_fd = root_fd = parent_fd = None
        result = None
        try:
            if root_abs == os.path.abspath(os.sep):
                root_fd = os.open(os.sep, flags)
                root_name = ""
            else:
                base_fd = os.open(os.sep, flags)
                relative_root = root_abs.lstrip(os.sep)
                parent_relative = os.path.dirname(relative_root)
                root_name = os.path.basename(relative_root)
                parent_fd = self._open_nofollow_dir_chain(base_fd, parent_relative)
                root_fd = os.open(root_name, flags, dir_fd=parent_fd)
            root_stat = os.fstat(root_fd)
            if not stat.S_ISDIR(root_stat.st_mode):
                return None
            if root_name:
                parent_stat = self._entry_lstat(parent_fd, root_name)
                if (
                    parent_stat is None
                    or not stat.S_ISDIR(parent_stat.st_mode)
                    or (parent_stat.st_dev, parent_stat.st_ino)
                    != (root_stat.st_dev, root_stat.st_ino)
                ):
                    return None
            result = {
                "path": root_abs,
                "fd": root_fd,
                "identity": (root_stat.st_dev, root_stat.st_ino),
                "parent_fd": parent_fd,
                "name": root_name,
            }
            return result
        except (OSError, TypeError, NotImplementedError, ValueError):
            return None
        finally:
            if result is None:
                for fd in (parent_fd, root_fd, base_fd):
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
            elif base_fd is not None:
                try:
                    os.close(base_fd)
                except OSError:
                    pass

    def _create_move_context(
        self,
        source_root: str,
        target_root: str,
        expected_manifest: Optional[Any] = None,
        expected_directories: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        source = self._open_bound_root(source_root)
        target = self._open_bound_root(target_root)
        if source is None or target is None:
            for bound in (source, target):
                if bound is not None:
                    for fd in (bound["parent_fd"], bound["fd"]):
                        if fd is not None:
                            try:
                                os.close(fd)
                            except OSError:
                                pass
            return None
        stage_fd = stage_name = None
        context = None
        try:
            base = f".courseorganizer-stage.{os.getpid()}.{time.time_ns()}"
            for suffix in range(1000):
                candidate = base if suffix == 0 else f"{base}.{suffix}"
                try:
                    os.mkdir(candidate, 0o700, dir_fd=source["fd"])
                    stage_name = candidate
                    stage_fd = os.open(
                        candidate,
                        getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY,
                        dir_fd=source["fd"],
                    )
                    break
                except FileExistsError:
                    continue
            if stage_fd is None or stage_name is None:
                return None
            stage_stat = os.fstat(stage_fd)
            context = {
                "source_root": source,
                "target_root": target,
                "stage_fd": stage_fd,
                "stage_name": stage_name,
                "stage_identity": (stage_stat.st_dev, stage_stat.st_ino),
                "counter": 0,
                "staged": [],
                "published": [],
                "created_target_dirs": [],
                "open_fds": [],
                "expected_source_manifest": self._coerce_source_manifest(expected_manifest)
                if expected_manifest is not None
                else None,
                "expected_source_directories": self._coerce_source_directory_manifest(
                    expected_directories
                )
                if expected_directories is not None
                else None,
                "expected_remaining_source_manifest": None,
                "expected_remaining_source_directories": None,
            }
            return context
        except (OSError, TypeError, NotImplementedError, ValueError):
            return None
        finally:
            if context is None:
                if stage_fd is not None:
                    try:
                        os.close(stage_fd)
                    except OSError:
                        pass
                if stage_name is not None:
                    self._unlink_if_identity(source["fd"], stage_name, None)
                    try:
                        os.rmdir(stage_name, dir_fd=source["fd"])
                    except OSError:
                        pass
                for bound in (source, target):
                    for fd in (bound["parent_fd"], bound["fd"]):
                        if fd is not None:
                            try:
                                os.close(fd)
                            except OSError:
                                pass

    @classmethod
    def _bound_root_is_current(cls, bound: Dict[str, Any]) -> bool:
        try:
            current = os.fstat(bound["fd"])
        except OSError:
            return False
        if (
            not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != bound["identity"]
        ):
            return False
        if bound["parent_fd"] is None:
            return True
        entry = cls._entry_lstat(bound["parent_fd"], bound["name"])
        return bool(
            entry is not None
            and stat.S_ISDIR(entry.st_mode)
            and (entry.st_dev, entry.st_ino) == bound["identity"]
        )

    @classmethod
    def _move_context_is_current(cls, context: Dict[str, Any]) -> bool:
        return cls._bound_root_is_current(context["source_root"]) and cls._bound_root_is_current(
            context["target_root"]
        )

    def _capture_move_identity(
        self,
        context: Dict[str, Any],
        source: str,
    ) -> Optional[Dict[str, Any]]:
        if not self._move_context_is_current(context):
            return None
        root = context["source_root"]
        relative = self._safe_relative_path(root["path"], source)
        if relative is None:
            return None
        parent_name, source_name = os.path.split(relative)
        parent_fd = None
        source_fd = None
        try:
            parent_fd = self._open_nofollow_dir_chain(root["fd"], parent_name)
            source_fd = os.open(
                source_name,
                getattr(os, "O_NOFOLLOW", 0)
                | os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_fd,
            )
            source_stat = os.fstat(source_fd)
            entry = self._regular_entry_stat(parent_fd, source_name)
            identity = (source_stat.st_dev, source_stat.st_ino)
            if entry is None or not self._file_stat_matches(source_stat, entry):
                return None
            after = os.fstat(source_fd)
            if not self._file_stat_matches(after, source_stat):
                return None
            return {
                "relative": relative,
                "parent": parent_name,
                "name": source_name,
                "identity": identity,
                "stat": after,
            }
        except (OSError, TypeError, NotImplementedError, ValueError):
            return None
        finally:
            for fd in (source_fd, parent_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def _restore_published_item(self, item: Dict[str, Any]) -> bool:
        source_parent_fd = item.get("source_parent_fd")
        original_fd = item.get("original_fd")
        original_stat = item.get("original_stat")
        if (
            source_parent_fd is None
            or not isinstance(original_fd, int)
            or original_stat is None
        ):
            return False

        current_source = self._entry_lstat(source_parent_fd, item["source_name"])
        if current_source is not None:
            if (current_source.st_dev, current_source.st_ino) != item["identity"]:
                return False
            if isinstance(original_fd, int) and original_stat is not None:
                try:
                    if not self._file_stat_matches_without_ctime(
                        os.fstat(original_fd), original_stat
                    ):
                        return False
                except (OSError, TypeError, ValueError):
                    return False
            return True

        try:
            held_stat = os.fstat(original_fd)
            if (
                not stat.S_ISREG(held_stat.st_mode)
                or (held_stat.st_dev, held_stat.st_ino) != item["identity"]
                or not self._file_stat_matches_without_ctime(held_stat, original_stat)
            ):
                return False
            source_stat = item.get("stat") or original_stat
            source_fd = os.open(
                item["source_name"],
                getattr(os, "O_NOFOLLOW", 0)
                | os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_BINARY", 0),
                stat.S_IMODE(getattr(source_stat, "st_mode", 0o600)),
                dir_fd=source_parent_fd,
            )
        except (OSError, TypeError, NotImplementedError, ValueError):
            return False

        source_identity = None
        restored = False
        try:
            source_stat = os.fstat(source_fd)
            source_identity = (source_stat.st_dev, source_stat.st_ino)
            if not stat.S_ISREG(source_stat.st_mode):
                return False
            os.lseek(original_fd, 0, os.SEEK_SET)
            remaining = original_stat.st_size
            while remaining:
                chunk = os.read(original_fd, min(1024 * 1024, remaining))
                if not chunk:
                    return False
                remaining -= len(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(source_fd, view)
                    if written <= 0:
                        return False
                    view = view[written:]
            if os.read(original_fd, 1):
                return False
            if not self._file_stat_matches_without_ctime(
                os.fstat(original_fd), original_stat
            ):
                return False
            os.fchmod(source_fd, stat.S_IMODE(getattr(item.get("stat"), "st_mode", 0o600)))
            source_times = item.get("stat")
            if source_times is not None:
                os.utime(
                    source_fd,
                    ns=(source_times.st_atime_ns, source_times.st_mtime_ns),
                )
            os.fsync(source_fd)
            current_source = self._entry_lstat(source_parent_fd, item["source_name"])
            if (
                current_source is None
                or (current_source.st_dev, current_source.st_ino) != source_identity
            ):
                return False
            self._fsync_dir(source_parent_fd)
            restored = True
            return True
        except (OSError, TypeError, NotImplementedError, ValueError):
            return False
        finally:
            try:
                os.close(source_fd)
            except OSError:
                pass
            if not restored:
                self._unlink_if_identity(source_parent_fd, item["source_name"], source_identity)

    def _restore_staged_item(self, context: Dict[str, Any], item: Dict[str, Any]) -> bool:
        source_parent_fd = item.get("source_parent_fd")
        stage_fd = context["stage_fd"]
        original_fd = item.get("original_fd")
        original_stat = item.get("original_stat")
        identity = item.get("identity")
        if (
            source_parent_fd is None
            or stage_fd is None
            or not isinstance(original_fd, int)
            or original_stat is None
            or not isinstance(identity, tuple)
            or len(identity) != 2
        ):
            return False
        try:
            held_original = os.fstat(original_fd)
            if (
                not stat.S_ISREG(held_original.st_mode)
                or (held_original.st_dev, held_original.st_ino) != identity
                or not self._file_stat_matches_without_ctime(held_original, original_stat)
            ):
                return False
            stage_names = os.listdir(stage_fd)
        except (OSError, TypeError, NotImplementedError, ValueError):
            return False

        original_entries = []
        for candidate_name in stage_names:
            candidate = self._regular_entry_stat(stage_fd, candidate_name)
            if candidate is not None and (candidate.st_dev, candidate.st_ino) == identity:
                original_entries.append((candidate_name, candidate))
        if len(original_entries) > 1:
            return False
        if not original_entries:
            return self._restore_published_item(item)

        candidate_name, candidate_stat = original_entries[0]
        current_source = self._entry_lstat(source_parent_fd, item["source_name"])
        if current_source is not None:
            if (current_source.st_dev, current_source.st_ino) == identity:
                restored = self._unlink_if_identity(
                    stage_fd, candidate_name, identity
                )
                if restored:
                    self._fsync_dir(source_parent_fd)
                    self._fsync_dir(stage_fd)
                return restored
            return False
        candidate_fd = None
        try:
            candidate_fd = os.open(
                candidate_name,
                getattr(os, "O_NOFOLLOW", 0)
                | os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=stage_fd,
            )
            held_candidate = os.fstat(candidate_fd)
            current_candidate = self._regular_entry_stat(stage_fd, candidate_name)
            if (
                current_candidate is None
                or (held_candidate.st_dev, held_candidate.st_ino) != identity
                or (current_candidate.st_dev, current_candidate.st_ino) != identity
                or not self._file_stat_matches_without_ctime(held_candidate, candidate_stat)
            ):
                return False
            _ORIGINAL_LINK(
                candidate_name,
                item["source_name"],
                src_dir_fd=stage_fd,
                dst_dir_fd=source_parent_fd,
                follow_symlinks=False,
            )
            linked_source = self._entry_lstat(source_parent_fd, item["source_name"])
            if linked_source is None or (linked_source.st_dev, linked_source.st_ino) != identity:
                return False
            restored = self._unlink_if_identity(stage_fd, candidate_name, identity)
            if restored:
                self._fsync_dir(source_parent_fd)
                self._fsync_dir(stage_fd)
            return restored
        except FileExistsError:
            return False
        except (OSError, TypeError, NotImplementedError, ValueError):
            return False
        finally:
            if candidate_fd is not None:
                try:
                    os.close(candidate_fd)
                except OSError:
                    pass

    def _stage_move_source(
        self,
        context: Dict[str, Any],
        source: str,
        captured: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not self._move_context_is_current(context):
            return None
        root = context["source_root"]
        parent_fd = None
        stage_name = None
        original_fd = None
        original_stat = None
        original_identity = None
        staged_entry = None
        renamed = False
        try:
            parent_fd = self._open_nofollow_dir_chain(root["fd"], captured["parent"])
            context["open_fds"].append(parent_fd)
            current = self._regular_entry_stat(parent_fd, captured["name"])
            if current is None or not self._file_stat_matches(current, captured["stat"]):
                return None
            original_fd = os.open(
                captured["name"],
                getattr(os, "O_NOFOLLOW", 0)
                | os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_fd,
            )
            original_stat = os.fstat(original_fd)
            original_identity = (original_stat.st_dev, original_stat.st_ino)
            current = self._regular_entry_stat(parent_fd, captured["name"])
            if (
                not stat.S_ISREG(original_stat.st_mode)
                or original_identity != captured["identity"]
                or not self._file_stat_matches(original_stat, captured["stat"])
                or current is None
                or not self._file_stat_matches(current, original_stat)
            ):
                return None
            context["counter"] += 1
            stage_name = f"{context['counter']:08x}-{captured['name']}"
            if self._entry_lstat(context["stage_fd"], stage_name) is not None:
                return None
            os.rename(
                captured["name"],
                stage_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=context["stage_fd"],
            )
            renamed = True
            self._fsync_dir(parent_fd)
            self._fsync_dir(context["stage_fd"])
            staged_entry = self._entry_lstat(context["stage_fd"], stage_name)
            staged_fd_stat = os.fstat(original_fd)
            staged = (
                staged_entry
                if staged_entry is not None
                and stat.S_ISREG(staged_entry.st_mode)
                and original_identity == (staged_fd_stat.st_dev, staged_fd_stat.st_ino)
                and self._file_stat_matches(staged_entry, staged_fd_stat)
                else None
            )
            if staged is None:
                item = {
                    "source_parent_fd": parent_fd,
                    "source_name": captured["name"],
                    "stage_name": stage_name,
                    "identity": captured["identity"],
                    "original_fd": original_fd,
                    "original_stat": original_stat,
                    "stat": captured["stat"],
                    "stage_identity": (
                        (staged_entry.st_dev, staged_entry.st_ino)
                        if staged_entry is not None
                        else None
                    ),
                }
                self._restore_staged_item(context, item)
                return None
            item = {
                "source_parent_fd": parent_fd,
                "source_name": captured["name"],
                "stage_name": stage_name,
                "identity": captured["identity"],
                "original_fd": original_fd,
                "original_stat": original_stat,
                "stage_identity": (staged.st_dev, staged.st_ino),
                "stat": captured["stat"],
                "staged_stat": staged,
                "source": source,
            }
            context["staged"].append(item)
            original_fd = None
            return item
        except (OSError, TypeError, NotImplementedError, ValueError):
            if renamed and parent_fd is not None and stage_name is not None:
                current = self._entry_lstat(context["stage_fd"], stage_name)
                item = {
                    "source_parent_fd": parent_fd,
                    "source_name": captured["name"],
                    "stage_name": stage_name,
                    "identity": original_identity or captured["identity"],
                    "original_fd": original_fd,
                    "original_stat": original_stat,
                    "stat": captured["stat"],
                    "stage_identity": (
                        (current.st_dev, current.st_ino) if current is not None else None
                    ),
                }
                try:
                    self._restore_staged_item(context, item)
                except (OSError, TypeError, NotImplementedError, ValueError, KeyError):
                    pass
            return None
        finally:
            if original_fd is not None:
                try:
                    os.close(original_fd)
                except OSError:
                    pass

    def _publish_staged_move(
        self,
        context: Dict[str, Any],
        item: Dict[str, Any],
        target: str,
    ) -> bool:
        if not self._move_context_is_current(context):
            return False
        root = context["target_root"]
        relative = self._safe_relative_path(root["path"], target)
        if relative is None:
            return False
        target_parent, target_name = os.path.split(relative)
        target_parent_fd = temp_fd = None
        temp_name = None
        published_identity = None
        published_fd = None
        source_fd = None
        try:
            target_parent_fd = self._open_nofollow_dir_chain(
                root["fd"],
                target_parent,
                create=True,
                created=context["created_target_dirs"],
            )
            context["open_fds"].append(target_parent_fd)
            source_stat = self._regular_entry_stat(context["stage_fd"], item["stage_name"])
            staged_stat = item.get("staged_stat", item["stat"])
            if source_stat is None or not self._file_stat_matches(source_stat, staged_stat):
                return False
            source_fd = os.open(
                item["stage_name"],
                getattr(os, "O_NOFOLLOW", 0)
                | os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=context["stage_fd"],
            )
            source_stat = os.fstat(source_fd)
            if not self._file_stat_matches(source_stat, staged_stat):
                return False

            same_filesystem = (
                os.fstat(target_parent_fd).st_dev == source_stat.st_dev
                and context.get("expected_source_manifest") is None
            )
            if same_filesystem:
                try:
                    os.link(
                        item["stage_name"],
                        target_name,
                        src_dir_fd=context["stage_fd"],
                        dst_dir_fd=target_parent_fd,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    if exc.errno != errno.EXDEV:
                        return False
                else:
                    published_identity = item["identity"]
                    target_stat = self._regular_entry_stat(target_parent_fd, target_name)
                    if target_stat is None or (target_stat.st_dev, target_stat.st_ino) != published_identity:
                        self._unlink_if_identity(target_parent_fd, target_name, published_identity)
                        return False
                    published_fd = os.open(
                        target_name,
                        getattr(os, "O_NOFOLLOW", 0)
                        | os.O_RDONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NONBLOCK", 0),
                        dir_fd=target_parent_fd,
                    )
                    published_fd_stat = os.fstat(published_fd)
                    published_stat = self._regular_entry_stat(target_parent_fd, target_name)
                    if (
                        published_stat is None
                        or not self._file_stat_matches(published_stat, published_fd_stat)
                    ):
                        self._unlink_if_identity(target_parent_fd, target_name, published_identity)
                        return False
                    if not self._file_stat_matches_without_ctime(
                        os.fstat(source_fd), staged_stat
                    ):
                        self._unlink_if_identity(target_parent_fd, target_name, published_identity)
                        return False
                    self._fsync_dir(target_parent_fd)
                    publication = {
                        "parent_fd": target_parent_fd,
                        "name": target_name,
                        "identity": published_identity,
                        "stage_identity": item["stage_identity"],
                        "shared_stage": True,
                        "fd": published_fd,
                        "stat": published_stat,
                        "fd_stat": published_fd_stat,
                    }
                    context["published"].append(publication)
                    item["published"] = publication
                    published_fd = None
                    return True

            mode = stat.S_IMODE(source_stat.st_mode) & ~(stat.S_ISUID | stat.S_ISGID)
            for suffix in range(1000):
                candidate = f".{target_name}.tmp.{context['counter']}.{suffix}"
                try:
                    temp_fd = os.open(
                        candidate,
                        getattr(os, "O_NOFOLLOW", 0)
                        | os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_BINARY", 0),
                        mode,
                        dir_fd=target_parent_fd,
                    )
                    temp_name = candidate
                    break
                except FileExistsError:
                    continue
            if temp_fd is None or temp_name is None:
                return False
            temp_stat = os.fstat(temp_fd)
            temp_identity = (temp_stat.st_dev, temp_stat.st_ino)
            remaining = source_stat.st_size
            while remaining:
                chunk = os.read(source_fd, min(1024 * 1024, remaining))
                if not chunk:
                    return False
                remaining -= len(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(temp_fd, view)
                    if written <= 0:
                        return False
                    view = view[written:]
            if os.read(source_fd, 1):
                return False
            if not self._file_stat_matches(os.fstat(source_fd), staged_stat):
                return False
            os.fchmod(temp_fd, mode)
            os.utime(
                temp_name,
                ns=(item["stat"].st_atime_ns, item["stat"].st_mtime_ns),
                dir_fd=target_parent_fd,
                follow_symlinks=False,
            )
            os.fsync(temp_fd)
            if (
                (current := self._regular_entry_stat(target_parent_fd, temp_name)) is None
                or (current.st_dev, current.st_ino) != temp_identity
            ):
                return False
            os.link(
                temp_name,
                target_name,
                src_dir_fd=target_parent_fd,
                dst_dir_fd=target_parent_fd,
                follow_symlinks=False,
            )
            published_identity = temp_identity
            target_stat = self._regular_entry_stat(target_parent_fd, target_name)
            if target_stat is None or (target_stat.st_dev, target_stat.st_ino) != published_identity:
                self._unlink_if_identity(target_parent_fd, target_name, published_identity)
                return False
            if not self._unlink_if_identity(target_parent_fd, temp_name, temp_identity):
                self._unlink_if_identity(target_parent_fd, target_name, published_identity)
                return False
            temp_name = None
            published_fd = os.open(
                target_name,
                getattr(os, "O_NOFOLLOW", 0)
                | os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=target_parent_fd,
            )
            published_fd_stat = os.fstat(published_fd)
            published_stat = self._regular_entry_stat(target_parent_fd, target_name)
            if (
                published_stat is None
                or not self._file_stat_matches(published_stat, published_fd_stat)
            ):
                self._unlink_if_identity(target_parent_fd, target_name, published_identity)
                return False
            self._fsync_dir(target_parent_fd)
            publication = {
                "parent_fd": target_parent_fd,
                "name": target_name,
                "identity": published_identity,
                "stage_identity": item["stage_identity"],
                "shared_stage": False,
                "fd": published_fd,
                "stat": published_stat,
                "fd_stat": published_fd_stat,
            }
            context["published"].append(publication)
            item["published"] = publication
            published_fd = None
            return True
        except (OSError, TypeError, NotImplementedError, ValueError):
            if published_identity is not None:
                self._unlink_if_identity(target_parent_fd, target_name, published_identity)
            return False
        finally:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
            if temp_name is not None:
                self._unlink_if_identity(target_parent_fd, temp_name, locals().get("temp_identity"))
            for fd in (source_fd, published_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def _rollback_move_context(self, context: Dict[str, Any]) -> None:
        cleanup = [
            published
            for published in reversed(context.get("published", []))
            if self._publication_matches(published)
        ]
        for item in reversed(context.get("staged", [])):
            self._restore_staged_item(context, item)
        for published in cleanup:
            self._unlink_if_identity(
                published["parent_fd"], published["name"], published["identity"]
            )
        self._remove_created_target_dirs(context)
        context["rolled_back"] = True
        stage_entry = self._entry_lstat(context["source_root"]["fd"], context["stage_name"])
        if (
            stage_entry is not None
            and (stage_entry.st_dev, stage_entry.st_ino) == context["stage_identity"]
        ):
            try:
                os.rmdir(context["stage_name"], dir_fd=context["source_root"]["fd"])
            except OSError:
                pass

    def _remove_created_target_dirs(self, context: Dict[str, Any]) -> None:
        root = context.get("target_root")
        raw_created = context.get("created_target_dirs", ())
        if not isinstance(raw_created, (list, tuple)):
            return
        created = list(raw_created)
        flags = (
            getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
        )
        created_by_path: Dict[str, Tuple[int, int]] = {}
        for item in created:
            if not isinstance(item, tuple) or len(item) != 2:
                return
            relative, identity = item
            normalized = relative if isinstance(relative, str) else ""
            components = normalized.split("/") if normalized else []
            if (
                not normalized
                or normalized.startswith("/")
                or normalized.endswith("/")
                or "\\" in normalized
                or "\x00" in normalized
                or any(component in {"", ".", ".."} for component in components)
                or os.path.normpath(normalized) != normalized
                or not isinstance(identity, tuple)
                or len(identity) != 2
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in identity
                )
                or normalized in created_by_path
            ):
                return
            created_by_path[normalized] = identity

        if not root:
            context["created_target_dirs"] = []
            return
        context["created_target_dirs"] = []

        roots: List[str] = []
        for relative in sorted(
            created_by_path, key=lambda value: (value.count("/"), value)
        ):
            if not any(
                relative == candidate or relative.startswith(f"{candidate}/")
                for candidate in roots
            ):
                roots.append(relative)

        def subtree_matches(
            directory_fd: int,
            identity: Tuple[int, int],
            expected_directories: Tuple[Tuple[str, int, int], ...],
        ) -> bool:
            try:
                current = os.fstat(directory_fd)
                if (
                    not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev, current.st_ino) != identity
                ):
                    return False
                tree = self._scan_manifest_dir(directory_fd)
                if tree is None:
                    return False
                files, directories = tree
                directories.sort(key=lambda item: item[0])
                return not files and tuple(directories) == expected_directories
            except (OSError, TypeError, NotImplementedError, ValueError):
                return False

        for relative in roots:
            identity = created_by_path[relative]
            expected_descendants = tuple(
                sorted(
                    (
                        candidate[len(relative) + 1 :],
                        descendant_identity[0],
                        descendant_identity[1],
                    )
                    for candidate, descendant_identity in created_by_path.items()
                    if candidate.startswith(f"{relative}/")
                )
            )
            parent_relative, name = os.path.split(relative)
            parent_fd = child_fd = quarantine_fd = None
            quarantine_name = None
            try:
                parent_fd = self._open_nofollow_dir_chain(root["fd"], parent_relative)
                entry = self._entry_lstat(parent_fd, name)
                if (
                    entry is None
                    or not stat.S_ISDIR(entry.st_mode)
                    or (entry.st_dev, entry.st_ino) != identity
                ):
                    continue
                child_fd = os.open(name, flags, dir_fd=parent_fd)
                if not subtree_matches(child_fd, identity, expected_descendants):
                    continue
                for _ in range(100):
                    candidate = f".courseorganizer-rollback-{uuid.uuid4().hex}"
                    if self._rename_noreplace(parent_fd, name, parent_fd, candidate):
                        quarantine_name = candidate
                        break
                if quarantine_name is None:
                    continue
                quarantine = self._entry_lstat(parent_fd, quarantine_name)
                if (
                    quarantine is None
                    or not stat.S_ISDIR(quarantine.st_mode)
                    or (quarantine.st_dev, quarantine.st_ino) != identity
                ):
                    self._restore_quarantined_dir(parent_fd, name, quarantine_name, identity)
                    continue
                quarantine_fd = os.open(quarantine_name, flags, dir_fd=parent_fd)
                if not subtree_matches(quarantine_fd, identity, expected_descendants):
                    self._restore_quarantined_dir(parent_fd, name, quarantine_name, identity)
                    continue
                # Keep one identity-checked quarantine rather than doing a
                # final name-based rmdir that could target a replacement.
                self._fsync_dir(parent_fd)
                if not subtree_matches(quarantine_fd, identity, expected_descendants):
                    self._restore_quarantined_dir(parent_fd, name, quarantine_name, identity)
                    continue
                quarantine = self._entry_lstat(parent_fd, quarantine_name)
                if (
                    quarantine is None
                    or not stat.S_ISDIR(quarantine.st_mode)
                    or (quarantine.st_dev, quarantine.st_ino) != identity
                ):
                    self._restore_quarantined_dir(parent_fd, name, quarantine_name, identity)
                    continue
            except (OSError, TypeError, NotImplementedError, ValueError):
                if parent_fd is not None and quarantine_name is not None:
                    self._restore_quarantined_dir(parent_fd, name, quarantine_name, identity)
                continue
            finally:
                for fd in (quarantine_fd, child_fd, parent_fd):
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass

    def _restore_quarantined_dir(
        self,
        parent_fd: Optional[int],
        name: str,
        quarantine_name: str,
        identity: Tuple[int, int],
    ) -> bool:
        quarantine = self._entry_lstat(parent_fd, quarantine_name)
        if (
            quarantine is None
            or not stat.S_ISDIR(quarantine.st_mode)
            or (quarantine.st_dev, quarantine.st_ino) != identity
            or self._entry_lstat(parent_fd, name) is not None
        ):
            return False
        return self._rename_noreplace(parent_fd, quarantine_name, parent_fd, name)

    def _move_context_remaining_matches(self, context: Dict[str, Any]) -> bool:
        expected_files = context.get("expected_remaining_source_manifest")
        expected_dirs = context.get("expected_remaining_source_directories")
        if expected_files is None or expected_dirs is None:
            return True
        if not self._move_context_is_current(context):
            return False
        current_tree = self._scan_manifest_dir(
            context["source_root"]["fd"],
            excluded_root=(context["stage_name"], context["stage_identity"]),
        )
        if current_tree is None:
            return False
        current_files, current_dirs = current_tree
        current_files.sort(key=lambda item: item[0])
        current_dirs.sort(key=lambda item: item[0])
        return (
            tuple(current_files) == tuple(expected_files)
            and tuple(current_dirs) == tuple(expected_dirs)
        )

    def _publication_matches(
        self, publication: Dict[str, Any], *, include_ctime: bool = True
    ) -> bool:
        stat_matches = (
            self._file_stat_matches
            if include_ctime
            else self._file_stat_matches_without_ctime
        )
        try:
            parent_fd = publication.get("parent_fd")
            published_fd = publication.get("fd")
            expected_identity = publication.get("identity")
            expected_stat = publication.get("stat")
            expected_fd_stat = publication.get("fd_stat")
            if (
                parent_fd is None
                or not isinstance(published_fd, int)
                or expected_identity is None
                or expected_stat is None
                or expected_fd_stat is None
            ):
                return False
            path_stat = self._regular_entry_stat(parent_fd, publication["name"])
            held_stat = os.fstat(published_fd)
            return bool(
                path_stat is not None
                and (path_stat.st_dev, path_stat.st_ino) == expected_identity
                and (held_stat.st_dev, held_stat.st_ino) == expected_identity
                and stat_matches(path_stat, expected_stat)
                and stat_matches(held_stat, expected_fd_stat)
                and stat_matches(path_stat, held_stat)
            )
        except (OSError, TypeError, NotImplementedError, ValueError):
            return False

    def _refresh_shared_publications(
        self, context: Dict[str, Any], item: Dict[str, Any]
    ) -> bool:
        for publication in context.get("published", ()):
            if not publication.get("shared_stage") or publication.get("stage_identity") != item.get(
                "stage_identity"
            ):
                continue
            try:
                path_stat = self._regular_entry_stat(
                    publication.get("parent_fd"), publication["name"]
                )
                held_stat = os.fstat(publication["fd"])
                if (
                    path_stat is None
                    or not self._file_stat_matches_without_ctime(
                        path_stat, publication["stat"]
                    )
                    or not self._file_stat_matches_without_ctime(
                        held_stat, publication["fd_stat"]
                    )
                    or not self._file_stat_matches(path_stat, held_stat)
                ):
                    return False
                publication["stat"] = path_stat
                publication["fd_stat"] = held_stat
            except (OSError, TypeError, NotImplementedError, ValueError):
                return False
        return True

    def _move_context_published_matches(
        self, context: Dict[str, Any], *, include_ctime: bool = True
    ) -> bool:
        return all(
            self._publication_matches(publication, include_ctime=include_ctime)
            for publication in context.get("published", ())
        )

    def _commit_move_context(self, context: Dict[str, Any]) -> bool:
        if not self._move_context_is_current(context):
            return False
        stage_entry = self._entry_lstat(context["source_root"]["fd"], context["stage_name"])
        if (
            stage_entry is None
            or (stage_entry.st_dev, stage_entry.st_ino) != context["stage_identity"]
            or not self._move_context_remaining_matches(context)
            or not self._move_context_published_matches(context)
        ):
            return False
        for item in context.get("staged", []):
            if not self._unlink_if_identity(
                context["stage_fd"], item["stage_name"], item["stage_identity"]
            ):
                return False
            if not self._refresh_shared_publications(context, item):
                return False
        self._fsync_dir(context["stage_fd"])
        if (
            not self._move_context_remaining_matches(context)
            or not self._move_context_published_matches(context, include_ctime=False)
        ):
            return False
        stage_entry = self._entry_lstat(context["source_root"]["fd"], context["stage_name"])
        if (
            stage_entry is None
            or (stage_entry.st_dev, stage_entry.st_ino) != context["stage_identity"]
        ):
            return False
        try:
            os.rmdir(context["stage_name"], dir_fd=context["source_root"]["fd"])
        except OSError:
            return False
        self._fsync_dir(context["source_root"]["fd"])
        if (
            not self._move_context_remaining_matches(context)
            or not self._move_context_published_matches(context, include_ctime=False)
        ):
            return False
        context["committed"] = True
        return True

    @staticmethod
    def _close_move_context(context: Optional[Dict[str, Any]]) -> None:
        if context is None:
            return
        fds: List[Optional[int]] = [context.get("stage_fd")]
        fds.extend(context.get("open_fds", []))
        for bound in (context.get("source_root"), context.get("target_root")):
            if bound:
                fds.extend((bound.get("parent_fd"), bound.get("fd")))
        for item in context.get("staged", []):
            fds.append(item.get("source_parent_fd"))
            fds.append(item.get("original_fd"))
        for item in context.get("published", []):
            fds.append(item.get("parent_fd"))
            fds.append(item.get("fd"))
        seen = set()
        for fd in fds:
            if fd is None or fd in seen:
                continue
            seen.add(fd)
            try:
                os.close(fd)
            except OSError:
                pass

    def _move_file(
        self,
        source: str,
        target: str,
        source_root: Optional[str] = None,
        target_root: Optional[str] = None,
        *,
        move_context: Optional[Dict[str, Any]] = None,
        source_identity: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not source_root or not target_root:
            return False
        own_context = move_context is None
        context = move_context or self._create_move_context(source_root, target_root)
        if context is None:
            return False
        try:
            captured = source_identity or self._capture_move_identity(context, source)
            if captured is None:
                if own_context:
                    self._rollback_move_context(context)
                return False
            staged = self._stage_move_source(context, source, captured)
            if staged is None or not self._publish_staged_move(context, staged, target):
                if own_context:
                    self._rollback_move_context(context)
                return False
            if own_context:
                if not self._commit_move_context(context):
                    self._rollback_move_context(context)
                    return False
            return True
        finally:
            if own_context:
                self._close_move_context(context)

    def _execute_move_plan(
        self,
        move_plan: List[Tuple[str, str, List[Tuple[str, str]]]],
        source_root: str,
        target_root: str,
        move_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[int, int]]:
        own_context = move_context is None
        context = move_context or self._create_move_context(source_root, target_root)
        if context is None:
            return None
        try:
            identities: Dict[str, Dict[str, Any]] = {}
            expected_manifest = context.get("expected_source_manifest")
            expected_directories = context.get("expected_source_directories")
            if expected_manifest is not None:
                if expected_directories is None:
                    self._rollback_move_context(context)
                    return None
                expected_by_path = {item[0]: item for item in expected_manifest}
                excluded_stage = (
                    context["stage_name"],
                    context["stage_identity"],
                )

                def manifest_matches(
                    expected_files: Tuple[Tuple[str, int, int, int, int, int], ...],
                    expected_dirs: Tuple[Tuple[str, int, int], ...],
                ) -> bool:
                    current_tree = self._scan_manifest_dir(
                        context["source_root"]["fd"],
                        excluded_root=excluded_stage,
                    )
                    if current_tree is None:
                        return False
                    current_files, current_dirs = current_tree
                    current_files.sort(key=lambda item: item[0])
                    current_dirs.sort(key=lambda item: item[0])
                    return (
                        tuple(current_files) == expected_files
                        and tuple(current_dirs) == expected_dirs
                    )

                expected_files = tuple(expected_manifest)
                expected_dirs = tuple(expected_directories)
                if not manifest_matches(expected_files, expected_dirs):
                    self._rollback_move_context(context)
                    return None
                for relative, expected in expected_by_path.items():
                    candidate = os.path.join(source_root, *relative.split("/"))
                    captured = self._capture_move_identity(context, candidate)
                    if captured is None or not self._manifest_stat_matches(
                        captured["stat"], expected
                    ):
                        self._rollback_move_context(context)
                        return None
                    identities[candidate] = captured
            for media_file, _, subtitle_pairs in move_plan:
                for candidate in [media_file, *(subtitle_file for subtitle_file, _ in subtitle_pairs)]:
                    if candidate not in identities:
                        captured = self._capture_move_identity(context, candidate)
                        if captured is None:
                            self._rollback_move_context(context)
                            return None
                        identities[candidate] = captured
            if expected_manifest is not None:
                expected_paths = set(expected_by_path)
                if {
                    self._safe_relative_path(source_root, candidate).replace(os.sep, "/")
                    for candidate in identities
                    if self._safe_relative_path(source_root, candidate) is not None
                } != expected_paths:
                    self._rollback_move_context(context)
                    return None
                planned_files: List[Tuple[str, str, Optional[str]]] = []
                for media_file, target_media, subtitle_pairs in move_plan:
                    planned_files.append((media_file, target_media, None))
                    for subtitle_file, target_subtitle in subtitle_pairs:
                        planned_files.append((subtitle_file, target_subtitle, media_file))
                if any(candidate not in identities for candidate, _, _ in planned_files):
                    self._rollback_move_context(context)
                    return None
                staged_items: Dict[str, Dict[str, Any]] = {}
                for candidate, _, _ in planned_files:
                    staged = self._stage_move_source(
                        context,
                        candidate,
                        identities[candidate],
                    )
                    if staged is None:
                        self._rollback_move_context(context)
                        return None
                    staged_items[candidate] = staged
                staged_paths = {
                    identities[candidate]["relative"].replace(os.sep, "/")
                    for candidate, _, _ in planned_files
                }
                expected_remaining = tuple(
                    item for item in expected_files if item[0] not in staged_paths
                )
                context["expected_remaining_source_manifest"] = expected_remaining
                context["expected_remaining_source_directories"] = expected_dirs
                if not manifest_matches(expected_remaining, expected_dirs):
                    self._rollback_move_context(context)
                    return None
                for candidate, target, _ in planned_files:
                    if not self._publish_staged_move(
                        context, staged_items[candidate], target
                    ):
                        self._rollback_move_context(context)
                        return None
                if not manifest_matches(expected_remaining, expected_dirs):
                    self._rollback_move_context(context)
                    return None
                moved_files = sum(1 for _, _, parent in planned_files if parent is None)
                moved_subtitles = len(planned_files) - moved_files
            else:
                moved_files = moved_subtitles = 0
                for media_file, target_media, subtitle_pairs in move_plan:
                    if not self._move_file(
                        media_file,
                        target_media,
                        source_root=source_root,
                        target_root=target_root,
                        move_context=context,
                        source_identity=identities[media_file],
                    ):
                        self._rollback_move_context(context)
                        return None
                    moved_files += 1
                    for subtitle_file, target_subtitle in subtitle_pairs:
                        if not self._move_file(
                            subtitle_file,
                            target_subtitle,
                            source_root=source_root,
                            target_root=target_root,
                            move_context=context,
                            source_identity=identities[subtitle_file],
                        ):
                            self._rollback_move_context(context)
                            return None
                        moved_subtitles += 1

            if not self._commit_move_context(context):
                self._rollback_move_context(context)
                return None
            return moved_files, moved_subtitles
        except (OSError, TypeError, NotImplementedError, ValueError):
            self._rollback_move_context(context)
            return None
        finally:
            if own_context:
                self._close_move_context(context)

    @classmethod
    def _course_sort_key(cls, file_path: str, course_path: str) -> List[Any]:
        return cls._natural_key(os.path.relpath(file_path, course_path).replace("\\", "/"))

    @classmethod
    def _natural_path_key(cls, path: str) -> List[Any]:
        return cls._natural_key(path)

    @staticmethod
    def _natural_key(value: str) -> List[Any]:
        parts = _NATURAL_SPLIT_RE.split(value)
        output: List[Any] = []
        for part in parts:
            if part.isdigit():
                output.append(int(part))
            else:
                output.append(part.lower())
        return output

    def _normalize_config(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        def _coerce_threshold(raw: Any, default: int) -> int:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return default
            return value if 80 <= value <= 100 else default

        def _coerce_margin(raw: Any, default: int) -> int:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return default
            return value if 5 <= value <= 30 else default

        raw = config if isinstance(config, dict) else {}
        legacy_naming_mode = str(
            raw.get("naming_mode", "preview") or "preview"
        ).strip().lower()
        legacy_auto_organize = legacy_naming_mode == "apply"
        auto_organize = _coerce_bool(
            raw.get("auto_organize", legacy_auto_organize),
            legacy_auto_organize,
        )
        naming_mode = "apply" if auto_organize else "preview"

        return {
            "enabled": _coerce_bool(raw.get("enabled", False), False),
            "run_once": _coerce_bool(raw.get("run_once", False), False),
            "incoming": str(raw.get("incoming", self.DEFAULT_INCOMING)),
            "tv_output": str(raw.get("tv_output", self.DEFAULT_TV_OUTPUT)),
            "movie_output": str(raw.get("movie_output", self.DEFAULT_MOVIE_OUTPUT)),
            "children_output": str(
                raw.get("children_output", raw.get("output", self.DEFAULT_CHILDREN_OUTPUT))
            ),
            "interval": self._normalize_interval(raw.get("interval", self.DEFAULT_INTERVAL)),
            "auto_organize": auto_organize,
            "naming_mode": naming_mode,
            "naming_auto_threshold": _coerce_threshold(raw.get("naming_auto_threshold", 90), 90),
            "naming_min_margin": _coerce_margin(raw.get("naming_min_margin", 12), 12),
            "naming_uncertain_policy": "hold",
            "naming_ai_review": True,
            "naming_manual_overrides": str(raw.get("naming_manual_overrides", "")),
            "naming_clear_cache_once": _coerce_bool(
                raw.get("naming_clear_cache_once", False),
                False,
            ),
        }

    @classmethod
    def _normalize_interval(cls, interval: Any) -> int:
        try:
            value = int(interval)
            return value if value > 0 else cls.DEFAULT_INTERVAL
        except (TypeError, ValueError):
            return cls.DEFAULT_INTERVAL

    def _get_config(self) -> Dict[str, Any]:
        run_config_local = getattr(self, "_run_config_local", None)
        run_config = getattr(run_config_local, "config", None)
        if isinstance(run_config, dict):
            return dict(run_config)
        try:
            raw = self.get_config()
            if not isinstance(raw, dict):
                return self._normalize_config()
            return self._normalize_config(raw)
        except Exception:
            return self._normalize_config()

    def _persist_config(self, config: Dict[str, Any]) -> bool:
        if not hasattr(self, "update_config"):
            return False
        try:
            result = self.update_config(config)
            return result is not False
        except TypeError:
            pass
        except Exception:
            return False

        try:
            result = self.update_config(config=config)
            return result is not False
        except Exception:
            return False

    ARCHIVE_DIRECTORIES_KEY = "archive_directories"
    DOWNLOAD_DIRECTORIES_KEY = "download_directories"
    BUILTIN_ARCHIVE_DIRECTORIES = (
        ("tv", "电视剧"),
        ("movie", "电影"),
        ("children", "儿童课程"),
    )

    @classmethod
    def _directory_item_path(cls, value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalize_directory_key(
        cls, value: Any, index: int, used: set[str], prefix: str
    ) -> str:
        candidate = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().lower())
        candidate = candidate.strip("_-") or f"{prefix}_{index + 1}"
        base = candidate
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        return candidate

    @classmethod
    def _normalize_download_directories(cls, raw: Dict[str, Any]) -> List[Dict[str, str]]:
        values = raw.get(cls.DOWNLOAD_DIRECTORIES_KEY)
        if not isinstance(values, list):
            legacy = cls._directory_item_path(raw.get("incoming"))
            values = [{"name": "下载目录", "path": legacy}] if legacy else []
        output: List[Dict[str, str]] = []
        for index, item in enumerate(values):
            if isinstance(item, str):
                item = {"path": item}
            if not isinstance(item, dict):
                continue
            path = cls._directory_item_path(item.get("path"))
            name = cls._directory_item_path(item.get("name", item.get("label")))
            output.append(
                {
                    "name": name or f"下载目录 {index + 1}",
                    "path": path,
                }
            )
        return output

    @classmethod
    def _normalize_archive_directories(
        cls, raw: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        values = raw.get(cls.ARCHIVE_DIRECTORIES_KEY)
        if not isinstance(values, list):
            legacy_keys = ("tv_output", "movie_output", "children_output", "output")
            if any(key in raw for key in legacy_keys):
                values = [
                    {
                        "key": "tv",
                        "name": "电视剧",
                        "path": raw.get("tv_output", ""),
                        "media_type": "tv",
                    },
                    {
                        "key": "movie",
                        "name": "电影",
                        "path": raw.get("movie_output", ""),
                        "media_type": "movie",
                    },
                    {
                        "key": "children",
                        "name": "儿童课程",
                        "path": raw.get("children_output", raw.get("output", "")),
                        "media_type": "tv",
                        "category": "儿童",
                    },
                ]
            else:
                values = []
        output: List[Dict[str, str]] = []
        used: set[str] = set()
        for index, item in enumerate(values):
            if isinstance(item, str):
                item = {"path": item}
            if not isinstance(item, dict):
                continue
            default_key = (
                cls.BUILTIN_ARCHIVE_DIRECTORIES[index][0]
                if index < len(cls.BUILTIN_ARCHIVE_DIRECTORIES)
                else f"archive_{index + 1}"
            )
            key = cls._normalize_directory_key(
                item.get("key", item.get("id", default_key)),
                index,
                used,
                "archive",
            )
            name = cls._directory_item_path(item.get("name", item.get("label")))
            if not name:
                name = next(
                    (
                        label
                        for builtin_key, label in cls.BUILTIN_ARCHIVE_DIRECTORIES
                        if builtin_key == key
                    ),
                    f"归档目录 {index + 1}",
                )
            output.append(
                {
                    "id": cls._directory_item_path(item.get("id")) or key,
                    "key": key,
                    "name": name,
                    "label": name,
                    "path": cls._directory_item_path(item.get("path")),
                    "media_type": cls._directory_item_path(item.get("media_type")),
                    "category": cls._directory_item_path(
                        item.get("category", item.get("media_category"))
                    ),
                }
            )
        return output

    @classmethod
    def _archive_paths_by_key(cls, archives: List[Dict[str, str]]) -> Dict[str, str]:
        return {
            str(item.get("key", "")).strip(): str(item.get("path", "")).strip()
            for item in archives
            if str(item.get("key", "")).strip()
        }

    def _download_directories(
        self, config: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, str]]:
        source = config if isinstance(config, dict) else self._get_config()
        values = source.get(self.DOWNLOAD_DIRECTORIES_KEY)
        if isinstance(values, list):
            return [dict(item) for item in values if isinstance(item, dict)]
        return self._normalize_download_directories(source)

    def _archive_directories(
        self, config: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, str]]:
        source = config if isinstance(config, dict) else self._get_config()
        values = source.get(self.ARCHIVE_DIRECTORIES_KEY)
        if isinstance(values, list):
            return [dict(item) for item in values if isinstance(item, dict)]
        return self._normalize_archive_directories(source)

    def _download_paths(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        return [
            str(item.get("path", "")).strip()
            for item in self._download_directories(config)
            if str(item.get("path", "")).strip()
        ]

    def _download_root_for_path(
        self, source_path: Any, config: Optional[Dict[str, Any]] = None
    ) -> str:
        for incoming in self._download_paths(config):
            if self._is_within_realpath(incoming, str(source_path)):
                return incoming
        return ""

    def _archive_output_roots(
        self, config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        return self._archive_paths_by_key(self._archive_directories(config))

    def _archive_directory_by_key(
        self, key: Any, config: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, str]]:
        normalized = str(key or "").strip().lower()
        for item in self._archive_directories(config):
            if str(item.get("key", "")).strip().lower() == normalized:
                return item
        return None

    def _manual_target_libraries(self) -> set[str]:
        return set(self._archive_output_roots())

    @staticmethod
    def _directory_is_readable(path: Any) -> bool:
        text = str(path or "").strip()
        return bool(
            text
            and os.path.isdir(text)
            and os.access(text, os.R_OK | os.X_OK)
        )

    @classmethod
    def _synthetic_archive_rule(
        cls, archive: Dict[str, str], incoming: str
    ) -> Dict[str, Any]:
        return {
            "title": archive["name"],
            "value": archive["key"],
            "name": archive["name"],
            "media_category": archive.get("category", ""),
            "media_type": archive.get("media_type", ""),
            "download_path": incoming,
            "path": archive["path"],
            "monitor_type": "",
            "storage": "local",
            "library_storage": "local",
            "transfer_type": "copy",
            "renaming": True,
            "scraping": False,
            "notify": False,
            "library_type_folder": False,
            "library_category_folder": False,
            "naming_format": "",
            "movie_naming_format": "",
            "synthetic": True,
        }

    def _moviepilot_directory_context(self) -> Dict[str, Any]:
        # This historical method name is used throughout the review and transfer
        # flow.  It now deliberately resolves only plugin-owned configuration.
        config = self._get_config()
        downloads = self._download_directories(config)
        archives = self._archive_directories(config)
        incoming = str(downloads[0].get("path", "")).strip() if downloads else ""
        issues: List[str] = []
        if not downloads:
            issues.append("请至少添加一个下载目录")
        for index, item in enumerate(downloads):
            if not str(item.get("path", "")).strip():
                issues.append(f"请填写下载目录 {index + 1}")
        if not archives:
            issues.append("请至少添加一个归档目录")
        for index, item in enumerate(archives):
            if not str(item.get("path", "")).strip():
                issues.append(f"请填写归档目录 {index + 1}")

        selected: Dict[str, Dict[str, Any]] = {}
        libraries: List[Dict[str, Any]] = []
        for archive in archives:
            path = str(archive.get("path", "")).strip()
            key = str(archive.get("key", "")).strip()
            if not key or not path:
                continue
            rule = self._synthetic_archive_rule(archive, incoming)
            selected[key] = rule
            libraries.append(rule)

        ready = (
            bool(downloads)
            and bool(archives)
            and not issues
            and len(selected) == len(archives)
        )
        return {
            "available": True,
            "incoming": incoming,
            "download_directories": downloads,
            "archive_directories": archives,
            "libraries": libraries,
            "rules": libraries,
            "selected": selected,
            "ready": ready,
            "issues": list(dict.fromkeys(issues)),
            "message": "；".join(dict.fromkeys(issues)),
            "settings_url": "",
            "monitoring_enabled": False,
            "monitoring_rules": [],
            "monitoring_conflicts": [],
        }

    def _review_path_config(
        self, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        config = self._get_config()
        directory_context = context or self._moviepilot_directory_context()
        config[self.DOWNLOAD_DIRECTORIES_KEY] = list(
            directory_context.get("download_directories", [])
        )
        config[self.ARCHIVE_DIRECTORIES_KEY] = list(
            directory_context.get("archive_directories", [])
        )
        config["incoming"] = str(directory_context.get("incoming", "") or "")
        archive_paths = {
            key: str(rule.get("path", "") or "")
            for key, rule in directory_context.get("selected", {}).items()
            if isinstance(rule, dict)
        }
        # Compatibility projections keep existing recognition and transfer code
        # working for the built-in types.  The authoritative source remains the
        # archive_directories list.
        config["tv_output"] = archive_paths.get("tv", "")
        config["movie_output"] = archive_paths.get("movie", "")
        config["children_output"] = archive_paths.get("children", "")

        if not directory_context.get("ready"):
            if config.get("auto_organize"):
                config["auto_organize"] = False
                config["naming_mode"] = "preview"
            config["monitoring_conflict"] = (
                directory_context.get("message")
                or "目录配置不完整，自动整理已暂停。"
            )
            return config

        unreadable = [
            path
            for path in self._download_paths(config)
            if not self._directory_is_readable(path)
        ]
        if unreadable:
            if config.get("auto_organize"):
                config["auto_organize"] = False
                config["naming_mode"] = "preview"
            config["monitoring_conflict"] = "下载目录不可读取，自动整理已暂停。"
            return config

        config["monitoring_conflict"] = ""
        return config

    def _normalize_config(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        def coerce_threshold(raw_value: Any, default: int) -> int:
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                return default
            return value if 80 <= value <= 100 else default

        def coerce_margin(raw_value: Any, default: int) -> int:
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                return default
            return value if 5 <= value <= 30 else default

        raw = config if isinstance(config, dict) else {}
        legacy_naming_mode = str(raw.get("naming_mode", "preview") or "preview").strip().lower()
        legacy_auto_organize = legacy_naming_mode == "apply"
        auto_organize = _coerce_bool(
            raw.get("auto_organize", legacy_auto_organize), legacy_auto_organize
        )
        downloads = self._normalize_download_directories(raw)
        archives = self._normalize_archive_directories(raw)
        archive_paths = self._archive_paths_by_key(archives)
        incoming = str(downloads[0].get("path", "")).strip() if downloads else ""
        return {
            "enabled": _coerce_bool(raw.get("enabled", False), False),
            "run_once": _coerce_bool(raw.get("run_once", False), False),
            self.DOWNLOAD_DIRECTORIES_KEY: downloads,
            self.ARCHIVE_DIRECTORIES_KEY: archives,
            "incoming": incoming,
            "tv_output": archive_paths.get("tv", ""),
            "movie_output": archive_paths.get("movie", ""),
            "children_output": archive_paths.get("children", ""),
            "interval": self._normalize_interval(
                raw.get("interval", self.DEFAULT_INTERVAL)
            ),
            "auto_organize": auto_organize,
            "naming_mode": "apply" if auto_organize else "preview",
            "naming_auto_threshold": coerce_threshold(
                raw.get("naming_auto_threshold", 90), 90
            ),
            "naming_min_margin": coerce_margin(raw.get("naming_min_margin", 12), 12),
            "naming_uncertain_policy": "hold",
            "naming_ai_review": True,
            "naming_manual_overrides": str(
                raw.get("naming_manual_overrides", "") or ""
            ),
            "naming_clear_cache_once": _coerce_bool(
                raw.get("naming_clear_cache_once", False), False
            ),
        }
