"""通过宿主公开 Chain 编排音乐下载；不改宿主流程或做种文件。"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any
from uuid import UUID

from app.chain.download import DownloadChain
from app.chain.mediaserver import MediaServerChain
from app.chain.musicbrainz import MusicBrainzChain
from app.chain.search import SearchChain
from app.schemas.types import MediaSource, MediaType
from app.sdk.logging import logger
from app.sdk.media import Context, MetaMusic, MusicInfo, TorrentInfo
from app.sdk.services import MediaServerHelper, MusicMediaServerHelper
from fastapi import HTTPException

from .matching import (
    collection_search_terms,
    evaluate_coverage,
    is_collection_resource,
    useful_artist_aliases,
    work_from_mapping,
)
from .paths import absolute_path, safe_component

_EXCLUDED_SECONDARY_TYPES = {
    "Compilation",
    "Live",
    "Remix",
    "Soundtrack",
    "DJ-mix",
    "Mixtape/Street",
}
_MAX_LIBRARY_ITEMS = 20000


def _artist_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(
            status_code=422, detail="无效的 MusicBrainz 艺术家 ID"
        ) from error


def _public_artist(info: Any) -> dict[str, Any]:
    data = info.to_dict() if hasattr(info, "to_dict") else dict(info or {})
    return {
        "media_source": "musicbrainz",
        "media_id": str(data.get("media_id") or ""),
        "name": str(data.get("name") or data.get("title") or ""),
        "sort_name": data.get("sort_name"),
        "disambiguation": data.get("disambiguation"),
        "artist_type": data.get("artist_type"),
        "country": data.get("country"),
        "aliases": [
            str(item)
            for item in data.get("aliases") or data.get("artist_aliases") or []
            if item
        ],
        "image_url": data.get("image_url") or data.get("poster_path"),
    }


def _public_torrent(torrent: TorrentInfo) -> dict[str, Any]:
    """只投影展示字段；下载 URL、Cookie、UA 和代理参数不得离开后端。"""
    return {
        "title": str(torrent.title or ""),
        "description": str(torrent.description or "")[:2000],
        "site_name": str(torrent.site_name or ""),
        "size": float(torrent.size or 0),
        "seeders": int(torrent.seeders or 0),
    }


def _candidate_key(context: Context, scope: str) -> str:
    torrent = context.torrent_info
    identity = (
        f"{scope}|{torrent.site}|{torrent.enclosure}|{torrent.page_url}|{torrent.title}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _library_state(media: MusicInfo, items: list, complete: bool) -> str:
    """已存在表示发现同一作品，不承诺曲目或发行版本完整。"""
    probe = MusicInfo.from_dict(media.to_dict())
    probe.total_tracks = 1
    if any(MusicMediaServerHelper.item_matches(probe, item) for item in items):
        return "present"
    return "missing" if complete else "unknown"


class MusicLibraryService:
    """搜索候选保存在插件实例内，提交时只使用后端绑定的作品身份。"""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.music = MusicBrainzChain()
        self.servers = MediaServerChain()
        self.server_configs = MediaServerHelper()
        self.search = SearchChain()
        self.download = DownloadChain()

    async def search_artists(self, query: str, limit: int = 20) -> list[dict]:
        candidates = await self.music.async_search_music(
            MetaMusic.parse_query(query),
            limit=limit,
            music_types=("artist",),
        )
        result, seen = [], set()
        for candidate in candidates or []:
            media_id = str(candidate.media_id or "")
            if media_id and media_id not in seen:
                seen.add(media_id)
                detail = await self.music.async_get_music_artist(media_id)
                result.append(_public_artist(detail or candidate))
        return result

    def library_inventory(self) -> tuple[list, bool]:
        """完整枚举音乐库后才判定缺失；无音乐库、数量不符及失败均为未知。"""
        result, complete, music_libraries = [], True, 0
        configs = self.server_configs.get_configs()
        for name in configs:
            try:
                libraries = self.servers.librarys(server=name)
                if libraries is None:
                    complete = False
                    continue
                for library in libraries:
                    if str(library.type or "").casefold() not in {
                        "music",
                        "音乐",
                        "musicalbum",
                        "audio",
                    }:
                        continue
                    music_libraries += 1
                    count = self.servers.items_count(server=name, library_id=library.id)
                    if (
                        count is None
                        or count < 0
                        or count > _MAX_LIBRARY_ITEMS - len(result)
                    ):
                        complete = False
                        continue
                    batch = []
                    for item in self.servers.items(server=name, library_id=library.id):
                        if item:
                            batch.append(item)
                        if len(batch) > count:
                            break
                    result.extend(batch)
                    complete = complete and len(batch) == count
            except Exception:  # noqa: BLE001 - 提供方边界：未知不能成为自动下载依据
                logger.warning("音乐媒体库清单读取失败，未命中作品保持未知")
                complete = False
        return result, bool(configs and music_libraries and complete)

    async def catalog(self, artist_id: str) -> tuple[dict, list[dict], bool]:
        artist_id = _artist_id(artist_id)
        artist = await self.music.async_get_music_artist(artist_id)
        if not artist:
            raise HTTPException(
                status_code=502, detail="MusicBrainz 未返回该艺术家，请稍后重试"
            )
        groups = await asyncio.gather(
            *(self._all_works(artist_id, kind) for kind in ("album", "ep", "single"))
        )
        works = {
            str(item.media_id): item
            for group in groups
            for item in group
            if item.media_id
            and not any(
                kind in _EXCLUDED_SECONDARY_TYPES for kind in item.secondary_types or []
            )
        }
        inventory, complete = await asyncio.to_thread(self.library_inventory)
        rows = [
            {
                "media": item.to_dict(),
                "library_state": _library_state(item, inventory, complete),
            }
            for item in works.values()
        ]
        rows.sort(
            key=lambda row: (
                str(
                    row["media"].get("release_date")
                    or row["media"].get("year")
                    or "9999"
                ),
                str(row["media"].get("title") or ""),
            )
        )
        return _public_artist(artist), rows, complete

    async def _all_works(self, artist_id: str, album_type: str) -> list[MusicInfo]:
        result = []
        for page in range(1, 51):
            batch = await self.music.async_get_music_artist_albums(
                media_id=artist_id,
                page=page,
                count=100,
                album_type=album_type,
            )
            if batch is None:
                raise HTTPException(status_code=502, detail="官方作品目录加载失败")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise HTTPException(
            status_code=502, detail="作品目录超出扫描上限，未宣称目录完整"
        )

    async def collections(
        self,
        artist_id: str,
        artist_name: str | None,
        sites: list[int] | None,
        limit: int,
    ) -> tuple[list[dict], list[str]]:
        artist, rows, _ = await self.catalog(artist_id)
        primary = artist["name"]  # 浏览器名称不能改变已选择的艺术家
        aliases = useful_artist_aliases(
            primary, [artist.get("sort_name") or "", *artist["aliases"]]
        )
        terms = collection_search_terms(primary, aliases)
        batches = await asyncio.gather(
            *(
                self.search.async_search_by_title(
                    title=term, sites=sites, mtype=MediaType.MUSIC
                )
                for term in terms
            ),
            return_exceptions=True,
        )
        unique = {}
        for batch in batches:
            if isinstance(batch, BaseException):
                logger.warning("艺术家合集站点搜索失败")
                continue
            for context in batch or []:
                torrent = context.torrent_info
                if torrent and is_collection_resource(
                    torrent.title, torrent.description, aliases
                ):
                    unique.setdefault(
                        _candidate_key(context, f"collection:{artist_id}"), context
                    )
        works = [work_from_mapping(row["media"]) for row in rows]
        candidates = sorted(
            unique.items(), key=lambda pair: -(pair[1].torrent_info.seeders or 0)
        )[:32]
        semaphore = asyncio.Semaphore(2)

        async def probe(key: str, context: Context) -> dict | None:
            torrent = context.torrent_info
            try:
                async with semaphore:
                    _, folder, files = await asyncio.to_thread(
                        self.download.download_torrent,
                        torrent,
                        source="MusicLibraryManagerProbe",
                    )
                coverage = evaluate_coverage(
                    works,
                    files or [],
                    torrent.title or "",
                    torrent.description or "",
                    folder or "",
                )
            except Exception:  # noqa: BLE001 - 单个外部种子解析失败不影响其它候选
                logger.warning("解析艺术家合集种子文件清单失败")
                return None
            self.owner.cache_candidate(key, context, artist=artist, kind="collection")
            return {"key": key, **_public_torrent(torrent), "coverage": coverage}

        probed = await asyncio.gather(
            *(probe(key, context) for key, context in candidates)
        )
        items = sorted(
            (item for item in probed if item),
            key=lambda item: (
                -item["coverage"]["confirmed_count"],
                -item["coverage"]["probable_count"],
                -item["seeders"],
            ),
        )
        return items[:limit], terms

    async def completion(self, artist_id: str, sites: list[int] | None) -> dict:
        artist, rows, complete = await self.catalog(artist_id)
        missing = [row for row in rows if row["library_state"] == "missing"]
        semaphore = asyncio.Semaphore(3)

        async def match(row: dict) -> dict:
            media = row["media"]
            try:
                async with semaphore:
                    contexts = await self.search.async_search_by_id(
                        media_source=MediaSource.MusicBrainz,
                        media_id=str(media["media_id"]),
                        mtype=MediaType.MUSIC,
                        area="title",
                        sites=sites,
                        music_type="album",
                        include_candidates=True,
                    )
            except Exception:  # noqa: BLE001 - 单个站点搜索失败保留缺失行
                logger.warning("搜索缺失作品失败")
                contexts = []
            resources = []
            for context in contexts or []:
                if not context.torrent_info:
                    continue
                exact = (
                    context.match_status == "exact"
                    and context.media_info is not None
                    and str(context.media_info.media_id) == str(media["media_id"])
                )
                key = _candidate_key(
                    context, f"completion:{artist_id}:{media['media_id']}"
                )
                if exact:
                    self.owner.cache_candidate(
                        key, context, artist=artist, kind="completion", media=media
                    )
                resources.append(
                    {
                        "key": key,
                        **_public_torrent(context.torrent_info),
                        "exact": exact,
                    }
                )
            resources.sort(key=lambda item: (not item["exact"], -item["seeders"]))
            return {**row, "resources": resources}

        return {
            "items": await asyncio.gather(*(match(row) for row in missing)),
            "present_count": sum(row["library_state"] == "present" for row in rows),
            "unknown_count": sum(row["library_state"] == "unknown" for row in rows),
            "library_status_complete": complete,
        }

    def download_collection(
        self,
        artist_id: str,
        artist_name: str,
        candidate_key: str,
        downloader: str | None,
        save_path: str | None,
    ) -> dict:
        self.owner.require_enabled()
        artist_id = _artist_id(artist_id)
        if save_path:
            absolute_path(save_path)
        candidate = self.owner.take_candidate(
            candidate_key, artist_id=artist_id, kind="collection"
        )
        artist_name = candidate["artist"]["name"]
        torrent = candidate["context"].torrent_info
        media = MusicInfo(
            media_source=MediaSource.MusicBrainz,
            media_id=artist_id,
            music_type="artist",
            title=f"{artist_name} 艺术家合集",
            artists=[artist_name],
            album_artist=artist_name,
            album_type="Artist Collection",
            library_category="Artist Collection",
        )
        context = Context(
            meta_info=MetaMusic.parse_resource(
                torrent.title or "", torrent.description
            ),
            media_info=media,
            torrent_info=torrent,
        )
        target = self.owner.collection_save_path(artist_name, save_path)
        row = self._submit(context, downloader, target)
        row["role"] = "collection"
        return self.owner.save_job("collection", artist_id, artist_name, [row])

    def download_completion(
        self,
        artist_id: str,
        artist_name: str,
        items: list,
        downloader: str | None,
        save_path: str | None,
    ) -> dict:
        self.owner.require_enabled()
        artist_id = _artist_id(artist_id)
        if save_path:
            absolute_path(save_path)
        inventory, complete = self.library_inventory()
        results, seen, validated = [], set(), []
        for item in items:
            if item.media_id in seen:
                continue
            seen.add(item.media_id)
            candidate = self.owner.take_candidate(
                item.candidate_key,
                artist_id=artist_id,
                kind="completion",
                media_id=item.media_id,
            )
            validated.append((item, candidate))
        for item, candidate in validated:
            artist_name = candidate["artist"]["name"]
            media = MusicInfo.from_dict(candidate["media"])
            if _library_state(media, inventory, complete) != "missing":
                results.append(
                    {
                        "media_id": item.media_id,
                        "state": "failed",
                        "error": "已存在或媒体库状态未知，未提交",
                    }
                )
                continue
            old = candidate["context"]
            context = Context(
                meta_info=old.meta_info, media_info=media, torrent_info=old.torrent_info
            )
            row = self._submit(context, downloader, save_path)
            row.update(role="supplement", media_id=item.media_id)
            results.append(row)
        return self.owner.save_job("completion", artist_id, artist_name, results)

    def _submit(
        self, context: Context, downloader: str | None, save_path: str | None
    ) -> dict:
        self.owner.require_enabled()
        try:
            result = self.download.download_single(
                context=context,
                source="MusicLibraryManager",
                downloader=downloader,
                save_path=save_path,
                return_detail=True,
            )
            download_id = result[0] if isinstance(result, tuple) else result
        except Exception:  # noqa: BLE001 - 记录提交失败，不向浏览器泄露下载票据
            logger.warning("音乐资源提交下载失败，详细原因请检查宿主下载日志")
            download_id = None
        return {
            "title": context.torrent_info.title,
            "state": "submitted" if download_id else "failed",
            "download_id": str(download_id) if download_id else None,
            "error": None if download_id else "提交失败，请检查宿主下载日志并重新搜索",
        }

    def torrent_tasks(self) -> list[dict]:
        rows = []
        for task in self.download.list_torrents(include_all_tags=True) or []:
            title = str(
                getattr(task, "title", None) or getattr(task, "name", None) or ""
            )
            if not re.search(
                r"(?:flac|wav|dsf|music|album|discography|合集|专辑)",
                title,
                re.IGNORECASE,
            ):
                continue
            rows.append(
                {
                    "hash": str(task.hash or ""),
                    "downloader": str(task.downloader or ""),
                    "title": title,
                    "save_path": str(task.save_path or task.path or ""),
                    "content_path": str(task.content_path or task.path or ""),
                    "state": str(task.state or ""),
                    "progress": float(getattr(task, "progress", 0) or 0),
                }
            )
        return rows

    def normalization_plan(self, request: Any) -> dict:
        """一期严格只读：即使宿主有改名接口，也不能绕过历史同步/恢复边界。"""
        if request.execute:
            raise HTTPException(
                status_code=409, detail="本版本仅支持预览，不修改下载器或源文件"
            )
        tasks = (
            self.download.list_torrents(
                hashs=[request.hash],
                downloader=request.downloader,
                include_all_tags=True,
            )
            or []
        )
        if len(tasks) != 1:
            raise HTTPException(status_code=409, detail="下载任务不存在或未唯一匹配")
        task = tasks[0]
        current_save = absolute_path(str(task.save_path or ""))
        current_content = absolute_path(str(task.content_path or ""))
        if current_content.parent != current_save:
            raise HTTPException(
                status_code=409, detail="内容路径不是保存目录的直接子项，不能规划根名"
            )
        files = (
            self.download.torrent_files(tid=request.hash, downloader=request.downloader)
            or []
        )
        paths = [str(item.name or "").replace("\\", "/") for item in files]
        root = current_content.name
        single = paths == [root]
        if not single and not (
            paths and all(path.startswith(f"{root}/") for path in paths)
        ):
            raise HTTPException(status_code=409, detail="任务不是单文件或单一根目录")
        artist, title = safe_component(request.artist), safe_component(request.title)
        proposed = "艺术家合集" if request.category == "Artist Collection" else title
        proposed += f" ({request.year})" if request.year else ""
        if single:
            proposed = f"{artist} - {proposed}{current_content.suffix}"
        target_save = (
            absolute_path(request.archive_root) / request.category / artist
            if request.archive_root
            else current_save
        )
        return {
            "hash": request.hash,
            "downloader": request.downloader,
            "current_save_path": current_save.as_posix(),
            "current_content_path": current_content.as_posix(),
            "target_save_path": target_save.as_posix(),
            "proposed_root_name": proposed,
            "target_content_path": (target_save / proposed).as_posix(),
            "move_required": current_save != target_save,
            "rename_required": root != proposed,
            "rename_supported": False,
            "executable": False,
            "executed": False,
            "message": "手工填写的命名规划；仅预览。MusicBrainz 自动识别、qB 最终校验及 MP 历史同步尚未开放。",
        }
