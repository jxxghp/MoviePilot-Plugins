"""字幕候选准入、排序与转换能力。"""

from .admission import (
    REJECTION_REASON_NAMES,
    admit_automatic_candidates,
    describe_rejections,
    has_exact_media_identity,
    normalized_imdb_id,
)
from .language import candidate_is_allowed, has_simplified_chinese, normalize_format_priority
from .ranking import candidate_from_record, candidate_rank, sort_candidates

__all__ = [
    "REJECTION_REASON_NAMES",
    "admit_automatic_candidates",
    "candidate_from_record",
    "candidate_is_allowed",
    "candidate_rank",
    "describe_rejections",
    "has_exact_media_identity",
    "has_simplified_chinese",
    "normalize_format_priority",
    "normalized_imdb_id",
    "sort_candidates",
]
