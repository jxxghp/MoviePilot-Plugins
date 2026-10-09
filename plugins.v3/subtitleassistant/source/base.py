"""字幕来源客户端基类：查询编排、缓存、去重与错误收敛的唯一实现点。"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import JsonValue

from app.core.cache import AsyncCache
from app.log import logger

from ..schemas.base import elapsed_ms, utc_now
from ..schemas.candidate import SubtitleCandidate
from ..schemas.source import (
    AssrtDownloadHandle,
    CandidateHandle,
    DownloadedAsset,
    MoviePilotDownloadHandle,
    OpenSubtitlesDownloadHandle,
    SourceErrorCode,
    SourceHealth,
    SourcePlanEntry,
    SourcePlanKind,
    SourceSearchResult,
    SourceSearchStatus,
    SourceStatus,
    SubtitleSource,
)
from ..schemas.target import SubtitleTarget
from .common import SourceLimitedError, SourceRequestError

SOURCE_CACHE_REGION = "subtitleassistant_source_query"
MAX_PAGINATION_PAGES = 1000
SOURCE_CACHE_TTL_SECONDS: dict[SubtitleSource, int] = {
    SubtitleSource.MOVIEPILOT: 10 * 60,
    SubtitleSource.OPENSUBTITLES: 30 * 60,
    SubtitleSource.ASSRT: 30 * 60,
}


@dataclass(frozen=True, slots=True, init=False)
class SourceQueryIdentity:
    """查询计划的不可变、可缓存 JSON 身份。"""

    encoded: str

    def __init__(self, value: Mapping[str, JsonValue]) -> None:
        """验证并冻结由来源计划提供的 JSON 请求身份。"""

        object.__setattr__(
            self,
            "encoded",
            json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )

    def get(self, key: str, default: JsonValue | None = None) -> JsonValue | None:
        """读取一个已冻结身份字段。"""

        return self.as_dict().get(key, default)

    def __getitem__(self, key: str) -> JsonValue:
        """以映射式只读访问身份字段。"""

        return self.as_dict()[key]

    def as_dict(self) -> dict[str, JsonValue]:
        """为 adapter 请求构造一个新的可变 JSON 副本。"""

        decoded = json.loads(self.encoded)
        if not isinstance(decoded, dict):
            raise SourceRequestError("来源查询身份结构无效", SourceErrorCode.INVALID_REQUEST)
        return cast(dict[str, JsonValue], decoded)


@dataclass(frozen=True, slots=True, init=False)
class SourcePlanQuery:
    """来源客户端生成的一项有序查询计划。"""

    label: str
    query: str | None
    identity: SourceQueryIdentity
    max_pages: int
    kind: SourcePlanKind

    def __init__(
        self,
        label: str,
        identity: Mapping[str, JsonValue] | SourceQueryIdentity | None = None,
        max_pages: int = MAX_PAGINATION_PAGES,
        kind: SourcePlanKind = "title",
        query: str | None = None,
    ) -> None:
        """创建冻结的来源查询计划项；query 为查询身份的实际参数（媒体 ID 或查询词）。"""

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "query", query)
        object.__setattr__(
            self,
            "identity",
            identity if isinstance(identity, SourceQueryIdentity) else SourceQueryIdentity(identity or {}),
        )
        object.__setattr__(self, "max_pages", max_pages)
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, slots=True)
class SourcePlan:
    """来源客户端提供的有序执行计划。"""

    queries: Sequence[SourcePlanQuery] = field(default_factory=tuple)
    configured: bool = True
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SourcePage:
    """来源客户端完成单页请求与归一化后返回的安全结果。"""

    candidates: list[CandidateHandle] = field(default_factory=list)
    raw_count: int = 0
    download_locator_excluded_count: int = 0
    malformed_count: int = 0
    has_next: bool = False


@dataclass(frozen=True, slots=True)
class SourceProbe:
    """健康探测返回的非默认结论，缺省字段沿用基类骨架推断。"""

    health: SourceHealth | None = None
    configured: bool | None = None
    error_summary: str | None = None


class SourceCachePort(Protocol):
    """来源基类所需的最小异步缓存协议。"""

    async def get(self, key: str, region: str | None = None) -> Any:
        """读取一个缓存值。"""

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        region: str | None = None,
    ) -> None:
        """写入一个带 TTL 的缓存值。"""


class SubtitleSourceBase(ABC):
    """字幕来源客户端基类：吸收分页循环、per-query 缓存、去重、错误收敛与健康骨架。"""

    source: SubtitleSource
    CACHE_TTL_SECONDS: int = 10 * 60

    def __init__(self, *, enabled: bool, cache: SourceCachePort | None = None) -> None:
        """保存构造期来源开关与共享缓存，运行中不再变更。"""

        self.enabled = enabled
        self._cache: SourceCachePort = cache if cache is not None else AsyncCache(cache_type="ttl", maxsize=512)
        self._last_details: dict[str, Any] = {}

    # ---- 外部表面（facade 与调用方所见）----

    @property
    @abstractmethod
    def configured(self) -> bool:
        """返回来源是否具备执行查询与下载所需的配置。"""

    async def search(self, context: SubtitleTarget, custom_query: str | None) -> SourceSearchResult:
        """模板方法：计划 → 逐查询（缓存读 → 分页 → 完整才写）→ 早停 → 去重 → 状态收敛。"""

        started = time.monotonic()
        source = self.source
        if not self.enabled:
            return self._result(source, "disabled", started)

        try:
            plan = self._plan(context, self._normalize_custom_query(custom_query))
            queries = list(plan.queries)
            configured = plan.configured
        except SourceLimitedError as exc:
            return self._result(
                source,
                "limited",
                started,
                error_summary=self._safe_error(exc),
                error_code=SourceErrorCode.LIMITED,
                retry_after_seconds=self._retry_after_seconds(exc),
            )
        except SourceRequestError as exc:
            return self._result(
                source,
                "error",
                started,
                error_summary=self._safe_error(exc),
                error_code=exc.error_code,
            )
        except Exception:  # noqa: BLE001 - 来源计划异常必须收敛为安全结果
            return self._result(source, "error", started, error_summary="字幕源查询计划生成失败")

        default_queries = self._plan_entries(plan)

        if not queries:
            return self._result(
                source,
                "success",
                started,
                skip_reason=plan.skip_reason or "query_unavailable",
                default_queries=default_queries,
            )

        if not configured:
            return self._result(source, "unconfigured", started, default_queries=default_queries)

        all_candidates: list[CandidateHandle] = []
        raw_count = 0
        excluded_count = 0
        malformed_count = 0
        cache_hit = False

        for query in queries:
            safe_label = self._safe_query_label(query.label)
            key = self._cache_key(source, query)
            cached = self._decode_cache(await self._read_cache(key), source, query)
            if cached is not None:
                handles, cached_raw, cached_excluded, cached_malformed = cached
                all_candidates.extend(handles)
                raw_count += cached_raw
                excluded_count += cached_excluded
                malformed_count += cached_malformed
                cache_hit = True
                if handles:
                    return self._result(
                        source,
                        "success",
                        started,
                        candidates=all_candidates,
                        raw_count=raw_count,
                        excluded_count=excluded_count,
                        malformed_count=malformed_count,
                        matched_query=safe_label,
                        cache_hit=True,
                        default_queries=default_queries,
                    )
                continue

            query_candidates: list[CandidateHandle] = []
            query_raw_count = 0
            query_excluded_count = 0
            query_malformed_count = 0
            page_number = 1
            pages_fetched = 0
            try:
                while True:
                    page = await self._fetch_page(query, page_number)
                    if not isinstance(page, SourcePage):
                        raise SourceRequestError("来源分页结果结构无效")
                    pages_fetched += 1
                    safe_candidates, invalid_count = self._safe_candidates(source, page.candidates)
                    query_candidates.extend(safe_candidates)
                    query_raw_count += max(0, int(page.raw_count))
                    query_excluded_count += max(0, int(page.download_locator_excluded_count)) + invalid_count
                    query_malformed_count += max(0, int(page.malformed_count))
                    if not page.has_next:
                        break
                    if pages_fetched >= min(query.max_pages, MAX_PAGINATION_PAGES):
                        raise SourceRequestError("来源分页超过安全上限")
                    page_number += 1
            except SourceLimitedError as exc:
                return self._converge_aborted(
                    started,
                    source,
                    "limited",
                    exc,
                    default_queries=default_queries,
                    pages_fetched=pages_fetched,
                    all_candidates=all_candidates,
                    query_candidates=query_candidates,
                    raw_count=raw_count,
                    query_raw_count=query_raw_count,
                    excluded_count=excluded_count,
                    query_excluded_count=query_excluded_count,
                    malformed_count=malformed_count,
                    query_malformed_count=query_malformed_count,
                    cache_hit=cache_hit,
                )
            except SourceRequestError as exc:
                return self._converge_aborted(
                    started,
                    source,
                    "error",
                    exc,
                    default_queries=default_queries,
                    pages_fetched=pages_fetched,
                    all_candidates=all_candidates,
                    query_candidates=query_candidates,
                    raw_count=raw_count,
                    query_raw_count=query_raw_count,
                    excluded_count=excluded_count,
                    query_excluded_count=query_excluded_count,
                    malformed_count=malformed_count,
                    query_malformed_count=query_malformed_count,
                    cache_hit=cache_hit,
                )
            except Exception:  # noqa: BLE001 - 来源请求异常必须收敛为安全结果
                return self._converge_aborted(
                    started,
                    source,
                    "error",
                    SourceRequestError("字幕源请求失败"),
                    default_queries=default_queries,
                    pages_fetched=pages_fetched,
                    all_candidates=all_candidates,
                    query_candidates=query_candidates,
                    raw_count=raw_count,
                    query_raw_count=query_raw_count,
                    excluded_count=excluded_count,
                    query_excluded_count=query_excluded_count,
                    malformed_count=malformed_count,
                    query_malformed_count=query_malformed_count,
                    cache_hit=cache_hit,
                )

            all_candidates.extend(query_candidates)
            raw_count += query_raw_count
            excluded_count += query_excluded_count
            malformed_count += query_malformed_count
            await self._write_cache(
                key, source, query_candidates, query_raw_count, query_excluded_count, query_malformed_count
            )

            if query_candidates:
                return self._result(
                    source,
                    "success",
                    started,
                    candidates=all_candidates,
                    raw_count=raw_count,
                    excluded_count=excluded_count,
                    malformed_count=malformed_count,
                    matched_query=safe_label,
                    cache_hit=cache_hit,
                    default_queries=default_queries,
                )

        return self._result(
            source,
            "success",
            started,
            candidates=all_candidates,
            raw_count=raw_count,
            excluded_count=excluded_count,
            malformed_count=malformed_count,
            cache_hit=cache_hit,
            default_queries=default_queries,
        )

    @abstractmethod
    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """下载来源候选字幕（各来源只写差异的领域逻辑）。"""

    async def refresh(self, manual: bool = False) -> SourceStatus:
        """模板方法：禁用短路 → 探测 → limited/error 分类 → 计时与 details 合并。"""

        status = SourceStatus(source=self.source, enabled=self.enabled, configured=self.configured)
        if not self.enabled or not self.configured:
            status.health = SourceHealth.DISABLED
            return status
        started = utc_now()
        status.last_checked_at = started
        try:
            probe = await self._probe(manual)
            if probe is not None:
                if probe.configured is not None:
                    status.configured = probe.configured
                if probe.health is not None:
                    status.health = probe.health
                if probe.error_summary is not None:
                    status.last_error_summary = probe.error_summary
            if status.health is SourceHealth.PENDING:
                status.health = SourceHealth.HEALTHY
            if status.health is SourceHealth.HEALTHY:
                status.last_success_at = utc_now()
        except SourceLimitedError as exc:
            status.health = SourceHealth.LIMITED
            status.last_error_at = utc_now()
            status.last_error_summary = str(exc)
        except SourceRequestError as exc:
            status.health = SourceHealth.ERROR
            status.last_error_at = utc_now()
            status.last_error_summary = str(exc)
        except Exception:  # noqa: BLE001 - 外部字幕源异常必须收敛为安全状态
            status.health = SourceHealth.ERROR
            status.last_error_at = utc_now()
            status.last_error_summary = "字幕源状态刷新失败"
        status.details = self.runtime_details()
        status.last_duration_ms = elapsed_ms(started)
        return status

    def default_queries(self, context: SubtitleTarget) -> list[SourcePlanEntry]:
        """返回前端展示使用的来源默认查询计划条目（计划展示唯一真源）。"""

        return self._plan_entries(self._plan(context, None))

    @staticmethod
    def _plan_entries(plan: SourcePlan) -> list[SourcePlanEntry]:
        """把来源 adapter 计划投影为展示条目，供 default_queries 与 search 共用。"""

        return [
            SourcePlanEntry(
                kind=item.kind,
                label=item.label,
                query=item.query or item.label,
                editable=True,
            )
            for item in plan.queries
            if item.label
        ]

    def runtime_details(self) -> dict[str, Any]:
        """返回非敏感运行观测。"""

        return dict(self._last_details)

    async def close(self) -> None:
        """释放来源运行资源，默认无资源可释放。"""

        return

    # ---- 内部接缝（各来源只写这三个，纯领域逻辑）----

    @abstractmethod
    def _plan(self, context: SubtitleTarget, custom_query: str | None) -> SourcePlan:
        """根据媒体上下文与自定义词生成有序查询计划。"""

    @abstractmethod
    async def _fetch_page(self, query: SourcePlanQuery, page: int) -> SourcePage:
        """执行一次来源请求并归一化为安全候选页（原 execute + normalize 合并）。"""

    @abstractmethod
    async def _probe(self, manual: bool) -> SourceProbe | None:
        """健康探测：正常返回可选结论，限流/错误以异常表达。"""

    # ---- 内部实现细节 ----

    def _converge_aborted(
        self,
        started: float,
        source: SubtitleSource,
        base_status: str,
        error: SourceRequestError,
        *,
        default_queries: list[SourcePlanEntry],
        pages_fetched: int,
        all_candidates: list[CandidateHandle],
        query_candidates: list[CandidateHandle],
        raw_count: int,
        query_raw_count: int,
        excluded_count: int,
        query_excluded_count: int,
        malformed_count: int,
        query_malformed_count: int,
        cache_hit: bool,
    ) -> SourceSearchResult:
        """把查询中断收敛为 partial（已取得分页）或基础状态（未取得分页）。"""

        if isinstance(error, SourceLimitedError):
            error_code = SourceErrorCode.LIMITED
            retry_after = self._retry_after_seconds(error)
        else:
            error_code = error.error_code
            retry_after = None
        if pages_fetched:
            return self._result(
                source,
                "partial",
                started,
                candidates=all_candidates + query_candidates,
                raw_count=raw_count + query_raw_count,
                excluded_count=excluded_count + query_excluded_count,
                malformed_count=malformed_count + query_malformed_count,
                cache_hit=cache_hit,
                error_summary=self._safe_error(error),
                error_code=error_code,
                retry_after_seconds=retry_after,
                default_queries=default_queries,
            )
        return self._result(
            source,
            base_status,
            started,
            candidates=all_candidates,
            raw_count=raw_count,
            excluded_count=excluded_count,
            malformed_count=malformed_count,
            cache_hit=cache_hit,
            error_summary=self._safe_error(error),
            error_code=error_code,
            retry_after_seconds=retry_after,
            default_queries=default_queries,
        )

    @staticmethod
    def _normalize_custom_query(value: str | None) -> str | None:
        """清理空白自定义关键词，避免空词替换默认计划。"""

        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _safe_query_label(value: str) -> str:
        """把查询摘要限制为可安全记录的单行文本。"""

        return " ".join(str(value).split())[:256]

    @staticmethod
    def _safe_error(error: SourceRequestError) -> str:
        """把约定的安全错误限制为单行文本。"""

        return " ".join(str(error).split())[:256] or "字幕源请求失败"

    @staticmethod
    def _retry_after_seconds(error: SourceLimitedError) -> int | None:
        """把预计恢复时间换算为剩余秒数。"""

        if not error.retry_at:
            return None
        return max(0, int((error.retry_at - utc_now()).total_seconds()))

    @staticmethod
    def _cache_key(source: SubtitleSource, query: SourcePlanQuery) -> str:
        """根据来源和结构化查询身份生成缓存键。"""

        payload = {
            "source": source.value,
            "query": query.identity.encoded,
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"{source.value}:{digest}"

    async def _read_cache(self, key: str) -> Any:
        """读取缓存失败时按未命中继续远端查询。"""

        try:
            return await self._cache.get(key, region=SOURCE_CACHE_REGION)
        except Exception:  # noqa: BLE001 - 缓存异常不得改变来源查询结果
            return None

    async def _write_cache(
        self,
        key: str,
        source: SubtitleSource,
        candidates: list[CandidateHandle],
        raw_count: int,
        excluded_count: int,
        malformed_count: int,
    ) -> None:
        """把一次完整来源查询的候选写入缓存，失败时保持业务成功。"""

        value = {
            "source": source.value,
            "handles": [
                {
                    "candidate": handle.candidate.model_dump(mode="json"),
                    "download_handle": self._encode_download_handle(handle),
                }
                for handle in candidates
            ],
            "raw_count": max(0, raw_count),
            "download_locator_excluded_count": max(0, excluded_count),
            "malformed_count": max(0, malformed_count),
        }
        try:
            await self._cache.set(key, value, ttl=self.CACHE_TTL_SECONDS, region=SOURCE_CACHE_REGION)
        except Exception:  # noqa: BLE001 - 缓存写入失败不得改变业务结果
            return

    @staticmethod
    def _encode_download_handle(handle: CandidateHandle) -> dict[str, Any]:
        """将强类型句柄编码为来源白名单字段。"""

        value = handle.download_handle
        if isinstance(value, MoviePilotDownloadHandle):
            return {"site_id": value.site_id, "enclosure": value.enclosure}
        if isinstance(value, OpenSubtitlesDownloadHandle):
            return {"file_id": value.file_id}
        if isinstance(value, AssrtDownloadHandle):
            return {"id": value.subtitle_id}
        raise TypeError("未知下载句柄类型")

    @staticmethod
    def _decode_cache(
        value: Any,
        source: SubtitleSource,
        query: SourcePlanQuery,
    ) -> tuple[list[CandidateHandle], int, int, int] | None:
        """运行时校验并解码缓存值，畸形值按未命中处理。"""

        if not isinstance(value, dict):
            return None
        if value.get("source") != source.value:
            return None
        encoded_handles = value.get("handles")
        if not isinstance(encoded_handles, list):
            return None
        handles: list[CandidateHandle] = []
        for item in encoded_handles:
            if not isinstance(item, dict) or "candidate" not in item or "download_handle" not in item:
                return None
            try:
                handle = CandidateHandle(
                    candidate=SubtitleCandidate.model_validate_json(json.dumps(item["candidate"], ensure_ascii=False)),
                    download_handle=SubtitleSourceBase._decode_download_handle(source, item["download_handle"]),
                )
            except (KeyError, TypeError, ValueError):
                return None
            if handle.candidate.source is not source or not SubtitleSourceBase._valid_handle(handle):
                return None
            handles.append(handle)
        raw_count = SubtitleSourceBase._cache_count(value.get("raw_count"))
        excluded_count = SubtitleSourceBase._cache_count(value.get("download_locator_excluded_count"))
        malformed_count = SubtitleSourceBase._cache_count(value.get("malformed_count"))
        if raw_count is None or excluded_count is None or malformed_count is None:
            return None
        return handles, raw_count, excluded_count, malformed_count

    @staticmethod
    def _decode_download_handle(source: SubtitleSource, value: Any) -> Any:
        """仅从缓存白名单字段重建强类型下载句柄。"""

        if not isinstance(value, Mapping):
            raise TypeError("缓存下载句柄无效")
        if source is SubtitleSource.MOVIEPILOT:
            return MoviePilotDownloadHandle(site_id=int(value["site_id"]), enclosure=str(value["enclosure"]))
        if source is SubtitleSource.OPENSUBTITLES:
            return OpenSubtitlesDownloadHandle(file_id=int(value["file_id"]))
        return AssrtDownloadHandle(subtitle_id=int(value["id"]))

    @staticmethod
    def _cache_count(value: Any) -> int | None:
        """校验缓存中的非负计数。"""

        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    @staticmethod
    def _safe_candidates(
        source: SubtitleSource,
        candidates: Sequence[CandidateHandle],
    ) -> tuple[list[CandidateHandle], int]:
        """只保留来源一致且具有内部下载定位的候选句柄。"""

        result: list[CandidateHandle] = []
        invalid_count = 0
        for handle in candidates:
            if handle.candidate.source is not source or not SubtitleSourceBase._valid_handle(handle):
                invalid_count += 1
            else:
                result.append(handle)
        return result, invalid_count

    @staticmethod
    def _valid_handle(handle: CandidateHandle) -> bool:
        """验证句柄仍为强类型白名单值。"""

        return isinstance(
            handle.download_handle,
            (
                MoviePilotDownloadHandle,
                OpenSubtitlesDownloadHandle,
                AssrtDownloadHandle,
            ),
        )

    @staticmethod
    def _result(
        source: SubtitleSource,
        status: str,
        started: float,
        *,
        candidates: list[CandidateHandle] | None = None,
        raw_count: int = 0,
        excluded_count: int = 0,
        malformed_count: int = 0,
        matched_query: str | None = None,
        cache_hit: bool = False,
        error_summary: str | None = None,
        error_code: SourceErrorCode | None = None,
        retry_after_seconds: int | None = None,
        skip_reason: str | None = None,
        default_queries: list[SourcePlanEntry] | None = None,
    ) -> SourceSearchResult:
        """构造来源查询最小安全结果；原始/排除/畸形计数只进日志。"""

        safe_candidates = list(candidates or [])
        deduplicated = list({item.candidate.candidate_key: item for item in reversed(safe_candidates)}.values())
        deduplicated.reverse()
        logger.debug(
            f"{source.value} 来源查询计数：原始 {max(0, raw_count)}，"
            f"排除 {max(0, excluded_count)}，畸形 {max(0, malformed_count)}，候选 {len(deduplicated)}"
        )
        return SourceSearchResult(
            source=source,
            status=SourceSearchStatus(status),
            candidates=deduplicated,
            matched_query=matched_query,
            cache_hit=cache_hit,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error_summary=error_summary,
            error_code=error_code,
            retry_after_seconds=retry_after_seconds,
            skip_reason=skip_reason,
            default_queries=list(default_queries or []),
        )
