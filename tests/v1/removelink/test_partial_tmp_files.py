"""清理硬链接插件：下载器把未完成文件改名为 .part/.!qB 不是删除，刮削清理不得误删临时文件和视频。"""

import os
from pathlib import Path

from app.plugins import removelink as plugin_module
from app.plugins.removelink import RemoveLink


def _plugin(monitor_dir: Path, delete_scrap_infos: bool = False) -> RemoveLink:
    """创建只保留硬链接清理（可选刮削清理）、关闭种子/历史/通知联动的插件实例。"""
    plugin = RemoveLink()
    plugin._delete_scrap_infos = delete_scrap_infos
    plugin._delete_torrents = False
    plugin._delete_history = False
    plugin._notify = False
    plugin.exclude_dirs = ""
    plugin.exclude_keywords = ""
    plugin.monitor_dirs = str(monitor_dir)
    plugin.state_set = {}
    plugin.dir_state_set = set()
    return plugin


def _track(plugin: RemoveLink, root: Path, *paths: Path) -> None:
    """通过新增事件把文件纳入监控，走插件自己的记录逻辑。"""
    handler = plugin_module.FileMonitorHandler(str(root), plugin)
    for path in paths:
        handler.on_created(plugin_module.WatchfilesEvent(str(path), is_directory=False))


def _source_and_link(root: Path):
    """创建下载源文件及其媒体库硬链接。"""
    source = root / "download" / "Show.S01E01.1080p.mkv"
    link = root / "library" / "Show (2024)" / "Season 1" / "Show - S01E01 - 第 1 集.mkv"
    source.parent.mkdir(parents=True)
    link.parent.mkdir(parents=True)
    source.write_bytes(b"episode")
    os.link(source, link)
    return source, link


def test_rename_to_part_keeps_hardlink(tmp_path):
    """Transmission 校验把 X.mkv 改名为 X.mkv.part 时，媒体库硬链接必须保留。"""
    plugin = _plugin(tmp_path)
    source, link = _source_and_link(tmp_path)
    _track(plugin, tmp_path, source, link)

    os.rename(source, source.with_name(source.name + ".part"))
    plugin.handle_deleted(source)

    assert link.exists(), "改名为 .part 不是删除，硬链接不能被清理"
    assert str(link) in plugin.state_set
    assert str(source) not in plugin.state_set


def test_rename_to_qb_tmp_keeps_hardlink(tmp_path):
    """qBittorrent 的 .!qB 临时后缀同样视为改名而不是删除。"""
    plugin = _plugin(tmp_path)
    source, link = _source_and_link(tmp_path)
    _track(plugin, tmp_path, source, link)

    os.rename(source, source.with_name(source.name + ".!qB"))
    plugin.handle_deleted(source)

    assert link.exists()


def test_real_deletion_still_removes_hardlink(tmp_path):
    """真正删除源文件时仍然联动删除硬链接；旁边无关的 .part 文件不能挡住清理。"""
    plugin = _plugin(tmp_path)
    source, link = _source_and_link(tmp_path)
    _track(plugin, tmp_path, source, link)

    source.unlink()
    source.with_name(source.name + ".part").write_bytes(b"unrelated new download")
    plugin.handle_deleted(source)

    assert not link.exists(), "真实删除仍需联动删除硬链接"


def test_delete_scrap_infos_skips_tmp_and_media_files(tmp_path):
    """刮削清理按前缀匹配时，跳过同名的下载临时文件和视频文件，只删 nfo/图片等。"""
    plugin = _plugin(tmp_path, delete_scrap_infos=True)
    folder = tmp_path / "download" / "Show"
    folder.mkdir(parents=True)
    video = folder / "Show.S01E01.mkv"
    partial = folder / "Show.S01E01.mkv.part"
    other_video = folder / "Show.S01E01.mp4"
    nfo = folder / "Show.S01E01.nfo"
    thumb = folder / "Show.S01E01-thumb.jpg"
    for path in (partial, other_video, nfo, thumb):
        path.write_bytes(b"x")

    plugin.delete_scrap_infos(video)

    assert partial.exists(), "正在下载的 .part 数据不是刮削文件"
    assert other_video.exists(), "同名视频文件不是刮削文件"
    assert not nfo.exists()
    assert not thumb.exists()
