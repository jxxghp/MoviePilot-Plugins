"""「仅补分集标题」模式的单元测试（不联网、不写媒体服务器）。"""

from __future__ import annotations

from typing import Any, Dict, List

from app.plugins.mediaoverviewenhancer.enhancer import EPISODE, OverviewEnhancer


class FakeTitleClient:
    """提供标题写入所需接口的假客户端。"""

    name = "fake"

    def __init__(self) -> None:
        """记录写入的字段与是否动过简介。"""
        self.fields: List[Dict[str, Any]] = []
        self.overview_writes = 0

    def get_items_by_ids(self, ids: List[str], fields: str = "") -> Dict[str, Dict[str, Any]]:
        """返回剧集条目，带 TMDB 标识。"""
        return {
            "s1": {
                "Id": "s1",
                "Name": "嫁金钗",
                "ProductionYear": 2026,
                "ProviderIds": {"Tmdb": "300146"},
            }
            for _ in ids
        }

    def get_full_dto(self, item_id: str) -> Dict[str, Any]:
        """返回最小可用 DTO。"""
        return {"Id": item_id, "Name": "第 5 集", "Overview": "旧简介", "LockedFields": []}

    def update_fields(self, item_id: str, fields: Dict[str, Any], dto: Any = None):
        """记录字段写入并返回成功。"""
        self.fields.append(fields)
        return True, ""

    def update_overview(self, *args: Any, **kwargs: Any):
        """本模式不应调用简介写入。"""
        self.overview_writes += 1
        return True, ""


def _episode(ep: int, title: str, season: int = 1) -> Dict[str, Any]:
    """构造一个分集条目。"""
    return {
        "Id": f"e{ep}",
        "SeriesId": "s1",
        "SeriesName": "嫁金钗",
        "ParentIndexNumber": season,
        "IndexNumber": ep,
        "Name": title,
        "Overview": "该集围绕一封信件展开，调查转向城南旧仓库。",
        "Path": f"/media/嫁金钗/S01E{ep:02d}.mkv",
    }


def test_build_title_jobs_only_placeholder(tmp_path) -> None:
    """只收集占位标题，且有语义标题的分集与特别篇都被跳过。"""
    engine = OverviewEnhancer(
        config={"episode_enabled": True, "episode_title_enabled": True}, data_dir=tmp_path
    )
    client = FakeTitleClient()
    jobs = engine._build_title_jobs(
        client,
        [
            _episode(1, "贵门恶女手扇情敌"),
            _episode(2, "第 2 集"),
            _episode(0, "第 0 集", season=0),
        ],
    )
    assert [job["episode"] for job in jobs] == [2]
    job = jobs[0]
    assert job["title_only"] is True
    assert job["reason"] == "title"
    assert job["tmdb_id"] == 300146
    assert job["title"] == "嫁金钗"
    engine.stop()


def test_build_title_jobs_all_mode_keeps_existing(tmp_path) -> None:
    """「全部重写」模式下已有语义标题也进入任务。"""
    engine = OverviewEnhancer(
        config={
            "episode_enabled": True,
            "episode_title_enabled": True,
            "episode_title_mode": "all",
        },
        data_dir=tmp_path,
    )
    client = FakeTitleClient()
    jobs = engine._build_title_jobs(client, [_episode(1, "贵门恶女手扇情敌")])
    assert len(jobs) == 1
    engine.stop()


def test_apply_title_only_writes_name_only(tmp_path, monkeypatch) -> None:
    """标题模式只写 Name（与 NFO），绝不调用简介写入。"""
    engine = OverviewEnhancer(
        config={
            "episode_enabled": True,
            "episode_title_enabled": True,
            "episode_title_max_chars": 14,
            "lock_overview": True,
        },
        data_dir=tmp_path,
    )
    monkeypatch.setattr(engine, "_plan_episode_title", lambda job, allow_llm=True: "密信藏拙露破绽")
    client = FakeTitleClient()
    job = {
        "key": "fake|e5",
        "kind": EPISODE,
        "server": "fake",
        "item_id": "e5",
        "title": "嫁金钗",
        "season": 1,
        "episode": 5,
        "episode_title": "第 5 集",
        "tmdb_id": 300146,
        "current": "旧简介",
        "title_only": True,
    }
    result = engine._apply_title_only(job, client)
    assert result["status"] == "updated"
    assert result["source"] == "title"
    assert client.fields == [{"Name": "密信藏拙露破绽"}]
    assert client.overview_writes == 0
    engine.stop()


def test_apply_title_only_skips_when_no_title(tmp_path, monkeypatch) -> None:
    """没有可生成标题（已有语义标题或失败）时计为跳过。"""
    engine = OverviewEnhancer(
        config={"episode_enabled": True, "episode_title_enabled": True}, data_dir=tmp_path
    )
    monkeypatch.setattr(engine, "_plan_episode_title", lambda job, allow_llm=True: "")
    client = FakeTitleClient()
    result = engine._apply_title_only(
        {"key": "fake|e1", "kind": EPISODE, "item_id": "e1", "title": "嫁金钗", "season": 1,
         "episode": 1, "episode_title": "第 1 集"},
        client,
    )
    assert result["status"] == "skipped"
    assert client.fields == []
    engine.stop()
