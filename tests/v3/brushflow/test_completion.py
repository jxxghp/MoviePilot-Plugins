"""文件完成度独立于传输流量的回归测试，所有下载器操作均使用替身。"""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.plugins.brushflow import BrushFlow, BrushTaskConfig


@pytest.fixture
def runtime():
    """构造启用超时与促销删除的单任务插件及 qB 快照。"""
    task = BrushTaskConfig(dict(id="completion", name="测试", site_id=1, downloader="qb",
                                enabled=True, download_time=1, del_no_free=True, proxy_delete=True))
    plugin = BrushFlow()
    plugin._task_configs = {task.id: task}
    plugin._task_context = threading.local()
    plugin._save_task_data = MagicMock()
    torrent = dict(hash="reuse", name="复用文件", total_size=100, size=100,
                   downloaded=0, uploaded=12, progress=1, amount_left=0,
                   state="stalledUP", added_on=1, completion_on=2, tags="刷流")
    record = dict(title="复用文件", size=101, downloaded=0, deleted=False,
                  freedate="2020-01-01 00:00:00")
    plugin._get_task_data = MagicMock(return_value={"reuse": record})
    downloader = MagicMock()
    downloader.is_inactive.return_value = False
    downloader.get_torrents.return_value = ([torrent], False)
    helper = MagicMock()
    helper.is_downloader.return_value = True
    helper.get_service.return_value = SimpleNamespace(instance=downloader)
    with patch(f"{BrushFlow.__module__}.DownloaderHelper", return_value=helper):
        with plugin._task_scope(task.id):
            yield plugin, task, torrent, record


@pytest.mark.parametrize("progress,downloaded,complete", [(1, 0, True), (.5, 200, False), (.9999, 0, False)])
def test_real_progress_controls_refresh_and_delete_rules(runtime, progress, downloaded, complete):
    """完成的零流量种子受保护，未完成的高流量种子仍受超时及促销规则约束。"""
    plugin, _, torrent, record = runtime
    torrent.update(progress=progress, downloaded=downloaded)
    info = plugin._BrushFlow__get_torrent_info(torrent)
    assert info["downloaded"] == downloaded
    assert info["progress"] == progress
    plugin._BrushFlow__update_torrent_tasks_state([torrent], {"reuse": record})
    assert record["progress"] == progress
    assert record["downloaded"] == downloaded
    assert plugin._torrent_complete(record) is complete
    assert plugin._BrushFlow__promotion_expired(info, record)[0] is (not complete)
    assert plugin._BrushFlow__evaluate_conditions_for_delete(info, record)[0] is (not complete)
    plugin._BrushFlow__send_delete_message = MagicMock()
    expected = [] if complete else ["reuse"]
    assert plugin._BrushFlow__delete_torrent_for_evaluate_proxy_pre_conditions([torrent], {"reuse": record}) == expected
    # 隔离促销，独立验证下载超时。
    record["freedate"] = None
    assert plugin._BrushFlow__evaluate_conditions_for_delete(info, record)[0] is (not complete)


def test_global_dynamic_candidates_use_real_completion(runtime):
    """全局动态删种正确识别已完成的零流量种子，且不误标超时或促销到期。"""
    plugin, _, _, record = runtime
    candidates, total_size, _, _ = plugin._collect_global_dynamic_delete_candidates()
    assert total_size == 100
    assert len(candidates) == 1
    assert candidates[0]["completed"] is True
    assert candidates[0]["pre_delete_reason"] == ""
    assert candidates[0]["conditional_reason"] == ""
    assert record["downloaded"] == 0


def test_completed_torrent_does_not_schedule_promotion_expiry(runtime):
    """刷新后的零流量已完成记录无需注册促销到期检查。"""
    plugin, task, _, record = runtime
    record.update(progress=1, freedate="2099-01-01 00:00:00")
    assert plugin._next_promotion_expiry(task) is None
    record["progress"] = .5
    assert plugin._next_promotion_expiry(task) is not None


@pytest.mark.parametrize("row,expected", [({"size": 100, "downloaded": 100}, True),
                                         ({"size": 100, "downloaded": 50}, False),
                                         ({"size": 0, "downloaded": 0}, False)])
def test_legacy_record_completion_fallback(row, expected):
    """尚未刷新且缺少实际进度的旧记录保留兼容行为。"""
    assert BrushFlow._torrent_complete(row) is expected


def test_transmission_progress_and_counters_are_independent():
    """Transmission 完成度从百分比归一化，流量使用累计计数而非文件大小。"""
    plugin = BrushFlow()
    torrent = SimpleNamespace(hashString="tr", name="复用", total_size=100,
                              progress=100, ratio=2, downloaded_ever=0, uploaded_ever=7)
    helper = MagicMock()
    helper.is_downloader.return_value = False
    with patch(f"{BrushFlow.__module__}.DownloaderHelper", return_value=helper), patch.object(
        BrushFlow, "service_info", new_callable=PropertyMock, return_value=MagicMock()
    ):
        info = plugin._BrushFlow__get_torrent_info(torrent)
    assert info["progress"] == 1
    assert info["downloaded"] == 0
    assert info["uploaded"] == 7
    assert plugin._torrent_complete(info) is True
