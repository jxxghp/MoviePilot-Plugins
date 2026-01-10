import pytz
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict, Tuple

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError

from app.api.endpoints.plugin import register_plugin_api
from app.core.config import settings, global_vars
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.string import StringUtils

from .api import ClashRuleProviderApi, apis
from .base import Constant
from .config import PluginConfig
from .helper.utilsprovider import UtilsProvider
from .models import ProxyGroup, ProxyGroups, RuleProviders, Hosts
from .models.api import SubscriptionsInfo
from .models.configuration import ClashConfig
from .models.datapatch import DataPatch
from .models.types import DataKey, DataSource
from .state import PluginState, GeoRules
from .services import ClashRuleProviderService


class ClashRuleProvider(_PluginBase):
    # 插件名称
    plugin_name = "Clash Rule Provider"
    # 插件描述
    plugin_desc = "随时为Clash添加一些额外的规则。"
    # 插件图标
    plugin_icon = "Mihomo_Meta_A.png"
    # 插件版本
    plugin_version = "2.1.2"
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

    # Runtime variables
    services: ClashRuleProviderService
    api: ClashRuleProviderApi
    state: PluginState
    scheduler: AsyncIOScheduler | None = None

    def init_plugin(self, conf: dict = None):
        self.stop_service()
        self.state = PluginState(self.__class__.__name__)
        self.upgrade_data()

        if conf:
            try:
                self.state.config = PluginConfig.model_validate(conf)
            except ValidationError as e:
                logger.error(f"解析配置出错: {e}")
                return
        self._update_config()

        if self.state.config.enabled:
            self._initialize_plugin()

    def upgrade_data(self):
        data_version = self.get_data(DataKey.DATA_VERSION) or "2.0.10"
        if StringUtils.compare_version(data_version, '<', "2.1.0"):
            from .helper.dataupgrader import v_2_1_0
            v_2_1_0.upgrade(self.__class__.__name__)

    def _initialize_plugin(self):
        self.state.top_rules_manager.clear()
        self.state.ruleset_rules_manager.clear()

        self.scheduler = AsyncIOScheduler(timezone=settings.TZ, event_loop=global_vars.loop)
        self.services = ClashRuleProviderService(self.__class__.__name__, self.state, self.scheduler)
        self.api = ClashRuleProviderApi(self.services, self.state.config)

        try:
            clash_template_dict = yaml.load(self.state.config.clash_template, Loader=yaml.SafeLoader) or {}
            if isinstance(clash_template_dict, dict):
                self.state.clash_template = ClashConfig.model_validate(clash_template_dict)
            else:
                logger.error("Invalid clash template yaml")
        except yaml.YAMLError as exc:
            logger.error(f"Error loading clash template yaml: {exc}")
        except Exception as ve:
            logger.error(f"Error validating clash template config: {ve}")

        self.services.load_rules()

        # Accessing subscription_info property triggers load from DB.
        sub_info_map = self.state.subscription_info
        sub_info_map.update(self.state.config.sub_links)
        self.state.subscription_info = sub_info_map

        # sub_configs loaded from DB. Filter by current sub_links.
        sub_configs_map = self.state.sub_configs
        sub_configs_map = {url: sub_configs_map[url] for url in self.state.config.sub_links if sub_configs_map.get(url)}
        self.state.sub_configs = sub_configs_map

        self.services.check_patch_lifetime()
        self._start_scheduler()

    def _start_scheduler(self):
        self.scheduler.start()
        now = datetime.now(tz=pytz.timezone(settings.TZ))
        self.scheduler.add_job(self.services.async_refresh_subscriptions, "date",
                               run_date=now + timedelta(seconds=2), misfire_grace_time=Constant.MISFIRE_GRACE_TIME)
        if self.state.config.hint_geo_dat:
            self.scheduler.add_job(self.services.async_refresh_geo_dat, "date",
                                   run_date=now + timedelta(seconds=3), misfire_grace_time=Constant.MISFIRE_GRACE_TIME)

        if self.state.config.enable_acl4ssr:
            self.scheduler.add_job(self.services.async_refresh_acl4ssr, "date",
                                   run_date=now + timedelta(seconds=4), misfire_grace_time=Constant.MISFIRE_GRACE_TIME)

    def get_state(self) -> bool:
        return self.state.config.enabled

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
        return [c for c in components if c.get("name") in self.state.config.dashboard_components]

    def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        clash_available = bool(self.state.config.dashboard_url and self.state.config.dashboard_secret)
        components = {'clash_info': {'title': 'Clash Info', 'md': 4},
                      'traffic_stats': {'title': 'Traffic Stats', 'md': 8}}
        col_config = {'cols': 12, 'md': components.get(key, {}).get('md', 4)}
        global_config = {
            'title': components.get(key, {}).get('title', 'Clash Info'),
            'border': True,
            'clash_available': clash_available,
            'secret': self.state.config.dashboard_secret,
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
            except Exception as e:
                logger.error(f"退出插件失败：{e}")

    def get_service(self) -> List[Dict[str, Any]]:
        if self.get_state() and self.state.config.auto_update_subscriptions and self.state.config.sub_links:
            return [{
                "id": "ClashRuleProvider",
                "name": "定时更新订阅",
                "trigger": CronTrigger.from_crontab(self.state.config.cron_string),
                "func": self.refresh_subscription_service,
                "kwargs": {}
            }]
        return []

    async def refresh_subscription_service(self):
        if not self.state.config.sub_links:
            return
        res = await self.services.async_refresh_subscriptions()
        messages = []
        index = 1
        for url, result in res.items():
            host_name = UtilsProvider.get_url_domain(url) or url
            message = f"{index}. 「 {host_name} 」\n"
            index += 1
            if result:
                sub_info = self.state.subscription_info.get(url)
                if sub_info.total:
                    used = sub_info.download + sub_info.upload
                    remaining = sub_info.total- used
                    info = (
                        f"节点数量: {sub_info.proxy_num}\n"
                        f"已用流量: {UtilsProvider.format_bytes(used)}\n"
                        f"剩余流量: {UtilsProvider.format_bytes(remaining)}\n"
                        f"总量: {UtilsProvider.format_bytes(sub_info.total)}\n"
                        f"过期时间: {UtilsProvider.format_expire_time(sub_info.expire)}"
                    )
                else:
                    info = f"节点数量: {sub_info.proxy_num}\n"
                message += f"订阅更新成功\n{info}"
            else:
                message += '订阅更新失败'
            messages.append(message)
        if self.state.config.notify:
            self.post_message(
                title=f"【{self.plugin_name}】", mtype=NotificationType.Plugin, text='\n'.join(messages)
            )

    def _update_config(self):
        conf = self.state.config.model_dump(by_alias=True)
        self.update_config(conf)

    def update_best_cf_ip(self, ips: List[str]):
        self.state.config.best_cf_ip = [*ips]
        conf = self.get_config()
        conf['best_cf_ip'] = self.state.config.best_cf_ip
        self.update_config(conf)

    @eventmanager.register(EventType.PluginAction)
    def update_cloudflare_ips_handler(self, event: Event):
        event_data = event.event_data
        if not event_data or event_data.get("action") != "update_cloudflare_ips":
            return
        ips = event_data.get("ips")
        if isinstance(ips, str):
            ips = [ips]
        if isinstance(ips, list):
            logger.info("更新 Cloudflare 优选 IP ...")
            self.update_best_cf_ip(ips)

    @eventmanager.register(EventType.PluginReload)
    def reload(self, event):
        """
        响应插件重载事件
        """
        plugin_id = event.event_data.get("plugin_id")
        if plugin_id == self.__class__.__name__:
            logger.info("正在注册 API ...")
            register_plugin_api(plugin_id=plugin_id)
