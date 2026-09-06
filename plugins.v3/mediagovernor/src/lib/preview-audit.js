import { cleanTitle, destinationPath, latestHistoryRows, pathKey, strictEpisodeHints, subtitlePattern, videoPattern } from './governance.js'

export function officialPreviewItems (preview = {}) {
  const rows = Array.isArray(preview?.items) ? preview.items : Array.isArray(preview?.data?.items) ? preview.data.items : []
  return rows.filter(item => item && item.success !== false && item.target)
}

export function previewComplete (preview = {}, sourceCount = 0) {
  const summary = preview?.summary || preview?.data?.summary || {}
  return Number(summary.total) === Number(sourceCount) && Number(summary.success) === Number(sourceCount) && Number(summary.failed || 0) === 0 && officialPreviewItems(preview).length === Number(sourceCount)
}

const seasonOf = value => Number(String(value || '').replace(/\\/g, '/').match(/\/(?:s|season)[ ._-]?(\d{1,2})(?=\/|$)/i)?.[1] || 0)
const parentTitle = value => cleanTitle(String(value || '').replace(/\\/g, '/').split('/').slice(-2, -1)[0] || '')

/** 一个作品单元只输出一个结论；details 在详情页解释所有逐文件差异。 */
export function evaluateOfficialPreview ({ unit, identity, preview, presentPaths = new Set(), libraryRootFor = () => null } = {}) {
  const finding = (kind, reason, details = []) => ({ kind, reason, details, strength: 'strong', unit_id: unit?.id || '', history_id: latestHistoryRows(unit?.history || [])[0]?.id || null })
  if (!unit?.complete) return finding('uncovered', '文件没有完整读取，暂时不能判断')
  if (!identity || identity.abstain || !identity.media_source || !identity.media_id) return finding('unconfirmed', unit?.identity_reason || '作品身份还没有确认')
  const requestedCount = Array.isArray(unit?.previewPayload?.fileitems) ? unit.previewPayload.fileitems.length : 0
  const sourceCount = requestedCount || (unit.entries || []).filter(item => item?.path && (videoPattern.test(item?.name || item?.path) || (unit?.attachment_only && subtitlePattern.test(item?.name || item?.path)))).length
  if (!previewComplete(preview, sourceCount)) return finding('unconfirmed', unit?.preview_error || 'MoviePilot 没有生成完整逐文件预览')
  const expected = officialPreviewItems(preview).map(item => pathKey(item.target))
  const successful = latestHistoryRows(unit.history || []).filter(row => row?.status === true && destinationPath(row))
  const current = successful.map(row => pathKey(destinationPath(row))).filter(path => presentPaths.has(path))
  const expectedPresent = expected.filter(path => presentPaths.has(path))
  if (!current.length) {
    if (expectedPresent.length === expected.length) return null
    return finding('native_failure', '原文件仍在，但官方应有目标没有完整建立', expected.filter(path => !presentPaths.has(path)))
  }
  const missing = expected.filter(path => !presentPaths.has(path))
  const unexpected = current.filter(path => !expected.includes(path))
  if (!missing.length && !unexpected.length) return null
  const details = [`缺少 ${missing.length} 个应有目标`, `存在 ${unexpected.length} 个错误目标`]
  const expectedRoots = new Set(expected.map(libraryRootFor).filter(Boolean).map(root => root.media_type || root.media_category || root.name))
  const currentRoots = new Set(current.map(libraryRootFor).filter(Boolean).map(root => root.media_type || root.media_category || root.name))
  if (expectedRoots.size && currentRoots.size && ![...expectedRoots].some(value => currentRoots.has(value))) return finding('category_error', '当前硬链接放错了媒体库分类', details)
  const expectedSeasons = new Set(expected.map(seasonOf).filter(Boolean)); const currentSeasons = new Set(current.map(seasonOf).filter(Boolean))
  if (expectedSeasons.size && currentSeasons.size && ![...expectedSeasons].some(value => currentSeasons.has(value))) return finding('hierarchy_error', '当前硬链接放错了季目录', details)
  const expectedEpisodes = expected.flatMap(strictEpisodeHints); const currentEpisodes = current.flatMap(strictEpisodeHints)
  if (expectedEpisodes.length && currentEpisodes.length && expectedEpisodes.join(',') !== currentEpisodes.join(',')) return finding('episode_error', '当前文件与应有集号对应不上', details)
  const expectedTitles = new Set(expected.map(parentTitle).filter(Boolean)); const currentTitles = new Set(current.map(parentTitle).filter(Boolean))
  if (expectedTitles.size && currentTitles.size && ![...expectedTitles].some(value => currentTitles.has(value))) return finding('identity_error', '当前硬链接归到了另一部作品', details)
  return finding('hierarchy_error', '当前硬链接位置与 MoviePilot 官方预览不一致', details)
}
