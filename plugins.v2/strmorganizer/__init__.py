# plugins/strmorganizer/__init__.py

import time
from pathlib import Path
from typing import Dict, Any, List
from threading import Lock

from app.core.plugin import _PluginBase
from app.utils.cron import CronTrigger
from app.log import logger
from app.core.config import settings

from .scanner import scan_missing_strm
from .copier import copy_strm
from .deleter import delete_strm
from .csv_report import write_csv


class StrmOrganizer(_PluginBase):

    plugin_name = "STRM 整理工具"
    plugin_desc = "扫描、删除、复制 STRM 文件（V2）"
    plugin_version = "1.0.6"
    plugin_author = "Daveccx"
    plugin_icon = "mdi-folder-refresh"

    _lock = Lock()
    _status = "idle"
    _progress = 0
    _last_message = ""

    def init_plugin(self, config: Dict[str, Any] = None):
        self.config = config or {}

    # ========= API =========
    def get_api(self):
        return [
            {
                "path": "/run",
                "endpoint": self.api_run,
                "methods": ["POST"],
                "summary": "立即执行 STRM 整理"
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "summary": "获取执行状态"
            }
        ]

    def api_run(self):
        if self._lock.locked():
            return {"success": False, "message": "任务正在运行"}

        self._run_task(manual=True)
        return {"success": True, "message": "任务已触发"}

    def api_status(self):
        return {
            "status": self._status,
            "progress": self._progress,
            "message": self._last_message
        }

    # ========= 状态页 =========
    def get_page(self):
        return [
            {
                "component": "VCard",
                "props": {"title": "STRM 整理工具状态"},
                "content": [
                    {
                        "component": "VText",
                        "props": {"text": f"状态：{self._status}"}
                    },
                    {
                        "component": "VProgressLinear",
                        "props": {
                            "model": self._progress,
                            "height": 10,
                            "striped": True
                        }
                    },
                    {
                        "component": "VText",
                        "props": {"text": self._last_message}
                    },
                    {
                        "component": "VBtn",
                        "props": {"text": "立即执行", "color": "primary"},
                        "events": {
                            "click": {
                                "api": "plugin/StrmOrganizer/run",
                                "method": "post"
                            }
                        }
                    }
                ]
            }
        ]

    # ========= 定时 =========
    def get_service(self):
        cron = self.config.get("cron")
        if not cron or not self.config.get("enabled"):
            return []

        return [{
            "id": "strm_organizer",
            "name": "STRM 整理工具",
            "trigger": CronTrigger.from_crontab(cron),
            "func": self._run_task,
            "kwargs": {}
        }]

    # ========= 执行 =========
    def _run_task(self, manual=False):
        if not self._lock.acquire(blocking=False):
            return

        try:
            self._status = "running"
            self._progress = 0

            mode = self.config.get("mode", "scan")
            dry = self.config.get("dry_run", False)

            target = Path(self.config.get("target_root", ""))
            missing = scan_missing_strm(target)

            self._progress = 30
            csv = write_csv(missing, self.config.get("csv_name", "strm_result.csv"))

            if mode == "delete":
                delete_strm(missing, dry)
            elif mode == "copy":
                copy_strm(
                    missing,
                    target,
                    Path(self.config.get("full_root")),
                    Path(self.config.get("output_root")),
                    dry
                )

            self._progress = 100
            self._status = "done"
            self._last_message = f"完成，目录数：{len(missing)}\nCSV：{csv}"
            self.post_message("STRM 整理完成", self._last_message)

        finally:
            self._lock.release()
