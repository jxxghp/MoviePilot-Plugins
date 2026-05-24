<script setup>
import AppPage from './AppPage.vue'

defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
})
</script>

<template>
  <AppPage :api="api" plugin-id="AgentTokens" />
</template>
