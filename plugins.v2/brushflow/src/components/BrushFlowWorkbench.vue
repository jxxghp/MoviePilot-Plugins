<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import TaskEditorDialog from './TaskEditorDialog.vue'
import {
  cloneTask,
  formatBytes,
  formatDateTime,
  formatDuration,
  taskStateMeta,
  torrentProgress,
  unwrapResponse,
} from '../utils'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'BrushFlow' },
  initialTab: { type: String, default: 'overview' },
  showClose: { type: Boolean, default: false },
  showSwitch: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'switch', 'action'])
const loading = ref(false)
const taskLoading = ref(false)
const saving = ref(false)
const error = ref('')
const status = ref({
  enabled: false,
  show_sidebar_nav: true,
  summary: {},
  tasks: [],
  options: { sites: [], downloaders: [] },
})
const taskDetail = ref(null)
const selectedTaskId = ref('')
const activeTab = ref(props.initialTab)
const torrentState = ref('active')
const torrentPage = ref(1)
const editorOpen = ref(false)
const editorTask = ref(cloneTask())
const deleteDialog = ref(false)
const clearDialog = ref(false)
const settingsMenu = ref(false)
const settingsDraft = ref({ enabled: false, show_sidebar_nav: true })
const hostToast = inject('moviepilot:toast', null)
let refreshTimer

const pluginBase = computed(() => `plugin/${props.pluginId || 'BrushFlow'}`)
const tasks = computed(() => status.value.tasks || [])
const selectedTask = computed(() => tasks.value.find(item => item.id === selectedTaskId.value) || null)
const selectedState = computed(() => taskStateMeta(selectedTask.value?.state))
const taskConfig = computed(() => taskDetail.value?.task || {})
const taskRuns = computed(() => taskDetail.value?.runs || [])
const latestBrushRun = computed(() => taskRuns.value.find(item => item.kind === 'brush') || null)
const torrentData = computed(() => taskDetail.value?.torrents || { items: [], total: 0, page: 1, page_size: 50 })
const totalTorrentPages = computed(() => Math.max(Math.ceil(torrentData.value.total / torrentData.value.page_size), 1))
const seedingPercent = computed(() => {
  const limit = Number(taskConfig.value.disksize || 0) * 1024 ** 3
  if (!limit) return 0
  return Math.min(Math.round((Number(selectedTask.value?.seeding_size || 0) * 100) / limit), 100)
})
const reasonEntries = computed(() => {
  const reasons = latestBrushRun.value?.reason_counts || {}
  return Object.entries(reasons)
    .map(([label, count]) => ({ label, count: Number(count || 0) }))
    .sort((left, right) => right.count - left.count)
})
const maxReasonCount = computed(() => Math.max(1, ...reasonEntries.value.map(item => item.count)))
const pipelineStages = computed(() => {
  const run = latestBrushRun.value || {}
  const sourceCount = Number(run.source_count || 0)
  const candidateCount = Number(run.candidate_count || 0)
  const addedCount = Number(run.added_count || 0)
  return [
    { title: '获取站点种子', detail: taskConfig.value.rss_support ? 'RSS' : '站点列表页', count: sourceCount },
    { title: '排除订阅内容', detail: `排除 ${Number(run.subscription_excluded || 0)} 个`, count: candidateCount },
    { title: '选种条件过滤', detail: `过滤 ${Number(run.filtered_count || 0)} 个`, count: addedCount },
    { title: '添加下载任务', detail: run.success === false ? '执行失败' : '下载器已确认', count: addedCount },
  ]
})

const torrentHeaders = [
  { title: '种子', key: 'title', sortable: false },
  { title: '状态', key: 'status', sortable: false },
  { title: '大小', key: 'size', align: 'end', sortable: false },
  { title: '上传', key: 'uploaded', align: 'end', sortable: false },
  { title: '分享率', key: 'ratio', align: 'end', sortable: false },
  { title: '处理条件', key: 'policy', sortable: false },
]

// 通过宿主注入的 Toast 显示操作结果，不在插件内创建第二套通知层。
function notify(text, color = 'success') {
  const method = ['error', 'info', 'warning', 'success'].includes(color) ? color : 'success'
  if (typeof hostToast?.[method] === 'function') {
    hostToast[method](text)
  } else if (method === 'error') {
    error.value = text
  }
}

// 从插件状态接口加载全局设置和任务摘要。
async function loadStatus({ preserveSelection = true, loadDetail = true } = {}) {
  loading.value = true
  error.value = ''
  try {
    const data = unwrapResponse(await props.api.get(`${pluginBase.value}/status`))
    status.value = data || status.value
    settingsDraft.value = {
      enabled: Boolean(status.value.enabled),
      show_sidebar_nav: status.value.show_sidebar_nav !== false,
    }
    const selectedStillExists = tasks.value.some(item => item.id === selectedTaskId.value)
    if (!preserveSelection || !selectedStillExists) selectedTaskId.value = tasks.value[0]?.id || ''
    if (loadDetail && selectedTaskId.value) await loadTaskDetail()
  } catch (err) {
    error.value = err?.message || '加载刷流任务失败'
  } finally {
    loading.value = false
  }
}

// 加载选中任务的配置、诊断记录和当前分页种子。
async function loadTaskDetail() {
  if (!selectedTaskId.value) {
    taskDetail.value = null
    return
  }
  taskLoading.value = true
  try {
    const query = `state=${torrentState.value}&page=${torrentPage.value}&page_size=50`
    taskDetail.value = unwrapResponse(
      await props.api.get(`${pluginBase.value}/tasks/${selectedTaskId.value}?${query}`),
    )
  } catch (err) {
    error.value = err?.message || '加载任务详情失败'
  } finally {
    taskLoading.value = false
  }
}

// 切换左侧任务并从第一页加载对应明细。
async function selectTask(taskId) {
  if (!taskId || taskId === selectedTaskId.value) return
  selectedTaskId.value = taskId
  torrentState.value = 'active'
  torrentPage.value = 1
  await loadTaskDetail()
}

// 同时刷新任务摘要和当前任务详情。
async function refreshAll(showMessage = false) {
  await loadStatus()
  if (showMessage) notify('刷流任务数据已刷新')
  emit('action')
}

// 打开一个空白任务草稿。
function openCreateTask() {
  editorTask.value = cloneTask()
  editorOpen.value = true
}

// 打开当前任务的服务端配置快照。
function openEditTask() {
  if (!taskConfig.value.id) return
  editorTask.value = cloneTask(taskConfig.value)
  editorOpen.value = true
}

// 通过任务 API 创建或更新任务并刷新调度状态。
async function saveTask(task) {
  saving.value = true
  try {
    const response = task.id
      ? await props.api.put(`${pluginBase.value}/tasks/${task.id}`, task)
      : await props.api.post(`${pluginBase.value}/tasks`, task)
    const detail = unwrapResponse(response)
    editorOpen.value = false
    selectedTaskId.value = detail?.task?.id || task.id || selectedTaskId.value
    await loadStatus()
    notify(task.id ? '刷流任务已更新' : '刷流任务已创建')
  } catch (err) {
    notify(err?.message || '保存刷流任务失败', 'error')
  } finally {
    saving.value = false
  }
}

// 切换当前任务启停状态并立即重建宿主调度。
async function toggleSelectedTask() {
  if (!selectedTask.value) return
  saving.value = true
  try {
    unwrapResponse(
      await props.api.post(`${pluginBase.value}/tasks/${selectedTaskId.value}/state`, {
        enabled: !selectedTask.value.enabled,
      }),
    )
    await loadStatus()
    notify(selectedTask.value?.enabled ? '刷流任务已启用' : '刷流任务已暂停')
  } catch (err) {
    notify(err?.message || '更新任务状态失败', 'error')
  } finally {
    saving.value = false
  }
}

// 提交一次刷流刷新或种子检查操作。
async function runOperation(operation) {
  if (!selectedTaskId.value) return
  saving.value = true
  try {
    const path = operation === 'brush' ? 'run' : 'check'
    unwrapResponse(await props.api.post(`${pluginBase.value}/tasks/${selectedTaskId.value}/${path}`, {}))
    await loadStatus()
    notify(operation === 'brush' ? '刷流刷新已提交' : '种子检查已提交')
  } catch (err) {
    notify(err?.message || '提交任务失败', 'error')
  } finally {
    saving.value = false
  }
}

// 保存全局插件与侧栏入口开关。
async function saveSettings() {
  saving.value = true
  try {
    status.value = unwrapResponse(await props.api.post(`${pluginBase.value}/settings`, settingsDraft.value))
    settingsMenu.value = false
    await loadStatus()
    notify('全局设置已保存')
  } catch (err) {
    notify(err?.message || '保存全局设置失败', 'error')
  } finally {
    saving.value = false
  }
}

// 删除当前没有活跃种子的任务。
async function confirmDeleteTask() {
  saving.value = true
  try {
    unwrapResponse(await props.api.delete(`${pluginBase.value}/tasks/${selectedTaskId.value}`))
    deleteDialog.value = false
    selectedTaskId.value = ''
    await loadStatus({ preserveSelection: false })
    notify('刷流任务已删除')
  } catch (err) {
    notify(err?.message || '删除刷流任务失败', 'error')
  } finally {
    saving.value = false
  }
}

// 清空当前任务的统计、诊断与种子记录。
async function confirmClearTask() {
  saving.value = true
  try {
    taskDetail.value = unwrapResponse(
      await props.api.post(`${pluginBase.value}/tasks/${selectedTaskId.value}/clear`, {}),
    )
    clearDialog.value = false
    await loadStatus()
    notify('任务数据已清除')
  } catch (err) {
    notify(err?.message || '清除任务数据失败', 'error')
  } finally {
    saving.value = false
  }
}

// 切换活跃或已删除种子分页视图。
async function changeTorrentState(value) {
  torrentState.value = value
  torrentPage.value = 1
  await loadTaskDetail()
}

// 加载指定页的种子记录。
async function changeTorrentPage(value) {
  torrentPage.value = value
  await loadTaskDetail()
}

// 根据配置生成当前种子的下一项处理条件摘要。
function torrentPolicy(item) {
  if (item.deleted) return '已删除'
  if (item.hit_and_run && taskConfig.value.hr_seed_time) return `H&R ${taskConfig.value.hr_seed_time} 小时`
  if (taskConfig.value.seed_time) return `${taskConfig.value.seed_time} 小时后检查`
  if (taskConfig.value.seed_ratio) return `分享率 ${taskConfig.value.seed_ratio}`
  return taskConfig.value.proxy_delete ? '动态删种托管' : '等待删除条件'
}

// 返回种子当前下载或做种状态文本。
function torrentStateText(item) {
  const progress = torrentProgress(item)
  if (item.deleted) return '已删除'
  return progress >= 100 ? '做种' : `下载 ${progress}%`
}

watch(
  () => props.initialTab,
  value => {
    if (value) activeTab.value = value
  },
)

onMounted(async () => {
  await loadStatus({ preserveSelection: false })
  refreshTimer = window.setInterval(() => {
    if (!editorOpen.value && document.visibilityState === 'visible') loadStatus()
  }, 30000)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})

defineExpose({ loadStatus, refreshAll, loading, saving })
</script>

<template>
  <div class="brushflow-page" :class="{ 'brushflow-page--compact': compact }">
    <header class="brushflow-page__header">
      <div class="brushflow-page__identity">
        <VIcon icon="mdi-sync" color="primary" size="28" />
        <div>
          <h1>站点刷流</h1>
          <p>多站点任务独立调度与托管</p>
        </div>
      </div>
      <div class="brushflow-page__actions">
        <VChip v-if="status.summary.task_count" size="small" variant="tonal">
          {{ status.summary.enabled_count || 0 }} / {{ status.summary.task_count }} 运行
        </VChip>
        <VMenu v-model="settingsMenu" :close-on-content-click="false" location="bottom end">
          <template #activator="{ props: menuProps }">
            <VBtn v-bind="menuProps" icon="mdi-tune-variant" variant="text" aria-label="全局设置" />
          </template>
          <VCard min-width="300" title="全局设置">
            <VCardText class="settings-menu__body">
              <VSwitch v-model="settingsDraft.enabled" label="启用插件" color="primary" hide-details inset />
              <VSwitch
                v-model="settingsDraft.show_sidebar_nav"
                label="显示侧栏入口"
                color="primary"
                hide-details
                inset
              />
            </VCardText>
            <VCardActions>
              <VSpacer />
              <VBtn color="primary" variant="flat" :loading="saving" @click="saveSettings">保存</VBtn>
            </VCardActions>
          </VCard>
        </VMenu>
        <VBtn v-if="showSwitch" icon="mdi-cog-outline" variant="text" aria-label="切换配置" @click="emit('switch')" />
        <VBtn v-if="showClose" icon="mdi-close" variant="text" aria-label="关闭" @click="emit('close')" />
      </div>
    </header>

    <VAlert v-if="error" type="error" variant="tonal" closable @click:close="error = ''">{{ error }}</VAlert>
    <VAlert v-if="!status.enabled" type="warning" variant="tonal">
      插件当前未启用，任务配置与历史仍可查看，启用后才会注册刷新和检查服务。
    </VAlert>

    <div v-if="loading && !tasks.length" class="brushflow-loading">
      <VSkeletonLoader type="list-item-three-line, list-item-three-line, article" />
    </div>

    <div v-else-if="!tasks.length" class="brushflow-empty">
      <VIcon icon="mdi-sync-off" size="52" color="medium-emphasis" />
      <div class="text-h6">还没有刷流任务</div>
      <div class="text-body-2 text-medium-emphasis">创建任务后可为每个站点分别设置刷新、筛选和删种规则</div>
      <VBtn color="primary" variant="flat" prepend-icon="mdi-plus" @click="openCreateTask">创建第一个任务</VBtn>
    </div>

    <template v-else>
      <VSelect
        class="brushflow-mobile-select"
        :model-value="selectedTaskId"
        :items="tasks"
        item-title="name"
        item-value="id"
        label="当前任务"
        hide-details
        @update:model-value="selectTask"
      >
        <template #item="{ props: itemProps, item }">
          <VListItem v-bind="itemProps" :subtitle="item.raw.site_name">
            <template #prepend>
              <VIcon :icon="taskStateMeta(item.raw.state).icon" :color="taskStateMeta(item.raw.state).color" />
            </template>
          </VListItem>
        </template>
      </VSelect>

      <div class="brushflow-layout">
        <VSheet tag="aside" class="brushflow-task-rail app-surface-static">
          <div class="brushflow-task-rail__head">
            <span class="text-subtitle-2">刷流任务</span>
            <VChip size="x-small" variant="tonal">{{ tasks.length }}</VChip>
          </div>
          <div class="brushflow-task-list">
            <button
              v-for="task in tasks"
              :key="task.id"
              type="button"
              class="brushflow-task-item"
              :class="{ 'brushflow-task-item--selected': task.id === selectedTaskId }"
              :aria-pressed="task.id === selectedTaskId"
              @click="selectTask(task.id)"
            >
              <span class="brushflow-task-item__title">
                <strong>{{ task.name }}</strong>
                <span class="brushflow-status-dot" :class="`brushflow-status-dot--${taskStateMeta(task.state).color}`" />
              </span>
              <span>{{ task.site_name }} · {{ task.downloader }}</span>
              <span class="brushflow-task-item__meta">
                <span>{{ task.statistic.active || 0 }} 个种子</span>
                <span>{{ task.next_run_at ? formatDateTime(task.next_run_at) : '暂无计划' }}</span>
              </span>
            </button>
          </div>
          <VBtn block variant="tonal" prepend-icon="mdi-plus" @click="openCreateTask">新建任务</VBtn>
        </VSheet>

        <main v-if="selectedTask" class="brushflow-workspace">
          <section class="brushflow-task-head">
            <div class="brushflow-task-head__identity">
              <VAvatar color="primary" variant="tonal" rounded size="42">
                <VIcon icon="mdi-web" />
              </VAvatar>
              <div>
                <div class="brushflow-task-head__title">
                  <h2>{{ selectedTask.name }}</h2>
                  <VChip :color="selectedState.color" size="small" variant="tonal" :prepend-icon="selectedState.icon">
                    {{ selectedState.text }}
                  </VChip>
                </div>
                <p>
                  {{ selectedTask.site_name }} · 最近 {{ selectedTask.last_run ? formatDateTime(selectedTask.last_run.started_at) : '尚未运行' }}
                  · 下次 {{ selectedTask.next_run_at ? formatDateTime(selectedTask.next_run_at) : '暂无计划' }}
                </p>
              </div>
            </div>
            <div class="brushflow-task-head__actions">
              <VTooltip text="立即刷新">
                <template #activator="{ props: tipProps }">
                  <VBtn v-bind="tipProps" icon="mdi-sync" variant="text" :loading="selectedTask.operation === 'brush'" @click="runOperation('brush')" />
                </template>
              </VTooltip>
              <VTooltip text="检查种子">
                <template #activator="{ props: tipProps }">
                  <VBtn v-bind="tipProps" icon="mdi-progress-check" variant="text" :loading="selectedTask.operation === 'check'" @click="runOperation('check')" />
                </template>
              </VTooltip>
              <VTooltip :text="selectedTask.enabled ? '暂停任务' : '启用任务'">
                <template #activator="{ props: tipProps }">
                  <VBtn
                    v-bind="tipProps"
                    :icon="selectedTask.enabled ? 'mdi-pause' : 'mdi-play'"
                    variant="text"
                    @click="toggleSelectedTask"
                  />
                </template>
              </VTooltip>
              <VTooltip text="编辑任务">
                <template #activator="{ props: tipProps }">
                  <VBtn v-bind="tipProps" icon="mdi-pencil-outline" variant="text" @click="openEditTask" />
                </template>
              </VTooltip>
            </div>
          </section>

          <VTabs v-model="activeTab" color="primary" class="brushflow-tabs">
            <VTab value="overview">任务概览</VTab>
            <VTab value="diagnostics">运行诊断</VTab>
            <VTab value="config">任务配置</VTab>
          </VTabs>

          <VDivider />

          <VWindow v-model="activeTab" :touch="false" class="brushflow-window">
            <VWindowItem value="overview">
              <div class="brushflow-stat-grid">
                <VSheet class="brushflow-stat app-surface-static">
                  <span>活跃种子</span>
                  <strong>{{ selectedTask.statistic.active || 0 }}</strong>
                  <small>{{ selectedTask.statistic.unarchived || 0 }} 个待归档</small>
                </VSheet>
                <VSheet class="brushflow-stat app-surface-static">
                  <span>累计上传 / 下载</span>
                  <strong>{{ formatBytes(selectedTask.statistic.uploaded) }} / {{ formatBytes(selectedTask.statistic.downloaded) }}</strong>
                  <small>当前任务累计</small>
                </VSheet>
                <VSheet class="brushflow-stat app-surface-static">
                  <span>当前做种</span>
                  <strong>{{ formatBytes(selectedTask.seeding_size) }}</strong>
                  <small>{{ taskConfig.disksize ? `上限 ${taskConfig.disksize} GB` : '未设置体积上限' }}</small>
                  <VProgressLinear v-if="taskConfig.disksize" :model-value="seedingPercent" height="4" color="primary" />
                </VSheet>
                <VSheet class="brushflow-stat app-surface-static">
                  <span>最近刷新</span>
                  <strong>{{ latestBrushRun ? `${latestBrushRun.added_count || 0} / ${latestBrushRun.source_count || 0}` : '-' }}</strong>
                  <small>新增 / 候选</small>
                </VSheet>
              </div>

              <div class="brushflow-overview-grid">
                <VSheet tag="section" class="brushflow-panel app-surface-static">
                  <header class="brushflow-panel__head">
                    <div>
                      <div class="text-subtitle-1 font-weight-medium">运行状态</div>
                      <div class="text-body-2 text-medium-emphasis">当前任务调度与核心策略</div>
                    </div>
                    <VChip :color="selectedState.color" size="small" variant="tonal">{{ selectedState.text }}</VChip>
                  </header>
                  <dl class="brushflow-facts">
                    <div><dt>刷新周期</dt><dd>{{ taskConfig.cron || `每 ${selectedTask.brush_interval} 分钟` }}</dd></div>
                    <div><dt>检查周期</dt><dd>每 {{ selectedTask.check_interval }} 分钟</dd></div>
                    <div><dt>开启时段</dt><dd>{{ taskConfig.active_time_range || '全天' }}</dd></div>
                    <div><dt>选种来源</dt><dd>{{ taskConfig.rss_support ? 'RSS' : '站点列表页' }}</dd></div>
                    <div><dt>促销要求</dt><dd>{{ taskConfig.freeleech === '2xfree' ? '2X 免费' : taskConfig.freeleech === 'free' ? '免费' : '全部' }}</dd></div>
                    <div><dt>删种策略</dt><dd>{{ taskConfig.proxy_delete ? `动态 ${taskConfig.delete_size_range || '-' } GB` : '满足任一条件' }}</dd></div>
                  </dl>
                </VSheet>

                <VSheet tag="section" class="brushflow-panel app-surface-static">
                  <header class="brushflow-panel__head">
                    <div>
                      <div class="text-subtitle-1 font-weight-medium">最近一次刷新</div>
                      <div class="text-body-2 text-medium-emphasis">
                        {{ latestBrushRun ? `${formatDateTime(latestBrushRun.started_at)} · ${formatDuration(latestBrushRun.started_at, latestBrushRun.finished_at)}` : '暂无运行记录' }}
                      </div>
                    </div>
                    <VChip v-if="latestBrushRun" :color="latestBrushRun.success === false ? 'error' : 'success'" size="small" variant="tonal">
                      {{ latestBrushRun.success === false ? '失败' : '完成' }}
                    </VChip>
                  </header>
                  <div class="brushflow-run-summary">
                    <div><span>站点候选</span><strong>{{ latestBrushRun?.source_count || 0 }}</strong></div>
                    <div><span>规则过滤</span><strong>{{ latestBrushRun?.filtered_count || 0 }}</strong></div>
                    <div><span>新增下载</span><strong>{{ latestBrushRun?.added_count || 0 }}</strong></div>
                  </div>
                  <VAlert v-if="latestBrushRun?.error" type="error" variant="tonal" density="compact">
                    {{ latestBrushRun.error }}
                  </VAlert>
                  <VBtn variant="text" color="primary" append-icon="mdi-arrow-right" @click="activeTab = 'diagnostics'">
                    查看运行诊断
                  </VBtn>
                </VSheet>
              </div>

              <VSheet tag="section" class="brushflow-panel brushflow-torrents app-surface-static">
                <header class="brushflow-panel__head">
                  <div>
                    <div class="brushflow-panel__title-row">
                      <span class="text-subtitle-1 font-weight-medium">托管种子</span>
                      <VChip size="x-small" variant="tonal">{{ torrentData.total }}</VChip>
                    </div>
                    <div class="text-body-2 text-medium-emphasis">当前任务独立记录</div>
                  </div>
                  <VBtnToggle :model-value="torrentState" mandatory color="primary" density="compact" @update:model-value="changeTorrentState">
                    <VBtn value="active">活跃</VBtn>
                    <VBtn value="deleted">已删除</VBtn>
                    <VBtn value="all">全部</VBtn>
                  </VBtnToggle>
                </header>

                <VDataTable
                  class="brushflow-torrent-table"
                  :headers="torrentHeaders"
                  :items="torrentData.items"
                  :loading="taskLoading"
                  :items-per-page="-1"
                  hide-default-footer
                  density="comfortable"
                >
                  <template #item.title="{ item }">
                    <div class="torrent-title-cell">
                      <strong>{{ item.title || '未知种子' }}</strong>
                      <span>{{ item.site_name }} · {{ formatDateTime((item.time || 0) * 1000) }}</span>
                    </div>
                  </template>
                  <template #item.status="{ item }">
                    <VChip size="small" :color="item.deleted ? 'secondary' : torrentProgress(item) >= 100 ? 'success' : 'info'" variant="tonal">
                      {{ torrentStateText(item) }}
                    </VChip>
                  </template>
                  <template #item.size="{ item }">{{ formatBytes(item.size) }}</template>
                  <template #item.uploaded="{ item }">{{ formatBytes(item.uploaded) }}</template>
                  <template #item.ratio="{ item }">{{ Number(item.ratio || 0).toFixed(2) }}</template>
                  <template #item.policy="{ item }">{{ torrentPolicy(item) }}</template>
                  <template #no-data>
                    <div class="brushflow-table-empty">当前筛选下没有种子记录</div>
                  </template>
                </VDataTable>

                <div class="brushflow-mobile-torrents">
                  <article v-for="item in torrentData.items" :key="`${item.task_id}-${item.title}-${item.time}`" class="brushflow-mobile-torrent">
                    <div class="brushflow-mobile-torrent__head">
                      <strong>{{ item.title || '未知种子' }}</strong>
                      <VChip size="x-small" variant="tonal">{{ torrentStateText(item) }}</VChip>
                    </div>
                    <div class="brushflow-mobile-torrent__meta">
                      <span>{{ formatBytes(item.size) }}</span><span>上传 {{ formatBytes(item.uploaded) }}</span><span>分享率 {{ Number(item.ratio || 0).toFixed(2) }}</span>
                    </div>
                    <div class="text-body-2 text-medium-emphasis">{{ torrentPolicy(item) }}</div>
                  </article>
                  <div v-if="!torrentData.items.length" class="brushflow-table-empty">当前筛选下没有种子记录</div>
                </div>

                <VPagination
                  v-if="totalTorrentPages > 1"
                  :model-value="torrentPage"
                  :length="totalTorrentPages"
                  :total-visible="5"
                  density="comfortable"
                  @update:model-value="changeTorrentPage"
                />
              </VSheet>
            </VWindowItem>

            <VWindowItem value="diagnostics">
              <div class="brushflow-diagnostic-head">
                <div>
                  <div class="text-subtitle-1 font-weight-medium">
                    {{ latestBrushRun ? `刷流刷新 #${latestBrushRun.id.slice(0, 8)}` : '暂无刷流刷新记录' }}
                  </div>
                  <div class="text-body-2 text-medium-emphasis">
                    {{ latestBrushRun ? `${formatDateTime(latestBrushRun.started_at)} · ${formatDuration(latestBrushRun.started_at, latestBrushRun.finished_at)}` : '执行一次任务后将显示筛选流水线和过滤原因' }}
                  </div>
                </div>
                <VChip v-if="latestBrushRun" :color="latestBrushRun.success === false ? 'error' : 'success'" variant="tonal">
                  {{ latestBrushRun.success === false ? '失败' : '完成' }}
                </VChip>
              </div>

              <div class="brushflow-diagnostic-grid">
                <VSheet tag="section" class="brushflow-panel app-surface-static">
                  <header class="brushflow-panel__head">
                    <div>
                      <div class="text-subtitle-1 font-weight-medium">选种流水线</div>
                      <div class="text-body-2 text-medium-emphasis">本轮候选在各阶段的剩余数量</div>
                    </div>
                  </header>
                  <ol class="brushflow-pipeline">
                    <li v-for="(stage, index) in pipelineStages" :key="stage.title">
                      <span class="brushflow-pipeline__index">{{ index + 1 }}</span>
                      <div><strong>{{ stage.title }}</strong><span>{{ stage.detail }}</span></div>
                      <VChip size="small" variant="tonal">{{ stage.count }}</VChip>
                    </li>
                  </ol>
                </VSheet>

                <VSheet tag="section" class="brushflow-panel app-surface-static">
                  <header class="brushflow-panel__head">
                    <div>
                      <div class="text-subtitle-1 font-weight-medium">过滤原因</div>
                      <div class="text-body-2 text-medium-emphasis">本轮未进入下载器的候选分布</div>
                    </div>
                  </header>
                  <div v-if="reasonEntries.length" class="brushflow-reasons">
                    <div v-for="item in reasonEntries" :key="item.label" class="brushflow-reason">
                      <div><span>{{ item.label }}</span><strong>{{ item.count }}</strong></div>
                      <span class="brushflow-reason__track"><i :style="{ width: `${(item.count / maxReasonCount) * 100}%` }" /></span>
                    </div>
                  </div>
                  <div v-else class="brushflow-table-empty">本轮没有记录过滤原因</div>
                </VSheet>
              </div>

              <VSheet tag="section" class="brushflow-panel app-surface-static">
                <header class="brushflow-panel__head">
                  <div>
                    <div class="text-subtitle-1 font-weight-medium">最近事件</div>
                    <div class="text-body-2 text-medium-emphasis">刷流刷新与种子检查独立记录</div>
                  </div>
                </header>
                <div class="brushflow-events">
                  <article v-for="run in taskRuns" :key="run.id">
                    <VIcon
                      :icon="run.success === false ? 'mdi-alert-circle-outline' : run.kind === 'brush' ? 'mdi-sync' : 'mdi-progress-check'"
                      :color="run.success === false ? 'error' : run.kind === 'brush' ? 'primary' : 'info'"
                    />
                    <div>
                      <strong>{{ run.kind === 'brush' ? '刷流刷新' : '种子检查' }}</strong>
                      <span>
                        {{ formatDateTime(run.started_at) }} · {{ formatDuration(run.started_at, run.finished_at) }} ·
                        {{ run.kind === 'brush' ? `新增 ${run.added_count || 0}，过滤 ${run.filtered_count || 0}` : `活跃 ${run.active_count || 0}，删除 ${run.deleted_count || 0}` }}
                      </span>
                      <span v-if="run.error" class="text-error">{{ run.error }}</span>
                    </div>
                  </article>
                  <div v-if="!taskRuns.length" class="brushflow-table-empty">暂无运行事件</div>
                </div>
              </VSheet>
            </VWindowItem>

            <VWindowItem value="config">
              <div class="brushflow-config-grid">
                <VSheet tag="section" class="brushflow-panel app-surface-static">
                  <header class="brushflow-panel__head">
                    <div>
                      <div class="text-subtitle-1 font-weight-medium">任务规则</div>
                      <div class="text-body-2 text-medium-emphasis">当前服务端生效配置</div>
                    </div>
                  </header>
                  <dl class="brushflow-facts brushflow-facts--two">
                    <div><dt>任务状态</dt><dd>{{ selectedTask.enabled ? '启用' : '暂停' }}</dd></div>
                    <div><dt>通知</dt><dd>{{ taskConfig.notify ? '发送' : '关闭' }}</dd></div>
                    <div><dt>站点</dt><dd>{{ selectedTask.site_name }}</dd></div>
                    <div><dt>下载器</dt><dd>{{ selectedTask.downloader }}</dd></div>
                    <div><dt>种子大小</dt><dd>{{ taskConfig.size || '不限' }}</dd></div>
                    <div><dt>做种人数</dt><dd>{{ taskConfig.seeder || '不限' }}</dd></div>
                    <div><dt>发布时间</dt><dd>{{ taskConfig.pubtime ? `${taskConfig.pubtime} 分钟` : '不限' }}</dd></div>
                    <div><dt>排除 H&R</dt><dd>{{ taskConfig.hr === 'yes' ? '是' : '否' }}</dd></div>
                    <div><dt>包含规则</dt><dd>{{ taskConfig.include || '无' }}</dd></div>
                    <div><dt>排除规则</dt><dd>{{ taskConfig.exclude || '无' }}</dd></div>
                    <div><dt>保种上限</dt><dd>{{ taskConfig.disksize ? `${taskConfig.disksize} GB` : '不限' }}</dd></div>
                    <div><dt>归档天数</dt><dd>{{ taskConfig.auto_archive_days || '不自动归档' }}</dd></div>
                  </dl>
                </VSheet>

                <VSheet tag="section" class="brushflow-panel app-surface-static">
                  <header class="brushflow-panel__head">
                    <div>
                      <div class="text-subtitle-1 font-weight-medium">任务数据</div>
                      <div class="text-body-2 text-medium-emphasis">以下操作只影响当前任务</div>
                    </div>
                  </header>
                  <div class="brushflow-config-actions">
                    <div>
                      <strong>清除统计与记录</strong>
                      <span>下载器中的任务标签种子会在下次检查时重新纳入</span>
                      <VBtn color="warning" variant="tonal" prepend-icon="mdi-eraser" @click="clearDialog = true">清除数据</VBtn>
                    </div>
                    <VDivider />
                    <div>
                      <strong>删除任务</strong>
                      <span>存在活跃种子时后端会拒绝删除，避免留下失管任务</span>
                      <VBtn color="error" variant="tonal" prepend-icon="mdi-delete-outline" @click="deleteDialog = true">删除任务</VBtn>
                    </div>
                  </div>
                </VSheet>
              </div>
            </VWindowItem>
          </VWindow>
        </main>
      </div>
    </template>

    <TaskEditorDialog
      v-model="editorOpen"
      :task="editorTask"
      :sites="status.options.sites"
      :downloaders="status.options.downloaders"
      :saving="saving"
      @save="saveTask"
    />

    <VDialog v-model="deleteDialog" max-width="28rem">
      <VCard title="删除刷流任务">
        <VCardText>确认删除“{{ selectedTask?.name }}”？存在活跃种子时不会执行删除。</VCardText>
        <VCardActions>
          <VSpacer />
          <VBtn variant="text" @click="deleteDialog = false">取消</VBtn>
          <VBtn color="error" variant="flat" :loading="saving" @click="confirmDeleteTask">删除</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>

    <VDialog v-model="clearDialog" max-width="28rem">
      <VCard title="清除任务数据">
        <VCardText>将清除当前任务的统计、运行诊断、托管和归档记录，下载器内的种子与文件不会删除。</VCardText>
        <VCardActions>
          <VSpacer />
          <VBtn variant="text" @click="clearDialog = false">取消</VBtn>
          <VBtn color="warning" variant="flat" :loading="saving" @click="confirmClearTask">清除</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>

  </div>
</template>

<style scoped>
.brushflow-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-inline-size: 0;
  padding: 16px;
  color: rgb(var(--v-theme-on-background));
}

.brushflow-page--compact {
  padding: 20px;
}

.brushflow-page__header,
.brushflow-page__identity,
.brushflow-page__actions,
.brushflow-task-head,
.brushflow-task-head__identity,
.brushflow-task-head__title,
.brushflow-task-head__actions,
.brushflow-panel__head,
.brushflow-panel__title-row,
.brushflow-task-item__title,
.brushflow-task-item__meta,
.brushflow-mobile-torrent__head,
.brushflow-mobile-torrent__meta,
.brushflow-diagnostic-head {
  display: flex;
  align-items: center;
}

.brushflow-page__header,
.brushflow-task-head,
.brushflow-panel__head,
.brushflow-mobile-torrent__head,
.brushflow-diagnostic-head {
  justify-content: space-between;
}

.brushflow-page__header {
  min-block-size: 48px;
  gap: 16px;
}

.brushflow-page__identity,
.brushflow-task-head__identity {
  min-inline-size: 0;
  gap: 12px;
}

.brushflow-page__identity h1,
.brushflow-task-head h2 {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: 0;
}

.brushflow-page__identity p,
.brushflow-task-head p {
  margin: 2px 0 0;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.875rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.brushflow-page__actions,
.brushflow-task-head__actions,
.brushflow-task-head__title,
.brushflow-panel__title-row,
.brushflow-mobile-torrent__meta {
  flex-wrap: wrap;
  gap: 8px;
}

.settings-menu__body {
  display: grid;
  gap: 8px;
}

.brushflow-loading,
.brushflow-empty {
  min-block-size: 20rem;
}

.brushflow-empty {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 12px;
  text-align: center;
}

.brushflow-mobile-select {
  display: none;
}

.brushflow-layout {
  display: grid;
  grid-template-columns: minmax(13.5rem, 0.3fr) minmax(0, 1.7fr);
  align-items: start;
  gap: 18px;
  min-inline-size: 0;
}

.brushflow-task-rail {
  position: sticky;
  top: 76px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-block-size: calc(100dvh - 104px);
  padding: 12px;
  overflow-y: auto;
  border: var(--app-surface-border);
  border-radius: var(--app-surface-radius);
}

.brushflow-task-rail__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-inline: 4px;
}

.brushflow-task-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.brushflow-task-item {
  appearance: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  inline-size: 100%;
  padding: 11px 12px;
  border: 1px solid transparent;
  border-radius: var(--app-control-radius);
  color: rgb(var(--v-theme-on-surface));
  background: transparent;
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.brushflow-task-item:hover {
  background: rgba(var(--v-theme-primary), 0.05);
}

.brushflow-task-item:focus-visible {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}

.brushflow-task-item--selected {
  border-color: rgba(var(--v-theme-primary), 0.28);
  background: rgba(var(--v-theme-primary), 0.1);
}

.brushflow-task-item__title,
.brushflow-task-item__meta {
  justify-content: space-between;
  gap: 8px;
}

.brushflow-task-item__title strong {
  min-inline-size: 0;
  overflow-wrap: anywhere;
}

.brushflow-task-item > span:not(.brushflow-task-item__title) {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.78rem;
}

.brushflow-status-dot {
  inline-size: 8px;
  block-size: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: rgb(var(--v-theme-secondary));
}

.brushflow-status-dot--success { background: rgb(var(--v-theme-success)); }
.brushflow-status-dot--primary { background: rgb(var(--v-theme-primary)); }
.brushflow-status-dot--info { background: rgb(var(--v-theme-info)); }
.brushflow-status-dot--warning { background: rgb(var(--v-theme-warning)); }
.brushflow-status-dot--error { background: rgb(var(--v-theme-error)); }

.brushflow-workspace {
  min-inline-size: 0;
}

.brushflow-task-head {
  min-block-size: 52px;
  gap: 12px;
  margin-block-end: 12px;
}

.brushflow-tabs {
  max-inline-size: 100%;
}

.brushflow-window {
  padding-block-start: 16px;
}

.brushflow-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.brushflow-stat,
.brushflow-panel {
  border: var(--app-surface-border);
  border-radius: var(--app-surface-radius);
}

.brushflow-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-block-size: 116px;
  padding: 16px;
}

.brushflow-stat > span,
.brushflow-stat > small {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}

.brushflow-stat > strong {
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.brushflow-stat :deep(.v-progress-linear) {
  margin-block-start: auto;
}

.brushflow-overview-grid,
.brushflow-diagnostic-grid,
.brushflow-config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-block-start: 12px;
}

.brushflow-panel {
  min-inline-size: 0;
  padding: 16px;
}

.brushflow-panel__head,
.brushflow-diagnostic-head {
  align-items: flex-start;
  gap: 12px;
}

.brushflow-facts {
  display: grid;
  gap: 11px;
  margin: 18px 0 0;
}

.brushflow-facts--two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.brushflow-facts > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  min-inline-size: 0;
}

.brushflow-facts dt {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}

.brushflow-facts dd {
  margin: 0;
  text-align: end;
  overflow-wrap: anywhere;
}

.brushflow-run-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-block: 20px;
}

.brushflow-run-summary > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.brushflow-run-summary span {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.8rem;
}

.brushflow-run-summary strong {
  font-size: 1.2rem;
}

.brushflow-torrents {
  margin-block-start: 12px;
}

.brushflow-torrent-table {
  margin-block-start: 8px;
  background: transparent;
}

.torrent-title-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-inline-size: 30rem;
}

.torrent-title-cell strong,
.torrent-title-cell span {
  overflow-wrap: anywhere;
}

.torrent-title-cell span {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.78rem;
}

.brushflow-table-empty {
  padding: 28px 12px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  text-align: center;
}

.brushflow-mobile-torrents {
  display: none;
}

.brushflow-diagnostic-head {
  margin-block-end: 12px;
}

.brushflow-pipeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.brushflow-pipeline li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding-block: 7px;
}

.brushflow-pipeline li > div,
.brushflow-events article > div,
.brushflow-config-actions > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-inline-size: 0;
}

.brushflow-pipeline li span,
.brushflow-events article span,
.brushflow-config-actions span {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.82rem;
  overflow-wrap: anywhere;
}

.brushflow-pipeline__index {
  display: grid;
  place-items: center;
  inline-size: 28px;
  block-size: 28px;
  border-radius: 50%;
  color: rgb(var(--v-theme-on-primary));
  background: rgb(var(--v-theme-primary));
  font-size: 0.78rem;
}

.brushflow-reasons {
  display: flex;
  flex-direction: column;
  gap: 13px;
  margin-block-start: 18px;
}

.brushflow-reason > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-block-end: 5px;
}

.brushflow-reason__track {
  display: block;
  block-size: 6px;
  overflow: hidden;
  border-radius: 3px;
  background: rgba(var(--v-theme-on-surface), 0.08);
}

.brushflow-reason__track i {
  display: block;
  block-size: 100%;
  border-radius: inherit;
  background: rgb(var(--v-theme-warning));
}

.brushflow-events {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-block-start: 16px;
}

.brushflow-events article {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 10px;
}

.brushflow-config-actions {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-block-start: 16px;
}

.brushflow-config-actions :deep(.v-btn) {
  align-self: flex-start;
  margin-block-start: 8px;
}

@media (max-width: 1199px) {
  .brushflow-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 959px) {
  .brushflow-page {
    padding: 12px;
  }

  .brushflow-page--compact {
    padding-block-start: 0;
  }

  .brushflow-page--compact .brushflow-page__header {
    position: sticky;
    top: 0;
    z-index: 4;
    margin-inline: -12px;
    padding: 12px;
    border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
    backdrop-filter: blur(var(--transparent-blur, 0px));
    background-color: rgba(var(--v-theme-surface), var(--transparent-opacity-heavy, 1));
  }

  .brushflow-page__header,
  .brushflow-task-head {
    align-items: flex-start;
  }

  .brushflow-task-rail {
    display: none;
  }

  .brushflow-mobile-select {
    display: block;
  }

  .brushflow-layout {
    grid-template-columns: 1fr;
  }

  .brushflow-overview-grid,
  .brushflow-diagnostic-grid,
  .brushflow-config-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 699px) {
  .brushflow-task-head {
    flex-direction: column;
  }

  .brushflow-page__header {
    align-items: center;
    flex-direction: row;
  }

  .brushflow-page__identity {
    flex: 1 1 auto;
    overflow: hidden;
  }

  .brushflow-page__identity > div {
    min-inline-size: 0;
  }

  .brushflow-page__identity h1,
  .brushflow-page__identity p {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .brushflow-page--compact .brushflow-page__header {
    align-items: center;
    flex-direction: row;
  }

  .brushflow-task-head__actions {
    inline-size: 100%;
  }

  .brushflow-page__actions,
  .brushflow-page--compact .brushflow-page__actions {
    flex: 0 0 auto;
    flex-wrap: nowrap;
    inline-size: auto;
    margin-inline-start: auto;
  }

  .brushflow-page--compact .brushflow-page__actions > :deep(.v-chip),
  .brushflow-page--compact .brushflow-page__identity p {
    display: none;
  }

  .brushflow-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .brushflow-stat {
    min-block-size: 104px;
    padding: 13px;
  }

  .brushflow-stat > strong {
    font-size: 1.05rem;
  }

  .brushflow-panel {
    padding: 14px;
  }

  .brushflow-panel__head {
    flex-wrap: wrap;
  }

  .brushflow-facts--two {
    grid-template-columns: 1fr;
  }

  .brushflow-torrent-table {
    display: none;
  }

  .brushflow-mobile-torrents {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-block-start: 12px;
  }

  .brushflow-mobile-torrent {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding-block: 13px;
    border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  }

  .brushflow-mobile-torrent__head {
    align-items: flex-start;
    gap: 8px;
  }

  .brushflow-mobile-torrent__head strong {
    min-inline-size: 0;
    overflow-wrap: anywhere;
  }

  .brushflow-run-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 419px) {
  .brushflow-stat-grid {
    grid-template-columns: 1fr;
  }

  .brushflow-page:not(.brushflow-page--compact) .brushflow-page__identity p {
    display: none;
  }

  .brushflow-page:not(.brushflow-page--compact) .brushflow-page__header,
  .brushflow-page:not(.brushflow-page--compact) .brushflow-page__identity {
    gap: 8px;
  }

  .brushflow-task-head__title {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
