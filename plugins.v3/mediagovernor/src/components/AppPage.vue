<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { unwrapMoviePilotResponse } from '../lib/moviepilot-response.js'

const props = defineProps({ api: { type: Object, default: () => ({}) } })
const snapshot = ref({ status: { job: { status: 'idle', phase: 'IDLE', total: 0, done: 0, current: '尚未检查', error: '' }, counts: {}, objects: 0 }, problems: [], confirmations: [], errors: [] })
const busy = ref(false)
const message = ref('')
const selected = ref(null)
const repairPlan = ref(null)
const confirmingRepair = ref(false)
let timer = null

const job = computed(() => snapshot.value.status?.job || {})
const running = computed(() => job.value.status === 'running')
const stopping = computed(() => running.value && Boolean(job.value.cancel_requested))
const progress = computed(() => job.value.total ? Math.round((job.value.done || 0) * 100 / job.value.total) : 0)
const hasResults = computed(() => snapshot.value.problems.length + snapshot.value.confirmations.length + snapshot.value.errors.length > 0)
const statusTitle = computed(() => ({
  running: stopping.value ? '正在停止' : '正在后台检查',
  completed: '检查完成',
  failed: '检查失败',
  cancelled: '检查已停止',
  interrupted: '上次检查已中断'
}[job.value.status] || '等待检查'))

function failure (error, fallback) {
  message.value = error?.message || fallback
}

async function get (path) {
  return unwrapMoviePilotResponse(await props.api.get(path, { feedback: 'silent' }))
}

async function post (path, body) {
  return unwrapMoviePilotResponse(await props.api.post(path, body, { feedback: 'silent' }))
}

async function refresh () {
  try {
    snapshot.value = await get('plugin/MediaGovernor/findings')
  } catch (error) {
    failure(error, '没有读到媒体治理状态')
  }
}

async function start (mode) {
  busy.value = true
  message.value = mode === 'full' ? '正在重新建立完整基线。' : '正在检查当前变动。'
  try {
    await post('plugin/MediaGovernor/audit/start', { mode })
    await refresh()
  } catch (error) {
    failure(error, '没有启动检查')
  } finally {
    busy.value = false
  }
}

async function cancel () {
  if (stopping.value) return
  message.value = '正在停止当前只读检查，已经完成的结果会保留。'
  try {
    await post('plugin/MediaGovernor/audit/start', { mode: 'cancel' })
    await refresh()
  } catch (error) {
    failure(error, '没有提交停止请求')
  }
}

async function openItem (item) {
  busy.value = true
  message.value = ''
  repairPlan.value = null
  confirmingRepair.value = false
  try {
    selected.value = await get(`plugin/MediaGovernor/objects/${encodeURIComponent(item.object_id)}`)
    selected.value.finding = item
  } catch (error) {
    failure(error, '没有读到这部作品的证据')
  } finally {
    busy.value = false
  }
}

function candidateKey (candidate) {
  const source = ['tmdb', 'the_movie_db'].includes(String(candidate?.media_source || '').toLowerCase()) ? 'themoviedb' : String(candidate?.media_source || '').toLowerCase()
  return `${source}:${candidate?.media_id || ''}:${candidate?.media_type || 'unknown'}`
}

async function confirmIdentity (candidate) {
  if (!selected.value) return
  busy.value = true
  try {
    await post('plugin/MediaGovernor/identity/confirm', { object_id: selected.value.id, candidate_key: candidateKey(candidate) })
    message.value = '身份已保存，只重新核对这一部作品。'
    selected.value = null
    await refresh()
  } catch (error) {
    failure(error, '没有保存作品身份')
  } finally {
    busy.value = false
  }
}

async function previewRepair () {
  if (!selected.value) return
  busy.value = true
  try {
    repairPlan.value = await post(`plugin/MediaGovernor/repair/${encodeURIComponent(selected.value.id)}`, { action: 'preview' })
    confirmingRepair.value = false
  } catch (error) {
    failure(error, '没有生成当前修复预览')
  } finally {
    busy.value = false
  }
}

async function executeRepair () {
  if (!selected.value || !repairPlan.value?.token) return
  busy.value = true
  try {
    const result = await post(`plugin/MediaGovernor/repair/${encodeURIComponent(selected.value.id)}`, { action: 'execute', token: repairPlan.value.token })
    message.value = result.message || 'MoviePilot 已完成重建，正在复核。'
    selected.value = null
    repairPlan.value = null
    await refresh()
  } catch (error) {
    failure(error, 'MoviePilot 没有完成重建')
  } finally {
    busy.value = false
  }
}

function closeDetail () {
  selected.value = null
  repairPlan.value = null
  confirmingRepair.value = false
}

onMounted(async () => {
  await refresh()
  timer = window.setInterval(() => { if (running.value) refresh() }, 1500)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <main class="governor-shell">
    <section class="hero">
      <div>
        <p class="eyebrow">MediaGovernor 5.0.1</p>
        <h1>检查现在，找到真实问题</h1>
        <p class="lead">逐作品比较原文件、当前硬链接和 MoviePilot 应有结果。已经完成的结果会立即保存，关掉页面也不会中断。</p>
      </div>
      <div class="actions">
        <button v-if="running" class="secondary" :disabled="stopping" @click="cancel">{{ stopping ? '正在停止…' : '停止检查' }}</button>
        <button class="primary" :disabled="busy || running" @click="start('incremental')">检查现在</button>
        <details class="advanced">
          <summary>高级操作</summary>
          <button class="secondary" :disabled="busy || running" @click="start('full')">重建全部基线</button>
          <p>只在首次使用、目录配置改变或诊断时运行。</p>
        </details>
      </div>
    </section>

    <section class="status-card" aria-live="polite">
      <div class="status-line">
        <div>
          <b>{{ statusTitle }}</b>
          <span>{{ job.current }}</span>
        </div>
        <strong>{{ job.done || 0 }}/{{ job.total || 0 }}</strong>
      </div>
      <div v-if="running" class="bar"><i :style="{ width: `${progress}%` }" /></div>
      <p v-if="job.error" class="warning">{{ job.error }}</p>
      <p v-if="message" class="notice">{{ message }}</p>
    </section>

    <section class="summary-grid">
      <article><strong>{{ snapshot.problems.length }}</strong><span>已经证明的问题</span></article>
      <article><strong>{{ snapshot.confirmations.length }}</strong><span>需要你确认</span></article>
      <article><strong>{{ snapshot.errors.length }}</strong><span>本轮没读完</span></article>
      <article><strong>{{ snapshot.status.objects || 0 }}</strong><span>当前作品</span></article>
    </section>

    <section class="panel">
      <header><div><p class="eyebrow">发现的问题</p><h2>整理失败和假成功</h2></div><span>{{ snapshot.problems.length }} 项</span></header>
      <button v-for="item in snapshot.problems" :key="item.id" class="result-row" @click="openItem(item)">
        <span><b>{{ item.title }}</b><small>{{ item.reason }}</small></span><i>查看证据与修复 →</i>
      </button>
      <p v-if="!snapshot.problems.length" class="empty">{{ running ? '已完成的作品还没有形成问题。' : hasResults ? '当前没有已经证明的问题。' : '点击“检查现在”开始。' }}</p>
    </section>

    <section class="panel review-panel">
      <header><div><p class="eyebrow">需要你确认</p><h2>身份歧义或手工改动</h2></div><span>{{ snapshot.confirmations.length }} 项</span></header>
      <button v-for="item in snapshot.confirmations" :key="item.id" class="result-row" @click="openItem(item)">
        <span><b>{{ item.title }}</b><small>{{ item.reason }}</small></span><i>选择正确答案 →</i>
      </button>
      <p v-if="!snapshot.confirmations.length" class="empty">没有等待你决定的项目。</p>
    </section>

    <section class="panel error-panel">
      <header><div><p class="eyebrow">本轮没读完</p><h2>明确的读取或预览错误</h2></div><span>{{ snapshot.errors.length }} 项</span></header>
      <button v-for="item in snapshot.errors" :key="item.id" class="result-row" @click="openItem(item)">
        <span><b>{{ item.title }}</b><small>{{ item.reason }}</small></span><i>查看失败阶段 →</i>
      </button>
      <p v-if="!snapshot.errors.length" class="empty">没有读取错误。</p>
    </section>

    <div v-if="selected" class="backdrop" @click.self="closeDetail">
      <section class="modal" role="dialog" aria-modal="true" :aria-label="selected.title">
        <button class="close" aria-label="关闭" @click="closeDetail">×</button>
        <p class="eyebrow">作品证据</p>
        <h2>{{ selected.title }}</h2>
        <p class="lead small">{{ selected.finding?.reason }}</p>

        <div class="facts">
          <div><span>文件读取</span><b>{{ selected.source?.object?.complete ? '完整' : '未完整' }}</b></div>
          <div><span>作品身份</span><b>{{ selected.identity_state === 'confirmed' ? '已确认' : '等待确认' }}</b></div>
          <div><span>确认依据</span><b>{{ selected.provenance || '暂无' }}</b></div>
        </div>

        <section v-if="selected.identity_state !== 'confirmed'" class="choice-area">
          <h3>请选择正确作品</h3>
          <p v-if="!selected.candidates.length" class="warning">MoviePilot 和智能助手都没有给出可用候选。本项会保留，不会被算成正常。</p>
          <button v-for="candidate in selected.candidates" :key="candidateKey(candidate)" class="candidate" :disabled="busy" @click="confirmIdentity(candidate)">
            <b>{{ candidate.title || candidate.original_title || '未命名候选' }}</b>
            <span>{{ candidate.year || '年份未知' }} · {{ candidate.media_type }} · {{ candidate.media_source }}/{{ candidate.media_id }}</span>
          </button>
        </section>

        <section v-else class="choice-area">
          <h3>{{ selected.identity.title || selected.identity.original_title }}</h3>
          <p>{{ selected.identity.year || '年份未知' }} · {{ selected.identity.media_type }} · {{ selected.identity.media_source }}/{{ selected.identity.media_id }}</p>
          <button class="primary" :disabled="busy" @click="previewRepair">重新读取并生成修复预览</button>
        </section>

        <section v-if="repairPlan" class="preview">
          <h3>整理前后对比</h3>
          <div class="compare-head"><b>原文件</b><b>当前硬链接</b><b>修复后</b></div>
          <div v-for="(row, index) in repairPlan.entries" :key="index" class="compare-row">
            <span>{{ row.source?.path }}</span><span>{{ row.current || '没有建立' }}</span><span>{{ row.expected }}</span>
          </div>
          <p class="warning">只会清理这里列出的旧硬链接，再由 MoviePilot 官方整理链重建；不会删除原始下载。</p>
          <button v-if="!confirmingRepair" class="danger" @click="confirmingRepair = true">继续到最终确认</button>
          <div v-else class="final-confirm"><b>确认执行这一个作品？</b><button class="secondary" @click="confirmingRepair = false">返回</button><button class="danger" :disabled="busy" @click="executeRepair">确认修复</button></div>
        </section>
      </section>
    </div>
  </main>
</template>

<style scoped>
.governor-shell{--ink:rgb(var(--v-theme-on-surface,242,245,250));--muted:rgba(var(--v-theme-on-surface,242,245,250),.68);--line:rgba(var(--v-theme-on-surface,242,245,250),.13);--paper:rgba(var(--v-theme-surface-variant,var(--v-theme-surface,31,27,46)),.54);--surface:rgba(var(--v-theme-surface,31,27,46),.88);--primary:rgb(var(--v-theme-primary,179,157,219));--primary-soft:rgba(var(--v-theme-primary,179,157,219),.15);--amber:rgb(var(--v-theme-warning,255,183,77));--red:rgb(var(--v-theme-error,239,83,80));color:var(--ink);display:grid;gap:16px;padding:20px;max-width:1180px;margin:auto}.governor-shell h1,.governor-shell h2,.governor-shell h3,.governor-shell b,.governor-shell strong{color:var(--ink)}.hero,.status-card,.panel{background:var(--surface);border:1px solid var(--line);border-radius:18px;box-shadow:0 14px 40px rgba(0,0,0,.18);backdrop-filter:blur(16px)}.hero{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;padding:26px;background:linear-gradient(135deg,var(--primary-soft),rgba(var(--v-theme-surface,31,27,46),.94) 56%,rgba(var(--v-theme-background,18,15,28),.9))}.eyebrow{margin:0 0 7px;color:var(--primary);font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.hero h1,.modal h2{margin:0;font-size:30px;line-height:1.15}.lead{max-width:720px;color:var(--muted);line-height:1.65}.lead.small{font-size:14px}.actions{display:flex;align-items:flex-start;gap:9px;flex-wrap:wrap;justify-content:flex-end}button{font:inherit}.primary,.secondary,.danger{border-radius:11px;padding:10px 15px;font-weight:700;cursor:pointer}.primary{border:0;color:rgb(var(--v-theme-on-primary,255,255,255));background:var(--primary)}.secondary{border:1px solid var(--line);background:var(--paper);color:var(--ink)}.danger{border:0;color:white;background:var(--red)}button:disabled{opacity:.48;cursor:not-allowed}.advanced{position:relative}.advanced summary{cursor:pointer;color:var(--muted);padding:10px}.advanced[open]{min-width:210px}.advanced p{font-size:12px;color:var(--muted);max-width:220px}.status-card{padding:17px 20px}.status-line{display:flex;justify-content:space-between;align-items:center}.status-line div{display:grid;gap:3px}.status-line span{color:var(--muted);font-size:13px}.bar{height:6px;background:rgba(var(--v-theme-on-surface,242,245,250),.09);border-radius:99px;margin-top:12px;overflow:hidden}.bar i{display:block;height:100%;background:var(--primary);transition:width .25s}.notice,.warning{font-size:13px;line-height:1.55}.notice{color:var(--primary)}.warning{color:var(--amber)}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.summary-grid article{display:grid;gap:4px;padding:17px 19px;background:var(--paper);border:1px solid var(--line);border-radius:14px}.summary-grid strong{font-size:27px}.summary-grid span{font-size:12px;color:var(--muted)}.panel{overflow:hidden}.panel header{display:flex;justify-content:space-between;align-items:center;padding:20px 22px 14px}.panel h2{margin:0;font-size:19px}.panel header>span{color:var(--muted);font-size:13px}.result-row{width:100%;display:flex;justify-content:space-between;gap:18px;text-align:left;padding:15px 22px;border:0;border-top:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer}.result-row:hover{background:var(--primary-soft)}.result-row span{display:grid;gap:5px}.result-row small{color:var(--muted);line-height:1.45}.result-row i{font-style:normal;color:var(--primary);white-space:nowrap}.review-panel{border-color:rgba(var(--v-theme-warning,255,183,77),.3)}.error-panel{border-color:rgba(var(--v-theme-error,239,83,80),.3)}.empty{padding:4px 22px 22px;color:var(--muted)}.backdrop{position:fixed;inset:0;background:rgba(5,4,9,.74);display:grid;place-items:center;padding:20px;z-index:50}.modal{position:relative;width:min(920px,96vw);max-height:90vh;overflow:auto;background:rgb(var(--v-theme-surface,31,27,46));color:var(--ink);border:1px solid var(--line);border-radius:20px;padding:28px;box-shadow:0 24px 80px #0008}.close{position:absolute;right:18px;top:14px;border:0;background:transparent;color:var(--ink);font-size:28px;cursor:pointer}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:20px 0}.facts div{display:grid;gap:5px;padding:12px;background:var(--paper);border-radius:10px}.facts span{font-size:12px;color:var(--muted)}.choice-area{border-top:1px solid var(--line);padding-top:18px}.candidate{width:100%;display:grid;gap:5px;text-align:left;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:11px;padding:12px;margin:8px 0;cursor:pointer}.candidate:hover{border-color:var(--primary)}.candidate span{font-size:12px;color:var(--muted)}.preview{margin-top:22px;padding-top:18px;border-top:1px solid var(--line)}.compare-head,.compare-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:9px;padding:10px;border-bottom:1px solid var(--line)}.compare-head{background:var(--paper);font-size:12px}.compare-row span{overflow-wrap:anywhere;font-size:12px}.final-confirm{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:12px}@media(max-width:760px){.governor-shell{padding:12px}.hero{display:grid}.actions{justify-content:flex-start}.summary-grid{grid-template-columns:1fr 1fr}.facts{grid-template-columns:1fr}.compare-head{display:none}.compare-row{grid-template-columns:1fr}.result-row{display:grid}.modal{padding:22px 16px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
