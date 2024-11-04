import hashlib
import json
import time
from typing import Tuple, Optional

from app.utils.http import RequestUtils


class IyuuHelper(object):
    """
    适配新版本IYUU开发版
    """
    _version = "8.2.0"
    _api_base = "https://2025.iyuu.cn"
    _sites = {}
    _token = None
    _sid_sha1 = None

    def __init__(self, token: str):
        self._token = token
        if self._token:
            self.init_config()

    def init_config(self):
        pass

    def __request_iyuu(self, url: str, method: str = "get", params: dict = None) -> Tuple[Optional[dict], str]:
        """
        向IYUUApi发送请求
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
            result = ret.json()
            if result.get('code') == 0:
                return result.get('data'), ""
            else:
                return None, f'请求IYUU失败，状态码：{result.get("code")}，返回信息：{result.get("msg")}'
        elif ret is not None:
            return None, f"请求IYUU失败，状态码：{ret.status_code}，错误原因：{ret.reason}"
        else:
            return None, f"请求IYUU失败，未获取到返回信息"

    def get_torrent_url(self, sid: str) -> Tuple[Optional[str], Optional[str]]:
        if not sid:
            return None, None
        if not self._sites:
            self._sites = self.__get_sites()
        if not self._sites.get(sid):
            return None, None
        site = self._sites.get(sid)
        return site.get('base_url'), site.get('download_page')

    def __get_sites(self) -> dict:
        """
        返回支持辅种的全部站点
        :return: 站点列表、错误信息
        """
        result, msg = self.__request_iyuu(url='/reseed/sites/index')
        if result:
            ret_sites = {}
            sites = result.get('sites')
            for site in sites:
                ret_sites[site.get('id')] = site
            return ret_sites
        else:
            print(msg)
            return {}

    def __report_existing(self) -> Optional[str]:
        """
        汇报辅种的站点
        :return:
        """
        if not self._sites:
            self._sites = self.__get_sites()
        sid_list = list(self._sites.keys())
        result, msg = self.__request_iyuu(url='/reseed/sites/reportExisting',
                                          method='post',
                                          params={'sid_list': sid_list})
        if result:
            return result.get('sid_sha1')
        return None

    def get_seed_info(self, info_hashs: list) -> Tuple[Optional[dict], str]:
        """
        返回info_hash对应的站点id、种子id
        :param info_hashs:
        :return:
        """
        if not self._sid_sha1:
            self._sid_sha1 = self.__report_existing()
        info_hashs.sort()
        json_data = json.dumps(info_hashs, separators=(',', ':'), ensure_ascii=False)
        sha1 = self.get_sha1(json_data)
        result, msg = self.__request_iyuu(url='/reseed/index/index', method='post', params={
            'hash': json_data,
            'sha1': sha1,
            'sid_sha1': self._sid_sha1,
            'timestamp': int(time.time()),
            'version': self._version
        })
        return result, msg

    @staticmethod
    def get_sha1(json_str: str) -> str:
        return hashlib.sha1(json_str.encode('utf-8')).hexdigest()
