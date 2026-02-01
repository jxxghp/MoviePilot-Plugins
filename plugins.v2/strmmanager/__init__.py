import os
import csv
import shutil
import time
import threading
import sched
from datetime import datetime
from croniter import croniter
from typing import Optional
from pydantic import Field

# 核心：确保_PluginBase能被正确导入（MoviePilot V2 核心插件基类）
try:
    from app.plugins import _PluginBase
    from app.core.config import settings
except ImportError as e:
    raise ImportError(f"导入MoviePilot核心模块失败：{e}，请确认MoviePilot V2环境正常")

# --------------------------
# 核心插件类（顶层定义，继承_PluginBase，确保能被扫描到）
# --------------------------
class STRMManager(_PluginBase):
    # 插件基础信息（MoviePilot V2 强制要求的字段）
    plugin_type = "scheduler"
    plugin_name = "STRM整理工具"
    plugin_desc = "扫描缺失STRM文件、批量删除STRM、从完整库复制STRM文件及目录结构（V2适配）"
    plugin_version = "1.0.1"
    plugin_author = "Daveccx"
    plugin_config_prefix = "strmmanager"
    plugin_icon = "world.png"
    plugin_enabled = False
    plugin_cron = ""

    # 定时任务调度器（原生实现）
    _scheduler = None
    _cron_thread = None

    # --------------------------
    # 图形化配置模型（必须是类内的ConfigModel，继承_PluginBase.ConfigModel）
    # --------------------------
    class ConfigModel(_PluginBase.ConfigModel):
        enabled: bool = Field(default=False, description="启用插件", title="启用插件")
        run_now: bool = Field(default=False, description="立即运行一次", title="立即运行一次")
        dry_run: bool = Field(default=False, description="模拟运行（仅打印日志）", title="模拟运行")
        operation_type: str = Field(default="scan", description="操作类型：scan=仅扫描, delete=删除STRM, copy=复制STRM", title="操作类型")
        cron: str = Field(default="", description="定时执行周期（5位cron表达式，留空关闭）", title="定时执行周期")
        target_root: str = Field(default="", description="当前影视库根路径（必填，绝对路径）", title="当前影视库根路径")
        full_root: str = Field(default="", description="完整影视库路径（仅copy模式必填）", title="完整影视库路径")
        output_root: str = Field(default="", description="复制输出路径（仅copy模式必填）", title="复制输出路径")
        max_threads: int = Field(default=8, ge=1, le=32, description="最大工作线程数（1-32）", title="最大工作线程数")
        csv_filename: str = Field(default="strm_result.csv", description="CSV报告文件名（带.csv后缀）", title="CSV报告文件名")

    # --------------------------
    # 插件初始化（MoviePilot 启动时调用）
    # --------------------------
    def init_plugin(self):
        self.init_config()
        self.stop_cron_task()  # 停止旧任务
        if self.plugin_enabled and self.plugin_cron:
            self.start_cron_task()
            self.logger.info(f"STRM整理工具初始化成功，定时周期：{self.plugin_cron}")
        else:
            self.logger.info("STRM整理工具初始化成功（未启用定时任务）")

    # --------------------------
    # 加载配置（关联图形化界面）
    # --------------------------
    def init_config(self):
        config = self.get_config()
        if not config:
            self.logger.warning("STRM整理工具无配置，使用默认值")
            return
        # 赋值配置项
        self.plugin_enabled = config.get("enabled", False)
        self.plugin_cron = config.get("cron", "")
        self.dry_run = config.get("dry_run", False)
        self.operation_type = config.get("operation_type", "scan")
        self.target_root = config.get("target_root", "").strip()
        self.full_root = config.get("full_root", "").strip()
        self.output_root = config.get("output_root", "").strip()
        self.max_threads = config.get("max_threads", 8)
        self.csv_filename = config.get("csv_filename", "strm_result.csv")
        # 立即运行一次
        if config.get("run_now", False):
            threading.Thread(target=self.run_strm_task, name="STRMManager-RunNow").start()
            self.update_config({"run_now": False})  # 重置开关

    # --------------------------
    # 原生定时任务实现
    # --------------------------
    def start_cron_task(self):
        """启动cron定时任务"""
        try:
            self._scheduler = sched.scheduler(time.time, time.sleep)
            self._cron_thread = threading.Thread(target=self._cron_loop, daemon=True, name="STRMManager-Cron")
            self._cron_thread.start()
        except Exception as e:
            self.logger.error(f"启动定时任务失败：{str(e)}")

    def stop_cron_task(self):
        """停止定时任务"""
        if self._scheduler:
            self._scheduler.cancel()
            self._scheduler = None
        if self._cron_thread and self._cron_thread.is_alive():
            self._cron_thread.join(timeout=5)
            self._cron_thread = None

    def _cron_loop(self):
        """cron任务循环执行"""
        while self.plugin_enabled and self._scheduler:
            try:
                # 计算下一次执行时间
                cron = croniter(self.plugin_cron, datetime.now())
                next_run = cron.get_next(datetime)
                delay = (next_run - datetime.now()).total_seconds()
                if delay < 0:
                    delay = 0
                # 调度任务
                self._scheduler.enter(delay, 1, self.run_strm_task)
                self._scheduler.run()
            except Exception as e:
                self.logger.error(f"定时任务执行异常：{str(e)}")
                time.sleep(60)  # 异常时休眠60秒，避免死循环

    # --------------------------
    # 核心业务逻辑
    # --------------------------
    def run_strm_task(self):
        """执行STRM任务（扫描/删除/复制）"""
        # 基础路径校验
        if not self.target_root or not os.path.exists(self.target_root):
            self.logger.error(f"当前影视库路径无效：{self.target_root}")
            return

        # 按操作类型执行
        if self.operation_type == "scan":
            self._scan_missing_strm()
        elif self.operation_type == "delete":
            self._delete_strm_files()
        elif self.operation_type == "copy":
            self._copy_strm_files()
        else:
            self.logger.error(f"不支持的操作类型：{self.operation_type}")

    def _scan_missing_strm(self):
        """扫描缺失STRM的目录"""
        missing_dirs = []
        for root, _, files in os.walk(self.target_root, followlinks=False):
            # 筛选：无.strm文件且无其他文件的目录
            has_strm = any(f.lower().endswith(".strm") for f in files)
            if not has_strm and len(files) == 0:
                missing_dirs.append(root)

        # 生成CSV报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_name = self.csv_filename if self.csv_filename.endswith(".csv") else f"{self.csv_filename}.csv"
        csv_path = os.path.join(settings.PLUGIN_DATA_PATH, f"{csv_name.replace('.csv', '')}_{timestamp}.csv")
        os.makedirs(settings.PLUGIN_DATA_PATH, exist_ok=True)

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["缺失STRM的目录路径"])
            for dir_path in missing_dirs:
                writer.writerow([dir_path])

        self.logger.info(f"扫描完成：共找到{len(missing_dirs)}个缺失STRM的目录，报告路径：{csv_path}")

    def _delete_strm_files(self):
        """删除STRM文件"""
        delete_count = 0
        for root, _, files in os.walk(self.target_root, followlinks=False):
            for file in files:
                if file.lower().endswith(".strm"):
                    file_path = os.path.join(root, file)
                    if self.dry_run:
                        self.logger.info(f"【模拟删除】{file_path}")
                    else:
                        try:
                            os.remove(file_path)
                            delete_count += 1
                            self.logger.info(f"删除成功：{file_path}")
                        except Exception as e:
                            self.logger.error(f"删除失败：{file_path}，错误：{str(e)}")
        self.logger.info(f"删除任务完成：{'模拟' if self.dry_run else '实际'}删除{delete_count}个STRM文件")

    def _copy_strm_files(self):
        """复制STRM及元文件"""
        if not self.full_root or not os.path.exists(self.full_root):
            self.logger.error(f"完整影视库路径无效：{self.full_root}")
            return
        if not self.output_root:
            self.logger.error("复制输出路径未填写")
            return

        copy_count = 0
        support_exts = [".strm", ".jpg", ".png", ".webp", ".srt", ".ass", ".ssa", ".nfo"]
        for root, _, files in os.walk(self.full_root, followlinks=False):
            # 计算相对路径，保持目录结构
            rel_path = os.path.relpath(root, self.full_root)
            dst_root = os.path.join(self.output_root, rel_path)
            os.makedirs(dst_root, exist_ok=True)

            for file in files:
                if any(file.lower().endswith(ext) for ext in support_exts):
                    src_path = os.path.join(root, file)
                    dst_path = os.path.join(dst_root, file)
                    if self.dry_run:
                        self.logger.info(f"【模拟复制】{src_path} → {dst_path}")
                    else:
                        try:
                            shutil.copy2(src_path, dst_path)  # 保留文件元数据
                            copy_count += 1
                            self.logger.info(f"复制成功：{src_path} → {dst_path}")
                        except Exception as e:
                            self.logger.error(f"复制失败：{src_path}，错误：{str(e)}")
        self.logger.info(f"复制任务完成：{'模拟' if self.dry_run else '实际'}复制{copy_count}个文件")

    # --------------------------
    # 图形化配置界面（MoviePilot V2 强制要求）
    # --------------------------
    def get_ui_pages(self):
        """注册图形化配置页面"""
        return [{
            "name": self.plugin_config_prefix,
            "title": self.plugin_name,
            "desc": self.plugin_desc,
            "route": f"/plugins/{self.plugin_config_prefix}",
            "form": self.ConfigModel.schema()
        }]

    # --------------------------
    # 配置保存（MoviePilot V2 调用）
    # --------------------------
    def save_config(self, config: dict):
        """保存配置时校验并初始化"""
        # 路径合法性校验
        if config.get("target_root") and not os.path.isabs(config.get("target_root")):
            self.logger.error("当前影视库根路径必须为绝对路径")
            return False
        # 保存配置
        self.update_config(config)
        # 重新初始化插件
        self.init_plugin()
        return True

    # --------------------------
    # 插件停止（MoviePilot V2 调用）
    # --------------------------
    def stop_plugin(self):
        """停止插件时清理资源"""
        self.stop_cron_task()
        self.logger.info("STRM整理工具已停止")
        return super().stop_plugin()

# --------------------------
# 关键：显式导出插件类，确保MoviePilot能扫描到
# --------------------------
__all__ = ["STRMManager"]
