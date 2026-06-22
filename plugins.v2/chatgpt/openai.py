import asyncio
import inspect
import json
import re
import threading
from typing import Any, Dict, Optional

from app.agent.llm import LLMHelper
from langchain_core.messages import HumanMessage, SystemMessage


class OpenAi:
    """
    Lightweight LLM recognition client kept under the original module name for plugin compatibility.
    """

    _JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)

    def __init__(
            self,
            api_key: str = None,
            api_url: str = None,
            provider: str = None,
            model: str = None,
            base_url_preset: str = None,
            user_agent: str = None,
            use_proxy: bool = None,
            thinking_level: str = None,
            customize_prompt: str = None,
            **kwargs,
    ):
        """
        初始化用于媒体识别的 LLM 客户端运行参数。
        """
        self._api_key = api_key
        self._api_url = api_url
        self._provider = provider or "openai"
        self._model = model
        self._base_url_preset = base_url_preset
        self._user_agent = user_agent
        self._use_proxy = use_proxy
        self._thinking_level = thinking_level
        self._prompt = customize_prompt or ""
        self._last_usage: Dict[str, int] = {}

    def get_state(self) -> bool:
        """
        返回当前客户端是否具备发起识别调用的必要模型配置。
        """
        return bool(self._api_key and self._model)

    def get_last_usage(self) -> Dict[str, int]:
        """
        返回最近一次模型调用提取到的 token 用量。
        """
        return dict(self._last_usage or {})

    @staticmethod
    def _run_async_compatible(value: Any) -> Any:
        """
        在同步插件回调中兼容执行新版 MoviePilot 的异步 LLM 初始化。
        """
        if not inspect.isawaitable(value):
            return value
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)

        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}

        def _worker() -> None:
            """
            在独立线程中运行协程，避免嵌套事件循环。
            """
            try:
                result["value"] = asyncio.run(value)
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        if "exc" in error:
            raise error["exc"]
        return result.get("value")

    @staticmethod
    def _lookup_int(data: Any, key: str) -> Optional[int]:
        """
        从字典或对象字段中安全读取整数 token 统计。
        """
        if not data:
            return None
        value = data.get(key) if isinstance(data, dict) else getattr(data, key, None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_usage(cls, response: Any) -> Dict[str, int]:
        """
        从 LangChain AIMessage 中提取 token 用量。
        """
        usage_metadata = getattr(response, "usage_metadata", None)
        response_metadata = getattr(response, "response_metadata", None) or {}
        token_usage = (
                response_metadata.get("token_usage")
                or response_metadata.get("usage")
                or response_metadata.get("usage_metadata")
                or {}
        )

        input_tokens = (
                cls._lookup_int(usage_metadata, "input_tokens")
                or cls._lookup_int(token_usage, "input_tokens")
                or cls._lookup_int(token_usage, "prompt_tokens")
                or 0
        )
        output_tokens = (
                cls._lookup_int(usage_metadata, "output_tokens")
                or cls._lookup_int(token_usage, "output_tokens")
                or cls._lookup_int(token_usage, "completion_tokens")
                or 0
        )
        total_tokens = (
                cls._lookup_int(usage_metadata, "total_tokens")
                or cls._lookup_int(token_usage, "total_tokens")
                or input_tokens + output_tokens
        )
        return {
            "input_tokens": max(input_tokens, 0),
            "output_tokens": max(output_tokens, 0),
            "total_tokens": max(total_tokens, 0),
        }

    def _get_llm(self) -> Any:
        """
        按当前运行参数创建 MoviePilot LLM 实例。
        """
        llm = LLMHelper.get_llm(
            streaming=False,
            provider=self._provider,
            model=self._model,
            thinking_level=self._thinking_level,
            api_key=self._api_key,
            base_url=self._api_url,
            base_url_preset=self._base_url_preset,
            user_agent=self._user_agent,
            use_proxy=self._use_proxy,
        )
        return self._run_async_compatible(llm)

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """
        兼容 MoviePilot 不同版本的 LLMHelper 文本提取接口。
        """
        extractor = getattr(LLMHelper, "extract_text_content", None)
        if callable(extractor):
            return extractor(content)

        legacy_extractor = getattr(LLMHelper, "_extract_text_content", None)
        if callable(legacy_extractor):
            return legacy_extractor(content)

        # 极旧版本缺少统一提取方法时，只保留常见 LangChain 文本块，避免把推理内容写入 JSON 解析。
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                elif isinstance(block, dict):
                    block_type = block.get("type")
                    if block.get("thought") or block_type in {"thinking", "reasoning_content", "reasoning", "thought"}:
                        continue
                    if block_type == "text" or (not block_type and isinstance(block.get("text"), str)):
                        text_parts.append(block.get("text", ""))
            return "".join(text_parts)
        if isinstance(content, dict):
            block_type = content.get("type")
            if content.get("thought") or block_type in {"thinking", "reasoning_content", "reasoning", "thought"}:
                return ""
            if block_type == "text" or (not block_type and isinstance(content.get("text"), str)):
                return content.get("text", "")
        return ""

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        """
        从模型响应对象中提取文本内容。
        """
        content = getattr(response, "content", response)
        return OpenAi._extract_text_content(content).strip()

    @classmethod
    def _strip_json_fence(cls, text: str) -> str:
        """
        移除模型可能附加的 Markdown JSON 代码块包裹。
        """
        text = str(text or "").strip()
        match = cls._JSON_FENCE_PATTERN.match(text)
        return match.group(1).strip() if match else text

    @classmethod
    def _extract_json_text(cls, text: str) -> str:
        """
        从模型回复中提取第一个 JSON 对象文本。
        """
        text = cls._strip_json_fence(text)
        if text.startswith("{") and text.endswith("}"):
            return text

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return text

    def get_media_name(self, filename: str) -> Dict[str, Any]:
        """
        从媒体文件名中提取结构化识别信息。
        """
        self._last_usage = {}
        if not self.get_state():
            return {"errorMsg": "LLM API Key or model is not configured"}

        result = ""
        try:
            llm = self._get_llm()
            completion = llm.invoke(
                [
                    SystemMessage(content=self._prompt),
                    HumanMessage(content=str(filename or "")),
                ]
            )
            self._last_usage = self._extract_usage(completion)
            result = self._extract_response_text(completion)
            json_text = self._extract_json_text(result)
            data = json.loads(json_text)
            if not isinstance(data, dict):
                raise ValueError("LLM response is not a JSON object")
            return data
        except Exception as exc:
            return {
                "content": result,
                "errorMsg": str(exc),
            }
