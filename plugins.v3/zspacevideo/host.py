"""MoviePilot / qBittorrent 侧适配：给已看删除提供记录查询、种子、删除能力。

只在插件进程里导入（依赖 MoviePilot）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.sdk.logging import logger

from .core import watched as W


def _snapshot_dict(item: Any) -> Dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return dict(item)
    return dict(getattr(item, "__dict__", {}))


def _query_all(fn: Any, filters: Dict[str, Any], limit: int = 2000) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 1
    while len(rows) < limit:
        result = fn(filters, {"page": page, "count": 200, "sort": {"field": "id", "direction": "asc"}})
        rows.extend(_snapshot_dict(x) for x in result.items)
        if not result.has_next:
            break
        page += 1
    return rows


def transfers_by_tmdb(tmdb_id: int) -> List[Dict[str, Any]]:
    from app.sdk import queries
    return _query_all(queries.list_transfer_history,
                      {"media_source": "themoviedb", "media_id": str(tmdb_id), "status": True})


def downloads_by_tmdb(tmdb_id: int) -> List[Dict[str, Any]]:
    from app.sdk import queries
    return _query_all(queries.list_download_history, {"media_source": "themoviedb", "media_id": str(tmdb_id)})


def library_roots() -> W.Roots:
    from app.application.directory import DirectoryHelper
    library: List[str] = []
    download: List[str] = []
    for conf in DirectoryHelper.get_dirs():
        if conf.library_path and (conf.library_storage or "local") == "local":
            library.append(os.path.normpath(conf.library_path))
        if conf.download_path and (conf.storage or "local") == "local":
            download.append(os.path.normpath(conf.download_path))
    # 下载根取最短的公共前缀（_wash 在 complete 下面）
    download = sorted({d for d in download if not any(d != o and W.within(d, o) for o in download)})
    library = sorted({d for d in library if not any(d != o and W.within(d, o) for o in library)})
    return W.Roots(library=library, download=download)


class QbAdapter:
    """所有 qBittorrent 下载器（MP 里配置的）的合并视图。"""

    def __init__(self) -> None:
        from app.sdk.services import DownloaderHelper
        self._helper = DownloaderHelper()

    def _clients(self) -> List[Any]:
        services = self._helper.get_services(type_filter="qbittorrent") or {}
        clients = []
        for service in services.values():
            instance = getattr(service, "instance", None)
            if instance is not None and getattr(instance, "qbc", None) is not None:
                clients.append(instance)
        return clients

    _site_names: Optional[Dict[str, str]] = None

    def _site(self, tracker: str, tags: str) -> str:
        """tracker 域名 -> MP 站点名（按站点域名后缀匹配）；对不上就给域名。"""
        host = tracker.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower() if tracker else ""
        if not host:
            return ""
        if self._site_names is None:
            names: Dict[str, str] = {}
            try:
                from app.db.oper.site import SiteOper
                for site in SiteOper().list():
                    domain = str(getattr(site, "domain", "") or "").lower()
                    name = str(getattr(site, "name", "") or "")
                    if domain and name:
                        names[domain] = name
            except Exception as error:  # noqa: BLE001
                logger.debug(f"极空间影视：读取站点列表失败：{error}")
            self._site_names = names
        parts = host.split(".")
        for i in range(len(parts) - 1):
            suffix = ".".join(parts[i:])
            if suffix in self._site_names:
                return self._site_names[suffix]
        # tracker 与站点主域名后缀不同（如 tracker.example.cc 对 example.io）：按主名比
        stem = parts[-2] if len(parts) >= 2 else host
        for domain, name in self._site_names.items():
            if domain.split(".")[0] == stem:
                return name
        return host

    def torrents(self, hashes: Optional[Sequence[str]] = None) -> List[W.TorrentInfo]:
        if not hashes:
            self._site_names = None  # 全量读取时顺便刷新站点名
        result: List[W.TorrentInfo] = []
        for client in self._clients():
            items, error = client.get_torrents(ids=list(hashes) if hashes else None)
            if error:
                raise RuntimeError("读取 qBittorrent 任务失败")
            for t in items:
                result.append(W.TorrentInfo(
                    hash=str(t.get("hash")), name=str(t.get("name") or ""),
                    content_path=str(t.get("content_path") or ""), save_path=str(t.get("save_path") or ""),
                    state=str(t.get("state") or ""), site=self._site(str(t.get("tracker") or ""), str(t.get("tags") or "")),
                    size=int(t.get("size") or 0), tags=str(t.get("tags") or "")))
        return result

    def files(self, torrent: W.TorrentInfo) -> List[str]:
        for client in self._clients():
            items, _ = client.get_torrents(ids=[torrent.hash])
            if not items:
                continue
            listing = client.get_files(torrent.hash) or []
            base = torrent.save_path.rstrip("/")
            return [os.path.normpath(os.path.join(base, str(f.get("name")))) for f in listing]
        return []

    def delete(self, hashes: Sequence[str]) -> bool:
        ok = True
        for client in self._clients():
            items, _ = client.get_torrents(ids=list(hashes))
            mine = [str(t.get("hash")) for t in items]
            if mine:
                ok = client.delete_torrents(delete_file=True, ids=mine) and ok
        return ok


def delete_path(path: str, role: str) -> bool:
    """经 MP 存储删除一个文件（本地存储）。"""
    from app import schemas
    from app.chain.storage import StorageChain
    item = schemas.FileItem(storage="local", type="file", path=path, name=Path(path).name)
    ok = StorageChain().delete_file(item)
    logger.info(f"极空间影视：删除 {role} {path}：{'成功' if ok else '失败'}")
    return bool(ok)


def prune_dir(path: str) -> None:
    """库里删完后，向上清理空目录（MP 的 delete_media_file 逻辑：止于媒体库分类目录）。"""
    from app import schemas
    from app.chain.storage import StorageChain
    folder = Path(path)
    if not folder.exists():
        return
    try:
        if any(folder.iterdir()):
            return
    except OSError:
        return
    item = schemas.FileItem(storage="local", type="dir", path=str(folder), name=folder.name)
    StorageChain().delete_media_file(item, delete_self=True)


def delete_records(ids: Sequence[int]) -> int:
    from app.db.oper.transferhistory import TransferHistoryOper
    oper = TransferHistoryOper()
    count = 0
    for record_id in ids:
        try:
            oper.delete(int(record_id))
            count += 1
        except Exception as error:  # noqa: BLE001
            logger.warning(f"极空间影视：删除整理记录 {record_id} 失败：{error}")
    return count


def forget_sources(paths: Sequence[str]) -> None:
    from app.db.oper.downloadhistory import DownloadHistoryOper
    oper = DownloadHistoryOper()
    for path in paths:
        try:
            oper.delete_file_by_fullpath(Path(path).as_posix())
        except Exception as error:  # noqa: BLE001
            logger.warning(f"极空间影视：清理下载文件记录 {path} 失败：{error}")
