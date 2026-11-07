"""混合下载器的上传预算、恢复和失败重试。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins import speedlimiter as module
from app.plugins.speedlimiter import SpeedLimiter


class Transmission:
    """保存原生十进制 KB/s 限速，记录每次修改。"""
    def __init__(self):
        self.session = SimpleNamespace(speed_limit_up=3000, speed_limit_up_enabled=True,
                                       speed_limit_down=123, speed_limit_down_enabled=False)
        self.writes = []

    def get_session(self):
        """读取会话，不把关闭的数值当成有效限速。"""
        return self.session

    def set_session(self, **kwargs):
        """应用传入字段，保留未涉及的下载设置。"""
        self.writes.append(kwargs)
        for key, value in kwargs.items():
            setattr(self.session, key, value)


def clients(monkeypatch):
    """装配两个使用不同速率单位的下载器。"""
    tr = Transmission()
    transfer = SimpleNamespace(upload_limit=512000, download_limit=0)
    services = {
        'TR': SimpleNamespace(type='transmission', instance=SimpleNamespace(trc=tr)),
        'QB': SimpleNamespace(type='qbittorrent', instance=SimpleNamespace(qbc=SimpleNamespace(transfer=transfer))),
    }
    monkeypatch.setattr(SpeedLimiter, 'service_infos', property(lambda self: services))
    p = SpeedLimiter()
    data = {}
    p.save_data = lambda key, value: data.update({key: value.copy()})
    p.get_data = lambda key: data.get(key)
    p.init_plugin(dict(enabled=True, downloader=['TR', 'QB'], bandwidth=45,
                       allocation_mode='priority', downloader_limits='TR=3000\nQB=500',
                       interval=5, notify=False))
    return p, tr, transfer, services, data


def apply(p, budget):
    """按字节预算运行实际写入路径。"""
    p._SpeedLimiter__set_limiter(limit_type='播放', upload_limit=budget / 1024, download_limit=0)


def test_priority_and_native_units_preserve_downloads(monkeypatch):
    """先满足TR，其余给qB；转换单位后仍不超总预算。"""
    p, tr, qb, _, _ = clients(monkeypatch)
    apply(p, 2_500_000)
    assert tr.session.speed_limit_up == 2489
    assert qb.upload_limit == 10240
    assert tr.session.speed_limit_up * 1000 + qb.upload_limit <= 2_500_000
    assert all('speed_limit_down' not in call for call in tr.writes)
    assert tr.session.speed_limit_down == 123
    assert not tr.session.speed_limit_down_enabled


def test_independent_ceilings_and_stop_restore(monkeypatch):
    """空闲预算不能放大上限；停用后恢复启用前设置。"""
    p, tr, qb, _, data = clients(monkeypatch)
    apply(p, 10_000_000)
    assert (tr.session.speed_limit_up, qb.upload_limit) == (3000, 512000)
    apply(p, 100_000)
    p.stop_service()
    assert (tr.session.speed_limit_up, qb.upload_limit) == (3000, 512000)
    assert data['original_limits'] == {}


def test_zero_budget_never_means_unlimited(monkeypatch):
    """超出链路能力时降到最小有效速率，不能写入0。"""
    p, tr, qb, _, _ = clients(monkeypatch)
    apply(p, 0)
    assert tr.session.speed_limit_up >= 1 and tr.session.speed_limit_up_enabled
    assert qb.upload_limit >= 1024


def test_weights_use_original_budget_for_every_downloader():
    """后面的下载器不能使用前一个已分配后的预算再次折半。"""
    result = SpeedLimiter.allocate_uploads(1_000_000, [2_000_000] * 2, [1, 1])
    assert result == [500_000, 500_000]
    assert sum(SpeedLimiter.allocate_uploads(1_000_000, [100_000, 2_000_000])) == 1_000_000


def test_failed_write_retries_and_does_not_block_other_client(monkeypatch):
    """一次RPC失败后，预算相同的下一轮仍需重试。"""
    p, tr, qb, _, _ = clients(monkeypatch)
    real_write = tr.set_session
    tr.set_session = Mock(side_effect=OSError())
    apply(p, 100_000)
    assert qb.upload_limit == 10240
    tr.set_session = real_write
    apply(p, 100_000)
    assert tr.session.speed_limit_up < 100


def test_restart_restores_persisted_baseline_before_reconfiguration(monkeypatch):
    """进程重启后不能把之前的临时低速当成原始上限。"""
    p, tr, qb, _, data = clients(monkeypatch)
    apply(p, 100_000)
    p2 = SpeedLimiter()
    p2.get_data = lambda key: data.get(key)
    p2.save_data = lambda key, value: data.update({key: value.copy()})
    p2.init_plugin(dict(enabled=False, downloader=['TR', 'QB']))
    assert tr.session.speed_limit_up == 3000
    assert qb.upload_limit == 512000


def test_stop_does_not_override_manual_change(monkeypatch):
    """用户手动修改过上传后，停用插件不覆盖手动值。"""
    p, _, qb, _, _ = clients(monkeypatch)
    apply(p, 100_000)
    qb.upload_limit = 123456
    p.stop_service()
    assert qb.upload_limit == 123456


def test_unavailable_downloader_does_not_release_more_budget(monkeypatch):
    """读失败时保留当前限速，不能把未知的那一份分给其它下载器。"""
    p, tr, qb, services, _ = clients(monkeypatch)
    apply(p, 100_000)
    previous = tr.session.speed_limit_up
    services.pop('QB')
    apply(p, 3_000_000)
    assert tr.session.speed_limit_up == previous


def test_recovery_is_gradual(monkeypatch):
    """停止后按步长恢复，不能直接跳回3000。"""
    p, tr, _, _, _ = clients(monkeypatch)
    apply(p, 100_000)
    p._recovering = True
    old = tr.session.speed_limit_up
    p._SpeedLimiter__set_limiter(limit_type='未播放', upload_limit=0, download_limit=0)
    assert old < tr.session.speed_limit_up <= old + 256


def test_emby_uses_transcoded_bitrate(monkeypatch):
    """输出8Mbps的转码不能按60Mbps原片预留。"""
    p, _, _, _, _ = clients(monkeypatch)
    sessions = [dict(RemoteEndPoint='8.8.8.8', PlayState=dict(IsPaused=False),
                     NowPlayingItem=dict(MediaType='Video', Bitrate=60_000_000),
                     TranscodingInfo=dict(Bitrate=8_000_000))]
    media = SimpleNamespace(type='emby', instance=SimpleNamespace(get_data=lambda url:
            SimpleNamespace(status_code=200, json=lambda: sessions)))
    monkeypatch.setattr(module, 'MediaServerHelper', lambda: SimpleNamespace(get_services=lambda: {'emby': media}))
    p._last_playing = module.time.monotonic()
    p._playback_started = p._last_playing - 20
    p._session_positions[('emby', '8.8.8.8', None)] = (p._last_playing, None)
    captured = []
    p._SpeedLimiter__set_limiter = lambda **kw: captured.append(kw)
    p.check_playing_sessions()
    assert captured[0]['upload_limit'] == pytest.approx((45_000_000 - 8_000_000 * 1.25) / 8192)


def test_media_failure_does_not_restore_upload(monkeypatch):
    """媒体服务器请求失败不能等同于停止播放。"""
    p, _, _, _, _ = clients(monkeypatch)
    media = SimpleNamespace(type='emby', instance=SimpleNamespace(get_data=lambda url: None))
    monkeypatch.setattr(module, 'MediaServerHelper', lambda: SimpleNamespace(get_services=lambda: {'emby': media}))
    p._SpeedLimiter__set_limiter = Mock()
    p.check_playing_sessions()
    p._SpeedLimiter__set_limiter.assert_not_called()


def test_unequal_weights_are_not_distorted_by_floor():
    """带宽充足时按原比例分配，不重复扣除保底额度。"""
    assert SpeedLimiter.allocate_uploads(1_000_000, [2_000_000] * 2, [1, 9]) == [100_000, 900_000]


@pytest.mark.parametrize('caps', [[1000, 2_000_000], [100_000, 200_000, 3_000_000]])
def test_capped_weighted_allocation_stays_within_budget(caps):
    """碰到某个下载器上限时只重新分配剩余预算。"""
    result = SpeedLimiter.allocate_uploads(1_000_000, caps)
    assert all(0 < value <= cap for value, cap in zip(result, caps))
    assert sum(result) <= 1_000_000.01


def test_startup_reserves_bandwidth_and_pause_holds(monkeypatch):
    """开播先保护缓存，暂停后不立即恢复。"""
    p, _, _, _, _ = clients(monkeypatch)
    sessions = [dict(RemoteEndPoint='8.8.8.8', PlayState=dict(IsPaused=False),
                     NowPlayingItem=dict(MediaType='Video', Bitrate=8_000_000))]
    media = SimpleNamespace(type='emby', instance=SimpleNamespace(get_data=lambda url:
            SimpleNamespace(status_code=200, json=lambda: sessions)))
    monkeypatch.setattr(module, 'MediaServerHelper', lambda: SimpleNamespace(get_services=lambda: {'emby': media}))
    p._SpeedLimiter__set_limiter = Mock()
    p.check_playing_sessions()
    assert p._SpeedLimiter__set_limiter.call_args.kwargs['upload_limit'] == 0
    p._SpeedLimiter__set_limiter.reset_mock()
    sessions[0]['PlayState']['IsPaused'] = True
    p.check_playing_sessions()
    p._SpeedLimiter__set_limiter.assert_not_called()


def test_unlimited_baseline_can_finish_recovery(monkeypatch):
    """原本不限速时，渐进恢复最后能退出限速状态。"""
    p, tr, qb, _, _ = clients(monkeypatch)
    p._caps = {}
    tr.session.speed_limit_up_enabled = False
    qb.upload_limit = 0
    apply(p, 5_000_000)
    p._recovering = True
    for _ in range(25):
        p._last_raise = 0
        p._SpeedLimiter__set_limiter(limit_type='未播放', upload_limit=0, download_limit=0)
    assert not tr.session.speed_limit_up_enabled
    assert qb.upload_limit == 0
    assert not p._recovering


def test_disabled_download_limit_is_not_restored_as_enabled(monkeypatch):
    """原始下载限速关闭但数值非零时，恢复后仍应关闭。"""
    p, tr, _, _, _ = clients(monkeypatch)
    p._SpeedLimiter__set_limiter(limit_type='播放', upload_limit=100, download_limit=100)
    assert tr.session.speed_limit_down_enabled
    p.stop_service()
    assert not tr.session.speed_limit_down_enabled


@pytest.mark.parametrize('raw', ['QB=not-a-number', 'QB=nan', 'QB=-1', 'QB=0', 'unknown=100'])
def test_invalid_caps_disable_plugin(monkeypatch, raw):
    """配置写错时不能忽略上限后继续控制。"""
    p, _, _, _, _ = clients(monkeypatch)
    p.init_plugin(dict(enabled=True, downloader=['TR', 'QB'], downloader_limits=raw))
    assert not p.get_state()


def test_priority_ignores_legacy_ratio(monkeypatch):
    """切换优先顺序后，不使用旧比例设置。"""
    p, tr, qb, _, _ = clients(monkeypatch)
    p._allocation_ratio = '1:2:3'
    apply(p, 100_000)
    assert tr.session.speed_limit_up < 100
    assert qb.upload_limit == 10240


def test_legacy_idle_limit_remains_effective(monkeypatch):
    """没有独立上限时，仍允许用原有的未播放限速配置。"""
    p, tr, qb, _, _ = clients(monkeypatch)
    p._caps = {}
    p._SpeedLimiter__set_limiter(limit_type='未播放', upload_limit=200, download_limit=0)
    assert tr.session.speed_limit_up == 200
    assert qb.upload_limit == 200 * 1024


def test_seek_restarts_buffer_protection(monkeypatch):
    """拖动后重新让出带宽；正常播放进度不反复触发。"""
    p, _, _, _, _ = clients(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    session = dict(Id='session', PlayState=dict(PositionTicks=100_000_000), NowPlayingItem=dict(Id='item'))
    p._note_playback('emby', session)
    first = p._playback_started
    clock[0] += 5
    session['PlayState']['PositionTicks'] += 50_000_000
    p._note_playback('emby', session)
    assert p._playback_started == first
    clock[0] += 5
    session['PlayState']['PositionTicks'] += 600_000_000
    p._note_playback('emby', session)
    assert p._playback_started == clock[0]


def test_interval_jitter_does_not_halve_recovery_speed(monkeypatch):
    """调度抖动几毫秒不应把每轮恢复拖成每两轮一次。"""
    p, tr, _, _, _ = clients(monkeypatch)
    apply(p, 100_000)
    p._recovering = True
    now = module.time.monotonic()
    p._last_raise = now - 4.99
    old = tr.session.speed_limit_up
    p._SpeedLimiter__set_limiter(limit_type='未播放', upload_limit=0, download_limit=0)
    assert tr.session.speed_limit_up > old


def test_snapshot_failure_never_leaves_unrecoverable_limits(monkeypatch):
    """原始设置落盘失败时不能写入限速，也不能在下一轮跳过保存。"""
    p, tr, qb, _, data = clients(monkeypatch)
    save = p.save_data
    p.save_data = Mock(side_effect=OSError())
    apply(p, 100_000)
    assert p._original == {}
    assert tr.session.speed_limit_up == 3000 and qb.upload_limit == 512000
    p.save_data = save
    apply(p, 100_000)
    assert data['original_limits']['TR']['upload'] == 3000
    assert data['original_limits']['QB']['upload'] == 500
    p.stop_service()
    assert tr.session.speed_limit_up == 3000 and qb.upload_limit == 512000


def test_configurable_recovery_step_remains_gradual(monkeypatch):
    p, tr, _, _, _ = clients(monkeypatch)
    apply(p, 100_000)
    p._recovering = True
    p._recovery_step = 512
    p._last_raise = 0
    old = tr.session.speed_limit_up
    p._SpeedLimiter__set_limiter(limit_type='未播放', upload_limit=0, download_limit=0)
    assert tr.session.speed_limit_up == old + 512
