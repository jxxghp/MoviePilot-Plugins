import { cleanTitle, normaliseMediaSource } from './governance.js'

const text = value => String(value || '').trim()
const mediaKind = value => /tv|series|电视剧|剧集|动漫|动画|综艺|纪录片/i.test(text(value)) ? 'tv' : /movie|film|电影/i.test(text(value)) ? 'movie' : 'unknown'

export function identityFromRaw (raw = {}) {
  const value = raw?.media_info || raw?.mediaInfo || raw?.media || raw || {}
  const title = text(value.title || value.name || value.media_name).slice(0, 120)
  const genreValues = value.genres || value.genre_names || value.genreNames || value.genre || []
  const genres = (Array.isArray(genreValues) ? genreValues : [genreValues]).map(item => text(item?.name || item)).filter(Boolean).slice(0, 20)
  const genreIds = (Array.isArray(value.genre_ids) ? value.genre_ids : []).map(Number).filter(Number.isFinite).slice(0, 20)
  const category = text(value.category || value.media_category || value.type_name || value.type)
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

export const identityKey = value => value?.media_source && value?.media_id ? `${value.media_source}:${value.media_id}` : ''

const comparableNames = value => [value?.title, value?.original_title].map(cleanTitle).filter(Boolean)

export function sameWork (left, right) {
  const leftNames = comparableNames(left); const rightNames = comparableNames(right)
  const titleMatches = leftNames.some(a => rightNames.some(b => a === b || (Math.min(a.length, b.length) >= 5 && (a.includes(b) || b.includes(a)))))
  const yearMatches = !left?.year || !right?.year || String(left.year) === String(right.year)
  const typeMatches = !left?.media_type || !right?.media_type || left.media_type === 'unknown' || right.media_type === 'unknown' || left.media_type === right.media_type
  return Boolean(titleMatches && yearMatches && typeMatches)
}

export function sameIdentity (left, right) {
  const a = identityKey(left); const b = identityKey(right)
  return Boolean(a && b && a === b)
}

export function chooseGroundedCandidate (hint = {}, rawCandidates = []) {
  const candidates = rawCandidates.map(identityFromRaw).filter(item => identityKey(item))
  const wanted = cleanTitle(hint.title || hint.original_title)
  const scored = candidates.map(candidate => {
    const names = [candidate.title, candidate.original_title].map(cleanTitle).filter(Boolean)
    const titleScore = wanted && names.some(name => name === wanted) ? 4 : wanted && names.some(name => name.includes(wanted) || wanted.includes(name)) ? 2 : 0
    const yearConflict = Boolean(hint.year && candidate.year && String(hint.year) !== String(candidate.year))
    const typeConflict = Boolean(hint.media_type && hint.media_type !== 'unknown' && candidate.media_type !== 'unknown' && hint.media_type !== candidate.media_type)
    const yearScore = !hint.year || !candidate.year ? 0 : 2
    const typeScore = !hint.media_type || hint.media_type === 'unknown' || candidate.media_type === 'unknown' ? 0 : 1
    return { candidate, score: titleScore + yearScore + typeScore, conflict: yearConflict || typeConflict }
  }).filter(item => !item.conflict && item.score >= 3).sort((a, b) => b.score - a.score)
  const best = scored[0]
  const unique = best && best.score >= 5 && !scored.slice(1).some(item => item.score >= best.score - 1 && !sameIdentity(item.candidate, best.candidate))
  return { selected: unique ? { ...best.candidate, evidence_verified: true } : null, candidates: scored.slice(0, 6).map(item => item.candidate) }
}

export function reconcileIdentities (nativeIdentity, aiGrounded, evidenceHint = null, nativeConflict = false) {
  const native = identityKey(nativeIdentity) ? nativeIdentity : null
  const ai = identityKey(aiGrounded?.selected) ? aiGrounded.selected : null
  const candidates = [...new Map([native, ...(aiGrounded?.candidates || [])].filter(Boolean).map(item => [identityKey(item), item])).values()]
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
