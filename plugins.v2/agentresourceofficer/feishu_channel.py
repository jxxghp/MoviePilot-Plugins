import asyncio
import copy
import fcntl
import importlib
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from base64 import b64decode
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import jieba
except Exception:
    jieba = None

for _site_path in (
    "/usr/local/lib/python3.12/site-packages",
    "/usr/local/lib/python3.11/site-packages",
):
    if Path(_site_path).exists() and _site_path not in sys.path:
        sys.path.append(_site_path)

try:
    import lark_oapi as lark
except Exception:
    lark = None

_LARK_IMPORT_LOCK = threading.Lock()
_LARK_AUTO_INSTALL_ATTEMPTED = False
_LARK_PACKAGE_SPEC = "lark-oapi==1.5.3"

try:
    from app.chain.download import DownloadChain
    from app.chain.media import MediaChain
    from app.chain.search import SearchChain
    from app.chain.subscribe import SubscribeChain
    from app.core.event import eventmanager
    from app.core.metainfo import MetaInfo
    from app.db.downloadhistory_oper import DownloadHistoryOper
    from app.db.models.downloadhistory import DownloadHistory
    from app.db.models.transferhistory import TransferHistory
    from app.db.site_oper import SiteOper
    from app.db.subscribe_oper import SubscribeOper
    from app.db.systemconfig_oper import SystemConfigOper
    from app.helper.subscribe import SubscribeHelper
    from app.core.plugin import PluginManager
    from app.log import logger
    from app.scheduler import Scheduler
    from app.schemas.types import EventType, SystemConfigKey, TorrentStatus, media_type_to_agent
    from app.utils.http import RequestUtils
    from app.utils.string import StringUtils
except Exception:
    DownloadChain = None
    DownloadHistoryOper = None
    DownloadHistory = None
    TransferHistory = None
    MediaChain = None
    SearchChain = None
    SiteOper = None
    SubscribeChain = None
    SubscribeHelper = None
    SubscribeOper = None
    SystemConfigOper = None
    eventmanager = None
    MetaInfo = None
    PluginManager = None
    Scheduler = None
    EventType = None
    SystemConfigKey = None
    TorrentStatus = None
    media_type_to_agent = None
    RequestUtils = None
    StringUtils = None

    class _FallbackLogger:
        @staticmethod
        def info(message: str) -> None:
            print(message)

        @staticmethod
        def warning(message: str) -> None:
            print(message)

        @staticmethod
        def error(message: str) -> None:
            print(message)

    logger = _FallbackLogger()


_EVENT_CACHE_FILE = Path("/config/plugins/AgentResourceOfficer/.feishu_event_cache.json")


def ensure_lark_sdk(auto_install: bool = False) -> tuple[bool, str]:
    global lark, _LARK_AUTO_INSTALL_ATTEMPTED

    if lark is not None:
        return True, ""

    with _LARK_IMPORT_LOCK:
        if lark is not None:
            return True, ""

        try:
            import lark_oapi as runtime_lark

            lark = runtime_lark
            return True, ""
        except Exception as exc:
            first_error = str(exc)

        if not auto_install:
            return False, f"缺少依赖 lark-oapi：{first_error}"

        if _LARK_AUTO_INSTALL_ATTEMPTED:
            return False, f"缺少依赖 lark-oapi：{first_error}"

        _LARK_AUTO_INSTALL_ATTEMPTED = True
        requirements_file = Path(__file__).with_name("requirements.txt")
        install_cmds = []
        if requirements_file.exists():
            install_cmds.append([sys.executable, "-m", "pip", "install", "-r", str(requirements_file)])
        install_cmds.append([sys.executable, "-m", "pip", "install", _LARK_PACKAGE_SPEC])

        install_errors: list[str] = []
        for cmd in install_cmds:
            try:
                logger.info(f"[AgentResourceOfficer][Feishu] 正在尝试安装依赖：{' '.join(cmd)}")
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except Exception as exc:
                install_errors.append(str(exc))
                continue
            if proc.returncode == 0:
                try:
                    import lark_oapi as runtime_lark

                    lark = runtime_lark
                    logger.info("[AgentResourceOfficer][Feishu] 已自动安装并加载 lark-oapi")
                    return True, ""
                except Exception as exc:
                    install_errors.append(str(exc))
            else:
                stderr = (proc.stderr or "").strip()
                stdout = (proc.stdout or "").strip()
                install_errors.append(stderr or stdout or f"returncode={proc.returncode}")

        detail = " | ".join([msg for msg in install_errors if msg]) or first_error
        return False, f"缺少依赖 lark-oapi，且自动安装失败：{detail}"


class _FeishuLongConnectionRuntime:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._fingerprint = ""
        self._channel: Optional["FeishuChannel"] = None

    def start(self, channel: "FeishuChannel") -> None:
        ok, message = ensure_lark_sdk(auto_install=True)
        if not ok:
            logger.error(f"[AgentResourceOfficer][Feishu] {message}")
            return

        if not channel.enabled or not channel.app_id or not channel.app_secret:
            return

        fingerprint = channel.connection_fingerprint()
        with self._lock:
            self._channel = channel
            if self._thread and self._thread.is_alive():
                if fingerprint != self._fingerprint:
                    logger.warning("[AgentResourceOfficer][Feishu] 长连接已在运行，飞书凭证变更需重启 MoviePilot 后生效")
                return
            self._fingerprint = fingerprint
            self._thread = threading.Thread(
                target=self._run,
                name="agent-resource-officer-feishu",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        channel = self._channel
        if channel is None or lark is None:
            return

        def _on_message(data) -> None:
            current = self._channel
            if current is not None:
                current.handle_long_connection_event(data)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            import lark_oapi.ws.client as lark_ws_client

            lark_ws_client.loop = loop
            event_handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(_on_message)
                .build()
            )
            ws_client = lark.ws.Client(
                channel.app_id,
                channel.app_secret,
                log_level=lark.LogLevel.DEBUG if channel.debug else lark.LogLevel.INFO,
                event_handler=event_handler,
            )
            logger.info("[AgentResourceOfficer][Feishu] 正在启动飞书长连接")
            ws_client.start()
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 长连接退出：{exc}\n{traceback.format_exc()}")

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        with self._lock:
            self._channel = None


class FeishuChannel:
    _LEGACY_DEFAULT_COMMANDS = {
        "/p115_manual_transfer",
        "/p115_inc_sync",
        "/p115_full_sync",
        "/p115_strm",
        "/quark_save",
        "/media_search",
        "/media_download",
    }
    _LEGACY_DEFAULT_ALIAS_KEYS = {
        "刮削",
        "搜索",
        "MP搜索",
        "原生搜索",
        "下载",
        "订阅",
        "生成STRM",
        "全量STRM",
        "指定路径STRM",
        "夸克转存",
        "夸克",
        "搜索资源",
        "下载资源",
    }

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.runtime = _FeishuLongConnectionRuntime()
        self.enabled = False
        self.allow_all = False
        self.reply_enabled = True
        self.reply_receive_id_type = "chat_id"
        self.app_id = ""
        self.app_secret = ""
        self.verification_token = ""
        self.allowed_chat_ids: List[str] = []
        self.allowed_user_ids: List[str] = []
        self.command_whitelist: List[str] = []
        self.command_aliases = ""
        self.command_mode = "resource_officer"
        self.debug = False
        self._token_cache: Dict[str, Any] = {}
        self._token_lock = threading.Lock()
        self._event_cache: Dict[str, float] = {}
        self._event_lock = threading.Lock()
        self._search_cache: Dict[str, Dict[str, Any]] = {}
        self._search_cache_lock = threading.Lock()
        self._search_cache_limit = 200

    @classmethod
    def default_command_whitelist(cls) -> List[str]:
        return [
            "/pansou_search",
            "/smart_entry",
            "/smart_pick",
            "/media_search",
            "/version",
        ]

    @classmethod
    def default_command_aliases(cls) -> str:
        return (
            "搜索=/smart_entry\n"
            "找=/smart_entry\n"
            "MP搜索=/smart_entry\n"
            "PT搜索=/smart_entry\n"
            "原生搜索=/smart_entry\n"
            "盘搜搜索=/pansou_search\n"
            "盘搜=/pansou_search\n"
            "ps=/pansou_search\n"
            "1=/pansou_search\n"
            "影巢搜索=/smart_entry\n"
            "影巢=/smart_entry\n"
            "yc=/smart_entry\n"
            "2=/smart_entry\n"
            "转存=/smart_entry\n"
            "115转存=/smart_entry\n"
            "夸克转存=/smart_entry\n"
            "夸克=/smart_entry\n"
            "下载=/smart_entry\n"
            "订阅=/smart_entry\n"
            "链接=/smart_entry\n"
            "处理=/smart_entry\n"
            "115登录=/smart_entry\n"
            "115扫码=/smart_entry\n"
            "检查115登录=/smart_entry\n"
            "115登录状态=/smart_entry\n"
            "115状态=/smart_entry\n"
            "115帮助=/smart_entry\n"
            "115任务=/smart_entry\n"
            "继续115任务=/smart_entry\n"
            "取消115任务=/smart_entry\n"
            "影巢签到=/smart_entry\n"
            "影巢普通签到=/smart_entry\n"
            "普通签到=/smart_entry\n"
            "签到=/smart_entry\n"
            "赌狗签到=/smart_entry\n"
            "签到日志=/smart_entry\n"
            "影巢签到日志=/smart_entry\n"
            "选择=/smart_pick\n"
            "详情=/smart_pick\n"
            "审查=/smart_pick\n"
            "选=/smart_pick\n"
            "继续=/smart_pick\n"
            "搜索资源=/smart_entry\n"
            "下载资源=/smart_entry\n"
            "版本=/version"
        )

    @staticmethod
    def clean(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        for ch in ("\ufeff", "\u200b", "\u200c", "\u200d", "\u2060", "\ufffc"):
            text = text.replace(ch, "")
        return text.strip()

    @staticmethod
    def split_lines(value: Any) -> List[str]:
        return [line.strip() for line in str(value or "").splitlines() if line.strip()]

    @staticmethod
    def split_commands(value: Any) -> List[str]:
        raw = str(value or "").replace("\n", ",")
        return [item.strip() for item in raw.split(",") if item.strip()]

    @classmethod
    def parse_alias_text(cls, text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for line in str(text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value.startswith("/"):
                result[key] = value
        return result

    @classmethod
    def merge_command_aliases(cls, configured_text: str) -> str:
        merged = cls.parse_alias_text(cls.default_command_aliases())
        for key, value in cls.parse_alias_text(configured_text).items():
            if key in cls._LEGACY_DEFAULT_ALIAS_KEYS and value in cls._LEGACY_DEFAULT_COMMANDS:
                continue
            merged[key] = value
        return "\n".join(f"{key}={value}" for key, value in merged.items())

    @classmethod
    def merge_command_whitelist(cls, configured: List[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for cmd in configured or []:
            if cmd in cls._LEGACY_DEFAULT_COMMANDS:
                continue
            if cmd and cmd not in seen:
                merged.append(cmd)
                seen.add(cmd)
        for cmd in cls.default_command_whitelist():
            if cmd not in seen:
                merged.append(cmd)
                seen.add(cmd)
        return merged

    def configure(self, config: Dict[str, Any]) -> None:
        self.enabled = bool(config.get("feishu_enabled", False))
        self.allow_all = bool(config.get("feishu_allow_all", False))
        self.reply_enabled = bool(config.get("feishu_reply_enabled", True))
        self.reply_receive_id_type = self.clean(config.get("feishu_reply_receive_id_type") or "chat_id")
        self.app_id = self.clean(config.get("feishu_app_id"))
        self.app_secret = self.clean(config.get("feishu_app_secret"))
        self.verification_token = self.clean(config.get("feishu_verification_token"))
        self.allowed_chat_ids = self.split_lines(config.get("feishu_allowed_chat_ids"))
        self.allowed_user_ids = self.split_lines(config.get("feishu_allowed_user_ids"))
        self.command_whitelist = self.merge_command_whitelist(self.split_commands(config.get("feishu_command_whitelist")))
        self.command_aliases = self.merge_command_aliases(self.clean(config.get("feishu_command_aliases")))
        self.command_mode = self.clean(config.get("feishu_command_mode") or "resource_officer")
        self.debug = bool(config.get("debug", False))

    def start(self) -> None:
        if self.enabled:
            self.runtime.start(self)

    def stop(self) -> None:
        self.runtime.stop()

    def is_running(self) -> bool:
        return self.runtime.is_running()

    @staticmethod
    def is_legacy_bridge_running() -> bool:
        if PluginManager is None:
            return False
        try:
            running_plugins = PluginManager().running_plugins or {}
            plugin = (
                running_plugins.get("FeishuCommandBridgeLong")
                or running_plugins.get("feishucommandbridgelong")
            )
            if not plugin:
                return False
            config_db = Path("/config/user.db")
            if config_db.exists():
                try:
                    with sqlite3.connect(str(config_db)) as conn:
                        row = conn.execute(
                            "select value from systemconfig where key=?",
                            ("plugin.FeishuCommandBridgeLong",),
                        ).fetchone()
                    if row and row[0]:
                        config = json.loads(row[0])
                        if not bool(config.get("enabled")):
                            return False
                except Exception:
                    pass
            # MoviePilot may keep disabled plugins in running_plugins after loading.
            # Treat the legacy bridge as a conflict only when it is actually enabled.
            if hasattr(plugin, "health"):
                try:
                    health = plugin.health()
                    if isinstance(health, dict):
                        return bool(health.get("enabled") and health.get("running"))
                except Exception:
                    pass
            if hasattr(plugin, "_enabled"):
                return bool(getattr(plugin, "_enabled", False))
            if hasattr(plugin, "get_state"):
                try:
                    return bool(plugin.get_state())
                except Exception:
                    return False
            return False
        except Exception:
            return False

    def connection_fingerprint(self) -> str:
        return "|".join([self.app_id, self.app_secret, self.verification_token])

    def health(self) -> Dict[str, Any]:
        sdk_available, sdk_message = ensure_lark_sdk(auto_install=False)
        legacy_bridge_running = self.is_legacy_bridge_running()
        app_id_configured = bool(self.app_id)
        app_secret_configured = bool(self.app_secret)
        verification_token_configured = bool(self.verification_token)
        missing_requirements = []
        if not sdk_available:
            missing_requirements.append("lark-oapi")
        if not app_id_configured:
            missing_requirements.append("feishu_app_id")
        if not app_secret_configured:
            missing_requirements.append("feishu_app_secret")
        conflict_warning = bool(self.enabled and legacy_bridge_running)
        ready_to_start = bool(self.enabled and sdk_available and app_id_configured and app_secret_configured and not conflict_warning)
        safe_to_enable = bool((not legacy_bridge_running) and sdk_available and app_id_configured and app_secret_configured)
        if conflict_warning:
            recommended_action = "disable_legacy_bridge_or_use_different_app"
            migration_hint = "内置飞书入口和旧飞书桥接同时运行，建议关闭旧桥接或使用不同飞书 App。"
        elif not self.enabled and legacy_bridge_running:
            recommended_action = "keep_legacy_or_disable_it_before_migration"
            migration_hint = "内置飞书入口关闭，旧飞书桥接运行中；迁移前先关闭旧桥接。"
        elif not self.enabled:
            recommended_action = "configure_and_enable_feishu_channel"
            migration_hint = "内置飞书入口关闭；配置飞书凭证后可开启。"
        elif missing_requirements:
            recommended_action = "complete_feishu_requirements"
            migration_hint = "内置飞书入口已启用，但依赖或飞书凭证不完整。"
        elif not self.is_running():
            recommended_action = "restart_moviepilot_or_resave_config"
            migration_hint = "内置飞书入口已启用但长连接未运行，建议保存配置或重启 MoviePilot。"
        else:
            recommended_action = "none"
            migration_hint = "内置飞书入口运行正常。"
        return {
            "enabled": self.enabled,
            "running": self.is_running(),
            "sdk_available": sdk_available,
            "app_id_configured": app_id_configured,
            "app_secret_configured": app_secret_configured,
            "verification_token_configured": verification_token_configured,
            "allow_all": self.allow_all,
            "reply_enabled": self.reply_enabled,
            "allowed_chat_count": len(self.allowed_chat_ids),
            "allowed_user_count": len(self.allowed_user_ids),
            "command_mode": self.command_mode,
            "command_whitelist": self.command_whitelist,
            "alias_count": len(self.parse_alias_text(self.command_aliases)),
            "legacy_bridge_running": legacy_bridge_running,
            "conflict_warning": conflict_warning,
            "ready_to_start": ready_to_start,
            "safe_to_enable": safe_to_enable,
            "missing_requirements": missing_requirements,
            "sdk_message": sdk_message,
            "recommended_action": recommended_action,
            "migration_hint": migration_hint,
        }

    def handle_long_connection_event(self, data: Any) -> None:
        if not self.enabled:
            return
        event = getattr(data, "event", None)
        header = getattr(data, "header", None)
        message = getattr(event, "message", None)
        sender = getattr(event, "sender", None)
        sender_id = getattr(sender, "sender_id", None)

        event_id = str(getattr(header, "event_id", "") or "").strip()
        if event_id and self._is_duplicate_event(event_id):
            return
        if not message or str(getattr(message, "message_type", "")).strip() != "text":
            return

        raw_text = self._extract_text(getattr(message, "content", None))
        if not raw_text:
            return
        sender_open_id = str(getattr(sender_id, "open_id", "") or "").strip()
        chat_id = str(getattr(message, "chat_id", "") or "").strip()
        if self.debug:
            logger.info(
                f"[AgentResourceOfficer][Feishu] event_id={event_id} "
                f"chat_id={chat_id} open_id={sender_open_id}"
            )

        if not self._is_allowed(chat_id=chat_id, user_open_id=sender_open_id):
            self.reply_text(chat_id, sender_open_id, "该会话未在白名单中，命令已拒绝。")
            return
        if self._is_help_request(raw_text):
            self.reply_text(chat_id, sender_open_id, self._build_help_text())
            return
        if self._is_menu_request(raw_text):
            self.reply_text(chat_id, sender_open_id, self._build_menu_text())
            return

        command_text = self._map_text_to_command(raw_text)
        if not command_text:
            return
        cmd = command_text.split()[0]
        if cmd not in self.command_whitelist:
            self.reply_text(chat_id, sender_open_id, f"命令 {cmd} 不在白名单中。\n\n{self._build_help_text()}")
            return
        if not self._handle_builtin_command(command_text, chat_id, sender_open_id):
            self._submit_moviepilot_command(command_text, chat_id, sender_open_id)

    def _handle_builtin_command(self, command_text: str, chat_id: str, open_id: str) -> bool:
        parts = command_text.split(maxsplit=1)
        cmd = parts[0].strip()
        arg = parts[1].strip() if len(parts) > 1 else ""
        cache_key = self._cache_key(chat_id, open_id)

        if cmd == "/version":
            self.reply_text(chat_id, open_id, f"Agent影视助手 {getattr(self.plugin, 'plugin_version', '')}\n飞书入口：{'运行中' if self.is_running() else '未运行'}")
            return True

        if cmd == "/media_search":
            if not arg:
                self.reply_text(chat_id, open_id, "用法：MP搜索 片名")
                return True
            self.reply_text(chat_id, open_id, f"正在使用 MP 原生搜索：{arg}")
            self._run_thread("feishu-media-search", self._run_media_search, arg, chat_id, open_id)
            return True

        if cmd == "/media_download":
            if not arg or not arg.isdigit():
                self.reply_text(chat_id, open_id, "用法：下载 序号\n示例：下载 1")
                return True
            self.reply_text(chat_id, open_id, f"正在下载第 {arg} 条 PT 结果，请稍候。")
            self._run_thread("feishu-media-download", self._run_media_download, int(arg), chat_id, open_id)
            return True

        if cmd in {"/media_subscribe", "/media_subscribe_search"}:
            if not arg:
                self.reply_text(chat_id, open_id, "用法：订阅 片名\n示例：订阅 流浪地球2")
                return True
            if cmd == "/media_subscribe_search":
                self.reply_text(
                    chat_id,
                    open_id,
                    "“订阅并搜索 片名”旧命令已取消。\n请改用：订阅 片名\n如需立即看资源，再手动发 MP搜索 / 盘搜搜索 / 影巢搜索。",
                )
                return True
            self.reply_text(chat_id, open_id, f"正在订阅：{arg}")
            self._run_thread("feishu-media-subscribe", self._run_media_subscribe, arg, False, chat_id, open_id)
            return True

        if cmd == "/pansou_search":
            if not arg:
                self.reply_text(chat_id, open_id, "用法：盘搜搜索 片名\n示例：盘搜搜索 流浪地球2")
                return True
            self.reply_text(chat_id, open_id, f"正在使用盘搜搜索：{arg}")
            self._run_thread("feishu-pansou-search", self._run_assistant_route, f"盘搜搜索 {arg}", cache_key, chat_id, open_id)
            return True

        if cmd in {"/smart_entry", "/quark_save"}:
            if not arg:
                self.reply_text(chat_id, open_id, "用法：处理 片名 或 处理 分享链接")
                return True
            self.reply_text(chat_id, open_id, f"正在智能处理：{arg}")
            self._run_thread("feishu-smart-entry", self._run_assistant_route, arg, cache_key, chat_id, open_id)
            return True

        if cmd == "/smart_pick":
            if not arg:
                self.reply_text(chat_id, open_id, "用法：选择 序号\n示例：选择 1\n也支持：详情、审查、n 下一页")
                return True
            self.reply_text(chat_id, open_id, f"正在继续执行：{arg}")
            self._run_thread("feishu-smart-pick", self._run_assistant_pick, arg, cache_key, chat_id, open_id)
            return True

        if cmd == "/p115_manual_transfer":
            if not arg:
                paths = self._get_p115_manual_transfer_paths()
                if not paths:
                    self.reply_text(chat_id, open_id, "未配置待整理目录。请先在 P115StrmHelper 中配置 pan_transfer_paths，或发送：刮削 /待整理/")
                    return True
                self.reply_text(chat_id, open_id, f"已开始刮削 {len(paths)} 个目录：\n" + "\n".join(f"- {path}" for path in paths))
                self._run_thread("feishu-p115-manual-transfer-batch", self._run_p115_manual_transfer_batch, paths, chat_id, open_id)
                return True
            self.reply_text(chat_id, open_id, f"已开始刮削：{arg}")
            self._run_thread("feishu-p115-manual-transfer", self._run_p115_manual_transfer, arg, chat_id, open_id)
            return True

        if cmd in {"/p115_inc_sync", "/p115_full_sync", "/p115_strm"}:
            final_command = "/p115_full_sync" if cmd == "/p115_strm" and not arg else command_text
            self._submit_p115_command(final_command, chat_id, open_id)
            return True

        return False

    @staticmethod
    def _run_thread(name: str, target: Any, *args: Any) -> None:
        threading.Thread(target=target, args=args, name=name, daemon=True).start()

    def _run_assistant_route(self, text: str, session: str, chat_id: str, open_id: str) -> None:
        result = self.plugin.feishu_assistant_route(text=text, session=session)
        self._reply_result(chat_id, open_id, result)

    def _run_assistant_pick(self, arg: str, session: str, chat_id: str, open_id: str) -> None:
        result = self.plugin.feishu_assistant_pick(arg=arg, session=session)
        self._reply_result(chat_id, open_id, result)

    def _reply_result(self, chat_id: str, open_id: str, result: Dict[str, Any]) -> None:
        message = str(result.get("message") or "处理完成").strip()
        self.reply_text(chat_id, open_id, message)
        qrcode = self._find_nested_value(result.get("data"), "qrcode")
        if isinstance(qrcode, str):
            self.reply_qrcode_data_url(chat_id, open_id, qrcode)

    @classmethod
    def _find_nested_value(cls, payload: Any, key: str) -> Any:
        if isinstance(payload, dict):
            if key in payload:
                return payload.get(key)
            for value in payload.values():
                found = cls._find_nested_value(value, key)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = cls._find_nested_value(value, key)
                if found:
                    return found
        return None

    def _run_media_search(self, keyword: str, chat_id: str, open_id: str) -> None:
        self.reply_text(chat_id, open_id, self._execute_media_search(keyword, self._cache_key(chat_id, open_id)))

    def _run_media_download(self, index: int, chat_id: str, open_id: str) -> None:
        result = self.plugin.feishu_assistant_route(
            text=f"下载 {index}",
            session=self._cache_key(chat_id, open_id),
        )
        self._reply_result(chat_id, open_id, result)

    def _run_media_subscribe(self, keyword: str, immediate: bool, chat_id: str, open_id: str) -> None:
        self.reply_text(chat_id, open_id, self._execute_media_subscribe(keyword, immediate))

    def _execute_media_search(self, keyword: str, cache_key: str) -> str:
        if not all([MetaInfo, MediaChain, SearchChain, StringUtils]):
            return "MP 原生搜索失败：当前环境缺少 MoviePilot 搜索依赖。"
        try:
            meta = MetaInfo(keyword)
            mediainfo = MediaChain().recognize_media(meta=meta)
            if not mediainfo:
                return f"未识别到媒体信息：{keyword}"
            season = meta.begin_season if meta.begin_season else mediainfo.season
            results = SearchChain().search_by_id(
                tmdbid=mediainfo.tmdb_id,
                doubanid=mediainfo.douban_id,
                mtype=mediainfo.type,
                season=season,
                cache_local=False,
            ) or []
            if not results:
                return f"已识别 {self._format_media_label(mediainfo, season)}，但暂未搜索到资源。"
            self._set_search_cache(cache_key, keyword, mediainfo, results)
            preview_limit = 10
            preview_results = results[:preview_limit]
            lines = [
                f"已识别：{self._format_media_label(mediainfo, season)}",
                f"共找到 {len(results)} 条资源，展示前 {len(preview_results)} 条：",
            ]
            for idx, context in enumerate(preview_results, start=1):
                torrent = context.torrent_info
                title = str(torrent.title or "").strip()
                size = StringUtils.str_filesize(torrent.size) if torrent.size else "未知"
                seeders = torrent.seeders if torrent.seeders is not None else "?"
                site = torrent.site_name or "未知站点"
                volume = torrent.volume_factor if getattr(torrent, "volume_factor", None) else "未知"
                lines.append(f"{idx}. [{site}] {title}")
                lines.append(f"   大小：{size} | 做种：{seeders} | 促销：{volume}")
            lines.append("下一步：回复“下载 序号”会直接下载当前 PT 结果。")
            lines.append("如需长期跟踪，回复“订阅 片名”。")
            return "\n".join(lines)
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 搜索资源失败：{keyword} {exc}\n{traceback.format_exc()}")
            return f"搜索资源失败：{keyword}\n错误：{exc}"

    def _query_media_detail(self, keyword: str, media_type: str = "", year: str = "") -> Dict[str, Any]:
        if not all([MetaInfo, MediaChain]):
            return {"success": False, "message": "媒体识别失败：当前环境缺少 MoviePilot 媒体识别依赖。", "item": {}}
        title_text = str(keyword or "").strip()
        if not title_text:
            return {"success": False, "message": "媒体识别失败：缺少片名。", "item": {}}
        try:
            meta = MetaInfo(title_text)
            if year:
                try:
                    meta.year = str(year)
                except Exception:
                    pass
            mediainfo = MediaChain().recognize_media(meta=meta)
            if not mediainfo:
                return {"success": False, "message": f"未识别到媒体信息：{title_text}", "item": {"keyword": title_text}}
            season = meta.begin_season if meta.begin_season else getattr(mediainfo, "season", None)
            media_type_value = getattr(mediainfo, "type", None)
            media_type_name = getattr(media_type_value, "name", "") or str(media_type_value or "")
            item = {
                "keyword": title_text,
                "title": str(getattr(mediainfo, "title", "") or ""),
                "original_title": str(getattr(mediainfo, "original_title", "") or ""),
                "year": str(getattr(mediainfo, "year", "") or ""),
                "type": media_type_name,
                "tmdb_id": getattr(mediainfo, "tmdb_id", None),
                "douban_id": getattr(mediainfo, "douban_id", None),
                "imdb_id": str(getattr(mediainfo, "imdb_id", "") or ""),
                "season": season,
                "category": str(getattr(mediainfo, "category", "") or ""),
                "overview": str(getattr(mediainfo, "overview", "") or "")[:300],
            }
            lines = [
                f"媒体识别：{title_text}",
                f"结果：{item.get('title') or '-'} ({item.get('year') or '-'})",
                f"类型：{item.get('type') or '-'} | TMDB：{item.get('tmdb_id') or '-'} | 豆瓣：{item.get('douban_id') or '-'}",
            ]
            if item.get("original_title") and item.get("original_title") != item.get("title"):
                lines.append(f"原标题：{item.get('original_title')}")
            if season:
                lines.append(f"季：S{int(season):02d}" if isinstance(season, int) else f"季：{season}")
            if item.get("overview"):
                lines.append(f"简介：{item.get('overview')}")
            lines.append("说明：这是 MoviePilot 原生识别结果，后续 MP 搜索、订阅和 PT 评分会以它为准。")
            return {"success": True, "message": "\n".join(lines), "item": item}
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 媒体识别失败：{title_text} {exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"媒体识别失败：{exc}", "item": {"keyword": title_text}}

    def _execute_media_download(self, index: int, cache_key: str) -> str:
        if DownloadChain is None:
            return "下载资源失败：当前环境缺少 MoviePilot 下载依赖。"
        cache = self._get_search_cache(cache_key)
        if not cache:
            return "没有可用的搜索缓存，请先发送：MP搜索 片名"
        results = cache.get("results") or []
        if index < 1 or index > len(results):
            return f"序号超出范围，请输入 1 到 {len(results)} 之间的数字。"
        context = copy.deepcopy(results[index - 1])
        torrent = context.torrent_info
        try:
            save_path = ""
            if self.plugin is not None:
                save_path = str(getattr(self.plugin, "_mp_download_save_path", "") or "").strip()
            download_id = DownloadChain().download_single(
                context=context,
                username="agentresourceofficer-feishu",
                source="AgentResourceOfficer",
                save_path=save_path or None,
            )
            if not download_id:
                return f"下载提交失败：{torrent.title}"
            path_line = f"\n保存路径：{save_path}" if save_path else ""
            return f"已提交下载：{torrent.title}\n站点：{torrent.site_name or '未知站点'}{path_line}\n任务ID：{download_id}"
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 下载资源失败：{torrent.title} {exc}\n{traceback.format_exc()}")
            return f"下载资源失败：{torrent.title}\n错误：{exc}"

    def _query_download_tasks(
        self,
        *,
        downloader: str = "",
        status: str = "downloading",
        title: str = "",
        hash_value: str = "",
        limit: int = 10,
    ) -> Dict[str, Any]:
        if DownloadChain is None:
            return {"success": False, "message": "查询下载任务失败：当前环境缺少 MoviePilot 下载依赖。", "items": []}
        try:
            chain = DownloadChain()
            status_name = str(status or "downloading").strip().lower()
            downloader_name = str(downloader or "").strip() or None
            tasks: List[Any] = []
            if hash_value:
                tasks = chain.list_torrents(downloader=downloader_name, hashs=[hash_value]) or []
            elif status_name == "downloading":
                tasks = chain.downloading(name=downloader_name) or []
            else:
                for torrent_status in [TorrentStatus.DOWNLOADING, TorrentStatus.TRANSFER] if TorrentStatus else []:
                    tasks.extend(chain.list_torrents(downloader=downloader_name, status=torrent_status) or [])
            if status_name == "completed":
                tasks = [task for task in tasks if str(getattr(task, "state", "") or "").lower() in {"seeding", "completed"}]
            elif status_name == "paused":
                tasks = [task for task in tasks if str(getattr(task, "state", "") or "").lower() == "paused"]
            if title:
                title_lower = title.lower()
                tasks = [
                    task for task in tasks
                    if title_lower in str(getattr(task, "title", "") or getattr(task, "name", "") or "").lower()
                ]
            items: List[Dict[str, Any]] = []
            for index, task in enumerate(tasks[:max(1, min(30, int(limit or 10)))], 1):
                task_hash = str(getattr(task, "hash", "") or "")
                history = DownloadHistoryOper().get_by_hash(task_hash) if DownloadHistoryOper and task_hash else None
                title_text = str(getattr(task, "title", "") or getattr(task, "name", "") or "").strip()
                if history and getattr(history, "title", None):
                    title_text = title_text or str(history.title)
                size_value = getattr(task, "size", None)
                size_text = StringUtils.str_filesize(size_value) if StringUtils and size_value else ""
                progress = getattr(task, "progress", None)
                try:
                    progress_text = f"{float(progress):.1f}%" if progress is not None else ""
                except Exception:
                    progress_text = str(progress or "")
                items.append({
                    "index": index,
                    "hash": task_hash,
                    "hash_short": task_hash[:8],
                    "downloader": str(getattr(task, "downloader", "") or ""),
                    "title": title_text or "未命名任务",
                    "name": str(getattr(task, "name", "") or ""),
                    "size": size_text,
                    "progress": progress_text,
                    "state": str(getattr(task, "state", "") or ""),
                    "dlspeed": getattr(task, "dlspeed", None),
                    "upspeed": getattr(task, "upspeed", None),
                    "left_time": getattr(task, "left_time", None),
                    "tags": str(getattr(task, "tags", "") or ""),
                    "media_title": str(getattr(history, "title", "") or "") if history else "",
                })
            status_label = {
                "downloading": "下载中",
                "completed": "已完成",
                "paused": "已暂停",
                "all": "全部",
            }.get(status_name, status_name)
            if not items:
                return {
                    "success": True,
                    "message": f"未找到{status_label}下载任务。",
                    "items": [],
                    "total": len(tasks),
                    "status": status_name,
                }
            lines = [f"下载任务：{status_label}，共 {len(tasks)} 条，展示前 {len(items)} 条："]
            for item in items:
                details = [
                    item.get("progress") or "进度未知",
                    item.get("size") or "大小未知",
                    item.get("state") or "状态未知",
                    f"下载器:{item.get('downloader') or '默认'}",
                    f"Hash:{item.get('hash_short')}",
                ]
                lines.append(f"{item.get('index')}. {item.get('title')}")
                lines.append("   " + " | ".join(details))
            lines.append("写入操作需确认：可发“暂停下载 1”“恢复下载 1”“删除下载 1”。")
            return {
                "success": True,
                "message": "\n".join(lines),
                "items": items,
                "total": len(tasks),
                "status": status_name,
            }
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 查询下载任务失败：{exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"查询下载任务失败：{exc}", "items": []}

    def _control_download_task(
        self,
        *,
        action: str,
        hash_value: str,
        downloader: str = "",
        delete_files: bool = False,
    ) -> Dict[str, Any]:
        if DownloadChain is None:
            return {"success": False, "message": "操作下载任务失败：当前环境缺少 MoviePilot 下载依赖。"}
        task_hash = str(hash_value or "").strip()
        if len(task_hash) != 40 or not all(ch in "0123456789abcdefABCDEF" for ch in task_hash):
            return {"success": False, "message": "操作下载任务失败：hash 格式无效，请先查询下载任务后按编号操作。"}
        downloader_name = str(downloader or "").strip() or None
        action_name = str(action or "").strip().lower()
        try:
            chain = DownloadChain()
            if action_name in {"pause", "stop"}:
                ok = chain.set_downloading(task_hash, "stop", name=downloader_name)
                label = "暂停"
            elif action_name in {"resume", "start"}:
                ok = chain.set_downloading(task_hash, "start", name=downloader_name)
                label = "恢复"
            elif action_name in {"delete", "remove"}:
                ok = chain.remove_torrents(hashs=[task_hash], downloader=downloader_name, delete_file=bool(delete_files))
                label = "删除"
            else:
                return {"success": False, "message": f"操作下载任务失败：不支持的动作 {action}"}
            suffix = "（包含文件）" if action_name in {"delete", "remove"} and delete_files else ""
            return {
                "success": bool(ok),
                "message": f"{label}下载任务{'成功' if ok else '失败'}：{task_hash[:8]}{suffix}",
                "hash": task_hash,
                "downloader": downloader_name or "",
                "action": action_name,
            }
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 操作下载任务失败：{task_hash} {exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"操作下载任务失败：{exc}"}

    def _query_downloaders(self) -> Dict[str, Any]:
        if SystemConfigOper is None or SystemConfigKey is None:
            return {"success": False, "message": "查询下载器失败：当前环境缺少 MoviePilot 配置依赖。", "items": []}
        try:
            raw_items = SystemConfigOper().get(SystemConfigKey.Downloaders) or []
            items: List[Dict[str, Any]] = []
            for index, item in enumerate(raw_items, 1):
                if not isinstance(item, dict):
                    continue
                items.append({
                    "index": index,
                    "name": str(item.get("name") or ""),
                    "type": str(item.get("type") or ""),
                    "enabled": bool(item.get("enabled")),
                    "default": bool(item.get("default")),
                })
            enabled = [item for item in items if item.get("enabled")]
            if not items:
                return {"success": True, "message": "未配置下载器。", "items": [], "enabled_count": 0}
            lines = [f"下载器配置：共 {len(items)} 个，启用 {len(enabled)} 个"]
            for item in items:
                status = "启用" if item.get("enabled") else "停用"
                default = "，默认" if item.get("default") else ""
                lines.append(f"{item.get('index')}. {item.get('name') or '-'} | {item.get('type') or '-'} | {status}{default}")
            return {
                "success": True,
                "message": "\n".join(lines),
                "items": items,
                "enabled_count": len(enabled),
            }
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 查询下载器失败：{exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"查询下载器失败：{exc}", "items": []}

    def _query_sites(self, *, status: str = "active", name: str = "", limit: int = 30) -> Dict[str, Any]:
        if SiteOper is None:
            return {"success": False, "message": "查询站点失败：当前环境缺少 MoviePilot 站点依赖。", "items": []}
        try:
            status_name = str(status or "active").strip().lower()
            name_filter = str(name or "").strip().lower()
            sites = SiteOper().list_order_by_pri() or []
            items: List[Dict[str, Any]] = []
            for site in sites:
                is_active = bool(getattr(site, "is_active", False))
                if status_name == "active" and not is_active:
                    continue
                if status_name == "inactive" and is_active:
                    continue
                site_name = str(getattr(site, "name", "") or "")
                if name_filter and name_filter not in site_name.lower():
                    continue
                cookie = str(getattr(site, "cookie", "") or "")
                items.append({
                    "index": len(items) + 1,
                    "id": getattr(site, "id", None),
                    "name": site_name,
                    "domain": str(getattr(site, "domain", "") or ""),
                    "url": str(getattr(site, "url", "") or ""),
                    "pri": getattr(site, "pri", None),
                    "is_active": is_active,
                    "has_cookie": bool(cookie),
                    "downloader": str(getattr(site, "downloader", "") or ""),
                    "proxy": bool(getattr(site, "proxy", False)),
                    "timeout": getattr(site, "timeout", None),
                })
            total = len(items)
            items = items[:max(1, min(100, int(limit or 30)))]
            label = {"active": "已启用", "inactive": "已停用", "all": "全部"}.get(status_name, status_name)
            if not items:
                return {"success": True, "message": f"未找到{label}站点。", "items": [], "total": total}
            lines = [f"PT 站点：{label}，共 {total} 个，展示前 {len(items)} 个："]
            for item in items:
                cookie_state = "有Cookie" if item.get("has_cookie") else "无Cookie"
                active_state = "启用" if item.get("is_active") else "停用"
                lines.append(
                    f"{item.get('index')}. {item.get('name') or '-'} | {item.get('domain') or '-'} | "
                    f"{active_state} | {cookie_state} | 优先级:{item.get('pri')} | 下载器:{item.get('downloader') or '默认'}"
                )
            lines.append("说明：这里不会返回 Cookie 明文；如站点搜索失败，优先检查是否启用、Cookie 是否存在、站点绑定下载器是否可用。")
            return {
                "success": True,
                "message": "\n".join(lines),
                "items": items,
                "total": total,
                "status": status_name,
            }
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 查询站点失败：{exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"查询站点失败：{exc}", "items": []}

    def _query_subscribes(
        self,
        *,
        status: str = "all",
        media_type: str = "all",
        name: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        if SubscribeOper is None:
            return {"success": False, "message": "查询订阅失败：当前环境缺少 MoviePilot 订阅依赖。", "items": []}
        try:
            status_name = str(status or "all").strip()
            media_type_name = str(media_type or "all").strip().lower()
            name_filter = str(name or "").strip().lower()
            subscribes = SubscribeOper().list() or []
            items: List[Dict[str, Any]] = []
            for sub in subscribes:
                state = str(getattr(sub, "state", "") or "")
                if status_name != "all" and state != status_name:
                    continue
                sub_type = str(getattr(sub, "type", "") or "").lower()
                if media_type_name != "all" and media_type_name not in {sub_type, "movie" if sub_type == "电影" else sub_type, "tv" if sub_type == "电视剧" else sub_type}:
                    continue
                title = str(getattr(sub, "name", "") or "")
                if name_filter and name_filter not in title.lower():
                    continue
                items.append({
                    "index": len(items) + 1,
                    "id": getattr(sub, "id", None),
                    "name": title or "未命名订阅",
                    "year": str(getattr(sub, "year", "") or ""),
                    "type": str(getattr(sub, "type", "") or ""),
                    "season": getattr(sub, "season", None),
                    "state": state,
                    "total_episode": getattr(sub, "total_episode", None),
                    "lack_episode": getattr(sub, "lack_episode", None),
                    "start_episode": getattr(sub, "start_episode", None),
                    "quality": str(getattr(sub, "quality", "") or ""),
                    "resolution": str(getattr(sub, "resolution", "") or ""),
                    "effect": str(getattr(sub, "effect", "") or ""),
                    "include": str(getattr(sub, "include", "") or ""),
                    "exclude": str(getattr(sub, "exclude", "") or ""),
                    "sites": getattr(sub, "sites", None),
                    "downloader": str(getattr(sub, "downloader", "") or ""),
                    "save_path": str(getattr(sub, "save_path", "") or ""),
                    "best_version": getattr(sub, "best_version", None),
                    "tmdbid": getattr(sub, "tmdbid", None),
                    "doubanid": str(getattr(sub, "doubanid", "") or ""),
                    "last_update": str(getattr(sub, "last_update", "") or ""),
                })
            total = len(items)
            items = items[:max(1, min(100, int(limit or 20)))]
            status_label = {"R": "启用", "S": "暂停", "P": "待处理", "N": "完成", "all": "全部"}.get(status_name, status_name)
            if not items:
                return {"success": True, "message": f"未找到{status_label}订阅。", "items": [], "total": total}
            lines = [f"MP 订阅：{status_label}，共 {total} 条，展示前 {len(items)} 条："]
            for item in items:
                season = f" S{int(item.get('season')):02d}" if item.get("season") else ""
                lack = item.get("lack_episode")
                lack_text = f"缺 {lack} 集" if lack not in (None, "", 0) else "无缺集"
                filters = " / ".join(value for value in [item.get("resolution"), item.get("effect"), item.get("quality")] if value) or "默认规则"
                lines.append(f"{item.get('index')}. #{item.get('id')} {item.get('name')} ({item.get('year') or '-'}){season}")
                lines.append(f"   状态:{item.get('state') or '-'} | {lack_text} | 规则:{filters} | 下载器:{item.get('downloader') or '默认'}")
            lines.append("写入操作需确认：可发“刷新订阅 1”“暂停订阅 1”“恢复订阅 1”“删除订阅 1”。")
            return {"success": True, "message": "\n".join(lines), "items": items, "total": total, "status": status_name}
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 查询订阅失败：{exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"查询订阅失败：{exc}", "items": []}

    def _control_subscribe(self, *, action: str, subscribe_id: int) -> Dict[str, Any]:
        if SubscribeOper is None:
            return {"success": False, "message": "操作订阅失败：当前环境缺少 MoviePilot 订阅依赖。"}
        sid = int(subscribe_id or 0)
        if sid <= 0:
            return {"success": False, "message": "操作订阅失败：订阅 ID 无效。"}
        action_name = str(action or "").strip().lower()
        try:
            oper = SubscribeOper()
            sub = oper.get(sid)
            if not sub:
                return {"success": False, "message": f"操作订阅失败：订阅 #{sid} 不存在。"}
            old_info = sub.to_dict() if hasattr(sub, "to_dict") else {}
            if action_name in {"search", "run"}:
                if Scheduler is None:
                    return {"success": False, "message": "刷新订阅失败：当前环境缺少调度器。"}
                Scheduler().start(job_id="subscribe_search", **{"sid": sid, "state": None, "manual": True})
                return {"success": True, "message": f"已触发订阅刷新：#{sid} {getattr(sub, 'name', '')}", "subscribe_id": sid, "action": action_name}
            if action_name in {"pause", "stop"}:
                updated = oper.update(sid, {"state": "S"})
                label = "暂停"
            elif action_name in {"resume", "start"}:
                updated = oper.update(sid, {"state": "R"})
                label = "恢复"
            elif action_name in {"delete", "remove"}:
                sub_name = str(getattr(sub, "name", "") or "")
                sub_year = str(getattr(sub, "year", "") or "")
                oper.delete(sid)
                if eventmanager and EventType:
                    eventmanager.send_event(EventType.SubscribeDeleted, {"subscribe_id": sid, "subscribe_info": old_info})
                if SubscribeHelper:
                    SubscribeHelper().sub_done_async({"tmdbid": getattr(sub, "tmdbid", None), "doubanid": getattr(sub, "doubanid", None)})
                return {"success": True, "message": f"成功删除订阅：#{sid} {sub_name} ({sub_year})", "subscribe_id": sid, "action": action_name}
            else:
                return {"success": False, "message": f"操作订阅失败：不支持的动作 {action}"}
            if eventmanager and EventType:
                eventmanager.send_event(EventType.SubscribeModified, {
                    "subscribe_id": sid,
                    "old_subscribe_info": old_info,
                    "subscribe_info": updated.to_dict() if updated and hasattr(updated, "to_dict") else {},
                })
            return {"success": True, "message": f"{label}订阅成功：#{sid} {getattr(sub, 'name', '')}", "subscribe_id": sid, "action": action_name}
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 操作订阅失败：{sid} {exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"操作订阅失败：{exc}", "subscribe_id": sid}

    @staticmethod
    def _path_preview(value: Any, max_parts: int = 4) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) <= max_parts:
            return normalized
        prefix = "/" if normalized.startswith("/") else ""
        return f"{prefix}.../" + "/".join(parts[-max_parts:])

    @staticmethod
    def _transfer_status_bool(status: str) -> Optional[bool]:
        name = str(status or "all").strip().lower()
        if name in {"success", "succeeded", "ok", "true", "成功", "已成功"}:
            return True
        if name in {"failed", "fail", "error", "false", "失败", "错误"}:
            return False
        return None

    def _query_download_history(
        self,
        *,
        title: str = "",
        hash_value: str = "",
        limit: int = 10,
        page: int = 1,
    ) -> Dict[str, Any]:
        if DownloadHistory is None or DownloadHistoryOper is None:
            return {"success": False, "message": "查询下载历史失败：当前环境缺少 MoviePilot 下载历史依赖。", "items": []}
        try:
            page_num = max(1, int(page or 1))
            page_size = max(1, min(50, int(limit or 10)))
            title_text = str(title or "").strip()
            hash_text = str(hash_value or "").strip()
            oper = DownloadHistoryOper()
            db = getattr(oper, "_db", None)
            if db is None:
                records = oper.list_by_page(page=1, count=500) or []
                if title_text:
                    title_lower = title_text.lower()
                    records = [
                        item for item in records
                        if title_lower in str(getattr(item, "title", "") or "").lower()
                        or title_lower in str(getattr(item, "torrent_name", "") or "").lower()
                        or title_lower in str(getattr(item, "path", "") or "").lower()
                    ]
                if hash_text:
                    records = [
                        item for item in records
                        if str(getattr(item, "download_hash", "") or "").lower().startswith(hash_text.lower())
                    ]
                total = len(records)
                selected_records = records[(page_num - 1) * page_size:(page_num - 1) * page_size + page_size]
            else:
                query = db.query(DownloadHistory)
                if title_text:
                    like = f"%{title_text}%"
                    query = query.filter(
                        DownloadHistory.title.like(like)
                        | DownloadHistory.torrent_name.like(like)
                        | DownloadHistory.path.like(like)
                    )
                if hash_text:
                    query = query.filter(DownloadHistory.download_hash.like(f"{hash_text}%"))
                query = query.order_by(DownloadHistory.date.desc(), DownloadHistory.id.desc())
                total = query.count()
                selected_records = query.offset((page_num - 1) * page_size).limit(page_size).all()

            items: List[Dict[str, Any]] = []
            for index, record in enumerate(selected_records, start=(page_num - 1) * page_size + 1):
                task_hash = str(getattr(record, "download_hash", "") or "")
                transfer_records = TransferHistory.list_by_hash(download_hash=task_hash) if TransferHistory is not None and task_hash else []
                transfer_success = any(bool(getattr(item, "status", False)) for item in transfer_records or [])
                transfer_failed = any(not bool(getattr(item, "status", False)) for item in transfer_records or [])
                if transfer_success:
                    transfer_status = "success"
                    transfer_status_text = "已入库"
                elif transfer_failed:
                    transfer_status = "failed"
                    transfer_status_text = "整理失败"
                else:
                    transfer_status = "none"
                    transfer_status_text = "未见整理记录"
                transfer_dest = ""
                transfer_error = ""
                if transfer_records:
                    first_transfer = transfer_records[0]
                    transfer_dest = self._path_preview(getattr(first_transfer, "dest", ""))
                    transfer_error = str(getattr(first_transfer, "errmsg", "") or "")[:300]
                item = {
                    "index": index,
                    "id": getattr(record, "id", None),
                    "title": str(getattr(record, "title", "") or "未命名媒体"),
                    "year": str(getattr(record, "year", "") or ""),
                    "type": str(getattr(record, "type", "") or ""),
                    "season": str(getattr(record, "seasons", "") or ""),
                    "episode": str(getattr(record, "episodes", "") or ""),
                    "date": str(getattr(record, "date", "") or ""),
                    "downloader": str(getattr(record, "downloader", "") or ""),
                    "download_hash": task_hash,
                    "download_hash_short": task_hash[:8],
                    "torrent_name": str(getattr(record, "torrent_name", "") or ""),
                    "torrent_site": str(getattr(record, "torrent_site", "") or ""),
                    "username": str(getattr(record, "username", "") or ""),
                    "channel": str(getattr(record, "channel", "") or ""),
                    "path_preview": self._path_preview(getattr(record, "path", "")),
                    "tmdbid": getattr(record, "tmdbid", None),
                    "doubanid": str(getattr(record, "doubanid", "") or ""),
                    "transfer_status": transfer_status,
                    "transfer_status_text": transfer_status_text,
                    "transfer_count": len(transfer_records or []),
                    "transfer_dest_preview": transfer_dest,
                }
                if transfer_error and transfer_status == "failed":
                    item["transfer_error"] = transfer_error
                items.append(item)

            title_label = f"：{title_text or hash_text}" if title_text or hash_text else ""
            if not items:
                return {
                    "success": True,
                    "message": f"未找到下载历史{title_label}。",
                    "items": [],
                    "total": total,
                    "page": page_num,
                    "limit": page_size,
                }
            total_pages = (total + page_size - 1) // page_size if total else 1
            lines = [f"下载历史{title_label}：第 {page_num}/{total_pages} 页，共 {total} 条，展示 {len(items)} 条："]
            for item in items:
                season_episode = " ".join(value for value in [item.get("season"), item.get("episode")] if value)
                lines.append(f"{item.get('index')}. {item.get('title')} ({item.get('year') or '-'}) {season_episode}".rstrip())
                details = [
                    item.get("date") or "-",
                    f"站点:{item.get('torrent_site') or '-'}",
                    f"下载器:{item.get('downloader') or '默认'}",
                    f"Hash:{item.get('download_hash_short') or '-'}",
                    f"整理:{item.get('transfer_status_text')}",
                ]
                lines.append("   " + " | ".join(details))
                if item.get("path_preview"):
                    lines.append(f"   保存：{item.get('path_preview')}")
                if item.get("transfer_dest_preview"):
                    lines.append(f"   入库：{item.get('transfer_dest_preview')}")
                if item.get("transfer_error"):
                    lines.append(f"   整理错误：{item.get('transfer_error')}")
            lines.append("说明：这是只读查询，用于追踪下载提交后是否进入整理流程。")
            return {
                "success": True,
                "message": "\n".join(lines),
                "items": items,
                "total": total,
                "page": page_num,
                "limit": page_size,
            }
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 查询下载历史失败：{exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"查询下载历史失败：{exc}", "items": []}

    def _query_transfer_history(
        self,
        *,
        title: str = "",
        status: str = "all",
        limit: int = 10,
        page: int = 1,
    ) -> Dict[str, Any]:
        if TransferHistory is None:
            return {"success": False, "message": "查询整理历史失败：当前环境缺少 MoviePilot 整理历史依赖。", "items": []}
        try:
            page_num = max(1, int(page or 1))
            page_size = max(1, min(50, int(limit or 10)))
            status_bool = self._transfer_status_bool(status)
            title_text = str(title or "").strip()
            search_text = title_text
            if title_text and jieba is not None:
                try:
                    search_text = "%".join(jieba.cut(title_text, HMM=False))
                except Exception:
                    search_text = title_text

            if search_text:
                records = TransferHistory.list_by_title(title=search_text, page=1, count=-1, status=None) or []
                if status_bool is not None:
                    records = [item for item in records if bool(getattr(item, "status", False)) is status_bool]
            else:
                records = TransferHistory.list_by_page(page=1, count=-1, status=status_bool) or []

            total = len(records)
            start = (page_num - 1) * page_size
            selected_records = records[start:start + page_size]
            items: List[Dict[str, Any]] = []
            for index, record in enumerate(selected_records, start=start + 1):
                media_type = str(getattr(record, "type", "") or "")
                if media_type_to_agent is not None:
                    try:
                        media_type = media_type_to_agent(media_type)
                    except Exception:
                        pass
                status_ok = bool(getattr(record, "status", False))
                item = {
                    "index": index,
                    "id": getattr(record, "id", None),
                    "title": str(getattr(record, "title", "") or "未命名媒体"),
                    "year": str(getattr(record, "year", "") or ""),
                    "type": media_type,
                    "category": str(getattr(record, "category", "") or ""),
                    "season": str(getattr(record, "seasons", "") or ""),
                    "episode": str(getattr(record, "episodes", "") or ""),
                    "mode": str(getattr(record, "mode", "") or ""),
                    "status": "success" if status_ok else "failed",
                    "status_text": "成功" if status_ok else "失败",
                    "date": str(getattr(record, "date", "") or ""),
                    "downloader": str(getattr(record, "downloader", "") or ""),
                    "download_hash_short": str(getattr(record, "download_hash", "") or "")[:8],
                    "src_preview": self._path_preview(getattr(record, "src", "")),
                    "dest_preview": self._path_preview(getattr(record, "dest", "")),
                    "tmdbid": getattr(record, "tmdbid", None),
                    "doubanid": str(getattr(record, "doubanid", "") or ""),
                }
                errmsg = str(getattr(record, "errmsg", "") or "").strip()
                if errmsg and not status_ok:
                    item["errmsg"] = errmsg[:300]
                items.append(item)

            status_name = str(status or "all").strip().lower()
            status_label = "成功" if status_bool is True else "失败" if status_bool is False else "全部"
            title_label = f"：{title_text}" if title_text else ""
            if not items:
                return {
                    "success": True,
                    "message": f"未找到{status_label}整理历史{title_label}。",
                    "items": [],
                    "total": total,
                    "page": page_num,
                    "limit": page_size,
                    "status": status_name,
                }

            total_pages = (total + page_size - 1) // page_size if total else 1
            lines = [f"整理历史{title_label}：{status_label}，第 {page_num}/{total_pages} 页，共 {total} 条，展示 {len(items)} 条："]
            for item in items:
                season_episode = " ".join(value for value in [item.get("season"), item.get("episode")] if value)
                label_parts = [
                    item.get("status_text") or "-",
                    item.get("type") or "-",
                    item.get("mode") or "-",
                    item.get("date") or "-",
                ]
                lines.append(f"{item.get('index')}. {item.get('title')} ({item.get('year') or '-'}) {season_episode}".rstrip())
                lines.append("   " + " | ".join(label_parts))
                if item.get("dest_preview"):
                    lines.append(f"   目标：{item.get('dest_preview')}")
                if item.get("errmsg"):
                    lines.append(f"   错误：{item.get('errmsg')}")
            lines.append("说明：这是只读查询，用于判断下载后是否已经整理入库。")
            return {
                "success": True,
                "message": "\n".join(lines),
                "items": items,
                "total": total,
                "page": page_num,
                "limit": page_size,
                "status": status_name,
            }
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 查询整理历史失败：{exc}\n{traceback.format_exc()}")
            return {"success": False, "message": f"查询整理历史失败：{exc}", "items": []}

    def _execute_media_subscribe(self, keyword: str, immediate_search: bool) -> str:
        if not all([MetaInfo, SubscribeChain]):
            return "订阅失败：当前环境缺少 MoviePilot 订阅依赖。"
        meta = MetaInfo(keyword)
        try:
            sid, message = SubscribeChain().add(
                title=keyword,
                year=meta.year,
                mtype=meta.type,
                season=meta.begin_season,
                username="agentresourceofficer-feishu",
                exist_ok=True,
                message=False,
            )
            if not sid:
                return f"订阅失败：{keyword}\n原因：{message}"
            lines = [f"已创建订阅：{keyword}", f"订阅ID：{sid}", f"结果：{message}"]
            if immediate_search and Scheduler is not None:
                Scheduler().start(job_id="subscribe_search", **{"sid": sid, "state": None, "manual": True})
                lines.append("已触发一次订阅搜索。")
            return "\n".join(lines)
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 订阅失败：{keyword} {exc}\n{traceback.format_exc()}")
            return f"订阅失败：{keyword}\n错误：{exc}"

    @staticmethod
    def _format_media_label(mediainfo: Any, season: Optional[int] = None) -> str:
        title = getattr(mediainfo, "title", "") or "未知媒体"
        year = getattr(mediainfo, "year", None)
        label = f"{title} ({year})" if year else title
        media_type = getattr(mediainfo, "type", None)
        media_type_name = getattr(media_type, "name", "")
        if media_type_name == "TV" and season:
            return f"{label} 第{season}季"
        return label

    def _set_search_cache(self, cache_key: str, keyword: str, mediainfo: Any, results: List[Any]) -> None:
        with self._search_cache_lock:
            now = time.time()
            expired_keys = [
                key
                for key, item in self._search_cache.items()
                if now - float((item or {}).get("ts") or 0) > 1800
            ]
            for key in expired_keys:
                self._search_cache.pop(key, None)
            while len(self._search_cache) >= self._search_cache_limit:
                oldest_key = min(
                    self._search_cache,
                    key=lambda key: float((self._search_cache.get(key) or {}).get("ts") or 0),
                )
                self._search_cache.pop(oldest_key, None)
            self._search_cache[cache_key] = {
                "ts": now,
                "keyword": keyword,
                "mediainfo": mediainfo,
                "results": list(results or []),
            }

    def _get_search_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        with self._search_cache_lock:
            item = self._search_cache.get(cache_key)
            if not item:
                return None
            if time.time() - float(item.get("ts") or 0) > 1800:
                self._search_cache.pop(cache_key, None)
                return None
            return item

    def _run_p115_manual_transfer_batch(self, paths: List[str], chat_id: str, open_id: str) -> None:
        summaries = [self._execute_p115_manual_transfer(path) for path in paths]
        self.reply_text(chat_id, open_id, "\n\n".join(item for item in summaries if item))

    def _run_p115_manual_transfer(self, path: str, chat_id: str, open_id: str) -> None:
        self.reply_text(chat_id, open_id, self._execute_p115_manual_transfer(path))

    def _get_p115_manual_transfer_paths(self) -> List[str]:
        try:
            config = self.plugin.systemconfig.get("plugin.P115StrmHelper") or {}
            raw = str(config.get("pan_transfer_paths") or "").strip()
            return [line.strip() for line in raw.splitlines() if line.strip()]
        except Exception as exc:
            logger.warning(f"[AgentResourceOfficer][Feishu] 获取待整理目录失败：{exc}")
            return []

    def _execute_p115_manual_transfer(self, path: str) -> str:
        log_path = Path("/config/logs/plugins/P115StrmHelper.log")
        log_offset = self._safe_log_offset(log_path)
        try:
            service_module = importlib.import_module("app.plugins.p115strmhelper.service")
            servicer = getattr(service_module, "servicer", None)
            if not servicer or not getattr(servicer, "monitorlife", None):
                return "刮削失败：P115StrmHelper 未初始化或未启用。"
            result = servicer.monitorlife.once_transfer(path)
            summary = self._format_p115_manual_transfer_result(result)
            return summary or self._build_p115_manual_transfer_summary(log_path, log_offset, path) or f"刮削完成：{path}"
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 手动刮削失败：{path} {exc}\n{traceback.format_exc()}")
            return f"刮削失败：{path}\n错误：{exc}"

    def _format_p115_manual_transfer_result(self, result: Any) -> Optional[str]:
        if not isinstance(result, dict):
            return None
        path = result.get("path") or ""
        failed_items = result.get("failed_items") or []
        lines = [
            f"刮削完成：{path}",
            f"总计：{result.get('total', 0)} 个项目（文件 {result.get('files', 0)}，文件夹 {result.get('dirs', 0)}）",
            f"成功：{result.get('success', 0)} 个",
            f"失败：{result.get('failed', 0)} 个",
            f"跳过：{result.get('skipped', 0)} 个",
        ]
        if result.get("error"):
            lines.append(f"错误：{result.get('error')}")
        if failed_items:
            lines.append("失败示例：")
            lines.extend(f"- {item}" for item in failed_items[:3])
            if len(failed_items) > 3:
                lines.append(f"- 还有 {len(failed_items) - 3} 项未展示")
        lines.extend(self._p115_strm_followup_lines(path))
        return "\n".join(lines)

    def _p115_strm_followup_lines(self, path: str) -> List[str]:
        hint = self._get_p115_strm_hint_path() or path
        return [
            "如需增量生成 STRM，请再发送：生成STRM",
            "如需按全部媒体库全量生成，请再发送：全量STRM",
            f"如需指定路径全量生成，请再发送：指定路径STRM {hint}",
        ]

    def _get_p115_strm_hint_path(self) -> Optional[str]:
        try:
            config = self.plugin.systemconfig.get("plugin.P115StrmHelper") or {}
            paths = str(config.get("full_sync_strm_paths") or "").strip()
            first_line = next((line.strip() for line in paths.splitlines() if line.strip()), "")
            if not first_line:
                return None
            parts = first_line.split("#")
            return parts[1].strip() if len(parts) >= 2 and parts[1].strip() else None
        except Exception:
            return None

    @staticmethod
    def _safe_log_offset(log_path: Path) -> int:
        try:
            return log_path.stat().st_size if log_path.exists() else 0
        except Exception:
            return 0

    def _build_p115_manual_transfer_summary(self, log_path: Path, start_offset: int, path: str) -> Optional[str]:
        try:
            if not log_path.exists():
                return None
            with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                f.seek(start_offset)
                chunk = f.read()
            if not chunk:
                return None
            path_re = re.escape(path)
            pattern = re.compile(
                rf"手动网盘整理完成 - 路径: {path_re}\n"
                rf"\s*总计: (?P<total>\d+) 个项目 \(文件: (?P<files>\d+), 文件夹: (?P<dirs>\d+)\)\n"
                rf"\s*成功: (?P<success>\d+) 个\n"
                rf"\s*失败: (?P<failed>\d+) 个\n"
                rf"\s*跳过: (?P<skipped>\d+) 个",
                re.S,
            )
            match = pattern.search(chunk)
            if not match:
                return None
            summary = (
                f"刮削完成：{path}\n"
                f"总计：{match.group('total')} 个项目（文件 {match.group('files')}，文件夹 {match.group('dirs')}）\n"
                f"成功：{match.group('success')} 个\n"
                f"失败：{match.group('failed')} 个\n"
                f"跳过：{match.group('skipped')} 个"
            )
            return summary + "\n" + "\n".join(self._p115_strm_followup_lines(path))
        except Exception:
            return None

    def _submit_p115_command(self, command_text: str, chat_id: str, open_id: str) -> None:
        if PluginManager is not None:
            try:
                if not PluginManager().running_plugins.get("P115StrmHelper"):
                    self.reply_text(chat_id, open_id, "P115StrmHelper 未加载或未启用，无法执行 STRM 命令。")
                    return
            except Exception:
                pass
        self._submit_moviepilot_command(command_text, chat_id, open_id)

    def _submit_moviepilot_command(self, command_text: str, chat_id: str, open_id: str) -> None:
        if eventmanager is None or EventType is None:
            self.reply_text(chat_id, open_id, "当前环境缺少 MoviePilot 事件总线，无法转发该命令。")
            return
        eventmanager.send_event(
            EventType.CommandExcute,
            {"cmd": command_text, "source": None, "user": open_id or chat_id or "feishu"},
        )
        self.reply_text(chat_id, open_id, f"已接收命令：{command_text}\n任务已提交给 MoviePilot。")

    def _map_text_to_command(self, text: str) -> Optional[str]:
        text = self._sanitize_text(text)
        if not text:
            return None
        if text.startswith("/"):
            return text
        normalized = text.strip().lower()
        if normalized in {"n", "next", "下一页", "下页"} or normalized.startswith("n "):
            return f"/smart_pick {text}".strip()
        shortcut_match = re.fullmatch(r"(\d+)(?:\s+(.+))?", text)
        if shortcut_match:
            rest = str(shortcut_match.group(2) or "").strip()
            if not rest or "=" in rest or rest.startswith("/"):
                return f"/smart_pick {text}".strip()
        first_url = self.plugin._extract_first_url(text)
        if first_url and (self.plugin._is_115_url(first_url) or self.plugin._is_quark_url(first_url)):
            return f"/smart_entry {text}".strip()

        alias_map = self.parse_alias_text(self.command_aliases)
        parts = text.split(maxsplit=1)
        alias = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        target = alias_map.get(alias)
        if not target:
            for alias_key in sorted(alias_map.keys(), key=len, reverse=True):
                if not text.startswith(alias_key):
                    continue
                remain = text[len(alias_key):].strip()
                target = alias_map.get(alias_key)
                if target:
                    if target == "/smart_pick" and alias_key in {"详情", "审查"}:
                        return f"{target} {alias_key} {remain}".strip()
                    return f"{target} {remain}".strip()
            return None
        if target == "/smart_pick" and alias in {"详情", "审查"}:
            return f"{target} {alias} {rest}".strip()
        return f"{target} {rest}".strip()

    def _is_duplicate_event(self, event_id: str) -> bool:
        now = time.time()
        with self._event_lock:
            expired = [key for key, ts in self._event_cache.items() if now - ts > 600]
            for key in expired:
                self._event_cache.pop(key, None)
            if event_id in self._event_cache:
                return True
            self._event_cache[event_id] = now
        return self._is_duplicate_event_cross_instance(event_id, now)

    @staticmethod
    def _is_duplicate_event_cross_instance(event_id: str, now: float) -> bool:
        try:
            _EVENT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _EVENT_CACHE_FILE.open("a+", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.seek(0)
                raw = f.read().strip()
                cache = json.loads(raw) if raw else {}
                cache = {key: ts for key, ts in cache.items() if isinstance(ts, (int, float)) and now - float(ts) <= 600}
                if event_id in cache:
                    f.seek(0)
                    f.truncate()
                    json.dump(cache, f, ensure_ascii=False)
                    f.flush()
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    return True
                cache[event_id] = now
                f.seek(0)
                f.truncate()
                json.dump(cache, f, ensure_ascii=False)
                f.flush()
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as exc:
            logger.warning(f"[AgentResourceOfficer][Feishu] 跨实例事件去重失败：{exc}")
        return False

    def _is_allowed(self, chat_id: str, user_open_id: str) -> bool:
        return bool(
            self.allow_all
            or (chat_id and chat_id in self.allowed_chat_ids)
            or (user_open_id and user_open_id in self.allowed_user_ids)
        )

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, dict):
            return str(content.get("text") or "").strip()
        if isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                return content.strip()
            return str(payload.get("text") or "").strip()
        return ""

    @staticmethod
    def _sanitize_text(text: str) -> str:
        text = re.sub(r"<at[^>]*>.*?</at>", " ", text or "", flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _is_help_request(text: str) -> bool:
        return FeishuChannel._sanitize_text(text) in {"帮助", "/help", "help"}

    @staticmethod
    def _is_menu_request(text: str) -> bool:
        return FeishuChannel._sanitize_text(text) in {"菜单", "/menu", "menu", "面板", "控制面板"}

    def _build_help_text(self) -> str:
        aliases = self.parse_alias_text(self.command_aliases)
        alias_text = "\n".join(f"{key} -> {value}" for key, value in aliases.items()) or "未配置别名"
        return (
            "可用命令：\n"
            f"{', '.join(self.command_whitelist)}\n\n"
            "别名：\n"
            f"{alias_text}\n\n"
            "快捷入口：发送“菜单”可查看可复制的快捷命令。"
        )

    @staticmethod
    def _build_menu_text() -> str:
        return (
            "快捷菜单\n"
            "1. 盘搜搜索 片名\n"
            "2. 影巢搜索 片名\n"
            "3. 搜索 片名\n"
            "4. MP搜索 片名 / PT搜索 片名\n"
            "5. 转存 片名（默认 115）\n"
            "6. 夸克转存 片名\n"
            "7. 下载 片名\n"
            "8. 更新检查 片名\n"
            "9. 选择 序号 / 详情 序号 / n\n"
            "10. 115登录 / 115状态 / 115任务\n"
            "11. 影巢签到 / 影巢签到日志"
        )

    @staticmethod
    def _cache_key(chat_id: str, open_id: str) -> str:
        return f"feishu::{chat_id or ''}::{open_id or ''}"

    @staticmethod
    def _brief_response_error(data: Any) -> str:
        if not isinstance(data, dict):
            return "body=<non-json>"
        code = str(data.get("code") or "").strip()
        msg = str(data.get("msg") or data.get("message") or "").strip()
        parts: List[str] = []
        if code:
            parts.append(f"code={code}")
        if msg:
            parts.append(f"msg={msg}")
        return " ".join(parts) if parts else "body=<json>"

    def reply_text(self, chat_id: str, open_id: str, text: str) -> None:
        if not self.reply_enabled or not self.app_id or not self.app_secret:
            return
        receive_id = chat_id if self.reply_receive_id_type == "chat_id" else open_id
        if not receive_id:
            return
        access_token = self._get_tenant_access_token()
        if not access_token or RequestUtils is None:
            return
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={self.reply_receive_id_type}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        response = RequestUtils(headers=headers).post(url=url, json=payload)
        if response is None:
            logger.error("[AgentResourceOfficer][Feishu] 发送文本失败：无响应")
            return
        try:
            data = response.json()
        except Exception:
            data = {}
        if response.status_code != 200 or data.get("code") not in (0, None):
            logger.error(
                f"[AgentResourceOfficer][Feishu] 发送文本失败: status={response.status_code} "
                f"{self._brief_response_error(data)}"
            )

    def reply_qrcode_data_url(self, chat_id: str, open_id: str, data_url: str) -> None:
        text = str(data_url or "").strip()
        if not text.startswith("data:image/") or ";base64," not in text:
            return
        _, _, payload = text.partition(";base64,")
        try:
            image_bytes = b64decode(payload)
        except Exception as exc:
            logger.error(f"[AgentResourceOfficer][Feishu] 解码二维码失败：{exc}")
            return
        image_key = self._upload_image(image_bytes=image_bytes, file_name="p115-qrcode.png")
        if image_key:
            self._reply_image(chat_id, open_id, image_key)

    def _upload_image(self, image_bytes: bytes, file_name: str) -> Optional[str]:
        if not image_bytes or RequestUtils is None:
            return None
        access_token = self._get_tenant_access_token()
        if not access_token:
            return None
        response = RequestUtils(headers={"Authorization": f"Bearer {access_token}"}).post(
            url="https://open.feishu.cn/open-apis/im/v1/images",
            data={"image_type": "message"},
            files={"image": (file_name, image_bytes, "image/png")},
        )
        if response is None:
            logger.error("[AgentResourceOfficer][Feishu] 上传图片失败：无响应")
            return None
        try:
            data = response.json()
        except Exception:
            data = {}
        if response.status_code != 200 or data.get("code") not in (0, None):
            logger.error(
                f"[AgentResourceOfficer][Feishu] 上传图片失败: status={response.status_code} "
                f"{self._brief_response_error(data)}"
            )
            return None
        return str(((data.get("data") or {}).get("image_key")) or "").strip() or None

    def _reply_image(self, chat_id: str, open_id: str, image_key: str) -> None:
        if not image_key or RequestUtils is None:
            return
        receive_id = chat_id if self.reply_receive_id_type == "chat_id" else open_id
        if not receive_id:
            return
        access_token = self._get_tenant_access_token()
        if not access_token:
            return
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={self.reply_receive_id_type}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_key}, ensure_ascii=False),
        }
        response = RequestUtils(headers=headers).post(url=url, json=payload)
        if response is None:
            logger.error("[AgentResourceOfficer][Feishu] 发送图片失败：无响应")
            return
        try:
            data = response.json()
        except Exception:
            data = {}
        if response.status_code != 200 or data.get("code") not in (0, None):
            logger.error(
                f"[AgentResourceOfficer][Feishu] 发送图片失败: status={response.status_code} "
                f"{self._brief_response_error(data)}"
            )

    def _get_tenant_access_token(self) -> Optional[str]:
        if RequestUtils is None:
            return None
        now = time.time()
        with self._token_lock:
            token = self._token_cache.get("token")
            expires_at = float(self._token_cache.get("expires_at") or 0)
            if token and now < expires_at - 60:
                return token
            response = RequestUtils(content_type="application/json").post(
                url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            if response is None:
                logger.error("[AgentResourceOfficer][Feishu] 获取 tenant_access_token 失败：无响应")
                return None
            try:
                data = response.json()
            except Exception as exc:
                logger.error(f"[AgentResourceOfficer][Feishu] token 响应解析失败：{exc}")
                return None
            token = data.get("tenant_access_token")
            expire = int(data.get("expire") or 0)
            if not token:
                logger.error(
                    f"[AgentResourceOfficer][Feishu] token 缺失：{self._brief_response_error(data)}"
                )
                return None
            self._token_cache = {"token": token, "expires_at": now + expire}
            return token
