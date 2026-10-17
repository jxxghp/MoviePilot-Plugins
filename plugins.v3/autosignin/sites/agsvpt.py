from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.sdk.utilities import StringUtils


class AGSVPT(_ISiteSigninHandler):
    """
    AGSVPT 签到。

    该站点的 attendance.php 是表单页而非动作页：
      GET  attendance.php → 返回「签到」页 + value="立即签到" 提交按钮
      POST attendance.php → 才真正执行签到
    因此通用流程的「GET 即签到」在此站点无效，必须显式提交表单。
    """

    site_url = "agsvpt.com"

    # 未签到时页面含此提交按钮；已签到时按钮消失并出现「签到已得」等文案
    _PENDING_BUTTON = "立即签到"
    # 签到成功的页面标志（NexusPHP 与本站自定义文案）
    _SUCCEED_REGEX = [
        r"签到成功",
        r"\[签到已得\d+",
        r"本次签到获得\s*\d+",
    ]

    @classmethod
    def match(cls, url: str) -> bool:
        """按域名匹配本站点；StringUtils.url_equal 兼容 http/https 与子域。"""
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到：先读取签到页判断是否已签，未签则 POST 提交表单，再回读结果。
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_url = str(site_info.get("url") or "").rstrip("/")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout") or 60

        if not site_url or not site_cookie:
            logger.error(f"{site} 签到失败，未配置站点地址或Cookie")
            return False, "签到失败，未配置站点地址或Cookie"

        attendance_url = f"{site_url}/attendance.php"
        proxies = self._resolve_proxies(proxy)

        try:
            # 第一步：确认登录态并判断是否已签到
            page = self._get(attendance_url, site_cookie, ua, proxies, timeout)
            if page is None:
                return False, "签到失败，无法打开签到页"
            if not self._is_logged_in_page(page):
                logger.error(f"{site} 签到失败，Cookie已失效")
                return False, "签到失败，Cookie已失效"
            if not self._pending_signin(page):
                # 页面没有「立即签到」按钮，说明今天已签到过
                if self.sign_in_result(html_res=page, regexs=self._SUCCEED_REGEX):
                    logger.info(f"{site} 今日已签到")
                    return True, "今日已签到"
                logger.error(f"{site} 签到失败，签到页缺少提交按钮且无成功标志")
                return False, "签到失败，签到页状态未知"

            # 第二步：POST 提交签到表单（站点以表单提交执行签到动作）
            result_page = self._post(attendance_url, site_cookie, ua, proxies, timeout)
            if result_page is None:
                return False, "签到失败，提交签到请求无响应"

            # 第三步：回读结果页确认签到状态
            if self.sign_in_result(html_res=result_page, regexs=self._SUCCEED_REGEX):
                logger.info(f"{site} 签到成功")
                return True, "签到成功"

            # 提交后仍无成功标志时，回读签到页二次确认（部分站点提交后 302 回页面）
            verify_page = self._get(attendance_url, site_cookie, ua, proxies, timeout)
            if verify_page and not self._pending_signin(verify_page) and \
                    self.sign_in_result(html_res=verify_page, regexs=self._SUCCEED_REGEX):
                logger.info(f"{site} 签到成功（回读确认）")
                return True, "签到成功"

            logger.error(f"{site} 签到失败，提交后未确认到签到成功状态")
            return False, "签到失败，提交后未确认到签到成功状态"
        except Exception as e:  # noqa: BLE001
            logger.error(f"{site} 签到异常：{str(e)}")
            return False, f"签到失败：{str(e)}"

    @staticmethod
    def _resolve_proxies(proxy) -> dict | None:
        """按站点开关读取宿主代理配置。"""
        if not proxy:
            return None
        try:
            from app.sdk.config import settings
            return settings.PROXY
        except Exception:  # noqa: BLE001
            return None

    def _get(self, url: str, cookie: str, ua: str, proxies, timeout: int) -> str:
        """GET 页面源码，失败返回空串。"""
        res = RequestUtils(cookies=cookie, ua=ua, proxies=proxies, timeout=timeout).get_res(url=url)
        if res is None or res.status_code != 200:
            return ""
        return res.text or ""

    def _post(self, url: str, cookie: str, ua: str, proxies, timeout: int) -> str:
        """POST 提交签到表单（表单无额外字段，仅需提交动作本身）。

        带上 Referer 模拟从签到页提交，避免站点校验来源。
        """
        headers = {"Referer": url}
        if ua:
            headers["User-Agent"] = ua
        res = RequestUtils(headers=headers,
                           cookies=cookie,
                           proxies=proxies,
                           timeout=timeout
                           ).post_res(url=url, data={})
        if res is None or res.status_code != 200:
            return ""
        return res.text or ""

    @staticmethod
    def _is_logged_in_page(html: str) -> bool:
        """签到页出现登录表单即视为登录态失效。"""
        return 'type="password"' not in (html or "")

    def _pending_signin(self, html: str) -> bool:
        """页面存在「立即签到」提交按钮 = 今天还没签。"""
        return self._PENDING_BUTTON in (html or "")
