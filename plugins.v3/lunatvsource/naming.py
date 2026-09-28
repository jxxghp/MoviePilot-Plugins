"""Conservative MoviePilot-compatible media path naming."""

from __future__ import annotations

import re
from pathlib import PurePath


INVALID = re.compile(r"[\\/:*?\"<>|]+")
SPACE = re.compile(r"\s+")

# Apple CMS names often carry publishing metadata in the title itself.  Keep
# this deliberately conservative: remove only suffixes that cannot be part of
# a real show title, while leaving ordinary punctuation and years untouched.
_SEASON_RANGE_SUFFIX = re.compile(
    r"(?:\s*[\(\[（【]?\s*)"
    r"(?:第\s*)?(?:\d{1,3}|[一二两三四五六七八九十百千万]+)\s*[-~至到]\s*"
    r"(?:第\s*)?(?:\d{1,3}|[一二两三四五六七八九十百千万]+)\s*季"
    r"(?:\s*[\)\]）】])?\s*$",
    re.IGNORECASE,
)
_SEASON_SUFFIX = re.compile(
    r"(?:\s*[\(\[（【]?\s*)(?:第\s*)?(?:\d{1,3}|[一二两三四五六七八九十百千万]+)\s*季(?:\s*[\)\]）】])?\s*$",
    re.IGNORECASE,
)
_EPISODE_SUFFIX = re.compile(
    r"\s*(?:S\s*\d{1,3}\s*E\s*\d{1,4}|第\s*(?:\d{1,4}|[一二两三四五六七八九十百千万]+)\s*[集话])\s*$",
    re.IGNORECASE,
)
_VIDEO_METADATA_SUFFIX = re.compile(
    r"(?:\s*[\(\[（【]?\s*)"
    r"(?:完结|全集|全季|高清|超清|蓝光|中字|双语|国语(?:版)?|粤语(?:版)?|"
    r"(?:中文|英语|日语|韩语|法语|德语|西班牙语)版|1080p|2160p|4k|web[- ]?dl|hdtv)"
    r"(?:\s*[\)\]）】])?\s*$",
    re.IGNORECASE,
)


def safe_component(value: str, fallback: str = "未命名") -> str:
    value = INVALID.sub(" ", str(value or ""))
    value = SPACE.sub(" ", value).strip(" .")
    return value or fallback


def normalize_media_title(value: str) -> str:
    """Return a stable display/search title without CMS bundle suffixes.

    The raw CMS title remains available in search results.  This helper is
    used only for folder/file naming and search fallback so a title such as
    ``海底小纵队中文版 (1-8季)`` does not become a misleading media folder.
    """

    result = SPACE.sub(" ", str(value or "")).strip()
    previous = None
    while result and result != previous:
        previous = result
        result = _SEASON_RANGE_SUFFIX.sub("", result).strip()
        # Search endpoints often publish one CMS row per episode, e.g.
        # ``小猪佩奇 第一季 第52集``.  Strip the trailing episode marker first
        # so the following season pass can collapse all rows into one season
        # resource card and one stable media folder.
        result = _EPISODE_SUFFIX.sub("", result).strip()
        result = _SEASON_SUFFIX.sub("", result).strip()
        result = _VIDEO_METADATA_SUFFIX.sub("", result).strip()
    return result or "未命名"


def normalize_search_title(value: str) -> str:
    """Conservative title used for CMS/TMDB lookup when AI is unavailable."""

    result = normalize_media_title(value)
    # Strip common release-group brackets only when they are clearly metadata.
    result = re.sub(
        r"\s*[\[【(（][^\]】)）]*(?:中字|双语|国语|粤语|1080p|2160p|4k|web[- ]?dl|hdtv)[^\]】)）]*[\]】)）]",
        " ",
        result,
        flags=re.IGNORECASE,
    )
    return SPACE.sub(" ", result).strip() or "未命名"


def extension_for_url(url: str, default: str = ".mp4") -> str:
    suffix = PurePath(url.split("?", 1)[0]).suffix.lower()
    if suffix in {".mp4", ".mkv", ".ts", ".mov", ".m4v", ".avi", ".webm"}:
        return suffix
    return default


def media_path(
    root: str,
    title: str,
    year: str,
    media_type: str,
    season: int,
    episode: int,
    url: str,
    mode: str = "download",
) -> tuple[str, str]:
    title_component = safe_component(normalize_media_title(title))
    year_component = f" ({safe_component(year, '')})" if str(year or "").strip() else ""
    display_title = f"{title_component}{year_component}"
    ext = ".strm" if mode == "strm" else extension_for_url(url)
    if media_type == "tv":
        season_number = max(0, int(season))
        season_dir = f"Season {season_number:02d}"
        filename = f"{display_title} - S{season_number:02d}E{max(1, int(episode)):02d}{ext}"
        return f"{display_title}/{season_dir}", filename
    return display_title, f"{display_title}{ext}"
