import time
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests
from ruamel.yaml import CommentedMap

from app.sdk.config import settings
from app.sdk.logging import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.sdk.network import RequestUtils


class SunnyPT(_ISiteSigninHandler):
    """
    Sunny 新版前端把签到交给独立 API，站点 Cookie 只能换取会话 accessToken，
    签到请求必须携带该 Token，因此先兑换再调用。
    """

    site_url = "sunnypt.top"
    # 兑换会话与签到共用同一登录态，失败后不再重复调用做登录回退。
    signin_is_login = True

    _session_path = "/api/auth/session"
    _api_template = "https://api.{domain}/api/v1/attendance"

    # 业务码：0 成功，400001 今日已签到，401000 会话失效。
    _code_duplicate = 400001
    _code_unauthorized = 401000

    # 站点接口偶发分钟级延迟，只读请求幂等，失败后重试一次；提交签到不重试。
    _read_attempts = 2
    _retry_pause = 3
    # attendance 接口实测可慢到 60 秒以上，站点默认 15 秒会稳定误判，这里保底放宽。
    _min_timeout = 60
    # 最近一次请求异常，仅用于把底层原因带进失败文案。
    _last_error = None

    @classmethod
    def match(cls, url: str) -> bool:
        """只匹配站点主域，API 子域与相近域名都不接手。"""
        return cls._host(url) == cls.site_url

    @staticmethod
    def _host(url: str) -> str:
        """提取主机名，站点地址可能缺少协议头。"""
        raw = str(url or "").strip()
        return (urlparse(raw if "//" in raw else f"//{raw}").hostname or "").lower()

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """用站点 Cookie 换取 accessToken 后提交签到。"""
        self._last_error = None
        cookie = str(site_info.get("cookie") or "").strip()
        if not cookie:
            return False, "签到失败，未配置站点Cookie"
        domain = self._host(site_info.get("url")) or self.site_url
        session = self._get(f"https://{domain}{self._session_path}", site_info)
        token = self._access_token(session)
        if not token:
            if session is None:
                # 请求超时或连接失败时没有响应，不能当作 Cookie 失效。
                return False, f"签到失败，无法访问站点会话接口，{self._reason('请求失败')}"
            if session.status_code == 401:
                return False, "签到失败，Cookie 已失效，请重新登录站点更新Cookie"
            if session.status_code == 403:
                return False, "签到失败，站点访问被拒绝（HTTP 403）"
            if session.status_code != 200:
                return False, f"签到失败，站点会话接口状态码：{session.status_code}！"
            return False, "签到失败，无法用Cookie获取会话令牌，请重新登录站点更新Cookie"

        api = self._api_template.format(domain=domain)
        status = self._json(self._get(f"{api}/status", site_info, token=token))
        if not isinstance(status, dict):
            return False, f"签到失败，签到状态接口{self._reason('返回异常')}"
        if self._code(status) != 0:
            return False, self._failure(status, "签到失败，签到状态接口返回异常")

        data = status.get("data") or {}
        if data.get("checked_in") is True:
            return True, f"签到成功，今日已签到，连续 {self._days(data)} 天"

        payload = self._json(self._post(f"{api}/check-in", site_info, token=token))
        if not isinstance(payload, dict):
            # 提交超时或响应不可解析时服务端可能已经受理，回查当日状态再判定。
            verified = self._json(self._get(f"{api}/status", site_info, token=token))
            if isinstance(verified, dict) and self._code(verified) == 0:
                body = verified.get("data") or {}
                if body.get("checked_in") is True:
                    return True, f"签到成功，今日已签到，连续 {self._days(body)} 天"
            return False, f"签到失败，签到接口{self._reason('返回异常')}"
        code = self._code(payload)
        if code == 0:
            body = payload.get("data") or {}
            return True, f"签到成功，获得 {body.get('points', 0)} 魔力，连续 {self._days(body)} 天"
        if code == self._code_duplicate:
            return True, "签到成功，今日已签到"
        if code == self._code_unauthorized:
            return False, "签到失败，会话令牌已失效，请重新登录站点更新Cookie"
        return False, self._failure(payload, "签到失败，签到接口未确认签到结果")

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """签到同时验证会话，登录保号复用同一入口。"""
        return self.signin(site_info)

    def _get(self, url: str, site_info: CommentedMap, token: str = None):
        """读取接口，带 Cookie 时用于兑换会话，带 Token 时用于签到接口。"""
        return self._request(url=url, site_info=site_info, token=token)

    def _post(self, url: str, site_info: CommentedMap, token: str = None):
        """提交签到，请求体为空对象。"""
        return self._request(url=url, site_info=site_info, token=token, method="post")

    def _request(self, url: str, site_info: CommentedMap, token: str = None, method: str = "get"):
        """
        执行接口请求，异常原因保留给失败信息使用。

        读请求失败后重试一次；提交签到只请求一次，避免重复提交，
        未确认结果时由调用方回查当日状态。
        """
        headers = {"Accept": "application/json"}
        ua = str(site_info.get("ua") or "").strip()
        if ua:
            # 显式传入 headers 时 RequestUtils 不再补 UA，需要自行带上站点 UA。
            headers["User-Agent"] = ua
        if token:
            headers["Authorization"] = f"Bearer {token}"
        attempts = 1 if method == "post" else self._read_attempts
        timeout = self._timeout(site_info)
        for attempt in range(1, attempts + 1):
            try:
                client = RequestUtils(cookies=site_info.get("cookie"),
                                      headers=headers,
                                      timeout=timeout,
                                      proxies=settings.PROXY if site_info.get("proxy") else None)
                if method == "post":
                    return client.post_res(url=url, json={}, raise_exception=True)
                return client.get_res(url=url, raise_exception=True)
            except Exception as err:
                # RequestUtils 默认吞掉网络异常返回 None，这里显式抛出后保留真实原因。
                self._last_error = err
                logger.error(f"Sunny 签到请求异常（第 {attempt}/{attempts} 次）：{url} {str(err)}")
                if attempt < attempts:
                    time.sleep(self._retry_pause)
        return None

    @classmethod
    def _timeout(cls, site_info: CommentedMap) -> int:
        """站点默认超时不足以覆盖该站抖动，单次请求不低于 60 秒。"""
        try:
            configured = int(site_info.get("timeout") or 0)
        except (TypeError, ValueError):
            configured = 0
        return max(configured, cls._min_timeout)

    def _reason(self, default: str) -> str:
        """
        把底层请求异常转换为通知可分类的简短原因。

        :param default: 非网络异常时使用的原因
        :return: 失败原因片段
        """
        error = self._last_error
        if isinstance(error, requests.exceptions.Timeout):
            return "请求超时"
        if isinstance(error, requests.exceptions.RequestException):
            return "网络连接失败"
        return default

    @staticmethod
    def _access_token(response) -> str:
        """会话接口返回的 accessToken 是 JWT，格式异常时按未登录处理。"""
        if response is None or response.status_code != 200:
            return ""
        try:
            data = response.json().get("data") or {}
        except ValueError:
            return ""
        token = str(data.get("accessToken") or "").strip()
        return token if token.count(".") == 2 else ""

    @staticmethod
    def _json(response) -> Optional[dict]:
        if response is None:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _code(payload: dict) -> Optional[int]:
        try:
            return int(payload.get("code"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _message(payload: dict) -> str:
        return str(payload.get("msg") or "").strip()

    def _failure(self, payload: dict, fallback: str) -> str:
        message = self._message(payload)
        return f"签到失败，{message}" if message else fallback

    @staticmethod
    def _days(data: dict) -> int:
        try:
            return int(data.get("days") or 0)
        except (TypeError, ValueError):
            return 0
