import json
import math
import subprocess
from pathlib import Path

from app.log import logger

# 单个文件截帧的最长等待时间（秒），避免异常文件让任务无限挂起
FFMPEG_THUMB_TIMEOUT = 300

# 读取时长的最长等待时间（秒），只是读容器索引，正常在 100ms 内返回
FFPROBE_DURATION_TIMEOUT = 30

# 截取点距视频结尾不足该值时视为越界，改用短片截取点（常见于单集 3 分钟的短动画）
FFMPEG_THUMB_TAIL_MARGIN = 5

# 短片（时长不足以支撑 3 分钟截取点）改取的秒数
FFMPEG_THUMB_SHORT_SEEK = 30


class FfmpegHelper:
    """封装有限时的媒体探测与缩略图生成。"""

    @staticmethod
    def _frames_to_seconds(frames: str) -> float:
        """
        把 HH:MM:SS（也接受 MM:SS 或纯秒数）转换为秒，无法解析时返回 0
        """
        try:
            total = 0.0
            for part in str(frames).split(":"):
                total = total * 60 + float(part)
            return total
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def get_duration(video_path: str) -> float:
        """
        读取视频时长（秒），只读容器索引不解码，失败返回 0
        """
        if not video_path:
            return 0.0
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(video_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=FFPROBE_DURATION_TIMEOUT
            )
            if result.returncode == 0:
                duration = float(result.stdout.decode("utf-8", errors="ignore").strip() or 0)
                return duration if math.isfinite(duration) and duration > 0 else 0.0
        except Exception as err:
            logger.warning(f"ffprobe读取视频时长失败：{video_path}，原因：{str(err)}")
        return 0.0

    @staticmethod
    def get_thumb(video_path: str, image_path: str, frames: str = None) -> bool:
        """
        使用ffmpeg从视频文件中截取缩略图

        - ``-ss`` 放在 ``-i`` 之前，由 ffmpeg 直接定位后精确解码，避免每个文件都从头解码到目标时间
        - 截取点超出视频长度时（短剧、短动画常见）自动前移到 30 秒处，否则 ffmpeg 会输出空文件并报 mjpeg 错误
        - 固定传入 ``-y``、``-nostdin`` 与超时，防止覆盖确认或异常输入把任务挂住

        :param video_path: 视频文件路径
        :param image_path: 输出图片路径
        :param frames: 截取时间点，格式 HH:MM:SS，留空时取 00:03:01
        :return: 是否成功生成图片
        """
        if not video_path or not image_path:
            return False
        frames = frames or "00:03:01"
        duration = FfmpegHelper.get_duration(video_path)
        seek_seconds = FfmpegHelper._frames_to_seconds(frames)
        if duration > 0 and seek_seconds >= duration - FFMPEG_THUMB_TAIL_MARGIN:
            # 目标时间点已经越过视频末尾，退到短片截取点，避免 -ss 越界导致输出空文件
            fallback = min(FFMPEG_THUMB_SHORT_SEEK, duration / 2)
            logger.info(f"视频时长 {duration:.0f} 秒，截取点 {frames} 越界，改取 {fallback:.0f} 秒：{video_path}")
            frames = f"{fallback:.6f}"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", str(frames), "-i", str(video_path),
            "-frames:v", "1", "-f", "image2", "-update", "1", str(image_path)
        ]
        try:
            result = subprocess.run(command,
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    timeout=FFMPEG_THUMB_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.error(f"FFmpeg截取缩略图超时（{FFMPEG_THUMB_TIMEOUT}秒）：{video_path}")
            return False
        except Exception as err:
            logger.error(f"FFmpeg截取缩略图异常：{video_path}，原因：{str(err)}")
            return False
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="ignore").strip()
            logger.error(f"FFmpeg截取缩略图失败：{video_path}，原因：{detail[-300:]}")
            return False
        output = Path(image_path)
        return output.is_file() and output.stat().st_size > 0

    @staticmethod
    def extract_wav(video_path: str, audio_path: str, audio_index: str = None):
        """
        使用ffmpeg从视频文件中提取16000hz, 16-bit的wav格式音频
        """
        if not video_path or not audio_path:
            return False

        # 提取指定音频流
        if audio_index:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path,
                       '-map', f'0:a:{audio_index}',
                       '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000', audio_path]
        else:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path,
                       '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000', audio_path]

        ret = subprocess.run(command).returncode
        if ret == 0:
            return True
        return False

    @staticmethod
    def get_metadata(video_path: str):
        """
        获取视频元数据
        """
        if not video_path:
            return False

        try:
            command = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', video_path]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                return json.loads(result.stdout.decode("utf-8"))
        except Exception as e:
            print(e)
        return None

    @staticmethod
    def extract_subtitle(video_path: str, subtitle_path: str, subtitle_index: str = None):
        """
        从视频中提取字幕
        """
        if not video_path or not subtitle_path:
            return False

        if subtitle_index:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path,
                       '-map', f'0:s:{subtitle_index}',
                       subtitle_path]
        else:
            command = ['ffmpeg', "-hide_banner", "-loglevel", "warning", '-y', '-i', video_path, subtitle_path]
        ret = subprocess.run(command).returncode
        if ret == 0:
            return True
        return False
