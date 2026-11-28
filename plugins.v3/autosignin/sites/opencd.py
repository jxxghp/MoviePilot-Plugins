import json
import time
from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.sdk.config import settings
from app.adapters.external.ocr import OcrHelper
from app.sdk.logging import logger
from app.plugins.autosignin.result import has_signin_evidence, is_challenge_page
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.sdk.network import RequestUtils
from app.sdk.utilities import StringUtils

# 单站签到预算下限（秒），实际预算为 max(本值, 站点超时 + 30)。
MAX_DURATION = 90
# 轮次上限：每轮至多提交一次，含验证码错误与识别失败两种重试。
MAX_SUBMITS = 3
# 单张验证码图片的识别次数，识别服务读不出时才换图。
CAPTCHA_ATTEMPTS_PER_IMAGE = 4
# 验证码识别总次数上限，换图重试不放大公共 OCR 的调用量。
MAX_CAPTCHA_CALLS = 2 * CAPTCHA_ATTEMPTS_PER_IMAGE
# 站点判定验证码无效时重新取整张表单的提示特征。
CAPTCHA_HINTS = ('验证码', 'captcha', 'imagehash')


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
        # 预算覆盖首页在内的全过程；至少留出一次请求余量，避免首页慢直接耗尽预算。
        budget = max(MAX_DURATION, int(timeout or 20) + 30)
        deadline = time.monotonic() + budget

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

        if is_challenge_page(html_text):
            logger.error(f"{site} 签到失败，站点被Cloudflare防护，请打开站点浏览器仿真")
            return False, '签到失败，站点被Cloudflare防护，请打开站点浏览器仿真'

        if "login.php" in html_text:
            logger.error(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        if has_signin_evidence(html_text):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 直接读取响应，避免只取页面文本而丢失与表单 token 配套的新 Cookie。
        signin_url = urljoin(site_url, 'plugin_sign-in.php')
        message = '签到失败，获取签到参数失败'
        captcha_calls = 0
        # 站点判验证码无效时整张表单已作废，重取表单重新识别，提交次数受限。
        for attempt in range(1, MAX_SUBMITS + 1):
            if time.monotonic() > deadline:
                message = f'签到失败，单站签到超时（超过 {int(budget)} 秒）'
                break
            page_res = self._signin_page(signin_url, site_cookie, ua, proxy, timeout, deadline)
            if page_res is None:
                message = '签到失败，签到页面请求失败：未收到响应'
                break
            if page_res.status_code != 200:
                message = (f'签到失败，签到页面返回 HTTP {page_res.status_code}：'
                           f'{self._response_summary(page_res.text)}')
                break

            # 没有签到则解析html
            html = etree.HTML(page_res.text)
            img_urls = html.xpath('//form[@id="frmSignin"]//img/@src') if html is not None else []
            img_hashes = html.xpath('//form[@id="frmSignin"]//input[@name="imagehash"]/@value') if html is not None else []
            csrf_tokens = html.xpath('//form[@id="frmSignin"]//input[@name="csrf_token"]/@value') if html is not None else []
            if not all(values and values[0] for values in (img_urls, img_hashes, csrf_tokens)):
                message = '签到失败，获取签到参数失败'
                break

            # 保留认证 Cookie，同名值以本次签到页下发的值为准；不修改用户保存的配置。
            cookies = dict(part.strip().split('=', 1) for part in (site_cookie or '').split(';') if '=' in part)
            cookies.update(page_res.cookies.get_dict())
            site_cookie = '; '.join(f'{key}={value}' for key, value in cookies.items())

            # 完整验证码url
            img_get_url = urljoin(signin_url, img_urls[0])
            logger.debug(f"{site} 获取到{site}验证码链接 {img_get_url}")
            remaining_calls = MAX_CAPTCHA_CALLS - captcha_calls
            ocr_result, used = self._captcha_text(site, img_get_url, site_cookie, ua, deadline, remaining_calls)
            captcha_calls += used
            if not ocr_result:
                message = '签到失败：未获取到验证码'
                # 同一张图读不出时换新图，与验证码错误共用轮次、时长和识别次数上限。
                if attempt < MAX_SUBMITS and captcha_calls < MAX_CAPTCHA_CALLS:
                    logger.info(f'{site} 未识别到六位验证码，重新获取签到表单（第 {attempt + 1} 轮）')
                    continue
                break
            if time.monotonic() > deadline:
                message = f'签到失败，单站签到超时（超过 {int(budget)} 秒）'
                break

            data = {
                'csrf_token': csrf_tokens[0],
                'imagehash': img_hashes[0],
                'imagestring': ocr_result
            }
            sign_res = RequestUtils(cookies=site_cookie,
                                    ua=ua,
                                    proxies=settings.PROXY if proxy else None,
                                    timeout=self._request_timeout(timeout, deadline),
                                    referer=signin_url
                                    ).post_res(url=signin_url + '?cmd=signin', data=data)
            # 提交无响应时不再提交，避免重复签到；本站没有可用的已签到核对接口。
            if sign_res is None:
                message = '签到失败，签到接口请求失败：未收到响应'
                break
            if sign_res.status_code != 200:
                message = (f'签到失败，签到接口返回 HTTP {sign_res.status_code}：'
                           f'{self._response_summary(sign_res.text)}')
                break
            try:
                sign_dict = json.loads(sign_res.text)
            except (TypeError, ValueError):
                message = '签到失败，签到接口响应不是有效JSON（HTTP 200）'
                break
            if not isinstance(sign_dict, dict):
                message = '签到失败，签到接口响应格式异常（HTTP 200）'
                break
            if sign_dict.get('state') == 'success':
                logger.info(f"{site} 签到成功")
                return True, '签到成功'
            if str(sign_dict.get('state', '')).lower() == 'false' and not str(sign_dict.get('msg') or '').strip():
                # 当日重复提交只回不带 msg 的 state=false；验证码错误等真实失败会带 msg。
                message = '今日已签到（接口未返回原因）'
                logger.info(f"{site} {message}")
                return True, message
            reason = self._response_summary(str(sign_dict.get('msg') or '未返回成功状态'))
            message = f'签到失败，签到接口返回 HTTP 200：{reason}'
            if attempt < MAX_SUBMITS and any(hint in reason.lower() for hint in CAPTCHA_HINTS):
                logger.info(f'{site} {reason}，重新获取签到表单（第 {attempt + 1} 次提交）')
                continue
            break

        logger.error(f'{site} {message}')
        return False, message

    @staticmethod
    def _signin_page(url: str, cookie: str, ua: str, proxy, timeout, deadline: float):
        """
        读取签到表单；未收到响应或服务端 5xx 时原地重试一次，其余 HTTP 错误不重试。

        :param url: 签到页地址
        :param cookie: 当前会话 Cookie
        :param ua: 请求 UA
        :param proxy: 是否使用代理
        :param timeout: 请求超时
        :param deadline: 单站签到截止的单调时钟
        :return: 页面响应；两次均未收到响应时为 None
        """
        page_res = None
        for index in range(2):
            page_res = RequestUtils(cookies=cookie,
                                    ua=ua,
                                    proxies=settings.PROXY if proxy else None,
                                    timeout=Opencd._request_timeout(timeout, deadline)).get_res(url=url)
            if page_res is not None and page_res.status_code < 500:
                break
            if index == 0:
                time.sleep(1)
        return page_res

    @staticmethod
    def _request_timeout(configured, deadline: float) -> int:
        """
        按剩余时长收紧单次请求超时，避免重试突破单站总预算。

        :param configured: 站点配置的请求超时
        :param deadline: 单站签到截止的单调时钟
        :return: 不小于 1 秒且不超过配置值的超时
        """
        remaining = deadline - time.monotonic()
        return max(1, min(int(configured or 20), int(remaining)))

    @staticmethod
    def _captcha_text(site: str, image_url: str, cookie: str, ua: str, deadline: float, limit: int):
        """
        同一张验证码在剩余次数内最多识别 CAPTCHA_ATTEMPTS_PER_IMAGE 次，返回六位结果与已用次数。

        :param site: 站点名称，用于日志
        :param image_url: 验证码图片地址
        :param cookie: 取图使用的会话 Cookie
        :param ua: 请求 UA
        :param deadline: 单站签到截止的单调时钟
        :param limit: 本次允许的最多识别次数
        :return: (六位验证码或 None, 实际识别次数)
        """
        attempts = min(CAPTCHA_ATTEMPTS_PER_IMAGE, limit)
        for times in range(attempts):
            if time.monotonic() > deadline:
                logger.info(f"{site} 验证码识别超时，停止识别")
                return None, times
            ocr_result = OcrHelper().get_captcha_text(image_url=image_url,
                                                     cookie=cookie,
                                                     ua=ua)
            logger.debug(f"ocr识别{site}验证码 {ocr_result}")
            if ocr_result and len(ocr_result) == 6:
                logger.info(f"ocr识别{site}验证码成功 {ocr_result}")
                return ocr_result, times + 1
            logger.debug(f"ocr识别{site}验证码失败，正在进行重试，目前重试次数 {times + 1}")
            if times + 1 < attempts:
                time.sleep(1)
        return None, attempts

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
