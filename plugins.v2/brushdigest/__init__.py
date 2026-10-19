import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.db.plugindata_oper import PluginDataOper
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import SystemConfigKey

# 插件根目录：本文件位于 <plugins_root>/brushdigest/__init__.py
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# 扫描单个插件源码时的体积上限，避免读到巨型文件
_MAX_SCAN_BYTES = 2 * 1024 * 1024
# 单任务版刷流插件：全局 statistic 键
_GLOBAL_STAT_RE = re.compile(r"""save_data\(\s*['"]statistic['"]""")
# 多任务版刷流插件：task.<id>.statistic 键
_MULTI_STAT_FLAG = "task.{task_id}.{data_name}"


def _human_size(value: Any) -> str:
    """把字节数格式化成可读单位"""
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} EB"


def _fmt_span(start_ts: Optional[float], end_ts: float) -> str:
    """把时间跨度格式化成中文描述"""
    if not start_ts:
        return "上次汇总以来"
    minutes = max(1, int((end_ts - start_ts) / 60))
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f} 小时"
    return f"{hours / 24:.1f} 天"


def _plugin_display_name(plugin_id: str, source: str) -> str:
    """从插件源码里取中文插件名，取不到就用 ID"""
    match = re.search(r"""plugin_name\s*=\s*['"]([^'"]+)['"]""", source)
    return match.group(1) if match else plugin_id


def _alert(kind: str, lines: List[str]) -> Dict[str, Any]:
    """构造多行提示框"""
    return {
        "component": "VAlert",
        "props": {
            "type": kind,
            "variant": "tonal",
            "density": "comfortable",
            "class": "mb-2",
        },
        "content": [
            {"component": "span", "props": {"class": "d-block"}, "text": line}
            for line in lines
        ],
    }


def _plugin_dirs() -> Dict[str, Path]:
    """
    插件目录映射：小写目录名 -> 实际目录。
    配置里记的插件 ID（如 BrushFlowLowFreq）与磁盘目录名（brushflowlowfreq）
    大小写经常不一致，必须做一次大小写无关的匹配。
    """
    mapping: Dict[str, Path] = {}
    try:
        for child in PLUGIN_ROOT.iterdir():
            if child.is_dir() and not child.name.startswith("__"):
                mapping[child.name.lower()] = child
    except OSError as err:
        logger.warning(f"【刷流汇总】扫描插件目录失败：{err}")
    return mapping


def detect_source_plugins() -> List[Dict[str, str]]:
    """
    自动检测本机已安装、且会产出 statistic 统计数据的刷流插件。
    普通用户不需要去翻插件 ID，直接从下拉框选中文名即可。
    """
    try:
        installed = SystemConfigOper().get(SystemConfigKey.UserInstalledPlugins) or []
    except Exception as err:
        logger.warning(f"【刷流汇总】读取已安装插件列表失败：{err}")
        installed = []
    if not isinstance(installed, list):
        installed = []

    items: List[Dict[str, str]] = []
    seen = set()
    dirs = _plugin_dirs()
    for plugin_id in installed:
        if not isinstance(plugin_id, str) or not plugin_id or plugin_id in seen:
            continue
        seen.add(plugin_id)
        if plugin_id == "BrushDigest":
            continue

        plugin_dir = dirs.get(plugin_id.lower())
        if not plugin_dir:
            continue
        init_file = plugin_dir / "__init__.py"
        try:
            if not init_file.is_file() or init_file.stat().st_size > _MAX_SCAN_BYTES:
                continue
            source = init_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        # 必须真的读写统计字段，才算刷流类插件
        if not (_GLOBAL_STAT_RE.search(source) or _MULTI_STAT_FLAG in source):
            continue

        items.append({
            "title": f"{_plugin_display_name(plugin_id, source)}（{plugin_id}）",
            "value": plugin_id,
        })

    items.sort(key=lambda item: item["title"])
    return items


class BrushDigest(_PluginBase):
    """把刷流插件的新增/删除汇总成一条通知"""

    plugin_name = "刷流汇总"
    plugin_desc = "把站点刷流的新增/删除汇总成一条通知，替代每个种子一条的逐条推送"
    plugin_icon = "https://raw.githubusercontent.com/IceNoproblem/MoviePilot-Plugins/main/icons/brushdigest.png"
    plugin_version = "1.1.0"
    plugin_author = "icenoproblem"
    author_url = "https://github.com/IceNoproblem/MoviePilot-Plugins"
    plugin_config_prefix = "brushdigest_"
    plugin_order = 31
    auth_level = 1

    _enabled: bool = False
    _notify: bool = True
    _cron: str = "*/10 * * * *"
    _skip_empty: bool = True
    _show_size: bool = True
    _source_plugin: str = "BrushFlowLowFreq"
    # 保存后立即推送一次，用完自动复位
    _onlyonce: bool = False

    def init_plugin(self, config: Optional[dict] = None):
        if config:
            self._enabled = bool(config.get("enabled", False))
            self._notify = bool(config.get("notify", True))
            self._cron = str(config.get("cron") or "*/10 * * * *").strip()
            self._skip_empty = bool(config.get("skip_empty", True))
            self._show_size = bool(config.get("show_size", True))
            self._source_plugin = str(
                config.get("source_plugin") or "BrushFlowLowFreq"
            ).strip()
            self._onlyonce = bool(config.get("onlyonce", False))

        if self._onlyonce:
            self._onlyonce = False
            self.update_config(self._config())
            logger.info("【刷流汇总】收到立即推送指令，3 秒后执行一次汇总")
            scheduler = BackgroundScheduler(timezone=settings.TZ)
            scheduler.add_job(
                func=self._digest,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                + timedelta(seconds=3),
                kwargs={"force": True},
                name="刷流汇总立即推送",
            )
            scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def _config(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "notify": self._notify,
            "cron": self._cron,
            "skip_empty": self._skip_empty,
            "show_size": self._show_size,
            "source_plugin": self._source_plugin,
            # 复位为 False，避免每次重启重复推送
            "onlyonce": False,
        }

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        source_items = detect_source_plugins()
        if not source_items:
            # 一个都没检测到时给个兜底项，用户仍可正常保存
            source_items = [{
                "title": "未检测到刷流插件（请先安装并启用站点刷流）",
                "value": "BrushFlowLowFreq",
            }]
        else:
            # 保证当前配置值一定在选项里，否则下拉框会显示空白
            values = [item["value"] for item in source_items]
            if self._source_plugin not in values:
                source_items.append({
                    "title": f"{self._source_plugin}（当前配置）",
                    "value": self._source_plugin,
                })

        return [
            {
                "component": "VForm",
                "content": [
                    # ── 使用说明 ──────────────────────────────
                    {
                        "component": "VRow",
                        "content": [{
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                _alert("info", [
                                    "本插件只做汇总，不刷流、不改动任何种子，可以放心长期开启。",
                                    "数据来源已自动检测，从下方下拉框选择中文插件名即可，不需要手填插件 ID。",
                                    "支持的插件：站点刷流（多任务版 BrushFlow）与站点刷流（低频版 BrushFlowLowFreq）。",
                                ]),
                                _alert("warning", [
                                    "重要：必须先把原刷流插件的「发送通知」关掉，否则每个种子仍会单独推送，汇总就白做了。",
                                    "① BrushFlowLowFreq：插件设置页 → 取消勾选「发送通知」→ 保存。",
                                    "② BrushFlow（多任务版）：插件设置页 → 在任务列表里逐个编辑任务 → 关闭该任务的「发送通知」→ 保存。",
                                    "③ 两个刷流插件都装了的话，两个都要关（哪个在用就关哪个）。",
                                    "④ 关掉原插件通知后，由本插件统一按下面的周期推送一条汇总。",
                                ]),
                            ],
                        }],
                    },
                    # ── 开关组 ────────────────────────────────
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "notify", "label": "发送通知"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "skip_empty", "label": "无变化不推送"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "show_size", "label": "显示流量"},
                                }],
                            },
                        ],
                    },
                    # ── 周期 / 来源 / 立即推送 ─────────────────
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VCronField",
                                    "props": {
                                        "model": "cron",
                                        "label": "汇总周期",
                                        "placeholder": "*/10 * * * *",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 5},
                                "content": [{
                                    "component": "VSelect",
                                    "props": {
                                        "model": "source_plugin",
                                        "label": "数据来源插件",
                                        "items": source_items,
                                        "hint": "已列出本机已安装的刷流插件，选中文名即可",
                                        "persistentHint": True,
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {
                                        "model": "onlyonce",
                                        "label": "立即汇总推送一次",
                                        "hint": "保存后立刻推一条，之后按周期自动推送",
                                        "persistentHint": True,
                                    },
                                }],
                            },
                        ],
                    },
                    # ── 立即推送说明 ──────────────────────────
                    {
                        "component": "VRow",
                        "content": [{
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                _alert("success", [
                                    "「立即汇总推送一次」：勾选并保存后 3 秒内推一条，用来验证通知渠道是否正常，开关会自动复位。",
                                    "统计口径是「距上次汇总以来的变化」，所以立即推送看到的就是这段时间的新增/删除数量。",
                                    "自检时如果「发送通知」是关的，只会写入日志不会真的推送。",
                                ]),
                            ],
                        }],
                    },
                ],
            }
        ], self._config()

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError as err:
            logger.error(f"【刷流汇总】CRON 表达式无效：{self._cron}（{err}）")
            return []
        return [{
            "id": "BrushDigest",
            "name": "刷流汇总推送",
            "trigger": trigger,
            "func": self._digest,
            "kwargs": {},
        }]

    def get_page(self) -> List[dict]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self):
        pass

    # ── 读取来源插件统计 ────────────────────────────────
    def _collect(self) -> Optional[Dict[str, Any]]:
        """
        读取来源插件的累计统计，兼容两种存储结构：
        1. 单任务版：plugin_data 里一条 statistic
        2. 多任务版：task.<任务ID>.statistic 每任务一条，需要求和
        """
        oper = PluginDataOper()

        # 1) 单任务版
        try:
            stat = oper.get_data(self._source_plugin, "statistic") or {}
        except Exception as err:
            logger.error(f"【刷流汇总】读取 {self._source_plugin} 统计失败：{err}")
            return None
        if isinstance(stat, dict) and stat:
            return {
                "count": int(stat.get("count") or 0),
                "deleted": int(stat.get("deleted") or 0),
                "active": int(stat.get("active") or 0),
                "uploaded": float(stat.get("uploaded") or 0),
                "downloaded": float(stat.get("downloaded") or 0),
            }

        # 2) 多任务版：把所有任务的统计加起来
        try:
            all_data = oper.get_data_all(self._source_plugin) or {}
        except Exception as err:
            logger.error(f"【刷流汇总】读取 {self._source_plugin} 任务数据失败：{err}")
            return None

        rows = [
            value for key, value in all_data.items()
            if isinstance(key, str)
            and key.startswith("task.")
            and key.endswith(".statistic")
            and isinstance(value, dict)
        ]
        if not rows:
            return None

        total = {
            "count": 0,
            "deleted": 0,
            "active": 0,
            "uploaded": 0.0,
            "downloaded": 0.0,
        }
        for row in rows:
            total["count"] += int(row.get("count") or 0)
            total["deleted"] += int(row.get("deleted") or 0)
            total["active"] += int(row.get("active") or 0)
            total["uploaded"] += float(row.get("uploaded") or 0)
            total["downloaded"] += float(row.get("downloaded") or 0)
        return total

    def _digest(self, force: bool = False):
        """读取刷流统计，与上次快照做差，汇总推送一条"""
        if not self._enabled and not force:
            return

        current = self._collect()
        if not current:
            logger.info(f"【刷流汇总】{self._source_plugin} 暂无统计数据，本次跳过")
            return

        now = datetime.now().timestamp()
        current["ts"] = now

        try:
            previous = self.get_data("snapshot") or {}
        except Exception:
            previous = {}

        first_run = not previous or "count" not in previous
        if first_run:
            delta_count = delta_deleted = 0
            delta_up = delta_down = 0.0
            span = "启动以来"
        else:
            delta_count = max(0, current["count"] - int(previous.get("count") or 0))
            delta_deleted = max(0, current["deleted"] - int(previous.get("deleted") or 0))
            delta_up = max(0.0, current["uploaded"] - float(previous.get("uploaded") or 0))
            delta_down = max(0.0, current["downloaded"] - float(previous.get("downloaded") or 0))
            span = _fmt_span(previous.get("ts"), now)

        changed = bool(delta_count or delta_deleted or delta_up or delta_down)

        if first_run:
            lines = [
                "已开始统计",
                f"当前累计：新增 {current['count']} · 删除 {current['deleted']} · 活跃 {current['active']}",
                f"之后按 {self._cron} 自动汇总推送",
            ]
        else:
            lines = [
                f"近 {span}",
                f"新增 {delta_count} 个 · 删除 {delta_deleted} 个",
                f"当前活跃 {current['active']} · 累计新增 {current['count']} / 删除 {current['deleted']}",
            ]
            if self._show_size:
                lines.append(f"流量 ↑ {_human_size(delta_up)} · ↓ {_human_size(delta_down)}")

        text = "\n".join(lines)
        logger.info(f"【刷流汇总】{text.replace(chr(10), ' / ')}")

        # 立即推送时忽略「无变化不推送」，其余情况照旧
        should_push = first_run or changed or force or not self._skip_empty
        if should_push and self._notify:
            try:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title="【刷流汇总】",
                    text=text,
                )
            except Exception as err:
                logger.error(f"【刷流汇总】发送通知失败：{err}")
        elif should_push and not self._notify:
            logger.info("【刷流汇总】未开启「发送通知」，本条仅写入日志")

        if first_run or should_push:
            self.save_data("snapshot", current)
        else:
            logger.info("【刷流汇总】无变化，跳过推送，时间窗继续累积")
