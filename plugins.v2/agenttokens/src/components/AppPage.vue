<script setup>
import { computed, onMounted, ref } from 'vue'

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
const activeTab = ref('usage')
const showEditor = ref(false)
const editorIndex = ref(-1)
const editedProvider = ref(createProvider())
const status = ref({
  config: { enabled: false, providers: [] },
  providers: [],
  summary: {},
})

// 构造 API 基础路径。
const pluginBase = computed(() => `plugin/${props.pluginId || 'AgentTokens'}`)
const config = computed(() => status.value.config || { enabled: false, providers: [] })
const providerRows = computed(() => status.value.providers || [])
const summary = computed(() => status.value.summary || {})

const providerTypeOptions = [
  { title: 'OpenAI Compatible', value: 'openai' },
  { title: 'DeepSeek', value: 'deepseek' },
  { title: 'Google Gemini', value: 'google' },
  { title: 'Anthropic Compatible', value: 'anthropic' },
  { title: 'ChatGPT', value: 'chatgpt' },
]

// 构建一个新的供应商默认配置。
function createProvider() {
  return {
    id: '',
    enabled: true,
    name: '',
    provider: 'openai',
    base_url: '',
    api_key: '',
    model: '',
    token_limit: 0,
    used_tokens: 0,
    priority: 1,
  }
}

// 兼容 MoviePilot API 包装器和原始响应两种返回形态。
function unwrapResponse(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

// 格式化 token 数字，保持表格紧凑可读。
function formatTokens(value) {
  const numberValue = Number(value || 0)
  return Number.isFinite(numberValue) ? numberValue.toLocaleString() : '0'
}

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

// 打开新增供应商弹窗。
function addProvider() {
  const nextPriority = Math.max(0, ...(config.value.providers || []).map(item => Number(item.priority || 0))) + 1
  editedProvider.value = { ...createProvider(), priority: nextPriority }
  editorIndex.value = -1
  showEditor.value = true
}

// 打开编辑供应商弹窗。
function editProvider(index) {
  editedProvider.value = { ...config.value.providers[index] }
  editorIndex.value = index
  showEditor.value = true
}

// 将弹窗中的供应商写回配置列表。
function commitProvider() {
  const providers = [...(config.value.providers || [])]
  const normalized = {
    ...editedProvider.value,
    token_limit: Number(editedProvider.value.token_limit || 0),
    used_tokens: Number(editedProvider.value.used_tokens || 0),
    priority: Number(editedProvider.value.priority || providers.length + 1),
  }
  if (editorIndex.value >= 0) {
    providers.splice(editorIndex.value, 1, normalized)
  } else {
    providers.push(normalized)
  }
  status.value.config = { ...config.value, providers }
  showEditor.value = false
}

// 从配置列表中移除一个供应商。
function removeProvider(index) {
  const providers = [...(config.value.providers || [])]
  providers.splice(index, 1)
  status.value.config = { ...config.value, providers }
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
  <div class="agenttokens-page pa-4">
    <div v-if="!hideTitle" class="d-flex align-center gap-2 mb-4 flex-nowrap">
      <h2 class="text-2xl font-bold leading-7 text-gray-100 truncate sm:text-3xl sm:leading-9">
        <span class="text-moviepilot">Agent Tokens 管理</span>
      </h2>
      <VSpacer />
      <VBtn icon="mdi-refresh" variant="text" :loading="loading" @click="loadStatus" />
      <VBtn icon="mdi-content-save" variant="text" color="primary" :loading="saving" @click="saveConfig" />
    </div>

    <VAlert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</VAlert>

    <VRow class="mb-4">
      <VCol cols="12" sm="auto">
        <VSwitch v-if="status.config" v-model="status.config.enabled" color="primary" hide-details inset label="启用插件" />
      </VCol>
      <VCol cols="12" sm="auto">
        <VSwitch v-if="status.config" v-model="status.config.show_sidebar_nav" color="primary" hide-details inset label="侧边栏入口" />
      </VCol>
    </VRow>

    <VRow class="mb-2">
      <VCol cols="12" sm="4">
        <VSheet border rounded class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">可用供应商</div>
          <div class="text-h5">{{ summary.available_count || 0 }} / {{ summary.enabled_count || 0 }}</div>
        </VSheet>
      </VCol>
      <VCol cols="12" sm="4">
        <VSheet border rounded class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">累计使用</div>
          <div class="text-h5">{{ formatTokens(summary.total_used) }}</div>
        </VSheet>
      </VCol>
      <VCol cols="12" sm="4">
        <VSheet border rounded class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">总额度</div>
          <div class="text-h5">{{ formatTokens(summary.total_limit) }}</div>
        </VSheet>
      </VCol>
    </VRow>

    <VTabs v-model="activeTab" density="comfortable" class="mb-3">
      <VTab value="usage">用量</VTab>
      <VTab value="config">配置</VTab>
    </VTabs>

    <VWindow v-model="activeTab">
      <VWindowItem value="usage">
        <VSheet border rounded>
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
              <tr v-for="row in providerRows" :key="row.id">
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
                  <VBtn icon="mdi-backup-restore" size="small" variant="text" @click="resetUsage(row.id)" />
                </td>
              </tr>
              <tr v-if="!providerRows.length">
                <td colspan="8" class="text-center text-medium-emphasis py-8">暂无供应商</td>
              </tr>
            </tbody>
          </VTable>
        </VSheet>
      </VWindowItem>

      <VWindowItem value="config">
        <div class="d-flex justify-end mb-3 gap-2">
          <VBtn prepend-icon="mdi-plus" color="primary" variant="tonal" @click="addProvider">新增</VBtn>
          <VBtn prepend-icon="mdi-backup-restore" color="warning" variant="tonal" @click="resetAllUsage">重置用量</VBtn>
        </div>
        <VSheet border rounded>
          <VTable density="comfortable">
            <thead>
              <tr>
                <th>启用</th>
                <th>优先级</th>
                <th>名称</th>
                <th>类型</th>
                <th>地址</th>
                <th>Key</th>
                <th>模型</th>
                <th>额度</th>
                <th class="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in config.providers" :key="row.id || index">
                <td>
                  <VSwitch v-model="row.enabled" color="primary" hide-details density="compact" />
                </td>
                <td>{{ row.priority }}</td>
                <td>{{ row.name }}</td>
                <td>{{ row.provider }}</td>
                <td class="truncate-cell">{{ row.base_url }}</td>
                <td>{{ providerRows[index]?.masked_api_key || '****' }}</td>
                <td>{{ row.model }}</td>
                <td>{{ row.token_limit > 0 ? formatTokens(row.token_limit) : '不限' }}</td>
                <td class="text-right">
                  <VBtn icon="mdi-pencil" size="small" variant="text" @click="editProvider(index)" />
                  <VBtn icon="mdi-delete" size="small" variant="text" color="error" @click="removeProvider(index)" />
                </td>
              </tr>
              <tr v-if="!config.providers?.length">
                <td colspan="9" class="text-center text-medium-emphasis py-8">暂无供应商</td>
              </tr>
            </tbody>
          </VTable>
        </VSheet>
      </VWindowItem>
    </VWindow>

    <VDialog v-model="showEditor" max-width="760">
      <VCard>
        <VCardTitle>{{ editorIndex >= 0 ? '编辑供应商' : '新增供应商' }}</VCardTitle>
        <VCardText>
          <VRow>
            <VCol cols="12" md="8">
              <VTextField v-model="editedProvider.name" label="名称" variant="outlined" density="comfortable" />
            </VCol>
            <VCol cols="12" md="4">
              <VTextField v-model.number="editedProvider.priority" label="优先级" type="number" variant="outlined" />
            </VCol>
            <VCol cols="12" md="6">
              <VSelect
                v-model="editedProvider.provider"
                :items="providerTypeOptions"
                label="类型"
                variant="outlined"
              />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model="editedProvider.model" label="模型" variant="outlined" />
            </VCol>
            <VCol cols="12">
              <VTextField v-model="editedProvider.base_url" label="API 地址" variant="outlined" />
            </VCol>
            <VCol cols="12">
              <VTextField v-model="editedProvider.api_key" label="API Key" type="password" variant="outlined" />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model.number="editedProvider.token_limit" label="Token 额度" type="number" variant="outlined" />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model.number="editedProvider.used_tokens" label="初始已用" type="number" variant="outlined" />
            </VCol>
          </VRow>
        </VCardText>
        <VCardActions>
          <VSpacer />
          <VBtn variant="text" @click="showEditor = false">取消</VBtn>
          <VBtn color="primary" @click="commitProvider">确定</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.gap-2 {
  gap: 8px;
}

.progress-cell {
  min-width: 140px;
}

.truncate-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
