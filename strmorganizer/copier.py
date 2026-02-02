# plugins/strmorganizer/copier.py

from pathlib import Path
import shutil
from app.log import logger

META_EXTS = {".strm", ".jpg", ".png", ".webp", ".srt", ".ass", ".ssa", ".nfo"}


def copy_strm(
    missing_dirs,
    target_root: Path,
    full_root: Path,
    output_root: Path,
    dry_run: bool = True
):
    for d in missing_dirs:
        rel = d.relative_to(target_root)
        src_dir = full_root / rel
        dst_dir = output_root / rel

        if not src_dir.exists():
            logger.warning(f"[COPY] 完整库不存在 {src_dir}")
            continue

        dst_dir.mkdir(parents=True, exist_ok=True)

        for f in src_dir.iterdir():
            if f.is_file() and f.suffix.lower() in META_EXTS:
                dst = dst_dir / f.name
                if dst.exists():
                    continue

                if dry_run:
                    logger.info(f"[DRY-RUN] 复制 {f} -> {dst}")
                else:
                    shutil.copy2(f, dst)
                    logger.info(f"[COPY] {f} -> {dst}")
