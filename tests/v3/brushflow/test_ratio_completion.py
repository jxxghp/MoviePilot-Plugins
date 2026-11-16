"""分享率删种必须以种子下载完成为前提的回归测试，所有下载器操作均使用替身。"""
import threading
from unittest.mock import MagicMock

import pytest

from app.plugins.brushflow import BrushFlow, BrushTaskConfig


def _make_plugin(**task_fields) -> BrushFlow:
    """构造只含一个任务且已进入任务上下文的最小插件实例。"""
    task = BrushTaskConfig(
        dict(id="ratio-complete", name="分享率测试", site_id=1, downloader="qb", enabled=True, **task_fields)
    )
    plugin = BrushFlow()
    plugin._task_configs = {task.id: task}
    plugin._task_context = threading.local()
    plugin._save_task_data = MagicMock()
    plugin._task_context.task_id = task.id
    return plugin


def _torrent_info(progress: float, ratio: float) -> dict:
    """构造一条只带完成度与分享率的下载器快照，其余删种维度保持未触发。"""
    return dict(
        hash="partial",
        progress=progress,
        total_size=100,
        size=100,
        downloaded=int(100 * progress),
        uploaded=int(100 * progress * ratio),
        ratio=ratio,
        seeding_time=0,
        dltime=60,
        iatime=0,
        avg_upspeed=0,
    )


@pytest.mark.parametrize("hit_and_run", [True, False])
def test_partial_torrent_is_not_deleted_by_ratio(hit_and_run):
    """刚开始下载时 上传/下载 比值即便达标，H&R 与普通种子都不得被分享率条件删除。"""
    plugin = _make_plugin(seed_ratio=1.05, hr_seed_time=21)
    record = dict(title="刚开下", size=100, deleted=False, hit_and_run=hit_and_run, freedate=None)
    deleted, reason = plugin._BrushFlow__evaluate_conditions_for_delete(_torrent_info(0.01, 1.4), record)
    assert deleted is False
    assert "分享率" not in reason


@pytest.mark.parametrize("hit_and_run,expected", [(True, "H&R 分享率达到 1.05"), (False, "分享率达到 1.05")])
def test_completed_torrent_is_still_deleted_by_ratio(hit_and_run, expected):
    """下载完成后分享率达标仍按原有 H&R 与普通路径删除，保持既有行为。"""
    plugin = _make_plugin(seed_ratio=1.05, hr_seed_time=21)
    record = dict(title="已完成", size=100, deleted=False, hit_and_run=hit_and_run, freedate=None)
    deleted, reason = plugin._BrushFlow__evaluate_conditions_for_delete(_torrent_info(1, 1.4), record)
    assert deleted is True
    assert reason == expected
