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
    plugin._api_bases = {}
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


def test_api_uses_mp_site_url_first(reseed):
    """API 端点优先用 MP 站点地址，用户配镜像域名时自然走镜像。"""
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
        "https://kp.m-team.io/api/torrent/genDlToken", params={"id": 42}
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
        url="https://skyeysnow.com/download.php?id=42",
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


def test_api_falls_back_to_iyuu_host(reseed):
    """MP 站点地址取不到时退回 IYUU 清单给的主机（m-team 这类 API 在独立子域）。"""
    site = {"id": 6, "name": "M-Team", "domain": "m-team.io", "url": "https://kp.m-team.io/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    reseed.request.return_value.post_res.side_effect = [None, response]
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is True

    urls = [call.args[0] for call in reseed.request.return_value.post_res.call_args_list]
    assert urls == ["https://kp.m-team.io/api/torrent/genDlToken",
                    "https://api.m-team.cc/api/torrent/genDlToken"]


def test_api_base_without_guessed_api_prefix(reseed):
    """兜底不再猜 api. 子域，多级域名不会被拼成 api.test.test-m-team.test 这类主机。"""
    site = {"id": 6, "name": "馒头", "domain": "test.test-m-team.test",
            "url": "https://test.test-m-team.test/", "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    reseed.request.return_value.post_res.side_effect = [None, None, response]
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is True

    urls = [call.args[0] for call in reseed.request.return_value.post_res.call_args_list]
    assert urls == ["https://test.test-m-team.test/api/torrent/genDlToken",
                    "https://api.m-team.cc/api/torrent/genDlToken",
                    "https://test-m-team.test/api/torrent/genDlToken"]
    assert not any("api.test" in url for url in urls)


def test_api_path_template_falls_back_to_iyuu_api_host(reseed):
    """API 挂在独立子域时（piggo），MP 站点地址失败后退回 IYUU 的 api 主机。"""
    site = {"id": 6, "name": "馒头", "domain": "piggo.me", "url": "https://piggo.me/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    reseed.request.return_value.post_res.side_effect = [None, response]
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.piggo.me", "v1/api/torrents/genDlToken",
                     nickname="馒头", site="m-team") is True

    urls = [call.args[0] for call in reseed.request.return_value.post_res.call_args_list]
    assert urls == ["https://piggo.me/v1/api/torrents/genDlToken",
                    "https://api.piggo.me/v1/api/torrents/genDlToken"]


def test_api_endpoint_falls_back_to_registered_domain(reseed):
    """未收录的多级后缀会把注册域名切错，最后一级仍用注册域名兜住。"""
    site = {"id": 6, "name": "馒头", "domain": "foo.web.id", "url": "https://foo.web.id/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    reseed.request.return_value.post_res.side_effect = [None, None, response]
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.old-host.id", "v1/api/torrents/genDlToken",
                     nickname="馒头", site="m-team") is True

    urls = [call.args[0] for call in reseed.request.return_value.post_res.call_args_list]
    assert urls == ["https://foo.web.id/v1/api/torrents/genDlToken",
                    "https://api.old-host.id/v1/api/torrents/genDlToken",
                    "https://web.id/v1/api/torrents/genDlToken"]


def test_site_matched_by_compact_name(reseed):
    """站点名写成 M-Team 时，与 IYUU 站点标识去分隔符后比对命中。"""
    site = {"id": 6, "name": "M-Team", "domain": "m-team.io", "url": "https://kp.m-team.io/",
            "cookie": "test-cookie", "ua": "test-ua"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "mteam.example", "download.php?id={id}",
                     nickname="馒头", site="m-team") is True

    reseed.sites.check.assert_called_once_with("m-team.io")
    reseed.torrent.download_torrent.assert_called_once_with(
        url="https://kp.m-team.io/download.php?id=42",
        cookie="test-cookie", ua="test-ua", proxy=None
    )


def test_template_with_torrent_key_placeholder(reseed):
    """带 {torrent_key} 的模板只保留 id，保持旧版整段丢弃的行为。"""
    site = {"id": 6, "name": "朱雀", "domain": "zhuque.in", "url": "https://zhuque.in/",
            "cookie": "test-cookie", "ua": "test-ua"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "zhuque.in", "api/torrent/download/{}/{torrent_key}",
                     nickname="朱雀", site="zhuque") is True

    reseed.torrent.download_torrent.assert_called_once_with(
        url="https://zhuque.in/api/torrent/download/42",
        cookie="test-cookie", ua="test-ua", proxy=None
    )


def test_hash_template_without_id_stays_on_detail_page(reseed):
    """没有 id 的 hash 模板，hash 只能来自详情页，不能拿 API 凭证顶替。"""
    site = {"id": 6, "name": "瓷器", "domain": "hdwing.org", "url": "https://hdwing.org/",
            "cookie": "test-cookie", "ua": "test-ua", "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]

    assert _download(reseed, "hdwing.org", "download.php?hash={hash}",
                     nickname="瓷器", site="hdchina") is False
    reseed.request.return_value.post_res.assert_not_called()


def test_api_base_follows_iyuu_http_declaration(reseed):
    """IYUU 声明 is_https=0 的站点，退回其主机时要用 http，不能写死 https。"""
    site = {"id": 6, "name": "路", "domain": "hdroute.org", "url": "https://hdroute.org/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return None if url.startswith("https://hdroute.org") else response

    reseed.request.return_value.post_res.side_effect = fake_post
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "www.hdroute.org", "v1/api/torrents/genDlToken",
                     nickname="路", site="hdroute", is_https=0) is True
    assert attempts == ["https://hdroute.org/v1/api/torrents/genDlToken",
                        "http://www.hdroute.org/v1/api/torrents/genDlToken"]

def test_api_base_probed_once_per_site(reseed):
    """同一站点命中端点后记下，后续种子不再逐个候选重试。"""
    site = {"id": 6, "name": "馒头", "domain": "m-team.io", "url": "https://kp.m-team.io/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return None if ("invalid" in url or url.startswith("https://kp.")) else response

    reseed.request.return_value.post_res.side_effect = fake_post
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    for _ in range(2):
        assert _download(reseed, "api.m-team.invalid", nickname="馒头", site="m-team") is True

    assert attempts == ["https://kp.m-team.io/api/torrent/genDlToken",
                        "https://api.m-team.invalid/api/torrent/genDlToken",
                        "https://m-team.io/api/torrent/genDlToken",
                        "https://m-team.io/api/torrent/genDlToken"]


def test_api_endpoint_skipped_after_all_bases_failed(reseed):
    """端点全部不可用的站点，同一次任务内不再为后续种子重试。"""
    site = {"id": 6, "name": "馒头", "domain": "m-team.io", "url": "https://kp.m-team.io/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return None

    reseed.request.return_value.post_res.side_effect = fake_post

    _download(reseed, "api.m-team.invalid", nickname="馒头", site="m-team")
    assert len(attempts) == 3
    _download(reseed, "api.m-team.invalid", nickname="馒头", site="m-team")
    assert len(attempts) == 3


def test_stale_cached_api_base_falls_through(reseed):
    """缓存的端点失效时仍会继续试其它候选，不会把站点钉死。"""
    site = {"id": 6, "name": "馒头", "domain": "m-team.io", "url": "https://kp.m-team.io/",
            "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    attempts = []
    dead = {"https://kp.m-team.io"}

    def fake_post(url, **kwargs):
        attempts.append(url)
        return None if any(url.startswith(item) for item in dead) else response

    reseed.request.return_value.post_res.side_effect = fake_post
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is True
    dead.add("https://api.m-team.cc")
    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is True

    assert attempts == ["https://kp.m-team.io/api/torrent/genDlToken",
                        "https://api.m-team.cc/api/torrent/genDlToken",
                        "https://api.m-team.cc/api/torrent/genDlToken",
                        "https://kp.m-team.io/api/torrent/genDlToken",
                        "https://m-team.io/api/torrent/genDlToken"]


def test_api_endpoint_follows_iyuu_subdomain_after_migration(reseed):
    """站点换域名而 IYUU 清单滞后时，跟随清单主机的子域前缀在新域名上换取下载链接。"""
    site = {"id": 6, "name": "馒头", "domain": "m-team.test", "url": "https://m-team.test/",
             "apikey": "test-key"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": "https://download.example/torrent"}
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return response if url == "https://api.m-team.test/api/torrent/genDlToken" else None

    reseed.request.return_value.post_res.side_effect = fake_post
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.m-team.cc", nickname="馒头", site="m-team") is True

    assert attempts == ["https://m-team.test/api/torrent/genDlToken",
                        "https://api.m-team.cc/api/torrent/genDlToken",
                        "https://api.m-team.test/api/torrent/genDlToken"]


def test_token_endpoint_tries_site_url_then_follows_prefix(reseed):
    """带 download-link 的模板同样走候选遍历：站点地址 → IYUU 主机 → 跟随前缀的新域名。"""
    site = {"id": 6, "name": "猪猪", "domain": "pig.test", "url": "https://pig.test/",
            "token": "test-token"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": {"url": "https://download.example/torrent"}}
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return response if url == "https://api.pig.test/v1/api/torrents/42/download-link" else None

    reseed.request.return_value.post_res.side_effect = fake_post
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.piggo.me", "/v1/api/torrents/{}/download-link",
                     nickname="猪猪", site="piggo") is True

    assert attempts == ["https://pig.test/v1/api/torrents/42/download-link",
                        "https://api.piggo.me/v1/api/torrents/42/download-link",
                        "https://api.pig.test/v1/api/torrents/42/download-link"]
    assert reseed.request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"


def test_token_endpoint_keeps_mirror_subdomain(reseed):
    """站点地址填的是镜像子域时以用户配置为准，不再拼 api 前缀主机。"""
    site = {"id": 6, "name": "猪猪", "domain": "mirror.pig.test", "url": "https://mirror.pig.test/",
            "token": "test-token"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": {"url": "https://download.example/torrent"}}
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return response if url == "https://api.piggo.me/v1/api/torrents/42/download-link" else None

    reseed.request.return_value.post_res.side_effect = fake_post
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.piggo.me", "/v1/api/torrents/{}/download-link",
                     nickname="猪猪", site="piggo") is True

    assert attempts == ["https://mirror.pig.test/v1/api/torrents/42/download-link",
                        "https://api.piggo.me/v1/api/torrents/42/download-link"]
    assert not any(url.startswith("https://api.pig.test") for url in attempts)


def test_token_endpoint_probed_once_per_site(reseed):
    """download-link 模板命中端点后记下，同站后续种子不再逐个候选重试。"""
    site = {"id": 6, "name": "猪猪", "domain": "pig.test", "url": "https://pig.test/",
            "token": "test-token"}
    reseed.sites.get_indexer.side_effect = {}.get
    reseed.sites.get_indexers.return_value = [site]
    response = Mock()
    response.json.return_value = {"data": {"url": "https://download.example/torrent"}}
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return response if url == "https://api.pig.test/v1/api/torrents/42/download-link" else None

    reseed.request.return_value.post_res.side_effect = fake_post
    reseed.torrent.download_torrent.return_value = (None, b"torrent", None, None, None)

    assert _download(reseed, "api.piggo.me", "/v1/api/torrents/{}/download-link",
                     nickname="猪猪", site="piggo") is True
    first = len(attempts)
    assert _download(reseed, "api.piggo.me", "/v1/api/torrents/{}/download-link",
                     nickname="猪猪", site="piggo") is True

    assert len(attempts) == first + 1
    assert attempts[first] == "https://api.pig.test/v1/api/torrents/42/download-link"

@pytest.mark.parametrize("host, expected", [
    ("www.m-team-test.test", "m-team-test.test"),
    ("api.m-team-test.test", "m-team-test.test"),
    ("www.api.m-team-test.test", "m-team-test.test"),
    ("test.m-team-test.test", "m-team-test.test"),
    ("www.m-team.cc", "m-team.cc"),
    ("a.b.m-team.cc", "m-team.cc"),
    ("www.x.com.cn", "x.com.cn"),
    ("hudbt.hust.edu.cn", "hust.edu.cn"),
    ("x.edu.cn", "x.edu.cn"),
    ("test.m-team.com.au", "m-team.com.au"),
    ("site.co.nz", "site.co.nz"),
    ("pt.www.abc.com", "abc.com"),
])
def test_registered_domain_strips_entry_prefixes(host, expected):
    """注册域名忽略入口前缀与普通子域，多级公共后缀保留两段。"""
    assert IYUUAutoSeed._IYUUAutoSeed__registered_domain(host) == expected


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
