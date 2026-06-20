<script setup>
import { computed, ref } from 'vue'
import ProviderConfigTable from './ProviderConfigTable.vue'
import ProviderEditorDialog from './ProviderEditorDialog.vue'
import ProviderUsageTable from './ProviderUsageTable.vue'
import UsageOverviewCard from './UsageOverviewCard.vue'
import {
  buildProviderRows,
  buildProviderSummary,
  createProvider,
  formatTokens,
  getNextProviderPriority,
  normalizeProvider,
} from '../provider'

const props = defineProps({
  config: {
    type: Object,
    default: () => ({ enabled: false, show_sidebar_nav: true, providers: [] }),
  },
  providerRows: {
    type: Array,
    default: () => [],
  },
  summary: {
    type: Object,
    default: () => ({}),
  },
  error: {
    type: String,
    default: '',
  },
  loading: {
    type: Boolean,
    default: false,
  },
  saving: {
    type: Boolean,
    default: false,
  },
  hideTitle: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['refresh', 'save', 'reset-usage', 'reset-all-usage'])

const activeTab = ref('usage')
const showEditor = ref(false)
const editorIndex = ref(-1)
const editedProvider = ref(createProvider())

const configValue = computed(() => props.config || { enabled: false, show_sidebar_nav: true, providers: [] })
const providers = computed(() => (Array.isArray(configValue.value.providers) ? configValue.value.providers : []))
const displayProviderRows = computed(() => (
  props.providerRows.length ? props.providerRows : buildProviderRows(providers.value)
))
const displaySummary = computed(() => (
  Object.keys(props.summary || {}).length ? props.summary : buildProviderSummary(displayProviderRows.value)
))
const limitedUsed = computed(() => Number(displaySummary.value.limited_used ?? displaySummary.value.total_used ?? 0))
const unlimitedUsed = computed(() => Number(displaySummary.value.unlimited_used || 0))

// 打开新增供应商弹窗。
function addProvider() {
  editedProvider.value = { ...createProvider(), priority: getNextProviderPriority(providers.value) }
  editorIndex.value = -1
  showEditor.value = true
}

// 打开编辑供应商弹窗。
function editProvider(index) {
  editedProvider.value = { ...providers.value[index] }
  editorIndex.value = index
  showEditor.value = true
}

// 将弹窗中的供应商写回配置列表。
function commitProvider() {
  const nextProviders = [...providers.value]
  const normalized = normalizeProvider(editedProvider.value, nextProviders.length + 1)
  if (editorIndex.value >= 0) {
    nextProviders.splice(editorIndex.value, 1, normalized)
  } else {
    nextProviders.push(normalized)
  }
  configValue.value.providers = nextProviders
  showEditor.value = false
}

// 从配置列表中移除一个供应商。
function removeProvider(index) {
  const nextProviders = [...providers.value]
  nextProviders.splice(index, 1)
  configValue.value.providers = nextProviders
}

// 请求重置单个供应商用量。
function resetUsage(providerId, index) {
  emit('reset-usage', providerId, index)
}

// 请求重置全部供应商用量。
function resetAllUsage() {
  emit('reset-all-usage')
}
</script>

<template>
  <div class="agenttokens-page">
    <div v-if="!hideTitle" class="agenttokens-header">
      <h2 class="text-2xl font-bold leading-7 text-gray-100 truncate sm:text-3xl sm:leading-9">
        <span class="text-moviepilot">Agent Tokens 管理</span>
      </h2>
      <VSpacer />
      <VBtn icon="mdi-refresh" variant="text" :loading="loading" @click="emit('refresh')" />
      <VBtn icon="mdi-content-save" variant="text" color="primary" :loading="saving" @click="emit('save')" />
    </div>

    <VAlert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</VAlert>

    <VSheet border rounded class="agenttokens-control-panel">
      <div class="agenttokens-control-panel__switches">
        <VSwitch v-model="configValue.enabled" color="primary" hide-details inset label="启用插件" />
        <VSwitch v-model="configValue.show_sidebar_nav" color="primary" hide-details inset label="侧边栏入口" />
      </div>
    </VSheet>

    <div class="agenttokens-overview-grid">
      <UsageOverviewCard class="agenttokens-overview-card" :summary="displaySummary" />
      <VSheet border rounded class="agenttokens-stat-card">
        <VIcon icon="mdi-check-decagram-outline" color="success" />
        <div>
          <div class="text-caption text-medium-emphasis">可用供应商</div>
          <div class="agenttokens-stat-card__value">
            {{ displaySummary.available_count || 0 }} / {{ displaySummary.enabled_count || 0 }}
          </div>
        </div>
      </VSheet>
      <VSheet border rounded class="agenttokens-stat-card">
        <VIcon icon="mdi-chart-timeline-variant" color="primary" />
        <div>
          <div class="text-caption text-medium-emphasis">累计使用</div>
          <div class="agenttokens-stat-card__value">{{ formatTokens(displaySummary.total_used) }}</div>
          <div class="agenttokens-stat-card__hint">
            限量 {{ formatTokens(limitedUsed) }} / 不限量 {{ formatTokens(unlimitedUsed) }}
          </div>
        </div>
      </VSheet>
      <VSheet border rounded class="agenttokens-stat-card">
        <VIcon icon="mdi-database-outline" color="info" />
        <div>
          <div class="text-caption text-medium-emphasis">限量总额度</div>
          <div class="agenttokens-stat-card__value">
            {{ displaySummary.total_limit ? formatTokens(displaySummary.total_limit) : '不限' }}
          </div>
        </div>
      </VSheet>
    </div>

    <VSheet border rounded class="agenttokens-content-panel">
      <div class="agenttokens-tabs-row">
        <VTabs v-model="activeTab" density="comfortable">
          <VTab value="usage">用量</VTab>
          <VTab value="config">配置</VTab>
        </VTabs>
      </div>

      <VDivider />

      <VWindow v-model="activeTab" :touch="false" class="agenttokens-window">
        <VWindowItem value="usage">
          <ProviderUsageTable :provider-rows="displayProviderRows" @reset="resetUsage" />
        </VWindowItem>

        <VWindowItem value="config">
          <div class="agenttokens-table-actions">
            <VBtn prepend-icon="mdi-plus" color="primary" variant="tonal" @click="addProvider">新增</VBtn>
            <VBtn prepend-icon="mdi-backup-restore" color="warning" variant="tonal" @click="resetAllUsage">
              重置用量
            </VBtn>
          </div>
          <ProviderConfigTable
            :providers="providers"
            :provider-rows="displayProviderRows"
            show-credentials
            @edit="editProvider"
            @remove="removeProvider"
          />
        </VWindowItem>
      </VWindow>
    </VSheet>

    <ProviderEditorDialog
      v-model="showEditor"
      :provider="editedProvider"
      :editor-index="editorIndex"
      @commit="commitProvider"
    />
  </div>
</template>

<style scoped>
.agenttokens-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}

.agenttokens-header {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 8px;
}

.agenttokens-control-panel {
  display: flex;
  align-items: center;
  padding: 12px 16px;
}

.agenttokens-control-panel__switches {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
}

.agenttokens-overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(3, minmax(10rem, 1fr));
  gap: 12px;
}

.agenttokens-overview-card {
  min-block-size: 172px;
}

.agenttokens-stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  min-block-size: 104px;
  padding: 16px;
}

.agenttokens-stat-card__value {
  margin-block-start: 2px;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.agenttokens-stat-card__hint {
  margin-block-start: 2px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.78rem;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.agenttokens-content-panel {
  overflow: hidden;
}

.agenttokens-tabs-row {
  padding-inline: 8px;
}

.agenttokens-window {
  padding: 12px;
}

.agenttokens-table-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-block-end: 12px;
}

@media (max-width: 1100px) {
  .agenttokens-overview-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .agenttokens-overview-card {
    grid-column: 1 / -1;
  }
}

@media (max-width: 700px) {
  .agenttokens-page {
    padding: 12px;
  }

  .agenttokens-table-actions > :deep(.v-btn) {
    flex: 1 1 10rem;
  }

  .agenttokens-overview-grid {
    grid-template-columns: 1fr;
  }

  .agenttokens-stat-card {
    min-block-size: 88px;
  }
}
</style>
