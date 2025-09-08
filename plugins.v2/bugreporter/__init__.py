import re
from typing import Any, Dict
from typing import List, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import sentry_sdk
from app.plugins import _PluginBase
from version import APP_VERSION


class SentrySanitizer:
    # 常见敏感字段名（可自行扩展）
    SENSITIVE_KEYS = {
        "password", "passwd", "pwd",
        "secret", "token", "access_token", "refresh_token",
        "authorization", "api_key", "apikey",
        "cookie", "set-cookie", "passkey",
        "key", "credential", "auth", "login", "user", "username",
        "email", "phone", "address", "ip", "host", "domain"
    }

    # 匹配包含敏感关键词的正则
    SENSITIVE_PATTERN = re.compile(
        "|".join(re.escape(key) for key in SENSITIVE_KEYS), re.IGNORECASE
    )

    # 网络连接错误类异常（不上报）
    NETWORK_ERRORS = {
        "ConnectionError", "ConnectionRefusedError", "ConnectionAbortedError",
        "ConnectionResetError", "TimeoutError", "socket.timeout", "socket.error",
        "ssl.SSLError", "ssl.SSLCertVerificationError", "ssl.SSLWantReadError",
        "ssl.SSLWantWriteError", "ssl.SSLZeroReturnError", "ssl.SSLSyscallError",
        "urllib.error.URLError", "urllib.error.HTTPError", "requests.exceptions.ConnectionError",
        "requests.exceptions.Timeout", "requests.exceptions.ConnectTimeout",
        "requests.exceptions.ReadTimeout", "requests.exceptions.SSLError",
        "aiohttp.ClientConnectionError", "aiohttp.ClientTimeout", "aiohttp.ServerTimeoutError",
        "aiohttp.ServerDisconnectedError", "aiohttp.ClientOSError"
    }

    # 网络连接错误关键词
    NETWORK_ERROR_KEYWORDS = [
        "connection", "timeout", "network", "dns", "ssl", "certificate",
        "refused", "reset", "aborted", "unreachable", "no route to host",
        "name or service not known", "temporary failure", "network is unreachable",
        "SOCKSHTTPSConnectionPool", "ERR_HTTP_RESPONSE_CODE_FAILURE", "HTTPSConnectionPool",
        "网络连接", "无法连接", "请求失败", "下载失败", "请求返回空值", "图片失败", "未获取到返回数据",
        "请求返回空值", "返回空响应", "连接出错", "请求错误", "未获取到"
    ]

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
    def is_network_error(cls, event) -> bool:
        """
        判断是否为网络连接错误类异常
        """
        # 检查异常类型
        if "exception" in event:
            for exc in event["exception"].get("values", []):
                if "type" in exc:
                    exc_type = exc["type"]
                    if exc_type in cls.NETWORK_ERRORS:
                        return True
                
                # 检查异常消息是否包含网络错误关键词
                if "value" in exc:
                    exc_value = exc["value"].lower()
                    for keyword in cls.NETWORK_ERROR_KEYWORDS:
                        if keyword in exc_value:
                            return True
        
        # 检查日志消息
        if "message" in event:
            message = event["message"].lower()
            for keyword in cls.NETWORK_ERROR_KEYWORDS:
                if keyword in message:
                    return True
        
        return False

    @classmethod
    def before_send(cls, event, hint):
        """
        在发送到 Sentry 之前脱敏和过滤
        """
        # 如果是网络连接错误，直接返回 None 不上报
        if cls.is_network_error(event):
            return None
        
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
                
                # 清理异常堆栈中的敏感信息
                if "stacktrace" in exc and "frames" in exc["stacktrace"]:
                    for frame in exc["stacktrace"]["frames"]:
                        if "vars" in frame:
                            frame["vars"] = cls.scrub_dict(frame["vars"])
                        if "context_line" in frame and cls.SENSITIVE_PATTERN.search(frame["context_line"]):
                            frame["context_line"] = "[Filtered]"

        # 清理消息中的敏感信息
        if "message" in event and cls.SENSITIVE_PATTERN.search(event["message"]):
            event["message"] = "[Filtered Message]"

        return event


class BugReporter(_PluginBase):
    # 插件名称
    plugin_name = "Bug反馈"
    # 插件描述
    plugin_desc = "自动上报异常，协助开发者发现和解决问题。"
    # 插件图标
    plugin_icon = "Alist_encrypt_A.png"
    # 插件版本
    plugin_version = "1.3"
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
                            release=APP_VERSION,
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
                                            'text': '注意：开启插件即代表你同意将部分异常信息自动发送给开发者，以帮助改进软件；如果你不希望自动发送任何数据，请关闭或卸载此插件；仅上报系统异常信息，不会包含任何个人隐私信息或敏感数据；网络连接错误类异常不会上报；异常信息采集为使用开源项目解决方案：GlitchTip。',
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
