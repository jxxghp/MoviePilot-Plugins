import re
import threading

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import SecretStr

from app.core.config import settings
from app.schemas import Context
from app.schemas.types import MediaType
from app.log import logger
from .lexicon import CefrDictionary, Lexicon, Coca20KDictionary
from .schemas import (
    SubtitleSegment,
    PosDef,
    Word,
    Cefr,
    WordMetadata,
    SegmentList,
    LlmFeedback,
    UniversalPos,
    LlmEnrichmentResult,
    LlmTranslationResult,
)
from .spacyworker import SpacyWorker


_patterns = [
    r"\d+th|\d?1st|\d?2nd|\d?3rd",
    r"\w+'s$",
    r"\w+'d$",
    r"\w+'t$",
    "[Ii]'m$",
    r"\w+'re$",
    r"\w+'ve$",
    r"\w+'ll$",
]
filter_patterns: list[re.Pattern] = [re.compile(p) for p in _patterns]
pos_interests = {"NOUN", "VERB", "ADJ", "ADV", "ADP", "CCONJ", "SCONJ"}

UNIVERSAL_POS_MAP: dict[UniversalPos, str] = {
    UniversalPos.ADJ: "adj.",
    UniversalPos.ADV: "adv.",
    UniversalPos.INTJ: "int.",
    UniversalPos.NOUN: "n.",
    UniversalPos.PROPN: "n.",
    UniversalPos.VERB: "v.",
    UniversalPos.AUX: "aux.",
    UniversalPos.ADP: "prep.",
    UniversalPos.CCONJ: "conj.",
    UniversalPos.SCONJ: "conj.",
    UniversalPos.DET: "det.",
    UniversalPos.NUM: "num.",
    UniversalPos.PART: "part.",
    UniversalPos.PRON: "pron.",
    UniversalPos.PUNCT: None,
    UniversalPos.SYM: None,
    UniversalPos.X: None,
}


def initialize_llm(
    provider: str,
    api_key: str,
    model_name: str,
    base_url: str | None,
    temperature: float = 0.1,
    max_retries: int = 3,
    proxy: bool = False,
) -> BaseChatModel:
    """初始化 LLM"""

    if provider == "google":
        if proxy:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=SecretStr(api_key),
                max_retries=3,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                temperature=settings.LLM_TEMPERATURE,
                openai_proxy=settings.PROXY_HOST,
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,  # noqa
            max_retries=max_retries,
            temperature=temperature,
        )
    elif provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=model_name,
            api_key=SecretStr(api_key),
            max_retries=max_retries,
            temperature=temperature,
        )
    else:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            api_key=SecretStr(api_key),
            max_retries=max_retries,
            base_url=base_url,
            temperature=temperature,
            openai_proxy=settings.PROXY_HOST if proxy else None,
        )


def convert_pos_to_spacy(pos: str):
    """
    将给定的词性列表转换为 spaCy 库中使用的词性标签

    :param pos: 字符串形式词性
    :returns: 一个包含对应spaCy词性标签的列表。对于无法直接映射的词性，将返回None
    """
    spacy_pos_map = {
        "noun": "NOUN",
        "adjective": "ADJ",
        "adverb": "ADV",
        "verb": "VERB",
        "preposition": "ADP",
        "conjunction": "CCONJ",
        "determiner": "DET",
        "pronoun": "PRON",
        "interjection": "INTJ",
        "number": "NUM",
    }

    pos_lower = pos.lower()
    if pos_lower in spacy_pos_map:
        spacy_pos = spacy_pos_map[pos_lower]
    elif pos_lower == "be-verb":
        spacy_pos = "AUX"  # Auxiliary verb (e.g., be, do, have)
    elif pos_lower == "vern":
        spacy_pos = "VERB"  # Assuming 'vern' is a typo for 'verb'
    elif pos_lower == "modal auxiliary":
        spacy_pos = "AUX"  # Modal verbs are also auxiliaries
    elif pos_lower == "do-verb":
        spacy_pos = "AUX"
    elif pos_lower == "have-verb":
        spacy_pos = "AUX"
    elif pos_lower == "infinitive-to":
        spacy_pos = "PART"  # Particle (e.g., to in "to go")
    elif not pos_lower:  # Handle empty strings
        spacy_pos = None
    else:
        spacy_pos = None  # For unmapped POS tags
    return spacy_pos


def convert_spacy_to_universal(spacy_pos: str) -> UniversalPos:
    """
    将 spaCy POS 标签转换为 UniversalPos 枚举
    """
    # 创建映射字典
    pos_mapping = {
        "ADJ": UniversalPos.ADJ,
        "ADV": UniversalPos.ADV,
        "INTJ": UniversalPos.INTJ,
        "NOUN": UniversalPos.NOUN,
        "PROPN": UniversalPos.PROPN,
        "VERB": UniversalPos.VERB,
        "AUX": UniversalPos.AUX,
        # 介词/后置词
        "ADP": UniversalPos.ADP,
        # 连词
        "CCONJ": UniversalPos.CCONJ,
        "SCONJ": UniversalPos.SCONJ,
        # 限定词
        "DET": UniversalPos.DET,
        # 数词
        "NUM": UniversalPos.NUM,
        # 代词
        "PRON": UniversalPos.PRON,
        # 小品词
        "PART": UniversalPos.PART,
        # 标点
        "PUNCT": UniversalPos.PUNCT,
        # 符号
        "SYM": UniversalPos.SYM,
        # 其他
        "X": UniversalPos.X,
        # 特殊处理：spaCy 可能返回的其他标签
        "SPACE": UniversalPos.PUNCT,  # 空格当作标点处理
        "CONJ": UniversalPos.CCONJ,  # 旧版 spaCy 的连词标签
    }

    # 转换为大写，确保一致
    spacy_pos = spacy_pos.upper()

    # 如果直接匹配，返回对应枚举
    if spacy_pos in pos_mapping:
        return pos_mapping[spacy_pos]

    # 处理特殊情况：以特定前缀开头的标签
    if spacy_pos.startswith("ADJ"):
        return UniversalPos.ADJ
    elif spacy_pos.startswith("ADV"):
        return UniversalPos.ADV
    elif spacy_pos.startswith("NOUN"):
        return UniversalPos.NOUN
    elif spacy_pos.startswith("VERB"):
        return UniversalPos.VERB
    elif spacy_pos.startswith("PROPN"):
        return UniversalPos.PROPN
    elif spacy_pos.startswith("PRON"):
        return UniversalPos.PRON

    # 默认返回 X（未知）
    return UniversalPos.X


def get_cefr_by_spacy(
    lemma_: str, pos_: str, cefr_lexicon: CefrDictionary
) -> Cefr | None:
    word = lemma_.lower().strip("-*'")

    result = cefr_lexicon.get(word)
    if result:
        all_cefr: list[Cefr] = []
        if len(result) > 0:
            for entry in result:
                if pos_ == convert_pos_to_spacy(entry.pos):
                    return entry.cefr
                all_cefr.append(entry.cefr)
        return min(all_cefr)
    return None


def query_coca20k(word: str, coca20k: Coca20KDictionary):
    word = word.lower().strip("-*'")
    return coca20k.get(word)


def _update_word_via_lexicon(word: Word, lexi: Lexicon) -> Word:
    """
    使用词典信息更新单词对象

    :param word: 需要更新的单词对象
    :param lexi: 词典对象
    :returns: 更新后的单词对象
    """
    # query dictionary
    cefr = get_cefr_by_spacy(word.lemma, word.pos.value, lexi.cefr)
    res_of_coca = query_coca20k(word.lemma, lexi.coca20k)
    if res_of_coca and not cefr:
        cefr = None
    res_of_exams = lexi.examinations.query(word.lemma)
    exam_tags = [exam_id for exam_id in res_of_exams if exam_id in res_of_exams]
    pos_defs = []
    phonetics = ""
    if res_of_exams:
        for exam, value in res_of_exams.items():
            phonetics = value.ipa_uk
            defs = {}
            for pos_def in value.defs:
                pos = pos_def.pos
                definition_cn = pos_def.definition_cn
                defs.setdefault(pos, []).append(definition_cn)
            for pos, meanings in defs.items():
                pos_defs.append(PosDef(pos=pos, meanings=meanings))
            break
    elif res_of_coca:
        phonetics = res_of_coca.phonetics_1
        pos_defs = res_of_coca.pos_defs
    word.exams = exam_tags
    word.cefr = cefr
    word.pos_defs = pos_defs
    word.phonetics = phonetics
    return word


def extract_advanced_words(segment: SubtitleSegment, lexi: Lexicon, spacy_worker: SpacyWorker,
                           simple_level: set[Cefr]) -> list[Word]:
    text = segment.clean_text
    doc = spacy_worker.submit(text)
    last_end_pos = 0
    lemma_to_query = []
    words = []
    for token in doc.tokens:
        # filter tokens
        if (
            len(token.text) == 1
            or token.is_stop
            or token.is_punct
            or token.ent_iob_ != "O"
        ):
            continue
        if token.pos_ not in pos_interests:
            continue
        if token.lemma_ in lexi.swear_words:
            continue

        striped = token.lemma_.strip("-[")
        if any(p.match(striped) for p in filter_patterns):
            continue

        if striped in lemma_to_query:
            continue
        else:
            lemma_to_query.append(striped)
        striped_text = token.text.strip("-*[")
        start_pos = text.find(striped_text, last_end_pos)
        end_pos = start_pos + len(striped_text)

        last_end_pos = end_pos
        word = Word(
            text=striped_text,
            lemma=striped,
            pos=convert_spacy_to_universal(token.pos_),
            meta=WordMetadata(
                start_pos=start_pos, end_pos=end_pos, context_id=segment.index
            ),
        )
        word = _update_word_via_lexicon(word, lexi)
        if word.cefr and word.cefr in simple_level:
            continue
        words.append(word)
    return words


def _find_segment_by_word_id(segments: list[SubtitleSegment], word_id: int) -> SubtitleSegment | None:
    for segment in segments:
        for word in segment.candidate_words:
            if word.meta.word_id == word_id:
                return segment
    return None


def _update_word_metadata(
    new_text: str, meta: WordMetadata, segment: SubtitleSegment
) -> WordMetadata | None:
    """
    更新单词的元数据

    :param new_text: 新的单词文本
    :param meta: 单词的元数据对象
    :param segment: 字幕片段对象
    """
    text = segment.clean_text
    p_end = meta.end_pos
    new_len = len(new_text)
    i = meta.start_pos - new_len + 1
    i = max(0, i)
    j = p_end + min(0, (len(text) - (p_end + new_len)))

    for x in range(i, j + 1):
        text_view = text[x : (x + new_len)]
        if text_view == new_text:
            return WordMetadata(
                start_pos=x,
                end_pos=x + new_len,
                context_id=segment.index,
                word_id=meta.word_id,
            )
    return None


def format_time_extended(milliseconds: int):
    """
    将秒数转换为时间格式

    :param milliseconds: 整数，表示毫秒数
    :return: 字符串，格式为 HH:MM:SS 或 HH:MM:SS.mmm
    """
    if milliseconds < 0:
        sign = "-"
        milliseconds = abs(milliseconds)
    else:
        sign = ""

    hours = int(milliseconds // 3600000)
    minutes = int((milliseconds % 3600000) // 60000)
    seconds = (milliseconds % 60000) // 1000
    milliseconds_remainder = milliseconds % 1000
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds_remainder:03d}"


def _context_process_chain(
    lexi: Lexicon,
    llm: BaseChatModel,
    segments: list[SubtitleSegment],
    start: int,
    end: int,
    leaner_level: str = "C1",
    media_name: str | None = None,
    translate_sentences: bool = False
):
    feedback_parser = PydanticOutputParser(pydantic_object=LlmFeedback)

    def format_input(segment_list: list[SubtitleSegment]):
        media_name_prefix = (
            f"The following subtitles are from '{media_name}'.\n" if media_name else ""
        )
        return {
            "media_name_prefix": media_name_prefix,
            "context_text": " ".join([seg.clean_text for seg in segment_list]),
            "candidate_words": "\n".join(
                [
                    f"- {word.text} (WORD_ID: {word.meta.word_id}, LEMMA: {word.lemma}, CEFR: {word.cefr}, POS: {word.pos})"
                    for seg in segment_list
                    for word in seg.candidate_words
                ]
            ),
            "leaner_level": leaner_level,
            "format_instructions": feedback_parser.get_format_instructions(),
        }

    def refactor_by_feedback(feedback: LlmFeedback):
        # Process LLM feedback to update segments
        for word in feedback.candidate_words_feedback:
            seg = _find_segment_by_word_id(segments, word.word_id)
            if not seg or seg.index < start or seg.index > end:
                continue
            # Update word info based on feedback
            if not word.should_keep:
                seg.candidate_words = [
                    w for w in seg.candidate_words if w.meta.word_id != word.word_id
                ]
                continue
            for w in seg.candidate_words:
                if w.meta.word_id == word.word_id:
                    word_text = word.text
                    if word_text is not None and word.text != w.text:
                        # Update metadata if text changed
                        if word.text not in seg.clean_text:
                            # If the word text is not found in the segment, skip updating metadata
                            continue
                        new_meta = _update_word_metadata(word_text, w.meta, seg)
                        if not new_meta:
                            continue
                        w.meta = new_meta
                        w.text = word_text
                    if word.pos:
                        w.pos = word.pos
                    if word.lemma:
                        w.lemma = word.lemma

        # Add new words identified by LLM
        for new_word in feedback.llm_identified_words:
            for seg in segments:
                if seg.index < start or seg.index > end:
                    continue
                start_pos = seg.clean_text.find(new_word.text)
                if start_pos == -1:
                    continue
                if any(w.text == new_word.text for w in seg.candidate_words):
                    continue
                if new_word.lemma in lexi.swear_words:
                    continue
                new_meta = WordMetadata(
                    start_pos=start_pos,
                    end_pos=start_pos + len(new_word.text),
                    context_id=seg.index
                )
                built_word = Word(
                    text=new_word.text,
                    lemma=new_word.lemma,
                    pos=new_word.pos,
                    meta=new_meta
                )

                built_word = _update_word_via_lexicon(built_word, lexi)
                if built_word.cefr and built_word.cefr < leaner_level:
                    continue
                seg.candidate_words.append(built_word)

    prompt_template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are an expert in linguistics and language learning. Your task is to analyze subtitle segments.
Please perform the following tasks for an English learner at {leaner_level} CEFR level.

**CRITICAL INSTRUCTION**: The learner is advanced. They already know common daily vocabulary.
Your goal is to identify **only** content that helps them reach native-level proficiency.

1.  **Review and Evaluate Candidate Words:**
    *   **Goal**: Filter out simple words and correct any errors in lemma/POS/text.
    *   **Action**: Return feedback items **ONLY** for words that:
        1.  Should be **discarded** (too simple, trivial filler, profanity without cultural value). Set `should_keep` to `False`.
        2.  Need **correction** (wrong lemma, POS, or text boundary). Set `should_keep` to `True` and provide correct values.
    *   **Implicit Rule**: If a word is appropriate for the learner and has correct info, **DO NOT** include it in the output list.
    *   **Keep criteria**: Keep simple words **ONLY IF** used in a non-literal, metaphorical, or idiomatic sense.
    *   **Discard criteria**: Discard trivial conversational fillers ('gonna', 'wanna'), simple interjections, common profanity, and words below {leaner_level} level.

2.  **Identify Missed Words:**
    *   Identify any additional single words or phrases (typically 1-3 words) from the `context_text` that may be important for {leaner_level} learners. This specifically includes:
        *   **Slang or informal expressions.**
        *   **Internet terms or modern colloquialisms.**
        *   **Words or phrases that require specific cultural background knowledge to understand.**
        *   **Any other words or phrases that are challenging.**
    *   Avoid repeating words already listed in `candidate_words`.
    *   Must exist in the exact form in `context_text`.
    *   Provide lemma and POS.
    *   **Do NOT include** simple high-frequency words, common fillers ('gonna', 'gotta'), onomatopoeia, or basic swear words.

-------------------------
You MUST return output strictly matching the provided Pydantic schema. 
Return ONLY valid JSON.

**Here are the output format instructions you MUST follow strictly:**
{format_instructions}
""",
            ),
            (
                "human",
                """{media_name_prefix}Here is the context from the subtitles:
---
{context_text}
---
Here are the candidate words identified by a basic algorithm:
{candidate_words}
""",
            ),
        ]
    )
    feedback_chain = (
        format_input | prompt_template | llm.with_structured_output(LlmFeedback).with_retry(stop_after_attempt=3)
    )
    result: LlmFeedback = feedback_chain.invoke(segments)  # type: ignore
    refactor_by_feedback(result)

    # 丰富词义
    if any(segment.candidate_words for segment in segments):
        enrichment_prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a linguistics and English-learning expert. Your goal is to enhance vocabulary learning for Chinese users.\n
For each word (identified by `WORD_ID`), provide:
1.  **Translation:** A concise Chinese translation.
2.  **Usage or Cultural Context (optional, in Chinese)**:
    *   **Keep it brief and clear.**
    *   ONLY include if:
        - The word has a specific meaning in this context that differs from its common definition;
        - It is slang, idiom, phrasal, metaphorical, or culturally loaded;
    *   ONLY provide this context when learners would likely struggle to understand the word's usage without it.
3.  **Lexical Features**:
    *   Select the most appropriate tag(s) if applicable.

**For each word, provide the `word_id` to ensure proper mapping.**
**Your judgment should be based strictly on the provided subtitle context. DO NOT fabricate context or forced explanation.**

-------------------------
You MUST return output strictly matching the provided Pydantic schema.
Return ONLY valid JSON. 

**Here are the output format instructions you MUST follow strictly:**
{format_instructions}
""",
                ),
                (
                    "human",
                    """{media_name_prefix}Here is the context from the subtitles:
---
{context_text}
---
Here are the words you need to enrich:
{words_to_enrich}
""",
                ),
            ]
        )
        enrichment_parser = PydanticOutputParser(pydantic_object=LlmEnrichmentResult)

        def format_enrichment_input(segment_list: list[SubtitleSegment]):
            media_name_prefix = (
                f"The following subtitles are from '{media_name}'.\n"
                if media_name
                else ""
            )
            words_to_enrich = []
            for seg in segment_list:
                if start <= seg.index <= end:
                    for w in seg.candidate_words:
                        words_to_enrich.append(
                            f"- {w.text} (WORD_ID: {w.meta.word_id}, LEMMA: {w.lemma}, POS: {w.pos}, DEFINITIONS: {w.pos_defs_plaintext})"
                        )
            return {
                "media_name_prefix": media_name_prefix,
                "context_text": " ".join([seg.clean_text for seg in segment_list]),
                "words_to_enrich": "\n".join(words_to_enrich),
                "format_instructions": enrichment_parser.get_format_instructions(),
            }

        enrichment_chain = (
            format_enrichment_input
            | enrichment_prompt_template
            | llm.with_structured_output(LlmEnrichmentResult).with_retry(stop_after_attempt=3)
        )

        enrichment_result: LlmEnrichmentResult = enrichment_chain.invoke(segments)  # type: ignore

        for enriched_word_data in enrichment_result.enriched_words:
            for segment in segments:
                if segment.index < start or segment.index > end:
                    continue
                for candidate_word in segment.candidate_words:
                    if candidate_word.meta.word_id == enriched_word_data.word_id:
                        candidate_word.llm_translation = enriched_word_data.translation
                        candidate_word.llm_usage_context = enriched_word_data.usage_context
                        candidate_word.lexical_features = enriched_word_data.lexical_features
                        break
    # 整句翻译
    if translate_sentences:
        translation_parser = PydanticOutputParser(pydantic_object=LlmTranslationResult)

        translation_prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a professional subtitle translator. Your task is to translate English subtitle segments into natural, idiomatic Chinese.

**Guidelines:**
1.  **Tone & Style:** Maintain the original tone (e.g., casual, formal, humorous, dramatic).
2.  **Context:** Use the surrounding segments to ensure continuity and correct meaning.
3.  **Conciseness:** Subtitles have space constraints. Keep translations concise but accurate.
4.  **Formatting:** Return the result strictly matching the provided JSON schema.

-------------------------
You MUST return output strictly matching the provided Pydantic schema.
Return ONLY valid JSON.

**Here are the output format instructions you MUST follow strictly:**
{format_instructions}
""",
                ),
                (
                    "human",
                    """{media_name_prefix}Here are the segments to translate:
---
{segments_text}
---
""",
                ),
            ]
        )

        def format_translation_input(segment_list: list[SubtitleSegment]):
            media_name_prefix = (
                f"The following subtitles are from '{media_name}'.\n"
                if media_name
                else ""
            )
            # Only translate segments within the current batch range (start to end)
            segments_text_lines = []
            for seg in segment_list:
                if start <= seg.index <= end:
                    segments_text_lines.append(f"ID {seg.index}: {seg.clean_text}")

            return {
                "media_name_prefix": media_name_prefix,
                "segments_text": "\n".join(segments_text_lines),
                "format_instructions": translation_parser.get_format_instructions(),
            }

        translation_chain = (
            format_translation_input
            | translation_prompt_template
            | llm.with_structured_output(LlmTranslationResult).with_retry(stop_after_attempt=3)
        )

        try:
            translation_result: LlmTranslationResult = translation_chain.invoke(segments)  # type: ignore

            # Map translations back to segments
            trans_map = {
                t.index: t.translation for t in translation_result.translations
            }
            for segment in segments:
                if segment.index in trans_map:
                    segment.Chinese = trans_map[segment.index]
        except Exception as e:
            logger.error(f"Error during sentence translation: {e}")

    return [segment for segment in segments if start <= segment.index <= end]


def llm_process_chain(
    lexi: Lexicon,
    llm: BaseChatModel,
    segments: SegmentList,
    shutdown_event: threading.Event,
    context_window: int = 30,
    leaner_level: str = "C1",
    media_context: Context | None = None,
    translate_sentences: bool = False,
) -> SegmentList:
    """
    根据 LLM 的反馈更新字幕片段中的单词信息

    :param lexi: 词典对象
    :param llm: LLM 对象
    :param segments: 字幕片段
    :param shutdown_event: 关闭事件
    :param context_window: 上下文窗口大小
    :param leaner_level: 学习者的 CEFR 水平
    :param media_context: 媒体信息
    :param translate_sentences: 是否翻译句子
    :returns: 更新后的字幕片段列表
    """
    media_name = None
    if media_context and media_context.media_info and media_context.meta_info:
        media_info = media_context.media_info
        if media_info.type == MediaType.TV:
            media_name = f"{media_info.title_year} {media_context.meta_info.season_episode}"
        else:
            media_name = f"{media_info.title_year}"

    segments_list = []
    for context, (start, end) in segments.context_generator(context_window=context_window, extra_len=2):
        if shutdown_event.is_set():
            break

        logger.info(
            f"Processing segments {format_time_extended(context[0].start_time)} ({context[0].index}) ->"
            f" {format_time_extended(context[-1].end_time)} ({context[-1].index}) via LLM..."
        )
        segments_list.extend(
            _context_process_chain(
                lexi, llm, context, start, end, leaner_level, media_name, translate_sentences
            )
        )

    return SegmentList(root=segments_list)
