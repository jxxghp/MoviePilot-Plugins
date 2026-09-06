import assert from 'node:assert/strict'
import test from 'node:test'
import { manualPreviewRequest, manualRebuildRequests, moviePilotTypeName } from './manual-transfer.js'

const unit = { complete: true, boundary: 'download_hash', root: { storage: 'local' }, entries: [{ type: 'file', storage: 'local', path: '/fixture/download/A.mkv', name: 'A.mkv' }] }

test('手动整理严格使用 MoviePilot 中文媒体类型枚举', () => {
  assert.equal(moviePilotTypeName('movie'), '电影')
  assert.equal(moviePilotTypeName('tv'), '电视剧')
  assert.equal(manualPreviewRequest(unit, { media_type: 'movie', media_source: 'tmdb', media_id: '1' }).type_name, '电影')
  const rebuild = manualRebuildRequests([7], { media_type: 'tv', media_source: 'tmdb', media_id: '2' }, { target_path: '/fixture/library/tv', target_storage: 'local', library_type_folder: true })[0]
  assert.equal(rebuild.type_name, '电视剧')
  assert.equal(rebuild.target_path, '/fixture/library/tv')
  assert.equal(rebuild.library_type_folder, true)
})

test('孤立错链字幕可沿正式 fileitems 预览链进入 MoviePilot', () => {
  const subtitleUnit = { complete: true, boundary: 'download_hash', attachment_only: true, root: { storage: 'local' }, entries: [{ type: 'file', storage: 'local', path: '/fixture/download/Movie.chs.srt', name: 'Movie.chs.srt' }], history: [{ id: 8, status: true, src: '/fixture/download/Movie.chs.srt' }] }
  const request = manualPreviewRequest(subtitleUnit, { media_type: 'movie', media_source: 'tmdb', media_id: '3' })
  assert.deepEqual(request.fileitems.map(item => item.path), ['/fixture/download/Movie.chs.srt'])
})
