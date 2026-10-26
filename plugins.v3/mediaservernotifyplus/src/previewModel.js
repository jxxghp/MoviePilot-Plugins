export const previewActionIcons = {
  library_added: '📂', library_deleted: '🗑️', playback_started: '▶️',
  playback_stopped: '⏹️', playback_paused: '⏸️', playback_resumed: '▶️',
  auth_success: '🔐', auth_failed: '⚠️', rated: '⭐', test: '🧪',
}

export const previewFieldMeta = {
  season_episode: { label: '季集', icon: '📺' },
  user: { label: '用户', icon: '👤' },
  device: { label: '设备', icon: '📱' },
  progress: { label: '播放进度', icon: '⏱️' },
  server: { label: '服务器', icon: '🖥️' },
  library: { label: '媒体库分类', icon: '🗂️' },
  rating: { label: '评分', icon: '⭐' },
  actors: { label: '演员', icon: '🎬' },
  region: { label: '地区', icon: '🏳️' },
  ip: { label: 'IP', icon: '🌐' },
  time: { label: '时间', icon: '🕐' },
  overview: { label: '剧情简介', icon: '📖', block: true },
}

const mediaExample = {
  name: '光阴之外', year: 2025, episode: 'S01E22 - 老爷子，我要筑基了',
  library: '动漫剧集', rating: '9.4/10', region: '中国大陆',
  actors: '陈张太康、凌振赫、常文涛、万舒心、刘思岑',
  overview: '许青为隐藏异质秘密，独自前往南凰州雨林开辟洞府筑基，布下多重法阵严防外人窥探。',
}

export function createPreviewSample() {
  const media = mediaExample
  return {
    mediaName: `${media.name} (${media.year})`,
    fileCount: 1,
    fields: {
      season_episode: media.episode,
      user: '预览',
      device: 'Apple_TV · VidHub',
      progress: '23.6%',
      server: 'cz',
      library: media.library,
      rating: media.rating,
      actors: media.actors,
      region: media.region,
      ip: '66.66.66.66 本地局域网',
      time: '2026-09-23 15:06:26',
      overview: media.overview,
    },
  }
}

export function buildPreviewRows(fieldRows, sample, selectedServer = '') {
  if (!sample) return []
  return fieldRows.filter(row => row.enabled).map(row => {
    const meta = previewFieldMeta[row.key]
    const value = row.key === 'server' && selectedServer ? selectedServer : sample.fields[row.key]
    return {
      key: row.key,
      icon: meta?.icon || '',
      label: String(row.label || meta?.label || row.key).trim(),
      value: String(value || '').trim(),
      block: Boolean(meta?.block),
    }
  }).filter(row => row.value)
}
