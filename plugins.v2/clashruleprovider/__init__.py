import requests
import re
from typing import Any, Optional, List, Dict, Tuple, Union
import time
import yaml
import hashlib
from fastapi import Body, Response
from datetime import datetime, timedelta
import pytz

from apscheduler.schedulers.background import BackgroundScheduler
from cachetools import cached, TTLCache
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from app.plugins.clashruleprovider.clash_rule_parser import ClashRuleParser
from app.plugins.clashruleprovider.clash_rule_parser import Action, RuleType, ClashRule, MatchRule, LogicRule


class ClashRuleProvider(_PluginBase):
    # 插件名称
    plugin_name = "Clash Rule Provider"
    # 插件描述
    plugin_desc = "随时为Clash添加一些额外的规则。"
    # 插件图标
    plugin_icon = ("https://raw.githubusercontent.com/wumode/MoviePilot-Plugins/"
                   "refs/heads/imdbsource_assets/icons/Mihomo_Meta_A.png")
    # 插件版本
    plugin_version = "0.1.0"
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

    # 插件配置
    # 启用插件
    _enabled = False
    _proxy = False
    _notify = False
    # 订阅链接
    _sub_links = []
    # Clash 面板 URL
    _clash_dashboard_url = None
    # Clash 面板密钥
    _clash_dashboard_secret = None
    # MoviePilot URL
    _movie_pilot_url = None
    _cron = ''
    _timeout = 10
    _retry_times = 3
    _filter_keywords = []
    _auto_update_subscriptions = True
    _ruleset_prefix = '📂<-'

    # 插件数据
    _clash_config = None
    _top_rules: List[str] = []
    _ruleset_rules: List[str] = []
    _rule_provider: Dict[str, Any] = {}
    _subscription_info = {}
    _ruleset_names: Dict[str, str] = {}

    # protected variables
    _clash_rule_parser = None
    _ruleset_rule_parser = None
    _custom_rule_sets = None
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        self._clash_config = self.get_data("clash_config")
        self._ruleset_rules = self.get_data("ruleset_rules")
        self._top_rules = self.get_data("top_rules")
        self._subscription_info = self.get_data("subscription_info") or \
                                   {"download": 0, "upload": 0, "total": 0, "expire": 0, "last_update": 0}
        self._rule_provider = self.get_data("rule_provider") or {}
        self._ruleset_names = self.get_data("ruleset_names") or {}
        if config:
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._notify = config.get("notify"),
            self._sub_links = config.get("sub_links")
            self._clash_dashboard_url = config.get("clash_dashboard_url")
            self._clash_dashboard_secret = config.get("clash_dashboard_secret")
            self._movie_pilot_url = config.get("movie_pilot_url")
            if self._movie_pilot_url[-1] == '/':
                self._movie_pilot_url = self._movie_pilot_url[:-1]
            self._cron = config.get("cron_string")
            self._timeout = config.get("timeout")
            self._retry_times = config.get("retry_times")
            self._filter_keywords = config.get("filter_keywords")
            self._ruleset_prefix = config.get("ruleset_prefix", "Custom_")
            self._auto_update_subscriptions = config.get("auto_update_subscriptions")
        self._clash_rule_parser = ClashRuleParser()
        self._ruleset_rule_parser = ClashRuleParser()
        if self._enabled:
            self.__parse_config()
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/connectivity",
                "endpoint": self.test_connectivity,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "测试连接",
                "description": "测试连接"
            },
            {
                "path": "/clash_outbound",
                "endpoint": self.get_clash_outbound,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "clash outbound",
                "description": "clash outbound"
            },
            {
                "path": "/status",
                "endpoint": self.get_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "stated",
                "description": "state"
            },
            {
                "path": "/rules",
                "endpoint": self.get_rules,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "clash rules",
                "description": "clash rules"
            },
            {
                "path": "/rules",
                "endpoint": self.update_rules,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "clash rules",
                "description": "clash rules"
            },
            {
                "path": "/reorder-rules",
                "endpoint": self.reorder_rules,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "clash rules",
                "description": "clash rules"
            },
            {
                "path": "/rule",
                "endpoint": self.update_rule,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "clash rules",
                "description": "clash rules"
            },
            {
                "path": "/rule",
                "endpoint": self.add_rule,
                "methods": ["POSt"],
                "auth": "bear",
                "summary": "clash rules",
                "description": "clash rules"
            },
            {
                "path": "/rule",
                "endpoint": self.delete_rule,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "clash rules",
                "description": "clash rules"
            },
            {
                "path": "/subscription",
                "endpoint": self.get_subscription,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "clash rules",
                "description": "clash rules"
            },
            {
                "path": "/subscription",
                "endpoint": self.update_subscription,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "update clash rules",
                "description": "update clash rules"
            },
            {
                "path": "/rule_providers",
                "endpoint": self.get_rule_providers,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "update rule providers",
                "description": "update rule providers"
            },
            {
                "path": "/ruleset",
                "endpoint": self.get_ruleset,
                "methods": ["GET"],
                "summary": "update rule providers",
                "description": "update rule providers"
            },
            {
                "path": "/config",
                "endpoint": self.get_clash_config,
                "methods": ["GET"],
                "summary": "update rule providers",
                "description": "update rule providers"
            }
        ]

    def get_render_mode(self) -> Tuple[str, str]:
        """
        获取插件渲染模式
        :return: 1、渲染模式，支持：vue/vuetify，默认vuetify
        :return: 2、组件路径，默认 dist/assets
        """
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [], {}

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        """
        退出插件
        """
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        if self.get_state() and self._auto_update_subscriptions:
            return [{
                "id": "ClashRuleProvider",
                "name": "Clash Rule Provider 服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.update_subscription_service,
                "kwargs": {}
            }]
        return []

    def __update_config(self):
        # 保存配置
        self.update_config(
            {
                "enabled": self._enabled,
                "cron": self._cron,
                "proxy": self._proxy,
                "notify": self._notify,
                "sub_links": self._sub_links,
                "clash_dashboard_url": self._clash_dashboard_url,
                "clash_dashboard_secret": self._clash_dashboard_secret,
                "movie_pilot_url": self._movie_pilot_url,
                "retry_times": self._retry_times,
                "timeout": self._timeout,
            })

    def __save_data(self):
        self.__insert_ruleset()
        self._top_rules = self._clash_rule_parser.to_string()
        self._ruleset_rules = self._ruleset_rule_parser.to_string()
        self.save_data('clash_config', self._clash_config)
        self.save_data('ruleset_rules', self._ruleset_rules)
        self.save_data('top_rules', self._top_rules)
        self.save_data('subscription_info', self._subscription_info)
        self.save_data('ruleset_names', self._ruleset_names)
        self.save_data('rule_provider', self._rule_provider)

    def __parse_config(self):
        if not self._top_rules:
            return
        self._clash_rule_parser.parse_rules_from_list(self._top_rules)
        if not self._ruleset_rules:
            return
        self._ruleset_rule_parser.parse_rules_from_list(self._ruleset_rules)

    def test_connectivity(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._enabled:
            return {"success": False, "message": ""}
        if not params.get('clash_dashboard_url') or not params.get('clash_dashboard_secret')\
                or not params.get('sub_link'):
            return {"success": False, "message": "missing params"}
        clash_version_url = f"{params.get('clash_dashboard_url')}/version"
        ret = RequestUtils(accept_type="application/json",
                           headers={"authorization": f"Bearer {params.get('clash_dashboard_secret')}"}
                           ).get(clash_version_url)
        if not ret:
            return {"success": False, "message": "无法连接到Clash"}
        ret = RequestUtils(accept_type="text/html",
                           proxies=settings.PROXY if self._proxy else None
                           ).get(params.get('sub_link'))
        if not ret:
            return {"success": False, "message": f"Unable to get {params.get('sub_link')}"}
        return {"success": True, "message": "测试连接成功"}

    def get_ruleset(self, name):
        if not self._ruleset_names.get(name):
            return None
        name = self._ruleset_names.get(name)
        rules = self.__get_ruleset(name)
        # if rules or ruleset in self._rule_provider:
        #     self._rule_provider[ruleset] = rules
        res = yaml.dump({"payload": rules}, allow_unicode=True)
        return Response(content=res, media_type="text/yaml")

    def get_clash_outbound(self):
        outbound = self.clash_outbound(self._clash_config)
        return {"success": True, "message": None, "data": {"outbound": outbound}}

    def get_status(self):
        rule_size = len(self._clash_config.get("rules", [])) if self._clash_config else 0
        return {"success": True, "message": "",
                "data": {"state": self._enabled,
                         "ruleset_prefix": self._ruleset_prefix,
                         "clash": {"rule_size": rule_size},
                         "subscription_info": self._subscription_info,
                         "sub_url": f"{self._movie_pilot_url}/api/v1/plugin/ClashRuleProvider/config?"
                                    f"apikey={settings.API_TOKEN}"}}

    def get_clash_config(self):
        config = self.clash_config()
        if not config:
            return {"success": False, "message": ""}
        res = yaml.dump(config, allow_unicode=True)
        headers = {'Subscription-Userinfo': f'upload={self._subscription_info["upload"]}; '
                                            f'download={self._subscription_info["download"]}; '
                                            f'total={self._subscription_info["total"]}; '
                                            f'expire={self._subscription_info["expire"]}'}
        return Response(headers=headers, content=res, media_type="text/yaml")

    def get_rules(self, rule_type: str) -> Dict[str, Any]:
        if rule_type == 'ruleset':
            return {"success": True, "message": None, "data": {"rules": self._ruleset_rule_parser.to_dict()}}
        return {"success": True, "message": None, "data": {"rules": self._clash_rule_parser.to_dict()}}

    def delete_rule(self, params: dict = Body(...)):
        if not self._enabled:
            return {"success": False, "message": ""}
        if params.get('type') == 'ruleset':
            res = self.delete_rule_by_priority(params.get('priority'), self._ruleset_rule_parser)
            if res:
                self.__add_notification_job(f"{self._ruleset_prefix}{res.action.value if isinstance(res.action, Action) else res.action}")
        else:
            res = self.delete_rule_by_priority(params.get('priority'), self._clash_rule_parser)
        return {"success": res, "message": None}

    def reorder_rules(self, params: Dict[str, Any]):
        if not self._enabled:
            return {"success": False, "message": ""}
        moved_priority = params.get('moved_priority')
        target_priority = params.get('target_priority')
        try:
            if params.get('type') == 'ruleset':
                self.__reorder_rules(self._ruleset_rule_parser, moved_priority, target_priority)
                self.__add_notification_job(f"{self._ruleset_prefix}{params.get('rule_data').get('action')}")
            else:
                self.__reorder_rules(self._clash_rule_parser, moved_priority, target_priority)
        except Exception as e:
            return {"success": False, "message": str(e)}
        return {"success": True, "message": None}

    def update_rules(self, params: Dict[str, Any]):
        if not self._enabled:
            return {"success": False, "message": ""}
        if params.get('type') == 'ruleset':
            self.__update_rules(params.get('rules'), self._ruleset_rule_parser)
        else:
            self.__update_rules(params.get('rules'), self._clash_rule_parser)
        return {"success": True, "message": None}

    def update_rule(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._enabled:
            return {"success": False, "message": ""}
        if params.get('type') == 'ruleset':
            res = self.update_rule_by_priority(params.get('rule_data'), self._ruleset_rule_parser)
            if res:
                self.__add_notification_job(f"{self._ruleset_prefix}{params.get('rule_data').get('action')}")
        else:
            res = self.update_rule_by_priority(params.get('rule_data'), self._clash_rule_parser)
        return {"success": bool(res), "message": None}

    def add_rule(self,  params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._enabled:
            return {"success": False, "message": ""}
        if params.get('type') == 'ruleset':
            res = self.add_rule_by_priority(params.get('rule_data'), self._ruleset_rule_parser)
            if res:
                self.__add_notification_job(f"{self._ruleset_prefix}{params.get('rule_data').get('action')}")
        else:
            res = self.add_rule_by_priority(params.get('rule_data'), self._clash_rule_parser)
        return {"success": bool(res), "message": None}

    def get_subscription(self):
        if not self._sub_links:
            return None
        return {"success": True, "message": None, "data": {"url": self._sub_links[0]}}

    def update_subscription(self, params: Dict[str, Any]):
        if not self._enabled:
            return {"success": False, "message": ""}
        url = params.get('url')
        if not url:
            return {"success": False, "message": "missing params"}
        res = self.update_subscription_service()
        if not res:
            return {"success": True, "message": f"订阅链接 {self._sub_links[0]} 更新失败"}
        return {"success": True, "message": "订阅更新成功"}

    def get_rule_providers(self):
        return {"success": True, "message": None, "data": self.rule_providers()}

    @staticmethod
    def clash_outbound(clash_config: Dict[str, Any]) -> Optional[List]:
        if not clash_config:
            return []
        outbound = [{'name': proxy_group.get("name")} for proxy_group in clash_config.get("proxy-groups")]
        outbound.extend([{'name': proxy.get("name")} for proxy in clash_config.get("proxies")])
        return outbound

    def rule_providers(self) -> Optional[Dict[str, Any]]:
        if not self._clash_config:
            return None
        rule_providers = {}
        for key, value in self._clash_config.get("rule-providers", {}):
            if value.get("path", '').startwith("./CRP/"):
                continue
            rule_providers[key] = value
        return rule_providers

    def __update_rules(self, rules: List[Dict[str, Any]], rule_parser: ClashRuleParser):
        rule_parser.rules = []
        for rule in rules:
            clash_rule = ClashRuleParser.parse_rule_dict(rule)
            rule_parser.insert_rule_at_priority(clash_rule, rule.get("priority"))
        self.__save_data()

    def __reorder_rules(self, rule_parser: ClashRuleParser, moved_priority, target_priority):
        rule_parser.reorder_rules(moved_priority, target_priority)
        self.__save_data()

    def __get_ruleset(self, ruleset: str) -> List[str]:
        if ruleset.startswith(self._ruleset_prefix):
            action = ruleset[len(self._ruleset_prefix):]
        else:
            return []
        try:
            action_enum = Action(action.upper())
            final_action = action_enum
        except ValueError:
            final_action = action
        rules = self._ruleset_rule_parser.filter_rules_by_action(final_action)
        res = []
        for rule in rules:
            res.append(rule.condition_string())
        return res

    def __insert_ruleset(self):
        outbounds = []
        for rule in self._ruleset_rule_parser.rules:
            action_str = f"{rule.action.value}" if isinstance(rule.action, Action) else rule.action
            if action_str not in outbounds:
                outbounds.append(action_str)
        self._clash_rule_parser.remove_rules(lambda r: r.rule_type == RuleType.RULE_SET and
                                                       r.payload.startswith(self._ruleset_prefix))
        for outbound in outbounds:
            clash_rule = ClashRuleParser.parse_rule_line(f"RULE-SET,{self._ruleset_prefix}{outbound},{outbound}")
            if not self._clash_rule_parser.has_rule(clash_rule):
                self._clash_rule_parser.insert_rule_at_priority(clash_rule, 0)

    def update_rule_by_priority(self, rule: Dict[str, Any], rule_parser: ClashRuleParser) -> bool:
        if not isinstance(rule.get("priority"), int):
            return False
        clash_rule = ClashRuleParser.parse_rule_dict(rule)
        if not clash_rule:
            return False
        res = rule_parser.update_rule_at_priority(clash_rule, rule.get("priority"))
        self.__save_data()
        return res

    def add_rule_by_priority(self, rule: Dict[str, Any], rule_parser: ClashRuleParser) -> bool:
        if not isinstance(rule.get("priority"), int):
            return False
        try:
            clash_rule = self._clash_rule_parser.parse_rule_dict(rule)
        except ValueError:
            logger.warn(f"无效的输入规则: {rule}")
            return False
        if not clash_rule:
            return False
        rule_parser.insert_rule_at_priority(clash_rule, rule.get("priority"))
        self.__save_data()
        return True

    def delete_rule_by_priority(self, priority: int, rule_parser: ClashRuleParser
                                ) -> Optional[Union[ClashRule, LogicRule, MatchRule]]:
        if not isinstance(priority, int):
            return None
        res = rule_parser.remove_rule_at_priority(priority)
        self.__save_data()
        return res

    @eventmanager.register(EventType.PluginAction)
    def update_subscription_service(self) -> bool:
        if not self._sub_links:
            return False
        url = self._sub_links[0]
        ret = RequestUtils(accept_type="text/html",
                           proxies=settings.PROXY if self._proxy else None
                           ).get_res(url)
        if not ret:
            return False
        try:
            rs = yaml.load(ret.content, Loader=yaml.FullLoader)
            self._clash_config = self.__remove_nodes_by_keywords(rs)
        except Exception as e:
            logger.error(f"解析配置出错： {e}")
            return False
        if 'Subscription-Userinfo' in ret.headers:
            matches = re.findall(r'(\w+)=(\d+)', ret.headers['Subscription-Userinfo'])
            variables = {key: int(value) for key, value in matches}
            self._subscription_info['download'] = variables['download']
            self._subscription_info['upload'] = variables['upload']
            self._subscription_info['total'] = variables['total']
            self._subscription_info['expire'] = variables['expire']
        self._subscription_info["last_update"] = int(time.time())
        self.save_data('subscription_info', self._subscription_info)
        self.save_data('clash_config', self._clash_config)
        return True

    def notify_clash(self, ruleset: str):
        url = f'{self._clash_dashboard_url}/providers/rules/{ruleset}'
        RequestUtils(content_type="application/json",
                     headers={"authorization": f"Bearer {self._clash_dashboard_secret}"}
                     ).put(url)

    def __add_notification_job(self, ruleset: str):
        if ruleset in self._rule_provider:
            self._scheduler.add_job(self.notify_clash, "date",
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=30),
                                    args=[ruleset],
                                    id='CRP-notify-clash',
                                    replace_existing=True
                                    )

    def __remove_nodes_by_keywords(self, clash_config: Dict[str, Any]) -> Dict[str, Any]:
        removed_proxies = []
        proxies = []
        for proxy in clash_config.get("proxies", []):
            has_keywords = bool(len([x for x in self._filter_keywords if x in proxy.get("name", '')]))
            if has_keywords:
                removed_proxies.append(proxy.get("name"))
            else:
                proxies.append(proxy)
        if proxies:
            clash_config["proxies"] = proxies
        else:
            logger.warn(f"关键词过滤后无可用节点，跳过过滤")
            removed_proxies = []
        for proxy_group in clash_config.get("proxy-groups", []):
            proxy_group['proxies'] = [x for x in proxy_group.get('proxies') if x not in removed_proxies]
        clash_config["proxy-groups"] = [x for x in clash_config.get("proxy-groups", []) if x.get("proxies")]
        return clash_config

    def clash_config(self) -> Optional[Dict[str, Any]]:
        if not self._clash_config:
            return
        self.__insert_ruleset()
        self._top_rules = self._clash_rule_parser.to_string()
        clash_config = self._clash_config.copy()
        top_rules = []
        for rule in self._clash_rule_parser.rules:
            if (not isinstance(rule.action, Action) and
                    not len([x for x in self.clash_outbound(clash_config) if rule.action == x.get("name", '')])):
                logger.warn(f"出站 {rule.action} 不存在, 绕过 {rule.raw_rule}")
                continue
            top_rules.append(rule.raw_rule)
        clash_config["rules"] = self._top_rules + clash_config.get("rules", [])
        self._rule_provider = {}
        for r in self._clash_rule_parser.rules:
            if r.rule_type == RuleType.RULE_SET and r.payload.startswith(self._ruleset_prefix):
                action_str = f"{r.action.value}" if isinstance(r.action, Action) else r.action
                path_name = hashlib.sha256(action_str.encode('utf-8')).hexdigest()[:10]
                self._ruleset_names[path_name] = r.payload
                sub_url = (f"{self._movie_pilot_url}/api/v1/plugin/ClashRuleProvider/ruleset?"
                           f"name={path_name}&apikey={settings.API_TOKEN}")
                self._rule_provider[r.payload] = {"behavior": "classical",
                                                  "format": "yaml",
                                                  "interval": 3600,
                                                  "path": f"./CRP/{path_name}.yaml",
                                                  "type": "http",
                                                  "url": sub_url}
        if clash_config.get("rule-providers"):
            clash_config['rule-providers'].update(self._rule_provider)
        else:
            clash_config['rule-providers'] = self._rule_provider
        for key, item in self._ruleset_names.items():
            if item not in clash_config['rule-providers']:
                del self._ruleset_names[key]
        self.save_data('ruleset_names', self._ruleset_names)
        self.save_data('rule_provider', self._rule_provider)
        return clash_config
