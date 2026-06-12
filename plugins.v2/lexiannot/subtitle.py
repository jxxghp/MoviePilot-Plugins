import re
import subprocess
from collections import Counter
from typing import Generator, Any, overload

import pymediainfo
from langdetect import detect
from pysubs2 import SSAEvent, SSAFile

from app.log import logger

from .schemas import SubtitleSegment


class SubtitleHelper:

    @staticmethod
    def remove_substring(replacements: list[dict]):
        new_list = []
        replacements.sort(key=lambda x: x["end"] - x["start"], reverse=True)
        for r in replacements:
            if any((r["start"] >= new["start"] and r["end"] <= new["end"]) for new in new_list):
                continue
            new_list.append(r)
        return new_list

    @staticmethod
    def analyze_ass_language(ass_file: SSAFile):

        def _replace_with_spaces(_text):
            """
            使用等长的空格替换文本中的 (xxx) 模式。
            例如："(Hi)" 会被替换成 "    " (4个空格)
            """
            pattern = r"(\([^()]*\)|\[[^\[\]]*\])"
            return re.sub(pattern, lambda match: " " * len(match.group(1)), _text)

        styles = {}
        for style in ass_file.styles:
            styles[style] = {"text": [], "duration": 0, "text_size": 0, "times": 0}
        for dialogue in ass_file:
            style = dialogue.style
            text = _replace_with_spaces(dialogue.plaintext)
            sub_text = text.split("\n")
            if style not in styles or not text:
                continue
            styles[style]["text"].extend(sub_text)
            styles[style]["duration"] += dialogue.duration
            styles[style]["text_size"] += len(text)
            styles[style]["times"] += 1
        style_language_analysis = {}
        for style_name, data in styles.items():
            all_text = " ".join(data["text"])
            if not all_text.strip():
                style_language_analysis[style_name] = None
                continue

            languages = []
            # 对每个文本片段进行语言检测
            for text_fragment in data["text"]:
                try:
                    lang = detect(text_fragment)
                    languages.append(lang)
                except Exception as e:
                    # 无法检测的文本
                    logger.debug(e)

            if languages:
                language_counts = Counter(languages)
                most_common_language = language_counts.most_common(1)[0]
                style_language_analysis[style_name] = {
                    "main_language": most_common_language[0],
                    "proportion": most_common_language[1] / len(languages),
                    "duration": data["duration"],
                    "text_size": data["text_size"],
                    "times": data["times"],
                }
            else:
                style_language_analysis[style_name] = None

        return style_language_analysis

    @staticmethod
    def select_main_style_weighted(analysis: dict[str, Any], known_language: str, weights = None):
        """
        根据语言分析结果和已知的字幕语言，使用加权评分选择主要样式

        :params analysis: `analyze_ass_language` 函数的输出结果
        :params known_language: 已知的字幕语言代码
        :params weights: 各个维度的权重，权重之和应为 1
        :returns: 主要字幕的样式名称，如果没有匹配的样式则返回 None
        """
        if weights is None:
            weights = {"times": 0.5, "text_size": 0.4, "duration": 0.1}
        matching_styles = []
        max_times = max([analysis.get("times", 0) for _, analysis in analysis.items() if analysis] or [0]) or 1
        max_text_size = max([analysis.get("text_size", 0) for _, analysis in analysis.items() if analysis] or [0]) or 1
        max_duration = max([analysis.get("duration", 0) for _, analysis in analysis.items() if analysis] or [0]) or 1
        for style, info in analysis.items():
            if not info:
                continue
            if info.get("main_language") == known_language:
                # 跳过多语言
                if info.get("proportion", 0) < 0.5:
                    continue
                score = 0
                score += info.get("times", 0) * weights.get("times", 0) / max_times
                score += info.get("text_size", 0) * weights.get("text_size", 0) / max_text_size
                score +=  info.get("duration", 0) * weights.get("duration", 0) / max_duration
                matching_styles.append((style, score))

        if not matching_styles:
            return None

        sorted_styles = sorted(matching_styles, key=lambda item: item[1], reverse=True)
        return sorted_styles[0][0]

    @staticmethod
    def set_srt_style(ass: SSAFile) -> SSAFile:
        ass.info["ScaledBorderAndShadow"] = "no"
        play_res_y = int(ass.info["PlayResY"])
        if "Default" in ass.styles:
            ass.styles["Default"].marginv = play_res_y // 16
            ass.styles["Default"].fontname = "Microsoft YaHei"
            ass.styles["Default"].fontsize = play_res_y // 16
        return ass

    @staticmethod
    def __extract_subtitle(
            video_path: str,
            subtitle_stream_index: str,
            ffmpeg_path: str = "ffmpeg",
            sub_format="ass",
    ) -> str | None:
        if sub_format not in ["srt", "ass"]:
            raise ValueError("Invalid subtitle format")
        try:
            map_parameter = f"0:s:{subtitle_stream_index}"
            command = [ffmpeg_path, "-i", video_path, "-map", map_parameter, "-f", sub_format, "-"]
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", check=True
            )
            return result.stdout
        except FileNotFoundError:
            logger.warn(f"错误：找不到视频文件 '{video_path}'")
            return None
        except subprocess.CalledProcessError as e:
            logger.warn(f"错误：提取字幕失败。\n错误信息：{e}")
            logger.warn(
                f"FFmpeg 输出 (stderr):\n{e.stderr.decode('utf-8', errors='ignore')}"
            )
            return None

    @staticmethod
    def extract_subtitles_by_lang(
            video_path: str, lang: str | list = "en", ffmpeg: str = "ffmpeg"
    ) -> list[dict]:
        """
        提取视频文件中的内嵌英文字幕，使用 MediaInfo 查找字幕流。
        """

        def check_lang(track_lang: str) -> bool:
            if isinstance(lang, list):
                return track_lang in lang
            return track_lang == lang

        supported_codec = ["S_TEXT/UTF8", "S_TEXT/ASS", "tx3g"]
        subtitles = []
        try:
            media_info: pymediainfo.MediaInfo = pymediainfo.MediaInfo.parse(video_path)
            for track in media_info.tracks:
                if (
                        track.track_type == "Text"
                        and check_lang(track_lang=track.language)
                        and track.codec_id in supported_codec
                ):
                    subtitle_stream_index = (
                        track.stream_identifier
                    )  # MediaInfo 的 stream_id 从 1 开始，ffmpeg 从 0 开始
                    extracted_subtitle = SubtitleHelper.__extract_subtitle(
                        video_path, subtitle_stream_index, ffmpeg
                    )
                    duration = 0
                    if hasattr(track, "duration"):
                        try:
                            duration = int(float(track.duration))
                        except (ValueError, TypeError):
                            pass
                    if extracted_subtitle:
                        subtitles.append(
                            {
                                "title": track.title or "",
                                "subtitle": extracted_subtitle,
                                "codec_id": track.codec_id,
                                "stream_id": subtitle_stream_index,
                                "duration": duration,
                            }
                        )
            if subtitles:
                # remove outliers with abnormally short duration
                if len(subtitles) > 1:
                    durations = [sub["duration"] for sub in subtitles if sub["duration"] > 0]
                    if durations:
                        avg_duration = sum(durations) / len(durations)
                        subtitles = [
                            sub for sub in subtitles if sub["duration"] >= avg_duration * 0.2
                        ]
            if not subtitles:
                logger.warn("未找到标记为英语的文本字幕流")

        except FileNotFoundError:
            logger.error(f"找不到视频文件 '{video_path}'")
        except subprocess.CalledProcessError as e:
            logger.error(f"错误：提取字幕失败。\n错误信息：{e}")
            logger.error(f"FFmpeg 输出 (stderr):\n{e.stderr}")
        except Exception as e:
            logger.error(f"使用 MediaInfo 提取字幕时发生错误：{e}")
        return subtitles

    @staticmethod
    def replace_by_plaintext_positions(line: SSAEvent, replacements: list[dict]):
        """
        使用 replacements 中的 plaintext 位置信息, 替换 line.text 中的内容。
        :param line: SSAEvent line
        :param replacements: [{'start': int, 'end': int, 'old_text': str, 'new_text': str}, ...]
        """
        text = line.text
        tag_pattern = re.compile(r"{.*?}")  # 匹配 {xxx} 格式控制符
        special_pattern = re.compile(r"\\[Nh]")
        # 构建 plaintext 位置到 text 索引的映射
        mapping = {}  # plaintext_index -> text_index
        p_index = 0  # 当前 plaintext 索引
        t_index = 0  # 当前 text 索引

        while t_index < len(text):
            if text[t_index] == "{":
                # 跳过格式标签
                match = tag_pattern.match(text, t_index)
                if match:
                    t_index = match.end()
                    continue
            elif text[t_index] == "\\":
                match = special_pattern.match(text, t_index)
                if match:
                    t_index = match.end() - 1
                    continue
            # 非格式字符
            mapping[p_index] = t_index
            p_index += 1
            t_index += 1
        replacements = SubtitleHelper.remove_substring(replacements)
        # 按照 mapping 执行替换（倒序替换防止位置错位）
        new_text = text
        for r in sorted(replacements, key=lambda x: x["start"], reverse=True):
            start = mapping.get(r["start"])
            end = mapping.get(r["end"] - 1)
            if start is None or end is None:
                continue
            end += 1
            new_text = new_text[:start] + r["new_text"] + new_text[end:]

        line.text = new_text

    @staticmethod
    def hex_to_rgb(hex_color: str | None) -> tuple[int, ...] | None:
        if not hex_color:
            return None
        pattern = r"^#[0-9a-fA-F]{6}$"
        if re.match(pattern, hex_color) is None:
            return None
        hex_color = hex_color.lstrip("#")  # 去掉前面的 #
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))


class SubtitleProcessor:
    def __init__(self):
        self._events: list[SSAEvent] = []

    def append(self, event: SSAEvent):
        self._events.append(event)

    def segment_generator(self) -> Generator[SubtitleSegment, None, None]:
        for index, event in enumerate(self._events):
            yield SubtitleSegment(
                index=index,
                start_time=event.start,
                end_time=event.end,
                plaintext=event.plaintext,
            )

    @overload
    def __getitem__(self, item: int) -> SSAEvent:
        pass

    @overload
    def __getitem__(self, s: slice) -> list[SSAEvent]:
        pass

    def __getitem__(self, item: Any) -> Any:
        return self._events[item]


def style_text(style: str, text: str) -> str:
    """
    使用指定的样式包装文本。

    :param style: 样式名称
    :param text: 要包装的文本
    :return: 包含样式的文本
    """
    return f"{{\\r{style}}}{text}{{\\r}}"
