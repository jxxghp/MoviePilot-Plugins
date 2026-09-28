from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe_subtitle_codecs(path: Path) -> list[str]:
    """按输入字幕流顺序返回编码名称。"""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    return [str(stream.get("codec_name") or "") for stream in data.get("streams") or []]


def encoder_command(
    output_path: Path,
    width: int,
    height: int,
    rate: str,
    sar: str,
    cq: int,
    gpu_index: int,
) -> list[str]:
    """构造固定使用推理 GPU 的 NVENC 命令。"""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s:v",
        f"{width}x{height}",
        "-r",
        rate,
        "-i",
        "pipe:0",
        "-an",
        "-vf",
        f"scale=out_color_matrix=bt709:out_range=tv,setsar={sar},format=p010le",
        "-c:v",
        "hevc_nvenc",
        "-gpu",
        str(gpu_index),
        "-preset",
        "p7",
        "-tune",
        "hq",
        "-rc",
        "vbr",
        "-cq",
        str(cq),
        "-b:v",
        "0",
        "-profile:v",
        "main10",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-color_range",
        "tv",
        str(output_path),
    ]


def remux_command(
    video_path: Path,
    input_path: Path,
    output_path: Path,
    subtitle_codecs: list[str],
) -> list[str]:
    """复制兼容流，并将 Matroska 不支持的 mov_text 字幕转为 SubRip。"""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-map",
        "1:s?",
        "-map",
        "1:t?",
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c",
        "copy",
    ]
    for index, codec in enumerate(subtitle_codecs):
        if codec == "mov_text":
            command.extend((f"-c:s:{index}", "srt"))
    command.append(str(output_path))
    return command
