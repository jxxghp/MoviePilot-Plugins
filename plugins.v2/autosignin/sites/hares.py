import json
from typing import Tuple

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class Hares(_ISiteSigninHandler):
    """
    白兔签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "club.hares.top"

    # 已签到
    _sign_text = '已签到'

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
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        # 获取页面html
        html_text = self.get_page_source(url='https://club.hares.top',
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)

        if not html_text:
            logger.error(f"{site} 模拟访问失败，请检查站点连通性")
            return False, '模拟访问失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.error(f"{site} 模拟访问失败，Cookie已失效")
            return False, '模拟访问失败，Cookie已失效'

        # if self._sign_text in html_res.text:
        #     logger.info(f"今日已签到")
        #     return True, '今日已签到'

        headers = {
            'Accept': 'application/json',
            "User-Agent": ua
        }
        sign_res = RequestUtils(cookies=site_cookie,
                                headers=headers,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout
                                ).get_res(url="https://club.hares.top/attendance.php?action=sign")
        if not sign_res or sign_res.status_code != 200:
            logger.error(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # {"code":1,"msg":"您今天已经签到过了"}
        # {"code":0,"msg":"签到成功"}
        sign_dict = json.loads(sign_res.text)
        if sign_dict['code'] == 0:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'
        else:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'
