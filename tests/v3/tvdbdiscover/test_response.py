from typing import List

from app import schemas
from app.runtime.config import settings
from app.plugins.tvdbdiscover import TvdbDiscover


def test_discover_route_declares_explicit_response_envelope() -> None:
    """探索公共组件要求显式 envelope，路由模型必须与端点返回值一致。"""
    plugin = object.__new__(TvdbDiscover)

    route = plugin.get_api()[0]

    assert route["response_model"] == schemas.Response[List[schemas.MediaInfo]]


def test_discover_rejects_invalid_token_with_empty_response() -> None:
    """无效令牌不访问 TVDB，并按探索组件合同返回空的统一响应。"""
    plugin = object.__new__(TvdbDiscover)

    endpoint = plugin.get_api()[0]["endpoint"]
    response = endpoint(apikey=f"{settings.API_TOKEN}-invalid")

    assert response.success is True
    assert response.data == []
