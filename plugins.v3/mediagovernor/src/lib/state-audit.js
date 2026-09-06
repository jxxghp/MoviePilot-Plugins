import { categoryOfIdentity, categoryOfRoot, classifyFinding, cleanTitle, destinationPath, latestHistoryRows, libraryRootForPath, pathKey, sourcePath, strictEpisodeKeys, summarizeUnit, videoPattern } from './governance.js'
import { evaluateOfficialPreview, officialPreviewItems } from './preview-audit.js'

const workFolder = value => {
  const parts = String(value || '').replace(/\\/g, '/').split('/').filter(Boolean)
  const season = parts.findIndex(part => /^(?:season|s)[ ._-]?\d{1,2}$/i.test(part))
  return cleanTitle(parts[season > 0 ? season - 1 : Math.max(0, parts.length - 2)] || '')
}

export function validatePreviewTarget ({ identity, preview, libraryRoots = [] } = {}) {
  if (!identity?.evidence_verified && !identity?.user_confirmed) return { valid: false, reason: '作品身份没有经过整包证据核验或你的明确选择，已禁止修复' }
  const expected = categoryOfIdentity(identity)
  const items = officialPreviewItems(preview)
  const roots = items.map(item => libraryRootForPath(item.target, libraryRoots)).filter(Boolean)
  const actual = [...new Set(roots.map(categoryOfRoot).filter(Boolean))]
  if (!expected || !actual.length) return { valid: false, reason: '无法确认官方预览选中的媒体库分类' }
  if (actual.some(value => value !== expected)) return { valid: false, reason: '官方预览选中的目录与作品类型不一致，已禁止修复' }
  const targets = items.map(item => pathKey(item.target))
  if (new Set(targets).size !== targets.length) return { valid: false, reason: '官方预览存在重复目标，已禁止修复' }
  const identityNames = [identity?.title, identity?.original_title].map(cleanTitle).filter(Boolean)
  for (const item of items) {
    const targetTitle = workFolder(item.target)
    if (identityNames.length && targetTitle && !identityNames.includes(targetTitle)) return { valid: false, reason: '官方预览的作品目录与已确认作品名称不一致，已禁止修复' }
    const targetYear = String(item?.year || item?.release_year || item?.target || '').match(/\b(?:19|20)\d{2}\b/)?.[0]
    if (identity?.year && targetYear && String(identity.year) !== targetYear) return { valid: false, reason: '官方预览的作品年份与已确认版本不一致，已禁止修复' }
    const sourceKeys = strictEpisodeKeys(item.source)
    const targetKeys = strictEpisodeKeys(item.target)
    if (sourceKeys.length && targetKeys.length && sourceKeys.join(',') !== targetKeys.join(',')) return { valid: false, reason: '官方预览的季集对应与原文件不一致，已禁止修复' }
  }
  return { valid: true, reason: '官方预览的目标分类已通过独立核对' }
}

/**
 * 生产和金标准共用的唯一判定入口。
 * 先用当前历史+实际目标证明问题；已完整建立且规则无冲突的作品直接正常；
 * 只有无历史或不完整项才需要官方预览作为最后证据。
 */
export function evaluateCurrentState ({ unit, identity, preview, presentPaths = new Set(), libraryRoots = [] } = {}) {
  const summary = unit?.summary || summarizeUnit(unit)
  const rules = classifyFinding({ unit, summary, history: unit?.history || [], library: libraryRoots, diagnosis: identity, presentPaths })
  const proven = rules.filter(item => !['unconfirmed', 'uncovered'].includes(item.kind))
  if (proven.length > 1) return { ...proven[0], kind: 'multiple_errors', reason: proven.map(item => item.reason).join('；'), issues: proven }
  if (proven.length) return proven[0]
  if (rules.length) return rules[0]
  if (!identity || identity.abstain || !identity.evidence_verified) return { kind: 'unconfirmed', reason: unit?.identity_reason || '作品身份还没有经过整包证据确认', strength: 'review', unit_id: unit?.id || '' }
  const sourceVideos = new Set((unit?.entries || []).filter(item => videoPattern.test(item?.name || '')).map(item => pathKey(item.path)))
  const currentVideoSources = new Set(latestHistoryRows(unit?.history || [])
    .filter(row => row?.status === true && videoPattern.test(sourcePath(row)) && presentPaths.has(pathKey(destinationPath(row))))
    .map(row => pathKey(sourcePath(row))))
  if (sourceVideos.size && [...sourceVideos].every(path => currentVideoSources.has(path))) return null
  return evaluateOfficialPreview({ unit, identity, preview, presentPaths, libraryRootFor: path => libraryRootForPath(path, libraryRoots) })
}
