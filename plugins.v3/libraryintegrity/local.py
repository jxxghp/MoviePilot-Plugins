"""本地目录数据源：不经过媒体服务器，直接遍历用户指定的目录，识别剧集、单集与电影。

剧集身份依次取自 tvshow.nfo、目录名中的 {tmdbid=…} 标记和 MoviePilot 整理记录；单集 TMDB ID 与
strm 技术参数取自同名 NFO（由扫描编排统一补充）；本地视频可选读取媒体信息。
"""

from __future__ import annotations

import os
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, Optional

from app.sdk.logging import logger

from .checks import parse_int
from .models import ORIGIN_LOCAL, LibraryEpisode, LibraryMovie, LibrarySeries, SourceError, VersionInfo
from .nfo import NfoReader, PathMapper
from .probe import MediaProbe

VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".m2ts", ".ts", ".avi", ".mov", ".wmv", ".flv", ".webm", ".iso", ".rmvb", ".m4v", ".mpg", ".mpeg",
}
STRM_EXTENSION = ".strm"
# 读取 strm 文件内容的上限，正常只有一行地址
MAX_STRM_BYTES = 4096

# 不属于正片的目录
_SKIPPED_DIRS = {
    "extrafanart", "extrathumbs", "extras", "featurettes", "behind the scenes", "deleted scenes", "trailers",
    "sample", "samples", "interviews", "shorts", "scenes", "other", "@eadir", "#recycle", ".deletedbytmm",
}
_SEASON_DIR = re.compile(r"^(?:season|s)\s*(\d+)$|^第\s*([0-9一二三四五六七八九十百]+)\s*季$|^(specials?)$", re.IGNORECASE)
_TMDB_TAG = re.compile(r"[\[{(]\s*tmdb(?:id)?\s*[=\-:]\s*(\d+)\s*[\]})]", re.IGNORECASE)
_YEAR = re.compile(r"[(\[（]\s*((?:19|20)\d{2})\s*[)\]）]")
_TAGS = re.compile(r"[\[{(（][^\]})）]*[\]})）]")
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

NumberParser = Callable[[str], tuple[Optional[int], Optional[int], Optional[int], str, str]]
HistoryLookup = Callable[[str], Optional[int]]


def _chinese_number(text: str) -> Optional[int]:
    """解析一到九十九的中文数字。"""
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        tens, _, ones = text.partition("十")
        return (_CN_DIGITS.get(tens, 1) if tens else 1) * 10 + (_CN_DIGITS.get(ones, 0) if ones else 0)
    return _CN_DIGITS.get(text)


def season_from_dir(name: str) -> Optional[int]:
    """从季目录名解析季号：Season 1、S01、第一季、Specials（第 0 季）；不是季目录时返回 None。"""
    match = _SEASON_DIR.match(name.strip())
    if not match:
        return None
    if match.group(3):
        return 0
    return _chinese_number(match.group(1) or match.group(2) or "")


_SEASON_NFO_NUMBER = re.compile(r"<(?:seasonnumber|season)>\s*(\d+)\s*</", re.IGNORECASE)
# season.nfo 正常只有几 KB
MAX_SEASON_NFO_BYTES = 256 * 1024


def season_from_nfo(path: Path) -> Optional[int]:
    """从 season.nfo 读取季号；没有季号（如 -1）或无法读取时返回 None。"""
    try:
        if path.stat().st_size > MAX_SEASON_NFO_BYTES:
            return None
        match = _SEASON_NFO_NUMBER.search(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return int(match.group(1)) if match else None


def tmdb_from_name(name: str) -> Optional[int]:
    """从目录名或文件名中的 {tmdbid=123}、[tmdb-123] 等标记读取 TMDB ID。"""
    match = _TMDB_TAG.search(name)
    return parse_int(match.group(1)) if match else None


def title_and_year(name: str) -> tuple[str, str]:
    """从目录名拆出标题与年份，去掉各类括号标记。"""
    year_match = _YEAR.search(name)
    title = _TAGS.sub(" ", name).strip(" .-_")
    return re.sub(r"\s+", " ", title) or name, year_match.group(1) if year_match else ""


@lru_cache(maxsize=8192)
def parse_numbers(stem: str) -> tuple[Optional[int], Optional[int], Optional[int], str, str]:
    """用宿主文件名识别解析 (季, 起始集, 结束集, 标题, 年份)；解析失败时全部为空。

    文件名去掉扩展名后可能以 .AAC、.DTS 等音频编码结尾，宿主会误判为音频文件改用音乐解析，
    因此强制按视频解析。
    """
    from app.sdk.media import MetaInfo

    try:
        meta = MetaInfo(stem, force_video=True)
    except Exception as err:  # noqa: BLE001 - 单个文件名解析失败不应中断扫描
        logger.debug(f"影视库完整性检查：文件名解析失败 {stem}：{err}")
        return None, None, None, "", ""
    return (
        parse_int(meta.begin_season),
        parse_int(meta.begin_episode),
        parse_int(meta.end_episode),
        str(meta.name or ""),
        str(meta.year or ""),
    )


def history_tmdb_id(path: str) -> Optional[int]:
    """按整理目标路径查询 MoviePilot 整理记录中的 TMDB ID。"""
    try:
        from app.db.oper.transferhistory import TransferHistoryOper

        history = TransferHistoryOper().get_by_dest(path)
    except Exception as err:  # noqa: BLE001 - 整理记录只是兜底来源
        logger.debug(f"影视库完整性检查：查询整理记录失败 {path}：{err}")
        return None
    if history is None or str(getattr(history, "media_source", "") or "") != "themoviedb":
        return None
    return parse_int(getattr(history, "media_id", None))


def read_strm_url(path: Path) -> str:
    """读取 strm 文件中的首个非空行作为远程地址。"""
    try:
        if path.stat().st_size > MAX_STRM_BYTES:
            return ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                return line.strip()
    except OSError:
        return ""
    return ""


@dataclass
class _EpisodeFile:
    """遍历时发现的单集文件。"""

    path: Path
    # 季目录无法确定季号且文件名也没有季号时为 None，与媒体服务器的处理一致
    season: Optional[int]
    episode: int
    episode_end: Optional[int]


class LocalSource:
    """把用户指定的每个目录当作一个媒体库扫描。"""

    origin = ORIGIN_LOCAL

    def __init__(
        self,
        roots: list[str],
        stop_event: threading.Event,
        probe: Optional[MediaProbe] = None,
        history_lookup: Optional[HistoryLookup] = history_tmdb_id,
        number_parser: NumberParser = parse_numbers,
        name: str = "本地目录",
    ) -> None:
        """记录扫描目录与依赖；本地路径无需映射，NFO 直接按实际路径读取。"""
        self.name = name
        self.roots = [root.strip() for root in roots if root and root.strip()]
        self.nfo = NfoReader(PathMapper(""))
        self._stop_event = stop_event
        self._probe = probe
        self._history_lookup = history_lookup
        self._parse = number_parser
        self._walked: dict[str, tuple[list[LibrarySeries], list[LibraryMovie]]] = {}

    def libraries(self) -> list[tuple[str, str, str]]:
        """返回存在的扫描目录，不存在的目录作为错误抛出。"""
        missing = [root for root in self.roots if not Path(root).is_dir()]
        if missing and len(missing) == len(self.roots):
            raise SourceError(f"本地目录不存在或无法访问：{'、'.join(missing)}")
        for root in missing:
            logger.warning(f"影视库完整性检查：本地目录不存在或无法访问：{root}")
        return [(root, root, "mixed") for root in self.roots if Path(root).is_dir()]

    def iter_series(self, library: tuple[str, str, str]) -> Iterator[LibrarySeries]:
        """返回目录中的剧集。"""
        yield from self._walk(library[1])[0]

    def iter_movies(self, library: tuple[str, str, str]) -> Iterator[LibraryMovie]:
        """返回目录中的电影。"""
        yield from self._walk(library[1])[1]

    def _walk(self, root: str) -> tuple[list[LibrarySeries], list[LibraryMovie]]:
        """遍历目录一次，按剧集目录与电影分组，结果在本轮扫描内复用。"""
        if root in self._walked:
            return self._walked[root]
        episodes_by_dir: dict[Path, list[_EpisodeFile]] = defaultdict(list)
        movies_by_key: dict[tuple[Path, str, str], list[Path]] = defaultdict(list)
        # 含 tvshow.nfo 的剧集目录；os.walk 自上而下，父目录总是先于子目录登记
        series_dirs: set[Path] = set()
        for dirpath, dirnames, filenames in os.walk(root):
            if self._stop_event.is_set():
                break
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in _SKIPPED_DIRS)
            current = Path(dirpath)
            lower_names = {name.lower() for name in filenames}
            is_season, dir_season = self._season_dir(current, lower_names, series_dirs)
            if "tvshow.nfo" in lower_names and not is_season:
                series_dirs.add(current)
            for filename in sorted(filenames):
                path = current / filename
                suffix = path.suffix.lower()
                if suffix not in VIDEO_EXTENSIONS and suffix != STRM_EXTENSION:
                    continue
                season, episode, episode_end, title, year = self._parse(path.stem)
                if episode is not None:
                    series_dir = current.parent if is_season else current
                    if season is None:
                        season = dir_season if is_season else 1
                    episodes_by_dir[series_dir].append(_EpisodeFile(path, season, episode, episode_end))
                else:
                    movies_by_key[(current, title.lower(), year)].append(path)
        # 有 tvshow.nfo 但没有任何单集文件的剧集目录也参与核对，与媒体服务器中空剧集的处理一致；
        # 含电影文件的目录（误放了 tvshow.nfo 的电影目录）除外，避免把电影 ID 当作剧集查询
        movie_dirs = {key[0] for key in movies_by_key}
        for directory in series_dirs:
            if directory in episodes_by_dir:
                continue
            if any(path == directory or directory in path.parents for path in movie_dirs):
                continue
            episodes_by_dir[directory] = []
        series = self._merge_same_identity([
            self._build_series(root, directory, files) for directory, files in sorted(episodes_by_dir.items())
        ])
        movies = [self._build_movie(root, key[0], files) for key, files in sorted(movies_by_key.items())]
        self._walked[root] = (series, movies)
        return self._walked[root]

    @staticmethod
    def _season_dir(current: Path, lower_names: set[str], series_dirs: set[Path]) -> tuple[bool, Optional[int]]:
        """判断目录是否为季目录并返回季号（无法确定时为 None）。

        季目录：名称为 Season 1、S01、第一季、Specials 等；或含 season.nfo；
        或自身没有 tvshow.nfo 而父目录是剧集目录（如自定义命名的「立志篇」「游郭篇」）。
        """
        number = season_from_dir(current.name)
        if number is not None:
            return True, number
        if "season.nfo" in lower_names:
            return True, season_from_nfo(current / "season.nfo")
        if "tvshow.nfo" not in lower_names and current.parent in series_dirs:
            return True, None
        return False, None

    @staticmethod
    def _merge_same_identity(series_list: list[LibrarySeries]) -> list[LibrarySeries]:
        """同一 TMDB 剧集分散在多个目录（如改名前后各存一份）时合并为一部剧，同一集的多个文件作为多个版本。"""
        groups: dict[int, list[LibrarySeries]] = defaultdict(list)
        result: list[LibrarySeries] = []
        for series in series_list:
            if series.tmdb_id:
                groups[series.tmdb_id].append(series)
            else:
                result.append(series)
        for items in groups.values():
            items.sort(key=lambda s: (-len(s.episodes), s.path))
            primary = items[0]
            by_key = {(e.season, e.episode): e for e in primary.episodes if e.season is not None}
            for other in items[1:]:
                for episode in other.episodes:
                    key = (episode.season, episode.episode)
                    if episode.season is not None and key in by_key:
                        by_key[key].versions.extend(episode.versions)
                        continue
                    primary.episodes.append(episode)
                    if episode.season is not None:
                        by_key[key] = episode
            primary.episodes.sort(key=lambda e: (e.season is None, e.season or 0, e.episode or 0))
            result.append(primary)
        return sorted(result, key=lambda s: s.path)

    def _identity(self, directory: Path, sample: Optional[Path], nfo_name: str, root_tag: str) -> tuple[Optional[int], str]:
        """依次从 NFO、目录名标记、整理记录确定 TMDB ID。"""
        nfo_path = directory / nfo_name
        if nfo_path.exists():
            for info in self.nfo.read_file(nfo_path, root_tag):
                if info.tmdb_id:
                    return info.tmdb_id, "nfo"
        tagged = tmdb_from_name(directory.name)
        if tagged:
            return tagged, "dirname"
        if sample is not None and self._history_lookup is not None:
            found = self._history_lookup(str(sample))
            if found:
                return found, "history"
        return None, ""

    def _version(self, path: Path) -> VersionInfo:
        """生成文件版本；本地视频按需读取媒体信息，strm 只读取文件内的地址。"""
        if path.suffix.lower() == STRM_EXTENSION:
            return VersionInfo(path=str(path), kind="strm", url=read_strm_url(path))
        version = VersionInfo(path=str(path), kind="file")
        if self._probe is not None:
            for dimension, value in self._probe.probe(path).items():
                version.fill(dimension, value, "mediainfo")
        return version

    def _build_series(self, root: str, directory: Path, files: list[_EpisodeFile]) -> LibrarySeries:
        """把一个剧集目录内的单集文件组装为剧集；同一季集号的多个文件作为多个版本。"""
        title, year = title_and_year(directory.name)
        tmdb_id, source = self._identity(directory, files[0].path if files else None, "tvshow.nfo", "tvshow")
        grouped: dict[tuple[Optional[int], int], list[_EpisodeFile]] = defaultdict(list)
        for file in files:
            grouped[(file.season, file.episode)].append(file)
        episodes = []
        ordered = sorted(grouped.items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or 0, kv[0][1]))
        for (season, number), items in ordered:
            first = items[0]
            episodes.append(LibraryEpisode(
                item_id=str(first.path),
                season=season,
                episode=number,
                episode_end=first.episode_end,
                path=str(first.path),
                versions=[self._version(item.path) for item in items],
            ))
        return LibrarySeries(
            server=self.name,
            library=root,
            item_id=str(directory),
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            tmdb_id_source=source,
            path=str(directory),
            episodes=episodes,
            origin=ORIGIN_LOCAL,
        )

    def _build_movie(self, root: str, directory: Path, files: list[Path]) -> LibraryMovie:
        """把同一目录内标题与年份相同的视频文件组装为一部电影的多个版本。"""
        first = files[0]
        tmdb_id, _ = self._identity(directory, first, f"{first.stem}.nfo", "movie")
        if not tmdb_id:
            tmdb_id, _ = self._identity(directory, None, "movie.nfo", "movie")
        title, year = title_and_year(directory.name if directory != Path(root) else first.stem)
        return LibraryMovie(
            server=self.name,
            library=root,
            item_id=str(first),
            title=title,
            year=year,
            tmdb_id=tmdb_id or tmdb_from_name(first.stem),
            versions=[self._version(path) for path in files],
            origin=ORIGIN_LOCAL,
        )
