# -*- coding: utf-8 -*-
import re
from typing import Optional

from lxml import etree

from app.log import logger
from app.plugins.contractcheck.siteuserinfo import ISiteUserInfo, SITE_BASE_ORDER, SiteSchema
from app.utils.string import StringUtils


class NexusPhpSiteUserInfo(ISiteUserInfo):
    schema = SiteSchema.NexusPhp
    order = SITE_BASE_ORDER * 2

    @classmethod
    def match(cls, html_text: str) -> bool:
        """
        默认使用NexusPhp解析
        :param html_text:
        :return:
        """
        return True

    def _parse_site_page(self, html_text: str):
        html_text = self._prepare_html_text(html_text)

        user_detail = re.search(r"userdetails.php\?id=(\d+)", html_text)
        if user_detail and user_detail.group().strip():
            self._user_detail_page = user_detail.group().strip().lstrip('/')
            self.userid = user_detail.group(1)
            self._torrent_seeding_page = f"getusertorrentlistajax.php?userid={self.userid}&type=seeding"
        else:
            user_detail = re.search(r"(userdetails)", html_text)
            if user_detail and user_detail.group().strip():
                self._user_detail_page = user_detail.group().strip().lstrip('/')
                self.userid = None
                self._torrent_seeding_page = None

    def _parse_user_torrent_seeding_info(self, html_text: str, multi_page: bool = False) -> Optional[str]:
        """
        做种相关信息
        :param html_text:
        :param multi_page: 是否多页数据
        :return: 下页地址
        """
        html = etree.HTML(str(html_text).replace(r'\/', '/'))
        if not html:
            return None

        # 首页存在扩展链接，使用扩展链接
        seeding_url_text = html.xpath('//a[contains(@href,"torrents.php") '
                                      'and contains(@href,"seeding")]/@href')
        if multi_page is False and seeding_url_text and seeding_url_text[0].strip():
            self._torrent_seeding_page = seeding_url_text[0].strip()
            return self._torrent_seeding_page

        title_col = 2
        size_col = 3
        seeders_col = 4
        # 搜索size列
        size_col_xpath = '//tr[position()=1]/' \
                         'td[(img[@class="size"] and img[@alt="size"])' \
                         ' or (text() = "大小")' \
                         ' or (a/img[@class="size" and @alt="size"])]'
        if html.xpath(size_col_xpath):
            size_col = len(html.xpath(f'{size_col_xpath}/preceding-sibling::td')) + 1
        # 搜索title列
        title_col_xpath = '//tr[position()=1]/' \
                           'td[(text() = "标题")]'
        if html.xpath(title_col_xpath):
            title_col = len(html.xpath(f'{title_col_xpath}/preceding-sibling::td')) + 1

        page_torrent_info = []
        # 如果 table class="torrents"，则增加table[@class="torrents"]
        table_class = '//table[@class="torrents"]' if html.xpath('//table[@class="torrents"]') else ''
        seeding_sizes = html.xpath(f'{table_class}//tr[position()>1]/td[{size_col}]')
        seeding_torrents = html.xpath(f'{table_class}//tr[position()>1]/td[{title_col}]/a/@title')
        if seeding_sizes:
            for i in range(0, len(seeding_sizes)):
                size = StringUtils.num_filesize(seeding_sizes[i].xpath("string(.)").strip())
                page_torrent_info.append([seeding_torrents[i], size])

        self.torrent_title_size.extend(page_torrent_info)

        # 是否存在下页数据
        next_page = None
        next_page_text = html.xpath('//a[contains(.//text(), "下一页") or contains(.//text(), "下一頁")]/@href')
        if next_page_text:
            next_page = next_page_text[-1].strip()
            # fix up page url
            if self.userid not in next_page:
                next_page = f'{next_page}&userid={self.userid}&type=seeding'

        return next_page