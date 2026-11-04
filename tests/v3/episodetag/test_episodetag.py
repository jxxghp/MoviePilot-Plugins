# -*- coding: utf-8 -*-
"""集数标签（EpisodeTag）v3 单测：标签构造/集数提取/标签识别与迁移/过滤。"""

from types import SimpleNamespace

from app.plugins.episodetag import EpisodeTag


class TestFormatEpisodes:
    """标签构造：前缀 / 合并阈值 / 分隔符组合。"""

    def test_default_each_episode_below_threshold(self, plugin):
        # 阈值 2：连续 ≤2 集各自独立标签
        assert plugin._format_episodes([1, 2]) == ["E01", "E02"]

    def test_merge_when_segment_exceeds_threshold(self, plugin):
        assert plugin._format_episodes([1, 2, 3]) == ["E01-03"]
        assert plugin._format_episodes([1, 2, 3, 4]) == ["E01-04"]

    def test_mixed_segments(self, plugin):
        # [1,2] 独立 + [5,6,7] 合并
        assert plugin._format_episodes([1, 2, 5, 6, 7]) == ["E01", "E02", "E05-07"]

    def test_threshold_one_never_merges(self, plugin):
        plugin._merge_threshold = 1
        assert plugin._format_episodes([1, 2, 3, 4]) == ["E01", "E02", "E03", "E04"]

    def test_custom_prefix_and_separator(self, plugin):
        plugin._tag_prefix = "EP"
        plugin._tag_separator = "~"
        assert plugin._format_episodes([1, 2, 3]) == ["EP01~03"]

    def test_empty_separator(self, plugin):
        plugin._tag_separator = ""
        assert plugin._format_episodes([1, 2, 3]) == ["E0103"]

    def test_dedup_and_sort(self, plugin):
        assert plugin._format_episodes([3, 1, 2, 1]) == ["E01-03"]


class TestParseEpisodesStr:

    def test_range_with_prefix(self):
        assert EpisodeTag._parse_episodes_str("E01-E12") == list(range(1, 13))

    def test_plain_range(self):
        assert EpisodeTag._parse_episodes_str("1-3") == [1, 2, 3]

    def test_list_with_separators(self):
        assert EpisodeTag._parse_episodes_str("E01,E03、E05/E07") == [1, 3, 5, 7]

    def test_season_only_skipped(self):
        # 纯季号（S01 / S01-S02）不产生集数
        assert EpisodeTag._parse_episodes_str("S01") is None
        assert EpisodeTag._parse_episodes_str("S01-S02") is None

    def test_empty(self):
        assert EpisodeTag._parse_episodes_str("") is None
        assert EpisodeTag._parse_episodes_str(None) is None


class TestEpisodesFromMeta:

    def test_episode_list(self):
        meta = SimpleNamespace(episode_list=[1, 2, None, 3])
        assert EpisodeTag._episodes_from_meta(meta) == [1, 2, 3]

    def test_begin_end_range(self):
        meta = SimpleNamespace(begin_episode=2, end_episode=4)
        assert EpisodeTag._episodes_from_meta(meta) == [2, 3, 4]

    def test_begin_only(self):
        meta = SimpleNamespace(begin_episode=5)
        assert EpisodeTag._episodes_from_meta(meta) == [5]

    def test_none(self):
        assert EpisodeTag._episodes_from_meta(None) is None


class TestEpisodesFromTorrentFiles:
    """种子文件列表兜底：仅视频文件、严格 SxxExx / 独立 Exx。"""

    @staticmethod
    def make_service(files):
        service = SimpleNamespace(
            name="qb", type="qbittorrent",
            instance=SimpleNamespace(get_files=lambda _hash: files))
        return service

    def test_sxxexx_priority(self, plugin):
        files = [SimpleNamespace(name="Show S01E02.mkv"), SimpleNamespace(name="Show S01E10.mp4")]
        assert plugin._episodes_from_torrent_files(self.make_service(files), "h") == [2, 10]

    def test_standalone_exx(self, plugin):
        files = [SimpleNamespace(name="Show - E03.mkv"), SimpleNamespace(name="Show - E04.mkv")]
        assert plugin._episodes_from_torrent_files(self.make_service(files), "h") == [3, 4]

    def test_non_video_ignored(self, plugin):
        files = [SimpleNamespace(name="Show S01E02.nfo"), SimpleNamespace(name="cover.jpg")]
        assert plugin._episodes_from_torrent_files(self.make_service(files), "h") is None

    def test_complete_season_title_not_misread(self, plugin):
        # 整季 Complete 标题（文件名无集数标记）不误判
        files = [SimpleNamespace(name="Show Season 1 Complete.mkv")]
        assert plugin._episodes_from_torrent_files(self.make_service(files), "h") is None


class TestIsPluginTag:
    """插件标签识别（含历史格式），用于迁移清理。"""

    def test_default_format(self, plugin):
        assert plugin._is_plugin_tag("E01")
        assert plugin._is_plugin_tag("E12")

    def test_merged_format(self, plugin):
        assert plugin._is_plugin_tag("E01-12")

    def test_legacy_v10_range(self, plugin):
        # v1.0 范围格式 E01-E12
        assert plugin._is_plugin_tag("E01-E12")

    def test_custom_prefix_after_config(self, plugin):
        assert not plugin._is_plugin_tag("EP01")
        plugin._known_prefixes = ["EP", "E"]
        assert plugin._is_plugin_tag("EP01")
        assert plugin._is_plugin_tag("EP01-12")

    def test_non_plugin_tags(self, plugin):
        assert not plugin._is_plugin_tag("电视剧")
        assert not plugin._is_plugin_tag("2026")
        assert not plugin._is_plugin_tag("")
        assert not plugin._is_plugin_tag("E01x")


class TestTagFilter:

    def test_parse(self):
        assert EpisodeTag._parse_tag_filter("电影, 动漫、TV") == {"电影", "动漫", "TV"}
        assert EpisodeTag._parse_tag_filter("") == set()
        assert EpisodeTag._parse_tag_filter(None) == set()

    def test_match_all_when_empty(self, plugin):
        assert plugin._match_tags(["任意"]) is True
        assert plugin._match_tags([]) is True

    def test_exclude_hit_skips(self, plugin):
        plugin._exclude_tags = {"手动管理"}
        assert plugin._match_tags(["电视剧", "手动管理"]) is False

    def test_include_miss_skips(self, plugin):
        plugin._include_tags = {"电视剧", "动漫"}
        assert plugin._match_tags(["电影"]) is False
        assert plugin._match_tags(["动漫"]) is True

    def test_include_empty_processes_all(self, plugin):
        # 仅配置排除时，未命中排除的全部处理
        plugin._exclude_tags = {"电影"}
        assert plugin._match_tags(["电视剧"]) is True


class TestTorrentFieldCompat:
    """qB（dict）与 Tr（对象）种子字段兼容。"""

    def test_qb_fields(self):
        torrent = {"hash": "abc", "tags": "a, b,,c", "name": "T1"}
        assert EpisodeTag._get_hash(torrent, "qbittorrent") == "abc"
        assert EpisodeTag._get_labels(torrent, "qbittorrent") == ["a", "b", "c"]
        assert EpisodeTag._get_torrent_name(torrent, "qbittorrent") == "T1"

    def test_tr_fields(self):
        torrent = SimpleNamespace(hashString="xyz", labels=[" a ", "b"], name="T2")
        assert EpisodeTag._get_hash(torrent, "transmission") == "xyz"
        assert EpisodeTag._get_labels(torrent, "transmission") == ["a", "b"]
        assert EpisodeTag._get_torrent_name(torrent, "transmission") == "T2"

    def test_broken_fields_return_safe_defaults(self):
        assert EpisodeTag._get_hash(None, "qbittorrent") is None
        assert EpisodeTag._get_labels(None, "qbittorrent") == []
        assert EpisodeTag._get_torrent_name(None, "qbittorrent") is None


class TestInitPlugin:

    def test_defaults_and_known_prefixes_persisted(self, plugin):
        """known_prefixes 存插件 data（不进 config），空前缀/非法阈值回退默认。"""
        plugin.init_plugin({
            "enabled": True, "onlyonce": False,
            "tag_prefix": "  ", "merge_threshold": "abc", "tag_separator": None,
        })
        assert plugin._tag_prefix == "E"
        assert plugin._merge_threshold == 2
        assert plugin._tag_separator == "-"
        plugin.save_data.assert_called_once_with("known_prefixes", ["E"])

    def test_format_change_triggers_refresh_and_config_update(self, plugin):
        """标签格式快照变化时置 last_format 并回写配置。"""
        plugin.init_plugin({
            "enabled": True, "tag_prefix": "EP", "merge_threshold": "3",
            "tag_separator": "~", "last_format": "E|2|-",
        })
        assert plugin._tag_prefix == "EP"
        assert plugin._merge_threshold == 3
        saved = plugin.update_config.call_args[0][0]
        assert saved["last_format"] == "EP|3|~"

    def test_legacy_config_known_prefixes_migrated_out(self, plugin):
        """旧版本把 known_prefixes 存 config：迁移合并进 data 并从 config 移除。"""
        plugin.init_plugin({
            "enabled": True, "known_prefixes": ["X"],
        })
        plugin.save_data.assert_called_once_with("known_prefixes", ["E", "X"])
        saved = plugin.update_config.call_args[0][0]
        assert "known_prefixes" not in saved

    def test_onlyonce_reset(self, plugin):
        plugin.init_plugin({"enabled": True, "onlyonce": True})
        assert plugin._onlyonce is False
        assert plugin.update_config.call_args[0][0]["onlyonce"] is False


class TestMeta:

    def test_plugin_meta(self):
        assert EpisodeTag.plugin_version == "3.0.0"
        assert EpisodeTag.plugin_author == "Guoyin-Wen"
        # get_form 第一元素必须是 list（V3 契约：裸 dict 会导致配置页空白）
        instance = object.__new__(EpisodeTag)
        form, defaults = instance.get_form()
        assert isinstance(form, list) and form
        assert isinstance(defaults, dict)
