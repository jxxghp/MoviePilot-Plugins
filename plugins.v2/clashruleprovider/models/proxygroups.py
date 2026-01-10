import jsonpatch
import re
from typing import List, Optional, Union, Literal

from pydantic import BaseModel, Field, field_validator, RootModel, model_validator

from .generics import ResourceItem, ResourceList


class ProxyGroupBase(BaseModel):
    """
    包含所有代理组类型共有的通用字段。
    """
    # Required field
    name: str = Field(..., description="The name of the proxy group.")

    # Proxy and provider references
    proxies: Optional[List[str]] = Field(default=None,
                                         description="References to outbound proxies or other proxy groups.")
    use: Optional[List[str]] = Field(default=None, description="References to proxy provider sets.")

    # Health check fields
    url: Optional[str] = Field(default="https://www.gstatic.com/generate_204", description="Health check test address.")
    interval: Optional[int] = Field(default=300, description="Health check interval in seconds.")
    lazy: Optional[bool] = Field(default=True, description="If not selected, no health checks are performed.")
    timeout: Optional[int] = Field(default=5000, description="Health check timeout in milliseconds.")
    max_failed_times: Optional[int] = Field(default=5, alias="max-failed-times",
                                            description="Maximum number of failures before a forced health check.")
    expected_status: Optional[str] = Field(default='*', alias="expected-status",
                                           description="Expected HTTP response status code for health checks.")

    # Network and routing fields
    disable_udp: Optional[bool] = Field(default=False, description="Disables UDP for this proxy group.",
                                        alias="disable-udp")
    interface_name: Optional[str] = Field(default=None, description="DEPRECATED. Specifies the outbound interface.",
                                          alias="interface-name")
    routing_mark: Optional[int] = Field(default=None, alias="routing-mark",
                                        description="DEPRECATED. The routing mark for outbound connections.")

    # Dynamic proxy inclusion
    include_all: Optional[bool] = Field(default=False, description="Includes all outbound proxies and proxy sets.",
                                        alias="include-all")
    include_all_proxies: Optional[bool] = Field(default=False, description="Includes all outbound proxies.",
                                                alias="include-all-proxies")
    include_all_providers: Optional[bool] = Field(default=False, description="Includes all proxy provider sets.",
                                                  alias="include-all-providers")

    # Filtering
    filter: Optional[str] = Field(default=None, description="Regex to filter nodes from providers.")
    exclude_filter: Optional[str] = Field(default=None, description="Regex to exclude nodes.", alias="exclude-filter")
    exclude_type: Optional[str] = Field(default=None, description="Exclude nodes by adapter type, separated by '|'.",
                                        alias="exclude-type")

    # UI fields
    hidden: Optional[bool] = Field(default=False, description="Hides the proxy group in the API.")
    icon: Optional[str] = Field(default=None, description="Icon string for the proxy group, for UI use.")

    @field_validator('expected_status')
    @classmethod
    def validate_expected_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == '*':
            return v
        pattern = re.compile(r'^\d{3}([-/]\d{3})*$')
        if not pattern.match(v):
            raise ValueError("Invalid format for expected-status.")
        parts = re.split(r'[/]', v)
        for part in parts:
            if '-' in part:
                start, end = part.split('-')
                if not (start.isdigit() and end.isdigit() and 100 <= int(start) < 600 and 100 <= int(end) < 600 and int(
                        start) <= int(end)):
                    raise ValueError(f"Invalid status code range: {part}")
            elif not (part.isdigit() and 100 <= int(part) < 600):
                raise ValueError(f"Invalid status code: {part}")
        return v


class SelectGroup(ProxyGroupBase):
    type: Literal['select'] = "select"


class RelayGroup(ProxyGroupBase):
    type: Literal['relay'] = "relay"


class FallbackGroup(ProxyGroupBase):
    type: Literal['fallback'] = "fallback"


class UrlTestGroup(ProxyGroupBase):
    type: Literal['url-test'] = "url-test"
    tolerance: Optional[int] = Field(default=None, description="proxies switch tolerance, measured in milliseconds (ms).")


class LoadBalanceGroup(ProxyGroupBase):
    type: Literal['load-balance'] = "load-balance"
    strategy: Optional[Literal['round-robin', 'consistent-hashing', 'sticky-sessions']] = Field(
        default='round-robin', description="Load balancing strategy."
    )


class SmartGroup(ProxyGroupBase):
    type: Literal['smart'] = "smart"
    uselightgbm: bool = Field(default=False, description="Use LightGBM model predict weight.")
    collectdata: bool = Field(default=False, description="Collect datas for model training.")
    policy_priority: Optional[str] = Field(default=None,
                                           description="<1 means lower priority, >1 means higher priority, "
                                                            "the default is 1, pattern support regex and string.",
                                           alias="policy-priority")
    strategy: Optional[Literal['round-robin', 'sticky-sessions']] = Field(
        default='sticky-sessions', description="Load balancing strategy."
    )
    sample_rate: Optional[int] = Field(default=1, description="Data acquisition rate.", alias="sample-rate")

    @field_validator('policy_priority', mode='before')
    @classmethod
    def validate_policy_priority(cls, v):
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise ValueError('policy_priority must be a string')
        return v

# Discriminated Union
ProxyGroupType = Union[SelectGroup, RelayGroup, FallbackGroup, UrlTestGroup, LoadBalanceGroup, SmartGroup]


class ProxyGroup(RootModel[ProxyGroupType]):
    root: ProxyGroupType = Field(..., discriminator='type')

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def proxies(self) -> list[str]:
        if self.root.proxies:
            return self.root.proxies
        return []

    def __getattr__(self, item):
        return getattr(self.root, item)

    def patch(self, patch: str) -> 'ProxyGroup':
        src = self.model_dump(mode="json", by_alias=True)
        patched = jsonpatch.apply_patch(src, patch=patch, in_place=True)
        return ProxyGroup.model_validate(patched)


class ProxyGroupData(ResourceItem[ProxyGroup]):
    """Proxy Group Data"""

    @model_validator(mode="after")
    def validate_name_consistency(self):
        data_name = self.data.name
        if self.name != data_name:
            raise ValueError(f"name ({self.name}) must equal data.name ({data_name})")
        return self


class ProxyGroups(ResourceList[ProxyGroupData]):
    """Proxy Groups Collection"""
    pass
