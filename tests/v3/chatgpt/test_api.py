"""ChatGPT 详情页 API 回归：HTTP 响应、统计数据、清理副作用与 OpenAPI 合同。"""

from copy import deepcopy
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.plugins.chatgpt import ChatGPT
from app.schemas import Response


USAGE_STATS = {
    "input_tokens": 120,
    "output_tokens": 30,
    "total_tokens": 150,
    "model_call_count": 3,
    "success_count": 2,
    "failed_count": 1,
    "last_used_at": "2026-10-30 10:00:00",
}
EMPTY_USAGE_STATS = {key: "" if key == "last_used_at" else 0 for key in USAGE_STATS}


@pytest.fixture
def plugin_api():
    """挂载插件实际声明的 FastAPI 路由，以内存存储隔离数据库与识别服务。"""
    plugin = object.__new__(ChatGPT)
    cache = {"video": {"name": "星际穿越"}, "music": {"name": "晴天"}}
    storage = {
        plugin._CACHE_DATA_KEY: deepcopy(cache),
        plugin._USAGE_STATS_KEY: dict(USAGE_STATS),
    }
    plugin._recognize_cache = deepcopy(cache)
    plugin._usage_stats = dict(EMPTY_USAGE_STATS)

    def save_data(key, value):
        """模拟持久化快照，避免内存引用变化掩盖遗漏的写入。"""
        storage[key] = deepcopy(value)

    app = FastAPI()
    for declaration in plugin.get_api():
        route = dict(declaration)
        assert route.pop("auth") == "bear"
        app.add_api_route(**route)
    with patch.object(plugin, "get_data", side_effect=storage.get), \
            patch.object(plugin, "save_data", side_effect=save_data), TestClient(app) as client:
        yield plugin, storage, client


@pytest.mark.parametrize("path,message,data", [
    ("/cache_stats", "", {"count": 2}),
    ("/usage_stats", "", USAGE_STATS),
    ("/clear_cache", "识别缓存已清除", {"count": 0}),
    ("/clear_usage_stats", "Token 用量统计已清除", EMPTY_USAGE_STATS),
])
def test_api_returns_standard_envelope(plugin_api, path, message, data):
    """详情页调用获得严格三字段响应，业务字段完整保留在 data 内。"""
    _, _, client = plugin_api

    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": message, "data": data}


def test_clear_cache_persists_without_clearing_usage(plugin_api):
    """缓存清理同时更新内存和持久化数据，保留 Token 用量统计。"""
    plugin, storage, client = plugin_api

    assert client.get("/clear_cache").status_code == 200

    assert plugin._recognize_cache == {}
    assert storage[plugin._CACHE_DATA_KEY] == {}
    assert storage[plugin._USAGE_STATS_KEY] == USAGE_STATS


def test_clear_usage_persists_without_clearing_cache(plugin_api):
    """用量清理保存全零统计，保留影视与音乐识别缓存。"""
    plugin, storage, client = plugin_api
    original_cache = deepcopy(storage[plugin._CACHE_DATA_KEY])

    assert client.get("/clear_usage_stats").status_code == 200

    assert plugin._usage_stats == EMPTY_USAGE_STATS
    assert storage[plugin._USAGE_STATS_KEY] == EMPTY_USAGE_STATS
    assert plugin._recognize_cache == original_cache
    assert storage[plugin._CACHE_DATA_KEY] == original_cache


def test_routes_publish_typed_envelope_schemas(plugin_api):
    """每个接口声明真实响应模型，OpenAPI 同时暴露信封和完整统计字段。"""
    plugin, _, client = plugin_api
    schema = client.get("/openapi.json").json()
    components = schema["components"]["schemas"]
    for route in plugin.get_api():
        assert issubclass(route["response_model"], Response)
        response_schema = (
            schema["paths"][route["path"]]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        )
        envelope = components[response_schema["$ref"].rsplit("/", 1)[1]]
        assert set(envelope["properties"]) == {"success", "message", "data"}
        assert set(envelope["required"]) == {"success", "message", "data"}
        data_ref = next(
            item["$ref"] for item in envelope["properties"]["data"]["anyOf"] if "$ref" in item
        )
        data_schema = components[data_ref.rsplit("/", 1)[1]]
        expected_fields = {"count"} if "cache" in route["path"] else set(USAGE_STATS)
        assert set(data_schema["properties"]) == expected_fields
