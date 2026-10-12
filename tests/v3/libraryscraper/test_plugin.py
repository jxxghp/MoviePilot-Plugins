from pathlib import Path

from app.plugins import libraryscraper
import pytest
from app.core.config import settings
from app.schemas import MediaSource, MediaType
from app.plugins.libraryscraper import LibraryScraper


def test_scrape_item_preserves_unified_media_identity(monkeypatch) -> None:
    """扫描目标必须完整携带来源枚举和数据源原生 ID。"""
    monkeypatch.setattr(
        settings,
        "MOVIE_RENAME_FORMAT",
        "{{title}}/{{title}}{{fileExt}}",
    )
    root = Path("/media")
    file_path = root / "Movie" / "Movie.mkv"

    item = LibraryScraper._LibraryScraper__get_scrape_item(
        file_path=file_path,
        scraper_path=root,
        mtype=MediaType.MOVIE,
        media_source=MediaSource.IMDb,
        media_id="tt1234567",
    )

    assert item == (
        root / "Movie",
        MediaType.MOVIE,
        "dir",
        MediaSource.IMDb,
        "tt1234567",
    )


def test_nfo_identity_uses_fixed_media_source_enum(tmp_path: Path) -> None:
    """NFO 中的来源专有标签只在解析边界映射为统一媒体身份。"""
    nfo_path = tmp_path / "movie.nfo"
    nfo_path.write_text(
        "<movie><uniqueid type='imdb'>tt7654321</uniqueid></movie>",
        encoding="utf-8",
    )

    identity = LibraryScraper._LibraryScraper__get_media_identity_from_nfo(nfo_path)

    assert identity == (MediaSource.IMDb, "tt7654321")


def test_nfo_identity_skips_zero_and_uses_later_valid_id(tmp_path: Path) -> None:
    """NFO 中的零值 ID 必须跳过，并继续寻找同来源的合法 ID。"""
    nfo_path = tmp_path / "movie.nfo"
    nfo_path.write_text(
        "<movie><uniqueid type='tmdb'>0</uniqueid><tmdbid>123</tmdbid></movie>",
        encoding="utf-8",
    )

    identity = LibraryScraper._LibraryScraper__get_media_identity_from_nfo(nfo_path)

    assert identity == (MediaSource.TMDB, "123")


def test_nfo_identity_rejects_only_zero_id(tmp_path: Path) -> None:
    """只有零值的 NFO 不得产生半对或伪造媒体身份。"""
    nfo_path = tmp_path / "movie.nfo"
    nfo_path.write_text(
        "<movie><uniqueid type='tmdb'>0</uniqueid></movie>",
        encoding="utf-8",
    )

    identity = LibraryScraper._LibraryScraper__get_media_identity_from_nfo(nfo_path)

    assert identity == (None, None)


def test_nfo_identity_skips_invalid_tmdb_placeholder(tmp_path: Path) -> None:
    """历史集级 NFO 的 None 占位值不得进入 V3 识别链。"""
    nfo_path = tmp_path / "episode.nfo"
    nfo_path.write_text(
        "<episodedetails><uniqueid type='tmdb'>None</uniqueid>"
        "<tmdbid>not-a-number</tmdbid></episodedetails>",
        encoding="utf-8",
    )

    assert LibraryScraper._LibraryScraper__get_media_identity_from_nfo(nfo_path) == (None, None)


def test_scrape_path_uses_pair_and_scraping_chain(tmp_path: Path, monkeypatch) -> None:
    """显式媒体身份必须直达识别链，元数据写入必须交给 ScrapingChain。"""
    media_file = tmp_path / "Movie.mkv"
    media_file.write_text("", encoding="utf-8")

    class FakeMediaInfo:
        media_source = MediaSource.IMDb
        media_id = "tt1234567"
        type = MediaType.MOVIE
        title = "Movie"

    class FakeMediaChain:
        def __init__(self) -> None:
            self.recognize_kwargs = None

        def recognize_media(self, **kwargs):
            self.recognize_kwargs = kwargs
            return FakeMediaInfo()

        @staticmethod
        def obtain_images(_mediainfo) -> None:
            return None

    class FakeScrapingChain:
        def __init__(self) -> None:
            self.calls = []

        def scrape_metadata(self, **kwargs) -> None:
            self.calls.append(kwargs)

    fake_media_chain = FakeMediaChain()
    fake_scraping_chain = FakeScrapingChain()
    monkeypatch.setattr(settings, "SCRAP_FOLLOW_TMDB", True)
    monkeypatch.setattr(libraryscraper, "_LibraryScrapingChain", lambda: fake_scraping_chain)
    plugin = object.__new__(LibraryScraper)
    plugin.chain = fake_media_chain
    plugin._mode = ""

    plugin._LibraryScraper__scrape_path(
        path=media_file,
        mtype=MediaType.MOVIE,
        target_type="file",
        media_source=MediaSource.IMDb,
        media_id="tt1234567",
    )

    assert fake_media_chain.recognize_kwargs == {
        "media_source": MediaSource.IMDb,
        "media_id": "tt1234567",
        "mtype": MediaType.MOVIE,
    }
    assert len(fake_scraping_chain.calls) == 1
    assert fake_scraping_chain.calls[0]["mediainfo"].media_id == "tt1234567"


@pytest.mark.parametrize(
    "media_source,media_id",
    (
        (MediaSource.TMDB, "0"),
        (MediaSource.TMDB, "   "),
        ("Plugin Source:Invalid", "123"),
        (MediaSource.TMDB, None),
        (None, "123"),
    ),
)
def test_scrape_path_rejects_invalid_explicit_identity(
        tmp_path: Path,
        media_source,
        media_id,
        monkeypatch,
) -> None:
    """零值、空白、未知来源和半对参数不得作为统一媒体身份传给识别链。"""
    media_file = tmp_path / "Movie.mkv"
    media_file.write_text("", encoding="utf-8")

    class FakeMeta:
        type = MediaType.MOVIE
        name = "Movie"

    monkeypatch.setattr(libraryscraper, "MetaInfoPath", lambda _path: FakeMeta())

    class FakeMediaChain:
        def __init__(self) -> None:
            self.recognize_kwargs = None

        def recognize_media(self, **kwargs):
            self.recognize_kwargs = kwargs
            return None

    fake_media_chain = FakeMediaChain()
    plugin = object.__new__(LibraryScraper)
    plugin.chain = fake_media_chain

    plugin._LibraryScraper__scrape_path(
        path=media_file,
        mtype=MediaType.MOVIE,
        target_type="file",
        media_source=media_source,
        media_id=media_id,
    )

    assert set(fake_media_chain.recognize_kwargs) == {"meta"}


@pytest.mark.parametrize("cache_name", ("Movie.trickplay", "Show - S01E01.TRICKPLAY"))
def test_scan_skips_trickplay_before_media_recognition(tmp_path, monkeypatch, cache_name):
    """扫描入口忽略预览缓存中的文件，仍发现正常媒体目录。"""
    from unittest.mock import Mock

    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    (movie_dir / "Movie.mkv").touch()
    cache = movie_dir / cache_name / "320"
    cache.mkdir(parents=True)
    (cache / "preview.mkv").touch()
    (cache / "0.jpg").touch()
    monkeypatch.setattr(settings, "MOVIE_RENAME_FORMAT", "{{title}}/{{title}}{{fileExt}}")
    plugin = object.__new__(LibraryScraper)
    plugin._scraper_paths = str(tmp_path)
    plugin._exclude_paths = ""
    metadata = Mock(return_value=Mock(type=MediaType.MOVIE, media_source=None, media_id=None))
    monkeypatch.setattr(libraryscraper, "MetaInfoPath", metadata)
    scrape = Mock()
    monkeypatch.setattr(plugin, "_LibraryScraper__scrape_path", scrape)
    plugin._LibraryScraper__libraryscraper()

    assert scrape.call_count == 1
    metadata.assert_called_once_with(movie_dir / "Movie.mkv")
    assert scrape.call_args.kwargs["path"] == movie_dir
    assert LibraryScraper._LibraryScraper__get_scrape_item(
        cache / "preview.mkv", tmp_path, MediaType.MOVIE,
    ) is None


@pytest.mark.parametrize("target", ("directory", "child"))
def test_scrape_rejects_direct_trickplay_targets(tmp_path, target):
    """直接配置缓存根目录或其子文件时，也不能识别或写入元数据。"""
    from unittest.mock import Mock

    cache = tmp_path / "Movie.trickplay"
    cache.mkdir()
    child = cache / "preview.mkv"
    child.touch()
    plugin = object.__new__(LibraryScraper)
    plugin.chain = Mock()
    plugin._LibraryScraper__scrape_path(
        path=cache if target == "directory" else child,
        mtype=MediaType.MOVIE,
        target_type="dir" if target == "directory" else "file",
    )
    plugin.chain.recognize_media.assert_not_called()


def test_category_fallback_skips_trickplay_children(tmp_path, monkeypatch):
    """分类目录识别失败后的逐文件回退也必须排除缓存后代。"""
    from unittest.mock import Mock

    normal = tmp_path / "Movie.mkv"
    normal.touch()
    cache = tmp_path / "Movie.trickplay" / "320"
    cache.mkdir(parents=True)
    (cache / "preview.mkv").touch()
    plugin = object.__new__(LibraryScraper)
    metadata = Mock(return_value=Mock(type=MediaType.MOVIE, media_source=None, media_id=None))
    monkeypatch.setattr(libraryscraper, "MetaInfoPath", metadata)
    scrape = Mock()
    monkeypatch.setattr(plugin, "_LibraryScraper__scrape_path", scrape)
    plugin._LibraryScraper__scrape_child_files(tmp_path, MediaType.MOVIE)
    assert scrape.call_count == 1
    metadata.assert_called_once_with(normal)
    assert scrape.call_args.kwargs["path"] == normal


def test_trickplay_suffix_only_excludes_directory_components(tmp_path):
    """精确匹配目录后缀，普通文件和名称相似的媒体目录保持可用。"""
    similar = tmp_path / "Movie.trickplay.backup"
    similar.mkdir()
    media = similar / "Movie.trickplay.mkv"
    media.touch()
    same_suffix_file = tmp_path / "Movie.trickplay"
    same_suffix_file.touch()
    assert not LibraryScraper._LibraryScraper__is_trickplay_path(media)
    assert not LibraryScraper._LibraryScraper__is_trickplay_path(same_suffix_file)


def test_recursive_chain_skips_season_named_trickplay_directory(tmp_path, monkeypatch):
    """递归刮削剧集根目录时，带季号的缓存也不能进入宿主写入流程。"""
    cache = tmp_path / "Show - S01E01.trickplay"
    cache.mkdir()
    cache_child = cache / "320"
    cache_child.mkdir()
    normal = tmp_path / "Season 1"
    normal.mkdir()
    chain = object.__new__(libraryscraper._LibraryScrapingChain)
    processed = []

    def host_scrape(self, fileitem, **kwargs):
        """模拟宿主递归派发，记录真正进入写入流程的目录。"""
        processed.append(Path(fileitem.path))
        if Path(fileitem.path) == tmp_path:
            for path in (cache, cache_child, normal):
                self.scrape_metadata(fileitem=libraryscraper.schemas.FileItem(
                    storage="local", type="dir", path=str(path) + "/", name=path.name,
                ), **kwargs)
        assert kwargs == {"overwrite": True}
        return True, "完成"

    monkeypatch.setattr(libraryscraper.ScrapingChain, "scrape_metadata", host_scrape)
    chain.scrape_metadata(fileitem=libraryscraper.schemas.FileItem(
        storage="local", type="dir", path=str(tmp_path) + "/", name=tmp_path.name,
    ), overwrite=True)
    assert processed == [tmp_path, normal]
