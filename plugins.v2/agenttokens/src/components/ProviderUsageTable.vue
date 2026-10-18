<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { formatTokens } from '../provider'

defineProps({
  providerRows: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['reset'])
const now = ref(Date.now())
let clockTimer

// 使用本地时钟更新冷却倒计时；卸载时清理计时器。
onMounted(() => {
  clockTimer = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => clearInterval(clockTimer))

// 到期后立即显示可用状态，无需等待下一次拉取状态。
function cooldownRemaining(row) {
  if (!row.failure_cooldown_enabled) return 0
  return Math.max(0, Math.ceil(Number(row.usage?.cooldown_until || 0) - now.value / 1000))
}

// 根据供应商状态返回 Vuetify 颜色。
function rowStatusColor(row) {
  if (!row.enabled) return 'default'
  if (row.usage?.exhausted) return 'error'
  if (cooldownRemaining(row)) return 'warning'
  if (!row.api_key || !row.base_url || !row.model) return 'warning'
  return 'success'
}

// 根据供应商状态返回短标签。
function rowStatusText(row) {
  if (!row.enabled) return '停用'
  if (row.usage?.exhausted) return '耗尽'
  if (cooldownRemaining(row)) return `冷却 ${cooldownRemaining(row)} 秒`
  if (!row.api_key || !row.base_url || !row.model) return '缺配置'
  return '可用'
}
</script>

<template>
  <VSheet border rounded class="provider-table-shell">
    <VTable density="comfortable">
      <thead>
        <tr>
          <th>优先级</th>
          <th>名称</th>
          <th>模型</th>
          <th>已用</th>
          <th>余量</th>
          <th>进度</th>
          <th>状态</th>
          <th class="text-right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in providerRows" :key="row.id || index">
          <td>{{ row.priority }}</td>
          <td>{{ row.name }}</td>
          <td>{{ row.model }}</td>
          <td>{{ formatTokens(row.usage?.total_tokens) }}</td>
          <td>
            {{ row.usage?.remaining_tokens === null ? '不限' : formatTokens(row.usage?.remaining_tokens) }}
          </td>
          <td class="progress-cell">
            <VProgressLinear
              :model-value="row.usage?.usage_percent || 0"
              :color="rowStatusColor(row)"
              height="8"
              rounded
            />
          </td>
          <td class="status-cell">
            <VChip size="small" :color="rowStatusColor(row)" variant="tonal">{{ rowStatusText(row) }}</VChip>
            <div v-if="cooldownRemaining(row)" class="text-caption text-medium-emphasis mt-1">
              {{ row.usage?.cooldown_reason }}
            </div>
            <div v-else-if="row.failure_cooldown_enabled" class="text-caption text-medium-emphasis mt-1">
              连续失败 {{ row.usage?.consecutive_failures || 0 }} / {{ row.failure_threshold }}
            </div>
          </td>
          <td class="text-right">
            <VBtn icon="mdi-backup-restore" size="small" variant="text" @click="emit('reset', row.id, index)" />
          </td>
        </tr>
        <tr v-if="!providerRows.length">
          <td colspan="8" class="text-center text-medium-emphasis py-8">暂无供应商</td>
        </tr>
      </tbody>
    </VTable>
  </VSheet>
</template>

<style scoped>
.provider-table-shell {
  overflow-x: auto;
}

.provider-table-shell :deep(table) {
  min-width: 760px;
}

.status-cell {
  min-width: 140px;
  max-width: 280px;
  overflow-wrap: anywhere;
}

.progress-cell {
  min-width: 140px;
}
</style>
