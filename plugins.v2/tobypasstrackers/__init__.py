import asyncio
import base64
import ipaddress
import json
import socket
import time
from datetime import datetime, timedelta
from ipaddress import IPv4Network, IPv6Network, IPv4Address, IPv6Address
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional, Literal, overload
from urllib.parse import urlparse

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Response
from pydantic import BaseModel, Field
from torrentool.api import Torrent
from torrentool.exceptions import BencodeDecodingError

from app.chain.torrents import TorrentsChain
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.db.site_oper import SiteOper
from app.helper.torrent import TorrentHelper
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from .dns_helper import DnsHelper


class IpCidrItem(BaseModel):
    # IP CIDR
    ip_cidr: str
    # 解析时间
    timestamp: int = Field(default=0)
    # DNS
    nameserver: str | None = Field(default=None)
    # 域名
    domain: str | None = Field(default=None)

    def to_dict(self) -> dict:
        if self.timestamp:
            dns_time = datetime.fromtimestamp(int(self.timestamp)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            dns_time = '-'
        return {
            'ip_cidr': self.ip_cidr,
            'domain': self.domain or '',
            'nameserver': self.nameserver or '-',
            'datetime': dns_time
        }


class ToBypassTrackers(_PluginBase):
    # 插件名称
    plugin_name = "绕过Trackers"
    # 插件描述
    plugin_desc = "提供 Tracker 服务器 IP 地址列表，帮助 IPv6 连接绕过 OpenClash。"
    # 插件图标
    plugin_icon = "Clash_A.png"
    # 插件版本
    plugin_version = "1.5.2"
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
    # CN IP lists
    chn_route6_lists_url = "https://ispip.clang.cn/all_cn_ipv6.txt"
    chn_route_lists_url = "https://ispip.clang.cn/all_cn.txt"
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    # 开关
    _enabled: bool = False
    _cron: str = ""
    _sync_cron: str = ""
    _notify: bool = False
    _onlyonce: bool = False
    _custom_trackers: str = ""
    _exempted_domains: str = ""
    _bypassed_sites: list = []
    _china_ip_route: bool = True
    _china_ipv6_route: bool = True
    _bypass_ipv4: bool = True
    _bypass_ipv6: bool = True
    _dns_input: str | None = None

    def init_plugin(self, config: dict = None):

        self.stop_service()
        # 配置
        if config:
            self._enabled = bool(config.get("enabled"))
            self._cron = config.get("cron") or "0 4 * * *"
            self._sync_cron = config.get("sync_cron") or "30 4 * * 1"
            self._onlyonce = bool(config.get("onlyonce"))
            self._notify = bool(config.get("notify"))
            self._custom_trackers = config.get("custom_trackers") or ""
            self._exempted_domains = config.get("exempted_domains") or ""
            self._bypassed_sites = config.get("bypassed_sites") or []
            self._bypass_ipv4 = bool(config.get("bypass_ipv4"))
            self._bypass_ipv6 = bool(config.get("bypass_ipv6"))
            self._dns_input: str | None = config.get("dns_input")
            self._china_ipv6_route = bool(config.get("china_ipv6_route"))
            self._china_ip_route = bool(config.get("china_ip_route"))
            # 过滤掉已删除的站点
            all_sites = [site.id for site in SiteOper().list_order_by_pri()]
            self._bypassed_sites = [site_id for site_id in all_sites if site_id in self._bypassed_sites]
            self.__update_config()
        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if self._onlyonce:
                logger.info("立即运行一次")
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
                "sync_cron": self._sync_cron,
                "onlyonce": self._onlyonce,
                "bypassed_sites": self._bypassed_sites,
                "custom_trackers": self._custom_trackers,
                "exempted_domains": self._exempted_domains,
                "notify": self._notify,
                "dns_input": self._dns_input,
                "china_ip_route": self._china_ip_route,
                "china_ipv6_route": self._china_ipv6_route,
                "bypass_ipv6": self._bypass_ipv6,
                "bypass_ipv4": self._bypass_ipv4,
            }
        )

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/refresh_tracker_ips",
                "event": EventType.PluginAction,
                "desc": "更新 Tracker IP 列表",
                "data": {
                    "action": "refresh_tracker_ips"
                }
            },
            {
                "cmd": "/check_ip",
                "event": EventType.PluginAction,
                "desc": "检测 IP 是否在绕过列表中: /check_ip <域名或IP>",
                "data": {
                    "action": "check_ip"
                }
            }
        ]

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
        return [
            {
                "path": "/bypassed_ips",
                "endpoint": self.bypassed_ips,
                "methods": ["GET"],
                "summary": "绕过的 IP",
                "description": "绕过 Clash 核心的 IP 地址列表",
            }
        ]

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
                                            'label': '合并中国大陆 IPv4 列表',
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
                                            'label': '合并中国大陆 IPv6 列表',
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
                                    'md': 4
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'sync_cron',
                                            'label': 'Trackers 更新周期',
                                            'placeholder': '30 4 * * 1'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'dns_input',
                                            'label': 'DNS 服务器',
                                            'placeholder': '留空则使用本地 DNS'
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
                                            'label': '自定义 Tracker 服务器',
                                            'rows': 3,
                                            'placeholder': '每行一个域名或 IP'
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
                                            'label': '排除的域名和 IP',
                                            'rows': 3,
                                            'placeholder': '每行一个域名或 IP'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VCard',
                        'content': [
                            {
                                'component': 'VCardItem',
                                'props': {
                                    'prepend-icon': 'mdi-link-variant',
                                    'title': '订阅 URL',
                                    'subtitle': '请先在 MoviePilot 设置中配置「访问域名」',
                                    'class': 'pb-0'
                                },
                            },
                            {
                                'component': 'VCardActions',
                                'props': {
                                },
                                'content': [
                                    {
                                        'component': 'VBtn',
                                        'text': 'IPv4',
                                        'props': {
                                            'append-icon': 'mdi-open-in-new',
                                            'href': self.api_url(protocol=4),
                                            'target': '_blank'
                                        },

                                    },
                                    {
                                        'component': 'VBtn',
                                        'text': 'IPv6',
                                        'props': {
                                            'append-icon': 'mdi-open-in-new',
                                            'href': self.api_url(protocol=6),
                                            'target': '_blank'
                                        },

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
                                            'title': 'DNS 服务器示例',
                                            'border': 'start',
                                            'variant': 'tonal',
                                            'text': '仅填一个: '
                                                    '「223.5.5.5」、'
                                                    '「[2400:3200::1]:53」、'
                                                    '「quic://dns.alidns.com:853」、'
                                                    '「https://dns.alidns.com/dns-query」。'
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
                                            'variant': 'tonal',
                                            'color': 'info',
                                            'border': 'start',
                                            'title': '如何使用',
                                            'text': '在「OpenClash->插件设置->流量控制->绕过指定区域 IP」选择「绕过中国大陆」; '
                                                    '在「OpenClash->插件设置->大陆白名单订阅」填入「订阅 URL」。'
                                                    '使用聊天命令`/check_ip <域名或IP>`检查 IP 是否在绕过列表。'
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
            "bypass_ipv6": True,
            "sync_cron": "30 4 * * 1"
        }

    def get_page(self) -> List[dict]:
        headers = [
            {'title': 'IP CIDR', 'key': 'ip_cidr', 'sortable': True},
            {'title': '域名', 'key': 'domain', 'sortable': True},
            {'title': 'DNS', 'key': 'nameserver', 'sortable': True},
            {'title': '解析时间', 'key': 'datetime', 'sortable': True},
        ]
        items = [IpCidrItem.model_validate(detail).to_dict()
                 for detail in (self.get_data("cidr_details") or []) if detail.get('domain') != 'CN']
        excluded_items = [IpCidrItem.model_validate(detail).to_dict()
                                 for detail in (self.get_data("excluded_cidr_details") or [])]

        return [
            {
                'component': 'VWindow',
                'props': {
                    'show-arrows': 'hover',
                },
                'content': [
                    {
                        'component': 'VWindowItem',
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'class': 'pa-0',
                                    'title': '绕过的 Tracker 服务器 IP 列表',
                                    'subtitle': '以下是已解析并添加到绕过列表中的 Tracker 服务器 IP 地址，'
                                                '请在 OpenClash 中配置「绕过中国大陆 IP」并订阅本列表以实现绕过效果。',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'content': [
                                            {
                                                'component': 'VDataTableVirtual',
                                                'props': {
                                                    'class': 'text-sm',
                                                    'headers': headers,
                                                    'items': items,
                                                    'height': '30rem',
                                                    'density': 'compact',
                                                    'fixed-header': True,
                                                    'hide-no-data': True,
                                                    'hover': True
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VWindowItem',
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'class': 'pa-0',
                                    'title': '排除的 IP 列表',
                                    'variant': 'elevated',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'content': [
                                            {
                                                'component': 'VDataTableVirtual',
                                                'props': {
                                                    'class': 'text-sm',
                                                    'headers': headers,
                                                    'items': excluded_items,
                                                    'height': '30rem',
                                                    'density': 'compact',
                                                    'fixed-header': True,
                                                    'hide-no-data': True,
                                                    'hover': True
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ]

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

    def api_url(self, protocol: int = 4) -> str:
        return settings.MP_DOMAIN(f'/api/v1/plugin/{self.__class__.__name__}/bypassed_ips?apikey={settings.API_TOKEN}'
                                  f'&protocol={protocol}')

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
            return [
                {
                    "id": "UpdateIPs",
                    "name": "更新IP列表",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.update_ips,
                    "kwargs": {}
                },
                {
                    "id": "GetTrackers",
                    "name": "更新Trackers",
                    "trigger": CronTrigger.from_crontab(self._sync_cron),
                    "func": self.refresh_trackers,
                    "kwargs": {}
                }
            ]
        return []

    @eventmanager.register(EventType.PluginReload)
    def reload(self, event):
        """
        响应插件重载事件
        """
        plugin_id = event.event_data.get("plugin_id")

        if plugin_id == self.__class__.__name__:
            Scheduler().update_plugin_job(plugin_id)

    @property
    def trackers(self) -> dict[str, list[str]]:
        trackers: dict[str, list[str]] = {}
        tracker_file = Path(self.get_data_path() / "trackers.json")
        try:
            if tracker_file.exists():
                trackers: dict[str, list[str]] = json.loads(tracker_file.read_text())
            else:
                file = settings.ROOT_PATH / 'app' / 'plugins' / self.__class__.__name__.lower() / 'sites' / 'trackers'
                with open(file, "r", encoding="utf-8") as f:
                    base64_str = f.read()
                    trackers = json.loads(base64.b64decode(base64_str).decode("utf-8"))
        except Exception as e:
            logger.error(f"trackers 加载错误：{e}")
        return trackers

    def refresh_trackers(self):
        """更新 Tracker 服务器列表"""
        logger.info("开始从站点获取最新 Tracker 服务器 ...")
        trackers = self.trackers
        sites = [site for site in SiteOper().list_order_by_pri() if site.id in self._bypassed_sites]
        torrents_chain = TorrentsChain()
        for site in sites:
            torrents = torrents_chain.browse(domain=site.domain)
            if not torrents:
                continue
            torrent_url = torrents[0].enclosure
            _, content, _, _, error_msg = TorrentHelper().download_torrent(
                url=torrent_url,
                cookie=site.cookie,
                ua=site.ua or settings.USER_AGENT,
                proxy=bool(site.proxy))
            if not content or error_msg:
                continue
            try:
                torrent = Torrent.from_string(content)
            except BencodeDecodingError as e:
                logger.error(f"解析 {site.name} 种子文件失败: {e}")
                continue
            servers: list[str] = []
            for urls in torrent.announce_urls:
                for url in urls:
                    parsed = urlparse(url)
                    if parsed.hostname:
                        servers.append(parsed.hostname)
            if servers:
                trackers[site.domain] = servers
        tracker_file = Path(self.get_data_path() / "trackers.json")
        tracker_file.write_text(json.dumps(trackers, indent=4))
        logger.info("已更新 Tracker 服务器列表")

    def bypassed_ips(self, protocol: Literal['4', '6']) -> Response:
        data_key = "ipv4_txt" if protocol == '4' else "ipv6_txt"
        data = self.get_data(data_key) or ""
        return Response(content=data, media_type="text/plain")

    @eventmanager.register(EventType.PluginAction)
    def check_ip(self, event: Event):
        """检查 IP 地址 是否在绕过列表"""
        event_data = event.event_data
        if not event_data or event_data.get("action") != "check_ip":
            return
        host = event_data.get("arg_str")
        channel = event_data.get("channel")
        userid = event_data.get("userid")
        logger.info(f"检查 IP 是否绕过: {host} (来自用户 {userid}，渠道 {channel})")
        ip_list, bypassed, excluded = self._check_details(host)
        if not ip_list:
            self.post_message(channel=channel, user=userid, text=f"无法解析 host: {host}", title=f"{host}")
            return
        message = ""
        for ip in ip_list:
            detail = bypassed.get(ip)
            excluded_detail = excluded.get(ip)
            sub_message = f"「{ip}」"
            if excluded_detail is not None:
                detail_msg = '\n'.join(f"{k}: {v}" for k,v in excluded_detail.to_dict().items())
                sub_message += f" 在排除列表中：\n{detail_msg}\n"
            if detail is not None:
                detail_msg = '\n'.join(f"{k}: {v}" for k,v in detail.to_dict().items())
                sub_message += f" 在绕过列表中：\n{detail_msg}\n"
            if detail and not excluded_detail:
                sub_message += f"✈️ 会被绕过。\n"
            else:
                sub_message += f"🛑 不会被绕过。\n"
            message += sub_message + "\n"
        self.post_message(channel=channel, user=userid, text=message, title=f"{host}")

    @overload
    def _load_cn_ip_lists(self, family: type[IPv4Network]) -> list[IPv4Network]: ...

    @overload
    def _load_cn_ip_lists(self, family: type[IPv6Network]) -> list[IPv6Network]: ...

    def _load_cn_ip_lists(self, family: type[IPv4Network] | type[IPv6Network] = IPv4Network
                          ) -> list[IPv4Network | IPv6Network]:
        ip_list: list[IPv4Network | IPv6Network] = []
        if family is IPv4Network:
            url = self.chn_route_lists_url
        elif family is IPv6Network:
            url = self.chn_route6_lists_url
        else:
            raise NotImplementedError(f"unknown address family {family}")
        res = RequestUtils().get_res(url=url, raise_exception=True)
        if res is None or res.status_code != 200:
            logger.warn(f"无法获取 CN IP 列表: {url}")
            raise ConnectionError
        route_list = res.text.strip().split('\n')
        for cn_ip_cidr in route_list:
            subnet = ipaddress.ip_network(cn_ip_cidr, strict=False)
            if isinstance(subnet, family):
                ip_list.append(subnet)
        return ip_list

    def _search_details(self, ip_list: list[IPv4Address | IPv6Address], data_key: str) -> dict[str, IpCidrItem | None]:
        cidr_details = [IpCidrItem.model_validate(detail) for detail in (self.get_data(data_key) or [])]
        ip_cidr_list = [ipaddress.ip_network(item.ip_cidr, strict=False) for item in cidr_details]
        details: dict[str, IpCidrItem | None] = {}
        for ip in ip_list:
            index = ToBypassTrackers._search_ip(ip, ip_cidr_list)
            if index == -1:
                details[str(ip)] = None
                continue
            details[str(ip)] = cidr_details[index]
        return details

    def _check_details(self, host: str) -> tuple[list[str], dict[str, IpCidrItem | None], dict[str, IpCidrItem | None]]:
        try:
            ip_list = [ipaddress.ip_address(host)]
        except ValueError:
            dns = DnsHelper(dns_server=self._dns_input)
            resolved = asyncio.run(dns.resolve_name(host))
            if resolved is None:
                return [], {}, {}
            ip_list = [ipaddress.ip_address(ip) for ip in resolved]
        details = self._search_details(ip_list, "cidr_details")
        excluded = self._search_details(ip_list, "excluded_cidr_details")
        return  [str(ip) for ip in ip_list], details, excluded

    @staticmethod
    def _search_ip(ip: IPv4Address | IPv6Address, ips_list: list[IPv4Network | IPv6Network]) -> int:
        i = 0
        for ip_range in ips_list:
            if ip in ip_range:
                return i
            i += 1
        return -1

    @staticmethod
    def _search_subnet(ip: IPv4Network | IPv6Network, ips_list: list[IPv4Network | IPv6Network]) -> int:
        i = 0
        for ip_range in ips_list:
            if ip.subnet_of(ip_range):
                return i
            i += 1
        return -1

    @eventmanager.register(EventType.PluginAction)
    def update_ips(self, event: Optional[Event] = None):

        async def resolve_and_check(domain_: str, results_: dict[str, bool], failed_msg_: list[str],
                                    family: int, ip_list_: list[IPv4Network | IPv6Network],
                                    cidr_details_: list[IpCidrItem]):
            try:
                addresses = await query_helper.resolve_name(domain_, family)
                if addresses is None:
                    dns_type = "AAAA" if family == socket.AF_INET6 else "A"
                    failed_msg_.append(f"【{domain_name_map.get(domain_, domain_)}】 {domain_}: {dns_type} 记录查询失败")
                    results_[domain_name_map.get(domain_, domain_)] = False
                    return

                for ip_str in addresses:
                    ip_obj = ipaddress.ip_address(ip_str)
                    has_flag = any(ip_obj in sub_net for sub_net in ip_list_)
                    if not has_flag:
                        net_obj = ipaddress.ip_network(ip_obj, strict=False)
                        ip_list_.append(net_obj)
                        ip_cidr_item = IpCidrItem(ip_cidr=str(net_obj), domain=domain_,
                                                  timestamp=int(time.time()), nameserver=query_helper.nameserver)
                        cidr_details_.append(ip_cidr_item)
                    logger.info(f"Resolving【{domain_name_map.get(domain_, domain_)}】{ip_str} ({domain_})")
            except Exception as e:
                logger.warn(f"处理 {domain_} 出错: {e}")
                results_[domain_name_map.get(domain_, domain_)] = False

        async def resolve_all(domains_: list[str], ipv6_list_: list[IPv6Network], ip_list_: list[IPv4Network],
                              details: list[IpCidrItem]):
            tasks = [
                resolve_and_check(domain_, results_v6, failed_msg, socket.AF_INET6, ipv6_list_, details)
                for domain_ in domains_
            ]
            tasks.extend([resolve_and_check(domain_, results, failed_msg, socket.AF_INET, ip_list_, details)
                          for domain_ in domains_])
            await asyncio.gather(*tasks)

        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "refresh_tracker_ips":
                return
        query_helper = DnsHelper(self._dns_input)
        logger.info(f"开始通过 {query_helper.nameserver} 解析DNS")

        ipv6_list: list[IPv6Network] = []
        ip_list: list[IPv4Network] = []
        domains = []
        success_msg = []
        failed_msg = []
        results: dict[str, bool] = {}  # 解析结果
        unsupported_msg = []
        results_v6: dict[str, bool] = {}
        cidr_details: list[IpCidrItem] = []
        exempted_cidr_details: list[IpCidrItem] = []

        # 加载 CN IP 列表
        if self._china_ipv6_route:
            ipv6_list = self._load_cn_ip_lists(family=IPv6Network)
        if self._china_ip_route:
            ip_list = self._load_cn_ip_lists(family=IPv4Network)
        for ip in ipv6_list + ip_list:
            cidr_details.append(IpCidrItem(ip_cidr=str(ip), domain="CN", timestamp=int(time.time())))

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
                    address = ipaddress.ip_address(custom_tracker)
                    net = ipaddress.ip_network(address)
                    if isinstance(net, IPv4Network):
                        if self._bypass_ipv4:
                            ip_list.append(net)
                    elif isinstance(net, IPv6Network):
                        if self._bypass_ipv6:
                            ipv6_list.append(net)
                except ValueError:
                        domains.append(custom_tracker)
        v6_nets = []
        v4_nets = []
        asyncio.run(resolve_all(domains, v6_nets, v4_nets, cidr_details))
        ipv6_list.extend(v6_nets)
        ip_list.extend(v4_nets)
        for result in results:
            if results[result]:
                success_msg.append(f"【{result}】 Trackers已被添加")
        exempted_ip: list[IPv4Network] = []
        exempted_ipv6: list[IPv6Network] = []
        exempted_domains = []
        for exempted_domain in self._exempted_domains.split('\n'):
            if exempted_domain:
                try:
                    address = ipaddress.ip_address(exempted_domain)
                    net = ipaddress.ip_network(address)

                    if isinstance(net, IPv4Network):
                        if self._bypass_ipv4:
                            exempted_ip.append(net)
                    elif isinstance(net, IPv6Network):
                        if self._bypass_ipv6:
                            exempted_ipv6.append(net)
                    exempted_cidr_details.append(IpCidrItem(ip_cidr=str(net), domain=exempted_domain,
                                                            timestamp=int(time.time())))
                except ValueError:
                        exempted_domains.append(exempted_domain)
        cidr_details_dict = {detail.ip_cidr: detail for detail in cidr_details}
        asyncio.run(resolve_all(exempted_domains, exempted_ipv6, exempted_ip, exempted_cidr_details))
        for ip in exempted_ip:
            while (index:= ToBypassTrackers._search_subnet(ip, ip_list)) != -1:
                subnet = ip_list[index]
                ip_list.pop(index)
                source = cidr_details_dict[str(subnet)].domain if str(subnet) in cidr_details_dict else "CN"
                logger.warn(f"Excluding subnet {subnet} ({source}) for exempted IP {ip}")
                if subnet.prefixlen < 12:
                    new_subnet = IPv4Network((ip.network_address, subnet.prefixlen + 8), strict=False)
                    ip_list.extend(subnet.address_exclude(new_subnet))
        for ip in exempted_ipv6:
            while (index:=ToBypassTrackers._search_subnet(ip, ipv6_list)) != -1:
                subnet = ipv6_list[index]
                ipv6_list.pop(index)
                source = cidr_details_dict[str(subnet)].domain if str(subnet) in cidr_details_dict else "CN"
                logger.warn(f"Excluding subnet {subnet} ({source}) for exempted IP {ip}")
                if subnet.prefixlen < 32:
                    new_subnet = IPv6Network((ip.network_address, min(32, subnet.prefixlen + 8)), strict=False)
                    ipv6_list.extend(subnet.address_exclude(new_subnet))
        ipv4_txt = "\n".join(str(net) for net in ip_list)
        ipv6_txt = "\n".join(str(net) for net in ipv6_list)
        self.save_data("ipv4_txt", ipv4_txt)
        self.save_data("ipv6_txt", ipv6_txt)
        self.save_data("cidr_details", [detail.model_dump() for detail in cidr_details])
        self.save_data("excluded_cidr_details", [detail.model_dump() for detail in exempted_cidr_details])
        if self._notify:
            res_message = success_msg + failed_msg
            res_message = "\n".join(res_message)
            self.post_message(
                title=f"【{self.plugin_name}】",
                mtype=NotificationType.Plugin,
                text=f"{res_message}"
            )
