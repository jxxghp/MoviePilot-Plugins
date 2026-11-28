"""IYUUAutoSeed V2 辅种缓存与站点退避测试。

缓存结构为 ``hash -> 过期时间戳`` 的字典：``0`` 表示不再重试，非 0 到期后放行；
旧版 ``list`` 结构不再兼容，读入时按空缓存处理。站点级退避按域名计数，
连续取种失败达阈值后整体跳过，到期自动恢复且不影响其他站点。
"""

import hashlib
import time
from types import SimpleNamespace

import pytest

from app.plugins import iyuuautoseed
from app.plugins.iyuuautoseed import IYUUAutoSeed

HASH = "a" * 40


def _plugin():
    """构造未初始化的插件实例，只使用纯内存方法。"""
    return IYUUAutoSeed()


def test_legacy_list_cache_is_discarded():
    """旧版 list 结构不再兼容，升级后按空缓存处理并重新尝试。"""
    plugin = _plugin()
    assert plugin._IYUUAutoSeed__load_seed_cache([HASH]) == {}


def test_new_dict_cache_roundtrip():
    """新结构回读后保留原过期时间。"""
    plugin = _plugin()
    expire = time.time() + 60
    cache = plugin._IYUUAutoSeed__load_seed_cache({HASH: expire})
    assert cache[HASH] == expire


def test_expired_entry_is_released():
    """过期条目不再命中缓存，下一轮会重试。"""
    hit = _plugin()._IYUUAutoSeed__cache_hit
    assert hit({HASH: time.time() - 1}, HASH) is False
    assert hit({HASH: time.time() + 60}, HASH) is True


def test_permanent_entry_never_expires():
    """0 表示不再重试，永久命中；缺失的 hash 不算命中。"""
    hit = _plugin()._IYUUAutoSeed__cache_hit
    assert hit({HASH: 0}, HASH) is True
    assert hit({}, HASH) is False


def test_trim_drops_expired_entries():
    """整理缓存时清掉过期条目，永久条目保留。"""
    plugin = _plugin()
    cache = {HASH: time.time() - 5, "b" * 40: 0}
    plugin._IYUUAutoSeed__trim_seed_cache(cache)
    assert HASH not in cache
    assert "b" * 40 in cache


def test_site_backoff_isolated_per_domain():
    """一个站点退避不影响其他站点。"""
    plugin = _plugin()
    plugin._site_backoff = {}
    for _ in range(plugin._site_backoff_threshold):
        plugin._IYUUAutoSeed__mark_site_backoff("a.example")
    assert plugin._IYUUAutoSeed__site_available("a.example") is False
    assert plugin._IYUUAutoSeed__site_available("b.example") is True


def test_site_backoff_expires():
    """退避窗口到期后站点恢复，并清掉记录。"""
    plugin = _plugin()
    plugin._site_backoff = {"a.example": {"fails": 3, "until": time.time() - 1}}
    assert plugin._IYUUAutoSeed__site_available("a.example") is True
    assert "a.example" not in plugin._site_backoff


def test_site_backoff_cleared_after_success():
    """取种成功后清除站点失败计数。"""
    plugin = _plugin()
    plugin._site_backoff = {"a.example": {"fails": 2, "until": 0}}
    plugin._IYUUAutoSeed__clear_site_backoff("a.example")
    assert "a.example" not in plugin._site_backoff


def _bstr(value: bytes) -> bytes:
    return str(len(value)).encode() + b":" + value


def _torrent(info: bytes) -> bytes:
    """把 info 字典包成最小种子文件。"""
    return b"d" + _bstr(b"announce") + _bstr(b"http://tracker.local") + _bstr(b"info") + info + b"e"


def test_info_hash_matches_target():
    """详情页候选种子按 info_hash 与 IYUU 目标比对。"""
    plugin = _plugin()
    info = (b"d" + _bstr(b"length") + b"i1024e" + _bstr(b"name") + _bstr(b"test.iso")
            + _bstr(b"piece length") + b"i16384e" + _bstr(b"pieces") + _bstr(b"a" * 20) + b"e")
    assert plugin._IYUUAutoSeed__torrent_info_hash(_torrent(info)) == hashlib.sha1(info).hexdigest()


def test_info_hash_rejects_other_torrent():
    """同页其他种子（合集/多版本）不能被当成目标。"""
    plugin = _plugin()
    info_a = b"d" + _bstr(b"name") + _bstr(b"a.iso") + b"e"
    info_b = b"d" + _bstr(b"name") + _bstr(b"b.iso") + b"e"
    assert plugin._IYUUAutoSeed__torrent_info_hash(_torrent(info_a)) \
        != hashlib.sha1(info_b).hexdigest()


def test_info_hash_invalid_content():
    """无法解析的内容返回空串，调用方按失败处理。"""
    plugin = _plugin()
    assert plugin._IYUUAutoSeed__torrent_info_hash(b"not-a-torrent") == ""
    assert plugin._IYUUAutoSeed__torrent_info_hash(b"d" + _bstr(b"info") + b"e") == ""


def test_info_hash_ignores_lookalike_keys():
    """announce/comment 里出现 4:info 时不得误当作 info 字典。"""
    plugin = _plugin()
    info = b"d" + _bstr(b"name") + _bstr(b"a.iso") + b"e"
    content = (b"d" + _bstr(b"announce") + _bstr(b"http://tracker.local/?4:info")
               + _bstr(b"comment") + _bstr(b"4:info") + _bstr(b"info") + info + b"e")
    assert plugin._IYUUAutoSeed__torrent_info_hash(content) == hashlib.sha1(info).hexdigest()


@pytest.mark.parametrize("code,msg,aborted,reason", [
    (0, "无数据", False, None),                     # 接口正常但没有可辅种数据
    (401, "unauthorized", True, "auth"),            # 英文 msg 也要认出是鉴权问题
    (403, "forbidden", True, "auth"),
    (429, "too many", True, "api"),
    (500, "server error", True, "api"),
    (502, "bad gateway", True, "api"),
    (None, "网络错误", True, "api"),
    (-1, "未知业务码", True, "api"),                # 未知码按接口失败处理，不静默跳过
    ("no_sites", "本机没有已配置且可匹配的辅种站点", True, "no_sites"),
])
def test_iyuu_failure_aborts_round(code, msg, aborted, reason):
    """鉴权失败、限流与 5xx 都要中止本轮，业务层“没有可辅种”不算接口故障。"""
    plugin = _plugin()
    plugin._token = "token"
    plugin._auto_downloader = None
    plugin._iyuu_aborted = False
    plugin._abort_reason = None
    plugin._error_caches = {}
    plugin.iyuu_helper = SimpleNamespace(
        get_seed_info=lambda hashs: (None, msg, code))
    plugin._IYUUAutoSeed__seed_torrents(
        hash_strs=[{"hash": HASH, "save_path": "/data", "category": None}],
        service=SimpleNamespace(name="QB"),
        completed_hashes_downloader=set())
    assert plugin._iyuu_aborted is aborted
    assert plugin._abort_reason == reason


def test_missing_token_is_reported_as_auth_reason():
    """令牌缺失单独归类，通知不能笼统写成接口异常。"""
    plugin = _plugin()
    plugin._token = "token"
    plugin._auto_downloader = None
    plugin._iyuu_aborted = False
    plugin._abort_reason = None
    plugin._error_caches = {}
    plugin.iyuu_helper = SimpleNamespace(
        get_seed_info=lambda hashs: (None, "请求缺少token", 0))
    plugin._IYUUAutoSeed__seed_torrents(
        hash_strs=[{"hash": HASH, "save_path": "/data", "category": None}],
        service=SimpleNamespace(name="QB"),
        completed_hashes_downloader=set())
    assert plugin._abort_reason == "auth"


def test_auth_reason_does_not_depend_on_chinese_message():
    """鉴权原因不能只靠中文子串判定，英文响应同样要归到 auth。"""
    plugin = _plugin()
    plugin._token = "token"
    plugin._auto_downloader = None
    plugin._iyuu_aborted = False
    plugin._abort_reason = None
    plugin._error_caches = {}
    plugin.iyuu_helper = SimpleNamespace(
        get_seed_info=lambda hashs: (None, "Unauthorized", 401))
    plugin._IYUUAutoSeed__seed_torrents(
        hash_strs=[{"hash": HASH, "save_path": "/data", "category": None}],
        service=SimpleNamespace(name="QB"),
        completed_hashes_downloader=set())
    assert plugin._abort_reason == "auth"


def test_report_sids_keeps_only_configured_sites(monkeypatch):
    """只上报本机已配置并能匹配到的 IYUU 站点。"""
    plugin = _plugin()
    plugin._sites = [6]
    plugin.iyuu_helper = SimpleNamespace(get_all_sites=lambda: {
        3: {"site": "m-team", "nickname": "馒头", "base_url": "api.m-team.cc"},
        9: {"site": "hdhome", "nickname": "家园", "base_url": "hdhome.org"},
    })
    monkeypatch.setattr(iyuuautoseed, "SitesHelper", lambda: SimpleNamespace(get_indexers=lambda: [
        {"id": 6, "name": "M-Team", "domain": "m-team.io", "url": "https://kp.m-team.io/"},
    ]))
    assert plugin._IYUUAutoSeed__report_sids() == [3]
