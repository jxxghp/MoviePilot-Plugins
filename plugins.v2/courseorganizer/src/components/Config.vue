<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['save', 'close'])

const localConfig = ref({})
const saving = ref(false)
const validationMessage = ref('')

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function textValue(value) {
  return String(value ?? '').trim()
}

function nextArchiveKey(index) {
  return 'archive_' + Date.now() + '_' + (index + 1)
}

function normalizeDownloads(config) {
  const values = Array.isArray(config.download_directories)
    ? config.download_directories
    : (textValue(config.incoming) ? [{ name: '下载目录', path: config.incoming }] : [])
  return values
    .filter(item => typeof item === 'string' || (item && typeof item === 'object'))
    .map((item, index) => {
      const value = typeof item === 'string' ? { path: item } : item
      return {
        name: textValue(value.name || value.label) || '下载目录 ' + (index + 1),
        path: textValue(value.path),
      }
    })
}

function normalizeArchives(config) {
  let values = config.archive_directories
  if (!Array.isArray(values)) {
    const hasLegacy = ['tv_output', 'movie_output', 'children_output', 'output']
      .some(key => Object.prototype.hasOwnProperty.call(config, key))
    values = hasLegacy
      ? [
          { key: 'tv', name: '电视剧', path: config.tv_output, media_type: 'tv' },
          { key: 'movie', name: '电影', path: config.movie_output, media_type: 'movie' },
          {
            key: 'children',
            name: '儿童课程',
            path: config.children_output ?? config.output,
            media_type: 'tv',
            category: '儿童',
          },
        ]
      : []
  }
  return values
    .filter(item => typeof item === 'string' || (item && typeof item === 'object'))
    .map((item, index) => {
      const value = typeof item === 'string' ? { path: item } : item
      const key = textValue(value.key || value.id) || nextArchiveKey(index)
      return {
        id: textValue(value.id) || key,
        key,
        name: textValue(value.name || value.label) || '归档目录 ' + (index + 1),
        path: textValue(value.path),
        media_type: textValue(value.media_type),
        category: textValue(value.category || value.media_category),
      }
    })
}

function normalizeInitialConfig(value) {
  const config = clone(value)
  const rawAutoOrganize = Object.prototype.hasOwnProperty.call(config, 'auto_organize')
    ? config.auto_organize
    : String(config.naming_mode || '').trim().toLowerCase() === 'apply'
  const autoOrganize = typeof rawAutoOrganize === 'string'
    ? ['1', 'true', 'yes', 'on'].includes(rawAutoOrganize.trim().toLowerCase())
    : Boolean(rawAutoOrganize)
  return {
    ...config,
    download_directories: normalizeDownloads(config),
    archive_directories: normalizeArchives(config),
    auto_organize: autoOrganize,
  }
}

function addDownloadDirectory() {
  const items = localConfig.value.download_directories
  items.push({ name: '下载目录 ' + (items.length + 1), path: '' })
}

function removeDownloadDirectory(index) {
  localConfig.value.download_directories.splice(index, 1)
}

function addArchiveDirectory() {
  const items = localConfig.value.archive_directories
  const index = items.length
  const key = nextArchiveKey(index)
  items.push({
    id: key,
    key,
    name: '归档目录 ' + (index + 1),
    path: '',
    media_type: '',
    category: '',
  })
}

function removeArchiveDirectory(index) {
  localConfig.value.archive_directories.splice(index, 1)
}

function validateDirectories() {
  const downloads = localConfig.value.download_directories
  const archives = localConfig.value.archive_directories
  if (!downloads.length || !archives.length) {
    return '请至少添加一个下载目录和一个归档目录。'
  }
  if (downloads.some(item => !textValue(item.name) || !textValue(item.path))) {
    return '请完整填写每个下载目录的名称和路径。'
  }
  const keys = new Set()
  for (const item of archives) {
    const key = textValue(item.key || item.id).toLowerCase()
    if (!key || !textValue(item.name) || !textValue(item.path)) {
      return '请完整填写每个归档目录的标识、名称和路径。'
    }
    if (keys.has(key)) return '归档目录标识不能重复。'
    keys.add(key)
  }
  return ''
}

function saveConfig() {
  if (saving.value) return
  validationMessage.value = validateDirectories()
  if (validationMessage.value) return
  saving.value = true
  try {
    emit('save', clone(localConfig.value))
  } finally {
    saving.value = false
  }
}

watch(
  () => props.initialConfig,
  value => {
    localConfig.value = normalizeInitialConfig(value)
  },
  { immediate: true, deep: true },
)
</script>

<template>
  <VForm class="course-config" aria-label="课程整理目录设置" @submit.prevent="saveConfig">
    <VToolbar density="comfortable" color="transparent" class="course-config__toolbar">
      <div class="text-h6">课程整理目录</div>
      <VSpacer />
      <VBtn icon="mdi-close" variant="text" aria-label="关闭设置" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <VAlert type="info" variant="tonal" class="ma-3" role="note">
      插件独立维护下载目录和归档目录，不读取 MoviePilot 的目录设置。可配置多个下载目录和多个归档目录；共享配置时，请由接收者填写自己设备上的绝对路径。
    </VAlert>

    <section class="course-config__section">
      <div class="d-flex align-center mb-2">
        <div class="text-subtitle-1">下载目录</div>
        <VSpacer />
        <VBtn size="small" variant="tonal" prepend-icon="mdi-plus" @click="addDownloadDirectory">
          添加下载目录
        </VBtn>
      </div>
      <VAlert v-if="!localConfig.download_directories.length" type="warning" variant="tonal" density="compact" class="mb-3">
        至少需要一个下载目录。
      </VAlert>
      <div
        v-for="(directory, index) in localConfig.download_directories"
        :key="directory.name + '-' + index"
        class="course-config__directory-row"
      >
        <VTextField v-model="directory.name" label="名称" density="comfortable" />
        <VTextField v-model="directory.path" label="路径" density="comfortable" />
        <VBtn icon="mdi-delete-outline" variant="text" color="error" :aria-label="'删除下载目录 ' + (index + 1)" @click="removeDownloadDirectory(index)" />
      </div>
    </section>

    <section class="course-config__section">
      <div class="d-flex align-center mb-2">
        <div class="text-subtitle-1">归档目录</div>
        <VSpacer />
        <VBtn size="small" variant="tonal" prepend-icon="mdi-plus" @click="addArchiveDirectory">
          添加归档目录
        </VBtn>
      </div>
      <VAlert v-if="!localConfig.archive_directories.length" type="warning" variant="tonal" density="compact" class="mb-3">
        至少需要一个归档目录。
      </VAlert>
      <div
        v-for="(directory, index) in localConfig.archive_directories"
        :key="directory.id || directory.key || index"
        class="course-config__archive-row"
      >
        <VTextField v-model="directory.key" label="标识" hint="供人工确认选择，不能重复。" persistent-hint density="comfortable" />
        <VTextField v-model="directory.name" label="名称" density="comfortable" />
        <VTextField v-model="directory.path" label="路径" density="comfortable" />
        <VTextField v-model="directory.media_type" label="媒体类型（可选）" density="comfortable" />
        <VTextField v-model="directory.category" label="分类（可选）" density="comfortable" />
        <VBtn icon="mdi-delete-outline" variant="text" color="error" :aria-label="'删除归档目录 ' + (index + 1)" @click="removeArchiveDirectory(index)" />
      </div>
      <VAlert type="info" variant="tonal" density="compact">
        自动识别仍使用现有 tv、movie、children 内置类型映射；其他归档目录可在人工确认时选择。
      </VAlert>
    </section>

    <VSwitch
      v-model="localConfig.auto_organize"
      class="mx-4 mb-2"
      label="自动整理符合条件的项目"
      hint="未完整配置目录或下载目录不可读取时，插件只保留安全预览。"
      persistent-hint
      color="primary"
    />

    <VAlert v-if="validationMessage" type="error" variant="tonal" density="compact" class="mx-3 mb-3">
      {{ validationMessage }}
    </VAlert>

    <div class="course-config__actions">
      <VBtn variant="text" min-width="88" @click="emit('close')">取消</VBtn>
      <VBtn color="primary" min-width="108" :loading="saving" @click="saveConfig">保存</VBtn>
    </div>
  </VForm>
</template>

<style scoped>
.course-config {
  min-width: 0;
  padding-bottom: 12px;
}

.course-config__toolbar {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 0 12px;
}

.course-config__section {
  padding: 0 16px 12px;
}

.course-config__directory-row,
.course-config__archive-row {
  display: grid;
  grid-template-columns: minmax(110px, 0.4fr) minmax(180px, 1fr) auto;
  align-items: start;
  gap: 8px;
}

.course-config__archive-row {
  grid-template-columns: minmax(110px, 0.35fr) minmax(110px, 0.35fr) minmax(180px, 1fr) minmax(120px, 0.35fr) minmax(120px, 0.35fr) auto;
}

.course-config__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 16px;
}

.course-config :deep(.v-btn) {
  min-height: 44px;
}

@media (max-width: 959px) {
  .course-config__directory-row,
  .course-config__archive-row {
    grid-template-columns: 1fr;
  }
}
</style>
