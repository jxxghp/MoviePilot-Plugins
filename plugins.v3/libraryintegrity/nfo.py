"""NFO 补充来源：路径映射、MP/Emby/Kodi 风格 NFO 解析与 strm 地址文件名提取。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import parse_qsl, unquote, urlparse

from .checks import normalize_codec, normalize_hdr, parse_int, resolution_bucket

# NFO 正常只有几 KB，超过上限视为异常文件，避免读入超大文件
MAX_NFO_BYTES = 1024 * 1024

_XML_DECLARATION = re.compile(r"<\?xml[^>]*\?>", re.IGNORECASE)
_VIDEO_NAME = re.compile(r"\.(mkv|mp4|m2ts|ts|avi|mov|wmv|flv|webm|iso|rmvb|m4v)$", re.IGNORECASE)


class PathMapper:
    """把媒体服务器看到的路径映射为 MoviePilot 可访问的本地路径。"""

    def __init__(self, rules_text: str = "") -> None:
        """解析映射规则：每行 "媒体服务器路径 => 本地路径"，按前缀长度从长到短匹配。"""
        rules: list[tuple[str, str]] = []
        for raw in str(rules_text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=>" not in line:
                continue
            source, _, target = line.partition("=>")
            source = source.strip().rstrip("/\\")
            target = target.strip().rstrip("/\\")
            if source and target:
                rules.append((source, target))
        self.rules = sorted(rules, key=lambda rule: len(rule[0]), reverse=True)

    def map(self, server_path: str) -> Optional[Path]:
        """返回映射后的本地路径；没有匹配规则时原样使用（两端挂载路径一致）。"""
        if not server_path:
            return None
        text = str(server_path)
        for source, target in self.rules:
            if text == source or text.startswith(source + "/") or text.startswith(source + "\\"):
                return Path(target + text[len(source):].replace("\\", "/"))
        return Path(text)


@dataclass
class NfoInfo:
    """NFO 中与完整性检查相关的字段。"""

    tmdb_id: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    resolution: Optional[str] = None
    video_codec: Optional[str] = None
    hdr: Optional[str] = None
    stale: bool = False


def _text(element: Optional[ET.Element], path: str) -> str:
    """读取子元素文本，不存在时返回空字符串。"""
    if element is None:
        return ""
    child = element.find(path)
    return (child.text or "").strip() if child is not None else ""


def _tmdb_id(element: ET.Element) -> Optional[int]:
    """读取 TMDB ID：优先 type="tmdb" 的 uniqueid，其次 tmdbid 标签。"""
    for unique in element.findall("uniqueid"):
        if str(unique.get("type") or "").lower() == "tmdb":
            value = parse_int(unique.text)
            if value:
                return value
    return parse_int(_text(element, "tmdbid")) or None


def parse_nfo_text(text: str, root_tag: str) -> list[NfoInfo]:
    """解析 NFO 文本中全部指定根标签的条目。

    Kodi 多集文件的 NFO 会连续写多个 <episodedetails>，不是合法的单根 XML，
    因此先去掉 XML 声明再包一层根节点解析。
    """
    body = _XML_DECLARATION.sub("", text or "")
    try:
        root = ET.fromstring(f"<nfo>{body}</nfo>")
    except ET.ParseError:
        return []
    results: list[NfoInfo] = []
    for element in root.findall(root_tag):
        info = NfoInfo(
            tmdb_id=_tmdb_id(element),
            season=parse_int(_text(element, "season")),
            episode=parse_int(_text(element, "episode")),
        )
        video = element.find("fileinfo/streamdetails/video")
        if video is not None:
            info.resolution = resolution_bucket(parse_int(_text(video, "width")), parse_int(_text(video, "height")))
            info.video_codec = normalize_codec(_text(video, "codec"))
            info.hdr = normalize_hdr(_text(video, "hdrtype"))
        results.append(info)
    return results


class NfoReader:
    """按需读取 NFO，并在一次扫描内缓存解析结果。"""

    def __init__(self, mapper: PathMapper) -> None:
        """记录路径映射并初始化缓存与计数。"""
        self.mapper = mapper
        self._cache: dict[str, list[NfoInfo]] = {}
        self.reads = 0

    def read_file(self, nfo_path: Path, root_tag: str, media_path: Optional[Path] = None) -> list[NfoInfo]:
        """读取并解析 NFO；文件不存在、过大或无法解析时返回空列表；传入媒体文件时比较新旧。"""
        key = f"{nfo_path}|{root_tag}"
        if key in self._cache:
            return self._cache[key]
        results: list[NfoInfo] = []
        try:
            stat = nfo_path.stat()
            if 0 < stat.st_size <= MAX_NFO_BYTES:
                self.reads += 1
                results = parse_nfo_text(nfo_path.read_text(encoding="utf-8", errors="replace"), root_tag)
                if results and media_path is not None:
                    try:
                        stale = stat.st_mtime < media_path.stat().st_mtime
                    except OSError:
                        stale = False
                    for info in results:
                        info.stale = stale
        except OSError:
            results = []
        self._cache[key] = results
        return results

    def episode(self, server_path: str) -> list[NfoInfo]:
        """读取单集文件同名 NFO，返回其中全部单集条目。"""
        media_path = self.mapper.map(server_path)
        if media_path is None:
            return []
        return self.read_file(media_path.with_suffix(".nfo"), "episodedetails", media_path)

    def series(self, server_path: str) -> Optional[NfoInfo]:
        """读取剧集目录下的 tvshow.nfo。"""
        series_path = self.mapper.map(server_path)
        if series_path is None:
            return None
        results = self.read_file(series_path / "tvshow.nfo", "tvshow")
        return results[0] if results else None


def strm_url_filename(url: str) -> str:
    """从 strm 内容地址中提取文件名，仅解析字符串，不发起网络请求。"""
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    path = parsed.path if parsed.scheme else text
    name = PurePosixPath(unquote(path).replace("\\", "/")).name
    if _VIDEO_NAME.search(name):
        return name
    # 部分网盘直链把文件路径放在查询参数里
    for _, value in parse_qsl(parsed.query):
        candidate = PurePosixPath(unquote(value).replace("\\", "/")).name
        if _VIDEO_NAME.search(candidate):
            return candidate
    return ""
