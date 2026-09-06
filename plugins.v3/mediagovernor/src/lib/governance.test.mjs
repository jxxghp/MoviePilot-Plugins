import assert from 'node:assert/strict'
import test from 'node:test'
import { classifyFinding, configuredDownloadRoots, createDownloadUnits, diffMap, episodeKeysCompatible, fileFingerprint, historyRowsForUnit, latestHistory, latestHistoryRows, libraryRootForPath, libraryRootSnapshot, normaliseMediaSource, strictEpisodeHints, strictEpisodeKeys, summarizeUnit } from './governance.js'

test('下载区顶层目录和单文件各是一个真实下载单元，不按相似标题拼包', () => {
  const units = createDownloadUnits({ storage: 'local', path: '/downloads' }, [{ type: 'dir', path: '/downloads/A', name: 'A' }, { type: 'file', path: '/downloads/B.mkv', name: 'B.mkv' }, { type: 'file', name: 'note.txt' }])
  assert.equal(units.length, 2)
})

test('文件指纹包含会随实际文件变动的名称、大小和时间', () => {
  assert.notEqual(fileFingerprint({ name: 'A.mkv', size: 1, modify_time: 'a' }), fileFingerprint({ name: 'A.mkv', size: 2, modify_time: 'a' }))
  assert.deepEqual(diffMap({ map_version: 1, download_units: [{ id: 'a', fingerprint: 'old' }] }, { download_units: [{ id: 'a', fingerprint: 'new' }, { id: 'b', fingerprint: 'x' }] }), { changed: ['a', 'b'], unchanged: 0, first: false })
})

test('地图只保存媒体库根摘要，不把海量子项塞进持久化状态', () => {
  const roots = [{ storage: 'nas', path: '/library/movie', name: '电影', type: 'dir' }, { storage: 'nas', path: '/library/tv', name: '电视剧', type: 'dir' }]
  const snapshot = libraryRootSnapshot(roots)
  assert.equal(snapshot.length, 2)
  assert.deepEqual(snapshot.map(item => item.category), ['电影', '电视剧'])
  assert.equal(snapshot.some(item => item.id.includes('Episode')), false)
})

test('集号只接收明确集号，不把清晰度误读为集数', () => {
  assert.deepEqual(strictEpisodeHints('Show.S01E02.2160p.mkv'), [2])
  assert.deepEqual(strictEpisodeKeys('Show.S02E02.2160p.mkv'), ['S2E2'])
  assert.deepEqual(strictEpisodeHints('Movie.2024.2160p.mkv'), [])
})

test('源文件只有 E09 时与目标 S01E09 兼容，但明确的不同季仍不兼容', () => {
  assert.deepEqual(strictEpisodeKeys('Show.E09.mkv'), ['E9'])
  assert.equal(episodeKeysCompatible('Show.E09.mkv', '/tv/Show/Season 1/Show.S01E09.mkv'), true)
  assert.equal(episodeKeysCompatible('Show.S02E09.mkv', '/tv/Show/Season 1/Show.S01E09.mkv'), false)
})

test('当前作品目录正确时，旧历史身份字段不再单独制造误报', () => {
  const unit = { id: 'stale-history', entries: [{ name: 'Forrest.Gump.mkv' }] }
  const result = classifyFinding({
    unit,
    summary: summarizeUnit(unit),
    history: [{ status: true, src: '/download/Forrest.Gump.mkv', dest: '/library/movie/Forrest Gump/Forrest.Gump.mkv', media_source: 'tmdb', media_id: 'old', title: 'Old Result' }],
    diagnosis: { title: '阿甘正传', original_title: 'Forrest Gump', media_type: 'movie', media_source: 'tmdb', media_id: '13', confidence: 1, abstain: false },
    presentPaths: new Set(['/library/movie/forrest gump/forrest.gump.mkv']),
    library: [{ path: '/library/movie', name: '电影' }],
  })
  assert.deepEqual(result, [])
})

test('六个已知正常作品不会再被旧身份或 E/EP 季号差异误报', () => {
  const samples = [
    ['阿甘正传', 'Forrest Gump', 'movie'],
    ['兄弟连', 'Band of Brothers', 'tv'],
    ['第五共和国', 'The 5th Republic', 'tv'],
    ['我的团长我的团', 'My Chief and My Regiment', 'tv'],
    ['沉默的真相', 'The Long Night', 'tv'],
    ['康熙王朝', 'Kangxi Dynasty', 'tv'],
  ]
  for (const [title, original, type] of samples) {
    const source = `/download/${original}.E09.mkv`
    const dest = type === 'movie' ? `/library/movie/${original}/${original}.mkv` : `/library/tv/${original}/Season 1/${original}.S01E09.mkv`
    const unit = { id: title, entries: [{ name: source.split('/').pop(), path: source }] }
    const result = classifyFinding({ unit, summary: summarizeUnit(unit), history: [{ status: true, src: source, dest, media_source: 'tmdb', media_id: 'stale', title: '旧记录' }], diagnosis: { title, original_title: original, media_type: type, media_source: 'tmdb', media_id: 'current', confidence: 1, abstain: false }, presentPaths: new Set([dest.toLowerCase()]), library: [{ path: `/library/${type === 'movie' ? 'movie' : 'tv'}`, name: type === 'movie' ? '电影' : '电视剧' }] })
    assert.deepEqual(result, [], title)
  }
})

test('真实失败与目标丢失才是问题，成功 move 的源缺失不是问题', () => {
  const unit = { id: 'u', root: { name: 'Show' }, entries: [{ name: 'Show.S01E01.mkv' }] }; const summary = summarizeUnit(unit)
  assert.equal(classifyFinding({ unit, summary, history: [{ id: 1, status: false }] })[0].kind, 'native_failure')
  assert.equal(classifyFinding({ unit, summary, history: [{ id: 2, status: true, dest: '/library/A.mkv' }] }).length, 0)
})

test('分类、季和作品名错误需要已确认身份，不能由猜测生成', () => {
  const unit = { id: 'u', root: { name: 'Show' }, entries: [{ name: 'Show.S01E01.mkv' }] }; const summary = summarizeUnit(unit)
  const diagnosis = { title: '正确作品', original_title: '', media_type: 'tv', season: 2, confidence: .9, abstain: false }
  const results = classifyFinding({ unit, summary, history: [{ status: true, dest: '/library/A', title: '错误作品', type: '电影', season: 1 }], diagnosis, presentPaths: new Set(['/library/a']) })
  assert.equal(results.some(item => item.kind === 'category_error'), true)
})

test('同集号位于不同季时不是重复集', () => {
  const summary = summarizeUnit({ entries: [{ name: 'Story.S01E01.mkv' }, { name: 'Story.S02E01.mkv' }] })
  assert.deepEqual(summary.duplicateEpisodes, [])
  assert.deepEqual(summary.episode_keys, ['S1E1', 'S2E1'])
})

test('历史目标被手工删除时进入确认区，不冒充原生整理失败', () => {
  const unit = { id: 'deleted', entries: [{ name: 'Film.mkv' }] }
  const result = classifyFinding({ unit, summary: summarizeUnit(unit), history: [{ status: true, src: '/d/Film.mkv', dest: '/library/Film.mkv' }], diagnosis: { title: 'Film', media_type: 'movie', confidence: 1, abstain: false }, presentPaths: new Set() })
  assert.equal(result[0].kind, 'unconfirmed')
})

test('下载范围只能来自 download_path，空路径和容器根目录必须硬拒绝且相同路径去重', () => {
  const scope = configuredDownloadRoots([
    { name: '下载', storage: 'local', download_path: '/downloads' },
    { name: '重复下载', storage: 'local', download_path: '/downloads/' },
    { name: '危险根', storage: 'local', download_path: '/' },
    { name: '空目录', storage: 'local', download_path: '' },
  ])
  assert.deepEqual(scope.roots.map(item => item.path), ['/downloads'])
  assert.equal(scope.rejected.length, 2)
})

test('下载范围不会因 Windows 分隔符或盘符根目录退化到容器根目录', () => {
  const scope = configuredDownloadRoots([
    { storage: 'local', download_path: 'D:\\downloads' },
    { storage: 'local', download_path: 'D:' },
  ])
  assert.equal(scope.roots[0].path, 'D:\\downloads')
  assert.equal(scope.rejected.length, 1)
})

test('历史只能单向归属当前下载包，父目录历史不得被猜测分配', () => {
  const unit = { root: { path: '/downloads/Package-A' } }
  const rows = [
    { id: 1, src: '/downloads/Package-A/E01.mkv', status: true, date: '2026-01-01T00:00:00Z' },
    { id: 2, src: '/downloads', status: false, date: '2026-02-01T00:00:00Z' },
    { id: 3, src: '/downloads/Package-AB/E01.mkv', status: false, date: '2026-03-01T00:00:00Z' },
    { id: 4, src: '/downloads/Package-A/E01.mkv', status: false, date: '2026-04-01T00:00:00Z' },
  ]
  const matched = historyRowsForUnit(unit, rows)
  assert.deepEqual(matched.map(item => item.id), [4, 1])
  assert.equal(latestHistory(matched).id, 4)
})

test('旧成功目标不会参与当前目标核验，当前状态只认同一源文件最新一条历史', () => {
  const rows = [
    { id: 1, src: '/downloads/Package-A/E01.mkv', dest: '/library/old/E01.mkv', status: true, date: '2026-01-01T00:00:00Z' },
    { id: 2, src: '/downloads/Package-A/E01.mkv', dest: '/library/new/E01.mkv', status: true, date: '2026-02-01T00:00:00Z' },
    { id: 3, src: '/downloads/Package-A/E02.mkv', status: false, date: '2026-02-02T00:00:00Z' },
  ]
  assert.deepEqual(latestHistoryRows(rows).map(item => item.id), [3, 2])
})

test('目标目录必须按最长匹配的媒体库配置归属，才能核验分类', () => {
  const roots = [{ path: '/library', media_type: '' }, { path: '/library/tv', media_type: 'tv' }]
  assert.equal(libraryRootForPath('/library/tv/Show/S01/E01.mkv', roots).media_type, 'tv')
})

test('MoviePilot 数据源名称统一为可比较的 TMDB 与豆瓣键', () => {
  assert.equal(normaliseMediaSource('TheMovieDb'), 'tmdb')
  assert.equal(normaliseMediaSource('豆瓣'), 'douban')
})
