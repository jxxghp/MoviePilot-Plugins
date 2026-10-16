"""字幕目标目录、路径解析与宿主目标投影能力的调用侧契约。"""

from .history import TargetCatalogService as TargetCatalog
from .projection import (
    MediaResolution,
    MediaResolver,
    build_media_context,
    enrich_search_target,
    match_context_from_history,
    match_context_from_mediainfo,
    target_from_history,
)

__all__ = [
    "MediaResolution",
    "MediaResolver",
    "TargetCatalog",
    "build_media_context",
    "enrich_search_target",
    "match_context_from_history",
    "match_context_from_mediainfo",
    "target_from_history",
]
