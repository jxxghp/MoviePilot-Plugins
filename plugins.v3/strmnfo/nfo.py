# -*- coding: utf-8 -*-
"""
从 .strm 文件名里的技术标签生成 Kodi 格式的 .strm.nfo 伴生文件，
供 Emby 插件 STRM Probe NFO 读取入库，全程不访问云盘、不下载任何文件，
只读本地文件名。

本模块是从独立脚本 strm_nfo_gen.py v3.0 移植而来，解析规则完全一致：
  * 音频多轨解析：文件名里出现几个音频编码就写几条 <audio>，
    每条各自带编码 + 声道（如 "TrueHD 7.1 Atmos + AC3 5.1" 生成两条）。
  * DDP 全写法统一认成 eac3：DDP5.1 / DDP 5.1 / DDP.5.1 / DDP-5.1 /
    DDP_5.1 / DD+5.1 / DD+ 5.1 / EAC3 5.1 / EAC35.1 / Dolby Digital Plus。
  * 码率：文件名里的 "22Mbps" / "22.74Mbps" 写入视频 <bitrate>（换算成 bps）。
  * 码深 / 配置 / 色域（10bit / Main 10 / bt2020 等）只做识别，
    不写入 nfo——插件读的 nfo 格式里没有这些字段，写进去也不会被读取。
  * 分辨率：文件名给的是标称值（如 2160p -> 3840x2160），真实探测才会给
    精确裁切值（如 3832x1600），这是文件名方式本身的上限，无法再准。
  * DV 优先于 HDR；音轨语言只认明确标记；DTS-HD MA -> dtshd；
    Atmos / DTS:X 只做标记（nfo 注释），不改编码本身。

配合插件：https://github.com/oxios0x00/emby-strm-probe-nfo
  要求 Emby Server 4.10.1.0 或更高（.NET 8）。

识别的文件名标签（标准发行版命名）：
  分辨率：8K / 4K / UHD / 2160p / 1080p / FHD / 1080i / 720p / 720i / 480p
  视频编码：AV1 / HEVC / H.265 / H.264 / AVC / x264 / x265 / VP9 / VC-1
  HDR：Dolby Vision / DV / DoVi / HDR10+ / HDR10 / HLG / SDR
  音频编码：TrueHD / DTS-HD MA / DTS-HD HR / DTS / DTS:X /
            EAC3 / DDP / DD+ / AC3 / AAC / FLAC / MP3 / Opus（可多轨）
  音效：Dolby Atmos / DTS:X（只做标记，不改编码）
  声道：2.0 / 5.1 / 7.1（接受 DDP5.1 这种无分隔写法）
  音轨语言：国语 / 普通话 / 粤语 / 英语 / 日语 / 韩语（明确标记才写）
  帧率：23.976 / 24 / 25 / 30 / 50 / 60 fps
  码率：22Mbps / 22.74Mbps（写入视频 bitrate）
  字幕：中字 / 简体 / 繁体 / 英字 / 双语
"""

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------- 映射表 ----------------

RESOLUTIONS = {
    "2160p": (3840, 2160),
    "1080p": (1920, 1080),
    "1080i": (1920, 1080),
    "720p": (1280, 720),
    "720i": (1280, 720),
    "480p": (720, 480),
    "576p": (720, 576),
    "4k": (3840, 2160),
    "8k": (7680, 4320),
    "uhd": (3840, 2160),
    "fhd": (1920, 1080),
}

VIDEO_CODECS = [
    (r"h\.?265|hevc|x265", "hevc"),
    (r"h\.?264|avc|x264", "h264"),
    (r"\bav1\b", "av1"),
    (r"\bvp9\b", "vp9"),
    (r"mpeg-?2", "mpeg2"),
    (r"vc-?1", "vc1"),
]

# 音频编码：组合正则（顺序重要，先匹配更具体的），以及匹配文本到标准名的映射。
AUDIO_CODEC_RE = re.compile(
    r"truehd|true-hd"
    r"|dts-?hd[\s._-]*ma|dtshdma"
    r"|dts-?hd[\s._-]*hr"
    r"|dts-?hd"
    r"|eac3|ddp|dd\+|dolby[\s._-]*digital[\s._-]*plus|dolby\+"
    r"|dts(?![\s._\-:]*x(?![a-z0-9]))"
    r"|ac3|dolby[\s._-]*digital"
    r"|aac|flac|mp3|opus",
    re.IGNORECASE,
)

AUDIO_CODEC_MAP = [
    (r"truehd|true-hd", "truehd"),
    (r"dts-?hd[\s._-]*ma|dtshdma", "dtshd"),   # DTS-HD Master Audio
    (r"dts-?hd[\s._-]*hr", "dtshd"),           # DTS-HD High Resolution
    (r"dts-?hd", "dtshd"),                     # DTS-HD（未注明 MA/HR）
    (r"eac3|ddp|dd\+|dolby[\s._-]*digital[\s._-]*plus|dolby\+", "eac3"),
    (r"dts", "dts"),
    (r"ac3|dolby[\s._-]*digital", "ac3"),
    (r"aac", "aac"),
    (r"flac", "flac"),
    (r"mp3", "mp3"),
    (r"opus", "opus"),
]

# 声道：5.1 -> 6，7.1 -> 8，2.0 -> 2。
# 数字前不要求分隔符（修 DDP5.1），但前后不能紧贴其他数字，
# 避免把日期（2024.11）或版本号误判为声道。
CHANNEL_RE = re.compile(r"(?<![0-9])([1-9])\.([01])(?![0-9])")


def _codec_name(matched_text: str):
    low = matched_text.lower()
    for pat, name in AUDIO_CODEC_MAP:
        if re.search(pat, low):
            return name
    return None


def parse_audio_tracks(low: str) -> list:
    """多轨解析：找出文件名里所有音频编码，各自配上附近的声道。

    每条音轨 = {"codec", "channels", "atmos", "dtsx"}。
    声道优先找编码后面、到下一个编码之间的那段；找不到再往编码前面找一小段。
    Atmos / DTS:X 是对象音效标记，挂在离它最近的前一个编码上，不单独成轨；
    DTS:X 本身意味着底层是 DTS-HD MA，所以只有 "DTS:X" 而没有写编码时，
    默认补一条 dtshd 音轨。
    """
    matches = list(AUDIO_CODEC_RE.finditer(low))
    atmos_pos = [m.start() for m in re.finditer(r"atmos", low)]
    dtsx_pos = [m.start() for m in re.finditer(r"dts[\s._\-:]*x(?![a-z0-9])", low)]
    tracks = []
    for i, m in enumerate(matches):
        codec = _codec_name(m.group(0))
        if codec is None:
            continue
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(low)
        seg = low[m.end():seg_end]
        channels = None
        cm = CHANNEL_RE.search(seg)
        if cm:
            channels = int(cm.group(1)) + (1 if cm.group(2) == "1" else 0)
        else:
            prev_end = matches[i - 1].end() if i > 0 else 0
            cm2 = CHANNEL_RE.search(low[prev_end:m.start()])
            if cm2:
                channels = int(cm2.group(1)) + (1 if cm2.group(2) == "1" else 0)
        atmos = any(m.start() <= p < seg_end for p in atmos_pos)
        dtsx = any(m.start() <= p < seg_end for p in dtsx_pos)
        tracks.append(
            {"codec": codec, "channels": channels, "atmos": atmos, "dtsx": dtsx}
        )
    if not tracks and dtsx_pos:
        # 只有 "DTS:X" 没写编码：底层一定是 DTS-HD MA，补一条 dtshd 音轨
        p = dtsx_pos[0]
        cm = CHANNEL_RE.search(low[p:])
        channels = None
        if cm:
            channels = int(cm.group(1)) + (1 if cm.group(2) == "1" else 0)
        tracks.append(
            {"codec": "dtshd", "channels": channels, "atmos": False, "dtsx": True}
        )
    return tracks


# ---------------- 解析 ----------------


def parse_filename(stem: str) -> dict:
    """从 .strm 文件名（不含扩展名）里解析技术标签，返回 nfo 字段字典。"""
    name = stem
    low = name.lower()
    info: dict = {}

    # 分辨率：先找 3840x2160 / 3832x1600 这种显式宽高，再找 2160p / 4K / UHD
    m = re.search(r"(\d{3,4})x(\d{3,4})", name)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    else:
        for tag, (w, h) in RESOLUTIONS.items():
            if re.search(r"\b" + re.escape(tag) + r"\b", low):
                info["width"], info["height"] = w, h
                break

    # 视频编码
    for pat, codec in VIDEO_CODECS:
        if re.search(pat, low):
            info["video_codec"] = codec
            break

    # HDR：Dolby Vision 最优先（独立 DV / DoVi / Dolby Vision 都算），
    # 再依次是 HDR10+、HDR10、HLG、裸 HDR（按 HDR10 计）、SDR。
    # 注意 "DV.HDR" 这种组合是 DV 兼容 HDR，要认成 dolbyvision 而不是 hdr10。
    if re.search(r"dolby[\s._-]*vision|dovi|(?<![a-z0-9])dv(?![a-z0-9])", low):
        info["hdr"] = "dolbyvision"
    elif re.search(r"hdr10\s*\+|hdr10[\s._-]*plus", low):
        info["hdr"] = "hdr10plus"
    elif re.search(r"hdr10", low):
        info["hdr"] = "hdr10"
    elif re.search(r"\bhlg\b", low):
        info["hdr"] = "hlg"
    elif re.search(r"\bhdr\b", low):
        info["hdr"] = "hdr10"
    elif re.search(r"\bsdr\b", low):
        info["hdr"] = "sdr"

    # 帧率：23.976fps / 24fps / 25fps / 30fps / 50fps / 60fps
    # 先去掉杜比视界规格标记（P5/P7/P8），避免 "DV.P5.60fps" 被误读成 5.6fps
    # （P5 是 DV Profile 5，60fps 才是帧率；只影响帧率/音频解析这一步，
    #  其他解析仍用原 low，HDR 识别不受影响）。
    fps_src = re.sub(r"(?<![a-z0-9])p[578](?![a-z0-9])", "", low)
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", fps_src)
    if m:
        info["framerate"] = float(m.group(1))

    # 码率：22Mbps / 22.74Mbps -> 视频 bitrate（bps）
    m = re.search(r"(\d+(?:\.\d+)?)\s*mbps", low)
    if m:
        info["video_bitrate"] = int(float(m.group(1)) * 1_000_000)

    # 码深 / 配置 / 色域：只识别，不写入 nfo
    # （插件读的 nfo 格式没有这些字段，写进去也不会被读取）。
    m = re.search(r"(\d+)\s*-?\s*bit", low)
    if m:
        info["bitdepth"] = int(m.group(1))
    m = re.search(r"\b(main|high)\s*10\b", low)
    if m:
        info["profile"] = m.group(0).title().replace(" ", " ")
        info.setdefault("bitdepth", 10)
    if re.search(r"bt[\s._-]*2020|rec[\s._-]*2020", low):
        info["color"] = "bt2020"
    elif re.search(r"bt[\s._-]*709|rec[\s._-]*709", low):
        info["color"] = "bt709"

    # 音频：多轨解析（用去掉 DV 规格标记的 fps_src，避免 "P5.60" 被误读成 6.0 声道）
    tracks = parse_audio_tracks(fps_src)
    if tracks:
        info["audio_tracks"] = tracks

    # 音轨语言：只认明确标记，没有就不写。
    # 先把字幕词组剔除，避免“英文字幕 / 日语字幕”被误判为音轨语言。
    lang_src = re.sub(
        r"中文字幕|英文字幕|日文字幕|韩文字幕|中英字幕|简体字幕|繁体字幕"
        r"|双语字幕|中字|英字",
        "",
        name,
    )
    lang_low = lang_src.lower()
    if re.search(r"国语|普通话|中配|中文配音|国粤", lang_src):
        info["audio_lang"] = "chi"
    elif re.search(r"粤语|粤語", lang_src):
        info["audio_lang"] = "yue"
    elif re.search(r"英语|英文|english", lang_low):
        info["audio_lang"] = "eng"
    elif re.search(r"日语|日文|japanese", lang_low):
        info["audio_lang"] = "jpn"
    elif re.search(r"韩语|韩文|korean", lang_low):
        info["audio_lang"] = "kor"

    # 时长：45分钟 / 90min / 01:23:45
    m = re.search(r"(\d+)\s*(?:分钟|min)", name)
    if m:
        info["duration"] = int(m.group(1)) * 60.0
    else:
        m = re.search(r"(\d{1,2}):(\d{2}):(\d{2})", name)
        if m:
            info["duration"] = (
                int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            )

    # 字幕：可多条（双语/中英同时写 chi + eng）
    chi_sub = any(
        k in name for k in ("中字", "简体", "繁体", "繁體", "中文字幕")
    )
    eng_sub = any(k in name for k in ("英字", "英文字幕"))
    if any(k in name for k in ("中英", "双语")):
        chi_sub = True
        eng_sub = True
    subs = []
    if chi_sub:
        subs.append(("subrip", "chi"))
    if eng_sub:
        subs.append(("subrip", "eng"))
    if subs:
        info["subtitles"] = subs

    return info


def is_episode(stem: str) -> bool:
    """判断是不是剧集（决定 nfo 根元素用 episodedetails 还是 movie）。"""
    low = stem.lower()
    return bool(
        re.search(r"\bs\d{1,2}e\d{1,2}\b", low)
        or re.search(r"\be\d{1,2}\b", low)
        or re.search(r"第\s*\d+\s*[集話话]", stem)
    )


def build_nfo(info: dict, episode: bool) -> str:
    """按 Kodi streamdetails 格式生成 .strm.nfo 内容（STRM Probe NFO 插件读取此格式）。"""
    root_tag = "episodedetails" if episode else "movie"
    root = ET.Element(root_tag)
    fileinfo = ET.SubElement(root, "fileinfo")
    sd = ET.SubElement(fileinfo, "streamdetails")

    video = ET.SubElement(sd, "video")
    if info.get("video_codec"):
        ET.SubElement(video, "codec").text = info["video_codec"]
    if info.get("width"):
        ET.SubElement(video, "width").text = str(info["width"])
    if info.get("height"):
        ET.SubElement(video, "height").text = str(info["height"])
    if info.get("video_bitrate"):
        ET.SubElement(video, "bitrate").text = str(info["video_bitrate"])
    if info.get("framerate"):
        ET.SubElement(video, "framerate").text = str(info["framerate"])
    if info.get("duration"):
        ET.SubElement(video, "durationinseconds").text = str(info["duration"])
    if info.get("hdr") and info["hdr"] != "sdr":
        # SDR 不写 hdrtype，插件默认就是 SDR
        ET.SubElement(video, "hdrtype").text = info["hdr"]

    for track in info.get("audio_tracks", []):
        audio = ET.SubElement(sd, "audio")
        ET.SubElement(audio, "codec").text = track["codec"]
        if track.get("channels"):
            ET.SubElement(audio, "channels").text = str(track["channels"])
        if info.get("audio_lang"):
            ET.SubElement(audio, "language").text = info["audio_lang"]
        # Atmos / DTS:X：插件读的 nfo 格式没有这两个字段，留注释保住信息，
        # 不改编码本身，避免影响 Emby 的直通/转码判断。
        note = []
        if track.get("atmos"):
            note.append("Dolby Atmos")
        if track.get("dtsx"):
            note.append("DTS:X")
        if note:
            audio.append(ET.Comment(" " + " + ".join(note) + " "))

    for codec, lang in info.get("subtitles", []):
        sub = ET.SubElement(sd, "subtitle")
        ET.SubElement(sub, "codec").text = codec
        ET.SubElement(sub, "language").text = lang

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# ---------------- 供插件调用的入口 ----------------


def generate_nfo_for_strm(strm_path, force: bool = False):
    """给一个 .strm 文件生成同名的 .strm.nfo。

    :param strm_path: .strm 文件路径（可以是 MoviePilot 生成的软链接）。
    :param force: True 时覆盖已有的 .strm.nfo；False 时已有则跳过。
    :return: (status, info)，status 取值：
        "generated" —— 已生成；
        "skipped" —— 已有 nfo 且未开启覆盖；
        "unparsed" —— 文件名里没有分辨率/编码/HDR 标签，无法生成；
        "error" —— 写入失败，info 为错误信息。
      info 为解析出的字段字典（generated 时）或附加说明。
    """
    strm = Path(strm_path)
    nfo = strm.with_suffix(".strm.nfo")
    if nfo.exists() and not force:
        return "skipped", {}
    # 先按 .strm 自己的文件名解析；如果是 MoviePilot 的软链接且名字里
    # 没有技术标签，就跟到软链接目标（openstrm 的原文件）用目标文件名解析。
    # nfo 始终写在软链接旁边（Emby 里条目的路径就是软链接的路径）。
    info = parse_filename(strm.stem)
    if strm.is_symlink() and not any(
        k in info for k in ("width", "video_codec", "hdr")
    ):
        try:
            target = strm.resolve()
            if target != strm:
                info = parse_filename(target.stem)
        except OSError:
            pass
    # 至少解析出分辨率 / 编码 / HDR 其中一项才生成
    if not any(k in info for k in ("width", "video_codec", "hdr")):
        return "unparsed", info
    try:
        content = build_nfo(info, is_episode(strm.stem))
        # 原子写入：先写同目录临时文件再 rename，避免 Emby 在写入中途
        # 读到半个 nfo；force 覆盖时也不会出现新旧内容混写。
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=str(nfo.parent),
                prefix=nfo.name + ".", suffix=".tmp", delete=False,
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(content)
            os.replace(tmp_path, nfo)
            tmp_path = None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except OSError as err:
        return "error", {"error": str(err)}
    return "generated", info
