"""MoviePilot V3: read-only release calendar in discovery and an optional widget."""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

from app import schemas
from app.schemas.types import ChainEventType, MediaSource, MediaType
from app.sdk import scheduler as scheduler_sdk
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.media import MediaInfo as DomainMediaInfo
from app.sdk.plugin import _PluginBase

from .calendar import BEIJING, SOURCE, CalendarCache, beijing_today, fetch_snapshot, media_payload, records
from .ui import calendar_nodes, config_form, dashboard_nodes, filter_ui


class SimpleMovieCalendar(_PluginBase):
    """Use the public calendar without collecting metadata or writing subscriptions."""

    plugin_name = '简单观影日历'
    plugin_desc = '查看电影数字版、蓝光和国内电影流媒体上线时间，可手动添加到MP首页仪表盘方便查看。'
    plugin_icon = 'https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/SimpleMovieCalendar.png'
    plugin_version = "0.1.6"
    plugin_author = '随风飞翔'
    author_url = 'https://ys.chenhao.net/'
    plugin_config_prefix = 'simplemoviecalendar_'
    plugin_order = 50
    auth_level = 1

    def __init__(self):
        """Give each running plugin instance its own locks and cache generation."""
        super().__init__()
        self._lock = threading.RLock()
        self._generation = 0
        self._enabled = False
        self._cache = None
        self._refresh_minutes = 30
        self._dashboard_count = 6

    @staticmethod
    def _bounded(value, default: int, minimum: int, maximum: int) -> int:
        """Normalize text inputs, rejecting malformed values without breaking reload."""
        try:
            return min(maximum, max(minimum, int(value))) if not isinstance(value, bool) else default
        except (ValueError, TypeError, OverflowError):
            return default

    def init_plugin(self, config: dict | None = None):
        """Replace runtime state atomically; stale network work cannot persist later."""
        self.stop_service()
        config = config or {}
        with self._lock:
            self._enabled = config.get('enabled', True) is True
            self._refresh_minutes = self._bounded(config.get('refresh_minutes', 30), 30, 5, 360)
            self._dashboard_count = self._bounded(config.get('dashboard_count', 6), 6, 1, 20)
            if not self._enabled:
                return
            generation = self._generation
            def persist(state):
                """Only the current enabled generation may commit a refreshed snapshot."""
                with self._lock:
                    if self._enabled and generation == self._generation:
                        self.save_data('calendar_cache_v1', state)
            self._cache = CalendarCache(
                loader=lambda: self.get_data('calendar_cache_v1'), save=persist,
                fetch=fetch_snapshot, interval=self._refresh_minutes * 60)
            add_once = getattr(scheduler_sdk, 'add_plugin_once_job', None)
            if callable(add_once):
                try:
                    add_once(self.__class__.__name__, 'initial_refresh', self.refresh_data,
                             '简单观影日历首次更新', delay_seconds=3)
                except Exception:
                    logger.warning('简单观影日历：首次后台任务暂未注册，将在首次访问时获取数据')

    def get_state(self) -> bool:
        """Expose the current enabled state to host registrations."""
        with self._lock:
            return self._enabled

    def stop_service(self):
        """Invalidate old work and release the host-managed one-shot registration."""
        with self._lock:
            self._generation += 1
            self._enabled, self._cache = False, None
            remove_once = getattr(scheduler_sdk, 'remove_plugin_once_job', None)
            if callable(remove_once):
                try:
                    remove_once(self.__class__.__name__, 'initial_refresh')
                except Exception:
                    logger.warning('简单观影日历：清理首次任务时出现暂时错误')

    @staticmethod
    def get_command() -> list[dict]:
        """No remote commands or notification channels are registered."""
        return []

    def get_form(self) -> tuple[list[dict], dict]:
        """Return a minimal host-native settings form."""
        return config_form()

    def get_service(self) -> list[dict]:
        """Let the host own periodic scheduling and cleanup, without private threads."""
        with self._lock:
            if not self._enabled:
                return []
            return [{'id': f'{self.__class__.__name__}.Refresh', 'name': '简单观影日历更新',
                     'trigger': IntervalTrigger(minutes=self._refresh_minutes, timezone=BEIJING),
                     'func': self.refresh_data, 'kwargs': {}, 'func_kwargs': {'force': True}}]

    def refresh_data(self, force: bool = False) -> bool:
        """Refresh one shared cache without holding the lifecycle lock during HTTP."""
        with self._lock:
            cache = self._cache if self._enabled else None
        return cache.refresh(force=force) if cache else False

    def _view(self) -> dict:
        """Serve last-good data; perform a bounded, throttled cold load if needed."""
        with self._lock:
            cache = self._cache if self._enabled else None
            generation = self._generation
        if cache is None:
            return {'snapshot': None, 'stale': True, 'disabled': True, 'error': '插件已停用'}
        view = cache.view()
        if view['snapshot'] is None:
            cache.refresh()
            view = cache.view()
        with self._lock:
            if not self._enabled or generation != self._generation:
                return {'snapshot': None, 'stale': True, 'disabled': True, 'error': '插件状态已变更，请刷新'}
        return view

    def get_api(self) -> list[dict[str, Any]]:
        """Declare typed data envelopes and require host login for every endpoint."""
        return [
            {'path': '/discover', 'endpoint': self.discover, 'methods': ['GET'], 'auth': 'bear',
             'summary': '电影发行排期', 'response_model': schemas.Response[list[schemas.MediaInfo]]},
            {'path': '/status', 'endpoint': self.status, 'methods': ['GET'], 'auth': 'bear',
             'summary': '发行日历状态', 'response_model': schemas.Response[dict[str, Any]]},
            {'path': '/refresh', 'endpoint': self.refresh_api, 'methods': ['POST'], 'auth': 'bear',
             'summary': '刷新公开发行日历', 'response_model': schemas.Response[dict[str, Any]]},
        ]

    def discover(self, page: int = 1, group: str = 'upcoming', kind: str = 'all',
                 query: str = '', count: int = 30) -> schemas.Response[list[schemas.MediaInfo]]:
        """Return stable paginated movies and their full release schedule descriptions."""
        if page < 1 or not 1 <= count <= 100 or len(query or '') > 200:
            return schemas.Response(success=False, message='页码、数量或搜索条件无效', data=[])
        view = self._view()
        if view.get('snapshot') is None:
            return schemas.Response(success=False, message=view.get('error') or '日历正在加载，请稍后刷新', data=[])
        today = beijing_today()
        try:
            items = records(view['snapshot'], today, group, kind, query or '')
        except ValueError as error:
            return schemas.Response(success=False, message=str(error), data=[])
        selected = items[(page - 1) * count:page * count]
        return schemas.Response(success=True, message='当前显示缓存数据' if view['stale'] else '', data=[
            schemas.MediaInfo(**media_payload(item, view['snapshot'], today, stale=view['stale'])) for item in selected])

    def status(self) -> schemas.Response[dict[str, Any]]:
        """Expose refresh state without tokens, local paths or raw exceptions."""
        view = self._view()
        snapshot = view.pop('snapshot', None)
        view['generated_at'] = snapshot.get('generated_at') if snapshot else None
        view['movie_count'] = len(snapshot['movies']) if snapshot else 0
        return schemas.Response(success=self.get_state(), data=view)

    def refresh_api(self) -> schemas.Response[dict[str, Any]]:
        """Allow an explicit logged-in refresh without modifying calendar content."""
        success = self.refresh_data(force=True)
        result = self.status()
        return schemas.Response(success=success, message='更新成功' if success else '更新失败或正在更新，已有缓存继续保留', data=result.data)

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        """Append the calendar source without replacing others or duplicating itself."""
        if not self.get_state():
            return
        data = event.event_data
        sources = data.extra_sources or []
        path = f'plugin/{self.__class__.__name__}/discover'
        if any(getattr(source, 'api_path', None) == path for source in sources):
            return
        data.extra_sources = [*sources, schemas.DiscoverMediaSource(
            name='简单观影日历', media_source=MediaSource(SOURCE), api_path=path,
            filter_params={'group': 'upcoming', 'kind': 'all', 'query': ''}, filter_ui=filter_ui())]

    def get_module(self) -> dict[str, Any]:
        """Supply cached film details only for this plugin's explicit source identity."""
        return {'recognize_media': self.recognize_media, 'async_recognize_media': self.async_recognize_media}

    def recognize_media(self, meta: Any = None, mtype: Any = None,
                        media_source: MediaSource | None = None, media_id: str | None = None,
                        episode_group: str | None = None, cache: bool = True, **kwargs) -> Any:
        """Return a real host domain object, never title-match or query other sources."""
        if str(media_source or '') != SOURCE or not media_id or mtype not in (None, MediaType.MOVIE, '电影'):
            return None
        view = self._view()
        if view.get('snapshot') is None:
            return None
        today = beijing_today()
        item = next((r for r in records(view['snapshot'], today, group='all') if r['movie']['id'] == str(media_id)), None)
        if not item:
            return None
        info = DomainMediaInfo()
        info.from_dict(media_payload(item, view['snapshot'], today, stale=view['stale']))
        return info

    async def async_recognize_media(self, meta: Any = None, mtype: Any = None,
                                    media_source: MediaSource | None = None, media_id: str | None = None,
                                    episode_group: str | None = None, cache: bool = True, **kwargs) -> Any:
        """Keep synchronous cache cold-start I/O off the host event loop."""
        return await asyncio.to_thread(self.recognize_media, meta=meta, mtype=mtype,
                                       media_source=media_source, media_id=media_id,
                                       episode_group=episode_group, cache=cache, **kwargs)

    def get_dashboard_meta(self) -> list[dict[str, str]]:
        """Register only a selectable candidate; never write user dashboard settings."""
        return [{'key': 'upcoming', 'name': '简单观影日历 · 即将发行'}] if self.get_state() else []

    def get_dashboard(self, key: str, **kwargs):
        """Show a bounded recent-upcoming summary using the same snapshot as discovery."""
        if key != 'upcoming' or not self.get_state():
            return None
        view, today = self._view(), beijing_today()
        items = records(view['snapshot'], today)[:self._dashboard_count] if view.get('snapshot') else []
        return ({'cols': 12, 'md': 6},
                {'title': '简单观影日历', 'refresh': 300, 'border': True},
                dashboard_nodes(view, items, today))

    def get_page(self) -> list[dict]:
        """在插件内按即将发行和最近发行分区展示，并提供手动更新。"""
        view, today = self._view(), beijing_today()
        items = records(view['snapshot'], today, group='all') if view.get('snapshot') else []
        refresh_api = f'plugin/{self.__class__.__name__}/refresh' if self.get_state() else None
        return calendar_nodes(view, items, today, refresh_api=refresh_api)
