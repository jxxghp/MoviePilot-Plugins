<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  ACTIONS,
  FILTERS,
  filterResources,
  formatBytes,
  formatGiB,
  issueKey,
  unwrapResponse,
} from '../provider.js'
import { refreshFeedback } from '../refresh-feedback.js'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'StorageCleanup' },
  hideTitle: { type: Boolean, default: false },
})

const emptySnapshot = {
  schemaVersion: 2,
  snapshotId: '',
  generatedAt: '',
  stats: {},
  resources: [],
}

const snapshot = ref(emptySnapshot)
const health = ref({})
const loading = ref(true)
const refreshing = ref(false)
const refreshElapsed = ref(0)
const error = ref('')
const search = ref('')
const activeFilter = ref('all')
const safeOnly = ref(false)
const descending = ref(true)
const selected = ref([])

const planOpen = ref(false)
const planMode = ref(null)
const plan = ref(null)
const planLoading = ref(false)
const planError = ref('')
const acknowledgeSiteRisk = ref(false)
const finalConfirmation = ref(false)
const executing = ref(false)
const executeError = ref('')
const executeResult = ref(null)

const gapOpen = ref(false)
const gapLoading = ref(false)
const gaps = ref([])
const gapError = ref('')

const recoveryOpen = ref(false)
const recoveryLoading = ref(false)
const recoveries = ref([])
const recoveryError = ref('')
const recoveryTarget = ref(null)
const recoveryAction = ref(null)
const recoveryPhrase = ref('')
const recovering = ref(false)

const pluginBase = computed(() => `plugin/${props.pluginId || 'StorageCleanup'}`)
const resources = computed(() => snapshot.value.resources || [])
const visible = computed(() => filterResources(resources.value, {
  filter: activeFilter.value,
  search: search.value,
  safeOnly: safeOnly.value,
  descending: descending.value,
}))
const selectedItems = computed(() => resources.value.filter(item => selected.value.includes(item.id)))
const selectedSize = computed(() => selectedItems.value.reduce((total, item) => total + Number(item.size || 0), 0))
const executionEnabled = computed(() => Boolean(health.value.executionEnabled))
const inventoryCurrent = computed(() => health.value.inventoryCurrent !== false)
const unresolvedTransactions = computed(() => Number(snapshot.value.stats?.unresolvedTransactions || 0))
const hrGap = computed(() => Math.max(
  0,
  Number(
    snapshot.value.stats?.hrMissingQbTasks ??
    Number(snapshot.value.stats?.hrActiveTitles || 0) - Number(snapshot.value.stats?.hrMatchedQbTasks || 0),
  ),
))
const hrUnassigned = computed(() => Number(
  snapshot.value.stats?.hrMissingUnassigned ??
  snapshot.value.stats?.hrMissingUncovered ??
  0,
))
const filters = computed(() => FILTERS.map(filter => ({
  ...filter,
  count: resources.value.filter(item => {
    if (filter.id === 'all') return true
    return filterResources([item], {
      filter: filter.id,
      search: '',
      safeOnly: false,
      descending: true,
    }).length === 1
  }).length,
})))
const allVisibleSelected = computed(() => {
  const selectable = visible.value.filter(item => !item.protected)
  return selectable.length > 0 && selectable.every(item => selected.value.includes(item.id))
})
const currentAction = computed(() => planMode.value ? ACTIONS[planMode.value] : null)
const planExpired = computed(() => Boolean(plan.value && Date.parse(plan.value.expiresAt) <= Date.now()))
const refreshMessage = computed(() => {
  if (!refreshing.value) return ''
  return refreshFeedback(refreshElapsed.value)
})

let refreshTimer = null

function stopRefreshTimer() {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

function startRefreshTimer() {
  stopRefreshTimer()
  refreshElapsed.value = 0
  refreshTimer = setInterval(() => {
    refreshElapsed.value += 1
  }, 1000)
}

function payloadError(payload, fallback) {
  return payload?.error?.message || fallback
}

async function get(path) {
  return unwrapResponse(await props.api.get(`${pluginBase.value}${path}`))
}

async function post(path, body) {
  return unwrapResponse(await props.api.post(`${pluginBase.value}${path}`, body))
}

function acceptSnapshot(next) {
  if (!next || next.schemaVersion !== 2 || !next.snapshotId || !Array.isArray(next.resources)) {
    throw new Error('资源快照格式不受支持。')
  }
  snapshot.value = next
  const available = new Set(next.resources.map(item => item.id))
  selected.value = selected.value.filter(id => available.has(id))
}

async function loadStatus() {
  loading.value = true
  error.value = ''
  try {
    const payload = await get('/status')
    if (!payload?.ok || !payload.snapshot) throw new Error(payloadError(payload, '无法读取清理台状态。'))
    health.value = payload.health || {}
    acceptSnapshot(payload.snapshot)
  } catch (err) {
    error.value = err?.message || '无法读取清理台状态。'
  } finally {
    loading.value = false
  }
}

async function refreshSnapshot() {
  if (refreshing.value) return
  refreshing.value = true
  startRefreshTimer()
  error.value = ''
  try {
    const payload = await post('/refresh', {})
    if (!payload?.ok || !payload.snapshot) throw new Error(payloadError(payload, '刷新失败。'))
    acceptSnapshot(payload.snapshot)
    health.value = { ...health.value, inventoryCurrent: true }
  } catch (err) {
    error.value = err?.message || '刷新失败，继续显示上次快照。'
    health.value = { ...health.value, inventoryCurrent: false }
  } finally {
    stopRefreshTimer()
    refreshing.value = false
  }
}

function toggle(item) {
  if (item.protected) return
  selected.value = selected.value.includes(item.id)
    ? selected.value.filter(id => id !== item.id)
    : [...selected.value, item.id]
}

function toggleVisible() {
  const ids = visible.value.filter(item => !item.protected).map(item => item.id)
  selected.value = allVisibleSelected.value
    ? selected.value.filter(id => !ids.includes(id))
    : [...new Set([...selected.value, ...ids])]
}

async function requestPlan(mode, acknowledged = false) {
  planLoading.value = true
  planError.value = ''
  plan.value = null
  finalConfirmation.value = false
  try {
    const payload = await post('/plan', {
      snapshotId: snapshot.value.snapshotId,
      resourceIds: selected.value,
      mode,
      acknowledgeSiteRisk: acknowledged,
    })
    if (!payload?.ok || !payload.plan) throw new Error(payloadError(payload, '无法生成执行计划。'))
    plan.value = payload.plan
  } catch (err) {
    planError.value = err?.message || '无法生成执行计划。'
  } finally {
    planLoading.value = false
  }
}

function openPlan(mode) {
  planMode.value = mode
  planOpen.value = true
  acknowledgeSiteRisk.value = false
  executeResult.value = null
  executeError.value = ''
  requestPlan(mode, false)
}

function closePlan() {
  if (executing.value) return
  planOpen.value = false
  planMode.value = null
  plan.value = null
  planError.value = ''
  finalConfirmation.value = false
  executeResult.value = null
}

async function setSiteRisk(value) {
  acknowledgeSiteRisk.value = value
  await requestPlan(planMode.value, value)
}

async function executePlan() {
  if (!plan.value || planExpired.value || executing.value) return
  executing.value = true
  executeError.value = ''
  try {
    const payload = await post('/execute', {
      planId: plan.value.planId,
      confirmPhrase: plan.value.confirmPhrase,
    })
    if (!payload?.ok || !payload.result) {
      if (payload?.error?.plan) plan.value = payload.error.plan
      throw new Error(payloadError(payload, '执行失败。'))
    }
    executeResult.value = payload.result
    selected.value = []
    if (payload.result.snapshotRefreshPending) {
      health.value = { ...health.value, inventoryCurrent: false }
    } else {
      const latest = await get('/snapshot')
      if (latest?.snapshot) acceptSnapshot(latest.snapshot)
    }
  } catch (err) {
    executeError.value = err?.message || '执行失败。'
    finalConfirmation.value = false
  } finally {
    executing.value = false
  }
}

async function loadGaps() {
  gapOpen.value = true
  gapLoading.value = true
  gapError.value = ''
  try {
    const payload = await get('/protection-gaps')
    if (!payload?.ok) throw new Error(payloadError(payload, '无法读取 H&R 缺口。'))
    gaps.value = payload.gaps || []
  } catch (err) {
    gapError.value = err?.message || '无法读取 H&R 缺口。'
  } finally {
    gapLoading.value = false
  }
}

async function loadRecoveries() {
  recoveryOpen.value = true
  recoveryLoading.value = true
  recoveryError.value = ''
  recoveryTarget.value = null
  try {
    const payload = await get('/recovery')
    if (!payload?.ok) throw new Error(payloadError(payload, '无法读取恢复状态。'))
    recoveries.value = payload.recoveries || []
  } catch (err) {
    recoveryError.value = err?.message || '无法读取恢复状态。'
  } finally {
    recoveryLoading.value = false
  }
}

function chooseRecovery(item, action) {
  recoveryTarget.value = item
  recoveryAction.value = action
  recoveryPhrase.value = ''
  recoveryError.value = ''
}

async function runRecovery() {
  if (!recoveryTarget.value || !recoveryAction.value || recovering.value) return
  recovering.value = true
  recoveryError.value = ''
  try {
    const payload = await post('/recovery', {
      planId: recoveryTarget.value.planId,
      action: recoveryAction.value,
      confirmPhrase: recoveryPhrase.value,
    })
    if (!payload?.ok) throw new Error(payloadError(payload, '恢复操作失败。'))
    await refreshSnapshot()
    await loadRecoveries()
  } catch (err) {
    recoveryError.value = err?.message || '恢复操作失败。'
  } finally {
    recovering.value = false
  }
}

function recoveryExpectedPhrase() {
  if (!recoveryTarget.value || !recoveryAction.value) return ''
  return recoveryAction.value === 'rollback'
    ? recoveryTarget.value.rollbackPhrase
    : recoveryTarget.value.finalizePhrase
}

onMounted(loadStatus)
onUnmounted(stopRefreshTimer)
</script>

<template>
  <main class="cleanup-app">
    <header v-if="!hideTitle" class="page-header">
      <div>
        <p class="eyebrow">安全清理台</p>
        <h1>存储清理</h1>
        <span>一部电影一行，一部剧一行；先看清影响，再选择清理等级。</span>
      </div>
      <div :class="['status-card', { danger: error || !inventoryCurrent }]">
        <i>{{ error || !inventoryCurrent ? '!' : '✓' }}</i>
        <p>
          <strong>{{ error || (executionEnabled ? '执行链路已连接' : '只读模式') }}</strong>
          <span v-if="snapshot.generatedAt">更新于 {{ snapshot.generatedAt.slice(5, 16).replace('T', ' ') }}</span>
        </p>
      </div>
    </header>

    <section class="toolbar">
      <label class="search">
        <span>⌕</span>
        <input v-model="search" aria-label="搜索资源" placeholder="搜索电影、剧集、季度或站点">
      </label>
      <label class="safe-toggle">
        <input v-model="safeOnly" type="checkbox">
        <span />
        仅看无做种限制
      </label>
      <button class="soft-button" type="button" @click="descending = !descending">
        实际占用 {{ descending ? '↓' : '↑' }}
      </button>
      <button
        class="icon-button"
        type="button"
        :disabled="refreshing"
        :aria-label="refreshing ? '正在刷新资源清单' : '刷新资源清单'"
        :aria-busy="refreshing"
        :title="refreshMessage || '刷新资源清单'"
        @click="refreshSnapshot"
      >
        {{ refreshing ? '…' : '↻' }}
      </button>
      <p v-if="refreshing" class="refresh-feedback" role="status" aria-live="polite">
        {{ refreshMessage }}
      </p>
    </section>

    <button
      v-if="unresolvedTransactions"
      class="notice critical"
      type="button"
      @click="loadRecoveries"
    >
      <i>!</i>
      <p>
        <strong>{{ unresolvedTransactions }} 个未完成清理事务</strong>
        <span>新操作已锁定；请先核对并恢复原事务。</span>
      </p>
      <b>查看恢复状态</b>
    </button>

    <button
      v-else-if="hrGap"
      :class="['notice', { warning: hrUnassigned }]"
      type="button"
      @click="loadGaps"
    >
      <i>H</i>
      <p>
        <strong>{{ hrGap }} 个学校站 H&R 尚未恢复完成</strong>
        <span>
          {{ hrUnassigned
            ? `${hrUnassigned} 个未精确关联媒体；不会锁定无关资源。`
            : '缺失任务只锁定精确关联资源，其他资源可独立清理。' }}
        </span>
      </p>
      <b>查看明细</b>
    </button>

    <nav class="filters" aria-label="资源筛选">
      <button
        v-for="filter in filters"
        :key="filter.id"
        :class="{ active: activeFilter === filter.id }"
        type="button"
        @click="activeFilter = filter.id"
      >
        {{ filter.label }} <span>{{ filter.count }}</span>
      </button>
    </nav>

    <section class="resource-card">
      <div class="table-head">
        <button class="select-all" type="button" @click="toggleVisible">
          {{ allVisibleSelected ? '✓' : '' }}
        </button>
        <span>资源</span>
        <span>媒体库</span>
        <span>做种与保护</span>
        <span>实际占用</span>
        <span>完整删除影响</span>
      </div>

      <div v-if="loading" class="empty-state">正在读取真实资源关系…</div>
      <article
        v-for="item in visible"
        v-else
        :key="item.id"
        :class="['resource-row', { selected: selected.includes(item.id) }]"
      >
        <button
          :class="['row-check', { locked: item.protected }]"
          type="button"
          :disabled="item.protected"
          @click="toggle(item)"
        >
          {{ item.protected ? '锁' : selected.includes(item.id) ? '✓' : '' }}
        </button>

        <div class="resource-title">
          <strong>{{ item.title }}</strong>
          <b>{{ item.englishTitle }}</b>
          <span>{{ [item.type, item.year, item.edition].filter(Boolean).join(' · ') }}</span>
        </div>

        <div class="stack-cell library" data-label="媒体库">
          <strong>{{ item.librarySummary }}</strong>
          <span>{{ item.libraryDetail }}</span>
        </div>

        <div class="seed-cell" data-label="做种与保护">
          <template v-if="item.seedTasks?.length">
            <div
              v-for="(task, index) in item.seedTasks"
              :key="`${task.site}-${task.scope}-${index}`"
              :class="['seed-task', task.tone]"
            >
              <i>{{ task.status }}</i>
              <strong>{{ task.site }}</strong>
              <span>{{ task.scope }}{{ task.count > 1 ? ` · ${task.count} 个任务` : '' }}</span>
            </div>
          </template>
          <div v-else class="stack-cell">
            <strong>{{ item.qbSummary }}</strong>
            <span>{{ item.siteSummary }}</span>
          </div>
        </div>

        <div class="stack-cell size" data-label="实际占用">
          <strong>{{ item.sizeLabel }}</strong>
          <span>{{ item.reclaimLabel }}</span>
        </div>

        <div
          :class="['impact', { danger: item.protected }]"
          data-label="完整删除影响"
        >
          <strong>{{ item.impactTitle }}</strong>
          <span>{{ item.impactDetail }}</span>
        </div>
      </article>

      <div v-if="!loading && !visible.length" class="empty-state">
        没有符合条件的资源，请取消筛选或更换关键词。
      </div>
    </section>

    <Teleport to="body">
      <aside v-if="selected.length" class="action-bar">
        <div class="selected-count">{{ selected.length }}</div>
        <p>
          <strong>已加入清理计划</strong>
          <span>完整删除上限 {{ formatGiB(selectedSize) }}</span>
        </p>
        <button class="clear-button" type="button" @click="selected = []">清空</button>
        <div class="action-buttons">
          <button
            v-for="(action, mode) in ACTIONS"
            :key="mode"
            :class="['action-level', { delete: mode === 'delete' }]"
            type="button"
            @click="openPlan(mode)"
          >
            <strong>{{ action.title }}</strong>
            <span>{{ action.detail }}</span>
          </button>
        </div>
      </aside>

      <div v-if="planOpen" class="modal-backdrop" @click.self="closePlan">
        <section class="modal plan-modal" role="dialog" aria-modal="true">
        <header>
          <div>
            <span>清理等级 · 真实预演</span>
            <h2>{{ currentAction?.title }}</h2>
          </div>
          <button type="button" :disabled="executing" @click="closePlan">×</button>
        </header>

        <div :class="['mode-summary', planMode]">
          <strong v-if="plan && planMode === 'delete'">已核算可释放 {{ formatBytes(plan.estimatedReclaimBytes) }}</strong>
          <strong v-else>{{ currentAction?.detail }}</strong>
          <span>
            {{ planMode === 'pause'
              ? '只改变 qB 运行状态，不删除任务或文件。'
              : planMode === 'retire'
                ? '移除 qB 任务但保留文件，媒体库继续可播放。'
                : '仅当全部路径、硬链接、H&R 与任务状态通过校验才会放行。' }}
          </span>
        </div>

        <div class="plan-resources">
          <div v-for="item in selectedItems" :key="item.id">
            <p><strong>{{ item.title }}</strong><span>{{ item.englishTitle }} · {{ item.edition }}</span></p>
            <b>{{ item.sizeLabel }}</b>
          </div>
        </div>

        <div v-if="planLoading" class="plan-state">正在刷新 NAS 状态并复核关系…</div>
        <div v-else-if="planError" class="plan-state blocked">
          <strong>无法生成计划</strong><span>{{ planError }}</span>
        </div>
        <template v-else-if="plan">
          <div :class="['plan-state', plan.canExecute ? 'passed' : 'blocked']">
            <strong>{{ plan.canExecute ? '安全预演通过' : '计划已被安全门禁拦截' }}</strong>
            <span>
              停止 {{ plan.operationCounts.qbStop }} 个任务 ·
              退出 {{ plan.operationCounts.qbRemoveKeepFiles }} 个任务 ·
              解除 {{ plan.operationCounts.unlinkFiles }} 个文件入口
            </span>
          </div>
          <ul v-if="plan.blocks?.length" class="issues blocked">
            <li v-for="(issue, index) in plan.blocks" :key="issueKey(issue, index)">{{ issue.message }}</li>
          </ul>
          <ul v-if="plan.warnings?.length" class="issues warning">
            <li v-for="(issue, index) in plan.warnings" :key="issueKey(issue, index)">{{ issue.message }}</li>
          </ul>
          <label v-if="plan.requiresSiteAcknowledgement" class="risk-check">
            <input
              :checked="acknowledgeSiteRisk"
              type="checkbox"
              @change="setSiteRisk($event.target.checked)"
            >
            <span />
            我已确认会影响私有站做种，并接受站点规则风险
          </label>
          <div v-if="planExpired" class="plan-state blocked">
            <strong>安全预演已过期</strong><span>请关闭后重新生成。</span>
          </div>
        </template>

        <div class="safety-note">
          <i>盾</i>
          <p>
            <strong>{{ executionEnabled ? '执行前还需第二次确认' : '执行引擎未启用' }}</strong>
            <span>最终执行前会重新读取 qB、路径、硬链接和保护状态。</span>
          </p>
        </div>

        <div v-if="executeResult" class="execution-result">
          <strong>{{ currentAction?.title }}已完成</strong>
          <span>
            停止 {{ executeResult.qbStopped }} · 退出 {{ executeResult.qbRemoved }} ·
            删除文件入口 {{ executeResult.filesDeleted }} · 清理索引 {{ executeResult.moviepilotIndexesDeleted }}
          </span>
          <button type="button" @click="closePlan">完成</button>
        </div>
        <div v-else-if="finalConfirmation" class="final-confirmation">
          <strong>再次确认：系统将立即执行这份计划</strong>
          <span v-if="executeError" class="error-text">{{ executeError }}</span>
          <div>
            <button type="button" :disabled="executing" @click="finalConfirmation = false">返回</button>
            <button
              :class="{ danger: planMode === 'delete' }"
              type="button"
              :disabled="executing || planExpired"
              @click="executePlan"
            >
              {{ executing ? '正在二次复核…' : `确认${currentAction?.title}` }}
            </button>
          </div>
        </div>
        <button
          v-else
          class="confirm-button"
          type="button"
          :disabled="!executionEnabled || !plan?.canExecute || planExpired"
          @click="finalConfirmation = true"
        >
          进入最终确认
        </button>
        </section>
      </div>

      <div v-if="gapOpen" class="modal-backdrop" @click.self="gapOpen = false">
        <section class="modal compact-modal">
          <header><div><span>学校站实时保护</span><h2>H&R 缺口明细</h2></div><button @click="gapOpen = false">×</button></header>
          <div v-if="gapLoading" class="empty-state">正在核对…</div>
          <div v-if="gapError" class="plan-state blocked">{{ gapError }}</div>
          <div v-for="item in gaps" :key="item.title" class="gap-row">
            <p><strong>{{ item.title }}</strong><span>{{ item.linkedResourceTitle || '尚未精确关联媒体' }}</span></p>
            <b>{{ item.qbTaskPresent ? 'qB 已存在' : item.coveredByCandidate ? '候选恢复中' : '任务缺失' }}</b>
          </div>
        </section>
      </div>

      <div v-if="recoveryOpen" class="modal-backdrop" @click.self="recoveryOpen = false">
        <section class="modal compact-modal">
          <header><div><span>失败关闭</span><h2>恢复未完成清理</h2></div><button @click="recoveryOpen = false">×</button></header>
          <div v-if="recoveryLoading" class="empty-state">正在读取事务…</div>
          <div v-if="recoveryError" class="plan-state blocked">{{ recoveryError }}</div>
          <div v-for="item in recoveries" :key="item.planId" class="recovery-row">
            <p><strong>{{ item.mode }} · {{ item.phase }}</strong><span>{{ item.planId.slice(-10) }}</span></p>
            <button type="button" @click="chooseRecovery(item, 'rollback')">回滚</button>
            <button type="button" @click="chooseRecovery(item, 'finalize')">完成原事务</button>
          </div>
          <div v-if="recoveryTarget" class="recovery-confirm">
            <label>输入确认短语 <code>{{ recoveryExpectedPhrase() }}</code></label>
            <input v-model="recoveryPhrase" autocomplete="off">
            <button
              type="button"
              :disabled="recovering || recoveryPhrase !== recoveryExpectedPhrase()"
              @click="runRecovery"
            >
              {{ recovering ? '处理中…' : '执行恢复' }}
            </button>
          </div>
        </section>
      </div>
    </Teleport>
  </main>
</template>

<style scoped>
.cleanup-app, .action-bar, .modal-backdrop {
  --ink: rgb(var(--v-theme-on-background, 30, 41, 59));
  --muted: rgba(var(--v-theme-on-background, 30, 41, 59), .58);
  --line: rgba(var(--v-border-color, 100, 116, 139), .18);
  --surface: rgb(var(--v-theme-surface, 255, 255, 255));
  --primary: rgb(var(--v-theme-primary, 59, 130, 246));
  --primary-soft: rgba(var(--v-theme-primary, 59, 130, 246), .10);
  --good: #16836b;
  --warn: #b86b11;
  --danger: #c44b47;
}
.cleanup-app {
  color: var(--ink);
  min-width: 980px;
  padding: 18px 24px 110px;
}
button, input { font: inherit; }
button { color: inherit; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
}
.eyebrow { margin: 0 0 4px; color: var(--primary); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.page-header h1 { margin: 0; font-size: 30px; line-height: 1.2; }
.page-header > div > span { color: var(--muted); font-size: 14px; }
.status-card {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 220px;
  padding: 10px 14px;
  border: 1px solid rgba(22, 131, 107, .22);
  border-radius: 12px;
  background: rgba(22, 131, 107, .08);
}
.status-card.danger { border-color: rgba(196, 75, 71, .24); background: rgba(196, 75, 71, .08); }
.status-card i, .notice i, .safety-note i {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: rgba(22, 131, 107, .12);
  color: var(--good);
  font-style: normal;
  font-weight: 900;
}
.status-card p, .notice p, .safety-note p, .plan-resources p, .gap-row p, .recovery-row p { display: grid; gap: 2px; margin: 0; }
.status-card strong { font-size: 13px; }
.status-card span { color: var(--muted); font-size: 12px; }
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}
.search {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  height: 46px;
  padding: 0 15px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
}
.search span { color: var(--muted); font-size: 21px; }
.search input { width: 100%; border: 0; outline: 0; color: inherit; background: transparent; font-size: 15px; }
.safe-toggle { display: flex; align-items: center; gap: 8px; height: 44px; white-space: nowrap; font-size: 14px; font-weight: 650; }
.safe-toggle input, .risk-check input { position: absolute; opacity: 0; }
.safe-toggle > span {
  width: 38px;
  height: 22px;
  padding: 3px;
  border-radius: 99px;
  background: rgba(100, 116, 139, .24);
}
.safe-toggle > span::after { display: block; width: 16px; height: 16px; border-radius: 50%; background: white; content: ''; transition: .2s; }
.safe-toggle input:checked + span { background: var(--primary); }
.safe-toggle input:checked + span::after { transform: translateX(16px); }
.soft-button, .icon-button {
  height: 42px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--surface);
  cursor: pointer;
}
.soft-button { padding: 0 14px; }
.icon-button { width: 42px; font-size: 20px; }
.refresh-feedback {
  flex: 0 0 100%;
  margin: -2px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.notice {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  margin: 0 0 14px;
  padding: 12px 16px;
  border: 1px solid rgba(184, 107, 17, .22);
  border-radius: 12px;
  background: rgba(184, 107, 17, .07);
  text-align: left;
  cursor: pointer;
}
.notice p { flex: 1; }
.notice p span { color: var(--muted); font-size: 13px; }
.notice b { color: var(--warn); font-size: 13px; }
.notice.critical { border-color: rgba(196, 75, 71, .25); background: rgba(196, 75, 71, .08); }
.notice.critical b { color: var(--danger); }
.filters { display: flex; gap: 6px; margin-bottom: 12px; }
.filters button {
  padding: 8px 13px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}
.filters button.active { border-color: var(--line); background: var(--surface); color: var(--ink); font-weight: 750; box-shadow: 0 4px 12px rgba(15, 23, 42, .04); }
.filters span { margin-left: 5px; padding: 2px 6px; border-radius: 99px; background: rgba(100, 116, 139, .10); font-size: 11px; }
.resource-card { overflow: hidden; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }
.table-head, .resource-row {
  display: grid;
  grid-template-columns: 42px minmax(270px, 1.55fr) minmax(170px, .85fr) minmax(360px, 1.65fr) minmax(125px, .65fr) minmax(230px, 1fr);
  align-items: center;
}
.table-head { min-height: 50px; padding: 0 16px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 12px; font-weight: 800; }
.resource-row { min-height: 126px; padding: 0 16px; border-bottom: 1px solid var(--line); }
.resource-row:last-child { border-bottom: 0; }
.resource-row.selected { background: var(--primary-soft); }
.select-all, .row-check {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid rgba(100, 116, 139, .35);
  border-radius: 7px;
  background: transparent;
  cursor: pointer;
}
.row-check.locked { border-color: rgba(184, 107, 17, .25); background: rgba(184, 107, 17, .08); color: var(--warn); font-size: 10px; cursor: not-allowed; }
.resource-title, .stack-cell { display: grid; gap: 4px; min-width: 0; padding-right: 16px; }
.resource-title strong { font-size: 17px; }
.resource-title b { overflow: hidden; color: var(--ink); font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; opacity: .78; }
.resource-title span, .stack-cell span, .impact span, .seed-task span { color: var(--muted); font-size: 12px; line-height: 1.45; }
.stack-cell strong { font-size: 14px; }
.stack-cell.library strong { color: var(--good); }
.stack-cell.size strong { font-size: 16px; }
.seed-cell { display: grid; gap: 4px; padding-right: 18px; }
.seed-task {
  display: grid;
  grid-template-columns: 62px minmax(72px, auto) minmax(100px, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 28px;
  padding-left: 8px;
  border-left: 2px solid rgba(100, 116, 139, .28);
}
.seed-task i { padding: 4px 8px; border-radius: 99px; background: rgba(100, 116, 139, .1); font-size: 11px; font-style: normal; font-weight: 800; text-align: center; white-space: nowrap; }
.seed-task strong { font-size: 13px; }
.seed-task.warning { border-color: rgba(184, 107, 17, .45); }
.seed-task.warning i { color: var(--warn); background: rgba(184, 107, 17, .1); }
.seed-task.protected { border-color: rgba(196, 75, 71, .45); }
.seed-task.protected i { color: var(--danger); background: rgba(196, 75, 71, .1); }
.impact { display: grid; gap: 4px; padding-left: 10px; border-left: 2px solid rgba(22, 131, 107, .35); }
.impact strong { font-size: 13px; }
.impact.danger { border-color: rgba(196, 75, 71, .5); }
.impact.danger strong { color: var(--danger); }
.empty-state { display: grid; place-items: center; min-height: 150px; color: var(--muted); }
.action-bar {
  position: fixed;
  z-index: 20;
  right: 30px;
  bottom: 22px;
  left: calc(var(--v-layout-left, 0px) + 30px);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, .14);
  border-radius: 16px;
  background: #17243a;
  color: white;
  box-shadow: 0 18px 45px rgba(15, 23, 42, .28);
}
.selected-count { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 12px; background: #3f70b7; font-size: 18px; font-weight: 900; }
.action-bar > p { display: grid; gap: 1px; min-width: 160px; margin: 0; }
.action-bar > p span, .action-level span { color: rgba(255, 255, 255, .64); font-size: 11px; }
.clear-button { border: 0; background: transparent; color: rgba(255, 255, 255, .66); cursor: pointer; }
.action-buttons { display: contents; }
.action-level { display: grid; flex: 1; gap: 3px; padding: 10px 14px; border: 1px solid rgba(255, 255, 255, .17); border-radius: 11px; background: rgba(255, 255, 255, .06); color: white; text-align: left; cursor: pointer; }
.action-level.delete { border-color: rgba(255, 142, 136, .32); background: rgba(196, 75, 71, .28); }
.modal-backdrop {
  position: fixed;
  z-index: 100;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(15, 23, 42, .55);
  backdrop-filter: blur(6px);
}
.modal {
  overflow: auto;
  width: min(760px, 90vw);
  max-height: 90vh;
  padding: 24px;
  border-radius: 18px;
  background: var(--surface);
  box-shadow: 0 24px 80px rgba(15, 23, 42, .3);
}
.modal > header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.modal > header span { color: var(--primary); font-size: 11px; font-weight: 850; letter-spacing: .08em; }
.modal h2 { margin: 3px 0 0; font-size: 24px; }
.modal > header button { width: 34px; height: 34px; border: 1px solid var(--line); border-radius: 10px; background: transparent; font-size: 22px; cursor: pointer; }
.mode-summary, .plan-state, .safety-note { display: grid; gap: 4px; margin-bottom: 12px; padding: 13px 15px; border-radius: 12px; background: var(--primary-soft); }
.mode-summary span, .plan-state span, .safety-note span { color: var(--muted); font-size: 12px; }
.mode-summary.delete { background: rgba(196, 75, 71, .08); }
.plan-resources { max-height: 170px; overflow: auto; margin-bottom: 12px; border: 1px solid var(--line); border-radius: 12px; }
.plan-resources > div { display: flex; justify-content: space-between; align-items: center; padding: 10px 13px; border-bottom: 1px solid var(--line); }
.plan-resources > div:last-child { border-bottom: 0; }
.plan-resources span { color: var(--muted); font-size: 11px; }
.plan-state.passed { color: var(--good); background: rgba(22, 131, 107, .08); }
.plan-state.blocked, .issues.blocked { color: var(--danger); background: rgba(196, 75, 71, .08); }
.issues { display: grid; gap: 6px; margin: 0 0 12px; padding: 12px 16px 12px 34px; border-radius: 12px; font-size: 13px; }
.issues.warning { color: var(--warn); background: rgba(184, 107, 17, .08); }
.risk-check { position: relative; display: flex; align-items: center; gap: 9px; margin: 12px 0; font-size: 13px; font-weight: 700; }
.risk-check > span { width: 20px; height: 20px; border: 1px solid rgba(100, 116, 139, .35); border-radius: 6px; }
.risk-check input:checked + span { border-color: var(--primary); background: var(--primary); box-shadow: inset 0 0 0 4px var(--surface); }
.safety-note { display: flex; align-items: center; background: rgba(100, 116, 139, .08); }
.safety-note p { flex: 1; }
.confirm-button, .execution-result button {
  width: 100%;
  min-height: 46px;
  border: 0;
  border-radius: 11px;
  background: var(--primary);
  color: white;
  font-weight: 800;
  cursor: pointer;
}
.confirm-button:disabled { background: rgba(100, 116, 139, .22); color: var(--muted); cursor: not-allowed; }
.final-confirmation, .execution-result { display: grid; gap: 10px; padding: 14px; border-radius: 12px; background: rgba(196, 75, 71, .08); }
.final-confirmation > div { display: flex; gap: 8px; }
.final-confirmation button { flex: 1; min-height: 42px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); cursor: pointer; }
.final-confirmation button.danger { border-color: transparent; background: var(--danger); color: white; }
.error-text { color: var(--danger); font-size: 13px; }
.execution-result { color: var(--good); background: rgba(22, 131, 107, .08); }
.compact-modal { width: min(650px, 90vw); }
.gap-row, .recovery-row { display: flex; align-items: center; gap: 8px; padding: 11px 4px; border-bottom: 1px solid var(--line); }
.gap-row p, .recovery-row p { flex: 1; }
.gap-row span, .recovery-row span { color: var(--muted); font-size: 11px; }
.gap-row b { font-size: 12px; color: var(--warn); }
.recovery-row button, .recovery-confirm button { padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px; background: transparent; cursor: pointer; }
.recovery-confirm { display: grid; gap: 8px; margin-top: 14px; padding: 14px; border-radius: 12px; background: rgba(196, 75, 71, .08); }
.recovery-confirm input { height: 40px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: inherit; }
@media (max-width: 1250px) {
  .table-head, .resource-row {
    grid-template-columns: 38px minmax(240px, 1.3fr) minmax(150px, .7fr) minmax(310px, 1.35fr) 120px minmax(200px, .9fr);
  }
}
@media (max-width: 760px) {
  .cleanup-app {
    min-width: 0;
    overflow-x: clip;
    padding: 14px 12px 190px;
  }
  .page-header {
    display: grid;
    gap: 12px;
    margin-bottom: 14px;
  }
  .eyebrow { font-size: 10px; }
  .page-header h1 { font-size: 27px; }
  .page-header > div > span {
    display: block;
    margin-top: 3px;
    font-size: 12px;
    line-height: 1.5;
  }
  .status-card {
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
  }
  .toolbar {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: 8px;
  }
  .search {
    grid-column: 1 / -1;
    height: 44px;
    box-sizing: border-box;
  }
  .safe-toggle {
    min-width: 0;
    font-size: 12px;
  }
  .soft-button { padding: 0 10px; font-size: 12px; }
  .icon-button { width: 40px; }
  .notice {
    align-items: flex-start;
    padding: 11px 12px;
  }
  .notice p strong { font-size: 14px; }
  .notice p span { font-size: 11px; }
  .notice b { display: none; }
  .filters {
    overflow-x: auto;
    width: calc(100vw - 24px);
    padding: 0 0 4px;
    scrollbar-width: none;
  }
  .filters::-webkit-scrollbar { display: none; }
  .filters button {
    flex: 0 0 auto;
    padding: 8px 11px;
    white-space: nowrap;
  }
  .resource-card {
    overflow: visible;
    border: 0;
    border-radius: 0;
    background: transparent;
  }
  .table-head { display: none; }
  .resource-row {
    grid-template-areas:
      "check title"
      ". library"
      ". seed"
      ". size"
      ". impact";
    grid-template-columns: 34px minmax(0, 1fr);
    gap: 12px 10px;
    min-height: 0;
    margin-bottom: 10px;
    padding: 15px 13px;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--surface);
    box-shadow: 0 5px 18px rgba(15, 23, 42, .04);
  }
  .resource-row:last-child { border-bottom: 1px solid var(--line); }
  .row-check {
    grid-area: check;
    align-self: start;
    width: 26px;
    height: 26px;
  }
  .resource-title {
    grid-area: title;
    padding-right: 0;
  }
  .resource-title strong { font-size: 16px; }
  .resource-title b { font-size: 12px; }
  .resource-title span { white-space: normal; }
  .stack-cell.library { grid-area: library; }
  .seed-cell { grid-area: seed; }
  .stack-cell.size { grid-area: size; }
  .impact { grid-area: impact; }
  .stack-cell, .seed-cell, .impact {
    min-width: 0;
    padding: 10px 0 0;
    border-top: 1px solid var(--line);
  }
  .stack-cell::before, .seed-cell::before, .impact::before {
    display: block;
    margin-bottom: 5px;
    color: var(--muted);
    content: attr(data-label);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .06em;
  }
  .impact {
    padding-left: 0;
    border-left: 0;
  }
  .impact.danger { border-left: 0; }
  .seed-task {
    grid-template-columns: 58px minmax(58px, auto) minmax(0, 1fr);
    gap: 6px;
    padding-left: 6px;
  }
  .seed-task i { padding: 4px 6px; font-size: 10px; }
  .seed-task strong { font-size: 12px; }
  .seed-task span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .action-bar {
    z-index: 2600;
    right: 10px;
    bottom: calc(78px + env(safe-area-inset-bottom, 0px));
    left: 10px;
    display: grid;
    grid-template-columns: 38px minmax(0, 1fr) auto;
    gap: 8px 10px;
    padding: 10px;
    border-radius: 15px;
  }
  .selected-count {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    font-size: 16px;
  }
  .action-bar > p {
    min-width: 0;
  }
  .action-bar > p strong {
    overflow: hidden;
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .action-bar > p span { font-size: 10px; }
  .clear-button {
    padding: 0 4px;
    font-size: 12px;
  }
  .action-buttons {
    display: grid;
    grid-column: 1 / -1;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 7px;
  }
  .action-level {
    display: block;
    min-width: 0;
    min-height: 42px;
    padding: 9px 5px;
    text-align: center;
  }
  .action-level strong {
    display: block;
    font-size: 13px;
    white-space: nowrap;
  }
  .action-level span { display: none; }
  .modal-backdrop {
    z-index: 3000;
    padding:
      max(12px, env(safe-area-inset-top, 0px))
      12px
      max(12px, env(safe-area-inset-bottom, 0px));
  }
  .modal, .compact-modal {
    width: calc(100vw - 24px);
    max-height: calc(100dvh - 24px);
    box-sizing: border-box;
    padding: 16px;
    border-radius: 16px;
  }
  .modal h2 { font-size: 21px; }
  .modal > header { margin-bottom: 12px; }
  .mode-summary, .plan-state, .safety-note { padding: 11px 12px; }
  .plan-resources { max-height: 120px; }
  .plan-resources > div { gap: 8px; padding: 9px 10px; }
  .plan-resources p { min-width: 0; }
  .plan-resources p span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .issues { padding: 10px 12px 10px 28px; font-size: 12px; }
  .final-confirmation > div { display: grid; grid-template-columns: 1fr 1fr; }
  .gap-row, .recovery-row {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .recovery-row p { flex-basis: 100%; }
}
</style>
