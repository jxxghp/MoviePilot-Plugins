from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import List, Tuple, Dict, Any, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.chain.scraping import ScrapingChain
from app.sdk.config import settings
from app.sdk.media import MetaInfoPath
from app.db.oper.transferhistory import TransferHistoryOper
from app.sdk.media import NfoReader
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas import MediaSource, MediaType
from app.sdk.media import resolve_media_identity
from app.sdk.utilities import SystemUtils


class LibraryScraper(_PluginBase):
    # 插件名称
    plugin_name = "媒体库刮削"
    # 插件描述
    plugin_desc = "定时对媒体库进行刮削，补齐缺失元数据和图片。"
    # 插件图标
    plugin_icon = "scraper.png"
    # 插件版本
    plugin_version = "3.1.0"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "libraryscraper_"
    # 加载顺序
    plugin_order = 7
    # 可使用的用户级别
    user_level = 1

    # 私有属性
    _scheduler = None
    _scraper = None
    # 限速开关
    _enabled = False
    _onlyonce = False
    _cron = None
    _mode = ""
    _scraper_paths = ""
    _exclude_paths = ""
    # 退出事件
    _event = Event()
    # 刮削目标类型
    _target_dir = "dir"
    _target_file = "file"

    def init_plugin(self, config: dict = None):

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._mode = config.get("mode") or ""
            self._scraper_paths = config.get("scraper_paths") or ""
            self._exclude_paths = config.get("exclude_paths") or ""

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:

            if self._onlyonce:
                logger.info(f"媒体库刮削服务，立即运行一次")
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(func=self.__libraryscraper, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="媒体库刮削")
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "mode": self._mode,
                    "scraper_paths": self._scraper_paths,
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

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._cron:
            return [{
                "id": "LibraryScraper",
                "name": "媒体库刮削",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.__libraryscraper,
                "kwargs": {}
            }]
        elif self._enabled:
            return [{
                "id": "LibraryScraper",
                "name": "媒体库刮削",
                "trigger": CronTrigger.from_crontab("0 0 */7 * *"),
                "func": self.__libraryscraper,
                "kwargs": {}
            }]
        return []

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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'mode',
                                            'label': '覆盖模式',
                                            'items': [
                                                {'title': '不覆盖已有元数据', 'value': ''},
                                                {'title': '覆盖所有元数据和图片', 'value': 'force_all'},
                                            ]
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
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
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
                                            'model': 'scraper_paths',
                                            'label': '削刮路径',
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
                                            'label': '排除路径',
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
                                            'text': '刮削路径后拼接#电视剧/电影，强制指定该媒体路径媒体类型。'
                                                    '不加默认根据文件名自动识别媒体类型。'
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
            "cron": "0 0 */7 * *",
            "mode": "",
            "scraper_paths": "",
            "err_hosts": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def __libraryscraper(self):
        """
        开始刮削媒体库
        """
        if not self._scraper_paths:
            return
        # 排除目录
        exclude_paths = self._exclude_paths.split("\n")
        # 已选择的目录
        paths = self._scraper_paths.split("\n")
        # 需要刮削的媒体目录或文件
        scraper_paths = []
        for path in paths:
            if not path:
                continue
            # 强制指定该路径媒体类型
            mtype = None
            if str(path).count("#") == 1:
                mtype = next(
                    (mediaType for mediaType in MediaType.__members__.values() if
                     mediaType.value == str(str(path).split("#")[1])),
                    None)
                path = str(path).split("#")[0]
            # 判断路径是否存在
            scraper_path = Path(path)
            if not scraper_path.exists():
                logger.warning(f"媒体库刮削路径不存在：{path}")
                continue
            logger.info(f"开始检索目录：{path} {mtype} ...")
            # 遍历所有文件
            files = SystemUtils.list_files(scraper_path, settings.RMT_MEDIAEXT)
            for file_path in files:
                if self._event.is_set():
                    logger.info(f"媒体库刮削服务停止")
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
                if mtype and not self.__match_forced_type_path(
                        file_path=file_path,
                        scraper_path=scraper_path,
                        mtype=mtype
                ):
                    logger.debug(f"{file_path} 不属于强制指定的{mtype.value}目录，跳过 ...")
                    continue
                # 识别是电影还是电视剧，强制类型只作为默认值，不污染后续文件识别结果
                file_meta = MetaInfoPath(file_path)
                file_mtype = mtype
                if not file_mtype:
                    file_mtype = file_meta.type
                    if file_mtype == MediaType.UNKNOWN:
                        file_mtype = self.__infer_type_from_path(file_path=file_path, scraper_path=scraper_path)
                scraper_item = self.__get_scrape_item(
                    file_path=file_path,
                    scraper_path=scraper_path,
                    mtype=file_mtype,
                    media_source=file_meta.media_source,
                    media_id=file_meta.media_id,
                )
                if scraper_item and not self.__contains_scrape_item(scraper_paths, scraper_item):
                    logger.info(f"发现刮削目标：{scraper_item}")
                    scraper_paths.append(scraper_item)
        # 开始刮削
        if scraper_paths:
            for item in scraper_paths:
                logger.info(f"开始刮削目标：{item[0]} ...")
                self.__scrape_path(
                    path=item[0],
                    mtype=item[1],
                    target_type=item[2],
                    media_source=item[3],
                    media_id=item[4],
                )
        else:
            logger.info(f"未发现需要刮削的目录")

    @staticmethod
    def __get_scrape_item(
            file_path: Path,
            scraper_path: Path,
            mtype: MediaType,
            media_source: Optional[MediaSource] = None,
            media_id: Optional[str] = None,
    ) -> Optional[Tuple[Path, MediaType, str, Optional[MediaSource], Optional[str]]]:
        """
        根据扫描根目录和重命名格式，计算真正需要刮削的媒体目录。
        分类目录通常位于扫描根目录下方，必须用相对路径计算，否则会被误当成媒体目录。
        """
        if not file_path or not scraper_path or not mtype:
            return None

        rename_format = settings.TV_RENAME_FORMAT if mtype == MediaType.TV else settings.MOVIE_RENAME_FORMAT
        rename_format_level = len(rename_format.strip("/").split("/")) - 1
        try:
            relative_path = file_path.relative_to(scraper_path)
        except ValueError:
            relative_path = Path(file_path.name)

        if rename_format_level >= 1:
            relative_parts = Path(relative_path).parts
            # 重命名格式中包含几层目录，就从文件往上取几层目录；前缀分类目录不会参与计算。
            if len(relative_parts) > rename_format_level:
                media_path = scraper_path.joinpath(*relative_parts[:-rename_format_level])
                return media_path, mtype, LibraryScraper._target_dir, media_source, media_id

        # 扁平目录或自定义重命名格式无目录层级时，退回到单文件刮削，避免分类目录识别失败。
        return file_path, mtype, LibraryScraper._target_file, media_source, media_id

    @staticmethod
    def __contains_scrape_item(
            scraper_paths: List[Tuple[Path, MediaType, str, Optional[MediaSource], Optional[str]]],
            scraper_item: Tuple[Path, MediaType, str, Optional[MediaSource], Optional[str]],
    ) -> bool:
        """
        判断刮削目标是否已存在；同一目标只刮削一次，媒体身份仅作为识别辅助信息。
        """
        return any(item[:3] == scraper_item[:3] for item in scraper_paths)

    @staticmethod
    def __match_forced_type_path(file_path: Path, scraper_path: Path, mtype: MediaType) -> bool:
        """
        强制指定媒体类型时，如果扫描根目录下同时存在“电影/电视剧”分类，则只处理匹配类型的目录。
        """
        if mtype not in (MediaType.MOVIE, MediaType.TV):
            return True
        try:
            relative_parts = file_path.relative_to(scraper_path).parts
        except ValueError:
            return True
        media_type_parts = {MediaType.MOVIE.value, MediaType.TV.value}.intersection(relative_parts)
        return not media_type_parts or mtype.value in media_type_parts

    @staticmethod
    def __infer_type_from_path(file_path: Path, scraper_path: Path) -> MediaType:
        """
        文件名无法识别类型时，从扫描根目录下的“电影/电视剧”分类层推断媒体类型。
        """
        try:
            relative_parts = file_path.relative_to(scraper_path).parts
        except ValueError:
            relative_parts = file_path.parts
        if MediaType.TV.value in relative_parts:
            return MediaType.TV
        if MediaType.MOVIE.value in relative_parts:
            return MediaType.MOVIE
        return MediaType.UNKNOWN

    def __scrape_path(
            self,
            path: Path,
            mtype: MediaType,
            target_type: str = _target_dir,
            media_source: Optional[MediaSource] = None,
            media_id: Optional[str] = None,
    ):
        """
        刮削一个媒体目录或媒体文件
        """
        media_source, media_id = resolve_media_identity(
            media_source=media_source,
            media_id=media_id,
        )
        # 优先读取本地 NFO 文件；NFO 无合法身份时保留文件路径中的统一身份。
        nfo_candidates = []
        if target_type == self._target_file:
            nfo_candidates.append(path.with_suffix(".nfo"))
        elif mtype == MediaType.MOVIE:
            nfo_candidates.extend((path / "movie.nfo", path / (path.stem + ".nfo")))
        else:
            nfo_candidates.append(path / "tvshow.nfo")
        for nfo_path in nfo_candidates:
            if not nfo_path.exists():
                continue
            nfo_source, nfo_media_id = self.__get_media_identity_from_nfo(nfo_path)
            if nfo_source:
                media_source, media_id = nfo_source, nfo_media_id
                break
        if media_source and media_id:
            logger.info(f"读取到本地 NFO 媒体身份：{media_source.value}:{media_id}")
            mediainfo = self.chain.recognize_media(
                media_source=media_source,
                media_id=str(media_id),
                mtype=mtype,
            )
        else:
            # 按名称识别
            meta = MetaInfoPath(path)
            meta.type = mtype
            mediainfo = self.chain.recognize_media(meta=meta)
        if not mediainfo:
            if target_type == self._target_dir:
                # 目录名无法识别时，通常是分类目录，继续尝试其中的具体媒体文件。
                self.__scrape_child_files(path=path, mtype=mtype)
                return
            logger.warn(f"未识别到媒体信息：{path}")
            return

        # 不跟随远端标题时，按统一媒体身份找回整理历史中的标题。
        if not settings.SCRAP_FOLLOW_TMDB:
            transfer_history = TransferHistoryOper().get_by_media_identity(
                media_source=mediainfo.media_source,
                media_id=mediainfo.media_id,
                mtype=mediainfo.type.value,
            )
            if transfer_history:
                mediainfo.title = transfer_history.title
        # 获取图片
        self.chain.obtain_images(mediainfo)
        # 刮削
        item_path = str(path).replace("\\", "/")
        if target_type == self._target_dir:
            item_path = f"{item_path}/"
        ScrapingChain().scrape_metadata(
            fileitem=schemas.FileItem(
                storage="local",
                type=target_type,
                path=item_path,
                name=path.name,
                basename=path.stem,
                extension=path.suffix[1:] if target_type == self._target_file else None,
                modify_time=path.stat().st_mtime,
            ),
            mediainfo=mediainfo,
            overwrite=True if self._mode else False
        )
        logger.info(f"{path} 刮削完成")

    def __scrape_child_files(self, path: Path, mtype: MediaType):
        """
        分类目录无法作为单个媒体识别时，继续按目录内的媒体文件逐个刮削。
        """
        child_files = SystemUtils.list_files(path, settings.RMT_MEDIAEXT)
        if not child_files:
            logger.warn(f"未识别到媒体信息：{path}")
            return
        logger.info(f"{path} 可能是分类目录，开始刮削目录内媒体文件 ...")
        for child_file in child_files:
            if self._event.is_set():
                logger.info(f"媒体库刮削服务停止")
                return
            child_mtype = mtype
            child_meta = MetaInfoPath(child_file)
            if not child_mtype:
                child_mtype = child_meta.type
            self.__scrape_path(
                path=child_file,
                mtype=child_mtype,
                target_type=self._target_file,
                media_source=child_meta.media_source,
                media_id=child_meta.media_id,
            )

    @staticmethod
    def __get_media_identity_from_nfo(file_path: Path) -> Tuple[Optional[MediaSource], Optional[str]]:
        """
        从 NFO 中读取第一个可识别的固定来源媒体身份。

        :param file_path: NFO 文件路径
        :return: 媒体来源枚举与数据源原生 ID
        """
        if not file_path:
            return None, None
        source_xpaths = {
            MediaSource.TMDB: (
                "uniqueid[@type='Tmdb']",
                "uniqueid[@type='tmdb']",
                "uniqueid[@type='TMDB']",
                "tmdbid",
            ),
            MediaSource.IMDb: (
                "uniqueid[@type='Imdb']",
                "uniqueid[@type='imdb']",
                "uniqueid[@type='IMDB']",
                "imdbid",
            ),
            MediaSource.TVDB: (
                "uniqueid[@type='Tvdb']",
                "uniqueid[@type='tvdb']",
                "uniqueid[@type='TVDB']",
                "tvdbid",
            ),
        }
        try:
            reader = NfoReader(file_path)
            for source, xpaths in source_xpaths.items():
                for xpath in xpaths:
                    media_source, media_id = resolve_media_identity(
                        media_source=source,
                        media_id=reader.get_element_value(xpath),
                    )
                    if media_source:
                        return media_source, media_id
        except Exception as err:
            logger.warn(f"从 NFO 文件中获取媒体身份失败：{str(err)}")
        return None, None

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
