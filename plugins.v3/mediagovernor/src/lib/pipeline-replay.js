import { configuredDownloadRoots, configuredLibraryRoots, createDownloadUnits, pathKey, summarizeUnit } from './governance.js'
import { nativeEvidenceConflict } from './diagnostic-plan.js'
import { appendTreeEvidence, createEvidencePackages } from './evidence-pipeline.js'
import { chooseGroundedCandidate, identityFromRaw, reconcileIdentities } from './identity.js'
import { evaluateCurrentState } from './state-audit.js'
import { selectLibraryTarget } from './target-selection.js'
import { createWorkUnits } from './work-units.js'

/**
 * 从“目录配置 -> 顶层列表 -> 完整树 -> 历史 -> 原生/AI身份 -> 当前目标”重放生产判定。
 * fixture 不得直接注入最终 finding，避免金标准绕过真实流水线。
 */
export function replayPipeline (input = {}) {
  const scope = configuredDownloadRoots(input.download_configurations || [])
  const histories = input.histories || []
  const tops = scope.roots.flatMap(root => createDownloadUnits(root, input.root_listings?.[pathKey(root.path)] || []))
  const packages = createEvidencePackages(tops.map(item => item.root), histories).map(pkg => appendTreeEvidence(pkg, (pkg.roots || [pkg.root]).map(root => ({ complete: true, entries: input.trees?.[pathKey(root.path)] || (root.type === 'file' ? [root] : []) }))))
  const libraryRoots = configuredLibraryRoots(input.library_configurations || [])
  const units = packages.flatMap(createWorkUnits)
  const present = new Set((input.present || []).map(pathKey))
  const findings = []
  for (const unit of units) {
    unit.summary = summarizeUnit(unit); unit.libraryRoots = libraryRoots
    const rawNative = input.native_by_label?.[unit.work_label] || input.native_by_root?.[pathKey(unit.root?.path)] || null
    unit.nativeIdentity = rawNative ? identityFromRaw(rawNative) : null
    unit.native_conflict = nativeEvidenceConflict(unit, unit.nativeIdentity)
    const hint = input.ai_hints?.[unit.work_label] || null
    const grounded = hint ? chooseGroundedCandidate(hint, input.ai_candidates?.[unit.work_label] || []) : { selected: null, candidates: [] }
    const resolved = reconcileIdentities(unit.nativeIdentity, grounded, hint, unit.native_conflict)
    unit.diagnosis = resolved.identity; unit.identity_reason = resolved.reason
    const selection = selectLibraryTarget(unit.diagnosis, libraryRoots)
    unit.selected_target = selection.selected
    const finding = evaluateCurrentState({ unit, identity: unit.diagnosis, preview: input.previews?.[unit.work_label], presentPaths: present, libraryRoots })
    if (finding) findings.push(finding)
  }
  return { scope, tops, packages, units, findings }
}
