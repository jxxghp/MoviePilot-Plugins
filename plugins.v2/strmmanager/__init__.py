import os
import shutil
import csv
import threading
import fnmatch
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# V2适配：保留必要导入
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.utils.system import SystemUtils


# 统一版本号读取（从package.v2.json）
def get_plugin_version():
    """从package.v2.json读取插件版本号"""
    try:
        package_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "package.v2.json"
        )
        with open(package_path, "r", encoding="utf-8") as f:
            package_data = json.load(f)
        return package_data.get("STRMManager", {}).get("version", "1.1.0")
    except Exception as e:
        logger.warning(f"读取版本号失败，使用默认版本：{e}")
        return "1.1.0"


class STRMManager(_PluginBase):
    # 插件基础信息
    plugin_name = "strm整理工具"
    plugin_desc = "扫描/删除/复制/替换STRM文件（详情页操作，支持文件管理）"
    plugin_icon = "Docker_E.png"
    plugin_version = get_plugin_version()
    plugin_author = "Daveccx"
    author_url = "https://github.com/Daveccx/MoviePilot-Plugins"
    plugin_config_prefix = "strmmanager_"
    plugin_order = 99
    user_level = 1

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled: bool = False
    _cron: str = ""
    _default_src_root: str = ""  # 配置页设置的默认当前库路径
    _default_full_root: str = ""  # 配置页设置的默认完整库路径
    _default_out_root: str = ""  # 配置页设置的默认输出路径
    _dry_run: bool = False
    _max_workers: int = 8
    _csv_file: str = "strm_result.csv"
    # 详情页临时操作参数（核心：绑定详情页控件）
    _page_src_root: str = ""
    _page_full_root: str = ""
    _page_out_root: str = ""
    _page_search_keyword: str = ""
    _page_action: str = "scan"
    _page_result: str = ""  # 详情页操作结果展示
    _event: threading.Event = threading.Event()

    def init_plugin(self, config: dict = None):
        """初始化插件（仅处理配置页的基础配置）"""
        if config:
            self._enabled = config.get("enabled", False)
            self._cron = config.get("cron", "")
            self._default_src_root = config.get("default_src_root", "").strip()
            self._default_full_root = config.get("default_full_root", "").strip()
            self._default_out_root = config.get("default_out_root", "").strip()
            self._dry_run = config.get("dry_run", False)
            self._max_workers = int(config.get("max_workers", 8))
            self._csv_file = config.get("csv_file", "strm_result.csv").strip()

        # 初始化详情页默认值（从配置页的默认路径读取）
        self._page_src_root = self._default_src_root
        self._page_full_root = self._default_full_root
        self._page_out_root = self._default_out_root
        self._page_result = "请选择操作类型并点击【执行操作】按钮开始处理"

        # 停止现有定时任务
        self.stop_service()

        # 启动定时任务（仅配置页的定时批量操作）
        if self._enabled and self._cron:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"[STRM整理工具] 启动定时任务，周期：{self._cron}")
            try:
                self._scheduler.add_job(
                    func=self.__run_cron_task,
                    trigger=CronTrigger.from_crontab(self._cron),
                    name="STRM整理定时任务"
                )
                self._scheduler.start()
                logger.info("[STRM整理工具] 定时任务启动完成")
            except Exception as e:
                err_msg = f"定时任务启动失败：{str(e)}"
                logger.error(f"[STRM整理工具] {err_msg}")
                self.send_system_message(
                    title="STRM整理工具",
                    content=err_msg,
                    type="error"
                )

    def get_state(self) -> bool:
        """获取插件启用状态"""
        return self._enabled

    # -------------------------- 修复核心：配置页（仅基础设置） --------------------------
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """配置页：仅保留基础配置，核心操作移到详情页"""
        form_config = [
            {
                'component': 'VForm',
                'content': [
                    # 基础开关
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用定时任务',
                                            'true-value': True,
                                            'false-value': False,
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
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'dry_run',
                                            'label': '全局模拟运行',
                                            'true-value': True,
                                            'false-value': False,
                                            'variant': 'outlined',
                                            'hint': '所有操作仅打印日志，不实际修改文件'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 定时配置
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
                    # 默认路径配置（文件管理：目录选择器）
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VFileSelector',
                                        'props': {
                                            'model': 'default_src_root',
                                            'label': '默认当前影视库路径',
                                            'placeholder': '选择目标影视所在的根目录',
                                            'type': 'directory',
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
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
                                            'model': 'default_full_root',
                                            'label': '默认完整影视库路径',
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
                                            'model': 'default_out_root',
                                            'label': '默认输出路径（复制时用）',
                                            'placeholder': '选择STRM复制的目标目录',
                                            'type': 'directory',
                                            'variant': 'outlined'
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
                                                '1. 核心操作请前往插件【详情页】进行（扫描/删除/复制/替换）；\n'
                                                '2. 此处仅设置定时任务和默认路径，详情页可临时修改路径；\n'
                                                '3. 模拟运行：所有操作仅打印日志，不执行实际的文件修改；\n'
                                                '4. 定时任务：按配置周期执行批量操作（操作类型为扫描）。'
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
        # 配置页默认值
        default_config = {
            "enabled": False,
            "cron": "",
            "default_src_root": "",
            "default_full_root": "",
            "default_out_root": "",
            "dry_run": False,
            "max_workers": 8,
            "csv_file": "strm_result.csv"
        }
        return form_config, default_config

    # -------------------------- 修复核心：详情页（所有操作在这里） --------------------------
    def get_page(self) -> List[dict]:
        """详情页：实现所有核心操作（文件管理、搜索、替换等）"""
        return [
            {
                'component': 'div',
                'props': {'class': 'plugin-page strm-manager-page'},
                'content': [
                    # 操作区：目录选择 + 搜索 + 操作类型
                    {
                        'component': 'VCard',
                        'props': {'variant': 'outlined', 'class': 'mb-4'},
                        'content': [
                            {
                                'component': 'VCardTitle',
                                'props': {'title': 'STRM文件管理操作', 'class': 'text-h6'}
                            },
                            {
                                'component': 'VCardText',
                                'content': [
                                    # 目录选择（文件管理核心：修复消失问题）
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12},
                                                'content': [
                                                    {
                                                        'component': 'VFileSelector',
                                                        'props': {
                                                            'model': 'page_src_root',
                                                            'label': '当前影视库路径',
                                                            'placeholder': '选择目标影视所在的根目录',
                                                            'type': 'directory',
                                                            'variant': 'outlined',
                                                            'class': 'mb-3'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
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
                                                            'model': 'page_full_root',
                                                            'label': '完整影视库路径',
                                                            'placeholder': '选择包含完整STRM的影视库目录',
                                                            'type': 'directory',
                                                            'variant': 'outlined',
                                                            'class': 'mb-3'
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
                                                            'model': 'page_out_root',
                                                            'label': '输出路径（复制时用）',
                                                            'placeholder': '选择STRM复制的目标目录',
                                                            'type': 'directory',
                                                            'variant': 'outlined',
                                                            'class': 'mb-3'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 影视搜索 + 操作类型
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
                                                            'model': 'page_search_keyword',
                                                            'label': '影视搜索关键词',
                                                            'placeholder': '输入影视名称（支持模糊匹配），例：星际穿越',
                                                            'variant': 'outlined',
                                                            'class': 'mb-3'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'page_action',
                                                            'label': '操作类型',
                                                            'items': [
                                                                {'title': '仅扫描缺失STRM', 'value': 'scan'},
                                                                {'title': '删除目录中STRM', 'value': 'delete'},
                                                                {'title': '从完整库复制STRM', 'value': 'copy'},
                                                                {'title': '从完整库替换STRM', 'value': 'replace'}
                                                            ],
                                                            'variant': 'outlined',
                                                            'clearable': False,
                                                            'class': 'mb-3'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 操作按钮
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VBtn',
                                                        'props': {
                                                            'color': 'primary',
                                                            'variant': 'elevated',
                                                            'class': 'w-100'
                                                        },
                                                        'text': '执行操作',
                                                        'click': 'call:execute_page_action'  # 绑定点击事件
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VBtn',
                                                        'props': {
                                                            'color': 'secondary',
                                                            'variant': 'elevated',
                                                            'class': 'w-100'
                                                        },
                                                        'text': '清空结果',
                                                        'click': 'call:clear_page_result'  # 绑定清空事件
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 4},
                                                'content': [
                                                    {
                                                        'component': 'VBtn',
                                                        'props': {
                                                            'color': 'success',
                                                            'variant': 'elevated',
                                                            'class': 'w-100'
                                                        },
                                                        'text': '加载默认路径',
                                                        'click': 'call:load_default_paths'  # 加载配置页默认路径
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 结果展示区
                    {
                        'component': 'VCard',
                        'props': {'variant': 'outlined'},
                        'content': [
                            {
                                'component': 'VCardTitle',
                                'props': {'title': '操作结果', 'class': 'text-h6'}
                            },
                            {
                                'component': 'VCardText',
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'page_result',
                                            'label': '日志/结果',
                                            'multiline': True,
                                            'rows': 10,
                                            'readonly': True,
                                            'variant': 'outlined'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    # -------------------------- 详情页事件处理（核心修复） --------------------------
    def execute_page_action(self, **kwargs):
        """详情页【执行操作】按钮点击事件"""
        # 校验路径
        if not self._page_src_root or not Path(self._page_src_root).exists():
            self._page_result = f"错误：当前影视库路径无效 → {self._page_src_root}"
            self.update_page_params()
            return

        # 不同操作类型的前置校验
        if self._page_action in ["copy", "replace"] and (not self._page_full_root or not Path(self._page_full_root).exists()):
            self._page_result = f"错误：完整影视库路径无效 → {self._page_full_root}"
            self.update_page_params()
            return

        if self._page_action == "copy" and (not self._page_out_root or not Path(self._page_out_root).exists()):
            self._page_result = f"错误：复制输出路径无效 → {self._page_out_root}"
            self.update_page_params()
            return

        # 执行操作
        try:
            self._page_result = f"开始执行【{self._page_action}】操作...\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            self.update_page_params()

            # 扫描缺失STRM的目录
            missing_dirs = self.__scan_missing_strm(self._page_src_root)
            self._page_result += f"✅ 扫描完成，缺失STRM的目录数：{len(missing_dirs)}\n"
            self.update_page_params()

            # 根据操作类型执行
            if self._page_action == "scan":
                # 仅扫描，生成CSV
                self.__write_csv(missing_dirs)
                self._page_result += f"✅ 扫描结果已写入CSV：{os.path.join(settings.PLUGIN_DATA_PATH, self._csv_file)}\n"
                self._page_result += "📋 缺失STRM的目录列表：\n" + "\n".join([f"- {d}" for d in missing_dirs])
            elif self._page_action == "delete":
                # 删除STRM
                self.__delete_strm_batch(missing_dirs)
                self._page_result += f"✅ 删除操作完成，处理目录数：{len(missing_dirs)}\n"
                self._page_result += "🗑️ 已处理目录：\n" + "\n".join([f"- {d}" for d in missing_dirs])
            elif self._page_action == "copy":
                # 复制STRM
                full_lib_dirs = [self.__find_in_full_lib(d, self._page_full_root) for d in missing_dirs if self.__find_in_full_lib(d, self._page_full_root)]
                self.__copy_strm_batch(full_lib_dirs, self._page_out_root)
                self._page_result += f"✅ 复制操作完成，成功复制目录数：{len(full_lib_dirs)}\n"
                self._page_result += "📤 已复制目录：\n" + "\n".join([f"- {d}" for d in full_lib_dirs])
            elif self._page_action == "replace":
                # 替换STRM（支持搜索关键词）
                if self._page_search_keyword:
                    # 按关键词搜索并替换
                    match_dirs = self.__search_movie(self._page_src_root, self._page_search_keyword)
                    self.__replace_strm_batch(match_dirs, self._page_full_root)
                    self._page_result += f"✅ 按关键词替换完成，匹配目录数：{len(match_dirs)}\n"
                    self._page_result += f"🔍 搜索关键词：{self._page_search_keyword}\n"
                    self._page_result += "🔄 已替换目录：\n" + "\n".join([f"- {d}" for d in match_dirs])
                else:
                    # 批量替换所有缺失STRM的目录
                    self.__replace_strm_batch(missing_dirs, self._page_full_root)
                    self._page_result += f"✅ 批量替换完成，处理目录数：{len(missing_dirs)}\n"
                    self._page_result += "🔄 已替换目录：\n" + "\n".join([f"- {d}" for d in missing_dirs])

            # 模拟运行提示
            if self._dry_run:
                self._page_result += "\n⚠️ 注意：当前为【模拟运行】模式，未实际修改任何文件！"

        except Exception as e:
            self._page_result += f"\n❌ 操作失败：{str(e)}"
            logger.error(f"[STRM整理工具] 详情页操作失败：{e}", exc_info=True)

        # 更新详情页参数
        self.update_page_params()

    def clear_page_result(self, **kwargs):
        """详情页【清空结果】按钮点击事件"""
        self._page_result = "请选择操作类型并点击【执行操作】按钮开始处理"
        self.update_page_params()

    def load_default_paths(self, **kwargs):
        """详情页【加载默认路径】按钮点击事件（从配置页读取）"""
        self._page_src_root = self._default_src_root
        self._page_full_root = self._default_full_root
        self._page_out_root = self._default_out_root
        self._page_result = f"已加载配置页默认路径：\n- 当前库：{self._page_src_root}\n- 完整库：{self._page_full_root}\n- 输出路径：{self._page_out_root}"
        self.update_page_params()

    def update_page_params(self):
        """更新详情页参数（关键：让页面实时刷新）"""
        self.update_config({
            "page_src_root": self._page_src_root,
            "page_full_root": self._page_full_root,
            "page_out_root": self._page_out_root,
            "page_search_keyword": self._page_search_keyword,
            "page_action": self._page_action,
            "page_result": self._page_result
        })

    # -------------------------- 核心功能函数（适配详情页） --------------------------
    def __run_cron_task(self):
        """定时任务执行（仅批量扫描）"""
        if not self._default_src_root or not Path(self._default_src_root).exists():
            logger.error(f"[STRM整理工具] 定时任务路径无效：{self._default_src_root}")
            return
        missing_dirs = self.__scan_missing_strm(self._default_src_root)
        self.__write_csv(missing_dirs)
        logger.info(f"[STRM整理工具] 定时任务完成，缺失STRM目录数：{len(missing_dirs)}")
        self.send_system_message(
            title="STRM整理工具-定时任务",
            content=f"定时扫描完成\n- 缺失STRM目录数：{len(missing_dirs)}\n- 结果已写入：{os.path.join(settings.PLUGIN_DATA_PATH, self._csv_file)}",
            type="info"
        )

    def __scan_missing_strm(self, root: str) -> list:
        """扫描缺失STRM的目录"""
        missing_dirs = []
        for cur, dirs, files in os.walk(root, followlinks=False):
            if self.__is_final_media_dir(cur) and not self.__has_strm(files):
                missing_dirs.append(cur)
        return missing_dirs

    def __search_movie(self, root: str, keyword: str) -> list:
        """模糊搜索影视目录"""
        if not keyword:
            return self.__scan_missing_strm(root)
        match_dirs = []
        keyword_lower = keyword.lower()
        for cur, dirs, files in os.walk(root, followlinks=False):
            if keyword_lower in cur.lower() and self.__is_final_media_dir(cur):
                match_dirs.append(cur)
        return match_dirs

    def __replace_strm(self, target_dir: str, full_root: str):
        """替换单个目录的STRM"""
        try:
            full_dir = self.__find_in_full_lib(target_dir, full_root)
            if not full_dir:
                logger.warning(f"完整库中未找到对应目录：{target_dir}")
                return
            # 删除旧STRM
            for old_strm in Path(target_dir).glob(f"*{self._strm_ext}"):
                if not self._dry_run:
                    old_strm.unlink(missing_ok=True)
                logger.info(f"删除旧STRM：{old_strm}")
            # 复制新STRM
            for new_strm in Path(full_dir).glob(f"*{self._strm_ext}"):
                dst_strm = Path(target_dir) / new_strm.name
                if not self._dry_run:
                    shutil.copy2(new_strm, dst_strm)
                logger.info(f"替换STRM：{new_strm} → {dst_strm}")
        except Exception as e:
            logger.error(f"替换STRM失败 {target_dir}：{e}")

    def __replace_strm_batch(self, dirs: list, full_root: str):
        """批量替换STRM"""
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(lambda d: self.__replace_strm(d, full_root), dirs))

    def __delete_strm(self, folder: str):
        """删除单个目录的STRM"""
        try:
            for file in Path(folder).glob(f"*{self._strm_ext}"):
                if not self._dry_run:
                    file.unlink(missing_ok=True)
                logger.info(f"删除STRM：{file}")
        except Exception as e:
            logger.error(f"删除STRM失败 {folder}：{e}")

    def __delete_strm_batch(self, dirs: list):
        """批量删除STRM"""
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(self.__delete_strm, dirs))

    def __copy_strm(self, src: str, out_root: str, full_root: str):
        """复制STRM到输出路径"""
        try:
            rel_path = os.path.relpath(src, start=full_root)
            dst_path = Path(out_root) / rel_path
            if not self._dry_run:
                dst_path.mkdir(parents=True, exist_ok=True)
            for file in Path(src).glob(f"*{self._strm_ext}"):
                dst_file = dst_path / file.name
                if not self._dry_run:
                    shutil.copy2(file, dst_file)
                logger.info(f"复制STRM：{file} → {dst_file}")
        except Exception as e:
            logger.error(f"复制STRM失败 {src}：{e}")

    def __copy_strm_batch(self, dirs: list, out_root: str):
        """批量复制STRM"""
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            list(pool.map(lambda d: self.__copy_strm(d, out_root, self._page_full_root), dirs))

    def __find_in_full_lib(self, target: str, full_root: str) -> Optional[str]:
        """从完整库查找对应目录"""
        try:
            rel_path = os.path.relpath(target, start=self._page_src_root)
            full_path = os.path.join(full_root, rel_path)
            return full_path if Path(full_path).exists() else None
        except Exception as e:
            logger.debug(f"查找完整库路径失败 {target}：{e}")
            return None

    def __write_csv(self, rows: list):
        """写入CSV报告"""
        try:
            csv_path = Path(settings.PLUGIN_DATA_PATH) / self._csv_file
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["序号", "缺失STRM的目录路径"])
                for idx, dir_path in enumerate(rows, 1):
                    writer.writerow([idx, dir_path])
            logger.info(f"CSV报告已生成：{csv_path}")
        except Exception as e:
            logger.error(f"写入CSV失败：{e}")

    # -------------------------- 基础工具函数 --------------------------
    def __is_meta_only(self, files: list) -> bool:
        """判断是否仅包含媒体元文件"""
        if not files:
            return False
        return all(f.lower().endswith((".jpg", ".png", ".nfo", ".srt", ".ass", ".ssa", ".webp")) for f in files)

    def __has_strm(self, files: list) -> bool:
        """判断是否包含STRM文件"""
        return any(f.lower().endswith(".strm") for f in files)

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
            logger.debug(f"判断媒体目录失败 {path}：{e}")
            return False

    def stop_service(self):
        """停止插件服务"""
