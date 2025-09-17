from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PluginConfig:
    """
    A dataclass to hold all the configuration of the ClashRuleProvider plugin.
    """
    enabled = False
    proxy = False
    notify = False
    subscriptions_config: List[Dict[str, Any]] = field(default_factory=list)
    movie_pilot_url: str = ''
    cron_string = '30 12 * * *'
    timeout = 10
    retry_times = 3
    filter_keywords: List[str] = field(default_factory=list)
    auto_update_subscriptions = True
    ruleset_prefix: str = '📂<='
    acl4ssr_prefix: str = '🗂️=>'
    group_by_region: bool = False
    group_by_country: bool = False
    refresh_delay: int = 5
    enable_acl4ssr: bool = False
    dashboard_components: List[str] = field(default_factory=list)
    clash_template: str = ''
    hint_geo_dat: bool = False
    best_cf_ip: List[str] = field(default_factory=list)
    apikey: Optional[str] = None
    clash_dashboards: List[Dict[str, str]] = field(default_factory=list)
    active_dashboard: Optional[int] = None

    def from_dict(self, config: Dict[str, Any]):
        if 'enabled' in config:
            self.enabled = bool(config.get("enabled"))
        if 'proxy' in config:
            self.proxy = bool(config.get("proxy"))
        if 'notify' in config:
            self.notify = bool(config.get("notify"))
        sub_links = config.get("sub_links") or []
        self.subscriptions_config = config.get("subscriptions_config") or []
        self.subscriptions_config.extend(
            [{'url': url, 'rules': True, 'rule-providers': True, 'proxies': True, 'proxy-groups': True,
              'proxy-providers': True}
             for url in sub_links]
        )

        clash_dashboards = config.get("clash_dashboards")
        if clash_dashboards is None:
            clash_dashboards = [{'url': config.get('clash_dashboard_url') or '',
                                 'secret': config.get('clash_dashboard_secret') or ''}]
        self.clash_dashboards = []
        for clash_dashboard in clash_dashboards:
            url = (clash_dashboard.get("url") or '').rstrip('/')
            if url and not (url.startswith('http://') or url.startswith('https://')):
                url = 'http://' + url
            self.clash_dashboards.append({'url': url, 'secret': clash_dashboard.get('secret') or ''})

        self.movie_pilot_url = (config.get("movie_pilot_url") or '').rstrip('/')
        if config.get("cron_string"):
            self.cron_string = config.get("cron_string")
        if config.get("timeout"):
            self.timeout = config.get("timeout")
        if config.get("retry_times"):
            self.retry_times = config.get("retry_times")
        if config.get("refresh_delay"):
            self.refresh_delay = config.get("refresh_delay")
        if config.get("filter_keywords"):
            self.filter_keywords =  config.get("filter_keywords")
        if config.get("clash_template"):
            self.clash_template = config.get("clash_template")
        if config.get("best_cf_ip"):
            self.best_cf_ip = config.get("best_cf_ip")
        self.ruleset_prefix = (config.get("ruleset_prefix") or '').strip()
        if config.get("acl4ssr_prefix"):
            self.acl4ssr_prefix = config.get("acl4ssr_prefix").strip()
        if 'auto_update_subscriptions' in config:
            self.auto_update_subscriptions = config.get("auto_update_subscriptions")
        if 'group_by_region' in config:
            self.group_by_region = config.get("group_by_region")
        if 'group_by_country' in config:
            self.group_by_country = config.get("group_by_country")
        if 'enable_acl4ssr' in config:
            self.enable_acl4ssr = config.get("enable_acl4ssr")
        if 'dashboard_components' in config:
            self.dashboard_components = config.get("dashboard_components")
        if 'hint_geo_dat' in config:
            self.hint_geo_dat = config.get("hint_geo_dat")
        self.active_dashboard = config.get("active_dashboard")
        if self.active_dashboard is None and self.clash_dashboards:
            self.active_dashboard = 0
        self.apikey = config.get("apikey")

    @property
    def sub_links(self) -> List[str]:
        for sub in self.subscriptions_config:
            sub['url'] = sub['url'].strip()
        return [sub['url'] for sub in self.subscriptions_config if sub.get('url')]

    @property
    def dashboard_url(self) -> str:
        dashboard_url = ''
        if self.active_dashboard is not None and self.active_dashboard in range(len(self.clash_dashboards)):
            dashboard_url = self.clash_dashboards[self.active_dashboard].get("url")
        return dashboard_url

    @property
    def dashboard_secret(self) -> str:
        dashboard_secret = ''
        if self.active_dashboard is not None and self.active_dashboard in range(len(self.clash_dashboards)):
            dashboard_secret = self.clash_dashboards[self.active_dashboard].get("secret")
        return dashboard_secret

    def to_dict(self):
        return {
            'enabled': self.enabled,
            'proxy': self.proxy,
            'notify': self.notify,
            'subscriptions_config': self.subscriptions_config,
            'clash_dashboards': self.clash_dashboards,
            'movie_pilot_url': self.movie_pilot_url,
            'cron_string': self.cron_string,
            'timeout': self.timeout,
            'retry_times': self.retry_times,
            'filter_keywords': self.filter_keywords,
            'auto_update_subscriptions': self.auto_update_subscriptions,
            'ruleset_prefix': self.ruleset_prefix,
            'acl4ssr_prefix': self.acl4ssr_prefix,
            'group_by_region': self.group_by_region,
            'group_by_country': self.group_by_country,
            'refresh_delay': self.refresh_delay,
            'enable_acl4ssr': self.enable_acl4ssr,
            'dashboard_components': self.dashboard_components,
            'clash_template': self.clash_template,
            'hint_geo_dat': self.hint_geo_dat,
            'best_cf_ip': self.best_cf_ip,
            'active_dashboard': self.active_dashboard,
            'apikey': self.apikey
        }
