"""简体中文字幕准入与格式归一规则。"""

import re
from collections.abc import Iterable, Mapping

from ..schemas.candidate import SubtitleCandidate, TranslationType
from ..schemas.source import SubtitleSource

_MP_EXPLICIT = re.compile(r"(?:简体|简中|zh[-_ ]?cn|zh[-_ ]?hans|\bchs\b)", re.IGNORECASE)
_ASSRT_EXPLICIT = re.compile(r"(?:简体|简中|zh[-_ ]?cn|zh[-_ ]?hans|\bchs\b)", re.IGNORECASE)
_ASSRT_FLAG_KEYS = {"langchs", "zh-cn", "zh_cn", "zh-hans", "chs"}
_DEFAULT_FORMAT_ORDER = ("ASS", "SSA", "SRT", "SUP")


def has_simplified_chinese(
    source: SubtitleSource,
    marker: str | None,
    flags: Mapping[str, object] | None = None,
) -> bool:
    """按字幕源明确标记判断候选是否含简体中文。"""

    language = (marker or "").strip()
    if source is SubtitleSource.OPENSUBTITLES:
        return language.lower().replace("_", "-") == "zh-cn"
    if source is SubtitleSource.MOVIEPILOT:
        return bool(_MP_EXPLICIT.search(language))
    if _ASSRT_EXPLICIT.search(language):
        return True
    normalized_flags = {str(key).strip().lower() for key, value in (flags or {}).items() if bool(value)}
    return bool(normalized_flags & _ASSRT_FLAG_KEYS)


def candidate_is_allowed(candidate: SubtitleCandidate, allow_machine: bool) -> bool:
    """判断候选是否满足翻译类型与内容范围约束。"""

    if candidate.foreign_parts_only:
        return False
    return allow_machine or candidate.translation_type not in {TranslationType.MACHINE, TranslationType.AI}


def normalize_format_priority(
    allowed_extensions: Iterable[str],
    saved_priority: Iterable[str] | None = None,
) -> list[str]:
    """将配置顺序归一为宿主允许的完整且无重复格式列表。"""

    allowed: list[str] = []
    for item in allowed_extensions:
        normalized = str(item).strip().lstrip(".").upper()
        if normalized and normalized not in allowed:
            allowed.append(normalized)

    preferred = list(saved_priority or _DEFAULT_FORMAT_ORDER)
    result: list[str] = []
    for item in preferred:
        normalized = str(item).strip().lstrip(".").upper()
        if normalized in allowed and normalized not in result:
            result.append(normalized)
    result.extend(item for item in allowed if item not in result)
    return result
