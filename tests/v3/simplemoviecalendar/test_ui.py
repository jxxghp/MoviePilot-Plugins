"""详情页分区、排期去重与仪表板展示回归。"""

import copy

from app.plugins.simplemoviecalendar import calendar, ui
from tests.v3.simplemoviecalendar.test_calendar import sample


def flatten(nodes):
    """读取宿主实际接收的递归渲染节点。"""
    return [child for node in nodes for child in [node, *flatten(node.get('content', []))]]


def view(snapshot=None):
    return {'snapshot': snapshot if snapshot is not None else sample(), 'stale': False}


def test_details_sections_keep_mixed_release_movie_only_in_upcoming():
    """有未来版本的影片只在即将发行区域出现，过去版本仍可展开查看。"""
    state = view()
    nodes = ui.calendar_nodes(state, calendar.records(state['snapshot'], '2026-11-01', group='all'), '2026-11-01')
    sections = [node for node in flatten(nodes) if node['component'] == 'section']
    assert [node['props']['aria-label'] for node in sections] == ['即将发行', '最近发行']
    upcoming = flatten(sections[0]['content'])
    recent = flatten(sections[1]['content'])
    assert any(node.get('text') == '多版本 (2026)' for node in upcoming)
    assert not any(node.get('text') == '多版本 (2026)' for node in recent)
    assert any(node.get('text') == 'Past' for node in recent)
    assert any('2026-10-20' in node.get('text', '') for node in upcoming)


def test_movie_summary_groups_same_day_types_without_repeating_versions():
    """摘要合并同日类型，版本和平台细节仅在折叠内容中展示。"""
    state = view()
    state['snapshot']['releases'].extend([
        {'id': 'a3', 'movie_id': 'a', 'date': '2026-11-17', 'kind': 'physical', 'edition': 'Blu-ray'},
        {'id': 'a4', 'movie_id': 'a', 'date': '2026-11-17', 'kind': 'digital', 'edition': 'Digital HD'},
    ])
    record = next(item for item in calendar.records(state['snapshot'], '2026-11-01') if item['movie']['id'] == 'a')
    card = ui.movie_card(record, state, '2026-11-01')
    nodes = flatten([card])
    detail = next(node for node in nodes if node['component'] == 'details')
    assert 'open' not in detail.get('props', {})
    assert detail['content'][0]['component'] == 'summary'
    assert detail['content'][0]['text'] == '完整排期'
    assert len([node for node in flatten(detail['content']) if '2026-' in node.get('text', '')]) == 4
    summary = next(node for node in nodes if node.get('props', {}).get('class') == 'smc-film-summary')
    texts = [node.get('text') for node in flatten([summary])]
    assert '数字发行 · 实体盘 · 还有 16 天' in texts
    assert texts.count('2026-11-17') == 1
    assert not any('Digital HD' in text or 'Blu-ray' in text for text in texts if text)
    assert all('href' not in node.get('props', {}) for node in nodes)


def test_today_and_recent_timing_use_beijing_calendar_days():
    state = view()
    rows = calendar.records(state['snapshot'], '2026-11-01', group='all')
    today = next(item for item in rows if item['movie']['id'] == 'b')
    past = next(item for item in rows if item['movie']['id'] == 'c')
    assert '平台上线 · 今日发行' in [node.get('text') for node in flatten([ui.movie_card(today, state, '2026-11-01')])]
    assert '数字发行 · 已发行 1 天' in [node.get('text') for node in flatten([ui.movie_card(past, state, '2026-11-01')])]
    assert any('北京时间 10:00' in node.get('text', '') for node in flatten([ui.movie_card(today, state, '2026-11-01')]))


def test_empty_groups_and_missing_posters_are_visible_without_broken_images():
    state = view({'schema_version': 1, 'generated_at': '2026-11-01T00:00:00+00:00', 'movies': [], 'releases': []})
    nodes = flatten(ui.calendar_nodes(state, [], '2026-11-01'))
    assert '暂无即将发行的电影' in [node.get('text') for node in nodes]
    assert '暂无最近发行的电影' in [node.get('text') for node in nodes]
    state = view()
    record = calendar.records(state['snapshot'], '2026-11-01')[0]
    nodes = flatten([ui.movie_card(record, state, '2026-11-01')])
    assert any(node['component'] == 'VIcon' for node in nodes)
    assert not any(node['component'] == 'VImg' for node in nodes)


def test_dynamic_movie_and_platform_text_stays_text_and_all_versions_survive():
    state = view()
    state['snapshot']['movies'][1]['title_zh'] = '<script>长片名</script>'
    state['snapshot']['releases'][2]['platform'] = '<img src=x onerror=alert(1)>\n腾讯视频'
    record = calendar.records(state['snapshot'], '2026-11-01')[0]
    nodes = flatten([ui.movie_card(record, state, '2026-11-01')])
    assert any(node.get('text') == '<script>长片名</script>' for node in nodes)
    assert any('腾讯视频' in node.get('text', '') for node in nodes)
    assert all('html' not in node for node in nodes)


def test_dashboard_has_no_film_links_and_retains_ratings_pin_and_dates():
    snapshot = copy.deepcopy(sample())
    snapshot['movies'][1].update(imdb_id='tt123', imdb_rating=8, imdb_votes=29842)
    nodes = flatten(ui.dashboard_nodes(view(snapshot), calendar.records(snapshot, '2026-11-01'), '2026-11-01'))
    assert all(node['component'] != 'a' and not node.get('props', {}).get('href') and not node.get('events') for node in nodes)
    text = [node.get('text') for node in nodes]
    for expected in ('今日电影', '置顶', 'IMDb', '8.0', '（29.8K评价）', '2026-11-01 今日发行'):
        assert expected in text
    assert any('border:1px solid' in node.get('props', {}).get('style', '') for node in nodes)


def test_page_toolbar_has_readable_timestamp_and_preserves_failure_warning(monkeypatch):
    from app.plugins.simplemoviecalendar import SimpleMovieCalendar
    monkeypatch.setattr(SimpleMovieCalendar, '__init__', lambda self: None)
    instance = SimpleMovieCalendar()
    state = view()
    state['stale'] = True
    state['error'] = '更新失败，继续显示已有日历'
    instance._view = lambda: state
    instance.get_state = lambda: True
    monkeypatch.setattr('app.plugins.simplemoviecalendar.beijing_today', lambda: '2026-11-01')
    nodes = flatten(instance.get_page())
    refresh = next(node for node in nodes if node.get('text') == '立即更新日历')
    assert refresh['events']['click']['method'] == 'post'
    assert refresh['events']['click']['api'] == 'plugin/SimpleMovieCalendar/refresh'
    assert any(node['component'] == 'time' and '2026-11-01 08:00' in node.get('text', '') for node in nodes)
    assert any(node.get('text') == state['error'] for node in nodes)


def test_large_upcoming_group_cannot_hide_recent_group():
    """长排期只截断各自分区，最近发行仍显示且明确提示数量上限。"""
    state = view()
    original = calendar.records(state['snapshot'], '2026-11-01', group='all')
    future = next(item for item in original if item['movie']['id'] == 'a')
    past = next(item for item in original if item['movie']['id'] == 'c')
    rows = [copy.deepcopy(future) for _ in range(103)] + [past]
    nodes = flatten(ui.calendar_nodes(state, rows, '2026-11-01'))
    sections = [node for node in nodes if node['component'] == 'section']
    assert sum(node['component'] == 'article' for node in flatten(sections[0]['content'])) == 100
    assert sum(node['component'] == 'article' for node in flatten(sections[1]['content'])) == 1
    assert any('每个区域最多显示 100 部' in node.get('text', '') for node in nodes)


def test_disabled_view_explains_state_without_refresh_or_empty_movie_sections():
    nodes = flatten(ui.calendar_nodes({'snapshot': None, 'disabled': True}, [], '2026-11-01'))
    assert any('插件已停用' in node.get('text', '') for node in nodes)
    assert not any(node['component'] == 'section' or node.get('events') for node in nodes)
