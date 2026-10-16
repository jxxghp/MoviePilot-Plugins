import base64
import hashlib
import hmac
import time
from typing import Optional, Tuple

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class MTorrent(_ISiteSigninHandler):
    """
    馒头仅通过更新访问时间保号，签到和登录共用同一接口。
    """

    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "m-team"
    # 签到接口本身完成登录保号，失败后不再用同一接口做登录回退。
    signin_is_login = True

    # updateLastBrowse 是前端 Web API：请求体必须携带毫秒时间戳和 HMAC-SHA1 签名，
    # Authorization 使用浏览器登录态 JWT（localStorage.auth），对应站点配置的 Token 字段。
    _api_path = "/api/member/updateLastBrowse"
    # 签名密钥由主站前端 main.*.js 生成，社区实现与抓包结果一致；站点轮换后需同步更新。
    _sign_secret = "HLkPcWmycL57mfJt"
    # 前端版本号参与请求指纹，站点发版可能变化，但不参与签名校验。
    _web_version = "2000"

    @classmethod
    def match(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if cls.site_url in url.split(".") else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作，馒头实际没有签到，通过更新最后访问时间确认登录态有效。
        :param site_info: 站点信息，含有站点Url、站点Token（浏览器登录态）等信息
        :return: 签到结果信息
        """
        url = str(site_info.get("url") or "").rstrip("/")
        token = str(site_info.get("token") or "").strip()
        if not url or not token:
            return False, "模拟登录失败，未配置站点Token（需填写浏览器登录态Authorization）"
        domain = StringUtils.get_url_domain(url)
        timestamp_ms = int(time.time() * 1000)
        # 更新最后访问时间
        res = RequestUtils(headers=self._build_headers(url=url,
                                                       token=token,
                                                       ua=site_info.get("ua"),
                                                       timestamp_ms=timestamp_ms),
                           timeout=site_info.get("timeout"),
                           proxies=settings.PROXY if site_info.get("proxy") else None
                           ).post_res(
            url=f"https://api.{domain}{self._api_path}",
            data={"_timestamp": str(timestamp_ms),
                  "_sgin": self._build_sign(timestamp_ms=timestamp_ms)},
        )
        if res is None:
            return False, "模拟登录失败，无法打开网站"
        if res.status_code != 200:
            return False, f"模拟登录失败，状态码：{res.status_code}"
        try:
            payload = res.json()
        except ValueError:
            return False, "模拟登录失败，接口返回数据异常"
        return self._parse_payload(payload)

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """
        return self.signin(site_info)

    def _build_headers(self, url: str, token: str, ua: Optional[str], timestamp_ms: int) -> dict:
        """构造认证与指纹请求头，did/visitorid 按登录态稳定派生，避免每轮都被识别为新设备。"""
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Authorization": token,
            "Origin": url,
            "Referer": f"{url}/index",
            "Ts": str(timestamp_ms // 1000),
            "webversion": self._web_version,
            "Did": fingerprint[:32],
            "visitorid": fingerprint[32:],
        }
        if ua:
            headers["User-Agent"] = ua
        return headers

    def _build_sign(self, timestamp_ms: int) -> str:
        """按前端算法生成签名：HMAC-SHA1(密钥, POST&接口路径&毫秒时间戳) 的 Base64 结果。"""
        message = f"POST&{self._api_path}&{timestamp_ms}".encode()
        digest = hmac.new(self._sign_secret.encode(), message, hashlib.sha1).digest()
        return base64.b64encode(digest).decode()

    @staticmethod
    def _parse_payload(payload) -> Tuple[bool, str]:
        """按接口业务状态判定结果：HTTP 200 或前端错误码都不代表访问时间更新成功。"""
        if not isinstance(payload, dict):
            return False, "模拟登录失败，接口返回数据异常"
        code = str(payload.get("code"))
        message = str(payload.get("message") or "").strip()
        if payload.get("success") is True or code == "0" or message.upper() == "SUCCESS":
            return True, "模拟登录成功"
        # 站点 2026-10 起该接口成功时同样返回 {"code":"1","message":"FAIL","data":null}，仅此组合可确认。
        if code == "1" and message.upper() == "FAIL":
            return True, "模拟登录成功"
        if code == "401" or "full authentication" in message.lower():
            return False, "模拟登录失败，Token登录态已失效，请重新登录站点后更新Token"
        return False, "模拟登录失败，接口未确认访问时间更新"
