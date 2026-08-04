<script setup>
import BrushFlowWorkbench from './BrushFlowWorkbench.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
})

defineEmits(['action', 'close'])
</script>

<template>
  <BrushFlowWorkbench
    :api="api"
    plugin-id="BrushFlow"
    show-close
    compact
    @action="$emit('action')"
    @close="$emit('close')"
  />
</template>
