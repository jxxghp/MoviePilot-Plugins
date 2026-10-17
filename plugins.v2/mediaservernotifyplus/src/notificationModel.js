export const actionOrder = [
  'library_added', 'library_deleted', 'playback_started', 'playback_stopped',
  'playback_paused', 'playback_resumed', 'auth_success', 'auth_failed', 'rated', 'test',
]

export const actionMetaFallback = {
  library_added: { label: '已入库', description: '媒体文件加入媒体库时通知', icon: 'mdi-folder-arrow-down' },
  library_deleted: { label: '已删除', description: '媒体文件从媒体库移除时通知', icon: 'mdi-delete-outline' },
  playback_started: { label: '开始播放', description: '用户开始播放媒体时通知', icon: 'mdi-play-circle-outline' },
  playback_stopped: { label: '停止播放', description: '用户停止播放媒体时通知', icon: 'mdi-stop-circle-outline' },
  playback_paused: { label: '暂停播放', description: '用户暂停播放媒体时通知', icon: 'mdi-pause-circle-outline' },
  playback_resumed: { label: '继续播放', description: '用户继续播放媒体时通知', icon: 'mdi-play-circle' },
  auth_success: { label: '登录成功', description: '用户成功登录媒体服务器时通知', icon: 'mdi-login-variant' },
  auth_failed: { label: '登录失败', description: '媒体服务器登录失败时通知', icon: 'mdi-shield-alert-outline' },
  rated: { label: '已标记', description: '用户标记已看、未看或评分时通知', icon: 'mdi-star-circle-outline' },
  test: { label: '测试', description: '用于检查当前通知样式', icon: 'mdi-flask-outline' },
}

const retiredFields = new Set(['client', 'year', 'channel', 'ip_location', 'play_link'])
const libraryUnsupportedFields = new Set(['user', 'device', 'progress', 'ip'])
const isAllowedField = (action, key) =>
  !retiredFields.has(key) && (!['library_added', 'library_deleted'].includes(action) || !libraryUnsupportedFields.has(key))
const clone = value => JSON.parse(JSON.stringify(value || {}))

export function normalizeNotificationModel(value) {
  const model = clone(value)
  model.field_configs = model.field_configs || {}
  const defaults = model._default_field_configs || {}

  for (const action of actionOrder) {
    const defaultRows = (defaults[action] || []).filter(row => isAllowedField(action, row.key))
    defaults[action] = defaultRows
    const allowed = new Set(defaultRows.map(row => row.key))
    const sourceRows = Array.isArray(model.field_configs[action]) ? model.field_configs[action] : []
    const rows = []
    const seen = new Set()

    for (const source of sourceRows) {
      if (!source || !isAllowedField(action, source.key) || seen.has(source.key)) continue
      if (allowed.size && !allowed.has(source.key)) continue
      const row = clone(source)
      if (row.key === 'device' && ['设备 / 客户端', '设备/客户端'].includes(row.label)) row.label = '设备'
      if (row.key === 'library' && ['媒体库', '媒体类别'].includes(row.label)) row.label = '媒体库分类'
      rows.push(row)
      seen.add(row.key)
    }
    for (const row of defaultRows) {
      if (!seen.has(row.key)) rows.push(clone(row))
    }
    model.field_configs[action] = rows
  }

  if (model._field_catalog) {
    for (const key of retiredFields) delete model._field_catalog[key]
  }
  return model
}
