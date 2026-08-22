"""Conservative MoviePilot-compatible media path naming."""

from __future__ import annotations

import re
from pathlib import PurePath


INVALID = re.compile(r"[\\/:*?\"<>|]+")
SPACE = re.compile(r"\s+")


def safe_component(value: str, fallback: str = "未命名") -> str:
    value = INVALID.sub(" ", str(value or ""))
    value = SPACE.sub(" ", value).strip(" .")
    return value or fallback


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
    title_component = safe_component(title)
    year_component = f" ({safe_component(year, '')})" if str(year or "").strip() else ""
    display_title = f"{title_component}{year_component}"
    ext = ".strm" if mode == "strm" else extension_for_url(url)
    if media_type == "tv":
        season_dir = f"Season {max(1, int(season)):02d}"
        filename = f"{display_title} - S{max(1, int(season)):02d}E{max(1, int(episode)):02d}{ext}"
        return f"{display_title}/{season_dir}", filename
    return display_title, f"{display_title}{ext}"
