"""字幕候选确定性排序规则。"""

from datetime import datetime
from typing import Any

from ..schemas.candidate import PackageScope, SubtitleCandidate, TranslationType
from ..schemas.record import MatchRecord
from ..schemas.source import SubtitleSource

_TRANSLATION_ORDER = {
    TranslationType.HUMAN: 0,
    TranslationType.UNKNOWN: 1,
    TranslationType.MACHINE: 2,
    TranslationType.AI: 3,
}
_PACKAGE_ORDER = {
    PackageScope.SEASON_PACK: 0,
    PackageScope.EPISODE: 1,
    PackageScope.UNKNOWN: 2,
}


def _timestamp(value: datetime | None) -> float:
    """把可空时间转换为可排序时间戳。"""

    return value.timestamp() if value else 0.0


def _position(value: str, order: list[str]) -> int:
    """返回值在用户顺序中的位置。"""

    try:
        return order.index(value)
    except ValueError:
        return len(order)


def _source_quality(candidate: SubtitleCandidate) -> tuple[Any, ...]:
    """返回来源内部的稳定质量排序维度。"""

    if candidate.source is SubtitleSource.MOVIEPILOT:
        return (
            candidate.site_priority if candidate.site_priority is not None else 2**31,
            -(candidate.download_count or 0),
            -_timestamp(candidate.uploaded_at),
        )
    if candidate.source is SubtitleSource.OPENSUBTITLES:
        return (
            0 if candidate.trusted else 1,
            -(candidate.score or 0),
            -(candidate.votes or 0),
            -(candidate.download_count or 0),
            -_timestamp(candidate.uploaded_at),
        )
    return (
        -(candidate.score or 0),
        -_timestamp(candidate.uploaded_at),
        -(candidate.revision or 0),
    )


def candidate_rank(
    candidate: SubtitleCandidate,
    format_priority: list[str],
    source_priority: list[str],
    *,
    include_format: bool = False,
) -> tuple[Any, ...]:
    """返回候选排序键；库存消费可显式启用真实文件格式优先级。"""

    source_values = [str(item).lower() for item in source_priority]
    format_position = (
        _position(candidate.format.upper(), [item.upper() for item in format_priority]) if include_format else 0
    )
    return (
        _TRANSLATION_ORDER[candidate.translation_type],
        1 if candidate.hearing_impaired else 0,
        _PACKAGE_ORDER[candidate.package_scope],
        format_position,
        0 if candidate.exact_id_match else 1,
        _position(candidate.source.value, source_values),
        *_source_quality(candidate),
        candidate.candidate_key,
    )


def sort_candidates(
    candidates: list[SubtitleCandidate],
    format_priority: list[str],
    source_priority: list[str],
) -> list[SubtitleCandidate]:
    """按统一质量规则稳定排序字幕候选。"""

    return sorted(candidates, key=lambda item: candidate_rank(item, format_priority, source_priority))


def candidate_from_record(record: MatchRecord) -> SubtitleCandidate:
    """把暂存记录还原为可参与统一排序的安全候选。"""

    return SubtitleCandidate(
        candidate_key=record.candidate_key,
        source=record.source,
        name=record.candidate_name or record.subtitle_file_name,
        file_name=record.subtitle_file_name,
        format=record.format,
        language=record.language,
        translation_type=record.translation_type,
        hearing_impaired=record.hearing_impaired,
        package_scope=record.package_scope,
        season=record.season,
        episode=record.episode,
        tmdb_id=record.tmdb_id,
        imdb_id=record.imdb_id,
        exact_id_match=record.exact_id_match,
        site_priority=record.site_priority,
        trusted=record.trusted,
        score=record.score,
        votes=record.votes,
        download_count=record.download_count,
        uploaded_at=record.uploaded_at,
        revision=record.revision,
    )
