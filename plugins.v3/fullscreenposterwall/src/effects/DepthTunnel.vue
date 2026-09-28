<template>
  <!-- 纵深穿梭：底部备选小图 → 被选中后抖动+绕圈热身 → 从纵深飞来掠过
       主图保持原始比例（contain，不裁切不变形） -->
  <div class="dt-root">
    <div class="dt-streaks" />
    <div
      v-for="f in flyers"
      :key="f.id"
      class="dt-flyer"
      :style="flyerStyle(f)"
    >
      <img v-if="f.url" :src="f.url" alt="" draggable="false" />
      <img v-if="imageType === 'logo' && f.logo" :src="f.logo" class="dt-logo" alt="" @load="onLogoLoad" />
    </div>
    <!-- 底部备选小图队列 -->
    <div class="dt-thumbs">
      <div
        v-for="t in thumbs"
        :key="t.id"
        class="dt-thumb"
        :style="thumbStyle(t)"
      >
        <img v-if="t.url" :src="t.url" alt="" draggable="false" />
      </div>
    </div>
    <div v-if="current" class="dt-meta">
      <img v-if="imageType === 'logo' && !hasNativeLogoImage(current) && logoUrl(current)" :src="logoUrl(current)" class="meta-logo" alt="" @load="onLogoLoad" />
      <template v-else>
        <div class="dt-title">{{ current.title }}</div>
        <div class="dt-sub">{{ current.year }}<span v-if="current.year && current.type"> · </span>{{ current.type }}</div>
      </template>
    </div>
    <div class="dt-vignette" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue';
import type { PosterItem, PluginConfig } from '../types';
import { pickImageUrl, pickImageCandidates, loadImageWithFallback, noteLoadedMainUrl, pickLogoUrl, hasNativeLogoImage } from '../types';

const props = withDefaults(defineProps<{
  items: PosterItem[];
  imageType?: string;
  active?: boolean;
}>(), { imageType: 'backdrop', active: true });

const cfg = ref<PluginConfig>({ tmdb_image_domain: 'https://image.tmdb.org/t/p/original' } as PluginConfig);
fetch('/api/v1/plugin/FullScreenPosterWall/config')
  .then(r => r.json()).then(d => { if (d?.data) cfg.value = d.data; }).catch(() => {});

const imageType = ref(props.imageType);
watch(() => props.imageType, v => { imageType.value = v || 'backdrop'; });

interface Flyer {
  id: number;
  url: string;
  logo: string;
  dx: number;
  dy: number;
  dur: number;
  born: number;
  z: number;
}
interface Thumb { id: number; url: string; item: PosterItem; x: number; y: number; w: number; dur: number; delay: number; depth: number; }

const THUMBS_N = 9;
let zSeq = 0;                        // 图层序号：新图始终压旧图

const flyers = ref<Flyer[]>([]);
const thumbs = ref<Thumb[]>([]);
const current = ref<PosterItem | null>(null);
let uid = 0;
let queue: PosterItem[] = [];
let cursor = 0;
let timer: ReturnType<typeof setInterval> | null = null;
let gcTimer: ReturnType<typeof setInterval> | null = null;
let warming = false;

function imageUrl(item: PosterItem): string {
  return pickImageUrl(item, props.imageType as any, cfg.value.tmdb_image_domain);
}
function logoUrl(item: PosterItem): string {
  return pickLogoUrl(item, cfg.value.tmdb_image_domain);
}
function onLogoLoad(e: Event) {
  const i = e.target as HTMLImageElement;
  i.classList.toggle('logo-wide', i.naturalWidth >= i.naturalHeight);
}
function reshuffle() {
  queue = [...props.items];
  for (let i = queue.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [queue[i], queue[j]] = [queue[j], queue[i]];
  }
  cursor = 0;
}
function nextItem(): PosterItem | null {
  if (!props.items.length) return null;
  if (cursor >= queue.length) reshuffle();
  return queue[cursor++] || null;
}
function fillThumbs() {
  // 有限扫描：连续 miss 满一轮队列长度即判定当前没有可用图片，进入空态，
  // 避免列表非空但全部缺图时 while 同步死循环卡死主线程
  const limit = Math.max(props.items.length, 1);
  let misses = 0;
  while (thumbs.value.length < THUMBS_N && misses < limit) {
    const it = nextItem();
    if (!it) break;
    const url = imageUrl(it);
    if (!url) { misses++; continue; }
    misses = 0;
    // 黑色深处随机散布：位置/大小/透明度/模糊（远景更小更淡更糊）
    const depth = 0.35 + Math.random() * 0.65;
    thumbs.value.push({
      id: ++uid, url, item: it,
      x: 4 + Math.random() * 88,
      y: 6 + Math.random() * 80,
      w: Math.round(56 + depth * 56),
      dur: 7 + Math.random() * 9,
      delay: -Math.random() * 10,
      depth,
    });
  }
}

function thumbStyle(t: Thumb) {
  return {
    left: t.x + '%',
    top: t.y + '%',
    width: t.w + 'px',
    height: Math.round(t.w * 0.66) + 'px',
    opacity: (0.3 + t.depth * 0.35).toFixed(2),
    filter: 'blur(' + ((1 - t.depth) * 1.6).toFixed(1) + 'px)',
    animationDuration: t.dur.toFixed(1) + 's',
    animationDelay: t.delay.toFixed(1) + 's',
  } as any;
}

function flyerStyle(f: Flyer) {
  return {
    '--dx': f.dx + 'vw',
    '--dy': f.dy + 'vh',
    animationDuration: f.dur + 'ms',
    zIndex: f.z,
  } as any;
}

// 选中备选图 → 螺旋状旋转飞出（无单独热身等待）
async function spawn() {
  if (warming || !thumbs.value.length) return;
  warming = true;
  const t = thumbs.value[0];
  const url = await loadImageWithFallback(pickImageCandidates(t.item, props.imageType as any, cfg.value.tmdb_image_domain));
  noteLoadedMainUrl(t.item, props.imageType as any, url, cfg.value.tmdb_image_domain);
  if (!url) {
    thumbs.value.shift();
    fillThumbs();
    warming = false;
    return;
  }
  thumbs.value.shift();
  fillThumbs();
  current.value = t.item;
  const iv = Math.max(4, cfg.value.interval || 8) * 1000;
  flyers.value.push({
    id: ++uid,
    url,
    logo: !hasNativeLogoImage(t.item) ? logoUrl(t.item) : '',
    dx: (Math.random() - 0.5) * 30,
    dy: (Math.random() - 0.5) * 20,
    dur: Math.round(iv * (0.92 + Math.random() * 0.1)),
    born: Date.now(),
    z: 5 + (++zSeq % 40),       // 图层递增：放大时压在所有旧图上
  });
  warming = false;
}

onMounted(() => {
  reshuffle();
  fillThumbs();
  spawn();
  const iv = Math.max(4, cfg.value.interval || 8) * 1000;
  timer = setInterval(spawn, iv);
  gcTimer = setInterval(() => {
    const now = Date.now();
    flyers.value = flyers.value.filter(f => now - f.born < f.dur + 800);
  }, 3000);
  document.addEventListener('visibilitychange', vis);
});
function vis() {
  if (document.hidden) {
    if (timer) { clearInterval(timer); timer = null; }
  } else if (!timer) {
    timer = setInterval(spawn, Math.max(4, cfg.value.interval || 8) * 1000);
  }
}
onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
  if (gcTimer) clearInterval(gcTimer);
  document.removeEventListener('visibilitychange', vis);
});
watch(() => props.items, () => { reshuffle(); thumbs.value = []; fillThumbs(); }, { deep: true });
</script>

<style scoped>
.dt-root {
  position: absolute; inset: 0; overflow: hidden;
  background: radial-gradient(ellipse at center, #0b0e14 0%, #000 75%);
}
.dt-streaks {
  position: absolute; left: 50%; top: 50%;
  width: 220vmax; height: 220vmax;
  transform: translate(-50%, -50%);
  background: repeating-conic-gradient(
    from 0deg,
    rgba(255,255,255,0.028) 0deg 0.6deg,
    transparent 0.6deg 9deg
  );
  animation: dt-spin 90s linear infinite;
  pointer-events: none;
}
@keyframes dt-spin { to { transform: translate(-50%, -50%) rotate(360deg); } }

.dt-flyer {
  position: absolute; left: 50%; top: 50%;
  width: min(72vw, 1280px); height: min(72vh, 760px);
  margin-left: calc(min(72vw, 1280px) / -2);
  margin-top: calc(min(72vh, 760px) / -2);
  animation-name: dt-fly;
  animation-timing-function: cubic-bezier(0.32, 0.42, 0.55, 1);
  animation-fill-mode: forwards;
  will-change: transform, opacity;
}
/* 螺旋飞出：绕 2 圈、轨道半径随接近而收缩；旋转截止点放大，放大时压在最上层 */
@keyframes dt-fly {
  /* 时间配比：旋转 30%、正向放大 60%（旋转的 2 倍）、淡出 10% */
  0%   { transform: scale(0.06) rotate(0deg) translate(16vw, -12vh); opacity: 0; }
  4%   { opacity: 1; }
  13%  { transform: scale(0.30) rotate(230deg) translate(-9vw, 6vh); }
  21%  { transform: scale(0.55) rotate(470deg) translate(5vw, 3.5vh); }
  26%  { transform: scale(0.82) rotate(650deg) translate(-2vw, -1.5vh); }
  30%  { transform: scale(1) rotate(720deg) translate(0, 0); }
  90%  { transform: scale(1.15) rotate(720deg) translate(0, 0); opacity: 1; }
  100% { transform: scale(1.2) rotate(720deg) translate(var(--dx), var(--dy)); opacity: 0; }
}
/* 主图保持原始比例：contain，不裁切、不拉伸 */
.dt-flyer img:not(.dt-logo) {
  width: 100%; height: 100%;
  object-fit: contain; object-position: center;
  display: block;
}
.dt-logo {
  position: absolute; inset: 0; margin: auto;
  max-width: 60%; max-height: 45%; width: auto; height: auto;
  object-fit: contain; filter: drop-shadow(0 6px 24px rgba(0,0,0,.7)); pointer-events: none;
}
.dt-logo.logo-wide { inset: auto; margin: 0; left: 50%; bottom: 7%; transform: translateX(-50%); }

/* 备选小图：散布在黑色深处，缓慢乱序漂移 */
.dt-thumbs {
  position: absolute; inset: 0;
  pointer-events: none;
  z-index: 1;
}
.dt-thumb {
  position: absolute;
  overflow: hidden;
  background: #111;
  border: 1px solid rgba(255,255,255,0.10);
  animation-name: dt-drift;
  animation-timing-function: ease-in-out;
  animation-iteration-count: infinite;
  animation-direction: alternate;
  will-change: transform;
}
@keyframes dt-drift {
  0%   { transform: translate(0, 0); }
  50%  { transform: translate(26px, -18px); }
  100% { transform: translate(-20px, 22px); }
}
.dt-thumb img {
  width: 100%; height: 100%;
  object-fit: cover; object-position: center;
  display: block;
}
.dt-meta {
  position: absolute; left: 48px; bottom: 42px; max-width: 560px;
  color: #fff; z-index: 60;
}
.dt-title { font-size: 42px; font-weight: 700; text-shadow: 0 2px 14px rgba(0,0,0,.8); }
.dt-sub { font-size: 15px; opacity: .8; margin-top: 6px; }
.meta-logo { max-width: 420px; max-height: 130px; object-fit: contain; object-position: left bottom; filter: drop-shadow(0 4px 16px rgba(0,0,0,.65)); }
.meta-logo.logo-wide { display: block; margin: 0 auto; }
.dt-vignette {
  position: absolute; inset: 0; pointer-events: none; z-index: 2;
  background: radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,.6) 100%);
  z-index: 50;
}
</style>
