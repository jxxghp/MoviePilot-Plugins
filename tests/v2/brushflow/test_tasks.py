"""BrushFlow V5 多任务配置、调度和联邦宿主契约测试。"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from brushflow import BrushFlow, BrushTaskConfig


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
