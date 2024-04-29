from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


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
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        url = site_info.get("url")
        token = site_info.get("token")
        if render:
            # 获取页面html
            html_text = self.get_page_source(url=url,
                                             cookie=site_cookie,
                                             ua=ua,
                                             proxy=proxy,
                                             render=render)
            if not html_text:
                logger.error(f"{site} 模拟登录失败，请检查站点连通性")
                return False, '模拟登录失败，请检查站点连通性'
            if "登 錄" in html_text:
                logger.error(f"{site} 模拟登录失败，Cookie已失效")
                return False, '模拟登录失败，Cookie已失效'
            return True, '模拟登录成功'
        else:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Authorization": token
            }
            res = RequestUtils(headers=headers,
                               timeout=60,
                               proxies=settings.PROXY if proxy else None
                               ).post_res(url=urljoin(url, "api/member/updateLastBrowse"))
            if res:
                logger.info(f'【{site}】模拟登录成功')
                return True, f'模拟登录成功'
            else:
                logger.error(f"{site} 模拟登录失败，{res.status_code if res else '网络错误'}")
                return False, f"模拟登录失败，{res.status_code if res else '网络错误'}"
