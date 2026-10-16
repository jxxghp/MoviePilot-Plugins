"""主类测试：配置、站点解析、采集调度、hash 回填与插件 API。"""

import json
from unittest.mock import Mock

import pytest

from app.plugins import siteuserdetail as plugin_module
from app.plugins.siteuserdetail import SiteUserDetail
from app.plugins.siteuserdetail.adapters import AdapterError


class _FakeAdapter:
    """可编程的假适配器，替代真实站点访问。"""

    render = False

    def __init__(self, uid="42", clients=None, torrents=None,
                 detail_hash="", error=None):
        self._uid = uid
        self._clients = clients
        self._torrents = torrents
        self._detail_hash = detail_hash
        self._error = error
        self.detail_calls = []

    def has_credential(self):
        return True

    def get_uid(self):
        if self._error:
            raise AdapterError(self._error)
        return self._uid

    def parse_clients(self, uid):
        return self._clients

    def parse_leeching(self, uid):
        return self._torrents

    def parse_detail_hash(self, torrent_id):
        self.detail_calls.append(torrent_id)
        return self._detail_hash


class TestGetForm:

    def test_form_structure(self, plugin, fake_site_oper):
        schema, defaults = plugin.get_form()
        # 契约：第一个元素必须是组件 list（裸 dict 会导致配置弹窗空白）
        assert isinstance(schema, list) and schema
        assert schema[0]["component"] == "VForm"
        for key in ("enabled", "onlyonce", "notify", "cron", "sites",
                    "use_downloader_hash", "hash_from_detail",
                    "detail_limit", "request_interval", "concurrency"):
            assert key in defaults

    def test_get_api_contract(self, plugin):
        apis = plugin.get_api()
        assert {api["path"] for api in apis} == {"/collect", "/snapshot"}
        assert all(api["auth"] == "apikey" and "GET" in api["methods"] for api in apis)


class TestInitPlugin:

    def test_config_loaded_and_saved(self, plugin, fake_site_oper):
        plugin.init_plugin({
            "enabled": True, "notify": True, "cron": "0 */6 * * *",
            "sites": [14], "detail_limit": 5, "request_interval": 2, "concurrency": 4,
        })
        assert plugin._enabled is True
        assert plugin._cron == "0 */6 * * *"
        assert plugin._detail_limit == 5
        assert plugin.update_config.called

    def test_deleted_sites_filtered(self, plugin, fake_site_oper, monkeypatch):
        plugin.init_plugin({"enabled": True, "sites": [14, 999]})
        assert plugin._sites == [14]


class TestGetService:

    def test_cron_trigger(self, plugin):
        plugin._enabled = True
        plugin._cron = "0 */6 * * *"
        jobs = plugin.get_service()
        assert len(jobs) == 1 and jobs[0]["id"] == "SiteUserDetail"
        assert "Cron" in type(jobs[0]["trigger"]).__name__

    def test_default_interval(self, plugin):
        plugin._enabled = True
        plugin._cron = ""
        jobs = plugin.get_service()
        assert jobs[0]["trigger"] == "interval" and jobs[0]["kwargs"]["hours"] == 6.0

    def test_disabled(self, plugin):
        plugin._enabled = False
        assert plugin.get_service() == []


class TestResolveSites:

    @pytest.fixture
    def with_sites(self, plugin, site_info, monkeypatch):
        public_site = {**site_info, "id": 2, "name": "公开站", "domain": "pub.org",
                       "url": "https://pub.org/", "public": True}
        monkeypatch.setattr(plugin_module, "SitesHelper", lambda: SimpleNamespaceSites(
            [site_info, public_site]))
        return plugin

    def test_all_private_sites_by_default(self, with_sites):
        sites = with_sites._resolve_sites()
        assert [s["domain"] for s in sites] == ["example.org"]

    def test_filter_by_domain_param(self, with_sites):
        sites = with_sites._resolve_sites(["https://example.org/torrents.php"])
        assert [s["domain"] for s in sites] == ["example.org"]

    def test_indexer_domain_with_protocol_normalized(self, plugin, site_info, monkeypatch):
        """indexer.domain 带协议前缀的站点（实测 hdfans）必须归一化为注册域。"""
        weird = {**site_info, "id": 31, "name": "带协议站", "domain": "https://example.org/"}
        monkeypatch.setattr(plugin_module, "SitesHelper",
                            lambda: SimpleNamespaceSites([weird]))
        sites = plugin._resolve_sites(["example.org"])
        assert [s["domain"] for s in sites] == ["example.org"]

    def test_filter_by_config_ids(self, with_sites):
        with_sites._sites = [14]
        sites = with_sites._resolve_sites()
        assert [s["domain"] for s in sites] == ["example.org"]

    def test_unknown_domain_yields_empty(self, with_sites):
        assert with_sites._resolve_sites(["nope.org"]) == []


class SimpleNamespaceSites:
    def __init__(self, indexers):
        self._indexers = indexers

    def get_indexers(self):
        return self._indexers


class TestCollectSiteHash:

    @pytest.fixture
    def torrent(self):
        return [{"id": "7", "name": "A.Torrent.2026", "tags": [], "size": 1, "hash": ""}]

    def test_pool_match_wins(self, plugin, site_info, monkeypatch, torrent):
        adapter = _FakeAdapter(torrents=torrent)
        monkeypatch.setattr(plugin_module, "get_adapter",
                            lambda site, interval=0, uid_map=None: adapter)
        _, clients, torrents, error, uid = plugin._collect_site(
            site_info, {"a.torrent.2026": "aa" * 20}, {})
        assert error is None
        assert torrents[0]["hash"] == "aa" * 20
        assert adapter.detail_calls == []

    def test_detail_fallback(self, plugin, site_info, monkeypatch, torrent):
        adapter = _FakeAdapter(torrents=torrent, detail_hash="bb" * 20)
        monkeypatch.setattr(plugin_module, "get_adapter",
                            lambda site, interval=0, uid_map=None: adapter)
        _, _, torrents, error, _ = plugin._collect_site(site_info, {}, {})
        assert torrents[0]["hash"] == "bb" * 20
        assert adapter.detail_calls == ["7"]

    def test_detail_limit_respected(self, plugin, site_info, monkeypatch):
        torrents = [{"id": str(i), "name": f"T{i}", "tags": [], "size": 1, "hash": ""}
                    for i in range(5)]
        adapter = _FakeAdapter(torrents=torrents, detail_hash="cc" * 20)
        monkeypatch.setattr(plugin_module, "get_adapter",
                            lambda site, interval=0, uid_map=None: adapter)
        plugin._detail_limit = 2
        _, _, result, _, _ = plugin._collect_site(site_info, {}, {})
        hashes = [t["hash"] for t in result]
        assert hashes[:2] == ["cc" * 20, "cc" * 20]
        assert hashes[2:] == ["", "", ""]

    def test_detail_skipped_when_disabled(self, plugin, site_info, monkeypatch, torrent):
        adapter = _FakeAdapter(torrents=torrent, detail_hash="dd" * 20)
        monkeypatch.setattr(plugin_module, "get_adapter",
                            lambda site, interval=0, uid_map=None: adapter)
        plugin._hash_from_detail = False
        _, _, torrents, _, _ = plugin._collect_site(site_info, {}, {})
        assert torrents[0]["hash"] == ""
        assert adapter.detail_calls == []

    def test_adapter_error_recorded(self, plugin, site_info, monkeypatch):
        monkeypatch.setattr(plugin_module, "get_adapter",
                            lambda site, interval=0, uid_map=None: _FakeAdapter(error="Cookie 已失效"))
        _, clients, torrents, error, _ = plugin._collect_site(site_info, {}, {})
        assert error == "Cookie 已失效"
        assert clients == [] and torrents == []


class TestCollectFlow:

    def test_aggregation_and_empty_client_entry(self, plugin, monkeypatch):
        site_a = {"id": 14, "name": "站A", "domain": "a.org", "url": "https://a.org/"}
        site_b = {"id": 15, "name": "站B", "domain": "b.org", "url": "https://b.org/"}
        monkeypatch.setattr(plugin, "_resolve_sites", lambda sites=None: [site_a, site_b])
        monkeypatch.setattr(plugin, "_build_downloader_pool", lambda: {})
        monkeypatch.setattr(plugin, "_collect_site", lambda site, pool, uid_map: (
            site,
            [{"agent": "qB 5.0", "ipv4": "1.1.1.1", "ipv6": "", "port": 5}],
            [{"id": "1", "name": "T1", "tags": ["Free"], "size": 9, "hash": "h1", }],
            None,
            "100",
        ) if site["domain"] == "a.org" else (site, [], [], "Cookie 已失效", None))
        snapshot = plugin.collect()
        assert snapshot["clients"][0]["site"] == "站A"
        assert snapshot["clients"][0]["domain"] == "a.org"
        # 站B 无客户端数据 → 全空值条目
        assert snapshot["clients"][1] == {
            "site": "站B", "domain": "b.org", "agent": "", "ipv4": "", "ipv6": "", "port": None}
        assert snapshot["torrents"] == [
            {"id": "1", "name": "T1", "tags": ["Free"], "size": 9, "hash": "h1",
             "site": "站A", "domain": "a.org"}]
        assert snapshot["errors"] == [{"site": "站B", "domain": "b.org", "error": "Cookie 已失效"}]
        # 快照与 uid 缓存已保存
        saved_keys = [call.args[0] for call in plugin.save_data.call_args_list]
        assert "snapshot" in saved_keys and "uid_map" in saved_keys
        uid_map = [call.args[1] for call in plugin.save_data.call_args_list
                   if call.args[0] == "uid_map"][0]
        assert uid_map == {"a.org": "100"}

    def test_no_sites_returns_error_snapshot(self, plugin, monkeypatch):
        monkeypatch.setattr(plugin, "_resolve_sites", lambda sites=None: [])
        snapshot = plugin.collect()
        assert snapshot["clients"] == [] and snapshot["torrents"] == []
        assert "没有可采集的站点" in snapshot["errors"][0]["error"]

    def test_thread_exception_becomes_error(self, plugin, monkeypatch):
        site = {"id": 14, "name": "站A", "domain": "a.org", "url": "https://a.org/"}
        monkeypatch.setattr(plugin, "_resolve_sites", lambda sites=None: [site])
        monkeypatch.setattr(plugin, "_build_downloader_pool", lambda: {})

        def boom(site, pool, uid_map):
            raise RuntimeError("炸了")

        monkeypatch.setattr(plugin, "_collect_site", boom)
        snapshot = plugin.collect()
        assert "炸了" in snapshot["errors"][0]["error"]
        # 异常站仍有全空值条目
        assert snapshot["clients"][0]["domain"] == "a.org"

    def test_notify_sent_when_enabled(self, plugin, monkeypatch):
        site = {"id": 14, "name": "站A", "domain": "a.org", "url": "https://a.org/"}
        monkeypatch.setattr(plugin, "_resolve_sites", lambda sites=None: [site])
        monkeypatch.setattr(plugin, "_build_downloader_pool", lambda: {})
        monkeypatch.setattr(plugin, "_collect_site",
                            lambda site, pool, uid_map: (site, [], [], None, None))
        plugin._notify = True
        plugin.collect()
        assert plugin.post_message.called


class TestPluginApi:

    def test_api_collect_triggers_collect(self, plugin, monkeypatch):
        fake_snapshot = {"update_time": 1, "clients": [], "torrents": [], "errors": []}
        monkeypatch.setattr(plugin, "collect", Mock(return_value=fake_snapshot))
        response = plugin.api_collect(sites="a.org,b.org")
        assert response.success is True
        plugin.collect.assert_called_once_with(["a.org", "b.org"])
        assert response.data is fake_snapshot

    def test_api_collect_empty_sites_means_all(self, plugin, monkeypatch):
        fake_snapshot = {"update_time": 1, "clients": [], "torrents": [], "errors": []}
        monkeypatch.setattr(plugin, "collect", Mock(return_value=fake_snapshot))
        plugin.api_collect(sites="")
        plugin.collect.assert_called_once_with(None)

    def test_api_snapshot_no_data(self, plugin):
        response = plugin.api_snapshot()
        assert response.success is False

    def test_api_snapshot_filters_by_domain(self, plugin, monkeypatch):
        snapshot = {
            "update_time": 1,
            "clients": [
                {"site": "A", "domain": "a.org", "agent": "x", "ipv4": "", "ipv6": "", "port": None},
                {"site": "B", "domain": "b.org", "agent": "", "ipv4": "", "ipv6": "", "port": None},
            ],
            "torrents": [
                {"site": "A", "domain": "a.org", "id": "1"},
                {"site": "B", "domain": "b.org", "id": "2"},
            ],
            "errors": [{"site": "B", "domain": "b.org", "error": "x"}],
        }
        monkeypatch.setattr(plugin, "get_data", Mock(return_value=snapshot))
        response = plugin.api_snapshot(sites="a.org")
        assert response.success is True
        assert [c["site"] for c in response.data["clients"]] == ["A"]
        assert [t["site"] for t in response.data["torrents"]] == ["A"]
        assert response.data["errors"] == []


class TestPluginMeta:

    def test_plugin_name(self):
        assert SiteUserDetail.plugin_name == "站点用户详情采集"
        assert SiteUserDetail.plugin_version


class TestGetPage:

    def test_empty_state_alert(self, plugin):
        page = plugin.get_page()
        assert len(page) == 1 and page[0]["component"] == "VAlert"

    def test_page_with_snapshot(self, plugin, monkeypatch):
        snapshot = {
            "update_time": 1760000000,
            "clients": [
                {"site": "站A", "domain": "a.org", "agent": "qBittorrent/5.0", "ipv4": "1.1.1.1",
                 "ipv6": "", "port": 51413},
                {"site": "站B", "domain": "b.org", "agent": "qB 5.0", "ipv4": "1.1.1.1",
                 "ipv6": "240c::1", "port": 51413},
                {"site": "", "domain": "c.org", "agent": "", "ipv4": "", "ipv6": "", "port": None},
            ],
            "torrents": [
                {"site": "站A", "domain": "a.org", "id": "1", "name": "T1",
                 "tags": ["Free"], "size": 1073741824, "hash": "ab" * 20},
                {"site": "站B", "domain": "b.org", "id": "2", "name": "T2",
                 "tags": [], "size": 5368709120, "hash": ""},
            ],
            "errors": [{"site": "站D", "domain": "d.org", "error": "连接失败"}],
        }
        monkeypatch.setattr(plugin, "get_data", Mock(return_value=snapshot))
        page = plugin.get_page()
        # style + 页面容器
        assert page[0]["component"] == "style"
        texts = json.dumps(page, ensure_ascii=False)
        for expected in ("IPv4 聚合", "IPv6 聚合", "无数据站点", "全部站点",
                         "下载中种子", "失败站点", "1.00 GB", "用户页未解析到客户端数据"):
            assert expected in texts
        # IPv4 聚合：1.1.1.1 出现在 2 个站点
        assert "1.1.1.1" in texts and "×" in texts
        # 分节顺序：IP 聚合 → 无数据站点 → 全部站点 → 下载中种子
        #（rfind 跳过顶部摘要卡的同名统计标签）
        assert texts.find("IPv4 聚合") < texts.find("无数据站点") < texts.find("全部站点") \
               < texts.rfind("下载中种子")
        # 站点空值回退 domain（含全部站点表格里的空数据行）
        assert "c.org" in texts

    def test_page_sections_collapsible_and_ordered(self, plugin, monkeypatch):
        """各分节为可折叠手风琴；无数据站点与全部站点为同级分节。"""
        snapshot = {
            "update_time": 1760000000,
            "clients": [{"site": "站A", "domain": "a.org", "agent": "qB/5.0",
                         "ipv4": "1.1.1.1", "ipv6": "", "port": 1}],
            "torrents": [], "errors": [],
        }
        monkeypatch.setattr(plugin, "get_data", Mock(return_value=snapshot))
        page = plugin.get_page()
        sections = [node for node in page[1]["content"]
                    if isinstance(node, dict) and node.get("component") == "VExpansionPanels"]
        # IPv4 聚合 + 无数据站点 + 全部站点 + 下载中种子（IPv6 无数据不生成）
        assert len(sections) == 4
        titles = []
        for section in sections:
            panel = section["content"][0]
            assert panel["component"] == "VExpansionPanel"
            assert panel["content"][0]["component"] == "VExpansionPanelTitle"
            assert panel["content"][1]["component"] == "VExpansionPanelText"
            titles.append(json.dumps(panel["content"][0], ensure_ascii=False))
        joined = "".join(titles)
        order = [joined.find(name) for name in ("IPv4 聚合", "无数据站点", "全部站点")]
        assert order == sorted(order)

    def test_all_sites_table_keeps_site_name_on_empty_rows(self, plugin, monkeypatch):
        """全部站点表格里空数据行的站点列必须显示站点名（弱化但不为空）。"""
        snapshot = {
            "update_time": 1760000000,
            "clients": [
                {"site": "站A", "domain": "a.org", "agent": "q/5.0", "ipv4": "1.1.1.1",
                 "ipv6": "", "port": 1},
                {"site": "馒头", "domain": "m-team.cc", "agent": "", "ipv4": "",
                 "ipv6": "", "port": None},
            ],
            "torrents": [], "errors": [],
        }
        monkeypatch.setattr(plugin, "get_data", Mock(return_value=snapshot))
        table = plugin._clients_table(snapshot["clients"])
        body_rows = table["content"][1]["content"]  # tbody -> tr
        assert body_rows[1]["content"][0]["text"] == "馒头"
        assert body_rows[1]["props"].get("class") == "sud-muted"


class TestCollectRobustness:

    def test_collect_skipped_when_locked(self, plugin, monkeypatch):
        last = {"update_time": 1, "clients": [{"site": "A"}], "torrents": [], "errors": []}
        monkeypatch.setattr(plugin, "get_data", Mock(return_value=last))
        called = []
        monkeypatch.setattr(plugin, "_SiteUserDetail__do_collect", lambda sites=None: called.append(1))
        with plugin._collect_lock:
            result = plugin.collect()
        assert result is last and not called

    def test_collect_returns_despite_save_failure(self, plugin, monkeypatch):
        site = {"id": 14, "name": "站A", "domain": "a.org", "url": "https://a.org/"}
        monkeypatch.setattr(plugin, "_resolve_sites", lambda sites=None: [site])
        monkeypatch.setattr(plugin, "_build_downloader_pool", lambda: {})
        monkeypatch.setattr(plugin, "_collect_site",
                            lambda site, pool, uid_map: (site, [], [], None, None))
        plugin.save_data.side_effect = RuntimeError("同步事务执行器尚未配置")
        snapshot = plugin.collect()
        assert snapshot["clients"][0]["site"] == "站A"


class TestAdapterFactory:

    def test_mteam_by_domain(self, site_info):
        from app.plugins.siteuserdetail.adapters import MTeamAdapter, get_adapter
        adapter = get_adapter({**site_info, "domain": "kp.m-team.cc", "url": "https://kp.m-team.cc/"})
        assert isinstance(adapter, MTeamAdapter)

    def test_nexusphp_default(self, site_info):
        from app.plugins.siteuserdetail.adapters import NexusPhpAdapter, get_adapter
        assert isinstance(get_adapter(site_info), NexusPhpAdapter)

    def test_uid_map_passed(self, site_info):
        from app.plugins.siteuserdetail.adapters import get_adapter
        adapter = get_adapter(site_info, uid_map={"example.org": "555"})
        assert adapter._uid == "555"
