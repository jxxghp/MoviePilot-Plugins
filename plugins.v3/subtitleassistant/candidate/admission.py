"""自动准入的纯函数：语言、翻译类型与精确媒体身份判定。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..schemas.candidate import SubtitleCandidate, TranslationType
from ..schemas.source import CandidateHandle
from ..schemas.target import SubtitleTarget
from .language import candidate_is_allowed, has_simplified_chinese

REJECTION_REASON_NAMES: dict[str, str] = {
    "language": "语言不符合自动规则",
    "translation": "翻译类型不符合自动规则",
    "machine_translation": "机器翻译不符合自动规则",
    "foreign_parts_only": "仅外语对白字幕不符合自动规则",
    "download_locator": "缺少下载定位",
    "admission": "未通过来源基础规则",
    "duplicate": "重复候选",
    "query_unavailable": "缺少可用查询词",
    "media_or_episode_mismatch": "与当前媒体或季集不匹配",
}


def admit_automatic_candidates(
    candidates: Sequence[CandidateHandle],
    context: SubtitleTarget,
    *,
    allow_machine_translation: bool,
) -> tuple[list[CandidateHandle], dict[str, int]]:
    """对来源结果执行自动语言、翻译和精确身份准入，返回通过列表与排除摘要。

    只做纯判定：不调用宿主匹配器、不排序、不尝试下载。通过候选已标记
    ``exact_id_match`` 供后续排序使用；宿主匹配确认、排序与上限尝试留在 task 调用点。
    """

    admitted: list[CandidateHandle] = []
    rejected: dict[str, int] = {}
    for handle in candidates:
        candidate = handle.candidate.model_copy(deep=True)
        flags = candidate.metadata.get("language_flags")
        if not has_simplified_chinese(
            candidate.source,
            candidate.language,
            flags if isinstance(flags, Mapping) else None,
        ):
            rejected["language"] = rejected.get("language", 0) + 1
            continue
        if not candidate_is_allowed(candidate, allow_machine_translation):
            reason = (
                "machine_translation"
                if candidate.translation_type in {TranslationType.MACHINE, TranslationType.AI}
                else "foreign_parts_only"
            )
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        candidate.exact_id_match = has_exact_media_identity(candidate, context)
        admitted.append(CandidateHandle(candidate=candidate, download_handle=handle.download_handle))
    return admitted, rejected


def has_exact_media_identity(candidate: SubtitleCandidate, context: SubtitleTarget) -> bool:
    """判断候选是否携带与当前目标相同的 TMDB 或 IMDb 身份。"""

    if context.tmdb_id is not None and candidate.tmdb_id == context.tmdb_id:
        return True
    return bool(
        context.imdb_id
        and candidate.imdb_id
        and normalized_imdb_id(candidate.imdb_id) == normalized_imdb_id(context.imdb_id)
    )


def normalized_imdb_id(value: str | None) -> str | None:
    """规范化 IMDb 编号用于媒体身份比较。"""

    if not value:
        return None
    normalized = value.strip().lower().removeprefix("tt").lstrip("0")
    return normalized or "0"


def describe_rejections(summary: Mapping[str, int]) -> str:
    """把自动规则排除汇总转换为中文说明。"""

    parts = [
        f"{REJECTION_REASON_NAMES.get(reason, reason)} {count} 个" for reason, count in summary.items() if count > 0
    ]
    return "、".join(parts) or "无"
