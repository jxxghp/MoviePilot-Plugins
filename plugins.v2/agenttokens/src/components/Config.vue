<script setup>
import { onMounted, ref } from 'vue'

const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['save', 'close', 'switch'])

const localConfig = ref({ enabled: false, show_sidebar_nav: true, providers: [] })
const showEditor = ref(false)
const editorIndex = ref(-1)
const editedProvider = ref(createProvider())

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

// 生成深拷贝配置，避免直接修改父组件传入对象。
function cloneConfig(config) {
  return JSON.parse(JSON.stringify(config || { enabled: false, show_sidebar_nav: true, providers: [] }))
}

// 格式化 token 数字。
function formatTokens(value) {
  const numberValue = Number(value || 0)
  return Number.isFinite(numberValue) ? numberValue.toLocaleString() : '0'
}

// 打开新增供应商弹窗。
function addProvider() {
  const nextPriority = Math.max(0, ...(localConfig.value.providers || []).map(item => Number(item.priority || 0))) + 1
  editedProvider.value = { ...createProvider(), priority: nextPriority }
  editorIndex.value = -1
  showEditor.value = true
}

// 打开编辑供应商弹窗。
function editProvider(index) {
  editedProvider.value = { ...localConfig.value.providers[index] }
  editorIndex.value = index
  showEditor.value = true
}

// 将弹窗中的供应商写回本地配置。
function commitProvider() {
  const providers = [...(localConfig.value.providers || [])]
  const provider = {
    ...editedProvider.value,
    token_limit: Number(editedProvider.value.token_limit || 0),
    used_tokens: Number(editedProvider.value.used_tokens || 0),
    priority: Number(editedProvider.value.priority || providers.length + 1),
  }
  if (editorIndex.value >= 0) {
    providers.splice(editorIndex.value, 1, provider)
  } else {
    providers.push(provider)
  }
  localConfig.value.providers = providers
  showEditor.value = false
}

// 移除一个供应商配置。
function removeProvider(index) {
  const providers = [...(localConfig.value.providers || [])]
  providers.splice(index, 1)
  localConfig.value.providers = providers
}

// 通知宿主保存 Vue 配置。
function saveConfig() {
  emit('save', cloneConfig(localConfig.value))
}

onMounted(() => {
  localConfig.value = cloneConfig(props.initialConfig)
  if (localConfig.value.show_sidebar_nav === undefined) {
    localConfig.value.show_sidebar_nav = true
  }
  if (!Array.isArray(localConfig.value.providers)) {
    localConfig.value.providers = []
  }
})
</script>

<template>
  <div class="agenttokens-config">
    <VToolbar density="comfortable" color="transparent">
      <VToolbarTitle>Agent Tokens 配置</VToolbarTitle>
      <VSpacer />
      <VBtn icon="mdi-close" variant="text" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <div class="pa-4">
      <div class="d-flex align-center mb-4 gap-2 flex-wrap">
        <VSwitch v-model="localConfig.enabled" color="primary" hide-details inset label="启用插件" />
        <VSwitch v-model="localConfig.show_sidebar_nav" color="primary" hide-details inset label="显示侧边栏入口" />
        <VSpacer />
        <VBtn prepend-icon="mdi-database-eye" variant="tonal" @click="emit('switch')">用量</VBtn>
        <VBtn prepend-icon="mdi-plus" color="primary" variant="tonal" @click="addProvider">新增</VBtn>
      </div>

      <VSheet border rounded>
        <VTable density="comfortable">
          <thead>
            <tr>
              <th>启用</th>
              <th>优先级</th>
              <th>名称</th>
              <th>类型</th>
              <th>模型</th>
              <th>额度</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in localConfig.providers" :key="row.id || index">
              <td>
                <VSwitch v-model="row.enabled" color="primary" hide-details density="compact" />
              </td>
              <td>{{ row.priority }}</td>
              <td>{{ row.name }}</td>
              <td>{{ row.provider }}</td>
              <td>{{ row.model }}</td>
              <td>{{ row.token_limit > 0 ? formatTokens(row.token_limit) : '不限' }}</td>
              <td class="text-right">
                <VBtn icon="mdi-pencil" size="small" variant="text" @click="editProvider(index)" />
                <VBtn icon="mdi-delete" size="small" variant="text" color="error" @click="removeProvider(index)" />
              </td>
            </tr>
            <tr v-if="!localConfig.providers.length">
              <td colspan="7" class="text-center text-medium-emphasis py-8">暂无供应商</td>
            </tr>
          </tbody>
        </VTable>
      </VSheet>
    </div>

    <VDivider />
    <div class="pa-4 d-flex justify-end">
      <VBtn prepend-icon="mdi-content-save" color="primary" @click="saveConfig">保存</VBtn>
    </div>

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
              <VSelect v-model="editedProvider.provider" :items="providerTypeOptions" label="类型" variant="outlined" />
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
</style>
