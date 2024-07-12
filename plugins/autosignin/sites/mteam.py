from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class MTorrent(_ISiteSigninHandler):
    """
    m-team签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "m-team"

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
        执行签到操作，馒头实际没有签到，非仿真模式下需要更新访问时间
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": site_info.get("ua"),
            "Accept": "application/json, text/plain, */*",
            "Authorization": site_info.get("token")
        }
        url = site_info.get('url')
        domain = StringUtils.get_url_domain(url)
        # 更新最后访问时间
        res = RequestUtils(headers=headers,
                           timeout=60,
                           proxies=settings.PROXY if site_info.get("proxy") else None,
                           referer=f"{url}index"
                           ).post_res(url=f"https://api.{domain}/api/member/updateLastBrowse")
        if res:
            return True, "模拟登录成功"
        elif res is not None:
            return False, f"模拟登录失败，状态码：{res.status_code}"
        else:
            return False, "模拟登录失败，无法打开网站"

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """
        return self.signin(site_info)
