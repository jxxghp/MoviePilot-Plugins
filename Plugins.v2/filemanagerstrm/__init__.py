import os
import shutil
from fastapi import APIRouter
from typing import List
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from io import StringIO
import csv

# 核心依赖来自 MoviePilot 环境，不需要放到 requirements.txt
from moviepilot.plugins._plugin_base import _PluginBase

class Filemanagerstrm(_PluginBase):
    plugin_name = "filemanagerstrm"
    plugin_version = "1.0.0"
    plugin_desc = "扫描缺失 STRM 并提取/复制"

    def __init__(self):
        super().__init__()
        self.router = APIRouter(prefix="/filemanagerstrm")
        self._last_scan = []

    def get_api(self):
        return [
            {
                "path": "/scan_missing",
                "endpoint": self.api_scan_missing,
                "methods": ["GET"],
                "summary": "扫描缺失 STRM 并返回路径列表"
            },
            {
                "path": "/copy_from_full",
                "endpoint": self.api_copy_from_full,
                "methods": ["POST"],
                "summary": "从完整库复制缺失 STRM 所在目录"
            },
            {
                "path": "/download_csv",
                "endpoint": self.api_download_csv,
                "methods": ["GET"],
                "summary": "下载上次扫描结果 CSV"
            }
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

    def is_meta_only(self, files):
        return files and all(f.lower().endswith((
            ".jpg", ".png", ".nfo", ".srt", ".ass", ".ssa", ".webp"
        )) for f in files)

    def has_strm(self, files):
        return any(f.lower().endswith(".strm") for f in files)

    def is_final_media_dir(self, path):
        items = os.listdir(path)
        files = [f for f in items if os.path.isfile(os.path.join(path, f))]
        dirs = [d for d in items if os.path.isdir(os.path.join(path, d))]
        return not dirs and self.is_meta_only(files)

    def scan_missing_strm(self, root):
        result = []
        for cur, dirs, files in os.walk(root):
            if self.is_final_media_dir(cur) and not self.has_strm(files):
                result.append(cur)
        return result

    def find_in_full_lib(self, target, full_root, src_root):
        rel = os.path.relpath(target, start=src_root)
        candidate = os.path.join(full_root, rel)
        return candidate if os.path.exists(candidate) else None

    def copy_with_structure(self, src, src_root, dst_root):
        rel = os.path.relpath(src, src_root)
        dst = os.path.join(dst_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.exists(dst):
            shutil.copytree(src, dst)

    def api_scan_missing(self):
        root = os.environ.get("MOVIEPILOT_STRM_ROOT", "")
        if not root or not os.path.isdir(root):
            return Filemanagerstrm.ScanResponse(missing_paths=[])
        missing = self.scan_missing_strm(root)
        self._last_scan = missing
        return Filemanagerstrm.ScanResponse(missing_paths=missing)

    def api_copy_from_full(self, body: CopyRequest):
        if not body.src_root or not body.full_root:
            return Filemanagerstrm.CopyResponse(copied=[], failed=[])

        missing = self.scan_missing_strm(body.src_root)
        copied, failed = [], []
        for p in missing:
            candidate = self.find_in_full_lib(p, body.full_root, body.src_root)
            if candidate:
                try:
                    self.copy_with_structure(candidate, body.full_root, body.out_root)
                    copied.append(p)
                except Exception:
                    failed.append(p)
            else:
                failed.append(p)
        return Filemanagerstrm.CopyResponse(copied=copied, failed=failed)

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
