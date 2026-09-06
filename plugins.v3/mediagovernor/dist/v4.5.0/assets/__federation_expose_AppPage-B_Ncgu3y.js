import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const text$1 = value => String(value || '').trim();
const unique = values => [...new Set(values.filter(Boolean))];

const videoPattern = /\.(mkv|mp4|avi|m2ts|ts|mov|webm)$/i;
const subtitlePattern = /\.(ass|ssa|srt|sub|vtt)$/i;

function isSampleItem(item = {}) {
  const path = pathKey(item.path || item.name);
  return /(?:^|\/)samples?(?:\/|$)/i.test(path) || /(?:^|[ ._-])sample(?:[ ._-]|\.)/i.test(String(item.name || ''))
}

function cleanTitle(value) {
  return text$1(value).replace(/\.[a-z0-9]{2,5}$/i, '').replace(/[\[【(（].*?[\]】)）]/g, ' ')
    .replace(/\b(2160p|1080p|720p|web[ .-]?(dl|rip)|bluray|bdrip|remux|x26[45]|h\.?26[45]|hevc|aac|dts|atmos|hdr10?\+?|dv|10bit|proper|repack|complete|中字|简繁|国语|粤语)\b/gi, ' ')
    .replace(/[._-]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120)
}

function strictEpisodeHints(value) {
  const name = text$1(value); const found = [];
  for (const match of name.matchAll(/\bS\d{1,2}E(\d{1,3})\b/ig)) found.push(Number(match[1]));
  for (const match of name.matchAll(/\b(?:EP|E)(\d{1,3})\b/ig)) found.push(Number(match[1]));
  for (const match of name.matchAll(/[\[【](\d{1,3})[\]】]/g)) found.push(Number(match[1]));
  return unique(found.filter(value => value > 0 && value < 1000)).sort((a, b) => a - b)
}

function strictEpisodeKeys(value) {
  const name = text$1(value); const found = [];
  for (const match of name.matchAll(/\bS(\d{1,2})E(\d{1,3})\b/ig)) found.push(`S${Number(match[1])}E${Number(match[2])}`);
  if (found.length) return unique(found)
  const season = Number(name.match(/(?:^|[\\/ ._-])(?:season|s)[ ._-]?(\d{1,2})(?=[\\/ ._-]|$)/i)?.[1] || 0);
  return strictEpisodeHints(name).map(episode => season ? `S${season}E${episode}` : `E${episode}`)
}

function episodeKeysCompatible(leftValue, rightValue) {
  const left = strictEpisodeKeys(leftValue); const right = strictEpisodeKeys(rightValue);
  if (!left.length || !right.length) return true
  const parts = key => ({ season: Number(key.match(/^S(\d+)E/)?.[1] || 0), episode: Number(key.match(/E(\d+)$/)?.[1] || 0) });
  const a = left.map(parts); const b = right.map(parts);
  return a.length === b.length && a.every((item, index) => item.episode === b[index].episode && (!item.season || !b[index].season || item.season === b[index].season))
}

function fileFingerprint(item = {}) {
  return [text$1(item.name), text$1(item.type), Number(item.size) || 0, text$1(item.modify_time || item.mtime)].join('|')
}

/** 固定长度的非加密摘要；用于变化检测，避免长目录清单在 API/持久化层被截断。 */
function compactFingerprint(value) {
  const source = String(value || '');
  let left = 0x811c9dc5; let right = 0x9e3779b9;
  for (let index = 0; index < source.length; index += 1) {
    const code = source.charCodeAt(index);
    left = Math.imul(left ^ code, 0x01000193) >>> 0;
    right = Math.imul(right ^ code, 0x85ebca6b) >>> 0;
  }
  return `${source.length.toString(16).padStart(8, '0')}${left.toString(16).padStart(8, '0')}${right.toString(16).padStart(8, '0')}`
}

function unitFingerprint(unit = {}) {
  return compactFingerprint([text$1(unit.root?.path || unit.root), ...(unit.entries || []).map(fileFingerprint).sort()].join('\n'))
}

function rootFingerprint(items = []) { return compactFingerprint([...items].map(fileFingerprint).sort().join('\n')) }

/** 下载包第一层指纹；单文件下载必须把文件本身算进去。 */
function packageHeaderFingerprint(roots = [], children = []) {
  return rootFingerprint([...(roots || []).filter(item => item?.type !== 'dir'), ...(children || [])])
}

function pathKey(value) {
  return String(value || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '').toLowerCase()
}

function isRootPath(value) {
  const path = pathKey(value);
  return !path || path === '/' || /^[a-z]:$/i.test(path)
}

function isWithinPath(value, root) {
  const path = pathKey(value); const base = pathKey(root);
  return Boolean(path && base && (path === base || path.startsWith(`${base}/`)))
}

/** 把“目录配置”显式转换为 FileItem；配置对象本身绝不能送进 storage/list。 */
function configuredDownloadRoots(configurations = []) {
  const roots = []; const rejected = []; const seen = new Set();
  for (const configuration of configurations) {
    const path = String(configuration?.download_path || '').trim();
    const storage = String(configuration?.storage || 'local').trim() || 'local';
    if (isRootPath(path)) { rejected.push({ name: text$1(configuration?.name) || '未命名目录配置', reason: '下载目录为空或指向容器根目录' }); continue }
    const key = `${storage}:${pathKey(path)}`;
    if (seen.has(key)) continue
    seen.add(key);
    roots.push({ type: 'dir', storage, path, name: text$1(configuration?.name) || path, configured: true, media_type: text$1(configuration?.media_type), media_category: text$1(configuration?.media_category) });
  }
  return { roots, rejected }
}

function configuredLibraryRoots(configurations = []) {
  const roots = []; const seen = new Set();
  for (const configuration of configurations) {
    const path = String(configuration?.library_path || '').trim();
    const storage = String(configuration?.library_storage || 'local').trim() || 'local';
    if (isRootPath(path)) continue
    const key = `${storage}:${pathKey(path)}`;
    if (seen.has(key)) continue
    seen.add(key);
    roots.push({
      type: 'dir', storage, path, name: text$1(configuration?.name) || path,
      media_type: text$1(configuration?.media_type), media_category: text$1(configuration?.media_category),
      transfer_type: text$1(configuration?.transfer_type) || 'link', scraping: Boolean(configuration?.scraping),
      library_type_folder: Boolean(configuration?.library_type_folder), library_category_folder: Boolean(configuration?.library_category_folder),
    });
  }
  return roots
}

function libraryRootForPath(path, roots = []) {
  return [...roots].filter(root => isWithinPath(path, root?.path)).sort((left, right) => pathKey(right?.path).length - pathKey(left?.path).length)[0] || null
}

function sourcePath(row = {}) {
  const item = row.src_fileitem || row.source_fileitem || row.fileitem || {};
  return String(item.path || row.src || row.source || '')
}

function destinationPath(row = {}) {
  const item = row.dest_fileitem || {};
  return String(item.path || row.dest || '')
}

function latestFirst(left, right) {
  const leftDate = Date.parse(left?.date || '') || 0; const rightDate = Date.parse(right?.date || '') || 0;
  if (leftDate !== rightDate) return rightDate - leftDate
  const sequence = value => Number(String(value || '').match(/(\d+)$/)?.[1] || 0);
  return sequence(right?.id) - sequence(left?.id)
}

function latestHistory(rows = []) { return [...rows].sort(latestFirst)[0] || null }

/** 同一源文件的旧整理记录只作审计依据，当前目标只认该源文件最近一次结果。 */
function latestHistoryRows(rows = []) {
  const bySource = new Map();
  for (const row of [...rows].sort(latestFirst)) {
    const source = pathKey(sourcePath(row)) || `history:${row?.id || bySource.size}`;
    if (!bySource.has(source)) bySource.set(source, row);
  }
  return [...bySource.values()].sort(latestFirst)
}

function createDownloadUnits(root, children = []) {
  // 顶层目录或顶层视频各是一个下载单元；不再用相似标题拼成虚构“包”。
  return children.filter(item => item?.type === 'dir' || videoPattern.test(item?.name || '')).map(item => ({
    id: `${root?.storage || 'local'}:${item?.path || item?.name}`, root: item, entries: [], status: 'pending',
  }))
}

/** 地图只持久化媒体库根摘要；具体存在性由整理历史指向的目标目录逐一核验。 */
function libraryRootSnapshot(roots = []) {
  return roots.filter(root => root && typeof root === 'object').map(root => ({
    id: `${root.storage || 'local'}:${root.path || root.name || ''}`,
    root,
    fingerprint: fileFingerprint(root),
    video_count: 0,
    episodes: [],
    category: cleanTitle(root.name) || '媒体库根',
  }))
}

function summarizeUnit(unit = {}) {
  const episodeFiles = new Map(); let video_count = 0; let subtitle_count = 0; let nfo_count = 0;
  for (const item of unit.entries || []) {
    if (isSampleItem(item)) continue
    const name = text$1(item.name);
    if (videoPattern.test(name)) { video_count += 1; for (const episode of strictEpisodeKeys(name)) episodeFiles.set(episode, [...(episodeFiles.get(episode) || []), name]); }
    else if (subtitlePattern.test(name)) subtitle_count += 1;
    else if (/\.nfo$/i.test(name)) nfo_count += 1;
  }
  const episode_keys = [...episodeFiles.keys()].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const episodes = unique(episode_keys.map(value => Number(value.match(/E(\d+)$/)?.[1] || 0)).filter(Boolean)).sort((a, b) => a - b);
  const duplicateEpisodes = [...episodeFiles].filter(([, files]) => new Set(files).size > 1).map(([episode]) => episode);
  return { video_count, subtitle_count, nfo_count, episodes, episode_keys, duplicateEpisodes, fingerprint: unitFingerprint(unit), names: unique([cleanTitle(unit.root?.name), ...(unit.entries || []).map(item => cleanTitle(item.name))].filter(Boolean)).slice(0, 50) }
}

const mediaKind$1 = value => /tv|series|电视剧|剧集|动漫|动画|综艺|纪录片/i.test(text$1(value)) ? 'tv' : /movie|film|电影/i.test(text$1(value)) ? 'movie' : '';

const categoryOfIdentity = identity => {
  const value = [identity?.category, ...(identity?.genres || [])].join(' ');
  const genreIds = new Set((identity?.genre_ids || []).map(Number));
  if (genreIds.has(16)) return 'animation'
  if (genreIds.has(99) || genreIds.has(10764) || genreIds.has(10767)) return 'other'
  if (/animation|动画|动漫|anime/i.test(value)) return 'animation'
  if (/variety|综艺|reality|talk[ -]?show/i.test(value)) return 'other'
  if (/documentary|纪录/i.test(value)) return 'other'
  return identity?.media_type === 'movie' ? 'movie' : identity?.media_type === 'tv' ? 'tv' : ''
};

const categoryOfRoot = root => {
  const value = [root?.name, root?.media_category, root?.media_type].join(' ');
  if (/动漫|动画|anime/i.test(value)) return 'animation'
  if (/其他|综艺|纪录|other/i.test(value)) return 'other'
  if (/movie|电影/i.test(value)) return 'movie'
  if (/tv|电视|剧集/i.test(value)) return 'tv'
  return ''
};

function destinationWorkFolder(value) {
  const parts = String(value || '').replace(/\\/g, '/').split('/').filter(Boolean);
  const season = parts.findIndex(part => /^(?:season|s)[ ._-]?\d{1,2}$/i.test(part));
  return cleanTitle(parts[season > 0 ? season - 1 : Math.max(0, parts.length - 2)] || '')
}

function titlesCompatible(leftValues = [], rightValues = []) {
  const left = leftValues.map(cleanTitle).filter(Boolean); const right = rightValues.map(cleanTitle).filter(Boolean);
  return left.some(a => right.some(b => a === b || (Math.min(a.length, b.length) >= 4 && (a.includes(b) || b.includes(a)))))
}

function classifyFinding({ unit, summary, history = [], library = [], diagnosis = null, presentPaths = new Set() }) {
  const finding = (kind, reason, strength = 'strong') => ({ kind, reason, strength, unit_id: unit.id, history_id: latestHistory(history)?.id || null });
  if (!summary.video_count && !(unit?.attachment_only && summary.subtitle_count)) return []
  const currentHistory = latestHistoryRows(history);
  const successful = currentHistory.filter(row => row?.status === true);
  const failed = currentHistory.filter(row => row?.status === false);
  const presentSuccessful = successful.filter(row => presentPaths.has(pathKey(destinationPath(row))));
  const targetMissing = successful.length && successful.every(row => !row?.dest_fileitem?.path && !row?.dest);
  if (failed.length && !successful.length) return [finding('native_failure', '原生整理失败：当前源文件仍在且没有成功建立硬链接')]
  if (targetMissing) return [finding('unconfirmed', '历史记录没有保存可核验的目标位置，不能判断当前是否仍有问题', 'review')]
  if (!diagnosis || diagnosis.abstain || diagnosis.confidence < .5) return failed.length ? [finding('native_failure', `部分整理失败：当前仍有 ${failed.length} 个源文件没有建立成功硬链接`)] : []
  const currentRecords = presentSuccessful;
  const record = currentRecords[0] || {}; const recordKind = mediaKind$1(record.type || record.media_type || record.category);
  const expectedKind = diagnosis.media_type;
  const missingSuffix = failed.length ? `；另有 ${failed.length} 个源文件当前仍未整理成功` : '';
  const expectedCategory = categoryOfIdentity(diagnosis);
  const currentRoots = currentRecords.map(row => libraryRootForPath(destinationPath(row), library)).filter(Boolean);
  const currentCategories = [...new Set(currentRoots.map(categoryOfRoot).filter(Boolean))];
  const results = [];
  if (expectedCategory && currentCategories.length && currentCategories.some(value => value !== expectedCategory)) results.push(finding('category_error', `目录分类错误：当前位置与已确认作品类型不同${missingSuffix}`));
  else if (recordKind && expectedKind !== 'unknown' && recordKind !== expectedKind) results.push(finding('category_error', `媒体类型对不上：当前整理结果与已确认作品类型不同${missingSuffix}`));
  for (const current of currentRecords) {
    const recordMedia = current.media_info || current.mediainfo || current.media || {};
    const recordSource = normaliseMediaSource(current.media_source || recordMedia.media_source || recordMedia.source);
    const recordId = text$1(current.media_id || current.tmdb_id || current.douban_id || recordMedia.media_id || recordMedia.tmdb_id || recordMedia.douban_id || recordMedia.id);
    const currentFolder = destinationWorkFolder(destinationPath(current));
    const proposed = [diagnosis.title, diagnosis.original_title];
    const currentFolderMatches = currentFolder && titlesCompatible([currentFolder], proposed);
    const recordYear = text$1(current.year || recordMedia.year || recordMedia.release_year);
    const targetYear = text$1(destinationPath(current).match(/\b(?:19|20)\d{2}\b/)?.[0]);
    if (diagnosis.year && ((targetYear && targetYear !== text$1(diagnosis.year)) || (!currentFolderMatches && recordYear && recordYear !== text$1(diagnosis.year)))) { results.push(finding('identity_error', `作品年份对不上：当前硬链接归到了同名的另一版${missingSuffix}`)); break }
    const titles = [current.title, current.original_title, current.media_name, recordMedia.title, recordMedia.original_title, recordMedia.name].map(cleanTitle).filter(Boolean);
    const identityMismatch = recordSource && recordId && diagnosis.media_source && diagnosis.media_id && `${recordSource}:${recordId}` !== `${normaliseMediaSource(diagnosis.media_source)}:${diagnosis.media_id}`;
    if (!currentFolderMatches && ((currentFolder && !titlesCompatible([currentFolder], proposed)) || (titles.length && !titlesCompatible(titles, proposed))) && identityMismatch) { results.push(finding('identity_error', `作品识别错误：当前硬链接归到了另一部作品${missingSuffix}`)); break }
  }
  if (diagnosis.season && record.season && Number(record.season) !== Number(diagnosis.season)) results.push(finding('hierarchy_error', '季目录对不上：当前整理季与整包证据不一致', 'review'));
  for (const row of successful) {
    const sourceEpisodes = strictEpisodeKeys(sourcePath(row)); const targetEpisodes = strictEpisodeKeys(destinationPath(row));
    if (sourceEpisodes.length && targetEpisodes.length && !episodeKeysCompatible(sourcePath(row), destinationPath(row))) { results.push(finding('episode_error', `剧集对应错误：源文件与当前硬链接的集号不一致${missingSuffix}`)); break }
  }
  if (expectedKind === 'tv' && summary.episodes.length && currentRecords.length && currentRecords.every(row => !/(?:^|[\\/])(?:season|s)[ ._-]?\d{1,2}(?:[\\/]|$)/i.test(destinationPath(row)))) results.push(finding('hierarchy_error', `目录层级错误：剧集被平铺，没有作品和季目录${missingSuffix}`));
  if (failed.length) results.push(finding('native_failure', `部分整理失败：当前仍有 ${failed.length} 个源文件没有建立成功硬链接`));
  if (!failed.length && successful.length && presentSuccessful.length < successful.length) results.push(finding('unconfirmed', `有 ${successful.length - presentSuccessful.length} 个历史硬链接现在不存在；可能是手工删除，确认前不会当成整理失败`, 'review'));
  return [...new Map(results.map(item => [`${item.kind}:${item.reason}`, item])).values()]
}

function findingLabel(kind) {
  return ({ multiple_errors: '多个整理问题', native_failure: '原生整理失败', category_error: '目录分类错误', hierarchy_error: '目录层级错误', episode_error: '剧集对应错误', identity_error: '作品识别错误', unconfirmed: '无法确认', uncovered: '尚未覆盖' })[kind] || '需要核对'
}

function normaliseMediaSource(value) {
  const raw = text$1(value).toLowerCase();
  if (raw.includes('豆瓣')) return 'douban'
  const source = raw.replace(/[^a-z0-9]/g, '');
  if (['tmdb', 'themoviedb'].includes(source)) return 'tmdb'
  if (source === 'douban') return 'douban'
  return source
}

/** 所有完整读取到的视频作品单元都要识别；历史不得决定诊断范围。 */
function identityTargets (units = []) {
  return units.filter(unit => unit?.complete && (unit?.summary?.video_count || (unit?.attachment_only && unit?.summary?.subtitle_count)))
}

/** AI 只兜底 MoviePilot 无法给出唯一身份的单元，避免全库重复消耗。 */
function aiFallbackTargets (units = []) {
  return identityTargets(units).filter(unit => {
    unit.native_conflict = nativeEvidenceConflict(unit, unit?.nativeIdentity);
    return !unit?.nativeIdentity || unit?.attachment_only || unit.native_conflict
  })
}

function nativeEvidenceConflict(unit = {}, identity = null) {
  if (!identity?.media_id || !identity?.media_source) return true
  const names = [unit?.work_label, ...(unit?.summary?.names || [])].map(cleanTitle).filter(Boolean);
  const years = [...new Set(names.flatMap(name => String(name).match(/\b(?:19|20)\d{2}\b/g) || []))];
  if (years.length > 1) return true
  if (years.length === 1 && String(identity.year || '') !== years[0]) return true
  if ((unit?.summary?.episode_keys || []).length && identity.media_type !== 'tv') return true
  const evidence = names.map(name => name.toLowerCase().replace(/\b(?:19|20)\d{2}\b/g, ' ').replace(/\bs\d{1,2}(?:e\d{1,3})?\b/gi, ' ').replace(/\b(?:ep|e)\d{1,3}\b/gi, ' ').replace(/\s+/g, ' ').trim()).filter(name => name.length >= 4 && !/^\d+$/.test(name));
  const candidates = [identity?.title, identity?.original_title].map(cleanTitle).map(name => name.toLowerCase()).filter(name => name.length >= 4);
  if (evidence.length && candidates.length && !evidence.some(name => candidates.some(candidate => name.includes(candidate) || candidate.includes(name)))) return true
  // 发布名常含压制组、语言、分辨率与别名，标题字面不一致不能单独推翻
  // MoviePilot 已在多个样本上给出的同一数据源身份；年份与媒体类型硬冲突仍须 AI 复核。
  return false
}

/**
 * MoviePilot 的联邦页面在不同宿主版本会多包一层或两层 data。
 * 业务代码只接受最终负载；失败响应始终原样抛出，不能被误当成空数据。
 */
function unwrapMoviePilotResponse (value) {
  let current = value;
  const seen = new Set();
  for (let depth = 0; depth < 6 && current && typeof current === 'object'; depth += 1) {
    if (seen.has(current)) break
    seen.add(current);
    if (current.success === false) throw new Error(current.message || 'MoviePilot 请求失败')
    if (!Object.prototype.hasOwnProperty.call(current, 'data') || current.data === undefined) break
    current = current.data;
  }
  return current
}

function historySucceeded (row = {}, fallback = null) {
  const value = row.status;
  if (typeof value === 'boolean') return value
  if (value == null || value === '') return fallback
  return ['true', 'success', 'succeeded', 'ok', '完成', '成功'].includes(String(value).trim().toLowerCase())
}

function normaliseHistoryRows (rows = [], fallback = null) {
  return (Array.isArray(rows) ? rows : []).map(row => ({ ...row, status: historySucceeded(row, fallback) }))
}

function officialPreviewItems (preview = {}) {
  const rows = Array.isArray(preview?.items) ? preview.items : Array.isArray(preview?.data?.items) ? preview.data.items : [];
  return rows.filter(item => item && item.success !== false && item.target)
}

function previewComplete (preview = {}, sourceCount = 0) {
  const summary = preview?.summary || preview?.data?.summary || {};
  return Number(summary.total) === Number(sourceCount) && Number(summary.success) === Number(sourceCount) && Number(summary.failed || 0) === 0 && officialPreviewItems(preview).length === Number(sourceCount)
}

const seasonOf$1 = value => Number(String(value || '').replace(/\\/g, '/').match(/\/(?:s|season)[ ._-]?(\d{1,2})(?=\/|$)/i)?.[1] || 0);
const parentTitle = value => cleanTitle(String(value || '').replace(/\\/g, '/').split('/').slice(-2, -1)[0] || '');

/** 一个作品单元只输出一个结论；details 在详情页解释所有逐文件差异。 */
function evaluateOfficialPreview ({ unit, identity, preview, presentPaths = new Set(), libraryRootFor = () => null } = {}) {
  const finding = (kind, reason, details = []) => ({ kind, reason, details, strength: 'strong', unit_id: unit?.id || '', history_id: latestHistoryRows(unit?.history || [])[0]?.id || null });
  if (!unit?.complete) return finding('uncovered', '文件没有完整读取，暂时不能判断')
  if (!identity || identity.abstain || !identity.media_source || !identity.media_id) return finding('unconfirmed', unit?.identity_reason || '作品身份还没有确认')
  const requestedCount = Array.isArray(unit?.previewPayload?.fileitems) ? unit.previewPayload.fileitems.length : 0;
  const sourceCount = requestedCount || (unit.entries || []).filter(item => item?.path && (videoPattern.test(item?.name || item?.path) || (unit?.attachment_only && subtitlePattern.test(item?.name || item?.path)))).length;
  if (!previewComplete(preview, sourceCount)) return finding('unconfirmed', unit?.preview_error || 'MoviePilot 没有生成完整逐文件预览')
  const expected = officialPreviewItems(preview).map(item => pathKey(item.target));
  const successful = latestHistoryRows(unit.history || []).filter(row => row?.status === true && destinationPath(row));
  const current = successful.map(row => pathKey(destinationPath(row))).filter(path => presentPaths.has(path));
  const expectedPresent = expected.filter(path => presentPaths.has(path));
  if (!current.length) {
    if (expectedPresent.length === expected.length) return null
    return finding('native_failure', '原文件仍在，但官方应有目标没有完整建立', expected.filter(path => !presentPaths.has(path)))
  }
  const missing = expected.filter(path => !presentPaths.has(path));
  const unexpected = current.filter(path => !expected.includes(path));
  if (!missing.length && !unexpected.length) return null
  const details = [`缺少 ${missing.length} 个应有目标`, `存在 ${unexpected.length} 个错误目标`];
  const expectedRoots = new Set(expected.map(libraryRootFor).filter(Boolean).map(root => root.media_type || root.media_category || root.name));
  const currentRoots = new Set(current.map(libraryRootFor).filter(Boolean).map(root => root.media_type || root.media_category || root.name));
  if (expectedRoots.size && currentRoots.size && ![...expectedRoots].some(value => currentRoots.has(value))) return finding('category_error', '当前硬链接放错了媒体库分类', details)
  const expectedSeasons = new Set(expected.map(seasonOf$1).filter(Boolean)); const currentSeasons = new Set(current.map(seasonOf$1).filter(Boolean));
  if (expectedSeasons.size && currentSeasons.size && ![...expectedSeasons].some(value => currentSeasons.has(value))) return finding('hierarchy_error', '当前硬链接放错了季目录', details)
  const expectedEpisodes = expected.flatMap(strictEpisodeHints); const currentEpisodes = current.flatMap(strictEpisodeHints);
  if (expectedEpisodes.length && currentEpisodes.length && expectedEpisodes.join(',') !== currentEpisodes.join(',')) return finding('episode_error', '当前文件与应有集号对应不上', details)
  const expectedTitles = new Set(expected.map(parentTitle).filter(Boolean)); const currentTitles = new Set(current.map(parentTitle).filter(Boolean));
  if (expectedTitles.size && currentTitles.size && ![...expectedTitles].some(value => currentTitles.has(value))) return finding('identity_error', '当前硬链接归到了另一部作品', details)
  return finding('hierarchy_error', '当前硬链接位置与 MoviePilot 官方预览不一致', details)
}

const stable = value => String(value || '').trim();
const idFor = value => String(value || '').replace(/[^a-zA-Z0-9:_-]/g, '_').slice(0, 160);

/**
 * 把目录第一层“候选根”与历史关联为下载包。download_hash 是强证据；顶层目录只是降级边界。
 * 不以相似标题合并，因此无法确认的散件绝不会被伪装为同一下载任务。
 */
function createEvidencePackages (roots = [], histories = []) {
  const rootRows = roots.map(root => ({ root, history: histories.filter(row => isWithinPath(sourcePath(row), root?.path)) }));
  const buckets = new Map();
  for (const item of rootRows) {
    const hashes = [...new Set(item.history.map(row => stable(row?.download_hash)).filter(Boolean))];
    const key = hashes.length === 1 ? `hash:${hashes[0]}` : `root:${pathKey(item.root?.path || item.root?.name)}`;
    const bucket = buckets.get(key) || { key, roots: [], history: [], hashes: new Set(), boundary: hashes.length === 1 ? 'download_hash' : 'top_level' };
    bucket.roots.push(item.root); bucket.history.push(...item.history); hashes.forEach(hash => bucket.hashes.add(hash));
    if (hashes.length > 1) bucket.boundary = 'conflict';
    buckets.set(key, bucket);
  }
  return [...buckets.values()].map(bucket => {
    const history = latestHistoryRows(bucket.history);
    const hashes = [...bucket.hashes];
    return {
      id: idFor(bucket.key), roots: bucket.roots, root: bucket.roots[0], history,
      download_hashes: hashes, boundary: bucket.boundary,
      boundary_reason: boundaryReason(bucket.boundary, bucket.roots.length, hashes.length),
      entries: [], complete: true,
    }
  })
}

function boundaryReason (boundary, rootCount = 0, hashCount = 0) {
  if (boundary === 'download_hash') return `已由同一下载任务编号关联${rootCount > 1 ? ` ${rootCount} 个顶层项目` : ''}`
  if (boundary === 'conflict') return `同一顶层项目关联到 ${hashCount} 个下载任务编号，不能自动合并`
  return '没有可用下载任务编号；仅按顶层目录暂时分组，不能自动重建'
}

function appendTreeEvidence (pkg, trees = []) {
  const entries = []; let complete = pkg?.complete !== false;
  for (const tree of trees) {
    entries.push(...(tree?.entries || [])); complete = complete && Boolean(tree?.complete);
  }
  return { ...pkg, entries, complete, evidence: packageEvidence({ ...pkg, entries, complete }) }
}

function packageEvidence (pkg = {}) {
  const entries = Array.isArray(pkg.entries) ? pkg.entries.filter(item => !isSampleItem(item)) : [];
  const videos = entries.filter(item => videoPattern.test(item?.name || ''));
  const directories = entries.filter(item => item?.type === 'dir');
  const subtitles = entries.filter(item => /\.(ass|ssa|srt|sub|vtt)$/i.test(item?.name || ''));
  const titles = [...new Set([
    ...(pkg.roots || []).map(item => cleanTitle(item?.name)),
    ...videos.map(item => cleanTitle(item?.name)),
    ...subtitles.map(item => cleanTitle(item?.name)),
  ].filter(Boolean))].slice(0, 80);
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

function previewSourceFiles (pkg = {}) {
  const historySources = new Set(latestHistoryRows(pkg.history || []).map(row => pathKey(sourcePath(row))).filter(Boolean));
  return (pkg.entries || []).filter(item => {
    if (!item?.path || isSampleItem(item)) return false
    if (videoPattern.test(item?.name || '')) return true
    return subtitlePattern.test(item?.name || '') && historySources.has(pathKey(item.path))
  }).map(item => ({ type: item.type || 'file', storage: item.storage || pkg.root?.storage || 'local', path: item.path, name: item.name, size: item.size, modify_time: item.modify_time }))
}

function repairAdmission (pkg = {}, identity = null, preview = null) {
  if (!pkg.complete) return { allowed: false, reason: '文件证据没有完整读取，不能重建' }
  if (pkg.boundary === 'conflict') return { allowed: false, reason: '同一文件边界关联了多个下载任务，不能自动重建' }
  if (!identity?.media_source || !identity?.media_id) return { allowed: false, reason: '作品身份没有得到 MoviePilot 数据源编号确认，不能重建' }
  if (!identity?.evidence_verified && !identity?.user_confirmed) return { allowed: false, reason: '作品身份没有经过整包证据核验或你的明确选择，不能重建' }
  const sourceCount = previewSourceFiles(pkg).length;
  if (!previewComplete(preview, sourceCount)) return { allowed: false, reason: '官方逐文件预览不完整或含失败项，不能重建' }
  const roots = pkg.roots || [pkg.root];
  const attributable = previewSourceFiles(pkg).every(item => roots.some(root => isWithinPath(item.path, root?.path))) && latestHistoryRows(pkg.history || []).every(row => roots.some(root => isWithinPath(sourcePath(row), root?.path)));
  if (!attributable) return { allowed: false, reason: '有文件或历史无法唯一归到当前下载单元，不能自动重建' }
  const histories = latestHistoryRows(pkg.history || []).filter(row => row?.status === true && row?.id);
  if (!histories.length) return { allowed: true, mode: 'create', reason: '这是没有旧成功目标的原生整理失败；将只从原始下载建立新硬链接', history_ids: [] }
  const successfulSources = new Set(histories.map(row => pathKey(sourcePath(row))));
  const pendingFileitems = previewSourceFiles(pkg).filter(item => !successfulSources.has(pathKey(item.path)));
  if (pendingFileitems.length) return { allowed: true, mode: 'mixed', reason: `将重建 ${histories.length} 个错误旧结果，并为 ${pendingFileitems.length} 个未成功源视频建立硬链接`, history_ids: histories.map(row => row.id), create_fileitems: pendingFileitems }
  return { allowed: true, mode: 'rebuild', reason: `将逐条重建 ${histories.length} 个已归因的旧整理结果`, history_ids: histories.map(row => row.id) }
}

/** MoviePilot 的 ManualTransferItem.type_name 接受 MediaType 的中文枚举值。 */
function moviePilotTypeName (value) {
  if (value === 'movie' || value === '电影') return '电影'
  if (value === 'tv' || value === '电视剧') return '电视剧'
  return undefined
}

/** 只生成 MoviePilot ManualTransferItem 已声明的字段；绝不发送旧版不存在的 src_fileitem。 */
function manualPreviewRequest (pkg, identity, target = {}) {
  const fileitems = previewSourceFiles(pkg);
  return {
    fileitems,
    media_source: identity?.media_source || undefined,
    media_id: identity?.media_id || undefined,
    type_name: moviePilotTypeName(identity?.media_type),
    season: identity?.season || undefined,
    target_storage: target?.target_storage || undefined,
    target_path: target?.target_path || undefined,
    transfer_type: 'link',
    preview: true,
    reorganize: false,
  }
}

/** 每个成功历史单独交给官方重建，令宿主只清理该历史可归因的旧目标。 */
function manualRebuildRequests (historyIds = [], identity = {}, target = {}) {
  return [...new Set(historyIds.filter(value => Number.isInteger(Number(value))).map(Number))].map(logid => ({
    logid,
    media_source: identity.media_source,
    media_id: identity.media_id,
    type_name: moviePilotTypeName(identity.media_type),
    season: identity.season || undefined,
    target_storage: target.target_storage || undefined,
    target_path: target.target_path || undefined,
    transfer_type: target.transfer_type || 'link',
    scrape: target.scrape || false,
    library_type_folder: target.library_type_folder,
    library_category_folder: target.library_category_folder,
    preview: false,
    reorganize: false,
  }))
}

const seasonOf = value => Number(String(value || '').match(/(?:^|[\\/ ._-])S(?:eason[ ._-]?)?(\d{1,2})(?=E\d|$|[\\/ ._-])/i)?.[1] || 0);
const matchingRoot = (path, roots = []) => [...roots]
  .filter(root => { const value = pathKey(path); const base = pathKey(root?.path); return value === base || value.startsWith(`${base}/`) })
  .sort((left, right) => pathKey(right?.path).length - pathKey(left?.path).length)[0];
const relativeParts = (path, root) => {
  const value = pathKey(path); const base = pathKey(root?.path || root);
  return value.startsWith(`${base}/`) ? value.slice(base.length + 1).split('/') : []
};

/**
 * 下载任务只是证据边界，不等于一部作品。优先按包内第一层作品目录拆分；
 * 没有独立子目录时再按季拆分。单文件电影和普通单季剧保持为一个作品单元。
 */
function createWorkUnits (pkg = {}) {
  const allEntries = (pkg.entries || []).filter(item => !isSampleItem(item));
  const videos = allEntries.filter(item => videoPattern.test(item?.name || '') && item?.path);
  const historySources = new Set((pkg.history || []).map(row => pathKey(sourcePath(row))));
  const orphanSubtitles = allEntries.filter(item => subtitlePattern.test(item?.name || '') && item?.path && historySources.has(pathKey(item.path)));
  if (!videos.length && !orphanSubtitles.length) return []
  const primaryFiles = videos.length ? videos : orphanSubtitles;
  const topGroups = new Map();
  for (const video of primaryFiles) {
    const root = matchingRoot(video.path, pkg.roots || [pkg.root]) || pkg.root;
    const parts = relativeParts(video.path, root);
    const rootKey = pathKey(root?.path);
    const key = (pkg.roots || []).length > 1 ? `root:${rootKey}` : parts.length > 1 ? `dir:${parts[0]}` : '';
    if (!topGroups.has(key)) topGroups.set(key, []);
    topGroups.get(key).push(video);
  }
  const isStructural = key => /^dir:(season|specials?|extras?|bonus|disc|cd)[ ._-]*\d*$/i.test(key);
  const namedTopGroups = [...topGroups].filter(([key]) => key && !isStructural(key));
  // 季目录是同一作品的结构，不再拆成多张卡；只有多个明确作品子目录才拆分。
  const groups = pkg.complete !== false && namedTopGroups.length > 1 && !topGroups.has('')
    ? namedTopGroups.map(([key, rows]) => ({ key, rows }))
    : [{ key: 'all', rows: primaryFiles }];
  return groups.map((group, index) => {
    const groupRoots = group.key.startsWith('root:')
      ? [group.key.slice(5)]
      : group.key.startsWith('dir:')
        ? (pkg.roots || [pkg.root]).map(root => `${pathKey(root?.path)}/${group.key.slice(4)}`)
        : (pkg.roots || [pkg.root]).map(root => pathKey(root?.path));
    const belongs = path => group.key === 'all' || groupRoots.some(root => pathKey(path) === root || pathKey(path).startsWith(`${root}/`));
    const entries = allEntries.filter(item => item?.path && belongs(item.path));
    const paths = new Set(entries.map(item => pathKey(item.path)));
    const history = latestHistoryRows((pkg.history || []).filter(row => !isSampleItem({ path: sourcePath(row), name: sourcePath(row).split(/[\\/]/).pop() }) && (paths.has(pathKey(sourcePath(row))) || belongs(sourcePath(row)))));
    const seasons = [...new Set(group.rows.flatMap(item => [seasonOf(item.path), seasonOf(item.name)].filter(Boolean)))];
    const label = group.key.startsWith('dir:') ? cleanTitle(group.key.slice(4)) : group.key.startsWith('root:')
      ? cleanTitle((pkg.roots || []).find(root => pathKey(root?.path) === group.key.slice(5))?.name)
      : cleanTitle(pkg.root?.name);
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

const text = value => String(value || '').trim();
const mediaKind = value => /tv|series|电视剧|剧集|动漫|动画|综艺|纪录片/i.test(text(value)) ? 'tv' : /movie|film|电影/i.test(text(value)) ? 'movie' : 'unknown';

function identityFromRaw (raw = {}) {
  const value = raw?.media_info || raw?.mediaInfo || raw?.media || raw || {};
  const title = text(value.title || value.name || value.media_name).slice(0, 120);
  const genreValues = value.genres || value.genre_names || value.genreNames || value.genre || [];
  const genres = (Array.isArray(genreValues) ? genreValues : [genreValues]).map(item => text(item?.name || item)).filter(Boolean).slice(0, 20);
  const genreIds = (Array.isArray(value.genre_ids) ? value.genre_ids : []).map(Number).filter(Number.isFinite).slice(0, 20);
  const category = text(value.category || value.media_category || value.type_name || value.type);
  return {
    title,
    original_title: text(value.original_title || value.originalName).slice(0, 120),
    year: text(value.year),
    media_type: mediaKind(value.type || value.media_type || value.mtype),
    season: Number(value.season || value.season_number || 0) || 0,
    media_source: normaliseMediaSource(value.media_source || value.source),
    media_id: text(value.media_id || value.id),
    genres,
    genre_ids: genreIds,
    category,
    confidence: title ? 0.8 : 0,
    abstain: !title,
  }
}

const identityKey = value => value?.media_source && value?.media_id ? `${value.media_source}:${value.media_id}` : '';

const comparableNames = value => [value?.title, value?.original_title].map(cleanTitle).filter(Boolean);

function sameWork (left, right) {
  const leftNames = comparableNames(left); const rightNames = comparableNames(right);
  const titleMatches = leftNames.some(a => rightNames.some(b => a === b || (Math.min(a.length, b.length) >= 5 && (a.includes(b) || b.includes(a)))));
  const yearMatches = !left?.year || !right?.year || String(left.year) === String(right.year);
  const typeMatches = !left?.media_type || !right?.media_type || left.media_type === 'unknown' || right.media_type === 'unknown' || left.media_type === right.media_type;
  return Boolean(titleMatches && yearMatches && typeMatches)
}

function sameIdentity (left, right) {
  const a = identityKey(left); const b = identityKey(right);
  return Boolean(a && b && a === b)
}

function chooseGroundedCandidate (hint = {}, rawCandidates = []) {
  const candidates = rawCandidates.map(identityFromRaw).filter(item => identityKey(item));
  const wanted = cleanTitle(hint.title || hint.original_title);
  const scored = candidates.map(candidate => {
    const names = [candidate.title, candidate.original_title].map(cleanTitle).filter(Boolean);
    const titleScore = wanted && names.some(name => name === wanted) ? 4 : wanted && names.some(name => name.includes(wanted) || wanted.includes(name)) ? 2 : 0;
    const yearConflict = Boolean(hint.year && candidate.year && String(hint.year) !== String(candidate.year));
    const typeConflict = Boolean(hint.media_type && hint.media_type !== 'unknown' && candidate.media_type !== 'unknown' && hint.media_type !== candidate.media_type);
    const yearScore = !hint.year || !candidate.year ? 0 : 2;
    const typeScore = !hint.media_type || hint.media_type === 'unknown' || candidate.media_type === 'unknown' ? 0 : 1;
    return { candidate, score: titleScore + yearScore + typeScore, conflict: yearConflict || typeConflict }
  }).filter(item => !item.conflict && item.score >= 3).sort((a, b) => b.score - a.score);
  const best = scored[0];
  const unique = best && best.score >= 5 && !scored.slice(1).some(item => item.score >= best.score - 1 && !sameIdentity(item.candidate, best.candidate));
  return { selected: unique ? { ...best.candidate, evidence_verified: true } : null, candidates: scored.slice(0, 6).map(item => item.candidate) }
}

function reconcileIdentities (nativeIdentity, aiGrounded, evidenceHint = null, nativeConflict = false) {
  const native = identityKey(nativeIdentity) ? nativeIdentity : null;
  const ai = identityKey(aiGrounded?.selected) ? aiGrounded.selected : null;
  const candidates = [...new Map([native, ...(aiGrounded?.candidates || [])].filter(Boolean).map(item => [identityKey(item), item])).values()];
  if (nativeConflict && ai && native && (sameIdentity(native, ai) || sameWork(native, ai))) return { identity: { abstain: true, confidence: 0, title: '', media_type: 'unknown', evidence_verified: false }, candidates, reason: '整包证据与原生身份冲突，AI 仍返回同一冲突身份，不能自动确认' }
  if (native && ai && (sameIdentity(native, ai) || sameWork(native, ai))) return { identity: { ...native, evidence_verified: true, confidence: 1, abstain: false }, candidates, reason: '原生识别与整包 AI 证据指向同一作品' }
  if (native && ai && evidenceHint?.year && String(ai.year) === String(evidenceHint.year) && String(native.year || '') !== String(evidenceHint.year)) return { identity: { ...ai, confidence: 0.95, abstain: false }, candidates, reason: '文件结构有明确年份，AI 候选已由 MoviePilot 数据源落地' }
  if (nativeConflict && ai) return { identity: { ...ai, evidence_verified: true, confidence: 0.9, abstain: false }, candidates, reason: '原生识别与整包证据冲突，采用经数据源详情核验的整包候选' }
  // MoviePilot 已经给出唯一数据源编号时，它本身就是可执行身份。
  // AI 是原生弃权时的兜底，不应反过来否定原生唯一结果。
  if (native && !ai && !nativeConflict) return { identity: { ...native, evidence_verified: true, confidence: Math.max(Number(native.confidence) || 0, 0.85), abstain: false }, candidates, reason: 'MoviePilot 原生识别与文件名、年份、类型证据没有冲突' }
  if (!native && ai) return { identity: { ...ai, confidence: 0.9, abstain: false }, candidates, reason: 'AI 候选已由 MoviePilot 数据源唯一落地' }
  return { identity: { abstain: true, confidence: 0, title: '', media_type: 'unknown', evidence_verified: false }, candidates, reason: nativeConflict ? 'MoviePilot 原生识别与整包的年份、类型或标题证据冲突' : native && ai ? '原生识别与整包证据冲突' : '没有唯一作品身份' }
}

const workFolder = value => {
  const parts = String(value || '').replace(/\\/g, '/').split('/').filter(Boolean);
  const season = parts.findIndex(part => /^(?:season|s)[ ._-]?\d{1,2}$/i.test(part));
  return cleanTitle(parts[season > 0 ? season - 1 : Math.max(0, parts.length - 2)] || '')
};

function validatePreviewTarget ({ identity, preview, libraryRoots = [] } = {}) {
  if (!identity?.evidence_verified && !identity?.user_confirmed) return { valid: false, reason: '作品身份没有经过整包证据核验或你的明确选择，已禁止修复' }
  const expected = categoryOfIdentity(identity);
  const items = officialPreviewItems(preview);
  const roots = items.map(item => libraryRootForPath(item.target, libraryRoots)).filter(Boolean);
  const actual = [...new Set(roots.map(categoryOfRoot).filter(Boolean))];
  if (!expected || !actual.length) return { valid: false, reason: '无法确认官方预览选中的媒体库分类' }
  if (actual.some(value => value !== expected)) return { valid: false, reason: '官方预览选中的目录与作品类型不一致，已禁止修复' }
  const targets = items.map(item => pathKey(item.target));
  if (new Set(targets).size !== targets.length) return { valid: false, reason: '官方预览存在重复目标，已禁止修复' }
  const identityNames = [identity?.title, identity?.original_title].map(cleanTitle).filter(Boolean);
  for (const item of items) {
    const targetTitle = workFolder(item.target);
    const normalizedTarget = targetTitle.replace(/\s+(?:19|20)\d{2}$/i, '').trim();
    if (identityNames.length && normalizedTarget && !identityNames.includes(normalizedTarget)) return { valid: false, reason: '官方预览的作品目录与已确认作品名称不一致，已禁止修复' }
    const targetYear = String(item?.year || item?.release_year || item?.target || '').match(/\b(?:19|20)\d{2}\b/)?.[0];
    if (identity?.year && targetYear && String(identity.year) !== targetYear) return { valid: false, reason: '官方预览的作品年份与已确认版本不一致，已禁止修复' }
    const sourceKeys = strictEpisodeKeys(item.source);
    const targetKeys = strictEpisodeKeys(item.target);
    if (sourceKeys.length && targetKeys.length && !episodeKeysCompatible(item.source, item.target)) return { valid: false, reason: '官方预览的季集对应与原文件不一致，已禁止修复' }
  }
  return { valid: true, reason: '官方预览的目标分类已通过独立核对' }
}

/**
 * 生产和金标准共用的唯一判定入口。
 * 先用当前历史+实际目标证明问题；已完整建立且规则无冲突的作品直接正常；
 * 只有无历史或不完整项才需要官方预览作为最后证据。
 */
function evaluateCurrentState ({ unit, identity, preview, presentPaths = new Set(), libraryRoots = [] } = {}) {
  const summary = unit?.summary || summarizeUnit(unit);
  const rules = classifyFinding({ unit, summary, history: unit?.history || [], library: libraryRoots, diagnosis: identity, presentPaths });
  const proven = rules.filter(item => !['unconfirmed', 'uncovered'].includes(item.kind));
  if (proven.length > 1) return { ...proven[0], kind: 'multiple_errors', reason: proven.map(item => item.reason).join('；'), issues: proven }
  if (proven.length) return proven[0]
  if (rules.length) return rules[0]
  if (!identity || identity.abstain || !identity.evidence_verified) return { kind: 'unconfirmed', reason: unit?.identity_reason || '作品身份还没有经过整包证据确认', strength: 'review', unit_id: unit?.id || '' }
  const sourceVideos = new Set((unit?.entries || []).filter(item => videoPattern.test(item?.name || '')).map(item => pathKey(item.path)));
  const currentVideoSources = new Set(latestHistoryRows(unit?.history || [])
    .filter(row => row?.status === true && videoPattern.test(sourcePath(row)) && presentPaths.has(pathKey(destinationPath(row))))
    .map(row => pathKey(sourcePath(row))));
  if (sourceVideos.size && [...sourceVideos].every(path => currentVideoSources.has(path))) return null
  return evaluateOfficialPreview({ unit, identity, preview, presentPaths, libraryRootFor: path => libraryRootForPath(path, libraryRoots) })
}

/**
 * 目标根目录只由已确认作品类型和 MoviePilot 的媒体库配置共同决定。
 * 下载源目录的映射不能作为目标真值；同类配置不唯一时必须让用户处理配置歧义。
 */
function selectLibraryTarget (identity = {}, roots = []) {
  const category = categoryOfIdentity(identity);
  if (!category) return { selected: null, reason: '作品类型还没有确认，无法选择媒体库目录' }
  const matches = roots.filter(root => categoryOfRoot(root) === category);
  if (!matches.length) return { selected: null, reason: `没有找到唯一的${categoryLabel(category)}媒体库目录` }
  if (matches.length > 1) return { selected: null, reason: `${categoryLabel(category)}媒体库目录有 ${matches.length} 个，无法安全地自动选择` }
  const root = matches[0];
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

function categoryLabel (category) {
  return ({ movie: '电影', tv: '电视剧', animation: '动漫', other: '其他' })[category] || '对应类型'
}

function createRequestBudget () {
  const waiters = new Set();
  const run = async (operation, timeout, label) => {
    let timer, cancellationReject;
    const cancellation = new Promise((resolve, reject) => { cancellationReject = reject; waiters.add(reject); });
    try {
      return await Promise.race([
        Promise.resolve(operation),
        new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error(`${label}超过 ${Math.ceil(timeout / 1000)} 秒，已跳过`)), timeout); }),
        cancellation,
      ])
    } finally {
      clearTimeout(timer);
      waiters.delete(cancellationReject);
    }
  };
  const cancel = (message = '检查已停止') => {
    for (const reject of [...waiters]) reject(new Error(message));
    waiters.clear();
  };
  return { run, cancel, pending: () => waiters.size }
}

async function settledResults (operations = []) {
  const rows = await Promise.allSettled(operations);
  return {
    values: rows.filter(row => row.status === 'fulfilled').map(row => row.value),
    errors: rows.filter(row => row.status === 'rejected').map(row => row.reason),
  }
}

async function runBatchesUntilFailure (items = [], options = {}) {
  const pending = [...items];
  const completed = [];
  while (pending.length && !options.stopped?.()) {
    const batch = []; let chars = 0;
    while (pending.length && batch.length < options.maxItems) {
      const next = pending[0]; const cost = options.cost(next);
      if (batch.length && chars + cost > options.maxChars) break
      pending.shift(); batch.push(next); chars += cost;
    }
    try {
      const result = await options.run(batch);
      completed.push(...batch);
      options.success?.(batch, result);
    } catch (error) {
      const failed = [...batch, ...pending];
      options.failure?.(failed, error);
      return { completed, failed, error }
    }
  }
  return { completed, failed: [], error: null }
}

const {createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,normalizeStyle:_normalizeStyle,renderList:_renderList,Fragment:_Fragment,unref:_unref,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "governor-page" };
const _hoisted_2 = { class: "hero" };
const _hoisted_3 = { class: "actions" };
const _hoisted_4 = ["disabled"];
const _hoisted_5 = ["disabled"];
const _hoisted_6 = ["disabled"];
const _hoisted_7 = { class: "summary" };
const _hoisted_8 = {
  key: 0,
  class: "progress"
};
const _hoisted_9 = {
  key: 1,
  class: "notice"
};
const _hoisted_10 = { class: "panel" };
const _hoisted_11 = {
  key: 0,
  class: "empty"
};
const _hoisted_12 = { class: "kind" };
const _hoisted_13 = ["disabled", "onClick"];
const _hoisted_14 = {
  key: 2,
  class: "panel secondary-panel"
};
const _hoisted_15 = ["disabled", "onClick"];
const _hoisted_16 = {
  key: 3,
  class: "panel secondary-panel"
};
const _hoisted_17 = {
  key: 4,
  class: "backdrop"
};
const _hoisted_18 = { class: "modal" };
const _hoisted_19 = { class: "candidate" };
const _hoisted_20 = {
  key: 0,
  class: "candidate-list"
};
const _hoisted_21 = ["onClick"];
const _hoisted_22 = {
  key: 1,
  class: "candidate"
};
const _hoisted_23 = {
  key: 2,
  class: "warning"
};
const _hoisted_24 = ["disabled"];
const _hoisted_25 = {
  key: 3,
  class: "preview"
};
const _hoisted_26 = { class: "compare" };
const _hoisted_27 = { class: "warning" };
const _hoisted_28 = ["disabled"];

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');

const pageSize = 100, entryLimit = 20000;

const _sfc_main = {
  __name: 'AppPage',
  props: { api: { type: Object, default: () => ({}) } },
  setup(__props) {

const props = __props;
const state = ref({ ready: false, updated_at: '', download_units: 0, library_nodes: 0, findings: 0, dirty: 0 });
const phase = ref('尚未建立地图'), notice = ref(''), running = ref(false), stopped = ref(false), aiAvailable = ref(null);
const progress = ref({ done: 0, total: 0, current: '', started_at: 0 }), findings = ref([]), units = ref([]), histories = ref([]), preview = ref(null), selected = ref(null);
const liveMapReady = ref(false);
const now = ref(Date.now()), requestBudget = createRequestBudget();
let clock = null;
const canUseApi = computed(() => typeof props.api?.get === 'function' && typeof props.api?.post === 'function');
const percent = computed(() => progress.value.total ? Math.min(100, Math.round(progress.value.done * 100 / progress.value.total)) : 0);
const elapsedLabel = computed(() => running.value && progress.value.started_at ? `本阶段 ${Math.max(0, Math.floor((now.value - progress.value.started_at) / 1000))} 秒` : state.value.updated_at ? '已有媒体地图' : '尚未建立媒体地图');
const cards = computed(() => findings.value.filter(item => item.kind !== 'unconfirmed' && item.kind !== 'uncovered'));
const pendingCards = computed(() => findings.value.filter(item => item.kind === 'unconfirmed'));
const uncoveredCards = computed(() => findings.value.filter(item => item.kind === 'uncovered'));
const provenCount = computed(() => cards.value.length);
const uncoveredCount = computed(() => findings.value.filter(item => item.kind === 'uncovered').length);
const safe = value => String(value || '').replace(/[\\/]/g, '').replace(/\s+/g, ' ').trim().slice(0, 160);
const displayPath = value => String(value || '').replace(/\\/g, '/') || '尚未建立';
function currentTargetFor(source) {
  const row = latestHistoryRows(selected.value?.unit?.history || []).find(item => pathKey(sourcePath(item)) === pathKey(source));
  return displayPath(destinationPath(row))
}
function previewRows(value) {
  return officialPreviewItems(value).map(item => ({ source: displayPath(item.source), current: currentTargetFor(item.source), expected: displayPath(item.target), episode: [item.season ? `S${String(item.season).padStart(2, '0')}` : '', item.episode ? `E${String(item.episode).padStart(2, '0')}` : ''].filter(Boolean).join('') || '电影' }))
}
const keyOf = item => `${item?.storage || 'local'}:${item?.path || item?.name || ''}`;
function fail(error, fallback) { notice.value = error?.message || fallback; }
function stage(label, total = 1, current = '') { phase.value = label; progress.value = { done: 0, total: Math.max(1, total), current, started_at: Date.now() }; now.value = Date.now(); }
function advance(current = '') { progress.value.done = Math.min(progress.value.total, progress.value.done + 1); if (current) progress.value.current = current; }
function resetRun(label) {
  running.value = true; stopped.value = false; liveMapReady.value = false; notice.value = ''; findings.value = []; units.value = []; histories.value = [];
  stage(label, 1, '正在准备检查范围。');
  if (clock) clearInterval(clock);
  clock = setInterval(() => { now.value = Date.now(); }, 1000);
}
function stop() {
  stopped.value = true;
  requestBudget.cancel();
  notice.value = '已停止等待；未完成的本轮结果不会保存，也没有改变任何媒体。';
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
    const snapshot = await get('plugin/MediaGovernor/map_snapshot');
    state.value = { ...state.value, ...(snapshot?.summary || snapshot || {}) };
    findings.value = Array.isArray(snapshot?.findings) ? snapshot.findings : [];
    if (state.value.ready) notice.value = `已载入上次结论：${provenCount.value} 个真实问题，${pendingCards.value.length} 个等待确认作品，${uncoveredCount.value} 个未完成覆盖。可直接点开任一卡片查看上次保存的证据。`;
  } catch (error) { fail(error, '无法读取已保存的媒体地图'); }
}
function listOf(raw) { return Array.isArray(raw) ? raw : raw?.items || raw?.list || raw?.data || [] }
async function directories(kind) { return listOf(await get(`storage/directories?directory_type=${kind}`)) }
async function list(item) { const value = await post('storage/list', item, 12000, '读取目录'); if (!Array.isArray(value)) throw new Error('MoviePilot 没有返回目录列表'); return value }
async function history(status) { const rows = []; for (let page = 1; !stopped.value; page += 1) { const data = await get(`history/transfer?status=${status}&page=${page}&count=${pageSize}`, 15000, '读取整理历史'); const batch = listOf(data); rows.push(...batch); if (batch.length < pageSize) break } return normaliseHistoryRows(rows, status) }
async function walk(root, recursive = true) {
  const entries = []; const queue = root?.type === 'dir' ? [{ item: root, depth: 0 }] : []; let readFailures = 0;
  if (root?.type !== 'dir') entries.push({ ...root, depth: 0 });
  while (queue.length && !stopped.value) {
    const current = queue.shift(); let children;
    try { children = await list(current.item); } catch { readFailures += 1; continue }
    for (const child of children) {
      if (entries.length >= entryLimit) return { entries, complete: false }
      const item = { ...child, depth: current.depth + 1 }; entries.push(item);
      if (recursive && child?.type === 'dir') queue.push({ item: child, depth: current.depth + 1 });
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
  const parentItems = new Map(); const expectedByUnit = new Map();
  for (const unit of allUnits) {
    const expected = targetPaths(unit); const parentKeys = [];
    for (const row of latestHistoryRows(unit.history).filter(row => row?.status === true)) {
      const target = destinationPath(row); const parent = parentOf(target, row?.dest_fileitem?.storage || row?.dest_storage);
      if (!parent) continue
      const key = keyOf(parent); parentItems.set(key, parent); parentKeys.push(key);
    }
    for (const item of officialPreviewItems(unit.officialPreview)) {
      const parent = parentOf(item.target, unit.previewPayload?.target_storage || 'local');
      if (!parent) continue
      const key = keyOf(parent); parentItems.set(key, parent); parentKeys.push(key);
    }
    expectedByUnit.set(unit.id, { expected, parentKeys: [...new Set(parentKeys)] });
  }
  const readable = new Map(); let readFailures = 0;
  const parents = [...parentItems.entries()]; stage('核对当前整理目标', parents.length, '只读取整理历史实际指向的目标目录，不扫描整座媒体库。');
  if (!parents.length) progress.value.done = progress.value.total;
  let cursor = 0;
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1;
      if (index >= parents.length) return
      const [key, parent] = parents[index];
      try {
        const items = (await list(parent)).filter(item => item?.path);
        readable.set(key, new Map(items.map(item => [pathKey(item.path), item])));
      } catch { readable.set(key, null); readFailures += 1; }
      advance(`已完成 ${progress.value.done + 1}/${parents.length} 个目标目录；读不到的目录会明确列为未覆盖。`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(8, parents.length) }, worker));
  const states = new Map();
  for (const unit of allUnits) {
    const plan = expectedByUnit.get(unit.id) || { expected: [], parentKeys: [] }; const present = new Map(); let complete = true;
    for (const key of plan.parentKeys) {
      const entries = readable.get(key);
      if (entries == null) { complete = false; continue }
      for (const [path, entry] of entries) present.set(path, entry);
    }
    const target_watch = plan.parentKeys.map(key => ({ item: parentItems.get(key), fingerprint: readable.get(key) ? rootFingerprint([...readable.get(key).values()]) : '' })).filter(row => row.item);
    states.set(unit.id, { expected: plan.expected, present, complete, target_watch });
  }
  return { states, parentCount: parents.length, readFailures }
}
async function detectTargetChanges() {
  if (!state.value.ready) return 0
  const watch = listOf(await get('plugin/MediaGovernor/map_watch')); const changedUnits = new Set(); let changed = 0; let cursor = 0;
  const worker = async () => {
    while (cursor < watch.length) {
      const index = cursor; cursor += 1; const row = watch[index];
      try { if (rootFingerprint(await list(row.item)) !== row.fingerprint) { changed += 1; if (row.unit_id) changedUnits.add(row.unit_id); } } catch { changed += 1; if (row.unit_id) changedUnits.add(row.unit_id); }
    }
  };
  await Promise.all(Array.from({ length: Math.min(8, watch.length) }, worker));
  if (changed) await post('plugin/MediaGovernor/map_dirty', { unit_ids: [...changedUnits], reason: `发现 ${changed} 个媒体库目标目录发生变动` });
  return changed
}
function modelEvidence(unit, summary) {
  const evidence = packageEvidence(unit);
  const directories = evidence.entries.filter(item => item.type === 'dir').slice(0, 8);
  const files = evidence.entries.filter(item => item.type === 'file');
  const indexes = [...new Set([...Array(Math.min(12, files.length)).keys(), ...Array.from({ length: Math.min(12, files.length) }, (_, index) => Math.max(0, files.length - 12 + index)), ...Array.from({ length: Math.min(12, files.length) }, (_, index) => Math.floor(index * Math.max(files.length - 1, 0) / Math.max(Math.min(12, files.length) - 1, 1)))])];
  const entries = [...directories, ...indexes.map(index => files[index]).filter(Boolean)].slice(0, 44).map(item => ({ ...item, name: safe(item.name).slice(0, 110) }));
  return { title_hints: evidence.title_hints.slice(0, 16), entries, video_count: evidence.video_count, episodes: summary.episodes, boundary: evidence.boundary, ai_truncated: evidence.entries.length > entries.length }
}
async function askAi(candidates) {
  if (!candidates.length || aiAvailable.value === false) return new Map()
  stage('智能助手复核', candidates.length, `共有 ${candidates.length} 个原生身份仍有冲突；小批处理，首次超时即停止后续批次。`);
  const diagnoses = new Map();
  const failures = [];
  try {
    const pending = candidates.map(item => ({ id: item.id, evidence: modelEvidence(item, item.summary) }));
    const outcome = await runBatchesUntilFailure(pending, {
      maxItems: 4,
      maxChars: 8000,
      cost: row => JSON.stringify(row.evidence).length,
      stopped: () => stopped.value,
      run: rows => post('plugin/MediaGovernor/bundle_analyze_batch', { items: rows }, 35000, '智能助手复核'),
      success: (rows, result) => {
        for (const [id, diagnosis] of Object.entries(result.diagnoses || {})) diagnoses.set(id, diagnosis);
        for (const id of result.omitted || []) diagnoses.set(id, { abstain: true, confidence: 0, reasons: ['证据超过智能助手单批安全上限'] });
        progress.value.done += rows.length;
        progress.value.current = `已完成 ${progress.value.done}/${progress.value.total} 个智能复核。`;
      },
      failure: (rows, error) => {
        const reason = error?.message || '智能助手没有完成这一批';
        failures.push(reason);
        for (const row of rows) diagnoses.set(row.id, { abstain: true, confidence: 0, reasons: [reason], transient_error: true });
        progress.value.done = progress.value.total;
        progress.value.current = '智能助手本轮首次失败后已熔断，不再继续空等。';
      },
    });
    if (outcome.error) notice.value = '智能助手本轮失败，已立即停止后续批次；规则和原生识别仍会继续形成结论。';
    return diagnoses
  } catch (error) { aiAvailable.value = false; notice.value = `${error?.message || '智能助手不可用'}；本轮只保留规则能证明的问题。`; return diagnoses }
}
async function identifyUnits() {
  const target = identityTargets(units.value);
  if (!target.length) return
  let cached = {};
  try {
    const response = await post('plugin/MediaGovernor/map_identities', { units: target.map(unit => ({ id: unit.id, fingerprint: unit.summary?.fingerprint || '' })) }, 10000, '读取作品身份缓存');
    cached = response?.identities || {};
  } catch { cached = {}; }
  const unresolved = [];
  for (const unit of target) {
    const stored = cached[unit.id];
    if (stored?.nativeIdentity) {
      unit.nativeIdentity = stored.nativeIdentity;
      unit.native_identity_errors = [];
    } else unresolved.push(unit);
  }
  stage('核验作品身份', unresolved.length || 1, unresolved.length ? `复用 ${target.length - unresolved.length} 个未变化身份，只核验 ${unresolved.length} 个。` : `已复用全部 ${target.length} 个未变化身份。`);
  if (!unresolved.length) { progress.value.done = progress.value.total; return }
  let cursor = 0;
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1;
      if (index >= unresolved.length) return
      const unit = unresolved[index]; const videos = unit.entries.filter(item => videoPattern.test(item?.name || '') && item?.path);
      const sampleIndexes = [...new Set([0, Math.floor((videos.length - 1) / 2), videos.length - 1].filter(value => value >= 0))];
      const samples = sampleIndexes.map(value => videos[value]).filter(Boolean);
      if (!samples.length && unit.attachment_only) samples.push(...unit.entries.filter(item => item?.path && /\.(ass|ssa|srt|sub|vtt)$/i.test(item?.name || '')).slice(0, 3));
      const settled = await settledResults(samples.map(async sample => identityFromRaw(await get(`media/recognize_file?path=${encodeURIComponent(sample.path)}`, 15000, '原生作品识别'))));
      const usable = settled.values.filter(candidate => !candidate.abstain);
      const identities = [...new Set(usable.map(identityKey).filter(Boolean))];
      unit.nativeIdentity = usable.length && identities.length === 1 ? usable[0] : null;
      unit.native_identity_errors = settled.errors.map(error => error?.message || '原生识别失败');
      advance(`已完成 ${progress.value.done + 1}/${unresolved.length}；单个样本失败不会再丢掉其他成功结果。`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(4, unresolved.length) }, worker));
}
async function groundAiDiagnoses(aiDiagnoses) {
  const target = units.value.filter(unit => aiDiagnoses.has(unit.id)); if (!target.length) return
  stage('核对智能候选', target.length, 'AI 只提供标题线索；可执行身份仍需由 MoviePilot 数据源唯一确认。');
  let cursor = 0;
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1; if (index >= target.length) return
      const unit = target[index]; const hint = aiDiagnoses.get(unit.id);
      let grounded = { selected: null, candidates: [] };
      if (hint && !hint.abstain && hint.title) {
        try {
          const query = [hint.title, hint.year].filter(Boolean).join(' ');
          const rows = listOf(await get(`media/search?title=${encodeURIComponent(query)}&type=media&page=1&count=8`, 15000, '搜索作品候选'));
          const detailed = await Promise.all(rows.slice(0, 8).map(async row => {
            const identity = identityFromRaw(row);
            if (!identityKey(identity) || identity.media_type === 'unknown') return row
            try {
              return await get(`media/${encodeURIComponent(identity.media_id)}?media_source=${encodeURIComponent(identity.media_source)}&type_name=${encodeURIComponent(moviePilotTypeName(identity.media_type))}`, 15000, '读取作品详情')
            } catch { return row }
          }));
          grounded = chooseGroundedCandidate(hint, detailed);
        } catch { grounded = { selected: null, candidates: [] }; }
      }
      const resolved = reconcileIdentities(unit.nativeIdentity, grounded, hint, unit.native_conflict);
      unit.diagnosis = resolved.identity; unit.candidates = resolved.candidates; unit.identity_reason = resolved.reason; unit.aiDiagnosis = hint;
      if (hint?.transient_error && unit.diagnosis?.abstain) unit.identity_reason = `智能助手本批失败：${hint.reasons?.[0] || '未知原因'}；下次检查会重试`;
      advance(`已完成 ${progress.value.done + 1}/${target.length} 个候选落地。`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(4, target.length) }, worker));
}
async function generateOfficialPreviews() {
  // 首次检查只为“没有任何历史可交叉验证”的作品生成官方预览。
  // 旧失败、错误分类和错作品先由当前历史+实际目标直接判断，点开卡片时再实时生成修复预览。
  const target = units.value.filter(unit => identityKey(unit.diagnosis) && !unit.history.length); if (!target.length) return
  stage('生成必要的官方预览', target.length, '仅为没有任何历史可交叉验证的作品生成预览。');
  let cursor = 0;
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1; if (index >= target.length) return
      const unit = target[index];
      try {
        const base = manualPreviewRequest(unit, unit.diagnosis);
        const selection = selectLibraryTarget(unit.diagnosis, unit.libraryRoots || []);
        if (!selection.selected) throw new Error(selection.reason)
        const targetPath = selection.selected;
        unit.previewPayload = { ...base, ...targetPath, preview: true, reorganize: false };
        unit.officialPreview = await post('transfer/manual', unit.previewPayload, 30000, '生成官方逐文件预览');
        if (!previewComplete(unit.officialPreview, base.fileitems.length)) throw new Error('MoviePilot 逐文件预览不完整')
      } catch (error) { unit.preview_error = error?.message || '官方预览生成失败'; unit.officialPreview = null; }
      advance(`已完成 ${progress.value.done + 1}/${target.length}；只有完整预览才会形成可修复结论。`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(3, target.length) }, worker));
}
async function scanDownloadUnits(toScan, total) {
  stage('读取发生变化的下载单元', toScan.length || 1, toScan.length ? `本轮只深度读取 ${toScan.length}/${total} 个下载包。` : `共 ${total} 个下载包，当前没有源文件变化。`);
  if (!toScan.length) { progress.value.done = progress.value.total; units.value = []; return }
  const results = new Array(toScan.length); let cursor = 0;
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1;
      if (index >= toScan.length) return
      const unit = toScan[index];
      try {
        const trees = await Promise.all((unit.roots || [unit.root]).map(root => walk(root)));
        Object.assign(unit, appendTreeEvidence(unit, trees)); unit.summary = summarizeUnit(unit); unit.headerFingerprint = packageHeaderFingerprint(unit.roots || [unit.root], unit.entries.filter(item => Number(item.depth) === 1));
      } catch { unit.entries = []; unit.complete = false; unit.summary = summarizeUnit(unit); }
      results[index] = unit; advance(`已完成 ${progress.value.done + 1}/${toScan.length}；读不到的目录会保留为尚未覆盖。`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(4, toScan.length) }, worker));
  units.value = results.filter(Boolean);
}
async function scanPackageHeaders(packages) {
  if (!packages.length) return
  stage('轻量检查源文件变化', packages.length, '只读取每个下载包的第一层目录指纹，不做作品识别。');
  let cursor = 0;
  const worker = async () => {
    while (!stopped.value) {
      const index = cursor; cursor += 1;
      if (index >= packages.length) return
      const pkg = packages[index];
      try {
        const rows = await Promise.all((pkg.roots || [pkg.root]).map(root => list(root)));
        pkg.headerFingerprint = packageHeaderFingerprint(pkg.roots || [pkg.root], rows.flat());
      } catch { pkg.headerFingerprint = ''; }
      advance(`已轻量核对 ${progress.value.done + 1}/${packages.length} 个下载包。`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(8, packages.length) }, worker));
}
async function buildMap(full = false) {
  if (!canUseApi.value) { notice.value = 'MoviePilot 页面 API 尚未注入，无法建立地图。'; return }
  resetRun(full ? '建立完整媒体地图' : '复核当前变动');
  try {
    stage('读取检查范围', 4, '同时读取下载目录、媒体库目录及成功/失败整理历史。');
    const tasks = [directories('download'), directories('library'), history(false), history(true)].map(task => Promise.resolve(task).finally(() => advance()));
    const [downloadConfigurations, libraryConfigurations, failed, successful] = await Promise.all(tasks);
    histories.value = [...failed, ...successful];
    const scope = configuredDownloadRoots(downloadConfigurations);
    if (!scope.roots.length) throw new Error('没有可用下载目录：拒绝扫描空路径或容器根目录')
    stage('读取下载区顶层项目', scope.roots.length, '只读取 MoviePilot 已配置的下载目录，不扫描容器根目录。'); const discovered = [];
    for (const root of scope.roots) { if (stopped.value) break; discovered.push(...createDownloadUnits(root, await list(root))); advance(`已读取 ${progress.value.done + 1}/${scope.roots.length} 个下载根目录。`); }
    const top = [...new Map(discovered.map(unit => [keyOf(unit.root), unit])).values()];
    const packages = createEvidencePackages(top.map(unit => unit.root), histories.value);
    const libraryRoots = configuredLibraryRoots(libraryConfigurations);
    const initial = !state.value.ready || full;
    if (!initial) await detectTargetChanges();
    if (!initial) await scanPackageHeaders(packages);
    const plan = initial ? { unchanged: [] } : await post('plugin/MediaGovernor/map_plan', { units: packages.map(unit => ({ id: unit.id, fingerprint: unit.headerFingerprint || rootFingerprint(unit.roots) })) });
    const toScan = initial ? packages : packages.filter(unit => !new Set(plan.unchanged || []).has(unit.id));
    progress.value.current = initial ? `发现 ${top.length} 个顶层项目，归为 ${packages.length} 个下载包；历史只用来关联，不当成问题数。` : `发现 ${packages.length} 个下载包，其中 ${toScan.length} 个发生变动，需要深度复核。`;
    await scanDownloadUnits(toScan, packages.length);
    units.value = units.value.flatMap(createWorkUnits);
    for (const unit of units.value) { unit.summary = summarizeUnit(unit); unit.libraryRoots = libraryRoots; }
    const libraryNodes = libraryRootSnapshot(libraryRoots);
    await identifyUnits();
    // AI 只兜底 MoviePilot 原生无法确认的单元；AI 结果仍必须回到 MoviePilot 数据源落地。
    const candidates = aiFallbackTargets(units.value);
    const diagnoses = await askAi(candidates);
    await groundAiDiagnoses(diagnoses);
    for (const unit of units.value.filter(item => !item.diagnosis)) {
      const resolved = reconcileIdentities(unit.nativeIdentity, { selected: null, candidates: [] }, null, unit.native_conflict);
      unit.diagnosis = resolved.identity; unit.candidates = resolved.candidates; unit.identity_reason = resolved.reason;
    }
    await generateOfficialPreviews();
    const targetAudit = await scanTargetParents(units.value);
    const refined = [];
    if (scope.rejected.length) refined.push({ unit_id: 'scope:invalid', title: `${scope.rejected.length} 个下载目录配置`, kind: 'uncovered', reason: '下载目录为空或指向容器根目录，已拒绝扫描；请在 MoviePilot 目录设置中修正', strength: 'review' });
    for (const unit of units.value) {
      if (!unit.complete) { refined.push({ unit_id: unit.id, title: cleanTitle(unit.root?.name) || '未命名下载单元', kind: 'uncovered', reason: '当前下载单元未完整读取，暂不能下结论', strength: 'review' }); continue }
      if (!unit.summary.video_count && !unit.attachment_only) continue
      const targetState = targetAudit.states.get(unit.id) || { expected: targetPaths(unit), present: new Map(), complete: false };
      unit.target_watch = targetState.target_watch || [];
      if (!targetState.complete) { refined.push({ unit_id: unit.id, title: unit.work_label, kind: 'uncovered', reason: '当前目标目录没有完整读取，暂时不能判断', strength: 'review' }); continue }
      const finding = evaluateCurrentState({ unit, identity: unit.diagnosis, preview: unit.officialPreview, presentPaths: new Set(targetState.present.keys()), libraryRoots });
      if (finding) refined.push({ ...finding, title: unit.work_label, boundary: unit.boundary, candidate_count: unit.candidates?.length || 0 });
    }
    const linkedHistoryIds = new Set(units.value.flatMap(unit => unit.history.map(row => String(row?.id || ''))));
    const unlinkedUnits = units.value.filter(unit => unit.summary.video_count && !unit.history.length);
    findings.value = dedupe(refined); phase.value = stopped.value ? '已停止（未保存不完整地图）' : '保存当前媒体地图';
    if (!stopped.value) {
      const linkedUnits = units.value.filter(unit => unit.history.length).length;
      const unmatchedFailed = failed.filter(item => !linkedHistoryIds.has(String(item?.id || ''))).length;
      stage('保存当前媒体地图', 2, '只保存本轮证据和结论，不修改任何媒体文件。');
      const historyUnit = new Map(units.value.flatMap(unit => unit.history.map(row => [String(row.id), unit.id])));
      const commit = await post('plugin/MediaGovernor/map_commit', { baseline: initial, partial: !initial, scope_verified: true, download_units: units.value.map(unit => ({ id: unit.id, package_id: unit.package_id, root: unit.root, label: unit.work_label || cleanTitle(unit.root?.name) || '未命名下载单元', fingerprint: unit.summary.fingerprint, header_fingerprint: unit.headerFingerprint || rootFingerprint(unit.roots), video_count: unit.summary.video_count, subtitle_count: unit.summary.subtitle_count, nfo_count: unit.summary.nfo_count, episodes: unit.summary.episodes, names: unit.summary.names, history: unit.history.map(row => row.id), boundary: unit.boundary, coverage: unit.complete ? 'complete' : 'uncovered', detail: unit })), library_nodes: libraryNodes, findings: findings.value, coverage: { configured_download_roots: scope.roots.length, rejected_download_roots: scope.rejected.length, download_units: packages.length, scanned_units: units.value.length, library_roots: libraryNodes.length, target_parent_dirs: targetAudit.parentCount, target_parent_read_failures: targetAudit.readFailures, failed_history: failed.length, successful_history: successful.length, linked_units: linkedUnits, unlinked_units: units.value.length - linkedUnits, unmatched_failed_history: unmatchedFailed, uncovered_units: uncoveredCount.value }, history_summary: histories.value.map(row => ({ id: row.id, status: row.status, mode: row.mode, media_source: row.media_source, media_id: row.media_id, target: destinationPath(row), download_hash: row.download_hash, unit_id: historyUnit.get(String(row.id)) || '' })) }, 20000, '保存媒体地图');
      advance('媒体地图已保存，正在读取公开摘要。');
      state.value = { ...state.value, ...commit };
      const saved = await get('plugin/MediaGovernor/map_snapshot');
      advance('公开摘要已核对。');
      findings.value = Array.isArray(saved?.findings) ? saved.findings : findings.value;
      liveMapReady.value = true;
      phase.value = '地图已更新'; notice.value = `已读到失败历史 ${failed.length} 条、成功历史 ${successful.length} 条；本轮复核 ${units.value.length} 个下载单元。核对了 ${targetAudit.parentCount} 个当前整理目标目录（${targetAudit.readFailures} 个暂不可读）。已证明 ${provenCount.value} 个问题，另有 ${findings.value.filter(item => item.kind === 'unconfirmed').length} 个无法确认、${uncoveredCount.value} 个尚未覆盖。`;
    }
  } catch (error) { fail(error, '建立地图失败；没有改变任何媒体。'); phase.value = '建立地图未完成'; }
  finally { running.value = false; if (clock) { clearInterval(clock); clock = null; } }
}
function dedupe(rows) { const map = new Map(); for (const row of rows) { const key = `${row.unit_id}:${row.kind}:${row.reason}`; if (!map.has(key)) map.set(key, row); } return [...map.values()] }
function titleFor(card) { const unit = units.value.find(item => item.id === card.unit_id); return card?.title || unit?.work_label || cleanTitle(unit?.root?.name) || '未命名下载单元' }
async function recognize(card) {
  let unit = units.value.find(item => item.id === card.unit_id);
  if (!unit?.root?.path) {
    try {
      const result = await post('plugin/MediaGovernor/map_unit', { unit_id: card.unit_id });
      unit = result?.unit;
    } catch (error) { fail(error, '无法读取这个作品的已保存证据'); return }
  }
  selected.value = { card, unit, candidate: identityKey(unit.diagnosis) ? unit.diagnosis : null, candidates: unit.candidates || [], error: '', preview_payload: unit.previewPayload || null, admission: null };
  preview.value = unit.officialPreview || null;
  if (preview.value && selected.value.candidate) selected.value.admission = repairAdmission(unit, selected.value.candidate, preview.value);
  if (!selected.value.candidate && !selected.value.candidates.length) selected.value.error = '当前证据没有得到可用候选。请先检查智能助手和媒体数据源配置。';
}
function selectCandidate(candidate) { selected.value.candidate = { ...candidate, user_confirmed: true }; selected.value.error = ''; selected.value.preview_payload = null; selected.value.admission = null; preview.value = null; }
function previewPayload() {
  return manualPreviewRequest(selected.value?.unit, selected.value?.candidate)
}
async function makePreview() {
  try {
    const base = previewPayload();
    if (!base.fileitems.length || !base.media_source || !base.media_id) throw new Error('缺少经 MoviePilot 确认的作品身份或视频文件')
    const selection = selectLibraryTarget(selected.value.candidate, selected.value.unit.libraryRoots || []);
    if (!selection.selected) throw new Error(selection.reason)
    const target = selection.selected;
    const payload = { ...base, ...target, preview: true, reorganize: false };
    preview.value = await post('transfer/manual', payload);
    selected.value.preview_payload = payload;
    selected.value.admission = repairAdmission(selected.value.unit, selected.value.candidate, preview.value);
    const targetPolicy = validatePreviewTarget({ identity: selected.value.candidate, preview: preview.value, libraryRoots: selected.value.unit.libraryRoots || [] });
    if (!targetPolicy.valid) selected.value.admission = { allowed: false, reason: targetPolicy.reason };
    selected.value.unit.diagnosis = selected.value.candidate; selected.value.unit.previewPayload = payload; selected.value.unit.officialPreview = preview.value;
    const targetAudit = await scanTargetParents([selected.value.unit]);
    const targetState = targetAudit.states.get(selected.value.unit.id) || { present: new Map(), complete: false };
    const updated = targetState.complete ? evaluateOfficialPreview({ unit: selected.value.unit, identity: selected.value.candidate, preview: preview.value, presentPaths: new Set(targetState.present.keys()) }) : null;
    selected.value.card = updated ? { ...selected.value.card, ...updated } : { ...selected.value.card, kind: 'normal', reason: '按当前官方预览核对，这个作品暂时没有已证明的整理差异' };
    const index = findings.value.findIndex(item => item.unit_id === selected.value.card.unit_id);
    if (updated) {
      const next = { ...selected.value.card, ...updated, title: titleFor(selected.value.card) };
      if (index >= 0) findings.value.splice(index, 1, next);
      else findings.value.push(next);
      selected.value.card = next;
    } else if (index >= 0) findings.value.splice(index, 1);
  } catch (error) { selected.value.error = error?.message || '官方预览没有生成'; fail(error, '官方预览没有生成；没有删除或重建任何硬链接。'); }
}
async function repair() {
  const admission = selected.value?.admission;
  if (!admission?.allowed) { notice.value = admission?.reason || '当前预览不满足安全重建条件。'; return }
  if (!window.confirm(`确认按本次官方预览重建吗？${admission.reason}。原始下载不会被删除。`)) return
  try {
    if (admission.mode === 'create') await postWrite('transfer/manual', { ...selected.value.preview_payload, preview: false, reorganize: false });
    else {
      for (const payload of manualRebuildRequests(admission.history_ids, selected.value.candidate, selected.value.preview_payload)) await postWrite('transfer/manual', payload);
      if (admission.mode === 'mixed' && admission.create_fileitems?.length) await postWrite('transfer/manual', { ...selected.value.preview_payload, fileitems: admission.create_fileitems, preview: false, reorganize: false });
    }
    notice.value = 'MoviePilot 已接收逐项重建。现在会重新读取当前状态；只有实际结果等于预览，问题才会关闭。';
    preview.value = null; selected.value = null; await buildMap(true);
  } catch (error) { fail(error, '官方没有完成全部重建；插件没有直接删除原始下载。请重新读取当前状态。'); }
}
async function probeAi() { try { const result = await post('plugin/MediaGovernor/ai_probe', {}); aiAvailable.value = Boolean(result.available); notice.value = aiAvailable.value ? '智能助手可用：只会复核规则无法确认的异常单元。' : '智能助手未返回可用状态。'; } catch (error) { aiAvailable.value = false; fail(error, '智能助手不可用，仍可建立地图和检查规则问题。'); } }
onMounted(status);
onUnmounted(() => { if (clock) clearInterval(clock); requestBudget.cancel('页面已关闭'); });

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("main", _hoisted_1, [
    _createElementVNode("section", _hoisted_2, [
      _cache[3] || (_cache[3] = _createElementVNode("div", null, [
        _createElementVNode("p", { class: "eyebrow" }, "MediaGovernor 4.5.0"),
        _createElementVNode("h1", null, "找到问题，再安全修好"),
        _createElementVNode("p", null, "当前文件和硬链接决定问题；历史只负责关联，修复目标按作品类型选择唯一媒体库。")
      ], -1)),
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("button", {
          class: "secondary",
          disabled: running.value,
          onClick: probeAi
        }, "检查智能助手", 8, _hoisted_4),
        (state.value.ready)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              class: "secondary",
              disabled: running.value,
              onClick: _cache[0] || (_cache[0] = $event => (buildMap(true)))
            }, "完整重建地图", 8, _hoisted_5))
          : _createCommentVNode("", true),
        _createElementVNode("button", {
          class: "primary",
          disabled: running.value,
          onClick: _cache[1] || (_cache[1] = $event => (buildMap(state.value.ready ? false : true)))
        }, _toDisplayString(state.value.ready ? '检查变动' : '开始首次检查'), 9, _hoisted_6)
      ])
    ]),
    _createElementVNode("section", _hoisted_7, [
      _createElementVNode("span", null, [
        _createElementVNode("b", null, _toDisplayString(provenCount.value), 1),
        _cache[4] || (_cache[4] = _createTextVNode("真实问题", -1))
      ]),
      _createElementVNode("span", null, [
        _createElementVNode("b", null, _toDisplayString(pendingCards.value.length), 1),
        _cache[5] || (_cache[5] = _createTextVNode("等待确认作品", -1))
      ]),
      _createElementVNode("span", null, [
        _createElementVNode("b", null, _toDisplayString(uncoveredCards.value.length), 1),
        _cache[6] || (_cache[6] = _createTextVNode("未完成覆盖", -1))
      ]),
      _createElementVNode("span", null, [
        _createElementVNode("b", null, _toDisplayString(units.value.length || state.value.download_units), 1),
        _cache[7] || (_cache[7] = _createTextVNode("作品单元", -1))
      ])
    ]),
    (running.value || progress.value.total)
      ? (_openBlock(), _createElementBlock("section", _hoisted_8, [
          _createElementVNode("div", null, [
            _createElementVNode("b", null, _toDisplayString(phase.value), 1),
            (running.value)
              ? (_openBlock(), _createElementBlock("button", {
                  key: 0,
                  class: "link",
                  onClick: stop
                }, "停止"))
              : _createCommentVNode("", true)
          ]),
          _createElementVNode("p", null, _toDisplayString(progress.value.current), 1),
          _createElementVNode("i", null, [
            _createElementVNode("em", {
              style: _normalizeStyle({ width: `${percent.value}%` })
            }, null, 4)
          ]),
          _createElementVNode("small", null, _toDisplayString(progress.value.done) + "/" + _toDisplayString(progress.value.total) + " · " + _toDisplayString(elapsedLabel.value), 1)
        ]))
      : _createCommentVNode("", true),
    (notice.value)
      ? (_openBlock(), _createElementBlock("p", _hoisted_9, _toDisplayString(notice.value), 1))
      : _createCommentVNode("", true),
    _createElementVNode("section", _hoisted_10, [
      _cache[9] || (_cache[9] = _createElementVNode("header", null, [
        _createElementVNode("div", null, [
          _createElementVNode("h2", null, "已确认的真实问题"),
          _createElementVNode("p", null, "这些项目已由当前硬链接、作品身份和分类/季集规则证明；点开后再生成当次修复预览。")
        ])
      ], -1)),
      (!cards.value.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_11, _toDisplayString(running.value ? '正在核对，还没有形成结论。' : state.value.ready ? '当前没有已经证明的真实问题。' : '首次使用请先开始检查。'), 1))
        : _createCommentVNode("", true),
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(cards.value, (card) => {
        return (_openBlock(), _createElementBlock("article", {
          key: `${card.unit_id}-${card.kind}`,
          class: "card"
        }, [
          _createElementVNode("div", null, [
            _createElementVNode("span", _hoisted_12, _toDisplayString(_unref(findingLabel)(card.kind)), 1),
            _createElementVNode("h3", null, _toDisplayString(titleFor(card)), 1),
            _createElementVNode("p", null, _toDisplayString(card.reason), 1),
            _cache[8] || (_cache[8] = _createElementVNode("small", null, "点开可查看当前结果、官方应有结果和安全修复条件。", -1))
          ]),
          _createElementVNode("button", {
            class: "primary",
            disabled: running.value,
            onClick: $event => (recognize(card))
          }, "查看对比与修复", 8, _hoisted_13)
        ]))
      }), 128))
    ]),
    (pendingCards.value.length)
      ? (_openBlock(), _createElementBlock("section", _hoisted_14, [
          _cache[11] || (_cache[11] = _createElementVNode("header", null, [
            _createElementVNode("div", null, [
              _createElementVNode("h2", null, "等待确认作品"),
              _createElementVNode("p", null, "这些不是已判定的问题。可以查看整包候选，选对作品后生成官方预览。")
            ])
          ], -1)),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(pendingCards.value, (card) => {
            return (_openBlock(), _createElementBlock("article", {
              key: `${card.unit_id}-${card.kind}`,
              class: "card"
            }, [
              _createElementVNode("div", null, [
                _cache[10] || (_cache[10] = _createElementVNode("span", { class: "kind" }, "等待确认", -1)),
                _createElementVNode("h3", null, _toDisplayString(titleFor(card)), 1),
                _createElementVNode("p", null, _toDisplayString(card.reason), 1)
              ]),
              _createElementVNode("button", {
                class: "secondary",
                disabled: running.value,
                onClick: $event => (recognize(card))
              }, "选择作品并预览", 8, _hoisted_15)
            ]))
          }), 128))
        ]))
      : _createCommentVNode("", true),
    (uncoveredCards.value.length)
      ? (_openBlock(), _createElementBlock("section", _hoisted_16, [
          _cache[13] || (_cache[13] = _createElementVNode("header", null, [
            _createElementVNode("div", null, [
              _createElementVNode("h2", null, "没有检查完整"),
              _createElementVNode("p", null, "这些项目不会被当成正常或问题；原因解决后需要重新检查。")
            ])
          ], -1)),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(uncoveredCards.value, (card) => {
            return (_openBlock(), _createElementBlock("article", {
              key: `${card.unit_id}-${card.kind}`,
              class: "card"
            }, [
              _createElementVNode("div", null, [
                _cache[12] || (_cache[12] = _createElementVNode("span", { class: "kind" }, "未完成", -1)),
                _createElementVNode("h3", null, _toDisplayString(titleFor(card)), 1),
                _createElementVNode("p", null, _toDisplayString(card.reason), 1)
              ])
            ]))
          }), 128))
        ]))
      : _createCommentVNode("", true),
    (selected.value)
      ? (_openBlock(), _createElementBlock("div", _hoisted_17, [
          _createElementVNode("section", _hoisted_18, [
            _createElementVNode("button", {
              class: "close",
              onClick: _cache[2] || (_cache[2] = $event => {selected.value = null; preview.value = null;})
            }, "×"),
            _cache[17] || (_cache[17] = _createElementVNode("p", { class: "eyebrow" }, "作品证据与官方预览", -1)),
            _createElementVNode("h2", null, _toDisplayString(titleFor(selected.value.card)), 1),
            _createElementVNode("p", null, _toDisplayString(selected.value.card.reason), 1),
            _createElementVNode("div", _hoisted_19, [
              _createElementVNode("b", null, "文件证据：" + _toDisplayString(selected.value.unit.complete ? '完整读取' : '未完整读取'), 1),
              _createElementVNode("span", null, _toDisplayString(selected.value.unit.summary?.video_count || 0) + " 个视频文件 · " + _toDisplayString(selected.value.unit.boundary_reason), 1)
            ]),
            (selected.value.candidates.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_20, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selected.value.candidates, (candidate) => {
                    return (_openBlock(), _createElementBlock("button", {
                      key: _unref(identityKey)(candidate),
                      class: _normalizeClass(['candidate-choice', { active: _unref(identityKey)(candidate) === _unref(identityKey)(selected.value.candidate) }]),
                      onClick: $event => (selectCandidate(candidate))
                    }, [
                      _createElementVNode("b", null, _toDisplayString(candidate.title || candidate.original_title), 1),
                      _createElementVNode("span", null, _toDisplayString(candidate.year || '年份未知') + " · " + _toDisplayString(candidate.media_type) + " · " + _toDisplayString(candidate.media_source) + " / " + _toDisplayString(candidate.media_id), 1)
                    ], 10, _hoisted_21))
                  }), 128))
                ]))
              : (selected.value.candidate)
                ? (_openBlock(), _createElementBlock("div", _hoisted_22, [
                    _createElementVNode("b", null, _toDisplayString(selected.value.candidate.title || selected.value.candidate.original_title), 1),
                    _createElementVNode("span", null, _toDisplayString(selected.value.candidate.year) + " · " + _toDisplayString(selected.value.candidate.media_type) + " · " + _toDisplayString(selected.value.candidate.media_source) + " / " + _toDisplayString(selected.value.candidate.media_id), 1)
                  ]))
                : _createCommentVNode("", true),
            (selected.value.error)
              ? (_openBlock(), _createElementBlock("p", _hoisted_23, _toDisplayString(selected.value.error), 1))
              : _createCommentVNode("", true),
            _createElementVNode("button", {
              class: "primary",
              disabled: !selected.value.candidate || Boolean(selected.value.error),
              onClick: makePreview
            }, _toDisplayString(preview.value ? '重新生成官方逐文件预览' : '生成官方逐文件预览'), 9, _hoisted_24),
            (preview.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_25, [
                  _cache[15] || (_cache[15] = _createElementVNode("h3", null, "整理前后对比", -1)),
                  _cache[16] || (_cache[16] = _createElementVNode("p", null, "每一行都是同一个原文件：中间是现在的硬链接，右侧是 MoviePilot 官方预览的新位置。", -1)),
                  _createElementVNode("div", _hoisted_26, [
                    _cache[14] || (_cache[14] = _createElementVNode("div", { class: "compare-head" }, [
                      _createElementVNode("b", null, "原文件"),
                      _createElementVNode("b", null, "当前硬链接"),
                      _createElementVNode("b", null, "修复后")
                    ], -1)),
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(previewRows(preview.value), (row) => {
                      return (_openBlock(), _createElementBlock("div", {
                        key: `${row.source}-${row.expected}`,
                        class: "compare-row"
                      }, [
                        _createElementVNode("span", null, _toDisplayString(row.source), 1),
                        _createElementVNode("span", null, _toDisplayString(row.current), 1),
                        _createElementVNode("span", null, [
                          _createTextVNode(_toDisplayString(row.expected), 1),
                          _createElementVNode("small", null, _toDisplayString(row.episode), 1)
                        ])
                      ]))
                    }), 128))
                  ]),
                  _createElementVNode("p", _hoisted_27, _toDisplayString(selected.value.admission?.reason), 1),
                  _createElementVNode("button", {
                    class: "danger",
                    disabled: !selected.value.admission?.allowed,
                    onClick: repair
                  }, "确认清理旧硬链接并重建", 8, _hoisted_28)
                ]))
              : _createCommentVNode("", true)
          ])
        ]))
      : _createCommentVNode("", true)
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-bbee604f"]]);

export { AppPage as default };
