<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['close'])

const loading = ref(false)
const error = ref('')
const notice = ref('')
const items = ref([])
const libraries = ref([])
const directoryRules = ref([])
const rulesReady = ref(false)
const rulesMessage = ref('')
const monitoringEnabled = ref(false)
const monitoringRules = ref([])
const incomingPath = ref('')
const settingsUrl = ref('#/setting')
const rulesExpanded = ref(false)
const helpOpen = ref(false)
const selectedKeys = ref([])
const batchRunning = ref(false)
const batchCurrent = ref(0)
const batchTotal = ref(0)
const savingKeys = ref([])
const organizingKey = ref('')
const tmdbLoadingKeys = ref([])
const tmdbSearchedKeys = ref([])
const tmdbSearchFailedKeys = ref([])
const tmdbCandidates = ref({})
const selectedCandidates = ref({})
const rowErrors = ref({})
let fileTransferSource = null
const fileTransferText = ref('')
const fileTransferValue = ref(null)
const fileTransferSeenActive = ref(false)
const ignoredSystemEntries = new Set([
  '#recycle',
  '@eadir',
  '.ds_store',
  'thumbs.db',
  'desktop.ini',
])

const hasItems = computed(() => items.value.length > 0)
const reviewSummary = computed(() => (
  hasItems.value ? `${items.value.length} 项待处理` : '检查名称与目标后再整理'
))
const directoryStatus = computed(() => {
  if (!directoryRules.value.length) return '未读取到目录规则'
  return rulesReady.value
    ? `已读取 ${directoryRules.value.length} 条目录规则`
    : '目录规则需要处理'
})
const monitoringRuleText = computed(() => (
  monitoringRules.value.length ? `“${monitoringRules.value.join('”“')}”` : '相关目录规则'
))
const queueableItems = computed(() => items.value.filter(item => canQueue(item)))
const selectedQueueableItems = computed(() => (
  queueableItems.value.filter(item => selectedKeys.value.includes(item.raw_title))
))
const allQueueableSelected = computed(() => (
  queueableItems.value.length > 0
  && selectedQueueableItems.value.length === queueableItems.value.length
))
const someQueueableSelected = computed(() => (
  selectedQueueableItems.value.length > 0 && !allQueueableSelected.value
))

function unwrap(response) {
  const body = response && Object.prototype.hasOwnProperty.call(response, 'success')
    ? response
    : (response?.data ?? response)
  if (body?.success === false) {
    throw new Error(body.message || '请求失败')
  }
  return body?.data ?? body ?? {}
}

function isIgnoredSystemItem(item) {
  const rawTitle = String(item?.raw_title || '').trim().toLowerCase()
  return rawTitle.startsWith('.') || ignoredSystemEntries.has(rawTitle)
}

function visibleReviewItems(data) {
  const rows = Array.isArray(data) ? data : (data?.items || [])
  return Array.isArray(rows) ? rows.filter(item => !isIgnoredSystemItem(item)) : []
}

function errorMessage(errorValue, fallback) {
  return errorValue?.message || fallback
}

async function openMoviePilotSettings() {
  const target = settingsUrl.value || '#/setting'
  emit('close')
  await nextTick()
  window.location.assign(target)
}

function rowErrorFor(row) {
  return rowErrors.value[row.raw_title] || ''
}

function setRowError(row, msg) {
  if (msg) {
    rowErrors.value = { ...rowErrors.value, [row.raw_title]: msg }
  } else {
    const next = { ...rowErrors.value }
    delete next[row.raw_title]
    rowErrors.value = next
  }
}

function clearRowError(row) {
  setRowError(row, '')
}

function hasKey(refValue, key) {
  return refValue.value.includes(key)
}

function addKey(refValue, key) {
  if (!refValue.value.includes(key)) {
    refValue.value = [...refValue.value, key]
  }
}

function removeKey(refValue, key) {
  refValue.value = refValue.value.filter(item => item !== key)
}

function sanitizeProgressText(value) {
  return (typeof value === 'string' ? value : '').trim()
}

function stopFileTransferProgress() {
  if (!fileTransferSource) {
    return
  }
  fileTransferSource.close()
  fileTransferSource = null
}

function startFileTransferProgress() {
  stopFileTransferProgress()
  fileTransferText.value = '正在校验目录并生成目标名称…'
  fileTransferValue.value = null
  fileTransferSeenActive.value = false
  try {
    const source = new EventSource('/api/v1/system/progress/filetransfer', {
      withCredentials: true,
    })
    source.onmessage = event => {
      let payload
      try {
        payload = JSON.parse(event.data)
      } catch {
        return
      }
      if (!payload || typeof payload !== 'object' || typeof payload.enable !== 'boolean') {
        return
      }
      if (payload.enable) {
        fileTransferSeenActive.value = true
        if (typeof payload.text === 'string' && payload.text.trim()) {
          fileTransferText.value = sanitizeProgressText(payload.text)
        }
        if (Number.isFinite(payload.value)) {
          const clipped = Math.max(0, Math.min(100, Number(payload.value)))
          fileTransferValue.value = Math.round(clipped)
        } else {
          fileTransferValue.value = null
        }
        return
      }
      if (fileTransferSeenActive.value) {
        fileTransferText.value = '文件移动完成，正在写入整理记录…'
        fileTransferValue.value = 100
      }
    }
    source.onerror = () => {
      // keep fallback indeterminate if EventSource is unavailable
    }
    fileTransferSource = source
  } catch {
    // fallback to local text/value only
  }
}

async function loadReview() {
  loading.value = true
  error.value = ''
  rowErrors.value = {}
  try {
    const response = await props.api.get('plugin/CourseOrganizer/review')
    const data = unwrap(response)
    items.value = visibleReviewItems(data)
    if (Array.isArray(data?.libraries) && data.libraries.length) {
      libraries.value = data.libraries
    } else {
      libraries.value = []
    }
    directoryRules.value = Array.isArray(data?.directory_rules) ? data.directory_rules : []
    rulesReady.value = Boolean(data?.rules_ready)
    rulesMessage.value = data?.rules_message || ''
    monitoringEnabled.value = Boolean(data?.monitoring_enabled)
    monitoringRules.value = Array.isArray(data?.monitoring_rules) ? data.monitoring_rules : []
    incomingPath.value = data?.incoming_path || ''
    settingsUrl.value = data?.settings_url || '#/setting'
    const restoredCandidates = {}
    const restoredSelections = {}
    for (const row of items.value) {
      const candidate = row?.selected_candidate
      const candidateKey = row?.selected_candidate_key || candidate?.candidate_key || ''
      if (candidate?.candidate_key && candidate.candidate_key === candidateKey) {
        restoredCandidates[row.raw_title] = [candidate]
        restoredSelections[row.raw_title] = candidateKey
      }
    }
    tmdbCandidates.value = restoredCandidates
    selectedCandidates.value = restoredSelections
    selectedKeys.value = []
  } catch (loadError) {
    error.value = errorMessage(loadError, '加载人工复核列表失败')
  } finally {
    loading.value = false
  }
}

async function refreshReview() {
  if (batchRunning.value) return
  loading.value = true
  error.value = ''
  try {
    await props.api.post('plugin/CourseOrganizer/review/refresh')
    await loadReview()
    notice.value = '预览已重新扫描'
  } catch (refreshError) {
    error.value = errorMessage(refreshError, '刷新预览失败，请检查源目录后重试')
  } finally {
    loading.value = false
  }
}

async function searchTmdb(row, silent = false) {
  if (batchRunning.value || isSaving(row) || isTmdbLoading(row)) return
  addKey(tmdbLoadingKeys, row.raw_title)
  error.value = ''
  if (!silent) notice.value = ''
  clearRowError(row)
  removeKey(tmdbSearchFailedKeys, row.raw_title)
  const selectedKey = selectedCandidateFor(row) || row.selected_candidate_key || ''
  const selectedCandidate = row.selected_candidate
  try {
    const response = await props.api.post('plugin/CourseOrganizer/review/tmdb/search', {
      raw_title: row.raw_title,
      revision: row.revision,
      search_name: (row.final_title && row.final_title.trim()) || row.raw_title,
    })
    const data = unwrap(response)
    let candidates = Array.isArray(data?.items) ? data.items : []
    if (
      selectedKey
      && selectedCandidate?.candidate_key === selectedKey
      && !candidates.some(candidate => candidate.candidate_key === selectedKey)
    ) {
      candidates = [selectedCandidate, ...candidates]
    }
    tmdbCandidates.value = { ...tmdbCandidates.value, [row.raw_title]: candidates }
    if (!silent) notice.value = data?.message || '已找到 TMDB 候选'
  } catch (searchError) {
    addKey(tmdbSearchFailedKeys, row.raw_title)
    if (!silent) setRowError(row, errorMessage(searchError, '搜索 TMDB 候选失败，请刷新后重试'))
  } finally {
    addKey(tmdbSearchedKeys, row.raw_title)
    removeKey(tmdbLoadingKeys, row.raw_title)
  }
}

async function autoSearchAll() {
  const todo = items.value.filter(item => !item.source_pending && !item.selected_candidate_key)
  for (const item of todo) {
    await searchTmdb(item, true)
  }
}

async function associateTmdb(row, candidate) {
  if (batchRunning.value || isSaving(row) || isTmdbLoading(row) || !candidate?.candidate_key) return
  addKey(savingKeys, row.raw_title)
  error.value = ''
  notice.value = ''
  clearRowError(row)
  try {
    const response = await props.api.post('plugin/CourseOrganizer/review/tmdb/associate', {
      raw_title: row.raw_title,
      revision: row.revision,
      candidate_key: candidate.candidate_key,
      search_name: (row.final_title && row.final_title.trim()) || row.raw_title,
    })
    const data = unwrap(response)
    // 记录选中的候选 key，让匹配下拉保持显示所选；并保留候选列表供展示
    selectedCandidates.value = { ...selectedCandidates.value, [row.raw_title]: candidate.candidate_key }
    notice.value = data?.final_title
      ? `已关联 TMDB：${data.final_title}`
      : (data?.message || '已保存 TMDB 关联')
    const updated = getUpdatedRow(row.raw_title, data)
    if (updated) {
      // 用返回的最新行替换：建议名称将更新为所选 TMDB 的标题
      items.value = replaceRow(row.raw_title, updated)
    }
  } catch (associateError) {
    setRowError(row, errorMessage(associateError, '保存 TMDB 关联失败，请刷新后重试'))
  } finally {
    removeKey(savingKeys, row.raw_title)
  }
}

async function saveReview(row, action, options = {}) {
  const queued = Boolean(options.queued)
  if ((batchRunning.value && !queued) || isSaving(row) || isTmdbLoading(row)) return false
  if (action === 'confirm' && organizingKey.value) return false
  if (action === 'confirm' && (!row.final_title || !row.target_library)) {
    setRowError(row, '请填写建议名称并选择目标媒体库')
    return false
  }
  if (!queued) {
    error.value = ''
    notice.value = ''
  }
  clearRowError(row)
  const payload = {
    raw_title: row.raw_title,
    revision: row.revision,
    action,
  }
  if (action === 'confirm') {
    payload.final_title = row.final_title
    payload.target_library = row.target_library
    startFileTransferProgress()
    organizingKey.value = row.raw_title
  } else {
    addKey(savingKeys, row.raw_title)
  }
  try {
    const response = await props.api.post('plugin/CourseOrganizer/review', payload)
    const data = unwrap(response)
    if (action === 'confirm') {
      items.value = items.value.filter(item => item.raw_title !== row.raw_title)
      const nextCandidates = { ...tmdbCandidates.value }
      delete nextCandidates[row.raw_title]
      tmdbCandidates.value = nextCandidates
      removeKey(selectedKeys, row.raw_title)
      if (!queued) notice.value = '整理完成'
    } else {
      notice.value = data?.message || '已保存人工决定'
      if (action === 'ignore') removeKey(selectedKeys, row.raw_title)
      const updated = getUpdatedRow(row.raw_title, data)
      if (updated) {
        items.value = replaceRow(row.raw_title, updated)
      }
    }
    return true
  } catch (saveError) {
    setRowError(row, errorMessage(
      saveError,
      action === 'confirm' ? '单条整理失败，记录已保留，请重试' : '保存人工决定失败，请刷新后重试',
    ))
    return false
  } finally {
    if (action === 'confirm') {
      stopFileTransferProgress()
      organizingKey.value = ''
    } else {
      removeKey(savingKeys, row.raw_title)
    }
  }
}

async function organizeSelected() {
  if (
    batchRunning.value
    || organizingKey.value
    || tmdbLoadingKeys.value.length
    || !selectedQueueableItems.value.length
  ) return
  const queue = [...selectedQueueableItems.value]
  batchRunning.value = true
  batchCurrent.value = 0
  batchTotal.value = queue.length
  error.value = ''
  notice.value = ''
  let succeeded = 0
  let failed = 0
  try {
    for (let index = 0; index < queue.length; index += 1) {
      batchCurrent.value = index + 1
      const row = items.value.find(item => item.raw_title === queue[index].raw_title)
      if (!row || !canQueue(row)) {
        failed += 1
        continue
      }
      if (await saveReview(row, 'confirm', { queued: true })) succeeded += 1
      else failed += 1
    }
  } finally {
    batchRunning.value = false
    if (failed) {
      error.value = `批量整理完成：成功 ${succeeded} 项，失败 ${failed} 项。失败项目已保留。`
    } else {
      notice.value = `批量整理完成，共 ${succeeded} 项。`
    }
  }
}

function getUpdatedRow(rawTitle, payload) {
  if (payload && typeof payload === 'object') {
    if (payload.raw_title) {
      return payload
    }
    if (payload.row && payload.row.raw_title) {
      return payload.row
    }
    if (payload.item && payload.item.raw_title) {
      return payload.item
    }
  }
  if (rawTitle && rawTitle === payload?.raw_title) {
    return payload
  }
  return null
}

function replaceRow(rawTitle, nextRow) {
  return items.value.map(item => (item.raw_title === rawTitle ? nextRow : item))
}

function isSaving(row) {
  return hasKey(savingKeys, row.raw_title)
}

function isTmdbLoading(row) {
  return hasKey(tmdbLoadingKeys, row.raw_title)
}

function isOrganizing(row) {
  return organizingKey.value === row.raw_title
}

function organizingProgress() {
  return ` ${fileTransferValue.value === null ? '' : `（${fileTransferValue.value}%）`}`
}

function hasOrganizingValue() {
  return fileTransferValue.value !== null && fileTransferSeenActive.value
}

function organizingStatusText() {
  if (!fileTransferText.value) {
    return '整理中'
  }
  return `${fileTransferText.value}${organizingProgress()}`
}

function libraryLabel(row) {
  return libraries.value.find(item => item.value === row.target_library)?.title || '待确认'
}

function hasLibrary(row) {
  return libraries.value.some(item => item.value === row.target_library)
}

function canConfirm(row) {
  return rulesReady.value && !row.source_pending && hasLibrary(row)
}

function canQueue(row) {
  return canConfirm(row) && Boolean(String(row.final_title || '').trim()) && row.status_label !== '已跳过'
}

function isSelected(row) {
  return selectedKeys.value.includes(row.raw_title)
}

function setSelected(row, selected) {
  if (selected) addKey(selectedKeys, row.raw_title)
  else removeKey(selectedKeys, row.raw_title)
}

function setAllQueueable(selected) {
  if (!selected) {
    selectedKeys.value = []
    return
  }
  selectedKeys.value = queueableItems.value.map(item => item.raw_title)
}

function isSourcePending(row) {
  return Boolean(row.source_pending)
}

function statusChipColor(row) {
  if (isSourcePending(row)) return 'info'
  if (row.status_label === '可以整理') return 'success'
  if (row.status_label === '已跳过') return 'default'
  return 'warning'
}

function targetRoot(row) {
  const library = libraries.value.find(item => item.value === row.target_library)
  return library?.path || '请选择目标媒体库'
}

function handlingMode(row) {
  return row.association_required ? '按标题整理' : 'TMDB 整理'
}

function transferTypeLabel(value) {
  const normalized = String(value || '').toLowerCase()
  if (!normalized || normalized === 'move' || normalized.startsWith('rclone_move')) return '移动'
  if (normalized === 'copy' || normalized.startsWith('rclone_copy')) return '复制'
  if (normalized.includes('hardlink')) return '硬链接'
  if (normalized.includes('softlink') || normalized.includes('soft_link')) return '软链接'
  return value
}

function tmdbSearchHint(row) {
  if (isTmdbLoading(row)) return '正在查找 TMDB 候选…'
  if (hasKey(tmdbSearchFailedKeys, row.raw_title)) return '自动匹配失败，可稍后重试'
  if (hasKey(tmdbSearchedKeys, row.raw_title) && !tmdbCandidatesFor(row).length) {
    return '未找到匹配，可修改名称后重试'
  }
  return ''
}

function tmdbCandidatesFor(row) {
  return tmdbCandidates.value[row.raw_title] || []
}

function tmdbCandidateItems(row) {
  return tmdbCandidatesFor(row).map(c => ({
    ...c,
    title: `${c.title}${c.year ? `（${c.year}）` : ''} · ${c.label || c.media_type}`,
  }))
}

function selectedCandidateFor(row) {
  return selectedCandidates.value[row.raw_title] || null
}

function findCandidate(row, key) {
  return tmdbCandidatesFor(row).find(c => c.candidate_key === key) || null
}

onMounted(async () => {
  await loadReview()
  if (Array.isArray(items.value) && items.value.length) {
    autoSearchAll()
  }
})
onUnmounted(stopFileTransferProgress)

defineExpose({ loadReview, items, loading, savingKeys, tmdbCandidates })
</script>

<template>
  <section class="course-review-page" aria-labelledby="course-review-title">
    <header class="course-review-toolbar">
      <div>
        <h1 id="course-review-title" class="text-h5">待整理项目</h1>
        <div class="text-body-2 text-medium-emphasis mt-1">{{ reviewSummary }}</div>
      </div>
      <div class="course-review-toolbar__actions">
        <VBtn icon="mdi-help-circle-outline" variant="text" aria-label="查看使用说明" @click="helpOpen = true" />
        <VBtn
          prepend-icon="mdi-refresh"
          variant="tonal"
          :loading="loading"
          :disabled="batchRunning"
          aria-label="重新扫描待整理项目"
          @click="refreshReview"
        >
          重新扫描
        </VBtn>
        <VBtn icon="mdi-close" variant="text" :disabled="batchRunning" aria-label="关闭待整理项目" @click="emit('close')" />
      </div>
    </header>

    <VSheet border rounded class="course-directory-summary mb-3">
      <VIcon :icon="rulesReady ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'" :color="rulesReady ? 'success' : 'warning'" />
      <div class="flex-grow-1">
        <div class="text-body-2 font-weight-medium">{{ directoryStatus }}</div>
        <div class="text-caption text-medium-emphasis">
          沿用 MoviePilot 的目录与整理设置<span v-if="incomingPath"> · 来源 {{ incomingPath }}</span>
        </div>
      </div>
      <VBtn
        v-if="directoryRules.length"
        variant="text"
        size="small"
        :append-icon="rulesExpanded ? 'mdi-chevron-up' : 'mdi-chevron-down'"
        @click="rulesExpanded = !rulesExpanded"
      >
        {{ rulesExpanded ? '收起' : '查看规则' }}
      </VBtn>
      <VBtn
        variant="text"
        color="primary"
        size="small"
        prepend-icon="mdi-folder-cog"
        :disabled="batchRunning"
        @click.stop="openMoviePilotSettings"
      >
        目录设置
      </VBtn>
    </VSheet>

    <div v-if="rulesExpanded && directoryRules.length" class="course-directory-rules mb-3">
      <VSheet
        v-for="rule in directoryRules"
        :key="`${rule.value}:${rule.download_path}:${rule.path}`"
        border
        rounded
        class="course-directory-rule"
      >
        <div class="d-flex align-center flex-wrap ga-2 mb-1">
          <strong class="text-body-2">{{ rule.title }}</strong>
          <VChip size="x-small" variant="tonal">{{ transferTypeLabel(rule.transfer_type) }}</VChip>
          <VChip size="x-small" variant="tonal" :color="rule.renaming ? 'success' : 'warning'">
            {{ rule.renaming ? '智能重命名' : '未开启重命名' }}
          </VChip>
          <VChip v-if="rule.scraping" size="x-small" variant="tonal">影视刮削</VChip>
          <VChip size="x-small" variant="tonal" :color="rule.monitor_type ? 'warning' : undefined">
            {{ rule.monitor_type ? '自动监控' : '手动整理' }}
          </VChip>
        </div>
        <div class="text-caption text-medium-emphasis text-break">
          {{ rule.download_path }} → {{ rule.path }}
        </div>
      </VSheet>
    </div>

    <VAlert v-if="rulesMessage" type="warning" variant="tonal" density="compact" class="mb-2" role="alert">
      {{ rulesMessage }}
    </VAlert>
    <VAlert v-if="monitoringEnabled" type="error" variant="tonal" density="compact" class="mb-2" role="alert">
      {{ monitoringRuleText }}与当前来源目录重叠；插件已自动禁止自动整理，仅保留安全预览。
    </VAlert>
    <VAlert v-if="batchRunning || organizingKey" type="info" variant="tonal" density="compact" class="mb-2" role="status">
      <template v-if="batchRunning">
        批量队列正在处理第 {{ batchCurrent }}/{{ batchTotal }} 项，其余项目将按顺序执行。
      </template>
      <template v-else>当前一次只能整理一个项目，完成后可继续下一项。</template>
    </VAlert>

    <VAlert v-if="error" type="error" variant="tonal" class="mb-4" role="alert">
      {{ error }}
    </VAlert>
    <VAlert v-if="notice" type="success" variant="tonal" class="mb-4" role="status">
      {{ notice }}
    </VAlert>

    <VSheet v-if="hasItems && !loading" border rounded class="course-batch-bar mb-3">
      <VCheckbox
        :model-value="allQueueableSelected"
        :indeterminate="someQueueableSelected"
        :disabled="batchRunning || !queueableItems.length"
        hide-details
        density="compact"
        label="全选可整理项目"
        aria-label="全选可整理项目"
        @update:model-value="setAllQueueable"
      />
      <div class="text-body-2 text-medium-emphasis flex-grow-1">
        已选 {{ selectedQueueableItems.length }} 项
      </div>
      <VBtn
        color="primary"
        variant="tonal"
        prepend-icon="mdi-playlist-check"
        :loading="batchRunning"
        :disabled="batchRunning || Boolean(organizingKey) || Boolean(tmdbLoadingKeys.length) || !selectedQueueableItems.length"
        @click="organizeSelected"
      >
        批量整理
      </VBtn>
    </VSheet>

    <VProgressLinear v-if="loading" indeterminate color="primary" aria-label="正在加载" />
    <VSheet v-else-if="!hasItems" border rounded class="course-empty-state" role="status">
      <VIcon icon="mdi-folder-search-outline" size="42" color="primary" />
      <div class="text-h6 mt-3">暂无待整理项目</div>
      <div class="text-body-2 text-medium-emphasis mt-1 mb-4">重新扫描后，这里会显示需要确认的目录。</div>
      <VBtn color="primary" variant="tonal" prepend-icon="mdi-refresh" :loading="loading" @click="refreshReview">
        重新扫描
      </VBtn>
    </VSheet>

    <VSheet v-else border rounded class="course-review-table-shell">
      <VTable class="course-review-table" density="comfortable">
        <thead>
          <tr>
            <th scope="col" class="course-review-select-column">选择</th>
            <th scope="col">原始名称</th>
            <th scope="col">建议名称（可改）</th>
            <th scope="col">目标媒体库</th>
            <th scope="col">状态</th>
            <th scope="col" class="text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.raw_title">
            <td class="course-review-select-column">
              <VCheckbox
                :model-value="isSelected(row)"
                :disabled="batchRunning || (!canQueue(row) && !isSelected(row))"
                hide-details
                density="compact"
                :aria-label="`选择整理：${row.raw_title}`"
                @update:model-value="value => setSelected(row, value)"
              />
            </td>
            <td class="course-review-name">{{ row.raw_title }}</td>
            <td class="course-review-edit-cell">
              <VTextField
                v-model="row.final_title"
                :aria-label="`建议名称：${row.raw_title}`"
                hide-details
                density="comfortable"
                variant="outlined"
                autocomplete="off"
                :disabled="batchRunning || isSaving(row) || isOrganizing(row)"
                placeholder="建议名称（可修改）"
              />
              <VProgressLinear
                v-if="isOrganizing(row)"
                :indeterminate="!hasOrganizingValue()"
                :model-value="fileTransferValue || 0"
                color="primary"
                class="mt-2"
                aria-label="正在整理"
              />
              <div
                v-if="isOrganizing(row)"
                role="status"
                aria-live="polite"
                class="text-caption text-medium-emphasis mt-1"
              >
                {{ organizingStatusText() }}
              </div>
              <VBtn
                class="mt-2"
                variant="tonal"
                min-width="132"
                :loading="isTmdbLoading(row)"
                :disabled="batchRunning || isSourcePending(row) || isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
                :aria-label="`重新搜索 TMDB：${row.raw_title}`"
                @click="searchTmdb(row)"
              >
                重新搜索 TMDB
              </VBtn>
              <div v-if="tmdbSearchHint(row)" class="text-caption text-medium-emphasis mt-1">
                {{ tmdbSearchHint(row) }}
              </div>
              <VSelect
                v-if="tmdbCandidatesFor(row).length"
                :model-value="selectedCandidateFor(row)"
                @update:model-value="(v) => { const c = findCandidate(row, v); if (c) associateTmdb(row, c) }"
                :items="tmdbCandidateItems(row)"
                item-title="title"
                item-value="candidate_key"
                hide-details
                density="compact"
                variant="outlined"
                :label="selectedCandidateFor(row) ? '已关联的 TMDB 作品' : '选择匹配的 TMDB 作品'"
                class="mt-1"
                :disabled="batchRunning || isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
                :aria-label="`选择 TMDB 候选：${row.raw_title}`"
              />
            </td>
            <td class="course-review-library-cell">
              <VSelect
                v-model="row.target_library"
                :items="libraries"
                item-title="title"
                item-value="value"
                :aria-label="`目标媒体库：${row.raw_title}`"
                hide-details
                density="comfortable"
                variant="outlined"
                :disabled="batchRunning || isSaving(row) || isOrganizing(row)"
              />
              <div class="text-caption text-medium-emphasis mt-1 text-break">目标：{{ targetRoot(row) }}</div>
            </td>
            <td>
              <VChip size="small" variant="tonal" class="mr-1">{{ handlingMode(row) }}</VChip>
              <VChip
                v-if="isOrganizing(row)"
                size="small"
                variant="tonal"
                color="info"
                aria-label="整理中"
                class="course-review-organizing-chip"
              >
                整理中
              </VChip>
              <VChip
                v-else
                size="small"
                variant="tonal"
                :color="statusChipColor(row)"
                :aria-label="`状态：${row.status_label || '需要确认'}`"
              >
                {{ row.status_label || '需要确认' }}
              </VChip>
            </td>
            <td class="course-review-actions text-right">
              <VBtn
                color="primary"
                variant="tonal"
                min-width="108"
                :loading="isOrganizing(row)"
                :disabled="batchRunning || Boolean(organizingKey) || !canConfirm(row) || isTmdbLoading(row)"
                :aria-label="`确认整理：${row.raw_title}`"
                @click="saveReview(row, 'confirm')"
              >
                确认并整理
              </VBtn>
              <VBtn
                v-if="row.status_label !== '已跳过'"
                variant="text"
                min-width="76"
                :disabled="batchRunning || isSourcePending(row) || isSaving(row) || isOrganizing(row)"
                :aria-label="`跳过：${row.raw_title}`"
                @click="saveReview(row, 'ignore')"
              >
                跳过
              </VBtn>
              <VBtn
                v-else
                variant="text"
                min-width="76"
                :disabled="batchRunning || isSourcePending(row) || isSaving(row) || isOrganizing(row)"
                :aria-label="`恢复处理：${row.raw_title}`"
                @click="saveReview(row, 'restore')"
              >
                恢复处理
              </VBtn>
              <VAlert
                v-if="rowErrorFor(row)"
                type="error"
                density="compact"
                variant="tonal"
                class="mt-2 text-left"
                role="alert"
                :aria-label="`操作提示：${row.raw_title}`"
                @click.stop
              >
                {{ rowErrorFor(row) }}
              </VAlert>
            </td>
          </tr>
        </tbody>
      </VTable>
    </VSheet>

    <div v-if="hasItems" class="course-review-cards">
      <VCard v-for="row in items" :key="`card-${row.raw_title}`" border variant="outlined" class="course-review-card">
          <VCardTitle class="course-review-card__title text-subtitle-1">
            <VCheckbox
              :model-value="isSelected(row)"
              :disabled="batchRunning || (!canQueue(row) && !isSelected(row))"
              hide-details
              density="compact"
              :aria-label="`选择整理：${row.raw_title}`"
              @update:model-value="value => setSelected(row, value)"
            />
            <span class="text-break">{{ row.raw_title }}</span>
          </VCardTitle>
          <VCardText>
            <VTextField
            v-model="row.final_title"
            label="建议名称"
            :aria-label="`建议名称：${row.raw_title}`"
            variant="outlined"
            density="comfortable"
            autocomplete="off"
            :disabled="batchRunning || isSaving(row) || isOrganizing(row)"
            />
            <VProgressLinear
            v-if="isOrganizing(row)"
            :indeterminate="!hasOrganizingValue()"
            :model-value="fileTransferValue || 0"
            color="primary"
            class="mb-2"
            aria-label="正在整理"
            />
            <div
            v-if="isOrganizing(row)"
            role="status"
            aria-live="polite"
            class="text-caption text-medium-emphasis mb-2"
            >
            {{ organizingStatusText() }}
            </div>
          <VChip
            v-if="isOrganizing(row)"
            size="small"
            variant="tonal"
            color="info"
            class="mb-2"
            aria-label="整理中"
          >
            整理中
          </VChip>
            <VBtn
            class="mb-3"
            variant="tonal"
            min-width="132"
            :loading="isTmdbLoading(row)"
            :disabled="batchRunning || isSourcePending(row) || isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
            :aria-label="`重新搜索 TMDB：${row.raw_title}`"
            @click="searchTmdb(row)"
            >
            重新搜索 TMDB
          </VBtn>
            <div v-if="tmdbSearchHint(row)" class="text-caption text-medium-emphasis mb-1">
              {{ tmdbSearchHint(row) }}
            </div>
            <VSelect
            v-if="tmdbCandidatesFor(row).length"
            :model-value="selectedCandidateFor(row)"
            @update:model-value="(v) => { const c = findCandidate(row, v); if (c) associateTmdb(row, c) }"
            :items="tmdbCandidateItems(row)"
            item-title="title"
            item-value="candidate_key"
            hide-details
            density="compact"
            variant="outlined"
            :label="selectedCandidateFor(row) ? '已关联的 TMDB 作品' : '选择匹配的 TMDB 作品'"
            class="mb-3"
            :disabled="batchRunning || isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
            :aria-label="`选择 TMDB 候选：${row.raw_title}`"
            />
            <VSelect
            v-model="row.target_library"
            :items="libraries"
            item-title="title"
            item-value="value"
            label="目标媒体库"
            :aria-label="`目标媒体库：${row.raw_title}`"
            variant="outlined"
            density="comfortable"
            :disabled="batchRunning || isSaving(row) || isOrganizing(row)"
            />
            <div class="text-caption text-medium-emphasis mt-n3 mb-3 text-break">目标：{{ targetRoot(row) }}</div>
          <div class="d-flex flex-wrap align-center ga-2">
            <VChip size="small" variant="tonal">{{ libraryLabel(row) }}</VChip>
            <VChip size="small" variant="tonal">{{ handlingMode(row) }}</VChip>
            <VChip size="small" variant="tonal" :color="statusChipColor(row)">
            {{ row.status_label || '需要确认' }}
            </VChip>
            <VSpacer />
            <VBtn
            color="primary"
            variant="tonal"
            min-width="108"
            :loading="isOrganizing(row)"
            :disabled="batchRunning || Boolean(organizingKey) || !canConfirm(row) || isTmdbLoading(row)"
            :aria-label="`确认整理：${row.raw_title}`"
            @click="saveReview(row, 'confirm')"
            >
            确认并整理
            </VBtn>
            <VBtn
            v-if="row.status_label !== '已跳过'"
            variant="text"
            min-width="76"
            :disabled="batchRunning || isSourcePending(row) || isSaving(row) || isOrganizing(row)"
            :aria-label="`跳过：${row.raw_title}`"
            @click="saveReview(row, 'ignore')"
            >
            跳过
            </VBtn>
            <VBtn
            v-else
            variant="text"
            min-width="76"
            :disabled="batchRunning || isSourcePending(row) || isSaving(row) || isOrganizing(row)"
            :aria-label="`恢复处理：${row.raw_title}`"
            @click="saveReview(row, 'restore')"
            >
            恢复处理
            </VBtn>
          </div>
          <VAlert
            v-if="rowErrorFor(row)"
            type="error"
            density="compact"
            variant="tonal"
            class="mt-2"
            role="alert"
            :aria-label="`操作提示：${row.raw_title}`"
          >
            {{ rowErrorFor(row) }}
          </VAlert>
          </VCardText>
      </VCard>
    </div>

    <VDialog v-model="helpOpen" max-width="680">
      <VCard>
        <VCardTitle class="d-flex align-center pa-4">
          <span>使用说明</span>
          <VSpacer />
          <VBtn icon="mdi-close" variant="text" aria-label="关闭使用说明" @click="helpOpen = false" />
        </VCardTitle>
        <VDivider />
        <VCardText class="course-help-content">
          <div>
            <strong>1. 目录来自 MoviePilot</strong>
            <p>插件直接读取「设置 → 存储 &amp; 目录」，沿用媒体类型、媒体类别、存储、整理方式、智能重命名和影视刮削。</p>
          </div>
          <div>
            <strong>2. 文件夹何时显示</strong>
            <p>插件会递归检查整个文件夹。目录内没有正在下载的临时或缓存文件，并且内容保持稳定后，才会显示在待整理列表。</p>
          </div>
          <div>
            <strong>3. 自动整理符合条件的项目</strong>
            <p>默认只扫描并生成建议，不会移动文件。开启自动整理后，仅识别可靠且目标媒体库明确的项目会自动执行；不确定项目仍等待人工确认。</p>
          </div>
          <div>
            <strong>4. 智能助手（如 DeepSeek）</strong>
            <p>插件直接使用 MoviePilot「设置 → 智能助手」中的模型，无需在插件内重复配置。复杂目录名会先提取 TMDB 搜索词再复核候选；不可用或判断不明确时不会自动整理。</p>
          </div>
          <div>
            <strong>5. 两种整理方式</strong>
            <p>已关联媒体信息的项目使用 MoviePilot 的 TMDB 整理；课程等无媒体 ID 的项目按确认后的标题整理。</p>
          </div>
          <div>
            <strong>6. 避免重复监控</strong>
            <p>同一来源目录不要同时启用 MoviePilot 自动监控和插件自动整理，避免两个任务竞争同一批文件。</p>
          </div>
          <div>
            <strong>7. 批量任务自动排队</strong>
            <p>可勾选多个项目后批量整理。任务会按顺序逐项执行，失败项目保留并继续下一项。</p>
          </div>
        </VCardText>
        <VCardActions class="pa-4 pt-0">
          <VSpacer />
          <VBtn color="primary" variant="tonal" @click="helpOpen = false">知道了</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </section>
</template>

<style scoped>
.course-review-page {
  min-width: 0;
  padding: 16px;
}

.course-review-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.course-review-toolbar__actions,
.course-directory-summary {
  display: flex;
  align-items: center;
  gap: 8px;
}

.course-directory-summary {
  padding: 10px 12px;
}

.course-batch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
}

.course-directory-rules {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 8px;
}

.course-directory-rule {
  min-width: 0;
  padding: 10px 12px;
}

.course-empty-state {
  padding: 40px 20px;
  text-align: center;
}

.course-help-content {
  display: grid;
  gap: 16px;
}

.course-help-content p {
  margin: 4px 0 0;
  color: rgb(var(--v-theme-on-surface-variant));
}

.course-review-table-shell {
  overflow-x: auto;
}

.course-review-table :deep(table) {
  min-width: 1050px;
}

.course-review-table th,
.course-review-table td {
  vertical-align: middle;
  padding: 10px 12px;
}

.course-review-select-column {
  width: 64px;
  min-width: 64px;
  text-align: center;
}

.course-review-select-column :deep(.v-selection-control) {
  justify-content: center;
}

.course-review-name {
  min-width: 180px;
  max-width: 260px;
  overflow-wrap: anywhere;
}

.course-review-edit-cell {
  min-width: 220px;
}

.course-review-library-cell {
  min-width: 160px;
}

.course-review-path {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-review-actions {
  min-width: 220px;
  white-space: nowrap;
}

.course-tmdb-candidates {
  max-width: 360px;
  background: transparent;
}

.course-tmdb-candidate {
  justify-content: flex-start;
  min-height: 44px;
  white-space: normal;
  text-align: left;
}

.course-review-page :deep(.v-btn) {
  min-height: 44px;
  min-width: 44px;
}

.course-review-cards {
  display: none;
}

.course-review-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 700px) {
  .course-review-page {
    padding: 12px;
  }

  .course-review-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .course-review-toolbar__actions,
  .course-directory-summary,
  .course-batch-bar {
    flex-wrap: wrap;
  }

  .course-batch-bar .v-btn {
    width: 100%;
  }

  .course-review-table-shell {
    display: none;
  }

  .course-review-cards {
    display: grid;
    gap: 12px;
  }

  .course-review-card :deep(.v-card-text) {
    padding-top: 8px;
  }
}
</style>
