import asyncio
import hashlib
import json
import pytz
import re
import time
import yaml
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Iterable, TypeVar

import jsonpatch
from fastapi import HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.cache import cached
from app.core.config import settings
from app.log import logger
from app.utils.http import AsyncRequestUtils

from .base import Constant
from .helper.clashruleparser import ClashRuleParser, RoutingRuleType, Action
from .helper.configconverter import Converter
from .helper.utilsprovider import UtilsProvider
from .models import ProxyGroup, Proxy, RuleProvider, RuleProviderData, ProxyData, HostData, VehicleType, SelectGroup, \
    ProxyGroupData, RuleItem, RuleData, Metadata, RuleProviders
from .models.api import ClashApi, SubscriptionSetting, DataUsage, SubscriptionInfo, ConfigRequest
from .models.configuration import ClashConfig
from .models.datapatch import PatchItem, DataPatch
from .models.rule import RuleType
from .models.types import DataSource, DataKey, RuleSet, ClashKey, SupportsPatch
from .state import PluginState


T = TypeVar("T")

class ClashRuleProviderService:

    def __init__(
            self, plugin_id: str,
            state: PluginState,
            scheduler: Optional[AsyncIOScheduler] = None
    ):
        self.plugin_id = plugin_id
        self.state = state
        self.scheduler = scheduler

    def save_rules(self):
        self.state.save_data(DataKey.TOP_RULES, self.state.top_rules_manager.export_rules())
        self.state.save_data(DataKey.RULESET_RULES, self.state.ruleset_rules_manager.export_rules())

    def load_rules(self):
        self.state.top_rules_manager.import_rules(self.state.get_data(DataKey.TOP_RULES) or [])
        self.state.ruleset_rules_manager.import_rules(self.state.get_data(DataKey.RULESET_RULES) or [])

    def _make_proxy_patch(self, src: Proxy, dst: Proxy):
        src_dict = src.model_dump(mode="json", by_alias=True, exclude_none=True)
        dst_dict = dst.model_dump(mode="json", by_alias=True, exclude_none=True)
        patch = jsonpatch.make_patch(src_dict, dst_dict)
        patches = self.state.proxy_patch
        patches[src.name] = PatchItem(patch=patch.to_string(), lifecycle=Constant.PATCH_LIFESPAN)
        self.state.proxy_patch = patches

    def _apply_patch(self, item: SupportsPatch[T], name: str, patch: DataPatch) -> T:
        try:
            if name in patch:
                return item.patch(patch[name].patch)
        except Exception as err:
            logger.error(f"Failed to apply patch for {name}: {repr(err)}")
        return item

    def _apply_patches(self, items: list[Any], patches: DataPatch) -> list[Any]:
        for item in items:
            item.data = self._apply_patch(item.data, item.name, patches)
            item.meta.patched = item.name in patches
        return items

    def _apply_patch_to_config(self, conf: ClashConfig) -> ClashConfig:
        conf.proxies = [self._apply_patch(proxy, proxy.name, self.state.proxy_patch) for proxy in conf.proxies]
        conf.proxy_groups = [self._apply_patch(pg, pg.name, self.state.proxy_group_patch) for pg in conf.proxy_groups]
        return conf

    def _merge_subscriptions(self, config: ClashConfig):
        subscriptions_config = self.state.config.subscriptions_config
        subscription_info = self.state.subscription_info

        for conf in subscriptions_config:
            if not subscription_info.get(conf.url).enabled:
                continue
            sub_config = self.state.get_sub_config(conf.url)
            config.merge(sub_config)

    def _filter_available_items(self, items: Iterable[Any], param: ConfigRequest) -> list[Any]:
        return [item.data for item in items if item.meta.available(param)]

    def _process_auto_rule_providers(self, config: ClashConfig):
        auto_rule_provider = {}
        ruleset_names = self.state.ruleset_names

        for r in self.state.ruleset_rules_manager.rules:
            rule = r.rule
            rule_provider_name = f'{self.state.config.ruleset_prefix}{rule.action}'
            if rule_provider_name not in auto_rule_provider:
                path_name = hashlib.sha256(rule.action.encode('utf-8')).hexdigest()[:10]
                ruleset_names[path_name] = rule_provider_name
                sub_url = (f"{self.state.config.movie_pilot_url}/api/v1/plugin/{self.plugin_id}/ruleset?"
                           f"name={path_name}&apikey={self.state.config.apikey or settings.API_TOKEN}")
                auto_rule_provider[rule_provider_name] = RuleProvider(
                    type=VehicleType.HTTP, behavior="classical", url=sub_url, path=f"./CRP/{path_name}.yaml",
                    interval=3600, format="yaml"
                )
        config.rule_providers = config.rule_providers | auto_rule_provider
        self.state.rule_provider = auto_rule_provider
        self.state.ruleset_names = ruleset_names

    def _process_rules(self, config: ClashConfig, param: ConfigRequest):
        top_rules: list[RuleType] = []
        acl4ssr_providers_map: dict[str, RuleProvider] = {}
        acl4ssr_data = self.state.acl4ssr_providers

        for r in self.state.top_rules_manager:
            if not r.meta.available(param):
                continue
            rule = r.rule
            if rule.rule_type == RoutingRuleType.RULE_SET:
                if rule.payload in acl4ssr_data:
                    acl4ssr_providers_map[rule.payload] = acl4ssr_data.get(rule.payload).data
            top_rules.append(rule)
        config.rule_providers = config.rule_providers | acl4ssr_providers_map
        config.rules = top_rules + config.rules

    def _cleanup_ruleset_names(self, config: ClashConfig):
        ruleset_names = self.state.ruleset_names
        key_to_delete = [key for key, item in ruleset_names.items() if item not in config.rule_providers]
        for key in key_to_delete:
            del ruleset_names[key]
        self.state.ruleset_names = ruleset_names

    def _check_cycles(self, config: ClashConfig):
        proxy_graph = self._build_graph(config)
        cycles = UtilsProvider.find_cycles(proxy_graph)
        if cycles:
            logger.warn("发现代理组回环：")
            for cycle in cycles:
                logger.warn(" -> ".join(cycle))

    def _make_proxy_group_patch(self, src: ProxyGroup, dst: ProxyGroup):
        src_dict = src.model_dump(mode="json", by_alias=True, exclude_none=True)
        dst_dict = dst.model_dump(mode="json", by_alias=True, exclude_none=True)
        patch = jsonpatch.make_patch(src_dict, dst_dict)

        # Flatten list patches to full replace to avoid index shift issues
        new_ops = []
        replaced_paths = set()
        list_fields = ["/proxies", "/use"]

        for op in patch.patch:
            path = op["path"]
            matched_list = next((f for f in list_fields if path == f or path.startswith(f + '/')), None)
            if matched_list:
                if matched_list not in replaced_paths:
                    field_name = matched_list.strip('/')
                    val = dst_dict.get(field_name)
                    if val is None:
                        # Removed in dst
                        new_ops.append({"op": "remove", "path": matched_list})
                    elif field_name not in src_dict:
                        # Not in src, added in dst
                        new_ops.append({"op": "add", "path": matched_list, "value": val})
                    else:
                        # In src and dst, replacing
                        new_ops.append({"op": "replace", "path": matched_list, "value": val})
                    replaced_paths.add(matched_list)
            else:
                new_ops.append(op)

        patch.patch = new_ops
        pg_patches = self.state.proxy_group_patch
        pg_patches[src.name] = PatchItem(patch=patch.to_string(), lifecycle=Constant.PATCH_LIFESPAN)
        self.state.proxy_group_patch = pg_patches

    def organize_and_save_rules(self):
        self.sync_ruleset()
        self.save_rules()

    def ruleset(self, ruleset: str) -> List[str]:
        if not ruleset.startswith(self.state.config.ruleset_prefix):
            return []
        action = ruleset[len(self.state.config.ruleset_prefix):]
        try:
            final_action = Action(action.upper())
        except ValueError:
            final_action = action
        rules = self.state.ruleset_rules_manager.filter_rules_by_action(final_action)
        return [rule.rule.condition_string() for rule in rules]

    def sync_ruleset(self):
        outbounds = set()
        new_outbounds = set()
        manager = self.state.top_rules_manager

        manager.remove_rules_by_lambda(
            lambda r: r.rule.rule_type == RoutingRuleType.RULE_SET and
                      r.meta.source == DataSource.AUTO and
                      r.rule.payload != f"{self.state.config.ruleset_prefix}{r.rule.action}"
        )
        rules_existed = manager.filter_rules_by_condition(
            lambda r: r.meta.source == DataSource.AUTO and r.rule.rule_type == RoutingRuleType.RULE_SET
        )
        actions_existed = {r.rule.action for r in rules_existed}

        for r in self.state.ruleset_rules_manager:
            if r.meta.disabled:
                continue
            outbounds.add(r.rule.action)
            if r.rule.action not in actions_existed:
                new_outbounds.add(r.rule.action)

        manager.remove_rules_by_lambda(
            lambda r: r.rule.rule_type == RoutingRuleType.RULE_SET and
                      r.meta.source == DataSource.AUTO and
                      (r.rule.action not in outbounds)
        )

        for outbound in new_outbounds:
            clash_rule = ClashRuleParser.parse_rule_line(
                f"RULE-SET,{self.state.config.ruleset_prefix}{outbound},{outbound}")
            if clash_rule is None:
                continue
            rule = RuleItem(rule=clash_rule, meta=Metadata(source=DataSource.AUTO))
            if not manager.has_rule_item(rule):
                manager.insert_rule_at_priority(rule, 0)

    def append_top_rules(self, rules: List[str]):
        clash_rules = []
        for rule in rules:
            clash_rule = ClashRuleParser.parse_rule_line(rule)
            if clash_rule:
                clash_rules.append(RuleItem(rule=clash_rule, meta=Metadata(source=DataSource.MANUAL)))
        self.state.top_rules_manager.append_rules(clash_rules)
        self.state.save_data(DataKey.TOP_RULES, self.state.top_rules_manager.export_rules())

    def clash_outbound(self) -> list[str]:
        outbound = [pg_data.data.name for pg_data in self.state.proxy_groups_from_subs()]
        if self.state.clash_template:
            outbound.extend(pg.name for pg in self.state.clash_template.proxy_groups)
        if self.state.config.group_by_region or self.state.config.group_by_country:
            outbound.extend(pg.name for pg in self.proxy_groups_by_region())
        outbound.extend(pg.data.name for pg in self.state.proxy_groups)
        outbound.extend(pg.data.name for pg in self.get_proxies())
        return outbound

    def delete_proxy(self, name: str) -> Tuple[bool, str]:
        proxies = self.state.proxies
        deleted = proxies.pop(name)
        if deleted:
            self.state.proxies = proxies
            return True, "代理删除成功"
        return False, f"代理 {name!r} 不存在"

    def delete_proxy_patch(self, name: str) -> tuple[bool, str]:
        patches = self.state.proxy_patch
        if name in patches:
            del patches.root[name]
            self.state.proxy_patch = patches
            return True, "补丁已删除"
        return False, "补丁不存在"

    def import_proxies(self, vehicle: str, payload: str) -> tuple[bool, str]:
        proxies = []
        if vehicle == 'LINK':
            links = payload.strip().splitlines()
            proxies = list(Converter().convert_v2ray(links, skip_exception=True, logger=logger).items())
        elif vehicle == 'YAML':
            try:
                imported = yaml.load(payload, Loader=yaml.SafeLoader)
                if not isinstance(imported, dict):
                    return False, "无效的输入"
            except yaml.YAMLError as err:
                logger.error(f"Failed to import rules: {repr(err)}")
                return False, 'YAML 格式错误'
            proxies = [(None, p) for p in (imported.get(DataKey.PROXIES) or [])]
        if not proxies:
            return False, "无可用节点"
        success_count = 0
        error_messages = ''
        success = True
        ps = self.state.proxies
        for item in proxies:
            try:
                proxy = Proxy.model_validate(item[1])
                meta = Metadata(source=DataSource.MANUAL)
                pd = ProxyData(data=proxy, name=proxy.name, meta=meta, raw=item[0], v2ray_link=item[0])
                if not pd.v2ray_link:
                    try:
                        pd.v2ray_link = Converter.convert_to_share_link(item[1])
                    except Exception as err:
                        logger.debug(f"Failed to convert proxy link: {repr(err)}")
                ps.add(pd)
                success_count += 1
            except Exception as err:
                success = False
                error_messages += f"{err}\n"
        message = f"导入 {success_count}/{len(proxies)} 个代理节点. \n{error_messages}"
        self.state.proxies = ps
        return success, message

    def update_proxy(self, previous_name: str, source: str, proxy: Proxy) -> tuple[bool, str]:
        if source == DataSource.MANUAL:
            proxies = self.state.proxies
            proxies.update(previous_name, ProxyData(data=proxy, name=proxy.name, meta=Metadata()))
            self.state.proxies = proxies
            return True, "代理更新成功"
        if previous_name != proxy.name:
            return False, "请勿修改代理名称"
        proxies = list(self.state.proxies_from_subs())
        src = next((g for g in proxies if g.name == previous_name), None)
        if src is None:
            return False, f"代理组 {previous_name!r} ({source}) 不存在"
        self._make_proxy_patch(src.data, proxy)
        return True, "代理更新成功"

    def update_proxy_meta(self, name: str, meta: Metadata) -> tuple[bool, str]:
        proxies = self.state.proxies
        if name not in proxies:
            return False, f"The proxy name {name} does not exist"
        proxies.set_meta(name, meta)
        self.state.proxies = proxies
        return True, ''

    def get_proxies(self, patched: bool = True) -> list[ProxyData]:
        proxies = self.state.all_proxies
        proxies = list(
            filter(lambda p: not any(keyword in p.data.name for keyword in self.state.config.filter_keywords), proxies)
        )
        if not patched:
            return proxies
        return self._apply_patches(proxies, self.state.proxy_patch)

    @cached(maxsize=1, ttl=86400, skip_empty=True)
    def _get_countries_data(self) -> List[Dict[str, str]]:
        file_path = settings.ROOT_PATH / 'app' / 'plugins' / self.plugin_id.lower() / 'countries.json'
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载国家/地区文件错误：{e}")
            return []

    def proxy_groups_by_region(self) -> list[ProxyGroupData]:
        countries = self._get_countries_data()
        proxies = self.get_proxies()
        return self._group_by_region(
            countries, proxies, self.state.config.group_by_region, self.state.config.group_by_country
        )

    @cached(maxsize=2, ttl=86400)
    def _group_by_region(self, countries: list[dict[str, str]], proxies: list[ProxyData], group_by_continent: bool,
                         group_by_country: bool) -> list[ProxyGroupData]:
        continent_groups = {}
        country_groups = {}
        continent_map = {
            '欧洲': 'Europe', '亚洲': 'Asia', '大洋洲': 'Oceania', '非洲': 'Africa',
            '北美洲': 'NorthAmerica', '南美洲': 'SouthAmerica'
        }
        proxy_groups: list[ProxyGroup] = []
        hk = next((c for c in countries if c['abbr'] == 'HK'), {})
        tw = next((c for c in countries if c['abbr'] == 'TW'), {})

        for proxy_data in proxies:
            proxy_node = proxy_data.data
            country = ClashRuleProviderService._country_from_node(countries, proxy_node.name)
            if not country:
                continue
            if country.get("abbr") == "CN":
                if any(key in proxy_node.name for key in ("🇭🇰", "HK", "香港")):
                    country = hk
                if any(key in proxy_node.name for key in ("🇹🇼", "TW", "台湾")):
                    country = tw
            continent = continent_map.get(country["continent"])
            if continent and group_by_continent:
                continent_groups.setdefault(continent, []).append(proxy_node.name)
            if group_by_country:
                country_groups.setdefault(f"{country.get('emoji')} {country.get('chinese')}", []).append(
                    proxy_node.name)
        for continent, nodes in continent_groups.items():
            if nodes:
                proxy_groups.append(ProxyGroup(root=SelectGroup(name=continent, proxies=nodes)))

        excluded = ('中国', '香港', 'CN', 'HK', '🇨🇳', '🇭🇰')
        for continent_node in continent_groups.get('Asia', []):
            if any(x in continent_node for x in excluded):
                continue
            continent_groups.setdefault('AsiaExceptChina', []).append(continent_node)
        if continent_groups.get('AsiaExceptChina'):
            pg = SelectGroup(name="AsiaExceptChina", proxies=continent_groups['AsiaExceptChina'])
            proxy_groups.append(ProxyGroup(root=pg))
        for country, nodes in country_groups.items():
            if len(nodes):
                proxy_groups.append(ProxyGroup(root=SelectGroup(name=country, proxies=nodes)))
        country_group = list(country_groups.keys())
        if country_group:
            proxy_groups.append(ProxyGroup(root=SelectGroup(name="🏴‍☠️国家分组", proxies=country_group)))
        ret = [ProxyGroupData(name=p.name, data=p, meta=Metadata(source=DataSource.AUTO)) for p in proxy_groups]
        return ret

    @staticmethod
    def _country_from_node(countries: List[Dict[str, str]], node_name: str) -> Optional[Dict[str, str]]:
        node_name_lower = node_name.lower()
        for country in countries:
            if country.get('emoji') and country['emoji'] in node_name:
                return country
            if (
                    (country.get('chinese') and country['chinese'] in node_name) or
                    (country.get('english') and country['english'].lower() in node_name_lower)
            ):
                return country
        return None

    @staticmethod
    def _build_graph(config: ClashConfig) -> Dict[str, Any]:
        """构建代理组有向图"""
        graph = {}
        groups = config.proxy_groups
        group_names = {g.name for g in groups}
        for group in groups:
            proxies = group.proxies
            graph[group.name] = [p for p in proxies if p in group_names]
        return graph

    async def fetch_clash_data(self, endpoint: str) -> Dict:
        headers = {"Authorization": f"Bearer {self.state.config.dashboard_secret}"}
        url = f"{self.state.config.dashboard_url}/{endpoint}"
        response = await AsyncRequestUtils().get_json(url, headers=headers, timeout=10)
        if response is None:
            raise HTTPException(status_code=502, detail=f"Failed to fetch {endpoint}")
        return response

    def get_subscription_user_info(self) -> DataUsage:
        sub_info = DataUsage()
        for info in self.state.subscription_info.root.values():
            sub_info.upload += info.upload
            sub_info.download += info.download
            sub_info.total += info.total
            sub_info.expire = max(sub_info.expire, info.expire)
        return sub_info

    @staticmethod
    async def async_notify_clash(ruleset: str, api_url: str, api_secret: str):
        """
        通知 Clash 刷新规则集
        """
        logger.info(f"正在刷新 [{ruleset}] {api_url} ...")
        url = f'{api_url}/providers/rules/{ruleset}'
        resp = await AsyncRequestUtils(content_type="application/json",
                                       headers={"authorization": f"Bearer {api_secret}"}
                                       ).put_res(url)
        if resp and resp.status_code == 204:
            logger.info(f"[{ruleset}] {api_url} 刷新完成")
        else:
            logger.warn(f"[{ruleset}] {api_url} 刷新失败")

    def add_notification_job(self, ruleset_names: List[str]):
        if not self.state.config.enabled or not self.scheduler:
            return
        for ruleset in ruleset_names:
            if ruleset in self.state.rule_provider:
                self.scheduler.add_job(
                    ClashRuleProviderService.async_notify_clash, "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) +
                             timedelta(seconds=self.state.config.refresh_delay),
                    args=(ruleset, self.state.config.dashboard_url,
                          self.state.config.dashboard_secret),
                    id=f'CRP-notify-clash{ruleset}', replace_existing=True,
                    misfire_grace_time=Constant.MISFIRE_GRACE_TIME
                )

    def build_clash_config(self, param: ConfigRequest) -> ClashConfig | None:
        if not self.state.clash_template:
            config = ClashConfig()
        else:
            config = self.state.clash_template.model_copy(deep=True)

        # Merge subscriptions
        self._merge_subscriptions(config)

        # Add proxies
        config.proxies += self._filter_available_items(self.state.proxies, param)
        config.proxies = list(
            filter(lambda p: not any(kw in p.name for kw in self.state.config.filter_keywords), config.proxies)
        )
        # Add proxy groups
        config.proxy_groups += self._filter_available_items(self.state.proxy_groups, param)

        # Add region groups
        if self.state.config.group_by_region or self.state.config.group_by_country:
            config.proxy_groups += [pg.data for pg in self.proxy_groups_by_region()]

        # Add rule providers (Load once)
        current_rule_providers = self.state.rule_providers
        rule_providers = {}
        for rp_data in current_rule_providers:
            if rp_data.meta.available(param):
                rule_providers[rp_data.name] = rp_data.data
        config.rule_providers = config.rule_providers | rule_providers

        # Apply patches
        config = self._apply_patch_to_config(config)

        # Sync and add auto rule providers
        self.sync_ruleset()
        self._process_auto_rule_providers(config)

        # Add rules (including ACL4SSR)
        self._process_rules(config, param)

        # Add Hosts
        hosts = self.state.hosts.to_dict(self.state.config.best_cf_ip)
        if hosts:
            config.hosts = config.hosts or {}
            config.hosts = config.hosts | hosts

        # Cleanup ruleset names
        self._cleanup_ruleset_names(config)

        # Cycle check
        self._check_cycles(config)

        return config

    def delete_proxy_group(self, name: str) -> Tuple[bool, str]:
        """
        Deletes a proxy group by name and saves the state.
        Returns True if a group was deleted, False otherwise.
        """
        pgs = self.state.proxy_groups
        deleted = pgs.pop(name)
        if deleted:
            self.state.proxy_groups = pgs
            return True, "代理组删除成功"
        return False, f"代理组 {name!r} 不存在"

    def delete_proxy_group_patch(self, name: str) -> tuple[bool, str]:
        patches = self.state.proxy_group_patch
        if name in patches:
            del patches.root[name]
            self.state.proxy_group_patch = patches
            return True, "补丁已删除"
        return False, "补丁不存在"

    def update_proxy_group_meta(self, name: str, meta: Metadata) -> tuple[bool, str]:
        pgs = self.state.proxy_groups
        res = pgs.set_meta(name, meta)
        if res:
            self.state.proxy_groups = pgs
            return True, ""
        return False, f"代理组 {name!r} 不存在"

    def add_proxy_group(self, proxy_group: ProxyGroup) -> tuple[bool, str]:
        """
        Adds a new proxy group, saves the state, and returns status.
        """
        try:
            pgs = self.state.proxy_groups
            pgs.add(ProxyGroupData(data=proxy_group, name=proxy_group.name, meta=Metadata(source=DataSource.MANUAL)))
            self.state.proxy_groups = pgs
        except Exception as e:
            logger.error(f"Failed to add proxy group: {repr(e)}")
            return False, "代理组添加失败"
        return True, "代理组添加成功"

    def get_proxy_groups(self, patched = True) -> list[ProxyGroupData]:
        pgs = self.state.all_proxy_groups
        pgs += self.proxy_groups_by_region()
        if not patched:
            return pgs
        return self._apply_patches(pgs, self.state.proxy_group_patch)

    def update_proxy_group(self, previous_name: str, source: str, proxy_group: ProxyGroup) -> tuple[bool, str]:
        if source == DataSource.MANUAL:
            pgs = self.state.proxy_groups
            pgs.update(previous_name, ProxyGroupData(data=proxy_group, name=proxy_group.name, meta=Metadata()))
            self.state.proxy_groups = pgs
            return True, "代理组更新成功"
        if previous_name != proxy_group.name:
            return False, "请勿修改代理组名称"
        pgs = self.proxy_groups_by_region()
        src = next((g for g in pgs if g.name == previous_name), None)
        if src is None:
            return False, f"代理组 {previous_name!r} ({source}) 不存在"
        self._make_proxy_group_patch(src.data, proxy_group)
        return True, "代理组更新成功"

    def update_rule_provider(self, name: str, rule_provider: RuleProviderData) -> Tuple[bool, str]:
        """
        Updates a rule provider.
        """
        rps = self.state.rule_providers
        if name not in rps:
            return False, f"规则集 {name!r} 不存在"
        rps.update(name, rule_provider)
        self.state.rule_providers = rps
        return True, "规则集更新成功"

    def update_rule_providers_meta(self, name: str, meta: Metadata) -> tuple[bool, str]:
        rps = self.state.rule_providers
        if name in rps:
            res = rps.set_meta(name, meta)
            if res:
                self.state.rule_providers = rps
                return True, ""

        arps = self.state.acl4ssr_providers
        if name in arps:
            res = arps.set_meta(name, meta)
            if res:
                self.state.acl4ssr_providers = arps
                return True, ""
        return False, f"规则集 {name!r} 不存在"

    def update_rule_meta(self, rule_type: RuleSet, priority: int, meta: Metadata) -> tuple[bool, str]:
        manager = self.state.get_rule_manager(rule_type)
        rule = manager.get_rule_at_priority(priority)
        if not rule:
            return False, "规则不存在"
        res = manager.update_rule_meta_at_priority(priority, meta)
        if res:
            if rule_type == RuleSet.RULESET:
                self.add_notification_job([f"{self.state.config.ruleset_prefix}{rule.rule.action}"])
            self.organize_and_save_rules()
            return True, ""
        return False, "更新规则元数据失败"

    def delete_rule_provider(self, name: str) -> tuple[bool, str]:
        rps = self.state.rule_providers
        deleted = rps.pop(name)
        if deleted:
            self.state.rule_providers = rps
            return True, f"规则集删除成功"
        return False, f"规则集 {name!r} 不存在"

    def add_rule_provider(self, name: str, rule_provider: RuleProvider) -> tuple[bool, str]:
        try:
            rps = self.state.rule_providers
            rps.add(RuleProviderData(data=rule_provider, name=name, meta=Metadata(source=DataSource.MANUAL)))
            self.state.rule_providers = rps
        except Exception as e:
            logger.error(f"Failed to add rule provider: {repr(e)}")
            return False, "规则集添加失败"
        return True, "规则集添加成功"

    async def test_connectivity(self, clash_apis: List[ClashApi], sub_links: List[str]) -> Tuple[bool, str]:
        tasks = []
        urls = []
        for d in clash_apis:
            headers = {"authorization": f"Bearer {d.secret}"}
            url = f"{d.url}/version"
            task = asyncio.create_task(
                AsyncRequestUtils(accept_type="application/json", headers=headers, timeout=5).get_res(url)
            )
            urls.append(url)
            tasks.append(task)
        for sub_link in sub_links:
            task = asyncio.create_task(
                AsyncRequestUtils(
                    accept_type="text/html", proxies=settings.PROXY if self.state.config.proxy else None,
                    timeout=5).get(sub_link)
            )
            urls.append(sub_link)
            tasks.append(task)
        results = await asyncio.gather(*tasks)
        for i, result in enumerate(results):
            if not result:
                return False, f"无法连接到 {urls[i]}"
        return True, ""

    def get_status(self) -> Dict[str, Any]:
        data = {
            "state": self.state.config.enabled,
            "ruleset_prefix": self.state.config.ruleset_prefix,
            "preset_identifiers": self.state.config.identifiers,
            "best_cf_ip": self.state.config.best_cf_ip,
            "geoRules": self.state.geo_rules,
            "subscription_info": self.state.subscription_info,
            "sub_url": f"{self.state.config.movie_pilot_url}/api/v1/plugin/{self.plugin_id}/config?"
                       f"apikey={self.state.config.apikey or settings.API_TOKEN}"
        }
        return data

    def get_rules(self, ruleset: RuleSet) -> list[RuleData]:
        manager = self.state.get_rule_manager(ruleset)
        return manager.to_list()

    def reorder_rules(self, rule_type: RuleSet, moved_priority: int, target_priority: int) -> tuple[bool, str]:
        manager = self.state.get_rule_manager(rule_type)
        try:
            rule = manager.reorder_rules(moved_priority, target_priority)
            if rule_type == RuleSet.RULESET:
                self.add_notification_job(
                    [f"{self.state.config.ruleset_prefix}{rule.rule.action}"])
        except Exception as e:
            logger.info(f"Failed to reorder rules: {repr(e)}")
            return False, "规则移动失败"
        self.organize_and_save_rules()
        return True, ""

    def update_rule(self, rule_type: RuleSet, priority: int, rule_data: RuleData) -> tuple[bool, str]:
        try:
            dst_priority = rule_data.priority
            src_priority = priority
            clash_rule = ClashRuleParser.parse_rule_dict(rule_data.model_dump(mode='json', exclude_none=True))
            if not clash_rule:
                return False, f"无效的规则: {rule_data!r}"
            manager = self.state.get_rule_manager(rule_type)
            original_rule = manager.get_rule_at_priority(src_priority)
            meta = Metadata(source=original_rule.meta.source, time_modified=time.time())
            rule_item = RuleItem(rule=clash_rule, meta=meta)
            if rule_type == RuleSet.RULESET:
                res = manager.update_rule_at_priority(rule_item, src_priority, dst_priority)
                if res:
                    ruleset_to_notify = [f"{self.state.config.ruleset_prefix}{clash_rule.action}"]
                    if rule_data.action != original_rule.rule.action:
                        ruleset_to_notify.append(f"{self.state.config.ruleset_prefix}{original_rule.rule.action}")
                    self.add_notification_job(ruleset_to_notify)
            else:
                res = manager.update_rule_at_priority(rule_item, src_priority, dst_priority)
        except Exception as err:
            logger.info(f"Failed to update rules: {repr(err)}")
            return False, "更新规则出错"
        self.organize_and_save_rules()
        return res, ""

    def add_rule(self, rule_type: RuleSet, rule_data: RuleData) -> tuple[bool, str]:
        try:
            priority = rule_data.priority
            clash_rule = ClashRuleParser.parse_rule_dict(rule_data.model_dump(mode='json', exclude_none=True))
            if not clash_rule:
                return False, f"无效的输入规则: {rule_data.model_dump(mode='json', exclude_none=True)}"
            meta = Metadata(source=DataSource.MANUAL, time_modified=time.time())
            rule_item = RuleItem(rule=clash_rule, meta=meta)
            if rule_type == RuleSet.RULESET:
                self.state.ruleset_rules_manager.insert_rule_at_priority(rule_item, priority)
                self.add_notification_job([f"{self.state.config.ruleset_prefix}{clash_rule.action}"])
            else:
                self.state.top_rules_manager.insert_rule_at_priority(rule_item, priority)
        except Exception as err:
            logger.info(f"Failed to add rule: {repr(err)}")
            return False, "添加规则出错"
        self.organize_and_save_rules()
        return True, ""

    def delete_rule(self, ruleset: RuleSet, priority: int):
        manager = self.state.get_rule_manager(ruleset)
        res = manager.remove_rule_at_priority(priority)
        if ruleset == RuleSet.RULESET:
            if res:
                self.add_notification_job([f"{self.state.config.ruleset_prefix}{res.rule.action}"])
        self.organize_and_save_rules()

    def delete_rules(self, ruleset: RuleSet, priorities: list[int]):
        manager = self.state.get_rule_manager(ruleset)
        removed = manager.remove_rules_at_priorities(priorities)
        if ruleset == RuleSet.RULESET:
            if removed:
                actions = {r.rule.action for r in removed}
                self.add_notification_job([f"{self.state.config.ruleset_prefix}{action}" for action in actions])
        self.organize_and_save_rules()

    def set_rules_status(self, ruleset: RuleSet, priorities: dict[int, bool]):
        manager = self.state.get_rule_manager(ruleset)
        updated = manager.update_rules_at_priorities(priorities)
        if ruleset == RuleSet.RULESET:
            if updated:
                actions = {r.rule.action for r in updated}
                self.add_notification_job([f"{self.state.config.ruleset_prefix}{action}" for action in actions])
        self.organize_and_save_rules()

    def import_rules(self, vehicle: str, payload: str) -> tuple[bool, str]:
        rules: List[str] = []
        if vehicle == 'YAML':
            try:
                imported_rules = yaml.load(payload, Loader=yaml.SafeLoader)
                if not isinstance(imported_rules, dict):
                    return False, "无效的输入"
            except yaml.YAMLError as err:
                logger.error(f"Failed to import rules: {repr(err)}")
                return False, 'YAML 格式错误'
            rules = imported_rules.get(ClashKey.RULES, [])
        self.append_top_rules(rules)
        return True, ""

    def get_ruleset(self, name: str) -> Optional[str]:
        ruleset_name = self.state.ruleset_names.get(name)
        if ruleset_name is None:
            return None
        rules = self.ruleset(ruleset_name)
        res = yaml.dump({"payload": rules}, allow_unicode=True)
        return res

    def update_hosts(self, domain: str, host: HostData) -> tuple[bool, str]:
        hosts = self.state.hosts
        hosts.update(domain, host)
        self.state.hosts = hosts
        return True, f"Host for domain {host.domain} updated successfully."

    def delete_host(self, domain: str) -> tuple[bool, str]:
        hosts = self.state.hosts
        original_len = len(hosts)
        hosts.delete(domain)
        if len(hosts) < original_len:
            self.state.hosts = hosts
            return True, ''
        else:
            return False, f'Host for domain {domain} not found.'

    async def refresh_subscription(self, url: str) -> Tuple[bool, str]:
        sub_conf = next((conf for conf in self.state.config.subscriptions_config if conf.url == url), None)
        if not sub_conf:
            return False, f"Configuration for {url} not found."
        config, info = await self.async_get_subscription(url)
        if not config:
            return False, f"订阅链接 {url} 更新失败"

        sub_configs = self.state.sub_configs
        sub_configs[url] = config
        self.state.sub_configs = sub_configs

        sub_info_map = self.state.subscription_info
        info.enabled = sub_info_map.get(url).enabled
        sub_info_map[url] = info
        self.state.subscription_info = sub_info_map
        return True, "订阅更新成功"

    def update_subscription_info(self, sub_setting: SubscriptionSetting):
        sub_info = self.state.subscription_info
        sub_info.set(sub_setting)
        self.state.subscription_info = sub_info

    async def async_get_subscription(self, url: str) -> tuple[ClashConfig | None, SubscriptionInfo | None]:
        if not url:
            return None, None
        logger.info(f"正在刷新 {UtilsProvider.get_url_domain(url)} ...")
        ret = None
        raw_proxies = {}
        for _ in range(self.state.config.retry_times):
            ret = await AsyncRequestUtils(
                accept_type="text/html", timeout=self.state.config.timeout, ua="clash.meta",
                proxies=settings.PROXY if self.state.config.proxy else None
            ).get_res(url)
            if ret:
                break
        if not ret:
            logger.warning(f"{UtilsProvider.get_url_domain(url)} 刷新失败.")
            return None, None
        try:
            content = ret.content
            rs = yaml.safe_load(content)
            if isinstance(rs, str):
                proxies = Converter().convert_v2ray(content)
                if not proxies:
                    raise ValueError("Unknown content type")
                rs = {
                    ClashKey.PROXIES: proxies.values(),
                    ClashKey.PROXY_GROUPS: [
                        {ClashKey.NAME: "All Proxies", 'type': 'select', 'include-all-proxies': True}
                    ]
                }
                raw_proxies = {p['name']: link for link, p in proxies.items()}
            if not isinstance(rs, dict):
                raise ValueError("Subscription content is not a valid dictionary.")
            rs: dict[str, Any] = rs
            logger.info(f"已刷新: {UtilsProvider.get_url_domain(url)}. 节点数量: {len(rs.get(ClashKey.PROXIES, []))}")
            conf = ClashConfig.model_validate(rs)
        except Exception as e:
            logger.error(f"解析配置出错： {e}")
            return None, None
        info = {"last_update": int(time.time()), "proxy_num": conf.node_num}
        if 'Subscription-Userinfo' in ret.headers:
            matches = re.findall(r'(\w+)=(\d+)', ret.headers['Subscription-Userinfo'])
            variables = {key: int(value) for key, value in matches}
            info.update(variables)
        sub_info = SubscriptionInfo(**info)
        conf.raw_proxies = raw_proxies
        return conf, sub_info

    async def async_refresh_subscriptions(self) -> Dict[str, bool]:
        res = {}
        sub_info_map = self.state.subscription_info
        sub_configs_map = self.state.sub_configs
        
        for sub_conf in self.state.config.subscriptions_config:
            url = sub_conf.url
            if not sub_info_map.get(url).enabled:
                continue
            conf, sub_info = await self.async_get_subscription(url)
            if not conf:
                res[url] = False
                continue
            sub_info_map[url] = sub_info
            res[url] = True
            sub_configs_map[url] = conf
        self.state.subscription_info = sub_info_map
        self.state.sub_configs = sub_configs_map
        return res

    async def async_refresh_acl4ssr(self):
        logger.info("正在刷新 ACL4SSR ...")
        paths = ['Clash/Providers', 'Clash/Providers/Ruleset']
        api_url = f"{Constant.ACL4SSR_API}/contents/%s"
        branch = 'master'
        new_providers = []
        names = set()
        for path in paths:
            response = await AsyncRequestUtils().get_res(api_url % path, headers=settings.GITHUB_HEADERS,
                                                         params={'ref': branch})
            if not response:
                continue
            files = response.json()
            yaml_files = [f for f in files if f["type"] == "file" and f[ClashKey.NAME].endswith((".yaml", ".yml"))]
            for f in yaml_files:
                name = f"{self.state.config.acl4ssr_prefix}{f[ClashKey.NAME][:f[ClashKey.NAME].rfind('.')]}"
                if name in names:
                    continue
                file_path = f"./ACL4SSR/{f['name']}"
                provider = RuleProvider(
                    type=VehicleType.HTTP, path=file_path, url=f["download_url"], interval=600, behavior="classical",
                    format="yaml"
                )
                meta = Metadata(source=DataSource.ACL4SSR)
                new_providers.append(RuleProviderData(name=name, data=provider, meta=meta))
                names.add(name)

        self.state.acl4ssr_providers = RuleProviders.model_validate(new_providers)
        logger.info(f"ACL4SSR 规则集刷新完成. 规则集数量: {len(self.state.acl4ssr_providers)}")

    async def async_refresh_geo_dat(self):
        logger.info("正在刷新 Geo Rules ...")
        branch = 'meta'
        api_url = f"{Constant.METACUBEX_RULE_DAT_API}/contents/geo"
        resp = await AsyncRequestUtils().get_res(api_url, headers=settings.GITHUB_HEADERS, params={'ref': branch})
        if not resp:
            return

        geo_rules = self.state.geo_rules
        for path in resp.json():
            if path["type"] == "dir" and path["name"] in geo_rules.model_fields:
                tree_sha = path["sha"]
                url = f"{Constant.METACUBEX_RULE_DAT_API}/git/trees/{tree_sha}"
                res = await AsyncRequestUtils().get_res(url, headers=settings.GITHUB_HEADERS, params={'ref': branch})
                if not res:
                    continue
                tree = res.json()
                yaml_files = [item["path"][:item["path"].rfind('.')] for item in tree["tree"] if
                              item["type"] == "blob" and item['path'].endswith((".yaml", ".yml"))]
                setattr(geo_rules, path["name"], yaml_files)
        self.state.geo_rules = geo_rules
        logger.info(f"Geo Rules 更新完成. 规则数量: "
                    f"geoip({len(self.state.geo_rules.geoip)}), geosite({len(self.state.geo_rules.geosite)})")

    def check_patch_lifetime(self):
        pp = self.state.proxy_patch
        proxies = self.state.all_proxies
        pp.update_patch({g.name for g in proxies}, lifespan=Constant.PATCH_LIFESPAN)
        self.state.proxy_patch = pp

        groups = self.proxy_groups_by_region() + self.state.all_proxy_groups
        pgp = self.state.proxy_group_patch
        pgp.update_patch({g.name for g in groups}, lifespan=Constant.PATCH_LIFESPAN)
        self.state.proxy_group_patch = pgp

        rpp = self.state.rule_provider_patch
        rule_providers = self.state.all_rule_providers
        rpp.update_patch({g.name for g in rule_providers}, lifespan=Constant.PATCH_LIFESPAN)
        self.state.rule_provider_patch = rpp
