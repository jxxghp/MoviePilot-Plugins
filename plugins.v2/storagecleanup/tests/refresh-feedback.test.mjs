import test from 'node:test'
import assert from 'node:assert/strict'

import { refreshFeedback } from '../src/refresh-feedback.js'

test('refresh feedback starts with a read-only snapshot message', () => {
  assert.equal(refreshFeedback(0), '正在读取 NAS 只读快照…')
  assert.equal(refreshFeedback(4), '正在读取 NAS 只读快照…')
})

test('refresh feedback exposes elapsed time during normal checks', () => {
  assert.equal(refreshFeedback(5), '正在核对媒体目录、qB 与 H&R（已等待 5 秒）')
  assert.match(refreshFeedback(29), /已等待 29 秒/)
})

test('refresh feedback explains long H&R probes without declaring failure', () => {
  assert.match(refreshFeedback(30), /可能需要数分钟/)
  assert.match(refreshFeedback(120), /已等待 120 秒/)
  assert.doesNotMatch(refreshFeedback(120), /失败|错误/)
})
