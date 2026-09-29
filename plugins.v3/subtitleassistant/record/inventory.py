"""暂存字幕库存索引与消费用例。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.log import logger

from ..candidate import candidate_from_record, candidate_rank
from ..schemas.base import utc_now
from ..schemas.record import FileLocation, InventoryConsumeResult, MatchRecord, RecordStatus
from ..schemas.target import PathMappingSnapshot, SubtitleTarget
from .lock import ReentrantAsyncLock


class InventoryStorePort(Protocol):
    """库存维护所需的匹配记录持久化能力。"""

    async def get_record(self, record_id: str) -> MatchRecord | None:
        """读取匹配记录快照。"""

    async def save_record(self, record: MatchRecord) -> None:
        """保存匹配记录快照。"""

    async def delete_record(self, record_id: str) -> bool:
        """删除匹配记录。"""


class InventoryFileSystemPort(Protocol):
    """库存维护所需的字幕文件能力。"""

    async def plugin_file_path(self, relative_path: str) -> Path:
        """解析插件数据目录中的相对路径。"""

    async def write_media_subtitle(self, source: Path, target: Path) -> Path:
        """把字幕写入媒体目录。"""

    async def delete_subtitle_file(self, path: Path) -> None:
        """删除媒体目录字幕。"""

    async def delete_plugin_file(self, relative_path: str) -> None:
        """删除插件数据目录中的字幕。"""


@dataclass(slots=True)
class InventoryRetargetReservation:
    """一次暂存记录改配期间持有的库存保留凭据。"""

    available: bool
    _committed: bool = False

    def commit(self) -> None:
        """标记改配已成功，退出保留区时从库存移除原记录。"""

        if not self.available:
            raise RuntimeError("不可用的暂存记录不能提交改配")
        self._committed = True


class SubtitleInventory:
    """从暂存记录重建并维护的内存库存索引。"""

    def __init__(
        self,
        store: InventoryStorePort,
        filesystem: InventoryFileSystemPort,
        records: list[MatchRecord],
        format_priority: list[str],
        source_priority: list[str],
        mutation_lock: ReentrantAsyncLock | None = None,
    ) -> None:
        """使用持久暂存记录初始化库存。"""

        self._store = store
        self._filesystem = filesystem
        self._format_priority = format_priority
        self._source_priority = source_priority
        self._records: dict[str, MatchRecord] = {}
        self._index: dict[tuple[str, str, str, int, int], set[str]] = {}
        self._lock = asyncio.Lock()
        self._mutation_lock = mutation_lock or ReentrantAsyncLock()
        for record in records:
            self._add_to_index(record)

    def _add_to_index(self, record: MatchRecord) -> None:
        """把合格暂存记录加入索引。"""

        if record.status is not RecordStatus.STAGED or record.inventory_key is None:
            return
        self._records[record.id] = record.model_copy(deep=True)
        self._index.setdefault(record.inventory_key, set()).add(record.id)

    def _remove_from_index(self, record: MatchRecord) -> None:
        """从索引移除记录。"""

        key = record.inventory_key
        self._records.pop(record.id, None)
        if key is None:
            return
        record_ids = self._index.get(key)
        if record_ids is None:
            return
        record_ids.discard(record.id)
        if not record_ids:
            self._index.pop(key, None)

    @staticmethod
    def key_for_context(context: SubtitleTarget) -> tuple[str, str, str, int, int] | None:
        """为媒体上下文构建精确库存键。"""

        identity = context.canonical_identity
        if identity is None or context.season is None or context.episode is None:
            return None
        identity_type, identity_value = identity
        return context.media_type.value, identity_type, identity_value, context.season, context.episode

    async def add(self, record: MatchRecord) -> None:
        """把新暂存记录加入内存索引。"""

        async with self._mutation_lock, self._lock:
            self._add_to_index(record)

    async def publish(self, record: MatchRecord) -> None:
        """在共同 mutation 边界内发布最终记录并同步暂存索引。

        插件数据文件保存完成前不应让记录对删除接口可见；最终记录发布与
        暂存索引加入也必须是同一临界区，避免删除刚完成后又出现幽灵库存项。
        """

        async with self._mutation_lock:
            try:
                await self._store.save_record(record)
                async with self._lock:
                    self._add_to_index(record)
            except BaseException:
                async with self._lock:
                    self._remove_from_index(record)
                try:
                    await self._store.delete_record(record.id)
                except BaseException as rollback_exc:  # noqa: BLE001 - 取消期间的回滚失败也必须记录
                    logger.error(
                        f"匹配记录 {record.id} 发布失败，且未能确认清除部分持久化结果；"
                        f"异常类型为 {type(rollback_exc).__name__}"
                    )
                raise

    async def remove(self, record: MatchRecord) -> None:
        """把被删除或已消费记录移出内存索引。"""

        async with self._mutation_lock:
            await self.remove_unlocked(record)

    async def restore(self, record: MatchRecord) -> None:
        """恢复一次删除事务中被移除的暂存记录索引。"""

        async with self._mutation_lock:
            await self.restore_unlocked(record)

    async def remove_unlocked(self, record: MatchRecord) -> None:
        """在调用方已持有记录 mutation 锁时移除索引。"""

        async with self._lock:
            self._remove_from_index(record)

    async def restore_unlocked(self, record: MatchRecord) -> None:
        """在调用方已持有记录 mutation 锁时恢复索引。"""

        async with self._lock:
            self._add_to_index(record)

    @asynccontextmanager
    async def reserve_for_retarget(
        self,
        record: MatchRecord,
    ) -> AsyncIterator[InventoryRetargetReservation]:
        """在改配文件与记录事务期间阻止同一暂存字幕被库存消费。"""

        # 即使是已匹配记录也必须进入共同 mutation 边界，避免删除在改配读取
        # 快照后抢先移除文件，随后改配又把旧字幕写回目标目录。
        async with self._mutation_lock, self._lock:
            current = await self._store.get_record(record.id)
            indexed = self._records.get(record.id)
            available = current is not None and current == record
            if record.status is RecordStatus.STAGED and record.inventory_key is not None:
                available = available and indexed is not None and indexed == record
            reservation = InventoryRetargetReservation(available=available)
            try:
                yield reservation
            finally:
                if reservation._committed and indexed is not None:
                    self._remove_from_index(indexed)

    async def consume(
        self,
        context: SubtitleTarget,
        task_id: str,
        target_history_id: int | None = None,
        history_target_path: Path | str | None = None,
        matched_path_mapping: PathMappingSnapshot | None = None,
        target_file_exists: bool | None = None,
    ) -> InventoryConsumeResult:
        """精确命中并消费当前媒体所有可提交的暂存字幕文件。"""

        key = self.key_for_context(context)
        if key is None:
            return InventoryConsumeResult()
        async with self._mutation_lock, self._lock:
            record_ids = self._index.get(key, set()).copy()
            records = [self._records[item].model_copy(deep=True) for item in record_ids if item in self._records]
            if not records:
                return InventoryConsumeResult()
            normalized_history_target_path = Path(history_target_path) if history_target_path is not None else None
            ranked = sorted(
                records,
                key=lambda record: (
                    candidate_rank(
                        candidate_from_record(record),
                        self._format_priority,
                        self._source_priority,
                        include_format=True,
                    ),
                    record.id,
                ),
            )
            consumed: list[MatchRecord] = []
            warnings: list[str] = []
            for selected in ranked:
                original = selected.model_copy(deep=True)
                destination: Path | None = None
                try:
                    source = await self._filesystem.plugin_file_path(str(selected.path))
                    destination = await self._filesystem.write_media_subtitle(
                        source,
                        Path(context.target_path),
                    )
                    now = utc_now()
                    selected.status = RecordStatus.MATCHED
                    selected.location = FileLocation.MEDIA_DIRECTORY
                    selected.path = Path(destination)
                    selected.target_history_id = target_history_id
                    selected.history_target_path = normalized_history_target_path
                    selected.target_path = context.target_path
                    selected.matched_path_mapping = matched_path_mapping
                    selected.target_file_exists = target_file_exists
                    selected.final_subtitle_path = Path(destination)
                    selected.consumed_task_id = task_id
                    selected.consumed_at = now
                    selected.updated_at = now
                    await self._store.save_record(selected)
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:
                    rollback_errors: list[BaseException] = []
                    try:
                        await self._store.save_record(original)
                    except BaseException as rollback_exc:  # noqa: BLE001 - 取消期间的回滚失败也必须记录
                        rollback_errors.append(rollback_exc)
                    if destination is not None:
                        try:
                            await self._filesystem.delete_subtitle_file(destination)
                        except BaseException as rollback_exc:  # noqa: BLE001 - 取消期间的回滚失败也必须记录
                            rollback_errors.append(rollback_exc)
                    if rollback_errors:
                        logger.error(
                            f"暂存记录 {selected.id} 消费失败且补偿未完整完成，"
                            f"可能存在一致性风险；异常类型为 {type(rollback_errors[0]).__name__}"
                        )
                    if len(ranked) == 1:
                        raise
                    warnings.append(f"暂存记录 {selected.id} 消费失败：{type(exc).__name__}")
                    continue

                # 持久记录已经转为已匹配后再发布索引变化；两步之间没有 await，
                # 其他 mutation 无法观察到“已匹配记录仍在库存”的中间状态。
                self._remove_from_index(original)
                try:
                    await self._filesystem.delete_plugin_file(str(original.path))
                except OSError:
                    warnings.append(f"暂存记录 {selected.id} 的源文件清理失败")
                consumed.append(selected)

            return InventoryConsumeResult(
                matched=bool(consumed),
                records=consumed,
                warning="；".join(warnings) or None,
            )
