import re
import shutil
import subprocess
import threading
import uuid
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.context import MediaInfo
from app.core.event import eventmanager
from app.core.meta import MetaBase
from app.core.metainfo import MetaInfoPath
from app.helper.directory import DirectoryHelper
from app.log import logger
from app.modules.filemanager.storages import StorageBase
from app.modules.filemanager.storages.local import LocalStorage
from app.modules.filemanager.transhandler import TransHandler
from app.plugins import _PluginBase
from app.schemas import (
    FileItem,
    TmdbEpisode,
    TransferDirectoryConf,
    TransferInfo,
    TransferInterceptEventData,
    TransferOverwriteCheckEventData,
)
from app.schemas.types import ChainEventType, MediaType

_MPLS_MAX_SIZE = 1024 * 1024
_MPLS_MAX_PLAYITEMS = 200
_MPLS_MAX_DURATION_SECONDS = 12 * 60 * 60
_MPLS_TIME_BASE = 45000
_PLAYITEM_IN_TIME_OFFSET = 14
_PLAYITEM_OUT_TIME_OFFSET = 18
_MIN_TIMEOUT_SECONDS = 60
_DEFAULT_TIMEOUT_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class _RemuxSource:
    """蓝光原盘转封装源分片。"""

    path: Path
    in_time: int = 0
    out_time: int = 0

    @property
    def need_clip(self) -> bool:
        return self.in_time > 0 or self.out_time > 0


@dataclass
class _TransferContext:
    target_storage: str
    target_path: Path
    transfer_type: str
    need_scrape: bool
    need_rename: bool
    need_notify: bool
    overwrite_mode: Optional[str]
    source_oper: StorageBase
    target_oper: StorageBase


class BlurayRemux(_PluginBase):
    plugin_name = "蓝光原盘转封装"
    plugin_desc = "整理电影蓝光原盘目录时，使用 ffmpeg 自动转封装为单个 MKV 文件。"
    plugin_icon = "ffmpeg.png"
    plugin_version = "1.0.0"
    plugin_author = "drdon1234"
    author_url = "https://github.com/drdon1234"
    plugin_config_prefix = "blurayremux_"
    plugin_order = 50
    auth_level = 1

    _enabled = False
    _timeout = _DEFAULT_TIMEOUT_SECONDS

    _target_locks = weakref.WeakValueDictionary()
    _target_locks_guard = threading.Lock()

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._timeout = self.__normalize_timeout(config.get("timeout"))

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_module(self) -> Dict[str, Any]:
        if not self._enabled:
            return {}
        return {"transfer": self.transfer}

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
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
                                            "model": "enabled",
                                            "label": "启用插件",
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
                                            "model": "timeout",
                                            "label": "转封装超时（秒）",
                                            "type": "number",
                                            "min": _MIN_TIMEOUT_SECONDS,
                                            "placeholder": str(_DEFAULT_TIMEOUT_SECONDS),
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "仅处理本地源到本地目标的电影 BDMV 目录；未命中时自动交回原生整理流程。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "timeout": _DEFAULT_TIMEOUT_SECONDS,
        }

    def get_page(self) -> List[dict]:
        state = "已启用" if self._enabled else "未启用"
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info" if self._enabled else "warning",
                    "variant": "tonal",
                    "text": f"{state}，当前 ffmpeg 超时为 {self._timeout} 秒。",
                },
            }
        ]

    def stop_service(self):
        pass

    def transfer(
            self,
            fileitem: FileItem,
            meta: MetaBase,
            mediainfo: MediaInfo,
            target_directory: TransferDirectoryConf = None,
            target_storage: Optional[str] = None,
            target_path: Path = None,
            transfer_type: Optional[str] = None,
            scrape: bool = None,
            library_type_folder: bool = None,
            library_category_folder: bool = None,
            episodes_info: List[TmdbEpisode] = None,
            source_oper: Callable = None,
            target_oper: Callable = None,
            preview: bool = False,
    ) -> Optional[TransferInfo]:
        if not self._enabled or preview or not fileitem or fileitem.type != "dir":
            return None

        bluray_root = self.__get_local_bluray_root(Path(fileitem.path))
        if not bluray_root:
            return None

        context = self.__build_transfer_context(
            fileitem=fileitem,
            mediainfo=mediainfo,
            target_directory=target_directory,
            target_storage=target_storage,
            target_path=target_path,
            transfer_type=transfer_type,
            scrape=scrape,
            library_type_folder=library_type_folder,
            library_category_folder=library_category_folder,
            source_oper=source_oper,
            target_oper=target_oper,
        )
        if isinstance(context, TransferInfo):
            return context
        if not context:
            return None

        if (fileitem.storage or "local") != "local" or context.target_storage != "local":
            logger.warn("蓝光原盘转封装仅支持本地源到本地目标，保持原生整理")
            return None
        if context.transfer_type not in ["copy", "move"]:
            logger.warn(f"蓝光原盘转封装不支持 {context.transfer_type} 整理方式，保持原生整理")
            return None
        if context.transfer_type == "move" and not self.__is_same_path(Path(fileitem.path), bluray_root):
            return TransferInfo(
                success=False,
                message="蓝光原盘转封装移动模式不支持从子目录入口整理",
                fileitem=fileitem,
                fail_list=[fileitem.path],
                transfer_type=context.transfer_type,
                need_notify=context.need_notify,
            )
        if mediainfo.type == MediaType.TV:
            logger.warn("电视剧蓝光原盘可能包含多集或全集播放列表，保持原生整理")
            return None

        return self.__transfer_bluray_remux(
            fileitem=fileitem,
            meta=meta,
            mediainfo=mediainfo,
            bluray_root=bluray_root,
            target_path=context.target_path,
            target_storage=context.target_storage,
            transfer_type=context.transfer_type,
            source_oper=context.source_oper,
            target_oper=context.target_oper,
            need_scrape=context.need_scrape,
            need_rename=context.need_rename,
            need_notify=context.need_notify,
            overwrite_mode=context.overwrite_mode,
            episodes_info=episodes_info,
        )

    @staticmethod
    def __normalize_timeout(value: Any) -> int:
        try:
            timeout = int(value or _DEFAULT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT_SECONDS
        return max(_MIN_TIMEOUT_SECONDS, timeout)

    def __build_transfer_context(
            self,
            fileitem: FileItem,
            mediainfo: MediaInfo,
            target_directory: TransferDirectoryConf = None,
            target_storage: Optional[str] = None,
            target_path: Path = None,
            transfer_type: Optional[str] = None,
            scrape: bool = None,
            library_type_folder: bool = None,
            library_category_folder: bool = None,
            source_oper: StorageBase = None,
            target_oper: StorageBase = None,
    ) -> Optional[_TransferContext | TransferInfo]:
        handler = TransHandler()
        if fileitem.storage == "local" and not Path(fileitem.path).exists():
            return TransferInfo(
                success=False,
                fileitem=fileitem,
                message=f"{fileitem.path} 不存在",
            )
        if target_path and Path(target_path).is_file():
            logger.error(f"整理目标路径 {target_path} 是一个文件")
            return TransferInfo(
                success=False,
                fileitem=fileitem,
                message=f"{target_path} 不是有效目录",
            )

        if target_directory:
            if not target_directory.library_path:
                logger.error(f"目标媒体库目录未设置，无法整理文件，源路径：{fileitem.path}")
                return TransferInfo(
                    success=False,
                    fileitem=fileitem,
                    message="目标媒体库目录未设置",
                )
            transfer_type = transfer_type or target_directory.transfer_type
            target_storage = target_storage or target_directory.library_storage or fileitem.storage or "local"
            need_rename = bool(target_directory.renaming)
            need_notify = bool(target_directory.notify)
            overwrite_mode = target_directory.overwrite_mode
            need_scrape = bool(target_directory.scraping) if scrape is None else bool(scrape)
            target_path = handler.get_dest_dir(
                mediainfo=mediainfo,
                target_dir=target_directory,
                need_type_folder=library_type_folder,
                need_category_folder=library_category_folder,
            )
        elif target_path:
            target_storage = target_storage or fileitem.storage or "local"
            need_scrape = bool(scrape or False)
            need_rename = True
            need_notify = False
            overwrite_mode = "never"
            target_path = handler.get_dest_path(
                mediainfo=mediainfo,
                target_path=Path(target_path),
                need_type_folder=library_type_folder,
                need_category_folder=library_category_folder,
            )
        else:
            logger.error(
                f"{mediainfo.type.value if mediainfo.type else '未知类型'} "
                f"{mediainfo.title_year} 未找到有效的媒体库目录，无法整理文件，源路径：{fileitem.path}"
            )
            return TransferInfo(
                success=False,
                fileitem=fileitem,
                message="未找到有效的媒体库目录",
            )

        if not transfer_type:
            directory_name = target_directory.name if target_directory else "目标目录"
            logger.error(f"{directory_name} 未设置整理方式")
            return TransferInfo(
                success=False,
                fileitem=fileitem,
                message=f"{directory_name} 未设置整理方式",
            )

        source_oper = source_oper or LocalStorage()
        target_oper = target_oper or LocalStorage()
        return _TransferContext(
            target_storage=target_storage,
            target_path=Path(target_path),
            transfer_type=transfer_type,
            need_scrape=need_scrape,
            need_rename=need_rename,
            need_notify=need_notify,
            overwrite_mode=overwrite_mode,
            source_oper=source_oper,
            target_oper=target_oper,
        )

    def __transfer_bluray_remux(
            self,
            fileitem: FileItem,
            meta: MetaBase,
            mediainfo: MediaInfo,
            bluray_root: Path,
            target_path: Path,
            target_storage: str,
            transfer_type: str,
            source_oper: StorageBase,
            target_oper: StorageBase,
            need_scrape: bool,
            need_rename: bool,
            need_notify: bool,
            overwrite_mode: Optional[str],
            episodes_info: List[TmdbEpisode] = None,
    ) -> TransferInfo:
        rename_format = settings.RENAME_FORMAT(mediainfo.type)
        target_file = self.__get_remux_target_file(
            fileitem=fileitem,
            meta=meta,
            mediainfo=mediainfo,
            target_path=target_path,
            rename_format=rename_format,
            need_rename=need_rename,
            episodes_info=episodes_info,
        )
        if self.__is_path_relative_to(target_file, bluray_root):
            return TransferInfo(
                success=False,
                message="蓝光原盘转封装目标不能位于源目录内",
                fileitem=fileitem,
                fail_list=[fileitem.path],
                transfer_type=transfer_type,
                need_notify=need_notify,
            )

        folder_path = (
            DirectoryHelper.get_media_root_path(rename_format, rename_path=target_file)
            if need_rename
            else target_file.parent
        )
        if not folder_path:
            return TransferInfo(
                success=False,
                message="重命名格式无效",
                fileitem=fileitem,
                transfer_type=transfer_type,
                need_notify=need_notify,
            )

        target_diritem = target_oper.get_folder(folder_path)
        if not target_diritem:
            return TransferInfo(
                success=False,
                message=f"目标目录 {folder_path} 获取失败",
                fileitem=fileitem,
                fail_list=[fileitem.path],
                transfer_type=transfer_type,
                need_notify=need_notify,
            )

        intercept = TransferInterceptEventData(
            fileitem=fileitem,
            meta=meta,
            mediainfo=mediainfo,
            target_storage=target_storage,
            target_path=target_file,
            transfer_type=transfer_type,
            options={"bluray_remux": True, "plugin": self.__class__.__name__},
        )
        intercept_event = eventmanager.send_event(ChainEventType.TransferIntercept, intercept)
        if intercept_event and intercept_event.event_data and intercept_event.event_data.cancel:
            return TransferInfo(
                success=False,
                message=intercept_event.event_data.reason,
                fileitem=fileitem,
                fail_list=[fileitem.path],
                transfer_type=transfer_type,
                need_notify=need_notify,
            )

        source_files, source_size = self.__get_remux_sources(bluray_root)
        if not source_files:
            return TransferInfo(
                success=False,
                message=f"蓝光原盘 {bluray_root} 未找到可转封装的视频分片",
                fileitem=fileitem,
                fail_list=[fileitem.path],
                transfer_type=transfer_type,
                need_notify=need_notify,
            )

        target_lock = self.__get_target_lock(target_file)
        with target_lock:
            target_item = self.__get_target_item(target_oper, target_storage, target_file)
            target_size = target_item.size if target_item else None
            if target_size is None and target_file.is_file():
                target_size = target_file.stat().st_size
            allow_target_replace = bool(target_item or target_file.exists() or target_file.is_symlink())
            can_overwrite, errmsg, recheck_output_size = self.__check_overwrite(
                fileitem=fileitem,
                target_oper=target_oper,
                target_file=target_file,
                target_storage=target_storage,
                transfer_type=transfer_type,
                overwrite_mode=overwrite_mode,
                source_size=source_size,
            )
            if not can_overwrite:
                return TransferInfo(
                    success=False,
                    message=errmsg,
                    fileitem=fileitem,
                    target_item=target_item,
                    target_diritem=target_diritem,
                    fail_list=[fileitem.path],
                    transfer_type=transfer_type,
                    need_notify=need_notify,
                )

            logger.info(f"正在转封装蓝光原盘：{bluray_root} 到 {target_file}")
            state, errmsg = self.__run_remux(
                source_files=source_files,
                target_file=target_file,
                allow_target_replace=allow_target_replace,
                recheck_target_size=target_size if recheck_output_size else None,
            )
            if not state:
                logger.error(f"蓝光原盘 {fileitem.path} 转封装失败：{errmsg}")
                return TransferInfo(
                    success=False,
                    message=errmsg,
                    fileitem=fileitem,
                    fail_list=[fileitem.path],
                    transfer_type=transfer_type,
                    need_notify=need_notify,
                )
            if overwrite_mode == "latest":
                self.__delete_version_files(target_oper, target_file)

        target_item = self.__get_target_item(target_oper, target_storage, target_file)
        if transfer_type == "move" and not source_oper.delete(fileitem):
            return TransferInfo(
                success=False,
                message="转封装成功但删除源目录失败",
                fileitem=fileitem,
                target_item=target_item,
                target_diritem=target_diritem,
                fail_list=[fileitem.path],
                transfer_type=transfer_type,
                need_notify=need_notify,
            )

        target_item = target_item or self.__build_local_fileitem(target_file)
        logger.info(f"蓝光原盘 {fileitem.path} 转封装整理成功")
        return TransferInfo(
            success=True,
            fileitem=fileitem,
            target_item=target_item,
            target_diritem=target_diritem,
            need_scrape=need_scrape,
            need_notify=need_notify,
            transfer_type=transfer_type,
            file_list=[fileitem.path],
            file_list_new=[target_item.path],
            file_count=1,
            total_size=target_item.size or 0,
        )

    @classmethod
    def __get_target_lock(cls, target_file: Path) -> threading.Lock:
        lock_key = target_file.resolve().as_posix()
        with cls._target_locks_guard:
            target_lock = cls._target_locks.get(lock_key)
            if target_lock is None:
                target_lock = threading.Lock()
                cls._target_locks[lock_key] = target_lock
            return target_lock

    @staticmethod
    def __get_local_bluray_root(path: Path) -> Optional[Path]:
        if (path / "BDMV" / "STREAM").is_dir():
            return path
        if path.name.upper() == "BDMV" and (path / "STREAM").is_dir():
            return path.parent
        if path.name.upper() == "STREAM" and path.parent.name.upper() == "BDMV" and path.is_dir():
            return path.parent.parent
        return None

    @staticmethod
    def __is_path_relative_to(path: Path, parent: Path) -> bool:
        try:
            parent_path = parent.resolve()
            candidate_path = path.parent.resolve() / path.name
            candidate_path.relative_to(parent_path)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def __is_same_path(path: Path, other: Path) -> bool:
        try:
            return path.resolve() == other.resolve()
        except OSError:
            return False

    @staticmethod
    def __build_local_fileitem(path: Path) -> FileItem:
        stat = path.stat()
        return FileItem(
            storage="local",
            path=path.as_posix(),
            name=path.name,
            basename=path.stem,
            type="file",
            size=stat.st_size,
            extension=path.suffix.lstrip("."),
            modify_time=stat.st_mtime,
        )

    @classmethod
    def __get_target_item(
            cls,
            target_oper: StorageBase,
            target_storage: str,
            target_file: Path,
    ) -> Optional[FileItem]:
        target_item = target_oper.get_item(target_file)
        if target_item:
            return target_item
        if target_file.exists() or target_file.is_symlink():
            if target_file.is_file():
                return cls.__build_local_fileitem(target_file)
            return FileItem(
                storage=target_storage,
                path=target_file.as_posix(),
                name=target_file.name,
                basename=target_file.stem,
                type="file",
                size=0,
                extension=target_file.suffix.lstrip("."),
            )
        return None

    @staticmethod
    def __parse_mpls_stream_items(mpls_file: Path) -> List[Tuple[str, int, int]]:
        try:
            if mpls_file.stat().st_size > _MPLS_MAX_SIZE:
                logger.warn(f"蓝光播放列表 {mpls_file} 过大，跳过解析")
                return []
            data = mpls_file.read_bytes()
            if len(data) < 16:
                return []
            playlist_start = int.from_bytes(data[8:12], "big")
            if playlist_start <= 0 or playlist_start + 10 > len(data):
                return []
            pos = playlist_start + 6
            playitem_count = int.from_bytes(data[pos:pos + 2], "big")
            if playitem_count <= 0 or playitem_count > _MPLS_MAX_PLAYITEMS:
                return []
            pos += 4
            stream_items = []
            seen_items = set()
            total_duration = 0
            for _ in range(playitem_count):
                if pos + _PLAYITEM_OUT_TIME_OFFSET + 4 > len(data):
                    return []
                item_length = int.from_bytes(data[pos:pos + 2], "big")
                item_end = pos + 2 + item_length
                if item_length < _PLAYITEM_OUT_TIME_OFFSET + 4 - 2 or item_end > len(data):
                    return []
                clip_name = data[pos + 2:pos + 7].decode("ascii", errors="ignore").strip("\x00 ")
                if not clip_name:
                    return []
                in_time = int.from_bytes(data[pos + _PLAYITEM_IN_TIME_OFFSET:pos + _PLAYITEM_IN_TIME_OFFSET + 4], "big")
                out_time = int.from_bytes(data[pos + _PLAYITEM_OUT_TIME_OFFSET:pos + _PLAYITEM_OUT_TIME_OFFSET + 4], "big")
                if out_time <= in_time:
                    return []
                item_key = (clip_name.upper(), in_time, out_time)
                if item_key in seen_items:
                    return []
                seen_items.add(item_key)
                total_duration += out_time - in_time
                if total_duration > _MPLS_MAX_DURATION_SECONDS * _MPLS_TIME_BASE:
                    return []
                stream_items.append((f"{clip_name}.m2ts", in_time, out_time))
                pos = item_end
            return stream_items
        except Exception as err:
            logger.debug(f"解析蓝光播放列表 {mpls_file} 失败：{err}")
            return []

    @classmethod
    def __get_remux_sources(cls, bluray_root: Path) -> Tuple[List[_RemuxSource], int]:
        stream_dir = bluray_root / "BDMV" / "STREAM"
        stream_files = [
            item
            for item in stream_dir.iterdir()
            if (
                not item.is_symlink()
                and item.is_file()
                and item.suffix.lower() == ".m2ts"
                and cls.__is_path_relative_to(item, bluray_root)
            )
        ] if stream_dir.is_dir() else []
        if not stream_files:
            return [], 0

        stream_map = {item.name.upper(): item for item in stream_files}
        playlist_dir = bluray_root / "BDMV" / "PLAYLIST"
        playlist_files = []
        best_files = []
        best_size = 0
        if playlist_dir.is_dir():
            playlist_files = [
                item
                for item in playlist_dir.iterdir()
                if item.is_file() and item.suffix.lower() == ".mpls"
            ]
            for mpls_file in sorted(playlist_files):
                stream_items = cls.__parse_mpls_stream_items(mpls_file)
                files = [
                    stream_map.get(name.upper())
                    for name, _in_time, _out_time in stream_items
                ]
                if not files or any(item is None for item in files):
                    continue
                total_size = sum(item.stat().st_size for item in files)
                if total_size > best_size:
                    best_files = [
                        _RemuxSource(file, in_time, out_time)
                        for file, (_name, in_time, out_time) in zip(files, stream_items)
                    ]
                    best_size = total_size

        if best_files:
            return best_files, best_size
        if playlist_files:
            logger.warn(f"蓝光原盘 {bluray_root} 存在播放列表但无法匹配可转封装分片，跳过转封装")
            return [], 0
        if len(stream_files) > 1:
            logger.warn(f"蓝光原盘 {bluray_root} 缺少播放列表，跳过多分片最大文件回退")
            return [], 0

        largest_file = max(stream_files, key=lambda item: item.stat().st_size)
        return [_RemuxSource(largest_file)], largest_file.stat().st_size

    def __get_remux_target_file(
            self,
            fileitem: FileItem,
            meta: MetaBase,
            mediainfo: MediaInfo,
            target_path: Path,
            rename_format: str,
            need_rename: bool,
            episodes_info: List[TmdbEpisode] = None,
    ) -> Path:
        if need_rename:
            handler = TransHandler()
            target_file = handler.get_rename_path(
                path=target_path,
                template_string=rename_format,
                rename_dict=handler.get_naming_dict(
                    meta=meta,
                    mediainfo=mediainfo,
                    file_ext=".mkv",
                    episodes_info=episodes_info,
                ),
                source_path=fileitem.path,
                source_item=fileitem,
            )
            if target_file.suffix.lower() != ".mkv":
                target_file = target_file.parent / f"{target_file.name}.mkv"
            return target_file
        return target_path / f"{fileitem.name}.mkv"

    def __run_remux(
            self,
            source_files: List[_RemuxSource],
            target_file: Path,
            allow_target_replace: bool,
            recheck_target_size: Optional[int],
    ) -> Tuple[bool, str]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False, "未找到 ffmpeg，无法进行蓝光原盘转封装"

        target_file.parent.mkdir(parents=True, exist_ok=True)
        temp_suffix = uuid.uuid4().hex
        tmp_file = target_file.with_name(f".{target_file.stem}.{temp_suffix}.tmp{target_file.suffix}")
        concat_file = target_file.with_name(f".{target_file.stem}.{temp_suffix}.ffconcat")
        try:
            if len(source_files) == 1 and not source_files[0].need_clip:
                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    source_files[0].path.as_posix(),
                    "-map",
                    "0",
                    "-c",
                    "copy",
                    "-dn",
                    tmp_file.as_posix(),
                ]
            else:
                concat_lines = ["ffconcat version 1.0"]
                for item in source_files:
                    concat_lines.append(f"file '{self.__escape_ffconcat_path(item.path)}'")
                    if item.in_time > 0:
                        concat_lines.append(f"inpoint {self.__format_bluray_time(item.in_time)}")
                    if item.out_time > 0:
                        concat_lines.append(f"outpoint {self.__format_bluray_time(item.out_time)}")
                concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
                command = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_file.as_posix(),
                    "-map",
                    "0",
                    "-c",
                    "copy",
                    "-dn",
                    tmp_file.as_posix(),
                ]

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout,
            )
            if completed.returncode != 0:
                errmsg = (completed.stderr or completed.stdout or "").strip()
                return False, f"ffmpeg 转封装失败：{errmsg or completed.returncode}"
            if not tmp_file.exists():
                return False, "ffmpeg 转封装完成但未生成目标文件"
            if tmp_file.stat().st_size <= 0:
                return False, "ffmpeg 转封装完成但输出文件为空"
            if not allow_target_replace and (target_file.exists() or target_file.is_symlink()):
                return False, f"{target_file} 在转封装期间被创建，取消覆盖"
            if recheck_target_size is not None and tmp_file.stat().st_size <= recheck_target_size:
                return False, "媒体库存在同名文件，且质量更好"
            tmp_file.replace(target_file)
            return True, ""
        except subprocess.TimeoutExpired:
            return False, f"ffmpeg 转封装超过 {self._timeout} 秒"
        except Exception as err:
            return False, f"蓝光原盘转封装失败：{err}"
        finally:
            for cleanup_file in [tmp_file, concat_file]:
                try:
                    if cleanup_file.exists():
                        cleanup_file.unlink()
                except OSError as err:
                    logger.warning(f"清理蓝光转封装临时文件失败：{cleanup_file} - {err}")

    def __check_overwrite(
            self,
            fileitem: FileItem,
            target_oper: StorageBase,
            target_file: Path,
            target_storage: str,
            transfer_type: str,
            overwrite_mode: Optional[str],
            source_size: int,
    ) -> Tuple[bool, str, bool]:
        target_item = self.__get_target_item(target_oper, target_storage, target_file)
        if not target_item:
            return True, "", False

        logger.info(f"目的文件系统中已经存在同名文件 {target_file}，当前整理覆盖模式设置为 {overwrite_mode}")
        overwrite_event_data = TransferOverwriteCheckEventData(
            fileitem=fileitem,
            target_item=target_item,
            target_storage=target_storage,
            target_path=target_file,
            overwrite_mode=overwrite_mode or "",
            transfer_type=transfer_type,
            options={"bluray_remux": True, "plugin": self.__class__.__name__},
        )
        overwrite_event = eventmanager.send_event(
            ChainEventType.TransferOverwriteCheck,
            overwrite_event_data,
        )
        if overwrite_event and overwrite_event.event_data:
            overwrite_event_data = overwrite_event.event_data
            if overwrite_event_data.overwrite is True:
                return True, "", False
            if overwrite_event_data.overwrite is False:
                return False, overwrite_event_data.reason or "插件决定不覆盖已有文件", False

        if overwrite_mode in ["always", "latest"]:
            return True, "", False
        if overwrite_mode == "size":
            if (target_item.size or 0) < source_size:
                return True, "", True
            return False, "媒体库存在同名文件，且质量更好", False
        if overwrite_mode == "never":
            return False, "媒体库存在同名文件，当前覆盖模式为不覆盖", False
        return False, f"{target_file} 已存在", False

    @staticmethod
    def __delete_version_files(storage_oper: StorageBase, path: Path) -> bool:
        if not storage_oper:
            return False
        meta = MetaInfoPath(path)
        season = meta.season
        episode = meta.episode
        part = meta.part
        logger.warn(f"正在删除目标目录中其它版本的文件：{path.parent}")
        parent_item = storage_oper.get_item(path.parent)
        if not parent_item:
            logger.warn(f"目录 {path.parent} 不存在")
            return False
        media_files = storage_oper.list(parent_item)
        if not media_files:
            logger.info(f"目录 {path.parent} 中没有文件")
            return False
        for media_file in media_files:
            media_path = Path(media_file.path)
            if media_path == path or media_file.type != "file":
                continue
            if f".{media_file.extension.lower()}" not in settings.RMT_MEDIAEXT:
                continue
            filemeta = MetaInfoPath(media_path)
            if filemeta.season != season or filemeta.episode != episode:
                continue
            if part and filemeta.part and filemeta.part != part:
                continue
            logger.info(f"正在删除文件：{media_file.name}")
            storage_oper.delete(media_file)
        return True

    @staticmethod
    def __escape_ffconcat_path(path: Path) -> str:
        value = path.as_posix()
        if "\n" in value or "\r" in value:
            raise ValueError("蓝光分片路径包含换行控制字符")
        return value.replace("'", "'\\''")

    @staticmethod
    def __format_bluray_time(value: int) -> str:
        return f"{value / _MPLS_TIME_BASE:.6f}".rstrip("0").rstrip(".")
