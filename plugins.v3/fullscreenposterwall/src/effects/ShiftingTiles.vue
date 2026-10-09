<template>
  <!-- 不断变化的拼贴（对齐 macOS Shifting Tiles 真实行为规格）：
       不同宽度的矩形模块铺满全屏，模块间 6px 黑色间隔；
       每隔 3~5s 随机一个模块水平收缩退出，相邻模块补位，
       新照片模块从空缺处展开滑入。无文字、无圆角、无阴影 -->
  <div class="collage-root">
    <div v-for="(row, ri) in rows" :key="ri" class="collage-row">
      <div
        v-for="t in row"
        :key="t.id"
        class="ctile"
        :style="{ flexBasis: (t.w * 100).toFixed(3) + '%' }"
      >
        <template v-if="t.stacked">
          <div class="ctile-half"><img v-if="t.url" :src="t.url" alt="" /></div>
          <div class="ctile-half"><img v-if="t.url2" :src="t.url2" alt="" /></div>
        </template>
        <img v-else-if="t.url" :src="t.url" class="ctile-img" alt="" />
        <img v-if="imageType === 'logo' && t.logo" :src="t.logo" class="ctile-logo" alt="" @load="onTileLogoLoad" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';
import type { PosterItem, PluginConfig } from '../types';
import { pickImageUrl, pickImageCandidates, loadImageWithFallback, noteLoadedMainUrl, pickLogoUrl, hasNativeLogoImage } from '../types';

const props = defineProps<{
  items: PosterItem[];
  interval: number;
  imageType: 'backdrop' | 'poster' | string;
  autoplay: boolean;
}>();
defineEmits<{ (e: 'exit'): void }>();

const cfg = ref<PluginConfig>({ tmdb_image_domain: 'https://image.tmdb.org/t/p/original' } as PluginConfig);

/* ---------- 规格常量 ---------- */
const GAP = 6;                       // 模块间黑色间隔 px
const ANIM_MS = 1100;                // 收缩/展开动画时长（900~1300）
const EASE = 'cubic-bezier(0.45, 0, 0.2, 1)';
const STACKED_PROB = 0.25;           // 双图模块概率
const PRELOAD_COUNT = 8;

interface Tile {
  id: number;
  w: number;                         // 行内宽度分数（行总和=1）
  url: string;
  url2?: string;
  logo?: string;                     // 片名 Logo 叠层（logo 模式用）
  stacked: boolean;
}

const rows = ref<Tile[][]>([]);
let uid = 0;
let timer: number | undefined;
let busy = false;

/* ---------- PhotoQueue：洗牌队列，防重复，跳过加载失败 ---------- */
let queue: PosterItem[] = [];
let cursor = 0;

function reshuffle() {
  queue = [...props.items];
  for (let i = queue.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [queue[i], queue[j]] = [queue[j], queue[i]];
  }
  cursor = 0;
}

function logoUrl(item: PosterItem): string {
  return pickLogoUrl(item, cfg.value.tmdb_image_domain);
}

// 横版 Logo（宽>高）贴瓷砖底部中间；竖版保持居中
function onTileLogoLoad(e: Event) {
  const i = e.target as HTMLImageElement;
  i.classList.toggle('logo-wide', i.naturalWidth >= i.naturalHeight);
}

function imageUrl(item: PosterItem): string {
  return pickImageUrl(item, props.imageType as any, cfg.value.tmdb_image_domain);
}

// 预加载成功才返回（条目内逐级回退候选图，死主机自动跳过、单候选 1.5s 超时），
// 全部失败跳下一张；同时带出片名 Logo URL
function nextPhoto(): Promise<{ url: string; logo: string }> {
  return new Promise(async resolve => {
    if (!props.items.length) return resolve({ url: '', logo: '' });
    let guard = 0;
    while (guard++ <= props.items.length) {
      if (cursor >= queue.length) reshuffle();
      const it = queue[cursor++];
      const cands = it ? pickImageCandidates(it, props.imageType as any, cfg.value.tmdb_image_domain) : [];
      if (!cands.length) continue;
      const url = await loadImageWithFallback(cands);
      if (!url) continue;
      noteLoadedMainUrl(it, props.imageType as any, url, cfg.value.tmdb_image_domain);
      return resolve({ url, logo: (it && !hasNativeLogoImage(it)) ? logoUrl(it) : '' });
    }
    resolve({ url: '', logo: '' });
  });
}

function preloadAhead() {
  let c = cursor;
  for (let k = 0; k < PRELOAD_COUNT && k < queue.length; k++) {
    const it = queue[(c + k) % queue.length];
    if (it) { const im = new Image(); im.src = imageUrl(it); }
  }
}

/* ---------- LayoutEngine：生成错落布局 ---------- */
function genWidth(): number {
  const r = Math.random();
  if (r < 0.25) return 0.30 + Math.random() * 0.08;   // 大横图
  if (r < 0.75) return 0.20 + Math.random() * 0.08;   // 普通
  return 0.14 + Math.random() * 0.06;                 // 窄条
}

async function makeTile(w: number): Promise<Tile> {
  const stacked = Math.random() < STACKED_PROB;
  const p = await nextPhoto();
  const t: Tile = { id: ++uid, w, url: p.url, logo: p.logo, stacked };
  if (stacked) t.url2 = (await nextPhoto()).url;
  return t;
}

async function makeRow(count: number): Promise<Tile[]> {
  const ws = Array.from({ length: count }, genWidth);
  const sum = ws.reduce((a, b) => a + b, 0);
  // 并行构建瓷砖：某块图慢不拖垮整行（首屏速度关键）
  return Promise.all(ws.map(w => makeTile(w / sum)));
}

async function buildLayout() {
  reshuffle();
  // 竖屏用 3 行，横屏 2 行（各占 50%）
  const nRows = window.innerWidth < window.innerHeight ? 3 : 2;
  const counts = nRows === 2 ? [4, 4] : [3, 3, 3];
  // 两行模块数错开（3~5），接缝自然不同
  counts[0] = 3 + Math.floor(Math.random() * 3);
  counts[1] = 3 + Math.floor(Math.random() * 3);
  const out: Tile[][] = await Promise.all(counts.map(c => makeRow(c)));
  rows.value = out;
  preloadAhead();
}

/* ---------- AnimationController：收缩→补位→展开 ---------- */
async function shiftOnce() {
  if (busy || !rows.value.length) return;
  busy = true;
  const ri = Math.floor(Math.random() * rows.value.length);
  const row = rows.value[ri];
  if (row.length < 3) { busy = false; return; }
  const ti = Math.floor(Math.random() * row.length);
  const victim = row[ti];
  const freed = victim.w;
  // 1) 旧模块收缩到 0，宽度让给随机邻居（邻居平滑补位）
  const ni = ti > 0 ? ti - 1 : ti + 1;
  victim.w = 0;
  row[ni].w += freed;
  // 2) 收缩过半后：移除旧模块，新模块以 0 宽插入随机位置
  window.setTimeout(async () => {
    const idx = row.indexOf(victim);
    if (idx >= 0) row.splice(idx, 1);
    const t = await makeTile(0);
    const pos = Math.floor(Math.random() * (row.length + 1));
    row.splice(pos, 0, t);
    // 3) 下一帧展开新模块：给它目标宽度，其余等比让出空间
    requestAnimationFrame(() => {
      const w = genWidth();
      const others = row.filter(x => x !== t);
      const sum = others.reduce((a, b) => a + b.w, 0) || 1;
      others.forEach(x => { x.w = x.w / sum * (1 - w); });
      t.w = w;
      window.setTimeout(() => { busy = false; }, ANIM_MS);
    });
  }, ANIM_MS * 0.55);
}

function schedule() {
  if (timer) { clearTimeout(timer); timer = undefined; }
  if (!props.autoplay) return;
  // 静止 3~5s 随机（interval 作为基准微调）
  const base = Math.min(5000, Math.max(3000, props.interval * 1000));
  const wait = base - 1000 + Math.random() * 2000;
  timer = window.setTimeout(async () => {
    await shiftOnce();
    schedule();
  }, wait);
}

/* ---------- 后台暂停 ---------- */
function onVis() {
  if (document.hidden) {
    if (timer) { clearTimeout(timer); timer = undefined; }
  } else {
    schedule();
  }
}

/* ---------- resize 防抖（布局用分数宽度天然自适应，仅需重建行数以适应横竖屏切换） ---------- */
let resizeTimer: number | undefined;
function onResize() {
  if (resizeTimer) clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    const want = window.innerWidth < window.innerHeight ? 3 : 2;
    if (rows.value.length !== want) buildLayout();
  }, 300);
}

onMounted(async () => {
  await buildLayout();
  schedule();
  document.addEventListener('visibilitychange', onVis);
  window.addEventListener('resize', onResize);
});
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer);
  if (resizeTimer) clearTimeout(resizeTimer);
  document.removeEventListener('visibilitychange', onVis);
  window.removeEventListener('resize', onResize);
});
watch(() => props.interval, () => schedule());
watch(() => props.items?.length, async (n, old) => { if (!old || n !== old) { await buildLayout(); schedule(); } });
</script>

<style scoped>
.collage-root {
  width: 100vw; height: 100vh;
  background: #000;
  overflow: hidden;
  display: flex; flex-direction: column;
}
.collage-row {
  flex: 1;
  display: flex;
  min-height: 0;
}
.ctile {
  flex: 0 0 auto;
  min-width: 0;
  position: relative;
  /* 6px 均匀黑色间隔（每边 3px padding） */
  padding: 3px;
  box-sizing: border-box;
  overflow: hidden;
  transition: flex-basis 1100ms cubic-bezier(0.45, 0, 0.2, 1);
}
.ctile-img { width: 100%; height: 100%; object-fit: cover; object-position: center; display: block; }
.ctile-half { height: calc(50% - 3px); }
.ctile-half:first-child { margin-bottom: 6px; }
.ctile-half img { width: 100%; height: 100%; object-fit: cover; object-position: center; display: block; }
.ctile-logo {
  position: absolute; inset: 0; margin: auto;
  /* 宽度驱动：始终随瓷砖宽度缩放（高度只做兜底约束） */
  width: 62%; height: auto;
  max-height: 62%;
  object-fit: contain;
  filter: drop-shadow(0 4px 16px rgba(0,0,0,.65));
  pointer-events: none;
}
/* 横版 Logo：贴瓷砖底部中间，同样随瓷砖宽度缩放 */
.ctile-logo.logo-wide {
  inset: auto; margin: 0;
  left: 50%; bottom: 8%;
  width: 56%;
  transform: translateX(-50%);
}
</style>
