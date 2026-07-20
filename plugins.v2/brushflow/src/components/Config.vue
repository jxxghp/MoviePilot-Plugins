<script setup>
import { onMounted } from 'vue'
import BrushFlowWorkbench from './BrushFlowWorkbench.vue'

defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['layout', 'switch', 'close'])

onMounted(() => {
  emit('layout', { maxWidth: '80rem' })
})
</script>

<template>
  <BrushFlowWorkbench
    :api="api"
    plugin-id="BrushFlow"
    initial-tab="config"
    show-close
    show-switch
    compact
    @switch="$emit('switch')"
    @close="$emit('close')"
  />
</template>
