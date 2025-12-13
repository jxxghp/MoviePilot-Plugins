from typing import Literal

from pydantic import BaseModel, Field, RootModel

from .schemas import PosDef, Cefr


class CefrEntry(BaseModel):
    pos: Literal[
        "noun",
        "adverb",
        "interjection",
        "preposition",
        "determiner",
        "have-verb",
        "modal auxiliary",
        "adjective",
        "number",
        "be-verb",
        "verb",
        "conjunction",
        "do-verb",
        "infinitive-to",
        "vern",
        "pos",
        "pronoun",
    ] = Field(..., description="Part of speech")
    cefr: Cefr = Field(..., description="CEFR level")
    notes: str | None = Field(default=None, description="Notes")


class CefrDictionary(RootModel):
    root: dict[str, list[CefrEntry]]

    def get(self, word: str) -> list[CefrEntry] | None:
        return self.root.get(word)


class Coca20KEntry(BaseModel):
    index: int = Field(..., description="Index of the entry")
    phonetics_1: str = Field(..., description="Phonetics style 1")
    phonetics_2: str = Field(..., description="Phonetics style 2")
    pos_defs: list[PosDef] = Field(
        ..., description="List of part of speech definitions"
    )


class Coca20KDictionary(RootModel):
    root: dict[str, Coca20KEntry]

    def get(self, word: str) -> Coca20KEntry | None:
        return self.root.get(word)


class ShanBayDef(BaseModel):
    # 'n.', 'v.', 'adv.', 'adj.', 'phrase.', 'int.', 'pron.', 'prep.', '.', 'conj.', 'num.', 'phrase v.', 'linkv.',
    # 'det.', 'ordnumber.', 'prefix.', 'un.', 'vt.', 'mod. v.', 'abbr.', 'auxv.', 'modalv.', 'vi.', 'aux. v.',
    # 'interj.', 'article.', 'infinitive.', 'suff.', 'ord.', 'art.', 'exclam.', 'n.[C]'
    pos: str = Field(..., description="Part of speech")
    definition_cn: str = Field(..., description="Definition in Chinese")


class ShanbayEntry(BaseModel):
    ipa_uk: str = Field(..., description="UK IPA pronunciation")
    ipa_us: str = Field(..., description="US IPA pronunciation")
    defs: list[ShanBayDef] = Field(..., description="List of definitions")


class ShanbayDictionary(BaseModel):
    """Dictionary entries for various examinations."""

    cet4: dict[str, ShanbayEntry] = Field(
        ..., alias="CET-4", description="CET-4 dictionary entries"
    )
    cet6: dict[str, ShanbayEntry] = Field(
        ..., alias="CET-6", description="CET-6 dictionary entries"
    )
    npee: dict[str, ShanbayEntry] = Field(
        ..., alias="NPEE", description="NPEE dictionary entries"
    )
    ielts: dict[str, ShanbayEntry] = Field(
        ..., alias="IELTS", description="IELTS dictionary entries"
    )
    toefl: dict[str, ShanbayEntry] = Field(
        ..., alias="TOEFL", description="TOEFL dictionary entries"
    )
    gre: dict[str, ShanbayEntry] = Field(
        ..., alias="GRE", description="GRE dictionary entries"
    )
    tem4: dict[str, ShanbayEntry] = Field(
        ..., alias="TEM-4", description="TEM-4 dictionary entries"
    )
    tem8: dict[str, ShanbayEntry] = Field(
        ..., alias="TEM-8", description="TEM-8 dictionary entries"
    )
    pet: dict[str, ShanbayEntry] = Field(
        ..., alias="PET", description="PET dictionary entries"
    )

    def query(self, word: str) -> dict[str, ShanbayEntry]:
        result = {}
        for field_name, field_info in ShanbayDictionary.model_fields.items():
            value = getattr(self, field_name)
            if word in value:
                result[field_info.alias] = value[word]
        return result


class Lexicon(BaseModel):
    cefr: CefrDictionary = Field(..., description="CEFR dictionary")
    coca20k: Coca20KDictionary = Field(..., description="COCA 20K dictionary")
    examinations: ShanbayDictionary = Field(
        ..., description="Shanbay examinations dictionary"
    )
    swear_words: list[str] = Field(..., description="List of swear words")
    version: str = Field(..., description="Version of the lexicon")
