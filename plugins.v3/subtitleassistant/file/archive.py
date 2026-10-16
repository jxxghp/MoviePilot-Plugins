"""统一使用 unar 的异步归档解包。"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path, PurePosixPath

from anyio import Path as AsyncPath

from app.log import logger

from ..schemas.file import ExtractedSubtitle
from ..schemas.source import DownloadedAsset


class ArchiveExtractor:
    """通过无 shell 的 unar 子进程解包字幕归档。"""

    def __init__(self) -> None:
        """初始化无状态解包器。"""

        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._processed_paths: set[str] = set()
        self._processed_digests: set[str] = set()
        self._archive_count = 0
        self._max_depth = 3
        self._max_archives = 100
        self._archive_extensions = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "cab", "iso"}
        self._compound_archive_suffixes = (".tar.bz2", ".tar.gz", ".tar.xz")

    async def extract(
        self,
        asset: DownloadedAsset,
        output: Path,
        allowed_formats: set[str],
    ) -> list[ExtractedSubtitle]:
        """解包归档并返回带逻辑来源路径的允许格式字幕。"""
        allowed = {item.lower().lstrip(".") for item in allowed_formats}
        extension = asset.path.suffix.lower().lstrip(".")
        source_name = self._source_name(asset)
        if extension in allowed:
            return [
                ExtractedSubtitle(
                    physical_path=Path(os.path.abspath(asset.path)),
                    logical_source_path=Path(source_name),
                    is_direct_file=True,
                )
            ]
        self._processed_paths.clear()
        self._processed_digests.clear()
        self._archive_count = 0
        return await self._extract_recursive(
            archive=asset.path,
            output=output,
            allowed=allowed,
            depth=1,
            logical_archive_parts=(self._outer_archive_name(source_name),),
        )

    async def _extract_recursive(
        self,
        archive: Path,
        output: Path,
        allowed: set[str],
        depth: int,
        logical_archive_parts: tuple[str, ...],
    ) -> list[ExtractedSubtitle]:
        """递归展开归档，单个分支失败不影响其他分支。"""
        if depth > self._max_depth:
            logger.warning(f"压缩包“{archive.name}”超过最大解包深度 {self._max_depth} 层，已停止处理该分支")
            return []
        if self._archive_count >= self._max_archives:
            logger.warning(
                f"当前候选已处理 {self._max_archives} 个压缩包，达到安全上限，已跳过“{archive.name}”及后续分支"
            )
            return []
        resolved_archive = Path(os.path.abspath(archive))
        digest = hashlib.sha256(await AsyncPath(resolved_archive).read_bytes()).hexdigest()
        normalized_path = os.path.normcase(str(resolved_archive))
        if normalized_path in self._processed_paths or digest in self._processed_digests:
            logger.debug(f"压缩包“{archive.name}”的路径或内容已经处理过，本次跳过")
            return []
        self._processed_paths.add(normalized_path)
        self._processed_digests.add(digest)
        self._archive_count += 1
        output = Path(output) if depth == 1 else Path(output) / f"level_{depth}_{self._archive_count}"
        output_async = AsyncPath(output)
        await output_async.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            self._process = await asyncio.create_subprocess_exec(
                "unar",
                "-quiet",
                "-force-overwrite",
                "-output-directory",
                str(output),
                str(archive),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            process = self._process
            stdout, stderr = await process.communicate()
            self._process = None
        if process.returncode != 0:
            detail = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"unar 解包失败：{detail[-300:]}")
        result: list[ExtractedSubtitle] = []
        nested: list[tuple[Path, tuple[str, ...]]] = []
        root = Path(os.path.abspath(output))
        async for child in output_async.rglob("*"):
            if await child.is_symlink():
                raise RuntimeError("解包结果包含不允许的符号链接")
            if not await child.is_file():
                continue
            resolved = Path(os.path.abspath(child))
            if os.path.commonpath((str(root), str(resolved))) != str(root):
                raise RuntimeError("解包结果路径越界")
            relative_parts = resolved.relative_to(root).parts
            logical_parts = (*logical_archive_parts, *relative_parts)
            if child.suffix.lower().lstrip(".") in allowed:
                result.append(
                    ExtractedSubtitle(
                        physical_path=resolved,
                        logical_source_path=Path(PurePosixPath(*logical_parts).as_posix()),
                        is_direct_file=False,
                    )
                )
            elif child.suffix.lower().lstrip(".") in self._archive_extensions:
                if depth >= self._max_depth:
                    logger.warning(
                        f"压缩包“{child.name}”位于第 {depth + 1} 层，超过最大解包深度 "
                        f"{self._max_depth} 层，已停止处理该分支"
                    )
                elif self._archive_count >= self._max_archives:
                    logger.warning(
                        f"当前候选已处理 {self._max_archives} 个压缩包，达到安全上限，已跳过“{child.name}”及后续分支"
                    )
                else:
                    nested.append((resolved, (*logical_archive_parts, *relative_parts[:-1])))
        for child, logical_parts in nested:
            try:
                result.extend(
                    await self._extract_recursive(
                        archive=child,
                        output=output,
                        allowed=allowed,
                        depth=depth + 1,
                        logical_archive_parts=logical_parts,
                    )
                )
            except RuntimeError as exc:
                logger.warning(f"压缩包分支“{child.name}”解包失败，其他分支将继续处理：{str(exc)[:300]}")
                continue
        return result

    @staticmethod
    def _source_name(asset: DownloadedAsset) -> str:
        """取下载元数据中的末级文件名，避免临时下载目录进入逻辑路径。"""

        normalized = asset.file_name.replace("\\", "/").rstrip("/")
        return normalized.rsplit("/", 1)[-1] or asset.path.name

    def _outer_archive_name(self, source_name: str) -> str:
        """移除外层包完整已知归档扩展名并保留发布名普通点号。"""

        lowered = source_name.casefold()
        for suffix in self._compound_archive_suffixes:
            if lowered.endswith(suffix):
                name = source_name[: -len(suffix)]
                return name or source_name
        suffix = Path(source_name).suffix
        if suffix.lstrip(".").casefold() in self._archive_extensions:
            name = source_name[: -len(suffix)]
            return name or source_name
        return source_name

    async def cancel(self) -> None:
        """终止当前 unar 子进程并等待退出。"""

        process = self._process
        if process is None or process.returncode is not None:
            return
        process.terminate()
        await process.wait()
