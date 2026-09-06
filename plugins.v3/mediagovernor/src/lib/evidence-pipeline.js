import { cleanTitle, isSampleItem, isWithinPath, latestHistoryRows, pathKey, sourcePath, subtitlePattern, videoPattern } from './governance.js'
import { previewComplete } from './preview-audit.js'

const stable = value => String(value || '').trim()
const idFor = value => String(value || '').replace(/[^a-zA-Z0-9:_-]/g, '_').slice(0, 160)

/**
 * 把目录第一层“候选根”与历史关联为下载包。download_hash 是强证据；顶层目录只是降级边界。
 * 不以相似标题合并，因此无法确认的散件绝不会被伪装为同一下载任务。
 */
export function createEvidencePackages (roots = [], histories = []) {
  const rootRows = roots.map(root => ({ root, history: histories.filter(row => isWithinPath(sourcePath(row), root?.path)) }))
  const buckets = new Map()
  for (const item of rootRows) {
    const hashes = [...new Set(item.history.map(row => stable(row?.download_hash)).filter(Boolean))]
    const key = hashes.length === 1 ? `hash:${hashes[0]}` : `root:${pathKey(item.root?.path || item.root?.name)}`
    const bucket = buckets.get(key) || { key, roots: [], history: [], hashes: new Set(), boundary: hashes.length === 1 ? 'download_hash' : 'top_level' }
    bucket.roots.push(item.root); bucket.history.push(...item.history); hashes.forEach(hash => bucket.hashes.add(hash))
    if (hashes.length > 1) bucket.boundary = 'conflict'
    buckets.set(key, bucket)
  }
  return [...buckets.values()].map(bucket => {
    const history = latestHistoryRows(bucket.history)
    const hashes = [...bucket.hashes]
    return {
      id: idFor(bucket.key), roots: bucket.roots, root: bucket.roots[0], history,
      download_hashes: hashes, boundary: bucket.boundary,
      boundary_reason: boundaryReason(bucket.boundary, bucket.roots.length, hashes.length),
      entries: [], complete: true,
    }
  })
}

export function boundaryReason (boundary, rootCount = 0, hashCount = 0) {
  if (boundary === 'download_hash') return `已由同一下载任务编号关联${rootCount > 1 ? ` ${rootCount} 个顶层项目` : ''}`
  if (boundary === 'conflict') return `同一顶层项目关联到 ${hashCount} 个下载任务编号，不能自动合并`
  return '没有可用下载任务编号；仅按顶层目录暂时分组，不能自动重建'
}

export function appendTreeEvidence (pkg, trees = []) {
  const entries = []; let complete = pkg?.complete !== false
  for (const tree of trees) {
    entries.push(...(tree?.entries || [])); complete = complete && Boolean(tree?.complete)
  }
  return { ...pkg, entries, complete, evidence: packageEvidence({ ...pkg, entries, complete }) }
}

export function packageEvidence (pkg = {}) {
  const entries = Array.isArray(pkg.entries) ? pkg.entries.filter(item => !isSampleItem(item)) : []
  const videos = entries.filter(item => videoPattern.test(item?.name || ''))
  const directories = entries.filter(item => item?.type === 'dir')
  const subtitles = entries.filter(item => /\.(ass|ssa|srt|sub|vtt)$/i.test(item?.name || ''))
  const titles = [...new Set([
    ...(pkg.roots || []).map(item => cleanTitle(item?.name)),
    ...videos.map(item => cleanTitle(item?.name)),
    ...subtitles.map(item => cleanTitle(item?.name)),
  ].filter(Boolean))].slice(0, 80)
  return {
    complete: Boolean(pkg.complete), entry_count: entries.length, video_count: videos.length,
    subtitle_count: entries.filter(item => /\.(ass|ssa|srt|sub|vtt)$/i.test(item?.name || '')).length,
    nfo_count: entries.filter(item => /\.nfo$/i.test(item?.name || '')).length,
    title_hints: titles, top_directories: [...new Set(directories.filter(item => Number(item.depth) === 1).map(item => cleanTitle(item.name)).filter(Boolean))].slice(0, 30),
    boundary: pkg.boundary || 'top_level', boundary_reason: pkg.boundary_reason || '',
    entries: entries.map(item => ({ name: stable(item?.name).slice(0, 180), type: item?.type === 'dir' ? 'dir' : 'file', depth: Number(item?.depth || 0) })).slice(0, 500),
    ai_truncated: entries.length > 500,
  }
}

export function previewSourceFiles (pkg = {}) {
  const historySources = new Set(latestHistoryRows(pkg.history || []).map(row => pathKey(sourcePath(row))).filter(Boolean))
  return (pkg.entries || []).filter(item => {
    if (!item?.path || isSampleItem(item)) return false
    if (videoPattern.test(item?.name || '')) return true
    return subtitlePattern.test(item?.name || '') && historySources.has(pathKey(item.path))
  }).map(item => ({ type: item.type || 'file', storage: item.storage || pkg.root?.storage || 'local', path: item.path, name: item.name, size: item.size, modify_time: item.modify_time }))
}

export function repairAdmission (pkg = {}, identity = null, preview = null) {
  if (!pkg.complete) return { allowed: false, reason: '文件证据没有完整读取，不能重建' }
  if (pkg.boundary !== 'download_hash') return { allowed: false, reason: '下载包边界未由下载任务编号确认，不能自动重建' }
  if (!identity?.media_source || !identity?.media_id) return { allowed: false, reason: '作品身份没有得到 MoviePilot 数据源编号确认，不能重建' }
  if (!identity?.evidence_verified && !identity?.user_confirmed) return { allowed: false, reason: '作品身份没有经过整包证据核验或你的明确选择，不能重建' }
  const sourceCount = previewSourceFiles(pkg).length
  if (!previewComplete(preview, sourceCount)) return { allowed: false, reason: '官方逐文件预览不完整或含失败项，不能重建' }
  const histories = latestHistoryRows(pkg.history || []).filter(row => row?.status === true && row?.id)
  if (!histories.length) return { allowed: true, mode: 'create', reason: '这是没有旧成功目标的原生整理失败；将只从原始下载建立新硬链接', history_ids: [] }
  const successfulSources = new Set(histories.map(row => pathKey(sourcePath(row))))
  const pendingFileitems = previewSourceFiles(pkg).filter(item => !successfulSources.has(pathKey(item.path)))
  if (pendingFileitems.length) return { allowed: true, mode: 'mixed', reason: `将重建 ${histories.length} 个错误旧结果，并为 ${pendingFileitems.length} 个未成功源视频建立硬链接`, history_ids: histories.map(row => row.id), create_fileitems: pendingFileitems }
  return { allowed: true, mode: 'rebuild', reason: `将逐条重建 ${histories.length} 个已归因的旧整理结果`, history_ids: histories.map(row => row.id) }
}
