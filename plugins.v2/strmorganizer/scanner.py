# plugins/strmorganizer/scanner.py

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Set

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".ts", ".rmvb"}


def _is_final_media_dir(path: Path) -> bool:
    files = list(path.iterdir())
    has_video = any(f.suffix.lower() in VIDEO_EXTS for f in files if f.is_file())
    has_strm = any(f.suffix.lower() == ".strm" for f in files if f.is_file())
    return has_video and not has_strm


def scan_missing_strm(target_root: Path, max_workers: int = 8) -> List[Path]:
    """
    扫描缺失 STRM 的最终媒体目录
    """
    result: Set[Path] = set()

    all_dirs = [
        p for p in target_root.rglob("*")
        if p.is_dir() and not p.is_symlink()
    ]

    def check_dir(p: Path):
        if _is_final_media_dir(p):
            result.add(p)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pool.map(check_dir, all_dirs)

    return sorted(result)
