import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .schemas import ConnectionResult, SubmitResult


class P115HelperClient:
    """Small, deliberately narrow client for P115StrmHelper's public API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 30,
        verify_ssl: bool = True,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()
        self.timeout = max(1, min(int(timeout), 120))
        self.verify_ssl = bool(verify_ssl)
        self.session = session or requests.Session()

    def validate_config(self) -> Optional[str]:
        if not self.base_url:
            return "P115StrmHelper API地址为空"
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "P115StrmHelper API地址格式无效"
        if not self.token:
            return "MoviePilot API Token为空"
        return None

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _http_error(status_code: int) -> str:
        if status_code in {401, 403}:
            return f"P115StrmHelper认证失败（HTTP {status_code}），请检查Token"
        if status_code == 404:
            return "P115StrmHelper接口不存在（HTTP 404），请检查API地址和插件版本"
        if status_code >= 500:
            return f"P115StrmHelper服务异常（HTTP {status_code}）"
        return f"P115StrmHelper API返回HTTP {status_code}"

    @staticmethod
    def _payload(response: requests.Response) -> Optional[Dict[str, Any]]:
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _safe_message(value: object) -> str:
        """Keep upstream messages useful without ever relaying a full magnet."""

        message = str(value or "")
        return re.sub(
            r"magnet:\?[^\s\"']+",
            "[magnet已脱敏]",
            message,
            flags=re.IGNORECASE,
        )

    def add_offline_task(self, magnet: str) -> SubmitResult:
        config_error = self.validate_config()
        if config_error:
            return SubmitResult(False, config_error)

        try:
            response = self.session.post(
                f"{self.base_url}/add_offline_task",
                headers=self._headers,
                json={"links": [magnet], "path": ""},
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        except requests.Timeout:
            return SubmitResult(False, "连接P115StrmHelper超时")
        except requests.ConnectionError:
            return SubmitResult(False, "无法连接P115StrmHelper")
        except requests.RequestException:
            return SubmitResult(False, "请求P115StrmHelper失败")

        if response.status_code != 200:
            return SubmitResult(False, self._http_error(response.status_code))
        payload = self._payload(response)
        if payload is None:
            return SubmitResult(False, "P115StrmHelper API返回非JSON响应")

        message = self._safe_message(payload.get("msg") or payload.get("message"))
        if payload.get("code") != 0:
            return SubmitResult(False, message or "P115StrmHelper添加离线任务失败")
        return SubmitResult(True, message or "115离线下载任务添加成功")

    def test_connection(self) -> ConnectionResult:
        config_error = self.validate_config()
        if config_error:
            return ConnectionResult(False, config_error)

        try:
            response = self.session.get(
                f"{self.base_url}/get_status",
                headers=self._headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        except requests.Timeout:
            return ConnectionResult(False, "连接P115StrmHelper超时")
        except requests.ConnectionError:
            return ConnectionResult(False, "无法连接P115StrmHelper")
        except requests.RequestException:
            return ConnectionResult(False, "请求P115StrmHelper失败")

        if response.status_code != 200:
            return ConnectionResult(False, self._http_error(response.status_code))
        payload = self._payload(response)
        if payload is None:
            return ConnectionResult(False, "P115StrmHelper API返回非JSON响应")
        if payload.get("code") != 0:
            message = self._safe_message(payload.get("msg") or payload.get("message"))
            return ConnectionResult(False, message or "P115StrmHelper状态检查失败")

        data = payload.get("data")
        if not isinstance(data, dict):
            return ConnectionResult(False, "P115StrmHelper状态响应缺少data")
        if not data.get("enabled"):
            return ConnectionResult(False, "P115StrmHelper插件未启用", data)
        if not data.get("has_client"):
            return ConnectionResult(False, "115客户端未初始化，请检查Cookie", data)
        return ConnectionResult(True, "连接成功，P115StrmHelper和115客户端可用", data)

    def close(self) -> None:
        self.session.close()
