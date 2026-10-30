"""影视库完整性检查：本地目录数据源与媒体信息读取测试。"""

import json
import re
import subprocess
import threading
from datetime import date

from app.plugins.libraryintegrity.local import (
    LocalSource,
    read_strm_url,
    season_from_dir,
    title_and_year,
    tmdb_from_name,
)
from app.plugins.libraryintegrity.models import IssueType
from app.plugins.libraryintegrity.probe import MediaProbe, parse_ffprobe, parse_mediainfo
from app.plugins.libraryintegrity.scanner import LibraryScanner, ScanOptions

_SE = re.compile(r"S(\d+)E(\d+)(?:-E(\d+))?", re.IGNORECASE)


def _numbers(stem):
    """文件名解析替身：识别 SxxEyy 与标题年份。"""
    match = _SE.search(stem)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3)) if match.group(3) else None, "", ""
    title, year = title_and_year(stem)
    return None, None, None, title, year


def _touch(path, text=""):
    """创建文件及其父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_directory_name_helpers():
    """季目录、TMDB 标记、标题年份解析。"""
    assert season_from_dir("Season 2") == 2
    assert season_from_dir("S03") == 3
    assert season_from_dir("第十二季") == 12
    assert season_from_dir("Specials") == 0
    assert season_from_dir("剧名") is None
    assert tmdb_from_name("黑镜 (2011) {tmdbid=42009}") == 42009
    assert tmdb_from_name("Show [tmdb-123]") == 123
    assert tmdb_from_name("Show (2011)") is None
    assert title_and_year("黑镜 (2011) {tmdbid=42009}") == ("黑镜", "2011")


def test_read_strm_url_takes_first_line_and_limits_size(tmp_path):
    """读取 strm 第一行地址，超大文件不读取。"""
    assert read_strm_url(_touch(tmp_path / "a.strm", "\n http://x/a.mkv \nignored")) == "http://x/a.mkv"
    assert read_strm_url(_touch(tmp_path / "b.strm", "x" * 5000)) == ""
    assert read_strm_url(tmp_path / "missing.strm") == ""


def test_local_source_groups_series_and_movies(tmp_path):
    """按剧集目录归组单集（含季目录、strm 与多版本），按目录与标题归组电影，身份依次取 NFO、目录标记与整理记录。"""
    tv = tmp_path / "电视剧"
    show = tv / "剧A (2020)"
    _touch(show / "tvshow.nfo", "<tvshow><uniqueid type=\"tmdb\">1</uniqueid></tvshow>")
    _touch(show / "Season 1" / "剧A S01E01.mkv")
    _touch(show / "Season 1" / "剧A S01E01 2160p.mkv")
    _touch(show / "Season 1" / "剧A S01E02.strm", "http://cloud/剧A.S01E02.1080p-GRP.mkv")
    _touch(show / "Season 1" / "extras" / "花絮 S01E99.mkv")
    _touch(tv / "剧B {tmdbid=2}" / "S01E01.mkv")
    _touch(tv / "剧C" / "S01E01.mkv")
    _touch(tv / "电影甲 (2019)" / "电影甲 (2019).mkv")
    _touch(tv / "电影甲 (2019)" / "电影甲 (2019) 4K.mkv")
    _touch(tv / "电影甲 (2019)" / "说明.txt")
    looked_up = []

    def history(path):
        """整理记录替身：只认识剧 C。"""
        looked_up.append(path)
        return 3 if "剧C" in path else None

    source = LocalSource([str(tv), str(tmp_path / "不存在")], threading.Event(), history_lookup=history, number_parser=_numbers)
    libraries = source.libraries()
    assert libraries == [(str(tv), str(tv), "mixed")]
    series = {s.title: s for s in source.iter_series(libraries[0])}
    assert {name: s.tmdb_id for name, s in series.items()} == {"剧A": 1, "剧B": 2, "剧C": 3}
    assert {name: s.tmdb_id_source for name, s in series.items()} == {"剧A": "nfo", "剧B": "dirname", "剧C": "history"}
    show_a = series["剧A"]
    assert show_a.year == "2020" and show_a.origin == "local"
    assert [e.label for e in show_a.episodes] == ["S01E01", "S01E02"]
    assert len(show_a.episodes[0].versions) == 2
    strm = show_a.episodes[1].versions[0]
    assert strm.kind == "strm" and strm.url == "http://cloud/剧A.S01E02.1080p-GRP.mkv"
    movies = list(source.iter_movies(libraries[0]))
    assert len(movies) == 2
    assert sorted(len(m.versions) for m in movies) == [1, 1]


def test_local_source_scanned_end_to_end(tmp_path):
    """本地目录与 Emby 走同一套检查：缺集、身份覆盖范围键使用 local: 前缀。"""
    tv = tmp_path / "tv"
    _touch(tv / "剧A {tmdbid=1}" / "S01E01.mkv")
    _touch(tv / "剧A {tmdbid=1}" / "S01E03.mkv")
    _touch(tv / "无名剧" / "S01E01.mkv")

    class _Tmdb:
        """只认识剧 1 的 TMDB 替身。"""

        requests = 0

        def get_series(self, tmdb_id):
            """返回剧 1 的三集。"""
            from app.plugins.libraryintegrity.models import TmdbEpisodeRef, TmdbSeries

            series = TmdbSeries(tmdb_id=1)
            series.seasons[1] = [TmdbEpisodeRef(100 + n, 1, n, "2026-01-01") for n in (1, 2, 3)]
            return series

    source = LocalSource([str(tv)], threading.Event(), history_lookup=None, number_parser=_numbers)
    scanner = LibraryScanner(ScanOptions(), _Tmdb(), threading.Event(), today=date(2026, 10, 30), name_parser=lambda n: {})
    report = scanner.scan([source])
    missing = [i for i in report.issues if i.type == IssueType.MISSING]
    assert len(missing) == 1 and missing[0].episodes == [2]
    unchecked = [i for i in report.issues if i.type == IssueType.UNCHECKED]
    assert unchecked[0].scope == f"local:{tv / '无名剧'}"
    assert report.stats.servers == ["本地目录"]


def test_local_source_reports_all_missing_roots(tmp_path):
    """全部目录都不存在时作为数据源错误报告。"""
    source = LocalSource([str(tmp_path / "x")], threading.Event(), history_lookup=None, number_parser=_numbers)
    report = LibraryScanner(ScanOptions(), None, threading.Event()).scan([source])
    assert report.errors and "本地目录不存在" in report.errors[0]


# ---------------- 媒体信息 ----------------

def test_parse_ffprobe_streams():
    """ffprobe：跳过封面流，识别 DV、位深与默认音轨；没有 HDR 标记时为 SDR。"""
    payload = {"streams": [
        {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
        {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160, "pix_fmt": "yuv420p10le",
         "color_transfer": "smpte2084", "side_data_list": [{"side_data_type": "DOVI configuration record"}]},
        {"codec_type": "audio", "codec_name": "aac"},
        {"codec_type": "audio", "codec_name": "truehd", "disposition": {"default": 1}},
    ]}
    assert parse_ffprobe(payload) == {
        "resolution": "2160p", "video_codec": "HEVC", "hdr": "DV", "bit_depth": "10bit", "audio_codec": "TrueHD",
    }
    sdr = parse_ffprobe({"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"}]})
    assert sdr["hdr"] == "SDR" and sdr["bit_depth"] == "8bit"


def test_parse_mediainfo_tracks():
    """mediainfo：识别 HDR10、编码与 TrueHD。"""
    payload = {"media": {"track": [
        {"@type": "General"},
        {"@type": "Video", "Format": "AVC", "Width": "1920", "Height": "800", "BitDepth": "8", "HDR_Format": "SMPTE ST 2086"},
        {"@type": "Audio", "Format": "MLP FBA", "Default": "Yes"},
    ]}}
    assert parse_mediainfo(payload) == {
        "resolution": "1080p", "video_codec": "H.264", "hdr": "HDR10", "bit_depth": "8bit", "audio_codec": "TrueHD",
    }


class _Runner:
    """subprocess.run 替身，记录命令并返回 ffprobe 输出。"""

    def __init__(self, returncode=0):
        """记录返回码。"""
        self.commands = []
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        """返回固定的 ffprobe 输出。"""
        self.commands.append(command)
        stdout = json.dumps({"streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080}]})
        return subprocess.CompletedProcess(command, self.returncode, stdout=stdout, stderr="")


def test_media_probe_caches_by_size_and_mtime_and_limits_new_reads(tmp_path):
    """未变化的文件走缓存，超过每轮上限的文件跳过，文件名以 file: 前缀传入防止被当作参数。"""
    first = _touch(tmp_path / "-a.mkv", "1")
    second = _touch(tmp_path / "b.mkv", "2")
    runner = _Runner()
    cache = tmp_path / "probe.json"
    probe = MediaProbe(cache, "/usr/bin/ffprobe", "ffprobe", max_new=1, runner=runner)
    assert probe.probe(first)["resolution"] == "1080p"
    assert probe.probe(second) == {}
    assert probe.skipped == 1
    assert runner.commands[0][-1] == f"file:{first}"
    probe.save()

    again = MediaProbe(cache, "/usr/bin/ffprobe", "ffprobe", max_new=0, runner=runner)
    assert again.probe(first)["video_codec"] == "HEVC"
    assert len(runner.commands) == 1
    _touch(first, "changed")
    assert again.probe(first) == {}


def test_media_probe_failure_is_cached_as_empty(tmp_path):
    """读取失败的文件记录为空结果，下次不重复读取。"""
    path = _touch(tmp_path / "bad.mkv", "x")
    runner = _Runner(returncode=1)
    probe = MediaProbe(tmp_path / "probe.json", "/usr/bin/ffprobe", "ffprobe", runner=runner)
    assert probe.probe(path) == {}
    assert probe.probe(path) == {}
    assert len(runner.commands) == 1


def test_local_source_uses_probe_for_files_not_strm(tmp_path):
    """本地视频读取媒体信息并标注来源，strm 不读取。"""
    tv = tmp_path / "tv"
    _touch(tv / "剧 {tmdbid=1}" / "S01E01.mkv", "v")
    _touch(tv / "剧 {tmdbid=1}" / "S01E02.strm", "http://x/y.mkv")
    runner = _Runner()
    probe = MediaProbe(tmp_path / "probe.json", "/usr/bin/ffprobe", "ffprobe", runner=runner)
    source = LocalSource([str(tv)], threading.Event(), probe=probe, history_lookup=None, number_parser=_numbers)
    series = next(source.iter_series(source.libraries()[0]))
    local_version = series.episodes[0].versions[0]
    assert local_version.resolution == "1080p" and local_version.sources["resolution"] == "mediainfo"
    assert series.episodes[1].versions[0].resolution is None
    assert len(runner.commands) == 1


def test_custom_named_season_dirs_belong_to_parent_series(tmp_path):
    """父目录有 tvshow.nfo 时，自定义命名的子目录（如「立志篇」）是季目录，不拆成多部剧。"""
    show = tmp_path / "tv" / "鬼灭之刃 (2019)"
    _touch(show / "tvshow.nfo", "<tvshow><uniqueid type=\"tmdb\">85937</uniqueid></tvshow>")
    _touch(show / "鬼灭之刃：立志篇" / "S01E01.strm", "x")
    _touch(show / "鬼灭之刃：游郭篇" / "S03E01.strm", "x")
    source = LocalSource([str(tmp_path / "tv")], threading.Event(), history_lookup=None, number_parser=_numbers)
    series = list(source.iter_series(source.libraries()[0]))
    assert [s.title for s in series] == ["鬼灭之刃"]
    assert [e.label for e in series[0].episodes] == ["S01E01", "S03E01"]


def test_season_nfo_marks_season_dir_and_unknown_number_stays_empty(tmp_path):
    """含 season.nfo 的目录是季目录，其中误放的 tvshow.nfo 不产生新剧；季号未知时留空，与 Emby 一致。"""
    show = tmp_path / "tv" / "铁臂阿童木 (1980)"
    _touch(show / "tvshow.nfo", "<tvshow><uniqueid type=\"tmdb\">23022</uniqueid></tvshow>")
    _touch(show / "Season" / "tvshow.nfo", "<tvshow><tmdbid>321623</tmdbid></tvshow>")
    _touch(show / "Season" / "season.nfo", "<season><title>Season</title></season>")
    _touch(show / "Season" / "E01.strm", "x")
    _touch(show / "Season 1" / "S01E45.strm", "x")
    _touch(tmp_path / "tv" / "剧B" / "Season 2" / "season.nfo", "<season><seasonnumber>2</seasonnumber></season>")
    _touch(tmp_path / "tv" / "剧B" / "Season 2" / "E03.strm", "x")

    def numbers(stem):
        """E01 这类文件名只有集号。"""
        if stem.startswith("E"):
            return None, int(stem[1:]), None, "", ""
        return _numbers(stem)

    source = LocalSource([str(tmp_path / "tv")], threading.Event(), history_lookup=None, number_parser=numbers)
    series = {s.title: s for s in source.iter_series(source.libraries()[0])}
    assert set(series) == {"铁臂阿童木", "剧B"}
    assert series["铁臂阿童木"].tmdb_id == 23022
    assert [(e.season, e.episode) for e in series["铁臂阿童木"].episodes] == [(1, 45), (None, 1)]
    assert [(e.season, e.episode) for e in series["剧B"].episodes] == [(2, 3)]


def test_directories_with_same_tmdb_id_are_merged(tmp_path):
    """改名前后各存一份的同一部剧合并核对：互补的集不再报缺集，重复的集作为多版本。"""
    tv = tmp_path / "tv"
    _touch(tv / "家业 (2026) {tmdbid=275966}" / "Season 1" / "S01E01.strm", "x")
    _touch(tv / "家业 (2026) {tmdbid=275966}" / "Season 1" / "S01E02.strm", "x")
    _touch(tv / "祯娘传 (2026) {tmdbid=275966}" / "Season 1" / "S01E02.strm", "x")
    _touch(tv / "祯娘传 (2026) {tmdbid=275966}" / "Season 1" / "S01E03.strm", "x")
    source = LocalSource([str(tv)], threading.Event(), history_lookup=None, number_parser=_numbers)
    series = list(source.iter_series(source.libraries()[0]))
    assert len(series) == 1 and series[0].title == "家业"
    assert [(e.episode, len(e.versions)) for e in series[0].episodes] == [(1, 1), (2, 2), (3, 1)]


def test_empty_series_dir_is_still_checked(tmp_path):
    """有 tvshow.nfo 但季目录为空的剧也参与核对，整季未下载会报缺集。"""
    show = tmp_path / "tv" / "逐玉 (2026)"
    _touch(show / "tvshow.nfo", "<tvshow><uniqueid type=\"tmdb\">279388</uniqueid></tvshow>")
    (show / "Season 1").mkdir()
    source = LocalSource([str(tmp_path / "tv")], threading.Event(), history_lookup=None, number_parser=_numbers)
    series = list(source.iter_series(source.libraries()[0]))
    assert [(s.title, s.tmdb_id, s.episodes) for s in series] == [("逐玉", 279388, [])]


def test_movie_dir_with_stray_tvshow_nfo_is_not_empty_series(tmp_path):
    """误放了 tvshow.nfo 的电影目录不当作空剧集，避免拿电影 ID 去查剧集。"""
    movie = tmp_path / "电影" / "罗小黑战记 2 (2025)"
    _touch(movie / "tvshow.nfo", "<tvshow><tmdbid>1</tmdbid></tvshow>")
    _touch(movie / "罗小黑战记 2 (2025) - 2160p.strm", "x")
    source = LocalSource([str(tmp_path / "电影")], threading.Event(), history_lookup=None, number_parser=_numbers)
    library = source.libraries()[0]
    assert list(source.iter_series(library)) == []
    assert len(list(source.iter_movies(library))) == 1


def test_filename_parsers_force_video(monkeypatch):
    """文件名以 .AAC 等音频编码结尾时，宿主可能按音频解析；插件调用时强制按视频解析。"""
    import app.sdk.media as media
    from app.plugins.libraryintegrity import emby, local

    calls = []

    class _Meta:
        """文件名识别结果替身。"""

        begin_season, begin_episode, end_episode, name, year = 5, 17, None, "", ""
        resource_pix = video_encode = resource_effect = audio_encode = resource_team = None

    def fake(title, **kwargs):
        """记录调用参数。"""
        calls.append(kwargs)
        return _Meta()

    monkeypatch.setattr(media, "MetaInfo", fake)
    local.parse_numbers.cache_clear()
    emby.parse_release_name.cache_clear()
    assert local.parse_numbers("哈哈哈哈哈 - S05E17 - 第 17 集 - 2160p.WEB-DL.H265.AAC")[:2] == (5, 17)
    emby.parse_release_name("哈哈哈哈哈 - S05E17 - 2160p.WEB-DL.H265.AAC.strm")
    assert calls == [{"force_video": True}, {"force_video": True}]
    local.parse_numbers.cache_clear()
    emby.parse_release_name.cache_clear()
