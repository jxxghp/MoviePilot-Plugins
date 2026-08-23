<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save', 'close'])

const localConfig = ref({})
const saving = ref(false)

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
  saving.value = true
  try {
    emit('save', clone(localConfig.value))
  } finally {
    saving.value = false
  }
}

async function openMoviePilotSettings() {
  emit('close')
  await nextTick()
  window.location.assign('#/setting')
}
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
    />

    <VAlert v-if="localConfig.auto_organize" type="warning" variant="tonal" density="compact" class="mx-3 mb-3">
      请确认同一来源目录未同时启用 MoviePilot 自动监控，避免两个整理任务竞争同一批文件。
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
