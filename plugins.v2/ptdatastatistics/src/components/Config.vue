<script setup>
import { onMounted } from 'vue'
import PTStatsWorkbench from './PTStatsWorkbench.vue'

defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'PTDataStatistics' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
})
const emit = defineEmits(['layout', 'save', 'close', 'switch'])

onMounted(() => emit('layout', { maxWidth: '80rem' }))
</script>

<template>
  <PTStatsWorkbench
    :api="api"
    :plugin-id="pluginId"
    :initial-settings="initialConfig"
    host-managed-config
    initial-tab="config"
    show-close
    compact
    @save="$emit('save', $event)"
    @close="$emit('close')"
  />
</template>
