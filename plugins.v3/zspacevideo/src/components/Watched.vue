<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  base: { type: String, default: 'plugin/ZSpaceVideo' },
})

const items = ref([])
const meta = ref({})
const settings = ref({})
const history = ref([])
const loading = ref(false)
const syncing = ref(false)
const error = ref('')
const notice = ref('')
const expanded = ref({})

const dialog = ref(false)
const target = ref(null)
const mode = ref('library')
const selected = ref([])
const confirmUnknown = ref(false)
const plan = ref(null)
const previewing = ref(false)
const executing = ref(false)
const result = ref(null)

const MODE_LABELS = { none: '不删', library: '只从库里移除', full: '真删除' }
const MODE_HINTS = {
  library: '删掉库里的入口（硬链接），下载目录里的文件继续做种，不腾空间。极影视里这部片会消失。',
  full: '库入口、下载目录里的做种文件、qB 任务（含辅种）一起删，腾出空间。删了只能重新下载。',
}

function unwrap(res) {
  if (res && typeof res === 'object' && 'success' in res) {
    if (!res.success) throw new Error(res.message || '请求失败')
    return res.data
  }
  return res
}

function fmtSize(n) {
  n = Number(n) || 0
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`
}
function fmtTime(ts) { return ts ? new Date(ts * 1000).toLocaleString() : '' }
function itemTitle(it) {
  if (it.kind === 'season' && !String(it.title || '').includes(`第 ${it.season} 季`)) return `${it.title} 第 ${it.season} 季`
  return it.title
}
function roleLabel(r) { return r === 'library' ? '库' : r === 'download' ? '下载目录' : '其它' }
function shortPath(p) {
  const s = String(p || '')
  return s.length > 90 ? '…' + s.slice(-88) : s
}

const autoText = computed(() => {
  const m = settings.value.watched_auto_mode || 'none'
  if (m === 'none') return '自动删除：关闭（不删）'
  return `自动删除：${MODE_LABELS[m]}，已看满 ${settings.value.watched_buffer_days} 天后执行`
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = unwrap(await props.api.get(`${props.base}/watched`)) || {}
    items.value = data.items || []
    meta.value = data.meta || {}
    settings.value = data.settings || {}
    history.value = unwrap(await props.api.get(`${props.base}/watched/history`)) || []
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function sync() {
  syncing.value = true
  error.value = ''
  try {
    const out = unwrap(await props.api.post(`${props.base}/watched/sync`, {}))
    notice.value = `已读取极影视：共 ${out.count} 个已看${out.added?.length ? `，新增 ${out.added.length}` : ''}${out.removed?.length ? `，取消 ${out.removed.length}` : ''}`
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    syncing.value = false
  }
}

function openDelete(it, version) {
  target.value = it
  selected.value = version ? [version.id] : (it.versions || []).filter(v => v.traced).map(v => v.id)
  mode.value = 'library'
  confirmUnknown.value = false
  plan.value = null
  result.value = null
  dialog.value = true
  preview()
}

// 每次预览一个序号：只认最后一次请求的结果，旧请求晚到时丢掉（否则按钮写的删除方式和实际清单可能不一致）
let previewSeq = 0

// 换版本或删除方式：要删的文件变了，「确认季号」必须对新清单重新勾选
function selectionChanged() {
  confirmUnknown.value = false
  preview()
}

async function preview() {
  const seq = ++previewSeq
  plan.value = null
  if (!target.value || !selected.value.length) { previewing.value = false; return }
  previewing.value = true
  error.value = ''
  try {
    const data = unwrap(await props.api.post(`${props.base}/watched/preview`, {
      key: target.value.key, mode: mode.value, version_ids: selected.value,
      confirm_unknown_season: confirmUnknown.value === true,
    }))
    if (seq === previewSeq) plan.value = data
  } catch (e) {
    if (seq === previewSeq) error.value = e.message || String(e)
  } finally {
    if (seq === previewSeq) previewing.value = false
  }
}

async function execute() {
  if (!plan.value) return
  executing.value = true
  try {
    result.value = unwrap(await props.api.post(`${props.base}/watched/execute`, { plan_id: plan.value.id }))
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    executing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <VAlert v-if="error" type="error" variant="tonal" class="mb-3" closable @click:close="error = ''">{{ error }}</VAlert>
    <VAlert v-if="notice" type="success" variant="tonal" class="mb-3" closable @click:close="notice = ''">{{ notice }}</VAlert>

    <div class="d-flex flex-wrap align-center ga-3 mb-3">
      <VChip variant="tonal" :color="(settings.watched_auto_mode || 'none') === 'none' ? 'grey' : 'warning'">{{ autoText }}</VChip>
      <span class="text-caption">上次读取 {{ fmtTime(meta.last_sync_at) || '—' }}</span>
      <span v-if="meta.last_sync_errors?.length" class="text-caption text-error">读取有错：{{ meta.last_sync_errors.join('；') }}</span>
      <VSpacer />
      <VBtn size="small" variant="tonal" prepend-icon="mdi-eye-refresh-outline" :loading="syncing" @click="sync">立即读取已看</VBtn>
      <VBtn size="small" variant="text" icon="mdi-refresh" :loading="loading" aria-label="刷新列表" @click="load" />
    </div>
    <p class="text-caption text-medium-emphasis mb-3">
      电影以极影视「已看过」为准；剧集只认对整季点的「已看过」，单集看完不算。库里的入口和下载目录里做种的文件是同一份数据，只移出库不腾空间。
    </p>

    <div v-if="!items.length" class="text-medium-emphasis pa-4">{{ loading ? '读取中…' : '极影视里还没有标记已看的影片' }}</div>

    <VCard v-for="it in items" :key="it.key" variant="outlined" class="mb-3">
      <VCardItem>
        <VCardTitle class="text-subtitle-1 d-flex flex-wrap align-center ga-2">
          {{ itemTitle(it) }}
          <span v-if="it.year" class="text-caption">({{ it.year }})</span>
          <VChip size="x-small" variant="tonal">{{ it.library_name }}</VChip>
          <VChip v-if="it.done_at" size="x-small" color="success" variant="tonal">已处理：{{ MODE_LABELS[it.done_mode] }} {{ fmtTime(it.done_at) }}</VChip>
        </VCardTitle>
        <VCardSubtitle>
          首次发现已看 {{ fmtTime(it.first_seen_at) }}
          <template v-if="!it.done_at">· 缓冲期还剩 {{ it.due_in_days }} 天</template>
          · {{ (it.versions || []).length }} 个版本，共 {{ fmtSize(it.total_size) }}
          <span v-if="it.last_error" class="text-error"> · {{ it.last_error }}</span>
        </VCardSubtitle>
        <template #append>
          <VBtn size="small" color="error" variant="tonal" :disabled="!(it.versions || []).some(v => v.traced)" @click="openDelete(it)">删除…</VBtn>
        </template>
      </VCardItem>
      <VCardText>
        <div v-if="it.error" class="text-error text-caption">{{ it.error }}</div>
        <VTable density="compact">
          <thead><tr><th>版本</th><th>大小</th><th>做种</th><th>站点</th><th /></tr></thead>
          <tbody>
            <template v-for="v in it.versions" :key="v.id">
              <tr>
                <td>
                  <a href="#" class="text-body-2" @click.prevent="expanded[v.id] = !expanded[v.id]">{{ v.label }}</a>
                  <VChip v-if="v.in_library" size="x-small" color="primary" variant="tonal" class="ms-1">库里</VChip>
                  <VChip v-else size="x-small" variant="tonal" class="ms-1">只在下载目录</VChip>
                  <VChip v-if="!v.traced" size="x-small" color="warning" variant="tonal" class="ms-1">记录追溯不到</VChip>
                  <VChip v-if="v.season_unknown_count" size="x-small" color="warning" variant="tonal" class="ms-1">{{ v.season_unknown_count }} 个文件认不出季号</VChip>
                </td>
                <td>{{ v.size_text }}</td>
                <td>
                  <span v-if="!v.torrents.length" class="text-medium-emphasis">无任务</span>
                  <span v-else>{{ v.seeding ? '做种中' : '已停止' }} · {{ v.torrents.length }} 个任务<span v-if="v.torrents.length > 1">（辅种）</span></span>
                </td>
                <td class="text-caption">{{ [...new Set([v.site, ...v.torrents.map(t => t.site)].filter(Boolean))].join('、') || '—' }}</td>
                <td><VBtn v-if="v.traced" size="x-small" variant="text" color="error" @click="openDelete(it, v)">删这个版本</VBtn></td>
              </tr>
              <tr v-if="expanded[v.id]">
                <td colspan="5" class="pb-3">
                  <div v-for="f in v.files" :key="f.path" class="text-caption">
                    <VChip size="x-small" variant="outlined" class="me-1">{{ roleLabel(f.role) }}</VChip>
                    <span :class="{ 'text-disabled': !f.exists }">{{ shortPath(f.path) }}</span>
                    · {{ fmtSize(f.size) }}
                    <span v-if="f.links && f.links.length > 1"> · 同一份数据 {{ f.links.length }} 个入口</span>
                    <span v-if="!f.exists" class="text-error"> · 已不存在</span>
                    <span v-if="f.exists && f.season_unknown" class="text-warning"> · 认不出季号</span>
                  </div>
                  <div v-for="t in v.torrents" :key="t.hash" class="text-caption mt-1">
                    <VChip size="x-small" variant="outlined" class="me-1">qB</VChip>{{ t.name }} · {{ t.site || '?' }} · {{ t.state }} · {{ t.hash.slice(0, 8) }}
                    <span v-if="t.foreign_media?.length" class="text-warning"> · 种子里还有 {{ t.foreign_media.length }} 个别的视频</span>
                  </div>
                  <div v-for="n in v.notes" :key="n" class="text-caption text-medium-emphasis">{{ n }}</div>
                </td>
              </tr>
            </template>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>

    <VCard v-if="history.length" variant="outlined" class="mt-4">
      <VCardTitle class="text-subtitle-1">删除记录</VCardTitle>
      <VCardText>
        <VTable density="compact">
          <thead><tr><th>时间</th><th>影片</th><th>方式</th><th>结果</th></tr></thead>
          <tbody>
            <tr v-for="h in history.slice(0, 30)" :key="h.plan_id + h.started_at">
              <td class="text-caption">{{ fmtTime(h.started_at) }}</td>
              <td>{{ h.title }}</td>
              <td class="text-caption">{{ h.mode_label }}（{{ h.trigger === 'auto' ? '自动' : '手动' }}）</td>
              <td class="text-caption">
                {{ h.status === 'done' ? '完成' : h.status === 'aborted' ? '未执行' : '部分失败' }}：删 {{ (h.deleted || []).length }} 个文件<span v-if="(h.torrents_removed || []).length">、{{ h.torrents_removed.length }} 个种子</span>，腾出 {{ h.freed_text }}
                <div v-if="(h.failed || []).length" class="text-error">{{ h.failed.join('；') }}</div>
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>

    <VDialog v-model="dialog" max-width="900" scrollable>
      <VCard v-if="target">
        <VCardTitle>删除：{{ itemTitle(target) }}</VCardTitle>
        <VCardText>
          <div class="mb-2 text-subtitle-2">选版本</div>
          <VCheckbox v-for="v in target.versions.filter(x => x.traced)" :key="v.id" v-model="selected" :value="v.id"
                     density="compact" hide-details :disabled="!!result" @update:model-value="selectionChanged">
            <template #label>{{ v.label }}（{{ v.size_text }}{{ v.in_library ? '，库里' : '，只在下载目录' }}）</template>
          </VCheckbox>
          <div class="mt-3 mb-1 text-subtitle-2">删除方式</div>
          <VRadioGroup v-model="mode" inline hide-details :disabled="!!result" @update:model-value="selectionChanged">
            <VRadio label="只从库里移除" value="library" />
            <VRadio label="真删除（含做种）" value="full" color="error" />
          </VRadioGroup>
          <p class="text-caption text-medium-emphasis mb-3">{{ MODE_HINTS[mode] }}</p>

          <VProgressLinear v-if="previewing" indeterminate class="mb-2" />
          <template v-if="plan && !result">
            <VAlert :type="plan.freed_bytes ? 'warning' : 'info'" variant="tonal" class="mb-2">
              将删除 {{ plan.actions.length }} 个文件<span v-if="plan.torrents.length">、{{ plan.torrents.length }} 个 qB 任务</span>，
              腾出 <b>{{ plan.freed_text }}</b>
            </VAlert>
            <VAlert v-if="plan.unknown_season && plan.unknown_season.count" type="warning" variant="outlined" density="compact" class="mb-2">
              <div>
                有 <b>{{ plan.unknown_season.count }}</b> 个文件（{{ plan.unknown_season.size_text }}）路径里认不出季号（蓝光原盘之类），
                <template v-if="plan.unknown_season.confirmed">已按你的确认纳入这次删除。</template>
                <template v-else>{{ mode === 'full' ? '这些文件所在的版本连同种子这次都不删' : '这些库入口这次不移出' }}。</template>
              </div>
              <div v-for="d in plan.unknown_season.dirs" :key="d.dir" class="text-caption">· {{ shortPath(d.dir) }}：{{ d.count }} 个，{{ d.size_text }}</div>
              <VCheckbox v-model="confirmUnknown" density="compact" hide-details color="error" :disabled="!!result"
                         @update:model-value="preview">
                <template #label>我确认这些文件属于第 {{ plan.unknown_season.season }} 季，一起{{ mode === 'full' ? '删除' : '移出库' }}</template>
              </VCheckbox>
              <div class="text-caption text-medium-emphasis">自动删除永远不会删这类文件，只能在这里手动确认。</div>
            </VAlert>
            <div v-for="w in plan.warnings" :key="w" class="text-caption text-warning">· {{ w }}</div>
            <div v-for="w in plan.skipped" :key="w" class="text-caption text-medium-emphasis">· 跳过：{{ w }}</div>
            <div class="mt-2 text-subtitle-2">文件</div>
            <div v-for="a in plan.actions" :key="a.path" class="text-caption">
              <VChip size="x-small" variant="outlined" class="me-1">{{ roleLabel(a.role) }}</VChip>{{ shortPath(a.path) }} · {{ fmtSize(a.size) }}
              <span v-if="a.nlink > 1"> · {{ a.nlink }} 个入口</span>
            </div>
            <template v-if="plan.torrents.length">
              <div class="mt-2 text-subtitle-2">qB 任务（连同文件删除）</div>
              <div v-for="t in plan.torrents" :key="t.hash" class="text-caption">{{ t.site || '?' }} · {{ t.name }} · {{ t.hash.slice(0, 8) }}</div>
            </template>
          </template>
          <template v-if="result">
            <VAlert :type="result.status === 'done' ? 'success' : 'error'" variant="tonal" class="mb-2">
              {{ result.status === 'done' ? '完成' : result.status === 'aborted' ? '没有执行' : '部分失败' }}：
              删了 {{ result.deleted.length }} 个文件<span v-if="result.torrents_removed.length">、{{ result.torrents_removed.length }} 个种子</span>，腾出 {{ result.freed_text }}
            </VAlert>
            <div v-for="f in result.failed" :key="f" class="text-caption text-error">· {{ f }}</div>
            <div v-if="result.zvideo" class="text-caption">
              极影视：已刷新 {{ (result.zvideo.rescan_targets || []).length }} 个目录；
              {{ (result.zvideo.still_in_zvideo || []).length ? `还看得到 ${result.zvideo.still_in_zvideo.length} 个已删文件` : '已删的文件已不在条目里' }}
            </div>
          </template>
        </VCardText>
        <VCardActions>
          <VSpacer />
          <VBtn variant="text" @click="dialog = false">{{ result ? '关闭' : '取消' }}</VBtn>
          <VBtn v-if="!result" color="error" variant="flat" :loading="executing"
                :disabled="!plan || previewing || (!plan.actions.length && !plan.torrents.length)" @click="execute">
            确认{{ mode === 'full' ? '真删除' : '移出库' }}
          </VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>
