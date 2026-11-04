# -*- coding: utf-8 -*-
"""xloli（萝莉，mua.xloli.cc）适配器测试：UUID uid、useruuid 列表、真实样本解析。

样本来自 2026-11-04 实测抓取（个人信息已替换为文档保留段/占位符）。
"""

import pytest

from app.plugins.siteuserdetail.adapters import get_adapter
from app.plugins.siteuserdetail.adapters.sites import SITE_ADAPTERS
from app.plugins.siteuserdetail.adapters.sites.xloli import XloliAdapter
from tests.v3.siteuserdetail.conftest import load_fixture

UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def xloli_info():
    """xloli 站点条目（MP 站点表 domain 为 xloli.cc，实际访问 mua.xloli.cc）。"""
    return {
        "id": 28,
        "name": "萝莉",
        "domain": "xloli.cc",
        "url": "https://mua.xloli.cc/",
        "cookie": "nexus_session=abc",
        "ua": "",
        "render": False,
        "proxy": False,
        "timeout": 15,
    }


def make_adapter(xloli_info):
    return XloliAdapter(xloli_info, interval=0)


class TestFactory:

    def test_registered_by_domain(self, xloli_info):
        assert SITE_ADAPTERS["xloli.cc"] is XloliAdapter
        assert isinstance(get_adapter(xloli_info), XloliAdapter)


class TestUid:

    def test_uid_from_homepage_user_name_anchor(self, xloli_info, monkeypatch):
        """首页锚定 class='User_Name' 链接解析自己的 UUID，不受管理员等其他用户链接干扰。"""
        adapter = make_adapter(xloli_info)
        monkeypatch.setattr(adapter, "fetch_index",
                            lambda: load_fixture("xloli_index.html"))
        assert adapter.get_uid() == UUID

    def test_uid_none_when_no_user_anchor(self, xloli_info, monkeypatch):
        """无 User_Name 链接时不猜测（避免误取他人 ID）。"""
        adapter = make_adapter(xloli_info)
        monkeypatch.setattr(adapter, "fetch_index", lambda: "<html></html>")
        assert adapter.get_uid() is None

    def test_urls_use_uuid_params(self, xloli_info):
        adapter = make_adapter(xloli_info)
        assert adapter.user_detail_url(UUID) == f"https://mua.xloli.cc/userdetails.php?uuid={UUID}"
        assert adapter.leeching_url(UUID) == \
               f"https://mua.xloli.cc/getusertorrentlistajax.php?useruuid={UUID}&type=leeching"
        assert adapter.leeching_url(UUID, 1) == \
               f"https://mua.xloli.cc/getusertorrentlistajax.php?useruuid={UUID}&type=leeching&page=1"


class TestParseClients:

    def test_real_userdetails_sample(self, xloli_info, monkeypatch):
        """标准 Agent/IPV4/IPV6/Port 内层表格，通用解析直接命中。"""
        adapter = make_adapter(xloli_info)
        monkeypatch.setattr(adapter, "_fetch", lambda url, **kw: load_fixture("xloli_userdetails.html"))
        clients = adapter.parse_clients(UUID)
        assert len(clients) == 2
        assert clients[0]["agent"] == "qBittorrent/5.3.0"
        assert clients[0]["ipv4"] == "203.0.113.10"
        assert clients[0]["ipv6"] == "2001:db8:1:f310:e327:707c:4354:1"
        assert clients[0]["port"] == 57501
        assert clients[1]["ipv6"] == "2001:db8:2:4930:d044:137c:455e:2"


class TestParseTorrentRows:

    def test_real_list_sample(self, xloli_info):
        """列表行（seeding 样本验证行结构，与 leeching 同一模板）：id/名称/促销/大小。"""
        adapter = make_adapter(xloli_info)
        fragment, _ = adapter.extract_rows(load_fixture("xloli_seeding.html"))
        rows = adapter.parse_torrent_rows(fragment)
        assert len(rows) == 7
        first = rows[0]
        assert first["id"] == "21476"
        assert first["name"] == "Chicago 2002 Diamond Edition BluRay 1080p x264 DTS 2Audios-CMCT"
        assert first["size"] == 12874164469
        assert first["hash"] == ""
        # 促销标签解析（Free）
        assert rows[1]["tags"] == ["Free"]
        assert rows[0]["tags"] == []

    def test_empty_response(self, xloli_info):
        """无下载中种子时接口返回纯文本「没有记录」，不产生条目也不报错。"""
        adapter = make_adapter(xloli_info)
        fragment, _ = adapter.extract_rows(load_fixture("xloli_leeching_empty.txt"))
        assert adapter.parse_torrent_rows(fragment) == []
