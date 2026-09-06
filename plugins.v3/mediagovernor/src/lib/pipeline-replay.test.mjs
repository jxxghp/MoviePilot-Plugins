import assert from 'node:assert/strict'
import test from 'node:test'
import { replayPipeline } from './pipeline-replay.js'

const library = [
  { name: '电影', library_path: '/fixture/library/movie', library_storage: 'nas' },
  { name: '电视剧', library_path: '/fixture/library/tv', library_storage: 'nas' },
  { name: '动漫', library_path: '/fixture/library/anime', library_storage: 'nas' },
  { name: '其他', library_path: '/fixture/library/other', library_storage: 'nas' },
]

test('真实阶段重放同时找出真失败和假成功，并保留正常项', () => {
  const result = replayPipeline({
    download_configurations: [{ name: '下载', storage: 'nas', download_path: '/fixture/download' }],
    library_configurations: library,
    root_listings: { '/fixture/download': [
      { type: 'dir', storage: 'nas', path: '/fixture/download/Failed', name: 'Failed' },
      { type: 'dir', storage: 'nas', path: '/fixture/download/Wrong', name: 'Wrong' },
      { type: 'dir', storage: 'nas', path: '/fixture/download/Normal', name: 'Normal' },
    ] },
    trees: {
      '/fixture/download/failed': [{ type: 'file', path: '/fixture/download/Failed/Failed.S01E01.mkv', name: 'Failed.S01E01.mkv' }],
      '/fixture/download/wrong': [{ type: 'file', path: '/fixture/download/Wrong/Wrong.S01E01.mkv', name: 'Wrong.S01E01.mkv' }],
      '/fixture/download/normal': [{ type: 'file', path: '/fixture/download/Normal/Normal.E01.mkv', name: 'Normal.E01.mkv' }],
    },
    histories: [
      { id: 1, status: false, src: '/fixture/download/Failed/Failed.S01E01.mkv' },
      { id: 2, status: true, src: '/fixture/download/Wrong/Wrong.S01E01.mkv', dest: '/fixture/library/tv/Wrong/Season 1/Wrong.S01E01.mkv' },
      { id: 3, status: true, src: '/fixture/download/Normal/Normal.E01.mkv', dest: '/fixture/library/tv/Normal/Season 1/Normal.S01E01.mkv' },
    ],
    native_by_label: {
      Failed: { title: 'Failed', type: '电视剧', media_source: 'tmdb', id: '1' },
      Wrong: { title: 'Wrong', type: '电视剧', genres: ['Animation'], media_source: 'tmdb', id: '2' },
      Normal: { title: 'Normal', type: '电视剧', media_source: 'tmdb', id: '3' },
    },
    present: ['/fixture/library/tv/Wrong/Season 1/Wrong.S01E01.mkv', '/fixture/library/tv/Normal/Season 1/Normal.S01E01.mkv'],
  })
  assert.equal(result.units.length, 3)
  assert.deepEqual(result.findings.map(item => item.kind).sort(), ['category_error', 'native_failure'])
  assert.equal(result.units.find(item => item.work_label === 'Normal').selected_target.target_path, '/fixture/library/tv')
})
