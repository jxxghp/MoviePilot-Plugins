<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  navKey: { type: String, default: 'main' },
})

const loading = ref(true)
const error = ref('')
const sources = ref([])
const status = ref({})
const healthCheckStarting = ref(false)
const busySourceKeys = ref(new Set())
let healthPollTimer = null
let healthPollDeadline = 0
const HEALTH_POLL_INTERVAL_MS = 1000
const HEALTH_POLL_TIMEOUT_MS = 5 * 60 * 1000

const apiCall = (method, path, payload) => {
  if (typeof props.api?.[method] === 'function') return props.api[method](`plugin/${props.pluginId}${path}`, payload)
  return Promise.reject(new Error('MoviePilot API 客户端未注入'))
}

function unwrap(response) {
  const body = response?.data ?? response
  if (body?.success === false) throw new Error(body.message || '请求失败')
  return body?.data ?? body ?? {}
}

async function load(options = {}) {
  const silent = options?.silent === true
  if (!silent) {
    loading.value = true
    error.value = ''
  }
  try {
    const [statusResponse, sourceResponse] = await Promise.all([
      apiCall('get', '/status'),
      apiCall('get', '/sources'),
    ])
    status.value = unwrap(statusResponse)
    sources.value = unwrap(sourceResponse) || []
  } catch (loadError) {
    error.value = loadError?.message || '加载 LunaTV 状态失败'
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadHealthStatus() {
  const [statusResponse, sourceResponse] = await Promise.all([
    apiCall('get', '/status'),
    apiCall('get', '/sources'),
  ])
  status.value = unwrap(statusResponse)
  sources.value = unwrap(sourceResponse) || []
}

function clearHealthPoll() {
  if (healthPollTimer) clearTimeout(healthPollTimer)
  healthPollTimer = null
  healthPollDeadline = 0
}

function scheduleHealthPoll() {
  if (Date.now() >= healthPollDeadline) {
    healthCheckStarting.value = false
    error.value = '健康检查仍在后台运行，请稍后刷新状态查看结果'
    clearHealthPoll()
    return
  }
  if (healthPollTimer) clearTimeout(healthPollTimer)
  healthPollTimer = setTimeout(async () => {
    try {
      await loadHealthStatus()
    } catch (pollError) {
      healthCheckStarting.value = false
      error.value = pollError?.message || '刷新健康检查状态失败'
      clearHealthPoll()
      return
    }
    if (sourceHealth.value.running) scheduleHealthPoll()
    else {
      await load({ silent: true })
      healthCheckStarting.value = false
      clearHealthPoll()
    }
  }, HEALTH_POLL_INTERVAL_MS)
}

async function startHealthCheck() {
  if (healthCheckStarting.value || sourceHealth.value.running) return
  healthCheckStarting.value = true
  error.value = ''
  try {
    unwrap(await apiCall('post', '/sources/refresh'))
    await loadHealthStatus()
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + HEALTH_POLL_TIMEOUT_MS
      scheduleHealthPoll()
    } else {
      healthCheckStarting.value = false
    }
  } catch (requestError) {
    healthCheckStarting.value = false
    error.value = requestError?.message || '启动健康检查失败'
  }
}

function sourceIsBusy(source) {
  return busySourceKeys.value.has(source.key)
}

async function setSourceEnabled(source, enabled) {
  if (!source?.key || sourceIsBusy(source)) return
  const nextBusyKeys = new Set(busySourceKeys.value)
  nextBusyKeys.add(source.key)
  busySourceKeys.value = nextBusyKeys
  error.value = ''
  try {
    const result = unwrap(await apiCall('post', '/sources/state', { source_key: source.key, enabled }))
    await load({ silent: true })
    if (enabled && result?.check_started && sourceHealth.value.running) {
      healthPollDeadline = Date.now() + HEALTH_POLL_TIMEOUT_MS
      scheduleHealthPoll()
    }
  } catch (requestError) {
    error.value = requestError?.message || `更新“${source.name || source.key}”状态失败`
  } finally {
    const remainingBusyKeys = new Set(busySourceKeys.value)
    remainingBusyKeys.delete(source.key)
    busySourceKeys.value = remainingBusyKeys
  }
}

function setSourceConfig(source, event) {
  const value = event?.target?.value
  setSourceEnabled(source, value === 'enabled')
}

async function recheckSource(source) {
  if (!source?.key || sourceIsBusy(source)) return
  const nextBusyKeys = new Set(busySourceKeys.value)
  nextBusyKeys.add(source.key)
  busySourceKeys.value = nextBusyKeys
  error.value = ''
  try {
    unwrap(await apiCall('post', '/sources/refresh', { source_key: source.key }))
    await load({ silent: true })
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + HEALTH_POLL_TIMEOUT_MS
      scheduleHealthPoll()
    }
  } catch (requestError) {
    error.value = requestError?.message || `重新检查“${source.name || source.key}”失败`
  } finally {
    const remainingBusyKeys = new Set(busySourceKeys.value)
    remainingBusyKeys.delete(source.key)
    busySourceKeys.value = remainingBusyKeys
  }
}

const directoryStatus = computed(() => status.value.directories || {})
const downloadSettings = computed(() => status.value.download_settings || {})
const engineStatus = computed(() => status.value.engine || {})
const subscriptionStatus = computed(() => status.value.subscription || {})
const sourceHealth = computed(() => status.value.source_health || {})
const healthChecked = computed(() => Math.max(0, Number(sourceHealth.value.checked || 0)))
const healthCheckTotal = computed(() => Math.max(0, Number(sourceHealth.value.check_total || 0)))
const healthProgress = computed(() => {
  if (!healthCheckTotal.value) return 0
  return Math.min(100, Math.round((healthChecked.value / healthCheckTotal.value) * 100))
})
const healthProgressLabel = computed(() => {
  if (sourceHealth.value.running && !healthCheckTotal.value) return '正在读取来源清单…'
  if (!healthCheckTotal.value) return '尚未开始健康检查'
  return `${sourceHealth.value.running ? '本轮进度' : '最近一轮'} ${healthChecked.value} / ${healthCheckTotal.value}`
})
const queueStatus = computed(() => status.value.queue || {})
const queueTotal = computed(() => ['pending', 'running', 'paused']
  .reduce((total, state) => total + Number(queueStatus.value[state] || 0), 0))
const followupStatus = computed(() => status.value.followup_status || {})
const subscriptionRefreshStatus = computed(() => followupStatus.value.subscription_refresh || {})
const mediaSyncStatus = computed(() => followupStatus.value.media_server_sync || {})

function followupSummary(item) {
  if (item?.running) return '进行中'
  if (!item?.finished_at) return '暂无记录'
  return `${item.success === false ? '失败' : '成功'} · ${formattedTime(item.finished_at)}`
}

function sourceVisualStatus(source) {
  if (
    source?.manual_disabled
    || source?.disabled_reason === 'configured'
    || ['pending', 'unchecked'].includes(source?.health_status)
  ) return 'muted'
  return source?.status || 'ready'
}

function sourceSearchVisualStatus(source) {
  if (
    source?.manual_disabled
    || source?.disabled_reason === 'configured'
    || ['pending', 'unchecked'].includes(source?.health_status)
  ) return 'muted'
  return source?.search_status || 'supported'
}

function sourceHealthVisualStatus(source) {
  if (
    source?.manual_disabled
    || source?.disabled_reason === 'configured'
    || ['pending', 'unchecked'].includes(source?.health_status)
  ) return 'muted'
  return source?.health_status || 'unknown'
}

function sourceCheckedLabel(source) {
  return source?.check_state === 'pending' ? '等待本轮检查' : formattedTime(source?.last_checked)
}

function formattedTime(value) {
  if (!value) return '未检查'
  const numeric = Number(value)
  const date = new Date(Number.isFinite(numeric) ? numeric * 1000 : value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

function sourceUrl(source) {
  const candidate = String(source?.url || source?.detail || source?.api || '').trim()
  if (!candidate) return ''
  try {
    const parsed = new URL(candidate)
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : ''
  } catch {
    return ''
  }
}

function sourceHost(source) {
  const url = sourceUrl(source)
  return url ? new URL(url).hostname : '—'
}

onMounted(load)
onBeforeUnmount(clearHealthPoll)
</script>

<template>
  <div class="lunatv-page">
    <div class="lunatv-header">
      <div>
        <div class="lunatv-eyebrow">THIRD-PARTY CMS / M3U8</div>
        <h1>LunaTV 资源订阅</h1>
        <p>接入 MoviePilot 原生搜索、订阅与下载；播放继续交给既有 Emby。</p>
      </div>
      <div class="header-status">
        <span class="chip">
          并发上限：{{ downloadSettings.max_concurrent_tasks || 2 }} 任务 × {{ downloadSettings.segment_thread_count || 16 }} 分片
        </span>
        <span :class="['chip', engineStatus.ready ? 'ready' : 'muted-chip']">
          N_m3u8DL-RE {{ engineStatus.ready ? '已就绪' : (engineStatus.supported ? '内置待安装' : '当前平台不支持') }}
        </span>
        <span :class="['chip', status.ai?.available ? 'ready' : 'muted-chip']">AI {{ status.ai?.available ? '已就绪' : '未启用' }}</span>
        <span :class="['chip', status.media_server_sync_running ? 'busy' : 'muted-chip']">媒体库 {{ status.media_server_sync_running ? '同步中' : '自动刷新' }}</span>
      </div>
      <div class="lunatv-actions">
        <button class="button secondary" :disabled="loading" @click="load">刷新状态</button>
        <button
          class="button"
          :disabled="status.enabled !== true || healthCheckStarting || sourceHealth.running"
          :aria-label="status.enabled !== true ? '请先启用插件' : (sourceHealth.running ? '健康检查进行中' : '立即健康检查所有来源')"
          @click="startHealthCheck"
        >{{ healthCheckStarting || sourceHealth.running ? '健康检查中…' : '立即健康检查' }}</button>
        <span v-if="status.enabled === false" class="source-caption">请先启用插件后进行健康检查</span>
      </div>
    </div>

    <div v-if="error" class="alert error">{{ error }}</div>
    <div v-else-if="sourceHealth.last_error" class="alert error">
      最近一次健康检查失败：{{ sourceHealth.last_error }}
    </div>
    <div v-if="status.source_config?.error" class="alert warning">
      远程来源清单刷新失败，当前使用{{ status.source_config?.origin || '缓存' }}：{{ status.source_config.error }}
    </div>
    <div v-if="subscriptionRefreshStatus.error" class="alert warning">
      最近一次追更失败：{{ subscriptionRefreshStatus.error }}
    </div>
    <div v-if="mediaSyncStatus.error" class="alert warning">
      最近一次媒体库或订阅进度同步失败：{{ mediaSyncStatus.error }}
    </div>

    <section class="setup-strip">
      <span>目录：{{ directoryStatus.configured_root || directoryStatus.auto_roots?.[0]?.download_path || '未配置' }}</span>
      <span>来源：{{ directoryStatus.source || '未配置' }}</span>
      <span>当前队列：运行 {{ queueStatus.running || 0 }} · 等待 {{ queueStatus.pending || 0 }} · 暂停 {{ queueStatus.paused || 0 }} · 共 {{ queueTotal }} 个活动任务</span>
      <span>追更：每 {{ subscriptionStatus.refresh_minutes || 30 }} 分钟检查新集</span>
      <span>最近追更：{{ followupSummary(subscriptionRefreshStatus) }}</span>
      <span>最近同步：{{ followupSummary(mediaSyncStatus) }}</span>
      <span>TMDB：{{ status.tmdb_association ? '自动关联' : '关闭' }}</span>
      <span>缓存：完成后才整理</span>
      <span>来源健康检查：每 {{ sourceHealth.interval_minutes || 60 }} 分钟</span>
    </section>

    <section class="panel">
      <div class="section-heading">
        <div class="section-title">资源站数量 <span class="muted">{{ loading ? '…' : sources.length }}</span></div>
        <span class="source-caption">打开页面仅读取缓存；搜索会跳过“配置禁用”的来源，网络不通的来源仍会尝试调用</span>
      </div>
      <div v-if="!loading && sources.length" :class="['health-overview', { 'is-running': sourceHealth.running }]">
        <div class="health-progress-block">
          <div class="health-progress-heading">
            <span class="health-progress-title">{{ sourceHealth.running ? '正在逐个检查来源' : '来源健康状态' }}</span>
            <span class="health-progress-count">{{ healthProgressLabel }}</span>
          </div>
          <div
            class="health-progress-track"
            role="progressbar"
            :aria-label="healthProgressLabel"
            :aria-valuemin="0"
            :aria-valuemax="100"
            :aria-valuenow="healthProgress"
          >
            <span :style="{ width: `${healthProgress}%` }"></span>
          </div>
        </div>
        <div class="health-legend" aria-label="健康状态图例">
          <span><i class="legend-dot is-pending" aria-hidden="true"></i>待检查</span>
          <span><i class="legend-dot is-healthy" aria-hidden="true"></i>正常</span>
          <span><i class="legend-dot is-failed" aria-hidden="true"></i>不可用</span>
        </div>
      </div>
      <div v-if="loading" class="empty">正在读取资源站配置…</div>
      <div v-else-if="!sources.length" class="empty">暂未读取到资源站配置</div>
      <div v-else class="source-table-wrap">
        <table class="source-table">
          <thead>
            <tr>
              <th scope="col">状态</th>
              <th scope="col">资源名称</th>
              <th scope="col">网址</th>
              <th scope="col">搜索功能</th>
              <th scope="col">最近检查</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="source in sources" :key="source.key" :class="{ 'is-pending': source.check_state === 'pending' }">
              <td>
                <span :class="['source-state', `is-${sourceVisualStatus(source)}`]">
                  <i class="state-dot" aria-hidden="true"></i>
                  {{ source.status_label || '已加载' }}
                </span>
                <div class="health-status">
                  <span :class="['health-state', `is-${sourceHealthVisualStatus(source)}`]">
                    {{ source.health_label || '未检查' }}
                  </span>
                                    <div class="network-metrics">
                    <span>{{ source.network_label || '待检查' }}</span>
                    <span>成功 {{ source.network_successes || 0 }} 次</span>
                    <span>失败 {{ source.network_failures || 0 }} 次</span>
                  </div>
<span v-if="source.last_error && source.check_state !== 'pending'" class="source-error" :title="source.last_error">{{ source.last_error }}</span>
                </div>
              </td>
              <td>
                <div class="source-identity">
                  <span class="source-name">{{ source.name }}</span>
                  <span class="source-key">{{ source.key }}</span>
                </div>
              </td>
              <td>
                <a
                  v-if="sourceUrl(source)"
                  class="source-link"
                  :href="sourceUrl(source)"
                  target="_blank"
                  rel="noopener noreferrer"
                >{{ sourceHost(source) }}</a>
                <span v-else class="muted">—</span>
              </td>
              <td>
                <span :class="['search-state', `is-${sourceSearchVisualStatus(source)}`]">
                  {{ source.search_label || '支持' }}
                </span>
              </td>
              <td><span :class="{ 'pending-time': source.check_state === 'pending' }">{{ sourceCheckedLabel(source) }}</span></td>
              <td>
                <div class="source-actions">
  <select
    class="source-config-select"
    :value="source.manual_disabled ? 'disabled' : 'enabled'"
    :disabled="sourceIsBusy(source)"
    :aria-label="'配置' + (source.name || source.key) + '来源'"
    @change="setSourceConfig(source, $event)"
  >
    <option value="enabled">配置启用</option>
    <option value="disabled">配置禁用</option>
  </select>
  <button
    class="source-action"
    :disabled="sourceIsBusy(source)"
    :aria-label="'测试来源 ' + (source.name || source.key)"
    @click="recheckSource(source)"
  >{{ sourceIsBusy(source) ? '测试中…' : '测试' }}</button>
</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel help-panel">
      <div class="section-title">使用说明</div>
      <div class="help-grid">
        <p><strong>目录</strong>：目录留空时按媒体类型读取 MoviePilot 的本地目录；填写插件目录则优先使用插件目录。</p>
        <p><strong>多季合集</strong>：有明确季号或 TMDB 季集数能完整对应时才会自动分季；无法确认时会暂停，避免错放。</p>
        <p><strong>自动追更</strong>：MoviePilot 活跃电视剧订阅会定期重新搜索；已完成和正在下载的集数会跳过，只排队新增集。</p>
        <p><strong>媒体库</strong>：目录内没有正在下载的缓存文件后才显示完整文件夹；完成后可请求 Emby/Jellyfin 刷新。</p>
        <p><strong>播放</strong>：插件不内置 m3u8 播放器，播放仍由已有 Emby/Jellyfin 页面负责。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lunatv-page {
  color: rgb(var(--v-theme-on-background, 232, 231, 241));
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 32px;
  box-sizing: border-box;
  background: rgb(var(--v-theme-background, 16, 16, 24));
  min-height: 100%;
}
.lunatv-header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }
.lunatv-eyebrow { color: rgb(var(--v-theme-primary, 139, 92, 246)); font-size: 12px; letter-spacing: .14em; font-weight: 700; }
h1 { margin: 8px 0; font-size: 32px; }
p { color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); margin: 0; }
.header-status { display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.chip { border-radius: 999px; background: rgba(var(--v-theme-primary, 139, 92, 246), .14); color: rgb(var(--v-theme-primary, 139, 92, 246)); padding: 6px 9px; font-size: 12px; white-space: nowrap; }
.chip.ready { background: rgba(var(--v-theme-success, 76, 175, 80), .16); color: rgb(var(--v-theme-on-surface, 232, 231, 241)); }
.chip.busy { background: rgba(var(--v-theme-warning, 251, 140, 0), .16); color: rgb(var(--v-theme-on-surface, 232, 231, 241)); }
.chip.muted-chip { color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); background: rgba(var(--v-theme-on-surface, 232, 231, 241), .08); }
.lunatv-actions { display: flex; gap: 10px; align-items: center; }
.button, .episode-button { border: 0; border-radius: 10px; background: rgb(var(--v-theme-primary, 139, 92, 246)); color: rgb(var(--v-theme-on-primary, 255, 255, 255)); padding: 10px 16px; cursor: pointer; font-weight: 650; }
.button.secondary { background: rgba(var(--v-theme-primary, 139, 92, 246), .14); color: rgb(var(--v-theme-primary, 139, 92, 246)); }
.button:disabled { opacity: .55; cursor: default; }
.panel { background: rgba(var(--v-theme-surface, 23, 23, 34), var(--transparent-opacity-heavy, 1)); border: 1px solid rgba(var(--v-border-color, 232, 231, 241), var(--v-border-opacity, .12)); border-radius: 16px; padding: 18px; margin-bottom: 18px; }
.section-title { font-size: 17px; font-weight: 700; margin-bottom: 14px; }
.muted, small { color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); font-size: 12px; }
.alert { border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; }
.alert.error { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-error, 244, 67, 54), .16); }
.alert.success { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-success, 76, 175, 80), .16); }
.alert.warning { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-warning, 251, 140, 0), .16); }
.setup-strip { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); font-size: 12px; }
.setup-strip span { border: 1px solid rgba(var(--v-border-color, 232, 231, 241), var(--v-border-opacity, .12)); border-radius: 999px; padding: 6px 9px; background: rgba(var(--v-theme-surface, 23, 23, 34), var(--transparent-opacity-heavy, 1)); }
.section-heading { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 14px; }
.section-heading .section-title { margin-bottom: 0; }
.source-caption { color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); font-size: 12px; white-space: nowrap; }
.source-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.source-table { width: 100%; min-width: 810px; border-collapse: collapse; font-size: 13px; }
.source-table th, .source-table td { padding: 11px 12px; border-bottom: 1px solid rgba(var(--v-border-color, 232, 231, 241), var(--v-border-opacity, .12)); text-align: left; white-space: nowrap; }
.source-table th { color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); font-size: 12px; font-weight: 650; }
.source-table tbody tr:last-child td { border-bottom: 0; }
.source-name { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); font-weight: 600; }
.source-link { color: rgb(var(--v-theme-primary, 139, 92, 246)); text-decoration: none; }
.source-link:hover { color: rgb(var(--v-theme-primary, 139, 92, 246)); text-decoration: underline; }
.source-state, .search-state { display: inline-flex; align-items: center; gap: 6px; min-height: 22px; border-radius: 999px; font-size: 12px; font-weight: 650; }
.source-state { padding: 3px 8px; background: rgba(var(--v-theme-on-surface, 232, 231, 241), .08); color: rgb(var(--v-theme-on-surface, 232, 231, 241)); }
.state-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); }
.source-state.is-ready { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-success, 76, 175, 80), .16); }
.source-state.is-ready .state-dot { background: rgb(var(--v-theme-success, 76, 175, 80)); }
.source-state.is-warning { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-warning, 251, 140, 0), .16); }
.source-state.is-warning .state-dot { background: rgb(var(--v-theme-warning, 251, 140, 0)); }
.source-state.is-error { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-error, 244, 67, 54), .16); }
.source-state.is-error .state-dot { background: rgb(var(--v-theme-error, 244, 67, 54)); }
.health-status { display: grid; gap: 4px; margin-top: 5px; }
.health-state { color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); font-size: 12px; }
.health-state.is-healthy, .health-state.is-ready { color: rgb(var(--v-theme-success, 76, 175, 80)); }
.health-state.is-unhealthy, .health-state.is-error, .health-state.is-failed { color: rgb(var(--v-theme-error, 244, 67, 54)); }
.health-state.is-warning, .health-state.is-degraded { color: rgb(var(--v-theme-warning, 251, 140, 0)); }
.network-metrics {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62));
  font-size: 11px;
}
.source-config-select {
  min-width: 92px;
  border: 1px solid rgba(var(--v-theme-primary, 139, 92, 246), .6);
  border-radius: 8px;
  padding: 6px 8px;
  color: rgb(var(--v-theme-on-surface, 232, 231, 241));
  background: rgba(var(--v-theme-surface, 23, 23, 34), 1);
  font: inherit;
}
.source-config-select:disabled {
  opacity: .55;
}
.source-error { color: rgb(var(--v-theme-error, 244, 67, 54)); font-size: 12px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.search-state { padding: 3px 8px; color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-primary, 139, 92, 246), .14); }
.search-state.is-unavailable { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-error, 244, 67, 54), .16); }
.search-state.is-unsupported { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-on-surface, 232, 231, 241), .08); }
.search-state.is-disabled { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-error, 244, 67, 54), .16); }
.search-state.is-empty, .search-state.is-degraded { color: rgb(var(--v-theme-on-surface, 232, 231, 241)); background: rgba(var(--v-theme-warning, 251, 140, 0), .16); }
.source-action { border: 1px solid rgba(var(--v-theme-primary, 139, 92, 246), .45); border-radius: 8px; background: transparent; color: rgb(var(--v-theme-primary, 139, 92, 246)); padding: 5px 10px; cursor: pointer; font-weight: 650; }
.source-action:disabled { cursor: default; opacity: .55; }
.source-actions { display: flex; gap: 6px; }
.empty { color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); padding: 16px 0; }
.help-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px; color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62)); font-size: 13px; line-height: 1.6; }
.help-grid p { margin: 0; }
@media (max-width: 760px) { .lunatv-page { padding: 18px; } .lunatv-header { flex-direction: column; align-items: stretch; } .lunatv-actions { justify-content: flex-start; } .section-heading { align-items: flex-start; flex-direction: column; gap: 4px; } }
@media (max-width: 760px) { .help-grid { grid-template-columns: 1fr; } }
.lunatv-page {
  padding: clamp(18px, 3vw, 32px);
}

.lunatv-header {
  gap: 20px;
}

.panel {
  box-shadow: 0 14px 34px rgba(0, 0, 0, .12);
}

.health-overview {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 14px 16px;
  margin-bottom: 14px;
  border: 1px solid rgba(var(--v-border-color, 232, 231, 241), var(--v-border-opacity, .12));
  border-radius: 12px;
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .035);
}

.health-overview.is-running {
  border-color: rgba(var(--v-theme-primary, 139, 92, 246), .38);
  background: rgba(var(--v-theme-primary, 139, 92, 246), .07);
}

.health-progress-block {
  flex: 1;
  min-width: 220px;
}

.health-progress-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.health-progress-title {
  color: rgb(var(--v-theme-on-surface, 232, 231, 241));
  font-size: 13px;
  font-weight: 700;
}

.health-progress-count {
  color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62));
  font-size: 12px;
  white-space: nowrap;
}

.health-progress-track {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .10);
}

.health-progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, rgb(var(--v-theme-primary, 139, 92, 246)), rgb(var(--v-theme-success, 76, 175, 80)));
  transition: width .25s ease;
}

.health-legend {
  display: flex;
  align-items: center;
  gap: 12px;
  color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62));
  font-size: 12px;
  white-space: nowrap;
}

.health-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .34);
}

.legend-dot.is-healthy { background: rgb(var(--v-theme-success, 76, 175, 80)); }
.legend-dot.is-failed { background: rgb(var(--v-theme-error, 244, 67, 54)); }

.source-table-wrap {
  border: 1px solid rgba(var(--v-border-color, 232, 231, 241), var(--v-border-opacity, .10));
  border-radius: 12px;
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .018);
}

.source-table {
  border-collapse: separate;
  border-spacing: 0;
}

.source-table thead {
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .045);
}

.source-table th,
.source-table td {
  padding: 13px 12px;
}

.source-table tbody tr {
  transition: background-color .18s ease;
}

.source-table tbody tr:hover,
.source-table tbody tr.is-pending {
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .028);
}

.source-identity {
  display: grid;
  gap: 3px;
}

.source-key {
  color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62));
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
}

.source-state.is-muted,
.search-state.is-muted {
  color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62));
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .08);
}

.source-state.is-muted .state-dot,
.legend-dot.is-pending {
  background: rgba(var(--v-theme-on-surface, 232, 231, 241), .34);
}

.health-state.is-pending,
.health-state.is-unchecked,
.health-state.is-unknown,
.pending-time {
  color: rgba(var(--v-theme-on-surface, 232, 231, 241), var(--v-medium-emphasis-opacity, .62));
}

@media (max-width: 900px) {
  .health-overview {
    align-items: stretch;
    flex-direction: column;
    gap: 12px;
  }

  .health-legend {
    flex-wrap: wrap;
  }
}

@media (max-width: 760px) {
  .lunatv-page {
    padding: 16px;
  }

  .health-progress-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 3px;
  }
}
</style>
