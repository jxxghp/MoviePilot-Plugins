"""字幕助手串行任务编排服务。"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from anyio import Path as AsyncPath

from app import log as app_log

from ..attribution import CandidateRecognizer, FileAttributor
from ..candidate import admit_automatic_candidates, candidate_rank, describe_rejections
from ..record import RecordCommitter
from ..schemas.base import elapsed_ms, utc_now
from ..schemas.candidate import SubtitleCandidate
from ..schemas.config import PluginConfig
from ..schemas.event import SubtitleWrittenEvent, SubtitleWrittenOperation
from ..schemas.file import ExtractedSubtitle
from ..schemas.record import CommittedFileFact, InventoryConsumeResult, MatchRecord, RecordStatus
from ..schemas.source import (
    CandidateHandle,
    DownloadedAsset,
    SourceHealth,
    SourceSearchResult,
    SourceSearchStatus,
    SourceStatus,
    SubtitleSource,
)
from ..schemas.target import MediaType, PathMappingResolution, PathMappingSnapshot, SubtitleTarget
from ..schemas.task import (
    AttemptResult,
    CandidateAttemptReasonCode,
    SubtitleTask,
    TaskStatus,
    TaskTrigger,
    TaskWorkItem,
)
from ..source import (
    SOURCE_NAMES,
    SOURCE_SKIP_REASONS,
    CandidatePool,
    SourceAdministration,
    describe_source_run,
    source_run_is_warning,
)
from .attempt import (
    CandidateAttemptRequest,
    CandidateAttemptResult,
    CandidateAttemptService,
    CandidateAttemptSourcePort,
    FailureResultRetention,
)


class _TaskStorePort(Protocol):
    """字幕任务生命周期所需的持久化操作。"""

    async def list_tasks(self) -> list[SubtitleTask]:
        """读取全部字幕任务快照。"""

    async def save_task(self, task: SubtitleTask) -> None:
        """保存字幕任务快照。"""

    async def get_task(self, task_id: str) -> SubtitleTask | None:
        """按标识读取字幕任务快照。"""

    async def delete_task(self, task_id: str) -> bool:
        """删除字幕任务快照。"""

    async def list_source_statuses(self) -> list[SourceStatus]:
        """读取来源状态快照。"""

    async def save_source_status(self, status: SourceStatus) -> None:
        """保存来源状态快照。"""

    def mark_nonterminal_interrupted_sync(self, message: str) -> list[str]:
        """同步标记未完成任务为已中断。"""

    async def reset(self) -> None:
        """清理插件持久化分区。"""


class _TaskFilePort(Protocol):
    """字幕任务生命周期所需的文件操作。"""

    async def has_standard_subtitle(self, target: Path) -> Path | None:
        """查找目标关联的标准简中外挂字幕。"""

    async def make_task_directory(self, task_id: str) -> Path:
        """创建字幕任务临时目录。"""

    async def cleanup_task_directory(self, task_id: str) -> None:
        """清理字幕任务临时目录。"""

    async def clear_data_directory(self) -> None:
        """清理插件数据目录。"""

    async def target_directory_status(self, target: Path) -> tuple[bool, str | None]:
        """检查字幕目标目录是否可写。"""


class _TaskArchivePort(Protocol):
    """字幕任务候选尝试所需的归档操作。"""

    async def extract(
        self,
        asset: DownloadedAsset,
        output: Path,
        allowed_formats: set[str],
    ) -> list[ExtractedSubtitle]:
        """解包候选下载结果。"""

    async def cancel(self) -> None:
        """终止当前归档解包。"""


class _TaskSourcePort(Protocol):
    """任务停止时所需的来源资源释放操作。"""

    async def close(self) -> None:
        """关闭来源运行态资源。"""


class _TaskTargetPort(Protocol):
    """任务执行所需的字幕目标路径解析能力。"""

    def resolve_actual_subtitle_path(self, target: SubtitleTarget) -> PathMappingResolution:
        """解析整理历史目标的实际字幕路径。"""


class SubtitleEventPublisher(Protocol):
    """任务拥有者发布字幕落盘事件所需的最小端口。"""

    async def publish(self, event: SubtitleWrittenEvent) -> None:
        """尽力广播一条已提交的媒体目录字幕事实。"""


class _NoopSubtitleEvents:
    """未接入宿主事件时忽略通知。"""

    async def publish(self, event: SubtitleWrittenEvent) -> None:
        """忽略字幕落盘通知。"""


class _UnavailableCandidatePool:
    """未由组合根注入候选池时的安全占位。"""

    async def query(self, *args: Any, **kwargs: Any) -> Any:
        """拒绝在未完成装配的运行态执行来源查询。"""

        raise RuntimeError("来源候选池未注入")


TRIGGER_NAMES = {
    TaskTrigger.TRANSFER_EVENT: "媒体整理事件",
    TaskTrigger.MANUAL_CANDIDATE: "人工选择字幕",
}

ATTEMPT_RESULT_NAMES = {
    AttemptResult.SUCCESS: "处理成功",
    AttemptResult.DOWNLOAD_FAILED: "下载失败",
    AttemptResult.EXTRACT_FAILED: "解包失败",
    AttemptResult.NO_MATCH: "没有匹配到当前目标字幕",
    AttemptResult.WRITE_FAILED: "落盘失败",
    AttemptResult.INTERRUPTED: "处理已中断",
}


class TaskOperations:
    """统一管理字幕任务的队列、worker、候选尝试与持久化快照。"""

    def __init__(
        self,
        store: _TaskStorePort,
        filesystem: _TaskFilePort,
        archive: _TaskArchivePort,
        matcher: CandidateRecognizer,
        sources: SourceAdministration | Mapping[SubtitleSource, _TaskSourcePort],
        config: PluginConfig,
        inventory: RecordCommitter,
        media_extensions: Sequence[str],
        attributor: FileAttributor | None = None,
        candidate_pool: CandidatePool | None = None,
        target_catalog: _TaskTargetPort | None = None,
        manage_resources: bool = True,
        publisher: SubtitleEventPublisher | None = None,
    ) -> None:
        """创建可注入依赖的字幕任务操作 facade。"""

        self._store = store
        self._filesystem = filesystem
        self._archive = archive
        self._matcher = matcher
        if attributor is not None:
            self._attribution = attributor
        elif callable(getattr(matcher, "attribute_requests", None)):
            self._attribution = cast(FileAttributor, matcher)
        else:
            raise TypeError("任务协调器必须注入文件归属 facade")
        self._sources = sources
        self._target_catalog = target_catalog
        self._config = config
        self._inventory = inventory
        self._media_extensions = frozenset(f".{value.lower().lstrip('.')}" for value in media_extensions)
        self._candidate_pool = candidate_pool or _UnavailableCandidatePool()
        self._manage_resources = manage_resources
        self._publisher = publisher or _NoopSubtitleEvents()
        self._candidate_attempt = CandidateAttemptService(
            filesystem=self._filesystem,
            archive=self._archive,
            matcher=self._matcher,
            sources=cast(CandidatePool, self._candidate_pool),
            config=self._config,
            inventory=self._inventory,
            # 生产归属实现通过统一批量 facade 注入；仅提供旧式
            # attribute_file 的测试/宿主替身由候选模块在组合边界适配。
            attributor=self._attribution,
            source_adapters=cast(Mapping[SubtitleSource, CandidateAttemptSourcePort] | None, self._sources),
            candidate_label=self._candidate_label,
        )
        self._strategy = config.package_attribution_strategy
        self._attempt_seq = 0
        self._queue: asyncio.Queue[TaskWorkItem] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._active_paths: dict[str, str] = {}
        self._source_conclusions: list[str] = []
        self._lock = asyncio.Lock()
        self._accepting = True
        self._cleanup_started = False

    def _path_key(self, path: str | Path) -> str:
        """生成同一路径任务合并键。"""

        return os.path.normcase(os.path.abspath(path))

    @staticmethod
    def _is_history_target(item: TaskWorkItem) -> bool:
        """判断工作项是否来自整理历史目标。"""

        if item.history_target is not None:
            return item.history_target
        return item.target_history_id is not None

    @staticmethod
    def _mapping_snapshot(resolution: PathMappingResolution) -> PathMappingSnapshot | None:
        """把本次解析命中的不可变规则转换为持久化快照。"""

        if resolution.mapping is None:
            return None
        return PathMappingSnapshot(
            source_prefix=Path(resolution.mapping.source_prefix),
            target_prefix=Path(resolution.mapping.target_prefix),
        )

    @staticmethod
    def _task_label(task: SubtitleTask) -> str:
        """返回适合人读日志的任务关联说明。"""

        return f"任务 {task.id}（{TRIGGER_NAMES[task.trigger]}）"

    @staticmethod
    def _candidate_label(candidate: SubtitleCandidate) -> str:
        """返回不暴露下载定位的候选说明。"""

        return f"{SOURCE_NAMES[candidate.source]} 候选“{candidate.name}”"

    def _ensure_worker(self) -> None:
        """在当前事件循环中懒启动唯一 worker。"""

        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop())

    async def enqueue(self, item: TaskWorkItem) -> SubtitleTask | None:
        """按目标路径创建或合并一个运行期字幕任务并返回任务快照。"""

        if not self._accepting:
            return None
        path_key = self._path_key(item.context.target_path)
        history_target = self._is_history_target(item)
        manual_handle = item.manual_handle
        manual_fields: dict[str, Any] = {}
        if manual_handle is not None:
            manual_fields = {
                "trigger": TaskTrigger.MANUAL_CANDIDATE,
                "manual_source": manual_handle.candidate.source,
                "manual_candidate_key": manual_handle.candidate.candidate_key,
                "manual_candidate_summary": manual_handle.candidate.model_dump(mode="json"),
                "actual_search_query": item.actual_search_query,
            }
        async with self._lock:
            existing_id = self._active_paths.get(path_key)
            if existing_id is not None:
                existing_task = await self._store.get_task(existing_id)
                if existing_task is not None and not existing_task.is_terminal:
                    app_log.logger.info(
                        f"{self._task_label(existing_task)}已存在同路径运行中任务，本次触发合并到既有任务"
                    )
                    return existing_task.model_copy(deep=True)
                self._active_paths.pop(path_key, None)
            task = SubtitleTask(
                media_title=item.context.title,
                year=item.context.year,
                media_type=item.context.media_type,
                season=item.context.season,
                episode=item.context.episode,
                tmdb_id=item.context.tmdb_id,
                imdb_id=item.context.imdb_id,
                target_file_name=item.context.target_file_name,
                target_path=item.context.target_path,
                target_history_id=item.target_history_id,
                history_target_path=item.context.target_path if history_target else None,
                target_storage=item.context.target_storage,
                **manual_fields,
            )
            await self._store.save_task(task)
            if manual_handle is not None:
                app_log.logger.info(
                    f"{self._task_label(task)}已创建，将下载{self._candidate_label(manual_handle.candidate)}，"
                    f"目标文件为“{task.target_path}”"
                )
            else:
                app_log.logger.info(f"{self._task_label(task)}已创建，目标文件为“{task.target_path}”")
            item.task_id = task.id
            self._active_paths[path_key] = task.id
            await self._queue.put(item)
            self._ensure_worker()
            return task.model_copy(deep=True)

    async def list_tasks(self) -> list[SubtitleTask]:
        """读取全部字幕任务快照。"""

        return await self._store.list_tasks()

    async def get_task(self, task_id: str) -> SubtitleTask | None:
        """按标识读取字幕任务快照。"""

        return await self._store.get_task(task_id)

    async def delete_task(self, task_id: str) -> bool:
        """删除指定字幕任务快照。"""

        return await self._store.delete_task(task_id)

    async def _worker_loop(self) -> None:
        """串行消费运行期队列。"""

        while self._accepting:
            item = await self._queue.get()
            try:
                task = await self._store.get_task(item.task_id) if item.task_id else None
                if task is not None:
                    await self._process(task, item)
                else:
                    app_log.logger.error(
                        f"字幕任务 {item.task_id or '未知'} 无法开始处理：持久化记录不存在，"
                        f"触发方式为“{'人工选择字幕' if item.manual_handle else '媒体整理事件'}”"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - worker 必须隔离单项任务异常
                app_log.logger.error(
                    f"字幕任务 {item.task_id or '未知'} 的 worker 发生未处理异常："
                    f"{type(exc).__name__}；插件调用栈：{self._safe_traceback()}"
                )
            finally:
                self._queue.task_done()
                key = self._path_key(item.context.target_path)
                async with self._lock:
                    if self._active_paths.get(key) == item.task_id:
                        self._active_paths.pop(key, None)

    async def _save(self, task: SubtitleTask) -> None:
        """持久化任务快照。"""

        await self._store.save_task(task)

    @staticmethod
    def _safe_traceback(exc: BaseException | None = None) -> str:
        """返回适合单行日志的精简插件调用栈。"""

        frames = traceback.extract_tb(exc.__traceback__ if exc is not None else sys.exc_info()[2], limit=8)
        return " | ".join(f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames)

    def _next_attempt_number(self) -> int:
        """返回串行 worker 内单调递增的候选尝试序号。"""

        self._attempt_seq += 1
        return self._attempt_seq

    async def _finish_task(
        self,
        task: SubtitleTask,
        status: TaskStatus,
        reason_code: str,
        reason_message: str,
    ) -> None:
        """写入任务终态、原因和耗时。"""

        now = utc_now()
        task.status = status
        task.reason_code = reason_code
        task.reason_message = reason_message
        task.finished_at = now
        task.duration_ms = elapsed_ms(task.started_at or task.created_at, now)
        await self._save(task)
        log = app_log.logger.warning if status is TaskStatus.FAILED else app_log.logger.info
        status_name = {
            TaskStatus.SUCCESS: "成功",
            TaskStatus.SKIPPED: "已跳过",
            TaskStatus.FAILED: "失败",
            TaskStatus.INTERRUPTED: "已中断",
        }.get(status, status.value)
        log(f"{self._task_label(task)}处理{status_name}：{reason_message}")

    async def _preflight(self, task: SubtitleTask, item: TaskWorkItem) -> bool:
        """完成本地文件、扩展名和已有字幕前置检查。"""

        context = item.context
        if context.target_storage != "local":
            await self._finish_task(task, TaskStatus.SKIPPED, "non_local_storage", "目标不是本地存储")
            return False
        if context.target_type != "file":
            await self._finish_task(task, TaskStatus.SKIPPED, "unsupported_media_container", "目标不是文件型媒体")
            return False
        extension = str(context.target_extension or Path(context.target_path).suffix.lstrip(".")).lower()
        if f".{extension}" not in self._media_extensions:
            await self._finish_task(
                task, TaskStatus.SKIPPED, "unsupported_media_format", "目标格式不在宿主媒体格式集合中"
            )
            return False
        if not self._is_history_target(item):
            task.target_file_exists = await AsyncPath(task.target_path).is_file()
        await self._save(task)
        if not task.target_file_exists and not self._is_history_target(item):
            await self._finish_task(task, TaskStatus.FAILED, "target_missing", "整理目标文件不存在")
            return False
        subtitle = await self._filesystem.has_standard_subtitle(Path(task.target_path))
        if subtitle:
            await self._finish_task(task, TaskStatus.SKIPPED, "existing_standard_subtitle", "目标已有标准简中外挂字幕")
            return False
        if task.media_type is MediaType.TV and task.episode is not None and task.season is None:
            await self._finish_task(
                task,
                TaskStatus.FAILED,
                "season_missing",
                "电视剧目标已有集号但缺少季号，无法安全查询字幕库存或匹配字幕，未搜索字幕源",
            )
            return False
        return True

    async def _prepare_history_target(self, task: SubtitleTask, item: TaskWorkItem) -> None:
        """通过唯一目标目录 seam 解析并冻结本次执行的实际路径。"""

        if not self._is_history_target(item):
            return
        history_path = task.history_target_path or item.context.target_path
        resolver = getattr(self._target_catalog, "resolve_actual_subtitle_path", None)
        if not callable(resolver):
            raise TypeError("字幕目标能力未提供实际路径解析")
        resolution = resolver(item.context.model_copy(update={"target_path": history_path}))
        task.history_target_path = resolution.original_path
        task.target_path = resolution.resolved_path
        task.matched_path_mapping = self._mapping_snapshot(resolution)
        task.target_file_exists = await AsyncPath(task.target_path).is_file()
        resolved_fields = (
            "title",
            "original_title",
            "english_title",
            "year",
            "media_type",
            "season",
            "episode",
            "tmdb_id",
            "imdb_id",
            "target_storage",
            "target_type",
            "target_extension",
            "target_container",
        )
        context_updates = {field: getattr(resolution, field) for field in resolved_fields if hasattr(resolution, field)}
        context_updates.update(
            {
                "target_path": task.target_path,
                "target_file_name": getattr(resolution, "target_file_name", Path(task.target_path).name)
                or Path(task.target_path).name,
            }
        )
        item.context = item.context.model_copy(update=context_updates)
        await self._save(task)
        if resolution.mapping is not None:
            app_log.logger.info(
                f"{self._task_label(task)}执行时应用整理历史路径映射："
                f"历史路径为“{resolution.original_path}”，实际路径为“{resolution.resolved_path}”"
            )

    async def _search_sources(self, task: SubtitleTask, item: TaskWorkItem) -> list[CandidateHandle]:
        """查询共享来源批次，在准入处执行自动漏斗并与当前目标匹配。"""

        batch = await self._candidate_pool.query(item.context)
        configured_sources = self._sources.keys() if isinstance(self._sources, Mapping) else ()
        sources_to_visit = [
            source for source in SubtitleSource if source in batch.sources or source in configured_sources
        ]
        handles: list[CandidateHandle] = []
        self._source_conclusions = []
        for source in sources_to_visit:
            result = batch.sources.get(source)
            if result is None:
                await self._save_source_failure(source, f"{SOURCE_NAMES[source]}查询结果缺失")
                app_log.logger.error(f"{self._task_label(task)}查询{SOURCE_NAMES[source]}时缺少共享来源结果")
                self._source_conclusions.append(f"{SOURCE_NAMES[source]}查询结果缺失")
                continue
            self._source_conclusions.append(f"{SOURCE_NAMES[source]}：{describe_source_run(result)}")

            candidates, rejection_summary = admit_automatic_candidates(
                result.candidates,
                item.context,
                allow_machine_translation=self._config.allow_machine_translation,
            )
            admitted_count = len(candidates)
            if result.error_code is not None and result.status in {
                SourceSearchStatus.LIMITED,
                SourceSearchStatus.ERROR,
            }:
                summary = result.error_summary or "字幕源请求异常"
            else:
                summary = None
            media_matched_count = 0
            for handle in candidates:
                normalized = self._matcher.normalize_candidate(handle.candidate, item.context, item.match_context)
                if normalized is not None:
                    handles.append(CandidateHandle(candidate=normalized, download_handle=handle.download_handle))
                    media_matched_count += 1
            media_rejected = admitted_count - media_matched_count
            if media_rejected:
                rejection_summary["media_or_episode_mismatch"] = (
                    rejection_summary.get("media_or_episode_mismatch", 0) + media_rejected
                )
            self._log_source_result(
                task,
                source,
                result,
                admitted_count=admitted_count,
                media_matched_count=media_matched_count,
                rejection_summary=rejection_summary,
            )
            await self._save_source_status(source, result, summary)
        if handles:
            app_log.logger.info(
                f"{self._task_label(task)}已汇总 {len(sources_to_visit)} 个字幕来源的处理结果，"
                f"共获得 {len(handles)} 个适用于当前目标的候选"
            )
        else:
            app_log.logger.warning(
                f"{self._task_label(task)}已汇总 {len(sources_to_visit)} 个字幕来源的处理结果，但没有获得适用于当前目标的候选"
            )
        return handles

    async def _save_source_status(
        self,
        source: SubtitleSource,
        result: SourceSearchResult,
        summary: str | None,
    ) -> None:
        """按来源最小结果保存来源健康状态。"""

        if result.status is SourceSearchStatus.ERROR:
            await self._save_source_failure(source, summary, False, result.duration_ms)
        elif result.status is SourceSearchStatus.LIMITED or (
            result.status is SourceSearchStatus.PARTIAL and not result.candidates
        ):
            await self._save_source_failure(source, summary, True, result.duration_ms)
        elif result.status is SourceSearchStatus.UNCONFIGURED:
            await self._save_source_unavailable(
                source,
                SOURCE_SKIP_REASONS.get(result.skip_reason or "", summary or "来源当前不可调用"),
                result.duration_ms,
            )
        elif result.skip_reason is None and result.status not in {
            SourceSearchStatus.DISABLED,
            SourceSearchStatus.UNCONFIGURED,
        }:
            await self._save_source_success(source, duration_ms=result.duration_ms)

    def _log_source_result(
        self,
        task: SubtitleTask,
        source: SubtitleSource,
        result: SourceSearchResult,
        *,
        admitted_count: int,
        media_matched_count: int,
        rejection_summary: dict[str, int],
    ) -> None:
        """逐源输出统一来源事实结论，并在准入步骤后追加自动准入漏斗结果。"""

        log = app_log.logger.warning if source_run_is_warning(result) else app_log.logger.info
        prefix = f"{self._task_label(task)}的 {SOURCE_NAMES[source]} 搜索"
        funnel = self._admission_funnel(
            result,
            admitted_count=admitted_count,
            media_matched_count=media_matched_count,
            rejection_summary=rejection_summary,
        )
        log(f"{prefix}{describe_source_run(result)}{funnel}")

    @staticmethod
    def _admission_funnel(
        result: SourceSearchResult,
        *,
        admitted_count: int,
        media_matched_count: int,
        rejection_summary: dict[str, int],
    ) -> str:
        """在来源事实结论后追加自动侧独有的准入漏斗句；未执行来源没有漏斗。"""

        if result.status in {SourceSearchStatus.DISABLED, SourceSearchStatus.UNCONFIGURED} or result.skip_reason:
            return ""
        text = f"；自动规则保留 {admitted_count} 个，其中 {media_matched_count} 个适用于当前目标"
        rejection_text = describe_rejections(rejection_summary)
        if rejection_text != "无":
            text += f"；自动规则排除：{rejection_text}"
        return text

    def _no_candidate_reason_message(self) -> str:
        """按固定开头与各来源一句短结论构造无候选任务摘要。"""

        if not self._source_conclusions:
            return "没有可用的合格简中字幕候选"
        return "没有可用的合格简中字幕候选；各来源结论：" + "；".join(self._source_conclusions)

    def _source_status_snapshot(self, source: SubtitleSource) -> SourceStatus | None:
        """读取来源 facade 提供的当前配置与运行详情。"""

        snapshot = getattr(self._sources, "status_snapshot", None)
        if callable(snapshot):
            return cast(SourceStatus, snapshot(source))
        if isinstance(self._sources, Mapping):
            adapter = self._sources.get(source)
            runtime_details = getattr(adapter, "runtime_details", dict)
            return SourceStatus(
                source=source,
                enabled=bool(getattr(adapter, "enabled", False)),
                configured=bool(getattr(adapter, "configured", adapter is not None)),
                details=runtime_details() if callable(runtime_details) else {},
            )
        return None

    async def _persist_source_status(
        self,
        source: SubtitleSource,
        *,
        health: SourceHealth,
        duration_ms: int | None,
        error_summary: str | None = None,
        success: bool = False,
        details: dict[str, Any] | None = None,
        unavailable: bool = False,
    ) -> None:
        """读取既有状态、合并 facade 快照并按统一形状保存来源健康状态。

        三个来源状态入口只保留健康值、错误与是否不可用的差异；``unavailable``
        表示来源未配置或未启用，此时配置一律记为未配置。
        """

        existing = {item.source: item for item in await self._store.list_source_statuses()}.get(source)
        status = existing or SourceStatus(source=source)
        snapshot = self._source_status_snapshot(source)
        if snapshot is not None:
            status.enabled = bool(snapshot.enabled) if unavailable else snapshot.enabled
            status.configured = False if unavailable else snapshot.configured
            status.details = {**status.details, **snapshot.details}
        elif unavailable:
            status.enabled = False
            status.configured = False
        status.health = health
        status.last_checked_at = utc_now()
        if success:
            status.last_success_at = status.last_checked_at
            status.details = {**status.details, **(details or {})}
        else:
            status.last_error_at = status.last_checked_at
            status.last_error_summary = error_summary
        status.last_duration_ms = duration_ms
        await self._store.save_source_status(status)

    async def _save_source_success(
        self,
        source: SubtitleSource,
        details: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """保存来源成功搜索的非敏感状态。"""

        await self._persist_source_status(
            source,
            health=SourceHealth.HEALTHY,
            duration_ms=duration_ms,
            success=True,
            details=details,
        )

    async def _save_source_failure(
        self,
        source: SubtitleSource,
        summary: str | None,
        limited: bool = False,
        duration_ms: int | None = None,
    ) -> None:
        """保存来源失败或限流的脱敏状态。"""

        await self._persist_source_status(
            source,
            health=SourceHealth.LIMITED if limited else SourceHealth.ERROR,
            duration_ms=duration_ms,
            error_summary=summary,
        )

    async def _save_source_unavailable(
        self,
        source: SubtitleSource,
        summary: str,
        duration_ms: int | None = None,
    ) -> None:
        """保存来源当前不可调用且未发出搜索请求的状态。"""

        await self._persist_source_status(
            source,
            health=SourceHealth.DISABLED,
            duration_ms=duration_ms,
            error_summary=summary,
            unavailable=True,
        )

    async def _consume_inventory(self, task: SubtitleTask, item: TaskWorkItem) -> InventoryConsumeResult:
        """在外部搜索前查询并消费精确库存字幕。"""

        result = await self._inventory.consume(
            item.context,
            task.id,
            target_history_id=task.target_history_id,
            history_target_path=task.history_target_path,
            matched_path_mapping=task.matched_path_mapping,
            target_file_exists=task.target_file_exists,
        )
        records = self._normalize_records(result.records or result.record)
        if records:
            log = app_log.logger.warning if result.warning else app_log.logger.info
            log(f"{self._task_label(task)}命中 {len(records)} 条字幕库存记录，字幕已写入媒体目录")
        elif result.warning:
            app_log.logger.warning(f"{self._task_label(task)}查询字幕库存时出现警告：{result.warning}")
        else:
            app_log.logger.info(f"{self._task_label(task)}没有找到对应的暂存字幕，将继续查询字幕源")
        return result

    @staticmethod
    def _normalize_records(value: MatchRecord | Sequence[MatchRecord] | None) -> list[MatchRecord]:
        """把单条或多条业务返回统一为逐文件匹配记录列表。"""

        if value is None:
            return []
        if isinstance(value, MatchRecord):
            return [value]
        return [record for record in value if isinstance(record, MatchRecord)]

    async def _publish_committed_files(
        self,
        task: SubtitleTask,
        operation: SubtitleWrittenOperation,
        facts: Sequence[CommittedFileFact],
    ) -> None:
        """逐文件尽力发布已经提交的媒体目录字幕事实。"""

        for fact in facts:
            try:
                await self._publisher.publish(
                    SubtitleWrittenEvent(
                        plugin_id="SubtitleAssistant",
                        operation=operation,
                        task_id=task.id,
                        record_id=fact.record.id,
                        target_path=fact.target_path,
                        subtitle_path=fact.subtitle_path,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 发布失败不得改变已提交业务事实
                app_log.logger.warning(f"字幕落盘事件发布失败，已保留成功业务结果；异常类型为 {type(exc).__name__}")

    async def _try_candidate(
        self,
        task: SubtitleTask,
        item: TaskWorkItem,
        handle: CandidateHandle,
        *,
        operation: SubtitleWrittenOperation | None = None,
        retention: FailureResultRetention | None = None,
    ) -> CandidateAttemptResult:
        """委托候选尝试模块处理单个候选并记录业务结论。"""

        operation = operation or item.attempt_operation or SubtitleWrittenOperation.AUTOMATIC_CANDIDATE
        retention = retention or FailureResultRetention(item.attempt_retention or FailureResultRetention.DISCARD.value)
        result = await self._candidate_attempt.attempt(
            CandidateAttemptRequest(
                task_id=task.id,
                handle=handle,
                target=item.context.model_copy(update={"target_path": task.target_path}),
                operation=operation,
                retention=retention,
                package_attribution_strategy=self._strategy,
                attempt_number=self._next_attempt_number(),
                target_history_id=task.target_history_id,
                history_target_path=task.history_target_path,
                matched_path_mapping=task.matched_path_mapping,
                target_file_exists=task.target_file_exists,
            )
        )
        await self._finalize_candidate_attempt(task, handle.candidate, result)
        if result.result is AttemptResult.INTERRUPTED:
            await self._publish_committed_files(task, operation, result.committed_files)
            raise asyncio.CancelledError
        return result

    async def _finalize_candidate_attempt(
        self,
        task: SubtitleTask,
        candidate: SubtitleCandidate,
        result: CandidateAttemptResult,
    ) -> None:
        """累计记录计数、保存任务快照并输出一次候选结论。"""

        for record in result.records:
            task.record_counts[record.status.value] = task.record_counts.get(record.status.value, 0) + 1
        if result.records:
            first_record = result.records[0]
            task.final_subtitle_path = first_record.final_subtitle_path
            task.result_source = candidate.source
            task.result_package_scope = candidate.package_scope
            task.result_format = first_record.format
        written_count = sum(1 for record in result.committed_media_records if record.status is RecordStatus.MATCHED)
        try:
            await self._save(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if written_count == 0:
                raise
            app_log.logger.error(
                f"{self._task_label(task)}候选结果快照保存失败，已提交文件事实仍将继续发布；"
                f"异常类型为 {type(exc).__name__}"
            )
        log = (
            app_log.logger.warning
            if result.result is not AttemptResult.SUCCESS or result.error_summary and written_count > 0
            else app_log.logger.info
        )
        if result.result is AttemptResult.SUCCESS:
            log(
                f"{self._task_label(task)}候选尝试成功：{self._candidate_label(candidate)}已落盘 {written_count} 个字幕"
            )
        else:
            log(
                f"{self._task_label(task)}候选尝试未成功：{self._candidate_label(candidate)}"
                f"结束原因是“{result.error_summary or result.result.value}”"
            )

    async def _process(self, task: SubtitleTask, item: TaskWorkItem) -> None:
        """执行单个字幕任务的完整状态机。"""

        task.status = TaskStatus.PROCESSING
        task.started_at = utc_now()
        await self._save(task)
        try:
            if item.manual_handle is not None:
                await self._prepare_history_target(task, item)
                item.attempt_operation = SubtitleWrittenOperation.MANUAL_CANDIDATE
                item.attempt_retention = FailureResultRetention.PRESERVE.value
                candidate_result = await self._try_candidate(task, item, item.manual_handle)
                media_records = self._normalize_records(candidate_result.committed_media_records)
                await self._publish_committed_files(
                    task,
                    SubtitleWrittenOperation.MANUAL_CANDIDATE,
                    candidate_result.committed_files,
                )
                retained_records = self._normalize_records(candidate_result.records)
                if media_records:
                    await self._finish_task(task, TaskStatus.SUCCESS, "subtitle_written", "人工选择的字幕已落盘")
                elif retained_records:
                    await self._finish_task(task, TaskStatus.SUCCESS, "subtitle_retained", "人工选择的字幕已安全保留")
                else:
                    reason_code = (
                        candidate_result.reason_code.value
                        if candidate_result.reason_code is not None
                        else CandidateAttemptReasonCode.MANUAL_CANDIDATE_FAILED.value
                    )
                    await self._finish_task(
                        task,
                        TaskStatus.FAILED,
                        reason_code,
                        f"人工选择的字幕处理失败：{candidate_result.error_summary or '没有得到可落盘字幕'}",
                    )
                return
            await self._prepare_history_target(task, item)
            if not await self._preflight(task, item):
                return
            inventory = await self._consume_inventory(task, item)
            inventory_records = self._normalize_records(inventory.records or inventory.record)
            if inventory_records:
                await self._publish_committed_files(
                    task,
                    SubtitleWrittenOperation.INVENTORY_CONSUMPTION,
                    inventory.committed_files,
                )
                first_record = inventory_records[0]
                task.result_source = first_record.source
                task.result_package_scope = first_record.package_scope
                task.result_format = first_record.format
                task.final_subtitle_path = first_record.final_subtitle_path
                task.record_counts[RecordStatus.MATCHED.value] = task.record_counts.get(
                    RecordStatus.MATCHED.value,
                    0,
                ) + len(inventory_records)
                await self._finish_task(task, TaskStatus.SUCCESS, "staged_inventory_consumed", "已消费字幕库存并落盘")
                return
            handles = await self._search_sources(task, item)
            if not handles:
                await self._finish_task(
                    task,
                    TaskStatus.FAILED,
                    "no_qualified_candidates",
                    self._no_candidate_reason_message(),
                )
                return
            ordered = sorted(
                handles,
                key=lambda handle: candidate_rank(
                    handle.candidate,
                    self._config.format_priority,
                    [source.value for source in self._config.source_priority],
                ),
            )
            attempt_summaries: list[str] = []
            attempt_count = 0
            for handle in ordered[: self._config.max_candidate_attempts]:
                item.attempt_operation = SubtitleWrittenOperation.AUTOMATIC_CANDIDATE
                item.attempt_retention = FailureResultRetention.DISCARD.value
                attempt_count += 1
                candidate_result = await self._try_candidate(task, item, handle)
                records = self._normalize_records(candidate_result.committed_media_records)
                attempt_summaries.append(
                    f"{SOURCE_NAMES[handle.candidate.source]} 候选“{handle.candidate.candidate_key}”："
                    f"{candidate_result.error_summary or ATTEMPT_RESULT_NAMES[candidate_result.result]}"
                )
                if records:
                    await self._publish_committed_files(
                        task,
                        SubtitleWrittenOperation.AUTOMATIC_CANDIDATE,
                        candidate_result.committed_files,
                    )
                    await self._finish_task(task, TaskStatus.SUCCESS, "subtitle_written", "字幕已落盘")
                    return
            unattempted_count = max(0, len(ordered) - attempt_count)
            if unattempted_count:
                reason_prefix = (
                    f"已达到最大候选尝试数 {self._config.max_candidate_attempts}；"
                    f"本次 {attempt_count} 次尝试均未成功，另有 {unattempted_count} 个候选未尝试"
                )
            else:
                reason_prefix = f"全部 {attempt_count} 个候选均已尝试但未成功"
            reason_message = f"{reason_prefix}：" + "；".join(attempt_summaries)
            await self._finish_task(task, TaskStatus.FAILED, "candidate_attempts_exhausted", reason_message)
        except asyncio.CancelledError:
            await self._finish_task(task, TaskStatus.INTERRUPTED, "service_interrupted", "插件停止时任务被中断")
            raise
        except Exception as exc:  # noqa: BLE001 - 任务边界必须收敛运行时失败
            app_log.logger.error(
                f"{self._task_label(task)}发生非预期处理异常：{type(exc).__name__}；"
                f"插件调用栈：{self._safe_traceback()}"
            )
            await self._finish_task(task, TaskStatus.FAILED, "processing_error", "字幕任务处理异常")
        finally:
            try:
                await self._filesystem.cleanup_task_directory(task.id)
            except Exception as exc:  # noqa: BLE001 - 临时目录清理失败不能覆盖任务结果
                app_log.logger.warning(f"{self._task_label(task)}的临时目录清理失败：{type(exc).__name__}")

    async def refresh_sources(self, manual: bool = True) -> list[SourceStatus]:
        """并发刷新三个字幕源且互不连带失败。"""

        refresher = getattr(self._sources, "refresh", None)
        if callable(refresher):
            return await refresher(manual=manual)
        return []

    def stop_sync(self, reason: str = "插件已停用，未完成任务已中断") -> None:
        """同步停止接收事件、取消 worker 并标记未完成任务。"""

        if not self._accepting:
            return
        self._accepting = False
        worker_loop: asyncio.AbstractEventLoop | None = None
        if self._worker and not self._worker.done():
            worker_loop = self._worker.get_loop()
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if worker_loop is current_loop:
                self._worker.cancel()
            elif worker_loop.is_running():
                worker_loop.call_soon_threadsafe(self._worker.cancel)
        self._active_paths.clear()
        mark_interrupted = getattr(self._store, "mark_nonterminal_interrupted_sync", None)
        if callable(mark_interrupted):
            cast(Callable[[str], object], mark_interrupted)(reason)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        cleanup_loop = loop or worker_loop
        if cleanup_loop and cleanup_loop.is_running():
            if cleanup_loop is loop:
                cleanup_loop.create_task(self._cleanup_runtime())
            else:
                asyncio.run_coroutine_threadsafe(self._cleanup_runtime(), cleanup_loop)

    async def _close_sources(self) -> None:
        """异步关闭全部字幕源。"""

        closer = getattr(self._sources, "close", None)
        if callable(closer):
            await closer()
            return
        source_map = cast(Mapping[SubtitleSource, _TaskSourcePort], self._sources)
        await asyncio.gather(*(source.close() for source in source_map.values()), return_exceptions=True)

    async def _cleanup_runtime(self) -> None:
        """终止解包并关闭全部字幕源。"""

        if self._cleanup_started:
            return
        self._cleanup_started = True
        if not self._manage_resources:
            return
        await self._archive.cancel()
        await self._close_sources()
        closer = getattr(self._candidate_pool, "close", None)
        if callable(closer):
            try:
                result = closer()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - 查询缓存关闭失败不能覆盖任务结果
                app_log.logger.error(f"共享字幕候选池缓存关闭失败：{type(exc).__name__}")

    async def shutdown(self, reason: str = "插件已停用，未完成任务已中断") -> None:
        """异步停止并等待运行资源释放。"""

        worker = self._worker
        self.stop_sync(reason)
        if worker and worker.get_loop() is asyncio.get_running_loop():
            await asyncio.gather(worker, return_exceptions=True)
        await self._cleanup_runtime()

    async def reset(self) -> None:
        """停止运行并清理插件数据目录及四个分区。"""

        await self.shutdown("插件数据重置，未完成任务已中断")
        await self._filesystem.clear_data_directory()
        await self._store.reset()
