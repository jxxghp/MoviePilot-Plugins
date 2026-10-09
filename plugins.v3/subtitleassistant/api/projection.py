"""搜索相关的 HTTP 投影：整理目标与人工来源结果。"""

from __future__ import annotations

from ..schemas.candidate import CandidateRecognition
from ..schemas.http.search import ManualCandidateItem, ManualSourceResult, SearchPlanItem
from ..schemas.http.target import TargetListItem
from ..schemas.search import ManualSourceView
from ..schemas.source import SubtitleSource
from ..schemas.target import SearchTarget
from ..source import SourceAdministration


def target_item(target: SearchTarget, sources: SourceAdministration) -> TargetListItem:
    """把整理历史目标投影为 HTTP 目标项，查询计划取自来源 adapter 结构化计划。"""

    context = target.context
    plans = {
        source: [
            SearchPlanItem(kind=entry.kind, label=entry.label, query=entry.query, editable=entry.editable)
            for entry in sources.default_queries(source, context)
        ]
        for source in SubtitleSource
    }
    return TargetListItem(
        history_id=target.history_id,
        media_title=context.title,
        year=context.year,
        media_type=context.media_type,
        season=context.season,
        episode=context.episode,
        tmdb_id=context.tmdb_id,
        imdb_id=context.imdb_id,
        target_file_name=context.target_file_name,
        target_path=str(context.target_path),
        organized_at=target.transferred_at,
        search_plans=plans,
    )


def source_item(view: ManualSourceView) -> ManualSourceResult:
    """把人工来源结果投影为不含下载定位的最小 HTTP 显示字段。"""

    def candidate_item(recognition: CandidateRecognition) -> ManualCandidateItem:
        """把一条候选识别标注投影为安全候选项。"""

        candidate = recognition.candidate
        return ManualCandidateItem(
            candidate_key=candidate.candidate_key,
            recognition_status=recognition.status,
            source=candidate.source,
            name=candidate.name,
            file_name=candidate.file_name,
            language=candidate.language or None,
            format=candidate.format or "UNKNOWN",
            package_scope=candidate.package_scope,
            season=candidate.season,
            episode=candidate.episode,
            seasons=list(candidate.seasons),
            episodes=list(candidate.episodes),
            translation_type=candidate.translation_type,
            hearing_impaired=candidate.hearing_impaired,
        )

    run = view.run
    return ManualSourceResult(
        source=run.source,
        status=run.status.value,
        default_plans=[
            SearchPlanItem(kind=entry.kind, label=entry.label, query=entry.query, editable=entry.editable)
            for entry in run.default_queries
        ],
        matched_query=run.matched_query,
        candidate_count=view.candidate_count,
        cache_hit=run.cache_hit,
        duration_ms=run.duration_ms,
        error_code=run.error_code,
        error_summary=run.error_summary,
        retry_after_seconds=run.retry_after_seconds,
        candidates=[candidate_item(item) for item in view.candidates],
    )
