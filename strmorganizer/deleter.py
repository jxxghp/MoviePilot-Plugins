# plugins/strmorganizer/deleter.py

from pathlib import Path
from app.log import logger


def delete_strm(dirs, dry_run: bool = True):
    for d in dirs:
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() == ".strm":
                if dry_run:
                    logger.info(f"[DRY-RUN] 删除 {f}")
                else:
                    try:
                        f.unlink()
                        logger.info(f"[DELETE] 已删除 {f}")
                    except Exception as e:
                        logger.error(f"[DELETE] 删除失败 {f}: {e}")
