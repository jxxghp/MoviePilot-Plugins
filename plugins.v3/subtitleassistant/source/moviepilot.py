"""MoviePilot 站点字幕源适配器。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.chain.search import SearchChain
from app.core.config import settings
from app.db.site_oper import SiteOper
from app.db.systemconfig_oper import SystemConfigOper

# SitesHelper 由 MoviePilot 的动态站点资源提供，基础源码树不包含该模块。
from app.helper.sites import SitesHelper  # ty: ignore[unresolved-import]
from app.log import logger
from app.schemas.types import SystemConfigKey
from app.utils.http import AsyncRequestUtils

from ..schemas.candidate import SubtitleCandidate, TranslationType
from ..schemas.source import (
    CandidateHandle,
    DownloadedAsset,
    MoviePilotDownloadHandle,
    SourceHealth,
    SubtitleSource,
)
from ..schemas.target import SubtitleTarget
from .base import (
    SourceCachePort,
    SourcePage,
    SourcePlan,
    SourcePlanQuery,
    SourceProbe,
    SubtitleSourceBase,
)
from .common import (
    SourceRequestError,
    _proxy_kwargs,
    download_file,
    parse_datetime,
    safe_file_name,
    subtitle_format,
)


class _MoviePilotRawPage(BaseModel):
    """MoviePilot adapter 私有的宿主原始搜索结果 envelope。"""

    model_config = ConfigDict(extra="forbid", strict=True, arbitrary_types_allowed=True)

    items: list[object] = Field(default_factory=list)


class _MoviePilotRawItem(BaseModel):
    """MoviePilot 宿主候选的私有属性边界模型。"""

    model_config = ConfigDict(extra="ignore", strict=True, from_attributes=True)

    site: int | str | None = None
    enclosure: str | None = None
    subtitle_id: int | str | None = None
    torrent_id: int | str | None = None
    title: str | None = None
    file_name: str | None = None
    description: str | None = None
    language: str | None = None
    site_order: int | str | None = None
    grabs: int | str | None = None
    pubdate: str | None = None
    site_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _require_host_candidate_shape(cls, value: object) -> object:
        """拒绝既非宿主候选也非测试替身的畸形条目。"""

        if isinstance(value, dict) or hasattr(value, "site") or hasattr(value, "title"):
            return value
        raise ValueError("MoviePilot 候选缺少宿主字段")


def _create_keyword_extractor() -> Any | None:
    """创建轻量 YAKE 英文单词提取器，依赖缺失时返回空。"""

    try:
        import yake  # type: ignore[import-not-found]
    except ImportError:
        return None
    return yake.KeywordExtractor(lan="en", n=1, top=12)


class MoviePilotSource(SubtitleSourceBase):
    """只调用宿主标题搜索接口并在下载前重新读取站点配置。"""

    source = SubtitleSource.MOVIEPILOT
    CACHE_TTL_SECONDS = 10 * 60

    def __init__(self, enabled: bool, cache: SourceCachePort | None = None) -> None:
        """创建 MoviePilot 站点来源适配器。"""

        super().__init__(enabled=enabled, cache=cache)

    @property
    def configured(self) -> bool:
        """MoviePilot 站点源不需要插件外部凭据。"""

        return True

    @staticmethod
    def _field(item: Any, name: str, default: Any = None) -> Any:
        """兼容宿主字幕 dataclass 与测试替身的属性读取。"""

        return getattr(item, name, default)

    @staticmethod
    def _integer(value: Any) -> int | None:
        """把宿主可空数值字段安全转换为整数。"""

        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _candidate_key(item: Any) -> str:
        """构造不包含原始下载链接的稳定来源键。"""

        site = MoviePilotSource._field(item, "site")
        subtitle_id = MoviePilotSource._field(item, "subtitle_id")
        torrent_id = MoviePilotSource._field(item, "torrent_id")
        if subtitle_id not in (None, ""):
            return f"moviepilot:{site}:subtitle:{subtitle_id}"
        if torrent_id not in (None, ""):
            return f"moviepilot:{site}:torrent:{torrent_id}"
        payload = {
            "site": site,
            "title": MoviePilotSource._field(item, "title", ""),
            "file_name": MoviePilotSource._field(item, "file_name", ""),
        }
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()
        return f"moviepilot:sha256:{digest}"

    def _normalize_pool(self, item: Any, query: str) -> CandidateHandle | None:
        """把宿主字幕对象转换为自动过滤前的来源候选池项。"""

        site_id = self._integer(self._field(item, "site"))
        enclosure = self._field(item, "enclosure")
        if site_id is None or not isinstance(enclosure, str) or not enclosure:
            return None
        file_name = self._field(item, "file_name")
        title = str(self._field(item, "title", "MoviePilot 字幕") or "MoviePilot 字幕")
        description = str(self._field(item, "description", "") or "")
        marker = f"{title} {description}".casefold()
        translation = TranslationType.UNKNOWN
        if "机器翻译" in marker or "machine translated" in marker:
            translation = TranslationType.MACHINE
        elif "ai翻译" in marker or "ai translated" in marker:
            translation = TranslationType.AI
        candidate = SubtitleCandidate(
            candidate_key=self._candidate_key(item),
            source=self.source,
            name=title,
            file_name=str(file_name or "") or None,
            format=subtitle_format(str(file_name or "")) or "UNKNOWN",
            language=str(self._field(item, "language", "") or ""),
            translation_type=translation,
            hearing_impaired=any(token in marker for token in ("sdh", "cc", "听障")),
            foreign_parts_only=any(token in marker for token in ("foreign_parts_only", "foreign parts only", "仅外语")),
            site_id=site_id,
            site_priority=self._integer(self._field(item, "site_order")),
            download_count=self._integer(self._field(item, "grabs")),
            uploaded_at=parse_datetime(self._field(item, "pubdate"), "%Y-%m-%d %H:%M:%S"),
            metadata={
                "description": description,
                "site_name": self._field(item, "site_name", ""),
                "actual_query": query,
            },
        )
        return CandidateHandle(
            candidate=candidate,
            download_handle=MoviePilotDownloadHandle(site_id=site_id, enclosure=enclosure),
        )

    @staticmethod
    def _default_queries(context: SubtitleTarget) -> tuple[list[str], str | None]:
        """从英文标题提取最多三个不重复的英文单词。"""

        title = (context.english_title or "").strip()
        if not title:
            return [], "english_title_missing"
        extractor = _create_keyword_extractor()
        if extractor is None:
            return [], "yake_unavailable"
        try:
            ranked = extractor.extract_keywords(title)
        except Exception:  # noqa: BLE001 - 第三方关键词提取失败必须降级
            return [], "keyword_extraction_failed"
        queries: list[str] = []
        seen: set[str] = set()
        for keyword, _score in ranked:
            value = str(keyword).strip()
            normalized = value.casefold()
            if not re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)*", value) or normalized in seen:
                continue
            seen.add(normalized)
            queries.append(value)
            if len(queries) == 3:
                break
        return queries, None if queries else "keyword_extraction_empty"

    async def _subtitle_site_indexers(self) -> list[dict[str, Any]]:
        """返回当前启用且声明支持字幕搜索的宿主索引站点。"""

        enabled_sites = SystemConfigOper().get(SystemConfigKey.IndexerSites) or []
        result: list[dict[str, Any]] = []
        for indexer in await SitesHelper().async_get_indexers():
            if not indexer.get("subtitles"):
                continue
            if not enabled_sites or indexer.get("id") in enabled_sites:
                result.append(indexer)
        return result

    def _sync_subtitle_site_ids(self) -> tuple[int, ...]:
        """读取宿主本地站点快照，为查询计划预先固定缓存身份。"""

        get_indexers = getattr(SitesHelper(), "get_indexers", None)
        if not callable(get_indexers):
            return ()
        try:
            enabled_sites = SystemConfigOper().get(SystemConfigKey.IndexerSites) or []
            indexers = get_indexers()
            site_ids = [
                int(indexer["id"])
                for indexer in indexers
                if indexer.get("subtitles")
                and (not enabled_sites or indexer.get("id") in enabled_sites)
                and indexer.get("id") is not None
            ]
        except Exception:  # noqa: BLE001 - 本地站点快照不可用时交给异步查询确认
            return ()
        return tuple(sorted(site_ids))

    def _plan(self, context: SubtitleTarget, custom_query: str | None) -> SourcePlan:
        """根据媒体上下文生成 MoviePilot 默认或自定义查询计划。"""

        site_ids = self._sync_subtitle_site_ids()
        default_queries, skip_reason = self._default_queries(context)
        custom = (custom_query or "").strip()
        labels = [custom] if custom else default_queries
        queries = [
            SourcePlanQuery(
                label=label,
                identity={"title": label},
                max_pages=1,
                kind="filename" if custom else "title",
                query=label,
            )
            for label in labels
        ]
        return SourcePlan(
            queries=queries,
            configured=bool(site_ids),
            skip_reason=skip_reason,
        )

    async def _fetch_page(self, query: SourcePlanQuery, page: int) -> SourcePage:
        """执行一次 MoviePilot 原生标题查询并归一化为安全候选页。"""

        indexers = await self._subtitle_site_indexers()
        site_ids = sorted(int(indexer["id"]) for indexer in indexers if indexer.get("id") is not None)
        if not site_ids:
            return SourcePage()
        logger.info(f"开始查询 MoviePilot 站点字幕源，查询词为“{query.label}”")
        items = await SearchChain().async_search_subtitles_by_title(
            title=query.label,
            page=max(0, page - 1),
            sites=site_ids,
            cache_local=False,
        )
        try:
            raw_page = _MoviePilotRawPage.model_validate({"items": list(items or [])})
        except ValidationError as exc:
            raise SourceRequestError("MoviePilot 响应结构无效") from exc
        page_result = self._normalize_page(raw_page.items, query.label)
        logger.info(
            f"MoviePilot 站点字幕源查询“{query.label}”完成，共返回 {page_result.raw_count} 个结果，"
            f"其中 {len(page_result.candidates)} 个具备下载定位"
        )
        return page_result

    def _normalize_page(self, items: list[object], query: str) -> SourcePage:
        """把一页宿主结果转换为共享候选池可接受的安全结果。"""

        handles: list[CandidateHandle] = []
        raw_count = 0
        excluded = 0
        malformed_count = 0
        for value in items:
            try:
                item = _MoviePilotRawItem.model_validate(value, from_attributes=True)
            except ValidationError:
                malformed_count += 1
                continue
            handle = self._normalize_pool(item, query)
            if handle is None:
                excluded += 1
            else:
                handles.append(handle)
                raw_count += 1
        return SourcePage(
            candidates=handles,
            raw_count=raw_count,
            download_locator_excluded_count=excluded,
            malformed_count=malformed_count,
        )

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """按站点 ID 重新水合凭据后下载候选字幕。"""

        if not isinstance(handle.download_handle, MoviePilotDownloadHandle):
            raise SourceRequestError("MoviePilot 候选缺少有效下载句柄")
        site_id = handle.download_handle.site_id
        enclosure = handle.download_handle.enclosure
        site = await SiteOper().async_get(site_id)
        if not site or not bool(getattr(site, "is_active", False)):
            raise SourceRequestError("MoviePilot 字幕站点不存在或已停用")
        request_options: dict[str, Any] = {
            "cookies": getattr(site, "cookie", None),
            "ua": getattr(site, "ua", None) or settings.USER_AGENT,
            "timeout": getattr(site, "timeout", None) or 20,
            **_proxy_kwargs(settings.PROXY if bool(getattr(site, "proxy", False)) else None),
        }
        request = AsyncRequestUtils(**request_options)
        fallback_name = safe_file_name(
            handle.candidate.file_name,
            f"moviepilot-{handle.candidate.candidate_key.rsplit(':', 1)[-1]}.bin",
        )
        path = await download_file(
            request,
            enclosure,
            directory,
            fallback_name,
            prefer_response_name=True,
        )
        return DownloadedAsset(path=path, file_name=path.name)

    async def _probe(self, manual: bool) -> SourceProbe | None:
        """重新读取宿主当前有效站点列表，不发起测试搜索。"""

        del manual
        indexers = await self._subtitle_site_indexers()
        site_names = [str(indexer.get("name") or indexer.get("domain") or indexer.get("id")) for indexer in indexers]
        self._last_details = {
            "site_names": site_names,
            "site_count": len(site_names),
            **{
                key: value
                for key, value in self._last_details.items()
                if key in {"site_candidate_counts", "candidate_total", "last_search_at"}
            },
        }
        if site_names:
            return None
        return SourceProbe(
            health=SourceHealth.DISABLED,
            configured=False,
            error_summary="没有启用且支持字幕搜索的站点",
        )
