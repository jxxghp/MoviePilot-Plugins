"""STRM 补全插件的文件写入、宿主事件和停止边界回归。"""

import copy
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins.strmnfo import StrmNfo
from app.plugins.strmnfo.nfo import generate_nfo_for_strm, parse_filename
from app.sdk.plugin import _PluginBase


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    """构造实例独立、存储隔离且不启动宿主服务的插件。"""
    monkeypatch.setattr(_PluginBase, "__init__", lambda self: None)
    instance = StrmNfo()
    instance._enabled = True
    instance._watch_paths = str(tmp_path)
    instance._exclude_paths = ""
    instance._force = False
    instance._notify = False
    instance._max_per_run = 2
    data = {}

    def save(key, value):
        """模拟宿主持久化时复制数据的行为。"""
        data[key] = copy.deepcopy(value)

    instance.get_data = lambda key: copy.deepcopy(data.get(key))
    instance.save_data = save
    instance.post_message = Mock()
    yield instance
    instance.stop_service()


def make_strm(path: Path) -> Path:
    """创建本地 STRM，文件内容只指向无须访问的占位地址。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("https://example.invalid/media.mkv", encoding="utf-8")
    return path


def test_generate_sidecar_preserves_strm_and_existing_nfo(tmp_path):
    """技术标签写入独立 sidecar，重复执行保留已有文件。"""
    path = make_strm(tmp_path / "Show.S01E01.2160p.HEVC.DV.P5.60fps.DDP5.1.strm")
    original = path.read_bytes()
    status, _ = generate_nfo_for_strm(path)
    assert status == "generated"
    nfo = path.with_suffix(".strm.nfo")
    root = ET.fromstring(nfo.read_text())
    assert root.tag == "episodedetails"
    assert root.findtext("fileinfo/streamdetails/video/width") == "3840"
    assert root.findtext("fileinfo/streamdetails/video/framerate") == "60.0"
    assert root.findtext("fileinfo/streamdetails/audio/channels") == "6"
    nfo.write_text("keep", encoding="utf-8")
    assert generate_nfo_for_strm(path)[0] == "skipped"
    assert nfo.read_text() == "keep" and path.read_bytes() == original
    assert generate_nfo_for_strm(path, force=True)[0] == "generated"
    assert not list(tmp_path.glob("*.tmp"))


def test_audio_tracks_and_dolby_vision_are_not_conflated():
    """多条音轨分别保留编码和声道，杜比视界优先于 HDR。"""
    info = parse_filename("Film.2160p.DV.HDR.TrueHD7.1.Atmos.AC3.5.1")
    assert info["hdr"] == "dolbyvision"
    assert [(t["codec"], t["channels"]) for t in info["audio_tracks"]] == [("truehd", 8), ("ac3", 6)]


@pytest.mark.parametrize("name", ["Film.strm", "Film.1080p.mkv", "Missing.1080p.strm"])
def test_unparsed_or_missing_sources_do_not_create_sidecars(tmp_path, name):
    """无技术标签、非 STRM 和不存在的源文件均不生成输出。"""
    path = tmp_path / name
    if not name.startswith("Missing"):
        path.write_text("placeholder")
    assert generate_nfo_for_strm(path)[0] in {"unparsed", "error"}
    assert not path.with_suffix(".strm.nfo").exists()


def test_symlink_uses_target_filename_and_writes_beside_link(tmp_path):
    """库内链接保留原位，技术信息可从源文件名补全。"""
    source = make_strm(tmp_path / "source" / "Film.1080p.HEVC.strm")
    link = tmp_path / "Film.strm"
    link.symlink_to(source)
    assert generate_nfo_for_strm(link)[0] == "generated"
    assert link.with_suffix(".strm.nfo").is_file()
    assert not source.with_suffix(".strm.nfo").exists()


def test_event_fileitem_path_is_not_joined_twice():
    """宿主 FileItem.path 已是完整路径，与目标清单合并时正确去重。"""
    target = SimpleNamespace(path="/media/Film.1080p.strm", name="Film.1080p.strm")
    transfer = SimpleNamespace(file_list_new=[target.path], target_item=target)
    assert StrmNfo._extract_strm_paths({"transferinfo": transfer}) == [target.path]


def test_batch_respects_monitor_exclusions_dedup_and_global_limit(plugin, tmp_path):
    """事件路径也遵守监控与排除目录，全事件数量限制不按目录重置。"""
    excluded = make_strm(tmp_path / "blocked" / "Film.1080p.strm")
    allowed = make_strm(tmp_path / "blocked-copy" / "Film.1080p.StRm")
    second = make_strm(tmp_path / "second" / "Film.1080p.strm")
    third = make_strm(tmp_path / "third" / "Film.1080p.strm")
    plugin._exclude_paths = str(excluded.parent)
    plugin._run_batch([str(excluded), str(allowed), str(allowed), str(second), str(third)], "event")
    assert not excluded.with_suffix(".strm.nfo").exists()
    assert allowed.with_suffix(".strm.nfo").exists()
    assert second.with_suffix(".strm.nfo").exists()
    assert not third.with_suffix(".strm.nfo").exists()
    assert plugin.get_data("history")[-1]["scanned"] == 2
    assert not plugin._allowed_path(tmp_path.parent / "outside.strm")


def test_full_scan_handles_mixed_case_and_overlapping_roots_once(plugin, tmp_path):
    """重叠监控目录中的同一文件只计数一次，支持混合大小写扩展名。"""
    path = make_strm(tmp_path / "nested" / "Film.1080p.StRm")
    plugin._watch_paths = f"{tmp_path}\n{path.parent}"
    plugin._scan()
    assert plugin.get_data("history")[-1]["scanned"] == 1
    assert path.with_suffix(".strm.nfo").is_file()


def test_nonlocal_transfer_is_ignored(plugin):
    """远端存储的路径不能被当作本地文件处理。"""
    plugin._submit_paths = Mock()
    transfer = {"target_item": {"storage": "u115", "path": "/media/Film.1080p.strm"}}
    plugin.on_transfer_complete(SimpleNamespace(event_data={"transferinfo": transfer}))
    plugin._submit_paths.assert_not_called()


def test_stopped_plugin_cannot_restart_worker_or_write(plugin, tmp_path):
    """停止后排队事件和定时任务不应重新创建线程池或写文件。"""
    path = make_strm(tmp_path / "Film.1080p.strm")
    plugin.stop_service()
    plugin._submit_paths([str(path)], "event")
    plugin._submit_scan("manual")
    plugin._run_batch([str(path)], "event")
    assert plugin._executor is None
    assert not path.with_suffix(".strm.nfo").exists()


def test_invalid_cron_is_reported_without_breaking_registration(plugin):
    """错误周期不阻断宿主加载其他插件服务。"""
    plugin._cron = "invalid"
    assert plugin.get_service() == []


def test_instance_locks_are_independent(monkeypatch):
    """分身实例的锁与停止状态互不共享。"""
    monkeypatch.setattr(_PluginBase, "__init__", lambda self: None)
    first, second = StrmNfo(), StrmNfo()
    first.stop_service()
    assert first._lock is not second._lock
    assert not second._stopped.is_set()
