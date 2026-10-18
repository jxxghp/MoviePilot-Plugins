"""MediaOverviewEnhancer 插件单测：纯函数与类级合同，不依赖宿主运行态实例。

覆盖：配置规整、文本清洗与指纹、标题归一化、事件字段读取、MV 文件名解析与
技术词过滤、插件类级元数据与索引版本一致性。真实 Emby 写入与 TMDB/AI 调用
属于运行时行为，这里只锁定可离线验证的逻辑合同。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.plugins.mediaoverviewenhancer import MediaOverviewEnhancer
from app.plugins.mediaoverviewenhancer.enhancer import (
    DEFAULT_CONFIG,
    _as_str_list,
    _base_series_title,
    _bounded_int,
    _normalize_title,
    clean_text,
    event_value,
    normalize_config,
    parse_mv_media,
    strip_mv_file_noise,
    strip_mv_file_noise_words,
    text_signature,
    visible_length,
)

PLUGIN_ID = "MediaOverviewEnhancer"
REPO_ROOT = Path(__file__).resolve().parents[3]


class TestNormalizeConfig:
    """配置规整：默认值、布尔归一、范围限幅与非法枚举回退。"""

    def test_defaults_keep_all_keys(self):
        """默认配置包含全部运行字段。"""
        config = normalize_config(None)
        assert set(DEFAULT_CONFIG) <= set(config)
        assert config["mv_libraries"] == ["mv"]
        assert config["mv_enabled"] is True
        assert config["concurrency"] == 2
        assert config["max_items_per_run"] == 200

    def test_bool_fields_coerced(self):
        """开关规整为布尔值。"""
        config = normalize_config({"enabled": 1, "mv_enabled": 0, "notify": "yes"})
        assert config["enabled"] is True
        assert config["mv_enabled"] is False
        assert config["notify"] is True

    def test_list_fields_split_and_dedupe(self):
        """列表配置支持拆分和去重。"""
        config = normalize_config({"mv_libraries": "MV, mv, 音乐\nMV", "servers": "emby, Emby"})
        assert config["mv_libraries"] == ["MV", "mv", "音乐"]
        assert config["servers"] == ["emby", "Emby"]

    def test_invalid_enum_falls_back(self):
        """非法模式回退默认值。"""
        config = normalize_config({"movie_mode": "whatever", "episode_mode": "nope"})
        assert config["movie_mode"] == "expand"
        assert config["episode_mode"] == "auto"

    def test_numeric_fields_clamped(self):
        """数值配置限制在允许范围内。"""
        config = normalize_config(
            {
                "concurrency": 99,
                "max_items_per_run": 99999,
                "post_transfer_delay": "abc",
                "mv_min_chars": -5,
                "mv_target_chars": 5,
            }
        )
        assert config["concurrency"] == 8
        assert config["max_items_per_run"] == 5000
        assert config["post_transfer_delay"] == 120
        assert config["mv_min_chars"] == 0
        assert config["mv_target_chars"] == 40

    def test_as_str_list_handles_separators(self):
        """列表解析兼容不同分隔符。"""
        assert _as_str_list("a, b，a") == ["a", "b"]
        assert _as_str_list(None) == []
        assert _as_str_list([" x ", "x", "y"]) == ["x", "y"]

    def test_bounded_int_defaults_and_clamps(self):
        """整数解析支持默认值与上下限。"""
        assert _bounded_int("12", 2, 1, 8) == 8
        assert _bounded_int(0, 2, 1, 8) == 1
        assert _bounded_int(None, 3, 0, 5) == 3


class TestTextHelpers:
    """简介文本清洗、可见字数与指纹：保证写入 Emby 的内容稳定可去重。"""

    def test_clean_text_strips_fence_prefix_and_blank_lines(self):
        """清理围栏、前缀和多余空行。"""
        raw = "```\n简介：你好   世界\r\n\r\n\r\n第二段```"
        assert clean_text(raw) == "你好 世界\n\n第二段"

    def test_clean_text_strips_wrapping_quotes(self):
        """清理正文外层引号。"""
        assert clean_text("“带引号”") == "带引号"

    def test_clean_text_empty_inputs(self):
        """空正文清理后保持为空。"""
        assert clean_text(None) == ""
        assert clean_text("   ") == ""

    def test_clean_text_respects_limit(self):
        """正文不超过长度上限。"""
        assert clean_text("abcdef", limit=3) == "abc"

    def test_visible_length_ignores_whitespace(self):
        """可见长度不计空白。"""
        assert visible_length(" a b\nc ") == 3
        assert visible_length(None) == 0

    def test_text_signature_ignores_whitespace(self):
        """正文指纹忽略空白差异。"""
        assert text_signature("a b") == text_signature("a\nb")
        assert text_signature("a b") != text_signature("a c")
        assert len(text_signature("a b")) == 40


class TestTitleHelpers:
    """标题归一化与季标记剥离：供 TMDB 标题搜索兜底使用。"""

    def test_normalize_title_keeps_alnum_and_cjk(self):
        """标题归一化保留中日韩文字及数字字母。"""
        assert _normalize_title("The Good Doctor 第2季") == "thegooddoctor第2季"

    def test_base_series_title_strips_season_marks(self):
        """匹配标题时剥离季标记。"""
        assert _base_series_title("The Good Doctor 第2季") == "The Good Doctor"
        assert _base_series_title("Show S02") == "Show"


class TestEventValue:
    """事件字段读取：字典/对象兼容，空值跳过并支持默认值。"""

    def test_dict_source_skips_empty(self):
        """事件字典跳过空字段。"""
        assert event_value({"a": "", "b": "v"}, "a", "b") == "v"

    def test_object_source(self):
        """事件读取兼容对象属性。"""
        class Payload:
            """最小事件载荷替身。"""

            name = "标题"

        assert event_value(Payload(), "name") == "标题"

    def test_default_and_zero_value(self):
        """事件读取保留零值且支持默认值。"""
        assert event_value(None, "a", default="D") == "D"
        assert event_value({"a": 0}, "a", default="D") == 0


class TestMvHelpers:
    """MV 素材解析与技术词过滤：决定 AI 提示词素材与最终文案质量。"""

    def test_parse_artist_song_and_noise(self):
        """MV 文件名提取艺人与曲名。"""
        parsed = parse_mv_media("(G)I-DLE - Klaxon 2160p WEB-DL HEVC")
        assert parsed["artist"] == "(G)I-DLE"
        assert parsed["song"] == "Klaxon"

    def test_parse_uses_origin_as_artist_fallback(self):
        """来源标签可作为艺人线索。"""
        parsed = parse_mv_media("[MBC] Song 2019 Live")
        assert parsed["artist"] == "MBC"
        assert parsed["year"] == "2019"
        assert "现场演出" in parsed["notes"]

    def test_parse_detects_version_notes(self):
        """MV 文件名保留版本线索。"""
        parsed = parse_mv_media("Artist - Song Dance Ver 2020")
        assert parsed["year"] == "2020"
        assert "舞蹈版" in parsed["notes"]
        assert "特别版本" in parsed["notes"]

    def test_parse_empty_input(self):
        """空文件名不产生素材。"""
        parsed = parse_mv_media("")
        assert parsed == {"artist": "", "song": "", "year": "", "notes": ""}

    def test_strip_mv_file_noise_words(self):
        """清理文件名技术词。"""
        assert strip_mv_file_noise_words("Klaxon 2160p WEB-DL HEVC 10bit") == "Klaxon"
        assert strip_mv_file_noise_words("official music video 1080p") == ""

    def test_strip_mv_file_noise_removes_technical_sentence(self):
        """正文过滤包含技术信息的句子。"""
        raw = (
            "这是一段完整的简介，描述了这首歌的曲风、编曲层次与整体氛围，"
            "也交代了它出自的专辑和发行年份。这支MV采用 2160p WEB-DL 高清画质，"
            "音轨为 AAC 立体声。画面里成员们的造型与编舞都很亮眼，剪辑节奏轻快，"
            "整体洋溢着夏日气息。"
        )
        cleaned = strip_mv_file_noise(raw)
        assert "2160p" not in cleaned
        assert "WEB-DL" not in cleaned
        assert "音轨" not in cleaned
        assert "剪辑节奏轻快" in cleaned

    def test_strip_mv_file_noise_keeps_original_when_too_short(self):
        """过滤后过短保留原文供后续判断。"""
        # 只剩文件信息说明模型主要在写技术信息，此时保留原文交给后续字数校验
        assert strip_mv_file_noise("2160p WEB-DL 蓝光画质。") == "2160p WEB-DL 蓝光画质。"


class TestPluginContract:
    """插件类级合同与市场索引一致性。"""

    def test_class_metadata(self):
        """插件元数据与联邦声明符合约定。"""
        assert MediaOverviewEnhancer.plugin_name == "影视简介增强"
        assert MediaOverviewEnhancer.plugin_author == "miguelito39721"
        assert MediaOverviewEnhancer.plugin_label == "元数据,媒体库,AI"
        assert MediaOverviewEnhancer.get_render_mode() == ("vue", "dist/assets")
        assert MediaOverviewEnhancer.get_command() == []

    def test_api_routes_declared(self):
        """联邦所需 API 均已声明。"""
        instance = object.__new__(MediaOverviewEnhancer)
        paths = {route["path"] for route in instance.get_api()}
        assert {"/status", "/config", "/servers", "/preview", "/run", "/cancel", "/clear"} <= paths

    def test_sidebar_nav_follows_switch(self):
        """侧栏入口跟随配置开关。"""
        enabled = object.__new__(MediaOverviewEnhancer)
        enabled._enabled = True
        enabled._config = {"show_sidebar_nav": True}
        nav = enabled.get_sidebar_nav()
        assert nav and nav[0]["nav_key"] == "main"

        enabled._config = {"show_sidebar_nav": False}
        assert enabled.get_sidebar_nav() == []

    def test_package_index_matches_plugin_version(self):
        """源码版本与市场发布索引一致。"""
        package = json.loads((REPO_ROOT / "package.v3.json").read_text(encoding="utf-8"))
        entry = package[PLUGIN_ID]
        assert entry["version"] == MediaOverviewEnhancer.plugin_version
        assert entry["release"] is True
        assert list(entry["history"])[0] == f"v{MediaOverviewEnhancer.plugin_version}"
