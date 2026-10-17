<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { actionMetaFallback, actionOrder, normalizeNotificationModel } from '../notificationModel.js'
import { buildPreviewRows, createPreviewSample, previewActionIcons } from '../previewModel.js'
import previewBanner from '../assets/preview-fantasy-banner.jpg'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaServerNotifyPlus' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
})
const emit = defineEmits(['layout', 'save', 'close', 'switch'])

const clone = value => JSON.parse(JSON.stringify(value || {}))
const draft = ref(normalizeNotificationModel(props.initialConfig))
const settingsOpen = ref(false)
const activeAction = ref('playback_started')
const draggingIndex = ref(-1)
const saved = ref(false)
const previewSample = createPreviewSample()
const actionGroups = [
  { label: '媒体库', actions: ['library_added', 'library_deleted'] },
  { label: '播放相关', actions: ['playback_started', 'playback_stopped', 'playback_paused', 'playback_resumed', 'rated'] },
  { label: '账号与调试', actions: ['auth_success', 'auth_failed', 'test'] },
]
watch(() => props.initialConfig, value => { draft.value = normalizeNotificationModel(value) }, { deep: true })
onMounted(() => {
  emit('layout', { maxWidth: '92rem' })
  try {
    const key = `mediaservernotifyplus:edit:${props.pluginId}`
    const requestedAction = window.sessionStorage.getItem(key)
    window.sessionStorage.removeItem(key)
    if (actionOrder.includes(requestedAction)) openEditor(requestedAction)
  } catch (_) { /* sessionStorage 不可用时仍可正常打开配置页 */ }
})

const actionMeta = action => {
  const supplied = draft.value._action_meta?.[action]
  return supplied || actionMetaFallback[action]
}
const fieldMeta = key => draft.value._field_catalog?.[key] || { label: key }
const activeFields = computed(() => draft.value.field_configs?.[activeAction.value] || [])
const activeMeta = computed(() => actionMeta(activeAction.value))
const enabledTypes = computed(() => new Set(draft.value.types || []))
const serverOptions = computed(() => draft.value._server_options || [])
const previewRows = computed(() => buildPreviewRows(activeFields.value, previewSample, draft.value.mediaservers?.[0]))
const showsMedia = computed(() => !['auth_success', 'auth_failed', 'test'].includes(activeAction.value))
const previewHeading = computed(() => activeAction.value === 'library_added'
  ? `已入库 ${previewSample.fileCount} 个文件`
  : activeMeta.value.label)

function isEnabled(action) {
  return enabledTypes.value.has(action)
}
function setEnabled(action, enabled) {
  const next = new Set(draft.value.types || [])
  enabled ? next.add(action) : next.delete(action)
  draft.value.types = actionOrder.filter(item => next.has(item))
}
function openEditor(action) {
  activeAction.value = action
}
function moveField(from, to) {
  const rows = activeFields.value
  if (from < 0 || to < 0 || from >= rows.length || to >= rows.length || from === to) return
  const [row] = rows.splice(from, 1)
  rows.splice(to, 0, row)
}
function startDrag(index, event) {
  draggingIndex.value = index
  event.dataTransfer.effectAllowed = 'move'
}
function dropField(index) {
  moveField(draggingIndex.value, index)
  draggingIndex.value = -1
}
function resetFields() {
  const original = draft.value._default_field_configs?.[activeAction.value]
  if (original) draft.value.field_configs[activeAction.value] = clone(original)
}
function cleanPayload() {
  const payload = clone(draft.value)
  Object.keys(payload).filter(key => key.startsWith('_')).forEach(key => delete payload[key])
  delete payload.libraries
  delete payload.fetch_metadata
  delete payload.lookup_ip
  payload.types = actionOrder.filter(action => (payload.types || []).includes(action))
  return payload
}
function saveConfig() {
  emit('save', cleanPayload())
  saved.value = true
  window.setTimeout(() => { saved.value = false }, 1800)
}
function enabledFieldCount(action) {
  return (draft.value.field_configs?.[action] || []).filter(row => row.enabled).length
}
</script>

<template>
  <div class="notify-config">
    <header class="page-header">
      <div>
        <div class="eyebrow">MEDIA LIBRARY NOTIFICATIONS</div>
        <h1>媒体库通知</h1>
        <p>选择通知类型并调整展示内容。</p>
      </div>
      <VBtn class="settings-button" variant="tonal" prepend-icon="mdi-tune-variant" @click="settingsOpen = true">
        设置
      </VBtn>
    </header>

    <VAlert v-if="!draft.enabled" class="mb-5" type="warning" variant="tonal" icon="mdi-bell-off-outline">
      插件当前未启用。你仍可编辑通知字段，启用后才会发送通知。
    </VAlert>

    <div class="workspace">
      <nav class="event-sidebar" aria-label="通知类型">
        <section v-for="group in actionGroups" :key="group.label" class="event-group">
          <h2>{{ group.label }}</h2>
          <div v-for="action in group.actions" :key="action" class="event-item" :class="{ 'event-item--active': activeAction === action }">
            <button class="event-item__select" type="button" :aria-current="activeAction === action ? 'true' : undefined" @click="openEditor(action)">
              <span class="event-icon"><VIcon :icon="actionMetaFallback[action].icon" size="22" /></span>
              <span class="event-item__copy"><strong>{{ actionMeta(action).label }}</strong><small>{{ actionMeta(action).description }}</small></span>
            </button>
            <VSwitch
              :model-value="isEnabled(action)"
              color="primary"
              hide-details
              density="compact"
              :aria-label="`启用${actionMeta(action).label}`"
              @update:model-value="setEnabled(action, $event)"
            />
          </div>
        </section>
      </nav>

      <section class="content-editor" aria-label="通知内容配置">
        <div class="editor-heading">
          <div><h2>通知内容配置</h2><p>自定义「{{ activeMeta.label }}」通知中显示的内容和顺序。</p></div>
          <span class="field-count">{{ enabledFieldCount(activeAction) }} / {{ activeFields.length }} 个字段已启用</span>
        </div>

        <div class="editor-workspace">
          <div class="preview-pane" aria-label="通知预览">
            <div class="preview-controls">
              <strong>消息预览</strong>
            </div>
            <div class="notification-card">
              <img v-if="showsMedia" class="notification-card__banner" :src="previewBanner" alt="示例媒体封面" />
              <div class="notification-card__body">
                <div class="notification-card__heading"><span aria-hidden="true">{{ previewActionIcons[activeAction] }}</span>{{ previewHeading }}</div>
                <div v-if="showsMedia" class="notification-card__media">{{ previewSample.mediaName }}</div>
                <div class="notification-card__rows">
                  <div v-for="row in previewRows" :key="row.key" class="preview-row" :class="{ 'preview-row--block': row.block }">
                    <span class="preview-row__icon" aria-hidden="true">{{ row.icon }}</span>
                    <div class="preview-row__text">
                      <template v-if="row.block"><span>{{ row.label }}</span><p>{{ row.value }}</p></template>
                      <template v-else>{{ row.label }}：{{ row.value }}</template>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <p class="preview-note">仅用于展示排版，不会发送通知。</p>
          </div>

          <div class="fields-pane">
            <div class="field-list-heading">
              <div><strong>可通知内容</strong><span>点击上下箭头调整顺序，也可拖动排序；勾选字段或修改展示名称，预览实时更新。</span></div>
              <VBtn size="small" variant="text" prepend-icon="mdi-restore" @click="resetFields">恢复默认</VBtn>
            </div>

            <div class="field-list" role="group" :aria-label="`${activeMeta.label}可通知内容`">
          <div class="field-list__header"><span>排序</span><span>字段</span><span>展示名称（可自定义）</span><span>调整</span><span>显示</span></div>
          <div
            v-for="(row, index) in activeFields"
            :key="row.key"
            class="field-row"
            :class="{ 'field-row--disabled': !row.enabled }"
            @dragover.prevent
            @drop.prevent="dropField(index)"
          >
            <button class="drag-handle" type="button" draggable="true" :aria-label="`拖动${row.label}排序`" @dragstart="startDrag(index, $event)" @dragend="draggingIndex = -1"><VIcon icon="mdi-drag-vertical" /></button>
            <div class="field-key">{{ fieldMeta(row.key).label }}</div>
            <div class="field-value">
              <VSelect
                v-if="row.key === 'server'"
                v-model="draft.mediaservers"
                :items="serverOptions"
                item-title="title"
                item-value="value"
                label="选择媒体服务器"
                placeholder="未选择时监听全部"
                density="compact"
                variant="outlined"
                multiple
                chips
                closable-chips
                clearable
                hide-details
              />
              <VTextField v-else v-model="row.label" :aria-label="`${fieldMeta(row.key).label}展示名称`" density="compact" variant="outlined" maxlength="30" hide-details />
            </div>
            <div class="field-order-buttons">
              <VBtn :disabled="index === 0" icon="mdi-chevron-up" size="x-small" variant="text" :aria-label="`上移${row.label}`" @click="moveField(index, index - 1)" />
              <VBtn :disabled="index === activeFields.length - 1" icon="mdi-chevron-down" size="x-small" variant="text" :aria-label="`下移${row.label}`" @click="moveField(index, index + 1)" />
            </div>
            <VCheckbox v-model="row.enabled" color="primary" hide-details :aria-label="`展示${row.label}`" />
          </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <footer class="page-actions">
      <span class="save-hint"><VIcon icon="mdi-information-outline" size="18" /> 字段没有数据时会自动隐藏整行</span>
      <div class="d-flex ga-2">
        <VBtn variant="text" @click="$emit('close')">取消</VBtn>
        <VBtn color="primary" variant="flat" prepend-icon="mdi-content-save-outline" @click="saveConfig">
          {{ saved ? '已保存' : '保存设置' }}
        </VBtn>
      </div>
    </footer>

    <VDialog v-model="settingsOpen" max-width="720" scrollable>
      <VCard class="settings-dialog">
        <VCardTitle class="dialog-header">
          <div class="dialog-title-icon"><VIcon icon="mdi-tune-variant" /></div>
          <div><div class="dialog-kicker">GLOBAL SETTINGS</div><div>通知设置</div></div>
          <VBtn class="ml-auto" icon="mdi-close" variant="text" @click="settingsOpen = false" />
        </VCardTitle>
        <VCardText class="dialog-body settings-stack">
          <div class="setting-row setting-row--featured">
            <div><strong>启用插件</strong><span>接收媒体服务器事件并发送通知</span></div>
            <VSwitch v-model="draft.enabled" color="primary" hide-details />
          </div>

          <div class="setting-block">
            <label>媒体服务器</label>
            <VSelect
              v-model="draft.mediaservers"
              :items="serverOptions"
              item-title="title"
              item-value="value"
              placeholder="未选择时监听全部媒体服务器"
              multiple
              chips
              closable-chips
              clearable
              variant="outlined"
              hide-details
            />
            <small>选择需要接收通知的 Emby、Jellyfin 或 Plex 实例。</small>
            <small>需在所选媒体服务器中设置 Webhooks，并勾选对应的通知项。</small>
          </div>

          <div class="info-panel webhook-guide" role="note">
            <VIcon class="info-panel__icon" icon="mdi-information-outline" size="20" />
            <div class="info-panel__content">
              <strong>媒体服务器 Webhook 配置</strong>
              <span>回调地址为：</span>
              <code>http://localhost:3000/api/v1/webhook?token=API_TOKEN&amp;source=媒体服务器名:3001</code>
              <span>其中 <code>API_TOKEN</code> 替换为 MoviePilot 设置中的 API Token，<code>source</code> 按“媒体服务器名:3001”填写。如果媒体服务器与 MoviePilot 不在同一台主机，请将 <code>localhost</code> 换成 MoviePilot 的实际 IP 或域名。</span>
            </div>
          </div>

          <div class="setting-row">
            <div><strong>聚合剧集入库</strong><span>同一剧集在窗口内只发送一条通知</span></div>
            <VSwitch v-model="draft.aggregate_enabled" color="primary" hide-details />
          </div>
          <VTextField v-if="draft.aggregate_enabled" v-model.number="draft.aggregate_time" label="聚合窗口（秒）" type="number" min="1" variant="outlined" hide-details />

          <div class="settings-grid">
            <VTextField v-model.number="draft.dedupe_library" label="入库/删除去重（秒）" type="number" min="0" variant="outlined" hide-details />
            <VTextField v-model.number="draft.dedupe_playback" label="播放事件去重（秒）" type="number" min="0" variant="outlined" hide-details />
          </div>

          <div class="setting-row"><div><strong>停止时发送待聚合消息</strong><span>插件重载或停止时不丢弃队列</span></div><VSwitch v-model="draft.flush_on_stop" color="primary" hide-details /></div>

          <div class="setting-block test-block">
            <label>测试通知</label>
            <div class="settings-grid settings-grid--test">
              <VSelect v-model="draft.preview_type" :items="actionOrder.map(value => ({ value, title: actionMeta(value).label }))" label="通知类型" variant="outlined" hide-details />
              <VSwitch v-model="draft.send_test" label="保存时发送" color="primary" hide-details />
            </div>
          </div>

          <div class="info-panel" role="note">
            <VIcon class="info-panel__icon" icon="mdi-information-outline" size="20" />
            <div class="info-panel__content">消息渠道遵循 MoviePilot 全局设置，通知类型固定为“媒体服务器”。</div>
          </div>
        </VCardText>
        <VCardActions class="dialog-actions"><span>设置随主页面一起保存</span><VBtn color="primary" variant="flat" @click="settingsOpen = false">完成</VBtn></VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.notify-config { --surface-soft: rgba(var(--v-theme-on-surface), .045); --line: rgba(var(--v-border-color), .18); padding: 8px 4px 4px; color: rgb(var(--v-theme-on-surface)); }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.eyebrow, .dialog-kicker { color: rgb(var(--v-theme-primary)); font-size: 11px; font-weight: 750; letter-spacing: .13em; }
h1 { margin: 3px 0 4px; font-size: clamp(28px, 4vw, 38px); line-height: 1.15; letter-spacing: -.035em; }
.page-header p { margin: 0; color: rgba(var(--v-theme-on-surface), .62); }
.settings-button { margin-top: 8px; }
.workspace { display: grid; grid-template-columns: minmax(230px, 250px) minmax(0, 1fr); gap: 16px; align-items: start; }
.event-sidebar, .content-editor { min-width: 0; border: 1px solid var(--line); border-radius: 16px; background: rgb(var(--v-theme-surface)); }
.event-sidebar { padding: 14px 10px; }
.event-group + .event-group { margin-top: 18px; }
.event-group h2 { margin: 0 12px 8px; color: rgba(var(--v-theme-on-surface), .56); font-size: 12px; font-weight: 650; }
.event-item { display: flex; align-items: center; gap: 2px; min-height: 58px; border-radius: 10px; transition: background-color .15s ease; }
.event-item:hover { background: var(--surface-soft); }
.event-item--active { background: rgba(var(--v-theme-primary), .14); }
.event-item--active:hover { background: rgba(var(--v-theme-primary), .18); }
.event-item__select { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; padding: 6px 4px 6px 10px; text-align: left; color: inherit; border: 0; border-radius: 9px; background: transparent; cursor: pointer; }
.event-item__select:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: -2px; }
.event-icon, .dialog-title-icon { display: grid; place-items: center; flex: none; width: 38px; height: 38px; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), .12); border-radius: 10px; }
.event-item__copy { min-width: 0; }
.event-item__copy strong, .event-item__copy small { display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.event-item__copy strong { font-size: 14px; font-weight: 650; }
.event-item__copy small { margin-top: 2px; color: rgba(var(--v-theme-on-surface), .53); font-size: 11px; }
.event-item :deep(.v-switch) { flex: none; margin-right: 4px; }
.content-editor { padding: 20px 22px 22px; }
.editor-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.editor-heading h2 { margin: 0; font-size: 19px; line-height: 1.3; }
.editor-heading p { margin: 4px 0 0; color: rgba(var(--v-theme-on-surface), .58); font-size: 13px; }
.field-count { flex: none; color: rgba(var(--v-theme-on-surface), .54); font-size: 12px; }
.editor-workspace { display: grid; grid-template-columns: minmax(320px, .85fr) minmax(440px, 1.15fr); align-items: start; gap: 18px; margin-top: 18px; }
.preview-pane, .fields-pane { min-width: 0; }
.preview-pane { position: sticky; top: 12px; max-height: calc(100vh - 100px); overflow-y: auto; scrollbar-width: thin; }
.preview-controls { margin-bottom: 10px; }
.preview-controls strong { font-size: 14px; }
.notification-card { overflow: hidden; border: 1px solid rgba(255, 255, 255, .06); border-radius: 11px; background: #202020; color: #f1f1f1; }
.notification-card__banner { display: block; width: 100%; aspect-ratio: 2.35; object-fit: cover; }
.notification-card__body { padding: 17px 18px 19px; }
.notification-card__heading { display: flex; align-items: baseline; gap: 8px; font-size: 20px; line-height: 1.35; }
.notification-card__heading span { flex: none; }
.notification-card__media { margin-top: 4px; font-size: 23px; line-height: 1.35; }
.notification-card__rows { margin-top: 14px; }
.preview-row { display: grid; grid-template-columns: 23px minmax(0, 1fr); align-items: start; gap: 5px; color: #aaa8ac; font-size: 14px; line-height: 1.5; }
.preview-row__icon { line-height: 1.5; }
.preview-row__text { min-width: 0; overflow-wrap: anywhere; }
.preview-row--block { margin-top: 3px; }
.preview-row--block p { margin: 1px 0 0; line-height: 1.65; }
.preview-note { margin: 9px 2px 0; color: rgba(var(--v-theme-on-surface), .5); font-size: 11px; }
.page-actions { position: sticky; bottom: 0; z-index: 3; display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 22px; padding: 14px 0 6px; background: rgb(var(--v-theme-surface)); }
.save-hint { display: flex; align-items: center; gap: 7px; color: rgba(var(--v-theme-on-surface), .58); font-size: 12px; }
.settings-dialog { border-radius: 20px !important; }
.dialog-header { display: flex; align-items: center; gap: 13px; padding: 20px 22px 16px; border-bottom: 1px solid var(--line); }
.dialog-title-icon { width: 42px; height: 42px; border-radius: 12px; }
.dialog-body { padding: 20px 22px 22px !important; }
.field-list-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 32px; margin: 0 0 10px; }
.field-list-heading strong, .field-list-heading span { display: block; }
.field-list-heading span { margin-top: 2px; color: rgba(var(--v-theme-on-surface), .52); font-size: 12px; }
.field-list { overflow: hidden; border: 1px solid var(--line); border-radius: 12px; }
.field-list__header, .field-row { display: grid; grid-template-columns: 38px minmax(84px, .6fr) minmax(160px, 1.6fr) 60px 48px; align-items: center; gap: 8px; }
.field-list__header { padding: 9px 12px; color: rgba(var(--v-theme-on-surface), .55); font-size: 11px; border-bottom: 1px solid var(--line); }
.field-list__header span:last-child { text-align: center; }
.field-row { min-height: 54px; padding: 5px 12px; border-bottom: 1px solid var(--line); }
.field-row:last-child { border-bottom: 0; }
.field-row:nth-child(even) { background: var(--surface-soft); }
.field-row--disabled .field-key, .field-row--disabled .field-value { opacity: .58; }
.drag-handle { width: 32px; height: 40px; color: rgba(var(--v-theme-on-surface), .46); cursor: grab; border: 0; background: transparent; border-radius: 8px; }
.drag-handle:active { cursor: grabbing; }
.field-key { font-size: 13px; }
.field-value { min-width: 0; }
.field-value :deep(.v-field) { min-height: 36px; }
.field-value :deep(.v-field__input) { min-height: 36px; padding-top: 5px; padding-bottom: 5px; }
.field-order-buttons { display: flex; }
.dialog-actions { display: flex; justify-content: space-between; min-height: 66px; padding: 12px 22px !important; border-top: 1px solid var(--line); color: rgba(var(--v-theme-on-surface), .56); font-size: 12px; }
.settings-stack { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.settings-stack > * { flex-shrink: 0; }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 14px; }
.setting-row--featured { border-color: rgba(var(--v-theme-primary), .32); background: rgba(var(--v-theme-primary), .055); }
.setting-row strong, .setting-row span { display: block; }
.setting-row span { margin-top: 3px; color: rgba(var(--v-theme-on-surface), .52); font-size: 12px; }
.setting-block { display: grid; gap: 8px; padding: 15px 16px; border: 1px solid var(--line); border-radius: 14px; }
.setting-block label { font-size: 14px; font-weight: 650; }
.setting-block small { color: rgba(var(--v-theme-on-surface), .5); }
.info-panel { display: flex; align-items: flex-start; gap: 12px; min-width: 0; padding: 14px 16px; border-radius: 12px; background: rgba(var(--v-theme-info), .12); color: rgb(var(--v-theme-on-surface)); line-height: 1.55; }
.info-panel__icon { flex: none; margin-top: 2px; color: rgb(var(--v-theme-info)); }
.info-panel__content { min-width: 0; overflow-wrap: anywhere; }
.webhook-guide strong, .webhook-guide span, .webhook-guide code { display: block; }
.webhook-guide span { margin-top: 5px; line-height: 1.55; }
.webhook-guide code { margin-top: 9px; padding: 9px 10px; white-space: normal; overflow-wrap: anywhere; border-radius: 8px; background: rgba(var(--v-theme-on-surface), .07); color: rgb(var(--v-theme-info)); font-size: 12px; }
.webhook-guide span code { display: inline; margin: 0; padding: 0; background: transparent; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.settings-grid--test { align-items: center; }
@media (max-width: 1100px) {
  .editor-workspace { grid-template-columns: minmax(0, 1fr); }
  .preview-pane { position: static; max-height: none; }
  .notification-card { max-width: 600px; }
}
@media (max-width: 900px) {
  .workspace { grid-template-columns: minmax(210px, 240px) minmax(0, 1fr); }
  .event-item__copy small { display: none; }
  .field-list__header, .field-row { grid-template-columns: 30px minmax(70px, .55fr) minmax(120px, 1.5fr) 48px 40px; gap: 4px; }
  .field-order-buttons :deep(.v-btn) { width: 24px; }
}
@media (max-width: 680px) {
  .notify-config { padding-top: 0; }
  .page-header { align-items: center; }
  .page-header p, .eyebrow { display: none; }
  h1 { font-size: 26px; }
  .workspace { grid-template-columns: minmax(0, 1fr); }
  .event-sidebar { display: flex; gap: 20px; overflow-x: auto; padding: 10px; }
  .event-group { min-width: max-content; }
  .event-group + .event-group { margin-top: 0; }
  .event-group h2 { margin-left: 5px; }
  .event-item { min-width: 170px; }
  .event-item__copy small { display: none; }
  .content-editor { padding: 16px 12px; }
  .editor-heading { display: block; }
  .field-count { display: block; margin-top: 5px; }
  .notification-card__media { font-size: 21px; }
  .field-list__header { display: none; }
  .field-row { grid-template-columns: 44px minmax(0, 1fr) 36px; grid-template-areas: 'order key check' 'order value check'; gap: 2px 6px; padding: 8px; }
  .drag-handle { display: none; }
  .field-key { grid-area: key; }
  .field-value { grid-area: value; }
  .field-row > :last-child { grid-area: check; }
  .field-order-buttons { grid-area: order; display: flex; flex-direction: column; align-items: center; }
  .field-order-buttons :deep(.v-btn) { width: 44px; height: 44px; }
  .page-actions { align-items: flex-end; }
  .save-hint { max-width: 150px; }
  .settings-grid { grid-template-columns: 1fr; }
}
</style>
