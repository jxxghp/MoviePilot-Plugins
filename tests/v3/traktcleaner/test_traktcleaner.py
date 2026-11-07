# -*- coding: utf-8 -*-
"""Trakt 观看清理（TraktCleaner）v3 单测：标题归一化/季集格式化/匹配/清理判定 fail-safe/队列条目。"""

import re
import time
from unittest.mock import Mock

import pytest

from app.plugins.traktcleaner import TraktCleaner


def call(plugin, name, *args, **kwargs):
    """调用插件私有方法（name mangling）。"""
    return getattr(plugin, f"_TraktCleaner{name}")(*args, **kwargs)


class TestNormalizeTitle:

    def test_basic(self, plugin):
        assert call(plugin, "__normalize_title", "The.Last.of.Us") == "the last of us"

    def test_strips_year_and_tech_tags(self, plugin):
        out = call(plugin, "__normalize_title", "Westworld 2016 1080p BluRay x265")
        assert "westworld" in out
        assert "2016" not in out and "1080p" not in out and "bluary" not in out

    def test_brackets_removed(self, plugin):
        out = call(plugin, "__normalize_title", "Show [2024] (1080p)")
        assert "[" not in out and "(" not in out

    def test_empty(self, plugin):
        assert call(plugin, "__normalize_title", "") == ""


class TestMergeEpisodeRanges:

    def test_single(self):
        assert TraktCleaner._TraktCleaner__merge_episode_ranges([5]) == "E05"

    def test_consecutive_merged(self):
        assert TraktCleaner._TraktCleaner__merge_episode_ranges([1, 2, 3]) == "E01-03"

    def test_mixed(self):
        assert TraktCleaner._TraktCleaner__merge_episode_ranges([1, 2, 3, 5, 6, 10]) == "E01-03E05-06E10"

    def test_dedup_and_sort(self):
        assert TraktCleaner._TraktCleaner__merge_episode_ranges([3, 1, 2, 1]) == "E01-03"

    def test_empty(self):
        assert TraktCleaner._TraktCleaner__merge_episode_ranges([]) == ""


class TestFormatSeasonEpisodeInt:

    def test_no_season(self):
        assert TraktCleaner._TraktCleaner__format_season_episode_int(None, [1]) == ""

    def test_whole_season(self):
        assert TraktCleaner._TraktCleaner__format_season_episode_int(1, []) == "S01整季"

    def test_few_episodes_listed(self):
        assert TraktCleaner._TraktCleaner__format_season_episode_int(2, [3, 1]) == "S02E01E03"

    def test_many_episodes_ranged(self):
        assert TraktCleaner._TraktCleaner__format_season_episode_int(1, [1, 2, 3, 4]) == "S01E01-E04"


class _FakeMetaInfo:
    """轻量标题解析替身：只提供 __match_torrent 用到的字段。

    单测环境没有 lifespan 登记的系统配置服务，真实 MetaInfo 无法构造；
    匹配测试的目标是 __match_torrent 的名字/年份/子串匹配逻辑。
    """

    def __init__(self, title):
        m = re.match(r"(.*?)[.\s]+S\d{1,2}", title)
        name = m.group(1).replace(".", " ").strip() if m else title
        ym = re.search(r"(?:19|20)\d{2}", title)
        self.name = name
        self.cn_name = ""
        self.en_name = name
        self.year = ym.group(0) if ym else None


@pytest.fixture
def fake_meta(monkeypatch):
    import app.plugins.traktcleaner as mod
    monkeypatch.setattr(mod, "MetaInfo", _FakeMetaInfo)


class TestMatchTorrent:

    def test_exact_with_year(self, plugin, fake_meta):
        watched = {"the last of us|2023": {"type": "show", "title": "The Last of Us"}}
        matched = call(plugin, "__match_torrent",
                       "The.Last.of.Us.S01.2023.1080p", watched)
        assert matched and matched["title"] == "The Last of Us"

    def test_exact_without_year(self, plugin, fake_meta):
        watched = {"westworld": {"type": "show", "title": "Westworld"}}
        assert call(plugin, "__match_torrent", "Westworld.S01", watched) is not None

    def test_no_match(self, plugin, fake_meta):
        watched = {"westworld": {"type": "show", "title": "Westworld"}}
        assert call(plugin, "__match_torrent", "Breaking.Bad.S01", watched) is None

    def test_empty_title(self, plugin, fake_meta):
        assert call(plugin, "__match_torrent", "", {"a": {"type": "movie"}}) is None


class TestShouldCleanTorrent:
    """清理判定 fail-safe：信息不足一律跳过，避免误删。"""

    @staticmethod
    def patch_episodes(plugin, monkeypatch, eps, total=None, parsed=None):
        total = total if total is not None else len(eps)
        parsed = parsed if parsed is not None else total
        monkeypatch.setattr(
            type(plugin), "_TraktCleaner__get_torrent_episodes",
            lambda self, h, ds=None: (eps, total, parsed))

    def test_movie_cleaned_immediately(self, plugin):
        ok, reason = call(plugin, "__should_clean_torrent",
                          {"type": "movie", "title": "M"}, "hash")
        assert ok is True and "电影" in reason

    def test_show_without_seasons_skipped(self, plugin):
        ok, reason = call(plugin, "__should_clean_torrent",
                          {"type": "show", "watched_seasons": {}}, "hash")
        assert ok is False and "跳过" in reason

    def test_show_unparsable_episodes_skipped(self, plugin, monkeypatch):
        self.patch_episodes(plugin, monkeypatch, {})
        ok, reason = call(plugin, "__should_clean_torrent",
                          {"type": "show", "watched_seasons": {"1": [1, 2]}}, "hash")
        assert ok is False and "无法解析" in reason

    def test_incomplete_parse_skipped(self, plugin, monkeypatch):
        # 3 个视频文件只解析出 2 个 → 跳过避免误删未识别文件
        self.patch_episodes(plugin, monkeypatch, {1: [1, 2]}, total=3, parsed=2)
        ok, reason = call(plugin, "__should_clean_torrent",
                          {"type": "show", "watched_seasons": {"1": [1, 2]}}, "hash")
        assert ok is False and "解析不完整" in reason

    def test_all_watched_cleaned(self, plugin, monkeypatch):
        self.patch_episodes(plugin, monkeypatch, {1: [1, 2, 3]})
        ok, reason = call(plugin, "__should_clean_torrent",
                          {"type": "show", "watched_seasons": {"1": [1, 2, 3]}}, "hash")
        assert ok is True and "全部3集已看" in reason

    def test_partial_watched_skipped(self, plugin, monkeypatch):
        self.patch_episodes(plugin, monkeypatch, {1: [1, 2, 3]})
        ok, reason = call(plugin, "__should_clean_torrent",
                          {"type": "show", "watched_seasons": {"1": [1]}}, "hash")
        assert ok is False and "未看" in reason

    def test_season_missing_in_watched_skipped(self, plugin, monkeypatch):
        self.patch_episodes(plugin, monkeypatch, {2: [1]})
        ok, reason = call(plugin, "__should_clean_torrent",
                          {"type": "show", "watched_seasons": {"1": [1]}}, "hash")
        assert ok is False and "S02未观看" in reason

    def test_watched_eps_as_str_ints_compared(self, plugin, monkeypatch):
        # Trakt 数据集号可能是字符串数字
        self.patch_episodes(plugin, monkeypatch, {1: [1, 2]})
        ok, _ = call(plugin, "__should_clean_torrent",
                     {"type": "show", "watched_seasons": {"1": ["1", "2"]}}, "hash")
        assert ok is True


class TestBuildPendingItem:

    def test_structure_and_defaults(self, plugin):
        info = {"hash": "h1", "title": "T", "matched_title": "M",
                "matched_type": "show", "season": 1, "episodes": [1]}
        item = call(plugin, "__build_pending_item", info, first_seen=123.0)
        assert item["torrent_hash"] == "h1"
        assert item["first_seen"] == 123.0
        assert item["status"] == "pending"
        # torrent_info 缺失的字段回落 None（前端安全）
        assert item["matched_year"] is None


class TestInitPlugin:

    def test_defaults(self, plugin):
        plugin.init_plugin({
            "enabled": True, "delay_days": None,
        })
        assert plugin._enabled is True
        assert plugin._delay_days == 0
        assert plugin._notify is True
        assert plugin._dry_run is False

    def test_values(self, plugin):
        plugin.init_plugin({
            "enabled": True, "delay_days": "7", "dry_run": True,
            "delete_file": False, "exclude_tags": "保留",
        })
        assert plugin._delay_days == 7
        assert plugin._dry_run is True
        assert plugin._delete_file is False
        assert plugin._exclude_tags == "保留"

    def test_no_token_marks_error(self, plugin):
        plugin._access_token = None
        plugin.init_plugin({"enabled": True})
        assert plugin._token_error is True

    def test_onlyonce_reset_without_run(self, plugin, monkeypatch):
        # onlyonce 起后台线程：单测里替身掉线程避免真实执行清理
        started = []
        import threading
        monkeypatch.setattr(threading, "Thread",
                            lambda *a, **kw: started.append(kw.get("name")) or Mock(start=lambda: None))
        plugin.init_plugin({"enabled": True, "onlyonce": True,
                            "client_id": "", "client_secret": "", "access_token": ""})
        assert plugin._onlyonce is False
        assert started


class TestMeta:

    def test_plugin_meta(self):
        assert TraktCleaner.plugin_version == "3.0.0"
        assert TraktCleaner.plugin_author == "Guoyin-Wen"
        instance = object.__new__(TraktCleaner)
        for name in ("get_data", "save_data", "update_config", "post_message"):
            setattr(instance, name, Mock())
        instance.get_data.return_value = None
        form, defaults = instance.get_form()
        # V3 契约：form 顶层 list 且首元素是组件 dict
        assert isinstance(form, list) and form and isinstance(form[0], dict)
        assert isinstance(defaults, dict)
        # 插件 API 必须声明框架级 apikey 鉴权
        apis = instance.get_api()
        assert apis and all(a.get("auth") == "apikey" for a in apis)
        page = instance.get_page()
        assert page is None or isinstance(page, list)


class TestTimeSanity:
    """delay_days 语义回归：0=即时、N=等待 N 天。"""

    def test_first_seen_is_timestamp(self, plugin):
        before = time.time()
        item = call(plugin, "__build_pending_item", {"hash": "h"}, first_seen=before)
        assert item["first_seen"] == before
