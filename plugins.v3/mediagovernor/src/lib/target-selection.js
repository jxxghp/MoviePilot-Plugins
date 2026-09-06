import { categoryOfIdentity, categoryOfRoot } from './governance.js'

/**
 * 目标根目录只由已确认作品类型和 MoviePilot 的媒体库配置共同决定。
 * 下载源目录的映射不能作为目标真值；同类配置不唯一时必须让用户处理配置歧义。
 */
export function selectLibraryTarget (identity = {}, roots = []) {
  const category = categoryOfIdentity(identity)
  if (!category) return { selected: null, reason: '作品类型还没有确认，无法选择媒体库目录' }
  const matches = roots.filter(root => categoryOfRoot(root) === category)
  if (!matches.length) return { selected: null, reason: `没有找到唯一的${categoryLabel(category)}媒体库目录` }
  if (matches.length > 1) return { selected: null, reason: `${categoryLabel(category)}媒体库目录有 ${matches.length} 个，无法安全地自动选择` }
  const root = matches[0]
  return {
    selected: {
      target_path: root.path,
      target_storage: root.storage || 'local',
      transfer_type: 'link',
      scrape: root.scraping || false,
      library_type_folder: root.library_type_folder || false,
      library_category_folder: root.library_category_folder || false,
    },
    root,
    category,
    reason: `已按作品类型选择${categoryLabel(category)}媒体库目录`,
  }
}

export function categoryLabel (category) {
  return ({ movie: '电影', tv: '电视剧', animation: '动漫', other: '其他' })[category] || '对应类型'
}
