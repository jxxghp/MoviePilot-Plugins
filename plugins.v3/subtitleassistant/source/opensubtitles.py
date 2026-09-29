"""OpenSubtitles.com REST API 字幕源。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.core.config import settings
from app.utils.http import AsyncRequestUtils

from ..schemas.base import utc_now
from ..schemas.candidate import PackageScope, SubtitleCandidate, TranslationType
from ..schemas.source import (
    CandidateHandle,
    DownloadedAsset,
    OpenSubtitlesDownloadHandle,
    SourceErrorCode,
    SubtitleSource,
)
from ..schemas.target import MediaType, SubtitleTarget
from .base import (
    SourceCachePort,
    SourcePage,
    SourcePlan,
    SourcePlanKind,
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
    safe_file_name,
    subtitle_format,
)


class _OpenSubtitlesRawPage(BaseModel):
    """OpenSubtitles adapter 私有的原始分页 envelope。"""

    model_config = ConfigDict(extra="ignore", strict=True)

    data: list[JsonValue] = Field(default_factory=list)
    total_pages: int | None = None


class _OpenSubtitlesRawItem(BaseModel):
    """OpenSubtitles 单项原始候选的私有校验模型。"""

    model_config = ConfigDict(extra="ignore", strict=True)

    id: int | str | None = None
    attributes: dict[str, JsonValue]


class _OpenSubtitlesRawFile(BaseModel):
    """OpenSubtitles 候选文件定位的私有校验模型。"""

    model_config = ConfigDict(extra="ignore", strict=True)

    file_id: int | str | None = None
    file_name: str | None = None


class OpenSubtitlesSource(SubtitleSourceBase):
    """按媒体 ID、英文标题串行查询 OpenSubtitles 来源候选池。"""

    source = SubtitleSource.OPENSUBTITLES
    BASE_URL = "https://api.opensubtitles.com/api/v1"
    USER_AGENT = "MoviePilot SubtitleAssistant/0.1.0"
    CACHE_TTL_SECONDS = 30 * 60

    def __init__(
        self,
        enabled: bool,
        credentials: dict[str, str],
        cache: SourceCachePort | None = None,
    ) -> None:
        """创建 OpenSubtitles 来源适配器。"""

        super().__init__(enabled=enabled, cache=cache)
        self._credentials = dict(credentials)
        self._jwt: str | None = None
        self._base_url = self.BASE_URL
        self._cooldown_until: datetime | None = None
        self._login_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """判断下载所需长期凭据是否完整。"""

        return all(self._credentials.get(key, "").strip() for key in ("api_key", "username", "password"))

    def _headers(self, authenticated: bool = False) -> dict[str, str]:
        """构造不写入日志的 OpenSubtitles 请求头。"""

        headers = {
            "Accept": "application/json",
            "Api-Key": self._credentials.get("api_key", ""),
            "User-Agent": self.USER_AGENT,
            "Content-Type": "application/json",
        }
        if authenticated and self._jwt:
            headers["Authorization"] = f"Bearer {self._jwt}"
        return headers

    @staticmethod
    def _normalize_base_url(value: Any) -> str | None:
        """校验登录响应中的 API 主机并归一为 `/api/v1` 根地址。"""

        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            return None
        if parsed.query or parsed.fragment:
            return None
        path = parsed.path.rstrip("/")
        if path in ("", "/api/v1"):
            path = "/api/v1"
        else:
            return None
        return f"https://{parsed.netloc}{path}"

    def _api_url(self, path: str) -> str:
        """拼接当前登录会话选定的 API 根地址。"""

        return f"{self._base_url}{path}"

    def _ensure_available(self) -> None:
        """在明确冷却期内跳过后续来源请求。"""

        if self._cooldown_until and self._cooldown_until > utc_now():
            raise SourceLimitedError("OpenSubtitles 暂时受限", retry_at=self._cooldown_until)
        self._cooldown_until = None

    def _mark_limited(self, response: Any) -> datetime:
        """根据 Retry-After 或默认六十秒进入冷却。"""

        headers = getattr(response, "headers", {}) if response is not None else {}
        retry_after = headers.get("Retry-After") if headers is not None else None
        try:
            seconds = max(1, int(retry_after if retry_after is not None else 60))
        except (TypeError, ValueError):
            seconds = 60
        self._cooldown_until = datetime.now(UTC) + timedelta(seconds=seconds)
        self._last_details["limited_until"] = self._cooldown_until.isoformat()
        return self._cooldown_until

    @staticmethod
    def normalize_imdb_id(value: str | None) -> int | None:
        """把 IMDb ID 转换为无前缀和前导零的十进制整数。"""

        if not value:
            return None
        normalized = value.strip().lower()
        normalized = normalized.removeprefix("tt")
        if not normalized.isdigit():
            return None
        return int(normalized)

    @staticmethod
    def _base_params(context: SubtitleTarget) -> dict[str, Any]:
        """构造自动与人工默认查询共享的稳定公共参数。"""

        return {
            "languages": "zh-cn",
            "type": "episode" if context.media_type is MediaType.TV else "movie",
        }

    def _query_plan(
        self,
        context: SubtitleTarget,
        custom_query: str | None = None,
    ) -> tuple[list[str], list[tuple[str, str, dict[str, Any]]]]:
        """构造 ID 到英文标题的查询计划，自定义词只替换 query。"""

        common = self._base_params(context)
        defaults: list[str] = []
        plan: list[tuple[str, str, dict[str, Any]]] = []
        imdb_id = self.normalize_imdb_id(context.imdb_id)
        id_params = dict(common)
        id_label = ""
        if context.media_type is MediaType.TV:
            if imdb_id is not None:
                id_params["parent_imdb_id"] = imdb_id
                id_label = f"IMDb ID: {context.imdb_id}"
            elif context.tmdb_id is not None:
                id_params["parent_tmdb_id"] = context.tmdb_id
                id_label = f"TMDB ID: {context.tmdb_id}"
            if context.season is not None:
                id_params["season_number"] = context.season
        else:
            if imdb_id is not None:
                id_params["imdb_id"] = imdb_id
                id_label = f"IMDb ID: {context.imdb_id}"
            elif context.tmdb_id is not None:
                id_params["tmdb_id"] = context.tmdb_id
                id_label = f"TMDB ID: {context.tmdb_id}"
        if id_label:
            defaults.append(id_label)
            plan.append((id_label, "media_id", id_params))

        english_title = (context.english_title or "").strip()
        if english_title:
            title_params = dict(common)
            title_params["query"] = english_title
            if context.year is not None:
                title_params["year"] = context.year
            if context.media_type is MediaType.TV and context.season is not None:
                title_params["season_number"] = context.season
            defaults.append(english_title)
            plan.append((english_title, "english_title", title_params))

        custom = (custom_query or "").strip()
        if custom:
            custom_params = dict(common)
            custom_params["query"] = custom
            if context.year is not None:
                custom_params["year"] = context.year
            if context.media_type is MediaType.TV and context.season is not None:
                custom_params["season_number"] = context.season
            return defaults, [(custom, "custom", custom_params)]
        return defaults, plan

    @staticmethod
    def _identity_query(params: dict[str, Any]) -> str | None:
        """从 OpenSubtitles 请求参数提取实际查询值：标题词或媒体 ID。"""

        title = params.get("query")
        if isinstance(title, str) and title:
            return title
        for key in ("parent_imdb_id", "parent_tmdb_id", "imdb_id", "tmdb_id"):
            value = params.get(key)
            if value is not None:
                return str(value)
        return None

    def _plan(self, context: SubtitleTarget, custom_query: str | None) -> SourcePlan:
        """根据媒体 ID、英文标题或自定义关键词生成有序查询计划。"""

        _defaults, plan = self._query_plan(context, custom_query)
        kinds: dict[str, SourcePlanKind] = {
            "media_id": "id",
            "english_title": "title",
            "custom": "filename",
        }
        queries = [
            SourcePlanQuery(
                label=label,
                identity={"params": params},
                kind=kinds[query_type],
                query=self._identity_query(params),
            )
            for label, query_type, params in plan
        ]
        return SourcePlan(
            queries=queries,
            configured=self.configured,
        )

    @staticmethod
    def _candidate_ids(attributes: dict[str, Any], is_tv: bool) -> tuple[int | None, str | None]:
        """从 feature_details 选择与媒体层级一致的 TMDB/IMDb ID。"""

        feature = attributes.get("feature_details") or {}
        if is_tv:
            tmdb_id = feature.get("parent_tmdb_id") or feature.get("tmdb_id")
            imdb_id = feature.get("parent_imdb_id") or feature.get("imdb_id")
        else:
            tmdb_id = feature.get("tmdb_id")
            imdb_id = feature.get("imdb_id")
        try:
            parsed_tmdb = int(tmdb_id) if tmdb_id not in (None, "") else None
        except (TypeError, ValueError):
            parsed_tmdb = None
        imdb_digits = str(imdb_id or "")
        parsed_imdb = f"tt{int(imdb_digits):07d}" if imdb_digits.isdigit() else None
        return parsed_tmdb, parsed_imdb

    def _normalize_pool(
        self,
        payload: dict[str, Any],
        query: SourcePlanQuery,
    ) -> tuple[list[CandidateHandle], int, dict[str, int], int]:
        """把单页响应归一为自动过滤前的来源候选池。"""

        params = query.identity.get("params")
        is_tv = isinstance(params, dict) and params.get("type") == "episode"
        result: list[CandidateHandle] = []
        raw_count = 0
        rejected: dict[str, int] = {}
        malformed_count = 0
        for item_value in payload.get("data") or []:
            try:
                item = _OpenSubtitlesRawItem.model_validate(item_value).model_dump()
            except ValidationError:
                malformed_count += 1
                continue
            attributes_value = item.get("attributes")
            if not isinstance(attributes_value, dict):
                malformed_count += 1
                continue
            attributes = cast(dict[str, Any], attributes_value)
            translation = TranslationType.HUMAN
            if bool(attributes.get("ai_translated")):
                translation = TranslationType.AI
            elif bool(attributes.get("machine_translated")):
                translation = TranslationType.MACHINE
            tmdb_id, imdb_id = self._candidate_ids(attributes, is_tv)
            feature = attributes.get("feature_details") or {}
            if not isinstance(feature, dict):
                malformed_count += 1
                continue
            season = feature.get("season_number")
            episode = feature.get("episode_number")
            season_digits = str(season or "")
            episode_digits = str(episode or "")
            package_scope = PackageScope.EPISODE
            if is_tv and season is not None and episode is None:
                package_scope = PackageScope.SEASON_PACK
            files = attributes.get("files") or []
            if not files:
                rejected["download_locator"] = rejected.get("download_locator", 0) + 1
            resource_id = str(item.get("id") or "").strip()
            for file_value in files:
                try:
                    file_info = _OpenSubtitlesRawFile.model_validate(file_value).model_dump()
                except ValidationError:
                    malformed_count += 1
                    continue
                try:
                    file_id = int(file_info.get("file_id"))
                except (TypeError, ValueError):
                    rejected["download_locator"] = rejected.get("download_locator", 0) + 1
                    continue
                if file_id <= 0:
                    rejected["download_locator"] = rejected.get("download_locator", 0) + 1
                    continue
                if not resource_id:
                    malformed_count += 1
                    continue
                raw_count += 1
                file_name = str(file_info.get("file_name") or "")
                candidate = SubtitleCandidate(
                    candidate_key=f"opensubtitles:{resource_id}:{file_id}",
                    source=self.source,
                    name=str(attributes.get("release") or file_name or item.get("id") or "OpenSubtitles"),
                    file_name=file_name or None,
                    format=subtitle_format(file_name) or "UNKNOWN",
                    language=str(attributes.get("language") or ""),
                    translation_type=translation,
                    hearing_impaired=bool(attributes.get("hearing_impaired")),
                    foreign_parts_only=bool(attributes.get("foreign_parts_only")),
                    package_scope=package_scope,
                    season=int(season_digits) if season_digits.isdigit() else None,
                    episode=int(episode_digits) if episode_digits.isdigit() else None,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    trusted=bool(attributes.get("from_trusted")),
                    score=float(attributes.get("ratings") or 0),
                    votes=int(attributes.get("votes") or 0),
                    download_count=int(attributes.get("download_count") or 0),
                    uploaded_at=parse_datetime(attributes.get("upload_date")),
                    metadata={"release": attributes.get("release"), "actual_query": query.label},
                )
                result.append(
                    CandidateHandle(
                        candidate=candidate,
                        download_handle=OpenSubtitlesDownloadHandle(file_id=file_id),
                    )
                )
        return result, raw_count, rejected, malformed_count

    async def _request_page(self, params: dict[str, Any], page: int) -> dict[str, Any]:
        """请求并校验一页 OpenSubtitles 搜索响应。"""

        self._ensure_available()
        request_params = {**params, "page": page}
        request = AsyncRequestUtils(headers=self._headers(), **_proxy_kwargs(settings.PROXY))
        for attempt in range(2):
            response = await request.get_res(self._api_url("/subtitles"), params=request_params)
            try:
                if response is not None and response.status_code in {406, 429}:
                    raise SourceLimitedError("OpenSubtitles 搜索暂时受限", retry_at=self._mark_limited(response))
                if response is not None and response.status_code >= 500:
                    if attempt == 0:
                        continue
                    raise SourceRequestError(
                        "OpenSubtitles 搜索服务暂时不可用",
                        SourceErrorCode.TEMPORARY_UNAVAILABLE,
                    )
                if response is None:
                    raise SourceRequestError("OpenSubtitles 搜索请求失败")
                if response.status_code in {401, 403}:
                    raise SourceRequestError("OpenSubtitles 搜索凭据无效", SourceErrorCode.INVALID_CREDENTIALS)
                if response.status_code >= 400:
                    raise SourceRequestError("OpenSubtitles 搜索请求无效", SourceErrorCode.INVALID_REQUEST)
                payload = response.json()
                if not isinstance(payload, dict):
                    raise SourceRequestError("OpenSubtitles 搜索响应结构无效", SourceErrorCode.MALFORMED_RESPONSE)
                return payload
            except ValueError as exc:
                raise SourceRequestError("OpenSubtitles 搜索响应无法解析", SourceErrorCode.MALFORMED_RESPONSE) from exc
            finally:
                if response is not None:
                    await response.aclose()
        raise SourceRequestError("OpenSubtitles 搜索服务暂时不可用", SourceErrorCode.TEMPORARY_UNAVAILABLE)

    async def _fetch_page(self, query: SourcePlanQuery, page: int) -> SourcePage:
        """执行一次 OpenSubtitles 请求并归一化为安全候选页。"""

        params = query.identity.get("params")
        if not isinstance(params, dict):
            raise SourceRequestError("OpenSubtitles 查询参数无效")
        try:
            payload = await self._request_page(dict(params), page)
        except SourceLimitedError as exc:
            if exc.retry_at:
                self._last_details["limited_until"] = exc.retry_at.isoformat()
            raise
        try:
            raw_page = _OpenSubtitlesRawPage.model_validate(payload)
        except ValidationError as exc:
            raise SourceRequestError("OpenSubtitles 响应结构无效", SourceErrorCode.MALFORMED_RESPONSE) from exc
        handles, raw_count, rejected, malformed_count = self._normalize_pool(raw_page.model_dump(), query)
        try:
            total_pages = max(1, int(raw_page.total_pages or 1))
        except (TypeError, ValueError):
            total_pages = 1
        return SourcePage(
            candidates=handles,
            raw_count=raw_count,
            download_locator_excluded_count=rejected.get("download_locator", 0),
            malformed_count=malformed_count,
            has_next=page < total_pages,
        )

    async def _login(self, force: bool = False) -> str:
        """合并并发登录并把 JWT 仅保存在当前运行内存。"""

        if not self.configured:
            raise SourceRequestError("OpenSubtitles 凭据不完整")
        self._ensure_available()
        async with self._login_lock:
            if self._jwt and not force:
                return self._jwt
            request = AsyncRequestUtils(headers=self._headers(), **_proxy_kwargs(settings.PROXY))
            response = await request.post_res(
                f"{self.BASE_URL}/login",
                json={"username": self._credentials["username"], "password": self._credentials["password"]},
            )
            try:
                if response is None:
                    raise SourceRequestError("OpenSubtitles 登录请求失败")
                if response.status_code >= 400:
                    if response.status_code == 429:
                        raise SourceLimitedError("OpenSubtitles 登录暂时受限", retry_at=self._mark_limited(response))
                    raise SourceRequestError(f"OpenSubtitles 登录返回 HTTP {response.status_code}")
                payload = response.json()
                token = payload.get("token") if isinstance(payload, dict) else None
                if not isinstance(token, str) or not token:
                    raise SourceRequestError("OpenSubtitles 登录响应缺少会话")
                base_url = self._normalize_base_url(payload.get("base_url") if isinstance(payload, dict) else None)
                if base_url is None:
                    raise SourceRequestError("OpenSubtitles 登录响应缺少合法 API 地址")
                self._base_url = base_url
                self._jwt = token
                return token
            except ValueError as exc:
                raise SourceRequestError("OpenSubtitles 登录响应无法解析") from exc
            finally:
                if response is not None:
                    await response.aclose()

    async def _download_link(self, file_id: int, retry_auth: bool = True) -> tuple[str, str]:
        """请求一次临时下载链接，JWT 失效时只重试一次。"""

        await self._login()
        request = AsyncRequestUtils(
            headers=self._headers(authenticated=True),
            **_proxy_kwargs(settings.PROXY),
        )
        response = await request.post_res(self._api_url("/download"), json={"file_id": file_id})
        try:
            if response is None:
                raise SourceRequestError("OpenSubtitles 下载授权请求失败")
            if response.status_code in {401, 403} and retry_auth:
                self._jwt = None
                await response.aclose()
                await self._login(force=True)
                return await self._download_link(file_id, retry_auth=False)
            if response.status_code in {406, 429}:
                raise SourceLimitedError("OpenSubtitles 下载额度暂时受限", retry_at=self._mark_limited(response))
            if response.status_code >= 400:
                raise SourceRequestError(f"OpenSubtitles 下载授权返回 HTTP {response.status_code}")
            payload = response.json()
            link = payload.get("link") if isinstance(payload, dict) else None
            if not isinstance(link, str) or not link:
                raise SourceRequestError("OpenSubtitles 下载授权缺少临时链接")
            self._last_details.update(
                {
                    "last_download_at": utc_now().isoformat(),
                    "remaining": payload.get("remaining"),
                    "reset_at": payload.get("reset_time_utc"),
                }
            )
            return link, safe_file_name(payload.get("file_name"), f"{file_id}.srt")
        except ValueError as exc:
            raise SourceRequestError("OpenSubtitles 下载授权响应无法解析") from exc
        finally:
            if response is not None and not response.is_closed:
                await response.aclose()

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """获取最新临时链接并下载字幕文件。"""

        if not isinstance(handle.download_handle, OpenSubtitlesDownloadHandle):
            raise SourceRequestError("OpenSubtitles 候选缺少有效下载句柄")
        file_id = handle.download_handle.file_id
        link, file_name = await self._download_link(file_id)
        request = AsyncRequestUtils(**_proxy_kwargs(settings.PROXY))
        try:
            path = await download_file(request, link, directory, file_name)
        except SourceRequestError as exc:
            if exc.status_code != 410:
                raise
            link, file_name = await self._download_link(file_id)
            path = await download_file(request, link, directory, file_name)
        return DownloadedAsset(path=path, file_name=file_name)

    async def _probe(self, manual: bool) -> SourceProbe | None:
        """重新登录验证长期凭据，不调用下载接口。"""

        del manual
        try:
            await self._login(force=True)
        except SourceLimitedError:
            self._last_details["session_active"] = bool(self._jwt)
            raise
        except Exception as exc:
            self._last_details["session_active"] = False
            raise SourceRequestError("OpenSubtitles 登录验证失败") from exc
        return None

    async def close(self) -> None:
        """清除内存 JWT。"""

        self._jwt = None

    def runtime_details(self) -> dict[str, Any]:
        """返回不含秘密的当前运行观测。"""

        return {**self._last_details, "session_active": bool(self._jwt)}
