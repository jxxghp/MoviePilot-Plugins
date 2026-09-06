import { cleanTitle } from './governance.js'

/** 所有完整读取到的视频作品单元都要识别；历史不得决定诊断范围。 */
export function identityTargets (units = []) {
  return units.filter(unit => unit?.complete && (unit?.summary?.video_count || (unit?.attachment_only && unit?.summary?.subtitle_count)))
}

/** AI 只兜底 MoviePilot 无法给出唯一身份的单元，避免全库重复消耗。 */
export function aiFallbackTargets (units = []) {
  return identityTargets(units).filter(unit => {
    unit.native_conflict = nativeEvidenceConflict(unit, unit?.nativeIdentity)
    return !unit?.nativeIdentity || unit?.attachment_only || unit.native_conflict
  })
}

export function nativeEvidenceConflict(unit = {}, identity = null) {
  if (!identity?.media_id || !identity?.media_source) return true
  const names = [unit?.work_label, ...(unit?.summary?.names || [])].map(cleanTitle).filter(Boolean)
  const years = [...new Set(names.flatMap(name => String(name).match(/\b(?:19|20)\d{2}\b/g) || []))]
  if (years.length > 1) return true
  if (years.length === 1 && String(identity.year || '') !== years[0]) return true
  if ((unit?.summary?.episode_keys || []).length && identity.media_type !== 'tv') return true
  const evidence = names.map(name => name.toLowerCase().replace(/\b(?:19|20)\d{2}\b/g, ' ').replace(/\bs\d{1,2}(?:e\d{1,3})?\b/gi, ' ').replace(/\b(?:ep|e)\d{1,3}\b/gi, ' ').replace(/\s+/g, ' ').trim()).filter(name => name.length >= 4 && !/^\d+$/.test(name))
  const candidates = [identity?.title, identity?.original_title].map(cleanTitle).map(name => name.toLowerCase()).filter(name => name.length >= 4)
  if (evidence.length && candidates.length && !evidence.some(name => candidates.some(candidate => name.includes(candidate) || candidate.includes(name)))) return true
  // 发布名常含压制组、语言、分辨率与别名，标题字面不一致不能单独推翻
  // MoviePilot 已在多个样本上给出的同一数据源身份；年份与媒体类型硬冲突仍须 AI 复核。
  return false
}
