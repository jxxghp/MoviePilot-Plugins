"""Emby 数据源：经宿主 Emby 服务实例读取媒体库、剧集、单集与电影，并解析版本信息。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import PurePath
from typing import Any, Callable, Iterator, Optional
from urllib.parse import quote, urlencode

from app.sdk.logging import logger

from .checks import (
    normalize_audio,
    normalize_bit_depth,
    normalize_codec,
    normalize_hdr,
    normalize_resolution_text,
    parse_int,
    resolution_bucket,
)
from .models import ORIGIN_EMBY, LibraryEpisode, LibraryMovie, LibrarySeries, SourceError, VersionInfo
from .nfo import NfoReader, strm_url_filename

# 不含影视内容的媒体库类型
_SKIPPED_COLLECTIONS = {"music", "books", "boxsets", "playlists", "musicvideos", "photos", "livetv", "audiobooks"}

EPISODE_FIELDS = "Path,ProviderIds,MediaSources,ParentIndexNumber,IndexNumberEnd,LocationType"
SERIES_FIELDS = "Path,ProviderIds,ProductionYear"
MOVIE_FIELDS = "Path,ProviderIds,ProductionYear,MediaSources"

NameParser = Callable[[str], dict[str, Optional[str]]]


class EmbyError(SourceError):
    """Emby 请求失败。"""


@lru_cache(maxsize=8192)
def parse_release_name(name: str) -> dict[str, Optional[str]]:
    """用宿主文件名识别解析发布信息：分辨率、编码、HDR、音频与发布组；解析失败时返回空结果。"""
    from app.sdk.media import MetaInfo

    try:
        # 文件名可能以 .AAC 等音频编码结尾，强制按视频解析，避免被当作音频文件
        meta = MetaInfo(name, force_video=True)
    except Exception as err:  # noqa: BLE001 - 单个文件名解析失败不应中断整轮扫描
        logger.debug(f"影视库完整性检查：文件名解析失败 {name}：{err}")
        return {}
    return {
        "resolution": normalize_resolution_text(meta.resource_pix),
        "video_codec": normalize_codec(meta.video_encode),
        "hdr": normalize_hdr(meta.resource_effect),
        "audio_codec": normalize_audio(meta.audio_encode),
        "release_group": (meta.resource_team or "").strip() or None,
    }


def provider_tmdb_id(item: dict) -> Optional[int]:
    """从 Emby 条目的 ProviderIds 读取 TMDB ID（键名大小写不固定）。"""
    providers = item.get("ProviderIds") or {}
    if not isinstance(providers, dict):
        return None
    for key, value in providers.items():
        if str(key).lower() == "tmdb":
            return parse_int(value) or None
    return None


def is_virtual(item: dict) -> bool:
    """判断是否为 Emby "显示缺失集"生成的占位条目，占位条目不代表库中已有文件。"""
    return str(item.get("LocationType") or "").lower() == "virtual" or bool(item.get("IsMissing"))


def _first_stream(streams: list, stream_type: str) -> Optional[dict]:
    """返回指定类型的首个媒体流，音频优先默认轨。"""
    candidates = [s for s in streams if isinstance(s, dict) and str(s.get("Type") or "").lower() == stream_type]
    if not candidates:
        return None
    if stream_type == "audio":
        for stream in candidates:
            if stream.get("IsDefault"):
                return stream
    return candidates[0]


def version_from_source(source: dict, item_path: str) -> VersionInfo:
    """从 Emby MediaSource 读取版本：技术参数来自媒体流探测结果，strm 未播放时通常为空。"""
    item_path = str(item_path or "")
    source_path = str(source.get("Path") or "")
    is_strm = (
        item_path.lower().endswith(".strm")
        or str(source.get("Container") or "").lower() == "strm"
        or str(source.get("Protocol") or "").lower() == "http"
        or bool(source.get("IsRemote"))
    )
    version = VersionInfo(
        path=item_path if is_strm and item_path else (source_path or item_path),
        kind="strm" if is_strm else "file",
        name=str(source.get("Name") or ""),
        url=source_path if is_strm and "://" in source_path else "",
    )
    streams = source.get("MediaStreams") or []
    video = _first_stream(streams, "video")
    if video:
        version.fill("resolution", resolution_bucket(parse_int(video.get("Width")), parse_int(video.get("Height"))), "emby")
        version.fill("video_codec", normalize_codec(video.get("Codec")), "emby")
        version.fill(
            "hdr",
            normalize_hdr(video.get("ExtendedVideoType"), video.get("DisplayTitle"), video.get("VideoRange")),
            "emby",
        )
        version.fill("bit_depth", normalize_bit_depth(video.get("BitDepth")), "emby")
    audio = _first_stream(streams, "audio")
    if audio:
        version.fill("audio_codec", normalize_audio(audio.get("Codec")), "emby")
    return version


def fill_from_names(version: VersionInfo, parser: NameParser = parse_release_name) -> None:
    """用文件名与 strm 地址中的发布信息补齐仍未知的维度。"""
    candidates = []
    if version.path:
        candidates.append((PurePath(version.path.replace("\\", "/")).name, "filename"))
    if version.url:
        url_name = strm_url_filename(version.url)
        if url_name:
            candidates.append((url_name, "url"))
    for name, source in candidates:
        if not name:
            continue
        for dimension, value in parser(name).items():
            version.fill(dimension, value, source)


def parse_versions(item: dict) -> list[VersionInfo]:
    """读取条目的全部版本；没有 MediaSources 时按条目路径生成一个版本。"""
    item_path = str(item.get("Path") or "")
    sources = [source for source in item.get("MediaSources") or [] if isinstance(source, dict)]
    versions = [version_from_source(source, item_path) for source in sources]
    if not versions and item_path:
        versions = [VersionInfo(path=item_path, kind="strm" if item_path.lower().endswith(".strm") else "file")]
    return versions


def parse_episode(item: dict) -> LibraryEpisode:
    """把 Emby 单集条目转换为库内单集。"""
    tmdb_id = provider_tmdb_id(item)
    return LibraryEpisode(
        item_id=str(item.get("Id") or ""),
        season=parse_int(item.get("ParentIndexNumber")),
        episode=parse_int(item.get("IndexNumber")),
        episode_end=parse_int(item.get("IndexNumberEnd")),
        tmdb_id=tmdb_id,
        tmdb_id_source="emby" if tmdb_id else "",
        path=str(item.get("Path") or ""),
        versions=parse_versions(item),
    )


def parse_movie(item: dict, server: str, library: str) -> LibraryMovie:
    """把 Emby 电影条目转换为库内电影。"""
    return LibraryMovie(
        server=server,
        library=library,
        item_id=str(item.get("Id") or ""),
        title=str(item.get("Name") or ""),
        year=str(item.get("ProductionYear") or ""),
        tmdb_id=provider_tmdb_id(item),
        versions=parse_versions(item),
    )


def select_libraries(libraries: list[dict], names: list[str]) -> list[tuple[str, str, str]]:
    """筛选需要扫描的影视媒体库，返回 (名称, ID, 类型)；未指定名称时跳过家庭视频库。"""
    wanted = {name.strip() for name in names if name and name.strip()}
    selected: list[tuple[str, str, str]] = []
    for library in libraries:
        if not isinstance(library, dict):
            continue
        name = str(library.get("Name") or "")
        collection = str(library.get("CollectionType") or "").lower()
        if collection in _SKIPPED_COLLECTIONS:
            continue
        if wanted and name not in wanted:
            continue
        if collection == "homevideos" and not wanted:
            continue
        library_id = str(library.get("ItemId") or library.get("Id") or "")
        if library_id:
            selected.append((name, library_id, collection))
    return selected


class EmbyReader:
    """Emby 只读客户端；地址、密钥和用户由宿主服务实例按占位符注入，插件不持有凭据。"""

    def __init__(self, name: str, instance: Any, page_size: int = 200) -> None:
        """记录服务名称与宿主 Emby 实例。"""
        self.name = name
        self._instance = instance
        self._page_size = page_size

    def _request(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        """发送 GET 请求并解析 JSON；占位符不能被 URL 编码，因此单独拼接。

        不带 UserId：Emby 的用户视图会把同一集或同一电影的多个条目合并为一个，
        并只返回其中一个文件，多文件检查因此会漏报；服务器 API Key 可以直接读取完整媒体库。
        """
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"[HOST]emby/{path}?{query + '&' if query else ''}api_key=[APIKEY]"
        response = self._instance.get_data(url)
        if response is None:
            raise EmbyError(f"{self.name} 请求 {path} 无响应")
        try:
            status = getattr(response, "status_code", 200)
            if status >= 300:
                raise EmbyError(f"{self.name} 请求 {path} 返回 HTTP {status}")
            try:
                return response.json()
            except ValueError as err:
                raise EmbyError(f"{self.name} 请求 {path} 返回内容无法解析") from err
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def libraries(self) -> list[dict]:
        """读取全部媒体库。"""
        data = self._request("Library/VirtualFolders")
        return [library for library in data or [] if isinstance(library, dict)]

    def iter_items(self, parent_id: str, item_types: str, fields: str) -> Iterator[dict]:
        """分页遍历媒体库内指定类型的条目；某页没有新条目时停止，防止服务端忽略分页参数导致死循环。"""
        start = 0
        seen: set[str] = set()
        while True:
            data = self._request(
                "Items",
                {
                    "ParentId": parent_id,
                    "Recursive": "true",
                    "IncludeItemTypes": item_types,
                    "Fields": fields,
                    "StartIndex": start,
                    "Limit": self._page_size,
                    "SortBy": "SortName",
                    "EnableImages": "false",
                    "EnableTotalRecordCount": "false",
                },
            )
            items = [item for item in (data or {}).get("Items") or [] if isinstance(item, dict)]
            fresh = [item for item in items if str(item.get("Id") or "") not in seen]
            seen.update(str(item.get("Id") or "") for item in fresh)
            yield from fresh
            if len(items) < self._page_size or not fresh:
                return
            start += self._page_size

    def series_episodes(self, series_id: str) -> list[dict]:
        """读取一部剧的全部单集（不含缺失占位条目）。"""
        data = self._request(
            f"Shows/{quote(str(series_id), safe='')}/Episodes",
            {"Fields": EPISODE_FIELDS, "IsMissing": "false", "EnableImages": "false"},
        )
        return [item for item in (data or {}).get("Items") or [] if isinstance(item, dict) and not is_virtual(item)]


class EmbySource:
    """把 Emby 读取器适配为扫描数据源：按媒体库产出剧集（含单集）与电影。"""

    origin = ORIGIN_EMBY

    def __init__(self, reader: EmbyReader, library_names: list[str], nfo: Optional[NfoReader] = None) -> None:
        """记录读取器、媒体库筛选与 NFO 读取器（需要路径映射）。"""
        self.reader = reader
        self.name = reader.name
        self.nfo = nfo
        self._library_names = library_names

    def libraries(self) -> list[tuple[str, str, str]]:
        """返回需要扫描的影视媒体库。"""
        return select_libraries(self.reader.libraries(), self._library_names)

    def iter_series(self, library: tuple[str, str, str]) -> Iterator[LibrarySeries]:
        """逐部读取剧集与单集；单集读取失败时记录在剧集的 error 中继续下一部。"""
        name, library_id, collection = library
        if collection == "movies":
            return
        for item in self.reader.iter_items(library_id, "Series", SERIES_FIELDS):
            tmdb_id = provider_tmdb_id(item)
            series = LibrarySeries(
                server=self.name,
                library=name,
                item_id=str(item.get("Id") or ""),
                title=str(item.get("Name") or ""),
                year=str(item.get("ProductionYear") or ""),
                tmdb_id=tmdb_id,
                tmdb_id_source="emby" if tmdb_id else "",
                path=str(item.get("Path") or ""),
            )
            try:
                series.episodes = [parse_episode(raw) for raw in self.reader.series_episodes(series.item_id)]
            except EmbyError as err:
                series.error = f"读取单集失败：{err}"
            yield series

    def iter_movies(self, library: tuple[str, str, str]) -> Iterator[LibraryMovie]:
        """逐部读取电影。"""
        name, library_id, collection = library
        if collection == "tvshows":
            return
        for item in self.reader.iter_items(library_id, "Movie", MOVIE_FIELDS):
            yield parse_movie(item, self.name, name)

