import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.chatgpt.openai import OpenAi
from app.schemas import AgentLLMProviderEventData, AgentTokensUsageEventData, NotificationType
from app.schemas.types import ChainEventType, EventType


DEFAULT_RECOGNIZE_PROMPT = """
You are a media filename recognition engine for MoviePilot.

Parse the movie or TV filename provided by the user and return exactly one JSON object:
{"name":string,"version":string,"part":string,"year":string,"resolution":string,"season":number|null,"episode":number|null}

Rules:
- Return JSON only. Do not wrap it in Markdown and do not add explanations.
- Use the most likely official title in "name"; remove release group, source, codec, audio, subtitle, edition, and site tags.
- Preserve meaningful edition information such as Director's Cut, Extended, Theatrical, Remastered, IMAX, Uncut, or Part in "version" or "part".
- If the filename contains Chinese homophones, pinyin, initials, or letter substitutions, infer the most likely real Chinese title.
- Put a four-digit release year in "year" when it is clearly present; otherwise use an empty string.
- Put resolution such as 2160p, 1080p, 720p, 4K, UHD, or HD in "resolution" when present; otherwise use an empty string.
- For TV series, extract numeric season and episode when reliable. Use null when unknown or ambiguous.
- For movies, use null for both season and episode unless the filename clearly describes a split part.
""".strip()


class ChatGPT(_PluginBase):
    """
    ChatGPT 识别增强插件，仅保留媒体名称辅助识别能力。
    """

    MODEL_SOURCE_SYSTEM = "system"
    MODEL_SOURCE_AGENT_TOKENS = "agent_tokens"

    # 缓存数据 key
    _CACHE_DATA_KEY = "recognize_cache"
    # 内存缓存，避免频繁读取数据库
    _recognize_cache: Dict[str, dict] = {}

    # 插件名称
    plugin_name = "ChatGPT"
    # 插件描述
    plugin_desc = "使用 MoviePilot 系统智能助手或 Agent Tokens 管理插件的 LLM 配置增强媒体名称识别。"
    # 插件图标
    plugin_icon = "Chatgpt_A.png"
    # 插件版本
    plugin_version = "3.0.3"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "chatgpt_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    openai: Optional[OpenAi] = None
    _enabled = False
    _model_source = MODEL_SOURCE_SYSTEM
    _notify = False
    _customize_prompt = DEFAULT_RECOGNIZE_PROMPT

    def init_plugin(self, config: dict = None):
        """
        初始化插件配置并同步识别事件处理器状态。
        """
        config = config or {}

        enabled = bool(config.get("enabled"))
        if "recognize" in config:
            enabled = enabled and bool(config.get("recognize"))

        model_source = self._clean_text(config.get("model_source")) or self.MODEL_SOURCE_SYSTEM
        if model_source not in {self.MODEL_SOURCE_SYSTEM, self.MODEL_SOURCE_AGENT_TOKENS}:
            model_source = self.MODEL_SOURCE_SYSTEM

        self._enabled = enabled
        self._model_source = model_source
        self._notify = bool(config.get("notify"))
        self._customize_prompt = self._clean_text(config.get("customize_prompt")) or DEFAULT_RECOGNIZE_PROMPT
        self.openai = None

        # 初始化时从数据库加载缓存到内存
        self._load_cache_from_db()

        self._sync_event_handler_state()

    def _load_cache_from_db(self) -> None:
        """
        从数据库加载识别缓存到内存。
        """
        try:
            db_cache = self.get_data(self._CACHE_DATA_KEY)
            self._recognize_cache = db_cache if isinstance(db_cache, dict) else {}
            logger.info(f"ChatGPT 识别缓存已加载，共 {len(self._recognize_cache)} 条记录")
        except Exception as exc:
            logger.warning(f"ChatGPT 识别缓存加载失败: {exc}")
            self._recognize_cache = {}

    def _sync_event_handler_state(self) -> None:
        """
        按插件开关启用或禁用链式识别事件处理器。
        """
        try:
            if self._enabled:
                eventmanager.enable_event_handler(self.recognize)
            else:
                eventmanager.disable_event_handler(self.recognize)
        except Exception as exc:
            logger.debug(f"同步 ChatGPT 识别事件处理器状态失败: {exc}")

    def _get_cache_key(self, title: str) -> str:
        """
        生成缓存 key，使用标题的 MD5 哈希。
        """
        return hashlib.md5(title.encode("utf-8")).hexdigest()

    def _get_cached_result(self, title: str) -> Optional[dict]:
        """
        从内存缓存获取识别结果。
        """
        cache_key = self._get_cache_key(title)
        return self._recognize_cache.get(cache_key)

    def _cache_result(self, title: str, result: dict) -> None:
        """
        缓存识别结果，同时写入内存和数据库。
        """
        cache_key = self._get_cache_key(title)
        cache_entry = {
            "title": title,
            "name": result.get("name"),
            "year": result.get("year"),
            "season": result.get("season"),
            "episode": result.get("episode"),
        }
        # 写入内存
        self._recognize_cache[cache_key] = cache_entry
        # 写入数据库
        try:
            self.save_data(self._CACHE_DATA_KEY, self._recognize_cache)
        except Exception as exc:
            logger.warning(f"ChatGPT 识别缓存保存失败: {exc}")

    def clear_cache(self) -> dict:
        """
        清除识别缓存，同时清除内存和数据库。
        """
        # 清除内存
        self._recognize_cache = {}
        # 清除数据库
        try:
            self.save_data(self._CACHE_DATA_KEY, {})
        except Exception as exc:
            logger.warning(f"ChatGPT 识别缓存清除失败: {exc}")
        logger.info("ChatGPT 识别缓存已清除")
        return {"success": True, "message": "识别缓存已清除"}

    @staticmethod
    def _clean_text(value: Any) -> str:
        """
        清理配置或事件中的文本字段。
        """
        return str(value or "").strip()

    @staticmethod
    def _event_get(event_data: Any, key: str, default: Any = None) -> Any:
        """
        兼容读取字典或事件模型中的字段。
        """
        if isinstance(event_data, dict):
            return event_data.get(key, default)
        return getattr(event_data, key, default)

    @staticmethod
    def _event_set(event_data: Any, key: str, value: Any) -> None:
        """
        兼容写入字典或事件模型中的字段。
        """
        if isinstance(event_data, dict):
            event_data[key] = value
        else:
            setattr(event_data, key, value)

    def get_state(self) -> bool:
        """
        返回插件是否启用。
        """
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        当前插件不注册用户消息命令。
        """
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册插件 API。
        """
        return [
            {
                "path": "/clear_cache",
                "method": "GET",
                "func": self.clear_cache,
                "summary": "清除识别缓存",
            },
            {
                "path": "/cache_stats",
                "method": "GET",
                "func": self.get_cache_stats,
                "summary": "获取缓存统计",
            },
        ]

    def get_cache_stats(self) -> dict:
        """
        获取缓存统计信息。
        """
        return {"count": len(self._recognize_cache)}

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        构建只面向识别增强的插件配置页面。
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "插件仅在 MoviePilot 原生识别失败后参与名称识别增强，不再处理聊天消息。模型配置可直接使用系统智能助手设置，或通过 Agent Tokens 管理插件动态分配。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用识别增强",
                                            "hint": "开启后监听媒体名称辅助识别链式事件",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "调用失败通知",
                                            "hint": "模型配置缺失或调用失败时发送插件通知",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "model_source",
                                            "label": "模型来源",
                                            "items": [
                                                {"title": "使用系统智能助手设置", "value": self.MODEL_SOURCE_SYSTEM},
                                                {"title": "使用 Agent Tokens 管理插件", "value": self.MODEL_SOURCE_AGENT_TOKENS},
                                            ],
                                            "hint": "Agent Tokens 模式会发出 Agent LLM 供应商链式事件，并读取插件返回的 API Base URL、API Key 与模型 ID。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "text": "选择 Agent Tokens 管理插件时，请先启用该插件，并至少配置一个已启用、未耗尽且填写了模型地址、API Key 和模型 ID 的供应商。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "识别缓存可避免相同标题重复调用 LLM API，点击按钮可清除已缓存的识别结果。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cache_count",
                                            "label": "当前缓存数量",
                                            "readonly": True,
                                            "hint": "点击右侧按钮清除缓存",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "warning",
                                            "block": True,
                                            "height": "56",
                                            "onClick": {
                                                "action": "fetch",
                                                "url": "/plugin/ChatGPT/clear_cache",
                                                "method": "GET",
                                                "then": {
                                                    "action": "refresh",
                                                },
                                            },
                                        },
                                        "text": "清除识别缓存",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "rows": 8,
                                            "auto-grow": True,
                                            "model": "customize_prompt",
                                            "label": "识别增强系统提示词",
                                            "hint": "用于约束模型只返回 MoviePilot 可消费的 JSON 识别结果",
                                            "clearable": True,
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "model_source": self.MODEL_SOURCE_SYSTEM,
            "notify": False,
            "customize_prompt": DEFAULT_RECOGNIZE_PROMPT,
            "cache_count": str(len(self._recognize_cache)),
        }

    def get_page(self) -> List[dict]:
        """
        当前插件不提供独立详情页。
        """
        pass

    def _resolve_system_model_config(self) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        直接从 MoviePilot 系统智能助手配置读取 LLM 运行参数。
        """
        config = {
            "provider": getattr(settings, "LLM_PROVIDER", None),
            "model": getattr(settings, "LLM_MODEL", None),
            "api_key": getattr(settings, "LLM_API_KEY", None),
            "base_url": getattr(settings, "LLM_BASE_URL", None),
            "base_url_preset": getattr(settings, "LLM_BASE_URL_PRESET", None),
            "user_agent": getattr(settings, "LLM_USER_AGENT", None),
            "use_proxy": getattr(settings, "LLM_USE_PROXY", True),
            "thinking_level": getattr(settings, "LLM_THINKING_LEVEL", None),
            "source": "system",
        }
        return self._normalize_model_config(config)

    def _resolve_agent_tokens_model_config(self) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        通过 Agent LLM 供应商链式事件从 Agent Tokens 管理插件读取 LLM 运行参数。
        """
        event_data = AgentLLMProviderEventData(
            provider=getattr(settings, "LLM_PROVIDER", None),
            model=getattr(settings, "LLM_MODEL", None),
            api_key=getattr(settings, "LLM_API_KEY", None),
            base_url=getattr(settings, "LLM_BASE_URL", None),
            base_url_preset=getattr(settings, "LLM_BASE_URL_PRESET", None),
            user_agent=getattr(settings, "LLM_USER_AGENT", None),
            use_proxy=getattr(settings, "LLM_USE_PROXY", True),
            thinking_level=None,
        )
        selected_event = eventmanager.send_event(ChainEventType.AgentLLMProvider, event_data)
        resolved_data = selected_event.event_data if selected_event else event_data
        if not self._clean_text(self._event_get(resolved_data, "selected_provider_id")):
            return None, "Agent Tokens 管理插件未返回可用供应商，请启用该插件并配置好模型地址、API Key 和模型 ID"

        config = {
            "provider": self._event_get(resolved_data, "provider"),
            "model": self._event_get(resolved_data, "model"),
            "api_key": self._event_get(resolved_data, "api_key"),
            "base_url": self._event_get(resolved_data, "base_url"),
            "base_url_preset": self._event_get(resolved_data, "base_url_preset"),
            "user_agent": self._event_get(resolved_data, "user_agent"),
            "use_proxy": self._event_get(resolved_data, "use_proxy"),
            "thinking_level": self._event_get(resolved_data, "thinking_level"),
            "selected_provider_id": self._event_get(resolved_data, "selected_provider_id"),
            "selected_provider_name": self._event_get(resolved_data, "selected_provider_name"),
            "source": self._event_get(resolved_data, "source") or "AgentTokens",
        }
        return self._normalize_model_config(config)

    def _normalize_model_config(self, config: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        标准化模型运行参数并校验必要字段。
        """
        normalized = {
            "provider": self._clean_text(config.get("provider")) or "openai",
            "model": self._clean_text(config.get("model")),
            "api_key": self._clean_text(config.get("api_key")),
            "base_url": self._clean_text(config.get("base_url")) or None,
            "base_url_preset": self._clean_text(config.get("base_url_preset")) or None,
            "user_agent": self._clean_text(config.get("user_agent")) or None,
            "use_proxy": bool(
                getattr(settings, "LLM_USE_PROXY", True)
                if config.get("use_proxy") is None
                else config.get("use_proxy")
            ),
            "thinking_level": self._clean_text(config.get("thinking_level")) or None,
            "selected_provider_id": self._clean_text(config.get("selected_provider_id")) or None,
            "selected_provider_name": self._clean_text(config.get("selected_provider_name")) or None,
            "source": self._clean_text(config.get("source")) or None,
        }
        if not normalized["api_key"]:
            return None, "未配置 LLM API Key"
        if not normalized["model"]:
            return None, "未配置 LLM 模型 ID"
        return normalized, ""

    def _resolve_model_config(self) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        根据配置的模型来源解析本次识别调用的 LLM 运行参数。
        """
        if self._model_source == self.MODEL_SOURCE_AGENT_TOKENS:
            return self._resolve_agent_tokens_model_config()
        return self._resolve_system_model_config()

    def init_openai(self, model_config: Dict[str, Any]) -> bool:
        """
        使用解析出的 LLM 运行参数初始化识别客户端。
        """
        if not model_config:
            self.openai = None
            return False

        self.openai = OpenAi(
            api_key=model_config.get("api_key"),
            api_url=model_config.get("base_url"),
            provider=model_config.get("provider"),
            model=model_config.get("model"),
            base_url_preset=model_config.get("base_url_preset"),
            user_agent=model_config.get("user_agent"),
            use_proxy=model_config.get("use_proxy"),
            thinking_level=model_config.get("thinking_level"),
            customize_prompt=self._customize_prompt,
        )
        logger.info(
            "ChatGPT 识别增强初始化 LLM 成功，来源：%s，Provider：%s，Model：%s，UseProxy：%s",
            self._model_source,
            model_config.get("provider"),
            model_config.get("model"),
            model_config.get("use_proxy"),
        )
        return True

    @staticmethod
    def is_api_error(response: Any) -> Tuple[bool, str]:
        """
        判断识别响应是否为模型调用错误。
        """
        if isinstance(response, dict) and response.get("errorMsg"):
            return True, str(response.get("errorMsg"))
        return False, ""

    def _notify_error(self, message: str) -> None:
        """
        按配置发送插件错误通知。
        """
        logger.warning(message)
        if self._notify:
            self.post_message(mtype=NotificationType.Plugin, title=self.plugin_name, text=message)

    def _record_agent_tokens_usage(
            self,
            model_config: Dict[str, Any],
            usage: Dict[str, int],
            success: bool,
            error: Optional[str] = None,
    ) -> None:
        """
        将 Agent Tokens 模式下的识别调用用量回写给配额管理插件。
        """
        if self._model_source != self.MODEL_SOURCE_AGENT_TOKENS:
            return
        if not model_config or not model_config.get("selected_provider_id"):
            return

        usage = usage or {}
        event_data = AgentTokensUsageEventData(
            session_id=f"chatgpt-recognize-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            selected_provider_id=model_config.get("selected_provider_id"),
            selected_provider_name=model_config.get("selected_provider_name"),
            provider=model_config.get("provider"),
            base_url=model_config.get("base_url"),
            model=model_config.get("model"),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            model_call_count=1,
            success=success,
            error=error,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            source=self.__class__.__name__,
        )
        eventmanager.send_event(EventType.AgentTokensUsage, event_data)

    def _write_recognition_result(self, event_data: Any, response: Dict[str, Any]) -> None:
        """
        将模型识别结果写回 MoviePilot 名称识别链式事件。
        """
        for key in ("name", "year", "season", "episode"):
            self._event_set(event_data, key, response.get(key))
        self._event_set(event_data, "source_plugin", self.__class__.__name__)

    @eventmanager.register(ChainEventType.NameRecognize)
    def recognize(self, event: Event):
        """
        监听名称识别链式事件，使用 LLM 进行辅助识别。
        """
        if not self._enabled or not event or not event.event_data:
            return
        if self._event_get(event.event_data, "source_plugin") or self._event_get(event.event_data, "name"):
            return

        title = self._clean_text(self._event_get(event.event_data, "title"))
        if not title:
            return

        # 检查内存缓存
        cached = self._get_cached_result(title)
        if cached:
            logger.info(f"ChatGPT 识别缓存命中：{title}")
            self._write_recognition_result(event.event_data, cached)
            return

        model_config, error = self._resolve_model_config()
        if error:
            self._notify_error(f"ChatGPT 识别增强不可用：{error}")
            return
        if not self.init_openai(model_config) or not self.openai:
            self._notify_error("ChatGPT 识别增强不可用：LLM 客户端初始化失败")
            return

        response = self.openai.get_media_name(filename=title)
        logger.info(f"ChatGPT 识别增强返回结果：{response}")
        is_error, error_msg = self.is_api_error(response)
        usage = self.openai.get_last_usage() if self.openai else {}
        self._record_agent_tokens_usage(model_config, usage, success=not is_error, error=error_msg)

        if is_error:
            self._notify_error(f"ChatGPT 识别增强调用失败：{error_msg}")
            return
        if not isinstance(response, dict) or not response.get("name"):
            self._notify_error(f"ChatGPT 识别增强未返回有效名称：{title}")
            return

        # 缓存识别结果到内存和数据库
        self._cache_result(title, response)

        self._write_recognition_result(event.event_data, response)

    def stop_service(self):
        """
        停止插件时禁用识别事件处理器。
        """
        try:
            eventmanager.disable_event_handler(self.recognize)
        except Exception as exc:
            logger.debug(f"禁用 ChatGPT 识别事件处理器失败: {exc}")
