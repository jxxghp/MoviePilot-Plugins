"""ASSRT 标题搜索字幕源。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.core.config import settings
from app.utils.http import AsyncRequestUtils

from ..schemas.base import utc_now
from ..schemas.candidate import PackageScope, SubtitleCandidate, TranslationType
from ..schemas.source import (
    AssrtDownloadHandle,
    CandidateHandle,
    DownloadedAsset,
    SourceErrorCode,
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
    SourceLimitedError,
    SourceRequestError,
    _proxy_kwargs,
    download_file,
    parse_datetime,
    raise_for_status,
    safe_file_name,
    subtitle_format,
)
from .limiter import SlidingWindowLimiter


class _AssrtRawPage(BaseModel):
    """ASSRT adapter 私有的原始响应 envelope。"""

    model_config = ConfigDict(extra="ignore", strict=True)

    status: int
    sub: dict[str, JsonValue] = Field(default_factory=dict)


class _AssrtRawItem(BaseModel):
    """ASSRT 单项原始候选的私有校验模型。"""

    model_config = ConfigDict(extra="ignore", strict=True)

    id: int | str | None = None
    revision: int | str | None = None
    native_name: str | None = None
    videoname: str | None = None
    subtype: str | None = None
    lang: dict[str, JsonValue] | None = None
    vote_machine_translate: JsonValue | None = None
    vote_score: int | float | str | None = None
    upload_time: str | None = None


class AssrtSource(SubtitleSourceBase):
    """统一按标题执行最多两轮搜索的 ASSRT 来源。"""

    source = SubtitleSource.ASSRT
    BASE_URL = "https://api.assrt.net/v1"
    CACHE_TTL_SECONDS = 30 * 60

    def __init__(
        self,
        enabled: bool,
        credentials: dict[str, str],
        cache: SourceCachePort | None = None,
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        """创建 ASSRT 来源适配器。"""

        super().__init__(enabled=enabled, cache=cache)
        self._token = credentials.get("token", "").strip()
        self._limiter = limiter or SlidingWindowLimiter(limit=20, window_seconds=60)
        self._last_details: dict[str, Any] = {"attribution": "https://assrt.net"}

    @property
    def configured(self) -> bool:
        """判断 ASSRT Token 是否已配置。"""

        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        """构造使用 Bearer Token 的 ASSRT 请求头。"""

        return {"Accept": "application/json", "Authorization": f"Bearer {self._token}"}

    def _default_queries(self, context: SubtitleTarget) -> list[str]:
        """构造中文标题、英文标题最多两轮且不重复的默认查询。"""

        primary = context.title.strip()
        alternate = next(
            (
                item.strip()
                for item in (context.english_title, context.original_title)
                if isinstance(item, str) and item.strip() and item.strip().casefold() != primary.casefold()
            ),
            "",
        )
        return [item for item in (primary, alternate) if len(item) >= 4]

    def _plan(self, context: SubtitleTarget, custom_query: str | None) -> SourcePlan:
        """根据标题回退或来源自定义关键词生成有序查询计划。"""

        defaults = self._default_queries(context)
        custom = (custom_query or "").strip()
        labels = [custom] if len(custom) >= 4 else [] if custom else defaults
        queries = [
            SourcePlanQuery(
                label=label,
                identity={"path": "sub/search", "params": {"q": label, "cnt": 15, "pos": 0}},
                max_pages=1,
                kind="title" if index == 0 else "fallback",
                query=label,
            )
            for index, label in enumerate(labels)
        ]
        return SourcePlan(
            queries=queries,
            configured=self.configured,
            skip_reason="keyword_too_short" if custom and len(custom) < 4 else None,
        )

    async def _request_json(
        self,
        path: str,
        params: dict[str, Any],
        wait: bool,
    ) -> dict[str, Any]:
        """经过统一限流器请求并校验 ASSRT 顶层状态。"""

        retry_at = await self._limiter.acquire(wait=wait)
        if retry_at is not None:
            raise SourceLimitedError("ASSRT 分钟请求额度暂时受限", retry_at=retry_at)
        request = AsyncRequestUtils(headers=self._headers(), **_proxy_kwargs(settings.PROXY))
        response = await request.get_res(f"{self.BASE_URL}/{path}", params=params)
        try:
            if response is None:
                raise SourceRequestError("ASSRT 请求失败")
            if response.status_code == 429:
                limited_until = await self._limiter.mark_limited()
                raise SourceLimitedError("ASSRT 分钟请求额度暂时受限", retry_at=limited_until)
            raise_for_status(response, context="ASSRT ", limited_codes=frozenset())
            payload = response.json()
            if not isinstance(payload, dict):
                raise SourceRequestError("ASSRT 响应结构无效", SourceErrorCode.MALFORMED_RESPONSE)
            status = int(payload.get("status", -1))
            if status == 30900:
                limited_until = await self._limiter.mark_limited()
                raise SourceLimitedError("ASSRT 分钟请求额度暂时受限", retry_at=limited_until)
            if status != 0:
                raise SourceRequestError("ASSRT 返回错误状态", SourceErrorCode.INVALID_REQUEST)
            self._last_details["last_request_at"] = utc_now().isoformat()
            return payload
        except ValueError as exc:
            raise SourceRequestError("ASSRT 响应无法解析", SourceErrorCode.MALFORMED_RESPONSE) from exc
        finally:
            if response is not None:
                await response.aclose()

    async def _fetch_page(self, query: SourcePlanQuery, page: int) -> SourcePage:
        """执行一次 ASSRT 请求并归一化为安全候选页。"""

        if page != 1:
            raise SourceRequestError("ASSRT 不支持多页查询")
        path = query.identity.get("path")
        params = query.identity.get("params")
        if not isinstance(path, str) or not isinstance(params, dict):
            raise SourceRequestError("ASSRT 查询参数无效")
        try:
            payload = await self._request_json(path, dict(params), wait=True)
        except SourceLimitedError as exc:
            if exc.retry_at:
                self._last_details["limited_until"] = exc.retry_at.isoformat()
            raise
        try:
            raw_page = _AssrtRawPage.model_validate(payload)
        except ValidationError as exc:
            raise SourceRequestError("ASSRT 响应结构无效", SourceErrorCode.MALFORMED_RESPONSE) from exc
        handles, raw_count, rejected, malformed_count = self._normalize_pool(raw_page.model_dump(), query)
        return SourcePage(
            candidates=handles,
            raw_count=raw_count,
            download_locator_excluded_count=rejected.get("download_locator", 0),
            malformed_count=malformed_count,
        )

    def _normalize_pool(
        self,
        payload: dict[str, Any],
        query: SourcePlanQuery,
    ) -> tuple[list[CandidateHandle], int, dict[str, int], int]:
        """归一化自动规则之前的 ASSRT 来源候选池。"""

        result: list[CandidateHandle] = []
        raw_count = 0
        rejected: dict[str, int] = {}
        malformed_count = 0
        sub = payload.get("sub") or {}
        if not isinstance(sub, dict):
            return result, raw_count, rejected, 1
        subs = sub.get("subs") or []
        if not isinstance(subs, list):
            return result, raw_count, rejected, 1
        for item_value in subs:
            try:
                item = _AssrtRawItem.model_validate(item_value).model_dump()
            except ValidationError:
                malformed_count += 1
                continue
            try:
                subtitle_id = int(item.get("id"))
            except (TypeError, ValueError):
                rejected["download_locator"] = rejected.get("download_locator", 0) + 1
                continue
            if subtitle_id <= 0:
                rejected["download_locator"] = rejected.get("download_locator", 0) + 1
                continue
            raw_count += 1
            language_data = item.get("lang") or {}
            marker = str(language_data.get("desc") or "")
            flags = language_data.get("langlist") if isinstance(language_data.get("langlist"), dict) else {}
            machine_vote = item.get("vote_machine_translate")
            translation = (
                TranslationType.MACHINE if machine_vote not in (None, False, 0, "0", "") else TranslationType.UNKNOWN
            )
            try:
                revision = int(item.get("revision") or 0)
            except (TypeError, ValueError):
                revision = 0
            candidate = SubtitleCandidate(
                candidate_key=f"assrt:{subtitle_id}:{revision}",
                source=self.source,
                name=str(item.get("native_name") or item.get("videoname") or subtitle_id),
                file_name=None,
                format=subtitle_format(None, str(item.get("subtype") or "")) or "UNKNOWN",
                language=marker,
                translation_type=translation,
                package_scope=PackageScope.UNKNOWN,
                score=float(item.get("vote_score") or 0),
                uploaded_at=parse_datetime(item.get("upload_time"), "%Y-%m-%d %H:%M:%S"),
                revision=revision,
                metadata={
                    "videoname": str(item.get("videoname") or ""),
                    "native_name": str(item.get("native_name") or ""),
                    "description": str(item.get("videoname") or ""),
                    "actual_query": query.label,
                    "language_flags": flags,
                },
            )
            result.append(
                CandidateHandle(
                    candidate=candidate,
                    download_handle=AssrtDownloadHandle(subtitle_id=subtitle_id),
                )
            )
        return result, raw_count, rejected, malformed_count

    async def _probe(self, manual: bool) -> SourceProbe | None:
        """查询 ASSRT 配额并服从统一分钟限流。"""

        try:
            payload = await self._request_json("user/quota", {}, wait=not manual)
        except SourceLimitedError as exc:
            if exc.retry_at:
                self._last_details["limited_until"] = exc.retry_at.isoformat()
            raise
        except Exception as exc:
            raise SourceRequestError("ASSRT 配额检查失败") from exc
        quota = (payload.get("user") or {}).get("quota")
        self._last_details.update({"quota": quota, "limited_until": None})
        return None

    async def _detail(self, subtitle_id: int) -> dict[str, Any]:
        """下载前请求最新字幕详情。"""

        payload = await self._request_json("sub/detail", {"id": subtitle_id}, wait=True)
        subs = (payload.get("sub") or {}).get("subs") or []
        detail = next(
            (item for item in subs if isinstance(item, dict) and int(item.get("id") or 0) == subtitle_id), None
        )
        if not detail:
            raise SourceRequestError("ASSRT 详情缺少目标字幕")
        return detail

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """请求最新详情并优先下载完整候选包。"""

        if not isinstance(handle.download_handle, AssrtDownloadHandle):
            raise SourceRequestError("ASSRT 候选缺少有效下载句柄")
        subtitle_id = handle.download_handle.subtitle_id
        detail = await self._detail(subtitle_id)
        url = detail.get("url")
        if not isinstance(url, str) or not url:
            raise SourceRequestError("ASSRT 详情缺少临时下载链接")
        file_name = safe_file_name(detail.get("filename"), f"assrt-{subtitle_id}.bin")
        path = await download_file(AsyncRequestUtils(**_proxy_kwargs(settings.PROXY)), url, directory, file_name)
        return DownloadedAsset(path=path, file_name=file_name)
