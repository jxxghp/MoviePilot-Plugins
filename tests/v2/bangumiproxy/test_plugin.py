"""BangumiProxy 的 URL 代理与补丁恢复回归测试。"""

import asyncio

from app.plugins import bangumiproxy
from app.plugins.bangumiproxy import BangumiProxy


class FakeBangumiApi:
    """不发起网络请求的最小 BangumiApi 替身。"""

    _base_url = "https://api.bgm.tv/"
    clear_count = 0

    def calendar(self):
        return [
            {
                "images": {
                    "large": "https://lain.bgm.tv/pic/cover/l/a.jpg",
                    "official": "https://bgm.tv/pic/cover/l/b.jpg",
                    "external": "https://example.com/not-bangumi.jpg",
                },
                "url": "https://bgm.tv/subject/1",
            }
        ]

    async def async_calendar(self):
        return self.calendar()

    def clear_cache(self):
        type(self).clear_count += 1

    def close(self):
        pass


def _install_fake_api(monkeypatch):
    from app.modules.bangumi import bangumi as bangumi_module

    FakeBangumiApi._base_url = "https://api.bgm.tv/"
    FakeBangumiApi.clear_count = 0
    monkeypatch.setattr(bangumi_module, "BangumiApi", FakeBangumiApi)


def test_proxy_rewrites_images_and_restores_bangumi_api(monkeypatch):
    _install_fake_api(monkeypatch)
    original_calendar = FakeBangumiApi.calendar
    plugin = object.__new__(BangumiProxy)

    plugin.init_plugin(
        {
            "enabled": True,
            "data_base_url": "https://data-proxy.example///",
            "image_base_url": "https://image-proxy.example/",
        }
    )

    assert plugin.get_state()
    assert FakeBangumiApi._base_url == "https://data-proxy.example/"
    result = FakeBangumiApi().calendar()[0]
    assert result["images"]["large"] == (
        "https://image-proxy.example/https://lain.bgm.tv/pic/cover/l/a.jpg"
    )
    assert result["images"]["official"] == (
        "https://image-proxy.example/https://bgm.tv/pic/cover/l/b.jpg"
    )
    assert result["images"]["external"] == "https://example.com/not-bangumi.jpg"
    assert result["url"] == "https://bgm.tv/subject/1"

    plugin.stop_service()

    assert not plugin.get_state()
    assert FakeBangumiApi._base_url == "https://api.bgm.tv/"
    assert FakeBangumiApi.calendar is original_calendar
    assert FakeBangumiApi.clear_count == 2


def test_proxy_rewrites_async_bangumi_results(monkeypatch):
    _install_fake_api(monkeypatch)
    plugin = object.__new__(BangumiProxy)

    plugin.init_plugin(
        {
            "enabled": True,
            "image_base_url": "https://image-proxy.example",
        }
    )
    result = asyncio.run(FakeBangumiApi().async_calendar())

    assert result[0]["images"]["large"].startswith("https://image-proxy.example/")
    assert FakeBangumiApi._base_url == "https://api.bgm.tv/"

    plugin.stop_service()


def test_invalid_or_missing_proxy_urls_do_not_install_patch():
    plugin = object.__new__(BangumiProxy)

    plugin.init_plugin(
        {
            "enabled": True,
            "data_base_url": "ftp://proxy.example",
            "image_base_url": "https://image-proxy.example/?token=secret",
        }
    )

    assert not plugin.get_state()
    assert BangumiProxy._normalize_base_url("https://proxy.example/path/", True) == (
        "https://proxy.example/path/"
    )
    assert BangumiProxy._normalize_base_url("https://proxy.example/path/", False) == (
        "https://proxy.example/path"
    )
    assert bangumiproxy._active_owner() is None
