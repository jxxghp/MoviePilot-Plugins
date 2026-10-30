"""影视库完整性检查：取值归一、忽略规则与缺集/版本/多文件规则测试。"""

from datetime import date

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
    assert issue.details[0] == "TMDB 没有第 6 季（TMDB 共 2 季），库内 E01-E02 无法对应"
    assert any("可能认错了剧" in line for line in issue.details)


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
