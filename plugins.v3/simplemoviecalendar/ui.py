"""Small Vuetify JSON views shared by plugin details and optional dashboard."""
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


def movie_card(record: dict, view: dict, today: str) -> dict:
    """Show every release version, and link to the maintained public film page."""
    item = media_payload(record, view['snapshot'], today, stale=view['stale'])
    text = [
        _node('div', item['title_year'], {'class': 'text-subtitle-1 font-weight-bold'}),
        _node('div', item['tagline'], {'class': 'text-caption mb-2', 'style': 'white-space:pre-line;overflow-wrap:anywhere'}),
    ]
    for release in record['releases']:
        text.append(_node('div', release_line(release), {'class': 'text-body-2 mb-1', 'style': 'white-space:pre-line;overflow-wrap:anywhere'}))
    text.append(_node('VBtn', '查看完整排期', {'href': item['homepage'], 'target': '_blank', 'rel': 'noopener noreferrer', 'variant': 'text', 'size': 'small', 'class': 'mt-1'}))
    columns = []
    if item['poster_path']:
        columns.append(_node('VCol', props={'cols': 3, 'sm': 2}, content=[_node('VImg', props={'src': item['poster_path'], 'aspect-ratio': 2 / 3, 'cover': True, 'max-width': 96, 'alt': item['title']})]))
    columns.append(_node('VCol', props={'cols': 9 if item['poster_path'] else 12, 'sm': 10 if item['poster_path'] else 12}, content=text))
    return _node('VCard', props={'variant': 'outlined', 'class': 'mb-3'}, content=[_node('VCardText', content=[_node('VRow', props={'dense': True}, content=columns)])])


def calendar_nodes(view: dict, items: list[dict], today: str, title: str) -> list[dict]:
    """Render cached records without triggering per-film requests."""
    result = status_nodes(view)
    if view.get('snapshot') is not None:
        result.append(_node('div', title, {'class': 'text-subtitle-1 mb-3'}))
        if not items:
            result.append(_node('div', '暂无符合条件的发行排期。', {'class': 'text-body-2 mb-3'}))
        result.extend(movie_card(item, view, today) for item in items)
    result.append(_node('VBtn', '打开完整观影日历', {'href': BASE_URL, 'target': '_blank', 'rel': 'noopener noreferrer', 'variant': 'text'}))
    return result


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
    """Link one poster and its compact release summary to the full schedule."""
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
    return _node('a', props={
        'href': item['homepage'], 'target': '_blank', 'rel': 'noopener noreferrer',
        'title': item['title'],
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
