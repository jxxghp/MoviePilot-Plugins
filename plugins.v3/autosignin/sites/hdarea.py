"""
高清视界的 API Key 签到和登录检测，保留未配置密钥时的 Cookie 签到。
"""

from typing import Any, Optional, Tuple

from ruamel.yaml import CommentedMap

from app.plugins.autosignin.result import has_login_evidence, has_signin_evidence
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.sdk.utilities import StringUtils


class HDArea(_ISiteSigninHandler):
    """
    高清视界签到处理器；已配置 API Key 时不向 Cookie 页面回退。
    """

    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "hdarea.club"

    # 签到成功
    _success_text = "此次签到您获得"
    _repeat_text = "请不要重复签到哦"

    @classmethod
    def match(cls, url: str) -> bool:
        """
        按域名选择高清视界处理器。

        :param url: 站点地址，支持 www 前缀
        :return: 是否属于高清视界
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        优先执行 API 签到；未配置密钥时保持旧 Cookie 行为。

        :param site_info: 站点地址、API Key、Cookie、UA、代理和超时配置
        :return: 是否确认签到及说明；API 失败不重试网页签到
        """
        if str(site_info.get("apikey") or "").strip():
            data, message = self._api_request(site_info, "user/signin", "post")
            if data is None:
                return False, f"签到失败，{message}"
            if data.get("already_signed") is True or has_signin_evidence(message) or self._repeat_text in message:
                return True, "今日已签到"
            return True, "签到成功"
        return self._cookie_signin(site_info)

    @staticmethod
    def _api_request(site_info: CommentedMap, path: str, method: str) -> Tuple[Optional[dict[str, Any]], str]:
        """
        使用 API Key 请求并校验完整信封，错误消息不输出密钥或原始页面。

        :param site_info: 当前站点 API Key 和网络配置
        :param path: API 根地址下的签到或用户资料路径
        :param method: get 或 post；POST 发送空 JSON
        :return: 成功 data 和消息；失败时 data 为 None 且保留错误原因
        """
        apikey = str(site_info.get("apikey") or "").strip()
        site_url = str(site_info.get("url") or "https://hdarea.club/").rstrip("/")
        base_url = str(site_info.get("api_url") or f"{site_url}/api/v1").rstrip("/")
        request = RequestUtils(
            headers={"X-API-Key": apikey, "Accept": "application/json", "Content-Type": "application/json"},
            ua=site_info.get("ua"), proxies=settings.PROXY if site_info.get("proxy") else None,
            timeout=site_info.get("timeout") or 15,
        )
        response = None
        try:
            if method == "post":
                response = request.post_res(url=f"{base_url}/{path}", json={}, allow_redirects=False)
            else:
                response = request.get_res(url=f"{base_url}/{path}", allow_redirects=False)
            if response is None:
                return None, "无法连接 HDArea API"
            try:
                payload = response.json()
            except (TypeError, ValueError):
                payload = {}
            payload = payload if isinstance(payload, dict) else {}
            message = str(payload.get("message") or "").replace(apikey, "[已隐藏]")
            if response.status_code == 401:
                return None, "HDArea API Key 已过期或无效"
            if response.status_code == 403:
                return None, f"HDArea API Key 权限不足或 IP 不在白名单{f'：{message}' if message else ''}"
            if response.status_code != 200:
                return None, f"HDArea API 返回 HTTP {response.status_code}"
            if (payload.get("success") is not True or str(payload.get("code")) != "0"
                    or not isinstance(payload.get("data"), dict)):
                return None, " ".join(message.split())[:300] or "HDArea API 响应结构或业务状态无效"
            return payload["data"], message
        finally:
            if response is not None:
                response.close()

    def _cookie_signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        保留旧 sign_in.php 提交方式，仅用于没有 API Key 的存量站点配置。

        :param site_info: Cookie、UA、代理和超时配置
        :return: 是否确认签到及说明
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxies = settings.PROXY if site_info.get("proxy") else None
        timeout = site_info.get("timeout")

        # 获取页面html
        data = {
            'action': 'sign_in'
        }
        html_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=proxies,
                                timeout=timeout
                                ).post_res(url="https://hdarea.club/sign_in.php", data=data)
        try:
            if html_res is None or html_res.status_code != 200:
                logger.error(f"{site} 签到失败，请检查站点连通性")
                return False, '签到失败，请检查站点连通性'
            if "login.php" in html_res.text:
                logger.error(f"{site} 签到失败，Cookie已失效")
                return False, '签到失败，Cookie已失效'
            if self.sign_in_result(html_res.text, [self._success_text]):
                logger.info(f"{site} 签到成功")
                return True, '签到成功'
            if self.sign_in_result(html_res.text, [self._repeat_text]):
                logger.info(f"{site} 今日已签到")
                return True, '今日已签到'
            logger.error(f"{site} 签到失败，接口未返回明确的签到结果")
            return False, '签到失败'
        finally:
            if html_res is not None:
                html_res.close()

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        用资料 API 检测已配置密钥的站点，签到失败后的保号确认也不访问 Cookie 页面。

        :param site_info: 站点认证和网络配置
        :return: 是否确认登录；登录可用不代表签到完成
        """
        if str(site_info.get("apikey") or "").strip():
            data, message = self._api_request(site_info, "user/profile", "get")
            user_id = str(data.get("id") or "") if data is not None else ""
            if data is not None and user_id.isdecimal() and int(user_id) > 0 and data.get("enabled") is not False:
                return True, "模拟登录成功"
            return False, f"模拟登录失败，{message or 'HDArea API 未返回有效用户资料'}"
        if not site_info.get("cookie"):
            return False, "模拟登录失败，未配置 Cookie 或 API Key"
        if site_info.get("render"):
            page_source = self.get_page_source(
                url=site_info.get("url"), cookie=site_info.get("cookie"), ua=site_info.get("ua"),
                proxy=bool(site_info.get("proxy")), render=True, timeout=site_info.get("timeout") or 60,
            )
            if page_source and has_login_evidence(page_source):
                return True, "模拟登录成功"
            return False, "模拟登录失败，未识别到登录状态"
        response = RequestUtils(cookies=site_info.get("cookie"), ua=site_info.get("ua"),
                                proxies=settings.PROXY if site_info.get("proxy") else None,
                                timeout=site_info.get("timeout") or 15).get_res(url=site_info.get("url"))
        try:
            if response is not None and response.status_code == 200 and has_login_evidence(response.text):
                return True, "模拟登录成功"
            return False, "模拟登录失败，未识别到登录状态"
        finally:
            if response is not None:
                response.close()
