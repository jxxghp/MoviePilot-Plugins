"""qBittorrent 添加结果判定、遗留任务认领与配置容错的回归测试。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins import iyuuautoseed
from app.plugins.iyuuautoseed import IYUUAutoSeed
from app.plugins.iyuuautoseed.iyuu_helper import IyuuHelper

# 名称改写后的私有方法，集中声明避免用例里到处写魔法字符串
DOWNLOAD = "_IYUUAutoSeed__download"
DOWNLOAD_TORRENT = "_IYUUAutoSeed__download_torrent"
ADOPT = "_IYUUAutoSeed__adopt_recheck_torrents"


def _plugin():
    """构造一个只带运行期状态的插件实例，不触发 init_plugin 的外部依赖。"""
    plugin = object.__new__(IYUUAutoSeed)
    plugin.iyuu_helper = IyuuHelper("")
    plugin._sites = []
    plugin._labelsafterseed = "辅种"
    plugin._addhosttotag = False
    plugin._recheck_torrents = {}
    plugin._error_caches = []
    plugin._success_caches = []
    plugin._permanent_error_caches = []
    plugin._api_bases = {}
    plugin._skipverify = False
    plugin._auto_start = False
    plugin._auto_category = False
    plugin._categoryafterseed = None
    plugin._reuse_save_path = True
    plugin._auto_downloader = None
    plugin._size = 0
    plugin._nopaths = None
    plugin._nolabels = None
    return plugin


def _qb_service(torrents=None):
    service = SimpleNamespace(name="QB", type="qbittorrent", instance=Mock())
    service.instance.get_torrents.return_value = (torrents or [], None)
    service.instance.add_torrent.return_value = (True, ["added-hash"])
    service.instance.get_torrent_id_by_tag.return_value = "tag-hash"
    return service


@pytest.fixture
def reseed(monkeypatch):
    """馒头 API 取种链路可跑通的 qB 场景。"""
    plugin = _plugin()
    seed = {"sid": 3, "torrent_id": 42, "info_hash": "seed-hash"}
    service = _qb_service()
    sites = Mock()
    torrent = Mock()
    request = Mock()
    sites.get_indexer.side_effect = {}.get
    sites.get_indexers.return_value = [
        {"id": 6, "name": "M-Team", "domain": "m-team.io", "url": "https://kp.m-team.io/", "apikey": "test-key"}
    ]
    sites.check.return_value = (False, "")
    torrent.download_torrent.return_value = (None, b"torrent", None, None, None)
    request.return_value.post_res.return_value.json.return_value = {
        "data": "https://download.example/torrent"
    }
    monkeypatch.setattr(iyuuautoseed, "SitesHelper", lambda: sites)
    monkeypatch.setattr(iyuuautoseed, "TorrentHelper", lambda: torrent)
    monkeypatch.setattr(iyuuautoseed, "RequestUtils", request)
    plugin.iyuu_helper._sites = {
        3: {"base_url": "api.m-team.cc", "download_page": "api/torrent/genDlToken"}
    }
    return SimpleNamespace(plugin=plugin, seed=seed, service=service, sites=sites, torrent=torrent,
                           request=request)


# ---------------------------------------------------------------- 添加结果判定

def test_qb_ids_are_used_without_tag_polling(reseed):
    """添加响应已带任务标识时直接取用，不再逐个种子轮询标签。"""
    torrent_hash, added = getattr(reseed.plugin, DOWNLOAD)(
        service=reseed.service, content=b"torrent", save_path="/data",
        save_category="tv", site_name="M-Team"
    )

    assert (torrent_hash, added) == ("added-hash", True)
    reseed.service.instance.get_torrent_id_by_tag.assert_not_called()
    reseed.service.instance.set_torrent_category.assert_called_once_with(
        hash_string="added-hash", category="tv"
    )


def test_qb_falls_back_to_tag_when_ids_empty(reseed):
    """未开启自动分类时 qB 不返回标识，仍需按标签兜底。"""
    reseed.service.instance.add_torrent.return_value = (True, [])

    torrent_hash, added = getattr(reseed.plugin, DOWNLOAD)(
        service=reseed.service, content=b"torrent", save_path="/data",
        save_category=None, site_name="M-Team"
    )

    assert (torrent_hash, added) == ("tag-hash", True)
    reseed.service.instance.get_torrent_id_by_tag.assert_called_once()


def test_qb_rejects_tuple_return_without_falsy_check(reseed):
    """(True, []) 与 (False, []) 都必须按添加结果本身判定。"""
    reseed.service.instance.add_torrent.return_value = (False, ["added-hash"])

    assert getattr(reseed.plugin, DOWNLOAD)(
        service=reseed.service, content=b"torrent", save_path="/data",
        save_category=None, site_name="M-Team"
    ) == (None, False)
    reseed.service.instance.get_torrent_id_by_tag.assert_not_called()


def test_qb_added_but_id_unknown_reports_added(reseed):
    """任务已进下载器只是取不到标识，返回 added=True 供上层区分。"""
    reseed.service.instance.add_torrent.return_value = (True, [])
    reseed.service.instance.get_torrent_id_by_tag.return_value = None

    assert getattr(reseed.plugin, DOWNLOAD)(
        service=reseed.service, content=b"torrent", save_path="/data",
        save_category=None, site_name="M-Team"
    ) == (None, True)


# ------------------------------------------------------- 失败缓存只在真失败时写

def test_seed_failure_is_cached(reseed):
    """添加被下载器拒绝时按失败处理并写入缓存。"""
    reseed.service.instance.add_torrent.return_value = (False, [])

    assert getattr(reseed.plugin, DOWNLOAD_TORRENT)(
        reseed.seed, reseed.service, "/data", "tv"
    ) is False
    assert reseed.plugin.fail == 1
    assert reseed.seed["info_hash"] in reseed.plugin._error_caches


def test_seed_added_without_id_is_not_cached(reseed):
    """已添加但未取到标识不得写入失败缓存，否则该种永远进不了兜底链路。"""
    reseed.service.instance.add_torrent.return_value = (True, [])
    reseed.service.instance.get_torrent_id_by_tag.return_value = None

    assert getattr(reseed.plugin, DOWNLOAD_TORRENT)(
        reseed.seed, reseed.service, "/data", "tv"
    ) is False
    assert reseed.plugin.fail == 1
    assert reseed.plugin._error_caches == []
    assert reseed.plugin._permanent_error_caches == []
    assert reseed.plugin._success_caches == []


# -------------------------------------------------------- 遗留辅种任务的认领兜底

def test_existing_seed_tagged_task_is_adopted_for_recheck(reseed):
    """下载器里已有的暂停辅种任务补入校验队列，避免停在未校验状态。"""
    torrent = {"hash": "seed-hash", "tags": "辅种,M-Team", "state": "stalledDL"}
    reseed.service.instance.get_torrents.return_value = ([torrent], None)

    assert getattr(reseed.plugin, DOWNLOAD_TORRENT)(
        reseed.seed, reseed.service, "/data", "tv"
    ) is False
    assert reseed.plugin.exist == 1
    assert reseed.plugin._recheck_torrents["QB"] == ["seed-hash"]


def test_existing_task_without_seed_label_is_left_alone(reseed):
    """用户自行暂停的普通下载不属于辅种，不得被接管。"""
    torrent = {"hash": "seed-hash", "tags": "电影", "state": "pausedDL"}
    reseed.service.instance.get_torrents.return_value = ([torrent], None)

    getattr(reseed.plugin, DOWNLOAD_TORRENT)(reseed.seed, reseed.service, "/data", "tv")

    assert reseed.plugin._recheck_torrents.get("QB", []) == []


def test_existing_seeding_task_is_not_adopted(reseed):
    """已在做种的种子无需校验，避免反复打断正常做种。"""
    torrent = {"hash": "seed-hash", "tags": "辅种", "state": "pausedUP"}
    reseed.service.instance.get_torrents.return_value = ([torrent], None)

    getattr(reseed.plugin, DOWNLOAD_TORRENT)(reseed.seed, reseed.service, "/data", "tv")

    assert reseed.plugin._recheck_torrents.get("QB", []) == []


def test_adopt_does_not_duplicate_queued_hash(reseed):
    """同一轮重复命中时不重复排队。"""
    torrent = {"hash": "seed-hash", "tags": "辅种", "state": "stoppedDL"}
    reseed.service.instance.get_torrents.return_value = ([torrent], None)

    getattr(reseed.plugin, DOWNLOAD_TORRENT)(reseed.seed, reseed.service, "/data", "tv")
    getattr(reseed.plugin, DOWNLOAD_TORRENT)(reseed.seed, reseed.service, "/data", "tv")

    assert reseed.plugin._recheck_torrents["QB"] == ["seed-hash"]


# ------------------------------------------------------------------ 校验轮询自愈

def test_recheck_flag_is_reset_when_downloaders_unavailable(monkeypatch):
    """下载器不可用时必须复位运行标记，否则校验轮询永久停摆。"""
    plugin = _plugin()
    plugin._downloaders = ["QB"]
    plugin._recheck_torrents = {"QB": ["seed-hash"]}
    calls = []
    monkeypatch.setattr(IYUUAutoSeed, "service_infos",
                        property(lambda self: calls.append(1) or None))
    monkeypatch.setattr(IYUUAutoSeed, "auto_service_info", property(lambda self: None))

    plugin.check_recheck()
    assert plugin._is_recheck_running is False

    plugin.check_recheck()
    assert len(calls) == 2


def test_recheck_falls_back_when_auto_downloader_missing(monkeypatch):
    """主辅分离下载器不可用时回退检查全部下载器，校验队列不停摆。"""
    plugin = _plugin()
    plugin._auto_downloader = "QB2"
    plugin._recheck_torrents = {"QB2": ["seed-hash"]}
    fallback = SimpleNamespace(name="QB", type="qbittorrent", instance=Mock())
    checked = []
    monkeypatch.setattr(IYUUAutoSeed, "auto_service_info", property(lambda self: None))
    monkeypatch.setattr(IYUUAutoSeed, "service_infos",
                        property(lambda self: {"QB": fallback}))
    monkeypatch.setattr(plugin, "check_recheck_service", lambda service: checked.append(service.name))

    plugin.check_recheck()

    assert checked == ["QB"]
    assert plugin._is_recheck_running is False


# ------------------------------------------------------------------- 配置与站点

def test_invalid_size_config_does_not_break_init(monkeypatch):
    """体积配置填了非数字时按不限制处理，插件仍可初始化。"""
    plugin = _plugin()
    plugin.get_config = lambda plugin_id=None: None
    plugin.update_config = lambda config: None
    monkeypatch.setattr(iyuuautoseed, "SiteOper",
                        lambda: SimpleNamespace(list_order_by_pri=lambda: []))

    plugin.init_plugin({"enabled": False, "size": "20G", "sites": []})

    assert plugin._size == 0


def test_site_deleted_accepts_string_site_id():
    """自定义站点 ID 是非数字字符串时，取消勾选不应抛异常。"""
    plugin = _plugin()
    plugin._sites = ["10001", 6]
    plugin.get_config = lambda plugin_id=None: {"sites": ["10001", 6]}
    saved = {}
    plugin.update_config = lambda config: saved.update(config)

    plugin.site_deleted(SimpleNamespace(event_data={"site_id": "10001"}))

    assert plugin._sites == [6]
    assert saved["sites"] == [6]


# ---------------------------------------------------------- 取种失败的缓存分类

CLASSIFY = "_IYUUAutoSeed__is_permanent_seed_error"


@pytest.mark.parametrize("error_msg,permanent", [
    ("下载种子出错，状态码：404", True),
    ("下载种子出错，状态码：410", True),
    ("下载种子出错，状态码：403", False),
    ("下载种子出错，状态码：500", False),
    ("下载种子出错，状态码：502", False),
    ("下载种子出错，状态码：504", False),
    ("下载种子出错，状态码:403", False),
    ("站点限流：Request frequency limit, please try in 5 seconds.", False),
    ("触发站点流控，请稍后重试", False),
    ("无法打开链接", False),
    ("未下载到种子数据", False),
    ("种子数据有误，请确认链接是否正确", False),
    ("种子下载重定向出现环路", False),
    ("磁力链接", True),
    ("获取到磁力链接", True),
    (None, False),
    ("", False),
])
def test_permanent_classification(error_msg, permanent):
    """只有确认种子不存在或磁力不可辅种才永久拉黑，其余按暂态处理。"""
    assert getattr(_plugin(), CLASSIFY)(error_msg) is permanent


@pytest.mark.parametrize("error_msg", [
    "下载种子出错，状态码：403",
    "下载种子出错，状态码：502",
    "站点限流：Request frequency limit, please try in 5 seconds.",
    "种子数据有误，请确认链接是否正确，如为PT站点则需手工在站点下载一次种子",
])
def test_transient_failure_goes_to_clearable_cache(reseed, error_msg):
    """暂态失败不得进永久缓存，只记入可清除缓存。"""
    reseed.torrent.download_torrent.return_value = (None, None, "", [], error_msg)

    assert getattr(reseed.plugin, DOWNLOAD_TORRENT)(
        reseed.seed, reseed.service, "/data", "tv"
    ) is False
    assert reseed.plugin._error_caches == [reseed.seed["info_hash"]]
    assert reseed.plugin._permanent_error_caches == []


def test_gone_seed_goes_to_permanent_cache(reseed):
    """站点明确返回种子不存在时才进永久缓存。"""
    reseed.torrent.download_torrent.return_value = (
        None, None, "", [], "下载种子出错，状态码：404"
    )

    getattr(reseed.plugin, DOWNLOAD_TORRENT)(reseed.seed, reseed.service, "/data", "tv")

    assert reseed.plugin._permanent_error_caches == [reseed.seed["info_hash"]]
    assert reseed.plugin._error_caches == []


@pytest.mark.parametrize("content,error_msg", [
    ("magnet:?xt=urn:btih:" + "a" * 40, "磁力链接"),
    ("magnet:?xt=urn:btih:" + "b" * 40, "获取到磁力链接"),
])
def test_magnet_is_not_submitted_to_downloader(reseed, content, error_msg):
    """宿主把磁力放在 content 位置返回时不得提交下载器，并按永久失败处理。"""
    reseed.torrent.download_torrent.return_value = (None, content, "", [], error_msg)

    assert getattr(reseed.plugin, DOWNLOAD_TORRENT)(
        reseed.seed, reseed.service, "/data", "tv"
    ) is False
    reseed.service.instance.add_torrent.assert_not_called()
    assert reseed.plugin._permanent_error_caches == [reseed.seed["info_hash"]]
    assert reseed.plugin._error_caches == []


def test_transient_cache_is_reset_for_next_round(reseed, monkeypatch):
    """上一轮的暂态失败不应固化成永久跳过，每轮开始时重清。"""
    plugin = reseed.plugin
    plugin._error_caches = ["last-round-hash"]
    plugin._notify = False
    reseed.service.instance.get_completed_torrents.return_value = []
    monkeypatch.setattr(plugin.iyuu_helper, "reset_sites", lambda: None)
    monkeypatch.setattr(plugin, "_IYUUAutoSeed__update_config", lambda: None)
    monkeypatch.setattr(type(plugin), "service_infos",
                        property(lambda self: {"QB": reseed.service}), raising=True)

    plugin.auto_seed()

    assert plugin._error_caches == []


def test_seed_url_is_not_logged(reseed, monkeypatch):
    """种子链接带 passkey，成功与失败日志都不得原样输出，但失败原因要留下。"""
    recorder = Mock()
    monkeypatch.setattr(iyuuautoseed, "logger", recorder)
    reseed.request.return_value.post_res.return_value.json.return_value = {
        "data": "https://download.example/torrent?passkey=SECRET-TOKEN"
    }
    # 成功路径：拿到可用种子内容
    reseed.torrent.download_torrent.return_value = (
        None, b"torrent", "folder", ["file.mkv"], ""
    )
    assert getattr(reseed.plugin, DOWNLOAD_TORRENT)(
        reseed.seed, reseed.service, "/data", "tv"
    ) is True
    # 失败路径：403 属暂态
    reseed.torrent.download_torrent.return_value = (
        None, None, "", [], "下载种子出错，状态码：403"
    )
    assert getattr(reseed.plugin, DOWNLOAD_TORRENT)(
        reseed.seed, reseed.service, "/data", "tv"
    ) is False

    joined = "\n".join(str(call.args[0]) for call in recorder.method_calls if call.args)
    # 凭证链接确实进了流程，否则上面两条断言是空断言
    assert "SECRET-TOKEN" in reseed.torrent.download_torrent.call_args.kwargs["url"]
    assert "SECRET-TOKEN" not in joined
    assert "download.example" not in joined
    assert "状态码：403" in joined
