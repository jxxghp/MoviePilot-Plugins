"""
EMOS 上传插件（MoviePilot V2）。

功能：
1. 定时轮询已选下载器，种子【下载完成】瞬间自动上传源文件到 EMOS；
2. 通过 EMOS 服务器端接口识别文件，自动匹配剧集信息；
3. 上传前检查 EMOS 已有资源版本，避免重复上传；
4. 支持 ask/silent 两种上传模式；
5. 支持分片并发上传，最大化吞吐。
"""

import datetime
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import urllib.request
import urllib.error

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.downloader import DownloaderHelper
from app.helper.service import ServiceConfigHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MessageChannel
from app.utils.system import SystemUtils


class EmosUpload(_PluginBase):
    """
    EMOS 上传插件。

    定时轮询下载器，检测到种子下载完成即上传其源文件到
    EMOS（Emby 资源站上传分发系统）。
    支持 ask（上传前确认）与 silent（自动上传）两种模式。
    """
    plugin_name = "EMOS上传"
    plugin_desc = "MoviePilot 下载完成后自动上传到 EMOS（Emby 资源站上传分发系统），轮询下载器检测下载完成即上传源文件，支持服务器端识别、版本对比、分片并发上传。"
    plugin_icon = "Emos_A.svg"
    plugin_version = "2.1.0"
    plugin_author = "xlmc"
    author_url = "https://github.com/xlmc"
    plugin_config_prefix = "emosupload_"
    plugin_order = 40
    auth_level = 1

    LOG_TAG = "[EMOS上传] "

    # ---- 硬编码域名（不暴露给用户） ----
    _API_BASE = "emos.best"
    _IDENTIFY_BASE = "emoss.wwzb.de"

    # ---- 配置项默认值 ----
    _enabled = False
    _token_path = "/opt/data/creds/emos_token"
    _token = ""
    _upload_mode = "ask"        # ask 或 silent
    _skip_tags = "刷流,保种,seedbox"  # 跳过标签（逗号分隔），命中的种子不上传
    _target_parts = 24          # 目标分片数
    _concurrency = 16           # 并发线程数
    _poll_interval = 60         # 轮询下载器间隔（秒）
    _notify_channel = []        # 通知渠道
    _onlyonce = False           # 仅运行一次（手动触发）

    # 调度器
    _scheduler = None

    # 已处理（已触发上传）的种子 hash 集合，防止重复
    _handled: Set[str] = set()

    # 运行时状态
    _upload_lock = threading.Lock()
    _ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

    # ---- 上传历史 ----
    _upload_history: List[dict] = []

    # ---- 待确认上传队列（ask 模式） ----
    _pending_uploads: List[dict] = []
    _pending_seq = 0

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

    def init_plugin(self, config: dict = None):
        """根据当前配置初始化插件，并启动下载器轮询任务。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._token_path = config.get("token_path") or self._token_path
        self._upload_mode = config.get("upload_mode") or self._upload_mode
        self._skip_tags = config.get("skip_tags") or self._skip_tags
        self._target_parts = int(config.get("target_parts") or self._target_parts)
        self._concurrency = int(config.get("concurrency") or self._concurrency)
        self._poll_interval = max(int(config.get("poll_interval") or self._poll_interval), 15)
        self._notify_channel = self._normalize_channels(config.get("notify_channel"))
        self._onlyonce = bool(config.get("onlyonce"))

        # 加载 token
        self._load_token()

        # 载入已处理的种子 hash，避免重复上传
        try:
            old = self.get_data("handled_hashes") or []
            self._handled = set(old) if isinstance(old, list) else set()
        except Exception as e:
            logger.warning(f"{self.LOG_TAG}读取已处理记录失败: {e}")
            self._handled = set()

        # 停止旧的调度器
        try:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
        except Exception:
            pass
        self._scheduler = None

        # 仅运行一次：3 秒后执行一次轮询
        if self._onlyonce:
            self._onlyonce = False
            self.update_config({"onlyonce": False})
            threading.Thread(target=self._poll_and_process, args=(), daemon=True,
                             name="EmosOncePoll").start()

        # 启用后：先立即轮询一次，再按间隔周期轮询
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        if self._enabled:
            self._poll_and_process()
            self._scheduler.add_job(
                func=self._poll_and_process,
                trigger="interval",
                seconds=self._poll_interval,
                coalesce=True,
                max_instances=1,
                name="EMOS 轮询下载完成种子",
            )
        if self._scheduler.get_jobs():
            self._scheduler.start()

    def _load_token(self):
        """加载 EMOS token。"""
        if self._token_path and os.path.exists(self._token_path):
            try:
                with open(self._token_path, 'r') as f:
                    self._token = f.read().strip()
                logger.info(f"{self.LOG_TAG}Token 已加载")
            except Exception as e:
                logger.error(f"{self.LOG_TAG}读取 token 失败: {e}")
                self._token = ""
        else:
            self._token = ""

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """注册远程命令。"""
        return [
            {
                "cmd": "/emos_status",
                "event": EventType.PluginAction,
                "desc": "查看 EMOS 上传状态",
                "category": "插件命令",
                "data": {
                    "action": "emos_status",
                },
            },
            {
                "cmd": "/emos_confirm",
                "event": EventType.PluginAction,
                "desc": "确认待上传文件（传=[全部编号]），例：/emos_confirm 传 1 2 / 不传 1",
                "category": "插件命令",
                "data": {
                    "action": "emos_confirm",
                },
            },
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """声明插件 API。"""
        return [
            {
                "path": "/status",
                "endpoint": self._api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取上传状态",
                "description": "获取当前插件状态、待确认列表和上传历史",
            },
            {
                "path": "/pending",
                "endpoint": self._api_pending,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取待确认列表",
                "description": "获取当前待确认上传的列表",
            },
        ]

    @staticmethod
    def _get_notify_items() -> List[dict]:
        """获取 MoviePilot 已启用通知渠道（type 去重），供配置下拉选择。"""
        items = []
        try:
            seen = set()
            for conf in (ServiceConfigHelper.get_notification_configs() or []):
                if not getattr(conf, "enabled", False):
                    continue
                conf_type = getattr(conf, "type", "") or ""
                conf_name = getattr(conf, "name", "") or conf_type
                if conf_type and conf_type not in seen:
                    seen.add(conf_type)
                    items.append({"title": conf_name, "value": conf_type})
        except Exception as e:
            logger.warning(f"{self.LOG_TAG}读取通知渠道配置失败: {e}")
        return items

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回配置页 JSON 和默认配置模型。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
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
                                            "model": "upload_mode",
                                            "label": "上传模式",
                                            "items": [
                                                {"title": "询问模式 (ask) - 识别后确认再上传", "value": "ask"},
                                                {"title": "静默模式 (silent) - 自动上传", "value": "silent"},
                                            ],
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
                                        "component": "VTextField",
                                        "props": {
                                            "model": "skip_tags",
                                            "label": "跳过标签（逗号分隔，命中种子的标签则不上传）",
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
                                            "model": "poll_interval",
                                            "label": "轮询间隔（秒）",
                                            "type": "number",
                                            "hint": "下载器轮询间隔，检测种子下载完成即上传",
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
                                        "component": "VTextField",
                                        "props": {
                                            "model": "token_path",
                                            "label": "Token 文件路径",
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
                                            "model": "target_parts",
                                            "label": "目标分片数",
                                            "type": "number",
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
                                            "model": "concurrency",
                                            "label": "并发数",
                                            "type": "number",
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
                                "props": {"cols": 12, "md": 12},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "notify_channel",
                                            "label": "通知渠道",
                                            "items": self._get_notify_items(),
                                            "multiple": True,
                                            "chips": True,
                                            "clearable": True,
                                            "hint": "ask 模式确认消息发送到的渠道；多选则发送到所选渠道，留空不发送通知（注意：ask 模式无确认消息将无法确认）。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "token_path": "/opt/data/creds/emos_token",
            "upload_mode": "ask",
            "skip_tags": "刷流,保种,seedbox",
            "target_parts": 24,
            "concurrency": 16,
            "poll_interval": 60,
            "notify_channel": [],
            "onlyonce": False,
        }

    def get_page(self) -> List[dict]:
        """返回详情页 JSON。"""
        status_text = "✅ 已启用" if self._enabled else "❌ 未启用"
        token_status = "✅ 已配置" if self._token else "❌ 未配置"
        mode_text = "询问模式" if self._upload_mode == "ask" else "静默模式"
        history_count = len(self._upload_history)
        pending_count = len(self._pending_uploads)

        page = [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "info" if self._enabled else "warning",
                                    "variant": "tonal",
                                    "text": f"插件状态: {status_text}",
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "success" if self._token else "error",
                                    "variant": "tonal",
                                    "text": f"Token: {token_status}",
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "text": f"上传模式: {mode_text} | 待确认: {pending_count} | 历史: {history_count} 条",
                                },
                            }
                        ],
                    },
                ],
            },
        ]

        # 待确认列表
        if self._pending_uploads:
            page.append({
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "warning",
                                    "variant": "tonal",
                                    "text": f"⏳ {pending_count} 个文件待确认上传，可用 /emos_confirm 传 确认",
                                },
                            }
                        ],
                    },
                ],
            })

        # 上传历史
        if self._upload_history:
            page.append({
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VDataTable",
                                "props": {
                                    "headers": [
                                        {"title": "文件", "key": "file"},
                                        {"title": "大小", "key": "size"},
                                        {"title": "速度", "key": "speed"},
                                        {"title": "时间", "key": "time"},
                                        {"title": "结果", "key": "result"},
                                    ],
                                    "items": self._upload_history[-10:],
                                    "density": "compact",
                                    "hover": True,
                                },
                            }
                        ],
                    },
                ],
            })

        # 使用说明
        page.append({
            "component": "VAlert",
            "props": {
                "type": "warning",
                "variant": "tonal",
                "text": "说明：轮询下载器，种子下载完成后自动识别并处理。ask 模式先汇报待确认，silent 模式自动上传。相同版本不重复上传。",
            },
        })

        return page

    def stop_service(self):
        """停用插件时停止轮询调度器并保存已处理记录。"""
        try:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
        except Exception:
            pass
        self._scheduler = None
        # 持久化已处理 hash
        try:
            self.save_data("handled_hashes", list(self._handled))
        except Exception:
            pass

    # ---- 轮询下载器（下载完成即上传） ----

    def _poll_and_process(self):
        """轮询已选下载器，检测下载完成的种子并触发上传。"""
        if not self._enabled or not self._token:
            return
        try:
            services = DownloaderHelper().get_services()
            if not services:
                return
            for _name, service_info in services.items():
                downloader = service_info.instance
                if not downloader or downloader.is_inactive():
                    continue
                downloader_type = getattr(service_info, "type", "")
                try:
                    torrents, error = downloader.get_torrents()
                except Exception as e:
                    logger.warning(f"{self.LOG_TAG}获取下载器 [{_name}] 种子列表失败: {e}")
                    continue
                if error or not torrents:
                    continue
                for torrent in torrents or []:
                    t_hash = self._torrent_hash(torrent, downloader_type)
                    if not t_hash or t_hash in self._handled:
                        continue
                    if not self._torrent_completed(torrent, downloader_type):
                        continue
                    # 刷流/保种标签直接跳过（不标记，避免长期做种撑大集合）
                    tags = self._torrent_tags(torrent, downloader_type)
                    if self._has_skip_tags(tags):
                        logger.info(f"{self.LOG_TAG}种子 [{t_hash[:8]}] 命中跳过标签 {tags}，不上传")
                        continue
                    # 获取该种子下载的媒体文件（源文件）
                    files = self._torrent_media_files(torrent, downloader_type)
                    if not files:
                        logger.warning(f"{self.LOG_TAG}种子 [{t_hash[:8]}] 未找到媒体文件，跳过")
                        self._mark_handled(t_hash)
                        continue
                    self._mark_handled(t_hash)
                    logger.info(f"{self.LOG_TAG}检测到下载完成种子 [{t_hash[:8]}]，即将上传 {len(files)} 个文件")
                    self._send_notification(
                        f"📥 检测到下载完成，正在上传\n"
                        f"种子: {self._torrent_name(torrent, downloader_type) or t_hash[:8]}\n"
                        f"文件: {len(files)} 个（源文件）"
                    )
                    threading.Thread(
                        target=self._handle_upload_batch, args=(files,), daemon=True,
                        name="EmosUploadPoll"
                    ).start()
        except Exception as e:
            logger.error(f"{self.LOG_TAG}轮询处理异常: {e}")

    def _mark_handled(self, t_hash: str):
        """标记种子已处理并持久化，防止重复上传。"""
        if t_hash in self._handled:
            return
        self._handled.add(t_hash)
        try:
            self.save_data("handled_hashes", list(self._handled)[-5000:])
        except Exception:
            pass

    @staticmethod
    def _torrent_completed(torrent: Any, downloader_type: str) -> bool:
        """判断种子是否已下载完成。

        qBittorrent 用 progress / completion_on，Transmission 用 percent_done / done_date。
        """
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return False
            progress = torrent.get("progress")
            if progress is not None:
                try:
                    return float(progress) >= 1
                except (TypeError, ValueError):
                    pass
            return int(torrent.get("completion_on") or 0) > 0
        percent = getattr(torrent, "percent_done", None)
        if percent is not None:
            try:
                return float(percent) >= 1
            except (TypeError, ValueError):
                pass
        return int(getattr(torrent, "done_date", 0) or 0) > 0

    def _torrent_media_files(self, torrent: Any, downloader_type: str) -> List[str]:
        """获取种子下载的媒体文件（源文件）路径列表。"""
        path = self._torrent_path(torrent, downloader_type)
        if not path or not os.path.exists(path):
            return []
        try:
            ext = settings.RMT_MEDIAEXT
            if os.path.isfile(path):
                return [str(path)] if Path(path).suffix.lower() in ext else []
            # 目录：枚举媒体文件（含子目录）
            files = list(SystemUtils.list_files(Path(path), ext) or [])
            # 过滤样本/预告片等非正片
            filter_re = re.compile(r'(\bsample\b|\btrailer\b|\bpreview\b|\bextra\b|\bbonus\b)', re.IGNORECASE)
            return [str(f) for f in files if not filter_re.search(Path(f).name)]
        except Exception as e:
            logger.warning(f"{self.LOG_TAG}枚举下载文件失败: {e}")
            return []

    @staticmethod
    def _torrent_path(torrent: Any, downloader_type: str) -> str:
        """获取种子内容路径（文件或目录）。"""
        try:
            if downloader_type == "qbittorrent":
                if not isinstance(torrent, dict):
                    return ""
                cp = torrent.get("content_path")
                if cp:
                    return str(cp)
                save = torrent.get("save_path") or ""
                name = torrent.get("name") or ""
                return str(Path(save) / name) if save else ""
            download_dir = (getattr(torrent, "download_dir", None)
                            or getattr(torrent, "downloadDir", None))
            name = getattr(torrent, "name", "") or ""
            return str(Path(str(download_dir)) / name) if download_dir else ""
        except Exception:
            return ""

    @staticmethod
    def _torrent_name(torrent: Any, downloader_type: str) -> str:
        """获取种子名称。"""
        if downloader_type == "qbittorrent":
            return str(torrent.get("name") or "") if isinstance(torrent, dict) else ""
        return str(getattr(torrent, "name", None) or "")

    def _has_skip_tags(self, tags: List[str]) -> bool:
        """判断种子标签是否命中跳过标签。"""
        if not self._skip_tags or not tags:
            return False
        skip_list = [t.strip().lower() for t in self._skip_tags.split(",") if t.strip()]
        if not skip_list:
            return False
        return any(tag and tag.strip().lower() in skip_list for tag in tags)

    @staticmethod
    def _torrent_tags(torrent: Any, downloader_type: str) -> List[str]:
        """获取种子标签列表。"""
        if downloader_type == "qbittorrent":
            if not isinstance(torrent, dict):
                return []
            tags = torrent.get("tags") or ""
            return [str(t).strip() for t in str(tags).split(",") if str(t).strip()]
        labels = getattr(torrent, "labels", None) or []
        return [str(label).strip() for label in labels if str(label).strip()]

    @staticmethod
    def _torrent_hash(torrent: Any, downloader_type: str) -> str:
        """获取种子 hash。"""
        if downloader_type == "qbittorrent":
            return str(torrent.get("hash") or "").strip() if isinstance(torrent, dict) else ""
        hash_val = getattr(torrent, "hash", None)
        return str(hash_val or "").strip()

    def _inspect_file(self, file_path: str) -> dict:
        """识别 + 版本对比单个文件，返回处理决策（供批量聚合）。"""
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        idr = self._identify_file(file_name)
        if idr.get("error"):
            return {"ok": False, "file_name": file_name, "error": idr.get("error")}
        item_type = idr.get("item_type")
        item_id = idr.get("item_id")
        name = idr.get("name", "未知")
        season = idr.get("season")
        episode = idr.get("episode")
        if season is None or episode is None:
            item_label = f"ID={item_id}"
        else:
            item_label = f"S{season:02d}E{episode:02d}"
        # 检查是否已有资源并版本对比
        same_version = False
        try:
            existing = self._check_media_exists(item_type, item_id)
            video_medias = existing.get("video_medias", [])
            if video_medias:
                same_version = not self._compare_versions(file_name, file_size, video_medias)
        except Exception as e:
            logger.warning(f"{self.LOG_TAG}版本检查失败 {file_name}: {e}")
        return {
            "ok": True, "file_path": file_path, "file_name": file_name, "file_size": file_size,
            "item_type": item_type, "item_id": item_id, "name": name, "season": season,
            "episode": episode, "item_label": item_label, "same_version": same_version,
        }

    def _handle_upload_batch(self, file_paths: List[str]):
        """后台线程：聚合处理一个种子下载的多个文件，生成一条聚合通知。

        同一剧名+季合并为一行，仅显示总大小。
        ask 模式：加入待确认队列，发一条待确认清单。
        silent 模式：逐个上传，发一条完成汇总。
        """
        if not file_paths:
            return

        with self._upload_lock:
            # 1. 逐个识别 + 版本对比
            results: List[dict] = []
            for fp in file_paths:
                try:
                    results.append(self._inspect_file(fp))
                except Exception as e:
                    results.append({"ok": False, "file_name": os.path.basename(fp), "error": str(e)})

            uploadable = [r for r in results if r.get("ok") and not r.get("same_version")]
            skipped = [r for r in results if r.get("ok") and r.get("same_version")]
            failed_id = [r for r in results if not r.get("ok")]

            # 2. ask 模式：入队 + 聚合待确认通知
            if self._upload_mode == "ask":
                if uploadable:
                    for r in uploadable:
                        self._pending_seq += 1
                        r["seq"] = self._pending_seq
                        self._pending_uploads.append({
                            "seq": r["seq"], "file_path": r["file_path"], "file_name": r["file_name"],
                            "file_size": r["file_size"], "item_type": r["item_type"], "item_id": r["item_id"],
                            "name": r["name"], "season": r["season"], "episode": r["episode"],
                        })
                    self._send_notification(self._build_batch_ask_msg(uploadable, skipped, failed_id))
                else:
                    if skipped or failed_id:
                        self._send_notification(self._build_skip_fail_msg(skipped, failed_id))
                return

            # 3. silent 模式：逐个上传 + 聚合汇总
            ok_list: List[str] = []
            fail_list: List[dict] = []
            for r in uploadable:
                ur = self._upload_file(r["file_path"], r["item_type"], r["item_id"])
                if ur.get("error"):
                    fail_list.append({"file_name": r["file_name"], "error": ur.get("error")})
                    continue
                self._record_history(r["file_name"], r["file_size"], ur)
                ok_list.append(r)
            self._send_notification(self._build_batch_summary(uploadable, ok_list, fail_list, skipped, failed_id))

    def _group_lines(self, items: List[dict]) -> List[str]:
        """按 (剧名, 季) 分组，每组合并为一行，仅显示总大小。"""
        groups: Dict[tuple, List[dict]] = {}
        for it in items:
            key = (str(it.get("name", "未知")), it.get("season"))
            groups.setdefault(key, []).append(it)
        lines = []
        for (name, season), its in groups.items():
            total = sum(int(x.get("file_size") or 0) for x in its)
            if season is not None:
                try:
                    season_label = f"S{int(season):02d}"
                except (TypeError, ValueError):
                    season_label = f"S{season}"
                lines.append(f"{name} {season_label}：{self._fmt_size(total)}")
            else:
                lines.append(f"{name}：{self._fmt_size(total)}")
        return lines

    @staticmethod
    def _fmt_size(size: int) -> str:
        """把字节数格式化为易读大小。"""
        try:
            size = float(size or 0)
            gb = size / 1024 / 1024 / 1024
            return f"{gb:.1f}GB" if gb >= 1 else f"{size / 1024 / 1024:.1f}MB"
        except Exception:
            return "0B"

    def _build_batch_ask_msg(self, uploadable, skipped, failed_id) -> str:
        """构造 ask 模式聚合待确认通知（每剧名+季仅一行，只显示总大小）。"""
        lines = self._group_lines(uploadable)
        msg = f"📥 待确认上传（共 {len(uploadable)} 个文件）"
        for ln in lines:
            msg += f"\n{ln}"
        if skipped:
            msg += f"\n⏭️ 跳过 {len(skipped)} 个（已有相同版本）"
        if failed_id:
            for f in failed_id[:5]:
                msg += f"\n❌ 识别失败: {f['file_name']}"
        msg += "\n\n回复确认：\n"
        msg += "  /emos_confirm 传 → 全部上传\n"
        msg += "  /emos_confirm 传 2 → 只传编号2\n"
        msg += "  /emos_confirm 不传 2 → 跳过编号2"
        return msg

    def _build_skip_fail_msg(self, skipped, failed_id) -> str:
        """全部没有可上传文件时的提示。"""
        msg = "⏭️ 本次无可上传文件"
        if skipped:
            msg += f"（{len(skipped)} 个已有相同版本）"
        if failed_id:
            for f in failed_id[:5]:
                msg += f"\n❌ 识别失败: {f['file_name']}"
        return msg

    def _build_batch_summary(self, uploadable, ok_list, fail_list, skipped, failed_id) -> str:
        """构造 silent 模式聚合完成汇总（每剧名+季仅一行，只显示总大小）。"""
        items_ok = [dict(x) for x in ok_list]
        # 分组汇总
        msg = f"✅ 批量上传完成（{len(uploadable)} 个文件）"
        for ln in self._group_lines(items_ok):
            msg += f"\n{ln}"
        if skipped:
            msg += f"⏭️ 跳过 {len(skipped)}（相同版本）"
        if failed_id:
            for f in failed_id[:5]:
                msg += f"\n❌ 识别失败: {f['file_name']}"
        if fail_list:
            for f in fail_list[:5]:
                msg += f"\n❌ 失败: {f['file_name']} {f['error']}"
        return msg

    def _build_version_report(self, video_medias: list) -> str:
        """生成已有资源版本报告文本。"""
        lines = []
        for m in video_medias:
            media_name = m.get("media_name", "")
            remote_size = m.get("media_file_size") or m.get("size") or 0
            remote_res = self._extract_resolution(media_name) or "未知"
            size_gb = remote_size / 1024 / 1024 / 1024 if remote_size else 0
            lines.append(f"  • {remote_res} / {size_gb:.1f}GB")
        return "\n".join(lines)

    def _record_history(self, file_name: str, file_size: int, upload_result: dict):
        """记录上传历史。"""
        entry = {
            "file": file_name,
            "size": f"{file_size / 1024 / 1024:.1f} MB",
            "speed": upload_result.get("speed", "N/A"),
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "result": "✅ 成功",
        }
        self._upload_history.append(entry)
        if len(self._upload_history) > 50:
            self._upload_history = self._upload_history[-50:]

    # ---- EMOS API 封装 ----

    def _req(self, method: str, url: str, data: dict = None, headers: dict = None) -> dict:
        """通用请求方法。"""
        h = {"Authorization": f"Bearer {self._token}", "User-Agent": self._ua}
        if headers:
            h.update(headers)
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            h["Content-Type"] = "application/json"

        r = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                return json.loads(resp.read().decode(errors="replace"))
        except urllib.error.HTTPError as e:
            content = e.read().decode(errors="replace")
            try:
                return json.loads(content)
            except Exception:
                return {"error": content, "status": e.code}
        except Exception as e:
            return {"error": str(e)}

    def _identify_file(self, filename: str) -> dict:
        """通过 EMOS 服务器识别文件信息。"""
        url = f"https://{self._IDENTIFY_BASE}/api/emos/item"
        return self._req("POST", url, {"filename": filename})

    def _check_media_exists(self, item_type: str, item_id: int) -> dict:
        """检查媒体资源是否存在。

        EMOS 该接口通过 URL query 传参（GET 请求），不能放在请求体中。
        """
        if not item_id:
            return {}
        url = (f"https://{self._API_BASE}/api/upload/video/base"
               f"?item_type={item_type}&item_id={item_id}")
        return self._req("GET", url)

    def _extract_resolution(self, filename: str) -> str:
        """从文件名提取分辨率。"""
        patterns = [
            (r'(2160P|4K|UHD)', '2160P'),
            (r'(1080P)', '1080P'),
            (r'(720P)', '720P'),
            (r'(480P)', '480P'),
        ]
        for pattern, normalized in patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return normalized
        return ""

    def _compare_versions(self, local_filename: str, local_size: int, remote_medias: list) -> bool:
        """
        比较本地文件与远程资源版本。

        只比较：1. 分辨率  2. 文件大小（5% 误差）

        返回 True 表示需要上传（版本不同或远程无资源）。
        返回 False 表示不需要上传（已有相同版本）。
        """
        if not remote_medias:
            return True

        local_resolution = self._extract_resolution(local_filename)

        for media in remote_medias:
            remote_name = media.get("media_name", "")
            remote_size = media.get("media_file_size") or media.get("size") or 0

            # 1. 比较分辨率
            remote_resolution = self._extract_resolution(remote_name)
            if local_resolution and remote_resolution:
                if local_resolution != remote_resolution:
                    continue

            # 2. 比较文件大小（允许 5% 误差）
            if remote_size > 0 and local_size > 0:
                size_diff = abs(local_size - remote_size) / remote_size
                if size_diff > 0.05:
                    continue

            return False

        return True

    def _put_part(self, url: str, chunk: bytes, number: int) -> Tuple[int, str]:
        """PUT 一个分片，返回 (number, etag)。"""
        r = urllib.request.Request(url, data=chunk, method="PUT")
        r.add_header("Content-Type", "application/octet-stream")
        r.add_header("User-Agent", self._ua)
        with urllib.request.urlopen(r, timeout=300) as resp:
            etag = resp.headers.get("ETag", "").strip('"')
            return number, etag

    def _upload_file(self, file_path: str, item_type: str, item_id: int) -> dict:
        """上传文件到 EMOS。"""
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}

        fsize = os.path.getsize(file_path)
        fname = os.path.basename(file_path)

        logger.info(f"{self.LOG_TAG}开始上传: {fname} ({fsize / 1024 / 1024:.1f} MB)")

        # 1. 获取上传凭证
        tok = self._req("POST", f"https://{self._API_BASE}/api/upload/getUploadToken", {
            "type": "video",
            "file_type": "video/mp4",
            "file_name": fname,
            "file_size": fsize,
            "file_storage": "zn_r2_upload",
        })

        if tok.get("error") or tok.get("message"):
            return {"error": f"getUploadToken 失败: {json.dumps(tok, ensure_ascii=False)[:500]}"}

        storage_type = tok.get("type", tok.get("storage_type"))
        file_id = tok.get("file_id")

        if storage_type != "multipart":
            return {"error": f"不支持的存储类型: {storage_type}"}

        d = tok.get("data", {})
        part_min = d.get("multipart_size", {}).get("min", 5 * 1024 * 1024)
        part_max = d.get("multipart_size", {}).get("max", 5 * 1024 * 1024 * 1024)

        part_size = max(part_min, min(part_max, math.ceil(fsize / self._target_parts / (1024 * 1024)) * 1024 * 1024))
        part_count = math.ceil(fsize / part_size)

        logger.info(f"{self.LOG_TAG}分片: {part_count} 片 x {part_size / 1024 / 1024:.0f} MB, 并发 {self._concurrency}")

        # 2. 获取分片上传地址
        pres = self._req("POST", f"https://{self._API_BASE}/api/upload/multipart/{file_id}/presign", {
            "number": part_count,
        })

        if isinstance(pres, dict) and pres.get("error"):
            return {"error": f"presign 失败: {json.dumps(pres, ensure_ascii=False)[:500]}"}

        if isinstance(pres, dict) and "presigns" in pres:
            presigns = pres["presigns"]
        elif isinstance(pres, list):
            presigns = pres
        else:
            presigns = pres.get("data", pres.get("items", []))

        logger.info(f"{self.LOG_TAG}拿到 {len(presigns)} 个上传地址")

        # 3. 并发分片上传
        etags = []
        t0 = time.time()
        done = 0
        fd = os.open(file_path, os.O_RDONLY)

        try:
            def worker(p):
                if isinstance(p, dict):
                    number = p.get("number")
                    url = p.get("upload_url") or p.get("presign_url") or p.get("url")
                else:
                    number = None
                    url = p
                offset = (number - 1) * part_size
                chunk = os.pread(fd, part_size, offset)
                return self._put_part(url, chunk, number)

            with ThreadPoolExecutor(max_workers=self._concurrency) as ex:
                futures = {ex.submit(worker, p): p for p in presigns}
                for fut in as_completed(futures):
                    number, etag = fut.result()
                    etags.append({"number": number, "etag": etag})
                    done += 1
                    elapsed = time.time() - t0
                    uploaded = fsize * done / part_count
                    speed = uploaded / elapsed if elapsed > 0 else 0
                    logger.info(f"{self.LOG_TAG}分片 {number}/{part_count} ({elapsed:.0f}s, {speed / 1024 / 1024:.1f} MB/s)")
        finally:
            os.close(fd)

        total_t = time.time() - t0
        speed_str = f"{fsize / 1024 / 1024 / total_t:.2f} MB/s" if total_t > 0 else "N/A"
        logger.info(f"{self.LOG_TAG}分片耗时 {total_t:.0f}s, 平均 {speed_str}")

        # 4. 完成分片合并
        self._req("POST", f"https://{self._API_BASE}/api/upload/multipart/{file_id}/complete", {
            "parts": sorted(etags, key=lambda x: x["number"]),
        })

        # 5. 保存记录
        sv = self._req("POST", f"https://{self._API_BASE}/api/upload/video/save", {
            "item_type": item_type,
            "item_id": int(item_id),
            "file_id": file_id,
        })

        return {
            "success": True,
            "file": fname,
            "size": fsize,
            "speed": speed_str,
            "save_result": sv,
        }

    # ---- 通知 ----

    @staticmethod
    def _normalize_channels(channels: Any) -> List[Any]:
        """将配置的渠道类型字符串列表转换为 MessageChannel 枚举列表。"""
        if not channels:
            return []
        result = []
        seen = set()
        for ch in (channels if isinstance(channels, (list, tuple)) else [channels]):
            ch = str(ch).strip()
            if not ch or ch in seen:
                continue
            seen.add(ch)
            result.append(EmosUpload._NOTIFY_TYPE_MAP.get(ch, ch))
        return result

    def _send_notification(self, message: str):
        """发送通知。

        仅当配置了通知渠道时才发送；未配置（留空）则不发送任何通知。
        """
        if not self._notify_channel:
            return
        try:
            for ch in self._notify_channel:
                self.post_message(title="EMOS上传", text=message, channel=ch)
        except Exception as e:
            logger.error(f"{self.LOG_TAG}发送通知失败: {e}")

    # ---- 命令处理 ----

    @eventmanager.register(EventType.PluginAction)
    def on_plugin_action(self, event: Event):
        """处理插件命令。"""
        event_data = event.event_data or {}
        action = event_data.get("action")

        if action == "emos_status":
            self._handle_status_command()
        elif action == "emos_confirm":
            self._handle_confirm_command(event_data)

    def _handle_confirm_command(self, event_data: dict):
        """处理用户确认命令：/emos_confirm 传 [编号列表] / 不传 [编号列表]"""
        text = event_data.get("text") or event_data.get("content") or ""
        raw = text.strip()

        if not raw:
            self._send_notification("📭 请输入确认指令，例：/emos_confirm 传 / 不传 1")
            return

        # 解析动作
        if "不传" in raw or "跳过" in raw or raw.lower().startswith("skip"):
            do_upload = False
        elif "传" in raw or raw.lower().startswith("up"):
            do_upload = True
            raw = raw.replace("上传", "").replace("传", "")
        else:
            self._send_notification("❌ 无法识别指令。请回复：/emos_confirm 传 [编号] 或 /emos_confirm 不传 [编号]")
            return

        if not self._pending_uploads:
            self._send_notification("📭 当前没有待确认的上传任务")
            return

        # 解析编号列表
        nums = re.findall(r'\d+', raw) if raw else []
        if nums:
            target_nums = set(int(x) for x in nums)
            targets = [n for n in self._pending_uploads if n["seq"] in target_nums]
        else:
            targets = list(self._pending_uploads)

        if not targets:
            self._send_notification("❌ 未找到对应编号的待确认任务。请先 /emos_status 查看待确认列表")
            return

        if do_upload:
            for item in targets:
                upload_result = self._upload_file(item["file_path"], item["item_type"], item["item_id"])
                if upload_result.get("error"):
                    logger.error(f"{self.LOG_TAG}上传失败 [{item['seq']}]: {upload_result.get('error')}")
                    self._send_notification(f"❌ 上传失败 [{item['seq']}] {item['file_name']}\n{upload_result.get('error', '')}")
                    continue
                self._record_history(item["file_name"], item["file_size"], upload_result)
                self._send_notification(
                    f"✅ 上传成功: {item['name']} [{item['seq']}]\n"
                    f"文件: {item['file_name']}\n"
                    f"大小: {item['file_size'] / 1024 / 1024:.1f} MB\n"
                    f"速度: {upload_result.get('speed', 'N/A')}"
                )
            for t in targets:
                if t in self._pending_uploads:
                    self._pending_uploads.remove(t)
        else:
            for t in targets:
                self._send_notification(f"⏭️ 已跳过: {t['file_name']}")
                if t in self._pending_uploads:
                    self._pending_uploads.remove(t)

    def _handle_status_command(self):
        """处理状态查询命令。"""
        status = "✅ 已启用" if self._enabled else "❌ 未启用"
        token_status = "✅ 已配置" if self._token else "❌ 未配置"
        mode = "询问模式" if self._upload_mode == "ask" else "静默模式"

        message = (
            f"📊 EMOS 上传状态\n"
            f"插件: {status}\n"
            f"Token: {token_status}\n"
            f"模式: {mode}\n"
            f"待确认: {len(self._pending_uploads)} 个\n"
            f"历史: {len(self._upload_history)} 条"
        )

        if self._pending_uploads:
            message += "\n\n📥 待确认列表："
            for item in self._pending_uploads:
                message += f"\n[{item['seq']}] {item['name']} {item['file_name']}"

        self._send_notification(message)

    # ---- API 端点 ----

    def _api_status(self):
        """API: 获取插件状态。"""
        return {
            "enabled": self._enabled,
            "token_configured": bool(self._token),
            "upload_mode": self._upload_mode,
            "pending_count": len(self._pending_uploads),
            "pending": self._pending_uploads,
            "history_count": len(self._upload_history),
            "history": self._upload_history[-10:],
        }

    def _api_pending(self):
        """API: 获取待确认列表。"""
        return {
            "pending_count": len(self._pending_uploads),
            "pending": self._pending_uploads,
        }