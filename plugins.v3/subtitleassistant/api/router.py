"""字幕助手 Bearer API 控制器。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import Body, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.db.models.user import User
from app.db.user_oper import (
    get_current_active_manage_user_async,
    get_current_active_superuser_async,
)
from app.schemas import Response

from ..record import RecordCatalog, RecordMaintenance
from ..schemas.http.page import PageSize
from ..schemas.http.record import (
    BatchRecordDeletePreflightItem,
    BatchRecordDeleteRequest,
    BatchRecordDeleteResponse,
    BatchRecordDeleteResultItem,
    BatchRetargetPreviewItem,
    BatchRetargetPreviewRequest,
    BatchRetargetPreviewResponse,
    BatchRetargetResponse,
    BatchRetargetResultItem,
    BatchRetargetSubmitRequest,
    RecordDeleteRequest,
    RecordDetail,
    RecordListItem,
    RecordPage,
    RetargetPreviewResponse,
    RetargetRequest,
)
from ..schemas.http.search import (
    ManualDownloadRequest,
    ManualDownloadResponse,
    ManualSearchRequest,
    ManualSearchResponse,
)
from ..schemas.http.source import CredentialUpdate, SourceStatusItem
from ..schemas.http.target import TargetPage
from ..schemas.http.task import TaskDetail, TaskListItem, TaskPage
from ..schemas.record import (
    BatchDeleteRecordConfirmation,
    DeleteMode,
    DeleteRecordConfirmation,
    FileLocation,
    MatchRecord,
    RecordStatus,
    RetargetMapping,
)
from ..schemas.source import SubtitleSource
from ..schemas.task import SubtitleTask, TaskStatus
from ..search import ManualSearch
from ..source import SourceAdministration
from ..target import TargetCatalog
from ..task import TaskOperations
from .projection import source_item, target_item

CredentialSource = Literal["opensubtitles", "assrt"]


class _RecordPathResolver(Protocol):
    """HTTP 投影记录路径所需的最小文件能力。"""

    async def plugin_file_path(self, relative_path: str) -> Path:
        """解析插件数据目录中的字幕相对路径。"""


class ApiController:
    """把应用服务结果转换为固定插件 API 契约。"""

    def __init__(
        self,
        *,
        tasks: TaskOperations,
        records: RecordCatalog,
        maintenance: RecordMaintenance,
        filesystem: _RecordPathResolver,
        targets: TargetCatalog,
        search: ManualSearch,
        sources: SourceAdministration,
        update_credentials: Callable[[SubtitleSource, dict[str, str]], Awaitable[bool]],
        clear_credentials: Callable[[SubtitleSource], Awaitable[bool]],
    ) -> None:
        """创建仅依赖能力 facade 与文件路径 adapter 的 HTTP 控制器。"""

        self._tasks = tasks
        self._records = records
        self._maintenance = maintenance
        self._filesystem = filesystem
        self._targets = targets
        self._search = search
        self._sources = sources
        self._update_credentials = update_credentials
        self._clear_credentials = clear_credentials

    async def _current_record_file_path(self, record: MatchRecord) -> str:
        """返回记录当前字幕文件的完整服务端路径。"""

        if record.location is FileLocation.MEDIA_DIRECTORY:
            return str(record.path)
        try:
            return str(await self._filesystem.plugin_file_path(str(record.path)))
        except (OSError, ValueError):
            # 历史损坏记录仍应能列出并由后端安全拒绝文件操作；此时保留原值
            # 供用户定位数据问题，不尝试自行拼接未经校验的路径。
            return str(record.path)

    async def _record_list_item(self, record: MatchRecord) -> RecordListItem:
        """把记录转换为包含完整当前文件路径的列表模型。"""

        item = RecordListItem.model_validate(record.model_dump(mode="json", include=set(RecordListItem.model_fields)))
        return item.model_copy(update={"current_file_path": await self._current_record_file_path(record)})

    async def _record_detail(self, record: MatchRecord) -> RecordDetail:
        """把记录转换为包含完整当前文件路径的详情模型。"""

        detail = RecordDetail.model_validate(record.model_dump(mode="json", include=set(RecordDetail.model_fields)))
        return detail.model_copy(update={"current_file_path": await self._current_record_file_path(record)})

    @staticmethod
    def _timestamp(value: datetime | None) -> float:
        """返回可排序的 UTC 时间戳。"""

        return (value or datetime.min.replace(tzinfo=UTC)).timestamp()

    @staticmethod
    def _task_search_text(task: SubtitleTask) -> str:
        """拼接任务固定全文搜索字段。"""

        season_episode = ""
        if task.season is not None:
            season_episode += f"S{task.season:02d}"
        if task.episode is not None:
            season_episode += f"E{task.episode:02d}"
        return " ".join(
            str(value or "")
            for value in (
                task.media_title,
                task.year,
                season_episode,
                task.target_file_name,
                task.target_path,
                task.reason_code,
                task.reason_message,
            )
        ).casefold()

    @classmethod
    def _task_sort_key(cls, task: SubtitleTask) -> tuple[int, float]:
        """返回处理中、等待中、终态三组固定排序键。"""

        if task.status is TaskStatus.PROCESSING:
            return 0, cls._timestamp(task.started_at or task.created_at)
        if task.status is TaskStatus.QUEUED:
            return 1, cls._timestamp(task.created_at)
        return 2, -cls._timestamp(task.finished_at or task.created_at)

    @staticmethod
    def _record_search_text(
        record: MatchRecord,
        current_file_path: str | None = None,
    ) -> str:
        """拼接匹配记录固定全文搜索字段。"""

        season_episode = ""
        if record.season is not None:
            season_episode += f"S{record.season:02d}"
        if record.episode is not None:
            season_episode += f"E{record.episode:02d}"
        return " ".join(
            str(value or "")
            for value in (
                record.subtitle_file_name,
                record.media_title,
                record.year,
                season_episode,
                record.source.value,
                record.path,
                current_file_path,
            )
        ).casefold()

    async def list_tasks(
        self,
        page: int = Query(default=1, ge=1),
        page_size: PageSize = Query(default=PageSize.ITEMS_25),  # noqa: B008 - FastAPI 查询参数注入
        search: str | None = Query(default=None),
        status: TaskStatus | None = Query(default=None),  # noqa: B008 - FastAPI 查询参数注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TaskPage:
        """分页查询字幕任务安全摘要。"""

        tasks = await self._tasks.list_tasks()
        if status is not None:
            tasks = [task for task in tasks if task.status is status]
        query = (search or "").strip().casefold()
        if query:
            tasks = [task for task in tasks if query in self._task_search_text(task)]
        tasks.sort(key=self._task_sort_key)
        total = len(tasks)
        start = (page - 1) * page_size
        items = [
            TaskListItem.model_validate(task.model_dump(mode="json", include=set(TaskListItem.model_fields)))
            for task in tasks[start : start + page_size]
        ]
        return TaskPage(items=items, total=total, page=page, page_size=page_size)

    async def get_task(
        self,
        task_id: str,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TaskDetail:
        """查询单个字幕任务详情。"""

        task = await self._tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        payload = task.model_dump(mode="json", include=set(TaskDetail.model_fields))
        return TaskDetail.model_validate(payload)

    async def delete_task(
        self,
        task_id: str,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """删除一个终态任务历史。"""

        task = await self._tasks.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if not task.is_terminal:
            raise HTTPException(status_code=409, detail="运行中的任务不能删除")
        await self._tasks.delete_task(task_id)
        return Response(success=True, message="任务记录已删除")

    async def list_records(
        self,
        page: int = Query(default=1, ge=1),
        page_size: PageSize = Query(default=PageSize.ITEMS_25),  # noqa: B008 - FastAPI 查询参数注入
        search: str | None = Query(default=None),
        status: RecordStatus | None = Query(default=None),  # noqa: B008 - FastAPI 查询参数注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RecordPage:
        """分页查询字幕匹配记录。"""

        records = await self._records.list_records()
        if status is not None:
            records = [record for record in records if record.status is status]
        query = (search or "").strip().casefold()
        if query:
            matched_records: list[MatchRecord] = []
            for record in records:
                current_file_path = await self._current_record_file_path(record)
                if query in self._record_search_text(record, current_file_path):
                    matched_records.append(record)
            records = matched_records
        records.sort(key=lambda record: record.updated_at, reverse=True)
        total = len(records)
        start = (page - 1) * page_size
        items = [await self._record_list_item(record) for record in records[start : start + page_size]]
        return RecordPage(items=items, total=total, page=page, page_size=page_size)

    async def get_record(
        self,
        record_id: str,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RecordDetail:
        """查询单个字幕匹配记录详情。"""

        record = await self._records.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="匹配记录不存在")
        return await self._record_detail(record)

    async def delete_record(
        self,
        record_id: str,
        payload: RecordDeleteRequest = Body(...),  # noqa: B008 - FastAPI 请求体注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """按用户确认版本删除匹配记录及可选字幕文件。"""

        if not isinstance(payload, RecordDeleteRequest):
            try:
                payload = RecordDeleteRequest.model_validate(payload)
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail=exc.errors()) from exc
        try:
            result = await self._records.delete(
                record_id,
                DeleteRecordConfirmation(
                    delete_mode=DeleteMode(payload.delete_mode),
                    expected_status=payload.expected_status,
                    expected_location=payload.expected_location,
                    expected_path=Path(payload.expected_path),
                    expected_updated_at=payload.expected_updated_at,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="匹配记录删除失败") from exc

        if result.error_code == "record_not_found":
            raise HTTPException(status_code=404, detail=result.message or "匹配记录不存在")
        if result.error_code in {"record_version_conflict", "delete_mode_not_allowed"}:
            raise HTTPException(
                status_code=409,
                detail={"code": result.error_code, "message": result.message or "当前记录不能删除"},
            )
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": result.error_code or "record_delete_failed",
                    "message": result.message or "匹配记录删除失败",
                    "consistency_risk": result.consistency_risk,
                },
            )
        message = (
            "匹配记录已删除，字幕文件已保留" if payload.delete_mode == "record_only" else "匹配记录及当前字幕文件已删除"
        )
        return Response(success=True, message=message)

    async def delete_records_batch(
        self,
        payload: BatchRecordDeleteRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> BatchRecordDeleteResponse:
        """整批预检后按请求顺序删除多条匹配记录。"""

        try:
            result = await self._records.delete_batch(
                [
                    BatchDeleteRecordConfirmation(
                        record_id=item.record_id,
                        confirmation=DeleteRecordConfirmation(
                            delete_mode=DeleteMode(payload.delete_mode),
                            expected_status=item.expected_status,
                            expected_location=item.expected_location,
                            expected_path=Path(item.expected_path),
                            expected_updated_at=item.expected_updated_at,
                        ),
                    )
                    for item in payload.items
                ],
                DeleteMode(payload.delete_mode),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="批量删除匹配记录失败") from exc

        if not result.started:
            preflight_items = [
                BatchRecordDeletePreflightItem(
                    record_id=item.record_id,
                    executable=item.executable,
                    error_code=item.error_code,
                    message=item.message,
                )
                for item in result.preflight.items
            ]
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "batch_preflight_failed",
                    "message": "批量删除预检未通过",
                    "items": [item.model_dump(mode="json") for item in preflight_items],
                },
            )
        return BatchRecordDeleteResponse(
            success_count=result.success_count,
            failure_count=result.failure_count,
            not_executed_count=result.not_executed_count,
            items=[
                BatchRecordDeleteResultItem(
                    record_id=item.record_id,
                    status=item.status.value,
                    error_code=item.error_code,
                    message=item.message,
                    consistency_risk=item.consistency_risk,
                )
                for item in result.items
            ],
        )

    @staticmethod
    def _raw_history_item(history: object) -> dict[str, Any]:
        """把宿主整理历史行编码为不丢字段的 JSON 对象。"""

        if isinstance(history, Mapping):
            values = dict(history)
        else:
            try:
                values = {key: value for key, value in vars(history).items() if not key.startswith("_")}
            except TypeError:
                values = {}
        encoded = jsonable_encoder(values)
        return encoded if isinstance(encoded, dict) else {}

    async def list_targets(
        self,
        page: int = Query(default=1, ge=1),
        page_size: PageSize = Query(default=PageSize.ITEMS_25),  # noqa: B008 - FastAPI 查询参数注入
        search: str | None = Query(default=None, max_length=512),
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TargetPage:
        """按 MoviePilot 历史搜索语义返回人工搜索和改配选择目标。"""

        result = await self._targets.list_targets(page=page, page_size=int(page_size), search=search)
        return TargetPage(
            items=[self._raw_history_item(item) for item in result.items],
            page=result.page,
            page_size=page_size,
            total=result.total,
        )

    async def search_subtitles(
        self,
        payload: ManualSearchRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> ManualSearchResponse:
        """并发执行三源人工字幕搜索。"""

        try:
            result = await self._search.search(
                int(payload.target_history_id),
                {
                    SubtitleSource.MOVIEPILOT: payload.moviepilot_keyword,
                    SubtitleSource.OPENSUBTITLES: payload.opensubtitles_keyword,
                    SubtitleSource.ASSRT: payload.assrt_keyword,
                },
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ManualSearchResponse(
            session_id=result.session_id,
            target=target_item(result.target, self._sources),
            sources=[source_item(run) for run in result.sources],
        )

    async def download_search_candidate(
        self,
        session_id: str,
        payload: ManualDownloadRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> ManualDownloadResponse:
        """把人工选定候选交给人工搜索应用服务并映射稳定结果。"""

        try:
            result = await self._search.submit(session_id, payload.candidate_key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="人工字幕任务提交失败") from exc
        if result.status == "session_not_found":
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "manual_search_session_expired",
                    "message": "搜索会话已失效，请重新搜索",
                },
            )
        if result.status == "candidate_not_found":
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "manual_search_candidate_unavailable",
                    "message": "当前候选不可用，请选择其他候选",
                },
            )
        if result.status == "rejected":
            raise HTTPException(status_code=409, detail="插件当前不接受新任务")
        if result.status != "success" or result.task is None:
            raise HTTPException(status_code=500, detail="人工字幕任务创建失败")
        return ManualDownloadResponse(
            task_id=result.task.id,
            task=TaskListItem.model_validate(
                result.task.model_dump(mode="json", include=set(TaskListItem.model_fields))
            ),
        )

    async def preview_retarget_record(
        self,
        record_id: str,
        payload: RetargetRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RetargetPreviewResponse:
        """按当前路径映射预览改配结果。"""

        result = await self._maintenance.preview(record_id, int(payload.target_history_id))
        if result.success and result.preview is not None:
            return self._retarget_preview_response(result.preview)
        status = 404 if result.error_code in {"record_not_found", "target_not_found"} else 409
        raise HTTPException(
            status_code=status,
            detail={
                "code": result.error_code or "retarget_preview_failed",
                "message": result.message or "改配预览失败",
            },
        )

    async def retarget_record(
        self,
        record_id: str,
        payload: RetargetRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RecordDetail:
        """把现有匹配记录改配到新的整理目标。"""

        result = await self._maintenance.retarget(record_id, int(payload.target_history_id))
        if result.success and result.record is not None:
            return await self._record_detail(result.record)
        status = 404 if result.error_code in {"record_not_found", "target_not_found"} else 409
        if result.error_code == "file_operation_failed":
            status = 500
        error_code = result.error_code or "retarget_failed"
        message = result.message or "改配目标失败"
        if result.consistency_risk:
            status = 500
            error_code = "retarget_consistency_risk"
            message = "改配失败且回滚未完整完成，文件与记录可能不一致，请检查后重试"
        raise HTTPException(
            status_code=status,
            detail={
                "code": error_code,
                "message": message,
                "consistency_risk": result.consistency_risk,
            },
        )

    def _batch_preview_response(self, result: Any) -> BatchRetargetPreviewResponse:
        """把领域批量预检结果转换为前端安全响应。"""

        return BatchRetargetPreviewResponse(
            executable=result.executable,
            items=[
                BatchRetargetPreviewItem(
                    record_id=item.record_id,
                    current_subtitle_path=(
                        str(item.current_subtitle_path) if item.current_subtitle_path is not None else None
                    ),
                    target_history_id=item.target_history_id,
                    target=target_item(item.target, self._sources) if item.target is not None else None,
                    preview=self._retarget_preview_response(item.preview) if item.preview is not None else None,
                    executable=item.executable,
                    error_code=item.error_code,
                    message=item.message,
                )
                for item in result.items
            ],
        )

    @staticmethod
    def _retarget_preview_response(preview: Any) -> RetargetPreviewResponse:
        """将领域路径明确投影为既有 HTTP 字符串字段。"""

        return RetargetPreviewResponse(
            target_history_id=preview.target_history_id,
            history_target_path=str(preview.history_target_path),
            target_path=str(preview.target_path),
            final_subtitle_path=str(preview.final_subtitle_path),
            directory_available=preview.directory_available,
            directory_error=preview.directory_error,
        )

    async def preview_batch_retarget_records(
        self,
        payload: BatchRetargetPreviewRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> BatchRetargetPreviewResponse:
        """自动建议目标并预检一批匹配记录改配。"""

        result = await self._maintenance.preview_batch(
            [
                RetargetMapping(
                    record_id=item.record_id,
                    target_history_id=item.target_history_id,
                )
                for item in payload.items
            ]
        )
        return self._batch_preview_response(result)

    async def retarget_batch_records(
        self,
        payload: BatchRetargetSubmitRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> BatchRetargetResponse:
        """整体预检后逐条独立执行一批匹配记录改配。"""

        result = await self._maintenance.retarget_batch(
            [
                RetargetMapping(
                    record_id=item.record_id,
                    target_history_id=item.target_history_id,
                )
                for item in payload.items
            ]
        )
        if not result.started:
            preview = self._batch_preview_response(result.preflight)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "batch_preflight_failed",
                    "message": "批量改配预检未通过",
                    **preview.model_dump(mode="json"),
                },
            )
        response_items: list[BatchRetargetResultItem] = []
        for item in result.items:
            consistency_risk = item.result.consistency_risk
            response_items.append(
                BatchRetargetResultItem(
                    record_id=item.record_id,
                    target_history_id=item.target_history_id,
                    success=item.result.success,
                    error_code=("retarget_consistency_risk" if consistency_risk else item.result.error_code),
                    message=(
                        "改配失败且回滚未完整完成，文件与记录可能不一致，请检查后重试"
                        if consistency_risk
                        else item.result.message
                    ),
                    consistency_risk=consistency_risk,
                    record=(await self._record_detail(item.result.record) if item.result.record is not None else None),
                )
            )
        return BatchRetargetResponse(
            success_count=result.success_count,
            failure_count=result.failure_count,
            items=response_items,
        )

    async def source_statuses(
        self,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> list[SourceStatusItem]:
        """读取三个字幕源的最近状态，不主动发起请求。"""

        statuses = {item.source: item for item in await self._sources.statuses()}
        return [
            SourceStatusItem.model_validate(
                statuses[source].model_dump(mode="json", include=set(SourceStatusItem.model_fields))
            )
            for source in SubtitleSource
            if source in statuses
        ]

    async def refresh_sources(
        self,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """并发刷新三个字幕源状态。"""

        try:
            await self._tasks.refresh_sources(manual=True)
        except asyncio.CancelledError:
            return Response(success=False, message="字幕源状态刷新已中断")
        except Exception:  # noqa: BLE001 - 来源刷新必须收敛运行时失败
            return Response(success=False, message="字幕源状态刷新失败")
        return Response(success=True, message="字幕源状态已刷新")

    async def update_credentials(
        self,
        source: CredentialSource,
        payload: CredentialUpdate,
        _: User = Depends(get_current_active_superuser_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """增量写入外部字幕源长期凭据且不回显秘密。"""

        values = payload.cleaned()
        try:
            configured = await self._update_credentials(SubtitleSource(source), values)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(success=True, message="凭据已更新", data={"configured": configured})

    async def clear_credentials(
        self,
        source: CredentialSource,
        _: User = Depends(get_current_active_superuser_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """删除外部字幕源凭据并立即关闭对应来源。"""

        success = await self._clear_credentials(SubtitleSource(source))
        if not success:
            return Response(success=False, message="凭据已删除，但来源开关保存失败")
        return Response(success=True, message="字幕源凭据已清除", data={"configured": False})

    def routes(self) -> list[dict[str, Any]]:
        """每次返回全新的 18 条 Bearer 路由定义。"""

        definitions = [
            ("/tasks", self.list_tasks, ["GET"], TaskPage, "查询字幕任务"),
            ("/tasks/{task_id}", self.get_task, ["GET"], TaskDetail, "查询字幕任务详情"),
            ("/tasks/{task_id}", self.delete_task, ["DELETE"], Response, "删除字幕任务记录"),
            ("/records", self.list_records, ["GET"], RecordPage, "查询字幕匹配记录"),
            (
                "/records/batch-delete",
                self.delete_records_batch,
                ["POST"],
                BatchRecordDeleteResponse,
                "批量删除字幕匹配记录",
            ),
            ("/records/{record_id}", self.get_record, ["GET"], RecordDetail, "查询字幕匹配记录详情"),
            ("/records/{record_id}", self.delete_record, ["DELETE"], Response, "删除字幕匹配记录"),
            ("/targets", self.list_targets, ["GET"], TargetPage, "查询可选整理目标"),
            ("/searches", self.search_subtitles, ["POST"], ManualSearchResponse, "人工搜索字幕"),
            (
                "/searches/{session_id}/downloads",
                self.download_search_candidate,
                ["POST"],
                ManualDownloadResponse,
                "提交人工字幕下载",
            ),
            (
                "/records/batch-retarget-preview",
                self.preview_batch_retarget_records,
                ["POST"],
                BatchRetargetPreviewResponse,
                "预览批量字幕改配目标",
            ),
            (
                "/records/batch-retarget",
                self.retarget_batch_records,
                ["POST"],
                BatchRetargetResponse,
                "批量改配字幕目标",
            ),
            (
                "/records/{record_id}/retarget-preview",
                self.preview_retarget_record,
                ["POST"],
                RetargetPreviewResponse,
                "预览字幕改配目标",
            ),
            ("/records/{record_id}/retarget", self.retarget_record, ["POST"], RecordDetail, "改配字幕目标"),
            ("/sources/status", self.source_statuses, ["GET"], list[SourceStatusItem], "查询字幕源状态"),
            ("/sources/refresh", self.refresh_sources, ["POST"], Response, "刷新字幕源状态"),
            ("/credentials/{source}", self.update_credentials, ["PUT"], Response, "更新字幕源凭据"),
            ("/credentials/{source}", self.clear_credentials, ["DELETE"], Response, "清除字幕源凭据"),
        ]
        return [
            {
                "path": path,
                "endpoint": endpoint,
                "methods": methods,
                "auth": "bear",
                "response_model": response_model,
                "summary": summary,
            }
            for path, endpoint, methods, response_model, summary in definitions
        ]
