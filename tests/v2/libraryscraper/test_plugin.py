from pathlib import Path

import libraryscraper
from app.core.config import settings
from app.schemas import MediaType
from libraryscraper import LibraryScraper


def test_get_scrape_item_uses_media_folder_below_category(monkeypatch):
    """带分类目录的电影结构，应定位到影片目录，而不是动画电影这类分类目录。"""
    monkeypatch.setattr(
        settings,
        "MOVIE_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/{{title}}{{fileExt}}",
    )
    scraper_path = Path("/media/strm-new/电影")
    file_path = scraper_path / "动画电影" / "哪吒之魔童闹海 (2025)" / "哪吒之魔童闹海 (2025).strm"

    item = LibraryScraper._LibraryScraper__get_scrape_item(file_path, scraper_path, MediaType.MOVIE)

    assert item == (scraper_path / "动画电影" / "哪吒之魔童闹海 (2025)", MediaType.MOVIE, "dir", None)


def test_get_scrape_item_uses_tv_root_relative_path(monkeypatch):
    """扫描根目录可直接配置到分类层，剧集目录计算仍应基于该根目录的相对路径。"""
    monkeypatch.setattr(
        settings,
        "TV_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/Season {{season}}/{{title}} - {{season_episode}}{{fileExt}}",
    )
    scraper_path = Path("/media/strm-new/电视剧/国产剧")
    file_path = scraper_path / "狂飙 (2023)" / "Season 1" / "狂飙 - S01E01.strm"

    item = LibraryScraper._LibraryScraper__get_scrape_item(file_path, scraper_path, MediaType.TV)

    assert item == (scraper_path / "狂飙 (2023)", MediaType.TV, "dir", None)


def test_get_scrape_item_falls_back_to_file_when_rename_format_is_flat(monkeypatch):
    """重命名格式没有目录层级时，不能跳过文件，应退回到单文件刮削。"""
    monkeypatch.setattr(settings, "TV_RENAME_FORMAT", "{{title}} - {{season_episode}}{{fileExt}}")
    scraper_path = Path("/media/strm-new/电视剧/国产剧")
    file_path = scraper_path / "狂飙 - S01E01.strm"

    item = LibraryScraper._LibraryScraper__get_scrape_item(file_path, scraper_path, MediaType.TV)

    assert item == (file_path, MediaType.TV, "file", None)


def test_get_scrape_item_uses_real_issue_paths_from_library_root(monkeypatch):
    """从媒体库根目录扫描时，应跳过电影/电视剧下的分类层，定位到真实媒体目录。"""
    monkeypatch.setattr(
        settings,
        "MOVIE_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/{{title}}{{fileExt}}",
    )
    monkeypatch.setattr(
        settings,
        "TV_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/Season {{season}}/{{title}} - {{season_episode}}{{fileExt}}",
    )
    scraper_path = Path("/media/strm-new")
    movie_file = scraper_path / "电影" / "动画电影" / "影片名" / "xxx.strm"
    tv_file = scraper_path / "电视剧" / "国产剧" / "剧名" / "Season 1" / "xxx.strm"

    movie_item = LibraryScraper._LibraryScraper__get_scrape_item(movie_file, scraper_path, MediaType.MOVIE)
    tv_item = LibraryScraper._LibraryScraper__get_scrape_item(tv_file, scraper_path, MediaType.TV)

    assert movie_item == (scraper_path / "电影" / "动画电影" / "影片名", MediaType.MOVIE, "dir", None)
    assert tv_item == (scraper_path / "电视剧" / "国产剧" / "剧名", MediaType.TV, "dir", None)


def test_libraryscraper_scans_real_issue_paths(tmp_path, monkeypatch):
    """直接跑扫描入口，确认用户提到的两类路径不会停在分类目录。"""
    root = tmp_path / "strm-new"
    movie_dir = root / "电影" / "动画电影" / "影片名"
    tv_dir = root / "电视剧" / "国产剧" / "剧名" / "Season 1"
    movie_dir.mkdir(parents=True)
    tv_dir.mkdir(parents=True)
    (movie_dir / "xxx.strm").write_text("", encoding="utf-8")
    (tv_dir / "xxx.strm").write_text("", encoding="utf-8")

    class FakeMediaInfo:
        tmdb_id = 129

        def __init__(self, mtype):
            self.type = mtype

    class FakeChain:
        def __init__(self):
            self.recognized_types = []

        def recognize_media(self, meta=None, mtype=None, tmdbid=None, **kwargs):
            recognized_type = mtype or meta.type
            self.recognized_types.append(recognized_type)
            return FakeMediaInfo(recognized_type)

        def obtain_images(self, mediainfo):
            return None

    class FakeMediaChain:
        def __init__(self):
            self.scraped_items = []

        def scrape_metadata(self, fileitem, **kwargs):
            self.scraped_items.append(fileitem)

    fake_media_chain = FakeMediaChain()
    monkeypatch.setattr(settings, "SCRAP_FOLLOW_TMDB", True)
    monkeypatch.setattr(
        settings,
        "MOVIE_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/{{title}}{{fileExt}}",
    )
    monkeypatch.setattr(
        settings,
        "TV_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/Season {{season}}/{{title}} - {{season_episode}}{{fileExt}}",
    )
    monkeypatch.setattr(libraryscraper, "MediaChain", lambda: fake_media_chain)

    plugin = LibraryScraper()
    fake_chain = FakeChain()
    plugin.chain = fake_chain
    plugin.init_plugin({"scraper_paths": str(root), "exclude_paths": ""})
    plugin._LibraryScraper__libraryscraper()

    scraped_paths = {Path(fileitem.path.rstrip("/")) for fileitem in fake_media_chain.scraped_items}
    assert scraped_paths == {movie_dir, tv_dir.parent}
    assert fake_chain.recognized_types == [MediaType.MOVIE, MediaType.TV]


def test_forced_tv_root_skips_movie_category_paths():
    """配置媒体库根目录加 #电视剧 时，应跳过同级电影分类路径。"""
    scraper_path = Path("/media/strm-new")
    movie_file = scraper_path / "电影" / "动画电影" / "影片名" / "xxx.strm"
    tv_file = scraper_path / "电视剧" / "国产剧" / "剧名" / "Season 1" / "xxx.strm"

    assert not LibraryScraper._LibraryScraper__match_forced_type_path(movie_file, scraper_path, MediaType.TV)
    assert LibraryScraper._LibraryScraper__match_forced_type_path(tv_file, scraper_path, MediaType.TV)


def test_scrape_dir_falls_back_to_child_files(tmp_path, monkeypatch):
    """分类目录识别失败后，应继续刮削目录内的具体媒体文件。"""
    category_path = tmp_path / "电影" / "动画电影"
    category_path.mkdir(parents=True)
    media_file = category_path / "哪吒之魔童闹海 (2025).strm"
    media_file.write_text("", encoding="utf-8")

    class FakeMediaInfo:
        tmdb_id = 129
        type = MediaType.MOVIE

    class FakeChain:
        def __init__(self):
            self.recognize_calls = 0

        def recognize_media(self, **kwargs):
            self.recognize_calls += 1
            return None if self.recognize_calls == 1 else FakeMediaInfo()

        def obtain_images(self, mediainfo):
            return None

    class FakeMediaChain:
        def __init__(self):
            self.scraped_items = []

        def scrape_metadata(self, fileitem, **kwargs):
            self.scraped_items.append(fileitem)

    fake_chain = FakeChain()
    fake_media_chain = FakeMediaChain()
    monkeypatch.setattr(settings, "SCRAP_FOLLOW_TMDB", True)
    monkeypatch.setattr(libraryscraper, "MediaChain", lambda: fake_media_chain)

    plugin = LibraryScraper()
    plugin.chain = fake_chain

    plugin._LibraryScraper__scrape_path(category_path, MediaType.MOVIE, target_type="dir")

    assert len(fake_media_chain.scraped_items) == 1
    fileitem = fake_media_chain.scraped_items[0]
    assert fileitem.type == "file"
    assert fileitem.path == media_file.as_posix()
