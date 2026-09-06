import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequestBudget, runBatchesUntilFailure, settledResults } from './request-budget.js'

test('慢请求按预算返回，停止操作不再等待底层请求', async () => {
  const budget = createRequestBudget()
  const started = Date.now()
  await assert.rejects(budget.run(new Promise(resolve => setTimeout(resolve, 100)), 15, '识别'), /识别超过/)
  assert.ok(Date.now() - started < 80)
  const waiting = budget.run(new Promise(resolve => setTimeout(resolve, 100)), 1000, '识别')
  budget.cancel()
  await assert.rejects(waiting, /检查已停止/)
  assert.equal(budget.pending(), 0)
})

test('一个样本失败不会丢弃同作品的其他成功身份', async () => {
  const result = await settledResults([Promise.resolve('first'), Promise.reject(new Error('middle failed')), Promise.resolve('last')])
  assert.deepEqual(result.values, ['first', 'last'])
  assert.equal(result.errors.length, 1)
})

test('智能助手第一批失败后熔断并标记所有剩余项目', async () => {
  const calls = []; let failed = []
  const result = await runBatchesUntilFailure([1, 2, 3, 4, 5], {
    maxItems: 2, maxChars: 10, cost: () => 1,
    run: async batch => { calls.push(batch); throw new Error('timeout') },
    failure: rows => { failed = rows },
  })
  assert.equal(calls.length, 1)
  assert.deepEqual(failed, [1, 2, 3, 4, 5])
  assert.equal(result.failed.length, 5)
})
