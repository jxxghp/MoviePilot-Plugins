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


def _download(reseed, source, template="api/torrent/genDlToken"):
    reseed.plugin.iyuu_helper._sites = {3: {"base_url": source, "download_page": template}}
    return reseed.plugin._IYUUAutoSeed__download_torrent(reseed.seed, reseed.service, "/data", "tv")


@pytest.mark.parametrize(("source", "configured_domain"), [
    ("api.m-team.cc", "m-team.io"),
    ("https://api.m-team.io/", "m-team.cc"),
])
def test_mteam_uses_configured_alias_for_rate_limit_and_download(reseed, source, configured_domain):
    site = {"id": 6, "name": "自定义站点名", "domain": f"https://zp.{configured_domain}/",
            "url": f"https://zp.{configured_domain}/", "apikey": "test-key", "proxy": True}
    reseed.sites.get_indexer.side_effect = {configured_domain: site}.get
    reseed.request.return_value.post_res.return_value.json.return_value = {
        "data": "https://download.example/torrent"
    }
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, source) is True

    reseed.sites.check.assert_called_once_with(configured_domain)
    assert reseed.request.call_args.kwargs["headers"]["x-api-key"] == "test-key"
    reseed.request.return_value.post_res.assert_called_once_with(
        f"https://api.{configured_domain}/api/torrent/genDlToken", params={"id": 42}
    )
    assert reseed.torrent.download_torrent.call_args.kwargs["proxy"] is True
    reseed.service.instance.add_torrent.assert_called_once_with(
        content=b"torrent", download_dir="/data", is_paused=True, labels=["辅种", "自定义站点名"]
    )


@pytest.mark.parametrize(("source_domain", "configured_domain"), [
    ("skyey2.com", "skyeysnow.com"),
    ("skyeysnow.com", "skyey2.com"),
])
def test_skyeysnow_uses_configured_alias_for_download(reseed, source_domain, configured_domain):
    """天雪别名命中后使用本地站点的 Cookie 和域名下载。"""
    reseed.sites.get_indexer.side_effect = {
        source_domain: {"id": "skyeysnow", "name": "天雪"},
        configured_domain: {"id": 6, "name": "天雪", "url": f"https://{configured_domain}/",
                            "cookie": "test-cookie", "ua": "test-ua"},
    }.get
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, source_domain, "download.php?id={}&passkey={passkey}") is True

    reseed.sites.check.assert_called_once_with(configured_domain)
    reseed.torrent.download_torrent.assert_called_once_with(
        url=f"https://{configured_domain}/download.php?id=42&https=1",
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


def test_alias_respects_rate_limit(reseed):
    reseed.sites.get_indexer.side_effect = {
        "m-team.io": {"id": 6, "url": "https://zp.m-team.io/"},
    }.get
    reseed.sites.check.return_value = (True, "触发站点流控")

    assert _download(reseed, "api.m-team.cc") is False

    reseed.sites.check.assert_called_once_with("m-team.io")
    reseed.request.assert_not_called()


@pytest.mark.parametrize(("source", "lookup_domain", "other_domain"), [
    ("lemonhd.club", "lemonhd.club", "lemonhd.net"),
    ("api.m-team.net", "m-team.net", "m-team.io"),
])
def test_similar_domains_are_not_matched(reseed, source, lookup_domain, other_domain):
    reseed.sites.get_indexer.side_effect = {
        other_domain: {"id": 6, "url": f"https://{other_domain}/"},
    }.get

    assert _download(reseed, source, "download.php?id={id}") is False

    reseed.sites.get_indexer.assert_called_once_with(lookup_domain)
    reseed.sites.check.assert_not_called()
    reseed.request.assert_not_called()
