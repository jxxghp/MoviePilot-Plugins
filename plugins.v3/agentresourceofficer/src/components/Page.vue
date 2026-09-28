<script setup>
import Config from './Config.vue'

defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['save', 'close'])
</script>

<template>
  <Config :api="api" :initial-config="initialConfig" @save="payload => emit('save', payload)" @close="emit('close')" />
</template>
