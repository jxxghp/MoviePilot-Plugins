"""单任务动态删种回归测试，下载器及持久化均使用替身。"""

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.plugins import brushflow
from app.plugins.brushflow import BrushFlow, BrushTaskConfig

GIB = 1024**3
BRUSH_TAG = "刷流-测试"


@pytest.fixture
def runtime(monkeypatch):
    task = BrushTaskConfig(
        {
            "id": "dynamic-delete",
            "name": "测试",
            "site_id": 1,
            "notify": False,
            "downloader": "qb",
            "tag": BRUSH_TAG,
            "proxy_delete": True,
            "delete_size_range": "4-5",
            "delete_except_tags": "辅种",
            "seed_time": 72,
        }
    )
    plugin = object.__new__(BrushFlow)
    plugin._task_configs = {task.id: task}
    plugin._task_context = threading.local()

    downloader = Mock()
    downloader.is_inactive.return_value = False
    downloader.delete_torrents.return_value = True
    service = SimpleNamespace(instance=downloader)
    helper = Mock()
    helper.get_service.return_value = service
    helper.is_downloader.side_effect = lambda name, **kwargs: name == "qbittorrent"
    monkeypatch.setattr(brushflow, "DownloaderHelper", lambda: helper)
    monkeypatch.setattr(plugin, "_validate_task_reference", Mock(return_value=True))
    monkeypatch.setattr(plugin, "_cleanup_unused_task_tag", Mock())
    monkeypatch.setattr(plugin, "_recalculate_statistics", Mock())

    def run(torrents):
        records = {
            torrent["hash"]: {
                "title": torrent["name"],
                "size": torrent["total_size"],
                "deleted": False,
            }
            for torrent in torrents
            if BRUSH_TAG in torrent["tags"].split(",")
        }
        task_data = {"torrents": records, "unmanaged": {}}
        monkeypatch.setattr(plugin, "_get_task_data", lambda _, key: task_data.get(key))
        monkeypatch.setattr(plugin, "_save_task_data", Mock())
        downloader.get_torrents.return_value = (torrents, False)
        report = {}
        with plugin._task_scope(task.id):
            plugin._run_check(task, report)
        return records, report

    return downloader, run


def _torrent(torrent_hash, size, tags=BRUSH_TAG, *, old=False):
    return {
        "hash": torrent_hash,
        "name": torrent_hash,
        "total_size": size * GIB,
        "tags": tags,
        "progress": 1,
        "completion_on": 1 if old else int(time.time()),
    }


@pytest.mark.parametrize("has_conditional_match", [False, True])
def test_empty_fallback_keeps_only_the_existing_plan(runtime, has_conditional_match):
    downloader, run = runtime
    protected = _torrent("protected", 5, f"{BRUSH_TAG},辅种")
    outside = _torrent("outside", 2, "教程", old=True)
    torrents = [protected, outside]
    if has_conditional_match:
        torrents.append(_torrent("conditional", 1, old=True))
    downloader.get_completed_torrents.return_value = [outside]

    records, report = run(torrents)

    downloader.get_completed_torrents.assert_not_called()
    if has_conditional_match:
        downloader.delete_torrents.assert_called_once_with(ids=["conditional"], delete_file=True)
        assert records["conditional"]["deleted"] is True
    else:
        downloader.delete_torrents.assert_not_called()
    assert records["protected"]["deleted"] is False
    assert report["deleted_count"] == int(has_conditional_match)


def test_fallback_ignores_hashes_outside_the_remaining_candidates(runtime):
    downloader, run = runtime
    protected = _torrent("protected", 4, f"{BRUSH_TAG},辅种", old=True)
    outside = _torrent("outside", 2, "教程", old=True)
    eligible = _torrent("eligible", 2)
    downloader.get_completed_torrents.return_value = [outside, protected, eligible]

    records, report = run([protected, outside, eligible])

    downloader.get_completed_torrents.assert_called_once_with(ids=["eligible"])
    downloader.delete_torrents.assert_called_once_with(ids=["eligible"], delete_file=True)
    assert records["protected"]["deleted"] is False
    assert records["eligible"]["deleted"] is True
    assert report["deleted_count"] == 1


def test_failed_fallback_query_keeps_condition_matches(runtime):
    downloader, run = runtime
    conditional = _torrent("conditional", 1, old=True)
    eligible = _torrent("eligible", 5)
    downloader.get_completed_torrents.return_value = None

    records, report = run([conditional, eligible])

    downloader.get_completed_torrents.assert_called_once_with(ids=["eligible"])
    downloader.delete_torrents.assert_called_once_with(ids=["conditional"], delete_file=True)
    assert records["conditional"]["deleted"] is True
    assert records["eligible"]["deleted"] is False
    assert report["deleted_count"] == 1
