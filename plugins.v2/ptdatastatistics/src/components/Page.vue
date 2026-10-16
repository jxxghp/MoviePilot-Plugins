<script setup>
import PTStatsWorkbench from './PTStatsWorkbench.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'PTDataStatistics' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
})
defineEmits(['action', 'switch', 'close'])
</script>

<template>
  <PTStatsWorkbench
    :api="api"
    :plugin-id="pluginId"
    show-close
    compact
    @action="$emit('action')"
    @close="$emit('close')"
  />
</template>
