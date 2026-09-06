const text = value => String(value || '').trim()
const unique = values => [...new Set(values.filter(Boolean))]

export const videoPattern = /\.(mkv|mp4|avi|m2ts|ts|mov|webm)$/i
export const subtitlePattern = /\.(ass|ssa|srt|sub|vtt)$/i

export function isSampleItem(item = {}) {
  const path = pathKey(item.path || item.name)
  return /(?:^|\/)samples?(?:\/|$)/i.test(path) || /(?:^|[ ._-])sample(?:[ ._-]|\.)/i.test(String(item.name || ''))
}

export function cleanTitle(value) {
  return text(value).replace(/\.[a-z0-9]{2,5}$/i, '').replace(/[\[【(（].*?[\]】)）]/g, ' ')
    .replace(/\b(2160p|1080p|720p|web[ .-]?(dl|rip)|bluray|bdrip|remux|x26[45]|h\.?26[45]|hevc|aac|dts|atmos|hdr10?\+?|dv|10bit|proper|repack|complete|中字|简繁|国语|粤语)\b/gi, ' ')
    .replace(/[._-]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120)
}

export function strictEpisodeHints(value) {
  const name = text(value); const found = []
  for (const match of name.matchAll(/\bS\d{1,2}E(\d{1,3})\b/ig)) found.push(Number(match[1]))
  for (const match of name.matchAll(/\b(?:EP|E)(\d{1,3})\b/ig)) found.push(Number(match[1]))
  for (const match of name.matchAll(/[\[【](\d{1,3})[\]】]/g)) found.push(Number(match[1]))
  return unique(found.filter(value => value > 0 && value < 1000)).sort((a, b) => a - b)
}

export function strictEpisodeKeys(value) {
  const name = text(value); const found = []
  for (const match of name.matchAll(/\bS(\d{1,2})E(\d{1,3})\b/ig)) found.push(`S${Number(match[1])}E${Number(match[2])}`)
  if (found.length) return unique(found)
  const season = Number(name.match(/(?:^|[\\/ ._-])(?:season|s)[ ._-]?(\d{1,2})(?=[\\/ ._-]|$)/i)?.[1] || 0)
  return strictEpisodeHints(name).map(episode => season ? `S${season}E${episode}` : `E${episode}`)
}

export function episodeKeysCompatible(leftValue, rightValue) {
  const left = strictEpisodeKeys(leftValue); const right = strictEpisodeKeys(rightValue)
  if (!left.length || !right.length) return true
  const parts = key => ({ season: Number(key.match(/^S(\d+)E/)?.[1] || 0), episode: Number(key.match(/E(\d+)$/)?.[1] || 0) })
  const a = left.map(parts); const b = right.map(parts)
  return a.length === b.length && a.every((item, index) => item.episode === b[index].episode && (!item.season || !b[index].season || item.season === b[index].season))
}

export function fileFingerprint(item = {}) {
  return [text(item.name), text(item.type), Number(item.size) || 0, text(item.modify_time || item.mtime)].join('|')
}

/** 固定长度的非加密摘要；用于变化检测，避免长目录清单在 API/持久化层被截断。 */
export function compactFingerprint(value) {
  const source = String(value || '')
  let left = 0x811c9dc5; let right = 0x9e3779b9
  for (let index = 0; index < source.length; index += 1) {
    const code = source.charCodeAt(index)
    left = Math.imul(left ^ code, 0x01000193) >>> 0
    right = Math.imul(right ^ code, 0x85ebca6b) >>> 0
  }
  return `${source.length.toString(16).padStart(8, '0')}${left.toString(16).padStart(8, '0')}${right.toString(16).padStart(8, '0')}`
}

export function unitFingerprint(unit = {}) {
  return compactFingerprint([text(unit.root?.path || unit.root), ...(unit.entries || []).map(fileFingerprint).sort()].join('\n'))
}

export function rootFingerprint(items = []) { return compactFingerprint([...items].map(fileFingerprint).sort().join('\n')) }

/** 下载包第一层指纹；单文件下载必须把文件本身算进去。 */
export function packageHeaderFingerprint(roots = [], children = []) {
  return rootFingerprint([...(roots || []).filter(item => item?.type !== 'dir'), ...(children || [])])
}

export function pathKey(value) {
  return String(value || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '').toLowerCase()
}

export function isRootPath(value) {
  const path = pathKey(value)
  return !path || path === '/' || /^[a-z]:$/i.test(path)
}

export function isWithinPath(value, root) {
  const path = pathKey(value); const base = pathKey(root)
  return Boolean(path && base && (path === base || path.startsWith(`${base}/`)))
}

/** 把“目录配置”显式转换为 FileItem；配置对象本身绝不能送进 storage/list。 */
export function configuredDownloadRoots(configurations = []) {
  const roots = []; const rejected = []; const seen = new Set()
  for (const configuration of configurations) {
    const path = String(configuration?.download_path || '').trim()
    const storage = String(configuration?.storage || 'local').trim() || 'local'
    if (isRootPath(path)) { rejected.push({ name: text(configuration?.name) || '未命名目录配置', reason: '下载目录为空或指向容器根目录' }); continue }
    const key = `${storage}:${pathKey(path)}`
    if (seen.has(key)) continue
    seen.add(key)
    roots.push({ type: 'dir', storage, path, name: text(configuration?.name) || path, configured: true, media_type: text(configuration?.media_type), media_category: text(configuration?.media_category) })
  }
  return { roots, rejected }
}

export function configuredLibraryRoots(configurations = []) {
  const roots = []; const seen = new Set()
  for (const configuration of configurations) {
    const path = String(configuration?.library_path || '').trim()
    const storage = String(configuration?.library_storage || 'local').trim() || 'local'
    if (isRootPath(path)) continue
    const key = `${storage}:${pathKey(path)}`
    if (seen.has(key)) continue
    seen.add(key)
    roots.push({
      type: 'dir', storage, path, name: text(configuration?.name) || path,
      media_type: text(configuration?.media_type), media_category: text(configuration?.media_category),
      transfer_type: text(configuration?.transfer_type) || 'link', scraping: Boolean(configuration?.scraping),
      library_type_folder: Boolean(configuration?.library_type_folder), library_category_folder: Boolean(configuration?.library_category_folder),
    })
  }
  return roots
}

export function libraryRootForPath(path, roots = []) {
  return [...roots].filter(root => isWithinPath(path, root?.path)).sort((left, right) => pathKey(right?.path).length - pathKey(left?.path).length)[0] || null
}

export function sourcePath(row = {}) {
  const item = row.src_fileitem || row.source_fileitem || row.fileitem || {}
  return String(item.path || row.src || row.source || '')
}

export function destinationPath(row = {}) {
  const item = row.dest_fileitem || {}
  return String(item.path || row.dest || '')
}

/** 仅允许“历史源文件位于下载单元内”的单向归属；父目录历史不能被猜测分配给多个包。 */
export function historyRowsForUnit(unit, rows = []) {
  const root = unit?.root?.path || ''
  return rows.filter(row => isWithinPath(sourcePath(row), root)).sort(latestFirst)
}

export function latestFirst(left, right) {
  const leftDate = Date.parse(left?.date || '') || 0; const rightDate = Date.parse(right?.date || '') || 0
  if (leftDate !== rightDate) return rightDate - leftDate
  const sequence = value => Number(String(value || '').match(/(\d+)$/)?.[1] || 0)
  return sequence(right?.id) - sequence(left?.id)
}

export function latestHistory(rows = []) { return [...rows].sort(latestFirst)[0] || null }

/** 同一源文件的旧整理记录只作审计依据，当前目标只认该源文件最近一次结果。 */
export function latestHistoryRows(rows = []) {
  const bySource = new Map()
  for (const row of [...rows].sort(latestFirst)) {
    const source = pathKey(sourcePath(row)) || `history:${row?.id || bySource.size}`
    if (!bySource.has(source)) bySource.set(source, row)
  }
  return [...bySource.values()].sort(latestFirst)
}

export function createDownloadUnits(root, children = []) {
  // 顶层目录或顶层视频各是一个下载单元；不再用相似标题拼成虚构“包”。
  return children.filter(item => item?.type === 'dir' || videoPattern.test(item?.name || '')).map(item => ({
    id: `${root?.storage || 'local'}:${item?.path || item?.name}`, root: item, entries: [], status: 'pending',
  }))
}

/** 地图只持久化媒体库根摘要；具体存在性由整理历史指向的目标目录逐一核验。 */
export function libraryRootSnapshot(roots = []) {
  return roots.filter(root => root && typeof root === 'object').map(root => ({
    id: `${root.storage || 'local'}:${root.path || root.name || ''}`,
    root,
    fingerprint: fileFingerprint(root),
    video_count: 0,
    episodes: [],
    category: cleanTitle(root.name) || '媒体库根',
  }))
}

export function summarizeUnit(unit = {}) {
  const episodeFiles = new Map(); let video_count = 0; let subtitle_count = 0; let nfo_count = 0
  for (const item of unit.entries || []) {
    if (isSampleItem(item)) continue
    const name = text(item.name)
    if (videoPattern.test(name)) { video_count += 1; for (const episode of strictEpisodeKeys(name)) episodeFiles.set(episode, [...(episodeFiles.get(episode) || []), name]) }
    else if (subtitlePattern.test(name)) subtitle_count += 1
    else if (/\.nfo$/i.test(name)) nfo_count += 1
  }
  const episode_keys = [...episodeFiles.keys()].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
  const episodes = unique(episode_keys.map(value => Number(value.match(/E(\d+)$/)?.[1] || 0)).filter(Boolean)).sort((a, b) => a - b)
  const duplicateEpisodes = [...episodeFiles].filter(([, files]) => new Set(files).size > 1).map(([episode]) => episode)
  return { video_count, subtitle_count, nfo_count, episodes, episode_keys, duplicateEpisodes, fingerprint: unitFingerprint(unit), names: unique([cleanTitle(unit.root?.name), ...(unit.entries || []).map(item => cleanTitle(item.name))].filter(Boolean)).slice(0, 50) }
}

export function historyIndex(rows = []) {
  const bySource = new Map()
  for (const row of rows) {
    const source = row?.src_fileitem || row?.source_fileitem || row?.fileitem || {}
    const key = text(source.path || row?.src || row?.source)
    if (!key) continue
    const group = bySource.get(key) || []; group.push(row); bySource.set(key, group)
  }
  return bySource
}

const mediaKind = value => /tv|series|电视剧|剧集|动漫|动画|综艺|纪录片/i.test(text(value)) ? 'tv' : /movie|film|电影/i.test(text(value)) ? 'movie' : ''

export const categoryOfIdentity = identity => {
  const value = [identity?.category, ...(identity?.genres || [])].join(' ')
  const genreIds = new Set((identity?.genre_ids || []).map(Number))
  if (genreIds.has(16)) return 'animation'
  if (genreIds.has(99) || genreIds.has(10764) || genreIds.has(10767)) return 'other'
  if (/animation|动画|动漫|anime/i.test(value)) return 'animation'
  if (/variety|综艺|reality|talk[ -]?show/i.test(value)) return 'other'
  if (/documentary|纪录/i.test(value)) return 'other'
  return identity?.media_type === 'movie' ? 'movie' : identity?.media_type === 'tv' ? 'tv' : ''
}

export const categoryOfRoot = root => {
  const value = [root?.name, root?.media_category, root?.media_type].join(' ')
  if (/动漫|动画|anime/i.test(value)) return 'animation'
  if (/其他|综艺|纪录|other/i.test(value)) return 'other'
  if (/movie|电影/i.test(value)) return 'movie'
  if (/tv|电视|剧集/i.test(value)) return 'tv'
  return ''
}

export function destinationWorkFolder(value) {
  const parts = String(value || '').replace(/\\/g, '/').split('/').filter(Boolean)
  const season = parts.findIndex(part => /^(?:season|s)[ ._-]?\d{1,2}$/i.test(part))
  return cleanTitle(parts[season > 0 ? season - 1 : Math.max(0, parts.length - 2)] || '')
}

export function titlesCompatible(leftValues = [], rightValues = []) {
  const left = leftValues.map(cleanTitle).filter(Boolean); const right = rightValues.map(cleanTitle).filter(Boolean)
  return left.some(a => right.some(b => a === b || (Math.min(a.length, b.length) >= 4 && (a.includes(b) || b.includes(a)))))
}

export function classifyFinding({ unit, summary, history = [], library = [], diagnosis = null, presentPaths = new Set() }) {
  const finding = (kind, reason, strength = 'strong') => ({ kind, reason, strength, unit_id: unit.id, history_id: latestHistory(history)?.id || null })
  if (!summary.video_count && !(unit?.attachment_only && summary.subtitle_count)) return []
  const currentHistory = latestHistoryRows(history)
  const successful = currentHistory.filter(row => row?.status === true)
  const failed = currentHistory.filter(row => row?.status === false)
  const presentSuccessful = successful.filter(row => presentPaths.has(pathKey(destinationPath(row))))
  const targetMissing = successful.length && successful.every(row => !row?.dest_fileitem?.path && !row?.dest)
  if (failed.length && !successful.length) return [finding('native_failure', '原生整理失败：当前源文件仍在且没有成功建立硬链接')]
  if (targetMissing) return [finding('unconfirmed', '历史记录没有保存可核验的目标位置，不能判断当前是否仍有问题', 'review')]
  if (!diagnosis || diagnosis.abstain || diagnosis.confidence < .5) return failed.length ? [finding('native_failure', `部分整理失败：当前仍有 ${failed.length} 个源文件没有建立成功硬链接`)] : []
  const currentRecords = presentSuccessful
  const record = currentRecords[0] || {}; const recordKind = mediaKind(record.type || record.media_type || record.category)
  const expectedKind = diagnosis.media_type
  const missingSuffix = failed.length ? `；另有 ${failed.length} 个源文件当前仍未整理成功` : ''
  const expectedCategory = categoryOfIdentity(diagnosis)
  const currentRoots = currentRecords.map(row => libraryRootForPath(destinationPath(row), library)).filter(Boolean)
  const currentCategories = [...new Set(currentRoots.map(categoryOfRoot).filter(Boolean))]
  const results = []
  if (expectedCategory && currentCategories.length && currentCategories.some(value => value !== expectedCategory)) results.push(finding('category_error', `目录分类错误：当前位置与已确认作品类型不同${missingSuffix}`))
  else if (recordKind && expectedKind !== 'unknown' && recordKind !== expectedKind) results.push(finding('category_error', `媒体类型对不上：当前整理结果与已确认作品类型不同${missingSuffix}`))
  for (const current of currentRecords) {
    const recordMedia = current.media_info || current.mediainfo || current.media || {}
    const recordSource = normaliseMediaSource(current.media_source || recordMedia.media_source || recordMedia.source)
    const recordId = text(current.media_id || current.tmdb_id || current.douban_id || recordMedia.media_id || recordMedia.tmdb_id || recordMedia.douban_id || recordMedia.id)
    const currentFolder = destinationWorkFolder(destinationPath(current))
    const proposed = [diagnosis.title, diagnosis.original_title]
    const currentFolderMatches = currentFolder && titlesCompatible([currentFolder], proposed)
    const recordYear = text(current.year || recordMedia.year || recordMedia.release_year)
    const targetYear = text(destinationPath(current).match(/\b(?:19|20)\d{2}\b/)?.[0])
    if (diagnosis.year && ((targetYear && targetYear !== text(diagnosis.year)) || (!currentFolderMatches && recordYear && recordYear !== text(diagnosis.year)))) { results.push(finding('identity_error', `作品年份对不上：当前硬链接归到了同名的另一版${missingSuffix}`)); break }
    const titles = [current.title, current.original_title, current.media_name, recordMedia.title, recordMedia.original_title, recordMedia.name].map(cleanTitle).filter(Boolean)
    const identityMismatch = recordSource && recordId && diagnosis.media_source && diagnosis.media_id && `${recordSource}:${recordId}` !== `${normaliseMediaSource(diagnosis.media_source)}:${diagnosis.media_id}`
    if (!currentFolderMatches && ((currentFolder && !titlesCompatible([currentFolder], proposed)) || (titles.length && !titlesCompatible(titles, proposed))) && identityMismatch) { results.push(finding('identity_error', `作品识别错误：当前硬链接归到了另一部作品${missingSuffix}`)); break }
  }
  if (diagnosis.season && record.season && Number(record.season) !== Number(diagnosis.season)) results.push(finding('hierarchy_error', '季目录对不上：当前整理季与整包证据不一致', 'review'))
  for (const row of successful) {
    const sourceEpisodes = strictEpisodeKeys(sourcePath(row)); const targetEpisodes = strictEpisodeKeys(destinationPath(row))
    if (sourceEpisodes.length && targetEpisodes.length && !episodeKeysCompatible(sourcePath(row), destinationPath(row))) { results.push(finding('episode_error', `剧集对应错误：源文件与当前硬链接的集号不一致${missingSuffix}`)); break }
  }
  if (expectedKind === 'tv' && summary.episodes.length && currentRecords.length && currentRecords.every(row => !/(?:^|[\\/])(?:season|s)[ ._-]?\d{1,2}(?:[\\/]|$)/i.test(destinationPath(row)))) results.push(finding('hierarchy_error', `目录层级错误：剧集被平铺，没有作品和季目录${missingSuffix}`))
  if (failed.length) results.push(finding('native_failure', `部分整理失败：当前仍有 ${failed.length} 个源文件没有建立成功硬链接`))
  if (!failed.length && successful.length && presentSuccessful.length < successful.length) results.push(finding('unconfirmed', `有 ${successful.length - presentSuccessful.length} 个历史硬链接现在不存在；可能是手工删除，确认前不会当成整理失败`, 'review'))
  return [...new Map(results.map(item => [`${item.kind}:${item.reason}`, item])).values()]
}

export function diffMap(previous = {}, next = {}) {
  const oldUnits = new Map((previous.download_units || []).map(item => [item.id, item.fingerprint]))
  const changed = (next.download_units || []).filter(item => oldUnits.get(item.id) !== item.fingerprint).map(item => item.id)
  return { changed, unchanged: (next.download_units || []).length - changed.length, first: !previous.map_version }
}

export function findingLabel(kind) {
  return ({ multiple_errors: '多个整理问题', native_failure: '原生整理失败', category_error: '目录分类错误', hierarchy_error: '目录层级错误', episode_error: '剧集对应错误', identity_error: '作品识别错误', unconfirmed: '无法确认', uncovered: '尚未覆盖' })[kind] || '需要核对'
}

export function normaliseMediaSource(value) {
  const raw = text(value).toLowerCase()
  if (raw.includes('豆瓣')) return 'douban'
  const source = raw.replace(/[^a-z0-9]/g, '')
  if (['tmdb', 'themoviedb'].includes(source)) return 'tmdb'
  if (source === 'douban') return 'douban'
  return source
}
