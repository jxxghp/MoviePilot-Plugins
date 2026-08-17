"""
QB上传限速插件（MoviePilot v2/v3）。

功能：
1. 定时轮询已选下载器（qBittorrent / Transmission）中的种子；
2. 仅处理 MoviePilot 已「整理入库成功」的种子：种子入库成功前对插件完全不可见，不监控、不限速（等同于插件未开启），入库成功后才按分享率限速；
3. 种子分享率（上传量 / 下载量）达到全局或站点单独阈值后，自动限制该种子上传速度为指定值（KB/s）；qBittorrent 全局上传限速更低时自动采用全局值，上传速度填 0 时不做限速处理；
4. 支持按站点筛选和按站点单独设置分享率阈值；未配置单独阈值的站点回退使用全局阈值；
5. 停用或卸载插件时，自动将本插件限速过的种子恢复为不限速；
6. 限速通知支持多选 MoviePilot 已启用通知渠道，测试通知仅首次发送；
7. 支持监控超时取消：下载完成后达不到限速值、或限速后持续超时/速度低于限速值 80% 时，取消监控并立即恢复该种子不限速。
"""

import datetime
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
    分享率 = 上传量 / 下载量，阈值为正整数，达到阈值后自动限速。
    """

    plugin_name = "QB上传限速"
    plugin_desc = "仅处理 MoviePilot 已整理入库成功的种子：分享率达到全局或站点单独阈值后自动限制上传速度（qBittorrent 与全局上传限速取较小值）；支持多下载器、站点筛选、定时检测，停用/卸载自动恢复不限速。"
    plugin_icon = "Qbittorrent_A.png"
    plugin_version = "1.3.4"
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
    # 全局分享率阈值（正整数）
    _share_ratio = 1
    # 站点名称（小写）-> 单独分享率阈值；未命中时使用全局阈值
    _site_share_ratios: Dict[str, int] = {}
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
        self._share_ratio = max(self._to_int(config.get("share_ratio"), 1), 1)
        self._site_share_ratios, self._site_share_ratios_text = self._normalize_site_share_ratios(
            config.get("site_share_ratios")
        )
        self._upload_limit = max(self._to_int(config.get("upload_limit"), 2000), 0)
        self._interval_seconds = max(self._to_int(config.get("interval_seconds"), 30), 10)
        # 监控超时取消配置（秒），0 表示不启用
        self._complete_timeout = max(self._to_int(config.get("complete_timeout"), 0), 0)
        self._limit_timeout = max(self._to_int(config.get("limit_timeout"), 0), 0)
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

    def get_page(self) -> List[dict]:
        """
        无独立详情页：点击插件卡片或通知消息将直接打开插件设置。
        """
        pass

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
                                            "placeholder": "正整数（≥1）；站点未配置单独阈值时使用该值",
                                            "type": "number",
                                            "min": 1,
                                            "step": 1,
                                            "hint": "不允许填 0，分享率阈值必须为正整数（≥1）",
                                            "persistent-hint": True,
                                            "onKeydown": "function (e) { if (e.key === '0') { var v = e.target.value || ''; var s = e.target.selectionStart || 0; var en = e.target.selectionEnd || 0; var next = v.slice(0, s) + '0' + v.slice(en); if (/^0+$/.test(next)) { e.preventDefault(); } } }",
                                            "onPaste": "function (e) { var t = (e.clipboardData || window.clipboardData).getData('text'); if (/^0+$/.test(t)) { var v = e.target.value || ''; var s = e.target.selectionStart || 0; var en = e.target.selectionEnd || 0; var next = v.slice(0, s) + t + v.slice(en); if (/^0+$/.test(next)) { e.preventDefault(); } } }",
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "site_share_ratios",
                                            "label": "按站点单独分享率阈值",
                                            "placeholder": "一行一个，例如：\n站点A=3\n站点B=5",
                                            "rows": 3,
                                            "auto-grow": True,
                                            "clearable": True,
                                            "hint": "格式：站点名称=正整数阈值（≥1）。对应站点使用单独阈值；未配置或无法识别站点时回退使用全局分享率阈值。",
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
                                            "text": "本插件仅处理 MoviePilot 已整理入库成功的种子：种子入库成功前不监控、不限速（等同于插件未开启），入库成功后按分享率逐种子限速——分享率（上传量/下载量）达到全局或站点单独设置的正整数阈值后，其上传速度将被限制为设定值（KB/s）。站点单独阈值使用「站点名称=阈值」格式，一行一个；未配置或无法识别站点时使用全局阈值。上传速度填 0 表示不做限速处理；两个监控超时填 0 表示不启用对应功能。支持 qBittorrent 和 Transmission。",
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

    def _threshold_for_site(self, site: str, fallback: int) -> int:
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

    def _set_torrent_limits(self, share_ratio: int, upload_limit: int, channel: Any = None) -> bool:
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

        threshold = max(self._to_int(share_ratio, 1), 1)
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
                f"（其他站点使用全局阈值 {threshold}）"
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
                            )
                            timeout_canceled += 1
                # 筛选出已入库且达标且（可选）属于勾选站点的种子；记录每个达标种子实际使用的阈值
                threshold_cache: Dict[str, int] = {}
                matched = self._collect_matched_torrents(
                    torrents=eligible_torrents,
                    downloader_type=downloader_type,
                    threshold=threshold,
                    selected=selected,
                    site_cache=site_cache,
                    threshold_cache=threshold_cache,
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
        downloader_type: str,
        threshold: int,
        selected: Optional[Set[str]],
        site_cache: Dict[str, str],
        threshold_cache: Dict[str, int],
    ) -> List[Any]:
        """
        从种子列表中筛选出达到分享率阈值且（可选）属于勾选站点的种子。

        启用站点筛选或配置了站点单独阈值时，一次性批量查询下载历史
        （hash -> 站点），优先使用 MoviePilot 记录的权威站点信息。
        每个达标种子实际使用的阈值写入 threshold_cache，供日志准确显示。
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
            # 只处理已下载完成的种子，下载中的种子即使分享率达标也不限速
            if not self._torrent_completed(torrent, downloader_type):
                continue

            site = ""
            if need_site:
                site = self._resolve_site(torrent, torrent_hash, downloader_type, history_sites, site_cache)
            # 站点筛选：无法识别或不属于勾选列表时跳过
            if selected and (not site or site.lower() not in selected):
                continue

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
        threshold: int,
        channel: Any,
        site_cache: Dict[str, str],
        threshold_cache: Dict[str, int],
    ) -> Tuple[int, int, int, int]:
        """
        对达标种子逐个设置上传限速，返回 (新增限速数, 已满足数, 失败数, 取消监控数)。

        监控超时取消机制（对应配置项为 0 时关闭）：
        - 下载完成后超时：种子下载完成后，若在设定秒数内上传速度始终达不到限速值，
          取消监控并立即恢复该种子不限速；
        - 限速后超时：种子被限速后，持续限速或上传速度低于限速值 80% 达到设定秒数时，
          取消监控并立即恢复该种子不限速。
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
            # 已取消监控的种子：跳过，不再设置限速
            if torrent_hash in canceled_hashes:
                continue

            now = time.time()
            restore_hashes = self._restore_hashes.setdefault(service_name, set())
            # 是否已由本插件认领（本次会话限速过，或跨会话仍有待恢复记录）
            owned = torrent_hash in limited_hashes or torrent_hash in restore_hashes

            if owned:
                if self._limit_timeout > 0 and limit > 0:
                    # 已认领种子（含跨会话恢复出的）重新建立限速起始时间，
                    # 保证「限速后超时」计时可用
                    self._limited_times.setdefault(service_name, {}).setdefault(torrent_hash, now)
                # 已认领种子：按「限速后超时」规则判断是否取消监控
                if self._limit_timeout > 0 and limit > 0 and self._check_limit_timeout(
                    service_name, torrent, downloader_type, torrent_hash, limit, now
                ):
                    self._cancel_monitoring(service_name, torrent_hash, torrent_name, reason="限速后超时", downloader=downloader)
                    canceled += 1
                    continue
                # 当前限速已是目标值：计入「已满足」，避免重复调用下载器接口
                if self._torrent_current_limit(torrent, downloader_type, limit, service_name, torrent_hash):
                    limited_hashes.add(torrent_hash)
                    already += 1
                    continue
            else:
                # 未认领种子：当前限速已等于目标值且并非本插件所设，不认领所有权，
                # 避免停用/卸载时误将外部设置的限速恢复为不限速
                # （「下载完成后监控超时」已在每轮检测前对所有已完成未认领种子统一处理）
                if self._torrent_current_limit(torrent, downloader_type, limit, service_name, torrent_hash):
                    already += 1
                    continue

            try:
                if not downloader.change_torrent(hash_string=torrent_hash, upload_limit=limit):
                    failed += 1
                    continue
                limited_hashes.add(torrent_hash)
                # 登记到待恢复集合：即使后续取消监控，停用/卸载时也能恢复不限速
                restore_hashes.add(torrent_hash)
                # 记录本次限速时间，用于「限速后超时」计时
                self._limited_times.setdefault(service_name, {})[torrent_hash] = now
                new_limited += 1
                logger.info(
                    f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 分享率达到 {torrent_threshold}，"
                    f"已限速 {self._format_limit(limit)}"
                )
                # 仅首次新限速的种子逐条通知；已认领种子被外部改回后重新应用限速
                # 不再重复发送通知，避免每轮检测重复推送
                if channels and not owned:
                    site = site_cache.get(torrent_hash, "") or self._torrent_site(torrent, downloader_type)
                    self._send_limit_notify(site=site, torrent_name=torrent_name, limit=limit, channels=channels)
            except Exception as err:
                failed += 1
                logger.error(f"{self.LOG_TAG}[{service_name}] 设置种子 [{torrent_name}] 上传限速失败：{err}")
        return new_limited, already, failed, canceled

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
        self, service_name: str, torrent_hash: str, torrent_name: str, reason: str, downloader: Any = None
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
            else:
                logger.error(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 取消监控（{reason}）时恢复不限速失败，已保留待恢复记录，停用/卸载时重试")
            return
        logger.info(f"{self.LOG_TAG}[{service_name}] 种子 [{torrent_name}] 已取消监控（{reason}），不再设置限速")

    # ---------------------------------------------------------------- 通知
    def _send_limit_notify(self, site: str, torrent_name: str, limit: float, channels: List[str]) -> bool:
        """
        发送单条限速通知：{站点}所下的{种子}已经限速{速度} KB/s，变量加粗；支持多个通知渠道。

        注意：故意不传 mtype（消息类型），以绕过 MoviePilot 通知渠道的
        「通知场景」开关过滤——用户已在本插件中显式勾选渠道，应保证必定送达。
        """
        if limit <= 0:
            return False
        site = (site or "").strip()
        name = (torrent_name or "").strip() or "未知种子"
        if site:
            text = f"**{site}**所下的**{name}**已经限速**{limit}** KB/s"
        else:
            text = f"**{name}**已经限速**{limit}** KB/s"
        sent = False
        for channel in channels:
            notify_channel = self._NOTIFY_TYPE_MAP.get(channel)
            if not notify_channel:
                continue
            try:
                self.post_message(
                    channel=notify_channel,
                    title="【QB上传限速】",
                    text=text,
                    link=settings.MP_DOMAIN(f"#/plugins?tab=installed&id={self.__class__.__name__}"),
                )
                sent = True
            except Exception as err:
                logger.error(f"{self.LOG_TAG}发送限速通知失败（{channel}）：{err}")
        return sent

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

    def _normalize_site_share_ratios(self, value: Any) -> Tuple[Dict[str, int], str]:
        """
        解析并规范化站点单独分享率阈值。

        表单使用每行「站点名称=正整数阈值」格式；同时兼容字典、字符串列表和
        {site/name/sitename, ratio/share_ratio/threshold} 字典列表，便于兼容历史或 API 配置。
        站点名称按小写匹配，重复站点以最后一项为准，非法项会被忽略。
        """
        ratios: Dict[str, int] = {}
        labels: Dict[str, str] = {}
        invalid_count = 0

        def add_entry(raw_name: Any, raw_ratio: Any):
            nonlocal invalid_count
            name = str(raw_name or "").strip()
            ratio = self._to_int(raw_ratio, 0)
            if not name or ratio < 1:
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
    def _format_limit(limit: float) -> str:
        """格式化限速显示。"""
        if limit <= 0:
            return "不限速"
        value = float(limit)
        display = int(value) if value.is_integer() else round(value, 3)
        return f"{display} KB/s"
