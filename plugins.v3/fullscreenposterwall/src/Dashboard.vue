<template>
  <div class="fspw-dash">
    <!-- 普通模式：dashboard 卡片 -->
    <template v-if="!fullscreen">
      <div class="dash-header">
        <span class="dash-icon">🎬</span>
        <span class="dash-title">全屏海报墙</span>
        <v-chip size="x-small" class="ml-2" color="primary" variant="tonal">
          {{ effectName }}
        </v-chip>
      </div>

      <!-- 当前设置的动效直接渲染进小窗格（与全屏播放一致，按窗格大小整体缩放） -->
      <div ref="stageRef" class="dash-stage" :class="{ 'dash-no-text': hideText }" @click="enterFullscreen" title="点击进入全屏">
        <div class="dash-effect-zoom" :style="{ zoom: stageZoom }">
          <component
            :is="currentEffectComp"
            :items="items"
            :interval="cfg.interval || 8"
            :image-type="cfg.image_type || 'backdrop'"
            :autoplay="false"
          />
        </div>
        <div class="dash-play-hint">
          <v-icon size="large">mdi-play-circle-outline</v-icon>
        </div>
      </div>

      <v-btn
        color="primary"
        variant="tonal"
        block
        class="dash-cta mt-3"
        prepend-icon="mdi-play-circle-outline"
        @click="enterFullscreen"
      >
        全屏播放
      </v-btn>

    </template>

    <!-- 全屏模式：Teleport 到 body，脱离 dashboard 卡片的布局/变换上下文 -->
    <Teleport to="body">
      <div
        v-if="fullscreen"
        ref="fullRef"
        class="dash-fullscreen"
        :class="{ 'dash-no-text': hideText }"
      >
      <component
        :is="currentEffectComp"
        :items="items"
        :interval="cfg.interval || 8"
        :image-type="cfg.image_type || 'backdrop'"
        :autoplay="true"
      />
      <!-- 退出按钮：先退全屏再清理状态 -->
      <button class="dash-exit" @click="exitFullscreen" title="退出 (Esc)">✕</button>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
// Dashboard 组件 — MoviePilot 主页面的仪表板小窗格。
//
// 核心改进：
// - "全屏播放"按钮不再跳转路由；点击直接在 dashboard 卡片内部渲染完整动效。
// - 动效由用户保存的插件 config 完全控制（effect / interval / image_type / shuffle / hide_text）。
// - 进入浏览器原生全屏 API（Fullscreen API），把整个 dashboard 卡扩展到整个屏幕。
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import PhotosSlideshow from './effects/PhotosSlideshow.vue'
import Floating from './effects/Floating.vue'
import VintagePrints from './effects/VintagePrints.vue'
import LightDance from './effects/LightDance.vue'
import ShiftingTiles from './effects/ShiftingTiles.vue'
import SlidingPanels from './effects/SlidingPanels.vue'
import RingGallery from './effects/RingGallery.vue'
import DepthTunnel from './effects/DepthTunnel.vue'

const props = defineProps({
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
})

const API_BASE = 'plugin/FullScreenPosterWall'

function getApi() { return (typeof window !== 'undefined' ? window.MoviePilotAPI : null) }

const items = ref([])
const fullscreen = ref(false)
const fullRef = ref(null)
const stageRef = ref(null)
// 本地拉取的插件配置：Config 保存后以此为准（设置的唯一数据源），
// props.config 仅作为首帧兜底，之后每 5 秒轮询刷新一次。
const localConfig = ref({})
const cfg = computed(() => ({ ...(props.config || {}), ...(localConfig.value || {}) }))
let configPollTimer
let fsChangeHandler

const effectMap = {
  photos: PhotosSlideshow,
  floating: Floating,
  vintage: VintagePrints,
  lightdance: LightDance,
  shiftingtiles: ShiftingTiles,
  slidingpanels: SlidingPanels,
  ring3d: RingGallery,
  depthtunnel: DepthTunnel,
}
const currentEffectComp = computed(() => effectMap[cfg.value?.effect || 'photos'] || PhotosSlideshow)
const effectName = computed(() => {
  const map = {
    photos: '照片', floating: '浮动', vintage: '怀旧冲印',
    lightdance: '光舞',
    shiftingtiles: '流动拼贴', slidingpanels: '滑动面板',
    ring3d: '环形画廊', depthtunnel: '纵深穿梭',
  }
  return map[cfg.value?.effect || 'photos'] || '照片'
})
const hideText = computed(() => !!cfg.value?.hide_text)

// 小窗格缩放系数：按窗格与视口的比例整体缩放动效（vw/px 单位都生效）。
// 用 max 而非 min（cover 语义）：窗格宽高比与视口不同时，
// min 会让内容缩得过小、右侧/下侧露出大块空白；max 铺满窗格、
// 超出部分由 .dash-stage 的 overflow:hidden 裁掉，观感更好。
const stageZoom = ref(0.2)
function updateStageZoom() {
  const el = stageRef.value
  if (!el) return
  stageZoom.value = Math.max(
    el.clientWidth / window.innerWidth,
    el.clientHeight / window.innerHeight
  )
}

async function loadData(forceShuffle = false) {
  const api = getApi()
  if (!api?.get) return
  try {
    const url = forceShuffle
      ? `${API_BASE}/recommend?shuffle=true`
      : `${API_BASE}/recommend`
    const raw = await api.get(url)
    let list = []
    if (Array.isArray(raw)) list = raw
    else if (Array.isArray(raw?.data)) list = raw.data
    items.value = list
  } catch (e) {
    console.warn('[FullScreenPosterWall-Dashboard] load failed', e)
  }
}

async function loadConfig() {
  const api = getApi()
  if (!api?.get) return
  try {
    const raw = await api.get(`${API_BASE}/config`)
    const c = raw?.data ?? raw
    if (c && typeof c === 'object') {
      const changed = JSON.stringify(localConfig.value) !== JSON.stringify(c)
      if (changed) localConfig.value = c
    }
  } catch (e) {
    console.warn('[FullScreenPosterWall-Dashboard] loadConfig failed', e)
  }
}

async function enterFullscreen() {
  // 进入全屏前强制刷新数据，避免用过时的轮播序列
  if (props.allowRefresh) {
    await loadData(true)
  }
  fullscreen.value = true
  await nextTick()
  // 尝试调用浏览器原生 Fullscreen API（用户手势后调用，浏览器允许）
  const el = fullRef.value
  if (el) {
    try {
      if (el.requestFullscreen) await el.requestFullscreen()
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen()
    } catch (e) {
      // 浏览器拒绝权限时，留在应用内全屏（容器已经 fixed 100vw/100vh）
      console.warn('[FullScreenPosterWall-Dashboard] requestFullscreen denied, stay in-app fullscreen', e)
    }
  }
}

/**
 * 在 LAN 模式下其他设备打开分享 URL 时，主框架跳到 /#/dashboard，
 * MoviePilot 渲染 dashboard.vue，里面有我们的 widget。
 *
 * 检测 query string ?fullscreen=1 / ?auto=1：用户首次访问时
 * 跳过 dashboard 直接进全屏。但 MoviePilot 默认行为是先登录，
 * 所以实际更现实的是 dashboard widget 监听 hash 里的 _lan=auto。
 */
function maybeStartFullscreenFromQuery() {
  try {
    const sp = new URLSearchParams(location.search)
    if (sp.get('fullscreen') === '1' || sp.get('auto') === '1') {
      fullscreen.value = true
      // 同时请求浏览器全屏
      nextTick(() => {
        const el = fullRef.value
        if (el?.requestFullscreen) {
          el.requestFullscreen().catch(() => {})
        }
      })
    }
  } catch {}
}

async function exitFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
  } catch {}
  fullscreen.value = false
}

// 监听浏览器全屏状态变化：用户按 Esc 退出屏幕全屏时，同步退出应用内全屏
function onFsChange() {
  if (!document.fullscreenElement && fullscreen.value) {
    fullscreen.value = false
  }
}

function onKey(e) {
  if (fullscreen.value && e.key === 'Escape') exitFullscreen()
}

let stageObserver = null
// MoviePilot 仪表板格子高度由框架 ResizeObserver 驱动，但联邦组件是异步注入的，
// 存在竞态：格子可能停留在骨架高度（只见标题、内容不占位）。
// 挂载与数据就绪后派发 window resize，强制 grid-stack 重新测量本格。
function nudgeGridResize() {
  nextTick(() => requestAnimationFrame(() => window.dispatchEvent(new Event('resize'))))
}
onMounted(async () => {
  await loadConfig()
  await loadData(true)
  nextTick(() => {
    updateStageZoom()
    // 窗格尺寸变化（侧栏折叠/布局调整）时自动重新适配
    if (stageRef.value && typeof ResizeObserver !== 'undefined') {
      stageObserver = new ResizeObserver(() => updateStageZoom())
      stageObserver.observe(stageRef.value)
    }
  })
  nudgeGridResize()
  setTimeout(nudgeGridResize, 800)
  setTimeout(nudgeGridResize, 2500)
  window.addEventListener('resize', updateStageZoom)
  fsChangeHandler = onFsChange
  document.addEventListener('fullscreenchange', fsChangeHandler)
  window.addEventListener('keydown', onKey)
  // 5 秒轮询插件配置：Config 弹窗保存后卡片自动用上新设置
  configPollTimer = window.setInterval(loadConfig, 5000)
  // 检测 URL query：如果带 ?fullscreen=1 / ?auto=1，自动进入全屏
  maybeStartFullscreenFromQuery()
})

onBeforeUnmount(() => {
  if (configPollTimer) clearInterval(configPollTimer)
  stageObserver?.disconnect()
  window.removeEventListener('resize', updateStageZoom)
  if (fsChangeHandler) document.removeEventListener('fullscreenchange', fsChangeHandler)
  window.removeEventListener('keydown', onKey)
  // 万一用户在 dashboard 卡片里全屏时切走，清理浏览器全屏
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
})
</script>

<style scoped>
.fspw-dash { width: 100%; }

/* 普通模式：dashboard 卡片样式 */
.dash-header {
  display: flex; align-items: center;
  margin-bottom: 10px;
  font-size: 14px; font-weight: 600;
}
.dash-icon { font-size: 22px; margin-right: 8px; }
.dash-title { font-size: 15px; font-weight: 600; }

.dash-stage {
  position: relative;
  width: 100%;
  height: 180px;
  border-radius: 10px;
  overflow: hidden;
  background: linear-gradient(135deg, #1e40af, #6d28d9);
  cursor: pointer;
}
.dash-photo { position: absolute; inset: 0; }
.dash-img {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover;
}
/* 小窗格内嵌动效：整体缩放容器填满舞台 */
.dash-effect-zoom {
  position: absolute;
  width: 100%;
  height: 100%;
  left: 0; top: 0;
}
/* 小窗格同样尊重「隐藏文字」设置 */
.dash-stage.dash-no-text :deep(.photo-overlay),
.dash-stage.dash-no-text :deep(.photo-meta),
.dash-stage.dash-no-text :deep(.vintage-meta),
.dash-stage.dash-no-text :deep(.light-meta),
.dash-stage.dash-no-text :deep(.float-caption),
.dash-stage.dash-no-text :deep(.origami-meta),
.dash-stage.dash-no-text :deep(.panels-meta) {
  display: none !important;
}
.dash-overlay {
  position: absolute; left: 0; right: 0; bottom: 0;
  padding: 12px;
  background: linear-gradient(transparent, rgba(0,0,0,0.8));
  color: #fff;
}
.dash-name { font-size: 16px; font-weight: 600; }
.dash-sub { font-size: 12px; opacity: 0.8; margin-top: 2px; }
.dash-fade-enter-active, .dash-fade-leave-active { transition: opacity 0.6s ease; }
.dash-fade-enter-from, .dash-fade-leave-to { opacity: 0; }
.dash-play-hint {
  position: absolute; bottom: 8px; right: 8px;
  background: rgba(0,0,0,0.4); border-radius: 50%;
  width: 36px; height: 36px;
  display: grid; place-items: center;
  color: #fff;
}
.dash-cta { margin-top: 8px; }

/* ─── 全屏模式：覆盖整个 viewport ─── */
.dash-fullscreen {
  position: fixed; inset: 0; z-index: 99999;
  background: #000; width: 100vw; height: 100vh;
}
/* hide_text 选项：隐藏所有动效的文字区域（用 :deep 穿透 scoped） */
.dash-fullscreen.dash-no-text :deep(.photo-overlay),
.dash-fullscreen.dash-no-text :deep(.photo-meta),
.dash-fullscreen.dash-no-text :deep(.origami-meta),
.dash-fullscreen.dash-no-text :deep(.tiles-meta),
.dash-fullscreen.dash-no-text :deep(.panels-meta),
.dash-fullscreen.dash-no-text :deep(.vintage-meta),
.dash-fullscreen.dash-no-text :deep(.light-meta),
.dash-fullscreen.dash-no-text :deep(.float-caption) {
  display: none !important;
}
.dash-exit {
  position: fixed; top: 20px; right: 24px; z-index: 100000;
  width: 40px; height: 40px; border-radius: 50%;
  background: rgba(0,0,0,0.45); color: #fff; border: 1px solid rgba(255,255,255,0.3);
  font-size: 18px; cursor: pointer; backdrop-filter: blur(8px);
  opacity: 0.2; transition: opacity 0.2s;
}
.dash-fullscreen:hover .dash-exit { opacity: 1; }
.dash-exit:hover { background: rgba(220,38,38,0.6); }
</style>
