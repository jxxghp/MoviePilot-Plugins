"""NexusPHP 适配器解析测试：客户端表格、leeching 列表、促销标签、翻页。"""

import pytest

from app.plugins.siteuserdetail.adapters.nexusphp import NexusPhpAdapter
from tests.v3.siteuserdetail.conftest import load_fixture


def make_adapter(site_info, **kwargs):
    return NexusPhpAdapter(site_info, interval=0, **kwargs)


class TestClientTable:

    def test_table_with_header(self, site_info):
        adapter = make_adapter(site_info)
        html = load_fixture("userdetails_clients.html")
        tables = adapter.client_table_locator(html)
        assert len(tables) == 1
        clients = adapter.client_table_parse(tables[0])
        assert len(clients) == 3
        first = clients[0]
        assert first["agent"] == "qBittorrent v5.0.1"
        assert first["ipv4"] == "112.10.1.22"
        assert first["ipv6"] == "2408:8456:1111:2222::9"
        assert first["port"] == 51413
        # ip:port 与 [v6]:port 形式
        third = clients[2]
        assert third["agent"] == "Deluge 2.0.5"
        assert third["ipv4"] == "223.5.5.5"
        assert third["ipv6"] == "240e:111:222::33"
        assert third["port"] == 58000

    def test_table_without_header(self, site_info):
        adapter = make_adapter(site_info)
        html = load_fixture("userdetails_clients_noheader.html")
        tables = adapter.client_table_locator(html)
        assert len(tables) == 1
        clients = adapter.client_table_parse(tables[0])
        assert len(clients) == 2
        assert clients[0]["agent"] == "BiglyBT 3.6.0.0"
        assert clients[0]["ipv4"] == "1.2.3.4"
        assert clients[0]["ipv6"] == "240c::1234:5678"
        assert clients[0]["port"] == 28881
        assert clients[1]["ipv4"] == "5.6.7.8"

    def test_nested_wrapper_table_picks_innermost(self, site_info):
        """嵌套包装表结构（如柠檬）：只解析最内层客户端表，包装行不混入整页文本。"""
        adapter = make_adapter(site_info)
        html = load_fixture("userdetails_clients_nested.html")
        tables = adapter.client_table_locator(html)
        assert len(tables) == 1
        clients = adapter.client_table_parse(tables[0])
        assert len(clients) == 1
        assert clients[0]["agent"] == "qBittorrent/5.2.4"
        assert clients[0]["ipv4"] == "183.192.19.191"
        assert clients[0]["ipv6"] == "2409:8a1e:8f23:9990:3ac4:d45f:9cca:b045"
        assert clients[0]["port"] == 57501

    def test_parse_clients_end_to_end(self, site_info, monkeypatch):
        adapter = make_adapter(site_info)
        monkeypatch.setattr(adapter, "_fetch", lambda url, **kw: load_fixture("userdetails_clients.html"))
        clients = adapter.parse_clients("12345")
        assert len(clients) == 3
        assert {c["agent"] for c in clients} == {"qBittorrent v5.0.1", "Transmission 4.0.3", "Deluge 2.0.5"}

    def test_no_client_table_returns_empty(self, site_info, monkeypatch):
        adapter = make_adapter(site_info)
        monkeypatch.setattr(adapter, "_fetch", lambda url, **kw: load_fixture("index.html"))
        assert adapter.parse_clients("1") == []


class TestTorrentRows:

    def test_rows_with_promo_and_size(self, site_info):
        adapter = make_adapter(site_info)
        rows = adapter.parse_torrent_rows(load_fixture("leeching_page1.html"))
        assert len(rows) == 2
        first = rows[0]
        assert first["id"] == "10086"
        assert first["name"] == "Example.Movie.2026.1080p.BluRay.x264-GRP"
        assert first["tags"] == ["Free", "2x", "50%"]
        assert first["size"] == int(10.55 * 1024 ** 3)
        assert first["hash"] == ""
        second = rows[1]
        assert second["id"] == "10087"
        assert second["tags"] == ["Free"]
        assert second["size"] == int(1.2 * 1024 ** 4)

    def test_json_wrapped_rows(self, site_info):
        adapter = make_adapter(site_info)
        fragment, total = adapter.extract_rows(load_fixture("leeching_json.txt"))
        assert total == 1
        rows = adapter.parse_torrent_rows(fragment)
        assert len(rows) == 1
        assert rows[0]["id"] == "20001"
        assert rows[0]["tags"] == ["Free"]

    def test_extract_rows_plain_html(self, site_info):
        adapter = make_adapter(site_info)
        fragment, total = adapter.extract_rows(load_fixture("leeching_page1.html"))
        assert total is None
        assert "details.php?id=10086" in fragment

    def test_next_page_url(self, site_info):
        adapter = make_adapter(site_info)
        url = adapter.next_page_url(load_fixture("leeching_page1.html"))
        assert url is not None and "page=1" in url
        assert adapter.next_page_url(load_fixture("leeching_page2.html")) is None


class TestParseLeeching:

    def test_pagination_and_dedup(self, site_info, monkeypatch):
        adapter = make_adapter(site_info)
        pages = [
            load_fixture("leeching_page1.html"),
            load_fixture("leeching_page2.html"),
        ]
        requested = []

        def fake_fetch(url, **kwargs):
            requested.append(url)
            if "page=1" in url:
                return pages[1]
            if "page=" not in url:
                return pages[0]
            return None

        monkeypatch.setattr(adapter, "_fetch", fake_fetch)
        torrents = adapter.parse_leeching("12345")
        assert [t["id"] for t in torrents] == ["10086", "10087", "10088"]
        assert torrents[2]["tags"] == ["2x"]
        assert torrents[2]["size"] == int(890.5 * 1024 ** 2)
        # 第一页（无 page 参数）+ 第二页（page=1）
        assert len(requested) == 2


class TestUidFallback:

    def test_uid_from_homepage_link(self, site_info, monkeypatch):
        adapter = make_adapter(site_info)
        monkeypatch.setattr(adapter, "fetch_index", lambda: load_fixture("index.html"))
        assert adapter.get_uid() == "12345"
