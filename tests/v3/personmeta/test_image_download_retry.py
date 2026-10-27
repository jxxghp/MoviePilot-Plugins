"""PersonMeta 图片下载重试（issue：读超时被就地吞掉，@retry 成为死代码导致海报静默丢失）的合同测试。"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from requests import ReadTimeout, RequestException

TMDB_IMAGE_URL = "https://tmdb.example/t/p/original/a.jpg"


def _load_plugin():
    return importlib.import_module("app.plugins.personmeta")


def _no_sleep(monkeypatch) -> None:
    """
    取消重试装饰器的退避等待，避免用例被真实 sleep 拖慢。

    ``app.runtime.execution.retry`` 在自身模块命名空间调用 ``time.sleep``，
    因此只需要替换该模块的 ``time``。
    """
    execution = importlib.import_module("app.runtime.execution")
    monkeypatch.setattr(execution.time, "sleep", lambda _seconds: None)


def _plugin_with_client(monkeypatch, responses):
    """
    构造插件实例，并让图片下载使用按 ``responses`` 逐个表现的可控客户端。

    :param monkeypatch: pytest monkeypatch
    :param responses: 依次执行的响应工厂，返回响应桩或抛出异常
    :return: (插件实例, 客户端替身)
    """
    module = _load_plugin()
    monkeypatch.setattr(module, "settings", SimpleNamespace(
        USER_AGENT="TestUA", PROXY=None, TMDB_IMAGE_DOMAIN="tmdb.example"))
    plugin = object.__new__(module.PersonMeta)

    class _Client:
        """
        记录请求次数并按脚本返回结果或抛出异常的 RequestUtils 替身。
        """

        def __init__(self, **_kwargs):
            self.requests = 0

        def get_res(self, url, **_kwargs):
            script = responses[min(self.requests, len(responses) - 1)]
            self.requests += 1
            return script(url)

        def close(self):
            pass

    monkeypatch.setattr(module, "RequestUtils", _Client)
    service = SimpleNamespace(instance=SimpleNamespace(
        post_data=lambda **kwargs: SimpleNamespace(status_code=200)
    ))
    monkeypatch.setattr(plugin, "service_infos", lambda _server_type: {"Emby": service})
    _no_sleep(monkeypatch)
    return plugin, lambda: plugin._image_clients["other"][1]


def _ok(_url):
    """
    生成一次成功下载。
    """
    return SimpleNamespace(content=b"jpeg-bytes")


def _timeout(_url):
    """
    生成一次跨境链路读超时。
    """
    raise ReadTimeout("HTTPSConnectionPool: Read timed out. (read timeout=20)")


def test_transient_download_failure_is_retried_and_image_uploaded(monkeypatch) -> None:
    """
    连续两次读超时后第三次成功时，图片必须仍然上传成功。

    修复前 ``__download_image`` 用 ``except Exception`` 吞掉 RequestException，
    外层 ``@retry(RequestException)`` 永远收不到异常，一次抖动就把海报永久丢掉。
    """
    plugin, client = _plugin_with_client(monkeypatch, [_timeout, _timeout, _ok])

    assert plugin.set_item_image(
        server="Emby", server_type="emby", itemid="1", imageurl=TMDB_IMAGE_URL
    ) is True
    assert client().requests == 3

    plugin.stop_service()


def test_download_gives_up_after_the_retry_budget(monkeypatch) -> None:
    """
    持续失败时按 ``@retry`` 的 3 次预算收敛，并把最后一次异常交给调用方。

    重试必须有界：链路整体不可用时不能把整轮刮削拖成无限等待。
    """
    plugin, client = _plugin_with_client(monkeypatch, [_timeout])

    with pytest.raises(RequestException):
        plugin.set_item_image(
            server="Emby", server_type="emby", itemid="1", imageurl=TMDB_IMAGE_URL
        )
    assert client().requests == 3

    plugin.stop_service()


def test_non_network_download_error_is_not_retried(monkeypatch) -> None:
    """
    非网络异常沿用修复前行为：记录错误、放弃这张图片、不进入重试。

    编码或类型错误重试再多次也不会变好，重试只服务于会自愈的网络抖动。
    """
    def _broken(_url):
        """
        生成一次与网络无关的实现缺陷。
        """
        raise TypeError("not an image payload")

    plugin, client = _plugin_with_client(monkeypatch, [_broken])

    assert plugin.set_item_image(
        server="Emby", server_type="emby", itemid="1", imageurl=TMDB_IMAGE_URL
    ) is None
    assert client().requests == 1

    plugin.stop_service()


def test_exhausted_download_retry_does_not_skip_name_and_overview_update(monkeypatch) -> None:
    """
    重试耗尽后只丢弃图片，同一人物的中文名与简介更新不能跟着被跳过。

    ``set_item_image`` 的异常会冒泡到按人物包裹的 ``try``，若不在此兜住，
    该人物的名称/简介锁定与写回都会被一起跳过。
    """
    module = _load_plugin()
    monkeypatch.setattr(module, "settings", SimpleNamespace(
        USER_AGENT="TestUA", PROXY=None, TMDB_IMAGE_DOMAIN="tmdb.example"))
    plugin = object.__new__(module.PersonMeta)
    plugin._person_detail_cache = {}
    plugin._processed_person_images = set()
    plugin._processed_person_infos = set()

    def _raise(**_kwargs):
        """
        模拟重试耗尽后仍然失败的图片下载。
        """
        raise ReadTimeout("HTTPSConnectionPool: Read timed out. (read timeout=20)")

    monkeypatch.setattr(plugin, "set_item_image", _raise)

    detail = SimpleNamespace(
        profile_path="/a.jpg",
        biography=None,
        also_known_as=["汤姆·克鲁斯"],
    )
    class _Chain:
        """
        TMDB 人物详情链替身，只返回带中文别名与图片的人物。
        """

        def person_detail(self, _person_id):
            return detail

    monkeypatch.setattr(module, "TmdbChain", lambda: _Chain())
    updated = []
    monkeypatch.setattr(plugin, "get_iteminfo", lambda **_kwargs: {
        "Name": "Tom Cruise",
        "ProviderIds": {"Tmdb": "819"},
    })
    monkeypatch.setattr(plugin, "set_iteminfo", lambda **kwargs: updated.append(kwargs) or True)

    ret = plugin._PersonMeta__update_people(
        server="Emby", server_type="emby",
        people={"Name": "Tom Cruise", "Id": "1"},
    )

    assert ret is not None
    assert ret["Name"] == "汤姆·克鲁斯"
    assert len(updated) == 1
