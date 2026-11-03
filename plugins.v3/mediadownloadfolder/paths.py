"""显式目录引用及下载子目录组合，不复制宿主自动选址策略。"""

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.modules.filemanager.transhandler import TransHandler
from app.schemas.file import FileURI
from app.schemas.system import TransferDirectoryConf
from app.schemas.types import StorageSchema
from app.sdk.media import MediaInfo


@dataclass(frozen=True)
class DirectoryReference:
    """保存用户当时选择的名称、存储和路径，避免目录变化后被同名配置替代。"""

    name: str | None
    storage: str
    path: str

    @property
    def uri(self) -> str:
        """返回下载事件接受的存储地址。"""
        return FileURI(storage=self.storage, path=self.path).uri


def _safe_root(path: str, storage: str) -> str:
    """校验选中的绝对根路径，保留宿主支持的本地盘符和远端 POSIX 形式。"""
    if (
        storage not in {item.value for item in StorageSchema}
        or not path
        or path != path.strip()
        or "\\" in path
        or path.startswith("//")
        or re.match(r"^/[A-Za-z]:(?:/|$)", path)
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        raise ValueError("下载目录的存储或绝对路径无效")
    windows = bool(re.match(r"^[A-Za-z]:/", path))
    parsed = PureWindowsPath(path) if windows else PurePosixPath(path)
    if not parsed.is_absolute() or ".." in parsed.parts or (windows and storage != "local"):
        raise ValueError("下载目录必须是没有上级跳转的绝对路径")
    return parsed.as_posix()


def directory_reference(directory: TransferDirectoryConf) -> str:
    """生成可供选择器持久化的精确引用，不包含其它目录设置。"""
    storage = directory.storage or "local"
    _safe_root(directory.download_path or "", storage)
    return json.dumps(
        [directory.name, storage, directory.download_path],
        ensure_ascii=False, separators=(",", ":"),
    )


def parse_reference(value: str) -> DirectoryReference:
    """验证插件配置中的根引用，不能由手工配置构造越界路径。"""
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("下载目录引用无效，请重新选择")
    try:
        parts = json.loads(value)
    except (ValueError, TypeError) as error:
        raise ValueError("下载目录引用无效，请重新选择") from error
    if (
        not isinstance(parts, list) or len(parts) != 3
        or (parts[0] is not None and not isinstance(parts[0], str))
        or not isinstance(parts[1], str) or not isinstance(parts[2], str)
    ):
        raise ValueError("下载目录引用无效，请重新选择")
    name, storage, path = parts
    _safe_root(path, storage)
    return DirectoryReference(name=name, storage=storage, path=path)


def resolve_directory(value: str, directories: list[TransferDirectoryConf]) -> TransferDirectoryConf:
    """仅接受唯一匹配的原配置，删除、改名或改路径后要求重新选择。"""
    reference = parse_reference(value)
    matches = [
        directory for directory in directories
        if (directory.name, directory.storage or "local", directory.download_path)
        == (reference.name, reference.storage, reference.path)
    ]
    if len(matches) != 1:
        raise ValueError("选中的下载目录已变化、删除或存在重复配置，请重新选择")
    return matches[0]


def build_save_path(directory: TransferDirectoryConf, media: MediaInfo, folder: str) -> str:
    """复用宿主类型与分类拼接，再追加已验证的作品目录；不创建文件或目录。"""
    storage = directory.storage or "local"
    root = _safe_root(directory.download_path or "", storage)
    path = TransHandler.get_dest_path(
        mediainfo=media,
        target_path=Path(root),
        need_type_folder=not directory.media_type and bool(directory.download_type_folder),
        need_category_folder=not (directory.media_category_id or directory.media_category)
        and bool(directory.download_category_folder),
    ) / folder
    return FileURI(storage=storage, path=path.as_posix()).uri
