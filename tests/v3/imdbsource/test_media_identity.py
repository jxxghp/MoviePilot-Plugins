from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from app.schemas.types import MediaSource
from app.plugins.imdbsource import ImdbSource
from app.plugins.imdbsource import imdbhelper
from app.plugins.imdbsource.imdbhelper import ImdbHelper
from app.sdk.utilities import convert


def _build_plugin() -> ImdbSource:
    """构造只验证入口委托、不触发插件初始化的 IMDbSource 实例。"""
    plugin = object.__new__(ImdbSource)
    plugin._enabled = True
    plugin._imdb_helper = Mock()
    plugin._imdb_helper.recognize_media = Mock(return_value=None)
    plugin._imdb_helper.async_recognize_media = AsyncMock(return_value=None)
    return plugin


def _build_helper() -> ImdbHelper:
    """构造不触发网络请求的 ImdbHelper 实例。"""
    helper = object.__new__(ImdbHelper)
    helper.get_info_by_imdbid = Mock(return_value=None)
    helper.async_get_info_by_imdbid = AsyncMock(return_value=None)
    return helper


def test_text_conversion_uses_host_sdk() -> None:
    """IMDb 中文转换应由宿主 SDK 选择兼容当前解释器的实现。"""
    assert imdbhelper.convert is convert


@pytest.mark.asyncio
async def test_helper_uses_httpx2_client_for_host_request_adapter() -> None:
    """IMDb 两条异步 API 复用同一个 HTTPX2 client。"""
    helper = ImdbHelper()
    try:
        assert isinstance(helper._async_client, httpx2.AsyncClient)
        assert helper.imdbapi_client._async_req._client is helper._async_client
        assert helper.official_api_client._async_req._client is helper._async_client
    finally:
        helper._session.close()
        await helper._async_client.aclose()


def test_plugin_recognize_media_delegates_explicit_identity() -> None:
    """插件入口只负责把统一识别参数委托给 IMDb helper。"""
    plugin = _build_plugin()

    assert plugin.recognize_media(media_source="imdb", media_id=" tt0111161 ") is None

    plugin._imdb_helper.recognize_media.assert_called_once_with(
        meta=None,
        mtype=None,
        media_source="imdb",
        media_id=" tt0111161 ",
        add_tmdb_id=False,
    )


@pytest.mark.parametrize(
    ("media_source", "media_id"),
    (
        (MediaSource.IMDb, "0"),
        (MediaSource.IMDb, "   "),
        (MediaSource.IMDb, None),
        (None, "tt0111161"),
        (MediaSource.TMDB, "tt0111161"),
    ),
)
def test_recognize_media_rejects_invalid_explicit_identity(
    media_source,
    media_id,
) -> None:
    """同步入口不得把零值、空白、半对或非 IMDb 身份发送到 IMDb。"""
    helper = _build_helper()

    assert helper.recognize_media(media_source=media_source, media_id=media_id) is None

    helper.get_info_by_imdbid.assert_not_called()


@pytest.mark.asyncio
async def test_plugin_async_recognize_media_delegates_explicit_identity() -> None:
    """插件异步入口只负责把统一识别参数委托给 IMDb helper。"""
    plugin = _build_plugin()

    assert await plugin.async_recognize_media(
        media_source=MediaSource.IMDb,
        media_id=" tt0111161 ",
    ) is None

    plugin._imdb_helper.async_recognize_media.assert_awaited_once_with(
        meta=None,
        mtype=None,
        media_source=MediaSource.IMDb,
        media_id=" tt0111161 ",
        add_tmdb_id=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_source", "media_id"),
    (
        (MediaSource.IMDb, "0"),
        (MediaSource.IMDb, "   "),
        (MediaSource.IMDb, None),
        (None, "tt0111161"),
        (MediaSource.TMDB, "tt0111161"),
    ),
)
async def test_async_recognize_media_rejects_invalid_explicit_identity(
    media_source,
    media_id,
) -> None:
    """异步入口不得把无效统一身份发送到 IMDb。"""
    helper = _build_helper()

    assert await helper.async_recognize_media(
        media_source=media_source,
        media_id=media_id,
    ) is None

    helper.async_get_info_by_imdbid.assert_not_awaited()
