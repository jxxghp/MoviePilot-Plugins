import test from 'node:test'
import assert from 'node:assert/strict'
import { aiFallbackTargets, identityTargets, nativeEvidenceConflict } from './diagnostic-plan.js'

test('every video unit receives native identity verification, even without history', () => {
  const units = [
    { id: 'apparently-successful-but-wrong', complete: true, history: [{ status: true }], summary: { video_count: 1 } },
    { id: 'without-history', complete: true, history: [], summary: { video_count: 1 } },
  ]
  assert.deepEqual(identityTargets(units).map(item => item.id), ['apparently-successful-but-wrong', 'without-history'])
})

test('AI 只兜底原生没有唯一身份或与整包证据冲突的单元', () => {
  const units = [
    { id: 'native-ok', complete: true, history: [{}], summary: { video_count: 1, names: ['Story 2021'] }, nativeIdentity: { media_source: 'tmdb', media_id: '1', title: 'Story', year: '2021', media_type: 'movie' } },
    { id: 'native-abstained', complete: true, history: [{}], summary: { video_count: 1 }, nativeIdentity: null },
    { id: 'native-year-conflict', complete: true, history: [{}], summary: { video_count: 1, names: ['Story 1998'] }, nativeIdentity: { media_source: 'tmdb', media_id: '2', title: 'Story', year: '2021', media_type: 'tv' } },
    { id: 'native-title-conflict', complete: true, history: [{}], summary: { video_count: 1, names: ['Forrest Gump 1994'] }, nativeIdentity: { media_source: 'tmdb', media_id: '4', title: 'Unrelated Animation', year: '1994', media_type: 'movie' } },
    { id: 'subtitle-only', complete: true, attachment_only: true, history: [{}], summary: { video_count: 0, subtitle_count: 1 }, nativeIdentity: { media_id: '3' } },
  ]
  assert.deepEqual(aiFallbackTargets(units).map(item => item.id), ['native-abstained', 'native-year-conflict', 'native-title-conflict', 'subtitle-only'])
})

test('中文标题或英文原名任一吻合都不会误判身份冲突', () => {
  assert.equal(nativeEvidenceConflict(
    { work_label: '阿甘正传 1994', summary: { names: ['阿甘正传.1994.mkv'] } },
    { title: '阿甘正传', original_title: 'Forrest Gump', year: '1994', media_type: 'movie', media_source: 'tmdb', media_id: '13' },
  ), false)
  assert.equal(nativeEvidenceConflict(
    { work_label: 'Forrest Gump 1994', summary: { names: ['Forrest.Gump.1994.mkv'] } },
    { title: '阿甘正传', original_title: 'Forrest Gump', year: '1994', media_type: 'movie', media_source: 'tmdb', media_id: '13' },
  ), false)
})
