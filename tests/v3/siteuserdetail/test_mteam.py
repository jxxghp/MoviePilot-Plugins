"""M-Team 适配器测试：JWT peers 客户端匹配、API 映射、分页、discount 促销标签。"""

from unittest.mock import Mock

import pytest

from app.plugins.siteuserdetail.adapters.base import AdapterError
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
        "token": "jwt-browser-token",
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

    @staticmethod
    def _seeding_row(tid):
        return {"torrent": {"id": tid, "name": f"T{tid}"}, "peer": {"peerId": "x"}}

    def test_member_id_matching_and_dedup(self, mt_site, monkeypatch):
        """peers 里 memberId 等于自己 uid 的即本人会话；同客户端多会话去重。"""
        adapter = make_adapter(mt_site)
        monkeypatch.setattr(adapter, "_api_post", lambda path, payload: {
            "total": 3, "data": [self._seeding_row(1), self._seeding_row(2)]})

        def fake_signed(path, params):
            assert path == "/api/torrent/peers"
            if params["id"] == "1":
                return [
                    {"memberId": "606354", "agent": "qBittorrent/5.2.4", "ip": "1.2.3.4",
                     "ipv6": "240c::1"},
                    {"memberId": "999", "agent": "Deluge 2.0", "ip": "5.6.7.8", "ipv6": None},
                ]
            # 第二个种子：同客户端同 IP（去重）+ 新 IPv4 会话
            return [
                {"memberId": "606354", "agent": "qBittorrent/5.2.4", "ip": "1.2.3.4",
                 "ipv6": "240c::1"},
                {"memberId": "606354", "agent": "qBittorrent/5.2.4", "ip": "9.9.9.9",
                 "ipv6": None},
            ]

        monkeypatch.setattr(adapter, "_call_signed", fake_signed)
        clients = adapter.parse_clients("606354")
        assert clients == [
            {"agent": "qBittorrent/5.2.4", "ipv4": "1.2.3.4", "ipv6": "240c::1", "port": None},
            {"agent": "qBittorrent/5.2.4", "ipv4": "9.9.9.9", "ipv6": "", "port": None},
        ]

    def test_no_web_token_returns_empty(self, mt_site, monkeypatch):
        adapter = MTeamAdapter({**mt_site, "token": None}, interval=0)
        monkeypatch.setattr(adapter, "_api_post", Mock())  # 不应被调用
        assert adapter.parse_clients("606354") == []

    def test_token_expired_returns_empty(self, mt_site, monkeypatch):
        from app.plugins.siteuserdetail.adapters.base import AdapterError

        adapter = make_adapter(mt_site)

        def boom(path, payload):
            raise AdapterError("Token 登录态已失效，请重新登录站点更新 Token")

        monkeypatch.setattr(adapter, "_api_post", lambda path, payload: {"data": [self._seeding_row(1)]})
        monkeypatch.setattr(adapter, "_call_signed", boom)
        assert adapter.parse_clients("606354") == []


class TestParseLeeching:

    @staticmethod
    def _row(tid, name, size=100, discount=None, peer=None, with_peer=True):
        row = {"torrent": {"id": tid, "name": name, "size": size,
                           "status": {"discount": discount} if discount else {}}}
        if with_peer:
            row["peer"] = peer
        return row

    def test_leecher_zero_returns_empty_without_listing(self, mt_site, monkeypatch):
        """myPeerStatus.leecher=0（无活动下载）直接返回空，不再请求种子列表。"""
        adapter = make_adapter(mt_site)
        calls = []

        def fake_api_post(path, payload):
            calls.append(path)
            return {"seeder": 32, "leecher": "0"}

        monkeypatch.setattr(adapter, "_api_post", fake_api_post)
        assert adapter.parse_leeching("606354") == []
        assert calls == ["api/tracker/myPeerStatus"]

    def test_only_active_peer_rows_returned(self, mt_site, monkeypatch):
        """INCOMPLETE 是历史未完成列表：peer 为空的行（已删种）不算正在下载。"""
        adapter = make_adapter(mt_site)
        pages = [
            {"total": 4, "data": [
                self._row(9001, "Active.A", peer={"status": "DOWNLOADING"}),
                self._row(9002, "Historical.B", peer=None),          # 历史未完成 → 剔除
                self._row(9003, "Active.C", 200, "FREE", peer={"progress": 0.5}),
            ]},
            {"total": 4, "data": [
                self._row(9004, "Active.D", 300, "PERCENT_50", peer={"status": "DOWNLOADING"}),
            ]},
        ]

        def fake_api_post(path, payload):
            if path == "api/tracker/myPeerStatus":
                return {"seeder": 32, "leecher": "3"}
            return pages[payload["pageNumber"] - 1]

        monkeypatch.setattr(adapter, "_api_post", fake_api_post)
        torrents = adapter.parse_leeching("606354")
        assert [t["id"] for t in torrents] == ["9001", "9003", "9004"]
        assert torrents[1]["tags"] == ["Free"]
        assert torrents[1]["hash"] == ""

    def test_fallback_when_peer_field_missing(self, mt_site, monkeypatch):
        """响应无 peer 字段（API 结构变化）时回退为返回全部行。"""
        adapter = make_adapter(mt_site)
        rows = [{"torrent": {"id": 9001, "name": "A", "size": 1}},
                {"torrent": {"id": 9002, "name": "B", "size": 2}}]

        def fake_api_post(path, payload):
            if path == "api/tracker/myPeerStatus":
                raise AdapterError("boom")
            return {"total": 2, "data": rows}

        monkeypatch.setattr(adapter, "_api_post", fake_api_post)
        torrents = adapter.parse_leeching("606354")
        assert [t["id"] for t in torrents] == ["9001", "9002"]

    def test_no_rows_stops(self, mt_site, monkeypatch):
        adapter = make_adapter(mt_site)
        monkeypatch.setattr(adapter, "_api_post", lambda path, payload: (
            {"seeder": 1, "leecher": "5"} if path.endswith("myPeerStatus")
            else {"total": 0, "data": []}))
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
