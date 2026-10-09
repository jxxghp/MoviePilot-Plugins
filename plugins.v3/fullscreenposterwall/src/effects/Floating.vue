<template>
  <div ref="root" class="float-root">
    <div
      v-for="(m, i) in moving" :key="m.item.tmdb_id || m.item.title"
      class="float-card"
      :style="cardStyle(m)"
    >
      <img :src="imageUrl(m.item)" :alt="m.item.title" />
      <div class="float-caption">
        <img v-if="imageType === 'logo' && !hasNativeLogoImage(m.item) && logoUrl(m.item)" :src="logoUrl(m.item)" class="meta-logo meta-logo-sm" alt="" />
        <div v-else class="float-caption-title">{{ m.item.title }}</div>
        <div v-if="m.item.overview" class="float-caption-overview">{{ trimOverview(m.item.overview, 70) }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue';
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
const root = ref<HTMLDivElement | null>(null);

interface Moving {
  item: PosterItem;
  x: number; y: number;
  vx: number; vy: number;
  size: number;       // 缩放后的宽
  rot: number;
  baseRot: number;    // 基础倾角（小角度，有界摆动）
  phase: number;      // 摆动相位
  z: number;          // 图层 0-1
  fade: number;       // 0..1 不透明度
}

const moving = ref<Moving[]>([]);
let raf: number | undefined;
let lastSpawn = 0;
let lastSwap = 0;
let cursor = 0;
let initialized = false;
const MAX = 16;    // 同时存在的卡片数（翻倍）

function logoUrl(item: PosterItem): string {
  return pickLogoUrl(item, cfg.value.tmdb_image_domain);
}

function imageUrl(item: PosterItem): string {
  return pickImageUrl(item, props.imageType as any, cfg.value.tmdb_image_domain);
}

function trimOverview(s: string, max = 70): string {
  return s && s.length > max ? s.slice(0, max) + '…' : (s || '');
}

function spawn(): Moving | null {
  if (!props.items.length) return null;
  // 队列耗尽后循环复用素材，保证长时间运行持续轮播
  if (cursor >= props.items.length) cursor = 0;
  const item = props.items[cursor++];
  const w = window.innerWidth, h = window.innerHeight;
  const size = 240 + Math.random() * 300;   // 最大尺寸增大
  const speed = 0.15 + Math.random() * 0.4;
  const angle = Math.random() * Math.PI * 2;
  return {
    item,
    x: Math.random() * (w - size),
    y: Math.random() * (h - size),
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed,
    size,
    rot: 0,
    baseRot: (Math.random() - 0.5) * 6,   // ±3°
    phase: Math.random() * Math.PI * 2,
    z: Math.random(),
    fade: 0,
  };
}

function cardStyle(m: Moving): Record<string, string> {
  return {
    transform: `translate(${m.x}px, ${m.y}px) rotate(${m.rot}deg)`,
    width: `${m.size}px`,
    height: `${m.size * 1.5}px`,
    zIndex: String(Math.floor(m.z * 100)),
    opacity: String(m.fade),
  };
}

function step(now: number) {
  const w = window.innerWidth, h = window.innerHeight;
  if (props.autoplay) {
    // 替换卡片（每 props.interval 秒换一次最早出现的）
    if (now - lastSwap > props.interval * 1000) {
      const oldest = moving.value.reduce((a, b) => (a.fade > b.fade ? b : a), moving.value[0]);
      if (oldest) {
        const fresh = spawn();
        if (fresh) {
          Object.assign(oldest, fresh);
        }
      }
      lastSwap = now;
    }
    // 新生卡片
    if (moving.value.length < MAX && now - lastSpawn > 800) {
      const m = spawn();
      if (m) moving.value.push(m);
      lastSpawn = now;
    }
  } else if (!initialized) {
    // 关闭自动播放：仅做一次性初始填充，之后不再轮换/补卡
    while (moving.value.length < Math.min(MAX, props.items.length)) {
      const m = spawn();
      if (!m) break;
      moving.value.push(m);
    }
  }
  initialized = true;

  for (const m of moving.value) {
    m.x += m.vx;
    m.y += m.vy;
    if (m.x < -m.size * 0.3) { m.x = -m.size * 0.3; m.vx = Math.abs(m.vx); }
    if (m.x > w - m.size * 0.7) { m.x = w - m.size * 0.7; m.vx = -Math.abs(m.vx); }
    if (m.y < -m.size * 0.3) { m.y = -m.size * 0.3; m.vy = Math.abs(m.vy); }
    if (m.y > h - m.size * 0.5) { m.y = h - m.size * 0.5; m.vy = -Math.abs(m.vy); }
    m.fade = Math.min(1, m.fade + 0.02);
    // 有界摆动（不累积）：最大倾角 ≈ baseRot ± 2°（峰值 ~5°），长时间运行不越发越斜
    m.rot = m.baseRot + Math.sin(now / 1000 * 0.5 + m.phase) * 2;
  }
  raf = requestAnimationFrame(step);
}

onMounted(() => { raf = requestAnimationFrame(step); });
onBeforeUnmount(() => { if (raf) cancelAnimationFrame(raf); });
</script>

<style scoped>
.float-root { width: 100vw; height: 100vh; background: linear-gradient(135deg, #0a0a0a, #1a1a2e); overflow: hidden; position: relative; }
.float-card {
  position: absolute; top: 0; left: 0;
  background: #111; border-radius: 8px; overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  transition: opacity 1.2s ease;
  will-change: transform, opacity;
}
.float-card img { width: 100%; height: 100%; object-fit: cover; display: block; }
.float-caption {
  position: absolute; bottom: 0; left: 0; right: 0;
  padding: 8px 10px; background: linear-gradient(transparent, rgba(0,0,0,.85));
  color: #fff;
}
.float-caption-title {
  font-size: 13px; font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.float-caption-overview {
  font-size: 11px; opacity: .8; margin-top: 3px; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta-logo-sm { max-width: 200px; max-height: 56px; object-fit: contain; object-position: left bottom; }
</style>