import { cleanTitle, isSampleItem, latestHistoryRows, pathKey, sourcePath, strictEpisodeHints, subtitlePattern, videoPattern } from './governance.js'

const seasonOf = value => Number(String(value || '').match(/(?:^|[\\/ ._-])S(?:eason[ ._-]?)?(\d{1,2})(?=E\d|$|[\\/ ._-])/i)?.[1] || 0)
const matchingRoot = (path, roots = []) => [...roots]
  .filter(root => { const value = pathKey(path); const base = pathKey(root?.path); return value === base || value.startsWith(`${base}/`) })
  .sort((left, right) => pathKey(right?.path).length - pathKey(left?.path).length)[0]
const relativeParts = (path, root) => {
  const value = pathKey(path); const base = pathKey(root?.path || root)
  return value.startsWith(`${base}/`) ? value.slice(base.length + 1).split('/') : []
}

/**
 * 下载任务只是证据边界，不等于一部作品。优先按包内第一层作品目录拆分；
 * 没有独立子目录时再按季拆分。单文件电影和普通单季剧保持为一个作品单元。
 */
export function createWorkUnits (pkg = {}) {
  const allEntries = (pkg.entries || []).filter(item => !isSampleItem(item))
  const videos = allEntries.filter(item => videoPattern.test(item?.name || '') && item?.path)
  const historySources = new Set((pkg.history || []).map(row => pathKey(sourcePath(row))))
  const orphanSubtitles = allEntries.filter(item => subtitlePattern.test(item?.name || '') && item?.path && historySources.has(pathKey(item.path)))
  if (!videos.length && !orphanSubtitles.length) return []
  const primaryFiles = videos.length ? videos : orphanSubtitles
  const topGroups = new Map()
  for (const video of primaryFiles) {
    const root = matchingRoot(video.path, pkg.roots || [pkg.root]) || pkg.root
    const parts = relativeParts(video.path, root)
    const rootKey = pathKey(root?.path)
    const key = (pkg.roots || []).length > 1 ? `root:${rootKey}` : parts.length > 1 ? `dir:${parts[0]}` : ''
    if (!topGroups.has(key)) topGroups.set(key, [])
    topGroups.get(key).push(video)
  }
  const isStructural = key => /^dir:(season|specials?|extras?|bonus|disc|cd)[ ._-]*\d*$/i.test(key)
  const namedTopGroups = [...topGroups].filter(([key]) => key && !isStructural(key))
  // 季目录是同一作品的结构，不再拆成多张卡；只有多个明确作品子目录才拆分。
  const groups = pkg.complete !== false && namedTopGroups.length > 1 && !topGroups.has('')
    ? namedTopGroups.map(([key, rows]) => ({ key, rows }))
    : [{ key: 'all', rows: primaryFiles }]
  return groups.map((group, index) => {
    const groupRoots = group.key.startsWith('root:')
      ? [group.key.slice(5)]
      : group.key.startsWith('dir:')
        ? (pkg.roots || [pkg.root]).map(root => `${pathKey(root?.path)}/${group.key.slice(4)}`)
        : (pkg.roots || [pkg.root]).map(root => pathKey(root?.path))
    const belongs = path => group.key === 'all' || groupRoots.some(root => pathKey(path) === root || pathKey(path).startsWith(`${root}/`))
    const entries = allEntries.filter(item => item?.path && belongs(item.path))
    const paths = new Set(entries.map(item => pathKey(item.path)))
    const history = latestHistoryRows((pkg.history || []).filter(row => !isSampleItem({ path: sourcePath(row), name: sourcePath(row).split(/[\\/]/).pop() }) && (paths.has(pathKey(sourcePath(row))) || belongs(sourcePath(row)))))
    const seasons = [...new Set(group.rows.flatMap(item => [seasonOf(item.path), seasonOf(item.name)].filter(Boolean)))]
    const label = group.key.startsWith('dir:') ? cleanTitle(group.key.slice(4)) : group.key.startsWith('root:')
      ? cleanTitle((pkg.roots || []).find(root => pathKey(root?.path) === group.key.slice(5))?.name)
      : cleanTitle(pkg.root?.name)
    return {
      ...pkg,
      id: `${pkg.id}:work:${group.key || index}`,
      package_id: pkg.id,
      entries,
      history,
      work_key: group.key,
      work_label: label || cleanTitle(group.rows[0]?.name) || `作品 ${index + 1}`,
      season_hint: seasons.length === 1 ? seasons[0] : 0,
      episode_hints: [...new Set(group.rows.flatMap(item => strictEpisodeHints(item.name)))].sort((a, b) => a - b),
      attachment_only: !videos.length,
    }
  })
}
