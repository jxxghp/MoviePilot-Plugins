import copy
import os
import re
import subprocess
import tempfile
import time
import traceback
from datetime import timedelta, datetime
from pathlib import Path
from typing import Tuple, Dict, Any, List
from threading import Event
import iso639
import psutil
import pytz
import srt
from apscheduler.schedulers.background import BackgroundScheduler
from lxml import etree

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.utils.system import SystemUtils
from plugins.autosubv2.ffmpeg import Ffmpeg
from plugins.autosubv2.translate.openai import OpenAi
from app.schemas.types import NotificationType


# todo
# 监听入库事件，自动调用翻译

class UserInterruptException(Exception):
    """用户中断当前任务的异常"""
    pass

class AutoSubv2(_PluginBase):
    # 插件名称
    plugin_name = "AI字幕自动生成(v2)"
    # 插件描述
    plugin_desc = "使用whisper自动生成视频文件字幕,使用大模型翻译字幕成中文。"
    # 插件图标
    plugin_icon = "autosubtitles.jpeg"
    # 主题色
    plugin_color = "#2C4F7E"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "TimoYoung"
    # 作者主页
    author_url = "https://github.com/TimoYoung"
    # 插件配置项ID前缀
    plugin_config_prefix = "autosubv2"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 2

    # 退出事件
    _event = Event()
    # 私有属性
    _running = False
    # 语句结束符
    _end_token = ['.', '!', '?', '。', '！', '？', '。"', '！"', '？"', '."', '!"', '?"']
    _noisy_token = [('(', ')'), ('[', ']'), ('{', '}'), ('【', '】'), ('♪', '♪'), ('♫', '♫'), ('♪♪', '♪♪')]

    def __init__(self):
        super().__init__()
        # ChatGPT
        self.openai = None
        self._openai_key = None
        self._openai_url = None
        self._openai_proxy = None
        self._openai_model = None
        self._scheduler = None
        self.process_count = None
        self.fail_count = None
        self.success_count = None
        self.skip_count = None
        self.faster_whisper_model_path = None
        self.faster_whisper_model = None
        self.asr_engine = None
        self.send_notify = None
        self.additional_args = None
        self.enable_asr = None
        self.translate_zh = None
        self.whisper_model = None
        self.whisper_main = None
        self.file_size = None
        self.enable_batch = None
        self.batch_size = None
        self.context_window = None
        self.max_retries = None
        self._proxy = None
        self._translate_preference = None

    def init_plugin(self, config=None):

        self.process_count = 0
        self.skip_count = 0
        self.fail_count = 0
        self.success_count = 0

        # 如果没有配置信息， 则不处理
        if not config:
            return

        self.translate_zh = config.get('translate_zh', False)
        if self.translate_zh:
            chatgpt = self.get_config("ChatGPT")
            if not chatgpt:
                logger.error(f"翻译依赖于ChatGPT，请先维护ChatGPT插件")
                return
            self._openai_key = chatgpt and chatgpt.get("openai_key")
            self._openai_url = chatgpt and chatgpt.get("openai_url")
            self._openai_proxy = chatgpt and chatgpt.get("proxy")
            self._openai_model = chatgpt and chatgpt.get("model")
            if not self._openai_key:
                logger.error(f"翻译依赖于ChatGPT，请先维护openai_key")
                return
            self.openai = OpenAi(api_key=self._openai_key, api_url=self._openai_url,
                                 proxy=settings.PROXY if self._openai_proxy else None,
                                 model=self._openai_model)

        path_list = list(set(config.get('path_list').split('\n')))
        self.file_size = int(config.get('file_size')) if config.get('file_size') else 10
        self.whisper_main = config.get('whisper_main')
        self.whisper_model = config.get('whisper_model')
        self.enable_asr = config.get('enable_asr', True)
        self.enable_batch = config.get('enable_batch', True)
        self.batch_size = int(config.get('batch_size')) if config.get('batch_size') else 20
        self.context_window = int(config.get('context_window')) if config.get('context_window') else 5
        self.max_retries = int(config.get('max_retries')) if config.get('max_retries') else 3
        self.additional_args = config.get('additional_args', '-t 4 -p 1')
        self.send_notify = config.get('send_notify', False)
        self.asr_engine = config.get('asr_engine', 'faster_whisper')
        self.faster_whisper_model = config.get('faster_whisper_model', 'base')
        self.faster_whisper_model_path = config.get('faster_whisper_model_path',
                                                    self.get_data_path() / "faster-whisper-models")
        self._proxy = config.get('proxy', False)
        self._translate_preference = config.get('translate_preference', 'origin_first')
        run_now = config.get('run_now')
        self.stop_service()

        if not run_now:
            return

        config['run_now'] = False
        self.update_config(config)
        # 如果没有配置信息， 则不处理
        if not path_list or not self.file_size:
            logger.warn(f"配置信息不完整，不进行处理")
            return

        # asr 配置检查
        if self.enable_asr and not self.__check_asr():
            return

        if self._running:
            logger.warn(f"上一次任务还未完成，不进行处理")
            return

        if run_now:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("AI字幕自动生成任务，立即运行一次")
            self._scheduler.add_job(func=self._do_autosub, kwargs={'path_list': path_list}, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="AI字幕自动生成")

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def _do_autosub(self, path_list: str):
        # 依次处理每个目录
        try:
            self._running = True
            self.success_count = self.skip_count = self.fail_count = self.process_count = 0
            for path in path_list:
                if self._event.is_set():
                    logger.info(f"字幕生成服务停止")
                    return
                logger.info(f"开始处理目录/文件：{path} ...")
                # 如果目录不存在， 则不处理
                if not os.path.exists(path):
                    logger.warn(f"目录/文件不存在，不进行处理")
                    continue

                # 如果目录不是绝对路径， 则不处理
                if not os.path.isabs(path):
                    logger.warn(f"目录/文件不是绝对路径，不进行处理")
                    continue

                if os.path.isdir(path):
                    # 处理目录
                    self.__process_folder_subtitle(path)
                elif os.path.splitext(path)[-1].lower() in settings.RMT_MEDIAEXT:
                    # 处理单个视频文件
                    self.__process_file_subtitle(path)
                # 如果目录不是文件夹， 则不处理
                else:
                    logger.warn(f"目录不是文件夹或视频文件，不进行处理")
                    continue

        except Exception as e:
            logger.error(f"处理异常: {e}")
            logger.error(traceback.format_exc())
        finally:
            logger.info(f"处理完成: "
                        f"成功{self.success_count} / 跳过{self.skip_count} / 失败{self.fail_count} / 共{self.process_count}")
            self._running = False

    def __check_asr(self):
        if self.asr_engine == 'whisper.cpp':
            if not self.whisper_main or not self.whisper_model:
                logger.warn(f"配置信息不完整，不进行处理")
                return False
            if not os.path.exists(self.whisper_main):
                logger.warn(f"whisper.cpp主程序不存在，不进行处理")
                return False
            if not os.path.exists(self.whisper_model):
                logger.warn(f"whisper.cpp模型文件不存在，不进行处理")
                return False
            # 校验扩展参数是否包含异常字符
            if self.additional_args and re.search(r'[;|&]', self.additional_args):
                logger.warn(f"扩展参数包含异常字符，不进行处理")
                return False
        elif self.asr_engine == 'faster-whisper':
            if not self.faster_whisper_model_path or not self.faster_whisper_model:
                logger.warn(f"配置信息不完整，不进行处理")
                return False
            if not os.path.exists(self.faster_whisper_model_path):
                logger.info(f"创建faster-whisper模型目录：{self.faster_whisper_model_path}")
                os.mkdir(self.faster_whisper_model_path)
            try:
                from faster_whisper import WhisperModel, download_model
            except ImportError:
                logger.warn(f"faster-whisper 未安装，不进行处理")
                return False
            return True
        else:
            logger.warn(f"未配置asr引擎，不进行处理")
            return False
        return True

    def __process_file_subtitle(self, video_file):
        if not video_file:
            return
        # 如果文件大小小于指定大小， 则不处理
        if os.path.getsize(video_file) < self.file_size:
            return

        self.process_count += 1
        start_time = time.time()
        file_path, file_ext = os.path.splitext(video_file)
        file_name = os.path.basename(video_file)

        try:
            logger.info(f"开始处理文件：{video_file} ...")
            # 判断目的字幕（和内嵌）是否已存在
            if self.__target_subtitle_exists(video_file):
                logger.warn(f"字幕文件已经存在，不进行处理")
                self.skip_count += 1
                return
            # 生成字幕
            ret, lang, gen_sub_path = self.__generate_subtitle(video_file, file_path, self.enable_asr)
            if not ret:
                message = f" 媒体: {file_name}\n "
                if not self.enable_asr:
                    message += "内嵌&外挂字幕不存在，不进行翻译"
                    self.skip_count += 1
                else:
                    message += "生成字幕失败，跳过后续处理"
                    self.fail_count += 1

                if self.send_notify:
                    self.post_message(mtype=NotificationType.Plugin, title="【自动字幕生成】", text=message)
                return

            if self.translate_zh:
                # 翻译字幕
                logger.info(f"开始翻译字幕为中文 ...")
                # self.__translate_zh_subtitle(lang, f"{file_path}.{lang}.srt", f"{file_path}.zh.机翻.srt")
                self.__translate_zh_subtitle(lang, gen_sub_path, f"{file_path}.zh.机翻.srt")
                logger.info(f"翻译字幕完成：{file_name}.zh.机翻.srt")

            end_time = time.time()
            message = f" 媒体: {file_name}\n 处理完成\n 字幕原始语言: {lang}\n "
            if self.translate_zh:
                message += f"字幕翻译语言: zh\n "
            message += f"耗时：{round(end_time - start_time, 2)}秒"
            logger.info(f"自动字幕生成 处理完成：{message}")
            if self.send_notify:
                self.post_message(mtype=NotificationType.Plugin, title="【自动字幕生成】", text=message)
            self.success_count += 1
        except UserInterruptException:
            logger.info(f"用户中断当前任务：{video_file}")
            self.fail_count += 1
        except Exception as e:
            logger.error(f"自动字幕生成 处理异常：{e}")
            end_time = time.time()
            message = f" 媒体: {file_name}\n 处理失败\n 耗时：{round(end_time - start_time, 2)}秒"
            if self.send_notify:
                self.post_message(mtype=NotificationType.Plugin, title="【自动字幕生成】", text=message)
            # 打印调用栈
            logger.error(traceback.format_exc())
            self.fail_count += 1

    def __process_folder_subtitle(self, path):
        """
        处理目录字幕
        :param path:
        :return:
        """
        # 获取目录媒体文件列表
        for video_file in self.__get_library_files(path):
            if self._event.is_set():
                logger.info(f"{video_file}处理中止")
                return
            self.__process_file_subtitle(video_file)

    def __do_speech_recognition(self, audio_lang, audio_file):
        """
        语音识别, 生成字幕
        :param audio_lang:
        :param audio_file:
        :return:
        """
        lang = audio_lang
        if self.asr_engine == 'whisper.cpp':
            command = [self.whisper_main] + self.additional_args.split()
            command += ['-l', lang, '-m', self.whisper_model, '-osrt', '-of', audio_file, audio_file]
            ret = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if ret.returncode == 0:
                if lang == 'auto':
                    # 从output中获取语言 "whisper_full_with_state: auto-detected language: en (p = 0.973642)"
                    output = ret.stdout.decode('utf-8') if ret.stdout else ""
                    lang = re.search(r"auto-detected language: (\w+)", output)
                    if lang and lang.group(1):
                        lang = lang.group(1)
                    else:
                        lang = "en"
                return True, lang
        elif self.asr_engine == 'faster-whisper':
            try:
                from faster_whisper import WhisperModel, download_model
                # 设置缓存目录, 防止缓存同目录出现 cross-device 错误
                cache_dir = os.path.join(self.faster_whisper_model_path, "cache")
                if not os.path.exists(cache_dir):
                    os.mkdir(cache_dir)
                os.environ["HF_HUB_CACHE"] = cache_dir
                if self._proxy:
                    os.environ["HTTP_PROXY"] = settings.PROXY['http']
                    os.environ["HTTPS_PROXY"] = settings.PROXY['https']
                model = WhisperModel(
                    download_model(self.faster_whisper_model, local_files_only=False, cache_dir=cache_dir),
                    device="cpu", compute_type="int8", cpu_threads=psutil.cpu_count(logical=False))
                segments, info = model.transcribe(audio_file,
                                                  language=lang if lang != 'auto' else None,
                                                  word_timestamps=True,
                                                  vad_filter=True,
                                                  temperature=0,
                                                  beam_size=5)
                logger.info("Detected language '%s' with probability %f" % (info.language, info.language_probability))

                if lang == 'auto':
                    lang = info.language

                subs = []
                if lang in ['en', 'eng']:
                    # 英文先生成单词级别字幕，再合并
                    idx = 0
                    for segment in segments:
                        if self._event.is_set():
                            logger.info(f"whisper音轨转录服务停止")
                            raise UserInterruptException(f"用户中断当前任务")
                        for word in segment.words:
                            idx += 1
                            subs.append(srt.Subtitle(index=idx,
                                                     start=timedelta(seconds=word.start),
                                                     end=timedelta(seconds=word.end),
                                                     content=word.word))
                    subs = self.__merge_srt(subs)
                else:
                    for i, segment in enumerate(segments):
                        if self._event.is_set():
                            logger.info(f"whisper音轨转录服务停止")
                            raise UserInterruptException(f"用户中断当前任务")
                        subs.append(srt.Subtitle(index=i,
                                                 start=timedelta(seconds=segment.start),
                                                 end=timedelta(seconds=segment.end),
                                                 content=segment.text))
                self.__save_srt(f"{audio_file}.srt", subs)
                logger.info(f"音轨转字幕完成")
                return True, lang
            except ImportError:
                logger.warn(f"faster-whisper 未安装，不进行处理")
                return False, None
            except Exception as e:
                traceback.print_exc()
                logger.error(f"faster-whisper 处理异常：{e}")
                return False, None
        return False, None

    def __generate_subtitle(self, video_file, subtitle_file, enable_asr=True):
        """
        生成字幕
        :param video_file: 视频文件
        :param subtitle_file: 字幕文件, 不包含后缀
        :return: 生成成功返回True，字幕语言,字幕路径，否则返回False, None, None
        """
        # 获取文件元数据
        video_meta = Ffmpeg().get_video_metadata(video_file)
        if not video_meta:
            logger.error(f"获取视频文件元数据失败，跳过后续处理")
            return False, None, None
        # 获取字幕语言偏好
        if self._translate_preference == "english_only":
            prefer_subtitle_langs = ['en', 'eng']
            strict = True
        elif self._translate_preference == "english_first":
            prefer_subtitle_langs = ['en', 'eng']
            strict = False
        else:  # self.translate_preference == "origin_first"
            prefer_subtitle_langs = None
            strict = False

        # 从视频文件音轨获取语言信息
        ret, audio_index, audio_lang = self.__get_video_prefer_audio(video_meta, prefer_lang=prefer_subtitle_langs)
        if not ret:
            logger.info(f"字幕源偏好：{self._translate_preference} 获取音轨元数据失败")
            return False, None, None
        if not iso639.find(audio_lang) or not iso639.to_iso639_1(audio_lang):
            logger.info(f"字幕源偏好：{self._translate_preference} 未从音轨元数据中获取到语言信息")
            audio_lang = 'auto'
        # 当字幕源偏好为origin_first时，优先使用音轨语言
        if self._translate_preference == "origin_first":
            prefer_subtitle_langs = ['en', 'eng'] if audio_lang == 'auto' else [audio_lang,
                                                                                iso639.to_iso639_1(audio_lang)]
        # 获取外挂字幕
        logger.info(f"使用 {prefer_subtitle_langs} 匹配已有外挂字幕文件 ...")
        external_sub_exist, external_sub_lang, exist_sub_name = self.__external_subtitle_exists(video_file,
                                                                                                prefer_subtitle_langs,
                                                                                                only_srt=True,
                                                                                                strict=strict)
        # 获取内嵌字幕
        logger.info(f"使用 {prefer_subtitle_langs} 匹配内嵌字幕文件 ...")
        inner_sub_exist, subtitle_index, inner_sub_lang, = self.__get_video_prefer_subtitle(video_meta,
                                                                                            prefer_subtitle_langs,
                                                                                            strict=strict)

        # 优先返回符合语言要求的外部字幕
        def get_sub_path():
            video_dir, _ = os.path.split(video_file)
            return os.path.join(video_dir, exist_sub_name)

        extract_subtitle = False
        if self._translate_preference == "english_only":
            if external_sub_exist:
                logger.info(f"字幕源偏好：{self._translate_preference} 外挂字幕存在，字幕语言 {external_sub_lang}")
                return True, iso639.to_iso639_1(external_sub_lang), get_sub_path()
            elif inner_sub_exist:
                logger.info(f"字幕源偏好：{self._translate_preference} 内嵌字幕存在，字幕语言 {inner_sub_lang}")
                extract_subtitle = True
            else:
                logger.info(f"字幕源偏好：{self._translate_preference} 未匹配到外挂或内嵌字幕,需要使用asr提取")
        else:  # english_first/origin_first
            if external_sub_exist and external_sub_lang in prefer_subtitle_langs:
                logger.info(f"字幕源偏好：{self._translate_preference} 外挂字幕存在，字幕语言 {external_sub_lang}")
                return True, iso639.to_iso639_1(external_sub_lang), get_sub_path()
            elif inner_sub_exist and inner_sub_lang in prefer_subtitle_langs:
                logger.info(f"字幕源偏好：{self._translate_preference} 内嵌字幕存在，字幕语言 {inner_sub_lang}")
                extract_subtitle = True
            elif external_sub_exist:
                logger.info(f"字幕源偏好：{self._translate_preference} 外挂字幕存在，字幕语言 {external_sub_lang}")
                return True, iso639.to_iso639_1(external_sub_lang), get_sub_path()
            elif inner_sub_exist:
                logger.info(f"字幕源偏好：{self._translate_preference} 内嵌字幕存在，字幕语言 {inner_sub_lang}")
                extract_subtitle = True
            else:
                logger.info(f"字幕源偏好：{self._translate_preference} 未匹配到外挂或内嵌字幕,需要使用asr提取")
        # 提取内嵌字幕
        if extract_subtitle:
            inner_sub_lang = iso639.to_iso639_1(inner_sub_lang) \
                if (inner_sub_lang and iso639.find(inner_sub_lang) and iso639.to_iso639_1(inner_sub_lang)) else 'und'
            extracted_sub_path = f"{subtitle_file}.{inner_sub_lang}.srt"
            Ffmpeg().extract_subtitle_from_video(video_file, extracted_sub_path, subtitle_index)
            logger.info(f"提取字幕完成：{extracted_sub_path}")
            return True, inner_sub_lang, extracted_sub_path
        # 使用asr音轨识别字幕
        if audio_lang != 'auto':
            audio_lang = iso639.to_iso639_1(audio_lang)

        if not enable_asr:
            logger.info(f"未开启语音识别，且无已有字幕文件，跳过后续处理")
            return False, None, None

        # 清理异常退出的临时文件
        tempdir = tempfile.gettempdir()
        for file in os.listdir(tempdir):
            if file.startswith('autosub-'):
                os.remove(os.path.join(tempdir, file))

        with tempfile.NamedTemporaryFile(prefix='autosub-', suffix='.wav', delete=True) as audio_file:
            # 提取音频
            logger.info(f"正在提取音频：{audio_file.name} ...")
            Ffmpeg().extract_wav_from_video(video_file, audio_file.name, audio_index)
            logger.info(f"提取音频完成：{audio_file.name}")

            # 生成字幕
            logger.info(f"开始生成字幕, 语言 {audio_lang} ...")
            ret, lang = self.__do_speech_recognition(audio_lang, audio_file.name)
            if ret:
                logger.info(f"生成字幕成功，原始语言：{lang}")
                # 复制字幕文件
                SystemUtils.copy(Path(f"{audio_file.name}.srt"), Path(f"{subtitle_file}.{lang}.srt"))
                logger.info(f"复制字幕文件：{subtitle_file}.{lang}.srt")
                # 删除临时文件
                os.remove(f"{audio_file.name}.srt")
                return ret, lang, Path(f"{subtitle_file}.{lang}.srt")
            else:
                logger.error(f"生成字幕失败")
                return False, None, None

    @staticmethod
    def __get_library_files(in_path, exclude_path=None):
        """
        获取目录媒体文件列表
        """
        if not os.path.isdir(in_path):
            yield in_path
            return

        for root, dirs, files in os.walk(in_path):
            if exclude_path and any(os.path.abspath(root).startswith(os.path.abspath(path))
                                    for path in exclude_path.split(",")):
                continue

            for file in files:
                cur_path = os.path.join(root, file)
                # 检查后缀
                if os.path.splitext(file)[-1].lower() in settings.RMT_MEDIAEXT:
                    yield cur_path

    @staticmethod
    def __load_srt(file_path):
        """
        加载字幕文件
        :param file_path: 字幕文件路径
        :return:
        """
        with open(file_path, 'r', encoding="utf8") as f:
            srt_text = f.read()
        return list(srt.parse(srt_text))

    @staticmethod
    def __save_srt(file_path, srt_data):
        """
        保存字幕文件
        :param file_path: 字幕文件路径
        :param srt_data: 字幕数据
        :return:
        """
        with open(file_path, 'w', encoding="utf8") as f:
            f.write(srt.compose(srt_data))

    def __merge_srt(self, subtitle_data):
        """
        合并整句字幕
        :param subtitle_data:
        :return:
        """
        subtitle_data = copy.deepcopy(subtitle_data)
        # 合并字幕
        merged_subtitle = []
        sentence_end = True

        for index, item in enumerate(subtitle_data):
            # 当前字幕先将多行合并为一行，再去除首尾空格
            content = item.content.replace('\n', ' ').strip()
            # 去除html标签
            parse = etree.HTML(content)
            if parse is not None:
                content = parse.xpath('string(.)')
            if content == '':
                continue
            item.content = content

            # 背景音等字幕，跳过
            if self.__is_noisy_subtitle(content):
                merged_subtitle.append(item)
                sentence_end = True
                continue

            if not merged_subtitle or sentence_end:
                merged_subtitle.append(item)
            elif not sentence_end:
                merged_subtitle[-1].content = f"{merged_subtitle[-1].content} {content}"
                merged_subtitle[-1].end = item.end

            # 如果当前字幕内容以标志符结尾，则设置语句已经终结
            if content.endswith(tuple(self._end_token)):
                sentence_end = True
            # 如果上句字幕超过一定长度，则设置语句已经终结
            elif len(merged_subtitle[-1].content) > 80:
                sentence_end = True
            else:
                sentence_end = False

        return merged_subtitle

    def __get_video_prefer_audio(self, video_meta, prefer_lang=None):
        """
        获取视频的首选音轨，如果有多音轨， 优先指定语言音轨，否则获取默认音轨
        :param video_meta
        :return:
        """
        if type(prefer_lang) == str and prefer_lang:
            prefer_lang = [prefer_lang]

        # 获取首选音轨
        audio_lang = None
        audio_index = None
        audio_stream = filter(lambda x: x.get('codec_type') == 'audio', video_meta.get('streams', []))
        for index, stream in enumerate(audio_stream):
            if not audio_index:
                audio_index = index
                audio_lang = stream.get('tags', {}).get('language', 'und')
            # 获取默认音轨
            if stream.get('disposition', {}).get('default'):
                audio_index = index
                audio_lang = stream.get('tags', {}).get('language', 'und')
            # 获取指定语言音轨
            if prefer_lang and stream.get('tags', {}).get('language') in prefer_lang:
                audio_index = index
                audio_lang = stream.get('tags', {}).get('language', 'und')
                break

        # 如果没有音轨， 则不处理
        if audio_index is None:
            logger.warn(f"没有音轨，不进行处理")
            return False, None, None

        logger.info(f"选中音轨信息：{audio_index}, {audio_lang}")
        return True, audio_index, audio_lang

    def __get_video_prefer_subtitle(self, video_meta, prefer_lang=None, strict=False, srt=True):
        """
        获取视频的首选字幕。优先级：1.字幕为偏好语言 2.默认字幕 3.第一个字幕
        :param video_meta: 视频元数据
        :param prefer_lang: 字幕偏好语言
        :param strict: 是否严格模式。如果指定了偏好语言，严格模式下必须返回偏好语言的字幕。
        :return: (是否命中字幕，字幕index，字幕语言)
        """
        # from https://wiki.videolan.org/Subtitles_codecs/
        """
        https://trac.ffmpeg.org/wiki/ExtractSubtitles
        ffmpeg -codecs | grep subtitle
         DES... ass                  ASS (Advanced SSA) subtitle (decoders: ssa ass ) (encoders: ssa ass )
         DES... dvb_subtitle         DVB subtitles (decoders: dvbsub ) (encoders: dvbsub )
         DES... dvd_subtitle         DVD subtitles (decoders: dvdsub ) (encoders: dvdsub )
         D.S... hdmv_pgs_subtitle    HDMV Presentation Graphic Stream subtitles (decoders: pgssub )
         ..S... hdmv_text_subtitle   HDMV Text subtitle
         D.S... jacosub              JACOsub subtitle
         D.S... microdvd             MicroDVD subtitle
         D.S... mpl2                 MPL2 subtitle
         D.S... pjs                  PJS (Phoenix Japanimation Society) subtitle
         D.S... realtext             RealText subtitle
         D.S... sami                 SAMI subtitle
         ..S... srt                  SubRip subtitle with embedded timing
         ..S... ssa                  SSA (SubStation Alpha) subtitle
         D.S... stl                  Spruce subtitle format
         DES... subrip               SubRip subtitle (decoders: srt subrip ) (encoders: srt subrip )
         D.S... subviewer            SubViewer subtitle
         D.S... subviewer1           SubViewer v1 subtitle
         D.S... vplayer              VPlayer subtitle
         DES... webvtt               WebVTT subtitle
        """
        image_based_subtitle_codecs = (
            'dvd_subtitle',
            'dvb_subtitle',
            'hdmv_pgs_subtitle',
        )

        if prefer_lang is str and prefer_lang:
            prefer_lang = [prefer_lang]

        # 获取首选字幕
        subtitle_lang = None
        subtitle_index = None
        subtitle_score = 0
        subtitle_stream = filter(lambda x: x.get('codec_type') == 'subtitle', video_meta.get('streams', []))
        for index, stream in enumerate(subtitle_stream):
            # 如果是强制字幕，则跳过
            if stream.get('disposition', {}).get('forced'):
                continue
            # image-based 字幕，跳过
            if srt and (
                    'width' in stream
                    or stream.get('codec_name') in image_based_subtitle_codecs
            ):
                continue
            cur_is_default = stream.get('disposition', {}).get('default')
            cur_lang = stream.get('tags', {}).get('language')
            # 计算当前字幕得分：1.字幕为偏好语言*4 2.默认字幕*2 3.第一个字幕*1
            cur_score = 0
            if prefer_lang and cur_lang in prefer_lang:
                cur_score += 4
            if cur_is_default:
                cur_score += 2
            if subtitle_index is None:
                cur_score += 1
                # 第一个字幕初始化为默认字幕
                subtitle_lang, subtitle_index, subtitle_score = cur_lang, index, cur_score
            if cur_score > subtitle_score:
                subtitle_lang, subtitle_index, subtitle_score = cur_lang, index, cur_score

        # 未找到字幕
        if subtitle_index is None:
            logger.debug(f"没有内嵌字幕")
            return False, None, None
        if strict and prefer_lang and subtitle_lang not in prefer_lang:
            logger.warn(f"严格模式,没有偏好语言的字幕")
            return False, None, None
        logger.debug(f"命中内嵌字幕信息：{subtitle_index}, {subtitle_lang}, score:{subtitle_score}")
        return True, subtitle_index, subtitle_lang

    def __is_noisy_subtitle(self, content):
        """
        判断是否为背景音等字幕
        :param content:
        :return:
        """
        return any(content.startswith(t[0]) and content.endswith(t[1]) for t in self._noisy_token)

    def __get_context(self, all_subs: list, target_indices: List[int], is_batch: bool) -> str:
        """通用上下文获取方法"""
        min_idx = max(0, min(target_indices) - self.context_window)
        max_idx = min(len(all_subs) - 1, max(target_indices) + self.context_window) if is_batch else min(target_indices)

        context = []
        for idx in range(min_idx, max_idx + 1):
            status = "[待译]" if idx in target_indices else ""
            content = all_subs[idx].content.replace('\n', ' ').strip()
            context.append(f"{status}{content}")

        return "\n".join(context)

    def __process_items(self, all_subs: list, items: list) -> list:
        """统一处理入口（支持批量和单条）"""
        if self.enable_batch and len(items) > 1:
            return self.__process_batch(all_subs, items)
        return [self.__process_single(all_subs, item) for item in items]

    def __process_batch(self, all_subs: list, batch: list) -> list:
        """批量处理逻辑"""
        indices = [all_subs.index(item) for item in batch]
        context = self.__get_context(all_subs, indices, is_batch=True) if self.context_window > 0 else None
        batch_text = '\n'.join([item.content for item in batch])

        try:
            ret, result = self.openai.translate_to_zh(batch_text, context)
            if not ret:
                raise Exception(result)

            translated = [line.strip() for line in result.split('\n') if line.strip()]
            if len(translated) != len(batch):
                raise Exception(f"批次行数不匹配 {len(translated)}/{len(batch)}")

            for item, trans in zip(batch, translated):
                item.content = f"{trans}\n{item.content}"
            self._stats['batch_success'] += len(batch)
            return batch
        except Exception as e:
            logger.warning(f"批次翻译失败（{str(e)}），降级到单行匹配...")
            self._stats['batch_fail'] += 1
            return [self.__process_single(all_subs, item) for item in batch]

    def __process_single(self, all_subs: List[srt.Subtitle], item: srt.Subtitle) -> srt.Subtitle:
        """单条处理逻辑"""
        for _ in range(self.max_retries):
            idx = all_subs.index(item)
            context = self.__get_context(all_subs, [idx], is_batch=False) if self.context_window > 0 else None
            success, trans = self.openai.translate_to_zh(item.content, context)

            if success:
                item.content = f"{trans}\n{item.content}"
                self._stats['line_fallback'] += 1
                return item

            time.sleep(1)

        item.content = f"[翻译失败]\n{item.content}"
        return item

    def __translate_zh_subtitle(self, source_lang: str, source_subtitle: str, dest_subtitle: str):
        self._stats = {'total': 0, 'batch_success': 0, 'batch_fail': 0, 'line_fallback': 0}
        subs = self.__load_srt(source_subtitle)
        if source_lang in ["en", "eng"]:    
            valid_subs = self.__merge_srt(subs)
            logger.info(f"英文字幕合并：合并前字幕数: {len(subs)},合并后字幕数: {len(valid_subs)}")
        else:
            valid_subs = subs
        self._stats['total'] = len(valid_subs)
        processed = []
        current_batch = []

        for item in valid_subs:
            if self._event.is_set():
                logger.info(f"字幕{source_subtitle}翻译停止")
                raise UserInterruptException(f"用户中断当前任务")
            current_batch.append(item)

            if len(current_batch) >= self.batch_size:
                processed += self.__process_items(valid_subs, current_batch)
                current_batch = []
                logger.info(f"进度: {len(processed)}/{len(valid_subs)}")

        if current_batch:
            processed += self.__process_items(valid_subs, current_batch)

        self.__save_srt(dest_subtitle, processed)
        logger.info(f"""
    翻译完成！
    总处理条目: {self._stats['total']}
    批次成功: {self._stats['batch_success']} ({(self._stats['batch_success'] / self._stats['total']) * 100:.1f}%)
    批次失败: {self._stats['batch_fail']}
    行补偿翻译: {self._stats['line_fallback']}
            """)

    @staticmethod
    def __external_subtitle_exists(video_file, prefer_langs=None, only_srt=False, strict=True):
        """
        外部字幕文件是否存在,支持多种格式及扩展需求。
        :param video_file: 视频文件路径
        :param prefer_langs: 偏好语言列表，支持单个语言字符串或列表
        :param only_srt: 是否只匹配srt格式的字幕
        :param strict: 是否严格匹配偏好语言.当不存在偏好语言字幕但存在其他语言字幕时,是否返回其他字幕
        :return: 元组 (是否存在, 检测到的语言, 文件名)
        """
        video_dir, video_name = os.path.split(video_file)
        video_name, video_ext = os.path.splitext(video_name)

        if prefer_langs and type(prefer_langs) == str:
            prefer_langs = [prefer_langs]

        metadata_flags = ["default", "forced", "foreign", "sdh", "cc", "hi", "机翻"]
        if only_srt:
            subtitle_extensions = [".srt"]
        else:
            subtitle_extensions = [".srt", ".sub", ".ass", ".ssa", ".vtt"]

        def parse_props(props):
            """
            解析字幕属性信息，提取语言和元数据标记。
            :param props: 属性字符串
            :return: (语言, 元数据列表)
            """
            parts = props.split(".")
            if len(parts) < 1:
                return None, []

            cur_subtitle_lang = None
            cur_metadata = []
            # 倒序遍历文件名中的标记
            for i in range(len(parts) - 1, -1, -1):
                part = parts[i]
                if part in metadata_flags:
                    cur_metadata.append(part)
                elif cur_subtitle_lang is None:
                    try:
                        iso639.to_iso639_1(part)
                    except iso639.NonExistentLanguageError:
                        continue
                    else:
                        cur_subtitle_lang = iso639.to_iso639_1(part)  # 记录最后一个语言标记

            return cur_subtitle_lang, cur_metadata

        # 备选的字幕语言.当strict=False时生效, 用于在未找到偏好语言时返回其他语言
        second_lang = None
        second_file = None
        # 检查字幕文件
        for file in os.listdir(video_dir):
            if not file.startswith(video_name):
                continue

            # 检查扩展名是否在支持范围内
            _, ext = os.path.splitext(file)
            if ext.lower() not in subtitle_extensions:
                continue

            # 提取文件名中的语言和元数据信息
            props_str = file[len(video_name) + 1: -len(ext)] if file.startswith(video_name + ".") else ""
            subtitle_lang, metadata = parse_props(props_str)

            # 如果没有语言标记，跳过
            if not subtitle_lang:
                continue

            # 如果指定了偏好语言
            if prefer_langs:
                if subtitle_lang in prefer_langs:
                    return True, subtitle_lang, file
                else:
                    second_lang = subtitle_lang
                    second_file = file
            else:
                # 未指定偏好语言，找到的第一个字幕即返回
                return True, subtitle_lang, file
        if not strict and second_lang:
            return True, second_lang, second_file
        return False, None, None

    def __target_subtitle_exists(self, video_file):
        """
        目标字幕文件是否存在
        :param video_file:
        :return:
        """
        if self.translate_zh:
            prefer_langs = ['zh', 'chi', 'zh-CN', 'chs', 'zhs', 'zh-Hans', 'zhong', 'simp', 'cn']
            strict = True
        else:
            if self._translate_preference == "english_first":
                prefer_langs = ['en', 'eng']
                strict = False
            elif self._translate_preference == "english_only":
                prefer_langs = ['en', 'eng']
                strict = True
            else:
                prefer_langs = None
                strict = False

        exist, lang, _ = self.__external_subtitle_exists(video_file, prefer_langs, strict=strict)
        if exist:
            return True

        video_meta = Ffmpeg().get_video_metadata(video_file)
        if not video_meta:
            return False
        ret, subtitle_index, subtitle_lang = self.__get_video_prefer_subtitle(video_meta, prefer_lang=prefer_langs,
                                                                              srt=False)
        if ret and subtitle_lang in prefer_langs:
            return True

        return False

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
                                            'model': 'run_now',
                                            'label': '立即运行一次',
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
                                            'model': 'translate_preference',
                                            'label': '本地字幕提取策略',
                                            'items': [
                                                {'title': '仅英文字幕', 'value': 'english_only'},
                                                {'title': '优先英文字幕', 'value': 'english_first'},
                                                {'title': '优先原音字幕', 'value': 'origin_first'}
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
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'translate_zh',
                                            'label': '翻译为中文',
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
                                            'model': 'enable_asr',
                                            'label': '允许从音轨提取字幕',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                    'v-show': 'enable_asr'
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'asr_engine',
                                            'label': 'ASR引擎',
                                            'items': [
                                                {'title': 'faster-whisper', 'value': 'faster-whisper'}
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
                                    'v-show': 'enable_asr'
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'faster_whisper_model',
                                            'label': '模型',
                                            'items': [
                                                {'title': 'tiny', 'value': 'tiny'},
                                                {'title': 'tiny.en', 'value': 'tiny.en'},
                                                {'title': 'base', 'value': 'base'},
                                                {'title': 'base.en', 'value': 'base.en'},
                                                {'title': 'small', 'value': 'small'},
                                                {'title': 'small.en', 'value': 'small.en'},
                                                {'title': 'medium', 'value': 'medium'},
                                                {'title': 'large-v1', 'value': 'large-v1'},
                                                {'title': 'large-v2', 'value': 'large-v2'},
                                                {'title': 'large-v3', 'value': 'large-v3'},
                                                {'title': 'distil-small.en', 'value': 'distil-small.en'},
                                                {'title': 'distil-medium.en', 'value': 'distil-medium.en'},
                                                {'title': 'distil-large-v2.en', 'value': 'distil-large-v2'},
                                                {'title': 'distil-large-v3.en', 'value': 'distil-large-v3'},
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
                                    'v-show': 'enable_asr'
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'proxy',
                                            'label': '使用代理下载模型',
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
                                    'v-show': 'translate_zh'
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enable_batch',
                                            'label': '启用批量翻译',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                    'v-show': 'translate_zh'
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'batch_size',
                                            'label': '每批翻译行数',
                                            'placeholder': '20'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                    'v-show': 'translate_zh'
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'context_window',
                                            'label': '上下文窗口大小',
                                            'placeholder': '5'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                    'v-show': 'translate_zh'
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'max_retries',
                                            'label': 'llm请求重试次数',
                                            'placeholder': '3'
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'path_list',
                                            'label': '媒体路径',
                                            'rows': 5,
                                            'placeholder': '媒体文件或文件夹绝对路径（如为文件夹会遍历其中所有媒体文件），每行一个路径，请确保路径正确'
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
                                            'model': 'file_size',
                                            'label': '文件大小（MB）',
                                            'placeholder': '单位 MB, 大于该大小的文件才会进行字幕生成'
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
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '翻译依赖 OpenAi 插件配置'
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
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'success',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                        'component': 'span',
                                        'text': '详细说明参考：'
                                        },
                                        {
                                            'component': 'a',
                                            'props': {
                                                'href': 'https://github.com/TimoYoung/MoviePilot-Plugins/blob/main/plugins/autosubv2/README.md',
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
            "run_now": False,
            "send_notify": False,
            "translate_zh": True,
            "enable_asr": True,
            "asr_engine": "faster-whisper",
            "faster_whisper_model": "base",
            "proxy": True,
            "translate_preference": "origin_first",
            "enable_batch": True,
            "batch_size": 20,
            "context_window": 5,
            "max_retries": 3,
            "path_list": "",
            "file_size": "10",
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
        return self._running

    def stop_service(self):
        """
        退出插件
        """
        if self._running:
            self._event.set()
            self._running = False
            self._scheduler.shutdown()
            self._event.clear()
            logger.info(f"停止自动字幕生成服务")
