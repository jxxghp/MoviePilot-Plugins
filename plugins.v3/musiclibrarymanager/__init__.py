"""MoviePilot V3 音乐资源管理插件。"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from app.db.oper.user import UserOper
from app.schemas.token import TokenPayload
from app.sdk.plugin import _PluginBase
from app.sdk.security import verify_token
from fastapi import Depends, HTTPException, Query

from .paths import absolute_path, safe_component
from .schemas import (
    ArtistCatalogResponse,
    ArtistSearchResponse,
    CollectionDownloadRequest,
    CollectionSearchResponse,
    CompletionDownloadRequest,
    CompletionResponse,
    DownloadJob,
    NormalizationPlan,
    NormalizationPreviewRequest,
    PluginStatus,
    TorrentTask,
)
from .service import MusicLibraryService


async def require_manage_user(
    token: Annotated[TokenPayload, Depends(verify_token)],
) -> Any:
    """经宿主令牌校验及用户 Oper 重读权限，拒绝失效账号与非管理用户。"""
    user = await UserOper().async_get_by_id(token.sub)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或未激活")
    if not user.is_superuser and not bool((user.permissions or {}).get("manage")):
        raise HTTPException(status_code=403, detail="需要管理权限")
    return user


class MusicLibraryManager(_PluginBase):
    """艺术家合集下载、缺失作品补全和 qB 资源规范化工作台。"""

    plugin_name = "音乐资源管理"
    plugin_desc = (
        "按 MusicBrainz 官方目录下载艺术家合集、补全缺失作品及只读资源命名预览。"
    )
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/163music_A.png"
    plugin_version = "1.0.0"
    plugin_author = "buaapyj"
    author_url = "https://github.com/dogodefi"
    plugin_config_prefix = "musiclibrarymanager_"
    plugin_order = 24
    auth_level = 2

    _CANDIDATE_TTL = 2 * 60 * 60
    _MAX_JOBS = 100
    _MAX_CANDIDATES = 1000

    def init_plugin(self, config: dict | None = None) -> None:
        """初始化配置和仅驻留内存的站点候选缓存。"""
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._show_sidebar_nav = bool(config.get("show_sidebar_nav", True))
        self._source_root = str(config.get("source_root") or "").strip()
        self._classify_source = bool(config.get("classify_source", True))
        self._candidate_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._candidate_lock = threading.Lock()
        self._job_lock = threading.Lock()

    def get_state(self) -> bool:
        return bool(getattr(self, "_enabled", False))

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        return []

    @staticmethod
    def get_render_mode() -> tuple[str, str]:
        return "vue", "dist/assets"

    def get_sidebar_nav(self) -> list[dict[str, Any]]:
        if not self.get_state() or not self._show_sidebar_nav:
            return []
        return [
            {
                "nav_key": "main",
                "title": "音乐资源管理",
                "icon": "mdi-music-box-multiple",
                "section": "organize",
                "permission": "manage",
                "order": 32,
            }
        ]

    def get_form(self) -> tuple[list[dict], dict[str, Any]]:
        return [], {
            "enabled": self._enabled,
            "show_sidebar_nav": self._show_sidebar_nav,
            "source_root": self._source_root,
            "classify_source": self._classify_source,
        }

    @staticmethod
    def get_page() -> list[dict]:
        return []

    @staticmethod
    def get_service() -> list[dict[str, Any]]:
        return []

    def stop_service(self) -> None:
        """停用时立即清除私密候选，旧页面不能继续提交下载。"""
        self._enabled = False
        with self._candidate_lock:
            self._candidate_cache.clear()

    def require_enabled(self) -> None:
        if not self.get_state():
            raise HTTPException(
                status_code=409, detail="插件未启用，请先启用后重新搜索"
            )

    def get_api(self) -> list[dict[str, Any]]:
        """注册工作台 API；写操作均要求 manage 权限对应的插件认证。"""
        declarations = [
            ("/status", self.status, "GET", PluginStatus, "音乐资源管理状态"),
            (
                "/artists/search",
                self.search_artists,
                "GET",
                ArtistSearchResponse,
                "搜索 MusicBrainz 艺术家",
            ),
            (
                "/artists/{artist_id}/catalog",
                self.artist_catalog,
                "GET",
                ArtistCatalogResponse,
                "官方作品与入库状态",
            ),
            (
                "/artists/{artist_id}/collections",
                self.artist_collections,
                "GET",
                CollectionSearchResponse,
                "搜索艺术家大合集",
            ),
            (
                "/artists/{artist_id}/completion",
                self.artist_completion,
                "GET",
                CompletionResponse,
                "搜索缺失作品资源",
            ),
            (
                "/downloads/collection",
                self.download_collection,
                "POST",
                DownloadJob,
                "下载一个艺术家大合集",
            ),
            (
                "/downloads/completion",
                self.download_completion,
                "POST",
                DownloadJob,
                "批量下载缺失作品",
            ),
            ("/jobs", self.jobs, "GET", list[DownloadJob], "查询插件下载任务"),
            (
                "/normalization/tasks",
                self.normalization_tasks,
                "GET",
                list[TorrentTask],
                "查询音乐任务",
            ),
            (
                "/normalization/plan",
                self.normalization_plan,
                "POST",
                NormalizationPlan,
                "只读资源命名预览",
            ),
        ]
        return [
            {
                "path": path,
                "endpoint": endpoint,
                "methods": [method],
                "auth": "bear",
                "response_model": model,
                "summary": summary,
                "dependencies": [Depends(require_manage_user)]
                + ([] if path == "/status" else [Depends(self.require_enabled)]),
            }
            for path, endpoint, method, model, summary in declarations
        ]

    def status(self) -> PluginStatus:
        return PluginStatus(
            enabled=self.get_state(),
            capabilities={
                "artist_collection": True,
                "completion": True,
                "normalization_preview": True,
                "torrent_move": False,
                "torrent_content_rename": False,
            },
            jobs=self._jobs()[:20],
        )

    async def search_artists(
        self,
        query: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> ArtistSearchResponse:
        return ArtistSearchResponse(
            items=await MusicLibraryService(self).search_artists(query, limit)
        )

    async def artist_catalog(self, artist_id: str) -> ArtistCatalogResponse:
        artist, works, complete = await MusicLibraryService(self).catalog(artist_id)
        return ArtistCatalogResponse(
            artist=artist, works=works, library_status_complete=complete
        )

    async def artist_collections(
        self,
        artist_id: str,
        artist_name: str | None = None,
        sites: str | None = None,
        limit: int = Query(default=8, ge=1, le=12),
    ) -> CollectionSearchResponse:
        items, terms = await MusicLibraryService(self).collections(
            artist_id=artist_id,
            artist_name=artist_name,
            sites=self._site_ids(sites),
            limit=limit,
        )
        return CollectionSearchResponse(items=items, searched_terms=terms)

    async def artist_completion(
        self,
        artist_id: str,
        sites: str | None = None,
    ) -> CompletionResponse:
        return CompletionResponse(
            **await MusicLibraryService(self).completion(
                artist_id, self._site_ids(sites)
            )
        )

    def download_collection(
        self,
        request: CollectionDownloadRequest,
    ) -> DownloadJob:
        return DownloadJob.model_validate(
            MusicLibraryService(self).download_collection(
                artist_id=request.artist_id,
                artist_name=request.artist_name,
                candidate_key=request.candidate_key,
                downloader=request.downloader,
                save_path=request.save_path,
            )
        )

    def download_completion(
        self,
        request: CompletionDownloadRequest,
    ) -> DownloadJob:
        return DownloadJob.model_validate(
            MusicLibraryService(self).download_completion(
                artist_id=request.artist_id,
                artist_name=request.artist_name,
                items=request.items,
                downloader=request.downloader,
                save_path=request.save_path,
            )
        )

    def jobs(self) -> list[DownloadJob]:
        return [DownloadJob.model_validate(item) for item in self._jobs()]

    def normalization_tasks(self) -> list[TorrentTask]:
        return [
            TorrentTask.model_validate(item)
            for item in MusicLibraryService(self).torrent_tasks()
        ]

    def normalization_plan(
        self,
        request: NormalizationPreviewRequest,
    ) -> NormalizationPlan:
        return NormalizationPlan.model_validate(
            MusicLibraryService(self).normalization_plan(request)
        )

    def cache_candidate(
        self,
        key: str,
        context: Any,
        *,
        artist: dict,
        kind: str,
        media: dict | None = None,
    ) -> None:
        """保存带站点凭据的上下文；仅驻留内存且定期淘汰。"""
        now = time.monotonic()
        with self._candidate_lock:
            if not self.get_state():
                return
            self._candidate_cache = {
                item_key: item
                for item_key, item in self._candidate_cache.items()
                if now - item[0] < self._CANDIDATE_TTL
            }
            while len(self._candidate_cache) >= self._MAX_CANDIDATES:
                self._candidate_cache.pop(next(iter(self._candidate_cache)))
            self._candidate_cache[key] = (
                now,
                {
                    "context": context,
                    "artist": dict(artist),
                    "kind": kind,
                    "media": dict(media) if media else None,
                },
            )

    def take_candidate(
        self, key: str, *, artist_id: str, kind: str, media_id: str | None = None
    ) -> dict:
        """候选一次性消费；模式/身份由服务端搜索快照决定，不能由浏览器替换。"""
        now = time.monotonic()
        with self._candidate_lock:
            item = self._candidate_cache.get(key)
            if not item or now - item[0] >= self._CANDIDATE_TTL:
                self._candidate_cache.pop(key, None)
                raise HTTPException(
                    status_code=409, detail="候选已使用或过期，请重新搜索"
                )
            candidate = item[1]
            if (
                candidate["artist"]["media_id"] != artist_id
                or candidate["kind"] != kind
                or (
                    media_id is not None
                    and (candidate["media"] or {}).get("media_id") != media_id
                )
            ):
                raise HTTPException(
                    status_code=422, detail="候选与艺术家、模式或作品不一致"
                )
            self._candidate_cache.pop(key)
            return candidate

    def collection_save_path(
        self, artist_name: str, explicit: str | None
    ) -> str | None:
        if explicit:
            return absolute_path(explicit).as_posix()
        if not self._source_root:
            return None
        root = absolute_path(self._source_root)
        if self._classify_source:
            return (root / "Artist Collection" / safe_component(artist_name)).as_posix()
        return root.as_posix()

    def save_job(
        self, kind: str, artist_id: str, artist_name: str, results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        submitted = sum(item.get("state") == "submitted" for item in results)
        failed = len(results) - submitted
        state = (
            "failed" if failed == len(results) else "partial" if failed else "submitted"
        )
        job = {
            "job_id": uuid4().hex,
            "kind": kind,
            "state": state,
            "artist_id": artist_id,
            "artist_name": artist_name,
            "total": len(results),
            "submitted": submitted,
            "failed": failed,
            "results": results,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with self._job_lock:
            jobs = self._jobs()
            jobs.insert(0, job)
            self.save_data("jobs_v1", jobs[: self._MAX_JOBS])
        return job

    def _jobs(self) -> list[dict[str, Any]]:
        value = self.get_data("jobs_v1") or []
        return value if isinstance(value, list) else []

    @staticmethod
    def _site_ids(value: str | None) -> list[int] | None:
        if not value:
            return None
        result = []
        for raw in value.split(","):
            try:
                result.append(int(raw.strip()))
            except ValueError:
                continue
        return result or None
