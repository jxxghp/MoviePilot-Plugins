"""Webhook 插件只读序列化与 V3 事件广播隔离回归测试。"""

from __future__ import annotations

import copy
import json
import threading
from types import SimpleNamespace

from app.core.event import Event
from app.plugins.webhook import WebHook
from app.runtime.event.binding import EventHandlerBinding
from app.runtime.event.dispatch import EventDispatcher
from app.runtime.event.registry import EventRegistry
from app.schemas.mediaserver import WebhookEventInfo
from app.schemas.types import EventType, MediaSource, MediaType, NotificationType


class _StubBindingResolver:
    """为隔离广播测试直接返回绑定方法，避免依赖全局插件注册表。"""

    def resolve(self, handler):
        owner = getattr(handler, "__self__", None)
        class_name = owner.__class__.__name__ if owner is not None else ""
        method_name = getattr(handler, "__name__", str(handler))
        binding = EventHandlerBinding(
            instance=owner,
            owner_name=class_name or "function",
            run_sync_in_threadpool=False,
        )
        return handler, binding, class_name, method_name


class _DictContainerObj:
    """带内部可变字典引用的自定义对象，用于验证 to_dict 返回值也不会被原地改写。"""

    def __init__(self, payload: dict):
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


class _PlainObject:
    """普通对象，用于验证 __dict__ 递归序列化与循环引用保护。"""

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)


def _make_plugin(method: str = "POST", url: str = "https://example.test/webhook") -> WebHook:
    """绕过宿主完整初始化构造最小可用 WebHook 插件实例。"""
    plugin = object.__new__(WebHook)
    plugin._enabled = True
    plugin._webhook_url = url
    plugin._method = method
    return plugin


def _dispatch_broadcast_in_order(event_type: EventType, event_data, handlers: list) -> None:
    """通过 MoviePilot V3 真实 EventDispatcher.dispatch_broadcast 按注册顺序同步投递事件。"""
    broadcast_subscribers = {
        event_type: {f"handler_{idx}": handler for idx, handler in enumerate(handlers)}
    }
    registry = EventRegistry(
        lock=threading.RLock(),
        broadcast_subscribers=lambda: broadcast_subscribers,
        chain_subscribers=lambda: {},
        disabled_handlers=set,
        disabled_classes=set,
    )
    errors: list[Exception] = []

    def _error_handler(**kwargs):
        err = kwargs.get("e")
        if isinstance(err, Exception):
            errors.append(err)

    dispatcher = EventDispatcher(
        registry=registry,
        binding_resolver=_StubBindingResolver(),
        event_factory=Event,
        error_handler=_error_handler,
        async_handle_sink=lambda _coro: False,
        sync_handle_sink=lambda fn, args: (fn(*args), True)[1],
    )
    dispatcher.dispatch_broadcast(Event(event_type=event_type, event_data=event_data))
    if errors:
        raise errors[0]


def test_broadcast_webhook_event_info_keeps_original_event_and_enum_intact(monkeypatch):
    """复现 #1428：WebHook 先处理后，后续监听器仍收到原生 MediaSource 且枚举单例未被污染。"""
    plugin = _make_plugin()
    sent_requests: list[dict] = []

    class _FakeRequestUtils:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def post_res(self, url, json=None):
            sent_requests.append({"url": url, "json": json, "init": self.kwargs})
            return SimpleNamespace(status_code=200, text="ok", reason="OK")

    monkeypatch.setattr("app.plugins.webhook.RequestUtils", _FakeRequestUtils)

    event_info = WebhookEventInfo(
        event="deep.delete",
        media_source=MediaSource.TMDB,
        media_id="123",
        json_object={"nested": [{"kind": "episode", "tags": ["deep", "delete"]}]},
    )
    json_object_before = event_info.json_object
    nested_list_before = event_info.json_object["nested"]
    nested_entry_before = nested_list_before[0]
    snapshot_before = copy.deepcopy(event_info.model_dump())
    enum_dict_before = dict(MediaSource.TMDB.__dict__)

    downstream_observed = []

    def _downstream_listener(event: Event):
        data = event.event_data
        # 模拟神医同步删除等监听器重新构造 MediaSource 枚举
        resolved_source = MediaSource(data.media_source)
        downstream_observed.append((data, data.media_source, resolved_source))

    _dispatch_broadcast_in_order(
        EventType.WebhookMessage,
        event_info,
        [plugin.send, _downstream_listener],
    )

    # 下游监听器必须看到未改写的原生对象和枚举
    assert len(downstream_observed) == 1
    received_info, received_source, resolved_source = downstream_observed[0]
    assert received_info is event_info
    assert received_source is MediaSource.TMDB
    assert resolved_source is MediaSource.TMDB
    assert event_info.media_source is MediaSource.TMDB
    assert event_info.media_id == "123"
    assert event_info.model_dump() == snapshot_before
    assert event_info.json_object is json_object_before
    assert event_info.json_object["nested"] is nested_list_before
    assert event_info.json_object["nested"][0] is nested_entry_before
    assert event_info.json_object["nested"][0]["tags"] == ["deep", "delete"]

    # 全局枚举单例 __dict__ 不能被污染
    assert dict(MediaSource.TMDB.__dict__) == enum_dict_before
    assert MediaSource.TMDB.__dict__["__objclass__"] is MediaSource

    # 校验出站请求已正常发送且保留既有 type/data 封装及兼容结构
    assert len(sent_requests) == 1
    payload = sent_requests[0]["json"]
    assert payload["type"] == EventType.WebhookMessage.value
    assert payload["data"]["event"] == "deep.delete"
    assert payload["data"]["media_id"] == "123"
    assert payload["data"]["media_source"]["_value_"] == "themoviedb"
    assert payload["data"]["media_source"]["_name_"] == "TMDB"
    assert payload["data"]["json_object"] is not json_object_before
    assert payload["data"]["json_object"]["nested"] is not nested_list_before
    assert payload["data"]["json_object"]["nested"][0] is not nested_entry_before
    # 完整请求体可正常 JSON 序列化
    serialized_json = json.dumps(payload, ensure_ascii=False)
    assert '"deep.delete"' in serialized_json
    assert '"themoviedb"' in serialized_json


def test_broadcast_nested_dict_event_preserves_shared_containers_and_objects(monkeypatch):
    """V3 广播仅浅拷贝字典外层时，WebHook 不得改写共享的嵌套字典、列表、对象和枚举。"""
    plugin = _make_plugin()
    sent_payloads: list[dict] = []

    class _FakeRequestUtils:
        def __init__(self, *args, **kwargs):
            pass

        def post_res(self, url, json=None):
            sent_payloads.append(json)
            return SimpleNamespace(status_code=200, text="ok", reason="OK")

    monkeypatch.setattr("app.plugins.webhook.RequestUtils", _FakeRequestUtils)

    internal_to_dict = {"media_source": MediaSource.TMDB, "items": [NotificationType.Subscribe]}
    to_dict_obj = _DictContainerObj(internal_to_dict)
    shared_list = [MediaSource.Douban, {"mtype": MediaType.TV}]
    shared_sub_dict = {"media_source": MediaSource.TMDB, "history": shared_list}
    shared_tuple = (MediaSource.TMDB, {"kind": MediaType.MOVIE})

    original_event_data = {
        "subscribe_id": 42,
        "meta": shared_sub_dict,
        "snapshot": to_dict_obj,
        "pair": shared_tuple,
    }

    downstream_events: list[dict] = []

    def _second_listener(event: Event):
        downstream_events.append(event.event_data)

    _dispatch_broadcast_in_order(
        EventType.SubscribeModified,
        original_event_data,
        [plugin.send, _second_listener],
    )

    assert len(downstream_events) == 1
    seen = downstream_events[0]
    assert seen["meta"] is shared_sub_dict
    assert seen["meta"]["media_source"] is MediaSource.TMDB
    assert seen["meta"]["history"] is shared_list
    assert seen["meta"]["history"][0] is MediaSource.Douban
    assert seen["meta"]["history"][1]["mtype"] is MediaType.TV
    assert seen["snapshot"] is to_dict_obj
    assert to_dict_obj._payload is internal_to_dict
    assert internal_to_dict["media_source"] is MediaSource.TMDB
    assert internal_to_dict["items"][0] is NotificationType.Subscribe
    assert seen["pair"][0] is MediaSource.TMDB
    assert seen["pair"][1]["kind"] is MediaType.MOVIE

    # 修改出站字典不应反向影响原始数据
    assert len(sent_payloads) == 1
    outbound = sent_payloads[0]
    outbound["data"]["meta"]["media_source"] = "mutated"
    outbound["data"]["meta"]["history"].append("mutated")
    assert original_event_data["meta"]["media_source"] is MediaSource.TMDB
    assert len(original_event_data["meta"]["history"]) == 2
    assert json.dumps(outbound, ensure_ascii=False)


def test_serialize_preserves_shared_dag_references_and_breaks_cycles():
    """同一对象在多处引用时均应完整展开，真正的循环引用应安全退化为字符串而非递归溢出。"""
    shared = {"source": MediaSource.TMDB}
    dag_payload = {"first": shared, "second": shared}

    serialized_dag = WebHook._serialize_event_data(dag_payload)
    assert serialized_dag["first"]["source"]["_value_"] == "themoviedb"
    assert serialized_dag["second"]["source"]["_value_"] == "themoviedb"
    assert serialized_dag["first"] is not shared
    assert serialized_dag["second"] is not shared
    assert shared["source"] is MediaSource.TMDB

    cyclic_dict: dict = {"name": "root"}
    cyclic_dict["self"] = cyclic_dict

    cyclic_list: list = []
    cyclic_list.append(cyclic_list)

    cyclic_obj = _PlainObject(name="node")
    cyclic_obj.self_ref = cyclic_obj

    serialized_dict = WebHook._serialize_event_data(cyclic_dict)
    serialized_list = WebHook._serialize_event_data(cyclic_list)
    serialized_obj = WebHook._serialize_event_data(cyclic_obj)

    assert isinstance(serialized_dict["self"], str)
    assert cyclic_dict["self"] is cyclic_dict
    assert isinstance(serialized_list[0], str)
    assert cyclic_list[0] is cyclic_list
    assert isinstance(serialized_obj["self_ref"], str)
    assert cyclic_obj.self_ref is cyclic_obj
    assert json.dumps(
        {"d": serialized_dict, "l": serialized_list, "o": serialized_obj},
        ensure_ascii=False,
    )


def test_serialize_handles_sets_class_with_to_dict_and_non_string_dict_keys():
    """set 应安全转为 JSON 可序列化列表，类对象的 to_dict 与非字符串键不应触发异常。"""
    original_set = {"DEBUG", "LOG_LEVEL"}
    payload = {
        "keys": original_set,
        "cls_ref": _DictContainerObj,
        "enum_key_map": {MediaType.MOVIE: "ok"},
    }

    serialized = WebHook._serialize_event_data(payload)

    assert isinstance(serialized["keys"], list)
    assert set(serialized["keys"]) == original_set
    assert isinstance(payload["keys"], set)
    assert payload["keys"] is original_set
    assert isinstance(serialized["cls_ref"], str)
    assert serialized["enum_key_map"] == {str(MediaType.MOVIE): "ok"}
    assert json.dumps(serialized, ensure_ascii=False)


def test_send_supports_get_method_plain_string_event_type_and_disabled_guard(monkeypatch):
    """兼容 GET 请求、纯字符串 event_type，并在未启用或缺少地址时跳过发送。"""
    get_calls: list[dict] = []

    class _FakeRequestUtils:
        def __init__(self, *args, **kwargs):
            pass

        def get_res(self, url, params=None):
            get_calls.append({"url": url, "params": params})
            return SimpleNamespace(status_code=200, text="ok", reason="OK")

    monkeypatch.setattr("app.plugins.webhook.RequestUtils", _FakeRequestUtils)

    plugin = _make_plugin(method="GET")
    raw_data = {"media_source": MediaSource.TMDB}
    plugin.send(SimpleNamespace(event_type="custom.event", event_data=raw_data))

    assert len(get_calls) == 1
    assert get_calls[0]["params"]["type"] == "custom.event"
    assert get_calls[0]["params"]["data"]["media_source"]["_value_"] == "themoviedb"
    assert raw_data["media_source"] is MediaSource.TMDB

    disabled_plugin = _make_plugin()
    disabled_plugin._enabled = False
    disabled_plugin.send(SimpleNamespace(event_type=EventType.WebhookMessage, event_data=raw_data))
    assert len(get_calls) == 1
