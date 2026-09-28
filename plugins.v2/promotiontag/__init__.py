import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app.chain.torrents import TorrentsChain
from app.core.config import settings
from app.core.context import Context
from app.core.event import eventmanager, Event
from app.helper.downloader import DownloaderHelper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ServiceInfo, NotificationType
from app.schemas.types import EventType
from app.utils.string import StringUtils


class PromotionTag(_PluginBase):
    # 插件名称
    plugin_name = "促销标签"
    # 插件描述
    plugin_desc = "自动为下载任务打上 PT 站点促销标签（免费/2X免费/50%/2X等），并在限时促销到期后自动移除标签。"
    # 插件图标
    plugin_icon = "seed.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "devin"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "PromotionTag_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1
    # 日志前缀
    LOG_TAG = "[PromotionTag] "

    # 退出事件
    _event = threading.Event()
    # 一次性任务调度器
    _scheduler = None

    # 以下为配置项
    _enabled = False
    _onlyonce = False
    _notify = False
    _downloaders = []
    _dl_hours = 3          # 未完成种子刷新间隔（小时）
    _cmp_hours = 24        # 已完成种子刷新间隔（小时）
    _fallback_enabled = True
    _fallback_hours = 12   # 兜底扫描间隔（小时）
    _tz_offset = 0         # 站点时间相对本地时间的偏移（分钟），站点比本地快为正
    _tag_prefix = ""       # 标签前缀，便于与其它插件标签区分

    def init_plugin(self, config: dict = None):
        # 停止已有的一次性任务
        self.stop_service()

        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._notify = bool(config.get("notify"))
            self._downloaders = config.get("downloaders") or []
            self._dl_hours = self._to_int(config.get("dl_hours"), 3)
            self._cmp_hours = self._to_int(config.get("cmp_hours"), 24)
            self._fallback_enabled = bool(config.get("fallback_enabled", True))
            self._fallback_hours = self._to_int(config.get("fallback_hours"), 12)
            self._tz_offset = self._to_int(config.get("tz_offset"), 0)
            self._tag_prefix = config.get("tag_prefix") or ""

        # 立即执行一次：触发一次兜底扫描补全历史种子
        if self._enabled and self._onlyonce:
            try:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(
                    func=self._fallback_scan,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                )
                self._onlyonce = False
                self.update_config(self._current_config())
                if self._scheduler.get_jobs():
                    self._scheduler.start()
            except Exception as e:
                logger.error(f"{self.LOG_TAG}启动一次性任务失败: {e}")

    @staticmethod
    def _to_int(s: Any, default: int) -> int:
        try:
            return int(s)
        except (ValueError, TypeError):
            return default

    def _current_config(self) -> Dict[str, Any]:
        """构造当前配置字典（用于 update_config 回写）"""
        return {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "downloaders": self._downloaders,
            "dl_hours": self._dl_hours,
            "cmp_hours": self._cmp_hours,
            "fallback_enabled": self._fallback_enabled,
            "fallback_hours": self._fallback_hours,
            "tz_offset": self._tz_offset,
            "tag_prefix": self._tag_prefix,
        }

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """获取已连接的下载器服务映射"""
        if not self._downloaders:
            return None
        services = DownloaderHelper().get_services(name_filters=self._downloaders)
        if not services:
            return None
        active = {}
        for name, info in services.items():
            try:
                if info.instance.is_inactive():
                    logger.warning(f"{self.LOG_TAG}下载器 {name} 未连接，跳过")
                else:
                    active[name] = info
            except Exception:
                active[name] = info
        return active or None

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_page(self) -> List[dict]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册定时服务
        """
        if not self._enabled:
            return []
        tasks = [
            {
                "id": "PromotionTagDownloading",
                "name": "刷新未完成种子促销标签",
                "trigger": "interval",
                "func": self._refresh_downloading,
                "kwargs": {"hours": max(1, self._dl_hours)}
            },
            {
                "id": "PromotionTagCompleted",
                "name": "刷新已完成种子促销标签",
                "trigger": "interval",
                "func": self._refresh_completed,
                "kwargs": {"hours": max(1, self._cmp_hours)}
            },
        ]
        if self._fallback_enabled:
            tasks.append({
                "id": "PromotionTagFallback",
                "name": "兜底扫描补全促销标签",
                "trigger": "interval",
                "func": self._fallback_scan,
                "kwargs": {"hours": max(1, self._fallback_hours)}
            })
        return tasks

    @eventmanager.register(EventType.DownloadAdded)
    def download_added(self, event: Event):
        """
        添加下载事件：立即从站点促销信息打标签并缓存
        """
        if not self.get_state() or not event.event_data:
            return
        try:
            downloader = event.event_data.get("downloader")
            service = (self.service_infos or {}).get(downloader)
            if not service:
                return
            _hash = event.event_data.get("hash")
            context: Context = event.event_data.get("context")
            if not _hash or not context:
                return
            ti = context.torrent_info
            if not ti:
                return
            dl = getattr(ti, "downloadvolumefactor", None)
            ul = getattr(ti, "uploadvolumefactor", None)
            freedate = getattr(ti, "freedate", None)
            label = self._promo_label(dl, ul)
            if not label:
                return  # 非促销种子，不打标签
            self._apply_tag(service=service, _hash=_hash, dl=dl, ul=ul,
                            freedate=freedate, label=label, source="event")
        except Exception as e:
            logger.error(f"{self.LOG_TAG}处理下载添加事件失败: {e}")

    # ==================== 定时刷新 ====================

    def _refresh_downloading(self):
        """刷新未完成种子：检查限时促销是否到期，到期则移除标签"""
        if not self.get_state():
            return
        services = self.service_infos
        if not services:
            return
        all_actions: List[str] = []
        for service in services.values():
            try:
                torrents = service.instance.get_downloading_torrents() or []
                all_actions += self._refresh(torrents, service)
            except Exception as e:
                logger.error(f"{self.LOG_TAG}刷新未完成种子失败 {service.name}: {e}")
        self._notify_actions("未完成种子促销标签刷新", all_actions)

    def _refresh_completed(self):
        """刷新已完成种子：检查限时促销是否到期，到期则移除标签"""
        if not self.get_state():
            return
        services = self.service_infos
        if not services:
            return
        all_actions: List[str] = []
        for service in services.values():
            try:
                torrents = service.instance.get_completed_torrents() or []
                all_actions += self._refresh(torrents, service)
            except Exception as e:
                logger.error(f"{self.LOG_TAG}刷新已完成种子失败 {service.name}: {e}")
        self._notify_actions("已完成种子促销标签刷新", all_actions)

    def _refresh(self, torrents: List[Any], service: ServiceInfo) -> List[str]:
        """
        遍历种子集合，对处于促销中（state=promo）的记录检查是否到期，
        到期则移除促销标签并把记录置为 expired
        """
        actions: List[str] = []
        if not torrents:
            return actions
        records = self._load_records()
        changed = False
        for torrent in torrents:
            _hash = self._get_hash(torrent, service.type)
            if not _hash:
                continue
            rec = records.get(f"{service.name}:{_hash}")
            if not rec or rec.get("state") != "promo":
                continue
            if self._is_expired(rec.get("freedate")):
                label = rec.get("label")
                if label and self._remove_torrents_tag(service, _hash, [label]):
                    rec["state"] = "expired"
                    changed = True
                    actions.append(f"移除促销标签[{label}]: {_hash[:12]}")
                    logger.info(f"{self.LOG_TAG}促销已到期，移除标签 [{label}]: {_hash}")
        if changed:
            self._save_records(records)
        return actions

    # ==================== 兜底扫描（覆盖非 MoviePilot 触发的下载） ====================

    def _fallback_scan(self):
        """
        全量扫描下载器种子，对未被事件覆盖、缺少促销标签的种子，
        通过站点种子列表（TorrentsChain.browse）按 大小 匹配反查促销信息并补标签。
        同时清理已不在下载器中的孤儿记录。
        """
        if not self.get_state():
            return
        services = self.service_infos
        if not services:
            return
        # 站点 domain 索引：[(注册域, 站点domain)]
        try:
            indexers = SitesHelper().get_indexers() or []
        except Exception:
            indexers = []
        site_domains: List[Tuple[str, str]] = []
        for ix in indexers:
            d = ix.get("domain")
            if not d:
                continue
            reg = StringUtils.get_url_domain(d)
            if reg:
                site_domains.append((reg, d))

        records = self._load_records()  # 本地工作集，避免与 _apply_tag 各自落盘互相覆盖
        all_current = set()  # (downloader_name, hash)，用于孤儿清理
        enumerated = set()  # 本轮成功完成全量枚举的下载器，孤儿清理仅限此范围
        actions: List[str] = []

        # 路径一：按下载历史精确匹配（MoviePilot 下载的种子，download_hash == qB hash）
        # 准确可靠，不依赖 browse；但 downloadhistory 不存促销信息，需在路径二补全
        dh_map = self._load_downloadhistory_map()
        for service in services.values():
            try:
                torrents, error = service.instance.get_torrents()
            except Exception as e:
                logger.error(f"{self.LOG_TAG}兜底扫描获取种子失败 {service.name}: {e}")
                continue
            if error or not torrents:
                continue
            enumerated.add(service.name)

            # 按站点分组：需要补标签的种子（无促销标签 或 记录缺失/已过期）
            need: Dict[str, List[Tuple[str, Any]]] = {}
            for t in torrents:
                _hash = self._get_hash(t, service.type)
                if not _hash:
                    continue
                all_current.add((service.name, _hash))
                rec = records.get(f"{service.name}:{_hash}")
                if rec and rec.get("state") == "promo":
                    continue  # 已在管理中
                # 下载历史命中的种子登记站点范围（供路径二用），若无站点再按 tracker 识别
                dh = dh_map.get(_hash)
                domain = None
                if dh and dh.get("site"):
                    domain = self._site_name_to_domain(dh.get("site"), site_domains)
                    if not domain:
                        domain = self._identify_site(t, service.type, site_domains)
                else:
                    domain = self._identify_site(t, service.type, site_domains)
                if domain:
                    need.setdefault(domain, []).append((_hash, t))

            # 路径二：每个站点只抓取一次，建立 size -> TorrentInfo 索引，反查促销补标签
            browse_cache: Dict[str, Dict[int, Any]] = {}
            matched = 0
            for domain, items in need.items():
                if domain not in browse_cache:
                    try:
                        # browse 需纯域名(URL 格式匹配不到站点 cookie 配置)
                        browse_domain = StringUtils.get_url_domain(domain) or domain
                        site_torrents = TorrentsChain().browse(domain=browse_domain) or []
                        idx: Dict[int, Any] = {}
                        for st in site_torrents:
                            sz = getattr(st, "size", None)
                            if sz:
                                try:
                                    idx.setdefault(int(sz), st)
                                except (TypeError, ValueError):
                                    continue
                        browse_cache[domain] = idx
                    except Exception as e:
                        logger.warning(f"{self.LOG_TAG}兜底抓取站点 {domain} 失败: {e}")
                        browse_cache[domain] = {}
                idx = browse_cache.get(domain, {})
                for _hash, torrent in items:
                    target = self._match_torrent(torrent, service.type, idx)
                    if not target:
                        continue
                    dl = getattr(target, "downloadvolumefactor", None)
                    ul = getattr(target, "uploadvolumefactor", None)
                    freedate = getattr(target, "freedate", None)
                    label = self._promo_label(dl, ul)
                    if not label:
                        continue
                    if self._apply_tag(service=service, _hash=_hash, dl=dl, ul=ul,
                                       freedate=freedate, label=label, source="fallback",
                                       records=records):
                        matched += 1
                        actions.append(f"补全促销标签[{self._format_label(label)}]: {_hash[:12]}")
            if matched:
                logger.info(f"{self.LOG_TAG}兜底扫描 {service.name} 补全 {matched} 个种子促销标签")

        # 孤儿记录清理：仅针对本轮成功枚举的下载器，记录指向的种子已不存在则移除
        orphans = [key for key, r in records.items()
                   if r.get("downloader") in enumerated
                   and (r.get("downloader"), r.get("hash")) not in all_current]
        for key in orphans:
            records.pop(key, None)
        # 统一保存（含本轮补标签写入 + 孤儿清理）
        self._save_records(records)
        if orphans:
            logger.info(f"{self.LOG_TAG}清理孤儿记录 {len(orphans)} 条")
        self._notify_actions("兜底扫描补全促销标签", actions)

    # ==================== 标签读写 ====================

    def _apply_tag(self, service: ServiceInfo, _hash: str,
                   dl: Any, ul: Any, freedate: Optional[str],
                   label: str, source: str,
                   records: Optional[Dict[str, dict]] = None) -> bool:
        """
        打促销标签并写入记录。
        records 非 None 时写入该工作集但不落盘（由调用方统一保存，避免覆盖）；
        records 为 None 时（事件触发等单点场景）自行加载并保存。
        """
        full_label = self._format_label(label)
        if not self._set_torrents_tag(service, _hash, [full_label]):
            return False
        own = records is None
        if own:
            records = self._load_records()
        key = f"{service.name}:{_hash}"
        records[key] = {
            "downloader": service.name,
            "hash": _hash,
            "dl_factor": dl,
            "ul_factor": ul,
            "freedate": freedate,
            "label": full_label,
            "state": "promo",
            "source": source,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if own:
            self._save_records(records)
        logger.info(f"{self.LOG_TAG}{service.name} 打{full_label}标签: {_hash}")
        return True

    def _set_torrents_tag(self, service: ServiceInfo, _hash: str, tags: List[str]) -> bool:
        """添加标签（qB / transmission 分支）"""
        try:
            obj = service.instance
            if service.type == "qbittorrent":
                obj.set_torrents_tag(ids=_hash, tags=tags)
            else:
                # transmission 为合并式设置，需先取出原有标签再合并
                torrents, error = obj.get_torrents(ids=_hash)
                existing = []
                if torrents and not error:
                    existing = getattr(torrents[0], "labels", None) or []
                obj.set_torrent_tag(ids=_hash, tags=list(set(existing) | set(tags)))
            return True
        except Exception as e:
            logger.error(f"{self.LOG_TAG}打标签失败 {_hash}: {e}")
            return False

    def _remove_torrents_tag(self, service: ServiceInfo, _hash: str, tags: List[str]) -> bool:
        """移除标签（qB / transmission 分支）"""
        try:
            obj = service.instance
            if service.type == "qbittorrent":
                obj.remove_torrents_tag(ids=_hash, tag=tags)
            else:
                torrents, error = obj.get_torrents(ids=_hash)
                existing = []
                if torrents and not error:
                    existing = getattr(torrents[0], "labels", None) or []
                obj.set_torrent_tag(ids=_hash, tags=list(set(existing) - set(tags)))
            return True
        except Exception as e:
            logger.error(f"{self.LOG_TAG}移除标签失败 {_hash}: {e}")
            return False

    # ==================== 促销判定 ====================

    def _promo_label(self, dl: Any, ul: Any) -> Optional[str]:
        """
        根据下载/上传因子返回标签文案，无促销返回 None
        dl: 0=免费, 0<dl<1=折扣, >=1=原价
        ul: >=2=双倍上传
        """
        try:
            dl_f = float(dl) if dl is not None else 1.0
            ul_f = float(ul) if ul is not None else 1.0
        except (TypeError, ValueError):
            return None
        is_free = dl_f == 0
        is_discount = 0 < dl_f < 1
        is_2x = ul_f >= 2
        if is_free and is_2x:
            return "2X免费"
        if is_free:
            return "免费"
        if is_discount and is_2x:
            return "2X 50%"
        if is_discount:
            return "50%"
        if is_2x:
            return "2X"
        return None

    def _format_label(self, base: str) -> str:
        return f"{self._tag_prefix}{base}" if self._tag_prefix else base

    def _is_expired(self, freedate: Optional[str]) -> bool:
        """
        判断限时促销是否已到期。freedate 为空（永久促销或站点未返回）时不判定为过期。
        tz_offset: 站点时间相对本地时间快的分钟数，用于校正 freedate 与 now 的比较。
        """
        if not freedate:
            return False
        try:
            fs = str(freedate).replace("T", " ").replace("Z", "")
            fd = datetime.strptime(fs, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return False
        now = datetime.now()
        delta_minutes = (fd - now).total_seconds() // 60 - self._tz_offset
        return delta_minutes <= 0

    # ==================== 站点 / 种子匹配 ====================

    def _load_downloadhistory_map(self) -> Dict[str, Dict[str, Any]]:
        """
        从下载历史构建 qB hash -> {site} 映射。
        downloadhistory.download_hash 就是 qB 种子 hash（实测 85/484 在 qB 命中），
        但 downloadhistory 不存促销信息，这里只提供"该种子属于哪个站点"的范围。
        """
        result: Dict[str, Dict[str, Any]] = {}
        try:
            from app.db import SessionFactory
            from sqlalchemy import text
            with SessionFactory() as s:
                for row in s.execute(text(
                        "SELECT download_hash, torrent_site, torrent_name FROM downloadhistory "
                        "WHERE download_hash IS NOT NULL AND download_hash != ''")):
                    result[row[0]] = {"site": row[1], "name": row[2]}
        except Exception as e:
            logger.warning(f"{self.LOG_TAG}读取下载历史失败: {e}")
        return result

    def _site_name_to_domain(self, site_name: Optional[str],
                             site_domains: List[Tuple[str, str]]) -> Optional[str]:
        """
        把下载历史里的站点名（如"学校/馒头/财神"）映射到站点 domain。
        site_domains 是 [(注册域, domain)]，这里再借助 indexer 的 name 匹配。
        """
        if not site_name:
            return None
        try:
            from app.helper.sites import SitesHelper
            for ix in (SitesHelper().get_indexers() or []):
                if ix.get("name") == site_name:
                    return ix.get("domain")
        except Exception:
            pass
        # 退化：站点名里可能含 domain 片段，做子串匹配
        name = str(site_name).lower()
        for reg, domain in site_domains:
            if name in domain.lower() or domain.lower() in name:
                return domain
        return None

    def _identify_site(self, torrent: Any, dl_type: str,
                       site_domains: List[Tuple[str, str]]) -> Optional[str]:
        """从种子 trackers 反查所属站点 domain（用于 browse）"""
        trackers = self._get_trackers(torrent, dl_type)
        if not trackers:
            return None
        tracker_regs = set()
        for url in trackers:
            try:
                reg = StringUtils.get_url_domain(url)
                if reg:
                    tracker_regs.add(reg)
            except Exception:
                continue
        if not tracker_regs:
            return None
        for site_reg, site_domain in site_domains:
            for tr in tracker_regs:
                if tr == site_reg or tr.endswith("." + site_reg) or site_reg.endswith("." + tr):
                    return site_domain
        return None

    @staticmethod
    def _match_torrent(torrent: Any, dl_type: str, idx: Dict[int, Any]) -> Optional[Any]:
        """按种子大小精确匹配站点种子（PT 种子大小唯一性较强）"""
        try:
            size = torrent.get("size") if dl_type == "qbittorrent" else getattr(torrent, "total_size", None)
            if size is None:
                return None
            return idx.get(int(size))
        except Exception:
            return None

    # ==================== 记录持久化 ====================

    def _load_records(self) -> Dict[str, dict]:
        data = self.get_data("records")
        return data if isinstance(data, dict) else {}

    def _save_records(self, records: Dict[str, dict]):
        self.save_data("records", records)

    def _notify_actions(self, title: str, actions: List[str]):
        """有动作时发送汇总通知"""
        if not self._notify or not actions:
            return
        try:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"{self.plugin_name}-{title}",
                text="\n".join(actions[:50]) + (f"\n...共 {len(actions)} 条" if len(actions) > 50 else "")
            )
        except Exception as e:
            logger.error(f"{self.LOG_TAG}发送通知失败: {e}")

    # ==================== 下载器对象适配（qB / transmission） ====================

    @staticmethod
    def _get_hash(torrent: Any, dl_type: str) -> Optional[str]:
        try:
            return torrent.get("hash") if dl_type == "qbittorrent" else torrent.hashString
        except Exception:
            return None

    @staticmethod
    def _get_trackers(torrent: Any, dl_type: str) -> List[str]:
        try:
            if dl_type == "qbittorrent":
                tracker = torrent.get("tracker")
                return [tracker] if tracker else []
            else:
                return [t.announce for t in (torrent.trackers or [])
                        if getattr(t, "tier", -1) >= 0 and getattr(t, "announce", None)]
        except Exception:
            return []

    # ==================== 配置表单 ====================

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        downloader_items = [
            {"title": cfg.name, "value": cfg.name}
            for cfg in (DownloaderHelper().get_configs() or {}).values()
        ]
        return [
            [{
                'component': 'VForm',
                'content': [
                    # 启用 / 立即执行 / 通知
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}
                            ]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                {'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即执行一次'}}
                            ]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [
                                {'component': 'VSwitch', 'props': {'model': 'notify', 'label': '发送通知'}}
                            ]},
                        ]
                    },
                    # 下载器多选
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12}, 'content': [{
                                'component': 'VSelect',
                                'props': {
                                    'multiple': True, 'chips': True, 'clearable': True,
                                    'model': 'downloaders', 'label': '生效下载器',
                                    'items': downloader_items
                                }
                            }]}
                        ]
                    },
                    # 刷新间隔
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{
                                'component': 'VTextField',
                                'props': {'model': 'dl_hours', 'label': '未完成种子刷新间隔(小时)', 'placeholder': '3'}
                            }]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{
                                'component': 'VTextField',
                                'props': {'model': 'cmp_hours', 'label': '已完成种子刷新间隔(小时)', 'placeholder': '24'}
                            }]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{
                                'component': 'VTextField',
                                'props': {'model': 'tz_offset', 'label': '时区偏移(分钟)', 'placeholder': '0'}
                            }]},
                        ]
                    },
                    # 兜底扫描
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{
                                'component': 'VSwitch',
                                'props': {'model': 'fallback_enabled', 'label': '启用兜底扫描'}
                            }]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{
                                'component': 'VTextField',
                                'props': {'model': 'fallback_hours', 'label': '兜底扫描间隔(小时)', 'placeholder': '12'}
                            }]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{
                                'component': 'VTextField',
                                'props': {'model': 'tag_prefix', 'label': '标签前缀(可选)', 'placeholder': '如 PT'}
                            }]},
                        ]
                    },
                    # 说明
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12}, 'content': [{
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info', 'variant': 'tonal',
                                    'text': '下载添加时从站点促销信息打标签（免费/2X免费/50%/2X 等）；'
                                            '限时促销到期后自动移除标签；兜底扫描会从站点种子列表反查促销，'
                                            '覆盖手动添加等未被事件触发的种子。时区偏移为站点时间相对本地快多少分钟。'
                                }
                            }]}
                        ]
                    }
                ]
            }],
            # 默认值
            {
                "enabled": False,
                "onlyonce": False,
                "notify": False,
                "downloaders": [],
                "dl_hours": "3",
                "cmp_hours": "24",
                "tz_offset": "0",
                "fallback_enabled": True,
                "fallback_hours": "12",
                "tag_prefix": ""
            }
        ]

    def stop_service(self):
        """停止一次性任务调度器"""
        try:
            if self._scheduler:
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.error(f"{self.LOG_TAG}stop_service 失败: {e}")
