import json
import time
from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.sdk.config import settings
from app.adapters.external.ocr import OcrHelper
from app.sdk.logging import logger
from app.plugins.autosignin.result import has_signin_evidence
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.sdk.network import RequestUtils
from app.sdk.utilities import StringUtils


class Opencd(_ISiteSigninHandler):
    """
    皇后 OCR 签到，保留签到页下发的 CSRF 字段与会话 Cookie。
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "open.cd"

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
        site_url = site_info.get("url")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        # 判断今日是否已签到
        html_text = self.get_page_source(url=site_url,
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)
        if not html_text:
            logger.error(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.error(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        if has_signin_evidence(html_text):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 直接读取响应，避免只取页面文本而丢失与表单 token 配套的新 Cookie。
        signin_url = urljoin(site_url, 'plugin_sign-in.php')
        page_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout or 20).get_res(url=signin_url)
        if page_res is None:
            message = '签到失败，签到页面请求失败：未收到响应'
            logger.error(f"{site} {message}")
            return False, message
        if page_res.status_code != 200:
            message = (f'签到失败，签到页面返回 HTTP {page_res.status_code}：'
                       f'{self._response_summary(page_res.text)}')
            logger.error(f"{site} {message}")
            return False, message

        # 没有签到则解析html
        html = etree.HTML(page_res.text)
        img_urls = html.xpath('//form[@id="frmSignin"]//img/@src') if html is not None else []
        img_hashes = html.xpath('//form[@id="frmSignin"]//input[@name="imagehash"]/@value') if html is not None else []
        csrf_tokens = html.xpath('//form[@id="frmSignin"]//input[@name="csrf_token"]/@value') if html is not None else []
        if not all(values and values[0] for values in (img_urls, img_hashes, csrf_tokens)):
            logger.error(f"{site} 签到失败，获取签到参数失败")
            return False, '签到失败，获取签到参数失败'

        # 保留认证 Cookie，同名值以本次签到页下发的值为准；不修改用户保存的配置。
        cookies = dict(part.strip().split('=', 1) for part in (site_cookie or '').split(';') if '=' in part)
        cookies.update(page_res.cookies.get_dict())
        site_cookie = '; '.join(f'{key}={value}' for key, value in cookies.items())

        # 完整验证码url
        img_get_url = urljoin(signin_url, img_urls[0])
        logger.debug(f"{site} 获取到{site}验证码链接 {img_get_url}")

        # ocr识别多次，获取6位验证码
        times = 0
        ocr_result = None
        # 识别几次
        while times <= 3:
            # ocr二维码识别
            ocr_result = OcrHelper().get_captcha_text(image_url=img_get_url,
                                                      cookie=site_cookie,
                                                      ua=ua)
            logger.debug(f"ocr识别{site}验证码 {ocr_result}")
            if ocr_result:
                if len(ocr_result) == 6:
                    logger.info(f"ocr识别{site}验证码成功 {ocr_result}")
                    break
            times += 1
            logger.debug(f"ocr识别{site}验证码失败，正在进行重试，目前重试次数 {times}")
            time.sleep(1)

        if not ocr_result or len(ocr_result) != 6:
            logger.error(f'{site} 签到失败：未获取到验证码')
            return False, '签到失败：未获取到验证码'

        data = {
            'csrf_token': csrf_tokens[0],
            'imagehash': img_hashes[0],
            'imagestring': ocr_result
        }
        sign_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout or 20,
                                referer=signin_url
                                ).post_res(url=signin_url + '?cmd=signin', data=data)
        # requests 的非 2xx 响应可能是假值，必须显式区分无响应和 HTTP 错误。
        if sign_res is None:
            message = '签到失败，签到接口请求失败：未收到响应'
        elif sign_res.status_code != 200:
            message = (f'签到失败，签到接口返回 HTTP {sign_res.status_code}：'
                       f'{self._response_summary(sign_res.text)}')
        else:
            try:
                sign_dict = json.loads(sign_res.text)
            except (TypeError, ValueError):
                message = '签到失败，签到接口响应不是有效JSON（HTTP 200）'
            else:
                if not isinstance(sign_dict, dict):
                    message = '签到失败，签到接口响应格式异常（HTTP 200）'
                elif sign_dict.get('state') == 'success':
                    logger.info(f"{site} 签到成功")
                    return True, '签到成功'
                else:
                    reason = self._response_summary(str(sign_dict.get('msg') or '未返回成功状态'))
                    message = f'签到失败，签到接口返回 HTTP 200：{reason}'
        logger.error(f'{site} {message}')
        return False, message

    @staticmethod
    def _response_summary(text: str) -> str:
        """
        提取简短可读的响应摘要，避免输出整页 HTML、脚本或表单属性。

        :param text: 站点响应文本或业务错误消息
        :return: 最多 200 字符的单行摘要
        """
        html = etree.HTML(text or '')
        if html is not None:
            text = ' '.join(html.xpath('//text()[not(ancestor::script or ancestor::style)]'))
        return ' '.join((text or '').split())[:200] or '空响应'
