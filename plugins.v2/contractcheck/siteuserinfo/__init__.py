# -*- coding: utf-8 -*-
import json
import re
from abc import ABCMeta, abstractmethod
from enum import Enum
from typing import Optional
from urllib.parse import urljoin, urlsplit

from requests import Session
from lxml import etree

from app.core.config import settings
from app.helper.cloudflare import under_challenge
from app.log import logger
from app.utils.http import RequestUtils
from app.utils.site import SiteUtils

SITE_BASE_ORDER = 1000


# 站点框架
class SiteSchema(Enum):
    DiscuzX = "Discuz!"
    Gazelle = "Gazelle"
    Ipt = "IPTorrents"
    NexusPhp = "NexusPhp"
    NexusProject = "NexusProject"
    NexusRabbit = "NexusRabbit"
    NexusHhanclub = "NexusHhanclub"
    SmallHorse = "Small Horse"
    Unit3d = "Unit3d"
    TorrentLeech = "TorrentLeech"
    FileList = "FileList"
    TNode = "TNode"
    NexusTtg = "NexusTtg"


class ISiteUserInfo(metaclass=ABCMeta):
    # 站点模版
    schema = SiteSchema.NexusPhp
    # 站点解析时判断顺序，值越小越先解析
    order = SITE_BASE_ORDER

    def __init__(self, site_name: str,
                 url: str,
                 site_cookie: str,
                 index_html: str,
                 session: Session = None,
                 ua: str = None,
                 emulate: bool = False,
                 proxy: bool = None):
        super().__init__()
        # 站点信息
        self.site_name = None
        self.site_url = None
        # 用户信息
        self.userid = None

        # 种子标题，种子大小
        self.torrent_title_size = []
        # 种子总大小 (数量，大小)
        self.total_seeding_size = [0, 0]
        # 官种总大小 (数量，大小)
        self.official_seeding_size = [0, 0]

        # 站点官组
        self.official_team = {
            "观众": ["Audies", "ADE", "ADWeb", "ADAudio", "ADeBook", "ADMusic"],
            "UBits": ["UBits"],
            "听听歌": ["TTG", "WiKi", "DoA", "NGB", "ARiN"],
            "馒头": ["MTeam", "MTeamTV"],
            "朋友": ["FRDS"],
            "猪猪": ["PigoHD","PigoWeb","PigoNF"]
        }

        # 错误信息
        self.err_msg = None
        # 内部数据
        self._base_url = None
        self._site_cookie = None
        self._index_html = None
        self._addition_headers = None

        # 站点页面
        self._user_detail_page = "userdetails.php?id="
        self._torrent_seeding_page = "getusertorrentlistajax.php?userid="
        self._torrent_seeding_params = None
        self._torrent_seeding_headers = None

        split_url = urlsplit(url)
        self.site_name = site_name
        self.site_url = url
        self._base_url = f"{split_url.scheme}://{split_url.netloc}"
        self._site_cookie = site_cookie
        self._index_html = index_html
        self._session = session if session else None
        self._ua = ua

        self._emulate = emulate
        self._proxy = proxy

    def site_schema(self) -> SiteSchema:
        """
        站点解析模型
        :return: 站点解析模型
        """
        return self.schema

    @classmethod
    def match(cls, html_text: str) -> bool:
        """
        是否匹配当前解析模型
        :param html_text: 站点首页html
        :return: 是否匹配
        """
        pass

    # 用于契约检查插件获取保种信息
    def parse_official_seeding_info(self):
        """
        解析站点保种信息
        :return:
        """
        if not self._parse_logged_in(self._index_html):
            return
        self._parse_site_page(self._index_html)

        # 某些站点已统计官种，直接解析
        if self.site_name == "憨憨":
            seeding_size = self._get_page_content(
                urljoin(
                    self._base_url,
                    f"getusertorrentlistajax.php?userid={self.userid}&type=size",
                )
            )
            if seeding_size:
                seeding_size = json.loads(seeding_size)
                self.total_seeding_size = (
                    seeding_size.get("total_count", 0),
                    self._size_to_byte(seeding_size.get("total_size", 0)),
                )
                self.official_seeding_size = (
                    seeding_size.get("total_official_count", 0),
                    self._size_to_byte(seeding_size.get("total_official_size", 0)),
                )
            else:
                logger.error(f"获取官种信息失败")
        elif self.site_name == "春天":
            html_text = self._get_page_content(
                urljoin(
                    self._base_url,
                    f"getusertorrentlistajax.php?userid={self.userid}&type=seeding",
                )
            )
            html = etree.HTML(html_text)
            if not html:
                return
            total_num = int(html.xpath('//body[1]/b[1]/text()')[0])
            total_size = html.xpath('//body[1]/b[2]/text()')
            official_num = int(html.xpath('//body[1]/b[3]/text()')[0])
            official_size = html.xpath('//body[1]/b[4]/text()')
            self.total_seeding_size = (total_num if total_num else 0, self._size_to_byte(total_size[0]) if total_size else 0)
            self.official_seeding_size = (official_num if official_num else 0, self._size_to_byte(official_size[0]) if official_size else 0)
        else:
            self._parse_seeding_pages()
            if len(self.torrent_title_size) == 0:
                logger.error(f"{self.site_name}:获取种子信息失败")
                return
            total_num = 0
            total_size = 0
            official_num = 0
            official_size = 0
            for torrent in self.torrent_title_size:
                self.total_seeding_size[0] += 1
                self.total_seeding_size[1] += torrent[1]
                if any(team in torrent[0] for team in self.official_team.get(self.site_name, [])):
                    self.official_seeding_size[0] += 1
                    self.official_seeding_size[1] += torrent[1]

        logger.info(f"{self.site_name} 官种信息 {self.official_seeding_size} 总种信息 {self.total_seeding_size}")

    # 将各种格式大小统一转为Byte
    def _size_to_byte(self, size: str) -> float:
        if str is None:
            return 0
        if size.endswith("TB"):
            return float(size[:-2]) * 1024 * 1024 * 1024 * 1024
        if size.endswith("GB"):
            return float(size[:-2]) * 1024 * 1024 * 1024
        elif size.endswith("MB"):
            return float(size[:-2]) * 1024 * 1024
        elif size.endswith("KB"):
            return float(size[:-2]) * 1024
        elif size.endswith("B"):
            return float(size[:-1])
        else:
            return 0

    def _parse_seeding_pages(self):
        if self._torrent_seeding_page:
            # 处理特殊站点
            if self.site_name == "听听歌":
                self._torrent_seeding_page = self._user_detail_page
            elif self.site_name == "馒头":
                self._torrent_seeding_page = f"getusertorrentlist.php?userid={self.userid}&type=seeding"
            elif self.site_name == "观众":
                self._torrent_seeding_headers = {"Referer": urljoin(self._base_url, self._user_detail_page)}
                logger.info(f" {self.site_name} {self._torrent_seeding_headers}")

            # 第一页
            next_page = self._parse_user_torrent_seeding_info(
                self._get_page_content(urljoin(self._base_url, self._torrent_seeding_page),
                                       self._torrent_seeding_params,
                                       self._torrent_seeding_headers))

            # 其他页处理
            while next_page:
                next_page = self._parse_user_torrent_seeding_info(
                    self._get_page_content(urljoin(urljoin(self._base_url, self._torrent_seeding_page), next_page),
                                           self._torrent_seeding_params,
                                           self._torrent_seeding_headers),
                    multi_page=True)

    @staticmethod
    def _prepare_html_text(html_text):
        """
        处理掉HTML中的干扰部分
        """
        return re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_text))

    def _get_page_content(self, url: str, params: dict = None, headers: dict = None):
        """
        :param url: 网页地址
        :param params: post参数
        :param headers: 额外的请求头
        :return:
        """
        req_headers = None
        proxies = settings.PROXY if self._proxy else None
        if self._ua or headers or self._addition_headers:
            req_headers = {}
            if headers:
                req_headers.update(headers)

            req_headers.update({
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": f"{self._ua}"
            })

            if self._addition_headers:
                req_headers.update(self._addition_headers)

        if params:
            res = RequestUtils(cookies=self._site_cookie,
                               session=self._session,
                               timeout=60,
                               proxies=proxies,
                               headers=req_headers).post_res(url=url, data=params)
        else:
            res = RequestUtils(cookies=self._site_cookie,
                               session=self._session,
                               timeout=60,
                               proxies=proxies,
                               headers=req_headers).get_res(url=url)
        if res is not None and res.status_code in (200, 500, 403):
            # 如果cloudflare 有防护，尝试使用浏览器仿真
            if under_challenge(res.text):
                logger.warn(
                    f"{self.site_name} 检测到Cloudflare，请更新Cookie和UA")
                return ""
            if re.search(r"charset=\"?utf-8\"?", res.text, re.IGNORECASE):
                res.encoding = "utf-8"
            else:
                res.encoding = res.apparent_encoding
            return res.text

        return ""

    @abstractmethod
    def _parse_site_page(self, html_text: str):
        """
        解析站点相关信息页面
        :param html_text:
        :return:
        """
        pass

    def _parse_logged_in(self, html_text):
        """
        解析用户是否已经登陆
        :param html_text:
        :return: True/False
        """
        logged_in = SiteUtils.is_logged_in(html_text)
        if not logged_in:
            self.err_msg = "未检测到已登陆，请检查cookies是否过期"
            logger.warn(f"{self.site_name} 未登录，跳过后续操作")

        return logged_in

    @abstractmethod
    def _parse_user_torrent_seeding_info(self, html_text: str, multi_page: bool = False) -> Optional[str]:
        """
        解析用户的做种相关信息
        :param html_text:
        :param multi_page: 是否多页数据
        :return: 下页地址
        """
        pass

    def to_dict(self):
        """
        转化为字典
        """
        attributes = [
            attr for attr in dir(self)
            if not callable(getattr(self, attr)) and not attr.startswith("_")
        ]
        return {
            attr: getattr(self, attr).value
            if isinstance(getattr(self, attr), SiteSchema)
            else getattr(self, attr) for attr in attributes
        }
