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
  status.value = unwrap(await apiCall('get', '/status'))
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
  }, 2000)
}

async function startHealthCheck() {
  if (healthCheckStarting.value || sourceHealth.value.running) return
  healthCheckStarting.value = true
  error.value = ''
  try {
    unwrap(await apiCall('post', '/sources/refresh'))
    await loadHealthStatus()
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + 60000
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
      healthPollDeadline = Date.now() + 60000
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

async function recheckSource(source) {
  if (!source?.key || sourceIsBusy(source) || sourceHealth.value.running) return
  const nextBusyKeys = new Set(busySourceKeys.value)
  nextBusyKeys.add(source.key)
  busySourceKeys.value = nextBusyKeys
  error.value = ''
  try {
    unwrap(await apiCall('post', '/sources/refresh', { source_key: source.key }))
    await load({ silent: true })
    if (sourceHealth.value.running) {
      healthPollDeadline = Date.now() + 60000
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
          {{ downloadSettings.max_concurrent_tasks || 2 }} 任务 × {{ downloadSettings.segment_thread_count || 16 }} 分片
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
          :disabled="healthCheckStarting || sourceHealth.running"
          :aria-label="sourceHealth.running ? '健康检查进行中' : '立即健康检查所有来源'"
          @click="startHealthCheck"
        >{{ healthCheckStarting || sourceHealth.running ? '健康检查中…' : '立即健康检查' }}</button>
      </div>
    </div>

    <div v-if="error" class="alert error">{{ error }}</div>
    <div v-else-if="sourceHealth.last_error" class="alert error">
      最近一次健康检查失败：{{ sourceHealth.last_error }}
    </div>
    <div v-if="status.source_config?.error" class="alert warning">
      远程来源清单刷新失败，当前使用{{ status.source_config?.origin || '缓存' }}：{{ status.source_config.error }}
    </div>

    <section class="setup-strip">
      <span>目录：{{ directoryStatus.configured_root || directoryStatus.auto_roots?.[0]?.download_path || '未配置' }}</span>
      <span>来源：{{ directoryStatus.source || '未配置' }}</span>
      <span>追更：每 {{ subscriptionStatus.refresh_minutes || 30 }} 分钟检查新集</span>
      <span>TMDB：{{ status.tmdb_association ? '自动关联' : '关闭' }}</span>
      <span>缓存：完成后才整理</span>
      <span>来源健康检查：每 {{ sourceHealth.interval_minutes || 60 }} 分钟</span>
    </section>

    <section class="panel">
      <div class="section-heading">
        <div class="section-title">资源站 <span class="muted">{{ loading ? '…' : sources.length }}</span></div>
        <span class="source-caption">打开页面仅读取缓存；搜索仅使用健康且已启用的来源</span>
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
            <tr v-for="source in sources" :key="source.key">
              <td>
                <span :class="['source-state', `is-${source.status || 'ready'}`]">
                  <i class="state-dot" aria-hidden="true"></i>
                  {{ source.status_label || '已加载' }}
                </span>
                <div class="health-status">
                  <span :class="['health-state', `is-${source.health_status || 'unknown'}`]">
                    {{ source.health_label || '未检查' }}
                  </span>
                  <span v-if="source.last_error" class="source-error" :title="source.last_error">{{ source.last_error }}</span>
                </div>
              </td>
              <td><span class="source-name">{{ source.name }}</span></td>
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
                <span :class="['search-state', `is-${source.search_status || 'supported'}`]">
                  {{ source.search_label || '支持' }}
                </span>
              </td>
              <td>{{ formattedTime(source.last_checked) }}</td>
              <td>
                <div class="source-actions">
                  <button
                    class="source-action"
                    :disabled="sourceIsBusy(source) || sourceHealth.running"
                    :aria-label="`${source.manual_disabled ? '重新启用' : '永久停用'}来源 ${source.name || source.key}`"
                    @click="setSourceEnabled(source, source.manual_disabled)"
                  >{{ sourceIsBusy(source) ? '处理中…' : (source.manual_disabled ? '重新启用' : '永久停用') }}</button>
                  <button
                    v-if="!source.manual_disabled && !source.enabled && source.disabled_reason !== 'configured'"
                    class="source-action"
                    :disabled="sourceIsBusy(source) || sourceHealth.running"
                    :aria-label="`立即复检来源 ${source.name || source.key}`"
                    @click="recheckSource(source)"
                  >立即复检</button>
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
</style>
