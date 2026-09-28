from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import torch
import torch.nn.functional as functional
from spandrel import MAIN_REGISTRY, ModelLoader
from spandrel_extra_arches import EXTRA_REGISTRY

from .config import RuntimeSettings
from .errors import Cancelled
from .ffmpeg import encoder_command, probe_subtitle_codecs, remux_command


_SPANDREL_REGISTRY_LOCK = threading.Lock()
_SPANDREL_EXTRA_REGISTERED = False


def register_spandrel_extra_arches() -> None:
    global _SPANDREL_EXTRA_REGISTERED
    if _SPANDREL_EXTRA_REGISTERED:
        return
    with _SPANDREL_REGISTRY_LOCK:
        if not _SPANDREL_EXTRA_REGISTERED:
            MAIN_REGISTRY.add(*EXTRA_REGISTRY)
            _SPANDREL_EXTRA_REGISTERED = True


def probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,avg_frame_rate,sample_aspect_ratio,nb_frames,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise RuntimeError("输入文件没有视频轨")
    stream = data["streams"][0]
    average_rate_text = stream.get("avg_frame_rate", "0/0")
    real_rate_text = stream.get("r_frame_rate", "0/0")
    try:
        average_rate = Fraction(average_rate_text)
        real_rate = Fraction(real_rate_text)
    except (ValueError, ZeroDivisionError) as error:
        raise RuntimeError("无法识别输入帧率") from error
    if average_rate <= 0 or real_rate <= 0:
        raise RuntimeError("无法识别输入帧率")
    if average_rate != real_rate:
        raise RuntimeError(
            f"暂不支持可变帧率视频：r_frame_rate={real_rate_text}，"
            f"avg_frame_rate={average_rate_text}"
        )
    rate_text = f"{average_rate.numerator}/{average_rate.denominator}"
    fps = float(average_rate)
    sar_text = stream.get("sample_aspect_ratio") or "1:1"
    try:
        sar = Fraction(sar_text.replace(":", "/"))
    except (ValueError, ZeroDivisionError) as error:
        raise RuntimeError(f"无法识别输入像素宽高比：{sar_text}") from error
    if sar <= 0:
        raise RuntimeError(f"无法识别输入像素宽高比：{sar_text}")
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    frames = int(stream.get("nb_frames") or 0)
    if not frames and duration:
        frames = max(1, round(duration * fps))
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "rate": rate_text,
        "fps": fps,
        "sar": f"{sar.numerator}/{sar.denominator}",
        "frames": frames,
        "duration": duration,
    }


def verify_output(path: Path, expected_width: int, expected_height: int) -> None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    if not streams or streams[0].get("codec_type") != "video":
        raise RuntimeError("封装后的输出文件没有可读视频轨")
    stream = streams[0]
    dimensions = (int(stream.get("width") or 0), int(stream.get("height") or 0))
    if dimensions != (expected_width, expected_height):
        raise RuntimeError(
            f"封装后的输出尺寸错误：{dimensions[0]}x{dimensions[1]}，"
            f"预期 {expected_width}x{expected_height}"
        )


class StarSampleRuntime:
    def __init__(self, settings: RuntimeSettings, log: Callable[[str], None]):
        if not torch.cuda.is_available():
            raise RuntimeError("MoviePilot 运行环境未检测到 CUDA")
        if not settings.model_path.is_file():
            raise RuntimeError(f"模型文件不存在：{settings.model_path}")
        register_spandrel_extra_arches()
        self.device = torch.device(settings.device)
        self.model = ModelLoader().load_from_file(settings.model_path).eval().to(self.device)
        self.scale = int(self.model.scale)
        if self.scale != 2:
            raise RuntimeError(f"模型缩放倍率应为 2，实际为 {self.scale}")
        self.model = self.model.to(dtype=torch.float32)
        self.tile = settings.tile
        self.context = settings.context
        log(
            f"模型已加载：{settings.model_path.name}，FP32，"
            f"tile={self.tile}，context={self.context}"
        )

    def upscale(self, frame: bytes, width: int, height: int) -> bytes:
        array = np.frombuffer(frame, dtype=np.uint8).reshape(height, width, 3).copy()
        image = (
            torch.from_numpy(array)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(device=self.device, dtype=torch.float32)
            / 255.0
        )
        output = self._upscale_tiled(image)
        output = (
            output.squeeze(0)
            .clamp_(0, 1)
            .mul_(255)
            .round_()
            .to(dtype=torch.uint8)
            .permute(1, 2, 0)
            .contiguous()
            .cpu()
            .numpy()
        )
        return output.tobytes()

    def _upscale_tiled(self, image: torch.Tensor) -> torch.Tensor:
        _, _, height, width = image.shape
        output = torch.empty(
            (1, 3, height * self.scale, width * self.scale),
            device=self.device,
            dtype=torch.float32,
        )
        with torch.inference_mode():
            for top in range(0, height, self.tile):
                bottom = min(top + self.tile, height)
                for left in range(0, width, self.tile):
                    right = min(left + self.tile, width)
                    input_top = max(0, top - self.context)
                    input_bottom = min(height, bottom + self.context)
                    input_left = max(0, left - self.context)
                    input_right = min(width, right + self.context)
                    patch = image[:, :, input_top:input_bottom, input_left:input_right]
                    upscaled = self.model(patch)
                    crop_top = (top - input_top) * self.scale
                    crop_left = (left - input_left) * self.scale
                    crop_bottom = crop_top + (bottom - top) * self.scale
                    crop_right = crop_left + (right - left) * self.scale
                    output[
                        :,
                        :,
                        top * self.scale : bottom * self.scale,
                        left * self.scale : right * self.scale,
                    ] = upscaled[:, :, crop_top:crop_bottom, crop_left:crop_right]
        return output


class AnimeSRRuntime:
    def __init__(self, settings: RuntimeSettings, log: Callable[[str], None]):
        if not torch.cuda.is_available():
            raise RuntimeError("MoviePilot 运行环境未检测到 CUDA")
        if not settings.animesr_model_path.is_file():
            raise RuntimeError(f"模型文件不存在：{settings.animesr_model_path}")

        from .animesr_arch import AnimeSRV2

        self.device = torch.device(settings.device)
        model = AnimeSRV2(num_feat=64, num_block=(5, 3, 2), netscale=4)
        checkpoint = torch.load(
            settings.animesr_model_path, map_location="cpu", weights_only=True
        )
        model.load_state_dict(checkpoint, strict=True)
        self.model = model.eval().to(self.device, dtype=torch.float32)
        log(
            f"模型已加载：{settings.animesr_model_path.name}，FP32，"
            "三帧时序输入，4x 网络输出后 Lanczos 缩放至 2x"
        )

    def _to_tensor(self, frame: bytes, width: int, height: int) -> torch.Tensor:
        array = np.frombuffer(frame, dtype=np.uint8).reshape(height, width, 3).copy()
        image = (
            torch.from_numpy(array)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(device=self.device, dtype=torch.float32)
            / 255.0
        )
        pad_right = (-width) % 4
        pad_bottom = (-height) % 4
        if pad_right or pad_bottom:
            image = functional.pad(image, (0, pad_right, 0, pad_bottom), mode="replicate")
        return image

    @staticmethod
    def _to_output(out: torch.Tensor, width: int, height: int) -> bytes:
        image = (
            out[:, :, : height * 4, : width * 4]
            .squeeze(0)
            # Keep recurrent feedback in floating-point 0..1 form.
            .clamp(0, 1)
            .mul(255)
            .round()
            .to(dtype=torch.uint8)
            .permute(1, 2, 0)
            .contiguous()
            .cpu()
            .numpy()
        )
        image = cv2.resize(image, (width * 2, height * 2), interpolation=cv2.INTER_LANCZOS4)
        return np.ascontiguousarray(image).tobytes()

    def upscale_sequence(
        self,
        stream,
        frame_size: int,
        width: int,
        height: int,
        cancel_event: threading.Event,
    ):
        first = read_frame(stream, frame_size)
        if not first:
            return
        if len(first) != frame_size:
            raise RuntimeError("FFmpeg 返回了不完整的视频帧")

        prev = self._to_tensor(first, width, height)
        cur = prev
        following = read_frame(stream, frame_size)
        if following and len(following) != frame_size:
            raise RuntimeError("FFmpeg 返回了不完整的视频帧")
        end = not following
        nxt = self._to_tensor(following, width, height) if following else cur
        padded_height, padded_width = cur.shape[-2:]
        state = cur.new_zeros(1, 64, padded_height, padded_width)
        out = cur.new_zeros(1, 3, padded_height * 4, padded_width * 4)

        with torch.inference_mode():
            while True:
                if cancel_event.is_set():
                    raise Cancelled()
                out, state = self.model.cell(torch.cat((prev, cur, nxt), dim=1), out, state)
                yield self._to_output(out, width, height)
                if end:
                    break
                prev, cur = cur, nxt
                following = read_frame(stream, frame_size)
                if following and len(following) != frame_size:
                    raise RuntimeError("FFmpeg 返回了不完整的视频帧")
                if following:
                    nxt = self._to_tensor(following, width, height)
                else:
                    nxt = cur
                    end = True


def terminate(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    except (OSError, ProcessLookupError):
        return


def read_frame(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def upscale_frames(
    runtime: StarSampleRuntime | AnimeSRRuntime,
    stream,
    frame_size: int,
    width: int,
    height: int,
    cancel_event: threading.Event,
):
    if isinstance(runtime, AnimeSRRuntime):
        yield from runtime.upscale_sequence(
            stream, frame_size, width, height, cancel_event
        )
        return
    while True:
        if cancel_event.is_set():
            raise Cancelled()
        frame = read_frame(stream, frame_size)
        if not frame:
            return
        if len(frame) != frame_size:
            raise RuntimeError("FFmpeg 返回了不完整的视频帧")
        yield runtime.upscale(frame, width, height)


def run_pipeline(
    job: dict,
    runtime: StarSampleRuntime | AnimeSRRuntime,
    settings: RuntimeSettings,
    cancel_event: threading.Event,
    progress: Callable[[int, int, float, int | None], None],
    log: Callable[[str], None],
    track_process: Optional[Callable[[subprocess.Popen, bool], None]] = None,
) -> None:
    input_path = Path(job["input_path"])
    output_path = Path(job["output_path"])
    if output_path.exists():
        raise RuntimeError(f"输出已存在，未覆盖：{output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe_video(input_path)
    width, height = info["width"], info["height"]
    output_width, output_height = width * 2, height * 2
    log(
        f"输入：{width}x{height} {info['rate']} fps；"
        f"输出：{output_width}x{output_height}；预计 {info['frames']} 帧"
    )

    temp_video = output_path.parent / f".{job['id']}.video.mkv"
    temp_mux = output_path.parent / f".{job['id']}.mux.mkv"
    for path in (temp_video, temp_mux):
        path.unlink(missing_ok=True)

    decoder = None
    encoder = None
    remux = None
    log_path = settings.log_root / f"{job['id']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    frame_size = width * height * 3
    started = time.monotonic()
    processed = 0

    try:
        with log_path.open("ab", buffering=0) as process_log:
            decoder = subprocess.Popen(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-i",
                    str(input_path),
                    "-map",
                    "0:v:0",
                    "-vsync",
                    "0",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=process_log,
            )
            if track_process:
                track_process(decoder, True)
            encoder = subprocess.Popen(
                encoder_command(
                    temp_video,
                    output_width,
                    output_height,
                    info["rate"],
                    info["sar"],
                    job["cq"],
                    settings.gpu_index,
                ),
                stdin=subprocess.PIPE,
                stderr=process_log,
            )
            if track_process:
                track_process(encoder, True)

            for result in upscale_frames(
                runtime, decoder.stdout, frame_size, width, height, cancel_event
            ):
                try:
                    encoder.stdin.write(result)
                except BrokenPipeError as error:
                    raise RuntimeError("NVENC 编码器提前退出，请查看任务日志") from error
                processed += 1
                if processed == 1 or processed % 10 == 0:
                    elapsed = time.monotonic() - started
                    processing_fps = processed / elapsed
                    remaining = max(0, info["frames"] - processed)
                    eta = round(remaining / processing_fps) if info["frames"] else None
                    progress(processed, info["frames"], processing_fps, eta)

            decoder.stdout.close()
            decoder_return = decoder.wait()
            if track_process:
                track_process(decoder, False)
            encoder.stdin.close()
            encoder_return = encoder.wait()
            if track_process:
                track_process(encoder, False)
            if decoder_return != 0:
                raise RuntimeError(f"FFmpeg 解码失败，退出码 {decoder_return}")
            if encoder_return != 0:
                raise RuntimeError(f"NVENC 编码失败，退出码 {encoder_return}")
            if processed == 0:
                raise RuntimeError("没有从输入文件解码到视频帧")

            if cancel_event.is_set():
                raise Cancelled()
            log("视频推理完成，正在复制音轨、字幕、附件、章节和元数据")
            remux = subprocess.Popen(
                remux_command(
                    temp_video,
                    input_path,
                    temp_mux,
                    probe_subtitle_codecs(input_path),
                ),
                stderr=process_log,
            )
            if track_process:
                track_process(remux, True)
            remux_return = remux.wait()
            if track_process:
                track_process(remux, False)
            if remux_return != 0:
                raise RuntimeError(f"音字幕封装失败，退出码 {remux_return}")
        verify_output(temp_mux, output_width, output_height)
        os.replace(temp_mux, output_path)
        temp_video.unlink(missing_ok=True)
        elapsed = time.monotonic() - started
        progress(processed, processed, processed / elapsed, 0)
        log(f"完成：{output_path}")
    except Exception as error:
        terminate(decoder)
        terminate(encoder)
        terminate(remux)
        temp_video.unlink(missing_ok=True)
        temp_mux.unlink(missing_ok=True)
        if cancel_event.is_set():
            raise Cancelled() from error
        raise
    finally:
        if track_process:
            for process in (decoder, encoder, remux):
                if process is not None:
                    track_process(process, False)
