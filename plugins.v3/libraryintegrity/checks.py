"""影视库完整性检查的纯规则：取值归一、季集匹配、缺集/版本/多文件判定与忽略规则。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from .models import (
    DIMENSION_SEVERITY,
    ORIGIN_LOCAL,
    VERSION_DIMENSIONS,
    Issue,
    IssueType,
    LibraryEpisode,
    LibraryMovie,
    LibrarySeries,
    Severity,
    TmdbEpisodeRef,
    TmdbSeries,
    VersionInfo,
)

TMDB_SOURCE = "themoviedb"

# ---------------------------------------------------------------------------
# 取值归一
# ---------------------------------------------------------------------------

_RESOLUTION_TEXT = re.compile(r"(\d{3,4})\s*[pi]\b", re.IGNORECASE)


def resolution_bucket(width: Optional[int], height: Optional[int]) -> Optional[str]:
    """按宽高归入分辨率档位；裁黑边的 1920x800 仍归为 1080p。"""
    w = int(width or 0)
    h = int(height or 0)
    if w <= 0 and h <= 0:
        return None
    if w >= 3200 or h >= 1800:
        return "2160p"
    if w >= 1800 or h >= 1000:
        return "1080p"
    if w >= 1200 or h >= 700:
        return "720p"
    return "480p"


def normalize_resolution_text(text: Optional[str]) -> Optional[str]:
    """把文件名中的分辨率标记（2160p、4K、1080i 等）归入分辨率档位。"""
    if not text:
        return None
    value = str(text).strip().lower()
    if value in {"4k", "uhd"}:
        return "2160p"
    if value in {"8k"}:
        return "4320p"
    match = _RESOLUTION_TEXT.search(value)
    if not match:
        return None
    lines = int(match.group(1))
    return resolution_bucket(0, lines) if lines < 4000 else "4320p"


_CODEC_PATTERNS = [
    (re.compile(r"hevc|[hx]\.?265"), "HEVC"),
    (re.compile(r"avc|[hx]\.?264"), "H.264"),
    (re.compile(r"av1"), "AV1"),
    (re.compile(r"vp9"), "VP9"),
    (re.compile(r"mpeg-?2"), "MPEG-2"),
    (re.compile(r"vc-?1"), "VC-1"),
]


def normalize_codec(text: Optional[str]) -> Optional[str]:
    """把视频编码名称归一为常见写法；文件名中的 "x265 10bit" 等组合写法按关键字识别。"""
    if not text:
        return None
    value = str(text).strip().lower()
    if not value:
        return None
    for pattern, name in _CODEC_PATTERNS:
        if pattern.search(value):
            return name
    return value.upper()


_AUDIO_ALIASES = {
    "eac3": "DDP",
    "e-ac-3": "DDP",
    "ddp": "DDP",
    "dd+": "DDP",
    "ac3": "DD",
    "ac-3": "DD",
    "dd": "DD",
    "truehd": "TrueHD",
    "dts": "DTS",
    "dts-hd": "DTS-HD",
    "dtshd": "DTS-HD",
    "aac": "AAC",
    "flac": "FLAC",
    "opus": "Opus",
    "mp3": "MP3",
}


def normalize_audio(text: Optional[str]) -> Optional[str]:
    """把音频编码名称归一，忽略声道数等附加信息。"""
    if not text:
        return None
    value = str(text).strip().lower().split()[0]
    if not value:
        return None
    return _AUDIO_ALIASES.get(value, value.upper())


def normalize_hdr(*texts: Optional[str]) -> Optional[str]:
    """从媒体流或文件名的 HDR 描述中归纳 HDR 类型；没有任何线索时返回 None（未知）。

    依次传入更可信的描述，命中第一个可识别的描述即返回。文件名里没有 HDR 标记不代表是 SDR，
    因此只有明确的 SDR 描述才返回 SDR。
    """
    for text in texts:
        if not text:
            continue
        value = str(text).strip().lower()
        if not value or value == "none":
            continue
        if "dolby" in value or "dovi" in value or re.search(r"(^|[^a-z])dv([^a-z]|$)", value):
            return "DV"
        if "hdr10+" in value or "hdr10plus" in value or "hdr10 plus" in value:
            return "HDR10+"
        if "hdr10" in value:
            return "HDR10"
        if "hlg" in value or "hyperloggamma" in value:
            return "HLG"
        if "hdr" in value:
            return "HDR"
        if "sdr" in value:
            return "SDR"
    return None


def normalize_bit_depth(value: Optional[object]) -> Optional[str]:
    """把位深统一为 "10bit" 形式。"""
    if value is None or value == "":
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    return f"{int(match.group())}bit"


def parse_int(value: object) -> Optional[int]:
    """把任意取值转换为整数，无法转换时返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def format_episode_ranges(numbers: Iterable[int], prefix: str = "E", width: int = 2) -> str:
    """把集号列表压缩为 "E01-E03、E05" 形式。"""
    values = sorted(set(numbers))
    if not values:
        return ""

    def label(value: int) -> str:
        return f"{prefix}{value:0{width}d}"

    parts: list[str] = []
    start = prev = values[0]
    for number in values[1:] + [None]:
        if number is not None and number == prev + 1:
            prev = number
            continue
        parts.append(label(start) if start == prev else f"{label(start)}-{label(prev)}")
        if number is not None:
            start = prev = number
    return "、".join(parts)


# ---------------------------------------------------------------------------
# 范围键与忽略规则
# ---------------------------------------------------------------------------

_SEASON_PART = re.compile(r"^S(\d+)(?:E(\d+))?$", re.IGNORECASE)


def series_scope(tmdb_id: Optional[int], server: str, item_id: str, origin: str = "emby") -> str:
    """返回媒体的基础范围键：有 TMDB ID 时用 tmdb:ID，否则用来源标识（Emby 条目或本地目录）。"""
    if tmdb_id:
        return f"tmdb:{tmdb_id}"
    return source_scope(server, item_id, origin)


def source_scope(server: str, item_id: str, origin: str = "emby") -> str:
    """返回不依赖 TMDB ID 的来源范围键，用于身份覆盖规则：emby:服务器/条目ID 或 local:目录。"""
    if origin == ORIGIN_LOCAL:
        return f"local:{item_id}"
    return f"emby:{server}/{item_id}"


def build_scope(base: str, season: Optional[int] = None, episode: Optional[int] = None) -> str:
    """在基础范围键上追加季、集。"""
    if season is None:
        return base
    if episode is None:
        return f"{base}:S{season}"
    return f"{base}:S{season}E{episode}"


@dataclass(frozen=True)
class IgnoreRule:
    """一条忽略规则：可选的问题类型 + 媒体范围（整部、整季或单集）。"""

    base: str
    season: Optional[int] = None
    episode: Optional[int] = None
    issue_type: Optional[IssueType] = None

    def matches(self, issue_type: IssueType, scope: str) -> bool:
        """判断规则是否覆盖指定问题类型和范围键。"""
        if self.issue_type is not None and self.issue_type != issue_type:
            return False
        parsed = parse_scope(scope)
        if parsed is None or parsed[0] != self.base:
            return False
        _, season, episode = parsed
        if self.season is not None and self.season != season:
            return False
        if self.episode is not None and self.episode != episode:
            return False
        return True


def parse_scope(scope: str) -> Optional[tuple[str, Optional[int], Optional[int]]]:
    """把范围键解析为 (基础键, 季, 集)。"""
    text = str(scope or "").strip()
    if not text:
        return None
    base, _, last = text.rpartition(":")
    match = _SEASON_PART.match(last) if base else None
    if match:
        season = int(match.group(1))
        episode = int(match.group(2)) if match.group(2) is not None else None
        return base.lower(), season, episode
    return text.lower(), None, None


def parse_ignore_rules(text: str) -> list[IgnoreRule]:
    """解析忽略规则文本：每行一条，# 开头为注释，可用 "类型@" 前缀限定问题类型。"""
    rules: list[IgnoreRule] = []
    for raw in str(text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        issue_type: Optional[IssueType] = None
        if "@" in line:
            type_text, _, line = line.partition("@")
            try:
                issue_type = IssueType(type_text.strip().lower())
            except ValueError:
                continue
        parsed = parse_scope(line)
        if parsed is None:
            continue
        rules.append(IgnoreRule(base=parsed[0], season=parsed[1], episode=parsed[2], issue_type=issue_type))
    return rules


def describe_missing(season: int, episodes: list[int]) -> str:
    """生成缺集问题的一句话说明。"""
    return f"第 {season} 季缺 {len(episodes)} 集：{format_episode_ranges(episodes)}"


def apply_ignore_rules(issues: list[Issue], rules: list[IgnoreRule]) -> tuple[list[Issue], int]:
    """按忽略规则过滤问题；缺集问题逐集过滤，返回 (可见问题, 被忽略数量)。"""
    if not rules:
        return list(issues), 0
    visible: list[Issue] = []
    ignored = 0
    for issue in issues:
        if any(rule.matches(issue.type, issue.scope) for rule in rules):
            ignored += 1
            continue
        if issue.type == IssueType.MISSING and issue.season is not None and issue.episodes:
            base = parse_scope(issue.scope)
            remaining = [
                number for number in issue.episodes
                if not any(
                    rule.matches(issue.type, build_scope(base[0], issue.season, number))
                    for rule in rules
                )
            ] if base else issue.episodes
            if not remaining:
                ignored += 1
                continue
            if len(remaining) != len(issue.episodes):
                issue = issue.model_copy(update={
                    "episodes": remaining,
                    "summary": describe_missing(issue.season, remaining),
                })
        visible.append(issue)
    return visible, ignored


# ---------------------------------------------------------------------------
# 采纳规则：编号映射与身份覆盖
# ---------------------------------------------------------------------------

_MAPPING_LINE = re.compile(
    r"^\s*(\S+)\s+S(\d+)E(\d+)(?:\s*-\s*(?:E)?(\d+))?\s*=>\s*S(\d+)E(\d+)\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class NumberMapping:
    """把库内一段连续集号映射到 TMDB 季集号：库 S{src_season}E{src_start}-E{src_end} => S{dst_season}E{dst_start}。"""

    src_season: int
    src_start: int
    src_end: int
    dst_season: int
    dst_start: int

    def translate(self, season: int, episode: int) -> Optional[tuple[int, int]]:
        """库内季集号落在映射范围内时返回对应的 TMDB 季集号。"""
        if season != self.src_season or not self.src_start <= episode <= self.src_end:
            return None
        return self.dst_season, self.dst_start + (episode - self.src_start)

    def describe(self, base: str) -> str:
        """生成可写入配置的规则文本。"""
        source = f"S{self.src_season}E{self.src_start}"
        if self.src_end != self.src_start:
            source += f"-E{self.src_end}"
        return f"{base} {source} => S{self.dst_season}E{self.dst_start}"


def parse_number_mappings(text: str) -> dict[str, list[NumberMapping]]:
    """解析编号映射规则：每行 "范围键 S1E13-E24 => S2E1"，# 后为注释。"""
    result: dict[str, list[NumberMapping]] = defaultdict(list)
    for raw in str(text or "").splitlines():
        match = _MAPPING_LINE.match(raw.split("#", 1)[0])
        if not match:
            continue
        base, s_season, s_start, s_end, d_season, d_start = match.groups()
        start = int(s_start)
        end = int(s_end) if s_end else start
        if end < start:
            continue
        result[base.lower()].append(NumberMapping(int(s_season), start, end, int(d_season), int(d_start)))
    return dict(result)


def parse_identity_overrides(text: str) -> dict[str, int]:
    """解析身份覆盖规则：每行 "emby:服务器/条目ID => tmdb:ID" 或 "local:目录 => tmdb:ID"。"""
    result: dict[str, int] = {}
    for raw in str(text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "=>" not in line:
            continue
        source, _, target = line.rpartition("=>")
        target = target.strip().lower()
        if not target.startswith("tmdb:"):
            continue
        tmdb_id = parse_int(target[5:])
        if source.strip() and tmdb_id:
            result[source.strip().lower()] = tmdb_id
    return result


def translate_number(mappings: Optional[list[NumberMapping]], season: int, episode: int) -> tuple[int, int]:
    """按映射规则翻译库内季集号，没有命中的规则时原样返回。"""
    for mapping in mappings or []:
        target = mapping.translate(season, episode)
        if target is not None:
            return target
    return season, episode


# ---------------------------------------------------------------------------
# 季集匹配与缺集
# ---------------------------------------------------------------------------


@dataclass
class EpisodeMatch:
    """一个库内单集条目与 TMDB 单集的匹配结果。"""

    episode: LibraryEpisode
    refs: list[TmdbEpisodeRef] = field(default_factory=list)
    # id：按单集 TMDB ID 匹配；number：按季集号匹配；none：未匹配
    method: str = "none"
    invalid_id: bool = False
    # 按季集号匹配时在 TMDB 中找不到的集号
    unmatched_numbers: list[int] = field(default_factory=list)


def match_episodes(
    series: LibrarySeries,
    tmdb: TmdbSeries,
    mappings: Optional[list[NumberMapping]] = None,
) -> list[EpisodeMatch]:
    """把库内单集与 TMDB 单集对应：优先使用校验过的单集 ID，否则按（映射后的）季集号。"""
    by_id = tmdb.episode_by_id()
    by_number = tmdb.episode_by_number()
    results: list[EpisodeMatch] = []
    for episode in series.episodes:
        match = EpisodeMatch(episode=episode)
        declared = episode.tmdb_id
        if declared and declared != tmdb.tmdb_id and declared in by_id:
            base = by_id[declared]
            match.refs.append(base)
            match.method = "id"
            # 多集文件只携带首集 ID，后续集按 TMDB 中的连续集号补齐
            for offset in range(1, len(episode.episode_numbers)):
                ref = by_number.get((base.season, base.episode + offset))
                if ref:
                    match.refs.append(ref)
        else:
            match.invalid_id = declared is not None
            if episode.season is not None:
                for number in episode.episode_numbers:
                    ref = by_number.get(translate_number(mappings, episode.season, number))
                    if ref:
                        match.refs.append(ref)
                    else:
                        match.unmatched_numbers.append(number)
                if match.refs:
                    match.method = "number"
        results.append(match)
    return results


def parse_air_date(text: Optional[str]) -> Optional[date]:
    """解析 TMDB 的 YYYY-MM-DD 播出日期。"""
    if not text:
        return None
    try:
        return datetime.strptime(str(text)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def find_missing(
    tmdb: TmdbSeries,
    matches: list[EpisodeMatch],
    today: date,
    buffer_days: int = 2,
    include_specials: bool = False,
    only_existing_seasons: bool = False,
) -> dict[int, list[TmdbEpisodeRef]]:
    """计算缺集：已播出（播出日期早于今天减去缓冲天数）且库内未覆盖的 TMDB 单集。

    TMDB 常有整段单集没填播出日期（如熊出没第 1 季 104 集只有 7 集有日期）。没有日期的单集
    若排在同季某个已播出单集之前，也视为已播出；排在最后一个已播出单集之后的仍视为未播出。
    """
    covered = {ref.tmdb_id for match in matches for ref in match.refs}
    library_seasons = {ref.season for match in matches for ref in match.refs}
    cutoff = today - timedelta(days=max(0, buffer_days))
    missing: dict[int, list[TmdbEpisodeRef]] = {}
    for season, refs in sorted(tmdb.seasons.items()):
        if season == 0 and not include_specials:
            continue
        if only_existing_seasons and season not in library_seasons:
            continue
        dates = {ref.tmdb_id: parse_air_date(ref.air_date) for ref in refs}
        last_aired = max(
            (ref.episode for ref in refs if dates[ref.tmdb_id] is not None and dates[ref.tmdb_id] <= cutoff),
            default=0,
        )
        for ref in refs:
            aired = dates[ref.tmdb_id]
            if aired is None and ref.episode < last_aired:
                aired = cutoff
            if aired is None or aired > cutoff:
                continue
            if ref.tmdb_id not in covered:
                missing.setdefault(season, []).append(ref)
    return missing


@dataclass
class MatchSummary:
    """一次匹配的结果统计，用于验证 AI 建议是否真的改善了对应关系。"""

    unmatched: int
    missing: int
    collisions: int
    matched: int


def summarize_match(
    series: LibrarySeries,
    tmdb: TmdbSeries,
    mappings: Optional[list[NumberMapping]],
    today: date,
    buffer_days: int,
    include_specials: bool,
) -> MatchSummary:
    """统计按给定映射匹配后的未匹配集数、缺集数与多个条目撞到同一 TMDB 单集的次数。"""
    matches = match_episodes(series, tmdb, mappings)
    unmatched = sum(
        len(m.unmatched_numbers) for m in matches
        if include_specials or m.episode.season != 0
    )
    owners: dict[int, set[str]] = defaultdict(set)
    for match in matches:
        for ref in match.refs:
            owners[ref.tmdb_id].add(match.episode.item_id)
    collisions = sum(1 for items in owners.values() if len(items) > 1)
    missing = find_missing(tmdb, matches, today, buffer_days=buffer_days, include_specials=include_specials)
    return MatchSummary(
        unmatched=unmatched,
        missing=sum(len(refs) for refs in missing.values()),
        collisions=collisions,
        matched=sum(len(m.refs) for m in matches),
    )


def numbering_improves(before: MatchSummary, after: MatchSummary) -> bool:
    """映射建议必须减少未匹配集数，且不能增加多个条目撞同一集的情况。"""
    return after.unmatched < before.unmatched and after.collisions <= before.collisions


# 库内首播日期与映射目标的 TMDB 播出日期相差不超过该天数即视为相符（时区、地区首播差异）
DATE_TOLERANCE_DAYS = 14
# 可核对日期的单集中至少这个比例相符，映射建议才算通过
MIN_DATE_AGREEMENT = 0.7


@dataclass
class DateCheck:
    """编号映射的播出日期核对结果。"""

    checked: int = 0
    agreed: int = 0
    # 第一处不符的示例，如 "库内 S05E01（2009-01-09）→ TMDB S01E143（2007-06-08）"
    sample: str = ""

    @property
    def passed(self) -> bool:
        """没有可核对的日期时无法否定，视为通过；否则须多数相符。"""
        return self.checked == 0 or self.agreed >= MIN_DATE_AGREEMENT * self.checked

    def describe(self) -> str:
        """生成展示给用户的核对说明。"""
        if self.checked == 0:
            return "库内这些单集没有首播日期，未核对播出日期"
        text = f"播出日期核对：{self.checked} 集中 {self.agreed} 集与 TMDB 相差不超过 {DATE_TOLERANCE_DAYS} 天"
        return f"{text}；不符示例：{self.sample}" if self.sample else text


def mapping_date_check(series: LibrarySeries, tmdb: TmdbSeries, mappings: list[NumberMapping]) -> DateCheck:
    """核对映射涉及的库内单集首播日期与映射到的 TMDB 单集播出日期是否接近。

    只按集数验证时，任何"总数凑得上"的平移都能通过（如把 2009 年的一季接到 2007 年的集号后面），
    播出日期能识别这类错位。多集文件只核对首集。
    """
    result = DateCheck()
    by_number = tmdb.episode_by_number()
    for episode in sorted(series.episodes, key=lambda e: (e.season or 0, e.episode or 0)):
        local = parse_air_date(episode.air_date)
        if local is None or episode.season is None or episode.episode is None:
            continue
        target = next(
            (t for t in (m.translate(episode.season, episode.episode) for m in mappings) if t is not None), None
        )
        ref = by_number.get(target) if target else None
        remote = parse_air_date(ref.air_date) if ref else None
        if remote is None:
            continue
        result.checked += 1
        if abs((local - remote).days) <= DATE_TOLERANCE_DAYS:
            result.agreed += 1
        elif not result.sample:
            result.sample = f"库内 {episode.label}（{local}）→ TMDB S{ref.season:02d}E{ref.episode:02d}（{remote}）"
    return result


def identity_coverage(series: LibrarySeries, tmdb: TmdbSeries) -> float:
    """按季集号计算库内单集能在候选剧集中找到对应的比例，用于验证 AI 选择的身份。"""
    numbers = [
        (episode.season, number)
        for episode in series.episodes
        if episode.season not in (None, 0)
        for number in episode.episode_numbers
    ]
    if not numbers:
        return 0.0
    by_number = tmdb.episode_by_number()
    return sum(1 for key in numbers if key in by_number) / len(numbers)


# ---------------------------------------------------------------------------
# 问题生成
# ---------------------------------------------------------------------------


def display_title(title: str, year: str) -> str:
    """生成带年份的展示标题；标题本身已带同一年份时不再重复追加。"""
    if not year:
        return title
    if re.search(rf"[(（\[]\s*{re.escape(str(year))}\s*[)）\]]", title):
        return title
    return f"{title} ({year})"


def _series_issue(series: LibrarySeries, issue_type: IssueType, **kwargs: object) -> Issue:
    """以剧集为上下文构造问题，统一填充服务器、媒体库和媒体身份。"""
    return Issue(
        type=issue_type,
        server=series.server,
        library=series.library,
        title=display_title(series.title, series.year),
        media_type="tv",
        media_source=TMDB_SOURCE if series.tmdb_id else None,
        media_id=str(series.tmdb_id) if series.tmdb_id else None,
        **kwargs,
    )


def missing_issues(series: LibrarySeries, missing: dict[int, list[TmdbEpisodeRef]]) -> list[Issue]:
    """把缺集结果按季生成问题。"""
    base = series_scope(series.tmdb_id, series.server, series.item_id, series.origin)
    issues: list[Issue] = []
    for season, refs in sorted(missing.items()):
        numbers = sorted(ref.episode for ref in refs)
        issues.append(_series_issue(
            series,
            IssueType.MISSING,
            severity=Severity.WARNING,
            season=season,
            episodes=numbers,
            summary=describe_missing(season, numbers),
            details=[
                f"E{ref.episode:02d} {ref.name}（{ref.air_date or 'TMDB 未填播出日期'}）".strip()
                for ref in sorted(refs, key=lambda r: r.episode)
            ],
            scope=build_scope(base, season),
        ))
    return issues


def _minor_extras(count: int, season_size: int) -> bool:
    """库内某季多出的集是否只是零星几集（如 TMDB 合并的双集、季末番外），不足以说明编号整体错位。

    既限制绝对数量，也限制占该季的比例，避免集数很少的季被误判为零星。
    """
    return count <= max(2, season_size // 10) and count * 4 <= season_size


def _empty_season(tmdb: Optional[TmdbSeries], season: Optional[int]) -> bool:
    """TMDB 已建立该季但还没有任何单集数据（常见于刚公布的新季）。"""
    return tmdb is not None and season in tmdb.seasons and not tmdb.seasons[season]


def _regular_seasons(tmdb: TmdbSeries) -> list[int]:
    """TMDB 中有单集数据的正片季。"""
    return sorted(season for season, refs in tmdb.seasons.items() if season != 0 and refs)


def _describe_seasons(seasons: list[int]) -> str:
    """把季号列表压缩为 "第 1-9 季" 或 "第 1、3 季"。"""
    if not seasons:
        return "没有正片季"
    return "第 " + format_episode_ranges(seasons, prefix="", width=1) + " 季"


def _absent_season_hint(series: LibrarySeries, season: int, tmdb: TmdbSeries, unmatched: list[int], identity: str) -> str:
    """库内某季在 TMDB 中不存在时的处理建议：多半是分季方式不同，其次才是认错了剧。"""
    if not series.tmdb_id or not unmatched:
        return f"处理：TMDB 上没有这一季，可能认错了剧，可在「身份指定」中写 {identity}"
    source = f"tmdb:{series.tmdb_id} S{season}E{min(unmatched)}-E{max(unmatched)}"
    regular = _regular_seasons(tmdb)
    if len(regular) == 1 and len(tmdb.seasons[regular[0]]) > len(unmatched):
        only = regular[0]
        return (
            f"处理：TMDB 把该剧按绝对集数排在第 {only} 季（共 {len(tmdb.seasons[only])} 集），库内可能按 TVDB 分季；"
            f"可在「编号映射」中写 {source} => S{only}E<起始集>，起始集可按本季首集的播出日期在 TMDB 第 {only} 季中查到；"
            f"若认错了剧，在「身份指定」中写 {identity}"
        )
    return (
        f"处理：库内分季可能与 TMDB 不同（如按 TVDB 分季），可在「编号映射」中写 {source} => S<TMDB 季>E<起始集>；"
        f"若认错了剧，在「身份指定」中写 {identity}"
    )


def _conflict_hint(
    series: LibrarySeries, season: Optional[int], tmdb: Optional[TmdbSeries], unmatched: list[int]
) -> str:
    """按冲突原因给出处理建议。"""
    identity = f"{source_scope(series.server, series.item_id, series.origin)} => tmdb:正确ID"
    if season is None:
        return "处理：把文件放进 Season N 目录或在文件名中写明季号（如 S01E01），再让 Emby 重新扫描该剧"
    if tmdb is not None and season not in tmdb.seasons:
        return _absent_season_hint(series, season, tmdb, unmatched, identity)
    if _empty_season(tmdb, season):
        return "处理：TMDB 已建立这一季但还没有单集数据，等 TMDB 补全后重新扫描即可，不需要编号映射；在此之前可点「忽略」"
    if tmdb is not None and unmatched and _minor_extras(len(unmatched), len(tmdb.seasons[season])):
        return "处理：多出的少量集通常是 TMDB 合并的双集或季末番外，不影响缺集核对；确认无误后可点「忽略」"
    if series.tmdb_id and unmatched:
        return (
            f"处理：编号整体错位时可在「编号映射」中对齐，格式为 "
            f"tmdb:{series.tmdb_id} S{season}E{min(unmatched)}-E{max(unmatched)} => S<TMDB 季>E<起始集>；"
            f"若认错了剧，在「身份指定」中写 {identity}"
        )
    return f"处理：核对 NFO 与媒体服务器中的季集号，或在「身份指定」中写 {identity}"


def conflict_issues(
    series: LibrarySeries,
    matches: Optional[list[EpisodeMatch]],
    include_specials: bool,
    tmdb: Optional[TmdbSeries] = None,
) -> list[Issue]:
    """按季汇总编号冲突：库内单集在 TMDB 找不到对应、缺少季集号或采集阶段发现的冲突，每季一条。"""
    base = series_scope(series.tmdb_id, series.server, series.item_id, series.origin)
    pairs = [(m.episode, m) for m in matches] if matches is not None else [(e, None) for e in series.episodes]
    groups: dict[Optional[int], list[LibraryEpisode]] = defaultdict(list)
    unmatched: dict[int, list[int]] = defaultdict(list)
    invalid: Counter = Counter()
    for episode, match in pairs:
        if episode.season == 0 and not include_specials:
            continue
        if episode.season is None or episode.episode is None:
            groups[None].append(episode)
            continue
        if match is not None and match.unmatched_numbers:
            unmatched[episode.season].extend(match.unmatched_numbers)
            invalid[episode.season] += 1 if match.invalid_id else 0
            groups[episode.season].append(episode)
        elif episode.conflicts:
            groups[episode.season].append(episode)

    issues: list[Issue] = []
    for season, episodes in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        numbers = sorted({n for episode in episodes for n in episode.episode_numbers})
        details: list[str] = []
        if season is None:
            summary = f"{len(episodes)} 个单集缺少季号或集号"
            details.append("媒体服务器未提供季号或集号")
        else:
            summary = f"第 {season} 季 {len(numbers)} 集编号无法与 TMDB 对应：{format_episode_ranges(numbers)}"
            if unmatched.get(season):
                ranges = format_episode_ranges(unmatched[season])
                if tmdb is not None and season not in tmdb.seasons:
                    details.append(
                        f"TMDB 没有第 {season} 季（TMDB 正片为{_describe_seasons(_regular_seasons(tmdb))}），库内 {ranges} 无法对应"
                    )
                elif _empty_season(tmdb, season):
                    details.append(f"TMDB 第 {season} 季暂无单集数据，库内 {ranges} 暂时无法对应")
                else:
                    details.append(f"TMDB 第 {season} 季中没有 {ranges}")
            if invalid.get(season):
                details.append(f"其中 {invalid[season]} 集的单集 TMDB ID 不属于该剧，已按季集号匹配")
        details.extend(f"{episode.label}：{note}" for episode in episodes for note in episode.conflicts)
        details.append(_conflict_hint(series, season, tmdb, unmatched.get(season, []) if season is not None else []))
        sample = next((episode.path for episode in episodes if episode.path), "")
        if sample:
            details.append(f"示例：{sample}")
        issues.append(_series_issue(
            series,
            IssueType.CONFLICT,
            severity=Severity.WARNING,
            season=season,
            episodes=numbers,
            summary=summary,
            details=details,
            scope=build_scope(base, season),
        ))
    return issues


def numbering_misaligned(matches: list[EpisodeMatch], tmdb: TmdbSeries, include_specials: bool) -> bool:
    """判断库内编号是否与 TMDB 整体错位，错位时按编号算出的缺集不可信。

    以下情况视为整体错位：有单集缺少季号或集号；库内某季在 TMDB 中不存在；某季对不上的集超出零星范围。
    季末多出一两集（TMDB 合并的双集、番外、E00）不影响其余集的对应，不算错位。
    """
    unmatched: dict[int, int] = defaultdict(int)
    for match in matches:
        season = match.episode.season
        if season == 0 and not include_specials:
            continue
        if season is None or match.episode.episode is None:
            if not match.refs:
                return True
            continue
        unmatched[season] += len(match.unmatched_numbers)
    for season, count in unmatched.items():
        if not count or _empty_season(tmdb, season):
            # TMDB 已建季但暂无单集时只是该季暂时无法核对，不影响其他季的对应
            continue
        if season not in tmdb.seasons or not _minor_extras(count, len(tmdb.seasons[season])):
            return True
    return False


# 判定"一个文件含两集"时 TMDB 季集数与库内集数之比的范围
_SPLIT_RATIO = (1.6, 2.4)
# TMDB 单集两两同日播出的比例达到该值，才认为该季是拆分的短篇
_SPLIT_PAIRED = 0.7


def _paired_ratio(refs: list[TmdbEpisodeRef]) -> float:
    """TMDB 某季中与另一集同日播出的单集比例；分段播出的短篇（如 11 分钟一段）通常两两同日。"""
    dates = Counter(ref.air_date for ref in refs if ref.air_date)
    total = sum(dates.values())
    return sum(n for n in dates.values() if n >= 2) / total if total else 0.0


def split_episode_seasons(
    matches: list[EpisodeMatch], tmdb: TmdbSeries, missing: dict[int, list[TmdbEpisodeRef]]
) -> list[int]:
    """找出疑似"库内一个文件对应 TMDB 两集"的季，这些季按编号算出的缺集是假的。

    典型如汪汪队立大功：TVDB 每季 26 集、每集含两个 11 分钟的故事，TMDB 把每个故事拆成一集（每季约 47 集）。
    库内按 TVDB 编号时，前半季编号恰好都能对上，后半季全部被当作缺集。

    单季的形态：库内恰好覆盖 TMDB 该季的 E01-En，缺的正好是其后全部已播集，且 TMDB 集数约为库内的两倍。
    只有一季呈此形态时无法与"后半季确实没下"区分，因此至少要有两季的 TMDB 单集多数两两同日播出，
    才认定整部剧是拆分短篇；认定后其余呈此形态的季一并按拆分处理。
    """
    covered: dict[int, set[int]] = defaultdict(set)
    for match in matches:
        for ref in match.refs:
            covered[ref.season].add(ref.episode)
    candidates: list[int] = []
    for season, refs in missing.items():
        have = covered.get(season)
        if season == 0 or not have:
            continue
        count = len(have)
        if have != set(range(1, count + 1)):
            continue
        if sorted(ref.episode for ref in refs) != list(range(count + 1, count + 1 + len(refs))):
            continue
        size = len(tmdb.seasons.get(season, []))
        if not _SPLIT_RATIO[0] * count <= size <= _SPLIT_RATIO[1] * count:
            continue
        candidates.append(season)
    paired = [season for season in candidates if _paired_ratio(tmdb.seasons[season]) >= _SPLIT_PAIRED]
    return sorted(candidates) if len(paired) >= 2 else []


def split_episode_issue(series: LibrarySeries, tmdb: TmdbSeries, seasons: list[int], matches: list[EpisodeMatch]) -> Issue:
    """疑似一个文件含两集的季，不报缺集，改为一条无法核对。"""
    have: dict[int, int] = Counter(ref.season for match in matches for ref in match.refs)
    details = [f"第 {season} 季：库内 {have[season]} 集，TMDB {len(tmdb.seasons[season])} 集" for season in seasons]
    details.append(
        "TMDB 把每集拆成了两段（多为 11 分钟左右的短篇），库内一个文件含两段、按 TVDB 编号，"
        "因此前半季编号能对上、后半季被误当作缺集；按编号无法核对这些季，也无法用编号映射对齐"
    )
    details.append("若这些季确实只下载了前半部分，可对照 TMDB 自行核实；其余季的缺集仍正常报告")
    return _series_issue(
        series,
        IssueType.UNCHECKED,
        severity=Severity.INFO,
        summary=f"疑似一个文件含 TMDB 两集，{_describe_seasons(seasons)}未核对缺集",
        details=details,
        scope=series_scope(series.tmdb_id, series.server, series.item_id, series.origin),
    )


# 只有集号、没有真正标题的单集名，如「第 57 集」「Episode 57」「第57话」
_PLACEHOLDER_NAME = re.compile(r"^(?:第\s*\d+\s*[集话話]|(?:episode|ep\.?)\s*\d+)$", re.IGNORECASE)
# TMDB 单集 ID 全站递增；末尾几集的 ID 比前面的集大出这么多，说明是很久以后才补建的
_LATE_ID_GAP = 100_000
ENDED_STATUSES = {"ended", "canceled", "cancelled"}


def _placeholder_name(name: str) -> bool:
    """单集名为空或只有集号。"""
    text = (name or "").strip()
    return not text or bool(_PLACEHOLDER_NAME.match(text))


def placeholder_tail_seasons(
    tmdb: TmdbSeries, matches: list[EpisodeMatch], missing: dict[int, list[TmdbEpisodeRef]]
) -> dict[int, list[TmdbEpisodeRef]]:
    """找出缺集恰好是 TMDB 季末"后补占位集"的季，这些缺集多半是 TMDB 数据错误。

    典型如长安诺：全剧 56 集，E56 已是大结局，TMDB 却在数年后被补了 E57-E60，标题只有「第 N 集」。
    判定条件（须同时满足）：剧集已完结；缺的正好是库内最后一集之后的全部 TMDB 单集；
    这些单集都没有真正的标题，而库内最后一集有；它们的 TMDB ID 远大于该季其余单集（后补建）。
    仍在播出的剧、或与前面同批建立的无标题集（只是还没人填标题）不在此列，照常报缺集。
    """
    if (tmdb.status or "").strip().lower() not in ENDED_STATUSES:
        return {}
    covered: dict[int, set[int]] = defaultdict(set)
    for match in matches:
        for ref in match.refs:
            covered[ref.season].add(ref.tmdb_id)
    result: dict[int, list[TmdbEpisodeRef]] = {}
    for season, refs in missing.items():
        have = covered.get(season)
        season_refs = sorted(tmdb.seasons.get(season, []), key=lambda r: r.episode)
        if season == 0 or not have or not refs:
            continue
        last = max((i for i, ref in enumerate(season_refs) if ref.tmdb_id in have), default=-1)
        tail = season_refs[last + 1:]
        if last < 0 or not tail or {ref.tmdb_id for ref in tail} != {ref.tmdb_id for ref in refs}:
            continue
        if _placeholder_name(season_refs[last].name) or not all(_placeholder_name(ref.name) for ref in tail):
            continue
        earlier = max(ref.tmdb_id for ref in season_refs[:last + 1])
        if min(ref.tmdb_id for ref in tail) - earlier < _LATE_ID_GAP:
            continue
        result[season] = sorted(refs, key=lambda r: r.episode)
    return result


def placeholder_tail_issue(series: LibrarySeries, tails: dict[int, list[TmdbEpisodeRef]]) -> Issue:
    """TMDB 季末疑似多余的占位集，不报缺集，改为一条无法核对。"""
    details = [
        f"第 {season} 季：TMDB 末尾 {format_episode_ranges(ref.episode for ref in refs)} 只有集号、没有标题，"
        f"且是在其余单集建立很久之后才补建的"
        for season, refs in sorted(tails.items())
    ]
    details.append("剧集已完结，库内最后一集之前的单集都有正式标题，这几集多半是 TMDB 上多余的占位条目，未计入缺集")
    details.append("若确实还有这几集，可对照播出平台核实；也可到 TMDB 删除或修正这些条目")
    numbers = "，".join(
        f"第 {season} 季末尾 {format_episode_ranges(ref.episode for ref in refs)}" for season, refs in sorted(tails.items())
    )
    return _series_issue(
        series,
        IssueType.UNCHECKED,
        severity=Severity.INFO,
        summary=f"TMDB {numbers} 疑似多余的占位集，未报缺集",
        details=details,
        scope=series_scope(series.tmdb_id, series.server, series.item_id, series.origin),
    )


def unreliable_missing_issue(series: LibrarySeries, missing: dict[int, list[TmdbEpisodeRef]]) -> Issue:
    """库内编号与 TMDB 不一致时，缺集结果不可信，不逐季报告缺集，改为一条无法核对。"""
    total = sum(len(refs) for refs in missing.values())
    seasons = [
        f"第 {season} 季：{format_episode_ranges(ref.episode for ref in refs)}"
        for season, refs in sorted(missing.items())
    ]
    if len(seasons) > 10:
        seasons = seasons[:10] + [f"……另有 {len(seasons) - 10} 季"]
    return _series_issue(
        series,
        IssueType.UNCHECKED,
        severity=Severity.INFO,
        summary=f"库内编号与 TMDB 不一致，缺集结果不可信，未报告（按当前对应 TMDB 有 {total} 集未找到）",
        details=seasons + ["先按「编号冲突」中的提示对齐编号或改正身份，再重新扫描即可得到可信的缺集结果"],
        scope=series_scope(series.tmdb_id, series.server, series.item_id, series.origin),
    )


def _describe_version(version: VersionInfo) -> str:
    """生成版本的简短描述。"""
    parts = [
        version.resolution, version.video_codec, version.hdr,
        version.release_group, "strm" if version.kind == "strm" else None,
    ]
    text = " / ".join(part for part in parts if part)
    return f"{text or '未知版本'}：{version.path or version.name}"


# 分段文件标记，如 S05E08-Part1、-CD2、.disc1；同一集拆成多段的文件不是多个版本
_PART_MARK = re.compile(r"(?<=[\s._-])(?:part|pt|cd|dis[ck])[\s._-]?\d{1,2}(?=$|[\s._-])", re.IGNORECASE)


def part_key(path: str) -> Optional[str]:
    """去掉文件名中的分段标记，同一版本的各段得到相同的键；文件名没有分段标记时返回 None。"""
    directory, _, name = (path or "").replace("\\", "/").rpartition("/")
    stripped = _PART_MARK.sub("", name)
    return f"{directory}/{stripped}" if stripped != name else None


def _distinct_versions(versions: list[VersionInfo]) -> list[VersionInfo]:
    """把同一版本的多个分段合并为一个，保留首段。"""
    seen: dict[object, VersionInfo] = {}
    for index, version in enumerate(versions):
        seen.setdefault(part_key(version.path or version.name) or index, version)
    return list(seen.values())


def _mixed_kinds(versions: list[VersionInfo]) -> bool:
    """判断多个版本是否同时包含 strm 与本地文件。"""
    return len({version.kind for version in versions}) > 1


def duplicate_issues(
    series: LibrarySeries,
    matches: Optional[list[EpisodeMatch]],
    ignore_mixed: bool,
    include_specials: bool,
) -> list[Issue]:
    """生成剧集多文件问题：单个条目多版本，或多个条目指向同一集。同一集拆成的多段文件（Part1/Part2）不算。"""
    base = series_scope(series.tmdb_id, series.server, series.item_id, series.origin)
    issues: list[Issue] = []
    for episode in series.episodes:
        if episode.season == 0 and not include_specials:
            continue
        versions = _distinct_versions(episode.versions)
        if len(versions) > 1 and not (ignore_mixed and _mixed_kinds(versions)):
            issues.append(_series_issue(
                series,
                IssueType.DUPLICATE,
                severity=Severity.INFO,
                season=episode.season,
                episodes=episode.episode_numbers,
                summary=f"{episode.label} 有 {len(versions)} 个版本",
                details=[_describe_version(version) for version in versions],
                scope=build_scope(base, episode.season, episode.episode),
            ))
    # 不同条目指向同一集：已匹配的按 TMDB 单集归组，未匹配的按季集号归组
    groups: dict[tuple, list[LibraryEpisode]] = defaultdict(list)
    if matches is not None:
        for match in matches:
            keys = [("id", ref.tmdb_id, ref.season, ref.episode) for ref in match.refs]
            keys += [("num", None, match.episode.season, number) for number in match.unmatched_numbers]
            for key in keys:
                groups[key].append(match.episode)
    else:
        for episode in series.episodes:
            for number in episode.episode_numbers:
                groups[("num", None, episode.season, number)].append(episode)
    for (_, _, season, number), episodes in sorted(groups.items(), key=lambda kv: (kv[0][2] or 0, kv[0][3] or 0)):
        # 媒体服务器没有把分段文件合成一个条目时，各段按路径去掉分段标记后合并
        unique = {part_key(episode.path) or episode.item_id: episode for episode in episodes}
        if len(unique) < 2 or season is None:
            continue
        if season == 0 and not include_specials:
            continue
        versions = [version for episode in unique.values() for version in episode.versions]
        if ignore_mixed and _mixed_kinds(versions):
            continue
        issues.append(_series_issue(
            series,
            IssueType.DUPLICATE,
            severity=Severity.INFO,
            season=season,
            episodes=[number],
            summary=f"S{season:02d}E{number:02d} 对应 {len(unique)} 个条目",
            details=[f"{episode.label}：{episode.path}" for episode in unique.values()],
            scope=build_scope(base, season, number),
        ))
    return issues


def version_issues(series: LibrarySeries, dimensions: list[str], include_specials: bool) -> list[Issue]:
    """按季检查版本一致性：以多数版本为基准，报告偏离基准的单集；无多数时报告混杂分布。"""
    base = series_scope(series.tmdb_id, series.server, series.item_id, series.origin)
    by_season: dict[int, list[LibraryEpisode]] = defaultdict(list)
    for episode in series.episodes:
        if episode.season is None or not episode.versions:
            continue
        if episode.season == 0 and not include_specials:
            continue
        by_season[episode.season].append(episode)
    issues: list[Issue] = []
    for season, episodes in sorted(by_season.items()):
        for dimension in dimensions:
            label = VERSION_DIMENSIONS.get(dimension)
            if not label:
                continue
            known = [(episode, episode.versions[0].get(dimension)) for episode in episodes]
            unknown = sum(1 for _, value in known if value is None)
            known = [(episode, value) for episode, value in known if value is not None]
            if len(known) < 2:
                continue
            counter = Counter(value for _, value in known)
            if len(counter) < 2:
                continue
            top_value, top_count = counter.most_common(1)[0]
            unknown_note = [f"另有 {unknown} 集无法获取{label}，未参与比较"] if unknown else []
            if top_count * 2 > len(known):
                outliers = [(episode, value) for episode, value in known if value != top_value]
                summary = f"第 {season} 季{label}：多数为 {top_value}（{top_count}/{len(known)} 集），{len(outliers)} 集偏离"
                details = [f"{episode.label}：{value}" for episode, value in sorted(outliers, key=lambda p: p[0].episode or 0)]
                numbers = sorted(n for episode, _ in outliers for n in episode.episode_numbers)
            else:
                summary = f"第 {season} 季{label}混杂，没有多数版本"
                details = [f"{value} × {count}" for value, count in counter.most_common()]
                numbers = []
            issues.append(_series_issue(
                series,
                IssueType.VERSION,
                severity=DIMENSION_SEVERITY.get(dimension, Severity.INFO),
                season=season,
                episodes=numbers,
                summary=summary,
                details=details + unknown_note,
                scope=build_scope(base, season),
            ))
    return issues


def unchecked_issue(series: LibrarySeries, reason: str) -> Issue:
    """生成无法核对的问题，表示该剧未参与缺集检查，而不是没有问题。"""
    return _series_issue(
        series,
        IssueType.UNCHECKED,
        severity=Severity.INFO,
        summary=reason,
        details=[series.path] if series.path else [],
        scope=series_scope(series.tmdb_id, series.server, series.item_id, series.origin),
    )


def movie_duplicate_issues(movies: list[LibraryMovie], ignore_mixed: bool) -> list[Issue]:
    """生成电影多文件问题：单个条目多版本，或同一服务器内多个条目指向同一 TMDB 电影。"""
    issues: list[Issue] = []

    def _movie_issue(movie: LibraryMovie, summary: str, details: list[str]) -> Issue:
        """以电影为上下文构造多文件问题。"""
        return Issue(
            type=IssueType.DUPLICATE,
            severity=Severity.INFO,
            server=movie.server,
            library=movie.library,
            title=display_title(movie.title, movie.year),
            media_type="movie",
            media_source=TMDB_SOURCE if movie.tmdb_id else None,
            media_id=str(movie.tmdb_id) if movie.tmdb_id else None,
            summary=summary,
            details=details,
            scope=series_scope(movie.tmdb_id, movie.server, movie.item_id, movie.origin),
        )

    for movie in movies:
        if len(movie.versions) > 1 and not (ignore_mixed and _mixed_kinds(movie.versions)):
            issues.append(_movie_issue(
                movie,
                f"电影有 {len(movie.versions)} 个版本",
                [_describe_version(version) for version in movie.versions],
            ))
    groups: dict[tuple[str, int], list[LibraryMovie]] = defaultdict(list)
    for movie in movies:
        if movie.tmdb_id:
            groups[(movie.server, movie.tmdb_id)].append(movie)
    for (_, _), items in sorted(groups.items()):
        if len(items) < 2:
            continue
        versions = [version for movie in items for version in movie.versions]
        if ignore_mixed and _mixed_kinds(versions):
            continue
        issues.append(_movie_issue(
            items[0],
            f"同一电影对应 {len(items)} 个条目",
            [f"[{movie.library}] {_describe_version(movie.versions[0]) if movie.versions else movie.item_id}" for movie in items],
        ))
    return issues


def suggestion_issue(
    series: LibrarySeries,
    summary: str,
    details: list[str],
    adopt_kind: str,
    adopt_rule: str,
) -> Issue:
    """生成 AI 建议问题：已通过规则验证，用户采纳后写入对应规则。"""
    return _series_issue(
        series,
        IssueType.SUGGESTION,
        severity=Severity.INFO,
        summary=summary,
        details=details,
        scope=series_scope(series.tmdb_id, series.server, series.item_id, series.origin),
        adopt_kind=adopt_kind,
        adopt_rule=adopt_rule,
    )
