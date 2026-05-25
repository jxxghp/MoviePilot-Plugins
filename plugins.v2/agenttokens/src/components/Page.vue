<script setup>
import AppPage from './AppPage.vue'

defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
})
const emit = defineEmits(['close'])
</script>

<template>
  <VCard>
    <VCardTitle class="d-flex justify-space-between align-center">
      <span>Agent Tokens 配置</span>
      <VBtn icon="mdi-close" variant="text" @click="emit('close')" />
    </VCardTitle>
    <VCardText class="pa-0">
      <AppPage :api="api" plugin-id="AgentTokens" />
    </VCardText>
  </VCard>
</template>
