import re
from typing import List, Optional, Union, Literal

from pydantic import BaseModel, Field, validator


class ProxyGroupBase(BaseModel):
    """
    包含所有代理组类型共有的通用字段。
    """
    # Required field
    name: str = Field(..., description="The name of the proxy group.")

    # Proxy and provider references
    proxies: Optional[List[str]] = Field(None, description="References to outbound proxies or other proxy groups.")
    use: Optional[List[str]] = Field(None, description="References to proxy provider sets.")

    # Health check fields
    url: Optional[str] = Field(None, description="Health check test address.")
    interval: Optional[int] = Field(None, description="Health check interval in seconds.")
    lazy: Optional[bool] = Field(True, description="If not selected, no health checks are performed.")
    timeout: Optional[int] = Field(None, description="Health check timeout in milliseconds.")
    max_failed_times: Optional[int] = Field(5, description="Maximum number of failures before a forced health check.",
                                            alias="max-failed-times")
    expected_status: Optional[str] = Field('*',
                                           description="Expected HTTP response status code for health checks.",
                                           alias="expected-status")

    # Network and routing fields
    disable_udp: Optional[bool] = Field(False, description="Disables UDP for this proxy group.", alias="disable-udp")
    interface_name: Optional[str] = Field(None, description="DEPRECATED. Specifies the outbound interface.",
                                          alias="interface-name")
    routing_mark: Optional[int] = Field(None, description="DEPRECATED. The routing mark for outbound connections.",
                                        alias="routing-mark")

    # Dynamic proxy inclusion
    include_all: Optional[bool] = Field(False, description="Includes all outbound proxies and proxy sets.",
                                        alias="include-all")
    include_all_proxies: Optional[bool] = Field(False, description="Includes all outbound proxies.",
                                                alias="include-all-proxies")
    include_all_providers: Optional[bool] = Field(False, description="Includes all proxy provider sets.",
                                                  alias="include-all-providers")

    # Filtering
    filter: Optional[str] = Field(None, description="Regex to filter nodes from providers.")
    exclude_filter: Optional[str] = Field(None, description="Regex to exclude nodes.", alias="exclude-filter")
    exclude_type: Optional[str] = Field(None, description="Exclude nodes by adapter type, separated by '|'.",
                                        alias="exclude-type")

    # UI fields
    hidden: Optional[bool] = Field(False, description="Hides the proxy group in the API.")
    icon: Optional[str] = Field(None, description="Icon string for the proxy group, for UI use.")

    @validator('expected_status', allow_reuse=True)
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
    type: Literal['select']


class RelayGroup(ProxyGroupBase):
    type: Literal['relay']


class FallbackGroup(ProxyGroupBase):
    type: Literal['fallback']


class UrlTestGroup(ProxyGroupBase):
    type: Literal['url-test']
    tolerance: Optional[int] = Field(None, description="proxies switch tolerance, measured in milliseconds (ms).")


class LoadBalanceGroup(ProxyGroupBase):
    type: Literal['load-balance']
    strategy: Optional[Literal['round-robin', 'consistent-hashing', 'sticky-sessions']] = Field(
        'round-robin',
        description="Load balancing strategy."
    )


class SmartGroup(ProxyGroupBase):
    type: Literal['smart']
    uselightgbm: bool = Field(..., description="Use LightGBM model predict weight.")
    collectdata: bool = Field(..., description="Collect datas for model training.")
    policy_priority: Optional[str] = Field("1",
                                           description="<1 means lower priority, >1 means higher priority, "
                                                            "the default is 1, pattern support regex and string.",
                                           alias="policy-priority")
    strategy: Optional[Literal['round-robin', 'sticky-sessions']] = Field(
        'sticky-sessions',
        description="Load balancing strategy."
    )
    sample_rate: Optional[int] = Field(1, description="Data acquisition rate.", alias="sample-rate")


# Discriminated Union
ProxyGroupType = Union[SelectGroup, RelayGroup, FallbackGroup, UrlTestGroup, LoadBalanceGroup, SmartGroup]


class ProxyGroup(BaseModel):
    __root__: ProxyGroupType = Field(..., discriminator='type')

    def dict(self, **kwargs):
        return self.__root__.dict(**kwargs)
