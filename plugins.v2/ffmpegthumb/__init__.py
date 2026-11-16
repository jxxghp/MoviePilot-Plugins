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
    """为缺少分集图片的视频生成缩略图，并管理扫描任务。"""
    plugin_name = "FFmpeg缩略图"
    # 插件描述
    plugin_desc = "为缺少分集剧照的视频截取画面作为分集缩略图，已有分集图片时不重复生成。"
    # 插件图标
    plugin_icon = "ffmpeg.png"
    # 插件版本
    plugin_version = "2.3"
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

    # 单个文件的处理结果
    RESULT_GENERATED = "generated"
    RESULT_SKIPPED = "skipped"
    RESULT_FAILED = "failed"

    # 蓝光原盘不是可直接截帧的成品文件：iso 镜像与 BDMV 目录结构直接跳过
    SKIP_SUFFIXES = {".iso"}
    SKIP_DIR_NAMES = {"BDMV"}

    # 私有属性
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _cron = None
    _timeline = "00:03:01"
    _scan_paths = ""
    _exclude_paths = ""
    _skip_existing = True
    # 退出事件
    _event = ThreadEvent()

    def init_plugin(self, config: dict = None):
        # 读取配置
        """停止旧任务并读取配置，按启用状态安排本实例任务。"""
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._timeline = config.get("timeline")
            self._scan_paths = config.get("scan_paths") or ""
            self._exclude_paths = config.get("exclude_paths") or ""
            # 默认跳过已有分集图片，避免视频截帧顶掉刮削到的分集剧照
            self._skip_existing = config.get("skip_existing")
            if self._skip_existing is None:
                self._skip_existing = True

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
                    "exclude_paths": self._exclude_paths,
                    "skip_existing": self._skip_existing
                })
            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        """返回插件启用状态，供宿主决定是否注册服务。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """声明插件远程命令；无命令时沿用宿主空入口。"""
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """声明插件接口及认证方式；无接口时沿用宿主空入口。"""
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回配置表单及其默认值。"""
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'skip_existing',
                                            'label': '跳过已有分集图片',
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
                                            'text': '开启插件后默认会实时处理增量整理的媒体文件；已入库的存量文件不会产生整理事件，需要主动扫描一次：可开启「立即运行一次」补一遍（跑完自动关闭），或设置定时扫描周期定期兜底；开启「跳过已有分集图片」后，已刮削到分集剧照的集不会再生成截帧；需要提前安装FFmpeg：https://www.ffmpeg.org'
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
            "exclude_paths": "",
            "skip_existing": True
        }

    def get_page(self) -> List[dict]:
        """返回插件详情页面；没有独立页面时保留空入口。"""
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
        exclude_paths = [line.strip() for line in self._exclude_paths.splitlines() if line.strip()]
        # 已选择的目录
        paths = self._scan_paths.split("\n")
        # 处理结果统计
        stats = {
            self.RESULT_GENERATED: 0,
            self.RESULT_SKIPPED: 0,
            self.RESULT_FAILED: 0
        }
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
                        logger.debug(f"FFmpeg缩略图排除路径匹配失败：{str(err)}")
                if exclude_flag:
                    logger.debug(f"{file_path} 在排除目录中，跳过 ...")
                    continue
                # 开始处理文件
                stats[self.gen_file_thumb(file_path)] += 1
            logger.info(f"目录 {path} 扫描完成")
        logger.info(f"FFmpeg缩略图扫描完成：生成 {stats[self.RESULT_GENERATED]} 个，"
                    f"跳过 {stats[self.RESULT_SKIPPED]} 个，失败 {stats[self.RESULT_FAILED]} 个")

    @staticmethod
    def build_thumb_path(file_path: Path) -> Path:
        """
        生成分集缩略图路径：与视频同目录同名，后缀为 -thumb.jpg

        :param file_path: 视频文件路径
        :return: 缩略图路径
        """
        return file_path.with_name(file_path.stem + "-thumb.jpg")

    @classmethod
    def should_skip(cls, file_path: Path, skip_existing: bool = True) -> Tuple[bool, str]:
        """
        判断是否需要跳过该视频文件

        :param file_path: 视频文件路径
        :param skip_existing: 是否在已有分集图片（与视频同名的 jpg）时跳过
        :return: (是否跳过, 跳过原因)
        """
        if file_path.suffix.lower() in cls.SKIP_SUFFIXES:
            return True, "蓝光原盘镜像，无法截帧，跳过"
        if any(part.upper() in cls.SKIP_DIR_NAMES for part in file_path.parts[:-1]):
            return True, "蓝光原盘目录结构，无法截帧，跳过"
        thumb_path = cls.build_thumb_path(file_path)
        if thumb_path.is_file() and thumb_path.stat().st_size > 0:
            return True, f"缩略图已存在：{thumb_path.name}"
        if skip_existing:
            scraped_image = file_path.with_suffix(".jpg")
            if scraped_image.is_file() and scraped_image.stat().st_size > 0:
                return True, f"已有分集图片：{scraped_image.name}，跳过"
        return False, ""

    def gen_file_thumb(self, file_path: Path) -> str:
        """
        处理一个文件

        :param file_path: 视频文件路径
        :return: 处理结果，取值 generated/skipped/failed
        """
        # 单线程处理
        with ffmpeg_lock:
            skip, reason = self.should_skip(file_path, self._skip_existing)
            if skip:
                logger.info(f"{file_path} {reason}")
                return self.RESULT_SKIPPED
            thumb_path = self.build_thumb_path(file_path)
            try:
                if FfmpegHelper.get_thumb(video_path=str(file_path),
                                          image_path=str(thumb_path), frames=self._timeline):
                    logger.info(f"{file_path} 缩略图已生成：{thumb_path.name}")
                    return self.RESULT_GENERATED
            except Exception as err:
                logger.error(f"FFmpeg处理文件 {file_path} 时发生错误：{str(err)}")
                return self.RESULT_FAILED
            logger.error(f"{file_path} 缩略图生成失败")
            return self.RESULT_FAILED

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
