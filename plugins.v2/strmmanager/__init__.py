import os
import csv
import shutil
import time
import threading
from datetime import datetime
from croniter import croniter
from typing import Optional, List
from pydantic import Field
from app.plugins import _PluginBase
from app.core.config import settings
from app.schemas.types import PluginType
from app.utils.cron import CronJob
from app.utils.system import SystemUtils

# MoviePilot V2 插件核心类（必须继承_PluginBase）
class STRMManager(_PluginBase):
    # 插件基础信息（与package.v2.json对应）
    plugin_type = PluginType.Scheduler
    plugin_name = "STRM整理工具"
    plugin_desc = "扫描缺失STRM文件、批量删除STRM、从完整库复制STRM文件及目录结构（V2适配）"
    plugin_version = "1.0.0"
    plugin_author = "Daveccx"
    plugin_config_prefix = "strmmanager"
    plugin_icon = "world.png"
    plugin_enabled = False
    plugin_cron = ""

    # --------------------------
    # 核心：定义图形化配置字段（关键！没有这个就没有配置界面）
    # --------------------------
    class ConfigModel(_PluginBase.ConfigModel):
        # 基础开关
        enabled: bool = Field(default=False, description="启用插件", title="启用插件")
        run_now: bool = Field(default=False, description="立即运行一次", title="立即运行一次")
        dry_run: bool = Field(default=False, description="模拟运行（仅打印日志，不实际操作）", title="模拟运行")
        
        # 操作类型（下拉选择）
        operation_type: str = Field(default="scan", description="操作类型：scan=仅扫描, delete=删除STRM, copy=复制STRM", title="操作类型")
        
        # 定时任务（cron表达式）
        cron: str = Field(default="", description="定时执行周期（5位cron表达式，留空关闭）", title="定时执行周期")
        
        # 路径配置
        target_root: str = Field(default="", description="当前影视库根路径（必填）", title="当前影视库根路径")
        full_root: str = Field(default="", description="完整影视库路径（仅copy模式必填）", title="完整影视库路径")
        output_root: str = Field(default="", description="复制输出路径（仅copy模式必填）", title="复制输出路径")
        
        # 高级配置
        max_threads: int = Field(default=8, ge=1, le=32, description="最大工作线程数（1-32）", title="最大工作线程数")
        csv_filename: str = Field(default="strm_result.csv", description="CSV报告文件名（带.csv后缀）", title="CSV报告文件名")

    # 初始化配置
    def init_plugin(self):
        self.init_config()
        # 注册定时任务
        if self.plugin_enabled and self.plugin_cron:
            self.register_cron_job(
                cron_job=CronJob(
                    cron_expr=self.plugin_cron,
                    func=self.run_strm_task,
                    args=[],
                    job_id=f"{self.plugin_config_prefix}_task"
                )
            )

    # 加载配置（关联图形化界面的配置值）
    def init_config(self):
        config = self.get_config()
        if config:
            self.plugin_enabled = config.get("enabled", False)
            self.plugin_cron = config.get("cron", "")
            self.dry_run = config.get("dry_run", False)
            self.operation_type = config.get("operation_type", "scan")
            self.target_root = config.get("target_root", "")
            self.full_root = config.get("full_root", "")
            self.output_root = config.get("output_root", "")
            self.max_threads = config.get("max_threads", 8)
            self.csv_filename = config.get("csv_filename", "strm_result.csv")
            # 立即运行一次
            if config.get("run_now", False):
                threading.Thread(target=self.run_strm_task).start()
                # 重置立即运行开关
                self.update_config({"run_now": False})

    # 核心任务执行函数（简化版，保留核心逻辑）
    def run_strm_task(self):
        # 校验基础路径
        if not os.path.exists(self.target_root):
            self.logger.error(f"当前影视库路径无效：{self.target_root}")
            return
        
        # 按操作类型执行
        if self.operation_type == "scan":
            self.scan_missing_strm()
        elif self.operation_type == "delete":
            self.delete_strm_files()
        elif self.operation_type == "copy":
            if not os.path.exists(self.full_root) or not self.output_root:
                self.logger.error("copy模式需填写完整影视库路径和复制输出路径")
                return
            self.copy_strm_files()
        else:
            self.logger.error(f"不支持的操作类型：{self.operation_type}")

    # 扫描缺失STRM的目录（生成CSV）
    def scan_missing_strm(self):
        missing_dirs = []
        # 遍历目录（简化逻辑，仅示例）
        for root, dirs, files in os.walk(self.target_root, followlinks=False):
            has_strm = any(f.endswith(".strm") for f in files)
            if not has_strm and len(files) == 0:  # 无STRM且无文件的目录
                missing_dirs.append(root)
        
        # 生成CSV报告（带时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = os.path.join(settings.PLUGIN_DATA_PATH, f"{self.csv_filename.replace('.csv', '')}_{timestamp}.csv")
        os.makedirs(settings.PLUGIN_DATA_PATH, exist_ok=True)
        with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["缺失STRM的目录路径"])
            for dir_path in missing_dirs:
                writer.writerow([dir_path])
        self.logger.info(f"扫描完成，共找到{len(missing_dirs)}个缺失STRM的目录，报告路径：{csv_file}")

    # 删除STRM文件（模拟运行+实际删除）
    def delete_strm_files(self):
        delete_count = 0
        for root, dirs, files in os.walk(self.target_root, followlinks=False):
            for file in files:
                if file.endswith(".strm"):
                    file_path = os.path.join(root, file)
                    if self.dry_run:
                        self.logger.info(f"【模拟删除】STRM文件：{file_path}")
                    else:
                        try:
                            os.remove(file_path)
                            delete_count += 1
                            self.logger.info(f"删除STRM文件成功：{file_path}")
                        except Exception as e:
                            self.logger.error(f"删除STRM文件失败：{file_path}，错误：{str(e)}")
        self.logger.info(f"删除任务完成，{'模拟' if self.dry_run else '实际'}删除{delete_count}个STRM文件")

    # 复制STRM及元文件
    def copy_strm_files(self):
        copy_count = 0
        # 支持的元文件格式
        support_ext = [".strm", ".jpg", ".png", ".webp", ".srt", ".ass", ".ssa", ".nfo"]
        for root, dirs, files in os.walk(self.full_root, followlinks=False):
            # 计算相对路径，保持目录结构
            rel_path = os.path.relpath(root, self.full_root)
            target_root = os.path.join(self.output_root, rel_path)
            os.makedirs(target_root, exist_ok=True)
            
            for file in files:
                if any(file.endswith(ext) for ext in support_ext):
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(target_root, file)
                    if self.dry_run:
                        self.logger.info(f"【模拟复制】{src_file} → {dst_file}")
                    else:
                        try:
                            shutil.copy2(src_file, dst_file)  # 保留文件元数据
                            copy_count += 1
                            self.logger.info(f"复制成功：{src_file} → {dst_file}")
                        except Exception as e:
                            self.logger.error(f"复制失败：{src_file}，错误：{str(e)}")
        self.logger.info(f"复制任务完成，{'模拟' if self.dry_run else '实际'}复制{copy_count}个文件")

    # 提供配置界面（必须实现，否则无图形化界面）
    def get_ui_pages(self):
        # 注册配置页面
        return [{
            "name": self.plugin_config_prefix,
            "title": self.plugin_name,
            "desc": self.plugin_desc,
            "route": f"/plugins/{self.plugin_config_prefix}",
            "form": self.ConfigModel.schema()
        }]

    # 保存配置时触发
    def save_config(self, config: dict):
        # 验证路径合法性
        if config.get("target_root") and not os.path.isabs(config.get("target_root")):
            self.logger.error("当前影视库根路径必须为绝对路径")
            return False
        # 保存配置
        self.update_config(config)
        # 重新初始化插件（更新定时任务）
        self.init_plugin()
        return True
