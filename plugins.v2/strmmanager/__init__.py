import os
import shutil
import csv
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# V2适配：导入路径/类型调整（修复：移除app.types的导入）
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.utils.system import SystemUtils


class STRMManager(_PluginBase):
    # 插件基础信息（V2新增/调整字段）
    plugin_name = "strm整理工具"
    plugin_desc = "扫描缺失STRM文件、批量删除STRM、从完整库复制STRM文件及目录结构"
    plugin_icon = "Docker_E.png"
    plugin_version = "1.0"
    plugin_author = "Daveccx"
    author_url = "https://github.com/Daveccx/MoviePilot-Plugins"
    plugin_config_prefix = "strmmanager_"
    plugin_order = 99
    user_level = 1  # V2权限：1=所有用户，2=认证用户，3=测试

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    # 核心配置
    _src_root: str = ""  # 当前影视库路径
    _full_root: str = ""  # 完整影视库路径（复制时用）
    _out_root: str = ""  # 复制输出路径（复制时用）
    _dry_run: bool = False  # 模拟运行（仅日志，不实际操作）
    _max_workers: int = 8  # 最大线程数
    _csv_file: str = "strm_result.csv"  # 结果CSV路径
    _action: str = "scan"  # 操作类型：scan/delete/copy
    # 媒体元文件后缀（仅元文件但无STRM的目录判定）
    _meta_exts: tuple = (".jpg", ".png", ".nfo", ".srt", ".ass", ".ssa", ".webp")
    _strm_ext: str = ".strm"
    # 退出事件（线程安全）
    _event: SystemUtils.ThreadEvent = SystemUtils.ThreadEvent()

    def init_plugin(self, config: dict = None):
        """V2初始化逻辑（核心与V1一致，仅系统消息调用微调）"""
        # 读取配置（兼容空配置）
        if config:
            self._enabled = config.get("enabled", False)
            self._onlyonce = config.get("onlyonce", False)
            self._cron = config.get("cron", "")
            self._src_root = config.get("src_root", "").strip()
            self._full_root = config.get("full_root", "").strip()
            self._out_root = config.get("out_root", "").strip()
            self._dry_run = config.get("dry_run", False)
            self._max_workers = int(config.get("max_workers", 8))
            self._csv_file = config.get("csv_file", "strm_result.csv").strip()
            self._action = config.get("action", "scan").strip()

        # 停止现有任务（防止重复启动）
        self.stop_service()

        # 启动定时任务 & 立即运行
        if self._enabled or self._onlyonce:
            # 初始化调度器（指定时区）
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            
            # 1. 定时任务（配置了cron才启动）
            if self._cron and self._enabled:
                logger.info(f"[STRM整理工具] 启动定时任务，周期：{self._cron}")
                try:
                    self._scheduler.add_job(
                        func=self.__run_strm_task,
                        trigger=CronTrigger.from_crontab(self._cron),
                        name="STRM整理定时任务"
                    )
                except Exception as e:
                    err_msg = f"定时任务启动失败：{str(e)}"
                    logger.error(f"[STRM整理工具] {err_msg}")
                    # 修复：改用字符串指定消息类型（兼容所有版本）
                    self.send_system_message(
                        title="STRM整理工具",
                        content=err_msg,
                        type="error"  # 替代SystemMessageType.ERROR
                    )
            
            # 2. 立即运行一次（onlyonce=True）
            if self._onlyonce:
                logger.info("[STRM整理工具] 立即运行一次任务")
                self._scheduler.add_job(
                    func=self.__run_strm_task,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="STRM整理立即任务"
                )
                # 关闭一次性开关并保存配置（防止重复运行）
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "src_root": self._src_root,
                    "full_root": self._full_root,
                    "out_root": self._out_root,
                    "dry_run": self._dry_run,
                    "max_workers": self._max_workers,
                    "csv_file": self._csv_file,
                    "action": self._action
                })

            # 启动调度器（有任务才启动）
            if self._scheduler and self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()
                logger.info("[STRM整理工具] 调度器启动完成")

    def get_state(self) -> bool:
        """获取插件启用状态（MoviePilot要求）"""
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """生成插件配置表单（Vuetify组件化配置）"""
        # 表单组件配置
        form_config = [
            {
                'component': 'VForm',
                'content': [
                    # 基础开关行
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                            'true-value': True,
                                            'false-value': False,
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                            'true-value': True,
                                            'false-value': False,
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'dry_run',
                                            'label': '模拟运行(Dry-Run)',
                                            'true-value': True,
                                            'false-value': False,
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 操作类型 & 定时配置行
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'action',
                                            'label': '操作类型',
                                            'items': [
                                                {'title': '仅扫描缺失STRM', 'value': 'scan'},
                                                {'title': '删除目录中STRM', 'value': 'delete'},
                                                {'title': '从完整库复制STRM', 'value': 'copy'},
                                            ],
                                            'variant': 'outlined',
                                            'clearable': False
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '定时执行周期',
                                            'placeholder': '5位cron表达式（例：0 0 * * * 每天凌晨）',
                                            'variant': 'outlined',
                                            'hint': '留空则关闭定时任务'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 核心路径配置 - 当前影视库
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'src_root',
                                            'label': '当前影视库根路径',
                                            'placeholder': '例：/mnt/media 或 D:/media',
                                            'variant': 'outlined',
                                            'required': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 复制专用路径配置
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'full_root',
                                            'label': '完整影视库路径（仅复制时需填）',
                                            'placeholder': '例：/mnt/full_media 或 D:/full_media',
                                            'variant': 'outlined',
                                            'hint': '复制模式下，从该路径读取完整STRM文件'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'out_root',
                                            'label': '复制输出路径（仅复制时需填）',
                                            'placeholder': '例：/mnt/strm_copy 或 D:/strm_copy',
                                            'variant': 'outlined',
                                            'hint': '复制模式下，STRM文件输出到该路径'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 高级配置
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'max_workers',
                                            'label': '最大工作线程数',
                                            'placeholder': '默认8',
                                            'type': 'number',
                                            'min': 1,
                                            'max': 32,
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'csv_file',
                                            'label': '结果CSV文件路径',
                                            'placeholder': '默认strm_result.csv',
                                            'variant': 'outlined',
                                            'hint': '会保存到MoviePilot插件数据目录'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 提示信息
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': (
                                                '1. 扫描模式：仅统计缺失STRM的目录并生成CSV报告；\n'
                                                '2. 删除模式：删除缺失STRM目录中的所有STRM文件（谨慎使用）；\n'
                                                '3. 复制模式：从完整库复制对应目录的STRM及目录结构到输出路径；\n'
                                                '4. 模拟运行：仅打印日志，不执行实际的删除/复制操作。'
                                            )
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
        # 表单默认值
        default_config = {
            "enabled": False,
            "onlyonce": False,
            "cron": "",
            "src_root": "",
            "full_root": "",
            "out_root": "",
            "dry_run": False,
            "max_workers": 8,
            "csv_file": "strm_result.csv",
            "action": "scan"
        }
        return form_config, default_config

    def __run_strm_task(self):
        """执行STRM核心任务（修复重复逻辑、统一消息调用）"""
        # 前置校验：当前影视库路径必须有效
        if not self._src_root or not Path(self._src_root).exists():
            err_msg = f"当前影视库路径无效：{self._src_root}（路径不存在或无权限）"
            logger.error(f"[STRM整理工具] {err_msg}")
            # 修复：改用字符串指定消息类型
            self.send_system_message(
                title="STRM整理工具",
                content=err_msg,
                type="error"
            )
            return

        try:
            # 1. 扫描缺失STRM的目录（所有模式都先扫描）
            logger.info(f"[STRM整理工具] 开始扫描缺失STRM的目录，源路径：{self._src_root}")
            missing_dirs = self.__scan_missing_strm(self._src_root)
            logger.info(f"[STRM整理工具] 扫描完成，共发现 {len(missing_dirs)} 个缺失STRM的目录")
            
            # 2. 生成CSV报告（所有模式都生成）
            self.__write_csv(missing_dirs)
            logger.info(f"[STRM整理工具] 扫描结果已写入CSV文件：{self._csv_file}")

            # 3. 根据操作类型执行对应逻辑
            if self._action == "delete":
                self.__delete_strm_batch(missing_dirs)
                logger.info(f"[STRM整理工具] 删除模式执行完成，处理 {len(missing_dirs)} 个目录")
            elif self._action == "copy":
                # 复制模式前置校验
                if not self._full_root or not Path(self._full_root).exists():
                    err_msg = f"完整影视库路径无效：{self._full_root}"
                    logger.error(f"[STRM整理工具] {err_msg}")
                    # 修复：改用字符串指定消息类型
                    self.send_system_message(
                        title="STRM整理工具",
                        content=err_msg,
                        type="error"
                    )
                    return
                if not self._out_root:
                    err_msg = "复制输出路径未配置（仅复制模式需填）"
                    logger.error(f"[STRM整理工具] {err_msg}")
                    # 修复：改用字符串指定消息类型
                    self.send_system_message(
                        title="STRM整理工具",
                        content=err_msg,
                        type="error"
                    )
                    return
                self.__copy_strm_batch(missing_dirs)
                logger.info(f"[STRM整理工具] 复制模式执行完成，处理 {len(missing_dirs)} 个目录")

            # 任务完成通知
            # 修复：改用字符串指定消息类型（info）
            self.send_system_message(
                title="STRM整理工具",
                content=f"{self._action}操作完成！\n- 处理目录数：{len(missing_dirs)}\n- 结果文件：{self._csv_file}",
                type="info"
            )
        except Exception as e:
            err_msg = f"任务执行失败：{str(e)}"
            logger.error(f"[STRM整理工具] {err_msg}", exc_info=True)
            # 修复：改用字符串指定消息类型
            self.send_system_message(
                title="STRM整理工具",
                content=err_msg,
                type="error"
            )

    def __is_meta_only(self, files: list) -> bool:
        """判断文件列表是否仅包含媒体元文件（无STRM/视频文件）"""
        if not files:
            return False
        return all(f.lower().endswith(self._meta_exts) for f in files)

    def __has_strm(self, files: list) -> bool:
        """判断文件列表是否包含STRM文件"""
        return any(f.lower().endswith(self._strm_ext) for f in files)

    def __is_final_media_dir(self, path: str) -> bool:
        """判断是否为最终媒体目录（无子目录 + 仅含元文件）"""
        try:
            path_obj = Path(path)
            if not path_obj.is_dir():
                return False
            # 区分文件/子目录
            files = [f.name for f in path_obj.iterdir() if f.is_file()]
            dirs = [d.name for d in path_obj.iterdir() if d.is_dir()]
            # 无子目录 + 仅元文件 → 判定为最终媒体目录
            return not dirs and self.__is_meta_only(files)
        except Exception as e:
            logger.debug(f"[STRM整理工具] 判断媒体目录失败 {path}：{str(e)}")
            return False

    def __scan_missing_strm(self, root: str) -> list:
        """扫描所有缺失STRM的最终媒体目录"""
        missing_dirs = []
        # 遍历目录（跳过符号链接，避免循环）
        for cur, dirs, files in os.walk(root, followlinks=False):
            if self.__is_final_media_dir(cur) and not self.__has_strm(files):
                missing_dirs.append(cur)
        return missing_dirs

    def __delete_strm(self, folder: str):
        """删除单个目录中的所有STRM文件"""
        try:
            folder_obj = Path(folder)
            for file in folder_obj.iterdir():
                if file.is_file() and file.name.lower().endswith(self._strm_ext):
                    if not self._dry_run:
                        file.unlink(missing_ok=True)  # 兼容文件不存在的情况
                        logger.info(f"[STRM整理工具] 删除STRM文件：{file.absolute()}")
                    else:
                        logger.info(f"[STRM整理工具] [Dry-Run] 模拟删除STRM文件：{file.absolute()}")
        except Exception as e:
            logger.error(f"[STRM整理工具] 删除STRM失败 {folder}：{str(e)}")

    def __delete_strm_batch(self, dirs: list):
        """批量删除STRM文件（多线程）"""
        logger.info(f"[STRM整理工具] 开始批量删除STRM文件，共{len(dirs)}个目录，Dry-Run：{self._dry_run}")
        # 多线程执行（控制最大线程数）
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(self.__delete_strm, dirs))
        logger.info("[STRM整理工具] STRM文件批量删除完成")

    def __find_in_full_lib(self, target: str) -> Optional[str]:
        """从完整库查找与目标目录对应的路径"""
        try:
            # 计算相对路径 → 拼接完整库路径
            rel_path = os.path.relpath(target, start=self._src_root)
            full_path = os.path.join(self._full_root, rel_path)
            return full_path if Path(full_path).exists() else None
        except Exception as e:
            logger.debug(f"[STRM整理工具] 查找完整库路径失败 {target}：{str(e)}")
            return None

    def __copy_with_structure(self, src: str):
        """按相对目录结构复制STRM及元文件到输出路径"""
        try:
            # 计算相对路径 → 拼接输出路径
            rel_path = os.path.relpath(src, start=self._full_root)
            dst_path = Path(self._out_root) / rel_path
            
            if self._dry_run:
                logger.info(f"[STRM整理工具] [Dry-Run] 模拟复制：{src} → {dst_path.absolute()}")
                return
            
            # 创建输出目录（递归创建）
            dst_path.mkdir(parents=True, exist_ok=True)
            
            # 复制目录下的所有STRM和元文件（保留结构）
            src_obj = Path(src)
            for file in src_obj.iterdir():
                if file.is_file() and (file.name.lower().endswith(self._strm_ext) or file.name.lower().endswith(self._meta_exts)):
                    dst_file = dst_path / file.name
                    # 跳过已存在的文件（避免覆盖）
                    if not dst_file.exists():
                        shutil.copy2(file, dst_file)  # 保留文件元数据
                        logger.info(f"[STRM整理工具] 复制文件：{file.absolute()} → {dst_file.absolute()}")
        except Exception as e:
            logger.error(f"[STRM整理工具] 复制目录失败 {src}：{str(e)}")

    def __copy_strm_batch(self, dirs: list):
        """批量复制STRM及目录结构（多线程）"""
        # 匹配完整库中的对应目录
        full_lib_dirs = []
        for target_dir in dirs:
            full_dir = self.__find_in_full_lib(target_dir)
            if full_dir:
                full_lib_dirs.append(full_dir)
            else:
                logger.warning(f"[STRM整理工具] 完整库中未找到对应目录：{target_dir}")
        
        logger.info(f"[STRM整理工具] 在完整库中匹配到 {len(full_lib_dirs)} 个目录，开始复制到：{self._out_root}，Dry-Run：{self._dry_run}")
        # 多线程复制
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(self.__copy_with_structure, full_lib_dirs))
        logger.info("[STRM整理工具] STRM目录批量复制完成")

    def __write_csv(self, rows: list):
        """将缺失STRM的目录写入CSV报告（保存到插件数据目录）"""
        try:
            # CSV文件保存路径（MoviePilot插件数据目录，避免权限问题）
            csv_path = Path(settings.PLUGIN_DATA_PATH) / self._csv_file
            # 写入CSV（UTF-8 BOM，兼容Excel）
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["序号", "缺失STRM的目录路径"])  # 补充序号列，更易读
                for idx, dir_path in enumerate(rows, 1):
                    writer.writerow([idx, dir_path])
            logger.info(f"[STRM整理工具] CSV报告已生成：{csv_path.absolute()}")
        except Exception as e:
            logger.error(f"[STRM整理工具] 写入CSV失败：{str(e)}")

    def stop_service(self):
        """停止插件服务（MoviePilot核心生命周期方法）"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)  # 非阻塞关闭
            self._scheduler = None
            logger.info("[STRM整理工具] 调度器已停止")
        # 触发退出事件（终止线程）
        self._event.set()

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """自定义命令（暂无）"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """自定义API（暂无）"""
        return []

    def get_page(self) -> List[dict]:
        """自定义页面（暂无）"""
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        """注册插件公共服务（定时任务备用方案）"""
        if self._enabled and self._cron:
            return [{
                "id": "STRMManager",
                "name": "STRM整理工具",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.__run_strm_task,
                "kwargs": {}
            }]
        return []
