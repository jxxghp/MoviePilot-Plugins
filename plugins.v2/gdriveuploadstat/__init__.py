import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.db.transferhistory_oper import TransferHistoryOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType


class GDriveUploadStat(_PluginBase):
    # ==================== 插件基本信息 ====================
    plugin_name = "网盘上传量统计"
    plugin_desc = "按盘符统计整理记录的落盘数据量，达到自定义阈值走通知频道告警（自用/gclone多盘限额监控）。"
    plugin_icon = "Alidrive_A.png"
    plugin_version = "1.0.0"
    plugin_author = "lkwang88"
    author_url = "https://github.com/Lkwang88"
    plugin_config_prefix = "gdriveuploadstat_"
    plugin_order = 21
    auth_level = 1

    # ==================== 运行时状态 ====================
    _enabled = False
    _notify = True
    _onlyonce = False
    _stat_mode = "day"          # day=自然日  rolling=滚动近N小时
    _day_boundary = "00:00"     # 自然日起算时间 HH:MM
    _rolling_hours = 24         # 滚动窗口小时数
    _cron = "*/30 * * * *"      # 检查频率
    _multi_level = True         # 多级预警 80%/95%/100%
    _rules_raw = ""             # 盘符规则原文

    _scheduler: Optional[BackgroundScheduler] = None

    # 计入的整理模式（英文为库内实际存储值，中文为兼容）
    _COUNT_MODES = {"move", "copy", "移动", "复制"}
    # 多级预警档位
    _LEVELS = [(1.0, "🔴 已超限"), (0.95, "🟠 接近上限"), (0.8, "🟡 提醒")]

    def init_plugin(self, config: dict = None):
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._notify = bool(config.get("notify", True))
        self._onlyonce = bool(config.get("onlyonce"))
        self._stat_mode = config.get("stat_mode") or "day"
        self._day_boundary = (config.get("day_boundary") or "00:00").strip()
        try:
            self._rolling_hours = int(config.get("rolling_hours") or 24)
        except (TypeError, ValueError):
            self._rolling_hours = 24
        self._cron = (config.get("cron") or "*/30 * * * *").strip()
        self._multi_level = bool(config.get("multi_level", True))
        self._rules_raw = config.get("rules") or ""

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"{self.plugin_name} 立即运行一次")
            self._scheduler.add_job(
                func=self.check,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name=f"{self.plugin_name}_立即运行",
            )
            self._onlyonce = False
            self._save_config()
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def _save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "stat_mode": self._stat_mode,
            "day_boundary": self._day_boundary,
            "rolling_hours": self._rolling_hours,
            "cron": self._cron,
            "multi_level": self._multi_level,
            "rules": self._rules_raw,
        })

    # ==================== 规则解析 ====================
    def _parse_rules(self) -> List[Dict[str, Any]]:
        """
        解析盘符规则文本，每行：显示名,盘符,阈值GB
        支持中文逗号；显示名可留空（用盘符代替）；阈值可留空/0（不告警）。
        """
        rules = []
        for line in (self._rules_raw or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[,，]", line)
            parts = [p.strip() for p in parts]
            if len(parts) < 2 or not parts[1]:
                logger.warning(f"{self.plugin_name} 规则行格式不正确，已跳过：{line}")
                continue
            name = parts[0] or parts[1]
            keyword = parts[1]
            threshold_gb = 0.0
            if len(parts) >= 3 and parts[2]:
                try:
                    threshold_gb = float(parts[2])
                except ValueError:
                    logger.warning(f"{self.plugin_name} 阈值不是数字，按0处理：{line}")
            rules.append({"name": name, "keyword": keyword, "threshold_gb": threshold_gb})
        return rules

    # ==================== 时间窗口 ====================
    def _window_start(self) -> Tuple[datetime, datetime]:
        """返回 (窗口起点, 当前时间)。"""
        tz = pytz.timezone(settings.TZ)
        now = datetime.now(tz=tz)
        if self._stat_mode == "rolling":
            return now - timedelta(hours=self._rolling_hours), now
        # 自然日
        try:
            hh, mm = [int(x) for x in self._day_boundary.split(":")]
        except (ValueError, AttributeError):
            hh, mm = 0, 0
        boundary_today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        start = boundary_today if now >= boundary_today else boundary_today - timedelta(days=1)
        return start, now

    @staticmethod
    def _size_of(history) -> Tuple[int, bool]:
        """取单条记录落盘字节数：dest 优先，其次 src。返回 (字节, 是否计量成功)。"""
        for fileitem in (history.dest_fileitem, history.src_fileitem):
            if isinstance(fileitem, dict):
                size = fileitem.get("size")
                if size:
                    try:
                        return int(size), True
                    except (TypeError, ValueError):
                        continue
        return 0, False

    @staticmethod
    def _match_disk(dest: Optional[str], src: Optional[str], keyword: str) -> bool:
        """盘符匹配：优先 dest 路径段 /keyword/，兜底 src。"""
        seg = f"/{keyword}/"
        for path in (dest, src):
            if path and seg in path:
                return True
        return False

    @staticmethod
    def _fmt(size_bytes: float) -> str:
        gib = size_bytes / (1024 ** 3)
        if gib >= 1:
            return f"{gib:.2f} GB"
        return f"{size_bytes / (1024 ** 2):.2f} MB"

    # ==================== 核心统计 ====================
    def _collect(self) -> Tuple[Dict[str, Dict[str, Any]], datetime, datetime]:
        rules = self._parse_rules()
        start, now = self._window_start()
        stats = {
            r["keyword"]: {
                "name": r["name"], "keyword": r["keyword"], "threshold_gb": r["threshold_gb"],
                "bytes": 0, "count": 0, "nosize": 0,
            } for r in rules
        }
        if not rules:
            return stats, start, now

        start_str = start.strftime("%Y-%m-%d %H:%M:%S")
        records = TransferHistoryOper().list_by_date(start_str) or []
        for h in records:
            if not h.status:
                continue
            if (h.mode or "").lower() not in {m.lower() for m in self._COUNT_MODES}:
                continue
            for r in rules:
                if self._match_disk(h.dest, h.src, r["keyword"]):
                    size, ok = self._size_of(h)
                    bucket = stats[r["keyword"]]
                    bucket["count"] += 1
                    if ok:
                        bucket["bytes"] += size
                    else:
                        bucket["nosize"] += 1
                    break  # 一条记录只归一个盘
        return stats, start, now

    def check(self):
        """定时任务入口：统计 + 阈值告警 + 快照。"""
        try:
            stats, start, now = self._collect()
        except Exception as e:
            logger.error(f"{self.plugin_name} 统计失败：{e}")
            return

        if not stats:
            logger.info(f"{self.plugin_name} 未配置盘符规则，跳过")
            return

        # 快照，供详情页展示
        snapshot = {
            "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": self._stat_mode,
            "disks": list(stats.values()),
        }
        self.save_data("snapshot", snapshot)

        # 每日告警去重：{日期: {盘: [已发档位]}}
        day_key = start.strftime("%Y-%m-%d")
        alerted = self.get_data("alerted") or {}
        today_alerted = alerted.get(day_key, {})

        for keyword, s in stats.items():
            threshold_gb = s["threshold_gb"]
            if not threshold_gb or threshold_gb <= 0:
                continue
            used_gb = s["bytes"] / (1024 ** 3)
            ratio = used_gb / threshold_gb if threshold_gb else 0
            levels = self._LEVELS if self._multi_level else [self._LEVELS[0]]
            sent = today_alerted.get(keyword, [])
            for level_ratio, label in levels:
                if ratio >= level_ratio and level_ratio not in sent:
                    self._notify_disk(s, used_gb, ratio, label, start, now)
                    sent.append(level_ratio)
                    break  # 一次只发命中的最高档
            today_alerted[keyword] = sent

        alerted[day_key] = today_alerted
        # 只保留最近 7 天去重记录
        for k in sorted(alerted.keys())[:-7]:
            alerted.pop(k, None)
        self.save_data("alerted", alerted)
        logger.info(f"{self.plugin_name} 统计完成，覆盖 {len(stats)} 个盘")

    def _notify_disk(self, s: Dict[str, Any], used_gb: float, ratio: float,
                     label: str, start: datetime, now: datetime):
        if not self._notify:
            return
        threshold_gb = s["threshold_gb"]
        text = (
            f"今日已上传：{used_gb:.2f} GB / {threshold_gb:g} GB ({ratio*100:.0f}%)  {label}\n"
            f"统计区间：{start.strftime('%m-%d %H:%M')} ~ {now.strftime('%m-%d %H:%M')}\n"
            f"计入记录：{s['count']} 条（移动/复制）"
        )
        if s["nosize"]:
            text += f"，未计量 {s['nosize']} 条"
        self.post_message(
            mtype=NotificationType.Plugin,
            title=f"📊 网盘上传量告警 [{s['name']}]",
            text=text,
        )

    # ==================== 服务注册 ====================
    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except Exception as e:
            logger.error(f"{self.plugin_name} cron 表达式无效：{self._cron}，{e}")
            return []
        return [{
            "id": f"{self.__class__.__name__}.Check",
            "name": f"{self.plugin_name}定时统计",
            "trigger": trigger,
            "func": self.check,
            "kwargs": {},
        }]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self):
        if self._scheduler:
            try:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
            except Exception as e:
                logger.error(f"{self.plugin_name} 停止调度器失败：{e}")
            self._scheduler = None

    # ==================== 配置页 ====================
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                             "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                             "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "发送通知"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                             "content": [{"component": "VSwitch", "props": {"model": "multi_level", "label": "多级预警(80/95/100%)"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                             "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                             "content": [{"component": "VSelect", "props": {
                                 "model": "stat_mode", "label": "统计模式",
                                 "items": [
                                     {"title": "自然日（推荐）", "value": "day"},
                                     {"title": "滚动近N小时", "value": "rolling"},
                                 ]}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                             "content": [{"component": "VTextField", "props": {
                                 "model": "day_boundary", "label": "自然日起算时间 HH:MM", "placeholder": "00:00"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                             "content": [{"component": "VTextField", "props": {
                                 "model": "rolling_hours", "label": "滚动窗口小时数", "placeholder": "24"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4},
                             "content": [{"component": "VTextField", "props": {
                                 "model": "cron", "label": "检查频率 (cron)", "placeholder": "*/30 * * * *"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12},
                             "content": [{"component": "VTextarea", "props": {
                                 "model": "rules",
                                 "label": "盘符规则（每行一个：显示名,盘符,阈值GB）",
                                 "rows": 6,
                                 "placeholder": "LK01盘,LK01,700\nLK02盘,LK02,2000\nGd01盘,Gd01,2000"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12},
                             "content": [{"component": "VAlert", "props": {
                                 "type": "info", "variant": "tonal",
                                 "text": "盘符原样填路径里那一段（区分大小写，不加斜杠），如 LK01。"
                                         "阈值纯数字单位GB(1024进制)，留空或0=不告警。"
                                         "统计口径：整理成功 + 移动/复制模式，按盘符对目标路径匹配求和。"}}]},
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "multi_level": True,
            "stat_mode": "day",
            "day_boundary": "00:00",
            "rolling_hours": 24,
            "cron": "*/30 * * * *",
            "rules": "",
        }

    # ==================== 详情页 ====================
    def get_page(self) -> List[dict]:
        snapshot = self.get_data("snapshot") or {}
        disks = snapshot.get("disks", [])
        if not disks:
            return [{"component": "VAlert", "props": {
                "type": "info", "variant": "tonal",
                "text": "暂无统计数据，请先配置盘符规则并等待定时任务运行（或勾选“立即运行一次”）。"}}]

        rows = []
        for d in disks:
            used_gb = d["bytes"] / (1024 ** 3)
            threshold = d.get("threshold_gb") or 0
            ratio = (used_gb / threshold * 100) if threshold else 0
            if not threshold:
                status = "—"
            elif ratio >= 100:
                status = "🔴"
            elif ratio >= 95:
                status = "🟠"
            elif ratio >= 80:
                status = "🟡"
            else:
                status = "🟢"
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": d["name"]},
                    {"component": "td", "text": self._fmt(d["bytes"])},
                    {"component": "td", "text": f"{threshold:g} GB" if threshold else "未设"},
                    {"component": "td", "text": f"{ratio:.0f}%" if threshold else "—"},
                    {"component": "td", "text": status},
                    {"component": "td", "text": str(d["count"])},
                ],
            })

        return [
            {"component": "VAlert", "props": {
                "type": "success", "variant": "tonal",
                "text": f"统计区间 {snapshot.get('start')} ~ {snapshot.get('updated')}"
                        f"（模式：{'自然日' if snapshot.get('mode') == 'day' else '滚动窗口'}）"}},
            {"component": "VTable", "props": {"hover": True}, "content": [
                {"component": "thead", "content": [{"component": "tr", "content": [
                    {"component": "th", "text": "盘"},
                    {"component": "th", "text": "已上传"},
                    {"component": "th", "text": "阈值"},
                    {"component": "th", "text": "占比"},
                    {"component": "th", "text": "状态"},
                    {"component": "th", "text": "记录数"},
                ]}]},
                {"component": "tbody", "content": rows},
            ]},
        ]
