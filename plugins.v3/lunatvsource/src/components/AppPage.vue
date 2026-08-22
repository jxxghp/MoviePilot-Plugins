<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  navKey: { type: String, default: 'main' },
})

const query = ref('')
const searching = ref(false)
const syncing = ref(false)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const results = ref([])
const sources = ref([])
const tasks = ref([])
const history = ref([])
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
    const [statusResponse, sourceResponse, taskResponse, historyResponse] = await Promise.all([
      apiCall('get', '/status'),
      apiCall('get', '/sources'),
      apiCall('get', '/tasks'),
      apiCall('get', '/history'),
    ])
    status.value = unwrap(statusResponse)
    sources.value = unwrap(sourceResponse) || []
    tasks.value = unwrap(taskResponse) || []
    history.value = unwrap(historyResponse) || []
  } catch (loadError) {
    error.value = loadError?.message || '加载 LunaTV 状态失败'
  } finally {
    loading.value = false
  }
}

async function retry(task) {
  try {
    await apiCall('post', `/tasks/${task.task_id}/retry`)
    notice.value = '失败任务已重新排队'
    await load()
  } catch (retryError) {
    error.value = retryError?.message || '重新排队失败'
  }
}

async function search() {
  if (!query.value.trim() || searching.value) return
  searching.value = true
  error.value = ''
  notice.value = ''
  try {
    const response = await apiCall('post', '/search', { query: query.value.trim() })
    results.value = unwrap(response) || []
    notice.value = results.value.length ? `找到 ${results.value.length} 个结果` : '没有找到资源'
  } catch (searchError) {
    error.value = searchError?.message || '搜索失败'
  } finally {
    searching.value = false
  }
}

async function enqueue(result, episode) {
  error.value = ''
  try {
    await apiCall('post', '/download', {
      source_key: result.source_key,
      vod_id: result.vod_id,
      media_id: `${result.source_key}:${result.vod_id}`,
      title: result.title,
      year: result.year,
      media_type: result.media_type,
      episode,
    })
    notice.value = '已加入串行下载队列'
    await load()
  } catch (enqueueError) {
    error.value = enqueueError?.message || '加入下载队列失败'
  }
}

async function sync() {
  if (syncing.value) return
  syncing.value = true
  try {
    const response = await apiCall('post', '/sync')
    notice.value = unwrap(response)?.started === false ? '刷新正在执行' : '已开始刷新订阅'
  } catch (syncError) {
    error.value = syncError?.message || '刷新订阅失败'
  } finally {
    syncing.value = false
  }
}

const pendingTasks = computed(() => tasks.value.filter(task => task.state === 'pending').length)
const stateLabel = (state) => ({ pending: '排队中', running: '下载中', completed: '已完成', failed: '失败' }[state] || state)

onMounted(load)
</script>

<template>
  <div class="lunatv-page">
    <div class="lunatv-header">
      <div>
        <div class="lunatv-eyebrow">THIRD-PARTY CMS / M3U8</div>
        <h1>LunaTV 资源订阅</h1>
        <p>订阅、搜索、排队下载；播放交给既有 Emby，插件只负责资源接入和整理。</p>
      </div>
      <div class="header-status">
        <span class="chip">串行队列</span>
        <span :class="['chip', status.ai?.available ? 'ready' : 'muted-chip']">AI {{ status.ai?.available ? '已就绪' : '未启用' }}</span>
        <span :class="['chip', status.media_server_sync_running ? 'busy' : 'muted-chip']">媒体库 {{ status.media_server_sync_running ? '同步中' : '自动刷新' }}</span>
      </div>
      <div class="lunatv-actions">
        <button class="button secondary" :disabled="syncing" @click="sync">{{ syncing ? '刷新中…' : '刷新订阅' }}</button>
        <button class="button" :disabled="loading" @click="load">重新加载</button>
      </div>
    </div>

    <div v-if="error" class="alert error">{{ error }}</div>
    <div v-if="notice" class="alert success">{{ notice }}</div>

    <section class="panel search-panel">
      <div class="section-title">资源搜索</div>
      <form class="search-row" @submit.prevent="search">
        <input v-model="query" placeholder="搜索电影或剧集" aria-label="搜索电影或剧集" />
        <button class="button" :disabled="searching">{{ searching ? '搜索中…' : '搜索' }}</button>
      </form>
    </section>

    <section v-if="results.length" class="panel">
      <div class="section-title">搜索结果</div>
      <div class="result-list">
        <article v-for="result in results" :key="`${result.source_key}:${result.vod_id}`" class="result-card">
          <div class="result-main">
            <strong>{{ result.title }}<span v-if="result.year"> ({{ result.year }})</span></strong>
            <small>{{ result.source_name }} · {{ result.media_type === 'tv' ? '电视剧' : '电影' }}</small>
          </div>
          <div v-if="result.episodes?.length" class="episode-list">
            <button v-for="episode in result.episodes" :key="`${episode.season}-${episode.episode}-${episode.url}`" class="episode-button" @click="enqueue(result, episode)">
              {{ result.media_type === 'tv' ? `S${String(episode.season).padStart(2, '0')}E${String(episode.episode).padStart(2, '0')}` : '下载' }}
            </button>
          </div>
          <small v-else class="muted">该结果没有可用播放地址</small>
        </article>
      </div>
    </section>

    <div class="grid">
      <section class="panel">
        <div class="section-title">资源站 <span class="muted">{{ sources.length }}</span></div>
        <div v-if="!sources.length" class="empty">暂未读取到资源站配置</div>
        <div v-for="source in sources" :key="source.key" class="source-row">
          <span>{{ source.name }}</span><small>{{ source.key }}</small>
        </div>
      </section>
      <section class="panel">
        <div class="section-title">下载队列 <span class="muted">待处理 {{ pendingTasks }}</span></div>
        <div v-if="!tasks.length" class="empty">暂无任务</div>
        <div v-for="task in tasks.slice(0, 12)" :key="task.task_id" class="task-row">
          <div><strong>{{ task.title }}</strong><small>S{{ String(task.season).padStart(2, '0') }}E{{ String(task.episode).padStart(2, '0') }}</small></div>
          <div class="task-actions">
            <span :class="['status', task.state]">{{ stateLabel(task.state) }}</span>
            <button v-if="task.state === 'failed'" class="link-button" @click="retry(task)">重试</button>
          </div>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="section-title">整理历史 <span class="muted">最近 {{ Math.min(history.length, 12) }} 条</span></div>
      <div v-if="!history.length" class="empty">暂无已完成记录</div>
      <div v-for="item in history.slice(0, 12)" :key="item.task_id" class="task-row">
        <div><strong>{{ item.title }}</strong><small>{{ item.mode === 'strm' ? 'STRM' : '本地下载' }} · S{{ String(item.season).padStart(2, '0') }}E{{ String(item.episode).padStart(2, '0') }}</small></div>
        <small class="history-output" :title="item.output">{{ item.output }}</small>
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
.lunatv-actions, .search-row, .episode-list { display: flex; gap: 10px; align-items: center; }
.button, .episode-button { border: 0; border-radius: 10px; background: #8b5cf6; color: white; padding: 10px 16px; cursor: pointer; font-weight: 650; }
.button.secondary { background: #28203e; color: #c4a8ff; } .button:disabled { opacity: .55; cursor: default; }
.panel { background: #171722; border: 1px solid #292938; border-radius: 16px; padding: 18px; margin-bottom: 18px; }
.section-title { font-size: 17px; font-weight: 700; margin-bottom: 14px; } .muted, small { color: #9693a7; font-size: 12px; }
input { flex: 1; border: 1px solid #3a384a; background: #101018; color: #eee; border-radius: 10px; padding: 12px 14px; min-width: 0; }
.alert { border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; } .alert.error { color: #ffb4ab; background: #3a1e22; } .alert.success { color: #a7efbd; background: #183125; }
.result-card { display: flex; justify-content: space-between; gap: 18px; align-items: center; border-top: 1px solid #292938; padding: 14px 0; } .result-card:first-child { border-top: 0; padding-top: 0; }
.result-main { display: grid; gap: 5px; } .episode-list { flex-wrap: wrap; justify-content: flex-end; } .episode-button { padding: 7px 10px; font-size: 12px; background: #2c2450; color: #d3c1ff; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; } .source-row, .task-row { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-top: 1px solid #292938; } .source-row:first-of-type, .task-row:first-of-type { border-top: 0; }
.task-row div { display: flex; gap: 8px; align-items: center; } .task-actions { display: flex; align-items: center; gap: 10px; } .link-button { background: transparent; color: #c4a8ff; border: 0; cursor: pointer; padding: 0; } .status { font-size: 12px; color: #a5a2b5; } .status.completed { color: #83e69c; } .status.failed { color: #ff9a92; } .status.running { color: #ffc66d; } .history-output { max-width: 55%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty { color: #9693a7; padding: 16px 0; }
@media (max-width: 760px) { .lunatv-page { padding: 18px; } .lunatv-header, .result-card { flex-direction: column; align-items: stretch; } .lunatv-actions { justify-content: flex-start; } .grid { grid-template-columns: 1fr; } .episode-list { justify-content: flex-start; } }
</style>
