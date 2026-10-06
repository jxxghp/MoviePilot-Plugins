"""EMOS上传（EmosUpload）V3 专用实现的合同与纯逻辑单测。

按官方测试规范：通过生产命名空间 app.plugins.emosupload 导入插件
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
SOURCE = ROOT / "plugins.v3/emosupload/__init__.py"
PLUGIN_ID = "EmosUpload"

LEGACY_MODULE_PREFIXES = ("app.core.", "app.helper.", "app.utils.", "app.db.models")
LEGACY_MODULES = {"app.log", "app.plugins"}
LEGACY_SYMBOLS = (
    "SessionFactory",
    "AsyncSessionFactory",
    "ScopedSession",
    "MessageChannel",
    "NotificationType",
)


def _load_plugin():
    return importlib.import_module("app.plugins.emosupload")


def _make_plugin(module):
    """绕过运行时组装实例化插件，并补齐纯逻辑方法依赖的状态。"""
    plugin = object.__new__(module.EmosUpload)
    plugin._enabled = True
    plugin._skip_tags = "刷流,保种,seedbox"
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

    assert module.EmosUpload.plugin_version == "3.0.0"
    assert entry["version"] == "3.0.0"
    assert entry["system_version"] == ">=3.0.0"
    assert entry["history"]["v3.0.0"]
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


def test_notify_type_map_uses_v3_channel_enum():
    """通知渠道映射必须使用 V3 的 NotificationChannel 枚举成员。"""
    module = _load_plugin()
    from app.schemas.types import NotificationChannel

    mapping = module.EmosUpload._NOTIFY_TYPE_MAP
    assert mapping["telegram"] is NotificationChannel.Telegram
    assert mapping["webpush"] is NotificationChannel.WebPush
    assert all(isinstance(value, NotificationChannel) for value in mapping.values())


def test_command_and_api_contract():
    """远程命令与插件 API 声明保持既有契约，API 使用宿主登录态。"""
    plugin = _make_plugin(_load_plugin())
    from app.schemas.types import EventType

    commands = plugin.get_command()
    assert [item["cmd"] for item in commands] == ["/emos_status", "/emos_confirm"]
    assert all(item["event"] is EventType.PluginAction for item in commands)

    apis = plugin.get_api()
    assert [item["path"] for item in apis] == ["/status", "/pending"]
    assert all(item["auth"] == "bear" for item in apis)
    assert all(callable(item["endpoint"]) for item in apis)


def test_get_state_follows_enabled_flag():
    """启用状态跟随配置。"""
    plugin = _make_plugin(_load_plugin())

    assert plugin.get_state() is True
    plugin._enabled = False
    assert plugin.get_state() is False


# ---------------- 种子属性 ----------------

def test_torrent_completed_prefers_current_progress():
    """当前进度可读时以进度为准，进度缺失才回退完成时间。"""
    plugin_class = _load_plugin().EmosUpload

    assert plugin_class._torrent_completed({"progress": 1.0, "completion_on": 0}, "qbittorrent") is True
    assert plugin_class._torrent_completed(
        {"progress": 0.5, "completion_on": 1700000000}, "qbittorrent"
    ) is False
    assert plugin_class._torrent_completed({"completion_on": 1700000000}, "qbittorrent") is True
    assert plugin_class._torrent_completed("not-a-dict", "qbittorrent") is False

    assert plugin_class._torrent_completed(SimpleNamespace(percent_done=1.0), "transmission") is True
    assert plugin_class._torrent_completed(
        SimpleNamespace(percent_done=0.4, done_date=1700000000), "transmission"
    ) is False
    assert plugin_class._torrent_completed(SimpleNamespace(done_date=1700000000), "transmission") is True


def test_torrent_accessors_dispatch_per_downloader():
    """qBittorrent 字典与 Transmission 对象分别按各自字段解析种子属性。"""
    plugin_class = _load_plugin().EmosUpload

    assert plugin_class._torrent_hash({"hash": " ABC "}, "qbittorrent") == "ABC"
    assert plugin_class._torrent_tags({"tags": "a, b ,"}, "qbittorrent") == ["a", "b"]

    tr_torrent = SimpleNamespace(hash=" TR ", labels=["x", ""])
    assert plugin_class._torrent_hash(tr_torrent, "transmission") == "TR"
    assert plugin_class._torrent_tags(tr_torrent, "transmission") == ["x"]


def test_has_skip_tags_matches_configured_tags():
    """命中跳过标签的种子不上传；未配置或标签为空时不跳过。"""
    plugin = _make_plugin(_load_plugin())

    assert plugin._has_skip_tags([" 刷流 "]) is True
    assert plugin._has_skip_tags(["SEEDBOX"]) is True
    assert plugin._has_skip_tags(["其他"]) is False
    assert plugin._has_skip_tags([]) is False

    plugin._skip_tags = ""
    assert plugin._has_skip_tags(["刷流"]) is False


# ---------------- 展示与渠道 ----------------

def test_fmt_size_formats_gb_and_mb():
    """容量按 GB 优先展示，小于 1GB 时展示 MB。"""
    plugin_class = _load_plugin().EmosUpload

    assert plugin_class._fmt_size(1073741824) == "1.0GB"
    assert plugin_class._fmt_size(104857600) == "100.0MB"


def test_extract_resolution_normalizes_known_resolutions():
    """文件名中的分辨率统一归一化为大写标准写法。"""
    plugin = _make_plugin(_load_plugin())

    assert plugin._extract_resolution("Movie.2024.2160p.WEB-DL.mkv") == "2160P"
    assert plugin._extract_resolution("Movie.4K.mkv") == "2160P"
    assert plugin._extract_resolution("Movie.1080p.mkv") == "1080P"
    assert plugin._extract_resolution("Movie.mkv") == ""


def test_normalize_channels_maps_known_and_keeps_unknown():
    """已配置渠道映射为 NotificationChannel，未知渠道保持原字符串并去重。"""
    plugin_class = _load_plugin().EmosUpload
    from app.schemas.types import NotificationChannel

    result = plugin_class._normalize_channels(["telegram", "telegram", "feishu", "unknown", ""])

    assert result == [NotificationChannel.Telegram, NotificationChannel.Feishu, "unknown"]
    assert plugin_class._normalize_channels(None) == []
