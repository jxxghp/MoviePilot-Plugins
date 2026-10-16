"""M-Team 适配器测试：API 映射、分页、discount 促销标签。"""

import pytest

from app.plugins.siteuserdetail.adapters.mteam import MTeamAdapter


@pytest.fixture
def mt_site():
    return {
        "id": 30,
        "name": "M-Team",
        "domain": "m-team.cc",
        "url": "https://kp.m-team.cc/",
        "cookie": None,
        "ua": "Mozilla/5.0 (test)",
        "apikey": "x-api-key-token",
        "proxy": False,
    }


def make_adapter(mt_site):
    return MTeamAdapter(mt_site, interval=0)


class TestAdapterBasics:

    def test_api_base(self, mt_site):
        adapter = make_adapter(mt_site)
        assert adapter.api_base == "https://api.m-team.cc"

    def test_requires_apikey(self, mt_site):
        adapter = MTeamAdapter({**mt_site, "apikey": None}, interval=0)
        assert not adapter.has_credential()
        with pytest.raises(Exception):
            adapter.get_uid()


class TestGetUid:

    def test_profile_uid(self, mt_site, monkeypatch):
        adapter = make_adapter(mt_site)
        calls = []

        def fake_api_post(path, payload):
            calls.append((path, payload))
            assert path == "api/member/profile"
            return {"id": 606354, "username": "demo"}

        monkeypatch.setattr(adapter, "_api_post", fake_api_post)
        assert adapter.get_uid() == "606354"
        # 二次调用走缓存
        assert adapter.get_uid() == "606354"
        assert len(calls) == 1


class TestParseClients:

    def test_peer_list_mapping(self, mt_site, monkeypatch):
        adapter = make_adapter(mt_site)
        monkeypatch.setattr(adapter, "_api_post", lambda path, payload: {
            "seeder": 2, "leecher": 1, "peers": [
                {"agent": "qBittorrent 5.0.1", "ip": "1.2.3.4", "port": 51413},
                {"agent": "Transmission 4.0.3", "ip": "::ffff:1.2.3.5", "ipv6": "240c::66",
                 "port": 51413},
            ]})
        clients = adapter.parse_clients("606354")
        assert len(clients) == 2
        assert clients[0]["agent"] == "qBittorrent 5.0.1"
        assert clients[0]["ipv4"] == "1.2.3.4"
        assert clients[0]["port"] == 51413
        assert clients[1]["ipv6"] == "240c::66"

    def test_no_peer_detail_returns_empty(self, mt_site, monkeypatch):
        adapter = make_adapter(mt_site)
        monkeypatch.setattr(adapter, "_api_post", lambda path, payload: {"seeder": 3})
        assert adapter.parse_clients("1") == []

    def test_api_error_returns_empty(self, mt_site, monkeypatch):
        from app.plugins.siteuserdetail.adapters.base import AdapterError

        adapter = make_adapter(mt_site)
        def boom(path, payload):
            raise AdapterError("boom")

        monkeypatch.setattr(adapter, "_api_post", boom)
        assert adapter.parse_clients("1") == []


class TestParseLeeching:

    def test_rows_and_pagination(self, mt_site, monkeypatch):
        """响应结构按 oes v3.1.5 实测：data.data 为行列表，种子字段在 torrent 子对象。"""
        adapter = make_adapter(mt_site)
        pages = [
            {"total": 3, "data": [
                {"torrent": {"id": 9001, "name": "MT.Torrent.A", "size": 100,
                              "infoHash": "ab" * 20, "status": {"discount": "FREE"}}},
                {"torrent": {"id": 9002, "name": "MT.Torrent.B", "size": 200,
                              "status": {}}},
            ]},
            {"total": 3, "data": [
                {"torrent": {"id": 9003, "name": "MT.Torrent.C", "size": 300,
                              "status": {"discount": "PERCENT_50"}}},
            ]},
        ]

        def fake_api_post(path, payload):
            assert path == "api/member/getUserTorrentList"
            assert payload["type"] == "INCOMPLETE"
            assert payload["userid"] == 606354
            return pages[payload["pageNumber"] - 1]

        monkeypatch.setattr(adapter, "_api_post", fake_api_post)
        torrents = adapter.parse_leeching("606354")
        assert [t["id"] for t in torrents] == ["9001", "9002", "9003"]
        assert torrents[0]["tags"] == ["Free"]
        assert torrents[0]["hash"] == "ab" * 20
        assert torrents[2]["tags"] == ["50%"]
        assert torrents[1]["hash"] == ""

    def test_no_rows_stops(self, mt_site, monkeypatch):
        adapter = make_adapter(mt_site)
        monkeypatch.setattr(adapter, "_api_post", lambda path, payload: {"total": 0, "data": []})
        assert adapter.parse_leeching("1") == []


class TestDiscountTags:

    def test_tokens(self):
        assert MTeamAdapter._discount_tags("FREE") == ["Free"]
        assert MTeamAdapter._discount_tags("_2X") == ["2x"]
        assert MTeamAdapter._discount_tags("PERCENT_50") == ["50%"]
        assert MTeamAdapter._discount_tags("2XFREE") == ["Free", "2x"]
        assert MTeamAdapter._discount_tags(None) == []
        assert MTeamAdapter._discount_tags("") == []


class TestDetailHash:

    def test_no_detail_hash_api(self, mt_site):
        assert make_adapter(mt_site).parse_detail_hash("9001") == ""
