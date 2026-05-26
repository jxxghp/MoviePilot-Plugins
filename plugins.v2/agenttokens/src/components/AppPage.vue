<script setup>
import { computed, onMounted, ref } from 'vue'
import AgentTokensManager from './AgentTokensManager.vue'
import { unwrapResponse } from '../provider'

const props = defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'AgentTokens',
  },
  hideTitle: {
    type: Boolean,
    default: false,
  },
})

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref({
  config: { enabled: false, show_sidebar_nav: true, providers: [] },
  providers: [],
  summary: {},
})

// 构造 API 基础路径。
const pluginBase = computed(() => `plugin/${props.pluginId || 'AgentTokens'}`)
const config = computed(() => status.value.config || { enabled: false, show_sidebar_nav: true, providers: [] })
const providerRows = computed(() => status.value.providers || [])
const summary = computed(() => status.value.summary || {})

// 从插件 API 拉取当前配置和用量状态。
async function loadStatus() {
  loading.value = true
  error.value = ''
  try {
    const response = await props.api.get(`${pluginBase.value}/status`)
    status.value = unwrapResponse(response) || status.value
  } catch (err) {
    error.value = err?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// 保存完整插件配置并刷新服务端标准化后的状态。
async function saveConfig() {
  saving.value = true
  error.value = ''
  try {
    const payload = {
      enabled: Boolean(config.value.enabled),
      show_sidebar_nav: Boolean(config.value.show_sidebar_nav),
      providers: [...(config.value.providers || [])],
    }
    const response = await props.api.post(`${pluginBase.value}/config`, payload)
    status.value = unwrapResponse(response) || status.value
  } catch (err) {
    error.value = err?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

// 重置指定供应商的运行记录。
async function resetUsage(providerId) {
  if (!providerId) return
  loading.value = true
  try {
    const response = await props.api.post(`${pluginBase.value}/usage/reset`, { provider_id: providerId })
    status.value = unwrapResponse(response) || status.value
  } finally {
    loading.value = false
  }
}

// 重置全部供应商的运行记录。
async function resetAllUsage() {
  loading.value = true
  try {
    const response = await props.api.post(`${pluginBase.value}/usage/reset_all`, {})
    status.value = unwrapResponse(response) || status.value
  } finally {
    loading.value = false
  }
}

defineExpose({
  loadStatus,
  saveConfig,
  loading,
  saving,
})

onMounted(loadStatus)
</script>

<template>
  <AgentTokensManager
    :config="config"
    :provider-rows="providerRows"
    :summary="summary"
    :error="error"
    :loading="loading"
    :saving="saving"
    :hide-title="hideTitle"
    @refresh="loadStatus"
    @save="saveConfig"
    @reset-usage="resetUsage"
    @reset-all-usage="resetAllUsage"
  />
</template>
