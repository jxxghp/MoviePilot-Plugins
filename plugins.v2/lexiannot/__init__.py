import os
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, Literal

import pymediainfo
from langdetect import detect
from langchain_community.callbacks import get_openai_callback
from pysubs2 import SSAFile, SSAEvent, SSAStyle, Color, Alignment

from app.core.config import settings
from app.helper.directory import DirectoryHelper
from app.log import logger
from app.plugins import _PluginBase
from app.core.cache import cached
from app.core.event import eventmanager, Event
from app.schemas import Response
from app.schemas.types import NotificationType, MediaType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.schemas import TransferInfo, Context
from app.schemas.types import EventType
from app.core.context import MediaInfo
from app.chain.media import MediaChain

from .agenttool import VocabularyAnnotatingTool
from .lexicon import Lexicon
from .schemas import (
    IDGenerator,
    TaskStatus,
    Task,
    TasksApiParams,
    ProcessResult,
    SegmentList,
    TaskParams, SegmentStatistics,
)
from .spacyworker import SpacyWorker
from .subtitle import SubtitleProcessor, style_text
from .pipeline import (
    extract_advanced_words,
    llm_process_chain,
    initialize_llm,
    UNIVERSAL_POS_MAP,
)


class LexiAnnot(_PluginBase):
    # 插件名称
    plugin_name = "美剧生词标注"
    # 插件描述
    plugin_desc = "根据CEFR等级，为英语影视剧标注高级词汇。"
    # 插件图标
    plugin_icon = "LexiAnnot.png"
    # 插件版本
    plugin_version = "1.2.0"
    # 插件作者
    plugin_author = "wumode"
    # 作者主页
    author_url = "https://github.com/wumode"
    # 插件配置项ID前缀
    plugin_config_prefix = "lexiannot_"
    # 加载顺序
    plugin_order = 50
    # 可使用的用户级别
    auth_level = 1

    _enabled: bool = False
    _annot_level = ""
    _send_notify = False
    _onlyonce = False
    _show_vocabulary_detail = False
    _show_phonetics = False
    _sentence_translation = False
    _in_place = False
    _enable_gemini = False
    _gemini_model = ""
    _gemini_apikey: str | None = None
    _llm_provider = "google"
    _llm_base_url = ""

    _context_window: int = 0
    _max_retries: int = 0
    _ffmpeg_path: str = "ffmpeg"
    _english_only = False
    _when_file_trans = False
    _model_temperature = ""
    _custom_files = ""
    _accent_color = ""
    _font_scaling = ""
    _opacity = ""
    _exam_tags: List[str] = []
    _spacy_model: str = ""
    _delete_data: bool = False
    _libraries: List[str] = []
    _use_mp_agent: bool = False
    _use_proxy: bool = False

    # protected variables
    _lexicon_repo = "https://raw.githubusercontent.com/wumode/LexiAnnot/"
    _worker_thread = None
    _task_queue: queue.Queue[Task] = queue.Queue()
    _shutdown_event = None
    _venv_python = None
    _query_gemini_script = ""
    _gemini_available = False
    _accent_color_rgb = None
    _color_alpha = 0
    _loaded = False
    _config_updating_lock: threading.Lock = threading.Lock()
    _tasks_lock: threading.RLock = threading.RLock()
    _tasks: Dict[str, Task] = {}

    def init_plugin(self, config=None):
        self.stop_service()
        if config:
            self._enabled = bool(config.get("enabled"))
            self._annot_level = config.get("annot_level") or "C1"
            self._send_notify = config.get("send_notify")
            self._onlyonce = config.get("onlyonce")
            self._show_vocabulary_detail = config.get("show_vocabulary_detail")
            self._sentence_translation = config.get("sentence_translation")
            self._in_place = config.get("in_place")
            self._enable_gemini = config.get("enable_gemini")
            self._gemini_model = config.get("gemini_model") or "gemini-2.5-flash"
            self._gemini_apikey = config.get("gemini_apikey") or ""
            self._context_window = int(config.get("context_window") or 10)
            self._context_window = max(5, min(self._context_window, 50))
            self._max_retries = int(config.get("max_retries") or 3)
            self._ffmpeg_path = config.get("ffmpeg_path") or "ffmpeg"
            self._english_only = config.get("english_only")
            self._when_file_trans = config.get("when_file_trans")
            self._model_temperature = config.get("model_temperature") or "0.3"
            self._show_phonetics = config.get("show_phonetics")
            self._custom_files = config.get("custom_files") or ""
            self._accent_color = config.get("accent_color")
            self._font_scaling = config.get("font_scaling") or "1"
            self._opacity = config.get("opacity") or "0"
            self._spacy_model = config.get("spacy_model") or "en_core_web_sm"
            self._exam_tags = config.get("exam_tags") or []
            self._delete_data = config.get("delete_data") or False
            self._libraries = config.get("libraries") or []
            self._llm_base_url = config.get("llm_base_url") or ""
            self._llm_provider = config.get("llm_provider") or "google"
            self._use_mp_agent = config.get("use_mp_agent") or False
            self._use_proxy = config.get("use_proxy") or False

            libraries = [
                library.name for library in DirectoryHelper().get_library_dirs()
            ]
            self._libraries = [
                library for library in self._libraries if library in libraries
            ]
            self._accent_color_rgb = LexiAnnot.hex_to_rgb(self._accent_color) or (255, 255, 0,)
            self._color_alpha = int(self._opacity) if self._opacity and len(self._opacity) else 0
        if self._delete_data:
            # 删除不再保存在数据库的数据
            self.del_data("cefr_lexicon")
            self.del_data("coca2k_lexicon")
            self.del_data("swear_words")
            self.del_data("lexicon_version")
            self.delete_data()
            self._delete_data = False
            self._loaded = False

        tasks = self.load_tasks()
        with self._tasks_lock:
            self._tasks = tasks
        if self._enabled:
            # 清空任务队列，避免残留对象
            while not self._task_queue.empty():
                self._task_queue.get()
                self._task_queue.task_done()
            # 从字典中恢复队列
            with self._tasks_lock:
                for task_id, task in self._tasks.items():
                    if task.status == TaskStatus.PENDING:
                        self._task_queue.put(task)

            self._shutdown_event = threading.Event()
            self._worker_thread = threading.Thread(
                target=self.__process_tasks, daemon=True
            )
            self._worker_thread.start()

            if self._onlyonce:
                for file_path in self._custom_files.split("\n"):
                    file_path = file_path.strip()
                    if not file_path or file_path.startswith("#"):
                        continue
                    self.add_media_file(file_path)
                self._onlyonce = False
        self.__update_config()

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        library_options = [
            {"title": library.name, "value": library.name}
            for library in DirectoryHelper().get_library_dirs()
        ]
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "send_notify",
                                            "label": "发送通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "手动运行一次",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_data",
                                            "label": "插件数据清理",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VTabs",
                        "props": {
                            "model": "_tabs",
                            "style": {"margin-top": "8px", "margin-bottom": "16px"},
                            "stacked": True,
                            "fixed-tabs": True,
                        },
                        "content": [
                            {
                                "component": "VTab",
                                "props": {"value": "base_tab"},
                                "text": "基本设置",
                            },
                            {
                                "component": "VTab",
                                "props": {"value": "subtitle_tab"},
                                "text": "字幕设置",
                            },
                            {
                                "component": "VTab",
                                "props": {"value": "gemini_tab"},
                                "text": "LLM 设置",
                            },
                        ],
                    },
                    {
                        "component": "VWindow",
                        "props": {"model": "_tabs"},
                        "content": [
                            {
                                "component": "VWindowItem",
                                "props": {"value": "base_tab"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "props": {"style": {"margin-top": "0px"}},
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "when_file_trans",
                                                            "label": "监控入库",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "spacy_model",
                                                            "label": "spaCy模型",
                                                            "hint": "用于分词和词性标注，推荐使用「md」",
                                                            "items": [
                                                                {
                                                                    "title": "sm (~12 MB)",
                                                                    "value": "en_core_web_sm",
                                                                },
                                                                {
                                                                    "title": "md (~30 MB)",
                                                                    "value": "en_core_web_md",
                                                                },
                                                                {
                                                                    "title": "lg (700+ MB)",
                                                                    "value": "en_core_web_lg",
                                                                },
                                                                {
                                                                    "title": "Transformer (400+ MB)",
                                                                    "value": "en_core_web_trf",
                                                                },
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "annot_level",
                                                            "label": "标注词汇的最低CEFR等级",
                                                            "items": [
                                                                {
                                                                    "title": "B1",
                                                                    "value": "B1",
                                                                },
                                                                {
                                                                    "title": "B2",
                                                                    "value": "B2",
                                                                },
                                                                {
                                                                    "title": "C1",
                                                                    "value": "C1",
                                                                },
                                                                {
                                                                    "title": "C2",
                                                                    "value": "C2",
                                                                },
                                                                {
                                                                    "title": "C2+",
                                                                    "value": "C2+",
                                                                },
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "english_only",
                                                            "label": "仅英语影视剧",
                                                            "hint": "检查入库影视剧原语言",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 8},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "exam_tags",
                                                            "label": "考试词汇标签",
                                                            "chips": True,
                                                            "multiple": True,
                                                            "items": [
                                                                {
                                                                    "title": "四级",
                                                                    "value": "CET-4",
                                                                },
                                                                {
                                                                    "title": "六级",
                                                                    "value": "CET-6",
                                                                },
                                                                {
                                                                    "title": "考研",
                                                                    "value": "NPEE",
                                                                },
                                                                {
                                                                    "title": "雅思",
                                                                    "value": "IELTS",
                                                                },
                                                                {
                                                                    "title": "托福",
                                                                    "value": "TOEFL",
                                                                },
                                                                {
                                                                    "title": "专四",
                                                                    "value": "TEM-4",
                                                                },
                                                                {
                                                                    "title": "专八",
                                                                    "value": "TEM-8",
                                                                },
                                                                {
                                                                    "title": "GRE",
                                                                    "value": "GRE",
                                                                },
                                                                {
                                                                    "title": "PET",
                                                                    "value": "PET",
                                                                },
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "ffmpeg_path",
                                                            "label": "FFmpeg 路径",
                                                            "placeholder": "ffmpeg",
                                                        },
                                                    }
                                                ],
                                            }
                                        ],
                                    },
                                ],
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "subtitle_tab"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "props": {"style": {"margin-top": "0px"}},
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "font_scaling",
                                                            "label": "字体缩放",
                                                            "items": [
                                                                {
                                                                    "title": "50%",
                                                                    "value": "0.5",
                                                                },
                                                                {
                                                                    "title": "75%",
                                                                    "value": "0.75",
                                                                },
                                                                {
                                                                    "title": "100%",
                                                                    "value": "1",
                                                                },
                                                                {
                                                                    "title": "125%",
                                                                    "value": "1.25",
                                                                },
                                                                {
                                                                    "title": "150%",
                                                                    "value": "1.5",
                                                                },
                                                                {
                                                                    "title": "200%",
                                                                    "value": "2",
                                                                },
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "accent_color",
                                                            "label": "强调色",
                                                            "placeholder": "#FFFF00",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "opacity",
                                                            "label": "透明度",
                                                            "items": [
                                                                {
                                                                    "title": "0",
                                                                    "value": "0",
                                                                },
                                                                {
                                                                    "title": "25%",
                                                                    "value": "63",
                                                                },
                                                                {
                                                                    "title": "50%",
                                                                    "value": "127",
                                                                },
                                                                {
                                                                    "title": "75%",
                                                                    "value": "191",
                                                                },
                                                                {
                                                                    "title": "100%",
                                                                    "value": "255",
                                                                },
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    },
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
                                                            "model": "show_phonetics",
                                                            "label": "标注音标",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "in_place",
                                                            "label": "在原字幕插入注释",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "show_vocabulary_detail",
                                                            "label": "显示完整释义",
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "gemini_tab"},
                                "content": [
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 3,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "enable_gemini",
                                                            "label": "启用 LLM",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 3,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "use_mp_agent",
                                                            "label": "使用系统 Agent 配置",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 3,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "use_proxy",
                                                            "label": "使用系统代理",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 3},
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "sentence_translation",
                                                            "label": "整句翻译",
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "llm_provider",
                                                            "label": "提供商",
                                                            "disabled": "use_mp_agent",
                                                            "items": [
                                                                {
                                                                    "title": "Google",
                                                                    "value": "google",
                                                                },
                                                                {
                                                                    "title": "OpenAI",
                                                                    "value": "openai",
                                                                },
                                                                {
                                                                    "title": "DeepSeek",
                                                                    "value": "deepseek",
                                                                },
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "llm_base_url",
                                                            "disabled": "use_mp_agent",
                                                            "placeholder": "https://api.deepseek.com",
                                                            "label": "基础 URL",
                                                            "hint": "参考 MoviePilot Agent 配置",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VCombobox",
                                                        "props": {
                                                            "model": "gemini_model",
                                                            "disabled": "use_mp_agent",
                                                            "label": "模型名称",
                                                            "items": [
                                                                "gemini-2.5-flash",
                                                                "gemini-2.5-flash-lite",
                                                                "gemini-2.5-pro",
                                                                "gemini-2.0-flash",
                                                                "gemini-2.0-flash-lite",
                                                                "deepseek-ai/DeepSeek-V3.2",
                                                                "deepseek-ai/DeepSeek-R1"
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 6,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "gemini_apikey",
                                                            "label": "API-KEY",
                                                            "disabled": "use_mp_agent",
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                    {
                                        "component": "VRow",
                                        "content": [
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 4,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "context_window",
                                                            "label": "上下文窗口大小",
                                                            "placeholder": "10",
                                                            "type": "number",
                                                            "max": 50,
                                                            "min": 1,
                                                            "hint": "向大模型发送的对话数量",
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VSelect",
                                                        "props": {
                                                            "model": "model_temperature",
                                                            "label": "模型温度",
                                                            "items": [
                                                                {"title": "0", "value": "0"},
                                                                {"title": "0.1", "value": "0.1"},
                                                                {"title": "0.2", "value": "0.2"},
                                                                {"title": "0.3", "value": "0.3"},
                                                                {"title": "0.4", "value": "0.4"},
                                                                {"title": "0.5", "value": "0.5"},
                                                            ],
                                                        },
                                                    }
                                                ],
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 4,
                                                },
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "max_retries",
                                                            "label": "请求重试次数",
                                                            "placeholder": "3",
                                                            "type": "number",
                                                            "min": 1,
                                                            "hint": "请求失败重试次数",
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "props": {"style": {"margin-top": "0px"}},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "chips": True,
                                            "multiple": True,
                                            "model": "libraries",
                                            "label": "监控入库",
                                            "items": library_options,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "props": {"style": {"margin-top": "0px"}},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "custom_files",
                                            "label": "手动处理视频路径",
                                            "rows": 3,
                                            "placeholder": "# 每行一个文件",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "success",
                                            "variant": "tonal",
                                        },
                                        "content": [
                                            {"component": "span", "text": "配置说明："},
                                            {
                                                "component": "a",
                                                "props": {
                                                    "href": "https://github.com/jxxghp/MoviePilot-Plugins/tree/main/plugins.v2/lexiannot/README.md",
                                                    "target": "_blank",
                                                },
                                                "content": [
                                                    {"component": "u", "text": "README"}
                                                ],
                                            },
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "annot_level": "C1",
            "send_notify": False,
            "onlyonce": False,
            "show_vocabulary_detail": False,
            "show_phonetics": False,
            "sentence_translation": False,
            "in_place": False,
            "enable_gemini": False,
            "gemini_model": "gemini-2.0-flash",
            "gemini_apikey": "",
            "context_window": 10,
            "max_retries": 3,
            "request_interval": 3,
            "ffmpeg_path": "",
            "english_only": True,
            "when_file_trans": True,
            "model_temperature": "0.1",
            "custom_files": "",
            "accent_color": "",
            "font_scaling": "1",
            "opacity": "0",
            "spacy_model": "en_core_web_sm",
            "exam_tags": [],
            "delete_data": False,
            "libraries": [],
            "llm_provider": "google",
            "llm_base_url": "",
            "use_mp_agent": False,
            "use_proxy": False,
        }

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/tasks",
                "endpoint": self.task_interface,
                "methods": ["POST"],
                "summary": "任务操作",
                "description": "任务操作",
            }
        ]

    def get_page(self) -> List[dict]:
        headers = [
            {"title": "添加时间", "key": "add_time", "sortable": True},
            {"title": "视频文件", "key": "video_path", "sortable": True},
            {"title": "消耗 Tokens", "key": "tokens_used", "sortable": True},
            {"title": "完成时间", "key": "complete_time", "sortable": True},
            {"title": "任务状态", "key": "status", "sortable": True},
        ]
        items = []
        with self._tasks_lock:
            sorted_tasks = sorted(
                self._tasks.items(), key=lambda x: x[1].add_time, reverse=True
            )

        status_map = {
            TaskStatus.PENDING: "等待中",
            TaskStatus.RUNNING: "处理中",
            TaskStatus.COMPLETED: "已完成",
            TaskStatus.IGNORED: "已忽略",
            TaskStatus.FAILED: "失败",
            TaskStatus.CANCELED: "已取消",
        }

        for task_id, task in sorted_tasks:
            status_text = status_map.get(task.status, task.status)
            item = {
                "task_id": task_id,
                "status": status_text,
                "video_path": task.video_path,
                "add_time": task.add_time if task.add_time else "-",
                "tokens_used": task.tokens_used,
                "complete_time": task.complete_time if task.complete_time else "-",
            }
            items.append(item)
        return [
            {
                "component": "div",
                "props": {"class": "d-flex align-center"},
                "content": [
                    {
                        "component": "h2",
                        "props": {"class": "page-title m-0"},
                        "text": "任务记录",
                    },
                    {"component": "VSpacer"},
                    {
                        "component": "VBtn",
                        "props": {
                            "prepend-icon": "mdi-delete-circle",
                            "variant": "tonal",
                        },
                        "text": "清空任务记录",
                        "events": {
                            "click": {
                                "api": f"plugin/{self.__class__.__name__}/tasks?apikey={settings.API_TOKEN}",
                                "method": "post",
                                "params": {
                                    "operation": "DELETE",
                                    "task_id": None,
                                },
                            }
                        },
                    },
                ],
            },
            {
                "component": "VRow",
                "props": {
                    "style": {
                        "overflow": "hidden",
                    }
                },
                "content": [
                    {
                        "component": "VCol",
                        "props": {
                            "cols": 12,
                        },
                        "content": [
                            {
                                "component": "VDataTableVirtual",
                                "props": {
                                    "class": "text-sm",
                                    "headers": headers,
                                    "items": items,
                                    "height": "30rem",
                                    "density": "compact",
                                    "fixed-header": True,
                                    "hide-no-data": True,
                                    "hover": True,
                                },
                            }
                        ],
                    }
                ],
            },
        ]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_state(self) -> bool:
        """
        获取插件状态，如果插件正在运行， 则返回True
        """
        return self._enabled

    def get_agent_tools(self) -> List[type]:
        """
        获取插件智能体工具
        返回工具类列表，每个工具类必须继承自 MoviePilotTool
        """
        return [VocabularyAnnotatingTool]

    def stop_service(self):
        """
        退出插件
        """
        try:
            self.shutdown()
        except Exception as e:
            logger.error(f"退出插件失败：{e}")

    def shutdown(self):
        """
        关闭插件
        """
        if self._worker_thread and self._worker_thread.is_alive():
            logger.debug("🔻 Stopping existing worker thread...")
            self._shutdown_event.set()
            self._worker_thread.join()
            logger.debug("✅ Existing worker thread stopped.")
            self._worker_thread = None
        else:
            logger.debug("ℹ️ No running worker thread to stop.")

    def delete_data(self):
        # 删除词典
        data_path = self.get_data_path()
        lexicon_path = data_path / "lexicon.json"
        try:
            os.remove(lexicon_path)
            logger.info(f"词典 {lexicon_path} 已删除")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"词典 {lexicon_path} 删除失败: {e}")
        self._load_lexicon_from_local.cache_clear()

        # 删除虚拟环境
        venv_dir = data_path / "venv_genai"
        if os.path.exists(venv_dir):
            try:
                shutil.rmtree(venv_dir)
                logger.info(f"虚拟环境 {venv_dir} 已删除")
            except Exception as e:
                logger.error(f"虚拟环境 {venv_dir} 删除失败: {e}")

        # 删除任务记录
        with self._tasks_lock:
            self._tasks = {}
            self.save_tasks()

    def load_tasks(self) -> Dict[str, Task]:
        raw_tasks = self.get_data("tasks") or {}
        tasks = {}
        for task_id, task_dict in raw_tasks.items():
            try:
                task = Task.model_validate(task_dict)
                tasks[task_id] = task
            except Exception as e:
                logger.error(f"加载任务失败：{e}")
        return tasks

    def save_tasks(self):
        with self._tasks_lock:
            tasks_dict = {
                task_id: task.model_dump(mode="json")
                for task_id, task in self._tasks.items()
            }
        self.save_data("tasks", tasks_dict)

    def add_task(self, video_file: str, skip_existing=True):
        task = Task(
            video_path=video_file,
            add_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            params=TaskParams(skip_existing=skip_existing),
        )
        with self._tasks_lock:
            self._tasks[task.task_id] = task
        self._task_queue.put(task)
        self.save_tasks()
        logger.info(f"加入任务队列: {video_file}")

    def add_media_file(self, path: str, skip_existing: bool = True):
        """
        添加新任务
        """
        if not self._shutdown_event.is_set():
            self.add_task(path)
        else:
            raise RuntimeError("Plugin is shutting down. Cannot add new tasks.")

    def delete_tasks(self, task_id: str | None):
        historical_status = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
            TaskStatus.IGNORED,
        }
        with self._tasks_lock:
            if task_id is None:
                tasks_to_delete = [
                    task_id
                    for task_id, task in self._tasks.items()
                    if task.status in historical_status
                ]
            else:
                task = self._tasks.get(task_id)
                if task and task.status in historical_status:
                    tasks_to_delete = [task_id]
                else:
                    tasks_to_delete = []
            for task_id in tasks_to_delete:
                del self._tasks[task_id]
        self.save_tasks()

    def task_interface(self, params: TasksApiParams) -> Response:
        if params.operation == "DELETE":
            logger.info("清空任务记录")
            self.delete_tasks(params.task_id)
        return Response(success=True)

    def __update_config(self):
        with self._config_updating_lock:
            self.update_config(
                {
                    "enabled": self._enabled,
                    "annot_level": self._annot_level,
                    "send_notify": self._send_notify,
                    "onlyonce": self._onlyonce,
                    "show_vocabulary_detail": self._show_vocabulary_detail,
                    "sentence_translation": self._sentence_translation,
                    "in_place": self._in_place,
                    "enable_gemini": self._enable_gemini,
                    "gemini_model": self._gemini_model,
                    "gemini_apikey": self._gemini_apikey,
                    "context_window": self._context_window,
                    "max_retries": self._max_retries,
                    "ffmpeg_path": self._ffmpeg_path,
                    "english_only": self._english_only,
                    "when_file_trans": self._when_file_trans,
                    "model_temperature": self._model_temperature,
                    "show_phonetics": self._show_phonetics,
                    "custom_files": self._custom_files,
                    "accent_color": self._accent_color,
                    "font_scaling": self._font_scaling,
                    "opacity": self._opacity,
                    "spacy_model": self._spacy_model,
                    "exam_tags": self._exam_tags,
                    "delete_data": self._delete_data,
                    "libraries": self._libraries,
                    "llm_provider": self._llm_provider,
                    "llm_base_url": self._llm_base_url,
                    "use_mp_agent": self._use_mp_agent,
                    "use_proxy": self._use_proxy,
                }
            )

    def _send_message(
            self,
            task: Task,
            phase: Literal["start", "end"],
            context: Context | None = None,
            process_result: ProcessResult | None = None,
    ):
        if not self._send_notify:
            return
        video_path = Path(task.video_path)
        media_name = video_path.name
        if context and context.media_info and context.meta_info:
            media_info = context.media_info
            if media_info.type == MediaType.TV:
                media_name = (
                    f"{media_info.title_year} {context.meta_info.season_episode}"
                )
            else:
                media_name = f"{media_info.title_year}"
        message = f"标题： {media_name}"
        if phase == "start":
            self.post_message(
                title=f"【{self.plugin_name}】 任务开始",
                image=context.media_info.get_message_image()
                if context and context.meta_info
                else None,
                mtype=NotificationType.Plugin,
                text=f"{message}",
            )
        else:
            result = "完成"
            if process_result and process_result.status == TaskStatus.FAILED:
                result = "失败"
            elif process_result and process_result.status == TaskStatus.CANCELED:
                result = "取消"
            stat_str = f"\n{task.statistics.to_string()}" if task.statistics else ""
            self.post_message(
                title=f"【{self.plugin_name}】 任务{result}",
                mtype=NotificationType.Plugin,
                image=context.media_info.get_message_image()
                if context and context.meta_info
                else None,
                text=f"{message}\n备注：{process_result.message if process_result else ''}\n"
                     f"Tokens：{task.tokens_used:,}{stat_str}",
            )

    def __process_tasks(self):
        """
        后台线程：处理任务队列
        """
        logger.debug(f"👷 Worker thread {threading.get_ident():#x} started.")

        self.__load_data()
        if not self._loaded:
            logger.warn("插件数据未加载")
            self._enabled = False
            self.__update_config()
            logger.debug("🛑 Worker exiting...")
            return
        if self._enable_gemini:
            self._gemini_available = True
            if not self._gemini_apikey:
                logger.warn("未提供 APIKEY")
                self._gemini_available = False

        while not self._shutdown_event.is_set():
            try:
                task = self._task_queue.get(timeout=1)
                if task is None:
                    continue
                context = MediaChain().recognize_by_path(path=task.video_path)
                cb = None
                res = ProcessResult(status=TaskStatus.FAILED, message="未知错误")
                try:
                    task.status = TaskStatus.RUNNING
                    self._send_message(task, "start", context)
                    with SpacyWorker(self._spacy_model) as worker:
                        with get_openai_callback() as cb:
                            res = self._process_file(
                                task.video_path,
                                worker,
                                context,
                                task.params.skip_existing,
                            )
                        task.status = res.status
                        task.message = res.message
                        task.statistics = res.statistics
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.message = str(e)
                    logger.error(f"处理 {task.task_id} 出错: {e}")
                    res = ProcessResult(status=TaskStatus.FAILED, message=str(e))
                finally:
                    self._task_queue.task_done()
                    task.complete_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if cb:
                        task.tokens_used = cb.total_tokens
                        logger.info(f"任务 {task.task_id} 消耗 Tokens: "
                                    f"Input ({cb.prompt_tokens:,}), Output ({cb.reasoning_tokens:,})")
                    self.save_tasks()
                    self._send_message(task, "end", context, res)
            except queue.Empty:
                continue
        logger.debug(
            f"🛑 Worker thread {threading.get_ident():#x} received shutdown signal, exiting..."
        )

    def _process_file(
            self,
            path: str,
            spacy_worker: SpacyWorker,
            mediainfo: Context | None = None,
            skip_existing: bool = True
    ) -> ProcessResult:
        """
        处理视频文件
        """
        if not self._loaded:
            return ProcessResult(status=TaskStatus.FAILED, message="插件数据未加载")
        lexi = self._load_lexicon_from_local()
        if not lexi:
            logger.error("字典加载失败")
            return ProcessResult(status=TaskStatus.FAILED, message="字典加载失败")

        video = Path(path)
        if video.suffix.lower() not in settings.RMT_MEDIAEXT:
            return ProcessResult(status=TaskStatus.CANCELED, message="不支持的文件格式")
        if not video.exists() or not video.is_file():
            logger.warn(f"文件 {str(video)} 不存在, 跳过")
            return ProcessResult(status=TaskStatus.FAILED, message="文件不存在")
        ass_file = video.with_suffix(".en.ass")
        if ass_file.exists() and skip_existing:
            logger.warn(f"字幕文件 ({ass_file}) 已存在, 跳过")
            return ProcessResult(status=TaskStatus.IGNORED, message="字幕文件已存在")
        logger.info(f"📂 Processing file: {path}")

        ffmpeg_path = self._ffmpeg_path if self._ffmpeg_path else "ffmpeg"
        eng_mark = ["en", "en-US", "eng", "en-GB", "english", "en-AU"]
        embedded_subtitles = LexiAnnot._extract_subtitles_by_lang(
            path, eng_mark, ffmpeg_path
        )
        if not embedded_subtitles:
            return ProcessResult(
                status=TaskStatus.CANCELED, message="未找到嵌入式英文文本字幕"
            )
        # order factor = 0, if 'SDH' in track['title']
        # order factor = track['duration'], otherwise
        embedded_subtitles = sorted(
            embedded_subtitles,
            key=lambda track: track["duration"] * (1 - int("SDH" in track["title"])),
            reverse=True,
        )
        ret_message = ""
        stat = None
        if embedded_subtitles:
            logger.info(f"提取到 {len(embedded_subtitles)} 条英语文本字幕")
            for embedded_subtitle in embedded_subtitles:
                if self._shutdown_event.is_set():
                    return ProcessResult(
                        status=TaskStatus.CANCELED, message="任务已取消"
                    )
                ass_subtitle = SSAFile.from_string(
                    embedded_subtitle["subtitle"], format_="ass"
                )
                if embedded_subtitle.get("codec_id") == "S_TEXT/UTF8":
                    ass_subtitle = LexiAnnot.set_srt_style(ass_subtitle)
                ass_subtitle = self.__set_style(ass_subtitle)
                ass_subtitle, stat = self.process_subtitles(
                    ass_subtitle, lexi, spacy_worker, mediainfo
                )
                if self._shutdown_event.is_set():
                    return ProcessResult(
                        status=TaskStatus.CANCELED, message="任务已取消"
                    )
                if ass_subtitle:
                    try:
                        ass_subtitle.save(str(ass_file))
                        ret_message = "字幕已保存"
                        logger.info(f"字幕已保存：{str(ass_file)}")
                    except Exception as e:
                        ret_message = f"字幕文件 {ass_file} 保存失败"
                        logger.error(f"字幕文件 {ass_file} 保存失败, {e}")
                    break
                else:
                    logger.info(
                        f"处理字幕{embedded_subtitle['codec_id']}-{embedded_subtitle['stream_id']}失败"
                    )
        else:
            logger.warn(f"未能在{path}中找到可提取的英文字幕")
        if not ret_message:
            ret_message = "未能找到可提取的英文字幕"
        logger.info(f"✅ Finished: {path}")

        return ProcessResult(status=TaskStatus.COMPLETED, message=ret_message, statistics=stat)

    @cached(maxsize=1, ttl=1800)
    def __load_lexicon_version(self) -> Optional[str]:
        logger.info("正在检查远程词典文件版本...")
        url = f"{self._lexicon_repo}master/version"
        version = RequestUtils().get(url, headers=settings.REPO_GITHUB_HEADERS())
        if version is None:
            return None
        return version.strip()

    @cached(maxsize=1, ttl=3600 * 24)
    def _load_lexicon_from_local(self) -> Lexicon | None:
        data_path = self.get_data_path()
        try:
            lexicon_path = data_path / "lexicon.json"
            with open(lexicon_path, "r", encoding="utf-8") as f:
                content = f.read()
                lexicon_model = Lexicon.model_validate_json(content)
        except Exception as e:
            logger.error(f"词典文件加载失败: {e}")
            return None
        return lexicon_model

    def _retrieve_lexicon_online(self, version: str) -> Lexicon | None:
        logger.info("开始下载词典文件...")
        lexicon_files = ["cefr", "coca20k", "swear_words", "examinations"]
        lexicon_dict = {}
        for file in lexicon_files:
            url = f"{self._lexicon_repo}master/{file}.json"
            res = RequestUtils().get_res(url, headers=settings.REPO_GITHUB_HEADERS())
            if not res:
                return None
            if res.status_code == 200:
                lexicon_dict[file] = res.json()
        if any(file not in lexicon_dict for file in lexicon_files):
            return None
        logger.info(f"词典文件 (v{version}) 下载完成")
        data_path = self.get_data_path()
        lexicon_dict["version"] = version
        try:
            lexicon_path = data_path / "lexicon.json"
            with open(lexicon_path, "w", encoding="utf-8") as f:
                json.dump(lexicon_dict, f, ensure_ascii=False, indent=2)
            lexi = Lexicon.model_validate(lexicon_dict)
        except Exception as e:
            logger.warn(f"词典文件保存失败: {e}")
            return None
        return lexi

    def __load_data(self):
        """
        测试插件数据加载
        """
        logger.info(f"加载 spaCy 模型 {self._spacy_model}...")
        try:
            with SpacyWorker(self._spacy_model):
                nlp = True
        except RuntimeError:
            nlp = LexiAnnot.__download_spacy_model(self._spacy_model)

        lexi = self._load_lexicon_from_local()
        latest = self.__load_lexicon_version() or "0.0.0"
        if not lexi or StringUtils.compare_version(
                lexi.version or "0.0.0", "<", latest
        ):
            lexi = self._retrieve_lexicon_online(latest)
            self._load_lexicon_from_local.cache_clear()
        if not (nlp and lexi):
            self._loaded = False
            logger.warn("插件数据加载失败")
        else:
            self._loaded = True
            logger.info(f"当前词典文件版本: {lexi.version}")

    @staticmethod
    def __download_spacy_model(model_name: str) -> bool:
        logger.info(f"下载 spaCy 模型 {model_name}...")
        try:
            subprocess.run(
                [sys.executable, "-m", "spacy", "download", model_name],
                capture_output=True,
                text=True,
                check=True,
            )
            with SpacyWorker(model_name):
                nlp = True
        except subprocess.CalledProcessError as e:
            logger.error(f"下载 spaCy 模型 '{model_name}' 失败。")
            logger.error(f"命令返回非零退出码：{e.returncode}")
            logger.error(f"Stdout:\n{e.stdout}")
            logger.error(f"Stderr:\n{e.stderr}")
            return False
        except Exception as e:
            logger.error(f"下载或加载 spaCy 模型时发生意外错误：{e}")
            return False
        logger.info(f"spaCy 模型 '{model_name}' 加载成功！")
        return nlp

    @eventmanager.register(EventType.TransferComplete)
    def check_media(self, event: Event):
        if not self._enabled or not self._when_file_trans:
            return
        event_info: dict = event.event_data
        if not event_info:
            return

        # 入库数据
        transfer_info: TransferInfo | None = event_info.get("transferinfo")
        if (
                not transfer_info
                or not transfer_info.target_diritem
                or not transfer_info.target_diritem.path
        ):
            return

        # 检查是否为选择的媒体库
        in_libraries = False
        libraries = {
            library.name: library.library_path
            for library in DirectoryHelper().get_library_dirs()
        }
        for library_name in self._libraries:
            if library_name in libraries:
                ll = libraries[library_name]
                if ll and Path(transfer_info.target_diritem.path).is_relative_to(
                        Path(ll)
                ):
                    in_libraries = True
                    break
        if not in_libraries:
            return

        mediainfo: MediaInfo | None = event_info.get("mediainfo")
        if self._english_only and mediainfo:
            if mediainfo.original_language and mediainfo.original_language not in {
                "en",
                "eng",
            }:
                logger.info(
                    f"原始语言 ({mediainfo.original_language}) 不为英语, 跳过 {mediainfo.title}： "
                )
                return
        for new_path in transfer_info.file_list_new or []:
            self.add_media_file(new_path)

    @staticmethod
    def format_duration(ms):
        total_seconds, milliseconds = divmod(ms, 1000)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        hundredths = milliseconds // 10
        return f"{hours}:{minutes:02}:{seconds:02}.{hundredths:02}"

    @staticmethod
    def _remove_substring(replacements: list[dict]):
        new_list = []
        replacements.sort(key=lambda x: x["end"] - x["start"], reverse=True)
        for r in replacements:
            if any(
                    (r["start"] >= new["start"] and r["end"] <= new["end"])
                    for new in new_list
            ):
                continue
            new_list.append(r)
        return new_list

    @staticmethod
    def replace_by_plaintext_positions(line: SSAEvent, replacements: List[dict]):
        """
        使用 replacements 中的 plaintext 位置信息, 替换 line.text 中的内容。
        :param line: SSAEvent line
        :param replacements: [{'start': int, 'end': int, 'old_text': str, 'new_text': str}, ...]
        """
        text = line.text
        tag_pattern = re.compile(r"{.*?}")  # 匹配 {xxx} 格式控制符
        special_pattern = re.compile(r"\\[Nh]")
        # 构建 plaintext 位置到 text 索引的映射
        mapping = {}  # plaintext_index -> text_index
        p_index = 0  # 当前 plaintext 索引
        t_index = 0  # 当前 text 索引

        while t_index < len(text):
            if text[t_index] == "{":
                # 跳过格式标签
                match = tag_pattern.match(text, t_index)
                if match:
                    t_index = match.end()
                    continue
            elif text[t_index] == "\\":
                match = special_pattern.match(text, t_index)
                if match:
                    t_index = match.end() - 1
                    continue
            # 非格式字符
            mapping[p_index] = t_index
            p_index += 1
            t_index += 1
        replacements = LexiAnnot._remove_substring(replacements)
        # 按照 mapping 执行替换（倒序替换防止位置错位）
        new_text = text
        for r in sorted(replacements, key=lambda x: x["start"], reverse=True):
            start = mapping.get(r["start"])
            end = mapping.get(r["end"] - 1)
            if start is None or end is None:
                continue
            end += 1
            new_text = new_text[:start] + r["new_text"] + new_text[end:]

        line.text = new_text

    @staticmethod
    def analyze_ass_language(ass_file: SSAFile):
        styles = {}
        for style in ass_file.styles:
            styles[style] = {"text": [], "duration": 0, "text_size": 0, "times": 0}
        for dialogue in ass_file:
            style = dialogue.style
            text = dialogue.plaintext
            sub_text = text.split("\n")
            if style not in styles or not text:
                continue
            styles[style]["text"].extend(sub_text)
            styles[style]["duration"] += dialogue.duration
            styles[style]["text_size"] += len(text)
            styles[style]["times"] += 1
        style_language_analysis = {}
        for style_name, data in styles.items():
            all_text = " ".join(data["text"])
            if not all_text.strip():
                style_language_analysis[style_name] = None
                continue

            languages = []
            # 对每个文本片段进行语言检测
            for text_fragment in data["text"]:
                try:
                    lang = detect(text_fragment)
                    languages.append(lang)
                except Exception as e:
                    # 无法检测的文本
                    logger.debug(e)
                    pass

            if languages:
                language_counts = Counter(languages)
                most_common_language = language_counts.most_common(1)[0]
                style_language_analysis[style_name] = {
                    "main_language": most_common_language[0],
                    "proportion": most_common_language[1] / len(languages),
                    "duration": data["duration"],
                    "text_size": data["text_size"],
                    "times": data["times"],
                }
            else:
                style_language_analysis[style_name] = None

        return style_language_analysis

    @staticmethod
    def select_main_style_weighted(
            language_analysis: Dict[str, Any], known_language: str, weights=None
    ):
        """
        根据语言分析结果和已知的字幕语言，使用加权评分选择主要样式

        :params language_analysis: `analyze_ass_language` 函数的输出结果
        :params known_language: 已知的字幕语言代码
        :params weights: 各个维度的权重，权重之和应为 1
        :returns: 主要字幕的样式名称，如果没有匹配的样式则返回 None
        """
        if weights is None:
            weights = {"times": 0.5, "text_size": 0.4, "duration": 0.1}
        matching_styles = []
        max_times = max([analysis.get("times", 0) for _, analysis in language_analysis.items() if analysis]) or 1
        max_text_size = (
                    max([analysis.get("text_size", 0) for _, analysis in language_analysis.items() if analysis]) or 1)
        max_duration = (
                max(
                    [
                        analysis.get("duration", 0)
                        for _, analysis in language_analysis.items()
                        if analysis
                    ]
                )
                or 1
        )
        for style, analysis in language_analysis.items():
            if not analysis:
                continue
            if analysis.get("main_language") == known_language:
                # 跳过多语言
                if analysis.get("proportion", 0) < 0.5:
                    continue
                score = 0
                score += analysis.get("times", 0) * weights.get("times", 0) / max_times
                score += analysis.get("text_size", 0) * weights.get("text_size", 0) / max_text_size
                score +=  analysis.get("duration", 0) * weights.get("duration", 0) / max_duration
                matching_styles.append((style, score))

        if not matching_styles:
            return None

        sorted_styles = sorted(matching_styles, key=lambda item: item[1], reverse=True)
        return sorted_styles[0][0]

    @staticmethod
    def set_srt_style(ass: SSAFile) -> SSAFile:
        ass.info["ScaledBorderAndShadow"] = "no"
        play_res_y = int(ass.info["PlayResY"])
        if "Default" in ass.styles:
            ass.styles["Default"].marginv = play_res_y // 16
            ass.styles["Default"].fontname = "Microsoft YaHei"
            ass.styles["Default"].fontsize = play_res_y // 16
        return ass

    def __set_style(self, ass: SSAFile) -> SSAFile:
        font_scaling = (
            float(self._font_scaling)
            if self._font_scaling and len(self._font_scaling)
            else 1
        )
        play_res_y = int(ass.info["PlayResY"])
        play_res_x = int(ass.info["PlayResX"])
        # 创建一个新样式
        fs = play_res_y // 16 * font_scaling
        new_style = SSAStyle()
        new_style.name = "Annotation EN"
        new_style.fontname = "Times New Roman"
        new_style.fontsize = fs
        new_style.primarycolor = Color(
            self._accent_color_rgb[0],
            self._accent_color_rgb[1],
            self._accent_color_rgb[2],
            self._color_alpha,
        )  # 黄色 (BGR, alpha)
        new_style.bold = True
        new_style.italic = False
        new_style.outline = 1
        new_style.shadow = 0
        new_style.alignment = Alignment.TOP_LEFT
        new_style.marginl = play_res_x // 20
        new_style.marginr = play_res_x // 20
        new_style.marginv = int(fs)
        ass.styles["Annotation EN"] = new_style
        zh_style = new_style.copy()
        zh_style.name = "Annotation ZH"
        zh_style.fontname = "Microsoft YaHei"
        zh_style.primarycolor = Color(255, 255, 255, self._color_alpha)
        ass.styles["Annotation ZH"] = zh_style

        usage_style = zh_style.copy()
        usage_style.name = "Annotation USAGE"
        usage_style.fontsize = fs * 0.75
        usage_style.italic = True
        usage_style.primarycolor = Color(224, 224, 224, self._color_alpha)
        ass.styles["Annotation USAGE"] = usage_style

        pos_style = zh_style.copy()
        pos_style.name = "Annotation POS"
        pos_style.fontname = "Times New Roman"
        pos_style.fontsize = fs * 0.75
        pos_style.italic = True
        ass.styles["Annotation POS"] = pos_style

        phone_style = pos_style.copy()
        phone_style.name = "Annotation PHONE"
        phone_style.fontname = "Arial"
        phone_style.fontsize = fs * 0.75
        phone_style.bold = False
        phone_style.italic = False
        ass.styles["Annotation PHONE"] = phone_style

        pos_def_cn_style = zh_style.copy()
        pos_def_cn_style.name = "DETAIL CN"
        pos_def_cn_style.fontsize = fs * 0.7
        ass.styles["DETAIL CN"] = pos_def_cn_style

        pos_def_pos_style = pos_style.copy()
        pos_def_pos_style.name = "DETAIL POS"
        pos_def_pos_style.fontsize = fs * 0.6
        ass.styles["DETAIL POS"] = pos_def_pos_style

        cefr_style = pos_style.copy()
        cefr_style.name = "Annotation CEFR"
        cefr_style.fontname = "Times New Roman"
        cefr_style.fontsize = fs * 0.5
        cefr_style.bold = True
        cefr_style.italic = False
        cefr_style.primarycolor = Color(
            self._accent_color_rgb[0],
            self._accent_color_rgb[1],
            self._accent_color_rgb[2],
            self._color_alpha,
        )
        cefr_style.outline = 1
        cefr_style.shadow = 0
        ass.styles["Annotation CEFR"] = cefr_style
        ass.styles["Annotation EXAM"] = cefr_style
        return ass

    @staticmethod
    def hex_to_rgb(hex_color) -> Optional[Tuple]:
        if not hex_color:
            return None
        pattern = r"^#[0-9a-fA-F]{6}$"
        if re.match(pattern, hex_color) is None:
            return None
        hex_color = hex_color.lstrip("#")  # 去掉前面的 #
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def __extract_subtitle(
            video_path: str,
            subtitle_stream_index: str,
            ffmpeg_path: str = "ffmpeg",
            sub_format="ass",
    ) -> Optional[str]:
        if sub_format not in ["srt", "ass"]:
            raise ValueError("Invalid subtitle format")
        try:
            map_parameter = f"0:s:{subtitle_stream_index}"
            command = [ffmpeg_path, "-i", video_path, "-map", map_parameter, "-f", sub_format, "-"]
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", check=True
            )
            return result.stdout
        except FileNotFoundError:
            logger.warn(f"错误：找不到视频文件 '{video_path}'")
            return None
        except subprocess.CalledProcessError as e:
            logger.warn(f"错误：提取字幕失败。\n错误信息：{e}")
            logger.warn(
                f"FFmpeg 输出 (stderr):\n{e.stderr.decode('utf-8', errors='ignore')}"
            )
            return None

    @staticmethod
    def _extract_subtitles_by_lang(
            video_path: str, lang: str | list = "en", ffmpeg: str = "ffmpeg"
    ) -> Optional[List[Dict]]:
        """
        提取视频文件中的内嵌英文字幕，使用 MediaInfo 查找字幕流。
        """

        def check_lang(track_lang: str) -> bool:
            if isinstance(lang, list):
                return track_lang in lang
            return track_lang == lang

        supported_codec = ["S_TEXT/UTF8", "S_TEXT/ASS"]
        subtitles = []
        try:
            media_info: pymediainfo.MediaInfo = pymediainfo.MediaInfo.parse(video_path)
            for track in media_info.tracks:
                if (
                        track.track_type == "Text"
                        and check_lang(track_lang=track.language)
                        and track.codec_id in supported_codec
                ):
                    subtitle_stream_index = (
                        track.stream_identifier
                    )  # MediaInfo 的 stream_id 从 1 开始，ffmpeg 从 0 开始
                    extracted_subtitle = LexiAnnot.__extract_subtitle(
                        video_path, subtitle_stream_index, ffmpeg
                    )
                    duration = 0
                    if hasattr(track, "duration"):
                        try:
                            duration = int(float(track.duration))
                        except (ValueError, TypeError):
                            pass
                    if extracted_subtitle:
                        subtitles.append(
                            {
                                "title": track.title or "",
                                "subtitle": extracted_subtitle,
                                "codec_id": track.codec_id,
                                "stream_id": subtitle_stream_index,
                                "duration": duration,
                            }
                        )
            if subtitles:
                return subtitles
            else:
                logger.warn("未找到标记为英语的文本字幕流")
                return None

        except FileNotFoundError:
            logger.error(f"找不到视频文件 '{video_path}'")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"错误：提取字幕失败。\n错误信息：{e}")
            logger.error(f"FFmpeg 输出 (stderr):\n{e.stderr}")
            return None
        except Exception as e:
            logger.error(f"使用 MediaInfo 提取字幕时发生错误：{e}")
            return None

    def _process_chain(
            self,
            segments: SegmentList,
            lexi: Lexicon,
            spacy_worker: SpacyWorker,
            mediainfo: Context | None = None,
    ) -> SegmentList:
        """
        处理字幕行

        :param segments: 待处理的字幕
        :param lexi: 词典对象
        :param spacy_worker: spaCy 分词器
        :returns: 处理后的字幕行列表
        """
        simple_vocabulary = set(
            filter(
                lambda x: x < self._annot_level, ["A1", "A2", "B1", "B2", "C1", "C2"]
            )
        )

        # model_temperature = float(self._model_temperature) if self._model_temperature else 0.1
        logger.info("通过 spaCy 分词...")
        for seg in segments:
            if self._shutdown_event.is_set():
                return segments
            seg.candidate_words = extract_advanced_words(
                segment=seg,
                lexi=lexi,
                spacy_worker=spacy_worker,
                simple_level=simple_vocabulary,
                exams=self._exam_tags,
            )
        if self._gemini_available:
            if self._use_mp_agent:
                llm_apikey = settings.LLM_API_KEY
                llm_base_url = settings.LLM_BASE_URL
                llm_model_name = settings.LLM_MODEL
                llm_provider = settings.LLM_PROVIDER.lower()
            else:
                llm_apikey = self._gemini_apikey
                llm_base_url = self._llm_base_url
                llm_model_name = self._gemini_model
                llm_provider = self._llm_provider.lower()
            llm = initialize_llm(
                provider=llm_provider,
                model_name=llm_model_name,
                base_url=llm_base_url,
                api_key=llm_apikey,
                temperature=self._model_temperature,
                max_retries=self._max_retries,
                proxy=self._use_proxy,
            )
            segments = llm_process_chain(
                lexi=lexi,
                llm=llm,
                segments=segments,
                shutdown_event=self._shutdown_event,
                context_window=self._context_window,
                leaner_level=self._annot_level,
                media_context=mediainfo,
                translate_sentences=self._sentence_translation
            )
        return segments

    def process_subtitles(
            self,
            ass_file: SSAFile,
            lexi: Lexicon,
            spacy_worker: SpacyWorker,
            mediainfo: Context | None = None,
    ) -> tuple[SSAFile | None, SegmentStatistics | None]:
        """
        处理字幕内容，标记词汇并添加翻译。
        """
        lang = "en"
        abgr_str = (
            f"&H{self._color_alpha:02x}{self._accent_color_rgb[2]:02x}"
            f"{self._accent_color_rgb[1]:02x}{self._accent_color_rgb[0]:02x}&"
        )  # &H00FFFFFF&

        statistical_res = LexiAnnot.analyze_ass_language(ass_file)
        main_style: str | None = LexiAnnot.select_main_style_weighted(
            statistical_res, lang
        )
        if not main_style:
            logger.error("无法确定主要字幕样式")
            return None, None
        # main_dialogue: Dict[int, SSAEvent] = {}
        main_processor = SubtitleProcessor()
        IDGenerator().reset()
        for dialogue in ass_file:
            if dialogue.style != main_style:
                continue
            main_processor.append(dialogue)
        segments = SegmentList(root=list(main_processor.segment_generator()))
        segments = self._process_chain(
            segments=segments, lexi=lexi, spacy_worker=spacy_worker, mediainfo=mediainfo
        )
        # 在原字幕添加标注
        main_style_fs = ass_file.styles[main_style].fontsize
        __N = r"\N"
        for seg in segments:
            if self._shutdown_event.is_set():
                return None, None
            if seg.candidate_words:
                replacements = []
                for word in seg.candidate_words:
                    exams = [exam for exam in word.exams if exam in self._exam_tags]
                    new_text = f"{{\\c{abgr_str}}}{word.text}{{\\r}}"
                    if self._in_place:
                        part_of_speech = (f"{{\\fnTimes New Roman\\fs{int(main_style_fs * 0.75)}\\i1}}"
                                          f"{UNIVERSAL_POS_MAP[word.pos] or ''}{{\\r}}")
                        new_text = new_text + f" ({word.llm_translation} {part_of_speech})" \
                            if word.llm_translation else ""
                    else:
                        dialogue = SSAEvent()
                        dialogue.start = main_processor[seg.index].start
                        dialogue.end = main_processor[seg.index].end
                        dialogue.style = "Annotation EN"
                        cefr_text = (
                            f" {style_text('Annotation CEFR', word.cefr)}"
                            if word.cefr
                            else ""
                        )
                        exam_text = (
                            f" {style_text('Annotation EXAM', ' '.join(exams))}"
                            if exams
                            else ""
                        )
                        phone_text = (
                            f"{__N}{style_text('Annotation PHONE', f'/{word.phonetics}/')}"
                            if word.phonetics and self._show_phonetics
                            else ""
                        )
                        annot_text = (f"{word.lemma} "
                                      f"{style_text('Annotation POS', UNIVERSAL_POS_MAP[word.pos] or '')} "
                                      f"{style_text('Annotation ZH', word.llm_translation or '')}"
                                      f"{cefr_text}{exam_text}{phone_text}")
                        dialogue.text = annot_text
                        ass_file.append(dialogue)
                        if word.llm_usage_context:
                            dialogue = SSAEvent(
                                start=main_processor[seg.index].start,
                                style="DETAIL CN",
                                end=main_processor[seg.index].end,
                                text=style_text("Annotation USAGE", f"{{\\q1}}{word.llm_usage_context}"),
                            )
                            ass_file.append(dialogue)
                        if self._show_vocabulary_detail and word.pos_defs:
                            dialogue = SSAEvent(
                                start=main_processor[seg.index].start,
                                style="DETAIL CN",
                                end=main_processor[seg.index].end,
                            )
                            detail_text = []
                            for pos_def in word.pos_defs:
                                meaning_str = ", ".join(pos_def.meanings)
                                pos_text = f"{style_text('DETAIL POS', pos_def.pos)} {meaning_str}"
                                detail_text.append(pos_text)
                            dialogue.text = "\\N".join(detail_text)
                            ass_file.append(dialogue)
                    replacement = {
                        "start": word.meta.start_pos,
                        "end": word.meta.end_pos,
                        "new_text": new_text,
                    }
                    replacements.append(replacement)
                LexiAnnot.replace_by_plaintext_positions(
                    main_processor[seg.index], replacements
                )
            if self._sentence_translation:
                chinese = seg.Chinese
                if chinese and chinese[-1] in ["。", "，"]:
                    chinese = chinese[:-1]
                main_processor[seg.index].text = (
                        main_processor[seg.index].text + f"\\N{{\\fs{int(main_style_fs * 0.75)}}}{chinese}{{\\r}}"
                )

        # 避免 Infuse 显示乱码
        unexplainable_line = SSAEvent(
            start=0, end=0, text=f"{style_text('Annotation ZH', self.plugin_name)}"
        )
        ass_file.insert(0, unexplainable_line)
        return ass_file, segments.statistics
