# -*- coding: utf-8 -*-
"""PT 站用户详情采集插件。

定时采集每个 PT 站用户详情页的两类数据：
1. BT 客户端列表（agent / ipv4 / ipv6 / port），每站至少一条，解析不到给全空值条目；
2. 下载中种子列表（id / hash / name / 促销标签 / size），hash 优先在下载器种子列表
   按种子名匹配回填，种子详情页解析兜底，均失败留空。

数据以两个平铺列表返回（每项含 site/domain 字段），聚合分组由前端/三方自行完成。
插件暴露两个 API：
- GET /api/v1/plugin/SiteUserDetail/collect?apikey=<TOKEN>&sites=<域名,逗号分隔>
  触发一次采集（与定时任务共用 collect 逻辑）并返回结果；
- GET /api/v1/plugin/SiteUserDetail/snapshot?apikey=<TOKEN>&sites=<...>
  读取最近一次采集快照（不触发采集）。

站点适配采用「通用架构采集 + 站点适配器」架构，详见 adapters/ 目录。
"""

import time
import traceback
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
    """PT 站用户详情采集：BT 客户端 + 下载中种子 + 插件 API。"""

    # 插件名称
    plugin_name = "PT站用户详情采集"
    # 插件描述
    plugin_desc = "定时采集 PT 站用户详情页的 BT 客户端与下载中种子数据，并通过插件 API 供三方调用。"
    # 插件图标
    plugin_icon = "siteuserdetail.png"
    # 插件版本
    plugin_version = "1.0.0"
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
                logger.info("PT站用户详情采集服务启动，立即运行一次")
                self._scheduler.add_job(
                    func=self.collect, trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="PT站用户详情采集")
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
            "name": "PT站用户详情采集服务",
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
        return []

    # ------------------------------------------------------------------ 采集

    def collect(self, sites: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        采集入口：定时任务与插件 API 共用同一逻辑。

        :param sites: 站点域名列表；None/空使用配置的采集站点（配置也空则全部）
        :return: {"update_time", "clients", "torrents", "errors"}
        """
        logger.info("开始采集 PT 站用户详情数据 ...")
        site_infos = self._resolve_sites(sites)
        if not site_infos:
            snapshot = {
                "update_time": int(time.time()),
                "clients": [], "torrents": [],
                "errors": [{"site": "-", "domain": "", "error": "没有可采集的站点"}],
            }
            return snapshot

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
            site_name = site.get("name")
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
        self.save_data("snapshot", snapshot)
        self.save_data("uid_map", uid_map)
        logger.info(f"PT站用户详情采集完成：{len(clients)} 条客户端、"
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
            self.post_message(title="【PT站用户详情采集】", text="\n".join(lines))
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
