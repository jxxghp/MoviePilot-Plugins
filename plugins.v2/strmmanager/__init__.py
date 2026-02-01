import os
import shutil
import csv
import threading
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json

# MoviePilot 必需导入
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.utils.system import SystemUtils


# 统一版本号读取（兼容本地文件）
def get_plugin_version():
    """读取版本号（优先package.v2.json，失败则返回默认）"""
    try:
        # 拼接package.v2.json路径
        package_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "package.v2.json"
        )
        if os.path.exists(package_path):
            with open(package_path, "r", encoding="utf-8") as f:
                package_data = json.load(f)
            return package_data.get("STRMManager", {}).get("version", "1.0.0")
        return "1.0.0"
    except Exception as e:
        logger.warning(f"读取版本号失败，使用默认版本：{e}")
        return "1.0.0"


class STRMManager(_PluginBase):
    """
    STRM文件管理插件（MoviePilot V2兼容版）
    核心功能：扫描/删除/复制/替换STRM文件
    """
    # 插件基础信息（必需，否则加载失败）
    plugin_name: str = "STRM管理工具"
    plugin_desc: str = "扫描、删除、复制、替换STRM文件（详情页操作）"
    plugin_icon: str = "mdi-file-document-outline"  # 使用内置图标，避免自定义图标加载失败
    plugin_version: str = get_plugin_version()
    plugin_author: str = "Daveccx"
    plugin_config_prefix: str = "strmmanager_"
    plugin_order: int = 99
    user_level: int = 1

    # 初始化核心变量（简化，避免未定义）
    _enabled: bool = False
    _cron: str = ""
    _default_src_root: str = ""
    _default_full_root: str = ""
    _default_out_root: str = ""
    _dry_run: bool = False
    _max_workers: int = 8
    _csv_file: str = "strm_result.csv"
    # 详情页变量（必需初始化）
    _page_src_root: str = ""
    _page_full_root: str = ""
    _page_out_root: str = ""
    _page_search_keyword: str = ""
    _page_action: str = "scan"
    _page_result: str = "请选择操作类型并点击【执行操作】开始处理"

    def init_plugin(self, config: dict = None):
        """
        插件初始化（必需方法，MoviePilot加载插件时调用）
        """
        try:
            # 初始化配置（兼容空配置）
            if config:
                self._enabled = config.get("enabled", False)
                self._cron = config.get("cron", "")
                self._default_src_root = config.get("default_src_root", "").strip()
                self._default_full_root = config.get("default_full_root", "").strip()
                self._default_out_root = config.get("default_out_root", "").strip()
                self._dry_run = config.get("dry_run", False)
                self._max_workers = int(config.get("max_workers", 8))
                self._csv_file = config.get("csv_file", "strm_result.csv").strip()

            # 初始化详情页参数（关键：避免页面变量未定义）
            self._page_src_root = self._default_src_root
            self._page_full_root = self._default_full_root
            self._page_out_root = self._default_out_root

            logger.info(f"STRM管理工具插件初始化完成，版本：{self.plugin_version}")
        except Exception as e:
            logger.error(f"STRM管理工具插件初始化失败：{e}")
            # 初始化失败时强制赋值，避免加载崩溃
            self._page_result = f"初始化失败：{str(e)}"

    def get_state(self) -> bool:
        """
        获取插件启用状态（必需方法）
        """
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        配置页（简化版，确保能显示）
        """
        # 配置页结构（严格符合MoviePilot V2规范）
        form_config = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用定时任务",
                                            "true-value": True,
                                            "false-value": False,
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "dry_run",
                                            "label": "模拟运行",
                                            "true-value": True,
                                            "false-value": False,
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VFileSelector",
                                        "props": {
                                            "model": "default_src_root",
                                            "label": "默认当前影视库路径",
                                            "type": "directory",
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VFileSelector",
                                        "props": {
                                            "model": "default_full_root",
                                            "label": "默认完整影视库路径",
                                            "type": "directory",
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VFileSelector",
                                        "props": {
                                            "model": "default_out_root",
                                            "label": "默认输出路径（复制用）",
                                            "type": "directory",
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "定时任务Cron表达式",
                                            "placeholder": "0 0 * * *",
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_workers",
                                            "label": "最大工作线程数",
                                            "type": "number",
                                            "default": 8,
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        # 配置页默认值（必需，避免渲染错误）
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

    def get_page(self) -> List[dict]:
        """
        详情页（核心操作页，简化渲染逻辑）
        """
        return [
            {
                "component": "div",
                "props": {"class": "plugin-page"},
                "content": [
                    {
                        "component": "VCard",
                        "props": {"variant": "outlined", "class": "mb-4"},
                        "content": [
                            {
                                "component": "VCardTitle",
                                "props": {"title": "STRM文件操作", "class": "text-h6"}
                            },
                            {
                                "component": "VCardText",
                                "content": [
                                    # 路径选择
                                    {
                                        "component": "VFileSelector",
                                        "props": {
                                            "model": "page_src_root",
                                            "label": "当前影视库路径",
                                            "type": "directory",
                                            "variant": "outlined",
                                            "class": "mb-3"
                                        }
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 6},
                                                "content": [
                                                    {
                                                        "component": "VFileSelector",
                                                        "props": {
                                                            "model": "page_full_root",
                                                            "label": "完整影视库路径",
                                                            "type": "directory",
                                                            "variant": "outlined",
                                                            "class": "mb-3"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 6},
                                                "content": [
                                                    {
                                                        "component": "VFileSelector",
                                                        "props": {
                                                            "model": "page_out_root",
                                                            "label": "输出路径（复制用）",
                                                            "type": "directory",
                                                            "variant": "outlined",
                                                            "class": "mb-3"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 搜索+操作类型
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 6},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "page_search_keyword",
                                                            "label": "影视搜索关键词",
                                                            "placeholder": "例：星际穿越",
                                                            "variant": "outlined",
                                                            "class": "mb-3"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 6},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "page_action",
                                                            "label": "操作类型",
                                                            "items": [
                                                                {"title": "扫描缺失STRM", "value": "scan"},
                                                                {"title": "删除STRM文件", "value": "delete"},
                                                                {"title": "复制STRM文件", "value": "copy"},
                                                                {"title": "替换STRM文件", "value": "replace"}
                                                            ],
                                                            "variant": "outlined",
                                                            "class": "mb-3"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 操作按钮
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VBtn",
                                                        "props": {"color": "primary", "class": "w-100"},
                                                        "text": "执行操作",
                                                        "click": "call:execute_action"
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VBtn",
                                                        "props": {"color": "secondary", "class": "w-100"},
                                                        "text": "加载默认路径",
                                                        "click": "call:load_defaults"
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VBtn",
                                                        "props": {"color": "error", "class": "w-100"},
                                                        "text": "清空结果",
                                                        "click": "call:clear_result"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 结果展示
                    {
                        "component": "VCard",
                        "props": {"variant": "outlined"},
                        "content": [
                            {
                                "component": "VCardTitle",
                                "props": {"title": "操作结果", "class": "text-h6"}
                            },
                            {
                                "component": "VCardText",
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "page_result",
                                            "label": "日志",
                                            "multiline": True,
                                            "rows": 8,
                                            "readonly": True,
                                            "variant": "outlined"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    # -------------------------- 详情页事件处理（简化，确保能执行） --------------------------
    def execute_action(self, **kwargs):
        """执行操作按钮点击事件"""
        try:
            # 基础校验
            if not self._page_src_root or not Path(self._page_src_root).exists():
                self._page_result = f"错误：当前影视库路径无效 → {self._page_src_root}"
                self._update_page()
                return

            self._page_result = f"开始执行【{self._page_action}】操作 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            self._update_page()

            # 扫描缺失STRM的目录
            missing_dirs = self._scan_missing_strm(self._page_src_root)
            self._page_result += f"✅ 扫描完成，缺失STRM目录数：{len(missing_dirs)}\n"
            self._update_page()

            # 执行对应操作
            if self._page_action == "scan":
                self._write_csv(missing_dirs)
                self._page_result += f"📝 结果已写入CSV：{os.path.join(settings.PLUGIN_DATA_PATH, self._csv_file)}\n"
                self._page_result += "📋 缺失目录列表：\n" + "\n".join([f"- {d}" for d in missing_dirs])
            elif self._page_action == "delete":
                self._delete_strm_batch(missing_dirs)
                self._page_result += f"🗑️ 删除完成，处理目录数：{len(missing_dirs)}"
            elif self._page_action == "copy":
                if not self._page_full_root or not Path(self._page_full_root).exists():
                    self._page_result += "❌ 完整影视库路径无效"
                    self._update_page()
                    return
                if not self._page_out_root or not Path(self._page_out_root).exists():
                    self._page_result += "❌ 输出路径无效"
                    self._update_page()
                    return
                full_dirs = [self._find_full_dir(d) for d in missing_dirs if self._find_full_dir(d)]
                self._copy_strm_batch(full_dirs)
                self._page_result += f"📤 复制完成，处理目录数：{len(full_dirs)}"
            elif self._page_action == "replace":
                if not self._page_full_root or not Path(self._page_full_root).exists():
                    self._page_result += "❌ 完整影视库路径无效"
                    self._update_page()
                    return
                # 支持关键词搜索
                target_dirs = self._search_movie(self._page_src_root, self._page_search_keyword) if self._page_search_keyword else missing_dirs
                self._replace_strm_batch(target_dirs)
                self._page_result += f"🔄 替换完成，处理目录数：{len(target_dirs)}"

            # 模拟运行提示
            if self._dry_run:
                self._page_result += "\n⚠️ 模拟运行模式，未修改任何文件！"

        except Exception as e:
            self._page_result += f"\n❌ 操作失败：{str(e)}"
            logger.error(f"STRM操作失败：{e}")

        self._update_page()

    def load_defaults(self, **kwargs):
        """加载默认路径"""
        self._page_src_root = self._default_src_root
        self._page_full_root = self._default_full_root
        self._page_out_root = self._default_out_root
        self._page_result = f"已加载默认路径：\n- 当前库：{self._page_src_root}\n- 完整库：{self._page_full_root}\n- 输出路径：{self._page_out_root}"
        self._update_page()

    def clear_result(self, **kwargs):
        """清空结果"""
        self._page_result = "请选择操作类型并点击【执行操作】开始处理"
        self._update_page()

    def _update_page(self):
        """更新详情页参数（关键：确保页面刷新）"""
        self.update_config({
            "page_src_root": self._page_src_root,
            "page_full_root": self._page_full_root,
            "page_out_root": self._page_out_root,
            "page_search_keyword": self._page_search_keyword,
            "page_action": self._page_action,
            "page_result": self._page_result
        })

    # -------------------------- 核心功能函数（简化，确保稳定） --------------------------
    def _scan_missing_strm(self, root: str) -> list:
        """扫描缺失STRM的目录"""
        missing = []
        for root_dir, dirs, files in os.walk(root):
            # 判断是否为媒体目录（无子目录 + 包含媒体元文件）
            if not dirs and any(f.lower().endswith((".jpg", ".png", ".nfo")) for f in files):
                # 检查是否有STRM文件
                if not any(f.lower().endswith(".strm") for f in files):
                    missing.append(root_dir)
        return missing

    def _search_movie(self, root: str, keyword: str) -> list:
        """按关键词搜索目录"""
        if not keyword:
            return self._scan_missing_strm(root)
        keyword = keyword.lower()
        match = []
        for root_dir, dirs, files in os.walk(root):
            if keyword in root_dir.lower() and not dirs:
                match.append(root_dir)
        return match

    def _find_full_dir(self, target_dir: str) -> Optional[str]:
        """从完整库查找对应目录"""
        try:
            rel_path = os.path.relpath(target_dir, self._page_src_root)
            full_path = os.path.join(self._page_full_root, rel_path)
            return full_path if Path(full_path).exists() else None
        except Exception as e:
            logger.error(f"查找完整目录失败：{e}")
            return None

    def _delete_strm_batch(self, dirs: list):
        """批量删除STRM文件"""
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            pool.map(self._delete_strm, dirs)

    def _delete_strm(self, dir_path: str):
        """删除单个目录的STRM文件"""
        try:
            for file in Path(dir_path).glob("*.strm"):
                if not self._dry_run:
                    file.unlink(missing_ok=True)
                logger.info(f"删除STRM：{file}")
        except Exception as e:
            logger.error(f"删除STRM失败 {dir_path}：{e}")

    def _copy_strm_batch(self, dirs: list):
        """批量复制STRM文件"""
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            pool.map(self._copy_strm, dirs)

    def _copy_strm(self, src_dir: str):
        """复制STRM文件到输出路径"""
        try:
            rel_path = os.path.relpath(src_dir, self._page_full_root)
            dst_dir = Path(self._page_out_root) / rel_path
            if not self._dry_run:
                dst_dir.mkdir(parents=True, exist_ok=True)
            for file in Path(src_dir).glob("*.strm"):
                dst_file = dst_dir / file.name
                if not self._dry_run:
                    shutil.copy2(file, dst_file)
                logger.info(f"复制STRM：{file} → {dst_file}")
        except Exception as e:
            logger.error(f"复制STRM失败 {src_dir}：{e}")

    def _replace_strm_batch(self, dirs: list):
        """批量替换STRM文件"""
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            pool.map(self._replace_strm, dirs)

    def _replace_strm(self, target_dir: str):
        """替换单个目录的STRM文件"""
        try:
            full_dir = self._find_full_dir(target_dir)
            if not full_dir:
                logger.warning(f"完整库中无对应目录：{target_dir}")
                return
            # 删除旧STRM
            self._delete_strm(target_dir)
            # 复制新STRM
            for file in Path(full_dir).glob("*.strm"):
                dst_file = Path(target_dir) / file.name
                if not self._dry_run:
                    shutil.copy2(file, dst_file)
                logger.info(f"替换STRM：{file} → {dst_file}")
        except Exception as e:
            logger.error(f"替换STRM失败 {target_dir}：{e}")

    def _write_csv(self, dirs: list):
        """写入CSV报告"""
        try:
            csv_path = Path(settings.PLUGIN_DATA_PATH) / self._csv_file
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["序号", "缺失STRM的目录路径"])
                for idx, dir_path in enumerate(dirs, 1):
                    writer.writerow([idx, dir_path])
            logger.info(f"CSV报告已生成：{csv_path}")
        except Exception as e:
            logger.error(f"写入CSV失败：{e}")

    def stop_service(self):
        """停止插件服务（必需方法）"""
        logger.info("STRM管理工具插件已停止")


# 插件注册（MoviePilot V2必需）
def get_plugin():
    return STRMManager()
