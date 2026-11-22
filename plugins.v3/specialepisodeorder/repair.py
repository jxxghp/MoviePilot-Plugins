"""限定目录内的 NFO 预览和原子写入。"""

import os
import stat
import tempfile
from pathlib import Path
from threading import Event, RLock

from app.sdk.cache import MemoryBackend
from app.sdk.logging import logger

from .nfo import NfoEnricher, children, integer, node_text, parse_document, read_positions, tmdb_identity


NFO_CACHE_REGION = "specialepisodeorder.nfo.non-special.v1"
_non_special_cache = MemoryBackend(maxsize=32768, ttl=24 * 3600)


def atomic_write(path: Path, content: bytes, original_stat: os.stat_result) -> None:
    """同目录落盘后原子替换，保留权限并尽可能保留所有者。"""
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            if hasattr(os, "fchown"):
                current = os.fstat(descriptor)
                if (current.st_uid, current.st_gid) != (original_stat.st_uid, original_stat.st_gid):
                    try:
                        os.fchown(descriptor, original_stat.st_uid, original_stat.st_gid)
                    except PermissionError:
                        logger.debug(f"特典播放顺序：权限不足，无法保留 {path} 的原属主和属组")
            os.fchmod(descriptor, stat.S_IMODE(original_stat.st_mode))
            os.fsync(descriptor)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class RepairRunner:
    """只扫描用户明确配置的本地目录；停用与写入共用锁。"""

    def __init__(self, engine: NfoEnricher, stopped: Event, write_lock: RLock) -> None:
        """保存本次扫描的引擎、取消信号及写入锁。"""
        self.engine = engine
        self.stopped, self.write_lock = stopped, write_lock

    @staticmethod
    def clear_file_cache() -> None:
        """清空普通 NFO 的进程内识别缓存。"""
        _non_special_cache.clear(region=NFO_CACHE_REGION)

    @staticmethod
    def _show_id(path: Path, root: Path) -> int | None:
        """在配置范围内寻找最近的 tvshow.nfo，不跨越扫描根目录。"""
        for directory in path.parents:
            candidate = directory / "tvshow.nfo"
            if candidate.is_file() and not candidate.is_symlink():
                document = parse_document(candidate.read_bytes())
                if document.documentElement.tagName == "tvshow":
                    return tmdb_identity(document.documentElement)
                return None
            if directory == root:
                break
        return None

    def run(self, paths: list[str], dry_run: bool = True) -> dict:
        """逐份预览或修复 NFO，将结果返回给当前插件实例。"""
        report = {"dry_run": dry_run, "status": "completed", "counts": {}, "records": []}
        seen = set()
        for value in paths:
            root = Path(value).expanduser()
            if root.is_symlink() or not root.is_dir():
                self._record(report, {"path": str(root), "status": "failed", "reason": "扫描根目录不存在或为符号链接"})
                continue
            root = root.resolve()
            show_ids: dict[Path, int | None] = {}
            for directory, directories, files in os.walk(root, followlinks=False):
                directories[:] = sorted(name for name in directories if not name.startswith(".") and not name.endswith(".trickplay"))
                for name in sorted(files):
                    if self.stopped.is_set():
                        report["status"] = "cancelled"
                        return report
                    path = Path(directory) / name
                    if path.suffix.lower() != ".nfo" or path in seen:
                        continue
                    seen.add(path)
                    record = {"path": str(path), "status": "skipped", "reason": "不是 Season 0 单集 NFO"}
                    try:
                        original_stat = path.lstat()
                        if not stat.S_ISREG(original_stat.st_mode):
                            continue
                        signature = (
                            original_stat.st_dev, original_stat.st_ino, original_stat.st_size,
                            original_stat.st_mtime_ns, original_stat.st_ctime_ns,
                        )
                        cache_key = str(path)
                        if _non_special_cache.get(cache_key, region=NFO_CACHE_REGION) == signature:
                            continue
                        original = path.read_bytes()
                        document = parse_document(original)
                        root_node = document.documentElement
                        nodes = children(root_node) if root_node.tagName == "episodedetails" else {}
                        season = integer(node_text(nodes.get("season")))
                        episode = integer(node_text(nodes.get("episode")), minimum=1)
                        if season != 0 or episode is None:
                            # 仅跳过内容已确认不属于目标的文件，且下次必须核对文件状态。
                            with self.write_lock:
                                if not self.stopped.is_set():
                                    _non_special_cache.set(cache_key, signature, region=NFO_CACHE_REGION)
                            continue
                        record["before"] = read_positions(nodes)
                        record["after"] = record["before"].copy()
                        if path.parent not in show_ids:
                            show_ids[path.parent] = self._show_id(path, root)
                        outcome = self.engine.enrich(original, show_ids[path.parent], episode)
                        record.update(
                            status=outcome.status, reason=outcome.reason,
                            mapping_source=outcome.mapping_source, tmdb_episode_id=outcome.tmdb_episode_id,
                            tvdb_episode_id=outcome.tvdb_episode_id,
                        )
                        if outcome.status == "updated":
                            if dry_run:
                                record["status"] = "preview"
                                record["reason"] = "可更新播放位置" if outcome.replaces_positions else "可补全缺失的播放位置"
                            else:
                                with self.write_lock:
                                    if self.stopped.is_set():
                                        record["status"], record["reason"] = "skipped", "插件已停用或重新配置"
                                    elif path.is_symlink() or path.read_bytes() != original:
                                        record["status"], record["reason"] = "skipped", "文件在查询期间已变化，未写入"
                                    else:
                                        output = outcome.content
                                        if isinstance(output, str):
                                            output = output.encode("utf-8")
                                        atomic_write(path, output, original_stat)
                                        logger.debug(f"特典播放顺序：已更新 {path}（{outcome.mapping_source}），{outcome.describe_changes()}")
                            if record["status"] in ("preview", "updated"):
                                record["after"] = outcome.positions_after
                    except Exception as error:
                        record.update(status="failed", reason=f"文件处理失败：{type(error).__name__}")
                    self._record(report, record)
        report["status"] = "cancelled" if self.stopped.is_set() else "completed"
        return report

    @staticmethod
    def _record(report: dict, record: dict) -> None:
        """累计计数并保留每条扫描明细。"""
        status = record["status"]
        report["counts"][status] = report["counts"].get(status, 0) + 1
        report["records"].append(record)
