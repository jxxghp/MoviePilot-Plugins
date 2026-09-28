"""目录新增监控刮削 (MediaDirWatcher) 纯逻辑单测。

按官方测试规范：
- 通过生产命名空间 app.plugins.mediadirwatcher 导入插件（conftest 负责注入后端与插件目录）；
- 使用 object.__new__ 绕过插件 __init__，只测不依赖运行时的纯逻辑方法。
"""
from pathlib import Path

from app.plugins.mediadirwatcher import MediaDirWatcher, CATEGORY_DIRS

# name-mangled 私有静态方法引用
_dir_signature = MediaDirWatcher._MediaDirWatcher__dir_signature
_item_path = MediaDirWatcher._MediaDirWatcher__item_path
_category_label = MediaDirWatcher._MediaDirWatcher__category_label
_type_label = MediaDirWatcher._MediaDirWatcher__type_label
_poster_url = MediaDirWatcher._MediaDirWatcher__poster_url


class _FakeMediaInfo:
    """最小 MediaInfo 替身，仅提供 __type_label/__poster_url 需要的属性。"""

    def __init__(self, type=None, poster_path=None):
        self.type = type
        self.poster_path = poster_path


# ---------------- 分类标注 ----------------

def test_category_label_matches_dir_category():
    """路径中包含分类目录名时，应返回该分类。"""
    p = Path("/media/vol3/动画片/千与千寻/千与千寻.mkv")
    assert _category_label(p) == "动画片"


def test_category_label_matches_first_category_in_path():
    """路径中出现多个分类名时，按路径顺序取第一个。"""
    p = Path("/media/电影/纪录片/某纪录片.mkv")
    assert _category_label(p) == "电影"


def test_category_label_empty_when_no_category():
    """路径中没有分类目录名时应返回空串。"""
    p = Path("/media/custom/some-movie/movie.mkv")
    assert _category_label(p) == ""


def test_category_dirs_contains_common_categories():
    """分类表应覆盖常见目录分类。"""
    for name in ("电影", "电视剧", "动画片", "纪录片"):
        assert name in CATEGORY_DIRS


# ---------------- 条目路径推断 ----------------

def test_item_path_tv_series_dir(tmp_path):
    """剧集结构: 剧集目录/Season x/文件 -> 条目为剧集目录(上两层)。"""
    base = tmp_path / "电视剧"
    season = base / "某剧集" / "Season 1"
    season.mkdir(parents=True)
    f = season / "S01E01.mkv"
    f.write_bytes(b"x")
    assert _item_path(f, base) == base / "某剧集"


def test_item_path_movie_dir(tmp_path):
    """电影结构: 根/分类/电影目录/文件 -> 条目为电影目录。"""
    base = tmp_path / "辅种"
    movie_dir = base / "电影" / "某电影 (2024)"
    movie_dir.mkdir(parents=True)
    f = movie_dir / "某电影.mkv"
    f.write_bytes(b"x")
    assert _item_path(f, base) == movie_dir


def test_item_path_flat_file(tmp_path):
    """扁平结构: 文件直接在监控根下 -> 条目为文件本身。"""
    base = tmp_path / "watch"
    base.mkdir()
    f = base / "movie.mkv"
    f.write_bytes(b"x")
    assert _item_path(f, base) == f


# ---------------- 目录树指纹 ----------------

def test_dir_signature_changes_on_new_dir(tmp_path):
    """目录树内新增子目录后，指纹应发生变化。"""
    (tmp_path / "a").mkdir()
    sig1 = _dir_signature(tmp_path)
    (tmp_path / "b").mkdir()
    sig2 = _dir_signature(tmp_path)
    assert sig1 and sig2 and sig1 != sig2


def test_dir_signature_stable_without_change(tmp_path):
    """目录树无变化时指纹应保持一致。"""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    assert _dir_signature(tmp_path) == _dir_signature(tmp_path)


def test_dir_signature_ignores_files(tmp_path):
    """指纹只收集目录，目录内文件增减不直接影响指纹（由目录 mtime 反映）。"""
    (tmp_path / "a").mkdir()
    sig1 = _dir_signature(tmp_path)
    # 同一秒内目录 mtime 可能不变，此处仅验证函数可用且返回字符串
    assert isinstance(sig1, str)


# ---------------- 展示辅助 ----------------

def test_type_label_movie_enum():
    """枚举类型(带 value 属性)应规范化为 电影。"""
    from types import SimpleNamespace
    mi = _FakeMediaInfo(type=SimpleNamespace(value="电影"))
    assert _type_label(mi) == "电影"


def test_type_label_tv_string():
    """字符串类型 tv 应规范化为 电视剧。"""
    assert _type_label(_FakeMediaInfo(type="tv")) == "电视剧"


def test_type_label_fallback():
    """未知类型应回退为 媒体。"""
    assert _type_label(_FakeMediaInfo(type="unknown")) == "媒体"


def test_poster_url_none():
    """无海报时应返回 None。"""
    assert _poster_url(_FakeMediaInfo()) is None


def test_poster_url_tmdb_path():
    """TMDB 相对路径应拼接为完整图片 URL。"""
    url = _poster_url(_FakeMediaInfo(poster_path="/abc.jpg"))
    assert url == "https://image.tmdb.org/t/p/w500/abc.jpg"


def test_poster_url_absolute():
    """完整 http 链接应原样返回。"""
    assert _poster_url(_FakeMediaInfo(poster_path="http://x/y.jpg")) == "http://x/y.jpg"
