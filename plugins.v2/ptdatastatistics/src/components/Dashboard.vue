<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import SiteAvatar from './SiteAvatar.vue'
import { formatBytes, unwrapResponse } from '../utils'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  config: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'PTDataStatistics' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
  allowRefresh: { type: Boolean, default: true },
})

const loading = ref(false)
const overview = ref({
  server_date: '',
  summary: {},
  today_sites: [],
})
let refreshTimer

const pluginBase = computed(() => `plugin/${props.pluginId || 'PTDataStatistics'}`)
const sites = computed(() => overview.value.today_sites || [])
const dashboardColors = [
  '#52d000', '#29a8e8', '#f59e0b', '#8b5cf6',
  '#22d3ee', '#fb7185', '#60a5fa', '#a78bfa',
  '#2dd4bf', '#f97316', '#e879f9', '#38bdf8',
]

const donutBackground = computed(() => {
  if (!sites.value.length) return 'conic-gradient(rgba(var(--v-theme-on-surface), .1) 0 100%)'
  let offset = 0
  const stops = sites.value.map((site, index) => {
    const start = offset
    offset += Number(site.contribution || 0)
    return `${dashboardColors[index % dashboardColors.length]} ${start}% ${Math.min(offset, 100)}%`
  })
  if (offset < 100) stops.push(`rgba(var(--v-theme-on-surface), .1) ${offset}% 100%`)
  return `conic-gradient(${stops.join(', ')})`
})

async function loadOverview() {
  if (!props.allowRefresh && overview.value.server_date) return
  loading.value = true
  try {
    const data = await props.api.get(`${pluginBase.value}/overview`, { feedback: 'silent' })
    overview.value = unwrapResponse(data) || overview.value
  } finally {
    loading.value = false
  }
}

watch(() => props.allowRefresh, enabled => enabled && loadOverview())

onMounted(() => {
  loadOverview()
  refreshTimer = window.setInterval(loadOverview, 60000)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <VCard class="pt-dashboard dashboard-grid-fill">
    <header class="pt-dashboard__heading">
      <div class="pt-dashboard__title">
        <VIcon class="pt-dashboard__title-icon" icon="mdi-finance" size="24" color="warning" />
        <strong>今日流量</strong>
      </div>
      <span>今天 00:00 起</span>
    </header>

    <VProgressLinear v-if="loading" indeterminate color="primary" height="2" />

    <div v-if="sites.length" class="pt-dashboard__body">
      <div class="donut-wrap">
        <div class="donut" :style="{ background: donutBackground }">
          <div class="donut__hole">
            <strong>{{ sites.length }}</strong>
            <span>个站点</span>
          </div>
        </div>
      </div>

      <div class="pt-dashboard__details">
        <div class="pt-dashboard__totals">
          <div class="total-pill">
            <VIcon class="total-pill__icon" icon="mdi-calendar-blank-outline" size="20" />
            <span>统计时间</span>
            <strong>{{ overview.server_date || '暂无' }}</strong>
          </div>
          <div class="total-pill total-pill--upload">
            <VIcon class="total-pill__icon" icon="mdi-arrow-up" size="20" />
            <span>上传增量</span>
            <strong>{{ formatBytes(overview.summary.today_upload) }}</strong>
          </div>
          <div class="total-pill total-pill--download">
            <VIcon class="total-pill__icon" icon="mdi-arrow-down" size="20" />
            <span>下载增量</span>
            <strong>{{ formatBytes(overview.summary.today_download) }}</strong>
          </div>
        </div>

        <div class="site-list" tabindex="0" aria-label="今日站点流量列表">
          <div v-for="(site, index) in sites" :key="site.site_id || site.site_name" class="site-row">
            <div class="site-row__identity">
              <SiteAvatar :api="api" :site="site" :size="30" />
              <strong>{{ site.site_name }}</strong>
            </div>
            <div class="site-row__metric site-row__metric--upload">
              <VIcon icon="mdi-arrow-up" size="16" />
              <span>{{ formatBytes(site.daily_upload) }}</span>
            </div>
            <div class="site-row__metric site-row__metric--download">
              <VIcon icon="mdi-arrow-down" size="16" />
              <span>{{ formatBytes(site.daily_download) }}</span>
            </div>
            <div class="site-row__share">
              <i :style="{ backgroundColor: dashboardColors[index % dashboardColors.length] }" />
              <span>{{ Number(site.contribution || 0).toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="pt-dashboard__empty">
      <VIcon icon="mdi-chart-donut-variant" size="48" color="secondary" />
      <strong>今日暂无站点流量</strong>
      <span>仅显示今日上传或下载大于零、且基线有效的站点</span>
    </div>
  </VCard>
</template>

<style scoped>
.pt-dashboard {
  display: flex;
  flex-direction: column;
  inline-size: 100%;
  block-size: 100%;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  container-type: inline-size;
  background: rgb(var(--v-theme-surface));
  padding: 12px;
}

.pt-dashboard__heading {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 74px;
  padding: 0 2px;
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.pt-dashboard__heading > span {
  color: rgba(var(--v-theme-on-surface), .78);
  font-size: .82rem;
  white-space: nowrap;
}

.pt-dashboard__title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.pt-dashboard__title-icon {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: rgba(43, 67, 88, .9);
}

.pt-dashboard__title strong {
  overflow: hidden;
  font-size: 1.25rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pt-dashboard__totals {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: clamp(8px, 1.5cqi, 16px);
}

.total-pill {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas: 'icon label' 'icon value';
  align-items: center;
  column-gap: 14px;
  min-height: 80px;
  padding: 9px 20px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 999px;
  background: rgba(var(--v-theme-on-surface), .04);
  box-shadow: inset 0 1px 0 rgba(var(--v-theme-on-surface), .06), 0 8px 22px rgba(0, 0, 0, .08);
  backdrop-filter: blur(16px) saturate(125%);
  -webkit-backdrop-filter: blur(16px) saturate(125%);
  min-width: 0;
}

.total-pill__icon {
  grid-area: icon;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: rgba(var(--v-theme-surface-variant), .42);
  color: rgb(var(--v-theme-on-surface)) !important;
}
.total-pill span { grid-area: label; font-size: .8rem; font-weight: 600; color: rgb(var(--v-theme-on-surface)); }
.total-pill strong { grid-area: value; overflow: hidden; color: rgb(var(--v-theme-on-surface)); font-size: 1.12rem; font-weight: 700; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }

.pt-dashboard__body {
  display: grid;
  grid-template-columns: minmax(180px, .7fr) minmax(0, 2.3fr);
  align-items: center;
  gap: clamp(18px, 3cqi, 38px);
  min-height: 0;
  flex: 1 1 auto;
  padding-top: clamp(20px, 2.6cqi, 30px);
}

.donut-wrap {
  display: grid;
  place-items: center start;
  min-width: 0;
  transform: translateY(-14px);
}

.donut {
  display: grid;
  place-items: center;
  width: min(100%, 210px);
  aspect-ratio: 1;
  border-radius: 50%;
  box-shadow: 0 12px 32px rgba(0, 0, 0, .16);
}

.donut__hole {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 72%;
  aspect-ratio: 1;
  border-radius: 50%;
  background: color-mix(in srgb, #52d000 38%, rgb(var(--v-theme-surface)));
}

.donut__hole strong { font-size: 2rem; line-height: 1; font-variant-numeric: tabular-nums; }
.donut__hole span { margin-top: 6px; font-size: .8rem; color: rgba(var(--v-theme-on-surface), .68); }

.pt-dashboard__details,
.site-list {
  min-width: 0;
  min-height: 0;
}

.pt-dashboard__details {
  display: flex;
  flex-direction: column;
  align-self: stretch;
  justify-content: flex-start;
  gap: clamp(16px, 2cqi, 22px);
}

.site-list {
  display: grid;
  grid-auto-rows: 90px;
  align-content: start;
  flex: 1 1 auto;
  gap: 14px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 3px;
  scrollbar-color: rgba(var(--v-theme-on-surface), .28) transparent;
  scrollbar-width: thin;
}

.site-list::-webkit-scrollbar { width: 5px; }
.site-list::-webkit-scrollbar-track { background: transparent; }
.site-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(var(--v-theme-on-surface), .28);
}

.site-row {
  display: grid;
  grid-template-columns: minmax(110px, 1fr) 126px 126px 80px;
  column-gap: 14px;
  align-items: center;
  height: 90px;
  padding: 12px 20px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 14px;
  background: rgba(var(--v-theme-on-surface), .04);
  box-shadow: inset 0 1px 0 rgba(var(--v-theme-on-surface), .06), 0 10px 26px rgba(0, 0, 0, .08);
}

.site-row__identity,
.site-row__metric,
.site-row__share {
  display: flex;
  align-items: center;
  min-width: 0;
}

.site-row__identity { gap: 10px; }
.site-row__identity strong { overflow: hidden; color: rgb(var(--v-theme-on-surface)); font-size: 1rem; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.site-row__metric {
  justify-self: end;
  justify-content: center;
  gap: 5px;
  width: 126px;
  min-height: 34px;
  padding: 5px 12px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 999px;
  background: rgba(var(--v-theme-on-surface), .025);
  color: rgb(var(--v-theme-on-surface));
  font-size: .8rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.site-row__metric span { color: rgb(var(--v-theme-on-surface)); font-weight: 700; }
.site-row__metric--download { color: rgb(var(--v-theme-on-surface)); }
.site-row__share {
  justify-self: end;
  justify-content: center;
  gap: 6px;
  width: 80px;
  min-height: 28px;
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(var(--v-theme-on-surface), .08);
  font-size: .78rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.site-row__share i { width: 8px; height: 8px; border-radius: 50%; }

.pt-dashboard__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  color: rgba(var(--v-theme-on-surface), .64);
}

.pt-dashboard__empty strong { color: rgb(var(--v-theme-on-surface)); }

@container (max-width: 820px) {
  .pt-dashboard { padding: 8px; }
  .pt-dashboard__heading { min-height: 56px; }
  .pt-dashboard__heading > span { font-size: .68rem; }
  .pt-dashboard__title { gap: 7px; }
  .pt-dashboard__title-icon { width: 28px; height: 28px; }
  .pt-dashboard__title strong { font-size: .95rem; }
  .pt-dashboard__body {
    grid-template-columns: minmax(130px, .62fr) minmax(0, 2.38fr);
    gap: 12px;
    padding-top: 12px;
  }
  .donut { width: min(100%, 140px); }
  .donut__hole strong { font-size: 1.55rem; }
  .donut__hole span { font-size: .68rem; }
  .pt-dashboard__details { gap: 10px; }
  .pt-dashboard__totals { gap: 6px; }
  .total-pill {
    min-height: 52px;
    padding: 5px 8px;
    column-gap: 6px;
  }
  .total-pill__icon { width: 26px; height: 26px; }
  .total-pill span { font-size: .7rem; }
  .total-pill strong { font-size: .82rem; }
  .site-list { grid-auto-rows: 60px; gap: 8px; }
  .site-row {
    grid-template-columns: minmax(70px, 1fr) repeat(2, minmax(68px, .82fr)) minmax(52px, .58fr);
    column-gap: 6px;
    height: 60px;
    padding: 6px 8px;
  }
  .site-row__identity { gap: 6px; }
  .site-row__identity :deep(.v-avatar) { width: 22px !important; height: 22px !important; }
  .site-row__identity strong { font-size: .82rem; }
  .site-row__metric {
    width: 100%;
    min-height: 24px;
    padding: 3px 5px;
    font-size: .66rem;
  }
  .site-row__share {
    width: 100%;
    min-width: 0;
    min-height: 22px;
    padding: 2px 4px;
    font-size: .64rem;
  }
}

@container (max-width: 480px) {
  /* Dashboard grid cells can have a fixed height on mobile as well. */
  .pt-dashboard__body {
    grid-template-columns: 1fr;
    align-content: start;
    overflow-y: auto;
    overscroll-behavior-y: contain;
  }
  .donut-wrap { place-items: center; transform: none; }
  .donut { width: min(42cqi, 170px); }
  .pt-dashboard__details { width: 100%; }
  .site-list { grid-auto-rows: auto; overflow-y: visible; padding-right: 0; }
  .site-row { height: auto; min-height: 60px; }
}

@container (max-width: 380px) {
  .pt-dashboard__totals { grid-template-columns: 1fr; }
  .pt-dashboard__heading { min-height: 56px; }
  .site-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'identity share' 'upload download';
  }
  .site-row__identity { grid-area: identity; }
  .site-row__metric--upload { grid-area: upload; }
  .site-row__metric--download { grid-area: download; }
  .site-row__share { grid-area: share; justify-content: flex-end; }
}
</style>
