"""字幕文件与插件数据目录异步操作。"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from pathlib import Path

from anyio import Path as AsyncPath
from anyio import to_thread

from ..schemas.record import RecordStatus


class SubtitleFiles:
    """使用 anyio.Path 执行字幕文件检查、排他落盘和数据清理。"""

    def __init__(self, data_root: Path, allowed_formats: Iterable[str]) -> None:
        """创建绑定到插件数据目录的文件服务。"""

        self.data_root = Path(data_root)
        self.allowed_formats = {str(item).strip().lstrip(".").lower() for item in allowed_formats if str(item).strip()}

    @staticmethod
    async def _has_symlink_component(path: Path) -> bool:
        """检查路径自身及其父级是否包含符号链接。"""

        absolute = Path(os.path.abspath(path))
        anchor = absolute.anchor
        current = AsyncPath(anchor or Path.cwd())
        parts = absolute.parts[1:] if anchor else absolute.parts
        for part in parts:
            current = current / part
            if await current.is_symlink():
                return True
        return False

    def _media_subtitle_names(self, target: Path) -> set[str]:
        """返回目标视频对应的两个标准简中字幕文件名后缀。"""

        return {
            f"{target.stem}{suffix}.{extension}"
            for suffix in (".chi.zh-cn", ".default.chi.zh-cn")
            for extension in self.allowed_formats
        }

    async def has_standard_subtitle(self, target: Path) -> Path | None:
        """查找严格同主文件名的标准简中外挂字幕。"""

        parent = AsyncPath(target.parent)
        if not await parent.exists():
            return None
        expected = {item.casefold() for item in self._media_subtitle_names(target)}
        async for child in parent.iterdir():
            if await child.is_file() and child.name.casefold() in expected:
                return Path(child)
        return None

    async def _copy_exclusive(
        self,
        source: Path,
        target: Path,
        *,
        create_parent: bool = False,
    ) -> int:
        """以排他模式复制文件并返回字节数。"""

        source_async = AsyncPath(source)
        target_async = AsyncPath(target)
        if create_parent:
            await target_async.parent.mkdir(parents=True, exist_ok=True)
        elif not await target_async.parent.is_dir():
            raise FileNotFoundError(f"字幕目标目录不存在：{target.parent}")
        total = 0
        created = False
        try:
            async with await source_async.open("rb") as source_file:
                target_file = await target_async.open("xb")
                created = True
                async with target_file:
                    while True:
                        chunk = await source_file.read(1024 * 1024)
                        if not chunk:
                            break
                        await target_file.write(chunk)
                        total += len(chunk)
        except BaseException:
            if created and await target_async.exists():
                await target_async.unlink()
            raise
        return total

    def media_subtitle_path(self, source: Path, target: Path) -> Path:
        """返回字幕按宿主标准命名规则落盘后的预计路径。"""

        extension = source.suffix.lower().lstrip(".")
        if extension not in self.allowed_formats:
            raise ValueError(f"字幕格式不在宿主允许集合中：{extension}")
        return target.with_name(f"{target.stem}.chi.zh-cn.{extension}")

    async def is_file(self, path: Path) -> bool:
        """判断路径当前是否为普通文件。"""

        return await AsyncPath(path).is_file()

    async def copy_file_exclusive(self, source: Path, target: Path) -> int:
        """以排他方式复制字幕文件到精确目标路径。"""

        return await self._copy_exclusive(source, target)

    async def target_directory_status(self, target: Path) -> tuple[bool, str | None]:
        """检查目标文件父目录是否存在、为目录且当前可写。"""

        parent = AsyncPath(target.parent)
        if not await parent.exists():
            return False, "目标目录不存在"
        if not await parent.is_dir():
            return False, "目标父路径不是目录"
        writable = await to_thread.run_sync(os.access, target.parent, os.W_OK)
        if not writable:
            return False, "目标目录不可写"
        return True, None

    async def delete_subtitle_file(self, path: Path) -> None:
        """删除一个精确字幕文件，目标不存在视为成功。"""

        target = AsyncPath(path)
        if not await target.exists():
            return
        if not await target.is_file():
            raise IsADirectoryError(str(path))
        await target.unlink()

    async def stage_file_deletion(self, path: Path) -> Path | None:
        """把待删除的普通文件原子移到同目录备份并返回备份路径。

        删除记录涉及多项持久化操作时，先把文件移到同目录临时名称，后续
        任一步失败即可通过 :meth:`rollback_file_deletion` 恢复。目标不存在
        按幂等成功处理；目录、符号链接和其他非普通文件拒绝参与事务。
        """

        if await self._has_symlink_component(path):
            raise ValueError(f"字幕路径不能包含符号链接：{path}")
        target = AsyncPath(path)
        if await target.is_symlink():
            raise IsADirectoryError(str(path))
        if not await target.exists():
            return None
        if not await target.is_file():
            raise IsADirectoryError(str(path))
        for _ in range(8):
            backup = target.with_name(f".{target.name}.subtitleassistant-delete-{uuid.uuid4().hex}")
            if await backup.exists():
                continue
            try:
                await target.rename(backup)
                return Path(backup)
            except FileExistsError:
                continue
        raise FileExistsError(f"无法创建字幕删除临时备份：{path}")

    async def commit_file_deletion(self, backup: Path | None) -> None:
        """提交文件删除并清理临时备份，备份不存在视为已完成。"""

        if backup is None:
            return
        target = AsyncPath(backup)
        if await target.is_symlink():
            raise IsADirectoryError(str(backup))
        if not await target.exists():
            return
        if not await target.is_file():
            raise IsADirectoryError(str(backup))
        await target.unlink()

    async def rollback_file_deletion(self, original: Path, backup: Path | None) -> None:
        """将文件删除事务回滚到原路径，目标被外部占用时拒绝覆盖。"""

        if backup is None:
            return
        source = AsyncPath(backup)
        if await source.is_symlink():
            raise IsADirectoryError(str(backup))
        if not await source.exists():
            raise FileNotFoundError(f"字幕删除备份不存在：{backup}")
        target = AsyncPath(original)
        if await target.is_symlink():
            raise FileExistsError(f"字幕原路径已被符号链接占用，无法回滚：{original}")
        if await target.exists():
            raise FileExistsError(f"字幕原路径已被占用，无法回滚：{original}")
        await source.rename(target)

    async def write_media_subtitle(self, source: Path, target: Path) -> Path:
        """按宿主语言后缀规则以排他方式落盘字幕。"""

        destination = self.media_subtitle_path(source, target)
        await self.copy_file_exclusive(source, destination)
        return destination

    async def save_plugin_file(self, source: Path, record_id: str, status: RecordStatus) -> str:
        """把暂存或未匹配文件保存到插件数据目录。"""

        if status not in {RecordStatus.STAGED, RecordStatus.UNMATCHED}:
            raise ValueError("只有暂存或未匹配记录可以保存插件文件")
        bucket = status.value
        extension = source.suffix.lower() or ".subtitle"
        relative = Path(bucket) / f"{record_id}{extension}"
        destination = await self.plugin_file_path(relative.as_posix())
        await self._copy_exclusive(source, destination, create_parent=True)
        return relative.as_posix()

    async def plugin_file_path(self, relative_path: str) -> Path:
        """安全解析插件数据目录内的相对文件路径。"""

        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("插件数据文件路径非法")
        # 允许插件数据根目录自身是宿主配置的符号链接，但从根目录往下
        # 的任何组件都必须是普通路径；否则记录路径可能借由链接逃逸到
        # 插件数据目录之外。
        try:
            root = Path(await AsyncPath(self.data_root).resolve(strict=False))
        except (OSError, RuntimeError) as exc:
            raise ValueError("插件数据目录路径不可解析") from exc
        result = Path(os.path.abspath(root / candidate))
        if os.path.commonpath((str(root), str(result))) != str(root):
            raise ValueError("插件数据文件路径越界")
        if await self._has_symlink_component(result):
            raise ValueError("插件数据文件路径不能包含符号链接")
        return result

    async def delete_plugin_file(self, relative_path: str) -> None:
        """删除插件数据目录内的文件，目标不存在视为成功。"""

        path = AsyncPath(await self.plugin_file_path(relative_path))
        if await path.exists():
            if not await path.is_file():
                raise IsADirectoryError(str(path))
            await path.unlink()

    async def make_task_directory(self, task_id: str) -> Path:
        """创建当前任务独立临时目录。"""

        path = AsyncPath(self.data_root / "tmp" / task_id)
        await path.mkdir(parents=True, exist_ok=True)
        return Path(path)

    async def _remove_tree(self, path: AsyncPath) -> None:
        """递归删除目录内容并拒绝跟随符号链接。"""

        if await path.is_symlink() or await path.is_file():
            await path.unlink()
            return
        if not await path.exists():
            return
        async for child in path.iterdir():
            await self._remove_tree(child)
        await path.rmdir()

    async def cleanup_task_directory(self, task_id: str) -> None:
        """删除当前任务临时目录。"""

        path = AsyncPath(self.data_root / "tmp" / task_id)
        if await path.exists():
            await self._remove_tree(path)

    async def clear_data_directory(self) -> None:
        """清除插件数据目录内容但保留目录本身。"""

        root = AsyncPath(self.data_root)
        await root.mkdir(parents=True, exist_ok=True)
        async for child in root.iterdir():
            await self._remove_tree(child)
