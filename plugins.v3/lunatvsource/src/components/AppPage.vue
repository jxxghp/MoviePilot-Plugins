<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  navKey: { type: String, default: 'main' },
})

const loading = ref(true)
const error = ref('')
const sources = ref([])
const status = ref({})

const apiCall = (method, path, payload) => {
  if (typeof props.api?.[method] === 'function') return props.api[method](`plugin/${props.pluginId}${path}`, payload)
  return Promise.reject(new Error('MoviePilot API 客户端未注入'))
}

function unwrap(response) {
  const body = response?.data ?? response
  if (body?.success === false) throw new Error(body.message || '请求失败')
  return body?.data ?? body ?? {}
}

async function load() {
  loading.value = true
  error.value = ''
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
    loading.value = false
  }
}

const directoryStatus = computed(() => status.value.directories || {})

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
        <span class="chip">串行队列</span>
        <span :class="['chip', status.ai?.available ? 'ready' : 'muted-chip']">AI {{ status.ai?.available ? '已就绪' : '未启用' }}</span>
        <span :class="['chip', status.media_server_sync_running ? 'busy' : 'muted-chip']">媒体库 {{ status.media_server_sync_running ? '同步中' : '自动刷新' }}</span>
      </div>
      <div class="lunatv-actions">
        <button class="button" :disabled="loading" @click="load">重新加载</button>
      </div>
    </div>

    <div v-if="error" class="alert error">{{ error }}</div>

    <section class="setup-strip">
      <span>目录：{{ directoryStatus.configured_root || directoryStatus.auto_roots?.[0]?.download_path || '未配置' }}</span>
      <span>来源：{{ directoryStatus.source || '未配置' }}</span>
      <span>TMDB：{{ status.tmdb_association ? '自动关联' : '关闭' }}</span>
      <span>缓存：完成后才整理</span>
    </section>

    <section class="panel">
      <div class="section-heading">
        <div class="section-title">资源站 <span class="muted">{{ loading ? '…' : sources.length }}</span></div>
        <span class="source-caption">依据源配置备注，非实时测速</span>
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
            </tr>
          </thead>
          <tbody>
            <tr v-for="source in sources" :key="source.key">
              <td>
                <span :class="['source-state', `is-${source.status || 'ready'}`]">
                  <i class="state-dot" aria-hidden="true"></i>
                  {{ source.status_label || '已加载' }}
                </span>
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
        <p><strong>媒体库</strong>：目录内没有正在下载的缓存文件后才显示完整文件夹；完成后可请求 Emby/Jellyfin 刷新。</p>
        <p><strong>播放</strong>：插件不内置 m3u8 播放器，播放仍由已有 Emby/Jellyfin 页面负责。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lunatv-page { color: #e8e7f1; max-width: 1200px; margin: 0 auto; padding: 32px; background: #101018; min-height: 100%; }
.lunatv-header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }
.lunatv-eyebrow { color: #9d72ff; font-size: 12px; letter-spacing: .14em; font-weight: 700; }
h1 { margin: 8px 0; font-size: 32px; } p { color: #a5a2b5; margin: 0; }
.header-status { display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.chip { border-radius: 999px; background: #28203e; color: #c4a8ff; padding: 6px 9px; font-size: 12px; white-space: nowrap; }
.chip.ready { background: #183125; color: #a7efbd; } .chip.busy { background: #3a2c1e; color: #ffc66d; } .chip.muted-chip { color: #9693a7; background: #20202b; }
.lunatv-actions { display: flex; gap: 10px; align-items: center; }
.button, .episode-button { border: 0; border-radius: 10px; background: #8b5cf6; color: white; padding: 10px 16px; cursor: pointer; font-weight: 650; }
.button.secondary { background: #28203e; color: #c4a8ff; } .button:disabled { opacity: .55; cursor: default; }
.panel { background: #171722; border: 1px solid #292938; border-radius: 16px; padding: 18px; margin-bottom: 18px; }
.section-title { font-size: 17px; font-weight: 700; margin-bottom: 14px; } .muted, small { color: #9693a7; font-size: 12px; }
.alert { border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; } .alert.error { color: #ffb4ab; background: #3a1e22; } .alert.success { color: #a7efbd; background: #183125; }
.setup-strip { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; color: #b8b4c8; font-size: 12px; }
.setup-strip span { border: 1px solid #292938; border-radius: 999px; padding: 6px 9px; background: #171722; }
.section-heading { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 14px; }
.section-heading .section-title { margin-bottom: 0; }
.source-caption { color: #9693a7; font-size: 12px; white-space: nowrap; }
.source-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.source-table { width: 100%; min-width: 590px; border-collapse: collapse; font-size: 13px; }
.source-table th, .source-table td { padding: 11px 12px; border-bottom: 1px solid #292938; text-align: left; white-space: nowrap; }
.source-table th { color: #b8b4c8; font-size: 12px; font-weight: 650; }
.source-table tbody tr:last-child td { border-bottom: 0; }
.source-name { color: #f1eff8; font-weight: 600; }
.source-link { color: #c4a8ff; text-decoration: none; }
.source-link:hover { color: #dccbff; text-decoration: underline; }
.source-state, .search-state { display: inline-flex; align-items: center; gap: 6px; min-height: 22px; border-radius: 999px; font-size: 12px; font-weight: 650; }
.source-state { padding: 3px 8px; background: #20202b; color: #b8b4c8; }
.state-dot { width: 6px; height: 6px; border-radius: 50%; background: #9693a7; }
.source-state.is-ready { color: #a7efbd; background: #183125; }.source-state.is-ready .state-dot { background: #83e69c; }
.source-state.is-warning { color: #ffc66d; background: #3a2c1e; }.source-state.is-warning .state-dot { background: #ffc66d; }
.source-state.is-error { color: #ffb4ab; background: #3a1e22; }.source-state.is-error .state-dot { background: #ff9a92; }
.search-state { padding: 3px 8px; color: #c4a8ff; background: #28203e; }
.search-state.is-unavailable { color: #ffb4ab; background: #3a1e22; }.search-state.is-unsupported { color: #9693a7; background: #20202b; }
.search-state.is-empty, .search-state.is-degraded { color: #ffc66d; background: #3a2c1e; }
.empty { color: #9693a7; padding: 16px 0; }
.help-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px; color: #a5a2b5; font-size: 13px; line-height: 1.6; }
.help-grid p { margin: 0; }
@media (max-width: 760px) { .lunatv-page { padding: 18px; } .lunatv-header { flex-direction: column; align-items: stretch; } .lunatv-actions { justify-content: flex-start; } .section-heading { align-items: flex-start; flex-direction: column; gap: 4px; } }
@media (max-width: 760px) { .help-grid { grid-template-columns: 1fr; } }
</style>
