<script setup>
import AppPage from './AppPage.vue'

defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  navKey: { type: String, default: 'main' },
})
</script>

<template>
  <AppPage v-bind="$props" />
</template>
