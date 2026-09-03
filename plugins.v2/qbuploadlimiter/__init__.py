"""
QB上传限速插件（MoviePilot v2/v3）。

功能：
1. 定时轮询已选下载器（qBittorrent / Transmission）中的种子；
2. 仅处理 MoviePilot 已「整理入库成功」的种子：种子入库成功前对插件完全不可见，不监控、不限速（等同于插件未开启），入库成功后才按分享率限速；
3. 种子分享率（上传量 / 下载量）达到全局或站点单独阈值后，自动限制该种子上传速度为指定值（KB/s）；qBittorrent 全局上传限速更低时自动采用全局值，上传速度填 0 时不做限速处理；
4. 支持按站点筛选和按站点单独设置分享率阈值；未配置单独阈值的站点回退使用全局阈值；
5. 可选 AI 智能限速：调用系统设置中已配置的大模型（智能体），按「种子分享率、上传活跃度、站点账号分享率」逐种子智能决策限速值与是否限速，仅在种子活跃（有实际上传流量）时评估，休眠种子自动跳过；大模型未配置/调用失败/输出解析失败时自动回退常规分享率阈值限速，无需在本插件配置任何 API 密钥；
6. 停用或卸载插件时，自动将本插件限速过的种子恢复为不限速；
7. 限速通知支持多选 MoviePilot 已启用通知渠道，测试通知仅首次发送；
8. 支持监控超时取消：下载完成后达不到限速值、或限速后持续超时/速度低于限速值 80% 时，取消监控并立即恢复该种子不限速。
"""

import asyncio
import datetime
import inspect
import json
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.helper.service import ServiceConfigHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ServiceInfo
from app.schemas.types import MessageChannel


class QbUploadLimiter(_PluginBase):
    """
    分享率限速插件。

    当 qBittorrent / Transmission 下载器中已下载的种子分享率达到设定阈值时，
    自动将该种子的上传速度限制为指定值（KB/s）。
    分享率 = 上传量 / 下载量，阈值为正数（最多 1 位小数），达到阈值后自动限速。
    """

    plugin_name = "QB上传限速"
    plugin_desc = "仅处理 MoviePilot 已整理入库成功的种子：分享率达到全局或站点单独阈值后自动限制上传速度（qBittorrent 与全局上传限速取较小值）；可选 AI 智能限速——调用系统设置的大模型按种子分享率、上传活跃度与站点账号分享率逐种子智能决策限速；支持多下载器、站点筛选、定时检测，停用/卸载自动恢复不限速。"
    plugin_icon = "Qbittorrent_A.png"
    plugin_version = "1.3.19"
    plugin_author = "xlmc"
    author_url = "https://github.com/xlmc"
    plugin_config_prefix = "qbuploadlimiter_"
    plugin_order = 30
    auth_level = 1

    LOG_TAG = "[QB上传限速] "

    # ---- 配置项默认值 ----
    _enabled = False
    _onlyonce = False
    # 已选择的通知渠道类型（如 telegram / wechat），留空表示不发通知
    _notify_channel = []
    # 全局分享率阈值（正数，最多 1 位小数，不能为 0 或负）
    _share_ratio = 1.0
    # 站点名称（小写）-> 单独分享率阈值；未命中时使用全局阈值
    _site_share_ratios: Dict[str, float] = {}
    # 站点单独阈值表单的规范化文本（每行「站点=阈值」）
    _site_share_ratios_text = ""
    # 上传速度 KB/s，0 表示分享率达到阈值后不做限速处理
    _upload_limit = 2000
    # 定时检测间隔（秒）
    _interval_seconds = 30
    # 已选择的下载器名称
    _downloaders = []
    # 已选择的站点名称，为空表示对所有种子生效
    _sites = []
    # 站点域名(小写) -> 站点名称，用于 tracker 域名匹配
    _site_domains: Dict[str, str] = {}
    # 站点名称(小写) -> 原始名称，用于标签/分类匹配
    _site_names: Dict[str, str] = {}

    _scheduler = None
    _last_result = None
    # 停用/卸载后兜底恢复重试的调度器与已重试次数：恢复失败项在下载器重连后自动重试
    _retry_scheduler = None
    _retry_attempts = 0
    # 兜底恢复重试的报告间隔（每 60 秒重试一次，累计达到该次数输出一次告警；
    # 任务持续运行直到全部恢复成功，不因下载器长期离线而提前终止）
    _MAX_RESTORE_RETRY = 60
    # 已被本插件限速且仍受监控的种子：{下载器名称: {种子Hash}}
    _limited_hashes: Dict[str, set] = {}
    # 本插件本次会话中设置过限速、停用/卸载时必须恢复的种子：{下载器名称: {种子Hash}}
    _restore_hashes: Dict[str, set] = {}
    # 已下载完成种子上传速度持续低于限速值的起始时间：{下载器名称: {种子Hash: 时间戳}}
    # 用于「下载完成后监控超时」的连续低速计时，速度回升到限速值即清零重新计时
    _complete_slow_since: Dict[str, Dict[str, float]] = {}

    # ---- AI 智能限速 ----
    # 是否启用 AI 智能限速（需 MoviePilot 系统设置已配置大模型）
    _ai_enabled = False
    # AI 评估间隔（秒）：两次大模型调用之间的最小间隔
    _ai_eval_interval = 3600
    # AI 限速上限（KB/s），0 表示使用配置的上传速度作为上限
    _ai_max_limit = 0
    # AI 账号分享率门槛：站点账号分享率达到该值才对该站种子生效 AI 决策，0 表示不启用（正整数）
    _ai_site_ratio_threshold = 0
    # 种子状态机：{下载器名称: {种子Hash: 状态}}
    # 状态：pending（待评估）/ limited（限速中）/ recovering（恢复中）/ idle（忽略）
    _seed_states: Dict[str, Dict[str, str]] = {}
    # AI 决策缓存：{下载器名称: {种子Hash: {action, limit_kb, reason, ts}}}
    _ai_decisions: Dict[str, Dict[str, dict]] = {}
    # 上传量快照（活跃度窗口增量）：{下载器名称: {种子Hash: 上次累计上传量(字节)}}
    _uploaded_snapshots: Dict[str, Dict[str, float]] = {}
    # 上次大模型调用时间戳（限频）
    _last_ai_eval_at = 0.0
    # 系统设置未配置大模型标记：置位后降频重试探测（而非永久放弃），补配置后自动恢复
    _ai_config_missing = False
    # 下次重试探测大模型配置的时间戳（配置缺失时降频重试，避免每轮刷错误日志）
    _ai_config_retry_at = 0.0
    # AI 智能限速已成功生效标记：大模型自检通过或至少一次评估调用成功后置位，
    # 用于详情页（种子状态页）的显隐——未成功开启 AI 前保持点击卡片直接进设置
    _ai_active = False
    # 自检序号：每次重新初始化递增，旧的自检线程完成时若已被新一轮取代则丢弃结果，
    # 避免慢速自检在保存配置后误置位新一轮的生效标记
    _ai_check_seq = 0
    # 种子状态页快照：{下载器名称: {种子Hash: {name, site, state, limit_kb, reason}}}
    # 每轮检测后更新，get_page 渲染时使用，避免页面请求时再访问下载器
    _seed_page_snapshot: Dict[str, Dict[str, dict]] = {}
    # 种子状态常量
    _STATE_PENDING = "pending"      # 待评估：已入库+活跃，等待 AI/规则决策
    _STATE_LIMITED = "limited"      # 限速中：已被本插件限速且仍受监控
    _STATE_RECOVERING = "recovering"  # 恢复中：超时放掉正在恢复不限速（含待重试）
    _STATE_NO_LIMIT = "no_limit"    # AI 不限速：AI 已评估且判定当前不限速
    _STATE_IDLE = "idle"            # 忽略：无上传流量或已放掉，插件零操作

    # 持久化数据键：跨会话保留待恢复限速种子 / 已取消监控种子
    _RESTORE_DATA_KEY = "restore_hashes"
    _CANCELED_DATA_KEY = "canceled_hashes"

    # 通知渠道类型（MoviePilot 通知配置的 type）-> MessageChannel 枚举
    _NOTIFY_TYPE_MAP = {
        "telegram": MessageChannel.Telegram,
        "wechat": MessageChannel.Wechat,
        "feishu": MessageChannel.Feishu,
        "wechatclawbot": MessageChannel.WechatClawBot,
        "slack": MessageChannel.Slack,
        "discord": MessageChannel.Discord,
        "synologychat": MessageChannel.SynologyChat,
        "vocechat": MessageChannel.VoceChat,
        "webpush": MessageChannel.WebPush,
        "qqbot": MessageChannel.QQ,
    }

    # ---------------------------------------------------------------- 生命周期

    def init_plugin(self, config: dict = None):
        """
        初始化插件：读取配置并按需立即检测限速、启动定时检测任务。
        插件从启用变为停用时，自动将已限速种子恢复为不限速。
        """
        was_enabled = self._enabled
        old_downloaders = self._downloaders or []
        self._stop_scheduler()

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        # 重新启用插件时停止停用期间运行的兜底恢复重试任务（恢复失败的记录仍保留，
        # 随本轮轮询或保存配置继续处理）；wait=True 等待在途重试任务结束，
        # 避免其恢复流程与立即执行的 apply_limit 并发撤销刚重新应用的限速
        if self._enabled:
            self._stop_restore_retry(wait=True)
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify_channel = self._normalize_channels(config.get("notify_channel"))
        self._share_ratio = self._to_ratio(config.get("share_ratio"), 1.0)
        self._site_share_ratios, self._site_share_ratios_text = self._normalize_site_share_ratios(
            config.get("site_share_ratios")
        )
        self._upload_limit = max(self._to_int(config.get("upload_limit"), 2000), 0)
        self._interval_seconds = max(self._to_int(config.get("interval_seconds"), 30), 10)
        # 监控超时取消配置（秒），0 表示不启用
        self._complete_timeout = max(self._to_int(config.get("complete_timeout"), 0), 0)
        self._limit_timeout = max(self._to_int(config.get("limit_timeout"), 0), 0)
        # AI 智能限速配置
        self._ai_enabled = bool(config.get("ai_enabled"))
        self._ai_eval_interval = max(self._to_int(config.get("ai_eval_interval"), 3600), 60)
        self._ai_max_limit = max(self._to_int(config.get("ai_max_limit"), 0), 0)
        self._ai_site_ratio_threshold = max(self._to_int(config.get("ai_site_ratio_threshold"), 0), 0)
        self._downloaders = self._normalize_config_list(config.get("downloaders"))
        self._sites = self._normalize_config_list(config.get("sites"))
        # 站点映射（域名 -> 名称、名称小写 -> 名称）只构建一次，供本轮所有种子复用
        self._site_domains = self._load_site_domains()
        self._site_names = {name.lower(): name for name in self._site_domains.values() if name}

        # 规范化持久化：修正历史遗留的非法配置（如分享率阈值 0、字符串数字等），
        # 避免非法值回显到表单或影响后续逻辑
        try:
            if self._current_config() != config:
                self.update_config(self._current_config())
        except Exception:
            pass

        # 版本升级后允许重新发送一次测试通知（同一版本内仍仅发送一次），
        # 便于升级后验证通知渠道是否可用
        try:
            if self.get_data("last_version") != self.plugin_version:
                self.save_data("notify_test_sent", False)
                self.save_data("last_version", self.plugin_version)
        except Exception:
            pass

        # 加载跨会话持久化的待恢复/已取消监控记录：保存配置或重启后仍保留，
        # 确保已限速种子停用/卸载时可兜底恢复、已取消监控种子不再被重新干预
        self._restore_hashes = self._load_set_map(self._RESTORE_DATA_KEY)
        self._canceled_hashes = self._load_set_map(self._CANCELED_DATA_KEY)

        # 停用插件或启用状态下修改配置时，先恢复旧配置下已限速的种子为不限速，
        # 避免清空记录后旧限速丢失归属、停用/卸载时无法恢复
        if was_enabled:
            self._restore_limits(downloaders=old_downloaders)

        # 每次重新初始化时仅清空本次会话的限速/计时记录；
        # 待恢复记录与已取消监控记录保留（恢复失败的仍可重试，取消状态不丢失）
        self._limited_hashes = {}
        self._limited_times = {}
        self._slow_since = {}
        self._complete_slow_since = {}
        # 种子状态机、AI 决策缓存与上传量快照为会话级数据，重新初始化时清空，
        # 快照丢失后首轮只建快照、次轮起窗口增量判断生效，种子状态自动重新归位
        self._seed_states = {}
        self._ai_decisions = {}
        self._uploaded_snapshots = {}
        self._last_ai_eval_at = 0.0
        self._ai_config_missing = False
        self._ai_config_retry_at = 0.0
        self._seed_page_snapshot = {}
        # 重新初始化后 AI 生效标记与决策缓存一并清零：详情页显隐跟随新一轮
        # 大模型调用结果重新判定，避免保存配置后出现「有页面无数据」或残留旧标记
        self._ai_active = False
        # AI 启用时保存配置即自动后台自检大模型连通性（不阻塞定时检测），
        # 自检结果写入插件日志；自检通过即视为 AI 生效，详情页立即可用
        if self._ai_enabled:
            self._ai_check_seq += 1
            seq = self._ai_check_seq
            threading.Thread(
                target=self._ai_background_check, args=(seq,), daemon=True, name="QbUploadLimiterAICheck"
            ).start()

        # 「立即运行一次」与启用状态下的周期任务独立调度，互不覆盖
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        if self._onlyonce:
            self._onlyonce = False
            self.update_config(self._current_config())
            self._scheduler.add_job(
                func=self.apply_limit,
                trigger="date",
                run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3),
                kwargs={"manual": True},
                name="立即检测 QB 上传限速",
            )

        # 启用插件：先立即检测一次，再按间隔定时检测
        if self._enabled:
            self.apply_limit(manual=False)
            self._scheduler.add_job(
                func=self.apply_limit,
                trigger="interval",
                seconds=self._interval_seconds,
                kwargs={"manual": False},
                name="定时检测 QB 上传限速",
            )
        self._start_scheduler()
        # 持久化待恢复/已取消监控记录（恢复失败项保留，已取消项不丢失）
        self._save_set_map(self._RESTORE_DATA_KEY, self._restore_hashes)
        self._save_set_map(self._CANCELED_DATA_KEY, self._canceled_hashes)
        # 停用状态下仍有待恢复记录时，启动兜底恢复重试任务：下载器短暂离线导致的
        # 恢复失败，在下载器重连后自动恢复不限速，无需重新启用插件
        if not self._enabled:
            self._start_restore_retry()

    def stop_service(self):
        """
        停止后台任务；停用或卸载插件时自动将已限速种子恢复为不限速。
        """
        self._stop_scheduler()

        try:
            self._restore_limits()
        except Exception as err:
            logger.error(f"{self.LOG_TAG}恢复上传不限速失败：{err}")
        # 持久化恢复结果：恢复失败项保留，下次停用/卸载时继续重试
        self._save_set_map(self._RESTORE_DATA_KEY, self._restore_hashes)
        self._save_set_map(self._CANCELED_DATA_KEY, self._canceled_hashes)
        # 仍有待恢复记录时启动兜底恢复重试任务：下载器短暂离线导致的恢复失败，
        # 在下载器重连后自动恢复不限速，无需再次触发停止流程
        self._start_restore_retry()

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """不注册额外 API。"""
        return []

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return bool(self._enabled)

    _STATE_LABELS = {
        "pending": "待评估",
        "limited": "限速中",
        "recovering": "恢复中",
        "no_limit": "AI 不限速",
        "idle": "忽略",
    }

    def get_page(self) -> Optional[List[dict]]:
        """
        种子状态详情页（彩蛋）：仅当 AI 智能限速已成功生效（至少一次大模型调用
        并解析成功）时返回状态页面，点击插件卡片进入该页查看每个种子的状态；
        未成功开启 AI 时返回 None，保持点击卡片直接进入插件设置的原有行为。
        """
        # AI 未启用或未成功生效：无详情页，点击卡片直接进设置
        if not self._ai_enabled or not self._ai_active:
            return None
        # 汇总各下载器的种子状态快照
        rows: List[dict] = []
        for service_name, snapshot in self._seed_page_snapshot.items():
            for info in snapshot.values():
                rows.append({**info, "service": service_name})
        if not rows:
            return [
                {
                    "component": "div",
                    "text": "AI 智能限速已生效，暂无已入库种子数据（等待下轮检测）",
                    "props": {"class": "text-center"},
                }
            ]
        # 状态排序：限速中 > 待评估 > 恢复中 > AI 不限速 > 忽略
        order = {"limited": 0, "pending": 1, "recovering": 2, "no_limit": 3, "idle": 4}
        rows.sort(key=lambda r: (order.get(r.get("state"), 9), r.get("service", "")))
        # 顶部状态统计卡片
        counts: Dict[str, int] = {}
        for row in rows:
            label = self._STATE_LABELS.get(row.get("state"), row.get("state"))
            counts[label] = counts.get(label, 0) + 1
        header_cards = []
        for label in ("待评估", "限速中", "恢复中", "AI 不限速", "忽略"):
            header_cards.append(
                {
                    "component": "VCol",
                    "props": {"cols": 6, "md": 3},
                    "content": [
                        {
                            "component": "VCard",
                            "props": {"class": "text-center"},
                            "content": [
                                {
                                    "component": "VCardText",
                                    "props": {"class": "pa-2 text-h6"},
                                    "text": str(counts.get(label, 0)),
                                },
                                {
                                    "component": "VCardText",
                                    "props": {"class": "pa-2 pt-0 text-caption"},
                                    "text": label,
                                },
                            ],
                        }
                    ],
                }
            )
        # 种子状态列表
        list_items = []
        for row in rows:
            state = row.get("state")
            label = self._STATE_LABELS.get(state, state)
            limit_kb = int(row.get("limit_kb") or 0)
            limit_text = f"，限速 {limit_kb} KB/s" if state == "limited" and limit_kb > 0 else ""
            site = str(row.get("site") or "").strip()
            site_text = f"（{site}）" if site else ""
            reason = str(row.get("reason") or "").strip()
            reason_text = f"：{reason}" if reason else ""
            list_items.append(
                {
                    "component": "VListItem",
                    "props": {"class": "px-2"},
                    "content": [
                        {
                            "component": "VListItemTitle",
                            "text": f"[{row.get('service')}] {row.get('name')}{site_text}",
                        },
                        {
                            "component": "VListItemSubtitle",
                            "text": f"{label}{limit_text}{reason_text}",
                        },
                    ],
                }
            )
        return [
            {
                "component": "VRow",
                "content": header_cards,
            },
            {
                "component": "VCard",
                "props": {"class": "mt-2"},
                "content": [
                    {"component": "VCardTitle", "props": {"class": "text-subtitle-1"}, "text": "种子状态"},
                    {
                        "component": "VList",
                        "props": {"density": "compact"},
                        "content": list_items,
                    },
                ],
            },
        ]

    # ---------------------------------------------------------------- 设置表单
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        插件设置表单：
        第一行：启用插件 / 立即运行一次 / 发送通知（多选渠道）；
        第二行：下载器（多选）/ 站点（多选，按站点筛选）；
        第三行：全局分享率阈值 / 上传速度 / 定时检测间隔；
        第四行：按站点单独分享率阈值；
        第五行：下载完成后监控超时 / 限速后取消监控超时；
        第六行：功能说明。
        """
        # 下载器下拉：MoviePilot 已配置并启用的 qBittorrent / Transmission
        downloader_items = []
        try:
            for conf in (ServiceConfigHelper.get_downloader_configs() or []):
                if not getattr(conf, "enabled", False):
                    continue
                conf_name = getattr(conf, "name", "") or ""
                conf_type = getattr(conf, "type", "") or ""
                if conf_type in ("qbittorrent", "transmission") and conf_name:
                    downloader_items.append({"title": conf_name, "value": conf_name})
        except Exception as err:
            logger.warning(f"{self.LOG_TAG}读取下载器配置失败：{err}")

        # 通知渠道下拉：MoviePilot 已启用渠道的类型去重（如 telegram / wechat）
        notify_items = []
        try:
            seen_types = set()
            for conf in (ServiceConfigHelper.get_notification_configs() or []):
                if not getattr(conf, "enabled", False):
                    continue
                conf_type = getattr(conf, "type", "") or ""
                conf_name = getattr(conf, "name", "") or conf_type
                if conf_type and conf_type not in seen_types:
                    seen_types.add(conf_type)
                    notify_items.append({"title": conf_name, "value": conf_type})
        except Exception as err:
            logger.warning(f"{self.LOG_TAG}读取通知渠道配置失败：{err}")

        # 站点下拉：与站点管理排序一致（按优先级 pri 升序，同优先级保持原顺序）
        site_items = []
        try:
            from app.helper.sites import SitesHelper
            site_list = [
                site for site in (SitesHelper().get_indexers() or [])
                if site.get("is_active") and str(site.get("name") or "").strip()
            ]
            site_list.sort(key=lambda s: s.get("pri") or 0)
            site_items = [
                {
                    "title": str(site.get("name") or "").strip(),
                    "value": str(site.get("name") or "").strip(),
                }
                for site in site_list
            ]
        except Exception as err:
            logger.warning(f"{self.LOG_TAG}读取站点配置失败：{err}")

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
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "onlyonce", "label": "立即运行一次"},
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
                                            "model": "notify_channel",
                                            "label": "发送通知",
                                            "items": notify_items,
                                            "multiple": True,
                                            "chips": True,
                                            "clearable": True,
                                            "hint": "可多选 MoviePilot 系统设置中已配置并启用的通知渠道；留空表示不发送通知。",
                                            "persistent-hint": True,
                                        },
                                    }
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
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "downloaders",
                                            "label": "下载器",
                                            "items": downloader_items,
                                            "multiple": True,
                                            "chips": True,
                                            "clearable": True,
                                            "hint": "留空时不会修改任何下载器；请选择 MoviePilot 中已配置的 qBittorrent 或 Transmission 下载器。",
                                            "persistent-hint": True,
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
                                            "model": "sites",
                                            "label": "站点（按站点筛选）",
                                            "items": site_items,
                                            "multiple": True,
                                            "chips": True,
                                            "clearable": True,
                                            "hint": "留空表示对所有种子生效；勾选站点后，仅对所选站点下载的种子进行上传限速。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "share_ratio",
                                            "label": "全局分享率阈值",
                                            "placeholder": "正数（>0），最多 1 位小数；站点未配置单独阈值时使用该值",
                                            "type": "number",
                                            "min": 0.1,
                                            "step": 0.1,
                                            "hint": "不能为 0 或负数，最多保留 1 位小数（如 1.5），多余位四舍五入",
                                            "persistent-hint": True,
                                            "onKeydown": "function (e) { if (e.key === '-') { e.preventDefault(); } }",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "upload_limit",
                                            "label": "上传速度（KB/s）",
                                            "placeholder": "例如 2000；qB 全局上传限速更低时采用全局值；0 表示不做限速处理",
                                            "type": "number",
                                            "min": 0,
                                            "step": 1,
                                            "hide-spin-buttons": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "interval_seconds",
                                            "label": "定时检测间隔（秒）",
                                            "placeholder": "建议设置 30 秒以上",
                                            "type": "number",
                                            "min": 10,
                                            "step": 10,
                                            "hide-spin-buttons": True,
                                            "hint": "建议设置 30 秒以上",
                                            "persistent-hint": True,
                                            "onKeydown": "function (e) { if (e.key === '0') { var v = e.target.value || ''; var s = e.target.selectionStart || 0; var en = e.target.selectionEnd || 0; var next = v.slice(0, s) + '0' + v.slice(en); if (/^0+$/.test(next)) { e.preventDefault(); } } }",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "ai_enabled", "label": "启用 AI 智能限速"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_eval_interval",
                                            "label": "AI 评估间隔（秒）",
                                            "placeholder": "默认 3600（1 小时）",
                                            "type": "number",
                                            "min": 60,
                                            "step": 60,
                                            "hide-spin-buttons": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_max_limit",
                                            "label": "AI 限速上限（KB/s）",
                                            "placeholder": "0 表示使用上方「上传速度」",
                                            "type": "number",
                                            "min": 0,
                                            "step": 1,
                                            "hide-spin-buttons": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_site_ratio_threshold",
                                            "label": "AI 账号分享率门槛",
                                            "placeholder": "0 = 不启用",
                                            "hint": "正整数，0=不启用；站点账号分享率达到该值才对该站种子生效 AI 决策，未达标（或查不到）回退常规阈值规则",
                                            "persistent-hint": True,
                                            "type": "number",
                                            "min": 0,
                                            "step": 1,
                                            "hide-spin-buttons": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "AI 智能限速：调用 MoviePilot 系统设置中已配置的大模型（智能体），无需在本插件重复配置 API 密钥/模型；由大模型根据「种子分享率、上传活跃度、站点账号分享率」逐种子决策限速值与是否限速，仅在种子活跃（有实际上传流量）时评估，休眠种子自动跳过；大模型调用失败、超时或未配置时自动回退常规分享率阈值限速。",
                                        },
                                    }
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
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "site_share_ratios",
                                            "label": "按站点单独分享率阈值",
                                            "placeholder": "一行一个，例如：\n站点A=3\n站点B=5.5",
                                            "rows": 3,
                                            "auto-grow": True,
                                            "clearable": True,
                                            "hint": "格式：站点名称=正数阈值（>0，最多 1 位小数）。对应站点使用单独阈值；未配置或无法识别站点时回退使用全局分享率阈值。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
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
                                            "model": "complete_timeout",
                                            "label": "下载完成后监控超时（秒）",
                                            "placeholder": "0 表示不启用；例如 300",
                                            "type": "number",
                                            "min": 0,
                                            "step": 1,
                                            "hide-spin-buttons": True,
                                            "hint": "种子下载完成后，插件持续监控其上传速度；上传速度持续低于限速值达到设定秒数时，取消监控并立即恢复该种子不限速",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "limit_timeout",
                                            "label": "限速后取消监控超时（秒）",
                                            "placeholder": "0 表示不启用；例如 600",
                                            "type": "number",
                                            "min": 0,
                                            "step": 1,
                                            "hide-spin-buttons": True,
                                            "hint": "种子被限速后，持续限速或上传速度低于限速值 80% 达到设定秒数时，取消监控并立即恢复该种子不限速",
                                            "persistent-hint": True,
                                        },
                                    }
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
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "本插件仅处理 MoviePilot 已整理入库成功的种子：种子入库成功前不监控、不限速（等同于插件未开启），入库成功后按分享率逐种子限速——分享率（上传量/下载量）达到全局或站点单独设置的正数阈值（>0，最多 1 位小数）后，其上传速度将被限制为设定值（KB/s）。站点单独阈值使用「站点名称=阈值」格式，一行一个；未配置或无法识别站点时使用全局阈值。上传速度填 0 表示不做限速处理；两个监控超时填 0 表示不启用对应功能。支持 qBittorrent 和 Transmission。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], self._current_config()

    def _current_config(self) -> Dict[str, Any]:
        """返回当前配置，供表单回填。"""
        return {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify_channel": self._notify_channel,
            "share_ratio": self._share_ratio,
            "site_share_ratios": self._site_share_ratios_text,
            "upload_limit": self._upload_limit,
            "interval_seconds": self._interval_seconds,
            "complete_timeout": self._complete_timeout,
            "limit_timeout": self._limit_timeout,
            "ai_enabled": self._ai_enabled,
            "ai_eval_interval": self._ai_eval_interval,
            "ai_max_limit": self._ai_max_limit,
            "ai_site_ratio_threshold": self._ai_site_ratio_threshold,
            "downloaders": self._downloaders,
            "sites": self._sites,
        }

    # ---------------------------------------------------------------- 核心逻辑

    def apply_limit(self, manual: bool = False):
        """
        按分享率阈值对种子应用上传限速。
        手动运行（点击「立即运行一次」）时，额外发送一次仅首启的测试通知。
        """
        if not self._enabled and not manual:
            return
        if manual:
            self._send_test_notify_if_needed()
        self._set_torrent_limits(self._share_ratio, self._upload_limit, channel=self._notify_channel)

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """获取已连接的 qBittorrent / Transmission 下载器。"""
        return self._get_services()

    def _get_services(self, downloaders: Optional[List[str]] = None) -> Optional[Dict[str, ServiceInfo]]:
        """
        获取已启用且可连接的 qBittorrent / Transmission 下载器实例。

        :param downloaders: 下载器名称列表；为空时使用插件配置中的下载器
        :return: {下载器名称: ServiceInfo}，无可用下载器时返回 None
        """
        names = downloaders if downloaders is not None else self._downloaders
        if not names:
            logger.warning(f"{self.LOG_TAG}尚未选择下载器")
            return None

        services = DownloaderHelper().get_services(name_filters=names)
        if not services:
            logger.warning(f"{self.LOG_TAG}获取下载器实例失败，请检查配置")
            return None

        helper = DownloaderHelper()
        active_services = {}
        for service_name, service_info in services.items():
            if not (helper.is_downloader(service_type="qbittorrent", service=service_info)
                    or helper.is_downloader(service_type="transmission", service=service_info)):
                logger.warning(f"{self.LOG_TAG}下载器 [{service_name}] 不是 qBittorrent/Transmission，已跳过")
                continue
            if not getattr(service_info, "instance", None):
                logger.warning(f"{self.LOG_TAG}下载器 [{service_name}] 实例不存在，已跳过")
                continue
            if service_info.instance.is_inactive():
                logger.warning(f"{self.LOG_TAG}下载器 [{service_name}] 未连接，已跳过")
                continue
            active_services[service_name] = service_info

        if not active_services:
            logger.warning(f"{self.LOG_TAG}没有可用的 qBittorrent/Transmission 下载器")
            return None
        return active_services

    def _selected_sites(self) -> Optional[Set[str]]:
        """
        返回已勾选站点的规范化（小写）集合。

        :return: 勾选了站点时返回小写站点名集合；未勾选返回 None（表示不筛选站点）
        """
        sites = [str(site).strip() for site in (self._sites or []) if str(site).strip()]
        return {site.lower() for site in sites} if sites else None

    def _threshold_for_site(self, site: str, fallback: float) -> float:
        """返回种子所属站点的单独分享率阈值，未配置或站点未知时使用全局阈值。"""
        site_key = str(site or "").strip().lower()
        if not site_key:
            return fallback
        return self._site_share_ratios.get(site_key, fallback)

    def _effective_upload_limit(self, downloader: Any, downloader_type: str, configured_limit: int) -> float:
        """
        返回下载器实际应使用的单种子上传限速（KB/s）。

        qBittorrent 启用了全局上传限速时，插件配置与 qB 全局值取较小者；
        qB 全局值为 0（不限速）、读取失败或下载器为 Transmission 时使用插件配置。
        """
        limit = max(self._to_int(configured_limit, 0), 0)
        if limit <= 0 or str(downloader_type or "").strip().lower() != "qbittorrent":
            return limit

        get_speed_limit = getattr(downloader, "get_speed_limit", None)
        if not callable(get_speed_limit):
            logger.warning(f"{self.LOG_TAG}当前 qBittorrent 下载器不支持读取全局上传限速，使用插件配置 {self._format_limit(limit)}")
            return limit

        try:
            speed_limits = get_speed_limit()
            if not isinstance(speed_limits, (tuple, list)) or len(speed_limits) < 2:
                raise ValueError("返回值格式无效")
            qb_upload_limit = float(speed_limits[1] or 0)
        except Exception as err:
            logger.warning(f"{self.LOG_TAG}读取 qBittorrent 全局上传限速失败，使用插件配置 {self._format_limit(limit)}：{err}")
            return limit

        # qB 全局上传限速为 0 表示不限速；NaN 等无效值同样回退插件配置。
        if qb_upload_limit <= 0 or qb_upload_limit != qb_upload_limit:
            return limit

        effective_limit = min(float(limit), qb_upload_limit)
        # 常见的整数 KB/s 保持整数显示；非整 KB/s 则保留 qB 返回的精确值。
        return int(effective_limit) if effective_limit.is_integer() else effective_limit

    def _set_torrent_limits(self, share_ratio: float, upload_limit: int, channel: Any = None) -> bool:
        """
        检测所有选中下载器中的种子分享率，达到阈值的设置上传限速。

        站点筛选逻辑：
        - 勾选了站点：仅处理能识别出站点且属于勾选站点的种子；
        - 未勾选站点：处理全部种子。

        :param share_ratio: 分享率阈值
        :param upload_limit: 上传限速 KB/s
        :param channel: 通知渠道配置（原始值，可为字符串或列表）
        :return: 是否所有下载器均处理成功
        """
        services = self._get_services()
        if not services:
            # 无可用下载器时也需兜底重试所有待恢复记录：下载器可能已从插件选择中
            # 移除或短暂离线，重连后无需重新选择也能自动恢复不限速
            self._retry_all_stuck_restores()
            self._save_set_map(self._RESTORE_DATA_KEY, self._restore_hashes)
            self._last_result = "没有可用的 qBittorrent/Transmission 下载器，未执行限速。"
            return False

        threshold = self._to_ratio(share_ratio, 1.0)
        limit = max(self._to_int(upload_limit, 0), 0)
        # 上传速度为 0：分享率达到阈值后不做限速处理
        if limit == 0:
            # 顺带重试所有待恢复记录：切换为 0 时若下载器离线导致恢复失败，
            # 下载器重连后每轮检测都能自动恢复旧限速，不依赖重新启用插件
            self._retry_all_stuck_restores()
            self._save_set_map(self._RESTORE_DATA_KEY, self._restore_hashes)
            self._last_result = "上传速度为 0，分享率达到阈值后不做限速处理。"
            return True
        # 站点筛选集合（None 表示不过滤）
        selected = self._selected_sites()
        summary_lines = []
        if selected:
            summary_lines.append(f"站点筛选：{'、'.join(sorted(self._sites))}")
        if self._site_share_ratios_text:
            summary_lines.append(
                f"站点单独阈值：{self._site_share_ratios_text.replace(chr(10), '、')}"
                f"（其他站点使用全局阈值 {threshold:g}）"
            )
        failed_names = []

        for service_name, service_info in services.items():
            downloader = service_info.instance
            downloader_type = getattr(service_info, "type", "")
            effective_limit = self._effective_upload_limit(downloader, downloader_type, limit)
            try:
                torrents, error = downloader.get_torrents()
                if error:
                    failed_names.append(service_name)
                    logger.warning(f"{self.LOG_TAG}获取下载器 [{service_name}] 种子列表失败")
                    continue
                # 空列表是下载器中没有任何种子的合法成功结果，不是获取失败
                torrents = torrents or []

                # 入库成功门禁：先批量查询 MP 整理入库记录，得到「已入库成功」的种子集合；
                # 种子入库成功前对插件完全不可见（不监控、不限速），等同于插件未开启
                transferred_hashes = self._load_transferred_hashes(
                    [self._torrent_hash(t, downloader_type) for t in torrents]
                )
                eligible_torrents = [
                    t for t in torrents if self._torrent_hash(t, downloader_type) in transferred_hashes
                ]

                now = time.time()
                # 状态刷新用完整列表（确保仅清理真正已移除的种子状态），
                # 监控计时仅对已入库种子维护
                self._refresh_torrent_state(
                    service_name, torrents, downloader_type, effective_limit, now,
                    transferred_hashes=transferred_hashes,
                )
                # 站点识别缓存：{种子Hash: 站点名称}，同一轮内每个种子只计算一次
                site_cache: Dict[str, str] = {}
                # 「下载完成后监控超时」覆盖所有已完成且未认领的种子（不依赖分享率达标）：
                # 持续低速达到设定秒数即取消监控，避免速度回升清除计时后仍可能被限速
                timeout_canceled = 0
                if self._complete_timeout > 0 and effective_limit > 0:
                    history_sites: Dict[str, str] = {}
                    if selected:
                        hashes = [self._torrent_hash(t, downloader_type) for t in eligible_torrents]
                        history_sites = self._load_history_sites(hashes)
                    canceled_hashes = self._canceled_hashes.get(service_name, set())
                    owned_hashes = (self._limited_hashes.get(service_name, set())
                                    | self._restore_hashes.get(service_name, set()))
                    for torrent in eligible_torrents:
                        torrent_hash = self._torrent_hash(torrent, downloader_type)
                        if not torrent_hash or torrent_hash in canceled_hashes:
                            continue
                        # 已认领种子走「限速后超时」逻辑，此处只处理未认领种子
                        if torrent_hash in owned_hashes:
                            continue
                        if not self._torrent_completed(torrent, downloader_type):
                            continue
                        if selected:
                            site = self._resolve_site(torrent, torrent_hash, downloader_type, history_sites, site_cache)
                            if not site or site.lower() not in selected:
                                continue
                        if self._check_complete_timeout(service_name, torrent, downloader_type, torrent_hash, effective_limit, now):
                            self._cancel_monitoring(
                                service_name,
                                torrent_hash,
                                self._torrent_name(torrent, downloader_type) or torrent_hash,
                                reason="下载完成后达不到限速值",
                                downloader=downloader,
                                site=site_cache.get(torrent_hash, "") or self._torrent_site(torrent, downloader_type),
                                channels=self._normalize_channels(channel),
                            )
                            timeout_canceled += 1
                # 筛选出已入库且达标且（可选）属于勾选站点的种子；记录每个达标种子实际使用的阈值
                threshold_cache: Dict[str, float] = {}
                # AI 智能限速：对活跃种子批量评估决策；AI 生效时替换阈值规则，
                # 未配置大模型/调用失败/输出解析失败时回退常规阈值规则
                ai_mode = False
                ai_limits: Dict[str, float] = {}
                if self._ai_enabled:
                    decisions = self._ai_evaluate(
                        service_name, eligible_torrents, downloader_type, self._load_site_ratios(), now
                    )
                    if decisions:
                        ai_mode = True
                        ai_limits, ai_unlimit = self._build_ai_limits(
                            service_name, downloader_type, eligible_torrents, decisions
                        )
                        if ai_unlimit:
                            unlimit_count = self._apply_ai_unlimit(
                                service_name, downloader, ai_unlimit,
                                torrents=eligible_torrents,
                                downloader_type=downloader_type,
                                channels=self._normalize_channels(channel),
                            )
                            summary_lines.append(f"{service_name}：AI 复核解限 {unlimit_count} 个种子")
                        summary_lines.append(f"{service_name}：AI 智能限速生效（本轮决策 {len(decisions)} 个种子）")
                matched = self._collect_matched_torrents(
                    torrents=eligible_torrents,
                    service_name=service_name,
                    downloader_type=downloader_type,
                    threshold=threshold,
                    selected=selected,
                    site_cache=site_cache,
                    threshold_cache=threshold_cache,
                    ai_mode=ai_mode,
                    ai_limits=ai_limits,
                )
                # 对达标种子应用限速并统计结果
                new_limited, already, failed, canceled = self._apply_limits(
                    service_name=service_name,
                    downloader=downloader,
                    downloader_type=downloader_type,
                    matched=matched,
                    limit=effective_limit,
                    threshold=threshold,
                    channel=channel,
                    site_cache=site_cache,
                    threshold_cache=threshold_cache,
                    ai_limits=ai_limits if ai_mode else None,
                )
                # 彩蛋：启用 AI 智能限速后，登记种子状态机（待评估/限速中/恢复中/忽略）
                # 并在运行日志输出各状态数量；未启用 AI 时保持原有逻辑
                if self._ai_enabled:
                    self._refresh_seed_states(service_name, eligible_torrents, downloader_type, site_cache=site_cache)
                    # 活跃度快照在 AI 评估与状态计算之后更新，保存本轮累计上传量，
                    # 供下一轮 _is_torrent_active 计算窗口增量（顺序不可颠倒，
                    # 否则本轮活跃判断比较的是「刚刷新」的当前值、恒为不活跃）
                    self._refresh_activity_snapshots(service_name, eligible_torrents, downloader_type)
                    if self._seed_states.get(service_name):
                        state_counts = {}
                        for state in self._seed_states.get(service_name, {}).values():
                            state_counts[state] = state_counts.get(state, 0) + 1
                        summary_lines.append(
                            f"{service_name}：种子状态 待评估 {state_counts.get('pending', 0)} / "
                            f"限速中 {state_counts.get('limited', 0)} / 恢复中 {state_counts.get('recovering', 0)} / "
                            f"AI 不限速 {state_counts.get('no_limit', 0)} / 忽略 {state_counts.get('idle', 0)}"
                        )
                # 兜底重试「已取消监控但恢复失败」的种子：下载器短暂离线导致的
                # 恢复失败，在下载器恢复后由每轮检测顺带重试，无需等待停用/卸载
                self._retry_stuck_restores(service_name, downloader)
                if effective_limit < limit:
                    summary_lines.append(
                        f"{service_name}：插件上传限速 {self._format_limit(limit)} 高于 qB 全局上传限速，实际采用 {self._format_limit(effective_limit)}"
                    )
                summary_lines.append(
                    f"{service_name}：达标 {len(matched)} 个，新限速 {new_limited} 个，已满足 {already} 个，失败 {failed} 个，取消监控 {canceled + timeout_canceled} 个，未入库忽略 {len(torrents) - len(eligible_torrents)} 个"
                )
            except Exception as err:
                failed_names.append(service_name)
                logger.error(f"{self.LOG_TAG}处理下载器 [{service_name}] 失败：{err}")

        # 对所有存在待恢复记录的服务兜底重试（含已从插件选择中移除的下载器）：
        # 下载器离线期间被移除选择导致的恢复失败，重连后无需重新选择也能恢复
        self._retry_all_stuck_restores()
        if failed_names:
            summary_lines.append(f"处理失败：{'、'.join(failed_names)}")
        self._last_result = "\n".join(summary_lines) if summary_lines else "未检测到符合条件的种子。"
        # 每次检测周期结束后立即持久化待恢复/已取消记录，避免后续保存配置时
        # 用数据存储中的旧快照覆盖本次会话的限速归属与取消状态
        self._save_set_map(self._RESTORE_DATA_KEY, self._restore_hashes)
        self._save_set_map(self._CANCELED_DATA_KEY, self._canceled_hashes)
        return not failed_names

    def _collect_matched_torrents(
        self,
        torrents: List[Any],
        service_name: str,
        downloader_type: str,
        threshold: float,
        selected: Optional[Set[str]],
        site_cache: Dict[str, str],
        threshold_cache: Dict[str, float],
        ai_mode: bool = False,
        ai_limits: Optional[Dict[str, float]] = None,
    ) -> List[Any]:
        """
        从种子列表中筛选出达到分享率阈值且（可选）属于勾选站点的种子。

        启用站点筛选或配置了站点单独阈值时，一次性批量查询下载历史
        （hash -> 站点），优先使用 MoviePilot 记录的权威站点信息。
        每个达标种子实际使用的阈值写入 threshold_cache，供日志准确显示。

        AI 智能限速模式（ai_mode=True）：limit 决策按 AI 限速值限速；
        no_limit 决策尊重不限速；无决策（限频期内新活跃、尚未评估）回退阈值规则兜底。
        """
        # 站点筛选或站点单独阈值至少启用一项时，才需要识别种子所属站点
        need_site = bool(selected or self._site_share_ratios)
        history_sites: Dict[str, str] = {}
        if need_site:
            hashes = [self._torrent_hash(t, downloader_type) for t in torrents]
            history_sites = self._load_history_sites(hashes)

        matched = []
        for torrent in torrents:
            torrent_hash = self._torrent_hash(torrent, downloader_type)
            if not torrent_hash:
                continue

            site = ""
            if need_site:
                site = self._resolve_site(torrent, torrent_hash, downloader_type, history_sites, site_cache)
            # 站点筛选：无法识别或不属于勾选列表时跳过
            if selected and (not site or site.lower() not in selected):
                continue

            # AI 智能限速模式：limit 决策限速、no_limit 尊重不限速、
            # 已限速种子未要求调整时维持现状、无决策回退阈值规则兜底，避免「漏管」
            if ai_mode:
                ai_value = (ai_limits or {}).get(torrent_hash)
                if ai_value is not None:
                    matched.append(torrent)
                    continue
                ai_decision = self._ai_decisions.get(service_name, {}).get(torrent_hash)
                if ai_decision and ai_decision.get("action") == "no_limit":
                    continue
                if torrent_hash in self._limited_hashes.get(service_name, set()):
                    # 已限速种子：AI 未要求调整（防抖维持现状/本轮未评估），跳过不重新按阈值限速
                    continue
                # 无决策：继续走下方阈值规则

            # 已识别且配置了单独阈值的站点使用单独值，否则回退到全局阈值
            torrent_threshold = self._threshold_for_site(site, threshold)
            if self._torrent_ratio(torrent, downloader_type) < torrent_threshold:
                continue
            threshold_cache[torrent_hash] = torrent_threshold
            matched.append(torrent)
        return matched

    def _refresh_torrent_state(
        self,
        service_name: str,
        torrents: List[Any],
        downloader_type: str,
        limit: float,
        now: float,
        transferred_hashes: Optional[Set[str]] = None,
    ):
        """
        每个检测周期刷新种子监控状态：
        - 为已下载完成且已入库成功的种子维护「上传速度持续低于限速值」的连续低速计时：
          速度低于限速值时开始/延续计时，速度回升到限速值即清零重新计时
          （仅「下载完成后监控超时」启用且限速值大于 0 时需要）；
        - 清理已不在下载器中的种子状态，避免记录无限增长。
        """
        current_hashes = set()
        for torrent in torrents:
            torrent_hash = self._torrent_hash(torrent, downloader_type)
            if not torrent_hash:
                continue
            current_hashes.add(torrent_hash)
            if (
                self._complete_timeout > 0
                and limit > 0
                and self._torrent_completed(torrent, downloader_type)
                and (transferred_hashes is None or torrent_hash in transferred_hashes)
            ):
                slow_map = self._complete_slow_since.setdefault(service_name, {})
                if self._torrent_upload_speed(torrent, downloader_type) < limit * 1024:
                    if torrent_hash not in slow_map:
                        slow_map[torrent_hash] = now
                else:
                    # 速度达到限速值：清零连续低速计时
                    slow_map.pop(torrent_hash, None)
        # 清理已不在下载器中的种子状态，集合与字典按各自语义删除
        for state in (
            self._limited_hashes,
            self._restore_hashes,
            self._canceled_hashes,
            self._limited_times,
            self._slow_since,
            self._complete_slow_since,
            self._uploaded_snapshots,
            self._seed_states,
            self._ai_decisions,
            self._seed_page_snapshot,
        ):
            mapping = state.get(service_name)
            if not mapping:
                continue
            for key in [key for key in mapping if key not in current_hashes]:
                if isinstance(mapping, set):
                    mapping.discard(key)
                else:
                    mapping.pop(key, None)

    def _apply_limits(
        self,
        service_name: str,
        downloader: Any,
        downloader_type: str,
        matched: List[Any],
        limit: float,
        threshold: float,
        channel: Any,
        site_cache: Dict[str, str],
        threshold_cache: Dict[str, float],
        ai_limits: Optional[Dict[str, float]] = None,
    ) -> Tuple[int, int, int, int]:
        """
        对达标种子逐个设置上传限速，返回 (新增限速数, 已满足数, 失败数, 取消监控数)。

        监控超时取消机制（对应配置项为 0 时关闭）：
        - 下载完成后超时：种子下载完成后，若在设定秒数内上传速度始终达不到限速值，
          取消监控并立即恢复该种子不限速；
        - 限速后超时：种子被限速后，持续限速或上传速度低于限速值 80% 达到设定秒数时，
          取消监控并立即恢复该种子不限速。

        AI 智能限速（ai_limits 非空）：每个种子使用其独立的目标限速值
        （不超过下载器全局有效限速），无 AI 决策的种子使用配置限速值。
        """
        new_limited = already = failed = canceled = 0
        limited_hashes = self._limited_hashes.setdefault(service_name, set())
        canceled_hashes = self._canceled_hashes.setdefault(service_name, set())
        # 限速值大于 0 时才需要发通知
        channels = self._normalize_channels(channel) if limit > 0 else []

        for torrent in matched:
            torrent_hash = self._torrent_hash(torrent, downloader_type)
            torrent_name = self._torrent_name(torrent, downloader_type) or torrent_hash
            torrent_threshold = threshold_cache.get(torrent_hash, threshold)
            # AI 智能限速：每种子独立目标限速值，不超过下载器全局有效限速；
            # 无 AI 决策时使用配置限速值
            torrent_limit = min(ai_limits.get(torrent_hash, limit), limit) if ai_limits else limit
            # 已取消监控的种子：跳过，不再设置限速
            if torrent_hash in canceled_hashes:
                continue

            now = time.time()
            restore_hashes = self._restore_hashes.setdefault(service_name, set())
            # 是否已由本插件认领（本次会话限速过，或跨会话仍有待恢复记录）
            owned = torrent_hash in limited_hashes or torrent_hash in restore_hashes

            if owned:
                if self._limit_timeout > 0 and torrent_limit > 0:
                    # 已认领种子（含跨会话恢复出的）重新建立限速起始时间，
                    # 保证「限速后超时」计时可用
                    self._limited_times.setdefault(service_name, {}).setdefault(torrent_hash, now)
                # 已认领种子：按「限速后超时」规则判断是否取消监控
                if self._limit_timeout > 0 and torrent_limit > 0 and self._check_limit_timeout(
                    service_name, torrent, downloader_type, torrent_hash, torrent_limit, now
                ):
                    self._cancel_monitoring(
                        service_name, torrent_hash, torrent_name,
                        reason="限速后超时", downloader=downloader,
                        site=site_cache.get(torrent_hash, "") or self._torrent_site(torrent, downloader_type),
                        channels=channels,
                    )
                    canceled += 1
                    continue
                # 当前限速已是目标值：计入「已满足」，避免重复调用下载器接口
                if self._torrent_current_limit(torrent, downloader_type, torrent_limit, service_name, torrent_hash):
                    limited_hashes.add(torrent_hash)
                    already += 1
                    continue
            else:
                # 未认领种子：当前限速已等于目标值且并非本插件所设，不认领所有权，
                # 避免停用/卸载时误将外部设置的限速恢复为不限速
                # （「下载完成后监控超时」已在每轮检测前对所有已完成未认领种子统一处理）
                if self._torrent_current_limit(torrent, downloader_type, torrent_limit, service_name, torrent_hash):
                    already += 1
                    continue

            try:
                if not downloader.change_torrent(hash_string=torrent_hash, upload_limit=torrent_limit):
                    failed += 1
                    continue
                limited_hashes.add(torrent_hash)
                # 登记到待恢复集合：即使后续取消监控，停用/卸载时也能恢复不限速
                restore_hashes.add(torrent_hash)
                # 记录本次限速时间，用于「限速后超时」计时
                self._limited_times.setdefault(service_name, {})[torrent_hash] = now
                new_limited += 1
                if ai_limits and torrent_hash in ai_limits:
                    logger.info(
                        f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] AI 智能限速 {self._format_limit(torrent_limit)}"
                    )
                else:
                    logger.info(
                        f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 分享率达到 {torrent_threshold:g}，"
                        f"已限速 {self._format_limit(torrent_limit)}"
                    )
                # 通知：AI 决策限速时发送「AI 接管」；常规阈值限速仅首次新限速逐条通知，
                # 已认领种子被外部改回后重新应用不再重复通知
                if channels and (ai_limits and torrent_hash in ai_limits or not owned):
                    site = site_cache.get(torrent_hash, "") or self._torrent_site(torrent, downloader_type)
                    if ai_limits and torrent_hash in ai_limits:
                        self._send_event_notify("ai_takeover", site, torrent_name, channels,
                                                limit=torrent_limit, reason="AI 决策限速")
                    else:
                        self._send_limit_notify(site=site, torrent_name=torrent_name, limit=torrent_limit, channels=channels)
            except Exception as err:
                failed += 1
                logger.error(f"{self.LOG_TAG}[{service_name}] 设置种子 [{torrent_name}] 上传限速失败：{err}")
        return new_limited, already, failed, canceled

    # ---------------------------------------------------------------- AI 智能限速

    def _load_site_ratios(self) -> Dict[str, float]:
        """
        读取各站点账号分享率（MoviePilot 站点用户数据最新快照），返回 {站点域名: 分享率}。

        站点未配置、未抓到用户数据或抓取失败时返回空字典，AI 决策退化为仅参考种子自身数据。
        """
        latest: Dict[str, Tuple[str, float]] = {}
        try:
            from app.db import SessionFactory
            from app.db.models.siteuserdata import SiteUserData
            db = SessionFactory()
            try:
                rows = db.query(SiteUserData).all() or []
            finally:
                db.close()
            for row in rows:
                if getattr(row, "err_msg", None):
                    continue
                domain = str(getattr(row, "domain", "") or "").strip().lower()
                if not domain:
                    continue
                try:
                    ratio = float(getattr(row, "ratio", 0) or 0)
                except (TypeError, ValueError):
                    continue
                stamp = f"{getattr(row, 'updated_day', '') or ''} {getattr(row, 'updated_time', '') or ''}"
                if ratio > 0 and (domain not in latest or stamp > latest[domain][0]):
                    latest[domain] = (stamp, ratio)
        except Exception as err:
            logger.warning(f"{self.LOG_TAG}读取站点账号分享率失败：{err}")
        return {domain: info[1] for domain, info in latest.items()}

    def _refresh_activity_snapshot(self, service_name: str, torrent: Any, downloader_type: str, torrent_hash: str):
        """
        更新种子累计上传量快照（活跃度窗口增量用）。

        快照丢失（插件重启后首轮）时仅写入当前值，窗口增量从次轮起生效。
        """
        uploaded = self._torrent_uploaded(torrent, downloader_type)
        self._uploaded_snapshots.setdefault(service_name, {})[torrent_hash] = uploaded

    def _refresh_activity_snapshots(self, service_name: str, torrents: List[Any], downloader_type: str):
        """
        批量更新已入库种子的活跃度快照（在本轮 AI 评估与状态计算之后调用）。

        快照保存的是「本轮」累计上传量，供下一轮 `_is_torrent_active` 与上一轮
        比较计算窗口增量；必须在活跃判断完成之后调用，否则当前值与快照相等，
        增量恒为 0、活跃判断失效。
        """
        for torrent in torrents:
            torrent_hash = self._torrent_hash(torrent, downloader_type)
            if torrent_hash:
                self._refresh_activity_snapshot(service_name, torrent, downloader_type, torrent_hash)

    def _is_torrent_active(self, service_name: str, torrent: Any, downloader_type: str, torrent_hash: str) -> bool:
        """
        判断种子是否活跃：窗口内有实际上传增量；无快照（首轮）时以当前上传速度为准。

        这是 AI 决策与状态机的基础信号：休眠种子（无增量）一律跳过，避免无意义干预。
        """
        prev = self._uploaded_snapshots.get(service_name, {}).get(torrent_hash)
        if prev is None:
            return self._torrent_upload_speed(torrent, downloader_type) > 0
        return self._torrent_uploaded(torrent, downloader_type) > prev

    def _window_upload_delta(self, service_name: str, torrent: Any, downloader_type: str, torrent_hash: str) -> float:
        """返回种子最近一轮窗口的上传增量（字节），负数按 0 处理。"""
        prev = self._uploaded_snapshots.get(service_name, {}).get(torrent_hash)
        if prev is None:
            return 0.0
        delta = self._torrent_uploaded(torrent, downloader_type) - prev
        return delta if delta > 0 else 0.0

    def _refresh_seed_states(self, service_name: str, eligible_torrents: List[Any], downloader_type: str,
                             site_cache: Optional[Dict[str, str]] = None):
        """
        推导并登记种子状态机（pending / limited / recovering / no_limit / idle），清理已移除种子。

        状态完全由现有机制推导：
        - 已取消监控 -> idle（忽略，插件不再干预）；
        - 已被本插件限速 -> limited（限速中）；
        - 有待恢复记录 -> recovering（恢复中，含恢复失败待重试）；
        - AI 判定不限速 -> no_limit（AI 不限速）；
        - 活跃 -> pending（待评估）；休眠 -> idle。

        同时维护种子状态页快照（名称/站点/状态/限速值/AI 决策原因），供 get_page 渲染。
        """
        states = self._seed_states.setdefault(service_name, {})
        snapshot = self._seed_page_snapshot.setdefault(service_name, {})
        decisions = self._ai_decisions.get(service_name, {})
        current = set()
        for torrent in eligible_torrents:
            torrent_hash = self._torrent_hash(torrent, downloader_type)
            if not torrent_hash:
                continue
            current.add(torrent_hash)
            if torrent_hash in self._canceled_hashes.get(service_name, set()):
                states[torrent_hash] = self._STATE_IDLE
            elif torrent_hash in self._limited_hashes.get(service_name, set()):
                states[torrent_hash] = self._STATE_LIMITED
            elif torrent_hash in self._restore_hashes.get(service_name, set()):
                states[torrent_hash] = self._STATE_RECOVERING
            elif self._ai_decisions.get(service_name, {}).get(torrent_hash, {}).get("action") == "no_limit":
                states[torrent_hash] = self._STATE_NO_LIMIT
            elif self._is_torrent_active(service_name, torrent, downloader_type, torrent_hash):
                states[torrent_hash] = self._STATE_PENDING
            else:
                states[torrent_hash] = self._STATE_IDLE
            # 页面快照：名称/站点/状态/AI 决策（限速值与原因）
            decision = decisions.get(torrent_hash) or {}
            snapshot[torrent_hash] = {
                "name": self._torrent_name(torrent, downloader_type) or torrent_hash,
                "site": (site_cache or {}).get(torrent_hash) or self._torrent_site(torrent, downloader_type),
                "state": states[torrent_hash],
                "limit_kb": int(decision.get("limit_kb") or 0),
                "reason": str(decision.get("reason") or ""),
            }
        # 清理已不在下载器中的种子：以状态与快照的并集为基准，
        # 覆盖「上一轮只进了快照未进状态」或反之的边界情况
        for torrent_hash in [h for h in set(states) | set(snapshot) if h not in current]:
            states.pop(torrent_hash, None)
            snapshot.pop(torrent_hash, None)

    @staticmethod
    def _run_async_compatible(value: Any) -> Any:
        """
        兼容 MoviePilot 新版 `LLMHelper.get_llm()` 的异步返回。

        同步上下文直接 asyncio.run；当前线程已有事件循环时开短线程执行。
        """
        if not inspect.isawaitable(value):
            return value
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)
        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}

        def _worker() -> None:
            try:
                result["value"] = asyncio.run(value)
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        if "exc" in error:
            raise error["exc"]
        return result.get("value")

    def _ai_invoke(self, prompt: str, timeout: int = 180) -> str:
        """
        调用 MoviePilot 系统设置中已配置的大模型（智能体），返回模型回复文本。

        复用系统级 LLM 配置（provider/model/api_key/base_url），插件不做任何
        API 密钥配置；调用失败或超时抛异常，由调用方回退常规阈值规则。
        带思考（reasoning）的模型可能较慢，默认超时放宽到 180 秒。
        """
        try:
            from app.agent.llm import LLMHelper
        except ImportError:
            from app.helper.llm import LLMHelper
        try:
            llm = self._run_async_compatible(LLMHelper.get_llm(streaming=False))
        except Exception as err:
            logger.warning(
                f"{self.LOG_TAG}获取大模型失败：{err}。"
                f"AI 智能限速不可用，请前往 MoviePilot「系统设置 - 大模型」完成配置后重新启用；"
                f"期间自动回退常规分享率阈值限速"
            )
            self._ai_config_missing = True
            self._ai_active = False
            raise
        if llm is None:
            logger.warning(
                f"{self.LOG_TAG}系统设置中未配置大模型，AI 智能限速不可用。"
                f"请前往 MoviePilot「系统设置 - 大模型」完成配置后重新启用；"
                f"期间自动回退常规分享率阈值限速"
            )
            self._ai_config_missing = True
            self._ai_active = False
            raise RuntimeError("系统设置未配置大模型")
        self._ai_config_missing = False
        response = llm.invoke(prompt, config={"configurable": {"timeout": timeout}})
        # 带思考（reasoning）的模型 content 可能为空或缺失，兜底为空串，
        # 解析失败时由调用方回退常规阈值规则，避免 extract_text_content 收到空值报错
        return LLMHelper.extract_text_content(getattr(response, "content", response)) or ""

    def _ai_background_check(self, seq: int):
        """
        保存配置（开启 AI 开关）后自动后台自检大模型连通性。

        用一个极小的探测提示词真实调用一次系统设置的大模型：能正常返回即视为
        AI 生效（置位 `_ai_active`，详情页立即可用）；未配置/调用失败则保持隐藏，
        本轮限速走常规阈值规则，全部结果写入插件日志供用户确认。
        seq 为自检序号：完成时若与当前序号不一致（已被更新的初始化取代）则丢弃。
        """
        try:
            logger.info(f"{self.LOG_TAG}AI 智能限速已开启，正在后台自检大模型连通性……")
            answer = self._ai_invoke("请只回复两个字：正常", timeout=60)
        except Exception as err:
            if seq != self._ai_check_seq:
                return
            if self._ai_config_missing:
                logger.warning(
                    f"{self.LOG_TAG}AI 自检失败：系统设置未配置大模型（{err}）。"
                    f"请前往 MoviePilot「系统设置 - 大模型」完成配置后重新保存插件配置；"
                    f"期间限速回退常规分享率阈值规则，种子状态页保持隐藏"
                )
            else:
                logger.warning(
                    f"{self.LOG_TAG}AI 自检失败：大模型调用异常（{err}）。"
                    f"请检查 MoviePilot「系统设置 - 大模型」配置与网络；"
                    f"期间限速回退常规分享率阈值规则，种子状态页保持隐藏"
                )
            return
        if seq != self._ai_check_seq:
            return
        if not answer.strip():
            logger.warning(
                f"{self.LOG_TAG}AI 自检失败：大模型返回内容为空。"
                f"请检查 MoviePilot「系统设置 - 大模型」配置；"
                f"期间限速回退常规分享率阈值规则，种子状态页保持隐藏"
            )
            return
        self._ai_active = True
        preview = answer.strip().replace("\n", " ")[:50]
        logger.info(
            f"{self.LOG_TAG}AI 自检成功：大模型连通正常（回复：{preview}），"
            f"AI 智能限速已生效，种子状态页已开启（点击插件卡片查看）"
        )

    @staticmethod
    def _build_ai_prompt(items: List[dict], site_lines: str, max_limit: int) -> str:
        """
        构造 AI 限速决策提示词。

        :param items: 种子信息列表（index/hash/site/ratio/uploaded/downloaded/speed/window_upload/current_limit）
        :param site_lines: 站点账号分享率文本（站点名=分享率，每行一个）
        :param max_limit: 限速上限 KB/s
        """
        seed_lines = "\n".join(
            f"[{it['index']}] 站点={it['site'] or '未知'} | 种子分享率={it['ratio']:.2f} | "
            f"累计上传={it['uploaded']} | 累计下载={it['downloaded']} | "
            f"当前上传速度={it['speed']} | 最近一轮上传增量={it['window_upload']} | "
            f"当前限速={it.get('current_limit', 0):g} KB/s（0=不限速）"
            for it in items
        )
        return (
            "你是 MoviePilot「QB上传限速」插件的 AI 限速决策助手。根据种子信息与站点账号分享率，"
            "决定每个种子的上传限速策略，帮助用户在保护站内上传指标的同时避免种子占用过多上行带宽。\n"
            "决策原则：\n"
            "1. 种子分享率（累计上传/累计下载）越高，说明该种子上传贡献已充足，越应限速；"
            "分享率低说明还在积累上传，应少限或不限；\n"
            "2. 站点账号分享率越高，说明该站上传指标越充足，该站种子可放心限速；"
            "站点分享率低（如低于 1.5）时该站种子应放宽，继续积攒上传量；\n"
            "3. 种子最近仍在上传（当前速度或窗口增量大于 0）才值得限速；\n"
            "4. 对已限速的种子（当前限速>0），可据其最新分享率/活跃度调整限速值或改为 no_limit 解除限速；"
            "仅当认为需要明显改变时才调整，避免无谓微调；\n"
            f"5. 限速值单位为 KB/s，必须为正整数，且不超过上限 {max_limit}；"
            "action 为 no_limit 时表示不限速，limit_kb 填 0；\n"
            "6. 严格只输出 JSON，不要输出任何其他文字，格式："
            "{{\"results\": [{{\"index\": 序号, \"action\": \"limit\" 或 \"no_limit\", "
            "\"limit_kb\": 数值, \"reason\": \"一句话原因\"}}]}}，输入的每个种子都必须给出结果。\n"
            f"站点账号分享率：{site_lines}\n"
            f"种子列表：\n{seed_lines}"
        )

    def _ai_evaluate(self, service_name: str, torrents: List[Any], downloader_type: str,
                     site_ratios: Dict[str, float], now: float) -> Dict[str, Dict[str, Any]]:
        """
        对活跃的种子（含已限速种子，用于复核加限/减限/解限）进行 AI 批量评估，
        返回本轮生效的决策 {种子Hash: 决策}。

        按 _ai_eval_interval 限频调用大模型：限频期内直接复用现有决策缓存；
        大模型调用失败/超时/输出解析失败时返回空字典（本轮回退常规阈值规则），
        已成功的决策仍保留在缓存中供后续轮次使用。休眠种子不参与评估。
        """
        decisions = self._ai_decisions.setdefault(service_name, {})
        canceled = self._canceled_hashes.get(service_name, set())
        items: List[dict] = []
        index_map: Dict[int, str] = {}
        for torrent in torrents:
            torrent_hash = self._torrent_hash(torrent, downloader_type)
            if not torrent_hash or torrent_hash in canceled:
                continue
            if not self._is_torrent_active(service_name, torrent, downloader_type, torrent_hash):
                continue
            # 账号分享率门槛：门槛>0 时，站点账号分享率未达标（或查不到）的种子不参与 AI 决策，
            # 回退常规阈值规则；高分享率账号（很安全）才交给 AI 限速减上行流量，规避家宽被运营商限速
            if self._ai_site_ratio_threshold > 0:
                site_ratio = self._torrent_site_ratio(torrent, downloader_type, site_ratios)
                if site_ratio is None or site_ratio < self._ai_site_ratio_threshold:
                    continue
            index = len(items)
            items.append({
                "index": index,
                "hash": torrent_hash,
                "site": self._torrent_site(torrent, downloader_type),
                "ratio": self._torrent_ratio(torrent, downloader_type),
                "uploaded": self._format_bytes(self._torrent_uploaded(torrent, downloader_type)),
                "downloaded": self._format_bytes(self._torrent_downloaded(torrent, downloader_type)),
                "speed": f"{self._torrent_upload_speed(torrent, downloader_type) / 1024:.1f} KB/s",
                "window_upload": self._format_bytes(self._window_upload_delta(service_name, torrent, downloader_type, torrent_hash)),
                "current_limit": self._torrent_current_limit_kb(torrent, downloader_type),
            })
            index_map[index] = torrent_hash
        if not items:
            return {}
        # 系统设置未配置大模型：降频重试探测（补配置后无需重新保存插件即可自动恢复），
        # 重试间隔内直接回退常规阈值规则，避免每轮刷错误日志
        if self._ai_config_missing:
            if now < self._ai_config_retry_at:
                return {}
            self._ai_config_retry_at = now + self._ai_eval_interval
            try:
                self._ai_invoke("请只回复两个字：正常", timeout=60)
                # 探测成功：_ai_invoke 内部已置 _ai_config_missing=False，继续正常评估
            except Exception:
                return {}
        # 限频：距上次大模型调用不足间隔时不调用，直接返回缓存中仍有效的决策；
        # 丢弃已过期（超过一个评估间隔未刷新）的旧决策，避免种子长时间休眠后
        # 重新活跃时命中陈旧结论（此类种子会回退阈值规则兜底，等下次评估刷新）
        if now - self._last_ai_eval_at < self._ai_eval_interval:
            fresh: Dict[str, dict] = {}
            for torrent_hash, decision in decisions.items():
                if torrent_hash not in index_map.values():
                    continue
                try:
                    ts = float(decision.get("ts") or 0)
                except (TypeError, ValueError):
                    ts = 0.0
                if now - ts >= self._ai_eval_interval:
                    continue
                fresh[torrent_hash] = decision
            return fresh
        max_limit = self._ai_max_limit if self._ai_max_limit > 0 else self._upload_limit
        if max_limit <= 0:
            return {}
        prompt = self._build_ai_prompt(items, self._build_site_ratio_lines(site_ratios), max_limit)
        try:
            text = self._ai_invoke(prompt)
        except Exception as err:
            logger.warning(f"{self.LOG_TAG}AI 智能限速调用大模型失败：{err}，本轮回退常规阈值限速")
            return {}
        parsed = self._parse_ai_result(text, index_map, max_limit)
        if not parsed:
            logger.warning(f"{self.LOG_TAG}AI 智能限速输出解析失败，本轮回退常规阈值限速")
            return {}
        self._last_ai_eval_at = now
        self._ai_active = True
        for torrent_hash, decision in parsed.items():
            decision["ts"] = now
            decisions[torrent_hash] = decision
        return parsed

    def _build_ai_limits(
        self,
        service_name: str,
        downloader_type: str,
        torrents: List[Any],
        decisions: Dict[str, dict],
    ) -> Tuple[Dict[str, float], Set[str]]:
        """
        根据 AI 决策构建「限速映射」与「解限集合」。

        - limit 决策：写入限速映射（KB/s）；对已限速种子做防抖——新值与当前值
          差异 < 20% 时维持现状，避免每轮无谓微调；
        - no_limit 决策：若该种子当前已限速，加入解限集合（由 _apply_ai_unlimit 恢复不限速）。
        """
        torrent_map = {self._torrent_hash(t, downloader_type): t for t in torrents}
        limited = self._limited_hashes.get(service_name, set())
        ai_limits: Dict[str, float] = {}
        unlimit_hashes: Set[str] = set()
        for torrent_hash, decision in decisions.items():
            action = decision.get("action")
            if action == "limit":
                try:
                    new_kb = float(decision.get("limit_kb") or 0)
                except (TypeError, ValueError):
                    continue
                if new_kb <= 0:
                    continue
                if torrent_hash in limited:
                    current_kb = self._torrent_current_limit_kb(torrent_map.get(torrent_hash), downloader_type)
                    if current_kb > 0 and abs(new_kb - current_kb) <= current_kb * 0.2:
                        continue  # 差异 < 20%，维持现状
                ai_limits[torrent_hash] = new_kb
            elif action == "no_limit" and torrent_hash in limited:
                unlimit_hashes.add(torrent_hash)
        return ai_limits, unlimit_hashes

    def _apply_ai_unlimit(
        self,
        service_name: str,
        downloader: Any,
        unlimit_hashes: Set[str],
        torrents: Optional[List[Any]] = None,
        downloader_type: str = "qbittorrent",
        channels: Optional[List[str]] = None,
    ) -> int:
        """
        执行 AI 解限：将已限速种子恢复为不限速，并移出限速/待恢复记录。

        与「取消监控」不同：解限不移入 canceled_hashes，种子后续仍可被 AI 重新评估并限速。
        返回实际解限数量。
        """
        limited = self._limited_hashes.get(service_name, set())
        restore = self._restore_hashes.get(service_name, set())
        torrent_map = {self._torrent_hash(t, downloader_type): t for t in (torrents or [])}
        count = 0
        for torrent_hash in unlimit_hashes:
            if torrent_hash not in limited:
                continue
            try:
                if not downloader.change_torrent(hash_string=torrent_hash, upload_limit=0):
                    logger.warning(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_hash}] AI 解限失败：下载器返回失败")
                    continue
            except Exception as err:
                logger.error(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_hash}] AI 解限失败：{err}")
                continue
            limited.discard(torrent_hash)
            restore.discard(torrent_hash)
            self._limited_times.get(service_name, {}).pop(torrent_hash, None)
            self._slow_since.get(service_name, {}).pop(torrent_hash, None)
            torrent = torrent_map.get(torrent_hash)
            if channels and torrent is not None:
                site = self._torrent_site(torrent, downloader_type)
                name = self._torrent_name(torrent, downloader_type) or torrent_hash
                self._send_event_notify("ai_release", site, name, channels, reason="AI 决策不限速")
            count += 1
            logger.info(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_hash}] AI 决策解限，已恢复不限速")
        return count

    def _build_site_ratio_lines(self, site_ratios: Dict[str, float]) -> str:
        """将站点账号分享率（域名 -> 分享率）转换为站点名=分享率文本，供 AI 参考。"""
        lines = []
        for domain, ratio in site_ratios.items():
            name = self._site_domains.get(domain)
            lines.append(f"{name or domain}={ratio:.2f}")
        return "；".join(lines) if lines else "无（未抓到站点账号分享率数据）"

    def _parse_ai_result(self, text: str, index_map: Dict[int, str], max_limit: int) -> Dict[str, dict]:
        """
        解析 AI 返回的 JSON（容忍代码块包裹与前后杂文），校验后返回
        {种子Hash: {action, limit_kb, reason}}；任何异常返回空字典。
        """
        if not text:
            return {}
        cleaned = str(text).strip()
        # 去掉代码块包裹
        for fence in ("```json", "```"):
            if fence in cleaned:
                cleaned = cleaned.replace(fence, "").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(cleaned[start:end + 1])
        except (TypeError, ValueError):
            return {}
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return {}
        parsed: Dict[str, dict] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            torrent_hash = index_map.get(index)
            if not torrent_hash:
                continue
            action = str(item.get("action") or "").strip().lower()
            if action not in ("limit", "no_limit"):
                continue
            limit_kb = 0
            if action == "limit":
                try:
                    limit_kb = int(float(item.get("limit_kb") or 0))
                except (TypeError, ValueError):
                    continue
                if limit_kb < 1:
                    continue
                if max_limit > 0:
                    limit_kb = min(limit_kb, max_limit)
            parsed[torrent_hash] = {
                "action": action,
                "limit_kb": limit_kb,
                "reason": str(item.get("reason") or "")[:200],
            }
        return parsed

    @staticmethod
    def _format_bytes(value: float) -> str:
        """格式化字节数为可读字符串。"""
        try:
            value = float(value or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while value >= 1024 and idx < len(units) - 1:
            value /= 1024
            idx += 1
        return f"{value:.2f} {units[idx]}"

    # ---------------------------------------------------------------- 站点识别
    def _load_site_domains(self) -> Dict[str, str]:
        """
        构建 站点域名(小写) -> 站点名称 映射，用于识别种子所属站点。
        """
        domains = {}
        try:
            from app.helper.sites import SitesHelper
            for site in SitesHelper().get_indexers() or []:
                if not site.get("is_active"):
                    continue
                name = str(site.get("name") or "").strip()
                if not name:
                    continue
                domain = str(site.get("domain") or "").strip().lower()
                if domain:
                    domains[domain] = name
                url = str(site.get("url") or "").strip()
                if url:
                    url_domain = self._normalize_domain(url)
                    if url_domain:
                        domains[url_domain] = name
        except Exception as err:
            logger.warning(f"{self.LOG_TAG}读取站点配置失败：{err}")
        return domains

    @staticmethod
    def _load_history_sites(hashes: List[str]) -> Dict[str, str]:
        """
        批量查询下载历史，返回 {种子Hash: 站点名称}，作为站点识别的权威依据。

        MoviePilot 在添加下载时会记录种子所属站点（torrent_site），
        优先使用该记录比 tracker/标签猜测更准确。
        """
        # 去重且过滤空值，减少一次数据库查询的行数
        hashes = [h for h in dict.fromkeys(hashes) if h]
        if not hashes:
            return {}
        try:
            from app.db.downloadhistory_oper import DownloadHistoryOper
            histories = DownloadHistoryOper().get_by_hashes(hashes)
            return {
                history.download_hash: (history.torrent_site or "").strip()
                for history in histories.values()
                if history and (history.torrent_site or "").strip()
            }
        except Exception as err:
            logger.warning(f"{QbUploadLimiter.LOG_TAG}查询下载历史站点失败：{err}")
            return {}

    @staticmethod
    def _load_transferred_hashes(hashes: List[str]) -> Set[str]:
        """
        批量查询已「整理入库成功」的种子 Hash 集合。

        MoviePilot 在下载完成并将媒体转移刮削进媒体库时会写入整理记录
        （TransferHistory，status=True），据此判断种子是否已完成入库。
        种子入库成功前对插件完全不可见（不监控、不限速）。
        """
        # 去重且过滤空值，减少一次数据库查询的行数
        hashes = [h for h in dict.fromkeys(hashes) if h]
        if not hashes:
            return set()
        try:
            from app.db import SessionFactory
            from app.db.models.transferhistory import TransferHistory
            db = SessionFactory()
            try:
                rows = (
                    db.query(TransferHistory)
                    .filter(
                        TransferHistory.download_hash.in_(hashes),
                        TransferHistory.status == True,
                    )
                    .all()
                )
            finally:
                db.close()
            return {row.download_hash for row in rows if row and row.download_hash}
        except Exception as err:
            logger.warning(f"{QbUploadLimiter.LOG_TAG}查询整理入库记录失败：{err}")
            return set()

    def _resolve_site(
        self,
        torrent: Any,
        torrent_hash: str,
        downloader_type: str,
        history_sites: Dict[str, str],
        site_cache: Dict[str, str],
    ) -> str:
        """
        识别种子所属站点（带缓存）。

        优先级：下载历史记录 -> tracker 域名 -> 标签 -> 分类。
        同一轮检测中每个种子只识别一次，结果写入 site_cache 复用。
        """
        if torrent_hash in site_cache:
            return site_cache[torrent_hash]
        site = history_sites.get(torrent_hash) or self._torrent_site(torrent, downloader_type)
        site_cache[torrent_hash] = site or ""
        return site_cache[torrent_hash]

    def _torrent_site(self, torrent: Any, downloader_type: str) -> str:
        """
        识别种子所属站点：优先通过 tracker 域名匹配，其次匹配标签/分类中的站点名。
        """
        for url in self._torrent_tracker_urls(torrent, downloader_type):
            domain = self._normalize_domain(url)
            if domain:
                hit = self._lookup_site_by_domain(domain)
                if hit:
                    return hit
        for tag in self._torrent_tags(torrent, downloader_type):
            hit = self._site_names.get(str(tag).strip().lower())
            if hit:
                return hit
        category = self._torrent_category(torrent, downloader_type)
        if category:
            hit = self._site_names.get(str(category).strip().lower())
            if hit:
                return hit
        return ""

    def _lookup_site_by_domain(self, host: str) -> str:
        """
        按域名（含子域名逐级回退）查找站点名称。

        例如 tracker.hdchina.org 会依次尝试 hdchina.org、org。
        """
        host = (host or "").strip().lower()
        if not host:
            return ""
        if host.startswith("www."):
            host = host[4:]
        if host in self._site_domains:
            return self._site_domains[host]
        labels = host.split(".")
        for i in range(1, len(labels)):
            candidate = ".".join(labels[i:])
            if candidate in self._site_domains:
                return self._site_domains[candidate]
        return ""

    def _torrent_site_ratio(self, torrent: Any, downloader_type: str, site_ratios: Dict[str, float]) -> Optional[float]:
        """
        返回种子所属站点的「账号分享率」（MoviePilot 站点用户数据）。

        按 tracker 域名（含子域名逐级回退）匹配 site_ratios；无法识别站点或
        未抓到该站账号分享率数据时返回 None。
        """
        for url in self._torrent_tracker_urls(torrent, downloader_type):
            host = self._normalize_domain(url)
            if not host:
                continue
            if host in site_ratios:
                return site_ratios[host]
            labels = host.split(".")
            for i in range(1, len(labels)):
                candidate = ".".join(labels[i:])
                if candidate in site_ratios:
                    return site_ratios[candidate]
        return None

    @staticmethod
    def _normalize_domain(url: str) -> str:
        """提取 URL 的域名部分（去除协议、端口与路径），统一转为小写。"""
        try:
            host = (urlparse(str(url or "")).hostname or "").strip().lower()
        except Exception:
            return ""
        if host.startswith("www."):
            host = host[4:]
        return host

    @staticmethod
    def _torrent_tracker_urls(torrent: Any, downloader_type: str) -> List[str]:
        """获取种子 tracker 地址列表。"""
        urls = []
        if downloader_type == "qbittorrent":
            if isinstance(torrent, dict):
                tracker = torrent.get("tracker") or ""
                if tracker:
                    urls.append(str(tracker))
        else:
            tracker_list = str(getattr(torrent, "trackerList", "") or "").strip()
            if tracker_list:
                urls.extend(url.strip() for url in tracker_list.splitlines() if url.strip())
            trackers = getattr(torrent, "trackers", None) or []
            for tracker in trackers:
                if isinstance(tracker, dict):
                    announce = tracker.get("announce") or ""
                else:
                    announce = getattr(tracker, "announce", "") or ""
                if announce:
                    urls.append(str(announce))
        return urls

    @staticmethod
    def _torrent_tags(torrent: Any, downloader_type: str) -> List[str]:
        """获取种子标签列表。"""
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return []
            tags = torrent.get("tags") or ""
            return [str(tag).strip() for tag in str(tags).split(",") if str(tag).strip()]
        labels = getattr(torrent, "labels", None) or []
        return [str(label).strip() for label in labels if str(label).strip()]

    @staticmethod
    def _torrent_category(torrent: Any, downloader_type: str) -> str:
        """获取种子分类（仅 qBittorrent）。"""
        if downloader_type == "qbittorrent" and isinstance(torrent, dict):
            return str(torrent.get("category") or "").strip()
        return ""

    # ---------------------------------------------------------------- 种子属性

    @staticmethod
    def _torrent_hash(torrent: Any, downloader_type: str) -> str:
        """获取种子哈希。"""
        if downloader_type == "qbittorrent":
            return str(torrent.get("hash") or "").strip() if isinstance(torrent, dict) else ""
        return str(getattr(torrent, "hashString", "") or getattr(torrent, "id", "") or "").strip()

    @staticmethod
    def _torrent_name(torrent: Any, downloader_type: str) -> str:
        """获取种子名称。"""
        if downloader_type == "qbittorrent":
            return str(torrent.get("name") or "") if isinstance(torrent, dict) else ""
        return str(getattr(torrent, "name", "") or "")

    @staticmethod
    def _torrent_ratio(torrent: Any, downloader_type: str) -> float:
        """
        获取种子分享率（上传量 / 下载量）。

        优先使用下载器返回的 ratio 字段，缺失时按 上传量 / 下载量 计算。
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return 0.0
            ratio = torrent.get("ratio")
            if ratio is None:
                uploaded = torrent.get("uploaded") or 0
                downloaded = torrent.get("downloaded") or 0
                ratio = uploaded / downloaded if downloaded else 0
        else:
            ratio = getattr(torrent, "uploadRatio", None)
            if ratio is None:
                ratio = getattr(torrent, "ratio", None)
            if ratio is None:
                uploaded = getattr(torrent, "uploadedEver", 0) or 0
                downloaded = getattr(torrent, "downloadedEver", 0) or 0
                ratio = uploaded / downloaded if downloaded else 0
        try:
            return float(ratio or 0)
        except (TypeError, ValueError):
            return 0.0

    def _torrent_current_limit(
        self, torrent: Any, downloader_type: str, limit_kb: float, service_name: str, torrent_hash: str
    ) -> bool:
        """
        判断种子当前上传限速是否已是目标值，避免重复调用下载器接口。

        qBittorrent 读取 up_limit（字节/秒）直接比较；Transmission 的核心下载器
        get_torrents 未请求单种限速字段（uploadLimited/uploadLimit），无法可靠读取
        实际单种限速，字段缺失时退化为插件自身「已限速」记录（_limited_times）判断：
        本插件设置过限速的种子视为仍处于目标限速，避免每轮重复设置限速、重复发送
        通知，并保证「限速后超时」的持续限速计时不会被误重置。

        :param limit_kb: 目标限速 KB/s，0 表示不限速
        :param service_name: 下载器名称，Transmission 回退到插件记录时用于定位种子
        :param torrent_hash: 种子 Hash，Transmission 回退到插件记录时用于定位种子
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return False
            try:
                current_limit = int(torrent.get("up_limit") or 0)
                target_limit = int(float(limit_kb) * 1024)
            except (TypeError, ValueError):
                return False
            return current_limit == target_limit
        # Transmission：uploadLimit 单位为 KB/s；字段缺失时回退到插件记录判断
        upload_limited = bool(getattr(torrent, "uploadLimited", False))
        upload_limit = int(getattr(torrent, "uploadLimit", 0) or 0)
        if upload_limited or upload_limit:
            if limit_kb == 0:
                # 目标是不限速：只要当前没有开启限速即视为已满足
                return not upload_limited
            return upload_limited and upload_limit == int(float(limit_kb))
        return bool(self._limited_times.get(service_name, {}).get(torrent_hash))

    @staticmethod
    def _torrent_current_limit_kb(torrent: Any, downloader_type: str) -> float:
        """
        读取种子当前上传限速值（KB/s），0 表示不限速；读取失败返回 0。

        qBittorrent 字段 up_limit 为字节/秒（除以 1024 得 KB/s）；
        Transmission 字段 uploadLimit 为 KB/s（uploadLimited=False 表示不限速）。
        """
        if torrent is None:
            return 0.0
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return 0.0
            try:
                return float(torrent.get("up_limit") or 0) / 1024
            except (TypeError, ValueError):
                return 0.0
        # Transmission
        try:
            if not getattr(torrent, "uploadLimited", False):
                return 0.0
            return float(getattr(torrent, "uploadLimit", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _torrent_upload_speed(torrent: Any, downloader_type: str) -> float:
        """
        获取种子当前上传速度（字节/秒）。

        qBittorrent 字段 upspeed、Transmission 字段 rateUpload 均为字节/秒。
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return 0.0
            try:
                return float(torrent.get("upspeed") or 0)
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(getattr(torrent, "rateUpload", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _torrent_uploaded(torrent: Any, downloader_type: str) -> float:
        """
        获取种子累计上传量（字节），用于活跃度窗口增量判断。

        qBittorrent 字段 uploaded、Transmission 字段 uploadedEver 均为字节。
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return 0.0
            try:
                return float(torrent.get("uploaded") or 0)
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(getattr(torrent, "uploadedEver", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _torrent_downloaded(torrent: Any, downloader_type: str) -> float:
        """
        获取种子累计下载量（字节），用于 AI 决策上下文展示。

        qBittorrent 字段 downloaded、Transmission 字段 downloadedEver 均为字节。
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return 0.0
            try:
                return float(torrent.get("downloaded") or 0)
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(getattr(torrent, "downloadedEver", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _torrent_completed(torrent: Any, downloader_type: str) -> bool:
        """
        判断种子是否已下载完成。

        qBittorrent 使用 progress / completion_on，Transmission 使用 percentDone / doneDate。
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return False
            progress = torrent.get("progress")
            if progress is not None:
                try:
                    # 当前进度明确可读时以进度为准：缺文件、重新校验或扩展下载导致
                    # 进度回退（<1）时，即使 completion_on 仍为正数也视为未完成
                    return float(progress) >= 1
                except (TypeError, ValueError):
                    pass
            # 进度字段缺失或不可解析时才回退到历史完成时间
            return QbUploadLimiter._torrent_completion_time(torrent, downloader_type) > 0
        percent = getattr(torrent, "percentDone", None)
        if percent is not None:
            try:
                # 当前进度明确可读时以进度为准，进度回退不再回退到历史完成时间
                return float(percent) >= 1
            except (TypeError, ValueError):
                pass
        return QbUploadLimiter._torrent_completion_time(torrent, downloader_type) > 0

    @staticmethod
    def _torrent_completion_time(torrent: Any, downloader_type: str) -> int:
        """
        获取种子下载完成时间（Unix 时间戳，秒），未完成时为 0。

        qBittorrent 字段 completion_on、Transmission 字段 doneDate。
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return 0
            try:
                value = int(torrent.get("completion_on") or 0)
            except (TypeError, ValueError):
                return 0
        else:
            try:
                value = int(getattr(torrent, "doneDate", 0) or 0)
            except (TypeError, ValueError):
                return 0
        # 非正值为未完成哨兵（qBittorrent 未完成时 completion_on 为 -1）
        return value if value > 0 else 0

    # ---------------------------------------------------------------- 监控超时取消

    def _check_complete_timeout(
        self, service_name: str, torrent: Any, downloader_type: str, torrent_hash: str, limit: int, now: float
    ) -> bool:
        """
        判断种子是否应因「下载完成后监控超时」而取消监控。

        规则：种子下载完成后，插件持续监控其上传速度；上传速度持续低于限速值
        达到设定秒数时取消监控（速度回升到限速值即重新计时）。
        - 尚未下载完成的种子不参与判断。
        """
        if not self._torrent_completed(torrent, downloader_type):
            return False
        # 速度已达到限速值：清零连续低速计时，不取消
        if self._torrent_upload_speed(torrent, downloader_type) >= limit * 1024:
            self._complete_slow_since.get(service_name, {}).pop(torrent_hash, None)
            return False
        # 连续低速计时：达到设定秒数才取消监控
        slow_since = self._complete_slow_since.get(service_name, {}).get(torrent_hash)
        if slow_since is None:
            self._complete_slow_since.setdefault(service_name, {})[torrent_hash] = now
            return False
        return now - slow_since >= self._complete_timeout

    def _check_limit_timeout(
        self, service_name: str, torrent: Any, downloader_type: str, torrent_hash: str, limit: int, now: float
    ) -> bool:
        """
        判断已限速种子是否应因「限速后超时」而取消监控。

        规则：种子被限速后，持续限速或上传速度低于限速值 80% 达到设定秒数时取消监控。
        """
        # 持续限速计时：从本次设置限速起算，仅当种子当前仍处于目标限速时有效。
        # 种子被手动或其他插件改回非目标限速时重新计时，避免沿用旧时间戳误判超时，
        # 让后续流程优先重新应用本插件限速而不是直接取消监控
        limit_time = self._limited_times.get(service_name, {}).get(torrent_hash)
        if limit_time:
            if not self._torrent_current_limit(torrent, downloader_type, limit, service_name, torrent_hash):
                # 外部改回非目标限速：全部超时计时状态重新起算，
                # 低速计时同样不沿用旧时长，避免提前取消监控
                # （setdefault 确保下载器首次出现时计时写入真实字典而非临时副本）
                self._limited_times.setdefault(service_name, {})[torrent_hash] = now
                self._slow_since.setdefault(service_name, {})[torrent_hash] = now
                limit_time = now
            if now - limit_time >= self._limit_timeout:
                return True
        # 上传速度低于限速值 80% 的连续时长计时
        speed_bps = self._torrent_upload_speed(torrent, downloader_type)
        if speed_bps < limit * 1024 * 0.8:
            slow_since = self._slow_since.get(service_name, {}).get(torrent_hash)
            if slow_since is None:
                self._slow_since.setdefault(service_name, {})[torrent_hash] = now
            elif now - slow_since >= self._limit_timeout:
                return True
        else:
            self._slow_since.get(service_name, {}).pop(torrent_hash, None)
        return False

    def _cancel_monitoring(
        self, service_name: str, torrent_hash: str, torrent_name: str, reason: str, downloader: Any = None,
        site: str = "", channels: Optional[List[str]] = None,
    ):
        """
        取消对单个种子的监控：移出限速记录并清理计时状态，后续轮询不再设置限速。

        - 若该种子此前被本插件限速过（在待恢复集合中），取消监控的同时立即恢复为不限速，
          并从待恢复集合移除，此后插件不再干预该种子（qB 后续如何限速与插件无关）；
        - 若恢复失败，则保留在待恢复集合中，停用/卸载插件时仍会再次尝试恢复。
        """
        self._limited_hashes.get(service_name, set()).discard(torrent_hash)
        self._canceled_hashes.setdefault(service_name, set()).add(torrent_hash)
        self._limited_times.get(service_name, {}).pop(torrent_hash, None)
        self._slow_since.get(service_name, {}).pop(torrent_hash, None)
        self._complete_slow_since.get(service_name, {}).pop(torrent_hash, None)
        # 本插件限速过的种子：取消监控时立即恢复不限速；
        # 恢复失败时保留待恢复记录，停用/卸载插件时仍会兜底重试
        if downloader is not None and torrent_hash in self._restore_hashes.get(service_name, set()):
            try:
                restored = downloader.change_torrent(hash_string=torrent_hash, upload_limit=0)
            except Exception as err:
                restored = False
                logger.error(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 取消监控时恢复不限速失败：{err}")
            if restored:
                self._restore_hashes.get(service_name, set()).discard(torrent_hash)
                logger.info(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 已取消监控并恢复不限速（{reason}）")
                if channels:
                    self._send_event_notify("cancel", site, torrent_name, channels, reason=reason)
            else:
                logger.error(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 取消监控（{reason}）时恢复不限速失败，已保留待恢复记录，停用/卸载时重试")
            return
        logger.info(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 已取消监控（{reason}），不再设置限速")

    # ---------------------------------------------------------------- 通知
    def _send_event_notify(self, event: str, site: str, torrent_name: str, channels: List[str], limit: Optional[float] = None, reason: str = "") -> bool:
        """发送限速状态事件通知。"""
        if not channels:
            return False
        site = (site or "").strip()
        name = (torrent_name or "").strip() or "未知种子"
        subject = f"**{site}**所下的**{name}**" if site else f"**{name}**"
        if event == "limit":
            text, title = f"{subject}已经限速**{limit:g}** KB/s", "【QB上传限速】"
        elif event == "cancel":
            text, title = f"{subject}已取消限速监控，已恢复不限速", "【QB上传限速】取消限速"
        elif event == "ai_takeover":
            text, title = f"AI已接管{subject}，当前限速**{limit:g}** KB/s", "【QB上传限速】AI接管"
        elif event == "ai_release":
            text, title = f"AI已取消接管{subject}，已恢复不限速", "【QB上传限速】AI取消接管"
        else:
            return False
        if reason:
            text += f"（{reason}）"
        sent = False
        for channel in channels:
            notify_channel = self._NOTIFY_TYPE_MAP.get(channel)
            if not notify_channel:
                continue
            try:
                self.post_message(channel=notify_channel, title=title, text=text, link=settings.MP_DOMAIN(f"#/plugins?tab=installed&id={self.__class__.__name__}"))
                sent = True
            except Exception as err:
                logger.error(f"{self.LOG_TAG}发送{event}通知失败（{channel}）：{err}")
        return sent

    def _send_limit_notify(self, site: str, torrent_name: str, limit: float, channels: List[str]) -> bool:
        """发送普通限速通知。"""
        return self._send_event_notify("limit", site, torrent_name, channels, limit=limit) if limit > 0 else False

    def _send_test_notify_if_needed(self) -> bool:
        """
        点击「立即运行一次」时自动发送一次测试通知（支持多个渠道），仅首次发送。
        """
        channels = self._normalize_channels(self._notify_channel)
        if not channels:
            return False
        try:
            if self.get_data("notify_test_sent"):
                logger.info(f"{self.LOG_TAG}测试通知已发送过（仅首次发送），本次跳过")
                return False
        except Exception:
            pass

        # 测试通知的站点取第一个勾选站点，未勾选时使用「测试站点」
        site = next((str(name).strip() for name in (self._sites or []) if str(name).strip()), "")
        if not site:
            site = "测试站点"
        text = f"**{site}**所下的**测试种子**已经限速**{self._upload_limit}** KB/s"
        sent = False
        for channel in channels:
            notify_channel = self._NOTIFY_TYPE_MAP.get(channel)
            if not notify_channel:
                continue
            try:
                self.post_message(
                    channel=notify_channel,
                    title="【QB上传限速】测试通知",
                    text=text,
                    link=settings.MP_DOMAIN(f"#/plugins?tab=installed&id={self.__class__.__name__}"),
                )
                sent = True
            except Exception as err:
                logger.error(f"{self.LOG_TAG}发送测试通知失败（{channel}）：{err}")
        if sent:
            self.save_data("notify_test_sent", True)
            logger.info(f"{self.LOG_TAG}已发送测试通知（仅首次发送）")
        return sent

    @staticmethod
    def _normalize_channels(value: Any) -> List[str]:
        """
        将通知渠道配置规范化为去重后的字符串列表，兼容旧版单个字符串配置。
        """
        if value is None:
            return []
        if isinstance(value, str):
            raw = [value]
        else:
            try:
                raw = list(value)
            except TypeError:
                raw = [value]
        channels = []
        for item in raw:
            item = str(item or "").strip()
            if item and item not in channels:
                channels.append(item)
        return channels

    def _load_set_map(self, key: str) -> Dict[str, set]:
        """
        从插件数据中加载 {下载器: {种子Hash}} 集合映射（JSON 兼容存储为列表）。

        用于跨会话保留待恢复限速种子与已取消监控种子，保证保存配置或
        重启插件后仍能兜底恢复本插件设置过的限速、并保持取消状态不丢失。
        """
        try:
            raw = self.get_data(key) or {}
            if not isinstance(raw, dict):
                return {}
            return {
                str(service): set(str(hash_value) for hash_value in (hashes or []))
                for service, hashes in raw.items()
                if service and hashes
            }
        except Exception as err:
            logger.error(f"{self.LOG_TAG}读取持久化数据 {key} 失败：{err}")
            return {}

    def _save_set_map(self, key: str, mapping: Dict[str, set]):
        """
        将 {下载器: {种子Hash}} 集合映射持久化为 JSON 兼容的 {下载器: [种子Hash]}。

        空集合不落盘，避免无效数据残留。
        """
        try:
            payload = {
                service: sorted(hashes)
                for service, hashes in mapping.items()
                if service and hashes
            }
            self.save_data(key, payload)
        except Exception as err:
            logger.error(f"{self.LOG_TAG}持久化数据 {key} 失败：{err}")

    # ---------------------------------------------------------------- 恢复与调度

    def _restore_limits(self, downloaders: Optional[List[str]] = None):
        """
        将本插件限速过的种子恢复为不限速。

        以待恢复集合为准（含已取消监控但仍限速的种子），用于停用/卸载插件时调用，
        保证不残留任何本插件设置过的限速状态。
        """
        # 未显式指定下载器时，从待恢复记录与当前配置合并确定恢复目标，
        # 避免用户清空/更换下载器选择后，旧下载器的待恢复记录得不到重试
        if downloaders is None:
            names = list(dict.fromkeys((self._downloaders or []) + list(self._restore_hashes.keys())))
        else:
            names = downloaders
        services = self._get_services(names)
        if not services:
            return
        for service_name, service_info in services.items():
            downloader = service_info.instance
            hashes = self._restore_hashes.get(service_name) or set()
            failed_hashes = set()
            for torrent_hash in hashes:
                try:
                    if not downloader.change_torrent(hash_string=torrent_hash, upload_limit=0):
                        failed_hashes.add(torrent_hash)
                        logger.error(f"{self.LOG_TAG}[{service_name}] 恢复种子 [{torrent_hash}] 上传限速失败：下载器返回失败")
                        continue
                    logger.info(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_hash}] 已恢复不限速")
                except Exception as err:
                    failed_hashes.add(torrent_hash)
                    logger.error(f"{self.LOG_TAG}[{service_name}] 恢复种子 [{torrent_hash}] 上传限速失败：{err}")
            # 仅移除确认恢复成功的记录，失败项保留以便后续重试
            if failed_hashes:
                self._restore_hashes[service_name] = failed_hashes
            else:
                self._restore_hashes.pop(service_name, None)
            self._limited_hashes[service_name] = set()

    def _start_scheduler(self):
        """启动后台调度器（存在任务时）。"""
        if self._scheduler and self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

    def _stop_scheduler(self):
        """停止并清理后台调度器。"""
        try:
            if getattr(self, "_scheduler", None):
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    # 等待正在执行的检测任务结束，避免停用/卸载恢复限速时与运行中的
                    # 任务竞态：任务可能在恢复流程完成后再次设置限速
                    self._scheduler.shutdown(wait=True)
                self._scheduler = None
        except Exception as err:
            logger.error(f"{self.LOG_TAG}停止定时任务失败：{err}")

    def _start_restore_retry(self):
        """
        存在待恢复记录时启动兜底恢复重试任务（停用/卸载状态下的生命周期保障）。

        停用/卸载时若下载器短暂离线导致恢复失败，记录保留且不依赖再次触发停止流程；
        下载器重连后，该任务会自动将仍受限速的种子恢复为不限速。
        """
        try:
            if getattr(self, "_retry_scheduler", None) and self._retry_scheduler.running:
                return
            if not any(self._restore_hashes.values()):
                return
            self._retry_attempts = 0
            self._retry_scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._retry_scheduler.add_job(
                func=self._restore_retry_job,
                trigger="interval",
                seconds=60,
                max_instances=1,
                name="QB上传限速-兜底恢复",
            )
            self._retry_scheduler.start()
            logger.info(
                f"{self.LOG_TAG}存在 {sum(len(v) for v in self._restore_hashes.values())} 个待恢复种子，"
                "已启动兜底恢复重试任务"
            )
        except Exception as err:
            logger.error(f"{self.LOG_TAG}启动兜底恢复重试任务失败：{err}")

    def _stop_restore_retry(self, wait: bool = False):
        """
        停止兜底恢复重试任务。

        :param wait: 是否等待正在执行的重试任务结束；重新启用插件时传 True，
                     避免在途任务与新一轮限速/恢复流程并发竞态（任务自身停止时
                     必须传 False，否则会等待自己造成死锁）
        """
        try:
            if getattr(self, "_retry_scheduler", None):
                if self._retry_scheduler.running:
                    self._retry_scheduler.shutdown(wait=wait)
                self._retry_scheduler = None
            self._retry_attempts = 0
        except Exception as err:
            logger.error(f"{self.LOG_TAG}停止兜底恢复重试任务失败：{err}")

    def _restore_retry_job(self):
        """
        兜底恢复重试任务：每轮尝试恢复待恢复记录。

        全部恢复成功后自动停止；下载器长时间离线时持续重试（每达到报告间隔
        输出一次告警），保证下载器重连后无需重新启用插件即可恢复不限速。
        每轮持久化结果，重启插件后仍会继续重试。
        """
        try:
            self._restore_limits()
        except Exception as err:
            logger.error(f"{self.LOG_TAG}兜底恢复上传不限速失败：{err}")
        # 每轮持久化恢复结果：恢复失败项保留，重启后继续重试
        self._save_set_map(self._RESTORE_DATA_KEY, self._restore_hashes)
        if not any(self._restore_hashes.values()):
            self._stop_restore_retry()
            return
        self._retry_attempts += 1
        if self._retry_attempts % self._MAX_RESTORE_RETRY == 0:
            # 达到报告间隔后不终止任务：下载器可能长时间离线，继续定时重试，
            # 保证下载器重连后种子能自动恢复不限速
            logger.warning(
                f"{self.LOG_TAG}待恢复种子仍有限速未恢复（已重试 {self._retry_attempts} 次），"
                "已继续定时重试，下载器重连后将自动恢复，请检查下载器连接"
            )

    def _retry_stuck_restores(self, service_name: str, downloader: Any):
        """
        启用状态下兜底重试「已取消监控但恢复失败」的种子恢复不限速。

        仅处理待恢复集合中未被本插件继续限速的种子（已取消监控项），
        避免与正在限速的种子冲突；下载器短暂离线导致的恢复失败，
        在下载器恢复后由每轮检测顺带重试，无需等待停用/卸载。
        """
        pending = set(self._restore_hashes.get(service_name) or set()) - set(
            self._limited_hashes.get(service_name) or set()
        )
        if not pending:
            return
        succeeded = set()
        for torrent_hash in pending:
            try:
                if not downloader.change_torrent(hash_string=torrent_hash, upload_limit=0):
                    logger.error(f"{self.LOG_TAG}[{service_name}] 兜底恢复种子 [{torrent_hash}] 上传限速失败：下载器返回失败")
                    continue
                succeeded.add(torrent_hash)
                logger.info(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_hash}] 已兜底恢复不限速")
            except Exception as err:
                logger.error(f"{self.LOG_TAG}[{service_name}] 兜底恢复种子 [{torrent_hash}] 上传限速失败：{err}")
        if succeeded:
            self._restore_hashes.get(service_name, set()).difference_update(succeeded)

    def _retry_all_stuck_restores(self):
        """
        对所有存在待恢复记录的服务兜底重试恢复不限速（启用状态下每轮调用）。

        覆盖所有持久化待恢复服务，包括已从插件选择中移除的下载器：
        下载器离线期间被移除选择导致的恢复失败，重连后无需重新选择即可恢复。
        """
        pending_services = [service for service, hashes in self._restore_hashes.items() if hashes]
        if not pending_services:
            return
        services = self._get_services(pending_services)
        if not services:
            return
        for service_name, service_info in services.items():
            self._retry_stuck_restores(service_name, service_info.instance)

    # ---------------------------------------------------------------- 工具方法

    def _normalize_site_share_ratios(self, value: Any) -> Tuple[Dict[str, float], str]:
        """
        解析并规范化站点单独分享率阈值。

        表单使用每行「站点名称=正数阈值」格式；同时兼容字典、字符串列表和
        {site/name/sitename, ratio/share_ratio/threshold} 字典列表，便于兼容历史或 API 配置。
        站点名称按小写匹配，重复站点以最后一项为准，非法项会被忽略。
        """
        ratios: Dict[str, float] = {}
        labels: Dict[str, str] = {}
        invalid_count = 0

        def add_entry(raw_name: Any, raw_ratio: Any):
            nonlocal invalid_count
            name = str(raw_name or "").strip()
            ratio = self._to_ratio(raw_ratio, 0.0)
            if not name or ratio <= 0:
                invalid_count += 1
                return
            key = name.lower()
            ratios[key] = ratio
            labels[key] = name

        def add_text(raw_text: Any):
            nonlocal invalid_count
            for raw_line in str(raw_text or "").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                separator = next((item for item in ("=", "：", ":") if item in line), "")
                if not separator:
                    invalid_count += 1
                    continue
                name, ratio = line.split(separator, 1)
                add_entry(name, ratio)

        if isinstance(value, dict):
            for name, ratio in value.items():
                add_entry(name, ratio)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, dict):
                    name = item.get("site") or item.get("name") or item.get("sitename")
                    ratio = item.get("ratio")
                    if ratio is None:
                        ratio = item.get("share_ratio")
                    if ratio is None:
                        ratio = item.get("threshold")
                    add_entry(name, ratio)
                else:
                    add_text(item)
        else:
            add_text(value)

        if invalid_count:
            logger.warning(f"{self.LOG_TAG}站点单独分享率阈值中有 {invalid_count} 项格式无效，已忽略")
        normalized_text = "\n".join(f"{labels[key]}={ratio}" for key, ratio in ratios.items())
        return ratios, normalized_text

    @staticmethod
    def _normalize_config_list(value: Any) -> List[str]:
        """
        将配置项规范化为去重后的字符串列表，兼容旧版单个字符串配置。

        :param value: 配置项原始值（可为字符串或列表）
        """
        if value is None:
            return []
        if isinstance(value, str):
            raw = [value]
        else:
            try:
                raw = list(value)
            except TypeError:
                raw = [value]
        items = []
        for item in raw:
            item = str(item or "").strip()
            if item and item not in items:
                items.append(item)
        return items

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        """
        安全转换为整数：仅接受整数或整数字符串，拒绝小数与科学计数法，转换失败时返回默认值。

        :param value: 待转换值（可为数字或字符串）
        :param default: 转换失败时的默认值
        """
        if value is None or isinstance(value, bool):
            return default
        try:
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                # 整数值的浮点（如 30.0）视为合法整数，非整数值拒绝
                return int(value) if value.is_integer() else default
            text = str(value).strip()
            # 含小数点或科学计数法标记的字符串不是正整数
            if not text or any(c in text for c in ".eE"):
                return default
            return int(text)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_ratio(value: Any, default: float = 1.0) -> float:
        """
        安全转换分享率阈值为正浮点数（最多 1 位小数）。

        规则：不能为 0、不能为负；小数最多取 1 位（四舍五入）；NaN、非数字、
        0、负数或四舍五入后仍为 0 的非法值一律回退默认值。
        """
        if value is None or isinstance(value, bool):
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if number != number:  # NaN
            return default
        number = round(number, 1)
        if number <= 0:
            return default
        return number

    @staticmethod
    def _format_limit(limit: float) -> str:
        """格式化限速显示。"""
        if limit <= 0:
            return "不限速"
        value = float(limit)
        display = int(value) if value.is_integer() else round(value, 3)
        return f"{display} KB/s"
