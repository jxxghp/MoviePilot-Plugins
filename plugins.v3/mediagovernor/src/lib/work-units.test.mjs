import assert from 'node:assert/strict'
import test from 'node:test'
import { createWorkUnits } from './work-units.js'

const file = (path, name = path.split('/').pop()) => ({ type: 'file', path, name })

test('多季剧集保持为一个作品，季只是卡内结构', () => {
  const rows = createWorkUnits({ id: 'pkg', root: { path: '/d/show', name: 'Show' }, entries: [file('/d/show/Show.S01E01.mkv'), file('/d/show/Show.S02E01.mkv')], history: [], complete: true })
  assert.equal(rows.length, 1)
  assert.equal(rows[0].season_hint, 0)
})

test('电影合集按独立子目录拆分', () => {
  const rows = createWorkUnits({ id: 'pkg', root: { path: '/d/collection' }, entries: [file('/d/collection/Film A/Film A.mkv'), file('/d/collection/Film B/Film B.mkv')], history: [], complete: true })
  assert.equal(rows.length, 2)
})

test('同一下载任务跨多个顶层项目时按每个项目拆分', () => {
  const rows = createWorkUnits({ id: 'pkg', roots: [{ path: '/d/Film A' }, { path: '/d/Film B' }], root: { path: '/d/Film A' }, entries: [file('/d/Film A/Film A.mkv'), file('/d/Film B/Film B.mkv')], history: [], complete: true })
  assert.equal(rows.length, 2)
})

test('字幕跟随所属作品，有整理历史的孤立字幕也能被审计', () => {
  const withVideo = createWorkUnits({ id: 'pkg', root: { path: '/d/Show', name: 'Show' }, entries: [file('/d/Show/Show.S01E01.mkv'), file('/d/Show/Show.S01E01.srt')], history: [], complete: true })
  assert.equal(withVideo[0].entries.length, 2)
  const subtitleOnly = createWorkUnits({ id: 'sub', root: { path: '/d/Film', name: 'Film' }, entries: [file('/d/Film/Film.2007.srt')], history: [{ status: true, src: '/d/Film/Film.2007.srt' }], complete: true })
  assert.equal(subtitleOnly[0].attachment_only, true)
})

test('Sample 样片及其旧失败历史不会形成媒体问题单元', () => {
  const sample = file('/d/Film/Sample/Film.sample.mkv')
  const rows = createWorkUnits({ id: 'pkg', root: { path: '/d/Film', name: 'Film' }, entries: [file('/d/Film/Film.mkv'), sample], history: [{ status: true, src: '/d/Film/Film.mkv' }, { status: false, src: sample.path }], complete: true })
  assert.equal(rows.length, 1)
  assert.equal(rows[0].entries.some(item => item.path === sample.path), false)
  assert.equal(rows[0].history.some(item => item.src === sample.path), false)
})
