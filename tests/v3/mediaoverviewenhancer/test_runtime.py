"""简介增强的宿主调用、媒体库范围与后台任务回归；所有外部边界均为替身。"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage

from app.plugins import mediaoverviewenhancer as plugin_module
from app.plugins.mediaoverviewenhancer import MediaOverviewEnhancer
from app.plugins.mediaoverviewenhancer import enhancer as module
from app.plugins.mediaoverviewenhancer.enhancer import (
    EmbyClient, LLMTextWriter, OverviewEnhancer, run_coroutine,
)


@pytest.fixture
def engine(tmp_path):
    """创建仅使用临时状态目录的启用引擎，并清理后台任务。

    关闭成员数据查询：该功能会访问 MusicBrainz / Wikidata，
    测试环境禁止真实出站网络。
    """
    instance = OverviewEnhancer(
        config={"enabled": True, "mv_member_enabled": False}, data_dir=tmp_path
    )
    yield instance
    instance.stop()


@pytest.fixture
def client():
    """构造不接触真实服务器的 Emby 客户端。"""
    instance = EmbyClient("emby", "http://emby.invalid", "test-key")
    instance._request = Mock()
    return instance


@pytest.mark.parametrize("failure", [False, True])
def test_llm_passes_literal_braces_and_closes_model(monkeypatch, failure):
    """模型直接接收正文消息，元数据花括号保持原样，失败时也释放模型。"""
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="简介：结果正文")))
    if failure:
        llm.ainvoke.side_effect = RuntimeError("model unavailable")
    helper = SimpleNamespace(
        get_llm=AsyncMock(return_value=llm), close_llm=AsyncMock(),
        extract_text_content=lambda content, **_kwargs: content,
    )
    monkeypatch.setattr(module, "LLMHelper", helper)
    result = LLMTextWriter().generate("系统 {规则}", '元数据 {"name": "示例"}')
    assert result == ("" if failure else "结果正文")
    messages = llm.ainvoke.call_args.args[0]
    assert messages[0].content == "系统 {规则}"
    assert messages[1].content == '元数据 {"name": "示例"}'
    helper.close_llm.assert_awaited_once_with(llm)


def test_full_dto_write_preserves_metadata_and_locks(client):
    """写回保留名称、季集号、来源及已有锁，剔除用户播放投影。"""
    original = {
        "Id": "42", "Name": "第七集", "IndexNumber": 7, "ParentIndexNumber": 2,
        "ProviderIds": {"Tmdb": "123"}, "UserData": {"Played": True},
        "LockedFields": ["Name"], "Overview": "旧简介",
    }
    client.get_full_dto = Mock(return_value=deepcopy(original))
    client.get_item_detail = Mock(return_value={"Name": "第七集", "Overview": "新的详细简介"})
    client._request.post_res.return_value = SimpleNamespace(status_code=204)
    assert client.update_overview("42", "新的详细简介") == (True, "")
    payload = client._request.post_res.call_args.kwargs["json"]
    assert payload["Name"] == "第七集"
    assert payload["IndexNumber"] == 7
    assert payload["ParentIndexNumber"] == 2
    assert payload["ProviderIds"] == original["ProviderIds"]
    assert payload["LockedFields"] == ["Name", "Overview"]
    assert "UserData" not in payload


def test_disabling_auto_lock_preserves_existing_overview_lock(client):
    """不新增锁定时也保留用户已有的简介锁。"""
    client.get_full_dto = Mock(return_value={"Id": "42", "Name": "电影", "LockedFields": ["Overview", "Name"]})
    client.get_item_detail = Mock(return_value={"Name": "电影", "Overview": "新的简介"})
    client._request.post_res.return_value = SimpleNamespace(status_code=204)
    assert client.update_overview("42", "新的简介", lock=False)[0]
    assert client._request.post_res.call_args.kwargs["json"]["LockedFields"] == ["Overview", "Name"]


def test_missing_full_dto_never_writes(client):
    """无法读取完整条目时阻止覆盖写入。"""
    client.get_full_dto = Mock(return_value={})
    assert client.update_overview("42", "新的简介")[0] is False
    client._request.post_res.assert_not_called()


@pytest.mark.parametrize("verify", [{"Name": "电影", "Overview": "仍是旧简介"}, {"Overview": "新的简介"}])
def test_write_verification_detects_failure(client, verify):
    """回读发现正文不一致或名称丢失时，不报告写入成功。"""
    client.get_full_dto = Mock(return_value={"Id": "42", "Name": "电影"})
    client.get_item_detail = Mock(return_value=verify)
    client._request.post_res.return_value = SimpleNamespace(status_code=204)
    assert client.update_overview("42", "新的简介")[0] is False


def test_title_search_carries_parent_id(client):
    """Emby 标题查询必须携带用户选定的媒体库 ID。"""
    client._get = Mock(return_value={"Items": []})
    client.search_items("标题", parent="library-id")
    assert client._get.call_args.args[1]["ParentId"] == "library-id"


def test_title_collection_stays_in_selected_library(engine, client):
    """指定标题仍受媒体库约束，且无来源标识时不按模糊首条结果改写。"""
    engine.update_config({"enabled": True, "libraries": ["电影库"], "episode_enabled": False})
    engine._resolve_clients = Mock(return_value=([client], []))
    client.resolve_library_ids = Mock(return_value=["movies"])
    client.search_items = Mock(return_value=[{"Id": "42", "Name": "标题", "Overview": ""}])
    engine._tmdb = Mock()
    jobs, errors, _ = engine._collect_jobs(title="标题")
    assert jobs == []
    assert errors == []
    client.search_items.assert_called_once_with("标题", "Movie", parent="movies")
    engine._tmdb.search_movie_id.assert_not_called()


def test_unmatched_library_never_falls_back_to_global_title_search(engine, client):
    """配置库不存在时给出错误，不能转为全服务器搜索。"""
    engine.update_config({"enabled": True, "libraries": ["不存在的库"]})
    engine._resolve_clients = Mock(return_value=([client], []))
    client.resolve_library_ids = Mock(return_value=[])
    client.search_items = Mock()
    jobs, errors, _ = engine._collect_jobs(title="标题")
    assert not jobs and errors
    client.search_items.assert_not_called()


@pytest.mark.parametrize("limit", [9999, "9999", -1, "invalid"])
def test_request_limit_cannot_exceed_configured_maximum(engine, client, limit):
    """API 请求不能突破配置中的单次处理上限，异常值安全回退。"""
    engine.update_config({"enabled": True, "max_items_per_run": 2, "episode_enabled": False})
    engine._resolve_clients = Mock(return_value=([client], []))
    client.resolve_library_ids = Mock(return_value=["movies"])
    client.iter_items = Mock(return_value=[])
    engine._build_movie_jobs = Mock(return_value=[{"Id": str(i)} for i in range(10)])
    jobs, _, _ = engine._collect_jobs(limit=limit)
    assert 1 <= len(jobs) <= 2


def test_preview_calls_neither_llm_nor_emby_write(engine):
    """MV 试跑只生成方案，不调用模型也不写回。"""
    engine._collect_jobs = Mock(return_value=([{"kind": "mv", "title": "艺人 - 歌曲"}], [], {}))
    engine._llm = Mock()
    engine._client_by_name = Mock()
    result = engine.preview({"media_type": "mv"})
    assert result["items"][0]["source"] == "ai"
    engine._llm.generate.assert_not_called()
    engine._client_by_name.assert_not_called()


def test_movie_expand_respects_translation_switch(engine):
    """电影扩写关闭翻译与缺失生成后，不应调用模型翻译英文。"""
    engine.update_config({"enabled": True, "translate_foreign": False, "ai_generate_when_missing": False})
    engine._tmdb = Mock()
    engine._tmdb.movie_detail.side_effect = [{"overview": ""}, {"overview": "English overview " * 10}]
    engine._llm = Mock()
    plan = engine._movie_plan({"tmdb_id": 1, "title": "电影"})
    assert plan["action"] == "skip"
    engine._llm.generate.assert_not_called()


def test_cancel_during_generation_prevents_write(engine, client):
    """生成期间收到取消时，在写回边界重新检查取消状态。"""
    engine._client_by_name = Mock(return_value=client)

    def generate(_job):
        """模拟耗时生成中收到取消。"""
        engine._cancel.set()
        return {"action": "write", "text": "这是一段长度充足的新简介，用来验证取消后的写入保护"}

    engine._plan_job = generate
    client.update_overview = Mock()
    assert engine._process_job({"server": "emby", "item_id": "42"})["status"] == "skipped"
    client.update_overview.assert_not_called()


def test_reinitialize_stops_previous_engine_before_replacement(tmp_path, monkeypatch):
    """重复初始化时先停止旧引擎，避免遗留线程继续处理。"""
    plugin = object.__new__(MediaOverviewEnhancer)
    old = Mock()
    plugin._engine = old
    plugin.get_data_path = Mock(return_value=tmp_path)
    replacement = Mock()

    def create(**_kwargs):
        """新引擎只在旧引擎停止后创建。"""
        old.stop.assert_called_once()
        return replacement

    monkeypatch.setattr(plugin_module, "OverviewEnhancer", create)
    plugin.init_plugin({"enabled": True})
    assert plugin.engine is replacement


def test_stopped_engine_rejects_runs_and_transfer_events(engine):
    """停止后的旧引擎不能被 API 或迟到事件重新启动。"""
    engine.stop()
    assert engine.start_run()["started"] is False
    assert engine.queue_transfer("标题")["queued"] is False


def test_delayed_queue_uses_full_configured_delay(engine, monkeypatch):
    """入库延迟大于五分钟时仍完整等待，且只创建一个队列线程。"""
    engine.update_config({"enabled": True, "post_transfer_delay": 900})
    worker = Mock()
    worker.is_alive.return_value = True
    thread_factory = Mock(return_value=worker)
    monkeypatch.setattr(module.threading, "Thread", thread_factory)
    monkeypatch.setattr(module.time, "monotonic", lambda: 100)
    assert engine.queue_transfer("电影一")["queued"]
    assert engine.queue_transfer("电影二")["queued"]
    assert [entry["ready_at"] for entry in engine._pending] == [1000, 1000]
    thread_factory.assert_called_once()


def test_pending_queue_keeps_events_while_busy(engine, monkeypatch):
    """已有批任务时不丢弃入库事件，空闲后才启动。"""
    engine._pending = [{"title": "电影", "ready_at": 0}]
    engine._thread = Mock()
    engine._thread.is_alive.side_effect = [True, False]
    engine.start_run = Mock(return_value={"started": True})
    monkeypatch.setattr(engine._stop_pending, "wait", Mock(side_effect=[False, False, True]))
    engine._pending_loop()
    engine.start_run.assert_called_once()
    assert engine._pending == []


def test_stopped_worker_cannot_overwrite_replacement_state(engine):
    """卸载后迟到的生成结果不再覆盖新引擎状态或发送通知。"""
    engine.stop()
    engine._save_state = Mock()
    engine._notify = Mock()
    engine._finish_run("迟到结果", {})
    engine._save_state.assert_not_called()
    engine._notify.assert_not_called()


def test_coroutine_bridge_inside_event_loop():
    """同步入口已处于事件循环时，通过独立线程执行协程。"""
    async def value():
        """返回可观察的异步结果。"""
        return "结果"

    async def caller():
        """模拟异步宿主调用同步生成桥。"""
        return run_coroutine(value())

    assert run_coroutine(caller()) == "结果"


def test_explicit_home_video_library_can_supply_mvs(client):
    """显式选择的家庭视频库可用于 MV，整库影视扫描仍排除它。"""
    client.list_libraries = Mock(return_value=[
        {"Name": "mv", "CollectionType": "homevideos", "ItemId": "mv-id"},
        {"Name": "电影", "CollectionType": "movies", "ItemId": "movie-id"},
    ])
    assert client.resolve_library_ids(["mv"]) == ["mv-id"]
    assert client.resolve_library_ids([]) == ["movie-id"]


def test_mv_collection_includes_music_video_and_respects_title(engine, client):
    """MV 显式扫描兼容音乐视频类型，并遵循指定标题。"""
    engine._resolve_clients = Mock(return_value=([client], []))
    client.resolve_library_ids = Mock(return_value=["mv-id"])
    client.iter_items = Mock(return_value=[
        {"Id": "1", "Type": "MusicVideo", "Name": "艺人 - 歌曲"},
        {"Id": "2", "Type": "Video", "Name": "其他曲目"},
    ])
    jobs, _, stats = engine._collect_jobs(media_type="mv", title="歌曲")
    assert [job["item_id"] for job in jobs] == ["1"]
    assert stats["mv"] == 1
    assert client.iter_items.call_args.args[0] == "Movie,MusicVideo,Video"


def test_old_engine_cannot_save_over_new_state(engine):
    """旧引擎停止后，迟到的普通保存不能覆盖其他引擎的状态文件。"""
    engine.stop()
    engine._state_file.write_text('{"records": {"new": {}}}', encoding="utf-8")
    engine._save_state()
    assert engine._state_file.read_text(encoding="utf-8") == '{"records": {"new": {}}}'


def test_concurrent_start_creates_one_worker(engine, monkeypatch):
    """API 并发启动时，只保留一个运行线程。"""
    from concurrent.futures import ThreadPoolExecutor

    worker = Mock()
    worker.is_alive.return_value = True
    # 替换插件的模块绑定，避免改动线程池共享的 threading 模块。
    with ThreadPoolExecutor(max_workers=2) as pool:
        factory = Mock(return_value=worker)
        monkeypatch.setattr(module, "threading", SimpleNamespace(
            Thread=factory, current_thread=module.threading.current_thread
        ))
        results = list(pool.map(lambda _i: engine.start_run(), range(2)))
    assert sum(result["started"] for result in results) == 1
    factory.assert_called_once()
