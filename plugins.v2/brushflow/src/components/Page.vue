<script setup>
import BrushFlowWorkbench from './BrushFlowWorkbench.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
})

defineEmits(['action', 'switch', 'close'])
</script>

<template>
  <BrushFlowWorkbench
    :api="api"
    plugin-id="BrushFlow"
    show-close
    show-switch
    compact
    @action="$emit('action')"
    @switch="$emit('switch')"
    @close="$emit('close')"
  />
</template>
