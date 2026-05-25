<script setup>
import { ref } from 'vue'
import AppPage from './AppPage.vue'

defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
})
const emit = defineEmits(['close'])

const pageRef = ref(null)
</script>

<template>
  <div class="agenttokens-page-wrapper">
    <VToolbar density="comfortable" class="sticky-toolbar">
      <div class="text-h6">Agent Tokens 管理</div>
      <VSpacer />
      <VBtn icon="mdi-refresh" variant="text" :loading="pageRef?.loading" @click="pageRef?.loadStatus()" />
      <VBtn icon="mdi-content-save" variant="text" color="primary" :loading="pageRef?.saving" @click="pageRef?.saveConfig()" />
      <VBtn icon="mdi-close" variant="text" @click="emit('close')" />
    </VToolbar>
    <VDivider />
    
    <AppPage ref="pageRef" :api="api" plugin-id="AgentTokens" hide-title />
  </div>
</template>

<style scoped>
.sticky-toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgb(var(--v-theme-surface));
}
</style>
