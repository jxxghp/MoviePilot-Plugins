from __future__ import annotations

import gc
import hashlib
import importlib.util
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body
from fastapi.responses import JSONResponse

from app.helper.thread import ThreadHelper
from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils

from .config import RuntimeSettings
from .database import Database
from .errors import Cancelled


class AnimeUpscale(_PluginBase):
    """在 MoviePilot 进程内执行动漫视频超分任务"""

    plugin_name = "动漫视频超分"
    plugin_desc = "在 MoviePilot 内直接使用 GPU 完成动漫视频 2 倍超分与 HEVC Main10 编码。"
    plugin_icon = "ffmpeg.png"
    plugin_version = "1.1.1"
    plugin_author = "RWDai"
    author_url = "https://github.com/RWDai/anime-upscale"
    plugin_config_prefix = "animeupscale_"
    plugin_order = 50
    auth_level = 1

    MODELS = {
        "starsample_v2_lite": {
            "label": "StarSample V2 Lite",
            "filename": "2x-StarSample-V2-Lite.safetensors",
            "sha256": "4008dfc72295bb48574a389bf4bd4e55d9af3766f34b6b68cc7bc0c78bd22a0b",
            "suffix": "starsample-2x",
        },
        "animesr_v2": {
            "label": "AnimeSR v2",
            "filename": "AnimeSR_v2.pth",
            "sha256": "d0f29c8966b53718828bd424bbdc306e7ff0cbf6350beadaf8b5b2500b108548",
            "suffix": "animesr-v2-2x",
        },
    }
    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".webm"}
    _MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024 * 1024
    _CHUNK_SIZE = 1024 * 1024

    _enabled = False
    _input_root = ""
    _output_root = ""
    _model_dir = ""
    _starsample_url = ""
    _animesr_url = ""
    _auto_download = False
    _input_path = ""
    _output_subdir = ""
    _recursive = True
    _cq = 18
    _model = "starsample_v2_lite"
    _gpu_index = 0
    _tile = 256
    _context = 32

    def init_plugin(self, config: dict = None):
        """停止旧 Worker，加载配置并恢复插件内部任务队列"""
        if hasattr(self, "_stop_event"):
            self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._input_root = str(config.get("input_root") or "").strip()
        self._output_root = str(config.get("output_root") or "").strip()
        data_path = self.get_data_path()
        self._model_dir = str(config.get("model_dir") or "").strip() or str(data_path / "models")
        self._starsample_url = str(config.get("starsample_url") or "").strip()
        self._animesr_url = str(config.get("animesr_url") or "").strip()
        self._auto_download = bool(config.get("auto_download"))
        self._input_path = str(config.get("input_path") or "").strip()
        self._output_subdir = str(config.get("output_subdir") or "").strip()
        self._recursive = bool(config.get("recursive", True))
        self._cq = self._bounded_int(config.get("cq"), 18, 0, 51)
        self._gpu_index = self._bounded_int(config.get("gpu_index"), 0, 0, 128)
        self._tile = self._bounded_int(config.get("tile"), 256, 64, 2048)
        self._context = self._bounded_int(config.get("context"), 32, 0, 512)
        model = str(config.get("model") or "starsample_v2_lite")
        self._model = model if model in self.MODELS else "starsample_v2_lite"

        self._runtime_settings = RuntimeSettings(
            model_dir=Path(self._model_dir),
            data_root=data_path,
            tile=self._tile,
            context=self._context,
            gpu_index=self._gpu_index,
        )
        self._database = Database(data_path / "jobs.sqlite3")
        self._database.recover_interrupted()
        self._stop_event = threading.Event()
        self._current_cancel: Optional[threading.Event] = None
        self._current_job_id: Optional[str] = None
        self._worker_guard = threading.Lock()
        self._worker_future: Optional[Future] = None
        self._worker_stopping = False
        self._process_lock = threading.Lock()
        self._active_processes: set[Any] = set()
        self._runtime: Optional[Any] = None
        self._runtime_name: Optional[str] = None
        self._download_lock = threading.Lock()
        self._download_state: Dict[str, dict] = {}
        self._hash_cache: Dict[str, Tuple[int, int, str]] = {}
        self._download_stop_event = threading.Event()
        self._download_future: Optional[Future] = None

        if self._enabled:
            if self._auto_download:
                self._start_auto_downloads()
            if self._database.has_queued():
                self._start_worker()

    def get_state(self) -> bool:
        """返回插件启用状态"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册远程命令"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册状态、任务和模型管理 API"""
        return [
            {"path": "/status", "endpoint": self.api_status, "methods": ["GET"], "auth": "bear", "summary": "获取超分状态"},
            {"path": "/jobs", "endpoint": self.api_jobs, "methods": ["GET"], "auth": "bear", "summary": "获取超分任务"},
            {"path": "/jobs", "endpoint": self.api_create_jobs, "methods": ["POST"], "auth": "bear", "summary": "创建超分任务"},
            {"path": "/jobs/cancel", "endpoint": self.api_cancel_job, "methods": ["POST"], "auth": "bear", "summary": "取消超分任务"},
            {"path": "/jobs/retry", "endpoint": self.api_retry_job, "methods": ["POST"], "auth": "bear", "summary": "重试超分任务"},
            {"path": "/models/verify", "endpoint": self.api_verify_models, "methods": ["POST"], "auth": "bear", "summary": "校验超分模型"},
            {"path": "/models/download", "endpoint": self.api_download_model, "methods": ["POST"], "auth": "bear", "summary": "下载超分模型"},
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回内嵌推理所需的路径、GPU 和模型配置"""
        fields = [
            self._field("VSwitch", "enabled", "启用插件", md=4),
            self._field("VTextField", "gpu_index", "GPU 编号", md=4, type="number"),
            self._field("VTextField", "cq", "HEVC CQ（0-51）", md=4, type="number"),
            self._field("VTextField", "input_root", "输入根目录", md=6, placeholder="/media"),
            self._field("VTextField", "output_root", "输出根目录", md=6, placeholder="/media-upscaled"),
            self._field("VTextField", "model_dir", "模型目录", placeholder=str(self.get_data_path() / "models")),
            self._field("VTextField", "starsample_url", "StarSample 下载地址（可选）"),
            self._field("VTextField", "animesr_url", "AnimeSR 下载地址（可选）"),
            self._field("VSwitch", "auto_download", "启用后自动下载缺失模型"),
            self._field("VTextField", "input_path", "默认输入相对路径", md=6),
            self._field("VTextField", "output_subdir", "默认输出子目录", md=6),
            self._field(
                "VSelect", "model", "默认模型", md=5,
                items=[{"title": item["label"], "value": key} for key, item in self.MODELS.items()],
            ),
            self._field("VTextField", "tile", "Tile 大小", md=3, type="number"),
            self._field("VTextField", "context", "Tile 上下文", md=2, type="number"),
            self._field("VSwitch", "recursive", "递归扫描", md=2),
        ]
        return [{"component": "VForm", "content": [{"component": "VRow", "content": fields}]}], self._current_config()

    def get_page(self) -> List[dict]:
        """返回本地运行环境、模型和任务详情页"""
        status = self._status()
        model_rows = [
            {
                "model": value["label"],
                "file": value["filename"],
                "state": {"valid": "校验通过", "missing": "缺失", "invalid": "校验失败", "downloading": "下载中", "failed": "下载失败"}.get(value["state"], value["state"]),
                "detail": value.get("message") or "-",
            }
            for value in status["models"].values()
        ]
        jobs = status["jobs"]
        job_rows = [
            {
                "id": job.get("id"), "input": job.get("input_path"),
                "model": job.get("model"), "status": job.get("status"),
                "progress": f"{float(job.get('progress') or 0):.1f}%",
                "fps": job.get("processing_fps") or 0, "error": job.get("error") or "-",
            }
            for job in jobs
        ]
        actions = []
        for job in jobs[:20]:
            job_id = str(job.get("id") or "")
            if job.get("status") in {"queued", "running"}:
                actions.append(self._action_button(f"取消 {job_id}", "mdi-cancel", "/jobs/cancel", {"job_id": job_id}, False))
            elif job.get("status") in {"failed", "cancelled"}:
                actions.append(self._action_button(f"重试 {job_id}", "mdi-replay", "/jobs/retry", {"job_id": job_id}, False))
        return [
            {"component": "VAlert", "props": {"type": "success" if status["ready"] else "warning", "variant": "tonal", "class": "mb-4", "text": status["summary"]}},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [{"component": "VDataTable", "props": {"density": "compact", "headers": [{"title": "模型", "key": "model"}, {"title": "文件", "key": "file"}, {"title": "状态", "key": "state"}, {"title": "说明", "key": "detail"}], "items": model_rows}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                    self._action_button("重新校验", "mdi-shield-check", "/models/verify"),
                    self._action_button("下载 StarSample", "mdi-download", "/models/download", {"model": "starsample_v2_lite"}),
                    self._action_button("下载 AnimeSR", "mdi-download", "/models/download", {"model": "animesr_v2"}),
                    self._action_button("提交默认任务", "mdi-play", "/jobs", self._default_job_payload()),
                ]},
            ]},
            {"component": "h3", "props": {"class": "mt-6 mb-2"}, "text": "最近任务"},
            {"component": "VDataTable", "props": {"density": "compact", "headers": [{"title": "ID", "key": "id"}, {"title": "输入", "key": "input"}, {"title": "模型", "key": "model"}, {"title": "状态", "key": "status"}, {"title": "进度", "key": "progress"}, {"title": "FPS", "key": "fps"}, {"title": "错误", "key": "error"}], "items": job_rows, "items-per-page": 20}},
            {"component": "div", "props": {"class": "d-flex flex-wrap ga-2 mt-3"}, "content": actions},
        ]

    def stop_service(self) -> None:
        """请求取消当前任务，等待 Worker 退出并释放 GPU 模型"""
        self._enabled = False
        stop_event = getattr(self, "_stop_event", None)
        if stop_event:
            stop_event.set()
        cancel_event = getattr(self, "_current_cancel", None)
        if cancel_event:
            cancel_event.set()
        self._terminate_active_processes()
        download_stop = getattr(self, "_download_stop_event", None)
        if download_stop:
            download_stop.set()
        future = getattr(self, "_worker_future", None)
        if future and not future.done():
            try:
                future.result()
            except Exception as error:
                logger.warning(f"动漫视频超分 Worker 退出异常：{error}")
        self._release_runtime()
        download_future = getattr(self, "_download_future", None)
        if download_future and not download_future.done():
            try:
                download_future.result()
            except Exception as error:
                logger.warning(f"动漫视频超分模型下载退出异常：{error}")

    def api_status(self) -> JSONResponse:
        """返回插件内部运行状态"""
        return JSONResponse(content=self._status())

    def api_jobs(self) -> JSONResponse:
        """返回本地任务队列"""
        return JSONResponse(content={"jobs": self._database.list()})

    def api_create_jobs(self, payload: Optional[dict] = Body(default=None)) -> JSONResponse:
        """校验根目录边界并将视频加入本地任务队列"""
        if not self._enabled:
            return self._response(409, "插件未启用")
        runtime = self._runtime_diagnostics()
        if runtime["errors"]:
            return self._response(503, "运行环境不可用：" + "；".join(runtime["errors"]))
        request = self._default_job_payload()
        if payload:
            request.update(payload)
        model = str(request.get("model") or "")
        if model not in self.MODELS:
            return self._response(400, "不支持的模型")
        if self._model_status(model)["state"] != "valid":
            return self._response(503, "所选模型缺失或校验失败")
        try:
            input_root = self._configured_root(self._input_root, "输入根目录")
            output_root = self._configured_root(self._output_root, "输出根目录")
            selected = self._inside(input_root, str(request.get("input_path") or ""))
            output_dir = self._inside(output_root, str(request.get("output_subdir") or ""))
            planned = self._plan_jobs(
                selected,
                output_dir,
                bool(request.get("recursive", True)),
                model,
                input_root,
                output_root,
            )
        except (ValueError, OSError) as error:
            return self._response(400, str(error))
        if not planned:
            return self._response(400, "没有找到支持的视频文件")
        if len(planned) > 500:
            return self._response(400, "一次最多添加 500 个视频")
        targets = [target for _, target in planned]
        if len(set(targets)) != len(targets):
            return self._response(409, "多个输入会写入同一个输出文件")
        for target in targets:
            if target.exists() or self._database.output_is_registered(target):
                return self._response(409, f"输出目标已存在或已登记：{target}")
        try:
            jobs = self._database.create_many(
                planned,
                self._bounded_int(request.get("cq"), 18, 0, 51),
                model,
            )
        except Exception as error:
            return self._response(409, f"创建任务失败：{error}")
        self._start_worker()
        return JSONResponse(status_code=201, content={"created": len(jobs), "jobs": jobs})

    def api_cancel_job(self, payload: dict = Body(...)) -> JSONResponse:
        """取消排队中或运行中的任务"""
        job_id = self._job_id(payload)
        if not job_id:
            return self._response(400, "无效的任务 ID")
        if not self._database.request_cancel(job_id):
            return self._response(409, "该任务当前不能取消")
        if job_id == self._current_job_id and self._current_cancel:
            self._current_cancel.set()
            self._terminate_active_processes()
        return JSONResponse(content={"ok": True})

    def api_retry_job(self, payload: dict = Body(...)) -> JSONResponse:
        """将失败或取消的任务重新加入队列"""
        job_id = self._job_id(payload)
        if not job_id:
            return self._response(400, "无效的任务 ID")
        if not self._database.retry(job_id):
            return self._response(409, "只有失败或已取消的任务可以重试")
        self._start_worker()
        return JSONResponse(content={"ok": True})

    def api_verify_models(self) -> JSONResponse:
        """清除摘要缓存并重新校验模型"""
        self._hash_cache.clear()
        self._download_state = {key: value for key, value in self._download_state.items() if value.get("state") == "downloading"}
        return JSONResponse(content={"models": self._model_statuses(force=True)})

    def api_download_model(self, payload: dict = Body(...)) -> JSONResponse:
        """提交单个模型下载任务"""
        model_id = str((payload or {}).get("model") or "")
        if model_id not in self.MODELS:
            return self._response(400, "不支持的模型")
        if not self._valid_download_url(self._model_url(model_id)):
            return self._response(400, "请先填写有效的 http/https 模型下载地址")
        if not self._download_lock.acquire(blocking=False):
            return self._response(409, "已有模型下载任务正在运行")
        try:
            self._download_future = ThreadHelper().submit(
                self._download_models,
                [model_id],
                True,
                self._download_stop_event,
            )
        except Exception as error:
            self._download_lock.release()
            return self._response(500, f"模型下载任务提交失败：{error}")
        return JSONResponse(status_code=202, content={"ok": True, "detail": "模型下载已开始"})

    def _start_worker(self) -> None:
        with self._worker_guard:
            if self._worker_stopping or not self._enabled or self._stop_event.is_set():
                return
            if self._worker_future and not self._worker_future.done():
                return
            worker_stop_event = self._stop_event
            self._worker_future = ThreadHelper().submit(
                self._drain_queue,
                worker_stop_event,
            )

    def _drain_queue(
        self,
        worker_stop_event: Optional[threading.Event] = None,
    ) -> None:
        worker_stop_event = worker_stop_event or self._stop_event
        try:
            while self._enabled and not worker_stop_event.is_set():
                job = self._database.claim_next()
                if not job:
                    break
                self._run_job(job)
        finally:
            with self._worker_guard:
                if worker_stop_event is self._stop_event:
                    self._worker_future = None
                    self._worker_stopping = False
                    if self._enabled and not worker_stop_event.is_set() and self._database.has_queued():
                        self._worker_future = ThreadHelper().submit(
                            self._drain_queue,
                            worker_stop_event,
                        )
            if worker_stop_event.is_set():
                self._release_runtime()

    def _run_job(self, job: dict) -> None:
        job_id = job["id"]
        cancel_event = threading.Event()
        self._current_job_id = job_id
        self._current_cancel = cancel_event
        try:
            current = self._database.get(job_id)
            if current and current.get("cancel_requested"):
                raise Cancelled()
            runtime = self._get_runtime(job.get("model") or "starsample_v2_lite", job_id)
            from .pipeline import run_pipeline

            run_pipeline(
                job, runtime, self._runtime_settings, cancel_event,
                lambda frame, total, fps, eta: self._database.update_progress(job_id, frame, total, fps, eta),
                lambda message: self._append_log(job_id, message),
                self._track_process,
            )
            self._database.finish(job_id, "completed")
        except Cancelled:
            self._append_log(job_id, "任务已取消")
            self._database.finish(job_id, "cancelled")
        except Exception as error:
            self._append_log(job_id, f"失败：{error}")
            self._database.finish(job_id, "failed", str(error)[:1000])
            logger.error(f"动漫视频超分任务 {job_id} 失败：{error}")
        finally:
            self._current_job_id = None
            self._current_cancel = None

    def _get_runtime(self, model: str, job_id: str) -> Any:
        if self._runtime is not None and self._runtime_name == model:
            return self._runtime
        self._release_runtime()
        self._append_log(job_id, f"正在加载模型：{self.MODELS[model]['label']}")
        from .pipeline import AnimeSRRuntime, StarSampleRuntime

        runtime_class = AnimeSRRuntime if model == "animesr_v2" else StarSampleRuntime
        self._runtime = runtime_class(self._runtime_settings, lambda message: self._append_log(job_id, message))
        self._runtime_name = model
        return self._runtime

    def _release_runtime(self) -> None:
        self._runtime = None
        self._runtime_name = None
        gc.collect()
        try:
            torch = importlib.import_module("torch")

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _append_log(self, job_id: str, message: str) -> None:
        log_root = self._runtime_settings.log_root
        log_root.mkdir(parents=True, exist_ok=True)
        with (log_root / f"{job_id}.log").open("a", encoding="utf-8") as stream:
            stream.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

    def _track_process(self, process: Any, active: bool) -> None:
        with self._process_lock:
            if active:
                self._active_processes.add(process)
            else:
                self._active_processes.discard(process)

    def _terminate_active_processes(self) -> None:
        with getattr(self, "_process_lock", threading.Lock()):
            active_processes = list(getattr(self, "_active_processes", set()))
        if not active_processes:
            return
        from .pipeline import terminate

        for process in active_processes:
            terminate(process)

    def _status(self) -> dict:
        runtime = self._runtime_diagnostics()
        ffmpeg_ready = runtime["ffmpeg_ready"]
        nvenc_ready = runtime["nvenc_ready"]
        missing_dependencies = runtime["missing_dependencies"]
        cuda_ready = runtime["cuda_ready"]
        gpu = runtime["gpu"]
        models = self._model_statuses()
        ready = self._enabled and not runtime["errors"]
        summary = (
            f"插件内嵌推理 | GPU：{gpu or '不可用'} | "
            f"FFmpeg/NVENC：{'可用' if ffmpeg_ready and nvenc_ready else '不可用'} | "
            f"依赖：{'完整' if not missing_dependencies else '缺少 ' + ', '.join(missing_dependencies)} | "
            f"当前任务：{self._current_job_id or '空闲'}"
        )
        return {
            "enabled": self._enabled, "ready": ready, "summary": summary,
            "cuda_ready": cuda_ready, "gpu": gpu, "gpu_index": self._gpu_index,
            "ffmpeg_ready": ffmpeg_ready, "nvenc_ready": nvenc_ready,
            "missing_dependencies": missing_dependencies,
            "runtime_errors": runtime["errors"],
            "current_job_id": self._current_job_id,
            "input_root": self._input_root, "output_root": self._output_root,
            "model_dir": self._model_dir, "models": models, "jobs": self._database.list(),
        }

    def _runtime_diagnostics(self) -> dict:
        ffmpeg_ready = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        nvenc_ready = False
        if ffmpeg_ready:
            try:
                result = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-encoders"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                nvenc_ready = result.returncode == 0 and "hevc_nvenc" in result.stdout
            except (OSError, subprocess.SubprocessError):
                nvenc_ready = False
        missing_dependencies = [
            name
            for name in ("torch", "cv2", "spandrel", "spandrel_extra_arches")
            if importlib.util.find_spec(name) is None
        ]
        cuda_ready = False
        gpu = None
        if not missing_dependencies:
            try:
                torch = importlib.import_module("torch")

                cuda_ready = (
                    torch.cuda.is_available()
                    and self._gpu_index < torch.cuda.device_count()
                )
                if cuda_ready:
                    gpu = torch.cuda.get_device_name(self._gpu_index)
            except Exception:
                cuda_ready = False
        errors = []
        if missing_dependencies:
            errors.append("缺少 Python 依赖 " + ", ".join(missing_dependencies))
        if not ffmpeg_ready:
            errors.append("缺少 ffmpeg 或 ffprobe")
        elif not nvenc_ready:
            errors.append("FFmpeg 不包含 hevc_nvenc 编码器")
        if not cuda_ready:
            errors.append(f"CUDA GPU {self._gpu_index} 不可用")
        return {
            "ffmpeg_ready": ffmpeg_ready,
            "nvenc_ready": nvenc_ready,
            "missing_dependencies": missing_dependencies,
            "cuda_ready": cuda_ready,
            "gpu": gpu,
            "errors": errors,
        }

    def _plan_jobs(
        self,
        selected: Path,
        output_dir: Path,
        recursive: bool,
        model: str,
        input_root: Path,
        output_root: Path,
    ) -> list[tuple[Path, Path]]:
        if not selected.exists():
            raise ValueError("输入路径不存在")
        if selected.is_file():
            files = [selected] if selected.suffix.lower() in self.VIDEO_EXTENSIONS else []
            base = selected.parent
        else:
            pattern = "**/*" if recursive else "*"
            files = sorted(path for path in selected.glob(pattern) if path.is_file() and path.suffix.lower() in self.VIDEO_EXTENSIONS)
            base = selected
        suffix = self.MODELS[model]["suffix"]
        planned = []
        for source in files:
            relative_parent = source.parent.relative_to(base) if selected.is_dir() else Path()
            resolved_source = self._within_root(input_root, source, "输入文件")
            target = output_dir / relative_parent / f"{source.stem}.{suffix}.mkv"
            resolved_target = self._within_root(output_root, target, "输出目标")
            planned.append((resolved_source, resolved_target))
        return planned

    @staticmethod
    def _configured_root(value: str, label: str) -> Path:
        if not value:
            raise ValueError(f"请先配置{label}")
        root = Path(value).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"{label}不存在或不是目录：{root}")
        return root

    @staticmethod
    def _inside(root: Path, relative: str) -> Path:
        requested = Path(relative)
        if requested.is_absolute():
            raise ValueError("任务路径必须是根目录内的相对路径")
        candidate = (root / requested).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("任务路径超出配置的根目录") from error
        return candidate

    @staticmethod
    def _within_root(root: Path, candidate: Path, label: str) -> Path:
        """解析符号链接后确认路径仍位于配置根目录内。"""
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(f"{label}超出配置的根目录：{candidate}") from error
        return resolved_candidate

    def _model_statuses(self, force: bool = False) -> Dict[str, dict]:
        return {model_id: self._model_status(model_id, force) for model_id in self.MODELS}

    def _model_status(self, model_id: str, force: bool = False) -> dict:
        model = self.MODELS[model_id]
        path = Path(self._model_dir) / model["filename"]
        download = self._download_state.get(model_id, {})
        if download.get("state") in {"downloading", "failed"}:
            return {**model, **download, "path": str(path)}
        if not path.is_file():
            return {**model, "path": str(path), "state": "missing", "message": "文件不存在"}
        try:
            digest = self._file_sha256(path, force)
        except OSError as error:
            return {**model, "path": str(path), "state": "invalid", "message": str(error)}
        valid = digest == model["sha256"]
        return {**model, "path": str(path), "size": path.stat().st_size, "sha256_actual": digest, "state": "valid" if valid else "invalid", "message": "SHA256 匹配" if valid else "SHA256 不匹配"}

    def _file_sha256(self, path: Path, force: bool = False) -> str:
        stat = path.stat()
        cache = self._hash_cache.get(str(path))
        key = (stat.st_mtime_ns, stat.st_size)
        if not force and cache and cache[:2] == key:
            return cache[2]
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(self._CHUNK_SIZE):
                digest.update(chunk)
        value = digest.hexdigest()
        self._hash_cache[str(path)] = (*key, value)
        return value

    def _start_auto_downloads(self) -> None:
        model_ids = [
            key for key, model in self.MODELS.items()
            if not (Path(self._model_dir) / model["filename"]).is_file()
            and self._valid_download_url(self._model_url(key))
        ]
        if not model_ids or not self._download_lock.acquire(blocking=False):
            return
        try:
            self._download_future = ThreadHelper().submit(
                self._download_models,
                model_ids,
                True,
                self._download_stop_event,
            )
        except Exception as error:
            self._download_lock.release()
            logger.error(f"动漫视频超分自动下载任务提交失败：{error}")

    def _download_models(
        self,
        model_ids: List[str],
        lock_acquired: bool = False,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        if not lock_acquired:
            self._download_lock.acquire()
        try:
            for model_id in model_ids:
                if cancel_event and cancel_event.is_set():
                    break
                self._download_model_file(
                    model_id,
                    self._model_url(model_id),
                    cancel_event,
                )
        finally:
            self._download_lock.release()

    def _download_model_file(
        self,
        model_id: str,
        url: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        model = self.MODELS[model_id]
        directory = Path(self._model_dir)
        target = directory / model["filename"]
        temporary = directory / f".{model['filename']}.part"
        self._download_state[model_id] = {"state": "downloading", "message": "正在下载"}
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with RequestUtils(
                ua="MoviePilot-AnimeUpscale/1.1", timeout=60
            ).get_stream(url) as response:
                if response is None:
                    raise ConnectionError("无法连接模型下载地址")
                response.raise_for_status()
                length = response.headers.get("Content-Length")
                if length and int(length) > self._MAX_DOWNLOAD_BYTES:
                    raise ValueError("模型文件超过 10 GiB 限制")
                total = 0
                digest = hashlib.sha256()
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=self._CHUNK_SIZE):
                        if not chunk:
                            continue
                        if cancel_event and cancel_event.is_set():
                            raise Cancelled("模型下载已取消")
                        total += len(chunk)
                        if total > self._MAX_DOWNLOAD_BYTES:
                            raise ValueError("模型文件超过 10 GiB 限制")
                        output.write(chunk)
                        digest.update(chunk)
            if digest.hexdigest() != model["sha256"]:
                raise ValueError("下载文件 SHA256 不匹配")
            os.replace(temporary, target)
            self._hash_cache.pop(str(target), None)
            self._download_state[model_id] = {"state": "valid", "message": "下载完成且校验通过"}
            logger.info(f"动漫视频超分模型下载完成：{target}")
        except Exception as error:
            temporary.unlink(missing_ok=True)
            self._download_state[model_id] = {"state": "failed", "message": str(error)}
            logger.error(f"动漫视频超分模型下载失败：{model['label']} - {error}")

    def _model_url(self, model_id: str) -> str:
        return self._animesr_url if model_id == "animesr_v2" else self._starsample_url

    @staticmethod
    def _valid_download_url(value: str) -> bool:
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _job_id(payload: dict) -> str:
        job_id = str((payload or {}).get("job_id") or "").strip()
        return job_id if job_id and all(char.isalnum() or char in "-_" for char in job_id) else ""

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return min(max(int(value), minimum), maximum)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _response(status: int, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": detail})

    def _default_job_payload(self) -> dict:
        return {"input_path": self._input_path, "output_subdir": self._output_subdir, "recursive": self._recursive, "cq": self._cq, "model": self._model}

    def _current_config(self) -> dict:
        return {
            "enabled": self._enabled, "input_root": self._input_root,
            "output_root": self._output_root, "model_dir": self._model_dir,
            "starsample_url": self._starsample_url, "animesr_url": self._animesr_url,
            "auto_download": self._auto_download, "gpu_index": self._gpu_index,
            "tile": self._tile, "context": self._context, **self._default_job_payload(),
        }

    @staticmethod
    def _field(component: str, model: str, label: str, md: Optional[int] = None, **props) -> dict:
        column = {"cols": 12}
        if md:
            column["md"] = md
        return {"component": "VCol", "props": column, "content": [{"component": component, "props": {"model": model, "label": label, **props}}]}

    def _action_button(self, text: str, icon: str, path: str, params: Optional[dict] = None, block: bool = True) -> dict:
        event = {"api": f"plugin/{self.__class__.__name__}{path}", "method": "post"}
        if params is not None:
            event["params"] = params
        return {"component": "VBtn", "props": {"class": "ma-1", "variant": "tonal", "prepend-icon": icon, "block": block}, "text": text, "events": {"click": event}}
