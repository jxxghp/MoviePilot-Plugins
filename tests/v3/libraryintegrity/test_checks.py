"""影视库完整性检查：取值归一、忽略规则与缺集/版本/多文件规则测试。"""

from dataclasses import replace
from datetime import date, timedelta

from app.plugins.libraryintegrity.checks import (
    apply_ignore_rules,
    conflict_issues,
    duplicate_issues,
    find_missing,
    format_episode_ranges,
    match_episodes,
    missing_issues,
    movie_duplicate_issues,
    normalize_codec,
    normalize_hdr,
    normalize_resolution_text,
    parse_ignore_rules,
    parse_scope,
    resolution_bucket,
    version_issues,
)
from app.plugins.libraryintegrity.models import (
    IssueType,
    LibraryEpisode,
    LibraryMovie,
    LibrarySeries,
    Severity,
    TmdbEpisodeRef,
    TmdbSeries,
    VersionInfo,
)

TODAY = date(2026, 10, 30)


def _tmdb(seasons: dict[int, int], air_date: str = "2026-01-01", series_id: int = 100) -> TmdbSeries:
    """构造季集结构：单集 ID 为 季*1000+集 + 10000。"""
    tmdb = TmdbSeries(tmdb_id=series_id)
    for season, count in seasons.items():
        tmdb.seasons[season] = [
            TmdbEpisodeRef(tmdb_id=10000 + season * 1000 + n, season=season, episode=n, air_date=air_date, name=f"第{n}集")
            for n in range(1, count + 1)
        ]
    return tmdb


def _episode(season, episode, tmdb_id=None, end=None, item_id=None, **version) -> LibraryEpisode:
    """构造库内单集。"""
    return LibraryEpisode(
        item_id=item_id or f"i{season}-{episode}",
        season=season,
        episode=episode,
        episode_end=end,
        tmdb_id=tmdb_id,
        path=f"/tv/S{season}E{episode}.mkv",
        versions=[VersionInfo(path=f"/tv/S{season}E{episode}.mkv", **version)],
    )


def _series(episodes, tmdb_id=100) -> LibrarySeries:
    """构造库内剧集。"""
    return LibrarySeries(server="Emby", library="剧集", item_id="s1", title="测试剧", year="2026", tmdb_id=tmdb_id, episodes=episodes)


# ---------------- 取值归一 ----------------

def test_resolution_bucket_handles_cropped_and_portrait_sizes():
    """裁黑边的宽银幕按宽度归档，缺少宽高时返回未知。"""
    assert resolution_bucket(1920, 800) == "1080p"
    assert resolution_bucket(3840, 1600) == "2160p"
    assert resolution_bucket(1280, 536) == "720p"
    assert resolution_bucket(720, 480) == "480p"
    assert resolution_bucket(None, None) is None


def test_resolution_text_and_codec_normalization():
    """文件名分辨率标记与编码别名归一。"""
    assert normalize_resolution_text("2160p") == "2160p"
    assert normalize_resolution_text("4K") == "2160p"
    assert normalize_resolution_text("1080i") == "1080p"
    assert normalize_resolution_text("") is None
    assert normalize_codec("hevc") == normalize_codec("x265") == "HEVC"
    assert normalize_codec("h264") == normalize_codec("AVC") == "H.264"
    assert normalize_codec("x265 10bit") == normalize_codec("H.265") == "HEVC"
    assert normalize_codec("mpeg2video") == "MPEG-2"
    assert normalize_codec("prores") == "PRORES"


def test_normalize_hdr_prefers_first_recognizable_and_never_guesses_sdr():
    """按传入顺序识别 HDR 类型；没有任何线索时为未知而不是 SDR。"""
    assert normalize_hdr("DolbyVision", "4K HDR10") == "DV"
    assert normalize_hdr("None", "4K HEVC HDR10") == "HDR10"
    assert normalize_hdr(None, None, "SDR") == "SDR"
    assert normalize_hdr("DV HDR10") == "DV"
    assert normalize_hdr("HDR10+") == "HDR10+"
    assert normalize_hdr(None, "") is None
    assert normalize_hdr("WEB-DL") is None


def test_format_episode_ranges_compresses_consecutive_numbers():
    """连续集号压缩为区间。"""
    assert format_episode_ranges([5, 1, 2, 3, 8, 9]) == "E01-E03、E05、E08-E09"
    assert format_episode_ranges([]) == ""


# ---------------- 忽略规则 ----------------

def test_parse_scope_and_rules():
    """范围键与规则解析，非法类型的规则被丢弃。"""
    assert parse_scope("tmdb:1:S2E3") == ("tmdb:1", 2, 3)
    assert parse_scope("tmdb:1:S10") == ("tmdb:1", 10, None)
    assert parse_scope("emby:My Server/abc") == ("emby:my server/abc", None, None)
    rules = parse_ignore_rules("tmdb:1  # 整部\nmissing@tmdb:2:S1\nbogus@tmdb:3\n\n")
    assert len(rules) == 2
    assert rules[1].issue_type == IssueType.MISSING


def test_season_rule_does_not_match_other_season_with_same_prefix():
    """S1 规则不能误伤 S10。"""
    rule = parse_ignore_rules("tmdb:1:S1")[0]
    assert rule.matches(IssueType.MISSING, "tmdb:1:S1")
    assert rule.matches(IssueType.MISSING, "tmdb:1:S1E3")
    assert not rule.matches(IssueType.MISSING, "tmdb:1:S10")
    assert not rule.matches(IssueType.MISSING, "tmdb:11:S1")


def test_apply_ignore_rules_filters_missing_per_episode():
    """缺集问题逐集过滤：部分忽略时更新说明，全部忽略时整条隐藏。"""
    series = _series([])
    issues = missing_issues(series, {1: _tmdb({1: 3}).seasons[1]})
    visible, ignored = apply_ignore_rules(issues, parse_ignore_rules("missing@tmdb:100:S1E2"))
    assert ignored == 0
    assert visible[0].episodes == [1, 3]
    assert "E01、E03" in visible[0].summary
    visible, ignored = apply_ignore_rules(issues, parse_ignore_rules("tmdb:100:S1E1\ntmdb:100:S1E2\ntmdb:100:S1E3"))
    assert visible == [] and ignored == 1
    visible, ignored = apply_ignore_rules(issues, parse_ignore_rules("version@tmdb:100"))
    assert len(visible) == 1 and ignored == 0


# ---------------- 匹配与缺集 ----------------

def test_match_prefers_episode_id_over_numbering():
    """单集 ID 有效时按 ID 匹配，即使库内编号与 TMDB 不同（如绝对集数）。"""
    tmdb = _tmdb({1: 2, 2: 2})
    series = _series([_episode(1, 3, tmdb_id=12001)])
    match = match_episodes(series, tmdb)[0]
    assert match.method == "id"
    assert [ref.tmdb_id for ref in match.refs] == [12001]


def test_match_rejects_series_id_written_as_episode_id():
    """旧 NFO 把剧集 ID 写进单集时视为无效，回退按季集号匹配。"""
    tmdb = _tmdb({1: 2})
    series = _series([_episode(1, 2, tmdb_id=100)])
    match = match_episodes(series, tmdb)[0]
    assert match.method == "number"
    assert match.invalid_id
    assert match.refs[0].episode == 2


def test_multi_episode_file_covers_following_episodes():
    """多集文件按 ID 匹配首集后补齐后续集，按编号匹配时覆盖起止范围。"""
    tmdb = _tmdb({1: 4})
    by_id = match_episodes(_series([_episode(1, 1, tmdb_id=11001, end=2)]), tmdb)[0]
    assert [ref.episode for ref in by_id.refs] == [1, 2]
    by_number = match_episodes(_series([_episode(1, 3, end=4)]), tmdb)[0]
    assert [ref.episode for ref in by_number.refs] == [3, 4]


def test_find_missing_only_counts_aired_episodes_after_buffer():
    """未播出、播出日期为空或仍在缓冲期内的集不计入缺集。"""
    tmdb = _tmdb({1: 3})
    tmdb.seasons[1] = [
        TmdbEpisodeRef(11001, 1, 1, "2026-10-01"),
        TmdbEpisodeRef(11002, 1, 2, "2026-10-29"),
        TmdbEpisodeRef(11003, 1, 3, ""),
        TmdbEpisodeRef(11004, 1, 4, "2026-11-20"),
    ]
    matches = match_episodes(_series([]), tmdb)
    missing = find_missing(tmdb, matches, TODAY, buffer_days=2)
    assert [ref.episode for ref in missing[1]] == [1]
    missing = find_missing(tmdb, matches, TODAY, buffer_days=0)
    assert [ref.episode for ref in missing[1]] == [1, 2]


def test_find_missing_specials_and_existing_seasons_options():
    """默认不查第 0 季；只查已有季时跳过整季缺失。"""
    tmdb = _tmdb({0: 2, 1: 2, 2: 2})
    matches = match_episodes(_series([_episode(1, 1), _episode(1, 2)]), tmdb)
    assert sorted(find_missing(tmdb, matches, TODAY)) == [2]
    assert sorted(find_missing(tmdb, matches, TODAY, include_specials=True)) == [0, 2]
    assert find_missing(tmdb, matches, TODAY, only_existing_seasons=True) == {}


def test_missing_issue_scope_and_summary():
    """缺集问题按季生成，范围键可用于忽略。"""
    tmdb = _tmdb({1: 5})
    series = _series([_episode(1, 1), _episode(1, 2), _episode(1, 4)])
    issues = missing_issues(series, find_missing(tmdb, match_episodes(series, tmdb), TODAY))
    assert len(issues) == 1
    issue = issues[0]
    assert issue.type == IssueType.MISSING
    assert issue.episodes == [3, 5]
    assert issue.scope == "tmdb:100:S1"
    assert issue.media_source == "themoviedb" and issue.media_id == "100"


def test_conflicts_are_aggregated_per_season_with_hints():
    """编号冲突每季一条：汇总 TMDB 中没有的集、采集阶段的冲突说明；缺少季集号的单独一条；都带处理提示。"""
    tmdb = _tmdb({1: 2})
    noted = _episode(1, 2)
    noted.conflicts.append("NFO 记录为 S01E05")
    series = _series([_episode(1, 1), _episode(1, 30), _episode(1, 31), noted, _episode(None, None)])
    issues = conflict_issues(series, match_episodes(series, tmdb), include_specials=False, tmdb=tmdb)
    assert len(issues) == 2
    season_issue, unnumbered = issues
    assert season_issue.summary == "第 1 季 3 集编号无法与 TMDB 对应：E02、E30-E31"
    assert season_issue.scope == "tmdb:100:S1" and season_issue.episodes == [2, 30, 31]
    assert "TMDB 第 1 季中没有 E30-E31" in season_issue.details
    assert "S01E02：NFO 记录为 S01E05" in season_issue.details
    assert any(
        line.startswith("处理：编号整体错位") and "tmdb:100 S1E30-E31 => S<TMDB 季>E<起始集>" in line
        and "emby:Emby/s1 => tmdb:正确ID" in line
        for line in season_issue.details
    )
    assert unnumbered.summary == "1 个单集缺少季号或集号" and unnumbered.scope == "tmdb:100"


def test_conflict_hint_for_season_absent_from_tmdb():
    """TMDB 没有该季时提示可能认错了剧。"""
    tmdb = _tmdb({1: 25, 2: 30})
    series = _series([_episode(6, 1), _episode(6, 2)])
    issue = conflict_issues(series, match_episodes(series, tmdb), include_specials=False, tmdb=tmdb)[0]
    assert issue.details[0] == "TMDB 没有第 6 季（TMDB 正片为第 1-2 季），库内 E01-E02 无法对应"
    assert any("认错了剧" in line for line in issue.details)


def test_minor_tail_extras_get_ignore_hint():
    """季末多出一两集（TMDB 合并的双集）提示可忽略。"""
    tmdb = _tmdb({1: 23})
    series = _series([_episode(1, n) for n in range(1, 25)])
    issue = conflict_issues(series, match_episodes(series, tmdb), include_specials=False, tmdb=tmdb)[0]
    assert issue.summary == "第 1 季 1 集编号无法与 TMDB 对应：E24"
    assert any("TMDB 合并的双集" in line for line in issue.details)


def test_numbering_misaligned_distinguishes_stray_extras_from_systematic():
    """零星的季末多集不算错位；TMDB 没有的季、超出零星范围的多集、缺少季号都算错位。"""
    from app.plugins.libraryintegrity.checks import numbering_misaligned

    def misaligned(episodes, seasons):
        """按给定季结构判断。"""
        tmdb = _tmdb(seasons)
        return numbering_misaligned(match_episodes(_series(episodes), tmdb), tmdb, include_specials=False)

    friends = [_episode(1, n) for n in range(1, 25)] + [_episode(2, n) for n in range(1, 26)]
    assert not misaligned(friends, {1: 23, 2: 23, 3: 23})
    assert not misaligned([_episode(1, 0), _episode(1, 1)], {1: 12})
    assert misaligned([_episode(6, 1)], {1: 25, 2: 30})
    assert misaligned([_episode(2, n) for n in range(1, 60)], {2: 36})
    assert misaligned([_episode(1, n) for n in range(1, 5)], {1: 2, 2: 2})
    assert misaligned([_episode(None, None)], {1: 3})
    assert not misaligned([_episode(0, 9), _episode(1, 1)], {0: 1, 1: 1})


def test_unreliable_missing_issue_replaces_missing():
    """编号不一致时缺集改为一条无法核对，列出按当前对应未找到的集。"""
    from app.plugins.libraryintegrity.checks import unreliable_missing_issue

    tmdb = _tmdb({1: 3, 2: 2})
    series = _series([_episode(1, 1), _episode(1, 9)])
    matches = match_episodes(series, tmdb)
    issue = unreliable_missing_issue(series, find_missing(tmdb, matches, TODAY))
    assert issue.type == IssueType.UNCHECKED
    assert "TMDB 有 4 集未找到" in issue.summary
    assert issue.details[:2] == ["第 1 季：E02-E03", "第 2 季：E01-E02"]


def test_display_title_does_not_repeat_year():
    """剧名本身带年份时不再重复追加。"""
    from app.plugins.libraryintegrity.checks import display_title

    assert display_title("哆啦A梦 (2005)", "2005") == "哆啦A梦 (2005)"
    assert display_title("哆啦A梦（2005）", "2005") == "哆啦A梦（2005）"
    assert display_title("哆啦A梦 (1979)", "2005") == "哆啦A梦 (1979) (2005)"
    assert display_title("剧", "2020") == "剧 (2020)"
    assert display_title("剧", "") == "剧"


# ---------------- 版本一致性 ----------------

def test_version_issue_reports_outliers_against_majority():
    """多数为 1080p 时报告偏离的单集，未知取值不参与比较。"""
    series = _series([
        _episode(1, 1, resolution="1080p"),
        _episode(1, 2, resolution="1080p"),
        _episode(1, 3, resolution="720p"),
        _episode(1, 4, resolution=None),
    ])
    issues = version_issues(series, ["resolution"], include_specials=False)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == Severity.WARNING
    assert issue.episodes == [3]
    assert "多数为 1080p（2/3 集）" in issue.summary
    assert any("另有 1 集" in line for line in issue.details)


def test_version_issue_reports_mixed_when_no_majority():
    """没有多数版本时报告分布，不指定偏离集。"""
    series = _series([
        _episode(1, 1, release_group="A"),
        _episode(1, 2, release_group="B"),
    ])
    issue = version_issues(series, ["release_group"], include_specials=False)[0]
    assert issue.severity == Severity.INFO
    assert issue.episodes == []
    assert "混杂" in issue.summary


def test_version_consistent_season_has_no_issue():
    """取值一致或已知取值不足两集时不报告。"""
    series = _series([_episode(1, 1, hdr="DV"), _episode(1, 2, hdr="DV"), _episode(2, 1, hdr="SDR")])
    assert version_issues(series, ["hdr"], include_specials=False) == []


# ---------------- 多文件 ----------------

def test_duplicate_versions_and_entries():
    """单个条目多版本、多个条目指向同一集都报告；strm 与本地并存可按配置忽略。"""
    tmdb = _tmdb({1: 2})
    multi = _episode(1, 1)
    multi.versions.append(VersionInfo(path="/strm/S1E1.strm", kind="strm"))
    copy_a = _episode(1, 2, item_id="a")
    copy_b = _episode(1, 2, item_id="b")
    series = _series([multi, copy_a, copy_b])
    issues = duplicate_issues(series, match_episodes(series, tmdb), ignore_mixed=False, include_specials=False)
    assert {issue.summary for issue in issues} == {"S01E01 有 2 个版本", "S01E02 对应 2 个条目"}
    issues = duplicate_issues(series, match_episodes(series, tmdb), ignore_mixed=True, include_specials=False)
    assert [issue.summary for issue in issues] == ["S01E02 对应 2 个条目"]


def test_movie_duplicates_by_versions_and_tmdb_id():
    """电影多版本与同一 TMDB 电影的多个条目。"""
    movies = [
        LibraryMovie("Emby", "电影", "m1", "A", tmdb_id=1, versions=[VersionInfo(path="/a1.mkv"), VersionInfo(path="/a2.mkv")]),
        LibraryMovie("Emby", "电影", "m2", "B", tmdb_id=2, versions=[VersionInfo(path="/b.mkv")]),
        LibraryMovie("Emby", "电影4K", "m3", "B", tmdb_id=2, versions=[VersionInfo(path="/b4k.mkv")]),
        LibraryMovie("Emby", "电影", "m4", "C", tmdb_id=None, versions=[VersionInfo(path="/c.mkv")]),
    ]
    issues = movie_duplicate_issues(movies, ignore_mixed=False)
    assert {issue.summary for issue in issues} == {"电影有 2 个版本", "同一电影对应 2 个条目"}
    assert all(issue.media_type == "movie" for issue in issues)


# ---------------- 采纳规则 ----------------

def test_parse_number_mappings_and_translate():
    """编号映射解析与翻译，非法行与倒序范围被忽略。"""
    from app.plugins.libraryintegrity.checks import parse_number_mappings, translate_number

    rules = parse_number_mappings(
        "tmdb:5 S1E13-E24 => S2E1  # 第二季\nTMDB:5 S1E25 => S3E1\ntmdb:5 S1E9-E3 => S2E1\n乱写"
    )
    mappings = rules["tmdb:5"]
    assert len(mappings) == 2
    assert translate_number(mappings, 1, 13) == (2, 1)
    assert translate_number(mappings, 1, 24) == (2, 12)
    assert translate_number(mappings, 1, 25) == (3, 1)
    assert translate_number(mappings, 1, 12) == (1, 12)
    assert mappings[0].describe("tmdb:5") == "tmdb:5 S1E13-E24 => S2E1"
    assert mappings[1].describe("tmdb:5") == "tmdb:5 S1E25 => S3E1"


def test_parse_identity_overrides_supports_paths_with_spaces():
    """身份指定支持带空格的本地路径，目标必须是 tmdb:ID。"""
    from app.plugins.libraryintegrity.checks import parse_identity_overrides

    rules = parse_identity_overrides("local:/media/剧 名 => tmdb:7\nemby:Emby/12 => TMDB:8\nemby:x => douban:1")
    assert rules == {"local:/media/剧 名": 7, "emby:emby/12": 8}


def test_summarize_match_counts_unmatched_missing_and_collisions():
    """映射前后的统计：未匹配集数、缺集数与撞集。"""
    from app.plugins.libraryintegrity.checks import NumberMapping, numbering_improves, summarize_match

    tmdb = _tmdb({1: 2, 2: 2})
    series = _series([_episode(1, n) for n in range(1, 5)])
    before = summarize_match(series, tmdb, None, TODAY, 2, False)
    assert (before.unmatched, before.missing, before.collisions) == (2, 2, 0)
    good = summarize_match(series, tmdb, [NumberMapping(1, 3, 4, 2, 1)], TODAY, 2, False)
    assert (good.unmatched, good.missing) == (0, 0)
    assert numbering_improves(before, good)
    bad = summarize_match(series, tmdb, [NumberMapping(1, 3, 4, 1, 1)], TODAY, 2, False)
    assert bad.collisions == 2 and not numbering_improves(before, bad)


def test_identity_coverage_ratio():
    """身份覆盖率按季集号计算，忽略第 0 季。"""
    from app.plugins.libraryintegrity.checks import identity_coverage

    tmdb = _tmdb({1: 2})
    assert identity_coverage(_series([_episode(1, 1), _episode(1, 2), _episode(0, 1)]), tmdb) == 1.0
    assert identity_coverage(_series([_episode(1, 1), _episode(1, 5)]), tmdb) == 0.5
    assert identity_coverage(_series([]), tmdb) == 0.0


def _paired_tmdb(seasons: dict[int, int], series_id: int = 100) -> TmdbSeries:
    """构造拆分短篇的季集结构：TMDB 单集两两同日播出。"""
    tmdb = TmdbSeries(tmdb_id=series_id)
    for season, count in seasons.items():
        tmdb.seasons[season] = [
            TmdbEpisodeRef(
                tmdb_id=10000 + season * 1000 + n, season=season, episode=n,
                air_date=f"2015-{season:02d}-{(n + 1) // 2:02d}", name=f"第{n}集",
            )
            for n in range(1, count + 1)
        ]
    return tmdb


def test_split_episode_seasons_detected_when_several_seasons_pair_up():
    """多季都是库内前 n 集、TMDB 约 2n 集且两两同日播出时，判定为一个文件含两集，这些季不报缺集。"""
    from app.plugins.libraryintegrity.checks import split_episode_issue, split_episode_seasons

    tmdb = _paired_tmdb({1: 47, 2: 50, 3: 26})
    episodes = [_episode(s, n) for s, size in ((1, 26), (2, 26), (3, 20)) for n in range(1, size + 1)]
    series = _series(episodes)
    matches = match_episodes(series, tmdb)
    missing = find_missing(tmdb, matches, TODAY)
    assert split_episode_seasons(matches, tmdb, missing) == [1, 2]
    issue = split_episode_issue(series, tmdb, [1, 2], matches)
    assert issue.type == IssueType.UNCHECKED
    assert issue.summary == "疑似一个文件含 TMDB 两集，第 1-2 季未核对缺集"
    assert issue.details[0] == "第 1 季：库内 26 集，TMDB 47 集"


def test_split_episode_seasons_needs_two_paired_seasons():
    """只有一季呈此形态、或 TMDB 单集并非两两同日播出时，按真缺集报告。"""
    from app.plugins.libraryintegrity.checks import split_episode_seasons

    def split(tmdb, sizes):
        """按库内各季集数判定。"""
        series = _series([_episode(s, n) for s, size in sizes.items() for n in range(1, size + 1)])
        matches = match_episodes(series, tmdb)
        return split_episode_seasons(matches, tmdb, find_missing(tmdb, matches, TODAY))

    # 只有一季：可能确实只下了前半季
    assert split(_paired_tmdb({1: 47, 2: 26}), {1: 26, 2: 26}) == []
    # 不是两两同日播出（普通剧集只下了一半）
    weekly = _tmdb({1: 52, 2: 52})
    for season, refs in weekly.seasons.items():
        weekly.seasons[season] = [
            replace(ref, air_date=str(date(2015, 1, 1) + timedelta(days=7 * (season * 100 + ref.episode))))
            for ref in refs
        ]
    assert split(weekly, {1: 26, 2: 26}) == []
    # 缺的不是紧接着的后半段（中间有断档）
    tmdb = _paired_tmdb({1: 47, 2: 47})
    series = _series([_episode(s, n) for s in (1, 2) for n in range(1, 27) if n != 5])
    matches = match_episodes(series, tmdb)
    assert split_episode_seasons(matches, tmdb, find_missing(tmdb, matches, TODAY)) == []


def _titled_tmdb(count: int, placeholders: int, gap: int, status: str = "Ended") -> TmdbSeries:
    """构造单季剧：前 count 集有标题，末尾 placeholders 集只有集号，其 ID 比前面大 gap。"""
    tmdb = TmdbSeries(tmdb_id=100, status=status)
    refs = [
        TmdbEpisodeRef(tmdb_id=20000 + n, season=1, episode=n, air_date="2020-09-10", name=f"剧情{n}")
        for n in range(1, count + 1)
    ]
    refs += [
        TmdbEpisodeRef(tmdb_id=20000 + count + gap + n, season=1, episode=count + n, air_date="2021-01-09", name=f"第 {count + n} 集")
        for n in range(1, placeholders + 1)
    ]
    tmdb.seasons[1] = refs
    return tmdb


def test_placeholder_tail_of_ended_series_is_not_missing():
    """已完结剧季末后补的无标题集（如长安诺 E57-E60）不报缺集，改为一条无法核对。"""
    from app.plugins.libraryintegrity.checks import placeholder_tail_issue, placeholder_tail_seasons

    tmdb = _titled_tmdb(56, 4, gap=3_500_000)
    series = _series([_episode(1, n) for n in range(1, 57)])
    matches = match_episodes(series, tmdb)
    missing = find_missing(tmdb, matches, TODAY)
    tails = placeholder_tail_seasons(tmdb, matches, missing)
    assert [ref.episode for ref in tails[1]] == [57, 58, 59, 60]
    issue = placeholder_tail_issue(series, tails)
    assert issue.type == IssueType.UNCHECKED and issue.severity == Severity.INFO
    assert issue.summary == "TMDB 第 1 季末尾 E57-E60 疑似多余的占位集，未报缺集"


def test_placeholder_tail_requires_all_signals():
    """仍在播出、与前面同批建立、库内中间也缺、或库内最后一集也无标题时，照常报缺集。"""
    from app.plugins.libraryintegrity.checks import placeholder_tail_seasons

    def tails(tmdb, numbers):
        """按库内集号判定。"""
        series = _series([_episode(1, n) for n in numbers])
        matches = match_episodes(series, tmdb)
        return placeholder_tail_seasons(tmdb, matches, find_missing(tmdb, matches, TODAY))

    full = range(1, 57)
    assert tails(_titled_tmdb(56, 4, gap=3_500_000, status="Returning Series"), full) == {}
    assert tails(_titled_tmdb(56, 4, gap=1), full) == {}
    assert tails(_titled_tmdb(56, 4, gap=3_500_000), [n for n in full if n != 30]) == {}
    # 缺的不只是占位集：库内只到 E50，E51-E56 有正式标题
    assert tails(_titled_tmdb(56, 4, gap=3_500_000), range(1, 51)) == {}
    # 全剧都只有集号（如蜗居），无从判断末尾是否多余
    untitled = _titled_tmdb(56, 4, gap=3_500_000)
    untitled.seasons[1] = [replace(ref, name=f"第 {ref.episode} 集") for ref in untitled.seasons[1]]
    assert tails(untitled, full) == {}


def test_undated_episodes_before_an_aired_one_count_as_missing():
    """TMDB 中没填播出日期、但排在已播出单集之前的集算已播出；排在最后一个已播出单集之后的不算。"""
    tmdb = _tmdb({1: 10})
    tmdb.seasons[1] = [
        replace(ref, air_date="" if 3 <= ref.episode <= 9 and ref.episode != 6 else ref.air_date) for ref in tmdb.seasons[1]
    ]
    tmdb.seasons[1][-1] = replace(tmdb.seasons[1][-1], air_date="")
    series = _series([_episode(1, 1), _episode(1, 2)])
    missing = find_missing(tmdb, match_episodes(series, tmdb), TODAY)
    assert [ref.episode for ref in missing[1]] == [3, 4, 5, 6]
    issue = missing_issues(series, missing)[0]
    assert issue.details[0] == "E03 第3集（TMDB 未填播出日期）"


def test_part_files_of_one_episode_are_not_versions():
    """同一集拆成 Part1/Part2 的文件不报多版本；分段的两个不同版本仍报。"""
    def versions(*names):
        """按文件名构造版本。"""
        return [VersionInfo(path=f"/tv/Season 5/{name}") for name in names]

    tmdb = _tmdb({5: 9})
    split = replace(_episode(5, 8), versions=versions("S05E08-Part1 - 第 8 集.strm", "S05E08-Part2 - 第 8 集.strm"))
    assert duplicate_issues(_series([split]), match_episodes(_series([split]), tmdb), False, False) == []
    two = replace(_episode(5, 8), versions=versions(
        "S05E08-Part1 - 1080p.strm", "S05E08-Part2 - 1080p.strm", "S05E08 - 2160p.strm",
    ))
    issues = duplicate_issues(_series([two]), match_episodes(_series([two]), tmdb), False, False)
    assert [issue.summary for issue in issues] == ["S05E08 有 2 个版本"]
    # 媒体服务器没有合并分段时是两个条目
    parts = [
        replace(_episode(5, 8, item_id="p1"), path="/tv/S05E08.cd1.mkv"),
        replace(_episode(5, 8, item_id="p2"), path="/tv/S05E08.cd2.mkv"),
    ]
    assert duplicate_issues(_series(parts), match_episodes(_series(parts), tmdb), False, False) == []


def test_mapping_date_check_rejects_shift_to_wrong_year():
    """映射到的 TMDB 单集播出日期与库内首播日期相差太远时不通过；没有日期时无法否定。"""
    from app.plugins.libraryintegrity.checks import NumberMapping, mapping_date_check

    tmdb = TmdbSeries(tmdb_id=100, seasons={1: [
        TmdbEpisodeRef(tmdb_id=n, season=1, episode=n, air_date=str(date(2005, 4, 15) + timedelta(days=7 * n)))
        for n in range(1, 301)
    ]})
    episodes = [_episode(5, n) for n in range(1, 11)]
    for n, episode in enumerate(episodes, start=1):
        episode.air_date = str(date(2005, 4, 15) + timedelta(days=7 * (199 + n)))
    series = _series(episodes)
    right = mapping_date_check(series, tmdb, [NumberMapping(5, 1, 10, 1, 200)])
    assert right.passed and (right.checked, right.agreed) == (10, 10)
    wrong = mapping_date_check(series, tmdb, [NumberMapping(5, 1, 10, 1, 143)])
    assert not wrong.passed and wrong.agreed == 0
    assert wrong.sample == "库内 S05E01（2009-02-13）→ TMDB S01E143（2008-01-11）"
    for episode in episodes:
        episode.air_date = ""
    unknown = mapping_date_check(series, tmdb, [NumberMapping(5, 1, 10, 1, 143)])
    assert unknown.passed and unknown.describe() == "库内这些单集没有首播日期，未核对播出日期"


def test_empty_tmdb_season_is_not_misaligned_and_hints_waiting():
    """TMDB 已建季但没有单集：不算整体错位，提示等待 TMDB 补全而不是编号映射。"""
    from app.plugins.libraryintegrity.checks import numbering_misaligned

    tmdb = _tmdb({1: 3, 8: 0})
    series = _series([_episode(1, 1), _episode(8, 1), _episode(8, 2)])
    matches = match_episodes(series, tmdb)
    assert not numbering_misaligned(matches, tmdb, include_specials=False)
    issue = conflict_issues(series, matches, include_specials=False, tmdb=tmdb)[0]
    assert "TMDB 第 8 季暂无单集数据，库内 E01-E02 暂时无法对应" in issue.details
    assert any("等 TMDB 补全" in line and "编号映射" in line for line in issue.details)
    assert not any("tmdb:100 S8" in line for line in issue.details)


def test_absent_season_hint_suggests_absolute_numbering_mapping():
    """TMDB 只有一个正片季（按绝对集数）时，提示把库内季映射到该季，而不是只建议身份指定。"""
    tmdb = _tmdb({0: 5, 1: 1400})
    series = _series([_episode(1, 1), _episode(5, 1), _episode(5, 80)])
    issue = conflict_issues(series, match_episodes(series, tmdb), include_specials=False, tmdb=tmdb)[0]
    assert issue.details[0] == "TMDB 没有第 5 季（TMDB 正片为第 1 季），库内 E01、E80 无法对应"
    hint = next(line for line in issue.details if line.startswith("处理："))
    assert "绝对集数" in hint and "tmdb:100 S5E1-E80 => S1E<起始集>" in hint and "身份指定" in hint


def test_absent_season_hint_for_multi_season_show():
    """TMDB 有多个正片季时提示分季方式可能不同，给出编号映射写法。"""
    tmdb = _tmdb({1: 25, 2: 30, 3: 10})
    series = _series([_episode(6, 1), _episode(6, 2)])
    issue = conflict_issues(series, match_episodes(series, tmdb), include_specials=False, tmdb=tmdb)[0]
    assert issue.details[0] == "TMDB 没有第 6 季（TMDB 正片为第 1-3 季），库内 E01-E02 无法对应"
    hint = next(line for line in issue.details if line.startswith("处理："))
    assert "tmdb:100 S6E1-E2 => S<TMDB 季>E<起始集>" in hint and "身份指定" in hint
