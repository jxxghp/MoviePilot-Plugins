from typing import Tuple

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.string import StringUtils


class PTTime(_ISiteSigninHandler):
    """
    PT时间签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "pttime.org"

    # 签到成功
    _succeed_regex = ['签到成功']

    @classmethod
    def match(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: dict) -> Tuple[bool, str]:
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

        # 签到
        # 签到返回：<html><head></head><body>签到成功</body></html>
        html_text = self.get_page_source(url='https://www.pttime.org/attendance.php',
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render)

        if not html_text:
            logger.error(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.error(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        sign_status = self.sign_in_result(html_res=html_text,
                                          regexs=self._succeed_regex)
        if sign_status:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.error(f"{site} 签到失败，签到接口返回 {html_text}")
        return False, '签到失败'
