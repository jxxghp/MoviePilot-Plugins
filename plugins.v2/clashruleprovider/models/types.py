from enum import StrEnum
from typing import TypeVar, Protocol


class DataSource(StrEnum):
    MANUAL = "Manual"
    ACL4SSR = "Acl4SSR"
    TEMPLATE = "Template"
    SUB = "Subscription"
    AUTO = "Auto"


class VehicleType(StrEnum):
    FILE = "file"
    HTTP = "http"
    INLINE = "inline"


class DataKey(StrEnum):
    """Plugin data key"""
    PROXY_PATCH = "proxy_patch"
    PROXY_GROUPS = "proxy-groups"
    PROXIES = "proxies"
    INVALID_PROXIES = "extra_proxies"
    SUB_INFO = "subscription_info"
    HOSTS = "hosts"
    ACL4SSR = "acl4ssr_providers"
    RULE_PROVIDERS = "rule-providers"
    DATA_VERSION = "data_version"
    SUB_CONFIGS = "clash_configs"
    PROXY_GROUP_PATCH = "proxy_group_patch"
    RULESET_NAMES = "ruleset_names"
    AUTO_RULE_PROVIDERS = "rule_provider"
    GEO_RULES = "geo_rules"
    TOP_RULES = "top_rules"
    RULESET_RULES = "ruleset_rules"
    RULE_PROVIDER_PATCH = "rule_provider_patch"
    RAW_PROXIES = "raw_proxies"


class RuleSet(StrEnum):
    TOP = "top"
    RULESET = "ruleset"


class ClashKey(StrEnum):
    PROXIES = "proxies"
    PROXY_GROUPS = "proxy-groups"
    NAME = "name"
    RULES = "rules"


T = TypeVar("T")

class SupportsPatch(Protocol[T]):
    def patch(self, patch: str) -> T:
        ...
