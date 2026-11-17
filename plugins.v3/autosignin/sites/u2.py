import datetime
import random
import re
import time
from typing import Tuple
from urllib.parse import urljoin, urlparse

from lxml import etree
from ruamel.yaml import CommentedMap

from app.sdk.config import settings
from app.sdk.logging import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.sdk.network import RequestUtils
from app.sdk.network import SiteUtils
from app.sdk.utilities import StringUtils


class U2(_ISiteSigninHandler):
    """
    U2签到 随机
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "u2.dmhy.org"

    # 顶部导航可能沿用昨日状态，只接受站点明确的当天完成提示。
    _sign_regex = [r'(?:感谢|感謝)[，,]\s*(?:今天|今日)已[签簽]到[。.!]']

    # 相对或绝对 URL 的跳转脚本仅用于诊断，不能作为回读条件或成功凭据。
    _success_redirect_regex = re.compile(
        r"window\s*\.\s*location\s*\.\s*href\s*=\s*['\"]([^'\"]+)['\"]"
    )

    @classmethod
    def _is_success_response(cls, response_text: str) -> bool:
        """识别提交后的签到页跳转供日志诊断，不影响后续回读确认。"""
        match = cls._success_redirect_regex.search(response_text)
        if not match:
            return False

        target = urlparse(urljoin("https://u2.dmhy.org/showup.php", match.group(1)))
        return target.netloc.casefold() == cls.site_url and target.path == "/showup.php"

    @classmethod
    def _has_signed_state(cls, html_text: str) -> bool:
        """已登录且显示当天完成提示时确认签到；历史查询表单不代表待答题。"""
        if not html_text or not SiteUtils.is_logged_in(html_text):
            return False
        html = etree.HTML(html_text)
        return (html is not None and not html.xpath('//input[@name="req"]')
                and cls.sign_in_result(html_text, cls._sign_regex))

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

        now = datetime.datetime.now()
        # 判断当前时间是否小于9点
        if now.hour < 9:
            logger.error(f"{site} 签到失败，9点前不签到")
            return False, '签到失败，9点前不签到'

        # 获取页面html
        html_text = self.get_page_source(url="https://u2.dmhy.org/showup.php",
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)
        if not html_text:
            logger.error(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        # 已登录页面的脚本权限数据可能包含 maxlogin.php，不能用 login.php 子串判断登录状态。
        if not SiteUtils.is_logged_in(html_text):
            logger.error(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        # 判断是否已签到
        sign_status = self._has_signed_state(html_text)
        if sign_status:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 没有签到则解析html
        html = etree.HTML(html_text)

        if html is None:
            return False, '签到失败'

        # 一次性 req 定位真实答题表单，避免混入历史查询的提交按钮或其他参数。
        signin_forms = html.xpath("//form[.//input[@name='req']]")
        if not signin_forms:
            logger.error(f"{site} 签到失败，未获取到相关签到参数")
            return False, '签到失败'
        signin_form = signin_forms[0]
        req = signin_form.xpath(".//input[@name='req']/@value")
        hash_str = signin_form.xpath(".//input[@name='hash']/@value")
        form = signin_form.xpath(".//input[@name='form']/@value")
        csrf_token = signin_form.xpath(".//input[@name='_csrf']/@value")
        submit_name = signin_form.xpath(".//td/input[@type='submit']/@name")
        submit_value = signin_form.xpath(".//td/input[@type='submit']/@value")
        if (
            not req
            or not hash_str
            or not form
            or not csrf_token
            or not submit_name
            or not submit_value
        ):
            logger.error(f"{site} 签到失败，未获取到相关签到参数")
            return False, '签到失败'

        # 随机一个答案
        answer_num = random.randint(0, 3)
        data = {
            'req': req[0],
            'hash': hash_str[0],
            'form': form[0],
            '_csrf': csrf_token[0],
            'message': '一切随缘~',
            submit_name[answer_num]: submit_value[answer_num]
        }
        # 签到
        sign_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None,
                                headers={
                                    "User-Agent": ua,
                                    "Referer": "https://u2.dmhy.org/showup.php",
                                    "Origin": "https://u2.dmhy.org",
                                }
                                ).post_res(url="https://u2.dmhy.org/showup.php?action=show",
                                           data=data)
        if not sign_res or sign_res.status_code != 200:
            logger.error(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # 答错提示页等响应可能没有跳转脚本；提交后始终回读，最多额外重试两次 GET。
        if not self._is_success_response(sign_res.text):
            logger.info(f"{site} 签到提交未匹配到签到页跳转脚本，仍将回读确认")
        for attempt in range(3):
            if attempt:
                logger.info(f"{site} 签到结果暂未确认，1秒后回读重试（{attempt}/2）")
                time.sleep(1)
            checked_page = self.get_page_source(url="https://u2.dmhy.org/showup.php",
                                                cookie=site_cookie, ua=ua, proxy=proxy,
                                                render=render, timeout=timeout)
            if self._has_signed_state(checked_page):
                logger.info(f"{site} 签到成功")
                return True, '签到成功'
        logger.error(f"{site} 签到失败，未确认签到结果")
        return False, '签到失败，未确认签到结果'
