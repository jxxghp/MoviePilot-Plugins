<script setup>
import AppPage from './AppPage.vue'
import { createLatestPlanApi } from '../provider.js'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'StorageCleanup' },
})

const guardedApi = createLatestPlanApi({
  get: (...args) => props.api.get(...args),
  post: (...args) => props.api.post(...args),
})
</script>

<template>
  <AppPage :api="guardedApi" :plugin-id="pluginId" />
</template>
