import os
import shutil
import csv
import threading
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytz
from apscheduler.triggers.cron import CronTrigger

# MoviePilot V2 核心依赖导入（规范导入，确保兼容性）
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.utils.system import SystemUtils

class STRMManager(_PluginBase):
    """
    MoviePilot V2 专属 STRM 整理工具
    功能：扫描缺失 STRM 文件、批量删除 STRM、从完整库复制 STRM 及目录结构
    """
    # ---------------------- 插件基础信息（与 package.v2.json 严格一致，必须）----------------------
    plugin_name = "strm整理工具"
    plugin_desc = "扫描缺失STRM文件、批量删除STRM、从完整库复制STRM文件及目录结构（V2专属适配）"
    plugin_icon = "world.png"  # 复用官方图标，无需自定义 URL
    plugin_version = "1.0.0"   # 语义化版本，与 package.v2.json 保持一致
    plugin_author = "Daveccx"
    author_url = "https://github.com/Daveccx/MoviePilot-Plugins"
    plugin_config_prefix = "strmmanager"  # 配置前缀，纯小写，唯一标识
    plugin_order = 99  # 插件市场展示排序
    user_level = 1     # 所有用户可见（1=公开，2=仅认证用户，3=密钥可见）

    # ---------------------- 私有配置与属性（插件内部使用）----------------------
    # 操作常量
    _META_EXTS = (".jpg", ".png", ".nfo", ".srt", ".ass", ".ssa", ".webp")
    _STRM_EXT = ".strm"
    _SUPPORT_ACTIONS = ("scan", "delete", "copy")

    # 配置属性（从主程序读取）
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _src_root: str = ""
    _full_root: str = ""
    _out_root: str = ""
    _dry_run: bool = False
    _max_workers: int = 8
    _csv_file: str = "strm_result.csv"
    _action: str = "scan"

    # 任务控制属性
    _task_event: threading.Event = threading.Event()  # 任务中断信号
    _csv_report_path: Optional[Path] = None  # 生成的 CSV 报告路径

    # ---------------------- 插件核心生命周期方法（必须实现）----------------------
    def init_plugin(self, config: dict = None):
        """
        初始化插件（读取配置、触发立即任务）
        触发时机：插件启用/配置修改/主程序启动
        """
        if not config:
            config = {}

        # ---------------------- 1. 读取并校验配置（核心：参数合法性校验）----------------------
        self._enabled = config.get("enabled", False)
        self._onlyonce = config.get("onlyonce", False)
        self._cron = config.get("cron", "").strip()
        self._src_root = config.get("src_root", "").strip()
        self._full_root = config.get("full_root", "").strip()
        self._out_root = config.get("out_root", "").strip()
        self._dry_run = config.get("dry_run", False)
        self._csv_file = config.get("csv_file", "strm_result.csv").strip() or "strm_result.csv"
        self._action = config.get("action", "scan").strip()

        # 校验操作类型（仅支持预设的三种动作）
        if self._action not in self._SUPPORT_ACTIONS:
            logger.warning(f"[STRM整理工具] 无效操作类型：{self._action}，自动切换为「仅扫描」")
            self._action = "scan"

        # 校验最大工作线程数（1-32 之间，避免资源耗尽）
        try:
            self._max_workers = int(config.get("max_workers", 8))
            self._max_workers = max(1, min(32, self._max_workers))
        except (ValueError, TypeError):
            logger.warning(f"[STRM整理工具] 无效线程数配置，使用默认值 8")
            self._max_workers = 8

        # ---------------------- 2. 触发立即运行任务（仅 once 为 True 时）----------------------
        if self._onlyonce and self._enabled:
            logger.info("[STRM整理工具] 触发立即运行任务（3秒后执行）")
            # 延迟 3 秒执行，避免主程序初始化未完成
            threading.Timer(3, self.__run_strm_task).start()
            # 重置 onlyonce 配置，避免重复触发
            self.update_config({"onlyonce": False})
            self._onlyonce = False

        # ---------------------- 3. 日志初始化完成信息----------------------
        if self._enabled:
            logger.info(f"[STRM整理工具] 插件初始化完成，当前操作模式：{self._action}，定时任务：{self._cron or '关闭'}")
        else:
            logger.info(f"[STRM整理工具] 插件已禁用")

    def stop_service(self):
        """
        停止插件服务（中断正在运行的任务）
        触发时机：插件禁用/主程序关闭/配置修改
        """
        # 1. 发送中断信号，终止正在运行的扫描/删除/复制任务
        self._task_event.set()
        logger.info("[STRM整理工具] 发送任务中断信号")

        # 2. 重置中断信号，便于下次启动
        self._task_event.clear()
        logger.info("[STRM整理工具] 插件服务已停止，任务中断信号已重置")

    # ---------------------- 插件配置表单（必须实现，生成前端配置界面）----------------------
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        生成 Vuetify 配置表单（前端展示）
        返回值：(表单配置列表, 表单默认值字典)
        """
        # ---------------------- 1. 表单配置（Vuetify 组件，兼容 V2 前端）----------------------
        form_config = [
            {
                'component': 'VForm',
                'content': [
                    # 第一行：基础开关（启用/立即运行/模拟运行）
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
                    # 第二行：操作类型 & 定时配置
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
                                            'hint': '留空则关闭定时任务，格式：分 时 日 月 周'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 第三行：核心路径（当前影视库，必填）
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
                    # 第四行：复制专用路径（仅复制模式需填）
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
                                            'model': 'out_root',
                                            'label': '复制输出路径（仅复制时需填）',
                                            'placeholder': '例：/mnt/strm_copy 或 D:/strm_copy',
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 第五行：高级配置（线程数 & CSV 文件名）
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
                                            'placeholder': '默认 8，范围 1-32',
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
                                            'label': '结果CSV文件名称',
                                            'placeholder': '默认 strm_result.csv',
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 第六行：提示信息（用户引导）
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
                                                '1. 扫描模式：仅统计缺失STRM的目录并生成CSV报告，无任何修改操作；\n'
                                                '2. 删除模式：删除缺失STRM目录中的所有STRM文件（谨慎使用，建议先模拟运行）；\n'
                                                '3. 复制模式：从完整库复制对应目录的STRM及元文件到输出路径，保留目录结构；\n'
                                                '4. 模拟运行：仅打印操作日志，不执行实际的删除/复制，用于验证操作有效性；\n'
                                                '5. CSV报告：生成在 MoviePilot 插件数据目录（含日期后缀，避免覆盖）。'
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

        # ---------------------- 2. 表单默认值（与配置项一一对应）----------------------
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

    # ---------------------- 公共定时服务注册（V2 最佳实践，必须实现 get_service）----------------------
    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册公共定时服务（主程序「设定-服务」中可见，可手动触发）
        替代手动创建 BackgroundScheduler，符合 V2 插件规范
        """
        # 仅当插件启用且 cron 表达式有效时，注册定时服务
        if not self._enabled or not self._cron:
            return []

        try:
            # 验证 cron 表达式合法性
            CronTrigger.from_crontab(self._cron)
            return [{
                "id": "STRMManagerTask",  # 服务唯一 ID，不可重复
                "name": "STRM整理工具定时任务",  # 服务展示名称
                "trigger": self._cron,  # 触发器：直接传入 cron 表达式（V2 支持）
                "func": self.__run_strm_task,  # 任务执行方法
                "kwargs": {}  # 额外参数（无）
            }]
        except Exception as e:
            logger.error(f"[STRM整理工具] cron 表达式无效，无法注册定时服务：{str(e)}")
            return []

    # ---------------------- 核心任务执行逻辑（内部方法）----------------------
    def __run_strm_task(self):
        """
        执行 STRM 核心任务（扫描 → 生成 CSV → 执行对应操作）
        入口：立即任务/定时服务/手动触发
        """
        # ---------------------- 前置校验：核心路径有效性 ----------------------
        src_root_path = Path(self._src_root)
        if not self._src_root or not src_root_path.exists() or not src_root_path.is_dir():
            err_msg = f"当前影视库路径无效：{self._src_root}（路径不存在、非目录或无访问权限）"
            logger.error(f"[STRM整理工具] {err_msg}")
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
            return

        # 重置任务中断信号
        self._task_event.clear()
        self._csv_report_path = None

        try:
            # ---------------------- 步骤 1：扫描缺失 STRM 的最终媒体目录 ----------------------
            logger.info(f"[STRM整理工具] 开始扫描缺失 STRM 的目录，源路径：{src_root_path.absolute()}")
            missing_strm_dirs = self.__scan_missing_strm(src_root_path)
            logger.info(f"[STRM整理工具] 扫描完成，共发现 {len(missing_strm_dirs)} 个缺失 STRM 的目录")

            # ---------------------- 步骤 2：生成 CSV 报告 ----------------------
            self.__generate_csv_report(missing_strm_dirs)
            logger.info(f"[STRM整理工具] CSV 报告已生成：{self._csv_report_path.absolute() if self._csv_report_path else '未知路径'}")

            # ---------------------- 步骤 3：根据操作类型执行对应任务 ----------------------
            if self._action == "delete":
                self.__batch_delete_strm(missing_strm_dirs)
                logger.info(f"[STRM整理工具] 批量删除 STRM 任务完成，处理 {len(missing_strm_dirs)} 个目录")
            elif self._action == "copy":
                if not self.__validate_copy_paths():
                    return  # 复制路径校验失败，直接退出
                self.__batch_copy_strm(missing_strm_dirs)
                logger.info(f"[STRM整理工具] 批量复制 STRM 任务完成，处理 {len(missing_strm_dirs)} 个目录")

            # ---------------------- 步骤 4：任务完成通知 ----------------------
            success_content = (
                f"{self._action} 操作完成！\n"
                f"- 处理目录数：{len(missing_strm_dirs)}\n"
                f"- CSV 报告路径：{self._csv_report_path.absolute() if self._csv_report_path else '生成失败'}\n"
                f"- 操作模式：{'模拟运行' if self._dry_run else '实际运行'}"
            )
            self.send_system_message(title="STRM整理工具", content=success_content, type="info")

        except Exception as e:
            err_msg = f"任务执行失败：{str(e)}"
            logger.error(f"[STRM整理工具] {err_msg}", exc_info=True)
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
        finally:
            # 重置任务中断信号
            self._task_event.clear()

    # ---------------------- 辅助方法：路径校验（复制模式专用）----------------------
    def __validate_copy_paths(self) -> bool:
        """
        校验复制模式所需路径的有效性
        返回：True=校验通过，False=校验失败
        """
        # 校验完整影视库路径
        full_root_path = Path(self._full_root)
        if not self._full_root or not full_root_path.exists() or not full_root_path.is_dir():
            err_msg = f"完整影视库路径无效：{self._full_root}（路径不存在、非目录或无访问权限）"
            logger.error(f"[STRM整理工具] {err_msg}")
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
            return False

        # 校验/创建输出路径
        out_root_path = Path(self._out_root)
        if not self._out_root:
            err_msg = "复制输出路径未配置，请填写有效路径"
            logger.error(f"[STRM整理工具] {err_msg}")
            self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
            return False

        if not out_root_path.exists():
            try:
                out_root_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"[STRM整理工具] 已创建复制输出路径：{out_root_path.absolute()}")
            except Exception as e:
                err_msg = f"复制输出路径创建失败：{out_root_path.absolute()}，错误：{str(e)}"
                logger.error(f"[STRM整理工具] {err_msg}")
                self.send_system_message(title="STRM整理工具", content=err_msg, type="error")
                return False

        return True

    # ---------------------- 辅助方法：扫描缺失 STRM 的目录 ----------------------
    def __scan_missing_strm(self, root_path: Path) -> List[str]:
        """
        扫描所有缺失 STRM 的最终媒体目录
        参数：root_path - 根目录路径（Path 对象）
        返回：缺失 STRM 的目录路径列表（字符串格式，便于 CSV 写入）
        """
        missing_dirs = []

        # 遍历目录（followlinks=False：跳过符号链接，避免循环遍历）
        for current_dir, sub_dirs, files in os.walk(root_path, followlinks=False):
            # 检查任务中断信号，用户停止插件时退出扫描
            if self._task_event.is_set():
                logger.info("[STRM整理工具] 扫描任务被用户中断")
                break

            current_dir_path = Path(current_dir)

            # 过滤隐藏目录（以 . 开头的目录，如 .DS_Store、.git）
            sub_dirs[:] = [d for d in sub_dirs if not d.startswith(".")]

            # 判断是否为「最终媒体目录」（无子目录 + 仅包含元文件）
            if self.__is_final_media_dir(current_dir_path):
                # 判断是否缺失 STRM 文件
                has_strm = any(Path(f).suffix.lower() == self._STRM_EXT for f in files)
                if not has_strm:
                    missing_dirs.append(str(current_dir_path.absolute()))

        return missing_dirs

    def __is_final_media_dir(self, dir_path: Path) -> bool:
        """
        判断是否为「最终媒体目录」（无子目录 + 仅包含元文件）
        参数：dir_path - 目录路径（Path 对象）
        返回：True=是最终媒体目录，False=否
        """
        if not dir_path.is_dir():
            return False

        # 列出目录下的所有文件和子目录
        try:
            files = [f for f in dir_path.iterdir() if f.is_file()]
            sub_dirs = [d for d in dir_path.iterdir() if d.is_dir() and not d.name.startswith(".")]

            # 条件1：无子目录；条件2：所有文件均为元文件（无视频/其他文件）
            return len(sub_dirs) == 0 and self.__is_meta_only(files)
        except Exception as e:
            logger.debug(f"[STRM整理工具] 目录判断失败：{dir_path.absolute()}，错误：{str(e)}")
            return False

    def __is_meta_only(self, files: List[Path]) -> bool:
        """
        判断文件列表是否仅包含元文件
        参数：files - 文件路径列表（Path 对象）
        返回：True=仅元文件，False=包含其他文件
        """
        if not files:
            return False
        return all(f.suffix.lower() in self._META_EXTS for f in files)

    # ---------------------- 辅助方法：生成 CSV 报告 ----------------------
    def __generate_csv_report(self, dirs: List[str]):
        """
        生成缺失 STRM 目录的 CSV 报告（UTF-8 BOM 兼容 Excel）
        参数：dirs - 缺失 STRM 的目录路径列表
        """
        if not dirs:
            logger.info("[STRM整理工具] 无缺失 STRM 的目录，无需生成 CSV 报告")
            return

        # 构建 CSV 文件路径（插件数据目录 + 日期后缀 + 原文件名）
        csv_filename = f"{Path(self._csv_file).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{Path(self._csv_file).suffix}"
        self._csv_report_path = Path(settings.PLUGIN_DATA_PATH) / csv_filename

        # 写入 CSV 报告
        try:
            with open(self._csv_report_path, "w", encoding="utf-8-sig", newline="") as csv_file:
                csv_writer = csv.writer(csv_file)
                # 写入表头
                csv_writer.writerow(["序号", "缺失 STRM 的目录路径"])
                # 写入数据行
                for idx, dir_path in enumerate(dirs, 1):
                    csv_writer.writerow([idx, dir_path])
        except Exception as e:
            logger.error(f"[STRM整理工具] CSV 报告生成失败：{str(e)}")
            self._csv_report_path = None

    # ---------------------- 辅助方法：批量删除 STRM ----------------------
    def __batch_delete_strm(self, dirs: List[str]):
        """
        批量删除目录中的 STRM 文件（多线程）
        参数：dirs - 待处理目录路径列表
        """
        if not dirs:
            logger.info("[STRM整理工具] 无待处理目录，跳过批量删除")
            return

        logger.info(f"[STRM整理工具] 开始批量删除 STRM 文件，共 {len(dirs)} 个目录，模拟运行：{self._dry_run}")

        # 多线程执行删除任务（提高效率）
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            executor.map(self.__delete_strm_from_dir, dirs)

    def __delete_strm_from_dir(self, dir_path: str):
        """
        删除单个目录中的所有 STRM 文件
        参数：dir_path - 目录路径（字符串格式）
        """
        dir_obj = Path(dir_path)
        if not dir_obj.is_dir():
            logger.debug(f"[STRM整理工具] 目录不存在，跳过删除：{dir_path}")
            return

        # 查找目录中的所有 STRM 文件
        strm_files = [f for f in dir_obj.iterdir() if f.is_file() and f.suffix.lower() == self._STRM_EXT]

        if not strm_files:
            logger.debug(f"[STRM整理工具] 无 STRM 文件，跳过目录：{dir_path}")
            return

        # 执行删除操作
        for strm_file in strm_files:
            if self._task_event.is_set():
                break
            try:
                if not self._dry_run:
                    strm_file.unlink(missing_ok=True)  # missing_ok=True：兼容文件已被删除的情况
                    logger.info(f"[STRM整理工具] 已删除 STRM 文件：{strm_file.absolute()}")
                else:
                    logger.info(f"[STRM整理工具] [Dry-Run] 模拟删除 STRM 文件：{strm_file.absolute()}")
            except Exception as e:
                logger.error(f"[STRM整理工具] 删除 STRM 文件失败：{strm_file.absolute()}，错误：{str(e)}")

    # ---------------------- 辅助方法：批量复制 STRM ----------------------
    def __batch_copy_strm(self, dirs: List[str]):
        """
        批量从完整库复制 STRM 及元文件到输出路径（保留目录结构，多线程）
        参数：dirs - 缺失 STRM 的目录路径列表（当前影视库）
        """
        if not dirs:
            logger.info("[STRM整理工具] 无待处理目录，跳过批量复制")
            return

        # 步骤 1：匹配完整库中的对应目录
        full_root_path = Path(self._full_root)
        src_root_path = Path(self._src_root)
        full_lib_dirs = []

        for dir_path in dirs:
            if self._task_event.is_set():
                break
            try:
                # 计算相对路径，拼接完整库路径
                dir_obj = Path(dir_path)
                rel_path = dir_obj.relative_to(src_root_path)
                full_dir_obj = full_root_path / rel_path

                if full_dir_obj.exists() and full_dir_obj.is_dir():
                    full_lib_dirs.append(str(full_dir_obj.absolute()))
                else:
                    logger.warning(f"[STRM整理工具] 完整库中未找到对应目录：{dir_path}")
            except Exception as e:
                logger.error(f"[STRM整理工具] 匹配完整库目录失败：{dir_path}，错误：{str(e)}")

        if not full_lib_dirs:
            logger.info("[STRM整理工具] 完整库中无匹配目录，跳过批量复制")
            return

        # 步骤 2：多线程执行复制任务
        logger.info(f"[STRM整理工具] 开始批量复制 STRM 及元文件，共 {len(full_lib_dirs)} 个目录，输出路径：{self._out_root}")
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            executor.map(self.__copy_strm_with_structure, full_lib_dirs)

    def __copy_strm_with_structure(self, full_dir_path: str):
        """
        按目录结构复制 STRM 及元文件到输出路径
        参数：full_dir_path - 完整库中的目录路径（字符串格式）
        """
        full_dir_obj = Path(full_dir_path)
        src_root_path = Path(self._src_root)
        full_root_path = Path(self._full_root)
        out_root_path = Path(self._out_root)

        if not full_dir_obj.is_dir():
            logger.debug(f"[STRM整理工具] 完整库目录不存在，跳过复制：{full_dir_path}")
            return

        try:
            # 步骤 1：计算相对路径（保留目录结构的核心）
            rel_path = full_dir_obj.relative_to(full_root_path)
            dst_dir_obj = out_root_path / rel_path

            # 步骤 2：创建目标目录（递归创建，兼容多级目录）
            if not self._dry_run:
                dst_dir_obj.mkdir(parents=True, exist_ok=True)

            # 步骤 3：复制 STRM 及元文件
            for file in full_dir_obj.iterdir():
                if self._task_event.is_set():
                    break
                if not file.is_file():
                    continue
                # 仅复制 STRM 文件和元文件
                if file.suffix.lower() not in (self._STRM_EXT, *self._META_EXTS):
                    continue

                # 构建目标文件路径
                dst_file_obj = dst_dir_obj / file.name

                # 避免覆盖已存在的文件（严谨性判断）
                if dst_file_obj.exists() and dst_file_obj.is_file():
                    logger.debug(f"[STRM整理工具] 目标文件已存在，跳过复制：{dst_file_obj.absolute()}")
                    continue

                # 执行复制操作
                if not self._dry_run:
                    shutil.copy2(file, dst_file_obj)  # copy2：保留文件元数据（创建时间、修改时间）
                    logger.info(f"[STRM整理工具] 已复制文件：{file.absolute()} → {dst_file_obj.absolute()}")
                else:
                    logger.info(f"[STRM整理工具] [Dry-Run] 模拟复制文件：{file.absolute()} → {dst_file_obj.absolute()}")

        except Exception as e:
            logger.error(f"[STRM整理工具] 复制目录失败：{full_dir_path}，错误：{str(e)}")

    # ---------------------- V2 插件必需的空实现（确保插件注册成功，不可删除）----------------------
    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """注册远程命令（本插件无需远程命令，返回空列表）"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """暴露 API 接口（本插件无需暴露 API，返回空列表）"""
        return []

    def get_page(self) -> List[dict]:
        """生成自定义页面（本插件无需自定义页面，返回空列表）"""
        return []
