import os
import re
import sys
import json
import subprocess
import time
import threading
import queue
import shutil
from typing import Any, List, Dict, Tuple, Optional, Union,  Type, TypeVar
import venv
from pathlib import Path
from collections import Counter

from apscheduler.schedulers.background import BackgroundScheduler
import pysubs2
from pysubs2 import SSAFile, SSAEvent
import pymediainfo
from langdetect import detect

from app.core.config import settings
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

class LexiAnnot(_PluginBase):
    # 插件名称
    plugin_name = "美剧生词标注"
    # 插件描述
    plugin_desc = "根据CEFR等级，为英语影视剧标注高级词汇。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/wumode/LexiAnnot/refs/heads/master/LexiAnnot.png"
    # 插件版本
    plugin_version = "1.0.1"
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
    _gemini_model = False
    _gemini_apikey = ''
    _context_window = 0
    _max_retries = 0
    _request_interval = 0
    _ffmpeg_path = ''
    _english_only = False
    _when_file_trans = False
    _model_temperature = ''
    _custom_files = ''
    _accent_color = ''
    _font_scaling = ''
    _opacity = ''

    # 插件数据
    _lexicon_version = ''
    _swear_words = None
    _cefr_lexicon = None
    _coca2k_lexicon = None

    # protected variables
    _lexicon_repo = 'https://raw.githubusercontent.com/wumode/LexiAnnot/'
    _spacy_model_name = "en_core_web_sm"
    _scheduler: Optional[BackgroundScheduler] = None
    _nlp = None
    _worker_thread = None
    _task_queue = None
    _shutdown_event = None
    _client = None
    _total_token_count = 0
    _venv_python = None
    _query_gemini_script = ''
    _gemini_available = False
    _accent_color_rgb = None
    _color_alpha = 0

    def init_plugin(self, config=None):
        self._task_queue = queue.Queue()
        self.stop_service()
        if config:
            self._enabled = config.get("enabled")
            self._annot_level = config.get("annot_level")
            self._send_notify = config.get("send_notify")
            self._onlyonce = config.get("onlyonce")
            self._show_vocabulary_detail = config.get("show_vocabulary_detail")
            self._sentence_translation = config.get("sentence_translation")
            self._in_place = config.get("in_place")
            self._enable_gemini = config.get("enable_gemini")
            self._gemini_model = config.get("gemini_model")
            self._gemini_apikey = config.get("gemini_apikey")
            self._context_window = config.get("context_window")
            self._max_retries = config.get("max_retries")
            self._request_interval = config.get("request_interval")
            self._ffmpeg_path = config.get("ffmpeg_path")
            self._english_only = config.get("english_only")
            self._when_file_trans = config.get("when_file_trans")
            self._model_temperature = config.get("model_temperature")
            self._show_phonetics = config.get("show_phonetics")
            self._custom_files = config.get("custom_files")
            self._accent_color = config.get("accent_color")
            self._font_scaling = config.get("font_scaling")
            self._opacity = config.get("opacity")

            self._accent_color_rgb = LexiAnnot.hex_to_rgb(self._accent_color) or (255, 255, 0)
            self._color_alpha = int(self._opacity) if self._opacity and len(self._opacity) else 0
        if self._enabled:
            self._query_gemini_script = f"{settings.ROOT_PATH}/app/plugins/lexiannot/query_gemini.py"
            self._cefr_lexicon = self.get_data("cefr_lexicon")
            self._coca2k_lexicon = self.get_data("coca2k_lexicon")
            self._swear_words = self.get_data("swear_words")
            self._lexicon_version = self.get_data("lexicon_version")
            latest = self.__load_lexicon_version()
            if not self._lexicon_version or StringUtils.compare_version(self._lexicon_version, '<', latest):
                self.__load_lexicon()
            # try to import spaCy
            try:
                import spacy
            except ModuleNotFoundError:
                logger.info('正在安装spaCy ...')
                result, output = SystemUtils.execute_with_subprocess(
                    [sys.executable, "-m", "pip", "install", 'thinc==8.3.4']
                )
                if not result:
                    logger.error(f"无法安装spaCy, {output}")
                    return
                result, output = SystemUtils.execute_with_subprocess(
                    [sys.executable, "-m", "pip", "install", 'spacy==3.8.7']
                )
                if not result:
                    logger.error(f"无法安装spaCy, {output}")
                    return
            try:
                import spacy
                from spacy.util import compile_infix_regex
                from spacy.tokenizer import Tokenizer
                if self._nlp is None:
                    self._nlp = spacy.load(self._spacy_model_name)
                    infixes = list(self._nlp.Defaults.infixes)
                    infixes = [i for i in infixes if '-' not in i]
                    # 使用修改后的正则表达式重新创建 tokenizer
                    infix_re = compile_infix_regex(infixes)
                    self._nlp.tokenizer = Tokenizer(
                        self._nlp.vocab,
                        prefix_search=self._nlp.tokenizer.prefix_search,
                        suffix_search=self._nlp.tokenizer.suffix_search,
                        infix_finditer=infix_re.finditer,
                        token_match=self._nlp.tokenizer.token_match
                    )
            except OSError:
                self._nlp = LexiAnnot.__load_spacy_model(self._spacy_model_name)
            if not (self._nlp and self._cefr_lexicon and self._coca2k_lexicon and self._swear_words):
                _loaded = False
            else:
                _loaded = True
            if not _loaded:
                logger.warn(f"插件数据未加载,初始化失败")
                self._enabled = False
                self.__update_config()
                return
            if self._enable_gemini:
                self._gemini_available = True
                res = self.init_venv()
                if not res:
                    self._gemini_available = False
                if not self._gemini_apikey:
                    logger.warn(f"未提供GEMINI APIKEY")
                    self._gemini_available = False
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
                                            'label': '立即运行一次',
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
                                    'md': 3
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
                                    'md': 3
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
                                    'md': 3,
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
                                    'md': 3
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
                                    'md': 3
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
                                    'md': 3
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
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'english_only',
                                            'label': '仅英语影视剧',
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
                                            'model': 'show_vocabulary_detail',
                                            'label': '显示完整释义',
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
                                                {'title': 'gemini-2.5-flash-preview-05-20',
                                                 'value': 'gemini-2.5-flash-preview-05-20'},
                                                {'title': 'gemini-2.5-pro-preview-05-06',
                                                 'value': 'gemini-2.5-pro-preview-05-06'},
                                                {'title': 'gemini-2.0-flash', 'value': 'gemini-2.0-flash'},
                                                {'title': 'gemini-2.0-flash-lite', 'value': 'gemini-2.0-flash-lite'},
                                                {'title': 'gemini-1.5-flash', 'value': 'gemini-1.5-flash'},
                                                {'title': 'gemini-1.5-pro', 'value': 'gemini-1.5-pro'}
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
                                            'placeholder': 5    ,
                                            'min': 1,
                                            'suffix': '秒',
                                            'hint': '请求间隔时间，建议不少于3秒'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'custom_files',
                                            'label': '视频路径',
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
                                            }]
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
        }

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_page(self) -> List[dict]:
        pass

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
        self.shutdown()

    def shutdown(self):
        """
        关闭插件
        """
        if self._worker_thread and self._worker_thread.is_alive():
            logger.debug("🔻 Stopping existing worker thread...")
            self._shutdown_event.set()
            self._worker_thread.join()
            logger.debug("✅ Existing worker thread stopped.")
        else:
            logger.debug("ℹ️ No running worker thread to stop.")

    def add_media_file(self, path: str):
        """
        添加新任务
        """
        if not self._shutdown_event.is_set():
            self._task_queue.put(path)
        else:
            raise RuntimeError("Plugin is shutting down. Cannot add new tasks.")

    def __update_config(self):
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
                            'opacity': self._opacity
                            })

    def __process_tasks(self):
        """
        后台线程：处理任务队列
        """
        logger.debug("👷 Worker thread started.")
        while not self._shutdown_event.is_set():
            try:
                task = self._task_queue.get(timeout=1)  # 最多等待1秒
                if task is None:
                    continue
                self.__process_file(task)
            except queue.Empty:
                continue
        logger.debug("🛑 Worker received shutdown signal, exiting...")

    def __process_file(self, path: str):
        """
        处理视频文件
        """
        video = Path(path)
        if video.suffix.lower() not in settings.RMT_MEDIAEXT:
            return
        if not video.exists() or not video.is_file():
            logger.warn(f"文件 {str(video)} 不存在, 跳过")
            return
        subtitle = video.with_suffix(".ass")
        if subtitle.exists():
            logger.warn(f"字幕文件 ({subtitle}) 已存在, 跳过")
            return
        logger.info(f"📂 Processing file: {path}")
        if self._send_notify:
            message = f"正在处理文件： {path}"
            self.post_message(title=f"【{self.plugin_name}】",
                              mtype=NotificationType.Plugin,
                              text=f"{message}")
        ffmpeg_path = self._ffmpeg_path if self._ffmpeg_path else 'ffmpeg'
        embedded_subtitles = LexiAnnot.__extract_subtitles_by_lang(path, 'en', ffmpeg_path)
        ret_message = ''
        if embedded_subtitles:
            logger.info(f'提取到 {len(embedded_subtitles)} 条英语文本字幕')
            for embedded_subtitle in embedded_subtitles:
                if self._shutdown_event.is_set():
                    return
                ass_subtitle = pysubs2.SSAFile.from_string(embedded_subtitle['subtitle'], format_='ass')
                if embedded_subtitle.get('codec_id') == 'S_TEXT/UTF8':
                    ass_subtitle = LexiAnnot.set_srt_style(ass_subtitle)
                ass_subtitle = self.__set_style(ass_subtitle)
                ass_subtitle = self.process_subtitles(ass_subtitle)
                if self._shutdown_event.is_set():
                    return
                if ass_subtitle:
                    try:
                        ass_subtitle.save(str(subtitle))
                        ret_message = f"字幕已保存：{str(subtitle)}"
                    except Exception as e:
                        logger.error(f"字幕文件 {subtitle} 保存失败, {e}")
                    break
                else:
                    logger.info(f"处理字幕{embedded_subtitle['codec_id']}-{embedded_subtitle['stream_id']}失败")
        else:
            logger.warn(f"未能在{path}中找到可提取的英文字幕")
        if not ret_message:
            ret_message= f"未能在{path}中找到可提取的英文字幕"
        logger.info(f"✅ Finished: {path}")
        if self._send_notify:
            self.post_message(title=f"【{self.plugin_name}】",
                              mtype=NotificationType.Plugin,
                              text=f"{ret_message}")

    @cached(maxsize=1000, ttl=1800)
    def __load_lexicon_version(self) -> Optional[str]:
        logger.info(f"正在检查远程词库版本...")
        url = f'{self._lexicon_repo}master/version'
        version = RequestUtils().get(url, headers=settings.REPO_GITHUB_HEADERS())
        if version is None:
            return None
        return version

    def __load_lexicon(self):
        url = f'{self._lexicon_repo}master/cefr.json'
        res = RequestUtils().get_res(url, headers=settings.REPO_GITHUB_HEADERS())
        if res:
            self._cefr_lexicon = res.json()
        url = f'{self._lexicon_repo}master/coca20k.json'
        res = RequestUtils().get_res(url, headers=settings.REPO_GITHUB_HEADERS())
        if res:
            self._coca2k_lexicon = res.json()
        url = f'{self._lexicon_repo}master/swear_words.json'
        res = RequestUtils().get_res(url, headers=settings.REPO_GITHUB_HEADERS())
        if res:
            self._swear_words = res.json()
        self._lexicon_version = self.__load_lexicon_version()
        self.save_data("cefr_lexicon", self._cefr_lexicon)
        self.save_data("coca2k_lexicon", self._coca2k_lexicon)
        self.save_data("swear_words", self._swear_words)
        self.save_data("lexicon_version", self._lexicon_version)

    @staticmethod
    def __load_spacy_model(model_name: str):
        try:
            import spacy
            result = subprocess.run(
                [sys.executable, "-m", "spacy", "download", model_name],
                capture_output=True,
                text=True,
                check=True
            )
            nlp = spacy.load(model_name)
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
        mediainfo: MediaInfo = event_info.get("mediainfo")
        if self._english_only:
            if mediainfo.original_language != 'en':
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
    def convert_pos_to_spacy(pos: str):
        """
        将给定的词性列表转换为spaCy库中使用的词性标签。

        Args:
          pos: 一个字符串形式词性。

        Returns:
          一个包含对应spaCy词性标签的列表。对于无法直接映射的词性，
          将返回None。
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
        替换 line.text 中的内容，使用 replacements 中的 plaintext 位置信息。
        replacement
        {'start': int, 'end': int, 'old_text': str, 'new_text': str}
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
            end += 1  # 因为 Python 切片不包含结束索引
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
        根据语言分析结果和已知的字幕语言，使用加权评分选择主要样式。

        Args:
            language_analysis (dict): `analyze_ass_language` 函数的输出结果。
            known_language (str): 已知的字幕语言代码.
            weights (dict): 各个维度的权重，权重之和应为 1.

        Returns:
            str or None: 主要字幕的样式名称，如果没有匹配的样式则返回 None。
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
        fs = play_res_y // 16*font_scaling
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
                           ffmpeg_path: str='ffmpeg',
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
        """提取视频文件中的内嵌英文字幕，使用 MediaInfo 查找字幕流。"""
        supported_codec = ['S_TEXT/UTF8', 'S_TEXT/ASS']
        subtitles = []
        try:
            media_info: pymediainfo.MediaInfo = pymediainfo.MediaInfo.parse(video_path)
            for track in media_info.tracks:
                if track.track_type == 'Text' and track.language == lang and track.codec_id in supported_codec:
                    if track.title and 'SDH' in track.title:
                        continue
                    subtitle_stream_index = track.stream_identifier  # MediaInfo 的 stream_id 从 1 开始，ffmpeg 从 0 开始
                    subtitle = LexiAnnot.__extract_subtitle(video_path, subtitle_stream_index, ffmpeg)
                    if subtitle:
                        subtitles.append({'title': track.title, 'subtitle': subtitle, 'codec_id': track.codec_id,
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
            logger.error(f"FFmpeg 输出 (stderr):\n{e.stderr.decode('utf-8', errors='ignore')}")
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
        except subprocess.CalledProcessError:
            logger.warn(f"虚拟环境创建失败")
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
            'tasks': [task.dict() for task in tasks],  # 保证是可序列化格式
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
            return [task_type(**task_data) for task_data in response["data"]["tasks"]]
        except Exception as e:
            logger.warning(f"Failed to reconstruct tasks: {str(e)}")
            return tasks

    def __process_by_ai(self, lines_to_process: List[Dict[str, Any]], cefr_lexicon, swear_words, coca20k_lexicon):
        simple_vocabulary = list(filter(lambda x:x<self._annot_level, ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']))
        patterns = [r'\d+th|\d?1st|\d?2nd']
        compiled_patterns = [re.compile(p) for p in patterns]
        model_temperature = float(self._model_temperature) if self._model_temperature else 0.3
        logger.info(f"通过spaCy分词...")
        vocabulary_trans_instruction = '''You are an expert translator. You will be given a list of English words along with their context, formatted as JSON. For each entry, provide the most appropriate translation in Simplified Chinese based on the context.
    Only complete the `Chinese` field. Do not include pinyin, explanations, or any additional information.'''
        # 使用nlp分词
        for line_data in lines_to_process:
            if self._shutdown_event.is_set():
                return lines_to_process
            text_raw = line_data.get('raw_subtitle')
            text = text_raw.replace('\n', ' ')
            new_vocab = []
            doc = self._nlp(text)
            last_end_pos = 0
            lemma_to_query = []
            for token in doc:
                if len(token.text) == 1:
                    continue
                if token.lemma_ in swear_words:
                    continue
                if token.pos_ not in ('NOUN', 'AUX', 'VERB', 'ADJ', 'ADV', 'ADP', 'CCONJ', 'SCONJ'):
                    continue
                if any(p.match(token.lemma_) for p in compiled_patterns):
                    continue
                cefr = LexiAnnot.get_cefr_by_spacy(token.lemma_, token.pos_, cefr_lexicon)
                if cefr and cefr in simple_vocabulary:
                    continue
                res_of_coco = LexiAnnot.query_coca20k(token.lemma_, coca20k_lexicon)
                if res_of_coco and not cefr:
                    cefr = 'COCA20K'
                if token.lemma_ in lemma_to_query:
                    continue
                else:
                    lemma_to_query.append(token.lemma_)
                start_pos = text.find(token.text, last_end_pos)
                end_pos = start_pos + len(token.text)
                phonetics = ''
                pos_defs = []
                if res_of_coco:
                    phonetics = res_of_coco.get('phonetics_1') or ''
                    pos_defs = res_of_coco.get('pos_defs') or []
                last_end_pos = end_pos
                new_vocab.append({'start': start_pos, 'end': end_pos, 'text': token.text, 'lemma': token.lemma_,
                                  'pos': token.pos_, 'cefr': cefr, 'Chinese': '', 'phonetics': phonetics,
                                  'pos_defs': pos_defs})
            line_data['new_vocab'] = new_vocab
        # 查询词汇翻译
        task_bulk: List[Union[VocabularyTranslationTask|DialogueTranslationTask]] = []
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
            f"{LexiAnnot.format_duration(lines_to_process[min(len(translation_tasks), i + self._context_window)-1]['time_code'][1])}")
            answer: List[DialogueTranslationTask] = self.__query_gemini(task_bulk,
                                                                        DialogueTranslationTask,
                                                                        self._gemini_apikey,
                                                                        dialog_trans_instruction,
                                                                        self._gemini_model,
                                                                        model_temperature)
            time.sleep(self._request_interval)
            for answer_line in answer:
                if  answer_line.index not in range(i, i+self._context_window):
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

    def process_subtitles(self, ass_file: SSAFile) -> Optional[SSAFile]:
        """
        处理字幕内容，标记词汇并添加翻译。
        """
        lang = 'en'
        cefr_lexicon = self._cefr_lexicon
        swear_words = self._swear_words
        coca20k_lexicon = self._coca2k_lexicon
        abgr_str = (f'&H{self._color_alpha:02x}{self._accent_color_rgb[2]:02x}'
                                 f'{self._accent_color_rgb[1]:02x}{self._accent_color_rgb[0]:02x}&') #&H00FFFFFF&
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
        lines_to_process = self.__process_by_ai(lines_to_process, cefr_lexicon, swear_words, coca20k_lexicon)

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
                        cefr_text = f" {{\\rAnnotation CEFR}}{replacement['cefr']}{{\\r}}" if replacement[
                            'cefr'] else ""
                        __N = r'\N'
                        phone_text = f"{__N}{{\\rAnnotation PHONE}}/{replacement['phonetics']}/{{\\r}}" if replacement[
                                                                                                               'phonetics'] and self._show_phonetics else ""
                        annot_text = f"{replacement['lemma']} {{\\rAnnotation POS}}{pos_map[replacement['pos']]}{{\\r}} {{\\rAnnotation ZH}}{replacement['Chinese']}{{\\r}}{cefr_text}{phone_text}"
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

