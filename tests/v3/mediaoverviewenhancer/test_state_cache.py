"""v1.9.2 状态治理与止损缓存测试：原子落盘、记录裁剪、中文缺失跳过、标题匹配缓存。"""

from __future__ import annotations

import time
from pathlib import Path

import app.plugins.mediaoverviewenhancer.enhancer as enhancer
from app.plugins.mediaoverviewenhancer.enhancer import (
    SOURCE_AI,
    OverviewEnhancer,
    text_signature,
)


class _FakeClient:
    """只实现简介增强用到的 Emby 读取接口。"""

    name = "emby"

    def get_full_dto(self, item_id: str) -> dict:
        return {
            "Id": item_id,
            "Name": "测试影片",
            "Overview": "English overview without Chinese",
            "ProviderIds": {},
        }


def _engine(tmp_path: Path) -> OverviewEnhancer:
    return OverviewEnhancer(config={"enabled": True}, data_dir=tmp_path)


def test_state_save_is_atomic_and_reloadable(tmp_path: Path) -> None:
    """状态写入使用临时文件替换，重新载入后数据完整。"""
    engine = _engine(tmp_path)
    engine._state["records"]["emby|1"] = {"hash": "abc", "time": "2026-10-22 10:00:00"}
    engine._save_state()

    assert engine._state_file.exists()
    assert not engine._state_file.with_name("state.json.tmp").exists()

    reloaded = _engine(tmp_path)
    assert reloaded._state["records"]["emby|1"]["hash"] == "abc"
    assert reloaded._state_dirty is False


def test_corrupt_state_file_is_quarantined(tmp_path: Path) -> None:
    """状态文件损坏时保留副本并回落到空状态，而不是静默覆盖。"""
    (tmp_path / "state.json").write_text("{not-json", encoding="utf-8")

    engine = _engine(tmp_path)

    assert engine._state["records"] == {}
    assert len(list(tmp_path.glob("state.corrupt-*.json"))) == 1


def test_records_are_pruned_by_time(tmp_path: Path) -> None:
    """处理记录超过上限时按时间保留最新部分。"""
    records = {
        f"k{index}": {"time": f"2026-01-01 00:{index % 60:02d}:00"}
        for index in range(enhancer._RECORDS_MAX + 1000)
    }

    pruned = OverviewEnhancer._prune_records(records)

    assert len(pruned) == enhancer._RECORDS_MAX
    assert f"k{len(records) - 1}" in pruned
    assert "k0" not in pruned


def test_untracked_state_is_marked_dirty_and_flushes_throttled(tmp_path: Path) -> None:
    """热点路径先标脏，节流窗口内不重复写盘，强制模式立即写盘。"""
    engine = _engine(tmp_path)
    engine._state["person_images"]["某人"] = "https://example.invalid/p.jpg"
    engine._mark_dirty()
    engine._last_save_at = time.time()

    engine._flush_state()
    assert not engine._state_file.exists()

    engine._flush_state(force=True)
    assert engine._state_file.exists()


def test_untranslated_result_is_skipped_and_cached(tmp_path: Path) -> None:
    """中文缺失不再算失败，而是跳过并写入止损缓存。"""
    engine = _engine(tmp_path)
    engine._client_by_name = lambda name: _FakeClient()
    engine._plan_job = lambda job, allow_llm=True: {
        "action": "write",
        "text": "This overview stays English because translation failed for this item.",
        "source": SOURCE_AI,
    }
    job = {
        "key": "emby|9",
        "kind": "movie",
        "server": "emby",
        "item_id": "9",
        "title": "测试影片",
        "current": "English overview without Chinese",
    }
    engine._run = engine._new_run("manual")

    result = engine._process_job(job)
    engine._record_result(job, result)

    assert result["status"] == "skipped"
    assert result["untranslated"] is True
    assert "emby|9" in engine._state["skipped_untranslated"]
    assert engine.daily_stats()["untranslated"] == 1
    assert engine._run["untranslated"] == 1


def test_untranslated_cache_blocks_candidate_until_text_changes(tmp_path: Path) -> None:
    """已止损的条目在简介未变化时不再进入候选，强制模式仍可处理。"""
    engine = _engine(tmp_path)
    item = {
        "Id": "77",
        "Name": "测试影片",
        "ProductionYear": 2020,
        "Overview": "English overview without Chinese",
        "ProviderIds": {"Tmdb": "12345"},
    }
    engine._state["skipped_untranslated"]["emby|77"] = {
        "sig": text_signature(item["Overview"]),
        "ts": time.time(),
    }

    assert engine._build_movie_jobs(
        _FakeClient(), [item], force=False, require_provider=True
    ) == []
    assert len(
        engine._build_movie_jobs(_FakeClient(), [item], force=True, require_provider=True)
    ) == 1


def test_title_match_cache_caches_positive_and_negative(tmp_path: Path) -> None:
    """TMDB 标题匹配的正负结果都命中缓存，避免每轮重复请求。"""
    engine = _engine(tmp_path)
    calls = {"count": 0}

    def _matcher():
        calls["count"] += 1
        return 456, "匹配片名"

    assert engine._cached_title_match("movie|甲|2020", _matcher) == 456
    assert engine._cached_title_match("movie|甲|2020", _matcher) == 456
    assert calls["count"] == 1

    negative_calls = {"count": 0}

    def _negative():
        negative_calls["count"] += 1
        return None, ""

    assert engine._cached_title_match("movie|乙|2021", _negative) is None
    assert engine._cached_title_match("movie|乙|2021", _negative) is None
    assert negative_calls["count"] == 1


def test_status_exposes_new_diagnostics(tmp_path: Path) -> None:
    """详情页状态需要暴露状态体积、止损条数与最近错误。"""
    engine = _engine(tmp_path)
    engine._state["skipped_untranslated"]["emby|1"] = {"sig": "x", "ts": time.time()}
    engine._save_state()
    engine._log("示例错误", "error")

    status = engine.status()

    assert status["skipped_untranslated"] == 1
    assert status["state_bytes"] > 0
    assert status["state_saved_at"]
    assert status["last_error"] == "示例错误"
    assert status["daily"]["untranslated"] == 0
