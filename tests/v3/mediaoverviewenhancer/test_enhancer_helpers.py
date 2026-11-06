"""配置规整、占位文本判定与文风指令的单元测试。"""

from __future__ import annotations

from app.plugins.mediaoverviewenhancer.enhancer import (
    OverviewEnhancer,
    is_placeholder_episode_title,
    is_placeholder_overview,
    normalize_config,
)


def test_normalize_config_defaults_new_features() -> None:
    """新配置项应有稳定默认值并做区间钳制。"""
    config = normalize_config(
        {
            "enabled": True,
            "quality_ai_flavor_min_score": 999,
            "quality_similarity_threshold": 5,
            "episode_title_max_chars": 1,
            "style_preset": "unknown",
            "episode_title_mode": "weird",
            "series_mode": "weird",
        }
    )
    assert config["quality_ai_flavor_min_score"] == 100
    assert config["quality_similarity_threshold"] == 1.0
    assert config["episode_title_max_chars"] == 4
    assert config["style_preset"] == "objective"
    assert config["episode_title_mode"] == "numeric_only"
    assert config["series_mode"] == "expand"
    assert config["avatar_only_missing"] is True
    assert config["quality_name_check"] is True
    assert config["adaptive_concurrency"] is True


def test_placeholder_overview() -> None:
    """占位简介应被识别，正常简介不受影响。"""
    assert is_placeholder_overview("")
    assert is_placeholder_overview("暂无简介")
    assert is_placeholder_overview("No overview available.")
    assert not is_placeholder_overview("一名警察在雨夜追踪失踪的妹妹。")


def test_placeholder_episode_title() -> None:
    """纯编号标题应被判为占位标题。"""
    assert is_placeholder_episode_title("第 3 集")
    assert is_placeholder_episode_title("Episode 12")
    assert is_placeholder_episode_title("7")
    assert is_placeholder_episode_title("")
    assert not is_placeholder_episode_title("雨夜的证词")


def test_style_directive(tmp_path) -> None:
    """文风模板与剧透开关应拼进提示词。"""
    engine = OverviewEnhancer(
        config={"style_preset": "review", "allow_spoiler": False},
        data_dir=tmp_path,
    )
    text = engine._style_directive()
    assert "观感" in text
    assert "不得剧透" in text
    engine.update_config({"style_preset": "objective", "allow_spoiler": True})
    assert "可以提及结局走向" in engine._style_directive()
    engine.stop()
