"""FFmpeg缩略图：分集缩略图命名、跳过规则与 ffmpeg 参数顺序。"""
from pathlib import Path
import threading
from unittest.mock import Mock, patch

from app.plugins.ffmpegthumb import FFmpegThumb
from app.plugins.ffmpegthumb.ffmpeg_helper import FFMPEG_THUMB_TIMEOUT, FfmpegHelper


def make_video(tmp_path: Path, name: str = "Show - S01E03.mkv") -> Path:
    """创建占位视频文件，只关心命名与存在性判断。"""
    video = tmp_path / name
    video.write_bytes(b"video")
    return video


def make_plugin(skip_existing: bool = True) -> FFmpegThumb:
    """绕过插件启动流程，仅装配缩略图处理需要的字段。"""
    plugin = object.__new__(FFmpegThumb)
    plugin._timeline = "00:03:01"
    plugin._skip_existing = skip_existing
    return plugin


def test_build_thumb_path_appends_thumb_suffix(tmp_path):
    """缩略图与视频同目录同名，仅追加 -thumb.jpg。"""
    video = make_video(tmp_path)

    assert FFmpegThumb.build_thumb_path(video) == tmp_path / "Show - S01E03-thumb.jpg"


def test_should_skip_when_thumb_exists(tmp_path):
    """已生成过缩略图时跳过，避免重复截帧。"""
    video = make_video(tmp_path)
    FFmpegThumb.build_thumb_path(video).write_bytes(b"jpg")

    skip, reason = FFmpegThumb.should_skip(video)

    assert skip is True
    assert "缩略图已存在" in reason


def test_should_skip_when_scraped_image_exists(tmp_path):
    """已刮削到分集剧照（同名 jpg）时跳过，不用截帧覆盖官方图。"""
    video = make_video(tmp_path)
    video.with_suffix(".jpg").write_bytes(b"jpg")

    skip, reason = FFmpegThumb.should_skip(video, skip_existing=True)

    assert skip is True
    assert "已有分集图片" in reason


def test_should_not_skip_scraped_image_when_switch_off(tmp_path):
    """关闭跳过开关后，同名 jpg 不再阻止生成。"""
    video = make_video(tmp_path)
    video.with_suffix(".jpg").write_bytes(b"jpg")

    assert FFmpegThumb.should_skip(video, skip_existing=False) == (False, "")


def test_should_not_skip_plain_video(tmp_path):
    """既无缩略图也无分集剧照的视频需要处理。"""
    video = make_video(tmp_path)

    assert FFmpegThumb.should_skip(video) == (False, "")


def test_gen_file_thumb_skips_without_calling_ffmpeg(tmp_path):
    """命中跳过规则时不应调用 ffmpeg。"""
    video = make_video(tmp_path)
    video.with_suffix(".jpg").write_bytes(b"jpg")
    plugin = make_plugin()

    with patch.object(FfmpegHelper, "get_thumb") as get_thumb:
        assert plugin.gen_file_thumb(video) == FFmpegThumb.RESULT_SKIPPED
        get_thumb.assert_not_called()


def test_gen_file_thumb_generates_and_reports_result(tmp_path):
    """需要处理时调用 ffmpeg，输出仍为 <视频名>-thumb.jpg。"""
    video = make_video(tmp_path)
    plugin = make_plugin()

    with patch.object(FfmpegHelper, "get_thumb", return_value=True) as get_thumb:
        assert plugin.gen_file_thumb(video) == FFmpegThumb.RESULT_GENERATED

    get_thumb.assert_called_once()
    assert get_thumb.call_args.kwargs["image_path"].endswith("Show - S01E03-thumb.jpg")


def test_gen_file_thumb_reports_failure(tmp_path):
    """ffmpeg 失败时返回失败结果，供扫描统计。"""
    video = make_video(tmp_path)
    plugin = make_plugin()

    with patch.object(FfmpegHelper, "get_thumb", return_value=False):
        assert plugin.gen_file_thumb(video) == FFmpegThumb.RESULT_FAILED


def test_get_thumb_seeks_before_input(tmp_path):
    """-ss 必须位于 -i 之前，否则每个文件都要从头解码到目标时间。"""
    video = make_video(tmp_path)
    image = tmp_path / "Show - S01E03-thumb.jpg"
    captured = {}

    class Result:
        """模拟外部命令返回的执行结果。"""
        returncode = 0
        stderr = b""

    def fake_run(command, **kwargs):
        """模拟命令执行，记录参数并生成占位图片。"""
        captured["command"] = command
        captured["kwargs"] = kwargs
        image.write_bytes(b"jpg")
        return Result()

    with patch("app.plugins.ffmpegthumb.ffmpeg_helper.subprocess.run", side_effect=fake_run):
        assert FfmpegHelper.get_thumb(str(video), str(image), "00:03:01") is True

    command = captured["command"]
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "00:03:01"
    assert "-y" in command
    assert "-nostdin" in command
    assert captured["kwargs"]["timeout"] == FFMPEG_THUMB_TIMEOUT


def test_get_thumb_returns_false_when_ffmpeg_fails(tmp_path):
    """ffmpeg 非零退出时返回 False，不把半成品当成功。"""
    video = make_video(tmp_path)
    image = tmp_path / "out.jpg"

    class Result:
        """模拟外部命令返回的执行结果。"""
        returncode = 1
        stderr = b"boom"

    with patch("app.plugins.ffmpegthumb.ffmpeg_helper.subprocess.run", return_value=Result()):
        assert FfmpegHelper.get_thumb(str(video), str(image)) is False


def test_subsecond_video_uses_seek_within_its_duration(tmp_path):
    """不足一秒的视频也选择实际时长以内的位置，避免最低一秒截取点越界。"""
    video = make_video(tmp_path)
    image = tmp_path / "out.jpg"

    def run(command, **kwargs):
        """模拟成功截取并校验定位参数。"""
        assert 0 <= float(command[command.index("-ss") + 1]) < 0.5
        image.write_bytes(b"jpg")
        return type("Result", (), {"returncode": 0, "stderr": b""})()

    with patch.object(FfmpegHelper, "get_duration", return_value=0.5), patch(
        "app.plugins.ffmpegthumb.ffmpeg_helper.subprocess.run", side_effect=run
    ):
        assert FfmpegHelper.get_thumb(str(video), str(image))


def test_ffmpeg_success_with_empty_output_is_failure(tmp_path):
    """命令成功但未输出有效图片时不能当作已生成。"""
    video = make_video(tmp_path)
    image = tmp_path / "empty.jpg"
    image.touch()
    result = type("Result", (), {"returncode": 0, "stderr": b""})()
    with patch.object(FfmpegHelper, "get_duration", return_value=600), patch(
        "app.plugins.ffmpegthumb.ffmpeg_helper.subprocess.run", return_value=result
    ):
        assert not FfmpegHelper.get_thumb(str(video), str(image))


def test_empty_existing_images_allow_retry(tmp_path):
    """空图片不能阻止后续截帧重试。"""
    video = make_video(tmp_path)
    FFmpegThumb.build_thumb_path(video).touch()
    video.with_suffix(".jpg").touch()
    assert FFmpegThumb.should_skip(video) == (False, "")


def test_blank_exclusion_does_not_exclude_scan_root(tmp_path):
    """空排除行不能被解释为当前目录，导致所有扫描文件被跳过。"""
    video = make_video(tmp_path)
    plugin = make_plugin()
    plugin._scan_paths = str(tmp_path)
    plugin._exclude_paths = "\n  \n"
    plugin._event = threading.Event()
    plugin.gen_file_thumb = Mock(return_value=FFmpegThumb.RESULT_GENERATED)
    with patch("app.plugins.ffmpegthumb.SystemUtils.list_files", return_value=[video]):
        plugin._FFmpegThumb__libraryscan()
    plugin.gen_file_thumb.assert_called_once_with(video)
