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
    monkeypatch.setattr(libraryscraper, "ScrapingChain", lambda: fake_scraping_chain)
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
