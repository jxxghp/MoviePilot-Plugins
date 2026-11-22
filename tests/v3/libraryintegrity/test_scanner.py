"""影视库完整性检查：扫描编排端到端测试（Emby、TMDB、AI 使用替身，NFO 使用临时文件）。"""

import json
import threading
from datetime import date, timedelta

from app.plugins.libraryintegrity.ai import (
    FAILED_RETRY_DAYS,
    AiAdvisor,
    AiAnswerCache,
    IdentityAnswer,
    MappingItem,
    NumberingAnswer,
)
from app.plugins.libraryintegrity.checks import parse_identity_overrides, parse_ignore_rules, parse_number_mappings
from app.plugins.libraryintegrity.emby import EmbyError, EmbySource
from app.plugins.libraryintegrity.models import ORIGIN_EMBY, ORIGIN_LOCAL, IssueType, LibraryEpisode
from app.plugins.libraryintegrity.nfo import NfoReader, PathMapper
from app.plugins.libraryintegrity.scanner import LibraryScanner, ScanOptions
from app.plugins.libraryintegrity.tmdb import TmdbSource

TODAY = date(2026, 10, 30)


def _stream(width, height):
    """构造带视频流的 MediaSource 列表。"""
    return [{"Path": "x", "MediaStreams": [{"Type": "Video", "Width": width, "Height": height, "Codec": "hevc"}]}]


class _FakeReader:
    """Emby 读取器替身。"""

    name = "Emby"

    def __init__(self, series, episodes, fail_series=()):
        """记录剧集、各剧单集与需要失败的剧。"""
        self._series = series
        self._episodes = episodes
        self._fail = set(fail_series)

    def libraries(self):
        """返回一个剧集库和一个电影库。"""
        return [
            {"Name": "电视剧", "ItemId": "tv", "CollectionType": "tvshows"},
            {"Name": "电影", "ItemId": "mv", "CollectionType": "movies"},
        ]

    def iter_items(self, parent_id, item_types, fields):
        """按媒体库返回剧集或电影。"""
        if parent_id == "tv" and item_types == "Series":
            yield from self._series
        if parent_id == "mv" and item_types == "Movie":
            yield {"Id": "m1", "Name": "电影", "ProviderIds": {"Tmdb": "9"}, "MediaSources": [{"Path": "/mv/a.mkv"}]}
            yield {"Id": "m2", "Name": "电影", "ProviderIds": {"Tmdb": "9"}, "MediaSources": [{"Path": "/mv/b.mkv"}]}

    def series_episodes(self, series_id):
        """返回单集或模拟读取失败。"""
        if series_id in self._fail:
            raise EmbyError("超时")
        return self._episodes.get(series_id, [])


def _season(season, count, offset=0):
    """构造全部已播出的季详情：单集 ID 为 季*100+集。"""
    return {"episodes": [
        {"id": season * 100 + n, "episode_number": n, "air_date": "2026-01-01", "name": f"E{n}"}
        for n in range(1 + offset, count + 1 + offset)
    ]}


class _Tv:
    """TMDB 剧集接口替身：剧 1 只有第 1 季 4 集；剧 5 有两季各 2 集；剧 7 有一季 2 集；其他不存在。"""

    def details(self, tmdb_id, append_to_response=None):
        """返回剧集详情。"""
        seasons = {1: [1], 5: [1, 2], 7: [1]}.get(tmdb_id)
        if seasons is None:
            raise RuntimeError("The resource you requested could not be found.")
        return {"id": tmdb_id, "name": f"剧{tmdb_id}", "status": "Ended", "seasons": [{"season_number": s} for s in seasons]}


class _Season:
    """TMDB 季接口替身。"""

    def details(self, tmdb_id, season, append_to_response=None):
        """返回季详情。"""
        if tmdb_id == 1:
            return _season(1, 4)
        if tmdb_id == 5:
            return _season(season, 2)
        return _season(1, 2)


class _Api:
    """TMDB 客户端替身。"""

    tv = _Tv()
    season_obj = _Season()

    def search_tvs(self, title, year):
        """按标题返回搜索候选。"""
        return [{"id": 8, "name": "无关剧"}, {"id": 7, "name": title, "first_air_date": "2020-01-01"}]


def _parser(name):
    """文件名解析替身：不提供任何发布信息。"""
    return {}


def _emby_series():
    """剧 A（tmdb 1）、剧 B（tvshow.nfo 提供 tmdb 2）、剧 C（无身份）、剧 D（读取失败）。"""
    return [
        {"Id": "A", "Name": "剧A", "ProductionYear": 2020, "ProviderIds": {"Tmdb": "1"}, "Path": "/emby/tv/A"},
        {"Id": "B", "Name": "剧B", "Path": "/emby/tv/B"},
        {"Id": "C", "Name": "剧C", "Path": "/emby/tv/C"},
        {"Id": "D", "Name": "剧D", "ProviderIds": {"Tmdb": "4"}, "Path": "/emby/tv/D"},
    ]


def _emby_episodes():
    """剧 A 的单集：E01 有 ID，E02 为 strm 由 NFO 补 ID 与技术参数，E04 按编号匹配。"""
    return {
        "A": [
            {"Id": "a1", "ParentIndexNumber": 1, "IndexNumber": 1, "ProviderIds": {"Tmdb": "101"},
             "Path": "/emby/tv/A/S01E01.mkv", "MediaSources": _stream(1920, 1080)},
            {"Id": "a2", "ParentIndexNumber": 1, "IndexNumber": 2, "Path": "/emby/tv/A/S01E02.strm",
             "MediaSources": [{"Path": "http://cloud/a2.mkv", "Protocol": "Http", "MediaStreams": []}]},
            {"Id": "a4", "ParentIndexNumber": 1, "IndexNumber": 4,
             "Path": "/emby/tv/A/S01E04.mkv", "MediaSources": _stream(1920, 800)},
        ],
        "C": [
            {"Id": "c1", "ParentIndexNumber": 1, "IndexNumber": 1, "Path": "/emby/tv/C/S01E01.mkv"},
            {"Id": "c2", "ParentIndexNumber": 1, "IndexNumber": 2, "Path": "/emby/tv/C/S01E02.mkv"},
        ],
    }


def _write_nfo(tmp_path):
    """写入剧 A 第 2 集与剧 B 的 NFO，返回本地根目录。"""
    local = tmp_path / "tv"
    (local / "A").mkdir(parents=True, exist_ok=True)
    (local / "B").mkdir(parents=True, exist_ok=True)
    (local / "A" / "S01E02.nfo").write_text(
        "<episodedetails><uniqueid type=\"tmdb\">102</uniqueid><season>1</season><episode>2</episode>"
        "<fileinfo><streamdetails><video><width>3840</width><height>2160</height></video></streamdetails></fileinfo>"
        "</episodedetails>",
        encoding="utf-8",
    )
    (local / "B" / "tvshow.nfo").write_text("<tvshow><tmdbid>2</tmdbid></tvshow>", encoding="utf-8")
    return local


def _scanner(tmp_path, stop_event=None, advisor=None, today=TODAY, ai_cache=None, **overrides):
    """组装扫描器。"""
    options = ScanOptions(dimensions=["resolution"], **overrides)
    return LibraryScanner(
        options,
        TmdbSource(tmp_path / "cache.json", api_factory=_Api),
        stop_event or threading.Event(),
        today=today,
        name_parser=_parser,
        advisor=advisor,
        ai_cache=ai_cache,
    )


def _emby_source(tmp_path, series=None, episodes=None):
    """组装带 NFO 映射的 Emby 数据源。"""
    local = _write_nfo(tmp_path)
    reader = _FakeReader(series or _emby_series(), episodes or _emby_episodes(), fail_series={"D"})
    return EmbySource(reader, [], NfoReader(PathMapper(f"/emby/tv => {local}")))


def _by_type(report):
    """按问题类型分组。"""
    grouped = {}
    for issue in report.issues:
        grouped.setdefault(issue.type, []).append(issue)
    return grouped


def test_scanner_end_to_end(tmp_path):
    """缺集、NFO 补单集 ID 与 strm 技术参数、版本偏离、无法核对与电影多文件。"""
    report = _scanner(tmp_path).scan([_emby_source(tmp_path)])
    by_type = _by_type(report)

    missing = by_type[IssueType.MISSING]
    assert len(missing) == 1 and missing[0].episodes == [3] and missing[0].title == "剧A (2020)"

    version = by_type[IssueType.VERSION]
    assert len(version) == 1 and version[0].episodes == [2]
    assert "2160p" in version[0].details[0]

    unchecked = {issue.title: issue.summary for issue in by_type[IssueType.UNCHECKED]}
    assert "TMDB 查询失败" in unchecked["剧B"]
    assert unchecked["剧C"] == "缺少 TMDB ID，无法核对缺集"
    assert "读取单集失败" in unchecked["剧D"]

    assert [issue.summary for issue in by_type[IssueType.DUPLICATE]] == ["同一电影对应 2 个条目"]
    assert IssueType.CONFLICT not in by_type and IssueType.SUGGESTION not in by_type

    stats = report.stats
    assert (stats.series, stats.episodes, stats.movies, stats.libraries) == (4, 5, 2, 2)
    assert stats.nfo_reads == 2
    assert not report.cancelled and report.finished_at


def test_scanner_stops_when_event_is_set(tmp_path):
    """停止信号置位后扫描尽快结束并标记为已停止。"""
    stop_event = threading.Event()
    stop_event.set()
    report = _scanner(tmp_path, stop_event=stop_event).scan([_emby_source(tmp_path)])
    assert report.cancelled
    assert report.stats.series == 0


def test_scanner_skips_tmdb_when_missing_check_disabled(tmp_path):
    """关闭缺集检查时不请求 TMDB，也不产生缺集与身份类无法核对问题。"""
    report = _scanner(tmp_path, check_missing=False).scan([_emby_source(tmp_path)])
    types = {issue.type for issue in report.issues}
    assert IssueType.MISSING not in types
    assert report.stats.tmdb_requests == 0
    assert all("读取单集失败" in i.summary for i in report.issues if i.type == IssueType.UNCHECKED)


def test_identity_override_and_number_mapping_are_applied(tmp_path):
    """身份指定让剧 C 参与核对；编号映射把绝对集数对应到第 2 季，消除冲突与缺集。"""
    series = [
        {"Id": "C", "Name": "剧C", "Path": "/emby/tv/C"},
        {"Id": "E", "Name": "剧E", "ProviderIds": {"Tmdb": "5"}, "Path": "/emby/tv/E"},
    ]
    episodes = {
        "C": _emby_episodes()["C"],
        "E": [{"Id": f"e{n}", "ParentIndexNumber": 1, "IndexNumber": n, "Path": f"/x/E{n}.mkv"} for n in range(1, 5)],
    }
    source = _emby_source(tmp_path, series, episodes)
    plain = _scanner(tmp_path).scan([source])
    assert {i.type for i in plain.issues} >= {IssueType.CONFLICT, IssueType.UNCHECKED}
    # 编号对不上的剧不直接报缺集，归入无法核对
    assert not [i for i in plain.issues if i.type == IssueType.MISSING and i.title == "剧E"]
    assert any(i.type == IssueType.UNCHECKED and i.title == "剧E" and "缺集结果不可信" in i.summary for i in plain.issues)

    source = _emby_source(tmp_path, series, episodes)
    report = _scanner(
        tmp_path,
        identity_overrides=parse_identity_overrides("emby:Emby/C => tmdb:7"),
        number_mappings=parse_number_mappings("tmdb:5 S1E3-E4 => S2E1"),
    ).scan([source])
    assert [issue for issue in report.issues if issue.media_type == "tv"] == []


class _FakeRunnable:
    """结构化输出替身：按提示内容返回预设答案。"""

    def __init__(self, llm, schema):
        """记录所属模型与结构定义。"""
        self._llm = llm
        self._schema = schema

    async def ainvoke(self, messages):
        """返回预设答案并记录提示。"""
        prompt = messages[-1].content
        self._llm.prompts.append(prompt)
        if self._schema is None:
            return type("Msg", (), {"content": "优先补齐剧A第3集。"})()
        return self._llm.answers[self._schema.__name__]


class _FakeLlm:
    """大模型替身。"""

    def __init__(self, answers):
        """记录各结构的预设答案。"""
        self.answers = answers
        self.prompts = []
        self.closed = False

    def with_structured_output(self, schema):
        """返回结构化输出替身。"""
        return _FakeRunnable(self, schema)

    async def ainvoke(self, messages):
        """文本请求。"""
        return await _FakeRunnable(self, None).ainvoke(messages)


def _advisor(llm, max_calls=10):
    """组装使用替身模型的 AI 顾问。"""

    async def factory():
        """返回替身模型。"""
        return llm

    async def closer(model):
        """记录模型已释放。"""
        model.closed = True

    return AiAdvisor(max_calls=max_calls, llm_factory=factory, llm_closer=closer)


def _ai_series():
    """剧 E 用绝对集数（需要映射），剧 C 缺少身份。"""
    series = [
        {"Id": "C", "Name": "剧C", "Path": "/emby/tv/C"},
        {"Id": "E", "Name": "剧E", "ProviderIds": {"Tmdb": "5"}, "Path": "/emby/tv/E"},
    ]
    episodes = {
        "C": _emby_episodes()["C"],
        "E": [{"Id": f"e{n}", "ParentIndexNumber": 1, "IndexNumber": n, "Path": f"/x/E{n}.mkv"} for n in range(1, 5)],
    }
    return series, episodes


def test_ai_suggestions_are_verified_before_reporting(tmp_path):
    """通过验证的映射与身份建议进入报告并带采纳规则；摘要占用预留的一次调用；模型最终被释放。"""
    llm = _FakeLlm({
        "NumberingAnswer": NumberingAnswer(
            mappings=[MappingItem(library_season=1, library_start=3, library_end=4, tmdb_season=2, tmdb_start=1)],
            confidence=0.9, reason="绝对集数",
        ),
        "IdentityAnswer": IdentityAnswer(candidate=1, confidence=0.8, reason="标题一致"),
    })
    advisor = _advisor(llm, max_calls=None)
    series, episodes = _ai_series()
    report = _scanner(tmp_path, advisor=advisor, ai_summary=True).scan([_emby_source(tmp_path, series, episodes)])
    suggestions = {issue.adopt_kind: issue for issue in report.issues if issue.type == IssueType.SUGGESTION}
    assert suggestions["mapping"].adopt_rule == "tmdb:5 S1E3-E4 => S2E1"
    assert any("无法对应的集 2 → 0" in line for line in suggestions["mapping"].details)
    assert "库内这些单集没有首播日期，未核对播出日期" in suggestions["mapping"].details
    assert suggestions["identity"].adopt_rule == "emby:Emby/C => tmdb:7"
    assert report.ai_summary == "优先补齐剧A第3集。"
    assert report.stats.ai_calls == 3 and llm.closed
    assert any("<data>" in prompt for prompt in llm.prompts)


def test_ai_suggestions_failing_verification_are_dropped(tmp_path):
    """映射不能减少冲突、身份覆盖率不足或把握过低的建议都被丢弃。"""
    llm = _FakeLlm({
        "NumberingAnswer": NumberingAnswer(
            mappings=[MappingItem(library_season=1, library_start=3, library_end=4, tmdb_season=9, tmdb_start=1)],
            confidence=0.9,
        ),
        "IdentityAnswer": IdentityAnswer(candidate=0, confidence=0.9),
    })
    series, episodes = _ai_series()
    report = _scanner(tmp_path, advisor=_advisor(llm)).scan([_emby_source(tmp_path, series, episodes)])
    assert not [issue for issue in report.issues if issue.type == IssueType.SUGGESTION]


def test_ai_mapping_with_mismatched_air_dates_is_dropped(tmp_path):
    """集数凑得上但映射到的 TMDB 单集播出日期与库内首播日期相差很远时，建议被丢弃。"""
    llm = _FakeLlm({
        "NumberingAnswer": NumberingAnswer(
            mappings=[MappingItem(library_season=1, library_start=3, library_end=4, tmdb_season=2, tmdb_start=1)],
            confidence=0.9,
        ),
    })
    series, episodes = _ai_series()
    for item in episodes["E"]:
        item["PremiereDate"] = "2019-05-01T00:00:00.0000000Z"
    report = _scanner(tmp_path, advisor=_advisor(llm)).scan([_emby_source(tmp_path, series, episodes)])
    assert not [issue for issue in report.issues if issue.adopt_kind == "mapping"]
    assert any("S01E03 | 2019-05-01 |" in prompt for prompt in llm.prompts)


def test_ai_respects_budget_and_ignore_rules(tmp_path):
    """被忽略的建议范围不再请求 AI；调用次数不超过预算。"""
    llm = _FakeLlm({
        "NumberingAnswer": NumberingAnswer(confidence=0.9),
        "IdentityAnswer": IdentityAnswer(candidate=-1, confidence=0.9),
    })
    series, episodes = _ai_series()
    advisor = _advisor(llm, max_calls=1)
    _scanner(tmp_path, advisor=advisor, ignore_rules=parse_ignore_rules("suggestion@tmdb:5")).scan(
        [_emby_source(tmp_path, series, episodes)]
    )
    assert advisor.calls == 1
    assert "剧C" in llm.prompts[0]


def test_ai_failure_is_reported_without_breaking_scan(tmp_path):
    """获取模型失败时扫描照常完成，并记录 AI 错误。"""

    async def broken_factory():
        """模拟模型不可用。"""
        raise RuntimeError("未配置模型")

    advisor = AiAdvisor(max_calls=5, llm_factory=broken_factory)
    series, episodes = _ai_series()
    report = _scanner(tmp_path, advisor=advisor).scan([_emby_source(tmp_path, series, episodes)])
    assert any("AI" in error for error in report.errors)
    assert any(issue.type == IssueType.CONFLICT for issue in report.issues)


def _passing_llm():
    """映射与身份都能通过验证的模型替身。"""
    return _FakeLlm({
        "NumberingAnswer": NumberingAnswer(
            mappings=[MappingItem(library_season=1, library_start=3, library_end=4, tmdb_season=2, tmdb_start=1)],
            confidence=0.9, reason="绝对集数",
        ),
        "IdentityAnswer": IdentityAnswer(candidate=1, confidence=0.8, reason="标题一致"),
    })


def _ai_scan(tmp_path, llm, cache_path, today=TODAY, episodes=None):
    """用新的缓存实例执行一次带 AI 的扫描并保存缓存，模拟一次独立的定时扫描。"""
    series, default_episodes = _ai_series()
    cache = AiAnswerCache(cache_path)
    report = _scanner(tmp_path, advisor=_advisor(llm, max_calls=None), today=today, ai_cache=cache).scan(
        [_emby_source(tmp_path, series, episodes or default_episodes)]
    )
    cache.save()
    return report


def test_passed_ai_answers_are_reused_without_new_requests(tmp_path):
    """通过验证的回答被缓存：输入不变的下一次扫描不再请求 AI，建议照常出现。"""
    cache_path = tmp_path / "ai_cache.json"
    first = _ai_scan(tmp_path, _passing_llm(), cache_path)
    assert first.stats.ai_calls == 2 and first.stats.ai_cached == 0

    llm = _passing_llm()
    second = _ai_scan(tmp_path, llm, cache_path)
    assert llm.prompts == [] and second.stats.ai_calls == 0 and second.stats.ai_cached == 2
    rules = {issue.adopt_kind: issue.adopt_rule for issue in second.issues if issue.type == IssueType.SUGGESTION}
    assert rules == {"mapping": "tmdb:5 S1E3-E4 => S2E1", "identity": "emby:Emby/C => tmdb:7"}


def test_failed_ai_answers_wait_until_retry_date(tmp_path):
    """未通过验证的回答记下原因；到期前不再请求，到期后重新请求一次。"""
    cache_path = tmp_path / "ai_cache.json"
    failing = {
        "NumberingAnswer": NumberingAnswer(
            mappings=[MappingItem(library_season=1, library_start=3, library_end=4, tmdb_season=9, tmdb_start=1)],
            confidence=0.9,
        ),
        "IdentityAnswer": IdentityAnswer(candidate=-1, confidence=0.9),
    }
    _ai_scan(tmp_path, _FakeLlm(failing), cache_path)
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    reasons = sorted(entry["reason"] for entry in saved.values())
    assert not any(entry["passed"] for entry in saved.values())
    assert reasons[0] == "AI 认为候选中没有同一部剧"
    assert "无法对应的集 2 → 2" in reasons[1] and "没有改善" in reasons[1]

    llm = _FakeLlm(failing)
    report = _ai_scan(tmp_path, llm, cache_path, today=TODAY + timedelta(days=FAILED_RETRY_DAYS - 1))
    assert llm.prompts == [] and report.stats.ai_cached == 2

    llm = _FakeLlm(failing)
    _ai_scan(tmp_path, llm, cache_path, today=TODAY + timedelta(days=FAILED_RETRY_DAYS))
    assert len(llm.prompts) == 2


def test_ai_is_asked_again_when_library_numbering_changes(tmp_path):
    """库内无法对应的集号变化后，缓存的回答不再适用，重新请求。"""
    cache_path = tmp_path / "ai_cache.json"
    _ai_scan(tmp_path, _passing_llm(), cache_path)
    _, episodes = _ai_series()
    episodes["E"].append({"Id": "e5", "ParentIndexNumber": 1, "IndexNumber": 5, "Path": "/x/E5.mkv"})
    llm = _passing_llm()
    _ai_scan(tmp_path, llm, cache_path, episodes=episodes)
    assert len(llm.prompts) == 1 and "S01E05" in llm.prompts[0]


def test_unverifiable_and_failed_requests_are_not_cached(tmp_path):
    """请求失败或候选详情暂时查不到时不写缓存，下次扫描重新请求；没用到的旧条目在保存时淘汰。"""
    cache_path = tmp_path / "ai_cache.json"
    cache_path.write_text(json.dumps({"stale": {"answer": {}, "passed": True}}), encoding="utf-8")

    async def broken_factory():
        """模拟模型不可用。"""
        raise RuntimeError("未配置模型")

    series, episodes = _ai_series()
    cache = AiAnswerCache(cache_path)
    _scanner(tmp_path, advisor=AiAdvisor(llm_factory=broken_factory), ai_cache=cache).scan(
        [_emby_source(tmp_path, series, episodes)]
    )
    cache.save()
    assert json.loads(cache_path.read_text(encoding="utf-8")) == {}

    # 候选 0（tmdb:8）在 TMDB 中查不到详情，本轮无法验证，不缓存
    _ai_scan(tmp_path, _FakeLlm({
        "NumberingAnswer": NumberingAnswer(confidence=0.2),
        "IdentityAnswer": IdentityAnswer(candidate=0, confidence=0.9),
    }), cache_path)
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert [entry["reason"] for entry in saved.values()] == ["把握 20%，低于 50%"]


def test_corrupt_ai_cache_starts_empty(tmp_path):
    """缓存文件损坏时从空缓存开始，不影响扫描。"""
    cache_path = tmp_path / "ai_cache.json"
    cache_path.write_text("{bad", encoding="utf-8")
    llm = _passing_llm()
    _ai_scan(tmp_path, llm, cache_path)
    assert len(llm.prompts) == 2


def test_nfo_conflict_note_names_the_library_side_by_origin(tmp_path):
    """NFO 与库内季集号不一致时，本地目录说「库内文件为」，Emby 说「媒体服务器为」。"""
    video = tmp_path / "谷雨 - S01E05.strm"
    video.write_text("http://x", encoding="utf-8")
    (tmp_path / "谷雨 - S01E05.nfo").write_text(
        "<episodedetails><season>1</season><episode>1</episode></episodedetails>", encoding="utf-8"
    )
    nfo = NfoReader(PathMapper(""))
    notes = {}
    for origin in (ORIGIN_LOCAL, ORIGIN_EMBY):
        episode = LibraryEpisode(item_id="e5", season=1, episode=5, path=str(video))
        LibraryScanner._supplement_episode(nfo, episode, None, origin)
        notes[origin] = episode.conflicts
    assert notes[ORIGIN_LOCAL] == ["NFO 记录为 S01E01，库内文件为 S01E05"]
    assert notes[ORIGIN_EMBY] == ["NFO 记录为 S01E01，媒体服务器为 S01E05"]


def test_ai_mappings_touching_only_matched_episodes_are_dropped(tmp_path):
    """AI 顺带改动本来就对得上的集时略去那几条，只按涉及无法对应单集的映射验证与展示。"""
    llm = _FakeLlm({
        "NumberingAnswer": NumberingAnswer(
            mappings=[
                MappingItem(library_season=1, library_start=1, library_end=2, tmdb_season=2, tmdb_start=1),
                MappingItem(library_season=1, library_start=3, library_end=4, tmdb_season=2, tmdb_start=1),
            ],
            confidence=0.9,
        ),
        "IdentityAnswer": IdentityAnswer(candidate=-1, confidence=0.9),
    })
    series, episodes = _ai_series()
    report = _scanner(tmp_path, advisor=_advisor(llm)).scan([_emby_source(tmp_path, series, episodes)])
    mapping = next(issue for issue in report.issues if issue.adopt_kind == "mapping")
    assert mapping.adopt_rule == "tmdb:5 S1E3-E4 => S2E1"
    assert "已略去 AI 另给的 1 条映射：只涉及本来就能对应的集" in mapping.details


def test_cached_failed_answer_is_rechecked_and_restored_when_it_now_passes(tmp_path):
    """缓存中未通过的回答也按当前规则重新核对；现在能通过时恢复展示并改记为通过，不重新请求。"""
    cache_path = tmp_path / "ai_cache.json"
    _ai_scan(tmp_path, _passing_llm(), cache_path)
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    for entry in saved.values():
        entry.update(passed=False, reason="旧规则下未通过")
    cache_path.write_text(json.dumps(saved), encoding="utf-8")

    llm = _passing_llm()
    report = _ai_scan(tmp_path, llm, cache_path)
    assert llm.prompts == []
    assert {issue.adopt_kind for issue in report.issues if issue.type == IssueType.SUGGESTION} == {"mapping", "identity"}
    assert all(entry["passed"] for entry in json.loads(cache_path.read_text(encoding="utf-8")).values())
