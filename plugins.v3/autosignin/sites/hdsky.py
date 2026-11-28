import json
import re
import time
from typing import Optional, Tuple

from ruamel.yaml import CommentedMap

from app.sdk.config import settings
from app.adapters.external.ocr import OcrHelper
from app.sdk.logging import logger
from app.plugins.autosignin.result import is_challenge_page
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.sdk.network import RequestUtils
from app.sdk.utilities import StringUtils

# 单站签到总时长下限（秒），实际预算随站点超时放宽。
MAX_DURATION = 90
# 轮次上限：每轮至多提交一次，验证码错误与识别失败都换新图重来。
MAX_SUBMITS = 3
# 单张验证码图最多识别次数，读不出就换图。
CAPTCHA_ATTEMPTS_PER_IMAGE = 4
# 验证码识别总次数上限，换图重试不放大公共 OCR 的调用量。
MAX_CAPTCHA_CALLS = 2 * CAPTCHA_ATTEMPTS_PER_IMAGE
# 取验证码图的请求次数上限，站点偶发失败时重试。
IMAGE_FETCH_ATTEMPTS = 4
CAPTCHA_LENGTH = 6


class HDSky(_ISiteSigninHandler):
    """
    天空ocr签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "hdsky.me"

    # 已签到
    _sign_regex = ['已签到']

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
        referer = site_info.get("url")
        timeout = site_info.get("timeout")
        # 预算覆盖首页在内的全过程；至少留出一次请求余量，避免首页慢直接耗尽预算。
        budget = max(MAX_DURATION, int(timeout or 20) + 30)
        deadline = time.monotonic() + budget

        # 判断今日是否已签到
        html_text = self.get_page_source(url='https://hdsky.me',
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

        sign_status = self.sign_in_result(html_res=html_text,
                                          regexs=self._sign_regex)
        if sign_status:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        message = '签到失败：未获取到验证码'
        captcha_calls = 0
        # 站点判验证码无效时该 imagehash 一并作废，换新图重新识别，提交次数受限。
        for round_no in range(1, MAX_SUBMITS + 1):
            if time.monotonic() > deadline:
                message = f'签到失败，单站签到超时（超过 {int(budget)} 秒）'
                break
            if captcha_calls >= MAX_CAPTCHA_CALLS:
                message = '签到失败：未获取到验证码'
                break
            img_hash = self._new_image_hash(site, site_cookie, ua, proxy, timeout, deadline)
            if not img_hash:
                message = (f'签到失败，单站签到超时（超过 {int(budget)} 秒）'
                           if time.monotonic() > deadline else '签到失败：未获取到验证码')
                break

            img_get_url = 'https://hdsky.me/image.php?action=regimage&imagehash=%s' % img_hash
            logger.info(f"获取到 {site} 验证码链接：{img_get_url}")
            ocr_result, used = self._captcha_text(
                site, img_get_url, site_cookie, ua,
                min(CAPTCHA_ATTEMPTS_PER_IMAGE, MAX_CAPTCHA_CALLS - captcha_calls), deadline)
            captcha_calls += used
            if not ocr_result:
                message = (f'签到失败，单站签到超时（超过 {int(budget)} 秒）'
                           if time.monotonic() > deadline else '签到失败：未获取到验证码')
                if round_no < MAX_SUBMITS:
                    logger.info(f"{site} 未识别到六位验证码，重新获取验证码（第 {round_no + 1} 轮）")
                continue
            if time.monotonic() > deadline:
                message = f'签到失败，单站签到超时（超过 {int(budget)} 秒）'
                break

            data = {
                'action': 'showup',
                'imagehash': img_hash,
                'imagestring': ocr_result
            }
            res = RequestUtils(cookies=site_cookie,
                               ua=ua,
                               referer=referer,
                               proxies=settings.PROXY if proxy else None,
                               timeout=self._request_timeout(timeout, deadline)
                               ).post_res(url='https://hdsky.me/showup.php', data=data)
            # 提交无响应时不再提交，避免重复签到。
            if res is None:
                message = '签到失败，签到接口请求失败：未收到响应'
                break
            if is_challenge_page(res.text):
                message = '签到失败，站点被Cloudflare防护，请打开站点浏览器仿真'
                break
            if res.status_code != 200:
                message = f'签到失败，签到接口返回 HTTP {res.status_code}：{self._response_summary(res.text)}'
                break
            payload = self._payload(res.text)
            if payload is None:
                message = '签到失败，签到接口返回非 JSON 响应'
                break
            if payload.get("success") is True:
                logger.info(f"{site} 签到成功")
                return True, '签到成功'
            reason = str(payload.get("message") or "")
            if reason == "date_unmatch":
                # 重复签到
                logger.warning(f"{site} 重复成功")
                return True, '今日已签到'
            if reason == "invalid_imagehash":
                # 验证码错误
                message = '签到失败：验证码错误'
                if round_no < MAX_SUBMITS:
                    logger.info(f"{site} 验证码错误，重新获取验证码（第 {round_no + 1} 轮）")
                continue
            message = f'签到失败，签到接口返回：{reason or "未返回成功状态"}'
            break

        logger.error(f"{site} {message}")
        return False, message

    @staticmethod
    def _payload(text: str) -> Optional[dict]:
        """解析接口 JSON，非对象响应按无效处理。"""
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _response_summary(text: str) -> str:
        """压缩接口响应，给失败原因保留可读片段。"""
        return re.sub(r"\s+", " ", str(text or "")).strip()[:60]

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

    def _new_image_hash(self, site, site_cookie, ua, proxy, timeout, deadline: float) -> Optional[str]:
        """取一张新验证码图的 imagehash，站点偶发失败或预算耗尽时返回空。"""
        for attempt in range(1, IMAGE_FETCH_ATTEMPTS + 1):
            if time.monotonic() > deadline:
                return None
            image_res = RequestUtils(cookies=site_cookie,
                                     ua=ua,
                                     content_type='application/x-www-form-urlencoded; charset=UTF-8',
                                     referer="https://hdsky.me/index.php",
                                     accept_type="*/*",
                                     proxies=settings.PROXY if proxy else None,
                                     timeout=self._request_timeout(timeout, deadline)
                                     ).post_res(url='https://hdsky.me/image_code_ajax.php',
                                                data={'action': 'new'})
            if image_res is not None and image_res.status_code == 200:
                payload = self._payload(image_res.text)
                if payload and payload.get("success") is True and payload.get("code"):
                    return payload["code"]
            logger.debug(f"获取 {site} 验证码失败，正在进行重试，目前重试次数：{attempt}")
            if attempt < IMAGE_FETCH_ATTEMPTS:
                time.sleep(1)
        return None

    def _captcha_text(self, site, image_url, site_cookie, ua, limit, deadline: float) -> Tuple[str, int]:
        """同一张图最多识别 limit 次，只接受六位结果，返回结果与实际识别次数。"""
        used = 0
        for index in range(1, max(limit, 0) + 1):
            if time.monotonic() > deadline:
                break
            used = index
            ocr_result = OcrHelper().get_captcha_text(image_url=image_url,
                                                      cookie=site_cookie,
                                                      ua=ua)
            logger.debug(f"OCR识别 {site} 验证码：{ocr_result}")
            if ocr_result and len(str(ocr_result)) == CAPTCHA_LENGTH:
                logger.info(f"OCR识别 {site} 验证码成功：{ocr_result}")
                return str(ocr_result), index
            logger.debug(f"OCR识别 {site} 验证码失败，正在进行重试，目前重试次数：{index}")
            if index < limit:
                time.sleep(1)
        return '', used
