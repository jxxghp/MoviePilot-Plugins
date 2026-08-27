from typing import Tuple

from ruamel.yaml import CommentedMap

from app.log import logger
from app.core.config import settings
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.plugins.autosignin.sites import _ISiteSigninHandler


class RousiPro(_ISiteSigninHandler):
    """
    使用 PeerGo 个人 API Key 执行 Rousi Pro 签到和模拟登录。

    签到需要 attendance:claim 权限，模拟登录需要 profile:read 权限；
    旧 Authorization Token 仅作为存量配置的兼容回退。
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "rousi.pro"

    @staticmethod
    def _bearer_auth(value: str) -> str:
        """
        将个人 API Key 或兼容 Authorization Token 规范化为 Bearer 认证值。
        """
        value = str(value or "").strip()
        return value if value.lower().startswith("bearer ") else f"Bearer {value}"

    @staticmethod
    def _response_code(res) -> int:
        """
        安全读取 Rousi Pro JSON 响应中的业务状态码。
        """
        if res is None:
            return -1
        try:
            payload = res.json() or {}
        except (TypeError, ValueError):
            return -1
        return payload.get("code", -1) if isinstance(payload, dict) else -1

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
        apikey = str(site_info.get("apikey") or "").strip()
        token = str(site_info.get("token") or "").strip()
        timeout = site_info.get("timeout")
        if not apikey and not token:
            logger.error(f"{site} 签到失败，缺少个人 API Key 或兼容 Authorization 信息")
            return False, "签到失败，缺少个人 API Key 或兼容 Authorization 信息"

        base_headers = {
            "Content-Type": "application/json",
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
        }
        body = {
            "mode": "fixed"
        }
        request_options = {
            "timeout": timeout,
            "proxies": settings.PROXY if site_info.get("proxy") else None,
        }
        res = None
        auth_type = "个人 API Key"

        if apikey:
            res = RequestUtils(
                headers={**base_headers, "api-token": apikey},
                **request_options,
            ).post_res(
                url="https://rousi.pro/api/points/attendance",
                json=body
            )
            code = self._response_code(res)
            if res is not None and res.status_code == 200 and code == 0:
                logger.info(f"{site} 签到成功")
                return True, "签到成功"
            if res is not None and res.status_code == 400 and code == 1:
                logger.info(f"{site} 今日已签到")
                return True, "今日已签到"
            if token:
                logger.info(f"{site} 个人 API Key 签到认证未成功，回退 Authorization")

        if token:
            auth_type = "Authorization"
            res = RequestUtils(
                headers={**base_headers, "Authorization": self._bearer_auth(token)},
                **request_options,
            ).post_res(
                url="https://rousi.pro/api/points/attendance",
                json=body
            )

        code = self._response_code(res)
        if res is not None and res.status_code == 200 and code == 0:
            logger.info(f"{site} 签到成功")
            return True, "签到成功"
        elif res is not None and res.status_code == 400 and code == 1:
            logger.info(f"{site} 今日已签到")
            return True, "今日已签到"
        elif res is not None and res.status_code in (401, 403):
            logger.error(f"{site} 签到失败，{auth_type} 已失效或权限不足")
            return False, f"签到失败，{auth_type} 已失效或权限不足"
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
        apikey = str(site_info.get("apikey") or "").strip()
        token = str(site_info.get("token") or "").strip()
        timeout = site_info.get("timeout")
        if not apikey and not token:
            logger.error(f"{site} 模拟登录失败，缺少个人 API Key 或兼容 Authorization 信息")
            return False, "模拟登录失败，缺少个人 API Key 或兼容 Authorization 信息"

        base_headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
        }
        request_options = {
            "timeout": timeout,
            "proxies": settings.PROXY if site_info.get("proxy") else None,
        }
        res = None
        auth_type = "个人 API Key"

        if apikey:
            res = RequestUtils(
                headers={**base_headers, "Authorization": self._bearer_auth(apikey)},
                **request_options,
            ).get_res(url="https://rousi.pro/api/v1/profile")
            if res is not None and res.status_code == 200 and self._response_code(res) == 0:
                logger.info(f"{site} 模拟登录成功")
                return True, "模拟登录成功"
            if token:
                logger.info(f"{site} 个人 API Key 模拟登录认证未成功，回退 Authorization")

        if token:
            auth_type = "Authorization"
            res = RequestUtils(
                headers={**base_headers, "Authorization": self._bearer_auth(token)},
                **request_options,
            ).get_res(url="https://rousi.pro/api/points/attendance/stats")

        if res is not None and res.status_code == 200 and self._response_code(res) == 0:
            logger.info(f"{site} 模拟登录成功")
            return True, "模拟登录成功"
        elif res is not None and res.status_code in (401, 403):
            logger.error(f"{site} 模拟登录失败，{auth_type} 已失效或权限不足")
            return False, f"模拟登录失败，{auth_type} 已失效或权限不足"
        elif res is not None:
            logger.error(f"{site} 模拟登录失败，状态码：{res.status_code}")
            return False, f"模拟登录失败，状态码：{res.status_code}"
        else:
            logger.error(f"{site} 模拟登录失败，无法访问网站")
            return False, "模拟登录失败，无法访问网站"
