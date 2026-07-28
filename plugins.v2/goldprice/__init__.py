import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests
from apscheduler.triggers.cron import CronTrigger

from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType


class GoldPrice(_PluginBase):
    """
    金价日报插件
    每日定时抓取金店零售价(周大福/老凤祥等)、银行纸黄金(工行/建行等)、大盘金价，
    排版后通过 MoviePilot 通知渠道(微信/企业微信/WxPusher/Telegram...)推送。
    数据源: ip138(金店+大盘) + 金价表 jinjiabiao.com(银行纸黄金)。
    均为服务端渲染 HTML 表格，免费、无需密钥。
    """

    # ===== 插件元信息 =====
    plugin_name = "金价日报"
    plugin_desc = "每日定时推送金店零售价、银行纸黄金、大盘金价到通知渠道(微信)。"
    plugin_icon = "gold.png"
    plugin_color = "#D4AF37"
    plugin_version = "1.2.1"
    plugin_author = "nshzswz"
    author_url = "https://github.com/nshzswz-c"
    plugin_config_prefix = "goldprice_"
    plugin_order = 50
    auth_level = 2

    # ===== 默认配置(类属性兜底, 保证 get_service 在 init_plugin 之前也有值) =====
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = "30 9 * * *"
    _show_market: bool = True
    _show_shop: bool = True
    _show_bank: bool = True
    _shops: str = ""
    _msgtype: str = ""
    _history_days: int = 90
    _summary_period: str = ""  # ""=关闭 / week / month / year

    # 历史数据存储 key
    _DATA_KEY = "history"

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    _IP138_URL = "https://www.ip138.com/gold/"
    _BANK_URL = "https://www.jinjiabiao.com/papergold"
    _TZ = pytz.timezone("Asia/Shanghai")

    def init_plugin(self, config: dict = None):
        """插件启用 / 配置保存时调用"""
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._cron = (config.get("cron") or "30 9 * * *").strip()
        self._show_market = bool(config.get("show_market", True))
        self._show_shop = bool(config.get("show_shop", True))
        self._show_bank = bool(config.get("show_bank", True))
        self._shops = (config.get("shops") or "").strip()
        self._msgtype = config.get("msgtype") or ""
        try:
            self._history_days = int(config.get("history_days") or 90)
        except (TypeError, ValueError):
            self._history_days = 90
        self._summary_period = (config.get("summary_period") or "").strip()

        # 立即运行一次
        if self._onlyonce:
            logger.info("金价日报: 立即运行一次")
            self._onlyonce = False
            self._save_config()
            self.push()

    def _save_config(self):
        """保存当前配置快照"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "show_market": self._show_market,
            "show_shop": self._show_shop,
            "show_bank": self._show_bank,
            "shops": self._shops,
            "msgtype": self._msgtype,
            "history_days": self._history_days,
            "summary_period": self._summary_period,
        })

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """插件配置表单 (Vuetify JSON, VForm > VRow > VCol 嵌套)"""
        # 消息类型下拉选项
        msg_options = [{"title": item.value, "value": item.name} for item in NotificationType]
        return [
            {
                "component": "VForm",
                "content": [
                    # 第一行: 启用 / 立即运行
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "onlyonce", "label": "立即运行一次"},
                                    }
                                ],
                            },
                        ],
                    },
                    # 第二行: cron / 消息类型 / 历史保留天数 / 周期汇报
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "推送时间 (5段 cron)",
                                            "placeholder": "30 9 * * *",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "msgtype",
                                            "label": "消息类型",
                                            "items": msg_options,
                                            "clearable": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "history_days",
                                            "label": "历史保留天数",
                                            "type": "number",
                                            "placeholder": "90",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "summary_period",
                                            "label": "周期汇报",
                                            "items": [
                                                {"title": "关闭", "value": ""},
                                                {"title": "每周 (周一9点)", "value": "week"},
                                                {"title": "每月 (1号9点)", "value": "month"},
                                                {"title": "每年 (1月1号9点)", "value": "year"},
                                            ],
                                            "clearable": False,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # 第三行: 三个内容开关
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "show_market", "label": "推送大盘金价"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "show_shop", "label": "推送金店零售价"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "show_bank", "label": "推送银行纸黄金"},
                                    }
                                ],
                            },
                        ],
                    },
                    # 第四行: 关注金店
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "shops",
                                            "label": "关注金店 (逗号分隔, 留空=全部)",
                                            "placeholder": "周大福,老凤祥,周生生",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    # 说明
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "数据来自 ip138 与金价表公开页面，免费无需密钥。"
                                                    "推送走系统通知渠道，请先在「设置 → 通知」启用微信等渠道。"
                                                    "每日推送含较昨日涨跌; 周期汇报按所选周/月/年在周期节点(周一/月初/年初)对比这段时间变化, 需先积累历史数据。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cron": "30 9 * * *",
            "msgtype": "",
            "history_days": 90,
            "summary_period": "",
            "show_market": True,
            "show_shop": True,
            "show_bank": True,
            "shops": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        """详情页: 历史金价折线图 (大盘/金店/银行 各一张)"""
        history: Dict[str, Any] = self.get_data(self._DATA_KEY) or {}
        if not history:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "暂无历史数据。插件每次推送后会记录当天金价，积累几天后这里会显示历史折线图。"
                                "可在配置页勾选「立即运行一次」先抓一次。",
                    },
                }
            ]

        dates = sorted(history.keys())

        def build_series(kind: str) -> List[dict]:
            """把某一类(market/shop/bank)整理成 ApexCharts series: [{name, data}]"""
            # 收集该类下出现过的所有条目名
            names: List[str] = []
            for d in dates:
                for n in history[d].get(kind, {}).keys():
                    if n not in names:
                        names.append(n)
            series = []
            for n in names:
                # 每个日期取值, 缺失填 None(折线断开)
                data = [history[d].get(kind, {}).get(n) for d in dates]
                # 全空的系列不画
                if any(v is not None for v in data):
                    series.append({"name": n, "data": data})
            return series

        def chart_card(title: str, series: List[dict]) -> Optional[dict]:
            if not series:
                return None
            return {
                "component": "VCol",
                "props": {"cols": 12},
                "content": [
                    {
                        "component": "VApexChart",
                        "props": {
                            "height": 300,
                            "options": {
                                "chart": {"type": "line", "zoom": {"enabled": True}},
                                "title": {"text": title},
                                "xaxis": {"categories": dates},
                                "stroke": {"curve": "smooth", "width": 2},
                                "markers": {"size": 3},
                                "legend": {"show": True},
                                "tooltip": {"shared": True},
                                "dataLabels": {"enabled": False},
                                "noData": {"text": "暂无数据"},
                                "yaxis": {"title": {"text": "元/克"}},
                            },
                            "series": series,
                        },
                    }
                ],
            }

        cards = []
        if self._show_market:
            c = chart_card("大盘金价走势 (元/克)", build_series("market"))
            if c:
                cards.append(c)
        if self._show_shop:
            c = chart_card("金店零售价走势 (元/克)", build_series("shop"))
            if c:
                cards.append(c)
        if self._show_bank:
            c = chart_card("银行纸黄金走势 (元/克)", build_series("bank"))
            if c:
                cards.append(c)

        if not cards:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": f"已记录 {len(dates)} 天数据，但当前开关下无可展示的图表。",
                    },
                }
            ]

        return [
            {
                "component": "VRow",
                "content": cards,
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时服务: 每日推送 + 可选的周期汇报"""
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except Exception as e:
            logger.error(f"金价日报: cron 表达式非法 [{self._cron}]: {e}, 回退默认 30 9 * * *")
            trigger = CronTrigger.from_crontab("30 9 * * *")
        services = [
            {
                "id": "GoldPricePush",
                "name": "金价日报推送",
                "trigger": trigger,
                "func": self.push,
                "kwargs": {},
            }
        ]
        # 周期汇报: 周=周一9点 / 月=每月1号9点 / 年=每年1月1号9点
        # 注意: APScheduler day_of_week 用名称避免数字歧义(数字周一=0, 与标准 crontab 周一=1 不同)
        summary_cron = {
            "week": "0 9 * * mon",
            "month": "0 9 1 * *",
            "year": "0 9 1 1 *",
        }.get(self._summary_period)
        if summary_cron:
            services.append({
                "id": "GoldPriceSummary",
                "name": "金价周期汇报",
                "trigger": CronTrigger.from_crontab(summary_cron),
                "func": self.summary,
                "kwargs": {},
            })
        return services

    # =====================================================================
    #  主流程
    # =====================================================================
    def push(self):
        """定时触发: 抓取金价并推送"""
        # 未启用任何内容: 直接跳过, 不发失败告警
        if not (self._show_market or self._show_shop or self._show_bank):
            logger.info("金价日报: 未启用任何推送内容, 跳过")
            return

        logger.info("金价日报: 开始抓取金价数据")
        blocks: List[str] = []
        errors: List[str] = []

        # 大盘 + 金店 (同一个 ip138 页面, 一次请求)
        shops, market = [], []
        if self._show_market or self._show_shop:
            try:
                shops, market = self._fetch_ip138()
            except Exception as e:
                logger.error(f"金价日报: 抓取 ip138 失败: {e}")
                errors.append("金店/大盘数据获取失败")

        # 银行纸黄金
        banks = []
        if self._show_bank:
            try:
                banks = self._fetch_bank()
            except Exception as e:
                logger.error(f"金价日报: 抓取银行金价失败: {e}")
                errors.append("银行金价数据获取失败")

        # 逐个启用项校验: 页面返回 200 但结构变了会得到空列表, 视为该项失败, 不静默
        if self._show_market and not market and "金店/大盘数据获取失败" not in errors:
            errors.append("大盘数据解析为空")
        if self._show_shop and not shops and "金店/大盘数据获取失败" not in errors:
            errors.append("金店数据解析为空")
        if self._show_bank and not banks and "银行金价数据获取失败" not in errors:
            errors.append("银行金价数据解析为空")

        # 取昨日记录做日环比(必须在写入今天之前取)
        today = datetime.now(self._TZ).strftime("%Y-%m-%d")
        prev = self._prev_record(before=today)
        pm = prev.get("market", {}) if prev else {}
        ps = prev.get("shop", {}) if prev else {}
        pb = prev.get("bank", {}) if prev else {}

        # 排版
        if self._show_market and market:
            blocks.append(self._fmt_market(market, pm))
        if self._show_shop and shops:
            blocks.append(self._fmt_shops(shops, ps))
        if self._show_bank and banks:
            blocks.append(self._fmt_banks(banks, pb))

        if not blocks:
            # 全部失败也要告知, 不静默
            msg = "金价日报抓取失败:\n" + "\n".join(f"· {e}" for e in (errors or ["无数据"]))
            logger.warning(msg)
            self._post(msg)
            return

        # 记录历史数据(用于详情页折线图 + 日环比 + 周期汇报)
        try:
            self._save_history(market, shops, banks)
        except Exception as e:
            logger.error(f"金价日报: 保存历史数据失败: {e}")

        now = datetime.now(self._TZ).strftime("%Y-%m-%d %H:%M")
        text = f"⏰ {now}\n\n" + "\n\n".join(blocks)
        if errors:
            text += "\n\n⚠️ 部分数据获取失败: " + "、".join(errors)

        self._post(text)
        logger.info("金价日报: 推送完成")

    def _save_history(self, market: List[dict], shops: List[dict], banks: List[dict]):
        """把当天抓到的金价按日期存入插件数据, 供详情页画折线图。

        存储结构: { "2026-07-27": {"market": {品种: 价}, "shop": {金店: 价}, "bank": {银行: 价}}, ... }
        同一天多次推送(如 9/12/14/18 点)以最后一次为准。
        """
        today = datetime.now(self._TZ).strftime("%Y-%m-%d")

        def to_float(v: str) -> Optional[float]:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        day_rec: Dict[str, Dict[str, float]] = {"market": {}, "shop": {}, "bank": {}}
        for m in market:
            val = to_float(m.get("cny"))
            if "黄金" in m.get("name", "") and val is not None:
                day_rec["market"][m["name"]] = val
        for s in shops:
            val = to_float(s.get("price"))
            if val is not None:
                day_rec["shop"][s["name"]] = val
        for b in banks:
            val = to_float(b.get("price"))
            if val is not None:
                day_rec["bank"][b["name"]] = val

        # 全空不记录, 避免抓取失败污染历史
        if not (day_rec["market"] or day_rec["shop"] or day_rec["bank"]):
            return

        history: Dict[str, Any] = self.get_data(self._DATA_KEY) or {}
        # 合并而非整体覆盖: 只更新本次实际抓到数据的类别,
        # 避免同一天某源失败/返回空时抹掉其它源已成功记录的价格 (PR-Agent: 历史丢失)
        existing = history.get(today) or {"market": {}, "shop": {}, "bank": {}}
        for kind in ("market", "shop", "bank"):
            if day_rec[kind]:  # 本次这类有数据才覆盖, 空则保留原值
                existing[kind] = day_rec[kind]
            else:
                existing.setdefault(kind, {})
        history[today] = existing

        # 按日期裁剪到保留天数
        days = sorted(history.keys())
        keep = max(1, self._history_days)
        if len(days) > keep:
            for d in days[:-keep]:
                history.pop(d, None)

        self.save_data(self._DATA_KEY, history)

    def _prev_record(self, before: str) -> Optional[Dict[str, Any]]:
        """取严格早于 before(YYYY-MM-DD)的最近一天记录, 用于日环比"""
        history: Dict[str, Any] = self.get_data(self._DATA_KEY) or {}
        earlier = sorted(d for d in history.keys() if d < before)
        return history[earlier[-1]] if earlier else None

    def _baseline_record(self, since: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """取周期起点: >=since(YYYY-MM-DD)的最早一天记录, 用于周/月/年对比。
        返回 (日期, 记录); 无则 (None, None)。"""
        history: Dict[str, Any] = self.get_data(self._DATA_KEY) or {}
        within = sorted(d for d in history.keys() if d >= since)
        return (within[0], history[within[0]]) if within else (None, None)

    def _latest_record(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """取最新一天记录"""
        history: Dict[str, Any] = self.get_data(self._DATA_KEY) or {}
        days = sorted(history.keys())
        return (days[-1], history[days[-1]]) if days else (None, None)

    @staticmethod
    def _delta(cur: Optional[float], base: Optional[float]) -> str:
        """格式化涨跌: '↑12.30 (+1.35%)' / '↓5.00 (-0.56%)' / '持平'; 缺基准返回空串"""
        if cur is None or base is None:
            return ""
        diff = cur - base
        if abs(diff) < 1e-9:
            return "持平"
        pct = (diff / base * 100) if base else 0
        arrow = "↑" if diff > 0 else "↓"
        sign = "+" if diff > 0 else "-"
        return f"{arrow}{abs(diff):.2f} ({sign}{abs(pct):.2f}%)"

    def _post(self, text: str):
        """通过 MoviePilot 通知渠道推送; 指定了消息类型则带上, 否则归入插件通知"""
        mtype = NotificationType.Plugin
        if self._msgtype:
            try:
                mtype = NotificationType[self._msgtype]
            except KeyError:
                mtype = NotificationType.Plugin
        self.post_message(mtype=mtype, title="📊 金价日报", text=text)

    # =====================================================================
    #  数据抓取
    # =====================================================================
    def _get(self, url: str) -> str:
        resp = requests.get(url, headers=self._HEADERS, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    @staticmethod
    def _rows(html: str, table_idx: int = 0) -> List[List[str]]:
        """取第 table_idx 个 table 的所有行, 每行返回纯文本单元格列表"""
        tables = re.findall(r"<table.*?</table>", html, re.S)
        if table_idx >= len(tables):
            return []
        out = []
        for tr in re.findall(r"<tr.*?>(.*?)</tr>", tables[table_idx], re.S):
            cells = [re.sub(r"<.*?>", "", c).strip()
                     for c in re.findall(r"<t[dh].*?>(.*?)</t[dh]>", tr, re.S)]
            if any(cells):
                out.append(cells)
        return out

    @staticmethod
    def _num(s: str) -> str:
        """从 '1248' / '889.99 元/克' 中提取数字部分"""
        m = re.search(r"\d+(?:\.\d+)?", s or "")
        return m.group(0) if m else (s or "").strip()

    def _fetch_ip138(self) -> Tuple[List[dict], List[dict]]:
        """ip138: table[0]=金店零售价, table[1]=大盘价"""
        html = self._get(self._IP138_URL)
        shops, market = [], []
        # 金店: 金店名称 | 零售价 | 换购价 | 更新时间
        for c in self._rows(html, 0):
            if len(c) >= 2 and c[0] != "金店名称" and re.search(r"\d", c[1]):
                shops.append({
                    "name": c[0],
                    "price": self._num(c[1]),
                    "buy": self._num(c[2]) if len(c) > 2 and re.search(r"\d", c[2]) else "",
                })
        # 大盘: 交易品种 | 交易价格 | 换算价格 | 更新时间
        for c in self._rows(html, 1):
            if len(c) >= 3 and c[0] != "交易品种":
                market.append({"name": c[0], "raw": c[1], "cny": self._num(c[2])})
        return shops, market

    def _fetch_bank(self) -> List[dict]:
        """金价表: 交易品种 | 最新价 | 昨收 | 涨跌额 | 涨跌幅 | 更新时间, 仅取纸黄金"""
        html = self._get(self._BANK_URL)
        banks = []
        for c in self._rows(html, 0):
            if len(c) >= 5 and "黄金" in c[0]:  # 过滤纸白银/纸铂金/纸钯金
                banks.append({
                    "name": c[0],
                    "price": self._num(c[1]),
                    "chg": c[3].strip(),
                    "pct": c[4].strip(),
                })
        return banks

    # =====================================================================
    #  排版
    # =====================================================================
    @staticmethod
    def _to_f(v) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _fmt_market(self, market: List[dict], prev: Dict[str, float] = None) -> str:
        prev = prev or {}
        lines = ["💰 大盘金价 (元/克)"]
        for m in market:
            if "黄金" in m["name"]:
                extra = f"  ({m['raw']})" if m["raw"] and m["raw"] != m["cny"] else ""
                d = self._delta(self._to_f(m["cny"]), prev.get(m["name"]))
                dtxt = f"  较昨日 {d}" if d else ""
                lines.append(f"· {m['name']}: {m['cny']}{extra}{dtxt}")
        return "\n".join(lines)

    def _fmt_shops(self, shops: List[dict], prev: Dict[str, float] = None) -> str:
        prev = prev or {}
        wanted = [s.strip() for s in self._shops.split(",") if s.strip()] if self._shops else []
        if wanted:
            order = {n: i for i, n in enumerate(wanted)}
            shops = sorted([s for s in shops if s["name"] in order],
                           key=lambda s: order[s["name"]])
        lines = ["🏪 金店零售价 (元/克)"]
        for s in shops:
            buy = f"  换购 {s['buy']}" if s["buy"] else ""
            d = self._delta(self._to_f(s["price"]), prev.get(s["name"]))
            dtxt = f"  较昨日 {d}" if d else ""
            lines.append(f"· {s['name']}: {s['price']}{buy}{dtxt}")
        return "\n".join(lines)

    def _fmt_banks(self, banks: List[dict], prev: Dict[str, float] = None) -> str:
        prev = prev or {}
        lines = ["🏦 银行纸黄金 (元/克)"]
        for b in banks:
            # 优先用历史算日环比, 无历史则回退数据源自带涨跌
            d = self._delta(self._to_f(b["price"]), prev.get(b["name"]))
            if d:
                dtxt = f"  较昨日 {d}"
            else:
                dtxt = f"  {b['chg']} ({b['pct']})" if b["chg"] else ""
            lines.append(f"· {b['name']}: {b['price']}{dtxt}")
        return "\n".join(lines)

    def summary(self):
        """周期汇报: 对比周期起点与最新价, 发送变化摘要"""
        if not self._summary_period:
            return
        now = datetime.now(self._TZ)
        today = now.strftime("%Y-%m-%d")
        period_labels = {"week": "周报", "month": "月报", "year": "年报"}
        label = period_labels.get(self._summary_period, "汇报")

        # 周期起点
        if self._summary_period == "week":
            days_back = 7
        elif self._summary_period == "month":
            days_back = 30
        else:  # year
            days_back = 365
        since = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")

        base_date, base_rec = self._baseline_record(since)
        latest_date, latest_rec = self._latest_record()
        if not base_rec or not latest_rec or base_date == latest_date:
            logger.info(f"金价日报: {label}数据不足, 跳过")
            return

        lines = [f"📈 金价{label}  {base_date} → {latest_date}"]

        def section(title: str, kind: str, name_filter: Optional[List[str]] = None):
            base_d = base_rec.get(kind, {})
            cur_d = latest_rec.get(kind, {})
            if not base_d or not cur_d:
                return
            # 应用白名单筛选(与每日推送保持一致)
            names = list(cur_d.keys())
            if name_filter:
                order = {n: i for i, n in enumerate(name_filter)}
                names = sorted([n for n in names if n in order], key=lambda n: order[n])
            rows = []
            for name in names:
                cur_v = cur_d.get(name)
                base_v = base_d.get(name)
                if cur_v is None:
                    continue
                d = self._delta(cur_v, base_v)
                dtxt = f"  {d}" if d else ""
                # base_v 缺失时(该项在周期起点不存在)只显示当前价
                base_str = f"{base_v:.2f}→" if base_v is not None else "新增→"
                rows.append(f"· {name}: {base_str}{cur_v:.2f}{dtxt}")
            if rows:
                lines.append(f"\n{title}")
                lines.extend(rows)

        # 金店白名单
        wanted_shops: Optional[List[str]] = (
            [s.strip() for s in self._shops.split(",") if s.strip()]
            if self._shops else None
        )

        if self._show_market:
            section("💰 大盘金价 (元/克)", "market")
        if self._show_shop:
            section("🏪 金店零售价 (元/克)", "shop", name_filter=wanted_shops)
        if self._show_bank:
            section("🏦 银行纸黄金 (元/克)", "bank")

        self._post_summary("\n".join(lines), label)
        logger.info(f"金价日报: {label}推送完成")

    def _post_summary(self, text: str, label: str):
        mtype = NotificationType.Plugin
        if self._msgtype:
            try:
                mtype = NotificationType[self._msgtype]
            except KeyError:
                mtype = NotificationType.Plugin
        self.post_message(mtype=mtype, title=f"📊 金价{label}", text=text)

    def stop_service(self):
        """插件停止时清理"""
        pass
