"""扫描编排：遍历各数据源（Emby、本地目录），补充 NFO，执行规则检查，按预算请求并验证 AI 建议，汇总报告。"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterator, Optional, Protocol

from app.sdk.logging import logger

from .ai import (
    FAILED_RETRY_DAYS,
    AiAdvisor,
    AiAnswerCache,
    CachedAnswer,
    IdentityAnswer,
    IdentityTask,
    NumberingAnswer,
    NumberingTask,
    task_fingerprint,
)
from .checks import (
    EpisodeMatch,
    IgnoreRule,
    NumberMapping,
    apply_ignore_rules,
    conflict_issues,
    duplicate_issues,
    find_missing,
    identity_coverage,
    mapping_date_check,
    match_episodes,
    missing_issues,
    movie_duplicate_issues,
    numbering_improves,
    numbering_misaligned,
    placeholder_tail_issue,
    placeholder_tail_seasons,
    series_scope,
    source_scope,
    split_episode_issue,
    split_episode_seasons,
    suggestion_issue,
    summarize_match,
    unchecked_issue,
    unreliable_missing_issue,
    version_issues,
)
from .emby import NameParser, fill_from_names, parse_release_name
from .models import (
    ISSUE_TYPE_LABELS,
    ORIGIN_EMBY,
    ORIGIN_LOCAL,
    Issue,
    IssueType,
    LibraryEpisode,
    LibraryMovie,
    LibrarySeries,
    Report,
    SourceError,
    TmdbSeries,
)
from .nfo import NfoReader
from .tmdb import TmdbLookupError, TmdbSource

# 报告中保存的问题上限，避免超大媒体库把插件数据撑得过大
MAX_ISSUES = 5000
# AI 建议需要达到的最低把握程度
MIN_AI_CONFIDENCE = 0.5
# AI 选择的身份需要覆盖的库内单集比例
MIN_IDENTITY_COVERAGE = 0.8
# 每个身份任务提供给 AI 的候选数量
MAX_CANDIDATES = 5


class LibrarySource(Protocol):
    """扫描数据源：按媒体库产出剧集（含单集）与电影。"""

    name: str
    origin: str
    nfo: Optional[NfoReader]

    def libraries(self) -> list[tuple[str, str, str]]:
        """返回 (名称, ID, 类型) 列表。"""

    def iter_series(self, library: tuple[str, str, str]) -> Iterator[LibrarySeries]:
        """产出媒体库内的剧集。"""

    def iter_movies(self, library: tuple[str, str, str]) -> Iterator[LibraryMovie]:
        """产出媒体库内的电影。"""


@dataclass
class ScanOptions:
    """一次扫描使用的检查选项与已采纳的规则。"""

    check_missing: bool = True
    check_versions: bool = True
    check_duplicates: bool = True
    dimensions: list[str] = field(default_factory=lambda: ["resolution", "video_codec", "hdr"])
    air_buffer_days: int = 2
    include_specials: bool = False
    only_existing_seasons: bool = False
    ignore_mixed: bool = False
    number_mappings: dict[str, list[NumberMapping]] = field(default_factory=dict)
    identity_overrides: dict[str, int] = field(default_factory=dict)
    ignore_rules: list[IgnoreRule] = field(default_factory=list)
    ai_summary: bool = False


_LABEL = re.compile(r"S(\d+)E(\d+)")


def _episode_numbers(labels: list[str]) -> set[tuple[int, int]]:
    """把 S05E01 形式的标签解析为 (季, 集)。"""
    return {(int(m.group(1)), int(m.group(2))) for m in (_LABEL.fullmatch(label) for label in labels) if m}


class LibraryScanner:
    """执行一次只读扫描；所有外部依赖由调用方注入，便于测试与停止。"""

    def __init__(
        self,
        options: ScanOptions,
        tmdb: Optional[TmdbSource],
        stop_event: threading.Event,
        progress: Callable[[str], None] = lambda _text: None,
        today: Optional[date] = None,
        name_parser: NameParser = parse_release_name,
        advisor: Optional[AiAdvisor] = None,
        ai_cache: Optional[AiAnswerCache] = None,
    ) -> None:
        """记录扫描选项与依赖；ai_cache 为空时每次都重新请求 AI。"""
        self.options = options
        self.tmdb = tmdb
        self.stop_event = stop_event
        self.progress = progress
        self.today = today or date.today()
        self.name_parser = name_parser
        self.advisor = advisor
        self.ai_cache = ai_cache
        self.report = Report()
        self._issues: list[Issue] = []
        self._numbering_tasks: list[NumberingTask] = []
        self._identity_tasks: list[IdentityTask] = []

    def _add(self, issues: list[Issue]) -> None:
        """追加问题，超过上限时只计截断标记。"""
        room = MAX_ISSUES - len(self._issues)
        if len(issues) > room:
            self.report.truncated = True
        self._issues.extend(issues[:max(0, room)])

    def scan(self, sources: list[LibrarySource]) -> Report:
        """扫描全部数据源并返回报告。"""
        started = time.monotonic()
        self.report.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for source in sources:
            if self.stop_event.is_set():
                break
            self.report.stats.servers.append(source.name)
            self._scan_source(source)
        if self.advisor is not None and not self.stop_event.is_set():
            self._run_ai()
        self.report.cancelled = self.stop_event.is_set()
        self.report.issues = self._issues
        self.report.stats.nfo_reads = sum(source.nfo.reads for source in sources if source.nfo is not None)
        if self.tmdb is not None:
            self.report.stats.tmdb_requests = self.tmdb.requests
        if self.advisor is not None:
            self.report.stats.ai_calls = self.advisor.calls
            counts = Counter(self.advisor.errors)
            self.report.errors.extend(
                f"{error}（共 {count} 次）" if count > 1 else error for error, count in list(counts.items())[:5]
            )
        self.report.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.report.duration_seconds = round(time.monotonic() - started, 1)
        return self.report

    def _scan_source(self, source: LibrarySource) -> None:
        """扫描一个数据源的选定媒体库。"""
        try:
            libraries = source.libraries()
        except SourceError as err:
            self.report.errors.append(str(err))
            return
        if not libraries:
            self.report.errors.append(f"{source.name} 没有匹配的影视媒体库")
            return
        movies: list[LibraryMovie] = []
        for library in libraries:
            if self.stop_event.is_set():
                return
            self.report.stats.libraries += 1
            self.progress(f"{source.name} / {library[0]}：正在读取")
            try:
                for series in source.iter_series(library):
                    if self.stop_event.is_set():
                        return
                    self._scan_series(source, series)
                if self.options.check_duplicates:
                    for movie in source.iter_movies(library):
                        if self.stop_event.is_set():
                            return
                        self._apply_override(movie)
                        for version in movie.versions:
                            fill_from_names(version, self.name_parser)
                        movies.append(movie)
                        self.report.stats.movies += 1
            except SourceError as err:
                self.report.errors.append(f"{source.name} / {library[0]}：{err}")
        if movies:
            self._add(movie_duplicate_issues(movies, self.options.ignore_mixed))

    def _apply_override(self, media: LibrarySeries | LibraryMovie) -> None:
        """按身份覆盖规则设置 TMDB ID；覆盖规则优先于媒体服务器与 NFO 中的 ID。"""
        key = source_scope(media.server, media.item_id, media.origin).lower()
        override = self.options.identity_overrides.get(key)
        if override:
            media.tmdb_id = override
            if isinstance(media, LibrarySeries):
                media.tmdb_id_source = "override"

    def _ignored(self, issue_type: IssueType, scope: str) -> bool:
        """判断某类问题在指定范围内是否已被忽略，用于跳过不必要的 AI 请求。"""
        return any(rule.matches(issue_type, scope) for rule in self.options.ignore_rules)

    def _scan_series(self, source: LibrarySource, series: LibrarySeries) -> None:
        """检查一部剧。"""
        self.report.stats.series += 1
        self.progress(f"{source.name} / {series.library} / {series.title}（第 {self.report.stats.series} 部）")
        self._apply_override(series)
        if series.error:
            self._add([unchecked_issue(series, series.error)])
            return
        self.report.stats.episodes += len(series.episodes)
        if source.nfo is not None:
            self._supplement_from_nfo(source.nfo, series)
        for episode in series.episodes:
            for version in episode.versions:
                fill_from_names(version, self.name_parser)

        issues: list[Issue] = []
        matches = None
        tmdb_series: Optional[TmdbSeries] = None
        if self.options.check_missing and self.tmdb is not None:
            if not series.tmdb_id:
                issues.append(unchecked_issue(series, "缺少 TMDB ID，无法核对缺集"))
                self._queue_identity(series)
            else:
                try:
                    tmdb_series = self.tmdb.get_series(series.tmdb_id)
                except TmdbLookupError as err:
                    issues.append(unchecked_issue(series, f"TMDB 查询失败，未核对缺集：{err}"))
                    logger.debug(f"影视库完整性检查：{series.title} TMDB 查询失败：{err}")
                else:
                    mappings = self.options.number_mappings.get(f"tmdb:{series.tmdb_id}")
                    matches = match_episodes(series, tmdb_series, mappings)
                    missing = find_missing(
                        tmdb_series,
                        matches,
                        self.today,
                        buffer_days=self.options.air_buffer_days,
                        include_specials=self.options.include_specials,
                        only_existing_seasons=self.options.only_existing_seasons,
                    )
                    # 编号对不上时缺集是按错位的编号算出来的，直接报告会产生大量假缺集
                    if missing and numbering_misaligned(matches, tmdb_series, self.options.include_specials):
                        issues.append(unreliable_missing_issue(series, missing))
                    else:
                        # 一个文件含 TMDB 两集的季，后半季会被误当作缺集
                        split = split_episode_seasons(matches, tmdb_series, missing)
                        if split:
                            issues.append(split_episode_issue(series, tmdb_series, split, matches))
                            missing = {season: refs for season, refs in missing.items() if season not in split}
                        # 已完结剧 TMDB 季末后补的无标题占位集，多半是 TMDB 数据错误
                        tails = placeholder_tail_seasons(tmdb_series, matches, missing)
                        if tails:
                            issues.append(placeholder_tail_issue(series, tails))
                            missing = {season: refs for season, refs in missing.items() if season not in tails}
                        issues.extend(missing_issues(series, missing))
                    self._queue_numbering(series, tmdb_series, matches)
        issues.extend(conflict_issues(series, matches, self.options.include_specials, tmdb_series))
        if self.options.check_versions and self.options.dimensions:
            issues.extend(version_issues(series, self.options.dimensions, self.options.include_specials))
        if self.options.check_duplicates:
            issues.extend(duplicate_issues(series, matches, self.options.ignore_mixed, self.options.include_specials))
        self._add(issues)

    # ------------------------------------------------------------------
    # NFO 补充
    # ------------------------------------------------------------------

    def _supplement_from_nfo(self, nfo: NfoReader, series: LibrarySeries) -> None:
        """按需读取 NFO：补剧集 ID、补单集 ID、补 strm 技术参数与播出日期，并校验季集号。"""
        if not series.tmdb_id and series.path:
            info = nfo.series(series.path)
            if info and info.tmdb_id:
                series.tmdb_id = info.tmdb_id
                series.tmdb_id_source = "nfo"
        for episode in series.episodes:
            self._supplement_episode(nfo, episode, series.tmdb_id, series.origin)

    @staticmethod
    def _supplement_episode(
        nfo: NfoReader, episode: LibraryEpisode, series_tmdb_id: Optional[int], origin: str = ORIGIN_EMBY
    ) -> None:
        """为单集读取同名 NFO；只在缺单集 ID 或 strm 技术参数未知时读取，避免全量读盘。"""
        needs_id = episode.tmdb_id is None
        needs_tech = any(
            version.kind == "strm" and (version.resolution is None or version.video_codec is None or version.hdr is None)
            for version in episode.versions
        )
        if not episode.path or not (needs_id or needs_tech):
            return
        infos = nfo.episode(episode.path)
        if not infos:
            return
        info = next((i for i in infos if i.episode == episode.episode), infos[0])
        # 旧版 MP 曾把剧集 ID 写入单集 NFO，与剧集 ID 相同的值视为无效
        if needs_id and info.tmdb_id and info.tmdb_id != series_tmdb_id:
            episode.tmdb_id = info.tmdb_id
            episode.tmdb_id_source = "nfo"
        if (
            info.season is not None and info.episode is not None
            and episode.season is not None and episode.episode is not None
            and (info.season != episode.season or info.episode not in episode.episode_numbers)
        ):
            # 本地目录的季集号来自目录与文件名，Emby 的来自媒体服务器
            where = "库内文件为" if origin == ORIGIN_LOCAL else "媒体服务器为"
            note = f"NFO 记录为 S{info.season:02d}E{info.episode:02d}，{where} {episode.label}"
            if info.stale:
                note += "（NFO 早于视频文件，可能已过期）"
            episode.conflicts.append(note)
        if not episode.air_date and info.aired:
            episode.air_date = info.aired
        for version in episode.versions:
            if version.kind == "strm":
                version.fill("resolution", info.resolution, "nfo")
                version.fill("video_codec", info.video_codec, "nfo")
                version.fill("hdr", info.hdr, "nfo")

    # ------------------------------------------------------------------
    # AI 建议
    # ------------------------------------------------------------------

    def _ai_budget_left(self) -> bool:
        """判断是否还能排入新的 AI 任务。"""
        if self.advisor is None:
            return False
        if self.advisor.max_calls is None:
            return True
        queued = len(self._numbering_tasks) + len(self._identity_tasks)
        reserve = 1 if self.options.ai_summary else 0
        return queued < self.advisor.max_calls - reserve

    def _queue_numbering(self, series: LibrarySeries, tmdb_series: TmdbSeries, matches: list[EpisodeMatch]) -> None:
        """剧集存在按季集号无法对应的单集时，排入编号映射任务。"""
        if not self._ai_budget_left():
            return
        unmatched = [
            f"S{m.episode.season:02d}E{n:02d}"
            for m in matches
            if m.episode.season is not None and (self.options.include_specials or m.episode.season != 0)
            # TMDB 已建季但暂无单集时，只能等 TMDB 补全，编号映射帮不上忙
            and not (m.episode.season in tmdb_series.seasons and not tmdb_series.seasons[m.episode.season])
            for n in m.unmatched_numbers
        ]
        scope = series_scope(series.tmdb_id, series.server, series.item_id, series.origin)
        if not unmatched or self._ignored(IssueType.SUGGESTION, scope):
            return
        self._numbering_tasks.append(NumberingTask(series=series, tmdb=tmdb_series, base=f"tmdb:{series.tmdb_id}", unmatched=unmatched))

    def _queue_identity(self, series: LibrarySeries) -> None:
        """剧集缺少 TMDB ID 时排入身份选择任务，候选在执行 AI 前才查询。"""
        if not self._ai_budget_left() or not series.episodes:
            return
        if self._ignored(IssueType.SUGGESTION, series_scope(None, series.server, series.item_id, series.origin)):
            return
        self._identity_tasks.append(IdentityTask(series=series))

    def _run_ai(self) -> None:
        """查询身份候选，请求 AI 建议，并只保留通过规则验证的建议；输入没变的任务沿用缓存的回答。"""
        assert self.advisor is not None
        if self.tmdb is not None:
            for task in self._identity_tasks:
                if self.stop_event.is_set():
                    return
                try:
                    task.candidates = self.tmdb.search_tv(task.series.title, task.series.year)[:MAX_CANDIDATES]
                except TmdbLookupError as err:
                    logger.debug(f"影视库完整性检查：搜索候选失败 {task.series.title}：{err}")
        identity_tasks = [task for task in self._identity_tasks if task.candidates]
        numbering_ask, numbering_reuse = self._split_cached(self._numbering_tasks, NumberingAnswer)
        identity_ask, identity_reuse = self._split_cached(identity_tasks, IdentityAnswer)
        numbering: list[tuple[NumberingTask, NumberingAnswer]] = []
        identity: list[tuple[IdentityTask, IdentityAnswer]] = []
        if numbering_ask or identity_ask:
            self.progress(f"正在请求 AI 建议（{len(numbering_ask) + len(identity_ask)} 项）")
            reserve = 1 if self.options.ai_summary else 0
            numbering, identity = self.advisor.advise(numbering_ask, identity_ask, reserve=reserve)
        for task, answer in numbering:
            self._record(task, answer, self._verify_numbering(task, answer), "映射")
        for task, answer in identity:
            self._record(task, answer, self._verify_identity(task, answer), "身份")
        for task, answer, entry in numbering_reuse:
            self._recheck(task, answer, entry, self._verify_numbering(task, answer), "映射")
        for task, answer, entry in identity_reuse:
            self._recheck(task, answer, entry, self._verify_identity(task, answer), "身份")
        if self.options.ai_summary:
            self._summarize()

    def _split_cached(self, tasks: list, schema: type) -> tuple[list, list]:
        """把任务分成需要请求的和沿用缓存回答的；未通过验证且未到期的回答也沿用，按当前规则重新核对而不再请求。"""
        if self.ai_cache is None:
            return list(tasks), []
        ask: list = []
        reuse: list = []
        for task in tasks:
            entry = self.ai_cache.get(task_fingerprint(task))
            if entry is None:
                ask.append(task)
                continue
            retry = entry.retry_on()
            if retry is not None and retry <= self.today:
                ask.append(task)
                continue
            try:
                answer = schema.model_validate(entry.answer)
            except ValueError:
                self.ai_cache.drop(task_fingerprint(task))
                ask.append(task)
                continue
            self.report.stats.ai_cached += 1
            reuse.append((task, answer, entry))
        return ask, reuse

    def _record(self, task: NumberingTask | IdentityTask, answer: Any, reason: Optional[str], kind: str) -> None:
        """记录新请求到的回答；reason 为 None 表示通过，空字符串表示暂时无法验证（不缓存）。"""
        if reason:
            retry = self.today + timedelta(days=FAILED_RETRY_DAYS)
            logger.info(f"影视库完整性检查：{task.series.title} 的 AI {kind}建议未通过验证（{reason}），已丢弃，{retry} 前不再请求")
        if self.ai_cache is not None and reason != "":
            self.ai_cache.put(task_fingerprint(task), answer, reason is None, reason or "", self.today)

    def _recheck(
        self, task: NumberingTask | IdentityTask, answer: Any, entry: CachedAnswer, reason: Optional[str], kind: str
    ) -> None:
        """按当前数据与规则重新核对沿用的回答。

        上次通过、这次不再成立时丢弃缓存，下次扫描重新请求；上次未通过、这次通过（如验证规则或库内数据有变化）
        时改记为通过；仍未通过时等到期再请求。
        """
        assert self.ai_cache is not None
        key = task_fingerprint(task)
        if entry.passed:
            if reason is not None:
                if reason:
                    logger.info(f"影视库完整性检查：{task.series.title} 上次的 AI {kind}建议按当前数据不再成立（{reason}），下次扫描重新请求")
                self.ai_cache.drop(key)
            return
        if reason is None:
            logger.info(f"影视库完整性检查：{task.series.title} 上次未通过验证的 AI {kind}建议按当前规则已通过，恢复展示")
            self.ai_cache.put(key, answer, True, "", self.today)
        elif reason:
            logger.info(
                f"影视库完整性检查：{task.series.title} 的 AI {kind}建议上次未通过验证（{reason}），"
                f"库内情况未变，{entry.retry_on()} 前不再请求"
            )

    def _verify_numbering(self, task: NumberingTask, answer: NumberingAnswer) -> Optional[str]:
        """映射建议必须减少无法对应的集数且不制造新的撞集，才作为建议展示；返回未通过的原因，通过时为 None。"""
        if answer.confidence < MIN_AI_CONFIDENCE:
            return f"把握 {answer.confidence:.0%}，低于 {MIN_AI_CONFIDENCE:.0%}"
        proposed = [
            NumberMapping(m.library_season, m.library_start, max(m.library_start, m.library_end or m.library_start), m.tmdb_season, m.tmdb_start)
            for m in answer.mappings
            if m.library_season >= 0 and m.library_start >= 1 and m.tmdb_season >= 0 and m.tmdb_start >= 1
        ]
        if not proposed:
            return "AI 未给出有效的映射规则"
        # 只采用涉及无法对应单集的映射：AI 有时顺带改动本来就对得上的季，整组核对会连累正确的那条
        targets = _episode_numbers(task.unmatched)
        relevant = [m for m in proposed if any(m.translate(season, number) for season, number in targets)]
        extra = len(proposed) - len(relevant)
        if not relevant:
            return "AI 给出的映射都不涉及无法对应的集"
        proposed = relevant
        existing = self.options.number_mappings.get(task.base, [])
        args = (self.today, self.options.air_buffer_days, self.options.include_specials)
        before = summarize_match(task.series, task.tmdb, existing or None, *args)
        after = summarize_match(task.series, task.tmdb, existing + proposed, *args)
        rule_text = "；".join(mapping.describe(task.base) for mapping in proposed)
        if not numbering_improves(before, after):
            return (
                f"按 {rule_text} 对应后无法对应的集 {before.unmatched} → {after.unmatched}，"
                f"撞集 {before.collisions} → {after.collisions}，没有改善"
            )
        # 集数凑得上不代表对得上：映射到的 TMDB 单集播出日期须与库内首播日期大体一致
        dates = mapping_date_check(task.series, task.tmdb, proposed)
        if not dates.passed:
            return f"{rule_text} 播出日期不符：{dates.describe()}"
        rule = "\n".join(mapping.describe(task.base) for mapping in proposed)
        self._add([suggestion_issue(
            task.series,
            "AI 建议：按映射规则对应库内编号",
            rule.splitlines() + [
                f"采纳后：无法对应的集 {before.unmatched} → {after.unmatched}，缺集 {before.missing} → {after.missing}",
                dates.describe(),
                *([f"已略去 AI 另给的 {extra} 条映射：只涉及本来就能对应的集"] if extra else []),
                f"AI 理由：{answer.reason}（把握 {answer.confidence:.0%}）",
            ],
            "mapping",
            rule,
        )])
        return None

    def _verify_identity(self, task: IdentityTask, answer: IdentityAnswer) -> Optional[str]:
        """身份建议必须在候选中，且库内单集按季集号能在该剧中找到足够比例的对应。

        返回未通过的原因，通过时为 None；TMDB 暂时查不到候选详情时返回空字符串，表示本轮无法验证。
        """
        if self.tmdb is None:
            return ""
        if answer.confidence < MIN_AI_CONFIDENCE:
            return f"把握 {answer.confidence:.0%}，低于 {MIN_AI_CONFIDENCE:.0%}"
        if not 0 <= answer.candidate < len(task.candidates):
            return "AI 认为候选中没有同一部剧"
        candidate = task.candidates[answer.candidate]
        try:
            tmdb_series = self.tmdb.get_series(int(candidate["id"]))
        except (TmdbLookupError, KeyError, TypeError, ValueError) as err:
            logger.debug(f"影视库完整性检查：{task.series.title} 的 AI 身份建议无法验证：{err}")
            return ""
        coverage = identity_coverage(task.series, tmdb_series)
        if coverage < MIN_IDENTITY_COVERAGE:
            return f"库内只有 {coverage:.0%} 的单集能在 tmdb:{candidate.get('id')} 中找到对应，低于 {MIN_IDENTITY_COVERAGE:.0%}"
        series = task.series
        rule = f"{source_scope(series.server, series.item_id, series.origin)} => tmdb:{candidate['id']}"
        year = str(candidate.get("first_air_date") or "")[:4]
        self._add([suggestion_issue(
            series,
            f"AI 建议识别为《{candidate.get('name')}》（{year or '年份未知'}，tmdb:{candidate['id']}）",
            [
                f"库内 {coverage:.0%} 的单集可在该剧中按季集号找到对应",
                f"AI 理由：{answer.reason}（把握 {answer.confidence:.0%}）",
                "采纳后下次扫描将按该身份核对缺集",
            ],
            "identity",
            rule,
        )])
        return None

    def _summarize(self) -> None:
        """为应用忽略规则后的问题生成 AI 摘要。"""
        assert self.advisor is not None
        visible, _ = apply_ignore_rules(self._issues, self.options.ignore_rules)
        counts = Counter(issue.type for issue in visible)
        if not counts:
            return
        labeled = {ISSUE_TYPE_LABELS[t]: n for t, n in counts.items()}
        samples = [f"{ISSUE_TYPE_LABELS[i.type]} | {i.title} | {i.summary}" for i in visible[:30]]
        self.report.ai_summary = self.advisor.summarize(labeled, samples)
