"""简介质量分析纯函数：AI 味评分、跨集相似度、人名校验与失败分类。

本模块刻意不依赖 MoviePilot 运行时（不导入 app.*），既方便单元测试，
也方便在其它脚本里复用。
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

# 中文与常见全角标点
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")

# AI 常见的套话开场（出现在开头 16 字内才扣分）
_OPENING_CLICHES = (
    "本集",
    "本片中",
    "本片中",
    "随着",
    "在这个",
    "故事发生在",
    "讲述了",
    "影片讲述",
    "该片讲述",
    "这部剧",
    "作为一",
)

# AI 文案里高频出现的连接与抒情词，命中密度越高越像模板
_FLAVOR_WORDS = (
    "随着",
    "在这个",
    "与此同时",
    "不禁",
    "仿佛",
    "宛如",
    "令人",
    "无疑",
    "不仅",
    "更是",
    "然而",
    "最终",
    "逐渐",
    "悄然",
    "交织",
    "缓缓",
    "深深",
    "充满",
    "展现",
    "呈现",
    "见证",
    "命运",
    "抉择",
    "羁绊",
    "守护",
)

# 结尾总结句式
_CLOSING_CLICHES = (
    "总的来说",
    "总而言之",
    "可以说",
    "究竟会如何",
    "让我们拭目以待",
    "敬请期待",
    "能否",
)

# 拉丁人名：Two Word 形式的首字母大写组合
_LATIN_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")
# 中文人名提示：「由 X 饰演 / 演员 X / 主演 X」与「X 饰演 / X 扮演」两种语序。
# 名字后面必须紧跟「饰演/扮演」或标点，避免把「饰演警探」里的角色名当成演员。
_CJK_NAME_AFTER_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:饰演|扮演|主演)"
)
_CJK_NAME_BEFORE_RE = re.compile(
    r"(?:由|主演|演员|领衔主演)[:：\s]*"
    r"([\u4e00-\u9fff]{2,4}?)(?=饰演|扮演|主演|饰|，|。|、|；|,|;|\s|$)"
)
# 中文姓名里不会出现的动词/角色词，命中即丢弃，降低误判
_CJK_NAME_STOPWORDS = {
    "主演",
    "出演",
    "饰演",
    "扮演",
    "领衔",
    "联合",
    "特别",
    "友情",
    "导演",
    "编剧",
    "配音",
}

_LATIN_STOPWORDS = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "When",
    "While",
    "After",
    "Before",
    "With",
    "From",
    "Into",
    "Their",
    "There",
    "Here",
    "What",
    "Where",
    "Which",
    "Who",
    "Why",
    "How",
}


def normalize_name(name: Any) -> str:
    """把名称规整成用于比较的形式（全角转半角、去空格、小写）。"""
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    text = re.sub(r"[\s·•・.\-_]+", "", text)
    return text.casefold()


def _visible_len(text: str) -> int:
    """统计可见字符数（不含空白）。"""
    return len(re.sub(r"\s+", "", str(text or "")))


def ai_flavor_score(text: Any) -> Tuple[int, List[str]]:
    """评估简介的「AI 味」，返回 0~100 的分数（越高越自然）与命中原因。

    评分维度：套话开场、连接词密度、句长均匀度、重复片段、总结式结尾。
    该函数是确定性的，便于回归测试与阈值调优。
    """
    body = str(text or "").strip()
    length = _visible_len(body)
    if length < 20:
        return 0, ["文本过短，无法评估"]
    score = 100
    reasons: List[str] = []

    head = body[:16]
    if any(word in head for word in _OPENING_CLICHES):
        score -= 18
        reasons.append("套话开场")

    hits = 0
    for word in _FLAVOR_WORDS:
        hits += body.count(word)
    density = hits * 100.0 / max(1, length)
    if density >= 3.0:
        score -= min(30, int(round(density * 3)))
        reasons.append(f"连接词密度偏高（{density:.1f}/百字）")

    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(body) if part.strip()]
    if len(sentences) >= 3:
        lengths = [_visible_len(item) for item in sentences]
        mean = sum(lengths) / len(lengths)
        variance = sum((value - mean) ** 2 for value in lengths) / len(lengths)
        deviation = math.sqrt(variance)
        if mean and deviation / mean < 0.22:
            score -= 10
            reasons.append("句长过于均匀")
        if max(lengths) - min(lengths) <= 2:
            score -= 6
            reasons.append("句式缺乏起伏")

    grams = [body[index : index + 4] for index in range(0, max(0, length - 3))]
    if grams:
        unique = len(set(grams))
        repetition = 1 - unique / len(grams)
        if repetition > 0.12:
            score -= min(16, int(round(repetition * 60)))
            reasons.append(f"重复片段偏多（{repetition:.0%}）")

    tail = body[-24:]
    if any(word in tail for word in _CLOSING_CLICHES):
        score -= 8
        reasons.append("总结式结尾")

    return max(0, min(100, score)), reasons


def _shingles(text: str, size: int = 3) -> Set[str]:
    """把文本切成字符级 shingle 集合，用于相似度计算。"""
    body = re.sub(r"\s+", "", str(text or ""))
    if len(body) <= size:
        return {body} if body else set()
    return {body[index : index + size] for index in range(len(body) - size + 1)}


def jaccard_similarity(left: Any, right: Any, size: int = 3) -> float:
    """计算两段文本的字符 shingle Jaccard 相似度（0~1）。"""
    first = _shingles(str(left or ""), size)
    second = _shingles(str(right or ""), size)
    if not first or not second:
        return 0.0
    inter = len(first & second)
    union = len(first | second)
    return inter / union if union else 0.0


def text_similarity(left: Any, right: Any, size: int = 3) -> float:
    """计算两段文本的综合相似度（Jaccard 与序列匹配取较大值）。

    中文短文本里插入一两个字会让 3-gram Jaccard 掉到 0.8 以下，
    只用 Jaccard 会漏判「稍微改写就绕过重复检测」的情况，
    因此这里再叠加 `difflib` 的序列匹配率并取较大值。
    """
    import difflib

    first = re.sub(r"\s+", "", str(left or ""))
    second = re.sub(r"\s+", "", str(right or ""))
    if not first or not second:
        return 0.0
    ratio = difflib.SequenceMatcher(None, first, second).ratio()
    return max(jaccard_similarity(first, second, size), ratio)


def near_duplicate(left: Any, right: Any, threshold: float = 0.85) -> bool:
    """判断两段文本是否近似重复（默认阈值 0.85）。"""
    if threshold <= 0:
        return False
    return text_similarity(left, right) >= float(threshold)


def max_similarity(text: Any, others: Iterable[Any]) -> Tuple[float, str]:
    """返回文本与候选集合中的最大相似度及对应的候选文本。"""
    best = 0.0
    best_text = ""
    for item in others:
        value = text_similarity(text, item)
        if value > best:
            best = value
            best_text = str(item or "")
    return best, best_text


def extract_person_names(text: Any) -> List[str]:
    """从简介文本中抽取疑似人名（拉丁双词名 + 中文「由 X 饰演」结构）。"""
    body = str(text or "")
    found: List[str] = []
    for match in _LATIN_NAME_RE.findall(body):
        candidate = match.strip()
        head = candidate.split(" ")[0]
        if head in _LATIN_STOPWORDS:
            continue
        found.append(candidate)
    for pattern in (_CJK_NAME_AFTER_RE, _CJK_NAME_BEFORE_RE):
        for match in pattern.findall(body):
            candidate = match.strip()
            if len(candidate) < 2 or candidate in _CJK_NAME_STOPWORDS:
                continue
            found.append(candidate)
    result: List[str] = []
    for name in found:
        if name not in result:
            result.append(name)
    return result


def suspicious_names(text: Any, known_names: Sequence[Any]) -> List[str]:
    """返回简介中出现、但不在已知演职员名单里的疑似人名。

    仅当已知名单非空时才判定，避免没有素材时把所有专有名词都当成幻觉。
    """
    known = {normalize_name(name) for name in (known_names or []) if str(name or "").strip()}
    if not known:
        return []
    suspects: List[str] = []
    for name in extract_person_names(text):
        key = normalize_name(name)
        if not key or key in known:
            continue
        # 中文名可能是「魏娆」这类两字名，若已知名单里存在包含关系则视为同一人
        if any(key in item or item in key for item in known):
            continue
        suspects.append(name)
    return suspects


def classify_failure(message: Any, default: str = "unknown") -> str:
    """把失败信息归类，便于按原因统计与制定重试策略。"""
    text = str(message or "")
    if not text:
        return default
    rules: List[Tuple[str, Tuple[str, ...]]] = [
        ("llm_unavailable", ("llm 不可用", "模型不可用", "未配置")),
        ("llm_rate_limit", ("限流", "429", "too many requests", "rate limit")),
        ("llm_empty", ("返回空内容", "空返回", "空内容")),
        ("llm_error", ("调用失败", "超时", "timeout", "翻译失败", "生成失败")),
        (
            "quality_gate",
            (
                "中文占比",
                "技术信息",
                "模板化",
                "过短",
                "超出目标字数",
                "AI 味",
                "雷同",
                "相似",
                "人名",
            ),
        ),
        ("material_missing", ("无可用简介", "无该集简介", "TMDB 无", "素材")),
        ("nfo_write", ("nfo",)),
        (
            "emby_write",
            ("无法读取条目", "http", "回读不一致", "写入后", "请求失败", "无响应"),
        ),
    ]
    lowered = text.casefold()
    for kind, keywords in rules:
        for keyword in keywords:
            if keyword.casefold() in lowered:
                return kind
    return default


def summarize_failure_kinds(failures: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """按失败类别汇总失败条目数量。"""
    summary: Dict[str, int] = {}
    for entry in failures or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("error_kind") or classify_failure(entry.get("message")))
        summary[kind] = summary.get(kind, 0) + 1
    return dict(sorted(summary.items(), key=lambda item: -item[1]))
