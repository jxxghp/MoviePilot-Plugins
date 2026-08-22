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
const selectedCandidates = ref({})
const tmdbSearching = ref({})

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
    const candidate = selectedCandidate(result)
    await apiCall('post', '/download', {
      source_key: result.source_key,
      vod_id: result.vod_id,
      media_id: `${result.source_key}:${result.vod_id}`,
      title: candidate?.title || result.normalized_title || result.title,
      year: candidate?.year || result.year,
      media_type: result.media_type,
      tmdb_id: candidate?.tmdb_id,
      tmdb_media_id: candidate?.media_id,
      episode,
    })
    notice.value = '已加入串行下载队列'
    await load()
  } catch (enqueueError) {
    error.value = enqueueError?.message || '加入下载队列失败'
  }
}

function resultKey(result) {
  return `${result.source_key}:${result.vod_id}`
}

function tmdbCandidates(result) {
  return result.association?.candidates || []
}

function selectedCandidate(result) {
  const candidates = tmdbCandidates(result)
  const selectedId = selectedCandidates.value[resultKey(result)] || result.association?.media_id
  return candidates.find(candidate => candidate.media_id === selectedId) || null
}

function selectCandidate(result, mediaId) {
  selectedCandidates.value = { ...selectedCandidates.value, [resultKey(result)]: mediaId }
}

async function searchTmdb(result) {
  const key = resultKey(result)
  tmdbSearching.value = { ...tmdbSearching.value, [key]: true }
  try {
    const response = await apiCall('post', '/tmdb/search', {
      title: result.search_title || result.title,
      year: result.year,
      media_type: result.media_type,
    })
    const candidates = unwrap(response) || []
    result.association = { ...(result.association || {}), candidates }
    const selected = result.association.media_id && candidates.some(item => item.media_id === result.association.media_id)
      ? result.association.media_id
      : candidates[0]?.media_id || ''
    selectCandidate(result, selected)
    notice.value = candidates.length ? `找到 ${candidates.length} 个 TMDB 候选` : '没有找到 TMDB 候选'
  } catch (searchError) {
    error.value = searchError?.message || 'TMDB 搜索失败'
  } finally {
    tmdbSearching.value = { ...tmdbSearching.value, [key]: false }
  }
}

function episodesFor(result) {
  if (!result.season_ambiguous) return result.episodes || []
  const candidate = selectedCandidate(result)
  const counts = candidate?.season_counts || {}
  const seasons = Object.keys(counts).map(Number).filter(season => counts[season] > 0).sort((a, b) => a - b)
  const total = seasons.reduce((sum, season) => sum + Number(counts[season] || 0), 0)
  if (!seasons.length || total !== (result.episodes || []).length) return result.episodes || []
  const mapped = []
  let offset = 0
  for (const season of seasons) {
    const count = Number(counts[season])
    for (let index = 0; index < count; index += 1) {
      mapped.push({ ...(result.episodes[offset + index] || {}), season, episode: index + 1, season_known: true })
    }
    offset += count
  }
  return mapped
}

function canEnqueue(result) {
  return !result.season_ambiguous || episodesFor(result).every(episode => episode.season_known !== false)
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
const directoryStatus = computed(() => status.value.directories || {})
const stateLabel = (state) => ({ pending: '排队中', running: '下载中', completed: '已完成', failed: '失败' }[state] || state)

onMounted(load)
</script>

<template>
  <div class="lunatv-page">
    <div class="lunatv-header">
      <div>
        <div class="lunatv-eyebrow">THIRD-PARTY CMS / M3U8</div>
        <h1>LunaTV 资源订阅</h1>
        <p>搜索、订阅、串行下载；播放继续交给既有 Emby。</p>
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

    <section class="setup-strip">
      <span>目录：{{ directoryStatus.configured_root || directoryStatus.auto_roots?.[0]?.download_path || '未配置' }}</span>
      <span>来源：{{ directoryStatus.source || '未配置' }}</span>
      <span>TMDB：{{ status.tmdb_association ? '自动关联' : '关闭' }}</span>
      <span>缓存：完成后才整理</span>
    </section>

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
            <small v-if="result.association?.status === 'matched'" class="matched">已关联 TMDB：{{ result.association.title || result.association.media_id }}</small>
            <small v-else-if="result.association?.status === 'unmatched'" class="muted">未匹配 TMDB，将按原始名称处理</small>
            <div class="association-row">
              <select
                v-if="tmdbCandidates(result).length"
                :value="selectedCandidates[resultKey(result)] || result.association?.media_id || tmdbCandidates(result)[0]?.media_id"
                aria-label="选择匹配的 TMDB 作品"
                @change="selectCandidate(result, $event.target.value)"
              >
                <option v-for="candidate in tmdbCandidates(result)" :key="candidate.media_id" :value="candidate.media_id">
                  {{ candidate.title || candidate.media_id }}<span v-if="candidate.year"> ({{ candidate.year }})</span>
                </option>
              </select>
              <button class="link-button" :disabled="tmdbSearching[resultKey(result)]" @click="searchTmdb(result)">
                {{ tmdbSearching[resultKey(result)] ? '搜索中…' : '重新搜索 TMDB' }}
              </button>
            </div>
            <small v-if="result.season_ambiguous" class="warning-text">检测到 {{ result.season_range?.[0] }}-{{ result.season_range?.[1] }} 季，但源地址没有季边界，暂不自动下载</small>
          </div>
          <div v-if="episodesFor(result).length" class="episode-list">
            <button v-for="episode in episodesFor(result)" :key="`${episode.season}-${episode.episode}-${episode.url}`" class="episode-button" :disabled="!canEnqueue(result)" :title="!canEnqueue(result) ? '请先选择能确定季边界的 TMDB 作品' : '加入串行队列'" @click="enqueue(result, episode)">
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
          <div><strong>{{ task.title }}</strong><small v-if="task.media_type === 'tv'">S{{ String(task.season).padStart(2, '0') }}E{{ String(task.episode).padStart(2, '0') }}</small><small v-else>电影</small></div>
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
        <div><strong>{{ item.title }}</strong><small>{{ item.mode === 'strm' ? 'STRM' : '本地下载' }}<span v-if="item.media_type === 'tv'"> · S{{ String(item.season).padStart(2, '0') }}E{{ String(item.episode).padStart(2, '0') }}</span></small></div>
        <small class="history-output" :title="item.output">{{ item.output }}</small>
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
.lunatv-actions, .search-row, .episode-list { display: flex; gap: 10px; align-items: center; }
.button, .episode-button { border: 0; border-radius: 10px; background: #8b5cf6; color: white; padding: 10px 16px; cursor: pointer; font-weight: 650; }
.button.secondary { background: #28203e; color: #c4a8ff; } .button:disabled { opacity: .55; cursor: default; }
.panel { background: #171722; border: 1px solid #292938; border-radius: 16px; padding: 18px; margin-bottom: 18px; }
.section-title { font-size: 17px; font-weight: 700; margin-bottom: 14px; } .muted, small { color: #9693a7; font-size: 12px; }
input { flex: 1; border: 1px solid #3a384a; background: #101018; color: #eee; border-radius: 10px; padding: 12px 14px; min-width: 0; }
.alert { border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; } .alert.error { color: #ffb4ab; background: #3a1e22; } .alert.success { color: #a7efbd; background: #183125; }
.setup-strip { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; color: #b8b4c8; font-size: 12px; }
.setup-strip span { border: 1px solid #292938; border-radius: 999px; padding: 6px 9px; background: #171722; }
.result-card { display: flex; justify-content: space-between; gap: 18px; align-items: center; border-top: 1px solid #292938; padding: 14px 0; } .result-card:first-child { border-top: 0; padding-top: 0; }
.result-main { display: grid; gap: 5px; } .matched { color: #a7efbd; } .warning-text { color: #ffc66d; } .association-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .association-row select { border: 1px solid #4b3b70; background: #101018; color: #d3c1ff; border-radius: 8px; padding: 6px 9px; max-width: 360px; } .episode-list { flex-wrap: wrap; justify-content: flex-end; } .episode-button { padding: 7px 10px; font-size: 12px; background: #2c2450; color: #d3c1ff; }
.episode-button:disabled { opacity: .45; cursor: not-allowed; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; } .source-row, .task-row { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-top: 1px solid #292938; } .source-row:first-of-type, .task-row:first-of-type { border-top: 0; }
.task-row div { display: flex; gap: 8px; align-items: center; } .task-actions { display: flex; align-items: center; gap: 10px; } .link-button { background: transparent; color: #c4a8ff; border: 0; cursor: pointer; padding: 0; } .status { font-size: 12px; color: #a5a2b5; } .status.completed { color: #83e69c; } .status.failed { color: #ff9a92; } .status.running { color: #ffc66d; } .history-output { max-width: 55%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty { color: #9693a7; padding: 16px 0; }
.help-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px; color: #a5a2b5; font-size: 13px; line-height: 1.6; }
.help-grid p { margin: 0; }
@media (max-width: 760px) { .lunatv-page { padding: 18px; } .lunatv-header, .result-card { flex-direction: column; align-items: stretch; } .lunatv-actions { justify-content: flex-start; } .grid { grid-template-columns: 1fr; } .episode-list { justify-content: flex-start; } }
@media (max-width: 760px) { .help-grid { grid-template-columns: 1fr; } }
</style>
