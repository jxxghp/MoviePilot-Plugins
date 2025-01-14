import threading
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event as ThreadEvent
from typing import List, Tuple, Dict, Any

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.ffmpegthumb.ffmpeg_helper import FfmpegHelper
from app.schemas import TransferInfo
from app.schemas.types import EventType
from app.utils.system import SystemUtils

ffmpeg_lock = threading.Lock()


class FFmpegThumb(_PluginBase):
    # 插件名称
    plugin_name = "FFmpeg缩略图"
    # 插件描述
    plugin_desc = "TheMovieDb没有背景图片时使用FFmpeg截取视频文件缩略图。"
    # 插件图标
    plugin_icon = "ffmpeg.png"
    # 插件版本
    plugin_version = "2.1"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "ffmpegthumb_"
    # 加载顺序
    plugin_order = 31
    # 可使用的用户级别
    user_level = 1

    # 私有属性
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _cron = None
    _timeline = "00:03:01"
    _scan_paths = ""
    _exclude_paths = ""
    # 退出事件
    _event = ThreadEvent()

    def init_plugin(self, config: dict = None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._timeline = config.get("timeline")
            self._scan_paths = config.get("scan_paths") or ""
            self._exclude_paths = config.get("exclude_paths") or ""

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if self._cron:
                logger.info(f"FFmpeg缩略图服务启动，周期：{self._cron}")
                try:
                    self._scheduler.add_job(func=self.__libraryscan,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="FFmpeg缩略图")
                except Exception as e:
                    logger.error(f"FFmpeg缩略图服务启动失败，原因：{str(e)}")
                    self.systemmessage.put(f"FFmpeg缩略图服务启动失败，原因：{str(e)}", title="FFmpeg缩略图")
            if self._onlyonce:
                logger.info(f"FFmpeg缩略图服务，立即运行一次")
                self._scheduler.add_job(func=self.__libraryscan, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="FFmpeg缩略图")
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "timeline": self._timeline,
                    "scan_paths": self._scan_paths,
                    "exclude_paths": self._exclude_paths
                })
            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                    'md': 6
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
                                    'md': 6
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'timeline',
                                            'label': '截取时间',
                                            'placeholder': '00:03:01'
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
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '定时扫描周期',
                                            'placeholder': '5位cron表达式，留空关闭'
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'scan_paths',
                                            'label': '定时扫描路径',
                                            'rows': 5,
                                            'placeholder': '每一行一个目录'
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'exclude_paths',
                                            'label': '定时扫描排除路径',
                                            'rows': 2,
                                            'placeholder': '每一行一个目录'
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
                                            'text': '开启插件后默认会实时处理增量整理的媒体文件，需要处理存量媒体文件时才需开启定时；需要提前安装FFmpeg：https://www.ffmpeg.org'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "cron": "",
            "timeline": "00:03:01",
            "scan_paths": "",
            "err_hosts": ""
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.TransferComplete)
    def scan_rt(self, event: Event):
        """
        根据事件实时扫描缩略图
        """
        if not self._enabled:
            return
        # 事件数据
        transferinfo: TransferInfo = event.event_data.get("transferinfo")
        if not transferinfo:
            return
        if transferinfo.target_diritem and transferinfo.target_diritem.storage != "local":
            logger.warn(f"FFmpeg缩略图不支持非本地存储：{transferinfo.target_diritem.storage}")
            return
        file_list = transferinfo.file_list_new
        for file in file_list:
            logger.info(f"FFmpeg缩略图处理文件：{file}")
            file_path = Path(file)
            if not file_path.exists():
                logger.warn(f"{file_path} 不存在")
                continue
            if file_path.suffix not in settings.RMT_MEDIAEXT:
                logger.warn(f"{file_path} 不是支持的视频文件")
                continue
            self.gen_file_thumb(file_path)

    def __libraryscan(self):
        """
        开始扫描媒体库
        """
        if not self._scan_paths:
            return
        # 排除目录
        exclude_paths = self._exclude_paths.split("\n")
        # 已选择的目录
        paths = self._scan_paths.split("\n")
        for path in paths:
            if not path:
                continue
            scan_path = Path(path)
            if not scan_path.exists():
                logger.warning(f"FFmpeg缩略图扫描路径不存在：{path}")
                continue
            logger.info(f"开始FFmpeg缩略图扫描：{path} ...")
            # 遍历目录下的所有文件
            for file_path in SystemUtils.list_files(scan_path, extensions=settings.RMT_MEDIAEXT):
                if self._event.is_set():
                    logger.info(f"FFmpeg缩略图扫描服务停止")
                    return
                # 排除目录
                exclude_flag = False
                for exclude_path in exclude_paths:
                    try:
                        if file_path.is_relative_to(Path(exclude_path)):
                            exclude_flag = True
                            break
                    except Exception as err:
                        print(str(err))
                if exclude_flag:
                    logger.debug(f"{file_path} 在排除目录中，跳过 ...")
                    continue
                # 开始处理文件
                self.gen_file_thumb(file_path)
            logger.info(f"目录 {path} 扫描完成")

    def gen_file_thumb(self, file_path: Path):
        """
        处理一个文件
        """
        # 单线程处理
        with ffmpeg_lock:
            try:
                thumb_path = file_path.with_name(file_path.stem + "-thumb.jpg")
                if thumb_path.exists():
                    logger.info(f"缩略图已存在：{thumb_path}")
                    return
                if FfmpegHelper.get_thumb(video_path=str(file_path),
                                          image_path=str(thumb_path), frames=self._timeline):
                    logger.info(f"{file_path} 缩略图已生成：{thumb_path}")
            except Exception as err:
                logger.error(f"FFmpeg处理文件 {file_path} 时发生错误：{str(err)}")

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))
