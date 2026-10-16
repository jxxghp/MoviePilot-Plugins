"""适配器基类纯函数与 uid/hash 解析测试。"""

import base64
import urllib.parse

import pytest

from app.plugins.siteuserdetail.adapters.base import (
    SiteAdapter,
    classify_token,
    extract_ips,
    looks_like_agent,
    parse_size,
)
from tests.v3.siteuserdetail.conftest import load_fixture


class TestIpUtils:

    def test_ipv4_plain(self):
        assert classify_token("112.10.1.22") == ("ipv4", "112.10.1.22", None)

    def test_ipv4_with_port(self):
        assert classify_token("223.5.5.5:58000") == ("ipv4", "223.5.5.5", 58000)

    def test_ipv6_plain(self):
        kind, ip, port = classify_token("2408:8456:1111:2222::9")
        assert kind == "ipv6" and ip == "2408:8456:1111:2222::9" and port is None

    def test_ipv6_bracket_with_port(self):
        kind, ip, port = classify_token("[240e:111:222::33]:58001")
        assert kind == "ipv6" and ip == "240e:111:222::33" and port == 58001

    def test_ipv6_with_port_no_bracket(self):
        # 尾段 58001 为 5 位，不可能是 IPv6 地址组（≤4 位 hex），必为端口
        kind, ip, port = classify_token("240e:111::33:58001")
        assert kind == "ipv6" and ip == "240e:111::33" and port == 58001

    def test_ipv6_trailing_short_group_is_address(self):
        # 尾组 4 位以内是合法地址的一部分，不能当端口
        kind, ip, port = classify_token("240c::1234:5678")
        assert kind == "ipv6" and ip == "240c::1234:5678" and port is None

    def test_not_ip(self):
        assert classify_token("qBittorrent/5.0.1")[0] is None
        assert classify_token("2026-10-01")[0] is None
        assert classify_token("51413")[0] is None

    def test_extract_ips_mixed_cell(self):
        text = "1.2.3.4:28881 [240c::1234:5678]:28882 其他"
        ipv4s, ipv6s, port = extract_ips(text)
        assert ipv4s == ["1.2.3.4"]
        assert ipv6s == ["240c::1234:5678"]
        assert port == 28881

    def test_extract_ips_concat_geo_text(self):
        """IP 与地理位置文本连写（UBits 实测格式）。"""
        ipv4s, ipv6s, port = extract_ips(
            "46.229.250.218Podturen·克罗地亚[v4]->ASN: 209604 "
            "2409:8a1e:8f23:9990:3ac4:d45f:9cca:b045上海·中国[v6]->ASN: 24400")
        assert ipv4s == ["46.229.250.218"]
        assert ipv6s == ["2409:8a1e:8f23:9990:3ac4:d45f:9cca:b045"]
        assert port is None


class TestAgentAndSize:

    def test_agent_patterns(self):
        assert looks_like_agent("qBittorrent v5.0.1")
        assert looks_like_agent("Transmission 4.0.3")
        assert looks_like_agent("Deluge 2.0.5")
        assert not looks_like_agent("112.10.1.22")
        assert not looks_like_agent("浙江 杭州")

    def test_parse_size(self):
        assert parse_size("10.55 GB") == int(10.55 * 1024 ** 3)
        assert parse_size("1.2 TB") == int(1.2 * 1024 ** 4)
        assert parse_size("890.5 MB") == int(890.5 * 1024 ** 2)
        assert parse_size("4.37 GB ") == int(4.37 * 1024 ** 3)
        assert parse_size("未知") == 0


class TestUidFromCookie:

    def test_c_secure_uid(self, site_info):
        adapter = SiteAdapter(site_info, interval=0)
        assert adapter._uid_from_cookie() == "12345"

    def test_cookie_without_uid(self):
        adapter = SiteAdapter({"name": "x", "domain": "x.org", "url": "https://x.org/",
                               "cookie": "other=1"}, interval=0)
        assert adapter._uid_from_cookie() is None

    def test_base64_padding(self):
        # 未补齐 padding 的 base64（url 编码后）
        encoded = urllib.parse.quote(base64.b64encode(b"987654").decode())
        adapter = SiteAdapter({"name": "x", "domain": "x.org", "url": "https://x.org/",
                               "cookie": f"c_secure_uid={encoded}"}, interval=0)
        assert adapter._uid_from_cookie() == "987654"


class TestUidFromHomepage:

    def test_homepage_uid(self, site_info, monkeypatch):
        adapter = SiteAdapter(site_info, interval=0)
        monkeypatch.setattr(adapter, "fetch_index", lambda: load_fixture("index.html"))
        assert adapter._uid_from_homepage() == "12345"

    def test_cached_uid_shortcut(self, site_info, monkeypatch):
        adapter = SiteAdapter(site_info, interval=0, uid="777")
        called = []
        monkeypatch.setattr(adapter, "fetch_index", lambda: called.append(1) or "")
        assert adapter.get_uid() == "777"
        assert not called


class TestDetailHash:

    def test_keyword_block_preferred_and_zero_excluded(self, site_info, monkeypatch):
        adapter = SiteAdapter(site_info, interval=0)
        monkeypatch.setattr(adapter, "_fetch", lambda url: load_fixture("torrent_detail_hash.html"))
        # Info Hash 区块的值，而非全 0 的随机串
        assert adapter.parse_detail_hash("1") == "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

    def test_no_hash_returns_empty(self, site_info, monkeypatch):
        adapter = SiteAdapter(site_info, interval=0)
        monkeypatch.setattr(adapter, "_fetch", lambda url: "<html><body>nothing</body></html>")
        assert adapter.parse_detail_hash("1") == ""


class TestLoginPage:

    def test_login_form_detected(self):
        assert SiteAdapter._is_login_page('<form action="takelogin.php"><input type="password">')

    def test_normal_page_not_login(self):
        assert not SiteAdapter._is_login_page(load_fixture("index.html"))
