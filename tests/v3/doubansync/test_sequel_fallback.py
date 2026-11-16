"""豆瓣续集 → 原剧季回退的纯函数与解析器用例。

用例只使用通用标题与本地桩，不访问网络与宿主服务。
"""

from typing import Any, Dict, List, Optional

import pytest
from app.schemas.types import MediaSource, MediaType

import app.plugins.doubansync as doubansync_module
from app.plugins.doubansync import (
    DoubanSync,
    find_unique_exact_tv,
    parse_sequel_title,
    verify_sequel_season,
)

_RESOLVER = DoubanSync._DoubanSync__resolve_sequel_identity


@pytest.mark.parametrize("media_id", ["0", "-1", True])
def test_invalid_candidate_identity_is_rejected(media_id):
    """非正数及布尔媒体 ID 不能作为可下载身份。"""
    assert find_unique_exact_tv([_candidate(media_id=media_id)], "示例剧集") is None


def test_candidate_source_must_match_exactly():
    """包含 TMDB 文本的其他来源不能冒充 TMDB 候选。"""
    assert find_unique_exact_tv([_candidate(media_source="not-themoviedb")], "示例剧集") is None


@pytest.fixture(autouse=True)
def stub_meta_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离宿主元数据解析：插件仓测试不装配启动阶段的系统配置服务。"""

    class _StubMetaInfo:
        """只保留标题与季号字段的元数据替身。"""

        def __init__(self, title: Any = None, **_: Any) -> None:
            """初始化隔离的测试字段与预设响应。"""
            self.title = str(title or "")
            self.name = self.title
            self.type = None
            self.begin_season = None

    monkeypatch.setattr(doubansync_module, "MetaInfo", _StubMetaInfo)


def _candidate(**overrides: Any) -> Dict[str, Any]:
    """构造一条 TMDB 电视剧候选。"""
    item: Dict[str, Any] = {
        "type": "电视剧",
        "media_source": "themoviedb",
        "media_id": "100",
        "title": "示例剧集",
        "original_name": "示例剧集",
    }
    item.update(overrides)
    return item


def _season(**overrides: Any) -> Dict[str, Any]:
    """构造一份季度详情。"""
    item: Dict[str, Any] = {
        "season_number": 2,
        "air_date": "2025-06-07",
        "episode_count": 10,
    }
    item.update(overrides)
    return item


class _StubChain:
    """记录调用的媒体链桩；不触碰宿主服务。"""

    def __init__(self, candidates: Optional[List[Any]] = None,
                 season_info: Optional[Any] = None,
                 error: Optional[Exception] = None) -> None:
        """初始化隔离的测试字段与预设响应。"""
        self.candidates = candidates
        self.season_info = season_info
        self.error = error
        self.search_calls: List[Dict[str, Any]] = []
        self.season_calls: List[Dict[str, Any]] = []

    def search_medias(self, meta: Any, media_source: Any = None) -> List[Any]:
        """返回预置候选并记录搜索参数。"""
        self.search_calls.append({"meta": meta, "media_source": media_source})
        if self.error:
            raise self.error
        return list(self.candidates or [])

    def tmdb_info(self, tmdbid: int, mtype: Any = None,
                  season: Optional[int] = None) -> Any:
        """返回预置季度详情并记录季查询参数。"""
        self.season_calls.append({"tmdbid": tmdbid, "mtype": mtype, "season": season})
        if self.error:
            raise self.error
        return self.season_info


@pytest.mark.parametrize("title, expected", [
    ("示例剧集2", ("示例剧集", 2)),
    ("示例剧集 12", ("示例剧集", 12)),
    ("Example Show 3", ("Example Show", 3)),
])
def test_parse_sequel_title_accepts_trailing_season_number(
        title: str, expected: tuple) -> None:
    """标题尾部裸数字可解析为原剧标题与季号。"""
    assert parse_sequel_title(title) == expected


def test_parse_sequel_title_prefers_parsed_season() -> None:
    """元数据已解析出季号时，原剧标题取 meta.name。"""
    assert parse_sequel_title("示例剧集 第二季", begin_season=2,
                              base_title="示例剧集") == ("示例剧集", 2)


@pytest.mark.parametrize("title", [
    "示例剧集",          # 非续集
    "1883",              # 纯数字年份标题
    "1923",
    "示例剧集2025",      # 尾部是年份而不是季号
    "示例剧集 第二季",   # 中文季标记不在此处解析
    "示例剧集Ⅱ",         # 罗马数字不做推断
    "剧2",               # 原剧标题过短
    "示例剧集1",         # 季号 1 不是续集
    "示例剧集0",         # 季号 0 为特别篇
    "示例剧集21",        # 超出季号上限
    "",
])
def test_parse_sequel_title_fails_closed(title: str) -> None:
    """无法安全推导时一律返回 None。"""
    assert parse_sequel_title(title) is None


def test_parse_sequel_title_rejects_bad_season_value() -> None:
    """已解析季号不是整数时按失败处理。"""
    assert parse_sequel_title("示例剧集", begin_season="第二季",
                              base_title="示例剧集") is None


def test_find_unique_exact_tv_returns_single_id() -> None:
    """只有一条精确同名电视剧时返回其 TMDB ID。"""
    assert find_unique_exact_tv([_candidate()], "示例剧集") == 100


def test_find_unique_exact_tv_accepts_alias_and_tmdb_id_field() -> None:
    """别名命中且只带 tmdb_id 字段的候选同样可用。"""
    candidate = _candidate(media_id=None, tmdb_id="100",
                           title="Another Title", original_name="Another Title",
                           names=["示例剧集"])
    assert find_unique_exact_tv([candidate], "示例剧集") == 100


def test_find_unique_exact_tv_rejects_ambiguous_candidates() -> None:
    """两条同名候选无法确认唯一性时返回 None。"""
    candidates = [_candidate(media_id="100"), _candidate(media_id="200")]
    assert find_unique_exact_tv(candidates, "示例剧集") is None


@pytest.mark.parametrize("candidate", [
    _candidate(title="示例剧集 第二季", original_name="示例剧集 第二季"),  # 非精确同名
    _candidate(type="电影"),                    # 电影候选
    _candidate(type=None),                      # 类型缺失
    _candidate(media_source="douban"),          # 非 TMDB 来源
    _candidate(media_id="unknown-id"),          # ID 不可解析
])
def test_find_unique_exact_tv_rejects_unusable_candidate(candidate: dict) -> None:
    """候选不满足精确同名或电视剧约束时拒绝。"""
    assert find_unique_exact_tv([candidate], "示例剧集") is None


def test_verify_sequel_season_accepts_matching_year() -> None:
    """季存在、有集数且首播年份相符时通过。"""
    payload = verify_sequel_season(_season(), 2, "2025")
    assert payload == {"season_number": 2, "air_date": "2025-06-07",
                       "episode_count": 10}


@pytest.mark.parametrize("season_info, year", [
    (_season(air_date="2024-06-07"), "2025"),   # 年份不符
    (_season(air_date=None), "2025"),           # 首播日期缺失
    (_season(season_number=3), "2025"),         # 季号不符
    (_season(episode_count=0), "2025"),         # 无集数
    ({}, "2025"),                               # 季不存在
    (None, "2025"),
])
def test_verify_sequel_season_fails_closed(season_info: Any, year: str) -> None:
    """任一季级条件不满足都返回 None。"""
    assert verify_sequel_season(season_info, 2, year) is None


def test_resolver_maps_sequel_to_original_season() -> None:
    """续集条目唯一命中原剧且季年份相符时返回季映射。"""
    chain = _StubChain(candidates=[_candidate()], season_info=_season())
    result = _RESOLVER(chain, "示例剧集2", "2025", MediaType.TV)

    assert result == {"id": 100, "season": 2, "air_date": "2025-06-07",
                      "episode_count": 10}
    assert [call["media_source"] for call in chain.search_calls] == [MediaSource.TMDB]
    assert chain.search_calls[0]["meta"].name == "示例剧集"
    assert chain.season_calls == [
        {"tmdbid": 100, "mtype": MediaType.TV, "season": 2}
    ]


@pytest.mark.parametrize("title", ["示例剧集", "1883", "示例剧集2025"])
def test_resolver_skips_non_sequel_without_remote_calls(title: str) -> None:
    """非续集标题不发起任何远端查询。"""
    chain = _StubChain(candidates=[_candidate()], season_info=_season())
    assert _RESOLVER(chain, title, "2025", MediaType.TV) is None
    assert chain.search_calls == []
    assert chain.season_calls == []


def test_resolver_skips_movie_type() -> None:
    """电影类型不走续集回退。"""
    chain = _StubChain(candidates=[_candidate()], season_info=_season())
    assert _RESOLVER(chain, "示例剧集2", "2025", MediaType.MOVIE) is None
    assert chain.search_calls == []


@pytest.mark.parametrize("year", [None, "", "2025年", "25"])
def test_resolver_skips_unknown_year(year: Any) -> None:
    """豆瓣年份不完整时不尝试回退。"""
    chain = _StubChain(candidates=[_candidate()], season_info=_season())
    assert _RESOLVER(chain, "示例剧集2", year, MediaType.TV) is None
    assert chain.search_calls == []


def test_resolver_rejects_ambiguous_candidate() -> None:
    """同名候选不唯一时放弃，且不再查询季。"""
    chain = _StubChain(candidates=[_candidate(media_id="100"),
                                   _candidate(media_id="200")],
                       season_info=_season())
    assert _RESOLVER(chain, "示例剧集2", "2025", MediaType.TV) is None
    assert chain.season_calls == []


def test_resolver_rejects_year_mismatch() -> None:
    """目标季首播年份与豆瓣年份不符时放弃。"""
    chain = _StubChain(candidates=[_candidate()],
                       season_info=_season(air_date="2024-06-07"))
    assert _RESOLVER(chain, "示例剧集2", "2025", MediaType.TV) is None


def test_resolver_rejects_missing_season() -> None:
    """目标季在 TMDB 不存在时放弃。"""
    chain = _StubChain(candidates=[_candidate()], season_info={})
    assert _RESOLVER(chain, "示例剧集2", "2025", MediaType.TV) is None


def test_resolver_swallows_exception() -> None:
    """远端异常按未命中处理，不向调用方抛出。"""
    chain = _StubChain(error=RuntimeError("boom"))
    assert _RESOLVER(chain, "示例剧集2", "2025", MediaType.TV) is None
