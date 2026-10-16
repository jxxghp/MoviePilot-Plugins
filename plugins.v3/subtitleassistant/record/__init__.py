"""匹配记录、字幕库存与记录维护能力的唯一业务接口。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.log import logger

from ..schemas.event import SubtitleWrittenEvent
from ..schemas.record import (
    BatchDeleteRecordConfirmation,
    BatchDeleteResult,
    BatchRetargetPreview,
    BatchRetargetResult,
    CommittedFileFact,
    DeleteMode,
    DeleteRecordConfirmation,
    DeleteRecordResult,
    InventoryConsumeResult,
    MatchRecord,
    RecordStatus,
    RetargetMapping,
    RetargetResult,
)
from ..schemas.target import PathMappingSnapshot, SubtitleTarget
from ..target import TargetCatalog
from .lock import ReentrantAsyncLock


class SubtitleEventPublisher(Protocol):
    """记录维护能力使用的字幕落盘事件端口。"""

    async def publish(self, event: SubtitleWrittenEvent) -> None:
        """尽力广播一条已提交的字幕落盘事实。"""


class RecordStorePort(Protocol):
    """记录能力所需的持久化操作。"""

    async def list_records(self) -> list[MatchRecord]:
        """读取全部记录快照。"""

    async def get_record(self, record_id: str) -> MatchRecord | None:
        """读取单条记录快照。"""

    async def save_record(self, record: MatchRecord) -> None:
        """保存记录快照。"""

    async def delete_record(self, record_id: str) -> bool:
        """删除记录。"""

    async def delete_record_if_match(self, expected: MatchRecord) -> bool:
        """按确认快照删除记录。"""


class RecordFilePort(Protocol):
    """记录能力所需的字幕文件操作。"""

    async def write_media_subtitle(self, source: Path, target: Path) -> Path:
        """排他写入媒体字幕。"""

    async def save_plugin_file(self, source: Path, record_id: str, status: RecordStatus) -> str:
        """保存插件数据字幕。"""

    async def delete_subtitle_file(self, path: Path) -> None:
        """删除媒体字幕。"""

    async def delete_plugin_file(self, relative_path: str) -> None:
        """删除插件数据字幕。"""

    async def plugin_file_path(self, relative_path: str) -> Path:
        """解析插件数据字幕路径。"""

    async def stage_file_deletion(self, path: Path) -> Path | None:
        """暂存文件删除。"""

    async def commit_file_deletion(self, backup: Path | None) -> None:
        """提交已暂存文件删除。"""

    async def rollback_file_deletion(self, original: Path, backup: Path | None) -> None:
        """回滚已暂存文件删除。"""

    def media_subtitle_path(self, source: Path, target: Path) -> Path:
        """计算媒体字幕目标路径。"""

    async def is_file(self, path: Path) -> bool:
        """检查目标是否为普通文件。"""

    async def target_directory_status(self, target: Path) -> tuple[bool, str | None]:
        """检查目标目录是否可用。"""

    async def copy_file_exclusive(self, source: Path, target: Path) -> int:
        """排他复制字幕文件。"""


class _RecordDeletion(Protocol):
    """记录查询 facade 代理的内部删除操作。"""

    async def delete(
        self,
        record_id: str,
        confirmation: DeleteRecordConfirmation,
    ) -> DeleteRecordResult:
        """按确认版本删除一条记录。"""

    async def delete_batch(
        self,
        items: list[BatchDeleteRecordConfirmation],
        delete_mode: DeleteMode,
    ) -> BatchDeleteResult:
        """预检并执行批量删除。"""


class _RecordRetargeting(Protocol):
    """记录维护 facade 代理的内部改配操作。"""

    async def preview(self, record_id: str, target_history_id: int) -> RetargetResult:
        """预览一条记录的改配目标。"""

    async def preview_batch(self, mappings: list[RetargetMapping]) -> BatchRetargetPreview:
        """预检一批改配映射。"""

    async def retarget(self, record_id: str, target_history_id: int) -> RetargetResult:
        """原地改配一条记录。"""

    async def retarget_batch(self, mappings: list[RetargetMapping]) -> BatchRetargetResult:
        """执行一批改配映射。"""


class RecordCommitter:
    """统一提交匹配记录、字幕库存和文件一致性结果。"""

    def __init__(
        self,
        store: RecordStorePort,
        filesystem: RecordFilePort,
        records: list[MatchRecord],
        format_priority: list[str],
        source_priority: list[str],
    ) -> None:
        """创建共享库存与记录提交协调器。"""

        from .inventory import SubtitleInventory

        self._store = store
        self._mutation_lock = ReentrantAsyncLock()
        self._filesystem = filesystem
        self._inventory = SubtitleInventory(
            store=store,
            filesystem=filesystem,
            records=records,
            format_priority=format_priority,
            source_priority=source_priority,
            mutation_lock=self._mutation_lock,
        )

    async def add(self, record: MatchRecord) -> None:
        """把暂存记录加入库存索引。"""

        await self._inventory.add(record)

    async def publish(self, record: MatchRecord) -> None:
        """持久化记录并在适用时更新字幕库存。"""

        await self._inventory.publish(record)

    async def commit_media(
        self,
        record: MatchRecord,
        source: Path,
        target: Path,
    ) -> CommittedFileFact:
        """提交媒体字幕与匹配记录，并返回逐文件已提交事实。"""

        destination: Path | None = None
        try:
            destination = await self._filesystem.write_media_subtitle(source, target)
            record.path = destination
            record.final_subtitle_path = destination
            await self._inventory.publish(record)
        except BaseException:
            if destination is not None:
                try:
                    await self._filesystem.delete_subtitle_file(destination)
                except BaseException as rollback_exc:  # noqa: BLE001 - 回滚失败必须保留审计
                    logger.error(
                        f"媒体目录字幕写入后记录提交失败，补偿删除失败；异常类型为 {type(rollback_exc).__name__}"
                    )
            raise
        return CommittedFileFact(record=record, target_path=Path(target), subtitle_path=destination)

    async def commit_plugin(self, record: MatchRecord, source: Path) -> MatchRecord:
        """提交插件数据字幕与匹配记录，并在失败时清理残留。"""

        try:
            record.path = Path(await self._filesystem.save_plugin_file(source, record.id, record.status))
            await self._inventory.publish(record)
        except BaseException:
            try:
                await self._store.delete_record(record.id)
            except BaseException as cleanup_exc:  # noqa: BLE001 - 清理失败必须保留审计
                logger.error(f"插件字幕记录提交失败且记录清理失败；异常类型为 {type(cleanup_exc).__name__}")
            if record.path:
                try:
                    await self._filesystem.delete_plugin_file(str(record.path))
                except BaseException as cleanup_exc:  # noqa: BLE001 - 清理失败必须保留审计
                    logger.error(f"插件字幕记录提交失败且文件清理失败；异常类型为 {type(cleanup_exc).__name__}")
            raise
        return record

    async def consume(
        self,
        context: SubtitleTarget,
        task_id: str,
        target_history_id: int | None = None,
        history_target_path: Path | str | None = None,
        matched_path_mapping: PathMappingSnapshot | None = None,
        target_file_exists: bool | None = None,
    ) -> InventoryConsumeResult:
        """消费精确命中的暂存字幕并更新匹配记录。"""

        result = await self._inventory.consume(
            context,
            task_id,
            target_history_id=target_history_id,
            history_target_path=history_target_path,
            matched_path_mapping=matched_path_mapping,
            target_file_exists=target_file_exists,
        )
        return result

    def catalog(self) -> RecordCatalog:
        """创建复用当前提交边界的记录查询 facade。"""

        from .deletion import RecordDeletionService

        return RecordCatalog(
            self._store,
            RecordDeletionService(
                store=self._store,
                filesystem=self._filesystem,
                inventory=self._inventory,
                mutation_lock=self._mutation_lock,
            ),
        )

    def maintenance(
        self,
        targets: TargetCatalog,
        publisher: SubtitleEventPublisher | None = None,
    ) -> RecordMaintenance:
        """创建复用当前提交边界的记录维护 facade。"""

        from .retarget import RetargetService

        return RecordMaintenance(
            RetargetService(
                store=self._store,
                filesystem=self._filesystem,
                inventory=self._inventory,
                targets=targets,
                mutation_lock=self._mutation_lock,
                publisher=publisher,
            )
        )


class RecordCatalog:
    """提供匹配记录查询、删除预检与批量维护。"""

    def __init__(
        self,
        store: RecordStorePort,
        deletion: _RecordDeletion,
    ) -> None:
        """创建记录查询与删除 facade。"""

        self._store = store
        self._deletion = deletion

    async def list_records(self) -> list[MatchRecord]:
        """读取全部匹配记录快照。"""

        return await self._store.list_records()

    async def get(self, record_id: str) -> MatchRecord | None:
        """按标识读取匹配记录快照。"""

        return await self._store.get_record(record_id)

    async def delete(
        self,
        record_id: str,
        confirmation: DeleteRecordConfirmation,
    ) -> DeleteRecordResult:
        """按确认版本删除一条匹配记录。"""

        return await self._deletion.delete(record_id, confirmation)

    async def delete_batch(
        self,
        items: list[BatchDeleteRecordConfirmation],
        delete_mode: DeleteMode,
    ) -> BatchDeleteResult:
        """预检并独立执行一批匹配记录删除。"""

        return await self._deletion.delete_batch(items, delete_mode)


class RecordMaintenance:
    """提供匹配记录改配预览、执行与批量维护。"""

    def __init__(
        self,
        service: _RecordRetargeting,
    ) -> None:
        """创建记录改配 facade，并复用提交器的 mutation lock。"""

        self._service = service

    async def preview(self, record_id: str, target_history_id: int) -> RetargetResult:
        """预览一条记录的改配目标。"""

        return await self._service.preview(record_id, target_history_id)

    async def preview_batch(self, mappings: list[RetargetMapping]) -> BatchRetargetPreview:
        """预检一批记录到目标的一对一映射。"""

        return await self._service.preview_batch(mappings)

    async def retarget(self, record_id: str, target_history_id: int) -> RetargetResult:
        """原地改配一条匹配记录。"""

        return await self._service.retarget(record_id, target_history_id)

    async def retarget_batch(self, mappings: list[RetargetMapping]) -> BatchRetargetResult:
        """按独立映射执行一批记录改配。"""

        return await self._service.retarget_batch(mappings)


__all__ = ["RecordCatalog", "RecordCommitter", "RecordMaintenance"]
