# -*- coding: utf-8 -*-
import re

from lxml import etree
from typing import Optional

from app.plugins.contractcheck.siteuserinfo import SITE_BASE_ORDER, SiteSchema
from app.plugins.contractcheck.siteuserinfo.nexus_php import NexusPhpSiteUserInfo
from app.utils.string import StringUtils


class NexusTtgSiteUserInfo(NexusPhpSiteUserInfo):
    schema = SiteSchema.NexusTtg
    order = SITE_BASE_ORDER + 20

    @classmethod
    def match(cls, html_text: str) -> bool:
        return 'totheglory.im' in html_text
        
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

            title_col = 2
            size_col = 4

            page_torrent_info = []

            table_class = '//div[@id="ka2"]/table'
            seeding_sizes = html.xpath(f'{table_class}//tr[position()>1]/td[{size_col}]')
            seeding_torrents = html.xpath(f'{table_class}//tr[position()>1]/td[{title_col}]/a/b/text()')
            if seeding_sizes:
                for i in range(0, len(seeding_sizes)):
                    size = StringUtils.num_filesize(seeding_sizes[i].xpath("string(.)").strip())
                    page_torrent_info.append([seeding_torrents[i], size])

            self.torrent_title_size.extend(page_torrent_info)

            # 不存在下页数据
            return False