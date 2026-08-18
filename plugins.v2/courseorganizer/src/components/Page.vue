<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

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
const rulesMessage = ref('')
const monitoringEnabled = ref(false)
const settingsUrl = ref('#/setting')
const savingKeys = ref([])
const organizingKey = ref('')
const tmdbLoadingKeys = ref([])
const tmdbCandidates = ref({})
const selectedCandidates = ref({})
const rowErrors = ref({})
let fileTransferSource = null
const fileTransferText = ref('')
const fileTransferValue = ref(null)
const fileTransferSeenActive = ref(false)

const hasItems = computed(() => items.value.length > 0)

function unwrap(response) {
  const body = response && Object.prototype.hasOwnProperty.call(response, 'success')
    ? response
    : (response?.data ?? response)
  if (body?.success === false) {
    throw new Error(body.message || '请求失败')
  }
  return body?.data ?? body ?? {}
}

function errorMessage(errorValue, fallback) {
  return errorValue?.message || fallback
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
  selectedCandidates.value = {}   
  try {
    const response = await props.api.get('plugin/CourseOrganizer/review')
    const data = unwrap(response)
    items.value = Array.isArray(data) ? data : (data.items || [])
    if (Array.isArray(data?.libraries) && data.libraries.length) {
      libraries.value = data.libraries
    } else {
      libraries.value = []
    }
    directoryRules.value = Array.isArray(data?.directory_rules) ? data.directory_rules : []
    rulesMessage.value = data?.rules_message || ''
    monitoringEnabled.value = Boolean(data?.monitoring_enabled)
    settingsUrl.value = data?.settings_url || '#/setting'
    tmdbCandidates.value = {}
  } catch (loadError) {
    error.value = errorMessage(loadError, '加载人工复核列表失败')
  } finally {
    loading.value = false
  }
}

async function refreshReview() {
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
  if (isSaving(row) || isTmdbLoading(row)) return
  addKey(tmdbLoadingKeys, row.raw_title)
  error.value = ''
  if (!silent) notice.value = ''
  clearRowError(row)
  tmdbCandidates.value = { ...tmdbCandidates.value, [row.raw_title]: [] }
  const sel = { ...selectedCandidates.value }
  delete sel[row.raw_title]
  selectedCandidates.value = sel
  try {
    const response = await props.api.post('plugin/CourseOrganizer/review/tmdb/search', {
      raw_title: row.raw_title,
      revision: row.revision,
      search_name: (row.final_title && row.final_title.trim()) || row.raw_title,
    })
    const data = unwrap(response)
    const candidates = Array.isArray(data?.items) ? data.items : []
    tmdbCandidates.value = { ...tmdbCandidates.value, [row.raw_title]: candidates }
    if (!silent) notice.value = data?.message || '已找到 TMDB 候选'
  } catch (searchError) {
    if (!silent) setRowError(row, errorMessage(searchError, '搜索 TMDB 候选失败，请刷新后重试'))
  } finally {
    removeKey(tmdbLoadingKeys, row.raw_title)
  }
}

async function autoSearchAll() {
  const todo = items.value.filter(item => !item.source_pending)
  for (const item of todo) {
    await searchTmdb(item, true)
  }
}

async function associateTmdb(row, candidate) {
  if (isSaving(row) || isTmdbLoading(row) || !candidate?.candidate_key) return
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

async function saveReview(row, action) {
  if (isSaving(row) || isTmdbLoading(row)) return
  if (action === 'confirm' && organizingKey.value) return
  if (action === 'confirm' && (!row.final_title || !row.target_library)) {
    setRowError(row, '请填写建议名称并选择目标媒体库')
    return
  }
  error.value = ''
  notice.value = ''
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
      notice.value = '整理完成'
    } else {
      notice.value = data?.message || '已保存人工决定'
      const updated = getUpdatedRow(row.raw_title, data)
      if (updated) {
        items.value = replaceRow(row.raw_title, updated)
      }
    }
  } catch (saveError) {
    setRowError(row, errorMessage(
      saveError,
      action === 'confirm' ? '单条整理失败，记录已保留，请重试' : '保存人工决定失败，请刷新后重试',
    ))
  } finally {
    if (action === 'confirm') {
      stopFileTransferProgress()
      organizingKey.value = ''
    } else {
      removeKey(savingKeys, row.raw_title)
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
  return !row.source_pending && hasLibrary(row)
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

function targetPath(row) {
  const library = libraries.value.find(item => item.value === row.target_library)
  if (library?.path && row.final_title) {
    return `${String(library.path).replace(/\/$/, '')}/${row.final_title}`
  }
  return row.target_path || row.target_output_root || '待确认'
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
        <h1 id="course-review-title" class="text-h5">安全预览与人工确认</h1>
      </div>
      <VBtn
        prepend-icon="mdi-refresh"
        variant="tonal"
        :loading="loading"
        aria-label="刷新人工复核列表"
        @click="refreshReview"
      >
        刷新
      </VBtn>
      <VBtn
        icon="mdi-close"
        variant="text"
        aria-label="关闭人工复核"
        @click="emit('close')"
      />
    </header>

    <div class="d-flex align-center flex-wrap ga-2 text-body-2 text-medium-emphasis mb-2">
      <span>整理方式来自 MoviePilot「设置 → 存储 &amp; 目录」</span>
      <VBtn
        :href="settingsUrl"
        variant="text"
        color="primary"
        size="small"
        prepend-icon="mdi-folder-cog"
      >
        打开目录设置
      </VBtn>
      <span v-if="directoryRules.length" class="d-flex flex-wrap ga-2">
        <VChip
          v-for="rule in directoryRules"
          :key="`${rule.value}:${rule.download_path}:${rule.path}`"
          size="small"
          variant="tonal"
          :title="`${rule.download_path} → ${rule.path}`"
        >
          {{ rule.title }}：{{ rule.download_path }} → {{ rule.path }}
        </VChip>
      </span>
    </div>

    <VAlert v-if="rulesMessage" type="warning" variant="tonal" density="compact" class="mb-2" role="alert">
      {{ rulesMessage }}
    </VAlert>
    <VAlert v-if="monitoringEnabled" type="warning" variant="tonal" density="compact" class="mb-2" role="alert">
      匹配规则启用了自动监控，人工复核期间请关闭监控，避免文件在确认前被自动整理。
    </VAlert>

    <VAlert v-if="error" type="error" variant="tonal" class="mb-4" role="alert">
      {{ error }}
    </VAlert>
    <VAlert v-if="notice" type="success" variant="tonal" class="mb-4" role="status">
      {{ notice }}
    </VAlert>

    <VProgressLinear v-if="loading" indeterminate color="primary" aria-label="正在加载" />
    <VAlert v-else-if="!hasItems" type="info" variant="tonal" role="status">
      暂无可复核记录。运行安全预览后，这里会显示待确认目录。
    </VAlert>

    <VSheet v-else border rounded class="course-review-table-shell">
      <VTable class="course-review-table" density="comfortable">
        <thead>
          <tr>
            <th scope="col">原始名称</th>
            <th scope="col">建议名称（可改）</th>
            <th scope="col">目标媒体库</th>
            <th scope="col">状态</th>
            <th scope="col" class="text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.raw_title">
            <td class="course-review-name">{{ row.raw_title }}</td>
            <td class="course-review-edit-cell">
              <VTextField
                v-model="row.final_title"
                :aria-label="`建议名称：${row.raw_title}`"
                hide-details
                density="comfortable"
                variant="outlined"
                autocomplete="off"
                :disabled="isSaving(row) || isOrganizing(row)"
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
                :disabled="isSourcePending(row) || isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
                :aria-label="`按名称搜索 TMDB：${row.raw_title}`"
                @click="searchTmdb(row)"
              >
                按名称搜索 TMDB
              </VBtn>
              <div class="text-caption text-medium-emphasis mt-1">自动查找，或按上方建议名称(可改)搜索</div>
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
                label="选择匹配的 TMDB 作品"
                class="mt-1"
                :disabled="isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
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
                :disabled="isSaving(row) || isOrganizing(row)"
              />
            </td>
            <td>
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
                :disabled="Boolean(organizingKey) || !canConfirm(row) || isTmdbLoading(row)"
                :aria-label="`确认整理：${row.raw_title}`"
                @click="saveReview(row, 'confirm')"
              >
                保存并整理
              </VBtn>
              <VBtn
                v-if="row.status_label !== '已跳过'"
                variant="text"
                min-width="76"
                :disabled="isSourcePending(row) || isSaving(row) || isOrganizing(row)"
                :aria-label="`跳过：${row.raw_title}`"
                @click="saveReview(row, 'ignore')"
              >
                跳过
              </VBtn>
              <VBtn
                v-else
                variant="text"
                min-width="76"
                :disabled="isSourcePending(row) || Boolean(organizingKey) || !canConfirm(row) || isTmdbLoading(row)"
                :aria-label="`重新确认：${row.raw_title}`"
                @click="saveReview(row, 'confirm')"
              >
                重新确认
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
          <VCardTitle class="text-subtitle-1 text-break">{{ row.raw_title }}</VCardTitle>
          <VCardText>
            <VTextField
            v-model="row.final_title"
            label="建议名称"
            :aria-label="`建议名称：${row.raw_title}`"
            variant="outlined"
            density="comfortable"
            autocomplete="off"
            :disabled="isSaving(row) || isOrganizing(row)"
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
            :disabled="isSourcePending(row) || isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
            :aria-label="`按名称搜索 TMDB：${row.raw_title}`"
            @click="searchTmdb(row)"
            >
            按名称搜索 TMDB
          </VBtn>
            <div class="text-caption text-medium-emphasis mb-1">自动查找，或按上方建议名称(可改)搜索</div>
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
            label="选择匹配的 TMDB 作品"
            class="mb-3"
            :disabled="isSaving(row) || isTmdbLoading(row) || isOrganizing(row)"
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
            :disabled="isSaving(row) || isOrganizing(row)"
            />
          <div class="d-flex flex-wrap align-center ga-2">
            <VChip size="small" variant="tonal">{{ libraryLabel(row) }}</VChip>
            <VChip size="small" variant="tonal" :color="statusChipColor(row)">
            {{ row.status_label || '需要确认' }}
            </VChip>
            <VSpacer />
            <VBtn
            color="primary"
            variant="tonal"
            min-width="108"
            :loading="isOrganizing(row)"
            :disabled="Boolean(organizingKey) || !canConfirm(row) || isTmdbLoading(row)"
            :aria-label="`确认整理：${row.raw_title}`"
            @click="saveReview(row, 'confirm')"
            >
            保存并整理
            </VBtn>
            <VBtn
            v-if="row.status_label !== '已跳过'"
            variant="text"
            min-width="76"
            :disabled="isSourcePending(row) || isSaving(row) || isOrganizing(row)"
            :aria-label="`跳过：${row.raw_title}`"
            @click="saveReview(row, 'ignore')"
            >
            跳过
            </VBtn>
            <VBtn
            v-else
            variant="text"
            min-width="76"
            :disabled="isSourcePending(row) || Boolean(organizingKey) || !canConfirm(row) || isTmdbLoading(row)"
            :aria-label="`重新确认：${row.raw_title}`"
            @click="saveReview(row, 'confirm')"
            >
            重新确认
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

@media (max-width: 700px) {
  .course-review-page {
    padding: 12px;
  }

  .course-review-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .course-review-toolbar .v-btn {
    align-self: flex-start;
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
