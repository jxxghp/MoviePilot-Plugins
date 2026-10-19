<script setup>
import { ref } from 'vue'

import AppPage from './AppPage.vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaOverviewEnhancer' },
  navKey: { type: String, default: 'main' },
  show_switch: { type: Boolean, default: true },
})

const emit = defineEmits(['close', 'switch'])

const pageRef = ref(null)
</script>

<template>
  <div class="moe-page-wrapper">
    <VToolbar density="comfortable" class="moe-toolbar">
      <div class="text-h6 ms-3">影视简介增强</div>
      <VSpacer />
      <VTooltip v-if="props.show_switch" text="插件设置" location="bottom">
        <template #activator="{ props: tooltipProps }">
          <VBtn
            v-bind="tooltipProps"
            icon="mdi-cog-outline"
            variant="text"
            aria-label="插件设置"
            @click="emit('switch')"
          />
        </template>
      </VTooltip>
      <VBtn icon="mdi-close" variant="text" aria-label="关闭" @click="emit('close')" />
    </VToolbar>
    <VDivider />
    <AppPage
      ref="pageRef"
      :api="props.api"
      :plugin-id="props.pluginId"
      :nav-key="props.navKey"
      hide-title
    />
  </div>
</template>

<style scoped>
.moe-toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgb(var(--v-theme-surface));
}
</style>
