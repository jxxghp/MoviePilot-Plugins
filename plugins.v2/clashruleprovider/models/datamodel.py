from pydantic import BaseModel, Field

from .api import SubscriptionsInfo
from .configuration import ClashConfig
from .datapatch import DataPatch
from .hosts import Hosts
from .proxy import Proxies
from .proxygroups import ProxyGroups
from .ruleproviders import RuleProviders, RuleProvider
from .types import DataKey


class GeoRules(BaseModel):
    geoip: list[str] = Field(default_factory=list)
    geosite: list[str] = Field(default_factory=list)


class PersistState(BaseModel):
    proxies: Proxies = Field(alias=DataKey.PROXIES, default_factory=Proxies)
    proxy_groups: ProxyGroups = Field(alias=DataKey.PROXY_GROUPS, default_factory=ProxyGroups)
    subscription_info: SubscriptionsInfo = Field(alias=DataKey.SUB_INFO, default_factory=SubscriptionsInfo)
    rule_provider: dict[str, RuleProvider] = Field(alias=DataKey.AUTO_RULE_PROVIDERS, default_factory=dict)
    rule_providers: RuleProviders = Field(alias=DataKey.RULE_PROVIDERS, default_factory=RuleProviders)
    ruleset_names: dict[str, str] = Field(alias=DataKey.RULESET_NAMES, default_factory=dict)
    acl4ssr_providers: RuleProviders = Field(alias=DataKey.ACL4SSR, default_factory=RuleProviders)
    sub_configs: dict[str, ClashConfig] = Field(alias=DataKey.SUB_CONFIGS, default_factory=dict)
    hosts: Hosts = Field(alias=DataKey.HOSTS, default_factory=Hosts)
    proxy_group_patch: DataPatch = Field(alias=DataKey.PROXY_GROUP_PATCH, default_factory=DataPatch)
    proxy_patch: DataPatch = Field(alias=DataKey.PROXY_PATCH, default_factory=DataPatch)
    geo_rules: GeoRules = Field(alias=DataKey.GEO_RULES, default_factory=GeoRules)
    rule_provider_patch: DataPatch = Field(alias=DataKey.RULE_PROVIDER_PATCH, default_factory=DataPatch)
