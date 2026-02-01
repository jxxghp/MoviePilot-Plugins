import os
import shutil
import logging
from typing import List, Optional, Dict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from io import StringIO
import csv

# MoviePilot 核心依赖
from moviepilot.plugins import PluginBase, register_plugin
from moviepilot.core.config import settings
from moviepilot.utils.types import PluginType
from moviepilot.utils.logger import logger

# 插件专属日志
plugin_logger = logging.getLogger("moviepilot.plugin.filemanagerstrm")


class FileManagerSTRMConfig(BaseModel):
    """插件配置模型（标准化配置项）"""
    strm_root: str = Field(
        default="",
        title="STRM 文件根目录",
        description="存放 STRM 文件的根目录路径，为空时使用系统环境变量 MOVIEPILOT_STRM_ROOT",
        example="/mnt/strm_media"
    )


@register_plugin
class Filemanagerstrm(PluginBase):
    """
    STRM 文件管理器插件
    扫描缺失 STRM 文件的媒体目录，并支持从完整媒体库复制对应目录结构及文件
    """
    # 插件基础信息（符合 MoviePilot 插件规范）
    plugin_type = PluginType.TOOL
    plugin_name = "filemanagerstrm"
    plugin_version = "1.2.0"  # 版本升级，新增进度查询功能
    plugin_author = "开发者名称"
    plugin_desc = "扫描缺失 STRM 文件的媒体目录，支持从完整库复制目录结构、导出扫描结果及复制进度查询"
    plugin_config_model = FileManagerSTRMConfig  # 绑定配置模型
    config: FileManagerSTRMConfig  # 配置实例

    def __init__(self):
        super().__init__()
        self.router = APIRouter(prefix="/filemanagerstrm", tags=["STRM 文件管理"])
        self._last_scan: List[str] = []  # 上次扫描结果缓存
        # 新增：复制进度缓存（key: 任务标识，这里简化为固定标识，多任务可扩展为 UUID）
        self._copy_progress: Dict[str, float] = {
            "total": 0.0,    # 总任务数
            "completed": 0.0,# 已完成任务数
            "progress": 0.0, # 进度百分比（0-100）
            "status": "idle" # 任务状态：idle(空闲)/running(运行中)/finished(完成)/failed(失败)
        }
        self._register_apis()  # 注册 API 路由

    def _register_apis(self):
        """注册 API 接口（标准化路由注册）"""
        # 扫描缺失 STRM 接口
        @self.router.get(
            "/scan_missing",
            summary="扫描缺失 STRM 文件的目录",
            response_model=self.ScanResponse,
            description="扫描配置的 STRM 根目录下，缺失 .strm 文件的媒体目录"
        )
        def scan_missing():
            return self.api_scan_missing()

        # 从完整库复制目录接口
        @self.router.post(
            "/copy_from_full",
            summary="从完整媒体库复制缺失 STRM 的目录",
            response_model=self.CopyResponse,
            description="根据扫描结果，从完整媒体库复制对应目录到目标路径"
        )
        def copy_from_full(body: self.CopyRequest):
            return self.api_copy_from_full(body)

        # 下载扫描结果 CSV 接口
        @self.router.get(
            "/download_csv",
            summary="下载缺失 STRM 目录的 CSV 清单",
            description="导出上次扫描的缺失 STRM 目录列表为 CSV 文件"
        )
        def download_csv():
            return self.api_download_csv()

        # 新增：查询复制进度接口
        @self.router.get(
            "/copy_progress",
            summary="查询目录复制进度",
            response_model=self.ProgressResponse,
            description="查询当前大目录复制任务的进度百分比及执行状态"
        )
        def get_copy_progress():
            return self.api_get_copy_progress()

    # ========== 数据模型定义 ==========
    class ScanResponse(BaseModel):
        """扫描结果响应模型"""
        missing_paths: List[str] = Field(default=[], description="缺失 STRM 文件的目录列表")

    class CopyRequest(BaseModel):
        """复制目录请求模型"""
        src_root: str = Field(..., description="源 STRM 根目录（需与扫描目录一致）")
        full_root: str = Field(..., description="完整媒体库根目录")
        out_root: str = Field(..., description="复制目标根目录")

    class CopyResponse(BaseModel):
        """复制结果响应模型"""
        copied: List[str] = Field(default=[], description="成功复制的目录列表")
        failed: List[str] = Field(default=[], description="复制失败的目录列表")

    # 新增：进度查询响应模型
    class ProgressResponse(BaseModel):
        """复制进度响应模型"""
        total: float = Field(default=0.0, description="总任务数")
        completed: float = Field(default=0.0, description="已完成任务数")
        progress: float = Field(default=0.0, description="复制进度百分比（0-100）")
        status: str = Field(default="idle", description="任务状态：idle/running/finished/failed")

    # ========== 核心业务逻辑 ==========
    def is_meta_only(self, files: List[str]) -> bool:
        """判断目录是否仅包含元数据文件（无媒体/STRM 文件）"""
        meta_extensions = (".jpg", ".png", ".nfo", ".srt", ".ass", ".ssa", ".webp")
        return files and all(f.lower().endswith(meta_extensions) for f in files)

    def has_strm(self, files: List[str]) -> bool:
        """判断目录是否包含 STRM 文件"""
        return any(f.lower().endswith(".strm") for f in files)

    def is_final_media_dir(self, path: str) -> bool:
        """判断是否为最终媒体目录（无子目录 + 仅含元数据文件）"""
        try:
            items = os.listdir(path)
            files = [f for f in items if os.path.isfile(os.path.join(path, f))]
            dirs = [d for d in items if os.path.isdir(os.path.join(path, d))]
            return not dirs and self.is_meta_only(files)
        except Exception as e:
            plugin_logger.error(f"判断媒体目录失败 {path}：{str(e)}")
            return False

    def scan_missing_strm(self, root: str) -> List[str]:
        """扫描指定根目录下缺失 STRM 的媒体目录"""
        if not os.path.isdir(root):
            plugin_logger.warning(f"扫描目录不存在：{root}")
            return []

        result = []
        plugin_logger.info(f"开始扫描缺失 STRM 文件的目录，根目录：{root}")
        try:
            for cur, dirs, files in os.walk(root):
                # 跳过隐藏目录（如 .DS_Store、.git）
                if os.path.basename(cur).startswith("."):
                    continue
                if self.is_final_media_dir(cur) and not self.has_strm(files):
                    result.append(cur)
            plugin_logger.info(f"扫描完成，共发现 {len(result)} 个缺失 STRM 的目录")
        except Exception as e:
            plugin_logger.error(f"扫描目录失败：{str(e)}")
        return result

    def find_in_full_lib(self, target: str, full_root: str, src_root: str) -> Optional[str]:
        """在完整媒体库中查找对应目录"""
        try:
            rel_path = os.path.relpath(target, start=src_root)
            candidate = os.path.join(full_root, rel_path)
            if os.path.exists(candidate):
                return candidate
            plugin_logger.warning(f"完整库中未找到对应目录：{candidate}")
            return None
        except Exception as e:
            plugin_logger.error(f"查找完整库目录失败 {target}：{str(e)}")
            return None

    def copy_with_structure(self, src: str, src_root: str, dst_root: str):
        """保留目录结构复制目录"""
        try:
            rel_path = os.path.relpath(src, src_root)
            dst_path = os.path.join(dst_root, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            if not os.path.exists(dst_path):
                shutil.copytree(
                    src,
                    dst_path,
                    ignore=shutil.ignore_patterns(".*"),  # 忽略隐藏文件
                    dirs_exist_ok=True
                )
            plugin_logger.info(f"成功复制目录：{src} -> {dst_path}")
        except Exception as e:
            plugin_logger.error(f"复制目录失败 {src}：{str(e)}")
            raise  # 抛出异常让上层处理

    def _update_copy_progress(self, completed: int, total: int):
        """
        新增：更新复制进度（内部辅助方法）
        :param completed: 已完成的目录数
        :param total: 总目录数
        """
        self._copy_progress["completed"] = completed
        self._copy_progress["total"] = total
        # 计算进度百分比（避免除零错误）
        if total > 0:
            self._copy_progress["progress"] = round((completed / total) * 100, 2)
        else:
            self._copy_progress["progress"] = 0.0
        # 更新任务状态
        if total == 0:
            self._copy_progress["status"] = "idle"
        elif completed < total:
            self._copy_progress["status"] = "running"
        else:
            self._copy_progress["status"] = "finished"

    # ========== API 接口实现 ==========
    def api_scan_missing(self) -> ScanResponse:
        """扫描缺失 STRM 接口实现"""
        # 优先使用插件配置，其次使用环境变量
        root = self.config.strm_root or os.environ.get("MOVIEPILOT_STRM_ROOT", "")
        if not root or not os.path.isdir(root):
            plugin_logger.warning("STRM 根目录未配置或不存在")
            return self.ScanResponse(missing_paths=[])
        
        missing_paths = self.scan_missing_strm(root)
        self._last_scan = missing_paths  # 缓存扫描结果
        return self.ScanResponse(missing_paths=missing_paths)

    def api_copy_from_full(self, body: CopyRequest) -> CopyResponse:
        """从完整库复制目录接口实现"""
        # 参数校验
        for param_name, param_value in {
            "源根目录": body.src_root,
            "完整库根目录": body.full_root,
            "目标根目录": body.out_root
        }.items():
            if not param_value or not os.path.isdir(param_value):
                plugin_logger.error(f"{param_name} 无效或不存在：{param_value}")
                raise HTTPException(status_code=400, detail=f"{param_name} 无效或不存在")

        missing_paths = self.scan_missing_strm(body.src_root)
        copied, failed = [], []
        total_count = len(missing_paths)
        
        # 初始化进度
        self._update_copy_progress(0, total_count)
        plugin_logger.info(f"开始从完整库复制，共处理 {total_count} 个目录")

        for idx, path in enumerate(missing_paths, 1):
            candidate = self.find_in_full_lib(path, body.full_root, body.src_root)
            if not candidate:
                failed.append(path)
                # 更新进度（即使失败也计入已处理）
                self._update_copy_progress(idx, total_count)
                continue
            try:
                self.copy_with_structure(candidate, body.full_root, body.out_root)
                copied.append(path)
            except Exception:
                failed.append(path)
            # 新增：每处理一个目录就更新进度
            self._update_copy_progress(idx, total_count)

        # 最终更新进度状态（确保异常场景下也能标记完成）
        self._update_copy_progress(total_count, total_count)
        plugin_logger.info(f"复制完成：成功 {len(copied)} 个，失败 {len(failed)} 个")
        return self.CopyResponse(copied=copied, failed=failed)

    def api_download_csv(self) -> StreamingResponse:
        """下载扫描结果 CSV 接口实现"""
        if not self._last_scan:
            raise HTTPException(status_code=400, detail="暂无扫描结果可导出")

        # 生成 CSV 内容
        output = StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)  # 引号包裹路径（避免特殊字符问题）
        writer.writerow(["缺失 STRM 的目录路径"])
        for path in self._last_scan:
            writer.writerow([path])
        output.seek(0)

        # 返回流式响应
        return StreamingResponse(
            output,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=missing_strm.csv",
                "Cache-Control": "no-cache"
            }
        )

    # 新增：进度查询接口实现
    def api_get_copy_progress(self) -> ProgressResponse:
        """查询复制进度接口实现"""
        return self.ProgressResponse(
            total=self._copy_progress["total"],
            completed=self._copy_progress["completed"],
            progress=self._copy_progress["progress"],
            status=self._copy_progress["status"]
        )

    # ========== 插件生命周期方法 ==========
    def on_start(self):
        """插件启动时执行"""
        plugin_logger.info(f"STRM 文件管理器插件启动，版本：{self.plugin_version}")

    def on_stop(self):
        """插件停止时执行"""
        plugin_logger.info("STRM 文件管理器插件停止")