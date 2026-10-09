"""源文件联动清理（ScrapeFileClean）V3 专用实现的合同与纯逻辑单测。

按官方测试规范：通过生产命名空间 app.plugins.scrapefileclean 导入插件
（tests/conftest.py 负责注入后端与 plugins.v3/ 插件目录），并用 object.__new__
绕过插件构造，只覆盖不依赖运行时组合根的合同与纯逻辑。
"""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/scrapefileclean/__init__.py"
PLUGIN_ID = "ScrapeFileClean"

LEGACY_MODULE_PREFIXES = ("app.core.", "app.helper.", "app.utils.", "app.db.models")
LEGACY_MODULES = {"app.log", "app.plugins"}
LEGACY_SYMBOLS = (
    "SessionFactory",
    "AsyncSessionFactory",
    "ScopedSession",
    "MessageChannel",
    "NotificationType",
    "transferhistory_oper",
)


def _load_plugin():
    return importlib.import_module("app.plugins.scrapefileclean")


def _make_plugin(module):
    """绕过运行时组装实例化插件，并补齐纯逻辑方法依赖的状态。"""
    plugin = object.__new__(module.ScrapeFileClean)
    plugin._enabled = True
    plugin._notify = False
    plugin._delete_scrap_infos = False
    plugin._delete_torrents = False
    plugin._delete_history = False
    plugin._custom_scrap_extensions = []
    plugin.monitor_dirs = ""
    plugin.exclude_dirs = ""
    plugin.exclude_keywords = ""
    plugin.file_state = {}
    return plugin


def _imported_modules() -> list:
    """返回插件源码中出现的所有导入模块名。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


# ---------------- 编制与索引合同 ----------------

def test_v3_metadata_and_indexes_are_aligned():
    """插件版本、V3 索引条目与旧索引禁用标记必须一致。"""
    module = _load_plugin()
    v3 = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
    entry = v3[PLUGIN_ID]

    assert module.ScrapeFileClean.plugin_version == "2.0.0"
    assert entry["version"] == "2.0.0"
    assert entry["system_version"] == ">=3.0.0"
    assert entry["history"]["v2.0.0"]
    assert entry.get("release") == v2[PLUGIN_ID].get("release")
    assert v2[PLUGIN_ID]["v3"] is False


def test_plugin_only_uses_stable_v3_imports():
    """V3 专用实现不得再依赖旧导入路径、裸会话工厂与宿主 Model。"""
    modules = _imported_modules()
    for name in modules:
        assert not name.startswith(LEGACY_MODULE_PREFIXES), name
        assert name not in LEGACY_MODULES, name

    text = SOURCE.read_text(encoding="utf-8")
    for symbol in LEGACY_SYMBOLS:
        assert symbol not in text, symbol
    assert any(name.startswith("app.sdk.") for name in modules)
    assert "from app.db.oper.transferhistory import TransferHistoryOper" in modules[0:1] or \
        "app.db.oper.transferhistory" in modules


def test_notifications_use_v3_message_type():
    """通知场景使用 V3 的 MessageType，不再出现旧名 NotificationType。"""
    text = SOURCE.read_text(encoding="utf-8")

    assert text.count("mtype=MessageType.SiteMessage") == 2
    assert "NotificationType" not in text


def test_api_command_page_and_state_contract():
    """插件不注册 API/命令、没有详情页，启用状态跟随配置。"""
    plugin = _make_plugin(_load_plugin())

    assert plugin.get_api() == []
    assert plugin.get_command() == []
    assert plugin.get_page() is None
    assert plugin.get_state() is True
    plugin._enabled = False
    assert plugin.get_state() is False


def test_delete_history_delegates_to_transfer_history_oper():
    """转移记录清理只通过 Oper 查询与删除，且受开关控制。"""
    plugin = _make_plugin(_load_plugin())

    class _FakeHistoryOper:
        def __init__(self, dest=None, src=None):
            self._dest = dest
            self._src = src
            self.deleted = []

        def get_by_dest(self, path):
            return self._dest

        def get_by_src(self, path):
            return self._src

        def delete(self, history_id):
            self.deleted.append(history_id)

    plugin._delete_history = True

    by_dest = _FakeHistoryOper(dest=SimpleNamespace(id=7))
    plugin._transferhistory = by_dest
    plugin.delete_history("/media/library/Show")
    assert by_dest.deleted == [7]

    by_src = _FakeHistoryOper(src=SimpleNamespace(id=9))
    plugin._transferhistory = by_src
    plugin.delete_history("/media/library/Show")
    assert by_src.deleted == [9]

    unmatched = _FakeHistoryOper()
    plugin._transferhistory = unmatched
    plugin.delete_history("/media/library/Show")
    assert unmatched.deleted == []

    plugin._delete_history = False
    disabled = _FakeHistoryOper(dest=SimpleNamespace(id=11))
    plugin._transferhistory = disabled
    plugin.delete_history("/media/library/Show")
    assert disabled.deleted == []


# ---------------- 路径与硬链接判定 ----------------

def test_same_file_identity_matches_dev_and_inode():
    """同一 (dev, inode) 判定为同一文件实体。"""
    module = _load_plugin()
    info = module.FileInfo(dev=11, inode=22, add_time=None)

    assert module.ScrapeFileClean._same_file_identity(info, 11, 22) is True
    assert module.ScrapeFileClean._same_file_identity(info, 11, 23) is False
    assert module.ScrapeFileClean._same_file_identity(info, 12, 22) is False


def test_is_same_or_child_path_avoids_prefix_false_positive():
    """子路径判定按路径段比较，避免 /media/movies2 被当成 /media/movies 的子目录。"""
    plugin_class = _load_plugin().ScrapeFileClean

    assert plugin_class._is_same_or_child_path(Path("/media/movies"), "/media/movies") is True
    assert plugin_class._is_same_or_child_path(Path("/media/movies/a.mkv"), "/media/movies") is True
    assert plugin_class._is_same_or_child_path(Path("/media/movies2/a.mkv"), "/media/movies") is False
    assert plugin_class._is_same_or_child_path(Path("/media/movies"), "") is False


def test_exclude_dirs_and_keywords():
    """不删除目录与过滤关键字按配置生效。"""
    plugin = _make_plugin(_load_plugin())
    plugin.exclude_dirs = "/media/keep\n\n/media/archive"
    plugin.exclude_keywords = "sample\n删我"

    assert plugin._ScrapeFileClean__is_excluded(Path("/media/keep/a.mkv")) is True
    assert plugin._ScrapeFileClean__is_excluded(Path("/media/other/a.mkv")) is False
    assert plugin._ScrapeFileClean__is_keyword_excluded(Path("/media/x/sample/a.mkv")) is True
    assert plugin._ScrapeFileClean__is_keyword_excluded(Path("/media/删我/a.mkv")) is True
    assert plugin._ScrapeFileClean__is_keyword_excluded(Path("/media/ok/a.mkv")) is False

    plugin.exclude_keywords = ""
    assert plugin._ScrapeFileClean__is_keyword_excluded(Path("/media/sample/a.mkv")) is False


# ---------------- 刮削文件识别 ----------------

def test_parse_custom_scrap_extensions_supports_separators():
    """自定义后缀支持换行、英文/中文逗号，自动补点并去重。"""
    plugin_class = _load_plugin().ScrapeFileClean

    assert plugin_class._parse_custom_scrap_extensions("nfo, .JPG\n，srt") == [".nfo", ".jpg", ".srt"]
    assert plugin_class._parse_custom_scrap_extensions("-thumb") == ["-thumb"]
    assert plugin_class._parse_custom_scrap_extensions("") == []
    assert plugin_class._parse_custom_scrap_extensions(".nfo,.nfo") == [".nfo"]


def test_scrap_extensions_merge_builtin_and_custom():
    """内置后缀与自定义后缀合并，且判定刮削文件时生效。"""
    plugin = _make_plugin(_load_plugin())
    plugin._custom_scrap_extensions = [".custom"]

    extensions = plugin._scrap_extensions()

    assert ".nfo" in extensions
    assert ".custom" in extensions
    assert plugin._is_scrap_file(Path("/media/Show/Show.nfo")) is True
    assert plugin._is_scrap_file(Path("/media/Show/Show.mkv")) is False


def test_same_media_scrap_name_requires_boundary():
    """刮削文件名需以媒体名为前缀并紧跟非字母数字边界，S01E01 不匹配 S01E010。"""
    plugin_class = _load_plugin().ScrapeFileClean

    assert plugin_class._same_media_scrap_name(Path("Show S01E01.nfo"), "Show S01E01") is True
    assert plugin_class._same_media_scrap_name(Path("Show S01E01"), "Show S01E01") is True
    assert plugin_class._same_media_scrap_name(Path("Show S01E010.nfo"), "Show S01E01") is False
    assert plugin_class._same_media_scrap_name(Path("Other.nfo"), "Show") is False


def test_belongs_to_other_media_detects_longer_stem():
    """同目录存在更长的其他媒体名时，其刮削文件不应被当前媒体清理。"""
    plugin_class = _load_plugin().ScrapeFileClean

    assert plugin_class._belongs_to_other_media("Film-2.nfo", "Film", {"Film-2"}) is True
    # 同 stem：刮削文件为两份媒体共享，删除时同样不能清理
    assert plugin_class._belongs_to_other_media("Film.nfo", "Film", {"Film"}) is True
    # 其他媒体名不比当前媒体名更长时不参与判定
    assert plugin_class._belongs_to_other_media("Film-2.nfo", "Film", {"Film-3"}) is False
    assert plugin_class._belongs_to_other_media("Film.nfo", "Film", set()) is False


# ---------------- 通知文本 ----------------

def test_build_notification_text_reports_actions():
    """通知文本按开关汇报清理动作，并区分立即/延迟。"""
    plugin = _make_plugin(_load_plugin())
    plugin._delete_history = True
    plugin._delete_scrap_infos = True

    single = plugin._build_notification_text(Path("/media/src/Show.mkv"), ["/media/lib/Show.mkv"], False)
    assert single.startswith("⚡ 立即删除完成")
    assert "🔗 硬链接：/media/lib/Show.mkv" in single
    assert "📝 已清理转移记录" in single
    assert "🖼️ 已清理刮削文件" in single
    assert "🌱 已联动删除种子" not in single

    multiple = plugin._build_notification_text(
        Path("/media/src/Show.mkv"), ["/media/lib/a.mkv", "/media/lib/b.mkv"], True
    )
    assert multiple.startswith("⏰ 延迟删除完成")
    assert "🔗 删除了 2 个硬链接文件" in multiple
