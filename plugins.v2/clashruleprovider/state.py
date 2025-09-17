from dataclasses import dataclass, field
from typing import Any, Dict, List

from .helper.clashrulemanager import ClashRuleManager
from .helper.proxiesmanager import ProxyManager


@dataclass
class PluginState:
    """
    A dataclass to hold all the runtime state of the ClashRuleProvider plugin.
    """
    # Rule and Proxy Managers
    top_rules_manager: ClashRuleManager = field(default_factory=ClashRuleManager)
    ruleset_rules_manager: ClashRuleManager = field(default_factory=ClashRuleManager)
    proxies_manager: ProxyManager = field(default_factory=ProxyManager)

    # Loaded from saved data
    proxy_groups: List[Dict[str, Any]] = field(default_factory=list)
    extra_proxies: List[Dict[str, Any]] = field(default_factory=list)
    subscription_info: Dict[str, Any] = field(default_factory=dict)
    rule_provider: Dict[str, Any] = field(default_factory=dict)
    rule_providers: Dict[str, Any] = field(default_factory=dict)
    ruleset_names: Dict[str, str] = field(default_factory=dict)
    acl4ssr_providers: Dict[str, Any] = field(default_factory=dict)
    clash_configs: Dict[str, Any] = field(default_factory=dict)
    hosts: List[Dict[str, Any]] = field(default_factory=list)
    overwritten_region_groups: Dict[str, Any] = field(default_factory=dict)
    overwritten_proxies: Dict[str, Any] = field(default_factory=dict)
    clash_template_dict: Dict[str, Any] = field(default_factory=dict)

    # Volatile state (generated at runtime)
    geo_rules: Dict[str, List[str]] = field(default_factory=lambda: {'geoip': [], 'geosite': []})
