<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Chart from 'chart.js/auto'
import MetricCard from './MetricCard.vue'
import SiteAvatar from './SiteAvatar.vue'
import { formatBytes, formatNumber, openNativePicker, siteColors, unwrapResponse, withQuery } from '../utils'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'PTDataStatistics' },
  initialTab: { type: String, default: 'overview' },
  initialSettings: { type: Object, default: () => ({}) },
  hostManagedConfig: { type: Boolean, default: false },
  showClose: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'action', 'save'])
const hostToast = inject('moviepilot:toast', null)
const activeTab = ref(props.initialTab)
const loading = ref(false)
const saving = ref(false)
const historyLoading = ref(false)
const distributionLoading = ref(false)
const error = ref('')
const rulesFileInput = ref(null)
const rulesUploadName = ref('')
const wealthyPickerOpen = ref(false)
const wealthySiteSearch = ref('')
const overview = ref({
  server_date: '', generated_at: '', first_history_day: '', last_history_day: '',
  summary: {}, sites: [], today_sites: [], history_sites: [],
  twelve: { joined: 0, total: 12, percent: 0, items: [] },
  retirement: { total: 0, retired: 0, wealthy_retired: 0, upgrading: 0, rule_missing: 0, sites: [] },
})
const distribution = ref({ month: '', day: '', monthly: [], daily: [] })
const distributionFilters = ref({ month: '', day: '' })
const distributionMetric = ref('upload')
const ruleAnchorSites = ref([])
const siteSortKey = ref('site_priority')
const siteSortOptions = [
  { title: '站点优先级', value: 'site_priority' },
  { title: '加入时间', value: 'join_at' },
  { title: '累计上传', value: 'upload' },
  { title: '累计下载', value: 'download' },
  { title: '魔力', value: 'bonus' },
  { title: '做种数', value: 'seeding' },
  { title: '做种体积', value: 'seeding_size' },
]
const retirementSortKey = ref('site_priority')
const retirementSortOptions = [
  { title: '站点优先级', value: 'site_priority' },
  { title: '加入时间', value: 'join_at' },
  { title: '养老进度', value: 'retirement_progress' },
  { title: '累计上传', value: 'upload' },
  { title: '累计下载', value: 'download' },
  { title: '站点名称', value: 'site_name' },
]
let distributionRequestSequence = 0
let historyRequestSequence = 0
let hourlyRequestSequence = 0
const ptdUuidVisible = ref(false)
const ptdPasswordVisible = ref(false)
const settingsDraft = ref({
  enabled: false, retention_days: 365,
  notification_enabled: false, notification_cron: '0 9 * * *', notification_modes: ['today'],
  ptd_cookiecloud_enabled: false, ptd_cookiecloud_uuid: '',
  ptd_cookiecloud_password: '', ptd_cookiecloud_headers: '',
  ptd_site_mappings: '',
  wealthy_retirement_sites: [],
  custom_retirement_rules: [],
})
const history = ref({ start_day: '', end_day: '', count: 0, records: [] })
const historyFilters = ref({ startDay: '', endDay: '', siteIds: [], includeArchived: true })
const historyScope = ref('day')
const selectedHistoryPeriodKey = ref('')
const selectedHistorySiteId = ref(null)
const hourlyTraffic = ref({ day: '', site_id: null, site_name: '全部站点', baseline_valid: false, sample_count: 0, points: [] })
const hourlyLoading = ref(false)
const historyChartCanvas = ref(null)
let historyChart = null
const selectedRetirementSiteKey = ref('')
const selectedRouteLevelName = ref('')
const springUpgradeTaskIndex = ref(0)

const pluginBase = computed(() => `plugin/${props.pluginId || 'PTDataStatistics'}`)
const ptdReceiverUrl = computed(() => {
  if (typeof window === 'undefined') return `/api/v1/${pluginBase.value}/cookiecloud`
  const url = new URL(`/api/v1/${pluginBase.value}/cookiecloud`, window.location.href)
  url.hostname = 'localhost'
  return url.toString()
})
const currentSites = computed(() => overview.value.sites || [])
function compareSiteNames(left, right) {
  return String(left?.site_name || '').localeCompare(String(right?.site_name || ''), 'zh-CN')
}
function sitePriority(site) {
  const raw = site?.site_priority
  const value = Number(raw)
  return raw !== null && raw !== undefined && Number.isFinite(value) ? value : Number.MAX_SAFE_INTEGER
}
function compareSites(left, right, key) {
  if (key === 'site_priority') return sitePriority(left) - sitePriority(right) || compareSiteNames(left, right)
  if (key === 'site_name') return compareSiteNames(left, right)
  if (key === 'join_at') {
    const leftDate = String(left?.join_at || '').slice(0, 10)
    const rightDate = String(right?.join_at || '').slice(0, 10)
    if (!leftDate) return rightDate ? 1 : compareSiteNames(left, right)
    if (!rightDate) return -1
    return leftDate.localeCompare(rightDate) || compareSiteNames(left, right)
  }
  const difference = Number(right?.[key] ?? -1) - Number(left?.[key] ?? -1)
  return difference || compareSiteNames(left, right)
}
const sortedCurrentSites = computed(() => [...currentSites.value].sort(
  (left, right) => compareSites(left, right, siteSortKey.value),
))
const historySites = computed(() => overview.value.history_sites?.length ? overview.value.history_sites : currentSites.value)
const todaySites = computed(() => overview.value.today_sites || [])
const summary = computed(() => overview.value.summary || {})
const twelveItems = computed(() => overview.value.twelve?.items || [])
const twelveJoinedCount = computed(() => Number(overview.value.twelve?.joined || 0))
const twelveTotalCount = computed(() => Number(overview.value.twelve?.total || 12))
const twelveRemainingCount = computed(() => Math.max(twelveTotalCount.value - twelveJoinedCount.value, 0))
const twelveTrackPercent = computed(() => {
  if (twelveTotalCount.value <= 1 || twelveJoinedCount.value <= 1) return 0
  return Math.min(100, (twelveJoinedCount.value - 1) * 100 / (twelveTotalCount.value - 1))
})
const retirement = computed(() => overview.value.retirement || { sites: [] })
const wealthyRetiredCount = computed(() => Number(
  retirement.value.wealthy_retired
    ?? (retirement.value.sites || []).filter(site => site.status === 'wealthy_retired').length
))
const ordinaryRetiredCount = computed(() => Number(retirement.value.retired || 0))
const sortedRetirementSites = computed(() => [...(retirement.value.sites || [])].sort((left, right) => {
  if (retirementSortKey.value === 'retirement_progress') {
    return nextLevelOverallProgress(right) - nextLevelOverallProgress(left) || compareSiteNames(left, right)
  }
  return compareSites(left, right, retirementSortKey.value)
}))
const customRuleSites = computed(() => (
  settingsDraft.value.custom_retirement_rules || []
).map(rule => rule.site).filter(Boolean))
function wealthyRetirementSiteKey(site) {
  return String(site?.site_id || site?.site_name || '').trim().toLocaleLowerCase()
}
const wealthyRetirementSiteOptions = computed(() => sortedCurrentSites.value.filter(wealthyRetirementSiteKey))
function isWealthyRetirementSiteSelected(site) {
  const key = wealthyRetirementSiteKey(site)
  return (settingsDraft.value.wealthy_retirement_sites || []).includes(key)
}
function toggleWealthyRetirementSite(site) {
  const key = wealthyRetirementSiteKey(site)
  if (!key) return
  const selected = new Set(settingsDraft.value.wealthy_retirement_sites || [])
  if (selected.has(key)) selected.delete(key)
  else selected.add(key)
  settingsDraft.value.wealthy_retirement_sites = [...selected]
}
const selectedWealthyRetirementSites = computed(() => wealthyRetirementSiteOptions.value.filter(isWealthyRetirementSiteSelected))
const filteredWealthyRetirementSiteOptions = computed(() => {
  const query = normalizedSiteName(wealthySiteSearch.value)
  return wealthyRetirementSiteOptions.value
    .filter(site => !query || [site.site_name, site.domain, site.site_id].some(value => normalizedSiteName(value).includes(query)))
    .sort((left, right) => (
      Number(isWealthyRetirementSiteSelected(right)) - Number(isWealthyRetirementSiteSelected(left))
      || compareSiteNames(left, right)
    ))
})
function clearWealthyRetirementSites() {
  settingsDraft.value.wealthy_retirement_sites = []
}
const selectedRetirementSite = computed(() => {
  const sites = sortedRetirementSites.value
  return sites.find(site => retirementSiteKey(site) === selectedRetirementSiteKey.value) || sites[0] || null
})
const historyGroups = computed(() => {
  const grouped = new Map()
  for (const item of history.value.records || []) {
    const day = item.updated_day || '未知日期'
    const group = grouped.get(day) || {
      day, records: [], siteCount: 0, validCount: 0, upload: 0, download: 0,
      totalUpload: 0, totalDownload: 0, bonus: 0, seeding: 0, seedingSize: 0,
    }
    group.records.push(item)
    group.siteCount += 1
    group.totalUpload += Number(item.upload || 0)
    group.totalDownload += Number(item.download || 0)
    group.bonus += Number(item.bonus || 0)
    group.seeding += Number(item.seeding || 0)
    group.seedingSize += Number(item.seeding_size || 0)
    if (item.baseline_valid) {
      group.validCount += 1
      group.upload += Number(item.daily_upload || 0)
      group.download += Number(item.daily_download || 0)
    }
    grouped.set(day, group)
  }
  return [...grouped.values()].sort((a, b) => b.day.localeCompare(a.day))
})
function summarizePeriod(key, label, startDay, endDay, records) {
  const valid = records.filter(item => item.baseline_valid)
  return {
    key, label, startDay, endDay, records,
    siteCount: new Set(records.map(item => item.site_id || item.site_name)).size,
    validCount: valid.length,
    upload: valid.reduce((sum, item) => sum + Number(item.daily_upload || 0), 0),
    download: valid.reduce((sum, item) => sum + Number(item.daily_download || 0), 0),
  }
}
function weekBounds(day) {
  const value = new Date(`${day}T00:00:00Z`)
  const offset = (value.getUTCDay() + 6) % 7
  const start = new Date(value)
  start.setUTCDate(value.getUTCDate() - offset)
  const end = new Date(start)
  end.setUTCDate(start.getUTCDate() + 6)
  return [start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)]
}
const historyPeriods = computed(() => {
  if (historyScope.value === 'day') {
    return historyGroups.value.map(group => summarizePeriod(
      `day:${group.day}`, group.day, group.day, group.day, group.records,
    ))
  }
  const grouped = new Map()
  for (const item of history.value.records || []) {
    const day = item.updated_day
    if (!day) continue
    let key
    let label
    let startDay
    let endDay
    if (historyScope.value === 'week') {
      ;[startDay, endDay] = weekBounds(day)
      key = `week:${startDay}`
      label = `${startDay.slice(5)} — ${endDay.slice(5)}`
    } else {
      startDay = `${day.slice(0, 7)}-01`
      const next = new Date(`${startDay}T00:00:00Z`)
      next.setUTCMonth(next.getUTCMonth() + 1)
      next.setUTCDate(0)
      endDay = next.toISOString().slice(0, 10)
      key = `month:${day.slice(0, 7)}`
      label = `${day.slice(0, 7)}`
    }
    const bucket = grouped.get(key) || { key, label, startDay, endDay, records: [] }
    bucket.records.push(item)
    grouped.set(key, bucket)
  }
  return [...grouped.values()]
    .map(item => summarizePeriod(item.key, item.label, item.startDay, item.endDay, item.records))
    .sort((a, b) => b.startDay.localeCompare(a.startDay))
})
const selectedHistoryPeriod = computed(() => (
  historyPeriods.value.find(period => period.key === selectedHistoryPeriodKey.value) || historyPeriods.value[0] || null
))
const selectedPeriodSites = computed(() => {
  const grouped = new Map()
  for (const item of selectedHistoryPeriod.value?.records || []) {
    const key = String(item.site_id || item.site_name)
    const current = grouped.get(key) || {
      ...item, period_upload: 0, period_download: 0, valid_count: 0,
    }
    if (String(item.updated_day || '') >= String(current.updated_day || '')) Object.assign(current, item)
    if (item.baseline_valid) {
      current.period_upload += Number(item.daily_upload || 0)
      current.period_download += Number(item.daily_download || 0)
      current.valid_count += 1
    }
    grouped.set(key, current)
  }
  return [...grouped.values()].sort((a, b) => (
    b.period_upload + b.period_download - a.period_upload - a.period_download
  ) || String(a.site_name).localeCompare(String(b.site_name), 'zh-CN'))
})
const selectedHistorySite = computed(() => (
  selectedPeriodSites.value.find(item => Number(item.site_id) === Number(selectedHistorySiteId.value)) || null
))
const selectedHistoryRecords = computed(() => {
  if (!selectedHistoryPeriod.value || !selectedHistorySiteId.value) return []
  return [...(selectedHistoryPeriod.value.records || [])]
    .filter(item => Number(item.site_id) === Number(selectedHistorySiteId.value))
    .sort((left, right) => String(right.updated_day || '').localeCompare(String(left.updated_day || '')))
})
const historyChartSeries = computed(() => {
  if (!selectedHistoryPeriod.value) return []
  if (historyScope.value === 'day') {
    return (hourlyTraffic.value.points || []).map(point => ({
      label: point.hour, upload: Number(point.upload || 0), download: Number(point.download || 0),
    }))
  }
  const grouped = new Map()
  for (const item of selectedHistoryPeriod.value.records || []) {
    if (selectedHistorySiteId.value && Number(item.site_id) !== Number(selectedHistorySiteId.value)) continue
    if (!item.baseline_valid) continue
    const value = grouped.get(item.updated_day) || { label: item.updated_day.slice(5), upload: 0, download: 0 }
    value.upload += Number(item.daily_upload || 0)
    value.download += Number(item.daily_download || 0)
    grouped.set(item.updated_day, value)
  }
  return [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([, value]) => value)
})

function notify(message, type = 'success') {
  const method = ['success', 'info', 'warning', 'error'].includes(type) ? type : 'success'
  if (typeof hostToast?.[method] === 'function') hostToast[method](message)
  else if (method === 'error') error.value = message
}
function field(value, digits = 2) {
  return value === '' || value === null || value === undefined ? '站点未提供' : formatNumber(value, digits)
}
function bonusValue(value) {
  return value === '' || value === null || value === undefined ? '暂无魔力数据' : formatNumber(value, 2)
}
function estimatedBonusHourly(value) {
  return value === null || value === undefined
    ? '暂不可估算'
    : `${formatNumber(value, 2)} / 小时`
}
function selectHistoryPeriod(period) {
  selectedHistoryPeriodKey.value = period.key
  selectedHistorySiteId.value = null
}
function selectHistorySite(item) {
  const value = item?.site_id ? Number(item.site_id) : null
  if (value === null) {
    selectedHistorySiteId.value = null
    return
  }
  selectedHistorySiteId.value = Number(selectedHistorySiteId.value) === value ? null : value
}
async function loadHourlyTraffic() {
  const requestSequence = ++hourlyRequestSequence
  const period = selectedHistoryPeriod.value
  const siteId = selectedHistorySiteId.value
  if (historyScope.value !== 'day' || !period) {
    hourlyLoading.value = false
    return
  }
  hourlyLoading.value = true
  try {
    const response = await props.api.get(withQuery(`${pluginBase.value}/history/hourly`, {
      day: period.startDay,
      site_id: siteId || '',
    }), { feedback: 'silent' })
    if (requestSequence === hourlyRequestSequence) hourlyTraffic.value = unwrapResponse(response) || hourlyTraffic.value
  } catch (err) {
    if (requestSequence !== hourlyRequestSequence) return
    notify(err?.message || '加载小时流量失败', 'error')
    hourlyTraffic.value = { day: period.startDay, site_id: siteId, site_name: selectedHistorySite.value?.site_name || '全部站点', baseline_valid: false, sample_count: 0, points: [] }
  } finally {
    if (requestSequence === hourlyRequestSequence) hourlyLoading.value = false
  }
}
function setHistoryChartCanvas(element) {
  if (element) historyChartCanvas.value = element
}
function renderHistoryChart() {
  if (historyChart) {
    historyChart.destroy()
    historyChart = null
  }
  if (!historyChartCanvas.value || !historyChartSeries.value.length) return
  const context = historyChartCanvas.value.getContext('2d')
  historyChart = new Chart(context, {
    type: 'line',
    data: {
      labels: historyChartSeries.value.map(item => item.label),
      datasets: [
        {
          label: '上传',
          data: historyChartSeries.value.map(item => item.upload),
          borderColor: '#74d83f',
          backgroundColor: 'rgba(116,216,63,.12)',
          pointBackgroundColor: '#74d83f',
          pointRadius: historyScope.value === 'day' ? 2 : 3,
          pointHoverRadius: 5,
          borderWidth: 2,
          tension: .34,
          fill: true,
        },
        {
          label: '下载',
          data: historyChartSeries.value.map(item => item.download),
          borderColor: '#ff5364',
          backgroundColor: 'rgba(255,83,100,.10)',
          pointBackgroundColor: '#ff5364',
          pointRadius: historyScope.value === 'day' ? 2 : 3,
          pointHoverRadius: 5,
          borderWidth: 2,
          tension: .34,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      animation: { duration: 220 },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: context => `${context.dataset.label}：${formatBytes(context.raw)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: 'rgba(210,218,238,.58)', maxRotation: 0, autoSkip: true, maxTicksLimit: historyScope.value === 'day' ? 12 : 16 },
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(210,218,238,.08)' },
          ticks: { color: 'rgba(210,218,238,.58)', callback: value => formatBytes(value) },
        },
      },
    },
  })
}
function stateMeta(state) {
  if (state === 'joined') return { label: '已加入', color: 'success', icon: 'mdi-check-circle' }
  if (state === 'waiting') return { label: '待数据', color: 'warning', icon: 'mdi-clock-outline' }
  return { label: '未加入', color: 'secondary', icon: 'mdi-lock-outline' }
}
function retirementMeta(status, site = null) {
  if (status === 'wealthy_retired') return { label: '富贵养老', color: 'warning', icon: 'mdi-crown' }
  if (status === 'retired') return { label: '已养老', color: 'success', icon: 'mdi-shield-check-outline' }
  if (status === 'upgrading' && site && !site.retirement_level && !site.next_level) return { label: '最高等级', color: 'primary', icon: 'mdi-medal-outline' }
  if (status === 'upgrading') return { label: '升级中', color: 'warning', icon: 'mdi-trending-up' }
  return { label: '规则缺失', color: 'secondary', icon: 'mdi-help-circle-outline' }
}
function retirementSiteKey(site) {
  return String(site?.site_id || site?.site_name || '')
}
function selectRetirementSite(site) {
  selectedRetirementSiteKey.value = retirementSiteKey(site)
}
function setDefaultRanges() {
  const end = overview.value.last_history_day || overview.value.server_date
  if (!end) return
  if (!historyFilters.value.endDay) {
    const startDate = new Date(`${end}T00:00:00Z`)
    startDate.setUTCDate(startDate.getUTCDate() - 29)
    historyFilters.value.endDay = end
    historyFilters.value.startDay = startDate.toISOString().slice(0, 10)
    historyFilters.value.siteIds = []
  }
  if (!distributionFilters.value.day) distributionFilters.value.day = end
  if (!distributionFilters.value.month) distributionFilters.value.month = end.slice(0, 7)
}
async function loadDistribution() {
  const filters = { ...distributionFilters.value }
  if (!filters.month || !filters.day) return
  const requestSequence = ++distributionRequestSequence
  distributionLoading.value = true
  try {
    const path = withQuery(`${pluginBase.value}/distribution`, filters)
    const response = unwrapResponse(await props.api.get(path, { feedback: 'silent' }))
    if (requestSequence === distributionRequestSequence && response) distribution.value = response
  } catch (err) {
    if (requestSequence === distributionRequestSequence) notify(err?.message || '加载流量分布失败', 'error')
  } finally {
    if (requestSequence === distributionRequestSequence) distributionLoading.value = false
  }
}
function updateDistributionFilter(key, value) {
  distributionFilters.value = { ...distributionFilters.value, [key]: value || '' }
  if (value) {
    loadDistribution()
  } else {
    distributionRequestSequence += 1
    distributionLoading.value = false
  }
}
async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [overviewData, settingsData] = await Promise.all([
      props.api.get(`${pluginBase.value}/overview`, { feedback: 'silent' }),
      props.api.get(`${pluginBase.value}/settings`, { feedback: 'silent' }),
    ])
    overview.value = unwrapResponse(overviewData) || overview.value
    const parsed = unwrapResponse(settingsData) || {}
    const hostSettings = props.hostManagedConfig && Object.keys(props.initialSettings || {}).length
      ? props.initialSettings
      : {}
    settingsDraft.value = JSON.parse(JSON.stringify({
      ...settingsDraft.value,
      ...(parsed.settings || {}),
      ...hostSettings,
    }))
    ptdUuidVisible.value = Boolean(settingsDraft.value.ptd_cookiecloud_uuid)
    ptdPasswordVisible.value = Boolean(settingsDraft.value.ptd_cookiecloud_password)
    ruleAnchorSites.value = parsed.rule_sites || []
    setDefaultRanges()
    await loadDistribution()
  } catch (err) {
    error.value = err?.message || '加载 PT 数据统计失败'
  } finally {
    loading.value = false
  }
}
async function loadHistory() {
  const requestSequence = ++historyRequestSequence
  historyLoading.value = true
  try {
    const path = withQuery(`${pluginBase.value}/history`, {
      start_day: historyFilters.value.startDay, end_day: historyFilters.value.endDay,
      site_ids: historyFilters.value.siteIds, include_archived: historyFilters.value.includeArchived, limit: 50000,
    })
    const response = await props.api.get(path, { feedback: 'silent' })
    if (requestSequence !== historyRequestSequence) return
    history.value = unwrapResponse(response) || history.value
    selectedHistoryPeriodKey.value = historyPeriods.value[0]?.key || ''
    selectedHistorySiteId.value = null
  } catch (err) {
    if (requestSequence === historyRequestSequence) notify(err?.message || '查询历史数据失败', 'error')
  } finally {
    if (requestSequence === historyRequestSequence) historyLoading.value = false
  }
}
async function saveSettings() {
  if (settingsDraft.value.ptd_cookiecloud_enabled && !settingsDraft.value.ptd_cookiecloud_password) {
    notify('请点击随机按钮生成 CookieCloud 密码后再保存', 'warning')
    return
  }
  saving.value = true
  try {
    const payload = JSON.parse(JSON.stringify(settingsDraft.value))
    delete payload.sync_interval_minutes
    if (props.hostManagedConfig) {
      const data = unwrapResponse(await props.api.post(`${pluginBase.value}/settings`, payload)) || {}
      settingsDraft.value = JSON.parse(JSON.stringify(data.settings || payload))
      ruleAnchorSites.value = data.rule_sites || ruleAnchorSites.value
      notify('设置已保存')
      emit('save', payload)
      return
    }
    const data = unwrapResponse(await props.api.post(`${pluginBase.value}/settings`, payload)) || {}
    settingsDraft.value = JSON.parse(JSON.stringify(data.settings || settingsDraft.value))
    ruleAnchorSites.value = data.rule_sites || ruleAnchorSites.value
    notify('设置已保存')
    emit('action')
  } catch (err) {
    notify(err?.message || '保存设置失败', 'error')
  } finally {
    saving.value = false
  }
}
function randomPtdValue(length) {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  const bytes = new Uint8Array(length)
  globalThis.crypto.getRandomValues(bytes)
  return Array.from(bytes, value => alphabet[value % alphabet.length]).join('')
}
function randomizePtdUuid() {
  settingsDraft.value.ptd_cookiecloud_uuid = randomPtdValue(20)
  ptdUuidVisible.value = true
}
function randomizePtdPassword() {
  settingsDraft.value.ptd_cookiecloud_password = randomPtdValue(24)
  ptdPasswordVisible.value = true
}
function uploadedRuleList(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.rules)) return payload.rules
  if (Array.isArray(payload?.sites)) return payload.sites
  const container = payload?.rules && typeof payload.rules === 'object' ? payload.rules : payload
  if (!container || typeof container !== 'object') throw new Error('规则文件必须包含 rules 或 sites 数组')
  return Object.entries(container)
    .filter(([key]) => key !== 'version')
    .map(([site, rule]) => ({ site, ...(rule || {}) }))
}
function normalizeUploadedRules(payload) {
  const rules = uploadedRuleList(payload).map((rule, index) => {
    const site = String(rule?.site || rule?.name || '').trim()
    const retirementLevel = String(rule?.retirement_level || '').trim()
    const levels = Array.isArray(rule?.levels) ? rule.levels : []
    if (!site) throw new Error(`第 ${index + 1} 条规则缺少 site`)
    if (!retirementLevel) throw new Error(`${site} 缺少 retirement_level`)
    if (!levels.length) throw new Error(`${site} 缺少完整 levels 列表`)
    const normalizeLevels = (items, label) => {
      const levelNames = new Set()
      return items.map((level, levelIndex) => {
      const name = String(level?.name || '').trim()
      if (!name) throw new Error(`${site} 的${label}第 ${levelIndex + 1} 个等级缺少 name`)
      const aliases = Array.isArray(level.aliases) ? level.aliases.map(value => String(value).trim()).filter(Boolean) : []
      for (const identity of [name, ...aliases].map(normalizedSiteName)) {
        if (levelNames.has(identity)) throw new Error(`${site} 的等级名称或别名重复：${name}`)
        levelNames.add(identity)
      }
      return { ...level, name, aliases }
      })
    }
    const normalizedLevels = normalizeLevels(levels, '')
    const retirementFound = normalizedLevels.some(level => (
      [level.name, ...(level.aliases || [])].some(value => normalizedSiteName(value) === normalizedSiteName(retirementLevel))
    ))
    if (!retirementFound) throw new Error(`${site} 的保号等级不在 levels 中：${retirementLevel}`)
    return {
      site,
      aliases: Array.isArray(rule.aliases) ? rule.aliases.map(value => String(value).trim()).filter(Boolean) : [],
      domains: Array.isArray(rule.domains) ? rule.domains.map(value => String(value).trim()).filter(Boolean) : [],
      retirement_level: retirementLevel,
      levels: normalizedLevels,
      vip_levels: normalizeLevels(Array.isArray(rule.vip_levels) ? rule.vip_levels : [], ' VIP '),
    }
  })
  if (!rules.length) throw new Error('规则文件中没有可用站点')
  if (rules.length > 100) throw new Error('单个规则文件最多包含 100 个站点')
  return rules
}
function normalizedSiteName(value) {
  return String(value || '').trim().toLocaleLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '')
}
function alignRulesToMoviePilotSites(rules) {
  const moviePilotSites = wealthyRetirementSiteOptions.value.length
    ? wealthyRetirementSiteOptions.value
    : (ruleAnchorSites.value || []).map(name => ({ site_name: name }))
  if (!moviePilotSites.length) throw new Error('MoviePilot 当前没有可用于匹配的站点')
  return rules.map(rule => {
    const ruleIdentities = [rule.site, ...(rule.aliases || []), ...(rule.domains || [])]
      .map(normalizedSiteName).filter(Boolean)
    const matched = moviePilotSites.find(site => {
      const siteIdentities = [site.site_name, site.domain].map(normalizedSiteName).filter(Boolean)
      return siteIdentities.some(siteIdentity => ruleIdentities.some(ruleIdentity => (
        siteIdentity === ruleIdentity
        || (ruleIdentity.length >= 4 && (siteIdentity.includes(ruleIdentity) || ruleIdentity.includes(siteIdentity)))
      )))
    })
    if (!matched) return rule
    const matchedName = String(matched.site_name || rule.site).trim()
    const aliases = [...new Set([rule.site, ...(rule.aliases || [])].map(value => String(value).trim()).filter(value => value && value !== matchedName))]
    const domains = [...new Set((rule.domains || []).map(value => String(value || '').trim()).filter(Boolean))]
    return { ...rule, site: matchedName, aliases, domains }
  })
}
async function uploadRuleFile(event) {
  const file = event?.target?.files?.[0]
  if (!file) return
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error('规则文件不能超过 2 MB')
    const payload = JSON.parse(await file.text())
    const rules = alignRulesToMoviePilotSites(normalizeUploadedRules(payload))
    settingsDraft.value.custom_retirement_rules = rules
    rulesUploadName.value = file.name
    notify(`已载入 ${rules.length} 个站点规则；名称、域名和别名将在保存后参与匹配`)
  } catch (err) {
    notify(err instanceof SyntaxError ? '规则文件不是有效的 JSON' : err?.message || '读取规则文件失败', 'error')
  } finally {
    if (event?.target) event.target.value = ''
  }
}
function clearUploadedRules() {
  settingsDraft.value.custom_retirement_rules = []
  rulesUploadName.value = ''
  notify('已清空自定义规则，请保存设置后生效', 'warning')
}
async function downloadRuleTemplate() {
  try {
    const template = unwrapResponse(await props.api.get(`${pluginBase.value}/rules/template`, { feedback: 'silent' }))
    const url = URL.createObjectURL(new Blob([JSON.stringify(template, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'mteam-level-rules-template.json'
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    notify(err?.message || '下载规则模板失败', 'error')
  }
}
function distributionSegments(items) {
  const key = distributionMetric.value
  const total = (items || []).reduce((sum, item) => sum + Number(item[key] || 0), 0)
  return (items || []).filter(item => Number(item[key] || 0) > 0).map((item, index) => ({
    ...item, value: Number(item[key] || 0), percent: total ? Number(item[key] || 0) * 100 / total : 0,
    color: siteColors[index % siteColors.length],
  }))
}
function donutStyle(items) {
  const segments = distributionSegments(items)
  if (!segments.length) return { background: 'conic-gradient(rgba(var(--v-theme-on-surface), .1) 0 100%)' }
  let offset = 0
  const stops = segments.map(segment => {
    const start = offset
    offset += segment.percent
    return `${segment.color} ${start}% ${Math.min(offset, 100)}%`
  })
  return { background: `conic-gradient(${stops.join(', ')})` }
}
function nextLevelRule(site) {
  return (site.route || []).find(level => level.name === site.next_level) || null
}
function retirementRoute(site) {
  const route = site.route || []
  const userIndex = route.findIndex(level => String(level.name || '').replace(/[^a-z0-9]/gi, '').toLowerCase() === 'user')
  return userIndex >= 0 ? route.slice(userIndex) : route
}
function nextLevelOverallProgress(site) {
  if (site?.status === 'wealthy_retired') return 100
  const nextLevel = nextLevelRule(site)
  if (!nextLevel) return site?.status === 'retired' || !site?.retirement_level ? 100 : 0
  const taskIndex = springUpgradeTasks(site, nextLevel).length ? 0 : null
  return averageRequirementProgress(requirementRows(site, nextLevel, taskIndex))
}
function routeNodeStatus(site, level) {
  if (level.is_current) return '当前'
  if (level.name === site?.next_level) return '下一等级'
  if (level.is_retirement) return level.reached ? '已保号' : '保号目标'
  return level.reached ? '已达成' : '待达成'
}
function splitLevelName(level) {
  const name = String(level?.name || level || '').trim()
  const aliases = Array.isArray(level?.aliases) ? level.aliases.map(value => String(value || '').trim()).filter(Boolean) : []
  const combined = [name, ...aliases]
    .map(value => value.match(/^(.+?[\u3400-\u9fff])\s*(?:[（(]([A-Za-z][A-Za-z0-9 .&+/_-]*)[）)]|([A-Za-z][A-Za-z0-9 .&+/_-]*))$/))
    .find(Boolean)
  if (combined) return { local: combined[1].trim(), english: String(combined[2] || combined[3]).trim() }
  const hasChinese = value => /[\u3400-\u9fff]/.test(value)
  const hasEnglish = value => /[A-Za-z]/.test(value)
  const chinese = [name, ...aliases].find(hasChinese) || ''
  const english = [name, ...aliases].find(value => hasEnglish(value) && !hasChinese(value)) || ''
  if (chinese) return { local: chinese, english }
  return { local: name, english: '' }
}
function nextLevelEta(site, requirements) {
  const serverDate = String(overview.value.server_date || site?.updated_day || '').slice(0, 10)
  if (!serverDate) return { label: '预计时间待补充', days: null }
  const candidates = (requirements || [])
    .map(row => row.eta)
    .filter(value => value && value !== '—')
    .sort()
  if (!candidates.length) return { label: '预计时间待补充', days: null }
  const targetDate = candidates[candidates.length - 1]
  const start = Date.parse(`${serverDate}T00:00:00Z`)
  const end = Date.parse(`${targetDate}T00:00:00Z`)
  const days = Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, Math.ceil((end - start) / 86400000)) : null
  return { label: `预计达成 ${targetDate}`, days }
}
function durationLabel(days) {
  const value = Number(days || 0)
  if (!value) return '无限制'
  return value % 7 === 0 ? `${value / 7} 周` : `${value} 天`
}
function elapsedAccountDays(site) {
  const startText = String(site?.join_at || '').slice(0, 10)
  const endText = String(overview.value.server_date || site?.updated_day || '').slice(0, 10)
  if (!startText || !endText) return null
  const start = Date.parse(`${startText}T00:00:00Z`)
  const end = Date.parse(`${endText}T00:00:00Z`)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  return Math.max(0, Math.floor((end - start) / 86400000))
}
function springTaskLevel(site, level) {
  const identity = normalizedSiteName(site?.site_name)
  if (!['春天', 'spring', 'springsunday'].includes(identity) || level?.alternatives?.length !== 4) return level
  const [first, second, third, fourth] = level.alternatives
  const realDownload = option => option.unsupported_requirements?.find(item => item.key === 'real_download')
  if (!(first.min_download > 0) || first.min_download !== second.min_download || !realDownload(third) || !realDownload(fourth)) return level
  const task = option => {
    const { min_download, min_download_strict, unsupported_requirements, ...requirements } = option
    return requirements
  }
  if (JSON.stringify(task(first)) !== JSON.stringify(task(third)) || JSON.stringify(task(second)) !== JSON.stringify(task(fourth))) return level
  return {
    ...level,
    downloadAlternatives: [
      { min_download: first.min_download, min_download_strict: first.min_download_strict },
      { unsupported_requirements: [realDownload(third)] },
    ],
    alternatives: [task(first), task(second)],
  }
}
function springUpgradeTasks(site, level) {
  const siteIdentity = normalizedSiteName(site?.site_name)
  const levelIdentity = normalizedSiteName(level?.name)
  const isSpring = siteIdentity === '春天' || siteIdentity === 'spring' || siteIdentity === 'springsunday'
  const isImmortal = levelIdentity.includes('神王') || levelIdentity.includes('immortal')
  if (!isSpring || !isImmortal || level?.alternatives?.length !== 2) return []
  return [
    { title: '任务一', subtitle: '保种升级', icon: 'mdi-seed-outline' },
    { title: '任务二', subtitle: '发种升级', icon: 'mdi-cloud-upload-outline' },
  ]
}
function alternativeTaskOptions(site, level) {
  level = springTaskLevel(site, level)
  const alternatives = level?.alternatives || []
  if (alternatives.length < 2) return []
  const springTasks = springUpgradeTasks(site, level)
  if (springTasks.length) return springTasks
  const numerals = ['一', '二', '三', '四', '五', '六']
  return alternatives.map((option, index) => {
    const targets = []
    if (option.min_seeding_points) targets.push(`积分 ${option.min_seeding_points_strict ? '>' : '≥'} ${formatNumber(option.min_seeding_points, 0)}`)
    if (option.min_torrent_uploads) targets.push(`发布 ${option.min_torrent_uploads_strict ? '>' : '≥'} ${formatNumber(option.min_torrent_uploads, 0)}`)
    if (option.min_download) targets.push(`下载 ${formatBytes(option.min_download)}`)
    if (option.min_upload) targets.push(`上传 ${formatBytes(option.min_upload)}`)
    return {
      title: `任务${numerals[index] || index + 1}`,
      subtitle: targets.slice(0, 2).join(' · ') || '任选条件',
      icon: `mdi-numeric-${index + 1}-circle-outline`,
    }
  })
}
function requirementRows(site, level, alternativeIndex = null) {
  if (!site || !level) return []
  level = springTaskLevel(site, level)
  const rows = []
  const reached = Boolean(level.reached)
  const pushNumeric = ({ key, label, icon, current, target, formatter, strict = false, unavailable = false, etaDate = '' }) => {
    if (!(Number(target) > 0)) return
    const currentNumber = Number(current)
    const targetNumber = Number(target)
    const available = !unavailable && Number.isFinite(currentNumber)
    const complete = reached || (available && (strict ? currentNumber > targetNumber : currentNumber >= targetNumber))
    const progress = complete ? 100 : available ? Math.max(0, Math.min(99, currentNumber * 100 / targetNumber)) : 0
    const difference = available ? Math.max(targetNumber - currentNumber, 0) : null
    let detail = '数据未提供'
    if (complete) detail = '已达成'
    else if (difference !== null) detail = strict && difference === 0 ? `需大于 ${formatter(targetNumber)}` : `剩余 ${formatter(difference)}`
    rows.push({
      key,
      label,
      icon,
      current: available ? formatter(currentNumber) : '数据未提供',
      target: `${strict ? '>' : '≥'} ${formatter(targetNumber)}`,
      detail,
      eta: complete ? '—' : etaDate || '—',
      complete,
      unavailable: !available,
      progress,
    })
  }

  const joinTimeRow = (requirement, key) => {
    if (!(Number(requirement.min_join_days) > 0)) return null
    const currentDays = elapsedAccountDays(site)
    const minimumDays = Number(requirement.min_join_days)
    const strict = Boolean(requirement.min_join_days_strict)
    const complete = reached || (currentDays !== null && (strict ? currentDays > minimumDays : currentDays >= minimumDays))
    const requiredDays = minimumDays + (strict ? 1 : 0)
    let eligibleDate = requirement.eligible_date || ''
    if (!eligibleDate && site.join_at) {
      const joined = new Date(`${String(site.join_at).slice(0, 10)}T00:00:00Z`)
      if (Number.isFinite(joined.getTime())) {
        joined.setUTCDate(joined.getUTCDate() + requiredDays)
        eligibleDate = joined.toISOString().slice(0, 10)
      }
    }
    return {
      key,
      label: '注册时间',
      icon: 'mdi-calendar-check-outline',
      current: complete ? '达成' : currentDays === null ? '加入时间未提供' : `${currentDays} 天`,
      target: `${strict ? '>' : '≥'} ${durationLabel(minimumDays)}`,
      detail: complete ? '已达成' : currentDays === null ? '加入时间未提供' : `剩余 ${durationLabel(requiredDays - currentDays)}`,
      eta: complete ? '—' : eligibleDate || '—',
      complete,
      unavailable: currentDays === null,
      progress: complete ? 100 : currentDays === null ? 0 : Math.max(0, Math.min(99, currentDays * 100 / minimumDays)),
    }
  }
  const pushUnsupported = (requirements, prefix) => {
    for (const [index, requirement] of (requirements || []).entries()) {
      const key = String(requirement.key || '')
      const icon = key.includes('seeding_bonus') ? 'mdi-star-circle-outline' : key.includes('seeding_upload') ? 'mdi-seed-outline' : key.includes('upload') ? 'mdi-cloud-upload-outline' : 'mdi-clipboard-check-outline'
      rows.push({
        key: `${prefix}-${key || 'requirement'}-${index}`,
        label: requirement.label || '其他要求',
        icon,
        current: reached ? '达成' : '数据未提供',
        target: String(requirement.target ?? '需人工确认'),
        detail: reached ? '已达成' : '数据未提供，需人工确认',
        eta: '—',
        complete: reached,
        unavailable: !reached,
        progress: reached ? 100 : 0,
      })
    }
  }
  const joinRow = joinTimeRow(level, 'join-time')
  pushNumeric({ key: 'upload', label: '上传量', icon: 'mdi-upload-outline', current: site.upload, target: level.min_upload, formatter: formatBytes, strict: level.min_upload_strict })
  pushNumeric({ key: 'download', label: '下载量', icon: 'mdi-download-outline', current: site.download, target: level.min_download, formatter: formatBytes, strict: level.min_download_strict })
  pushNumeric({ key: 'ratio', label: '分享率', icon: 'mdi-chart-donut', current: site.ratio, target: level.min_ratio, formatter: value => formatNumber(value, 2), strict: level.min_ratio_strict })
  pushNumeric({ key: 'seeding-points', label: '做种积分', icon: 'mdi-star-circle-outline', current: site.seeding_points, target: level.min_seeding_points, formatter: value => formatNumber(value, 0), strict: level.min_seeding_points_strict, unavailable: site.seeding_points === null || site.seeding_points === undefined, etaDate: level.seeding_points_eta_date })
  if (joinRow) rows.push(joinRow)
  pushNumeric({ key: 'bonus', label: '魔力', icon: 'mdi-lightning-bolt-circle', current: site.bonus, target: level.min_bonus, formatter: value => formatNumber(value, 0), strict: level.min_bonus_strict, unavailable: site.bonus === null || site.bonus === undefined })
  pushNumeric({ key: 'seeding', label: '做种数', icon: 'mdi-seed-outline', current: site.seeding, target: level.min_seeding, formatter: value => formatNumber(value, 0), strict: level.min_seeding_strict })
  pushNumeric({ key: 'seeding-size', label: '做种体积', icon: 'mdi-database-outline', current: site.seeding_size, target: level.min_seeding_size, formatter: formatBytes, strict: level.min_seeding_size_strict })
  pushNumeric({ key: 'torrent-uploads', label: '发布数', icon: 'mdi-cloud-upload-outline', current: site.torrent_uploads, target: level.min_torrent_uploads, formatter: value => formatNumber(value, 0), strict: level.min_torrent_uploads_strict, unavailable: site.torrent_uploads === null || site.torrent_uploads === undefined })
  pushNumeric({ key: 'average-seeding-time', label: '平均做种时间', icon: 'mdi-timer-sand', current: site.average_seeding_time_days, target: level.min_average_seeding_time_days, formatter: value => `${formatNumber(value, 1)} 天`, strict: level.min_average_seeding_time_days_strict, unavailable: site.average_seeding_time_days === null || site.average_seeding_time_days === undefined })
  pushUnsupported(level.unsupported_requirements, 'requirement')
  if (level.downloadAlternatives?.length) {
    const download = level.downloadAlternatives[0]
    pushNumeric({ key: 'download-options', label: '下载量', icon: 'mdi-download-outline', current: site.download, target: download.min_download, formatter: formatBytes, strict: download.min_download_strict })
  }
  const selectedAlternative = Number.isInteger(alternativeIndex) ? level.alternatives?.[alternativeIndex] : null
  if (selectedAlternative) {
    const taskJoinRow = joinTimeRow(selectedAlternative, `task-${alternativeIndex}-join-time`)
    if (taskJoinRow) rows.push(taskJoinRow)
    const taskFields = [
      ['min_upload', '上传量', 'mdi-upload-outline', site.upload, formatBytes],
      ['min_download', '下载量', 'mdi-download-outline', site.download, formatBytes],
      ['min_ratio', '分享率', 'mdi-chart-donut', site.ratio, value => formatNumber(value, 2)],
      ['min_bonus', '魔力', 'mdi-lightning-bolt-circle', site.bonus, value => formatNumber(value, 0)],
      ['min_seeding_points', '做种积分', 'mdi-star-circle-outline', site.seeding_points, value => formatNumber(value, 0)],
      ['min_seeding', '做种数', 'mdi-seed-outline', site.seeding, value => formatNumber(value, 0)],
      ['min_seeding_size', '做种体积', 'mdi-database-outline', site.seeding_size, formatBytes],
      ['min_torrent_uploads', '发布数', 'mdi-cloud-upload-outline', site.torrent_uploads, value => formatNumber(value, 0)],
      ['min_average_seeding_time_days', '平均做种时间', 'mdi-timer-sand', site.average_seeding_time_days, value => `${formatNumber(value, 1)} 天`],
    ]
    for (const [key, label, icon, current, formatter] of taskFields) {
      const target = Number(selectedAlternative[key])
      if (!(target > 0)) continue
      const currentNumber = Number(current)
      const available = current !== null && current !== undefined && Number.isFinite(currentNumber)
      const strict = Boolean(selectedAlternative[`${key}_strict`])
      const complete = reached || (available && (strict ? currentNumber > target : currentNumber >= target))
      const progress = complete ? 100 : available ? Math.max(0, Math.min(99, currentNumber * 100 / target)) : 0
      const difference = available ? Math.max(target - currentNumber, 0) : null
      rows.push({
        key: `task-${alternativeIndex}-${key}`,
        label,
        icon,
        current: available ? formatter(currentNumber) : '数据未提供',
        target: `${strict ? '>' : '≥'} ${formatter(target)}`,
        detail: complete ? '已达成' : difference === null ? '数据未提供' : strict && difference === 0 ? `需大于 ${formatter(target)}` : `剩余 ${formatter(difference)}`,
        eta: key === 'min_seeding_points' && !complete ? selectedAlternative.seeding_points_eta_date || '—' : '—',
        complete,
        unavailable: !available,
        progress,
      })
    }
    pushUnsupported(selectedAlternative.unsupported_requirements, `task-${alternativeIndex}`)
    return rows
  }
  const alternativeRows = (level.alternatives || []).map((option, optionIndex) => {
    const conditions = [
      ['min_upload', '上传', site.upload, formatBytes],
      ['min_download', '下载', site.download, formatBytes],
      ['min_ratio', '分享率', site.ratio, value => formatNumber(value, 2)],
      ['min_bonus', '魔力', site.bonus, value => formatNumber(value, 0)],
      ['min_seeding_points', '做种积分', site.seeding_points, value => formatNumber(value, 0)],
      ['min_seeding', '做种数', site.seeding, value => formatNumber(value, 0)],
      ['min_seeding_size', '做种体积', site.seeding_size, formatBytes],
      ['min_torrent_uploads', '发布数', site.torrent_uploads, value => formatNumber(value, 0)],
      ['min_average_seeding_time_days', '平均做种时间', site.average_seeding_time_days, value => `${formatNumber(value, 1)} 天`],
    ].filter(([key]) => Number(option?.[key]) > 0).map(([key, label, current, formatter]) => {
      const target = Number(option[key])
      const currentNumber = Number(current)
      const available = current !== null && current !== undefined && Number.isFinite(currentNumber)
      const strict = Boolean(option[`${key}_strict`])
      const complete = available && (strict ? currentNumber > target : currentNumber >= target)
      return {
        target: `${label} ${strict ? '>' : '≥'} ${formatter(target)}`,
        current: available ? `${label} ${formatter(currentNumber)}` : `${label}数据未提供`,
        complete,
        progress: complete ? 100 : available ? Math.max(0, Math.min(99, currentNumber * 100 / target)) : 0,
      }
    })
    const optionJoinRow = joinTimeRow(option, `alternative-${optionIndex}-join-time`)
    if (optionJoinRow) {
      conditions.push({
        target: `注册 ${optionJoinRow.target}`,
        current: `注册 ${optionJoinRow.current}`,
        complete: optionJoinRow.complete,
        progress: optionJoinRow.progress,
      })
    }
    for (const requirement of option?.unsupported_requirements || []) {
      conditions.push({ target: `${requirement.label || '其他要求'} ${requirement.target ?? ''}`.trim(), current: `${requirement.label || '其他要求'}数据未提供`, complete: false, progress: 0 })
    }
    return {
      key: `alternative-${optionIndex}`,
      target: conditions.map(item => item.target).join(' 且 '),
      current: conditions.map(item => item.current).join('、'),
      complete: conditions.length > 0 && conditions.every(item => item.complete),
      progress: conditions.length ? conditions.reduce((sum, item) => sum + item.progress, 0) / conditions.length : 0,
    }
  }).filter(option => option.target)
  if (alternativeRows.length) {
    const complete = reached || alternativeRows.some(option => option.complete)
    rows.push({
      key: 'alternatives',
      label: '任选条件',
      icon: 'mdi-call-split',
      current: complete ? '达成' : alternativeRows.map(option => option.current).join(' 或 '),
      target: alternativeRows.map(option => option.target).join(' 或 '),
      detail: complete ? '已达成' : '满足任一条件即可',
      eta: '—',
      complete,
      unavailable: !alternativeRows.some(option => option.current && !option.current.includes('数据未提供')),
      progress: complete ? 100 : Math.max(...alternativeRows.map(option => option.progress)),
    })
  }
  return rows
}
function averageRequirementProgress(requirements) {
  if (!requirements.length || requirements.every(row => row.complete)) return 100
  const progress = Math.round(requirements.reduce((sum, row) => sum + Number(row.progress || 0), 0) / requirements.length)
  return Math.min(99, progress)
}
function levelTrafficRequirements(level) {
  const requirements = []
  if (level.min_upload) requirements.push(`上传 ${level.min_upload_strict ? '>' : '≥'} ${formatBytes(level.min_upload)}`)
  if (level.min_download) requirements.push(`下载 ${level.min_download_strict ? '>' : '≥'} ${formatBytes(level.min_download)}`)
  return requirements.length ? requirements : ['—']
}
function levelRatioRequirement(level) {
  if (level.min_ratio === null || level.min_ratio === undefined) return '—'
  return `分享率 ${level.min_ratio_strict ? '>' : '≥'} ${formatNumber(level.min_ratio, 2)}`
}
function levelPointsRequirement(level) {
  if (level.min_seeding_points) return `做种积分 ${level.min_seeding_points_strict ? '>' : '≥'} ${formatNumber(level.min_seeding_points, 0)}`
  if (level.min_bonus) return `魔力 ${formatNumber(level.min_bonus, 0)}`
  if (level.min_seeding) return `做种 ${formatNumber(level.min_seeding, 0)}`
  return '—'
}
function levelHasDetails(level) {
  return Boolean(level.description?.trim() || level.alternatives?.length)
}
function levelAlternativeRequirements(level, site) {
  level = springTaskLevel(site, level)
  const download = level.downloadAlternatives?.[0]
  const realDownload = level.downloadAlternatives?.[1]?.unsupported_requirements?.[0]
  const commonDownload = download && realDownload
    ? `下载量 ${download.min_download_strict ? '>' : '≥'} ${formatBytes(download.min_download)} 或 ${realDownload.label} ${realDownload.target}`
    : ''
  const numerals = ['一', '二', '三', '四', '五', '六']
  const fields = [
    ['min_join_days', '注册', durationLabel],
    ['min_upload', '上传', formatBytes],
    ['min_download', '下载', formatBytes],
    ['min_ratio', '分享率', value => formatNumber(value, 2)],
    ['min_bonus', '魔力', value => formatNumber(value, 0)],
    ['min_seeding_points', '做种积分', value => formatNumber(value, 0)],
    ['min_seeding', '做种数', value => formatNumber(value, 0)],
    ['min_seeding_size', '做种体积', formatBytes],
    ['min_torrent_uploads', '发布数', value => formatNumber(value, 0)],
    ['min_average_seeding_time_days', '平均做种时间', value => `${formatNumber(value, 1)} 天`],
  ]
  return (level.alternatives || []).map((option, index) => ({
    title: `任务${numerals[index] || index + 1}`,
    requirements: [
      ...(commonDownload ? [commonDownload] : []),
      ...fields.filter(([key]) => Number(option[key]) > 0).map(([key, label, formatter]) => (
        `${label} ${option[`${key}_strict`] ? '>' : '≥'} ${formatter(option[key])}`
      )),
      ...(option.unsupported_requirements || []).map(item => (
        `${item.label || '其他要求'} ${item.target || '需人工确认'}`
      )),
    ],
  }))
}

const selectedRetirementView = computed(() => {
  const site = selectedRetirementSite.value
  if (!site) return null

  const route = retirementRoute(site)
  const levels = site.route || []
  const nextLevel = nextLevelRule(site)
  const displayedLevel = route.find(level => level.name === selectedRouteLevelName.value) || nextLevel
  const upgradeTasks = alternativeTaskOptions(site, displayedLevel)
  const selectedTaskIndex = upgradeTasks.length ? Math.min(springUpgradeTaskIndex.value, upgradeTasks.length - 1) : null
  const requirements = requirementRows(site, displayedLevel, selectedTaskIndex)
  const overallProgress = averageRequirementProgress(requirements)
  const completedCount = requirements.filter(row => row.complete).length
  const routeCount = route.length
  const currentRouteIndex = route.findIndex(level => level.is_current)
  const completedRouteSegments = currentRouteIndex >= 0
    ? Math.min(currentRouteIndex, Math.max(routeCount - 1, 0))
    : site.status === 'retired' ? Math.max(routeCount - 1, 0) : 0

  return {
    route,
    levels,
    routeStyle: routeCount ? {
      '--route-count': routeCount,
      '--route-inset': `${50 / routeCount}%`,
      '--route-span': `${100 - 100 / routeCount}%`,
    } : {},
    routeProgress: routeCount <= 1
      ? 100
      : Math.min(100, (completedRouteSegments + nextLevelOverallProgress(site) / 100) * 100 / (routeCount - 1)),
    displayedLevel,
    isDefaultLevel: displayedLevel?.name === nextLevel?.name,
    requirements,
    upgradeTasks,
    selectedTaskIndex,
    overallProgress,
    completedCount,
    pendingCount: requirements.length - completedCount,
    eta: displayedLevel?.reached ? { label: '已达成', days: null } : nextLevelEta(site, requirements),
  }
})
watch(
  () => sortedRetirementSites.value.map(retirementSiteKey).join('|'),
  () => {
    const sites = sortedRetirementSites.value
    if (!sites.some(site => retirementSiteKey(site) === selectedRetirementSiteKey.value)) {
      selectedRetirementSiteKey.value = retirementSiteKey(sites[0])
    }
  },
  { immediate: true },
)
watch(selectedRetirementSiteKey, () => {
  selectedRouteLevelName.value = ''
  springUpgradeTaskIndex.value = 0
})
watch(
  () => `${historyScope.value}:${historyPeriods.value.map(period => period.key).join('|')}`,
  () => {
    if (!historyPeriods.value.some(period => period.key === selectedHistoryPeriodKey.value)) {
      selectedHistoryPeriodKey.value = historyPeriods.value[0]?.key || ''
    }
    selectedHistorySiteId.value = null
  },
  { immediate: true },
)
watch(
  () => [historyScope.value, selectedHistoryPeriod.value?.key, selectedHistorySiteId.value],
  async () => {
    await loadHourlyTraffic()
    await nextTick()
    renderHistoryChart()
  },
)
watch(historyChartSeries, async () => {
  await nextTick()
  renderHistoryChart()
}, { deep: true })
watch(activeTab, value => {
  if (value === 'history' && !(history.value.records || []).length) loadHistory()
}, { immediate: true })
onMounted(loadAll)
onBeforeUnmount(() => {
  hourlyRequestSequence += 1
  historyRequestSequence += 1
  distributionRequestSequence += 1
  historyChart?.destroy()
})
</script>

<template>
  <div class="pt-workbench" :class="{ 'pt-workbench--compact': compact }">
    <VAlert v-if="error" type="error" variant="tonal" closable class="mb-4" @click:close="error = ''">{{ error }}</VAlert>
    <VProgressLinear v-if="loading" indeterminate color="primary" rounded class="mb-3" />
    <div class="workbench-nav">
      <VTabs v-model="activeTab" color="primary" class="workbench-tabs">
        <VTab value="overview" prepend-icon="mdi-view-dashboard-outline">数据总览</VTab>
        <VTab value="retirement" prepend-icon="mdi-shield-star-outline">养老进度</VTab>
        <VTab value="history" prepend-icon="mdi-chart-timeline-variant">数据统计</VTab>
        <VTab value="config" prepend-icon="mdi-tune-variant">设置</VTab>
      </VTabs>
      <div class="workbench-nav__actions">
        <VBtn v-if="showClose" icon="mdi-close" variant="text" aria-label="关闭" @click="$emit('close')" />
      </div>
    </div>

    <VWindow v-model="activeTab" :touch="false">
      <VWindowItem value="overview">
        <section class="section-block"><div class="metric-grid">
          <MetricCard label="总上传" :value="formatBytes(summary.total_upload)" icon="mdi-arrow-up-bold" color="success" />
          <MetricCard label="总下载" :value="formatBytes(summary.total_download)" icon="mdi-arrow-down-bold" color="error" />
          <MetricCard label="总做种数" :value="formatNumber(summary.total_seeding, 0)" icon="mdi-seed-outline" color="warning" />
          <MetricCard label="总做种体积" :value="formatBytes(summary.total_seeding_size)" icon="mdi-database-outline" color="info" />
          <MetricCard label="今日上传" :value="formatBytes(summary.today_upload)" icon="mdi-arrow-up-bold" color="success" />
          <MetricCard label="今日下载" :value="formatBytes(summary.today_download)" icon="mdi-arrow-down-bold" color="error" />
        </div></section>

        <section class="section-block distribution-panel">
          <div class="section-heading distribution-heading">
            <div><span class="section-kicker">TRAFFIC DISTRIBUTION</span><h2>流量分布</h2></div>
            <VBtnToggle v-model="distributionMetric" mandatory color="primary" density="compact" variant="outlined"><VBtn value="upload">上传</VBtn><VBtn value="download">下载</VBtn></VBtnToggle>
          </div>
          <VProgressLinear v-if="distributionLoading" indeterminate color="primary" height="2" class="mb-3" />
          <div class="distribution-grid">
            <article v-for="panel in [{ key: 'monthly', label: '月度分布', inputLabel: '选择月份', icon: 'mdi-calendar-month-outline', dateKey: 'month', type: 'month' }, { key: 'daily', label: '每日分布', inputLabel: '选择日期', icon: 'mdi-calendar-outline', dateKey: 'day', type: 'date' }]" :key="panel.key" class="distribution-card">
              <div class="distribution-card__header">
                <strong>{{ panel.label }}</strong>
                <VTextField
                  :model-value="distributionFilters[panel.dateKey]"
                  class="distribution-date-input"
                  :type="panel.type"
                  :label="panel.inputLabel"
                  :prepend-inner-icon="panel.icon"
                  :max="panel.type === 'month' ? overview.server_date?.slice(0, 7) : overview.server_date"
                  density="compact"
                  variant="outlined"
                  hide-details
                  :aria-label="panel.inputLabel"
                  @click="openNativePicker"
                  @update:model-value="value => updateDistributionFilter(panel.dateKey, value)"
                />
              </div>
              <div v-if="distributionSegments(distribution[panel.key]).length" class="pie-layout">
                <div class="pie" :style="donutStyle(distribution[panel.key])"><div class="pie__hole"><span>{{ distribution[panel.dateKey] }}</span><strong>{{ formatBytes(distributionSegments(distribution[panel.key]).reduce((sum, item) => sum + item.value, 0)) }}</strong></div></div>
                <div class="pie-legend"><div v-for="item in distributionSegments(distribution[panel.key])" :key="item.site_id || item.site_name"><i :style="{ background: item.color }" /><span>{{ item.site_name }}</span><strong>{{ formatBytes(item.value) }}</strong><em>{{ item.percent.toFixed(1) }}%</em></div></div>
              </div>
              <div v-else class="empty-state compact-empty">所选时间暂无有效流量</div>
            </article>
          </div>
        </section>

        <section class="section-block">
          <div class="section-heading site-data-heading">
            <div><span class="section-kicker">CURRENT SNAPSHOT</span><h2>站点数据</h2></div>
            <VSelect v-model="siteSortKey" :items="siteSortOptions" label="排序方式" prepend-inner-icon="mdi-sort-descending" density="compact" variant="outlined" hide-details class="site-sort-select" />
          </div>
          <div v-if="currentSites.length" class="site-data-list">
            <article v-for="site in sortedCurrentSites" :key="site.site_id || site.site_name" class="site-data-card">
              <header class="site-data-card__header">
                <div class="site-identity"><SiteAvatar :api="api" :site="site" /><div><strong>{{ site.site_name }}</strong><span>{{ site.username || '站点未提供' }} · UID {{ site.userid || '站点未提供' }}</span></div></div>
                <div class="site-account-meta"><VIcon icon="mdi-calendar-outline" size="16" /><span>加入 {{ site.join_at?.slice(0, 10) || '站点未提供' }}</span><VChip size="x-small" color="primary" variant="tonal">{{ site.user_level || '等级未提供' }}</VChip></div>
              </header>
              <div class="site-stat-grid">
                <div><span>累计上传</span><strong class="metric-upload">{{ formatBytes(site.upload) }}</strong></div>
                <div><span>累计下载</span><strong class="metric-download">{{ formatBytes(site.download) }}</strong></div>
                <div><span>今日上传</span><strong class="metric-upload">{{ site.baseline_valid ? formatBytes(site.daily_upload) : '基线不足' }}</strong></div>
                <div><span>今日下载</span><strong class="metric-download">{{ site.baseline_valid ? formatBytes(site.daily_download) : '基线不足' }}</strong></div>
                <div><span>分享率</span><strong>{{ field(site.ratio, 3) }}</strong></div>
                <div><span>魔力</span><strong>{{ bonusValue(site.bonus) }}</strong></div>
                <div><span>预估时魔</span><strong>{{ estimatedBonusHourly(site.estimated_bonus_hourly) }}</strong></div>
                <div><span>做种积分</span><strong>{{ site.seeding_points === null || site.seeding_points === undefined ? '暂无数据' : formatNumber(site.seeding_points, 2) }}</strong></div>
                <div><span>做种数</span><strong>{{ formatNumber(site.seeding, 0) }}</strong></div>
                <div><span>做种体积</span><strong>{{ formatBytes(site.seeding_size) }}</strong></div>
              </div>
            </article>
          </div>
          <div v-else class="empty-state compact-empty">MoviePilot 暂无已启用站点数据</div>
        </section>
      </VWindowItem>

      <VWindowItem value="history">
        <section class="history-console">
          <div v-if="historyPeriods.length" class="history-period-strip" role="listbox" aria-label="数据统计周期">
            <button v-for="period in historyPeriods" :key="period.key" type="button" class="history-period-card" :class="{ 'is-selected': selectedHistoryPeriod?.key === period.key }" :aria-selected="selectedHistoryPeriod?.key === period.key" @click="selectHistoryPeriod(period)"><strong>{{ period.label }}</strong><span><b class="metric-upload">↑ {{ period.validCount ? formatBytes(period.upload) : '—' }}</b><b class="metric-download">↓ {{ period.validCount ? formatBytes(period.download) : '—' }}</b></span></button>
          </div>

          <template v-if="selectedHistoryPeriod">
            <header class="history-detail-summary">
              <VBtnToggle v-model="historyScope" mandatory color="primary" density="compact" variant="outlined" divided class="history-summary-scope"><VBtn value="day">日</VBtn><VBtn value="week">周</VBtn><VBtn value="month">月</VBtn></VBtnToggle>
              <div class="history-detail-metrics"><div><span>周期上传</span><strong class="metric-upload">{{ selectedHistoryPeriod.validCount ? formatBytes(selectedHistoryPeriod.upload) : '基线不足' }}</strong></div><div><span>周期下载</span><strong class="metric-download">{{ selectedHistoryPeriod.validCount ? formatBytes(selectedHistoryPeriod.download) : '基线不足' }}</strong></div><div><span>有效站点</span><strong>{{ selectedHistoryPeriod.siteCount }}</strong></div><div><span>统计范围</span><strong>{{ historyScope === 'day' ? '00:00–23:59' : `${selectedHistoryPeriod.startDay.slice(5)} 至 ${selectedHistoryPeriod.endDay.slice(5)}` }}</strong></div></div>
            </header>

            <section class="history-workspace">
              <aside class="history-site-sidebar" aria-label="数据统计站点列表">
                <div class="history-site-sidebar__heading"><strong>站点列表</strong><span>共 {{ selectedPeriodSites.length }} 个</span></div>
                <div class="history-site-sidebar__items">
                  <button type="button" class="history-site-option" :class="{ 'is-selected': selectedHistorySiteId === null }" @click="selectHistorySite(null)">
                    <VAvatar :size="34" color="primary" variant="tonal"><VIcon icon="mdi-earth" size="19" /></VAvatar>
                    <span class="history-site-option__body"><strong>全部站点</strong><small><b class="metric-upload">↑ {{ selectedHistoryPeriod.validCount ? formatBytes(selectedHistoryPeriod.upload) : '—' }}</b><b class="metric-download">↓ {{ selectedHistoryPeriod.validCount ? formatBytes(selectedHistoryPeriod.download) : '—' }}</b></small></span>
                  </button>
                  <button v-for="item in selectedPeriodSites" :key="item.site_id || item.site_name" type="button" class="history-site-option" :class="{ 'is-selected': Number(item.site_id) === Number(selectedHistorySiteId) }" @click="selectHistorySite(item)">
                    <SiteAvatar :api="api" :site="item" :size="34" />
                    <span class="history-site-option__body"><strong>{{ item.site_name }}</strong><small><b class="metric-upload">↑ {{ item.valid_count ? formatBytes(item.period_upload) : '—' }}</b><b class="metric-download">↓ {{ item.valid_count ? formatBytes(item.period_download) : '—' }}</b></small></span>
                  </button>
                </div>
              </aside>

              <div class="history-workspace__main">
                <section class="history-trend-panel history-overall-trend">
                  <div class="history-pane-heading history-chart-heading"><div><strong>{{ selectedHistorySite?.site_name || '全部站点' }} · {{ historyScope === 'day' ? '每小时流量' : '按日期流量' }}</strong><span>{{ selectedHistoryPeriod.startDay }}{{ historyScope === 'day' ? ' 00:00–23:59' : ` — ${selectedHistoryPeriod.endDay}` }}</span></div><div class="legend"><span><i class="legend__upload" />上传</span><span><i class="legend__download" />下载</span></div></div>
                  <div class="history-line-chart" :class="{ 'is-loading': hourlyLoading }"><canvas :ref="setHistoryChartCanvas" :aria-label="`${selectedHistorySite?.site_name || '全部站点'}上传下载流量曲线图`" /></div>
                  <div v-if="historyScope === 'day' && !hourlyLoading && !hourlyTraffic.baseline_valid" class="history-chart-note">MP 在该日没有足够的相邻采样：小时曲线至少需要同一站点在当天产生 2 次数据刷新</div>
                </section>

                <section class="history-site-panel">
                  <div class="history-pane-heading"><div><strong>{{ selectedHistorySite ? `${selectedHistorySite.site_name} · 历史数据` : '全部站点 · 周期明细' }}</strong><span>{{ selectedHistorySite ? '所选周期内的每日历史数据' : '选择左侧站点可查看该站点历史数据' }}</span></div><VChip v-if="selectedHistorySite" size="small" color="primary" variant="tonal" closable @click:close="selectHistorySite(null)">{{ selectedHistorySite.site_name }}</VChip></div>
                  <div v-if="!selectedHistorySite" class="history-detail-shell"><VTable fixed-header density="compact" class="history-detail-table"><thead><tr><th>站点</th><th>累计数据</th><th>周期增量</th><th>分享率</th><th>魔力</th><th>做种数</th><th>做种体积</th></tr></thead><tbody><tr v-for="item in selectedPeriodSites" :key="`${item.site_id || item.site_name}-${selectedHistoryPeriod.key}`" class="history-site-row" tabindex="0" @click="selectHistorySite(item)" @keydown.enter.prevent="selectHistorySite(item)"><td><div class="site-identity"><SiteAvatar :api="api" :site="item" :size="30" /><strong>{{ item.site_name }}</strong><VIcon icon="mdi-chevron-right" size="17" /></div></td><td><span class="stacked-metric metric-upload">↑ {{ formatBytes(item.upload) }}</span><span class="stacked-metric metric-download">↓ {{ formatBytes(item.download) }}</span></td><td><span class="stacked-metric metric-upload">↑ {{ item.valid_count ? formatBytes(item.period_upload) : '基线不足' }}</span><span class="stacked-metric metric-download">↓ {{ item.valid_count ? formatBytes(item.period_download) : '基线不足' }}</span></td><td>{{ field(item.ratio, 3) }}</td><td>{{ bonusValue(item.bonus) }}</td><td>{{ formatNumber(item.seeding, 0) }} 个</td><td>{{ formatBytes(item.seeding_size) }}</td></tr></tbody></VTable></div>
                  <div v-else class="history-record-shell"><VTable fixed-header density="compact" class="history-record-table"><thead><tr><th>日期</th><th>累计上传</th><th>累计下载</th><th>当日上传</th><th>当日下载</th><th>分享率</th><th>魔力</th><th>做种数</th><th>做种体积</th></tr></thead><tbody><tr v-for="record in selectedHistoryRecords" :key="`${record.site_id}-${record.updated_day}`"><td>{{ record.updated_day || '—' }}</td><td class="metric-upload">{{ formatBytes(record.upload) }}</td><td class="metric-download">{{ formatBytes(record.download) }}</td><td class="metric-upload">{{ record.baseline_valid ? formatBytes(record.daily_upload) : '基线不足' }}</td><td class="metric-download">{{ record.baseline_valid ? formatBytes(record.daily_download) : '基线不足' }}</td><td>{{ field(record.ratio, 3) }}</td><td>{{ bonusValue(record.bonus) }}</td><td>{{ formatNumber(record.seeding, 0) }} 个</td><td>{{ formatBytes(record.seeding_size) }}</td></tr></tbody></VTable></div>
                </section>
              </div>
            </section>
          </template>
          <div v-else class="empty-state"><VIcon icon="mdi-database-search-outline" size="44" /><span>暂无历史数据，请等待 MoviePilot 站点刷新</span></div>
        </section>
      </VWindowItem>

      <VWindowItem value="retirement">
        <section class="section-block twelve-panel">
          <div class="section-heading twelve-panel__heading">
            <div><span class="section-kicker">COLLECTION</span><h2>十二大进度</h2></div>
            <div class="twelve-summary" aria-label="十二大完成情况">
              <div><strong>{{ twelveJoinedCount }}</strong><span>/ {{ twelveTotalCount }}</span><small>已加入站点</small></div>
              <i aria-hidden="true" />
              <div><strong class="text-success">{{ overview.twelve?.percent || 0 }}%</strong><small>完成进度</small></div>
            </div>
          </div>
          <div class="twelve-overflow">
            <div class="twelve-track" role="list" aria-label="十二大站点进度">
              <div class="twelve-track__line"><i :style="{ width: `${twelveTrackPercent}%` }" /></div>
              <div v-for="(item, index) in twelveItems" :key="item.key" class="twelve-node" :class="`twelve-node--${item.state}`" role="listitem" :aria-label="item.state === 'joined' ? `${item.name}，加入于 ${item.join_at || '未知时间'}` : `第 ${index + 1} 个未解锁节点`">
                <span class="twelve-node__index">{{ index + 1 }}</span>
                <VTooltip location="top">
                  <template #activator="{ props: tooltipProps }">
                    <div v-bind="tooltipProps" class="twelve-node__marker">
                    <SiteAvatar v-if="item.state === 'joined' && item.site_id" :api="api" :site="{ site_id: item.site_id, site_name: item.name }" :size="36" />
                    <VAvatar v-else :size="36" color="secondary" variant="tonal"><VIcon :icon="stateMeta(item.state).icon" size="20" /></VAvatar>
                  </div>
                  </template>
                  <strong>{{ item.state === 'joined' ? item.name : '未解锁节点' }}</strong>
                  <div>{{ item.state === 'joined' && item.join_at ? `加入于 ${item.join_at}` : stateMeta(item.state).label }}</div>
                </VTooltip>
                <strong v-if="item.state === 'joined'" class="twelve-node__name">{{ item.name }}</strong>
              </div>
            </div>
            <div class="twelve-remaining">剩余 <strong>{{ twelveRemainingCount }}</strong> 个站点</div>
          </div>
        </section>
        <section class="section-block">
          <div class="section-heading">
            <div><span class="section-kicker">RETIREMENT</span><h2>养老进度</h2></div>
            <div class="retirement-summary">
              <VChip color="secondary" variant="tonal">规则缺失 {{ retirement.rule_missing || 0 }}</VChip>
              <VChip color="warning" variant="tonal">升级中 {{ retirement.upgrading || 0 }}</VChip>
              <VChip color="success" variant="tonal">养老中 {{ ordinaryRetiredCount }}</VChip>
              <VChip class="wealthy-summary-chip" prepend-icon="mdi-crown" variant="flat">富贵养老 {{ wealthyRetiredCount }}</VChip>
            </div>
          </div>
          <div v-if="selectedRetirementSite" class="retirement-explorer">
            <aside class="retirement-site-list" aria-label="养老进度站点列表">
              <div class="retirement-site-list__heading"><strong>站点列表</strong><span>共 {{ retirement.sites?.length || 0 }} 个站点</span></div>
              <VSelect v-model="retirementSortKey" :items="retirementSortOptions" label="排序方式" prepend-inner-icon="mdi-sort" density="compact" variant="outlined" hide-details class="retirement-site-sort" />
              <div class="retirement-site-list__items">
                <button
                  v-for="site in sortedRetirementSites"
                  :key="retirementSiteKey(site)"
                  type="button"
                  class="retirement-site-option"
                  :class="{ 'retirement-site-option--selected': retirementSiteKey(site) === retirementSiteKey(selectedRetirementSite), 'retirement-site-option--wealthy': site.status === 'wealthy_retired' }"
                  :aria-pressed="retirementSiteKey(site) === retirementSiteKey(selectedRetirementSite)"
                  @click="selectRetirementSite(site)"
                >
                  <SiteAvatar :api="api" :site="site" :size="42" />
                  <span class="retirement-site-option__body">
                    <span class="retirement-site-option__title"><strong>{{ site.site_name }}</strong><em v-if="site.status !== 'wealthy_retired'" :class="`status-${site.status}`">{{ retirementMeta(site.status, site).label }}</em></span>
                    <span>{{ site.current_level || '站点未提供等级' }}</span>
                    <VProgressLinear :model-value="nextLevelOverallProgress(site)" :color="site.status === 'wealthy_retired' ? 'warning' : 'primary'" bg-color="surface-variant" height="4" rounded />
                  </span>
                  <small>{{ site.status === 'wealthy_retired' ? '富贵养老' : `${nextLevelOverallProgress(site)}%` }}</small>
                </button>
              </div>
            </aside>

            <article class="retirement-detail">
              <header class="retirement-detail__header">
                <div class="retirement-detail__identity">
                  <SiteAvatar :api="api" :site="selectedRetirementSite" :size="58" />
                  <div><h3>{{ selectedRetirementSite.site_name }}</h3><span>当前等级 <strong>{{ selectedRetirementSite.current_level || '站点未提供' }}</strong></span><span v-if="selectedRetirementSite.retirement_level">目标等级 <strong class="target-level">{{ selectedRetirementSite.retirement_level }}（保号）</strong></span></div>
                </div>
                <div class="retirement-detail__right">
                  <VChip v-if="selectedRetirementSite.status === 'wealthy_retired'" class="wealthy-retirement-badge" prepend-icon="mdi-crown" variant="flat">富贵养老</VChip>
                  <div class="retirement-detail__metrics">
                    <span>上传<strong>{{ formatBytes(selectedRetirementSite.upload) }}</strong></span>
                    <span>下载<strong>{{ formatBytes(selectedRetirementSite.download) }}</strong></span>
                    <span>分享率<strong>{{ field(selectedRetirementSite.ratio, 2) }}</strong></span>
                  </div>
                </div>
              </header>

              <div v-if="selectedRetirementSite.status === 'wealthy_retired'" class="wealthy-retirement-state" aria-label="富贵养老状态">
                <div class="wealthy-retirement-state__icon"><VIcon icon="mdi-crown" size="28" /></div>
                <div><span>{{ selectedRetirementSite.wealthy_retirement_manual ? '手动指定站点' : 'VIP 会员等级' }}</span><strong>富贵养老</strong><small>{{ selectedRetirementSite.wealthy_retirement_manual ? '已在设置中手动标记；完整等级路线仍可在下方查看。' : '会员等级不强行映射普通等级，完整等级路线仍可在下方查看。' }}</small></div>
              </div>

              <div v-else-if="selectedRetirementView.route.length" class="retirement-route-rail" aria-label="等级进度">
                <div
                  class="retirement-route-rail__track"
                  :style="selectedRetirementView.routeStyle"
                >
                  <div class="retirement-route-rail__line">
                    <VProgressLinear :model-value="selectedRetirementView.routeProgress" color="primary" bg-color="secondary" :bg-opacity="0.3" height="5" rounded />
                  </div>
                  <div class="retirement-route-rail__nodes">
                    <button
                      v-for="(level, index) in selectedRetirementView.route"
                      :key="level.name"
                      type="button"
                      class="retirement-route-node"
                      :class="{ 'is-reached': level.reached, 'is-current': level.is_current, 'is-next': level.name === selectedRetirementSite.next_level, 'is-retirement': level.is_retirement, 'is-selected': level.name === selectedRetirementView.displayedLevel?.name }"
                      :aria-pressed="level.name === selectedRetirementView.displayedLevel?.name"
                      :aria-label="`查看 ${level.name} 等级进度`"
                      @click="selectedRouteLevelName = level.name; springUpgradeTaskIndex = 0"
                    >
                      <i class="retirement-route-node__marker" aria-hidden="true">{{ index + 1 }}</i>
                      <strong class="retirement-route-node__name"><span>{{ splitLevelName(level).local }}</span><span v-if="splitLevelName(level).english">{{ splitLevelName(level).english }}</span></strong>
                      <em class="retirement-route-node__badge">{{ routeNodeStatus(selectedRetirementSite, level) }}</em>
                    </button>
                  </div>
                </div>
              </div>

              <div v-if="selectedRetirementSite.status !== 'wealthy_retired' && selectedRetirementView.route.length" class="retirement-target-grid">
                <section class="requirement-panel">
                  <div class="requirement-panel__heading">
                    <div><VIcon icon="mdi-target" color="primary" size="34" /><span>{{ selectedRetirementView.isDefaultLevel ? '下一等级' : '所选等级' }}</span><strong>{{ selectedRetirementView.displayedLevel?.name || '已是最高等级' }}</strong></div>
                    <div v-if="selectedRetirementView.upgradeTasks.length" class="spring-upgrade-tasks" role="tablist" aria-label="任选任务">
                      <button
                        v-for="(task, index) in selectedRetirementView.upgradeTasks"
                        :key="task.title"
                        type="button"
                        class="spring-upgrade-task"
                        :class="{ 'is-selected': selectedRetirementView.selectedTaskIndex === index }"
                        role="tab"
                        :aria-selected="selectedRetirementView.selectedTaskIndex === index"
                        @click="springUpgradeTaskIndex = index"
                      >
                        <VIcon :icon="task.icon" size="18" />
                        <span><strong>{{ task.title }}</strong><small>{{ task.subtitle }}</small></span>
                      </button>
                    </div>
                    <div v-else class="requirement-panel__spacer" aria-hidden="true" />
                    <VChip :color="selectedRetirementView.displayedLevel?.reached ? 'success' : 'warning'" size="small" variant="tonal" :prepend-icon="selectedRetirementView.displayedLevel?.reached ? 'mdi-check-circle-outline' : 'mdi-clock-outline'">{{ selectedRetirementView.eta.label }}<template v-if="selectedRetirementView.eta.days !== null"> · 约 {{ selectedRetirementView.eta.days }} 天</template></VChip>
                  </div>
                  <div v-if="selectedRetirementView.requirements.length" class="requirement-overview">
                    <div class="requirement-overview__score">
                      <VProgressCircular :model-value="selectedRetirementView.overallProgress" :size="124" :width="12" color="primary"><strong>{{ selectedRetirementView.overallProgress }}%</strong></VProgressCircular>
                      <span>总体进度</span><b>{{ selectedRetirementView.overallProgress }}%</b>
                      <small>已完成 {{ selectedRetirementView.completedCount }} 项 · 待完成 {{ selectedRetirementView.pendingCount }} 项</small>
                    </div>
                    <div class="requirement-table">
                      <div class="requirement-table__head"><span>项目</span><span>目标要求</span><span>当前进度</span><span>剩余</span><span>时间</span><span>完成进度</span></div>
                      <div v-for="row in selectedRetirementView.requirements" :key="row.key" class="requirement-row">
                        <span class="requirement-row__item"><VIcon :icon="row.icon" color="secondary" size="22" /><strong>{{ row.label }}</strong></span>
                        <span>{{ row.target }}</span>
                        <strong :class="{ 'text-success': row.complete }">{{ row.current }}</strong>
                        <span :class="{ 'text-success': row.complete, 'text-warning': row.unavailable }">{{ row.complete ? '—' : row.detail.replace(/^剩余\s*/, '') }}</span>
                        <span>{{ row.eta }}</span>
                        <span class="requirement-row__progress"><VProgressLinear :model-value="row.progress" :color="row.complete ? 'success' : row.unavailable ? 'warning' : 'primary'" bg-color="surface-variant" height="7" rounded /><b>{{ Math.round(row.progress) }}%</b></span>
                      </div>
                    </div>
                  </div>
                  <div v-else class="compact-empty-state">{{ selectedRetirementView.displayedLevel ? '该等级没有要求数据' : '没有后续等级要求' }}</div>
                </section>

              </div>

              <section v-if="selectedRetirementView.levels.length" class="retirement-levels">
                <div class="retirement-levels__heading"><div><VIcon icon="mdi-chart-bar" color="primary" /><strong>等级路线与要求</strong></div></div>
                <div class="retirement-levels__table">
                  <div class="retirement-levels__columns"><span>等级</span><span>注册</span><span>流量</span><span>分享率</span><span>做种积分</span><i /></div>
                  <details v-for="level in selectedRetirementView.levels" :key="level.name" class="retirement-level-row" :class="{ 'has-detail': levelHasDetails(level) }" :open="levelHasDetails(level) && (level.is_current || level.name === selectedRetirementSite.next_level)">
                    <summary @click="!levelHasDetails(level) && $event.preventDefault()">
                      <strong>{{ level.name }}</strong>
                      <span data-label="注册">{{ level.min_join_days ? `${level.min_join_days_strict ? '>' : '≥'} ${durationLabel(level.min_join_days)}` : '无限制' }}</span>
                      <span class="retirement-level-row__traffic" data-label="流量"><span v-for="item in levelTrafficRequirements(level)" :key="item">{{ item }}</span></span>
                      <span data-label="分享率">{{ levelRatioRequirement(level).replace(/^分享率\s*/, '') }}</span>
                      <span data-label="做种积分">{{ levelPointsRequirement(level).replace(/^做种积分\s*/, '') }}</span>
                      <VIcon v-if="levelHasDetails(level)" icon="mdi-chevron-down" size="18" />
                    </summary>
                    <div v-if="level.description || level.alternatives?.length" class="retirement-level-row__detail" :class="{ 'has-alternatives': level.description && level.alternatives?.length }">
                      <div v-if="level.description" class="retirement-level-row__description">
                        <div class="retirement-level-row__detail-title"><VIcon icon="mdi-text-box-outline" size="18" /><strong>等级说明</strong></div>
                        <p>{{ level.description }}</p>
                      </div>
                      <div v-if="level.alternatives?.length" class="retirement-level-row__alternatives">
                        <div class="retirement-level-row__detail-title"><VIcon icon="mdi-call-split" size="18" /><strong>任选条件</strong></div>
                        <p>满足以下任一任务即可达到该等级</p>
                        <div class="retirement-level-row__tasks">
                          <div v-for="task in levelAlternativeRequirements(level, selectedRetirementSite)" :key="task.title" class="retirement-level-row__task">
                            <strong>{{ task.title }}</strong>
                            <span v-for="requirement in task.requirements" :key="requirement">{{ requirement }}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </details>
                </div>
              </section>
              <div v-else class="empty-state compact-empty">该站等级规则尚未确定</div>
            </article>
          </div>
          <div v-if="!retirement.sites?.length" class="empty-state"><VIcon icon="mdi-shield-search-outline" size="42" /><span>MoviePilot 暂无有效站点数据</span></div>
        </section>
      </VWindowItem>

      <VWindowItem value="config">
        <section class="section-block settings-layout">
          <div class="settings-card"><div class="section-heading"><div><span class="section-kicker">GENERAL</span><h2>基础设置</h2></div></div><VSwitch v-model="settingsDraft.enabled" color="primary" label="启用插件" hint="启用后读取 MP 已保存的站点数据，并在刷新时记录小时快照" persistent-hint /><VTextField v-model.number="settingsDraft.retention_days" type="number" min="0" max="36500" label="小时快照保留天数" hint="0 表示永久保留；日级历史由 MP 管理，不受此设置影响" persistent-hint variant="outlined" class="mt-3" /></div>
          <div class="settings-card"><div class="section-heading"><div><span class="section-kicker">NOTIFICATION</span><h2>每日通知</h2></div></div><VSwitch v-model="settingsDraft.notification_enabled" color="primary" label="启用汇总通知" /><VTextField v-model="settingsDraft.notification_cron" label="通知 Cron（五段式）" placeholder="0 9 * * *" hint="分 时 日 月 星期；按服务器时区执行，每个自然日最多通知一次" persistent-hint variant="outlined" /><VCheckbox v-model="settingsDraft.notification_modes" value="today" label="今日数据：仅上传和下载增量" hide-details /><VCheckbox v-model="settingsDraft.notification_modes" value="all" label="所有数据：仅累计上传和累计下载" hide-details /><div class="setting-hint mt-2">Cron 错过后不补发；无数据站点不会通知。</div></div>
          <div class="settings-card settings-card--wide"><div class="section-heading"><div><span class="section-kicker">PTD RECEIVER</span><h2>PTD 数据补充</h2></div><span class="section-note">仅导入时魔和做种积分</span></div><VSwitch v-model="settingsDraft.ptd_cookiecloud_enabled" color="primary" label="启用 PTD 兼容接收端" hint="PTD 直接把最新备份发送给本插件；不需要启用 MoviePilot 内置 CookieCloud" persistent-hint /><div v-if="settingsDraft.ptd_cookiecloud_enabled" class="ptd-settings-grid"><VTextField :model-value="ptdReceiverUrl" class="ptd-receiver-url" label="PTD CookieCloud 地址" hint="同机使用 localhost；其它局域网设备请替换为 MoviePilot 主机 IP" persistent-hint readonly variant="outlined" /><VTextField :model-value="ptdUuidVisible ? settingsDraft.ptd_cookiecloud_uuid : ''" :readonly="!ptdUuidVisible" placeholder="点击右侧随机按钮生成并显示" autocomplete="off" @update:model-value="settingsDraft.ptd_cookiecloud_uuid = $event" label="PTD 专用 UUID" hint="插件与 PTD 必须填写完全相同的 UUID" persistent-hint variant="outlined"><template #append-inner><VBtn icon="mdi-shuffle-variant" size="small" variant="text" title="随机生成 UUID" @click="randomizePtdUuid" /></template></VTextField><VTextField :model-value="ptdPasswordVisible ? settingsDraft.ptd_cookiecloud_password : ''" :readonly="!ptdPasswordVisible" placeholder="点击右侧随机按钮生成并显示" @update:model-value="settingsDraft.ptd_cookiecloud_password = $event" label="CookieCloud 密码" hint="插件与 PTD 必须填写完全相同的密码" persistent-hint type="text" autocomplete="off" variant="outlined"><template #append-inner><VBtn icon="mdi-shuffle-variant" size="small" variant="text" title="随机生成密码" @click="randomizePtdPassword" /></template></VTextField><VTextarea v-model="settingsDraft.ptd_cookiecloud_headers" label="接收鉴权 Headers（可选）" placeholder="X-PTD-Token: 自定义密钥" hint="如填写，PTD 的 Headers 也要逐行填写相同内容；日志不会记录值" persistent-hint variant="outlined" rows="3" /></div><div class="setting-hint mt-3">先保存本页，再在 PTD 中新增 CookieCloud 备份服务器：PTD 与 MoviePilot 同机时使用上方 localhost 地址；其它局域网设备将 localhost 替换为 MoviePilot 主机 IP。UUID、密码和可选 Headers 与这里保持一致；备份项目勾选“用户信息”。收到新备份后会立即解析并覆盖上一份数据，过程可在 MoviePilot 插件日志中查看。</div></div>
          <div class="settings-card settings-card--wide wealthy-site-settings">
            <div class="section-heading"><div><span class="section-kicker">WEALTHY RETIREMENT</span><h2>富贵养老</h2></div><VChip class="wealthy-summary-chip" prepend-icon="mdi-crown" variant="flat">已选择 {{ settingsDraft.wealthy_retirement_sites?.length || 0 }}</VChip></div>
            <div class="setting-hint">选择当前拥有 VIP、捐赠者或其它特殊会员身份的站点；保存后该站养老进度显示为“富贵养老”。选择结果按 MoviePilot 站点 ID 保存。</div>
            <div v-if="wealthyRetirementSiteOptions.length" class="wealthy-selection-summary">
              <div class="wealthy-selection-summary__sites">
                <div v-if="selectedWealthyRetirementSites.length" class="wealthy-selection-avatars" aria-hidden="true">
                  <SiteAvatar v-for="site in selectedWealthyRetirementSites.slice(0, 5)" :key="wealthyRetirementSiteKey(site)" :api="api" :site="site" :size="34" />
                </div>
                <div class="wealthy-selection-summary__copy">
                  <strong>{{ selectedWealthyRetirementSites.length ? selectedWealthyRetirementSites.map(site => site.site_name).join('、') : '尚未选择站点' }}</strong>
                  <small>{{ selectedWealthyRetirementSites.length ? `已标记 ${selectedWealthyRetirementSites.length} 个特殊会员站点` : '需要时打开选择器，不会占用设置页空间' }}</small>
                </div>
              </div>
              <VBtn color="warning" variant="tonal" prepend-icon="mdi-tune-variant" @click="wealthyPickerOpen = true">选择站点</VBtn>
            </div>
            <div v-else class="empty-state compact-empty">MoviePilot 暂无可选择的站点</div>

            <VDialog v-model="wealthyPickerOpen" max-width="720" scrollable transition="dialog-bottom-transition">
              <VCard class="wealthy-picker-dialog-card">
                <VCardTitle class="wealthy-picker-dialog__header">
                  <div><span class="section-kicker">VIP SITES</span><strong>选择富贵养老站点</strong></div>
                  <VBtn icon="mdi-close" variant="text" aria-label="关闭站点选择器" @click="wealthyPickerOpen = false" />
                </VCardTitle>
                <VCardText class="wealthy-picker-dialog__body">
                  <div class="wealthy-picker-toolbar">
                    <VTextField v-model="wealthySiteSearch" autofocus clearable hide-details density="comfortable" variant="outlined" prepend-inner-icon="mdi-magnify" label="搜索站点名称或 ID" />
                    <VBtn variant="text" color="error" :disabled="!settingsDraft.wealthy_retirement_sites?.length" @click="clearWealthyRetirementSites">清空已选</VBtn>
                  </div>
                  <div class="wealthy-picker-status"><span>已选 {{ settingsDraft.wealthy_retirement_sites?.length || 0 }} 个</span><small>已选站点优先显示</small></div>
                  <div v-if="filteredWealthyRetirementSiteOptions.length" class="wealthy-site-picker">
                    <button v-for="site in filteredWealthyRetirementSiteOptions" :key="wealthyRetirementSiteKey(site)" type="button" class="wealthy-site-card" :class="{ 'is-selected': isWealthyRetirementSiteSelected(site) }" :aria-pressed="isWealthyRetirementSiteSelected(site)" @click="toggleWealthyRetirementSite(site)"><SiteAvatar :api="api" :site="site" :size="38" /><span><strong>{{ site.site_name }}</strong><small>站点 ID {{ site.site_id }}</small></span><VIcon :icon="isWealthyRetirementSiteSelected(site) ? 'mdi-check-circle' : 'mdi-circle-outline'" size="22" /></button>
                  </div>
                  <div v-else class="empty-state compact-empty"><VIcon icon="mdi-magnify-close" size="34" /><span>没有匹配的站点</span></div>
                </VCardText>
                <VCardActions class="wealthy-picker-dialog__actions"><span>修改将在保存设置后生效</span><VBtn color="primary" variant="flat" @click="wealthyPickerOpen = false">完成</VBtn></VCardActions>
              </VCard>
            </VDialog>
          </div>
          <div class="settings-card settings-card--wide"><div class="section-heading"><div><span class="section-kicker">LEVEL RULES</span><h2>等级规则</h2></div><div class="rules-upload__actions"><VBtn variant="tonal" color="primary" prepend-icon="mdi-upload-outline" @click="rulesFileInput?.click()">上传规则文件</VBtn><VBtn variant="text" prepend-icon="mdi-file-download-outline" @click="downloadRuleTemplate">下载模板</VBtn><VBtn v-if="customRuleSites.length" variant="text" color="error" prepend-icon="mdi-delete-outline" @click="clearUploadedRules">清空</VBtn></div></div><input ref="rulesFileInput" class="rules-file-input" type="file" accept="application/json,.json" @change="uploadRuleFile"><div v-if="customRuleSites.length" class="rules-upload"><div><strong>已载入 {{ customRuleSites.length }} 个站点</strong><p>{{ customRuleSites.join('、') }}</p><small v-if="rulesUploadName">文件：{{ rulesUploadName }}</small></div></div><div class="setting-hint mt-3">自定义规则优先级最高，上传并保存后，匹配站点以自定义规则为主；未匹配的站点继续使用内置规则。</div></div>
          <div class="settings-card settings-card--wide settings-actions"><div><strong>数据来源</strong><p>上传、下载、分享率等仍仅来自 MoviePilot；PTD 只补充最新时魔和做种积分。</p></div><VBtn color="primary" size="large" variant="flat" prepend-icon="mdi-content-save-outline" :loading="saving" @click="saveSettings">保存设置</VBtn></div>
        </section>
      </VWindowItem>
    </VWindow>
  </div>
</template>

<style scoped>
.distribution-date-input{max-width:220px}.distribution-date-input :deep(.v-field){border-radius:12px;background:rgba(var(--v-theme-surface),.72)}
.site-sort-select{width:min(100%,220px);flex:0 0 220px}
.history-search-btn{min-height:48px;border-radius:12px;font-weight:700;letter-spacing:.02em}
.workbench-nav{display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:1px solid var(--pt-border)}
.workbench-nav .workbench-tabs{min-width:0;flex:1 1 auto;margin:0;border-bottom:0}
.workbench-nav__actions{display:flex;flex:0 0 auto;align-items:center;gap:6px;padding-right:4px}
.history-console{min-width:0;margin-top:16px;overflow:hidden;border:1px solid var(--pt-border);border-radius:18px;background:rgba(var(--v-theme-surface),.55)}
.history-period-strip{display:flex;gap:7px;overflow-x:auto;padding:10px 14px;border-bottom:1px solid var(--pt-border);scrollbar-width:thin;scroll-snap-type:x proximity}
.history-period-card{appearance:none;display:grid;flex:0 0 minmax(150px,1fr);min-width:150px;gap:7px;padding:10px 12px;border:1px solid var(--pt-border);border-radius:11px;background:rgba(var(--v-theme-surface),.34);color:inherit;font:inherit;text-align:left;cursor:pointer;scroll-snap-align:start;transition:background-color .16s ease,border-color .16s ease,box-shadow .16s ease}
.history-period-card:hover,.history-period-card:focus-visible{border-color:rgba(var(--v-theme-primary),.46);background:rgba(var(--v-theme-primary),.07);outline:none}.history-period-card.is-selected{border-color:rgb(var(--v-theme-primary));background:rgba(var(--v-theme-primary),.15);box-shadow:inset 0 -2px rgb(var(--v-theme-primary))}
.history-period-card strong{font-size:.78rem}.history-period-card span{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:.66rem;white-space:nowrap}
.history-pane-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px;border-bottom:1px solid var(--pt-border)}
.history-pane-heading>div{display:flex;min-width:0;flex-direction:column;gap:2px}
.history-pane-heading strong{font-size:.84rem}
.history-pane-heading span{color:rgba(var(--v-theme-on-surface),.52);font-size:.68rem}
.history-detail-summary{display:flex;align-items:center;justify-content:space-between;gap:22px;padding:13px 18px;border-bottom:1px solid var(--pt-border)}
.history-summary-scope{flex:0 0 auto}.history-summary-scope :deep(.v-btn){min-width:42px}
.history-detail-metrics{display:grid;grid-template-columns:repeat(4,minmax(92px,1fr));gap:20px}.history-detail-metrics>div{display:flex;min-width:0;flex-direction:column;gap:3px}.history-detail-metrics span{color:rgba(var(--v-theme-on-surface),.52);font-size:.66rem}.history-detail-metrics strong{font-size:.8rem;white-space:nowrap}
.history-workspace{display:grid;grid-template-columns:minmax(210px,255px) minmax(0,1fr);height:clamp(610px,calc(100vh - 230px),800px);min-height:0;overflow:hidden}
.history-site-sidebar{display:flex;min-width:0;min-height:0;flex-direction:column;overflow:hidden;padding:12px;border-right:1px solid var(--pt-border);background:rgba(var(--v-theme-surface-variant),.08)}
.history-site-sidebar__heading{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:2px 4px 11px}.history-site-sidebar__heading span{color:rgba(var(--v-theme-on-surface),.52);font-size:.68rem}
.history-site-sidebar__items{display:grid;min-height:0;flex:1 1 auto;align-content:start;gap:6px;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable}
.history-site-option{appearance:none;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:9px;width:100%;padding:10px;border:1px solid transparent;border-radius:12px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color .15s ease,border-color .15s ease}
.history-site-option:hover,.history-site-option:focus-visible{border-color:rgba(var(--v-theme-primary),.34);background:rgba(var(--v-theme-primary),.07);outline:none}.history-site-option.is-selected{border-color:rgba(var(--v-theme-primary),.5);background:rgba(var(--v-theme-primary),.14);box-shadow:inset 3px 0 rgb(var(--v-theme-primary))}
.history-site-option__body{display:grid;min-width:0;gap:4px}.history-site-option__body>strong{overflow:hidden;font-size:.76rem;text-overflow:ellipsis;white-space:nowrap}.history-site-option__body>small{display:flex;min-width:0;justify-content:space-between;gap:7px;font-size:.62rem}.history-site-option__body b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.history-workspace__main{min-width:0;min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable}
.history-trend-panel{border-bottom:1px solid var(--pt-border);background:rgba(var(--v-theme-surface-variant),.035)}
.history-trend-panel .history-pane-heading,.history-site-panel .history-pane-heading{border-bottom:0;padding-bottom:7px}
.history-chart-heading{align-items:flex-end}.history-line-chart{position:relative;height:260px;margin:0 14px 10px}.history-line-chart.is-loading{opacity:.48}.history-chart-note{padding:0 16px 10px;color:rgb(var(--v-theme-warning));font-size:.68rem}
.history-site-panel{min-width:0;padding-bottom:14px}
.history-site-panel .history-detail-shell{max-height:460px;overflow-x:hidden;overflow-y:auto;margin:0 14px;padding:0;border:1px solid var(--pt-border);border-radius:12px;scrollbar-gutter:stable}
.history-site-panel .history-detail-table{width:100%;min-width:0;table-layout:fixed}
.history-detail-table th:nth-child(1){width:18%}.history-detail-table th:nth-child(2),.history-detail-table th:nth-child(3){width:18%}.history-detail-table th:nth-child(4){width:11%}.history-detail-table th:nth-child(5){width:13%}.history-detail-table th:nth-child(6){width:10%}.history-detail-table th:nth-child(7){width:12%}
.history-site-row{cursor:pointer;transition:background-color .15s ease}.history-site-row:hover,.history-site-row:focus{background:rgba(var(--v-theme-primary),.07);outline:none}
.history-site-row .site-identity{min-width:0}.history-site-row .site-identity strong{min-width:0;overflow:hidden;text-overflow:ellipsis}.history-site-row .site-identity .v-icon{margin-left:auto;color:rgba(var(--v-theme-on-surface),.5)}
.history-record-shell{max-height:460px;overflow-x:hidden;overflow-y:auto;margin:0 14px 14px;border:1px solid var(--pt-border);border-radius:10px;background:rgba(var(--v-theme-surface),.42);scrollbar-gutter:stable}.history-record-table{width:100%;min-width:0;table-layout:fixed;background:transparent}.history-record-table th{color:rgba(var(--v-theme-on-surface),.55)!important;font-size:.62rem;white-space:nowrap}.history-record-table td{overflow:hidden;font-size:.66rem;text-overflow:ellipsis;white-space:nowrap}
.stacked-metric{display:block;overflow:hidden;font-size:.7rem;line-height:1.45;text-overflow:ellipsis;white-space:nowrap}
.site-data-list{display:grid;gap:12px}
.site-data-card{min-width:0;padding:16px;border:1px solid var(--pt-border);border-radius:16px;background:rgba(var(--v-theme-surface-variant),.12)}
.site-data-card__header{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;padding-bottom:12px;border-bottom:1px solid var(--pt-border)}
.site-data-card__header .site-identity>div{display:flex;flex-direction:column;min-width:0}
.site-data-card__header .site-identity span,.site-account-meta{color:rgba(var(--v-theme-on-surface),.56);font-size:.72rem}
.site-account-meta{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:7px}
.site-stat-grid{display:grid;grid-template-columns:repeat(10,minmax(0,1fr));gap:8px;margin-top:12px}
.site-stat-grid>div{display:flex;min-width:0;flex-direction:column;gap:4px;padding:10px 12px;border-radius:10px;background:rgba(var(--v-theme-surface),.54)}
.site-stat-grid span{color:rgba(var(--v-theme-on-surface),.52);font-size:.68rem}
.site-stat-grid strong{overflow-wrap:anywhere;font-size:.82rem}
.retirement-explorer{display:grid;grid-template-columns:minmax(240px,300px) minmax(0,1fr);align-items:start;min-height:0;overflow:visible;border:1px solid var(--pt-border);border-radius:18px;background:rgba(var(--v-theme-surface),.44)}
.retirement-site-list{display:flex;min-width:0;height:auto;min-height:0;flex-direction:column;padding:14px;border-right:1px solid var(--pt-border);background:rgba(var(--v-theme-surface-variant),.1)}
.retirement-site-list__heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:2px 4px 12px}
.retirement-site-list__heading span{color:rgba(var(--v-theme-on-surface),.52);font-size:.7rem}
.retirement-site-sort{width:100%;flex:0 0 auto;margin-bottom:10px}
.retirement-site-list__items{display:grid;align-content:start;gap:5px}
.retirement-site-option{appearance:none;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:10px;width:100%;padding:11px 10px;border:1px solid transparent;border-radius:12px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color .16s ease,border-color .16s ease}
.retirement-site-option:hover,.retirement-site-option:focus-visible{border-color:rgba(var(--v-theme-primary),.34);background:rgba(var(--v-theme-primary),.08);outline:none}
.retirement-site-option--selected{border-color:rgba(var(--v-theme-primary),.46);background:rgba(var(--v-theme-primary),.12)}
.retirement-site-option__body{display:grid;min-width:0;gap:4px}
.retirement-site-option__body>span:nth-child(2){overflow:hidden;color:rgba(var(--v-theme-on-surface),.58);font-size:.7rem;text-overflow:ellipsis;white-space:nowrap}
.retirement-site-option__title{display:flex;min-width:0;align-items:center;justify-content:space-between;gap:7px}
.retirement-site-option__title strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.retirement-site-option__title em{flex:0 0 auto;font-size:.66rem;font-style:normal;font-weight:700}
.retirement-site-option>small{color:rgba(var(--v-theme-on-surface),.52);font-size:.68rem;font-weight:700}
.status-wealthy_retired{color:#f5b942}.status-retired{color:rgb(var(--v-theme-success))}.status-upgrading{color:rgb(var(--v-theme-primary))}.status-rule_missing{color:rgb(var(--v-theme-warning))}
.retirement-detail{min-width:0;min-height:0;overflow:visible;padding:20px}
.retirement-detail__header{display:flex;align-items:center;justify-content:space-between;gap:24px;padding-bottom:18px;border-bottom:1px solid var(--pt-border)}
.retirement-detail__identity{display:flex;min-width:0;align-items:center;gap:14px}
.retirement-detail__identity>div{display:flex;min-width:0;flex-direction:column;gap:3px}
.retirement-detail__identity h3{margin:0;font-size:1.2rem}
.retirement-detail__identity span{color:rgba(var(--v-theme-on-surface),.58);font-size:.72rem}
.retirement-detail__identity span strong{color:rgba(var(--v-theme-on-surface),.86)}
.retirement-detail__identity .target-level{color:rgb(var(--v-theme-success))}
.retirement-detail__right{display:flex;flex-direction:column;align-items:flex-end;gap:10px}.wealthy-summary-chip,.wealthy-retirement-badge{background:linear-gradient(135deg,#744800,#e0a91f)!important;color:#fff5cb!important;font-weight:800;letter-spacing:.05em;box-shadow:0 7px 20px rgba(224,169,31,.2)}
.wealthy-selection-summary{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:16px;padding:12px 14px;border:1px solid var(--pt-border);border-radius:14px;background:rgba(var(--v-theme-surface-variant),.1)}.wealthy-selection-summary__sites{display:flex;min-width:0;align-items:center;gap:13px}.wealthy-selection-avatars{display:flex;flex:0 0 auto;padding-left:4px}.wealthy-selection-avatars :deep(.v-avatar){margin-left:-8px;border:2px solid rgb(var(--v-theme-surface));box-shadow:0 3px 10px rgba(0,0,0,.22)}.wealthy-selection-avatars :deep(.v-avatar:first-child){margin-left:0}.wealthy-selection-summary__copy{display:grid;min-width:0;gap:3px}.wealthy-selection-summary__copy strong{overflow:hidden;max-width:min(55vw,680px);font-size:.8rem;text-overflow:ellipsis;white-space:nowrap}.wealthy-selection-summary__copy small{color:rgba(var(--v-theme-on-surface),.54);font-size:.66rem}.wealthy-picker-dialog-card{max-height:min(82dvh,760px);border:1px solid var(--pt-border)!important;border-radius:20px!important}.wealthy-picker-dialog__header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px 20px 14px!important;border-bottom:1px solid var(--pt-border)}.wealthy-picker-dialog__header>div{display:grid;gap:3px}.wealthy-picker-dialog__header strong{font-size:1.05rem}.wealthy-picker-dialog__body{padding:16px 20px!important}.wealthy-picker-toolbar{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px}.wealthy-picker-status{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 2px 8px;color:rgba(var(--v-theme-on-surface),.7);font-size:.7rem}.wealthy-picker-status small{color:rgba(var(--v-theme-on-surface),.48)}.wealthy-site-picker{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.wealthy-site-card{appearance:none;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:11px;min-width:0;padding:11px 12px;border:1px solid var(--pt-border);border-radius:13px;background:rgba(var(--v-theme-surface-variant),.12);color:inherit;font:inherit;text-align:left;cursor:pointer;transition:border-color .16s ease,background-color .16s ease,box-shadow .16s ease}.wealthy-site-card:hover,.wealthy-site-card:focus-visible{border-color:rgba(224,169,31,.5);outline:none}.wealthy-site-card.is-selected{border-color:#d9a11c;background:linear-gradient(135deg,rgba(117,72,0,.24),rgba(224,169,31,.08));box-shadow:inset 3px 0 #d9a11c}.wealthy-site-card>span{display:grid;min-width:0;gap:3px}.wealthy-site-card strong,.wealthy-site-card small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wealthy-site-card strong{font-size:.78rem}.wealthy-site-card small{color:rgba(var(--v-theme-on-surface),.54);font-size:.64rem}.wealthy-site-card>.v-icon{color:rgba(var(--v-theme-on-surface),.32)}.wealthy-site-card.is-selected>.v-icon{color:#e0a91f}.wealthy-picker-dialog__actions{display:flex;justify-content:space-between!important;gap:14px;padding:12px 20px 18px!important;border-top:1px solid var(--pt-border)}.wealthy-picker-dialog__actions span{color:rgba(var(--v-theme-on-surface),.52);font-size:.68rem}
.retirement-site-option--wealthy{border-color:rgba(224,169,31,.34)}.retirement-site-option--wealthy.retirement-site-option--selected{border-color:#d9a11c;background:linear-gradient(135deg,rgba(117,72,0,.26),rgba(var(--v-theme-primary),.11))}.wealthy-retirement-state{display:flex;align-items:center;gap:15px;margin-top:24px;padding:18px 20px;border:1px solid rgba(224,169,31,.34);border-radius:16px;background:linear-gradient(135deg,rgba(117,72,0,.2),rgba(var(--v-theme-surface),.58))}.wealthy-retirement-state__icon{display:grid;flex:0 0 48px;place-items:center;width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#744800,#e0a91f);color:#fff5cb;box-shadow:0 8px 24px rgba(224,169,31,.2)}.wealthy-retirement-state>div:last-child{display:flex;min-width:0;flex-direction:column;gap:3px}.wealthy-retirement-state span{color:#d7b55d;font-size:.7rem;font-weight:700;letter-spacing:.08em}.wealthy-retirement-state strong{color:#fff1b5;font-size:1.08rem}.wealthy-retirement-state small{color:rgba(var(--v-theme-on-surface),.58);font-size:.72rem}
.retirement-detail__metrics{display:flex;flex:0 0 auto;align-items:center;gap:22px}
.retirement-detail__metrics span{display:flex;flex-direction:column;gap:3px;color:rgba(var(--v-theme-on-surface),.52);font-size:.68rem}
.retirement-detail__metrics strong{color:rgba(var(--v-theme-on-surface),.9);font-size:.86rem}
.retirement-route-rail{overflow-x:auto;padding:22px 12px 14px}
.retirement-route-rail__track{position:relative;min-width:860px}
.retirement-route-rail__line{position:absolute;z-index:0;top:23px;left:var(--route-inset);width:var(--route-span)}
.retirement-route-rail__nodes{position:relative;z-index:1;display:grid;grid-template-columns:repeat(var(--route-count),minmax(80px,1fr));align-items:start}
.retirement-route-node{appearance:none;display:grid;min-width:0;grid-template-rows:48px auto 24px;place-items:center;gap:5px;padding:0 5px;border:0;border-radius:12px;background:transparent;color:inherit;font:inherit;text-align:center;cursor:pointer}
.retirement-route-node:hover,.retirement-route-node:focus-visible{background:rgba(var(--v-theme-primary),.08);outline:none}
.retirement-route-node:focus-visible{box-shadow:inset 0 0 0 2px rgb(var(--v-theme-primary))}
.retirement-route-node__marker{position:relative;z-index:1;display:grid;width:38px;height:38px;place-items:center;border:4px solid rgba(var(--v-theme-on-surface),.32);border-radius:50%;background:rgb(var(--v-theme-surface));box-shadow:0 0 0 4px rgb(var(--v-theme-surface));color:rgba(var(--v-theme-on-surface),.82);font-size:.9rem;font-style:normal;font-weight:900}
.retirement-route-rail__nodes .is-reached .retirement-route-node__marker{border-color:rgb(var(--v-theme-primary));background:rgb(var(--v-theme-primary))}
.retirement-route-rail__nodes .is-next .retirement-route-node__marker{border-color:rgb(var(--v-theme-primary));background:rgba(var(--v-theme-primary),.34)}
.retirement-route-rail__nodes .is-current .retirement-route-node__marker,.retirement-route-rail__nodes .is-next .retirement-route-node__marker{box-shadow:0 0 0 4px rgb(var(--v-theme-surface)),0 0 0 7px rgba(var(--v-theme-primary),.18)}
.retirement-route-rail__nodes .is-retirement .retirement-route-node__marker{border-color:rgb(var(--v-theme-success));background:rgb(var(--v-theme-success))}
.retirement-route-rail__nodes .is-selected .retirement-route-node__marker{box-shadow:0 0 0 4px rgb(var(--v-theme-surface)),0 0 0 8px rgb(var(--v-theme-primary))}
.retirement-route-rail__nodes strong{max-width:100%;color:rgba(var(--v-theme-on-surface),.78);font-size:.7rem;line-height:1.2}
.retirement-route-node__name{display:grid;min-height:34px;align-content:start;place-items:center;gap:1px}.retirement-route-node__name>span{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.retirement-route-node__name>span+span{font-size:.66rem;text-transform:uppercase}
.retirement-route-node__badge{padding:2px 9px;border-radius:999px;background:rgba(var(--v-theme-on-surface),.1);color:rgba(var(--v-theme-on-surface),.68);font-size:.6rem;font-style:normal;font-weight:800;line-height:16px;white-space:nowrap}
.retirement-route-rail__nodes .is-current strong,.retirement-route-rail__nodes .is-current .retirement-route-node__badge{color:rgb(var(--v-theme-primary))}
.retirement-route-rail__nodes .is-next strong,.retirement-route-rail__nodes .is-next .retirement-route-node__badge{color:rgb(var(--v-theme-primary))}
.retirement-route-rail__nodes .is-retirement strong,.retirement-route-rail__nodes .is-retirement .retirement-route-node__badge{color:rgb(var(--v-theme-success))}
.retirement-route-rail__nodes .is-current .retirement-route-node__badge,.retirement-route-rail__nodes .is-next .retirement-route-node__badge{background:rgba(var(--v-theme-primary),.16)}
.retirement-route-rail__nodes .is-retirement .retirement-route-node__badge{background:rgba(var(--v-theme-success),.12)}
.retirement-target-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;margin-top:16px}
.requirement-panel,.retirement-levels{min-width:0;border:1px solid var(--pt-border);border-radius:14px;background:rgba(var(--v-theme-surface-variant),.1)}
.requirement-panel{padding:15px}
.requirement-panel__heading{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;padding-bottom:14px;border-bottom:1px solid var(--pt-border)}
.requirement-panel__heading>div:first-child{display:flex;align-items:center;gap:9px}
.requirement-panel__heading span{color:rgba(var(--v-theme-on-surface),.56);font-size:.72rem}
.requirement-panel__heading strong{margin-left:3px;font-size:1.22rem}
.requirement-panel__spacer{min-width:0}
.spring-upgrade-tasks{display:grid;grid-template-columns:repeat(2,minmax(140px,1fr));justify-self:center;gap:8px}.spring-upgrade-task{appearance:none;display:flex;align-items:center;justify-content:center;gap:8px;min-width:140px;padding:8px 12px;border:1px solid var(--pt-border);border-radius:12px;background:rgba(var(--v-theme-surface-variant),.12);color:rgba(var(--v-theme-on-surface),.62);font:inherit;text-align:left;cursor:pointer;transition:border-color .16s ease,background-color .16s ease,color .16s ease,box-shadow .16s ease}.spring-upgrade-task:hover,.spring-upgrade-task:focus-visible{border-color:rgba(var(--v-theme-primary),.48);outline:none}.spring-upgrade-task.is-selected{border-color:rgb(var(--v-theme-primary));background:rgba(var(--v-theme-primary),.14);color:rgb(var(--v-theme-primary));box-shadow:0 5px 16px rgba(var(--v-theme-primary),.12)}.spring-upgrade-task>span{display:grid;gap:1px;color:inherit}.requirement-panel__heading .spring-upgrade-task strong{margin:0;color:inherit;font-size:.72rem;line-height:1.1}.spring-upgrade-task small{color:rgba(var(--v-theme-on-surface),.58);font-size:.61rem;line-height:1.25;overflow-wrap:anywhere}.spring-upgrade-task.is-selected small{color:rgba(var(--v-theme-primary),.82)}
@media(max-width:1100px){.requirement-panel__heading{grid-template-columns:minmax(0,1fr) auto}.spring-upgrade-tasks{grid-column:1/-1;grid-row:2}.requirement-panel__spacer{display:none}}
@media(max-width:420px){.spring-upgrade-tasks{grid-template-columns:1fr}}
.requirement-overview{display:grid;grid-template-columns:190px minmax(0,1fr);gap:20px;padding-top:14px}
.requirement-overview__score{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;border-right:1px solid var(--pt-border)}
.requirement-overview__score :deep(.v-progress-circular__content)>strong{font-size:1.35rem}
.requirement-overview__score>span{margin-top:2px;color:rgba(var(--v-theme-on-surface),.56);font-size:.68rem}
.requirement-overview__score>b{font-size:1.25rem}
.requirement-overview__score>small{color:rgba(var(--v-theme-on-surface),.54);font-size:.64rem}
.requirement-table{min-width:0}
.requirement-table__head,.requirement-row{display:grid;grid-template-columns:minmax(110px,.82fr) minmax(100px,.68fr) minmax(105px,.7fr) minmax(95px,.62fr) minmax(105px,.68fr) minmax(180px,1.18fr);align-items:center;gap:12px}
.requirement-table__head{padding:7px 10px;color:rgba(var(--v-theme-on-surface),.58);font-size:.65rem}
.requirement-row{min-height:42px;padding:8px 10px;border-top:1px solid var(--pt-border);font-size:.7rem}
.requirement-row__item{display:flex;align-items:center;gap:10px}
.requirement-row__progress{display:grid;grid-template-columns:minmax(90px,1fr) 38px;align-items:center;gap:9px}
.requirement-row__progress b{text-align:right}
.compact-empty-state{display:grid;min-height:88px;place-items:center;color:rgba(var(--v-theme-on-surface),.5);font-size:.76rem}
.retirement-levels{margin-top:14px;overflow:hidden}
.retirement-levels__heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 20px}
.retirement-levels__heading>div{display:flex;align-items:center;gap:8px}
.retirement-levels__table{min-width:760px}
.retirement-levels__columns,.retirement-level-row summary{display:grid;grid-template-columns:minmax(125px,1fr) minmax(95px,.75fr) minmax(190px,1.4fr) minmax(95px,.7fr) minmax(125px,.9fr) 24px;align-items:center;gap:14px;padding:13px 20px}
.retirement-levels__columns{background:rgba(var(--v-theme-primary),.09);color:rgba(var(--v-theme-on-surface),.64);font-size:.72rem}
.retirement-level-row{overflow:hidden;border-top:1px solid var(--pt-border);background:transparent}
.retirement-level-row[open]{background:rgba(var(--v-theme-primary),.055);box-shadow:inset 3px 0 rgb(var(--v-theme-primary))}
.retirement-level-row summary{position:relative;min-height:64px;cursor:default;list-style:none;font-size:.78rem}
.retirement-level-row.has-detail summary{cursor:pointer}
.retirement-level-row summary::-webkit-details-marker{display:none}
.retirement-level-row summary>strong{font-size:.82rem}
.retirement-level-row summary>span{color:rgba(var(--v-theme-on-surface),.68)}
.retirement-level-row__traffic{display:grid;gap:3px}
.retirement-level-row summary>.v-icon{transition:transform .18s ease}
.retirement-level-row[open] summary>.v-icon{transform:rotate(180deg)}
.retirement-level-row__detail{display:grid;gap:20px;padding:22px 28px 24px 36px;border-top:1px solid var(--pt-border);color:rgba(var(--v-theme-on-surface),.76);font-size:.76rem}
.retirement-level-row__detail.has-alternatives{grid-template-columns:minmax(0,1fr) minmax(0,1.05fr)}
.retirement-level-row__description,.retirement-level-row__alternatives{min-width:0}
.retirement-level-row__alternatives{padding-left:22px;border-left:1px solid var(--pt-border)}
.retirement-level-row__detail-title{display:flex;align-items:center;gap:9px;color:rgba(var(--v-theme-on-surface),.94);font-size:.86rem}
.retirement-level-row__detail-title>.v-icon{color:rgb(var(--v-theme-primary))}
.retirement-level-row__description p,.retirement-level-row__alternatives p{margin:11px 0 0;line-height:1.7;overflow-wrap:anywhere}
.retirement-level-row__tasks{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:10px;margin-top:14px}
.retirement-level-row__task{display:grid;align-content:start;gap:5px;min-width:0;padding:12px 14px;border:1px solid var(--pt-border);border-radius:10px;background:rgba(var(--v-theme-surface),.25);line-height:1.45}
.retirement-level-row__task>strong{margin-bottom:3px;color:rgba(var(--v-theme-on-surface),.95)}
.retirement-level-row__task>span{overflow-wrap:anywhere}
.pt-workbench{--pt-border:rgba(var(--v-border-color),var(--v-border-opacity));min-width:0;padding:4px}.retirement-summary{display:flex;flex-wrap:wrap;gap:9px}.section-block{margin-top:16px;padding:20px;border:1px solid var(--pt-border);border-radius:20px;background:rgba(var(--v-theme-surface),.7)}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}.section-heading h2{margin:2px 0 0;font-size:1.18rem}.section-kicker{color:rgb(var(--v-theme-primary));font-size:.72rem;font-weight:800;letter-spacing:.12em}.section-note,.setting-hint,.row-label{color:rgba(var(--v-theme-on-surface),.56);font-size:.76rem}.metric-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}.distribution-panel,.twelve-panel{background:linear-gradient(135deg,rgba(var(--v-theme-primary),.07),rgba(var(--v-theme-surface),.72))}.distribution-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.distribution-card{min-width:0;padding:18px;border:1px solid var(--pt-border);border-radius:17px;background:rgba(var(--v-theme-surface),.55)}.distribution-card__header{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px}.distribution-card__header :deep(.v-input){max-width:190px}.pie-layout{display:grid;grid-template-columns:minmax(150px,40%) minmax(0,1fr);gap:20px;align-items:center}.pie{display:grid;place-items:center;width:min(100%,220px);margin:auto;aspect-ratio:1;border-radius:50%;box-shadow:0 12px 32px rgba(0,0,0,.15)}.pie__hole{display:flex;flex-direction:column;align-items:center;justify-content:center;width:66%;aspect-ratio:1;border-radius:50%;background:rgb(var(--v-theme-surface));text-align:center}.pie__hole span{color:rgba(var(--v-theme-on-surface),.58);font-size:.68rem}.pie__hole strong{margin-top:5px;font-size:1rem}.pie-legend{max-height:250px;overflow-y:auto}.pie-legend>div{display:grid;grid-template-columns:9px minmax(80px,1fr) auto auto;gap:8px;align-items:center;padding:6px 2px;font-size:.74rem}.pie-legend i{width:8px;height:8px;border-radius:50%}.pie-legend strong{font-size:.72rem}.pie-legend em{color:rgba(var(--v-theme-on-surface),.5);font-style:normal}.table-shell,.twelve-overflow{overflow-x:auto;border:1px solid var(--pt-border);border-radius:14px}.site-table{min-width:1450px;background:transparent}.history-detail-shell{overflow-x:auto}.history-detail-table{min-width:1050px}.site-table th{color:rgba(var(--v-theme-on-surface),.55)!important;font-size:.7rem;letter-spacing:.04em;white-space:nowrap}.site-table td{white-space:nowrap}.site-identity{display:flex;align-items:center;gap:10px}.cell-sub{display:block;max-width:220px;overflow:hidden;color:rgba(var(--v-theme-on-surface),.52);font-size:.68rem;text-overflow:ellipsis;white-space:nowrap}.metric-upload{color:rgb(var(--v-theme-success));font-weight:650}.metric-download{color:rgb(var(--v-theme-error));font-weight:650}.empty-cell{height:140px!important;text-align:center;color:rgba(var(--v-theme-on-surface),.52)}.legend{display:flex;flex:0 0 auto;align-items:center;gap:14px;color:rgba(var(--v-theme-on-surface),.62);font-size:.75rem;white-space:nowrap}.legend>span{display:inline-flex;align-items:center;gap:5px;line-height:1}.legend i{display:block;flex:0 0 9px;width:9px;height:9px;border-radius:2px}.legend__upload{background:rgb(var(--v-theme-success))}.legend__download{background:rgb(var(--v-theme-error))}.bar-chart{display:flex;align-items:stretch;gap:5px;height:250px;overflow-x:auto;padding:10px 3px 0;border-bottom:1px solid var(--pt-border)}.bar-column{display:flex;flex:1 0 28px;flex-direction:column;min-width:28px}.bar-column__bars{display:flex;flex:1;align-items:flex-end;justify-content:center;gap:2px}.bar{display:block;width:7px;border-radius:5px 5px 1px 1px}.bar--upload{background:rgb(var(--v-theme-success))}.bar--download{background:rgb(var(--v-theme-error))}.empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;min-height:180px;color:rgba(var(--v-theme-on-surface),.54)}.compact-empty{min-height:120px}.twelve-track{position:relative;display:grid;grid-template-columns:repeat(12,minmax(54px,1fr));min-width:760px;padding:20px 4px 4px}.twelve-track__line{position:absolute;z-index:0;top:38px;left:4.2%;right:4.2%;height:5px;overflow:hidden;border-radius:999px;background:rgba(var(--v-theme-on-surface),.12)}.twelve-track__line i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,rgb(var(--v-theme-primary)),rgb(var(--v-theme-success)))}.twelve-node{z-index:1;display:flex;flex-direction:column;align-items:center;gap:8px;min-width:0;text-align:center}.twelve-node span{max-width:100%;overflow:hidden;font-size:.72rem;text-overflow:ellipsis;white-space:nowrap}.twelve-node--missing,.twelve-node--waiting{opacity:.66}.settings-layout{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;border:0;padding:0;background:transparent}.settings-card{padding:20px;border:1px solid var(--pt-border);border-radius:18px;background:rgba(var(--v-theme-surface),.76)}.settings-card--wide{grid-column:1/-1}.settings-actions{display:flex;align-items:center;justify-content:space-between;gap:20px}.settings-actions p{margin:4px 0 0;color:rgba(var(--v-theme-on-surface),.56)}
.rules-file-input{display:none}.rules-upload{display:flex;align-items:center;justify-content:space-between;gap:20px}.rules-upload>div:first-child{display:grid;min-width:0;gap:5px}.rules-upload p{max-width:760px;margin:0;color:rgba(var(--v-theme-on-surface),.62);overflow-wrap:anywhere}.rules-upload small{color:rgba(var(--v-theme-on-surface),.48)}.rules-upload__actions{display:flex;flex:0 0 auto;flex-wrap:wrap;justify-content:flex-end;gap:8px}
.twelve-panel{padding:18px 22px 14px}
.twelve-panel__heading{align-items:flex-start;margin-bottom:0}
.twelve-panel__heading h2{font-size:1.42rem;letter-spacing:-.025em}
.twelve-summary{display:flex;align-items:center;gap:24px;padding:2px 4px 0}
.twelve-summary>div{display:grid;grid-template-columns:auto auto;align-items:baseline;column-gap:7px}
.twelve-summary strong{font-size:2rem;line-height:1}
.twelve-summary span{color:rgba(var(--v-theme-on-surface),.48);font-size:1.25rem;font-weight:750}
.twelve-summary small{grid-column:1/-1;margin-top:7px;color:rgba(var(--v-theme-on-surface),.52);font-size:.7rem}
.twelve-summary>i{width:1px;height:42px;background:var(--pt-border)}
.twelve-overflow{position:relative;overflow-x:auto;padding:20px 12px 4px;border:0;border-radius:0}
.twelve-track{grid-template-columns:repeat(12,minmax(70px,1fr));min-width:920px;padding:0 0 12px}
.twelve-track__line{top:39px;left:4.15%;right:4.15%;height:4px}
.twelve-node{position:relative;display:grid;grid-template-rows:18px 46px 20px;place-items:center;gap:3px}
.twelve-node__index{color:rgba(var(--v-theme-on-surface),.64);font-size:.68rem;font-weight:750;line-height:1}
.twelve-node__marker{position:relative;z-index:1;display:grid;width:46px;height:46px;place-items:center;border:3px solid rgba(var(--v-theme-on-surface),.2);border-radius:50%;background:rgb(var(--v-theme-surface));box-shadow:0 0 0 5px rgb(var(--v-theme-surface))}
.twelve-node--joined .twelve-node__marker{border-color:rgb(var(--v-theme-primary));box-shadow:0 0 0 5px rgb(var(--v-theme-surface)),0 0 18px rgba(var(--v-theme-primary),.35)}
.twelve-node--missing .twelve-node__marker,.twelve-node--waiting .twelve-node__marker{opacity:.72}
.twelve-node__name{max-width:100%;overflow:hidden;font-size:.75rem;text-overflow:ellipsis;white-space:nowrap}
.twelve-node--missing .twelve-node__name,.twelve-node--waiting .twelve-node__name{display:none}
.twelve-remaining{display:flex;justify-content:flex-end;gap:4px;min-width:920px;color:rgba(var(--v-theme-on-surface),.52);font-size:.7rem}
.twelve-remaining strong{color:rgb(var(--v-theme-success));font-size:.8rem}
.pt-workbench--compact .retirement-explorer{grid-template-columns:1fr;height:auto;min-height:0;overflow:visible}
.pt-workbench--compact .retirement-site-list{position:static;max-height:none;overflow:visible;border-right:0;border-bottom:1px solid var(--pt-border)}
.pt-workbench--compact .retirement-site-list__items{display:flex;max-height:none;overflow-x:auto;overflow-y:hidden;scrollbar-gutter:auto}
.pt-workbench--compact .retirement-site-option{width:245px;flex:0 0 245px}
.pt-workbench--compact .retirement-detail{min-width:0;overflow:visible;scrollbar-gutter:auto}
.pt-workbench--compact .requirement-overview{grid-template-columns:1fr}
.pt-workbench--compact .requirement-overview__score{border-right:0;border-bottom:1px solid var(--pt-border);padding-bottom:14px}
.pt-workbench--compact .requirement-table,.pt-workbench--compact .retirement-levels{max-width:100%;overflow-x:auto;overflow-y:hidden;overscroll-behavior-x:contain}
.pt-workbench--compact .requirement-table__head,.pt-workbench--compact .requirement-row{min-width:840px}
@media(max-width:1280px){.metric-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.site-stat-grid{grid-template-columns:repeat(5,minmax(0,1fr))}.retirement-target-grid{grid-template-columns:1fr}}
@media(max-width:960px){.workbench-nav{align-items:stretch;flex-direction:column;gap:5px}.workbench-nav__actions{align-self:flex-end;padding-bottom:10px}.history-workspace{grid-template-columns:1fr;height:auto;overflow:visible}.history-site-sidebar{overflow:visible;border-right:0;border-bottom:1px solid var(--pt-border)}.history-site-sidebar__items{display:flex;max-height:none;overflow-x:auto;overflow-y:hidden;scrollbar-gutter:auto}.history-site-option{width:210px;flex:0 0 210px}.history-workspace__main{overflow:visible;scrollbar-gutter:auto}.history-record-shell{overflow-x:auto}.history-record-table{min-width:900px;table-layout:auto}.distribution-grid{grid-template-columns:1fr}.retirement-explorer{grid-template-columns:1fr;height:auto;min-height:0;overflow:visible}.retirement-site-list{overflow:visible;border-right:0;border-bottom:1px solid var(--pt-border)}.retirement-site-list__items{display:flex;max-height:none;overflow-x:auto;overflow-y:hidden;scrollbar-gutter:auto}.retirement-site-option{width:245px;flex:0 0 245px}.retirement-detail{overflow:visible;scrollbar-gutter:auto}.requirement-overview{grid-template-columns:1fr}.requirement-overview__score{border-right:0;border-bottom:1px solid var(--pt-border);padding-bottom:14px}.requirement-table,.retirement-levels{overflow-x:auto}}
.ptd-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}.ptd-receiver-url{grid-column:1/-1}
@media(max-width:720px){.workbench-nav__actions{align-self:stretch}.section-block{padding:14px}.metric-grid,.settings-layout,.ptd-settings-grid{grid-template-columns:1fr}.ptd-receiver-url{grid-column:auto}.settings-card--wide{grid-column:auto}.settings-actions{align-items:stretch;flex-direction:column}.section-heading,.distribution-heading{align-items:flex-start;flex-direction:column}.pie-layout{grid-template-columns:1fr}.pie{width:180px}.history-detail-summary{align-items:flex-start;flex-direction:column}.history-detail-metrics{width:100%;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.history-period-card{min-width:142px}.history-line-chart{height:220px}.history-site-panel .history-detail-shell{overflow-x:auto}.history-site-panel .history-detail-table{min-width:720px}}
@media(max-width:720px){.site-sort-select{width:100%;flex:0 0 auto}.site-data-card{padding:12px}.site-data-card__header,.site-account-meta{align-items:flex-start;flex-direction:column}.site-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.retirement-detail{padding:14px}.retirement-detail__header{align-items:flex-start;flex-direction:column}.retirement-detail__metrics{width:100%;justify-content:space-between;gap:10px}.retirement-route-rail{margin-right:-14px;margin-left:-14px;padding-right:14px;padding-left:14px}.requirement-panel__heading{grid-template-columns:1fr;align-items:flex-start}.requirement-panel__heading>div:first-child{flex-wrap:wrap}.spring-upgrade-tasks{width:100%;justify-self:stretch}.spring-upgrade-task{min-width:0}.requirement-table__head,.requirement-row{min-width:840px}.retirement-levels__heading{align-items:flex-start;flex-direction:column}}
@media(max-width:720px){.retirement-detail__right{width:100%;align-items:flex-start}}
@media(max-width:720px){.wealthy-selection-summary{align-items:stretch;flex-direction:column}.wealthy-selection-summary>.v-btn{width:100%}.wealthy-selection-summary__copy strong{max-width:calc(100vw - 150px)}.wealthy-picker-dialog-card{max-height:88dvh;border-radius:20px 20px 0 0!important}.wealthy-picker-toolbar{grid-template-columns:1fr}.wealthy-picker-toolbar>.v-btn{justify-self:end}.wealthy-site-picker{grid-template-columns:1fr}.wealthy-picker-dialog__header,.wealthy-picker-dialog__body{padding-right:14px!important;padding-left:14px!important}.wealthy-picker-dialog__actions{align-items:stretch;flex-direction:column;padding-right:14px!important;padding-left:14px!important}.wealthy-picker-dialog__actions>.v-btn{width:100%}}
@media(max-width:720px){.rules-upload{align-items:flex-start;flex-direction:column}.rules-upload__actions{width:100%;justify-content:flex-start}}
@media(max-width:960px){.retirement-site-list{position:static;max-height:none}.twelve-panel{padding:18px}.twelve-panel__heading{align-items:flex-start;flex-direction:column}.twelve-summary{width:100%;justify-content:flex-end}}
@media(max-width:760px){
  .retirement-levels{overflow-x:hidden}
  .retirement-levels__table{min-width:0}
  .retirement-levels__columns{display:none}
  .retirement-level-row summary{grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:12px;min-height:0;padding:15px 16px}
  .retirement-level-row summary>strong{grid-column:1/-1;padding-right:26px;font-size:.9rem}
  .retirement-level-row summary>span{display:grid;gap:4px;min-width:0}
  .retirement-level-row summary>span::before{content:attr(data-label);color:rgba(var(--v-theme-on-surface),.5);font-size:.66rem}
  .retirement-level-row summary>.v-icon{position:absolute;top:16px;right:16px}
  .retirement-level-row__detail,.retirement-level-row__detail.has-alternatives{grid-template-columns:1fr;gap:18px;padding:16px}
  .retirement-level-row__alternatives{padding:18px 0 0;border-top:1px solid var(--pt-border);border-left:0}
  .retirement-level-row__tasks{grid-template-columns:1fr}
}
.pt-workbench--compact .retirement-levels{overflow-x:hidden;overflow-y:visible}
.pt-workbench--compact .retirement-levels__table{min-width:0}
.pt-workbench--compact .retirement-levels__columns{display:none}
.pt-workbench--compact .retirement-level-row summary{grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:12px;min-height:0;padding:15px 16px}
.pt-workbench--compact .retirement-level-row summary>strong{grid-column:1/-1;padding-right:26px;font-size:.9rem}
.pt-workbench--compact .retirement-level-row summary>span{display:grid;gap:4px;min-width:0}
.pt-workbench--compact .retirement-level-row summary>span::before{content:attr(data-label);color:rgba(var(--v-theme-on-surface),.5);font-size:.66rem}
.pt-workbench--compact .retirement-level-row summary>.v-icon{position:absolute;top:16px;right:16px}
.pt-workbench--compact .retirement-level-row__detail,.pt-workbench--compact .retirement-level-row__detail.has-alternatives{grid-template-columns:1fr;gap:18px;padding:16px}
.pt-workbench--compact .retirement-level-row__alternatives{padding:18px 0 0;border-top:1px solid var(--pt-border);border-left:0}
.pt-workbench--compact .retirement-level-row__tasks{grid-template-columns:1fr}
</style>
