<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { formatBytes, taskStateMeta, unwrapResponse } from '../utils'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
})

const loading = ref(false)
const status = ref({ summary: {}, tasks: [] })
let refreshTimer

const runningTasks = computed(() => (status.value.tasks || []).filter(item => item.enabled).slice(0, 3))

// 从插件接口加载仪表板聚合统计。
async function loadStatus() {
  if (!props.allowRefresh && status.value.tasks?.length) return
  loading.value = true
  try {
    status.value = unwrapResponse(await props.api.get('plugin/BrushFlow/status')) || status.value
  } finally {
    loading.value = false
  }
}

watch(
  () => props.allowRefresh,
  enabled => {
    if (enabled) loadStatus()
  },
)

onMounted(() => {
  loadStatus()
  refreshTimer = window.setInterval(loadStatus, 30000)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="brushflow-dashboard">
    <div class="brushflow-dashboard__metrics">
      <div><span>运行任务</span><strong>{{ status.summary.enabled_count || 0 }} / {{ status.summary.task_count || 0 }}</strong></div>
      <div><span>活跃种子</span><strong>{{ status.summary.active_count || 0 }}</strong></div>
      <div><span>累计上传</span><strong>{{ formatBytes(status.summary.uploaded) }}</strong></div>
      <div><span>当前做种</span><strong>{{ formatBytes(status.summary.seeding_size) }}</strong></div>
    </div>
    <VDivider />
    <div class="brushflow-dashboard__tasks">
      <div v-for="task in runningTasks" :key="task.id">
        <VIcon :icon="taskStateMeta(task.state).icon" :color="taskStateMeta(task.state).color" size="18" />
        <div><strong>{{ task.name }}</strong><span>{{ task.site_name }} · {{ task.statistic.active || 0 }} 个种子</span></div>
        <span>{{ formatBytes(task.statistic.uploaded) }}</span>
      </div>
      <div v-if="!runningTasks.length" class="brushflow-dashboard__empty">
        <VIcon icon="mdi-sync-off" />
        暂无启用的刷流任务
      </div>
    </div>
    <VProgressLinear v-if="loading" indeterminate color="primary" height="2" />
  </div>
</template>

<style scoped>
.brushflow-dashboard {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-inline-size: 0;
}

.brushflow-dashboard__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.brushflow-dashboard__metrics > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-inline-size: 0;
}

.brushflow-dashboard__metrics span,
.brushflow-dashboard__tasks span {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.78rem;
}

.brushflow-dashboard__metrics strong {
  font-size: 1.05rem;
  overflow-wrap: anywhere;
}

.brushflow-dashboard__tasks {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.brushflow-dashboard__tasks > div {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
}

.brushflow-dashboard__tasks > div > div {
  display: flex;
  flex-direction: column;
  min-inline-size: 0;
}

.brushflow-dashboard__tasks strong {
  overflow-wrap: anywhere;
}

.brushflow-dashboard__empty {
  justify-content: center;
  padding-block: 18px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}

@media (max-width: 599px) {
  .brushflow-dashboard__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
