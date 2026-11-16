"""观影日历数据语义与缓存回退测试，使用宿主的生产插件命名空间。"""

import copy
import threading
from datetime import datetime, timezone
import pytest
from app.plugins.simplemoviecalendar import calendar


def sample():
    """构造包含多版本发行记录的固定日历。"""
    return {
        "schema_version": 1,
        "generated_at": "2026-11-01T00:00:00+00:00",
        "movies": [
            {
                "id": "a",
                "title_zh": "多版本",
                "year": 2026,
                "poster_url": "posters/a.webp",
                "imdb_id": "tt12345",
                "douban_id": "123",
                "douban_rating": None,
                "douban_rating_state": "unrated",
            },
            {"id": "b", "title_zh": "今日电影", "pinned": True},
            {"id": "c", "title_original": "Past", "imdb_rating": 7.2},
        ],
        "releases": [
            {
                "id": "a1",
                "movie_id": "a",
                "date": "2026-10-20",
                "kind": "digital",
                "edition": "Digital HD",
            },
            {
                "id": "a2",
                "movie_id": "a",
                "date": "2026-11-17",
                "kind": "physical",
                "edition": "4K UHD",
            },
            {
                "id": "b1",
                "movie_id": "b",
                "date": "2026-11-01",
                "kind": "streaming",
                "platform": "腾讯视频\n优酷",
                "time": "10:00",
                "timezone": "Asia/Shanghai",
            },
            {"id": "c1", "movie_id": "c", "date": "2026-10-31", "kind": "digital"},
        ],
    }


class TestCalendar:
    """验证日期、发行记录和媒体身份的业务约束。"""

    def test_rating_count_copy_handles_sparse_and_abbreviated_source_data(self):
        """验证rating count copy handles sparse and abbreviated source data的日历契约。"""
        assert calendar.rating_rows(
            {"douban_id": "123", "douban_rating_state": "unknown", "imdb_rating": 7}
        ) == [("douban", "—", ""), ("imdb", "7.0", "（人数暂缺）")]
        assert calendar.rating_rows(
            {
                "douban_id": "123",
                "douban_rating": 8,
                "douban_votes": 0,
                "imdb_id": "tt12345",
                "imdb_votes": "1.2m",
            }
        ) == [("douban", "8.0", "（0条评价）"), ("imdb", "未开分", "（1.2M评价）")]

    def test_beijing_midnight_changes_date_without_relying_on_export_today(self):
        """验证beijing midnight changes date without relying on export today的日历契约。"""
        assert (
            calendar.beijing_today(datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc))
            == "2026-11-02"
        )

    def test_multiversion_movie_counts_once_and_keeps_all_release_rows(self):
        """验证multiversion movie counts once and keeps all release rows的日历契约。"""
        result = calendar.records(sample(), "2026-11-01")
        assert [r["movie"]["id"] for r in result] == ["b", "a"]
        assert result[1]["primary"]["date"] == "2026-11-17"
        assert len(result[1]["releases"]) == 2

    def test_filter_kind_selects_primary_before_grouping_without_losing_other_versions(
        self,
    ):
        """验证filter kind selects primary before grouping without losing other versions的日历契约。"""
        result = calendar.records(
            sample(), "2026-11-01", group="recent", kind="digital"
        )
        assert [r["movie"]["id"] for r in result] == ["c", "a"]
        assert result[1]["primary"]["date"] == "2026-10-20"
        assert len(result[1]["releases"]) == 2

    def test_invalid_partial_and_orphan_dates_are_not_invented(self):
        """验证invalid partial and orphan dates are not invented的日历契约。"""
        data = sample()
        data["releases"] += [
            {"id": "x", "movie_id": "a", "date": "2026-02-30"},
            {
                "id": "y",
                "movie_id": "a",
                "date": "2026-11-01",
                "date_precision": "month",
            },
            {"id": "z", "movie_id": "orphan", "date": "2026-11-01"},
        ]
        assert len(calendar.records(data, "2026-11-01")[1]["releases"]) == 2

    def test_search_is_case_insensitive_and_hidden_movie_is_excluded(self):
        """验证search is case insensitive and hidden movie is excluded的日历契约。"""
        data = sample()
        assert (
            calendar.records(data, "2026-11-01", group="recent", query="PAST")[0][
                "movie"
            ]["id"]
            == "c"
        )
        data["movies"][0]["hidden"] = True
        assert len(calendar.records(data, "2026-11-01")) == 1

    def test_payload_has_real_title_stable_identity_full_schedule_and_no_fabricated_rating(
        self,
    ):
        """验证payload has real title stable identity full schedule and no fabricated rating的日历契约。"""
        data = sample()
        record = calendar.records(data, "2026-11-01")[1]
        item = calendar.media_payload(record, data, "2026-11-01", stale=False)
        assert item["title"] == "多版本"
        assert (item["media_source"], item["media_id"]) == ("simplecalendar", "a")
        assert item["poster_path"] == "https://ys.chenhao.net/posters/a.webp"
        assert item["vote_average"] is None
        assert "豆瓣 未开分" in item["overview"]
        assert "2026-10-20" in item["overview"]
        assert "2026-11-17" in item["overview"]
        assert item["homepage"] == "https://ys.chenhao.net/#movie=a"
        assert "tmdb_id" not in item

    def test_time_preserves_timezone_and_stale_warning_is_visible(self):
        """验证time preserves timezone and stale warning is visible的日历契约。"""
        data = sample()
        item = calendar.media_payload(
            calendar.records(data, "2026-11-01")[0], data, "2026-11-01", stale=True
        )
        assert "北京时间 10:00" in item["overview"]
        assert "今日发行" in item["tagline"]
        assert "缓存" in item["overview"]
        assert "腾讯视频" in item["overview"]
        assert "优酷" in item["overview"]

    def test_asset_urls_disallow_script_credentials_and_traversal(self):
        """验证asset urls disallow script credentials and traversal的日历契约。"""
        for value in (
            "javascript:alert(1)",
            "../key.env",
            "https://a:b@example.org/x",
            "data:image/png,x",
        ):
            assert calendar.asset_url(value) is None
        assert (
            calendar.asset_url("//example.org/a.webp") == "https://example.org/a.webp"
        )

    def test_malformed_ipv6_image_is_discarded_and_cannot_break_media_rendering(self):
        """验证malformed ipv6 image is discarded and cannot break media rendering的日历契约。"""
        data = sample()
        data["movies"][0]["poster_url"] = "https://[broken"
        checked = calendar.validate_snapshot(data)
        item = calendar.media_payload(
            calendar.records(checked, "2026-11-01")[1], checked, "2026-11-01"
        )
        assert item["poster_path"] is None
        assert item["title"] == "多版本"

    def test_bad_top_level_is_rejected_before_cache_replacement(self):
        """验证bad top level is rejected before cache replacement的日历契约。"""
        for value in (
            {},
            {"schema_version": True, "movies": [], "releases": []},
            {**sample(), "schema_version": 9},
            {**sample(), "movies": [None]},
            {**sample(), "generated_at": "not-a-time"},
        ):
            with pytest.raises(ValueError):
                calendar.validate_snapshot(value)
        assert calendar.validate_snapshot(sample())["schema_version"] == 1


class TestCache:
    """验证缓存失败回退、持久化和并发刷新。"""

    def make_cache(self, fetch, saved=None, store=None):
        """构造使用可控时钟和隔离持久化的缓存。"""
        self.now = 1000.0
        return calendar.CalendarCache(
            loader=lambda: copy.deepcopy(saved),
            save=store or (lambda x: None),
            fetch=fetch,
            clock=lambda: self.now,
            interval=1800,
        )

    def test_failed_refresh_preserves_successful_data_and_restart_cache(self):
        """验证failed refresh preserves successful data and restart cache的日历契约。"""
        persisted = []
        values = iter([sample(), OSError("offline")])

        def fetch():
            """返回预设响应并记录请求，隔离真实网络。"""
            value = next(values)
            if isinstance(value, Exception):
                raise value
            return value

        cache = self.make_cache(fetch, store=persisted.append)
        assert cache.refresh()
        self.now += 1801
        assert not cache.refresh()
        view = cache.view()
        assert len(view["snapshot"]["movies"]) == 3
        assert view["stale"]
        restarted = self.make_cache(lambda: sample(), saved=persisted[-1])
        assert len(restarted.view()["snapshot"]["movies"]) == 3

    def test_invalid_response_keeps_old_cache_and_empty_first_load_reports_error(self):
        """验证invalid response keeps old cache and empty first load reports error的日历契约。"""
        cache = self.make_cache(lambda: {"schema_version": 100})
        assert not cache.refresh()
        assert cache.view()["snapshot"] is None
        assert cache.view()["error"]

    def test_malformed_optional_kind_cannot_overwrite_good_cache(self):
        """验证malformed optional kind cannot overwrite good cache的日历契约。"""
        malformed = sample()
        malformed["releases"][0]["kind"] = []
        values = iter([sample(), malformed])
        saved = []
        cache = self.make_cache(lambda: next(values), store=saved.append)
        assert cache.refresh()
        assert not cache.refresh(force=True)
        assert len(saved) == 1
        assert cache.view()["snapshot"]["releases"][0]["kind"] == "digital"

    def test_persistence_failure_does_not_discard_valid_network_data(self):
        """验证persistence failure does not discard valid network data的日历契约。"""

        def save(value):
            """模拟持久化失败，验证已取得的数据仍可展示。"""
            raise OSError("disk full")

        cache = self.make_cache(sample, store=save)
        assert cache.refresh()
        assert cache.view()["snapshot"] is not None
        assert cache.view()["persistence_error"]

    def test_throttles_repeated_failures_and_returns_defensive_snapshot(self):
        """验证throttles repeated failures and returns defensive snapshot的日历契约。"""
        calls = []

        def fetch():
            """返回预设响应并记录请求，隔离真实网络。"""
            calls.append(1)
            return sample()

        cache = self.make_cache(fetch)
        cache.refresh()
        cache.view()["snapshot"]["movies"].clear()
        cache.refresh()
        assert len(calls) == 1
        assert len(cache.view()["snapshot"]["movies"]) == 3

    def test_concurrent_refreshes_only_fetch_once(self):
        """验证concurrent refreshes only fetch once的日历契约。"""
        started, release = (threading.Event(), threading.Event())
        calls = []

        def fetch():
            """返回预设响应并记录请求，隔离真实网络。"""
            calls.append(1)
            started.set()
            release.wait(2)
            return sample()

        cache = self.make_cache(fetch)
        worker = threading.Thread(target=cache.refresh)
        worker.start()
        assert started.wait(1)
        assert not cache.refresh(force=True)
        release.set()
        worker.join(3)
        assert len(calls) == 1
        assert cache.view()["snapshot"] is not None
