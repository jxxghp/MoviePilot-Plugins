<script setup>
import PTStatsWorkbench from './PTStatsWorkbench.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
  navKey: { type: String, default: 'main' },
  pluginId: { type: String, default: 'PTDataStatistics' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
})

defineEmits(['action'])
</script>

<template>
  <PTStatsWorkbench :api="api" :plugin-id="pluginId" @action="$emit('action')" />
</template>
