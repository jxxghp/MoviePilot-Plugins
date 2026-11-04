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


def test_probe_accounts_for_all_tracks_and_normalizes_origin(monkeypatch):
    p = SpeedLimiter()
    def read(command, consume, cancel, deadline=None):
        if "format=start_time" in command:
            consume("5.0")
        else:
            for line in ["pts_time=35.1|size=100", "pts_time=35.2|size=200",
                         "pts_time=N/A|size=9", "pts_time=144.8|size=1"]:
                consume(line)
    monkeypatch.setattr(p, '_read_probe', read)
    buckets = p._probe_segment('/file.mkv', 30, 500)
    assert buckets[0] == 300
    assert len(buckets) == 110
    assert SpeedLimiter.segment_rate(buckets, 51) == 0
    assert len(p._probe_segment('/file.mkv', 30, 100)) == 120


def test_empty_probe_is_failure(monkeypatch):
    p = SpeedLimiter()
    def read(command, consume, cancel, deadline=None):
        consume("0" if "format=start_time" in command else "pts_time=N/A|size=2")
    monkeypatch.setattr(p, '_read_probe', read)
    with pytest.raises(ValueError):
        p._probe_segment('/file.mkv', 0, 500)


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
    p._probe_cache[(str(path), 30)] = [1_000_000] * 120
    p._probe_checked = {k: module.time.monotonic() for k in p._probe_cache}
    s = session(path)
    assert p._playback_bitrate(s) * p._overhead == pytest.approx(9_200_000)
    s['TranscodingInfo'] = {'Bitrate': 3_000_000}
    assert p._playback_bitrate(s) == 3_000_000


def test_failed_probe_and_missing_file_fall_back(tmp_path, monkeypatch):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'x')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    st = path.stat()
    p._probe_cache[(str(path), 30)] = []
    p._probe_checked = {k: module.time.monotonic() for k in p._probe_cache}
    assert p._playback_bitrate(session(path)) == 20_000_000
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
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


def test_adjacent_probe_keeps_valid_scene_budget_while_refreshing(tmp_path, monkeypatch):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'x')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    p._overhead = 1.75
    st = path.stat()
    p._probe_cache[(str(path), 0)] = [1_000_000] * 120
    jobs = []
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: jobs.append(kw['target'])))
    s = session(path)  # 35s, starts a new 30s probe
    expected = 8_000_000 * 1.15 / p._overhead
    assert p._playback_bitrate(s) == pytest.approx(expected)
    assert len(jobs) == 1
    assert p._playback_bitrate(s) == pytest.approx(expected)
    s['PlayState']['PositionTicks'] = 100 * 10_000_000
    assert p._playback_bitrate(s) == 20_000_000  # 旧区间不足以覆盖拖动后的需求


def test_file_metadata_is_never_read_on_polling_thread(tmp_path, monkeypatch):
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    jobs = []
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: jobs.append(kw['target'])))
    monkeypatch.setattr(module.os, 'stat', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('polling did IO')))
    assert p._playback_bitrate(session(tmp_path / 'slow.mkv')) == 20_000_000
    assert len(jobs) == 1


def test_read_probe_limits_output_and_cleans_child():
    import sys
    p = SpeedLimiter()
    command = [sys.executable, '-c', "import sys;sys.stdout.write(('x'*4095+'\\n')*5000)"]
    with pytest.raises(ValueError, match='16MiB'):
        p._read_probe(command, lambda line: None, p._probe_cancel)
    assert p._probe_process is None


def test_stop_kills_probe_without_waiting_for_timeout():
    import sys
    import threading
    import time
    p = SpeedLimiter()
    ready = threading.Event()
    failures = []
    def worker():
        try:
            p._read_probe([sys.executable, '-u', '-c', "import time;print('ready');time.sleep(60)"],
                          lambda line: ready.set(), p._probe_cancel)
        except (ValueError, module.subprocess.SubprocessError):
            failures.append(True)
    thread = threading.Thread(target=worker)
    thread.start()
    assert ready.wait(3)
    child = p._probe_process
    started = time.monotonic()
    p.stop_service()
    thread.join(3)
    assert not thread.is_alive()
    assert child.poll() is not None
    assert time.monotonic() - started < 3
    assert p._probe_process is None


def test_seek_with_incomplete_start_falls_back(monkeypatch):
    p = SpeedLimiter()
    def read(command, consume, cancel, deadline=None):
        consume('0' if 'format=start_time' in command else 'pts_time=40|size=1000')
    monkeypatch.setattr(p, '_read_probe', read)
    with pytest.raises(ValueError, match='起始'):
        p._probe_segment('/file.mkv', 30, 500)


def test_multiple_sessions_share_one_probe_then_get_separate_budgets(tmp_path, monkeypatch):
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    files = [tmp_path / 'a.mkv', tmp_path / 'b.mkv']
    for path in files:
        path.write_bytes(b'x')
    jobs = []
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: jobs.append(kw['target'])))
    monkeypatch.setattr(p, '_probe_segment', lambda *args: [1_000_000] * 120)
    p._playback_bitrate(session(files[0]))
    p._playback_bitrate(session(files[1]))
    assert len(jobs) == 1
    jobs[0]()
    p._playback_bitrate(session(files[1]))
    assert len(jobs) == 2
    jobs[1]()
    assert len(p._probe_cache) == 2


def test_probe_commands_share_one_deadline(monkeypatch):
    p = SpeedLimiter()
    deadlines = []
    def read(command, consume, cancel, deadline=None):
        deadlines.append(deadline)
        if 'format=start_time' in command:
            consume('0')
        else:
            consume('pts_time=30.1|size=100')
    monkeypatch.setattr(p, '_read_probe', read)
    p._probe_segment('/file.mkv', 30, 500)
    assert len(deadlines) == 2 and deadlines[0] == deadlines[1]


def test_replacing_file_discards_previous_segment_cache(tmp_path, monkeypatch):
    path = tmp_path / 'a.mkv'
    path.write_bytes(b'new')
    p = SpeedLimiter()
    p._segment_prediction = p._auto_limit = True
    p._probe_cache[(str(path), 0)] = [1_000_000] * 120
    p._probe_signatures[str(path)] = (1, 0)
    jobs = []
    monkeypatch.setattr(module.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: jobs.append(kw['target'])))
    monkeypatch.setattr(p, '_probe_segment', lambda *args: [2_000_000] * 120)
    p._playback_bitrate(session(path))
    jobs[0]()
    assert (str(path), 0) not in p._probe_cache
    assert p._probe_cache[(str(path), 30)][0] == 2_000_000
