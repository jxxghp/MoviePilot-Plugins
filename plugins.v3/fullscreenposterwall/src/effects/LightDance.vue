<template>
  <div ref="root" class="light-root">
    <img v-if="current" :key="currentIndex" :src="imageUrl(current)" class="light-img" />
    <div class="light-rays" />
    <div class="light-orbs">
      <div v-for="o in orbs" :key="o.id" class="orb" :style="orbStyle(o)" />
    </div>
    <div class="light-vignette" />
    <div v-if="current" class="light-meta" :class="{ 'meta-center': logoWide }">
      <img v-if="imageType === 'logo' && !hasNativeLogoImage(current) && logoUrl(current)" :src="logoUrl(current)" class="meta-logo" alt="" @load="onLogoLoad" />
      <div v-else class="light-title">{{ current.title }}</div>
      <div class="light-sub">{{ current.year }} <span v-if="current.type">· {{ current.type }}</span></div>
      <div v-if="current.overview" class="light-overview">{{ trimOverview(current.overview) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue';
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
const current = computed(() => props.items[currentIndex.value] || null);

interface Orb {
  id: number; x: number; y: number; size: number;
  hue: number; phase: number;
}
const orbs = ref<Orb[]>([]);
const root = ref<HTMLDivElement | null>(null);
let timer: number | undefined;
let raf: number | undefined;
const ORB_COUNT = 12;
let cursor = 0;

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

function trimOverview(s: string, max = 120): string {
  return s && s.length > max ? s.slice(0, max) + '…' : (s || '');
}
function orbStyle(o: Orb): Record<string,string> {
  return {
    transform: `translate(${o.x}px, ${o.y}px)`,
    width: `${o.size}px`,
    height: `${o.size}px`,
    background: `radial-gradient(circle, hsla(${o.hue}, 90%, 70%, 0.85), hsla(${o.hue}, 90%, 50%, 0.0) 70%)`,
  };
}

function step(now: number) {
  const t = now / 1000;
  const w = window.innerWidth, h = window.innerHeight;
  for (const o of orbs.value) {
    o.x = w * 0.5 + Math.cos(t * 0.4 + o.phase) * w * 0.45;
    o.y = h * 0.5 + Math.sin(t * 0.35 + o.phase * 1.7) * h * 0.45;
  }
  raf = requestAnimationFrame(step);
}

function next() {
  if (!props.items.length) return;
  currentIndex.value = (currentIndex.value + 1) % props.items.length;
  // 每张图换一组色相
  for (const o of orbs.value) {
    o.hue = (o.hue + 35 + Math.random() * 40) % 360;
    o.size = 200 + Math.random() * 280;
  }
}

function startTimer() {
  if (timer) { clearInterval(timer); timer = undefined; }
  if (props.autoplay) timer = window.setInterval(next, Math.max(3000, props.interval * 1000));
}

onMounted(() => {
  for (let i = 0; i < ORB_COUNT; i++) {
    orbs.value.push({
      id: i,
      x: 0, y: 0,
      size: 200 + Math.random() * 200,
      hue: Math.random() * 360,
      phase: Math.random() * Math.PI * 2,
    });
  }
  raf = requestAnimationFrame(step);
  startTimer();
});
onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
  if (raf) cancelAnimationFrame(raf);
});
watch(() => props.interval, () => startTimer());
</script>

<style scoped>
.light-root {
  width: 100vw; height: 100vh; position: relative;
  background: #000; overflow: hidden;
}
.light-img {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover;
  filter: brightness(0.6) saturate(1.3) contrast(1.1);
  animation: pulse 10s ease-in-out infinite alternate;
  transition: filter 1.6s ease;
}
@keyframes pulse {
  0% { filter: brightness(0.55) saturate(1.2) contrast(1.1) hue-rotate(0deg); }
  100% { filter: brightness(0.7) saturate(1.4) contrast(1.2) hue-rotate(20deg); }
}
.light-rays {
  position: absolute; inset: 0;
  background: conic-gradient(from 0deg at 50% 50%,
    rgba(255,255,255,0) 0deg,
    rgba(255,255,255,0.08) 30deg,
    rgba(255,255,255,0) 60deg,
    rgba(255,200,100,0.06) 120deg,
    rgba(255,255,255,0) 150deg,
    rgba(100,200,255,0.08) 240deg,
    rgba(255,255,255,0) 360deg);
  mix-blend-mode: screen;
  animation: rotate 30s linear infinite;
  pointer-events: none;
}
@keyframes rotate { to { transform: rotate(360deg); } }
.light-orbs { position: absolute; inset: 0; pointer-events: none; mix-blend-mode: screen; }
.orb { position: absolute; top: 0; left: 0; border-radius: 50%; filter: blur(8px); will-change: transform; }
.light-vignette {
  position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.75) 100%);
}
.light-meta {
  position: absolute; bottom: 80px; left: 80px;
  color: #fff; text-shadow: 0 2px 12px rgba(0,0,0,.8);
  animation: rise 1.6s ease both;
}
.light-title { font-size: 48px; font-weight: 700; }
.light-sub { font-size: 18px; opacity: .85; margin-top: 8px; letter-spacing: 2px; }
.light-overview {
  font-size: 14px; opacity: .8; max-width: 640px;
  line-height: 1.6; margin-top: 10px;
}
@keyframes rise { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: none; } }
.meta-logo { max-width: 420px; max-height: 130px; object-fit: contain; object-position: left bottom; filter: drop-shadow(0 4px 16px rgba(0,0,0,.65)); }
/* 横版 Logo：整个 meta 区拉满宽度，内容水平居中 → Logo 位于图片底部中间 */
.meta-center { left: 0 !important; right: 0 !important; width: 100% !important; max-width: none !important; text-align: center !important; align-items: center !important; }
.meta-center .meta-logo { margin: 0 auto; object-position: center bottom; }
</style>