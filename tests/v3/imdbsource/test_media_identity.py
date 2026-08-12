from unittest.mock import AsyncMock, Mock

import pytest
from app.schemas.types import MediaSource
from imdbsource import ImdbSource


def _build_plugin() -> ImdbSource:
    """构造不触发插件初始化和外部请求的 IMDbSource 测试实例。"""
    plugin = object.__new__(ImdbSource)
    plugin._enabled = True
    plugin._imdb_helper = Mock()
    plugin._imdb_helper.get_info_by_imdbid.return_value = None
    plugin._imdb_helper.async_get_info_by_imdbid = AsyncMock(return_value=None)
    return plugin


def test_recognize_media_normalizes_explicit_imdb_identity() -> None:
    """同步通用识别入口只把规范化后的 IMDb 身份传给单源 helper。"""
    plugin = _build_plugin()

    assert plugin.recognize_media(media_source="imdb", media_id=" tt0111161 ") is None

    plugin._imdb_helper.get_info_by_imdbid.assert_called_once_with("tt0111161")


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
    plugin = _build_plugin()

    assert plugin.recognize_media(media_source=media_source, media_id=media_id) is None

    plugin._imdb_helper.get_info_by_imdbid.assert_not_called()


@pytest.mark.asyncio
async def test_async_recognize_media_normalizes_explicit_imdb_identity() -> None:
    """异步通用识别入口与同步入口采用相同的统一身份归一化规则。"""
    plugin = _build_plugin()

    assert await plugin.async_recognize_media(
        media_source=MediaSource.IMDb,
        media_id=" tt0111161 ",
    ) is None

    plugin._imdb_helper.async_get_info_by_imdbid.assert_awaited_once_with("tt0111161")


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
    plugin = _build_plugin()

    assert await plugin.async_recognize_media(
        media_source=media_source,
        media_id=media_id,
    ) is None

    plugin._imdb_helper.async_get_info_by_imdbid.assert_not_awaited()
