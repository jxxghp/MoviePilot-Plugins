from datetime import datetime
import base64
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

try:
    from app.helper.browser import PlaywrightHelper
except Exception:
    PlaywrightHelper = None

try:
    from app.chain.media import MediaChain
except Exception:
    MediaChain = None

try:
    from app.core.config import settings
except Exception:
    settings = None


class HDHiveOpenApiService:
    """Reusable HDHive execution layer for Agent影视助手."""

    _signin_action_name = "checkIn"
    _signin_router_tree = ["", {"children": ["(app)", {"children": ["__PAGE__", {}, None, None]}, None, None]}, None, None, True]
    _login_api_candidates = [
        "/api/customer/user/login",
        "/api/customer/auth/login",
    ]
    _login_page = "/login"
    _login_action_router_state = '%5B%22%22%2C%7B%22children%22%3A%5B%22(auth)%22%2C%7B%22children%22%3A%5B%22login%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Flogin%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D%7D%2Cnull%2Cnull%2Ctrue%5D'
    _login_action_fallback = "602b5a3af7ab2e93be6a14001ca83c1be491ccecea"

    # Meta endpoints that only require app-level X-API-Key auth.
    _META_ENDPOINT_PREFIXES: Tuple[str, ...] = (
        "/api/open/ping",
        "/api/open/quota",
        "/api/open/usage",
        "/api/open/usage/today",
    )
    # Refresh endpoint path per HDHive documented OpenAPI contract.
    _REFRESH_ENDPOINT = "/api/public/openapi/oauth/refresh"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://hdhive.com",
        timeout: int = 30,
        openapi_user_token: str = "",
        openapi_refresh_token: str = "",
    ) -> None:
        self.api_key = self.normalize_text(api_key)
        self.base_url = (self.normalize_text(base_url) or "https://hdhive.com").rstrip("/")
        self.timeout = self.safe_int(timeout, 30)
        self.openapi_user_token = self.normalize_text(openapi_user_token)
        self.openapi_refresh_token = self.normalize_text(openapi_refresh_token)
        self._login_action_id = ""
        self._in_refresh_retry = False

    def _is_meta_endpoint(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self._META_ENDPOINT_PREFIXES)

    @staticmethod
    def safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def normalize_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def normalize_slug(value: Any) -> str:
        return str(value or "").strip().replace("-", "")

    @staticmethod
    def normalize_pan_path(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if not text.startswith("/"):
            text = f"/{text}"
        return text.rstrip("/") or "/"

    @staticmethod
    def media_type_text(value: Any) -> str:
        if value is None:
            return ""
        raw = str(getattr(value, "value", value)).strip().lower()
        mapping = {
            "电影": "movie",
            "movie": "movie",
            "电视剧": "tv",
            "tv": "tv",
        }
        return mapping.get(raw, raw)

    def tz_now(self) -> datetime:
        if settings is not None:
            try:
                return datetime.now(ZoneInfo(getattr(settings, "TZ", "Asia/Shanghai")))
            except Exception:
                pass
        return datetime.now()

    def base_headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
        }

    def api_url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def tmdb_web_search_url(self, media_type: str, keyword: str) -> str:
        query = quote(keyword)
        if media_type == "movie":
            return f"https://www.themoviedb.org/search/movie?query={query}"
        if media_type == "tv":
            return f"https://www.themoviedb.org/search/tv?query={query}"
        return f"https://www.themoviedb.org/search?query={query}"

    def tmdb_web_search_headers(self) -> Dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
        }

    @staticmethod
    def extract_year_from_release(value: Any) -> str:
        match = re.search(r"(19|20)\d{2}", str(value or ""))
        return match.group(0) if match else ""

    def tmdb_web_search_candidates(
        self,
        keyword: str,
        media_type: str = "auto",
        year: str = "",
        candidate_limit: int = 10,
    ) -> Tuple[List[Dict[str, Any]], str]:
        keyword = self.normalize_text(keyword)
        media_type = self.normalize_text(media_type).lower() or "auto"
        year = self.normalize_text(year)
        candidate_limit = min(50, max(1, self.safe_int(candidate_limit, 10)))
        search_order = [media_type] if media_type in {"movie", "tv"} else ["tv", "movie"]
        pattern = re.compile(
            r'href="/(?P<media_type>tv|movie)/(?P<tmdb_id>\d+)"[^>]*>\s*'
            r'<div[^>]*>\s*'
            r'<img alt="(?P<title>[^"]+)"[^>]*srcset="(?P<srcset>[^"]*)"[^>]*src="(?P<src>[^"]+)"[^>]*>'
            r'.*?<span class="release_date[^"]*">(?P<release>[^<]+)</span>',
            re.S,
        )
        candidates: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        errors: List[str] = []
        for search_type in search_order:
            try:
                response = requests.get(
                    self.tmdb_web_search_url(search_type, keyword),
                    headers=self.tmdb_web_search_headers(),
                    timeout=self.timeout,
                    proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                )
                response.raise_for_status()
            except Exception as exc:
                errors.append(f"{search_type}:{exc}")
                continue
            html = response.text or ""
            for match in pattern.finditer(html):
                item_type = self.normalize_text(match.group("media_type")).lower()
                tmdb_id = self.normalize_text(match.group("tmdb_id"))
                if not tmdb_id or tmdb_id in seen_ids:
                    continue
                item_year = self.extract_year_from_release(match.group("release"))
                if year and item_year and item_year != year:
                    continue
                seen_ids.add(tmdb_id)
                candidates.append(
                    {
                        "title": self.normalize_text(match.group("title")),
                        "year": item_year,
                        "media_type": item_type or search_type,
                        "tmdb_id": tmdb_id,
                        "poster_path": self.normalize_text(match.group("src")),
                    }
                )
                if len(candidates) >= candidate_limit:
                    return candidates, ""
        return candidates, "；".join(errors)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        require_user_auth: Optional[bool] = None,
    ) -> Tuple[bool, Dict[str, Any], str, int]:
        if not self.api_key:
            return False, {}, "未配置影巢 API Key", 400

        # Auto-detect: meta endpoints don't need user auth; business endpoints do.
        needs_user_auth = require_user_auth if require_user_auth is not None else not self._is_meta_endpoint(path)
        if needs_user_auth and not self.openapi_user_token:
            return False, {}, (
                "当前影巢 OpenAPI 业务接口需要用户授权令牌（Bearer Token），"
                "但未配置 hdhive_openapi_user_token。请先在插件配置中填入 OpenAPI 用户 Access Token，"
                "或通过 OAuth 流程获取后填入。"
            ), 401

        headers = self.base_headers()
        if needs_user_auth and self.openapi_user_token:
            headers["Authorization"] = f"Bearer {self.openapi_user_token}"

        try:
            response = requests.request(
                method=method.upper(),
                url=self.api_url(path),
                headers=headers,
                params=params,
                json=payload if payload is not None else None,
                timeout=timeout or self.timeout,
                proxies=getattr(settings, "PROXY", None) if settings is not None else None,
            )
        except Exception as exc:
            return False, {}, f"请求异常: {exc}", 0

        try:
            result = response.json()
        except Exception:
            result = {
                "success": False,
                "message": response.text[:300] if response.text else f"HTTP {response.status_code}",
                "description": "接口未返回有效 JSON",
            }

        if response.ok and isinstance(result, dict) and result.get("success", True):
            return True, result, "", response.status_code

        # If a business request fails with 401/403 and we have a refresh token, try once.
        if (
            needs_user_auth
            and response.status_code in (401, 403)
            and self.openapi_refresh_token
            and not self._in_refresh_retry
        ):
            refresh_ok = self._try_refresh_user_token()
            if refresh_ok:
                self._in_refresh_retry = True
                try:
                    return self.request(
                        method, path,
                        params=params, payload=payload, timeout=timeout,
                        require_user_auth=True,
                    )
                finally:
                    self._in_refresh_retry = False

        message = ""
        if isinstance(result, dict):
            message = (
                result.get("description")
                or result.get("message")
                or result.get("code")
                or f"HTTP {response.status_code}"
            )
        if not message:
            message = f"HTTP {response.status_code}"
        return False, result if isinstance(result, dict) else {}, message, response.status_code

    def _try_refresh_user_token(self) -> bool:
        if not self.openapi_refresh_token:
            return False
        try:
            response = requests.post(
                url=self.api_url(self._REFRESH_ENDPOINT),
                headers=self.base_headers(),
                json={"refresh_token": self.openapi_refresh_token},
                timeout=self.timeout,
                proxies=getattr(settings, "PROXY", None) if settings is not None else None,
            )
            if response.status_code != 200:
                return False
            data = response.json()
            if not isinstance(data, dict) or not data.get("success", True):
                return False
            meta = data.get("data") if isinstance(data.get("data"), dict) else {}
            new_access = self.normalize_text(meta.get("access_token") or meta.get("token"))
            new_refresh = self.normalize_text(meta.get("refresh_token")) or self.openapi_refresh_token
            if not new_access:
                return False
            self.openapi_user_token = new_access
            self.openapi_refresh_token = new_refresh
            return True
        except Exception:
            return False

    def auth_status(self) -> Dict[str, Any]:
        return {
            "api_key_configured": bool(self.api_key),
            "user_token_configured": bool(self.openapi_user_token),
            "refresh_token_configured": bool(self.openapi_refresh_token),
        }

    def resource_sort_key(self, item: Dict[str, Any]) -> Tuple[int, int, int, int, str]:
        pan = str(item.get("pan_type") or "").lower()
        points = item.get("unlock_points")
        try:
            points_value = int(points) if points is not None and str(points) != "" else 0
        except Exception:
            points_value = 9999
        validate = str(item.get("validate_status") or "").lower()
        resolutions = [str(v).upper() for v in (item.get("video_resolution") or [])]
        sources = [str(v) for v in (item.get("source") or [])]
        pan_rank = 0 if pan == "115" else 1 if pan == "quark" else 2
        points_rank = 0 if points_value <= 0 else 1
        validate_rank = 0 if validate in {"valid", ""} else 1
        resolution_rank = 0 if "4K" in resolutions else 1 if "1080P" in resolutions else 2
        source_rank = 0 if "蓝光原盘/REMUX" in sources else 1 if "WEB-DL/WEBRip" in sources else 2
        return (pan_rank, points_rank, validate_rank, resolution_rank + source_rank, str(item.get("title") or ""))

    async def resolve_candidates_by_keyword(
        self,
        keyword: str,
        media_type: str = "auto",
        year: str = "",
        candidate_limit: int = 10,
    ) -> Tuple[bool, Dict[str, Any], str]:
        keyword = self.normalize_text(keyword)
        media_type = self.normalize_text(media_type).lower() or "auto"
        type_filter = "" if media_type in {"auto", "all", "*"} else media_type
        year = self.normalize_text(year)
        candidate_limit = min(50, max(1, self.safe_int(candidate_limit, 10)))

        if not keyword:
            return False, {"message": "keyword 不能为空", "query": {"keyword": "", "media_type": media_type}}, "keyword 不能为空"
        if type_filter and type_filter not in {"movie", "tv"}:
            return False, {"message": "媒体类型必须是 movie、tv 或 auto", "query": {"keyword": keyword, "media_type": media_type}}, "媒体类型必须是 movie、tv 或 auto"
        chain_error = ""
        medias = []
        if MediaChain is None:
            chain_error = "MoviePilot MediaChain 不可用"
        else:
            try:
                _, medias = await MediaChain().async_search(title=keyword)
            except Exception as exc:
                chain_error = f"TMDB 解析失败: {exc}"
        try:
            medias = list(medias or [])
        except Exception:
            medias = []

        candidates: List[Dict[str, Any]] = []
        for media in medias:
            item_type = self.media_type_text(getattr(media, "type", ""))
            item_year = self.normalize_text(getattr(media, "year", ""))
            if type_filter and item_type and item_type != type_filter:
                continue
            if year and item_year and item_year != year:
                continue
            tmdb_id = getattr(media, "tmdb_id", None)
            if not tmdb_id:
                continue
            candidates.append(
                {
                    "title": getattr(media, "title", "") or getattr(media, "en_title", "") or "",
                    "year": item_year,
                    "media_type": item_type or type_filter or "movie",
                    "tmdb_id": tmdb_id,
                    "poster_path": getattr(media, "poster_path", "") or "",
                }
            )
            if len(candidates) >= candidate_limit:
                break

        fallback_used = False
        fallback_message = ""
        if not candidates:
            web_candidates, web_error = self.tmdb_web_search_candidates(
                keyword=keyword,
                media_type=media_type,
                year=year,
                candidate_limit=candidate_limit,
            )
            if web_candidates:
                candidates = web_candidates
                fallback_used = True
            else:
                fallback_message = web_error

        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": bool(candidates),
            "status_code": 200 if candidates else 404,
            "message": "success" if candidates else "未找到可用于影巢搜索的 TMDB 候选",
            "query": {"keyword": keyword, "media_type": media_type, "year": year},
            "candidates": candidates,
            "meta": {
                "total": len(candidates),
                "candidate_source": "tmdb_web_search" if fallback_used else "mediainfo_chain",
            },
        }
        if fallback_used:
            result["fallback_reason"] = chain_error or "MediaChain 未返回候选"
        elif chain_error:
            result["chain_warning"] = chain_error
        if not candidates and fallback_message:
            result["fallback_error"] = fallback_message
            if chain_error:
                result["message"] = f"{chain_error}；TMDB 网页搜索兜底也未命中"
        elif not candidates and chain_error:
            result["message"] = chain_error
        return bool(candidates), result, result["message"]

    def search_resources(self, media_type: str, tmdb_id: str) -> Tuple[bool, Dict[str, Any], str]:
        media_type = (media_type or "").strip().lower()
        tmdb_id = self.normalize_text(tmdb_id)
        if media_type not in {"movie", "tv"}:
            return False, {"message": "媒体类型必须是 movie 或 tv", "query": {"media_type": media_type, "tmdb_id": tmdb_id}}, "媒体类型必须是 movie 或 tv"
        if not tmdb_id:
            return False, {"message": "TMDB ID 不能为空", "query": {"media_type": media_type, "tmdb_id": tmdb_id}}, "TMDB ID 不能为空"

        ok, payload, message, status_code = self.request("GET", f"/api/open/resources/{media_type}/{tmdb_id}")
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "status_code": status_code,
            "message": payload.get("message") if ok else message,
            "query": {"media_type": media_type, "tmdb_id": tmdb_id},
            "data": payload.get("data") if isinstance(payload, dict) else [],
            "meta": payload.get("meta") if isinstance(payload, dict) else {},
        }
        return ok, result, message

    async def search_resources_by_keyword(
        self,
        keyword: str,
        media_type: str = "auto",
        year: str = "",
        candidate_limit: int = 10,
        result_limit: int = 12,
    ) -> Tuple[bool, Dict[str, Any], str]:
        result_limit = min(50, max(1, self.safe_int(result_limit, 12)))
        ok, candidate_result, candidate_message = await self.resolve_candidates_by_keyword(
            keyword=keyword,
            media_type=media_type,
            year=year,
            candidate_limit=candidate_limit,
        )
        if not ok:
            result = dict(candidate_result)
            result["data"] = []
            return False, result, candidate_message
        candidates = candidate_result.get("candidates") or []

        merged_items: List[Dict[str, Any]] = []
        seen_slugs: set[str] = set()
        last_status = 200

        for candidate in candidates:
            ok, payload, message = self.search_resources(
                media_type=candidate["media_type"] or media_type,
                tmdb_id=str(candidate["tmdb_id"]),
            )
            last_status = payload.get("status_code", last_status) if isinstance(payload, dict) else last_status
            if not ok:
                continue
            for resource in payload.get("data") or []:
                slug = self.normalize_slug(resource.get("slug"))
                if not slug or slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                annotated = dict(resource)
                annotated["matched_tmdb_id"] = candidate["tmdb_id"]
                annotated["matched_title"] = candidate["title"]
                annotated["matched_year"] = candidate["year"]
                merged_items.append(annotated)

        merged_items.sort(key=self.resource_sort_key)
        merged_items = merged_items[:result_limit]

        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": bool(merged_items),
            "status_code": last_status,
            "message": "success" if merged_items else "已解析 TMDB，但影巢暂无匹配资源",
            "query": {"keyword": keyword, "media_type": media_type, "year": year},
            "candidates": candidates,
            "data": merged_items,
            "meta": {"total": len(merged_items), "candidate_count": len(candidates)},
        }
        return bool(merged_items), result, result["message"]

    def unlock_resource(self, slug: str) -> Tuple[bool, Dict[str, Any], str]:
        slug = self.normalize_slug(slug)
        if not slug:
            return False, {"message": "slug 不能为空", "slug": ""}, "slug 不能为空"
        ok, payload, message, status_code = self.request(
            "POST",
            "/api/open/resources/unlock",
            payload={"slug": slug},
        )
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "status_code": status_code,
            "message": payload.get("message") if ok else message,
            "slug": slug,
            "data": payload.get("data") if isinstance(payload, dict) else {},
        }
        return ok, result, message

    def fetch_me(self) -> Tuple[bool, Dict[str, Any], str]:
        ok, payload, message, status_code = self.request("GET", "/api/open/me")
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "status_code": status_code,
            "message": payload.get("message") if ok else message,
            "data": payload.get("data") if isinstance(payload, dict) else {},
        }
        return ok, result, message

    def fetch_quota(self) -> Tuple[bool, Dict[str, Any], str]:
        ok, payload, message, status_code = self.request("GET", "/api/open/quota")
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "status_code": status_code,
            "message": payload.get("message") if ok else message,
            "data": payload.get("data") if isinstance(payload, dict) else {},
        }
        return ok, result, message

    def fetch_usage_today(self) -> Tuple[bool, Dict[str, Any], str]:
        ok, payload, message, status_code = self.request("GET", "/api/open/usage/today")
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "status_code": status_code,
            "message": payload.get("message") if ok else message,
            "data": payload.get("data") if isinstance(payload, dict) else {},
        }
        return ok, result, message

    def fetch_weekly_free_quota(self) -> Tuple[bool, Dict[str, Any], str]:
        ok, payload, message, status_code = self.request("GET", "/api/open/vip/weekly-free-quota")
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "status_code": status_code,
            "message": payload.get("message") if ok else message,
            "data": payload.get("data") if isinstance(payload, dict) else {},
        }
        return ok, result, message

    def perform_checkin(
        self,
        *,
        is_gambler: Optional[bool] = None,
        trigger: str = "手动",
    ) -> Tuple[bool, Dict[str, Any], str]:
        gambler_mode = bool(is_gambler)
        payload = {"is_gambler": True} if gambler_mode else None
        ok, result_payload, message, status_code = self.request("POST", "/api/open/checkin", payload=payload)
        data = result_payload.get("data") if isinstance(result_payload, dict) else {}
        checked_in = bool((data or {}).get("checked_in")) if ok else False
        if ok:
            status_text = "签到成功" if checked_in else "今日已签到"
        else:
            status_text = "签到失败"
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "status_code": status_code,
            "trigger": trigger,
            "is_gambler": gambler_mode,
            "status": status_text,
            "message": (data or {}).get("message") or result_payload.get("message") or message,
            "data": data or {},
        }
        return ok, result, message

    @staticmethod
    def parse_cookie_string(cookie_str: Optional[str]) -> Dict[str, str]:
        cookies: Dict[str, str] = {}
        if not cookie_str:
            return cookies
        for cookie_item in str(cookie_str).split(";"):
            if "=" in cookie_item:
                name, value = cookie_item.strip().split("=", 1)
                cookies[name] = value
        return cookies

    @staticmethod
    def _decode_token_user_id(token: str) -> str:
        if not token or "." not in token:
            return ""
        try:
            payload = token.split(".", 2)[1]
            padding = "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8", "ignore")
            data = json.loads(decoded)
            return str(data.get("user_id") or data.get("sub") or data.get("id") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _cookie_string_from_mapping(cookies: Dict[str, str]) -> str:
        normalized = {str(key or "").strip(): str(value or "").strip() for key, value in (cookies or {}).items()}
        token_cookie = normalized.get("token", "")
        if not token_cookie:
            return ""
        preferred_order = ["hdh_sa_token", "token", "refresh_token", "csrf_access_token", "hdh_uid"]
        cookie_items: List[str] = []
        seen: set[str] = set()
        for name in preferred_order:
            value = normalized.get(name, "")
            if value:
                cookie_items.append(f"{name}={value}")
                seen.add(name)
        for name, value in normalized.items():
            if name and value and name not in seen:
                cookie_items.append(f"{name}={value}")
        return "; ".join(cookie_items)

    @classmethod
    def _extract_login_action_id_from_text(cls, text: str) -> str:
        patterns = [
            r'next-action"\s*:\s*"([a-fA-F0-9]{16,64})"',
            r'name="next-action"\s+value="([a-fA-F0-9]{16,64})"',
            r'createServerReference\("([a-f0-9]{40,})"[^\\n]+?"login"\)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text or "")
            if match:
                return str(match.group(1) or "").strip()
        return ""

    def _discover_login_action_id(self, warm_text: str, scraper: Any) -> str:
        if self._login_action_id:
            return self._login_action_id

        action_id = self._extract_login_action_id_from_text(warm_text)
        if action_id:
            self._login_action_id = action_id
            return action_id

        script_paths = re.findall(
            r'<script[^>]+src="([^"]+/app/\(auth\)/login/page-[^"]+\.js)"',
            warm_text or "",
        )
        for script_path in script_paths:
            script_url = script_path if script_path.startswith("http") else f"{self.base_url}{script_path}"
            try:
                resp = scraper.get(
                    script_url,
                    headers={
                        "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
                        "Referer": f"{self.base_url}{self._login_page}",
                        "Accept": "*/*",
                    },
                    timeout=self.timeout,
                    proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                )
            except Exception:
                continue
            action_id = self._extract_login_action_id_from_text(getattr(resp, "text", "") or "")
            if action_id:
                self._login_action_id = action_id
                return action_id

        self._login_action_id = self._login_action_fallback
        return self._login_action_id

    @staticmethod
    def _parse_server_action_error(response_text: str) -> str:
        if not response_text:
            return ""
        try:
            for line in response_text.splitlines():
                line = line.strip()
                if not line.startswith("1:"):
                    continue
                payload = json.loads(line[2:])
                error = payload.get("error") or {}
                message = str(error.get("message") or "").strip()
                description = str(error.get("description") or "").strip()
                if message or description:
                    return f"{message} ({description})" if description and description != message else (message or description)
        except Exception:
            return ""
        return ""

    def login_for_cookie(self, *, username: str, password: str) -> Tuple[bool, str, str]:
        username = self.normalize_text(username)
        password = self.normalize_text(password)
        if not username or not password:
            return False, "", "未配置影巢用户名或密码，无法自动刷新 Cookie"

        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
        except Exception:
            scraper = requests

        login_url = f"{self.base_url}{self._login_page}"
        warm_text = ""
        try:
            resp_warm = scraper.get(
                login_url,
                timeout=self.timeout,
                proxies=getattr(settings, "PROXY", None) if settings is not None else None,
            )
            warm_text = getattr(resp_warm, "text", "") or ""
        except Exception:
            pass
        if "系统维护中" in warm_text or "maintenance" in warm_text.lower():
            return False, "", "影巢站点当前处于维护页，暂时无法自动登录刷新 Cookie"

        for path in self._login_api_candidates:
            url = f"{self.base_url}{path}"
            headers = {
                "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
                "Accept": "application/json, text/plain, */*",
                "Origin": self.base_url,
                "Referer": login_url,
                "Content-Type": "application/json",
            }
            payload = {"username": username, "password": password}
            try:
                resp = scraper.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                    proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                )
            except Exception:
                continue

            cookies_dict: Dict[str, str] = {}
            try:
                cookies_dict = getattr(resp, "cookies", None).get_dict() if getattr(resp, "cookies", None) else {}
            except Exception:
                cookies_dict = {}

            cookie_string = self._cookie_string_from_mapping(cookies_dict)
            if cookie_string:
                return True, cookie_string, "API 登录成功"

            try:
                data = resp.json()
            except Exception:
                data = {}
            meta = (data.get("meta") or {}) if isinstance(data, dict) else {}
            access_token = str(meta.get("access_token") or "").strip()
            refresh_token = str(meta.get("refresh_token") or "").strip()
            if access_token:
                cookie_items = [f"token={access_token}"]
                if refresh_token:
                    cookie_items.append(f"refresh_token={refresh_token}")
                return True, "; ".join(cookie_items), "API 登录成功"

        action_id = self._discover_login_action_id(warm_text, scraper)
        if action_id:
            headers = {
                "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
                "Accept": "text/x-component",
                "Origin": self.base_url,
                "Referer": login_url,
                "Content-Type": "text/plain;charset=UTF-8",
                "next-action": action_id,
                "next-router-state-tree": self._login_action_router_state,
            }
            body = json.dumps([{"username": username, "password": password}, "/"], separators=(",", ":"))
            try:
                resp = scraper.post(
                    login_url,
                    headers=headers,
                    data=body,
                    timeout=self.timeout,
                    proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                )
            except Exception as exc:
                resp = None
                server_action_message = f"Server Action 登录请求异常: {exc}"
            else:
                server_action_message = ""
            if resp is not None:
                try:
                    cookies_dict = getattr(resp, "cookies", None).get_dict() if getattr(resp, "cookies", None) else {}
                except Exception:
                    cookies_dict = {}
                cookie_string = self._cookie_string_from_mapping(cookies_dict)
                if cookie_string:
                    return True, cookie_string, "Server Action 登录成功"
                action_error = self._parse_server_action_error(getattr(resp, "text", "") or "")
                if action_error:
                    server_action_message = action_error
        else:
            server_action_message = "未解析到登录 Action"

        if PlaywrightHelper is None:
            return False, "", server_action_message or "自动登录失败，且 MoviePilot PlaywrightHelper 不可用"

        def _login_with_page(page: Any) -> List[Dict[str, Any]]:
            for selector in [
                "input[name='username']",
                "input[name='email']",
                "input[type='email']",
                "input[placeholder*='邮箱']",
                "input[placeholder*='email']",
                "input[placeholder*='用户名']",
            ]:
                try:
                    if page.query_selector(selector):
                        page.fill(selector, username)
                        break
                except Exception:
                    continue
            for selector in [
                "input[name='password']",
                "input[type='password']",
                "input[placeholder*='密码']",
            ]:
                try:
                    if page.query_selector(selector):
                        page.fill(selector, password)
                        break
                except Exception:
                    continue
            try:
                button = (
                    page.query_selector("button[type='submit']")
                    or page.query_selector("button:has-text('登录')")
                    or page.query_selector("button:has-text('Login')")
                )
                if button:
                    button.click()
                else:
                    page.click("button")
            except Exception:
                try:
                    page.click("button")
                except Exception:
                    pass
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            deadline = self.tz_now().timestamp() + 15
            while self.tz_now().timestamp() < deadline:
                try:
                    cookies = page.context.cookies()
                    if any(str(item.get("name") or "") == "token" and item.get("value") for item in cookies):
                        return cookies
                except Exception:
                    pass
                try:
                    if "/login" not in (page.url or ""):
                        page.wait_for_timeout(1000)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    break
            try:
                return page.context.cookies()
            except Exception:
                return []

        try:
            proxy_config = getattr(settings, "PROXY", None) if settings is not None else None
            cookies = PlaywrightHelper().action(
                login_url,
                callback=_login_with_page,
                proxies=proxy_config,
                headless=True,
                timeout=max(30, self.timeout),
            ) or []
        except Exception as exc:
            return False, "", f"PlaywrightHelper 自动登录失败: {exc}"

        cookie_map = {str(item.get("name") or ""): str(item.get("value") or "") for item in cookies or []}
        cookie_string = self._cookie_string_from_mapping(cookie_map)
        if cookie_string:
            return True, cookie_string, "PlaywrightHelper 登录成功"
        return False, "", server_action_message or "自动登录失败，未获取到有效 Cookie"

    @classmethod
    def _build_signin_tree_header(cls) -> str:
        return quote(json.dumps(cls._signin_router_tree, separators=(",", ":")))

    @staticmethod
    def _build_signin_action_body(is_gambler: bool) -> str:
        return json.dumps([bool(is_gambler)], separators=(",", ":"))

    @staticmethod
    def _normalize_response_text(text: str) -> str:
        if not text:
            return ""
        if "ä½" in text or "å·²" in text or "ç­¾å°" in text:
            try:
                return text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            except Exception:
                return text
        return text

    @classmethod
    def _extract_signin_action_id_from_chunk(cls, chunk_text: str) -> str:
        if not chunk_text:
            return ""
        patterns = [
            rf'createServerReference[\s\S]{{0,120}}?\("([a-f0-9]{{32,}})"[\s\S]{{0,1200}}?"{re.escape(cls._signin_action_name)}"',
            rf'([a-f0-9]{{32,}}).{{0,240}}?"{re.escape(cls._signin_action_name)}"',
        ]
        for pattern in patterns:
            match = re.search(pattern, chunk_text, re.S)
            if match:
                return match.group(1)
        return ""

    @classmethod
    def _parse_signin_action_response(cls, text: str) -> Tuple[bool, str]:
        text = cls._normalize_response_text(text)
        if not text:
            return False, "签到响应为空"
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            _, payload = line.split(":", 1)
            try:
                data = json.loads(payload)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if isinstance(data.get("response"), dict):
                data = data["response"]
            error = data.get("error")
            if isinstance(error, dict):
                message = cls._normalize_response_text(error.get("description") or error.get("message") or "签到失败")
                if "已经签到" in message or "签到过" in message or "明天再来" in message:
                    return True, message
                return False, message
            message = cls._normalize_response_text(data.get("message") or data.get("description"))
            success = data.get("success")
            if message:
                if success is False:
                    return False, message
                if "已经签到" in message or "签到过" in message or "明天再来" in message:
                    return True, message
                return True, message
        return False, "签到响应格式异常"

    def _discover_signin_action_id(self, cookies: Dict[str, str], token: str, referer: str) -> str:
        headers = {
            "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": self.base_url,
            "Referer": referer,
            "Authorization": f"Bearer {token}",
        }
        try:
            home_resp = requests.get(
                url=f"{self.base_url}/",
                headers=headers,
                cookies=cookies,
                proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                timeout=self.timeout,
                verify=False,
            )
        except Exception:
            return ""
        if home_resp.status_code != 200:
            return ""
        html = home_resp.text or ""
        chunk_paths = list(dict.fromkeys(re.findall(r'/_next/static/chunks/[A-Za-z0-9._-]+\.js', html)))
        for chunk_path in chunk_paths:
            try:
                chunk_resp = requests.get(
                    url=f"{self.base_url}{chunk_path}",
                    headers={
                        "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
                        "Accept": "application/javascript,text/javascript,*/*;q=0.1",
                        "Connection": "close",
                    },
                    proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                    timeout=min(self.timeout, 20),
                    verify=False,
                )
            except Exception:
                continue
            if chunk_resp.status_code != 200:
                continue
            action_id = self._extract_signin_action_id_from_chunk(chunk_resp.text or "")
            if action_id:
                return action_id
        return ""

    def perform_legacy_web_checkin(
        self,
        *,
        cookie_string: str,
        is_gambler: bool = False,
        trigger: str = "网页兜底",
    ) -> Tuple[bool, Dict[str, Any], str]:
        cookies = self.parse_cookie_string(cookie_string)
        token = str(cookies.get("token") or "").strip()
        csrf_token = str(cookies.get("csrf_access_token") or "").strip()
        if not cookies or not token:
            result = {
                "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
                "ok": False,
                "status_code": 400,
                "trigger": trigger,
                "is_gambler": bool(is_gambler),
                "status": "签到失败",
                "message": "缺少可用的影巢网页 Cookie",
                "data": {},
                "source": "hdhive_web_legacy",
            }
            return False, result, result["message"]

        user_id = self._decode_token_user_id(token)
        referer = f"{self.base_url}/user/{user_id}" if user_id else f"{self.base_url}/"
        headers = {
            "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": self.base_url,
            "Referer": referer,
            "Authorization": f"Bearer {token}",
        }
        if csrf_token:
            headers["X-CSRF-TOKEN"] = csrf_token

        payload = {"is_gambler": True} if is_gambler else {}
        try:
            response = requests.post(
                url=f"{self.base_url}/api/customer/user/checkin",
                headers=headers,
                cookies=cookies,
                json=payload,
                timeout=self.timeout,
                proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                verify=False,
            )
        except Exception as exc:
            result = {
                "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
                "ok": False,
                "status_code": 0,
                "trigger": trigger,
                "is_gambler": bool(is_gambler),
                "status": "签到失败",
                "message": f"网页签到请求异常: {exc}",
                "data": {},
                "source": "hdhive_web_legacy",
            }
            return False, result, result["message"]

        try:
            body = response.json()
        except Exception:
            body = {}

        message = ""
        if isinstance(body, dict):
            message = str(body.get("description") or body.get("message") or body.get("code") or "").strip()
        if not message:
            message = str(response.text or f"HTTP {response.status_code}").strip()[:200]

        lowered = message.lower()
        already_signed = "已经签到" in message or "签到过" in message or "明天再来" in message
        success = bool(response.status_code < 400 and (not isinstance(body, dict) or body.get("success") is not False))
        if already_signed:
            success = True

        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": success,
            "status_code": response.status_code,
            "trigger": trigger,
            "is_gambler": bool(is_gambler),
            "status": "今日已签到" if already_signed else "签到成功" if success else "签到失败",
            "message": message or ("签到成功" if success else f"HTTP {response.status_code}"),
            "data": body if isinstance(body, dict) else {},
            "source": "hdhive_web_legacy",
        }
        return success, result, result["message"]

    def perform_web_checkin_with_fallback(
        self,
        *,
        cookie_string: str,
        is_gambler: bool = False,
        trigger: str = "网页兜底",
    ) -> Tuple[bool, Dict[str, Any], str]:
        legacy_ok, legacy_result, legacy_message = self.perform_legacy_web_checkin(
            cookie_string=cookie_string,
            is_gambler=is_gambler,
            trigger=trigger,
        )
        if legacy_ok:
            return legacy_ok, legacy_result, legacy_message

        cookies = self.parse_cookie_string(cookie_string)
        token = str(cookies.get("token") or "").strip()
        csrf_token = str(cookies.get("csrf_access_token") or "").strip()
        if not cookies or not token:
            return legacy_ok, legacy_result, legacy_message

        user_id = self._decode_token_user_id(token)
        referer = f"{self.base_url}/user/{user_id}" if user_id else f"{self.base_url}/"
        action_id = self._discover_signin_action_id(cookies, token, referer)
        if not action_id:
            message = "旧版网页签到接口不可用，且未能解析当前站点签到 Action；请更新影巢网页 Cookie 后重试"
            legacy_result["message"] = message
            legacy_result["status"] = "签到失败"
            legacy_result["source"] = "hdhive_web_next_action"
            return False, legacy_result, message

        headers = {
            "User-Agent": getattr(settings, "USER_AGENT", "MoviePilot") if settings is not None else "MoviePilot",
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "Authorization": f"Bearer {token}",
            "next-action": action_id,
            "next-router-state-tree": self._build_signin_tree_header(),
        }
        if csrf_token:
            headers["x-csrf-token"] = csrf_token

        try:
            response = requests.post(
                url=f"{self.base_url}/",
                headers=headers,
                cookies=cookies,
                data=self._build_signin_action_body(is_gambler),
                proxies=getattr(settings, "PROXY", None) if settings is not None else None,
                timeout=self.timeout,
                verify=False,
            )
        except Exception as exc:
            return False, {
                "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
                "ok": False,
                "status_code": 0,
                "trigger": trigger,
                "is_gambler": bool(is_gambler),
                "status": "签到失败",
                "message": f"Next Action 签到请求异常: {exc}",
                "data": {},
                "source": "hdhive_web_next_action",
            }, f"Next Action 签到请求异常: {exc}"

        redirect_target = str(response.headers.get("x-action-redirect") or response.headers.get("Location") or "").strip()
        if "/login" in redirect_target:
            message = "影巢网页 Cookie 已失效，请先在 HDHiveDailySign 中更新 Cookie 或重新自动登录"
            result = {
                "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
                "ok": False,
                "status_code": response.status_code,
                "trigger": trigger,
                "is_gambler": bool(is_gambler),
                "status": "签到失败",
                "message": message,
                "data": {"redirect": redirect_target},
                "source": "hdhive_web_next_action",
            }
            return False, result, message
        if response.status_code in (404, 405):
            message = f"影巢网页签到入口暂不可用或 Cookie 已失效（HTTP {response.status_code}），请更新本插件里的影巢网页 Cookie 后重试"
            result = {
                "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
                "ok": False,
                "status_code": response.status_code,
                "trigger": trigger,
                "is_gambler": bool(is_gambler),
                "status": "签到失败",
                "message": message,
                "data": {},
                "source": "hdhive_web_next_action",
            }
            return False, result, message

        response_text = ""
        try:
            response_text = response.content.decode("utf-8", errors="ignore")
        except Exception:
            response_text = response.text or ""
        success, message = self._parse_signin_action_response(response_text)
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": success,
            "status_code": response.status_code,
            "trigger": trigger,
            "is_gambler": bool(is_gambler),
            "status": "今日已签到" if "已经签到" in message or "签到过" in message or "明天再来" in message else "签到成功" if success else "签到失败",
            "message": message,
            "data": {},
            "source": "hdhive_web_next_action",
        }
        return success, result, message
