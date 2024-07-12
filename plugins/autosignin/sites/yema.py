from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class YemaPT(_ISiteSigninHandler):
    """
    YemaPT 签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "yemapt.org"

    @classmethod
    def match(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if cls.site_url in url else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": site_info.get("ua"),
            "Accept": "application/json, text/plain, */*",
        }
        # 获取用户信息，更新最后访问时间
        res = (RequestUtils(headers=headers,
                            timeout=15,
                            cookies=site_info.get("cookie"),
                            proxies=settings.PROXY if site_info.get("proxy") else None,
                            referer=site_info.get('url')
                            ).get_res(urljoin(site_info.get('url'), "api/consumer/checkIn")))

        if res and res.json().get("success"):
            return True, "签到成功"
        elif res is not None:
            return False, f"签到失败，签到结果：{res.json().get('errorMessage')}"
        else:
            return False, "签到失败，无法打开网站"

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """

        headers = {
            "Content-Type": "application/json",
            "User-Agent": site_info.get("ua"),
            "Accept": "application/json, text/plain, */*",
        }
        # 获取用户信息，更新最后访问时间
        res = (RequestUtils(headers=headers,
                            timeout=15,
                            cookies=site_info.get("cookie"),
                            proxies=settings.PROXY if site_info.get("proxy") else None,
                            referer=site_info.get('url')
                            ).get_res(urljoin(site_info.get('url'), "api/user/profile")))

        if res and res.json().get("success"):
            return True, "模拟登录成功"
        elif res is not None:
            return False, f"模拟登录失败，状态码：{res.status_code}"
        else:
            return False, "模拟登录失败，无法打开网站"
