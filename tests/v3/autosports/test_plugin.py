"""
AutoSports 插件回归与单元测试。
"""

import copy
import json
from pathlib import Path
import socket
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from apscheduler.triggers.cron import CronTrigger
import pytest

import app.plugins.autosports as autosports_mod
from app.plugins.autosports import AutoSports
import app.plugins.autosports.monitor as monitor_mod
import app.plugins.autosports.recognition as recognition_mod
import app.plugins.autosports.search as search_mod
from app.plugins.autosports.search.indexer import build_sportscult_indexer
from app.plugins.autosports.search.models import Matchinfo
import app.plugins.autosports.ui as ui_mod
from app.domain.context import Context, MediaInfo, TorrentInfo
from app.domain.metainfo import MetaInfo
from app.modules.indexer.spider import SiteSpider
from app.schemas.file import FileItem
from app.schemas.transfer import TransferInfo
from app.schemas.types import MediaType
from app.sdk.plugin.base import _PluginBase


LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def block_external_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    阻断非本地网络解析，确保单测全程离线执行。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    orig_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        """
        校验目标主机是否为本地回环地址。
        """
        host_text = host.decode() if isinstance(host, bytes) else (host or "")
        if host_text not in LOCAL_HOSTS:
            raise AssertionError(f"测试禁止访问外部网络主机: {host_text}")
        return orig_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def reset_autosports_class_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    在每个测试用例前后隔离并还原 AutoSports 类级可变状态。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    state_defaults = {
        "_vault_cache": None,
        "_stamp_cache": {},
        "_match_crests": {},
        "_failed_matches": {},
        "_cached_matches": {},
        "_cached_matches_at": {},
        "_sportscult_site_id": None,
    }
    for attr_name, default_val in state_defaults.items():
        if hasattr(AutoSports, attr_name):
            fresh_val = default_val.copy() if isinstance(default_val, dict) else default_val
            monkeypatch.setattr(AutoSports, attr_name, fresh_val)


@pytest.fixture(autouse=True)
def ensure_system_config_for_metainfo(monkeypatch: pytest.MonkeyPatch):
    """
    确保插件仓独立运行时 MetaInfo() 所需的系统配置服务可用，并清理 Rust 解析选项缓存。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    from app.application import recognition as app_recognition
    from app.domain import metainfo as metainfo_module

    try:
        app_recognition.get_configured_system_config()
    except RuntimeError:
        fake_sysconfig = SimpleNamespace(get=lambda _key: None)
        monkeypatch.setattr(app_recognition, "get_configured_system_config", lambda: fake_sysconfig)
    metainfo_module.clear_rust_parse_options_cache()
    try:
        yield
    finally:
        metainfo_module.clear_rust_parse_options_cache()


class _FakeSitesHelper:
    """
    模拟 SitesHelper，用于替代测试引导中的最小站点存根。
    """

    def __init__(
        self,
        indexsites: list[dict] | None = None,
        indexers: list[dict] | None = None,
        auth_level: int = 2,
    ) -> None:
        """
        初始化模拟站点管理器状态。

        :param indexsites: 站点列表数据
        :param indexers: 索引器规则列表
        :param auth_level: 站点认证等级
        """
        self.indexsites = list(indexsites or [])
        self.indexers: dict[str, dict] = {}
        seed_indexers = self.indexsites if indexers is None else indexers
        for item in seed_indexers:
            key = str(item.get("domain") or item.get("name") or f"site-{len(self.indexers)}")
            self.indexers[key] = item
        self.auth_level = auth_level
        self.added_calls: list[tuple[str, dict]] = []

    def get_indexsites(self) -> list[dict]:
        """
        返回所有已索引站点信息。

        :return: 站点信息字典列表
        """
        return list(self.indexsites)

    def get_indexers(self) -> list[dict]:
        """
        返回全部索引器规则字典。

        :return: 索引器规则列表
        """
        return list(self.indexers.values())

    def get_indexer(self, domain: str) -> dict | None:
        """
        按域名查找对应的索引器规则。

        :param domain: 站点域名
        :return: 匹配的索引器规则或 None
        """
        if domain in self.indexers:
            return self.indexers[domain]
        for site in self.indexsites:
            site_url = str(site.get("url") or site.get("domain") or "")
            if domain and domain in site_url:
                return site
        return None

    def add_indexer(self, domain: str, indexer: dict) -> None:
        """
        记录并保存新增或覆盖的索引器规则，保留既有站点数字 ID。

        :param domain: 站点域名
        :param indexer: 索引器规则字典
        """
        self.added_calls.append((domain, indexer))
        stored = copy.deepcopy(indexer)
        existing = self.indexers.get(domain)
        if existing:
            if "id" in existing:
                stored["id"] = existing["id"]
            if "is_active" in existing:
                stored["is_active"] = existing["is_active"]
        self.indexers[domain] = stored


def _install_fake_sites_helper(
    monkeypatch: pytest.MonkeyPatch,
    *,
    indexsites: list[dict] | None = None,
    indexers: list[dict] | None = None,
    auth_level: int = 2,
) -> _FakeSitesHelper:
    """
    向 search 模块注入共享的模拟 SitesHelper 实例。

    :param monkeypatch: pytest 猴子补丁夹具
    :param indexsites: 站点信息列表
    :param indexers: 索引器规则列表
    :param auth_level: 站点认证等级
    :return: 创建的 _FakeSitesHelper 实例
    """
    helper = _FakeSitesHelper(indexsites=indexsites, indexers=indexers, auth_level=auth_level)
    monkeypatch.setattr(search_mod, "SitesHelper", lambda: helper)
    return helper


def _create_isolated_plugin(monkeypatch: pytest.MonkeyPatch) -> tuple[AutoSports, dict]:
    """
    构造不依赖外部数据库、下载器和系统消息的隔离插件实例。

    :param monkeypatch: pytest 猴子补丁夹具
    :return: 插件实例与状态记录字典的二元组
    """
    plugin = AutoSports()
    state = {
        "data": {},
        "configs": [],
        "messages": [],
    }
    monkeypatch.setattr(plugin, "get_data", lambda key=None: state["data"].get(key))
    monkeypatch.setattr(plugin, "save_data", lambda key, value: state["data"].__setitem__(key, value))
    monkeypatch.setattr(plugin, "update_config", lambda cfg, plugin_id=None: state["configs"].append(cfg))
    monkeypatch.setattr(plugin, "stop_service", lambda: None)
    monkeypatch.setattr(
        plugin,
        "systemmessage",
        SimpleNamespace(put=lambda message, title=None, **kwargs: state["messages"].append((title, message))),
    )
    fake_downloader = SimpleNamespace(get_configs=lambda: {})
    monkeypatch.setattr(autosports_mod, "DownloaderHelper", lambda: fake_downloader)
    return plugin, state


def _make_sportscult_torrent(
    *,
    title: str = "LaLiga 2026 04 12 Barcelona vs Real Madrid 1080p WEB-DL H264 EN",
    site: int | None = None,
    site_name: str | None = None,
    page_url: str | None = None,
    enclosure: str | None = None,
    seeders: int = 10,
    size: int = 4 * 1024**3,
) -> TorrentInfo:
    """
    构造用于搜索与过滤测试的 TorrentInfo 对象。

    :param title: 种子标题
    :param site: 站点 ID
    :param site_name: 站点名称
    :param page_url: 种子详情页链接
    :param enclosure: 种子下载链接
    :param seeders: 做种数
    :param size: 体积字节数
    :return: 填充完成的 TorrentInfo 实例
    """
    return TorrentInfo(
        title=title,
        site=site,
        site_name=site_name,
        page_url=page_url,
        enclosure=enclosure,
        seeders=seeders,
        size=size,
    )


def _valid_builtin_sportscult_indexer(site_id: int = 701, name: str = "SportsCult") -> dict:
    """
    构造与官方可用规则一致的内置 Sportscult 索引器配置。

    :param site_id: 站点 ID
    :param name: 站点名称
    :return: 索引器规则字典
    """
    indexer = copy.deepcopy(build_sportscult_indexer())
    indexer["id"] = site_id
    indexer["name"] = name
    indexer["domain"] = "sportscult.org"
    indexer["is_active"] = True
    return indexer


def _run_coro_sync(coro):
    """
    以无事件循环的同步方式推进不挂起的协程对象，避免 Windows 沙箱 socketpair 阻塞。

    :param coro: 待执行的协程对象
    :return: 协程返回值
    """
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    finally:
        coro.close()
    raise AssertionError("异步识别方法在离线单测中不应挂起等待")


def test_plugin_metadata_and_default_form() -> None:
    """
    验证插件版本号、SDK 基类继承、默认表单字段与模块/API 暴露。
    """
    assert AutoSports.plugin_version == "3.1.1"
    assert issubclass(AutoSports, _PluginBase)
    assert AutoSports.MEDIA_SOURCE == "autosports"
    assert AutoSports.MEDIA_SOURCE_NAME == "AutoSports"

    plugin = AutoSports()
    form_layout, default_model = plugin.get_form()
    assert default_model.get("lowest_pix") == "720"
    assert "lowest_px" not in default_model

    # 表单中的单值字段应使用单行 VTextField，避免输入换行符
    field_types: dict[str, str] = {}

    def _collect_fields(node) -> None:
        """
        递归收集表单配置里 model 对应的 Vuetify 组件类型。
        """
        if isinstance(node, list):
            for item in node:
                _collect_fields(item)
        elif isinstance(node, dict):
            props = node.get("props") or {}
            model = props.get("model")
            if model and node.get("component"):
                field_types[model] = node["component"]
            _collect_fields(node.get("content"))

    _collect_fields(form_layout)
    assert field_types.get("football_apikey") == "VTextField"
    assert field_types.get("max_download") == "VTextField"

    api_paths = {item["path"] for item in plugin.get_api()}
    assert {"/delete_history", "/history_page"} <= api_paths

    modules = plugin.get_module()
    assert set(modules) == {"filter_torrents", "recognize_media", "async_recognize_media"}


def test_init_plugin_requires_football_apikey(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证启用插件但未配置 football_apikey 时会自动停用并发送提示消息，且不启动监听线程。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    _install_fake_sites_helper(monkeypatch)
    plugin, state = _create_isolated_plugin(monkeypatch)

    observer_started = []
    if hasattr(autosports_mod, "Observer"):
        monkeypatch.setattr(autosports_mod, "Observer", lambda *a, **kw: observer_started.append(True))

    plugin.init_plugin({"enabled": True, "football_apikey": "", "cron": "0 8 * * *"})

    assert plugin._enabled is False  # pylint: disable=protected-access
    assert state["messages"]
    assert not observer_started


@pytest.mark.parametrize(
    ("size_range", "expected_valid", "expected_after"),
    [
        ("5-20", True, "5-20"),
        ("10", True, "10"),
        ("20-10", False, None),
        ("invalid-size", False, None),
        ("10-20-30", False, None),
    ],
)
def test_validate_and_fix_config_size_range(
    monkeypatch: pytest.MonkeyPatch,
    size_range: str,
    expected_valid: bool,
    expected_after: str | None,
) -> None:
    """
    验证大小范围配置校验与非法值自动清理行为。

    :param monkeypatch: pytest 猴子补丁夹具
    :param size_range: 待校验的体积范围字符串
    :param expected_valid: 预期校验返回值
    :param expected_after: 校验后 config 中的 size_range 值
    """
    plugin, _ = _create_isolated_plugin(monkeypatch)
    logged_errors = []
    monkeypatch.setattr(plugin, "_log_and_notify_error", lambda msg: logged_errors.append(msg))

    cfg = {"size_range": size_range}
    assert plugin._validate_and_fix_config(cfg) is expected_valid  # pylint: disable=protected-access
    assert cfg["size_range"] == expected_after
    assert bool(logged_errors) is (not expected_valid)


def test_get_service_schedules(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证插件在不同启用状态与 cron 配置下的定时任务输出。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    plugin, _ = _create_isolated_plugin(monkeypatch)

    plugin._enabled = False  # pylint: disable=protected-access
    assert plugin.get_service() == []

    plugin._enabled = True  # pylint: disable=protected-access
    plugin._cron = "15 6 * * *"  # pylint: disable=protected-access
    cron_services = plugin.get_service()
    assert len(cron_services) == 1
    assert isinstance(cron_services[0]["trigger"], CronTrigger)

    plugin._cron = ""  # pylint: disable=protected-access
    interval_services = plugin.get_service()
    assert len(interval_services) == 1
    assert interval_services[0]["trigger"] == "interval"
    assert interval_services[0]["kwargs"].get("hours") == 12

    plugin._cron = "not-a-valid-cron"  # pylint: disable=protected-access
    fallback_services = plugin.get_service()
    assert len(fallback_services) == 1
    assert fallback_services[0]["trigger"] == "interval"
    assert fallback_services[0]["kwargs"].get("hours") == 12


def test_sportscult_indexer_urls_with_site_spider() -> None:
    """
    验证 Sportscult 索引器 URL 模板以及 SiteSpider 生成的搜索和浏览地址。
    """
    indexer = build_sportscult_indexer()
    assert indexer["domain"] == "https://sportscult.org/"

    search_path = indexer["search"]["paths"][0]["path"]
    assert search_path == "index.php?page=torrents&active=1&gold=0&search={keyword}&order=3&by=2"
    assert "&&order" not in search_path

    assert indexer["browse"]["path"] == "index.php?page=torrents&active=1&gold=0&order=3&by=2&pages={page}"
    assert indexer["browse"]["start"] == 1

    spider_search = SiteSpider(indexer=indexer, keyword="Real Madrid", page=1)
    search_url = spider_search._SiteSpider__get_search_url()  # pylint: disable=protected-access
    assert "index.php?page=torrents" in search_url
    assert "&order=3" in search_url
    assert "&&order" not in search_url
    assert "Real" in search_url

    spider_browse = SiteSpider(indexer=indexer, keyword="", page=0)
    browse_url_first = spider_browse._SiteSpider__get_search_url()  # pylint: disable=protected-access
    assert "pages=1" in browse_url_first

    spider_browse_next = SiteSpider(indexer=indexer, keyword="", page=2)
    browse_url_next = spider_browse_next._SiteSpider__get_search_url()  # pylint: disable=protected-access
    assert "pages=3" in browse_url_next


def test_sportscult_spider_parse_normal_gold_silver_rows() -> None:
    """
    验证 SiteSpider 使用插件索引器配置解析常规、免费与半价种子行的正确性。
    """
    indexer = build_sportscult_indexer()
    spider = SiteSpider(indexer=indexer, keyword="LaLiga", page=1)
    html = """
    <html>
      <body>
        <table class="lista">
          <tr>
            <td class="header">Cat</td>
            <td class="header">Name</td>
            <td class="header">DL</td>
            <td class="header">Size</td>
            <td class="header">Added</td>
            <td class="header">S</td>
            <td class="header">L</td>
            <td class="header">C</td>
          </tr>
          <tr>
            <td class="lista"><a href="index.php?page=torrents&category=18">Football</a></td>
            <td class="lista specialPadding">
              <a href="index.php?page=torrent-details&id=101">LaLiga Real Madrid vs Barcelona 1080p EN</a>
            </td>
            <td class="lista"><a href="download.php?id=101&f=laliga.torrent">DL</a></td>
            <td class="lista">4.50 GB</td>
            <td class="lista">2026-04-12 20:00:00</td>
            <td class="lista"><a href="#">25</a></td>
            <td class="lista"><a href="#">3</a></td>
            <td class="lista"><a href="#" alt="Football">100</a></td>
          </tr>
          <tr>
            <td class="lista"><a href="index.php?page=torrents&category=18">Football</a></td>
            <td class="lista specialPadding">
              <a href="index.php?page=torrent-details&id=102">UCL Arsenal vs Bayern 1080p</a>
              <img src="images/gold.gif" alt="gold" />
            </td>
            <td class="lista"><a href="download.php?id=102&f=ucl.torrent">DL</a></td>
            <td class="lista">6.00 GB</td>
            <td class="lista">2026-04-11 21:00:00</td>
            <td class="lista"><a href="#">40</a></td>
            <td class="lista"><a href="#">2</a></td>
            <td class="lista"><a href="#" alt="Champions League">150</a></td>
          </tr>
          <tr>
            <td class="lista"><a href="index.php?page=torrents&category=18">Football</a></td>
            <td class="lista specialPadding">
              <a href="index.php?page=torrent-details&id=103">EPL Liverpool vs Chelsea 720p</a>
              <img src="images/silver.gif" alt="silver" />
            </td>
            <td class="lista"><a href="download.php?id=103&f=epl.torrent">DL</a></td>
            <td class="lista">2.50 GB</td>
            <td class="lista">2026-04-10 19:00:00</td>
            <td class="lista"><a href="#">12</a></td>
            <td class="lista"><a href="#">1</a></td>
            <td class="lista"><a href="#" alt="English Premier League">60</a></td>
          </tr>
        </table>
      </body>
    </html>
    """
    torrents = spider.parse(html)
    assert len(torrents) == 3
    assert torrents[0]["title"] == "LaLiga Real Madrid vs Barcelona 1080p EN"
    assert torrents[0]["seeders"] == 25
    assert torrents[0]["downloadvolumefactor"] == 1.0
    assert torrents[1]["downloadvolumefactor"] == 0.0
    assert torrents[2]["downloadvolumefactor"] == 0.5


@pytest.mark.parametrize(
    ("scenario", "expect_add_indexer"),
    [
        ("missing_builtin", True),
        ("valid_builtin", False),
        ("broken_search_browse_php", True),
        ("broken_browse_page_param", True),
    ],
)
def test_ensure_sportscult_indexer_builtin_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expect_add_indexer: bool,
) -> None:
    """
    验证内置 Sportscult 索引器优先复用与缺失/损坏场景下的插件兜底覆盖逻辑。

    :param monkeypatch: pytest 猴子补丁夹具
    :param scenario: 测试场景标识
    :param expect_add_indexer: 是否预期调用 add_indexer 注册插件规则
    """
    if scenario == "missing_builtin":
        helper = _install_fake_sites_helper(monkeypatch, indexsites=[], indexers=[], auth_level=0)
    elif scenario == "valid_builtin":
        valid = _valid_builtin_sportscult_indexer()
        helper = _install_fake_sites_helper(monkeypatch, indexsites=[valid], indexers=[valid])
    elif scenario == "broken_search_browse_php":
        broken = _valid_builtin_sportscult_indexer()
        broken["search"]["paths"][0]["path"] = "browse.php?search={keyword}"
        helper = _install_fake_sites_helper(monkeypatch, indexsites=[broken], indexers=[broken])
    else:
        broken = _valid_builtin_sportscult_indexer()
        broken["browse"] = {"path": "?p={page}", "start": 0}
        helper = _install_fake_sites_helper(monkeypatch, indexsites=[broken], indexers=[broken])

    AutoSports._ensure_sportscult_indexer()  # pylint: disable=protected-access
    assert (len(helper.added_calls) > 0) is expect_add_indexer
    if expect_add_indexer:
        domain, added_rule = helper.added_calls[0]
        assert domain == "sportscult.org"
        assert "index.php?page=torrents" in added_rule["search"]["paths"][0]["path"]


def test_deferred_auth_ensures_indexer_in_check_and_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证宿主延迟完成站点认证后，check() 与 filter_torrents() 仍会重新补全索引器与站点 ID。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    helper = _install_fake_sites_helper(monkeypatch, indexsites=[], indexers=[], auth_level=0)
    plugin, _ = _create_isolated_plugin(monkeypatch)
    plugin._football_apikey = "dummy-key"  # pylint: disable=protected-access
    plugin._sportscult_site_id = None  # pylint: disable=protected-access

    plugin.chain = SimpleNamespace(
        filter_torrents=lambda rule_groups=None, torrent_list=None, mediainfo=None: [],
        async_search_by_id=MagicMock(),
    )

    sc_torrent = _make_sportscult_torrent(page_url="https://sportscult.org/index.php?page=torrent-details&id=5")
    filtered = plugin.filter_torrents([], [sc_torrent])
    assert len(filtered) == 1
    assert len(helper.added_calls) >= 1

    # 模拟站点在运行期间才进入已索引站点列表，并在 check() 阶段检测修复损坏的内置规则
    helper.added_calls.clear()
    broken_site = _valid_builtin_sportscult_indexer(site_id=505)
    broken_site["search"]["paths"][0]["path"] = "browse.php?search={keyword}"
    helper.indexsites = [broken_site]
    helper.indexers = {"sportscult.org": broken_site}
    helper.auth_level = 2

    plugin._teams_info = "Real Madrid"  # pylint: disable=protected-access
    plugin._action = "download"  # pylint: disable=protected-access
    plugin._sync_all = False  # pylint: disable=protected-access
    monkeypatch.setattr(plugin, "_exists_match", lambda use_cache=True: {})
    monkeypatch.setattr(
        search_mod,
        "SearchChain",
        lambda: SimpleNamespace(search_by_title=lambda *a, **kw: []),
    )

    plugin.check()
    assert len(helper.added_calls) == 1
    assert plugin._sportscult_site_id == 505  # pylint: disable=protected-access


@pytest.mark.parametrize(
    ("indexsites", "expected_id"),
    [
        ([{"id": 42, "name": "Custom Tracker", "domain": "sportscult.org", "is_active": True}], 42),
        ([{"id": 77, "name": "SportsCult", "domain": "mirror.example", "is_active": True}], 77),
        ([{"id": 99, "name": "sportscult", "is_active": True}], 99),
        ([{"id": 66, "name": "SportsCult", "domain": "sportscult.org", "is_active": False}], None),
        ([{"id": 12, "name": "OtherSite", "domain": "other.example", "is_active": True}], None),
    ],
)
def test_get_sportscult_indexer_domain_and_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    indexsites: list[dict],
    expected_id: int | None,
) -> None:
    """
    验证 get_sportscult_indexer() 的域名优先与大小写不敏感匹配规则。

    :param monkeypatch: pytest 猴子补丁夹具
    :param indexsites: 模拟的站点索引列表
    :param expected_id: 预期匹配的站点 ID
    """
    _install_fake_sites_helper(monkeypatch, indexsites=indexsites)
    assert AutoSports.get_sportscult_indexer() == expected_id


def test_is_sportscult_torrent_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证 _is_sportscult_torrent() 对站点名称、详情链接、下载链接与站点 ID 的识别能力。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    _install_fake_sites_helper(
        monkeypatch,
        indexsites=[{"id": 88, "name": "CustomSC", "domain": "sportscult.org", "is_active": True}],
    )
    plugin, _ = _create_isolated_plugin(monkeypatch)

    assert plugin._is_sportscult_torrent(  # pylint: disable=protected-access
        _make_sportscult_torrent(site_name="SportsCult")
    )
    assert plugin._is_sportscult_torrent(  # pylint: disable=protected-access
        _make_sportscult_torrent(page_url="https://sportscult.org/index.php?page=torrent-details&id=1")
    )
    assert plugin._is_sportscult_torrent(  # pylint: disable=protected-access
        _make_sportscult_torrent(enclosure="https://sportscult.org/download.php?id=1")
    )
    assert plugin._is_sportscult_torrent(  # pylint: disable=protected-access
        _make_sportscult_torrent(site=88)
    )
    assert not plugin._is_sportscult_torrent(  # pylint: disable=protected-access
        _make_sportscult_torrent(
            site=1,
            site_name="MTeam",
            page_url="https://other.example/details.php?id=1",
            enclosure="https://other.example/download.php?id=1",
        )
    )


def test_filter_torrents_bypass_builtin_flag_and_recursion_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证 filter_torrents() 在放行旁路、内置搜索开关与递归防重入保护下的行为。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    _install_fake_sites_helper(monkeypatch, indexsites=[_valid_builtin_sportscult_indexer(site_id=18)])
    plugin, _ = _create_isolated_plugin(monkeypatch)
    plugin._filter_builtin_search = False  # pylint: disable=protected-access

    sc_torrent = _make_sportscult_torrent(site=18, site_name="SportsCult")
    other_torrent = _make_sportscult_torrent(title="Other Match", site=9, site_name="Other")
    plugin.chain = SimpleNamespace(
        filter_torrents=lambda rule_groups=None, torrent_list=None, mediainfo=None: [other_torrent]
    )

    # 仅返回被宿主过滤掉的本站种子，供宿主与自身保留结果合并
    result = plugin.filter_torrents(["default"], [sc_torrent, other_torrent])
    assert result == [sc_torrent]

    # 启用内置过滤搜索时不再把宿主过滤掉的 Sportscult 种子旁路放回
    plugin._filter_builtin_search = True  # pylint: disable=protected-access
    result_strict = plugin.filter_torrents(["default"], [sc_torrent, other_torrent])
    assert result_strict == []

    # 模拟内部重入调用时，_filter_isolation 阻止无限递归
    plugin._filter_builtin_search = False  # pylint: disable=protected-access
    inner_returns = []

    def reentrant_filter(rule_groups=None, torrent_list=None, mediainfo=None):
        """
        触发一次插件自身 filter_torrents() 重入以检验隔离保护。
        """
        if not inner_returns:
            inner_returns.append(plugin.filter_torrents(rule_groups, torrent_list, mediainfo))
        return []

    plugin.chain = SimpleNamespace(filter_torrents=reentrant_filter)
    guarded = plugin.filter_torrents(["default"], [sc_torrent])
    assert inner_returns == [[]]
    assert guarded == [sc_torrent]


def test_find_best_selection_and_vault_match() -> None:
    """
    验证 find_best() 的画质、语言与做种数择优规则以及 is_match_in_vault() 查重逻辑。
    """
    media = MediaInfo(title="西甲", year="2026")
    meta = MetaInfo(title="西甲")
    meta.title = "西甲"
    meta.begin_season = 2026
    meta.begin_episode = 11
    meta.set_episode(11)

    t_low = Matchinfo(
        torrentinfo=_make_sportscult_torrent(title="480p", seeders=100),
        mediainfo=media,
        metainfo=meta,
        language="en",
        pix=480,
    )
    t_720_ru = Matchinfo(
        torrentinfo=_make_sportscult_torrent(title="720p RU", seeders=80),
        mediainfo=media,
        metainfo=meta,
        language="ru",
        pix=720,
    )
    t_1080_en_low_seed = Matchinfo(
        torrentinfo=_make_sportscult_torrent(title="1080p EN low", seeders=5),
        mediainfo=media,
        metainfo=meta,
        language="en",
        pix=1080,
    )
    t_1080_en_high_seed = Matchinfo(
        torrentinfo=_make_sportscult_torrent(title="1080p EN high", seeders=30),
        mediainfo=media,
        metainfo=meta,
        language="en",
        pix=1080,
    )

    matches = [t_1080_en_low_seed]
    AutoSports.find_best(force_en=True, lowest_pix=720, matchesinfo=matches, new_matchinfo=t_low)
    assert matches == [t_1080_en_low_seed]

    AutoSports.find_best(force_en=True, lowest_pix=720, matchesinfo=matches, new_matchinfo=t_720_ru)
    assert matches == [t_1080_en_low_seed]

    AutoSports.find_best(force_en=True, lowest_pix=720, matchesinfo=matches, new_matchinfo=t_1080_en_high_seed)
    assert matches == [t_1080_en_high_seed]

    exist_matches = {"西甲": {2026: [11]}}
    assert AutoSports.is_match_in_vault(exist_matches, meta) is True

    meta_missing = MetaInfo(title="西甲")
    meta_missing.title = "西甲"
    meta_missing.begin_season = 2026
    meta_missing.begin_episode = 12
    meta_missing.set_episode(12)
    assert AutoSports.is_match_in_vault(exist_matches, meta_missing) is False


def test_recognition_team_matching_and_date() -> None:
    """
    验证球队名标准化、双队匹配打分以及标题日期提取工具方法。
    """
    normalized = AutoSports.normalize_team_name("FC Atlético de Madrid.")
    assert "atletico" in normalized
    assert "madrid" in normalized

    score_match = AutoSports.team_name_score(
        ["Real Madrid", "Barcelona"],
        full_name="Real Madrid CF",
        short_name="Real Madrid",
    )
    score_miss = AutoSports.team_name_score(
        ["Arsenal", "Chelsea"],
        full_name="Real Madrid CF",
        short_name="Real Madrid",
    )
    assert score_match > 0
    assert score_miss == 0

    assert AutoSports.extract_date("LaLiga 2026 04 12 Real Madrid vs Barcelona 1080p") == (2026, 4, 12)
    assert AutoSports.extract_date("LaLiga.2026.04.12.Real.Madrid.vs.Barcelona.1080p") == (2026, 4, 12)
    assert AutoSports.extract_date("LaLiga_2026-04-12_Real_Madrid_vs_Barcelona") == (2026, 4, 12)
    assert AutoSports.extract_date("UCL 2026/04/12 Arsenal vs Bayern") == (2026, 4, 12)
    assert AutoSports.extract_date("UCL 12-04-2026 Arsenal vs Bayern 1080p") == (2026, 4, 12)
    assert AutoSports.extract_date("Match 20260412") == (2026, 4, 12)
    assert AutoSports.extract_date("Invalid date 2026-02-31 or 2026-13-01") is None

    lang_cases = [
        ("LaLiga Arsenal vs Valencia 1080p Spanish", "sp"),
        ("EPL Napoli vs Chelsea 1080p", "en"),
        ("LaLiga Atletico de Madrid vs Sevilla 1080p", "en"),
        ("UCL Real Madrid vs PSG 1080p PL", "pl"),
        ("Bundesliga Bayern vs Dortmund 1080p German", "de"),
    ]
    for title_str, expected_lang in lang_cases:
        lang_meta = MetaInfo(title=title_str)
        lang_meta.org_string = title_str
        assert AutoSports.recognize_language(lang_meta) == expected_lang


def test_recognition_online_and_offline_competitions(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证在线联赛接口伪造响应识别（LaLiga/UCL）及纯离线赛事识别（国王杯 CDR）。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    plugin, _ = _create_isolated_plugin(monkeypatch)
    plugin._football_apikey = "fake-football-token"  # pylint: disable=protected-access

    mock_matches = {
        "competitions/PD/matches": {
            "matches": [
                {
                    "id": 9001,
                    "utcDate": "2026-04-12T19:00:00Z",
                    "competition": {"code": "PD", "name": "Primera Division", "type": "LEAGUE"},
                    "season": {"startDate": "2025-08-15"},
                    "matchday": 31,
                    "stage": "REGULAR_SEASON",
                    "homeTeam": {"name": "Real Madrid CF", "shortName": "Real Madrid", "crest": "https://img/rm.png"},
                    "awayTeam": {"name": "FC Barcelona", "shortName": "Barça", "crest": "https://img/fcb.png"},
                }
            ]
        },
        "competitions/CL/matches": {
            "matches": [
                {
                    "id": 9002,
                    "utcDate": "2026-04-15T19:00:00Z",
                    "competition": {"code": "CL", "name": "UEFA Champions League", "type": "CUP"},
                    "season": {"startDate": "2025-09-10"},
                    "matchday": 2,
                    "stage": "QUARTER_FINALS",
                    "homeTeam": {"name": "Arsenal FC", "shortName": "Arsenal", "crest": ""},
                    "awayTeam": {"name": "FC Bayern München", "shortName": "Bayern", "crest": ""},
                }
            ]
        },
    }

    class _FakeResponse:
        """
        模拟 football-data HTTP JSON 响应对象。
        """

        def __init__(self, payload: dict, status_code: int = 200) -> None:
            """
            初始化模拟响应体与状态码。

            :param payload: JSON 载荷字典
            :param status_code: HTTP 状态码
            """
            self._payload = payload
            self.status_code = status_code

        def json(self) -> dict:
            """
            返回预置 JSON 字典。

            :return: JSON 字典
            """
            return self._payload

    class _FakeRequestUtils:
        """
        拦截 RequestUtils 对 football-data.org 的在线请求。
        """

        def __init__(self, *args, **kwargs) -> None:
            """
            接收并忽略默认请求工具初始化参数。
            """

        @staticmethod
        def get_res(url: str, **kwargs):
            """
            按请求路径返回模拟赛程响应。

            :param url: 请求地址
            :param kwargs: 额外请求参数
            :return: _FakeResponse 实例或 None
            """
            for key, payload in mock_matches.items():
                if key in url:
                    return _FakeResponse(payload)
            return None

    monkeypatch.setattr(recognition_mod, "RequestUtils", _FakeRequestUtils)

    # 在线识别：西甲 PD（标题采用空格分隔日期以符合 extract_date 解析约定）
    laliga_meta = MetaInfo(title="LaLiga 2026 04 12 Real Madrid vs Barcelona 1080p WEB-DL")
    laliga_media = plugin.recognize_competition_mediainfo(meta_info=laliga_meta)
    assert laliga_media is not None
    laliga_recognized, laliga_ep = plugin.recognized_match_metainfo(laliga_media, laliga_meta)
    assert laliga_recognized is not None
    assert laliga_recognized.begin_season == 2025
    assert laliga_recognized.begin_episode == 31
    assert laliga_ep is not None

    # 在线识别：欧冠 CL
    ucl_meta = MetaInfo(title="UEFA Champions League 2026 04 15 Arsenal vs Bayern 1080p")
    ucl_media = plugin.recognize_competition_mediainfo(meta_info=ucl_meta)
    assert ucl_media is not None
    ucl_recognized, _ = plugin.recognized_match_metainfo(ucl_media, ucl_meta)
    assert ucl_recognized is not None

    # 离线识别：西班牙国王杯 CDR（无需在线 API）
    cdr_meta = MetaInfo(title="Copa del Rey 2026 04 18 Real Madrid vs Barcelona Final 1080p")
    cdr_media = plugin.recognize_competition_mediainfo(meta_info=cdr_meta)
    assert cdr_media is not None
    cdr_recognized, _ = plugin.recognized_match_metainfo(cdr_media, cdr_meta)
    assert cdr_recognized is not None


def test_recognition_media_source_isolation_and_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证 recognize_media 与 async_recognize_media 对外部媒体源的隔离及内部 ID 往返还原。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    plugin, _ = _create_isolated_plugin(monkeypatch)
    meta = MetaInfo(title="LaLiga 2026 04 12 Real Madrid vs Barcelona 1080p")

    assert plugin.recognize_media(meta=meta, media_source="tmdb", media_id="12345") is None
    assert _run_coro_sync(plugin.async_recognize_media(meta=meta, media_source="douban", media_id="999")) is None

    encoded_id = plugin._encode_media_id({"c": "西班牙足球甲级联赛", "s": "2025"})  # pylint: disable=protected-access
    restored = plugin.recognize_media(
        meta=meta,
        mtype=MediaType.TV,
        media_source=AutoSports.MEDIA_SOURCE,
        media_id=encoded_id,
    )
    assert restored is not None
    assert restored.media_source == AutoSports.MEDIA_SOURCE
    assert restored.media_id == encoded_id

    restored_async = _run_coro_sync(
        plugin.async_recognize_media(
            meta=meta,
            mtype=MediaType.TV,
            media_source=AutoSports.MEDIA_SOURCE,
            media_id=encoded_id,
        )
    )
    assert restored_async is not None
    assert restored_async.media_source == AutoSports.MEDIA_SOURCE
    assert restored_async.media_id == encoded_id


def test_monitor_exists_match_and_vault_integration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    验证 Monitor._exists_match() 扫描本地媒体库并配合 Search.is_match_in_vault() 判定已入库场次。

    :param monkeypatch: pytest 猴子补丁夹具
    :param tmp_path: 临时媒体目录路径
    """
    monkeypatch.setattr(monitor_mod.settings, "LOCAL_EXISTS_SEARCH", True)
    plugin, _ = _create_isolated_plugin(monkeypatch)
    plugin._dest_path = str(tmp_path)  # pylint: disable=protected-access

    target_dir = tmp_path / "西班牙足球甲级联赛"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "西班牙足球甲级联赛 S2026E11.mkv").write_bytes(b"")

    existing = plugin._exists_match(use_cache=False)  # pylint: disable=protected-access
    assert existing

    gotten_meta = MetaInfo(title="西班牙足球甲级联赛 S2026E11")
    gotten_meta.title = "西班牙足球甲级联赛"
    gotten_meta.begin_season = 2026
    gotten_meta.begin_episode = 11
    gotten_meta.set_episode(11)
    assert AutoSports.is_match_in_vault(existing, gotten_meta) is True


def test_ui_api_pages_and_delete_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证 UI 页面渲染、历史分页接口及删除历史接口的 API Token 鉴权与数据变更。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    monkeypatch.setattr(ui_mod.settings, "API_TOKEN", "test-secret")
    plugin, state = _create_isolated_plugin(monkeypatch)

    sample_history = [
        {
            "competition_name": "西班牙足球甲级联赛",
            "season": 2025,
            "roundinfo": "第31轮",
            "title": "Real Madrid vs Barcelona",
            "date": "2026-04-12",
            "pix": "1080p",
            "language": "en",
            "size": "4.5 GB",
            "time": "2026-04-12 22:00:00",
            "torrent": "sc-101",
            "key": "PD-2025-31",
        }
    ]
    state["data"]["history"] = list(sample_history)

    page = plugin.get_page()
    assert isinstance(page, list)
    assert page

    denied_page = plugin.history_page(direction="next", apikey="wrong")
    assert denied_page.success is False

    ok_page = plugin.history_page(direction="next", apikey="test-secret")
    assert ok_page.success is True

    denied_del = plugin.delete_history(key="西班牙足球甲级联赛", roundinfo="第31轮", apikey="wrong")
    assert denied_del.success is False
    assert len(state["data"]["history"]) == 1

    ok_del = plugin.delete_history(key="西班牙足球甲级联赛", roundinfo="第31轮", apikey="test-secret")
    assert ok_del.success is True
    assert state["data"]["history"] == []


def test_init_plugin_config_edges_and_clear(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    验证目录监控边界防护、need_rename 保持、apikey 去空白及 clear 保存即清空行为。

    :param monkeypatch: pytest 猴子补丁夹具
    :param tmp_path: pytest 临时目录夹具
    """
    _install_fake_sites_helper(monkeypatch)
    observer_calls = []
    monkeypatch.setattr(autosports_mod, "Observer", lambda *a, **kw: observer_calls.append(True))

    # save_path 为空时不启动 Observer，并清理 apikey 首尾空白与保留 need_rename=False
    plugin, state = _create_isolated_plugin(monkeypatch)
    plugin.init_plugin({
        "enabled": True,
        "football_apikey": "  trimmed-key\n ",
        "save_path": "",
        "need_rename": False,
    })
    assert not observer_calls
    assert plugin._football_apikey == "trimmed-key"  # pylint: disable=protected-access
    assert plugin._need_rename is False  # pylint: disable=protected-access

    # save_path 不存在时不启动 Observer
    missing_dir = tmp_path / "missing_downloads"
    plugin.init_plugin({
        "enabled": True,
        "football_apikey": "key",
        "save_path": str(missing_dir),
    })
    assert not observer_calls
    assert state["messages"]

    # dest_path 为 save_path 子目录时不启动 Observer
    state["messages"].clear()
    save_dir = tmp_path / "downloads"
    dest_sub = save_dir / "library"
    dest_sub.mkdir(parents=True)
    plugin.init_plugin({
        "enabled": True,
        "football_apikey": "key",
        "save_path": str(save_dir),
        "dest_path": str(dest_sub),
    })
    assert not observer_calls
    assert state["messages"]

    # clear=True 在保存配置时立即清空持久化历史
    state["data"]["history"] = [{"competition_name": "西班牙足球甲级联赛", "roundinfo": "S2025E31"}]
    plugin.init_plugin({
        "enabled": False,
        "football_apikey": "key",
        "clear": True,
    })
    assert state["data"]["history"] == []


def test_monitor_get_thumb_and_handle_file_protections(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    验证 ffmpeg 参数列表截帧安全性，以及文件整理时重命名开关、完整文件名和海报防误删保护。

    :param monkeypatch: pytest 猴子补丁夹具
    :param tmp_path: pytest 临时目录夹具
    """
    out_img = tmp_path / "thumb.jpg"
    video_name = 'Brighton & Hove "2026".mkv'
    recorded_cmds = []

    def fake_run_ok(cmd, **kwargs):
        """
        记录 ffmpeg 调用参数并模拟成功生成截图文件。
        """
        recorded_cmds.append((cmd, kwargs))
        out_img.write_bytes(b"jpg")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(monitor_mod.subprocess, "run", fake_run_ok)
    assert AutoSports.get_thumb(video_name, str(out_img), frames="00:00:10") is True
    assert isinstance(recorded_cmds[0][0], list)
    assert video_name in recorded_cmds[0][0]
    assert "shell" not in recorded_cmds[0][1]

    monkeypatch.setattr(
        monitor_mod.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stderr=b"boom"),
    )
    assert AutoSports.get_thumb(video_name, str(tmp_path / "fail.jpg")) is False

    def raise_os_err(*_a, **_kw):
        """
        模拟系统中缺少 ffmpeg 可执行文件时的 OSError。
        """
        raise FileNotFoundError("ffmpeg not found")

    monkeypatch.setattr(monitor_mod.subprocess, "run", raise_os_err)
    assert AutoSports.get_thumb(video_name, str(tmp_path / "missing.jpg")) is False

    # 验证 _handle_file：need_rename=False 生效、含点号队名不截断、截帧失败不删同目录旧海报
    plugin, _ = _create_isolated_plugin(monkeypatch)
    plugin._dest_path = str(tmp_path / "dest")  # pylint: disable=protected-access
    plugin._need_rename = False  # pylint: disable=protected-access
    plugin._notify = False  # pylint: disable=protected-access

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_video = src_dir / "LaLiga St. Pauli vs HSV S2025E10.mkv"
    src_video.write_bytes(b"")

    season_dir = tmp_path / "dest" / "Season 2025"
    season_dir.mkdir(parents=True)
    target_video = season_dir / "LaLiga - St. Pauli vs HSV - S2025E10.mkv"
    existing_poster = season_dir / "Existing_Match_poster.jpg"
    existing_poster.write_bytes(b"keep-poster")

    fake_media = MediaInfo(title="德国足球甲级联赛", en_title="Bundesliga", year="1962")
    fake_meta = MetaInfo(title="德国足球甲级联赛")
    fake_meta.title = "德国足球甲级联赛"
    fake_meta.title_year = "德国足球甲级联赛 (25-26赛季)"
    fake_meta.cn_name = "25-26赛季 - 第十轮 - FC St. Pauli vs HSV"
    fake_meta.en_name = "Season 25-26 - Round 10 - FC St. Pauli vs HSV"
    fake_meta.subtitle = "FC St. Pauli vs HSV"
    fake_meta.begin_season = 2025
    fake_meta.begin_episode = 10
    fake_meta.set_season(2025)
    fake_meta.set_episode(10)
    fake_ep = recognition_mod.TmdbEpisode(episode_number=10, season_number=2025, air_date="2025-11-01")

    monkeypatch.setattr(plugin, "_parse_file_metadata", lambda *_a, **_kw: (fake_meta, fake_media, fake_ep))
    monkeypatch.setattr(monitor_mod, "DirectoryHelper", lambda: SimpleNamespace(get_dir=lambda *a, **kw: None))

    captured = {}

    def fake_transfer(**kwargs):
        """
        捕获传给宿主转移链的目录重命名开关并返回目标文件项。
        """
        captured["target_dir"] = kwargs["target_directory"]
        return TransferInfo(target_item=FileItem(path=str(target_video)))

    plugin.chain = SimpleNamespace(obtain_images=MagicMock(), transfer=fake_transfer)

    def fake_gen_thumb(title="", file_path=None, rename_conf=False):
        """
        记录缩略图生成调用时的开关参数并模拟未产生缩略图。
        """
        captured["thumb_rename_conf"] = rename_conf
        captured["thumb_title"] = title
        return None

    monkeypatch.setattr(plugin, "gen_file_thumb", fake_gen_thumb)
    plugin._handle_file(str(src_video), exist_matches={})  # pylint: disable=protected-access

    assert captured["target_dir"].renaming is False
    assert captured["thumb_rename_conf"] is True
    assert captured["thumb_title"] == "LaLiga - St. Pauli vs HSV - S2025E10"
    assert (season_dir / "LaLiga - St. Pauli vs HSV - S2025E10.nfo").is_file()
    assert existing_poster.exists() and existing_poster.read_bytes() == b"keep-poster"


def test_multi_matches_same_round_find_best_vault_and_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    验证同赛事同轮次下不同对阵比赛在择优、NFO 查重与历史精确删除中的隔离性。

    :param monkeypatch: pytest 猴子补丁夹具
    :param tmp_path: pytest 临时目录夹具
    """
    media = MediaInfo(title="西班牙足球甲级联赛", year="2025")

    meta_rm = MetaInfo(title="西班牙足球甲级联赛")
    meta_rm.title = "西班牙足球甲级联赛"
    meta_rm.subtitle = "Real Madrid CF vs FC Barcelona"
    meta_rm.begin_season = 2025
    meta_rm.begin_episode = 31
    meta_rm.set_season(2025)
    meta_rm.set_episode(31)

    meta_atm = MetaInfo(title="西班牙足球甲级联赛")
    meta_atm.title = "西班牙足球甲级联赛"
    meta_atm.subtitle = "Club Atlético de Madrid vs Sevilla FC"
    meta_atm.begin_season = 2025
    meta_atm.begin_episode = 31
    meta_atm.set_season(2025)
    meta_atm.set_episode(31)

    m_rm_low = Matchinfo(_make_sportscult_torrent(title="rm-low", seeders=5), media, meta_rm, "en", 1080)
    m_rm_high = Matchinfo(_make_sportscult_torrent(title="rm-high", seeders=30), media, meta_rm, "en", 1080)
    m_atm = Matchinfo(_make_sportscult_torrent(title="atm", seeders=15), media, meta_atm, "en", 1080)

    candidates = []
    AutoSports.find_best(force_en=True, lowest_pix=720, matchesinfo=candidates, new_matchinfo=m_rm_low)
    AutoSports.find_best(force_en=True, lowest_pix=720, matchesinfo=candidates, new_matchinfo=m_atm)
    AutoSports.find_best(force_en=True, lowest_pix=720, matchesinfo=candidates, new_matchinfo=m_rm_high)
    assert len(candidates) == 2
    assert candidates[0] is m_rm_high
    assert candidates[1] is m_atm

    # 同目录 NFO 写有真实对阵时，同轮另一支关注球队不应被误判为已入库
    monkeypatch.setattr(monitor_mod.settings, "LOCAL_EXISTS_SEARCH", True)
    monkeypatch.setattr(ui_mod.settings, "API_TOKEN", "test-secret")
    plugin, state = _create_isolated_plugin(monkeypatch)
    plugin._dest_path = str(tmp_path)  # pylint: disable=protected-access

    season_dir = tmp_path / "西班牙足球甲级联赛" / "Season 2025"
    season_dir.mkdir(parents=True)
    saved_mkv = season_dir / "西班牙足球甲级联赛 S2025E31 - rm.mkv"
    saved_nfo = season_dir / "西班牙足球甲级联赛 S2025E31 - rm.nfo"
    saved_mkv.write_bytes(b"")
    saved_nfo.write_text(
        "<episodedetails><title>25-26赛季 - 第三十一轮 - Real Madrid CF vs FC Barcelona</title></episodedetails>",
        encoding="utf-8",
    )

    existing = plugin._exists_match(use_cache=False)  # pylint: disable=protected-access
    assert AutoSports.is_match_in_vault(existing, meta_rm) is True
    assert AutoSports.is_match_in_vault(existing, meta_atm) is False

    # delete_history 按对阵与种子标题精确删除，不影响同轮另一场比赛历史
    state["data"]["history"] = [
        {
            "torrent_title": "sc-rm",
            "competition_name": "西班牙足球甲级联赛",
            "roundinfo": "S2025E31",
            "matchmake": "Real Madrid CF vs FC Barcelona",
            "time": "2026-04-12 22:00:00",
        },
        {
            "torrent_title": "sc-atm",
            "competition_name": "西班牙足球甲级联赛",
            "roundinfo": "S2025E31",
            "matchmake": "Club Atlético de Madrid vs Sevilla FC",
            "time": "2026-04-12 20:00:00",
        },
    ]
    del_resp = plugin.delete_history(
        key="西班牙足球甲级联赛",
        roundinfo="S2025E31",
        apikey="test-secret",
        matchmake="Real Madrid CF vs FC Barcelona",
        torrent_title="sc-rm",
    )
    assert del_resp.success is True
    assert [item["torrent_title"] for item in state["data"]["history"]] == ["sc-atm"]


def test_check_resilience_null_description_trailing_comma_bad_regex_fhd(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证 check() 面对 description=None、size=None、尾随逗号、非法正则及 FHD 清晰度时不崩溃也不误杀。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    valid_site = _valid_builtin_sportscult_indexer(site_id=9)
    _install_fake_sites_helper(monkeypatch, indexsites=[valid_site], indexers=[valid_site])
    plugin, state = _create_isolated_plugin(monkeypatch)
    plugin._football_apikey = "fake-key"  # pylint: disable=protected-access
    plugin._teams_info = "Barcelona"  # pylint: disable=protected-access
    plugin._include = "[bad-regex, Barcelona"  # pylint: disable=protected-access
    plugin._exclude = "720p,"  # pylint: disable=protected-access
    plugin._size_range = ""  # pylint: disable=protected-access
    plugin._action = "download"  # pylint: disable=protected-access
    plugin._sync_all = False  # pylint: disable=protected-access
    plugin._filter = False  # pylint: disable=protected-access

    title = "Copa del Rey 2026 04 18 Barcelona vs Real Madrid Final FHD"
    torrent = TorrentInfo(
        site=9,
        site_name="SportsCult",
        title=title,
        description=None,
        size=None,
        seeders=18,
    )
    meta = MetaInfo(title=title)
    meta.org_string = title
    meta.resource_pix = "FHD"

    monkeypatch.setattr(plugin, "_exists_match", lambda use_cache=True: {})
    monkeypatch.setattr(
        search_mod,
        "SearchChain",
        lambda: SimpleNamespace(search_by_title=lambda *a, **kw: [Context(torrent_info=torrent, meta_info=meta)]),
    )
    downloaded = []
    monkeypatch.setattr(
        plugin,
        "_download",
        lambda t, paused, metainfo=None: downloaded.append((t.title, paused)) or (False, "hash123"),
    )
    monkeypatch.setattr(plugin, "post_message", MagicMock())

    plugin.check()
    assert len(downloaded) == 1
    assert len(state["data"]["history"]) == 1
    assert state["data"]["history"][0]["torrent_title"] == title


def test_recognition_offline_ucl_playoffs_homepage_and_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    验证离线赛事无 API key 识别、欧冠附加赛英文轮次修正、homepage 协议去重及赛程缓存 TTL 过期刷新。

    :param monkeypatch: pytest 猴子补丁夹具
    """
    plugin, _ = _create_isolated_plugin(monkeypatch)

    # 纯离线赛事无 football_apikey 时仍可走媒体源识别
    plugin._football_apikey = ""  # pylint: disable=protected-access
    cdr_meta = MetaInfo(title="Copa del Rey 2026 04 18 Real Madrid vs Barcelona Final 1080p")
    cdr_meta.org_string = "Copa del Rey 2026 04 18 Real Madrid vs Barcelona Final 1080p"
    cdr_media = plugin.recognize_media(meta=cdr_meta, mtype=MediaType.TV, media_source=AutoSports.MEDIA_SOURCE)
    assert cdr_media is not None
    assert cdr_media.title == "西班牙国王杯"

    # 自定义赛事 homepage 已包含 https:// 时不应重复拼接
    plugin._competitions_config = json.dumps([
        {
            "names": ["Test Cup"],
            "type": "CUP",
            "shortname": "TC",
            "title": "测试杯",
            "homepage": "https://cup.example/info",
            "offline_info": {"group": 0, "knockout_single": 8, "knockout_double": 0},
        },
        {
            "names": ["Bare Cup"],
            "type": "CUP",
            "shortname": "BC",
            "title": "裸域杯",
            "homepage": "bare.example",
            "offline_info": {"group": 0, "knockout_single": 8, "knockout_double": 0},
        },
    ])
    plugin._initialize_competition_config()  # pylint: disable=protected-access
    custom_map = {item["title"]: item.get("homepage") for item in plugin._competitions_parses}  # pylint: disable=protected-access
    assert custom_map["测试杯"] == "https://cup.example/info"
    assert custom_map["裸域杯"] == "https://bare.example"

    # 欧冠 PLAYOFFS 英文轮次修正 & _cached_matches TTL 过期刷新
    plugin._football_apikey = "fake-token"  # pylint: disable=protected-access
    fetch_count = [0]

    class _FakePlayoffResponse:
        """
        模拟返回欧冠附加赛赛程的 JSON 响应。
        """

        status_code = 200
        text = "{}"

        @staticmethod
        def json() -> dict:
            """
            返回包含欧冠 PLAYOFFS 首回合比赛的字典。

            :return: 赛事响应载荷
            """
            return {
                "matches": [
                    {
                        "id": 9100,
                        "utcDate": "2026-02-12T20:00:00Z",
                        "competition": {"code": "CL", "name": "UEFA Champions League", "type": "CUP"},
                        "season": {"startDate": "2025-09-10"},
                        "matchday": 1,
                        "stage": "PLAYOFFS",
                        "homeTeam": {"name": "Real Madrid CF", "shortName": "Real Madrid", "crest": ""},
                        "awayTeam": {"name": "Manchester City FC", "shortName": "Man City", "crest": ""},
                    }
                ]
            }

    class _FakePlayoffRequest:
        """
        统计 football-data 请求次数的模拟请求类。
        """

        def __init__(self, *args, **kwargs) -> None:
            """
            接收并忽略默认初始化参数。
            """

        @staticmethod
        def get_res(url: str, **kwargs):
            """
            累加请求次数并返回模拟赛程响应。

            :param url: 请求地址
            :param kwargs: 额外请求参数
            :return: _FakePlayoffResponse 实例
            """
            fetch_count[0] += 1
            return _FakePlayoffResponse()

    monkeypatch.setattr(recognition_mod, "RequestUtils", _FakePlayoffRequest)

    # 先注入已过期的赛程缓存，确认会触发重新请求刷新并识别正确的英文附加赛轮次
    plugin._cached_matches["CL_2025"] = {"matches": []}  # pylint: disable=protected-access
    plugin._cached_matches_at["CL_2025"] = time.time() - plugin._CACHED_MATCH_TTL - 10  # pylint: disable=protected-access

    ucl_meta = MetaInfo(title="UCL 2026 02 12 Real Madrid vs Man City 1080p")
    ucl_meta.org_string = "UCL 2026 02 12 Real Madrid vs Man City 1080p"
    ucl_media = plugin.recognize_competition_mediainfo(meta_info=ucl_meta)
    ucl_recognized, _ = plugin.recognized_match_metainfo(ucl_media, ucl_meta)
    assert fetch_count[0] == 1
    assert ucl_recognized is not None
    assert "Knockout Phase Playoffs 1st Leg" in ucl_recognized.en_name
