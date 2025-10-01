import asyncio
import json
import secrets
from typing import Any, Dict, List, Callable, Optional, Literal

import websockets
import yaml
from fastapi import HTTPException, Request, status, Response
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from app import schemas
from app.core.config import settings
from app.log import logger

from .config import PluginConfig
from .models import ProxyGroup
from .models.api import RuleData, Connectivity, Subscription, RuleProviderData, SubscriptionInfo, HostData
from .services import ClashRuleProviderService


class ApiCollection:
    def __init__(self):
        self.route_definitions = []

    def register(self, path: str,
                 methods: List[Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD', 'TRACE']],
                 allow_anonymous: Optional[bool] = None,
                 auth: Optional[str] = None,
                 summary: Optional[str] = ''):

        def decorator(func: Callable):
            route_meta: Dict[str, Any] = {
                'path': path,
                'methods': methods,
                'summary': summary,
                'endpoint': func
            }
            if allow_anonymous is not None:
                route_meta['allow_anonymous'] = allow_anonymous
            if auth is not None:
                route_meta['auth'] = auth
            self.route_definitions.append(route_meta)
            return func

        return decorator

    def get_routes(self, instance: Any) -> List[Dict[str, Any]]:
        bound_routes = []
        for route in self.route_definitions:
            func_name = route['endpoint'].__name__
            bound_method = getattr(instance, func_name)
            bound_routes.append({**route, 'endpoint': bound_method})
        return bound_routes


apis = ApiCollection()


class ClashRuleProviderApi:

    def __init__(self, services: ClashRuleProviderService, config: PluginConfig):
        self.services: ClashRuleProviderService = services
        self.config = config

    @apis.register(path='/connectivity', methods=['POST'], auth='bear', summary='测试连接')
    async def test_connectivity(self, item: Connectivity) -> schemas.Response:
        success, message = await self.services.test_connectivity(item.clash_apis, item.sub_links)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/clash-outbound", methods=["GET"], auth="bear", summary="获取所有出站")
    def get_clash_outbound(self) -> schemas.Response:
        outbound = self.services.clash_outbound()
        return schemas.Response(success=True, data={"outbound": outbound})

    @apis.register(path="/status", methods=["GET"], auth="bear", summary="插件状态")
    def get_status(self) -> schemas.Response:
        data = self.services.get_status()
        return schemas.Response(success=True, data=data)

    @apis.register(path="/rules/{ruleset}", methods=["GET"], auth="bear", summary="获取指定集合中的规则")
    def get_rules(self, ruleset: Literal['ruleset', 'top']) -> schemas.Response:
        data = self.services.get_rules(ruleset)
        return schemas.Response(success=True, data={'rules': data})

    @apis.register(path="/reorder-rules/{ruleset}/{target_priority}", methods=["PUT"], auth="bear",
                   summary="重新排序规则")
    def reorder_rules(self, ruleset: Literal['ruleset', 'top'], target_priority: int,
                      rule_data: RuleData) -> schemas.Response:
        moved_priority = rule_data.priority
        success, message = self.services.reorder_rules(ruleset, moved_priority, target_priority)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rules/{ruleset}/{priority}", methods=["PATCH"], auth="bear", summary="更新规则")
    def update_rule(self, ruleset: Literal['ruleset', 'top'], priority: int, rule_data: RuleData) -> schemas.Response:
        success, message = self.services.update_rule(ruleset, priority, rule_data)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rules/{ruleset}", methods=["POST"], auth="bear", summary="添加规则")
    def add_rule(self, ruleset: Literal['ruleset', 'top'], rule_data: RuleData) -> schemas.Response:
        success, message = self.services.add_rule(ruleset, rule_data)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rules/{ruleset}/{priority}", methods=["DELETE"], auth="bear", summary="删除规则")
    def delete_rule(self, ruleset: Literal['ruleset', 'top'], priority: int) -> schemas.Response:
        self.services.delete_rule(ruleset, priority)
        return schemas.Response(success=True)

    @apis.register(path="/refresh", methods=["PUT"], auth="bear", summary="更新订阅")
    async def refresh_subscription(self, subscription: Subscription) -> schemas.Response:
        success, message = await self.services.refresh_subscription(subscription.url)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rule-providers", methods=["GET"], auth="bear", summary="获取规则集合")
    def get_rule_providers(self) -> schemas.Response:
        return schemas.Response(success=True, data=self.services.rule_providers())

    @apis.register(path="/rule-providers/{name}", methods=["POST"], auth="bear", summary="更新规则集合")
    def update_rule_provider(self, name: str, item: RuleProviderData):
        success, message = self.services.update_rule_provider(name, item)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rule-providers/{name}", methods=["DELETE"], auth="bear", summary="删除规则集合")
    def delete_rule_provider(self, name: str):
        self.services.delete_rule_provider(name)
        return schemas.Response(success=True)

    @apis.register(path="/proxies", methods=["GET"], auth="bear", summary="获取出站代理")
    def get_proxies(self):
        proxies = self.services.get_all_proxies_with_details()
        return schemas.Response(success=True, data={'proxies': proxies})

    @apis.register(path="/proxies/{name}", methods=["DELETE"], auth="bear", summary="删除出站代理")
    def delete_proxy(self, name: str):
        self.services.delete_proxy(name)
        return schemas.Response(success=True)

    @apis.register(path="/proxies", methods=["PUT"], auth="bear", summary="添加出站代理")
    def import_proxies(self, params: Dict[str, Any]):
        success, message = self.services.import_proxies(params)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxies/{name}", methods=["PATCH"], auth="bear", summary="更新出站代理")
    def update_proxy(self, name: str, param: Dict[str, Any]) -> schemas.Response:
        success, message = self.services.update_proxy(name, param)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups", methods=["GET"], auth="bear", summary="获取代理组")
    def get_proxy_groups(self):
        proxy_groups = self.services.get_all_proxy_groups_with_source()
        return schemas.Response(success=True, data={'proxy_groups': proxy_groups})

    @apis.register(path="/proxy-groups/{name}", methods=["DELETE"], auth="bear", summary="删除代理组")
    def delete_proxy_group(self, name: str):
        success, message = self.services.delete_proxy_group(name)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups", methods=["POST"], auth="bear", summary="添加代理组")
    def add_proxy_group(self, item: ProxyGroup):
        success, message = self.services.add_proxy_group(item)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups/{previous_name}", methods=["PATCH"], auth="bear", summary="更新代理组")
    def update_proxy_group(self, previous_name: str, item: ProxyGroup):
        success, message = self.services.update_proxy_group(previous_name, item)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-providers", methods=["GET"], auth="bear", summary="获取代理集合")
    def get_proxy_providers(self):
        proxy_providers = self.services.all_proxy_providers()
        return schemas.Response(success=True, data={'proxy_providers': proxy_providers})

    @apis.register(path="/ruleset", methods=["GET"], allow_anonymous=bool(True), summary="获取规则集规则")
    def get_ruleset(self, name: str, apikey: str) -> PlainTextResponse:
        _apikey = self.config.apikey or settings.API_TOKEN
        if not secrets.compare_digest(_apikey, apikey):
            raise HTTPException(status_code=403, detail="Invalid API Key")
        res = self.services.get_ruleset(name)
        if not res:
            raise HTTPException(status_code=404, detail=f"Ruleset {name!r} not found")
        return PlainTextResponse(content=res, media_type="application/x-yaml")

    @apis.register(path="/import", methods=["POST"], auth="bear", summary="导入规则")
    def import_rules(self, params: Dict[str, Any]):
        self.services.import_rules(params)
        return schemas.Response(success=True)

    @apis.register(path="/hosts", methods=["GET"], auth="bear", summary="获取 Hosts")
    def get_hosts(self):
        return schemas.Response(success=True, data={'hosts': self.services.get_hosts()})

    @apis.register(path="/hosts", methods=["POST"], auth="bear", summary="更新 Hosts")
    def update_hosts(self, host: HostData):
        success, message = self.services.update_hosts(host)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/hosts", methods=["DELETE"], auth="bear", summary="删除 Hosts")
    def delete_host(self, host: HostData):
        success, message = self.services.delete_host(host)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/subscription-info", methods=["POST"], auth="bear", summary="更新订阅信息")
    def update_subscription_info(self, sub_info: SubscriptionInfo):
        self.services.update_subscription_info(sub_info)
        return schemas.Response(success=True)

    @apis.register(path="/config", methods=["GET"], allow_anonymous=bool(True), summary="获取 Clash 配置")
    def get_clash_config(self, apikey: str, request: Request):
        _apikey = self.config.apikey or settings.API_TOKEN
        if not secrets.compare_digest(apikey, _apikey):
            raise HTTPException(status_code=403, detail="Invalid API Key")
        logger.info(f"{request.client.host} 正在获取配置")
        config = self.services.clash_config()
        if not config:
            raise HTTPException(status_code=500, detail="配置不可用")

        res = yaml.dump(config, allow_unicode=True, sort_keys=False)
        sub_info = self.services.get_subscription_user_info()
        headers = {'Subscription-Userinfo': f'upload={sub_info["upload"]}; download={sub_info["download"]}; '
                                            f'total={sub_info["total"]}; expire={sub_info["expire"]}'}
        return Response(headers=headers, content=res, media_type="text/yaml")

    @apis.register(path="/clash/proxy/{path:path}", methods=["GET"], auth="bear", summary="转发 Clash API 请求")
    async def clash_proxy(self, path: str):
        return await self.services.fetch_clash_data(path)

    @apis.register(path="/clash/ws/{endpoint}", methods=["GET"], allow_anonymous=True,
                   summary="转发 Clash API Websocket 请求")
    async def clash_websocket(self, request: Request, endpoint: str, secret: str):
        if not secrets.compare_digest(secret, self.config.dashboard_secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Secret 校验不通过")
        if endpoint not in ['traffic', 'connections', 'memory']:
            raise HTTPException(status_code=400, detail="Invalid endpoint")

        # This logic is highly coupled with the web framework, so it stays here.
        queue = asyncio.Queue()
        ws_base = self.config.dashboard_url.replace(
            'http://', 'ws://').replace('https://', 'wss://')
        url = f"{ws_base}/{endpoint}?token={self.config.dashboard_secret}"

        async def clash_ws_listener():
            try:
                async with websockets.connect(url, ping_interval=None) as ws:
                    async for message in ws:
                        await queue.put(json.loads(message))
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
                        yield {'event': endpoint, 'data': json.dumps(data)}
                    except asyncio.CancelledError:
                        break
            finally:
                listener_task.cancel()

        return EventSourceResponse(event_generator())
