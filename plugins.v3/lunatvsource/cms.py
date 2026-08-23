"""Apple CMS V10 configuration and response adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_EPISODE_RE = re.compile(
    r"(?:S(?P<season>\d{1,3})\s*E(?P<episode>\d{1,4}))|"
    r"(?:第\s*(?P<cn_episode>\d{1,4})\s*[集话])|"
    r"(?:^|[\s._\-])(?P<bare_episode>\d{1,4})(?:$|[\s._\-])",
    re.IGNORECASE,
)
_SEASON_RE = re.compile(
    r"(?:S\s*(?P<s_season>\d{1,3})\s*(?:季|SEASON)?|"
    r"第\s*(?P<season>\d{1,3})\s*季)",
    re.IGNORECASE,
)
_CN_SEASON_RE = re.compile(
    r"(?:第\s*)(?P<season>[一二两三四五六七八九十百千万]+)\s*季",
    re.IGNORECASE,
)
_SEASON_RANGE_RE = re.compile(
    r"(?:第\s*)?(?P<start>\d{1,3})\s*[-~至]\s*(?P<end>\d{1,3})\s*季|"
    r"S(?P<sstart>\d{1,3})\s*[-~至]\s*S?(?P<send>\d{1,3})",
    re.IGNORECASE,
)


def _season_range(label: str) -> Tuple[int, int]:
    """Return an explicit season range from a CMS title, if present."""

    match = _SEASON_RANGE_RE.search(_text(label))
    if not match:
        return 1, 1
    start = int(match.group("start") or match.group("sstart") or 1)
    end = int(match.group("end") or match.group("send") or start)
    return (start, end) if end >= start else (end, start)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _chinese_number(value: str) -> int:
    """Convert the small Chinese numerals commonly used in CMS season names."""

    text = _text(value).replace("两", "二")
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if all(char in digits for char in text):
        result = 0
        for char in text:
            result = result * 10 + digits[char]
        return result
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return 0


def _json_get(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "LunaTVSource/0.1 MoviePilot"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _split_player_values(value: str) -> List[str]:
    return [part.strip() for part in _text(value).split("$$$") if part.strip()]


def _extract_season_episode(label: str, default_season: int = 1) -> Tuple[int, int]:
    match = _EPISODE_RE.search(_text(label))
    if not match:
        return default_season, 1
    season = int(match.group("season") or default_season)
    episode = int(match.group("episode") or match.group("cn_episode") or match.group("bare_episode") or 1)
    return season, episode


def _extract_season(label: str, default_season: int = 1) -> int:
    match = _SEASON_RE.search(_text(label))
    if match:
        return int(match.group("season") or match.group("s_season"))
    match = _CN_SEASON_RE.search(_text(label))
    return _chinese_number(match.group("season")) if match else default_season


def _season_hint(label: str, default_season: int = 1) -> int:
    """从线路标题中读取季号；没有季号时保留默认值。"""
    return _extract_season(label, default_season)


def _has_explicit_season(label: str) -> bool:
    value = _text(label)
    return bool(
        re.search(r"S\s*\d{1,3}\s*E\s*\d{1,4}", value, re.IGNORECASE)
        or re.search(r"(?:第\s*)?\d{1,3}\s*季", value, re.IGNORECASE)
        or _CN_SEASON_RE.search(value)
        or re.search(r"\bS\s*\d{1,3}\b", value, re.IGNORECASE)
    )


def _parse_play_urls(
    play_from: Any,
    play_url: Any,
    default_season: int = 1,
    default_season_known: bool = True,
) -> List["CmsEpisode"]:
    from_values = _split_player_values(_text(play_from))
    url_values = _split_player_values(_text(play_url))
    if not url_values:
        return []

    # A CMS response may list one player name and one URL group, or several
    # groups in matching order.  The first group is the stable fallback.
    selected_groups: List[Tuple[str, str]] = []
    if from_values:
        pairs = list(zip(from_values, url_values))
        has_season_groups = any(_extract_season(name, 0) > 0 for name, _ in pairs)
        preferred = [
            pair
            for pair in pairs
            if any(token in pair[0].lower() for token in ("m3u8", "高清", "在线播放", "在线"))
        ]
        # Keep all season-labelled groups; otherwise select one stable
        # playable group to avoid downloading the same episode repeatedly from
        # backup players.
        selected_groups = pairs if has_season_groups else (preferred[:1] or pairs[:1])
    else:
        selected_groups = [("", url_values[0])]

    episodes: List[CmsEpisode] = []
    for group_name, group in selected_groups:
        for raw in group.split("#"):
            raw = raw.strip()
            if not raw:
                continue
            if "$" in raw:
                label, url = raw.split("$", 1)
            else:
                label, url = "", raw
            url = url.strip()
            parsed_url = urllib.parse.urlparse(url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                continue
            season, episode = _extract_season_episode(label, _season_hint(group_name, default_season))
            season_known = default_season_known or _has_explicit_season(group_name) or _has_explicit_season(label)
            episodes.append(
                CmsEpisode(
                    season=season,
                    episode=episode,
                    label=label.strip(),
                    url=url,
                    season_known=season_known,
                )
            )
    deduped: Dict[Tuple[int, int, str], CmsEpisode] = {}
    for item in episodes:
        deduped[(item.season, item.episode, item.url)] = item
    return sorted(deduped.values(), key=lambda item: (item.season, item.episode, item.url))


def _source_status(comment: str) -> Tuple[str, str]:
    """Map a LunaTV source remark to a non-live display state."""

    remark = _text(comment).casefold()
    if any(token in remark for token in ("403", "失效", "不可用")):
        return "error", "异常"
    if "不稳定" in remark:
        return "warning", "不稳定"
    if "备用" in remark:
        return "warning", "备用"
    return "ready", "已加载"


def _source_search_status(comment: str, status: str) -> Tuple[str, str]:
    """Map a LunaTV source remark to its documented search capability."""

    if status == "error":
        return "unavailable", "不可用"

    remark = _text(comment).casefold()
    # ``无搜索结果`` is a distinct configured capability note.  Check it
    # before the unsupported wording so it is never presented as a disabled
    # search source by a future broader matching rule.
    if "无搜索结果" in remark:
        return "empty", "无结果"
    if any(token in remark for token in ("暂不支持搜索", "无法搜索", "禁止搜索")):
        return "unsupported", "不支持"
    if "污染搜索结果" in remark:
        return "degraded", "结果异常"
    return "supported", "支持"


@dataclass(frozen=True)
class CmsSource:
    key: str
    name: str
    api: str
    detail: str = ""
    comment: str = ""

    def to_dict(self) -> Dict[str, str]:
        """Return stable source metadata for the plugin workbench.

        The upstream LunaTV configuration carries human-maintained remarks, not
        health-check telemetry.  Keep the presentation state derived solely
        from that remark so the UI cannot imply a live availability probe.
        """

        status, status_label = _source_status(self.comment)
        search_status, search_label = _source_search_status(self.comment, status)
        return {
            "key": self.key,
            "name": self.name,
            "api": self.api,
            "detail": self.detail,
            "comment": self.comment,
            "url": self.detail or self.api,
            "status": status,
            "status_label": status_label,
            "search_status": search_status,
            "search_label": search_label,
        }


@dataclass(frozen=True)
class CmsEpisode:
    season: int
    episode: int
    label: str
    url: str
    season_known: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "season": self.season,
            "episode": self.episode,
            "label": self.label,
            "url": self.url,
            "season_known": self.season_known,
        }


@dataclass(frozen=True)
class CmsResult:
    source_key: str
    source_name: str
    vod_id: str
    title: str
    year: str
    media_type: str
    remark: str
    episodes: Tuple[CmsEpisode, ...] = field(default_factory=tuple)
    detail: str = ""
    season_range: Tuple[int, int] = (1, 1)
    season_ambiguous: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_key": self.source_key,
            "source_name": self.source_name,
            "vod_id": self.vod_id,
            "title": self.title,
            "year": self.year,
            "media_type": self.media_type,
            "remark": self.remark,
            "episodes": [episode.to_dict() for episode in self.episodes],
            "detail": self.detail,
            "season_range": list(self.season_range),
            "season_ambiguous": self.season_ambiguous,
        }


def _media_type(item: Mapping[str, Any]) -> str:
    value = f"{item.get('type_name', '')} {item.get('vod_class', '')}".lower()
    if "电影" in value and "电视剧" not in value:
        return "movie"
    if any(token in value for token in ("电视剧", "连续剧", "tv", "剧集", "综艺", "儿童", "少儿")):
        return "tv"
    # 动漫/动画/纪录片在 CMS 中同时承载电影和剧集。 只有出现季集
    # 标记或明确的多集播放列表时才按电视剧处理，避免把动画电影误放到 TV 库。
    if any(token in value for token in ("动漫", "动画", "纪录")):
        title = _text(item.get("vod_name"))
        play_url = _text(item.get("vod_play_url"))
        if (
            _SEASON_RE.search(title)
            or _CN_SEASON_RE.search(title)
            or re.search(r"第\s*\d{1,4}\s*[集话]", title)
            or "#" in play_url
        ):
            return "tv"
    return "movie"


def _source_key(api_key: str, item: Mapping[str, Any]) -> str:
    return _text(item.get("vod_id") or item.get("vod_name") or api_key)


def _result_from_item(source: CmsSource, item: Mapping[str, Any]) -> CmsResult:
    title = _text(item.get("vod_name") or item.get("vod_en"))
    year = _text(item.get("vod_year"))
    media_type = _media_type(item)
    # 有些 CMS 只把“1-8季”写在片名里，线路名和集名都没有季号。
    # 这时至少保留起始季，避免所有集被误标成 S01；真正分季的线路仍优先使用线路标题。
    title_season = _extract_season(title, 1)
    season_range = _season_range(title)
    episodes = tuple(
        _parse_play_urls(
            item.get("vod_play_from"),
            item.get("vod_play_url"),
            title_season,
            default_season_known=season_range[0] == season_range[1],
        )
    )
    if media_type == "movie" and not episodes:
        direct_url = _text(item.get("vod_play_url"))
        if direct_url.startswith("http"):
            episodes = (CmsEpisode(season=1, episode=1, label="正片", url=direct_url),)
    season_ambiguous = season_range[1] > season_range[0] and not all(
        episode.season_known for episode in episodes
    )
    return CmsResult(
        source_key=source.key,
        source_name=source.name,
        vod_id=_source_key(source.key, item),
        title=title,
        year=year,
        media_type=media_type,
        remark=_text(item.get("vod_remarks")),
        episodes=episodes,
        detail=source.detail,
        season_range=season_range,
        season_ambiguous=season_ambiguous,
    )


def apply_season_counts(result: CmsResult, season_counts: Mapping[int, int]) -> CmsResult:
    """Map a flat multi-season CMS list when TMDB supplies exact counts.

    A title range alone is not enough to infer season boundaries.  We only
    rewrite episodes when the CMS list length exactly equals the sum of the
    known season counts, avoiding silently putting episodes in the wrong
    season.
    """

    if not result.season_ambiguous or not season_counts:
        return result
    seasons = sorted(
        (int(season), int(count))
        for season, count in season_counts.items()
        if int(season) >= result.season_range[0]
        and int(season) <= result.season_range[1]
        and int(count) > 0
    )
    if not seasons or sum(count for _, count in seasons) != len(result.episodes):
        return result
    mapped: List[CmsEpisode] = []
    offset = 0
    for season, count in seasons:
        for episode_number in range(1, count + 1):
            episode = result.episodes[offset]
            mapped.append(replace(episode, season=season, episode=episode_number, season_known=True))
            offset += 1
    return replace(result, episodes=tuple(mapped), season_ambiguous=False)


def _merge_detail_item(item: Mapping[str, Any], detail: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge a detail response without discarding list metadata.

    Apple CMS installations commonly omit ``vod_play_url`` from ``ac=list``
    results and only expose the playable URLs from ``ac=detail``.  Keep the
    list item as the base so a sparse detail response cannot erase its title or
    type fields.
    """

    merged = dict(item)
    for key, value in detail.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def parse_config(payload: Mapping[str, Any], allowlist: Sequence[str] = ()) -> List[CmsSource]:
    raw_sites = payload.get("api_site") if isinstance(payload, Mapping) else None
    if not isinstance(raw_sites, Mapping):
        return []
    allowed = {str(item).strip().lower() for item in allowlist if str(item).strip()}
    sources: List[CmsSource] = []
    for key, value in raw_sites.items():
        if not isinstance(value, Mapping):
            continue
        api = _text(value.get("api"))
        if not api:
            continue
        key_text = _text(key).lower()
        host = urllib.parse.urlparse(api).hostname or key_text
        if allowed and not ({key_text, host.lower()} & allowed):
            continue
        sources.append(
            CmsSource(
                key=key_text,
                name=_text(value.get("name") or key),
                api=api,
                detail=_text(value.get("detail")),
                comment=_text(value.get("_comment")),
            )
        )
    return sources


def load_sources_from_url(url: str, timeout: float = 15, allowlist: Sequence[str] = ()) -> List[CmsSource]:
    return parse_config(_json_get(url, timeout), allowlist=allowlist)


class AppleCmsClient:
    def __init__(
        self,
        sources: Sequence[CmsSource],
        timeout: float = 15,
        parallel_wait_timeout: Optional[float] = None,
    ) -> None:
        self.sources = list(sources)
        self.timeout = timeout
        self.parallel_wait_timeout = parallel_wait_timeout

    def _parallel_wait_seconds(self) -> float:
        """Return the total budget for a parallel source search.

        The optional override keeps the timeout behavior deterministic in
        tests; production callers use a bounded budget derived from the
        per-source request timeout.
        """

        if self.parallel_wait_timeout is not None:
            return max(0.0, float(self.parallel_wait_timeout))
        return max(20.0, min(30.0, float(self.timeout) * 2))

    def _request(self, source: CmsSource, **params: Any) -> Mapping[str, Any]:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value not in (None, "")})
        separator = "&" if "?" in source.api else "?"
        url = f"{source.api}{separator}{query}" if query else source.api
        payload = _json_get(url, self.timeout)
        if not isinstance(payload, Mapping):
            raise ValueError("CMS 响应不是 JSON 对象")
        return payload

    @staticmethod
    def _items(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        items = payload.get("list") or payload.get("data") or []
        if isinstance(items, Mapping):
            items = items.get("list") or []
        return [item for item in items if isinstance(item, Mapping)]

    def _enrich_item(self, source: CmsSource, item: Mapping[str, Any]) -> Mapping[str, Any]:
        """Fetch the playable detail payload when the list response is sparse."""

        if _text(item.get("vod_play_url")):
            return item
        vod_id = _text(item.get("vod_id"))
        if not vod_id:
            return item
        try:
            payload = self._request(source, ac="detail", ids=vod_id)
            detail_items = self._items(payload)
            if detail_items:
                return _merge_detail_item(item, detail_items[0])
        except Exception:
            # A broken detail endpoint should not hide a valid list result.
            pass
        return item

    def _search_source(
        self,
        source: CmsSource,
        query: str,
        limit: int,
        enrich: bool = True,
        require_playable: bool = False,
    ) -> List[CmsResult]:
        source_results: List[CmsResult] = []
        try:
            payload = self._request(source, ac="list", wd=query, pg=1)
            items = self._items(payload)
            if not items:
                payload = self._request(source, ac="list", wd=query, pg=1, pages=1)
                items = self._items(payload)
            for item in items[:limit]:
                result = _result_from_item(
                    source,
                    self._enrich_item(source, item) if enrich else item,
                )
                if require_playable and not result.episodes:
                    continue
                source_results.append(result)
        except Exception:
            # A single third-party source must not block the rest.
            return []
        return source_results

    def detail(self, source_key: str, vod_id: str) -> Optional[CmsResult]:
        """按插件媒体身份读取单条详情，供 MoviePilot 原生订阅复用。"""
        source = next((item for item in self.sources if item.key == str(source_key).lower()), None)
        if source is None:
            return None
        payload = self._request(source, ac="detail", ids=vod_id)
        items = self._items(payload)
        if not items:
            return None
        return _result_from_item(source, self._enrich_item(source, items[0]))

    def search(
        self,
        query: str,
        limit: int = 20,
        stop_after_first_source: bool = False,
        enrich: bool = True,
        require_playable: bool = False,
        source_limit: Optional[int] = None,
        max_workers: int = 1,
    ) -> List[CmsResult]:
        if limit <= 0:
            return []
        per_source_limit = max(1, min(int(source_limit or limit), int(limit)))
        results: List[CmsResult] = []
        ordered_sources = list(self.sources)
        seen: set[Tuple[str, str]] = set()
        max_workers = max(1, int(max_workers))
        if stop_after_first_source or max_workers == 1 or len(ordered_sources) <= 1:
            for source in ordered_sources:
                source_result_count = len(results)
                for result in self._search_source(
                    source,
                    query=query,
                    limit=per_source_limit,
                    enrich=enrich,
                    require_playable=require_playable,
                ):
                    key = (result.source_key, result.vod_id)
                    if result.title and key not in seen:
                        seen.add(key)
                        results.append(result)
                if stop_after_first_source and len(results) > source_result_count:
                    break
            return results[:limit]

        futures = []
        executor = ThreadPoolExecutor(max_workers=min(max_workers, len(ordered_sources)))
        try:
            for idx, source in enumerate(ordered_sources):
                futures.append(
                    (
                        idx,
                        source,
                        executor.submit(
                            self._search_source,
                            source=source,
                            query=query,
                            limit=per_source_limit,
                            enrich=enrich,
                            require_playable=require_playable,
                        ),
                    )
                )
            done_futures, pending_futures = wait(
                [future for _, _, future in futures],
                timeout=self._parallel_wait_seconds(),
            )
            # Do not leave queued sources running after the total search
            # budget expires. Running requests cannot be forcefully stopped,
            # but queued futures can be cancelled before executor shutdown.
            for future in pending_futures:
                future.cancel()
            source_results: Dict[int, List[CmsResult]] = {}
            for idx, source, future in futures:
                if future not in done_futures:
                    continue
                try:
                    source_results[idx] = future.result()
                except Exception:
                    source_results[idx] = []
            for idx in sorted(source_results):
                for result in source_results[idx]:
                    key = (result.source_key, result.vod_id)
                    if result.title and key not in seen:
                        seen.add(key)
                        results.append(result)
                        if len(results) >= limit:
                            return results
            return results[:limit]
        finally:
            # ``wait=False`` is intentional: a slow third-party source must
            # not hold up the native search response after the budget.
            executor.shutdown(wait=False, cancel_futures=True)
