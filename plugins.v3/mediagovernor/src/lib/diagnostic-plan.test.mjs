import test from 'node:test'
import assert from 'node:assert/strict'
import { aiFallbackTargets, identityTargets } from './diagnostic-plan.js'

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
    { id: 'subtitle-only', complete: true, attachment_only: true, history: [{}], summary: { video_count: 0, subtitle_count: 1 }, nativeIdentity: { media_id: '3' } },
  ]
  assert.deepEqual(aiFallbackTargets(units).map(item => item.id), ['native-abstained', 'native-year-conflict', 'subtitle-only'])
})
