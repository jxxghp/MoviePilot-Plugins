"""匹配记录删除用例及可补偿事务边界。"""

from __future__ import annotations

import asyncio
import os
import traceback
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from anyio import Path as AsyncPath

from app.log import logger

from ..schemas.record import (
    BatchDeletePreflight,
    BatchDeletePreflightItem,
    BatchDeleteRecordConfirmation,
    BatchDeleteResult,
    BatchDeleteResultItem,
    BatchDeleteStatus,
    DeleteMode,
    DeleteRecordConfirmation,
    DeleteRecordResult,
    FileLocation,
    MatchRecord,
    RecordStatus,
)
from .lock import ReentrantAsyncLock

MIN_BATCH_DELETE_RECORDS = 1
MAX_BATCH_DELETE_RECORDS = 100


class RecordDeletionStorePort(Protocol):
    """删除用例使用的记录持久化能力。"""

    async def get_record(self, record_id: str) -> MatchRecord | None:
        """读取当前匹配记录快照。"""

    async def list_records(self) -> list[MatchRecord]:
        """读取全部当前匹配记录快照。"""

    async def delete_record_if_match(self, expected: MatchRecord) -> bool:
        """仅在记录版本未变化时原子删除，返回是否成功。"""

    async def save_record(self, record: MatchRecord) -> None:
        """恢复删除事务中被移除的记录。"""


class RecordDeletionFileSystemPort(Protocol):
    """删除用例使用的可回滚文件能力。"""

    async def plugin_file_path(self, relative_path: str) -> Path:
        """安全解析插件数据目录中的相对路径。"""

    async def stage_file_deletion(self, path: Path) -> Path | None:
        """把目标文件移到可回滚的临时备份。"""

    async def commit_file_deletion(self, backup: Path | None) -> None:
        """提交临时备份的删除。"""

    async def rollback_file_deletion(self, original: Path, backup: Path | None) -> None:
        """把临时备份恢复到原路径。"""


class RecordDeletionInventoryPort(Protocol):
    """删除用例使用的暂存库存索引能力。"""

    async def remove(self, record: MatchRecord) -> None:
        """从库存索引移除记录。"""

    async def restore(self, record: MatchRecord) -> None:
        """恢复库存索引中的记录。"""


@dataclass(slots=True)
class _FileMutation:
    """记录文件阶段是否发生了可回滚变更。"""

    path: Path
    backup: Path | None = None
    changed: bool = False


class RecordDeletionService:
    """执行带确认版本和补偿回滚的匹配记录删除。"""

    def __init__(
        self,
        store: RecordDeletionStorePort,
        filesystem: RecordDeletionFileSystemPort,
        inventory: RecordDeletionInventoryPort,
        mutation_lock: ReentrantAsyncLock | None = None,
    ) -> None:
        """绑定记录存储、文件系统和暂存库存。"""

        self._store = store
        self._filesystem = filesystem
        self._inventory = inventory
        self._lock = asyncio.Lock()
        self._mutation_lock = mutation_lock or ReentrantAsyncLock()

    @staticmethod
    def _same_datetime(left: datetime, right: datetime) -> bool:
        """按 UTC 瞬时点比较确认时间，兼容历史无时区值。"""

        def normalized(value: datetime) -> datetime:
            """把无时区或其他时区时间统一为 UTC。"""

            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)

        return normalized(left) == normalized(right)

    @staticmethod
    def _confirmation_matches(
        record: MatchRecord,
        confirmation: DeleteRecordConfirmation,
    ) -> bool:
        """判断当前记录是否仍等于用户确认时的版本。"""

        return (
            record.status is confirmation.expected_status
            and record.location is confirmation.expected_location
            and record.path == confirmation.expected_path
            and RecordDeletionService._same_datetime(
                record.updated_at,
                confirmation.expected_updated_at,
            )
        )

    @staticmethod
    def _version_conflict() -> DeleteRecordResult:
        """构造统一的确认版本冲突结果。"""

        return DeleteRecordResult(
            error_code="record_version_conflict",
            message="匹配记录已发生变化，请刷新后重新确认删除",
        )

    async def _record_file_path(self, record: MatchRecord) -> Path:
        """按服务端记录位置解析当前字幕文件，拒绝不安全媒体路径。"""

        if record.location is FileLocation.PLUGIN_DATA:
            return await self._filesystem.plugin_file_path(str(record.path))
        if record.location is FileLocation.MEDIA_DIRECTORY:
            path = Path(record.path)
            if not path.is_absolute():
                raise ValueError("媒体字幕路径必须是绝对路径")
            return path
        raise ValueError("匹配记录文件位置未知")

    async def _normalized_record_file_path(self, record: MatchRecord) -> str:
        """返回用于批量共享文件检测的物理规范绝对路径。"""

        path = await self._record_file_path(record)
        try:
            resolved = Path(await AsyncPath(path).resolve(strict=False))
        except (OSError, RuntimeError) as exc:
            raise ValueError("当前字幕文件路径不可解析") from exc
        return os.path.normcase(os.path.normpath(str(resolved)))

    async def _stage_file(self, record: MatchRecord) -> _FileMutation:
        """把记录当前文件移到可回滚备份。"""

        path = await self._record_file_path(record)
        backup = await self._filesystem.stage_file_deletion(path)
        return _FileMutation(path=path, backup=backup, changed=backup is not None)

    async def _commit_file(self, mutation: _FileMutation) -> None:
        """提交文件阶段并删除可回滚备份。"""

        await self._filesystem.commit_file_deletion(mutation.backup)

    async def _rollback_file(self, mutation: _FileMutation) -> None:
        """回滚文件阶段。"""

        if not mutation.changed:
            return
        await self._filesystem.rollback_file_deletion(mutation.path, mutation.backup)

    async def _restore_inventory(self, record: MatchRecord) -> None:
        """尽力恢复暂存库存索引。"""

        await self._inventory.restore(record)

    async def _restore_inventory_after_failure(
        self,
        snapshot: MatchRecord,
        *,
        version_conflict: bool,
    ) -> None:
        """按失败时的最新记录恢复库存，避免把过期快照重新索引。

        CAS 冲突说明记录可能已被其它写入者改动或删除。此时不能直接恢复
        删除前的旧快照；先读取当前记录，只有当前记录仍存在时才让库存按其
        最新状态重建。库存恢复本身是幂等的，已由其它事务恢复的记录不会
        重复产生索引项。
        """

        record = snapshot
        if version_conflict:
            current = await self._store.get_record(snapshot.id)
            if current is None:
                return
            record = current
        await self._restore_inventory(record)

    async def _delete_record_if_current(self, record: MatchRecord) -> None:
        """按确认快照删除记录，并把 CAS 失败转换为稳定内部信号。"""

        deleted = await self._store.delete_record_if_match(record)
        if deleted:
            return
        current = await self._store.get_record(record.id)
        if current is None or (
            current.status is not record.status
            or current.location is not record.location
            or current.path != record.path
            or not self._same_datetime(current.updated_at, record.updated_at)
        ):
            raise _RecordVersionConflict
        raise RuntimeError("记录删除未找到目标")

    async def _delete_metadata_only(self, record: MatchRecord) -> DeleteRecordResult:
        """删除仅匹配记录元数据，并在持久化失败时恢复原记录。"""

        snapshot = record.model_copy(deep=True)
        inventory_attempted = record.status is RecordStatus.STAGED
        try:
            if inventory_attempted:
                await self._inventory.remove(record)
            await self._delete_record_if_current(record)
        except BaseException as exc:
            rollback_errors: list[BaseException] = []
            if inventory_attempted:
                try:
                    await self._restore_inventory_after_failure(
                        snapshot,
                        version_conflict=isinstance(exc, _RecordVersionConflict),
                    )
                except BaseException as rollback_exc:  # noqa: BLE001 - 取消时也必须完成补偿
                    rollback_errors.append(rollback_exc)
            if not isinstance(exc, _RecordVersionConflict):
                try:
                    await self._store.save_record(snapshot)
                except BaseException as rollback_exc:  # noqa: BLE001 - 取消时也必须完成补偿
                    rollback_errors.append(rollback_exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, _RecordVersionConflict):
                if rollback_errors:
                    return self._failure_result(record, exc, rollback_errors)
                return self._version_conflict()
            return self._failure_result(record, exc, rollback_errors)
        return DeleteRecordResult(success=True)

    async def _delete_with_file(self, record: MatchRecord) -> DeleteRecordResult:
        """执行文件、库存和记录三阶段删除并在失败时补偿。"""

        snapshot = record.model_copy(deep=True)
        mutation: _FileMutation | None = None
        inventory_attempted = False
        store_delete_attempted = False
        try:
            mutation = await self._stage_file(record)
            inventory_attempted = True
            await self._inventory.remove(record)
            store_delete_attempted = True
            await self._delete_record_if_current(record)
            await self._commit_file(mutation)
        except BaseException as exc:
            rollback_errors: list[BaseException] = []
            if store_delete_attempted and not isinstance(exc, _RecordVersionConflict):
                try:
                    await self._store.save_record(snapshot)
                except BaseException as rollback_exc:  # noqa: BLE001 - 取消时也必须完成补偿
                    rollback_errors.append(rollback_exc)
            if inventory_attempted:
                try:
                    await self._restore_inventory_after_failure(
                        snapshot,
                        version_conflict=isinstance(exc, _RecordVersionConflict),
                    )
                except BaseException as rollback_exc:  # noqa: BLE001 - 取消时也必须完成补偿
                    rollback_errors.append(rollback_exc)
            if mutation is not None:
                try:
                    await self._rollback_file(mutation)
                except BaseException as rollback_exc:  # noqa: BLE001 - 取消时也必须完成补偿
                    rollback_errors.append(rollback_exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, _RecordVersionConflict) and not rollback_errors:
                return self._version_conflict()
            return self._failure_result(record, exc, rollback_errors)
        return DeleteRecordResult(success=True)

    @staticmethod
    def _failure_result(
        record: MatchRecord,
        error: BaseException,
        rollback_errors: list[BaseException],
    ) -> DeleteRecordResult:
        """记录删除失败及回滚风险，并转换为稳定领域错误。"""

        consistency_risk = bool(rollback_errors)
        if consistency_risk:
            first = rollback_errors[0]
            stack = " | ".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(first.__traceback__, limit=8)
            )
            logger.error(
                f"匹配记录 {record.id} 删除失败且补偿未完整完成，可能存在一致性风险；"
                f"异常类型为 {type(first).__name__}；插件调用栈：{stack}"
            )
            return DeleteRecordResult(
                error_code="record_delete_consistency_risk",
                message="匹配记录删除失败，文件与记录可能存在不一致，请检查后重试",
                consistency_risk=True,
            )
        logger.error(f"匹配记录 {record.id} 删除失败，文件、库存与记录已回滚；异常类型为 {type(error).__name__}")
        return DeleteRecordResult(
            error_code="record_delete_failed",
            message="匹配记录删除失败，未改变原记录与字幕文件",
        )

    @staticmethod
    def _delete_mode_error(
        record: MatchRecord,
        delete_mode: DeleteMode,
    ) -> DeleteRecordResult | None:
        """校验记录状态是否允许采用指定删除模式。"""

        if record.status not in {
            RecordStatus.MATCHED,
            RecordStatus.STAGED,
            RecordStatus.UNMATCHED,
        }:
            return DeleteRecordResult(
                error_code="delete_mode_not_allowed",
                message="当前记录状态不能删除",
            )
        if delete_mode not in {DeleteMode.RECORD_ONLY, DeleteMode.RECORD_AND_FILE}:
            return DeleteRecordResult(
                error_code="delete_mode_not_allowed",
                message="删除模式不受支持",
            )
        if delete_mode is DeleteMode.RECORD_ONLY and record.status is not RecordStatus.MATCHED:
            return DeleteRecordResult(
                error_code="delete_mode_not_allowed",
                message="暂存和未匹配记录必须同时删除当前字幕文件",
            )
        return None

    async def _delete_current_unlocked(
        self,
        record: MatchRecord,
        delete_mode: DeleteMode,
    ) -> DeleteRecordResult:
        """在调用方持有删除互斥边界时执行一条记录。"""

        mode_error = self._delete_mode_error(record, delete_mode)
        if mode_error is not None:
            return mode_error
        if delete_mode is DeleteMode.RECORD_ONLY:
            return await self._delete_metadata_only(record)
        return await self._delete_with_file(record)

    async def _preflight_batch_unlocked(
        self,
        items: list[BatchDeleteRecordConfirmation],
        delete_mode: DeleteMode,
    ) -> BatchDeletePreflight:
        """在共享变更锁内校验整批确认版本和共享文件路径。"""

        duplicate_ids = {
            record_id for record_id, count in Counter(item.record_id for item in items).items() if count > 1
        }
        preflight_items: list[BatchDeletePreflightItem] = []
        for item in items:
            if item.record_id in duplicate_ids:
                preflight_items.append(
                    BatchDeletePreflightItem(
                        record_id=item.record_id,
                        error_code="duplicate_record",
                        message="同一匹配记录不能在批次中重复出现",
                    )
                )
                continue
            record = await self._store.get_record(item.record_id)
            if record is None:
                preflight_items.append(
                    BatchDeletePreflightItem(
                        record_id=item.record_id,
                        error_code="record_not_found",
                        message="匹配记录不存在",
                    )
                )
                continue
            if not self._confirmation_matches(record, item.confirmation):
                conflict = self._version_conflict()
                preflight_items.append(
                    BatchDeletePreflightItem(
                        record_id=item.record_id,
                        record=record,
                        error_code=conflict.error_code,
                        message=conflict.message,
                    )
                )
                continue
            mode_error = self._delete_mode_error(record, delete_mode)
            preflight_items.append(
                BatchDeletePreflightItem(
                    record_id=item.record_id,
                    record=record,
                    error_code=mode_error.error_code if mode_error is not None else None,
                    message=mode_error.message if mode_error is not None else None,
                )
            )

        if delete_mode is not DeleteMode.RECORD_AND_FILE:
            return BatchDeletePreflight(items=preflight_items)

        selected_paths: dict[str, str] = {}
        for index, item in enumerate(preflight_items):
            if not item.executable or item.record is None:
                continue
            try:
                selected_paths[item.record_id] = await self._normalized_record_file_path(item.record)
            except (OSError, ValueError) as exc:
                preflight_items[index] = replace(
                    item,
                    error_code="record_file_path_invalid",
                    message=f"当前字幕文件路径不可用：{exc}",
                )

        path_owners: dict[str, set[str]] = {}
        selected_records = {item.record_id: item.record for item in preflight_items if item.record is not None}
        all_records = await self._store.list_records()
        records_by_id = {record.id: record for record in all_records}
        records_by_id.update(selected_records)
        for record in records_by_id.values():
            try:
                path = await self._normalized_record_file_path(record)
            except (OSError, ValueError):
                continue
            path_owners.setdefault(path, set()).add(record.id)

        for index, item in enumerate(preflight_items):
            path = selected_paths.get(item.record_id)
            if path is None or not item.executable:
                continue
            other_record_ids = path_owners.get(path, set()) - {item.record_id}
            if other_record_ids:
                preflight_items[index] = replace(
                    item,
                    error_code="shared_record_file",
                    message="当前字幕文件被其他匹配记录引用，不能安全删除",
                )
        return BatchDeletePreflight(items=preflight_items)

    async def delete(
        self,
        record_id: str,
        confirmation: DeleteRecordConfirmation,
    ) -> DeleteRecordResult:
        """按确认版本删除一条匹配记录。"""

        async with self._lock, self._mutation_lock:
            record = await self._store.get_record(record_id)
            if record is None:
                return DeleteRecordResult(
                    error_code="record_not_found",
                    message="匹配记录不存在",
                )
            if not self._confirmation_matches(record, confirmation):
                return self._version_conflict()
            return await self._delete_current_unlocked(record, confirmation.delete_mode)

    async def delete_batch(
        self,
        items: list[BatchDeleteRecordConfirmation],
        delete_mode: DeleteMode,
    ) -> BatchDeleteResult:
        """整批预检确认版本后按请求顺序逐条删除匹配记录。"""

        item_count = len(items)
        if not MIN_BATCH_DELETE_RECORDS <= item_count <= MAX_BATCH_DELETE_RECORDS:
            raise ValueError(f"批量删除记录数量必须在 {MIN_BATCH_DELETE_RECORDS} 至 {MAX_BATCH_DELETE_RECORDS} 条之间")
        async with self._lock, self._mutation_lock:
            preflight = await self._preflight_batch_unlocked(items, delete_mode)
            if not preflight.executable:
                return BatchDeleteResult(
                    preflight=preflight,
                    items=[],
                    started=False,
                )

            result_items: list[BatchDeleteResultItem] = []
            for index, item in enumerate(preflight.items):
                if item.record is None:
                    continue
                result = await self._delete_current_unlocked(item.record, delete_mode)
                if result.success:
                    result_items.append(
                        BatchDeleteResultItem(
                            record_id=item.record_id,
                            status=BatchDeleteStatus.SUCCESS,
                        )
                    )
                    continue
                result_items.append(
                    BatchDeleteResultItem(
                        record_id=item.record_id,
                        status=BatchDeleteStatus.FAILED,
                        error_code=result.error_code,
                        message=result.message,
                        consistency_risk=result.consistency_risk,
                    )
                )
                if not result.consistency_risk:
                    continue
                result_items.extend(
                    BatchDeleteResultItem(
                        record_id=remaining.record_id,
                        status=BatchDeleteStatus.NOT_EXECUTED,
                        error_code="batch_delete_not_executed",
                        message="批量删除因一致性风险中止，请刷新后重新选择",
                    )
                    for remaining in preflight.items[index + 1 :]
                )
                break

            batch = BatchDeleteResult(
                preflight=preflight,
                items=result_items,
                started=True,
            )
        logger.info(
            f"批量删除已完成：共处理 {len(batch.items)} 条匹配记录，"
            f"成功 {batch.success_count} 条，失败 {batch.failure_count} 条，"
            f"未执行 {batch.not_executed_count} 条"
        )
        return batch


class _RecordVersionConflict(RuntimeError):
    """存储层 CAS 发现确认快照已过期。"""
