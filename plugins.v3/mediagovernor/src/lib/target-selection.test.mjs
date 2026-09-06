import assert from 'node:assert/strict'
import test from 'node:test'
import { selectLibraryTarget } from './target-selection.js'

const roots = [
  { path: '/library/movie', storage: 'nas', name: '电影' },
  { path: '/library/tv', storage: 'nas', name: '电视剧' },
  { path: '/library/anime', storage: 'nas', name: '动漫' },
  { path: '/library/other', storage: 'nas', name: '其他' },
]

test('四类作品分别选择自己的唯一媒体库根，不受下载源目录影响', () => {
  assert.equal(selectLibraryTarget({ media_type: 'movie' }, roots).selected.target_path, '/library/movie')
  assert.equal(selectLibraryTarget({ media_type: 'tv' }, roots).selected.target_path, '/library/tv')
  assert.equal(selectLibraryTarget({ media_type: 'tv', genres: ['Animation'] }, roots).selected.target_path, '/library/anime')
  assert.equal(selectLibraryTarget({ media_type: 'tv', genres: ['Documentary'] }, roots).selected.target_path, '/library/other')
})

test('目标目录缺失或同类目录不唯一时硬停止', () => {
  assert.equal(selectLibraryTarget({ media_type: 'movie' }, []).selected, null)
  assert.equal(selectLibraryTarget({ media_type: 'movie' }, [...roots, { path: '/library/movie-2', name: '电影2' }]).selected, null)
})
