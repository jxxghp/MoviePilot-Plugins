from typing import Tuple

from ruamel.yaml import CommentedMap

from app.log import logger
from app.core.config import settings
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.plugins.autosignin.sites import _ISiteSigninHandler


class RousiPro(_ISiteSigninHandler):
    """
    rousi pro 签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "rousi.pro"

    @classmethod
    def match(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作，固定签到
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        ua = site_info.get("ua")
        token = site_info.get("token")
        timeout = site_info.get("timeout")
        if not token or token.strip() == "":
            logger.error(f"{site} 签到失败，缺少 Authorization 信息")
            return False, "签到失败，缺少 Authorization 信息"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}"
        }
        body = {
            "mode": "fixed"
        }
        res = RequestUtils(
            headers=headers,
            timeout=timeout,
            proxies=settings.PROXY if site_info.get("proxy") else None,
        ).post_res(
            url="https://rousi.pro/api/points/attendance",
            json=body
        )

        if res is not None and res.status_code == 200 and res.json().get("code", -1) == 0:
            logger.info(f"{site} 签到成功")
            return True, "签到成功"
        elif res is not None and res.status_code == 400 and res.json().get("code", -1) == 1:
            logger.info(f"{site} 今日已签到")
            return True, "今日已签到"
        elif res is not None and res.status_code == 401:
            logger.error(f"{site} 签到失败，登录状态无效")
            return False, "签到失败，登录状态无效"
        elif res is not None:
            logger.error(f"{site} 签到失败，状态码：{res.status_code}")
            return False, f"签到失败，状态码：{res.status_code}"
        else:
            logger.error(f"{site} 签到失败，无法访问网站")
            return False, "签到失败，无法访问网站"

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作，访问签到统计接口更新站点最后活跃时间
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """
        site = site_info.get("name")
        ua = site_info.get("ua")
        token = site_info.get("token")
        timeout = site_info.get("timeout")
        if not token or token.strip() == "":
            logger.error(f"{site} 模拟登录失败，缺少 Authorization 信息")
            return False, "模拟登录失败，缺少 Authorization 信息"

        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}"
        }
        res = RequestUtils(
            headers=headers,
            timeout=timeout,
            proxies=settings.PROXY if site_info.get("proxy") else None,
        ).get_res(
            url="https://rousi.pro/api/points/attendance/stats"
        )

        if res is not None and res.status_code == 200 and res.json().get("code", -1) == 0:
            logger.info(f"{site} 模拟登录成功")
            return True, "模拟登录成功"
        elif res is not None and res.status_code == 401:
            logger.error(f"{site} 模拟登录失败，登录状态无效")
            return False, "模拟登录失败，登录状态无效"
        elif res is not None:
            logger.error(f"{site} 模拟登录失败，状态码：{res.status_code}")
            return False, f"模拟登录失败，状态码：{res.status_code}"
        else:
            logger.error(f"{site} 模拟登录失败，无法访问网站")
            return False, "模拟登录失败，无法访问网站"
