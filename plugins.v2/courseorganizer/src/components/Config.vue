<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save', 'close'])

const localConfig = ref({})
const saving = ref(false)

const recognitionDefaults = {
  naming_sources: 'themoviedb,douban',
  naming_auto_threshold: 90,
  naming_min_margin: 12,
  naming_uncertain_policy: 'local',
  naming_append_tmdb_id: false,
  naming_ai_review: false,
  naming_clear_cache_once: false,
}

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

watch(
  () => props.initialConfig,
  value => { localConfig.value = { ...recognitionDefaults, ...clone(value) } },
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
      目录和整理规则沿用 MoviePilot 系统设置，本插件只保留识别选项。
      <template #append>
        <VBtn variant="tonal" color="primary" prepend-icon="mdi-folder-cog" @click.stop="openMoviePilotSettings">
          打开目录设置
        </VBtn>
      </template>
    </VAlert>

    <VExpansionPanels class="mx-3 mb-3" variant="accordion">
      <VExpansionPanel title="高级识别设置" value="recognition">
        <VExpansionPanelText>
          <VTextField
            v-model="localConfig.naming_sources"
            label="识别来源（逗号分隔）"
            aria-label="识别来源（逗号分隔）"
            variant="outlined"
          />
          <VTextField
            v-model.number="localConfig.naming_auto_threshold"
            label="自动采用阈值（80~100）"
            aria-label="自动采用阈值（80~100）"
            type="number"
            min="80"
            max="100"
            variant="outlined"
          />
          <VTextField
            v-model.number="localConfig.naming_min_margin"
            label="领先幅度（5~30）"
            aria-label="领先幅度（5~30）"
            type="number"
            min="5"
            max="30"
            variant="outlined"
          />
          <VSwitch
            v-model="localConfig.naming_append_tmdb_id"
            label="名称追加 TMDB ID"
            aria-label="名称追加 TMDB ID"
            color="primary"
          />
          <VSwitch
            v-model="localConfig.naming_ai_review"
            label="启用 AI 搜索与复核"
            aria-label="启用 AI 搜索与复核"
            hint="复杂目录会先精简名称再搜索"
            persistent-hint
            color="primary"
          />
          <VSwitch
            v-model="localConfig.naming_clear_cache_once"
            label="一次性清空识别缓存"
            aria-label="一次性清空识别缓存"
            hint="下次运行时清除旧识别结果；执行后自动复位"
            persistent-hint
            color="error"
          />
        </VExpansionPanelText>
      </VExpansionPanel>
    </VExpansionPanels>

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

.course-config :deep(.v-text-field),
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
