<script setup>
import AppPage from './AppPage.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: '' },
  sourcePluginId: { type: String, default: '' },
})
</script>

<template>
  <AppPage :api="api" :plugin-id="pluginId" :source-plugin-id="sourcePluginId" compact />
</template>
