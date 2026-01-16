import re
import uuid
from collections import Counter
from enum import Enum, StrEnum
from typing import Literal, Generator, Iterator

from pydantic import BaseModel, Field, RootModel, model_validator, field_validator

from app.utils.singleton import Singleton


Cefr = Literal["C2", "C1", "B2", "B1", "A2", "A1"]


class UniversalPos(StrEnum):
    """Universal Part-of-Speech tags"""
    ADJ = "ADJ"  # Adjective
    ADV = "ADV"  # Adverb
    INTJ = "INTJ"  # Interjection
    NOUN = "NOUN"  # Noun
    PROPN = "PROPN"  # Proper noun
    VERB = "VERB"  # Verb
    ADP = "ADP"  # Adposition (preposition/postposition)
    AUX = "AUX"  # Auxiliary verb
    CCONJ = "CCONJ"  # Coordinating conjunction
    DET = "DET"  # Determiner
    NUM = "NUM"  # Numeral
    PART = "PART"  # Particle
    PRON = "PRON"  # Pronoun
    SCONJ = "SCONJ"  # Subordinating conjunction
    PUNCT = "PUNCT"  # Punctuation
    SYM = "SYM"  # Symbol
    X = "X"  # Other/unknown


class LexicalFeatures(StrEnum):
    """Lexical features for words."""
    FORMAL = "formal"
    INFORMAL = "informal"
    SLANG = "slang"
    COLLOQUIAL = "colloquial"
    ARCHAIC = "archaic"
    DIALECT = "dialect"
    TECHNICAL = "technical"
    LITERARY = "literary"
    ABBREVIATION = "abbreviation"
    NAME = "name"
    IDIOMATIC = "idiomatic"
    NEOLOGISM = "neologism"
    GIBBERISH = "gibberish"
    COMPOUND = "compound"


class IDGenerator(metaclass=Singleton):
    """Singleton class for generating unique IDs."""

    _counter = 0

    def next_id(self):
        self._counter += 1
        return self._counter

    def reset(self):
        self._counter = 0


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    IGNORED = "ignored"


class TaskParams(BaseModel):
    skip_existing: bool = Field(default=True, description="Whether to skip existing subtitle files")


class TasksApiParams(BaseModel):
    operation: Literal["DELETE", "RETRY", "IGNORE"] = Field(
        ..., description="Operation to perform on the tasks"
    )
    task_id: str | None = Field(default=None, description="Unique identifier for the task")


class SegmentStatistics(BaseModel):
    total_segments: int = Field(default=0, description="Total number of subtitle segments")
    total_words: int = Field(default=0, description="Total number of candidate words")
    cefr_distribution: dict[str, int] = Field(
        default_factory=dict, description="Distribution of words by CEFR level"
    )
    pos_distribution: dict[str, int] = Field(
        default_factory=dict, description="Distribution of words by Part of Speech"
    )
    exam_distribution: dict[str, int] = Field(
        default_factory=dict, description="Distribution of words by Examination"
    )

    def to_string(self) -> str:
        cefr_str = ", ".join(
            [f"{level}({count})" for level, count in self.cefr_distribution.items()]
        )
        pos_str = ", ".join(
            [f"{pos}({count})" for pos, count in self.pos_distribution.items()]
        )
        exam_str = ", ".join([f"{exam}({count})" for exam, count in self.exam_distribution.items()])
        return (
            f"Total Segments: {self.total_segments}\n"
            f"Total Words: {self.total_words}\n"
            f"CEFR Distribution: {cefr_str if cefr_str else 'N/A'}\n"
            f"POS Distribution: {pos_str if pos_str else 'N/A'}\n"
            f"Exam Distribution: {exam_str if exam_str else 'N/A'}"
        )


class ProcessResult(BaseModel):
    """Result of processing a task."""

    message: str | None = Field(default=None, description="Additional message or error information")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current status of the task")
    statistics: SegmentStatistics | None = Field(default=None, description="Statistics of the task")


class Task(BaseModel):
    video_path: str = Field(..., description="Path to the video file")
    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the task",
    )
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current status of the task")
    add_time: str | None = Field(default=None, description="Add time of the task, format %Y-%m-%d %H:%M:%S")
    complete_time: str | None = Field(default=None, description="Complete time of the task")
    tokens_used: int = Field(default=0, description="Number of used tokens")
    message: str | None = Field(default=None, description="Additional message or error information")
    params: TaskParams = Field(default_factory=TaskParams, description="Parameters for the task")
    statistics: SegmentStatistics | None = Field(default=None, description="Statistics of the task")


class WordMetadata(BaseModel):
    start_pos: int = Field(..., description="Start position of the word in the context sentence")
    end_pos: int = Field(..., description="End position of the word in the context sentence")
    context_id: int = Field(..., description="Identifier of the context sentence")
    word_id: int = Field(
        default_factory=lambda: IDGenerator().next_id(),
        description="Identifier of the word in the context",
    )


class PosDef(BaseModel):
    # 'art.', 'v.', 'aux.', 'conj.', 'prep.', 'adv.', 'adj.', 'n.', 'vt.', 'pron.', 'det.', 'vi.', 'int.'
    # 'num.', 'abbr.', 'na.', 'quant.', 'phr.'
    pos: str = Field(..., description="Part of speech")
    meanings: list[str] = Field(..., description="List of definitions")

    @property
    def plaintext(self):
        return f"{self.pos} {'; '.join(self.meanings)}"


class WordBase(BaseModel):
    text: str = Field(..., description="The word or phrase")
    lemma: str = Field(..., description="Lemma form of the word")
    pos: UniversalPos = Field(default=UniversalPos.X, description="Universal POS tag of the word")


class Word(WordBase):
    phonetics: str | None = Field(default=None, description="Phonetic transcription of the word")
    meta: WordMetadata = Field(default_factory=WordMetadata, description="Additional metadata")
    cefr: Cefr | None = Field(default=None, description="CEFR level")
    exams: list[str] = Field(
        default_factory=list,
        description="Exams whose vocabulary syllabus include this word",
    )
    pos_defs: list[PosDef] = Field(default_factory=list, description="Part of speech definitions")
    llm_translation: str | None = Field(default=None, description="LLM generated Chinese translation")
    llm_usage_context: str | None = Field(default=None, description="LLM generated cultural context")
    lexical_features: list[LexicalFeatures] = Field(default_factory=list, description="Lexical features")
    llm_example_sentences: list[str] = Field(default_factory=list, description="LLM generated example sentences")

    @property
    def pos_defs_plaintext(self) -> str:
        return " ".join(
            [
                f"{index}. {pos_def.plaintext}"
                for index, pos_def in enumerate(self.pos_defs)
            ]
        )


class SubtitleSegment(BaseModel):
    index: int = Field(..., description="Index of the subtitle segment")
    start_time: int = Field(
        ..., description="Start time of the subtitle segment in milliseconds"
    )
    end_time: int = Field(..., description="End time of the subtitle segment in milliseconds")
    plaintext: str = Field(..., description="Text content of the subtitle segment")
    Chinese: str | None = Field(default=None, description="Chinese translation of the subtitle segment")
    candidate_words: list[Word] = Field(
        default_factory=list, description="List of words worth learning in the segment"
    )

    def words_append(self, word: Word):
        """
        向字幕片段中添加一个单词到 words_worth_larning 列表中。

        :param word: 要添加的单词对象。
        """
        self.candidate_words.append(word)

    @staticmethod
    def _replace_with_spaces(_text):
        """
        使用等长的空格替换文本中的 [xxx] 模式。
        例如："[Hi]" 会被替换成 "    " (4个空格)
        """
        pattern = r"(\[.*?\])"
        return re.sub(pattern, lambda match: " " * len(match.group(1)), _text)

    @property
    def clean_text(self) -> str:
        """
        获取清理后的文本内容，去除换行符并将 [xxx] 模式替换为空格。
        """
        return SubtitleSegment._replace_with_spaces(self.plaintext.replace("\n", " "))

    def __lt__(self, other: object):
        if not isinstance(other, SubtitleSegment):
            return NotImplemented
        return self.index < other.index


class SegmentList(RootModel):
    root: list[SubtitleSegment] = Field(
        default_factory=list, description="List of subtitle segments"
    )

    @property
    def statistics(self) -> SegmentStatistics:
        all_words = [word for seg in self.root for word in seg.candidate_words]

        cefr_counts = Counter(word.cefr if word.cefr else "Other" for word in all_words)
        pos_counts = Counter(word.pos.value if word.pos else "Other" for word in all_words)
        exam_counts = Counter(exam for word in all_words for exam in word.exams)

        return SegmentStatistics(
            total_segments=len(self.root),
            total_words=len(all_words),
            cefr_distribution=dict(cefr_counts),
            pos_distribution=dict(pos_counts),
            exam_distribution=dict(exam_counts)
        )

    def context_generator(
        self, context_window: int, extra_len: int = 1
    ) -> Generator[tuple[list[SubtitleSegment], tuple[int, int]], None, None]:
        """
        生成包含上下文窗口的字幕片段列表

        :param context_window: 上下文窗口大小
        :param extra_len: 额外长度，用于调整窗口大小
        :yield: 包含上下文的字幕片段列表。
        """
        total_segments = len(self.root)
        for i in range((total_segments + context_window - 1) // context_window):
            real_start = i * context_window
            real_end = min(total_segments, (i + 1) * context_window) - 1
            start_index = max(0, i * context_window - extra_len)
            end_index = min(total_segments, (i + 1) * context_window + extra_len)
            yield (
                self.root[start_index:end_index],
                (self.root[real_start].index, self.root[real_end].index),
            )

    def sort(self):
        self.root.sort()

    @model_validator(mode="after")
    def sort_root(self):
        self.root.sort()
        return self

    def __iter__(self) -> Iterator[SubtitleSegment]:
        return iter(self.root)


class SpacyToken(BaseModel):
    lemma_: str = Field(..., description="Lemma form of the word (string)")
    pos_: str = Field(..., description="POS tag of the word")
    text: str = Field(..., description="Text of the word")
    is_stop: bool = Field(default=False, description="Indicates if the word is a stop word")
    is_punct: bool = Field(default=False, description="Indicates if the word is punctuation")
    ent_iob_: str = Field(..., description="Entity IOB")


class SpacyNamedEntity(BaseModel):
    text: str = Field(..., description="Text of the entity")
    label_: str = Field(..., description="Label of the entity")


class NlpResult(BaseModel):
    tokens: list[SpacyToken] = Field(default_factory=list, description="List of tokens")
    entities: list[SpacyNamedEntity] = Field(default_factory=list, description="List of named entities")


class LlmFeedbackAboutCandidateWord(BaseModel):
    should_keep: bool = Field(..., description="Indicates whether to keep the candidate word")
    # reason: str | None = Field(default=None, description="Concise reason for the decision")
    word_id: int = Field(..., description="Identifier of the word in the context")
    text: str | None = Field(default=None, description="The vocabulary word or phrase")
    lemma: str | None = Field(default=None, description="Lemma form of the word")
    pos: UniversalPos | None = Field(
        default=None,
        description="Universal POS tag of the word. Options: ADJ, ADV, INTJ, NOUN, PROPN, "
        "VERB, ADP, AUX, CCONJ, DET, NUM, PART, PRON, SCONJ, PUNCT, SYM, X",
    )


class LlmFeedback(BaseModel):
    candidate_words_feedback: list[LlmFeedbackAboutCandidateWord] = Field(
        default_factory=list, description="Feedback about candidate words."
    )
    llm_identified_words: list[WordBase] = Field(
        default_factory=list, description="List of words identified by the LLM."
    )


class LlmWordEnrichment(BaseModel):
    word_id: int = Field(..., description="Identifier of the word in the context")
    translation: str | None = Field(default=None, description="Chinese translation of the word")
    usage_context: str | None = Field(default=None, description="Usage or Cultural Context")
    lexical_features: list[LexicalFeatures] = Field(default_factory=list, description="Lexical features")

    @field_validator("lexical_features", mode="before")
    @classmethod
    def filter_invalid_lexical_features(cls, v):
        if isinstance(v, list):
            valid_values = {f.value for f in LexicalFeatures}
            return [item for item in v if item in valid_values]
        return v


class LlmEnrichmentResult(BaseModel):
    enriched_words: list[LlmWordEnrichment] = Field(default_factory=list, description="List of enriched word data")


class LlmSegmentTranslation(BaseModel):
    index: int = Field(..., description="Index of the subtitle segment")
    translation: str = Field(..., description="Natural Chinese translation of the segment")


class LlmTranslationResult(BaseModel):
    translations: list[LlmSegmentTranslation] = Field(default_factory=list, description="List of segment translations")


class VocabularyAnnotatingToolInput(BaseModel):
    explanation: str = Field(
        ...,
        description="This is a tool for adding a new vocabulary-annotating task to AnnotLexi",
    )
    video_path: str = Field(..., description="Path to the video file")
    skip_existing: bool = Field(default=True, description="Whether to skip existing subtitle files")


class QueryAnnotationTasksToolInput(BaseModel):
    count: int = Field(default=5, description="The maximum number of returned annotation tasks")
    explanation: str = Field(..., description="This is a tool for querying the latest annotation tasks in AnnotLexi")
