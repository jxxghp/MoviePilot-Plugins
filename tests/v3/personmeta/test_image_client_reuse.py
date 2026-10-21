"""PersonMeta 图片下载连接复用（issue：跨境图片链路握手放大刮削超时）的合同测试。"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

TMDB_IMAGE_URL = "https://tmdb.example/t/p/original/a.jpg"
DOUBAN_IMAGE_URL = "https://img1.doubanio.com/view/nm/large.jpg"


def _load_plugin():
    return importlib.import_module("app.plugins.personmeta")


def _spy_clients(monkeypatch, module, **config):
    """
    替换 settings 与 RequestUtils 构造入口，记录每次真实建连参数。

    :param monkeypatch: pytest monkeypatch
    :param module: personmeta 插件模块
    :param config: 期望的图片下载依赖的运行时配置
    :return: (插件实例, 构造记录列表)
    """
    monkeypatch.setattr(module, "settings", SimpleNamespace(**config))
    plugin = object.__new__(module.PersonMeta)
    builds = []
    real = module.RequestUtils

    def _spy(**kwargs):
        builds.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(module, "RequestUtils", _spy)
    return plugin, builds


def _image_client(plugin, is_douban: bool):
    """
    调用插件的图片复用会话入口。

    :param plugin: 插件实例
    :param is_douban: 是否按图片来源取得豆瓣客户端
    :return: RequestUtils 实例
    """
    return plugin._PersonMeta__image_client(is_douban)


def test_images_from_the_same_source_share_one_pooled_client(monkeypatch) -> None:
    """
    同一来源的多张图片必须复用同一个客户端并开启持久会话。

    修复前每张图片都会新建不带会话的 RequestUtils，同步请求落到无连接池的
    ``requests.request``，跨境链路的 TLS 握手成本按图片数量线性叠加。
    """
    plugin, builds = _spy_clients(monkeypatch, _load_plugin(), USER_AGENT="TestUA", PROXY=None)

    first = _image_client(plugin, False)
    second = _image_client(plugin, False)

    assert first is second
    assert len(builds) == 1
    assert builds[0]["use_session"] is True

    plugin.stop_service()


def test_douban_and_other_sources_keep_distinct_headers_and_proxies(monkeypatch) -> None:
    """
    豆瓣客户端保留 Referer 且不套用 TMDB 代理，其他来源沿用配置的代理。

    这是修复前两个分支的既有差异，复用会话后不得改变。
    """
    proxy = {"https": "http://127.0.0.1:8888"}
    plugin, builds = _spy_clients(monkeypatch, _load_plugin(), USER_AGENT="TestUA", PROXY=proxy)

    other = _image_client(plugin, False)
    douban = _image_client(plugin, True)

    assert other is not douban
    assert builds[0]["proxies"] == proxy
    assert builds[0]["headers"] is None
    assert builds[1]["proxies"] is None
    assert builds[1]["headers"] == {"Referer": "https://movie.douban.com/"}

    plugin.stop_service()


def test_client_is_rebuilt_and_old_session_closed_when_config_changes(monkeypatch) -> None:
    """
    代理或 UA 运行时变更后必须重建客户端，并关闭旧会话。

    插件在配置重载时会调用 stop_service，这里校验未调用 stop_service 的路径也不会
    继续携带过期代理。
    """
    module = _load_plugin()
    monkeypatch.setattr(module, "settings", SimpleNamespace(USER_AGENT="TestUA", PROXY=None))
    plugin = object.__new__(module.PersonMeta)
    original = _image_client(plugin, False)

    module.settings.PROXY = {"https": "http://127.0.0.1:9999"}
    rebuilt = _image_client(plugin, False)

    assert rebuilt is not original
    assert original._session is None
    assert rebuilt._session is not None

    plugin.stop_service()


def test_stop_service_releases_every_pooled_session(monkeypatch) -> None:
    """
    停止服务后所有来源的复用会话都必须释放，避免插件卸载残留连接。
    """
    plugin, _ = _spy_clients(monkeypatch, _load_plugin(), USER_AGENT="TestUA", PROXY=None)
    other = _image_client(plugin, False)
    douban = _image_client(plugin, True)

    plugin.stop_service()

    assert other._session is None
    assert douban._session is None
    assert plugin._image_clients is None


def test_stop_service_is_idempotent_without_any_client(monkeypatch) -> None:
    """
    未发生过图片下载时停止服务不应抛错，init_plugin 会在启动流程中调用它。
    """
    plugin, _ = _spy_clients(monkeypatch, _load_plugin(), USER_AGENT="TestUA", PROXY=None)

    plugin.stop_service()

    assert plugin._image_clients is None


def test_download_image_uses_the_pooled_client(monkeypatch) -> None:
    """
    图片下载入口必须经由复用客户端，而不是就地新建。

    校验 ``set_item_image`` 内部的下载闭包与 ``__image_client`` 的唯一契约点。
    """
    module = _load_plugin()
    plugin, _ = _spy_clients(monkeypatch, module, USER_AGENT="TestUA", PROXY=None)
    client = _image_client(plugin, False)
    calls = []

    class _Response:
        """
        最小响应桩，仅提供下载闭包读取的字节内容。
        """

        content = b"jpeg-bytes"

    def _get_res(url, **_kwargs):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(client, "get_res", _get_res)
    builds = []
    real = module.RequestUtils
    monkeypatch.setattr(
        module,
        "RequestUtils",
        lambda **kwargs: builds.append(kwargs) or real(**kwargs),
    )

    service = SimpleNamespace(instance=SimpleNamespace(
        post_data=lambda **kwargs: SimpleNamespace(status_code=200)
    ))
    monkeypatch.setattr(plugin, "service_infos", lambda _server_type: {"Emby": service})

    assert plugin.set_item_image(
        server="Emby", server_type="emby", itemid="1", imageurl=TMDB_IMAGE_URL
    ) is True
    assert calls == [TMDB_IMAGE_URL]
    assert not builds

    plugin.stop_service()


def test_repeated_images_build_one_pooled_client(monkeypatch) -> None:
    """
    连续下载多张图片时只允许建立一个 HTTP 客户端，且必须开启持久会话。

    直接钉住被修复的行为：旧实现每张图片就地新建不带会话的 RequestUtils，
    同步请求落到无连接池的 ``requests.request``，跨境链路握手成本随图片数量线性叠加。
    """
    module = _load_plugin()
    monkeypatch.setattr(module, "settings", SimpleNamespace(USER_AGENT="TestUA", PROXY=None))
    plugin = object.__new__(module.PersonMeta)
    built = []

    class _Client:
        """
        记录构造参数、请求次数与关闭状态的 RequestUtils 替身。
        """

        def __init__(self, **kwargs):
            self.config = kwargs
            self.requests = 0
            self.closed = False
            built.append(self)

        def get_res(self, url, **_kwargs):
            self.requests += 1
            return SimpleNamespace(content=b"jpeg-bytes")

        def close(self):
            self.closed = True

    monkeypatch.setattr(module, "RequestUtils", _Client)
    service = SimpleNamespace(instance=SimpleNamespace(
        post_data=lambda **kwargs: SimpleNamespace(status_code=200)
    ))
    monkeypatch.setattr(plugin, "service_infos", lambda _server_type: {"Emby": service})

    for itemid in ("1", "2", "3"):
        assert plugin.set_item_image(
            server="Emby", server_type="emby", itemid=itemid, imageurl=TMDB_IMAGE_URL
        ) is True

    assert len(built) == 1
    assert built[0].config["use_session"] is True
    assert built[0].requests == 3

    plugin.stop_service()
    assert built[0].closed is True


def test_douban_image_url_is_routed_to_the_douban_client(monkeypatch) -> None:
    """
    豆瓣图片地址必须落到带 Referer 的那个客户端，两个客户端不可互相顶替。
    """
    module = _load_plugin()
    plugin, _ = _spy_clients(monkeypatch, module, USER_AGENT="TestUA", PROXY=None)
    douban = _image_client(plugin, True)
    other = _image_client(plugin, False)
    routed = []

    class _Response:
        """
        最小响应桩，仅用于记录本次请求命中了哪个客户端。
        """

        content = b"jpeg-bytes"

    def _record(name):
        """
        生成记录客户端名称的 get_res 替身。
        """

        def _get_res(url, **_kwargs):
            routed.append(name)
            return _Response()

        return _get_res

    monkeypatch.setattr(douban, "get_res", _record("douban"))
    monkeypatch.setattr(other, "get_res", _record("other"))
    service = SimpleNamespace(instance=SimpleNamespace(
        post_data=lambda **kwargs: SimpleNamespace(status_code=200)
    ))
    monkeypatch.setattr(plugin, "service_infos", lambda _server_type: {"Emby": service})

    plugin.set_item_image(
        server="Emby", server_type="emby", itemid="1", imageurl=DOUBAN_IMAGE_URL
    )

    assert routed == ["douban"]

    plugin.stop_service()
