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
const widgetRef = ref(null)
const widgetSize = ref({ inline: 0, block: 0 })
const status = ref({ providers: [], summary: {} })
let timer = null
let resizeObserver = null

const attrs = computed(() => props.config?.attrs || {})
const summary = computed(() => status.value.summary || {})
const providers = computed(() => status.value.providers || [])
// 总调用量用于累计展示，包含限量和不限量模型。
const totalUsed = computed(() => Number(summary.value.total_used || 0))
// 限量调用量只用于配额进度，避免不限量模型推高使用率。
const limitedUsed = computed(() => Number(summary.value.limited_used ?? summary.value.total_used ?? 0))
// 不限量调用量单独展示为调用统计。
const unlimitedUsed = computed(() => Number(summary.value.unlimited_used || 0))
const totalLimit = computed(() => Number(summary.value.total_limit || 0))
const remainingTokens = computed(() => {
  if (summary.value.limited_remaining !== undefined) return summary.value.limited_remaining
  if (totalLimit.value <= 0) return null
  return Math.max(totalLimit.value - limitedUsed.value, 0)
})
const usagePercent = computed(() => {
  if (summary.value.limited_usage_percent !== undefined) {
    return Number(summary.value.limited_usage_percent || 0)
  }
  if (totalLimit.value <= 0) return 0
  return Math.min((limitedUsed.value * 100) / totalLimit.value, 100)
})
const usagePercentText = computed(() => (totalLimit.value > 0 ? `${Math.round(usagePercent.value)}%` : '不限'))
const progressColor = computed(() => {
  if (totalLimit.value <= 0) return 'primary'
  if (usagePercent.value >= 90) return 'error'
  if (usagePercent.value >= 70) return 'warning'
  return 'success'
})
const isCompact = computed(() => (
  (widgetSize.value.inline > 0 && widgetSize.value.inline < 340) ||
  (widgetSize.value.block > 0 && widgetSize.value.block < 300)
))
const isMini = computed(() => (
  (widgetSize.value.inline > 0 && widgetSize.value.inline < 260) ||
  (widgetSize.value.block > 0 && widgetSize.value.block < 230)
))
const gaugeSize = computed(() => {
  if (isMini.value) return 52
  if (isCompact.value) return 68
  return 84
})
const gaugeWidth = computed(() => {
  if (isMini.value) return 5
  if (isCompact.value) return 6
  return 8
})
const showMetrics = computed(() => !isMini.value)
const visibleProviderLimit = computed(() => {
  if (isMini.value) return 0
  if (
    (widgetSize.value.inline > 0 && widgetSize.value.inline < 320) ||
    (widgetSize.value.block > 0 && widgetSize.value.block < 310)
  ) {
    return 1
  }
  if (
    (widgetSize.value.inline > 0 && widgetSize.value.inline < 380) ||
    (widgetSize.value.block > 0 && widgetSize.value.block < 360)
  ) {
    return 2
  }
  return 3
})
const visibleProviders = computed(() => providers.value.slice(0, visibleProviderLimit.value))
// 兼容宿主传入的数字或字符串刷新间隔。
const refreshSeconds = computed(() => {
  const seconds = Number(props.refreshInterval || attrs.value.refresh || 0)
  return Number.isFinite(seconds) ? seconds : 0
})
const cardTitle = computed(() => attrs.value.title || 'Agent Tokens 管理')
const cardSubtitle = computed(() => attrs.value.subtitle || 'LLM 配额使用情况')
const cardFlat = computed(() => attrs.value.border === false)
const widgetClasses = computed(() => ({
  'agenttokens-dashboard-widget--compact': isCompact.value,
  'agenttokens-dashboard-widget--mini': isMini.value,
}))
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

// 记录宿主 GridStack 分配给组件的实际尺寸，用于切换紧凑布局。
function observeWidgetSize() {
  if (!widgetRef.value || typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(entries => {
    const entry = entries[0]
    if (!entry) return
    widgetSize.value = {
      inline: entry.contentRect.width,
      block: entry.contentRect.height,
    }
  })
  resizeObserver.observe(widgetRef.value)
}

// 停止监听组件尺寸，避免仪表板卸载后继续触发布局计算。
function stopWidgetSizeObserver() {
  if (!resizeObserver) return
  resizeObserver.disconnect()
  resizeObserver = null
}

onMounted(() => {
  observeWidgetSize()
  loadStatus()
  startRefreshTimer()
})

onUnmounted(() => {
  stopWidgetSizeObserver()
  stopRefreshTimer()
})
</script>

<template>
  <div ref="widgetRef" class="agenttokens-dashboard-widget" :class="widgetClasses">
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
              bg-color="surface"
              :size="gaugeSize"
              :width="gaugeWidth"
            >
              <span class="agenttokens-dashboard-summary__percent">{{ usagePercentText }}</span>
            </VProgressCircular>

            <div class="agenttokens-dashboard-summary__body">
              <div class="text-caption text-medium-emphasis">限量模型使用进度</div>
              <div class="agenttokens-dashboard-summary__count">
                {{ formatTokens(limitedUsed) }}
                <span>/ {{ totalLimit > 0 ? formatTokens(totalLimit) : '不限' }}</span>
              </div>
              <VProgressLinear
                :model-value="usagePercent"
                :color="progressColor"
                height="6"
                rounded
              />
            </div>
          </div>

          <div v-if="showMetrics" class="agenttokens-dashboard-metrics">
            <div class="agenttokens-dashboard-metric">
              <span>累计</span>
              <strong>{{ formatTokens(totalUsed) }}</strong>
            </div>
            <div class="agenttokens-dashboard-metric">
              <span>不限量</span>
              <strong>{{ formatTokens(unlimitedUsed) }}</strong>
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

          <div v-else-if="!providers.length" class="agenttokens-dashboard-empty">
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
        <span v-if="!isMini" class="text-caption text-disabled">
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
  color: rgb(var(--v-theme-on-surface));
  inline-size: 100%;

  --agenttokens-divider-color: rgba(var(--v-theme-on-surface), 0.08);
  --agenttokens-muted-color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  --agenttokens-soft-surface: rgba(var(--v-theme-on-surface), 0.035);
  --agenttokens-soft-surface-hover: rgba(var(--v-theme-on-surface), 0.055);
}

.agenttokens-dashboard-card {
  block-size: 100%;
  color: rgb(var(--v-theme-on-surface));
  display: flex;
  flex-direction: column;
  min-block-size: 0;
  overflow: hidden;
}

.agenttokens-dashboard-card__header {
  flex: 0 0 auto;
  padding-block-end: 8px;
}

.agenttokens-dashboard-card__header :deep(.v-card-item__content) {
  min-inline-size: 0;
}

.agenttokens-dashboard-card__title {
  font-size: 1rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agenttokens-dashboard-card__body {
  flex: 1 1 auto;
  min-block-size: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding-block-start: 8px;
}

.agenttokens-dashboard-card__actions {
  flex: 0 0 auto;
  min-block-size: 40px;
  padding: 4px 12px;
}

.agenttokens-dashboard-state {
  block-size: 100%;
  min-block-size: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.agenttokens-dashboard-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-block-size: 0;
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
  color: var(--agenttokens-muted-color);
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
  border: 1px solid var(--agenttokens-divider-color);
  border-radius: 6px;
  background: var(--agenttokens-soft-surface);
  padding: 8px 10px;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.agenttokens-dashboard-metric:hover {
  background: var(--agenttokens-soft-surface-hover);
}

.agenttokens-dashboard-metric span {
  display: block;
  color: var(--agenttokens-muted-color);
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
  min-block-size: 0;
}

.agenttokens-dashboard-provider {
  min-block-size: 34px;
  border-radius: 6px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding-inline: 2px;
}

.agenttokens-dashboard-provider:hover {
  background: var(--agenttokens-soft-surface);
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
  color: var(--agenttokens-muted-color);
  font-size: 0.75rem;
  line-height: 1.2;
}

.agenttokens-dashboard-provider__tokens {
  color: var(--agenttokens-muted-color);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.agenttokens-dashboard-empty {
  min-block-size: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--agenttokens-muted-color);
  font-size: 0.82rem;
}

.agenttokens-dashboard-widget :deep(.v-progress-circular__underlay) {
  stroke: rgba(var(--v-theme-on-surface), 0.12);
}

.agenttokens-dashboard-widget--compact .agenttokens-dashboard-card__body {
  padding-block: 6px 10px;
}

.agenttokens-dashboard-widget--compact .agenttokens-dashboard-content {
  gap: 8px;
}

.agenttokens-dashboard-widget--compact .agenttokens-dashboard-summary {
  gap: 10px;
}

.agenttokens-dashboard-widget--compact .agenttokens-dashboard-summary__count {
  margin-block-end: 6px;
  font-size: 1.35rem;
}

.agenttokens-dashboard-widget--compact .agenttokens-dashboard-metric {
  min-block-size: 46px;
  padding: 6px 8px;
}

.agenttokens-dashboard-widget--compact .agenttokens-dashboard-provider {
  min-block-size: 30px;
}

.agenttokens-dashboard-widget--mini .agenttokens-dashboard-card__header {
  padding-block: 10px 4px;
}

.agenttokens-dashboard-widget--mini .agenttokens-dashboard-card__header :deep(.v-card-subtitle) {
  display: none;
}

.agenttokens-dashboard-widget--mini .agenttokens-dashboard-summary {
  grid-template-columns: auto minmax(0, 1fr);
}

.agenttokens-dashboard-widget--mini .agenttokens-dashboard-summary__count {
  margin-block: 0 4px;
  font-size: 1.15rem;
}

.agenttokens-dashboard-widget--mini .agenttokens-dashboard-card__actions {
  justify-content: flex-end;
  min-block-size: 34px;
}

@media (max-width: 480px) {
  .agenttokens-dashboard-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
