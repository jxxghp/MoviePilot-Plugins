import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType


class MediaInfoRenameEnhancer(_PluginBase):
    """在整理文件名渲染前读取 MediaInfo 技术元数据并注入模板变量。"""

    plugin_name = "MediaInfo命名增强"
    plugin_desc = "为整理模板提供HDR、编码、音频、Atmos、字幕及发布组兜底字段"
    plugin_version = "1.0.0"
    plugin_author = "annanygy"
    plugin_config_prefix = "mediainforenameenhancer_"
    plugin_order = 20
    auth_level = 1

    _enabled = False
    _mediainfo_path = ""

    def init_plugin(self, config: dict = None) -> None:
        config = config or {}
        self._enabled = config.get("enabled", False)
        self._mediainfo_path = config.get("mediainfo_path") or shutil.which("mediainfo") or ""

    def get_state(self) -> bool:
        return self._enabled and bool(self._mediainfo_path)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 9},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "mediainfo_path",
                                            "label": "MediaInfo命令行路径",
                                            "placeholder": "mediainfo",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": (
                                "注入 miVideoFormat、miHdrFormat、miVideoCodec、"
                                "miVideoBit、miAudioCodec、miAtmos、miSubtitle、"
                                "miReleaseGroup 模板变量。只读取媒体头信息，不修改源文件。"
                            ),
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "mediainfo_path": shutil.which("mediainfo") or "mediainfo",
        }

    def get_page(self) -> Optional[List[dict]]:
        return None

    def stop_service(self) -> None:
        return None

    @eventmanager.register(ChainEventType.TransferRenameBuild)
    def on_transfer_rename_build(self, event: Event) -> None:
        if not self.get_state() or not event or not event.event_data:
            return

        event_data = event.event_data
        source_path = event_data.source_path
        source_item = event_data.source_item
        if not source_path:
            return
        if source_item and source_item.storage not in (None, "local"):
            return

        media_path = Path(source_path)
        if not media_path.is_file():
            return

        fields = self._probe(media_path, event_data.rename_dict.get("releaseGroup"))
        if fields:
            event_data.rename_dict.update(fields)

    def _probe(self, media_path: Path, release_group: Optional[str]) -> Dict[str, str]:
        try:
            completed = subprocess.run(
                [self._mediainfo_path, "--Output=JSON", "--Full", "--", str(media_path)],
                capture_output=True,
                check=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as err:
            logger.warning(f"MediaInfo命名增强读取失败：{media_path.name} - {str(err)}")
            return {}

        return self._parse_mediainfo(payload, media_path, release_group)

    @classmethod
    def _parse_mediainfo(
        cls,
        payload: Dict[str, Any],
        media_path: Path,
        release_group: Optional[str],
    ) -> Dict[str, str]:
        tracks = payload.get("media", {}).get("track", [])
        video_tracks = [track for track in tracks if track.get("@type") == "Video"]
        audio_tracks = [track for track in tracks if track.get("@type") == "Audio"]
        text_tracks = [track for track in tracks if track.get("@type") == "Text"]

        video = video_tracks[0] if video_tracks else {}
        audio = cls._preferred_audio_track(audio_tracks)
        audio_codec, atmos = cls._audio_summary(audio)
        fields = {
            "miVideoFormat": cls._resolution(video),
            "miHdrFormat": cls._hdr_format(video),
            "miVideoCodec": cls._video_codec(video),
            "miVideoBit": cls._video_bit(video),
            "miAudioCodec": audio_codec,
            "miAtmos": "Atmos" if atmos else "",
            "miSubtitle": cls._subtitle_summary(text_tracks),
            "miReleaseGroup": cls._release_group(media_path) or release_group,
        }
        return {key: value for key, value in fields.items() if value}

    @staticmethod
    def _digits(value: Any) -> Optional[int]:
        match = re.search(r"\d+", str(value or "").replace(" ", ""))
        return int(match.group()) if match else None

    @classmethod
    def _resolution(cls, video: Dict[str, Any]) -> str:
        width = cls._digits(video.get("Width")) or 0
        if width >= 7000:
            return "4320p"
        if width >= 3500:
            return "2160p"
        if width >= 1800:
            return "1080p"
        if width >= 1200:
            return "720p"
        return ""

    @staticmethod
    def _video_codec(video: Dict[str, Any]) -> str:
        codec = str(video.get("Format") or "").upper()
        return {"HEVC": "HEVC", "AVC": "AVC", "AV1": "AV1", "VP9": "VP9"}.get(codec, codec)

    @staticmethod
    def _video_bit(video: Dict[str, Any]) -> str:
        bit_depth = re.search(r"\d+", str(video.get("BitDepth") or ""))
        return f"{bit_depth.group()}bit" if bit_depth else ""

    @staticmethod
    def _hdr_format(video: Dict[str, Any]) -> str:
        raw = " ".join(
            str(video.get(key) or "")
            for key in (
                "HDR_Format",
                "HDR_Format_Profile",
                "HDR_Format_Compatibility",
                "HDR_Format_String",
            )
        )
        upper = raw.upper()
        if "DOLBY VISION" in upper or "DVHE." in upper:
            profile = re.search(r"DVHE\.0?(\d+)", upper)
            label = f"DoVi.P{int(profile.group(1))}" if profile else "DoVi"
            if "HDR10+" in upper or "HDR10PLUS" in upper:
                return f"{label}+HDR10+"
            if "HDR10" in upper or "ST 2086" in upper:
                return f"{label}+HDR10"
            return label
        if "HDR10+" in upper or "HDR10PLUS" in upper or "ST 2094" in upper:
            return "HDR10+"
        if "HLG" in upper:
            return "HLG"
        if "HDR10" in upper or "ST 2086" in upper:
            return "HDR10"
        return "SDR"

    @staticmethod
    def _preferred_audio_track(audio_tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
        for track in audio_tracks:
            if str(track.get("Default") or "").lower() == "yes":
                return track
        return audio_tracks[0] if audio_tracks else {}

    @classmethod
    def _audio_summary(cls, audio: Dict[str, Any]) -> Tuple[str, bool]:
        raw = " ".join(
            str(audio.get(key) or "")
            for key in ("Format", "Format_Commercial_IfAny", "Title", "Format_AdditionalFeatures")
        )
        upper = raw.upper()
        base_format = str(audio.get("Format") or "").upper()
        if "TRUEHD" in upper or base_format == "MLP FBA":
            codec = "TrueHD"
        elif "DTS-HD MASTER" in upper:
            codec = "DTS-HD MA"
        elif base_format == "E-AC-3":
            codec = "DDP"
        elif base_format == "AC-3":
            codec = "DD"
        else:
            codec = base_format

        channels = cls._digits(audio.get("Channels"))
        channel_label = {8: "7.1", 6: "5.1", 2: "2.0", 1: "1.0"}.get(channels, "")
        summary = " ".join(part for part in (codec, channel_label) if part)
        return summary, "ATMOS" in upper

    @classmethod
    def _subtitle_summary(cls, text_tracks: List[Dict[str, Any]]) -> str:
        languages = set()
        for track in text_tracks:
            language = cls._normalize_language(track.get("Language"))
            if language:
                languages.add(language)
            title = str(track.get("Title") or "")
            if re.search(r"中英|简英|繁英", title):
                languages.update({"ZH", "EN"})

        priority = {"ZH": 0, "EN": 1, "JA": 2, "KO": 3, "ES": 4}
        ordered = sorted(languages, key=lambda item: (priority.get(item, 99), item))
        preferred = [language for language in ordered if language in {"ZH", "EN"}]
        return "-".join(preferred or ordered[:2])

    @staticmethod
    def _normalize_language(language: Any) -> str:
        code = str(language or "").split("-")[0].lower()
        return {
            "zh": "ZH", "zho": "ZH", "chi": "ZH", "en": "EN", "eng": "EN",
            "ja": "JA", "jpn": "JA", "ko": "KO", "kor": "KO", "es": "ES", "spa": "ES",
        }.get(code, code.upper() if code and code != "und" else "")

    @staticmethod
    def _release_group(media_path: Path) -> str:
        stem = media_path.stem
        last_token = stem.rsplit(".", 1)[-1]
        excluded = {"HEVC", "H265", "X265", "AVC", "H264", "X264", "MKV"}
        if re.fullmatch(r"[A-Z][A-Z0-9]{1,15}", last_token) and last_token not in excluded:
            return last_token

        hyphen_match = re.search(r"-([A-Za-z0-9][A-Za-z0-9._]{0,20})$", stem)
        if hyphen_match:
            return hyphen_match.group(1)
        return ""
