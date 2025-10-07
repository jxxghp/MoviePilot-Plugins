import asyncio
import copy
import hashlib
import json
import pytz
import re
import time
import yaml
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Literal, Tuple

from fastapi import HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.cache import cached
from app.core.config import settings
from app.log import logger
from app.utils.http import AsyncRequestUtils

from .base import _ClashRuleProviderBase as Crp
from .config import PluginConfig
from .helper.clashrulemanager import RuleItem, ClashRuleManager
from .helper.clashruleparser import ClashRuleParser, RoutingRuleType, Action, ClashRule
from .helper.configconverter import Converter
from .helper.utilsprovider import UtilsProvider
from .models import ProxyBase, TLSMixin, NetworkMixin, ProxyGroup, Proxy
from .models.api import RuleData, ClashApi, RuleProviderData, SubscriptionInfo, HostData
from .state import PluginState
from .store import PluginStore


class ClashRuleProviderService:

    def __init__(
            self, plugin_id: str,
            config: PluginConfig,
            state: PluginState,
            store: PluginStore,
            scheduler: Optional[AsyncIOScheduler] = None
    ):
        self.plugin_id = plugin_id
        self.config = config
        self.state = state
        self.store = store
        self.scheduler = scheduler

    def save_rules(self):
        self.store.save_data(Crp.KEY_TOP_RULES, self.state.top_rules_manager.export_rules())
        self.store.save_data(Crp.KEY_RULESET_RULES, self.state.ruleset_rules_manager.export_rules())

    def load_rules(self):
        def process_rules(raw_rules: List[str], manager: ClashRuleManager, key: str):
            raw_rules = raw_rules or []
            rules = [self._upgrade_rule(r) if isinstance(r, str) else r for r in raw_rules]
            manager.import_rules(rules)
            if any((isinstance(r, str) or 'time_modified' not in r) for r in raw_rules):
                self.store.save_data(key, manager.export_rules())

        process_rules(self.store.get_data(Crp.KEY_TOP_RULES), self.state.top_rules_manager, Crp.KEY_TOP_RULES)
        process_rules(self.store.get_data(Crp.KEY_RULESET_RULES), self.state.ruleset_rules_manager,
                      Crp.KEY_RULESET_RULES)

    def _upgrade_rule(self, rule_string: str) -> Dict[str, str]:
        rule = ClashRuleParser.parse_rule_line(rule_string)
        remark = 'Manual'
        if isinstance(rule, ClashRule) and rule.rule_type == RoutingRuleType.RULE_SET and rule.payload.startswith(
                self.config.ruleset_prefix):
            remark = 'Auto'
        return {'rule': rule_string, 'remark': remark, 'time_modified': time.time()}

    def save_proxies(self):
        proxies = self.state.proxies_manager.export_raw(condition=lambda proxy: proxy.remark == 'Manual')
        self.store.save_data(Crp.KEY_PROXIES, proxies)

    def load_proxies(self):
        proxies = self.store.get_data(Crp.KEY_PROXIES) or []
        initial_len = len(proxies)
        proxies.extend(self.state.extra_proxies)
        invalid_proxies = []
        converter = Converter()
        for proxy in proxies:
            try:
                if isinstance(proxy, dict):
                    proxy = UtilsProvider.filter_empty(proxy, empty=['', None])
                    self.state.proxies_manager.add_proxy_dict(proxy, remark='Manual')
                elif isinstance(proxy, str):
                    proxy_dict = converter.convert_line(proxy)
                    if proxy_dict:
                        self.state.proxies_manager.add_proxy_dict(proxy_dict, remark='Manual', raw=proxy)
            except Exception as e:
                logger.error(f"Failed to load proxy {proxy}: {e}")
                invalid_proxies.append(proxy)
        if len(self.state.extra_proxies) != len(invalid_proxies):
            self.state.extra_proxies = invalid_proxies
            self.store.save_data('extra_proxies', self.state.extra_proxies)
        if len(self.state.proxies_manager) > initial_len:
            self.save_proxies()

    def overwrite_proxy(self, proxy: Dict[str, Any]):
        proxy_base = ProxyBase.parse_obj(proxy)
        tls = TLSMixin.parse_obj(proxy)
        network = NetworkMixin.parse_obj(proxy)
        overwrite_config = {
            'base': proxy_base.dict(by_alias=True, exclude_none=True),
            'tls': tls.dict(by_alias=True, exclude_none=True),
            'network': network.dict(by_alias=True, exclude_none=True),
            'lifetime': Crp.OVERWRITTEN_PROXIES_LIFETIME
        }
        self.state.overwritten_proxies[proxy_base.name] = overwrite_config
        self.store.save_data('overwritten_proxies', self.state.overwritten_proxies)

    def remove_overwritten_proxy(self, proxy_name: str):
        self.state.overwritten_proxies.pop(proxy_name, None)
        self.store.save_data('overwritten_proxies', self.state.overwritten_proxies)

    def overwrite_region_group(self, region_group: ProxyGroup):
        overwrite_config = {k: v for k, v in region_group.dict(by_alias=True, exclude_none=True).items() if
                            k not in {Crp.KEY_NAME, Crp.KEY_PROXIES, 'use'}}
        self.state.overwritten_region_groups[region_group.__root__.name] = overwrite_config
        self._group_by_region.cache_clear()
        self.store.save_data('overwritten_region_groups', self.state.overwritten_region_groups)

    def organize_and_save_rules(self):
        self.sync_ruleset()
        self.save_rules()

    def ruleset(self, ruleset: str) -> List[str]:
        if not ruleset.startswith(self.config.ruleset_prefix):
            return []
        action = ruleset[len(self.config.ruleset_prefix):]
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
                      r.remark == 'Auto' and
                      r.rule.payload != f"{self.config.ruleset_prefix}{ClashRuleParser.action_string(r.rule.action)}"
        )
        rules_existed = manager.filter_rules_by_condition(
            lambda r: r.remark == 'Auto' and r.rule.rule_type == RoutingRuleType.RULE_SET
        )
        actions_existed = {ClashRuleParser.action_string(r.rule.action) for r in rules_existed}

        for r in self.state.ruleset_rules_manager.rules:
            action_str = ClashRuleParser.action_string(r.rule.action)
            outbounds.add(action_str)
            if action_str not in actions_existed:
                new_outbounds.add(action_str)

        manager.remove_rules_by_lambda(
            lambda r: r.rule.rule_type == RoutingRuleType.RULE_SET and
                      r.remark == 'Auto' and
                      (ClashRuleParser.action_string(r.rule.action) not in outbounds)
        )

        for outbound in new_outbounds:
            clash_rule = ClashRuleParser.parse_rule_line(
                f"RULE-SET,{self.config.ruleset_prefix}{outbound},{outbound}")
            rule = RuleItem(rule=clash_rule, remark='Auto')
            if not manager.has_rule_item(rule):
                manager.insert_rule_at_priority(rule, 0)

    def append_top_rules(self, rules: List[str]):
        clash_rules = []
        for rule in rules:
            clash_rule = ClashRuleParser.parse_rule_line(rule)
            if clash_rule:
                clash_rules.append(RuleItem(rule=clash_rule, remark='Manual'))
        self.state.top_rules_manager.append_rules(clash_rules)
        self.store.save_data(Crp.KEY_TOP_RULES, self.state.top_rules_manager.export_rules())

    def clash_outbound(self) -> List[Dict[str, Any]]:
        outbound = [{Crp.KEY_NAME: pg.get(Crp.KEY_NAME)} for pg in self.value_from_sub_conf('proxy-groups')]
        if self.state.clash_template_dict:
            outbound.extend(
                [{Crp.KEY_NAME: pg.get(Crp.KEY_NAME)} for pg in
                 self.state.clash_template_dict.get(Crp.KEY_PROXY_GROUPS, [])])
        if self.config.group_by_region or self.config.group_by_country:
            outbound.extend([{Crp.KEY_NAME: pg.get(Crp.KEY_NAME)} for pg in self.proxy_groups_by_region()])
        outbound.extend([{Crp.KEY_NAME: pg.get(Crp.KEY_NAME)} for pg in self.state.proxy_groups])
        outbound.extend([{Crp.KEY_NAME: pg.get(Crp.KEY_NAME)} for pg in self.get_proxies()])
        return outbound

    def rule_providers(self) -> List[Dict[str, Any]]:
        providers_list = []
        sub_providers = self.dict_from_sub_conf('rule-providers')
        hostnames = [UtilsProvider.get_url_domain(url) for url in sub_providers]
        provider_sources = (
            self.state.rule_providers,
            *sub_providers.values(),
            self.state.clash_template_dict.get('rule-providers', {}),
            self.state.acl4ssr_providers
        )
        source_names = ('Manual', *hostnames, 'Template', 'Acl4ssr')
        for i, provider_dict in enumerate(provider_sources):
            for name, value in provider_dict.items():
                provider = copy.deepcopy(value)
                provider[Crp.KEY_NAME] = name
                provider['source'] = source_names[i]
                providers_list.append(provider)
        return providers_list

    def all_proxy_providers(self) -> Dict[str, Any]:
        proxy_providers = self.value_from_sub_conf('proxy-providers')
        proxy_providers.update(self.state.clash_template_dict.get('proxy-providers', {}))
        return proxy_providers

    def get_all_proxies_with_details(self) -> List[Dict[str, Any]]:
        proxies = self.get_proxies(regex='^Manual$', flat=False)
        proxies.extend(self.get_proxies(regex='^Template$', flat=False))
        proxies.extend(self.get_proxies(regex='^Sub:', flat=False))
        ret = []
        for proxy in proxies:
            remark = proxy['remark']
            i = remark.rfind('-')
            source = remark[remark.rfind(':') + 1:(len(remark) if i == -1 else i)]
            if isinstance(proxy['raw'], str):
                proxy_link = proxy['raw']
            else:
                try:
                    proxy_link = Converter.convert_to_share_link(proxy['proxy'])
                except Exception as e:
                    logger.warn(f"Failed to convert proxy link: {repr(e)}")
                    proxy_link = None
            proxy['proxy']['source'] = source
            proxy['proxy']['v2ray_link'] = proxy_link
            proxy['proxy']['overwritten'] = proxy['proxy'][Crp.KEY_NAME] in self.state.overwritten_proxies
            ret.append(proxy['proxy'])
        ret.extend([{'source': 'Invalid', 'v2ray_link': None, **proxy} for proxy in self.state.extra_proxies])
        return ret

    def delete_proxy(self, name: str):
        extra_proxies = [p for p in self.state.extra_proxies if p.get(Crp.KEY_NAME) != name]
        if len(extra_proxies) != len(self.state.extra_proxies):
            self.state.extra_proxies = extra_proxies
            self.store.save_data('extra_proxies', self.state.extra_proxies)
            return
        self.state.proxies_manager.remove_proxy(name)
        self.save_proxies()

    def import_proxies(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        extra_proxies = ClashRuleProviderService.parse_proxies_from_input(params)
        if not extra_proxies:
            return False, "无可用节点或输入格式错误"
        success_count = 0
        error_messages = ''
        success = True
        for proxy_item in extra_proxies:
            try:
                self.state.proxies_manager.add_proxy_dict(
                    proxy_item['proxy'], 'Manual', raw=proxy_item['raw']
                )
                success_count += 1
            except Exception as err:
                success = False
                error_messages += f"{err}\n"
        message = f"导入 {success_count}/{len(extra_proxies)} 个代理节点. \n{error_messages}"
        self.save_proxies()
        return success, message

    def update_proxy(self, name: str, params: Dict[str, Any]) -> Tuple[bool, str]:
        proxy_dict = params
        previous_name = name
        if previous_name not in self.state.proxies_manager:
            return False, f"The proxy name {previous_name} does not exist"
        if proxy_dict.get('rescind'):
            self.remove_overwritten_proxy(previous_name)
            return True, ''
        try:
            Proxy.parse_obj(proxy_dict)
            if proxy_dict[Crp.KEY_NAME] != previous_name:
                return False, "Proxy name is not allowed to be overwritten"
            self.overwrite_proxy(proxy_dict)
        except Exception as e:
            logger.error(f"Failed to overwrite proxy: {repr(e)}")
            return False, "覆写代理失败"
        return True, ''

    @staticmethod
    def parse_proxies_from_input(params: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        extra_proxies: List = []
        if params.get('type') == 'YAML':
            try:
                imported_proxies = yaml.load(params["payload"], Loader=yaml.SafeLoader)
                if not imported_proxies or not isinstance(imported_proxies, dict):
                    logger.error(f"Failed to load YAML payload: {repr(params)}")
                    return None
                if Crp.KEY_PROXIES not in imported_proxies:
                    logger.error("No field 'proxies' found")
                    return None
                extra_proxies = [{'proxy': proxy, 'raw': None} for proxy in imported_proxies.get(Crp.KEY_PROXIES, [])]
            except Exception as err:
                logger.error(f"Failed to load YAML payload: {params['payload']}: {repr(err)}")
                return None
        elif params.get('type') == 'LINK':
            try:
                links = params['payload'].strip().splitlines()
                for link in links:
                    proxy = Converter().convert_line(link, skip_exception=True)
                    if proxy:
                        extra_proxies.append({'proxy': proxy, 'raw': link})
            except Exception as err:
                logger.error(f"Failed to load LINK payload: {repr(params)}: {repr(err)}")
        return extra_proxies

    def get_all_proxy_groups_with_source(self) -> List[Dict[str, Any]]:
        proxy_groups = []
        sub = self.dict_from_sub_conf('proxy-groups')
        hostnames = [UtilsProvider.get_url_domain(url) or '' for url in sub]
        sub_proxy_groups = sub.values()
        sources = ('Manual', 'Template', *hostnames, 'Region')
        groups = (self.state.proxy_groups, self.state.clash_template_dict.get(Crp.KEY_PROXY_GROUPS, []),
                  *sub_proxy_groups, self.proxy_groups_by_region())
        for i, group in enumerate(groups):
            for proxy_group in group:
                proxy_group_copy = copy.deepcopy(proxy_group)
                proxy_group_copy['source'] = sources[i]
                proxy_groups.append(proxy_group_copy)
        return proxy_groups

    def get_proxies(self, regex: Optional[str] = None, flat: bool = True) -> List[Dict[str, Any]]:
        def _overwrite_proxy(_proxy: Dict[str, Any]) -> Dict[str, Any]:
            if _proxy[Crp.KEY_NAME] in self.state.overwritten_proxies:
                for key in ['base', 'tls', 'network']:
                    _proxy.update(copy.deepcopy(self.state.overwritten_proxies[_proxy[Crp.KEY_NAME]].get(key)) or {})
            return _proxy

        if regex is None:
            proxy_items = list(self.state.proxies_manager)
        else:
            proxy_items = self.state.proxies_manager.filter_proxies_by_condition(
                lambda item: bool(re.compile(regex).match(item.remark))
            )

        result = []
        for p in proxy_items:
            if any(keyword in p.proxy.name for keyword in self.config.filter_keywords):
                continue
            proxy_dict = _overwrite_proxy(p.proxy.dict(by_alias=True, exclude_none=True))
            if flat:
                result.append(proxy_dict)
            else:
                result.append({'proxy': proxy_dict, 'raw': p.raw, 'remark': p.remark})
        return result

    @cached(maxsize=1, ttl=86400, skip_empty=True)
    def _get_countries_data(self) -> List[Dict[str, str]]:
        file_path = settings.ROOT_PATH / 'app' / 'plugins' / self.plugin_id.lower() / 'countries.json'
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载国家/地区文件错误：{e}")
            return []

    def proxy_groups_by_region(self) -> List[Dict[str, Any]]:
        countries = self._get_countries_data()
        all_proxies = self.get_proxies()
        return self._group_by_region(countries, all_proxies, self.config.group_by_region,
                                     self.config.group_by_country,
                                     self.state.overwritten_region_groups)

    @cached(maxsize=1, ttl=86400)
    def _group_by_region(self, countries: List[Dict[str, str]], all_proxies: List[Dict[str, Any]],
                         group_by_region: bool, group_by_country: bool,
                         overwritten_groups: Dict[str, Any]) -> List[Dict[str, Any]]:
        continent_groups = {}
        country_groups = {}
        continent_map = {
            '欧洲': 'Europe', '亚洲': 'Asia', '大洋洲': 'Oceania', '非洲': 'Africa',
            '北美洲': 'NorthAmerica', '南美洲': 'SouthAmerica'
        }
        proxy_groups: List[Dict[str, Any]] = []
        hk = next((c for c in countries if c['abbr'] == 'HK'), {})
        tw = next((c for c in countries if c['abbr'] == 'TW'), {})

        for proxy_node in all_proxies:
            country = ClashRuleProviderService._country_from_node(countries, proxy_node[Crp.KEY_NAME])
            if not country:
                continue
            if country.get("abbr") == "CN":
                if any(key in proxy_node[Crp.KEY_NAME] for key in ("🇭🇰", "HK", "香港")):
                    country = hk
                if any(key in proxy_node[Crp.KEY_NAME] for key in ("🇹🇼", "TW", "台湾")):
                    country = tw
            continent = continent_map.get(country.get('continent'))
            if continent and group_by_region:
                continent_groups.setdefault(continent, []).append(proxy_node[Crp.KEY_NAME])
            if group_by_country:
                country_groups.setdefault(f"{country.get('emoji')} {country.get('chinese')}", []).append(
                    proxy_node[Crp.KEY_NAME])
        for continent, nodes in continent_groups.items():
            if nodes:
                proxy_groups.append({Crp.KEY_NAME: continent, 'type': 'select', Crp.KEY_PROXIES: nodes})

        excluded = ('中国', '香港', 'CN', 'HK', '🇨🇳', '🇭🇰')
        for continent_node in continent_groups.get('Asia', []):
            if any(x in continent_node for x in excluded):
                continue
            continent_groups.setdefault('AsiaExceptChina', []).append(continent_node)
        if continent_groups.get('AsiaExceptChina'):
            proxy_group = {Crp.KEY_NAME: 'AsiaExceptChina', 'type': 'select',
                           Crp.KEY_PROXIES: continent_groups['AsiaExceptChina']}
            proxy_groups.append(proxy_group)
        for country, nodes in country_groups.items():
            if len(nodes):
                proxy_group = {Crp.KEY_NAME: country, 'type': 'select', Crp.KEY_PROXIES: nodes}
                proxy_groups.append(proxy_group)
        country_group = list(country_groups.keys())
        if country_group:
            proxy_groups.append({Crp.KEY_NAME: '🏴‍☠️国家分组', 'type': 'select', Crp.KEY_PROXIES: country_group})

        for pg in proxy_groups:
            if pg[Crp.KEY_NAME] in overwritten_groups:
                pg.update(overwritten_groups[pg[Crp.KEY_NAME]])

        return proxy_groups

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
    def _extend_with_name_checking(to_list: List[Dict[str, Any]], from_list: List[Dict[str, Any]]
                                   ) -> List[Dict[str, Any]]:
        """
        去除同名元素合并列表
        """
        for item in from_list:
            if any(p.get(Crp.KEY_NAME) == item.get(Crp.KEY_NAME, '') for p in to_list):
                logger.warn(f"Item named {item.get(Crp.KEY_NAME)!r} already exists. Skipping...")
                continue
            to_list.append(item)
        return to_list

    @staticmethod
    def _remove_invalid_outbounds(proxies: List[Dict[str, Any]], proxy_groups: List[Dict[str, Any]]
                                  ) -> List[Dict[str, Any]]:
        """
        从代理组中移除无效的出站
        """
        outbounds = {proxy.get(Crp.KEY_NAME) for proxy in proxies if proxy.get(Crp.KEY_NAME)} | \
                    {proxy_group.get(Crp.KEY_NAME) for proxy_group in proxy_groups if proxy_group.get(Crp.KEY_NAME)} | \
                    {action.value for action in Action}
        outbounds.add('GLOBAL')
        for proxy_group in proxy_groups:
            ps = []
            if proxy_group.get(Crp.KEY_PROXIES):
                for proxy in proxy_group.get(Crp.KEY_PROXIES, []):
                    if proxy in outbounds:
                        ps.append(proxy)
                    else:
                        logger.warn(f"Proxy {proxy!r} in {proxy_group.get(Crp.KEY_NAME)!r} doesn't exist. Skipping...")
                proxy_group[Crp.KEY_PROXIES] = ps
        return proxy_groups

    @staticmethod
    def _remove_invalid_proxy_providers(providers: Dict[str, Any], proxy_groups: List[Dict[str, Any]]
                                        ) -> List[Dict[str, Any]]:
        provider_names = providers.keys()
        for proxy_group in proxy_groups:
            ps = []
            if proxy_group.get('use'):
                for provider in proxy_group.get('use', []):
                    if provider in provider_names:
                        ps.append(provider)
                    else:
                        logger.warn(f"Proxy provider {provider!r} in {proxy_group.get(Crp.KEY_NAME)!r} doesn't exist. "
                                    f"Skipping...")
                proxy_group['use'] = ps
        return proxy_groups

    @staticmethod
    def _build_graph(config: Dict[str, Any]) -> Dict[str, Any]:
        """构建代理组有向图"""
        graph = {}
        groups = config.get(Crp.KEY_PROXY_GROUPS, [])
        group_names = {g[Crp.KEY_NAME] for g in groups}
        for group in groups:
            name = group[Crp.KEY_NAME]
            proxies = group.get(Crp.KEY_PROXIES, [])
            graph[name] = [p for p in proxies if p in group_names]
        return graph

    def value_from_sub_conf(self,
                            key: Literal['rules', 'rule-providers', 'proxies', 'proxy-groups', 'proxy-providers']):
        default = copy.deepcopy(Crp.DEFAULT_CLASH_CONF[key])
        for conf in self.config.subscriptions_config:
            url = conf.url
            sub_config = self.state.clash_configs.get(url, {})
            if isinstance(default, dict):
                default.update(sub_config.get(key, {}))
            elif isinstance(default, list):
                default.extend(sub_config.get(key, []))
        return default

    def dict_from_sub_conf(self,
                           key: Literal['rules', 'rule-providers', 'proxies', 'proxy-groups', 'proxy-providers']
                           ) -> Dict[str, Any]:
        result = {}
        for conf in self.config.subscriptions_config:
            url = conf.url
            sub_config = self.state.clash_configs.get(url, {})
            result[url] = sub_config.get(key, copy.deepcopy(Crp.DEFAULT_CLASH_CONF[key]))
        return result

    async def fetch_clash_data(self, endpoint: str) -> Dict:
        headers = {"Authorization": f"Bearer {self.config.dashboard_secret}"}
        url = f"{self.config.dashboard_url}/{endpoint}"
        response = await AsyncRequestUtils().get_json(url, headers=headers, timeout=10)
        if response is None:
            raise HTTPException(status_code=502, detail=f"Failed to fetch {endpoint}")
        return response

    def get_subscription_user_info(self) -> Dict[str, int]:
        sub_info = {'upload': 0, 'download': 0, 'total': 0, 'expire': 0}
        for info in self.state.subscription_info.values():
            if not info:
                continue
            sub_info['upload'] += info.get('upload', 0)
            sub_info['download'] += info.get('download', 0)
            sub_info['total'] += info.get('total', 0)
            sub_info['expire'] = max(sub_info['expire'], info.get('expire') or 0)
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
        if not self.config.enabled or not self.scheduler:
            return
        for ruleset in ruleset_names:
            if ruleset in self.state.rule_provider:
                self.scheduler.add_job(
                    ClashRuleProviderService.async_notify_clash, "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) +
                             timedelta(seconds=self.config.refresh_delay),
                    args=(ruleset, self.config.dashboard_url,
                          self.config.dashboard_secret),
                    id=f'CRP-notify-clash{ruleset}', replace_existing=True,
                    misfire_grace_time=Crp.MISFIRE_GRACE_TIME
                )

    def clash_config(self) -> Optional[Dict[str, Any]]:
        if not self.state.clash_template_dict:
            config: Dict[str, Any] = copy.deepcopy(Crp.DEFAULT_CLASH_CONF)
        else:
            config: Dict[str, Any] = copy.deepcopy(self.state.clash_template_dict)

        for key, default in Crp.DEFAULT_CLASH_CONF.items():
            if isinstance(default, dict):
                UtilsProvider.update_with_checking(self.value_from_sub_conf(key), config.get(key, {}))
            elif isinstance(default, list):
                self._extend_with_name_checking(config.get(key, []), self.value_from_sub_conf(key))
        proxies = []
        for proxy in self.get_proxies():
            if any(p.get(Crp.KEY_NAME) == proxy.get(Crp.KEY_NAME, '') for p in proxies):
                logger.warn(f"Proxy named {proxy.get(Crp.KEY_NAME)!r} already exists. Skipping...")
                continue
            proxies.append(proxy)
        if proxies:
            config[Crp.KEY_PROXIES] = proxies
        self.sync_ruleset()
        # 添加代理组
        proxy_groups = copy.deepcopy(self.state.proxy_groups)
        if proxy_groups:
            config[Crp.KEY_PROXY_GROUPS] = self._extend_with_name_checking(config[Crp.KEY_PROXY_GROUPS],
                                                                           proxy_groups)
        # 添加按大洲代理组
        if self.config.group_by_region or self.config.group_by_country:
            groups_by_region = self.proxy_groups_by_region()
            if groups_by_region:
                config[Crp.KEY_PROXY_GROUPS] = self._extend_with_name_checking(config[Crp.KEY_PROXY_GROUPS],
                                                                               groups_by_region)
        # 移除无效出站, 避免配置错误
        config[Crp.KEY_PROXY_GROUPS] = self._remove_invalid_outbounds(config.get(Crp.KEY_PROXIES, []),
                                                                      config.get(Crp.KEY_PROXY_GROUPS, []))
        config[Crp.KEY_PROXY_GROUPS] = self._remove_invalid_proxy_providers(
            self.all_proxy_providers(),
            config.get(Crp.KEY_PROXY_GROUPS, [])
        )
        top_rules = []
        outbound_names = list(x.get(Crp.KEY_NAME) for x in self.clash_outbound())

        # 添加 extra rule providers
        if self.state.rule_providers:
            config['rule-providers'].update(self.state.rule_providers)

        # 通过 ruleset rules 添加 rule-providers
        self.state.rule_provider = {}
        for r in self.state.ruleset_rules_manager.rules:
            rule = r.rule
            action_str = ClashRuleParser.action_string(rule.action)
            rule_provider_name = f'{self.config.ruleset_prefix}{action_str}'
            if rule_provider_name not in self.state.rule_provider:
                path_name = hashlib.sha256(action_str.encode('utf-8')).hexdigest()[:10]
                self.state.ruleset_names[path_name] = rule_provider_name
                sub_url = (f"{self.config.movie_pilot_url}/api/v1/plugin/ClashRuleProvider/ruleset?"
                           f"name={path_name}&apikey={self.config.apikey or settings.API_TOKEN}")
                self.state.rule_provider[rule_provider_name] = {"behavior": "classical",
                                                                "format": "yaml",
                                                                "interval": 3600,
                                                                "path": f"./CRP/{path_name}.yaml",
                                                                "type": "http",
                                                                "url": sub_url}
        config['rule-providers'].update(self.state.rule_provider)
        # 添加规则
        for r in self.state.top_rules_manager:
            rule = r.rule
            if (not isinstance(rule.action, Action) and rule.action not in outbound_names and
                    rule.rule_type != RoutingRuleType.SUB_RULE):
                logger.warn(f"出站 {rule.action} 不存在, 跳过 {rule.raw_rule}")
                continue
            if rule.rule_type == RoutingRuleType.RULE_SET:
                # 添加ACL4SSR Rules
                if rule.payload in self.state.acl4ssr_providers:
                    config['rule-providers'][rule.payload] = self.state.acl4ssr_providers[rule.payload]
                if rule.payload not in config.get('rule-providers', {}):
                    logger.warn(f"规则集合 {rule.payload!r} 不存在, 跳过 {rule.raw_rule!r}")
                    continue
            top_rules.append(str(rule))
        for raw_rule in config.get("rules", []):
            rule = ClashRuleParser.parse_rule_line(raw_rule)
            if not rule:
                logger.warn(f"无效的规则 {raw_rule!r}, 跳过")
                continue

            if (not isinstance(rule.action, Action) and rule.action not in outbound_names and
                    rule.rule_type != RoutingRuleType.SUB_RULE):
                logger.warn(f"出站 {rule.action!r} 不存在, 跳过 {rule.raw_rule!r}")
                continue
            top_rules.append(str(rule))
        config["rules"] = top_rules

        # 添加 Hosts
        if self.state.hosts:
            config.setdefault('hosts', {})
            new_hosts = {
                item['domain']: item.get('value', []) if not item.get(
                    'using_cloudflare') else self.config.best_cf_ip
                for item in self.state.hosts if item.get('domain')
            }
            config["hosts"] = {**config["hosts"], **new_hosts}

        if self.state.rule_provider:
            config['rule-providers'] = config.get('rule-providers') or {}
            config['rule-providers'].update(self.state.rule_provider)

        key_to_delete = []
        for key, item in self.state.ruleset_names.items():
            if item not in config.get('rule-providers', {}):
                key_to_delete.append(key)
        for key in key_to_delete:
            del self.state.ruleset_names[key]
        if not config.get("rule-providers"):
            del config["rule-providers"]

        # 对代理组进行回环检测
        proxy_graph = self._build_graph(config)
        cycles = UtilsProvider.find_cycles(proxy_graph)
        # 警告但不处理
        if cycles:
            logger.warn("发现代理组回环：")
            for cycle in cycles:
                logger.warn(" -> ".join(cycle))

        self.store.save_data('ruleset_names', self.state.ruleset_names)
        self.store.save_data('rule_provider', self.state.rule_provider)
        return config

    def delete_proxy_group(self, name: str) -> Tuple[bool, str]:
        """
        Deletes a proxy group by name and saves the state.
        Returns True if a group was deleted, False otherwise.
        """
        initial_len = len(self.state.proxy_groups)
        self.state.proxy_groups = [item for item in self.state.proxy_groups if item.get(Crp.KEY_NAME) != name]
        if len(self.state.proxy_groups) < initial_len:
            self.store.save_data('proxy_groups', self.state.proxy_groups)
            return True, ''
        return False, ''

    def add_proxy_group(self, item: ProxyGroup) -> Tuple[bool, str]:
        """
        Adds a new proxy group, saves the state, and returns status.
        """
        if any(x.get(Crp.KEY_NAME) == item.__root__.name for x in self.state.proxy_groups):
            return False, f"The proxy group name {item.__root__.name} already exists"
        try:
            proxy_group = ProxyGroup.parse_obj(item)
        except Exception as e:
            logger.error(f"Failed to parse proxy group: {repr(e)}")
            return False, "Failed to parse proxy group"
        self.state.proxy_groups.append(proxy_group.dict(by_alias=True, exclude_none=True))
        self.store.save_data('proxy_groups', self.state.proxy_groups)
        return True, "Proxy group added successfully."

    def update_proxy_group(self, previous_name: str, item: ProxyGroup) -> Tuple[bool, str]:
        proxy_group = item.__root__
        region_groups = {g[Crp.KEY_NAME] for g in self.proxy_groups_by_region()}
        if previous_name in region_groups:
            self.overwrite_region_group(item)
            return True, ''

        index = next((i for i, x in enumerate(self.state.proxy_groups) if x.get(Crp.KEY_NAME) == previous_name), None)
        if index is None:
            return False, f"Proxy group {previous_name!r} does not exist"

        new_name_index = next((i for i, x in enumerate(self.state.proxy_groups) if
                               x.get(Crp.KEY_NAME) == proxy_group.name), None)
        if new_name_index is not None and new_name_index != index:
            return False, f"The proxy group name {proxy_group.name} already exists"
        self.state.proxy_groups[index] = proxy_group.dict(by_alias=True, exclude_none=True)
        self.store.save_data('proxy_groups', self.state.proxy_groups)
        return True, ''

    def update_rule_provider(self, name: str, rule_provider_data: RuleProviderData) -> Tuple[bool, str]:
        """
        Updates a rule provider, saves the state, and returns status.
        """
        new_name = rule_provider_data.name
        if name != new_name:
            self.state.rule_providers.pop(name, None)
        self.state.rule_providers[new_name] = rule_provider_data.rule_provider.dict(by_alias=True,
                                                                                    exclude_none=True)
        self.store.save_data('extra_rule_providers', self.state.rule_providers)
        return True, "Rule provider updated successfully."

    def delete_rule_provider(self, name: str):
        self.state.rule_providers.pop(name, None)
        self.store.save_data('extra_rule_providers', self.state.rule_providers)

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
                    accept_type="text/html", proxies=settings.PROXY if self.config.proxy else None,
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
            "state": self.config.enabled,
            "ruleset_prefix": self.config.ruleset_prefix,
            "best_cf_ip": self.config.best_cf_ip,
            "geoRules": self.state.geo_rules,
            "subscription_info": self.state.subscription_info,
            "sub_url": f"{self.config.movie_pilot_url}/api/v1/plugin/{self.plugin_id}/config?"
                       f"apikey={self.config.apikey or settings.API_TOKEN}"
        }
        return data

    def get_rules(self, rule_type: str) -> List[Dict[str, Any]]:
        manager = self.state.ruleset_rules_manager \
            if rule_type == 'ruleset' else self.state.top_rules_manager
        return manager.to_list()

    def reorder_rules(self, rule_type: str, moved_priority: int, target_priority: int) -> Tuple[bool, str]:
        try:
            if rule_type == 'ruleset':
                rule = self.state.ruleset_rules_manager.reorder_rules(moved_priority, target_priority)
                self.add_notification_job(
                    [f"{self.config.ruleset_prefix}{rule.rule.action}"])
            else:
                self.state.top_rules_manager.reorder_rules(moved_priority, target_priority)
        except Exception as e:
            logger.info(f"Failed to reorder rules: {repr(e)}")
            return False, "规则移动失败"
        self.organize_and_save_rules()
        return True, ""

    def update_rule(self, rule_type: str, priority: int, rule_data: RuleData) -> Tuple[bool, str]:
        try:
            dst_priority = rule_data.priority
            src_priority = priority
            clash_rule = ClashRuleParser.parse_rule_dict(rule_data.dict(exclude_none=True))
            if not clash_rule:
                return False, f"无效的规则: {rule_data!r}"
            if rule_type == 'ruleset':
                manager = self.state.ruleset_rules_manager
                original_rule = manager.get_rule_at_priority(src_priority)
                rule_item = RuleItem(rule=clash_rule, remark=original_rule.remark, time_modified=time.time())
                res = manager.update_rule_at_priority(rule_item, src_priority, dst_priority)
                if res:
                    ruleset_to_notify = [f"{self.config.ruleset_prefix}{clash_rule.action}"]
                    if rule_data.action != original_rule.rule.action:
                        ruleset_to_notify.append(f"{self.config.ruleset_prefix}{original_rule.rule.action}")
                    self.add_notification_job(ruleset_to_notify)
            else:
                manager = self.state.top_rules_manager
                original_rule = manager.get_rule_at_priority(src_priority)
                rule_item = RuleItem(rule=clash_rule, remark=original_rule.remark, time_modified=time.time())
                res = manager.update_rule_at_priority(rule_item, src_priority, dst_priority)
        except Exception as err:
            logger.info(f"Failed to update rules: {repr(err)}")
            return False, "更新规则出错"
        self.organize_and_save_rules()
        return res, ""

    def add_rule(self, rule_type: str, rule_data: RuleData) -> Tuple[bool, str]:
        try:
            priority = rule_data.priority
            clash_rule = ClashRuleParser.parse_rule_dict(rule_data.dict(exclude_none=True))
            if not clash_rule:
                return False, f"无效的输入规则: {rule_data.dict(exclude_none=True)}"
            rule_item = RuleItem(rule=clash_rule, remark='Manual', time_modified=time.time())
            if rule_type == 'ruleset':
                self.state.ruleset_rules_manager.insert_rule_at_priority(rule_item, priority)
                self.add_notification_job([f"{self.config.ruleset_prefix}{clash_rule.action}"])
            else:
                self.state.top_rules_manager.insert_rule_at_priority(rule_item, priority)
        except Exception as err:
            logger.info(f"Failed to add rule: {repr(err)}")
            return False, "添加规则出错"
        self.organize_and_save_rules()
        return True, ""

    def delete_rule(self, rule_type: str, priority: int):
        if rule_type == 'ruleset':
            res = self.state.ruleset_rules_manager.remove_rule_at_priority(priority)
            if res:
                rule = res.rule
                action_str = ClashRuleParser.action_string(rule.action)
                self.add_notification_job([f"{self.config.ruleset_prefix}{action_str}"])
        else:
            self.state.top_rules_manager.remove_rule_at_priority(priority)
        self.organize_and_save_rules()

    def import_rules(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        rules: List[str] = []
        if params.get('type') == 'YAML':
            try:
                imported_rules = yaml.load(params["payload"], Loader=yaml.SafeLoader)
                if not isinstance(imported_rules, dict):
                    return False, "无效的输入"
                rules = imported_rules.get("rules", [])
            except yaml.YAMLError as err:
                logger.error(f"Failed to import rules: {repr(err)}")
                return False, 'YAML 格式错误'
        self.append_top_rules(rules)
        return True, ""

    def get_ruleset(self, name: str) -> Optional[str]:
        ruleset_name = self.state.ruleset_names.get(name)
        if ruleset_name is None:
            return None
        rules = self.ruleset(ruleset_name)
        res = yaml.dump({"payload": rules}, allow_unicode=True)
        return res

    def get_hosts(self) -> List[Dict[str, Any]]:
        return self.state.hosts

    def update_hosts(self, param: HostData) -> Tuple[bool, str]:
        if not param.value:
            return False, "无效的参数"
        value = param.value.dict(exclude_none=True)
        for i, host in enumerate(self.state.hosts):
            if host.get('domain') == param.domain:
                self.state.hosts[i] = {**host, **value}
                self.store.save_data('hosts', self.state.hosts)
                logger.info(f"Host for domain {param.domain} updated successfully.")
                return True, ""
        self.state.hosts.append(value)
        self.store.save_data('hosts', self.state.hosts)
        return True, ""

    def delete_host(self, param: HostData) -> Tuple[bool, str]:
        original_len = len(self.state.hosts)
        self.state.hosts = [host for host in self.state.hosts if host.get('domain') != param.domain]
        self.store.save_data('hosts', self.state.hosts)

        if len(self.state.hosts) < original_len:
            return True, ''
        else:
            return False, f'Host for domain {param.domain} not found.'

    async def refresh_subscription(self, url: str) -> Tuple[bool, str]:
        sub_conf = next((conf for conf in self.config.subscriptions_config if conf.url == url), None)
        if not sub_conf:
            return False, f"Configuration for {url} not found."
        config, info = await self.async_get_subscription(url, sub_conf.dict())
        if not config:
            return False, f"订阅链接 {url} 更新失败"

        self.state.clash_configs[url] = config
        self.__sync_sub_proxies(url, config)
        self.state.subscription_info[url] = {**info,
            'enabled': self.state.subscription_info.get(url, {}).get(
                'enabled', True)}
        self.store.save_data('clash_configs', self.state.clash_configs)
        self.store.save_data('subscription_info', self.state.subscription_info)
        return True, "订阅更新成功"

    def update_subscription_info(self, sub_info: SubscriptionInfo):
        self.state.subscription_info[sub_info.url][sub_info.field] = sub_info.value
        self.store.save_data('subscription_info', self.state.subscription_info)

    def add_proxies_to_manager(self, proxies: List[Dict[str, Any]], remark: str, raw: Optional[str] = None):
        for proxy in proxies:
            try:
                self.state.proxies_manager.add_proxy_dict(proxy, remark=remark, raw=raw)
            except Exception as e:
                logger.error(f"Failed to add proxies: {e}")

    async def async_get_subscription(self, url: str, conf: Dict[str, Any]
                                     ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not url:
            return None, None
        logger.info(f"正在刷新 {UtilsProvider.get_url_domain(url)} ...")
        ret = None
        for _ in range(self.config.retry_times):
            ret = await AsyncRequestUtils(accept_type="text/html", timeout=self.config.timeout,
                                          proxies=settings.PROXY if self.config.proxy else None
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
                rs = {Crp.KEY_PROXIES: proxies,
                      Crp.KEY_PROXY_GROUPS: [
                          {Crp.KEY_NAME: "All Proxies", 'type': 'select', 'include-all-proxies': True}]}

            if not isinstance(rs, dict):
                raise ValueError("Subscription content is not a valid dictionary.")

            logger.info(f"已刷新: {UtilsProvider.get_url_domain(url)}. 节点数量: {len(rs.get(Crp.KEY_PROXIES, []))}")
            for key, default in Crp.DEFAULT_CLASH_CONF.items():
                rs.setdefault(key, copy.deepcopy(default))
                if not conf.get(key, False):
                    rs[key] = copy.deepcopy(default)
        except Exception as e:
            logger.error(f"解析配置出错： {e}")
            return None, None

        sub_info = {'last_update': int(time.time()), 'proxy_num': len(rs.get(Crp.KEY_PROXIES, []))}
        if 'Subscription-Userinfo' in ret.headers:
            matches = re.findall(r'(\w+)=(\d+)', ret.headers['Subscription-Userinfo'])
            variables = {key: int(value) for key, value in matches}
            sub_info.update(variables)
        return rs, sub_info

    async def async_refresh_subscriptions(self) -> Dict[str, bool]:
        res = {}
        for sub_conf in self.config.subscriptions_config:
            url = sub_conf.url
            if not self.state.subscription_info.get(url, {}).get('enabled'):
                continue
            conf, sub_info = await self.async_get_subscription(url, conf=sub_conf.dict())
            if not conf:
                res[url] = False
                continue
            self.state.subscription_info[url] = {**sub_info, 'enabled': True}
            res[url] = True
            self.state.clash_configs[url] = conf
            self.__sync_sub_proxies(url, conf)
        self.store.save_data('subscription_info', self.state.subscription_info)
        self.store.save_data('clash_configs', self.state.clash_configs)
        return res

    def __sync_sub_proxies(self, url: str, conf: Dict[str, Any]):
        remark = f"Sub:{UtilsProvider.get_url_domain(url)}-{abs(hash(url))}"
        self.state.proxies_manager.remove_proxies_by_condition(lambda p: p.remark == remark)
        self.add_proxies_to_manager(conf.get(Crp.KEY_PROXIES, []), remark)

    async def async_refresh_acl4ssr(self):
        logger.info("正在刷新 ACL4SSR ...")
        paths = ['Clash/Providers', 'Clash/Providers/Ruleset']
        api_url = f"{Crp.ACL4SSR_API}/contents/%s"
        branch = 'master'
        new_providers = {}
        for path in paths:
            response = await AsyncRequestUtils().get_res(api_url % path, headers=settings.GITHUB_HEADERS,
                                                         params={'ref': branch})
            if not response:
                continue
            files = response.json()
            yaml_files = [f for f in files if f["type"] == "file" and f[Crp.KEY_NAME].endswith((".yaml", ".yml"))]
            for f in yaml_files:
                name = f"{self.config.acl4ssr_prefix}{f[Crp.KEY_NAME][:f[Crp.KEY_NAME].rfind('.')]}"
                file_path = f"./ACL4SSR/{f['name']}"
                provider = {'type': 'http', 'path': file_path, 'url': f["download_url"], 'interval': 600,
                            'behavior': 'classical', 'format': 'yaml', 'size-limit': 0}
                if name not in new_providers:
                    new_providers[name] = provider
        self.state.acl4ssr_providers = new_providers
        self.store.save_data('acl4ssr_providers', self.state.acl4ssr_providers)
        logger.info(f"ACL4SSR 规则集刷新完成. 规则集数量: {len(self.state.acl4ssr_providers)}")

    async def async_refresh_geo_dat(self):
        logger.info("正在刷新 Geo Rules ...")
        branch = 'meta'
        api_url = f"{Crp.METACUBEX_RULE_DAT_API}/contents/geo"
        resp = await AsyncRequestUtils().get_res(api_url, headers=settings.GITHUB_HEADERS, params={'ref': branch})
        if not resp:
            return

        for path in resp.json():
            if path["type"] == "dir" and path["name"] in self.state.geo_rules:
                tree_sha = path["sha"]
                url = f"{Crp.METACUBEX_RULE_DAT_API}/git/trees/{tree_sha}"
                res = await AsyncRequestUtils().get_res(url, headers=settings.GITHUB_HEADERS, params={'ref': branch})
                if not res:
                    continue
                tree = res.json()
                yaml_files = [item["path"][:item["path"].rfind('.')] for item in tree["tree"] if
                              item["type"] == "blob" and item['path'].endswith((".yaml", ".yml"))]
                self.state.geo_rules[path["name"]] = yaml_files
        self.store.save_data('geo_rules', self.state.geo_rules)
        logger.info(
            f"Geo Rules 更新完成. 规则数量: {', '.join([f'{k}({len(v)})' for k, v in self.state.geo_rules.items()])}")

    def check_proxies_lifetime(self):
        for proxy in self.state.proxies_manager:
            proxy_name = proxy.proxy.name
            if proxy_name in self.state.overwritten_proxies:
                self.state.overwritten_proxies[proxy_name][
                    'lifetime'] = Crp.OVERWRITTEN_PROXIES_LIFETIME
        outdated_proxies = []
        for proxy_name, data in self.state.overwritten_proxies.items():
            if proxy_name not in self.state.proxies_manager:
                data['lifetime'] = data.get('lifetime', Crp.OVERWRITTEN_PROXIES_LIFETIME) - 1
                if data['lifetime'] < 0:
                    outdated_proxies.append(proxy_name)
        for proxy_name in outdated_proxies:
            del self.state.overwritten_proxies[proxy_name]
        self.store.save_data('overwritten_proxies', self.state.overwritten_proxies)
