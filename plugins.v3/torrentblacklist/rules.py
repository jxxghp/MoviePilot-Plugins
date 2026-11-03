"""有界、不可变的规则与纯资源事实匹配。"""

import hashlib
import json
from typing import Annotated, Literal, Self
from unicodedata import normalize

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

SiteId = Annotated[StrictInt, Field(gt=0)]
RuleId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Keyword = Annotated[StrictStr, Field(min_length=1, max_length=256)]
SiteName = Annotated[StrictStr, Field(min_length=1, max_length=256)]
TorrentTitle = Annotated[StrictStr, Field(min_length=1, max_length=2048)]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def normalized_text(value: str) -> str:
    """关键词按文字匹配，不解释正则或通配符。"""
    return normalize("NFC", normalize("NFC", value).casefold())


def _nonblank(value: str, limit: int, *, fold: bool = False) -> str:
    value = normalized_text(value.strip()) if fold else normalize("NFC", value.strip())
    if not value or len(value) > limit:
        raise ValueError("文字不能为空或超过长度限制")
    return value


class KeywordInput(FrozenModel):
    kind: Literal["keyword"] = "keyword"
    keyword: Keyword
    site_id: SiteId | None = None

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        return _nonblank(value, 256, fold=True)


class SiteInput(FrozenModel):
    kind: Literal["site"] = "site"
    site_id: SiteId


RuleInput = Annotated[KeywordInput | SiteInput, Field(discriminator="kind")]


class RuleSpec(FrozenModel):
    kind: Literal["keyword", "site", "site_title"]
    keyword: Keyword | None = None
    site_id: SiteId | None = None
    site_name: SiteName | None = None
    title: TorrentTitle | None = None

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value, 256, fold=True)

    @field_validator("site_name", "title")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value, 2048)

    @model_validator(mode="after")
    def check_shape(self) -> Self:
        present = {name for name in ("keyword", "site_id", "site_name", "title")
                   if getattr(self, name) is not None}
        if self.kind == "keyword":
            valid = "keyword" in present and present <= {"keyword", "site_id"}
        elif self.kind == "site":
            valid = present == {"site_id"}
        else:
            valid = present == {"site_name", "title"}
        if not valid:
            raise ValueError("规则字段与类型不匹配")
        return self


def _rule_id(spec: RuleSpec) -> str:
    fields = {name: getattr(spec, name) for name in RuleSpec.model_fields
              if getattr(spec, name) is not None}
    content = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class Rule(RuleSpec):
    id: RuleId

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        if self.id != _rule_id(self):
            raise ValueError("规则标识与内容不匹配")
        return self


def create_rule(value: KeywordInput | SiteInput) -> Rule:
    spec = RuleSpec.model_validate(value.model_dump())
    return Rule(id=_rule_id(spec), **spec.model_dump())


def history_rule(site_name: str, title: str) -> Rule:
    spec = RuleSpec(kind="site_title", site_name=site_name, title=title)
    return Rule(id=_rule_id(spec), **spec.model_dump())


def matches(rule: Rule, torrent: object) -> bool:
    """只使用当前候选提供的站点 ID、名称、标题和简介。"""
    site = getattr(torrent, "site", None)
    if rule.kind in {"keyword", "site"} and rule.site_id is not None:
        if type(site) is not int or site != rule.site_id:
            return False
    if rule.kind == "site":
        return True
    title = getattr(torrent, "title", "")
    title = title if isinstance(title, str) else ""
    if rule.kind == "site_title":
        site_name = getattr(torrent, "site_name", "")
        return (
            isinstance(site_name, str)
            and normalize("NFC", site_name.strip()) == rule.site_name
            and normalize("NFC", title.strip()) == rule.title
        )
    description = getattr(torrent, "description", "")
    description = description if isinstance(description, str) else ""
    return any(rule.keyword in normalized_text(text) for text in (title, description))
