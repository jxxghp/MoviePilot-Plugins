import hashlib
from typing import Optional, Tuple, List

from app.utils.http import RequestUtils


class IyuuHelper(object):
    _version = "2.0.0"
    _api_base = "http://api.iyuu.cn/%s"
    _sites = {}
    _token = None

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
        if params:
            if not params.get("sign"):
                params.update({"sign": self._token})
            if not params.get("version"):
                params.update({"version": self._version})
        else:
            params = {"sign": self._token, "version": self._version}
        # 开始请求
        if method == "get":
            ret = RequestUtils(
                accept_type="application/json"
            ).get_res(f"{url}", params=params)
        else:
            ret = RequestUtils(
                accept_type="application/json"
            ).post_res(f"{url}", data=params)
        if ret:
            result = ret.json()
            if result.get('ret') == 200:
                return result.get('data'), ""
            else:
                return None, f"请求IYUU失败，状态码：{result.get('ret')}，返回信息：{result.get('msg')}"
        elif ret is not None:
            return None, f"请求IYUU失败，状态码：{ret.status_code}，错误原因：{ret.reason}"
        else:
            return None, f"请求IYUU失败，未获取到返回信息"

    @staticmethod
    def get_sha1(json_str: str) -> str:
        return hashlib.sha1(json_str.encode('utf-8')).hexdigest()

    def get_auth_sites(self) -> List[dict]:
        """
        返回支持鉴权的站点列表
        [
            {
                "id": 2,
                "site": "pthome",
                "bind_check": "passkey,uid"
            }
        ]
        """
        result, msg = self.__request_iyuu(url=self._api_base % 'App.Api.GetRecommendSites')
        if result:
            return result.get('recommend') or []
        else:
            print(msg)
            return []

    def bind_site(self, site: str, passkey: str, uid: str):
        """
        绑定站点
        :param site: 站点名称
        :param passkey: passkey
        :param uid: 用户id
        :return: 状态码、错误信息
        """
        result, msg = self.__request_iyuu(url=self._api_base % 'App.Api.Bind',
                                          method="get",
                                          params={
                                              "token": self._token,
                                              "site": site,
                                              "passkey": self.get_sha1(passkey),
                                              "id": uid
                                          })
        return result, msg
