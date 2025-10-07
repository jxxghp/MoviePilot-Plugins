import asyncio
import copy
import pytz
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict, Tuple

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.schemas.types import EventType, NotificationType
from app.scheduler import Scheduler

from .api import ClashRuleProviderApi, apis
from .base import _ClashRuleProviderBase
from .config import PluginConfig
from .helper.utilsprovider import UtilsProvider
from .state import PluginState
from .services import ClashRuleProviderService
from .store import PluginStore


class ClashRuleProvider(_ClashRuleProviderBase):
    # 插件名称
    plugin_name = "Clash Rule Provider"
    # 插件描述
    plugin_desc = "随时为Clash添加一些额外的规则。"
    # 插件图标
    plugin_icon = "Mihomo_Meta_A.png"
    # 插件版本
    plugin_version = "2.0.8"
    # 插件作者
    plugin_author = "wumode"
    # 作者主页
    author_url = "https://github.com/wumode"
    # 插件配置项ID前缀
    plugin_config_prefix = "clashruleprovider_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1
    # 主线程事件循环
    event_loop: Optional[asyncio.AbstractEventLoop] = None

    def __init__(self):
        # Configuration attributes
        super().__init__()

        # Runtime variables
        self.services: Optional[ClashRuleProviderService] = None
        self.api: Optional[ClashRuleProviderApi] = None

    def init_plugin(self, conf: dict = None):
        self.stop_service()
        self.state = PluginState()
        self.config = PluginConfig()
        self.store = PluginStore(self.__class__.__name__)

        # Load persistent data into state
        self.state.proxy_groups = self.get_data("proxy_groups") or []
        self.state.extra_proxies = self.get_data("extra_proxies") or []
        self.state.subscription_info = self.get_data("subscription_info") or {}
        self.state.rule_provider = self.get_data("rule_provider") or {}
        self.state.rule_providers = self.get_data("extra_rule_providers") or {}
        self.state.ruleset_names = self.get_data("ruleset_names") or {}
        self.state.acl4ssr_providers = self.get_data("acl4ssr_providers") or {}
        self.state.clash_configs = self.get_data("clash_configs") or {}
        self.state.hosts = self.get_data("hosts") or []
        self.state.overwritten_region_groups = self.get_data("overwritten_region_groups") or {}
        self.state.overwritten_proxies = self.get_data("overwritten_proxies") or {}
        self.state.geo_rules = self.get_data("geo_rules") or {'geoip': [], 'geosite': []}

        if conf:
            try:
                raw_conf = PluginConfig.upgrade_conf(conf)
                self.config = PluginConfig.parse_obj(raw_conf)
            except ValidationError as e:
                logger.error(f"解析配置出错: {e}")
                return
        self._update_config()

        if self.config.enabled:
            self._initialize_plugin()

    def _initialize_plugin(self):
        self.state.proxies_manager.clear()
        self.state.top_rules_manager.clear()
        self.state.ruleset_rules_manager.clear()

        if ClashRuleProvider.event_loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = Scheduler().loop
            ClashRuleProvider.event_loop = loop
        self.scheduler = AsyncIOScheduler(timezone=settings.TZ, event_loop=ClashRuleProvider.event_loop)
        self.services = ClashRuleProviderService(self.__class__.__name__, self.config, self.state, self.store,
                                                 self.scheduler)
        self.api = ClashRuleProviderApi(self.services, self.config)

        try:
            self.state.clash_template_dict = yaml.load(self.config.clash_template, Loader=yaml.SafeLoader) or {}
            if not isinstance(self.state.clash_template_dict, dict):
                self.state.clash_template_dict = {}
                logger.error("Invalid clash template yaml")
        except yaml.YAMLError as exc:
            logger.error(f"Error loading clash template yaml: {exc}")
            self.state.clash_template_dict = {}

        # Normalize template
        for key, default in self.DEFAULT_CLASH_CONF.items():
            self.state.clash_template_dict.setdefault(key, copy.deepcopy(default))

        self.services.load_rules()
        self.services.load_proxies()

        self.state.subscription_info = {url: self.state.subscription_info.get(url) or {}
                                        for url in self.config.sub_links}
        for _, sub_info in self.state.subscription_info.items():
            sub_info.setdefault('enabled', True)
        self.state.clash_configs = {url: self.state.clash_configs[url] for url in self.config.sub_links if
                                    self.state.clash_configs.get(url)}

        for url, conf in self.state.clash_configs.items():
            self.services.add_proxies_to_manager(conf.get('proxies', []),
                                                 f"Sub:{UtilsProvider.get_url_domain(url)}-{abs(hash(url))}")
        self.services.add_proxies_to_manager(self.state.clash_template_dict.get('proxies', []), 'Template')

        self.services.check_proxies_lifetime()
        self._start_scheduler()

    def _start_scheduler(self):
        self.scheduler.start()
        now = datetime.now(tz=pytz.timezone(settings.TZ))
        self.scheduler.add_job(self.services.async_refresh_subscriptions, "date",
                               run_date=now + timedelta(seconds=2), misfire_grace_time=self.MISFIRE_GRACE_TIME)
        if self.config.hint_geo_dat:
            self.scheduler.add_job(self.services.async_refresh_geo_dat, "date",
                                   run_date=now + timedelta(seconds=3), misfire_grace_time=self.MISFIRE_GRACE_TIME)
        else:
            self.state.geo_rules = {'geoip': [], 'geosite': []}
        if self.config.enable_acl4ssr:
            self.scheduler.add_job(self.services.async_refresh_acl4ssr, "date",
                                   run_date=now + timedelta(seconds=4), misfire_grace_time=self.MISFIRE_GRACE_TIME)
        else:
            self.state.acl4ssr_providers = {}

    def get_state(self) -> bool:
        return self.config.enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return apis.get_routes(self.api) if self.api else []

    def get_render_mode(self) -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [], {}

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        components = [
            {"key": "clash_info", "name": "Clash Info"},
            {"key": "traffic_stats", "name": "Traffic Stats"}
        ]
        return [c for c in components if c.get("name") in self.config.dashboard_components]

    def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        clash_available = bool(self.config.dashboard_url and self.config.dashboard_secret)
        components = {'clash_info': {'title': 'Clash Info', 'md': 4},
                      'traffic_stats': {'title': 'Traffic Stats', 'md': 8}}
        col_config = {'cols': 12, 'md': components.get(key, {}).get('md', 4)}
        global_config = {
            'title': components.get(key, {}).get('title', 'Clash Info'),
            'border': True,
            'clash_available': clash_available,
            'secret': self.config.dashboard_secret,
        }
        return col_config, global_config, []

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        if self.scheduler:
            try:
                self.scheduler.remove_all_jobs()
                if self.scheduler.running:
                    self.scheduler.shutdown()
                self.scheduler = None
            except Exception as e:
                logger.error(f"退出插件失败：{e}")
        self.services = None
        self.api = None

    def get_service(self) -> List[Dict[str, Any]]:
        if self.get_state() and self.config.auto_update_subscriptions and self.config.sub_links:
            return [{
                "id": "ClashRuleProvider",
                "name": "定时更新订阅",
                "trigger": CronTrigger.from_crontab(self.config.cron_string),
                "func": self.refresh_subscription_service,
                "kwargs": {}
            }]
        return []

    async def refresh_subscription_service(self):
        if not self.config.sub_links:
            return
        res = await self.services.async_refresh_subscriptions()
        messages = []
        index = 1
        for url, result in res.items():
            host_name = UtilsProvider.get_url_domain(url) or url
            message = f"{index}. 「 {host_name} 」\n"
            index += 1
            if result:
                sub_info = self.state.subscription_info.get(url, {})
                if sub_info.get('total') is not None:
                    used = sub_info.get('download', 0) + sub_info.get('upload', 0)
                    remaining = sub_info.get('total', 0) - used
                    info = (
                        f"节点数量: {sub_info.get('proxy_num', 0)}\n"
                        f"已用流量: {UtilsProvider.format_bytes(used)}\n"
                        f"剩余流量: {UtilsProvider.format_bytes(remaining)}\n"
                        f"总量: {UtilsProvider.format_bytes(sub_info.get('total', 0))}\n"
                        f"过期时间: {UtilsProvider.format_expire_time(sub_info.get('expire', 0))}"
                    )
                else:
                    info = f"节点数量: {sub_info.get('proxy_num', 0)}\n"
                message += f"订阅更新成功\n{info}"
            else:
                message += '订阅更新失败'
            messages.append(message)
        if self.config.notify:
            self.post_message(title=f"【{self.plugin_name}】",
                              mtype=NotificationType.Plugin,
                              text='\n'.join(messages)
                              )

    def _update_config(self):
        conf = self.config.dict(by_alias=True)
        self.update_config(conf)

    def update_best_cf_ip(self, ips: List[str]):
        self.config.best_cf_ip = [*ips]
        conf = self.get_config()
        conf['best_cf_ip'] = self.config.best_cf_ip
        self.update_config(conf)

    @eventmanager.register(EventType.PluginAction)
    def update_cloudflare_ips_handler(self, event: Event = None):
        event_data = event.event_data
        if not event_data or event_data.get("action") != "update_cloudflare_ips":
            return
        ips = event_data.get("ips")
        if isinstance(ips, str):
            ips = [ips]
        if isinstance(ips, list):
            logger.info("更新 Cloudflare 优选 IP ...")
            self.update_best_cf_ip(ips)
