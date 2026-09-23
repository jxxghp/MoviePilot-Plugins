<template>
  <div class="vintage-root">
    <transition name="vintage-fade" mode="out-in">
      <div v-if="current" :key="currentIndex" class="vintage-stage">
        <img :src="imageUrl(current)" class="vintage-img" :style="imgStyle" />
        <canvas ref="canvasRef" class="vintage-canvas"></canvas>
        <div class="vintage-frame">
          <div class="vintage-meta" :class="{ 'meta-center': logoWide }">
            <img v-if="imageType === 'logo' && !hasNativeLogoImage(current) && logoUrl(current)" :src="logoUrl(current)" class="meta-logo" alt="" @load="onLogoLoad" />
            <div v-else class="vintage-title">{{ current.title }}</div>
            <div class="vintage-year">{{ current.year }}</div>
            <div v-if="current.overview" class="vintage-overview">{{ trimOverview(current.overview) }}</div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue';
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
const currentIndex = ref(0);
const canvasRef = ref<HTMLCanvasElement | null>(null);
const current = computed(() => props.items[currentIndex.value] || null);
const imgStyle = ref<Record<string,string>>({});

// 横版 Logo（宽>高）置于图片底部中间；竖版保持现状（meta 区左下）
const logoWide = ref(false);
function onLogoLoad(e: Event) {
  const i = e.target as HTMLImageElement;
  logoWide.value = i.naturalWidth >= i.naturalHeight;
}

function logoUrl(item: PosterItem): string {
  return pickLogoUrl(item, cfg.value.tmdb_image_domain);
}

function imageUrl(item: PosterItem): string {
  return pickImageUrl(item, props.imageType as any, cfg.value.tmdb_image_domain);
}

function next() { if (props.items.length) currentIndex.value = (currentIndex.value + 1) % props.items.length; }

function trimOverview(s: string, max = 120): string {
  return s && s.length > max ? s.slice(0, max) + '…' : (s || '');
}

let timer: number | undefined;

// 给图片加复古滤镜（CSS 滤镜足够，无需 Canvas 处理像素）
watch(current, async () => {
  await nextTick();
  imgStyle.value = {
    filter: 'sepia(0.55) saturate(0.85) contrast(1.05) brightness(0.95) hue-rotate(-8deg)',
  };
  drawGrain();
});

function drawGrain() {
  const c = canvasRef.value;
  if (!c) return;
  c.width = window.innerWidth;
  c.height = window.innerHeight;
  const ctx = c.getContext('2d');
  if (!ctx) return;
  // 清空 + 暗角
  ctx.clearRect(0, 0, c.width, c.height);
  const grad = ctx.createRadialGradient(
    c.width/2, c.height/2, Math.min(c.width, c.height) * 0.4,
    c.width/2, c.height/2, Math.max(c.width, c.height) * 0.7,
  );
  grad.addColorStop(0, 'rgba(0,0,0,0)');
  grad.addColorStop(1, 'rgba(0,0,0,0.55)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, c.width, c.height);

  // 颗粒噪点
  const id = ctx.getImageData(0, 0, c.width, c.height);
  const d = id.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * 38;
    d[i] = Math.max(0, Math.min(255, d[i] + n));
    d[i+1] = Math.max(0, Math.min(255, d[i+1] + n));
    d[i+2] = Math.max(0, Math.min(255, d[i+2] + n));
  }
  ctx.putImageData(id, 0, 0);
}

onMounted(() => {
  if (props.autoplay) timer = window.setInterval(next, Math.max(2500, props.interval * 1000));
  window.addEventListener('resize', drawGrain);
});
onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
  window.removeEventListener('resize', drawGrain);
});
</script>

<style scoped>
.vintage-root { width: 100vw; height: 100vh; background: #1a1108; overflow: hidden; }
.vintage-stage { position: absolute; inset: 0; }
.vintage-img {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: contain;
  transition: filter 1.4s ease;
  background: #1a1108;
}
.vintage-canvas {
  position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none;
}
.vintage-frame {
  position: absolute; inset: 0;
  border: 24px solid #f5e9d0;
  box-shadow: inset 0 0 60px rgba(0,0,0,0.6), inset 0 0 6px rgba(0,0,0,0.4);
  display: flex; align-items: flex-start; justify-content: flex-end; padding: 56px 40px 0 0;
  pointer-events: none;
}
.vintage-meta { text-align: right; color: #f5e9d0; }
.vintage-title {
  font-family: 'Times New Roman', 'Songti SC', serif;
  font-size: 36px; font-weight: 600; letter-spacing: 1px;
  text-shadow: 0 2px 6px rgba(0,0,0,.6);
}
.vintage-year { font-size: 14px; opacity: .8; margin-top: 6px; letter-spacing: 4px; }
.vintage-overview {
  font-size: 14px; opacity: .75; max-width: 640px;
  margin: 10px auto 0; line-height: 1.6;
  text-shadow: 0 1px 4px rgba(0,0,0,.6);
}
.vintage-fade-enter-active, .vintage-fade-leave-active { transition: opacity 1.4s ease; }
.vintage-fade-enter-from, .vintage-fade-leave-to { opacity: 0; }
.meta-logo { max-width: 420px; max-height: 130px; object-fit: contain; object-position: left bottom; filter: drop-shadow(0 4px 16px rgba(0,0,0,.65)); }
/* 横版 Logo：整个 meta 区拉满宽度，内容水平居中 → Logo 位于图片底部中间 */
.meta-center { left: 0 !important; right: 0 !important; width: 100% !important; max-width: none !important; text-align: center !important; align-items: center !important; }
.meta-center .meta-logo { margin: 0 auto; object-position: center bottom; }
</style>