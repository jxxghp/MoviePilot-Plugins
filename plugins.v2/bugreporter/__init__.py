import re
from typing import Any, Dict
from typing import List, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import sentry_sdk
from app.plugins import _PluginBase


class SentrySanitizer:
    # 常见敏感字段名（可自行扩展）
    SENSITIVE_KEYS = {
        "password", "passwd", "pwd",
        "secret", "token", "access_token", "refresh_token",
        "authorization", "api_key", "apikey",
        "cookie", "set-cookie", "passkey"
    }

    # 匹配包含敏感关键词的正则
    SENSITIVE_PATTERN = re.compile(
        "|".join(re.escape(key) for key in SENSITIVE_KEYS), re.IGNORECASE
    )

    @classmethod
    def scrub_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        递归清洗字典中的敏感信息
        """
        if not isinstance(data, dict):
            return data

        sanitized = {}
        for key, value in data.items():
            if isinstance(value, dict):
                sanitized[key] = cls.scrub_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [cls.scrub_dict(v) if isinstance(v, dict) else v for v in value]
            else:
                if cls.SENSITIVE_PATTERN.search(str(key)):
                    sanitized[key] = "[Filtered]"
                else:
                    sanitized[key] = value
        return sanitized

    @classmethod
    def scrub_url(cls, url: str) -> str:
        """
        清理 URL 中的敏感 query 参数
        """
        try:
            parsed = urlparse(url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            for key in query:
                if cls.SENSITIVE_PATTERN.search(key):
                    query[key] = ["[Filtered]"]
            new_query = urlencode(query, doseq=True)
            return urlunparse(parsed._replace(query=new_query))
        except Exception as err:
            print(str(err))
            return url

    @classmethod
    def before_send(cls, event, hint):
        """
        在发送到 Sentry 之前脱敏
        """
        # 处理 request 数据
        request = event.get("request", {})
        if "url" in request:
            request["url"] = cls.scrub_url(request["url"])
        if "headers" in request:
            request["headers"] = cls.scrub_dict(request["headers"])
        if "data" in request:
            request["data"] = cls.scrub_dict(request["data"])
        if "cookies" in request:
            request["cookies"] = cls.scrub_dict(request["cookies"])

        # 处理 user 数据
        if "user" in event:
            event["user"] = cls.scrub_dict(event["user"])

        # 处理 extra 数据
        if "extra" in event:
            event["extra"] = cls.scrub_dict(event["extra"])

        # 处理异常信息（避免敏感数据出现在 message 中）
        if "exception" in event:
            for exc in event["exception"].get("values", []):
                if "value" in exc and cls.SENSITIVE_PATTERN.search(exc["value"]):
                    exc["value"] = "[Filtered Exception Message]"

        return event


class BugReporter(_PluginBase):
    # 插件名称
    plugin_name = "Bug反馈"
    # 插件描述
    plugin_desc = "自动上报异常，协助开发者发现和解决问题。"
    # 插件图标
    plugin_icon = "Alist_encrypt_A.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "bugreporter_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False

    def init_plugin(self, config: dict = None):
        self._enable = config.get("enable")
        if self._enable:
            sentry_sdk.init("https://88da01ad33b4423cb0380620de53efa8@glitchtip.movie-pilot.org/1",
                            before_send=SentrySanitizer.before_send,
                            send_default_pii=False)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                            'model': 'enable',
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
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '注意：开启插件即代表你同意将部分异常信息自动发送给开发者，以帮助改进软件；如果你不希望自动发送任何数据，请关闭或卸载此插件；仅上报系统异常信息，不会包含任何个人隐私信息或敏感数据；异常信息采集为使用开源项目解决方案：GlitchTip。',
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enable": self._enable,
        }

    def get_page(self) -> List[dict]:
        pass

    def get_state(self) -> bool:
        return self._enable

    def stop_service(self):
        pass
