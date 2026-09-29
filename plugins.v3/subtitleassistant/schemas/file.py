"""字幕文件与归档能力之间的交接契约。"""

from dataclasses import dataclass
from pathlib import Path

__all__ = ["ExtractedSubtitle"]


@dataclass(frozen=True, slots=True)
class ExtractedSubtitle:
    """描述解包后字幕的物理位置与可审计逻辑来源。"""

    physical_path: Path
    logical_source_path: Path
    is_direct_file: bool
