"""BrushFlow V5 多任务配置、调度和联邦宿主契约测试。"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from brushflow import BrushFlow, BrushTaskConfig
from brushflow.models import BrushFlowSettingsPayload, BrushTaskPayload


def _make_task(task_id: str, site_id: int = 1, name: str = "任务") -> BrushTaskConfig:
    """创建字段完整且适合独立单元测试的刷流任务。"""
    return BrushTaskConfig(
        {
            "id": task_id,
            "name": name,
            "site_id": site_id,
            "downloader": "主下载器",
            "enabled": True,
        }
    )


def _make_runtime_plugin(*tasks: BrushTaskConfig) -> BrushFlow:
    """创建不访问真实配置、数据库或下载器的运行时插件实例。"""
    plugin = BrushFlow()
    plugin._enabled = True
    plugin._show_sidebar_nav = True
    plugin._global_disksize = None
    plugin._global_maxdlcount = None
    plugin._global_maxupspeed = None
    plugin._global_maxdlspeed = None
    plugin._task_context = threading.local()
    plugin._task_configs = {task.id: task for task in tasks}
    plugin._task_locks = {task.id: threading.Lock() for task in tasks}
    plugin._runtime_lock = threading.Lock()
    plugin._runtime = {
        task.id: {"state": "idle", "operation": None, "last_error": None}
        for task in tasks
    }
    return plugin


def test_vue_render_api_and_sidebar_contract():
    """插件应暴露 Vue 入口、Bearer API 与整理分组侧栏菜单。"""
    plugin = _make_runtime_plugin(_make_task("task-a"))

    assert plugin.get_render_mode() == ("vue", "dist/assets")
    assert plugin.get_sidebar_nav() == [
        {
            "nav_key": "main",
            "title": "站点刷流",
            "icon": "mdi-sync",
            "section": "organize",
            "permission": "manage",
            "order": 45,
        }
    ]
    api_rows = plugin.get_api()
    assert {row["path"] for row in api_rows} == {
        "/status",
        "/settings",
        "/tasks",
        "/tasks/{task_id}",
        "/tasks/{task_id}/state",
        "/tasks/{task_id}/run",
        "/tasks/{task_id}/check",
        "/tasks/{task_id}/clear",
    }
    assert all(row["auth"] == "bear" for row in api_rows)


def test_services_are_registered_per_task():
    """每个启用任务应获得唯一的刷新和检查服务及独立参数。"""
    first = _make_task("task-a", site_id=1, name="A 站")
    second = _make_task("task-b", site_id=2, name="B 站")
    plugin = _make_runtime_plugin(first, second)

    services = plugin.get_service()

    assert len(services) == 4
    assert len({service["id"] for service in services}) == 4
    assert {service["func_kwargs"]["task_id"] for service in services} == {"task-a", "task-b"}


def test_site_ratio_control_requires_target():
    """开启站点分享率控制但未设置目标时，请求模型应拒绝保存。"""
    with pytest.raises(ValueError, match="目标分享率"):
        BrushTaskPayload(
            name="A 站",
            site_id=1,
            downloader="主下载器",
            site_ratio_control=True,
        )


def test_site_ratio_control_blocks_at_target_and_keeps_task_enabled():
    """站点分享率达到目标时应暂停新增种子，但不能关闭任务调度。"""
    task = BrushTaskConfig(
        {
            **_make_task("task-a").to_dict(),
            "site_ratio_control": True,
            "site_ratio_target": 2.5,
        }
    )
    plugin = _make_runtime_plugin(task)
    plugin._get_task_data = MagicMock(return_value={})
    site = SimpleNamespace(id=1, name="A 站", domain="tracker.example.com", public=False)
    user_data = SimpleNamespace(
        domain="example.com",
        ratio=2.5,
        upload=250,
        download=100,
        updated_day="2026-08-02",
        updated_time="12:00:00",
    )

    with patch("brushflow.SiteOper") as site_oper:
        site_oper.return_value.get.return_value = site
        site_oper.return_value.get_userdata_latest.return_value = [user_data]
        passed, reason, status = plugin._evaluate_site_ratio_control(task, site=site)
        summary = plugin._task_summary(task.id)

    assert passed is False
    assert "已达到目标" in reason
    assert status["current"] == 2.5
    assert status["reached"] is True
    assert task.enabled is True
    assert summary["state"] == "waiting_ratio"
    assert len(plugin.get_service()) == 2


def test_site_ratio_control_allows_brushing_below_target():
    """站点分享率低于目标时应允许任务继续新增种子。"""
    task = BrushTaskConfig(
        {
            **_make_task("task-a").to_dict(),
            "site_ratio_control": True,
            "site_ratio_target": 3,
        }
    )
    plugin = _make_runtime_plugin(task)
    site = SimpleNamespace(id=1, name="A 站", domain="example.com", public=False)
    user_data = SimpleNamespace(
        domain="example.com",
        ratio=2.99,
        upload=299,
        download=100,
        updated_day="2026-08-02",
        updated_time="12:00:00",
    )

    with patch("brushflow.SiteOper") as site_oper:
        site_oper.return_value.get.return_value = site
        site_oper.return_value.get_userdata_latest.return_value = [user_data]
        passed, reason, status = plugin._evaluate_site_ratio_control(task, site=site)

    assert passed is True
    assert reason is None
    assert status["current"] == 2.99
    assert status["reached"] is False


def test_site_ratio_control_waits_when_statistics_are_unavailable():
    """显式启用控制但无站点统计时应等待数据，避免无法判断时继续刷流。"""
    task = BrushTaskConfig(
        {
            **_make_task("task-a").to_dict(),
            "site_ratio_control": True,
            "site_ratio_target": 2,
        }
    )
    plugin = _make_runtime_plugin(task)
    site = SimpleNamespace(id=1, name="A 站", domain="example.com", public=False)

    with patch("brushflow.SiteOper") as site_oper:
        site_oper.return_value.get.return_value = site
        site_oper.return_value.get_userdata_latest.return_value = []
        passed, reason, status = plugin._evaluate_site_ratio_control(task, site=site)

    assert passed is False
    assert "等待数据更新" in reason
    assert status["available"] is False


def test_cleanup_unused_task_tag_removes_orphan_qb_tag():
    """任务标签不再被任何种子使用时，应删除 qBittorrent 全局标签定义。"""
    task = _make_task("task-a")
    plugin = _make_runtime_plugin(task)
    downloader = MagicMock()
    downloader.get_torrents.return_value = ([{"tags": "已整理,刷流"}], False)
    downloader.delete_torrents_tag.return_value = True
    service = SimpleNamespace(name="主下载器", type="qbittorrent", instance=downloader)
    helper = MagicMock()
    helper.get_service.return_value = service
    helper.is_downloader.return_value = True

    with patch("brushflow.DownloaderHelper", return_value=helper):
        plugin._cleanup_unused_task_tag(task)

    downloader.delete_torrents_tag.assert_called_once_with(ids=None, tag=task.brush_tag)


def test_cleanup_unused_task_tag_keeps_tag_used_by_torrent():
    """仍绑定种子的任务标签不能被清理。"""
    task = _make_task("task-a")
    plugin = _make_runtime_plugin(task)
    downloader = MagicMock()
    downloader.get_torrents.return_value = ([{"tags": f"刷流,{task.brush_tag}"}], False)
    service = SimpleNamespace(name="主下载器", type="qbittorrent", instance=downloader)
    helper = MagicMock()
    helper.get_service.return_value = service
    helper.is_downloader.return_value = True

    with patch("brushflow.DownloaderHelper", return_value=helper):
        plugin._cleanup_unused_task_tag(task)

    downloader.delete_torrents_tag.assert_not_called()


def test_cleanup_unused_task_tags_removes_historical_orphans():
    """启动扫描应只删除历史遗留且未使用的刷流唯一标签。"""
    plugin = _make_runtime_plugin(_make_task("task-a"))
    downloader = MagicMock()
    downloader.qbc.torrents_tags.return_value = ["刷流-deadbeef", "刷流-live123", "其他标签"]
    downloader.get_torrents.return_value = ([{"tags": "刷流-live123"}], False)
    downloader.delete_torrents_tag.return_value = True
    service = SimpleNamespace(name="主下载器", type="qbittorrent", instance=downloader)
    helper = MagicMock()
    helper.get_configs.return_value = {"主下载器": SimpleNamespace(name="主下载器")}
    helper.get_service.return_value = service
    helper.is_downloader.return_value = True

    with patch("brushflow.DownloaderHelper", return_value=helper):
        plugin._cleanup_unused_task_tags()

    downloader.delete_torrents_tag.assert_called_once_with(ids=None, tag=["刷流-deadbeef"])


def test_legacy_config_migrates_timezone_and_site_overrides():
    """旧版全局分钟时区应还原为小时，站点覆盖值应保持小时语义。"""
    plugin = BrushFlow()
    sites = {
        1: SimpleNamespace(id=1, name="A 站", public=False),
        2: SimpleNamespace(id=2, name="B 站", public=False),
    }
    config = {
        "brushsites": [1, 2],
        "downloader": "主下载器",
        "timezone_offset": 480,
        "enable_site_config": True,
        "site_config": '[{"sitename": "B 站", "timezone_offset": -5, "rss_support": true}]',
    }

    with patch("brushflow.SiteOper") as site_oper:
        site_oper.return_value.get.side_effect = sites.get
        tasks = plugin._migrate_legacy_config(config)

    by_name = {task["name"]: task for task in tasks}
    assert by_name["A 站"]["timezone_offset"] == 8
    assert by_name["B 站"]["timezone_offset"] == -5
    assert by_name["B 站"]["rss_support"] is True


def test_legacy_global_limits_are_restored_during_initial_upgrade():
    """从 V4 直升时应把原有运行限额恢复为跨任务全局限额。"""
    plugin = BrushFlow()
    plugin.update_config = MagicMock()
    plugin._migrate_legacy_data = MagicMock()
    site = SimpleNamespace(id=1, name="A 站", public=False)
    config = {
        "brushsites": [1],
        "downloader": "主下载器",
        "disksize": 500,
        "maxdlcount": 4,
        "maxupspeed": 1024,
        "maxdlspeed": 2048,
    }

    with patch("brushflow.SiteOper") as site_oper, patch("brushflow.DownloaderHelper") as downloader_helper:
        site_oper.return_value.get.return_value = site
        downloader_helper.return_value.get_configs.return_value = {
            "主下载器": SimpleNamespace(name="主下载器")
        }
        plugin.init_plugin(config)

    assert plugin._global_disksize == 500
    assert plugin._global_maxdlcount == 4
    assert plugin._global_maxupspeed == 1024
    assert plugin._global_maxdlspeed == 2048
    saved_config = plugin.update_config.call_args.args[0]
    assert saved_config["global_disksize"] == 500


def test_payloads_treat_legacy_zero_limits_as_unset():
    """历史配置用 0 表示不限时，任务和全局设置接口都不应返回 422。"""
    task_payload = BrushTaskPayload.model_validate(
        {
            "name": "A 站",
            "site_id": 1,
            "downloader": "主下载器",
            "disksize": 0,
            "maxupspeed": "0",
            "maxdlspeed": 0.0,
            "maxdlcount": 0,
            "seed_ratio": 0,
        }
    )
    settings_payload = BrushFlowSettingsPayload.model_validate(
        {
            "global_disksize": 0,
            "global_maxdlcount": "0",
            "global_maxupspeed": 0.0,
            "global_maxdlspeed": 0,
        }
    )

    assert task_payload.disksize is None
    assert task_payload.maxupspeed is None
    assert task_payload.maxdlspeed is None
    assert task_payload.maxdlcount is None
    assert task_payload.seed_ratio is None
    assert settings_payload.global_disksize is None
    assert settings_payload.global_maxdlcount is None
    assert settings_payload.global_maxupspeed is None
    assert settings_payload.global_maxdlspeed is None


def test_global_limits_aggregate_all_tasks():
    """全局体积和下载并发应阻止任一任务继续突破合计上限。"""
    first = _make_task("task-a")
    second = _make_task("task-b", site_id=2)
    plugin = _make_runtime_plugin(first, second)
    plugin._global_disksize = 100
    plugin._global_maxdlcount = 3
    gib = 1024 ** 3
    task_rows = {
        first.id: {"first": {"size": 40 * gib, "deleted": False}},
        second.id: {"second": {"size": 50 * gib, "deleted": False}},
    }
    plugin._get_task_data = MagicMock(side_effect=lambda task_id, _name: task_rows[task_id])
    plugin._BrushFlow__get_global_downloading_count = MagicMock(return_value=3)

    global_size = plugin._calculate_global_seeding_size()
    with plugin._task_scope(first.id):
        size_passed, size_reason = plugin._BrushFlow__evaluate_size_condition_for_brush(
            40 * gib,
            20 * gib,
            global_torrents_size=global_size,
        )
        count_passed, count_reason = plugin._BrushFlow__evaluate_pre_conditions_for_brush(
            include_network_conditions=False
        )

    assert global_size == 90 * gib
    assert size_passed is False
    assert "全局保种上限" in size_reason
    assert count_passed is False
    assert "全局同时下载任务数" in count_reason


def test_reference_validation_uses_configured_downloader_when_offline():
    """下载器临时离线时只要配置仍存在，就不应自动停用任务。"""
    plugin = BrushFlow()
    task = _make_task("task-a")
    site = SimpleNamespace(id=1, name="A 站", public=False)
    helper = MagicMock()
    helper.get_configs.return_value = {"主下载器": SimpleNamespace(name="主下载器")}
    helper.get_service.return_value = None

    with patch("brushflow.SiteOper") as site_oper, patch("brushflow.DownloaderHelper", return_value=helper):
        site_oper.return_value.get.return_value = site
        assert plugin._validate_task_reference(task) is True


def test_manual_operation_queue_is_atomic():
    """同一任务重复提交手动刷新时只能有一个操作进入线程池。"""
    task = _make_task("task-a")
    plugin = _make_runtime_plugin(task)
    plugin._task_summary = MagicMock(return_value={"id": task.id})
    thread_helper = MagicMock()

    with patch("brushflow.ThreadHelper", return_value=thread_helper):
        first = plugin.run_task(task.id)
        second = plugin.run_task(task.id)

    assert first.success is True
    assert second.success is False
    thread_helper.submit.assert_called_once_with(plugin.brush, task.id)


def test_run_report_is_saved_as_plain_json_data():
    """运行诊断中的 Counter 应在持久化前转换成普通字典。"""
    task = _make_task("task-a")
    plugin = _make_runtime_plugin(task)
    plugin._get_task_data = MagicMock(return_value=[])
    plugin._save_task_data = MagicMock()
    report = plugin._new_run_report("brush")
    report["reason_counts"]["重复种子"] += 2

    plugin._append_run(task.id, report)

    saved_history = plugin._save_task_data.call_args.args[2]
    assert saved_history[0]["reason_counts"] == {"重复种子": 2}
    assert type(saved_history[0]["reason_counts"]) is dict
