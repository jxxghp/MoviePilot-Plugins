"""
验证识别总预算、取消收尾与真实 SDK 无响应、慢响应及重试的退出行为。
"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI

from app.agent.llm import LLMHelper
from app.plugins.chatgpt.openai import OpenAi
from app.scheduler import bridge as scheduler_bridge
from app.scheduler import execution as scheduler_execution
from app.scheduler import progress as scheduler_progress
from app.scheduler.facade import Scheduler
from app.scheduler.registry import ExecutionRegistry


@pytest.fixture
def anyio_backend():
    """
    本地服务与 SDK 仅使用 asyncio 后端。
    """
    return "asyncio"


@pytest.mark.parametrize("running_loop", [False, True])
def test_total_budget_cancels_generation_and_allows_next_title(monkeypatch, running_loop):
    """
    普通同步回调和已有事件循环的回调都等待取消、关闭后返回，下一条仍能识别。
    """
    monkeypatch.setattr(OpenAi, "_REQUEST_TIMEOUT_SECONDS", 0.02)
    client = OpenAi(api_key="key", model="model")
    events = []

    async def generate(_messages):
        """
        首次模拟永久等待，第二次返回有效候选。
        """
        if not events:
            try:
                await asyncio.Event().wait()
            finally:
                events.append("cancelled")
        events.append("generated")
        return LLMResult(generations=[[
            ChatGeneration(message=AIMessage(content='{"name":"Title"}')),
        ]])

    async def close(_model):
        """
        记录模型收尾顺序，确保同步入口不提前返回。
        """
        events.append("closed")
        return True

    async def invoke_in_loop():
        """
        模拟在已有事件循环的同步插件事件处理器内调用识别。
        """
        return client.get_media_name("title")

    monkeypatch.setattr(client, "_get_llm", lambda: SimpleNamespace(agenerate=generate))
    monkeypatch.setattr(LLMHelper, "close_llm", close)
    invoke = lambda: asyncio.run(invoke_in_loop()) if running_loop else client.get_media_name("title")
    result = invoke()
    assert result["errorCode"] == "timeout"
    assert "包含重试" in result["errorMsg"]
    assert events == ["cancelled", "closed"]
    assert invoke() == {"name": "Title"}
    assert events == ["cancelled", "closed", "generated", "closed"]


def test_initialization_is_included_in_total_budget(monkeypatch):
    """
    供应商初始化也占用同一预算，未创建完成的模型不误走关闭入口。
    """
    monkeypatch.setattr(OpenAi, "_REQUEST_TIMEOUT_SECONDS", 0.02)
    cancelled = []

    async def initialize():
        """
        模拟尚未返回模型的异步初始化。
        """
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    client = OpenAi(api_key="key", model="model")
    monkeypatch.setattr(client, "_get_llm", initialize)
    with patch.object(LLMHelper, "close_llm", new_callable=AsyncMock) as close:
        assert client.get_media_name("title")["errorCode"] == "timeout"
    assert cancelled == [True]
    close.assert_not_called()


@pytest.mark.parametrize("has_cleanup", [True, False])
def test_async_initialization_and_cleanup_share_the_generation_loop(monkeypatch, has_cleanup):
    """
    宿主初始化协程在生成所属循环内等待，兼容没有统一回收入口的旧版宿主。
    """
    loops = []

    async def generate(_messages):
        """
        保存生成使用的循环并返回有效候选。
        """
        loops.append(asyncio.get_running_loop())
        return LLMResult(generations=[[
            ChatGeneration(message=AIMessage(content='{"name":"Title"}')),
        ]])

    async def initialize(**_kwargs):
        """
        模拟新版异步宿主工厂，并记录客户端创建循环。
        """
        loops.append(asyncio.get_running_loop())
        return SimpleNamespace(agenerate=generate)

    async def close(_model):
        """
        记录支持统一回收的宿主关闭模型时使用的循环。
        """
        loops.append(asyncio.get_running_loop())
        return True

    monkeypatch.setattr(LLMHelper, "get_llm", initialize)
    if has_cleanup:
        monkeypatch.setattr(LLMHelper, "close_llm", close)
    else:
        monkeypatch.delattr(LLMHelper, "close_llm")
    assert OpenAi(api_key="key", model="model").get_media_name("title") == {"name": "Title"}
    assert len(loops) == (3 if has_cleanup else 2)
    assert all(loop is loops[0] for loop in loops)


def test_timeout_allows_remaining_titles_and_next_scheduler_run(monkeypatch):
    """
    同步调度链中首条超时后继续识别，真实收尾释放 generation，下一轮仍能准入。
    """
    monkeypatch.setattr(OpenAi, "_REQUEST_TIMEOUT_SECONDS", 0.02)
    client = OpenAi(api_key="key", model="model")
    results = []
    calls = []

    async def generate(_messages):
        """
        第一条等待取消，后续标题正常返回。
        """
        calls.append(True)
        if len(calls) == 1:
            await asyncio.Event().wait()
        return LLMResult(generations=[[
            ChatGeneration(message=AIMessage(content='{"name":"Title"}')),
        ]])

    def refresh():
        """
        模拟一轮同步订阅刷新连续识别两条资源。
        """
        results.extend(client.get_media_name(title) for title in ("first", "second"))

    scheduler = object.__new__(Scheduler)
    scheduler._scheduler = None
    scheduler._event = threading.Event()
    scheduler._lock = threading.RLock()
    scheduler._jobs = {"subscribe_refresh": {
        "name": "订阅刷新", "func": refresh, "running": False,
    }}
    scheduler._lifecycle_state = "running"
    scheduler._registry = ExecutionRegistry(scheduler._lock)
    scheduler._registry.assign_generation("subscribe_refresh", scheduler._jobs["subscribe_refresh"])

    async def close(_model):
        """
        请求取消和回收期间仍由本轮持有 generation。
        """
        assert scheduler._is_job_active("subscribe_refresh")
        return True

    monkeypatch.setattr(client, "_get_llm", lambda: SimpleNamespace(agenerate=generate))
    monkeypatch.setattr(LLMHelper, "close_llm", close)
    for owner in (scheduler_execution, scheduler_bridge):
        monkeypatch.setattr(owner, "main_loop_registry", SimpleNamespace(current=None))
    monkeypatch.setattr(scheduler_execution, "ProgressHelper", MagicMock())
    monkeypatch.setattr(scheduler_progress, "AsyncProgressHelper", lambda _key: SimpleNamespace(
        get=AsyncMock(return_value=None), end=AsyncMock(),
    ))
    for _ in range(2):
        assert scheduler.start("subscribe_refresh") is True
        assert not scheduler._is_job_active("subscribe_refresh")
        assert not scheduler._jobs["subscribe_refresh"]["running"]
    assert results[0]["errorCode"] == "timeout"
    assert results[1:] == [{"name": "Title"}] * 3


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["silent", "trickle", "retry"])
async def test_real_sdk_total_budget_closes_sockets(monkeypatch, mode):
    """
    即使 SDK 没有读超时、持续收到零星字节或正在退避重试，识别仍按总预算取消并关闭连接。
    """
    monkeypatch.setattr(OpenAi, "_REQUEST_TIMEOUT_SECONDS", 1.0)
    writers = set()
    finished = asyncio.Queue()
    requests = []

    async def respond(reader, writer):
        """
        只接收本地测试请求，分别模拟静默、持续慢回包和可重试错误。
        """
        writers.add(writer)
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1]) for line in header.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            await reader.readexactly(length)
            requests.append(True)
            if mode == "retry":
                writer.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
            elif mode == "trickle":
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
                while not reader.at_eof():
                    writer.write(b" ")
                    await writer.drain()
                    await asyncio.sleep(0.01)
            else:
                await reader.read()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            finished.put_nowait(True)

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    base_url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
    models = []

    def create_model():
        """
        在识别所属循环中创建真实 SDK，并故意关闭请求超时以验证外层预算。
        """
        model = ChatOpenAI(
            api_key="offline-key", model="test-model", base_url=base_url,
            request_timeout=None, max_retries=3,
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
        )
        models.append(model)
        return model

    client = OpenAi(api_key="key", model="model")
    monkeypatch.setattr(client, "_get_llm", create_model)
    try:
        result = await asyncio.wait_for(asyncio.to_thread(client.get_media_name, "title"), timeout=5)
        assert result["errorCode"] == "timeout"
        assert requests
        assert models[0].http_client.is_closed
        assert models[0].http_async_client.is_closed
        assert await asyncio.wait_for(finished.get(), timeout=2)
    finally:
        for writer in tuple(writers):
            writer.close()
        server.close()
        await server.wait_closed()
