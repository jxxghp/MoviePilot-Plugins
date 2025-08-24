import asyncio
import copy
import hashlib
import json
import math
import re
import time
import urllib
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict, Tuple, Union
from urllib.parse import urlparse

import pytz
import websockets
import yaml
from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.clashruleprovider.clashruleparser import Action, RuleType, ClashRule, MatchRule, LogicRule
from app.plugins.clashruleprovider.clashruleparser import ClashRuleParser, Converter
from app.plugins.clashruleprovider.clashruleparser import ProxyGroup, RuleProvider
from app.schemas.types import EventType
from app.schemas.types import NotificationType
from app.utils.http import RequestUtils, AsyncRequestUtils
from app.utils.ip import IpUtils
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException, Request, status, Body, Response
from sse_starlette.sse import EventSourceResponse


class ClashRuleProvider(_PluginBase):
    # 插件名称
    plugin_name = "Clash Rule Provider"
    # 插件描述
    plugin_desc = "随时为Clash添加一些额外的规则。"
    # 插件图标
    plugin_icon = "Mihomo_Meta_A.png"
    # 插件版本
    plugin_version = "1.3.3"
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
    _movie_pilot_url = ''
    _cron = ''
    _timeout = 10
    _retry_times = 3
    _filter_keywords = []
    _auto_update_subscriptions = True
    _ruleset_prefix: str = '📂<='
    _group_by_region: bool = False
    _group_by_country: bool = False
    _refresh_delay: int = 5
    _discard_rules: bool = False
    _discard_proxy_groups: bool = False
    _enable_acl4ssr: bool = False
    _dashboard_components: List[str] = []
    _clash_template_yaml: str = ''
    _hint_geo_dat: bool = False
    # Cloudflare 优选 IPs 可通过外部设置
    _best_cf_ip: List[str] = []

    # 插件数据
    _top_rules: List[str] = []
    _ruleset_rules: List[str] = []
    _rule_provider: Dict[str, Any] = {}
    _extra_rule_providers: Dict[str, Any] = {}
    _subscription_info = {}
    _ruleset_names: Dict[str, str] = {}
    _proxy_groups = []
    _extra_proxies = []
    _acl4ssr_providers: Dict[str, Any] = {}
    _acl4ssr_prefix: str = '🗂️=>'
    # 保存每个订阅文件的原始内容
    _clash_configs: Dict[str, Any] = {}
    _hosts: List[Dict[str, Any]] = []

    # protected variables
    _clash_rule_parser = None
    _ruleset_rule_parser = None
    _clash_template: Optional[Dict[str, Any]] = None
    _scheduler: Optional[BackgroundScheduler] = None
    _countries: Optional[List[Dict[str, str]]] = None
    _geo_rules: Dict[str, List[str]] = {'geoip': [], 'geosite': []}

    def init_plugin(self, config: dict = None):
        self.stop_service()
        self._ruleset_rules = self.get_data("ruleset_rules")
        self._top_rules = self.get_data("top_rules")
        self._proxy_groups = self.get_data("proxy_groups") or []
        self._extra_proxies = self.get_data("extra_proxies") or []
        self._subscription_info = self.get_data("subscription_info") or {}
        self._rule_provider = self.get_data("rule_provider") or {}
        self._extra_rule_providers = self.get_data("extra_rule_providers") or {}
        self._ruleset_names = self.get_data("ruleset_names") or {}
        self._acl4ssr_providers = self.get_data("acl4ssr_providers") or {}
        self._clash_configs = self.get_data("clash_configs") or {}
        self._hosts = self.get_data("hosts") or []
        if config:
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._notify = config.get("notify"),
            self._sub_links = config.get("sub_links") or []
            self._clash_dashboard_url = config.get("clash_dashboard_url") or ''
            if self._clash_dashboard_url:
                self._clash_dashboard_url = self._clash_dashboard_url.rstrip("/")
            if not (self._clash_dashboard_url.startswith('http://') or
                    self._clash_dashboard_url.startswith('https://')):
                self._clash_dashboard_url = 'http://' + self._clash_dashboard_url
            self._clash_dashboard_secret = config.get("clash_dashboard_secret")
            self._movie_pilot_url = config.get("movie_pilot_url")
            if self._movie_pilot_url:
                self._movie_pilot_url = self._movie_pilot_url.rstrip("/")
            self._cron = config.get("cron_string") or '30 12 * * *'
            self._timeout = config.get("timeout")
            self._retry_times = config.get("retry_times") or 3
            self._filter_keywords = config.get("filter_keywords")
            self._ruleset_prefix = config.get("ruleset_prefix", "📂<=")
            self._acl4ssr_prefix = config.get("acl4ssr_prefix", "🗂️=>")
            self._auto_update_subscriptions = config.get("auto_update_subscriptions")
            self._group_by_region = config.get("group_by_region")
            self._group_by_country = config.get("group_by_country") or False
            self._refresh_delay = config.get("refresh_delay") or 5
            self._discard_rules = config.get("discard_rules") or False
            self._discard_proxy_groups = config.get("discard_proxy_groups") or False
            self._enable_acl4ssr = config.get("enable_acl4ssr") or False
            self._dashboard_components = config.get("dashboard_components") or []
            self._clash_template_yaml = config.get("clash_template") or ''
            self._hint_geo_dat = config.get("hint_geo_dat", False)
            self._best_cf_ip = config.get("best_cf_ip") or []
        self._clash_rule_parser = ClashRuleParser()
        self._ruleset_rule_parser = ClashRuleParser()
        self._clash_template = {}
        self._countries = []
        if self._enabled:
            try:
                self._clash_template = yaml.load(self._clash_template_yaml, Loader=yaml.SafeLoader) or {}
                if not isinstance(self._clash_template, dict):
                    self._clash_template = {}
                    logger.error(f"Invalid clash template yaml")
                # 规范配置模板
                self._clash_template['proxies'] = self._clash_template.get('proxies') or []
                self._clash_template['proxy-groups'] = self._clash_template.get('proxy-groups') or []
                self._clash_template['rule-providers'] = self._clash_template.get('rule-providers') or {}
                self._clash_template['rules'] = self._clash_template.get('rules') or []
            except yaml.YAMLError as exc:
                logger.error(f"Error loading clash template yaml: {exc}")
            if self._group_by_region:
                self._countries = ClashRuleProvider.__load_countries(
                    f"{settings.ROOT_PATH}/app/plugins/clashruleprovider/countries.json")
            self.__parse_config()
            # 清理不存在的 URL
            self._subscription_info = {url: self._subscription_info.get(url)
                                       for url in self._sub_links if self._subscription_info.get(url)}
            self._clash_configs = {url: self._clash_configs[url] for url in self._sub_links if
                                   self._clash_configs.get(url)}
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.start()
            # 更新订阅
            self._scheduler.add_job(self.refresh_subscriptions, "date",
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=2))
            if self._hint_geo_dat:
                self._scheduler.add_job(self.__refresh_geo_dat, "date",
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3))
            else:
                self._geo_rules = {'geoip': [], 'geosite': []}
            # 更新acl4ssr
            if self._enable_acl4ssr:
                self._scheduler.add_job(self.__refresh_acl4ssr, "date",
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=4))
            else:
                self._acl4ssr_providers = {}

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
                "path": "/clash-outbound",
                "endpoint": self.get_clash_outbound,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取所有出站",
                "description": "获取所有出站"
            },
            {
                "path": "/status",
                "endpoint": self.get_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "插件状态",
                "description": "插件状态"
            },
            {
                "path": "/rules",
                "endpoint": self.get_rules,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取指定集合中的规则",
                "description": "获取指定集合中的规则"
            },
            {
                "path": "/rules",
                "endpoint": self.update_rules,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "更新 Clash 规则",
                "description": "更新 Clash 规则"
            },
            {
                "path": "/reorder-rules",
                "endpoint": self.reorder_rules,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "重新排序两条规则",
                "description": "重新排序两条规则"
            },
            {
                "path": "/rule",
                "endpoint": self.update_rule,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "更新一条规则",
                "description": "更新一条规则"
            },
            {
                "path": "/rule",
                "endpoint": self.add_rule,
                "methods": ["POSt"],
                "auth": "bear",
                "summary": "添加一条规则",
                "description": "添加一条规则"
            },
            {
                "path": "/rule",
                "endpoint": self.delete_rule,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "删除一条规则",
                "description": "删除一条规则"
            },
            {
                "path": "/subscription",
                "endpoint": self.refresh_subscription,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "更新订阅",
                "description": "更新订阅"
            },
            {
                "path": "/rule-providers",
                "endpoint": self.get_rule_providers,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取规则集合",
                "description": "获取规则集合"
            },
            {
                "path": "/extra-rule-provider",
                "endpoint": self.update_extra_rule_provider,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "更新一个规则集合",
                "description": "更新一个规则集合"
            },
            {
                "path": "/extra-rule-provider",
                "endpoint": self.delete_extra_rule_provider,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "删除一个规则集合",
                "description": "删除一个规则集合"
            },
            {
                "path": "/extra-proxies",
                "endpoint": self.get_extra_proxies,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取附加出站代理",
                "description": "获取附加出站代理"
            },
            {
                "path": "/extra-proxies",
                "endpoint": self.delete_extra_proxy,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "删除一条出站代理",
                "description": "删除一条出站代理"
            },
            {
                "path": "/extra-proxies",
                "endpoint": self.add_extra_proxies,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "添加出站代理",
                "description": "添加出站代理"
            },
            {
                "path": "/proxy-groups",
                "endpoint": self.get_proxy_groups,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取代理组",
                "description": "获取代理组"
            },
            {
                "path": "/proxy-group",
                "endpoint": self.delete_proxy_group,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "删除一个代理组",
                "description": "删除一个代理组"
            },
            {
                "path": "/proxy-group",
                "endpoint": self.add_proxy_group,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "添加一个代理组",
                "description": "添加一个代理组"
            },
            {
                "path": "/proxy-group",
                "endpoint": self.update_proxy_group,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "更新一个代理组",
                "description": "更新一个代理组"
            },
            {
                "path": "/ruleset",
                "endpoint": self.get_ruleset,
                "methods": ["GET"],
                "summary": "获取规则集规则",
                "description": "获取规则集规则"
            },
            {
                "path": "/import",
                "endpoint": self.import_rules,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "导入规则",
                "description": "导入规则"
            },
            {
                "path": "/hosts",
                "endpoint": self.get_hosts,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取 Hosts",
                "description": "获取 Hosts"
            },
            {
                "path": "/host",
                "endpoint": self.update_hosts,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "更新 Host",
                "description": "更新 Host"
            },
            {
                "path": "/host",
                "endpoint": self.delete_host,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "删除一条 Host",
                "description": "删除一条 Host"
            },
            {
                "path": "/config",
                "endpoint": self.get_clash_config,
                "methods": ["GET"],
                "summary": "获取 Clash 配置",
                "description": "获取 Clash 配置"
            },
            {
                "path": "/clash/proxy/{path:path}",
                "auth": "bear",
                "endpoint": self.clash_proxy,
                "methods": ["GET"],
                "summary": "转发 Clash API 请求",
                "description": "转发 Clash API 请求"
            },
            {
                "path": "/clash/ws/{endpoint}",
                "endpoint": self.clash_websocket,
                "methods": ["GET"],
                "summary": "转发 Clash API Websocket 请求",
                "description": "转发 Clash API Websocket 请求",
                "allow_anonymous": True
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

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        components = [
            {
                "key": "clash_info",
                "name": "Clash Info"
            },
            {
                "key": "traffic_stats",
                "name": "Traffic Stats"
            }
        ]
        return [component for component in components if component.get("name") in self._dashboard_components]

    def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、全局配置参考：
        {
            "refresh": 10, // 自动刷新时间，单位秒
            "border": True, // 是否显示边框，默认True，为False时取消组件边框和边距，由插件自行控制
            "title": "组件标题", // 组件标题，如有将显示该标题，否则显示插件名称
            "subtitle": "组件子标题", // 组件子标题，缺省时不展示子标题
        }
        3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/

        kwargs参数可获取的值：1、user_agent：浏览器UA

        :param key: 仪表盘key，根据指定的key返回相应的仪表盘数据，缺省时返回一个固定的仪表盘数据（兼容旧版）
        """
        clash_available = bool(self._clash_dashboard_url and self._clash_dashboard_secret)
        components = {'clash_info': {'title': 'Clash Info', 'md': 4},
                      'traffic_stats': {'title': 'Traffic Stats', 'md': 8}}
        col_config = {'cols': 12, 'md': components.get(key, {}).get('md', 4)}
        global_config = {
            'title': components.get(key, {}).get('title', 'Clash Info'),
            'border': True,
            'clash_available': clash_available,
            'secret': self._clash_dashboard_secret,
        }
        return col_config, global_config, []

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        """
        退出插件
        """
        if self._scheduler:
            try:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
            except Exception as e:
                logger.error(f"退出插件失败：{e}")

    def get_service(self) -> List[Dict[str, Any]]:
        if self.get_state() and self._auto_update_subscriptions and self._sub_links:
            return [{
                "id": "ClashRuleProvider",
                "name": "定时更新订阅",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.refresh_subscription_service,
                "kwargs": {}
            }]
        return []

    def update_best_cf_ip(self, ips: List[str]):
        """
        通过深拷贝更新 Cloudflare 优选 IPs
        :param ips: Best Cloudflare IPs
        """
        self._best_cf_ip = [*ips]
        config = self.get_config()
        config['best_cf_ip'] = self._best_cf_ip
        self.update_config(config)

    def __save_data(self):
        self.__insert_ruleset()
        self._top_rules = self._clash_rule_parser.to_list()
        self._ruleset_rules = self._ruleset_rule_parser.to_list()
        self.save_data('ruleset_rules', self._ruleset_rules)
        self.save_data('top_rules', self._top_rules)
        self.save_data('subscription_info', self._subscription_info)
        self.save_data('ruleset_names', self._ruleset_names)
        self.save_data('rule_provider', self._rule_provider)
        self.save_data('proxy_groups', self._proxy_groups)
        self.save_data('extra_proxies', self._extra_proxies)
        self.save_data('extra_rule_providers', self._extra_rule_providers)
        self.save_data('acl4ssr_providers', self._acl4ssr_providers)
        self.save_data('clash_configs', self._clash_configs)
        self.save_data('hosts', self._hosts)

    def __parse_config(self):
        if self._top_rules is None:
            self._top_rules = []
        if self._ruleset_rules is None:
            self._ruleset_rules = []
        self._clash_rule_parser.parse_rules_from_list(self._top_rules)
        self._ruleset_rule_parser.parse_rules_from_list(self._ruleset_rules)

    async def clash_websocket(self, request: Request, endpoint: str, secret: str):
        if secret != self._clash_dashboard_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Secret 校验不通过"
            )
        if endpoint not in ['traffic', 'connections', 'memory']:
            raise HTTPException(status_code=400, detail="Invalid endpoint")
        queue = asyncio.Queue()
        ws_base = self._clash_dashboard_url.replace('http://', 'ws://').replace('https://', 'wss://')
        url = f"{ws_base}/{endpoint}?token={self._clash_dashboard_secret}"

        async def clash_ws_listener():
            try:
                async with websockets.connect(url, ping_interval=None) as ws:
                    async for message in ws:
                        data = json.loads(message)
                        await queue.put(data)
            except Exception as e:
                await queue.put({"error": str(e)})

        listener_task = asyncio.create_task(clash_ws_listener())

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await queue.get()
                        yield {
                            'event': endpoint,
                            'data': json.dumps(data)
                        }
                    except asyncio.CancelledError:
                        break
            finally:
                listener_task.cancel()  # 停止与 Clash 的连接

        return EventSourceResponse(event_generator())

    async def fetch_clash_data(self, endpoint: str) -> Dict:
        clash_headers = {"Authorization": f"Bearer {self._clash_dashboard_secret}"}
        url = f"{self._clash_dashboard_url}/{endpoint}"
        response = await AsyncRequestUtils().get_json(url, headers=clash_headers, timeout=10)
        if response is None:
            raise HTTPException(status_code=502, detail=f"Failed to fetch {endpoint}")
        return response

    async def clash_proxy(self, path: str) -> Dict:
        return await self.fetch_clash_data(path)

    async def test_connectivity(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message="")
        if not params.get('clash_dashboard_url') or not params.get('clash_dashboard_secret') \
                or not params.get('sub_links'):
            return schemas.Response(success=True, message="missing params")
        clash_version_url = f"{params.get('clash_dashboard_url')}/version"
        ret = await AsyncRequestUtils(accept_type="application/json",
                                      headers={"authorization": f"Bearer {params.get('clash_dashboard_secret')}"}
                                      ).get(clash_version_url)
        if ret is None:
            return schemas.Response(success=False, message="无法连接到Clash")
        for sub_link in (params.get('sub_links') or []):
            ret = await AsyncRequestUtils(accept_type="text/html",
                                          proxies=settings.PROXY if self._proxy else None
                                          ).get(sub_link)
            if ret is None:
                return schemas.Response(success=False, message=f"Unable to fetch {sub_link}")
        return schemas.Response(success=True, message="测试连接成功")

    def get_ruleset(self, name):
        if not self._ruleset_names.get(name):
            return None
        name = self._ruleset_names.get(name)
        rules = self.__get_ruleset(name)
        res = yaml.dump({"payload": rules}, allow_unicode=True)
        return Response(content=res, media_type="text/yaml")

    def get_clash_outbound(self) -> schemas.Response:
        outbound = self.clash_outbound()
        return schemas.Response(success=True, message="", data={"outbound": outbound})

    def get_status(self):
        first_config = self._clash_configs.get(self._sub_links[0], {}) if self._sub_links else {}
        rule_size = len(first_config.get("rules", []))
        return {"success": True, "message": "",
                "data": {"state": self._enabled,
                         "ruleset_prefix": self._ruleset_prefix,
                         "clash": {"rule_size": rule_size},
                         "best_cf_ip": self._best_cf_ip,
                         "geoRules": self._geo_rules,
                         "subscription_info": self._subscription_info,
                         "sub_url": f"{self._movie_pilot_url}/api/v1/plugin/ClashRuleProvider/config?"
                                    f"apikey={settings.API_TOKEN}"}}

    def get_clash_config(self, request: Request):
        logger.info(f"{request.client.host} 正在获取配置")
        config = self.clash_config()
        if not config:
            return {'success': False, "message": '配置不可用'}
        res = yaml.dump(config, allow_unicode=True)
        first_url = self._sub_links[0] if self._sub_links else None
        if not first_url:
            sub_info = {'upload': 0, 'download': 0, 'total': 0, 'expire': 0}
        else:
            sub_info = self._subscription_info.get(first_url, {})
        headers = {'Subscription-Userinfo': f'upload={sub_info.get("upload", 0)}; '
                                            f'download={sub_info.get("download", 0)}; '
                                            f'total={sub_info.get("total", 0)}; '
                                            f'expire={sub_info.get("expire", 0)}'}
        return Response(headers=headers, content=res, media_type="text/yaml")

    def get_hosts(self) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=True, message='', data={'hosts': []})
        return schemas.Response(success=True, message='', data={'hosts': self._hosts})

    def update_hosts(self, params: dict = Body(...)) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        domain = params.get('domain')
        if not domain:
            return schemas.Response(success=False, message=f"Invalid param: domain={domain}")
        # Search for the host with the same domain
        for i, host in enumerate(self._hosts):
            if host.get('domain') == domain:
                # Update the existing host
                self._hosts[i] = {**host, **params.get('value', {})}
                self.save_data('hosts', self._hosts)
                return schemas.Response(success=True, message=f'Host for domain {domain} updated successfully.')

        new_host = params.get('value', {})
        if not new_host.get('domain'):
            return schemas.Response(success=False, message=f"Invalid param: value={new_host}")
        self._hosts.append(new_host)
        self.save_data('hosts', self._hosts)

        return schemas.Response(success=True, message=f"New host for domain {domain} added successfully.")

    def delete_host(self, params: dict = Body(...)) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='Host deletion is disabled.')

        domain = params.get('domain')
        if not domain:
            return schemas.Response(success=False, message=f"Invalid param: domain={domain}")

        original_hosts_length = len(self._hosts)
        self._hosts = [host for host in self._hosts if host.get('domain') != domain]
        self.save_data('hosts', self._hosts)

        if len(self._hosts) < original_hosts_length:
            return schemas.Response(success=True, message=f'Host for domain {domain} deleted successfully.')
        else:
            return schemas.Response(success=False, message=f'Host for domain {domain} not found.')

    def get_rules(self, rule_type: str) -> schemas.Response:
        if rule_type == 'ruleset':
            return schemas.Response(success=True, message='', data={'rules': self._ruleset_rule_parser.to_dict()})
        return schemas.Response(success=True, message='', data={'rules': self._clash_rule_parser.to_dict()})

    def delete_rule(self, params: dict = Body(...)) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        if params.get('type') == 'ruleset':
            res = self.delete_rule_by_priority(params.get('priority'), self._ruleset_rule_parser)
            if res:
                self.__add_notification_job(
                    [f"{self._ruleset_prefix}{res.action.value if isinstance(res.action, Action) else res.action}", ])
        else:
            self.delete_rule_by_priority(params.get('priority'), self._clash_rule_parser)
        return schemas.Response(success=True, message='')

    def import_rules(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        rules: List[str] = []
        if params.get('type') == 'YAML':
            try:
                imported_rules = yaml.load(params["payload"], Loader=yaml.SafeLoader)
                if not isinstance(imported_rules, dict):
                    return schemas.Response(success=False, message='Invalid input')
                rules = imported_rules.get("rules", [])
            except yaml.YAMLError as err:
                return schemas.Response(success=False, message=f'YAML error: {err}')
        self.append_top_rules(rules)
        return schemas.Response(success=True)

    def reorder_rules(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        moved_priority = params.get('moved_priority')
        target_priority = params.get('target_priority')
        try:
            if params.get('type') == 'ruleset':
                self.__reorder_rules(self._ruleset_rule_parser, moved_priority, target_priority)
                self.__add_notification_job([f"{self._ruleset_prefix}{params.get('rule_data').get('action')}"])
            else:
                self.__reorder_rules(self._clash_rule_parser, moved_priority, target_priority)
        except Exception as e:
            return schemas.Response(success=False, message=str(e))
        return schemas.Response(success=True)

    def update_rules(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        if params.get('type') == 'ruleset':
            self.__update_rules(params.get('rules'), self._ruleset_rule_parser)
        else:
            self.__update_rules(params.get('rules'), self._clash_rule_parser)
        return schemas.Response(success=True)

    def update_rule(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        if params.get('type') == 'ruleset':
            original_rule = self._ruleset_rule_parser.get_rule_at_priority(params.get('priority'))
            res = self.update_rule_by_priority(params.get('rule_data'),
                                               params.get('priority'),
                                               self._ruleset_rule_parser)
            if res:
                ruleset_to_notify = [f"{self._ruleset_prefix}{params.get('rule_data').get('action')}"]
                if params.get('rule_data').get('action') != original_rule.action:
                    ruleset_to_notify.append(f"{self._ruleset_prefix}{original_rule.action}")
                self.__add_notification_job(ruleset_to_notify)
        else:
            res = self.update_rule_by_priority(params.get('rule_data'), params.get('priority'), self._clash_rule_parser)
        return schemas.Response(success=bool(res), message='')

    def add_rule(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        if params.get('type') == 'ruleset':
            res = self.add_rule_by_priority(params.get('rule_data'), self._ruleset_rule_parser)
            if res:
                self.__add_notification_job([f"{self._ruleset_prefix}{params.get('rule_data').get('action')}", ])
        else:
            res = self.add_rule_by_priority(params.get('rule_data'), self._clash_rule_parser)
        return schemas.Response(success=bool(res), message='')

    def refresh_subscription(self, params: Dict[str, Any]):
        if not self._enabled:
            return schemas.Response(success=False, message="")
        url = params.get('url')
        if not url:
            return schemas.Response(success=False, message="Missing params")
        config, info = self.__get_subscription(url)
        if not config:
            return schemas.Response(success=False, message=f"订阅链接 {url} 更新失败")
        self._clash_configs[url] = config
        self._subscription_info[url] = info
        self.save_data('clash_configs', self._clash_configs)
        self.save_data('subscription_info', self._subscription_info)
        return schemas.Response(success=True, message='订阅更新成功')

    def get_rule_providers(self) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=True, data=[])
        return schemas.Response(success=True, data=self.rule_providers())

    def update_extra_rule_provider(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        name = params.get('name')
        new_value = params.get('value')
        new_name = new_value.get('name')
        if not name or not new_name:
            return schemas.Response(success=False, message="Missing param: name")
        item = {}
        for key, value in new_value.items():
            if key == 'name' or value is None:
                continue
            if key == 'payload' and params.get('type') != 'inline':
                continue
            if value == '' or value is None:
                continue
            item[key] = value
        try:
            rule_provider = RuleProvider.parse_obj(item)
            if rule_provider.type == 'inline' and rule_provider.behavior == 'classical':
                for rule in rule_provider.payload:
                    clash_rule = ClashRuleParser.parse_rule_line(f"{rule},DIRECT")
                    if not clash_rule:
                        raise ValueError(f"Invalid clash_rule: {rule}")
        except Exception as e:
            error_message = f"Failed to save rule provider: {repr(e)}"
            logger.error(error_message)
            return schemas.Response(success=False, message=str(error_message))
        if name != new_name:
            self._extra_rule_providers.pop(name, None)
        self._extra_rule_providers[new_name] = item
        self.save_data('extra_rule_providers', self._extra_rule_providers)
        return schemas.Response(success=True)

    def delete_extra_rule_provider(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        name = params.get('name')
        if not name:
            return schemas.Response(success=False, message="Missing param: name")
        self._extra_rule_providers.pop(name, None)
        self.save_data('extra_rule_providers', self._extra_rule_providers)
        return schemas.Response(success=True)

    def get_proxy_groups(self) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=True, data={'proxy_groups': []})
        first_config = self._clash_configs.get(self._sub_links[0], {}) if self._sub_links else {}
        proxy_groups = []
        sources = ('Manual', 'Template', urlparse(self._sub_links[0]).hostname if self._sub_links else '', 'Region')
        groups = (self._proxy_groups, self._clash_template.get('proxy-groups', []),
                  first_config.get('proxy-groups', []), self.proxy_groups_by_region())
        for i, group in enumerate(groups):
            for proxy_group in group:
                proxy_group_copy = copy.deepcopy(proxy_group)
                proxy_group_copy['source'] = sources[i]
                proxy_groups.append(proxy_group_copy)
        return schemas.Response(success=True, data={'proxy_groups': proxy_groups})

    def get_extra_proxies(self) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=True, data={'extra_proxies': []})
        proxies = []
        for proxy in self._extra_proxies:
            proxy_copy = copy.deepcopy(proxy)
            proxy_copy['source'] = 'Manual'
            proxies.append(proxy_copy)
        for url, config in self._clash_configs.items():
            hostname = urlparse(url).hostname
            for proxy in config['proxies']:
                proxy_copy = copy.deepcopy(proxy)
                proxy_copy['source'] = hostname
                proxies.append(proxy_copy)
        for proxy in self._clash_template.get('proxies', []):
            proxy_copy = copy.deepcopy(proxy)
            proxy_copy['source'] = 'Template'
            proxies.append(proxy_copy)
        return schemas.Response(success=True, data={'extra_proxies': proxies})

    def add_extra_proxies(self, params: Dict[str, Any]):
        if not self._enabled:
            return schemas.Response(success=False, message='')
        extra_proxies: List = []
        if params.get('type') == 'YAML':
            try:
                imported_proxies = yaml.load(params["payload"], Loader=yaml.SafeLoader)
                if not imported_proxies or not isinstance(imported_proxies, dict):
                    return schemas.Response(success=False, message=f"Invalid input")
                if 'proxies' not in imported_proxies:
                    return schemas.Response(success=False, message=f"No field 'proxies' found")
                extra_proxies = imported_proxies.get("proxies", [])
            except Exception as err:
                return schemas.Response(success=False, message=f'YAML error: {err}')
        elif params.get('type') == 'LINK':
            try:
                links = params['payload'].strip().splitlines()
                extra_proxies = Converter.convert_v2ray(v2ray_link=links)
            except Exception as err:
                return schemas.Response(success=False, message=f'LINK error: {err}')
        if not extra_proxies:
            return schemas.Response(success=False, message='无可用节点')
        result = True
        message = ''
        try:
            for proxy in extra_proxies:
                name = proxy.get('name')
                if not name or any(x.get('name') == name for x in self.clash_outbound()):
                    logger.warning(f"The proxy name {name} already exists. Skipping ...")
                    message = f"The proxy name {name} already exists. Skipping ..."
                    result = False
                    continue
                required_fields = {'name', 'type', 'server', 'port'}
                if not required_fields.issubset(proxy.keys()):
                    missing = required_fields - proxy.keys()
                    logger.error(f"Required field is missing: {missing}")
                    message = f"Required field is missing: {missing}"
                    result = False
                    continue
                self._extra_proxies.append(proxy)
            self.save_data('extra_proxies', self._extra_proxies)
        except Exception as err:
            return schemas.Response(success=False, message=f'{err}')
        return schemas.Response(success=result, message=message)

    def delete_extra_proxy(self, params: dict = Body(...)) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        name = params.get('name')
        self._extra_proxies = [item for item in self._extra_proxies if item.get('name') != name]
        self.save_data('extra_proxies', self._extra_proxies)
        return schemas.Response(success=True, message='')

    def add_proxy_group(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        if 'proxy_group' not in params or params['proxy_group'] is None:
            return schemas.Response(success=False, message="Missing params")
        item = params['proxy_group']
        if not item.get('name') or any(x.get('name') == item.get('name') for x in self._proxy_groups):
            return schemas.Response(success=False, message=f"The proxy group name {item.get('name')} already exists")
        try:
            ProxyGroup.parse_obj(item)
        except Exception as e:
            error_message = f"Failed to parse proxy group: Invalid data={item}, error={repr(e)}"
            logger.error(error_message)
            return schemas.Response(success=False, message=str(error_message))
        new_item = {}
        for k, v in item.items():
            if v == '':
                continue
            if v is None:
                continue
            new_item[k] = v
        self._proxy_groups.append(new_item)
        self.save_data('proxy_groups', self._proxy_groups)
        return schemas.Response(success=True)

    def update_proxy_group(self, params: Dict[str, Any]) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        proxy_group = params.get('proxy_group', {})
        name = params.get('name')
        if not name or not proxy_group:
            return schemas.Response(success=False, message='Invalid params')
        try:
            ProxyGroup.parse_obj(proxy_group)
        except Exception as e:
            error_message = f"Failed to parse proxy group: Invalid data={proxy_group}, error={repr(e)}"
            logger.error(error_message)
            return schemas.Response(success=False, message=str(error_message))
        index = next((i for i, x in enumerate(self._proxy_groups) if x.get('name') == name), None)
        # whether new name exists
        new_name_index = next((i for i, x in enumerate(self._proxy_groups) if x.get('name') == proxy_group.get('name')),
                              None
                              )
        if new_name_index and new_name_index != index:
            return schemas.Response(success=False,
                                    message=f"The proxy group name {proxy_group.get('name')} already exists")
        new_item = {}
        for k, v in proxy_group.items():
            if v == '':
                continue
            if v is None:
                continue
            new_item[k] = v
        self._proxy_groups[index] = new_item
        self.save_data('proxy_groups', self._proxy_groups)
        return schemas.Response(success=True)

    def delete_proxy_group(self, params: dict = Body(...)) -> schemas.Response:
        if not self._enabled:
            return schemas.Response(success=False, message='')
        name = params.get('name')
        self._proxy_groups = [item for item in self._proxy_groups if item.get('name') != name]
        self.save_data('proxy_groups', self._proxy_groups)
        return schemas.Response(success=True, message='')

    def clash_outbound(self) -> Optional[List]:
        first_config = self._clash_configs.get(self._sub_links[0], {}) if self._sub_links else {}
        outbound = [{'name': proxy_group.get("name")} for proxy_group in first_config.get("proxy-groups", [])]
        outbound.extend([{'name': proxy.get("name")} for proxy in first_config.get("proxies", [])])
        if self._clash_template:
            if 'proxy-groups' in self._clash_template:
                outbound.extend(self._clash_template.get('proxy-groups') or [])
            if 'proxies' in self._clash_template:
                outbound.extend(self._clash_template.get('proxies') or [])
        if self._group_by_region:
            outbound.extend([{'name': proxy_group.get("name")} for proxy_group in self.proxy_groups_by_region()])
        outbound.extend([{'name': proxy.get("name")} for proxy in self._extra_proxies])
        outbound.extend([{'name': proxy_group.get("name")} for proxy_group in self._proxy_groups])
        return outbound

    def rule_providers(self) -> List[Dict[str, Any]]:
        first_config = self._clash_configs.get(self._sub_links[0], {}) if self._sub_links else {}
        hostname = urllib.parse.urlparse(self._sub_links[0]).hostname if self._sub_links else ''
        rule_providers = []
        provider_sources = (self._extra_rule_providers,
                            first_config.get('rule-providers', {}),
                            self._clash_template.get('rule-providers', {}),
                            self._acl4ssr_providers)
        source_names = ('Manual', hostname, 'Template', 'Auto', 'Acl4ssr')
        for i, provider in enumerate(provider_sources):
            for name, value in provider.items():
                rule_provider = copy.deepcopy(value)
                rule_provider['name'] = name
                rule_provider['source'] = source_names[i]
                rule_providers.append(rule_provider)
        return rule_providers

    def __update_rules(self, rules: List[Dict[str, Any]], rule_parser: ClashRuleParser):
        rule_parser.rules = []
        for rule in rules:
            clash_rule = ClashRuleParser.parse_rule_dict(rule)
            rule_parser.insert_rule_at_priority(clash_rule, rule.get('priority'))
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
        new_outbounds = []
        rules_existed = self._clash_rule_parser.filter_rules_by_lambda(
            lambda r: r.rule_type == RuleType.RULE_SET and r.payload.startswith(self._ruleset_prefix)
        )
        actions_existed = [ClashRuleParser.action_string(r.action) for r in rules_existed]
        for rule in self._ruleset_rule_parser.rules:
            action_str = ClashRuleParser.action_string(rule.action)
            if action_str not in outbounds:
                outbounds.append(action_str)
            if action_str not in new_outbounds and action_str not in actions_existed:
                new_outbounds.append(action_str)
        self._clash_rule_parser.remove_rules(lambda r: r.rule_type == RuleType.RULE_SET and
                                                       r.payload.startswith(self._ruleset_prefix) and
                                                       ClashRuleParser.action_string(r.action) not in outbounds
                                             )
        for outbound in new_outbounds:
            clash_rule = ClashRuleParser.parse_rule_line(f"RULE-SET,{self._ruleset_prefix}{outbound},{outbound}")
            if not self._clash_rule_parser.has_rule(clash_rule):
                self._clash_rule_parser.insert_rule_at_priority(clash_rule, 0)

    def append_top_rules(self, rules: List[str]) -> None:
        clash_rules = []
        for rule in rules:
            clash_rule = ClashRuleParser.parse_rule_line(rule)
            if not clash_rule:
                continue
            clash_rules.append(clash_rule)
        self._clash_rule_parser.append_rules(clash_rules)
        self._top_rules = self._clash_rule_parser.to_list()
        self.save_data('top_rules', self._top_rules)
        return

    def update_rule_by_priority(self, rule: Dict[str, Any], priority: int, rule_parser: ClashRuleParser) -> bool:
        if type(rule.get("priority")) is not int or type(priority) is not int:
            return False
        clash_rule = ClashRuleParser.parse_rule_dict(rule)
        if not clash_rule:
            logger.error(f"Failed to update rule at priority {priority}. Invalid clash rule: {rule!r}")
            return False
        res = rule_parser.update_rule_at_priority(clash_rule, priority)
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
        res = rule_parser.remove_rule_at_priority(priority)
        self.__save_data()
        return res

    @staticmethod
    def format_bytes(value_bytes):
        if value_bytes == 0:
            return '0 B'
        k = 1024
        sizes = ['B', 'KB', 'MB', 'GB', 'TB']
        i = math.floor(math.log(value_bytes) / math.log(k))
        return f"{value_bytes / math.pow(k, i):.2f} {sizes[i]}"

    @staticmethod
    def format_expire_time(timestamp):
        seconds_left = timestamp - int(time.time())
        days = seconds_left // 86400
        return f"{days}天后过期" if days > 0 else "已过期"

    def refresh_subscription_service(self):
        res = self.refresh_subscriptions()
        messages = []
        index = 1
        for url, result in res.items():
            try:
                host_name = urlparse(url).hostname
            except ValueError:
                host_name = url
            message = f"{index}. 「 {host_name} 」\n"
            index += 1
            if result:
                sub_info = self._subscription_info.get(url, {})
                if sub_info.get('total') is not None:
                    used = sub_info.get('download', 0) + sub_info.get('upload', 0)
                    remaining = sub_info.get('total', 0) - used
                    info = (f"节点数量: {sub_info.get('proxy_num', 0)}\n"
                            f"已用流量: {ClashRuleProvider.format_bytes(used)}\n"
                            f"剩余流量: {ClashRuleProvider.format_bytes(remaining)}\n"
                            f"总量: {ClashRuleProvider.format_bytes(sub_info.get('total', 0))}\n"
                            f"过期时间: {ClashRuleProvider.format_expire_time(sub_info.get('expire', 0))}")
                else:
                    info = ""
                message += f"订阅更新成功\n{info}"
            else:
                message += '订阅更新失败'
            messages.append(message)
        if self._notify:
            self.post_message(title=f"【{self.plugin_name}】",
                              mtype=NotificationType.Plugin,
                              text='\n'.join(messages)
                              )

    def __refresh_acl4ssr(self):
        logger.info(f"Refreshing ACL4SSR ...")
        # 配置参数
        owner = 'ACL4SSR'
        repo = 'ACL4SSR'
        paths = ['Clash/Providers', 'Clash/Providers/Ruleset']
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/%s"
        branch = 'master'
        for path in paths:
            response = RequestUtils().get_res(api_url % path, headers=settings.GITHUB_HEADERS, params={'ref': branch})
            if not response:
                return
            files = response.json()
            yaml_files = [f for f in files if f["type"] == "file" and f["name"].endswith((".yaml", ".yml"))]
            self._acl4ssr_providers = {}
            for f in yaml_files:
                name = f"{self._acl4ssr_prefix}{f['name'][:f['name'].rfind('.')]}"
                path = f"./ACL4SSR/{f['name']}"
                provider = {'type': 'http', 'path': path, 'url': f["download_url"], 'interval': 600,
                            'behavior': 'classical', 'format': 'yaml', 'size-limit': 0}
                if name not in self._acl4ssr_providers:
                    self._acl4ssr_providers[name] = provider
        self.save_data('acl4ssr_providers', self._acl4ssr_providers)

    def __refresh_geo_dat(self):
        logger.info(f"Refreshing Geo Rules ...")
        owner = 'MetaCubeX'
        repo = 'meta-rules-dat'
        branch = 'meta'
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/geo"
        resp = RequestUtils().get_res(api_url, headers=settings.GITHUB_HEADERS, params={'ref': branch})
        if not resp:
            return
        for path in resp.json():
            if path["type"] == "dir" and path["name"] in self._geo_rules:
                tree_sha = path["sha"]
                url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}"
                res = RequestUtils().get_res(url, headers=settings.GITHUB_HEADERS, params={'ref': branch})
                if not res:
                    continue
                tree = res.json()
                yaml_files = [item["path"][:item["path"].rfind('.')] for item in tree["tree"] if
                              item["type"] == "blob" and item['path'].endswith((".yaml", ".yml"))]
                self._geo_rules[path["name"]] = yaml_files

    def refresh_subscriptions(self) -> Dict[str, bool]:
        """
        更新全部订阅链接
        """
        all_proxies = []
        res = {}
        for index, url in enumerate(self._sub_links):
            config, sub_info = self.__get_subscription(url)
            self._subscription_info[url] = sub_info or {}
            if not config:
                res[url] = False
                continue
            res[url] = True
            self._clash_configs[url] = config
            all_proxies.extend(config.get("proxies", []))
        self.save_data('subscription_info', self._subscription_info)
        self.save_data('clash_configs', self._clash_configs)
        return res

    def __get_subscription(self, url: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not url:
            logger.error(f"Invalid links: {url}")
            return None, None
        logger.info(f"正在更新: {url}")
        ret = None
        for i in range(0, self._retry_times):
            ret = RequestUtils(accept_type="text/html",
                               proxies=settings.PROXY if self._proxy else None
                               ).get_res(url)
            if ret:
                break
        if not ret:
            logger.warn(f"更新失败: {url}.")
            return None, None
        try:
            rs: Dict[str, Any] = yaml.load(ret.content, Loader=yaml.FullLoader)
            if type(rs) is str:
                all_proxies = {'name': "All Proxies", 'type': 'select', 'include-all-proxies': True}
                proxies = Converter.convert_v2ray(ret.content)
                if not proxies:
                    raise ValueError(f"Unknown content: {rs}")
                rs = {'proxies': proxies, 'proxy-groups': [all_proxies, ]}
            logger.info(f"已更新: {url}. 节点数量: {len(rs['proxies'])}")
            if rs.get('rules') is None:
                rs['rules'] = []
            if self._discard_proxy_groups:
                rs['proxy-groups'] = []
            rs = self.__remove_nodes_by_keywords(rs)
        except Exception as e:
            logger.error(f"解析配置出错： {e}")
            return None, None

        sub_info = {'last_update': int(time.time()), 'proxy_num': len(rs.get('proxies', []))}
        if 'Subscription-Userinfo' in ret.headers:
            matches = re.findall(r'(\w+)=(\d+)', ret.headers['Subscription-Userinfo'])
            variables = {key: int(value) for key, value in matches}
            sub_info.update({
                'download': variables['download'],
                'upload': variables['upload'],
                'total': variables['total'],
                'expire': variables['expire']
            })
        return rs, sub_info

    def notify_clash(self, ruleset: str):
        """
        通知 Clash 刷新规则集
        """
        url = f'{self._clash_dashboard_url}/providers/rules/{ruleset}'
        RequestUtils(content_type="application/json",
                     headers={"authorization": f"Bearer {self._clash_dashboard_secret}"}
                     ).put(url)

    def proxy_groups_by_region(self) -> List[Dict[str, Any]]:
        return self.__group_by_region(self._countries, self.all_proxies())

    @staticmethod
    def __load_countries(file_path: str) -> List:
        try:
            countries = json.load(open(file_path))
        except Exception as e:
            logger.error(f"插件加载错误：{e}")
            return []
        return countries

    def __group_by_region(self, countries: List, proxies) -> List[Dict[str, Any]]:
        continent_groups = {}
        country_groups = {}
        continent_map = {
            '欧洲': 'Europe',
            '亚洲': 'Asia',
            '大洋洲': 'Oceania',
            '非洲': 'Africa',
            '北美洲': 'NorthAmerica',
            '南美洲': 'SouthAmerica'
        }
        proxy_groups = []
        hk = next(filter(lambda c: c['abbr'] == 'HK', countries),
                  {"abbr": "HK", "chinese": "中国香港特别行政区", "emoji": "🇭🇰"})
        tw = next(filter(lambda c: c['abbr'] == 'TW', countries),
                  {"abbr": "TW", "chinese": "中国台湾", "emoji": "🇹🇼"})
        for proxy_node in proxies:
            country = ClashRuleProvider.__country_from_node(countries, proxy_node['name'])
            if not country:
                continue
            if country.get("abbr") == "CN":
                if any(key in proxy_node["name"] for key in ("🇭🇰", "HK", "香港")):
                    country = hk
                if any(key in proxy_node["name"] for key in ("🇹🇼", "TW", "台湾")):
                    country = tw
            continent = continent_map[country.get('continent')]
            if self._group_by_region:
                continent_groups.setdefault(continent, []).append(proxy_node['name'])
            if self._group_by_country:
                country_groups.setdefault(f"{country.get('emoji')} {country.get('chinese')}", []).append(
                    proxy_node['name'])
        for continent, nodes in continent_groups.items():
            if len(nodes):
                proxy_group = {'name': continent, 'type': 'select', 'proxies': nodes}
                proxy_groups.append(proxy_group)
        excluded = ('中国', '香港', 'CN', 'HK', '🇨🇳', '🇭🇰')
        for continent_node in continent_groups.get('Asia', []):
            if any(x in continent_node for x in excluded):
                continue
            continent_groups.setdefault('AsiaExceptChina', []).append(continent_node)
        if continent_groups.get('AsiaExceptChina'):
            proxy_group = {'name': 'AsiaExceptChina', 'type': 'select', 'proxies': continent_groups['AsiaExceptChina']}
            proxy_groups.append(proxy_group)
        for country, nodes in country_groups.items():
            if len(nodes):
                proxy_group = {'name': country, 'type': 'select', 'proxies': nodes}
                proxy_groups.append(proxy_group)
        country_group = list(country_groups.keys())
        if country_group:
            proxy_groups.append({'name': '🏴‍☠️国家分组', 'type': 'select', 'proxies': country_group})

        return proxy_groups

    @staticmethod
    def __country_from_node(countries: List[Dict[str, str]], node_name: str) -> Optional[Dict[str, str]]:
        node_name_lower = node_name.lower()
        for country in countries:
            if country['emoji'] and country['emoji'] in node_name:
                return country
            elif (
                    country['chinese'] in node_name
                    or country['english'].lower() in node_name_lower
            ):
                return country

        return None

    def __add_notification_job(self, ruleset_names: List[str]):
        if not self._enabled or not self._scheduler:
            return
        for ruleset in ruleset_names:
            if ruleset in self._rule_provider:
                self._scheduler.add_job(self.notify_clash, "date",
                                        run_date=datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + timedelta(seconds=self._refresh_delay),
                                        args=[ruleset],
                                        id=f'CRP-notify-clash{ruleset}',
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
            proxy_group['proxies'] = [x for x in proxy_group.get('proxies', []) if x not in removed_proxies]
        return clash_config

    def all_proxies(self) -> List[Dict[str, Any]]:
        """
        所有出站代理
        """
        all_proxies = []
        for index, url in enumerate(self._sub_links):
            config = self._clash_configs.get(url, {})
            all_proxies.extend(config.get("proxies", []))
        all_proxies.extend(self._clash_template.get("proxies", []))
        all_proxies.extend(self._extra_proxies)
        return all_proxies

    @staticmethod
    def extend_with_name_checking(to_list: List[Dict[str, Any]], from_list: List[Dict[str, Any]]
                                  ) -> List[Dict[str, Any]]:
        """
        去除同名元素合并列表
        """
        for item in from_list:
            if any(p.get('name') == item.get('name', '') for p in to_list):
                logger.warn(f"Item named {item.get('name')!r} already exists. Skipping...")
                continue
            to_list.append(item)
        return to_list

    def clash_config(self) -> Optional[Dict[str, Any]]:
        """
        整理 clash 配置，返回配置字典
        """
        # 使用模板或第一个订阅
        first_config = self._clash_configs.get(self._sub_links[0], {}) if self._sub_links else {}
        proxies = []
        if not self._clash_template:
            clash_config = copy.deepcopy(first_config)
            clash_config['proxy-groups'] = []
            clash_config['rule-providers'] = {}
            clash_config['rules'] = []
        else:
            clash_config = copy.deepcopy(self._clash_template)
        clash_config['proxy-groups'] = ClashRuleProvider.extend_with_name_checking(clash_config.get('proxy-groups', []),
                                                                                   first_config.get('proxy-groups', []),
                                                                                   )
        clash_config['rules'] = clash_config.get('rules', [])
        if not self._discard_rules:
            clash_config['rules'] = first_config.get('rules', []) + clash_config['rules']

        clash_config['rule-providers'] = clash_config.get('rule-providers') or {}
        clash_config['rule-providers'].update(first_config.get('rule-providers', {}))

        for proxy in self.all_proxies():
            if any(p.get('name') == proxy.get('name', '') for p in proxies):
                logger.warn(f"Proxy named {proxy.get('name')!r} already exists. Skipping...")
                continue
            proxies.append(proxy)
        if proxies:
            clash_config['proxies'] = proxies
        self.__insert_ruleset()
        self._top_rules = self._clash_rule_parser.to_list()
        # 添加代理组
        proxy_groups = copy.deepcopy(self._proxy_groups)
        if proxy_groups:
            clash_config['proxy-groups'] = ClashRuleProvider.extend_with_name_checking(clash_config['proxy-groups'],
                                                                                       proxy_groups)
        # 添加按大洲代理组
        if self._group_by_region or self._group_by_country:
            groups_by_region = self.proxy_groups_by_region()
            if groups_by_region:
                clash_config['proxy-groups'] = ClashRuleProvider.extend_with_name_checking(clash_config['proxy-groups'],
                                                                                           groups_by_region)

        top_rules = []
        outbound_names = list(x.get("name") for x in self.clash_outbound())

        # 添加 extra rule providers
        if self._extra_rule_providers:
            clash_config['rule-providers'].update(self._extra_rule_providers)

        # 通过 ruleset rules 添加 rule-providers
        self._rule_provider = {}
        for rule in self._ruleset_rule_parser.rules:
            action_str = ClashRuleParser.action_string(rule.action)
            rule_provider_name = f'{self._ruleset_prefix}{action_str}'
            if rule_provider_name not in self._rule_provider:
                path_name = hashlib.sha256(action_str.encode('utf-8')).hexdigest()[:10]
                self._ruleset_names[path_name] = rule_provider_name
                sub_url = (f"{self._movie_pilot_url}/api/v1/plugin/ClashRuleProvider/ruleset?"
                           f"name={path_name}&apikey={settings.API_TOKEN}")
                self._rule_provider[rule_provider_name] = {"behavior": "classical",
                                                           "format": "yaml",
                                                           "interval": 3600,
                                                           "path": f"./CRP/{path_name}.yaml",
                                                           "type": "http",
                                                           "url": sub_url}
        clash_config['rule-providers'].update(self._rule_provider)
        # 添加规则
        for rule in self._clash_rule_parser.rules:
            if not isinstance(rule.action, Action) and rule.action not in outbound_names:
                logger.warn(f"出站 {rule.action} 不存在, 跳过 {rule.raw_rule}")
                continue
            if rule.rule_type == RuleType.RULE_SET:
                # 添加ACL4SSR Rules
                if rule.payload in self._acl4ssr_providers:
                    clash_config['rule-providers'][rule.payload] = self._acl4ssr_providers[rule.payload]
                if rule.payload not in clash_config.get('rule-providers', {}):
                    logger.warn(f"规则集合 {rule.payload!r} 不存在, 跳过 {rule.raw_rule!r}")
                    continue
            top_rules.append(rule.raw_rule)
        for raw_rule in clash_config.get("rules", []):
            rule = ClashRuleParser.parse_rule_line(raw_rule)
            if not rule:
                logger.warn(f"无效的规则 {raw_rule!r}, 跳过")
                continue
            if not isinstance(rule.action, Action) and rule.action not in outbound_names:
                logger.warn(f"出站 {rule.action!r} 不存在, 跳过 {rule.raw_rule!r}")
                continue
            top_rules.append(rule.raw_rule)
        clash_config["rules"] = top_rules

        # 添加 Hosts
        if self._hosts:
            clash_config.setdefault('hosts', {})
            new_hosts = {
                item['domain']: item.get('value', []) if not item.get('using_cloudflare') else self._best_cf_ip
                for item in self._hosts if item.get('domain')
            }
            clash_config["hosts"] = {**clash_config["hosts"], **new_hosts}

        if self._rule_provider:
            clash_config['rule-providers'] = clash_config.get('rule-providers') or {}
            clash_config['rule-providers'].update(self._rule_provider)

        key_to_delete = []
        for key, item in self._ruleset_names.items():
            if item not in clash_config.get('rule-providers', {}):
                key_to_delete.append(key)
        for key in key_to_delete:
            del self._ruleset_names[key]
        if not clash_config.get("rule-providers"):
            del clash_config["rule-providers"]
        self.save_data('ruleset_names', self._ruleset_names)
        self.save_data('rule_provider', self._rule_provider)
        return clash_config

    @property
    def best_cf_ipv4(self) -> List[str]:
        v4 = [ip for ip in self._best_cf_ip if IpUtils.is_ipv4(ip)]
        return v4

    @property
    def best_cf_ipv6(self) -> List[str]:
        v6 = [ip for ip in self._best_cf_ip if IpUtils.is_ipv6(ip)]
        return v6

    @eventmanager.register(EventType.PluginAction)
    def update_cloudflare_ips_handler(self, event: Event = None):
        event_data = event.event_data
        if not event_data or event_data.get("action") != "update_cloudflare_ips":
            return
        ips = event_data.get("ips")
        if isinstance(ips, str):
            ips = [ips]
        if isinstance(ips, list):
            logger.info(f"更新 Cloudflare 优选 IP ...")
            self.update_best_cf_ip(ips)
