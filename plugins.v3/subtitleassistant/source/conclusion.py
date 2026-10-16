"""一次来源查询结论的统一中文文案与来源名称常量。"""

from __future__ import annotations

from ..schemas.source import SourceSearchResult, SourceSearchStatus, SubtitleSource

SOURCE_NAMES: dict[SubtitleSource, str] = {
    SubtitleSource.MOVIEPILOT: "MoviePilot 站点字幕源",
    SubtitleSource.OPENSUBTITLES: "OpenSubtitles",
    SubtitleSource.ASSRT: "ASSRT",
}

SOURCE_SKIP_REASONS: dict[str, str] = {
    "english_title_missing": "缺少英文标题",
    "yake_unavailable": "英文关键词提取组件不可用",
    "keyword_extraction_failed": "英文关键词提取失败",
    "keyword_extraction_empty": "没有提取到可用的英文关键词",
    "no_subtitle_sites": "没有启用且支持字幕搜索的站点",
}


def source_run_is_warning(result: SourceSearchResult) -> bool:
    """判断一次来源结论是否应以警告级别记录。"""

    return result.status in {
        SourceSearchStatus.ERROR,
        SourceSearchStatus.LIMITED,
        SourceSearchStatus.PARTIAL,
    }


def describe_source_run(result: SourceSearchResult) -> str:
    """只用来源事实描述一次查询：状态六态、命中查询词、缓存复用与耗时。

    返回的句子不含任务或整理历史前缀，也不含准入漏斗结果——漏斗是分叉后的产物，
    由自动侧在准入步骤之后自行追加。
    """

    status = result.status
    if status is SourceSearchStatus.DISABLED:
        conclusion = "未执行：该来源未启用"
    elif status is SourceSearchStatus.UNCONFIGURED:
        conclusion = f"未执行：{SOURCE_SKIP_REASONS.get(result.skip_reason or '', '来源配置不完整')}"
    elif result.skip_reason:
        conclusion = f"未执行：{SOURCE_SKIP_REASONS.get(result.skip_reason, '缺少可用查询条件')}"
    elif status is SourceSearchStatus.ERROR:
        conclusion = f"失败：{result.error_summary or '字幕源请求异常'}"
    elif status is SourceSearchStatus.LIMITED:
        conclusion = f"受限：{result.error_summary or '字幕源暂时限制请求'}"
    elif status is SourceSearchStatus.PARTIAL:
        conclusion = f"部分完成：{result.error_summary or '分页未完整读取'}，已取得 {len(result.candidates)} 个候选"
    elif not result.candidates:
        conclusion = "完成：字幕站没有返回候选"
    else:
        conclusion = f"完成：字幕站返回 {len(result.candidates)} 个候选"

    parts = [conclusion]
    query = (result.matched_query or "").strip()
    if query:
        parts.append(f"命中查询词“{query}”")
    if result.cache_hit:
        parts.append("复用了缓存")
    parts.append(f"耗时 {result.duration_ms} 毫秒")
    return "；".join(parts)
