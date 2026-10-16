# -*- coding: utf-8 -*-
"""站点级微调适配器注册表。

同架构（NexusPHP 等）但用户详情页模板有细微差异的站点，在此注册一个小适配器，
只覆写差异钩子（client_table_locator / parse_torrent_rows / promotion_tags /
leeching_url 等），基类能力自动继承。示例：

    # sites/hdsky.py
    from ..nexusphp import NexusPhpAdapter

    class HdskyAdapter(NexusPhpAdapter):
        \"\"\"HDSky 模板差异：客户端表格位于独立 div。\"\"\"

        def client_table_locator(self, html):
            ...  # 仅覆写该站差异部分

然后在本文件注册：

    from .hdsky import HdskyAdapter
    SITE_ADAPTERS["hdsky.me"] = HdskyAdapter

注意：插件包内一律使用相对导入（安装目录名为插件类名，绝对路径大小写不匹配）。
"""

from typing import Dict, Type

from ..base import SiteAdapter

# 站点域名（小写）→ 站点适配器
SITE_ADAPTERS: Dict[str, Type[SiteAdapter]] = {}
