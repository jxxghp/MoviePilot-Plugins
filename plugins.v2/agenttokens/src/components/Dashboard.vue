<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { formatTokens, unwrapResponse } from '../provider'

const props = defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  config: {
    type: Object,
    default: () => ({ attrs: {} }),
  },
  allowRefresh: {
    type: Boolean,
    default: true,
  },
  refreshInterval: {
    type: Number,
    default: 0,
  },
})

const loading = ref(false)
const error = ref('')
const initialDataLoaded = ref(false)
const lastRefreshedAt = ref(null)
const status = ref({ providers: [], summary: {} })
let timer = null

const attrs = computed(() => props.config?.attrs || {})
const summary = computed(() => status.value.summary || {})
const providers = computed(() => status.value.providers || [])
const visibleProviders = computed(() => providers.value.slice(0, 3))
const totalUsed = computed(() => Number(summary.value.total_used || 0))
const totalLimit = computed(() => Number(summary.value.total_limit || 0))
const remainingTokens = computed(() => {
  if (totalLimit.value <= 0) return null
  return Math.max(totalLimit.value - totalUsed.value, 0)
})
const usagePercent = computed(() => {
  if (totalLimit.value <= 0) return 0
  return Math.min((totalUsed.value * 100) / totalLimit.value, 100)
})
const usagePercentText = computed(() => (totalLimit.value > 0 ? `${Math.round(usagePercent.value)}%` : '不限'))
const progressColor = computed(() => {
  if (totalLimit.value <= 0) return 'primary'
  if (usagePercent.value >= 90) return 'error'
  if (usagePercent.value >= 70) return 'warning'
  return 'success'
})
// 兼容宿主传入的数字或字符串刷新间隔。
const refreshSeconds = computed(() => {
  const seconds = Number(props.refreshInterval || attrs.value.refresh || 0)
  return Number.isFinite(seconds) ? seconds : 0
})
const cardTitle = computed(() => attrs.value.title || 'Agent Tokens 管理')
const cardSubtitle = computed(() => attrs.value.subtitle || 'LLM 配额使用情况')
const cardFlat = computed(() => attrs.value.border === false)
const lastRefreshedTime = computed(() => {
  if (!lastRefreshedAt.value) return ''
  return new Date(lastRefreshedAt.value).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  })
})

// 读取 Agent Tokens 仪表板状态。
async function loadStatus() {
  if (!props.api?.get) {
    error.value = 'API 未就绪'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const response = await props.api.get('plugin/AgentTokens/status')
    status.value = unwrapResponse(response) || status.value
    initialDataLoaded.value = true
    lastRefreshedAt.value = Date.now()
  } catch (err) {
    error.value = err?.message || '获取数据失败'
  } finally {
    loading.value = false
  }
}

// 启动宿主传入或插件配置中的自动刷新。
function startRefreshTimer() {
  if (refreshSeconds.value <= 0) return
  timer = window.setInterval(loadStatus, refreshSeconds.value * 1000)
}

// 清理仪表板自动刷新计时器。
function stopRefreshTimer() {
  if (!timer) return
  window.clearInterval(timer)
  timer = null
}

onMounted(() => {
  loadStatus()
  startRefreshTimer()
})

onUnmounted(() => {
  stopRefreshTimer()
})
</script>

<template>
  <div class="agenttokens-dashboard-widget">
    <VCard :flat="cardFlat" :loading="loading" class="agenttokens-dashboard-card">
      <VCardItem class="agenttokens-dashboard-card__header">
        <template #prepend>
          <VAvatar color="primary" variant="tonal" size="36">
            <VIcon icon="mdi-key-chain" size="20" />
          </VAvatar>
        </template>
        <VCardTitle class="agenttokens-dashboard-card__title">{{ cardTitle }}</VCardTitle>
        <VCardSubtitle>{{ cardSubtitle }}</VCardSubtitle>
      </VCardItem>

      <VCardText class="agenttokens-dashboard-card__body">
        <div v-if="loading && !initialDataLoaded" class="agenttokens-dashboard-state">
          <VProgressCircular indeterminate color="primary" size="28" />
        </div>

        <VAlert v-else-if="error" type="error" variant="tonal" density="compact" class="text-caption">
          {{ error }}
        </VAlert>

        <div v-else-if="initialDataLoaded" class="agenttokens-dashboard-content">
          <div class="agenttokens-dashboard-summary">
            <VProgressCircular
              :model-value="usagePercent"
              :color="progressColor"
              bg-color="surface-variant"
              :size="84"
              :width="8"
            >
              <span class="agenttokens-dashboard-summary__percent">{{ usagePercentText }}</span>
            </VProgressCircular>

            <div class="agenttokens-dashboard-summary__body">
              <div class="text-caption text-medium-emphasis">可用供应商</div>
              <div class="agenttokens-dashboard-summary__count">
                {{ summary.available_count || 0 }}
                <span>/ {{ summary.enabled_count || 0 }}</span>
              </div>
              <VProgressLinear
                :model-value="usagePercent"
                :color="progressColor"
                height="6"
                rounded
              />
            </div>
          </div>

          <div class="agenttokens-dashboard-metrics">
            <div class="agenttokens-dashboard-metric">
              <span>累计</span>
              <strong>{{ formatTokens(totalUsed) }}</strong>
            </div>
            <div class="agenttokens-dashboard-metric">
              <span>额度</span>
              <strong>{{ totalLimit > 0 ? formatTokens(totalLimit) : '不限' }}</strong>
            </div>
            <div class="agenttokens-dashboard-metric">
              <span>剩余</span>
              <strong>{{ remainingTokens === null ? '不限' : formatTokens(remainingTokens) }}</strong>
            </div>
          </div>

          <div v-if="visibleProviders.length" class="agenttokens-dashboard-list">
            <div v-for="row in visibleProviders" :key="row.id" class="agenttokens-dashboard-provider">
              <VIcon
                :icon="row.usage?.exhausted ? 'mdi-alert-circle' : 'mdi-check-circle'"
                :color="row.usage?.exhausted ? 'error' : 'success'"
                size="16"
              />
              <div class="agenttokens-dashboard-provider__main">
                <div class="agenttokens-dashboard-provider__name">{{ row.name || '未命名供应商' }}</div>
                <div class="agenttokens-dashboard-provider__model">{{ row.model || '未配置模型' }}</div>
              </div>
              <div class="agenttokens-dashboard-provider__tokens">
                {{ formatTokens(row.usage?.total_tokens) }}
              </div>
            </div>
          </div>

          <div v-else class="agenttokens-dashboard-empty">
            <VIcon icon="mdi-database-off-outline" size="18" />
            <span>暂无供应商</span>
          </div>
        </div>

        <div v-else class="agenttokens-dashboard-state text-caption text-disabled">
          暂无数据
        </div>
      </VCardText>

      <VDivider v-if="allowRefresh" />
      <VCardActions v-if="allowRefresh" class="agenttokens-dashboard-card__actions">
        <span class="text-caption text-disabled">
          {{ lastRefreshedTime ? `更新于 ${lastRefreshedTime}` : '等待更新' }}
        </span>
        <VSpacer />
        <VBtn icon variant="text" size="small" :loading="loading" @click="loadStatus">
          <VIcon icon="mdi-refresh" size="18" />
        </VBtn>
      </VCardActions>
    </VCard>
  </div>
</template>

<style scoped>
.agenttokens-dashboard-widget {
  block-size: 100%;
  inline-size: 100%;
}

.agenttokens-dashboard-card {
  block-size: 100%;
  min-block-size: 280px;
  display: flex;
  flex-direction: column;
}

.agenttokens-dashboard-card__header {
  padding-block-end: 8px;
}

.agenttokens-dashboard-card__title {
  font-size: 1rem;
  line-height: 1.35;
}

.agenttokens-dashboard-card__body {
  flex: 1 1 auto;
  padding-block-start: 8px;
}

.agenttokens-dashboard-card__actions {
  min-block-size: 40px;
  padding: 4px 12px;
}

.agenttokens-dashboard-state {
  min-block-size: 144px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.agenttokens-dashboard-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agenttokens-dashboard-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 14px;
}

.agenttokens-dashboard-summary__percent {
  font-size: 0.95rem;
  font-weight: 700;
}

.agenttokens-dashboard-summary__body {
  min-inline-size: 0;
}

.agenttokens-dashboard-summary__count {
  margin-block: 2px 8px;
  font-size: 1.7rem;
  font-weight: 700;
  line-height: 1.1;
}

.agenttokens-dashboard-summary__count span {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 1rem;
  font-weight: 600;
}

.agenttokens-dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.agenttokens-dashboard-metric {
  min-block-size: 54px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 6px;
  padding: 8px 10px;
  background: rgba(var(--v-theme-surface-variant), 0.22);
}

.agenttokens-dashboard-metric span {
  display: block;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.75rem;
  line-height: 1.2;
}

.agenttokens-dashboard-metric strong {
  display: block;
  margin-block-start: 4px;
  font-size: 0.95rem;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.agenttokens-dashboard-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.agenttokens-dashboard-provider {
  min-block-size: 34px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.agenttokens-dashboard-provider__main {
  min-inline-size: 0;
}

.agenttokens-dashboard-provider__name,
.agenttokens-dashboard-provider__model {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agenttokens-dashboard-provider__name {
  font-size: 0.85rem;
  font-weight: 600;
  line-height: 1.2;
}

.agenttokens-dashboard-provider__model {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.75rem;
  line-height: 1.2;
}

.agenttokens-dashboard-provider__tokens {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.agenttokens-dashboard-empty {
  min-block-size: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.82rem;
}

@media (max-width: 480px) {
  .agenttokens-dashboard-card {
    min-block-size: 300px;
  }

  .agenttokens-dashboard-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
