"""v1.12.0 简介质量补强测试：AI 套话开场清理、短简介扩写判定、扩写提示词约束。"""

from __future__ import annotations

from pathlib import Path

from app.plugins.mediaoverviewenhancer.enhancer import (
    EPISODE_EXPAND_SYSTEM,
    EPISODE_SYSTEM,
    EPISODE_TEMPLATE_OPENING_PATTERN,
    OverviewEnhancer,
    strip_template_opening,
    visible_length,
)

# 真实线上文本：AI 生成的「编号/自我指涉」套话开场
EPISODE_TEXT_SAMPLES = [
    "第12集中，刘铮亮在家乡的处境迎来新的考验。此前临时集结的伙伴们各怀心思，配合上频频出现状况。",
    "本集中，刘铮亮继续在小城诊所里应对接连而来的病患与琐事，他与身边那群看似不靠谱的伙伴在配合中磨合渐深。",
    "这一集中，老段坚持只输液不检查，性格执拗没人能劝动，刘铮亮凭查体和化验判断她可能是输尿管结石。",
    "作为第一季推进至后半程的一集，本集延续刘铮亮在家乡重新起步的线索，聚焦他与那群伙伴在具体事务上的磨合与协作。",
]


class _FakeLlm:
    """只回答可用性判断，避免测试真的调用大模型。"""

    def __init__(self, available: bool = True) -> None:
        self._available = available

    def available(self) -> bool:
        return self._available


def _engine(tmp_path: Path, llm_available: bool = True) -> OverviewEnhancer:
    engine = OverviewEnhancer(config={"enabled": True, "episode_min_chars": 80}, data_dir=tmp_path)
    engine._llm = _FakeLlm(llm_available)  # type: ignore[assignment]
    return engine


def test_strip_template_opening_removes_numbered_leading_phrase() -> None:
    """「第12集中，」「本集中，」这类开场被剥离，正文保留。"""
    for text in EPISODE_TEXT_SAMPLES:
        stripped = strip_template_opening(text)
        assert stripped, "不应把简介削空"
        assert not EPISODE_TEMPLATE_OPENING_PATTERN.match(stripped), f"仍残留套话：{stripped}"
        assert visible_length(stripped) < visible_length(text)


def test_strip_template_opening_keeps_plain_text() -> None:
    """无套话的正文原样返回。"""
    text = "刘铮亮接诊了一位名叫邵楠的患者，她因腹痛前来就医。"
    assert strip_template_opening(text) == text


def test_strip_template_opening_removes_stacked_prefixes() -> None:
    """「作为第一季…的一集，本集延续…」这类叠层套话要剥到正文为止。"""
    text = "作为第一季推进至后半程的一集，本集延续刘铮亮在家乡重新起步的线索，聚焦他与伙伴们的磨合。"
    stripped = strip_template_opening(text)
    assert stripped.startswith("刘铮亮在家乡重新起步")
    assert not EPISODE_TEMPLATE_OPENING_PATTERN.match(stripped)


def test_strip_template_opening_never_empties_short_text() -> None:
    """去掉套话后几乎没有内容时回退原文，避免整段简介被削没。"""
    text = "第3集中，他出发了。"
    assert strip_template_opening(text) == text


def test_expand_prompts_forbid_template_openings() -> None:
    """两个分集提示词都带有禁止编号/自我指涉开场的要求。"""
    assert "套话" in EPISODE_SYSTEM
    assert "套话" in EPISODE_EXPAND_SYSTEM
    assert "本集延续" in EPISODE_EXPAND_SYSTEM


def test_short_tmdb_overview_is_expanded(tmp_path: Path) -> None:
    """TMDB 中文简介 52 字（达到 20 字素材线但低于阈值）应进入扩写。"""
    engine = _engine(tmp_path)
    short = "傅庭芸在傅家遇到一个神秘的新来客。赵凌一面维持假身份，一面暗中推进自己的计划。"
    job = {"kind": "episode", "reason": "short"}
    assert engine._episode_short_and_expandable(job, short, 80) is True


def test_long_overview_without_rewrite_flag_is_kept(tmp_path: Path) -> None:
    """素材充足且未开启「已有简介也交给 AI 重写」时不扩写，避免浪费额度。"""
    engine = _engine(tmp_path)
    long_text = "沈嘉兰本与林锦岐订有婚约，不料祖父沈其翰被判谋逆之罪，" * 3
    job = {"kind": "episode", "reason": "missing"}
    assert engine._episode_short_and_expandable(job, long_text, 80) is False


def test_expand_skipped_when_llm_unavailable(tmp_path: Path) -> None:
    """大模型不可用时判定为不扩写，调用方会回退原文。"""
    engine = _engine(tmp_path, llm_available=False)
    job = {"kind": "episode", "reason": "short"}
    assert engine._episode_short_and_expandable(job, "短简介。", 80) is False
