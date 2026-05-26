import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body

from app import schemas
from app.api.endpoints.plugin import register_plugin_api
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType, EventType


class AgentTokens(_PluginBase):
    """
    Agent Tokens 管理插件。

    通过 Agent LLM 供应商链式事件按优先级选择仍有 token 余量的供应商，
    并通过 Agent Tokens 用量广播事件回写实际消耗。
    """

    plugin_name = "Agent Tokens 管理"
    plugin_desc = "管理多平台免费 Token 配额，按优先级自动切换 Agent LLM 供应商。"
    plugin_icon = "agentresourceofficer.png"
    plugin_version = "1.0.8"
    plugin_author = "jxxghp"
    author_url = "https://github.com/jxxghp"
    plugin_config_prefix = "agenttokens_"
    plugin_order = 45
    auth_level = 1

    DATA_KEY_USAGE = "usage"

    def init_plugin(self, config: dict = None):
        """
        初始化插件配置，补齐供应商稳定 ID 以便后续用量能持续关联。
        """
        self._usage_lock = threading.RLock()
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._show_sidebar_nav = bool(config.get("show_sidebar_nav", True))
        self._providers = self._normalize_providers(config.get("providers") or [])
        self._save_config()

    def get_state(self) -> bool:
        """
        返回插件是否已启用。
        """
        return bool(getattr(self, "_enabled", False))

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        当前插件不注册远程命令。
        """
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册 Vue 界面需要调用的插件 API。
        """
        return [
            {
                "path": "/status",
                "endpoint": self.get_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取 Agent Tokens 状态",
            },
            {
                "path": "/config",
                "endpoint": self.save_config_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存 Agent Tokens 配置",
            },
            {
                "path": "/usage/reset",
                "endpoint": self.reset_usage_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "重置指定供应商用量",
            },
            {
                "path": "/usage/reset_all",
                "endpoint": self.reset_all_usage_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "重置全部供应商用量",
            },
        ]

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """
        声明插件使用 Vue 联邦组件渲染。
        """
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        Vue 模式下返回默认配置模型。
        """
        return [], self._current_config()

    def get_page(self) -> List[dict]:
        """
        Vue 模式下详情页由远程 Page 组件渲染。
        """
        return []

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """
        声明一个用量概览仪表板组件。
        """
        return [{"key": "usage", "name": "Agent Tokens 管理"}] if self.get_state() else []

    def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        返回 Vue 仪表板组件的布局与标题配置。
        """
        if not self.get_state():
            return None
        return (
            {"cols": 12, "md": 6},
            {
                "title": "Agent Tokens 管理",
                "subtitle": "LLM 配额使用情况",
                "refresh": 30,
                "border": True,
            },
            [],
        )

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """
        将 Agent Tokens 管理页注册到主界面侧栏。
        """
        if not self.get_state() or not getattr(self, "_show_sidebar_nav", True):
            return []
        return [
            {
                "nav_key": "main",
                "title": "Agent Tokens 管理",
                "icon": "mdi-key-chain",
                "section": "system",
                "permission": "manage",
                "order": 46,
            }
        ]

    def stop_service(self):
        """
        插件无后台服务，停用时无需清理额外资源。
        """
        pass

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        """
        将配置或事件中的数字字段安全转为整数。
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_text(value: Any) -> str:
        """
        清理配置中的文本字段，避免空白值参与供应商选择。
        """
        return str(value or "").strip()

    @staticmethod
    def _event_get(event_data: Any, key: str, default: Any = None) -> Any:
        """
        兼容读取 Pydantic 事件模型或字典中的字段。
        """
        if isinstance(event_data, dict):
            return event_data.get(key, default)
        return getattr(event_data, key, default)

    @staticmethod
    def _event_set(event_data: Any, key: str, value: Any) -> None:
        """
        兼容写入 Pydantic 事件模型或字典中的字段。
        """
        if isinstance(event_data, dict):
            event_data[key] = value
        else:
            setattr(event_data, key, value)

    @classmethod
    def _normalize_provider(cls, provider: dict, index: int) -> dict:
        """
        标准化单个供应商配置，并为旧配置补齐稳定 ID。
        """
        provider = provider or {}
        provider_id = cls._clean_text(provider.get("id")) or uuid.uuid4().hex
        token_limit = max(cls._to_int(provider.get("token_limit"), 0), 0)
        used_tokens = max(cls._to_int(provider.get("used_tokens"), 0), 0)
        priority = cls._to_int(provider.get("priority"), index + 1)
        return {
            "id": provider_id,
            "enabled": bool(provider.get("enabled", True)),
            "name": cls._clean_text(provider.get("name")) or f"Provider {index + 1}",
            "provider": cls._clean_text(
                provider.get("provider") or provider.get("llm_provider")
            ) or "openai",
            "base_url": cls._clean_text(provider.get("base_url")),
            "api_key": cls._clean_text(provider.get("api_key")),
            "user_agent": cls._clean_text(provider.get("user_agent")),
            "model": cls._clean_text(provider.get("model")),
            "token_limit": token_limit,
            "used_tokens": used_tokens,
            "priority": priority,
        }

    @classmethod
    def _normalize_providers(cls, providers: list) -> List[dict]:
        """
        标准化供应商列表并按优先级排序。
        """
        normalized = [
            cls._normalize_provider(provider, index)
            for index, provider in enumerate(providers or [])
            if isinstance(provider, dict)
        ]
        return sorted(normalized, key=lambda item: (item["priority"], item["name"]))

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        """
        生成 API Key 的脱敏展示文本。
        """
        if not api_key:
            return ""
        if len(api_key) <= 8:
            return "****"
        return f"{api_key[:4]}...{api_key[-4:]}"

    def _current_config(self) -> Dict[str, Any]:
        """
        返回当前插件配置快照。
        """
        return {
            "enabled": bool(getattr(self, "_enabled", False)),
            "show_sidebar_nav": bool(getattr(self, "_show_sidebar_nav", True)),
            "providers": list(getattr(self, "_providers", [])),
        }

    def _save_config(self) -> None:
        """
        保存当前插件配置，确保供应商 ID 的补齐结果能持久化。
        """
        self.update_config(self._current_config())

    def _load_usage(self) -> Dict[str, dict]:
        """
        读取已记录的供应商用量。
        """
        usage = self.get_data(self.DATA_KEY_USAGE) or {}
        return usage if isinstance(usage, dict) else {}

    def _save_usage(self, usage: Dict[str, dict]) -> None:
        """
        保存供应商用量数据。
        """
        self.save_data(self.DATA_KEY_USAGE, usage or {})

    def _provider_usage(self, provider: dict, usage: Optional[Dict[str, dict]] = None) -> dict:
        """
        汇总供应商的手工初始用量和 Agent 实际记录用量。
        """
        usage = usage if usage is not None else self._load_usage()
        provider_usage = usage.get(provider["id"], {}) or {}
        recorded_total = self._to_int(provider_usage.get("total_tokens"), 0)
        manual_used = self._to_int(provider.get("used_tokens"), 0)
        total_used = manual_used + recorded_total
        token_limit = self._to_int(provider.get("token_limit"), 0)
        remaining = None if token_limit <= 0 else max(token_limit - total_used, 0)
        percent = 0
        if token_limit > 0:
            percent = min(round(total_used * 100 / token_limit, 2), 100)
        return {
            "input_tokens": self._to_int(provider_usage.get("input_tokens"), 0),
            "output_tokens": self._to_int(provider_usage.get("output_tokens"), 0),
            "recorded_tokens": recorded_total,
            "manual_used_tokens": manual_used,
            "total_tokens": total_used,
            "token_limit": token_limit,
            "remaining_tokens": remaining,
            "usage_percent": percent,
            "model_call_count": self._to_int(provider_usage.get("model_call_count"), 0),
            "runs": self._to_int(provider_usage.get("runs"), 0),
            "success_count": self._to_int(provider_usage.get("success_count"), 0),
            "failure_count": self._to_int(provider_usage.get("failure_count"), 0),
            "last_used_at": provider_usage.get("last_used_at"),
            "last_error": provider_usage.get("last_error"),
            "exhausted": token_limit > 0 and total_used >= token_limit,
        }

    def _provider_status_rows(self) -> List[dict]:
        """
        构建前端展示用的供应商状态列表。
        """
        usage = self._load_usage()
        rows = []
        for provider in getattr(self, "_providers", []):
            provider_usage = self._provider_usage(provider, usage)
            rows.append({
                **provider,
                "masked_api_key": self._mask_api_key(provider.get("api_key", "")),
                "usage": provider_usage,
            })
        return rows

    def _summary(self) -> Dict[str, Any]:
        """
        汇总当前供应商数量和 token 使用情况。
        """
        rows = self._provider_status_rows()
        enabled_rows = [row for row in rows if row.get("enabled")]
        available_rows = [
            row for row in enabled_rows
            if not row["usage"].get("exhausted")
            and row.get("api_key")
            and row.get("model")
            and row.get("base_url")
        ]
        return {
            "enabled": self.get_state(),
            "provider_count": len(rows),
            "enabled_count": len(enabled_rows),
            "available_count": len(available_rows),
            "total_limit": sum(row["usage"]["token_limit"] for row in rows),
            "total_used": sum(row["usage"]["total_tokens"] for row in rows),
        }

    def _select_provider(self) -> Optional[dict]:
        """
        按优先级选择第一个启用且未耗尽 token 配额的供应商。
        """
        usage = self._load_usage()
        for provider in getattr(self, "_providers", []):
            if not provider.get("enabled"):
                continue
            if not provider.get("api_key") or not provider.get("model") or not provider.get("base_url"):
                continue
            provider_usage = self._provider_usage(provider, usage)
            if provider_usage["exhausted"]:
                continue
            return provider
        return None

    def get_status(self) -> schemas.Response:
        """
        获取插件配置、供应商用量和概览统计。
        """
        return schemas.Response(
            success=True,
            data={
                "config": self._current_config(),
                "providers": self._provider_status_rows(),
                "summary": self._summary(),
            },
        )

    def save_config_api(self, config: dict = Body(...)) -> schemas.Response:
        """
        保存前端提交的供应商配置。
        """
        try:
            self._enabled = bool(config.get("enabled"))
            self._show_sidebar_nav = bool(config.get("show_sidebar_nav", True))
            self._providers = self._normalize_providers(config.get("providers") or [])
            self._save_config()
            return schemas.Response(success=True, data=self.get_status().data)
        except Exception as err:
            logger.error(f"保存 Agent Tokens 配置失败: {err}")
            return schemas.Response(success=False, message=str(err))

    def reset_usage_api(self, payload: Optional[dict] = Body(default=None)) -> schemas.Response:
        """
        重置指定供应商的已记录用量。
        """
        payload = payload or {}
        provider_id = self._clean_text(payload.get("provider_id"))
        if not provider_id:
            return schemas.Response(success=False, message="缺少 provider_id")
        with self._usage_lock:
            usage = self._load_usage()
            usage.pop(provider_id, None)
            self._save_usage(usage)
        return schemas.Response(success=True, data=self.get_status().data)

    def reset_all_usage_api(self) -> schemas.Response:
        """
        重置所有供应商的已记录用量。
        """
        with self._usage_lock:
            self._save_usage({})
        return schemas.Response(success=True, data=self.get_status().data)

    @eventmanager.register(ChainEventType.AgentLLMProvider, priority=50)
    def select_llm_provider(self, event: Event):
        """
        响应 Agent LLM 供应商链式事件，写入当前可用供应商配置。
        """
        if not self.get_state() or not event or not event.event_data:
            return
        if self._event_get(event.event_data, "selected_provider_id"):
            return

        provider = self._select_provider()
        if not provider:
            logger.info("Agent Tokens 没有可用供应商，Agent 将使用系统 LLM 配置")
            return

        provider_name = provider.get("name")
        model = provider.get("model")
        logger.info(f"Agent Tokens 分配 LLM 供应商：[{provider_name}] 模型：[{model}]")

        self._event_set(event.event_data, "provider", provider.get("provider") or "openai")
        self._event_set(event.event_data, "base_url", provider.get("base_url"))
        self._event_set(event.event_data, "api_key", provider.get("api_key"))
        self._event_set(event.event_data, "user_agent", provider.get("user_agent"))
        self._event_set(event.event_data, "model", provider.get("model"))
        self._event_set(event.event_data, "base_url_preset", None)
        self._event_set(event.event_data, "selected_provider_id", provider.get("id"))
        self._event_set(event.event_data, "selected_provider_name", provider.get("name"))
        self._event_set(event.event_data, "source", self.__class__.__name__)

    @eventmanager.register(EventType.AgentTokensUsage)
    def record_tokens_usage(self, event: Event):
        """
        响应 Agent Tokens 用量广播事件，累计记录到对应供应商。
        """
        if not self.get_state() or not event or not event.event_data:
            return

        provider_id = self._clean_text(
            self._event_get(event.event_data, "selected_provider_id")
        )
        if not provider_id:
            return

        input_tokens = max(self._to_int(self._event_get(event.event_data, "input_tokens"), 0), 0)
        output_tokens = max(self._to_int(self._event_get(event.event_data, "output_tokens"), 0), 0)
        total_tokens = max(self._to_int(self._event_get(event.event_data, "total_tokens"), 0), 0)
        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens

        with self._usage_lock:
            usage = self._load_usage()
            record = usage.setdefault(provider_id, {})
            record["input_tokens"] = self._to_int(record.get("input_tokens"), 0) + input_tokens
            record["output_tokens"] = self._to_int(record.get("output_tokens"), 0) + output_tokens
            record["total_tokens"] = self._to_int(record.get("total_tokens"), 0) + total_tokens
            record["model_call_count"] = self._to_int(
                record.get("model_call_count"), 0
            ) + max(self._to_int(self._event_get(event.event_data, "model_call_count"), 0), 0)
            record["runs"] = self._to_int(record.get("runs"), 0) + 1
            if bool(self._event_get(event.event_data, "success", False)):
                record["success_count"] = self._to_int(record.get("success_count"), 0) + 1
                record["last_error"] = None
            else:
                record["failure_count"] = self._to_int(record.get("failure_count"), 0) + 1
                record["last_error"] = self._clean_text(self._event_get(event.event_data, "error"))
            record["last_model"] = self._clean_text(self._event_get(event.event_data, "model"))
            record["last_used_at"] = (
                self._clean_text(self._event_get(event.event_data, "finished_at"))
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            usage[provider_id] = record
            
            provider_name = self._clean_text(self._event_get(event.event_data, "selected_provider_name")) or provider_id
            logger.info(f"Agent Tokens 更新用量记录：供应商 [{provider_name}] 本次消耗了 {total_tokens} Tokens")
            
            self._save_usage(usage)

    @eventmanager.register(EventType.PluginReload)
    def reload(self, event: Event):
        """
        插件重载后重新注册动态 API。
        """
        if event.event_data.get("plugin_id") == self.__class__.__name__:
            register_plugin_api(plugin_id=self.__class__.__name__)
