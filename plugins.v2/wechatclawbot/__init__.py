import base64
from collections import deque
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from app.chain.message import MessageChain
from app.command import Command
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.db.message_oper import MessageOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import CommingMessage, MessageResponse, Notification
from app.schemas.types import EventType, MessageChannel
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from fastapi.responses import Response

from .ilink import ILinkClient, ILinkIncomingMessage


class WechatClawBot(_PluginBase):
    """WeChat-ClawBot 插件（纯插件实现，不修改系统模块）。"""

    plugin_name = "WeChat-ClawBot"
    plugin_desc = (
        "基于 OpenClaw/ClawBot 协议接入个人微信，支持扫码登录、消息通知转发与命令控制。"
    )
    plugin_version = "0.2.1"
    plugin_author = "mijjjj"
    author_url = "https://github.com/mijjjj/MoviePilot-Plugins-WeChat-ClawBot"
    plugin_label = "微信,消息通知,clawBot"
    plugin_icon = "Wechat_A.png"
    plugin_order = 60

    _CREDENTIALS_KEY = "credentials"
    _QRCODE_KEY = "qrcode"
    _QRCODE_COMMAND = "/wechatclawbot_qrcode"
    _MAX_LOG_ITEMS = 1000
    _QRCODE_REFRESH_HINT_SECONDS = 5
    _LOGIN_WATCH_SECONDS = 240
    _LOGIN_WATCH_INTERVAL_SECONDS = 3
    _MAX_API_RETRY_FAILURES = 10

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._config: Dict[str, Any] = {}
        self._client: Optional[ILinkClient] = None

        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()
        self._lock = threading.Lock()
        self._logs = deque(maxlen=self._MAX_LOG_ITEMS)
        self._logs_lock = threading.Lock()
        self._qrcode_prepare_thread: Optional[threading.Thread] = None
        self._qrcode_prepare_started_at: int = 0
        self._qrcode_prepare_lock = threading.Lock()
        self._command_login_wait_threads: Dict[str, threading.Thread] = {}
        self._command_login_wait_lock = threading.Lock()

    def _log(self, level: str, message: str):
        """记录插件日志到内存并输出到全局日志。"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            "time": timestamp,
            "level": (level or "INFO").upper(),
            "message": str(message),
        }
        with self._logs_lock:
            self._logs.append(entry)

        msg = f"[WechatClawBot] {message}"
        lv = (level or "info").lower()
        if lv == "debug":
            logger.debug(msg)
        elif lv == "warning":
            logger.warning(msg)
        elif lv == "error":
            logger.error(msg)
        else:
            logger.info(msg)

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "enabled": False,
            "base_url": "https://ilinkai.weixin.qq.com",
            "force_generate_qrcode": False,
            "admins": "",
            "notify_enabled": True,
            "notify_types": [],
            "command_enabled": True,
            "poll_timeout": 25,
            "reconnect_delay": 3,
        }

    def init_plugin(self, config: dict = None):
        cfg = self._default_config()
        if config:
            cfg.update(config)

        force_generate = bool(cfg.get("force_generate_qrcode"))
        if force_generate:
            # 强制生码开关按“一次性按钮”处理，执行后自动复位。
            cfg["force_generate_qrcode"] = False
            self.update_config(cfg)

        self._config = cfg
        self._log("info", "插件配置已加载")

        self.stop_service()
        self._enabled = bool(cfg.get("enabled"))
        if not self._enabled:
            self._log("info", "插件未启用")
            return

        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        token = creds.get("bot_token")
        if token:
            self._client = ILinkClient(
                base_url=creds.get("base_url") or cfg.get("base_url"),
                bot_token=token,
                account_id=creds.get("account_id"),
                sync_buf=creds.get("sync_buf"),
                log_func=self._log,
            )
            self._start_polling()
            self._log("info", "检测到历史 token，启动轮询")
        else:
            self._log("info", "未检测到历史 token，等待扫码登录")

        if force_generate or not token:
            self._trigger_qrcode_prepare(force=force_generate, reason="init_plugin")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": WechatClawBot._QRCODE_COMMAND,
                "event": EventType.PluginAction,
                "desc": "获取 WeChat-ClawBot 登录二维码",
                "category": "插件",
                "data": {
                    "plugin_id": "WechatClawBot",
                    "action": "get_qrcode",
                },
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/qrcode",
                "endpoint": self.get_qrcode,
                "methods": ["GET"],
                "summary": "获取 WeChat-ClawBot 登录二维码",
            },
            {
                "path": "/qrcode/image",
                "endpoint": self.get_qrcode_image,
                "methods": ["GET"],
                "summary": "获取 WeChat-ClawBot 登录二维码图片",
                "allow_anonymous": True,
            },
            {
                "path": "/status",
                "endpoint": self.get_status,
                "methods": ["GET"],
                "summary": "获取 WeChat-ClawBot 登录状态",
            },
            {
                "path": "/logout",
                "endpoint": self.logout,
                "methods": ["POST"],
                "summary": "退出 WeChat-ClawBot 登录",
            },
            {
                "path": "/test_connection",
                "endpoint": self.test_connection_api,
                "methods": ["GET"],
                "summary": "测试 WeChat-ClawBot 连接",
            },
            {
                "path": "/logs",
                "endpoint": self.get_logs,
                "methods": ["GET"],
                "summary": "获取 WeChat-ClawBot 插件日志",
            },
            {
                "path": "/logs/clear",
                "endpoint": self.clear_logs,
                "methods": ["POST"],
                "summary": "清空 WeChat-ClawBot 插件日志",
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    # ── 行1：启用开关 + 强制生码开关 ──────────────────────────
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
                                            "label": "启用 WeChat-ClawBot",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "force_generate_qrcode",
                                            "label": "保存时强制刷新登录二维码",
                                            "hint": "开启后保存配置会立即刷新二维码，随后自动关闭该开关。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 行2：命令控制 + 通知转发开关 ──────────────────────────
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
                                            "model": "command_enabled",
                                            "label": "允许微信命令控制",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify_enabled",
                                            "label": "启用系统通知转发",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 行3：轮询超时 + 重连间隔 ──────────────────────────────
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
                                            "model": "poll_timeout",
                                            "label": "轮询超时（秒）",
                                            "type": "number",
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
                                            "model": "reconnect_delay",
                                            "label": "重连间隔（秒）",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 行4：ClawBot Base URL（全宽）─────────────────────────
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
                                            "model": "base_url",
                                            "label": "ClawBot Base URL",
                                            "placeholder": "https://ilinkai.weixin.qq.com",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    # ── 行5：管理员用户ID（全宽）─────────────────────────────
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
                                            "model": "admins",
                                            "label": "管理员用户ID（逗号分隔）",
                                            "rows": 2,
                                            "placeholder": "多个ID用英文逗号分隔",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    # ── 行6：使用说明提示 ─────────────────────────────────────
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
                                            "text": (
                                                "启用插件后，请前往插件详情页扫码登录微信。"
                                                "如需重新登录，可开启「保存时强制刷新登录二维码」后保存配置，或在详情页刷新二维码。"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], self._default_config()

    def get_page(self) -> List[dict]:
        # 详情页只读取缓存状态，避免阻塞页面渲染。
        status = self._build_status()
        connected = bool(status.get("connected"))
        qrcode_image_src = status.get("qrcode_image_src")

        preparing = False
        elapsed = 0
        if self._enabled and not connected:
            qrcode = self.get_data(self._QRCODE_KEY) or {}
            need_prepare = (not qrcode.get("qrcode")) or self._qrcode_expired(
                qrcode.get("updated_at")
            )
            self._trigger_qrcode_prepare(force=need_prepare, reason="page_open")
            preparing, elapsed = self._qrcode_prepare_state()

        status_lines = [
            f"启用状态：{'已启用' if status.get('enabled') else '未启用'}",
            f"连接状态：{'已连接' if connected else '未连接'}",
            f"账号ID：{status.get('account_id') or '-'}",
            f"已互动用户数：{status.get('known_users') or 0}",
            f"二维码状态：{status.get('qrcode_status') or 'waiting'}",
        ]
        if preparing:
            status_lines.append("二维码任务：生成中")

        # ── 状态信息行 ─────────────────────────────────────────────────────
        content: List[dict] = [
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
                                    "type": "success" if connected else "info",
                                    "variant": "tonal",
                                    "text": "\n".join(status_lines),
                                    "style": "white-space: pre-line;",
                                },
                            }
                        ],
                    }
                ],
            }
        ]

        if not self._enabled:
            content.append(
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
                                        "type": "warning",
                                        "variant": "outlined",
                                        "text": "请先在插件配置中启用 WeChat-ClawBot 并保存，然后返回此页扫码登录。",
                                    },
                                }
                            ],
                        }
                    ],
                }
            )
            return [
                {
                    "component": "VCard",
                    "props": {
                        "title": "WeChat-ClawBot 登录",
                        "variant": "outlined",
                    },
                    "content": content,
                }
            ]

        if not connected:
            refresh_after = self._QRCODE_REFRESH_HINT_SECONDS
            if preparing:
                refresh_after = max(1, self._QRCODE_REFRESH_HINT_SECONDS - elapsed)

            # ── 扫码提示行 ─────────────────────────────────────────────────
            content.append(
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
                                        "type": "warning",
                                        "variant": "outlined",
                                        "text": (
                                            "请使用微信扫一扫下方二维码完成登录。\n"
                                            f"若二维码未显示或已失效，请在约 {refresh_after} 秒后刷新本页面。"
                                        ),
                                    },
                                }
                            ],
                        }
                    ],
                }
            )

            if qrcode_image_src:
                # ── 二维码图片居中行 ───────────────────────────────────────
                content.append(
                    {
                        "component": "VRow",
                        "props": {"justify": "center"},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": "auto"},
                                "content": [
                                    {
                                        "component": "VImg",
                                        "props": {
                                            "src": qrcode_image_src,
                                            "width": 280,
                                            "height": 280,
                                            "maxWidth": 280,
                                            "aspectRatio": 1,
                                            "cover": False,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                )
            elif preparing:
                content.append(
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
                                            "variant": "outlined",
                                            "text": f"二维码正在后台生成中，请在约 {refresh_after} 秒后刷新本页面。",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                )
            else:
                content.append(
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
                                            "type": "error",
                                            "variant": "outlined",
                                            "text": "二维码暂不可用，请检查 iLink 服务后刷新页面重试。",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                )

        return [
            {
                "component": "VCard",
                "props": {
                    "title": "WeChat-ClawBot 登录",
                    "variant": "outlined",
                },
                "content": content,
            }
        ]
        if preparing:
            status_lines.append("二维码任务: 生成中")

        content: List[dict] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "success" if connected else "info",
                    "variant": "tonal",
                    "text": "\n".join(status_lines),
                },
            }
        ]

        if not self._enabled:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "warning",
                        "variant": "outlined",
                        "text": "请先在插件配置中启用 WeChat-ClawBot 并保存，然后返回此页扫码登录。",
                    },
                }
            )
            return [
                {
                    "component": "VCard",
                    "props": {
                        "title": "WeChat-ClawBot 登录",
                        "variant": "outlined",
                    },
                    "content": content,
                }
            ]

        if not connected:
            refresh_after = self._QRCODE_REFRESH_HINT_SECONDS
            if preparing:
                refresh_after = max(1, self._QRCODE_REFRESH_HINT_SECONDS - elapsed)
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "warning",
                        "variant": "outlined",
                        "text": (
                            "请使用微信扫一扫下方二维码完成登录。\n"
                            f"若二维码未显示或已失效，请在约 {refresh_after} 秒后刷新本页面。"
                        ),
                    },
                }
            )

            if qrcode_image_src:
                content.append(
                    {
                        "component": "VImg",
                        "props": {
                            "src": qrcode_image_src,
                            "width": 280,
                            "height": 280,
                            "maxWidth": 280,
                            "aspectRatio": 1,
                            "cover": False,
                        },
                    }
                )
            elif preparing:
                content.append(
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "outlined",
                            "text": f"二维码正在后台生成中，请在约 {refresh_after} 秒后刷新本页面。",
                        },
                    }
                )
            else:
                content.append(
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "error",
                            "variant": "outlined",
                            "text": "二维码暂不可用，请检查 iLink 服务后刷新页面重试。",
                        },
                    }
                )

        return [
            {
                "component": "VCard",
                "props": {
                    "title": "WeChat-ClawBot 登录",
                    "variant": "outlined",
                },
                "content": content,
            }
        ]

    def get_module(self) -> Dict[str, Any]:
        # 仅接管列表类回包，普通通知通过 NoticeMessage 事件处理，
        # 避免劫持系统通用 post_message 链路。
        return {
            "post_medias_message": self._module_post_medias_message,
            "post_torrents_message": self._module_post_torrents_message,
            "send_direct_message": self._module_send_direct_message,
        }

    def stop_service(self):
        self._poll_stop.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=3)
        self._poll_thread = None
        self._log("info", "轮询服务已停止")

    def _invalidate_token(self, reason: str, force_qrcode: bool = True) -> bool:
        """判定 token 失效并清理登录凭据。"""
        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        old_token = creds.get("bot_token")
        if not old_token:
            return False

        self._save_credentials(
            bot_token=None,
            account_id=None,
            sync_buf=None,
            user_login_tokens={},
        )
        self._client = None
        self._poll_stop.set()
        self._log("warning", f"{reason}，已判定当前 token 失效并自动清理")

        if self._enabled and force_qrcode:
            self._trigger_qrcode_prepare(force=True, reason="token_invalid")
        return True

    def get_logs(self, limit: int = 200, level: Optional[str] = None):
        """获取插件日志。"""
        try:
            limit = int(limit)
        except Exception:
            limit = 200
        limit = max(1, min(limit, self._MAX_LOG_ITEMS))

        with self._logs_lock:
            logs = list(self._logs)

        if level:
            level_value = level.upper().strip()
            logs = [item for item in logs if item.get("level") == level_value]

        return {
            "success": True,
            "count": len(logs),
            "logs": logs[-limit:],
        }

    def clear_logs(self):
        """清空插件日志。"""
        with self._logs_lock:
            self._logs.clear()
        self._log("info", "插件日志已清空")
        return {"success": True}

    def _ensure_client(self) -> ILinkClient:
        if self._client:
            return self._client
        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        self._client = ILinkClient(
            base_url=creds.get("base_url") or self._config.get("base_url"),
            bot_token=creds.get("bot_token"),
            account_id=creds.get("account_id"),
            sync_buf=creds.get("sync_buf"),
            timeout=20,
            log_func=self._log,
        )
        return self._client

    def _save_credentials(self, **kwargs) -> None:
        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        creds.update(kwargs)
        creds.setdefault("known_users", [])
        creds.setdefault("user_last_active", {})
        creds.setdefault("user_context_tokens", {})
        creds.setdefault("user_login_tokens", {})
        self.save_data(self._CREDENTIALS_KEY, creds)

    def _build_status(self) -> Dict[str, Any]:
        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        qrcode = self.get_data(self._QRCODE_KEY) or {}

        qrcode_id = qrcode.get("qrcode")
        qrcode_url = qrcode.get("qrcode_url")
        if not qrcode_url and qrcode_id:
            qrcode_url = self._compose_qrcode_url(qrcode_id)

        qrcode_image_src = qrcode.get("qrcode_image_src")
        if not qrcode_image_src and qrcode_id:
            qrcode_image_src = self._compose_qrcode_image_api_url(
                qrcode.get("updated_at")
            )

        return {
            "enabled": self._enabled,
            "connected": bool(creds.get("bot_token")),
            "account_id": creds.get("account_id"),
            "known_users": len(creds.get("known_users") or []),
            "qrcode": qrcode_id,
            "qrcode_status": qrcode.get("status"),
            "qrcode_url": qrcode_url,
            "qrcode_image_src": qrcode_image_src,
        }

    @staticmethod
    def _compose_qrcode_url(qrcode: str) -> str:
        """由 qrcode id 组装可扫码链接。"""
        return f"https://liteapp.weixin.qq.com/q/7GiQu1?qrcode={qrcode}&bot_type=3"

    def _compose_qrcode_image_api_url(self, updated_at: Optional[int] = None) -> str:
        """详情页二维码图片使用插件匿名 API 渲染，避免前端直接加载网页链接。"""
        suffix = f"?ts={int(updated_at)}" if updated_at else ""
        return f"/api/v1/plugin/{self.__class__.__name__}/qrcode/image{suffix}"

    @staticmethod
    def _qrcode_expired(updated_at: Optional[int], ttl_seconds: int = 240) -> bool:
        """二维码有效期较短，详情页打开时按时间窗口自动刷新。"""
        if not updated_at:
            return True
        return (int(time.time()) - int(updated_at)) > ttl_seconds

    def _qrcode_prepare_state(self) -> Tuple[bool, int]:
        with self._qrcode_prepare_lock:
            if self._qrcode_prepare_thread and self._qrcode_prepare_thread.is_alive():
                elapsed = max(
                    0, int(time.time()) - int(self._qrcode_prepare_started_at or 0)
                )
                return True, elapsed
        return False, 0

    def _trigger_qrcode_prepare(self, force: bool = False, reason: str = "page"):
        with self._qrcode_prepare_lock:
            if self._qrcode_prepare_thread and self._qrcode_prepare_thread.is_alive():
                return

            self._qrcode_prepare_started_at = int(time.time())
            self._qrcode_prepare_thread = threading.Thread(
                target=self._qrcode_prepare_worker,
                kwargs={"force": force, "reason": reason},
                daemon=True,
            )
            self._qrcode_prepare_thread.start()

    def _qrcode_prepare_worker(self, force: bool = False, reason: str = "page"):
        try:
            self._log("info", f"后台二维码任务启动: reason={reason}, force={force}")
            qr = self._ensure_qrcode(force=force)
            if qr.get("success"):
                self._log("info", "后台二维码任务完成")
                self._watch_login_status(reason=reason)
            else:
                self._log(
                    "warning",
                    f"后台二维码任务失败: {qr.get('message') or 'unknown error'}",
                )
        except Exception as err:
            self._log("error", f"后台二维码任务异常: {err}")

    def _watch_login_status(self, reason: str = "page"):
        """二维码生成后短时观察扫码状态，扫码成功即启动消息轮询。"""
        if not self._enabled:
            return

        status = self._build_status()
        if status.get("connected"):
            return

        qrcode = self.get_data(self._QRCODE_KEY) or {}
        if not qrcode.get("qrcode"):
            return

        self._log("debug", f"后台登录状态监听启动: reason={reason}")
        result = self._wait_for_login_status(reason=reason)
        if result.get("connected"):
            self._log("info", "后台登录状态监听：检测到已登录")
            return

        qr_state = str(result.get("status") or "").lower()
        if qr_state in {
            "expired",
            "timeout",
            "canceled",
            "cancelled",
            "not_initialized",
        }:
            self._log("warning", f"后台登录状态监听结束: qrcode_status={qr_state}")
            return
        if qr_state == "watch_timeout":
            self._log("debug", "后台登录状态监听结束: 观察超时")
            return
        if qr_state == "error":
            self._log(
                "warning",
                f"后台登录状态监听异常: {result.get('message') or 'unknown error'}",
            )
            return

        self._log("debug", f"后台登录状态监听结束: status={qr_state or 'unknown'}")

    def _wait_for_login_status(
        self,
        reason: str = "page",
        timeout_seconds: Optional[int] = None,
        interval_seconds: Optional[int] = None,
        expected_qrcode: Optional[str] = None,
        require_qrcode_scan: bool = False,
    ) -> Dict[str, Any]:
        """轮询登录状态直到成功、终止状态或超时。"""
        timeout = int(timeout_seconds or self._LOGIN_WATCH_SECONDS)
        interval = max(1, int(interval_seconds or self._LOGIN_WATCH_INTERVAL_SECONDS))
        max_failures = self._MAX_API_RETRY_FAILURES
        retry_failures = 0

        if timeout <= 0:
            timeout = self._LOGIN_WATCH_SECONDS

        status = self._build_status()
        if status.get("connected") and not require_qrcode_scan:
            return {"connected": True, "status": "connected", **status}

        qrcode = self.get_data(self._QRCODE_KEY) or {}
        qrcode_id = qrcode.get("qrcode")
        if not qrcode_id:
            return {"connected": False, "status": "not_initialized", **status}
        if expected_qrcode and str(qrcode_id) != str(expected_qrcode):
            return {"connected": False, "status": "replaced", **status}

        started_at = time.time()
        self._log("debug", f"登录状态等待启动: reason={reason}, timeout={timeout}s")

        while self._enabled and (time.time() - started_at) < timeout:
            if expected_qrcode:
                current_qrcode = (self.get_data(self._QRCODE_KEY) or {}).get("qrcode")
                if current_qrcode and str(current_qrcode) != str(expected_qrcode):
                    return {
                        "connected": False,
                        "status": "replaced",
                        **self._build_status(),
                    }

            try:
                result = self.get_status(force_qrcode_check=require_qrcode_scan)
            except Exception as err:
                retry_failures += 1
                self._log(
                    "warning",
                    f"登录状态接口异常，重试 {retry_failures}/{max_failures}: {err}",
                )
                if retry_failures >= max_failures:
                    self._invalidate_token(
                        reason=f"登录状态接口连续异常重试超过 {max_failures} 次",
                        force_qrcode=False,
                    )
                    return {
                        "connected": False,
                        "status": "error",
                        "message": f"登录状态接口连续异常重试超过 {max_failures} 次",
                        **self._build_status(),
                    }
                time.sleep(interval)
                continue

            qr_state = str(
                result.get("qrcode_status") or result.get("status") or ""
            ).lower()
            if not result.get("success") and qr_state not in {
                "expired",
                "timeout",
                "canceled",
                "cancelled",
                "not_initialized",
            }:
                retry_failures += 1
                self._log(
                    "warning",
                    f"登录状态接口返回异常结果，重试 {retry_failures}/{max_failures}: status={qr_state or 'unknown'}",
                )
                if retry_failures >= max_failures:
                    self._invalidate_token(
                        reason=f"登录状态接口连续异常重试超过 {max_failures} 次",
                        force_qrcode=False,
                    )
                    return {
                        "connected": False,
                        "status": "error",
                        "message": f"登录状态接口连续异常重试超过 {max_failures} 次",
                        **self._build_status(),
                    }
                time.sleep(interval)
                continue

            retry_failures = 0

            if result.get("connected"):
                return {"connected": True, "status": "connected", **result}

            if qr_state in {
                "expired",
                "timeout",
                "canceled",
                "cancelled",
                "not_initialized",
            }:
                return {"connected": False, "status": qr_state, **result}

            time.sleep(interval)

        if not self._enabled:
            return {"connected": False, "status": "disabled", **self._build_status()}
        return {"connected": False, "status": "watch_timeout", **self._build_status()}

    @staticmethod
    def _decode_data_image(data_image: str) -> Tuple[Optional[bytes], str]:
        if not data_image or not data_image.startswith("data:image/"):
            return None, "image/png"

        try:
            header, raw = data_image.split(",", 1)
            media_type = "image/png"
            if ":" in header and ";" in header:
                media_type = header.split(":", 1)[1].split(";", 1)[0] or media_type
            return base64.b64decode(raw), media_type
        except Exception:
            return None, "image/png"

    def _fetch_qrcode_png(self, qr_text: str) -> Optional[bytes]:
        if not qr_text:
            return None

        image_sources = [
            f"https://api.qrserver.com/v1/create-qr-code/?size=320x320&format=png&data={quote_plus(qr_text)}",
            f"https://quickchart.io/qr?size=320&margin=1&text={quote_plus(qr_text)}",
        ]

        for source in image_sources:
            try:
                resp = RequestUtils(timeout=15).get_res(source)
                if not resp or resp.status_code != 200:
                    continue
                content_type = (resp.headers.get("Content-Type") or "").lower()
                if "image" not in content_type:
                    continue
                if resp.content:
                    return resp.content
            except Exception:
                continue

        return None

    def get_qrcode_image(self, force: bool = False):
        if force:
            self._ensure_qrcode(force=True)

        qrcode = self.get_data(self._QRCODE_KEY) or {}
        raw = qrcode.get("qrcode_url")
        qrcode_id = qrcode.get("qrcode")
        if not raw and qrcode_id:
            raw = self._compose_qrcode_url(str(qrcode_id))

        if not raw:
            return Response(
                content=b"qrcode not ready", media_type="text/plain", status_code=404
            )

        if str(raw).startswith("data:image/"):
            decoded, media_type = self._decode_data_image(str(raw))
            if decoded:
                return Response(
                    content=decoded,
                    media_type=media_type,
                    headers={
                        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"
                    },
                )

        img = self._fetch_qrcode_png(str(raw))
        if not img:
            return Response(
                content=b"qrcode image build failed",
                media_type="text/plain",
                status_code=502,
            )

        return Response(
            content=img,
            media_type="image/png",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    def _prepare_qrcode_for_page(self) -> Dict[str, Any]:
        """详情页展示前，尽可能准备好可显示的二维码和登录状态。"""
        status = self._build_status()
        if status.get("connected"):
            return status

        if not self._enabled:
            return status

        qrcode = self.get_data(self._QRCODE_KEY) or {}
        need_new_qr = not qrcode.get("qrcode") or self._qrcode_expired(
            qrcode.get("updated_at")
        )

        if need_new_qr:
            qr = self._ensure_qrcode(force=True)
            if qr.get("success"):
                status = self._build_status()
        else:
            # 已有二维码时尝试刷新一次状态，便于扫码后详情页立刻反映连接结果
            st = self.get_status()
            if st.get("success") or st.get("status"):
                status = self._build_status()

        return status

    def _ensure_qrcode(self, force: bool = False) -> Dict[str, Any]:
        """在可复用时优先返回现有二维码，必要时重新生成。"""
        qrcode = self.get_data(self._QRCODE_KEY) or {}
        if (
            not force
            and qrcode.get("qrcode")
            and not self._qrcode_expired(qrcode.get("updated_at"))
        ):
            qrcode_id = qrcode.get("qrcode")
            qrcode_url = qrcode.get("qrcode_url")
            if not qrcode_url and qrcode_id:
                qrcode["qrcode_url"] = self._compose_qrcode_url(str(qrcode_id))
            if not qrcode.get("qrcode_image_src") and qrcode_id:
                qrcode["qrcode_image_src"] = self._compose_qrcode_image_api_url(
                    qrcode.get("updated_at")
                )
            self.save_data(self._QRCODE_KEY, qrcode)
            return {"success": True, "reused": True, **qrcode}

        qr = self.get_qrcode()
        if qr.get("success"):
            qr["reused"] = False
        return qr

    def get_qrcode(self):
        self._log("info", "开始请求二维码")
        client = ILinkClient(base_url=self._config.get("base_url"), log_func=self._log)
        qr = client.get_qrcode()
        if not qr.get("success"):
            self._log(
                "warning", f"获取二维码失败: {qr.get('message') or 'unknown error'}"
            )
            return qr

        qrcode_id = qr.get("qrcode")
        qrcode_url = qr.get("qrcode_url")
        if not qrcode_url and qrcode_id:
            qrcode_url = self._compose_qrcode_url(str(qrcode_id))

        now_ts = int(time.time())
        payload = {
            "qrcode": qrcode_id,
            "qrcode_url": qrcode_url,
            "qrcode_image_src": self._compose_qrcode_image_api_url(now_ts),
            "status": "waiting",
            "updated_at": now_ts,
        }
        self.save_data(self._QRCODE_KEY, payload)
        self._log("info", f"二维码获取成功: has_url={bool(qrcode_url)}")
        return {"success": True, **payload}

    def get_status(self, force_qrcode_check: bool = False):
        qrcode = self.get_data(self._QRCODE_KEY) or {}
        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        previous_status = qrcode.get("status")

        if creds.get("bot_token") and not force_qrcode_check:
            return {"success": True, "status": "connected", **self._build_status()}

        qrcode_id = qrcode.get("qrcode")
        if not qrcode_id:
            self._log("warning", "状态查询失败：二维码尚未初始化")
            return {
                "success": False,
                "status": "not_initialized",
                **self._build_status(),
            }

        client = ILinkClient(base_url=self._config.get("base_url"), log_func=self._log)
        status = client.get_qrcode_status(str(qrcode_id))
        current_status = status.get("status")
        qrcode["status"] = current_status
        qrcode["updated_at"] = int(time.time())
        self.save_data(self._QRCODE_KEY, qrcode)

        token = status.get("token")
        if token:
            resolved_base_url = status.get("base_url") or self._config.get("base_url")
            self._save_credentials(
                bot_token=token,
                account_id=status.get("account_id"),
                base_url=resolved_base_url,
                sync_buf=None,
            )
            self._client = ILinkClient(
                base_url=resolved_base_url,
                bot_token=token,
                account_id=status.get("account_id"),
                log_func=self._log,
            )
            self._start_polling()
            self._log("info", "扫码登录成功，轮询已启动")
        else:
            if current_status != previous_status:
                self._log("debug", f"扫码状态: {current_status}")

        merged_status = self._build_status()
        if force_qrcode_check and not token:
            merged_status["connected"] = False
        return {"success": bool(status.get("success")), **merged_status}

    def logout(self):
        self.stop_service()
        self._client = None
        self.del_data(self._CREDENTIALS_KEY)
        self.del_data(self._QRCODE_KEY)
        self._log("info", "已退出登录并清理凭据")
        return {"success": True, "message": "已退出 WeChat-ClawBot 登录"}

    def test_connection_api(self):
        ok, message = self.test_connection()
        return {"success": ok, "message": message, **self._build_status()}

    def test_connection(self) -> Tuple[bool, str]:
        client = self._ensure_client()
        return client.test_connection()

    def _start_polling(self):
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        self._log("info", "后台轮询线程已启动")

    def _poll_loop(self):
        backoff = [1, 2, 5, 10, 30]
        attempt = 0
        max_failures = self._MAX_API_RETRY_FAILURES
        while not self._poll_stop.is_set() and self._enabled:
            try:
                client = self._ensure_client()
                timeout = int(self._config.get("poll_timeout") or 25)
                messages, sync_buf, result = client.poll_updates(
                    timeout_seconds=timeout
                )
                if sync_buf is not None:
                    self._save_credentials(sync_buf=sync_buf)

                if not result.get("success"):
                    raise RuntimeError(result.get("message") or "poll failed")

                for msg in messages:
                    self._handle_incoming(msg)

                attempt = 0
            except Exception as err:
                attempt += 1
                if attempt >= max_failures:
                    self._log(
                        "error",
                        f"轮询接口连续异常重试超过 {max_failures} 次，准备清理 token",
                    )
                    self._invalidate_token(
                        reason=f"轮询接口连续异常重试超过 {max_failures} 次"
                    )
                    break
                delay = backoff[min(max(attempt - 1, 0), len(backoff) - 1)]
                self._log("warning", f"轮询异常，{delay}s 后重试: {err}")
                self._poll_stop.wait(delay)

    def _is_admin(self, user_id: str) -> bool:
        admins = str(self._config.get("admins") or "").strip()
        if not admins:
            return True
        admin_list = [x.strip() for x in admins.split(",") if x.strip()]
        return str(user_id) in admin_list

    def _touch_user(self, user_id: str, context_token: Optional[str] = None):
        with self._lock:
            creds = self.get_data(self._CREDENTIALS_KEY) or {}
            known_users = creds.get("known_users") or []
            if user_id not in known_users:
                known_users.append(user_id)
            user_last_active = creds.get("user_last_active") or {}
            user_last_active[user_id] = int(time.time())
            user_context_tokens = creds.get("user_context_tokens") or {}
            if context_token:
                user_context_tokens[user_id] = str(context_token)
            self._save_credentials(
                known_users=known_users,
                user_last_active=user_last_active,
                user_context_tokens=user_context_tokens,
            )

    def _update_user_login_token(self, user_id: str) -> bool:
        user_id = str(user_id or "").strip()
        if not user_id:
            return False

        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        bot_token = creds.get("bot_token")
        if not bot_token:
            return False

        known_users = creds.get("known_users") or []
        if user_id not in known_users:
            known_users.append(user_id)

        user_last_active = creds.get("user_last_active") or {}
        user_last_active[user_id] = int(time.time())

        user_login_tokens = creds.get("user_login_tokens") or {}
        user_login_tokens[user_id] = str(bot_token)

        self._save_credentials(
            known_users=known_users,
            user_last_active=user_last_active,
            user_login_tokens=user_login_tokens,
        )
        return True

    def _get_user_context_token(self, user_id: str) -> Optional[str]:
        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        tokens = creds.get("user_context_tokens") or {}
        token = tokens.get(str(user_id))
        return str(token) if token else None

    def _active_users(self) -> List[str]:
        creds = self.get_data(self._CREDENTIALS_KEY) or {}
        known_users = creds.get("known_users") or []
        user_last_active = creds.get("user_last_active") or {}
        now = datetime.now()
        active = []
        for user_id in known_users:
            ts = user_last_active.get(user_id)
            if not ts:
                continue
            dt = datetime.fromtimestamp(ts)
            if now - dt <= timedelta(hours=24):
                active.append(user_id)
        return active

    def _record_incoming_message(self, msg: ILinkIncomingMessage, text: str):
        """将入站微信消息写入 MoviePilot 消息记录（action=0）。"""
        try:
            note = {
                "username": msg.username,
                "message_id": msg.message_id,
                "chat_id": msg.chat_id,
                "context_token": msg.context_token,
            }
            MessageOper().add(
                channel=MessageChannel.Wechat,
                source=self.__class__.__name__,
                title="微信入站消息",
                text=text,
                userid=str(msg.user_id),
                action=0,
                note=note,
            )
        except Exception as err:
            self._log("warning", f"入站消息写入记录失败: {err}")

    def _is_plugin_command(self, text: str) -> bool:
        """判断是否为插件内置命令（需要插件自行处理）。"""
        if not text or not text.startswith("/"):
            return False
        cmd = text.split()[0].strip().lower()
        return cmd == self._QRCODE_COMMAND.lower()

    def _dispatch_to_official_message_chain(
        self, msg: ILinkIncomingMessage, text: str
    ) -> bool:
        """将入站消息转交官方微信消息处理链，保持与默认微信通道一致。"""
        try:
            MessageChain().handle_message(
                channel=MessageChannel.Wechat,
                source=self.__class__.__name__,
                userid=str(msg.user_id),
                username=str(msg.username or msg.user_id),
                text=text,
                original_message_id=msg.message_id,
                original_chat_id=msg.chat_id,
                images=None,
            )
            self._log("info", f"消息已转交官方微信链路处理: user={msg.user_id}")
            return True
        except Exception as err:
            self._log("error", f"转交官方微信链路失败: user={msg.user_id}, err={err}")
            return False

    def _send_direct_reply_for_ilink_user(
        self, source: str, userid: Any, title: str, text: str
    ) -> bool:
        """当命令来自 WeChat-ClawBot 用户时，直接回包，避免链路差异导致漏回。"""
        if source != self.__class__.__name__:
            return False
        if userid in (None, ""):
            return False

        payload = "\n".join([p for p in [title, text] if p]).strip()
        if not payload:
            return False

        sent = self._send_text_with_retry(str(userid), payload)
        if sent:
            self._log("info", f"命令结果已直发 WeChat-ClawBot 用户: user={userid}")
        return sent

    def _send_qrcode_image_for_ilink_user(
        self, source: str, userid: Any, qrcode_url: Optional[str]
    ) -> bool:
        """给 WeChat-ClawBot 用户直发二维码图片（非链接）。"""
        if source != self.__class__.__name__:
            return False
        if userid in (None, ""):
            return False

        qrcode_value = qrcode_url
        if not qrcode_value:
            qrcode = self.get_data(self._QRCODE_KEY) or {}
            qrcode_value = qrcode.get("qrcode_url")
            if not qrcode_value and qrcode.get("qrcode"):
                qrcode_value = self._compose_qrcode_url(str(qrcode.get("qrcode")))

        if not qrcode_value:
            self._log("warning", f"二维码图片发送失败：qrcode_url 为空, user={userid}")
            return False

        image_bytes = self._fetch_qrcode_png(str(qrcode_value))
        if not image_bytes:
            self._log("warning", f"二维码图片发送失败：二维码渲染失败, user={userid}")
            return False

        client = self._ensure_client()
        context_token = self._get_user_context_token(str(userid))
        sent = client.send_image_png(
            str(userid), image_bytes, context_token=context_token
        )
        if sent:
            self._log("info", f"二维码图片已发送: user={userid}")
        return sent

    def _handle_incoming(self, msg: ILinkIncomingMessage):
        text = (msg.text or "").strip()
        if not text:
            return

        self._log("info", f"收到入站消息: user={msg.user_id}, text={text[:64]}")
        self._touch_user(msg.user_id, msg.context_token)

        is_command = text.startswith("/")
        if is_command and not self._config.get("command_enabled", True):
            self._log(
                "info",
                f"命令控制已关闭，忽略命令: user={msg.user_id}, text={text[:64]}",
            )
            return

        if is_command and self._is_plugin_command(text):
            if not self._is_admin(msg.user_id):
                self._log(
                    "warning", f"用户 {msg.user_id} 非管理员，拒绝插件命令: {text}"
                )
                self._send_text_with_retry(
                    msg.user_id,
                    "只有管理员才有权限执行此命令",
                    context_token=msg.context_token,
                )
                return

            self._record_incoming_message(msg, text)
            cmd = text.split()[0]
            args = " ".join(text.split()[1:])

            try:
                Command().execute(
                    cmd=cmd,
                    data_str=args,
                    channel=MessageChannel.Wechat,
                    source=self.__class__.__name__,
                    userid=msg.user_id,
                )
                self._log("info", f"已执行插件命令: {cmd} (user={msg.user_id})")
            except Exception as err:
                self._log(
                    "error",
                    f"插件命令执行异常: cmd={cmd}, user={msg.user_id}, err={err}",
                )
                self._send_text_with_retry(
                    msg.user_id, f"命令执行失败: {err}", context_token=msg.context_token
                )
            return

        # 非插件内置命令全部转交官方 MessageChain 处理，以对齐默认微信通道行为。
        if not self._dispatch_to_official_message_chain(msg, text):
            self._send_text_with_retry(
                msg.user_id, "消息处理异常，请稍后重试", context_token=msg.context_token
            )

    @staticmethod
    def _compose_text(message: Notification) -> str:
        parts: List[str] = []
        if message.title:
            parts.append(str(message.title))
        if message.text:
            parts.append(str(message.text))
        if message.link:
            parts.append(str(message.link))
        return "\n".join([p for p in parts if p]).strip()

    def _send_text_with_retry(
        self,
        user_id: str,
        text: str,
        retries: int = 3,
        context_token: Optional[str] = None,
    ) -> bool:
        if not user_id or not text:
            return False

        client = self._ensure_client()
        token = context_token or self._get_user_context_token(user_id)
        for idx in range(retries):
            if client.send_text(user_id, text, context_token=token):
                self._log("debug", f"发送消息成功: user={user_id}, attempt={idx + 1}")
                return True
            if idx < retries - 1:
                time.sleep(1)
        self._log("error", f"发送消息失败: user={user_id}, retries={retries}")
        return False

    def _can_send_notify_type(self, message: Notification) -> bool:
        if not self._config.get("notify_enabled", True):
            return False

        filters = self._config.get("notify_types") or []
        if not filters or not message.mtype:
            return True
        return message.mtype.value in filters

    def _resolve_targets(self, message: Notification) -> List[str]:
        if message.userid:
            return [str(message.userid)]

        if message.targets:
            uid = (
                message.targets.get("wechatclawbot_userid")
                or message.targets.get("wechatilink_userid")
                or message.targets.get("wechat_userid")
            )
            if uid:
                return [str(uid)]

        return self._active_users()

    def _notification_to_title_lines(
        self, message: Notification
    ) -> Tuple[Optional[str], List[str]]:
        """统一整理通知消息文案结构。"""
        title = str(message.title).strip() if message.title else None

        lines: List[str] = []
        if message.text:
            lines.extend(
                [
                    line.strip()
                    for line in str(message.text).splitlines()
                    if line.strip()
                ]
            )
        if message.link:
            lines.append(f"查看详情：{message.link}")

        return title, lines

    def _load_image_bytes(self, image: Optional[str]) -> Optional[bytes]:
        """将图片URL或data:image转换为图片字节。"""
        if not image:
            return None

        image_value = str(image).strip()
        if not image_value:
            return None

        if image_value.startswith("data:image/"):
            decoded, _ = self._decode_data_image(image_value)
            return decoded

        if image_value.startswith("/"):
            image_value = settings.MP_DOMAIN(image_value)

        if not image_value.lower().startswith("http"):
            return None

        try:
            # iLink 侧需要先拉取图片再上传 CDN，这里复用系统代理提升外链可达性。
            resp = RequestUtils(
                timeout=20, proxies=settings.PROXY, ua=settings.USER_AGENT
            ).get_res(image_value)
            if not resp or resp.status_code != 200 or not resp.content:
                return None

            content_type = (resp.headers.get("Content-Type") or "").lower()
            if content_type and "image" not in content_type:
                return None

            return resp.content
        except Exception as err:
            self._log("warning", f"加载图片失败: {err}")
            return None

    def _load_first_image_bytes(self, image: Any) -> Optional[bytes]:
        """支持候选图片列表，返回首个可加载的图片字节。"""
        if isinstance(image, (list, tuple, set)):
            for one in image:
                data = self._load_image_bytes(str(one) if one is not None else None)
                if data:
                    return data
            return None
        return self._load_image_bytes(str(image) if image is not None else None)

    def _send_image_bytes_with_retry(
        self,
        user_id: str,
        image_bytes: bytes,
        retries: int = 2,
    ) -> bool:
        """发送图片并重试。"""
        if not user_id or not image_bytes:
            return False

        client = self._ensure_client()
        token = self._get_user_context_token(user_id)
        for idx in range(retries):
            if client.send_image_png(user_id, image_bytes, context_token=token):
                return True
            if idx < retries - 1:
                time.sleep(0.6)

        self._log("warning", f"发送图片失败: user={user_id}")
        return False

    @staticmethod
    def _truncate_text(text: Any, max_len: int = 120) -> str:
        value = str(text or "").replace("\n", " ").replace("\r", " ").strip()
        if len(value) <= max_len:
            return value
        return f"{value[: max_len - 3]}..."

    def _is_ilink_wechat_message(self, message: Notification) -> bool:
        """仅处理来自 WechatClawBot 源的微信消息。"""
        if not message:
            return False
        if message.source != self.__class__.__name__:
            return False
        if message.channel and message.channel != MessageChannel.Wechat:
            return False
        return True

    def _send_lines_with_title(
        self,
        users: List[str],
        title: Optional[str],
        lines: Optional[List[str]] = None,
        image: Optional[str] = None,
        link: Optional[str] = None,
        max_chunk_len: int = 1500,
    ) -> bool:
        """将标题与列表分段发送，避免单条消息过长。"""
        image_bytes = self._load_first_image_bytes(image)

        chunks: List[str] = []
        if title:
            chunks.append(str(title).strip())

        if lines:
            current: List[str] = []
            current_len = 0
            for line in lines:
                line = str(line or "").strip()
                if not line:
                    continue
                extra = len(line) + (1 if current else 0)
                if current and current_len + extra > max_chunk_len:
                    chunks.append("\n".join(current))
                    current = [line]
                    current_len = len(line)
                else:
                    current.append(line)
                    current_len += extra
            if current:
                chunks.append("\n".join(current))

        if link:
            chunks.append(str(link).strip())

        ok = True
        for user_id in users:
            user_chunks = [chunk for chunk in chunks if chunk]
            if image_bytes:
                token = self._get_user_context_token(user_id)
                rich_text = ""
                if user_chunks:
                    rich_text = user_chunks.pop(0)
                    # 标题单独成块时，优先和正文首块合并成一条图文。
                    if title and rich_text == str(title).strip() and user_chunks:
                        rich_text = f"{rich_text}\n{user_chunks.pop(0)}"

                rich_ok = False
                if rich_text:
                    try:
                        rich_ok = self._ensure_client().send_image_text_png(
                            user_id,
                            image_bytes,
                            rich_text,
                            context_token=token,
                        )
                    except Exception as err:
                        self._log("warning", f"发送图文失败，回退到分开发送: {err}")

                if not rich_ok:
                    image_ok = self._send_image_bytes_with_retry(user_id, image_bytes)
                    ok = ok and image_ok
                    if rich_text:
                        text_ok = self._send_text_with_retry(
                            user_id, rich_text, context_token=token
                        )
                        ok = ok and text_ok

            for chunk in user_chunks:
                if not chunk:
                    continue
                one_ok = self._send_text_with_retry(user_id, chunk)
                ok = ok and one_ok
        return ok

    def _normalize_notice_message(self, event_data: Any) -> Optional[Notification]:
        """将 NoticeMessage 事件数据统一转换为 Notification。"""
        if isinstance(event_data, Notification):
            return event_data
        if not isinstance(event_data, dict):
            return None

        data = dict(event_data)
        if "mtype" not in data and data.get("type") is not None:
            data["mtype"] = data.get("type")

        try:
            return Notification(**data)
        except Exception as err:
            self._log("warning", f"通知事件数据解析失败: {err}")
            return None

    @eventmanager.register(EventType.NoticeMessage)
    def notice_message_event(self, event: Event):
        """监听系统通知并转发到 WeChat-ClawBot。"""
        if not self._enabled:
            return

        event_data = event.event_data
        if not event_data:
            return

        message = self._normalize_notice_message(event_data)
        if not message:
            return

        self._module_post_message(message)

    def _module_post_message(
        self, message: Notification, **kwargs
    ) -> Optional[MessageResponse]:
        if not self._enabled:
            return None

        # 插件命令回包：source 为插件类名时强制接管。
        force_handle = message.source == self.__class__.__name__
        if not force_handle:
            # 普通系统通知：仅在未指定渠道时接管，避免劫持其他渠道消息。
            if message.channel is not None:
                return None
            if not self._can_send_notify_type(message):
                return None

        title, lines = self._notification_to_title_lines(message)
        if not title and not lines and not message.image:
            return MessageResponse(success=False, source=self.__class__.__name__)

        users = self._resolve_targets(message)
        if not users:
            return MessageResponse(success=False, source=self.__class__.__name__)

        ok = self._send_lines_with_title(
            users=users,
            title=title,
            lines=lines,
            image=message.image,
        )

        return MessageResponse(success=ok, source=self.__class__.__name__)

    def _module_send_direct_message(
        self, message: Notification
    ) -> Optional[MessageResponse]:
        """处理直接发送消息接口，覆盖即时回包场景。"""
        if not self._enabled:
            return None
        if not self._is_ilink_wechat_message(message):
            return None

        title, lines = self._notification_to_title_lines(message)
        if not title and not lines and not message.image:
            return MessageResponse(success=False, source=self.__class__.__name__)

        users = self._resolve_targets(message)
        if not users:
            return MessageResponse(success=False, source=self.__class__.__name__)

        ok = self._send_lines_with_title(
            users=users,
            title=title,
            lines=lines,
            image=message.image,
        )

        # iLink 当前不支持消息编辑，message_id/chat_id 返回空即可。
        return MessageResponse(
            success=ok,
            channel=MessageChannel.Wechat,
            source=self.__class__.__name__,
            chat_id=users[0] if len(users) == 1 else None,
        )

    def _module_post_medias_message(
        self, message: Notification, medias: List[Any]
    ) -> Optional[MessageResponse]:
        """处理媒体列表回包（如“搜索 XXX”后的候选列表）。"""
        if not self._enabled:
            return None
        if not self._is_ilink_wechat_message(message):
            return None

        users = self._resolve_targets(message)
        if not users:
            return MessageResponse(success=False, source=self.__class__.__name__)

        lines: List[str] = []

        for idx, media in enumerate(medias or [], start=1):
            title = self._truncate_text(
                getattr(media, "title_year", None)
                or getattr(media, "title", None)
                or "未知媒体",
                80,
            )
            mtype = (
                getattr(getattr(media, "type", None), "value", None)
                or getattr(media, "type", None)
                or "未知类型"
            )
            score = getattr(media, "vote_average", None)
            if score:
                lines.append(f"{idx}. {title}｜{mtype}｜评分 {score}")
            else:
                lines.append(f"{idx}. {title}｜{mtype}")

        ok = self._send_lines_with_title(
            users=users,
            title=message.title,
            lines=lines,
            link=message.link,
        )
        return MessageResponse(success=ok, source=self.__class__.__name__)

    def _module_post_torrents_message(
        self, message: Notification, torrents: List[Any]
    ) -> Optional[MessageResponse]:
        """处理种子列表回包（如资源选择页）。"""
        if not self._enabled:
            return None
        if not self._is_ilink_wechat_message(message):
            return None

        users = self._resolve_targets(message)
        if not users:
            return MessageResponse(success=False, source=self.__class__.__name__)

        lines: List[str] = []

        for idx, context in enumerate(torrents or [], start=1):
            torrent = getattr(context, "torrent_info", None)
            if not torrent:
                lines.append(f"{idx}. 未知资源")
                continue

            site_name = self._truncate_text(
                getattr(torrent, "site_name", None) or "未知站点", 20
            )
            title = self._truncate_text(
                getattr(torrent, "title", None) or "未知标题", 80
            )
            seeders = getattr(torrent, "seeders", None)
            size = getattr(torrent, "size", None)
            size_text = (
                StringUtils.str_filesize(size)
                if isinstance(size, (int, float))
                else str(size or "未知大小")
            )
            if seeders is not None:
                lines.append(f"{idx}. 【{site_name}】{title}｜{size_text}｜{seeders}↑")
            else:
                lines.append(f"{idx}. 【{site_name}】{title}｜{size_text}")

        ok = self._send_lines_with_title(
            users=users,
            title=message.title,
            lines=lines,
            link=message.link,
        )
        return MessageResponse(success=ok, source=self.__class__.__name__)

    def _module_message_parser(
        self, source: str, body: Any, form: Any, args: Any
    ) -> Optional[CommingMessage]:
        """纯插件方案下不接管 /api/v1/message 解析，返回 None 交由系统模块处理。"""
        return None

    @eventmanager.register(EventType.PluginAction)
    def plugin_action_event(self, event: Event):
        """处理插件命令事件。"""
        data = event.event_data or {}
        if data.get("plugin_id") != self.__class__.__name__:
            return
        if data.get("action") != "get_qrcode":
            return

        force = False
        arg_str = str(data.get("arg_str") or "").strip().lower()
        if arg_str in {"force", "new", "refresh", "--force", "-f", "强制"}:
            force = True

        # 命令态下若已登录，默认刷新二维码，避免复用旧会话导致立即判定已登录。
        if not force:
            creds = self.get_data(self._CREDENTIALS_KEY) or {}
            if creds.get("bot_token"):
                force = True

        channel = data.get("channel")
        userid = data.get("user")
        source = data.get("source") or self.__class__.__name__
        result = self._ensure_qrcode(force=force)

        if result.get("success"):
            qrcode_url = result.get("qrcode_url")
            qrcode_id = result.get("qrcode")
            if not qrcode_url and qrcode_id:
                qrcode_url = self._compose_qrcode_url(str(qrcode_id))

            title = "WeChat-ClawBot 登录二维码"
            ilink_direct = source == self.__class__.__name__ and userid not in (
                None,
                "",
            )
            lines = [
                "已生成登录二维码。",
                f"系统将在 {self._LOGIN_WATCH_SECONDS} 秒内等待扫码登录，登录成功后自动更新用户 token。",
            ]

            if ilink_direct:
                image_sent = self._send_qrcode_image_for_ilink_user(
                    source=source,
                    userid=userid,
                    qrcode_url=qrcode_url,
                )
                if image_sent:
                    lines.append("二维码图片已发送，请直接扫码完成登录。")
                else:
                    lines.append("二维码图片发送失败，请稍后重试或在插件详情页扫码。")
            else:
                lines.append("可在插件详情页直接扫码。")
                if qrcode_url:
                    lines.append(f"二维码链接：{qrcode_url}")
                else:
                    lines.append("二维码链接暂不可用，请稍后重试。")

            content = "\n".join(lines)
            self._notify_command_feedback(
                channel=channel,
                source=source,
                userid=userid,
                title=title,
                text=content,
            )
            self._start_command_login_wait(
                channel=channel,
                source=source,
                userid=userid,
                expected_qrcode=str(qrcode_id) if qrcode_id else None,
            )
            self._log("info", f"命令 {self._QRCODE_COMMAND} 执行成功")
        else:
            fail_text = result.get("message") or "未知错误"
            self._notify_command_feedback(
                channel=channel,
                source=source,
                userid=userid,
                title="WeChat-ClawBot 登录二维码获取失败",
                text=fail_text,
            )
            self._log(
                "warning",
                f"命令 {self._QRCODE_COMMAND} 执行失败: {result.get('message') or 'unknown error'}",
            )

    def _notify_command_feedback(
        self, channel: Any, source: str, userid: Any, title: str, text: str
    ):
        if not self._send_direct_reply_for_ilink_user(
            source=source,
            userid=userid,
            title=title,
            text=text,
        ):
            self.chain.post_message(
                Notification(
                    channel=channel,
                    source=source,
                    userid=userid,
                    title=title,
                    text=text,
                )
            )

    def _start_command_login_wait(
        self, channel: Any, source: str, userid: Any, expected_qrcode: Optional[str]
    ):
        user_id = str(userid or "").strip()
        if not user_id:
            self._log("debug", "命令扫码等待跳过：缺少 user id")
            return

        with self._command_login_wait_lock:
            thread = threading.Thread(
                target=self._command_login_wait_worker,
                kwargs={
                    "channel": channel,
                    "source": source,
                    "user_id": user_id,
                    "expected_qrcode": expected_qrcode,
                },
                daemon=True,
            )
            self._command_login_wait_threads[user_id] = thread
            thread.start()

    def _command_login_wait_worker(
        self,
        channel: Any,
        source: str,
        user_id: str,
        expected_qrcode: Optional[str],
    ):
        try:
            result = self._wait_for_login_status(
                reason=f"command_user:{user_id}",
                expected_qrcode=expected_qrcode,
                require_qrcode_scan=True,
            )
            if result.get("connected"):
                token_updated = self._update_user_login_token(user_id)
                if token_updated:
                    text = "扫码登录成功，用户 token 已更新。"
                else:
                    text = "扫码登录成功，登录状态已更新。"
                self._notify_command_feedback(
                    channel=channel,
                    source=source,
                    userid=user_id,
                    title="WeChat-ClawBot 登录成功",
                    text=text,
                )
                self._log(
                    "info",
                    f"命令扫码等待成功: user={user_id}, token_updated={token_updated}",
                )
                return

            wait_status = str(result.get("status") or "").lower()
            if wait_status == "replaced":
                self._log("info", f"命令扫码等待结束: user={user_id}, status=replaced")
                return
            if wait_status == "expired":
                text = "二维码已过期，请重新发送命令获取新的二维码。"
            elif wait_status == "timeout":
                text = "二维码已超时，请重新发送命令获取二维码。"
            elif wait_status == "watch_timeout":
                text = "在等待时间内未检测到登录成功，请重新发送命令并扫码。"
            elif wait_status in {"canceled", "cancelled"}:
                text = "扫码已取消，请重新发送命令获取二维码。"
            elif wait_status == "disabled":
                text = "插件已停用，已停止等待扫码登录。"
            elif wait_status == "not_initialized":
                text = "二维码尚未初始化，请重新发送命令。"
            elif wait_status == "error":
                detail = result.get("message") or "状态查询异常"
                text = f"等待扫码时发生异常：{detail}"
            else:
                text = "在等待时间内未检测到登录成功，请重新发送命令并扫码。"

            self._notify_command_feedback(
                channel=channel,
                source=source,
                userid=user_id,
                title="WeChat-ClawBot 登录状态",
                text=text,
            )
            self._log(
                "info",
                f"命令扫码等待结束: user={user_id}, status={wait_status or 'unknown'}",
            )
        finally:
            with self._command_login_wait_lock:
                current = self._command_login_wait_threads.get(user_id)
                if current is threading.current_thread():
                    self._command_login_wait_threads.pop(user_id, None)

    def close(self):
        self.stop_service()
