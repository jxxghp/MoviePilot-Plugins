import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createLatestPlanApi,
  createFilterState,
  FILTER_GROUPS,
  filterResources,
  filterOptionCount,
  FILTERS,
  formatGiB,
  isIncompleteTv,
  mediaType,
  matchesFilter,
  matchesFilterState,
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

test('generic filter list does not expose brush-flow tasks', () => {
  assert.equal(FILTERS.some(filter => filter.id === 'brush'), false)
  assert.equal(FILTERS.some(filter => filter.label === '刷流任务'), false)
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

test('media type filters include all TV and retain an incomplete-TV legacy shortcut', () => {
  const typedResources = [
    { id: 'movie', title: '电影', type: '电影', library: false, size: 30 },
    { id: 'tv', title: '完整剧集', type: '电视剧', library: true, edition: 'S01 · 8 集', size: 20 },
    { id: 'tv-incomplete', title: '缺集剧集', type: '电视剧', library: true, edition: 'S01 · 6 集', episodeExpected: 8, episodeActual: 6, episodeIncomplete: true, size: 10 },
    { id: 'tv-unimported', title: '未入库剧集', type: '电视剧', library: false, edition: 'S01 · 未入库', size: 5 },
  ]

  assert.equal(mediaType(typedResources[0]), 'movie')
  assert.equal(mediaType(typedResources[1]), 'tv')
  assert.equal(isIncompleteTv(typedResources[2]), true)
  assert.equal(isIncompleteTv(typedResources[3]), false)
  assert.equal(isIncompleteTv(typedResources[0]), false)
  assert.deepEqual(
    filterResources(typedResources, { filter: 'movie', search: '', safeOnly: false, descending: true }).map(item => item.id),
    ['movie'],
  )
  assert.deepEqual(
    filterResources(typedResources, { filter: 'tv', search: '', safeOnly: false, descending: true }).map(item => item.id),
    ['tv', 'tv-incomplete', 'tv-unimported'],
  )
  assert.deepEqual(
    filterResources(typedResources, { filter: 'tv-incomplete', search: '', safeOnly: false, descending: true }).map(item => item.id),
    ['tv-incomplete'],
  )
})

test('grouped filters combine with AND and quality flags can stack', () => {
  const typedResources = [
    { id: 'movie', type: '电影', library: true, protected: false, qbSummary: '无 qB 任务', size: 30 },
    { id: 'complete-tv', type: '电视剧', library: true, metadataVerified: true, protected: false, qbSummary: '1 个 qB 任务', size: 20 },
    { id: 'incomplete-tv', type: '电视剧', library: false, episodeIncomplete: true, metadataVerified: false, protected: true, hr: true, qbSummary: '1 个 qB 任务', size: 10 },
  ]
  const state = { ...createFilterState(), type: 'tv', library: 'not-imported', flags: ['incomplete', 'name-pending'] }

  assert.equal(matchesFilterState(typedResources[2], state), true)
  assert.equal(matchesFilterState(typedResources[1], state), false)
  assert.deepEqual(
    filterResources(typedResources, { filters: state, search: '', safeOnly: false, descending: true }).map(item => item.id),
    ['incomplete-tv'],
  )
  assert.equal(filterOptionCount(typedResources, createFilterState(), 'type', 'tv'), 2)
  assert.equal(filterOptionCount(typedResources, { ...createFilterState(), type: 'tv' }, 'library', 'not-imported'), 1)
  assert.equal(FILTER_GROUPS.find(group => group.id === 'flags')?.multi, true)
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
