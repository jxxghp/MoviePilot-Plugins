<script setup>
import { formatTokens } from '../provider'

const props = defineProps({
  providers: {
    type: Array,
    default: () => [],
  },
  providerRows: {
    type: Array,
    default: () => [],
  },
  showCredentials: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['edit', 'remove'])

// 获取管理页服务端返回的脱敏 Key。
function getMaskedApiKey(index) {
  return props.providerRows[index]?.masked_api_key || '****'
}
</script>

<template>
  <VSheet border rounded class="provider-table-shell">
    <VTable density="comfortable">
      <thead>
        <tr>
          <th>启用</th>
          <th>优先级</th>
          <th>名称</th>
          <th>类型</th>
          <th v-if="showCredentials">地址</th>
          <th v-if="showCredentials">Key</th>
          <th>模型</th>
          <th>额度</th>
          <th class="text-right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in providers" :key="row.id || index">
          <td>
            <VSwitch v-model="row.enabled" color="primary" hide-details density="compact" />
          </td>
          <td>{{ row.priority }}</td>
          <td>{{ row.name }}</td>
          <td>{{ row.provider }}</td>
          <td v-if="showCredentials" class="truncate-cell">{{ row.base_url }}</td>
          <td v-if="showCredentials">{{ getMaskedApiKey(index) }}</td>
          <td>{{ row.model }}</td>
          <td>{{ row.token_limit > 0 ? formatTokens(row.token_limit) : '不限' }}</td>
          <td class="text-right">
            <VBtn icon="mdi-pencil" size="small" variant="text" @click="emit('edit', index)" />
            <VBtn icon="mdi-delete" size="small" variant="text" color="error" @click="emit('remove', index)" />
          </td>
        </tr>
        <tr v-if="!providers.length">
          <td :colspan="showCredentials ? 9 : 7" class="text-center text-medium-emphasis py-8">暂无供应商</td>
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
  min-width: 880px;
}

.truncate-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
