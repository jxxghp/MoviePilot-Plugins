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

# 拉丁人名：只抓带「饰演/扮演/主演」上下文的双词姓名。
# 裸的双词大写组合会把 New York、Los Angeles 这类地名当成演员名，误杀正常简介。
_LATIN_NAME_AFTER_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*(?:饰演|扮演|主演)"
)
_LATIN_NAME_BEFORE_RE = re.compile(
    r"(?:由|主演|演员|领衔主演|配音)[:：\s]*"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"
)
# 中文人名提示：「由 X 饰演」与「X 饰演」两种语序。
# 名字后面必须紧跟「饰演/扮演」，不能再用标点做断言：否则「自由。」「围中，」
# 这类普通短语会被截成 2~4 字候选并误判成编造人名。
_CJK_NAME_AFTER_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:饰演|扮演|主演)"
)
_CJK_NAME_BEFORE_RE = re.compile(
    r"(?:由|主演|演员|领衔主演|配音)[:：\s]*"
    r"([\u4e00-\u9fff]{2,4}?)(?=饰演|扮演|主演|饰)"
)

# 常见中文姓氏（单姓），用于过滤并非人名的候选片段。
# 不追求完整：宁可漏判也不误杀——误杀会让正常简介永远进失败清单。
_CJK_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
    "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍卻璩桑桂濮牛寿通边扈燕冀郏浦尚农"
    "温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘"
    "匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空"
    "曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
# 常见复姓：命中时姓氏占两个字，避免把「欧阳锋」截成「阳锋」。
_CJK_COMPOUND_SURNAMES = {
    "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫", "万俟",
    "闻人", "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台", "皇甫", "宗政",
    "濮阳", "公冶", "太叔", "申屠", "公孙", "慕容", "仲孙", "钟离", "长孙",
    "宇文", "司徒", "鲜于", "司空", "闾丘", "子车", "亓官", "司寇", "巫马",
    "公西", "颛孙", "壤驷", "公良", "漆雕", "乐正", "宰父", "谷梁", "拓跋",
    "夹谷", "轩辕", "令狐", "段干", "百里", "呼延", "东郭", "南门", "羊舌",
    "微生", "公户", "公玉", "公仪", "梁丘", "公仲", "公上", "公门", "公山",
    "公坚", "左丘", "公伯", "西门", "公祖", "第五", "公乘", "贯丘", "公皙",
    "南荣", "东里", "东宫", "仲长", "子书", "子桑", "即墨", "达奚", "褚师",
}
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


# 中文简介里混入英文时最常见的高频副词/连接词。
# 只收录这类词，避免把片名、品牌、人名等专有名词误判成「中英混杂」。
_STRAY_ENGLISH_WORDS = {
    "increasingly",
    "meanwhile",
    "however",
    "actually",
    "finally",
    "basically",
    "literally",
    "arguably",
    "eventually",
    "apparently",
    "unfortunately",
    "surprisingly",
    "particularly",
    "especially",
    "essentially",
    "relatively",
    "gradually",
    "constantly",
    "ultimately",
    "obviously",
    "simultaneously",
    "consequently",
    "furthermore",
    "moreover",
    "nevertheless",
    "therefore",
    "otherwise",
    "somewhat",
    "somehow",
    "anyway",
}


def stray_english_words(text: Any) -> List[str]:
    """找出中文简介里混入的英文高频副词/连接词，返回原文片段。

    只匹配固定词表，避免把片名、品牌、人名等专有名词当成中英混杂。
    """
    body = str(text or "")
    found: List[str] = []
    for match in re.finditer(r"[A-Za-z]{3,}", body):
        word = match.group()
        if word.casefold() in _STRAY_ENGLISH_WORDS and word not in found:
            found.append(word)
    return found


def common_prefix_length(left: Any, right: Any) -> int:
    """返回两段文本从开头起连续相同的字符数（忽略空白）。

    用于识别「同一部剧每集都用同一个开头」的模板化写法：字符级相似度对
    语序调整很敏感，而公共前缀对这种结构重复更稳定。
    """
    first = re.sub(r"\s+", "", str(left or ""))
    second = re.sub(r"\s+", "", str(right or ""))
    length = 0
    for char_left, char_right in zip(first, second):
        if char_left != char_right:
            break
        length += 1
    return length


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


def _cjk_surname_prefix(name: str) -> int:
    """返回中文名开头的姓氏长度：2 表示复姓、1 表示单姓、0 表示不像人名。"""
    text = str(name or "").strip()
    if len(text) >= 2 and text[:2] in _CJK_COMPOUND_SURNAMES:
        return 2
    if text[:1] and text[:1] in _CJK_SURNAMES:
        return 1
    return 0


def _plausible_cjk_name(raw: str) -> str:
    """从 2~4 字候选串里截出最像人名的片段，要求以常见姓氏开头。

    正则在「由/演员」后可能连带动词或称谓（如「由父亲张三饰演」会先匹配到
    「亲张三」），这里从候选串内找一个以姓氏开头的后缀，既保留正确姓名，
    也丢弃「围中各自」这类普通短语。
    """
    text = str(raw or "").strip()
    if len(text) < 2:
        return ""
    for start in range(0, len(text) - 1):
        tail = text[start:]
        if len(tail) > 4:
            continue
        if _cjk_surname_prefix(tail):
            return tail
    return ""


def _edit_distance(left: str, right: str) -> int:
    """计算两个短字符串的编辑距离，用于容忍译名里的一字差异。"""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, ch_left in enumerate(left, start=1):
        current = [i]
        for j, ch_right in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ch_left != ch_right),
                )
            )
        previous = current
    return previous[-1]


def _names_related(candidate: str, known: str) -> bool:
    """判断中文候选名与已知演职员名是否可能指同一人。

    允许「张三 / 张三丰」这类包含关系、共享两个字，以及只差一个字的译名，
    避免因为演职员表写全名、简介写简称而误判成编造人名。
    """
    if not candidate or not known:
        return False
    if candidate == known or candidate in known or known in candidate:
        return True
    if abs(len(candidate) - len(known)) <= 1 and len(set(candidate) & set(known)) >= 2:
        return True
    if len(candidate) >= 2 and len(known) >= 2 and _edit_distance(candidate, known) <= 1:
        return True
    return False


def _latin_names_related(candidate: str, known: str) -> bool:
    """判断拉丁名是否可能指同一人（允许只写姓或只写名）。"""
    left = str(candidate or "").strip().casefold()
    right = str(known or "").strip().casefold()
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    return bool(set(left.split()) & set(right.split()))


def extract_person_names(text: Any) -> List[str]:
    """从简介文本中抽取疑似人名（带饰演上下文的拉丁名与中文名）。"""
    body = str(text or "")
    found: List[str] = []
    for pattern in (_LATIN_NAME_AFTER_RE, _LATIN_NAME_BEFORE_RE):
        for match in pattern.findall(body):
            candidate = match.strip()
            head = candidate.split(" ")[0]
            if head in _LATIN_STOPWORDS:
                continue
            found.append(candidate)
    for pattern in (_CJK_NAME_AFTER_RE, _CJK_NAME_BEFORE_RE):
        for match in pattern.findall(body):
            candidate = _plausible_cjk_name(match)
            if not candidate or candidate in _CJK_NAME_STOPWORDS:
                continue
            found.append(candidate)
    result: List[str] = []
    for name in found:
        if name not in result:
            result.append(name)
    return result


def suspicious_names(
    text: Any, known_names: Sequence[Any], source_text: Any = ""
) -> List[str]:
    """返回简介中出现、但不在已知演职员名单里的疑似人名。

    仅当已知名单非空时才判定，避免没有素材时把所有专有名词都当成幻觉。
    为降低误杀，额外加三道保险：

    1. 中文候选必须以常见姓氏开头（过滤「围中各自」这类普通短语）；
    2. 与已知名单存在包含、共享两个字或编辑距离 1 时视为同一译名；
    3. 出现在素材原文里的名字不算 AI 编造，直接放行。
    """
    known = {normalize_name(name) for name in (known_names or []) if str(name or "").strip()}
    if not known:
        return []
    source_blob = normalize_name(source_text)
    suspects: List[str] = []
    for name in extract_person_names(text):
        key = normalize_name(name)
        if not key or key in known:
            continue
        if source_blob and key in source_blob:
            continue
        if re.search(r"[A-Za-z]", name):
            related = any(_latin_names_related(key, item) for item in known)
        else:
            related = any(_names_related(key, item) for item in known)
        if related:
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
