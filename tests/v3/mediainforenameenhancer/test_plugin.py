from pathlib import Path

from app.plugins.mediainforenameenhancer import MediaInfoRenameEnhancer


def test_parse_dolby_vision_mediainfo() -> None:
    payload = {
        "media": {"track": [
            {"@type": "Video", "Width": "3840", "Format": "HEVC", "BitDepth": "10",
             "HDR_Format": "Dolby Vision / SMPTE ST 2086", "HDR_Format_Profile": "dvhe.08 / ",
             "HDR_Format_Compatibility": " / HDR10"},
            {"@type": "Audio", "Format": "MLP FBA", "Format_Commercial_IfAny": "Dolby TrueHD with Dolby Atmos", "Channels": "8"},
            {"@type": "Text", "Language": "zh", "Title": "中英双语"},
        ]}
    }
    result = MediaInfoRenameEnhancer._parse_mediainfo(
        payload, Path("Dune.2021.2160p.DoVi.TrueHD.Atmos.x265-b.mkv"), None
    )
    assert result == {
        "miVideoFormat": "2160p", "miHdrFormat": "DoVi.P8+HDR10", "miVideoCodec": "HEVC",
        "miVideoBit": "10bit", "miAudioCodec": "TrueHD 7.1", "miAtmos": "Atmos",
        "miSubtitle": "ZH-EN", "miReleaseGroup": "b",
    }


def test_parse_sdr_mediainfo() -> None:
    payload = {"media": {"track": [
        {"@type": "Video", "Width": "3840", "Format": "HEVC", "BitDepth": "10"},
        {"@type": "Audio", "Format": "E-AC-3", "Format_Commercial_IfAny": "Dolby Digital Plus with Dolby Atmos", "Channels": "6"},
        {"@type": "Text", "Language": "zh", "Title": "中英特效字幕"},
    ]}}
    result = MediaInfoRenameEnhancer._parse_mediainfo(
        payload, Path("Dune.2021.2160p.SDR.H265.Atmos.DDP5.1.CHS-ENG.BOBO.mkv"), "ENG.BOBO"
    )
    assert result["miHdrFormat"] == "SDR"
    assert result["miAudioCodec"] == "DDP 5.1"
    assert result["miAtmos"] == "Atmos"
    assert result["miSubtitle"] == "ZH-EN"
    assert result["miReleaseGroup"] == "BOBO"
