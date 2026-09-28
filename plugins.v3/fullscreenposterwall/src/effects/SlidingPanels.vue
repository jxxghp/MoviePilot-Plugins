<template>
  <div class="panels-root">
    <!-- 滑动面板（对齐 macOS Sliding Panels 屏保，经官方预览视频逐帧校准）：
         面板宽度不固定（混排横竖构图），每组停留数秒后各面板
         以上/下交错方向滑出（抽屉式），新图从对侧滑入 -->
    <div
      v-for="(p, i) in panels"
      :key="`${layoutIdx}-${i}`"
      class="panel-col"
      :class="[`dir-${p.dir}`, { exiting: p.exiting, entering: p.entering }]"
      :style="{ flexBasis: p.width * 100 + '%' }"
    >
      <img v-if="p.url" :src="p.url" alt="" />
      <!-- 每个面板都显示剧名，尺寸统一 -->
      <div v-if="p.item" class="panel-cap">
        <img v-if="imageType === 'logo' && !hasNativeLogoImage(p.item) && p.logo" :src="p.logo" class="cap-logo" alt="" />
        <div v-else class="cap-title">{{ p.item.title }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';
import type { PosterItem, PluginConfig } from '../types';
import { pickImageUrl, pickLogoUrl, hasNativeLogoImage } from '../types';

const props = defineProps<{
  items: PosterItem[];
  interval: number;
  imageType: 'backdrop' | 'poster' | string;
  autoplay: boolean;
}>();
defineEmits<{ (e: 'exit'): void }>();

const cfg = ref<PluginConfig>({ tmdb_image_domain: 'https://image.tmdb.org/t/p/original' } as PluginConfig);

// Apple 官方预览实测：面板宽度不固定（0.31/0.19/0.10/0.40 等混排）。
// 轮换几种布局逼近原生
const LAYOUTS: number[][] = [
  [0.31, 0.19, 0.10, 0.40],
  [0.25, 0.25, 0.25, 0.25],
  [0.40, 0.20, 0.40],
  [0.20, 0.30, 0.30, 0.20],
];

interface Panel { url: string; width: number; dir: 'up' | 'down'; exiting: boolean; entering: boolean; item: PosterItem | null; logo: string }
const panels = ref<Panel[]>([]);
const layoutIdx = ref(0);
let timer: number | undefined;
let cursor = 0;
let busy = false;

function logoUrl(item: PosterItem): string {
  return pickLogoUrl(item, cfg.value.tmdb_image_domain);
}

function imageUrl(item: PosterItem): string {
  return pickImageUrl(item, props.imageType as any, cfg.value.tmdb_image_domain);
}

function nextItem(): PosterItem | null {
  if (!props.items.length) return null;
  const it = props.items[cursor % props.items.length];
  cursor++;
  return it;
}

function buildPanels(li: number) {
  const layout = LAYOUTS[li % LAYOUTS.length];
  panels.value = layout.map((w, i) => {
    const it = nextItem();
    return {
      url: it ? imageUrl(it) : '',
      width: w,
      // Apple：相邻面板滑动方向交错
      dir: (i % 2 === 0 ? 'up' : 'down') as 'up' | 'down',
      exiting: false,
      entering: false,
      item: it,
      logo: (it && !hasNativeLogoImage(it)) ? logoUrl(it) : '',
    };
  });
}

// 抽屉轮换：面板交错滑出，换布局+新图后从对侧滑入
function rotatePanels() {
  if (!props.items.length || busy) return;
  busy = true;
  const SLIDE_MS = 750, STAGGER = 110;
  const n = panels.value.length;
  panels.value.forEach((p, i) => {
    window.setTimeout(() => { p.exiting = true }, i * STAGGER);
  });
  window.setTimeout(() => {
    layoutIdx.value = (layoutIdx.value + 1) % LAYOUTS.length;
    const layout = LAYOUTS[layoutIdx.value];
    panels.value = layout.map((w, i) => {
      const it = nextItem();
      return {
        url: it ? imageUrl(it) : '',
        width: w,
        dir: (i % 2 === 0 ? 'up' : 'down') as 'up' | 'down',
        exiting: false,
        entering: true,
        item: it,
        logo: (it && !hasNativeLogoImage(it)) ? logoUrl(it) : '',
      };
    });
    window.setTimeout(() => {
      panels.value.forEach(p => { p.entering = false });
      busy = false;
    }, SLIDE_MS + 80);
  }, n * STAGGER + SLIDE_MS);
}

function startTimer() {
  if (timer) { clearInterval(timer); timer = undefined; }
  if (props.autoplay) {
    // Apple 实测：约 1s 滑动 + 1.5~3s 停留
    timer = window.setInterval(rotatePanels, Math.max(3000, props.interval * 1000));
  }
}

onMounted(() => { buildPanels(0); startTimer() });
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
watch(() => props.interval, () => startTimer());
watch(() => props.items?.length, (n, old) => { if (!old || n !== old) { buildPanels(0); startTimer() } });
</script>

<style scoped>
.panels-root {
  width: 100vw; height: 100vh; background: #000;
  display: flex; overflow: hidden; position: relative;
}
.panel-col {
  flex: none; height: 100vh; overflow: hidden; position: relative;
  transition: transform 0.75s cubic-bezier(.65,.02,.3,1);
}
.panel-col img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
.panel-col.dir-up.exiting   { transform: translateY(-100%); }
.panel-col.dir-down.exiting { transform: translateY(100%); }
.panel-col.dir-up.entering   { animation: panels-in-from-down 0.75s cubic-bezier(.65,.02,.3,1); }
.panel-col.dir-down.entering { animation: panels-in-from-up 0.75s cubic-bezier(.65,.02,.3,1); }
@keyframes panels-in-from-down { from { transform: translateY(100%); } to { transform: translateY(0); } }
@keyframes panels-in-from-up   { from { transform: translateY(-100%); } to { transform: translateY(0); } }
/* 每个面板底部剧名条：所有面板统一字号 */
.panel-cap {
  position: absolute; left: 0; right: 0; bottom: 0; z-index: 10;
  padding: 40px 18px 16px;
  background: linear-gradient(transparent, rgba(0,0,0,0.72));
  color: #fff; text-shadow: 0 2px 12px rgba(0,0,0,.9);
  pointer-events: none;
}
.cap-title { font-size: 32px; font-weight: 700; line-height: 1.25; }
.cap-logo { max-width: 85%; max-height: 64px; object-fit: contain; object-position: left bottom; filter: drop-shadow(0 4px 12px rgba(0,0,0,.65)); }
</style>
