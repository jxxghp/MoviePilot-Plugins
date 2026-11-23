"""Small Vuetify JSON views shared by plugin details and optional dashboard."""
from datetime import date
from uuid import uuid4

from .calendar import BASE_URL, KINDS, beijing_timestamp, media_payload, rating_rows, records, release_line, release_timing


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
.smc-page .smc-grid { display: grid; grid-template-columns: minmax(0, 1fr);
    align-items: start; gap: 14px; }
.smc-page .smc-film { min-width: 0; border-radius: 11px; overflow: hidden;
    border: 1px solid rgba(var(--v-theme-on-surface), .12); background: rgb(var(--v-theme-surface)); }
.smc-page .smc-film.smc-pinned { border-color: #b38b3a;
    border-color: color-mix(in srgb, #cba04b 82%, rgb(var(--v-theme-on-surface))); }
.smc-page .smc-pin-badge { position: absolute; top: 8px; left: 8px; z-index: 1;
    border-radius: 999px; padding: 2px 6px; background: #f8e3ac; color: #523d1c;
    font-size: 10px; font-weight: 700; line-height: 16px; white-space: nowrap;
    pointer-events: none; }
.smc-page .smc-poster { position: relative; isolation: isolate; aspect-ratio: 2 / 3; width: 100%; min-width: 0;
    display: grid; place-items: center; overflow: hidden;
    background: rgba(var(--v-theme-on-surface), .06); }
.smc-page .smc-film-info { min-width: 0; padding: 12px 11px 9px; text-align: center; }
.smc-page .smc-film-summary { min-width: 0; }
.smc-page .smc-film-title { font-size: 15px; line-height: 22px; font-weight: 600;
    overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical;
    -webkit-line-clamp: 2; overflow: hidden; }
.smc-page .smc-original { color: rgba(var(--v-theme-on-surface), .6); font-size: 11px;
    line-height: 17px; min-height: 17px; margin: 2px 0 9px; overflow: hidden;
    white-space: nowrap; text-overflow: ellipsis; }
.smc-page .smc-ratings { display: grid; align-content: center; gap: 3px; min-height: 43px; }
.smc-page .smc-rating { display: flex; justify-content: center; align-items: center;
    flex-wrap: wrap; gap: 3px 5px; font-size: 12px; line-height: 18px; }
.smc-page .smc-brand { display: inline-flex; align-items: center; flex-shrink: 0;
    justify-content: center; min-width: 27px; padding: 1px 3px; border-radius: 3px;
    font-size: 10px; line-height: 14px; font-weight: 800; }
.smc-page .smc-brand-douban { background: #12a64e; color: #fff; }
.smc-page .smc-brand-imdb { background: #f5c518; color: #191811; letter-spacing: -.5px; }
.smc-page .smc-score { font-weight: 600; }
.smc-page .smc-votes, .smc-page .smc-unrated { color: rgba(var(--v-theme-on-surface), .6);
    font-size: 11px; overflow-wrap: anywhere; }
.smc-page .smc-release-summary { border-top: 1px solid rgba(var(--v-theme-on-surface), .12);
    margin-top: 11px; padding-top: 10px; }
.smc-page .smc-timing { display: inline-block; color: rgb(var(--v-theme-primary));
    background: rgba(var(--v-theme-primary), .08); border: 1px solid rgba(var(--v-theme-primary), .15);
    border-radius: 14px; padding: 1px 9px; font-size: 11px; line-height: 20px; }
.smc-page .smc-recent .smc-timing { color: rgba(var(--v-theme-on-surface), .65);
    background: rgba(var(--v-theme-on-surface), .04); border-color: rgba(var(--v-theme-on-surface), .1); }
.smc-page .smc-date { font-size: 11px; line-height: 18px; margin-top: 6px;
    color: rgba(var(--v-theme-on-surface), .7); font-variant-numeric: tabular-nums;
    overflow-wrap: anywhere; text-wrap: balance; }
.smc-page .smc-details { margin-top: 3px; min-width: 0; }
.smc-page .smc-details summary { color: rgb(var(--v-theme-primary)); cursor: pointer;
    min-height: 28px; display: flex; justify-content: center; align-items: center;
    gap: 3px; list-style: none; font-size: 11px; }
.smc-page .smc-details summary::-webkit-details-marker { display: none; }
.smc-page .smc-details .smc-expand-icon { font-size: 15px; }
.smc-page .smc-details[open] .smc-expand-icon { transform: rotate(180deg); }
.smc-page .smc-versions { border-top: 1px solid rgba(var(--v-theme-on-surface), .12);
    margin-top: 5px; padding-top: 8px; text-align: start; color: rgba(var(--v-theme-on-surface), .7); }
.smc-page .smc-version { font-size: 12px; line-height: 1.8;
    white-space: pre-line; overflow-wrap: anywhere; }
.smc-page .smc-version + .smc-version { margin-top: 5px; }
.smc-page .smc-footer { display: flex; flex-wrap: wrap; align-items: center;
    justify-content: flex-end; gap: 8px; margin-top: 18px; }
@container (min-width: 260px) {
    .smc-page .smc-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (min-width: 560px) {
    .smc-page .smc-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@container (min-width: 800px) {
    .smc-page .smc-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
@container (min-width: 1060px) {
    .smc-page .smc-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); }
}
@container (max-width: 559px) {
    .smc-page .smc-grid { gap: 12px; }
    .smc-page .smc-film-info { padding: 10px 7px 8px; }
    .smc-page .smc-pin-badge { top: 6px; left: 6px; padding: 1px 5px; font-size: 9px; }
    .smc-page .smc-film-title { font-size: 14px; line-height: 21px; }
    .smc-page .smc-original, .smc-page .smc-votes, .smc-page .smc-unrated { font-size: 10px; }
    .smc-page .smc-rating { gap: 3px 4px; }
    .smc-page .smc-brand { font-size: 9px; min-width: 24px; line-height: 13px; padding: 1px 2px; }
    .smc-page .smc-date { font-size: 10px; }
}
@media (pointer: coarse) {
    .smc-page .smc-details summary { min-height: 44px; }
}
"""


def _page_ratings(movie: dict) -> dict:
    """展示真实评分和原有的人数文案，缺少来源时不补造评分。"""
    rows = []
    for provider, score, votes in rating_rows(movie):
        label = '豆瓣' if provider == 'douban' else 'IMDb'
        children = [
            _node('span', label, {'class': 'smc-brand smc-brand-' + provider}),
            _node('span', score, {'class': 'smc-score' if score[0].isdigit() else 'smc-unrated'}),
        ]
        if votes:
            children.append(_node('span', votes, {'class': 'smc-votes'}))
        rows.append(_node('div', props={'class': 'smc-rating', 'aria-label': label + '评分'}, content=children))
    return _node('div', props={'class': 'smc-ratings'}, content=rows or [
        _node('span', '暂无评分', {'class': 'smc-unrated'}),
    ])


def movie_card(record: dict, view: dict, today: str) -> dict:
    """大海报下居中展示评分和单次发行摘要，完整版本在当前卡片展开。"""
    item = media_payload(record, view['snapshot'], today, stale=view['stale'])
    release_date = record['primary']['date']
    same_day_kinds = {release.get('kind') for release in record['releases'] if release['date'] == release_date}
    kinds = ' · '.join(KINDS[kind] for kind in ('digital', 'physical', 'streaming') if kind in same_day_kinds)
    timing = release_timing(release_date, today)
    if not record['upcoming']:
        timing = f'已发行 {(date.fromisoformat(today) - date.fromisoformat(release_date)).days} 天'
    subtitle = ' · '.join(part for part in (
        item['original_title'] if item['original_title'] != item['title'] else None, item['year'],
    ) if part)
    summary = _node('div', props={'class': 'smc-film-summary'}, content=[
        _node('div', item['title'], {'class': 'smc-film-title', 'title': item['title']}),
        _node('div', subtitle, {'class': 'smc-original', 'title': subtitle}),
        _page_ratings(record['movie']),
        _node('div', props={'class': 'smc-release-summary'}, content=[
            _node('span', timing, {'class': 'smc-timing'}),
            _node('div', props={'class': 'smc-date'}, content=[
                _node('time', release_date, {'datetime': release_date}),
                _node('span', ' · ' + (kinds or '发行')),
            ]),
        ]),
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
    # 与即将发行的排序逻辑保持一致；过去影片保留标记时也不高亮。
    pinned = record['upcoming'] and record['movie'].get('pinned')
    poster_content = [poster]
    if pinned:
        poster_content.append(_node('span', '置顶推荐', {'class': 'smc-pin-badge'}))
    return _node('article', props={
        'class': 'smc-film smc-pinned' if pinned else 'smc-film', 'aria-label': item['title'],
    }, content=[
        _node('div', props={'class': 'smc-poster'}, content=poster_content),
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


MORE_CSS = """
.smc-dashboard-more { width: 42px; padding: 12px 8px; align-self: start;
    height: calc(clamp(min(100cqw, 118px), 26cqw, 156px) * 1.5);
    border: 1px solid rgba(var(--v-theme-primary), .18); border-radius: 8px;
    background: rgba(var(--v-theme-primary), .06); color: rgb(var(--v-theme-primary));
    font: inherit; font-size: 13px; writing-mode: vertical-rl; text-orientation: upright;
    letter-spacing: 3px; cursor: pointer; scroll-snap-align: end; }
.smc-dashboard-more:hover { background: rgba(var(--v-theme-primary), .12); }
.smc-calendar-popup { display: none; position: fixed; inset: 0; margin: auto;
    width: min(80rem, calc(100vw - 32px)); max-height: calc(100dvh - 32px);
    overflow: auto; overscroll-behavior: contain; padding: 0;
    border: 1px solid rgba(var(--v-theme-on-surface), .12); border-radius: 14px;
    background: rgb(var(--v-theme-surface)); color: rgb(var(--v-theme-on-surface));
    box-shadow: 0 16px 48px rgba(0, 0, 0, .24); }
.smc-calendar-popup:popover-open { display: block; }
.smc-calendar-popup::backdrop { background: rgba(0, 0, 0, .4); pointer-events: auto; }
.smc-calendar-popup .smc-popup-header { display: flex; justify-content: space-between;
    align-items: center; gap: 12px; padding: 16px 20px; position: sticky; top: 0;
    background: rgb(var(--v-theme-surface)); z-index: 1;
    border-bottom: 1px solid rgba(var(--v-theme-on-surface), .12); }
.smc-calendar-popup .smc-popup-title { font-size: 20px; font-weight: 600; margin: 0; }
.smc-calendar-popup .smc-popup-close { font: inherit; font-size: 24px; cursor: pointer;
    display: grid; place-items: center; width: 40px; height: 40px;
    border: 0; border-radius: 8px; color: inherit; background: transparent; }
.smc-calendar-popup .smc-popup-close:hover { background: rgba(var(--v-theme-on-surface), .08); }
.smc-calendar-popup .smc-popup-body { padding: 18px 20px 24px; }
@media (max-width: 600px) {
    .smc-calendar-popup { width: calc(100vw - 16px); max-height: calc(100dvh - 16px); }
    .smc-calendar-popup .smc-popup-header { padding: 12px; }
    .smc-calendar-popup .smc-popup-body { padding: 14px 12px; }
}
"""


def _dashboard_more(view: dict, today: str) -> tuple[dict, dict]:
    """用唯一原生触发器打开同一缓存的完整排期，无需仪表盘 API 事件。"""
    popup_id = 'smc-calendar-' + uuid4().hex
    title_id = popup_id + '-title'
    button = _node('button', '查看更多', {
        'type': 'button', 'class': 'smc-dashboard-more', 'aria-label': '查看更多发行排期',
        'popovertarget': popup_id, 'popovertargetaction': 'show',
    })
    popup = _node('div', props={
        'id': popup_id, 'popover': 'auto', 'role': 'dialog',
        'aria-labelledby': title_id, 'class': 'smc-calendar-popup',
    }, content=[
        _node('div', props={'class': 'smc-popup-header'}, content=[
            _node('h2', '简单观影日历', {'id': title_id, 'class': 'smc-popup-title'}),
            _node('button', '×', {
                'type': 'button', 'class': 'smc-popup-close', 'aria-label': '关闭观影日历',
                'autofocus': True, 'popovertarget': popup_id, 'popovertargetaction': 'hide',
            }),
        ]),
        _node('div', props={'class': 'smc-popup-body'}, content=calendar_nodes(
            view, records(view['snapshot'], today, group='all'), today,
        )),
    ])
    return button, popup


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
    if snapshot is not None:
        more, popup = _dashboard_more(view, today)
        if not items:
            nodes.append(_node('div', '暂无即将发行的电影', {'class': 'text-body-2 text-medium-emphasis mb-2'}))
        columns = f'repeat({len(items)}, clamp(min(100%,118px),26%,156px)) 42px' if items else '42px'
        nodes.append(_node('style', MORE_CSS))
        nodes.append(_node('div', props={
            'role': 'region', 'aria-label': '即将发行电影', 'tabindex': 0,
            'style': (
                f'display:grid;grid-auto-flow:column;grid-template-columns:{columns};'
                'container-type:inline-size;gap:10px;min-width:0;max-width:100%;overflow-x:auto;'
                'scroll-snap-type:x proximity;padding-block-end:6px'
            ),
        }, content=[*(_dashboard_card(item, snapshot, today) for item in items), more]))
        nodes.append(popup)
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
