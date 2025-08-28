import os
import json
import queue
import re
import shutil
import subprocess
import sys
import time
import threading
import uuid
import venv
from collections import Counter
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, Union, Type, TypeVar

import pysubs2
from pysubs2 import SSAFile, SSAEvent
import pymediainfo
from langdetect import detect
from spacy.tokenizer import Tokenizer
import spacy

from app.core.config import settings
from app.helper.directory import DirectoryHelper
from app.log import logger
from app.plugins import _PluginBase
from app.core.cache import cached
from app.core.event import eventmanager, Event
from app.utils.system import SystemUtils
from app.schemas.types import NotificationType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.schemas import TransferInfo
from app.schemas.types import EventType
from app.core.context import MediaInfo
from app.plugins.lexiannot.query_gemini import DialogueTranslationTask, VocabularyTranslationTask, Vocabulary, Context


T = TypeVar('T', VocabularyTranslationTask, DialogueTranslationTask)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    IGNORED = "ignored"


class Task:

    def __init__(self, video_path: str,
                 task_id: Optional[str] = None,
                 status: TaskStatus = TaskStatus.PENDING,
                 add_time: Optional[datetime] = None,
                 complete_time: Optional[datetime] = None,
                 tokens_used: int = 0):
        self.task_id = task_id or str(uuid.uuid4())
        self.video_path = video_path
        self.status: TaskStatus = status
        self.add_time: Optional[datetime] = add_time
        self.complete_time: Optional[datetime] = complete_time
        self.tokens_used: int = tokens_used

    def __repr__(self):
        return f"<Task {self.task_id[:8]} status={self.status} video={self.video_path}>"

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "video_path": self.video_path,
            "status": self.status.value,
            "add_time": self.add_time.isoformat() if self.add_time else None,
            "complete_time": self.complete_time.isoformat() if self.complete_time else None,
            "tokens_used": self.tokens_used
        }


class LexiAnnot(_PluginBase):
    # 插件名称
    plugin_name = "美剧生词标注"
    # 插件描述
    plugin_desc = "根据CEFR等级，为英语影视剧标注高级词汇。"
    # 插件图标
    plugin_icon = "LexiAnnot.png"
    # 插件版本
    plugin_version = "1.1.1"
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
    _annot_level = ''
    _send_notify = False
    _onlyonce = False
    _show_vocabulary_detail = False
    _show_phonetics = False
    _sentence_translation = False
    _in_place = False
    _enable_gemini = False
    _gemini_model = ''
    _gemini_apikey = ''
    _context_window: int = 0
    _max_retries: int = 0
    _request_interval: int = 0
    _ffmpeg_path = ''
    _english_only = False
    _when_file_trans = False
    _model_temperature = ''
    _custom_files = ''
    _accent_color = ''
    _font_scaling = ''
    _opacity = ''
    _exam_tags: List[str] = []
    _spacy_model: str = ''
    _delete_data: bool = False
    _libraries: List[str] = []

    # protected variables
    _lexicon_repo = 'https://raw.githubusercontent.com/wumode/LexiAnnot/'
    _worker_thread = None
    _task_queue: queue.Queue[Task] = queue.Queue()
    _shutdown_event = None
    _total_token_count = 0
    _venv_python = None
    _query_gemini_script = ''
    _gemini_available = False
    _accent_color_rgb = None
    _color_alpha = 0
    _loaded = False
    _config_updating_lock: threading.Lock = threading.Lock()
    _tasks_lock: threading.RLock = threading.RLock()
    _tasks: Dict[str, Task] = {}
    import spacy

    def init_plugin(self, config=None):
        self.stop_service()
        if config:
            self._enabled = config.get("enabled")
            self._annot_level = config.get("annot_level") or 'C1'
            self._send_notify = config.get("send_notify")
            self._onlyonce = config.get("onlyonce")
            self._show_vocabulary_detail = config.get("show_vocabulary_detail")
            self._sentence_translation = config.get("sentence_translation")
            self._in_place = config.get("in_place")
            self._enable_gemini = config.get("enable_gemini")
            self._gemini_model = config.get("gemini_model") or 'gemini-2.0-flash'
            self._gemini_apikey = config.get("gemini_apikey") or ''
            self._context_window = int(config.get("context_window") or 10)
            self._max_retries = int(config.get("max_retries") or 3)
            self._request_interval = int(config.get("request_interval") or 3)
            self._ffmpeg_path = config.get("ffmpeg_path")
            self._english_only = config.get("english_only")
            self._when_file_trans = config.get("when_file_trans")
            self._model_temperature = config.get("model_temperature") or '0.3'
            self._show_phonetics = config.get("show_phonetics")
            self._custom_files = config.get("custom_files")
            self._accent_color = config.get("accent_color")
            self._font_scaling = config.get("font_scaling") or '1'
            self._opacity = config.get("opacity") or '0'
            self._spacy_model = config.get("spacy_model") or 'en_core_web_sm'
            self._exam_tags = config.get("exam_tags") or []
            self._delete_data = config.get("delete_data") or False
            self._libraries = config.get("libraries") or []

            libraries = [library.name for library in DirectoryHelper().get_library_dirs()]
            self._libraries = [library for library in self._libraries if library in libraries]
            self._accent_color_rgb = LexiAnnot.hex_to_rgb(self._accent_color) or (255, 255, 0)
            self._color_alpha = int(self._opacity) if self._opacity and len(self._opacity) else 0
        if self._delete_data:
            # 删除不再保存在数据库的数据
            self.del_data('cefr_lexicon')
            self.del_data('coca2k_lexicon')
            self.del_data('swear_words')
            self.del_data('lexicon_version')
            self.delete_data()
            self._delete_data = False
            self._loaded = False

        tasks = self.load_tasks()
        with self._tasks_lock:
            self._tasks = tasks
        if self._enabled:
            self._query_gemini_script = str(settings.ROOT_PATH / "app" / "plugins" / "lexiannot" / "query_gemini.py")

            self._shutdown_event = threading.Event()
            self._worker_thread = threading.Thread(target=self.__process_tasks, daemon=True)
            self._worker_thread.start()

            if self._onlyonce:
                for file_path in self._custom_files.split("\n"):
                    if not file_path:
                        continue
                    self.add_media_file(file_path)
                self._onlyonce = False
        self.__update_config()

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        library_options = [{'title': library.name,'value': library.name}
                           for library in DirectoryHelper().get_library_dirs()]
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },

                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'send_notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '手动运行一次',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'delete_data',
                                            'label': '插件数据清理',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VTabs',
                        'props': {
                            'model': '_tabs',
                            'style': {
                                'margin-top': '8px',
                                'margin-bottom': '16px'
                            },
                            'stacked': True,
                            'fixed-tabs': True
                        },
                        'content': [
                            {
                                'component': 'VTab',
                                'props': {
                                    'value': 'base_tab'
                                },
                                'text': '基本设置'
                            }, {
                                'component': 'VTab',
                                'props': {
                                    'value': 'subtitle_tab'
                                },
                                'text': '字幕设置'
                            }, {
                                'component': 'VTab',
                                'props': {
                                    'value': 'gemini_tab'
                                },
                                'text': 'Gemini设置'
                            }
                        ]
                    },
                    {
                        'component': 'VWindow',
                        'props': {
                            'model': '_tabs'
                        },
                        'content': [
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'base_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '0px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'when_file_trans',
                                                            'label': '监控入库',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'spacy_model',
                                                            'label': 'spaCy模型',
                                                            'hint': 'spaCy 模型用于分词和词性标注，推荐使用 Small',
                                                            'items': [
                                                                {'title': 'Small (~12 MB)', 'value': 'en_core_web_sm'},
                                                                {'title': 'Medium (~30 MB)', 'value': 'en_core_web_md'},
                                                                {'title': 'Large (700+ MB)', 'value': 'en_core_web_lg'},
                                                                {'title': 'Transformer (400+ MB)',
                                                                 'value': 'en_core_web_trf'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'annot_level',
                                                            'label': '标注词汇的最低CEFR等级',
                                                            'items': [
                                                                {'title': 'B1', 'value': 'B1'},
                                                                {'title': 'B2', 'value': 'B2'},
                                                                {'title': 'C1', 'value': 'C1'},
                                                                {'title': 'C2', 'value': 'C2'},
                                                                {'title': 'C2+', 'value': 'C2+'}
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'english_only',
                                                            'label': '仅英语影视剧',
                                                            'hint': '检查入库影视剧原语言'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 8
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'exam_tags',
                                                            'label': '考试词汇标签',
                                                            'chips': True,
                                                            'multiple': True,
                                                            'items': [
                                                                {'title': '四级', 'value': 'CET-4'},
                                                                {'title': '六级', 'value': 'CET-6'},
                                                                {'title': '考研', 'value': 'NPEE'},
                                                                {'title': '雅思', 'value': 'IELTS'},
                                                                {'title': '托福', 'value': 'TOEFL'},
                                                                {'title': '专四', 'value': 'TEM-4'},
                                                                {'title': '专八', 'value': 'TEM-8'},
                                                                {'title': 'GRE', 'value': 'GRE'},
                                                                {'title': 'PET', 'value': 'PET'},
                                                            ]
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
                                                'props': {
                                                    'cols': 12,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'ffmpeg_path',
                                                            'label': 'FFmpeg 路径',
                                                            'placeholder': 'ffmpeg'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'subtitle_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '0px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'font_scaling',
                                                            'label': '字体缩放',
                                                            'items': [
                                                                {'title': '50%', 'value': '0.5'},
                                                                {'title': '75%', 'value': '0.75'},
                                                                {'title': '100%', 'value': '1'},
                                                                {'title': '125%', 'value': '1.25'},
                                                                {'title': '150%', 'value': '1.5'},
                                                                {'title': '200%', 'value': '2'}
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'accent_color',
                                                            'label': '强调色',
                                                            'placeholder': '#FFFF00'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'opacity',
                                                            'label': '不透明度',
                                                            'items': [
                                                                {'title': '0', 'value': '0'},
                                                                {'title': '25%', 'value': '63'},
                                                                {'title': '50%', 'value': '127'},
                                                                {'title': '75%', 'value': '191'},
                                                                {'title': '100%', 'value': '255'},
                                                            ]
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
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'show_phonetics',
                                                            'label': '标注音标',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'in_place',
                                                            'label': '在原字幕插入注释',
                                                        }
                                                    }
                                                ]
                                            },

                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'show_vocabulary_detail',
                                                            'label': '显示完整释义',
                                                        }
                                                    }
                                                ]
                                            },

                                        ]
                                    },
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'gemini_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 6,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'enable_gemini',
                                                            'label': '启用Gemini翻译',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 6
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'sentence_translation',
                                                            'label': '整句翻译',
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
                                                'props': {
                                                    'cols': 12,
                                                    'md': 6,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'gemini_model',
                                                            'label': '模型',
                                                            'items': [
                                                                {'title': 'gemini-2.5-flash',
                                                                 'value': 'gemini-2.5-flash'},
                                                                {'title': 'gemini-2.5-flash-lite',
                                                                 'value': 'gemini-2.5-flash-lite'},
                                                                {'title': 'gemini-2.5-pro',
                                                                 'value': 'gemini-2.5-pro'},
                                                                {'title': 'gemini-2.0-flash',
                                                                 'value': 'gemini-2.0-flash'},
                                                                {'title': 'gemini-2.0-flash-lite',
                                                                 'value': 'gemini-2.0-flash-lite'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 6,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'gemini_apikey',
                                                            'label': 'Gemini APIKEY',
                                                            'placeholder': ''
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'context_window',
                                                            'label': '上下文窗口大小',
                                                            'placeholder': '10',
                                                            'type': 'number',
                                                            'max': 20,
                                                            'min': 1,
                                                            'hint': '向Gemini发送的上下文长度'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'model_temperature',
                                                            'label': '模型温度',
                                                            'items': [
                                                                {'title': '0', 'value': '0'},
                                                                {'title': '0.1', 'value': '0.1'},
                                                                {'title': '0.2', 'value': '0.2'},
                                                                {'title': '0.3', 'value': '0.3'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'max_retries',
                                                            'label': '请求重试次数',
                                                            'placeholder': '3',
                                                            'type': 'number',
                                                            'min': 1,
                                                            'hint': '请求失败重试次数'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'request_interval',
                                                            'label': '请求间隔',
                                                            'type': 'number',
                                                            'placeholder': 5,
                                                            'min': 1,
                                                            'suffix': '秒',
                                                            'hint': '请求间隔时间，建议不少于3秒'
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {
                            'style': {
                                'margin-top': '0px'
                            }
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'libraries',
                                            'label': '监控入库',
                                            'items': library_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {
                            'style': {
                                'margin-top': '0px'
                            }
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'custom_files',
                                            'label': '手动处理视频路径',
                                            'rows': 3,
                                            'placeholder': '每行一个文件'
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'success',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                                'component': 'span',
                                                'text': '配置说明：'
                                            },
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': 'https://github.com/jxxghp/MoviePilot-Plugins/tree/main/plugins.v2/lexiannot/README.md',
                                                    'target': '_blank'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'u',
                                                        'text': 'README'
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "annot_level": 'C1',
            "send_notify": False,
            "onlyonce": False,
            "show_vocabulary_detail": False,
            "show_phonetics": False,
            "sentence_translation": False,
            "in_place": False,
            "enable_gemini": False,
            "gemini_model": 'gemini-2.0-flash',
            "gemini_apikey": '',
            "context_window": 10,
            "max_retries": 3,
            'request_interval': 3,
            "ffmpeg_path": "",
            "english_only": True,
            "when_file_trans": True,
            "model_temperature": '0.3',
            "custom_files": '',
            "accent_color": '',
            "font_scaling": '1',
            "opacity": '0',
            "spacy_model": 'en_core_web_sm',
            "exam_tags": [],
            "delete_data": False,
            "libraries": []
        }

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_page(self) -> List[dict]:
        headers = [
            {'title': '添加时间', 'key': 'add_time', 'sortable': True},
            {'title': '视频文件', 'key': 'video_path', 'sortable': True},
            {'title': '消耗 Tokens', 'key': 'tokens_used', 'sortable': True},
            {'title': '完成时间', 'key': 'complete_time', 'sortable': True},
            {'title': '任务状态', 'key': 'status', 'sortable': True},
        ]
        items = []
        with self._tasks_lock:
            sorted_tasks = sorted(
                self._tasks.items(),
                key=lambda x: x[1].add_time,
                reverse=True
            )

        status_map = {
            TaskStatus.PENDING: "等待中",
            TaskStatus.RUNNING: "处理中",
            TaskStatus.COMPLETED: "已完成",
            TaskStatus.IGNORED: "已忽略",
            TaskStatus.FAILED: "失败",
            TaskStatus.CANCELED: "已取消"
        }

        for task_id, task in sorted_tasks:
            status_text = status_map.get(task.status, task.status)
            item = {
                'task_id': task_id,
                'status': status_text,
                'video_path': task.video_path,
                'add_time': task.add_time.strftime("%Y-%m-%d %H:%M:%S") if task.add_time else '-',
                'tokens_used': task.tokens_used,
                'complete_time': task.complete_time.strftime("%Y-%m-%d %H:%M:%S") if task.complete_time else '-',
            }
            items.append(item)
        return [
            {
                'component': 'VRow',
                'props': {
                    'style': {
                        'overflow': 'hidden',
                    }
                },
                'content': [
                    {
                        'component': 'VRow',
                        'props': {
                            'class': 'd-none d-sm-block',
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VDataTableVirtual',
                                        'props': {
                                            'class': 'text-sm',
                                            'headers': headers,
                                            'items': items,
                                            'height': '30rem',
                                            'density': 'compact',
                                            'fixed-header': True,
                                            'hide-no-data': True,
                                            'hover': True
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_state(self) -> bool:
        """
        获取插件状态，如果插件正在运行， 则返回True
        """
        return self._enabled

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
        lexicon_path = data_path / 'lexicon.json'
        try:
            os.remove(lexicon_path)
            logger.info(f"词典 {lexicon_path} 已删除")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"词典 {lexicon_path} 删除失败: {e}")
        self.__load_lexicon_from_local.cache_clear()

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
        raw_tasks = self.get_data('tasks') or {}
        tasks = {}
        for task_id, task_dict in raw_tasks.items():
            try:
                task = Task(
                    video_path=task_dict.get('video_path'),
                    task_id=task_dict.get('task_id'),
                    status=TaskStatus(task_dict.get('status')),
                    add_time=datetime.fromisoformat(task_dict.get('add_time')) if task_dict.get('add_time') else None,
                    complete_time=datetime.fromisoformat(task_dict.get('complete_time')) if task_dict.get(
                        'complete_time') else None,
                    tokens_used=task_dict.get('tokens_used', 0)
                )
                tasks[task_id] = task
            except Exception as e:
                logger.error(f"加载任务失败：{e}")
        return tasks

    def save_tasks(self):
        with self._tasks_lock:
            tasks_dict = {task_id: task.to_dict() for task_id, task in self._tasks.items()}
        self.save_data("tasks", tasks_dict)

    def add_task(self, video_file: str):
        task = Task(video_path=video_file, add_time=datetime.now())
        with self._tasks_lock:
            self._tasks[task.task_id] = task
        self._task_queue.put(task)
        self.save_tasks()
        logger.info(f"加入任务队列: {video_file}")

    def add_media_file(self, path: str):
        """
        添加新任务
        """
        if not self._shutdown_event.is_set():
            self.add_task(path)
        else:
            raise RuntimeError("Plugin is shutting down. Cannot add new tasks.")

    def __update_config(self):
        with self._config_updating_lock:
            self.update_config({'enabled': self._enabled,
                                'annot_level': self._annot_level,
                                'send_notify': self._send_notify,
                                'onlyonce': self._onlyonce,
                                'show_vocabulary_detail': self._show_vocabulary_detail,
                                'sentence_translation': self._sentence_translation,
                                'in_place': self._in_place,
                                'enable_gemini': self._enable_gemini,
                                'gemini_model': self._gemini_model,
                                'gemini_apikey': self._gemini_apikey,
                                'context_window': self._context_window,
                                'max_retries': self._max_retries,
                                'request_interval': self._request_interval,
                                'ffmpeg_path': self._ffmpeg_path,
                                'english_only': self._english_only,
                                'when_file_trans': self._when_file_trans,
                                'model_temperature': self._model_temperature,
                                'show_phonetics': self._show_phonetics,
                                'custom_files': self._custom_files,
                                'accent_color': self._accent_color,
                                'font_scaling': self._font_scaling,
                                'opacity': self._opacity,
                                'spacy_model': self._spacy_model,
                                'exam_tags': self._exam_tags,
                                'delete_data': self._delete_data,
                                'libraries': self._libraries
                                })

    def __process_tasks(self):
        """
        后台线程：处理任务队列
        """
        logger.debug("👷 Worker thread started.")

        self.__load_data()
        if not self._loaded:
            logger.warn('插件数据未加载')
            self._enabled = False
            self.__update_config()
            logger.debug("🛑 Worker exiting...")
            return
        if self._enable_gemini:
            self._gemini_available = True
            res = self.init_venv()
            if not res:
                self._gemini_available = False
            if not self._gemini_apikey:
                logger.warn(f"未提供GEMINI APIKEY")
                self._gemini_available = False
        with self._tasks_lock:
            for task_id, task in self._tasks.items():
                if task.status == TaskStatus.PENDING:
                    self._task_queue.put(task)
        while not self._shutdown_event.is_set():
            try:
                task = self._task_queue.get(timeout=1)
                if task is None:
                    continue
                tokens = self._total_token_count
                try:
                    task.status = TaskStatus.RUNNING
                    task.status = self.__process_file(task.video_path)
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    logger.error(f"处理 {task} 出错: {e}")
                finally:
                    self._task_queue.task_done()
                    task.complete_time = datetime.now()
                    task.tokens_used = self._total_token_count - tokens
                    self.save_tasks()
            except queue.Empty:
                continue
        logger.debug("🛑 Worker received shutdown signal, exiting...")

    def __process_file(self, path: str) -> TaskStatus:
        """
        处理视频文件
        """
        if not self._loaded:
            return TaskStatus.FAILED
        lexicon = self.__load_lexicon_from_local()
        if not lexicon:
            logger.error(f"字典加载失败")
            return TaskStatus.FAILED
        try:
            # 为减少内存占用，只在处理时加载 spaCy 模型
            nlp = LexiAnnot.__load_nlp(self._spacy_model)
            infixes = list(nlp.Defaults.infixes)
            infixes = [i for i in infixes if '-' not in i]
            # 使用修改后的正则表达式重新创建 tokenizer
            infix_re = spacy.util.compile_infix_regex(infixes)
            nlp.tokenizer = Tokenizer(
                nlp.vocab,
                prefix_search=nlp.tokenizer.prefix_search,
                suffix_search=nlp.tokenizer.suffix_search,
                infix_finditer=infix_re.finditer,
                token_match=nlp.tokenizer.token_match
            )
        except Exception as e:
            logger.error(f"spaCy 模型 {self._spacy_model} 加载失败: {e}")
            return TaskStatus.FAILED
        video = Path(path)
        if video.suffix.lower() not in settings.RMT_MEDIAEXT:
            return TaskStatus.CANCELED
        if not video.exists() or not video.is_file():
            logger.warn(f"文件 {str(video)} 不存在, 跳过")
            return TaskStatus.FAILED
        subtitle = video.with_suffix(".en.ass")
        if subtitle.exists():
            logger.warn(f"字幕文件 ({subtitle}) 已存在, 跳过")
            return TaskStatus.IGNORED
        logger.info(f"📂 Processing file: {path}")
        if self._send_notify:
            message = f"正在处理文件： {path}"
            self.post_message(title=f"【{self.plugin_name}】",
                              mtype=NotificationType.Plugin,
                              text=f"{message}")
        ffmpeg_path = self._ffmpeg_path if self._ffmpeg_path else 'ffmpeg'
        embedded_subtitles = LexiAnnot.__extract_subtitles_by_lang(path, 'en', ffmpeg_path)
        embedded_subtitles = sorted(embedded_subtitles, key=lambda track: 'SDH' in track['title'])
        ret_message = ''
        if embedded_subtitles:
            logger.info(f'提取到 {len(embedded_subtitles)} 条英语文本字幕')
            for embedded_subtitle in embedded_subtitles:
                if self._shutdown_event.is_set():
                    return TaskStatus.CANCELED
                ass_subtitle = pysubs2.SSAFile.from_string(embedded_subtitle['subtitle'], format_='ass')
                if embedded_subtitle.get('codec_id') == 'S_TEXT/UTF8':
                    ass_subtitle = LexiAnnot.set_srt_style(ass_subtitle)
                ass_subtitle = self.__set_style(ass_subtitle)
                ass_subtitle = self.process_subtitles(ass_subtitle, lexicon.get('cefr'), lexicon.get('coca20k'),
                                                      lexicon.get('examinations'),lexicon.get('swear_words'), nlp)
                if self._shutdown_event.is_set():
                    return TaskStatus.CANCELED
                if ass_subtitle:
                    try:
                        ass_subtitle.save(str(subtitle))
                        ret_message = f"字幕已保存：{str(subtitle)}"
                        logger.info(f"字幕已保存：{str(subtitle)}")
                    except Exception as e:
                        ret_message = f"字幕文件 {subtitle} 保存失败, {e}"
                        logger.error(f"字幕文件 {subtitle} 保存失败, {e}")
                    break
                else:
                    logger.info(f"处理字幕{embedded_subtitle['codec_id']}-{embedded_subtitle['stream_id']}失败")
        else:
            logger.warn(f"未能在{path}中找到可提取的英文字幕")
        if not ret_message:
            ret_message = f"未能在{path}中找到可提取的英文字幕"
        logger.info(f"✅ Finished: {path}")
        if self._send_notify:
            self.post_message(title=f"【{self.plugin_name}】",
                              mtype=NotificationType.Plugin,
                              text=f"{ret_message}")

        return TaskStatus.COMPLETED

    @cached(maxsize=1000, ttl=1800)
    def __load_lexicon_version(self) -> Optional[str]:
        logger.info(f"正在检查远程词典文件版本...")
        url = f'{self._lexicon_repo}master/version'
        version = RequestUtils().get(url, headers=settings.REPO_GITHUB_HEADERS())
        if version is None:
            return None
        return version.strip()

    @cached(maxsize=1, ttl=3600*6)
    def __load_lexicon_from_local(self) -> Optional[Dict[str, Any]]:
        data_path = self.get_data_path()
        lexicon = {}
        try:
            lexicon_path = data_path / 'lexicon.json'
            with open(lexicon_path, 'r', encoding='utf-8') as f:
                lexicon = json.load(f)
        except Exception as e:
            logger.debug(f"词典文件读取失败: {e}")
        lexicon_files = ('cefr', 'coca20k', 'swear_words', 'examinations', 'version')
        if any(file not in lexicon for file in lexicon_files):
            return None
        return lexicon

    @staticmethod
    @cached(maxsize=1, ttl=3600*6)
    def __load_nlp(model: str) -> spacy.Language:
        return spacy.load(model)

    def __retrieve_lexicon_online(self, version: str) -> Optional[Dict[str, Any]]:
        logger.info('开始下载词典文件...')
        lexicon_files = ['cefr', 'coca20k', 'swear_words', 'examinations']
        lexicon = {}
        for file in lexicon_files:
            url = f'{self._lexicon_repo}master/{file}.json'
            res = RequestUtils().get_res(url, headers=settings.REPO_GITHUB_HEADERS())
            if res.status_code == 200:
                lexicon[file] = res.json()
        if any(file not in lexicon for file in lexicon_files):
            return None
        logger.info(f"词典文件 (v{version}) 下载完成")
        data_path = self.get_data_path()
        lexicon['version'] = version
        try:
            lexicon_path = data_path / 'lexicon.json'
            with open(lexicon_path, 'w', encoding='utf-8') as f:
                json.dump(lexicon, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warn(f"词典文件保存失败: {e}")
        return lexicon

    def __load_data(self):
        """
        测试插件数据加载
        """
        try:
            logger.info(f"加载 spaCy 模型 {self._spacy_model}...")
            nlp = LexiAnnot.__load_nlp(self._spacy_model)
        except OSError:
            nlp = LexiAnnot.__load_spacy_model(self._spacy_model)
        lexicon = self.__load_lexicon_from_local()
        latest = self.__load_lexicon_version() or '0.0.0'
        if not lexicon or StringUtils.compare_version(lexicon.get('version'), '<', latest):
            lexicon = self.__retrieve_lexicon_online(latest)

        if not (nlp and lexicon):
            self._loaded = False
            logger.warn(f"插件数据加载失败")
        else:
            self._loaded = True
            logger.info(f"当前词典文件版本: {lexicon.get('version')}")

    @staticmethod
    def __load_spacy_model(model_name: str):
        try:
            logger.info(f"下载 spaCy 模型 {model_name}...")
            subprocess.run(
                [sys.executable, "-m", "spacy", "download", model_name],
                capture_output=True,
                text=True,
                check=True
            )
            nlp = LexiAnnot.__load_nlp(model_name)
            logger.info(f"spaCy 模型 '{model_name}' 加载成功！")
            return nlp
        except subprocess.CalledProcessError as e:
            logger.error(f"下载 spaCy 模型 '{model_name}' 失败。")
            logger.error(f"命令返回非零退出码：{e.returncode}")
            logger.error(f"Stdout:\n{e.stdout}")
            logger.error(f"Stderr:\n{e.stderr}")
            return None
        except Exception as e:
            logger.error(f"下载或加载 spaCy 模型时发生意外错误：{e}")
            return None

    @eventmanager.register(EventType.TransferComplete)
    def check_media(self, event: Event):
        if not self._enabled or not self._when_file_trans:
            return
        event_info: dict = event.event_data
        if not event_info:
            return

        # 入库数据
        transfer_info: TransferInfo = event_info.get("transferinfo")
        if not transfer_info or not transfer_info.target_diritem or not transfer_info.target_diritem.path:
            return

        # 检查是否为选择的媒体库
        in_libraries = False
        libraries = {library.name: library.library_path for library in DirectoryHelper().get_library_dirs()}
        for library_name in self._libraries:
            if library_name in libraries and Path(transfer_info.target_diritem.path).is_relative_to(
                    Path(libraries[library_name])):
                in_libraries = True
                break
        if not in_libraries:
            return

        mediainfo: MediaInfo = event_info.get("mediainfo")
        if self._english_only:
            if mediainfo.original_language and mediainfo.original_language != 'en':
                logger.info(f"原始语言 ({mediainfo.original_language}) 不为英语, 跳过 {mediainfo.title}： ")
                return
        for new_path in transfer_info.file_list_new:
            self.add_media_file(new_path)

    @staticmethod
    def query_cefr(word, cefr_lexicon):
        word = word.lower().strip("-*'")
        if word in cefr_lexicon:
            return cefr_lexicon[word]
        else:
            return None

    @staticmethod
    def query_coca20k(word: str, lexicon: Dict[str, Any]):
        word = word.lower().strip("-*'")
        return lexicon.get(word)

    @staticmethod
    def query_examinations(word: str, lexicon: Dict[str, Any]) -> Dict[str, Any]:
        res = {}
        for examination, exam_lexicon in lexicon.items():
            if word in exam_lexicon:
                res[examination] = exam_lexicon[word]
        return res

    @staticmethod
    def convert_pos_to_spacy(pos: str):
        """
        将给定的词性列表转换为 spaCy 库中使用的词性标签
        :param pos: 字符串形式词性
        :returns: 一个包含对应spaCy词性标签的列表。对于无法直接映射的词性，将返回None
        """
        spacy_pos_map = {
            'noun': 'NOUN',
            'adjective': 'ADJ',
            'adverb': 'ADV',
            'verb': 'VERB',
            'preposition': 'ADP',
            'conjunction': 'CCONJ',
            'determiner': 'DET',
            'pronoun': 'PRON',
            'interjection': 'INTJ',
            'number': 'NUM'
        }

        pos_lower = pos.lower()
        if pos_lower in spacy_pos_map:
            spacy_pos = spacy_pos_map[pos_lower]
        elif pos_lower == 'be-verb':
            spacy_pos = 'AUX'  # Auxiliary verb (e.g., be, do, have)
        elif pos_lower == 'vern':
            spacy_pos = 'VERB'  # Assuming 'vern' is a typo for 'verb'
        elif pos_lower == 'modal auxiliary':
            spacy_pos = 'AUX'  # Modal verbs are also auxiliaries
        elif pos_lower == 'do-verb':
            spacy_pos = 'AUX'
        elif pos_lower == 'have-verb':
            spacy_pos = 'AUX'
        elif pos_lower == 'infinitive-to':
            spacy_pos = 'PART'  # Particle (e.g., to in "to go")
        elif not pos_lower:  # Handle empty strings
            spacy_pos = None
        else:
            spacy_pos = None  # For unmapped POS tags
        return spacy_pos

    @staticmethod
    def get_cefr_by_spacy(lemma_: str, pos_: str, cefr_lexicon: Dict[str, Any]) -> Optional[str]:
        result = LexiAnnot.query_cefr(lemma_, cefr_lexicon)
        if result:
            all_cefr = []
            if len(result) > 0:
                for entry in result:
                    if pos_ == LexiAnnot.convert_pos_to_spacy(entry['pos']):
                        return entry['cefr']
                    all_cefr.append(entry['cefr'])
            return min(all_cefr)
        return None

    @staticmethod
    def format_duration(ms):
        total_seconds, milliseconds = divmod(ms, 1000)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        hundredths = milliseconds // 10
        return f"{hours}:{minutes:02}:{seconds:02}.{hundredths:02}"

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
            styles[style] = {'text': [], 'duration': 0, 'text_size': 0, 'times': 0}
        for dialogue in ass_file:
            style = dialogue.style
            text = dialogue.plaintext
            sub_text = text.split('\n')
            if style not in styles or not text: continue
            styles[style]['text'].extend(sub_text)
            styles[style]['duration'] += dialogue.duration
            styles[style]['text_size'] += len(text)
            styles[style]['times'] += 1
        style_language_analysis = {}
        for style_name, data in styles.items():
            all_text = ' '.join(data['text'])
            if not all_text.strip():
                style_language_analysis[style_name] = None
                continue

            languages = []
            # 对每个文本片段进行语言检测
            for text_fragment in data['text']:
                try:
                    lang = detect(text_fragment)
                    languages.append(lang)
                except:
                    pass  # 无法检测的文本

            if languages:
                language_counts = Counter(languages)
                most_common_language = language_counts.most_common(1)[0]
                style_language_analysis[style_name] = {"main_language": most_common_language[0],
                                                       "proportion": most_common_language[1] / len(languages),
                                                       "duration": data['duration'],
                                                       "text_size": data['text_size'],
                                                       "times": data['times']}
            else:
                style_language_analysis[style_name] = None

        return style_language_analysis

    @staticmethod
    def select_main_style_weighted(language_analysis: Dict[str, Any], known_language: str,
                                   weights=None):
        """
        根据语言分析结果和已知的字幕语言，使用加权评分选择主要样式
        :params language_analysis: `analyze_ass_language` 函数的输出结果
        :params known_language: 已知的字幕语言代码
        :params weights: 各个维度的权重，权重之和应为 1
        :returns: 主要字幕的样式名称，如果没有匹配的样式则返回 None
        """
        if weights is None:
            weights = {'times': 0.5, 'text_size': 0.4, 'duration': 0.1}
        matching_styles = []
        max_times = max([analysis.get('times', 0) for _, analysis in language_analysis.items() if analysis]) or 1
        max_text_size = max(
            [analysis.get('text_size', 0) for _, analysis in language_analysis.items() if analysis]) or 1
        max_duration = max([analysis.get('duration', 0) for _, analysis in language_analysis.items() if analysis]) or 1
        for style, analysis in language_analysis.items():
            if not analysis:
                continue
            if analysis.get('main_language') == known_language:
                # 跳过多语言
                if analysis.get('proportion', 0) < 0.5:
                    continue
                score = 0
                score += analysis.get('times', 0) * weights.get('times', 0) / max_times
                score += analysis.get('text_size', 0) * weights.get('text_size', 0) / max_text_size
                score += analysis.get('duration', 0) * weights.get('duration', 0) / max_duration
                matching_styles.append((style, score))

        if not matching_styles:
            return None

        sorted_styles = sorted(matching_styles, key=lambda item: item[1], reverse=True)
        return sorted_styles[0][0]

    @staticmethod
    def set_srt_style(ass: SSAFile) -> SSAFile:
        ass.info['ScaledBorderAndShadow'] = 'no'
        play_res_y = int(ass.info.get('PlayResY'))
        play_res_x = int(ass.info.get('PlayResX'))
        if 'Default' in ass.styles:
            ass.styles['Default'].marginv = play_res_y // 16
            ass.styles['Default'].fontname = 'Microsoft YaHei'
            ass.styles['Default'].fontsize = play_res_y // 16
        return ass

    def __set_style(self, ass: SSAFile) -> SSAFile:
        font_scaling = float(self._font_scaling) if self._font_scaling and len(self._font_scaling) else 1
        play_res_y = int(ass.info.get('PlayResY'))
        play_res_x = int(ass.info.get('PlayResX'))
        # 创建一个新样式
        fs = play_res_y // 16 * font_scaling
        new_style = pysubs2.SSAStyle()
        new_style.name = 'Annotation EN'
        new_style.fontname = 'Times New Roman'
        new_style.fontsize = fs
        new_style.primarycolor = pysubs2.Color(self._accent_color_rgb[0],
                                               self._accent_color_rgb[1],
                                               self._accent_color_rgb[2],
                                               self._color_alpha)  # 黄色 (BGR, alpha)
        new_style.bold = True
        new_style.italic = False
        new_style.outline = 1
        new_style.shadow = 0
        new_style.alignment = pysubs2.Alignment.TOP_LEFT
        new_style.marginl = play_res_x // 20
        new_style.marginr = play_res_x // 20
        new_style.marginv = fs
        ass.styles['Annotation EN'] = new_style
        zh_style = new_style.copy()
        zh_style.name = 'Annotation ZH'
        zh_style.fontname = 'Microsoft YaHei'
        zh_style.primarycolor = pysubs2.Color(255, 255, 255, self._color_alpha)
        ass.styles['Annotation ZH'] = zh_style

        pos_style = zh_style.copy()
        pos_style.name = 'Annotation POS'
        pos_style.fontname = 'Times New Roman'
        pos_style.fontsize = fs * 0.75
        pos_style.italic = True
        ass.styles['Annotation POS'] = pos_style

        phone_style = pos_style.copy()
        phone_style.name = 'Annotation PHONE'
        phone_style.fontname = 'Arial'
        phone_style.fontsize = fs * 0.75
        phone_style.bold = False
        phone_style.italic = False
        ass.styles['Annotation PHONE'] = phone_style

        pos_def_cn_style = zh_style.copy()
        pos_def_cn_style.name = 'DETAIL CN'
        pos_def_cn_style.fontsize = fs * 0.7
        ass.styles['DETAIL CN'] = pos_def_cn_style

        pos_def_pos_style = pos_style.copy()
        pos_def_pos_style.name = 'DETAIL POS'
        pos_def_pos_style.fontsize = fs * 0.6
        ass.styles['DETAIL POS'] = pos_def_pos_style

        cefr_style = pos_style.copy()
        cefr_style.name = "Annotation CEFR"
        cefr_style.fontname = "Times New Roman"
        cefr_style.fontsize = fs * 0.5
        cefr_style.bold = True
        cefr_style.italic = False
        cefr_style.primarycolor = pysubs2.Color(self._accent_color_rgb[0],
                                                self._accent_color_rgb[1],
                                                self._accent_color_rgb[2],
                                                self._color_alpha)
        cefr_style.outline = 1
        cefr_style.shadow = 0
        ass.styles['Annotation CEFR'] = cefr_style
        ass.styles['Annotation EXAM'] = cefr_style
        return ass

    @staticmethod
    def hex_to_rgb(hex_color) -> Optional[Tuple]:
        if not hex_color:
            return None
        pattern = r'^#[0-9a-fA-F]{6}$'
        if re.match(pattern, hex_color) is None:
            return None
        hex_color = hex_color.lstrip('#')  # 去掉前面的 #
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def __extract_subtitle(video_path: str,
                           subtitle_stream_index: str,
                           ffmpeg_path: str = 'ffmpeg',
                           sub_format='ass') -> Optional[str]:
        if sub_format not in ['srt', 'ass']:
            raise ValueError('Invalid subtitle format')
        try:
            map_parameter = f"0:s:{subtitle_stream_index}"
            command = [
                ffmpeg_path,
                '-i', video_path,
                '-map', map_parameter,
                '-f', sub_format,
                '-'
            ]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=True)
            return result.stdout
        except FileNotFoundError:
            logger.warn(f"错误：找不到视频文件 '{video_path}'")
            return None
        except subprocess.CalledProcessError as e:
            logger.warn(f"错误：提取字幕失败。\n错误信息：{e}")
            logger.warn(f"FFmpeg 输出 (stderr):\n{e.stderr.decode('utf-8', errors='ignore')}")
            return None

    @staticmethod
    def __extract_subtitles_by_lang(video_path: str, lang: str = 'en', ffmpeg: str = 'ffmpeg') -> Optional[List[Dict]]:
        """
        提取视频文件中的内嵌英文字幕，使用 MediaInfo 查找字幕流。
        """
        supported_codec = ['S_TEXT/UTF8', 'S_TEXT/ASS']
        subtitles = []
        try:
            media_info: pymediainfo.MediaInfo = pymediainfo.MediaInfo.parse(video_path)
            for track in media_info.tracks:
                if track.track_type == 'Text' and track.language == lang and track.codec_id in supported_codec:
                    subtitle_stream_index = track.stream_identifier  # MediaInfo 的 stream_id 从 1 开始，ffmpeg 从 0 开始
                    subtitle = LexiAnnot.__extract_subtitle(video_path, subtitle_stream_index, ffmpeg)
                    if subtitle:
                        subtitles.append({'title': track.title or '', 'subtitle': subtitle, 'codec_id': track.codec_id,
                                          'stream_id': subtitle_stream_index})
            if subtitles:
                return subtitles
            else:
                logger.warn('未找到标记为英语的文本字幕流')
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

    def init_venv(self) -> bool:
        venv_dir = os.path.join(self.get_data_path(), "venv_genai")
        python_path = os.path.join(venv_dir, "bin", "python") if os.name != "nt" else os.path.join(venv_dir, "Scripts",
                                                                                                   "python.exe")
        # 创建虚拟环境
        try:
            if not os.path.exists(venv_dir):
                logger.info(f"为 google-genai 初始化虚拟环境: {venv_dir}")
                venv.create(venv_dir, with_pip=True, symlinks=True, clear=True)
                logger.info(f"虚拟环境创建成功: {venv_dir}")
            SystemUtils.execute_with_subprocess([python_path, "-m", "pip", "install", 'google-genai'])
        except subprocess.CalledProcessError as e:
            logger.warn(f"虚拟环境创建失败: {e}")
            shutil.rmtree(venv_dir)
            return False
        self._venv_python = python_path

        return True

    def __query_gemini(
            self,
            tasks: List[T],
            task_type: Type[T],
            api_key: str,
            system_instruction: str,
            model: str,
            temperature: float
    ) -> List[T]:
        input_dict = {
            'tasks': [task.dict() for task in tasks],
            'params': {
                'api_key': api_key,
                'system_instruction': system_instruction,
                'schema': task_type.__name__,
                'model': model,
                'temperature': temperature,
                'max_retries': self._max_retries
            }
        }

        try:
            result = subprocess.run(
                [self._venv_python, self._query_gemini_script],
                input=json.dumps(input_dict),
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Subprocess failed: {str(e)}")
            return tasks

        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from subprocess:\n{result.stdout}")
            return tasks

        if not response.get("success"):
            logger.warning(f"Error in subprocess response: {response.get('message')}")
            return tasks

        try:
            self._total_token_count += response['data']['total_token_count'] or 0
            return [task_type(**task_data) for task_data in response["data"]["tasks"]]
        except Exception as e:
            logger.warning(f"Failed to reconstruct tasks: {str(e)}")
            return tasks

    def __process_by_ai(self, lines_to_process: List[Dict[str, Any]],
                        cefr_lexicon: Dict[str, Any],
                        coca20k_lexicon: Dict[str, Any],
                        exams_lexicon: Dict[str, Any],
                        swear_words: List[str],
                        nlp: spacy.Language):

        def __replace_with_spaces(_text):
            """
            使用等长的空格替换文本中的 [xxx] 模式。
            例如："[Hi]" 会被替换成 "    " (4个空格)
            """
            pattern = r'(\[.*?\])'
            return re.sub(pattern, lambda match: ' ' * len(match.group(1)), _text)

        simple_vocabulary = list(filter(lambda x: x < self._annot_level, ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']))
        patterns = [r'\d+th|\d?1st|\d?2nd|\d?3rd', r"\w+'s$", r"\w+'t$", "[Ii]'m$", r"\w+'re$", r"\w+'ve$", r"\w+'ll$"]
        compiled_patterns = [re.compile(p) for p in patterns]
        model_temperature = float(self._model_temperature) if self._model_temperature else 0.3
        logger.info(f"通过 spaCy 分词...")
        vocabulary_trans_instruction = '''You are an expert translator. You will be given a list of English words along with their context, formatted as JSON. For each entry, provide the most appropriate translation in Simplified Chinese based on the context.
    Only complete the `Chinese` field. Do not include pinyin, explanations, or any additional information.'''
        # 使用nlp分词
        for line_data in lines_to_process:
            if self._shutdown_event.is_set():
                return lines_to_process
            text_raw = line_data.get('raw_subtitle')
            text = text_raw.replace('\n', ' ')
            text = __replace_with_spaces(text)
            new_vocab = []
            doc = nlp(text)
            last_end_pos = 0
            lemma_to_query = []
            for token in doc:
                if len(token.text) == 1:
                    continue
                if token.lemma_ in swear_words:
                    continue
                if token.pos_ not in ('NOUN', 'AUX', 'VERB', 'ADJ', 'ADV', 'ADP', 'CCONJ', 'SCONJ'):
                    continue
                striped = token.lemma_.strip('-[')
                if any(p.match(striped) for p in compiled_patterns):
                    continue
                cefr = LexiAnnot.get_cefr_by_spacy(striped, token.pos_, cefr_lexicon)
                if cefr and cefr in simple_vocabulary:
                    continue
                res_of_coco = LexiAnnot.query_coca20k(striped, coca20k_lexicon)
                if res_of_coco and not cefr:
                    cefr = ''
                res_of_exams = self.query_examinations(striped, exams_lexicon)
                exam_tags = []
                if res_of_exams:
                    exam_tags = [exam_id for exam_id in res_of_exams if exam_id in self._exam_tags]
                if striped in lemma_to_query:
                    continue
                else:
                    lemma_to_query.append(striped)
                striped_text = token.text.strip('-*[')
                start_pos = text.find(striped_text, last_end_pos)
                end_pos = start_pos + len(striped_text)
                phonetics = ''
                pos_defs = []
                if res_of_exams:
                    for exam, value in res_of_exams.items():
                        phonetics = value.get('ipa_uk') or ''
                        defs = {}
                        for pos_def in value.get('defs', []):
                            pos = pos_def.get('pos', '')
                            definition_cn = pos_def.get('definition_cn', '')
                            defs.setdefault(pos, []).append(definition_cn)
                        pos_defs = [{'pos': pos, 'meanings': meanings} for pos, meanings in defs.items() if pos]
                        break
                elif res_of_coco:
                    phonetics = res_of_coco.get('phonetics_1') or ''
                    pos_defs = res_of_coco.get('pos_defs') or []
                last_end_pos = end_pos
                new_vocab.append({'start': start_pos, 'end': end_pos, 'text': striped_text, 'lemma': striped,
                                  'pos': token.pos_, 'cefr': cefr, 'Chinese': '', 'phonetics': phonetics,
                                  'pos_defs': pos_defs, 'exam_tags': exam_tags})
            line_data['new_vocab'] = new_vocab
        # 查询词汇翻译
        task_bulk: List[Union[VocabularyTranslationTask | DialogueTranslationTask]] = []
        i = 0
        if self._gemini_available:
            logger.info(f"查询词汇翻译...")
        for line_data in lines_to_process:
            if self._shutdown_event.is_set():
                return lines_to_process
            if not self._gemini_available:
                break
            i += 1
            if not (len(line_data["new_vocab"]) or (i == len(lines_to_process) and len(task_bulk))):
                continue
            new_vocab = [Vocabulary(lemma=new_vocab['lemma'], Chinese='') for new_vocab in line_data['new_vocab']]
            task_bulk.append(VocabularyTranslationTask(index=line_data['index'],
                                                       vocabulary=new_vocab,
                                                       context=Context(
                                                           original_text=line_data['raw_subtitle'].replace('\n', ' ')
                                                       )))
            if len(task_bulk) >= self._context_window or (len(task_bulk) and i == len(lines_to_process)):
                logger.info(f"processing dialogues: "
                            f"{LexiAnnot.format_duration(lines_to_process[task_bulk[0].index]['time_code'][0])} -> "
                            f"{LexiAnnot.format_duration(lines_to_process[i - 1]['time_code'][1])}")
                answer: Optional[List[VocabularyTranslationTask]] = self.__query_gemini(task_bulk,
                                                                                        VocabularyTranslationTask,
                                                                                        self._gemini_apikey,
                                                                                        vocabulary_trans_instruction,
                                                                                        self._gemini_model,
                                                                                        model_temperature)
                if not answer:
                    continue
                time.sleep(self._request_interval)
                for answer_line in answer:
                    answer_lemma = tuple(v.lemma for v in answer_line.vocabulary)
                    filtered_raw = [x for x in lines_to_process if x.get('index') == answer_line.index]
                    if not len(filtered_raw):
                        logger.warn(f'Unknown answer: {answer_line.index}: {answer_line.context.original_text}')
                    available_answer = False
                    for item in filtered_raw:
                        lemma = tuple(v['lemma'] for v in item['new_vocab'])
                        if lemma == answer_lemma:
                            available_answer = True
                            for i_, v in enumerate(item['new_vocab']):
                                v['Chinese'] = answer_line.vocabulary[i_].Chinese
                            break
                    if not available_answer:
                        logger.warn(f'Unknown answer: {answer_line.index}: {answer_line.context.original_text}')
                task_bulk = []
        if not self._sentence_translation:
            return lines_to_process
        if self._gemini_available:
            logger.info(f"查询整句翻译...")
        # 查询整句翻译
        translation_tasks: List[DialogueTranslationTask] = []
        for line_data in lines_to_process:
            translation_tasks.append(DialogueTranslationTask(index=line_data['index'],
                                                             original_text=line_data['raw_subtitle'].replace('\n', ' '),
                                                             Chinese=''))
        i = 0
        dialog_trans_instruction = '''You are an expert translator. You will be given a list of dialogue translation tasks in JSON format. For each entry, provide the most appropriate translation in Simplified Chinese based on the context. 
    Only complete the `Chinese` field. Do not include pinyin, explanations, or any additional information.'''
        while i < len(translation_tasks):
            if self._shutdown_event.is_set():
                return lines_to_process
            if not self._gemini_available:
                break
            start_index = max(0, i - 1)
            end_index = min(len(translation_tasks), i + self._context_window + 1)
            task_bulk: List[DialogueTranslationTask] = translation_tasks[start_index:end_index]
            logger.info(f"processing dialogues: "
                        f"{LexiAnnot.format_duration(lines_to_process[i]['time_code'][0])} -> "
                        f"{LexiAnnot.format_duration(lines_to_process[min(len(translation_tasks), i + self._context_window) - 1]['time_code'][1])}")
            answer: List[DialogueTranslationTask] = self.__query_gemini(task_bulk,
                                                                        DialogueTranslationTask,
                                                                        self._gemini_apikey,
                                                                        dialog_trans_instruction,
                                                                        self._gemini_model,
                                                                        model_temperature)
            time.sleep(self._request_interval)
            for answer_line in answer:
                if answer_line.index not in range(i, i + self._context_window):
                    continue
                filtered_raw = [x for x in lines_to_process if x.get('index') == answer_line.index]
                if not len(filtered_raw):
                    logger.warn(f'Unknown answer: {answer_line.index}: {answer_line.original_text}')
                available_answer = False
                for item in filtered_raw:
                    if item['raw_subtitle'].replace('\n', ' ') == answer_line.original_text:
                        available_answer = True
                        item['Chinese'] = answer_line.Chinese
                        break
                if not available_answer:
                    logger.warn(f'Unknown answer: {answer_line.index}: {answer_line.original_text}')
            i += self._context_window
        return lines_to_process

    def process_subtitles(self, ass_file: SSAFile,
                          cefr_lexicon: Dict[str, Any],
                          coca20k_lexicon: Dict[str, Any],
                          exams_lexicon: Dict[str, Any],
                          swear_words: List[str],
                          nlp: spacy.Language) -> Optional[SSAFile]:
        """
        处理字幕内容，标记词汇并添加翻译。
        """
        lang = 'en'
        abgr_str = (f'&H{self._color_alpha:02x}{self._accent_color_rgb[2]:02x}'
                    f'{self._accent_color_rgb[1]:02x}{self._accent_color_rgb[0]:02x}&')  # &H00FFFFFF&
        pos_map = {
            'NOUN': 'n.',
            'AUX': 'aux.',
            'VERB': 'v.',
            'ADJ': 'adj.',
            'ADV': 'adv.',
            'ADP': 'prep.',
            'CCONJ': 'conj.',
            'SCONJ': 'conj.'
        }
        statistical_res = LexiAnnot.analyze_ass_language(ass_file)
        main_style = LexiAnnot.select_main_style_weighted(statistical_res, lang)
        if not main_style:
            logger.error(f'无法确定主要字幕样式')
            return None
        index = 0
        lines_to_process = []
        main_dialogue: Dict[int, SSAEvent] = {}
        for dialogue in ass_file:
            if dialogue.style != main_style:
                continue
            time_code = (dialogue.start, dialogue.end)
            text_raw = dialogue.plaintext
            line_data = {'index': index, 'time_code': time_code, 'raw_subtitle': text_raw, 'new_vocab': [],
                         'Chinese': ''}
            lines_to_process.append(line_data)
            main_dialogue[index] = dialogue
            index += 1
        lines_to_process = self.__process_by_ai(lines_to_process, cefr_lexicon, coca20k_lexicon, exams_lexicon,
                                                swear_words, nlp)

        # 在原字幕添加标注
        main_style_fs = ass_file.styles[main_style].fontsize
        for line_data in lines_to_process:
            if self._shutdown_event.is_set():
                return None
            if line_data['new_vocab']:
                replacements = line_data['new_vocab']
                for replacement in replacements:
                    part_of_speech = f"{{\\fnTimes New Roman\\fs{int(main_style_fs * 0.75)}\\i1}}{pos_map[replacement['pos']]}{{\\r}}"
                    new_text = f"{{\\c{abgr_str}}}{replacement['text']}{{\\r}}"
                    if self._in_place:
                        new_text = new_text + f" ({replacement['Chinese']} {part_of_speech})" if replacement[
                            'Chinese'] else ""
                    else:
                        dialogue = pysubs2.SSAEvent()
                        dialogue.start = main_dialogue[line_data['index']].start
                        dialogue.end = main_dialogue[line_data['index']].end
                        dialogue.style = 'Annotation EN'
                        cefr_text = f" {{\\rAnnotation CEFR}}{replacement['cefr']}{{\\r}}" \
                            if replacement['cefr'] else ""
                        exam_text = f" {{\\rAnnotation EXAM}}{' '.join(replacement['exam_tags'])}{{\\r}}" \
                            if replacement['exam_tags'] else ""
                        __N = r'\N'
                        phone_text = f"{__N}{{\\rAnnotation PHONE}}/{replacement['phonetics']}/{{\\r}}" if replacement['phonetics'] and self._show_phonetics else ""
                        annot_text = f"{replacement['lemma']} {{\\rAnnotation POS}}{pos_map[replacement['pos']]}{{\\r}} {{\\rAnnotation ZH}}{replacement['Chinese']}{{\\r}}{cefr_text}{exam_text}{phone_text}"
                        dialogue.text = annot_text
                        ass_file.append(dialogue)
                        if self._show_vocabulary_detail and replacement['pos_defs']:
                            dialogue = pysubs2.SSAEvent()
                            dialogue.start = main_dialogue[line_data['index']].start
                            dialogue.end = main_dialogue[line_data['index']].end
                            dialogue.style = 'DETAIL CN'
                            detail_text = []
                            for pos_def in replacement['pos_defs']:
                                meaning_str = ', '.join(pos_def['meanings'])
                                pos_text = f"{{\\rDETAIL POS}}{pos_def['pos']}{{\\r}} {meaning_str}"
                                detail_text.append(pos_text)
                            dialogue.text = '\\N'.join(detail_text)
                            ass_file.append(dialogue)
                    replacement['new_text'] = new_text
                LexiAnnot.replace_by_plaintext_positions(main_dialogue[line_data['index']], replacements)
            if self._sentence_translation:
                chinese = line_data['Chinese']
                if chinese and chinese[-1] in ['。', '，']:
                    chinese = chinese[:-1]
                main_dialogue[line_data['index']].text = main_dialogue[line_data['index']].text + f"\\N{chinese}"
        return ass_file
