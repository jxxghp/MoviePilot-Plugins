"""IYUU 站点解析和辅种下载入口的回归测试。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins import iyuuautoseed
from app.plugins.iyuuautoseed import IYUUAutoSeed
from app.plugins.iyuuautoseed.iyuu_helper import IyuuHelper


@pytest.fixture
def reseed(monkeypatch):
    plugin = object.__new__(IYUUAutoSeed)
    plugin.iyuu_helper = IyuuHelper("")
    plugin._sites = [6]
    plugin._labelsafterseed = "辅种"
    plugin._addhosttotag = True
    plugin._recheck_torrents = {}
    plugin._success_caches = []
    seed = {"sid": 3, "torrent_id": 42, "info_hash": "seed-hash"}
    service = SimpleNamespace(name="TR", type="transmission", instance=Mock())
    service.instance.get_torrents.return_value = ([], None)
    service.instance.add_torrent.return_value = SimpleNamespace(hashString="added-hash")
    sites = Mock()
    request = Mock()
    torrent = Mock()
    sites.check.return_value = (False, "")
    monkeypatch.setattr(iyuuautoseed, "SitesHelper", lambda: sites)
    monkeypatch.setattr(iyuuautoseed, "RequestUtils", request)
    monkeypatch.setattr(iyuuautoseed, "TorrentHelper", lambda: torrent)
    return SimpleNamespace(plugin=plugin, seed=seed, service=service, sites=sites,
                           request=request, torrent=torrent)


def _download(reseed, source, template="api/torrent/genDlToken", **meta):
    """按指定 IYUU 站点信息执行一次辅种下载。"""
    site_meta = {"base_url": source, "download_page": template}
    site_meta.update(meta)
    reseed.plugin.iyuu_helper._sites = {3: site_meta}
    return reseed.plugin._IYUUAutoSeed__download_torrent(reseed.seed, reseed.service, "/data", "tv")


def test_api_domain_matched_by_domain_body(reseed):
    """IYUU 用 api.m-team.cc、MoviePilot 用 m-team.io 时按域名主体命中，仍用 IYUU 域名调接口。"""
    site = {"id": 6, "name": "M-Team", "domain": "m-team.io", "url": "https://kp.m-team.io/",
            "apikey": "test-key", "proxy": True}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    reseed.request.return_value.post_res.return_value.json.return_value = {
        "data": "https://download.example/torrent"
    }
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is True

    reseed.sites.check.assert_called_once_with("m-team.io")
    assert reseed.request.call_args.kwargs["headers"]["x-api-key"] == "test-key"
    # UA 必须走请求库参数，写进 headers 会被站点判为浏览器访问
    assert "User-Agent" not in reseed.request.call_args.kwargs["headers"]
    reseed.request.return_value.post_res.assert_called_once_with(
        "https://api.m-team.cc/api/torrent/genDlToken", params={"id": 42}
    )
    assert reseed.torrent.download_torrent.call_args.kwargs["proxy"] is True
    reseed.service.instance.add_torrent.assert_called_once_with(
        content=b"torrent", download_dir="/data", is_paused=True, labels=["辅种", "M-Team"]
    )


def test_skyeysnow_matched_by_site_name(reseed):
    """IYUU 与 MoviePilot 使用不同天雪域名时按站点名命中，并用本地站点的 Cookie 下载。"""
    site = {"id": 6, "name": "天雪", "domain": "skyeysnow.com", "url": "https://skyeysnow.com/",
            "cookie": "test-cookie", "ua": "test-ua"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "skyey2.com", "download.php?id={}&passkey={passkey}",
                     nickname="天雪", site="skyey") is True

    reseed.sites.check.assert_called_once_with("skyeysnow.com")
    reseed.torrent.download_torrent.assert_called_once_with(
        url="https://skyeysnow.com/download.php?id=42&https=1",
        cookie="test-cookie", ua="test-ua", proxy=None
    )
    reseed.service.instance.add_torrent.assert_called_once()


def test_exact_match_takes_priority_and_respects_site_selection(reseed):
    reseed.sites.get_indexer.side_effect = {
        "m-team.cc": {"id": 7, "url": "https://kp.m-team.cc/"},
        "m-team.io": {"id": 6, "url": "https://zp.m-team.io/"},
    }.get

    assert _download(reseed, "api.m-team.cc") is False

    reseed.sites.get_indexer.assert_called_once_with("m-team.cc")
    reseed.sites.check.assert_not_called()
    reseed.request.assert_not_called()


def test_matched_site_respects_rate_limit(reseed):
    """域名主体命中后仍按本地站点域名走流控。"""
    site = {"id": 6, "name": "M-Team", "domain": "m-team.io", "url": "https://kp.m-team.io/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    reseed.sites.check.return_value = (True, "触发站点流控")

    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is False

    reseed.sites.check.assert_called_once_with("m-team.io")
    reseed.request.assert_not_called()


def test_ambiguous_domain_body_is_skipped(reseed):
    """多个站点域名主体相同时不猜，直接跳过。"""
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [
        {"id": 6, "name": "A", "domain": "m-team.io", "url": "https://kp.m-team.io/"},
        {"id": 7, "name": "B", "domain": "m-team.net", "url": "https://zp.m-team.net/"},
    ]

    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is False

    reseed.sites.check.assert_not_called()
    reseed.request.assert_not_called()


def test_unrelated_site_is_not_matched(reseed):
    """域名与站点名都对不上时不下载。"""
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [
        {"id": 6, "name": "家园", "domain": "hdhome.org", "url": "https://hdhome.org/"},
    ]

    assert _download(reseed, "hdsky.me", "download.php?id={id}", nickname="天空", site="hdsky") is False

    reseed.sites.check.assert_not_called()
    reseed.request.assert_not_called()
