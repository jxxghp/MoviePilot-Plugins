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
const sampling = ref(false)
const starting = ref(false)
const retrying = ref(false)
const rolling = ref(false)
const clearing = ref(false)
const writingKey = ref('')
const message = ref('')
const error = ref('')
const status = ref({})
const servers = ref([])
const previewItems = ref([])
const previewTotal = ref(0)
const previewSampled = ref(0)
const sourceFilter = ref('all')
const form = ref({ media_type: 'all', title: '', force: false, limit: 30 })
let timer = null

const reasonLabels = {
  missing: '简介缺失',
  short: '简介过短',
  duplicate: '简介重复',
  force: '强制重写',
  people: '缺演员',
  nfo: 'NFO/头像待补',
  avatar: '缺演员头像',
}

const actionLabels = {
  write: '将写入',
  skip: '跳过',
}

const kindLabels = {
  movie: '电影',
  episode: '剧集',
  series: '整剧',
  season: '整季',
  mv: 'MV',
}

const failureKindLabels = {
  llm_unavailable: '大模型不可用',
  llm_rate_limit: '大模型限流',
  llm_empty: '空返回',
  llm_error: '调用异常',
  quality_gate: '质量闸门',
  material_missing: '素材缺失',
  emby_write: '写入失败',
  nfo_write: 'NFO 写入',
  unknown: '未归类',
}

const run = computed(() => status.value.run || {})
const running = computed(() => Boolean(status.value.running))
const failures = computed(() => status.value.failures || [])
const backups = computed(() => status.value.backups || [])
const progress = computed(() => {
  const total = Number(run.value.total || 0)
  const done = Number(run.value.done || 0)
  if (!total) return 0
  return Math.min(100, Math.round((done / total) * 100))
})

const sourceOptions = computed(() => {
  const values = new Set()
  previewItems.value.forEach(item => {
    if (item.source) values.add(String(item.source))
  })
  return [
    { title: '全部来源', value: 'all' },
    ...Array.from(values).sort().map(value => ({ title: value, value })),
  ]
})

const filteredPreview = computed(() => {
  if (sourceFilter.value === 'all') return previewItems.value
  return previewItems.value.filter(item => String(item.source || '') === sourceFilter.value)
})

const latestRunId = computed(() => {
  const row = backups.value.find(item => item.run_id)
  return row?.run_id || ''
})

const llmStats = computed(() => status.value.llm || {})
const failureKinds = computed(() => status.value.failure_kinds || {})
const features = computed(() => status.value.features || {})

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

function errorText(err) {
  if (!err) return '未知错误'
  const response = err.response || {}
  const data = response.data || {}
  const detail = data.detail || data.message || err.message
  if (typeof detail === 'string' && detail.trim()) return detail
  if (response.status) return `HTTP ${response.status}`
  return '未知错误（后端未返回详情，请查看 MP 日志）'
}

function kindLabel(kind) {
  return kindLabels[kind] || '电影'
}

function reasonLabel(reason) {
  return reasonLabels[reason] || reason || '-'
}

function actionLabel(item) {
  if (item.action === 'write') return `${actionLabels.write} · ${item.source || ''}`
  return `${actionLabels.skip} · ${item.message || ''}`
}

function episodeLabel(item) {
  if (item.kind !== 'episode') return '-'
  return `S${item.season}E${item.episode}`
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

async function runPreview(withSample = false) {
  if (withSample) sampling.value = true
  else previewing.value = true
  error.value = ''
  message.value = ''
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/preview`, {
        media_type: form.value.media_type,
        title: form.value.title,
        force: form.value.force,
        limit: Number(form.value.limit) || 30,
        sample: withSample ? 2 : 0,
      }),
    )
    previewItems.value = data?.items || []
    previewTotal.value = Number(data?.total || previewItems.value.length)
    previewSampled.value = Number(data?.sample || 0)
    const problems = (data?.errors || []).join('；')
    message.value = `试跑完成：共 ${previewTotal.value} 条待处理${
      previewSampled.value ? `，已生成 ${previewSampled.value} 条样张` : ''
    }${problems ? `（${problems}）` : ''}`
  } catch (err) {
    error.value = `试跑失败：${errorText(err)}`
  } finally {
    previewing.value = false
    sampling.value = false
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

async function redoItem(item) {
  if (!item?.key) return
  const mediaType = item.kind === 'episode' ? 'tv' : (item.kind === 'mv' ? 'mv' : 'movie')
  starting.value = true
  error.value = ''
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/run`, {
        media_type: mediaType,
        title: '',
        force: true,
        limit: 1,
        keys: [item.key],
        trigger: 'manual',
      }),
    )
    message.value = data?.message || '已提交单条重做'
    await loadStatus()
  } catch (err) {
    error.value = `单条重做失败：${errorText(err)}`
  } finally {
    starting.value = false
  }
}

async function writeSample(item) {
  if (!item?.key || !item?.preview) return
  writingKey.value = String(item.key)
  error.value = ''
  message.value = ''
  const mediaType = ['episode', 'series', 'season'].includes(item.kind)
    ? 'tv'
    : (item.kind === 'mv' ? 'mv' : 'movie')
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/write-sample`, {
        key: item.key,
        kind: item.kind || '',
        media_type: mediaType,
        title: item.title || '',
        year: item.year || '',
        season: item.season ?? 0,
        episode: item.episode ?? 0,
        episode_title: item.episode_title || '',
        text: item.preview,
        title_override: item.new_title || '',
      }),
    )
    if (data?.written) {
      message.value = `已写入样张：${item.title || item.key}`
      await loadStatus()
    } else {
      error.value = `写入失败：${data?.message || '未知原因'}`
    }
  } catch (err) {
    error.value = `写入失败：${errorText(err)}`
  } finally {
    writingKey.value = ''
  }
}

async function retryFailures() {
  retrying.value = true
  error.value = ''
  try {
    const data = unwrap(await props.api.post(`${base.value}/retry`, {}))
    message.value = data?.message || '已请求重试'
    await loadStatus()
  } catch (err) {
    error.value = `重试失败：${errorText(err)}`
  } finally {
    retrying.value = false
  }
}

async function rollbackOne(row) {
  if (!row?.key) return
  rolling.value = true
  error.value = ''
  try {
    const data = unwrap(await props.api.post(`${base.value}/rollback`, { keys: [row.key] }))
    message.value = data?.message || '已回滚'
    await loadStatus()
  } catch (err) {
    error.value = `回滚失败：${errorText(err)}`
  } finally {
    rolling.value = false
  }
}

async function rollbackLatestRun() {
  const runId = latestRunId.value
  if (!runId) {
    message.value = '没有可回滚的运行批次'
    return
  }
  rolling.value = true
  error.value = ''
  try {
    const data = unwrap(await props.api.post(`${base.value}/rollback`, { run_id: runId }))
    message.value = data?.message || '已回滚最近一轮'
    await loadStatus()
  } catch (err) {
    error.value = `回滚失败：${errorText(err)}`
  } finally {
    rolling.value = false
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
    message.value = `已清空 ${data?.cleared ?? 0} 条处理记录与 ${data?.failures ?? 0} 条失败记录`
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

const auditing = ref(false)
const repairing = ref(false)
const auditItems = ref([])
const auditScanned = ref(0)
const auditTotal = ref(0)
const auditTime = ref('')
const auditErrors = ref([])
const auditType = ref('all')
const auditLimit = ref(300)
const auditSelected = ref([])

const auditFilter = ref('all')
const auditSelectedSet = computed(() => new Set(auditSelected.value.map(String)))

function auditHas(item, kind) {
  const text = (item.reasons || []).join('；')
  if (kind === 'missing') return text.includes('简介缺失')
  if (kind === 'short') return text.includes('简介过短')
  if (kind === 'tech') return text.includes('技术信息')
  if (kind === 'flavor') return text.includes('AI 味')
  if (kind === 'similar') return text.includes('雷同')
  return true
}

const filteredAuditItems = computed(() => {
  if (auditFilter.value === 'all') return auditItems.value
  return auditItems.value.filter(item => auditHas(item, auditFilter.value))
})

const auditAllSelected = computed(
  () =>
    filteredAuditItems.value.length > 0 &&
    filteredAuditItems.value.every(item => auditSelectedSet.value.has(String(item.key))),
)

function auditReasonText(item) {
  return (item.reasons || []).join('；') || '-'
}

function applyAudit(data) {
  auditItems.value = data?.items || []
  auditScanned.value = Number(data?.scanned || 0)
  auditTotal.value = Number(data?.total || 0)
  auditTime.value = data?.time || ''
  auditErrors.value = data?.errors || []
  const keys = new Set(auditItems.value.map(item => String(item.key)))
  auditSelected.value = auditSelected.value.filter(key => keys.has(key))
}

async function loadAudit() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/audit`))
    applyAudit(data)
  } catch (err) {
    auditItems.value = []
  }
}

async function runAudit() {
  auditing.value = true
  error.value = ''
  message.value = ''
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/audit/scan`, {
        media_type: auditType.value,
        limit: Number(auditLimit.value) || 300,
      }),
    )
    applyAudit(data)
    const problems = (data?.errors || []).join('；')
    message.value = `体检完成：扫描 ${auditScanned.value} 条，发现 ${auditTotal.value} 条低质简介${
      data?.truncated ? `（仅显示前 ${auditItems.value.length} 条）` : ''
    }${problems ? `（${problems}）` : ''}`
    auditSelected.value = auditItems.value.slice(0, 50).map(item => String(item.key))
  } catch (err) {
    error.value = `体检失败：${errorText(err)}`
  } finally {
    auditing.value = false
  }
}

function toggleAuditAll() {
  if (auditAllSelected.value) {
    auditSelected.value = []
  } else {
    auditSelected.value = filteredAuditItems.value.map(item => String(item.key))
  }
}

function toggleAuditItem(key) {
  const value = String(key)
  const index = auditSelected.value.indexOf(value)
  if (index >= 0) auditSelected.value.splice(index, 1)
  else auditSelected.value.push(value)
}

async function repairAudit() {
  if (!auditSelected.value.length) {
    message.value = '请先勾选要重写的条目'
    return
  }
  repairing.value = true
  error.value = ''
  try {
    const data = unwrap(
      await props.api.post(`${base.value}/audit/repair`, { keys: auditSelected.value }),
    )
    if (data?.started) {
      message.value = data?.message || '已提交重写'
      await loadStatus()
    } else {
      error.value = data?.message || '提交重写失败'
    }
  } catch (err) {
    error.value = `提交重写失败：${errorText(err)}`
  } finally {
    repairing.value = false
  }
}

onMounted(() => {
  loadStatus()
  loadServers()
  loadAudit()
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
        <VChip
          v-if="status.failure_count"
          color="error"
          size="small"
          variant="tonal"
        >
          失败待处理 {{ status.failure_count }} 条
        </VChip>
        <VChip size="small" variant="tonal">可回滚 {{ status.backup_count || 0 }} 条</VChip>
        <VChip v-if="Number(llmStats.calls || 0)" size="small" variant="tonal">
          今日大模型 {{ llmStats.calls }} 次 · 成功率 {{ llmStats.success_rate ?? 0 }}% ·
          均耗时 {{ llmStats.avg_seconds ?? 0 }}s
        </VChip>
        <VChip
          v-if="Number(llmStats.rate_limited || 0)"
          color="warning"
          size="small"
          variant="tonal"
        >
          今日限流 {{ llmStats.rate_limited }} 次
        </VChip>
        <VChip v-if="features.style_preset" size="small" variant="tonal">
          文风 {{ features.style_preset }}
        </VChip>
        <VChip v-if="features.episode_title" size="small" variant="tonal">分集标题美化</VChip>
        <VChip v-if="features.series" size="small" variant="tonal">整剧简介</VChip>
        <VChip v-if="features.season" size="small" variant="tonal">整季简介</VChip>
        <VChip v-if="features.people_bio" size="small" variant="tonal">演职员简介</VChip>
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
      <VCardText v-if="Object.keys(failureKinds).length" class="moe-chips">
        <span class="text-caption text-medium-emphasis align-self-center">失败分类：</span>
        <VChip
          v-for="(count, kind) in failureKinds"
          :key="kind"
          size="small"
          color="error"
          variant="tonal"
        >
          {{ failureKindLabels[kind] || kind }} {{ count }}
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
                { title: '仅剧集（含整剧/整季）', value: 'tv' },
                { title: '仅 MV', value: 'mv' },
                { title: '仅补分集标题', value: 'titles' },
                { title: '仅补 NFO/头像', value: 'maintenance' },
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
          「仅 MV」扫描 MV 媒体库并由 AI 生成简介；「仅补分集标题」只改写「第 N 集」这类占位标题
          （写 Emby 标题与 NFO），**不动简介**；「仅补 NFO/头像」只修复缺失或过期的 NFO 与演员头像；
          「全部」不含 MV，避免一次性产生大量大模型调用。
        </div>
        <div class="moe-actions">
          <VBtn variant="tonal" prepend-icon="mdi-flask-outline" :loading="previewing" @click="runPreview(false)">
            试跑（不写入）
          </VBtn>
          <VBtn variant="tonal" prepend-icon="mdi-image-text" :loading="sampling" @click="runPreview(true)">
            生成 2 条样张
          </VBtn>
          <VBtn color="primary" prepend-icon="mdi-play" :loading="starting" :disabled="running" @click="runNow">
            立即执行
          </VBtn>
          <VBtn variant="tonal" color="warning" prepend-icon="mdi-stop" :disabled="!running" @click="cancelRun">
            停止
          </VBtn>
          <VBtn
            variant="tonal"
            color="error"
            prepend-icon="mdi-restart-alert"
            :loading="retrying"
            :disabled="!failures.length || running"
            @click="retryFailures"
          >
            重试失败项
          </VBtn>
          <VSpacer />
          <VBtn variant="text" color="error" prepend-icon="mdi-delete-sweep-outline" :loading="clearing" @click="clearRecords">
            清空处理记录
          </VBtn>
          <VBtn variant="text" prepend-icon="mdi-cog-outline" @click="emit('switch')">插件设置</VBtn>
        </div>
      </VCardText>
    </VCard>

    <VCard variant="outlined" class="mb-3">
      <VCardTitle class="text-subtitle-1 d-flex align-center flex-wrap ga-2">
        存量简介体检
        <VChip v-if="auditTime" size="x-small" variant="tonal">{{ auditTime }}</VChip>
        <VSpacer />
        <VSelect
          v-model="auditFilter"
          :items="[
            { title: '全部问题', value: 'all' },
            { title: '简介缺失', value: 'missing' },
            { title: '简介过短', value: 'short' },
            { title: '技术词', value: 'tech' },
            { title: 'AI 味', value: 'flavor' },
            { title: '同季雷同', value: 'similar' },
          ]"
          density="compact"
          variant="outlined"
          hide-details
          style="max-width: 150px"
        />
        <VBtn
          size="small"
          variant="tonal"
          prepend-icon="mdi-magnify-scan"
          :loading="auditing"
          :disabled="running || repairing"
          @click="runAudit"
        >
          开始体检
        </VBtn>
      </VCardTitle>
      <VCardText>
        <VRow dense>
          <VCol cols="12" md="4">
            <VSelect
              v-model="auditType"
              :items="[
                { title: '电影 + 剧集', value: 'all' },
                { title: '仅电影', value: 'movie' },
                { title: '仅剧集分集', value: 'tv' },
                { title: '仅 MV', value: 'mv' },
              ]"
              label="体检范围"
              density="comfortable"
              hide-details
            />
          </VCol>
          <VCol cols="12" md="3">
            <VTextField
              v-model="auditLimit"
              type="number"
              label="最多显示条数"
              density="comfortable"
              hide-details
            />
          </VCol>
          <VCol cols="12" md="5" class="d-flex align-center flex-wrap ga-2">
            <VBtn size="small" variant="text" :disabled="!auditItems.length" @click="toggleAuditAll">
              {{ auditAllSelected ? '取消全选' : '全选' }}
            </VBtn>
            <VBtn
              size="small"
              color="primary"
              prepend-icon="mdi-auto-fix"
              :disabled="!auditSelected.length || running || repairing"
              :loading="repairing"
              @click="repairAudit"
            >
              重写选中（{{ auditSelected.length }}）
            </VBtn>
          </VCol>
        </VRow>
        <div class="text-caption text-medium-emphasis mt-1">
          只读扫描已有简介（包括旧版本写入、手动修改和其他插件写入的内容），检测缺失 / 过短、技术词、
          模板化开头、AI 味偏重与同季雷同。扫描不调用大模型、不写库；只有「重写选中」才会生成并写回，
          且仍走质量闸门与失败重试。
        </div>
        <div v-if="auditErrors.length" class="text-caption text-warning mt-1">
          {{ auditErrors.join('；') }}
        </div>
      </VCardText>
      <VCardText v-if="auditItems.length" class="moe-table-wrap">
        <VTable density="compact">
          <thead>
            <tr>
              <th style="width: 40px"></th>
              <th>类型</th>
              <th>标题</th>
              <th>集</th>
              <th>字数</th>
              <th>AI 味</th>
              <th>问题</th>
              <th>现简介</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in filteredAuditItems" :key="item.key">
              <td>
                <VCheckbox
                  :model-value="auditSelectedSet.has(String(item.key))"
                  density="compact"
                  hide-details
                  @update:model-value="toggleAuditItem(item.key)"
                />
              </td>
              <td>{{ kindLabel(item.kind) }}</td>
              <td>{{ item.title }}</td>
              <td>{{ item.kind === 'episode' ? `S${item.season}E${item.episode}` : '-' }}</td>
              <td>{{ item.chars }}</td>
              <td>{{ item.flavor || '-' }}</td>
              <td>
                <div class="text-error">{{ auditReasonText(item) }}</div>
                <div v-if="(item.hints || []).length" class="text-caption text-medium-emphasis">
                  {{ (item.hints || []).join('；') }}
                </div>
              </td>
              <td class="moe-preview">{{ item.preview }}</td>
            </tr>
          </tbody>
        </VTable>
        <div class="text-caption text-medium-emphasis mt-1">
          共发现 {{ auditTotal }} 条；当前筛选 {{ filteredAuditItems.length }} 条（已保存 {{ auditItems.length }} 条）。
          体检结果会保留到下次扫描。
        </div>
      </VCardText>
      <VCardText v-else class="text-caption text-medium-emphasis">
        还没有体检结果。点击「开始体检」扫描当前媒体库。
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
        <div v-if="run.llm && run.llm.calls" class="text-caption text-medium-emphasis">
          本轮大模型：调用 {{ run.llm.calls }} 次 · 失败 {{ run.llm.errors || 0 }} ·
          空返回 {{ run.llm.empty || 0 }}
          <span v-if="run.llm.rate_limited" class="text-warning">· 出现限流 {{ run.llm.rate_limited }} 次</span>
        </div>
      </VCardText>
    </VCard>

    <VCard v-if="previewItems.length" variant="outlined" class="mb-3">
      <VCardTitle class="text-subtitle-1 d-flex align-center">
        试跑结果（共 {{ previewTotal }} 条）
        <VSpacer />
        <VSelect
          v-model="sourceFilter"
          :items="sourceOptions"
          density="compact"
          variant="outlined"
          hide-details
          style="max-width: 200px"
        />
      </VCardTitle>
      <VCardText class="moe-table-wrap">
        <VTable density="compact">
          <thead>
            <tr>
              <th>类型</th>
              <th>标题</th>
              <th>集</th>
              <th>原因</th>
              <th>处理</th>
              <th>样张 / 质量</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in filteredPreview" :key="item.key || index">
              <td>{{ kindLabel(item.kind) }}</td>
              <td>{{ item.title }}</td>
              <td>{{ episodeLabel(item) }}</td>
              <td>{{ reasonLabel(item.reason) }}</td>
              <td>
                <div>{{ actionLabel(item) }}</div>
                <div v-if="item.need_nfo" class="text-caption text-medium-emphasis">将补 NFO</div>
                <div v-if="item.need_avatar" class="text-caption text-medium-emphasis">将补头像</div>
              </td>
              <td class="moe-preview">
                <div v-if="item.preview">{{ item.preview }}</div>
                <div v-if="item.quality" class="text-error text-caption">质量提示：{{ item.quality }}</div>
                <div v-if="item.preview" class="text-caption text-medium-emphasis">
                  AI 味 {{ item.ai_flavor ?? '-' }} 分
                  <span v-if="(item.ai_flavor_reasons || []).length">
                    （{{ (item.ai_flavor_reasons || []).join('、') }}）
                  </span>
                  <span v-if="item.similarity"> · 同季相似度 {{ Math.round(item.similarity * 100) }}%</span>
                </div>
                <div v-if="item.new_title" class="text-caption">
                  新标题：{{ item.new_title }}
                </div>
              </td>
              <td>
                <VBtn
                  v-if="item.preview"
                  size="x-small"
                  variant="tonal"
                  color="primary"
                  :disabled="running"
                  :loading="writingKey === String(item.key)"
                  @click="writeSample(item)"
                >
                  写入此样张
                </VBtn>
                <VBtn
                  size="x-small"
                  variant="text"
                  :disabled="running"
                  :loading="starting && writingKey !== String(item.key)"
                  @click="redoItem(item)"
                >
                  重做
                </VBtn>
              </td>
            </tr>
          </tbody>
        </VTable>
        <div class="text-caption text-medium-emphasis mt-1">
          样张只对前 {{ previewSampled || 0 }} 条生成，不会写入媒体库；「写入此样张」会直接落库并记一次人工写入，
          「重做」会强制重新生成该条。
        </div>
      </VCardText>
    </VCard>

    <VCard v-if="failures.length" variant="outlined" class="mb-3">
      <VCardTitle class="text-subtitle-1 d-flex align-center">
        失败条目（最近 {{ failures.length }} 条）
        <VSpacer />
        <VBtn
          size="small"
          variant="tonal"
          color="error"
          prepend-icon="mdi-restart-alert"
          :loading="retrying"
          :disabled="running"
          @click="retryFailures"
        >
          全部重试
        </VBtn>
      </VCardTitle>
      <VCardText class="moe-table-wrap">
        <VTable density="compact">
          <thead>
            <tr>
              <th>类型</th>
              <th>标题</th>
              <th>集</th>
              <th>分类</th>
              <th>失败原因</th>
              <th>时间</th>
              <th>次数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in failures" :key="row.key || index">
              <td>{{ kindLabel(row.kind) }}</td>
              <td>{{ row.title }}</td>
              <td>{{ row.kind === 'episode' ? `S${row.season}E${row.episode}` : '-' }}</td>
              <td>
                <VChip size="x-small" variant="tonal" color="error">
                  {{ failureKindLabels[row.error_kind] || row.error_kind || '未归类' }}
                </VChip>
              </td>
              <td class="text-error">{{ row.message }}</td>
              <td>{{ row.time }}</td>
              <td>{{ row.count }}</td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>

    <VCard v-if="backups.length" variant="outlined" class="mb-3">
      <VCardTitle class="text-subtitle-1 d-flex align-center">
        可回滚的旧简介（最近 {{ backups.length }} 条）
        <VSpacer />
        <VBtn
          size="small"
          variant="tonal"
          color="warning"
          prepend-icon="mdi-history"
          :loading="rolling"
          :disabled="!latestRunId || running"
          @click="rollbackLatestRun"
        >
          回滚最近一轮
        </VBtn>
      </VCardTitle>
      <VCardText class="moe-table-wrap">
        <VTable density="compact">
          <thead>
            <tr>
              <th>类型</th>
              <th>标题</th>
              <th>集</th>
              <th>写入前简介</th>
              <th>时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in backups" :key="row.key || index">
              <td>{{ kindLabel(row.kind) }}</td>
              <td>{{ row.title }}</td>
              <td>{{ row.kind === 'episode' ? `S${row.season}E${row.episode}` : '-' }}</td>
              <td class="moe-preview">{{ row.preview }}（{{ row.chars }} 字）</td>
              <td>{{ row.time }}</td>
              <td>
                <VBtn
                  size="x-small"
                  variant="text"
                  color="warning"
                  :loading="rolling"
                  :disabled="running"
                  @click="rollbackOne(row)"
                >
                  回滚
                </VBtn>
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

.moe-preview {
  max-width: 420px;
  white-space: normal;
  line-height: 1.5;
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
