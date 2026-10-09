"""MoviePilot system-assistant title normalization.

The plugin never stores an API key.  It reads the host's
``LLM_*`` settings (DeepSeek and other OpenAI-compatible providers are
supported by MoviePilot) and asks for a short search title.  Any host or model
failure falls back to the original title, so search/subscription refresh keeps
working without AI.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
from typing import Any, Dict, Optional, Tuple

from .naming import normalize_search_title


class AiTitleNormalizer:
    _fence = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)

    def __init__(self, enabled: bool = True, logger: Any = None) -> None:
        self.enabled = bool(enabled)
        self.logger = logger

    @staticmethod
    def _run_async(value: Any) -> Any:
        if not inspect.isawaitable(value):
            return value
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)
        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}

        def worker() -> None:
            try:
                result["value"] = asyncio.run(value)
            except BaseException as exc:  # noqa: BLE001
                error["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join()
        if "error" in error:
            raise error["error"]
        return result.get("value")

    @staticmethod
    def _text(content: Any) -> str:
        try:
            from app.agent.llm import LLMHelper

            extractor = getattr(LLMHelper, "extract_text_content", None)
            if callable(extractor):
                return str(extractor(content) or "").strip()
        except Exception:
            pass
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content).strip()
        if isinstance(content, dict):
            return str(content.get("text") or content.get("content") or "").strip()
        return str(content or "").strip()

    @classmethod
    def _json(cls, text: str) -> Dict[str, Any]:
        text = str(text or "").strip()
        match = cls._fence.match(text)
        if match:
            text = match.group(1).strip()
        if not text.startswith("{"):
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        value = json.loads(text)
        return value if isinstance(value, dict) else {}

    def _config(self) -> Tuple[Optional[Dict[str, Any]], str]:
        try:
            from app.sdk.config import settings
            config = {
                "provider": getattr(settings, "LLM_PROVIDER", None) or "openai",
                "model": getattr(settings, "LLM_MODEL", None),
                "api_key": getattr(settings, "LLM_API_KEY", None),
                "base_url": getattr(settings, "LLM_BASE_URL", None),
                "base_url_preset": getattr(settings, "LLM_BASE_URL_PRESET", None),
                "user_agent": getattr(settings, "LLM_USER_AGENT", None),
                "use_proxy": getattr(settings, "LLM_USE_PROXY", True),
                "thinking_level": getattr(settings, "LLM_THINKING_LEVEL", None),
            }
        except Exception as exc:
            return None, f"MoviePilot 智能助手不可用：{exc}"
        if not str(config.get("api_key") or "").strip():
            return None, "未配置 MoviePilot 智能助手 API Key"
        if not str(config.get("model") or "").strip():
            return None, "未配置 MoviePilot 智能助手模型"
        return config, ""

    def status(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "available": False, "message": "未启用系统智能助手识别"}
        config, message = self._config()
        return {
            "enabled": True,
            "available": bool(config),
            "provider": (config or {}).get("provider"),
            "model": (config or {}).get("model"),
            "message": message or "已读取 MoviePilot 智能助手配置",
        }

    def normalize(self, title: str, year: str = "", media_type: str = "") -> Tuple[str, str]:
        original = str(title or "").strip()
        if not self.enabled or not original:
            return normalize_search_title(original), "disabled"
        config, message = self._config()
        if not config:
            return normalize_search_title(original), message
        try:
            from app.agent.llm import LLMHelper
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = LLMHelper.get_llm(
                streaming=False,
                provider=config["provider"],
                model=config["model"],
                thinking_level=config.get("thinking_level"),
                api_key=config["api_key"],
                base_url=config.get("base_url"),
                base_url_preset=config.get("base_url_preset"),
                user_agent=config.get("user_agent"),
                use_proxy=config.get("use_proxy"),
            )
            llm = self._run_async(llm)
            prompt = (
                "你是影视资源搜索助手。只输出 JSON，不要解释。"
                "从原始名称中去掉分辨率、语言、合集范围、视频标记和发布组信息，"
                "保留用于 TMDB/苹果 CMS 搜索的正式片名；如果有明确年份保留 year。"
                '格式：{"query":"正式片名","year":"年份或空字符串"}'
            )
            response = llm.invoke([
                SystemMessage(content=prompt),
                HumanMessage(content=json.dumps({"title": original, "year": year, "type": media_type}, ensure_ascii=False)),
            ])
            data = self._json(self._text(getattr(response, "content", response)))
            query = str(data.get("query") or "").strip()
            if query:
                return query, "ai"
        except Exception as exc:  # AI is an enhancement, never a hard dependency.
            if self.logger:
                self.logger.warning("LunaTV AI 标题识别失败：%s", exc)
            return normalize_search_title(original), str(exc)
        return normalize_search_title(original), "ai_empty"
