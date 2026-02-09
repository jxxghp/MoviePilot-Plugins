"""MoviePilot 活动总结插件 — 定时发送每日/每周/每月活动总结通知"""

import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, List, Dict, Tuple, Optional
from datetime import datetime, timedelta

import pytz
from apscheduler.triggers.cron import CronTrigger

from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.core.event import eventmanager, Event
from app.schemas.types import EventType
from app.core.config import settings
from app.db.transferhistory_oper import TransferHistoryOper
from app.db.subscribe_oper import SubscribeOper
from app.db.plugindata_oper import PluginDataOper
from app.db.models.siteuserdata import SiteUserData
from app.db import ScopedSession


# ─── 模块注册表：key → 中文名，各报告按需选取 ───

MODULES = OrderedDict([
    ("download",     "下载记录"),
    ("transfer",     "入库记录"),
    ("signin",       "签到状态"),
    ("brush",        "刷流统计"),
    ("downloader",   "下载器概览"),
    ("site_delta",   "站点增量"),
    ("site_current", "站点快照"),
    ("subscribe",    "订阅进度"),
    ("storage",      "存储空间"),
])

MODULE_OPTIONS = [{"title": name, "value": key} for key, name in MODULES.items()]

# 各报告类型的默认模块
DEFAULT_DAILY_MODULES = ["download", "transfer", "signin", "brush", "downloader", "site_delta"]
DEFAULT_WEEKLY_MODULES = ["download", "transfer", "subscribe", "site_delta", "brush"]
DEFAULT_MONTHLY_MODULES = [
    "download", "transfer", "subscribe", "site_current",
    "site_delta", "storage", "brush", "downloader",
]

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 历史记录上限
MAX_HISTORY = 100


@dataclass
class TimeRange:
    """报告的时间范围"""
    start: datetime
    end: datetime
    start_str: str       # "YYYY-MM-DD HH:MM:SS" — 用于数据库查询
    start_date: str      # "YYYY-MM-DD"
    end_date: str        # "YYYY-MM-DD"
    report_type: str     # "daily" / "weekly" / "monthly"
    prefix: str          # "今日" / "本周" / "本月"


class DailySummary(_PluginBase):
    plugin_name = "活动总结"
    plugin_desc = "定时发送每日/每周/每月活动总结通知，支持自定义报告模块、历史记录查看"
    plugin_icon = "Bark_A.png"
    plugin_version = "2.0.0"
    plugin_author = "yuhoye"
    author_url = "https://github.com/yuhoye"
    plugin_config_prefix = "dailysummary_"
    plugin_order = 30
    auth_level = 1

    # ─── 配置字段 ───

    _enabled: bool = False
    _notify: bool = True
    _daily_cron: str = "0 23 * * *"
    _weekly_cron: str = "0 23 * * 1"
    _monthly_cron: str = "0 23 1 * *"
    _onlyonce: bool = False
    _test_type: str = "daily"

    _daily_modules: list = None
    _weekly_modules: list = None
    _monthly_modules: list = None

    _signin_plugin_id: str = "AutoSignIn"
    _brush_plugin_ids: str = "BrushFlow"
    _storage_paths: str = ""

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._notify = config.get("notify", True)
            self._daily_cron = config.get("daily_cron", "0 23 * * *")
            self._weekly_cron = config.get("weekly_cron", "0 23 * * 1")
            self._monthly_cron = config.get("monthly_cron", "0 23 1 * *")
            self._onlyonce = config.get("onlyonce", False)
            self._test_type = config.get("test_type", "daily")
            self._daily_modules = config.get("daily_modules") or DEFAULT_DAILY_MODULES
            self._weekly_modules = config.get("weekly_modules") or DEFAULT_WEEKLY_MODULES
            self._monthly_modules = config.get("monthly_modules") or DEFAULT_MONTHLY_MODULES
            self._signin_plugin_id = config.get("signin_plugin_id", "AutoSignIn")
            self._brush_plugin_ids = config.get("brush_plugin_ids", "BrushFlow")
            self._storage_paths = config.get("storage_paths", "")
        else:
            self._daily_modules = DEFAULT_DAILY_MODULES
            self._weekly_modules = DEFAULT_WEEKLY_MODULES
            self._monthly_modules = DEFAULT_MONTHLY_MODULES

        if self._onlyonce:
            self._onlyonce = False
            self._save_config()
            from apscheduler.schedulers.background import BackgroundScheduler
            scheduler = BackgroundScheduler(timezone=settings.TZ)
            test_func = {
                "daily": self.send_daily,
                "weekly": self.send_weekly,
                "monthly": self.send_monthly,
            }.get(self._test_type, self.send_daily)
            scheduler.add_job(
                func=test_func,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="立即测试",
            )
            scheduler.start()

    def _save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "daily_cron": self._daily_cron,
            "weekly_cron": self._weekly_cron,
            "monthly_cron": self._monthly_cron,
            "onlyonce": False,
            "test_type": self._test_type,
            "daily_modules": self._daily_modules,
            "weekly_modules": self._weekly_modules,
            "monthly_modules": self._monthly_modules,
            "signin_plugin_id": self._signin_plugin_id,
            "brush_plugin_ids": self._brush_plugin_ids,
            "storage_paths": self._storage_paths,
        })

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {"cmd": "/daily_summary", "event": EventType.PluginAction, "desc": "发送每日总结", "category": "工具", "data": {"action": "daily_summary"}},
            {"cmd": "/weekly_summary", "event": EventType.PluginAction, "desc": "发送每周总结", "category": "工具", "data": {"action": "weekly_summary"}},
            {"cmd": "/monthly_summary", "event": EventType.PluginAction, "desc": "发送每月总结", "category": "工具", "data": {"action": "monthly_summary"}},
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/clear_history",
            "endpoint": self._api_clear_history,
            "methods": ["POST"],
            "summary": "清除历史记录",
        }]

    def _api_clear_history(self) -> dict:
        self.save_data("history", [])
        logger.info("[DailySummary] 历史记录已清除")
        return {"success": True}

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        services = []
        if self._daily_cron:
            services.append({
                "id": "DailySummary_daily",
                "name": "每日总结",
                "trigger": CronTrigger.from_crontab(self._daily_cron),
                "func": self.send_daily,
                "kwargs": {},
            })
        if self._weekly_cron:
            services.append({
                "id": "DailySummary_weekly",
                "name": "每周总结",
                "trigger": CronTrigger.from_crontab(self._weekly_cron),
                "func": self.send_weekly,
                "kwargs": {},
            })
        if self._monthly_cron:
            services.append({
                "id": "DailySummary_monthly",
                "name": "每月总结",
                "trigger": CronTrigger.from_crontab(self._monthly_cron),
                "func": self.send_monthly,
                "kwargs": {},
            })
        return services

    # ─── 配置表单：三 Tab 布局 ───

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        test_options = [
            {"title": "每日总结", "value": "daily"},
            {"title": "每周总结", "value": "weekly"},
            {"title": "每月总结", "value": "monthly"},
        ]
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VTabs",
                        "props": {"model": "_tab", "style": "margin-top: -18px; margin-bottom: 12px;"},
                        "content": [
                            {"component": "VTab", "props": {"value": "basic"}, "text": "基本设置"},
                            {"component": "VTab", "props": {"value": "modules"}, "text": "报告内容"},
                            {"component": "VTab", "props": {"value": "advanced"}, "text": "高级设置"},
                        ],
                    },
                    {
                        "component": "VWindow",
                        "props": {"model": "_tab"},
                        "content": [
                            # ── Tab 1: 基本设置 ──
                            {
                                "component": "VWindowItem",
                                "props": {"value": "basic"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "发送通知"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即测试一次"}}]},
                                        ],
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                                             "content": [{"component": "VTextField", "props": {"model": "daily_cron", "label": "每日 Cron"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                                             "content": [{"component": "VTextField", "props": {"model": "weekly_cron", "label": "每周 Cron"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                                             "content": [{"component": "VTextField", "props": {"model": "monthly_cron", "label": "每月 Cron"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                                             "content": [{"component": "VSelect", "props": {"model": "test_type", "label": "测试类型", "items": test_options}}]},
                                        ],
                                    },
                                ],
                            },
                            # ── Tab 2: 报告内容 ──
                            {
                                "component": "VWindowItem",
                                "props": {"value": "modules"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12},
                                             "content": [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "选择各报告中包含的信息模块，模块按选择顺序显示在报告中"}}]},
                                        ],
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VSelect", "props": {
                                                 "model": "daily_modules", "label": "日报模块",
                                                 "items": MODULE_OPTIONS, "multiple": True, "chips": True, "closable-chips": True,
                                             }}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VSelect", "props": {
                                                 "model": "weekly_modules", "label": "周报模块",
                                                 "items": MODULE_OPTIONS, "multiple": True, "chips": True, "closable-chips": True,
                                             }}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VSelect", "props": {
                                                 "model": "monthly_modules", "label": "月报模块",
                                                 "items": MODULE_OPTIONS, "multiple": True, "chips": True, "closable-chips": True,
                                             }}]},
                                        ],
                                    },
                                ],
                            },
                            # ── Tab 3: 高级设置 ──
                            {
                                "component": "VWindowItem",
                                "props": {"value": "advanced"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12},
                                             "content": [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "以下为高级配置，一般无需修改"}}]},
                                        ],
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VTextField", "props": {"model": "signin_plugin_id", "label": "签到插件 ID", "placeholder": "AutoSignIn"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VTextField", "props": {"model": "brush_plugin_ids", "label": "刷流插件 ID", "placeholder": "BrushFlow", "hint": "多个用逗号分隔"}}]},
                                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                                             "content": [{"component": "VTextField", "props": {"model": "storage_paths", "label": "存储监控路径", "placeholder": "留空自动检测", "hint": "格式: /media:媒体盘,/downloads:下载盘"}}]},
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "daily_cron": "0 23 * * *",
            "weekly_cron": "0 23 * * 1",
            "monthly_cron": "0 23 1 * *",
            "onlyonce": False,
            "test_type": "daily",
            "daily_modules": DEFAULT_DAILY_MODULES,
            "weekly_modules": DEFAULT_WEEKLY_MODULES,
            "monthly_modules": DEFAULT_MONTHLY_MODULES,
            "signin_plugin_id": "AutoSignIn",
            "brush_plugin_ids": "BrushFlow",
            "storage_paths": "",
        }

    # ─── 历史记录页面 ───

    def get_page(self) -> List[dict]:
        history = self.get_data("history") or []

        # 模块配置摘要
        def _module_names(modules):
            return "、".join(MODULES.get(m, m) for m in (modules or []))

        config_cards = [
            self._config_card('📊 日报模块', _module_names(self._daily_modules), self._daily_cron),
            self._config_card('📈 周报模块', _module_names(self._weekly_modules), self._weekly_cron),
            self._config_card('📅 月报模块', _module_names(self._monthly_modules), self._monthly_cron),
        ]

        if not history:
            return [
                {
                    'component': 'VRow',
                    'content': config_cards,
                },
                {
                    'component': 'div',
                    'text': '暂无发送记录',
                    'props': {'class': 'text-center mt-4'},
                },
            ]

        daily_count = sum(1 for r in history if r.get("type") == "daily")
        weekly_count = sum(1 for r in history if r.get("type") == "weekly")
        monthly_count = sum(1 for r in history if r.get("type") == "monthly")

        items = [
            {
                'time': r.get('time', ''),
                'type_label': {'daily': '日报', 'weekly': '周报', 'monthly': '月报'}.get(r.get('type'), ''),
                'title': r.get('title', ''),
                'preview': (r.get('text', '')[:80] + '...') if len(r.get('text', '')) > 80 else r.get('text', ''),
            }
            for r in reversed(history)
        ]

        return [
            {
                'component': 'VRow',
                'content': config_cards + [
                    # 发送统计
                    self._stat_card('日报', f'{daily_count} 份'),
                    self._stat_card('周报', f'{weekly_count} 份'),
                    self._stat_card('月报', f'{monthly_count} 份'),
                    # 历史记录表格
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'class': 'd-none d-sm-block'},
                        'content': [
                            {
                                'component': 'VDataTableVirtual',
                                'props': {
                                    'class': 'text-sm',
                                    'headers': [
                                        {'title': '时间', 'key': 'time', 'sortable': True},
                                        {'title': '类型', 'key': 'type_label', 'sortable': True},
                                        {'title': '标题', 'key': 'title', 'sortable': False},
                                        {'title': '预览', 'key': 'preview', 'sortable': False},
                                    ],
                                    'items': items,
                                    'height': '30rem',
                                    'density': 'compact',
                                    'fixed-header': True,
                                    'hide-no-data': True,
                                    'hover': True,
                                },
                            }
                        ],
                    },
                ],
            }
        ]

    @staticmethod
    def _config_card(title: str, modules_text: str, cron: str) -> dict:
        return {
            'component': 'VCol',
            'props': {'cols': 12, 'md': 4},
            'content': [{
                'component': 'VCard',
                'props': {'variant': 'tonal'},
                'content': [{
                    'component': 'VCardText',
                    'content': [
                        {'component': 'div', 'props': {'class': 'text-subtitle-2 mb-1'}, 'text': f'{title}  ⏰ {cron}'},
                        {'component': 'span', 'props': {'class': 'text-caption'}, 'text': modules_text},
                    ],
                }],
            }],
        }

    @staticmethod
    def _stat_card(title: str, value: str) -> dict:
        return {
            'component': 'VCol',
            'props': {'cols': 4, 'md': 4},
            'content': [{
                'component': 'VCard',
                'props': {'variant': 'tonal'},
                'content': [{
                    'component': 'VCardText',
                    'props': {'class': 'text-center pa-2'},
                    'content': [
                        {'component': 'div', 'props': {'class': 'text-caption'}, 'text': title},
                        {'component': 'div', 'props': {'class': 'text-h6'}, 'text': value},
                    ],
                }],
            }],
        }

    def stop_service(self):
        pass

    # ─── 命令处理 ───

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event = None):
        if not event:
            return
        action = (event.event_data or {}).get("action", "")
        handler = {
            "daily_summary": self.send_daily,
            "weekly_summary": self.send_weekly,
            "monthly_summary": self.send_monthly,
        }.get(action)
        if handler:
            handler()

    # ─── 统一报告引擎 ───

    def send_daily(self):
        header, text = self._build_report("daily")
        self._send(report_type="daily", title=header, text=text)

    def send_weekly(self):
        header, text = self._build_report("weekly")
        self._send(report_type="weekly", title=header, text=text)

    def send_monthly(self):
        header, text = self._build_report("monthly")
        self._send(report_type="monthly", title=header, text=text)

    def _build_report(self, report_type: str) -> Tuple[str, str]:
        logger.info(f"[DailySummary] 开始生成 {report_type} 总结")
        tr = self._calc_time_range(report_type)
        modules = {
            "daily": self._daily_modules,
            "weekly": self._weekly_modules,
            "monthly": self._monthly_modules,
        }.get(report_type, self._daily_modules)

        sections = []
        for mod in modules:
            result = self._run_section(mod, tr)
            if result:
                sections.append(result)

        header = self._make_header(report_type, tr)
        text = header + "\n\n" + "\n\n".join(sections) if sections else header + "\n\n无数据"
        return header, text

    def _calc_time_range(self, report_type: str) -> TimeRange:
        tz = pytz.timezone(settings.TZ)
        now = datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if report_type == "daily":
            start = today_start
            prefix = "今日"
        elif report_type == "weekly":
            start = today_start - timedelta(days=now.weekday())
            prefix = "本周"
        else:
            start = today_start.replace(day=1)
            prefix = "本月"

        return TimeRange(
            start=start,
            end=now,
            start_str=start.strftime("%Y-%m-%d 00:00:00"),
            start_date=start.strftime("%Y-%m-%d"),
            end_date=today_start.strftime("%Y-%m-%d"),
            report_type=report_type,
            prefix=prefix,
        )

    def _make_header(self, report_type: str, tr: TimeRange) -> str:
        now = tr.end
        if report_type == "daily":
            return f"📊 每日总结 ({now.strftime('%m-%d')} {WEEKDAY_NAMES[now.weekday()]})"
        elif report_type == "weekly":
            return f"📈 周报 ({tr.start.strftime('%m-%d')} ~ {now.strftime('%m-%d')})"
        else:
            return f"📅 月报 ({now.strftime('%Y年%m月')})"

    def _run_section(self, module: str, tr: TimeRange) -> Optional[str]:
        handler = {
            "download":     self._section_download,
            "transfer":     self._section_transfer,
            "signin":       self._section_signin,
            "brush":        self._section_brush,
            "downloader":   self._section_downloader,
            "site_delta":   self._section_site_delta,
            "site_current": self._section_site_current,
            "subscribe":    self._section_subscribe,
            "storage":      self._section_storage,
        }.get(module)
        if not handler:
            return None
        try:
            return handler(tr)
        except Exception as e:
            logger.error(f"[DailySummary] 模块 {module} 执行失败: {e}")
            return f"【{MODULES.get(module, module)}】数据读取失败"

    # ─── 各模块实现 ───

    def _section_download(self, tr: TimeRange) -> Optional[str]:
        downloads = self._get_downloads(tr.start_str)
        if not downloads:
            return f"【{tr.prefix}下载】无"

        # 日报：详细列表；周报/月报：分类汇总
        if tr.report_type == "daily":
            lines = [f"【{tr.prefix}下载 {len(downloads)} 部】"]
            for d in downloads:
                ep = f" {d.seasons}{d.episodes}" if d.episodes else (f" {d.seasons}" if d.seasons else "")
                site = f" - {d.torrent_site}" if d.torrent_site else ""
                lines.append(f"  • {d.title}{ep}{site}")
            return "\n".join(lines)

        type_count = {}
        for d in downloads:
            cat = d.media_category or d.type or "其他"
            type_count[cat] = type_count.get(cat, 0) + 1
        type_summary = " | ".join(f"{k} {v}" for k, v in sorted(type_count.items(), key=lambda x: -x[1]))
        return f"【{tr.prefix}下载】共 {len(downloads)} 部\n  {type_summary}"

    def _section_transfer(self, tr: TimeRange) -> Optional[str]:
        transfers = self._get_transfers(tr.start_str)
        success = [t for t in transfers if t.status]
        if not success:
            return f"【{tr.prefix}入库】无"

        # 日报：详细列表；周报/月报：分类汇总
        if tr.report_type == "daily":
            lines = [f"【{tr.prefix}入库 {len(success)} 部】"]
            for t in success:
                ep = f" {t.seasons}{t.episodes}" if t.episodes else (f" {t.seasons}" if t.seasons else "")
                cat = f" → {t.category}" if t.category else ""
                lines.append(f"  • {t.title}{ep}{cat}")
            return "\n".join(lines)

        cat_count = {}
        for t in success:
            cat = t.category or t.type or "其他"
            cat_count[cat] = cat_count.get(cat, 0) + 1
        cat_summary = " | ".join(f"{k} {v}" for k, v in sorted(cat_count.items(), key=lambda x: -x[1]))
        return f"【{tr.prefix}入库】共 {len(success)} 部\n  {cat_summary}"

    def _section_signin(self, tr: TimeRange) -> str:
        pdo = PluginDataOper()
        plugin_id = self._signin_plugin_id or "AutoSignIn"
        now = tr.end
        key = f"{now.month}月{now.day}日"
        data = pdo.get_data(plugin_id, key)
        if not data:
            return "【签到】今日无签到记录"

        signin_records = [r for r in data if "模拟登录" not in r.get("status", "")]
        total = len(signin_records)
        success = sum(1 for r in signin_records if "成功" in r.get("status", ""))
        failed = [r for r in signin_records if "成功" not in r.get("status", "")]

        if success == total:
            return f"【签到】✅ 全部成功 ({success}/{total})"

        fail_sites = ", ".join(r["site"] for r in failed)
        return f"【签到】⚠️ {success}/{total} 成功\n  失败: {fail_sites}"

    def _section_brush(self, tr: TimeRange) -> str:
        pdo = PluginDataOper()
        plugin_ids = [pid.strip() for pid in (self._brush_plugin_ids or "BrushFlow").split(",") if pid.strip()]

        total_uploaded = 0
        total_downloaded = 0
        total_active = 0
        total_deleted = 0
        total_count = 0

        for pid in plugin_ids:
            stat = pdo.get_data(pid, "statistic")
            if not stat:
                continue
            total_uploaded += stat.get("uploaded", 0) + stat.get("active_uploaded", 0)
            total_downloaded += stat.get("downloaded", 0)
            total_active += stat.get("active", 0)
            total_deleted += stat.get("deleted", 0)
            total_count += stat.get("count", 0)

        return (
            f"【刷流】总种: {total_count} | 活跃: {total_active} | 已删: {total_deleted}\n"
            f"  总↑ {_human_size(total_uploaded)} | 总↓ {_human_size(total_downloaded)}"
        )

    def _section_downloader(self, tr: TimeRange) -> Optional[str]:
        """通过 DownloaderHelper 获取所有已配置下载器的概览"""
        try:
            from app.helper.downloader import DownloaderHelper
        except ImportError:
            logger.warning("[DailySummary] DownloaderHelper 不可用")
            return None

        services = DownloaderHelper().get_services()
        if not services:
            return None

        lines = ["【下载器概览】"]
        for name, svc in services.items():
            if not svc or not svc.instance:
                continue
            inst = svc.instance
            completed = inst.get_completed_torrents() or []
            downloading = inst.get_downloading_torrents() or []
            total = len(completed) + len(downloading)
            ti = inst.transfer_info()
            up_speed = ti.get("up_info_speed", 0) if ti else 0
            dl_speed = ti.get("dl_info_speed", 0) if ti else 0
            lines.append(f"  {name}: 种子 {total} | ↑{_human_size(up_speed)}/s | ↓{_human_size(dl_speed)}/s")

        return "\n".join(lines) if len(lines) > 1 else None

    def _section_site_delta(self, tr: TimeRange) -> Optional[str]:
        with ScopedSession() as db:
            start_data = SiteUserData.get_by_date(db, tr.start_date)
            end_data = SiteUserData.get_by_date(db, tr.end_date)

        if not start_data or not end_data:
            return None

        start_map = {d.domain: d for d in start_data}
        end_map = {d.domain: d for d in end_data}

        label = {"daily": "站点增量", "weekly": "站点周增量", "monthly": "站点月增量"}.get(tr.report_type, "站点增量")
        lines = [f"【{label}】", "  站点        ↑上传        ↓下载       魔力变化"]

        has_data = False
        for domain, end in sorted(end_map.items(), key=lambda x: (x[1].upload or 0), reverse=True):
            start = start_map.get(domain)
            if not start:
                continue
            up_delta = (end.upload or 0) - (start.upload or 0)
            down_delta = (end.download or 0) - (start.download or 0)
            bonus_delta = (end.bonus or 0) - (start.bonus or 0)

            no_change = up_delta == 0 and down_delta == 0 and bonus_delta == 0
            data_anomaly = up_delta < 0 or down_delta < 0
            if no_change or data_anomaly:
                continue

            has_data = True
            name = (end.name or domain)[:6].ljust(6)
            bonus_str = f"+{bonus_delta:.0f}" if bonus_delta >= 0 else f"{bonus_delta:.0f}"
            lines.append(f"  {name}  {_human_size(up_delta):>10}  {_human_size(down_delta):>10}  {bonus_str:>8}")

        return "\n".join(lines) if has_data else None

    def _section_site_current(self, tr: TimeRange) -> Optional[str]:
        with ScopedSession() as db:
            data = SiteUserData.get_latest(db)

        if not data:
            return None

        lines = ["【站点数据】", "  站点        总↑          总↓        分享率   魔力"]

        for d in sorted(data, key=lambda x: (x.upload or 0), reverse=True):
            if not d.upload and not d.download:
                continue
            name = (d.name or d.domain)[:6].ljust(6)
            ratio = f"{d.ratio:.2f}" if d.ratio else "∞"
            bonus = f"{d.bonus:.0f}" if d.bonus else "0"
            lines.append(f"  {name}  {_human_size(d.upload or 0):>10}  {_human_size(d.download or 0):>10}  {ratio:>6}  {bonus:>8}")

        return "\n".join(lines) if len(lines) > 2 else None

    def _section_subscribe(self, tr: TimeRange) -> str:
        subs = SubscribeOper().list(state="R") or []
        if not subs:
            return "【订阅进度】无活跃订阅"

        lines = [f"【订阅进度】{len(subs)} 部进行中"]
        for s in subs:
            total = s.total_episode or 0
            lack = s.lack_episode or 0
            done = total - lack
            season = f" S{s.season}" if s.season else ""
            progress = f" {done}/{total}" if total > 0 else ""
            lines.append(f"  • {s.name}{season}{progress}")
        return "\n".join(lines)

    def _section_storage(self, tr: TimeRange) -> Optional[str]:
        volumes = self._parse_storage_paths()
        if not volumes:
            return None

        lines = ["【存储空间】"]
        has_data = False
        for path, label in volumes:
            if not os.path.exists(path):
                continue
            stat = os.statvfs(path)
            total = stat.f_blocks * stat.f_frsize
            used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
            if total == 0:
                continue
            has_data = True
            pct = used / total * 100
            lines.append(f"  {label}: 已用 {_human_size(used)} / {_human_size(total)} ({pct:.0f}%)")
        return "\n".join(lines) if has_data else None

    def _parse_storage_paths(self) -> List[Tuple[str, str]]:
        """解析用户配置的存储路径，或自动检测 MP 的 LIBRARY_PATH / DOWNLOAD_PATH"""
        if self._storage_paths:
            result = []
            for item in self._storage_paths.split(","):
                item = item.strip()
                if ":" in item:
                    path, label = item.split(":", 1)
                    result.append((path.strip(), label.strip()))
                elif item:
                    result.append((item, item))
            return result

        # 自动检测
        paths = []
        if hasattr(settings, "LIBRARY_PATH") and settings.LIBRARY_PATH:
            paths.append((settings.LIBRARY_PATH, "媒体库"))
        if hasattr(settings, "DOWNLOAD_PATH") and settings.DOWNLOAD_PATH:
            paths.append((settings.DOWNLOAD_PATH, "下载目录"))
        return paths

    # ─── 数据查询 ───

    def _get_downloads(self, since: str) -> list:
        try:
            from app.db.models.downloadhistory import DownloadHistory
            with ScopedSession() as db:
                return db.query(DownloadHistory).filter(
                    DownloadHistory.date > since
                ).order_by(DownloadHistory.date.desc()).all()
        except Exception as e:
            logger.error(f"[DailySummary] 查询下载记录失败: {e}")
            return []

    def _get_transfers(self, since: str) -> list:
        try:
            return TransferHistoryOper().list_by_date(since) or []
        except Exception as e:
            logger.error(f"[DailySummary] 查询入库记录失败: {e}")
            return []

    # ─── 发送通知 + 保存历史 ───

    def _send(self, report_type: str, title: str, text: str):
        logger.info(f"[DailySummary] {title}\n{text}")

        if self._notify:
            self.post_message(mtype=NotificationType.Plugin, title=title, text=text)

        # 保存历史记录
        tz = pytz.timezone(settings.TZ)
        now = datetime.now(tz)
        record = {
            "time": now.strftime("%Y-%m-%d %H:%M"),
            "type": report_type,
            "title": title,
            "text": text,
        }
        history = self.get_data("history") or []
        history.append(record)
        # 保留最近 MAX_HISTORY 条
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        self.save_data("history", history)


# ─── 工具函数 ───

def _human_size(size_bytes: float) -> str:
    if size_bytes is None or size_bytes == 0:
        return "0 B"
    negative = size_bytes < 0
    size_bytes = abs(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if size_bytes < 1024:
            formatted = f"{size_bytes:.1f} {unit}" if size_bytes != int(size_bytes) else f"{int(size_bytes)} {unit}"
            return f"-{formatted}" if negative else formatted
        size_bytes /= 1024
    return f"{size_bytes:.1f} EB"
