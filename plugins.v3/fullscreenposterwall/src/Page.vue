<template>
  <div class="fspw-root">
    <!-- ─── 顶部信息条：标题 + 设置按钮 + 全屏播放 ─── -->
    <div v-if="!playing" class="fspw-header">
      <div class="fspw-title">
        <div class="fspw-icon">🎬</div>
        <div>
          <h2 class="ma-0">全屏海报墙</h2>
          <div class="fspw-meta">
            <span v-if="!items.length" class="fspw-waiting">请等候拉取图片/Logo…</span>
            <template v-else>
              {{ items.length }} 张已就绪
              <template v-if="config.image_type === 'logo' && logoReady > 0"> · Logo {{ logoReady }}/{{ items.length }} 就绪{{ logoReady >= items.length ? ' · 完成' : '' }}</template>
              ·
            </template>
            <strong>{{ effectName }}</strong> ·
            {{ config.interval }} 秒切换
          </div>
        </div>
      </div>
      <div class="fspw-header-actions">
        <v-btn
          icon="mdi-cog-outline"
          variant="text"
          size="small"
          @click="openSettings"
          title="插件设置"
        />
        <v-btn
          icon="mdi-close"
          variant="text"
          size="small"
          @click="emit('close')"
          title="关闭"
        />
        <v-btn
          color="primary"
          variant="tonal"
          prepend-icon="mdi-play-circle-outline"
          @click="enterFullscreen"
          :disabled="!loaded"
          class="ml-2"
        >
          进入全屏播放
        </v-btn>
      </div>
    </div>

    <!-- ─── 加载/错误提示 ─── -->
    <v-alert
      v-if="loadError"
      type="warning"
      density="compact"
      variant="tonal"
      class="my-3"
    >
      数据加载失败：{{ loadError }}
      <v-btn
        size="small"
        variant="text"
        @click="reloadItems(true)"
        class="ml-2"
      >重试</v-btn>
    </v-alert>

    <!-- ─── 播放效果缩略图 + 当前设置 ─── -->
    <div v-if="!playing" class="fspw-body">
      <div class="fspw-section-title">
        播放效果
        <span class="fspw-section-hint">当前生效的效果由「插件设置」决定（彩色=选中，灰色=未选中）。</span>
      </div>
      <div class="fspw-effects">
        <div
          v-for="e in effects"
          :key="e.key"
          class="fspw-effect"
          :class="{ 'is-active': config.effect === e.key, 'is-inactive': config.effect !== e.key }"
        >
          <div class="fspw-effect-icon">{{ e.icon }}</div>
          <div class="fspw-effect-name">{{ e.name }}</div>
          <div class="fspw-effect-desc">{{ e.desc }}</div>
          <div v-if="config.effect === e.key" class="fspw-effect-check">✓</div>
        </div>
      </div>

      <div class="fspw-section-title mt-5">当前设置</div>
      <div class="fspw-summary">
        <div class="fspw-summary-row">
          <span class="k">推荐数据源</span>
          <span class="v">
            <v-chip
              v-for="s in sourceChips"
              :key="s.key"
              size="x-small"
              color="primary"
              variant="tonal"
              class="mr-1"
            >{{ s.name }}</v-chip>
          </span>
        </div>
        <div class="fspw-summary-row">
          <span class="k">图片来源</span>
          <span class="v">{{ imageTypeName }}</span>
        </div>
        <div class="fspw-summary-row">
          <span class="k">切换间隔</span>
          <span class="v">{{ config.interval }} 秒切换</span>
        </div>
        <div class="fspw-summary-row">
          <span class="k">随机乱序</span>
          <span class="v">{{ config.shuffle ? '开' : '关' }}</span>
        </div>
        <div class="fspw-summary-row">
          <span class="k">隐藏文字</span>
          <span class="v">{{ config.hide_text ? '开' : '关' }}</span>
        </div>
      </div>

      <div class="fspw-hint">
        💡 修改以上效果/间隔/数据源等：<strong>右上齿轮按钮</strong> 打开插件设置保存。
        <br>
        💡 在同一 Wi-Fi 内的手机/电脑浏览器直接打开（无需登录）：
        <span class="fspw-lan-row">
          <code class="fspw-lan-url">{{ lanWallUrl }}</code>
          <v-btn size="x-small" variant="tonal" color="primary" class="fspw-lan-btn" @click="copyLanUrl">{{ copyText }}</v-btn>
          <v-btn size="x-small" variant="tonal" color="primary" class="fspw-lan-btn" prepend-icon="mdi-open-in-new" @click="openLanUrl">打开</v-btn>
        </span>
      </div>
    </div>

    <!-- ─── 全屏播放：严格走插件 config，stage 用 :key 强制重建 ─── -->
    <!--
      key 同时包含 effect / interval / image_type / hide_text / shuffle
      任一变化都重新挂载组件树，确保所有子组件 timer / props 都按最新 config 跑
    -->
    <Teleport to="body">
      <div
        v-if="playing"
        :key="`stage-${stageKey}`"
        ref="stageRef"
        class="fspw-stage"
        :class="{ 'fspw-no-text': config.hide_text }"
      >
        <component
          :is="currentEffectComp"
          :items="shuffledItems"
          :interval="config.interval"
          :image-type="config.image_type"
          :autoplay="true"
          @exit="exitFullscreen"
        />
        <button class="fspw-exit" @click="exitFullscreen" title="退出 (Esc)">✕</button>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
/*
 * 全屏海报墙 — Page 详情组件（Vue 联邦 Page）。
 *
 * 设计要点（针对用户反馈的"设置不生效"问题）：
 *
 * 1) **stage key 包含全部相关字段** —— effect / interval / image_type /
 *    hide_text / shuffle 任一变化都会触发 Vue 卸载旧 effect 组件并
 *    重建新组件，确保子组件 onMounted 重新读 props.interval 启动 timer。
 *
 * 2) **shuffledItems 在父组件计算**：如果 config.shuffle=true，
 *    进入全屏时把 items 数组复制后用 Fisher-Yates 洗牌。这样子组件
 *    拿到的就是已经乱序的列表，不会出现"显示时按 trending 顺序，
 *    但 Page 概要说 shuffle=true"的语义不一致。
 *
 * 3) **shuffle 用 useMemo（computed）**：每次 playing 进入时重新洗牌，
 *    退出全屏再次进入时又是新顺序。
 *
 * 4) **config 三秒轮询**：见下方 loadConfig + setInterval polling，
 *    保证 Page 概要始终反映最新的 Config 保存结果。
 */
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import PhotosSlideshow from './effects/PhotosSlideshow.vue'
import Floating from './effects/Floating.vue'
import VintagePrints from './effects/VintagePrints.vue'
import LightDance from './effects/LightDance.vue'
import ShiftingTiles from './effects/ShiftingTiles.vue'
import SlidingPanels from './effects/SlidingPanels.vue'
import RingGallery from './effects/RingGallery.vue'
import DepthTunnel from './effects/DepthTunnel.vue'

const emit = defineEmits(['switch', 'close'])  // switch=切到设置弹窗；close=关闭（宿主 PluginDataDialog 转发）

const API_BASE = 'plugin/FullScreenPosterWall'
const TMDB_DOMAIN = 'https://image.tmdb.org/t/p/original'
function getApi() {
  return (typeof window !== 'undefined' ? window.MoviePilotAPI : null)
}

// ─── 状态 ─────────────────────────────────────────────────
const config = ref({
  enabled: false,
  source_config: {},
  effect: 'photos',
  image_type: 'backdrop',
  interval: 8,
  refresh_minutes: 60,
  autoplay: true,
  show_dashboard: true,
  shuffle: false,
  hide_text: false,
  tmdb_image_domain: TMDB_DOMAIN,
})
const items = ref([])
const playing = ref(false)
const loaded = ref(false)
const loadError = ref('')
const stageRef = ref(null)
const copyText = ref('复制')

// 免登录全屏页地址：直接用当前浏览器访问 MoviePilot 的 host（随环境自动更新，
// localhost / 局域网 IP / 域名都适用；不再依赖后端 socket 探测——容器内探到的是网桥 IP）
const lanWallUrl = computed(() => {
  if (typeof window === 'undefined') return ''
  return `${window.location.protocol}//${window.location.host}/api/v1/plugin/FullScreenPosterWall/lan-wall`
})

let configPollTimer

// ─── 动效元数据 ───────────────────────────────────────────
const effects = [
  { key: 'photos',       name: '照片',         icon: '📷', desc: '幻灯片 + Ken Burns', comp: PhotosSlideshow },
  { key: 'shiftingtiles', name: '流动拼贴', icon: '🧩', desc: '模块收缩补位', comp: ShiftingTiles },
  { key: 'ring3d',       name: '环形画廊',       icon: '🎡', desc: '3D 环廊聚焦',  comp: RingGallery },
  { key: 'depthtunnel',  name: '纵深穿梭',       icon: '🚀', desc: '照片飞来掠影', comp: DepthTunnel },
  { key: 'slidingpanels',name: '滑动面板',      icon: '📑', desc: '多列反向滑动',       comp: SlidingPanels },
  { key: 'floating',     name: '浮动',         icon: '🪟', desc: '多图漂浮碰撞',        comp: Floating },
  { key: 'vintage',      name: '怀旧冲印',     icon: '📜', desc: '复古胶片 + 噪点',     comp: VintagePrints },
  { key: 'lightdance',   name: '光舞',         icon: '✨', desc: '光束 + 浮动光球',     comp: LightDance },
]
const currentEffectComp = computed(() => {
  const e = effects.find(x => x.key === config.value.effect)
  return e ? e.comp : PhotosSlideshow
})
const effectName = computed(() => {
  const e = effects.find(x => x.key === config.value.effect)
  return e ? e.name : '照片'
})
// Logo 拉取就绪数（logo 模式下显示在标题行）
const logoReady = computed(() => items.value.filter(i => i.logo_path).length)
const sourceChips = computed(() => {
  // 动态数据源：{api_path: [types]} → 短名 chips（内置源映射，第三方源取路径末段）
  const map = {
    'recommend/tmdb_trending': '流行趋势',
    'recommend/douban_showing': '正在热映',
    'recommend/bangumi_calendar': 'Bangumi放送',
    'recommend/tmdb_movies': 'TMDB电影',
    'recommend/tmdb_tvs': 'TMDB电视剧',
    'recommend/douban_movie_hot': '豆瓣热影',
    'recommend/douban_tv_hot': '豆瓣热剧',
    'recommend/douban_tv_animation': '豆瓣动漫',
    'recommend/douban_movies': '豆瓣新影',
    'recommend/douban_tvs': '豆瓣新剧',
    'recommend/douban_movie_top250': '豆瓣TOP250',
    'recommend/douban_tv_weekly_chinese': '国产剧榜',
    'recommend/douban_tv_weekly_global': '全球剧榜',
    'anilist/trending': 'AniList趋势',
    'anilist/popular_this_season': 'AniList本季',
  }
  const cfg = config.value.source_config || {}
  return Object.keys(cfg)
    .filter(k => (cfg[k] || []).length)
    .map(k => ({ key: k, name: map[k] || k.split('/').pop() }))
})
const imageTypeName = computed(() => {
  const m = { poster: '海报 (poster)', backdrop: '背景大图 (backdrop)', both: '海报 + 背景' }
  return m[config.value.image_type] || config.value.image_type
})

// ─── stage key：任一字段变化都重新挂载 stage ─────────────
const stageKey = computed(() => [
  config.value.effect,
  config.value.interval,
  config.value.image_type,
  config.value.hide_text ? '1' : '0',
  config.value.shuffle ? '1' : '0',
].join('-'))

// ─── 乱序（进入全屏时洗牌） ────────────────────────────────
function shuffleArray(arr) {
  const a = arr.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]]
  }
  return a
}
const shuffledItems = computed(() => {
  if (!config.value.shuffle) return items.value
  return shuffleArray(items.value)
})

// ─── 数据加载 ─────────────────────────────────────────────
async function loadConfig(silent = false) {
  const api = getApi()
  if (!api?.get) return
  try {
    const raw = await api.get(`${API_BASE}/config`)
    // MoviePilot 主框架 axios 的 response interceptor 已经把响应解包：
    //   api.get() 返回的就是后端 {enabled, effect, interval, ...} 字段本体
    //   而不再是 axios 包装的 {data: {...}}
    const newCfg = raw?.data ?? raw  // 兼容两种格式
    if (newCfg && typeof newCfg === 'object') {
      const merged = { ...config.value, ...newCfg }
      const changed = JSON.stringify(config.value) !== JSON.stringify(merged)
      if (changed) config.value = merged
    }
  } catch (e) {
    if (!silent) console.warn('[FullScreenPosterWall] loadConfig failed', e)
  }
}

async function copyLanUrl() {
  const url = lanWallUrl.value
  if (!url) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url)
    } else {
      const ta = document.createElement('textarea')
      ta.value = url
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    copyText.value = '已复制 ✓'
    setTimeout(() => { copyText.value = '复制' }, 2000)
  } catch (e) {
    console.error('[FullScreenPosterWall] copy failed', e)
    copyText.value = '复制失败'
  }
}

function openLanUrl() {
  if (lanWallUrl.value) window.open(lanWallUrl.value, '_blank', 'noopener')
}

async function reloadItems(forceShuffle = false) {
  loadError.value = ''
  const api = getApi()
  if (!api?.get) return
  try {
    const url = (forceShuffle || config.value.shuffle)
      ? `${API_BASE}/recommend?shuffle=true`
      : `${API_BASE}/recommend`
    const raw = await api.get(url)
    // raw 已经是后端字段本体 {success, count, data: [...]} 或直接 [...]
    let list = []
    if (Array.isArray(raw)) list = raw
    else if (Array.isArray(raw?.data)) list = raw.data
    items.value = list
    loaded.value = true
  } catch (e) {
    loadError.value = String(e?.message || e)
    loaded.value = true
  }
}

// ─── 用户交互 ─────────────────────────────────────────────
function openSettings() {
  emit('switch')  // 通知宿主切到 Config 弹窗（PluginConfigDialog 监听 @switch）
}

async function enterFullscreen() {
  if (!loaded.value) await reloadItems(true)
  playing.value = true
  await nextTick()
  // 请求浏览器原生屏幕全屏（用户点击手势内调用，浏览器允许）
  const el = stageRef.value
  if (el) {
    try {
      if (el.requestFullscreen) await el.requestFullscreen()
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen()
    } catch (e) {
      // 浏览器拒绝时保留网页内全屏兜底
      console.warn('[FullScreenPosterWall] requestFullscreen denied, stay in-page fullscreen', e)
    }
  }
}

function exitFullscreen() {
  playing.value = false
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {})
  }
}

// 用户按 Esc 退出屏幕全屏时，同步退出应用内播放状态
function onFsChange() {
  if (!document.fullscreenElement && playing.value) {
    playing.value = false
  }
}

// 全局键盘：F 进 / Esc 出
function onKey(e) {
  if (playing.value && e.key === 'Escape') {
    exitFullscreen()
  } else if (!playing.value && (e.key === 'f' || e.key === 'F') && loaded.value) {
    enterFullscreen()
  }
}

// ─── 生命周期 ─────────────────────────────────────────────
onMounted(async () => {
  await loadConfig()
  await reloadItems(true)
  window.addEventListener('keydown', onKey)
  document.addEventListener('fullscreenchange', onFsChange)
  // 3 秒轮询同步 config：用户在 Config 保存后 Page 概要会自动更新
  configPollTimer = window.setInterval(() => {
    loadConfig(true)
  }, 3000)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('fullscreenchange', onFsChange)
  if (configPollTimer) clearInterval(configPollTimer)
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
})
</script>

<style scoped>
.fspw-root { padding: 4px; }

/* 顶部 */
.fspw-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px;
}
.fspw-title { display: flex; align-items: center; gap: 12px; }
.fspw-icon {
  font-size: 28px;
  background: linear-gradient(135deg, #6366f1, #ec4899);
  width: 48px; height: 48px; border-radius: 12px;
  display: grid; place-items: center;
}
.fspw-meta { font-size: 13px; opacity: 0.65; }
.fspw-waiting { color: #f87171; font-weight: 600; opacity: 1; animation: fspw-blink 0.9s step-start infinite; }
@keyframes fspw-blink { 50% { opacity: 0.15; } }
.fspw-meta strong { color: rgb(var(--v-theme-primary)); }
.fspw-header-actions { display: flex; align-items: center; }

/* 5 动效缩略图 */
.fspw-section-title {
  font-weight: 600; margin-bottom: 8px;
  display: flex; align-items: baseline; gap: 12px;
}
.fspw-section-hint { font-weight: normal; font-size: 12px; opacity: 0.6; }
.fspw-effects {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 150px));
  justify-content: center;
  gap: 10px;
}
.fspw-effect {
  position: relative;
  padding: 10px 8px;
  border-radius: 10px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  cursor: default;
  transition: all 0.18s ease;
}
/* 不可点击的纯状态展示：未选中=灰色淡化，选中=彩色高亮 */
.fspw-effect.is-inactive {
  filter: grayscale(1);
  opacity: 0.45;
}
.fspw-effect.is-active {
  background: rgba(99,102,241,0.18);
  border-color: rgb(var(--v-theme-primary));
}
.fspw-effect-icon { font-size: 26px; }
.fspw-effect-name { font-weight: 600; margin-top: 6px; font-size: 14px; }
.fspw-effect-desc { font-size: 11px; opacity: 0.65; margin-top: 2px; }
.fspw-effect-check {
  position: absolute; top: 6px; right: 8px;
  color: rgb(var(--v-theme-primary)); font-weight: 700;
}

/* 当前设置摘要 */
.fspw-summary {
  padding: 10px 14px;
  background: rgba(255,255,255,0.04);
  border-radius: 8px;
  font-size: 13px;
}
.fspw-summary-row { display: flex; align-items: center; gap: 12px; padding: 4px 0; }
.fspw-summary-row .k { min-width: 92px; opacity: 0.7; }
.fspw-summary-row .v { color: rgb(var(--v-theme-primary)); }

.fspw-hint { font-size: 12px; opacity: 0.6; margin-top: 12px; }
.fspw-lan-row {
  display: inline-flex; align-items: center; gap: 6px;
  margin-top: 4px; flex-wrap: wrap;
}
.fspw-lan-url {
  font-family: monospace; font-size: 11px;
  background: rgba(255,255,255,0.06);
  padding: 2px 6px; border-radius: 4px;
  user-select: all;
}
.fspw-lan-btn { text-transform: none; }

/* 全屏 stage */
.fspw-stage {
  position: fixed; inset: 0; z-index: 99999;
  background: #000; width: 100vw; height: 100vh;
}
/* hide_text：穿透 scoped 隐藏子组件文字区域 */
.fspw-stage.fspw-no-text :deep(.photo-overlay),
.fspw-stage.fspw-no-text :deep(.photo-meta),
.fspw-stage.fspw-no-text :deep(.vintage-meta),
.fspw-stage.fspw-no-text :deep(.vintage-title),
.fspw-stage.fspw-no-text :deep(.light-meta),
.fspw-stage.fspw-no-text :deep(.light-title),
.fspw-stage.fspw-no-text :deep(.float-caption),
.fspw-stage.fspw-no-text :deep(.origami-meta),
.fspw-stage.fspw-no-text :deep(.tiles-meta),
.fspw-stage.fspw-no-text :deep(.panels-meta) {
  display: none !important;
}
.fspw-exit {
  position: fixed; top: 20px; right: 24px; z-index: 100000;
  width: 40px; height: 40px; border-radius: 50%;
  background: rgba(0,0,0,0.45); color: #fff; border: 1px solid rgba(255,255,255,0.3);
  font-size: 18px; cursor: pointer; backdrop-filter: blur(8px);
  opacity: 0.2; transition: opacity 0.2s;
}
.fspw-stage:hover .fspw-exit { opacity: 1; }
.fspw-exit:hover { background: rgba(220,38,38,0.6); }

@media (max-width: 720px) {
  .fspw-effects { grid-template-columns: repeat(2, minmax(0, 150px)); }
}
</style>