# -*- coding: utf-8 -*-
"""站点用户详情采集插件（SiteUserDetail）。

定时采集每个 PT 站用户详情页的两类数据：
1. BT 客户端列表（agent / ipv4 / ipv6 / port），每站至少一条，解析不到给全空值条目；
2. 下载中种子列表（id / hash / name / 促销标签 / size），hash 优先在下载器种子列表
   按种子名匹配回填，种子详情页解析兜底，均失败留空。

数据以两个平铺列表返回（每项含 site/domain 字段），API 聚合分组由三方前端自行完成；
插件详情页提供摘要、明细与 IP 聚合视图。插件暴露两个 API：
- GET /api/v1/plugin/SiteUserDetail/collect?apikey=<TOKEN>&sites=<域名,逗号分隔>
  触发一次采集（与定时任务共用 collect 逻辑）并返回结果；
- GET /api/v1/plugin/SiteUserDetail/snapshot?apikey=<TOKEN>&sites=<...>
  读取最近一次采集快照（不触发采集）。

站点适配采用「通用架构采集 + 站点适配器」架构，详见 adapters/ 目录。
"""

import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from app import schemas
from app.db.oper.site import SiteOper
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import SitesHelper
from app.sdk.plugin import _PluginBase
from app.sdk.services import DownloaderHelper
from app.sdk.utilities import StringUtils
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .adapters import AdapterError, get_adapter


class SiteUserDetail(_PluginBase):
    """站点用户详情采集：BT 客户端 + 下载中种子 + 插件 API。"""

    # 插件名称
    plugin_name = "站点用户详情采集"
    # 插件描述
    plugin_desc = "定时采集 PT 站用户详情页的 BT 客户端与下载中种子数据，并通过插件 API 供三方调用。"
    # 插件图标
    plugin_icon = "siteuserdetail.png"
    # 插件版本
    plugin_version = "1.0.5"
    # 插件作者
    plugin_author = "Guoyin-Wen"
    # 作者主页
    author_url = "https://github.com/Guoyin-Wen"
    # 插件配置项ID前缀
    plugin_config_prefix = "siteuserdetail_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 2

    # 一次性任务执行器
    _scheduler: Optional[BackgroundScheduler] = None
    # 采集互斥锁：防止定时/API/立即运行并发触发重复采集
    _collect_lock = threading.Lock()

    # 配置属性
    _enabled: bool = False
    _onlyonce: bool = False
    _notify: bool = False
    _cron: str = ""
    _sites: list = []
    _use_downloader_hash: bool = True
    _hash_from_detail: bool = True
    _detail_limit: int = 20
    _request_interval: int = 3
    _concurrency: int = 3

    def init_plugin(self, config: dict = None):
        """加载配置并按需注册立即执行任务。"""
        self.stop_service()
        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._notify = bool(config.get("notify"))
            self._cron = str(config.get("cron") or "").strip()
            self._sites = config.get("sites") or []
            self._use_downloader_hash = bool(config.get("use_downloader_hash", True))
            self._hash_from_detail = bool(config.get("hash_from_detail", True))
            self._detail_limit = int(config.get("detail_limit") or 20)
            self._request_interval = int(config.get("request_interval") or 3)
            self._concurrency = int(config.get("concurrency") or 3)

            # 过滤已删除的站点
            all_site_ids = {str(site.id) for site in SiteOper().list_order_by_pri()} | {
                str(site.get("id")) for site in self.__custom_sites()}
            self._sites = [site_id for site_id in self._sites if str(site_id) in all_site_ids]
            self.__update_config()

        if self._enabled or self._onlyonce:
            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info("站点用户详情采集服务启动，立即运行一次")
                self._scheduler.add_job(
                    func=self.collect, trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="站点用户详情采集")
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        """停止一次性任务。"""
        try:
            if self._scheduler and self._scheduler.get_jobs():
                self._scheduler.shutdown()
                self._scheduler = None
        except Exception as err:
            logger.error(f"停止任务失败: {str(err)}")

    def get_command(self) -> Optional[List[Dict[str, Any]]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """暴露给三方系统的采集/查询接口。"""
        return [
            {
                "path": "/collect",
                "endpoint": self.api_collect,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "触发一次采集并返回结果",
                "description": "实时从各站采集最新数据（与定时任务同一逻辑），"
                               "支持 sites 参数（站点域名，逗号分隔）限定范围",
            },
            {
                "path": "/snapshot",
                "endpoint": self.api_snapshot,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "读取最近一次采集快照",
                "description": "返回最近一次采集（定时或 collect 接口）存储的数据，不触发采集，"
                               "支持 sites 参数（站点域名，逗号分隔）过滤",
            },
        ]

    def get_service(self) -> Optional[List[Dict[str, Any]]]:
        """注册定时服务：5 位 cron 表达式 / 小时间隔数字，留空默认每 6 小时。"""
        if not self._enabled:
            return []
        cron = str(self._cron or "").strip()
        trigger: Any
        kwargs: Dict[str, Any] = {}
        try:
            if not cron:
                trigger = "interval"
                kwargs = {"hours": 6.0}
            elif cron.count(" ") == 4:
                trigger = CronTrigger.from_crontab(cron)
            else:
                # 纯数字视为小时间隔
                trigger = "interval"
                kwargs = {"hours": float(cron)}
        except Exception as err:
            logger.error(f"PT站用户详情采集定时配置错误: {err}")
            return []
        return [{
            "id": "SiteUserDetail",
            "name": "站点用户详情采集服务",
            "trigger": trigger,
            "func": self.collect,
            "kwargs": kwargs,
        }]

    def get_form(self) -> tuple:
        """配置页面（注意：第一个元素必须是 Vuetify 组件 list）。"""
        custom_sites = self.__custom_sites()
        site_options = ([{"title": site.name, "value": site.id}
                         for site in SiteOper().list_order_by_pri()]
                        + [{"title": site.get("name"), "value": site.get("id")}
                           for site in custom_sites])
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用定时采集'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'onlyonce', 'label': '立即运行一次'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'notify', 'label': '发送采集通知'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron或小时间隔，默认每6小时'
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'sites',
                                            'label': '采集站点',
                                            'items': site_options,
                                            'hint': '留空采集全部已配置站点',
                                            'persistent-hint': True
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
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'use_downloader_hash',
                                            'label': '下载器匹配 hash',
                                            'hint': '按种子名在下载器种子列表匹配 infohash',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'hash_from_detail',
                                            'label': '详情页兜底 hash',
                                            'hint': '匹配不到时访问种子详情页解析（注意请求量）',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 2},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'detail_limit',
                                            'label': '详情页请求上限',
                                            'hint': '每站每次采集最多访问的详情页数',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 2},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'request_interval',
                                            'label': '同站请求间隔(秒)'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 2},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'concurrency',
                                            'label': '站点并发数'
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': 'API：GET /api/v1/plugin/SiteUserDetail/collect'
                                                    '?apikey=<TOKEN>&sites=<域名,逗号分隔> 实时采集并返回；'
                                                    'GET /api/v1/plugin/SiteUserDetail/snapshot 读取最近快照。'
                                                    '返回 clients/torrents 两个平铺列表（每项含 site/domain），聚合分组由调用方完成。'
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '站点需在 MoviePilot 中配置有效 Cookie/UA（M-Team 需 APIKEY）；'
                                                    'hash 回填需已配置下载器。客户端表格解析不到的站点会返回全空值条目。'
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
            "onlyonce": False,
            "notify": False,
            "cron": "",
            "sites": [],
            "use_downloader_hash": True,
            "hash_from_detail": True,
            "detail_limit": 20,
            "request_interval": 3,
            "concurrency": 3
        }

    def get_page(self) -> Optional[List[Dict[str, Any]]]:
        """插件详情页：采集快照摘要 + 客户端/种子明细 + IP 聚合视图。"""
        snapshot = self.get_data("snapshot")
        if not isinstance(snapshot, dict) or not snapshot \
                or not any(snapshot.get(k) is not None for k in ("clients", "torrents", "errors")):
            return [{
                'component': 'VAlert',
                'props': {
                    'type': 'info', 'variant': 'tonal', 'class': 'mt-4',
                    'prepend-icon': 'mdi-information',
                    'text': '暂无采集数据：请开启插件定时采集，或在设置中「立即运行一次」，'
                            '也可调用 collect 接口实时采集。'
                }
            }]

        clients = snapshot.get("clients") or []
        torrents = snapshot.get("torrents") or []
        errors = snapshot.get("errors") or []
        site_count = len({c.get("site") for c in clients if c.get("site")})
        valid_clients = [c for c in clients
                         if c.get("agent") or c.get("ipv4") or c.get("ipv6") or c.get("port") is not None]
        no_data_clients = [c for c in clients if not (c.get("agent") or c.get("ipv4") or c.get("ipv6"))]
        hash_hit = sum(1 for t in torrents if t.get("hash"))
        promo_counter = Counter(tag for t in torrents for tag in (t.get("tags") or []))
        no_promo = sum(1 for t in torrents if not t.get("tags"))
        update_time = snapshot.get("update_time")
        update_str = datetime.fromtimestamp(int(update_time)).strftime("%Y-%m-%d %H:%M:%S") \
            if update_time else "-"

        # 促销分布 chips
        promo_chips = [{
            'component': 'VChip', 'props': {
                'size': 'x-small', 'variant': 'tonal', 'color': 'success', 'class': 'mr-1'
            }, 'text': f"{tag} ×{count}"
        } for tag, count in promo_counter.most_common(8)]
        if no_promo:
            promo_chips.append({
                'component': 'VChip', 'props': {
                    'size': 'x-small', 'variant': 'tonal', 'class': 'mr-1'
                }, 'text': f"无促销 ×{no_promo}"
            })

        # 促销分布 chips + 种子表
        torrents_content: list = []
        if promo_chips:
            torrents_content.append({
                'component': 'div', 'props': {'class': 'sud-promo mb-2'}, 'content': promo_chips
            })
        torrents_content.append(self._torrents_table(torrents))

        return [
            {'component': 'style', 'text': self._page_css()},
            {
                'component': 'div',
                'props': {'class': 'sud-page'},
                'content': [
                    {
                        'component': 'div',
                        'props': {'class': 'sud-summary'},
                        'content': [
                            self._stat_item("更新时间", update_str,
                                            f"客户端 {len(valid_clients)} 条有效 / 共 {len(clients)} 条",
                                            "mdi-clock-outline"),
                            self._stat_item("采集站点", f"{site_count}",
                                            f"失败 {len(errors)} 站" if errors else "全部成功",
                                            "mdi-web", "error" if errors else "success"),
                            self._stat_item("下载中种子", f"{len(torrents)}",
                                            f"已匹配 hash {hash_hit} 个", "mdi-download", "primary"),
                        ]
                    },
                    # IP 聚合在前；客户端分节：无数据站点 + 全部站点（同级可折叠）
                    *self._ip_sections(clients),
                    self._page_section(
                        title="无数据站点",
                        icon="mdi-lan-disconnect" if no_data_clients else "mdi-lan-connect",
                        count_text=f"{len(no_data_clients)} 个",
                        content=self._clients_no_data_content(no_data_clients, errors)),
                    self._page_section(
                        title="全部站点", icon="mdi-lan-connect",
                        count_text=f"{len(clients)} 条记录",
                        content=[self._clients_table(clients)]),
                    self._page_section(
                        title="下载中种子", icon="mdi-download", count_text=f"{len(torrents)} 个",
                        content=torrents_content),
                    *([self._page_section(
                        title="失败站点", icon="mdi-alert-circle-outline", count_text=f"{len(errors)} 个",
                        content=[{
                            'component': 'VAlert', 'props': {
                                'type': 'error', 'variant': 'tonal', 'density': 'compact'
                            },
                            'text': "；".join(f"{e.get('site')}: {e.get('error')}" for e in errors[:10])
                        }])] if errors else []),
                ]
            }
        ]

    # ------------------------------------------------------------------ 详情页构件

    _PAGE_CSS = """
    .sud-page { display: flex; flex-direction: column; gap: 10px; }
    .sud-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .sud-stat { min-width: 0; padding: 10px 12px; border-radius: 8px;
                background: rgba(var(--v-theme-surface-variant), .35); }
    .sud-stat__head { display: flex; align-items: center; gap: 6px; min-width: 0;
                      color: rgba(var(--v-theme-on-surface), .6); font-size: .75rem;
                      font-weight: 600; white-space: nowrap; overflow: hidden;
                      text-overflow: ellipsis; }
    .sud-stat__value { margin-top: 8px; font-size: 1.15rem; font-weight: 700; line-height: 1.2;
                       word-break: break-all; }
    .sud-stat__meta { margin-top: 4px; color: rgba(var(--v-theme-on-surface), .5); font-size: .72rem; }
    .sud-section .v-expansion-panel-title { font-weight: 600; }
    .sud-section-head { display: flex; align-items: center; gap: 6px; }
    .sud-table th { height: 34px !important; padding: 0 8px !important; white-space: nowrap;
                    color: rgba(var(--v-theme-on-surface), .62); font-size: .75rem; }
    .sud-table td { height: 36px !important; padding: 0 8px !important; font-size: .8rem;
                    vertical-align: middle; max-width: 420px; overflow: hidden;
                    text-overflow: ellipsis; white-space: nowrap; }
    .sud-table td.sud-wrap { white-space: normal; overflow: visible; max-width: none;
                             line-height: 1.6; }
    .sud-muted td { color: rgba(var(--v-theme-on-surface), .38); }
    .sud-promo { display: flex; flex-wrap: wrap; gap: 4px; }
    @media (max-width: 720px) { .sud-summary { grid-template-columns: 1fr; } }
    """

    @classmethod
    def _page_css(cls) -> str:
        return cls._PAGE_CSS

    @staticmethod
    def _site_label(item: Dict[str, Any]) -> str:
        """站点显示名：name 为空时回退 domain，再回退「未知」。"""
        return str(item.get("site") or item.get("domain") or "未知")

    @staticmethod
    def _stat_item(label: str, value: str, meta: str = "",
                   icon: str = "mdi-chart-box-outline", color: str = "primary") -> dict:
        return {
            'component': 'div',
            'props': {'class': 'sud-stat'},
            'content': [
                {'component': 'VIcon', 'props': {'size': 'small', 'color': color}, 'text': icon},
                {'component': 'span', 'props': {'class': 'sud-stat__head'}, 'text': label},
                {'component': 'div', 'props': {'class': 'sud-stat__value'}, 'text': str(value)},
                {'component': 'div', 'props': {'class': 'sud-stat__meta'}, 'text': meta} if meta
                else {'component': 'span', 'props': {}},
            ]
        }

    @staticmethod
    def _page_section(title: str, icon: str, count_text: str, content: list) -> dict:
        """可折叠分节（手风琴，默认收起，点击展开）。"""
        return {
            'component': 'VExpansionPanels',
            'props': {'variant': 'accordion', 'multiple': True, 'class': 'sud-section'},
            'content': [
                {
                    'component': 'VExpansionPanel',
                    'content': [
                        {
                            'component': 'VExpansionPanelTitle',
                            'content': [
                                {
                                    'component': 'div',
                                    'props': {'class': 'sud-section-head'},
                                    'content': [
                                        {'component': 'VIcon', 'props': {
                                            'size': 'small', 'color': 'primary'}, 'text': icon},
                                        {'component': 'span', 'text': title},
                                        {'component': 'VSpacer'},
                                        {'component': 'VChip', 'props': {
                                            'size': 'x-small', 'variant': 'tonal',
                                            'color': 'primary'}, 'text': count_text},
                                    ]
                                }
                            ]
                        },
                        {'component': 'VExpansionPanelText', 'content': content},
                    ]
                }
            ]
        }

    @staticmethod
    def _table(headers: List[str], rows: List[List[dict]]) -> dict:
        return {
            'component': 'VTable',
            'props': {'hover': True, 'density': 'compact', 'class': 'sud-table'},
            'content': [
                {
                    'component': 'thead',
                    'content': [{
                        'component': 'tr',
                        'content': [{'component': 'th', 'props': {'class': 'text-start'}, 'text': h}
                                    for h in headers]
                    }]
                },
                {
                    'component': 'tbody',
                    'content': [{
                        'component': 'tr',
                        'props': row.get('props') or {},
                        'content': row['cells'],
                    } for row in rows]
                },
            ]
        }

    @staticmethod
    def _td(text: Any, muted: bool = False, title: str = None) -> dict:
        props = {'class': 'text-start'}
        if title:
            props['title'] = title
        return {'component': 'td', 'props': props, 'text': "-" if text in ("", None) else str(text)} \
            if not muted else {'component': 'td', 'props': props, 'text': "-"}

    @staticmethod
    def _clients_no_data_content(no_data: list, errors: list) -> list:
        """无数据站点分节内容：原因表格 / 全部成功的提示。"""
        if not no_data:
            return [{
                'component': 'VAlert', 'props': {
                    'type': 'success', 'variant': 'tonal', 'density': 'compact',
                    'prepend-icon': 'mdi-check-circle-outline',
                    'text': "全部站点均解析到客户端数据"}
            }]
        error_map = {e.get("site"): e.get("error") for e in (errors or [])}
        rows = [{
            'cells': [
                SiteUserDetail._td(SiteUserDetail._site_label(c), title=c.get("domain")),
                SiteUserDetail._td(error_map.get(c.get("site")) or "用户页未解析到客户端数据"),
            ]
        } for c in sorted(no_data, key=SiteUserDetail._site_label)]
        return [
            {
                'component': 'VAlert', 'props': {
                    'type': 'warning', 'variant': 'tonal', 'density': 'compact',
                    'prepend-icon': 'mdi-alert-outline',
                    'text': f"{len(no_data)} 个站点未解析到客户端数据，可能为站点限制（如馒头 API 无 peers 明细）或模板暂不支持"}
            },
            SiteUserDetail._table(["站点", "原因"], rows),
        ]

    def _clients_table(self, clients: list) -> dict:
        rows = []
        for client in sorted(clients, key=lambda c: self._site_label(c)):
            muted = not (client.get("agent") or client.get("ipv4") or client.get("ipv6"))
            ipv6 = client.get("ipv6") or ""
            rows.append({
                'props': {'class': 'sud-muted'} if muted else {},
                'cells': [
                    # 站点列始终显示（空数据行只是弱化，不能没有站点名）
                    self._td(self._site_label(client), title=client.get("domain")),
                    self._td(client.get("agent"), muted=muted),
                    self._td(client.get("ipv4"), muted=muted),
                    self._td(ipv6[:48] + ("…" if len(ipv6) > 48 else ""), muted=muted, title=ipv6),
                    self._td(client.get("port") if client.get("port") is not None else "", muted=muted),
                ]
            })
        return self._table(["站点", "Agent", "IPv4", "IPv6", "端口"], rows)

    def _ip_sections(self, clients: list) -> List[dict]:
        """按 IPv4 / IPv6 聚合：同一 IP 出现在哪些站点（跨站关联视图）。"""
        sections = []
        for field, title, icon in (("ipv4", "IPv4 聚合", "mdi-ip-network"), ("ipv6", "IPv6 聚合", "mdi-ip-network-outline")):
            groups: Dict[str, Dict[str, set]] = {}
            for client in clients:
                ip = str(client.get(field) or "").strip()
                if not ip:
                    continue
                group = groups.setdefault(ip, {"sites": set(), "agents": set()})
                group["sites"].add(self._site_label(client))
                if client.get("agent"):
                    group["agents"].add(str(client["agent"]))
            if not groups:
                continue
            rows = []
            for ip, group in sorted(groups.items(), key=lambda kv: -len(kv[1]["sites"])):
                display_ip = ip[:48] + ("…" if len(ip) > 48 else "")
                # 全量站点 chips，超出显示范围自动换行
                site_chips = [{
                    'component': 'VChip', 'props': {
                        'size': 'x-small', 'variant': 'tonal', 'class': 'mr-1 mb-1',
                        'color': 'warning' if len(group["sites"]) > 1 else 'default'},
                    'text': site} for site in sorted(group["sites"])]
                agent_text = " / ".join(sorted(group["agents"])[:3]) or "-"
                rows.append({
                    'cells': [
                        self._td(display_ip, title=ip),
                        self._td(len(group["sites"])),
                        {'component': 'td', 'props': {'class': 'text-start sud-wrap'},
                         'content': site_chips},
                        self._td(agent_text, title=agent_text),
                    ]
                })
            sections.append(self._page_section(
                title=title, icon=icon, count_text=f"{len(groups)} 个地址",
                content=[self._table(["IP", "站点数", "使用站点", "Agent"], rows)]))
        return sections

    def _torrents_table(self, torrents: list) -> dict:
        rows = []
        for torrent in sorted(torrents, key=lambda t: self._site_label(t))[:300]:
            name = str(torrent.get("name") or "")
            torrent_hash = str(torrent.get("hash") or "")
            tags = torrent.get("tags") or []
            tag_chips = [{
                'component': 'VChip', 'props': {'size': 'x-small', 'variant': 'tonal',
                                                'color': 'success', 'class': 'mr-1'},
                'text': tag} for tag in tags]
            rows.append({
                'cells': [
                    self._td(self._site_label(torrent), title=torrent.get("domain")),
                    self._td(name[:80] + ("…" if len(name) > 80 else ""), title=name),
                    {'component': 'td', 'props': {'class': 'text-start'}, 'content': tag_chips}
                    if tag_chips else self._td(""),
                    self._td(self._fmt_size(torrent.get("size"))),
                    self._td(torrent_hash[:16] + "…" if torrent_hash else "-", title=torrent_hash or None),
                ]
            })
        return self._table(["站点", "种子名称", "促销", "大小", "hash"], rows)

    @staticmethod
    def _fmt_size(size: Any) -> str:
        try:
            value = float(size or 0)
        except (TypeError, ValueError):
            return "-"
        for unit in ("TB", "GB", "MB", "KB"):
            factor = 1024 ** ({"TB": 4, "GB": 3, "MB": 2, "KB": 1}[unit])
            if value >= factor:
                return f"{value / factor:.2f} {unit}"
        return f"{int(value)} B"

    # ------------------------------------------------------------------ 采集

    def collect(self, sites: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        采集入口：定时任务与插件 API 共用同一逻辑（互斥，防止并发重复采集）。

        :param sites: 站点域名列表；None/空使用配置的采集站点（配置也空则全部）
        :return: {"update_time", "clients", "torrents", "errors"}
        """
        if not self._collect_lock.acquire(blocking=False):
            logger.warning("站点用户详情采集：已有采集任务在进行中，跳过本次触发")
            last = self.get_data("snapshot")
            if isinstance(last, dict) and last:
                return last
            return {
                "update_time": int(time.time()), "clients": [], "torrents": [],
                "errors": [{"site": "-", "domain": "", "error": "已有采集任务在进行中"}],
            }
        try:
            return self.__do_collect(sites)
        finally:
            self._collect_lock.release()

    def __do_collect(self, sites: Optional[List[str]] = None) -> Dict[str, Any]:
        """实际采集流程（由 collect 持锁调用）。"""
        logger.info("开始采集 PT 站用户详情数据 ...")
        site_infos = self._resolve_sites(sites)
        if not site_infos:
            return {
                "update_time": int(time.time()),
                "clients": [], "torrents": [],
                "errors": [{"site": "-", "domain": "", "error": "没有可采集的站点"}],
            }

        # 下载器种子池：normalize(种子名) -> infohash
        hash_pool = self._build_downloader_pool() if self._use_downloader_hash else {}
        uid_map = self.get_data("uid_map") or {}

        results = []
        with ThreadPoolExecutor(max_workers=max(1, self._concurrency or 3)) as executor:
            futures = {
                executor.submit(self._collect_site, site, hash_pool, uid_map): site
                for site in site_infos
            }
            for future in as_completed(futures):
                site = futures[future]
                try:
                    results.append(future.result())
                except Exception as err:  # 兜底：线程内不应抛出，保险起见
                    logger.error(f"【{site.get('name')}】采集线程异常: {err}\n{traceback.format_exc()}")
                    results.append((site, [], [], f"线程异常: {err}", None))

        clients: List[Dict[str, Any]] = []
        torrents: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for site, site_clients, site_torrents, error, uid in results:
            domain = site.get("domain")
            site_name = site.get("name") or domain or "未知"
            if uid and domain:
                uid_map[domain] = uid
            if error:
                errors.append({"site": site_name, "domain": domain, "error": error})
            if not site_clients:
                # 需求约定：每站至少一条，解析不到给全空值
                site_clients = [{"agent": "", "ipv4": "", "ipv6": "", "port": None}]
            for client in site_clients:
                client["site"] = site_name
                client["domain"] = domain
            for torrent in site_torrents:
                torrent["site"] = site_name
                torrent["domain"] = domain
            clients.extend(site_clients)
            torrents.extend(site_torrents)

        snapshot = {
            "update_time": int(time.time()),
            "clients": clients,
            "torrents": torrents,
            "errors": errors,
        }
        try:
            self.save_data("snapshot", snapshot)
            self.save_data("uid_map", uid_map)
        except Exception as err:
            # 快照保存失败不影响本次结果返回（如服务停机过程中的收尾竞态）
            logger.error(f"站点用户详情采集：快照保存失败: {err}")
        logger.info(f"站点用户详情采集完成：{len(clients)} 条客户端、"
                    f"{len(torrents)} 个下载中种子、{len(errors)} 个站点失败")
        if self._notify:
            self.__notify(snapshot)
        return snapshot

    def _collect_site(self, site: Dict[str, Any], hash_pool: Dict[str, str],
                      uid_map: Dict[str, str]):
        """
        采集单个站点：解析适配器 → uid → 客户端列表 → 下载中种子 → hash 回填。

        :return: (site, clients, torrents, error, uid)
        """
        site_name = site.get("name")
        clients: List[Dict[str, Any]] = []
        torrents: List[Dict[str, Any]] = []
        error = None
        uid = None
        try:
            adapter = get_adapter(site, interval=self._request_interval, uid_map=uid_map)
            if not adapter.has_credential():
                raise AdapterError("站点未配置 Cookie/APIKEY")
            uid = adapter.get_uid()
            if not uid:
                raise AdapterError("未能解析用户 ID")
            clients = adapter.parse_clients(uid) or []
            torrents = adapter.parse_leeching(uid) or []
            # hash 回填：下载器名匹配 → 详情页兜底（限额、非浏览器仿真站）
            detail_used = 0
            for torrent in torrents:
                if not torrent.get("hash"):
                    torrent["hash"] = hash_pool.get(self._norm_name(torrent.get("name"))) or ""
                if not torrent["hash"] and self._hash_from_detail and not adapter.render \
                        and detail_used < self._detail_limit and torrent.get("id"):
                    detail_used += 1
                    torrent["hash"] = adapter.parse_detail_hash(str(torrent["id"]))
        except AdapterError as err:
            error = str(err)
            logger.warning(f"【{site_name}】采集失败: {error}")
        except Exception as err:
            error = f"{type(err).__name__}: {err}"
            logger.error(f"【{site_name}】采集异常: {error}\n{traceback.format_exc()}")
        return site, clients, torrents, error, uid

    def _resolve_sites(self, sites: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """解析目标站点列表：内置私站 + 自定义站点，补齐/规范化 domain。

        注意：indexer 的 domain 字段部分站点带协议前缀（如 https://xxx.org/），
        统一经 get_url_domain 归一化为注册域，保证 API 过滤与输出一致。
        """
        builtin_sites = [dict(site) for site in SitesHelper().get_indexers()
                         if not site.get("public")]
        all_sites = builtin_sites + self.__custom_sites()
        for site in all_sites:
            domain = site.get("domain") or site.get("url")
            site["domain"] = StringUtils.get_url_domain(domain) or str(domain or "").lower()
        if sites:
            wanted = {self._norm_domain(s) for s in sites if str(s).strip()}
            return [site for site in all_sites if site["domain"] in wanted]
        if self._sites:
            id_set = {str(site_id) for site_id in self._sites}
            return [site for site in all_sites if str(site.get("id")) in id_set]
        return all_sites

    def _build_downloader_pool(self) -> Dict[str, str]:
        """遍历所有下载器构建 normalize(种子名) -> infohash 映射。"""
        pool: Dict[str, str] = {}
        try:
            services = DownloaderHelper().get_services() or {}
        except Exception as err:
            logger.warning(f"获取下载器失败，跳过 hash 匹配: {err}")
            return pool
        for name, service in services.items():
            try:
                instance = getattr(service, "instance", None)
                if instance is None or (hasattr(instance, "is_inactive") and instance.is_inactive()):
                    continue
                torrents, error = instance.get_torrents()
                if error or not torrents:
                    continue
                for torrent in torrents:
                    torrent_name = torrent.get("name") if hasattr(torrent, "get") \
                        else getattr(torrent, "name", None)
                    torrent_hash = (torrent.get("hash") if hasattr(torrent, "get")
                                    else getattr(torrent, "hashString", "")) or ""
                    if torrent_name and torrent_hash:
                        pool[self._norm_name(torrent_name)] = str(torrent_hash).lower()
            except Exception as err:
                logger.warning(f"下载器【{name}】获取种子列表失败: {err}")
        return pool

    @staticmethod
    def _norm_name(name: Any) -> str:
        """种子名归一化（精确匹配用）。"""
        return str(name or "").strip().lower()

    @staticmethod
    def _norm_domain(domain: Any) -> str:
        """域名归一化：带协议/路径的输入提取注册域。"""
        text = str(domain or "").strip().lower()
        if not text:
            return ""
        if "://" in text or "/" in text:
            return StringUtils.get_url_domain(text)
        return text

    def __custom_sites(self) -> List[Any]:
        """读取已启用的自定义站点插件配置。"""
        custom_sites = []
        custom_sites_config = self.get_config("CustomSites")
        if custom_sites_config and custom_sites_config.get("enabled"):
            custom_sites = custom_sites_config.get("sites") or []
        return custom_sites

    def __notify(self, snapshot: Dict[str, Any]):
        """发送采集结果汇总通知。"""
        try:
            site_count = len({c.get("site") for c in snapshot.get("clients", [])})
            errors = snapshot.get("errors") or []
            lines = [
                f"站点数：{site_count}",
                f"客户端记录：{len(snapshot.get('clients', []))} 条",
                f"下载中种子：{len(snapshot.get('torrents', []))} 个",
            ]
            if errors:
                lines.append(f"失败站点：{len(errors)} 个")
                lines.extend(f"  - {e.get('site')}: {e.get('error')}" for e in errors[:10])
            self.post_message(title="【站点用户详情采集】", text="\n".join(lines))
        except Exception as err:
            logger.error(f"发送采集通知失败: {err}")

    def __update_config(self):
        """保存插件配置。"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cron": self._cron,
            "sites": self._sites,
            "use_downloader_hash": self._use_downloader_hash,
            "hash_from_detail": self._hash_from_detail,
            "detail_limit": self._detail_limit,
            "request_interval": self._request_interval,
            "concurrency": self._concurrency,
        })

    # ------------------------------------------------------------------ 插件 API

    def api_collect(self, sites: str = "") -> schemas.Response:
        """触发一次采集（视同一次定时调用）并返回结果。"""
        site_list = [s for s in str(sites or "").split(",") if s.strip()] or None
        try:
            result = self.collect(site_list)
        except Exception as err:
            logger.error(f"采集接口执行失败: {err}\n{traceback.format_exc()}")
            return schemas.Response(success=False, message=f"采集执行失败: {err}")
        message = (f"采集完成：{len(result.get('clients', []))} 条客户端、"
                   f"{len(result.get('torrents', []))} 个下载中种子、"
                   f"{len(result.get('errors', []))} 个站点失败")
        return schemas.Response(success=True, message=message, data=result)

    def api_snapshot(self, sites: str = "") -> schemas.Response:
        """读取最近一次采集快照，支持按站点域名过滤。"""
        snapshot = self.get_data("snapshot")
        if not snapshot:
            return schemas.Response(success=False, message="暂无采集数据，请先执行一次采集")
        wanted = [s for s in str(sites or "").split(",") if s.strip()]
        if wanted:
            domains = {self._norm_domain(s) for s in wanted}
            snapshot = {
                "update_time": snapshot.get("update_time"),
                "clients": [c for c in snapshot.get("clients", []) if c.get("domain") in domains],
                "torrents": [t for t in snapshot.get("torrents", []) if t.get("domain") in domains],
                "errors": [e for e in snapshot.get("errors", []) if e.get("domain") in domains],
            }
        return schemas.Response(success=True, data=snapshot)
