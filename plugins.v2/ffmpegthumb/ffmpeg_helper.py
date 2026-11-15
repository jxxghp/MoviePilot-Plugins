import json
import subprocess
from pathlib import Path

from app.log import logger

# 单个文件截帧的最长等待时间（秒），避免异常文件让任务无限挂起
FFMPEG_THUMB_TIMEOUT = 300


class FfmpegHelper:

    @staticmethod
    def get_thumb(video_path: str, image_path: str, frames: str = None) -> bool:
        """
        使用ffmpeg从视频文件中截取缩略图

        - ``-ss`` 放在 ``-i`` 之前，由 ffmpeg 直接定位后精确解码，避免每个文件都从头解码到目标时间
        - 固定传入 ``-y``、``-nostdin`` 与超时，防止覆盖确认或异常输入把任务挂住

        :param video_path: 视频文件路径
        :param image_path: 输出图片路径
        :param frames: 截取时间点，格式 HH:MM:SS，留空时取 00:03:01
        :return: 是否成功生成图片
        """
        if not video_path or not image_path:
            return False
        frames = frames or "00:03:01"
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
        return Path(image_path).exists()

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
