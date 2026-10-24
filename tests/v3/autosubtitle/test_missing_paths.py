"""整理目标失效时的事件处理、外挂扫描与内封探测回归。"""

import asyncio
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.testing import stub_modules

# 本组只验证文件边界，不运行关键词提取，也不要求安装 YAKE。
yake_stub = ModuleType("yake")
yake_stub.KeywordExtractor = Mock()
with stub_modules({"yake": yake_stub}):
    from app.plugins import autosubtitle


@pytest.fixture
def plugin(monkeypatch):
    """绕过宿主初始化，只装配字幕检查需要的配置并隔离日志。"""
    instance = object.__new__(autosubtitle.AutoSubtitle)
    instance._enabled = True
    instance._media_types = ["电影", "电视剧"]
    instance._subtitle_langs = ["简体中文", "繁體中文"]
    instance._subtitle_exts = {".srt", ".ass"}
    instance._SIMPLIFIED_FILE_MARKERS = {"zh-cn"}
    instance._TRADITIONAL_FILE_MARKERS = {"zh-tw"}
    monkeypatch.setattr(autosubtitle, "logger", Mock())
    return instance


def transfer_event(video_path):
    """构造包含目标路径的整理完成事件，不依赖真实整理和搜索服务。"""
    target = SimpleNamespace(path=str(video_path), name=video_path.name)
    return SimpleNamespace(event_data={
        "meta": SimpleNamespace(en_name="Movie"),
        "mediainfo": SimpleNamespace(type=SimpleNamespace(value="电影")),
        "transferinfo": SimpleNamespace(target_item=target, fileitem=None),
    })


def test_release_metadata_matches_implementation():
    """修复版本、索引历史和 Release 开关必须与实际分发的 V3 实现一致。"""
    root = Path(__file__).resolve().parents[3]
    entry = json.loads((root / "package.v3.json").read_text(encoding="utf-8"))["AutoSubtitle"]
    assert entry["version"] == autosubtitle.AutoSubtitle.plugin_version
    assert next(iter(entry["history"])) == f"v{entry['version']}"
    assert entry["release"] is True


@pytest.mark.parametrize("target_kind", ["missing_directory", "missing_video", "directory"])
def test_transfer_skips_missing_video_before_subtitle_work(plugin, tmp_path, monkeypatch, target_kind):
    """失效目标不进入字幕探测、关键词提取或搜索，事件正常完成。"""
    video = tmp_path / "movie.mkv"
    if target_kind == "missing_directory":
        video = tmp_path / "removed" / video.name
    elif target_kind == "directory":
        video.mkdir()
    check = AsyncMock(return_value=[])
    extract = Mock(return_value=[])
    search = AsyncMock()
    monkeypatch.setattr(plugin, "_AutoSubtitle__check_missing_subtitles", check)
    monkeypatch.setattr(plugin, "_AutoSubtitle__extract_keywords", extract)
    monkeypatch.setattr(plugin, "_AutoSubtitle__search_subtitles", search)

    asyncio.run(plugin.on_transfer_complete(transfer_event(video)))

    check.assert_not_awaited()
    extract.assert_not_called()
    search.assert_not_awaited()
    assert str(video) in autosubtitle.logger.debug.call_args.args[0]


def test_transfer_keeps_existing_video_processing(plugin, tmp_path, monkeypatch):
    """有效视频继续检查已有字幕，入口保护不影响正常整理事件。"""
    video = tmp_path / "movie.mkv"
    video.touch()
    check = AsyncMock(return_value=[])
    monkeypatch.setattr(plugin, "_AutoSubtitle__check_missing_subtitles", check)

    asyncio.run(plugin.on_transfer_complete(transfer_event(video)))

    check.assert_awaited_once_with(str(video))


@pytest.mark.parametrize("target_kind", ["missing", "not_directory"])
def test_scan_unavailable_directory_returns_no_subtitles(plugin, tmp_path, target_kind):
    """真实缺失目录或被同名文件替换的目录都按无外挂字幕回退。"""
    directory = tmp_path / "removed"
    if target_kind == "not_directory":
        directory.touch()

    assert plugin._AutoSubtitle__scan_subtitles_in_dir(directory, "movie") == (False, False, [])
    assert str(directory) in autosubtitle.logger.warning.call_args.args[0]


@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_scan_read_error_returns_no_subtitles(plugin, tmp_path, monkeypatch, error_type):
    """目录权限和其他文件系统错误不会冒泡到事件派发。"""
    monkeypatch.setattr(Path, "iterdir", Mock(side_effect=error_type("scan failed")))

    assert plugin._AutoSubtitle__scan_subtitles_in_dir(tmp_path, "movie") == (False, False, [])
    autosubtitle.logger.warning.assert_called_once()


def test_scan_catches_error_during_lazy_iteration(plugin, tmp_path, monkeypatch):
    """遍历开始后目录消失也要捕获，不能只保护迭代器的创建。"""
    subtitle = tmp_path / "movie.zh-cn.srt"
    subtitle.touch()

    def interrupted_entries(_directory):
        """先返回一个有效字幕，再模拟读取目录中途失败。"""
        yield subtitle
        raise FileNotFoundError("directory removed during iteration")

    monkeypatch.setattr(Path, "iterdir", interrupted_entries)

    assert plugin._AutoSubtitle__scan_subtitles_in_dir(tmp_path, "movie") == (False, False, [])
    autosubtitle.logger.warning.assert_called_once()


def test_scan_preserves_language_markers_and_unmarked_candidates(plugin, tmp_path):
    """正常扫描仍识别简繁标记、下载临时后缀和需内容验证的同名字幕。"""
    for name in ("movie.zh-cn.srt", "movie.zh-tw.srt.!qB", "movie.srt", "other.srt", "movie.txt"):
        (tmp_path / name).touch()
    (tmp_path / "ignored.zh-cn.ass").mkdir()

    assert plugin._AutoSubtitle__scan_subtitles_in_dir(tmp_path, "movie") == (
        True, True, [tmp_path / "movie.srt"],
    )


def test_transfer_directory_removed_after_entry_check_completes(plugin, tmp_path, monkeypatch):
    """入口检查后发生删除竞态时，实际目录扫描仍能回退并完成事件。"""
    directory = tmp_path / "removed"
    directory.mkdir()
    video = directory / "movie.mkv"
    video.touch()
    real_check = plugin._AutoSubtitle__check_missing_subtitles

    async def check_after_removal(video_path):
        """在入口确认视频存在后删除目标，再执行真实字幕检查。"""
        video.unlink()
        directory.rmdir()
        return await real_check(video_path)

    probe = AsyncMock(return_value=(False, False))
    monkeypatch.setattr(plugin, "_AutoSubtitle__check_missing_subtitles", check_after_removal)
    monkeypatch.setattr(plugin, "_AutoSubtitle__probe_embedded_subtitles", probe)
    monkeypatch.setattr(plugin, "_AutoSubtitle__extract_keywords", Mock(return_value=[]))

    asyncio.run(plugin.on_transfer_complete(transfer_event(video)))

    probe.assert_awaited_once_with(str(video))
    autosubtitle.logger.warning.assert_any_call(
        "[AutoSubtitle] 无法获取英文关键词，跳过",
    )


def test_ffprobe_missing_video_returns_no_embedded_subtitles(plugin, tmp_path, monkeypatch):
    """视频已删除时 ffprobe 的非零返回码保持无内封字幕的现有回退。"""
    version = SimpleNamespace(communicate=AsyncMock(return_value=(b"", b"")), returncode=0)
    probe = SimpleNamespace(communicate=AsyncMock(return_value=(b"", b"No such file")), returncode=1)
    launch = AsyncMock(side_effect=[version, probe])
    monkeypatch.setattr(autosubtitle.asyncio, "create_subprocess_exec", launch)
    video = str(tmp_path / "removed.mkv")

    assert asyncio.run(plugin._AutoSubtitle__probe_embedded_subtitles(video)) == (False, False)
    assert video in launch.call_args.args
    probe.communicate.assert_awaited_once()


def test_ffprobe_missing_executable_returns_no_embedded_subtitles(plugin, monkeypatch):
    """缺少可选 ffprobe 程序时也不应让整理完成事件失败。"""
    monkeypatch.setattr(autosubtitle.asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError))

    assert asyncio.run(plugin._AutoSubtitle__probe_embedded_subtitles("removed.mkv")) == (False, False)
