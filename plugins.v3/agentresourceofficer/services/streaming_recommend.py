"""
流媒体推荐 — TMDB Discover 直连服务

直接调用 TMDB discover API，不走 MoviePilot RecommendChain。
原因：RecommendChain 不支持 with_watch_providers + 时间窗口组合筛选。

支持的能力：
- 按流媒体平台聚合（Netflix / Disney+ / Apple TV+ / Prime Video）
- 严格按时间窗口过滤（本月 / 近N天）
- 按热度 + 评分 + 投票人数综合排序
- 区分电影 / 剧集 / 全部
"""

import json
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

# TMDB Watch Provider ID 映射
PROVIDER_MAP: Dict[str, int] = {
    "netflix": 8,
    "disney": 337,
    "disney+": 337,
    "apple": 384,
    "apple tv+": 384,
    "prime": 10,
    "prime video": 10,
    "amazon": 10,
}

# 默认聚合平台
DEFAULT_PROVIDER_IDS: List[int] = [8, 337, 384, 10]

# 默认地区（CN / US）
DEFAULT_WATCH_REGION = "US"

# 综合排序权重
SCORE_WEIGHTS = {
    "popularity": 0.4,
    "vote_average": 0.35,
    "vote_count_norm": 0.15,
    "freshness": 0.1,
}


class StreamingRecommendService:
    """TMDB Discover 直连，返回流媒体推荐列表"""

    def __init__(self, tmdb_api_key: str):
        self._api_key = tmdb_api_key.strip()

    # ─── 公开入口 ────────────────────────────────────────────────

    async def query(
        self,
        *,
        media_type: str = "all",
        intent: str = "hot",
        start_date: str = "",
        end_date: str = "",
        window_days: int = 90,
        providers: Optional[List[int]] = None,
        watch_region: str = DEFAULT_WATCH_REGION,
        limit: int = 15,
    ) -> Dict[str, Any]:
        """
        查询流媒体推荐。

        返回:
            {
                "success": bool,
                "message": str,
                "items": [ { index, title, year, media_type, release_date,
                             popularity, vote_average, vote_count,
                             providers_str, reason } ],
                "query_params": { ... },
            }
        """
        if not self._api_key:
            return {
                "success": False,
                "message": "TMDB API Key 未配置，无法查询流媒体推荐。",
                "items": [],
                "query_params": {},
            }

        provider_ids = providers or DEFAULT_PROVIDER_IDS
        media_type = (media_type or "all").lower()
        intent = (intent or "hot").lower()

        # ── 时间窗口 ──
        final_start, final_end = self._resolve_time_range(
            start_date=start_date,
            end_date=end_date,
            window_days=window_days,
        )

        # ── 分别查电影和剧集 ──
        all_items: List[Dict[str, Any]] = []

        if media_type in ("movie", "all"):
            movie_items = await self._discover(
                media_category="movie",
                intent=intent,
                start_date=final_start,
                end_date=final_end,
                provider_ids=provider_ids,
                watch_region=watch_region,
                limit=limit if media_type == "movie" else limit * 2,
            )
            all_items.extend(movie_items)

        if media_type in ("tv", "all"):
            tv_items = await self._discover(
                media_category="tv",
                intent=intent,
                start_date=final_start,
                end_date=final_end,
                provider_ids=provider_ids,
                watch_region=watch_region,
                limit=limit if media_type == "tv" else limit * 2,
            )
            all_items.extend(tv_items)

        # ── 综合排序并截断 ──
        ranked = self._rank(all_items, intent=intent)
        trimmed = ranked[:limit]

        # ── 编号 & 推荐理由 ──
        for idx, item in enumerate(trimmed, start=1):
            item["index"] = idx
            item["reason"] = self._generate_reason(item, intent)

        return {
            "success": True,
            "message": "",
            "items": trimmed,
            "query_params": {
                "media_type": media_type,
                "intent": intent,
                "start_date": final_start,
                "end_date": final_end,
                "provider_ids": provider_ids,
                "watch_region": watch_region,
                "count": len(trimmed),
            },
        }

    # ─── TMDB Discover 直连 ──────────────────────────────────────

    async def _discover(
        self,
        *,
        media_category: str,
        intent: str,
        start_date: str,
        end_date: str,
        provider_ids: List[int],
        watch_region: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        调用 TMDB discover/movie 或 discover/tv。
        返回标准化的条目列表。
        """
        endpoint = "movie" if media_category == "movie" else "tv"
        date_field = (
            "primary_release_date.gte" if media_category == "movie"
            else "first_air_date.gte"
        )
        date_field_end = (
            "primary_release_date.lte" if media_category == "movie"
            else "first_air_date.lte"
        )

        params: Dict[str, Any] = {
            "api_key": self._api_key,
            "language": "zh-CN",
            "sort_by": "popularity.desc",
            "watch_region": watch_region,
            "with_watch_providers": "|".join(str(p) for p in provider_ids),
            "with_watch_monetization_types": "flatrate",
            "vote_count.gte": self._min_vote_count(intent),
            "page": 1,
        }

        # 严格时间过滤
        if start_date:
            params[date_field] = start_date
        if end_date:
            params[date_field_end] = end_date

        url = f"https://api.themoviedb.org/3/discover/{endpoint}?" + urlencode(params)

        try:
            request = UrlRequest(url=url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", "ignore"))
        except Exception as exc:
            return []

        raw_results = payload.get("results") or []
        if not isinstance(raw_results, list):
            return []

        items: List[Dict[str, Any]] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            item = self._normalize_item(raw, media_category)
            if item:
                items.append(item)

        return items[:limit * 2]

    def _normalize_item(self, raw: Dict[str, Any], media_category: str) -> Optional[Dict[str, Any]]:
        """把 TMDB 原始条目转为标准格式"""
        title = (
            raw.get("title")
            or raw.get("name")
            or raw.get("original_title")
            or raw.get("original_name")
            or ""
        ).strip()
        if not title:
            return None

        release_date = raw.get("release_date") or raw.get("primary_release_date") or raw.get("first_air_date") or ""
        year = str(release_date)[:4] if release_date else ""

        popularity = float(raw.get("popularity") or 0)
        vote_average = float(raw.get("vote_average") or 0)
        vote_count = int(raw.get("vote_count") or 0)

        # 处理 media_type
        raw_type = raw.get("media_type") or ""
        if media_category == "movie":
            display_type = "电影"
        elif media_category == "tv":
            display_type = "剧集"
        else:
            display_type = "电影" if raw_type == "movie" else "剧集"

        # provider_ids 从原数据获取
        provider_ids_raw = raw.get("origin_country") or []

        return {
            "title": title,
            "year": year,
            "media_type": display_type,
            "release_date": release_date,
            "popularity": round(popularity, 1),
            "vote_average": round(vote_average, 1),
            "vote_count": vote_count,
            "tmdb_id": raw.get("id"),
            "provider_ids_raw": provider_ids_raw,
        }

    # ─── 综合排序 ────────────────────────────────────────────────

    def _rank(self, items: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
        """
        按综合分排序。
        intent 影响权重：big_titles 偏重评分，hot 偏重热度，new 偏重新鲜度。
        """
        if not items:
            return []

        weights = dict(SCORE_WEIGHTS)
        if intent == "big_titles":
            weights["vote_average"] = 0.45
            weights["popularity"] = 0.25
            weights["vote_count_norm"] = 0.2
            weights["freshness"] = 0.1
        elif intent == "new":
            weights["freshness"] = 0.3
            weights["popularity"] = 0.3
            weights["vote_average"] = 0.25
            weights["vote_count_norm"] = 0.15

        # 归一化基准
        max_pop = max((i.get("popularity") or 0) for i in items) or 1
        max_votes = max((i.get("vote_count") or 0) for i in items) or 1

        today = date.today()

        def score(item: Dict[str, Any]) -> float:
            pop = (item.get("popularity") or 0) / max_pop
            avg = (item.get("vote_average") or 0) / 10.0
            vc = (item.get("vote_count") or 0) / max_votes
            # 新鲜度：发布越近分越高（90天内线性衰减）
            try:
                rd = item.get("release_date") or ""
                days_ago = (today - date.fromisoformat(rd[:10])).days if rd and len(rd) >= 10 else 180
            except Exception:
                days_ago = 180
            freshness = max(0.0, 1.0 - days_ago / 180.0)
            return (
                weights["popularity"] * pop
                + weights["vote_average"] * avg
                + weights["vote_count_norm"] * vc
                + weights["freshness"] * freshness
            )

        items.sort(key=score, reverse=True)
        return items

    # ─── 推荐理由 ────────────────────────────────────────────────

    def _generate_reason(self, item: Dict[str, Any], intent: str) -> str:
        """基于数据生成一句话推荐理由，不经过 LLM"""
        avg = item.get("vote_average") or 0
        pop = item.get("popularity") or 0
        votes = item.get("vote_count") or 0

        if intent == "big_titles":
            if avg >= 8.0 and votes >= 500:
                return "高口碑大作"
            if avg >= 7.0 and votes >= 200:
                return "口碑不错"
            return "值得关注"

        if intent == "new":
            if pop >= 500:
                return "新上线即爆"
            if avg >= 7.0:
                return "新上线口碑佳"
            return "新上线"

        # hot
        if avg >= 8.0 and pop >= 600:
            return "口碑热度双高"
        if pop >= 800:
            return "热度爆棚"
        if avg >= 7.5:
            return "口碑出色"
        if votes >= 1000:
            return "大众高关注"
        return "近期热门"

    # ─── 时间范围 ────────────────────────────────────────────────

    @staticmethod
    def _resolve_time_range(
        *,
        start_date: str = "",
        end_date: str = "",
        window_days: int = 90,
    ) -> tuple[str, str]:
        """
        给定起止日期或窗口天数，返回严格时间范围（YYYY-MM-DD）。
        - specific_month / this_month：严格按自然月
        - recent：从今天往前推 window_days 天
        - last_month：上一个自然月
        """
        today = date.today()

        # 如果都给了就直接用
        if start_date and end_date:
            return start_date[:10], end_date[:10]

        # 如果只给了 start_date，end_date 默认今天
        if start_date and not end_date:
            return start_date[:10], today.isoformat()

        # 如果只给了 end_date，start_date 往前推 window_days
        if end_date and not start_date:
            try:
                end_d = date.fromisoformat(end_date[:10])
            except Exception:
                end_d = today
            start_d = end_d - timedelta(days=window_days)
            return start_d.isoformat(), end_d.isoformat()

        # 都没给：默认最近 window_days
        start_d = today - timedelta(days=window_days)
        return start_d.isoformat(), today.isoformat()

    @staticmethod
    def _min_vote_count(intent: str) -> int:
        """不同 intent 的最低投票人数门槛"""
        if intent == "big_titles":
            return 300
        if intent == "new":
            return 30
        return 100
