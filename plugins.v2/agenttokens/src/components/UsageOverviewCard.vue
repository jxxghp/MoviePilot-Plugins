<script setup>
import { computed } from 'vue'
import { formatTokens } from '../provider'

const props = defineProps({
  summary: {
    type: Object,
    default: () => ({}),
  },
})

// 读取限量模型用量，兼容旧接口缺少 limited_used 的情况。
const totalUsed = computed(() => Number(props.summary.limited_used ?? props.summary.total_used ?? 0))
const totalLimit = computed(() => Number(props.summary.total_limit || 0))
const usagePercent = computed(() => {
  if (props.summary.limited_usage_percent !== undefined) {
    return Number(props.summary.limited_usage_percent || 0)
  }
  if (totalLimit.value <= 0) return 0
  return Math.min((totalUsed.value * 100) / totalLimit.value, 100)
})
const usagePercentText = computed(() => `${Math.round(usagePercent.value)}%`)
const remainingTokens = computed(() => {
  if (props.summary.limited_remaining !== undefined) return props.summary.limited_remaining
  if (totalLimit.value <= 0) return null
  return Math.max(totalLimit.value - totalUsed.value, 0)
})
const progressColor = computed(() => {
  if (totalLimit.value <= 0) return 'primary'
  if (usagePercent.value >= 90) return 'error'
  if (usagePercent.value >= 70) return 'warning'
  return 'success'
})
</script>

<template>
  <VSheet border rounded class="usage-overview-card">
    <div class="usage-overview-card__content">
      <div class="usage-overview-card__chart">
        <VProgressCircular
          :model-value="usagePercent"
          :color="progressColor"
          bg-color="surface-variant"
          :size="132"
          :width="12"
        >
          <div class="usage-overview-card__percent">{{ totalLimit > 0 ? usagePercentText : '不限' }}</div>
        </VProgressCircular>
      </div>

      <div class="usage-overview-card__body">
        <div class="text-caption text-medium-emphasis">限量模型使用进度</div>
        <div class="usage-overview-card__headline">
          {{ formatTokens(totalUsed) }}
          <span class="text-medium-emphasis">/ {{ totalLimit > 0 ? formatTokens(totalLimit) : '不限' }}</span>
        </div>
        <VProgressLinear
          :model-value="usagePercent"
          :color="progressColor"
          height="8"
          rounded
          class="my-4"
        />
        <div class="usage-overview-card__meta">
          <span>剩余 {{ remainingTokens === null ? '不限' : formatTokens(remainingTokens) }}</span>
          <span>可用 {{ summary.available_count || 0 }} / {{ summary.enabled_count || 0 }}</span>
        </div>
      </div>
    </div>
  </VSheet>
</template>

<style scoped>
.usage-overview-card {
  block-size: 100%;
  padding: 20px;
}

.usage-overview-card__content {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 20px;
}

.usage-overview-card__chart {
  display: flex;
  justify-content: center;
}

.usage-overview-card__percent {
  font-size: 1.35rem;
  font-weight: 700;
}

.usage-overview-card__headline {
  margin-block-start: 4px;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.usage-overview-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.875rem;
}

@media (max-width: 600px) {
  .usage-overview-card {
    padding: 16px;
  }

  .usage-overview-card__content {
    grid-template-columns: 1fr;
    text-align: center;
  }

  .usage-overview-card__meta {
    justify-content: center;
  }
}
</style>
