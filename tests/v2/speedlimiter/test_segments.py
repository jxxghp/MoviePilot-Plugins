from types import SimpleNamespace

import pytest

from app.plugins import speedlimiter as module
from app.plugins.speedlimiter import SpeedLimiter


def test_segment_budget_changes_with_scene_and_anticipates_peak():
    quiet = 1_000_000
    busy = 4_000_000
    buckets = [quiet] * 120
    assert SpeedLimiter.segment_rate(buckets, 0) == 8_000_000
    buckets[40:70] = [busy] * 30
    assert SpeedLimiter.segment_rate(buckets, 0) == 24_000_000
    assert SpeedLimiter.segment_rate(buckets, 30) == 32_000_000
    assert SpeedLimiter.segment_rate(buckets, 70) == 0  # 未探测完整，不能低估


def test_path_mapping_requires_prefix_boundary_and_prefers_longest():
    p = SpeedLimiter()
    p._media_paths = '/media=/data\n/media/movies=/movies'
    assert p._mapped_media_path('/media/movies/a.mkv') == '/movies/a.mkv'
    assert p._mapped_media_path('/media2/a.mkv') == '/media2/a.mkv'
    assert p._mapped_media_path('https://host/a.mkv') is None


def test_probe_accounts_for_all_muxed_tracks_and_rejects_short_tail(monkeypatch):
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        stdout='pts_time=30.1|size=100\npts_time=30.2|size=200\npts_time=N/A|size=9\npts_time=139.8|size=1\n'))
    buckets = SpeedLimiter._probe_segment('/file.mkv', 30, 500)
    assert buckets[0] == 300
    assert len(buckets) == 110
    assert SpeedLimiter.segment_rate(buckets, 51) == 0
    assert len(SpeedLimiter._probe_segment('/file.mkv', 30, 100)) == 120


def test_empty_probe_is_failure(monkeypatch):
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='pts_time=N/A|size=2'))
    with pytest.raises(ValueError):
        SpeedLimiter._probe_segment('/file.mkv', 0, 500)


def session(path):
    return {'NowPlayingItem': {'Path': str(path), 'Bitrate': 20_000_000, 'RunTimeTicks': 600 * 10_000_000},
            'PlayState': {'PositionTicks': 35 * 10_000_000, 'PlayMethod': 'DirectStream'}}


def test_cache_uses_scene_rate_without_double_applying_fallback_margin(tmp_path):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'x')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    p._overhead = 1.75
    st = path.stat()
    p._probe_cache[(str(path), st.st_size, st.st_mtime_ns, 30)] = [1_000_000] * 120
    s = session(path)
    assert p._playback_bitrate(s) * p._overhead == pytest.approx(9_200_000)
    s['TranscodingInfo'] = {'Bitrate': 3_000_000}
    assert p._playback_bitrate(s) == 3_000_000


def test_failed_probe_and_missing_file_fall_back(tmp_path):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'x')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    st = path.stat()
    p._probe_cache[(str(path), st.st_size, st.st_mtime_ns, 30)] = []
    assert p._playback_bitrate(session(path)) == 20_000_000
    assert p._playback_bitrate(session(tmp_path / 'missing')) == 20_000_000


def test_slow_probe_is_single_flight_and_does_not_block_polling(tmp_path, monkeypatch):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'x')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    jobs = []
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: jobs.append(kw['target'])))
    monkeypatch.setattr(p, '_probe_segment', lambda *a: [1_000_000] * 120)
    assert p._playback_bitrate(session(path)) == 20_000_000
    assert p._playback_bitrate(session(path)) == 20_000_000
    assert len(jobs) == 1
    jobs[0]()
    assert p._playback_bitrate(session(path)) < 20_000_000


def test_stopped_generation_discards_pending_result(tmp_path, monkeypatch):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'x')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    jobs = []
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: jobs.append(kw['target'])))
    monkeypatch.setattr(p, '_probe_segment', lambda *a: [1_000_000] * 120)
    p._playback_bitrate(session(path))
    p.stop_service()
    jobs[0]()
    assert p._probe_cache == {}


def test_scene_budget_preserves_priority_and_bandwidth():
    p = SpeedLimiter()
    p._bandwidth = 40_000_000
    p._headroom = 2_000_000
    p._overhead = 1.75
    for rate in (10_000_000, 24_000_000, 39_000_000):
        normalized = rate * 1.15 / p._overhead
        budget = p._SpeedLimiter__calc_limit(normalized) * 1024
        tr, qb = p.allocate_uploads(budget, [4_000_000, 512_000], priority=True)
        assert tr <= 4_000_000 and qb <= 512_000
        assert tr + qb <= max(budget, 2048)
        if rate == 10_000_000:
            assert tr > 3_000_000
            assert qb == 10240
        if rate == 39_000_000:
            assert tr == qb == 1024


def test_probe_timeout_is_cached_as_failure_without_limit_changes(tmp_path, monkeypatch):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'x')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    jobs = []
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: jobs.append(kw['target'])))
    def timeout(*args):
        raise module.subprocess.TimeoutExpired('ffprobe', 20)
    monkeypatch.setattr(p, '_probe_segment', timeout)
    assert p._playback_bitrate(session(path)) == 20_000_000
    jobs[0]()
    assert not p._probe_pending
    assert p._playback_bitrate(session(path)) == 20_000_000
    assert len(jobs) == 1
