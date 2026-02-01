import os
import shutil
import csv
import threading
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json

# MoviePilot 核心依赖（必需）
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.utils.system import SystemUtils


# 版本号读取（兼容本地配置）
def get_plugin_version() -> str:
    """读取插件版本号"""
    try:
        package_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "package.v2.json"
        )
        if os.path.exists(package_path):
            with open(package_path, "r", encoding="utf-8") as f:
                return json.load(f).get("STRMManager", {}).get("version", "1.1.0")
        return "1.1.0"
    except Exception as e:
        logger.warning(f"读取版本号失败：{e}，使用默认版本1.1.0")
        return "1.1.0"


class STRMManager(_PluginBase):
    """STRM文件管理插件（全UI可视化版）"""
    # 插件基础信息（MoviePilot必需）
    plugin_name: str = "STRM文件管理器"
    plugin_desc: str = "可视化管理STRM文件（扫描/删除/复制/替换）"
    plugin_icon: str = "mdi-file-document-multiple-outline"  # 内置图标（确保显示）
    plugin_version: str = get_plugin_version()
    plugin_author: str = "Daveccx"
    plugin_config_prefix: str = "strmmanager_"
    plugin_order: int = 50  # 插件展示顺序
    user_level: int = 1     # 所有用户可见

    # 核心状态变量（可视化绑定）
    _enabled: bool = False  # 仅用于插件启用标识（无实际功能）
    # 可视化操作参数（绑定UI组件）
    _page_src_dir: str = ""          # 当前影视库目录（UI选择）
    _page_full_dir: str = ""         # 完整STRM库目录（UI选择）
    _page_out_dir: str = ""          # 复制输出目录（UI选择）
    _page_keyword: str = ""          # 搜索关键词（UI输入）
    _page_action: str = "scan"       # 当前选择操作（UI下拉）
    _page_progress: int = 0          # 操作进度（UI进度条）
    _page_log: str = "📌 欢迎使用STRM文件管理器\n请选择目录和操作类型，点击【执行操作】开始\n"  # 操作日志（UI文本框）
    _page_dry_run: bool = True       # 模拟运行（UI开关）
    _page_running: bool = False      # 操作中状态（禁用按钮）

    def init_plugin(self, config: dict = None):
        """插件初始化（加载保存的配置）"""
        if not config:
            logger.info("STRM文件管理器初始化：无配置，使用默认值")
            return

        # 加载可视化参数（确保UI状态恢复）
        self._page_src_dir = config.get("page_src_dir", "")
        self._page_full_dir = config.get("page_full_dir", "")
        self._page_out_dir = config.get("page_out_dir", "")
        self._page_keyword = config.get("page_keyword", "")
        self._page_action = config.get("page_action", "scan")
        self._page_dry_run = config.get("page_dry_run", True)
        self._page_log = config.get("page_log", self._page_log)
        
        logger.info("STRM文件管理器初始化完成")

    def get_state(self) -> bool:
        """获取插件启用状态（MoviePilot必需）"""
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """配置页（简化，仅保留插件启用开关）"""
        form_config = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件（仅标识，不影响功能）",
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
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "outlined"
                                        },
                                        "text": "✅ 核心功能请前往【详情页】操作\n📌 所有操作支持可视化选择和实时反馈\n⚠️ 删除/替换操作请谨慎使用"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
        default_config = {"enabled": False}
        return form_config, default_config

    def get_page(self) -> List[dict]:
        """详情页（核心可视化操作界面）"""
        return [
            {
                "component": "div",
                "props": {"class": "plugin-page strm-manager", "style": "padding: 16px;"},
                "content": [
                    # 第一部分：目录选择区（可视化文件选择器）
                    {
                        "component": "VCard",
                        "props": {"variant": "outlined", "class": "mb-4"},
                        "content": [
                            {
                                "component": "VCardTitle",
                                "props": {"title": "📂 目录选择", "class": "text-h6"}
                            },
                            {
                                "component": "VCardText",
                                "content": [
                                    # 当前影视库目录
                                    {
                                        "component": "VFileSelector",
                                        "props": {
                                            "model": "page_src_dir",
                                            "label": "当前影视库目录（必选）",
                                            "type": "directory",
                                            "variant": "outlined",
                                            "class": "mb-3",
                                            "placeholder": "点击选择存放影视文件的目录"
                                        }
                                    },
                                    # 完整STRM库 + 复制输出目录
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
                                                            "model": "page_full_dir",
                                                            "label": "完整STRM库目录（复制/替换用）",
                                                            "type": "directory",
                                                            "variant": "outlined",
                                                            "class": "mb-3",
                                                            "placeholder": "点击选择包含完整STRM的目录"
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
                                                            "model": "page_out_dir",
                                                            "label": "复制输出目录（复制用）",
                                                            "type": "directory",
                                                            "variant": "outlined",
                                                            "class": "mb-3",
                                                            "placeholder": "点击选择STRM复制的目标目录"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },

                    # 第二部分：操作配置区（可视化选择/输入）
                    {
                        "component": "VCard",
                        "props": {"variant": "outlined", "class": "mb-4"},
                        "content": [
                            {
                                "component": "VCardTitle",
                                "props": {"title": "⚙️ 操作配置", "class": "text-h6"}
                            },
                            {
                                "component": "VCardText",
                                "content": [
                                    # 操作类型 + 搜索关键词
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 6},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "page_action",
                                                            "label": "选择操作类型",
                                                            "items": [
                                                                {"title": "🔍 扫描缺失STRM", "value": "scan"},
                                                                {"title": "🗑️ 删除STRM文件", "value": "delete"},
                                                                {"title": "📤 复制STRM文件", "value": "copy"},
                                                                {"title": "🔄 替换STRM文件", "value": "replace"}
                                                            ],
                                                            "variant": "outlined",
                                                            "class": "mb-3",
                                                            "disabled": "page_running"
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
                                                            "model": "page_keyword",
                                                            "label": "影视搜索关键词（可选）",
                                                            "placeholder": "例：星际穿越、漫威",
                                                            "variant": "outlined",
                                                            "class": "mb-3",
                                                            "disabled": "page_running",
                                                            "hint": "仅替换操作生效，为空则处理所有缺失目录"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 模拟运行开关 + 进度条
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "page_dry_run",
                                                            "label": "模拟运行",
                                                            "true-value": True,
                                                            "false-value": False,
                                                            "variant": "outlined",
                                                            "disabled": "page_running",
                                                            "hint": "开启后仅预览操作，不修改文件"
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 8},
                                                "content": [
                                                    {
                                                        "component": "VProgressLinear",
                                                        "props": {
                                                            "modelValue": "page_progress",
                                                            "variant": "determinate",
                                                            "class": "mb-3",
                                                            "color": "primary",
                                                            "height": 8
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 操作按钮组（可视化交互）
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VBtn",
                                                        "props": {
                                                            "color": "primary",
                                                            "variant": "elevated",
                                                            "class": "w-100",
                                                            "disabled": "page_running || !page_src_dir",
                                                            "loading": "page_running"
                                                        },
                                                        "text": "执行操作",
                                                        "click": "call:execute_operation"
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VBtn",
                                                        "props": {
                                                            "color": "secondary",
                                                            "variant": "elevated",
                                                            "class": "w-100",
                                                            "disabled": "page_running"
                                                        },
                                                        "text": "重置配置",
                                                        "click": "call:reset_config"
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VBtn",
                                                        "props": {
                                                            "color": "error",
                                                            "variant": "elevated",
                                                            "class": "w-100",
                                                            "disabled": "page_running"
                                                        },
                                                        "text": "清空日志",
                                                        "click": "call:clear_log"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },

                    # 第三部分：日志展示区（可视化结果反馈）
                    {
                        "component": "VCard",
                        "props": {"variant": "outlined"},
                        "content": [
                            {
                                "component": "VCardTitle",
                                "props": {"title": "📝 操作日志", "class": "text-h6"}
                            },
                            {
                                "component": "VCardText",
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "page_log",
                                            "label": "实时日志",
                                            "multiline": True,
                                            "rows": 10,
                                            "readonly": True,
                                            "variant": "outlined",
                                            "class": "font-mono text-sm"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    # -------------------------- 可视化操作核心方法 --------------------------
    def execute_operation(self, **kwargs):
        """执行操作（可视化入口）"""
        # 基础校验
        if not Path(self._page_src_dir).exists():
            self._append_log(f"❌ 错误：当前影视库目录无效 → {self._page_src_dir}")
            return

        # 不同操作的前置校验
        if self._page_action in ["copy", "replace"] and not Path(self._page_full_dir).exists():
            self._append_log(f"❌ 错误：完整STRM库目录无效 → {self._page_full_dir}")
            return

        if self._page_action == "copy" and not Path(self._page_out_dir).exists():
            self._append_log(f"❌ 错误：复制输出目录无效 → {self._page_out_dir}")
            return

        # 危险操作二次确认（可视化弹窗）
        if self._page_action in ["delete", "replace"]:
            # 模拟弹窗确认（MoviePilot V2支持call:方式触发弹窗，此处简化为日志提示）
            confirm_text = f"⚠️ 确认执行【{self._page_action}】操作？\n- 目录：{self._page_src_dir}\n- 模拟运行：{self._page_dry_run}"
            self._append_log(f"\n{confirm_text}\n✅ 确认执行，开始处理...")

        # 异步执行操作（避免阻塞UI）
        self._page_running = True
        self._page_progress = 0
        self._update_ui()
        
        thread = threading.Thread(target=self._run_operation)
        thread.daemon = True
        thread.start()

    def _run_operation(self):
        """后台执行操作（避免UI卡顿）"""
        try:
            # 1. 扫描目标目录
            self._append_log(f"\n📅 操作开始：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self._append_log(f"🔧 操作类型：{self._page_action} | 模拟运行：{self._page_dry_run}")
            self._append_log(f"📂 目标目录：{self._page_src_dir}")
            
            target_dirs = self._scan_target_dirs()
            total = len(target_dirs)
            if total == 0:
                self._append_log("📌 未找到符合条件的目录，操作结束")
                self._reset_operation_state()
                return
            
            self._append_log(f"🔍 找到 {total} 个符合条件的目录，开始处理...")
            self._update_ui()

            # 2. 执行具体操作
            success = 0
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(self._process_dir, dir_path): dir_path for dir_path in target_dirs}
                
                for idx, future in enumerate(as_completed(futures), 1):
                    dir_path = futures[future]
                    try:
                        future.result()
                        success += 1
                        self._append_log(f"✅ [{idx}/{total}] 处理完成：{dir_path}")
                    except Exception as e:
                        self._append_log(f"❌ [{idx}/{total}] 处理失败：{dir_path} → {str(e)}")
                    
                    # 更新进度（可视化）
                    self._page_progress = int((idx / total) * 100)
                    self._update_ui()

            # 3. 操作完成
            self._append_log(f"\n🎉 操作完成！总计：{total} | 成功：{success} | 失败：{total - success}")
            if self._page_dry_run:
                self._append_log("⚠️ 注意：当前为模拟运行模式，未修改任何文件！")
                
        except Exception as e:
            self._append_log(f"\n💥 操作异常：{str(e)}")
            logger.error(f"STRM操作异常：{e}", exc_info=True)
        finally:
            self._reset_operation_state()

    def _scan_target_dirs(self) -> list:
        """扫描目标目录（可视化结果）"""
        target_dirs = []
        # 扫描缺失STRM的目录
        for root, dirs, files in os.walk(self._page_src_dir):
            # 过滤条件：无子目录 + 包含媒体元文件（nfo/jpg/png） + 无STRM文件
            if not dirs and any(f.lower().endswith((".nfo", ".jpg", ".png")) for f in files):
                if not any(f.lower().endswith(".strm") for f in files):
                    # 搜索关键词过滤
                    if self._page_keyword and self._page_action == "replace":
                        if self._page_keyword.lower() in root.lower():
                            target_dirs.append(root)
                    else:
                        target_dirs.append(root)
        return target_dirs

    def _process_dir(self, dir_path: str):
        """处理单个目录（根据操作类型）"""
        if self._page_action == "scan":
            # 仅扫描，无需修改文件
            pass
        
        elif self._page_action == "delete":
            # 删除STRM文件
            for file in Path(dir_path).glob("*.strm"):
                if not self._page_dry_run:
                    file.unlink(missing_ok=True)
        
        elif self._page_action == "copy":
            # 从完整库复制STRM到输出目录
            rel_path = os.path.relpath(dir_path, self._page_src_dir)
            full_dir = Path(self._page_full_dir) / rel_path
            out_dir = Path(self._page_out_dir) / rel_path
            
            if full_dir.exists():
                if not self._page_dry_run:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    for file in full_dir.glob("*.strm"):
                        shutil.copy2(file, out_dir / file.name)
        
        elif self._page_action == "replace":
            # 替换STRM文件（删除旧的 + 复制新的）
            # 删除旧STRM
            for file in Path(dir_path).glob("*.strm"):
                if not self._page_dry_run:
                    file.unlink(missing_ok=True)
            # 复制新STRM
            rel_path = os.path.relpath(dir_path, self._page_src_dir)
            full_dir = Path(self._page_full_dir) / rel_path
            if full_dir.exists():
                for file in full_dir.glob("*.strm"):
                    if not self._page_dry_run:
                        shutil.copy2(file, dir_path / file.name)

    # -------------------------- 可视化辅助方法 --------------------------
    def _append_log(self, content: str):
        """追加日志（可视化）"""
        self._page_log += f"\n{content}"
        # 限制日志长度（避免卡顿）
        if len(self._page_log) > 10000:
            self._page_log = self._page_log[-10000:]
        self._update_ui()

    def _update_ui(self):
        """更新UI状态（核心：同步可视化参数）"""
        self.update_config({
            "page_src_dir": self._page_src_dir,
            "page_full_dir": self._page_full_dir,
            "page_out_dir": self._page_out_dir,
            "page_keyword": self._page_keyword,
            "page_action": self._page_action,
            "page_progress": self._page_progress,
            "page_log": self._page_log,
            "page_dry_run": self._page_dry_run,
            "page_running": self._page_running
        })

    def _reset_operation_state(self):
        """重置操作状态（可视化）"""
        self._page_running = False
        self._page_progress = 0
        self._update_ui()

    def reset_config(self, **kwargs):
        """重置配置（可视化）"""
        self._page_src_dir = ""
        self._page_full_dir = ""
        self._page_out_dir = ""
        self._page_keyword = ""
        self._page_action = "scan"
        self._page_dry_run = True
        self._page_progress = 0
        self._page_log = "📌 配置已重置\n请重新选择目录和操作类型\n"
        self._update_ui()

    def clear_log(self, **kwargs):
        """清空日志（可视化）"""
        self._page_log = "📌 日志已清空\n"
        self._update_ui()

    def stop_service(self):
        """停止插件（MoviePilot必需）"""
        logger.info("STRM文件管理器已停止")


# 插件注册（MoviePilot V2必需，否则无法加载）
def get_plugin():
    return STRMManager()
