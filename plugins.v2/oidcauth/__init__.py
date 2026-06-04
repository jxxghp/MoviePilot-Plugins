import hashlib
import json
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import schemas
from app.core.auth_bridge import create_plugin_auth_ticket
from app.core.config import settings
from app.db.models.user import User
from app.db.user_oper import get_current_active_user
from app.log import logger
from app.plugins import _PluginBase


class OidcAuth(_PluginBase):
    """
    OIDC 认证插件。
    """

    plugin_name = "OIDC 认证"
    plugin_desc = "通过 OpenID Connect Provider 为 MoviePilot 提供插件化登录与账号绑定。"
    plugin_icon = "Authelia_A.png"
    plugin_version = "0.1.0"
    plugin_author = "ui-beam-9,jxxghp"
    author_url = "https://github.com/ui-beam-9"
    plugin_label = "认证,OIDC,SSO"
    plugin_order = 36

    _STATE_TTL_SECONDS = 300
    _PLUGIN_ID = "OidcAuth"

    def __init__(self):
        """
        初始化插件运行状态。
        """
        super().__init__()
        self._enabled = False
        self._config: Dict[str, Any] = {}
        self._states: Dict[str, Dict[str, Any]] = {}
        self._state_lock = threading.RLock()

    def init_plugin(self, config: dict = None):
        """
        初始化插件配置。

        :param config: 插件配置
        """
        self._config = self._normalize_config(config or {})
        self._enabled = bool(self._config.get("enabled"))

    def get_state(self) -> bool:
        """
        获取插件启用状态。

        :return: 是否启用
        """
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        获取插件命令列表。

        :return: 命令列表
        """
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册插件 API。

        :return: API 路由声明列表
        """
        return [
            {
                "path": "/public/status",
                "endpoint": self.public_status,
                "methods": ["GET"],
                "summary": "查询 OIDC 登录公开状态",
                "allow_anonymous": True,
            },
            {
                "path": "/authorize",
                "endpoint": self.authorize,
                "methods": ["GET"],
                "summary": "发起 OIDC 登录",
                "allow_anonymous": True,
            },
            {
                "path": "/callback",
                "endpoint": self.callback,
                "methods": ["GET"],
                "summary": "OIDC 回调",
                "allow_anonymous": True,
            },
            {
                "path": "/status",
                "endpoint": self.status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询 OIDC 插件状态",
            },
            {
                "path": "/config",
                "endpoint": self.save_config_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存 OIDC 插件配置",
            },
            {
                "path": "/test",
                "endpoint": self.test_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "测试 OIDC Provider",
            },
            {
                "path": "/bind/start",
                "endpoint": self.bind_start,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "发起 OIDC 账号绑定",
            },
            {
                "path": "/unbind",
                "endpoint": self.unbind,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "解绑 OIDC 账号",
            },
        ]

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """
        声明插件使用 Vue 联邦组件。

        :return: 渲染模式与构建产物路径
        """
        return "vue", "dist/assets"

    def get_auth_providers(self) -> List[Dict[str, Any]]:
        """
        声明未登录页面可展示的认证入口。

        :return: 认证入口列表
        """
        if not self._is_login_ready():
            return []
        return [
            {
                "id": "oidc",
                "name": self._config.get("provider_name") or "OIDC 登录",
                "icon": "mdi-openid",
                "component": "AuthPage",
                "enabled": True,
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        返回 Vue 模式配置表单占位。

        :return: 表单配置与默认模型
        """
        return [], self._config

    def get_page(self) -> List[dict]:
        """
        返回 Vue 模式详情页占位。

        :return: 页面配置
        """
        return []

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """
        声明插件侧栏管理入口。

        :return: 侧栏导航项
        """
        if not self.get_state():
            return []
        return [
            {
                "nav_key": "main",
                "title": "OIDC 认证",
                "icon": "mdi-openid",
                "section": "system",
                "permission": "admin",
                "order": 47,
            }
        ]

    def stop_service(self):
        """
        停止插件服务。
        """
        with self._state_lock:
            self._states.clear()

    def public_status(self) -> schemas.Response:
        """
        查询匿名可见的 OIDC 登录状态。

        :return: 公开状态响应
        """
        return schemas.Response(
            success=True,
            data={
                "enabled": self._is_login_ready(),
                "name": self._config.get("provider_name") or "OIDC 登录",
                "icon": "mdi-openid",
            },
        )

    async def authorize(self, request: Request) -> RedirectResponse:
        """
        发起 OIDC 登录授权。

        :param request: 当前请求
        :return: IdP 授权跳转响应
        """
        self._ensure_login_ready()
        state = self._create_state(action="login")
        redirect_uri = self._callback_url(request)
        authorize_url = await self._build_authorize_url(redirect_uri=redirect_uri, state=state)
        return RedirectResponse(authorize_url)

    async def callback(
        self,
        request: Request,
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ) -> HTMLResponse:
        """
        处理 OIDC 登录或绑定回调。

        :param request: 当前请求
        :param code: 授权码
        :param state: CSRF state
        :param error: IdP 返回的错误码
        :param error_description: IdP 返回的错误描述
        :return: 回调 HTML
        """
        if error:
            return self._callback_html(False, "oidc_error", error_description or error)
        if not code or not state:
            return self._callback_html(False, "oidc_invalid_callback", "OIDC 回调参数不完整")
        state_data = self._pop_state(state)
        if not state_data:
            return self._callback_html(False, "oidc_invalid_state", "OIDC state 无效或已过期")
        try:
            redirect_uri = self._callback_url(request)
            token_data = await self._exchange_code(code=code, redirect_uri=redirect_uri)
            userinfo = await self._fetch_userinfo(token_data)
            sub = str(userinfo.get("sub") or "")
            if not sub:
                return self._callback_html(False, "oidc_no_sub", "OIDC 用户信息缺少 sub")
            action = state_data.get("action")
            if action == "bind":
                return self._handle_bind_callback(state_data=state_data, userinfo=userinfo, sub=sub)
            return self._handle_login_callback(userinfo=userinfo, sub=sub)
        except Exception as err:
            logger.error(f"OIDC 回调处理失败: {err}", exc_info=True)
            return self._callback_html(False, "oidc_error", str(err))

    def status(self, current_user: User = Depends(get_current_active_user)) -> schemas.Response:
        """
        查询当前用户绑定状态和管理员配置。

        :param current_user: 当前登录用户
        :return: 插件状态响应
        """
        binding = self._get_user_binding(current_user.id)
        data: Dict[str, Any] = {
            "public": {
                "enabled": self._is_login_ready(),
                "name": self._config.get("provider_name") or "OIDC 登录",
                "redirect_uri": self._configured_or_display_redirect_uri(),
            },
            "binding": {
                "bound": bool(binding),
                "masked_sub": self._mask_sub((binding or {}).get("sub")),
                "username": (binding or {}).get("username"),
                "email": (binding or {}).get("email"),
            },
            "is_superuser": bool(current_user.is_superuser),
        }
        if current_user.is_superuser:
            data["config"] = self._config.copy()
        return schemas.Response(success=True, data=data)

    def save_config_api(self, config: dict, current_user: User = Depends(get_current_active_user)) -> schemas.Response:
        """
        保存 OIDC 插件配置。

        :param config: 前端提交的配置
        :param current_user: 当前登录用户
        :return: 保存结果
        """
        if not current_user.is_superuser:
            raise HTTPException(status_code=403, detail="用户权限不足")
        normalized = self._normalize_config(config or {})
        self._config = normalized
        self._enabled = bool(normalized.get("enabled"))
        self.update_config(normalized)
        return schemas.Response(success=True, data={"config": normalized})

    async def test_api(self, body: dict, current_user: User = Depends(get_current_active_user)) -> schemas.Response:
        """
        测试 OIDC Provider 发现文档。

        :param body: 待测试配置
        :param current_user: 当前登录用户
        :return: 测试结果
        """
        if not current_user.is_superuser:
            raise HTTPException(status_code=403, detail="用户权限不足")
        test_config = self._normalize_config({**self._config, **(body or {})})
        try:
            discovery = await self._get_discovery(test_config)
            missing = [
                key
                for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint")
                if not discovery.get(key)
            ]
            if missing:
                return schemas.Response(success=False, message=f"发现文档缺少端点: {', '.join(missing)}")
            return schemas.Response(success=True, message="OIDC Provider 连接正常")
        except Exception as err:
            return schemas.Response(success=False, message=str(err))

    async def bind_start(
        self,
        request: Request,
        current_user: User = Depends(get_current_active_user),
    ) -> schemas.Response:
        """
        发起当前用户的 OIDC 绑定流程。

        :param request: 当前请求
        :param current_user: 当前登录用户
        :return: 授权地址
        """
        self._ensure_login_ready()
        if self._get_user_binding(current_user.id):
            return schemas.Response(success=False, message="当前用户已绑定 OIDC 账号")
        state = self._create_state(action="bind", user_id=current_user.id)
        redirect_uri = self._callback_url(request)
        authorize_url = await self._build_authorize_url(redirect_uri=redirect_uri, state=state)
        return schemas.Response(success=True, data={"authorize_url": authorize_url})

    def unbind(self, current_user: User = Depends(get_current_active_user)) -> schemas.Response:
        """
        解绑当前用户的 OIDC 账号。

        :param current_user: 当前登录用户
        :return: 解绑结果
        """
        binding = self._get_user_binding(current_user.id)
        if not binding:
            return schemas.Response(success=False, message="当前用户未绑定 OIDC 账号")
        self.del_data(self._sub_key(binding.get("issuer") or "", binding.get("sub") or ""))
        self.del_data(self._user_key(current_user.id))
        return schemas.Response(success=True)

    def _normalize_config(self, config: dict) -> Dict[str, Any]:
        """
        规范化插件配置。

        :param config: 原始配置
        :return: 规范化后的配置
        """
        return {
            "enabled": bool(config.get("enabled")),
            "provider_name": str(config.get("provider_name") or "OIDC 登录"),
            "issuer": str(config.get("issuer") or "").strip().rstrip("/"),
            "client_id": str(config.get("client_id") or "").strip(),
            "client_secret": str(config.get("client_secret") or ""),
            "scopes": str(config.get("scopes") or "openid profile email").strip(),
            "redirect_uri": str(config.get("redirect_uri") or "").strip(),
            "username_claim": str(config.get("username_claim") or "preferred_username").strip(),
            "email_claim": str(config.get("email_claim") or "email").strip(),
            "allow_auto_bind_by_username": bool(config.get("allow_auto_bind_by_username")),
        }

    def _is_login_ready(self) -> bool:
        """
        判断 OIDC 登录是否具备最小可用配置。

        :return: 是否可用
        """
        return bool(
            self._enabled
            and self._config.get("issuer")
            and self._config.get("client_id")
            and self._config.get("client_secret")
        )

    def _ensure_login_ready(self) -> None:
        """
        确认 OIDC 登录已可用。
        """
        if not self._is_login_ready():
            raise HTTPException(status_code=400, detail="OIDC 登录未启用或配置不完整")

    async def _get_discovery(self, config: Optional[dict] = None) -> dict:
        """
        获取 OIDC Provider 发现文档。

        :param config: 指定配置，未传入时使用当前配置
        :return: 发现文档
        """
        oidc_config = config or self._config
        issuer = str(oidc_config.get("issuer") or "").rstrip("/")
        if not issuer:
            raise ValueError("OIDC issuer 未配置")
        discovery_url = (
            issuer
            if issuer.endswith("/.well-known/openid-configuration")
            else f"{issuer}/.well-known/openid-configuration"
        )
        async with httpx.AsyncClient(timeout=10.0, proxy=settings.PROXY_HOST) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            return response.json()

    async def _build_authorize_url(self, redirect_uri: str, state: str) -> str:
        """
        构造 OIDC 授权地址。

        :param redirect_uri: 回调地址
        :param state: CSRF state
        :return: 授权地址
        """
        discovery = await self._get_discovery()
        authorization_endpoint = discovery.get("authorization_endpoint")
        if not authorization_endpoint:
            raise ValueError("OIDC 发现文档缺少 authorization_endpoint")
        params = {
            "client_id": self._config.get("client_id"),
            "response_type": "code",
            "scope": self._config.get("scopes") or "openid profile email",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{authorization_endpoint}?{urlencode(params)}"

    async def _exchange_code(self, code: str, redirect_uri: str) -> dict:
        """
        使用授权码换取 Token。

        :param code: 授权码
        :param redirect_uri: 回调地址
        :return: Token 响应
        """
        discovery = await self._get_discovery()
        token_endpoint = discovery.get("token_endpoint")
        if not token_endpoint:
            raise ValueError("OIDC 发现文档缺少 token_endpoint")
        async with httpx.AsyncClient(timeout=10.0, proxy=settings.PROXY_HOST) as client:
            response = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._config.get("client_id"),
                    "client_secret": self._config.get("client_secret"),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()

    async def _fetch_userinfo(self, token_data: dict) -> dict:
        """
        使用 Access Token 获取用户信息。

        :param token_data: Token 响应
        :return: 用户信息
        """
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("OIDC Token 响应缺少 access_token")
        discovery = await self._get_discovery()
        userinfo_endpoint = discovery.get("userinfo_endpoint")
        if not userinfo_endpoint:
            raise ValueError("OIDC 发现文档缺少 userinfo_endpoint")
        async with httpx.AsyncClient(timeout=10.0, proxy=settings.PROXY_HOST) as client:
            response = await client.get(userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"})
            response.raise_for_status()
            return response.json()

    def _handle_login_callback(self, userinfo: dict, sub: str) -> HTMLResponse:
        """
        处理 OIDC 登录回调。

        :param userinfo: OIDC 用户信息
        :param sub: OIDC subject
        :return: 回调 HTML
        """
        issuer = self._config.get("issuer") or ""
        binding = self.get_data(self._sub_key(issuer, sub))
        user = User.get(db=None, rid=(binding or {}).get("user_id")) if binding else None
        if not user and self._config.get("allow_auto_bind_by_username"):
            user = self._auto_bind_by_username(userinfo=userinfo, sub=sub)
        if not user:
            return self._callback_html(False, "oidc_unbound", "该 OIDC 账号尚未绑定 MoviePilot 用户")
        if not user.is_active:
            return self._callback_html(False, "user_inactive", "用户已被禁用")
        ticket = create_plugin_auth_ticket(
            user_id=user.id,
            provider_id=f"{self._PLUGIN_ID}:oidc",
            metadata={"sub": sub, "issuer": issuer},
        )
        return self._callback_html(True, data={"ticket": ticket})

    def _handle_bind_callback(self, state_data: dict, userinfo: dict, sub: str) -> HTMLResponse:
        """
        处理 OIDC 绑定回调。

        :param state_data: state 中保存的绑定上下文
        :param userinfo: OIDC 用户信息
        :param sub: OIDC subject
        :return: 回调 HTML
        """
        user_id = state_data.get("user_id")
        user = User.get(db=None, rid=user_id) if user_id else None
        if not user or not user.is_active:
            return self._callback_html(False, "bind_user_invalid", "绑定用户不存在或已禁用", event_type="oidcauth_bind_callback")
        issuer = self._config.get("issuer") or ""
        existing = self.get_data(self._sub_key(issuer, sub))
        if existing and existing.get("user_id") != user.id:
            return self._callback_html(False, "bind_conflict", "该 OIDC 账号已绑定其他用户", event_type="oidcauth_bind_callback")
        if self._get_user_binding(user.id):
            return self._callback_html(False, "already_bound", "当前用户已绑定 OIDC 账号", event_type="oidcauth_bind_callback")
        binding = self._binding_payload(user_id=user.id, userinfo=userinfo, sub=sub)
        self.save_data(self._user_key(user.id), binding)
        self.save_data(self._sub_key(issuer, sub), binding)
        return self._callback_html(True, data={"bound": True}, event_type="oidcauth_bind_callback")

    def _auto_bind_by_username(self, userinfo: dict, sub: str) -> Optional[User]:
        """
        按用户名 claim 自动绑定已有用户。

        :param userinfo: OIDC 用户信息
        :param sub: OIDC subject
        :return: 绑定成功的用户
        """
        username = str(userinfo.get(self._config.get("username_claim") or "preferred_username") or "").strip()
        if not username:
            return None
        user = User.get_by_name(db=None, name=username)
        if not user or not user.is_active or self._get_user_binding(user.id):
            return None
        binding = self._binding_payload(user_id=user.id, userinfo=userinfo, sub=sub)
        issuer = self._config.get("issuer") or ""
        self.save_data(self._user_key(user.id), binding)
        self.save_data(self._sub_key(issuer, sub), binding)
        return user

    def _binding_payload(self, user_id: int, userinfo: dict, sub: str) -> dict:
        """
        构造绑定数据。

        :param user_id: 本地用户 ID
        :param userinfo: OIDC 用户信息
        :param sub: OIDC subject
        :return: 绑定数据
        """
        return {
            "user_id": user_id,
            "issuer": self._config.get("issuer") or "",
            "sub": sub,
            "username": userinfo.get(self._config.get("username_claim") or "preferred_username"),
            "email": userinfo.get(self._config.get("email_claim") or "email"),
            "updated_at": int(time.time()),
        }

    def _create_state(self, action: str, user_id: Optional[int] = None) -> str:
        """
        创建并缓存 OIDC state。

        :param action: login 或 bind
        :param user_id: 绑定用户 ID
        :return: state 字符串
        """
        state = secrets.token_urlsafe(32)
        with self._state_lock:
            self._cleanup_states()
            self._states[state] = {
                "action": action,
                "user_id": user_id,
                "created_at": time.time(),
            }
        return state

    def _pop_state(self, state: str) -> Optional[dict]:
        """
        取出并删除 OIDC state。

        :param state: state 字符串
        :return: state 数据
        """
        with self._state_lock:
            data = self._states.pop(state, None)
            self._cleanup_states()
        if not data:
            return None
        if time.time() - float(data.get("created_at") or 0) > self._STATE_TTL_SECONDS:
            return None
        return data

    def _cleanup_states(self) -> None:
        """
        清理过期 state。
        """
        now = time.time()
        expired = [
            key
            for key, value in self._states.items()
            if now - float(value.get("created_at") or 0) > self._STATE_TTL_SECONDS
        ]
        for key in expired:
            self._states.pop(key, None)

    def _callback_url(self, request: Request) -> str:
        """
        生成 OIDC 回调地址。

        :param request: 当前请求
        :return: 回调地址
        """
        if self._config.get("redirect_uri"):
            return self._config["redirect_uri"]
        path = f"{settings.API_V1_STR}/plugin/{self._PLUGIN_ID}/callback"
        if settings.MP_DOMAIN(path):
            return settings.MP_DOMAIN(path)
        return f"{str(request.base_url).rstrip('/')}{path}"

    def _configured_or_display_redirect_uri(self) -> str:
        """
        获取展示用回调地址。

        :return: 回调地址或默认路径
        """
        return self._config.get("redirect_uri") or f"{settings.API_V1_STR}/plugin/{self._PLUGIN_ID}/callback"

    def _get_user_binding(self, user_id: int) -> Optional[dict]:
        """
        获取用户绑定信息。

        :param user_id: 本地用户 ID
        :return: 绑定信息
        """
        return self.get_data(self._user_key(user_id))

    @staticmethod
    def _user_key(user_id: int) -> str:
        """
        构造用户绑定数据键。

        :param user_id: 本地用户 ID
        :return: 数据键
        """
        return f"binding:user:{user_id}"

    @staticmethod
    def _sub_key(issuer: str, sub: str) -> str:
        """
        构造 OIDC subject 反查数据键。

        :param issuer: OIDC issuer
        :param sub: OIDC subject
        :return: 数据键
        """
        digest = hashlib.sha256(f"{issuer}|{sub}".encode("utf-8")).hexdigest()
        return f"binding:sub:{digest}"

    @staticmethod
    def _mask_sub(sub: Optional[str]) -> str:
        """
        脱敏 OIDC subject。

        :param sub: OIDC subject
        :return: 脱敏字符串
        """
        if not sub:
            return ""
        value = str(sub)
        return f"{value[:6]}***" if len(value) > 6 else f"{value}***"

    def _callback_html(
        self,
        success: bool,
        error: Optional[str] = None,
        message: Optional[str] = None,
        data: Optional[dict] = None,
        event_type: str = "oidcauth_callback",
    ) -> HTMLResponse:
        """
        构造回调 HTML，通过 postMessage 通知插件联邦页面。

        :param success: 是否成功
        :param error: 错误码
        :param message: 错误信息
        :param data: 成功数据
        :param event_type: postMessage 事件类型
        :return: HTML 响应
        """
        payload = {
            "type": event_type,
            "success": success,
            "error": error,
            "message": message,
            "data": data or {},
        }
        payload_json = json.dumps(payload, ensure_ascii=False)
        html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>OIDC Callback</title></head>
<body>
<script>
(function() {{
  var payload = {payload_json};
  if (window.opener && !window.opener.closed) {{
    window.opener.postMessage(payload, window.location.origin);
    window.close();
  }} else {{
    document.body.innerText = payload.success ? '认证成功，请关闭此窗口' : (payload.message || '认证失败');
  }}
}})();
</script>
</body>
</html>"""
        return HTMLResponse(content=html)
