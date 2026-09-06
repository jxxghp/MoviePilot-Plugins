import assert from 'node:assert/strict'
import test from 'node:test'
import { appendTreeEvidence, createEvidencePackages, packageEvidence, repairAdmission } from './evidence-pipeline.js'

const roots = [
  { type: 'file', storage: 'local', path: '/download/A.E01.mkv', name: 'A.E01.mkv' },
  { type: 'file', storage: 'local', path: '/download/A.E02.mkv', name: 'A.E02.mkv' },
  { type: 'dir', storage: 'local', path: '/download/Mixed', name: 'Mixed' },
]

test('同一下载任务编号合并散文件；无编号顶层目录保持临时边界', () => {
  const packages = createEvidencePackages(roots, [
    { id: 1, status: false, download_hash: 'task-a', src: '/download/A.E01.mkv' },
    { id: 2, status: false, download_hash: 'task-a', src: '/download/A.E02.mkv' },
  ])
  const hashed = packages.find(item => item.boundary === 'download_hash')
  const fallback = packages.find(item => item.boundary === 'top_level')
  assert.equal(hashed.roots.length, 2)
  assert.equal(fallback.root.name, 'Mixed')
})

test('证据未读全时不可自动重建；完整且身份、预览、历史齐备才放行', () => {
  const pkg = appendTreeEvidence({ id: 'p', root: roots[0], roots: [roots[0]], boundary: 'download_hash', history: [{ id: 9, status: true, src: roots[0].path }] }, [{ complete: true, entries: [roots[0]] }])
  assert.equal(packageEvidence(pkg).video_count, 1)
  const preview = { summary: { total: 1, success: 1, failed: 0 }, items: [{ source: roots[0].path, target: '/library/A.mkv', success: true }] }
  assert.equal(repairAdmission(pkg, { media_source: 'tmdb', media_id: '1', evidence_verified: true }, preview).allowed, true)
  assert.equal(repairAdmission(pkg, { media_source: 'tmdb', media_id: '1' }, preview).allowed, false)
  assert.equal(repairAdmission(pkg, { media_source: 'tmdb', media_id: '1', user_confirmed: true }, preview).allowed, true)
  assert.equal(repairAdmission({ ...pkg, complete: false }, { media_source: 'tmdb', media_id: '1' }, { summary: { total: 1, failed: 0 } }).allowed, false)
  assert.equal(repairAdmission({ ...pkg, entries: [...pkg.entries, roots[1]] }, { media_source: 'tmdb', media_id: '1' }, preview).allowed, false)
})

test('真正失败没有旧成功目标时只建立新硬链接，不猜测删除对象', () => {
  const pkg = appendTreeEvidence({ id: 'p', root: roots[0], roots: [roots[0]], boundary: 'download_hash', history: [{ id: 10, status: false, src: roots[0].path }] }, [{ complete: true, entries: [roots[0]] }])
  const admission = repairAdmission(pkg, { media_source: 'tmdb', media_id: '1', evidence_verified: true }, { summary: { total: 1, success: 1, failed: 0 }, items: [{ source: roots[0].path, target: '/library/A.mkv', success: true }] })
  assert.equal(admission.allowed, true)
  assert.equal(admission.mode, 'create')
})

test('同一作品同时有假成功和真失败时生成混合修复计划', () => {
  const pkg = { complete: true, boundary: 'download_hash', root: { storage: 'local' }, entries: [{ type: 'file', path: '/fixture/E01.mkv', name: 'E01.mkv' }, { type: 'file', path: '/fixture/E02.mkv', name: 'E02.mkv' }], history: [{ id: 7, status: true, src: '/fixture/E01.mkv' }, { id: 8, status: false, src: '/fixture/E02.mkv' }] }
  const preview = { summary: { total: 2, success: 2, failed: 0 }, items: [{ target: '/fixture/library/E01.mkv', success: true }, { target: '/fixture/library/E02.mkv', success: true }] }
  const result = repairAdmission(pkg, { media_source: 'tmdb', media_id: '1', evidence_verified: true }, preview)
  assert.equal(result.mode, 'mixed')
  assert.deepEqual(result.history_ids, [7])
  assert.deepEqual(result.create_fileitems.map(item => item.path), ['/fixture/E02.mkv'])
})

test('有整理关系的字幕必须进入同一次预览，不能未经预览就清理旧链接', () => {
  const pkg = { complete: true, boundary: 'download_hash', root: { storage: 'local' }, entries: [{ type: 'file', path: '/fixture/Show.S01E01.mkv', name: 'Show.S01E01.mkv' }, { type: 'file', path: '/fixture/Show.S01E01.chs.srt', name: 'Show.S01E01.chs.srt' }, { type: 'file', path: '/fixture/Show.nfo', name: 'Show.nfo' }], history: [{ id: 11, status: true, src: '/fixture/Show.S01E01.mkv' }, { id: 12, status: true, src: '/fixture/Show.S01E01.chs.srt' }] }
  const preview = { summary: { total: 2, success: 2, failed: 0 }, items: [{ source: '/fixture/Show.S01E01.mkv', target: '/fixture/library/Show.S01E01.mkv', success: true }, { source: '/fixture/Show.S01E01.chs.srt', target: '/fixture/library/Show.S01E01.chs.srt', success: true }] }
  const result = repairAdmission(pkg, { media_source: 'tmdb', media_id: '1', evidence_verified: true }, preview)
  assert.equal(result.allowed, true)
  assert.deepEqual(result.history_ids, [12, 11])
})
