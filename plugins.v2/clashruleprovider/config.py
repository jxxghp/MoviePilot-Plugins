from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from .models.api import ClashApi


class SubscriptionConfig(BaseModel):
    url: str
    rules: Optional[bool] = True
    rule_providers: Optional[bool] = Field(True, alias='rule-providers')
    proxies: Optional[bool] = True
    proxy_groups: Optional[bool] = Field(True, alias='proxy-groups')
    proxy_providers: Optional[bool] = Field(True, alias='proxy-providers')

    @validator('url', allow_reuse=True)
    def validate_url(cls, v: str):
        return v.strip()


class PluginConfig(BaseModel):
    """
    A dataclass to hold all the configuration of the ClashRuleProvider plugin.
    """
    enabled: bool = False
    proxy: bool = False
    notify: bool = False
    subscriptions_config: List[SubscriptionConfig] = Field(default_factory=list)
    movie_pilot_url: str = ''
    cron_string: str = '30 12 * * *'
    timeout: int = 10
    retry_times: int = 3
    filter_keywords: List[str] = Field(default_factory=list)
    auto_update_subscriptions: bool = True
    ruleset_prefix: str = '📂<='
    acl4ssr_prefix: str = '🗂️=>'
    group_by_region: bool = False
    group_by_country: bool = False
    refresh_delay: int = 5
    enable_acl4ssr: bool = False
    dashboard_components: List[str] = Field(default_factory=list)
    clash_template: str = ''
    hint_geo_dat: bool = False
    best_cf_ip: List[str] = Field(default_factory=list)
    apikey: Optional[str] = None
    clash_dashboards: List[ClashApi] = Field(default_factory=list)
    active_dashboard: Optional[int] = None

    @validator('clash_dashboards', allow_reuse=True)
    def validate_clash_dashboards(cls, v: List[ClashApi]):
        for item in v:
            url = item.url.rstrip('/')
            if not (url.startswith('http://') or url.startswith('https://')):
                url = 'http://' + url
            item.url = url
        return v

    @validator('movie_pilot_url', allow_reuse=True)
    def validate_movie_pilot_url(cls, v: str):
        return v.rstrip('/')

    @validator('ruleset_prefix', allow_reuse=True)
    def validate_ruleset_prefix(cls, v: str):
        return v.strip()

    @validator('acl4ssr_prefix', allow_reuse=True)
    def validate_acl4ssr_prefix(cls, v: str):
        return v.strip()

    @staticmethod
    def upgrade_conf(conf: Dict[str, Any]) -> Dict[str, Any]:
        if conf.get('sub_links'):
            subscriptions_config = conf.get('subscriptions_config') or []
            subscriptions_config.extend(
                [{'url': url, 'rules': True, 'rule-providers': True, 'proxies': True, 'proxy-groups': True,
                  'proxy-providers': True}
                 for url in conf['sub_links']]
            )
            conf['subscriptions_config'] = subscriptions_config
        if conf.get('clash_dashboard_url') and conf.get('clash_dashboard_secret'):
            clash_dashboards = conf.get('clash_dashboards') or []
            clash_dashboards.append({'url': conf.get('clash_dashboard_url'), 'secret': conf.get('clash_dashboard_secret')})
            conf['clash_dashboards'] = clash_dashboards
        return conf

    @property
    def sub_links(self) -> List[str]:
        return [sub.url for sub in self.subscriptions_config]

    @property
    def dashboard_url(self) -> str:
        dashboard_url = ''
        if self.active_dashboard is not None and self.active_dashboard in range(len(self.clash_dashboards)):
            dashboard_url = self.clash_dashboards[self.active_dashboard].url
        return dashboard_url

    @property
    def dashboard_secret(self) -> str:
        dashboard_secret = ''
        if self.active_dashboard is not None and self.active_dashboard in range(len(self.clash_dashboards)):
            dashboard_secret = self.clash_dashboards[self.active_dashboard].secret
        return dashboard_secret
