from datetime import datetime, timedelta
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.core.config import settings
from app.chain import ChainBase
from app.chain.storage import StorageChain
from app.core.event import eventmanager
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.transferhistory_oper import TransferHistoryOper
from app.helper.service import ServiceConfigHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType

from .disc_remuxer import DiscRemuxer


class DiscRemuxPlugin(_PluginBase):
    plugin_name = "蓝光原盘重封装"
    plugin_desc = "基于最近整理历史查找蓝光原盘，使用 MakeMKV 重封装到媒体库条目目录。"
    plugin_icon = "https://raw.githubusercontent.com/the-bruz/MoviePilot-Plugins/main/icons/discremuxplugin.png"
    plugin_version = "1.0.2"

    plugin_author = "bruz"
    author_url = "https://github.com/the-bruz"

    plugin_config_prefix = "discremux_"
    plugin_order = 10
    auth_level = 1

    _DATA_KEY = "processed_histories"
    _enabled = False
    _message = "插件尚未初始化"
    _stop_event = threading.Event()
    _scheduler: Optional[BackgroundScheduler] = None
    _remuxer: Optional[DiscRemuxer] = None

    def init_plugin(self, config: dict = None):
        """根据当前配置初始化插件。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._message = config.get("message") or "插件初始化完成，等待定时任务执行。"
        self._stop_event = threading.Event()

        if config.get("run_once"):
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("蓝光原盘重封装服务启动，立即运行一次")
            self._scheduler.add_job(
                self.remux,
                "date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="蓝光原盘重封装",
            )
            self._scheduler.start()
            config["run_once"] = False
            self.update_config(config)

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        """注册后台定时任务。"""
        if not self.get_state():
            return []

        cron_str = (self.get_config() or {}).get("cron_schedule") or "0 3 * * *"
        return [
            {
                "id": f"{self.__class__.__name__}.remux",
                "name": "定时重封装最近整理的蓝光原盘",
                "trigger": CronTrigger.from_crontab(cron_str),
                "func": self.remux,
                "kwargs": {},
            }
        ]

    def stop_service(self):
        """停止正在执行的重封装任务。"""
        self._stop_event.set()
        logger.info("收到停用信号，正在终止 MakeMKV 重封装任务...")
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None
            except Exception as e:
                logger.warning(f"关闭一次性调度器失败: {e}")
        if self._remuxer:
            try:
                self._remuxer.terminate()
            except Exception as e:
                logger.error(f"尝试终止 MakeMKV 进程时发生异常: {e}")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        json_path = Path(__file__).parent / "form_ui.json"
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                form_ui = json.load(f)
        except Exception as e:
            logger.error(f"加载表单配置失败: {json_path} | 错误详情: {e}")
            raise RuntimeError(f"插件 UI 配置加载失败: {e}") from e

        default_config = {
            "enabled": False,
            "run_once": False,
            "recent_days": 7,
            "min_mkv_size_gb": 5,
            "movies_only": True,
            "bdmv_action": "ignore",
            "delete_download_source": False,
            "refresh_media_server": True,
            "cron_schedule": "0 3 * * *",
        }
        return form_ui, default_config

    def get_page(self) -> List[dict]:
        """返回详情页 JSON。"""
        histories = self._get_processed_histories()[:20]
        table_rows = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "output": item.get("output"),
                "time": item.get("time"),
            }
            for item in histories
        ]
        return [
            {
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal", "text": self._message},
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "secondary",
                    "variant": "tonal",
                    "text": f"插件数据目录：{self.get_data_path()}",
                },
            },
            {
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": "History ID", "key": "id"},
                        {"title": "标题", "key": "title"},
                        {"title": "输出", "key": "output"},
                        {"title": "时间", "key": "time"},
                    ],
                    "items": table_rows,
                    "items-per-page": 10,
                    "density": "compact",
                },
            },
        ]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def _get_processed_histories(self) -> List[dict]:
        data = self.get_data(self._DATA_KEY)
        return data if isinstance(data, list) else []

    def _save_processed_history(self, history, output_file: Path) -> None:
        histories = [
            item for item in self._get_processed_histories()
            if str(item.get("id")) != str(history.id)
        ]
        histories.insert(
            0,
            {
                "id": history.id,
                "title": history.title or Path(str(history.dest or "")).name,
                "src": history.src,
                "dest": history.dest,
                "output": output_file.as_posix(),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self.save_data(self._DATA_KEY, histories[:200])

    def _is_processed(self, history_id: int) -> bool:
        return any(str(item.get("id")) == str(history_id) for item in self._get_processed_histories())

    @staticmethod
    def _is_valid_bdmv_dir(path: Optional[Path]) -> bool:
        if not path or not path.exists() or not path.is_dir():
            return False
        try:
            marker_files = {item.name.lower() for item in path.iterdir() if item.is_file()}
        except OSError:
            return False
        return "index.bdmv" in marker_files or "movieobject.bdmv" in marker_files

    @staticmethod
    def _resolve_movie_dir(dest: str) -> Path:
        dest_path = Path(dest)
        if dest_path.name.upper() == "BDMV":
            return dest_path.parent
        if dest_path.exists() and dest_path.is_file():
            return dest_path.parent
        if dest_path.suffix:
            return dest_path.parent
        return dest_path

    @classmethod
    def _resolve_old_bdmv_dir(cls, dest: str, movie_dir: Path) -> Optional[Path]:
        dest_path = Path(dest)
        parts = list(dest_path.parts)
        for index, part in enumerate(parts):
            if part.upper() == "BDMV":
                bdmv_dir = Path(*parts[: index + 1])
                return bdmv_dir if cls._is_valid_bdmv_dir(bdmv_dir) else None
        candidate = movie_dir / "BDMV"
        return candidate if cls._is_valid_bdmv_dir(candidate) else None

    @classmethod
    def _is_bdmv_history(cls, history) -> bool:
        if not history or not history.dest:
            return False
        movie_dir = cls._resolve_movie_dir(history.dest)
        old_bdmv_dir = cls._resolve_old_bdmv_dir(history.dest, movie_dir)
        return cls._is_valid_bdmv_dir(old_bdmv_dir)

    @staticmethod
    def _target_mkv_exists(output_file: Path, min_size_gb: float) -> bool:
        min_size = int(min_size_gb * 1024 * 1024 * 1024)
        return output_file.exists() and output_file.is_file() and output_file.stat().st_size > min_size

    @staticmethod
    def _has_ignore_file(old_bdmv_dir: Optional[Path]) -> bool:
        return bool(old_bdmv_dir and (old_bdmv_dir / ".ignore").exists())

    @staticmethod
    def _touch_ignore_file(old_bdmv_dir: Optional[Path]) -> None:
        if not old_bdmv_dir or not old_bdmv_dir.exists() or not old_bdmv_dir.is_dir():
            logger.warning(f"旧 BDMV 目录不存在，无法创建 .ignore: {old_bdmv_dir}")
            return
        (old_bdmv_dir / ".ignore").touch(exist_ok=True)

    @staticmethod
    def _delete_old_bdmv(movie_dir: Path, old_bdmv_dir: Optional[Path]) -> None:
        for target in [old_bdmv_dir, movie_dir / "CERTIFICATE"]:
            if target and target.exists() and target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                logger.info(f"已删除旧媒体库原盘目录: {target}")

    @staticmethod
    def _media_type(history) -> Optional[MediaType]:
        if history.type == MediaType.MOVIE.value:
            return MediaType.MOVIE
        if history.type == MediaType.TV.value:
            return MediaType.TV
        return None

    def _cleanup_transfer_history(self, history, delete_source: bool) -> None:
        transferhis = TransferHistoryOper()
        storage_chain = StorageChain()

        if delete_source and history.src_fileitem:
            src_fileitem = schemas.FileItem(**history.src_fileitem)
            if not storage_chain.delete_media_file(src_fileitem):
                raise RuntimeError(f"下载源删除失败: {src_fileitem.path}")
            DownloadHistoryOper().delete_file_by_fullpath(Path(src_fileitem.path).as_posix())
            eventmanager.send_event(
                EventType.DownloadFileDeleted,
                {"src": history.src, "hash": history.download_hash},
            )
            logger.info(f"已删除下载源: history_id={history.id}, src={history.src}")

        transferhis.delete(history.id)
        logger.info(f"已删除整理记录: history_id={history.id}")

    def _refresh_media_server(self, history, output_file: Path) -> None:
        item = schemas.RefreshMediaItem(
            title=history.title,
            year=history.year,
            type=self._media_type(history),
            category=history.category,
            target_path=output_file,
        )
        if not ServiceConfigHelper.get_mediaserver_configs():
            logger.info("未配置媒体服务器，跳过媒体库刷新。")
            return
        try:
            ChainBase().run_module("refresh_library_by_items", items=[item])
            logger.info(f"已尝试刷新媒体服务器条目: path={output_file}")
        except Exception as e:
            logger.warning(f"刷新媒体服务器失败: path={output_file}, error={e}")

    def remux(self) -> bool:
        """从整理历史中查找 BDMV 记录并调度重封装。"""
        self._stop_event.clear()
        config = self.get_config() or {}
        recent_days = int(config.get("recent_days") or 7)
        min_mkv_size_gb = float(config.get("min_mkv_size_gb") or 5)
        movies_only = bool(config.get("movies_only", True))
        bdmv_action = config.get("bdmv_action") or "ignore"
        delete_download_source = bool(config.get("delete_download_source"))
        refresh_media_server = bool(config.get("refresh_media_server", True))

        since_time = (datetime.now() - timedelta(days=recent_days)).strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"开始查询最近 {recent_days} 天整理历史: since_time={since_time}")
        histories = TransferHistoryOper().list_by_date(since_time)
        candidates = [history for history in histories if self._is_bdmv_history(history)]
        logger.info(f"找到 BDMV 整理历史 {len(candidates)} 条。")

        remuxer = DiscRemuxer()
        self._remuxer = remuxer
        try:
            remuxer.validate_environment()
        except Exception:
            self._remuxer = None
            raise

        processed_count = 0
        for history in candidates:
            if self._stop_event.is_set():
                logger.info("任务已被中止。")
                break

            history_id = history.id
            if movies_only and history.type != MediaType.MOVIE.value:
                logger.info(f"跳过非电影记录: history_id={history_id}, type={history.type}, dest={history.dest}")
                continue
            if self._is_processed(history_id):
                logger.info(f"跳过已记录处理的整理历史: history_id={history_id}")
                continue

            movie_dir = self._resolve_movie_dir(history.dest)
            old_bdmv_dir = self._resolve_old_bdmv_dir(history.dest, movie_dir)
            output_file = movie_dir / f"{movie_dir.name}.mkv"

            logger.info(
                "准备处理光盘源: "
                f"history_id={history_id}, src={history.src}, dest={history.dest}, "
                f"input={old_bdmv_dir.parent if old_bdmv_dir else None}, "
                f"output={output_file}, old_bdmv_action={bdmv_action}"
            )

            if self._target_mkv_exists(output_file, min_mkv_size_gb):
                logger.info(
                    f"目标 MKV 已存在且大于阈值，跳过: history_id={history_id}, output={output_file}, "
                    f"threshold={min_mkv_size_gb}GB"
                )
                continue
            if self._has_ignore_file(old_bdmv_dir):
                logger.info(f"旧 BDMV 已存在 .ignore，跳过: history_id={history_id}, old_bdmv={old_bdmv_dir}")
                continue
            if not self._is_valid_bdmv_dir(old_bdmv_dir):
                logger.warning(f"媒体库旧 BDMV 不存在，跳过: history_id={history_id}, old_bdmv={old_bdmv_dir}")
                continue
            media_source_root = old_bdmv_dir.parent

            try:
                remuxer.remux_to_mkv(
                    source_root_path=media_source_root.as_posix(),
                    output_file_path=output_file.as_posix(),
                    progress_callback=lambda progress, hid=history_id: logger.info(
                        f"当前文件 remux 进度: history_id={hid}, progress={progress}%"
                    ),
                )
                if self._stop_event.is_set():
                    raise InterruptedError("用户发送了停用信号。")

                if bdmv_action == "delete_bdmv":
                    self._delete_old_bdmv(movie_dir, old_bdmv_dir)
                else:
                    self._touch_ignore_file(old_bdmv_dir)
                    logger.info(f"已在旧 BDMV 内创建 .ignore: history_id={history_id}, old_bdmv={old_bdmv_dir}")

                if delete_download_source:
                    self._cleanup_transfer_history(history, delete_source=True)

                self._save_processed_history(history, output_file)
                if refresh_media_server:
                    self._refresh_media_server(history, output_file)
                processed_count += 1
            except subprocess.CalledProcessError as e:
                logger.error(f"MakeMKV 处理失败: history_id={history_id}, stderr={e.stderr}")
            except Exception as e:
                logger.error(f"处理整理历史失败: history_id={history_id}, error={e}", exc_info=True)

        self._message = f"最近一次执行完成：候选 {len(candidates)} 条，成功处理 {processed_count} 条。"
        self._remuxer = None
        logger.info(self._message)
        return True
