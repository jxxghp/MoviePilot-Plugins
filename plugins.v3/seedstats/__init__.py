"""站点保种统计插件：按 tracker 汇总各站点做种情况，并合并站点账户信息。

统计在后台线程定时计算并缓存，页面与仪表板只读缓存，避免拖慢 Web 界面。
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.db.oper.site import SiteOper
from app.schemas.types import EventType
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.network import SitesHelper
from app.sdk.plugin import _PluginBase
from app.sdk.services import DownloaderHelper
from app.sdk.utilities import StringUtils

# 做种状态（Transmission 的 status 与 qBittorrent 的 state 都归一到这一张表）
_SEEDING_STATES = {
    "seeding", "seed pending", "seed_pending",
    "uploading", "stalledup", "queuedup", "forcedup", "checkingup",
}
# 暂停状态
_PAUSED_STATES = {
    "stopped", "paused", "pausedup", "stoppedup", "pauseddl", "stoppeddl",
}
# 辅种任务标签
_CROSS_SEED_TAG = "辅种"
# 缓存键
_CACHE_KEY = "stats"
# 自建魔力快照键
_BONUS_KEY = "bonus_history"
# 旧版趋势数据键（升级后用于补齐历史趋势点）
_HISTORY_KEY = "history"
# 自建估算允许的窗口（小时）
_MIN_HOURLY_WINDOW = 0.5
_MAX_HOURLY_WINDOW = 12.0
# 自建魔力快照保留时长（小时）
_BONUS_KEEP_HOURS = 72
# 魔力快照最多保留点数
_BONUS_MAX_POINTS = 400
# 趋势数据保留小时（14 天）
_HISTORY_KEEP_HOURS = 24 * 14
# 趋势数据最多保留点数
_HISTORY_MAX_POINTS = 400
# 站点数据默认过期阈值（小时）
_DEFAULT_STALE_HOURS = 24
# 站点状态文本
_STATUS_OK = "正常"
_STATUS_STALE = "数据过期"
_STATUS_IDLE = "零做种"


class SeedStats(_PluginBase):
    """站点保种统计插件。

    后台按配置周期读取下载器任务，按 tracker 归属统计各站点的做种数、
    辅种数、做种体积，并合并 MoviePilot 站点数据中的上传/下载/分享率/
    等级/魔力等信息；结果缓存后由插件详情页与首页仪表板展示。插件只读。
    """

    plugin_name = "站点保种统计"
    plugin_desc = "按 tracker 汇总各站点做种/辅种数量与做种体积，合并站点账户信息（上传/下载/分享率/等级/魔力/时魔估算），并给出数据过期与零做种告警。"
    plugin_icon = (
        "https://raw.githubusercontent.com/jxxghp/MoviePilot-Frontend/refs/heads/v2/src/assets/images/misc/statistic.png"
    )
    plugin_version = "1.6.0"
    plugin_label = "站点,做种,统计"
    plugin_author = "miguelito39721"
    plugin_config_prefix = "seedstats_"
    plugin_order = 26
    auth_level = 1

    _enabled: bool = False
    _downloaders: List[str] = []
    _dashboard: bool = True
    _interval: int = 60
    _stale_hours: int = _DEFAULT_STALE_HOURS
    _include_removed: bool = False
    _refreshing: bool = False
    # 站点域名前缀到站点名的兜底映射
    _site_prefixes: Dict[str, str] = {}
    # 用户手动配置的 tracker 域名到站点名映射
    _site_mapping: Dict[str, str] = {}

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """根据插件配置初始化运行状态，并安排一次立即统计。"""
        self.stop_service()
        self._enabled = False
        self._downloaders = []
        self._dashboard = True
        self._interval = 60
        self._stale_hours = _DEFAULT_STALE_HOURS
        self._include_removed = False
        self._site_mapping = {}
        if config:
            self._enabled = bool(config.get("enabled"))
            self._downloaders = [str(name) for name in (config.get("downloaders") or []) if name]
            self._dashboard = bool(config.get("dashboard", True))
            self._interval = self.__bounded_int(config.get("interval"), 60, 5, 1440)
            self._stale_hours = self.__bounded_int(
                config.get("stale_hours"), _DEFAULT_STALE_HOURS, 1, 720
            )
            self._include_removed = bool(config.get("include_removed"))
            self._site_mapping = self.__parse_site_mapping(config.get("site_mapping"))
        if self._enabled:
            self.__schedule_once()

    def get_state(self) -> bool:
        """返回插件是否已启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表（/保种统计 输出当前缓存汇总）。"""
        return [
            {
                "cmd": "/保种统计",
                "event": EventType.PluginAction,
                "desc": "站点保种统计汇总",
                "category": "",
                "data": {"action": "seedstats_summary"},
            }
        ]

    @eventmanager.register(EventType.PluginAction)
    def remote_summary(self, event: Event) -> None:
        """响应远程命令，推送当前统计汇总。"""
        if not event or not isinstance(event.event_data, dict):
            return
        if event.event_data.get("action") != "seedstats_summary":
            return
        self.post_message(
            channel=event.event_data.get("channel"),
            title="站点保种统计",
            text=self.__summary_text(),
            userid=event.event_data.get("user"),
        )

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 列表（本插件无需额外 API）。"""
        return []

    def get_service(self) -> Optional[List[Dict[str, Any]]]:
        """注册后台定时刷新统计缓存的服务。"""
        if not self._enabled:
            return []
        return [
            {
                "id": f"{self.__class__.__name__}Refresh",
                "name": "站点保种统计刷新",
                "trigger": "interval",
                "func": self.__refresh_cache,
                "kwargs": {"minutes": self._interval},
            }
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回插件配置表单与默认配置。"""
        downloader_items = [
            {"title": name, "value": name}
            for name in (DownloaderHelper().get_configs() or {}).keys()
        ]
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {"component": "VSwitch",
                                     "props": {"model": "enabled", "label": "启用插件"}}
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {"component": "VSwitch",
                                     "props": {"model": "dashboard", "label": "显示首页仪表板"}}
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {"component": "VTextField",
                                     "props": {"model": "interval", "label": "刷新间隔(分钟)",
                                               "placeholder": "60"}}
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {"component": "VSelect",
                                     "props": {"model": "downloaders", "label": "统计的下载器",
                                               "multiple": True, "chips": True, "clearable": True,
                                               "hint": "不选则统计全部已启用下载器",
                                               "persistentHint": True, "items": downloader_items}}
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VTextField",
                                     "props": {"model": "stale_hours", "label": "站点数据过期阈值(小时)",
                                               "placeholder": str(_DEFAULT_STALE_HOURS),
                                               "hint": "站点数据超过该时长未更新会在页面提示",
                                               "persistentHint": True}}
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {"component": "VSwitch",
                                     "props": {"model": "include_removed",
                                               "label": "合计包含已删除站点",
                                               "hint": "关闭时只统计当前配置的站点",
                                               "persistentHint": True}}
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {"component": "VTextarea",
                                     "props": {"model": "site_mapping", "label": "tracker 站点映射",
                                               "rows": 3, "placeholder": "bgp.technology=BGP\npt.example.com=示例站",
                                               "hint": "每行一条「tracker 域名=站点名」，用于修正未识别的 tracker 归属",
                                               "persistentHint": True}}
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {"component": "VAlert",
                                     "props": {"type": "info", "variant": "tonal",
                                               "text": "只读插件：统计在后台线程定时计算并缓存，页面/仪表板读缓存秒出。"
                                                       "账户信息取自 MoviePilot 站点数据（上传/下载/分享率/等级/魔力）。"
                                                       "「时魔*」优先用插件自建的魔力快照估算（0.5~12 小时窗口），"
                                                       "首次运行回退到站点数据的日级快照（标记为粗估），非站点官方数值。"
                                                       "保存配置后会立即重新统计一次。"}}
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "dashboard": True,
            "interval": 60,
            "downloaders": [],
            "stale_hours": _DEFAULT_STALE_HOURS,
            "include_removed": False,
            "site_mapping": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回插件详情页面（读取缓存快照）。"""
        if not self._enabled:
            return [
                {"component": "VAlert",
                 "props": {"type": "warning", "variant": "tonal", "text": "插件未启用，请先在配置中启用。"}}
            ]
        cached = self.__cached()
        rows = cached.get("rows") or []
        totals = cached.get("totals") or {}
        freshness = self.__cache_alert(cached)
        if not rows:
            return [
                {"component": "VAlert",
                 "props": {"type": "warning" if freshness else "info", "variant": "tonal",
                           "text": freshness or "首次统计进行中，请稍等十几秒后重新打开本页面。"}}
            ]

        alerts = cached.get("alerts") or []
        top_rows = rows[:12]
        cross_seed = totals.get("辅种", 0)
        normal_seed = max(totals.get("做种", 0) - cross_seed, 0)
        bar_options = {
            "chart": {"type": "bar", "toolbar": {"show": False}},
            "plotOptions": {"bar": {"horizontal": True, "borderRadius": 4}},
            "dataLabels": {"enabled": False},
            "xaxis": {"categories": [row.get("站点") for row in top_rows]},
            "legend": {"show": False},
            "noData": {"text": "暂无数据"},
        }
        bar_series = [{"name": "做种数", "data": [row.get("做种", 0) for row in top_rows]}]
        pie_options = {
            "chart": {"type": "pie"},
            "labels": ["辅种（做种中）", "普通做种"],
            "legend": {"show": True},
            "noData": {"text": "暂无数据"},
        }

        headers = ("站点", "做种", "辅种", "辅种暂停", "做种体积", "上传", "下载",
                   "分享率", "等级", "魔力", "时魔*", "效率*", "状态", "数据时间")
        content: List[dict] = [
            {
                "component": "VRow",
                "content": [
                    self.__card("站点数", str(totals.get("站点数", 0)), "mdi-server-network", 6, 2),
                    self.__card("任务总数", str(totals.get("任务数", 0)), "mdi-database", 6, 2),
                    self.__card("做种中", str(totals.get("做种", 0)), "mdi-upload", 6, 2),
                    self.__card("辅种（做种中）", str(cross_seed), "mdi-content-duplicate", 6, 2),
                    self.__card("做种体积", self.__format_size(totals.get("体积", 0)), "mdi-harddisk", 6, 2),
                    self.__card("总上传", self.__format_size(totals.get("上传", 0)), "mdi-cloud-upload", 6, 2),
                ],
            }
        ]
        if freshness:
            content.append(
                {
                    "component": "VAlert",
                    "props": {"type": "warning", "variant": "tonal", "class": "mt-3",
                              "title": "数据新鲜度", "text": freshness},
                }
            )
        if alerts:
            content.append(
                {
                    "component": "VAlert",
                    "props": {"type": "warning", "variant": "tonal", "class": "mt-3",
                              "title": "提示", "text": "；".join(alerts)},
                }
            )
        content.extend(
            [
                {
                    "component": "VRow",
                    "props": {"class": "mt-2"},
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 7},
                            "content": [
                                {"component": "VCard",
                                 "props": {"variant": "tonal"},
                                 "content": [
                                     {"component": "VCardTitle", "text": "做种数 Top 12"},
                                     {"component": "VCardText",
                                      "content": [{"component": "VApexChart",
                                                   "props": {"height": 380, "options": bar_options,
                                                             "series": bar_series}}]},
                                 ]},
                            ],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 5},
                            "content": [
                                {"component": "VCard",
                                 "props": {"variant": "tonal"},
                                 "content": [
                                     {"component": "VCardTitle", "text": "辅种占比"},
                                     {"component": "VCardText",
                                      "content": [{"component": "VApexChart",
                                                   "props": {"height": 380, "options": pie_options,
                                                             "series": [cross_seed, normal_seed]}}]},
                                 ]},
                            ],
                        },
                    ],
                }
            ]
        )
        trend = self.__trend_chart(cached.get("trend") or [])
        if trend:
            content.append(
                {
                    "component": "VCard",
                    "props": {"variant": "tonal", "class": "mt-3"},
                    "content": [
                        {"component": "VCardTitle", "text": "做种/辅种趋势（最近 7 天）"},
                        {"component": "VCardText",
                         "content": [{"component": "VApexChart", "props": trend}]},
                    ],
                }
            )
        content.append(
            {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mt-3"},
                "content": [
                    {"component": "VCardTitle",
                     "text": f"各站点明细（统计时间：{cached.get('timestamp', '未知')}）"},
                    {"component": "VCardText", "props": {"class": "text-caption text-medium-emphasis"},
                     "text": "辅种 = 带「辅种」标签且正在做种的任务；辅种暂停单列。"
                             "时魔* = 插件自建魔力快照增量 ÷ 时间（粗估标记为日级快照回退，非站点官方数值）；"
                             "效率* = 每小时魔力 / 做种体积(TB)。"},
                    {"component": "VTable",
                     "props": {"density": "compact", "hover": True},
                     "content": [
                         {"component": "thead",
                          "content": [{"component": "tr",
                                       "content": [{"component": "th", "text": text} for text in headers]}]},
                         {"component": "tbody",
                          "content": [self.__row(row) for row in rows]},
                     ]},
                ],
            }
        )
        return content

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """返回插件仪表板元信息。"""
        if not self._enabled or not self._dashboard:
            return []
        return [{"key": "seedstats", "name": "站点保种统计"}]

    def get_dashboard(
        self, key: str, **kwargs: Any
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], Optional[List[Dict[str, Any]]]]]:
        """返回首页仪表板配置与缓存数据。"""
        if not self._enabled or not self._dashboard:
            return None
        cached = self.__cached()
        rows = cached.get("rows") or []
        totals = cached.get("totals") or {}
        freshness = self.__cache_alert(cached)
        cols = {"cols": 12, "md": 6}
        attrs = {"refresh": 600, "title": "站点保种统计"}
        if not rows:
            return cols, attrs, [
                {"component": "VAlert",
                 "props": {"type": "warning" if freshness else "info", "variant": "tonal",
                           "text": freshness or "首次统计进行中，稍后自动刷新"}}
            ]
        top_rows = rows[:10]
        bar_options = {
            "chart": {"type": "bar", "toolbar": {"show": False}},
            "plotOptions": {"bar": {"horizontal": True, "borderRadius": 4}},
            "dataLabels": {"enabled": False},
            "xaxis": {"categories": [row.get("站点") for row in top_rows]},
            "legend": {"show": False},
            "noData": {"text": "暂无数据"},
        }
        content: List[dict] = [
            {
                "component": "VRow",
                "content": [
                    self.__card("做种中", str(totals.get("做种", 0)), "mdi-upload", 6, 3),
                    self.__card("辅种（做种中）", str(totals.get("辅种", 0)), "mdi-content-duplicate", 6, 3),
                    self.__card("做种体积", self.__format_size(totals.get("体积", 0)), "mdi-harddisk", 6, 3),
                    self.__card("总上传", self.__format_size(totals.get("上传", 0)), "mdi-cloud-upload", 6, 3),
                ],
            },
            {
                "component": "VApexChart",
                "props": {"height": 320, "options": bar_options,
                          "series": [{"name": "做种数", "data": [row.get("做种", 0) for row in top_rows]}]},
            },
            {
                "component": "div",
                "props": {"class": "text-caption text-medium-emphasis mt-2"},
                "text": f"共 {len(rows)} 个站点 ｜ 统计时间 {cached.get('timestamp', '未知')}",
            },
        ]
        if freshness:
            content.insert(0, {
                "component": "VAlert",
                "props": {"type": "warning", "variant": "tonal",
                          "title": "数据新鲜度", "text": freshness},
            })
        return cols, attrs, content

    def stop_service(self) -> None:
        """停止插件服务，取消待执行的首次统计任务。"""
        try:
            from app.sdk.scheduler import remove_plugin_once_job

            remove_plugin_once_job(self.__class__.__name__, f"{self.__class__.__name__}Once")
        except Exception:  # noqa: BLE001
            pass
        return None

    def __schedule_once(self) -> None:
        """安排一次立即统计，用于启用或保存配置后快速出数据。"""
        try:
            from app.sdk.scheduler import add_plugin_once_job

            add_plugin_once_job(
                plugin_id=self.__class__.__name__,
                job_id=f"{self.__class__.__name__}Once",
                func=self.__refresh_cache,
                name="站点保种统计首次刷新",
                delay_seconds=5,
            )
        except Exception as err:  # noqa: BLE001
            logger.error(f"站点保种统计：安排首次统计失败 {err}")

    def __refresh_cache(self) -> None:
        """重新计算统计结果并写入缓存。"""
        if self._refreshing:
            logger.info("站点保种统计：上一次统计尚未结束，本次跳过")
            return
        self._refreshing = True
        started = time.time()
        try:
            rows, totals, alerts = self.__collect_stats()
            trend = self.__append_trend(totals)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save_data(_CACHE_KEY, {
                "timestamp": stamp,
                "last_attempt": stamp,
                "last_error": "",
                "rows": rows,
                "totals": totals,
                "alerts": alerts,
                "trend": trend,
            })
            logger.info(
                f"站点保种统计：统计完成，站点 {len(rows)} 个，任务 {totals.get('任务数', 0)} 个，"
                f"做种体积 {self.__format_size(totals.get('体积', 0))}，用时 {time.time() - started:.1f}s"
            )
        except Exception as err:  # noqa: BLE001
            logger.error(f"站点保种统计：统计失败 {err}", exc_info=True)
            # 保留上一次明细，只标记失败原因与时间，避免页面继续静默展示旧数据
            cached = self.__cached()
            cached["last_attempt"] = time.strftime("%Y-%m-%d %H:%M:%S")
            cached["last_error"] = str(err)
            self.save_data(_CACHE_KEY, cached)
        finally:
            self._refreshing = False

    def __cached(self) -> Dict[str, Any]:
        """读取缓存的统计快照。"""
        data = self.get_data(_CACHE_KEY)
        return data if isinstance(data, dict) else {}

    def __cache_alert(self, cached: Dict[str, Any]) -> str:
        """返回缓存新鲜度/最近失败提示，空字符串表示正常。"""
        parts: List[str] = []
        error = str(cached.get("last_error") or "").strip()
        if error:
            parts.append(f"最近一次后台统计失败：{error}")
        stamp = str(cached.get("timestamp") or "").strip()
        if stamp:
            try:
                age_minutes = (
                    time.time() - time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
                ) / 60
            except (ValueError, OverflowError):
                age_minutes = 0.0
            if age_minutes > max(self._interval * 2, 60):
                parts.append(
                    f"统计数据已 {int(age_minutes)} 分钟未更新"
                    f"（刷新间隔 {self._interval} 分钟），后台任务可能未运行"
                )
        return "；".join(parts)

    def __summary_text(self) -> str:
        """构造远程命令返回的汇总文本。"""
        cached = self.__cached()
        totals = cached.get("totals") or {}
        rows = cached.get("rows") or []
        if not rows:
            return "暂无统计数据，请先启用插件并等待首次统计完成。"
        lines = [
            f"统计时间：{cached.get('timestamp', '未知')}",
            f"站点 {totals.get('站点数', 0)} 个 ｜ 任务 {totals.get('任务数', 0)} 个 ｜ 做种 {totals.get('做种', 0)} 个",
            f"辅种（做种中）{totals.get('辅种', 0)} 个 ｜ 辅种合计 {totals.get('辅种合计', 0)} 个",
            f"做种体积 {self.__format_size(totals.get('体积', 0))}",
            f"总上传 {self.__format_size(totals.get('上传', 0))} ｜ 总下载 {self.__format_size(totals.get('下载', 0))}",
        ]
        top = sorted(rows, key=lambda item: item.get("做种", 0), reverse=True)[:5]
        if top:
            lines.append("做种 Top5：" + "、".join(
                f"{item.get('站点')} {item.get('做种', 0)}" for item in top
            ))
        alerts = cached.get("alerts") or []
        if alerts:
            lines.append("提示：" + "；".join(alerts))
        return "\n".join(lines)

    def __card(self, title: str, value: str, icon: str, cols: int, md: int) -> Dict[str, Any]:
        """构造一个统计卡片元素。"""
        return {
            "component": "VCol",
            "props": {"cols": cols, "md": md},
            "content": [
                {"component": "VCard",
                 "props": {"variant": "tonal"},
                 "content": [
                     {"component": "VCardText",
                      "props": {"class": "d-flex align-center"},
                      "content": [
                          {"component": "VIcon", "props": {"icon": icon, "size": 32, "class": "me-3",
                                                            "color": "primary"}},
                          {"component": "div",
                           "content": [
                               {"component": "div", "props": {"class": "text-caption text-medium-emphasis"},
                                "text": title},
                               {"component": "div", "props": {"class": "text-h6 font-weight-bold"},
                                "text": value},
                           ]},
                      ]},
                 ]},
            ],
        }

    def __row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """构造站点明细表的一行。"""
        status = str(row.get("状态") or _STATUS_OK)
        status_class = "text-success" if status == _STATUS_OK else "text-warning"
        cells = [
            {"component": "td", "props": {"class": "font-weight-medium"}, "text": str(row.get("站点") or "-")},
            {"component": "td", "text": str(row.get("做种", 0))},
            {"component": "td", "props": {"class": "text-info"}, "text": str(row.get("辅种", 0))},
            {"component": "td", "props": {"class": "text-medium-emphasis"}, "text": str(row.get("辅种暂停", 0))},
            {"component": "td", "text": self.__format_size(row.get("体积"))},
            {"component": "td", "props": {"class": "text-success"},
             "text": self.__format_size(row.get("上传"))},
            {"component": "td", "props": {"class": "text-error"}, "text": self.__format_size(row.get("下载"))},
            {"component": "td", "text": self.__format_ratio(row.get("分享率"))},
            {"component": "td", "text": str(row.get("等级") or "-")},
            {"component": "td", "text": self.__format_bonus(row.get("魔力"))},
            {"component": "td", "props": {"class": "text-primary"},
             "text": self.__format_hourly(row.get("时魔"), row.get("时魔标记"))},
            {"component": "td", "props": {"class": "text-primary"},
             "text": self.__format_efficiency(row.get("时魔"), row.get("体积"))},
            {"component": "td", "props": {"class": status_class}, "text": status},
            {"component": "td", "props": {"class": "text-medium-emphasis"},
             "text": str(row.get("数据时间") or "-")},
        ]
        return {"component": "tr", "content": cells}

    @staticmethod
    def __format_size(value: Any) -> str:
        """把字节数格式化为可读容量。"""
        try:
            size = float(value or 0)
        except (TypeError, ValueError):
            return "-"
        if size <= 0:
            return "-"
        for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
            if size < 1024 or unit == "PB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return "-"

    @staticmethod
    def __format_bonus(value: Any) -> str:
        """格式化魔力值。"""
        try:
            bonus = float(value or 0)
        except (TypeError, ValueError):
            return "-"
        if bonus <= 0:
            return "-"
        if bonus >= 10000:
            return f"{bonus / 10000:.2f} 万"
        return f"{bonus:,.0f}"

    @staticmethod
    def __format_ratio(value: Any) -> str:
        """格式化分享率。"""
        try:
            ratio = float(value or 0)
        except (TypeError, ValueError):
            return "-"
        if ratio <= 0:
            return "-"
        if ratio >= 1000:
            return "∞"
        return f"{ratio:.2f}"

    @staticmethod
    def __format_hourly(value: Any, mark: Any = None) -> str:
        """格式化估算时魔，并附带粗估/异常标记。"""
        try:
            hourly = float(value)
        except (TypeError, ValueError):
            return str(mark) if mark else "-"
        text = f"{hourly:.1f}/时"
        if mark:
            text += f"（{mark}）"
        return text

    @staticmethod
    def __format_efficiency(hourly: Any, volume: Any) -> str:
        """按做种体积（TB）折算每小时魔力效率。"""
        try:
            hourly_value = float(hourly)
            volume_value = float(volume or 0)
        except (TypeError, ValueError):
            return "-"
        if hourly_value <= 0 or volume_value <= 0:
            return "-"
        per_tb = hourly_value / (volume_value / 1024 ** 4)
        return f"{per_tb:.0f}/TB·时"

    @staticmethod
    def __bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        """把配置值收敛到允许的整数区间。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def __parse_site_mapping(raw: Any) -> Dict[str, str]:
        """解析「域名=站点名」多行配置，返回小写域名到站点名的映射。"""
        mapping: Dict[str, str] = {}
        if isinstance(raw, dict):
            items = raw.items()
        else:
            text = str(raw or "")
            items = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                for sep in ("=", ":", " ", "\t"):
                    if sep in line:
                        domain, name = line.split(sep, 1)
                        items.append((domain.strip(), name.strip()))
                        break
        for domain, name in items:
            key = str(domain or "").strip().lower().rstrip("/")
            site_name = str(name or "").strip()
            if not key or not site_name:
                continue
            key = StringUtils.get_url_domain(key) if "://" in key else key
            mapping[key] = site_name
            if "." in key:
                mapping.setdefault(key.split(".")[0], site_name)
        return mapping

    def __collect_stats(self) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
        """读取下载器任务与站点账户数据，按站点汇总并生成告警。"""
        summary: Dict[str, Dict[str, Any]] = {}
        totals: Dict[str, Any] = {
            "下载器": 0, "任务数": 0, "做种": 0, "辅种": 0, "辅种合计": 0, "体积": 0, "上传": 0, "下载": 0,
        }
        configured = self.__configured_sites()
        accounts = self.__load_accounts()
        bonus_history = self.__update_bonus_history(accounts)
        self.__attach_hourly(accounts, bonus_history)
        self.__load_site_prefixes(configured)
        try:
            services = DownloaderHelper().get_services(name_filters=self._downloaders or None) or {}
        except Exception as err:  # noqa: BLE001
            logger.error(f"站点保种统计：获取下载器失败 {err}")
            return [], totals, ["读取下载器失败，请检查下载器配置"]
        sites_helper: Optional[SitesHelper] = None
        try:
            sites_helper = SitesHelper()
        except Exception as err:  # noqa: BLE001
            logger.error(f"站点保种统计：初始化站点助手失败 {err}")
        # tracker 域名到站点名的解析结果按域名记忆化，避免上万个任务重复查站点目录
        resolved: Dict[str, str] = {}
        for service in services.values():
            totals["下载器"] += 1
            torrents: Optional[List[Any]] = None
            # 优先使用下载器原生接口的轻量字段读取，显著降低耗时；失败时回退到公共接口
            native = getattr(service.instance, "trc", None)
            if native is not None:
                try:
                    torrents = native.get_torrents(arguments=["hashString", "status", "percentDone",
                                                              "labels", "downloadDir", "trackers",
                                                              "totalSize"])
                except Exception as err:  # noqa: BLE001
                    logger.error(f"站点保种统计：{service.name} 原生快速读取失败，回退公共接口 {err}")
                    torrents = None
            if torrents is None:
                try:
                    torrents, error = service.instance.get_torrents()
                except Exception as err:  # noqa: BLE001
                    logger.error(f"站点保种统计：读取下载器 {service.name} 任务失败 {err}")
                    continue
                if error:
                    torrents = None
            if not torrents:
                continue
            for torrent in torrents:
                site = self.__resolve_site(
                    torrent=torrent, sites_helper=sites_helper, cache=resolved
                )
                entry = summary.setdefault(
                    site,
                    {"任务数": 0, "做种": 0, "暂停": 0, "其他": 0, "辅种": 0, "辅种暂停": 0,
                     "体积": 0, "辅种体积": 0},
                )
                entry["任务数"] += 1
                state = self.__torrent_state(torrent)
                is_seeding = state in _SEEDING_STATES
                is_paused = state in _PAUSED_STATES
                if not is_seeding and not is_paused and self.__progress(torrent) >= 1:
                    # 状态文本不认识（新下载器/新版本）时按完成度兜底，避免整站被算成「其他」
                    is_seeding = True
                is_cross = _CROSS_SEED_TAG in self.__labels(torrent)
                size = self.__torrent_size(torrent)
                if is_seeding:
                    entry["做种"] += 1
                    entry["体积"] += size
                    if is_cross:
                        entry["辅种"] += 1
                        entry["辅种体积"] += size
                elif is_paused:
                    entry["暂停"] += 1
                    if is_cross:
                        entry["辅种暂停"] += 1
                else:
                    entry["其他"] += 1
        rows: List[Dict[str, Any]] = []
        removed_rows: List[Dict[str, Any]] = []
        candidates = set(summary) | set(configured) | set(accounts)
        for site in candidates:
            entry = summary.get(site) or {
                "任务数": 0, "做种": 0, "暂停": 0, "其他": 0, "辅种": 0, "辅种暂停": 0,
                "体积": 0, "辅种体积": 0,
            }
            account = accounts.get(site) or {}
            known = site in configured
            row: Dict[str, Any] = {"站点": site}
            row.update(entry)
            row["辅种合计"] = entry["辅种"] + entry["辅种暂停"]
            row.update({
                "上传": account.get("上传"),
                "下载": account.get("下载"),
                "分享率": account.get("分享率"),
                "等级": account.get("等级"),
                "魔力": account.get("魔力"),
                "时魔": account.get("时魔"),
                "时魔窗口": account.get("时魔窗口") or 0,
                "时魔标记": account.get("时魔标记") or "",
                "数据时间": account.get("数据时间"),
                "_updated_ts": account.get("_updated_ts") or 0.0,
                "_known": known,
            })
            row["状态"] = self.__row_status(row)
            if known or self._include_removed:
                rows.append(row)
            elif entry["任务数"] > 0 and not account:
                # tracker 未归属到任何已配置站点，仍然展示，便于配置手动映射
                row["_unknown_tracker"] = True
                row["状态"] = "未映射"
                rows.append(row)
            elif entry["任务数"] > 0 or account:
                # 已从站点列表删除但仍有账户/任务残留，只作提示，不计入合计
                removed_rows.append(row)
        rows.sort(key=lambda item: (item["任务数"], item.get("上传") or 0), reverse=True)
        for row in rows:
            totals["任务数"] += row["任务数"]
            totals["做种"] += row["做种"]
            totals["辅种"] += row["辅种"]
            totals["辅种合计"] += row["辅种合计"]
            totals["体积"] += row["体积"]
            totals["上传"] += float(row.get("上传") or 0)
            totals["下载"] += float(row.get("下载") or 0)
        # 「站点数」只统计 MoviePilot 里仍然存在的站点，未映射 tracker 单独计数
        totals["站点数"] = sum(1 for row in rows if row.get("_known"))
        totals["未映射"] = sum(1 for row in rows if row.get("_unknown_tracker"))
        return rows, totals, self.__build_alerts(rows, removed_rows)

    def __row_status(self, row: Dict[str, Any]) -> str:
        """判定站点行的健康状态文本。"""
        if row.get("_unknown_tracker"):
            return "未映射"
        # 过期优先：账户数据长时间未更新时先提示过期，避免把「数据旧」误判成「没做种」
        updated_ts = float(row.get("_updated_ts") or 0)
        if updated_ts > 0:
            age_hours = (time.time() - updated_ts) / 3600
            if age_hours > self._stale_hours:
                return _STATUS_STALE
        # 用「做种数」判定零做种：任务全暂停/全在下载的站点同样是零做种；
        # 行里没有做种字段时退回按任务数判定，保持旧口径兼容
        if row.get("做种") == 0 or not row.get("任务数"):
            return _STATUS_IDLE
        return _STATUS_OK

    def __build_alerts(self, rows: List[Dict[str, Any]],
                       removed_rows: List[Dict[str, Any]]) -> List[str]:
        """根据统计结果生成页面告警文案。"""
        alerts: List[str] = []
        stale = [row for row in rows if row.get("状态") == _STATUS_STALE]
        if stale:
            names = "、".join(f"{row['站点']}({str(row.get('数据时间') or '未知')[:10]})" for row in stale[:5])
            alerts.append(f"{len(stale)} 个站点数据超过 {self._stale_hours} 小时未更新：{names}")
        idle = [row for row in rows if row.get("状态") == _STATUS_IDLE]
        if idle:
            alerts.append(f"{len(idle)} 个站点本地零做种：{'、'.join(row['站点'] for row in idle[:6])}")
        unknown = [row for row in rows if row.get("_unknown_tracker")]
        if unknown:
            detail = "、".join(f"{row['站点']} {row.get('任务数', 0)}" for row in unknown[:5])
            alerts.append(f"未归属到已配置站点的 tracker：{detail}（可在配置「tracker 站点映射」中绑定）")
        if removed_rows:
            alerts.append(
                "已删除站点的残留数据未计入合计："
                + "、".join(
                    f"{row['站点']}("
                    + (f"任务 {row.get('任务数', 0)}" if row.get("任务数") else "仅账户数据")
                    + ")"
                    for row in removed_rows[:5]
                )
            )
        return alerts

    def __configured_sites(self) -> Dict[str, str]:
        """返回当前配置的站点名到域名映射。"""
        result: Dict[str, str] = {}
        try:
            sites = SiteOper().list_order_by_pri() or []
        except Exception as err:  # noqa: BLE001
            logger.error(f"站点保种统计：读取站点列表失败 {err}")
            return result
        for site in sites:
            name = str(getattr(site, "name", "") or "")
            if not name:
                continue
            result[name] = str(getattr(site, "domain", "") or "").lower()
        return result

    def __load_accounts(self) -> Dict[str, Dict[str, Any]]:
        """读取各站点最新账户数据（原始值，时魔另行估算）。"""
        accounts: Dict[str, Dict[str, Any]] = {}
        try:
            latest: List[Any] = SiteOper().get_userdata_latest() or []
        except Exception as err:  # noqa: BLE001
            logger.error(f"站点保种统计：读取站点数据失败 {err}")
            return accounts
        for data in latest:
            if not data or not data.name:
                continue
            updated: Optional[datetime] = None
            if data.updated_day:
                try:
                    updated = datetime.strptime(
                        f"{data.updated_day} {data.updated_time or '00:00:00'}", "%Y-%m-%d %H:%M:%S"
                    )
                except ValueError:
                    updated = None
            accounts[str(data.name)] = {
                "上传": data.upload,
                "下载": data.download,
                "分享率": data.ratio,
                "等级": data.user_level,
                "魔力": data.bonus,
                "时魔": None,
                "时魔窗口": 0.0,
                "时魔标记": "",
                "数据时间": f"{data.updated_day or ''} {data.updated_time or ''}".strip(),
                "_updated": updated,
                "_updated_ts": updated.timestamp() if updated else 0.0,
                "_data": data,
            }
        return accounts

    def __update_bonus_history(
        self, accounts: Dict[str, Dict[str, Any]]
    ) -> Dict[str, List[List[float]]]:
        """把本次魔力值写入自建快照序列，返回站点到快照点的映射。"""
        now = time.time()
        raw = self.get_data(_BONUS_KEY)
        history: Dict[str, List[List[float]]] = dict(raw) if isinstance(raw, dict) else {}
        if accounts:
            # 已删除站点的历史不再保留，避免 JSON 只增不减
            history = {site: points for site, points in history.items() if site in accounts}
        cutoff = now - _BONUS_KEEP_HOURS * 3600
        for site, account in accounts.items():
            bonus = account.get("魔力")
            if bonus is None:
                continue
            points = history.get(site)
            if not isinstance(points, list):
                points = []
            cleaned: List[List[float]] = []
            for point in points:
                try:
                    ts, value = float(point[0]), float(point[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if ts >= cutoff:
                    cleaned.append([ts, value])
            if cleaned and now - cleaned[-1][0] < 600:
                cleaned[-1][1] = float(bonus)
            else:
                cleaned.append([now, float(bonus)])
            history[site] = cleaned[-_BONUS_MAX_POINTS:]
        self.save_data(_BONUS_KEY, history)
        return history

    def __attach_hourly(
        self,
        accounts: Dict[str, Dict[str, Any]],
        bonus_history: Dict[str, List[List[float]]],
    ) -> None:
        """为每个站点计算时魔估算值、估算窗口与标记。"""
        previous_cache: Dict[str, Dict[str, Any]] = {}
        try:
            site_oper = SiteOper()
        except Exception:  # noqa: BLE001
            site_oper = None
        for site, account in accounts.items():
            hourly, window, note = self.__estimate_hourly(
                account.get("魔力"), bonus_history.get(site) or []
            )
            if hourly is None and not note and site_oper is not None:
                hourly, window = self.__fallback_hourly(site_oper, account, previous_cache)
                if hourly is not None:
                    note = "粗估"
            if hourly is not None and window > 6 and not note:
                note = "粗估"
            account["时魔"] = hourly
            account["时魔窗口"] = round(window, 1)
            account["时魔标记"] = note

    @staticmethod
    def __estimate_hourly(
        current: Any, points: List[List[float]]
    ) -> Tuple[Optional[float], float, str]:
        """用自建魔力快照估算时魔，返回 (时魔, 窗口小时, 标记)。"""
        if current is None:
            return None, 0.0, "无魔力"
        try:
            bonus_now = float(current)
        except (TypeError, ValueError):
            return None, 0.0, "无魔力"
        # 部分站点不对外提供魔力（恒为 0），不做估算，避免显示成 0/时
        if bonus_now <= 0:
            return None, 0.0, "无魔力"
        now = time.time()
        for point in points:
            try:
                ts, bonus_then = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError):
                continue
            hours = (now - ts) / 3600
            if hours < _MIN_HOURLY_WINDOW:
                continue
            if hours > _MAX_HOURLY_WINDOW:
                continue
            delta = bonus_now - bonus_then
            if delta < 0:
                return None, hours, "异常"
            return delta / hours, hours, ""
        return None, 0.0, ""

    @staticmethod
    def __fallback_hourly(
        site_oper: SiteOper,
        account: Dict[str, Any],
        previous_cache: Dict[str, Dict[str, Any]],
    ) -> Tuple[Optional[float], float]:
        """站点数据日级快照回退估算（首次运行无自建快照时使用）。"""
        data = account.get("_data")
        # 宿主站点数据以属性形式提供，这里按鸭子类型判断，避免依赖宿主 ORM 模型
        if not data or not getattr(data, "updated_day", None) or getattr(data, "bonus", None) is None:
            return None, 0.0
        if float(data.bonus) <= 0:
            return None, 0.0
        try:
            today = datetime.strptime(
                f"{data.updated_day} {data.updated_time or '00:00:00'}", "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            return None, 0.0
        for back in range(1, 4):
            prev_day = (today - timedelta(days=back)).strftime("%Y-%m-%d")
            if prev_day not in previous_cache:
                try:
                    previous_cache[prev_day] = {
                        str(row.name): row
                        for row in (site_oper.get_userdata_by_date(prev_day) or [])
                        if row
                    }
                except Exception:  # noqa: BLE001
                    previous_cache[prev_day] = {}
            previous = previous_cache[prev_day].get(str(data.name))
            if not previous or previous.bonus is None:
                continue
            try:
                prev_time = datetime.strptime(
                    f"{previous.updated_day} {previous.updated_time or '00:00:00'}",
                    "%Y-%m-%d %H:%M:%S",
                )
            except ValueError:
                continue
            hours = (today - prev_time).total_seconds() / 3600
            if hours <= 0 or hours > 72:
                continue
            delta = float(data.bonus or 0) - float(previous.bonus or 0)
            if delta <= 0:
                continue
            return delta / hours, hours
        return None, 0.0

    def __append_trend(self, totals: Dict[str, Any]) -> List[Dict[str, Any]]:
        """按小时聚合写入趋势快照，保留最近 14 天。"""
        now = time.time()
        current = (self.__cached().get("trend") or [])
        # 旧版本 history 快照只用于补齐升级前的历史点；同小时以新数据为准
        merged: Dict[str, Dict[str, Any]] = {}
        for item in self.__migrate_history():
            merged[str(item.get("hour"))] = item
        for item in current:
            if isinstance(item, dict):
                merged[str(item.get("hour"))] = dict(item)
        entries: List[Dict[str, Any]] = sorted(
            merged.values(), key=lambda item: float(item.get("ts") or 0)
        )
        hour_key = time.strftime("%Y-%m-%d %H", time.localtime(now))
        snapshot = {
            "hour": hour_key,
            "ts": now,
            "做种": int(totals.get("做种", 0)),
            "辅种": int(totals.get("辅种", 0)),
            "体积": float(totals.get("体积", 0) or 0),
            "站点数": int(totals.get("站点数", 0)),
        }
        if entries and entries[-1].get("hour") == hour_key:
            entries[-1] = snapshot
        else:
            entries.append(snapshot)
        cutoff = now - _HISTORY_KEEP_HOURS * 3600
        entries = [item for item in entries if float(item.get("ts") or 0) >= cutoff]
        return entries[-_HISTORY_MAX_POINTS:]

    def __migrate_history(self) -> List[Dict[str, Any]]:
        """把旧版本按条保存的 history 快照转换为趋势点。"""
        legacy = self.get_data(_HISTORY_KEY)
        if not isinstance(legacy, list):
            return []
        entries: List[Dict[str, Any]] = []
        for item in legacy:
            if not isinstance(item, dict) or not item.get("timestamp"):
                continue
            try:
                stamp = time.mktime(time.strptime(str(item["timestamp"]), "%Y-%m-%d %H:%M:%S"))
            except (TypeError, ValueError):
                continue
            entries.append({
                "hour": str(item["timestamp"])[:13],
                "ts": stamp,
                "做种": int(item.get("做种") or 0),
                # 旧版本的「辅种」包含暂停任务，与当前口径不同，不迁移以免曲线跳变
                "辅种": None,
                "体积": float(item.get("体积") or 0),
                "站点数": int(item.get("站点数") or 0),
            })
        return entries

    def __trend_chart(self, trend: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """构造最近 7 天的做种/辅种折线图配置。"""
        cutoff = time.time() - 7 * 24 * 3600
        points = [item for item in trend if float(item.get("ts") or 0) >= cutoff]
        if len(points) < 2:
            return None
        categories = [time.strftime("%m-%d %H:%M", time.localtime(float(item.get("ts") or 0)))
                      for item in points]
        options = {
            "chart": {"type": "line", "toolbar": {"show": False}, "zoom": {"enabled": False}},
            "dataLabels": {"enabled": False},
            "stroke": {"curve": "smooth", "width": 2},
            "xaxis": {"categories": categories, "labels": {"show": False}},
            "legend": {"show": True},
            "noData": {"text": "暂无数据"},
        }
        series = [
            {"name": "做种", "data": [item.get("做种", 0) for item in points]},
            {"name": "辅种（做种中）", "data": [item.get("辅种", 0) for item in points]},
        ]
        return {"height": 280, "options": options, "series": series}

    def __load_site_prefixes(self, configured: Optional[Dict[str, str]] = None) -> None:
        """加载已配置站点的域名前缀映射，用于 tracker 归属兜底匹配。"""
        self._site_prefixes = {}
        sites = configured if configured is not None else self.__configured_sites()
        for name, domain in sites.items():
            if not domain:
                continue
            try:
                registered = StringUtils.get_url_domain(f"https://{domain}")
            except Exception:  # noqa: BLE001
                registered = ""
            # tracker 域名常为子域（kp.m-team.cc），announce 解析出的是注册域名，
            # 因此两种形态都登记，避免子域站点匹配不到。
            # 首段过短（pt / hd 之类）容易把别的站点误并进来，只登记长度 >= 4 的首段
            for key in (
                domain,
                domain.split(".")[0],
                registered,
                registered.split(".")[0],
            ):
                if not key:
                    continue
                if "." not in key and len(key) < 4:
                    continue
                if key:
                    self._site_prefixes.setdefault(key.lower(), name)

    def __mapped_site(self, domain: str) -> str:
        """按用户配置的 tracker 映射解析站点名。"""
        if not domain or not self._site_mapping:
            return ""
        key = str(domain).split(":")[0].lower()
        for candidate in (key, key.split(".")[0], key.replace("tracker.", "")):
            if candidate and candidate in self._site_mapping:
                return self._site_mapping[candidate]
        return ""

    @classmethod
    def __tracker_urls(cls, torrent: Any) -> List[str]:
        """按层级顺序返回任务的 tracker 地址列表（兼容 TR 与 qB）。"""
        entries: List[Tuple[int, str]] = []
        trackers = cls.__field(torrent, "trackers")
        if isinstance(trackers, list):
            for tracker in trackers:
                if isinstance(tracker, str):
                    entries.append((9, tracker))
                    continue
                announce = cls.__field(tracker, "announce") or ""
                tier = cls.__field(tracker, "tier")
                if announce:
                    entries.append((tier if isinstance(tier, int) else 9, str(announce)))
        single = cls.__field(torrent, "tracker")
        if single:
            entries.append((0, str(single)))
        entries.sort(key=lambda item: item[0])
        return [url for _, url in entries if url]

    def __resolve_site(
        self,
        torrent: Any,
        sites_helper: Optional[SitesHelper],
        cache: Optional[Dict[str, str]] = None,
    ) -> str:
        """根据任务的 tracker 解析所属站点名称。"""
        urls = self.__tracker_urls(torrent)
        if not urls:
            return "未识别"
        domains: List[str] = []
        for url in urls:
            try:
                domain = StringUtils.get_url_domain(str(url)).split(":")[0]
            except Exception:  # noqa: BLE001
                domain = ""
            if domain:
                domains.append(domain)
        # 按 tracker 层级顺序逐个解析：同一域名内再依次走手动映射、索引器、前缀兜底，
        # 避免次级 tracker 的映射覆盖主 tracker 的归属。
        for domain in domains:
            if cache is not None and domain in cache:
                site = cache[domain]
                if site:
                    return site
                continue
            site = ""
            mapped = self.__mapped_site(domain)
            if mapped:
                site = mapped
            elif sites_helper is not None:
                try:
                    indexer = sites_helper.get_indexer(domain) or {}
                except Exception:  # noqa: BLE001
                    indexer = {}
                if indexer.get("name"):
                    site = str(indexer["name"])
            if not site:
                key = domain.lower()
                for prefix in (key, key.split(".")[0], key.replace("tracker.", "")):
                    if prefix in self._site_prefixes:
                        site = self._site_prefixes[prefix]
                        break
            if cache is not None:
                cache[domain] = site
            if site:
                return site
        # 全部未命中时按 tracker 域名单独成行，便于在配置里手动映射
        return domains[0] if domains else "未识别"

    @classmethod
    def __torrent_state(cls, torrent: Any) -> str:
        """读取任务状态文本：Transmission 用 status，qBittorrent/rTorrent 用 state。"""
        for name in ("status", "state"):
            value = cls.__field(torrent, name)
            if value is None:
                continue
            text = str(getattr(value, "value", value) or "").strip().lower()
            text = text.replace("_", " ")
            if text and text not in {"none", "unknown", "null"}:
                return text
        return ""

    @classmethod
    def __progress(cls, torrent: Any) -> float:
        """读取任务完成度并归一为 0~1，兼容 progress / percentDone。"""
        for name in ("progress", "percentDone", "percent_done"):
            value = cls.__field(torrent, name)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            return number / 100 if number > 1.5 else number
        return 0.0

    @classmethod
    def __torrent_size(cls, torrent: Any) -> int:
        """读取任务总大小（兼容 TR 与 qB 字段）。"""
        for name in ("totalSize", "total_size", "size"):
            value = cls.__field(torrent, name)
            if value:
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    continue
        return 0

    @staticmethod
    def __field(obj: Any, name: str) -> Any:
        """兼容字典与对象两种形式的字段读取。"""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    @classmethod
    def __labels(cls, torrent: Any) -> List[str]:
        """读取任务的标签列表。"""
        labels = cls.__field(torrent, "labels")
        if labels is None:
            labels = cls.__field(torrent, "tags")
        if not labels:
            return []
        if isinstance(labels, str):
            return [item.strip() for item in labels.split(",") if item.strip()]
        return [str(item).strip() for item in labels]
