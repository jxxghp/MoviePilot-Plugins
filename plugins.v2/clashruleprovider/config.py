from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models.api import ClashApi


class SubscriptionConfig(BaseModel):
    url: str
    rules: Optional[bool] = True
    rule_providers: Optional[bool] = Field(default=True, alias='rule-providers')
    proxies: Optional[bool] = True
    proxy_groups: Optional[bool] = Field(default=True, alias='proxy-groups')
    proxy_providers: Optional[bool] = Field(default=True, alias='proxy-providers')

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        return v.strip()


class PluginConfig(BaseModel):
    """
    A dataclass to hold all the configuration of the ClashRuleProvider plugin.
    """
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    enabled: bool = False
    proxy: bool = False
    notify: bool = False
    subscriptions_config: list[SubscriptionConfig] = Field(default_factory=list)
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
    identifiers: list[str] = Field(default_factory=list)
    cache_ttl: int = 3600

    @field_validator('clash_dashboards')
    @classmethod
    def validate_clash_dashboards(cls, v: List[ClashApi]):
        for item in v:
            url = item.url.rstrip('/')
            if not (url.startswith('http://') or url.startswith('https://')):
                url = 'http://' + url
            item.url = url
        return v

    @field_validator('movie_pilot_url')
    @classmethod
    def validate_movie_pilot_url(cls, v: str):
        return v.rstrip('/')

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

    def get_sub_conf(self, url: str) -> SubscriptionConfig:
        return next((conf for conf in self.subscriptions_config if conf.url == url), SubscriptionConfig(url=url))
