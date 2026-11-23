"""已看列表与删除的编排：定时读极影视已看、跟踪缓冲期、组装版本、预览/执行删除、自动删除。

外部能力全部注入（MP 记录查询、qB、删除、极影视刷新、通知、持久化），单测里用假的。
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence

from . import pathmap
from . import watched as W
from .cli import Cli, CliError


@dataclass
class WatchSettings:
    enabled: bool = False  # 定时读已看（只读）
    auto_mode: str = W.MODE_NONE  # 自动删除选项：none / library / full
    buffer_days: float = 7.0
    sync_minutes: int = 60
    auto_since: float = 0.0  # 打开自动删除的时间；只有这之后才首次发现已看的才会被自动删除

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "WatchSettings":
        config = config or {}
        mode = str(config.get("watched_auto_mode") or W.MODE_NONE)
        try:
            days = float(config.get("watched_buffer_days", 7))
        except (TypeError, ValueError):
            days = 7.0
        try:
            minutes = int(config.get("watched_sync_minutes", 60))
        except (TypeError, ValueError):
            minutes = 60
        try:
            since = float(config.get("watched_auto_since") or 0)
        except (TypeError, ValueError):
            since = 0.0
        return cls(enabled=bool(config.get("watched_enabled", False)),
                   auto_mode=mode if mode in W.MODES else W.MODE_NONE,
                   buffer_days=max(1.0, min(365.0, days)),
                   sync_minutes=max(10, min(1440, minutes)),
                   auto_since=since)

    def stamped(self, previous: "WatchSettings", now: float) -> "WatchSettings":
        """保存配置时：从「不删」改成删除选项（或换了选项）就重新记开启时间；关掉则清零。"""
        if self.auto_mode == W.MODE_NONE:
            self.auto_since = 0.0
        elif previous.auto_mode != self.auto_mode or not previous.auto_since:
            self.auto_since = now
        else:
            self.auto_since = previous.auto_since
        return self

    def to_config(self) -> Dict[str, Any]:
        return {"watched_enabled": self.enabled, "watched_auto_mode": self.auto_mode,
                "watched_buffer_days": self.buffer_days, "watched_sync_minutes": self.sync_minutes,
                "watched_auto_since": self.auto_since}


@dataclass
class WatchHost:
    """MP / qB 侧能力。"""

    transfers_by_tmdb: Callable[[int, str], List[Dict[str, Any]]]  # (tmdb_id, movie/season)
    downloads_by_tmdb: Callable[[int, str], List[Dict[str, Any]]]
    torrents: Callable[[], List[W.TorrentInfo]]
    torrent_files: Callable[[W.TorrentInfo], List[str]]
    roots: Callable[[], W.Roots]
    exec_host: Callable[[], W.Host]
    rescan: Callable[[Sequence[str], str], List[Dict[str, Any]]]  # 容器路径 -> 刷新记录（同步等终态）


class WatchService:
    HISTORY_LIMIT = 100

    def __init__(self, cli: Cli, settings: WatchSettings, host: WatchHost, *,
                 mappings: Callable[[], List[pathmap.Mapping]], log: Any,
                 notify: Callable[[str, str], None],
                 load: Callable[[str], Any], save: Callable[[str, Any], None],
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> None:
        self.cli = cli
        self.settings = settings
        self.host = host
        self._mappings = mappings
        self.log = log
        self._notify = notify
        self._save = save
        self._clock = clock
        self._sleep = sleep
        self.state: Dict[str, Dict[str, Any]] = load("watched_state") or {}
        self.meta: Dict[str, Any] = load("watched_meta") or {}
        self.history: Deque[Dict[str, Any]] = deque(load("watched_history") or [], maxlen=self.HISTORY_LIMIT)
        self._plans: Dict[str, W.Plan] = {}
        self._lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._index: Optional[W.InodeIndex] = None

    # ------------------------------------------------------------------ 读已看
    def sync(self) -> Dict[str, Any]:
        """读一次极影视已看，更新跟踪表。只读。"""
        now = self._clock()
        entries: List[W.SeenEntry] = []
        zvideo: Dict[str, List[str]] = {}
        errors: List[str] = []
        failed_libs: set = set()
        failed_collections: set = set()
        for lib in self.cli.libraries():
            library_id = str(lib.get("id") or "")
            if not library_id:
                continue
            try:
                rows = self.cli.seen_collections(library_id)
            except CliError as error:
                errors.append(f"{lib.get('name')}: {error}")
                failed_libs.add(library_id)
                continue
            for row in rows:
                cid = str(row.get("collection_id") or "")
                cache: Dict[str, Any] = {}

                def info(cid=cid, cache=cache) -> Dict[str, Any]:
                    if "info" not in cache:
                        cache["info"] = self.cli.collection_info(library_id, cid)
                    return cache["info"]

                def videos(cid=cid, cache=cache) -> Dict[str, Any]:
                    if "videos" not in cache:
                        cache["videos"] = self.cli.collection_videos(library_id, cid)
                    return cache["videos"]

                try:
                    found = W.watched_entries(row, info, videos, library_name=str(lib.get("name") or ""))
                except CliError as error:
                    errors.append(f"{row.get('title')}: {error}")
                    failed_collections.add(cid)
                    continue
                for entry in found:
                    entries.append(entry)
                    try:
                        zvideo[entry.key] = self._zvideo_paths(videos(), entry)
                    except CliError as error:
                        errors.append(f"{row.get('title')} 文件列表: {error}")
        with self._lock:
            # 有分类/专辑读失败时，保留原有对象，避免把读失败误判为取消已看
            keep = [_entry(v) for v in self.state.values()
                    if v.get("library_id") in failed_libs or v.get("collection_id") in failed_collections]
            current = {e.key for e in entries}
            keep = [e for e in keep if e.key not in current]
            state, added, removed = W.track(self.state, entries + keep, now)
            for entry in keep:
                state[entry.key]["stale"] = True  # 这次没能确认仍是已看：保留在列表里，但不自动删
            for key, paths in zvideo.items():
                state[key]["zvideo_files"] = paths
            for key in state:
                state[key].setdefault("zvideo_files", self.state.get(key, {}).get("zvideo_files", []))
            self.state = state
            self.meta.update({"last_sync_at": now, "last_sync_errors": errors, "last_added": added,
                              "last_removed": removed})
            self._persist()
        if added:
            self.log.info(f"极空间影视：新发现已看 {len(added)} 个：{added}")
        if removed:
            self.log.info(f"极空间影视：取消已看 {len(removed)} 个（缓冲期内不删）：{removed}")
        return {"count": len(self.state), "added": added, "removed": removed, "errors": errors}

    def _zvideo_paths(self, videos: Dict[str, Any], entry: W.SeenEntry) -> List[str]:
        mappings = self._mappings()
        result: List[str] = []
        for video in (videos or {}).get("video_list") or []:
            raw = str(video.get("file_path") or "")
            if not raw:
                continue
            local = pathmap.from_zspace(raw, mappings)
            if local and (entry.kind != "season" or W.season_of_path(local) in (None, entry.season)):
                result.append(local)
        return sorted(set(result))

    # ------------------------------------------------------------------ 列表
    def _inode_index(self, roots: W.Roots) -> W.InodeIndex:
        if self._index is None or self._index.roots != roots.library + roots.download:
            self._index = W.InodeIndex(roots.library + roots.download)
        return self._index

    def versions_for(self, key: str, torrents: Optional[List[W.TorrentInfo]] = None,
                     exact: bool = False) -> List[W.Version]:
        item = self.state.get(key)
        if not item:
            raise KeyError("这部片不在已看列表里")
        entry = _entry(item)
        roots = self.host.roots()
        transfers = self.host.transfers_by_tmdb(entry.tmdb_id, entry.kind) if entry.tmdb_id else []
        downloads = self.host.downloads_by_tmdb(entry.tmdb_id, entry.kind) if entry.tmdb_id else []
        if torrents is None:
            torrents = self.host.torrents()
        return W.build_versions(entry, transfers, downloads, torrents, roots, self._inode_index(roots),
                                self.host.torrent_files, zvideo_files=item.get("zvideo_files") or [],
                                exact_links=exact)

    def listing(self) -> Dict[str, Any]:
        now = self._clock()
        torrents = self.host.torrents()
        items: List[Dict[str, Any]] = []
        for key, item in sorted(self.state.items(), key=lambda kv: -float(kv[1].get("first_seen_at") or 0)):
            row = {k: item.get(k) for k in ("key", "title", "kind", "season", "tmdb_id", "library_name",
                                            "first_seen_at", "done_at", "done_mode", "last_error", "year")}
            first = item.get("first_seen_at")
            first = now if first is None else float(first)
            row["due_in_days"] = max(0.0, round(self.settings.buffer_days - (now - first) / 86400, 2))
            try:
                versions = self.versions_for(key, torrents)
                row["versions"] = [_version_dict(v) for v in versions]
                row["total_size"] = sum(v.size for v in versions)
            except Exception as error:  # noqa: BLE001
                row["versions"] = []
                row["error"] = str(error)
            items.append(row)
        return {"items": items, "settings": self.settings.to_config(), "meta": self.meta,
                "modes": [{"value": m, "title": W.MODE_LABELS[m]} for m in W.MODES]}

    # ------------------------------------------------------------------ 预览 / 执行
    def preview(self, key: str, mode: str, version_ids: Optional[Sequence[str]] = None,
                confirm_unknown_season: bool = False) -> Dict[str, Any]:
        """confirm_unknown_season：只给手动删除用（页面上勾选确认），自动删除永远不传。"""
        if self._index:
            self._index.invalidate()  # 预览要最新的目录项
        versions = self.versions_for(key, exact=True)
        item = self.state[key]
        title = _title(item)
        plan = W.make_plan(key, title, versions, mode, version_ids, self.host.roots(), self._clock(),
                           confirm_unknown_season=confirm_unknown_season)
        with self._lock:
            self._plans = {k: v for k, v in self._plans.items() if self._clock() - v.created_at < W.PLAN_TTL}
            self._plans[plan.id] = plan
        return plan.to_dict()

    def execute(self, plan_id: str, trigger: str = "manual") -> Dict[str, Any]:
        with self._lock:
            plan = self._plans.pop(plan_id, None)
        if plan is None:
            raise KeyError("清单不存在或已过期，请重新预览")
        with self._run_lock:
            return self._execute(plan, trigger)

    def _execute(self, plan: W.Plan, trigger: str) -> Dict[str, Any]:
        self.log.info(f"极空间影视：开始删除 {plan.title}（{W.MODE_LABELS[plan.mode]}），"
                      f"{len(plan.actions)} 个文件、{len(plan.torrents)} 个种子，预计腾出 {W.human_size(plan.freed_bytes)}")
        result = W.execute_plan(plan, self.host.exec_host(), self._clock())
        result["trigger"] = trigger
        result["plan"] = plan.to_dict()
        if self._index:
            self._index.invalidate()
        # 极影视：自己有目录监听；再按目录刷新一次并核对条目里不再有这些文件
        if result["status"] != "aborted" and plan.rescan_paths:
            result["zvideo"] = self._refresh_and_check(plan)
        try:
            left = W.leftover(self.versions_for(plan.item_key), plan.mode)
        except Exception:  # noqa: BLE001
            left = ["?"]
        result["left_after"] = left[:50]
        all_versions = not left
        with self._lock:
            item = self.state.get(plan.item_key)
            if item is not None:
                if result["status"] == "done" and all_versions:
                    item["done_at"] = self._clock()
                    item["done_mode"] = plan.mode
                    item.pop("last_error", None)
                elif result["status"] != "done":
                    item["last_error"] = "；".join((result.get("failed") or []) + (result.get("torrents_failed") or []))[:300]
            self.history.appendleft(_compact(result))
            self._persist()
        self.log.info(f"极空间影视：删除结束 {plan.title}：{result['status']}，删除 {len(result['deleted'])} 个文件，"
                      f"腾出 {result['freed_text']}")
        return result

    def _refresh_and_check(self, plan: W.Plan) -> Dict[str, Any]:
        item = self.state.get(plan.item_key) or {}
        deleted_lib = {a.path for a in plan.actions if a.role == "library" and not os.path.lexists(a.path)}
        targets: List[str] = []
        for path in plan.rescan_paths:
            probe = path
            while probe and not os.path.isdir(probe):
                probe = os.path.dirname(probe)
            if probe:
                targets.append(probe)
        info: Dict[str, Any] = {"rescan_targets": sorted(set(targets))}
        try:
            info["rescan"] = self.host.rescan(sorted(set(targets)), f"已看删除：{plan.title}")
        except Exception as error:  # noqa: BLE001
            info["rescan_error"] = str(error)
        try:
            videos = self.cli.collection_videos(str(item.get("library_id")), str(item.get("collection_id")))
            mappings = self._mappings()
            remaining = []
            for video in videos.get("video_list") or []:
                local = pathmap.from_zspace(str(video.get("file_path") or ""), mappings) if video.get("file_path") else None
                if local in deleted_lib:
                    remaining.append(local)
            info["still_in_zvideo"] = remaining
            info["zvideo_versions_left"] = len(videos.get("video_list") or [])
        except CliError as error:
            # 专辑整个没了（全部版本删掉）时接口会报错或返回空，按「已消失」处理
            info["still_in_zvideo"] = []
            info["zvideo_versions_left"] = 0
            info["collection_error"] = str(error)
        return info

    # ------------------------------------------------------------------ 自动
    def run_auto(self) -> Dict[str, Any]:
        """定时任务：读已看；选了删除选项时处理超过缓冲期的。"""
        if not self._run_lock.acquire(blocking=False):
            return {"skipped": "上一次还没跑完"}
        try:
            summary: Dict[str, Any] = {"sync": self.sync(), "results": []}
            mode = self.settings.auto_mode
            if mode == W.MODE_NONE or not self.settings.auto_since:
                return summary
            due = W.due_keys(self.state, self.settings.buffer_days, self._clock(), since=self.settings.auto_since)
            results = []
            for key in due:
                try:
                    plan_dict = self.preview(key, mode, confirm_unknown_season=False)  # 自动删除永远不纳入认不出季号的文件
                    with self._lock:
                        plan = self._plans.pop(plan_dict["id"])
                    if not plan.actions and not plan.torrents:
                        with self._lock:
                            self.state[key]["done_at"] = self._clock()
                            self.state[key]["done_mode"] = mode
                            self.state[key]["last_error"] = "；".join(plan.skipped + plan.warnings)[:300]
                            self._persist()
                        continue
                    results.append(self._execute(plan, "auto"))
                except Exception as error:  # noqa: BLE001
                    self.log.error(f"极空间影视：自动删除 {key} 出错：{error}\n{traceback.format_exc()}")
                    with self._lock:
                        if key in self.state:
                            self.state[key]["last_error"] = str(error)[:300]
                            self._persist()
            summary["results"] = results
            if results:
                self._notify("极空间影视：已看自动删除", W.summarize(results))
            return summary
        finally:
            self._run_lock.release()

    def run_keys(self, keys: Sequence[str], mode: str, confirm_unknown_season: bool = False) -> List[Dict[str, Any]]:
        """只处理指定条目（手动「按选项删除」），不看缓冲期，不碰别的条目。"""
        if mode not in (W.MODE_LIBRARY, W.MODE_FULL):
            raise ValueError("删除选项只能是「只从库里移除」或「真删除」")
        results = []
        with self._run_lock:
            for key in keys:
                if key not in self.state:
                    raise KeyError(f"{key} 不在已看列表里")
            for key in keys:
                plan_dict = self.preview(key, mode, confirm_unknown_season=confirm_unknown_season)
                with self._lock:
                    plan = self._plans.pop(plan_dict["id"])
                results.append(self._execute(plan, "manual"))
        return results

    def reset(self, keys: Sequence[str]) -> List[str]:
        """清掉条目的「已处理」状态（文件恢复后用），首次发现时间不变。"""
        done = []
        with self._lock:
            for key in keys:
                item = self.state.get(key)
                if item:
                    for k in ("done_at", "done_mode", "last_error"):
                        item.pop(k, None)
                    done.append(key)
            self._persist()
        return done

    def notify_manual(self, result: Dict[str, Any]) -> None:
        self._notify("极空间影视：已看手动删除", W.summarize([result]))

    def update_settings(self, settings: WatchSettings) -> None:
        self.settings = settings

    def _persist(self) -> None:
        try:
            self._save("watched_state", self.state)
            self._save("watched_meta", self.meta)
            self._save("watched_history", list(self.history))
        except Exception as error:  # noqa: BLE001
            self.log.warning(f"极空间影视：保存已看数据失败：{error}")


def _entry(item: Dict[str, Any]) -> W.SeenEntry:
    return W.SeenEntry(**{k: item[k] for k in ("library_id", "library_name", "collection_id", "title",
                                               "kind", "tmdb_id", "season", "year")})


def _title(item: Dict[str, Any]) -> str:
    title = str(item.get("title") or "")
    if item.get("kind") == "season" and f"第 {item.get('season')} 季" not in title:
        title += f" 第 {item.get('season')} 季"
    return title


def _version_dict(version: W.Version) -> Dict[str, Any]:
    data = asdict(version)
    data["size"] = version.size
    data["size_text"] = W.human_size(version.size)
    unknown = [f for f in version.files if f.exists and f.season_unknown]
    data["season_unknown_count"] = len(unknown)
    data["season_unknown_size_text"] = W.human_size(sum(f.size for f in unknown))
    return data


def _compact(result: Dict[str, Any]) -> Dict[str, Any]:
    keep = dict(result)
    plan = keep.pop("plan", {}) or {}
    keep["planned_files"] = len(plan.get("actions") or [])
    keep["planned_torrents"] = [(t.get("site"), t.get("hash")) for t in plan.get("torrents") or []]
    keep["warnings"] = plan.get("warnings") or []
    keep["skipped"] = plan.get("skipped") or []
    keep["deleted"] = (keep.get("deleted") or [])[:200]
    return keep
