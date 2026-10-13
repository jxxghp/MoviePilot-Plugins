"""清理硬链接插件：硬链接匹配必须同时比较设备号与 inode，跨卷同 inode 号不得误删。"""

import os
from pathlib import Path

from app.plugins import removelink as plugin_module
from app.plugins.removelink import RemoveLink


def _plugin() -> RemoveLink:
    """创建关闭了刮削/种子/历史/通知联动、只保留硬链接清理逻辑的插件实例。"""
    plugin = RemoveLink()
    plugin._delete_scrap_infos = False
    plugin._delete_torrents = False
    plugin._delete_history = False
    plugin._notify = False
    plugin.exclude_dirs = ""
    plugin.exclude_keywords = ""
    plugin.monitor_dirs = ""
    plugin.state_set = {}
    plugin.dir_state_set = set()
    return plugin


def test_update_state_records_device_and_inode(tmp_path):
    """全量扫描记录的是 (st_dev, st_ino)，同一文件实体的硬链接二者一致。"""
    source = tmp_path / "media" / "episode.mkv"
    link = tmp_path / "links" / "episode.mkv"
    source.parent.mkdir()
    link.parent.mkdir()
    source.write_bytes(b"data")
    os.link(source, link)

    state_set, dir_state_set = plugin_module.updateState([str(tmp_path)])

    stat_info = source.stat()
    assert state_set[str(source)] == (stat_info.st_dev, stat_info.st_ino)
    assert state_set[str(link)] == state_set[str(source)]
    assert str(source.parent) in dir_state_set


def test_on_created_records_device_and_inode(tmp_path):
    """新增文件事件写入的监控记录同样带设备号。"""
    plugin = _plugin()
    new_file = tmp_path / "new.mkv"
    new_file.write_bytes(b"data")
    handler = plugin_module.FileMonitorHandler(str(tmp_path), plugin)

    handler.on_created(plugin_module.WatchfilesEvent(str(new_file), is_directory=False))

    stat_info = new_file.stat()
    assert plugin.state_set[str(new_file)] == (stat_info.st_dev, stat_info.st_ino)


def test_handle_deleted_ignores_same_inode_on_other_device(tmp_path, monkeypatch):
    """被删文件的 inode 号在另一卷上撞号时，另一卷的文件不能被当作硬链接删除。"""
    plugin = _plugin()
    source = tmp_path / "vol3" / "show.mkv"
    hardlink = tmp_path / "vol3" / "links" / "show.mkv"
    other_volume = tmp_path / "vol4" / "unrelated.mkv"
    hardlink.parent.mkdir(parents=True)
    other_volume.parent.mkdir(parents=True)
    source.write_bytes(b"data")
    os.link(source, hardlink)
    other_volume.write_bytes(b"other")
    source_stat = source.stat()

    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        """让另一卷的文件呈现为：inode 号与源文件相同，但设备号不同。"""
        result = real_stat(self, *args, **kwargs)
        if self == other_volume:
            return os.stat_result(
                (
                    result.st_mode,
                    source_stat.st_ino,
                    result.st_dev + 1,
                    result.st_nlink,
                    result.st_uid,
                    result.st_gid,
                    result.st_size,
                    result.st_atime,
                    result.st_mtime,
                    result.st_ctime,
                )
            )
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)
    handler = plugin_module.FileMonitorHandler(str(tmp_path), plugin)
    for path in (source, hardlink, other_volume):
        handler.on_created(plugin_module.WatchfilesEvent(str(path), is_directory=False))
    assert plugin.state_set[str(other_volume)][1] == plugin.state_set[str(source)][1]

    source.unlink()
    plugin.handle_deleted(source)

    assert not hardlink.exists(), "同卷同实体的硬链接应被联动删除"
    assert other_volume.exists(), "另一卷同 inode 号的文件不是硬链接，不能删除"
    assert str(other_volume) in plugin.state_set
    assert str(source) not in plugin.state_set
