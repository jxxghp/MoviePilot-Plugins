"""MoviePilot V2 PT 数据统计插件。"""

from __future__ import annotations

import hmac
import threading
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas import NotificationType
from app.schemas.types import EventType
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .api_models import (
    CookieCloudActionResponse,
    CookieCloudEncryptedData,
    CookieCloudUpdateData,
    HourlyTrafficResponse,
    HistoryResponse,
    OverviewResponse,
    RetirementProgressData,
    SettingsData,
    SettingsResponse,
    SiteSnapshotData,
    SummaryData,
    SyncResponse,
    TrafficDistributionItem,
    TrafficDistributionResponse,
    TwelveProgressData,
)
from .core import (
    DEFAULT_RETIREMENT_RULES,
    MTEAM_RETIREMENT_RULE,
    as_float,
    as_int,
    as_text,
    build_hourly_traffic,
    build_retirement_progress,
    build_twelve_progress,
    career_days,
    compute_daily_delta,
    earliest_join_date,
    estimate_bonus_hourly,
    format_bytes,
    overall_ratio,
)
from .database import LocalDatabaseHandle
from .ptd_cookiecloud import PTDCookieCloudError, match_metrics, parse_backup_response
from .repository import SnapshotRepository


class PTDataStatistics(_PluginBase):
    """统计并展示 MoviePilot 已采集的 PT 站点账号数据。"""

    plugin_name = "PT数据统计"
    plugin_desc = "统计 PT 站点累计与每日上传下载，提供历史、养老进度和通知。"
    plugin_icon = "https://raw.githubusercontent.com/changzhanghs/MoviePilot-Plugins/main/icons/ptdatastatistics.png"
    plugin_version = "2.1.8"
    plugin_author = "changzhanghs"
    author_url = "https://github.com/changzhanghs"
    plugin_config_prefix = "ptdatastatistics_"
    plugin_order = 20
    auth_level = 1

    _enabled = False
    _retention_days = 365
    _notification_enabled = False
    _notification_cron = "0 9 * * *"
    _notification_modes: ClassVar[list[str]] = ["today"]
    _ptd_cookiecloud_enabled = False
    _ptd_cookiecloud_uuid = ""
    _ptd_cookiecloud_password = ""
    _ptd_cookiecloud_headers = ""
    _ptd_site_mappings = ""
    _wealthy_retirement_sites: ClassVar[list[str]] = []
    _custom_retirement_rules: ClassVar[list[dict[str, Any]]] = []

    def init_plugin(self, config: dict | None = None) -> None:
        """读取配置并准备 V2/V3 共用的本地历史库。"""

        raw = dict(config or {})
        # 兼容 0.0.1 的 HH:mm 配置；保存后统一转成标准五段式 Cron。
        if "notification_cron" not in raw and raw.get("notification_time"):
            try:
                hour, minute = str(raw["notification_time"]).split(":", maxsplit=1)
                raw["notification_cron"] = f"{int(minute)} {int(hour)} * * *"
            except (TypeError, ValueError):
                raw["notification_cron"] = "0 9 * * *"
        try:
            normalized = SettingsData.model_validate(raw)
        except ValueError as error:
            logger.warning(f"PT数据统计配置无效，已回退安全默认值：{error}")
            normalized = SettingsData()
        self._apply_settings(normalized)
        self._log_custom_rule_state("已加载")
        self._sync_lock = threading.RLock()
        self._reset_database_handle()

    def _reset_database_handle(self) -> None:
        """重复初始化时关闭旧连接，并按当前运行实例重新打开历史库。"""

        existing = getattr(self, "_database_handle", None)
        if existing is not None:
            existing.close()
        self._database_handle = LocalDatabaseHandle(
            self.get_data_path() / "ptdatastatistics.db"
        )

    def _apply_settings(self, value: SettingsData) -> None:
        """把已校验设置投影为插件运行属性。"""

        self._enabled = value.enabled
        self._retention_days = value.retention_days
        self._notification_enabled = value.notification_enabled
        self._notification_cron = value.notification_cron
        self._notification_modes = list(value.notification_modes)
        self._ptd_cookiecloud_enabled = value.ptd_cookiecloud_enabled
        self._ptd_cookiecloud_uuid = value.ptd_cookiecloud_uuid
        self._ptd_cookiecloud_password = value.ptd_cookiecloud_password
        self._ptd_cookiecloud_headers = value.ptd_cookiecloud_headers
        self._ptd_site_mappings = value.ptd_site_mappings
        self._wealthy_retirement_sites = list(value.wealthy_retirement_sites)
        self._custom_retirement_rules = [rule.model_dump() for rule in value.custom_retirement_rules]

    def _log_custom_rule_state(self, action: str) -> None:
        """记录自定义规则状态，不输出具体门槛或说明正文。"""

        sites = [as_text(rule.get("site")) for rule in self._custom_retirement_rules]
        logger.info(
            f"自定义等级规则{action}：{len(sites)} 个站点"
            + (f"（{'、'.join(sites)}）" if sites else "")
        )

    def _settings(self) -> SettingsData:
        """返回当前设置模型。"""

        return SettingsData(
            enabled=self._enabled,
            retention_days=self._retention_days,
            notification_enabled=self._notification_enabled,
            notification_cron=self._notification_cron,
            notification_modes=self._notification_modes,
            ptd_cookiecloud_enabled=self._ptd_cookiecloud_enabled,
            ptd_cookiecloud_uuid=self._ptd_cookiecloud_uuid,
            ptd_cookiecloud_password=self._ptd_cookiecloud_password,
            ptd_cookiecloud_headers=self._ptd_cookiecloud_headers,
            ptd_site_mappings=self._ptd_site_mappings,
            wealthy_retirement_sites=self._wealthy_retirement_sites,
            custom_retirement_rules=self._custom_retirement_rules,
        )

    def _retirement_rules(self) -> dict[str, dict[str, Any]]:
        """将用户规则覆盖到内置规则，同时保留未覆盖的内置站点。"""

        rules: dict[str, dict[str, Any]] = {
            name: dict(rule) for name, rule in DEFAULT_RETIREMENT_RULES.items()
        }
        for uploaded in self._custom_retirement_rules:
            rule = {**uploaded, "_custom_rule": True}
            rules[uploaded["site"]] = rule
        return rules

    def get_state(self) -> bool:
        """返回插件启用状态。"""

        return bool(self._enabled)

    @staticmethod
    def get_render_mode() -> tuple[str, str]:
        """使用 Vue 模块联邦渲染侧栏、详情、配置和仪表盘。"""

        return "vue", "dist/assets"

    def get_sidebar_nav(self) -> list[dict[str, Any]]:
        """在 MoviePilot 侧栏发现分组注册 PT 数据统计入口。"""

        if not self.get_state():
            return []
        return [
            {
                "nav_key": "main",
                "title": "PT数据统计",
                "icon": "mdi-chart-donut",
                "section": "discovery",
                "permission": "discovery",
                "order": 25,
            }
        ]

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        """当前插件不注册消息命令。"""

        return []

    def get_form(self) -> tuple[list[dict], dict[str, Any]]:
        """Vue 配置组件读取当前配置模型。"""

        return [], self._settings().model_dump()

    @staticmethod
    def get_page() -> list[dict]:
        """Vue 详情组件通过插件 API 加载数据。"""

        return []

    def get_dashboard_meta(self) -> list[dict[str, str]]:
        """声明唯一的今日上传下载仪表盘组件。"""

        return [{"key": "today", "name": "今日PT数据"}]

    def get_dashboard(
        self,
        key: str = "today",
        **_: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], None] | None:
        """返回 Vue 仪表盘布局元数据。"""

        if not self.get_state() or key not in ("", "today"):
            return None
        return (
            {"cols": 12, "sm": 12, "md": 8, "lg": 8},
            {
                "title": "站点数据",
                "subtitle": "今日 00:00 起 · 仅显示有流量站点",
                "refresh": 60,
                "border": True,
            },
            None,
        )

    def get_service(self) -> list[dict[str, Any]]:
        """注册 Cron 通知和历史清理；数据同步复用 MP 的站点刷新事件。"""

        if not self.get_state():
            return []

        service_prefix = self.__class__.__name__
        services = [
            {
                "id": f"{service_prefix}.Cleanup",
                "name": "PT数据统计历史清理",
                "trigger": CronTrigger.from_crontab("30 3 * * *", timezone=settings.TZ),
                "func": self.cleanup_history,
                "kwargs": {},
            },
        ]
        if self._notification_enabled and self._notification_modes:
            services.append(
                {
                    "id": f"{service_prefix}.Notification",
                    "name": "PT数据统计每日通知",
                    "trigger": CronTrigger.from_crontab(self._notification_cron, timezone=settings.TZ),
                    "func": self._notification_tick,
                    "kwargs": {},
                }
            )
        return services

    def get_api(self) -> list[dict[str, Any]]:
        """注册数据查询、设置和 PTD 接收 API。"""

        return [
            {
                "path": "/cookiecloud",
                "endpoint": self.api_cookiecloud_ping,
                "methods": ["GET"],
                "allow_anonymous": True,
                "summary": "检测 PTD CookieCloud 兼容接收端",
                "response_model": None,
                "response_class": PlainTextResponse,
            },
            {
                "path": "/cookiecloud/",
                "endpoint": self.api_cookiecloud_ping,
                "methods": ["GET"],
                "allow_anonymous": True,
                "summary": "检测 PTD CookieCloud 兼容接收端（尾斜杠）",
                "response_model": None,
                "response_class": PlainTextResponse,
            },
            {
                "path": "/cookiecloud/update",
                "endpoint": self.api_cookiecloud_update,
                "methods": ["POST"],
                "allow_anonymous": True,
                "summary": "接收 PTD 加密备份",
                "response_model": CookieCloudActionResponse,
            },
            {
                "path": "/cookiecloud/get/{uuid}",
                "endpoint": self.api_cookiecloud_get,
                "methods": ["GET"],
                "allow_anonymous": True,
                "summary": "读取最新 PTD 加密备份",
                "response_model": CookieCloudEncryptedData,
            },
            {
                "path": "/overview",
                "endpoint": self.api_overview,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取 PT 数据总览",
                "response_model": OverviewResponse,
            },
            {
                "path": "/history",
                "endpoint": self.api_history,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询 PT 历史数据",
                "response_model": HistoryResponse,
            },
            {
                "path": "/history/hourly",
                "endpoint": self.api_hourly_traffic,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询随 MP 刷新保存的小时流量采样",
                "response_model": HourlyTrafficResponse,
            },
            {
                "path": "/distribution",
                "endpoint": self.api_distribution,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询月度与日度站点流量分布",
                "response_model": TrafficDistributionResponse,
            },
            {
                "path": "/settings",
                "endpoint": self.api_settings,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "读取插件设置",
                "response_model": SettingsResponse,
            },
            {
                "path": "/rules/template",
                "endpoint": self.api_rule_template,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "下载馒头等级规则模板",
                "response_model": None,
            },
            {
                "path": "/settings",
                "endpoint": self.api_update_settings,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存插件设置",
                "response_model": SettingsResponse,
            },
        ]

    def _now(self) -> datetime:
        """返回 MoviePilot 配置时区中的服务器时间。"""

        return datetime.now(ZoneInfo(settings.TZ))

    def _repository(self) -> SnapshotRepository:
        """从 MP 读取日级历史，并绑定插件本地小时快照库。"""

        database_handle = getattr(self, "_database_handle", None)
        if database_handle is None:
            self._reset_database_handle()
            database_handle = self._database_handle
        return SnapshotRepository(database_handle, self._mp_daily_snapshots())

    def _hourly_repository(self) -> SnapshotRepository:
        """创建只操作插件小时快照的仓储，不读取或写入日级插件表。"""

        database_handle = getattr(self, "_database_handle", None)
        if database_handle is None:
            self._reset_database_handle()
            database_handle = self._database_handle
        return SnapshotRepository(database_handle, [])

    @staticmethod
    def _site_dict(site: Any) -> dict[str, Any]:
        """把宿主站点对象投影为不含认证信息的普通字典。"""

        priority = getattr(site, "pri", None)
        return {
            "id": getattr(site, "id", None),
            "name": as_text(getattr(site, "name", "")),
            "domain": as_text(getattr(site, "domain", "")).casefold(),
            "is_active": bool(getattr(site, "is_active", False)),
            "site_priority": as_int(priority) if priority is not None else None,
        }

    @staticmethod
    def _snapshot_dict(row: Any, sites_by_domain: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """把宿主 SiteUserData 转换为插件业务字段。"""

        domain = as_text(getattr(row, "domain", "")).casefold()
        site = sites_by_domain.get(domain, {})
        updated_day = as_text(getattr(row, "updated_day", ""))[:10]
        updated_time = as_text(getattr(row, "updated_time", ""))[:16]
        return {
            "site_id": site.get("id"),
            "domain": domain,
            "site_name": site.get("name") or as_text(getattr(row, "name", "")) or domain,
            "is_active": bool(site.get("is_active")),
            "username": as_text(getattr(row, "username", "")),
            "userid": as_text(getattr(row, "userid", "")),
            "join_at": as_text(getattr(row, "join_at", "")),
            "user_level": as_text(getattr(row, "user_level", "")),
            "upload": as_int(getattr(row, "upload", 0)),
            "download": as_int(getattr(row, "download", 0)),
            "ratio": as_float(getattr(row, "ratio", None)),
            "bonus": as_float(getattr(row, "bonus", None)),
            "seeding": as_int(getattr(row, "seeding", 0)),
            "seeding_size": as_int(getattr(row, "seeding_size", 0)),
            "leeching": as_int(getattr(row, "leeching", 0)),
            "leeching_size": as_int(getattr(row, "leeching_size", 0)),
            "updated_day": updated_day,
            "updated_time": updated_time,
            "err_msg": as_text(getattr(row, "err_msg", "")),
            "source_updated_at": " ".join(part for part in (updated_day, updated_time) if part),
        }

    def _configured_sites(self) -> list[dict[str, Any]]:
        """读取宿主当前全部站点，不返回 Cookie 等敏感字段。"""

        return [self._site_dict(site) for site in (SiteOper().list() or [])]

    def _mp_daily_snapshots(self) -> list[dict[str, Any]]:
        """直接读取并规范化 MP 保存的全部 SiteUserData 日级历史。"""

        site_oper = SiteOper()
        configured_sites = [self._site_dict(site) for site in (site_oper.list() or [])]
        sites_by_domain = {
            site["domain"]: site for site in configured_sites if site["domain"]
        }
        snapshots_by_day: dict[tuple[str, str], dict[str, Any]] = {}
        for row in site_oper.get_userdata() or []:
            item = self._snapshot_dict(row, sites_by_domain)
            key = (item["domain"], item["updated_day"])
            current = snapshots_by_day.get(key)
            item_score = (not bool(item["err_msg"].strip()), item["updated_time"])
            current_score = (
                not bool(current["err_msg"].strip()),
                current["updated_time"],
            ) if current else (False, "")
            if not current or item_score >= current_score:
                snapshots_by_day[key] = item
        return list(snapshots_by_day.values())

    @staticmethod
    def _masked_uuid(value: str) -> str:
        """Return a log-safe UUID fragment."""

        normalized = as_text(value)
        if len(normalized) <= 8:
            return "***"
        return f"{normalized[:4]}…{normalized[-4:]}"

    def _require_ptd_receiver(self, request: Request | None = None, uuid: str | None = None) -> None:
        """Validate receiver state, UUID capability and optional configured headers."""

        if not self.get_state() or not self._ptd_cookiecloud_enabled:
            logger.warning("PTD CookieCloud 接收请求被拒绝：兼容接收端未启用")
            raise HTTPException(status_code=404, detail="PTD CookieCloud 接收端未启用")
        configured_uuid = self._ptd_cookiecloud_uuid.strip()
        if not configured_uuid or not self._ptd_cookiecloud_password:
            logger.warning("PTD CookieCloud 接收请求被拒绝：UUID 或密码尚未配置")
            raise HTTPException(status_code=503, detail="请先在插件设置中填写 PTD 专用 UUID 和密码")
        if uuid is not None and not hmac.compare_digest(as_text(uuid), configured_uuid):
            logger.warning(
                f"PTD CookieCloud 接收请求被拒绝：UUID 不匹配（收到 {self._masked_uuid(uuid)}）"
            )
            raise HTTPException(status_code=404, detail="Item not found")
        if request is None or not self._ptd_cookiecloud_headers:
            return
        for line in self._ptd_cookiecloud_headers.splitlines():
            if not line.strip():
                continue
            name, separator, expected = line.partition(":")
            name = name.strip()
            expected = expected.strip()
            if not separator or not name or not expected:
                logger.warning("PTD CookieCloud 接收请求被拒绝：鉴权 Headers 配置格式错误")
                raise HTTPException(status_code=503, detail="接收鉴权 Headers 配置格式错误")
            actual = request.headers.get(name, "").strip()
            if not hmac.compare_digest(actual, expected):
                logger.warning(f"PTD CookieCloud 接收请求被拒绝：缺少或不匹配的 Header {name}")
                raise HTTPException(status_code=403, detail="CookieCloud 认证失败")

    def _parse_and_match_ptd(self, encrypted: str) -> tuple[Any, list[dict[str, Any]]]:
        """Decrypt the received payload and map its metrics to configured MP sites."""

        backup = parse_backup_response(
            response={"encrypted": encrypted},
            uuid=self._ptd_cookiecloud_uuid,
            password=self._ptd_cookiecloud_password,
        )
        matched = match_metrics(
            backup.metrics,
            backup.metadata,
            self._configured_sites(),
            self._ptd_site_mappings,
        )
        if not matched:
            raise PTDCookieCloudError(
                "PTD 备份中有数据，但未能匹配任何 MoviePilot 站点；请补充站点映射"
            )
        return backup, matched

    def _save_ptd_import(self, *, encrypted: str, backup: Any, matched: list[dict[str, Any]]) -> None:
        """Replace the receiver payload and derived metrics under stable storage keys."""

        imported_at = self._now().isoformat(timespec="seconds")
        self.save_data(
            "ptd_cookiecloud_payload_v1",
            {"encrypted": encrypted, "received_at": imported_at},
        )
        self.save_data(
            "ptd_latest_metrics_v1",
            {
                "backup": backup.name,
                "source_url": "plugin-receiver",
                "imported_at": imported_at,
                "metrics": matched,
            },
        )

    def api_cookiecloud_ping(self, request: Request) -> PlainTextResponse:
        """Return the exact health text required by PTD's CookieCloud client."""

        self._require_ptd_receiver(request=request)
        logger.info("PTD CookieCloud 兼容接收端连接检测成功")
        return PlainTextResponse("Hello World!API ROOT = /api/v1/plugin/PTDataStatistics/cookiecloud")

    def api_cookiecloud_update(
        self,
        payload: CookieCloudUpdateData,
        request: Request,
    ) -> CookieCloudActionResponse:
        """Accept, validate and immediately import the newest encrypted PTD backup."""

        self._require_ptd_receiver(request=request, uuid=payload.uuid)
        logger.info(
            "收到 PTD CookieCloud 加密备份："
            f"UUID {self._masked_uuid(payload.uuid)}，密文 {len(payload.encrypted)} 字符"
        )
        try:
            backup, matched = self._parse_and_match_ptd(payload.encrypted)
            self._save_ptd_import(encrypted=payload.encrypted, backup=backup, matched=matched)
        except PTDCookieCloudError as error:
            logger.warning(f"PTD CookieCloud 备份解析失败：{error}")
            return CookieCloudActionResponse(action="error")
        logger.info(
            f"PTD CookieCloud 备份导入成功：{backup.name}，"
            f"读取 {len(backup.metrics)} 个站点，匹配 {len(matched)} 个站点；旧数据已覆盖"
        )
        missing_magic = [
            as_text(item.get("site_name") or item.get("ptd_site"))
            for item in matched
            if item.get("estimated_bonus_hourly") is None
        ]
        if missing_magic:
            logger.warning(
                "PTD 备份未提供以下站点的时魔，界面将显示暂不可估算："
                + "、".join(name for name in missing_magic if name)
            )
        return CookieCloudActionResponse(action="done")

    def api_cookiecloud_get(self, uuid: str, request: Request) -> CookieCloudEncryptedData:
        """Return only the single latest encrypted PTD backup."""

        self._require_ptd_receiver(request=request, uuid=uuid)
        saved = self.get_data("ptd_cookiecloud_payload_v1") or {}
        encrypted = saved.get("encrypted") if isinstance(saved, dict) else None
        if not isinstance(encrypted, str) or not encrypted:
            logger.info("PTD CookieCloud 读取请求：尚未收到备份")
            raise HTTPException(status_code=404, detail="Item not found")
        logger.info(
            f"PTD CookieCloud 已返回最新加密备份：UUID {self._masked_uuid(uuid)}，"
            f"密文 {len(encrypted)} 字符"
        )
        return CookieCloudEncryptedData(encrypted=encrypted)

    def sync_from_ptd(self) -> tuple[int, str]:
        """Re-import the single latest payload received directly from PTD."""

        if not self._ptd_cookiecloud_enabled:
            return 0, ""
        saved = self.get_data("ptd_cookiecloud_payload_v1") or {}
        encrypted = saved.get("encrypted") if isinstance(saved, dict) else None
        if not isinstance(encrypted, str) or not encrypted:
            raise PTDCookieCloudError("尚未收到 PTD 备份，请先在 PTD 中执行一次备份")
        backup, matched = self._parse_and_match_ptd(encrypted)
        self._save_ptd_import(encrypted=encrypted, backup=backup, matched=matched)
        logger.info(
            f"PTD 最新备份同步成功：{backup.name}，匹配 {len(matched)} 个站点；旧数据已覆盖"
        )
        return len(matched), backup.name

    def _ptd_metrics_by_domain(self) -> dict[str, dict[str, Any]]:
        """Return the latest PTD values only while CookieCloud is enabled."""

        if not self._ptd_cookiecloud_enabled:
            return {}
        saved = self.get_data("ptd_latest_metrics_v1") or {}
        values = saved.get("metrics") if isinstance(saved, dict) else []
        metrics: dict[str, dict[str, Any]] = {}
        for saved_item in values or []:
            if not isinstance(saved_item, dict) or not saved_item.get("domain"):
                continue
            item = dict(saved_item)
            # Upgrade already-imported v1.1.5/v1.1.6 data in memory so users do
            # not have to send another PTD backup before all sites receive the
            # same bonusPerHour fallback used by PTD's remaining-time display.
            if (
                item.get("seeding_points_hourly") is None
                and item.get("estimated_bonus_hourly") is not None
            ):
                item["seeding_points_hourly"] = item["estimated_bonus_hourly"]
            metrics[as_text(item.get("domain")).casefold()] = item
        return metrics

    def sync_from_mp(self, *, full: bool = False, site_id: int | None = None) -> SyncResponse:
        """读取 MP 最新累计值，仅写入插件小时快照库。"""

        if not hasattr(self, "_sync_lock"):
            self._sync_lock = threading.RLock()
        with self._sync_lock:
            site_oper = SiteOper()
            configured_sites = [self._site_dict(site) for site in (site_oper.list() or [])]
            sites_by_domain = {site["domain"]: site for site in configured_sites if site["domain"]}
            repository = self._hourly_repository()

            if site_id not in (None, 0):
                site = site_oper.get(int(site_id))
                domain = as_text(getattr(site, "domain", "")).casefold() if site else ""
                candidates = site_oper.get_userdata_by_domain(domain) if domain else []
                source_rows = sorted(
                    candidates or [],
                    key=lambda item: (
                        not bool(as_text(getattr(item, "err_msg", "")).strip()),
                        as_text(getattr(item, "updated_day", "")),
                        as_text(getattr(item, "updated_time", "")),
                    ),
                    reverse=True,
                )[:1]
            else:
                source_rows = site_oper.get_userdata_latest() or []

            # MP 历史库可能存在同站点同一天的多条记录。插件按天保存一条，
            # 优先保留成功记录，再取当天时间较晚者，避免失败记录覆盖有效累计值。
            snapshots_by_day: dict[tuple[str, str], dict[str, Any]] = {}
            for row in source_rows:
                item = self._snapshot_dict(row, sites_by_domain)
                key = (item["domain"], item["updated_day"])
                current = snapshots_by_day.get(key)
                item_score = (not bool(item["err_msg"].strip()), item["updated_time"])
                current_score = (
                    not bool(current["err_msg"].strip()),
                    current["updated_time"],
                ) if current else (False, "")
                if not current or item_score >= current_score:
                    snapshots_by_day[key] = item
            snapshots = list(snapshots_by_day.values())
            captured_at = self._now()
            server_day = captured_at.date().isoformat()
            imported = repository.capture_hourly(
                (item for item in snapshots if item.get("updated_day") == server_day),
                captured_at=captured_at.isoformat(sep=" ", timespec="seconds"),
            )
            deleted = repository.cleanup(
                retention_days=self._retention_days,
                server_day=server_day,
            )
            completed_at = self._now().isoformat(timespec="seconds")
            self.save_data("last_sync", completed_at)
            return SyncResponse(imported=imported, deleted=deleted, completed_at=completed_at)

    def _ensure_history(self) -> None:
        """日级历史由每次查询直接读取 MP，无需插件侧初始化。"""

    @eventmanager.register(EventType.SiteRefreshed)
    def on_site_refreshed(self, event: Event | None = None) -> None:
        """MP 刷新站点后立即复制其结果，不访问 PT 站点或下载器。"""

        if not self.get_state():
            return
        event_data = event.event_data if event else {}
        raw_site_id = event_data.get("site_id") if isinstance(event_data, dict) else None
        try:
            site_id = int(raw_site_id) if raw_site_id not in (None, "", "*") else None
            # “*” 表示 MP 完成了一轮站点刷新；这里只读取 MP 的最新结果。
            self.sync_from_mp(full=False, site_id=site_id)
        except Exception as error:  # noqa: BLE001 - 事件失败不得影响宿主刷新链
            logger.error(f"PT数据统计同步 MoviePilot 站点数据失败：{error}")
        if self._ptd_cookiecloud_enabled and raw_site_id in (None, "", "*"):
            try:
                # MP 通常会为单站刷新发出多次事件，只在整轮完成后读一次 CookieCloud。
                self.sync_from_ptd()
            except PTDCookieCloudError as error:
                logger.warning(f"同步 PTD CookieCloud 数据失败：{error}")

    def _build_overview(self) -> OverviewResponse:
        """构建可由侧栏和仪表盘共同复用的指标模型。"""

        self._ensure_history()
        repository = self._repository()
        now = self._now()
        server_day = now.date().isoformat()
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        latest_valid = repository.latest(active_only=True, valid_only=True)
        latest_valid_all = repository.latest(active_only=False, valid_only=True)
        latest_any = repository.latest(active_only=True, valid_only=False)
        history_sites = repository.latest(active_only=False, valid_only=False)
        previous_bonus_rows = repository.previous_successful(latest_valid_all)
        ptd_by_domain = self._ptd_metrics_by_domain()
        day_rows = repository.records_for_days((server_day, yesterday), active_only=True)
        today_by_domain = {
            item["domain"]: item for item in day_rows if item["updated_day"] == server_day
        }
        previous_by_domain = {
            item["domain"]: item for item in day_rows if item["updated_day"] == yesterday
        }

        configured_all = self._configured_sites()
        configured = [site for site in configured_all if site["is_active"]]
        configured_by_domain = {
            site["domain"]: site for site in configured_all if site.get("domain")
        }
        valid_by_domain = {item["domain"]: item for item in latest_valid}
        any_by_domain = {item["domain"]: item for item in latest_any}
        sites: list[dict[str, Any]] = []
        today_sites: list[dict[str, Any]] = []
        for configured_site in configured:
            domain = configured_site["domain"]
            latest_row = valid_by_domain.get(domain) or any_by_domain.get(domain) or {
                "site_id": configured_site["id"],
                "domain": domain,
                "site_name": configured_site["name"] or domain,
                "is_active": True,
                "username": "",
                "userid": "",
                "join_at": "",
                "user_level": "",
                "upload": 0,
                "download": 0,
                "ratio": None,
                "bonus": None,
                "seeding": 0,
                "seeding_size": 0,
                "leeching": 0,
                "leeching_size": 0,
                "updated_day": "",
                "updated_time": "",
                "err_msg": "尚无 MoviePilot 站点数据",
                "source_updated_at": "",
            }
            current = today_by_domain.get(latest_row["domain"])
            delta = compute_daily_delta(
                current or {**latest_row, "updated_day": server_day},
                previous_by_domain.get(latest_row["domain"]),
            ) if current else {
                "baseline_valid": False,
                "daily_upload": 0,
                "daily_download": 0,
                "counter_reset": False,
            }
            item = {
                **latest_row,
                **delta,
                "site_priority": configured_site.get("site_priority"),
                "contribution": 0.0,
                "estimated_bonus_hourly": estimate_bonus_hourly(
                    latest_row,
                    previous_bonus_rows.get(domain),
                ) if domain in valid_by_domain else None,
                "seeding_points": None,
                "seeding_points_hourly": None,
                "torrent_uploads": None,
            }
            ptd_metric = ptd_by_domain.get(domain)
            if ptd_metric:
                # A matched PTD record is authoritative.  Do not silently show
                # an MP snapshot estimate when PTD did not provide time magic;
                # HHanClub's seeding-points rate is a different metric and must
                # never be presented as time magic.
                item["estimated_bonus_hourly"] = as_float(
                    ptd_metric.get("estimated_bonus_hourly")
                )
                if ptd_metric.get("seeding_points") is not None:
                    item["seeding_points"] = as_float(ptd_metric.get("seeding_points"))
                if ptd_metric.get("seeding_points_hourly") is not None:
                    item["seeding_points_hourly"] = as_float(
                        ptd_metric.get("seeding_points_hourly")
                    )
                if ptd_metric.get("torrent_uploads") is not None:
                    item["torrent_uploads"] = as_float(
                        ptd_metric.get("torrent_uploads")
                    )
                if not as_text(item.get("user_level")) and as_text(
                    ptd_metric.get("user_level")
                ):
                    item["user_level"] = as_text(ptd_metric.get("user_level"))
            sites.append(item)
            if current and delta["baseline_valid"] and (
                delta["daily_upload"] > 0 or delta["daily_download"] > 0
            ):
                today_sites.append(item)

        total_today_upload = sum(item["daily_upload"] for item in today_sites)
        total_today_download = sum(item["daily_download"] for item in today_sites)
        contribution_total = total_today_upload or total_today_download
        contribution_field = "daily_upload" if total_today_upload else "daily_download"
        for item in today_sites:
            item["contribution"] = round(
                item[contribution_field] * 100 / contribution_total,
                1,
            ) if contribution_total else 0.0
        today_sites.sort(
            key=lambda item: (item[contribution_field], item["site_name"]),
            reverse=True,
        )

        valid_sites = [item for item in sites if item["domain"] in valid_by_domain]
        total_upload = sum(item["upload"] for item in valid_sites)
        total_download = sum(item["download"] for item in valid_sites)
        earliest = earliest_join_date(valid_sites)
        site_count = len(valid_sites)
        summary = SummaryData(
            valid_sites=site_count,
            total_upload=total_upload,
            total_download=total_download,
            overall_ratio=overall_ratio(total_upload, total_download),
            total_seeding=sum(item["seeding"] for item in valid_sites),
            total_seeding_size=sum(item["seeding_size"] for item in valid_sites),
            today_upload=total_today_upload,
            today_download=total_today_download,
            today_sites=len(today_sites),
            earliest_join_at=earliest,
            career_days=career_days(earliest, server_day),
            average_upload=round(total_upload / site_count) if site_count else 0,
            average_download=round(total_download / site_count) if site_count else 0,
            top_upload_site=max(valid_sites, key=lambda item: item["upload"])["site_name"] if valid_sites else "",
            top_download_site=max(valid_sites, key=lambda item: item["download"])["site_name"] if valid_sites else "",
        )

        valid_by_site_id = {
            int(item["site_id"]): item
            for item in latest_valid_all
            if isinstance(item.get("site_id"), int)
        }
        twelve = TwelveProgressData.model_validate(
            build_twelve_progress(configured_all, valid_by_site_id)
        )
        retirement_snapshots = [
            {
                **item,
                "user_level": as_text(item.get("user_level")) or as_text(
                    ptd_by_domain.get(item["domain"], {}).get("user_level")
                ),
                "site_priority": configured_by_domain.get(item["domain"], {}).get(
                    "site_priority"
                ),
                "estimated_bonus_hourly": (
                    as_float(ptd_by_domain[item["domain"]].get("estimated_bonus_hourly"))
                    if item["domain"] in ptd_by_domain
                    else estimate_bonus_hourly(item, previous_bonus_rows.get(item["domain"]))
                ),
                "seeding_points": as_float(
                    ptd_by_domain.get(item["domain"], {}).get("seeding_points")
                ),
                "seeding_points_hourly": as_float(
                    ptd_by_domain.get(item["domain"], {}).get("seeding_points_hourly")
                ),
                "torrent_uploads": as_float(
                    ptd_by_domain.get(item["domain"], {}).get("torrent_uploads")
                ),
            }
            for item in latest_valid_all
        ]
        retirement = RetirementProgressData.model_validate(
            build_retirement_progress(
                retirement_snapshots,
                self._retirement_rules(),
                self._wealthy_retirement_sites,
            )
        )
        first_day, last_day = repository.date_bounds()
        last_mp_update = max(
            (item.get("source_updated_at") or "" for item in latest_any),
            default="",
        )
        return OverviewResponse(
            server_date=server_day,
            generated_at=now.isoformat(timespec="seconds"),
            last_mp_update=last_mp_update,
            first_history_day=first_day,
            last_history_day=last_day,
            summary=summary,
            sites=[SiteSnapshotData.model_validate(item) for item in sites],
            today_sites=[SiteSnapshotData.model_validate(item) for item in today_sites],
            history_sites=[SiteSnapshotData.model_validate(item) for item in history_sites],
            twelve=twelve,
            retirement=retirement,
        )

    def api_overview(self) -> OverviewResponse:
        """返回侧栏与仪表盘总览。"""

        return self._build_overview()

    def _date_range(self, start_day: str | None, end_day: str | None) -> tuple[str, str]:
        """规范历史查询日期，默认最近九十个服务器日期。"""

        today = self._now().date()
        try:
            end = date.fromisoformat(end_day) if end_day else today
            start = date.fromisoformat(start_day) if start_day else end - timedelta(days=89)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM-DD") from error
        if start > end:
            start, end = end, start
        return start.isoformat(), end.isoformat()

    def api_history(
        self,
        start_day: str | None = Query(default=None),
        end_day: str | None = Query(default=None),
        site_ids: str | None = Query(default=None),
        include_archived: bool = Query(default=True),
        limit: int = Query(default=10000, ge=1, le=50000),
    ) -> HistoryResponse:
        """按日期和站点查询插件历史。"""

        self._ensure_history()
        start, end = self._date_range(start_day, end_day)
        site_id_values = self._parse_site_ids(site_ids)
        records = self._repository().history(
            start_day=start,
            end_day=end,
            site_ids=site_id_values,
            include_archived=include_archived,
            limit=limit,
        )
        return HistoryResponse(
            start_day=start,
            end_day=end,
            count=len(records),
            records=[SiteSnapshotData.model_validate(item) for item in records],
        )

    def api_hourly_traffic(
        self,
        day: str = Query(...),
        site_id: int | None = Query(default=None, ge=1),
    ) -> HourlyTrafficResponse:
        """读取插件随 MP 刷新保存的时点快照并计算指定自然日的小时增量。"""

        try:
            selected_day = date.fromisoformat(day).isoformat()
        except ValueError as error:
            raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM-DD") from error

        configured_sites = self._configured_sites()
        selected_site = next((site for site in configured_sites if site.get("id") == site_id), None)
        snapshots = self._repository().hourly_for_day(selected_day, site_id=site_id)
        result = build_hourly_traffic(snapshots, selected_day)
        return HourlyTrafficResponse(
            day=selected_day,
            site_id=site_id,
            site_name=as_text(selected_site.get("name")) if selected_site else "全部站点",
            **result,
        )

    @staticmethod
    def _parse_site_ids(raw: str | None) -> list[int]:
        """校验逗号分隔的 MoviePilot 站点 ID。"""

        values: list[int] = []
        for item in (raw or "").split(","):
            if not item.strip():
                continue
            try:
                value = int(item)
            except ValueError as error:
                raise HTTPException(status_code=422, detail="站点 ID 必须为整数") from error
            if value > 0 and value not in values:
                values.append(value)
        return values

    def api_distribution(
        self,
        month: str | None = Query(default=None),
        day: str | None = Query(default=None),
    ) -> TrafficDistributionResponse:
        """返回所选月份和日期的按站点上传下载增量。"""

        self._ensure_history()
        today = self._now().date()
        try:
            selected_day = date.fromisoformat(day) if day else today
            if month:
                selected_month = date.fromisoformat(f"{month}-01")
            else:
                selected_month = selected_day.replace(day=1)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM 或 YYYY-MM-DD") from error
        next_month = (
            selected_month.replace(year=selected_month.year + 1, month=1)
            if selected_month.month == 12
            else selected_month.replace(month=selected_month.month + 1)
        )
        month_end = next_month - timedelta(days=1)
        repository = self._repository()
        monthly_rows = repository.history(
            start_day=selected_month.isoformat(),
            end_day=month_end.isoformat(),
            include_archived=True,
            limit=None,
        )
        daily_rows = repository.history(
            start_day=selected_day.isoformat(),
            end_day=selected_day.isoformat(),
            include_archived=True,
            limit=None,
        )

        def aggregate(rows: list[dict[str, Any]]) -> list[TrafficDistributionItem]:
            grouped: dict[tuple[int | None, str], dict[str, Any]] = {}
            for row in rows:
                if not row.get("baseline_valid"):
                    continue
                key = (row.get("site_id"), as_text(row.get("site_name")))
                item = grouped.setdefault(
                    key,
                    {"site_id": row.get("site_id"), "site_name": key[1], "upload": 0, "download": 0},
                )
                item["upload"] += as_int(row.get("daily_upload"))
                item["download"] += as_int(row.get("daily_download"))
            values = [item for item in grouped.values() if item["upload"] > 0 or item["download"] > 0]
            values.sort(key=lambda item: (item["upload"] + item["download"], item["site_name"]), reverse=True)
            return [TrafficDistributionItem.model_validate(item) for item in values]

        return TrafficDistributionResponse(
            month=selected_month.strftime("%Y-%m"),
            day=selected_day.isoformat(),
            monthly=aggregate(monthly_rows),
            daily=aggregate(daily_rows),
        )

    def api_settings(self) -> SettingsResponse:
        """返回当前设置与可用于自定义规则锚定的 MP 站点名。"""

        return SettingsResponse(
            settings=self._settings(),
            rule_sites=[site["name"] for site in self._configured_sites() if site.get("name")],
        )

    @staticmethod
    def api_rule_template() -> dict[str, Any]:
        """从内置馒头规则生成带说明、可直接上传的 JSON 模板。"""

        uploadable_fields = {
            "name", "aliases", "description", "min_join_days",
            "min_join_days_strict", "min_upload", "min_upload_strict",
            "min_download", "min_download_strict", "min_ratio",
            "min_ratio_strict", "min_bonus", "min_bonus_strict",
            "min_seeding_points", "min_seeding_points_strict", "min_seeding",
            "min_seeding_strict", "min_seeding_size", "min_seeding_size_strict",
            "min_torrent_uploads", "min_torrent_uploads_strict",
            "min_average_seeding_time_days", "min_average_seeding_time_days_strict",
            "alternatives", "unsupported_requirements",
        }
        levels = [
            {
                **{key: value for key, value in level.items() if key in uploadable_fields},
                "aliases": list(level.get("aliases") or ()),
            }
            for level in MTEAM_RETIREMENT_RULE["levels"]
        ]
        return {
            "version": 1,
            "_comment": [
                "这是馒头完整等级规则示例，可直接上传，也可复制后修改为其他站点。",
                "site、aliases 和 domains 均参与 MoviePilot 站点名称及域名匹配。",
                "levels[].aliases 用于匹配 MoviePilot 返回的本地化等级名称。",
                "retirement_level 必须填写该站实际保号等级，可使用 levels[].name 或对应 aliases 中的别名。",
                "保号等级按名称或别名精确匹配（忽略大小写及符号），计算结果统一显示等级主名称。",
                "各站保号等级不同；修改为其他站点时，请同步修改完整等级路线和 retirement_level，不要照搬馒头的 Extreme User。",
                "流量门槛使用字节；strict 为 true 表示严格大于，否则表示大于等于。",
                "_comment 仅用于说明，导入时不会写入插件规则。",
            ],
            "rules": [{
                "site": "馒头",
                "aliases": list(MTEAM_RETIREMENT_RULE.get("aliases") or ()),
                "domains": list(MTEAM_RETIREMENT_RULE.get("domains") or ()),
                "retirement_level": MTEAM_RETIREMENT_RULE["retirement_level"],
                "levels": levels,
                "vip_levels": [
                    {
                        **{key: value for key, value in level.items() if key in uploadable_fields},
                        "aliases": list(level.get("aliases") or ()),
                    }
                    for level in MTEAM_RETIREMENT_RULE.get("vip_levels") or ()
                ],
            }],
        }

    def api_update_settings(self, payload: SettingsData) -> SettingsResponse:
        """保存设置并让宿主重建当前插件的定时任务。"""

        self._apply_settings(payload)
        self._log_custom_rule_state("已保存")
        self.update_config(payload.model_dump())
        if self._ptd_cookiecloud_enabled:
            logger.info(
                "PTD CookieCloud 兼容接收端设置已保存："
                f"UUID {self._masked_uuid(self._ptd_cookiecloud_uuid)}，"
                f"接收鉴权 {'已启用' if self._ptd_cookiecloud_headers else '未启用'}"
            )
        else:
            logger.info("PTD CookieCloud 兼容接收端已关闭")
        try:
            Scheduler().update_plugin_job(self.__class__.__name__)
        except Exception as error:  # noqa: BLE001 - 保存设置本身仍然有效
            logger.warning(f"更新 PT 数据统计定时任务失败，将在插件重载后生效：{error}")
        self.cleanup_history()
        return self.api_settings()

    def cleanup_history(self) -> int:
        """按配置清理插件小时快照，不修改 MoviePilot 日级历史。"""

        try:
            return self._hourly_repository().cleanup(
                retention_days=self._retention_days,
                server_day=self._now().date().isoformat(),
            )
        except Exception as error:  # noqa: BLE001 - 后台清理失败不影响插件主功能
            logger.error(f"清理 PT 数据统计小时快照失败：{error}")
            return 0

    def _notification_tick(self) -> None:
        """由用户 Cron 直接触发，每个服务器日期最多发送一次。"""

        if not self.get_state() or not self._notification_enabled or not self._notification_modes:
            return
        now = self._now()
        server_day = now.date().isoformat()
        if self.get_data("last_notification_day") == server_day:
            return

        try:
            self.sync_from_mp(full=False)
            overview = self._build_overview()
            sections: list[str] = []
            if "today" in self._notification_modes and overview.today_sites:
                lines = [
                    f"【今日数据 · {server_day}】",
                    f"总上传：{format_bytes(overview.summary.today_upload)}",
                    f"总下载：{format_bytes(overview.summary.today_download)}",
                ]
                lines.extend(
                    f"{item.site_name}：↑ {format_bytes(item.daily_upload)}  ↓ {format_bytes(item.daily_download)}"
                    for item in overview.today_sites
                )
                sections.append("\n".join(lines))

            all_sites = [item for item in overview.sites if item.upload > 0 or item.download > 0]
            if "all" in self._notification_modes and all_sites:
                lines = [
                    "【所有数据】",
                    f"总上传：{format_bytes(overview.summary.total_upload)}",
                    f"总下载：{format_bytes(overview.summary.total_download)}",
                ]
                lines.extend(
                    f"{item.site_name}：↑ {format_bytes(item.upload)}  ↓ {format_bytes(item.download)}"
                    for item in all_sites
                )
                sections.append("\n".join(lines))

            if not sections:
                logger.info("PT数据统计每日通知没有符合条件的站点，已跳过")
                self.save_data("last_notification_day", server_day)
                return
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title="PT数据统计",
                text="\n\n".join(sections),
            )
            self.save_data("last_notification_day", server_day)
        except Exception as error:  # noqa: BLE001 - 计划任务错误由插件记录
            logger.error(f"发送 PT 数据统计每日通知失败：{error}")

    def stop_service(self) -> None:
        """关闭运行开关并释放 V2 本地历史库连接。"""

        self._enabled = False
        database_handle = getattr(self, "_database_handle", None)
        if database_handle is not None:
            database_handle.close()
            self._database_handle = None
