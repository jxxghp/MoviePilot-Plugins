<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaOverviewEnhancer' },
  navKey: { type: String, default: 'main' },
  hideTitle: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'switch'])

const base = computed(() => `plugin/${props.pluginId || 'MediaOverviewEnhancer'}`)

const loading = ref(false)
const previewing = ref(false)
const starting = ref(false)
const clearing = ref(false)
const message = ref('')
const error = ref('')
const status = ref({})
const servers = ref([])
const previewItems = ref([])
const previewTotal = ref(0)
const form = ref({ media_type: 'all', title: '', force: false, limit: 30 })
let timer = null

const reasonLabels = {
  missing: '简介缺失',
  short: '简介过短',
  duplicate: '简介重复',
  force: '强制重写',
}

const actionLabels = {
  write: '将写入',
  skip: '跳过',
}

const run = computed(() => status.value.run || {})
const running = computed(() => Boolean(status.value.running))
const progress = computed(() => {
  const total = Number(run.value.total || 0)
  const done = Number(run.value.done || 0)
  if (!total) return 0
  return Math.min(100, Math.round((done / total) * 100))
})

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

function errorText(err) {
  if (!err) return '未知错误'
  return err.message || String(err)
}

function kindLabel(kind) {
  if (kind === 'episode') return '剧集'
  if (kind === 'mv') return 'MV'
  return '电影'
}

function reasonLabel(reason) {
  return reasonLabels[reason] || reason || '-'
}

function actionLabel(item) {
  if (item.action === 'write') return `${actionLabels.write} · ${item.source || ''}`
  return `${actionLabels.skip} · ${item.message || ''}`
}

async function loadStatus() {
  loading.value = true
  try {
    const data = unwrap(await props.api.get(`${base.value}/status`))
    status.value = data && typeof data === 'object' ? data : {}
    if (status.value.running) {
      startPolling()
    } else {
      stopPolling()
    }
  } catch (err) {
    error.value = `读取状态失败：${errorText(err)}`
  } finally {
    loading.value = false
  }
}

async function loadServers() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/servers`))
    servers.value = data?.servers || []
  } catch (err) {
    servers.value = []
  }
}

async function runPreview() {
  previewing.value = true
  error.value = ''
  message.value = ''
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/preview`, {
        media_type: form.value.media_type,
        title: form.value.title,
        force: form.value.force,
        limit: Number(form.value.limit) || 30,
      }),
    )
    previewItems.value = data?.items || []
    previewTotal.value = Number(data?.total || previewItems.value.length)
    const problems = (data?.errors || []).join('；')
    message.value = `试跑完成：共 ${previewTotal.value} 条待处理${problems ? `（${problems}）` : ''}`
  } catch (err) {
    error.value = `试跑失败：${errorText(err)}`
  } finally {
    previewing.value = false
  }
}

async function runNow() {
  starting.value = true
  error.value = ''
  message.value = ''
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/run`, {
        media_type: form.value.media_type,
        title: form.value.title,
        force: form.value.force,
        limit: Number(form.value.limit) || 30,
        trigger: 'manual',
      }),
    )
    message.value = data?.message || '任务已提交'
    await loadStatus()
  } catch (err) {
    error.value = `启动失败：${errorText(err)}`
  } finally {
    starting.value = false
  }
}

async function cancelRun() {
  try {
    const data = unwrap(await props.api.post(`${base.value}/cancel`, {}))
    message.value = data?.message || '已请求停止'
    await loadStatus()
  } catch (err) {
    error.value = `停止失败：${errorText(err)}`
  }
}

async function clearRecords() {
  clearing.value = true
  try {
    const data = unwrap(await props.api.post(`${base.value}/clear`, {}))
    message.value = `已清空 ${data?.cleared ?? 0} 条处理记录`
    await loadStatus()
  } catch (err) {
    error.value = `清空失败：${errorText(err)}`
  } finally {
    clearing.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadServers()])
}

function startPolling() {
  if (timer) return
  timer = window.setInterval(() => {
    loadStatus()
  }, 3000)
}

function stopPolling() {
  if (!timer) return
  window.clearInterval(timer)
  timer = null
}

onMounted(() => {
  loadStatus()
  loadServers()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="moe-root">
    <div v-if="!props.hideTitle" class="moe-header">
      <div>
        <div class="text-h6">影视简介增强</div>
        <div class="text-caption text-medium-emphasis">
          为电影写更详细的简介，为剧集每一集写独立简介，为 MV 生成中文简介，并写回 Emby。
        </div>
      </div>
      <VSpacer />
      <VBtn icon="mdi-refresh" variant="text" :loading="loading" @click="refreshAll" />
    </div>

    <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">{{ error }}</VAlert>
    <VAlert v-if="message" type="info" variant="tonal" density="compact" class="mb-3">{{ message }}</VAlert>

    <VCard variant="tonal" class="mb-3">
      <VCardText class="moe-chips">
        <VChip :color="status.enabled ? 'success' : 'grey'" size="small" variant="flat">
          {{ status.enabled ? '插件已启用' : '插件未启用' }}
        </VChip>
        <VChip :color="status.llm_available ? 'primary' : 'warning'" size="small" variant="tonal">
          {{ status.llm_available ? 'LLM 可用' : 'LLM 不可用' }}
        </VChip>
        <VChip size="small" variant="tonal">已处理 {{ status.processed_total || 0 }} 条</VChip>
        <VChip v-if="status.daily" size="small" variant="tonal">
          今日成功 {{ status.daily.updated || 0 }} / 失败 {{ status.daily.failed || 0 }}
        </VChip>
        <VChip size="small" variant="tonal">电影模式 {{ status.movie_mode || '-' }}</VChip>
        <VChip size="small" variant="tonal">分集模式 {{ status.episode_mode || '-' }}</VChip>
        <VChip size="small" variant="tonal">
          MV 简介 {{ status.mv_enabled ? `已启用 · ${(status.mv_libraries || []).join('/') || 'mv'}` : '关闭' }}
        </VChip>
        <VChip size="small" variant="tonal">
          {{ status.auto_on_transfer ? '入库后自动' : '仅手动' }}
        </VChip>
        <VChip size="small" variant="tonal">
          定时补漏 {{ Number(status.schedule_hours || 0) > 0 ? `${status.schedule_hours} 小时` : '关闭' }}
        </VChip>
      </VCardText>
      <VCardText v-if="servers.length" class="moe-chips">
        <VChip
          v-for="server in servers"
          :key="server.name + server.message"
          :color="server.connected ? 'success' : 'error'"
          size="small"
          variant="tonal"
        >
          Emby {{ server.name }} · {{ server.connected ? '已连接' : server.message }}
        </VChip>
      </VCardText>
    </VCard>

    <VCard variant="outlined" class="mb-3">
      <VCardTitle class="text-subtitle-1">执行范围</VCardTitle>
      <VCardText>
        <VRow dense>
          <VCol cols="12" md="3">
            <VSelect
              v-model="form.media_type"
              :items="[
                { title: '全部', value: 'all' },
                { title: '仅电影', value: 'movie' },
                { title: '仅剧集', value: 'tv' },
                { title: '仅 MV', value: 'mv' },
              ]"
              label="处理对象"
              density="comfortable"
              hide-details
            />
          </VCol>
          <VCol cols="12" md="4">
            <VTextField
              v-model="form.title"
              label="指定标题（留空为整库扫描）"
              density="comfortable"
              hide-details
              clearable
            />
          </VCol>
          <VCol cols="12" md="2">
            <VTextField
              v-model="form.limit"
              type="number"
              label="本次上限"
              density="comfortable"
              hide-details
            />
          </VCol>
          <VCol cols="12" md="3" class="d-flex align-center">
            <VSwitch v-model="form.force" label="强制重写已有简介" density="comfortable" hide-details />
          </VCol>
        </VRow>
        <div class="text-caption text-medium-emphasis mt-1">
          「仅 MV」只扫描配置里的 MV 媒体库，简介由 AI 生成（需 LLM 可用）；「全部」不含 MV，避免一次性产生大量大模型调用。
        </div>
        <div class="moe-actions">
          <VBtn variant="tonal" prepend-icon="mdi-flask-outline" :loading="previewing" @click="runPreview">
            试跑（不写入）
          </VBtn>
          <VBtn color="primary" prepend-icon="mdi-play" :loading="starting" :disabled="running" @click="runNow">
            立即执行
          </VBtn>
          <VBtn variant="tonal" color="warning" prepend-icon="mdi-stop" :disabled="!running" @click="cancelRun">
            停止
          </VBtn>
          <VSpacer />
          <VBtn variant="text" color="error" prepend-icon="mdi-delete-sweep-outline" :loading="clearing" @click="clearRecords">
            清空处理记录
          </VBtn>
          <VBtn variant="text" prepend-icon="mdi-cog-outline" @click="emit('switch')">插件设置</VBtn>
        </div>
      </VCardText>
    </VCard>

    <VCard v-if="run && Object.keys(run).length" variant="outlined" class="mb-3">
      <VCardTitle class="text-subtitle-1">运行进度</VCardTitle>
      <VCardText>
        <div class="text-body-2 mb-2">
          {{ run.state === 'running' ? '执行中' : '已结束' }} · 共 {{ run.total || 0 }} 条 ·
          成功 {{ run.updated || 0 }} · 跳过 {{ run.skipped || 0 }} · 失败 {{ run.failed || 0 }}
        </div>
        <VProgressLinear :model-value="progress" color="primary" height="10" rounded />
        <div class="text-caption text-medium-emphasis mt-2">{{ run.message || '' }}</div>
        <div v-if="run.current" class="text-caption text-medium-emphasis">当前：{{ run.current }}</div>
        <div v-if="run.started_at" class="text-caption text-medium-emphasis">
          开始于 {{ run.started_at }}<span v-if="run.finished_at"> · 结束于 {{ run.finished_at }}</span>
        </div>
      </VCardText>
    </VCard>

    <VCard v-if="previewItems.length" variant="outlined" class="mb-3">
      <VCardTitle class="text-subtitle-1">试跑结果（共 {{ previewTotal }} 条）</VCardTitle>
      <VCardText class="moe-table-wrap">
        <VTable density="compact">
          <thead>
            <tr>
              <th>服务器</th>
              <th>类型</th>
              <th>标题</th>
              <th>集</th>
              <th>原因</th>
              <th>处理</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in previewItems" :key="index">
              <td>{{ item.server }}</td>
              <td>{{ kindLabel(item.kind) }}</td>
              <td>{{ item.title }}</td>
              <td>{{ item.kind === 'episode' ? `S${item.season}E${item.episode}` : '-' }}</td>
              <td>{{ reasonLabel(item.reason) }}</td>
              <td>
                <div>{{ actionLabel(item) }}</div>
                <div v-if="item.preview" class="text-caption text-medium-emphasis">{{ item.preview }}</div>
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>

    <VCard variant="outlined">
      <VCardTitle class="text-subtitle-1">最近日志</VCardTitle>
      <VCardText class="moe-logs">
        <div v-if="!(status.logs || []).length" class="text-caption text-medium-emphasis">暂无日志</div>
        <div v-for="(log, index) in (status.logs || []).slice().reverse()" :key="index" class="moe-log-line">
          <span class="text-caption text-medium-emphasis">[{{ log.time }}]</span>
          <span :class="log.level === 'error' ? 'text-error' : (log.level === 'warning' ? 'text-warning' : '')">
            {{ log.message }}
          </span>
        </div>
      </VCardText>
    </VCard>
  </div>
</template>

<style scoped>
.moe-root {
  padding: 12px 16px 24px;
}

.moe-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.moe-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-bottom: 8px;
}

.moe-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.moe-table-wrap {
  max-height: 360px;
  overflow: auto;
}

.moe-logs {
  max-height: 240px;
  overflow: auto;
  font-size: 12px;
}

.moe-log-line {
  display: flex;
  gap: 6px;
  line-height: 1.6;
}
</style>
