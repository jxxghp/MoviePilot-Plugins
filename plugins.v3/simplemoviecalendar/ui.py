"""Small Vuetify JSON views shared by plugin details and optional dashboard."""
from datetime import date

from .calendar import BASE_URL, KINDS, beijing_timestamp, media_payload, rating_rows, release_line, release_timing


def _node(component, text=None, props=None, content=None):
    """Construct text-only renderer nodes; external titles never become HTML."""
    result = {'component': component}
    if text is not None:
        result['text'] = text
    if props:
        result['props'] = props
    if content is not None:
        result['content'] = content
    return result


def status_nodes(view: dict, *, show_timestamp: bool = True) -> list[dict]:
    """Explain loading, failed refreshes, and snapshot age without raw exceptions."""
    if view.get('disabled'):
        return [_node('VAlert', '插件已停用，请在设置中启用。', {'type': 'info', 'variant': 'tonal'})]
    result = []
    if view.get('error'):
        result.append(_node('VAlert', view['error'], {'type': 'warning', 'variant': 'tonal', 'class': 'mb-3'}))
    if view.get('persistence_error'):
        result.append(_node('VAlert', view['persistence_error'], {'type': 'warning', 'variant': 'tonal', 'class': 'mb-3'}))
    snapshot = view.get('snapshot')
    if snapshot is None:
        if not result:
            result.append(_node('VAlert', '日历正在加载，请稍后刷新。', {'type': 'info', 'variant': 'tonal'}))
    elif show_timestamp:
        state = '缓存数据 · ' if view.get('stale') else ''
        result.append(_node('div', state + '数据更新时间：' + snapshot['generated_at'], {'class': 'text-caption mb-3', 'style': 'overflow-wrap:anywhere'}))
    return result


PAGE_CSS = """
.smc-page { container-type: inline-size; min-width: 0; }
.smc-page .smc-toolbar { display: flex; flex-wrap: wrap; align-items: center;
    justify-content: space-between; gap: 8px 16px; margin-bottom: 20px; }
.smc-page .smc-updated { margin-inline-start: auto; color: rgba(var(--v-theme-on-surface), .65);
    font-size: 12px; overflow-wrap: anywhere; text-align: end; }
.smc-page .smc-section + .smc-section { margin-top: 26px; padding-top: 22px;
    border-top: 1px solid rgba(var(--v-theme-on-surface), .12); }
.smc-page .smc-heading { display: flex; align-items: center; gap: 9px;
    font-size: 17px; font-weight: 600; margin: 0 0 12px; }
.smc-page .smc-heading::before { content: ''; width: 4px; height: 17px;
    border-radius: 3px; background: rgb(var(--v-theme-primary)); flex-shrink: 0; }
.smc-page .smc-recent .smc-heading::before { background: rgba(var(--v-theme-on-surface), .5); }
.smc-page .smc-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start; gap: 12px; }
.smc-page .smc-film { display: grid; grid-template-columns: 88px minmax(0, 1fr);
    gap: 15px; min-width: 0; padding: 13px; border-radius: 11px;
    border: 1px solid rgba(var(--v-theme-on-surface), .12); background: rgb(var(--v-theme-surface)); }
.smc-page .smc-poster { aspect-ratio: 2 / 3; width: 88px; min-width: 0;
    display: grid; place-items: center; border-radius: 6px; overflow: hidden;
    background: rgba(var(--v-theme-on-surface), .06); }
.smc-page .smc-film-info, .smc-page .smc-film-summary { min-width: 0; }
.smc-page .smc-film-title { font-size: 15px; line-height: 1.5; font-weight: 600;
    margin-bottom: 5px; overflow-wrap: anywhere; }
.smc-page .smc-timing { color: rgb(var(--v-theme-primary)); font-size: 13px;
    line-height: 1.6; margin-bottom: 6px; overflow-wrap: anywhere; }
.smc-page .smc-recent .smc-timing { color: rgba(var(--v-theme-on-surface), .65); }
.smc-page .smc-date { font-size: 12px; color: rgba(var(--v-theme-on-surface), .65);
    font-variant-numeric: tabular-nums; }
.smc-page .smc-details { margin-top: 10px; min-width: 0; }
.smc-page .smc-details summary { color: rgb(var(--v-theme-primary)); cursor: pointer;
    width: fit-content; min-height: 32px; display: flex; align-items: center;
    gap: 5px; list-style: none; font-size: 12px; }
.smc-page .smc-details summary::-webkit-details-marker { display: none; }
.smc-page .smc-details .smc-expand-icon { font-size: 16px; }
.smc-page .smc-details[open] .smc-expand-icon { transform: rotate(180deg); }
.smc-page .smc-versions { border-top: 1px solid rgba(var(--v-theme-on-surface), .12);
    margin-top: 8px; padding-top: 8px; color: rgba(var(--v-theme-on-surface), .7); }
.smc-page .smc-version { font-size: 12px; line-height: 1.8;
    white-space: pre-line; overflow-wrap: anywhere; }
.smc-page .smc-version + .smc-version { margin-top: 5px; }
.smc-page .smc-footer { display: flex; flex-wrap: wrap; align-items: center;
    justify-content: flex-end; gap: 8px; margin-top: 18px; }
@container (min-width: 1280px) {
    .smc-page .smc-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@container (max-width: 640px) {
    .smc-page .smc-grid { grid-template-columns: minmax(0, 1fr); }
    .smc-page .smc-film { grid-template-columns: 76px minmax(0, 1fr); gap: 11px; padding: 11px; }
    .smc-page .smc-poster { width: 76px; }
    .smc-page .smc-updated { text-align: start; }
}
@media (pointer: coarse) {
    .smc-page .smc-details summary { min-height: 44px; }
}
"""


def movie_card(record: dict, view: dict, today: str) -> dict:
    """用单次摘要展示下一次发行，全部版本保留在可键盘展开的排期中。"""
    item = media_payload(record, view['snapshot'], today, stale=view['stale'])
    release_date = record['primary']['date']
    same_day_kinds = {release.get('kind') for release in record['releases'] if release['date'] == release_date}
    kinds = ' · '.join(KINDS[kind] for kind in ('digital', 'physical', 'streaming') if kind in same_day_kinds)
    timing = release_timing(release_date, today)
    if not record['upcoming']:
        timing = f'已发行 {(date.fromisoformat(today) - date.fromisoformat(release_date)).days} 天'
    summary = _node('div', props={'class': 'smc-film-summary'}, content=[
        _node('div', item['title_year'], {'class': 'smc-film-title'}),
        _node('div', f'{kinds or "发行"} · {timing}', {'class': 'smc-timing'}),
        _node('time', release_date, {'datetime': release_date, 'class': 'smc-date'}),
    ])
    poster = _node('VImg', props={
        'src': item['poster_path'], 'width': '100%', 'aspect-ratio': 2 / 3, 'cover': True, 'alt': item['title'],
    }) if item['poster_path'] else _node('VIcon', props={'icon': 'mdi-movie-outline', 'aria-hidden': 'true'})
    details = _node('details', props={'class': 'smc-details'}, content=[
        _node('summary', '完整排期', content=[
            _node('VIcon', props={'icon': 'mdi-chevron-down', 'class': 'smc-expand-icon', 'aria-hidden': 'true'}),
        ]),
        _node('div', props={'class': 'smc-versions'}, content=[
            _node('div', release_line(release), {'class': 'smc-version'}) for release in record['releases']
        ]),
    ])
    # 摘要和折叠入口共用信息列，展开时完整版本可自然换行。
    return _node('article', props={'class': 'smc-film', 'aria-label': item['title']}, content=[
        _node('div', props={'class': 'smc-poster'}, content=[poster]),
        _node('div', props={'class': 'smc-film-info'}, content=[summary, details]),
    ])


def calendar_nodes(view: dict, items: list[dict], today: str, *, refresh_api: str | None = None) -> list[dict]:
    """生成按容器宽度重排的详情页，分区内按既有日期顺序显示。"""
    toolbar = []
    if refresh_api:
        refresh = _node('VBtn', '立即更新日历', {
            'variant': 'tonal', 'color': 'primary', 'size': 'small', 'prepend-icon': 'mdi-refresh',
        })
        refresh['events'] = {'click': {'api': refresh_api, 'method': 'post', 'params': {}}}
        toolbar.append(refresh)
    snapshot = view.get('snapshot')
    if snapshot is not None:
        timestamp = snapshot['generated_at']
        state = '缓存 · ' if view.get('stale') else ''
        toolbar.append(_node('time', state + '更新于 ' + beijing_timestamp(timestamp) + ' · 北京时间', {
            'datetime': timestamp, 'class': 'smc-updated',
        }))
    content = [_node('div', props={'class': 'smc-toolbar'}, content=toolbar)] if toolbar else []
    content.extend(status_nodes(view, show_timestamp=False))
    if snapshot is not None:
        for upcoming, label in ((True, '即将发行'), (False, '最近发行')):
            group = [item for item in items if item['upcoming'] is upcoming]
            grid = _node('div', props={'class': 'smc-grid'}, content=[
                movie_card(item, view, today) for item in group[:100]
            ]) if group else _node('div', '暂无' + label + '的电影', {'class': 'text-body-2 text-medium-emphasis'})
            content.append(_node('section', props={
                'class': 'smc-section' if upcoming else 'smc-section smc-recent', 'aria-label': label,
            }, content=[_node('h3', label, {'class': 'smc-heading'}), grid]))
        footer = []
        if any(sum(item['upcoming'] is upcoming for item in items) > 100 for upcoming in (True, False)):
            footer.append(_node('span', '每个区域最多显示 100 部，更多请到探索页查看。', {'class': 'text-caption text-medium-emphasis'}))
        footer.append(_node('VBtn', '查看完整观影日历', {
            'href': BASE_URL, 'target': '_blank', 'rel': 'noopener noreferrer', 'variant': 'text', 'size': 'small',
        }))
        content.append(_node('div', props={'class': 'smc-footer'}, content=footer))
    return [_node('style', PAGE_CSS), _node('div', props={'class': 'smc-page'}, content=content)]


def _dashboard_ratings(movie: dict) -> list[dict]:
    """Center each provider row and keep its wordmark beside the score."""
    nodes = []
    for provider, score, votes in rating_rows(movie):
        is_douban = provider == 'douban'
        wordmark_style = (
            'background:#00a51b;color:#fff' if is_douban else 'background:#f5c518;color:#111'
        )
        items = [_node('span', props={
            'style': 'display:inline-flex;align-items:center;gap:4px;white-space:nowrap',
        }, content=[
            _node('span', '豆' if is_douban else 'IMDb', {
                'aria-label': '豆瓣' if is_douban else 'IMDb',
                'style': f'padding:1px 3px;border-radius:3px;font-weight:800;line-height:1.25;{wordmark_style}',
            }),
            _node('span', score, {'class': 'font-weight-medium'}),
        ])]
        if votes:
            items.append(_node('span', votes, {
                'class': 'text-medium-emphasis', 'style': 'overflow-wrap:anywhere',
            }))
        nodes.append(_node('div', props={
            'style': 'display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:0 2px;font-size:11px;line-height:1.45',
        }, content=items))
    return nodes


def _dashboard_card(record: dict, snapshot: dict, today: str) -> dict:
    """居中展示海报、评分和发行信息，影片卡片保持纯展示。"""
    item = media_payload(record, snapshot, today)
    release_date = record['primary']['date']
    timing = release_timing(release_date, today).replace(' ', '')
    release_kinds = {release.get('kind') for release in record['releases']}
    labels = ' · '.join(KINDS[kind] for kind in ('digital', 'physical', 'streaming') if kind in release_kinds)
    poster = _node('VImg', props={
        'src': item['poster_path'], 'alt': '', 'aspect-ratio': 2 / 3, 'cover': True,
    }) if item['poster_path'] else _node('VIcon', props={'icon': 'mdi-movie-outline', 'aria-hidden': 'true'})
    poster_content = [poster]
    if record['upcoming'] and record['movie'].get('pinned'):
        poster_content.append(_node('div', props={
            'style': ('position:absolute;inset:0;z-index:1;pointer-events:none;'
                      'box-sizing:border-box;border:1px solid #e9b755;border-radius:inherit'),
        }, content=[_node('span', '置顶', {
            'style': ('position:absolute;top:5px;left:5px;padding:2px 5px;border-radius:4px;'
                      'background:#f1bd58;color:#2b1b05;font-size:11px;font-weight:600;'
                      'line-height:1.35;white-space:nowrap'),
        })]))
    title_style = (
        'display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;'
        'overflow:hidden;overflow-wrap:anywhere;line-height:1.35'
    )
    return _node('div', props={
        'class': 'smc-dashboard-film', 'aria-label': item['title'],
        'style': 'display:block;min-width:0;scroll-snap-align:start;color:inherit;text-decoration:none;text-align:center',
    }, content=[
        _node('div', props={
            'style': ('position:relative;aspect-ratio:2/3;display:grid;align-items:center;text-align:center;'
                      'overflow:hidden;border-radius:8px;background:rgba(var(--v-theme-on-surface),.08)'),
        }, content=poster_content),
        _node('div', item['title'], {'class': 'text-body-2 font-weight-medium mt-2', 'style': title_style}),
        *_dashboard_ratings(record['movie']),
        _node('div', f'{release_date} {timing}', {
            'class': 'text-caption text-primary', 'style': 'text-wrap:balance;overflow-wrap:anywhere',
        }),
        _node('div', labels or '发行', {
            'class': 'text-caption text-medium-emphasis', 'style': 'text-wrap:balance;word-break:keep-all;overflow-wrap:anywhere',
        }),
    ])


def dashboard_nodes(view: dict, items: list[dict], today: str) -> list[dict]:
    """Fit a horizontal poster strip to the widget's own width."""
    header = [_node('div', '即将发行', {'class': 'text-subtitle-2'})]
    snapshot = view.get('snapshot')
    if snapshot is not None:
        timestamp = snapshot['generated_at']
        prefix = '缓存 · ' if view['stale'] else ''
        header.append(_node('time', prefix + '数据更新于 ' + beijing_timestamp(timestamp), {
            'datetime': timestamp, 'title': '北京时间', 'class': 'text-caption text-medium-emphasis',
            'style': 'margin-inline-start:auto;text-align:end;overflow-wrap:anywhere',
        }))
    nodes = [
        _node('div', props={
            'style': 'display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:2px 12px;margin-bottom:8px',
        }, content=header),
        *status_nodes(view, show_timestamp=False),
    ]
    if items:
        nodes.append(_node('div', props={
            'role': 'region', 'aria-label': '即将发行电影', 'tabindex': 0,
            'style': (
                'display:grid;grid-auto-flow:column;grid-auto-columns:clamp(min(100%,118px),26%,156px);'
                'gap:10px;min-width:0;max-width:100%;overflow-x:auto;'
                'scroll-snap-type:x proximity;padding-block-end:6px'
            ),
        }, content=[_dashboard_card(item, snapshot, today) for item in items]))
    elif snapshot is not None:
        nodes.append(_node('div', '暂无即将发行的电影', {'class': 'text-body-2 text-medium-emphasis'}))
    return nodes


def filter_ui() -> list[dict]:
    """Expose host-native exploration filters rather than a separate front end."""
    controls = [
        ('VSelect', {'model': 'group', 'label': '排期范围', 'items': [
            {'title': '即将发行', 'value': 'upcoming'}, {'title': '最近发行', 'value': 'recent'}, {'title': '全部排期', 'value': 'all'}]}),
        ('VSelect', {'model': 'kind', 'label': '发行类型', 'items': [
            {'title': '全部类型', 'value': 'all'}, *({'title': name, 'value': key} for key, name in KINDS.items())]}),
        ('VTextField', {'model': 'query', 'label': '搜索片名或 IMDb／豆瓣 ID', 'clearable': True}),
    ]
    return [_node('VRow', content=[_node('VCol', props={'cols': 12, 'md': 4}, content=[_node(component, props=props)]) for component, props in controls])]


def config_form() -> tuple[list[dict], dict]:
    """Keep source credentials out of settings; only expose useful view controls."""
    defaults = {'enabled': True, 'refresh_minutes': 30, 'dashboard_count': 6}
    controls = [
        _node('VSwitch', props={'model': 'enabled', 'label': '启用简单观影日历'}),
        _node('VTextField', props={'model': 'refresh_minutes', 'label': '数据更新间隔（分钟，5–360）', 'type': 'number', 'min': 5, 'max': 360}),
        _node('VTextField', props={'model': 'dashboard_count', 'label': '仪表板影片数量（1–20）', 'type': 'number', 'min': 1, 'max': 20}),
        _node('VAlert', '探索来源随插件启用。仪表板组件需在 MP 的仪表板设置中手动添加。首版用于查看排期，直接订阅留待后续。', {'type': 'info', 'variant': 'tonal'}),
    ]
    return [_node('VForm', content=controls)], defaults
