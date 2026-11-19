from typing import Optional, Tuple
from urllib.parse import urlparse

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


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
        cookie = str(site_info.get("cookie") or "").strip()
        if not cookie:
            return False, "签到失败，未配置站点Cookie"
        domain = self._host(site_info.get("url")) or self.site_url
        session = self._get(f"https://{domain}{self._session_path}", site_info)
        token = self._access_token(session)
        if not token:
            if session is not None and session.status_code in (401, 403):
                return False, "签到失败，Cookie 已失效，请重新登录站点更新Cookie"
            return False, "签到失败，无法用Cookie获取会话令牌，请重新登录站点更新Cookie"

        api = self._api_template.format(domain=domain)
        status = self._json(self._get(f"{api}/status", site_info, token=token))
        if not isinstance(status, dict):
            return False, "签到失败，签到状态接口返回异常"
        if self._code(status) != 0:
            return False, self._failure(status, "签到失败，签到状态接口返回异常")

        data = status.get("data") or {}
        if data.get("checked_in") is True:
            return True, f"签到成功，今日已签到，连续 {self._days(data)} 天"

        payload = self._json(self._post(f"{api}/check-in", site_info, token=token))
        if not isinstance(payload, dict):
            return False, "签到失败，签到接口返回异常"
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

    @staticmethod
    def _request(url: str, site_info: CommentedMap, token: str = None, method: str = "get"):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            client = RequestUtils(cookies=site_info.get("cookie"),
                                  ua=site_info.get("ua"),
                                  headers=headers,
                                  timeout=site_info.get("timeout"),
                                  proxies=settings.PROXY if site_info.get("proxy") else None)
            if method == "post":
                return client.post_res(url=url, json={})
            return client.get_res(url=url)
        except Exception as err:
            logger.error(f"Sunny 签到请求异常：{str(err)}")
            return None

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
