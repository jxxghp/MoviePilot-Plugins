"""分类与目录的对应关系，以及「这个路径该刷新哪个分类的哪个目录」。

zspace-cli 0.3.11 的 ``dirs`` 只返回所有分类目录的并集，拿不到分类和目录的对应；
而且 ``rescan`` 对不属于该分类的路径也会返回成功（服务端不校验）。所以对应关系必须
由插件自己确定，来源优先级：
1. 手动配置（``分类名或ID = 目录``）；
2. 只读挂载的极影视库 ``zvideo.db`` 的 ``zvideo_classification_file`` 表；
3. 都没有时不刷新，避免把路径投到错误的分类。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .pathmap import is_within, normalize, zfuse_owner, zfuse_to_zspace


@dataclass
class Library:
    """一个极影视分类。"""

    id: str
    name: str
    dirs: List[str] = field(default_factory=list)
    is_system: bool = False


@dataclass(frozen=True)
class Target:
    """一次刷新目标：某分类下某个目录（极空间用户路径）。"""

    library_id: str
    library_name: str
    library_dir: str
    path: str


def read_zvideo_dirs(db_path: str, owner: Optional[str] = None) -> Dict[str, List[str]]:
    """只读打开极影视库，返回 {分类ID: [用户路径目录]}。

    使用 ``mode=ro``；挂载为只读时 SQLite 仍能读到 WAL 里的最新提交。
    owner 不为空时只取该账号（zfuse 路径中的 uid）的目录。
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        rows = conn.execute(
            "select classification_id, path from zvideo_classification_file"
        ).fetchall()
    finally:
        conn.close()
    result: Dict[str, List[str]] = {}
    for library_id, raw_path in rows:
        if owner and zfuse_owner(raw_path) not in (None, owner):
            continue
        path = zfuse_to_zspace(raw_path)
        if not path:
            continue
        bucket = result.setdefault(str(library_id), [])
        if path not in bucket:
            bucket.append(path)
    return result


def parse_manual_dirs(text: str, libraries: Sequence[Library]) -> Dict[str, List[str]]:
    """解析手动分类目录，每行 ``分类名或分类ID = 极空间目录``。"""
    by_name = {lib.name: lib.id for lib in libraries}
    by_id = {lib.id: lib.id for lib in libraries}
    result: Dict[str, List[str]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"分类目录格式应为 分类名 = 目录：{line}")
        key, value = (part.strip() for part in line.split("=", 1))
        library_id = by_id.get(key) or by_name.get(key)
        if not library_id:
            raise ValueError(f"找不到分类：{key}")
        path = normalize(value)
        bucket = result.setdefault(library_id, [])
        if path not in bucket:
            bucket.append(path)
    return result


def attach_dirs(libraries: Sequence[Library], dirs: Dict[str, List[str]]) -> List[Library]:
    """把目录挂到分类上，返回新列表。"""
    out = []
    for lib in libraries:
        out.append(Library(id=lib.id, name=lib.name, dirs=list(dirs.get(lib.id, [])), is_system=lib.is_system))
    return out


def resolve_targets(path: str, libraries: Iterable[Library]) -> List[Target]:
    """找出包含该路径的所有分类目录。

    「电影」「电视剧」这类共享目录的智能分类会同时命中，两边都要刷新。
    同一分类下若多个目录都包含该路径，取最深的那个。
    """
    path = normalize(path)
    targets: List[Target] = []
    for lib in libraries:
        best: Optional[str] = None
        for library_dir in lib.dirs:
            if is_within(path, library_dir) and (best is None or len(library_dir) > len(best)):
                best = library_dir
        if best:
            targets.append(Target(library_id=lib.id, library_name=lib.name, library_dir=best, path=path))
    return targets
