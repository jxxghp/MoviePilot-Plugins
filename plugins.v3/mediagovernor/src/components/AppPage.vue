<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { cleanTitle, configuredDownloadRoots, configuredLibraryRoots, createDownloadUnits, destinationPath, findingLabel, latestHistoryRows, libraryRootSnapshot, packageHeaderFingerprint, pathKey, rootFingerprint, sourcePath, summarizeUnit, videoPattern } from '../lib/governance.js'
import { aiFallbackTargets, identityTargets } from '../lib/diagnostic-plan.js'
import { normaliseHistoryRows, unwrapMoviePilotResponse } from '../lib/moviepilot-response.js'
import { appendTreeEvidence, createEvidencePackages, packageEvidence, repairAdmission } from '../lib/evidence-pipeline.js'
import { manualPreviewRequest, manualRebuildRequests, moviePilotTypeName } from '../lib/manual-transfer.js'
import { createWorkUnits } from '../lib/work-units.js'
import { chooseGroundedCandidate, identityFromRaw, identityKey, reconcileIdentities } from '../lib/identity.js'
import { evaluateOfficialPreview, officialPreviewItems, previewComplete } from '../lib/preview-audit.js'
import { evaluateCurrentState, validatePreviewTarget } from '../lib/state-audit.js'
import { selectLibraryTarget } from '../lib/target-selection.js'
import { createRequestBudget, runBatchesUntilFailure, settledResults } from '../lib/request-budget.js'

const props = defineProps({ api: { type: Object, default: () => ({}) } })
const state = ref({ ready: false, updated_at: '', download_units: 0, library_nodes: 0, findings: 0, dirty: 0 })
const phase = ref('尚未建立地图'), notice = ref(''), running = ref(false), stopped = ref(false), aiAvailable = ref(null)
const progress = ref({ done: 0, total: 0, current: '', started_at: 0 }), findings = ref([]), units = ref([]), histories = ref([]), preview = ref(null), selected = ref(null)
const liveMapReady = ref(false)
const pageSize = 100, entryLimit = 20000
const now = ref(Date.now()), requestBudget = createRequestBudget()
let clock = null
const canUseApi = computed(() => typeof props.api?.get === 'function' && typeof props.api?.post === 'function')
const percent = computed(() => progress.value.total ? Math.min(100, Math.round(progress.value.done * 100 / progress.value.total)) : 0)
const elapsedLabel = computed(() => running.value && progress.value.started_at ? `本阶段 ${Math.max(0, Math.floor((now.value - progress.value.started_at) / 1000))} 秒` : state.value.updated_at ? '已有媒体地图' : '尚未建立媒体地图')
const cards = computed(() => findings.value.filter(item => item.kind !== 'unconfirmed' && item.kind !== 'uncovered'))
const pendingCards = computed(() => findings.value.filter(item => item.kind === 'unconfirmed'))
const uncoveredCards = computed(() => findings.value.filter(item => item.kind === 'uncovered'))
const provenCount = computed(() => cards.value.length)
const uncoveredCount = computed(() => findings.value.filter(item => item.kind === 'uncovered').length)
const safe = value => String(value || '').replace(/[\\/]/g, '').replace(/\s+/g, ' ').trim().slice(0, 160)
const displayPath = value => String(value || '').replace(/\\/g, '/') || '尚未建立'
function currentTargetFor(source) {
  const row = latestHistoryRows(selected.value?.unit?.history || []).find(item => pathKey(sourcePath(item)) === pathKey(source))
  return displayPath(destinationPath(row))
}
function previewRows(value) {
  return officialPreviewItems(value).map(item => ({ source: displayPath(item.source), current: currentTargetFor(item.source), expected: displayPath(item.target), episode: [item.season ? `S${String(item.season).padStart(2, '0')}` : '', item.episode ? `E${String(item.episode).padStart(2, '0')}` : ''].filter(Boolean).join('') || '电影' }))
}
const keyOf = item => `${item?.storage || 'local'}:${item?.path || item?.name || ''}`
function fail(error, fallback) { notice.value = error?.message || fallback }
function stage(label, total = 1, current = '') { phase.value = label; progress.value = { done: 0, total: Math.max(1, total), current, started_at: Date.now() }; now.value = Date.now() }
function advance(current = '') { progress.value.done = Math.min(progress.value.total, progress.value.done + 1); if (current) progress.value.current = current }
function resetRun(label) {
  running.value = true; stopped.value = false; liveMapReady.value = false; notice.value = ''; findings.value = []; units.value = []; histories.value = []
  stage(label, 1, '正在准备检查范围。')
  if (clock) clearInterval(clock)
  clock = setInterval(() => { now.value = Date.now() }, 1000)
}
function stop() {
  stopped.value = true
  requestBudget.cancel()
  notice.value = '已停止等待；未完成的本轮结果不会保存，也没有改变任何媒体。'
}
async function bounded(operation, timeout, label) {
  return requestBudget.run(operation, timeout, label)
}
async function get(path, timeout = 15000, label = 'MoviePilot 请求') { return unwrapMoviePilotResponse(await bounded(props.api.get(path, { feedback: 'silent' }), timeout, label)) }
async function post(path, body, timeout = 20000, label = 'MoviePilot 请求') { return unwrapMoviePilotResponse(await bounded(props.api.post(path, body, { feedback: 'silent' }), timeout, label)) }
async function postWrite(path, body) { return unwrapMoviePilotResponse(await props.api.post(path, body, { feedback: 'silent' })) }
async function status() {
  if (!canUseApi.value) return
  try {
    const snapshot = await get('plugin/MediaGovernor/map_snapshot')
    state.value = { ...state.value, ...(snapshot?.summary || snapshot || {}) }
    findings.value = Array.isArray(snapshot?.findings) ? snapshot.findings : []
    if (state.value.ready) notice.value = `已载入上次结论：${provenCount.value} 个真实问题，${pendingCards.value.length} 个等待确认作品，${uncoveredCount.value} 个未完成覆盖。可直接点开任一卡片查看上次保存的证据。`
  } catch (error) { fail(error, '无法读取已保存的媒体地图') }
}
function listOf(raw) { return Array.isArray(raw) ? raw : raw?.items || raw?.list || raw?.data || [] }
async function directories(kind) { return listOf(await get(`storage/directories?directory_type=${kind}`)) }
async function list(item) { const value = await post('storage/list', item, 12000, '读取目录'); if (!Array.isArray(value)) throw new Error('MoviePilot 没有返回目录列表'); return value }
async function history(status) { const rows = []; for (let page = 1; !stopped.value; page += 1) { const data = await get(`history/transfer?status=${status}&page=${page}&count=${pageSize}`, 15000, '读取整理历史'); const batch = listOf(data); rows.push(...batch); if (batch.length < pageSize) break } return normaliseHistoryRows(rows, status) }
async function walk(root, recursive = true) {
  const entries = []; const queue = root?.type === 'dir' ? [{ item: root, depth: 0 }] : []; let readFailures = 0
  if (root?.type !== 'dir') entries.push({ ...root, depth: 0 })
  while (queue.length && !stopped.value) {
    const current = queue.shift(); let children
    try { children = await list(current.item) } catch { readFailures += 1; continue }
    for (const child of children) {
      if (entries.length >= entryLimit) return { entries, complete: false }
      const item = { ...child, depth: current.depth + 1 }; entries.push(item)
      if (recursive && child?.type === 'dir') queue.push({ item: child, depth: current.depth + 1 })
    }
  }
  return { entries, complete: !stopped.value && !readFailures }
}
function targetPaths(unit) {
  return [...new Set([
    ...latestHistoryRows(unit?.history || []).filter(row => row?.status === true).map(destinationPath),
    ...officialPreviewItems(unit?.officialPreview).map(item => item.target),
  ].filter(Boolean))]
}
function parentOf(path, storage = 'local') { const value = String(path || ''); const cut = Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\')); return cut > 0 ? { type: 'dir', path: value.slice(0, cut), storage } : null }
async function scanTargetParents(allUnits) {
  const parentItems = new Map(); const expectedByUnit = new Map()
  for (const unit of allUnits) {
    const expected = targetPaths(unit); const parentKeys = []
    for (const row of latestHistoryRows(unit.history).filter(row => row?.status === true)) {
      const target = destinationPath(row); const parent = parentOf(target, row?.dest_fileitem?.storage || row?.dest_storage)
      if (!parent) continue
      const key = keyOf(parent); parentItems.set(key, parent); parentKeys.push(key)
    }
    for (const item of officialPreviewItems(unit.officialPreview)) {
      const parent = parentOf(item.target, unit.previewPayload?.target_storage || 'local')
      if (!parent) continue
      const key = keyOf(parent); parentItems.set(key, parent); parentKeys.push(key)
    }
    expectedByUnit.set(unit.id, { expected, parentKeys: [...new Set(parentKeys)] })
  }
  const readable = new Map(); let readFailures = 0
  const parents = [...parentItems.entries()]; stage('核对当前整理目标', parents.length, '只读取整理历史实际指向的目标目录，不扫描整座媒体库。')
  if (!parents.length) progress.value.done = progress.value.total
  let cursor = 0
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1
      if (index >= parents.length) return
      const [key, parent] = parents[index]
      try {
        const items = (await list(parent)).filter(item => item?.path)
        readable.set(key, new Map(items.map(item => [pathKey(item.path), item])))
      } catch { readable.set(key, null); readFailures += 1 }
      advance(`已完成 ${progress.value.done + 1}/${parents.length} 个目标目录；读不到的目录会明确列为未覆盖。`)
    }
  }
  await Promise.all(Array.from({ length: Math.min(8, parents.length) }, worker))
  const states = new Map()
  for (const unit of allUnits) {
    const plan = expectedByUnit.get(unit.id) || { expected: [], parentKeys: [] }; const present = new Map(); let complete = true
    for (const key of plan.parentKeys) {
      const entries = readable.get(key)
      if (entries == null) { complete = false; continue }
      for (const [path, entry] of entries) present.set(path, entry)
    }
    const target_watch = plan.parentKeys.map(key => ({ item: parentItems.get(key), fingerprint: readable.get(key) ? rootFingerprint([...readable.get(key).values()]) : '' })).filter(row => row.item)
    states.set(unit.id, { expected: plan.expected, present, complete, target_watch })
  }
  return { states, parentCount: parents.length, readFailures }
}
async function detectTargetChanges() {
  if (!state.value.ready) return 0
  const watch = listOf(await get('plugin/MediaGovernor/map_watch')); const changedUnits = new Set(); let changed = 0; let cursor = 0
  const worker = async () => {
    while (cursor < watch.length) {
      const index = cursor; cursor += 1; const row = watch[index]
      try { if (rootFingerprint(await list(row.item)) !== row.fingerprint) { changed += 1; if (row.unit_id) changedUnits.add(row.unit_id) } } catch { changed += 1; if (row.unit_id) changedUnits.add(row.unit_id) }
    }
  }
  await Promise.all(Array.from({ length: Math.min(8, watch.length) }, worker))
  if (changed) await post('plugin/MediaGovernor/map_dirty', { unit_ids: [...changedUnits], reason: `发现 ${changed} 个媒体库目标目录发生变动` })
  return changed
}
function modelEvidence(unit, summary) {
  const evidence = packageEvidence(unit)
  const directories = evidence.entries.filter(item => item.type === 'dir').slice(0, 8)
  const files = evidence.entries.filter(item => item.type === 'file')
  const indexes = [...new Set([...Array(Math.min(12, files.length)).keys(), ...Array.from({ length: Math.min(12, files.length) }, (_, index) => Math.max(0, files.length - 12 + index)), ...Array.from({ length: Math.min(12, files.length) }, (_, index) => Math.floor(index * Math.max(files.length - 1, 0) / Math.max(Math.min(12, files.length) - 1, 1)))])]
  const entries = [...directories, ...indexes.map(index => files[index]).filter(Boolean)].slice(0, 44).map(item => ({ ...item, name: safe(item.name).slice(0, 110) }))
  return { title_hints: evidence.title_hints.slice(0, 16), entries, video_count: evidence.video_count, episodes: summary.episodes, boundary: evidence.boundary, ai_truncated: evidence.entries.length > entries.length }
}
async function askAi(candidates) {
  if (!candidates.length || aiAvailable.value === false) return new Map()
  stage('智能助手复核', candidates.length, `共有 ${candidates.length} 个原生身份仍有冲突；小批处理，首次超时即停止后续批次。`)
  const diagnoses = new Map()
  const failures = []
  try {
    const pending = candidates.map(item => ({ id: item.id, evidence: modelEvidence(item, item.summary) }))
    const outcome = await runBatchesUntilFailure(pending, {
      maxItems: 4,
      maxChars: 8000,
      cost: row => JSON.stringify(row.evidence).length,
      stopped: () => stopped.value,
      run: rows => post('plugin/MediaGovernor/bundle_analyze_batch', { items: rows }, 35000, '智能助手复核'),
      success: (rows, result) => {
        for (const [id, diagnosis] of Object.entries(result.diagnoses || {})) diagnoses.set(id, diagnosis)
        for (const id of result.omitted || []) diagnoses.set(id, { abstain: true, confidence: 0, reasons: ['证据超过智能助手单批安全上限'] })
        progress.value.done += rows.length
        progress.value.current = `已完成 ${progress.value.done}/${progress.value.total} 个智能复核。`
      },
      failure: (rows, error) => {
        const reason = error?.message || '智能助手没有完成这一批'
        failures.push(reason)
        for (const row of rows) diagnoses.set(row.id, { abstain: true, confidence: 0, reasons: [reason], transient_error: true })
        progress.value.done = progress.value.total
        progress.value.current = '智能助手本轮首次失败后已熔断，不再继续空等。'
      },
    })
    if (outcome.error) notice.value = '智能助手本轮失败，已立即停止后续批次；规则和原生识别仍会继续形成结论。'
    return diagnoses
  } catch (error) { aiAvailable.value = false; notice.value = `${error?.message || '智能助手不可用'}；本轮只保留规则能证明的问题。`; return diagnoses }
}
async function identifyUnits() {
  const target = identityTargets(units.value)
  if (!target.length) return
  let cached = {}
  try {
    const response = await post('plugin/MediaGovernor/map_identities', { units: target.map(unit => ({ id: unit.id, fingerprint: unit.summary?.fingerprint || '' })) }, 10000, '读取作品身份缓存')
    cached = response?.identities || {}
  } catch { cached = {} }
  const unresolved = []
  for (const unit of target) {
    const stored = cached[unit.id]
    if (stored?.nativeIdentity) {
      unit.nativeIdentity = stored.nativeIdentity
      unit.native_identity_errors = []
    } else unresolved.push(unit)
  }
  stage('核验作品身份', unresolved.length || 1, unresolved.length ? `复用 ${target.length - unresolved.length} 个未变化身份，只核验 ${unresolved.length} 个。` : `已复用全部 ${target.length} 个未变化身份。`)
  if (!unresolved.length) { progress.value.done = progress.value.total; return }
  let cursor = 0
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1
      if (index >= unresolved.length) return
      const unit = unresolved[index]; const videos = unit.entries.filter(item => videoPattern.test(item?.name || '') && item?.path)
      const sampleIndexes = [...new Set([0, Math.floor((videos.length - 1) / 2), videos.length - 1].filter(value => value >= 0))]
      const samples = sampleIndexes.map(value => videos[value]).filter(Boolean)
      if (!samples.length && unit.attachment_only) samples.push(...unit.entries.filter(item => item?.path && /\.(ass|ssa|srt|sub|vtt)$/i.test(item?.name || '')).slice(0, 3))
      const settled = await settledResults(samples.map(async sample => identityFromRaw(await get(`media/recognize_file?path=${encodeURIComponent(sample.path)}`, 15000, '原生作品识别'))))
      const usable = settled.values.filter(candidate => !candidate.abstain)
      const identities = [...new Set(usable.map(identityKey).filter(Boolean))]
      unit.nativeIdentity = usable.length && identities.length === 1 ? usable[0] : null
      unit.native_identity_errors = settled.errors.map(error => error?.message || '原生识别失败')
      advance(`已完成 ${progress.value.done + 1}/${unresolved.length}；单个样本失败不会再丢掉其他成功结果。`)
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, unresolved.length) }, worker))
}
async function groundAiDiagnoses(aiDiagnoses) {
  const target = units.value.filter(unit => aiDiagnoses.has(unit.id)); if (!target.length) return
  stage('核对智能候选', target.length, 'AI 只提供标题线索；可执行身份仍需由 MoviePilot 数据源唯一确认。')
  let cursor = 0
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1; if (index >= target.length) return
      const unit = target[index]; const hint = aiDiagnoses.get(unit.id)
      let grounded = { selected: null, candidates: [] }
      if (hint && !hint.abstain && hint.title) {
        try {
          const query = [hint.title, hint.year].filter(Boolean).join(' ')
          const rows = listOf(await get(`media/search?title=${encodeURIComponent(query)}&type=media&page=1&count=8`, 15000, '搜索作品候选'))
          const detailed = await Promise.all(rows.slice(0, 8).map(async row => {
            const identity = identityFromRaw(row)
            if (!identityKey(identity) || identity.media_type === 'unknown') return row
            try {
              return await get(`media/${encodeURIComponent(identity.media_id)}?media_source=${encodeURIComponent(identity.media_source)}&type_name=${encodeURIComponent(moviePilotTypeName(identity.media_type))}`, 15000, '读取作品详情')
            } catch { return row }
          }))
          grounded = chooseGroundedCandidate(hint, detailed)
        } catch { grounded = { selected: null, candidates: [] } }
      }
      const resolved = reconcileIdentities(unit.nativeIdentity, grounded, hint, unit.native_conflict)
      unit.diagnosis = resolved.identity; unit.candidates = resolved.candidates; unit.identity_reason = resolved.reason; unit.aiDiagnosis = hint
      if (hint?.transient_error && unit.diagnosis?.abstain) unit.identity_reason = `智能助手本批失败：${hint.reasons?.[0] || '未知原因'}；下次检查会重试`
      advance(`已完成 ${progress.value.done + 1}/${target.length} 个候选落地。`)
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, target.length) }, worker))
}
async function generateOfficialPreviews() {
  // 首次检查只为“没有任何历史可交叉验证”的作品生成官方预览。
  // 旧失败、错误分类和错作品先由当前历史+实际目标直接判断，点开卡片时再实时生成修复预览。
  const target = units.value.filter(unit => identityKey(unit.diagnosis) && !unit.history.length); if (!target.length) return
  stage('生成必要的官方预览', target.length, '仅为没有任何历史可交叉验证的作品生成预览。')
  let cursor = 0
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1; if (index >= target.length) return
      const unit = target[index]
      try {
        const base = manualPreviewRequest(unit, unit.diagnosis)
        const selection = selectLibraryTarget(unit.diagnosis, unit.libraryRoots || [])
        if (!selection.selected) throw new Error(selection.reason)
        const targetPath = selection.selected
        unit.previewPayload = { ...base, ...targetPath, preview: true, reorganize: false }
        unit.officialPreview = await post('transfer/manual', unit.previewPayload, 30000, '生成官方逐文件预览')
        if (!previewComplete(unit.officialPreview, base.fileitems.length)) throw new Error('MoviePilot 逐文件预览不完整')
      } catch (error) { unit.preview_error = error?.message || '官方预览生成失败'; unit.officialPreview = null }
      advance(`已完成 ${progress.value.done + 1}/${target.length}；只有完整预览才会形成可修复结论。`)
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, target.length) }, worker))
}
async function scanDownloadUnits(toScan, total) {
  stage('读取发生变化的下载单元', toScan.length || 1, toScan.length ? `本轮只深度读取 ${toScan.length}/${total} 个下载包。` : `共 ${total} 个下载包，当前没有源文件变化。`)
  if (!toScan.length) { progress.value.done = progress.value.total; units.value = []; return }
  const results = new Array(toScan.length); let cursor = 0
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1
      if (index >= toScan.length) return
      const unit = toScan[index]
      try {
        const trees = await Promise.all((unit.roots || [unit.root]).map(root => walk(root)))
        Object.assign(unit, appendTreeEvidence(unit, trees)); unit.summary = summarizeUnit(unit); unit.headerFingerprint = packageHeaderFingerprint(unit.roots || [unit.root], unit.entries.filter(item => Number(item.depth) === 1))
      } catch { unit.entries = []; unit.complete = false; unit.summary = summarizeUnit(unit) }
      results[index] = unit; advance(`已完成 ${progress.value.done + 1}/${toScan.length}；读不到的目录会保留为尚未覆盖。`)
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, toScan.length) }, worker))
  units.value = results.filter(Boolean)
}
async function scanPackageHeaders(packages) {
  if (!packages.length) return
  stage('轻量检查源文件变化', packages.length, '只读取每个下载包的第一层目录指纹，不做作品识别。')
  let cursor = 0
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1
      if (index >= packages.length) return
      const pkg = packages[index]
      try {
        const rows = await Promise.all((pkg.roots || [pkg.root]).map(root => list(root)))
        pkg.headerFingerprint = packageHeaderFingerprint(pkg.roots || [pkg.root], rows.flat())
      } catch { pkg.headerFingerprint = '' }
      advance(`已轻量核对 ${progress.value.done + 1}/${packages.length} 个下载包。`)
    }
  }
  await Promise.all(Array.from({ length: Math.min(8, packages.length) }, worker))
}
async function buildMap(full = false) {
  if (!canUseApi.value) { notice.value = 'MoviePilot 页面 API 尚未注入，无法建立地图。'; return }
  resetRun(full ? '建立完整媒体地图' : '复核当前变动')
  try {
    stage('读取检查范围', 4, '同时读取下载目录、媒体库目录及成功/失败整理历史。')
    const tasks = [directories('download'), directories('library'), history(false), history(true)].map(task => Promise.resolve(task).finally(() => advance()))
    const [downloadConfigurations, libraryConfigurations, failed, successful] = await Promise.all(tasks)
    histories.value = [...failed, ...successful]
    const scope = configuredDownloadRoots(downloadConfigurations)
    if (!scope.roots.length) throw new Error('没有可用下载目录：拒绝扫描空路径或容器根目录')
    stage('读取下载区顶层项目', scope.roots.length, '只读取 MoviePilot 已配置的下载目录，不扫描容器根目录。'); const discovered = []
    for (const root of scope.roots) { if (stopped.value) break; discovered.push(...createDownloadUnits(root, await list(root))); advance(`已读取 ${progress.value.done + 1}/${scope.roots.length} 个下载根目录。`) }
    const top = [...new Map(discovered.map(unit => [keyOf(unit.root), unit])).values()]
    const packages = createEvidencePackages(top.map(unit => unit.root), histories.value)
    const libraryRoots = configuredLibraryRoots(libraryConfigurations)
    const initial = !state.value.ready || full
    if (!initial) await detectTargetChanges()
    if (!initial) await scanPackageHeaders(packages)
    const plan = initial ? { unchanged: [] } : await post('plugin/MediaGovernor/map_plan', { units: packages.map(unit => ({ id: unit.id, fingerprint: unit.headerFingerprint || rootFingerprint(unit.roots) })) })
    const toScan = initial ? packages : packages.filter(unit => !new Set(plan.unchanged || []).has(unit.id))
    progress.value.current = initial ? `发现 ${top.length} 个顶层项目，归为 ${packages.length} 个下载包；历史只用来关联，不当成问题数。` : `发现 ${packages.length} 个下载包，其中 ${toScan.length} 个发生变动，需要深度复核。`
    await scanDownloadUnits(toScan, packages.length)
    units.value = units.value.flatMap(createWorkUnits)
    for (const unit of units.value) { unit.summary = summarizeUnit(unit); unit.libraryRoots = libraryRoots }
    const libraryNodes = libraryRootSnapshot(libraryRoots)
    await identifyUnits()
    // AI 只兜底 MoviePilot 原生无法确认的单元；AI 结果仍必须回到 MoviePilot 数据源落地。
    const candidates = aiFallbackTargets(units.value)
    const diagnoses = await askAi(candidates)
    await groundAiDiagnoses(diagnoses)
    for (const unit of units.value.filter(item => !item.diagnosis)) {
      const resolved = reconcileIdentities(unit.nativeIdentity, { selected: null, candidates: [] }, null, unit.native_conflict)
      unit.diagnosis = resolved.identity; unit.candidates = resolved.candidates; unit.identity_reason = resolved.reason
    }
    await generateOfficialPreviews()
    const targetAudit = await scanTargetParents(units.value)
    const refined = []
    if (scope.rejected.length) refined.push({ unit_id: 'scope:invalid', title: `${scope.rejected.length} 个下载目录配置`, kind: 'uncovered', reason: '下载目录为空或指向容器根目录，已拒绝扫描；请在 MoviePilot 目录设置中修正', strength: 'review' })
    for (const unit of units.value) {
      if (!unit.complete) { refined.push({ unit_id: unit.id, title: cleanTitle(unit.root?.name) || '未命名下载单元', kind: 'uncovered', reason: '当前下载单元未完整读取，暂不能下结论', strength: 'review' }); continue }
      if (!unit.summary.video_count && !unit.attachment_only) continue
      const targetState = targetAudit.states.get(unit.id) || { expected: targetPaths(unit), present: new Map(), complete: false }
      unit.target_watch = targetState.target_watch || []
      if (!targetState.complete) { refined.push({ unit_id: unit.id, title: unit.work_label, kind: 'uncovered', reason: '当前目标目录没有完整读取，暂时不能判断', strength: 'review' }); continue }
      const finding = evaluateCurrentState({ unit, identity: unit.diagnosis, preview: unit.officialPreview, presentPaths: new Set(targetState.present.keys()), libraryRoots })
      if (finding) refined.push({ ...finding, title: unit.work_label, boundary: unit.boundary, candidate_count: unit.candidates?.length || 0 })
    }
    const linkedHistoryIds = new Set(units.value.flatMap(unit => unit.history.map(row => String(row?.id || ''))))
    const unlinkedUnits = units.value.filter(unit => unit.summary.video_count && !unit.history.length)
    findings.value = dedupe(refined); phase.value = stopped.value ? '已停止（未保存不完整地图）' : '保存当前媒体地图'
    if (!stopped.value) {
      const linkedUnits = units.value.filter(unit => unit.history.length).length
      const unmatchedFailed = failed.filter(item => !linkedHistoryIds.has(String(item?.id || ''))).length
      stage('保存当前媒体地图', 2, '只保存本轮证据和结论，不修改任何媒体文件。')
      const historyUnit = new Map(units.value.flatMap(unit => unit.history.map(row => [String(row.id), unit.id])))
      const commit = await post('plugin/MediaGovernor/map_commit', { baseline: initial, partial: !initial, scope_verified: true, download_units: units.value.map(unit => ({ id: unit.id, package_id: unit.package_id, root: unit.root, label: unit.work_label || cleanTitle(unit.root?.name) || '未命名下载单元', fingerprint: unit.summary.fingerprint, header_fingerprint: unit.headerFingerprint || rootFingerprint(unit.roots), video_count: unit.summary.video_count, subtitle_count: unit.summary.subtitle_count, nfo_count: unit.summary.nfo_count, episodes: unit.summary.episodes, names: unit.summary.names, history: unit.history.map(row => row.id), boundary: unit.boundary, coverage: unit.complete ? 'complete' : 'uncovered', detail: unit })), library_nodes: libraryNodes, findings: findings.value, coverage: { configured_download_roots: scope.roots.length, rejected_download_roots: scope.rejected.length, download_units: packages.length, scanned_units: units.value.length, library_roots: libraryNodes.length, target_parent_dirs: targetAudit.parentCount, target_parent_read_failures: targetAudit.readFailures, failed_history: failed.length, successful_history: successful.length, linked_units: linkedUnits, unlinked_units: units.value.length - linkedUnits, unmatched_failed_history: unmatchedFailed, uncovered_units: uncoveredCount.value }, history_summary: histories.value.map(row => ({ id: row.id, status: row.status, mode: row.mode, media_source: row.media_source, media_id: row.media_id, target: destinationPath(row), download_hash: row.download_hash, unit_id: historyUnit.get(String(row.id)) || '' })) }, 20000, '保存媒体地图')
      advance('媒体地图已保存，正在读取公开摘要。')
      state.value = { ...state.value, ...commit }
      const saved = await get('plugin/MediaGovernor/map_snapshot')
      advance('公开摘要已核对。')
      findings.value = Array.isArray(saved?.findings) ? saved.findings : findings.value
      liveMapReady.value = true
      phase.value = '地图已更新'; notice.value = `已读到失败历史 ${failed.length} 条、成功历史 ${successful.length} 条；本轮复核 ${units.value.length} 个下载单元。核对了 ${targetAudit.parentCount} 个当前整理目标目录（${targetAudit.readFailures} 个暂不可读）。已证明 ${provenCount.value} 个问题，另有 ${findings.value.filter(item => item.kind === 'unconfirmed').length} 个无法确认、${uncoveredCount.value} 个尚未覆盖。`
    }
  } catch (error) { fail(error, '建立地图失败；没有改变任何媒体。'); phase.value = '建立地图未完成' }
  finally { running.value = false; if (clock) { clearInterval(clock); clock = null } }
}
function dedupe(rows) { const map = new Map(); for (const row of rows) { const key = `${row.unit_id}:${row.kind}:${row.reason}`; if (!map.has(key)) map.set(key, row) } return [...map.values()] }
function titleFor(card) { const unit = units.value.find(item => item.id === card.unit_id); return card?.title || unit?.work_label || cleanTitle(unit?.root?.name) || '未命名下载单元' }
async function recognize(card) {
  let unit = units.value.find(item => item.id === card.unit_id)
  if (!unit?.root?.path) {
    try {
      const result = await post('plugin/MediaGovernor/map_unit', { unit_id: card.unit_id })
      unit = result?.unit
    } catch (error) { fail(error, '无法读取这个作品的已保存证据'); return }
  }
  selected.value = { card, unit, candidate: identityKey(unit.diagnosis) ? unit.diagnosis : null, candidates: unit.candidates || [], error: '', preview_payload: unit.previewPayload || null, admission: null }
  preview.value = unit.officialPreview || null
  if (preview.value && selected.value.candidate) selected.value.admission = repairAdmission(unit, selected.value.candidate, preview.value)
  if (!selected.value.candidate && !selected.value.candidates.length) selected.value.error = '当前证据没有得到可用候选。请先检查智能助手和媒体数据源配置。'
}
function selectCandidate(candidate) { selected.value.candidate = { ...candidate, user_confirmed: true }; selected.value.error = ''; selected.value.preview_payload = null; selected.value.admission = null; preview.value = null }
function previewPayload() {
  return manualPreviewRequest(selected.value?.unit, selected.value?.candidate)
}
async function makePreview() {
  try {
    const base = previewPayload()
    if (!base.fileitems.length || !base.media_source || !base.media_id) throw new Error('缺少经 MoviePilot 确认的作品身份或视频文件')
    const selection = selectLibraryTarget(selected.value.candidate, selected.value.unit.libraryRoots || [])
    if (!selection.selected) throw new Error(selection.reason)
    const target = selection.selected
    const payload = { ...base, ...target, preview: true, reorganize: false }
    preview.value = await post('transfer/manual', payload)
    selected.value.preview_payload = payload
    selected.value.admission = repairAdmission(selected.value.unit, selected.value.candidate, preview.value)
    const targetPolicy = validatePreviewTarget({ identity: selected.value.candidate, preview: preview.value, libraryRoots: selected.value.unit.libraryRoots || [] })
    if (!targetPolicy.valid) selected.value.admission = { allowed: false, reason: targetPolicy.reason }
    selected.value.unit.diagnosis = selected.value.candidate; selected.value.unit.previewPayload = payload; selected.value.unit.officialPreview = preview.value
    const targetAudit = await scanTargetParents([selected.value.unit])
    const targetState = targetAudit.states.get(selected.value.unit.id) || { present: new Map(), complete: false }
    const updated = targetState.complete ? evaluateOfficialPreview({ unit: selected.value.unit, identity: selected.value.candidate, preview: preview.value, presentPaths: new Set(targetState.present.keys()) }) : null
    selected.value.card = updated ? { ...selected.value.card, ...updated } : { ...selected.value.card, kind: 'normal', reason: '按当前官方预览核对，这个作品暂时没有已证明的整理差异' }
    const index = findings.value.findIndex(item => item.unit_id === selected.value.card.unit_id)
    if (updated) {
      const next = { ...selected.value.card, ...updated, title: titleFor(selected.value.card) }
      if (index >= 0) findings.value.splice(index, 1, next)
      else findings.value.push(next)
      selected.value.card = next
    } else if (index >= 0) findings.value.splice(index, 1)
  } catch (error) { selected.value.error = error?.message || '官方预览没有生成'; fail(error, '官方预览没有生成；没有删除或重建任何硬链接。') }
}
async function repair() {
  const admission = selected.value?.admission
  if (!admission?.allowed) { notice.value = admission?.reason || '当前预览不满足安全重建条件。'; return }
  if (!window.confirm(`确认按本次官方预览重建吗？${admission.reason}。原始下载不会被删除。`)) return
  try {
    if (admission.mode === 'create') await postWrite('transfer/manual', { ...selected.value.preview_payload, preview: false, reorganize: false })
    else {
      for (const payload of manualRebuildRequests(admission.history_ids, selected.value.candidate, selected.value.preview_payload)) await postWrite('transfer/manual', payload)
      if (admission.mode === 'mixed' && admission.create_fileitems?.length) await postWrite('transfer/manual', { ...selected.value.preview_payload, fileitems: admission.create_fileitems, preview: false, reorganize: false })
    }
    notice.value = 'MoviePilot 已接收逐项重建。现在会重新读取当前状态；只有实际结果等于预览，问题才会关闭。'
    preview.value = null; selected.value = null; await buildMap(true)
  } catch (error) { fail(error, '官方没有完成全部重建；插件没有直接删除原始下载。请重新读取当前状态。') }
}
async function probeAi() { try { const result = await post('plugin/MediaGovernor/ai_probe', {}); aiAvailable.value = Boolean(result.available); notice.value = aiAvailable.value ? '智能助手可用：只会复核规则无法确认的异常单元。' : '智能助手未返回可用状态。' } catch (error) { aiAvailable.value = false; fail(error, '智能助手不可用，仍可建立地图和检查规则问题。') } }
onMounted(status)
onUnmounted(() => { if (clock) clearInterval(clock); requestBudget.cancel('页面已关闭') })
</script>

<template>
  <main class="governor-page">
    <section class="hero"><div><p class="eyebrow">MediaGovernor 4.5.0</p><h1>找到问题，再安全修好</h1><p>当前文件和硬链接决定问题；历史只负责关联，修复目标按作品类型选择唯一媒体库。</p></div><div class="actions"><button class="secondary" :disabled="running" @click="probeAi">检查智能助手</button><button v-if="state.ready" class="secondary" :disabled="running" @click="buildMap(true)">完整重建地图</button><button class="primary" :disabled="running" @click="buildMap(state.ready ? false : true)">{{ state.ready ? '检查变动' : '开始首次检查' }}</button></div></section>
    <section class="summary"><span><b>{{ provenCount }}</b>真实问题</span><span><b>{{ pendingCards.length }}</b>等待确认作品</span><span><b>{{ uncoveredCards.length }}</b>未完成覆盖</span><span><b>{{ units.length || state.download_units }}</b>作品单元</span></section>
    <section v-if="running || progress.total" class="progress"><div><b>{{ phase }}</b><button v-if="running" class="link" @click="stop">停止</button></div><p>{{ progress.current }}</p><i><em :style="{ width: `${percent}%` }"></em></i><small>{{ progress.done }}/{{ progress.total }} · {{ elapsedLabel }}</small></section>
    <p v-if="notice" class="notice">{{ notice }}</p>
    <section class="panel"><header><div><h2>已确认的真实问题</h2><p>这些项目已由当前硬链接、作品身份和分类/季集规则证明；点开后再生成当次修复预览。</p></div></header>
      <p v-if="!cards.length" class="empty">{{ running ? '正在核对，还没有形成结论。' : state.ready ? '当前没有已经证明的真实问题。' : '首次使用请先开始检查。' }}</p>
      <article v-for="card in cards" :key="`${card.unit_id}-${card.kind}`" class="card"><div><span class="kind">{{ findingLabel(card.kind) }}</span><h3>{{ titleFor(card) }}</h3><p>{{ card.reason }}</p><small>点开可查看当前结果、官方应有结果和安全修复条件。</small></div><button class="primary" :disabled="running" @click="recognize(card)">查看对比与修复</button></article>
    </section>
    <section v-if="pendingCards.length" class="panel secondary-panel"><header><div><h2>等待确认作品</h2><p>这些不是已判定的问题。可以查看整包候选，选对作品后生成官方预览。</p></div></header>
      <article v-for="card in pendingCards" :key="`${card.unit_id}-${card.kind}`" class="card"><div><span class="kind">等待确认</span><h3>{{ titleFor(card) }}</h3><p>{{ card.reason }}</p></div><button class="secondary" :disabled="running" @click="recognize(card)">选择作品并预览</button></article>
    </section>
    <section v-if="uncoveredCards.length" class="panel secondary-panel"><header><div><h2>没有检查完整</h2><p>这些项目不会被当成正常或问题；原因解决后需要重新检查。</p></div></header>
      <article v-for="card in uncoveredCards" :key="`${card.unit_id}-${card.kind}`" class="card"><div><span class="kind">未完成</span><h3>{{ titleFor(card) }}</h3><p>{{ card.reason }}</p></div></article>
    </section>
    <div v-if="selected" class="backdrop"><section class="modal"><button class="close" @click="selected = null; preview = null">×</button><p class="eyebrow">作品证据与官方预览</p><h2>{{ titleFor(selected.card) }}</h2><p>{{ selected.card.reason }}</p><div class="candidate"><b>文件证据：{{ selected.unit.complete ? '完整读取' : '未完整读取' }}</b><span>{{ selected.unit.summary?.video_count || 0 }} 个视频文件 · {{ selected.unit.boundary_reason }}</span></div><div v-if="selected.candidates.length" class="candidate-list"><button v-for="candidate in selected.candidates" :key="identityKey(candidate)" :class="['candidate-choice', { active: identityKey(candidate) === identityKey(selected.candidate) }]" @click="selectCandidate(candidate)"><b>{{ candidate.title || candidate.original_title }}</b><span>{{ candidate.year || '年份未知' }} · {{ candidate.media_type }} · {{ candidate.media_source }} / {{ candidate.media_id }}</span></button></div><div v-else-if="selected.candidate" class="candidate"><b>{{ selected.candidate.title || selected.candidate.original_title }}</b><span>{{ selected.candidate.year }} · {{ selected.candidate.media_type }} · {{ selected.candidate.media_source }} / {{ selected.candidate.media_id }}</span></div><p v-if="selected.error" class="warning">{{ selected.error }}</p><button class="primary" :disabled="!selected.candidate || Boolean(selected.error)" @click="makePreview">{{ preview ? '重新生成官方逐文件预览' : '生成官方逐文件预览' }}</button><div v-if="preview" class="preview"><h3>整理前后对比</h3><p>每一行都是同一个原文件：中间是现在的硬链接，右侧是 MoviePilot 官方预览的新位置。</p><div class="compare"><div class="compare-head"><b>原文件</b><b>当前硬链接</b><b>修复后</b></div><div v-for="row in previewRows(preview)" :key="`${row.source}-${row.expected}`" class="compare-row"><span>{{ row.source }}</span><span>{{ row.current }}</span><span>{{ row.expected }}<small>{{ row.episode }}</small></span></div></div><p class="warning">{{ selected.admission?.reason }}</p><button class="danger" :disabled="!selected.admission?.allowed" @click="repair">确认清理旧硬链接并重建</button></div></section></div>
  </main>
</template>

<style scoped>
.governor-page{max-width:1180px;margin:auto;padding:34px;color:rgb(var(--v-theme-on-surface,245,245,245))}.hero,header,.card,.actions,.summary{display:flex;gap:18px;align-items:center;justify-content:space-between}.hero{padding:30px;border-radius:20px;background:linear-gradient(125deg,rgba(var(--v-theme-primary,112,77,255),.25),rgba(20,20,35,.35))}.hero h1{font-size:32px;margin:5px 0}.hero p,header p,.card p,small{color:rgba(255,255,255,.7);line-height:1.6}.eyebrow,.kind{color:rgb(var(--v-theme-primary,160,120,255));font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.actions{flex-wrap:wrap}.primary,.secondary,.danger,.link,.candidate-choice{border:0;border-radius:10px;padding:10px 15px;font-weight:700;cursor:pointer}.primary{background:rgb(var(--v-theme-primary,139,92,246));color:#fff}.secondary{background:rgba(255,255,255,.1);color:inherit}.danger{background:#dc2626;color:#fff;margin-top:14px}.primary:disabled,.secondary:disabled,.danger:disabled{opacity:.45;cursor:not-allowed}.link{background:transparent;color:#fbbf24;padding:0}.summary{margin:18px 0;justify-content:flex-start;flex-wrap:wrap}.summary span{min-width:145px;padding:13px;border:1px solid rgba(255,255,255,.12);border-radius:12px;color:rgba(255,255,255,.7)}.summary b{display:block;color:#fff;font-size:22px}.progress,.panel,.notice,.modal{border:1px solid rgba(255,255,255,.14);border-radius:16px;background:rgba(var(--v-theme-surface,23,23,34),.94);padding:20px}.panel{margin-bottom:18px}.secondary-panel{background:rgba(var(--v-theme-surface,23,23,34),.72)}.progress div{display:flex;justify-content:space-between}.progress i{display:block;height:8px;background:rgba(255,255,255,.12);border-radius:99px;overflow:hidden;margin:12px 0}.progress em{display:block;height:100%;background:rgb(var(--v-theme-primary,139,92,246))}.notice{margin-bottom:18px;color:#fef3c7}.panel header{align-items:flex-start}.empty{padding:30px 0;color:rgba(255,255,255,.65)}.card{padding:20px 0;border-top:1px solid rgba(255,255,255,.12)}.card h3{margin:7px 0}.card:first-of-type{border-top:0}.backdrop{position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:10;display:grid;place-items:center;padding:20px}.modal{position:relative;width:min(860px,100%);max-height:calc(100vh - 40px);overflow:auto}.close{position:absolute;right:15px;top:8px;border:0;background:transparent;color:inherit;font-size:28px}.candidate,.preview{margin-top:18px;padding:15px;border-radius:12px;background:rgba(255,255,255,.06)}.candidate span,.candidate-choice span{display:block;color:rgba(255,255,255,.68);margin-top:5px}.candidate-list{display:grid;gap:8px;margin:18px 0}.candidate-choice{text-align:left;background:rgba(255,255,255,.06);color:inherit;border:1px solid transparent}.candidate-choice.active{border-color:rgb(var(--v-theme-primary,139,92,246));background:rgba(var(--v-theme-primary,139,92,246),.18)}.warning{color:#fbbf24}.preview pre{max-height:330px;overflow:auto;white-space:pre-wrap;font-size:12px}@media(max-width:720px){.governor-page{padding:18px}.hero,header,.card{align-items:stretch;flex-direction:column}.hero h1{font-size:25px}}
.compare{margin-top:14px;overflow:auto}.compare-head,.compare-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;min-width:720px;padding:10px;border-bottom:1px solid rgba(255,255,255,.1)}.compare-row span{overflow-wrap:anywhere}.compare-row small{display:block;margin-top:5px}
</style>
