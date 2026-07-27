import re
from datetime import datetime
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
    plugin_version = "1.0.0"
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
                    # 第二行: cron / 消息类型
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
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
                                "props": {"cols": 12, "md": 6},
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
                                                    "推送走系统通知渠道，请先在「设置 → 通知」启用微信等渠道。",
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
            "show_market": True,
            "show_shop": True,
            "show_bank": True,
            "shops": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        """详情页: 无独立数据展示，返回 None"""
        return None

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时服务"""
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except Exception as e:
            logger.error(f"金价日报: cron 表达式非法 [{self._cron}]: {e}, 回退默认 30 9 * * *")
            trigger = CronTrigger.from_crontab("30 9 * * *")
        return [
            {
                "id": "GoldPricePush",
                "name": "金价日报推送",
                "trigger": trigger,
                "func": self.push,
                "kwargs": {},
            }
        ]

    # =====================================================================
    #  主流程
    # =====================================================================
    def push(self):
        """定时触发: 抓取金价并推送"""
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

        # 排版
        if self._show_market and market:
            blocks.append(self._fmt_market(market))
        if self._show_shop and shops:
            blocks.append(self._fmt_shops(shops))
        if self._show_bank and banks:
            blocks.append(self._fmt_banks(banks))

        if not blocks:
            # 全部失败也要告知, 不静默
            msg = "金价日报抓取失败:\n" + "\n".join(f"· {e}" for e in (errors or ["无数据"]))
            logger.warning(msg)
            self._post(msg)
            return

        now = datetime.now(self._TZ).strftime("%Y-%m-%d %H:%M")
        text = f"⏰ {now}\n\n" + "\n\n".join(blocks)
        if errors:
            text += "\n\n⚠️ 部分数据获取失败: " + "、".join(errors)

        self._post(text)
        logger.info("金价日报: 推送完成")

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
    def _fmt_market(self, market: List[dict]) -> str:
        lines = ["💰 大盘金价 (元/克)"]
        for m in market:
            if "黄金" in m["name"]:
                extra = f"  ({m['raw']})" if m["raw"] and m["raw"] != m["cny"] else ""
                lines.append(f"· {m['name']}: {m['cny']}{extra}")
        return "\n".join(lines)

    def _fmt_shops(self, shops: List[dict]) -> str:
        wanted = [s.strip() for s in self._shops.split(",") if s.strip()] if self._shops else []
        if wanted:
            order = {n: i for i, n in enumerate(wanted)}
            shops = sorted([s for s in shops if s["name"] in order],
                           key=lambda s: order[s["name"]])
        lines = ["🏪 金店零售价 (元/克)"]
        for s in shops:
            buy = f"  换购 {s['buy']}" if s["buy"] else ""
            lines.append(f"· {s['name']}: {s['price']}{buy}")
        return "\n".join(lines)

    def _fmt_banks(self, banks: List[dict]) -> str:
        lines = ["🏦 银行纸黄金 (元/克)"]
        for b in banks:
            chg = f"  {b['chg']} ({b['pct']})" if b["chg"] else ""
            lines.append(f"· {b['name']}: {b['price']}{chg}")
        return "\n".join(lines)

    def stop_service(self):
        """插件停止时清理"""
        pass
