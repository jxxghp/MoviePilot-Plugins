import asyncio
import json
import secrets
from typing import Any, Dict, List, Callable, Optional, Literal

import websockets
import yaml
from fastapi import HTTPException, Request, status, Response, Body
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from app import schemas
from app.core.config import settings
from app.log import logger

from .config import PluginConfig
from .models import ProxyGroup, Proxy, HostData, RuleData, RuleProvider, RuleProviderData
from .models.api import Connectivity, SubscriptionSetting, ConfigRequest
from .models.metadata import Metadata
from .models.types import RuleSet, DataSource
from .services import ClashRuleProviderService


class ApiCollection:
    def __init__(self):
        self.route_definitions = []

    def register(self, path: str,
                 methods: List[Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD', 'TRACE']],
                 allow_anonymous: Optional[bool] = None,
                 auth: Optional[str] = None,
                 summary: Optional[str] = '',
                 **kwargs):

        def decorator(func: Callable):
            route_meta: Dict[str, Any] = {
                'path': path,
                'methods': methods,
                'summary': summary,
                'endpoint': func,
                **kwargs
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

    @apis.register(path="/connectivity", methods=["POST"], auth="bear", summary="测试连接")
    async def test_connectivity(self, item: Connectivity) -> schemas.Response:
        success, message = await self.services.test_connectivity(item.clash_apis, item.sub_links)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/clash-outbound", methods=["GET"], auth="bear", summary="获取所有出站")
    def get_clash_outbound(self) -> schemas.Response:
        outbound = self.services.clash_outbound()
        return schemas.Response(success=True, data=outbound)

    @apis.register(path="/status", methods=["GET"], auth="bear", summary="插件状态")
    def get_status(self) -> schemas.Response:
        data = self.services.get_status()
        return schemas.Response(success=True, data=data)

    @apis.register(path="/rules/{ruleset}", methods=["GET"], auth="bear", summary="获取指定集合中的规则")
    def get_rules(self, ruleset: RuleSet) -> schemas.Response:
        data = self.services.get_rules(ruleset)
        return schemas.Response(success=True, data=data)

    @apis.register(path="/reorder-rules/{ruleset}/{target}", methods=["PUT"], auth="bear", summary="重新排序规则")
    def reorder_rules(self, ruleset: RuleSet, target: int,
                      moved_priority: int = Body(..., embed=True)) -> schemas.Response:
        success, message = self.services.reorder_rules(ruleset, moved_priority, target)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rules/{ruleset}/{priority}", methods=["PATCH"], auth="bear", summary="更新规则")
    def update_rule(self, ruleset: RuleSet, priority: int, rule_data: RuleData) -> schemas.Response:
        success, message = self.services.update_rule(ruleset, priority, rule_data)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rules/{ruleset}", methods=["POST"], auth="bear", summary="添加规则")
    def add_rule(self, ruleset: RuleSet, rule_data: RuleData = Body(...)) -> schemas.Response:
        success, message = self.services.add_rule(ruleset, rule_data)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rules/{ruleset}/{priority}/meta", methods=["PATCH"], auth="bear", summary="更新规则元数据")
    def update_rule_meta(self, ruleset: RuleSet, priority: int, meta: Metadata = Body(...)) -> schemas.Response:
        success, message = self.services.update_rule_meta(ruleset, priority, meta)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rules/{ruleset}/metadata/disabled", methods=["POST"], auth="bear", summary="设置规则状态")
    def set_rules_status(self, ruleset: RuleSet, priorities: dict[int, bool] = Body(...)):
        self.services.set_rules_status(ruleset, priorities)

    @apis.register(path="/rules/{ruleset}/{priority}", methods=["DELETE"], auth="bear", summary="删除规则")
    def delete_rule(self, ruleset: RuleSet, priority: int) -> schemas.Response:
        self.services.delete_rule(ruleset, priority)
        return schemas.Response(success=True)

    @apis.register(path="/rules/{ruleset}", methods=["DELETE"], auth="bear", summary="批量删除规则")
    def delete_rules(self, ruleset: RuleSet, priority: list[int] = Body(...)) -> schemas.Response:
        self.services.delete_rules(ruleset, priority)
        return schemas.Response(success=True)

    @apis.register(path="/refresh", methods=["PUT"], auth="bear", summary="更新订阅")
    async def refresh_subscription(self, url: str = Body(..., embed=True)) -> schemas.Response:
        success, message = await self.services.refresh_subscription(url)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rule-providers", methods=["GET"], auth="bear", summary="获取规则集合",
                   response_model=schemas.Response, response_model_exclude_none=True)
    def get_rule_providers(self) -> schemas.Response:
        return schemas.Response(success=True, data=self.services.state.all_rule_providers)

    @apis.register(path="/rule-providers/{name}", methods=["POST"], auth="bear", summary="添加规则集合")
    def add_rule_provider(self, name: str, item: RuleProvider):
        success, message = self.services.add_rule_provider(name, item)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rule-providers/{name}", methods=["PATCH"], auth="bear", summary="更新规则集合")
    def update_rule_provider(self, name: str, item: RuleProviderData):
        success, message = self.services.update_rule_provider(name, item)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rule-providers/{name}/meta", methods=["PATCH"], auth="bear", summary="更新规则集元数据")
    def update_rule_providers_meta(self, name: str, meta: Metadata):
        success, message = self.services.update_rule_providers_meta(name, meta)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/rule-providers/{name}", methods=["DELETE"], auth="bear", summary="删除规则集合")
    def delete_rule_provider(self, name: str):
        self.services.delete_rule_provider(name)
        return schemas.Response(success=True)

    @apis.register(path="/proxies", methods=["GET"], auth="bear", summary="获取代理",
                   response_model=schemas.Response, response_model_exclude_none=True)
    def get_proxies(self):
        proxies = self.services.get_proxies()
        return schemas.Response(success=True, data=proxies)

    @apis.register(path="/proxies/{name}", methods=["DELETE"], auth="bear", summary="删除出站代理")
    def delete_proxy(self, name: str):
        self.services.delete_proxy(name)
        return schemas.Response(success=True)

    @apis.register(path="/proxies", methods=["PUT"], auth="bear", summary="添加出站代理")
    def import_proxies(self, vehicle: Literal["YAML", "LINK"] = Body(...), payload: str = Body(...)):
        success, message = self.services.import_proxies(vehicle, payload)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxies/{name}", methods=["PATCH"], auth="bear", summary="更新出站代理")
    def update_proxy(self, name: str, source: DataSource = Body(...), proxy: Proxy = Body(...)) -> schemas.Response:
        success, message = self.services.update_proxy(name, source, proxy)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxies/{name}/meta", methods=["PATCH"], auth="bear", summary="更新代理组元数据")
    def update_proxy_meta(self, name: str, meta: Metadata):
        success, message = self.services.update_proxy_meta(name, meta)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxies/{name}/patch", methods=["DELETE"], auth="bear", summary="删除代理补丁")
    def delete_proxy_patch(self, name: str):
        success, message = self.services.delete_proxy_patch(name)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups", methods=["GET"], auth="bear", summary="获取代理组",
                   response_model=schemas.Response, response_model_exclude_none=True)
    def get_proxy_groups(self):
        proxy_groups = self.services.get_proxy_groups()
        return schemas.Response(success=True, data=proxy_groups)

    @apis.register(path="/proxy-groups/{name}", methods=["DELETE"], auth="bear", summary="删除代理组")
    def delete_proxy_group(self, name: str):
        success, message = self.services.delete_proxy_group(name)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups/{name}/meta", methods=["PATCH"], auth="bear", summary="更新代理组元数据")
    def update_proxy_group_meta(self, name: str, meta: Metadata):
        success, message = self.services.update_proxy_group_meta(name, meta)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups/{name}/patch", methods=["DELETE"], auth="bear", summary="删除代理组补丁")
    def delete_proxy_group_patch(self, name: str):
        success, message = self.services.delete_proxy_group_patch(name)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups", methods=["POST"], auth="bear", summary="添加代理组")
    def add_proxy_group(self, item: ProxyGroup):
        success, message = self.services.add_proxy_group(item)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-groups/{name}", methods=["PATCH"], auth="bear", summary="更新代理组")
    def update_proxy_group(self, name: str, source: DataSource = Body(...), proxy_group: ProxyGroup = Body(...)):
        success, message = self.services.update_proxy_group(name, source, proxy_group)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/proxy-providers", methods=["GET"], auth="bear", summary="获取代理集合",
                   response_model=schemas.Response, response_model_exclude_none=True)
    def get_proxy_providers(self):
        proxy_providers = self.services.state.all_proxy_providers
        return schemas.Response(success=True, data=proxy_providers)

    @apis.register(path="/ruleset", methods=["GET"], allow_anonymous=True, summary="获取规则集规则")
    def get_ruleset(self, name: str, apikey: str) -> PlainTextResponse:
        _apikey = self.config.apikey or settings.API_TOKEN
        if not secrets.compare_digest(_apikey, apikey):
            raise HTTPException(status_code=403, detail="Invalid API Key")
        res = self.services.get_ruleset(name)
        if not res:
            raise HTTPException(status_code=404, detail=f"Ruleset {name!r} not found")
        return PlainTextResponse(content=res, media_type="application/x-yaml")

    @apis.register(path="/import", methods=["POST"], auth="bear", summary="导入规则")
    def import_rules(self, vehicle: Literal["YAML"] = Body(...), payload: str = Body(...)):
        self.services.import_rules(vehicle, payload)
        return schemas.Response(success=True)

    @apis.register(path="/hosts", methods=["GET"], auth="bear", summary="获取 Hosts")
    def get_hosts(self):
        return schemas.Response(success=True, data=self.services.state.hosts.model_dump(mode='json'))

    @apis.register(path="/hosts", methods=["POST"], auth="bear", summary="更新 Hosts")
    def update_hosts(self, domain: str = Body(..., embed=True), host: HostData = Body(...)):
        success, message = self.services.update_hosts(domain, host)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/hosts/{domain}", methods=["DELETE"], auth="bear", summary="删除 Hosts")
    def delete_host(self, domain: str):
        success, message = self.services.delete_host(domain)
        return schemas.Response(success=success, message=message)

    @apis.register(path="/subscription-info", methods=["POST"], auth="bear", summary="更新订阅信息")
    def update_subscription_info(self, sub_info: SubscriptionSetting):
        self.services.update_subscription_info(sub_info)
        return schemas.Response(success=True)

    @apis.register(path="/config", methods=["GET"], allow_anonymous=bool(True), summary="获取 Clash 配置")
    def get_clash_config(self, apikey: str, request: Request, identifier: str | None = None):
        _apikey = self.config.apikey or settings.API_TOKEN
        param = ConfigRequest(
            url=str(request.url),
            client_host=request.client.host,
            identifier=identifier,
            user_agent=request.headers.get("user-agent")
        )
        if not secrets.compare_digest(apikey, _apikey):
            raise HTTPException(status_code=403, detail="Invalid API Key")
        logger.info(f"{request.client.host} 正在获取配置")
        config = self.services.build_clash_config(param=param)
        if not config:
            raise HTTPException(status_code=500, detail="配置不可用")

        config_dict = config.model_dump(mode="json", by_alias=True, exclude_none=True)
        res = yaml.dump(config_dict, allow_unicode=True, sort_keys=False)
        sub_info = self.services.get_subscription_user_info()
        headers = {'Subscription-Userinfo': sub_info.header}
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
