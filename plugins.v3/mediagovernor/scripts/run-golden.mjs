import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createWorkUnits } from '../src/lib/work-units.js'
import { chooseGroundedCandidate, reconcileIdentities } from '../src/lib/identity.js'
import { evaluateOfficialPreview } from '../src/lib/preview-audit.js'
import { repairAdmission } from '../src/lib/evidence-pipeline.js'
import { evaluateCurrentState, validatePreviewTarget } from '../src/lib/state-audit.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const fixturePaths = [
  resolve(root, 'tests/v3/mediagovernor/fixtures/golden/v1/cases.json'),
  resolve(root, 'tests/v3/mediagovernor/fixtures/golden/v1/live-baseline.json'),
]
const reportIndex = process.argv.indexOf('--report')
const reportPath = reportIndex >= 0 ? resolve(process.cwd(), process.argv[reportIndex + 1]) : ''
const pathKey = value => String(value || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '').toLowerCase()
const verified = identity => identity ? { evidence_verified: true, ...identity } : identity

function execute (item) {
  if (item.operation === 'work_units') {
    const rows = createWorkUnits(item.input)
    return { count: rows.length, seasons: rows.map(row => row.season_hint) }
  }
  if (item.operation === 'identity') {
    const grounded = chooseGroundedCandidate(item.input.hint, item.input.candidates)
    const resolved = reconcileIdentities(item.input.native, grounded, item.input.hint, Boolean(item.input.native_conflict))
    return { disposition: resolved.identity.abstain ? 'unconfirmed' : 'confirmed', media_id: resolved.identity.media_id || '', candidate_count: resolved.candidates.length }
  }
  if (item.operation === 'admission') {
    const result = repairAdmission(item.input.unit, verified(item.input.identity), item.input.preview)
    return { allowed: result.allowed, mode: result.mode || '' }
  }
  if (item.operation === 'audit') {
    const input = item.input
    const roots = input.library_roots || []
    const result = evaluateOfficialPreview({
      unit: input.unit,
      identity: input.identity,
      preview: input.preview,
      presentPaths: new Set((input.present || []).map(pathKey)),
      libraryRootFor: path => roots.find(root => pathKey(path).startsWith(`${pathKey(root.path)}/`)) || null,
    })
    return result ? { disposition: result.kind === 'unconfirmed' || result.kind === 'uncovered' ? result.kind : 'problem', kind: result.kind, issue_kinds: (result.issues || [result]).map(issue => issue.kind), finding_count: 1 } : { disposition: 'normal', kind: '', issue_kinds: [], finding_count: 0 }
  }
  if (item.operation === 'state_audit') {
    const input = item.input
    const result = evaluateCurrentState({ unit: input.unit, identity: verified(input.identity), preview: input.preview, presentPaths: new Set((input.present || []).map(pathKey)), libraryRoots: input.library_roots || [] })
    return result ? { disposition: result.kind === 'unconfirmed' || result.kind === 'uncovered' ? result.kind : 'problem', kind: result.kind, issue_kinds: (result.issues || [result]).map(issue => issue.kind), finding_count: 1 } : { disposition: 'normal', kind: '', issue_kinds: [], finding_count: 0 }
  }
  if (item.operation === 'preview_policy') {
    const result = validatePreviewTarget({ identity: verified(item.input.identity), preview: item.input.preview, libraryRoots: item.input.library_roots || [] })
    return { allowed: result.valid }
  }
  throw new Error(`${item.id}: 未知金标准操作 ${item.operation}`)
}

function matches (actual, expected) { return Object.entries(expected).every(([key, value]) => JSON.stringify(actual[key]) === JSON.stringify(value)) }
function html (result) {
  const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char])
  const rows = result.cases.map(item => `<tr class="${item.pass ? 'pass' : 'fail'}"><td>${escape(item.id)}</td><td><code>${escape(JSON.stringify(item.expected))}</code></td><td><code>${escape(JSON.stringify(item.actual))}</code></td><td>${item.pass ? '通过' : '失败'}</td></tr>`).join('')
  return `<!doctype html><meta charset="utf-8"><title>MediaGovernor 4.4 金标准验收回执</title><style>body{font:16px system-ui;margin:32px;color:#172033}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #d8dee9;text-align:left}.pass{background:#ecfdf3}.fail{background:#fff1f2}.summary{padding:16px;border-radius:12px;background:#eef2ff}code{white-space:pre-wrap}</style><h1>MediaGovernor 4.4 金标准验收回执</h1><p class="summary">样本 ${result.summary.total} · 通过 ${result.summary.passed} · 失败 ${result.summary.failed} · ${result.summary.status}</p><table><thead><tr><th>样本</th><th>预期</th><th>实际</th><th>结果</th></tr></thead><tbody>${rows}</tbody></table>`
}

const fixtures = await Promise.all(fixturePaths.map(async path => JSON.parse(await readFile(path, 'utf8'))))
if (fixtures.some(fixture => fixture.schema !== 'mediagovernor-golden-fixture/v2') || fixtures[0].cases.length < 14 || fixtures[1].cases.length < 16) throw new Error('金标准样本 schema 或数量不符合门禁')
const fixture = { schema: 'mediagovernor-golden-fixture/v2', cases: fixtures.flatMap(item => item.cases) }
const unsafePath = value => {
  if (Array.isArray(value)) return value.some(unsafePath)
  if (value && typeof value === 'object') return Object.values(value).some(unsafePath)
  return typeof value === 'string' && (/^[\\/]/.test(value) || /^[a-z]:\\/i.test(value)) && !value.startsWith('/fixture/')
}
if (unsafePath(fixture)) throw new Error('金标准样本包含非 fixture 路径，拒绝生成回执')
const cases = fixture.cases.map(item => { const actual = execute(item); return { id: item.id, expected: item.expected, actual, pass: matches(actual, item.expected) } })
const summary = { total: cases.length, passed: cases.filter(item => item.pass).length, failed: cases.filter(item => !item.pass).length }
summary.status = summary.failed ? '失败：禁止冻结候选' : '通过：新识别、官方预览判错和安全执行门已连通'
const result = { schema: 'mediagovernor-golden-receipt/v2', fixture_schema: fixture.schema, fixture_files: fixturePaths.map(path => path.split(/[\\/]/).pop()), summary, cases }
if (reportPath) {
  await mkdir(dirname(reportPath), { recursive: true })
  await writeFile(reportPath, html(result), 'utf8')
  await writeFile(reportPath.replace(/\.html?$/i, '.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
}
console.log(JSON.stringify(result, null, 2))
if (summary.failed) process.exitCode = 1
