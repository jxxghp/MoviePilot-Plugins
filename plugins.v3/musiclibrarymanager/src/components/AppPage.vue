<script setup>
import { computed, inject, onMounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: '' },
  sourcePluginId: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})

const toast = inject('moviepilot:toast', null)
const confirm = inject('moviepilot:confirm', null)
const tab = ref('collection')
const query = ref('')
const artists = ref([])
const selectedArtist = ref(null)
const searchingArtists = ref(false)
const loading = ref(false)
const collections = ref([])
const completion = ref([])
const completionSummary = ref(null)
let artistGeneration = 0
const selectedCollection = ref('')
const completionSelections = ref({})
const jobs = ref([])
const tasks = ref([])
const selectedTask = ref(null)
const normalization = ref({ category: 'Artist Collection', artist: '', title: '艺术家合集', year: null, archive_root: '' })
const normalizationPlan = ref(null)
const status = ref(null)
const error = ref('')

const endpoint = path => `plugin/${props.pluginId}/${path}`
const artistTitle = computed(() => selectedArtist.value?.name || '尚未选择艺术家')
const selectedCompletionCount = computed(() => Object.values(completionSelections.value).filter(Boolean).length)

function message(kind, text) {
  if (toast?.[kind]) toast[kind](text)
  else error.value = text
}

async function searchArtists() {
  if (!query.value.trim()) return
  searchingArtists.value = true
  error.value = ''
  try {
    const data = await props.api.get(endpoint('artists/search'), { params: { query: query.value.trim(), limit: 20 } })
    artists.value = data?.items || []
  } catch (err) {
    console.error(err)
    message('error', '搜索 MusicBrainz 艺术家失败')
  } finally {
    searchingArtists.value = false
  }
}

function chooseArtist(artist) {
  artistGeneration += 1
  selectedArtist.value = artist
  collections.value = []
  completion.value = []
  completionSummary.value = null
  selectedCollection.value = ''
  completionSelections.value = {}
  normalization.value.artist = artist.name
}

async function loadCollections() {
  if (!selectedArtist.value) return
  const generation = artistGeneration
  const artist = selectedArtist.value
  loading.value = true
  error.value = ''
  try {
    const data = await props.api.get(endpoint(`artists/${artist.media_id}/collections`), {
      params: { limit: 8 },
    })
    if (generation !== artistGeneration) return
    collections.value = data?.items || []
    selectedCollection.value = collections.value[0]?.key || ''
    if (!collections.value.length) message('warning', '当前站点没有返回符合条件的艺术家大合集')
  } catch (err) {
    console.error(err)
    message('error', '加载艺术家合集失败')
  } finally {
    loading.value = false
  }
}

async function loadCompletion() {
  if (!selectedArtist.value) return
  const generation = artistGeneration
  const artist = selectedArtist.value
  loading.value = true
  error.value = ''
  try {
    const data = await props.api.get(endpoint(`artists/${artist.media_id}/completion`))
    if (generation !== artistGeneration) return
    completion.value = data?.items || []
    completionSummary.value = data
    const selections = {}
    completion.value.forEach((row, index) => {
      const exact = row.resources?.find(resource => resource.exact)
      if (exact) selections[index] = exact.key
    })
    completionSelections.value = selections
  } catch (err) {
    console.error(err)
    message('error', '加载缺失作品失败')
  } finally {
    loading.value = false
  }
}

async function downloadCollection() {
  if (!selectedCollection.value || !selectedArtist.value) return
  if (confirm && !(await confirm({ type: 'info', title: '下载艺术家大合集', content: '一次只提交当前选中的一个合集资源，是否继续？' }))) return
  loading.value = true
  try {
    const job = await props.api.post(endpoint('downloads/collection'), {
      artist_id: selectedArtist.value.media_id,
      artist_name: selectedArtist.value.name,
      candidate_key: selectedCollection.value,
    })
    selectedCollection.value = ''
    message(job?.failed ? 'warning' : 'success', job?.failed ? '提交失败，请检查宿主下载日志' : '艺术家大合集已提交下载')
    await loadJobs()
  } catch (err) {
    console.error(err)
    message('error', '提交合集下载失败')
  } finally {
    loading.value = false
  }
}

async function downloadCompletion() {
  if (!selectedArtist.value) return
  const items = completion.value.flatMap((row, index) => {
    const key = completionSelections.value[index]
    return key ? [{ media_id: row.media.media_id, candidate_key: key }] : []
  })
  if (!items.length) return
  if (confirm && !(await confirm({ type: 'info', title: '补全缺失作品', content: `将提交 ${items.length} 个已确认资源，是否继续？` }))) return
  loading.value = true
  try {
    const job = await props.api.post(endpoint('downloads/completion'), {
      artist_id: selectedArtist.value.media_id,
      artist_name: selectedArtist.value.name,
      items,
    })
    message(job?.failed ? 'warning' : 'success', `已提交 ${job?.submitted || 0} 项，失败 ${job?.failed || 0} 项`)
    completionSelections.value = {}
    await loadJobs()
  } catch (err) {
    console.error(err)
    message('error', '提交补全任务失败')
  } finally {
    loading.value = false
  }
}

async function loadJobs() {
  try { jobs.value = (await props.api.get(endpoint('jobs'))) || [] } catch (err) { console.error(err) }
}

async function loadTasks() {
  loading.value = true
  try { tasks.value = (await props.api.get(endpoint('normalization/tasks'))) || [] }
  catch (err) { console.error(err); message('error', '加载 qB 音乐任务失败') }
  finally { loading.value = false }
}

function chooseTask(task) {
  selectedTask.value = task
  normalizationPlan.value = null
  normalization.value.title = task.title || '艺术家合集'
}

async function previewNormalization() {
  if (!selectedTask.value) return
  loading.value = true
  try {
    const payload = {
      hash: selectedTask.value.hash,
      downloader: selectedTask.value.downloader,
      ...normalization.value,
      year: normalization.value.year ? Number(normalization.value.year) : null,
      archive_root: normalization.value.archive_root || null,
    }
    normalizationPlan.value = await props.api.post(endpoint('normalization/plan'), payload)
  } catch (err) {
    console.error(err)
    message('error', err?.message || '规范化计划失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try { status.value = await props.api.get(endpoint('status')) } catch (err) { console.error(err) }
  await loadJobs()
})
</script>

<template>
  <div class="music-manager" :class="{ compact }" data-glass-optical-surface data-glass-optical-mode="dynamic">
    <div class="hero">
      <div>
        <div class="text-h4 font-weight-bold">音乐资源管理</div>
        <div class="text-body-1 text-medium-emphasis mt-2">合集只下载一个基线资源；补全只处理媒体库确认缺失的官方作品。</div>
      </div>
      <VChip v-if="status" color="warning" variant="tonal">
        {{ status.enabled ? '资源命名：只读预览' : '请先在插件配置中启用' }}
      </VChip>
    </div>

    <VAlert v-if="error" type="error" variant="tonal" closable class="mb-4" @click:close="error = ''">{{ error }}</VAlert>

    <VCard variant="tonal" class="panel mb-4">
      <VCardTitle>选择 MusicBrainz 艺术家</VCardTitle>
      <VCardText>
        <div class="d-flex ga-2 align-start">
          <VTextField v-model="query" label="艺人名称" prepend-inner-icon="mdi-magnify" hide-details @keyup.enter="searchArtists" />
          <VBtn color="primary" height="56" :loading="searchingArtists" @click="searchArtists">搜索</VBtn>
        </div>
        <div v-if="artists.length" class="artist-grid mt-4">
          <VCard v-for="artist in artists" :key="artist.media_id" :color="selectedArtist?.media_id === artist.media_id ? 'primary' : undefined" variant="tonal" class="artist-card" @click="chooseArtist(artist)">
            <VAvatar size="48" color="surface-variant"><VImg v-if="artist.image_url" :src="artist.image_url" /><VIcon v-else icon="mdi-account-music" /></VAvatar>
            <div><div class="font-weight-bold">{{ artist.name }}</div><div class="text-caption">{{ [artist.artist_type, artist.country, artist.disambiguation].filter(Boolean).join(' · ') }}</div></div>
          </VCard>
        </div>
      </VCardText>
    </VCard>

    <VTabs v-model="tab" color="primary" class="mb-5">
      <VTab value="collection">下载艺术家大合集</VTab>
      <VTab value="completion">补全缺失作品</VTab>
      <VTab value="normalization" @click="loadTasks">资源命名预览</VTab>
      <VTab value="jobs">任务记录</VTab>
    </VTabs>

    <VWindow v-model="tab">
      <VWindowItem value="collection">
        <VCard variant="tonal" class="panel">
          <VCardTitle class="d-flex justify-space-between align-center"><span>{{ artistTitle }}的大合集资源</span><VBtn :disabled="!selectedArtist" :loading="loading" @click="loadCollections">搜索大合集</VBtn></VCardTitle>
          <VCardText>
            <VAlert type="info" variant="tonal" class="mb-4">一次只下载一个大合集，不自动补全。清单命中仅代表目录/文件名称有证据，不保证曲目或版本完整；年份范围仅列为可能包含。</VAlert>
            <VRadioGroup v-model="selectedCollection">
              <VExpansionPanels variant="accordion">
                <VExpansionPanel v-for="item in collections" :key="item.key">
                  <VExpansionPanelTitle>
                    <div class="d-flex align-center ga-3 flex-grow-1">
                      <VRadio :value="item.key" @click.stop />
                      <div class="flex-grow-1"><div class="font-weight-bold">{{ item.title }}</div><div class="text-caption">{{ item.site_name }} · 做种 {{ item.seeders }} · 文件 {{ item.coverage.file_count }}</div></div>
                      <VChip color="primary" size="small">清单命中 {{ item.coverage.confirmed_count }}</VChip>
                      <VChip color="warning" size="small">可能 {{ item.coverage.probable_count }}</VChip>
                    </div>
                  </VExpansionPanelTitle>
                  <VExpansionPanelText>
                    <div class="coverage-grid">
                      <div v-for="work in item.coverage.works" :key="work.media_id" class="coverage-row"><VChip :color="work.state === 'confirmed' ? 'success' : work.state === 'probable' ? 'warning' : 'default'" size="x-small">{{ work.state }}</VChip><span><strong>{{ work.title }}</strong><span class="text-caption text-medium-emphasis"> · {{ work.album_type }}<template v-if="work.year"> · {{ work.year }}</template></span></span><span class="text-caption text-medium-emphasis">{{ work.evidence || '合集文件清单未确认包含' }}</span></div>
                    </div>
                  </VExpansionPanelText>
                </VExpansionPanel>
              </VExpansionPanels>
            </VRadioGroup>
          </VCardText>
          <VCardActions class="justify-end"><VBtn color="primary" :disabled="!selectedCollection" :loading="loading" @click="downloadCollection">下载选中大合集</VBtn></VCardActions>
        </VCard>
      </VWindowItem>

      <VWindowItem value="completion">
        <VCard variant="tonal" class="panel">
          <VCardTitle class="d-flex justify-space-between"><span>{{ artistTitle }} · 缺失作品补全</span><VBtn :disabled="!selectedArtist" :loading="loading" @click="loadCompletion">扫描缺失作品</VBtn></VCardTitle>
          <VCardText>
            <VAlert type="info" variant="tonal" class="mb-4">仅显示媒体库明确确认缺失的官方 Album、EP、Single；状态未知的作品不会默认判定为缺失。</VAlert>
            <VAlert v-if="completionSummary" :type="completionSummary.library_status_complete ? 'info' : 'warning'" variant="tonal" class="mb-4">已存在 {{ completionSummary.present_count || 0 }} 项（默认不选）；状态未知 {{ completionSummary.unknown_count || 0 }} 项。{{ completionSummary.library_status_complete ? '音乐库清单已扫描，已存在不代表发行版本或曲目完整。' : '媒体库扫描未完成或未配置音乐库，未知作品不会下载。' }}</VAlert>
            <VTable density="comfortable">
              <thead><tr><th>作品</th><th>类别 / 年份</th><th>站点资源</th></tr></thead>
              <tbody>
                <tr v-for="(row, index) in completion" :key="row.media.media_id">
                  <td><div class="font-weight-medium">{{ row.media.title }}</div><div class="text-caption">{{ row.media.artists?.join(' / ') }}</div></td>
                  <td>{{ row.media.album_type }} · {{ row.media.year || '-' }}</td>
                  <td><VSelect v-model="completionSelections[index]" :items="row.resources.filter(resource => resource.exact)" item-title="title" item-value="key" label="选择精确资源" clearable hide-details><template #item="{ props: itemProps, item }"><VListItem v-bind="itemProps" :subtitle="`${item.raw.site_name} · 做种 ${item.raw.seeders}`" /></template></VSelect><span class="text-caption">{{ row.resources.filter(resource => !resource.exact).length }} 个未确认候选不参与下载</span></td>
                </tr>
              </tbody>
            </VTable>
          </VCardText>
          <VCardActions class="justify-end"><VBtn color="primary" :disabled="!selectedCompletionCount" :loading="loading" @click="downloadCompletion">下载选中缺失作品（{{ selectedCompletionCount }}）</VBtn></VCardActions>
        </VCard>
      </VWindowItem>

      <VWindowItem value="normalization">
        <div class="normalization-grid">
          <VCard variant="tonal" class="panel">
            <VCardTitle class="d-flex justify-space-between"><span>qB 音乐任务</span><VBtn size="small" :loading="loading" @click="loadTasks">刷新</VBtn></VCardTitle>
            <VList lines="two"><VListItem v-for="task in tasks" :key="`${task.downloader}:${task.hash}`" :active="selectedTask?.hash === task.hash" :title="task.title" :subtitle="task.content_path" @click="chooseTask(task)" /></VList>
          </VCard>
          <VCard variant="tonal" class="panel">
            <VCardTitle>手工命名预览（不执行）</VCardTitle>
            <VCardText>
              <VSelect v-model="normalization.category" :items="['Album', 'EP', 'Single', 'Artist Collection']" label="MusicBrainz 主类别" />
              <VTextField v-model="normalization.artist" label="标准艺人" />
              <VTextField v-model="normalization.title" label="标准作品名" />
              <VTextField v-model="normalization.year" label="年份（可选）" type="number" />
              <VTextField v-model="normalization.archive_root" label="归档根目录（留空则保持原位置）" placeholder="/volume1/UT/Musics" />
              <VAlert v-if="normalizationPlan" :type="normalizationPlan.executable ? 'success' : 'warning'" variant="tonal">
                <div>当前：{{ normalizationPlan.current_content_path }}</div><div>目标：{{ normalizationPlan.target_content_path }}</div><div v-if="normalizationPlan.message" class="mt-2">{{ normalizationPlan.message }}</div>
              </VAlert>
            </VCardText>
            <VCardActions class="justify-end"><VBtn :disabled="!selectedTask" :loading="loading" @click="previewNormalization">预览路径</VBtn></VCardActions>
          </VCard>
        </div>
      </VWindowItem>

      <VWindowItem value="jobs">
        <VCard variant="tonal" class="panel"><VCardTitle class="d-flex justify-space-between"><span>插件任务记录</span><VBtn size="small" @click="loadJobs">刷新</VBtn></VCardTitle><VTable><thead><tr><th>时间</th><th>艺术家</th><th>模式</th><th>状态</th><th>结果</th></tr></thead><tbody><tr v-for="job in jobs" :key="job.job_id"><td>{{ job.created_at }}</td><td>{{ job.artist_name }}</td><td>{{ job.kind === 'collection' ? '大合集' : '缺失补全' }}</td><td><VChip :color="job.failed ? 'warning' : 'success'" size="small">{{ job.state }}</VChip></td><td>{{ job.submitted }}/{{ job.total }}</td></tr></tbody></VTable></VCard>
      </VWindowItem>
    </VWindow>
  </div>
</template>

<style scoped>
.music-manager { padding: 24px; min-height: 100%; }
.music-manager.compact { padding: 8px; }
.hero { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.panel { border: 1px solid rgba(var(--v-theme-on-surface), .12); backdrop-filter: blur(18px); }
.artist-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.artist-card { display: flex; gap: 12px; align-items: center; padding: 12px; cursor: pointer; }
.coverage-grid { display: grid; gap: 7px; max-height: 360px; overflow: auto; }
.coverage-row { display: grid; grid-template-columns: 72px minmax(170px, 1fr) 2fr; gap: 10px; align-items: center; }
.normalization-grid { display: grid; grid-template-columns: minmax(340px, 1fr) minmax(420px, 1fr); gap: 16px; }
@media (max-width: 900px) { .normalization-grid { grid-template-columns: 1fr; } .hero { align-items: flex-start; flex-direction: column; } }
</style>
