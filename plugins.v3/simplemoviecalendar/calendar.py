"""Read-only public calendar adaptation, Beijing dates, and durable cache."""
from __future__ import annotations

import copy
import json
import math
import re
import threading
import time
from datetime import date, datetime, timezone
from urllib.parse import quote, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from app.sdk.network import RequestUtils

BASE_URL = 'https://ys.chenhao.net/'
DATA_URL = BASE_URL + 'calendar.json'
SOURCE = 'simplecalendar'
KINDS = {'digital': '数字发行', 'streaming': '平台上线', 'physical': '实体盘'}
BEIJING = ZoneInfo('Asia/Shanghai')
MAX_BYTES = 8 * 1024 * 1024


def beijing_today(now: datetime | None = None) -> str:
    """Compute the current Beijing calendar day independently of export time."""
    return (now or datetime.now(timezone.utc)).astimezone(BEIJING).date().isoformat()


def _text(value) -> str:
    """Accept only source strings, avoiding accidental object representations."""
    return value.strip() if isinstance(value, str) else ''


def _stamp(value) -> datetime:
    """Require an ISO timestamp with an explicit timezone."""
    stamp = datetime.fromisoformat(_text(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('数据更新时间缺少时区')
    return stamp


def validate_snapshot(value) -> dict:
    """Reject incompatible or ambiguous public snapshots before replacement."""
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('日历数据格式不兼容，请更新插件')
    _stamp(value.get('generated_at'))
    for field, maximum in (('movies', 10000), ('releases', 50000)):
        items = value.get(field)
        if not isinstance(items, list) or len(items) > maximum:
            raise ValueError('日历数据结构无效')
        seen = set()
        for item in items:
            if not isinstance(item, dict) or not _text(item.get('id')) or item['id'] in seen:
                raise ValueError('日历条目 ID 无效或重复')
            if item['id'] != item['id'].strip():
                raise ValueError('日历条目 ID 含空白')
            seen.add(item['id'])
            if field == 'releases':
                if not _text(item.get('movie_id')):
                    raise ValueError('发行记录缺少影片 ID')
                if item.get('kind') is not None and not isinstance(item['kind'], str):
                    raise ValueError('发行类型格式无效')
    return copy.deepcopy(value)


def fetch_snapshot() -> dict:
    """Fetch only the public endpoint, limiting transfer size and socket wait."""
    request = RequestUtils(timeout=12, verify=True, headers={
        'Accept': 'application/json', 'User-Agent': 'SimpleMovieCalendar/0.1.5',
    })
    with request.get_stream(DATA_URL, raise_exception=True) as response:
        if response is None:
            raise OSError('日历数据请求失败')
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise ValueError('日历数据过大')
    return json.loads(content)


def asset_url(value) -> str | None:
    """Resolve public images and reject unsafe schemes, credentials and traversal."""
    text = _text(value)
    if not text or any(ord(c) < 32 for c in text) or '\\' in text:
        return None
    try:
        if '..' in unquote(urlsplit(text).path).split('/'):
            return None
        target = urljoin(BASE_URL, text)
        parsed = urlsplit(target)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            return None
        return target
    except ValueError:
        return None


def _valid_day(release: dict) -> bool:
    """Do not invent dates from partial or invalid source schedules."""
    value = release.get('date')
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    if release.get('date_precision') not in (None, '', 'day'):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def records(snapshot: dict, today: str, group: str = 'upcoming', kind: str = 'all', query: str = '') -> list[dict]:
    """Aggregate per film; filters choose the primary schedule, details keep all."""
    if group not in ('upcoming', 'recent', 'all') or kind not in ('all', *KINDS):
        raise ValueError('不支持的排期筛选')
    grouped = {}
    for release in snapshot['releases']:
        if _valid_day(release):
            grouped.setdefault(release['movie_id'], []).append(release)
    result = []
    query = query.strip().casefold()
    for movie in snapshot['movies']:
        if movie.get('hidden') or movie['id'] not in grouped:
            continue
        if query and query not in ' '.join(_text(movie.get(k)) for k in ('title_zh', 'title_original', 'title_source', 'imdb_id', 'douban_id')).casefold():
            continue
        releases = sorted(grouped[movie['id']], key=lambda r: r['date'])
        selected = [r for r in releases if kind == 'all' or r.get('kind') == kind]
        if not selected:
            continue
        future = next((r for r in selected if r['date'] >= today), None)
        upcoming = future is not None
        if (group == 'upcoming' and not upcoming) or (group == 'recent' and upcoming):
            continue
        result.append({'movie': movie, 'releases': releases, 'primary': future or selected[-1], 'upcoming': upcoming})
    # Match the public calendar: historical ties use descending stable ID.
    recent = sorted((r for r in result if not r['upcoming']), key=lambda r: (r['primary']['date'], r['movie']['id']), reverse=True)
    upcoming = sorted((r for r in result if r['upcoming']), key=lambda r: (not bool(r['movie'].get('pinned')), r['primary']['date'], r['movie']['id']))
    return upcoming + recent


def release_label(release: dict) -> str:
    """Keep multiline platforms and editions without guessing a play URL."""
    return ' · '.join(filter(None, (_text(release.get('platform')) or KINDS.get(release.get('kind'), '发行'), _text(release.get('edition')), _text(release.get('region')))))


def release_line(release: dict) -> str:
    """Display a concrete time only when supplied, preserving its timezone."""
    stamp = release['date']
    clock, zone = _text(release.get('time')), _text(release.get('timezone'))
    if re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
        label = '北京时间' if zone == 'Asia/Shanghai' else zone
        stamp += ' ' + ' '.join(filter(None, (label, clock)))
    return stamp + ' · ' + release_label(release)


def _rating(value) -> float | None:
    """Null, booleans and invalid scores must never become fabricated ratings."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 10:
        return float(value)
    return None


def _vote_label(value, provider: str) -> str | None:
    """Format counts like the public website, preserving source abbreviations."""
    if isinstance(value, float) and value.is_integer() and 0 <= value < 2 ** 53:
        value = int(value)
    raw = str(value).strip().replace(',', '')
    if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?[KMB]', raw, re.IGNORECASE):
        return raw.upper()
    if not re.fullmatch(r'[0-9]+', raw):
        return None
    digits = raw.lstrip('0') or '0'
    if len(digits) > 16:
        return None
    count = int(digits)
    if count >= 2 ** 53:
        return None
    if provider == 'imdb' and count >= 1000:
        for suffix, scale in (('K', 10**3), ('M', 10**6), ('B', 10**9), ('T', 10**12)):
            tenths = (count * 10 + scale // 2) // scale
            if tenths < 10_000 or suffix == 'T':
                whole, fraction = divmod(tenths, 10)
                label = f'{whole}.{fraction}' if fraction else str(whole)
                return label + suffix
    return f'{count:,}'


def rating_rows(movie: dict) -> list[tuple[str, str, str]]:
    """Build provider, score and vote copy using the public website's rules."""
    rows = []
    for provider in ('douban', 'imdb'):
        source_id = movie.get(f'{provider}_id')
        rating = _rating(movie.get(f'{provider}_rating'))
        if not source_id and (provider == 'douban' or rating is None):
            continue
        if rating is not None:
            score = f'{rating:.1f}'
        else:
            unrated = provider == 'imdb' or movie.get('douban_rating_state') == 'unrated'
            score = '未开分' if unrated else '—'
        count = _vote_label(movie.get(f'{provider}_votes'), provider)
        votes = ''
        if count is not None and (count != '0' or rating is not None):
            unit = '条评价' if provider == 'douban' else '评价'
            votes = f'（{count}{unit}）'
        elif rating is not None:
            votes = '（人数暂缺）'
        rows.append((provider, score, votes))
    return rows


def release_timing(day: str, today: str) -> str:
    """Describe the distance between two Beijing calendar dates."""
    distance = (date.fromisoformat(day) - date.fromisoformat(today)).days
    if distance > 0:
        return f'还有 {distance} 天'
    return '今日发行' if distance == 0 else '已到发行日'


def beijing_timestamp(value: str) -> str:
    """Display the source snapshot's timestamp in Beijing time."""
    return _stamp(value).astimezone(BEIJING).strftime('%Y-%m-%d %H:%M')


def media_payload(record: dict, snapshot: dict, today: str, stale: bool = False) -> dict:
    """Build fields accepted by the host DTO and domain MediaInfo objects."""
    movie, release = record['movie'], record['primary']
    title = next((_text(movie.get(k)) for k in ('title_zh', 'title_original', 'title_source') if _text(movie.get(k))), '资料待补齐')
    timing = release_timing(release['date'], today)
    tagline = f'{release["date"]} · {release_label(release)} · {timing}'
    sections = [tagline]
    if movie.get('pinned') and record['upcoming']:
        sections.append('重点关注')
    scores = []
    douban, imdb = _rating(movie.get('douban_rating')), _rating(movie.get('imdb_rating'))
    if movie.get('douban_id'):
        scores.append('豆瓣 ' + (f'{douban:.1f}' if douban is not None else '未开分' if movie.get('douban_rating_state') == 'unrated' else '暂无评分'))
    if imdb is not None:
        scores.append(f'IMDb {imdb:.1f}')
    if scores:
        sections.append(' · '.join(scores))
    sections.append('发行排期：\n' + '\n'.join(release_line(r) for r in record['releases']))
    link = BASE_URL + '#movie=' + quote(movie['id'], safe='')
    updated = beijing_timestamp(snapshot['generated_at'])
    if stale:
        sections.append('当前显示缓存数据，请留意更新时间。')
    sections.extend([f'数据更新于 {updated}（北京时间）', '排期不代表已核验上线或已有播放资源。', f'完整日历：{link}'])
    return {
        'media_source': SOURCE, 'media_id': movie['id'], 'type': '电影',
        'title': title, 'original_title': _text(movie.get('title_original')) or None,
        'year': str(movie['year']) if isinstance(movie.get('year'), int) and not isinstance(movie['year'], bool) else None,
        'title_year': f'{title} ({movie["year"]})' if movie.get('year') else title,
        'poster_path': asset_url(movie.get('poster_url')), 'backdrop_path': asset_url(movie.get('backdrop_url')),
        'release_date': release['date'], 'tagline': tagline, 'overview': '\n\n'.join(sections),
        'vote_average': douban if douban is not None else imdb,
        'homepage': link, 'imdb_id': _text(movie.get('imdb_id')) or None,
        'douban_id': _text(movie.get('douban_id')) or None,
    }


class CalendarCache:
    """Share one durable last-good snapshot across all views and refresh jobs."""

    def __init__(self, loader, save, fetch=fetch_snapshot, clock=time.time, interval=1800):
        """Recover validated persisted state without network work during creation."""
        self._save, self._fetch, self._clock, self.interval = save, fetch, clock, interval
        self._lock, self._refresh_lock = threading.RLock(), threading.Lock()
        self._snapshot, self._fetched_at, self._attempted_at = None, None, None
        self._error, self._persistence_error = '', ''
        try:
            state = loader()
            if isinstance(state, dict) and state.get('snapshot') is not None:
                self._snapshot = validate_snapshot(state['snapshot'])
                stamp = state.get('fetched_at')
                self._fetched_at = float(stamp) if isinstance(stamp, (float, int)) and math.isfinite(stamp) else None
        except Exception:
            self._error = '本地缓存不可用，等待重新获取日历'

    def refresh(self, force: bool = False) -> bool:
        """Bound concurrent work and preserve the last-good snapshot on any failure."""
        if not self._refresh_lock.acquire(blocking=False):
            return False
        try:
            with self._lock:
                now = self._clock()
                delay = 60 if self._error else self.interval
                previous = self._attempted_at if self._attempted_at is not None else self._fetched_at
                if not force and previous is not None and now - previous < delay:
                    return self._snapshot is not None
                self._attempted_at = now
            try:
                snapshot = validate_snapshot(self._fetch())
            except Exception:
                with self._lock:
                    self._error = '日历更新失败，请检查网络或数据格式；已有缓存继续保留'
                return False
            with self._lock:
                self._snapshot, self._fetched_at, self._error = snapshot, self._clock(), ''
                state = {'snapshot': copy.deepcopy(snapshot), 'fetched_at': self._fetched_at}
            try:
                self._save(state)
                with self._lock:
                    self._persistence_error = ''
            except Exception:
                with self._lock:
                    self._persistence_error = '日历已更新，但缓存保存失败；重启后可能使用旧数据'
            return True
        finally:
            self._refresh_lock.release()

    def view(self) -> dict:
        """Return defensive copies; staleness is recomputed rather than persisted."""
        with self._lock:
            now = self._clock()
            stale = bool(self._error) or self._fetched_at is None or now - self._fetched_at > self.interval * 2
            if self._snapshot:
                stale = stale or now - _stamp(self._snapshot['generated_at']).timestamp() > 48 * 3600
            return {'snapshot': copy.deepcopy(self._snapshot), 'fetched_at': self._fetched_at,
                    'attempted_at': self._attempted_at, 'error': self._error,
                    'persistence_error': self._persistence_error, 'stale': stale}
