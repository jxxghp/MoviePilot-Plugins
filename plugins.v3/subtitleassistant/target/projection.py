"""宿主媒体信息与整理历史到插件目标的唯一投影实现。

本模块收编此前散落在事件入口与整理历史两侧的同构投影：整理完成事件
载荷、宿主 MediaInfo、整理历史行，以及手动链所需的宿主媒体补充。别名
聚合、豆瓣/Bangumi/AniList 外部 ID 解析与季年份处理都只在本模块实现一
份，自动链与手动链共用相同结果。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.chain.media import MediaChain
from app.log import logger
from app.schemas.types import MediaType as HostMediaType

from ..schemas.attribution import CandidateMatchContext
from ..schemas.target import MediaType, SearchTarget, SubtitleTarget


@dataclass(frozen=True, slots=True)
class MediaResolution:
    """宿主媒体补充在目标投影内产出的插件事实。"""

    context: SubtitleTarget
    match_context: CandidateMatchContext


MediaResolver = Callable[[SubtitleTarget], Awaitable[MediaResolution | None]]


def _parse_integer(value: object) -> int | None:
    """把宿主非空标量收敛为整数，无法解析时返回空。"""

    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_number(value: object) -> int | None:
    """从宿主季集字段中读取第一个整数。"""

    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _parse_history_time(value: object) -> datetime:
    """把宿主整理时间归一化为 UTC。"""

    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone(UTC)


def match_context_from_mediainfo(context: SubtitleTarget, mediainfo: Any) -> CandidateMatchContext | None:
    """由宿主 MediaInfo 投影候选识别所需的插件自有媒体事实。

    事件入口与手动搜索此前各有一份逐行同构实现，本函数是唯一来源。
    """

    if mediainfo is None:
        return None
    aliases: list[str] = []
    for value in (
        getattr(mediainfo, "en_title", None),
        getattr(mediainfo, "original_title", None),
        *(getattr(mediainfo, "names", None) or []),
    ):
        if isinstance(value, str) and value.strip() and value.strip() not in aliases:
            aliases.append(value.strip())
    season_years = tuple(
        (str(season), str(year))
        for season, year in (getattr(mediainfo, "season_years", None) or {}).items()
        if year not in (None, "")
    )
    raw_douban = getattr(mediainfo, "douban_id", None)
    return CandidateMatchContext(
        title=str(getattr(mediainfo, "title", None) or context.title),
        aliases=tuple(aliases),
        original_title=getattr(mediainfo, "original_title", None) or context.original_title,
        year=context.year,
        media_type=context.media_type,
        tmdb_id=context.tmdb_id,
        imdb_id=context.imdb_id,
        douban_id=str(raw_douban).strip() if raw_douban not in (None, "") else None,
        bangumi_id=_parse_integer(getattr(mediainfo, "bangumi_id", None)),
        anilist_id=_parse_integer(getattr(mediainfo, "anilist_id", None)),
        season_years=season_years,
    )


def match_context_from_history(context: SubtitleTarget, history: Any) -> CandidateMatchContext:
    """由整理历史行投影候选识别事实。

    历史字段形状与 MediaInfo 不同：没有季年份映射，别名只来自英文标题
    与原始标题，因此保留独立入口而不构造虚假的中间形状。
    """

    aliases = tuple(
        value.strip()
        for value in (context.english_title, context.original_title)
        if isinstance(value, str) and value.strip() and value.strip() != context.title
    )
    raw_douban = getattr(history, "doubanid", None)
    return CandidateMatchContext(
        title=context.title,
        aliases=aliases,
        original_title=context.original_title,
        year=context.year,
        media_type=context.media_type,
        tmdb_id=context.tmdb_id,
        imdb_id=context.imdb_id,
        douban_id=str(raw_douban).strip() if raw_douban not in (None, "") else None,
        bangumi_id=_parse_number(getattr(history, "bangumiid", None)),
        anilist_id=_parse_number(getattr(history, "anilistid", None)),
    )


def build_media_context(target: Any, meta: Any, mediainfo: Any) -> SubtitleTarget | None:
    """在宿主整理事件边界投影安全的字幕目标。"""

    path_value = getattr(target, "path", None)
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    target_name = str(getattr(target, "name", None) or Path(path_value).name)
    media_title = str(
        getattr(mediainfo, "title", None)
        or getattr(meta, "name", None)
        or getattr(meta, "cn_name", None)
        or getattr(meta, "en_name", None)
        or Path(path_value).stem
    ).strip()
    media_type_value = getattr(getattr(mediainfo, "type", None), "name", None) or str(
        getattr(getattr(mediainfo, "type", None), "value", "")
    )
    media_type = MediaType.TV if media_type_value.upper() in {"TV", "电视剧"} else MediaType.MOVIE
    year_value = getattr(mediainfo, "year", None) or getattr(meta, "year", None)
    year = _parse_integer(year_value)
    season = getattr(mediainfo, "season", None) or getattr(meta, "begin_season", None)
    episode = getattr(meta, "begin_episode", None)
    season = _parse_integer(season)
    episode = _parse_integer(episode)
    tmdb_id = getattr(mediainfo, "tmdb_id", None) or getattr(meta, "tmdbid", None)
    tmdb_id = _parse_integer(tmdb_id)
    return SubtitleTarget(
        title=media_title,
        original_title=getattr(mediainfo, "original_title", None),
        english_title=getattr(mediainfo, "en_title", None),
        year=year,
        media_type=media_type,
        season=season,
        episode=episode,
        tmdb_id=tmdb_id,
        imdb_id=getattr(mediainfo, "imdb_id", None),
        target_path=Path(path_value),
        target_file_name=target_name,
        target_storage=getattr(target, "storage", None),
        target_type=str(getattr(target, "type", None) or "file"),
        target_extension=str(getattr(target, "extension", None) or Path(path_value).suffix).lstrip("."),
        target_container=getattr(target, "container", None),
    )


def target_from_history(history: Any) -> SearchTarget | None:
    """把一条成功的本地文件整理历史投影为插件搜索目标。"""

    if history is None:
        return None
    path_value = getattr(history, "dest", None)
    file_data = getattr(history, "dest_fileitem", None)
    if (
        getattr(history, "status", False) is not True
        or getattr(history, "dest_storage", None) != "local"
        or not isinstance(path_value, str)
        or not path_value.strip()
        or not isinstance(file_data, dict)
        or file_data.get("type") != "file"
    ):
        return None
    raw_type = str(getattr(history, "type", "") or "")
    media_type = (
        MediaType.TV
        if raw_type in {HostMediaType.TV.value, "tv", "TV"}
        else MediaType.MOVIE
        if raw_type in {HostMediaType.MOVIE.value, "movie", "MOVIE"}
        else MediaType.UNKNOWN
    )
    year_value = getattr(history, "year", None)
    year = _parse_integer(str(year_value)) if year_value is not None else None
    tmdb_value = getattr(history, "tmdbid", None)
    tmdb_id = _parse_integer(str(tmdb_value)) if tmdb_value is not None else None
    context = SubtitleTarget(
        title=str(getattr(history, "title", "") or Path(path_value).stem),
        original_title=getattr(history, "original_title", None),
        english_title=getattr(history, "en_title", None),
        year=year,
        media_type=media_type,
        season=_parse_number(getattr(history, "seasons", None)),
        episode=_parse_number(getattr(history, "episodes", None)),
        tmdb_id=tmdb_id,
        imdb_id=getattr(history, "imdbid", None),
        target_path=Path(path_value),
        target_file_name=str(file_data.get("name") or Path(path_value).name),
        target_storage="local",
        target_type="file",
        target_extension=str(file_data.get("extension") or Path(path_value).suffix).lstrip("."),
        target_container=file_data.get("container") if isinstance(file_data.get("container"), str) else None,
    )
    return SearchTarget(
        history_id=int(history.id),
        context=context,
        transferred_at=_parse_history_time(getattr(history, "date", None)),
        match_context=match_context_from_history(context, history),
    )


async def _default_media_resolver(context: SubtitleTarget) -> MediaResolution | None:
    """使用 MoviePilot 公共媒体能力按 TMDB ID 补充媒体信息。"""

    if context.tmdb_id is None:
        return None
    host_type = HostMediaType.TV if context.media_type is MediaType.TV else HostMediaType.MOVIE
    mediainfo = await MediaChain().async_recognize_media(
        mtype=host_type,
        tmdbid=context.tmdb_id,
        cache=True,
    )
    if mediainfo is None:
        return None
    enriched = context.model_copy(
        update={
            "english_title": getattr(mediainfo, "en_title", None) or context.english_title,
            "original_title": getattr(mediainfo, "original_title", None) or context.original_title,
        }
    )
    match_context = match_context_from_mediainfo(enriched, mediainfo)
    return MediaResolution(context=enriched, match_context=match_context) if match_context is not None else None


async def enrich_search_target(target: SearchTarget, resolver: MediaResolver | None = None) -> SearchTarget:
    """在英文标题缺失时尽力通过宿主媒体能力补充搜索目标。"""

    if target.context.english_title or not (target.context.tmdb_id or target.context.imdb_id):
        return target
    resolve = resolver or _default_media_resolver
    try:
        resolution = await resolve(target.context)
    except Exception:  # noqa: BLE001 - 宿主媒体补充失败时必须降级查询
        logger.warning(f"人工字幕搜索无法为整理历史 {target.history_id} 补充英文标题，将跳过依赖英文标题的查询")
        return target
    if resolution is None:
        return target
    target.context = resolution.context
    target.match_context = resolution.match_context
    return target
