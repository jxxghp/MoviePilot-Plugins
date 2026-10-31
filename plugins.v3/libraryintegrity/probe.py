"""本地媒体信息读取：调用 ffprobe 或 mediainfo 获取本地视频的技术参数，并按文件大小与修改时间增量缓存。

只处理本地视频文件，strm 指向的远程地址不会被读取。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.sdk.logging import logger

from .checks import normalize_audio, normalize_bit_depth, normalize_codec, parse_int, resolution_bucket

# 缓存条目超过该时长未被使用时在保存时清理
PRUNE_SECONDS = 90 * 86400

ProbeFields = dict[str, Optional[str]]


def _ffprobe_hdr(video: dict) -> Optional[str]:
    """从 ffprobe 视频流判断 HDR 类型；能读取到流信息时，没有 HDR 标记即为 SDR。"""
    for side in video.get("side_data_list") or []:
        side_type = str((side or {}).get("side_data_type") or "").lower()
        if "dovi" in side_type or "dolby vision" in side_type:
            return "DV"
        if "2094-40" in side_type or "hdr10+" in side_type:
            return "HDR10+"
    transfer = str(video.get("color_transfer") or "").lower()
    if transfer == "smpte2084":
        return "HDR10"
    if transfer == "arib-std-b67":
        return "HLG"
    return "SDR"


def parse_ffprobe(payload: dict) -> ProbeFields:
    """解析 ffprobe -show_streams 的 JSON 输出。"""
    streams = [s for s in payload.get("streams") or [] if isinstance(s, dict)]
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
        None,
    )
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    audio = next((s for s in audios if (s.get("disposition") or {}).get("default")), audios[0] if audios else None)
    fields: ProbeFields = {}
    if video:
        fields["resolution"] = resolution_bucket(parse_int(video.get("width")), parse_int(video.get("height")))
        fields["video_codec"] = normalize_codec(video.get("codec_name"))
        fields["hdr"] = _ffprobe_hdr(video)
        depth = video.get("bits_per_raw_sample")
        if not parse_int(depth):
            pix_fmt = str(video.get("pix_fmt") or "")
            depth = "12" if "12" in pix_fmt else "10" if "10" in pix_fmt else "8" if pix_fmt else None
        fields["bit_depth"] = normalize_bit_depth(depth)
    if audio:
        fields["audio_codec"] = normalize_audio(audio.get("codec_name"))
    return fields


def _mediainfo_hdr(video: dict) -> Optional[str]:
    """从 mediainfo 视频轨判断 HDR 类型。"""
    text = " ".join(str(video.get(key) or "") for key in ("HDR_Format", "HDR_Format_Compatibility")).lower()
    if "dolby vision" in text:
        return "DV"
    if "2094" in text or "hdr10+" in text:
        return "HDR10+"
    if "2086" in text or "hdr10" in text:
        return "HDR10"
    if "hlg" in text or "arib" in text:
        return "HLG"
    transfer = str(video.get("transfer_characteristics") or "").lower()
    if "pq" in transfer or "2084" in transfer:
        return "HDR10"
    return "SDR"


def parse_mediainfo(payload: dict) -> ProbeFields:
    """解析 mediainfo --Output=JSON 的输出。"""
    tracks = [t for t in ((payload.get("media") or {}).get("track") or []) if isinstance(t, dict)]
    video = next((t for t in tracks if t.get("@type") == "Video"), None)
    audios = [t for t in tracks if t.get("@type") == "Audio"]
    audio = next((t for t in audios if str(t.get("Default") or "").lower() == "yes"), audios[0] if audios else None)
    fields: ProbeFields = {}
    if video:
        fields["resolution"] = resolution_bucket(parse_int(video.get("Width")), parse_int(video.get("Height")))
        fields["video_codec"] = normalize_codec(video.get("Format"))
        fields["hdr"] = _mediainfo_hdr(video)
        fields["bit_depth"] = normalize_bit_depth(video.get("BitDepth"))
    if audio:
        audio_format = str(audio.get("Format") or "")
        fields["audio_codec"] = "TrueHD" if audio_format.upper().startswith("MLP") else normalize_audio(audio_format)
    return fields


def find_probe_binary(configured: str = "") -> tuple[str, str]:
    """返回 (工具类型, 可执行文件路径)：优先使用配置路径，其次 ffprobe，再次 mediainfo；都没有时返回空。"""
    candidates = [configured] if configured else []
    candidates += ["ffprobe", "mediainfo"]
    for candidate in candidates:
        path = shutil.which(candidate) if candidate else None
        if path:
            kind = "mediainfo" if "mediainfo" in Path(path).name.lower() else "ffprobe"
            return kind, path
    return "", ""


class MediaProbe:
    """按需读取本地视频技术参数；结果按 (大小, 修改时间) 缓存，每轮新读取的文件数量受上限约束。"""

    def __init__(
        self,
        cache_file: Path,
        binary: str,
        kind: str,
        max_new: int = 300,
        timeout: int = 30,
        runner: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """加载缓存并记录读取工具。"""
        self._cache_file = cache_file
        self._binary = binary
        self._kind = kind
        self._max_new = max(0, max_new)
        self._timeout = timeout
        self._runner = runner
        self._clock = clock
        self._dirty = False
        self.probed = 0
        self.skipped = 0
        self._cache: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        """读取缓存文件，损坏时重建。"""
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as err:
            logger.warning(f"影视库完整性检查：媒体信息缓存无法读取，已重建：{err}")
            return {}

    def _command(self, path: Path) -> list[str]:
        """生成读取命令；ffprobe 使用 file: 前缀，避免文件名被当作参数或其他协议。"""
        if self._kind == "mediainfo":
            return [self._binary, "--Output=JSON", "--", str(path)]
        return [self._binary, "-v", "error", "-print_format", "json", "-show_streams", f"file:{path}"]

    def probe(self, path: Path) -> ProbeFields:
        """返回文件的技术参数；超过本轮新读取上限、读取失败或文件不存在时返回空结果。"""
        try:
            stat = path.stat()
        except OSError:
            return {}
        key = str(path)
        cached = self._cache.get(key)
        if cached and cached.get("size") == stat.st_size and cached.get("mtime") == int(stat.st_mtime):
            cached["used_at"] = self._clock()
            self._dirty = True
            return dict(cached.get("fields") or {})
        if self.probed >= self._max_new:
            self.skipped += 1
            return {}
        self.probed += 1
        fields: ProbeFields = {}
        try:
            completed = self._runner(
                self._command(path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout:
                payload = json.loads(completed.stdout)
                fields = parse_mediainfo(payload) if self._kind == "mediainfo" else parse_ffprobe(payload)
        except (OSError, subprocess.SubprocessError, ValueError) as err:
            logger.debug(f"影视库完整性检查：读取媒体信息失败 {path}：{err}")
        # 读取失败也记录，避免每轮重复尝试同一个损坏文件；文件变化后会重新读取
        self._cache[key] = {
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "fields": fields,
            "used_at": self._clock(),
        }
        self._dirty = True
        return dict(fields)

    def save(self) -> None:
        """清理长期未使用的条目并写回缓存文件。"""
        if not self._dirty:
            return
        now = self._clock()
        self._cache = {k: v for k, v in self._cache.items() if now - float(v.get("used_at") or 0) < PRUNE_SECONDS}
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._cache_file)
            self._dirty = False
        except OSError as err:
            logger.warning(f"影视库完整性检查：媒体信息缓存保存失败：{err}")
