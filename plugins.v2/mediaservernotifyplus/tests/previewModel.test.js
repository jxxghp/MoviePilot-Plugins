import assert from 'node:assert/strict'
import test from 'node:test'
import { computed, reactive, toRaw } from 'vue'
import { buildPreviewRows, createPreviewSample, previewFieldMeta } from '../src/previewModel.js'
import { normalizeNotificationModel } from '../src/notificationModel.js'

test('library events discard playback-only options while playback keeps them', () => {
  const keys = ['user', 'device', 'progress', 'ip', 'server']
  const rows = keys.map(key => ({ key, label: key, enabled: true }))
  const model = normalizeNotificationModel({
    field_configs: {
      library_added: rows,
      library_deleted: rows,
      playback_started: rows,
    },
    _default_field_configs: {
      library_added: rows,
      library_deleted: rows,
      playback_started: rows,
    },
  })
  for (const action of ['library_added', 'library_deleted']) {
    assert.deepEqual(model.field_configs[action].map(row => row.key), ['server'])
    assert.deepEqual(model._default_field_configs[action].map(row => row.key), ['server'])
  }
  assert.deepEqual(model.field_configs.playback_started.map(row => row.key), keys)
})

test('fixed media preview follows every selected field, label, and order', () => {
  const sample = createPreviewSample()
  const state = reactive({
    rows: Object.keys(previewFieldMeta).map(key => ({ key, label: previewFieldMeta[key].label, enabled: true })),
    sample,
  })
  const preview = computed(() => buildPreviewRows(state.rows, state.sample))

  assert.equal(preview.value.length, 12)
  assert.equal(preview.value[0].key, 'season_episode')
  assert.equal(preview.value.at(-1).key, 'overview')
  assert.equal(preview.value.at(-1).block, true)
  assert.equal(sample.mediaName, '光阴之外 (2025)')
  assert.equal(sample.fields.user, '预览')
  assert.equal(sample.fields.ip, '66.66.66.66 本地局域网')
  assert.equal(preview.value.find(row => row.key === 'time').value, '2026-09-23 15:06:26')
  assert.match(preview.value.find(row => row.key === 'overview').value, /许青为隐藏异质秘密/)

  state.rows[0].enabled = false
  assert.equal(preview.value.length, 11)
  assert.equal(preview.value.some(row => row.key === 'season_episode'), false)

  state.rows[1].label = '观看用户'
  assert.equal(preview.value.find(row => row.key === 'user').label, '观看用户')

  state.rows.reverse()
  assert.equal(preview.value[0].key, 'overview')
  assert.strictEqual(toRaw(state.sample), sample)

  state.rows[0].enabled = false
  assert.equal(preview.value[0].key, 'time')
})

test('server selection overrides only the preview value', () => {
  const sample = createPreviewSample()
  const rows = [{ key: 'server', label: '媒体服务器', enabled: true }]
  const [preview] = buildPreviewRows(rows, sample, '客厅 Plex')
  assert.equal(preview.label, '媒体服务器')
  assert.equal(preview.value, '客厅 Plex')
  assert.notEqual(sample.fields.server, '客厅 Plex')
})
