"""MoviePilot native UI for the PiNAS storage cleanup console."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fastapi import Body
from fastapi.responses import JSONResponse

from app.plugins import _PluginBase

from .bridge_client import DEFAULT_GATEWAY, DEFAULT_TOKEN_FILE, CleanupBridge


class StorageCleanup(_PluginBase):
    plugin_name = "存储清理"
    plugin_desc = "一键清理全链路耦合：自动发现 MoviePilot、qB、媒体目录与硬链接关系，联动核验做种、H&R 后安全释放空间。无特定媒体服务器也能使用。需先部署 NAS 清理台服务。"
    plugin_icon = "https://raw.githubusercontent.com/Hommchen/nas-storage-cleanup-ui-public/main/public/storagecleanup.svg"
    plugin_version = "1.0.15"
    plugin_author = "Hommchen"
    author_url = "https://github.com/Hommchen/nas-storage-cleanup-ui-public"
    plugin_config_prefix = "storagecleanup_"
    plugin_order = 34
    auth_level = 1

    def init_plugin(self, config: dict | None = None) -> None:
        settings = config or {}
        self._bridge = CleanupBridge(
            gateway=str(settings.get("gateway_url") or DEFAULT_GATEWAY),
            token_file=str(settings.get("token_file") or DEFAULT_TOKEN_FILE),
        )

    @staticmethod
    def get_state() -> bool:
        return True

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/v1.0.15/assets"

    @staticmethod
    def get_form() -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "key": "gateway_url",
                "type": "text",
                "title": "清理台后台地址（管理员）",
                "required": True,
                "placeholder": DEFAULT_GATEWAY,
                "help": "由 NAS 管理员部署清理台后提供；插件不会通过 SSH 登录 NAS。",
            },
            {
                "key": "token_file",
                "type": "text",
                "title": "控制令牌文件路径",
                "required": True,
                "placeholder": DEFAULT_TOKEN_FILE,
                "help": "由 NAS 管理员部署清理台后提供；仅填写 MoviePilot 容器内可读的文件路径，不填写令牌内容。",
            },
        ], {
            "gateway_url": DEFAULT_GATEWAY,
            "token_file": DEFAULT_TOKEN_FILE,
        }

    @staticmethod
    def get_page() -> List[dict]:
        return []

    @staticmethod
    def get_sidebar_nav() -> List[Dict[str, Any]]:
        return [
            {
                "nav_key": "main",
                "title": "存储清理",
                "icon": "mdi-broom",
                "section": "organize",
                "permission": "manage",
                "order": 34,
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            self._route("/status", self.status, ["GET"], "读取清理台状态"),
            self._route("/config", self.config_status, ["GET"], "读取清理台配置"),
            self._route("/config", self.update_config, ["POST"], "保存清理台配置"),
            self._route("/discover", self.discover, ["GET"], "自动发现 NAS 配置"),
            self._route("/snapshot", self.snapshot, ["GET"], "读取资源快照"),
            self._route("/refresh", self.refresh, ["POST"], "刷新资源快照"),
            self._route("/plan", self.plan, ["POST"], "生成清理计划"),
            self._route("/execute", self.execute, ["POST"], "执行清理计划"),
            self._route("/recovery", self.recovery_status, ["GET"], "读取恢复状态"),
            self._route("/recovery", self.recovery, ["POST"], "执行事务恢复"),
            self._route(
                "/protection-gaps",
                self.protection_gaps,
                ["GET"],
                "读取 H&R 缺口",
            ),
        ]

    @staticmethod
    def _route(
        path: str,
        endpoint: Any,
        methods: List[str],
        summary: str,
    ) -> Dict[str, Any]:
        return {
            "path": path,
            "endpoint": endpoint,
            "methods": methods,
            "auth": "bear",
            "summary": summary,
        }

    def _proxy(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> JSONResponse:
        try:
            status, content = self._bridge.request(
                path,
                method=method,
                payload=payload,
            )
        except RuntimeError as exc:
            status, content = 503, {
                "ok": False,
                "error": {
                    "code": "cleanup_bridge_not_ready",
                    "message": str(exc),
                },
            }
        return JSONResponse(status_code=status, content=content)

    def status(self) -> JSONResponse:
        status, health = self._bridge.request("/health")
        if status != 200 or not health.get("ok"):
            return JSONResponse(status_code=status, content=health)
        snapshot_status, snapshot = self._bridge.request("/v1/snapshot")
        if snapshot_status != 200:
            return JSONResponse(status_code=snapshot_status, content=snapshot)
        return JSONResponse(
            content={
                "ok": True,
                "health": health,
                "snapshot": snapshot.get("snapshot"),
            }
        )

    def snapshot(self) -> JSONResponse:
        return self._proxy("/v1/snapshot")

    def config_status(self) -> JSONResponse:
        return self._proxy("/v1/config")

    def update_config(self, payload: dict = Body(...)) -> JSONResponse:
        return self._proxy("/v1/config", method="POST", payload=payload)

    def discover(self) -> JSONResponse:
        return self._proxy("/v1/discover")

    def refresh(self, payload: dict = Body(default={})) -> JSONResponse:
        return self._proxy("/v1/refresh", method="POST", payload=payload)

    def plan(self, payload: dict = Body(...)) -> JSONResponse:
        return self._proxy("/v1/plan", method="POST", payload=payload)

    def execute(self, payload: dict = Body(...)) -> JSONResponse:
        return self._proxy("/v1/execute", method="POST", payload=payload)

    def recovery_status(self) -> JSONResponse:
        return self._proxy("/v1/recovery")

    def recovery(self, payload: dict = Body(...)) -> JSONResponse:
        return self._proxy("/v1/recovery", method="POST", payload=payload)

    def protection_gaps(self) -> JSONResponse:
        return self._proxy("/v1/protection-gaps")

    @staticmethod
    def stop_service() -> None:
        return None
