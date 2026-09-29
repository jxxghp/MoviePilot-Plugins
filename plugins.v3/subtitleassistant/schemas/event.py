"""字幕落盘成功事实的公共事件契约。"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

__all__ = ["SubtitleWrittenEvent", "SubtitleWrittenOperation"]


class SubtitleWrittenOperation(StrEnum):
    """字幕落盘事件对应的业务操作类型。"""

    AUTOMATIC_CANDIDATE = "automatic_candidate"
    MANUAL_CANDIDATE = "manual_candidate"
    INVENTORY_CONSUMPTION = "inventory_consumption"
    RETARGET = "retarget"


@dataclass(frozen=True, slots=True)
class SubtitleWrittenEvent:
    """描述字幕文件与已匹配记录已经共同提交的成功事实。"""

    plugin_id: str
    operation: SubtitleWrittenOperation
    task_id: str | None
    record_id: str
    target_path: Path
    subtitle_path: Path
    action: Literal["subtitle_written"] = field(default="subtitle_written", init=False)

    def __post_init__(self) -> None:
        """把边界处的操作值收敛为强类型枚举。"""

        if not isinstance(self.operation, SubtitleWrittenOperation):
            object.__setattr__(self, "operation", SubtitleWrittenOperation(self.operation))
