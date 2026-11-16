"""简介质量纯函数与配置规整的单元测试。"""

from __future__ import annotations

import pytest

from app.plugins.mediaoverviewenhancer.quality import (
    ai_flavor_score,
    classify_failure,
    extract_person_names,
    jaccard_similarity,
    near_duplicate,
    stray_english_words,
    suspicious_names,
    summarize_failure_kinds,
)


NATURAL_TEXT = (
    "老刑警在退休前接手一桩旧案，线索指向二十年前的搭档。"
    "他一边应付上级的压力，一边独自走访当年的证人。"
    "第三集里，一封没有署名的信把调查引向城南的废弃仓库，"
    "而仓库管理员的态度让案情第一次出现裂缝。"
)

CLICHE_TEXT = (
    "随着剧情的推进，在这个充满张力的故事中，人物命运交织在一起。"
    "不禁令人感叹，仿佛命运的齿轮悄然转动，深深地打动了观众。"
    "最终，他们能否守护彼此的羁绊，让我们拭目以待。"
)


def test_ai_flavor_prefers_natural_text() -> None:
    """自然叙述的分数应明显高于套话堆砌的文案。"""
    natural, _ = ai_flavor_score(NATURAL_TEXT)
    cliche, reasons = ai_flavor_score(CLICHE_TEXT)
    assert natural >= 70
    assert cliche < 60
    assert reasons


def test_ai_flavor_short_text_is_zero() -> None:
    """过短文本无法评估，直接返回 0 分。"""
    score, reasons = ai_flavor_score("很好看")
    assert score == 0
    assert reasons


def test_jaccard_and_near_duplicate() -> None:
    """近似改写的文本应被判为重复，主题不同的文本不应命中。"""
    left = "他独自走进雨夜，沿着铁轨寻找失踪的妹妹，直到天亮才停下脚步。"
    right = "他独自走进雨夜，沿着铁轨寻找失踪的妹妹，直到天亮才停住脚步。"
    other = "警方在港口查获一批走私货物，牵出跨境洗钱网络。"
    assert jaccard_similarity(left, right) > 0.8
    assert near_duplicate(left, right, 0.85)
    assert not near_duplicate(left, other, 0.85)


def test_extract_and_suspicious_names() -> None:
    """已知演职员不应告警，编造的人名应被识别。"""
    text = "该片由张三饰演父亲，John Smith 饰演警探，李四饰演邻居。"
    names = extract_person_names(text)
    assert "张三" in names
    assert "John Smith" in names
    suspects = suspicious_names(text, ["张三", "李四"])
    assert suspects == ["John Smith"]


def test_suspicious_names_without_known_list() -> None:
    """没有演职员名单时不做幻觉判定，避免误伤。"""
    assert suspicious_names("由张三饰演父亲。", []) == []


def test_suspicious_names_ignores_plain_phrases() -> None:
    """普通短语不能被当成编造人名（回归「路西法 S5E4 围中各自」误判）。"""
    text = (
        "时间是1946年，世界唯有黑白两色。路西法成了黑色侦探故事的明星要角，"
        "熟悉的人物也各自诠释起新的角色。"
    )
    assert extract_person_names(text) == []
    assert suspicious_names(text, ["汤姆·埃利斯", "劳伦·日尔曼"]) == []


def test_suspicious_names_ignores_phrase_after_you() -> None:
    """「由围中各自，…」这类没有饰演语境的片段不应被截成人名。"""
    text = "故事由围中各自，剧情在雨夜不断推进。"
    assert extract_person_names(text) == []
    assert suspicious_names(text, ["汤姆·埃利斯"]) == []


def test_suspicious_names_accepts_source_text() -> None:
    """素材原文里出现过的名字不算 AI 编造。"""
    text = "该片由王五饰演警探。"
    source = "王五 饰演 警探，张三 饰演 父亲。"
    assert suspicious_names(text, ["张三"], source_text=source) == []


def test_suspicious_names_tolerates_translation_variants() -> None:
    """演职员表写全名、简介写简称时不应误判。"""
    text = "该片由张三饰演父亲，欧阳锋饰演警探。"
    assert suspicious_names(text, ["张三丰", "欧阳锋"]) == []


def test_extract_person_names_skips_places() -> None:
    """没有饰演上下文的地名不应被当成演员名。"""
    assert extract_person_names("故事发生在 New York，警方随后封锁了街区。") == []


def test_stray_english_words() -> None:
    """中文简介混入英文副词应被识别，专有名词不应误判。"""
    assert stray_english_words("幻视则 increasingly 难以容忍奥创的操控意图。") == [
        "increasingly"
    ]
    assert stray_english_words("该片由 John Smith 饰演，使用 IMAX 摄影机拍摄。") == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("大量模型不可用", "llm_unavailable"),
        ("LLM 返回空内容（可能触发限流或内容被截断）", "llm_rate_limit"),
        ("简介中文占比过低（12%），疑似未翻译", "quality_gate"),
        ("AI 味过重（42 分：套话开场）", "quality_gate"),
        ("TMDB 无该集简介", "material_missing"),
        ("HTTP 400: bad request", "emby_write"),
        ("NFO 写入失败", "nfo_write"),
        ("某种未归类错误", "unknown"),
    ],
)
def test_classify_failure(message: str, expected: str) -> None:
    """失败文案应被归入预期的类别。"""
    assert classify_failure(message) == expected


def test_summarize_failure_kinds() -> None:
    """失败清单按类别聚合并按数量排序。"""
    rows = [
        {"message": "TMDB 无该集简介"},
        {"message": "TMDB 无该集简介"},
        {"message": "HTTP 500"},
        {"message": "", "error_kind": "llm_error"},
    ]
    summary = summarize_failure_kinds(rows)
    assert summary["material_missing"] == 2
    assert summary["emby_write"] == 1
    assert summary["llm_error"] == 1
    assert list(summary)[0] == "material_missing"
