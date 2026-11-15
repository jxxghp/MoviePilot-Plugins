"""Behavior tests for calendar semantics and durable cache failure recovery."""
import copy
import importlib.util
import sys
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[3] / 'plugins.v3' / 'simplemoviecalendar'
spec = importlib.util.spec_from_file_location('calendar_under_test', PLUGIN / 'calendar.py')
calendar = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = calendar
spec.loader.exec_module(calendar)


def sample():
    return {
        'schema_version': 1, 'generated_at': '2026-11-01T00:00:00+00:00',
        'movies': [
            {'id': 'a', 'title_zh': '多版本', 'year': 2026, 'poster_url': 'posters/a.webp',
             'imdb_id': 'tt12345', 'douban_id': '123', 'douban_rating': None,
             'douban_rating_state': 'unrated'},
            {'id': 'b', 'title_zh': '今日电影', 'pinned': True},
            {'id': 'c', 'title_original': 'Past', 'imdb_rating': 7.2},
        ],
        'releases': [
            {'id': 'a1', 'movie_id': 'a', 'date': '2026-10-20', 'kind': 'digital', 'edition': 'Digital HD'},
            {'id': 'a2', 'movie_id': 'a', 'date': '2026-11-17', 'kind': 'physical', 'edition': '4K UHD'},
            {'id': 'b1', 'movie_id': 'b', 'date': '2026-11-01', 'kind': 'streaming',
             'platform': '腾讯视频\n优酷', 'time': '10:00', 'timezone': 'Asia/Shanghai'},
            {'id': 'c1', 'movie_id': 'c', 'date': '2026-10-31', 'kind': 'digital'},
        ],
    }


class CalendarTests(unittest.TestCase):
    def test_rating_count_copy_handles_sparse_and_abbreviated_source_data(self):
        self.assertEqual(calendar.rating_rows({
            'douban_id': '123', 'douban_rating_state': 'unknown', 'imdb_rating': 7,
        }), [('douban', '—', ''), ('imdb', '7.0', '（人数暂缺）')])
        self.assertEqual(calendar.rating_rows({
            'douban_id': '123', 'douban_rating': 8, 'douban_votes': 0,
            'imdb_id': 'tt12345', 'imdb_votes': '1.2m',
        }), [('douban', '8.0', '（0条评价）'), ('imdb', '未开分', '（1.2M评价）')])

    def test_beijing_midnight_changes_date_without_relying_on_export_today(self):
        self.assertEqual(calendar.beijing_today(datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)), '2026-11-02')

    def test_multiversion_movie_counts_once_and_keeps_all_release_rows(self):
        result = calendar.records(sample(), '2026-11-01')
        self.assertEqual([r['movie']['id'] for r in result], ['b', 'a'])
        self.assertEqual(result[1]['primary']['date'], '2026-11-17')
        self.assertEqual(len(result[1]['releases']), 2)

    def test_filter_kind_selects_primary_before_grouping_without_losing_other_versions(self):
        result = calendar.records(sample(), '2026-11-01', group='recent', kind='digital')
        self.assertEqual([r['movie']['id'] for r in result], ['c', 'a'])
        self.assertEqual(result[1]['primary']['date'], '2026-10-20')
        self.assertEqual(len(result[1]['releases']), 2)

    def test_invalid_partial_and_orphan_dates_are_not_invented(self):
        data = sample()
        data['releases'] += [
            {'id': 'x', 'movie_id': 'a', 'date': '2026-02-30'},
            {'id': 'y', 'movie_id': 'a', 'date': '2026-11-01', 'date_precision': 'month'},
            {'id': 'z', 'movie_id': 'orphan', 'date': '2026-11-01'},
        ]
        self.assertEqual(len(calendar.records(data, '2026-11-01')[1]['releases']), 2)

    def test_search_is_case_insensitive_and_hidden_movie_is_excluded(self):
        data = sample()
        self.assertEqual(calendar.records(data, '2026-11-01', group='recent', query='PAST')[0]['movie']['id'], 'c')
        data['movies'][0]['hidden'] = True
        self.assertEqual(len(calendar.records(data, '2026-11-01')), 1)

    def test_payload_has_real_title_stable_identity_full_schedule_and_no_fabricated_rating(self):
        data = sample()
        record = calendar.records(data, '2026-11-01')[1]
        item = calendar.media_payload(record, data, '2026-11-01', stale=False)
        self.assertEqual(item['title'], '多版本')
        self.assertEqual((item['media_source'], item['media_id']), ('simplecalendar', 'a'))
        self.assertEqual(item['poster_path'], 'https://ys.chenhao.net/posters/a.webp')
        self.assertIsNone(item['vote_average'])
        self.assertIn('豆瓣 未开分', item['overview'])
        self.assertIn('2026-10-20', item['overview'])
        self.assertIn('2026-11-17', item['overview'])
        self.assertEqual(item['homepage'], 'https://ys.chenhao.net/#movie=a')
        self.assertNotIn('tmdb_id', item)

    def test_time_preserves_timezone_and_stale_warning_is_visible(self):
        data = sample()
        item = calendar.media_payload(calendar.records(data, '2026-11-01')[0], data, '2026-11-01', stale=True)
        self.assertIn('北京时间 10:00', item['overview'])
        self.assertIn('今日发行', item['tagline'])
        self.assertIn('缓存', item['overview'])
        self.assertIn('腾讯视频', item['overview'])
        self.assertIn('优酷', item['overview'])

    def test_asset_urls_disallow_script_credentials_and_traversal(self):
        for value in ('javascript:alert(1)', '../key.env', 'https://a:b@example.org/x', 'data:image/png,x'):
            self.assertIsNone(calendar.asset_url(value))
        self.assertEqual(calendar.asset_url('//example.org/a.webp'), 'https://example.org/a.webp')

    def test_malformed_ipv6_image_is_discarded_and_cannot_break_media_rendering(self):
        data = sample()
        data['movies'][0]['poster_url'] = 'https://[broken'
        checked = calendar.validate_snapshot(data)
        item = calendar.media_payload(calendar.records(checked, '2026-11-01')[1], checked, '2026-11-01')
        self.assertIsNone(item['poster_path'])
        self.assertEqual(item['title'], '多版本')

    def test_bad_top_level_is_rejected_before_cache_replacement(self):
        for value in ({}, {'schema_version': True, 'movies': [], 'releases': []},
                      {**sample(), 'schema_version': 9}, {**sample(), 'movies': [None]},
                      {**sample(), 'generated_at': 'not-a-time'}):
            with self.assertRaises(ValueError):
                calendar.validate_snapshot(value)
        self.assertEqual(calendar.validate_snapshot(sample())['schema_version'], 1)


class CacheTests(unittest.TestCase):
    def make_cache(self, fetch, saved=None, store=None):
        self.now = 1000.0
        return calendar.CalendarCache(
            loader=lambda: copy.deepcopy(saved), save=store or (lambda x: None), fetch=fetch,
            clock=lambda: self.now, interval=1800)

    def test_failed_refresh_preserves_successful_data_and_restart_cache(self):
        persisted = []
        values = iter([sample(), OSError('offline')])
        def fetch():
            value = next(values)
            if isinstance(value, Exception):
                raise value
            return value
        cache = self.make_cache(fetch, store=persisted.append)
        self.assertTrue(cache.refresh())
        self.now += 1801
        self.assertFalse(cache.refresh())
        view = cache.view()
        self.assertEqual(len(view['snapshot']['movies']), 3)
        self.assertTrue(view['stale'])
        restarted = self.make_cache(lambda: sample(), saved=persisted[-1])
        self.assertEqual(len(restarted.view()['snapshot']['movies']), 3)

    def test_invalid_response_keeps_old_cache_and_empty_first_load_reports_error(self):
        cache = self.make_cache(lambda: {'schema_version': 100})
        self.assertFalse(cache.refresh())
        self.assertIsNone(cache.view()['snapshot'])
        self.assertTrue(cache.view()['error'])

    def test_malformed_optional_kind_cannot_overwrite_good_cache(self):
        malformed = sample()
        malformed['releases'][0]['kind'] = []
        values = iter([sample(), malformed])
        saved = []
        cache = self.make_cache(lambda: next(values), store=saved.append)
        self.assertTrue(cache.refresh())
        self.assertFalse(cache.refresh(force=True))
        self.assertEqual(len(saved), 1)
        self.assertEqual(cache.view()['snapshot']['releases'][0]['kind'], 'digital')

    def test_persistence_failure_does_not_discard_valid_network_data(self):
        def save(value):
            raise OSError('disk full')
        cache = self.make_cache(sample, store=save)
        self.assertTrue(cache.refresh())
        self.assertIsNotNone(cache.view()['snapshot'])
        self.assertTrue(cache.view()['persistence_error'])

    def test_throttles_repeated_failures_and_returns_defensive_snapshot(self):
        calls = []
        def fetch():
            calls.append(1)
            return sample()
        cache = self.make_cache(fetch)
        cache.refresh()
        cache.view()['snapshot']['movies'].clear()
        cache.refresh()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(cache.view()['snapshot']['movies']), 3)

    def test_concurrent_refreshes_only_fetch_once(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def fetch():
            calls.append(1)
            started.set()
            release.wait(2)
            return sample()
        cache = self.make_cache(fetch)
        worker = threading.Thread(target=cache.refresh)
        worker.start()
        self.assertTrue(started.wait(1))
        self.assertFalse(cache.refresh(force=True))
        release.set()
        worker.join(3)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(cache.view()['snapshot'])


if __name__ == '__main__':
    unittest.main()
