from fastapi import APIRouter
from typing import List
from pydantic import BaseModel
from .utils import scan_missing_strm, find_in_full_lib, copy_with_structure
from fastapi.responses import StreamingResponse
from io import StringIO
import csv
import os

class Plugin(_PluginBase):  # ✅ 继承 _PluginBase
    plugin_name = "filemanagerstrm"
    plugin_version = "1.0.0"
    plugin_desc = "扫描缺失 STRM 并管理/复制"

    def __init__(self):
        super().__init__()  # 调用父类初始化
        self.router = APIRouter(prefix="/filemanagerstrm")
        self._last_scan = []

    def get_api(self):
        return [
            {"path": "/scan_missing", "endpoint": self.api_scan_missing, "methods": ["GET"]},
            {"path": "/copy_from_full", "endpoint": self.api_copy_from_full, "methods": ["POST"]},
            {"path": "/download_csv", "endpoint": self.api_download_csv, "methods": ["GET"]}
        ]

    class ScanResponse(BaseModel):
        missing_paths: List[str]

    class CopyRequest(BaseModel):
        src_root: str
        full_root: str
        out_root: str

    class CopyResponse(BaseModel):
        copied: List[str]
        failed: List[str]

    def api_scan_missing(self):
        src_root = os.environ.get("MOVIEPILOT_STRM_ROOT", "")
        if not src_root or not os.path.exists(src_root):
            return Plugin.ScanResponse(missing_paths=[])
        missing = scan_missing_strm(src_root)
        self._last_scan = missing
        return Plugin.ScanResponse(missing_paths=missing)

    def api_copy_from_full(self, body: CopyRequest):
        if not all([os.path.exists(body.src_root), os.path.exists(body.full_root)]):
            return Plugin.CopyResponse(copied=[], failed=[])
        missing = scan_missing_strm(body.src_root)
        copied, failed = [], []
        for p in missing:
            candidate = find_in_full_lib(p, body.full_root, body.src_root)
            if candidate:
                try:
                    copy_with_structure(candidate, body.full_root, body.out_root)
                    copied.append(p)
                except Exception:
                    failed.append(p)
            else:
                failed.append(p)
        return Plugin.CopyResponse(copied=copied, failed=failed)

    def api_download_csv(self):
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["路径"])
        for row in getattr(self, "_last_scan", []):
            writer.writerow([row])
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=missing_strm.csv"}
        )
