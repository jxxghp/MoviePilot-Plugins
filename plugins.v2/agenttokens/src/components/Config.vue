<script setup>
import { onMounted, ref } from 'vue'
import AgentTokensManager from './AgentTokensManager.vue'
import { cloneConfig } from '../provider'

const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['save', 'close'])

const localConfig = ref({ enabled: false, show_sidebar_nav: true, providers: [] })

// 重置本地配置中的单个供应商用量。
function resetUsage(providerId, index) {
  const providers = localConfig.value.providers || []
  const providerIndex = providers.findIndex(provider => provider.id && provider.id === providerId)
  const targetIndex = providerIndex >= 0 ? providerIndex : index
  if (!providers[targetIndex]) return
  providers[targetIndex].used_tokens = 0
}

// 重置本地配置中的全部供应商用量。
function resetAllUsage() {
  ;(localConfig.value.providers || []).forEach(provider => {
    provider.used_tokens = 0
  })
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
      <div class="text-h6 ms-3">Agent Tokens 配置</div>
      <VSpacer />
      <VBtn icon="mdi-content-save" variant="text" color="primary" @click="saveConfig" />
      <VBtn icon="mdi-close" variant="text" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <AgentTokensManager
      :config="localConfig"
      hide-title
      @save="saveConfig"
      @reset-usage="resetUsage"
      @reset-all-usage="resetAllUsage"
    />
  </div>
</template>
