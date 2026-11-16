"""整剧 / 整季任务收集与分集标题生成的无网络测试。"""

from __future__ import annotations

from typing import Any, Dict, List

from app.plugins.mediaoverviewenhancer.enhancer import (
    EPISODE,
    SEASON,
    SERIES,
    OverviewEnhancer,
)


class FakeClient:
    """只提供任务收集所需接口的假媒体服务器客户端。"""

    name = "fake"

    def __init__(self, items: Dict[str, Dict[str, Any]] | None = None) -> None:
        """保存按 ID 索引的条目。"""
        self.items = items or {}

    def get_items_by_ids(self, ids: List[str], fields: str = "") -> Dict[str, Dict[str, Any]]:
        """按 ID 返回已知条目，模拟 Emby 批量读取。"""
        return {key: self.items[key] for key in ids if key in self.items}


def _series(overview: str = "一句话简介", tmdb: str = "300146") -> Dict[str, Any]:
    """构造一个剧集条目。"""
    return {
        "Id": "s1",
        "Name": "嫁金钗",
        "ProductionYear": 2026,
        "Overview": overview,
        "ProviderIds": {"Tmdb": tmdb},
        "Path": "/media/电视剧/嫁金钗 (2026)",
    }


def _season(overview: str = "") -> Dict[str, Any]:
    """构造一个季条目。"""
    return {
        "Id": "sea1",
        "Name": "第 1 季",
        "SeriesId": "s1",
        "IndexNumber": 1,
        "Overview": overview,
        "Path": "/media/电视剧/嫁金钗 (2026)/Season 1",
        "ChildCount": 30,
    }


def test_build_series_job(tmp_path) -> None:
    """TMDB 标识存在时应生成整剧任务，并带上条目路径。"""
    engine = OverviewEnhancer(
        config={"series_enabled": True, "series_min_chars": 120}, data_dir=tmp_path
    )
    client = FakeClient()
    jobs = engine._build_series_jobs(client, [_series("短简介")], False)
    assert len(jobs) == 1
    assert jobs[0]["kind"] == SERIES
    assert jobs[0]["tmdb_id"] == 300146
    assert jobs[0]["reason"] == "short"
    assert jobs[0]["path"].endswith("嫁金钗 (2026)")
    engine.stop()


def test_build_series_job_skips_placeholder_filter(tmp_path) -> None:
    """开启「仅占位简介」时，已有正常简介的条目不进入任务清单。"""
    engine = OverviewEnhancer(
        config={"series_enabled": True, "scan_placeholder_only": True}, data_dir=tmp_path
    )
    client = FakeClient()
    assert engine._build_series_jobs(client, [_series("已有完整简介内容")], False) == []
    jobs = engine._build_series_jobs(client, [_series("")], False)
    assert len(jobs) == 1
    engine.stop()


def test_build_season_job(tmp_path) -> None:
    """季任务应解析所属剧集并保留集数信息。"""
    engine = OverviewEnhancer(
        config={"season_enabled": True, "series_min_chars": 120}, data_dir=tmp_path
    )
    client = FakeClient({"s1": _series()})
    jobs = engine._build_season_jobs(client, [_season("")], None, False)
    assert len(jobs) == 1
    assert jobs[0]["kind"] == SEASON
    assert jobs[0]["season"] == 1
    assert jobs[0]["title"] == "嫁金钗"
    assert jobs[0]["tmdb_id"] == 300146
    assert jobs[0]["episode_count"] == 30
    engine.stop()


def test_build_season_job_skips_specials(tmp_path) -> None:
    """第 0 季（特别篇）不生成季简介任务。"""
    engine = OverviewEnhancer(config={"season_enabled": True}, data_dir=tmp_path)
    special = dict(_season(""))
    special["IndexNumber"] = 0
    client = FakeClient({"s1": _series()})
    assert engine._build_season_jobs(client, [special], None, False) == []
    engine.stop()


class FakeLLM:
    """返回固定文案的假大模型。"""

    @staticmethod
    def available() -> bool:
        """始终可用。"""
        return True

    @staticmethod
    def generate(system_prompt: str, user_prompt: str, retries: int = 0) -> str:
        """返回带标点的标题，用于验证清洗逻辑。"""
        return "《雨夜的证词》。"


def test_plan_episode_title_only_for_placeholder(tmp_path) -> None:
    """「仅占位标题」模式下，已有语义标题不应被改写。"""
    engine = OverviewEnhancer(
        config={"episode_title_enabled": True, "episode_title_mode": "numeric_only"},
        data_dir=tmp_path,
    )
    engine._llm = FakeLLM()
    job = {"kind": EPISODE, "title": "嫁金钗", "season": 1, "episode": 3,
           "episode_title": "雨夜的证词", "tmdb_id": 300146, "current": "已有简介"}
    assert engine._plan_episode_title(job) == ""
    engine.stop()


def test_plan_episode_title_generates_and_caches(tmp_path) -> None:
    """占位标题应生成干净短标题，并写入状态缓存。"""
    engine = OverviewEnhancer(
        config={"episode_title_enabled": True, "episode_title_max_chars": 12},
        data_dir=tmp_path,
    )
    engine._llm = FakeLLM()
    job = {"kind": EPISODE, "title": "嫁金钗", "season": 1, "episode": 3,
           "episode_title": "第 3 集", "tmdb_id": 300146, "current": "该集简介"}
    title = engine._plan_episode_title(job)
    assert title == "雨夜的证词"
    cached = engine._state.get("episode_titles", {}).get("300146|1|3")
    assert cached and cached["title"] == "雨夜的证词"
    # 第二次命中缓存，不再调用大模型
    engine._llm = None
    assert engine._plan_episode_title(job) == "雨夜的证词"
    engine.stop()
