import asyncio
import base64
import ipaddress
import json
import socket
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Response

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.tobypasstrackers.dns_helper import DnsHelper
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class ToBypassTrackers(_PluginBase):
    # 插件名称
    plugin_name = "绕过Trackers"
    # 插件描述
    plugin_desc = "提供tracker服务器IP地址列表，帮助IPv6连接绕过OpenClash。"
    # 插件图标
    plugin_icon = "Clash_A.png"
    # 插件版本
    plugin_version = "1.4.3"
    # 插件作者
    plugin_author = "wumode"
    # 作者主页
    author_url = "https://github.com/wumode"
    # 插件配置项ID前缀
    plugin_config_prefix = "tobypasstrackers_"
    # 加载顺序
    plugin_order = 21
    # 可使用的用户级别
    auth_level = 2

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    # 开关
    _enabled: bool = False
    _cron: str = ""
    _notify = False
    _onlyonce: bool = False
    _custom_trackers: str = ""
    _exempted_domains: str = ""
    _bypassed_sites: list = []
    _china_ip_route: bool = True
    _china_ipv6_route: bool = True
    _bypass_ipv4: bool = True
    _bypass_ipv6: bool = True
    _dns_input: str = ""
    ipv6_txt: str = ""
    ipv4_txt: str = ""
    trackers: Dict[str, List[str]] = {}

    def init_plugin(self, config: dict = None):

        self.stop_service()

        self.trackers = {}
        self.ipv6_txt = self.get_data("ipv6_txt") if self.get_data("ipv6_txt") else ""
        self.ipv4_txt = self.get_data("ipv4_txt") if self.get_data("ipv4_txt") else ""
        try:
            site_file = settings.ROOT_PATH/'app'/'plugins'/'tobypasstrackers'/'sites'/'trackers'
            with open(site_file, "r", encoding="utf-8") as f:
                base64_str = f.read()
                self.trackers = json.loads(base64.b64decode(base64_str).decode("utf-8"))
        except Exception as e:
            logger.error(f"插件加载错误：{e}")
        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify")
            self._custom_trackers = config.get("custom_trackers")
            self._exempted_domains = config.get("exempted_domains")
            self._bypassed_sites = config.get("bypassed_sites") or []
            self._bypass_ipv4 = config.get("bypass_ipv4")
            self._bypass_ipv6 = config.get("bypass_ipv6")
            self._dns_input = config.get("dns_input")
            self._china_ipv6_route = config.get("china_ipv6_route")
            self._china_ip_route = config.get("china_ip_route")
            # 过滤掉已删除的站点
            all_sites = [site.id for site in SiteOper().list_order_by_pri()]
            self._bypassed_sites = [site_id for site_id in all_sites if site_id in self._bypassed_sites]
            self.__update_config()
        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if self._onlyonce:
                logger.info(f"立即运行一次")
                self._scheduler.add_job(self.update_ips, "date",
                                        run_date=datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                                        )
                self._onlyonce = False
            self.__update_config()
            self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def __update_config(self):
        # 保存配置
        self.update_config(
            {
                "enabled": self._enabled,
                "cron": self._cron,
                "onlyonce": self._onlyonce,
                "bypassed_sites": self._bypassed_sites,
                "custom_trackers": self._custom_trackers,
                "exempted_domains": self._exempted_domains,
                "notify": self._notify,
                "dns_input": self._dns_input,
                "china_ip_route": self._china_ip_route,
                "china_ipv6_route": self._china_ipv6_route,
                "bypass_ipv6": self._bypass_ipv6,
                "bypass_ipv4": self._bypass_ipv4
            }
        )

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/refresh_tracker_ips",
            "event": EventType.PluginAction,
            "desc": "更新 Tracker IP 列表",
            "data": {
                "action": "refresh_tracker_ips"
            }
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        return [{
            "path": "/bypassed_ips",
            "endpoint": self.bypassed_ips,
            "methods": ["GET"],
            "summary": "绕过的IP",
            "description": "绕过Clash核心的IP地址列表",
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        site_options = ([{"title": site.name, "value": site.id}
                         for site in SiteOper().list_order_by_pri()])
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'bypass_ipv4',
                                            'label': '绕过 IPv4 Tracker',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'bypass_ipv6',
                                            'label': '绕过 IPv6 Tracker',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'china_ip_route',
                                            'label': '合并中国大陆IPv4列表',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'china_ipv6_route',
                                            'label': '合并中国大陆IPv6列表',
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '0 4 * * *'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'dns_input',
                                            'label': 'DNS 服务器',
                                            'placeholder': '留空则使用本地DNS'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'bypassed_sites',
                                            'label': '绕过站点',
                                            'items': site_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'custom_trackers',
                                            'label': '自定义Tracker服务器',
                                            'rows': 3,
                                            'placeholder': '每行一个域名或IP'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'exempted_domains',
                                            'label': '排除的域名和IP',
                                            'rows': 3,
                                            'placeholder': '每行一个域名或IP'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': 'DNS 服务器示例 (仅填一个): '
                                                    '「94.140.14.140」、'
                                                    '「94.140.14.140:53」、'
                                                    '「[2a10:50c0::1:ff]:53」、'
                                                    '「https://unfiltered.adguard-dns.com/dns-query」。'
                                                    '仅支持UDP和HTTPS方法, 留空使用本地DNS查询。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '【订阅URL】'
                                                    f'「IPv4 API」: /api/v1/plugin/ToBypassTrackers/bypassed_ips?apikey={settings.API_TOKEN}&protocol=4; '
                                                    f'「IPv6 API」: /api/v1/plugin/ToBypassTrackers/bypassed_ips?apikey={settings.API_TOKEN}&protocol=6'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '【如何使用】'
                                                    '在「OpenClash->插件设置->中国大陆IP路由」选择「绕过中国大陆」; '
                                                    '在「OpenClash->插件设置->Chnroute Update」填入「订阅URL」。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "cron": "0 4 * * *",
            "bypassed_sites": [],
            "custom_trackers": "",
            "exempted_domains": "",
            "dns_input": "",
            "china_ip_route": True,
            "china_ipv6_route": True,
            "bypass_ipv4": True,
            "bypass_ipv6": True
        }

    def get_page(self) -> List[dict]:
        pass

    def get_dashboard(self, key: str = None, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、全局配置参考：
        {
            "refresh": 10 // 自动刷新时间，单位秒
        }
        3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        """
        pass

    def stop_service(self):
        """
                退出插件
                """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出插件失败：{e}")

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self.get_state():
            return [{
                "id": "ToBypassTrackers",
                "name": "绕过Trackers服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.update_ips,
                "kwargs": {}
            }]
        return []

    def bypassed_ips(self, protocol: str) -> Response:
        if protocol == '6':
            return Response(content=self.ipv6_txt, media_type="text/plain")
        return Response(content=self.ipv4_txt, media_type="text/plain")

    @eventmanager.register(EventType.PluginAction)
    def update_ips(self, event: Optional[Event]=None):
        def __is_ip_in_subnet(ip_input: str, su_bnet: str) -> bool:
            """
            Check if the given IP address is in the specified subnet.

            :param ip_input: IP address as a string (e.g., '192.168.1.1')
            :param su_bnet: Subnet in CIDR notation (e.g., '192.168.1.0/24')
            :return: True if IP is in the subnet, False otherwise
            """
            ip_obj = ipaddress.ip_address(ip_input)
            subnet_obj = ipaddress.ip_network(su_bnet, strict=False)
            return ip_obj in subnet_obj

        def __search_ip(_ip, ips_list):
            i = 0
            for ip_range in ips_list:
                if __is_ip_in_subnet(_ip, ip_range):
                    return i
                i += 1
            return -1

        def __exclude_ip_range(range_b: str, range_a: str):
            """
            Exclude IP range A from IP range B and return the remaining subranges.

            :param range_b: The larger IP range in CIDR notation (must include range_a).
            :param range_a: The smaller IP range to exclude in CIDR notation.
            :return: List of remaining IP subranges in CIDR notation.
            """
            net_b = ipaddress.ip_network(range_b, strict=False)
            net_a = ipaddress.ip_network(range_a, strict=False)

            if not (net_a.subnet_of(net_b)):
                raise ValueError("Range A is not fully contained within Range B.")

            remaining_ranges = list(net_b.address_exclude(net_a))

            return [str(sub_net) for sub_net in remaining_ranges]

        async def resolve_and_check(domain_, results_, failed_msg_, dns_type_, ip_list_):
            try:
                addresses = await query_helper.query_dns(domain_, dns_type_)
                if addresses is None:
                    failed_msg_.append(f"【{domain_name_map.get(domain_, domain_)}】 {domain_}: {dns_type_} 记录查询失败")
                    results_[domain_name_map.get(domain_, domain_)] = False
                    return

                for address in addresses:
                    has_flag = any(__is_ip_in_subnet(address, subnet) for subnet in ip_list_)
                    if not has_flag:
                        if dns_type_ == "AAAA":
                            ip_list_.append(address)
                        else:
                            ip_list_.append(address)
                    logger.info(f"Resolving【{domain_name_map.get(domain_, domain_)}】{address} ({domain_})")
            except Exception as e:
                logger.exception(f"处理 {domain_} 出错: {e}")
                results_[domain_name_map.get(domain_, domain_)] = False

        async def resolve_all(domains_, ipv6_list_, ip_list_):
            tasks = [
                resolve_and_check(domain_, results_v6, failed_msg, "AAAA", ipv6_list_)
                for domain_ in domains_
            ]
            tasks.extend([resolve_and_check(domain_, results, failed_msg, "A", ip_list_)
                          for domain_ in domains_])
            await asyncio.gather(*tasks)

        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "refresh_tracker_ips":
                return
        query_helper = DnsHelper(self._dns_input)
        logger.info(f"开始通过 {query_helper.method_name} 解析DNS")
        chnroute6_lists_url = "https://ispip.clang.cn/all_cn_ipv6.txt"
        chnroute_lists_url = "https://ispip.clang.cn/all_cn.txt"
        ipv6_list = []
        ip_list = []
        domains = []
        success_msg = []
        failed_msg = []
        results = {}
        unsupported_msg = []
        results_v6 = {}
        if self._china_ipv6_route:
            # Load Chnroute6 Lists
            res = RequestUtils().get_res(url=chnroute6_lists_url)
            if res is not None and res.status_code == 200:
                chnroute6_lists = res.text.strip().split('\n')
                ipv6_list = [*chnroute6_lists]
        if self._china_ip_route:
            # Load Chnroute Lists
            res = RequestUtils().get_res(url=chnroute_lists_url)
            if res is not None and res.status_code == 200:
                chnroute_lists = res.text.strip().split('\n')
                ip_list = [*chnroute_lists]
        do_sites = {site.domain: site.name for site in SiteOper().list_order_by_pri() if
                    site.id in self._bypassed_sites}
        domain_name_map = {}
        for site in do_sites:
            site_domains = self.trackers.get(site)
            results[do_sites[site]] = True
            if site_domains:
                domains.extend(site_domains)
                for domain in site_domains:
                    domain_name_map[domain] = do_sites[site]
            else:
                logger.warn(f"不支持的站点: {do_sites[site]}({site})")
                unsupported_msg.append(f'【{do_sites[site]}】不支持的站点')
        for custom_tracker in self._custom_trackers.split('\n'):
            if custom_tracker:
                try:
                    socket.inet_pton(socket.AF_INET, custom_tracker)
                    if self._bypass_ipv4:
                        ip_list.append(f"{custom_tracker}/32")
                except socket.error:
                    try:
                        socket.inet_pton(socket.AF_INET6, custom_tracker)
                        if self._bypass_ipv6:
                            ipv6_list.append(ipaddress.ip_network(f"{custom_tracker}/128", strict=False).compressed)
                    except socket.error:
                        domains.append(custom_tracker)
        v6_ips = []
        v4_ips = []
        asyncio.run(resolve_all(domains, v6_ips, v4_ips))
        ipv6_list.extend([ipaddress.ip_network(f"{ad}/128", strict=False).compressed for ad in v6_ips])
        ip_list.extend([f"{ad}/32" for ad in v4_ips])
        for result in results:
            if results[result]:
                success_msg.append(f"【{result}】 Trackers已被添加")
        exempted_ip = []
        exempted_ipv6 = []
        exempted_domains = []
        for exempted_domain in self._exempted_domains.split('\n'):
            if exempted_domain:
                try:
                    socket.inet_pton(socket.AF_INET, exempted_domain)
                    if self._bypass_ipv4:
                        exempted_ip.append(f"{exempted_domain}")
                except socket.error:
                    try:
                        socket.inet_pton(socket.AF_INET6, exempted_domain)
                        if self._bypass_ipv6:
                            exempted_ipv6.append(f"{exempted_domain}")
                    except socket.error:
                        exempted_domains.append(exempted_domain)

        asyncio.run(resolve_all(exempted_domains, exempted_ip, exempted_ipv6))
        for ip in exempted_ip:
            index = __search_ip(ip, ip_list)
            if index == -1:
                continue
            ip_larger = ip_list[index]
            ip_list.pop(index)
            length = int(ip_larger.split('/')[1])
            if length < 12:
                remaining_ip = __exclude_ip_range(ip_larger, f"{ip}/{length + 8}")
                ip_list.extend(remaining_ip)
        for ip in exempted_ipv6:
            index = __search_ip(ip, ipv6_list)
            if index == -1:
                continue
            ip_larger = ipv6_list[index]
            ipv6_list.pop(index)
            length = int(ip_larger.split('/')[1])
            if length < 32:
                remaining_ip = __exclude_ip_range(ip_larger, f"{ip}/{min(32, length + 8)}")
                ipv6_list.extend(remaining_ip)
        self.ipv4_txt = "\n".join(ip_list)
        self.ipv6_txt = "\n".join(ipv6_list)
        self.save_data("ipv4_txt", self.ipv4_txt)
        self.save_data("ipv6_txt", self.ipv6_txt)
        if self._notify:
            res_message = success_msg + failed_msg
            res_message = "\n".join(res_message)
            self.post_message(title=f"【绕过Trackers】",
                              mtype=NotificationType.Plugin,
                              text=f"{res_message}"
                              )
