import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createLatestPlanApi,
  filterResources,
  formatGiB,
  matchesFilter,
  unwrapResponse,
} from '../src/provider.js'

const resources = [
  { id: 'safe', title: '回到未来', englishTitle: 'Back to the Future', size: 78.1, protected: false, qbSummary: '无 qB 任务', library: true },
  { id: 'hr', title: '择天记', englishTitle: 'Fighter of the Destiny', size: 58.7, protected: true, hr: true, qbSummary: '1 个 qB 任务' },
]

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

test('review filter means no seeding task or protection restriction', () => {
  assert.equal(matchesFilter(resources[0], 'review'), true)
  assert.equal(matchesFilter(resources[1], 'review'), false)
})

test('resource filtering supports bilingual search and size order', () => {
  assert.deepEqual(
    filterResources(resources, { filter: 'all', search: 'Back to', safeOnly: false, descending: true }).map(item => item.id),
    ['safe'],
  )
  assert.deepEqual(
    filterResources(resources, { filter: 'all', search: '', safeOnly: false, descending: true }).map(item => item.id),
    ['safe', 'hr'],
  )
})

test('MoviePilot response wrapper is normalized', () => {
  assert.deepEqual(unwrapResponse({ success: true, data: { ok: true } }), { ok: true })
  assert.equal(formatGiB(2048), '2.00 TB')
})

test('stale plan requests resolve to the newest plan response', async () => {
  const pending = []
  const api = createLatestPlanApi({
    get: () => null,
    post: (_path, body) => {
      const request = deferred()
      pending.push({ body, request })
      return request.promise
    },
  })

  const deleteResult = api.post('plugin/StorageCleanup/plan', { mode: 'delete' })
  const retireResult = api.post('plugin/StorageCleanup/plan', { mode: 'retire' })
  pending[0].request.resolve({ success: true, data: { ok: true, plan: { mode: 'delete' } } })
  const pauseResult = api.post('plugin/StorageCleanup/plan', { mode: 'pause' })
  pending[1].request.resolve({ success: true, data: { ok: true, plan: { mode: 'retire' } } })
  pending[2].request.resolve({ success: true, data: { ok: true, plan: { mode: 'pause' } } })

  const results = await Promise.all([deleteResult, retireResult, pauseResult])
  assert.deepEqual(
    results.map(result => unwrapResponse(result).plan.mode),
    ['pause', 'pause', 'pause'],
  )
})
