import assert from 'node:assert/strict'
import test from 'node:test'
import { chooseGroundedCandidate, reconcileIdentities } from './identity.js'

const anime = { title: 'Cowboy Bebop', year: '1998', media_type: 'tv', media_source: 'themoviedb', media_id: '1' }
const live = { title: 'Cowboy Bebop', year: '2021', media_type: 'tv', media_source: 'themoviedb', media_id: '2' }

test('年份把动画与真人版候选区分开', () => {
  const result = chooseGroundedCandidate({ title: 'Cowboy Bebop', year: '1998', media_type: 'tv' }, [anime, live])
  assert.equal(result.selected.media_id, '1')
})

test('原生识别与整包证据冲突时必须停下来', () => {
  const result = reconcileIdentities(live, { selected: anime, candidates: [anime] })
  assert.equal(result.identity.abstain, true)
  assert.equal(result.candidates.length, 2)
})

test('AI 重复原生的冲突答案不能把错误身份重新盖章', () => {
  const result = reconcileIdentities(live, { selected: live, candidates: [live] }, { year: '1998' }, true)
  assert.equal(result.identity.abstain, true)
  assert.equal(result.identity.evidence_verified, false)
})

test('不同数据源但标题年份类型一致时认定为同一作品', () => {
  const native = { title: 'Example Story', year: '2020', media_type: 'movie', media_source: 'tmdb', media_id: '10' }
  const douban = { title: 'Example Story', year: '2020', media_type: 'movie', media_source: 'douban', media_id: '20' }
  const result = reconcileIdentities(native, { selected: douban, candidates: [douban] })
  assert.equal(result.identity.media_source, 'tmdb')
  assert.equal(result.identity.abstain, false)
})

test('MoviePilot 唯一原生身份不需要 AI 再盖章', () => {
  const result = reconcileIdentities(anime, { selected: null, candidates: [] })
  assert.equal(result.identity.media_id, '1')
  assert.equal(result.identity.abstain, false)
})

test('文件有明确年份时，可选择已由 MoviePilot 数据源落地的年份匹配候选', () => {
  const result = reconcileIdentities(live, { selected: anime, candidates: [anime] }, { year: '1998' })
  assert.equal(result.identity.media_id, '1')
  assert.equal(result.identity.abstain, false)
})
