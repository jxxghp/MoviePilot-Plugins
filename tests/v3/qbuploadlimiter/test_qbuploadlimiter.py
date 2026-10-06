"""QB上传限速（QbUploadLimiter）V3 专用实现的合同与纯逻辑单测。

按官方测试规范：通过生产命名空间 app.plugins.qbuploadlimiter 导入插件
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
SOURCE = ROOT / "plugins.v3/qbuploadlimiter/__init__.py"
PLUGIN_ID = "QbUploadLimiter"

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
    return importlib.import_module("app.plugins.qbuploadlimiter")


def _make_plugin(module):
    """绕过运行时组装实例化插件，并补齐纯逻辑方法依赖的状态。"""
    plugin = object.__new__(module.QbUploadLimiter)
    plugin._enabled = True
    plugin._sites = []
    plugin._site_share_ratios = {}
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

    assert module.QbUploadLimiter.plugin_version == "2.0.0"
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
    assert any(name.startswith("app.db.oper.") for name in modules)


def test_notify_type_map_uses_v3_channel_enum():
    """通知渠道映射必须使用 V3 的 NotificationChannel 枚举成员。"""
    module = _load_plugin()
    from app.schemas.types import NotificationChannel

    mapping = module.QbUploadLimiter._NOTIFY_TYPE_MAP
    assert mapping["telegram"] is NotificationChannel.Telegram
    assert mapping["qqbot"] is NotificationChannel.QQ
    assert all(isinstance(value, NotificationChannel) for value in mapping.values())


def test_api_command_and_state_contract():
    """插件不注册额外 API/命令，启用状态跟随配置。"""
    plugin = _make_plugin(_load_plugin())

    assert plugin.get_api() == []
    assert plugin.get_command() == []
    assert plugin.get_state() is True
    plugin._enabled = False
    assert plugin.get_state() is False


# ---------------- 配置规范化 ----------------

def test_to_int_accepts_integers_and_rejects_fractions():
    """整数开关只接受整数语义的取值，小数与科学计数法回退默认值。"""
    plugin_class = _load_plugin().QbUploadLimiter

    assert plugin_class._to_int("30", 0) == 30
    assert plugin_class._to_int(30.0, 0) == 30
    assert plugin_class._to_int("30.5", 7) == 7
    assert plugin_class._to_int("1e3", 7) == 7
    assert plugin_class._to_int(True, 7) == 7
    assert plugin_class._to_int(None, 7) == 7
    assert plugin_class._to_int("abc", 7) == 7


def test_to_ratio_rounds_to_single_decimal_and_falls_back():
    """分享率阈值最多保留 1 位小数，0/负数/NaN 一律回退默认值。"""
    plugin_class = _load_plugin().QbUploadLimiter

    assert plugin_class._to_ratio("2.34", 1.0) == 2.3
    assert plugin_class._to_ratio("1.26", 1.0) == 1.3
    assert plugin_class._to_ratio(0, 1.0) == 1.0
    assert plugin_class._to_ratio(-3, 1.0) == 1.0
    assert plugin_class._to_ratio(float("nan"), 1.0) == 1.0
    assert plugin_class._to_ratio("abc", 1.0) == 1.0
    assert plugin_class._to_ratio(None, 1.0) == 1.0


def test_normalize_config_list_dedupes_and_keeps_whole_string():
    """单字符串配置不再按字符拆分，列表配置去重并去除空白。"""
    plugin_class = _load_plugin().QbUploadLimiter

    assert plugin_class._normalize_config_list([" qb ", "qb", "", None, "tr"]) == ["qb", "tr"]
    assert plugin_class._normalize_config_list("qbittorrent") == ["qbittorrent"]
    assert plugin_class._normalize_config_list(None) == []


def test_normalize_channels_dedupes_and_trims():
    """通知渠道配置去重、去空白，忽略空值。"""
    plugin_class = _load_plugin().QbUploadLimiter

    assert plugin_class._normalize_channels(["telegram", "telegram", " feishu ", ""]) == [
        "telegram",
        "feishu",
    ]
    assert plugin_class._normalize_channels(None) == []


def test_normalize_site_share_ratios_parses_text_lines():
    """站点单独阈值支持「站点=阈值」文本，忽略注释、非法行与重复项。"""
    plugin = _make_plugin(_load_plugin())

    ratios, text = plugin._normalize_site_share_ratios("HDHome=2.5\n# 注释\n坏行\nCHD：3\nHDHome=1")

    assert ratios == {"hdhome": 1.0, "chd": 3.0}
    assert text.splitlines() == ["HDHome=1.0", "CHD=3.0"]


def test_normalize_site_share_ratios_accepts_mapping_and_drops_invalid():
    """字典配置同样生效，0 阈值的站点被丢弃。"""
    plugin = _make_plugin(_load_plugin())

    ratios, _text = plugin._normalize_site_share_ratios({"HDHome": "1.5", "坏站": 0})

    assert ratios == {"hdhome": 1.5}


def test_threshold_for_site_prefers_site_override():
    """已配置站点使用单独阈值，未配置或站点未知时回退全局阈值。"""
    plugin = _make_plugin(_load_plugin())
    plugin._site_share_ratios = {"hdhome": 2.5}

    assert plugin._threshold_for_site("HDHome", 1.0) == 2.5
    assert plugin._threshold_for_site("  ", 1.0) == 1.0
    assert plugin._threshold_for_site("other", 1.0) == 1.0


def test_selected_sites_returns_none_when_unset():
    """未勾选站点表示不筛选，勾选后返回小写站点集合。"""
    plugin = _make_plugin(_load_plugin())

    assert plugin._selected_sites() is None
    plugin._sites = [" HDHome ", "chd"]
    assert plugin._selected_sites() == {"hdhome", "chd"}


# ---------------- 下载器交互逻辑 ----------------

def test_effective_upload_limit_uses_qb_global_minimum():
    """qBittorrent 全局上传限速更低时取全局值，不限速或读取失败时用插件配置。"""
    plugin = _make_plugin(_load_plugin())

    class _FakeQb:
        def __init__(self, upload_limit):
            self._upload_limit = upload_limit

        def get_speed_limit(self):
            return (0, self._upload_limit)

    assert plugin._effective_upload_limit(_FakeQb(500), "qbittorrent", 2000) == 500
    assert plugin._effective_upload_limit(_FakeQb(3000), "qbittorrent", 2000) == 2000
    assert plugin._effective_upload_limit(_FakeQb(0), "qbittorrent", 2000) == 2000
    assert plugin._effective_upload_limit(_FakeQb(500), "transmission", 2000) == 2000
    assert plugin._effective_upload_limit(object(), "qbittorrent", 2000) == 2000


def test_torrent_accessors_dispatch_per_downloader():
    """qBittorrent 字典与 Transmission 对象分别按各自字段解析种子属性。"""
    plugin_class = _load_plugin().QbUploadLimiter
    torrent = {
        "hash": " ABC ",
        "name": "剧集",
        "tags": "刷流, 保种 ,",
        "category": " 电影 ",
    }

    assert plugin_class._torrent_hash(torrent, "qbittorrent") == "ABC"
    assert plugin_class._torrent_name(torrent, "qbittorrent") == "剧集"
    assert plugin_class._torrent_tags(torrent, "qbittorrent") == ["刷流", "保种"]
    assert plugin_class._torrent_category(torrent, "qbittorrent") == "电影"

    tr_torrent = SimpleNamespace(
        hashString="TRHASH",
        name="TR剧集",
        labels=["a", " b "],
        trackerList="http://t1/announce\n\nhttp://t2/announce",
    )
    assert plugin_class._torrent_hash(tr_torrent, "transmission") == "TRHASH"
    assert plugin_class._torrent_name(tr_torrent, "transmission") == "TR剧集"
    assert plugin_class._torrent_tags(tr_torrent, "transmission") == ["a", "b"]
    assert plugin_class._torrent_category(tr_torrent, "transmission") == ""
    assert plugin_class._torrent_tracker_urls(tr_torrent, "transmission") == [
        "http://t1/announce",
        "http://t2/announce",
    ]


def test_torrent_completed_prefers_current_progress():
    """当前进度可读时以进度为准，进度缺失才回退历史完成时间。"""
    plugin_class = _load_plugin().QbUploadLimiter

    assert plugin_class._torrent_completed({"progress": 1.0, "completion_on": 0}, "qbittorrent") is True
    assert plugin_class._torrent_completed(
        {"progress": 0.5, "completion_on": 1700000000}, "qbittorrent"
    ) is False
    assert plugin_class._torrent_completed({"completion_on": 1700000000}, "qbittorrent") is True
    assert plugin_class._torrent_completed({"completion_on": -1}, "qbittorrent") is False
    assert plugin_class._torrent_completed("not-a-dict", "qbittorrent") is False

    assert plugin_class._torrent_completed(SimpleNamespace(percentDone=1.0), "transmission") is True
    assert plugin_class._torrent_completed(
        SimpleNamespace(percentDone=0.4, doneDate=1700000000), "transmission"
    ) is False
    assert plugin_class._torrent_completed(SimpleNamespace(doneDate=1700000000), "transmission") is True


# ---------------- 站点与格式化 ----------------

def test_normalize_domain_strips_scheme_port_and_www():
    """域名提取统一小写，去掉协议、端口、路径与 www 前缀。"""
    plugin_class = _load_plugin().QbUploadLimiter

    assert plugin_class._normalize_domain("https://WWW.HDHome.org:443/announce?x=1") == "hdhome.org"
    assert plugin_class._normalize_domain("") == ""


def test_format_helpers():
    """限速与容量格式化保持既有展示语义。"""
    plugin_class = _load_plugin().QbUploadLimiter

    assert plugin_class._format_limit(0) == "不限速"
    assert plugin_class._format_limit(2000) == "2000 KB/s"
    assert plugin_class._format_bytes(0) == "0 B"
    assert plugin_class._format_bytes(1024 * 1024) == "1.00 MB"


# ---------------- V3 宿主数据访问 ----------------

def test_load_transferred_hashes_filters_successful_records(monkeypatch):
    """整理入库判定改为 Oper 查询后，仍只保留 status 为真的记录与去重后的 hash。"""
    module = _load_plugin()
    from app.db.oper import transferhistory as oper_module

    rows = {
        "hash-a": [
            SimpleNamespace(status=True, download_hash="hash-a"),
            SimpleNamespace(status=False, download_hash="hash-a-old"),
        ],
        "hash-b": [SimpleNamespace(status=None, download_hash="hash-b")],
    }
    calls = []

    class _FakeOper:
        def list_by_hash(self, download_hash):
            calls.append(download_hash)
            return rows.get(download_hash, [])

    monkeypatch.setattr(oper_module, "TransferHistoryOper", _FakeOper)

    assert module.QbUploadLimiter._load_transferred_hashes(["hash-a", "hash-b", "hash-a", ""]) == {
        "hash-a"
    }
    assert calls == ["hash-a", "hash-b"]


def test_load_transferred_hashes_skips_query_without_valid_hashes(monkeypatch):
    """没有有效 hash 时不访问数据库。"""
    module = _load_plugin()
    from app.db.oper import transferhistory as oper_module

    def _forbidden(*args, **kwargs):
        raise AssertionError("不应在没有有效 hash 时访问 Oper")

    monkeypatch.setattr(oper_module, "TransferHistoryOper", _forbidden)

    assert module.QbUploadLimiter._load_transferred_hashes(["", None]) == set()


def test_load_site_ratios_keeps_latest_snapshot_per_domain(monkeypatch):
    """站点账号分享率改用 SiteOper 后，仍按域名取最新快照并跳过失败记录。"""
    module = _load_plugin()
    from app.db.oper import site as site_module

    class _FakeSiteOper:
        def get_userdata(self):
            return [
                SimpleNamespace(
                    err_msg=None,
                    domain="HDHome.org",
                    ratio="2.0",
                    updated_day="2024-01-01",
                    updated_time="10:00:00",
                ),
                SimpleNamespace(
                    err_msg=None,
                    domain="hdhome.org",
                    ratio=3.0,
                    updated_day="2024-01-02",
                    updated_time="10:00:00",
                ),
                SimpleNamespace(
                    err_msg="抓取失败",
                    domain="fail.org",
                    ratio=9.0,
                    updated_day="2024-01-03",
                    updated_time="10:00:00",
                ),
                SimpleNamespace(
                    err_msg=None,
                    domain="",
                    ratio=1.0,
                    updated_day="2024-01-01",
                    updated_time="10:00:00",
                ),
                SimpleNamespace(
                    err_msg=None,
                    domain="zero.org",
                    ratio=0,
                    updated_day="2024-01-01",
                    updated_time="10:00:00",
                ),
            ]

    monkeypatch.setattr(site_module, "SiteOper", _FakeSiteOper)

    plugin = _make_plugin(module)

    assert plugin._load_site_ratios() == {"hdhome.org": 3.0}
