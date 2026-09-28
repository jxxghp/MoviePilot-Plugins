<script setup>
import BrushFlowWorkbench from './BrushFlowWorkbench.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
  navKey: { type: String, default: 'main' },
  pluginId: { type: String, default: 'BrushFlow' },
})

defineEmits(['action'])
</script>

<template>
  <BrushFlowWorkbench :api="api" :plugin-id="pluginId" @action="$emit('action')" />
</template>
