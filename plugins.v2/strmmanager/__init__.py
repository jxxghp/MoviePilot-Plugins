import os
import shutil
import csv
import threading
import fnmatch
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# V2适配：保留必要导入
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.utils.system import SystemUtils


class STRMManager(_PluginBase):
    # 插件基础信息
    plugin_name = "strm整理工具"
    plugin_desc = "扫描/删除/复制/替换STRM文件，支持目录选择、影视搜索替换（V2适配）"
    plugin_icon = "Docker_E.png"
    plugin_version = "1.1"  # 版本升级
    plugin_author = "Daveccx"
    author_url = "https://github.com/Daveccx/MoviePilot-Plugins"
    plugin_config_prefix = "strmmanager_"
    plugin_order = 99
    user_level = 1

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _src_root: str = ""  # 当前影视库根路径（目录选择器）
    _full_root: str = ""  # 完整影视库路径（目录选择器）
    _out_root: str = ""  # 输出路径（目录选择器）
    _dry_run: bool = False
    _max_workers: int = 8
    _csv_file: str = "strm_result.csv"
    _action: str = "scan"  # 新增：replace（替换STRM）
    _search_keyword: str = ""  # 影视搜索关键词
    _replace_single: bool = False  # 单次替换触发标记
    _meta_exts: tuple = (".jpg", ".png", ".nfo", ".srt", ".ass", ".ssa", ".webp")
    _strm_ext: str = ".strm"
    _event: threading.Event = threading.Event()

    def init_plugin(self, config: dict = None):
        """初始化插件（兼容新增配置项）"""
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
            self._search_keyword = config.get("search_keyword", "").strip()
            # 处理单次替换触发
            self._replace_single = config.get("replace_single", False)

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行
        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            
            # 定时任务
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
                    self.send_system_message(
                        title="STRM整理工具",
                        content=err_msg,
                        type="error"
                    )
            
            # 立即运行一次（批量操作）
            if self._onlyonce:
                logger.info("[STRM整理工具] 立即运行一次批量任务")
                self._scheduler.add_job(
                    func=self.__run_strm_task,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="STRM整理立即任务"
                )
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({**config, "onlyonce": False})

            # 单次替换触发（新增）
            if self._replace_single:
                logger.info(f"[STRM整理工具] 触发单次替换任务，搜索关键词：{self._search_keyword}")
                self._scheduler.add_job(
                    func=self.__run_replace_single,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=2),
                    name="STRM替换单次任务"
                )
                # 关闭替换触发标记
                self._replace_single = False
                self.update_config({**config, "replace_single": False})

            # 启动调度器
            if self._scheduler and self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()
                logger.info("[STRM整理工具] 调度器启动完成")

    def get_state(self) -> bool:
        """获取插件启用状态"""
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """生成插件配置表单（核心修改：目录选择器+搜索替换）"""
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
                                            'label': '立即运行批量任务',
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
                                                {'title': '从完整库替换STRM', 'value': 'replace'}  # 新增
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
                    # 核心路径配置 - 目录选择器（替代手动输入）
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VFileSelector',  # 目录选择器（核心修改）
                                        'props': {
                                            'model': 'src_root',
                                            'label': '当前影视库根路径',
                                            'placeholder': '选择目标影视所在的根目录',
                                            'type': 'directory',  # 仅选择目录
                                            'variant': 'outlined',
                                            'required': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 完整库+输出路径 - 目录选择器
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VFileSelector',
                                        'props': {
                                            'model': 'full_root',
                                            'label': '完整影视库路径（复制/替换时需选）',
                                            'placeholder': '选择包含完整STRM的影视库目录',
                                            'type': 'directory',
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
                                        'component': 'VFileSelector',
                                        'props': {
                                            'model': 'out_root',
                                            'label': '输出路径（复制时需选）',
                                            'placeholder': '选择STRM复制的目标目录',
                                            'type': 'directory',
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 新增：影视搜索+单次替换
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 8},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'search_keyword',
                                            'label': '影视搜索关键词（替换时使用）',
                                            'placeholder': '输入影视名称（支持模糊匹配），例：星际穿越',
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
                                            'model': 'replace_single',
                                            'label': '触发单次替换',
                                            'true-value': True,
                                            'false-value': False,
                                            'variant': 'outlined',
                                            'hint': '开启后立即替换匹配的影视STRM'
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
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 提示信息（更新）
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
                                                '4. 替换模式：批量替换当前库中缺失STRM的影视STRM（需完整库）；\n'
                                                '5. 单次替换：输入影视关键词，仅替换匹配的单个/多个影视STRM；\n'
                                                '6. 模拟运行：仅打印日志，不执行实际的删除/复制/替换操作。'
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
        # 表单默认值（新增搜索关键词、单次替换）
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
            "action": "scan",
            "search_keyword": "",
            "replace_single": False
        }
        return form_config, default_config

    # -------------------------- 新增核心功能：影视搜索 + STRM替换 --------------------------
    def __search_movie(self, root: str, keyword: str) -> list:
        """
        模糊搜索影视目录（新增）
        :param root: 搜索根目录
        :param keyword: 搜索关键词（不区分大小写）
        :return: 匹配的影视目录列表
        """
        if not keyword or not Path(root).exists():
            logger.warning(f"[STRM整理工具] 搜索条件无效：关键词={keyword}，根目录={root}")
            return []
        
        match_dirs = []
        keyword_lower = keyword.lower()
        logger.info(f"[STRM整理工具] 开始搜索影视，根目录：{root}，关键词：{keyword}")
        
        # 遍历目录，模糊匹配目录名
        for cur, dirs, files in os.walk(root, followlinks=False):
            # 匹配条件：目录名包含关键词（不区分大小写）+ 是最终媒体目录
            if keyword_lower in cur.lower() and self.__is_final_media_dir(cur):
                match_dirs.append(cur)
                logger.info(f"[STRM整理工具] 匹配到影视目录：{cur}")
        
        logger.info(f"[STRM整理工具] 搜索完成，共匹配 {len(match_dirs)} 个影视目录")
        return match_dirs

    def __replace_strm(self, target_dir: str, full_root: str):
        """
        替换单个影视目录的STRM文件（新增）
        :param target_dir: 目标影视目录（当前库）
        :param full_root: 完整影视库路径
        """
        try:
            # 从完整库查找对应目录
            full_dir = self.__find_in_full_lib(target_dir, full_root)
            if not full_dir:
                logger.warning(f"[STRM整理工具] 完整库中未找到对应目录：{target_dir}")
                return
            
            # 查找完整库中的STRM文件
            full_strm_files = [f for f in Path(full_dir).iterdir() if f.is_file() and f.name.lower().endswith(self._strm_ext)]
            if not full_strm_files:
                logger.warning(f"[STRM整理工具] 完整库目录中无STRM文件：{full_dir}")
                return
            
            # 替换目标目录的STRM
            target_dir_obj = Path(target_dir)
            # 先删除目标目录原有STRM（如果有）
            for old_strm in target_dir_obj.iterdir():
                if old_strm.is_file() and old_strm.name.lower().endswith(self._strm_ext):
                    if not self._dry_run:
                        old_strm.unlink(missing_ok=True)
                        logger.info(f"[STRM整理工具] 删除旧STRM文件：{old_strm.absolute()}")
                    else:
                        logger.info(f"[STRM整理工具] [Dry-Run] 模拟删除旧STRM文件：{old_strm.absolute()}")
            
            # 复制完整库的STRM到目标目录
            for new_strm in full_strm_files:
                dst_strm = target_dir_obj / new_strm.name
                if not self._dry_run:
                    shutil.copy2(new_strm, dst_strm)
                    logger.info(f"[STRM整理工具] 替换STRM文件：{new_strm.absolute()} → {dst_strm.absolute()}")
                else:
                    logger.info(f"[STRM整理工具] [Dry-Run] 模拟替换STRM文件：{new_strm.absolute()} → {dst_strm.absolute()}")
        
        except Exception as e:
            logger.error(f"[STRM整理工具] 替换STRM失败 {target_dir}：{str(e)}")

    def __replace_strm_batch(self, dirs: list):
        """批量替换STRM文件（新增）"""
        logger.info(f"[STRM整理工具] 开始批量替换STRM文件，共{len(dirs)}个目录，Dry-Run：{self._dry_run}")
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            # 多线程替换
            list(pool.map(lambda d: self.__replace_strm(d, self._full_root), dirs))
        logger.info("[STRM整理工具] STRM文件批量替换完成")

    def __run_replace_single(self):
        """执行单次替换任务（新增：按关键词替换）"""
        # 前置校验
        if not self._src_root or not Path(self._src_root).exists():
            err_msg = f"当前影视库路径无效：{self._src_root}"
            logger.error(f"[STRM整理工具] {err_msg}")
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
            return
        if not self._full_root or not Path(self._full_root).exists():
            err_msg = f"完整影视库路径无效：{self._full_root}"
            logger.error(f"[STRM整理工具] {err_msg}")
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
            return
        if not self._search_keyword:
            err_msg = "影视搜索关键词未输入"
            logger.error(f"[STRM整理工具] {err_msg}")
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
            return
        
        try:
            # 1. 搜索匹配的影视目录
            match_dirs = self.__search_movie(self._src_root, self._search_keyword)
            if not match_dirs:
                msg = f"未找到匹配的影视目录，关键词：{self._search_keyword}"
                logger.info(f"[STRM整理工具] {msg}")
                self.send_system_message(title="STRM整理工具", content=msg, type="info")
                return
            
            # 2. 替换匹配目录的STRM
            self.__replace_strm_batch(match_dirs)
            
            # 3. 发送完成通知
            msg = f"单次替换完成！\n- 匹配影视数：{len(match_dirs)}\n- 搜索关键词：{self._search_keyword}"
            logger.info(f"[STRM整理工具] {msg}")
            self.send_system_message(title="STRM整理工具", content=msg, type="info")
        
        except Exception as e:
            err_msg = f"单次替换任务失败：{str(e)}"
            logger.error(f"[STRM整理工具] {err_msg}", exc_info=True)
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")

    # -------------------------- 原有功能兼容调整 --------------------------
    def __find_in_full_lib(self, target: str, full_root: str = None) -> Optional[str]:
        """兼容调整：支持自定义完整库路径"""
        if not full_root:
            full_root = self._full_root
        try:
            rel_path = os.path.relpath(target, start=self._src_root)
            full_path = os.path.join(full_root, rel_path)
            return full_path if Path(full_path).exists() else None
        except Exception as e:
            logger.debug(f"[STRM整理工具] 查找完整库路径失败 {target}：{str(e)}")
            return None

    def __run_strm_task(self):
        """核心任务执行（新增替换模式兼容）"""
        # 前置校验
        if not self._src_root or not Path(self._src_root).exists():
            err_msg = f"当前影视库路径无效：{self._src_root}"
            logger.error(f"[STRM整理工具] {err_msg}")
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
            return

        try:
            # 扫描缺失STRM的目录
            logger.info(f"[STRM整理工具] 开始扫描缺失STRM的目录，源路径：{self._src_root}")
            missing_dirs = self.__scan_missing_strm(self._src_root)
            logger.info(f"[STRM整理工具] 扫描完成，共发现 {len(missing_dirs)} 个缺失STRM的目录")
            
            # 生成CSV报告
            self.__write_csv(missing_dirs)
            logger.info(f"[STRM整理工具] 扫描结果已写入CSV文件：{self._csv_file}")

            # 执行对应操作（新增replace模式）
            if self._action == "delete":
                self.__delete_strm_batch(missing_dirs)
                logger.info(f"[STRM整理工具] 删除模式执行完成，处理 {len(missing_dirs)} 个目录")
            elif self._action == "copy":
                if not self._full_root or not Path(self._full_root).exists():
                    err_msg = f"完整影视库路径无效：{self._full_root}"
                    logger.error(f"[STRM整理工具] {err_msg}")
                    self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
                    return
                if not self._out_root:
                    err_msg = "复制输出路径未配置"
                    logger.error(f"[STRM整理工具] {err_msg}")
                    self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
                    return
                self.__copy_strm_batch(missing_dirs)
                logger.info(f"[STRM整理工具] 复制模式执行完成，处理 {len(missing_dirs)} 个目录")
            elif self._action == "replace":  # 新增批量替换
                if not self._full_root or not Path(self._full_root).exists():
                    err_msg = f"完整影视库路径无效：{self._full_root}"
                    logger.error(f"[STRM整理工具] {err_msg}")
                    self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
                    return
                self.__replace_strm_batch(missing_dirs)
                logger.info(f"[STRM整理工具] 替换模式执行完成，处理 {len(missing_dirs)} 个目录")

            # 任务完成通知
            msg = f"{self._action}操作完成！\n- 处理目录数：{len(missing_dirs)}\n- 结果文件：{self._csv_file}"
            self.send_system_message(title="STRM整理工具", content=msg, type="info")
        except Exception as e:
            err_msg = f"任务执行失败：{str(e)}"
            logger.error(f"[STRM整理工具] {err_msg}", exc_info=True)
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")

    # -------------------------- 原有基础函数（无修改） --------------------------
    def __is_meta_only(self, files: list) -> bool:
        """判断是否仅包含媒体元文件"""
        if not files:
            return False
        return all(f.lower().endswith(self._meta_exts) for f in files)

    def __has_strm(self, files: list) -> bool:
        """判断是否包含STRM文件"""
        return any(f.lower().endswith(self._strm_ext) for f in files)

    def __is_final_media_dir(self, path: str) -> bool:
        """判断是否为最终媒体目录"""
        try:
            path_obj = Path(path)
            if not path_obj.is_dir():
                return False
            files = [f.name for f in path_obj.iterdir() if f.is_file()]
            dirs = [d.name for d in path_obj.iterdir() if d.is_dir()]
            return not dirs and self.__is_meta_only(files)
        except Exception as e:
            logger.debug(f"[STRM整理工具] 判断媒体目录失败 {path}：{str(e)}")
            return False

    def __scan_missing_strm(self, root: str) -> list:
        """扫描缺失STRM的目录"""
        missing_dirs = []
        for cur, dirs, files in os.walk(root, followlinks=False):
            if self.__is_final_media_dir(cur) and not self.__has_strm(files):
                missing_dirs.append(cur)
        return missing_dirs

    def __delete_strm(self, folder: str):
        """删除单个目录的STRM文件"""
        try:
            folder_obj = Path(folder)
            for file in folder_obj.iterdir():
                if file.is_file() and file.name.lower().endswith(self._strm_ext):
                    if not self._dry_run:
                        file.unlink(missing_ok=True)
                        logger.info(f"[STRM整理工具] 删除STRM文件：{file.absolute()}")
                    else:
                        logger.info(f"[STRM整理工具] [Dry-Run] 模拟删除STRM文件：{file.absolute()}")
        except Exception as e:
            logger.error(f"[STRM整理工具] 删除STRM失败 {folder}：{str(e)}")

    def __delete_strm_batch(self, dirs: list):
        """批量删除STRM文件"""
        logger.info(f"[STRM整理工具] 开始批量删除STRM文件，共{len(dirs)}个目录，Dry-Run：{self._dry_run}")
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(self.__delete_strm, dirs))
        logger.info("[STRM整理工具] STRM文件批量删除完成")

    def __copy_with_structure(self, src: str):
        """按结构复制STRM及元文件"""
        try:
            rel_path = os.path.relpath(src, start=self._full_root)
            dst_path = Path(self._out_root) / rel_path
            
            if self._dry_run:
                logger.info(f"[STRM整理工具] [Dry-Run] 模拟复制：{src} → {dst_path.absolute()}")
                return
            
            dst_path.mkdir(parents=True, exist_ok=True)
            src_obj = Path(src)
            for file in src_obj.iterdir():
                if file.is_file() and (file.name.lower().endswith(self._strm_ext) or file.name.lower().endswith(self._meta_exts)):
                    dst_file = dst_path / file.name
                    if not dst_file.exists():
                        shutil.copy2(file, dst_file)
                        logger.info(f"[STRM整理工具] 复制文件：{file.absolute()} → {dst_file.absolute()}")
        except Exception as e:
            logger.error(f"[STRM整理工具] 复制目录失败 {src}：{str(e)}")

    def __copy_strm_batch(self, dirs: list):
        """批量复制STRM文件"""
        full_lib_dirs = []
        for target_dir in dirs:
            full_dir = self.__find_in_full_lib(target_dir)
            if full_dir:
                full_lib_dirs.append(full_dir)
            else:
                logger.warning(f"[STRM整理工具] 完整库中未找到对应目录：{target_dir}")
        
        logger.info(f"[STRM整理工具] 在完整库中匹配到 {len(full_lib_dirs)} 个目录，开始复制到：{self._out_root}")
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(self.__copy_with_structure, full_lib_dirs))
        logger.info("[STRM整理工具] STRM目录批量复制完成")

    def __write_csv(self, rows: list):
        """写入CSV报告"""
        try:
            csv_path = Path(settings.PLUGIN_DATA_PATH) / self._csv_file
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["序号", "缺失STRM的目录路径"])
                for idx, dir_path in enumerate(rows, 1):
                    writer.writerow([idx, dir_path])
            logger.info(f"[STRM整理工具] CSV报告已生成：{csv_path.absolute()}")
        except Exception as e:
            logger.error(f"[STRM整理工具] 写入CSV失败：{str(e)}")

    def stop_service(self):
        """停止插件服务"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("[STRM整理工具] 调度器已停止")
        self._event.set()

    # -------------------------- 插件必需的空实现 --------------------------
    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_page(self) -> List[dict]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if self._enabled and self._cron:
            return [{
                "id": "STRMManager",
                "name": "STRM整理工具",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.__run_strm_task,
                "kwargs": {}
            }]
        return []
