"""只读源路径规划的输入校验，不接触文件系统或下载器写 API。"""

import re
from pathlib import PurePosixPath

from fastapi import HTTPException


def safe_component(value: str) -> str:
    """规范单一路径分量，避免艺人或作品名称产生额外目录层。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")[:180]
    if not cleaned:
        raise HTTPException(status_code=422, detail="名称为空或包含非法路径片段")
    return cleaned


def absolute_path(value: str) -> PurePosixPath:
    """当前规划针对 NAS POSIX 路径，拒绝相对路径与路径穿越。"""
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(ord(char) < 32 for char in value)
        or path.as_posix().startswith("//")
    ):
        raise HTTPException(status_code=422, detail="必须使用无路径穿越的绝对 NAS 路径")
    return path
