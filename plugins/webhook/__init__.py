from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.config import settings
from app.core.event import eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class WebHook(_PluginBase):
    # 插件名称
    plugin_name = "Webhook"
    # 插件描述
    plugin_desc = "事件发生时向第三方地址发送请求。"
    # 插件图标
    plugin_icon = "webhook.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "webhook_"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _webhook_url = None
    _method = None
    _enabled = False

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._webhook_url = config.get("webhook_url")
            self._method = config.get('request_method')

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        request_options = ["POST", "GET"]
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'request_method',
                                            'label': '请求方式',
                                            'items': request_options
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'webhook_url',
                                            'label': 'webhook地址'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "request_method": "POST",
            "webhook_url": ""
        }

    def get_page(self) -> List[dict]:
        pass

    @classmethod
    def _serialize_event_data(cls, value: Any, _active: Optional[Set[int]] = None) -> Any:
        """
        将事件载荷只读地转换为可发送的数据结构，不改写原始事件及其嵌套对象。

        广播事件在不同监听器之间共享模型实例、嵌套容器以及枚举单例；这里始终构造
        新的容器并保留既有出站结构兼容，避免原地修改 ``dict``、``list`` 或对象
        ``__dict__``，同时通过当前递归路径集合断开循环引用。
        """
        if _active is None:
            _active = set()

        if isinstance(value, dict):
            obj_id = id(value)
            if obj_id in _active:
                return str(value)
            _active.add(obj_id)
            try:
                return {
                    (
                        k
                        if isinstance(k, (str, int, float, bool, type(None)))
                        else str(k)
                    ): cls._serialize_event_data(v, _active)
                    for k, v in tuple(value.items())
                }
            finally:
                _active.discard(obj_id)

        if isinstance(value, list):
            obj_id = id(value)
            if obj_id in _active:
                return str(value)
            _active.add(obj_id)
            try:
                return [cls._serialize_event_data(item, _active) for item in tuple(value)]
            finally:
                _active.discard(obj_id)

        if isinstance(value, tuple):
            obj_id = id(value)
            if obj_id in _active:
                return str(value)
            _active.add(obj_id)
            try:
                return tuple(cls._serialize_event_data(item, _active) for item in value)
            finally:
                _active.discard(obj_id)

        if isinstance(value, set):
            obj_id = id(value)
            if obj_id in _active:
                return str(value)
            _active.add(obj_id)
            try:
                # JSON 不支持 set，转换为新列表以保证请求体可正常序列化
                return [cls._serialize_event_data(item, _active) for item in tuple(value)]
            finally:
                _active.discard(obj_id)

        if not isinstance(value, type) and callable(getattr(value, "to_dict", None)):
            obj_id = id(value)
            if obj_id in _active:
                return str(value)
            _active.add(obj_id)
            try:
                return cls._serialize_event_data(value.to_dict(), _active)
            finally:
                _active.discard(obj_id)

        if hasattr(value, "__dict__"):
            obj_id = id(value)
            if obj_id in _active:
                return str(value)
            _active.add(obj_id)
            try:
                return cls._serialize_event_data(value.__dict__, _active)
            finally:
                _active.discard(obj_id)

        if isinstance(value, (int, float, str, bool, type(None))):
            return value

        return str(value)

    @eventmanager.register(EventType)
    def send(self, event):
        """
        向第三方Webhook发送请求，将原始事件视为只读输入。
        """
        if not self._enabled or not self._webhook_url:
            return

        if not event or not event.event_type:
            return

        version = getattr(settings, "VERSION_FLAG", "v1")
        event_type = (
            event.event_type
            if version == "v1"
            else getattr(event.event_type, "value", event.event_type)
        )

        event_info = {
            "type": event_type,
            "data": self._serialize_event_data(event.event_data)
        }

        try:
            if self._method == 'POST':
                ret = RequestUtils(content_type="application/json").post_res(self._webhook_url, json=event_info)
            else:
                ret = RequestUtils().get_res(self._webhook_url, params=event_info)
            if ret:
                logger.info(f"发送成功：{self._webhook_url}")
            elif ret is not None:
                logger.error(f"发送失败，状态码：{ret.status_code}，返回信息：{ret.text} {ret.reason}")
            else:
                logger.error("发送失败，未获取到返回信息")
        except Exception as e:
            logger.error(f"发送请求时发生异常：{e}")

    def stop_service(self):
        """
        退出插件
        """
        pass
