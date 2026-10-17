"""PTZONE 使用 POST 提交签到，GET 访问仅展示签到页面。"""

from typing import Tuple
from urllib.parse import urljoin, urlparse

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.helper.cloudflare import under_challenge
from app.plugins.autosignin.result import has_login_evidence, has_login_form, has_signin_evidence
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class PTZone(_ISiteSigninHandler):
    """单独适配 PTZONE 的提交方式，避免改变其他 NexusPHP 站点的 GET 行为。"""

    site_url = "ptzone.xyz"

    @classmethod
    def match(cls, url: str) -> bool:
        """仅匹配 PTZONE 域名，允许配置首页或签到页地址。"""
        return urlparse(url).hostname in {cls.site_url, f"www.{cls.site_url}"}

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """提交签到并验证登录和完成回执，不能将页面可访问视为已签到。"""
        site_url = site_info.get("url")
        site_cookie = site_info.get("cookie")
        if not site_url or not site_cookie:
            return False, "签到失败，未配置站点地址或Cookie"

        checkin_url = urljoin(site_url, "attendance.php")
        # 该入口按 HTTP 方法执行签到，即使启用浏览器仿真也不能只导航 GET。
        response = RequestUtils(
            cookies=site_cookie,
            ua=site_info.get("ua"),
            referer=checkin_url,
            proxies=settings.PROXY if site_info.get("proxy") else None,
            timeout=site_info.get("timeout") or 60,
        ).post_res(url=checkin_url, data={})
        if response is None:
            return False, "签到失败，无法打开网站"
        if under_challenge(response.text):
            return False, "签到失败，站点被Cloudflare防护"
        if response.status_code != 200:
            return False, f"签到失败，状态码：{response.status_code}"
        if not response.text:
            return False, "签到失败，站点返回空页面"
        if has_login_form(response.text):
            return False, "签到失败，Cookie已失效"
        if not has_login_evidence(response.text):
            return False, "签到失败，未识别到登录状态"
        if has_signin_evidence(response.text):
            return True, "签到成功"
        return False, "签到失败，未确认签到结果"
