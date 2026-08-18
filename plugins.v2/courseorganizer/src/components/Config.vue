<script setup>
import { ref, watch } from 'vue'

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
</script>

<template>
  <VForm class="course-config" aria-label="课程识别设置" @submit.prevent="saveConfig">
    <VToolbar density="comfortable" color="transparent" class="course-config__toolbar">
      <div class="text-h6">课程识别设置</div>
      <VSpacer />
      <VBtn
        icon="mdi-content-save"
        color="primary"
        variant="text"
        :loading="saving"
        aria-label="保存课程识别设置"
        @click="saveConfig"
      />
      <VBtn icon="mdi-close" variant="text" aria-label="关闭设置" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <VAlert type="info" variant="tonal" class="ma-3" role="note">
      来源目录、目标媒体库、搬运方式、重命名、刮削和通知统一使用
      MoviePilot「设置 → 存储 &amp; 目录」，本插件不重复保存这些配置。
      <template #append>
        <VBtn href="#/setting" variant="tonal" color="primary" prepend-icon="mdi-folder-cog">
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
            label="启用 AI 辅助复核"
            aria-label="启用 AI 辅助复核"
            color="primary"
          />
          <VSwitch
            v-model="localConfig.naming_clear_cache_once"
            label="一次性清空识别缓存"
            aria-label="一次性清空识别缓存"
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
