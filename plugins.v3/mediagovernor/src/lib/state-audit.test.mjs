import assert from 'node:assert/strict'
import test from 'node:test'
import { evaluateCurrentState, validatePreviewTarget } from './state-audit.js'

const video = (name, path = `/fixture/download/${name}`) => ({ name, path })
const present = (...paths) => new Set(paths.map(value => value.toLowerCase()))
const roots = [
  { path: '/fixture/library/movie', name: '电影', media_type: 'movie' },
  { path: '/fixture/library/tv', name: '电视剧', media_type: 'tv' },
  { path: '/fixture/library/anime', name: '动漫', media_type: 'tv' },
  { path: '/fixture/library/other', name: '其他' },
]

test('已完整建立的正常电视剧不会被错误预览反向误报', () => {
  const unit = { id: 'normal-tv', complete: true, entries: [video('Story.S01E01.mkv')], history: [{ status: true, src: '/fixture/download/Story.S01E01.mkv', dest: '/fixture/library/tv/Story/Season 1/Story.S01E01.mkv', title: 'Story', type: '电视剧' }] }
  const identity = { title: 'Story', media_type: 'tv', media_source: 'tmdb', media_id: '1', confidence: 1, abstain: false, evidence_verified: true }
  const preview = { summary: { total: 1, success: 1, failed: 0 }, items: [{ target: '/fixture/library/anime/Story/Season 1/Story.S01E01.mkv', success: true }] }
  assert.equal(evaluateCurrentState({ unit, identity, preview, presentPaths: present('/fixture/library/tv/Story/Season 1/Story.S01E01.mkv'), libraryRoots: roots }), null)
  assert.equal(validatePreviewTarget({ identity, preview, libraryRoots: roots }).valid, false)
})

test('同类作品也必须核对季集，未经整包确认的候选不能解锁修复', () => {
  const preview = { summary: { total: 1, success: 1, failed: 0 }, items: [{ source: '/fixture/download/Story.S02E01.mkv', target: '/fixture/library/tv/Other/Season 1/Other.S01E01.mkv', success: true }] }
  assert.equal(validatePreviewTarget({ identity: { title: 'Story', media_type: 'tv', media_source: 'tmdb', media_id: '5' }, preview, libraryRoots: roots }).valid, false)
  const selected = { title: 'Story', media_type: 'tv', media_source: 'tmdb', media_id: '5', user_confirmed: true }
  assert.equal(validatePreviewTarget({ identity: selected, preview, libraryRoots: roots }).valid, false)
  const correct = { summary: { total: 1, success: 1, failed: 0 }, items: [{ source: '/fixture/download/Story.S02E01.mkv', target: '/fixture/library/tv/Story/Season 2/Story.S02E01.mkv', success: true }] }
  assert.equal(validatePreviewTarget({ identity: selected, preview: correct, libraryRoots: roots }).valid, true)
  const wrongWork = { summary: { total: 1, success: 1, failed: 0 }, items: [{ source: '/fixture/download/Story.S02E01.mkv', target: '/fixture/library/tv/Other Story/Season 2/Other.Story.S02E01.mkv', success: true }] }
  assert.equal(validatePreviewTarget({ identity: selected, preview: wrongWork, libraryRoots: roots }).valid, false)
  const wrongYear = { summary: { total: 1, success: 1, failed: 0 }, items: [{ source: '/fixture/download/Story.S02E01.mkv', target: '/fixture/library/tv/Story (2021)/Season 2/Story.S02E01.mkv', success: true }] }
  assert.equal(validatePreviewTarget({ identity: { ...selected, year: '1998' }, preview: wrongYear, libraryRoots: roots }).valid, false)
})

test('动画放进电视剧目录是假成功', () => {
  const unit = { id: 'animation', complete: true, entries: [video('Animation.S01E01.mkv')], history: [{ status: true, src: '/fixture/download/Animation.S01E01.mkv', dest: '/fixture/library/tv/Animation/Season 1/Animation.S01E01.mkv', title: 'Animation', type: '电视剧' }] }
  const identity = { title: 'Animation', media_type: 'tv', genres: ['Animation'], media_source: 'tmdb', media_id: '2', confidence: 1, abstain: false, evidence_verified: true }
  assert.equal(evaluateCurrentState({ unit, identity, presentPaths: present('/fixture/library/tv/Animation/Season 1/Animation.S01E01.mkv'), libraryRoots: roots }).kind, 'category_error')
})

test('同一作品的部分失败不会被部分成功掩盖', () => {
  const unit = { id: 'partial', complete: true, entries: [video('Story.S01E01.mkv'), video('Story.S01E02.mkv')], history: [{ status: true, src: '/fixture/download/Story.S01E01.mkv', dest: '/fixture/library/tv/Story/Season 1/Story.S01E01.mkv', title: 'Story', type: '电视剧' }, { status: false, src: '/fixture/download/Story.S01E02.mkv' }] }
  const identity = { title: 'Story', media_type: 'tv', media_source: 'tmdb', media_id: '3', confidence: 1, abstain: false, evidence_verified: true }
  assert.equal(evaluateCurrentState({ unit, identity, presentPaths: present('/fixture/library/tv/Story/Season 1/Story.S01E01.mkv'), libraryRoots: roots }).kind, 'native_failure')
})

test('剧集平铺在分类根目录是层级错误', () => {
  const unit = { id: 'flat', complete: true, entries: [video('Doc.S01E01.mkv')], history: [{ status: true, src: '/fixture/download/Doc.S01E01.mkv', dest: '/fixture/library/other/Doc.S01E01.mkv', title: 'Doc', type: '纪录片' }] }
  const identity = { title: 'Doc', media_type: 'tv', genres: ['Documentary'], media_source: 'tmdb', media_id: '4', confidence: 1, abstain: false, evidence_verified: true }
  assert.equal(evaluateCurrentState({ unit, identity, presentPaths: present('/fixture/library/other/Doc.S01E01.mkv'), libraryRoots: roots }).kind, 'hierarchy_error')
})
