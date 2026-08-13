from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body
from fastapi.responses import JSONResponse

from app.helper.thread import ThreadHelper
from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils


class AnimeUpscale(_PluginBase):
    """
    Anime Upscale 服务客户端，负责模型文件管理与超分任务操作
    """
    plugin_name = "动漫视频超分"
    plugin_desc = "连接 Anime Upscale GPU 服务，管理模型并提交、取消和重试视频超分任务。"
    plugin_icon = "ffmpeg.png"
    plugin_version = "1.0.0"
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
        },
        "animesr_v2": {
            "label": "AnimeSR v2",
            "filename": "AnimeSR_v2.pth",
            "sha256": "d0f29c8966b53718828bd424bbdc306e7ff0cbf6350beadaf8b5b2500b108548",
        },
    }
    _MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024 * 1024
    _CHUNK_SIZE = 1024 * 1024

    _enabled = False
    _service_url = "http://anime-upscale:8787"
    _model_dir = ""
    _starsample_url = ""
    _animesr_url = ""
    _auto_download = False
    _input_path = ""
    _output_subdir = ""
    _recursive = True
    _cq = 18
    _model = "starsample_v2_lite"

    def init_plugin(self, config: dict = None):
        """加载插件配置并初始化运行时状态"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._service_url = self._normalize_service_url(
            config.get("service_url") or "http://anime-upscale:8787"
        )
        configured_dir = str(config.get("model_dir") or "").strip()
        self._model_dir = configured_dir or str(self.get_data_path() / "models")
        self._starsample_url = str(config.get("starsample_url") or "").strip()
        self._animesr_url = str(config.get("animesr_url") or "").strip()
        self._auto_download = bool(config.get("auto_download"))
        self._input_path = str(config.get("input_path") or "").strip()
        self._output_subdir = str(config.get("output_subdir") or "").strip()
        self._recursive = bool(config.get("recursive", True))
        self._cq = self._bounded_int(config.get("cq"), 18, 0, 51)
        model = str(config.get("model") or "starsample_v2_lite")
        self._model = model if model in self.MODELS else "starsample_v2_lite"
        if not hasattr(self, "_download_lock"):
            self._download_lock = threading.Lock()
        if not hasattr(self, "_download_state"):
            self._download_state: Dict[str, dict] = {}
        if not hasattr(self, "_hash_cache"):
            self._hash_cache: Dict[str, Tuple[int, int, str]] = {}
        if self._enabled and self._auto_download:
            self._start_auto_downloads()

    def get_state(self) -> bool:
        """返回插件启用状态"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册远程命令"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册服务代理、任务管理和模型管理 API"""
        return [
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取超分服务与模型状态",
            },
            {
                "path": "/jobs",
                "endpoint": self.api_jobs,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取超分任务",
            },
            {
                "path": "/jobs",
                "endpoint": self.api_create_jobs,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "创建超分任务",
            },
            {
                "path": "/jobs/cancel",
                "endpoint": self.api_cancel_job,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "取消超分任务",
            },
            {
                "path": "/jobs/retry",
                "endpoint": self.api_retry_job,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "重试超分任务",
            },
            {
                "path": "/models/verify",
                "endpoint": self.api_verify_models,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "校验超分模型",
            },
            {
                "path": "/models/download",
                "endpoint": self.api_download_model,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "下载超分模型",
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回插件配置表单和默认配置"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            self._field(
                                "VSwitch", "enabled", "启用插件", cols=12, md=4
                            ),
                            self._field(
                                "VTextField",
                                "service_url",
                                "Anime Upscale 服务地址",
                                cols=12,
                                md=8,
                                placeholder="http://anime-upscale:8787",
                            ),
                            self._field(
                                "VTextField",
                                "model_dir",
                                "共享模型目录",
                                cols=12,
                                placeholder=str(self.get_data_path() / "models"),
                            ),
                            self._field(
                                "VTextField",
                                "starsample_url",
                                "StarSample 下载地址（可选）",
                                cols=12,
                            ),
                            self._field(
                                "VTextField",
                                "animesr_url",
                                "AnimeSR 下载地址（可选）",
                                cols=12,
                            ),
                            self._field(
                                "VSwitch",
                                "auto_download",
                                "启用后自动下载缺失模型",
                                cols=12,
                            ),
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "模型目录必须同时挂载到 MoviePilot 和 anime-upscale 容器；下载后会强制校验 SHA256。",
                                        },
                                    }
                                ],
                            },
                            self._field(
                                "VTextField",
                                "input_path",
                                "默认输入路径（服务媒体根目录内的相对路径）",
                                cols=12,
                                md=8,
                            ),
                            self._field(
                                "VTextField",
                                "output_subdir",
                                "默认输出子目录",
                                cols=12,
                                md=4,
                            ),
                            self._field(
                                "VSelect",
                                "model",
                                "默认模型",
                                cols=12,
                                md=5,
                                items=[
                                    {"title": item["label"], "value": model_id}
                                    for model_id, item in self.MODELS.items()
                                ],
                            ),
                            self._field(
                                "VTextField",
                                "cq",
                                "HEVC CQ（0-51）",
                                cols=12,
                                md=3,
                                type="number",
                            ),
                            self._field(
                                "VSwitch",
                                "recursive",
                                "递归扫描目录",
                                cols=12,
                                md=4,
                            ),
                        ],
                    }
                ],
            }
        ], self._current_config()

    def get_page(self) -> List[dict]:
        """返回服务、模型和任务状态详情页"""
        status = self._combined_status()
        service = status["service"]
        rows = []
        for model_id, model_status in status["models"].items():
            state = model_status["state"]
            rows.append(
                {
                    "model": model_status["label"],
                    "file": model_status["filename"],
                    "state": {
                        "valid": "校验通过",
                        "missing": "缺失",
                        "invalid": "校验失败",
                        "checking": "校验中",
                        "downloading": "下载中",
                        "failed": "下载失败",
                    }.get(state, state),
                    "detail": model_status.get("message") or "-",
                    "action": model_id,
                }
            )

        jobs = service.get("jobs") if isinstance(service.get("jobs"), list) else []
        job_rows = [
            {
                "id": job.get("id"),
                "input": job.get("input_path"),
                "model": job.get("model"),
                "status": job.get("status"),
                "progress": f"{float(job.get('progress') or 0):.1f}%",
                "fps": job.get("processing_fps") or 0,
                "error": job.get("error") or "-",
            }
            for job in jobs
        ]
        job_actions = []
        for job in jobs[:20]:
            job_id = str(job.get("id") or "")
            job_status = job.get("status")
            if job_status in {"queued", "running"}:
                job_actions.append(
                    self._action_button(
                        f"取消 {job_id}",
                        "mdi-cancel",
                        "/jobs/cancel",
                        "post",
                        {"job_id": job_id},
                        block=False,
                    )
                )
            elif job_status in {"failed", "cancelled"}:
                job_actions.append(
                    self._action_button(
                        f"重试 {job_id}",
                        "mdi-replay",
                        "/jobs/retry",
                        "post",
                        {"job_id": job_id},
                        block=False,
                    )
                )
        return [
            {
                "component": "div",
                "props": {"class": "d-flex align-center mb-4"},
                "content": [
                    {"component": "h2", "text": "动漫视频超分"},
                    {"component": "VSpacer"},
                    self._action_button("刷新", "mdi-refresh", "/status"),
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "success" if service.get("online") else "warning",
                    "variant": "tonal",
                    "class": "mb-4",
                    "text": self._service_summary(service),
                },
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 8},
                        "content": [
                            {
                                "component": "VDataTable",
                                "props": {
                                    "density": "compact",
                                    "headers": [
                                        {"title": "模型", "key": "model"},
                                        {"title": "文件", "key": "file"},
                                        {"title": "状态", "key": "state"},
                                        {"title": "说明", "key": "detail"},
                                    ],
                                    "items": rows,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            self._action_button(
                                "校验模型", "mdi-shield-check", "/models/verify", "post"
                            ),
                            self._action_button(
                                "下载 StarSample",
                                "mdi-download",
                                "/models/download",
                                "post",
                                {"model": "starsample_v2_lite"},
                            ),
                            self._action_button(
                                "下载 AnimeSR",
                                "mdi-download",
                                "/models/download",
                                "post",
                                {"model": "animesr_v2"},
                            ),
                            self._action_button(
                                "提交默认任务",
                                "mdi-play",
                                "/jobs",
                                "post",
                                self._default_job_payload(),
                            ),
                        ],
                    },
                ],
            },
            {"component": "h3", "props": {"class": "mt-6 mb-2"}, "text": "最近任务"},
            {
                "component": "VDataTable",
                "props": {
                    "density": "compact",
                    "headers": [
                        {"title": "ID", "key": "id"},
                        {"title": "输入", "key": "input"},
                        {"title": "模型", "key": "model"},
                        {"title": "状态", "key": "status"},
                        {"title": "进度", "key": "progress"},
                        {"title": "FPS", "key": "fps"},
                        {"title": "错误", "key": "error"},
                    ],
                    "items": job_rows,
                    "items-per-page": 20,
                },
            },
            {
                "component": "div",
                "props": {"class": "d-flex flex-wrap ga-2 mt-3"},
                "content": job_actions,
            },
        ]

    @staticmethod
    def stop_service() -> None:
        """插件未持有独立后台服务，无需停止额外资源"""
        return None

    def api_status(self) -> JSONResponse:
        """返回超分服务和本地模型的组合状态"""
        return JSONResponse(content=self._combined_status())

    def api_jobs(self) -> JSONResponse:
        """返回超分服务任务列表"""
        return self._proxy_response("/api/jobs")

    def api_create_jobs(self, payload: Optional[dict] = Body(default=None)) -> JSONResponse:
        """使用请求参数或插件默认值创建超分任务"""
        request = self._default_job_payload()
        if payload:
            request.update(payload)
        if not str(request.get("input_path") or "").strip():
            return self._response(400, {"detail": "请先填写输入路径"})
        request["cq"] = self._bounded_int(request.get("cq"), 18, 0, 51)
        if request.get("model") not in self.MODELS:
            return self._response(400, {"detail": "不支持的模型"})
        request["recursive"] = bool(request.get("recursive", True))
        return self._proxy_response("/api/jobs", "POST", request)

    def api_cancel_job(self, payload: dict = Body(...)) -> JSONResponse:
        """取消排队中或运行中的超分任务"""
        return self._job_action(payload, "cancel")

    def api_retry_job(self, payload: dict = Body(...)) -> JSONResponse:
        """重试失败或已取消的超分任务"""
        return self._job_action(payload, "retry")

    def api_verify_models(self) -> JSONResponse:
        """清除摘要缓存并重新校验全部模型"""
        self._hash_cache.clear()
        self._download_state = {
            model_id: state
            for model_id, state in self._download_state.items()
            if state.get("state") == "downloading"
        }
        return JSONResponse(content={"models": self._model_statuses(force=True)})

    def api_download_model(self, payload: dict = Body(...)) -> JSONResponse:
        """将指定模型下载任务提交到 MoviePilot 公共线程池"""
        model_id = str((payload or {}).get("model") or "")
        if model_id not in self.MODELS:
            return self._response(400, {"detail": "不支持的模型"})
        url = self._model_url(model_id)
        if not url:
            return self._response(400, {"detail": "请先在插件配置中填写该模型的下载地址"})
        if not self._valid_download_url(url):
            return self._response(400, {"detail": "下载地址必须是 http 或 https URL"})
        if not self._download_lock.acquire(blocking=False):
            return self._response(409, {"detail": "已有模型下载任务正在运行"})
        try:
            ThreadHelper().submit(self._download_models, [model_id], True)
        except Exception:
            self._download_lock.release()
            raise
        return self._response(202, {"ok": True, "detail": "模型下载已开始"})

    def _job_action(self, payload: dict, action: str) -> JSONResponse:
        job_id = str((payload or {}).get("job_id") or "").strip()
        if not job_id or not all(char.isalnum() or char in "-_" for char in job_id):
            return self._response(400, {"detail": "无效的任务 ID"})
        return self._proxy_response(f"/api/jobs/{job_id}/{action}", "POST", {})

    def _combined_status(self) -> dict:
        service: dict = {"online": False, "error": "插件未启用"}
        if self._enabled:
            status_code, content = self._service_request("/api/status")
            if status_code == 200 and isinstance(content, dict):
                service = {"online": True, **content}
                jobs_code, jobs_content = self._service_request("/api/jobs")
                if jobs_code == 200 and isinstance(jobs_content, dict):
                    service["jobs"] = jobs_content.get("jobs", [])
            else:
                service = {
                    "online": False,
                    "error": self._error_text(content),
                    "status_code": status_code,
                }
        return {
            "enabled": self._enabled,
            "service_url": self._service_url,
            "model_dir": self._model_dir,
            "service": service,
            "models": self._model_statuses(),
        }

    def _model_statuses(self, force: bool = False) -> Dict[str, dict]:
        return {
            model_id: self._model_status(model_id, force)
            for model_id in self.MODELS
        }

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
        return {
            **model,
            "path": str(path),
            "size": path.stat().st_size,
            "sha256_actual": digest,
            "state": "valid" if valid else "invalid",
            "message": "SHA256 匹配" if valid else "SHA256 不匹配",
        }

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
            model_id
            for model_id, model in self.MODELS.items()
            if not (Path(self._model_dir) / model["filename"]).is_file()
            and self._valid_download_url(self._model_url(model_id))
        ]
        if not model_ids or not self._download_lock.acquire(blocking=False):
            return
        try:
            ThreadHelper().submit(self._download_models, model_ids, True)
        except Exception as error:
            self._download_lock.release()
            logger.error(f"动漫视频超分自动下载任务提交失败：{error}")

    def _download_models(
        self, model_ids: List[str], lock_acquired: bool = False
    ) -> None:
        if not lock_acquired:
            self._download_lock.acquire()
        try:
            for model_id in model_ids:
                self._download_model_file(model_id, self._model_url(model_id))
        finally:
            self._download_lock.release()

    def _download_model_file(self, model_id: str, url: str) -> None:
        model = self.MODELS[model_id]
        directory = Path(self._model_dir)
        target = directory / model["filename"]
        temporary = directory / f".{model['filename']}.part"
        self._download_state[model_id] = {"state": "downloading", "message": "正在下载"}
        try:
            directory.mkdir(parents=True, exist_ok=True)
            request = RequestUtils(ua="MoviePilot-AnimeUpscale/1.0", timeout=60)
            with request.get_stream(url) as response:
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
                        total += len(chunk)
                        if total > self._MAX_DOWNLOAD_BYTES:
                            raise ValueError("模型文件超过 10 GiB 限制")
                        output.write(chunk)
                        digest.update(chunk)
            if digest.hexdigest() != model["sha256"]:
                raise ValueError("下载文件 SHA256 不匹配")
            os.replace(temporary, target)
            self._hash_cache.pop(str(target), None)
            self._download_state[model_id] = {
                "state": "valid",
                "message": "下载完成且校验通过",
            }
            logger.info(f"动漫视频超分模型下载完成：{target}")
        except Exception as error:
            temporary.unlink(missing_ok=True)
            self._download_state[model_id] = {"state": "failed", "message": str(error)}
            logger.error(f"动漫视频超分模型下载失败：{model['label']} - {error}")

    def _proxy_response(self, path: str, method: str = "GET", payload: Optional[dict] = None) -> JSONResponse:
        if not self._enabled:
            return self._response(409, {"detail": "插件未启用"})
        status, content = self._service_request(path, method, payload)
        return self._response(status, content)

    def _service_request(
        self, path: str, method: str = "GET", payload: Optional[dict] = None
    ) -> Tuple[int, Any]:
        url = f"{self._service_url}{path}"
        try:
            request = RequestUtils(
                ua="MoviePilot-AnimeUpscale/1.0",
                timeout=15,
                content_type="application/json",
                accept_type="application/json",
            )
            response = (
                request.post_res(url, json=payload or {})
                if method.upper() == "POST"
                else request.get_res(url)
            )
            if response is None:
                return 502, {"detail": "无法连接 Anime Upscale 服务"}
            try:
                return response.status_code, self._decode_response(response.content)
            finally:
                response.close()
        except Exception as error:
            return 502, {"detail": f"无法连接 Anime Upscale 服务：{error}"}

    @staticmethod
    def _decode_response(content: bytes) -> Any:
        if not content:
            return {}
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"detail": content.decode("utf-8", errors="replace")[:1000]}

    @staticmethod
    def _response(status: int, content: Any) -> JSONResponse:
        if not isinstance(content, (dict, list)):
            content = {"detail": str(content)}
        return JSONResponse(status_code=status, content=content)

    @staticmethod
    def _normalize_service_url(value: Any) -> str:
        text = str(value or "").strip().rstrip("/")
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "http://anime-upscale:8787"
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

    @staticmethod
    def _valid_download_url(value: str) -> bool:
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return min(max(int(value), minimum), maximum)
        except (TypeError, ValueError):
            return default

    def _model_url(self, model_id: str) -> str:
        return self._animesr_url if model_id == "animesr_v2" else self._starsample_url

    def _default_job_payload(self) -> dict:
        return {
            "input_path": self._input_path,
            "output_subdir": self._output_subdir,
            "recursive": self._recursive,
            "cq": self._cq,
            "model": self._model,
        }

    def _current_config(self) -> dict:
        return {
            "enabled": self._enabled,
            "service_url": self._service_url,
            "model_dir": self._model_dir,
            "starsample_url": self._starsample_url,
            "animesr_url": self._animesr_url,
            "auto_download": self._auto_download,
            **self._default_job_payload(),
        }

    @staticmethod
    def _field(component: str, model: str, label: str, cols: int = 12, md: Optional[int] = None, **props) -> dict:
        column = {"cols": cols}
        if md:
            column["md"] = md
        return {
            "component": "VCol",
            "props": column,
            "content": [{"component": component, "props": {"model": model, "label": label, **props}}],
        }

    def _action_button(
        self,
        text: str,
        icon: str,
        path: str,
        method: str = "get",
        params: Optional[dict] = None,
        block: bool = True,
    ) -> dict:
        event = {"api": f"plugin/{self.__class__.__name__}{path}", "method": method}
        if params is not None:
            event["params"] = params
        return {
            "component": "VBtn",
            "props": {"class": "ma-1", "variant": "tonal", "prepend-icon": icon, "block": block},
            "text": text,
            "events": {"click": event},
        }

    @staticmethod
    def _error_text(content: Any) -> str:
        if isinstance(content, dict):
            return str(content.get("detail") or content.get("error") or content)
        return str(content)

    @staticmethod
    def _service_summary(service: dict) -> str:
        if not service.get("online"):
            return f"服务不可用：{service.get('error') or '未知错误'}"
        gpu = service.get("gpu") or "未检测到 GPU"
        cuda = "CUDA 可用" if service.get("cuda_ready") else "CUDA 不可用"
        current = service.get("current_job_id") or "空闲"
        return f"服务在线 | {gpu} | {cuda} | 当前任务：{current}"
