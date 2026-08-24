<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'CourseOrganizer' },
  initialConfig: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save', 'close'])

const localConfig = ref({})
const saving = ref(false)
const monitoringBlocked = ref(true)
const monitoringMessage = ref('正在自动检测 MoviePilot 自动监控配置…')
const monitoringMessageType = ref('info')

const configDefaults = {
  auto_organize: false,
}

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function normalizeInitialConfig(value) {
  const config = clone(value)
  const rawAutoOrganize = Object.prototype.hasOwnProperty.call(config, 'auto_organize')
    ? config.auto_organize
    : String(config.naming_mode || '').trim().toLowerCase() === 'apply'
  const autoOrganize = typeof rawAutoOrganize === 'string'
    ? ['1', 'true', 'yes', 'on'].includes(rawAutoOrganize.trim().toLowerCase())
    : Boolean(rawAutoOrganize)

  return { ...configDefaults, ...config, auto_organize: autoOrganize }
}

watch(
  () => props.initialConfig,
  value => { localConfig.value = normalizeInitialConfig(value) },
  { immediate: true, deep: true },
)

function saveConfig() {
  if (saving.value) return
  if (localConfig.value.auto_organize && monitoringBlocked.value) return
  saving.value = true
  try {
    emit('save', clone(localConfig.value))
  } finally {
    saving.value = false
  }
}

async function loadMonitoringStatus() {
  if (typeof props.api?.get !== 'function') {
    monitoringMessage.value = '无法读取 MoviePilot 自动监控配置，自动整理暂不可开启。'
    monitoringMessageType.value = 'error'
    return
  }
  try {
    const response = await props.api.get(`plugin/${props.pluginId || 'CourseOrganizer'}/review`)
    const body = response?.data ?? response
    const data = body?.data ?? body ?? {}
    if (data.monitoring_enabled) {
      const rules = Array.isArray(data.monitoring_rules) ? data.monitoring_rules.filter(Boolean) : []
      const ruleText = rules.length ? `（${rules.join('、')}）` : ''
      const sourceText = data.incoming_path ? `来源目录 ${data.incoming_path}` : '当前来源目录'
      monitoringBlocked.value = true
      monitoringMessageType.value = 'error'
      monitoringMessage.value = `已自动检测到 ${sourceText} 与 MoviePilot 自动监控规则${ruleText}重叠；自动整理已禁止，仅保留安全预览。`
      localConfig.value = { ...localConfig.value, auto_organize: false }
      return
    }
    monitoringBlocked.value = false
    monitoringMessageType.value = 'success'
    monitoringMessage.value = '已自动检测 MoviePilot 自动监控配置，当前来源目录未发现监控冲突。'
  } catch (error) {
    monitoringBlocked.value = true
    monitoringMessageType.value = 'error'
    monitoringMessage.value = error?.message
      ? `无法读取 MoviePilot 自动监控配置：${error.message}`
      : '无法读取 MoviePilot 自动监控配置，自动整理暂不可开启。'
    localConfig.value = { ...localConfig.value, auto_organize: false }
  }
}

async function openMoviePilotSettings() {
  emit('close')
  await nextTick()
  window.location.assign('#/setting')
}

onMounted(loadMonitoringStatus)
</script>

<template>
  <VForm class="course-config" aria-label="整理识别设置" @submit.prevent="saveConfig">
    <VToolbar density="comfortable" color="transparent" class="course-config__toolbar">
      <div class="text-h6">整理识别设置</div>
      <VSpacer />
      <VBtn icon="mdi-close" variant="text" aria-label="关闭设置" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <VAlert type="info" variant="tonal" class="ma-3" role="note">
      目录、媒体类型、分类规则、整理方式、重命名、刮削和智能助手均直接读取 MoviePilot 系统设置，不在插件内重复配置。
      <template #append>
        <VBtn variant="tonal" color="primary" prepend-icon="mdi-folder-cog" @click.stop="openMoviePilotSettings">
          打开目录设置
        </VBtn>
      </template>
    </VAlert>

    <VSwitch
      v-model="localConfig.auto_organize"
      class="mx-4 mb-2"
      label="自动整理符合条件的项目"
      aria-label="自动整理符合条件的项目"
      hint="开启后，仅自动整理识别结果可靠且目标媒体库明确的项目；不确定项目继续保留在待确认列表"
      persistent-hint
      color="primary"
      :disabled="monitoringBlocked"
    />

    <VAlert :type="monitoringMessageType" variant="tonal" density="compact" class="mx-3 mb-3">
      {{ monitoringMessage }}
    </VAlert>

    <div class="course-config__actions">
      <VBtn variant="text" min-width="88" @click="emit('close')">取消</VBtn>
      <VBtn color="primary" min-width="108" :loading="saving" @click="saveConfig">保存</VBtn>
    </div>
  </VForm>
</template>

<style scoped>
.course-config {
  min-width: 0;
  padding-bottom: 12px;
}

.course-config__toolbar {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 0 12px;
}

.course-config :deep(.v-switch) {
  margin-bottom: 12px;
}

.course-config__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 16px;
}

.course-config :deep(.v-btn) {
  min-height: 44px;
}

@media (max-width: 599px) {
  .course-config :deep(.v-alert__content) {
    min-width: 0;
  }

  .course-config :deep(.v-alert__append) {
    margin-inline-start: 0;
    margin-top: 12px;
  }
}
</style>
