import hashlib
import json
import time
from typing import Optional, Tuple, Union

from app.log import logger
from app.utils.http import RequestUtils


class IyuuHelper(object):
    """
    适配新版本 IYUU 开发版，并将上游异常响应转换为可处理的错误信息。
    """
    _version = "8.2.0"
    _api_base = "https://2025.iyuu.cn"
    _sites = {}
    _token = None
    _sid_sha1 = None
    # 接口失败后的冷却窗口（秒），避免一次失败在同一轮的多批请求上连锁重试
    _error_cooldown = 300

    def __init__(self, token: str):
        """初始化 IYUU 请求客户端并保存访问令牌。"""
        self._token = token
        self._sites_error = None
        self._sites_failed_at = 0.0
        self._sid_sha1_error = None
        self._sid_sha1_failed_at = 0.0
        self._sid_sha1_code = None
        # None 表示尚未设置，空列表表示本机确实没有可上报的站点
        self._report_sids = None
        if self._token:
            self.init_config()

    def init_config(self):
        """保留 IYUU 配置初始化钩子，当前无需额外配置。"""
        pass

    def __request_iyuu(self, url: str, method: str = "get",
                       params: dict = None) -> Tuple[Optional[dict], str, Optional[Union[int, str]]]:
        """
        向 IYUU API 发送请求，并把无效 JSON 降级为可读的错误信息。
        第三项为 HTTP 状态码或业务 code，供调用方区分凭证失效与临时故障。
        """
        if method == "post":
            ret = RequestUtils(
                accept_type="application/json",
                headers={'token': self._token}
            ).post_res(f'{self._api_base + url}', json=params)
        else:
            ret = RequestUtils(
                accept_type="application/json",
                headers={'token': self._token}
            ).get_res(f'{self._api_base + url}', params=params)
        if ret:
            try:
                result = ret.json()
            except ValueError as err:
                text_preview = (ret.text or "")[:200].replace("\n", "\\n")
                return None, (
                    f"请求IYUU失败，响应解析失败：{type(err).__name__} "
                    f"状态码：{ret.status_code}，响应前缀：{text_preview}"
                ), ret.status_code if ret.status_code >= 400 else -1
            if result.get('code') == 0:
                # 0 表示接口正常，data 为空时由调用方按“确实没有可辅种”处理
                return result.get('data'), "", 0
            else:
                code = result.get("code")
                try:
                    code = int(code)
                except (TypeError, ValueError):
                    # 无法识别的业务码按未知错误处理，避免被当成“没有可辅种”
                    code = ret.status_code if ret.status_code >= 400 else -1
                return None, f'请求IYUU失败，状态码：{code}，返回信息：{result.get("msg")}', code
        elif ret is not None:
            return None, f"请求IYUU失败，状态码：{ret.status_code}，错误原因：{ret.reason}", ret.status_code
        else:
            return None, "请求IYUU失败，未获取到返回信息", None

    def __get_site(self, sid) -> Optional[dict]:
        """
        按站点 ID 取 IYUU 站点配置，兼容整数与字符串 ID

        :param sid: IYUU 站点 ID
        :return: 站点配置，未维护时返回 None
        """
        if not sid:
            return None
        if not self._sites:
            self._sites = self.__get_sites()
        return self._sites.get(sid) or self._sites.get(str(sid)) or None

    def get_torrent_url(self, sid: str) -> Tuple[Optional[str], Optional[str]]:
        """根据站点 ID 返回站点基础地址和种子下载页地址。"""
        site = self.__get_site(sid)
        if not site:
            return None, None
        return site.get('base_url'), site.get('download_page')

    def get_site_pages(self, sid) -> dict:
        """
        返回站点基础地址、种子下载页与详情页模板，详情页缺失时由调用方兜底

        :param sid: IYUU 站点 ID
        :return: base_url / download_page / details_page
        """
        site = self.__get_site(sid) or {}
        return {"base_url": site.get("base_url"),
                "download_page": site.get("download_page"),
                "details_page": site.get("details_page")}

    def get_all_sites(self) -> dict:
        """返回 IYUU 站点清单，按站点 ID 索引"""
        if not self._sites:
            self._sites = self.__get_sites()
        return self._sites

    def set_report_sids(self, sids: list):
        """限定上报的站点 ID，只包含本机已配置、实际会参与辅种的站点"""
        self._report_sids = [sid for sid in (sids or []) if sid]

    def get_site_info(self, sid) -> Optional[dict]:
        """
        返回 IYUU 站点标识、昵称、站点地址与协议声明，用于站点匹配与拼装 API 地址

        :param sid: IYUU 站点 ID
        :return: 站点信息，未维护时返回 None
        """
        site = self.__get_site(sid)
        if not site:
            return None
        return {"site": site.get("site"), "nickname": site.get("nickname"),
                "base_url": site.get("base_url"), "is_https": site.get("is_https")}

    def reset_sites(self):
        """清空站点清单缓存，下次取用时重新向 IYUU 拉取"""
        self._sites = {}
        self._sid_sha1 = None
        self._sites_error = None
        self._sites_failed_at = 0.0
        self._sid_sha1_error = None
        self._sid_sha1_failed_at = 0.0
        self._sid_sha1_code = None
        self._report_sids = None

    def __get_sites(self) -> dict:
        """
        返回支持辅种的全部站点
        :return: 站点列表、错误信息
        """
        # 冷却窗口内不再请求，避免清单失败后每个种子重打一次
        if self._sites_error and time.time() - self._sites_failed_at < self._error_cooldown:
            return {}
        result, msg, _ = self.__request_iyuu(url='/reseed/sites/index')
        if result:
            self._sites_error = None
            self._sites_failed_at = 0.0
            return {site.get('id'): site for site in result.get('sites') or []}
        self._sites_error = msg or "未返回站点清单"
        self._sites_failed_at = time.time()
        logger.warning(f"获取IYUU站点列表失败：{self._sites_error}")
        return {}

    def __report_existing(self) -> Optional[str]:
        """
        汇报辅种的站点
        只上报本机已配置的站点；清单缺失或本机无可上报站点时不发请求。
        :return:
        """
        if not self._sites:
            self._sites = self.__get_sites()
        if not self._sites:
            # 保留站点清单的真实失败原因，排障时才不会被“站点哈希值”盖掉
            self._sid_sha1_error = self._sites_error or "未获取到站点清单"
            self._sid_sha1_code = None
            return None
        if self._report_sids is not None and not self._report_sids:
            self._sid_sha1_error = "本机没有已配置且可匹配的辅种站点"
            # 单独标记，避免被插件层当成 IYUU 接口故障
            self._sid_sha1_code = "no_sites"
            return None
        if self._sid_sha1_error and time.time() - self._sid_sha1_failed_at < self._error_cooldown:
            return None
        sid_list = self._report_sids if self._report_sids is not None else list(self._sites.keys())
        result, msg, code = self.__request_iyuu(url='/reseed/sites/reportExisting',
                                                method='post',
                                                params={'sid_list': sid_list})
        if result:
            self._sid_sha1_error = None
            self._sid_sha1_failed_at = 0.0
            self._sid_sha1_code = None
            return result.get('sid_sha1')
        self._sid_sha1_error = msg or "未返回站点哈希"
        self._sid_sha1_code = code
        self._sid_sha1_failed_at = time.time()
        logger.warning(f"汇报辅种站点失败：{self._sid_sha1_error}")
        return None

    def __reseed_index(self, json_data: str, sha1: str) -> Tuple[Optional[dict], str, Optional[Union[int, str]]]:
        return self.__request_iyuu(url='/reseed/index/index', method='post', params={
            'hash': json_data,
            'sha1': sha1,
            'sid_sha1': self._sid_sha1,
            'timestamp': int(time.time()),
            'version': self._version
        })

    def get_seed_info(self, info_hashs: list) -> Tuple[Optional[dict], str, Optional[Union[int, str]]]:
        """
        返回info_hash对应的站点id、种子id
        :param info_hashs:
        :return:
        """
        if not self._sid_sha1:
            self._sid_sha1 = self.__report_existing()
        if not self._sid_sha1:
            # 站点哈希拿不到时继续请求只会白打，交由调用方中断本轮
            return None, self._sid_sha1_error or "未获取到站点哈希值", self._sid_sha1_code
        info_hashs.sort()
        json_data = json.dumps(info_hashs, separators=(',', ':'), ensure_ascii=False)
        sha1 = self.get_sha1(json_data)
        result, msg, code = self.__reseed_index(json_data, sha1)
        if msg and "站点哈希值 require" in msg:
            self._sid_sha1 = self.__report_existing()
            if not self._sid_sha1:
                return None, self._sid_sha1_error or "未获取到站点哈希值", self._sid_sha1_code
            result, msg, code = self.__reseed_index(json_data, sha1)
        return result, msg, code

    @staticmethod
    def get_sha1(json_str: str) -> str:
        """计算 IYUU 请求参数 JSON 字符串的 SHA-1 摘要。"""
        return hashlib.sha1(json_str.encode('utf-8')).hexdigest()
