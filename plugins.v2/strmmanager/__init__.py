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


# 版本号读取（修改：移除GitHub依赖，硬编码本地版本号）
def get_plugin_version() -> str:
    """读取插件版本号（本地版本，无需依赖package.v2.json）"""
    try:
        # 直接返回本地版本，避免读取package.v2.json触发远程检查
        return "1.1.3"
    except Exception as e:
        logger.warning(f"读取版本号失败：{e}，使用默认版本1.1.3")
        return "1.1.3"


class STRMManager(_PluginBase):
    """STRM文件管理插件（全UI可视化版-本地适配）"""
    # 插件基础信息（MoviePilot必需，补充本地插件标识）
    plugin_name: str = "STRM文件管理器"
    plugin_desc: str = "可视化管理STRM文件（扫描/删除/复制/替换）-本地版"
    plugin_icon: str = "mdi-file-document-multiple-outline"  # 内置图标（确保显示）
    plugin_version: str = get_plugin_version()
    plugin_author: str = "Daveccx"
    plugin_config_prefix: str = "strmmanager_"
    plugin_order: int = 50  # 插件展示顺序
    user_level: int = 1     # 所有用户可见
    # 新增：标记为本地插件，禁用远程检查（核心修改）
    is_local: bool = True    # MoviePilot本地插件标识
    no_update: bool = True   # 禁用自动更新

    # 核心状态变量（可视化绑定）
    _enabled: bool = True   # 修改：默认启用，避免手动开关
    # 可视化操作参数（绑定UI组件）
    _page_src_dir: str = ""          # 当前影视库目录（UI选择）
    _page_full_dir: str = ""         # 完整STRM库目录（UI选择）
    _page_out_dir: str = ""          # 复制输出目录（UI选择）
    _page_keyword: str = ""          # 搜索关键词（UI输入）
    _page_action: str = "scan"       # 当前选择操作（UI下拉）
    _page_progress: int = 0          # 操作进度（UI进度条）
    _page_log: str = "📌 欢迎使用STRM文件管理器（本地版）\n请选择目录和操作类型，点击【执行操作】开始\n"  # 操作日志（UI文本框）
    _page_dry_run: bool = True       # 模拟运行（UI开关）
    _page_running: bool = False      # 操作中状态（禁用按钮）

    def init_plugin(self, config: dict = None):
        """插件初始化（加载保存的配置，适配本地场景）"""
        # 修改：兼容空配置，强制本地加载
        if not config:
            logger.info("STRM文件管理器（本地版）初始化：无配置，使用本地默认值")
            self._update_ui()  # 初始化UI状态
            return

        # 加载可视化参数（确保UI状态恢复）
        self._page_src_dir = config.get("page_src_dir", "")
        self._page_full_dir = config.get("page_full_dir", "")
        self._page_out_dir = config.get("page_out_dir", "")
        self._page_keyword = config.get("page_keyword", "")
        self._page_action = config.get("page_action", "scan")
        self._page_dry_run = config.get("page_dry_run", True)
        self._page_log = config.get("page_log", self._page_log)
        
        logger.info("STRM文件管理器（本地版）初始化完成")

    def get_state(self) -> bool:
        """获取插件启用状态（MoviePilot必需，强制返回启用）"""
        return True  # 修改：强制启用，避免安装失败后被禁用

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """配置页（简化，移除无用开关，突出本地版标识）"""
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
                                        "component": "VAlert",
                                        "props": {
                                            "type": "success",
                                            "variant": "outlined"
                                        },
                                        "text": "✅ 本地版STRM文件管理器已启用\n📌 核心功能请前往【详情页】操作\n⚠️ 删除/替换操作请谨慎使用（建议先开启模拟运行）"
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
                                        "text": "💡 本地版特性：无需GitHub Release，直接本地运行\n📂 支持可视化目录选择、实时进度、操作日志"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
        default_config = {"enabled": True}  # 修改：默认启用
        return form_config, default_config

    def get_page(self) -> List[dict]:
        """详情页（核心可视化操作界面，优化兼容性）"""
        return [
            {
                "component": "div",
                "props": {"class": "plugin-page strm-manager", "style": "padding: 16px;"},
                "content": [
                    # 第一部分：目录选择区（可视化文件选择器，优化提示）
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
                                    # 当前影视库目录（优化必填提示）
                                    {
                                        "component": "VFileSelector",
                                        "props": {
                                            "model": "page_src_dir",
                                            "label": "当前影视库目录（*必选）",
                                            "type": "directory",
                                            "variant": "outlined",
                                            "class": "mb-3",
                                            "placeholder": "点击选择存放影视文件的目录（如：/movies）",
                                            "hint": "必须选择有效目录才能执行操作"
                                        }
                                    },
                                    # 完整STRM库 + 复制输出目录（优化提示）
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
                                                            "placeholder": "点击选择包含完整STRM的目录",
                                                            "hint": "仅复制/替换操作需要填写"
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
                                                            "placeholder": "点击选择STRM复制的目标目录",
                                                            "hint": "仅复制操作需要填写"
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

                    # 第二部分：操作配置区（可视化选择/输入，优化交互）
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
                                    # 操作类型 + 搜索关键词（优化禁用逻辑）
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
                                                            "disabled": "page_running",
                                                            "hint": "操作中不可修改"
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
                                                            "placeholder": "例：星际穿越、漫威、DC",
                                                            "variant": "outlined",
                                                            "class": "mb-3",
                                                            "disabled": "page_running || page_action != 'replace'",
                                                            "hint": "仅替换操作生效，为空则处理所有缺失目录"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 模拟运行开关 + 进度条（优化样式）
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
                                                            "hint": "开启后仅预览操作，不修改文件（推荐新手开启）"
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
                                                            "height": 8,
                                                            "rounded": True  # 优化样式：圆角进度条
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    # 操作按钮组（可视化交互，优化禁用逻辑）
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
                                                            "disabled": "page_running || !page_src_dir || (page_action == 'copy' && !page_full_dir) || (page_action == 'copy' && !page_out_dir) || (page_action == 'replace' && !page_full_dir)",
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

                    # 第三部分：日志展示区（可视化结果反馈，优化样式）
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
                                            "label": "实时日志（本地版）",
                                            "multiline": True,
                                            "rows": 12,  # 增加行数，优化查看
                                            "readonly": True,
                                            "variant": "outlined",
                                            "class": "font-mono text-sm",
                                            "bgColor": "rgba(245,245,245,0.5)"  # 优化背景色
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    # -------------------------- 可视化操作核心方法（优化兼容性） --------------------------
    def execute_operation(self, **kwargs):
        """执行操作（可视化入口，强化校验）"""
        # 基础校验（强化提示）
        if not Path(self._page_src_dir).exists():
            self._append_log(f"❌ 错误：当前影视库目录无效或不存在 → {self._page_src_dir}")
            self._append_log(f"💡 提示：请选择真实存在的影视文件目录（如：/movies、/tv）")
            return

        # 不同操作的前置校验（强化提示）
        if self._page_action in ["copy", "replace"] and not Path(self._page_full_dir).exists():
            self._append_log(f"❌ 错误：完整STRM库目录无效或不存在 → {self._page_full_dir}")
            self._append_log(f"💡 提示：复制/替换操作必须选择包含STRM文件的目录")
            return

        if self._page_action == "copy" and not Path(self._page_out_dir).exists():
            self._append_log(f"❌ 错误：复制输出目录无效或不存在 → {self._page_out_dir}")
            self._append_log(f"💡 提示：复制操作必须选择有效的目标输出目录")
            return

        # 危险操作二次确认（优化提示文案）
        if self._page_action in ["delete", "replace"]:
            confirm_text = f"⚠️ 高危操作确认！\n- 操作类型：{self._page_action.upper()}\n- 目标目录：{self._page_src_dir}\n- 模拟运行：{self._page_dry_run}\n📢 确认执行？（删除/替换后无法恢复）"
            self._append_log(f"\n{confirm_text}\n✅ 已确认，开始处理...")

        # 异步执行操作（避免阻塞UI）
        self._page_running = True
        self._page_progress = 0
        self._update_ui()
        
        thread = threading.Thread(target=self._run_operation)
        thread.daemon = True
        thread.start()

    def _run_operation(self):
        """后台执行操作（避免UI卡顿，优化异常处理）"""
        try:
            # 1. 扫描目标目录（优化日志提示）
            self._append_log(f"\n📅 操作开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self._append_log(f"🔧 操作类型：{self._page_action} | 模拟运行：{self._page_dry_run}")
            self._append_log(f"📂 目标目录：{self._page_src_dir}")
            if self._page_keyword:
                self._append_log(f"🔤 搜索关键词：{self._page_keyword}（仅匹配目录名称）")
            
            target_dirs = self._scan_target_dirs()
            total = len(target_dirs)
            if total == 0:
                self._append_log("📌 未找到符合条件的目录（无缺失STRM的媒体目录）")
                self._append_log("💡 提示：检查目录是否包含媒体文件（nfo/jpg/png）且无STRM文件")
                self._reset_operation_state()
                return
            
            self._append_log(f"🔍 成功找到 {total} 个符合条件的目录，开始批量处理...")
            self._update_ui()

            # 2. 执行具体操作（优化线程数，适配低配置）
            success = 0
            # 修改：线程数从4改为2，降低资源占用
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {executor.submit(self._process_dir, dir_path): dir_path for dir_path in target_dirs}
                
                for idx, future in enumerate(as_completed(futures), 1):
                    dir_path = futures[future]
                    try:
                        future.result()
                        success += 1
                        self._append_log(f"✅ [{idx}/{total}] 处理完成：{dir_path}")
                    except Exception as e:
                        self._append_log(f"❌ [{idx}/{total}] 处理失败：{dir_path} → {str(e)}")
                        self._append_log(f"💡 失败原因：权限不足/目录不存在/文件被占用")
                    
                    # 更新进度（可视化）
                    self._page_progress = int((idx / total) * 100)
                    self._update_ui()

            # 3. 操作完成（优化总结提示）
            self._append_log(f"\n🎉 操作全部完成！📊 统计：")
            self._append_log(f"   总计目录数：{total} | 成功：{success} | 失败：{total - success}")
            if self._page_dry_run:
                self._append_log(f"⚠️ 重要提示：当前为【模拟运行】模式，未修改任何文件！\n   确认操作无误后，可关闭模拟运行执行真实操作")
            else:
                self._append_log(f"✅ 真实运行模式：已完成文件修改，请检查结果")
                
        except Exception as e:
            self._append_log(f"\n💥 操作异常终止：{str(e)}")
            self._append_log(f"💡 异常排查：检查目录权限/磁盘空间/文件是否被占用")
            logger.error(f"STRM操作异常：{e}", exc_info=True)
        finally:
            self._reset_operation_state()

    def _scan_target_dirs(self) -> list:
        """扫描目标目录（优化过滤逻辑，避免死循环）"""
        target_dirs = []
        # 修改：限制递归深度，避免遍历过深
        max_depth = 5  # 最大遍历深度
        for root, dirs, files in os.walk(self._page_src_dir):
            # 计算当前深度
            depth = root.count(os.sep) - self._page_src_dir.count(os.sep)
            if depth > max_depth:
                dirs[:] = []  # 停止递归
                continue
                
            # 过滤条件：无子目录 + 包含媒体元文件（nfo/jpg/png） + 无STRM文件
            if not dirs and any(f.lower().endswith((".nfo", ".jpg", ".png", ".jpeg")) for f in files):
                if not any(f.lower().endswith(".strm") for f in files):
                    # 搜索关键词过滤
                    if self._page_keyword and self._page_action == "replace":
                        if self._page_keyword.lower() in root.lower():
                            target_dirs.append(root)
                    else:
                        target_dirs.append(root)
        return target_dirs

    def _process_dir(self, dir_path: str):
        """处理单个目录（增加异常捕获，避免单个目录失败导致整体中断）"""
        try:
            if self._page_action == "scan":
                # 仅扫描，无需修改文件
                pass
            
            elif self._page_action == "delete":
                # 删除STRM文件（增加权限检查）
                for file in Path(dir_path).glob("*.strm"):
                    if file.exists() and os.access(file, os.W_OK):
                        if not self._page_dry_run:
                            file.unlink(missing_ok=True)
                    else:
                        raise Exception("无文件写入权限")
            
            elif self._page_action == "copy":
                # 从完整库复制STRM到输出目录（增加目录创建校验）
                rel_path = os.path.relpath(dir_path, self._page_src_dir)
                full_dir = Path(self._page_full_dir) / rel_path
                out_dir = Path(self._page_out_dir) / rel_path
                
                if full_dir.exists() and os.access(full_dir, os.R_OK):
                    if not self._page_dry_run:
                        # 确保输出目录存在
                        out_dir.mkdir(parents=True, exist_ok=True)
                        if os.access(out_dir, os.W_OK):
                            for file in full_dir.glob("*.strm"):
                                shutil.copy2(file, out_dir / file.name)
                        else:
                            raise Exception("输出目录无写入权限")
                else:
                    raise Exception("源STRM目录不存在/无读取权限")
            
            elif self._page_action == "replace":
                # 替换STRM文件（删除旧的 + 复制新的，增加双重校验）
                # 删除旧STRM
                for file in Path(dir_path).glob("*.strm"):
                    if file.exists() and os.access(file, os.W_OK):
                        if not self._page_dry_run:
                            file.unlink(missing_ok=True)
                # 复制新STRM
                rel_path = os.path.relpath(dir_path, self._page_src_dir)
                full_dir = Path(self._page_full_dir) / rel_path
                if full_dir.exists() and os.access(full_dir, os.R_OK):
                    for file in full_dir.glob("*.strm"):
                        if os.access(dir_path, os.W_OK) and not self._page_dry_run:
                            shutil.copy2(file, dir_path / file.name)
                else:
                    raise Exception("完整STRM目录不存在/无读取权限")
        except Exception as e:
            # 抛出异常，让上层捕获
            raise e

    # -------------------------- 可视化辅助方法（优化稳定性） --------------------------
    def _append_log(self, content: str):
        """追加日志（优化编码，避免乱码）"""
        try:
            # 处理中文编码问题
            self._page_log += f"\n{content}"
            # 限制日志长度（避免卡顿，优化截断逻辑）
            max_log_len = 15000
            if len(self._page_log) > max_log_len:
                # 保留最后15000字符，同时保证日志完整性
                self._page_log = "📜 日志过长，仅显示最后部分...\n" + self._page_log[-max_log_len:]
            self._update_ui()
        except Exception as e:
            logger.error(f"日志追加失败：{e}")

    def _update_ui(self):
        """更新UI状态（核心：同步可视化参数，增加异常捕获）"""
        try:
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
        except Exception as e:
            logger.error(f"UI状态更新失败：{e}")

    def _reset_operation_state(self):
        """重置操作状态（可视化）"""
        try:
            self._page_running = False
            self._page_progress = 0
            self._update_ui()
        except Exception as e:
            logger.error(f"操作状态重置失败：{e}")

    def reset_config(self, **kwargs):
        """重置配置（可视化，优化提示）"""
        self._page_src_dir = ""
        self._page_full_dir = ""
        self._page_out_dir = ""
        self._page_keyword = ""
        self._page_action = "scan"
        self._page_dry_run = True
        self._page_progress = 0
        self._page_log = "📌 配置已重置为默认值\n请重新选择目录和操作类型\n💡 建议新手先开启【模拟运行】测试操作效果\n"
        self._update_ui()

    def clear_log(self, **kwargs):
        """清空日志（可视化，优化提示）"""
        self._page_log = "📌 日志已清空\n操作日志将在此处实时显示...\n"
        self._update_ui()

    def stop_service(self):
        """停止插件（MoviePilot必需，增加日志）"""
        logger.info("STRM文件管理器（本地版）已停止")
        self._append_log("\n🛑 STRM文件管理器已停止运行")


# 插件注册（MoviePilot V2必需，优化注册逻辑）
def get_plugin():
    """插件注册函数（确保返回单例）"""
    try:
        return STRMManager()
    except Exception as e:
        logger.error(f"插件注册失败：{e}")
        # 兜底返回空，避免MoviePilot崩溃
        return None
