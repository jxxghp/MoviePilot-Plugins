"""MediaGovernor v5 的后端对账器。

这里只保存当前文件事实、身份候选和逐作品结论。浏览器不参与扫描，也不持有
私有媒体地图；旧 ``media_map.json`` 会原样保留，但从不作为 v5 真值。
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".ts", ".m2ts", ".iso"}
SIDECAR_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".nfo", ".jpg", ".jpeg", ".png", ".webp"}
DISC_DIRECTORIES = {"bdmv", "video_ts"}
AI_TIMEOUT_SECONDS = 45
MOVIEPILOT_TIMEOUT_SECONDS = 30
SEARCH_TIMEOUT_SECONDS = 20
SAMPLE_PATTERN = re.compile(r"(^|[\\/ ._-])(sample|samples|trailer|extras?)([\\/ ._-]|$)", re.IGNORECASE)
SEASON_PATTERN = re.compile(r"(?:^|[ ._-])S(\d{1,2})(?:E\d{1,4})?", re.IGNORECASE)
EPISODE_PATTERN = re.compile(r"S(\d{1,2})E(\d{1,4})", re.IGNORECASE)


class AuditCancelled(Exception):
    """用户要求停止只读检查；不得被记录成检查失败。"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    for method in ("model_dump", "dict", "to_dict"):
        candidate = getattr(value, method, None)
        if callable(candidate):
            result = candidate()
            if isinstance(result, dict):
                return result
    return {key: item for key, item in vars(value).items() if not key.startswith("_")} if hasattr(value, "__dict__") else {}


def normal_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").rstrip("/")
    return text.casefold()


def under(path: Any, root: Any) -> bool:
    item, base = normal_path(path), normal_path(root)
    return bool(item and base and (item == base or item.startswith(base + "/")))


def stable_id(*parts: Any) -> str:
    raw = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def json_text(value: Any, *, sort_keys: bool = False) -> str:
    """把 MoviePilot DTO 中的 Path、Enum 与时间统一写成稳定文本。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=sort_keys, default=str, separators=(",", ":"))


def fingerprint(entries: Iterable[dict[str, Any]]) -> str:
    rows = sorted(
        f"{normal_path(row.get('path'))}|{row.get('type') or ''}|{int(row.get('size') or 0)}|{row.get('modify_time') or 0}"
        for row in entries
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def item_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or Path(str(item.get("path") or "")).name or "未命名作品")


def is_media_file(item: dict[str, Any]) -> bool:
    return str(Path(str(item.get("name") or item.get("path") or "")).suffix).casefold() in VIDEO_EXTENSIONS


def is_sidecar(item: dict[str, Any]) -> bool:
    return str(Path(str(item.get("name") or item.get("path") or "")).suffix).casefold() in SIDECAR_EXTENSIONS


def is_sample(item: dict[str, Any]) -> bool:
    return bool(SAMPLE_PATTERN.search(str(item.get("path") or item.get("name") or "")))


def identity_key(identity: dict[str, Any] | None) -> str:
    if not identity:
        return ""
    source = str(identity.get("media_source") or "").casefold()
    source = {"tmdb": "themoviedb", "the_movie_db": "themoviedb"}.get(source, source)
    media_id = str(identity.get("media_id") or "").strip()
    media_type = media_type_key(identity.get("media_type") or identity.get("type"))
    return f"{source}:{media_id}:{media_type}" if source and media_id else ""


def media_type_key(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").casefold()
    if text in {"movie", "电影"}:
        return "movie"
    if text in {"tv", "电视剧", "电视"}:
        return "tv"
    return "unknown"


def category_key(value: Any) -> str:
    text = str(value or "").casefold()
    if any(word in text for word in ("动漫", "动画", "anime", "animation")):
        return "anime"
    if any(word in text for word in ("综艺", "variety")):
        return "variety"
    if any(word in text for word in ("纪录", "documentary")):
        return "documentary"
    if any(word in text for word in ("电影", "movie")):
        return "movie"
    if any(word in text for word in ("电视剧", "电视", "tv")):
        return "tv"
    return "other"


def expected_category(identity: dict[str, Any]) -> str:
    category = category_key(identity.get("category"))
    if category != "other":
        return category
    genre_values = identity.get("genres") or []
    if any(str(getattr(value, "id", value.get("id") if isinstance(value, dict) else value)) == "16" for value in genre_values):
        return "anime"
    genres = " ".join(str(value) for value in genre_values)
    if category_key(genres) == "anime":
        return "anime"
    return media_type_key(identity.get("media_type"))


def root_category(path: str, library_roots: list[dict[str, Any]]) -> str:
    matches = [row for row in library_roots if under(path, row.get("path"))]
    if not matches:
        return "other"
    row = max(matches, key=lambda value: len(normal_path(value.get("path"))))
    return category_key(" ".join(str(row.get(key) or "") for key in ("name", "media_category", "media_type", "path")))


def work_folder(path: str) -> str:
    parts = [part for part in str(path or "").replace("\\", "/").split("/") if part]
    season_index = next((index for index, part in enumerate(parts) if re.fullmatch(r"(?:season|s)[ ._-]?\d{1,2}", part, re.IGNORECASE)), -1)
    value = parts[season_index - 1] if season_index > 0 else (parts[-2] if len(parts) > 1 else "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", re.sub(r"\b(?:19|20)\d{2}\b", "", value, flags=re.IGNORECASE)).strip().casefold()


def identity_from_media(value: Any) -> dict[str, Any]:
    data = model_dict(value)
    source = data.get("media_source") or data.get("source") or data.get("scrape_source")
    source = getattr(source, "value", source)
    media_id = data.get("media_id") or data.get("tmdb_id") or data.get("douban_id") or data.get("id")
    genres = data.get("genres") or data.get("genre_ids") or []
    if isinstance(genres, str):
        genres = [genres]
    return {
        "title": str(data.get("title") or data.get("name") or ""),
        "original_title": str(data.get("original_title") or ""),
        "year": str(data.get("year") or ""),
        "media_type": media_type_key(data.get("type") or data.get("media_type")),
        "media_source": str(source or ""),
        "media_id": str(media_id or ""),
        "category": str(data.get("category") or ""),
        "genres": [str(item) for item in genres][:20],
    }


def history_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(row.get("title") or ""),
        "original_title": "",
        "year": str(row.get("year") or ""),
        "media_type": media_type_key(row.get("type")),
        "media_source": str(getattr(row.get("media_source"), "value", row.get("media_source")) or ""),
        "media_id": str(row.get("media_id") or ""),
        "category": str(row.get("category") or row.get("media_category") or ""),
        "genres": [],
    }


def public_identity(identity: dict[str, Any]) -> dict[str, Any]:
    return {key: identity.get(key) for key in ("title", "original_title", "year", "media_type", "media_source", "media_id", "category", "genres")}


def latest_histories(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: int(item.get("id") or 0)):
        source = normal_path(row.get("src") or model_dict(row.get("src_fileitem")).get("path"))
        if source:
            result[source] = row
    return result


def classify_false_success(current: str, expected: str, identity: dict[str, Any], library_roots: list[dict[str, Any]]) -> str:
    if root_category(current, library_roots) != root_category(expected, library_roots):
        return "category_error"
    current_season, expected_season = SEASON_PATTERN.search(current), SEASON_PATTERN.search(expected)
    if bool(current_season) != bool(expected_season) or (current_season and expected_season and current_season.group(1) != expected_season.group(1)):
        return "hierarchy_error"
    source_episode, target_episode = EPISODE_PATTERN.search(current), EPISODE_PATTERN.search(expected)
    if source_episode and target_episode and source_episode.group(2) != target_episode.group(2):
        return "episode_error"
    if work_folder(current) and work_folder(expected) and work_folder(current) != work_folder(expected):
        return "identity_error"
    names = {re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", str(identity.get(key) or "")).strip().casefold() for key in ("title", "original_title")}
    names.discard("")
    if names and work_folder(current) and work_folder(current) not in names:
        return "identity_error"
    if Path(current).suffix.casefold() in SIDECAR_EXTENSIONS:
        return "attachment_error"
    return "path_error"


ISSUE_LABELS = {
    "native_failure": "原生整理失败",
    "category_error": "目录分类错误",
    "identity_error": "作品对应错误",
    "episode_error": "季集对应错误",
    "hierarchy_error": "目录层级错误",
    "attachment_error": "字幕或附件对应错误",
    "path_error": "整理位置错误",
    "identity_confirmation": "需要确认作品身份",
    "manual_change": "媒体库文件已被手动改动",
    "read_error": "目录没有读取完整",
    "preview_error": "官方预览失败",
}


@dataclass
class Inventory:
    objects: list[dict[str, Any]]
    library_roots: list[dict[str, Any]]
    histories: list[dict[str, Any]]
    errors: list[dict[str, str]]


def history_source(row: dict[str, Any]) -> str:
    return str(row.get("src") or model_dict(row.get("src_fileitem")).get("path") or "")


def history_destination(row: dict[str, Any]) -> str:
    return str(row.get("dest") or model_dict(row.get("dest_fileitem")).get("path") or "")


def history_group_key(row: dict[str, Any]) -> str:
    """优先使用下载任务边界；没有 hash 时退到已知作品身份。"""
    download_hash = str(row.get("download_hash") or "").strip()
    if download_hash:
        return f"hash:{download_hash}"
    key = identity_key(history_identity(row))
    return f"identity:{key}" if key else ""


def partition_entries(top: dict[str, Any], entries: list[dict[str, Any]], histories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把一个下载目录拆成作品任务；只使用可证明的历史边界，不猜标题。"""
    rows = [top] if top.get("type") == "file" else entries
    exact_history: dict[str, dict[str, Any]] = {}
    for history in histories:
        source = normal_path(history_source(history))
        if source:
            exact_history[source] = history
    videos = [row for row in rows if is_media_file(row) and not is_sample(row)]
    video_parents = {normal_path(Path(str(row.get("path") or "")).parent) for row in videos}
    sidecars = [
        row for row in rows
        if is_sidecar(row) and not is_sample(row)
        and (normal_path(row.get("path")) in exact_history or normal_path(Path(str(row.get("path") or "")).parent) in video_parents)
    ]
    media_rows = [*videos, *sidecars]
    if not media_rows:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    unmatched: list[dict[str, Any]] = []
    for row in media_rows:
        history = exact_history.get(normal_path(row.get("path")))
        key = history_group_key(history) if history else ""
        if key:
            groups.setdefault(key, []).append(row)
        else:
            unmatched.append(row)
    # 没有历史边界时，只在“多个非季度子目录且各自都有视频”这一结构证据充分的
    # 合集/混包场景拆分；Season 1、Season 2 仍保持为同一部剧。
    if unmatched:
        top_path = normal_path(top.get("path"))
        children: dict[str, list[dict[str, Any]]] = {}
        for row in unmatched:
            relative = normal_path(row.get("path"))[len(top_path):].lstrip("/") if top_path and under(row.get("path"), top_path) else ""
            first = relative.split("/", 1)[0] if "/" in relative else ""
            children.setdefault(first, []).append(row)
        splittable = [key for key, values in children.items() if key and any(is_media_file(row) for row in values)]
        season_children = any(re.fullmatch(r"(?:season|s)[ ._-]?\d{1,2}", key, re.IGNORECASE) for key in splittable)
        if len(splittable) >= 2 and not season_children:
            for child in splittable:
                groups[f"folder:{child}"] = children[child]
            leftovers = [row for key, values in children.items() if key not in splittable for row in values]
            if leftovers:
                groups["unmatched"] = leftovers
        else:
            groups["unmatched"] = unmatched
    result: list[dict[str, Any]] = []
    for key, members in groups.items():
        member_histories = [
            row for row in histories
            if history_group_key(row) == key and any(normal_path(history_source(row)) == normal_path(item.get("path")) for item in members)
        ] if key != "unmatched" else []
        label = item_name(top)
        if key.startswith("folder:"):
            label = key.split(":", 1)[1]
        elif key != "unmatched":
            titles = [str(row.get("title") or "").strip() for row in member_histories if row.get("title")]
            label = titles[0] if titles else label
        result.append({"group_key": key, "label": label, "root": top, "entries": members, "histories": member_histories})
    return result


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    source_json TEXT NOT NULL, status TEXT NOT NULL, dirty INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identities (
                    object_id TEXT PRIMARY KEY, state TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    identity_json TEXT NOT NULL, candidates_json TEXT NOT NULL,
                    provenance TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    object_id TEXT NOT NULL, kind TEXT NOT NULL, complete INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(object_id, kind)
                );
                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY, object_id TEXT NOT NULL, kind TEXT NOT NULL,
                    reason TEXT NOT NULL, status TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
                    total INTEGER NOT NULL, done INTEGER NOT NULL, current TEXT NOT NULL,
                    error TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL, finished_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS findings_status ON findings(status, kind);
            """)

    def execute(self, sql: str, values: tuple[Any, ...] = ()) -> None:
        with self._lock, self._connect() as db:
            db.execute(sql, values)

    def query(self, sql: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(sql, values).fetchall()]

    def one(self, sql: str, values: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, values)
        return rows[0] if rows else None

    def upsert_object(self, obj: dict[str, Any]) -> None:
        previous = self.one("SELECT fingerprint FROM objects WHERE id=?", (obj["id"],))
        dirty = 1 if not previous or previous["fingerprint"] != obj["fingerprint"] else 0
        self.execute(
            "INSERT INTO objects VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,fingerprint=excluded.fingerprint,source_json=excluded.source_json,dirty=MAX(objects.dirty,excluded.dirty),updated_at=excluded.updated_at",
            (obj["id"], obj["label"], obj["fingerprint"], json_text(obj), "DISCOVERED", dirty, utcnow()),
        )

    def replace_findings(self, object_id: str, findings: list[dict[str, Any]]) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE findings SET status='resolved',updated_at=? WHERE object_id=? AND status='open'", (utcnow(), object_id))
            for finding in findings:
                finding_id = stable_id(object_id, finding["kind"])
                db.execute(
                    "INSERT INTO findings VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET reason=excluded.reason,status='open',evidence_json=excluded.evidence_json,updated_at=excluded.updated_at",
                    (finding_id, object_id, finding["kind"], finding["reason"], "open", json_text(finding.get("evidence") or {}), utcnow()),
                )
            db.execute("UPDATE objects SET status=?,dirty=0,updated_at=? WHERE id=?", ("OBSERVED", utcnow(), object_id))

    def save_identity(self, object_id: str, state: str, fp: str, identity: dict[str, Any], candidates: list[dict[str, Any]], provenance: str) -> None:
        self.execute(
            "INSERT INTO identities VALUES(?,?,?,?,?,?,?) ON CONFLICT(object_id) DO UPDATE SET state=excluded.state,fingerprint=excluded.fingerprint,identity_json=excluded.identity_json,candidates_json=excluded.candidates_json,provenance=excluded.provenance,updated_at=excluded.updated_at",
            (object_id, state, fp, json_text(identity), json_text(candidates), provenance, utcnow()),
        )

    def save_observation(self, object_id: str, kind: str, complete: bool, fp: str, payload: Any) -> None:
        self.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?) ON CONFLICT(object_id,kind) DO UPDATE SET complete=excluded.complete,fingerprint=excluded.fingerprint,payload_json=excluded.payload_json,updated_at=excluded.updated_at",
            (object_id, kind, int(complete), fp, json_text(payload), utcnow()),
        )

    def begin_job(self, mode: str, total: int = 0) -> str:
        job_id = stable_id(time.time_ns(), mode)
        self.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)", (job_id, mode, "running", "PREPARING", total, 0, "正在读取当前配置", "", 0, utcnow(), ""))
        return job_id

    def update_job(self, job_id: str, **values: Any) -> None:
        if not values:
            return
        fields = ",".join(f"{key}=?" for key in values)
        self.execute(f"UPDATE jobs SET {fields} WHERE id=?", tuple(values.values()) + (job_id,))

    def current_job(self) -> dict[str, Any] | None:
        return self.one("SELECT * FROM jobs ORDER BY started_at DESC LIMIT 1")


class MoviePilotAdapter:
    """MoviePilot 内部能力的唯一适配层；所有导入都延迟到真实调用。"""

    def __init__(self):
        self._loaded: dict[str, Any] | None = None

    def _ports(self) -> dict[str, Any]:
        if self._loaded is None:
            from app.application.directory import DirectoryHelper
            from app.chain.media import MediaChain
            from app.chain.storage import StorageChain
            from app.chain.transfer import TransferChain
            from app.schemas.file import FileItem
            from app.schemas.types import MediaSource, MediaType
            from app.sdk.queries import list_transfer_history
            self._loaded = {"dirs": DirectoryHelper(), "media": MediaChain(), "storage": StorageChain(), "transfer": TransferChain(), "FileItem": FileItem, "MediaSource": MediaSource, "MediaType": MediaType, "histories": list_transfer_history}
        return self._loaded

    @staticmethod
    def _directory(value: Any, kind: str) -> dict[str, Any]:
        data = model_dict(value)
        path_key = "download_path" if kind == "download" else "library_path"
        storage_key = "storage" if kind == "download" else "library_storage"
        return {**data, "path": str(data.get(path_key) or ""), "storage": str(data.get(storage_key) or "local"), "type": "dir"}

    def directories(self, kind: str) -> list[dict[str, Any]]:
        helper = self._ports()["dirs"]
        rows = helper.get_download_dirs() if kind == "download" else helper.get_library_dirs()
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            directory = self._directory(row, kind)
            path = directory["path"]
            normalized = normal_path(path)
            if not normalized or normalized == "/" or re.fullmatch(r"[a-z]:", normalized):
                continue
            key = (directory["storage"], normalized)
            if key not in seen:
                seen.add(key)
                result.append(directory)
        return result

    def list_dir(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        ports = self._ports()
        fileitem = ports["FileItem"](**{key: item.get(key) for key in ("path", "storage", "type", "name", "fileid", "parent_fileid") if item.get(key) is not None})
        return [model_dict(row) for row in (ports["storage"].list_files(fileitem) or [])]

    def get_item(self, storage: str, path: str) -> dict[str, Any] | None:
        value = self._ports()["storage"].get_file_item_strict(storage=storage or "local", path=Path(path))
        return model_dict(value) if value else None

    def histories(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            value = self._ports()["histories"](None, {"page": page, "count": 200, "sort": {"field": "id", "direction": "asc"}})
            rows = [model_dict(row) for row in getattr(value, "items", [])]
            result.extend(rows)
            if not getattr(value, "has_next", False):
                break
            page += 1
        return result

    def recognize(self, path: str) -> dict[str, Any]:
        context = self._ports()["media"].recognize_by_path(path, obtain_images=False)
        media = getattr(context, "media_info", None) if context else None
        return identity_from_media(media) if media else {}

    def search(self, query: str) -> list[dict[str, Any]]:
        _, rows = self._ports()["media"].search(query)
        return [identity_from_media(row) for row in rows or [] if identity_key(identity_from_media(row))][:8]

    def media_info(self, identity: dict[str, Any]) -> Any:
        ports = self._ports()
        source = ports["MediaSource"](identity["media_source"])
        mtype = ports["MediaType"].MOVIE if media_type_key(identity.get("media_type")) == "movie" else ports["MediaType"].TV
        return ports["media"].recognize_media(media_source=source, media_id=str(identity["media_id"]), mtype=mtype)

    def preview(self, source: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        ports = self._ports()
        media = self.media_info(identity)
        if not media:
            raise RuntimeError("MoviePilot 无法读取这个作品的数据库详情")
        src = ports["FileItem"](**{key: source.get(key) for key in ("path", "storage", "type", "name", "fileid", "parent_fileid") if source.get(key) is not None})
        directory = ports["dirs"].get_dir(media=media, src_path=Path(str(source["path"])), storage=source.get("storage") or "local")
        if not directory or not directory.library_path:
            raise RuntimeError("MoviePilot 没有找到匹配的媒体库目录")
        state, payload = ports["transfer"].manual_transfer(
            fileitem=src, target_storage=directory.library_storage, target_path=Path(directory.library_path),
            media_source=ports["MediaSource"](identity["media_source"]), media_id=str(identity["media_id"]),
            mtype=media.type, season=int(identity.get("season") or 0) or None,
            transfer_type=directory.transfer_type or "link", scrape=False,
            library_type_folder=directory.library_type_folder, library_category_folder=directory.library_category_folder,
            force=True, background=False, preview=True, reorganize=False, sync_extra_files=True,
        )
        if isinstance(payload, dict):
            for item in payload.get("items") or []:
                if isinstance(item, dict):
                    item.setdefault("target_storage", directory.library_storage or "local")
            return payload
        if not state:
            raise RuntimeError(str(payload or "官方预览失败"))
        return {"summary": {"total": 0, "success": 0, "failed": 0}, "items": []}

    def rebuild(self, entry: dict[str, Any], identity: dict[str, Any]) -> None:
        ports = self._ports()
        media = self.media_info(identity)
        if not media:
            raise RuntimeError("MoviePilot 无法读取这个作品的数据库详情")
        source = entry["source"]
        src = ports["FileItem"](**source)
        directory = ports["dirs"].get_dir(media=media, src_path=Path(str(source["path"])), storage=source.get("storage") or "local")
        if not directory or not directory.library_path:
            raise RuntimeError("MoviePilot 没有找到匹配的媒体库目录")
        cleanup = ports["FileItem"](**entry["current_item"]) if entry.get("current_item") else None
        state, error = ports["transfer"].manual_transfer(
            fileitem=src, target_storage=directory.library_storage, target_path=Path(directory.library_path),
            media_source=ports["MediaSource"](identity["media_source"]), media_id=str(identity["media_id"]),
            mtype=media.type, season=int(identity.get("season") or 0) or None,
            transfer_type=directory.transfer_type or "link", scrape=False,
            library_type_folder=directory.library_type_folder, library_category_folder=directory.library_category_folder,
            force=True, background=False, preview=False, reorganize=False, sync_extra_files=False,
            cleanup_dest_fileitem=cleanup,
        )
        if not state:
            raise RuntimeError(str(error or "MoviePilot 没有完成重建"))

    def ai_queries(self, evidence: dict[str, Any]) -> list[str]:
        return self.ai_queries_batch([("one", evidence)]).get("one", [])

    def ai_queries_batch(self, items: list[tuple[str, dict[str, Any]]]) -> dict[str, list[str]]:
        from app.agent.llm.helper import LLMHelper

        prompt = (
            "你只负责把每个文件结构转换成影视数据库搜索词，不判断整理是否正确。"
            "输出 JSON 对象，键保持输入 id，每项格式为 {\"queries\":[{\"title\":\"\",\"year\":\"\",\"media_type\":\"movie|tv\"}]}。"
            "每项最多3个搜索词；无法判断就给空数组。\n"
            + json.dumps({"items": [{"id": key, "evidence": evidence} for key, evidence in items[:4]]}, ensure_ascii=False, separators=(",", ":"))
        )
        model = LLMHelper.get_llm(streaming=False)
        if inspect.isawaitable(model):
            model = asyncio.run(model)
        ainvoke = getattr(model, "ainvoke", None)
        invoke = getattr(model, "invoke", None)
        if callable(ainvoke):
            response = asyncio.run(asyncio.wait_for(ainvoke(prompt), timeout=AI_TIMEOUT_SECONDS))
        elif callable(invoke):
            response = invoke(prompt)
        else:
            raise TypeError("当前大模型没有可用的调用接口")
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        text = LLMHelper.extract_text_content(getattr(response, "content", response))
        match = re.search(r"\{.*\}", str(text), re.DOTALL)
        value = json.loads(match.group(0)) if match else {}
        # 单项旧模型可能直接返回 {queries: [...]}，继续兼容但仍受三项上限。
        if "queries" in value and len(items) == 1:
            value = {items[0][0]: value}
        result: dict[str, list[str]] = {}
        for item_id, _ in items[:4]:
            rows = (value.get(item_id) or {}).get("queries") or []
            result[item_id] = [" ".join(str(row.get(key) or "") for key in ("title", "year")).strip() for row in rows if isinstance(row, dict) and row.get("title")][:3]
        return result


class GovernorService:
    def __init__(self, data_path: Path, adapter: MoviePilotAdapter | None = None):
        self.ledger = Ledger(data_path / "governor-v5.sqlite3")
        self.ledger.execute("UPDATE jobs SET status='interrupted',phase='INTERRUPTED',current='宿主上次退出时任务未完成',finished_at=? WHERE status='running'", (utcnow(),))
        self.adapter = adapter or MoviePilotAdapter()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._lock = threading.RLock()

    def start(self, mode: str = "incremental", object_ids: list[str] | None = None) -> dict[str, Any]:
        if mode == "cancel":
            self._cancel.set()
            job = self.ledger.current_job()
            if job and job["status"] == "running":
                self.ledger.update_job(job["id"], cancel_requested=1, current="停止领取下一部作品；正在等待当前 MoviePilot 调用返回")
            return self.status()
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._cancel.clear()
            job_id = self.ledger.begin_job(mode)
            self._thread = threading.Thread(target=self._run, args=(job_id, mode, object_ids), name="MediaGovernor-v5", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self) -> bool:
        self._cancel.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        return not bool(thread and thread.is_alive())

    def _cancelled(self, job_id: str) -> bool:
        row = self.ledger.one("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,))
        return self._cancel.is_set() or bool(row and row["cancel_requested"])

    def _check_cancelled(self, job_id: str) -> None:
        if self._cancelled(job_id):
            raise AuditCancelled()

    def _readonly_call(self, job_id: str, label: str, function: Any, *args: Any, timeout: int = MOVIEPILOT_TIMEOUT_SECONDS) -> Any:
        """让不可中断的宿主只读调用具备可取消等待和统一期限。

        Python 不能安全杀死正在执行的同步线程，因此取消或超时后只丢弃它的
        返回值。helper 不接触账本，也不执行媒体写入；媒体重建永远不走这里。
        """
        self._check_cancelled(job_id)
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["value"] = function(*args)
            except BaseException as error:  # noqa: BLE001 - 原异常要回到所属作品
                outcome["error"] = error
            finally:
                completed.set()

        threading.Thread(target=invoke, name=f"MediaGovernor-read-{label}", daemon=True).start()
        deadline = time.monotonic() + timeout
        while not completed.wait(0.1):
            if self._cancel.is_set():
                raise AuditCancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{label}超过 {timeout} 秒仍未返回")
        self._check_cancelled(job_id)
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def _readonly_many(self, job_id: str, label: str, calls: list[tuple[Any, tuple[Any, ...]]], *, timeout: int = MOVIEPILOT_TIMEOUT_SECONDS, concurrency: int = 8) -> list[Any]:
        """并发执行一组彼此独立的只读探针；结果顺序与输入一致。"""
        results: list[Any] = []
        for offset in range(0, len(calls), concurrency):
            self._check_cancelled(job_id)
            chunk = calls[offset:offset + concurrency]
            outcomes: list[dict[str, Any]] = [{} for _ in chunk]
            completed = [threading.Event() for _ in chunk]

            def invoke(index: int, function: Any, args: tuple[Any, ...], batch_outcomes: list[dict[str, Any]] = outcomes, batch_completed: list[threading.Event] = completed) -> None:
                try:
                    batch_outcomes[index]["value"] = function(*args)
                except BaseException as error:  # noqa: BLE001 - 调用方决定单项如何降级
                    batch_outcomes[index]["error"] = error
                finally:
                    batch_completed[index].set()

            for index, (function, args) in enumerate(chunk):
                threading.Thread(target=invoke, args=(index, function, args), name=f"MediaGovernor-read-{label}-{index}", daemon=True).start()
            deadline = time.monotonic() + timeout
            while not all(event.is_set() for event in completed):
                if self._cancel.is_set():
                    raise AuditCancelled()
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
            self._check_cancelled(job_id)
            for event, outcome in zip(completed, outcomes):
                if not event.is_set():
                    results.append(TimeoutError(f"{label}超过 {timeout} 秒仍未返回"))
                elif "error" in outcome:
                    results.append(outcome["error"])
                else:
                    results.append(outcome.get("value"))
        return results

    def mark_dirty(self, _event: Any = None) -> None:
        self.ledger.execute("UPDATE objects SET dirty=1")

    def _walk(self, job_id: str, root: dict[str, Any], errors: list[dict[str, str]], max_nodes: int = 100000) -> list[dict[str, Any]]:
        if root.get("type") == "file":
            return [root]
        queue, rows, seen = deque([root]), [], set()
        while queue and len(rows) < max_nodes:
            self._check_cancelled(job_id)
            current = queue.popleft()
            key = f"{current.get('storage') or 'local'}:{normal_path(current.get('path'))}"
            if key in seen:
                continue
            seen.add(key)
            try:
                children = self._readonly_call(job_id, "目录读取", self.adapter.list_dir, current)
            except AuditCancelled:
                raise
            except Exception as error:  # noqa: BLE001 - 单目录失败必须隔离并进入证据
                errors.append({"path": str(current.get("path") or ""), "error": str(error)[:240]})
                continue
            for child in children:
                rows.append(child)
                if child.get("type") == "dir" and item_name(child).casefold() not in DISC_DIRECTORIES:
                    queue.append(child)
        if queue:
            errors.append({"path": str(root.get("path") or ""), "error": f"目录项超过安全上限 {max_nodes}，本轮没有读完整"})
        return rows

    def _discover(self, job_id: str) -> Inventory:
        self.ledger.update_job(job_id, phase="INVENTORY", current="读取下载目录配置")
        errors: list[dict[str, str]] = []
        download_roots = self._readonly_call(job_id, "下载目录配置读取", self.adapter.directories, "download")
        library_roots = self._readonly_call(job_id, "媒体库目录配置读取", self.adapter.directories, "library")
        if not download_roots:
            raise RuntimeError("MoviePilot 没有可用的下载目录配置；已拒绝空路径或容器根目录")
        if not library_roots:
            raise RuntimeError("MoviePilot 没有可用的媒体库目录配置")
        histories = self._readonly_call(job_id, "整理历史读取", self.adapter.histories)
        objects: list[dict[str, Any]] = []
        self.ledger.update_job(job_id, total=len(download_roots), done=0, current="准备读取下载目录")
        for root_index, root in enumerate(download_roots, 1):
            self._check_cancelled(job_id)
            self.ledger.update_job(job_id, current=f"读取下载目录 {root_index}/{len(download_roots)}")
            try:
                tops = self._readonly_call(job_id, "下载目录读取", self.adapter.list_dir, root)
            except AuditCancelled:
                raise
            except Exception as error:  # noqa: BLE001 - 单目录失败必须隔离并进入证据
                errors.append({"path": str(root.get("path") or ""), "error": str(error)[:240]})
                obj = {"id": stable_id(root.get("storage") or "local", normal_path(root.get("path")), "read-error"), "label": "下载目录读取失败", "root": root, "entries": [], "complete": False, "group_key": "read-error", "preview_sources": []}
                obj["fingerprint"] = fingerprint([root])
                objects.append(obj)
                self.ledger.update_job(job_id, done=root_index)
                continue
            for top in tops:
                if is_sample(top):
                    continue
                entries = self._walk(job_id, top, errors)
                partitions = partition_entries(top, entries, histories)
                if not partitions and not any(item_name(row).casefold() in DISC_DIRECTORIES for row in entries if row.get("type") == "dir"):
                    continue
                complete = not any(under(error["path"], top.get("path")) for error in errors)
                for partition in partitions or [{"group_key": "disc", "label": item_name(top), "root": top, "entries": entries, "histories": []}]:
                    preview_sources = [top] if len(partitions) <= 1 else [row for row in partition["entries"] if is_media_file(row)]
                    obj = {
                        "id": stable_id(top.get("storage") or "local", normal_path(top.get("path")), partition["group_key"]),
                        "label": partition["label"], "root": top, "entries": partition["entries"],
                        "complete": complete, "group_key": partition["group_key"], "preview_sources": preview_sources,
                    }
                    obj["fingerprint"] = fingerprint([top, *partition["entries"]])
                    objects.append(obj)
            self.ledger.update_job(job_id, done=root_index)
        return Inventory(objects, library_roots, histories, errors)

    @staticmethod
    def _evidence(obj: dict[str, Any]) -> dict[str, Any]:
        names = [item_name(row)[:120] for row in obj.get("entries") or []]
        return {"root_name": item_name(obj.get("root") or {}), "file_count": len(names), "names": names[:60], "episodes": sorted({match.group(0).upper() for name in names if (match := EPISODE_PATTERN.search(name))})[:80]}

    @staticmethod
    def _histories_for(obj: dict[str, Any], histories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources = {normal_path(row.get("path")) for row in obj.get("entries") or []}
        return [row for row in histories if normal_path(history_source(row)) in sources]

    def _resolve_identity(self, obj: dict[str, Any], histories: list[dict[str, Any]], queries: list[str] | None = None, allow_ai: bool = True, force: bool = False, job_id: str | None = None) -> tuple[str, dict[str, Any], list[dict[str, Any]], str]:
        saved = self.ledger.one("SELECT * FROM identities WHERE object_id=?", (obj["id"],))
        if saved and saved["state"] == "confirmed" and saved["fingerprint"] == obj["fingerprint"] and (not force or saved["provenance"] == "user_confirmed"):
            return "confirmed", json.loads(saved["identity_json"]), json.loads(saved["candidates_json"]), saved["provenance"]
        if saved and saved["state"] == "candidate" and saved["fingerprint"] == obj["fingerprint"] and not force:
            return "candidate", {}, json.loads(saved["candidates_json"]), saved["provenance"]
        history_candidates = {identity_key(value): value for row in histories if identity_key(value := history_identity(row))}
        native: dict[str, Any] = {}
        try:
            path = str(obj["root"].get("path") or "")
            native = self._readonly_call(job_id, "作品识别", self.adapter.recognize, path) if job_id else self.adapter.recognize(path)
        except AuditCancelled:
            raise
        except Exception:  # noqa: BLE001 - 原生识别失败会降级为待确认
            native = {}
        candidates = list(history_candidates.values())
        if identity_key(native):
            candidates = [native, *[row for row in candidates if identity_key(row) != identity_key(native)]]
        if identity_key(native) and len(history_candidates) == 1 and identity_key(native) in history_candidates:
            result = {**history_candidates[identity_key(native)], **{key: value for key, value in native.items() if value}}
            return "confirmed", result, candidates, "native_and_history_agree"
        if not identity_key(native) or (history_candidates and identity_key(native) not in history_candidates):
            try:
                if queries is None and allow_ai:
                    selected_queries = self._readonly_call(job_id, "智能识别", self.adapter.ai_queries, self._evidence(obj), timeout=AI_TIMEOUT_SECONDS) if job_id else self.adapter.ai_queries(self._evidence(obj))
                else:
                    selected_queries = queries or []
                for query in selected_queries:
                    rows = self._readonly_call(job_id, "候选搜索", self.adapter.search, query, timeout=SEARCH_TIMEOUT_SECONDS) if job_id else self.adapter.search(query)
                    for candidate in rows:
                        if identity_key(candidate) and all(identity_key(candidate) != identity_key(row) for row in candidates):
                            candidates.append(candidate)
            except AuditCancelled:
                raise
            except Exception:  # noqa: BLE001,S110 - AI 是可弃权候选源
                pass
        return "candidate", {}, candidates[:12], "needs_user_confirmation"

    @staticmethod
    def _preview_items(preview: dict[str, Any]) -> list[dict[str, Any]]:
        return [row for row in preview.get("items") or [] if isinstance(row, dict)]

    def _official_preview(self, obj: dict[str, Any], identity: dict[str, Any], job_id: str | None = None) -> dict[str, Any]:
        sources = obj.get("preview_sources") or [obj.get("root") or {}]
        items: list[dict[str, Any]] = []
        messages: list[str] = []
        for source in sources:
            value = self._readonly_call(job_id, "官方预览", self.adapter.preview, source, identity) if job_id else self.adapter.preview(source, identity)
            items.extend(self._preview_items(value))
            if value.get("message"):
                messages.append(str(value["message"]))
        # 同一文件可能因附加文件同步被多次带出，以 source+target 去重。
        unique = list({(normal_path(row.get("source")), normal_path(row.get("target"))): row for row in items}.values())
        failed = len([row for row in unique if not row.get("success", True)])
        return {"summary": {"total": len(unique), "success": len(unique) - failed, "failed": failed}, "items": unique, "message": "；".join(messages[:3])}

    def _findings(self, obj: dict[str, Any], histories: list[dict[str, Any]], identity_state: str, identity: dict[str, Any], preview: dict[str, Any], inventory: Inventory, job_id: str | None = None) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        if not obj.get("complete"):
            return [{"kind": "read_error", "reason": ISSUE_LABELS["read_error"], "evidence": {"stage": "source_inventory"}}]
        latest = latest_histories(histories)
        failed = [row for row in latest.values() if not bool(row.get("status"))]
        if failed:
            reasons = [str(row.get("errmsg") or "MoviePilot 没有建立硬链接") for row in failed]
            findings.append({"kind": "native_failure", "reason": f"原生整理失败：{len(failed)} 个文件；{reasons[0][:120]}", "evidence": {"history_ids": [row.get("id") for row in failed]}})
        if identity_state != "confirmed":
            findings.append({"kind": "identity_confirmation", "reason": "文件线索与历史身份不能相互证明，请确认正确作品", "evidence": {"candidate_count": 0}})
            return findings
        preview_items = self._preview_items(preview)
        summary = preview.get("summary") if isinstance(preview.get("summary"), dict) else {}
        if not preview_items or int(summary.get("failed") or 0) > 0:
            findings.append({"kind": "preview_error", "reason": str(preview.get("message") or ISSUE_LABELS["preview_error"])[:200], "evidence": {"summary": summary}})
            return findings
        false_kinds: list[str] = []
        manual_changes = 0
        native_missing = 0
        comparisons: list[dict[str, Any]] = []
        contexts: list[dict[str, Any]] = []
        probe_calls: list[tuple[Any, tuple[Any, ...]]] = []
        probe_slots: list[tuple[int, str]] = []
        for index, row in enumerate(preview_items):
            source = normal_path(row.get("source"))
            expected = str(row.get("target") or "")
            current_history = latest.get(source)
            current = str((current_history or {}).get("dest") or model_dict((current_history or {}).get("dest_fileitem")).get("path") or "")
            current_storage = str((current_history or {}).get("dest_storage") or model_dict((current_history or {}).get("dest_fileitem")).get("storage") or "local")
            contexts.append({"row": row, "source": source, "expected": expected, "current_history": current_history, "current": current, "current_storage": current_storage})
            if job_id and expected:
                probe_calls.append((self.adapter.get_item, (str(row.get("target_storage") or "local"), expected)))
                probe_slots.append((index, "expected_item"))
            if job_id and current:
                probe_calls.append((self.adapter.get_item, (current_storage, current)))
                probe_slots.append((index, "current_item"))
        if job_id and probe_calls:
            probe_results = self._readonly_many(job_id, "硬链接读取", probe_calls)
            for (index, key), value in zip(probe_slots, probe_results):
                contexts[index][key] = value

        for context in contexts:
            row = context["row"]
            expected = context["expected"]
            current_history = context["current_history"]
            current = context["current"]
            try:
                expected_item = context.get("expected_item") if job_id else (self.adapter.get_item(str(row.get("target_storage") or "local"), expected) if expected else None)
                current_item = context.get("current_item") if job_id else (self.adapter.get_item(context["current_storage"], current) if current else None)
                if isinstance(expected_item, BaseException):
                    raise expected_item
                if isinstance(current_item, BaseException):
                    raise current_item
            except AuditCancelled:
                raise
            except Exception as error:  # noqa: BLE001 - 存储 provider 异常必须形成读取错误
                findings.append({"kind": "read_error", "reason": f"媒体库当前状态读取失败：{str(error)[:160]}", "evidence": {"stage": "target_probe"}})
                return findings
            expected_present = bool(expected_item)
            current_present = bool(current_item)
            comparisons.append({"source": row.get("source"), "current": current, "expected": expected, "current_present": current_present, "expected_present": expected_present})
            intended_category = expected_category(identity)
            preview_category = root_category(expected, inventory.library_roots)
            current_category = root_category(current, inventory.library_roots)
            if intended_category not in {"unknown", "other"} and preview_category not in {"other", intended_category}:
                if current_present and current_category == intended_category:
                    continue
                if current_present:
                    findings.append({"kind": "preview_error", "reason": "MoviePilot 预览目录与已确认作品类型矛盾，已停止判定", "evidence": {"comparisons": comparisons}})
                    return findings
            if current_present and normal_path(current) != normal_path(expected):
                false_kinds.append(classify_false_success(current, expected, identity, inventory.library_roots))
            elif expected_present:
                continue
            elif current_history and bool(current_history.get("status")):
                manual_changes += 1
            else:
                native_missing += 1
        if false_kinds:
            labels = [ISSUE_LABELS[kind] for kind in dict.fromkeys(false_kinds)]
            findings.append({"kind": "false_success", "reason": "假成功：" + "、".join(labels), "evidence": {"issue_kinds": list(dict.fromkeys(false_kinds)), "comparisons": comparisons}})
        if native_missing and not any(row["kind"] == "native_failure" for row in findings):
            findings.append({"kind": "native_failure", "reason": f"原生整理失败：{native_missing} 个应有硬链接不存在", "evidence": {"comparisons": comparisons}})
        if manual_changes:
            findings.append({"kind": "manual_change", "reason": f"{manual_changes} 个历史成功文件目前不存在，无法判断是主动删除还是误删", "evidence": {"comparisons": comparisons}})
        return findings

    def _process(self, job_id: str, obj: dict[str, Any], inventory: Inventory, resolved: tuple[str, dict[str, Any], list[dict[str, Any]], str] | None = None, force_preview: bool = False) -> None:
        histories = self._histories_for(obj, inventory.histories)
        self._check_cancelled(job_id)
        state, identity, candidates, provenance = resolved or self._resolve_identity(obj, histories, job_id=job_id)
        self.ledger.save_identity(obj["id"], state, obj["fingerprint"], identity, candidates, provenance)
        preview: dict[str, Any] = {}
        if state == "confirmed":
            config_fp = fingerprint(inventory.library_roots)
            basis = stable_id(obj["fingerprint"], identity_key(identity), config_fp)
            cached = self.ledger.one("SELECT payload_json FROM observations WHERE object_id=? AND kind='preview'", (obj["id"],))
            cached_payload = json.loads(cached["payload_json"]) if cached else {}
            if cached_payload.get("_basis") == basis and not force_preview:
                preview = cached_payload
            else:
                try:
                    preview = self._official_preview(obj, identity, job_id)
                    preview["_basis"] = basis
                except AuditCancelled:
                    raise
                except Exception as error:  # noqa: BLE001 - 官方预览失败属于单项结果
                    preview = {"_basis": basis, "summary": {"total": 0, "success": 0, "failed": 1}, "items": [], "message": str(error)[:240]}
        self.ledger.save_observation(obj["id"], "source", bool(obj.get("complete")), obj["fingerprint"], {"object": obj, "histories": histories})
        self.ledger.save_observation(obj["id"], "preview", bool(preview and not (preview.get("summary") or {}).get("failed")), fingerprint(self._preview_items(preview)), preview)
        self._check_cancelled(job_id)
        findings = self._findings(obj, histories, state, identity, preview, inventory, job_id)
        for finding in findings:
            if finding["kind"] == "identity_confirmation":
                finding["evidence"]["candidate_count"] = len(candidates)
        self.ledger.replace_findings(obj["id"], findings)

    def _finish_cancelled(self, job_id: str, message: str = "已停止，已完成结果仍然保留") -> None:
        row = self.ledger.one("SELECT done FROM jobs WHERE id=?", (job_id,)) or {}
        self.ledger.update_job(job_id, status="cancelled", phase="CANCELLED", done=int(row.get("done") or 0), current=message, finished_at=utcnow())

    def _run(self, job_id: str, mode: str, object_ids: list[str] | None) -> None:
        try:
            inventory = self._discover(job_id)
            self._check_cancelled(job_id)
            library_fp = fingerprint(inventory.library_roots)
            self.ledger.save_observation("__library__", "configuration", True, library_fp, {"roots": inventory.library_roots})
            current_ids = {obj["id"] for obj in inventory.objects}
            for obj in inventory.objects:
                self.ledger.upsert_object(obj)
            if current_ids and not inventory.errors:
                placeholders = ",".join("?" for _ in current_ids)
                self.ledger.execute(f"UPDATE objects SET status='REMOVED',dirty=0 WHERE id NOT IN ({placeholders})", tuple(current_ids))
                self.ledger.execute(f"UPDATE findings SET status='resolved' WHERE object_id NOT IN ({placeholders})", tuple(current_ids))
            elif not current_ids and not inventory.errors:
                self.ledger.execute("UPDATE objects SET status='REMOVED',dirty=0")
                self.ledger.execute("UPDATE findings SET status='resolved' WHERE status='open'")
            # 增量运行仍逐项做廉价的目标存在性探针，以发现用户在文件管理器中的删除/移动；
            # 身份和官方预览在指纹、规则与目录配置未变化时复用，不再次消耗 AI 或重算路径。
            selected = list(inventory.objects)
            if object_ids:
                selected = [obj for obj in selected if obj["id"] in object_ids]
            self.ledger.update_job(job_id, phase="RECONCILING", total=len(selected), done=0, current="准备逐批核对作品")
            completed = 0
            for offset in range(0, len(selected), 4):
                self._check_cancelled(job_id)
                batch = selected[offset:offset + 4]
                resolved: dict[str, tuple[str, dict[str, Any], list[dict[str, Any]], str]] = {}
                needs_queries: list[dict[str, Any]] = []
                for obj in batch:
                    self._check_cancelled(job_id)
                    self.ledger.update_job(job_id, phase="IDENTIFYING", current=f"识别：{obj['label']}", done=completed)
                    if not obj.get("complete"):
                        resolved[obj["id"]] = ("candidate", {}, [], "source_incomplete")
                        continue
                    saved = self.ledger.one("SELECT state,fingerprint FROM identities WHERE object_id=?", (obj["id"],))
                    reused_candidate = bool(mode != "full" and saved and saved["state"] == "candidate" and saved["fingerprint"] == obj["fingerprint"])
                    histories = self._histories_for(obj, inventory.histories)
                    probe = self._resolve_identity(obj, histories, allow_ai=False, force=mode == "full", job_id=job_id)
                    resolved[obj["id"]] = probe
                    if probe[0] != "confirmed" and not reused_candidate:
                        needs_queries.append(obj)
                query_map: dict[str, list[str]] = {}
                if needs_queries:
                    self.ledger.update_job(job_id, phase="IDENTIFYING", current=f"智能识别本批 {len(needs_queries)} 部作品", done=completed)
                    try:
                        query_map = self._readonly_call(
                            job_id, "智能识别", self.adapter.ai_queries_batch,
                            [(obj["id"], self._evidence(obj)) for obj in needs_queries], timeout=AI_TIMEOUT_SECONDS,
                        )
                    except AuditCancelled:
                        raise
                    except Exception:  # noqa: BLE001 - AI 批次可整体弃权
                        query_map = {}
                search_slots: list[str] = []
                search_calls: list[tuple[Any, tuple[Any, ...]]] = []
                for obj in needs_queries:
                    for query in query_map.get(obj["id"], [])[:3]:
                        search_slots.append(obj["id"])
                        search_calls.append((self.adapter.search, (query,)))
                search_results = self._readonly_many(job_id, "候选搜索", search_calls, timeout=SEARCH_TIMEOUT_SECONDS, concurrency=4) if search_calls else []
                for object_id, search_rows in zip(search_slots, search_results):
                    if isinstance(search_rows, BaseException):
                        continue
                    state, identity, candidates, provenance = resolved[object_id]
                    for candidate in search_rows or []:
                        if identity_key(candidate) and all(identity_key(candidate) != identity_key(row) for row in candidates):
                            candidates.append(candidate)
                    resolved[object_id] = (state, identity, candidates[:12], provenance)
                for obj in batch:
                    self._check_cancelled(job_id)
                    self.ledger.update_job(job_id, phase="RECONCILING", current=f"核对：{obj['label']}", done=completed)
                    try:
                        self._process(job_id, obj, inventory, resolved.get(obj["id"]), force_preview=mode == "full")
                    except AuditCancelled:
                        raise
                    except Exception as error:  # noqa: BLE001 - 一部失败不能终止其余作品
                        self.ledger.replace_findings(obj["id"], [{"kind": "read_error", "reason": f"核对阶段失败：{str(error)[:180]}", "evidence": {"stage": "reconciliation"}}])
                    completed += 1
                    self.ledger.update_job(job_id, done=completed)
            self.ledger.update_job(job_id, status="completed", phase="DONE", done=len(selected), current="检查完成", finished_at=utcnow())
        except AuditCancelled:
            self._finish_cancelled(job_id)
        except Exception as error:  # noqa: BLE001 - 后台任务边界必须持久化失败原因
            self.ledger.update_job(job_id, status="failed", phase="FAILED", error=str(error)[:500], current="检查失败", finished_at=utcnow())

    def status(self) -> dict[str, Any]:
        job = self.ledger.current_job() or {"status": "idle", "phase": "IDLE", "total": 0, "done": 0, "current": "尚未检查", "error": ""}
        counts = {row["kind"]: row["count"] for row in self.ledger.query("SELECT kind,COUNT(*) count FROM findings WHERE status='open' GROUP BY kind")}
        return {"job": job, "counts": counts, "objects": (self.ledger.one("SELECT COUNT(*) count FROM objects WHERE status!='REMOVED'") or {}).get("count", 0)}

    def findings(self) -> dict[str, Any]:
        rows = self.ledger.query("SELECT f.*,o.label FROM findings f JOIN objects o ON o.id=f.object_id WHERE f.status='open' ORDER BY f.kind,o.label")
        public = [{"id": row["id"], "object_id": row["object_id"], "title": row["label"], "kind": row["kind"], "reason": row["reason"]} for row in rows]
        problems = [row for row in public if row["kind"] in {"native_failure", "false_success"}]
        confirmations = [row for row in public if row["kind"] in {"identity_confirmation", "manual_change"}]
        errors = [row for row in public if row["kind"] in {"read_error", "preview_error"}]
        return {"status": self.status(), "problems": problems, "confirmations": confirmations, "errors": errors}

    def detail(self, object_id: str) -> dict[str, Any] | None:
        obj = self.ledger.one("SELECT * FROM objects WHERE id=?", (object_id,))
        if not obj:
            return None
        identity = self.ledger.one("SELECT * FROM identities WHERE object_id=?", (object_id,)) or {}
        source = self.ledger.one("SELECT * FROM observations WHERE object_id=? AND kind='source'", (object_id,)) or {}
        preview = self.ledger.one("SELECT * FROM observations WHERE object_id=? AND kind='preview'", (object_id,)) or {}
        return {
            "id": object_id, "title": obj["label"], "fingerprint": obj["fingerprint"],
            "source": json.loads(source.get("payload_json") or "{}"),
            "identity_state": identity.get("state") or "candidate",
            "identity": json.loads(identity.get("identity_json") or "{}"),
            "candidates": json.loads(identity.get("candidates_json") or "[]"),
            "provenance": identity.get("provenance") or "",
            "preview": json.loads(preview.get("payload_json") or "{}"),
        }

    def confirm_identity(self, object_id: str, candidate_key: str) -> dict[str, Any]:
        detail = self.detail(object_id)
        if not detail:
            raise ValueError("作品不存在")
        candidate = next((row for row in detail["candidates"] if identity_key(row) == candidate_key), None)
        if not candidate:
            raise ValueError("候选已经过期，请重新检查")
        self.ledger.save_identity(object_id, "confirmed", detail["fingerprint"], candidate, detail["candidates"], "user_confirmed")
        self.ledger.execute("UPDATE objects SET dirty=1 WHERE id=?", (object_id,))
        return self.start("incremental", [object_id])

    def repair_preview(self, object_id: str) -> dict[str, Any]:
        detail = self.detail(object_id)
        if not detail or detail["identity_state"] != "confirmed":
            raise ValueError("必须先确认作品身份")
        source_payload = detail["source"]
        obj = source_payload.get("object") or {}
        histories = source_payload.get("histories") or []
        preview = self._official_preview(obj, detail["identity"])
        latest = latest_histories(histories)
        library_config = self.ledger.one("SELECT payload_json FROM observations WHERE object_id='__library__' AND kind='configuration'") or {}
        library_roots = json.loads(library_config.get("payload_json") or "{}").get("roots") or []
        entries = []
        for row in self._preview_items(preview):
            history = latest.get(normal_path(row.get("source")))
            current_path = str((history or {}).get("dest") or model_dict((history or {}).get("dest_fileitem")).get("path") or "")
            source_item = next((item for item in obj.get("entries") or [] if normal_path(item.get("path")) == normal_path(row.get("source"))), obj.get("root"))
            current_item = model_dict((history or {}).get("dest_fileitem")) or ({"path": current_path, "storage": (history or {}).get("dest_storage") or "local", "type": "file"} if current_path else None)
            # 只有“成功历史明确指向、且与新目标不同”的旧目标才允许交给官方 cleanup 参数。
            attributable = bool(history and history.get("status") and current_path and normal_path(current_path) != normal_path(row.get("target")))
            if attributable and not any(under(current_path, root.get("path")) for root in library_roots):
                attributable = False
            entries.append({
                "source": {key: source_item.get(key) for key in ("path", "storage", "type", "name", "size", "modify_time") if source_item.get(key) is not None},
                "current": current_path, "current_item": current_item if attributable else None,
                "expected": row.get("target"), "target_storage": row.get("target_storage") or "local",
                "history_id": (history or {}).get("id"), "cleanup_attributable": attributable,
            })
        if not entries or any(not row.get("expected") for row in entries):
            raise ValueError("官方预览没有给出完整目标，不能执行修复")
        live = self._repair_live_state(entries)
        token = stable_id(object_id, detail["fingerprint"], identity_key(detail["identity"]), json_text(entries, sort_keys=True), json_text(live, sort_keys=True))
        plan = {"token": token, "object_fingerprint": detail["fingerprint"], "identity": detail["identity"], "entries": entries, "live": live, "created_at": utcnow()}
        self.ledger.save_observation(object_id, "repair_plan", True, token, plan)
        return plan

    def _repair_live_state(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        state: list[dict[str, Any]] = []
        for entry in entries:
            source = entry["source"]
            source_item = self.adapter.get_item(str(source.get("storage") or "local"), str(source.get("path") or ""))
            current_item = None
            if entry.get("current"):
                storage = str((entry.get("current_item") or {}).get("storage") or "local")
                current_item = self.adapter.get_item(storage, str(entry["current"]))
            target_item = self.adapter.get_item(str(entry.get("target_storage") or "local"), str(entry.get("expected") or ""))
            state.append({
                "source": fingerprint([source_item]) if source_item else "missing",
                "current": fingerprint([current_item]) if current_item else "missing",
                "expected": fingerprint([target_item]) if target_item else "missing",
            })
        return state

    def repair_execute(self, object_id: str, token: str) -> dict[str, Any]:
        row = self.ledger.one("SELECT * FROM observations WHERE object_id=? AND kind='repair_plan'", (object_id,))
        detail = self.detail(object_id)
        if not row or not detail or row["fingerprint"] != token:
            raise ValueError("预览已经过期，请重新生成")
        plan = json.loads(row["payload_json"])
        if plan.get("object_fingerprint") != detail["fingerprint"]:
            raise ValueError("原文件已经变化，请重新检查")
        # 第二次调用官方预览，并重新读取源、旧目标和新目标；任何变化都使确认失效。
        obj = (detail.get("source") or {}).get("object") or {}
        fresh_preview = self._official_preview(obj, plan["identity"])
        fresh_targets = [(normal_path(item.get("source")), normal_path(item.get("target"))) for item in self._preview_items(fresh_preview)]
        frozen_targets = [(normal_path(item.get("source", {}).get("path")), normal_path(item.get("expected"))) for item in plan.get("entries") or []]
        if fresh_targets != frozen_targets or self._repair_live_state(plan.get("entries") or []) != plan.get("live"):
            raise ValueError("文件或官方预览已经变化，请重新生成预览")
        for entry in plan.get("entries") or []:
            self.adapter.rebuild(entry, plan["identity"])
        verification = self._repair_live_state(plan.get("entries") or [])
        for entry, state in zip(plan.get("entries") or [], verification):
            if state["expected"] == "missing":
                raise RuntimeError("MoviePilot 返回成功，但修复后的硬链接不存在；问题仍会保留")
            if entry.get("cleanup_attributable") and normal_path(entry.get("current")) != normal_path(entry.get("expected")) and state["current"] != "missing":
                raise RuntimeError("新硬链接已建立，但可归因的旧硬链接仍存在；问题仍会保留")
        self.ledger.execute("DELETE FROM observations WHERE object_id=? AND kind='repair_plan'", (object_id,))
        self.ledger.execute("UPDATE objects SET dirty=1 WHERE id=?", (object_id,))
        self.start("incremental", [object_id])
        return {"accepted": True, "message": "MoviePilot 已完成重建，正在只复核这一部作品"}
