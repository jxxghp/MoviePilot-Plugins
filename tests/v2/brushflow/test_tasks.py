"""BrushFlow V5 多任务配置、调度和联邦宿主契约测试。"""

import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

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
    plugin._global_proxy_delete = False
    plugin._global_delete_size_range = None
    plugin._global_delete_lock = threading.Lock()
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


def test_promotion_expiry_service_uses_nearest_incomplete_torrent():
    """启用促销到期删除后，应按最近一项未完成下载注册一次性检查。"""
    task = BrushTaskConfig({**_make_task("task-a").to_dict(), "del_no_free": True})
    plugin = _make_runtime_plugin(task)
    timezone = ZoneInfo("Asia/Shanghai")
    now = datetime.now(timezone)
    nearest = now + timedelta(minutes=10)
    later = now + timedelta(minutes=20)
    plugin._get_task_data = MagicMock(
        return_value={
            "nearest": {
                "freedate": nearest.strftime("%Y-%m-%d %H:%M:%S"),
                "size": 100,
                "downloaded": 50,
                "deleted": False,
            },
            "later": {
                "freedate": later.strftime("%Y-%m-%d %H:%M:%S"),
                "size": 100,
                "downloaded": 0,
                "deleted": False,
            },
            "completed": {
                "freedate": (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
                "size": 100,
                "downloaded": 100,
                "deleted": False,
            },
        }
    )

    services = plugin.get_service()

    expiry_service = next(service for service in services if service["id"].endswith("PromotionExpiry"))
    assert expiry_service["trigger"] == "date"
    assert expiry_service["kwargs"]["run_date"] == nearest.replace(microsecond=0)
    assert expiry_service["func_kwargs"] == {"task_id": task.id}


def test_promotion_expiry_applies_site_timezone_offset():
    """站点截止时间应加上本机与站点的时差后再进行到期判断。"""
    expiry = BrushFlow._promotion_expiry_at("2026-08-04T12:00:00Z", 8)

    assert expiry == datetime(2026, 8, 4, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_promotion_expiry_callback_waits_and_rebuilds_schedule():
    """促销到期回调应等待任务空闲，并在检查完成后安排下一截止时间。"""
    task = _make_task("task-a")
    plugin = _make_runtime_plugin(task)
    plugin.check = MagicMock()
    plugin._refresh_scheduler = MagicMock()

    plugin._check_promotion_expiry(task.id)

    plugin.check.assert_called_once_with(task.id, wait_for_lock=True)
    plugin._refresh_scheduler.assert_called_once_with()


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
    downloader.qbc.torrents_delete_tags.return_value = None
    service = SimpleNamespace(name="主下载器", type="qbittorrent", instance=downloader)
    helper = MagicMock()
    helper.get_service.return_value = service
    helper.is_downloader.return_value = True

    with patch("brushflow.DownloaderHelper", return_value=helper):
        plugin._cleanup_unused_task_tag(task)

    downloader.qbc.torrents_delete_tags.assert_called_once_with(tags=task.brush_tag)
    downloader.delete_torrents_tag.assert_not_called()


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
    downloader.qbc.torrents_delete_tags.return_value = None
    service = SimpleNamespace(name="主下载器", type="qbittorrent", instance=downloader)
    helper = MagicMock()
    helper.get_configs.return_value = {"主下载器": SimpleNamespace(name="主下载器")}
    helper.get_service.return_value = service
    helper.is_downloader.return_value = True

    with patch("brushflow.DownloaderHelper", return_value=helper):
        plugin._cleanup_unused_task_tags()

    downloader.qbc.torrents_delete_tags.assert_called_once_with(tags=["刷流-deadbeef"])
    downloader.delete_torrents_tag.assert_not_called()


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
    """从 V4 直升时应恢复跨任务全局限额和全局动态删种。"""
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
        "proxy_delete": True,
        "delete_size_range": "50-100",
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
    assert plugin._global_proxy_delete is True
    assert plugin._global_delete_size_range == "50-100"
    saved_config = plugin.update_config.call_args.args[0]
    assert saved_config["global_disksize"] == 500
    assert saved_config["global_proxy_delete"] is True
    assert saved_config["global_delete_size_range"] == "50-100"


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
            "global_proxy_delete": False,
            "global_delete_size_range": "",
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
    assert settings_payload.global_proxy_delete is False
    assert settings_payload.global_delete_size_range is None


def test_global_dynamic_delete_requires_valid_range():
    """全局动态删种必须配置正数单值或下限小于上限的区间。"""
    with pytest.raises(ValueError, match="必须设置动态删种阈值"):
        BrushFlowSettingsPayload(global_proxy_delete=True)
    with pytest.raises(ValueError, match="下限必须小于上限"):
        BrushFlowSettingsPayload(
            global_proxy_delete=True,
            global_delete_size_range="100-50",
        )


def test_invalid_persisted_global_dynamic_delete_is_disabled():
    """持久化或迁移得到的零阈值不得在初始化后启用破坏性全局删种。"""
    plugin = BrushFlow()
    plugin.update_config = MagicMock()
    plugin._migrate_legacy_data = MagicMock()

    plugin.init_plugin(
        {
            "enabled": False,
            "tasks": [],
            "global_proxy_delete": True,
            "global_delete_size_range": "0",
        }
    )

    assert plugin._global_proxy_delete is False
    assert plugin._global_delete_size_range is None
    saved_config = plugin.update_config.call_args.args[0]
    assert saved_config["global_proxy_delete"] is False
    assert saved_config["global_delete_size_range"] is None


def test_disabled_global_dynamic_delete_ignores_invalid_hidden_range():
    """关闭全局动态删种时应清理隐藏的非法阈值并允许保存设置。"""
    payload = BrushFlowSettingsPayload(
        global_proxy_delete=False,
        global_delete_size_range="invalid",
    )

    assert payload.global_proxy_delete is False
    assert payload.global_delete_size_range is None


def test_global_dynamic_delete_plan_restores_v4_priority():
    """全局计划应依次执行预删、普通条件、托管条件和最长做种兜底。"""
    gib = 1024 ** 3
    unmanaged = _make_task("unmanaged")
    managed = BrushTaskConfig({**_make_task("managed").to_dict(), "proxy_delete": True})
    candidates = [
        {
            "task": managed,
            "torrent_hash": "pre",
            "downloader_name": "主下载器",
            "size": 10 * gib,
            "pre_delete_reason": "下载耗时达到 1 小时",
            "conditional_reason": "",
            "proxy_delete": True,
            "completed": False,
            "hit_and_run": False,
            "seeding_time": 0,
        },
        {
            "task": unmanaged,
            "torrent_hash": "unmanaged-condition",
            "downloader_name": "主下载器",
            "size": 20 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "分享率达到 2",
            "proxy_delete": False,
            "completed": True,
            "hit_and_run": False,
            "seeding_time": 10,
        },
        {
            "task": managed,
            "torrent_hash": "managed-condition",
            "downloader_name": "主下载器",
            "size": 30 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "做种时间达到 10 小时",
            "proxy_delete": True,
            "completed": True,
            "hit_and_run": False,
            "seeding_time": 20,
        },
        {
            "task": managed,
            "torrent_hash": "oldest",
            "downloader_name": "主下载器",
            "size": 40 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "",
            "proxy_delete": True,
            "completed": True,
            "hit_and_run": False,
            "seeding_time": 200,
        },
        {
            "task": managed,
            "torrent_hash": "hr-protected",
            "downloader_name": "主下载器",
            "size": 40 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "",
            "proxy_delete": True,
            "completed": True,
            "hit_and_run": True,
            "seeding_time": 300,
        },
    ]

    selected, remaining_size, triggered = BrushFlow._select_global_dynamic_deletions(
        candidates,
        total_size=150 * gib,
        min_size=50 * gib,
        max_size=100 * gib,
    )

    assert triggered is True
    assert [entry["torrent_hash"] for entry in selected] == [
        "pre",
        "unmanaged-condition",
        "managed-condition",
        "oldest",
    ]
    assert remaining_size == 50 * gib


@pytest.mark.parametrize("proxy_delete", [False, True])
def test_global_dynamic_delete_condition_stages_stop_at_lower_bound(proxy_delete):
    """托管与非托管普通条件阶段均应在达到区间下限后停止选择。"""
    gib = 1024 ** 3
    task = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": proxy_delete})
    candidates = [
        {
            "task": task,
            "torrent_hash": f"hash-{index}",
            "downloader_name": task.downloader,
            "size": 10 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "做种时间达到 10 小时",
            "proxy_delete": proxy_delete,
            "completed": True,
            "hit_and_run": False,
            "seeding_time": index,
        }
        for index in range(3)
    ]

    selected, remaining_size, triggered = BrushFlow._select_global_dynamic_deletions(
        candidates,
        total_size=120 * gib,
        min_size=100 * gib,
        max_size=110 * gib,
    )

    assert triggered is True
    assert [entry["torrent_hash"] for entry in selected] == ["hash-0", "hash-1"]
    assert remaining_size == 100 * gib


def test_global_dynamic_delete_preserves_each_tasks_delete_reason():
    """共享种子应在删除计划中保留每个关联任务各自满足的条件原因。"""
    first = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    second = BrushTaskConfig(
        {**_make_task("task-b", site_id=2).to_dict(), "proxy_delete": True}
    )
    candidate = {
        "task": first,
        "torrent_hash": "shared-hash",
        "downloader_name": first.downloader,
        "size": 20,
        "pre_delete_reason": "",
        "conditional_reason": "做种时间达到 10 小时",
        "proxy_delete": True,
        "completed": True,
        "hit_and_run": False,
        "seeding_time": 100,
        "associated_records": [(first, {}), (second, {})],
        "task_condition_reasons": {
            first.id: {"conditional_reason": "做种时间达到 10 小时"},
            second.id: {"conditional_reason": "分享率达到 2"},
        },
    }

    selected, _, triggered = BrushFlow._select_global_dynamic_deletions(
        [candidate],
        total_size=120,
        min_size=100,
        max_size=110,
    )

    assert triggered is True
    assert selected[0]["task_delete_reasons"] == {
        first.id: "触发全局动态删除阈值，做种时间达到 10 小时",
        second.id: "触发全局动态删除阈值，分享率达到 2",
    }


def test_global_dynamic_delete_preconditions_run_below_threshold():
    """未达到全局上限时仍应执行非 H&R 促销过期或下载超时预删。"""
    task = BrushTaskConfig({**_make_task("managed").to_dict(), "proxy_delete": True})
    candidate = {
        "task": task,
        "torrent_hash": "timeout",
        "downloader_name": "主下载器",
        "size": 10,
        "pre_delete_reason": "下载耗时达到 1 小时",
        "conditional_reason": "",
        "proxy_delete": True,
        "completed": False,
        "hit_and_run": False,
        "seeding_time": 0,
    }

    selected, remaining_size, triggered = BrushFlow._select_global_dynamic_deletions(
        [candidate],
        total_size=50,
        min_size=100,
        max_size=100,
    )

    assert [entry["torrent_hash"] for entry in selected] == ["timeout"]
    assert remaining_size == 40
    assert triggered is False


def test_global_dynamic_delete_batches_multiple_downloaders():
    """跨任务计划应按下载器分别批量删除并回写各任务记录。"""
    gib = 1024 ** 3
    first = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    second = BrushTaskConfig(
        {**_make_task("task-b", site_id=2).to_dict(), "proxy_delete": True, "downloader": "备用下载器"}
    )
    plugin = _make_runtime_plugin(first, second)
    plugin._global_proxy_delete = True
    plugin._global_delete_size_range = "50-100"
    plugin.post_message = MagicMock()
    first_record = {"title": "A", "deleted": False}
    second_record = {"title": "B", "deleted": False}
    candidates = [
        {
            "task": first,
            "torrent_hash": "hash-a",
            "torrent_task": first_record,
            "downloader_name": first.downloader,
            "size": 40 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "",
            "proxy_delete": True,
            "completed": True,
            "hit_and_run": False,
            "seeding_time": 200,
        },
        {
            "task": second,
            "torrent_hash": "hash-b",
            "torrent_task": second_record,
            "downloader_name": second.downloader,
            "size": 40 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "",
            "proxy_delete": True,
            "completed": True,
            "hit_and_run": False,
            "seeding_time": 100,
        },
    ]
    first_downloader = MagicMock()
    first_downloader.delete_torrents.return_value = True
    second_downloader = MagicMock()
    second_downloader.delete_torrents.return_value = True
    services = {
        first.downloader: SimpleNamespace(instance=first_downloader),
        second.downloader: SimpleNamespace(instance=second_downloader),
    }
    plugin._collect_global_dynamic_delete_candidates = MagicMock(
        return_value=(
            candidates,
            120 * gib,
            {first.id: {"hash-a": first_record}, second.id: {"hash-b": second_record}},
            services,
        )
    )
    plugin._save_task_data = MagicMock()
    plugin._recalculate_statistics = MagicMock()
    downloader_helper = MagicMock()
    downloader_helper.is_downloader.return_value = False

    with patch("brushflow.DownloaderHelper", return_value=downloader_helper):
        deleted_count = plugin._run_global_dynamic_delete()

    assert deleted_count == 2
    first_downloader.delete_torrents.assert_called_once_with(ids=["hash-a"], delete_file=True)
    second_downloader.delete_torrents.assert_called_once_with(ids=["hash-b"], delete_file=True)
    assert first_record["deleted"] is True
    assert second_record["deleted"] is True
    assert plugin._recalculate_statistics.call_count == 2


def test_global_dynamic_delete_does_not_mark_failed_downloader_deletion():
    """下载器拒绝批量删除时不得把计划中的种子标记为已删除。"""
    gib = 1024 ** 3
    task = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    plugin = _make_runtime_plugin(task)
    plugin._global_proxy_delete = True
    plugin._global_delete_size_range = "50-100"
    record = {"title": "A", "deleted": False}
    candidate = {
        "task": task,
        "torrent_hash": "hash-a",
        "torrent_task": record,
        "downloader_name": task.downloader,
        "size": 80 * gib,
        "pre_delete_reason": "",
        "conditional_reason": "",
        "proxy_delete": True,
        "completed": True,
        "hit_and_run": False,
        "seeding_time": 200,
    }
    downloader = MagicMock()
    downloader.delete_torrents.return_value = False
    plugin._collect_global_dynamic_delete_candidates = MagicMock(
        return_value=(
            [candidate],
            120 * gib,
            {task.id: {"hash-a": record}},
            {task.downloader: SimpleNamespace(instance=downloader)},
        )
    )
    plugin._save_task_data = MagicMock()
    plugin._recalculate_statistics = MagicMock()
    downloader_helper = MagicMock()
    downloader_helper.is_downloader.return_value = False

    with patch("brushflow.DownloaderHelper", return_value=downloader_helper):
        deleted_count = plugin._run_global_dynamic_delete()

    assert deleted_count == 0
    assert record["deleted"] is False
    plugin._save_task_data.assert_not_called()
    plugin._recalculate_statistics.assert_not_called()


def test_global_dynamic_delete_aborts_when_downloader_snapshot_is_unavailable():
    """任一启用下载器缺少实时快照时不得用陈旧记录触发全局删种。"""
    task = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    plugin = _make_runtime_plugin(task)
    plugin._get_task_data = MagicMock(return_value={"stale": {"size": 200 * 1024 ** 3}})
    downloader_helper = MagicMock()
    downloader_helper.get_service.return_value = None

    with patch("brushflow.DownloaderHelper", return_value=downloader_helper):
        with pytest.raises(RuntimeError, match="实时状态.*本轮已中止"):
            plugin._collect_global_dynamic_delete_candidates()


def test_global_dynamic_delete_deduplicates_physical_torrents_and_tracks_all_records():
    """同一下载器 Hash 应只计量一次，同时保留全部关联任务记录用于回写。"""
    gib = 1024 ** 3
    first = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    second = _make_task("task-b", site_id=2)
    plugin = _make_runtime_plugin(first, second)
    records = {
        first.id: {"shared-hash": {"title": "A", "size": 60 * gib, "deleted": False}},
        second.id: {"shared-hash": {"title": "B", "size": 60 * gib, "deleted": False}},
    }
    plugin._get_task_data = MagicMock(
        side_effect=lambda task_id, data_name: records[task_id] if data_name == "torrents" else {}
    )
    plugin._save_task_data = MagicMock()
    torrent = {
        "hash": "shared-hash",
        "name": "共享种子",
        "total_size": 60 * gib,
        "downloaded": 60 * gib,
        "tags": "刷流",
    }
    downloader = MagicMock()
    downloader.is_inactive.return_value = False
    downloader.get_torrents.return_value = ([torrent], False)
    service = SimpleNamespace(instance=downloader)
    downloader_helper = MagicMock()
    downloader_helper.get_service.return_value = service
    downloader_helper.is_downloader.return_value = True

    with patch("brushflow.DownloaderHelper", return_value=downloader_helper):
        candidates, total_size, _, _ = plugin._collect_global_dynamic_delete_candidates()

    assert total_size == 60 * gib
    assert len(candidates) == 1
    assert candidates[0]["proxy_delete"] is False
    assert {task.id for task, _ in candidates[0]["associated_records"]} == {first.id, second.id}

    second.enabled = False
    with patch("brushflow.DownloaderHelper", return_value=downloader_helper):
        protected_candidates, protected_total_size, _, _ = (
            plugin._collect_global_dynamic_delete_candidates()
        )

    assert protected_total_size == 60 * gib
    assert protected_candidates == []


def test_global_dynamic_delete_updates_all_records_for_deduplicated_torrent():
    """物理种子删除成功后应把同 Hash 的全部关联任务记录标记为已删除。"""
    gib = 1024 ** 3
    first = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    second = BrushTaskConfig(
        {**_make_task("task-b", site_id=2).to_dict(), "proxy_delete": True}
    )
    plugin = _make_runtime_plugin(first, second)
    plugin._global_proxy_delete = True
    plugin._global_delete_size_range = "50-100"
    plugin.post_message = MagicMock()
    first_record = {"title": "A", "deleted": False}
    second_record = {"title": "B", "deleted": False}
    candidate = {
        "task": first,
        "torrent_hash": "shared-hash",
        "torrent_task": first_record,
        "downloader_name": first.downloader,
        "size": 80 * gib,
        "pre_delete_reason": "",
        "conditional_reason": "",
        "proxy_delete": True,
        "completed": True,
        "hit_and_run": False,
        "seeding_time": 200,
        "associated_records": [(first, first_record), (second, second_record)],
    }
    downloader = MagicMock()
    downloader.delete_torrents.return_value = True
    plugin._collect_global_dynamic_delete_candidates = MagicMock(
        return_value=(
            [candidate],
            120 * gib,
            {
                first.id: {"shared-hash": first_record},
                second.id: {"shared-hash": second_record},
            },
            {first.downloader: SimpleNamespace(instance=downloader)},
        )
    )
    plugin._save_task_data = MagicMock()
    plugin._recalculate_statistics = MagicMock()
    downloader_helper = MagicMock()
    downloader_helper.is_downloader.return_value = False

    with patch("brushflow.DownloaderHelper", return_value=downloader_helper):
        deleted_count = plugin._run_global_dynamic_delete()

    assert deleted_count == 1
    assert first_record["deleted"] is True
    assert second_record["deleted"] is True
    assert plugin._save_task_data.call_count == 2
    assert plugin._recalculate_statistics.call_count == 2


def test_global_dynamic_delete_writes_back_success_before_later_batch_exception():
    """后续下载器抛出异常时应保留并回写此前已经成功删除的批次。"""
    gib = 1024 ** 3
    first = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    second = BrushTaskConfig(
        {**_make_task("task-b", site_id=2).to_dict(), "proxy_delete": True, "downloader": "备用下载器"}
    )
    plugin = _make_runtime_plugin(first, second)
    plugin._global_proxy_delete = True
    plugin._global_delete_size_range = "50-100"
    plugin.post_message = MagicMock()
    first_record = {"title": "A", "deleted": False}
    second_record = {"title": "B", "deleted": False}

    def candidate(task, torrent_hash, record, seeding_time):
        """构造跨下载器异常回写测试所需的全局候选。"""
        return {
            "task": task,
            "torrent_hash": torrent_hash,
            "torrent_task": record,
            "downloader_name": task.downloader,
            "size": 40 * gib,
            "pre_delete_reason": "",
            "conditional_reason": "",
            "proxy_delete": True,
            "completed": True,
            "hit_and_run": False,
            "seeding_time": seeding_time,
        }

    first_downloader = MagicMock()
    first_downloader.delete_torrents.return_value = True
    second_downloader = MagicMock()
    second_downloader.delete_torrents.side_effect = RuntimeError("downloader failed")
    plugin._collect_global_dynamic_delete_candidates = MagicMock(
        return_value=(
            [
                candidate(first, "hash-a", first_record, 200),
                candidate(second, "hash-b", second_record, 100),
            ],
            120 * gib,
            {first.id: {"hash-a": first_record}, second.id: {"hash-b": second_record}},
            {
                first.downloader: SimpleNamespace(instance=first_downloader),
                second.downloader: SimpleNamespace(instance=second_downloader),
            },
        )
    )
    plugin._save_task_data = MagicMock()
    plugin._recalculate_statistics = MagicMock()
    downloader_helper = MagicMock()
    downloader_helper.is_downloader.return_value = False

    with patch("brushflow.DownloaderHelper", return_value=downloader_helper):
        deleted_count = plugin._run_global_dynamic_delete()

    assert deleted_count == 1
    assert first_record["deleted"] is True
    assert second_record["deleted"] is False
    plugin._save_task_data.assert_called_once_with(
        first.id,
        "torrents",
        {"hash-a": first_record},
    )
    plugin._recalculate_statistics.assert_called_once_with(first.id)


def test_disabling_global_dynamic_delete_restores_consistent_task_modes():
    """关闭全局模式时仅保留具备独立阈值的任务级动态删种。"""
    participant = BrushTaskConfig({**_make_task("task-a").to_dict(), "proxy_delete": True})
    standalone = BrushTaskConfig(
        {
            **_make_task("task-b", site_id=2).to_dict(),
            "proxy_delete": True,
            "delete_size_range": "50-100",
        }
    )
    plugin = _make_runtime_plugin(participant, standalone)
    plugin._global_proxy_delete = True
    plugin._global_delete_size_range = "50-100"
    plugin._save_config = MagicMock()
    plugin._refresh_scheduler = MagicMock()
    plugin._build_status_data = MagicMock(return_value={})

    plugin.update_settings(BrushFlowSettingsPayload(global_proxy_delete=False))

    assert participant.proxy_delete is False
    assert standalone.proxy_delete is True
    plugin._save_config.assert_called_once_with()


def test_task_check_runs_global_delete_after_releasing_task_lock():
    """任务状态同步完成后应先释放任务锁，再进入跨任务动态删种。"""
    task = _make_task("task-a")
    plugin = _make_runtime_plugin(task)
    plugin._global_proxy_delete = True
    plugin._global_delete_size_range = "50-100"
    plugin._run_check = MagicMock(side_effect=lambda _task, report: report.update({"result": "completed"}))
    plugin._append_run = MagicMock()

    def run_global_delete():
        """断言跨任务处理开始前当前任务锁已经释放。"""
        assert plugin._task_locks[task.id].locked() is False
        return 2

    plugin._run_global_dynamic_delete = MagicMock(side_effect=run_global_delete)

    plugin.check(task.id)

    saved_report = plugin._append_run.call_args.args[1]
    assert saved_report["success"] is True
    assert saved_report["global_deleted_count"] == 2
    assert saved_report["deleted_count"] == 2
    assert plugin._runtime[task.id]["state"] == "idle"


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
