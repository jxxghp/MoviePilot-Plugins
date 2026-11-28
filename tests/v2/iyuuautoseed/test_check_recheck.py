"""IYUUAutoSeed V2 校验轮询的自动补发校验测试。

qBittorrent 5.3+ 的 WebAPI 移除了 ``skip_checking`` 参数，跳过校验添加的种子
不再被标记为已完成，而是停在 ``stoppedDL`` 且进度为 0；校验轮询需要主动补发
校验，种子才能进入「校验完成 -> 自动开始辅种」的流程。
"""

from types import SimpleNamespace

from app.plugins.iyuuautoseed import IYUUAutoSeed


def _torrent(hash_str, state, progress):
    """构造 qBittorrent 风格的种子信息字典。"""
    return {"hash": hash_str, "state": state, "progress": progress}


def _service(torrents):
    """构造最小下载器服务对象，记录 recheck/start 调用。"""
    instance = SimpleNamespace(
        get_torrents=lambda ids: (torrents, None),
        recheck_torrents_calls=[],
        start_torrents_calls=[],
    )
    instance.recheck_torrents = lambda ids: instance.recheck_torrents_calls.append(list(ids))
    instance.start_torrents = lambda ids: instance.start_torrents_calls.append(list(ids))
    return SimpleNamespace(name="oes", type="qbittorrent", instance=instance)


def _plugin_with_queue(downloader, hashes):
    plugin = IYUUAutoSeed()
    plugin._recheck_torrents = {downloader: list(hashes)}
    plugin._auto_rechecked = set()
    return plugin


def test_unchecked_stopped_torrent_triggers_recheck():
    """停止且未校验（0%）的种子应被自动补发一次校验。"""
    service = _service([_torrent("a" * 40, "stoppedDL", 0)])
    plugin = _plugin_with_queue("oes", ["a" * 40])
    plugin.check_recheck_service(service)
    assert service.instance.recheck_torrents_calls == [["a" * 40]]
    assert "a" * 40 in plugin._auto_rechecked
    # 校验尚未完成，种子仍留在待处理队列
    assert plugin._recheck_torrents["oes"] == ["a" * 40]


def test_recheck_not_repeated_for_same_torrent():
    """同一种子只补发一次校验，避免校验后仍为 0% 时无限循环。"""
    service = _service([_torrent("a" * 40, "stoppedDL", 0)])
    plugin = _plugin_with_queue("oes", ["a" * 40])
    plugin.check_recheck_service(service)
    plugin.check_recheck_service(service)
    assert service.instance.recheck_torrents_calls == [["a" * 40]]


def test_completed_torrent_is_started_without_extra_recheck():
    """校验完成（stoppedUP）的种子直接开始辅种，不再补发校验。"""
    service = _service([_torrent("b" * 40, "stoppedUP", 1)])
    plugin = _plugin_with_queue("oes", ["b" * 40])
    plugin.check_recheck_service(service)
    assert service.instance.start_torrents_calls == [["b" * 40]]
    assert service.instance.recheck_torrents_calls == []
    assert plugin._recheck_torrents["oes"] == []


def test_checking_or_partial_torrents_are_left_alone():
    """校验中或已下载部分的种子不补发校验，也不开始。"""
    service = _service([
        _torrent("c" * 40, "checkingDL", 0),
        _torrent("d" * 40, "stoppedDL", 0.4),
        _torrent("e" * 40, "downloading", 0.1),
    ])
    plugin = _plugin_with_queue("oes", ["c" * 40, "d" * 40, "e" * 40])
    plugin.check_recheck_service(service)
    assert service.instance.recheck_torrents_calls == []
    assert service.instance.start_torrents_calls == []


def test_seeding_torrent_is_dropped_from_queue():
    """已在做种的种子不补校验也不重新开始，直接出队。"""
    service = _service([_torrent("f" * 40, "uploading", 1)])
    plugin = _plugin_with_queue("oes", ["f" * 40])
    plugin.check_recheck_service(service)
    assert service.instance.recheck_torrents_calls == []
    assert service.instance.start_torrents_calls == []
    assert plugin._recheck_torrents["oes"] == []


def test_checking_up_torrent_stays_in_queue():
    """校验中的种子留在队列，等校验结束后再判定。"""
    service = _service([_torrent("g" * 40, "checkingUP", 1)])
    plugin = _plugin_with_queue("oes", ["g" * 40])
    plugin.check_recheck_service(service)
    assert plugin._recheck_torrents["oes"] == ["g" * 40]


def test_adopt_skips_seeding_torrent():
    """遗留认领不把正在做种的种子补入队列。"""
    service = _service([])
    plugin = _plugin_with_queue("oes", [])
    plugin._labelsafterseed = "辅种"
    torrent = {**_torrent("h" * 40, "stalledUP", 1), "tags": "辅种"}
    plugin._IYUUAutoSeed__adopt_recheck_torrents(service, torrent)
    assert plugin._recheck_torrents["oes"] == []


def test_adopt_keeps_unfinished_tagged_torrent():
    """未完成且带辅种标签的种子仍补入队列。"""
    service = _service([])
    plugin = _plugin_with_queue("oes", [])
    plugin._labelsafterseed = "辅种"
    torrent = {**_torrent("i" * 40, "pausedDL", 0.3), "tags": "辅种"}
    plugin._IYUUAutoSeed__adopt_recheck_torrents(service, torrent)
    assert plugin._recheck_torrents["oes"] == ["i" * 40]


def test_transmission_seeding_torrent_is_dropped_from_queue():
    """Transmission 做种中的种子同样出队。"""
    torrent = SimpleNamespace(hashString="j" * 40, labels=["辅种"], percent_done=1,
                              status=SimpleNamespace(stopped=False, checking=False))
    instance = SimpleNamespace(get_torrents=lambda ids: ([torrent], None),
                               recheck_torrents=lambda ids: None,
                               start_torrents=lambda ids: None)
    service = SimpleNamespace(name="tr", type="transmission", instance=instance)
    plugin = _plugin_with_queue("tr", ["j" * 40])
    plugin.check_recheck_service(service)
    assert plugin._recheck_torrents["tr"] == []


def test_adopt_skips_paused_completed_torrent():
    """已暂停的做种种子与 2.28 一致，不重复补登。"""
    service = _service([])
    plugin = _plugin_with_queue("oes", [])
    plugin._labelsafterseed = "辅种"
    torrent = {**_torrent("k" * 40, "pausedUP", 1), "tags": "辅种"}
    plugin._IYUUAutoSeed__adopt_recheck_torrents(service, torrent)
    assert plugin._recheck_torrents["oes"] == []


def test_transmission_checking_torrent_stays_in_queue():
    """Transmission 校验中即使进度为 1 也留在队列。"""
    torrent = SimpleNamespace(hashString="l" * 40, labels=[], percent_done=1,
                              status=SimpleNamespace(stopped=False, checking=True))
    instance = SimpleNamespace(get_torrents=lambda ids: ([torrent], None),
                               recheck_torrents=lambda ids: None,
                               start_torrents=lambda ids: None)
    service = SimpleNamespace(name="tr", type="transmission", instance=instance)
    plugin = _plugin_with_queue("tr", ["l" * 40])
    plugin.check_recheck_service(service)
    assert plugin._recheck_torrents["tr"] == ["l" * 40]
