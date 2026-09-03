<script setup>
import { formatTokens } from '../provider'

defineProps({
  providerRows: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['reset'])

// 根据供应商状态返回 Vuetify 颜色。
function rowStatusColor(row) {
  if (!row.enabled) return 'default'
  if (row.usage?.exhausted) return 'error'
  if (!row.api_key || !row.base_url || !row.model) return 'warning'
  return 'success'
}

// 根据供应商状态返回短标签。
function rowStatusText(row) {
  if (!row.enabled) return '停用'
  if (row.usage?.exhausted) return '耗尽'
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
          <td>
            <VChip size="small" :color="rowStatusColor(row)" variant="tonal">{{ rowStatusText(row) }}</VChip>
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

.progress-cell {
  min-width: 140px;
}
</style>
