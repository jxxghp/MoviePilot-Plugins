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
  <div class="agenttokens-page-wrapper">
    <VToolbar density="comfortable" color="transparent">
      <VToolbarTitle>Agent Tokens 数据</VToolbarTitle>
      <VSpacer />
      <VBtn icon="mdi-close" variant="text" @click="emit('close')" />
    </VToolbar>
    <VDivider />
    
    <AppPage :api="api" plugin-id="AgentTokens" hide-title />
  </div>
</template>
