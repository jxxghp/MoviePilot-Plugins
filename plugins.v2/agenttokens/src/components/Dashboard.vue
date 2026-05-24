<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  allowRefresh: {
    type: Boolean,
    default: true,
  },
})

const loading = ref(false)
const status = ref({ providers: [], summary: {} })
let timer = null

const summary = computed(() => status.value.summary || {})
const providers = computed(() => status.value.providers || [])

// 兼容 MoviePilot API 包装器和原始响应两种返回形态。
function unwrapResponse(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

// 格式化 token 数字。
function formatTokens(value) {
  const numberValue = Number(value || 0)
  return Number.isFinite(numberValue) ? numberValue.toLocaleString() : '0'
}

// 读取仪表板所需的精简状态。
async function loadStatus() {
  if (!props.allowRefresh) return
  loading.value = true
  try {
    const response = await props.api.get('plugin/AgentTokens/status')
    status.value = unwrapResponse(response) || status.value
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadStatus()
  timer = window.setInterval(loadStatus, 30000)
})

onUnmounted(() => {
  if (timer) {
    window.clearInterval(timer)
  }
})
</script>

<template>
  <div class="agenttokens-dashboard">
    <div class="d-flex align-center mb-3">
      <div>
        <div class="text-subtitle-2">Agent Tokens 管理</div>
        <div class="text-h5">{{ summary.available_count || 0 }} / {{ summary.enabled_count || 0 }}</div>
      </div>
      <VSpacer />
      <VBtn icon="mdi-refresh" variant="text" size="small" :loading="loading" @click="loadStatus" />
    </div>

    <VProgressLinear
      :model-value="summary.total_limit ? Math.min((summary.total_used || 0) * 100 / summary.total_limit, 100) : 0"
      color="primary"
      height="8"
      rounded
      class="mb-3"
    />

    <div class="text-caption text-medium-emphasis mb-3">
      {{ formatTokens(summary.total_used) }} / {{ summary.total_limit ? formatTokens(summary.total_limit) : '不限' }}
    </div>

    <VList density="compact" class="py-0">
      <VListItem v-for="row in providers.slice(0, 4)" :key="row.id" :title="row.name" :subtitle="row.model">
        <template #prepend>
          <VIcon :color="row.usage?.exhausted ? 'error' : 'success'" size="small">
            {{ row.usage?.exhausted ? 'mdi-alert-circle' : 'mdi-check-circle' }}
          </VIcon>
        </template>
        <template #append>
          <span class="text-caption">{{ formatTokens(row.usage?.total_tokens) }}</span>
        </template>
      </VListItem>
    </VList>
  </div>
</template>
