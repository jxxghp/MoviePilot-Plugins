<script setup>
import { onMounted } from 'vue'

defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaServerNotifyPlus' },
})
const emit = defineEmits(['action', 'switch', 'close'])

// 插件卡片只保留一个界面：点击后直接进入 Config。
onMounted(() => emit('switch'))
</script>

<template>
  <div class="page-forward" aria-live="polite">
    <VProgressCircular indeterminate color="primary" size="28" />
    <span>正在打开媒体库通知…</span>
  </div>
</template>

<style scoped>
.page-forward {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 180px;
  color: rgba(var(--v-theme-on-surface), .62);
}
</style>
