from pydantic import BaseModel, Field, field_validator, field_serializer

from .metadata import Metadata
from .rule import RuleType
from .rule import RoutingRuleType, Action, AdditionalParam
from ..helper.clashruleparser import ClashRuleParser


class RuleItem(BaseModel):
    """Clash rule item"""
    rule: RuleType
    meta: Metadata = Field(default_factory=Metadata)

    @field_serializer("rule")
    def serialize_rule(self, v: RuleType, _info):
        return str(v)

    @field_validator("rule", mode="before")
    @classmethod
    def validate_rule(cls, v):
        if isinstance(v, str):
            return ClashRuleParser.parse(v)
        return v


class RuleData(BaseModel):
    priority: int
    rule_string: str
    type: RoutingRuleType
    payload: str | None = None
    action: Action | str
    additional_params: AdditionalParam | None = None
    conditions: list[str] | None = None
    condition: str | None = None
    meta: Metadata = Field(default_factory=Metadata)

    @classmethod
    def from_rule_item(cls, item: RuleItem, priority: int) -> 'RuleData':
        fields = item.rule.to_dict()
        return cls(priority=priority, meta=item.meta, **fields)
