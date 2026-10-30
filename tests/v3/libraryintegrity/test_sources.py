"""影视库完整性检查：NFO、strm 地址、Emby 解析与 TMDB 缓存测试。"""

import os

import pytest

from app.plugins.libraryintegrity.emby import (
    EmbyError,
    EmbyReader,
    fill_from_names,
    is_virtual,
    parse_episode,
    select_libraries,
    version_from_source,
)
from app.plugins.libraryintegrity.nfo import NfoReader, PathMapper, parse_nfo_text, strm_url_filename
from app.plugins.libraryintegrity.tmdb import ENDED_TTL_SECONDS, TmdbLookupError, TmdbSource

MP_EPISODE_NFO = """<?xml version="1.0" encoding="utf-8"?>
<episodedetails>
  <uniqueid type="tmdb" default="true">63056</uniqueid>
  <tmdbid>63056</tmdbid>
  <title>第 1 集</title>
  <aired>2011-04-17</aired>
  <season>1</season>
  <episode>1</episode>
</episodedetails>
"""

EMBY_EPISODE_NFO = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<episodedetails>
  <lockdata>false</lockdata>
  <uniqueid type="Tvdb">3254641</uniqueid>
  <season>2</season>
  <episode>3</episode>
  <fileinfo><streamdetails><video>
    <codec>hevc</codec><width>3840</width><height>2160</height><hdrtype>dolbyvision</hdrtype>
  </video></streamdetails></fileinfo>
</episodedetails>
"""


# ---------------- NFO 与路径 ----------------

def test_path_mapper_uses_longest_prefix_and_keeps_unmapped_paths():
    """按最长前缀映射，未匹配的路径原样返回，不误匹配同名前缀目录。"""
    mapper = PathMapper("/media => /mnt/media\n/media/strm => /strm\n# 注释\n无效行")
    assert str(mapper.map("/media/strm/剧/S01E01.strm")) == "/strm/剧/S01E01.strm"
    assert str(mapper.map("/media/tv/a.mkv")) == "/mnt/media/tv/a.mkv"
    assert str(mapper.map("/media2/a.mkv")) == "/media2/a.mkv"
    assert mapper.map("") is None


def test_parse_mp_and_emby_episode_nfo():
    """MP NFO 提供单集 TMDB ID；Emby NFO 提供 streamdetails 技术参数。"""
    mp = parse_nfo_text(MP_EPISODE_NFO, "episodedetails")[0]
    assert (mp.tmdb_id, mp.season, mp.episode) == (63056, 1, 1)
    emby = parse_nfo_text(EMBY_EPISODE_NFO, "episodedetails")[0]
    assert emby.tmdb_id is None
    assert (emby.resolution, emby.video_codec, emby.hdr) == ("2160p", "HEVC", "DV")


def test_parse_multi_episode_nfo_and_invalid_xml():
    """Kodi 多集 NFO 有多个根元素；无法解析的内容返回空列表。"""
    text = "<episodedetails><season>1</season><episode>1</episode></episodedetails>\n" \
           "<episodedetails><season>1</season><episode>2</episode></episodedetails>"
    assert [info.episode for info in parse_nfo_text(text, "episodedetails")] == [1, 2]
    assert parse_nfo_text("<episodedetails><season>", "episodedetails") == []


def test_nfo_reader_reads_mapped_files_and_marks_stale(tmp_path):
    """读取映射后的同名 NFO 与 tvshow.nfo，NFO 早于视频文件时标记过期，结果在扫描内缓存。"""
    show = tmp_path / "剧"
    show.mkdir()
    (show / "tvshow.nfo").write_text("<tvshow><uniqueid type=\"tmdb\">1399</uniqueid></tvshow>", encoding="utf-8")
    nfo = show / "S01E01.nfo"
    nfo.write_text(MP_EPISODE_NFO, encoding="utf-8")
    media = show / "S01E01.strm"
    media.write_text("http://example/S01E01.mkv", encoding="utf-8")
    os.utime(nfo, (1_000_000, 1_000_000))
    reader = NfoReader(PathMapper(f"/emby/tv => {tmp_path}"))
    infos = reader.episode("/emby/tv/剧/S01E01.strm")
    assert infos[0].tmdb_id == 63056 and infos[0].stale
    assert reader.series("/emby/tv/剧").tmdb_id == 1399
    reader.episode("/emby/tv/剧/S01E01.strm")
    assert reader.reads == 2
    assert reader.episode("/emby/tv/剧/S01E09.strm") == []


def test_strm_url_filename_from_path_or_query():
    """从直链路径或查询参数中提取视频文件名，非视频地址返回空。"""
    assert strm_url_filename("http://alist/d/tv/Show.S01E01.2160p.WEB-DL.H265-ADWeb.mkv?sign=x") == \
        "Show.S01E01.2160p.WEB-DL.H265-ADWeb.mkv"
    assert strm_url_filename("http://h/api/play?file=%2Ftv%2FShow.S01E02.1080p.mkv&t=1") == "Show.S01E02.1080p.mkv"
    assert strm_url_filename("http://h/api/play?id=123") == ""
    assert strm_url_filename("") == ""


# ---------------- Emby 解析 ----------------

def test_version_from_local_source_reads_streams():
    """本地文件版本读取 Emby 探测到的视频与音频流。"""
    version = version_from_source({
        "Path": "/tv/a.mkv",
        "Protocol": "File",
        "MediaStreams": [
            {"Type": "Audio", "Codec": "aac"},
            {"Type": "Audio", "Codec": "eac3", "IsDefault": True},
            {"Type": "Video", "Codec": "hevc", "Width": 3840, "Height": 1608, "BitDepth": 10,
             "ExtendedVideoType": "DolbyVision", "VideoRange": "HDR"},
        ],
    }, "/tv/a.mkv")
    assert version.kind == "file"
    assert (version.resolution, version.video_codec, version.hdr, version.bit_depth, version.audio_codec) == \
        ("2160p", "HEVC", "DV", "10bit", "DDP")
    assert version.sources["resolution"] == "emby"


def _fake_parser(name):
    """按文件名返回预设的发布信息，替代依赖系统配置的宿主文件名识别。"""
    if name.endswith(".strm"):
        return {"resolution": "1080p"}
    return {"resolution": "2160p", "hdr": "DV", "release_group": "ADWeb"}


def test_strm_source_falls_back_to_filename_and_url():
    """未探测的 strm 没有媒体流，技术参数先取文件名，再用地址中的文件名补齐。"""
    version = version_from_source(
        {"Path": "http://alist/d/Show.S01E01.2160p.WEB-DL.H265.DV-ADWeb.mkv", "Protocol": "Http", "MediaStreams": []},
        "/strm/剧/剧 - S01E01 - 第 1 集 - 1080p.strm",
    )
    assert version.kind == "strm" and version.resolution is None
    assert version.path.endswith(".strm") and version.url.startswith("http://")
    fill_from_names(version, _fake_parser)
    assert version.resolution == "1080p" and version.sources["resolution"] == "filename"
    assert version.release_group == "ADWeb" and version.sources["release_group"] == "url"
    assert version.hdr == "DV"


def test_emby_streams_are_not_overridden_by_filename():
    """媒体流探测结果优先，文件名只补未知维度。"""
    version = version_from_source(
        {"Path": "/tv/a.mkv", "MediaStreams": [{"Type": "Video", "Width": 1920, "Height": 1080, "Codec": "h264"}]},
        "/tv/a.mkv",
    )
    fill_from_names(version, _fake_parser)
    assert version.resolution == "1080p" and version.sources["resolution"] == "emby"
    assert version.release_group == "ADWeb"


def test_parse_episode_and_virtual_detection():
    """单集解析读取季集号、多集范围和 TMDB ID；占位条目被识别。"""
    episode = parse_episode({
        "Id": "e1", "ParentIndexNumber": 1, "IndexNumber": 1, "IndexNumberEnd": 2,
        "ProviderIds": {"tmdb": "63056"}, "Path": "/tv/a.mkv", "MediaSources": [{"Path": "/tv/a.mkv"}],
    })
    assert (episode.season, episode.episode_numbers, episode.tmdb_id, episode.tmdb_id_source) == (1, [1, 2], 63056, "emby")
    assert episode.label == "S01E01-E02"
    assert is_virtual({"LocationType": "Virtual"})
    assert not is_virtual({"LocationType": "FileSystem"})


def test_select_libraries_skips_non_video_and_home_videos():
    """跳过音乐等非影视库；未指定名称时跳过家庭视频库，指定名称时只取指定库。"""
    libraries = [
        {"Name": "电视剧", "ItemId": "1", "CollectionType": "tvshows"},
        {"Name": "音乐", "ItemId": "2", "CollectionType": "music"},
        {"Name": "家庭", "ItemId": "3", "CollectionType": "homevideos"},
        {"Name": "混合", "ItemId": "4"},
    ]
    assert [lib[0] for lib in select_libraries(libraries, [])] == ["电视剧", "混合"]
    assert [lib[0] for lib in select_libraries(libraries, ["家庭"])] == ["家庭"]


class _Response:
    """最小 HTTP 响应替身。"""

    def __init__(self, data, status_code=200):
        """记录返回内容。"""
        self._data = data
        self.status_code = status_code
        self.closed = False

    def json(self):
        """返回 JSON 内容。"""
        if isinstance(self._data, Exception):
            raise self._data
        return self._data

    def close(self):
        """记录响应已关闭。"""
        self.closed = True


class _Instance:
    """宿主 Emby 实例替身，记录请求地址。"""

    def __init__(self, responses, user="u1"):
        """准备按顺序返回的响应。"""
        self.user = user
        self.urls = []
        self._responses = list(responses)

    def get_data(self, url):
        """返回下一个响应。"""
        self.urls.append(url)
        return self._responses.pop(0) if self._responses else None


def test_emby_reader_keeps_placeholders_unencoded_and_pages():
    """占位符原样传给宿主替换，分页读取到不足一页为止，响应都被关闭。"""
    first = _Response({"Items": [{"Id": "1"}, {"Id": "2"}]})
    second = _Response({"Items": [{"Id": "3"}]})
    instance = _Instance([first, second])
    reader = EmbyReader("Emby", instance, page_size=2)
    assert [item["Id"] for item in reader.iter_items("lib", "Series", "Path")] == ["1", "2", "3"]
    assert instance.urls[0].startswith("[HOST]emby/Items?")
    # 不带 UserId：用户视图会合并同一集的多个条目，导致多文件漏报
    assert instance.urls[0].endswith("api_key=[APIKEY]") and "UserId" not in instance.urls[0]
    assert "StartIndex=2" in instance.urls[1]
    assert first.closed and second.closed


def test_emby_reader_stops_when_server_ignores_paging():
    """服务端忽略分页参数、重复返回同一页时停止，不陷入死循环。"""
    page = {"Items": [{"Id": "1"}, {"Id": "2"}]}
    instance = _Instance([_Response(page), _Response(page), _Response(page)])
    reader = EmbyReader("Emby", instance, page_size=2)
    assert [item["Id"] for item in reader.iter_items("lib", "Series", "Path")] == ["1", "2"]
    assert len(instance.urls) == 2


def test_emby_reader_errors_and_virtual_filter():
    """无响应与 HTTP 错误时抛出 EmbyError；不依赖 Emby 用户；单集列表过滤占位条目。"""
    with pytest.raises(EmbyError):
        EmbyReader("Emby", _Instance([])).libraries()
    with pytest.raises(EmbyError):
        EmbyReader("Emby", _Instance([_Response({}, 401)])).libraries()
    no_user = _Instance([_Response({"Items": [{"Id": "x"}]})], user=None)
    assert [item["Id"] for item in EmbyReader("Emby", no_user).series_episodes("s1")] == ["x"]
    instance = _Instance([_Response({"Items": [{"Id": "a"}, {"Id": "b", "LocationType": "Virtual"}]})])
    assert [item["Id"] for item in EmbyReader("Emby", instance).series_episodes("s/1")] == ["a"]
    assert instance.urls[0].startswith("[HOST]emby/Shows/s%2F1/Episodes?")


# ---------------- TMDB ----------------

class _FakeTv:
    """TMDB 剧集接口替身。"""

    def __init__(self, details):
        """记录剧集详情与调用次数。"""
        self.details_data = details
        self.calls = 0

    def details(self, tmdb_id, append_to_response=None):
        """返回剧集详情。"""
        self.calls += 1
        if isinstance(self.details_data, Exception):
            raise self.details_data
        return self.details_data


class _FakeSeason:
    """TMDB 季接口替身。"""

    def __init__(self, seasons):
        """记录各季详情。"""
        self.seasons = seasons

    def details(self, tmdb_id, season, append_to_response=None):
        """返回季详情。"""
        return self.seasons.get(season)


class _FakeApi:
    """TMDB 客户端替身。"""

    def __init__(self, details, seasons):
        """组装剧集与季接口。"""
        self.tv = _FakeTv(details)
        self.season_obj = _FakeSeason(seasons)
        self.closed = False

    def close(self):
        """记录关闭。"""
        self.closed = True


def _season(number, count):
    """构造季详情。"""
    return {"episodes": [
        {"id": number * 100 + n, "episode_number": n, "air_date": "2020-01-01", "name": f"E{n}"} for n in range(1, count + 1)
    ]}


def test_tmdb_source_fetches_caches_and_persists(tmp_path):
    """读取各季单集 ID，已完结剧集在 TTL 内使用缓存，保存后可被新实例读取。"""
    api = _FakeApi({"id": 1, "status": "Ended", "seasons": [{"season_number": 0}, {"season_number": 1}]},
                   {0: _season(0, 1), 1: _season(1, 2)})
    now = [1_000_000.0]
    cache_file = tmp_path / "cache.json"
    source = TmdbSource(cache_file, api_factory=lambda: api, clock=lambda: now[0])
    series = source.get_series(1)
    assert sorted(series.seasons) == [0, 1]
    assert [ref.tmdb_id for ref in series.seasons[1]] == [101, 102]
    assert source.requests == 3
    source.get_series(1)
    assert api.tv.calls == 1
    source.save()
    source.close()
    assert api.closed

    now[0] += ENDED_TTL_SECONDS - 10
    reloaded = TmdbSource(cache_file, api_factory=lambda: api, clock=lambda: now[0])
    assert [ref.episode for ref in reloaded.get_series(1).seasons[1]] == [1, 2]
    assert api.tv.calls == 1
    now[0] += 20
    reloaded.get_series(1)
    assert api.tv.calls == 2


def test_tmdb_source_errors_raise_lookup_error(tmp_path):
    """TMDB 异常、空详情与季读取失败都转换为 TmdbLookupError。"""
    failing = TmdbSource(tmp_path / "a.json", api_factory=lambda: _FakeApi(RuntimeError("404"), {}))
    with pytest.raises(TmdbLookupError):
        failing.get_series(1)
    empty = TmdbSource(tmp_path / "b.json", api_factory=lambda: _FakeApi({}, {}))
    with pytest.raises(TmdbLookupError):
        empty.get_series(1)
    no_season = TmdbSource(tmp_path / "c.json", api_factory=lambda: _FakeApi({"id": 1, "seasons": [{"season_number": 1}]}, {}))
    with pytest.raises(TmdbLookupError):
        no_season.get_series(1)


def test_tmdb_cache_file_corruption_is_tolerated(tmp_path):
    """缓存文件损坏时重建，不影响扫描。"""
    cache_file = tmp_path / "cache.json"
    cache_file.write_text("{broken", encoding="utf-8")
    source = TmdbSource(cache_file, api_factory=lambda: _FakeApi({"id": 1, "seasons": []}, {}))
    assert source.get_series(1).seasons == {}
