from abc import ABC
from typing import Final, Literal, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.plugins import _PluginBase

from .config import PluginConfig
from .state import PluginState
from .store import PluginStore


class _ClashRuleProviderBase(_PluginBase, ABC):
    # Constants
    DEFAULT_CLASH_CONF: Final[
        Dict[Literal['rules', 'rule-providers', 'proxies', 'proxy-groups', 'proxy-providers'], dict | list]] = {
        'rules': [], 'rule-providers': {},
        'proxies': [], 'proxy-groups': [], 'proxy-providers': {}
    }
    OVERWRITTEN_PROXIES_LIFETIME: Final[int] = 10
    ACL4SSR_API: Final[str] = "https://api.github.com/repos/ACL4SSR/ACL4SSR"
    METACUBEX_RULE_DAT_API: Final[str] = "https://api.github.com/repos/MetaCubeX/meta-rules-dat"
    MISFIRE_GRACE_TIME: Final[int] = 120
    KEY_TOP_RULES: Final[str] = "top_rules"
    KEY_RULESET_RULES: Final[str] = "ruleset_rules"
    KEY_PROXIES: Final[str] = "proxies"
    KEY_PROXY_GROUPS: Final[str] = "proxy-groups"
    KEY_NAME: Final[str] = "name"

    # Runtime variables
    state: PluginState
    config: PluginConfig
    store: PluginStore
    scheduler: AsyncIOScheduler = None
