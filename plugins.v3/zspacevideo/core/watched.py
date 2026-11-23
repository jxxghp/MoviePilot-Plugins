"""极影视「已看」：判定、跟踪、版本归组、删除清单与执行。

纯逻辑，不依赖 MoviePilot。所有外部能力（极影视读取、MP 记录、qB、删除文件、
删除整理记录）都通过 ``Host`` 注入，单测里用假的。

处理规则：
- 电影看客户端「已看过」；剧集只认整季标记（某一季的专辑被标记已看），不按单集进度算。
- 删除是选项：不删（默认）/ 只从库里移除（删库入口，继续做种，不腾空间）/
  真删除（库入口 + 做种源文件 + qB 任务一起删）。
- 自动删除：已看超过缓冲期才执行；缓冲期内取消已看就不删。
- 只碰 MP 整理/下载记录能追溯到这部片（这一季）的文件；同 inode 的其它入口全部列出；
  辅种共用的源文件一并列出，真删除时这些种子一起删。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat as statmod
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

MODE_NONE = "none"
MODE_LIBRARY = "library"
MODE_FULL = "full"
MODES = (MODE_NONE, MODE_LIBRARY, MODE_FULL)
MODE_LABELS = {MODE_NONE: "不删", MODE_LIBRARY: "只从库里移除", MODE_FULL: "真删除"}

TYPE_MOVIE = 100
TYPE_TV = 200
EXTEND_SINGLE = 1  # 普通专辑；7 是合集（系列）行，不算整季标记

MEDIA_EXTS = frozenset({
    ".mp4", ".mkv", ".ts", ".iso", ".rmvb", ".avi", ".mov", ".mpeg", ".mpg", ".wmv", ".3gp",
    ".asf", ".m4v", ".flv", ".m2ts", ".strm", ".tp", ".f4v", ".webm",
})
PLAN_TTL = 900
# 影片目录删完视频后可以一起清掉的附属文件；目录里有别的文件就整个目录不动
SIDECAR_EXTS = frozenset({
    ".nfo", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tbn",
    ".srt", ".ass", ".ssa", ".sub", ".idx", ".sup", ".vtt", ".smi",
})
_SAMPLE = re.compile(r"(?:^|[ ._\-\[(])sample(?:[ ._\-\])]|$)", re.I)

_SEASON_DIR = re.compile(r"(?:^|/)Season\s*0*(\d{1,3})(?:/|$)", re.I)
_SXXEYY = re.compile(r"(?<![A-Za-z0-9])S(\d{1,3})(?:[ ._-]*E\d{1,4}|(?![0-9]))", re.I)


# ---------------------------------------------------------------------- 小工具
def is_media(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in MEDIA_EXTS


def within(path: str, root: str) -> bool:
    root = root.rstrip("/") or "/"
    return path == root or path.startswith(root + "/")


def season_of_path(path: str) -> Optional[int]:
    """从路径里认季号：优先 ``Season N`` 目录，其次文件名里的 SxxEyy / Sxx。"""
    match = _SEASON_DIR.search(path)
    if match:
        return int(match.group(1))
    match = _SXXEYY.search(os.path.basename(path))
    if match:
        return int(match.group(1))
    return None


def parse_seasons(text: Optional[str]) -> Set[int]:
    """MP 记录里的季文本（``S01``、``S01-S03``、``S01 S02``）。"""
    result: Set[int] = set()
    if not text:
        return result
    nums = [int(x) for x in re.findall(r"S(\d{1,3})", text, re.I)]
    if "-" in text and len(nums) == 2 and nums[0] <= nums[1]:
        return set(range(nums[0], nums[1] + 1))
    return set(nums)


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} TB"


# ---------------------------------------------------------------------- 已看判定
@dataclass
class SeenEntry:
    """极影视里一个被标记已看的对象：一部电影或某剧的一季。"""

    library_id: str
    library_name: str
    collection_id: str
    title: str
    kind: str  # movie / season
    tmdb_id: int
    season: int = 0
    year: int = 0
    ambiguous: bool = False  # 季号是从文件路径推出来的且不止一季：可手动删，不自动删

    @property
    def key(self) -> str:
        if self.kind == "movie":
            return f"movie:{self.tmdb_id}" if self.tmdb_id else f"movie:c:{self.collection_id}"
        return f"tv:{self.tmdb_id}:S{self.season}" if self.tmdb_id else f"tv:c:{self.collection_id}:S{self.season}"


def watched_entries(row: Dict[str, Any], info_loader: Callable[[], Dict[str, Any]],
                    videos_loader: Callable[[], Dict[str, Any]],
                    library_name: str = "") -> List[SeenEntry]:
    """把 collection_list(seen=1) 的一行换成已看对象。

    - 电影：``type=100`` 且 ``is_seen=1`` 的普通专辑。
    - 剧集：只认季专辑本身的已看标记（``type=200``、普通专辑、``is_seen=1``）；季号取
      collection_info.season，为 0 时从文件路径认。合集行（extend_type=7）不算。
    - 不读播放记录：单集看到哪不参与判定。
    """
    if int(row.get("is_seen") or 0) != 1:
        return []
    if int(row.get("extend_type") or EXTEND_SINGLE) != EXTEND_SINGLE:
        return []
    kind_type = int(row.get("type") or 0)
    base: Dict[str, Any] = dict(library_id=str(row.get("classification_id") or ""), library_name=library_name or str(row.get("classification_name") or ""),
                collection_id=str(row.get("collection_id") or ""), title=str(row.get("title") or ""),
                tmdb_id=int(row.get("tmdb_id") or 0), year=int(row.get("release_year") or 0))
    if kind_type == TYPE_MOVIE:
        return [SeenEntry(kind="movie", **base)]
    if kind_type != TYPE_TV:
        return []
    info = info_loader() or {}
    if int(info.get("is_seen") or 0) != 1:  # 以详情为准，列表和详情不一致时不删
        return []
    if not base["tmdb_id"]:
        base["tmdb_id"] = int(info.get("tmdbid") or 0)
    season = int(info.get("season") or 0)
    seasons: Set[int] = {season} if season else set()
    if not seasons:
        for video in (videos_loader() or {}).get("video_list") or []:
            found = season_of_path(str(video.get("file_path") or ""))
            if found is not None:
                seasons.add(found)
    ambiguous = not season and len(seasons) > 1
    return [SeenEntry(kind="season", season=s, ambiguous=ambiguous, **base) for s in sorted(seasons)]


# ---------------------------------------------------------------------- 跟踪（首次发现、缓冲期）
def track(state: Dict[str, Dict[str, Any]], entries: Sequence[SeenEntry], now: float
          ) -> Tuple[Dict[str, Dict[str, Any]], List[str], List[str]]:
    """用这次读到的已看清单更新跟踪表。

    返回 (新表, 新增 key, 取消 key)。不在本次清单里的对象视为取消已看，从表里去掉；
    以后再标已看，首次发现时间从那时重新算（缓冲期重新计）。
    """
    current = {e.key: e for e in entries}
    new_state: Dict[str, Dict[str, Any]] = {}
    added: List[str] = []
    for key, entry in current.items():
        old = state.get(key)
        record = asdict(entry)
        record["key"] = key
        first = (old or {}).get("first_seen_at")
        record["first_seen_at"] = now if first is None else first
        record["last_seen_at"] = now
        for keep in ("done_at", "done_mode", "last_error"):
            if old and old.get(keep):
                record[keep] = old[keep]
        if not old:
            added.append(key)
        new_state[key] = record
    removed = [k for k in state if k not in current]
    return new_state, added, removed


def due_keys(state: Dict[str, Dict[str, Any]], buffer_days: float, now: float, since: float = 0.0) -> List[str]:
    """已看且超过缓冲期、还没处理过的对象。

    since：打开自动删除的时间。首次发现早于它的（开自动删除之前就已经看过的）不自动删，只能手动删，
    避免一打开自动删除就把以前看过的全部清掉。
    ambiguous：一个专辑的已看标记推不出唯一季号（文件跨多季），不自动删。
    stale：这次没能从极影视确认它仍是已看（读失败时保留的旧条目），不自动删。
    """
    limit = max(0.0, float(buffer_days)) * 86400
    return sorted(k for k, v in state.items()
                  if not v.get("done_at") and v.get("first_seen_at") is not None
                  and not v.get("ambiguous") and not v.get("stale")
                  and float(v["first_seen_at"]) >= since
                  and now - float(v["first_seen_at"]) >= limit)


# ---------------------------------------------------------------------- 版本归组
@dataclass
class FileInfo:
    path: str
    role: str  # library / download / other
    size: int = 0
    dev: int = 0
    ino: int = 0
    nlink: int = 0
    mtime_ns: int = 0
    exists: bool = True
    traced: bool = True  # 能从 MP 记录追溯到这部片
    links: List[str] = field(default_factory=list)  # 同 inode 的全部入口
    season_unknown: bool = False  # 剧集：这个路径认不出季号（真删除默认不删，需手动确认）
    other_season: bool = False  # 剧集：路径明确属于别的季（同一份数据的另一个入口），永远不删


@dataclass
class TorrentInfo:
    hash: str
    name: str
    content_path: str
    save_path: str
    state: str = ""
    site: str = ""
    size: int = 0
    tags: str = ""
    cross_seed: bool = False  # 与别的种子共用同一份源文件
    foreign_media: List[str] = field(default_factory=list)  # 种子里不属于这部片/这季的媒体文件


@dataclass
class Version:
    id: str
    label: str
    files: List[FileInfo] = field(default_factory=list)
    torrents: List[TorrentInfo] = field(default_factory=list)
    site: str = ""
    record_ids: List[int] = field(default_factory=list)
    in_library: bool = False
    seeding: bool = False
    traced: bool = True  # 来自 MP 记录；False 表示只在极影视里看到，不删
    notes: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        seen: Set[Tuple[int, int]] = set()
        total = 0
        for item in self.files:
            if item.exists and (item.dev, item.ino) not in seen:
                seen.add((item.dev, item.ino))
                total += item.size
        return total


@dataclass
class Roots:
    library: List[str]
    download: List[str]

    def role(self, path: str) -> str:
        if any(within(path, r) for r in self.library):
            return "library"
        if any(within(path, r) for r in self.download):
            return "download"
        return "other"


def _matches_season(entry: SeenEntry, seasons_text: Optional[str], path: str) -> bool:
    """剧集只要这一季：路径里认得出季号就按路径，认不出再看 MP 记录的季文本。"""
    if entry.kind != "season":
        return True
    found = season_of_path(path) if path else None
    if found is not None:
        return found == entry.season
    return entry.season in parse_seasons(seasons_text)


def _season_certain(entry: SeenEntry, path: str, seasons_text: Optional[str] = None,
                    record_is_file: bool = False) -> bool:
    """剧集：这个路径能不能确定属于这一季。

    - 路径里有 ``Season N`` 目录或文件名里有 SxxEyy / Sxx：按它判断；
    - 都没有时，只有「这条 MP 记录就是这个文件」且记录的季文本正好是这一季才算确定。
      目录级记录（整盘原盘、整个种子目录）的季文本不算：MP 认不出季号时默认记成 S01。
    电影永远确定。
    """
    if entry.kind != "season":
        return True
    found = season_of_path(path) if path else None
    if found is not None:
        return found == entry.season
    return record_is_file and parse_seasons(seasons_text) == {entry.season}


def _is_sample(path: str) -> bool:
    """样片：在 ``Sample`` 目录里，或文件名里 ``sample`` 是一个独立的词（``xxx-sample.mkv``）。

    不按子串判断：片名里含 sample（如 The.Sampler）的视频不是样片。
    """
    parts = path.replace("\\", "/").lower().split("/")
    if "sample" in parts[:-1] or "samples" in parts[:-1]:
        return True
    return bool(_SAMPLE.search(os.path.splitext(parts[-1])[0]))


def _walk_media(path: str) -> List[str]:
    if os.path.isfile(path):
        return [path]
    result: List[str] = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(root, name)
            if is_media(full):
                result.append(full)
    return sorted(result)


class InodeIndex:
    """(dev, ino) -> 路径 索引，按目录项建立，不依赖链接数。

    极空间 zfuse 视图会缓存文件属性：删掉一个硬链接后，另一个入口的 st_nlink 可能还是旧值（实测
    几分钟不变，直到下一次 setattr）。所以「同一份数据有几个入口」以实际目录项为准。
    """

    def __init__(self, roots: Sequence[str], ttl: float = 600.0, clock: Callable[[], float] = time.time) -> None:
        self.roots = list(roots)
        self.ttl = ttl
        self._clock = clock
        self._index: Optional[Dict[Tuple[int, int], List[str]]] = None
        self._built_at = 0.0

    def invalidate(self) -> None:
        self._index = None

    def lookup(self, dev: int, ino: int) -> List[str]:
        if self._index is None or self._clock() - self._built_at > self.ttl:
            index: Dict[Tuple[int, int], List[str]] = {}
            for root in self.roots:
                for base, _dirs, files in os.walk(root):
                    for name in files:
                        full = os.path.join(base, name)
                        try:
                            info = os.lstat(full)
                        except OSError:
                            continue
                        if statmod.S_ISREG(info.st_mode):
                            index.setdefault((info.st_dev, info.st_ino), []).append(full)
            self._index = index
            self._built_at = self._clock()
        return list(self._index.get((dev, ino), []))


def stat_file(path: str, role: str, traced: bool = True) -> FileInfo:
    try:
        info = os.lstat(path)
    except OSError:
        return FileInfo(path=path, role=role, exists=False, traced=traced)
    return FileInfo(path=path, role=role, size=info.st_size, dev=info.st_dev, ino=info.st_ino,
                    nlink=info.st_nlink, mtime_ns=info.st_mtime_ns, exists=True, traced=traced)


def torrent_covers(torrent: TorrentInfo, path: str) -> bool:
    content = (torrent.content_path or "").rstrip("/")
    return bool(content) and within(path, content)


_EP_TOKEN = re.compile(r"S\d{1,3}E\d{1,4}(?:\s*-\s*第\s*\d+\s*集)?", re.I)


def _group_name(path: str) -> str:
    """没有种子的库文件按「目录 + 去掉集号的文件名」归成一个版本（同一版本的各集）。"""
    stem, ext = os.path.splitext(os.path.basename(path))
    stem = re.sub(r"\.{2,}", ".", re.sub(r"(?:[\s._-]+-)+", " -", _EP_TOKEN.sub("", stem))).strip(" -._")
    return os.path.join(os.path.dirname(path), (stem or "未命名") + ext)


def build_versions(entry: SeenEntry, transfers: Sequence[Dict[str, Any]], downloads: Sequence[Dict[str, Any]],
                   torrents: Sequence[TorrentInfo], roots: Roots, index: InodeIndex,
                   torrent_files: Callable[[TorrentInfo], List[str]],
                   zvideo_files: Optional[Sequence[str]] = None, exact_links: bool = False) -> List[Version]:
    """把一部片（一季）的所有版本串起来。

    exact_links=True（预览删除时）：每份数据都用全量目录项索引找齐入口，不看 st_nlink。

    1. 收集候选文件：MP 整理记录（src 下载目录、dest 库入口）、下载记录（种子内容路径）、
       极影视条目里的文件；剧集只取这一季。
    2. 按 inode 合并成「同一份数据」，链接数多于已知入口时全量找其它入口。
    3. 同一份数据落在某个种子内容路径下，就按种子内容路径归成一个版本（辅种同内容路径，归在一起）；
       没有种子的按目录 + 去掉集号的文件名归组。
    4. 能追溯：数据来自 MP 整理/下载记录，或所在种子在 MP 下载记录里（同一 TMDB）。追溯不到的只展示不删。
    洗版换下来、库里已没有入口的旧版本也会出现（只剩下载目录里的文件）。
    """
    hash_site: Dict[str, str] = {}
    traced_hashes: Set[str] = set()
    for record in list(transfers) + list(downloads):
        if record.get("download_hash"):
            traced_hashes.add(str(record["download_hash"]).lower())
            if record.get("torrent_site"):
                hash_site[str(record["download_hash"]).lower()] = str(record["torrent_site"])

    traced_paths: Set[str] = set()
    certain_paths: Set[str] = set()  # 剧集：确定属于这一季的路径
    candidates: Dict[str, str] = {}  # 路径 -> 来源
    record_ids_by_path: Dict[str, List[int]] = {}
    notes_by_path: Dict[str, str] = {}

    def add(path: str, source: str) -> None:
        if path and path not in candidates:
            candidates[path] = source
        if source != "zvideo":
            traced_paths.add(path)

    for record in transfers:
        if not record.get("status"):
            continue
        src, dest = str(record.get("src") or ""), str(record.get("dest") or "")
        matched: List[str] = []
        # 整理记录也覆盖别的季（多季合集目录）时，删掉这一季也要留着这条记录，剩下的季还靠它追溯
        shared = entry.kind == "season" and bool(parse_seasons(record.get("seasons")) - {entry.season})
        for path, storage in ((src, record.get("src_storage")), (dest, record.get("dest_storage"))):
            if not path:
                continue
            if storage not in (None, "", "local"):
                continue  # 网盘等非本地存储：同名本地路径不是这个文件
            is_dir = os.path.isdir(path)
            medias = _walk_media(path) if is_dir else [path]
            for media in medias:
                if _matches_season(entry, record.get("seasons"), media):
                    add(media, "transfer")
                    if _season_certain(entry, media, record.get("seasons"), record_is_file=not is_dir):
                        certain_paths.add(media)
                    matched.append(media)
                else:
                    shared = True
        if record.get("id") is not None and not shared:
            for media in matched:
                record_ids_by_path.setdefault(media, []).append(int(record["id"]))
    for record in downloads:
        path = str(record.get("path") or "")
        if not path or not os.path.exists(path):
            continue
        is_file = not os.path.isdir(path)
        for media in _walk_media(path):
            if _matches_season(entry, record.get("seasons"), media):
                if media not in candidates:
                    notes_by_path[media] = "只有下载记录，没有整理记录"
                add(media, "download")
                if _season_certain(entry, media, record.get("seasons"), record_is_file=is_file):
                    certain_paths.add(media)
    zvideo_dirs: List[str] = []
    for path in zvideo_files or []:
        if os.path.isdir(path):
            zvideo_dirs.append(path)
        elif path:
            add(path, "zvideo")

    # 2. 按 inode 合并
    infos: Dict[str, FileInfo] = {}
    for path in candidates:
        infos[path] = stat_file(path, roots.role(path))
    units: Dict[Tuple[int, int], Set[str]] = {}
    missing: List[str] = []
    for path, info in infos.items():
        if info.exists:
            units.setdefault((info.dev, info.ino), set()).add(path)
        else:
            missing.append(path)
    for inode, paths in units.items():
        nlink = max(infos[p].nlink for p in paths)
        if exact_links or nlink > len(paths):
            for path in index.lookup(*inode):
                if path not in paths:
                    paths.add(path)
                    infos[path] = stat_file(path, roots.role(path))

    # 原盘之类的目录：去掉已单独列出的文件后汇总成一个单元
    dir_units: List[Tuple[str, List[str]]] = []
    known_paths = {p for paths in units.values() for p in paths}
    for folder in zvideo_dirs:
        medias = [m for m in _walk_media(folder) if m not in known_paths]
        if medias:
            dir_units.append((folder, medias))

    # 3. 归版本
    by_key: Dict[str, Version] = {}

    def holders_of(paths: Iterable[str]) -> List[TorrentInfo]:
        found = {t.hash: t for t in torrents for p in paths if torrent_covers(t, p)}
        return sorted(found.values(), key=lambda t: (t.content_path, t.hash))

    def get_version(key: str, label: str) -> Version:
        version = by_key.get(key)
        if version is None:
            version = Version(id=hashlib.sha1(key.encode("utf-8")).hexdigest()[:12], label=label, traced=False)
            by_key[key] = version
        return version

    unit_holders: Dict[Tuple[int, int], List[TorrentInfo]] = {}
    for inode, paths in sorted(units.items(), key=lambda kv: sorted(kv[1])[0]):
        holders = holders_of(paths)
        unit_holders[inode] = holders
        if holders:
            content = holders[0].content_path.rstrip("/")
            version = get_version("t:" + content, os.path.basename(content))
        else:
            anchor = sorted(paths, key=lambda p: (roots.role(p) != "download", p))[0]
            key = os.path.dirname(anchor) if roots.role(anchor) == "download" else _group_name(anchor)
            version = get_version("g:" + key, os.path.basename(key) or os.path.basename(anchor))
        traced = bool(paths & traced_paths) or any(t.hash.lower() in traced_hashes for t in holders)
        for path in sorted(paths):
            info = infos[path]
            info.links = sorted(paths)
            info.traced = traced
            found = season_of_path(path) if entry.kind == "season" else None
            info.other_season = found is not None and found != entry.season
            info.season_unknown = (not info.other_season and path not in certain_paths
                                   and not _season_certain(entry, path))
            version.files.append(info)
            version.record_ids.extend(record_ids_by_path.get(path, []))
            if path in notes_by_path and notes_by_path[path] not in version.notes:
                version.notes.append(notes_by_path[path])
        version.traced = version.traced or traced
    # 记录里已不存在的路径（例如洗版时被覆盖掉的旧库入口）不单独成版本
    for folder, medias in dir_units:
        version = get_version("d:" + folder, os.path.basename(folder))
        total = sum(stat_file(m, "other").size for m in medias)
        version.files.append(FileInfo(path=folder.rstrip("/") + "/", role=roots.role(folder), size=total,
                                      exists=True, traced=False, links=[folder.rstrip("/") + "/"]))
        version.notes.append(f"目录，含 {len(medias)} 个视频文件（原盘等）")

    # 4. 种子与版本状态
    for version in by_key.values():
        if not version.traced and "MP 整理/下载记录里追溯不到，只展示，不会删" not in version.notes:
            version.notes.insert(0, "MP 整理/下载记录里追溯不到，只展示，不会删")
        holders: Dict[str, TorrentInfo] = {}
        for item in version.files:
            if not item.exists or not item.ino:
                continue
            for torrent in unit_holders.get((item.dev, item.ino), []):
                holders.setdefault(torrent.hash, torrent)
        version_paths = {f.path for f in version.files}
        allowed = set(version_paths)
        files_of: Dict[str, List[str]] = {t.hash: torrent_files(t) for t in holders.values()}
        for torrent in holders.values():
            if torrent.hash.lower() in traced_hashes:
                for path in files_of[torrent.hash]:
                    if is_media(path) and _matches_season(entry, None, path):
                        allowed.add(path)
        # 种子里属于这一季、但不在候选里的文件（例如还没整理的集）也算这个版本
        for path in sorted(allowed - version_paths):
            if os.path.lexists(path):
                info = stat_file(path, roots.role(path), traced=True)
                info.links = [path]
                version.files.append(info)
                version_paths.add(path)
        unknown_count = sum(1 for f in version.files if f.exists and f.season_unknown)
        if unknown_count and version.traced:
            version.notes.append(f"{unknown_count} 个文件路径里认不出季号（原盘等），真删除默认不删这个版本，"
                                 f"要在删除时手动确认属于第 {entry.season} 季")
        unknown_count = sum(1 for f in version.files if f.exists and f.season_unknown)
        if unknown_count:
            version.notes.append(f"{unknown_count} 个文件路径里认不出季号，真删除默认不删，"
                                 f"要在删除时手动确认属于第 {entry.season} 季")
        for torrent in holders.values():
            copy = TorrentInfo(**asdict(torrent))
            copy.site = copy.site or hash_site.get(copy.hash.lower(), "")
            copy.cross_seed = len(holders) > 1
            copy.foreign_media = [p for p in files_of[torrent.hash]
                                  if is_media(p) and p not in allowed and not _is_sample(p)]
            version.torrents.append(copy)
        version.torrents.sort(key=lambda t: t.hash)
        version.record_ids = sorted(set(version.record_ids))
        version.seeding = any(t.state.endswith("UP") or t.state in ("uploading", "forcedUP", "queuedUP")
                              for t in version.torrents)
        version.in_library = any(f.exists and f.role == "library" for f in version.files)
        version.site = next((hash_site[t.hash.lower()] for t in version.torrents if t.hash.lower() in hash_site), "") \
            or next((t.site for t in version.torrents if t.site), "")
        version.files.sort(key=lambda f: (f.role != "library", f.path))
    return sorted(by_key.values(), key=lambda v: (not v.in_library, not v.traced, v.label))


# ---------------------------------------------------------------------- 删除清单
@dataclass
class Action:
    path: str
    role: str
    size: int
    dev: int
    ino: int
    mtime_ns: int
    nlink: int
    via: str = "storage"  # storage=经 MP 存储删除；torrent=随 qB 任务删除
    entries: int = 1  # 预览时找到的同一份数据的入口数（目录项），算腾出空间用
    keep: List[str] = field(default_factory=list)  # 只从库里移除：必须还在的同 inode 入口（做种源）


@dataclass
class Plan:
    id: str
    created_at: float
    mode: str
    item_key: str
    title: str
    version_ids: List[str]
    actions: List[Action] = field(default_factory=list)
    torrents: List[TorrentInfo] = field(default_factory=list)
    record_ids: List[int] = field(default_factory=list)
    freed_bytes: int = 0
    warnings: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    rescan_paths: List[str] = field(default_factory=list)
    confirm_unknown_season: bool = False
    unknown_season: Dict[str, Any] = field(default_factory=dict)  # 认不出季号的文件汇总（数量、目录、大小）

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["mode_label"] = MODE_LABELS.get(self.mode, self.mode)
        data["freed_text"] = human_size(self.freed_bytes)
        return data


def _unknown_summary(files: Sequence[FileInfo], season: int, confirmed: bool, labels: Sequence[str]) -> Dict[str, Any]:
    dirs: Dict[str, Dict[str, Any]] = {}
    total = 0
    for item in files:
        row = dirs.setdefault(os.path.dirname(item.path), {"dir": os.path.dirname(item.path), "count": 0, "size": 0})
        row["count"] += 1
        row["size"] += item.size
        total += item.size
    for row in dirs.values():
        row["size_text"] = human_size(row["size"])
    return {"season": season, "confirmed": confirmed, "count": len(files), "size": total, "size_text": human_size(total),
            "dirs": sorted(dirs.values(), key=lambda r: r["dir"]), "files": sorted(f.path for f in files),
            "versions": list(labels)}


def _season_of_key(item_key: str) -> int:
    match = re.search(r":S(\d+)$", item_key or "")
    return int(match.group(1)) if match else 0


def make_plan(item_key: str, title: str, versions: Sequence[Version], mode: str,
              version_ids: Optional[Iterable[str]], roots: Roots, now: float,
              confirm_unknown_season: bool = False) -> Plan:
    """冻结一份删除清单：要删的每个路径记下 (dev, ino, size, mtime)，执行时逐个核对。

    剧集里认不出季号的文件（``season_unknown``）：
    - 真删除：版本里只要有一个，整个版本（含种子）默认不删，单独列出；
    - 只从库里移除：这样的库入口跳过并列出，其它库入口照常；
    - ``confirm_unknown_season=True``（只给手动删除用，用户在页面上确认这些文件属于这一季）才纳入。
      自动删除永远不传，所以永远跳过。
    """
    if mode not in (MODE_LIBRARY, MODE_FULL):
        raise ValueError("删除选项只能是「只从库里移除」或「真删除」")
    chosen_ids = set(v.id for v in versions) if version_ids is None else set(version_ids)  # 空列表 = 什么都没选
    chosen = [v for v in versions if v.id in chosen_ids]
    if not chosen:
        raise ValueError("没有选中任何版本")
    plan = Plan(id="", created_at=now, mode=mode, item_key=item_key, title=title,
                version_ids=sorted(v.id for v in chosen), confirm_unknown_season=bool(confirm_unknown_season))
    planned: Dict[str, Action] = {}
    blocked_versions: Set[str] = set()
    season = _season_of_key(item_key)
    unknown_files: List[FileInfo] = []
    unknown_labels: List[str] = []
    for version in chosen:
        if not version.traced:
            continue
        found = [f for f in version.files if f.exists and f.season_unknown
                 and (mode == MODE_FULL or f.role == "library")]
        if found:
            unknown_files.extend(found)
            unknown_labels.append(version.label)
            if mode == MODE_FULL and not confirm_unknown_season:
                dirs = sorted({os.path.dirname(f.path) for f in found})
                plan.skipped.append(
                    f"「{version.label}」有 {len(found)} 个文件路径里认不出季号（{human_size(sum(f.size for f in found))}，"
                    f"在 {len(dirs)} 个目录，如 {dirs[0]}），整个版本和它的种子都不删；确认它们属于第 {season} 季后可勾选纳入")
                blocked_versions.add(version.id)

    if mode == MODE_FULL:
        for version in chosen:
            if version.id in blocked_versions:
                continue
            for torrent in version.torrents:
                if torrent.foreign_media:
                    plan.skipped.append(
                        f"「{version.label}」：种子 {torrent.name}（{torrent.hash[:8]}）里还有 {len(torrent.foreign_media)} 个"
                        f"不属于这部片/这季的视频文件（如 {os.path.basename(torrent.foreign_media[0])}），整个版本不删")
                    blocked_versions.add(version.id)
                    break

    for version in chosen:
        if version.id in blocked_versions:
            continue
        if not version.traced:
            plan.skipped.append(f"「{version.label}」在 MP 整理/下载记录里追溯不到，不删")
            continue
        for item in version.files:
            if not item.exists:
                continue
            if item.other_season:
                plan.warnings.append(f"{item.path}：和这一季是同一份数据，但在别的季目录里，不删")
                continue
            if mode == MODE_LIBRARY:
                if item.role != "library":
                    continue
                if item.season_unknown and not confirm_unknown_season:
                    plan.skipped.append(f"{item.path}：路径里认不出季号，不移出库；确认属于第 {season} 季后可勾选纳入")
                    continue
                outside = [p for p in item.links if roots.role(p) != "library"]
                if not outside:
                    plan.skipped.append(f"{item.path}：库里这一份没有做种源（唯一一份），只移库会真删掉，已跳过；要删请选「真删除」")
                    continue
            via = "torrent" if mode == MODE_FULL and any(torrent_covers(t, item.path) for t in version.torrents) else "storage"
            if not item.traced and via != "torrent":
                plan.warnings.append(f"{item.path} 和这部片是同一份数据（同 inode），但 MP 记录追溯不到这个入口，不删"
                                     + ("；这份空间腾不出来" if mode == MODE_FULL else ""))
                continue
            keep = [p for p in item.links if roots.role(p) != "library"] if mode == MODE_LIBRARY else []
            planned[item.path] = Action(path=item.path, role=item.role, size=item.size, dev=item.dev, ino=item.ino,
                                        mtime_ns=item.mtime_ns, nlink=item.nlink, via=via,
                                        entries=max(1, len(item.links)), keep=keep)
        if mode == MODE_FULL:
            for torrent in version.torrents:
                if all(t.hash != torrent.hash for t in plan.torrents):
                    plan.torrents.append(torrent)
            plan.record_ids.extend(version.record_ids)
            if any(t.cross_seed for t in version.torrents):
                plan.warnings.append(f"「{version.label}」由 {len(version.torrents)} 个种子共用同一份文件（辅种），会一起删："
                                     + "、".join(f"{t.site or '?'} {t.hash[:8]}" for t in version.torrents))
        elif version.torrents:
            plan.warnings.append(f"「{version.label}」继续做种（{len(version.torrents)} 个任务），文件还在下载目录，不腾空间")

    if unknown_files:
        plan.unknown_season = _unknown_summary(unknown_files, season, bool(confirm_unknown_season), unknown_labels)
    _add_sidecars(plan, planned, roots)
    plan.actions = sorted(planned.values(), key=lambda a: (a.role != "library", a.path))
    plan.record_ids = sorted(set(plan.record_ids))
    # 腾出空间：一个 inode 的全部链接都在清单里才算
    by_inode: Dict[Tuple[int, int], List[Action]] = {}
    for action in plan.actions:
        by_inode.setdefault((action.dev, action.ino), []).append(action)
    for group in by_inode.values():
        if len(group) >= group[0].entries:
            plan.freed_bytes += group[0].size
        elif mode == MODE_FULL:
            plan.warnings.append(f"{os.path.basename(group[0].path)} 共 {group[0].entries} 个入口，清单里只有 {len(group)} 个"
                                 "，删完这份数据还在，不腾空间")
    # 删完要刷新的库目录：库入口所在目录（存在的最近上级）
    dirs = sorted({os.path.dirname(a.path) for a in plan.actions if a.role == "library"})
    plan.rescan_paths = dirs
    if not plan.actions and not plan.torrents:
        plan.warnings.append("没有可以删的文件")
    plan.id = plan_digest(plan)
    return plan


def _add_sidecars(plan: Plan, planned: Dict[str, Action], roots: Roots) -> None:
    """库里的影片目录（或季目录）删完视频后只剩 nfo/海报/字幕（SIDECAR_EXTS）时，一起清掉；
    还有别的视频、原盘或任何认不得的文件就整个目录不动。"""
    dirs = sorted({os.path.dirname(a.path) for a in planned.values() if a.role == "library"})
    for folder in dirs:
        if not os.path.isdir(folder) or any(os.path.normpath(folder) == os.path.normpath(r) for r in roots.library):
            continue
        if not any(within(folder, r) and folder != r for r in roots.library):
            continue
        rest: List[str] = []
        blocked = False
        for base, subdirs, files in os.walk(folder):
            if any(d.upper() in ("BDMV", "CERTIFICATE", "VIDEO_TS") for d in subdirs):
                blocked = True
                break
            for name in files:
                full = os.path.join(base, name)
                if full in planned:
                    continue
                if os.path.splitext(name)[1].lower() not in SIDECAR_EXTS:
                    blocked = True  # 视频或认不得的文件（文档、压缩包…）：整个目录不动
                    break
                rest.append(full)
            if blocked:
                break
        if blocked or not rest:
            continue
        for full in rest:
            item = stat_file(full, "library")
            if item.exists:
                planned[full] = Action(path=full, role="library", size=item.size, dev=item.dev, ino=item.ino,
                                       mtime_ns=item.mtime_ns, nlink=item.nlink, via="storage", entries=1)
        plan.warnings.append(f"{folder} 里不再有视频，剩下的 {len(rest)} 个附属文件（nfo/海报/字幕等）一起清掉")


def prune_empty_dirs(path: str, boundaries: Sequence[str],
                     rmdir: Callable[[str], None] = os.rmdir) -> List[str]:
    """从 path 往上逐层删除空目录，返回删掉的目录。

    - 每一层都必须真的为空（``os.rmdir`` 本身只删空目录，有任何文件或子目录都会失败并停下）；
    - 只在某个边界目录（媒体库根、MP 的类型/分类目录）之下工作，边界目录本身和它的祖先永远不删；
    - 不在任何边界之下的路径一律不动。
    """
    bounds = [os.path.normpath(b) for b in boundaries if b]
    current = os.path.normpath(path)
    inside = [b for b in bounds if within(current, b)]
    if not inside:
        return []
    stop = max(inside, key=len)  # 最深的边界
    removed: List[str] = []
    while current != stop and within(current, stop) and os.path.isdir(current):
        try:
            if os.listdir(current):
                break
            rmdir(current)
        except OSError:
            break
        removed.append(current)
        current = os.path.dirname(current)
    return removed


def leftover(versions: Sequence[Version], mode: str) -> List[str]:
    """按删除选项还剩哪些能删的文件（用来判断这部片是否处理完）。"""
    left: List[str] = []
    for version in versions:
        if not version.traced:
            continue
        for item in version.files:
            if item.exists and item.traced and (mode == MODE_FULL or item.role == "library"):
                left.append(item.path)
    return left


def plan_digest(plan: Plan) -> str:
    body = json.dumps({
        "mode": plan.mode, "key": plan.item_key,
        "actions": [asdict(a) for a in plan.actions],
        "torrents": sorted((t.hash, t.content_path) for t in plan.torrents),
        "records": plan.record_ids, "created": round(plan.created_at, 3),
        "confirm_unknown_season": plan.confirm_unknown_season,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------- 执行
@dataclass
class Host:
    """执行删除需要的外部能力。"""

    delete_path: Callable[[str, str], bool]  # (路径, role) -> 是否删掉
    list_torrents: Callable[[Sequence[str]], List[TorrentInfo]]  # 按 hash 查当前任务
    delete_torrents: Callable[..., bool]  # (hashes, expected={hash: content_path}) 删任务并删文件；内容路径对不上就拒删
    delete_records: Callable[[Sequence[int]], int] = lambda ids: 0
    forget_sources: Callable[[Sequence[str]], None] = lambda paths: None  # 清 MP 下载文件记录
    prune_dir: Callable[[str], None] = lambda path: None  # 删完后清理库里的空目录
    sleep: Callable[[float], None] = time.sleep


def verify_frozen(plan: Plan, host: Host, now: float) -> List[str]:
    """执行前核对：清单没过期、每个路径还是当时那个文件、每个种子还是当时那个内容路径。"""
    problems: List[str] = []
    if now - plan.created_at > PLAN_TTL:
        problems.append("清单已过期，请重新预览")
        return problems
    for action in plan.actions:
        try:
            info = os.lstat(action.path)
        except OSError:
            problems.append(f"{action.path} 已不存在")
            continue
        current = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if current != (action.dev, action.ino, action.size, action.mtime_ns):
            problems.append(f"{action.path} 和预览时不是同一个文件了")
            continue
        if action.keep and not any(_same_inode(p, action.dev, action.ino) for p in action.keep):
            problems.append(f"{action.path} 的做种源已不在，只移出库会删掉唯一一份")
    if plan.torrents:
        live = {t.hash: t for t in host.list_torrents([t.hash for t in plan.torrents])}
        for torrent in plan.torrents:
            now_t = live.get(torrent.hash)
            if now_t is None:
                problems.append(f"种子 {torrent.hash[:8]} 已不在 qB")
            elif now_t.content_path.rstrip("/") != torrent.content_path.rstrip("/"):
                problems.append(f"种子 {torrent.hash[:8]} 的内容路径变了")
    return problems


def _same_inode(path: str, dev: int, ino: int) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return (info.st_dev, info.st_ino) == (dev, ino)


def execute_plan(plan: Plan, host: Host, now: float, wait_seconds: float = 120.0,
                 poll: float = 2.0) -> Dict[str, Any]:
    """按冻结清单执行并读回。任何核对不过就整单不执行。"""
    result: Dict[str, Any] = {
        "plan_id": plan.id, "mode": plan.mode, "mode_label": MODE_LABELS.get(plan.mode, plan.mode),
        "item_key": plan.item_key, "title": plan.title, "started_at": now,
        "deleted": [], "failed": [], "torrents_removed": [], "torrents_failed": [],
        "records_deleted": 0, "freed_bytes": 0, "status": "pending",
    }
    problems = verify_frozen(plan, host, now)
    if problems:
        result.update(status="aborted", failed=problems)
        return result

    # 1. 库入口（经 MP 存储删除）
    for action in plan.actions:
        if action.role != "library":
            continue
        _delete(action, host, result)
    for path in plan.rescan_paths:
        try:
            host.prune_dir(path)
        except Exception as error:  # noqa: BLE001
            result["failed"].append(f"清理空目录 {path} 失败：{error}")

    if plan.mode == MODE_FULL:
        # 2. qB 任务连同文件（含辅种）
        hashes = [t.hash for t in plan.torrents]
        qb_clear = True  # 计划里的 qB 任务都确认已经不在
        if hashes:
            try:
                expected = {t.hash: t.content_path for t in plan.torrents}
                if not host.delete_torrents(hashes, expected=expected):
                    result["torrents_failed"].extend(hashes)
                deadline = time.monotonic() + wait_seconds
                while True:
                    left = {t.hash for t in host.list_torrents(hashes)}
                    files_left = [a for a in plan.actions if a.via == "torrent" and os.path.lexists(a.path)]
                    if not left and not files_left:
                        break
                    if time.monotonic() >= deadline:
                        break
                    host.sleep(poll)
                # 以最后一次读回为准：每个 hash 只在「已删」或「失败」其中一个列表里
                left = {t.hash for t in host.list_torrents(hashes)}
                result["torrents_removed"] = [h for h in hashes if h not in left]
                result["torrents_failed"] = sorted(left)
                qb_clear = not left
            except Exception as error:  # noqa: BLE001
                qb_clear = False
                result["torrents_failed"] = sorted(set(result["torrents_failed"]) | set(hashes))
                result["failed"].append(f"读取 qB 任务失败，种子状态不明：{error}")
        # 3. qB 没带走的源文件（不在种子里，或种子已确认不在）经 MP 存储删除。
        #    qB 任务还在或状态不明时，种子里的源文件一律不删：删了会让任务指向缺失的文件。
        for action in plan.actions:
            if action.role == "library":
                continue
            if not os.path.lexists(action.path):
                result["deleted"].append(action.path)
            elif action.via == "torrent" and not qb_clear:
                result["failed"].append(f"{action.path}：qB 任务没有删掉，源文件保留")
            else:
                _delete(action, host, result)
        # 4. 文件都没了的整理记录、下载文件记录
        gone_sources = [a.path for a in plan.actions if a.role != "library" and not os.path.lexists(a.path)]
        if gone_sources:
            try:
                host.forget_sources(gone_sources)
            except Exception as error:  # noqa: BLE001
                result["failed"].append(f"清理下载文件记录失败：{error}")
        # 整理记录最后删：删之前再核一次清单里的路径都已不在（中途被新整理写回的，记录要留着）
        reappeared = [a.path for a in plan.actions if os.path.lexists(a.path)]
        if reappeared:
            result["failed"].extend(f"{p} 删除后又出现了（可能是新的整理），整理记录保留" for p in reappeared)
        if plan.record_ids and not result["failed"] and not result["torrents_failed"]:
            try:
                result["records_deleted"] = host.delete_records(plan.record_ids)
            except Exception as error:  # noqa: BLE001
                result["failed"].append(f"删除整理记录失败：{error}")

    # 5. 读回
    still = [a.path for a in plan.actions if os.path.lexists(a.path)]
    for path in still:
        if not any(path in f for f in result["failed"]):
            result["failed"].append(f"{path} 删除后仍存在")
    result["deleted"] = sorted({p for p in result["deleted"] if not os.path.lexists(p)})
    gone = {a.path for a in plan.actions if not os.path.lexists(a.path)}
    by_inode: Dict[Tuple[int, int], List[Action]] = {}
    for action in plan.actions:
        by_inode.setdefault((action.dev, action.ino), []).append(action)
    for group in by_inode.values():
        if len(group) >= group[0].entries and all(a.path in gone for a in group):
            result["freed_bytes"] += group[0].size
    result["freed_text"] = human_size(result["freed_bytes"])
    result["finished_at"] = time.time()
    result["status"] = "done" if not result["failed"] and not result["torrents_failed"] else "partial"
    return result


def _delete(action: Action, host: Host, result: Dict[str, Any]) -> None:
    try:
        ok = host.delete_path(action.path, action.role)
    except Exception as error:  # noqa: BLE001
        ok = False
        result["failed"].append(f"{action.path}：{error}")
        return
    if ok and not os.path.lexists(action.path):
        result["deleted"].append(action.path)
    else:
        result["failed"].append(f"{action.path} 删除失败")


def summarize(results: Sequence[Dict[str, Any]]) -> str:
    """站内消息：部数、文件数、腾出空间、失败项。"""
    done = [r for r in results if r.get("status") in ("done", "partial")]
    files = sum(len(r.get("deleted") or []) for r in results)
    freed = sum(int(r.get("freed_bytes") or 0) for r in results)
    lines = [f"{len(done)} 部/季，删除 {files} 个文件，腾出 {human_size(freed)}"]
    for r in results:
        torrents = len(r.get("torrents_removed") or [])
        line = f"· {r.get('title')}（{r.get('mode_label')}）：{len(r.get('deleted') or [])} 个文件"
        if torrents:
            line += f"、{torrents} 个种子"
        line += f"，腾出 {r.get('freed_text') or human_size(int(r.get('freed_bytes') or 0))}"
        if r.get("status") == "aborted":
            line += "；未执行：" + "；".join(r.get("failed") or [])[:200]
        elif r.get("failed") or r.get("torrents_failed"):
            line += "；失败：" + "；".join((r.get("failed") or []) + (r.get("torrents_failed") or []))[:200]
        lines.append(line)
    return "\n".join(lines)
