from typing import List, Optional, Union, Literal

from pydantic import BaseModel, Field

from .rule import RoutingRuleType, Action, AdditionalParam
from .ruleproviders import RuleProvider

class RuleData(BaseModel):
    priority: int
    type: RoutingRuleType
    payload: Optional[str] = None
    action: Union[Action, str]
    additional_params: Optional[AdditionalParam] = None
    conditions: Optional[List[str]] = None
    condition: Optional[str] = None

    class Config:
        use_enum_values = True

class ClashApi(BaseModel):
    url: str
    secret: str

class Connectivity(BaseModel):
    clash_apis: List[ClashApi] = Field(default_factory=list)
    sub_links: List[str] = Field(default_factory=list)

class Subscription(BaseModel):
    url: str

class RuleProviderData(BaseModel):
    name: str
    rule_provider: RuleProvider

class SubscriptionInfo(BaseModel):
    url: str
    field: Literal['name', 'enabled']
    value: Union[bool, str]

class Host(BaseModel):
    domain: str
    value: List[str]
    using_cloudflare: bool

class HostData(BaseModel):
    domain: str
    value: Optional[Host] = None
