"""容器路径与极空间路径之间的映射。

极空间里同一个目录有三种写法：
- 容器里看到的挂载路径，例如 ``/downloads/tv/黑镜 (2011)``；
- 宿主机 zfuse 视图，例如 ``/tmp/zfsv3/sata1/<uid>/data/downloads/tv``（极影视库里存的就是这种）；
- zspace-cli / 极空间接口用的用户路径，例如 ``/sata1/my/data/downloads/tv``。

本模块只做纯字符串换算，不访问文件系统，便于单测。
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

# 挂载根是极空间存储池下某个用户的 data 目录：/<pool>/<uid>/data[/...]
_POOL_ROOT = re.compile(r"^/(?P<pool>[A-Za-z0-9_]+)/(?P<uid>[^/]+)/data(?P<rest>/.*)?$")
# 极影视库里的 zfuse 视图路径：/tmp/zfsv3/<pool>/<uid>/data[/...]
_ZFUSE = re.compile(r"^/tmp/zfsv3/(?P<pool>[A-Za-z0-9_]+)/(?P<uid>[^/]+)/data(?P<rest>/.*)?$")


@dataclass(frozen=True)
class Mapping:
    """一条前缀映射：容器前缀 -> 极空间用户路径前缀。"""

    container: str
    zspace: str
    source: str = "manual"


def normalize(path: str) -> str:
    """规范化 POSIX 路径：去掉重复斜杠、结尾斜杠和 ``.``，拒绝相对路径。"""
    if not path or not path.startswith("/"):
        raise ValueError("路径必须是绝对路径")
    if ".." in path.split("/"):
        raise ValueError("路径不允许包含 ..")
    norm = posixpath.normpath(path)
    # normpath 会保留开头的 //，统一成单个 /
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    return norm


def is_within(path: str, ancestor: str) -> bool:
    """按路径段判断 path 是否等于 ancestor 或在其之下。"""
    path = normalize(path)
    ancestor = normalize(ancestor)
    if ancestor == "/":
        return True
    return path == ancestor or path.startswith(ancestor + "/")


def _unescape_mountinfo(value: str) -> str:
    """mountinfo 用八进制转义空格等字符。"""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def parse_mountinfo(text: str) -> List[Tuple[str, str, str]]:
    """解析 /proc/self/mountinfo，返回 (挂载点, 挂载根, 文件系统类型)。"""
    rows: List[Tuple[str, str, str]] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 10 or "-" not in parts:
            continue
        sep = parts.index("-")
        root = _unescape_mountinfo(parts[3])
        mount_point = _unescape_mountinfo(parts[4])
        fstype = parts[sep + 1] if sep + 1 < len(parts) else ""
        rows.append((mount_point, root, fstype))
    return rows


def infer_mappings(mountinfo_text: str) -> List[Mapping]:
    """从挂载信息推断映射：挂载根形如 /<pool>/<uid>/data/... 的 zfuse 挂载。

    只认极空间 zfuse 文件系统，其它挂载（配置盘、证书）不会被误当成媒体目录。
    """
    mappings: List[Mapping] = []
    for mount_point, root, fstype in parse_mountinfo(mountinfo_text):
        if not fstype.startswith("zfuse"):
            continue
        match = _POOL_ROOT.match(root)
        if not match:
            continue
        rest = match.group("rest") or ""
        zspace = f"/{match.group('pool')}/my/data{rest}"
        mappings.append(Mapping(container=normalize(mount_point), zspace=normalize(zspace), source="auto"))
    return mappings


def parse_manual(text: str) -> List[Mapping]:
    """解析手动映射，每行 ``容器前缀 => 极空间前缀``，# 开头为注释。"""
    mappings: List[Mapping] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" not in line:
            raise ValueError(f"映射格式应为 容器前缀 => 极空间前缀：{line}")
        left, right = (part.strip() for part in line.split("=>", 1))
        mappings.append(Mapping(container=normalize(left), zspace=normalize(right), source="manual"))
    return mappings


def to_zspace(path: str, mappings: Sequence[Mapping]) -> Optional[str]:
    """把容器路径换成极空间用户路径；按最长前缀匹配，没有匹配返回 None。"""
    path = normalize(path)
    best: Optional[Mapping] = None
    for mapping in mappings:
        if is_within(path, mapping.container):
            if best is None or len(mapping.container) > len(best.container):
                best = mapping
    if best is None:
        return None
    suffix = path[len(best.container):] if best.container != "/" else path
    return normalize(best.zspace + suffix) if suffix else best.zspace


def from_zspace(path: str, mappings: Sequence[Mapping]) -> Optional[str]:
    """极空间用户路径 -> 容器路径（to_zspace 的反向）；没有匹配返回 None。"""
    path = normalize(path)
    best: Optional[Mapping] = None
    for mapping in mappings:
        if is_within(path, mapping.zspace):
            if best is None or len(mapping.zspace) > len(best.zspace):
                best = mapping
    if best is None:
        return None
    suffix = path[len(best.zspace):] if best.zspace != "/" else path
    return normalize(best.container + suffix) if suffix else best.container


def zfuse_to_zspace(path: str) -> Optional[str]:
    """极影视库里的 zfuse 路径 -> 用户路径；不是 zfuse 格式返回 None。"""
    match = _ZFUSE.match(path or "")
    if not match:
        return None
    rest = match.group("rest") or ""
    return normalize(f"/{match.group('pool')}/my/data{rest}")


def zfuse_owner(path: str) -> Optional[str]:
    """zfuse 路径里的用户目录名（极空间账号 uid）。"""
    match = _ZFUSE.match(path or "")
    return match.group("uid") if match else None


def merge_paths(paths: Iterable[str]) -> List[str]:
    """去重并去掉已被祖先目录覆盖的子路径，结果排序稳定。"""
    unique = sorted({normalize(p) for p in paths}, key=lambda p: (p.count("/"), p))
    kept: List[str] = []
    for path in unique:
        if any(is_within(path, parent) for parent in kept):
            continue
        kept.append(path)
    return sorted(kept)
