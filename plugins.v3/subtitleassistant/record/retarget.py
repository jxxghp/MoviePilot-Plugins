"""匹配记录改配目标应用服务。"""

from __future__ import annotations

import asyncio
import os
import traceback
from collections import Counter
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from anyio import Path as AsyncPath

from app.log import logger

from ..schemas.base import utc_now
from ..schemas.event import SubtitleWrittenEvent, SubtitleWrittenOperation
from ..schemas.record import (
    BatchRetargetPreview,
    BatchRetargetPreviewItem,
    BatchRetargetResult,
    BatchRetargetResultItem,
    FileLocation,
    MatchRecord,
    RecordStatus,
    RetargetHistoryEntry,
    RetargetMapping,
    RetargetPreview,
    RetargetResult,
)
from ..schemas.target import MediaType, PathMappingResolution, PathMappingSnapshot, SearchTarget, SubtitleTarget
from .lock import ReentrantAsyncLock

MIN_BATCH_RETARGET_MAPPINGS = 1
MAX_BATCH_RETARGET_MAPPINGS = 100
SUBTITLE_ASSISTANT_PLUGIN_ID = "SubtitleAssistant"


class SubtitleEventPublisher(Protocol):
    """改配提交完成后使用的字幕落盘事件端口。"""

    async def publish(self, event: SubtitleWrittenEvent) -> None:
        """尽力广播已经提交的字幕落盘事实。"""


class _NoopSubtitleEvents:
    """未接入宿主事件时忽略通知。"""

    async def publish(self, event: SubtitleWrittenEvent) -> None:
        """忽略字幕落盘通知。"""


async def _publish_subtitle_written_best_effort(
    publisher: SubtitleEventPublisher,
    event: SubtitleWrittenEvent,
) -> None:
    """发布已提交事件；通知失败不改变业务结果，取消继续向上传播。"""

    try:
        await publisher.publish(event)
    except Exception as exc:  # noqa: BLE001 - 提交后的通知失败不能回滚业务事实
        logger.warning(f"字幕落盘事件发布失败，已保留成功业务结果；异常类型为 {type(exc).__name__}")


class RetargetStorePort(Protocol):
    """改配目标所需的匹配记录持久化能力。"""

    async def get_record(self, record_id: str) -> MatchRecord | None:
        """读取一个匹配记录快照。"""

    async def save_record(self, record: MatchRecord) -> None:
        """保存一个匹配记录快照。"""


class RetargetFileSystemPort(Protocol):
    """改配目标所需的字幕文件能力。"""

    def media_subtitle_path(self, source: Path, target: Path) -> Path:
        """返回标准命名后的预计字幕路径。"""

    async def is_file(self, path: Path) -> bool:
        """判断路径当前是否为普通文件。"""

    async def target_directory_status(self, target: Path) -> tuple[bool, str | None]:
        """检查目标文件父目录是否可以写入字幕。"""

    async def write_media_subtitle(self, source: Path, target: Path) -> Path:
        """把字幕排他复制到目标视频旁。"""

    async def copy_file_exclusive(self, source: Path, target: Path) -> int:
        """把字幕排他复制到精确路径。"""

    async def delete_subtitle_file(self, path: Path) -> None:
        """删除一个精确字幕文件。"""

    async def plugin_file_path(self, relative_path: str) -> Path:
        """安全解析插件数据目录中的记录文件。"""


class RetargetInventoryPort(Protocol):
    """改配目标所需的暂存库存维护能力。"""

    def reserve_for_retarget(
        self,
        record: MatchRecord,
    ) -> AbstractAsyncContextManager[RetargetInventoryReservation]:
        """在改配事务期间保留暂存记录并阻止库存消费。"""


class RetargetInventoryReservation(Protocol):
    """改配服务使用的库存保留凭据。"""

    available: bool

    def commit(self) -> None:
        """在记录与文件均成功更新后提交库存移除。"""


class RetargetTargetQueryPort(Protocol):
    """按 MoviePilot 整理历史读取可选目标。"""

    async def get_target(self, history_id: int) -> SearchTarget | None:
        """返回有效的单文件本地整理历史目标。"""

    async def list_all_targets(self) -> Sequence[SearchTarget]:
        """返回全部去重后的有效整理历史目标。"""

    def resolve_actual_subtitle_path(self, target: SubtitleTarget) -> PathMappingResolution:
        """解析整理历史目标的实际字幕路径。"""


class RetargetService:
    """按当前映射预览并原地移动一条匹配记录。"""

    def __init__(
        self,
        store: RetargetStorePort,
        filesystem: RetargetFileSystemPort,
        inventory: RetargetInventoryPort,
        targets: RetargetTargetQueryPort,
        mutation_lock: ReentrantAsyncLock | None = None,
        publisher: SubtitleEventPublisher | None = None,
    ) -> None:
        """绑定持久化、文件系统、库存、目标查询与事件发布器。"""

        self._store = store
        self._filesystem = filesystem
        self._inventory = inventory
        self._targets = targets
        self._lock = asyncio.Lock()
        self._mutation_lock = mutation_lock or ReentrantAsyncLock()
        self._publisher = publisher or _NoopSubtitleEvents()

    @staticmethod
    def _normalized_path(path: str | Path) -> str:
        """返回用于比较本地目标的规范路径。"""

        return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))

    async def _record_source_path(self, record: MatchRecord) -> Path:
        """把记录位置解析为当前字幕绝对路径。"""

        if record.location is FileLocation.PLUGIN_DATA:
            path = await self._filesystem.plugin_file_path(str(record.path))
        else:
            path = Path(record.path)
            if not path.is_absolute():
                raise ValueError("媒体目录字幕路径必须是绝对路径")
        if await AsyncPath(path).is_symlink():
            raise ValueError("原字幕文件不能是符号链接")
        return path

    def _resolve_target(self, target: SearchTarget) -> PathMappingResolution:
        """使用调用时的当前配置解析整理历史目标路径。"""

        resolver = getattr(self._targets, "resolve_actual_subtitle_path", None)
        if callable(resolver):
            return resolver(target.context)
        raise RuntimeError("字幕目标能力未提供实际路径解析")

    async def _build_preview(
        self,
        record: MatchRecord,
        target: SearchTarget,
        target_history_id: int,
    ) -> RetargetPreview:
        """计算一次不产生文件副作用的改配预览。"""

        source = await self._record_source_path(record)
        resolution = self._resolve_target(target)
        resolved_target = Path(resolution.resolved_path)
        destination = self._filesystem.media_subtitle_path(source, resolved_target)
        available, error = await self._filesystem.target_directory_status(resolved_target)
        return RetargetPreview(
            target_history_id=target_history_id,
            history_target_path=resolution.original_path,
            target_path=resolution.resolved_path,
            final_subtitle_path=destination,
            directory_available=available,
            directory_error=error,
        )

    async def preview(self, record_id: str, target_history_id: int) -> RetargetResult:
        """返回按当前映射计算的改配目标预览。"""

        record = await self._store.get_record(record_id)
        if record is None:
            return RetargetResult(error_code="record_not_found", message="匹配记录不存在")
        target = await self._targets.get_target(target_history_id)
        if target is None:
            return RetargetResult(error_code="target_not_found", message="整理历史目标不存在")
        try:
            preview = await self._build_preview(record, target, target_history_id)
        except (OSError, ValueError) as exc:
            return RetargetResult(
                error_code="preview_failed",
                message=f"无法计算改配预览：{exc}",
            )
        return RetargetResult(preview=preview)

    @staticmethod
    def _matches_exact_target(record: MatchRecord, target: SearchTarget) -> bool:
        """按共同媒体标识、类型与完整季集判断唯一精确目标。"""

        context = target.context
        if record.media_type is MediaType.UNKNOWN or context.media_type is MediaType.UNKNOWN:
            return False
        if record.media_type is not context.media_type:
            return False
        record_imdb = (record.imdb_id or "").strip().casefold()
        target_imdb = (context.imdb_id or "").strip().casefold()
        has_common_tmdb = record.tmdb_id is not None and context.tmdb_id is not None
        has_common_imdb = bool(record_imdb and target_imdb)
        if has_common_tmdb and record.tmdb_id != context.tmdb_id:
            return False
        if has_common_imdb and record_imdb != target_imdb:
            return False
        identity_matches = (has_common_tmdb and record.tmdb_id == context.tmdb_id) or (
            not has_common_tmdb and has_common_imdb and record_imdb == target_imdb
        )
        if not identity_matches:
            return False
        if record.media_type is MediaType.TV:
            return (
                record.season is not None
                and record.episode is not None
                and record.season == context.season
                and record.episode == context.episode
            )
        return True

    @classmethod
    def _suggest_target(
        cls,
        record: MatchRecord,
        targets: Sequence[SearchTarget],
    ) -> SearchTarget | None:
        """仅在精确匹配结果唯一时返回自动建议目标。"""

        matches = [target for target in targets if cls._matches_exact_target(record, target)]
        return matches[0] if len(matches) == 1 else None

    async def _preview_mapping(
        self,
        mapping: RetargetMapping,
        all_targets: Sequence[SearchTarget],
        target_cache: dict[int, SearchTarget | None],
    ) -> BatchRetargetPreviewItem:
        """校验一条批量映射并返回完整路径预览。"""

        record = await self._store.get_record(mapping.record_id)
        if record is None:
            return BatchRetargetPreviewItem(
                record_id=mapping.record_id,
                target_history_id=mapping.target_history_id,
                error_code="record_not_found",
                message="匹配记录不存在",
            )
        target = None
        target_history_id = mapping.target_history_id
        if target_history_id is None:
            target = self._suggest_target(record, all_targets)
            if target is None:
                return BatchRetargetPreviewItem(
                    record_id=mapping.record_id,
                    current_subtitle_path=record.path,
                    error_code="target_required",
                    message="无法唯一确定整理历史目标，请手动选择",
                )
            target_history_id = target.history_id
        else:
            if target_history_id not in target_cache:
                target_cache[target_history_id] = await self._targets.get_target(target_history_id)
            target = target_cache[target_history_id]
        if target is None:
            return BatchRetargetPreviewItem(
                record_id=mapping.record_id,
                current_subtitle_path=record.path,
                target_history_id=target_history_id,
                error_code="target_not_found",
                message="整理历史目标不存在",
            )
        try:
            source = await self._record_source_path(record)
            preview = await self._build_preview(record, target, target_history_id)
        except (OSError, ValueError) as exc:
            return BatchRetargetPreviewItem(
                record_id=mapping.record_id,
                current_subtitle_path=record.path,
                target_history_id=target_history_id,
                target=target,
                error_code="preview_failed",
                message=f"无法计算改配预览：{exc}",
            )
        item = BatchRetargetPreviewItem(
            record_id=mapping.record_id,
            current_subtitle_path=record.path,
            target_history_id=target_history_id,
            target=target,
            preview=preview,
        )
        if not await self._filesystem.is_file(source):
            return replace(item, error_code="source_file_missing", message="原字幕文件不存在")
        current_subtitle = Path(record.final_subtitle_path or record.path)
        if self._normalized_path(str(current_subtitle)) == self._normalized_path(preview.final_subtitle_path):
            return replace(item, error_code="same_target", message="预计最终字幕路径与当前路径相同")
        if not preview.directory_available:
            return replace(
                item,
                error_code="target_directory_unavailable",
                message=preview.directory_error or "目标目录不可用",
            )
        if await self._filesystem.is_file(Path(preview.final_subtitle_path)):
            return replace(item, error_code="destination_conflict", message="预计最终字幕路径已存在")
        return item

    async def _preview_batch_unlocked(
        self,
        mappings: list[RetargetMapping],
    ) -> BatchRetargetPreview:
        """在调用方所处并发边界内完成整批预检。"""

        duplicate_ids = {
            record_id for record_id, count in Counter(mapping.record_id for mapping in mappings).items() if count > 1
        }
        all_targets = (
            await self._targets.list_all_targets()
            if any(mapping.target_history_id is None for mapping in mappings)
            else []
        )
        target_cache: dict[int, SearchTarget | None] = {}
        items: list[BatchRetargetPreviewItem] = []
        for mapping in mappings:
            if mapping.record_id in duplicate_ids:
                items.append(
                    BatchRetargetPreviewItem(
                        record_id=mapping.record_id,
                        target_history_id=mapping.target_history_id,
                        error_code="duplicate_record",
                        message="同一匹配记录不能在批次中重复出现",
                    )
                )
                continue
            items.append(await self._preview_mapping(mapping, all_targets, target_cache))

        destination_counts = Counter(
            self._normalized_path(item.preview.final_subtitle_path)
            for item in items
            if item.executable and item.preview is not None
        )
        for index, item in enumerate(items):
            if (
                item.executable
                and item.preview is not None
                and destination_counts[self._normalized_path(item.preview.final_subtitle_path)] > 1
            ):
                items[index] = replace(
                    item,
                    error_code="batch_destination_conflict",
                    message="批次中多条记录将写入同一最终字幕路径",
                )
        return BatchRetargetPreview(items=items)

    @staticmethod
    def _validate_batch_mapping_count(mappings: list[RetargetMapping]) -> None:
        """拒绝空批次和超过同步改配上限的批次。"""

        mapping_count = len(mappings)
        if not MIN_BATCH_RETARGET_MAPPINGS <= mapping_count <= MAX_BATCH_RETARGET_MAPPINGS:
            raise ValueError(
                f"批量改配映射数量必须在 {MIN_BATCH_RETARGET_MAPPINGS} 至 {MAX_BATCH_RETARGET_MAPPINGS} 条之间"
            )

    async def preview_batch(self, mappings: list[RetargetMapping]) -> BatchRetargetPreview:
        """自动建议缺失目标并返回批量改配整体预检。"""

        self._validate_batch_mapping_count(mappings)
        return await self._preview_batch_unlocked(mappings)

    @staticmethod
    def _mapping_snapshot(resolution: PathMappingResolution) -> PathMappingSnapshot | None:
        """把命中规则转换为持久化审计快照。"""

        if resolution.mapping is None:
            return None
        return PathMappingSnapshot(
            source_prefix=Path(resolution.mapping.source_prefix),
            target_prefix=Path(resolution.mapping.target_prefix),
        )

    async def _updated_record(
        self,
        record: MatchRecord,
        target: SearchTarget,
        target_history_id: int,
        resolution: PathMappingResolution,
        old_subtitle: Path,
        destination: Path,
    ) -> MatchRecord:
        """构造成功改配后的记录快照。"""

        context = target.context
        updated = record.model_copy(deep=True)
        identity = context.canonical_identity
        now = utc_now()
        updated.subtitle_file_name = destination.name
        updated.format = destination.suffix.lstrip(".").upper()
        updated.media_title = context.title
        updated.year = context.year
        updated.media_type = context.media_type
        updated.season = context.season
        updated.episode = context.episode
        updated.status = RecordStatus.MATCHED
        updated.location = FileLocation.MEDIA_DIRECTORY
        updated.path = destination
        updated.updated_at = now
        updated.canonical_identity_type = identity[0] if identity else None
        updated.canonical_identity_value = identity[1] if identity else None
        updated.tmdb_id = context.tmdb_id
        updated.imdb_id = context.imdb_id
        updated.target_history_id = target_history_id
        updated.history_target_path = resolution.original_path
        updated.target_path = resolution.resolved_path
        updated.matched_path_mapping = self._mapping_snapshot(resolution)
        updated.target_file_exists = await self._filesystem.is_file(Path(resolution.resolved_path))
        updated.final_subtitle_path = destination
        updated.retarget_history.append(
            RetargetHistoryEntry(
                operated_at=now,
                old_target_history_id=record.target_history_id,
                new_target_history_id=target_history_id,
                old_history_target_path=record.history_target_path,
                new_history_target_path=resolution.original_path,
                old_target_path=record.target_path,
                new_target_path=resolution.resolved_path,
                new_matched_path_mapping=self._mapping_snapshot(resolution),
                old_subtitle_path=old_subtitle,
                new_subtitle_path=destination,
            )
        )
        return updated

    async def _publish_subtitle_written(self, record: MatchRecord) -> None:
        """在改配事务提交后发布一条不关联字幕任务的落盘事实。"""

        await _publish_subtitle_written_best_effort(
            self._publisher,
            SubtitleWrittenEvent(
                plugin_id=SUBTITLE_ASSISTANT_PLUGIN_ID,
                operation=SubtitleWrittenOperation.RETARGET,
                task_id=None,
                record_id=record.id,
                target_path=record.target_path or record.path,
                subtitle_path=record.final_subtitle_path or record.path,
            ),
        )

    async def _publish_subtitle_written_records(self, records: Sequence[MatchRecord]) -> None:
        """按已经提交的每个媒体目录字幕文件独立发布落盘事实。"""

        for record in records:
            await self._publish_subtitle_written(record)

    async def _retarget_unlocked(self, record_id: str, target_history_id: int) -> RetargetResult:
        """在调用方持有服务级互斥锁时执行一条改配。"""

        record = await self._store.get_record(record_id)
        if record is None:
            return RetargetResult(error_code="record_not_found", message="匹配记录不存在")
        target = await self._targets.get_target(target_history_id)
        if target is None:
            return RetargetResult(error_code="target_not_found", message="整理历史目标不存在")

        try:
            source = await self._record_source_path(record)
        except (OSError, ValueError) as exc:
            return RetargetResult(
                error_code="file_operation_failed",
                message=f"原字幕路径不可用：{exc}",
            )
        resolution = self._resolve_target(target)
        resolved_target = Path(resolution.resolved_path)
        destination = self._filesystem.media_subtitle_path(source, resolved_target)
        current_subtitle = Path(record.final_subtitle_path or record.path)
        if self._normalized_path(str(current_subtitle)) == self._normalized_path(str(destination)):
            return RetargetResult(error_code="same_target", message="预计最终字幕路径与当前路径相同")
        available, directory_error = await self._filesystem.target_directory_status(resolved_target)
        if not available:
            return RetargetResult(
                error_code="target_directory_unavailable",
                message=directory_error or "目标目录不可用",
            )
        async with self._inventory.reserve_for_retarget(record) as reservation:
            if not reservation.available:
                return RetargetResult(
                    error_code="record_state_changed",
                    message="暂存记录已被其他任务消费，请刷新后重试",
                )
            if not await self._filesystem.is_file(source):
                return RetargetResult(error_code="file_operation_failed", message="原字幕文件不存在")
            if await self._filesystem.is_file(destination):
                return RetargetResult(error_code="destination_conflict", message="预计最终字幕路径已存在")

            written: Path | None = None
            record_save_attempted = False
            try:
                written = await self._filesystem.write_media_subtitle(source, resolved_target)
                await self._filesystem.delete_subtitle_file(source)
                updated = await self._updated_record(
                    record,
                    target,
                    target_history_id,
                    resolution,
                    source,
                    written,
                )
                record_save_attempted = True
                await self._store.save_record(updated)
                reservation.commit()
            except BaseException as exc:
                rollback_errors: list[BaseException] = []
                try:
                    if written is not None and await self._filesystem.is_file(written):
                        if not await self._filesystem.is_file(source):
                            await self._filesystem.copy_file_exclusive(written, source)
                        await self._filesystem.delete_subtitle_file(written)
                except BaseException as rollback_exc:  # noqa: BLE001 - 取消期间的回滚失败也必须记录
                    rollback_errors.append(rollback_exc)
                if record_save_attempted:
                    try:
                        await self._store.save_record(record)
                    except BaseException as rollback_exc:  # noqa: BLE001 - 取消期间的回滚失败也必须记录
                        rollback_errors.append(rollback_exc)
                rollback_failed = bool(rollback_errors)
                if rollback_failed:
                    rollback_exc = rollback_errors[0]
                    stack = " | ".join(
                        f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                        for frame in traceback.extract_tb(rollback_exc.__traceback__, limit=8)
                    )
                    logger.error(
                        f"匹配记录 {record.id} 改配失败，且回滚未能完整恢复文件或记录状态，"
                        f"可能存在一致性风险：原字幕为“{source}”，新字幕为“{written}”，"
                        f"异常类型为 {type(rollback_exc).__name__}；插件调用栈：{stack}"
                    )
                else:
                    stack = " | ".join(
                        f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                        for frame in traceback.extract_tb(exc.__traceback__, limit=8)
                    )
                    logger.error(
                        f"匹配记录 {record.id} 改配失败，文件与记录状态已回滚："
                        f"原目标为“{record.target_path or '未记录'}”，"
                        f"新目标为“{resolution.resolved_path}”，异常类型为 {type(exc).__name__}；"
                        f"插件调用栈：{stack}"
                    )
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return RetargetResult(
                    error_code="file_operation_failed",
                    message="改配目标失败",
                    consistency_risk=rollback_failed,
                )
        logger.info(
            f"匹配记录 {record.id} 已改配成功："
            f"原目标为“{record.target_path or '未记录'}”，"
            f"新目标为“{resolution.resolved_path}”"
        )
        return RetargetResult(records=[updated])

    async def retarget(self, record_id: str, target_history_id: int) -> RetargetResult:
        """重新解析当前映射并把匹配记录改配到整理历史目标。"""

        async with self._lock, self._mutation_lock:
            result = await self._retarget_unlocked(record_id, target_history_id)
            await self._publish_subtitle_written_records(result.records)
            return result

    async def retarget_batch(self, mappings: list[RetargetMapping]) -> BatchRetargetResult:
        """整体预检后逐条独立执行一批匹配记录改配。"""

        self._validate_batch_mapping_count(mappings)
        async with self._lock, self._mutation_lock:
            preflight = await self._preview_batch_unlocked(mappings)
            if not preflight.executable:
                return BatchRetargetResult(preflight=preflight, items=[], started=False)
            items: list[BatchRetargetResultItem] = []
            for item in preflight.items:
                if item.target_history_id is None:
                    continue
                try:
                    result = await self._retarget_unlocked(item.record_id, item.target_history_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 单项失败不能中断批量改配
                    stack = " | ".join(
                        f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                        for frame in traceback.extract_tb(exc.__traceback__, limit=8)
                    )
                    logger.error(
                        f"批量改配记录 {item.record_id} 到整理历史 {item.target_history_id} 时发生异常，"
                        f"将继续处理后续记录：异常类型为 {type(exc).__name__}；插件调用栈：{stack}"
                    )
                    result = RetargetResult(
                        error_code="retarget_failed",
                        message="改配目标失败",
                    )
                await self._publish_subtitle_written_records(result.records)
                items.append(
                    BatchRetargetResultItem(
                        record_id=item.record_id,
                        target_history_id=item.target_history_id,
                        result=result,
                    )
                )
            batch = BatchRetargetResult(preflight=preflight, items=items, started=True)
        logger.info(
            f"批量改配已完成：共处理 {len(batch.items)} 条匹配记录，"
            f"成功 {batch.success_count} 条，失败 {batch.failure_count} 条"
        )
        return batch
