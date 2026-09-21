<template>
  <div class="photos-root">
    <transition name="fade" mode="out-in">
      <div v-if="current" :key="currentIndex" class="photo-frame">
        <img :src="imageUrl(current)" class="photo-img" alt="" />
        <div class="photo-overlay">
          <div class="photo-meta" :class="{ 'meta-center': logoWide }">
            <img v-if="imageType === 'logo' && !hasNativeLogoImage(current) && logoUrl(current)" :src="logoUrl(current)" class="meta-logo" alt="" @load="onLogoLoad" />
            <h1 v-else>{{ current.title }}</h1>
            <p v-if="current.year || current.type" class="photo-sub">
              {{ current.year }} <span v-if="current.year && current.type">·</span> {{ current.type }}
            </p>
            <p v-if="current.overview" class="photo-overview">{{ trimOverview(current.overview) }}</p>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue';
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
// 从 Page.vue 注入的 config 也可，但这里简化只用 props.imageType
const currentIndex = ref(0);
let timer: number | undefined;

const current = computed(() => props.items[currentIndex.value] || null);

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

function trimOverview(s: string, max = 160): string {
  return s.length > max ? s.slice(0, max) + '…' : s;
}

function next() {
  if (!props.items.length) return;
  currentIndex.value = (currentIndex.value + 1) % props.items.length;
}

function startTimer() {
  if (timer) { clearInterval(timer); timer = undefined; }
  if (props.autoplay) {
    timer = window.setInterval(next, Math.max(2000, props.interval * 1000));
  }
}

onMounted(() => { startTimer() });
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
// 父组件 interval 变化时重启定时器
watch(() => props.interval, () => startTimer());
// items 数组变化（如新数据加载完成）也重启 timer 避免旧 index 错位
watch(() => props.items?.length, (n, old) => {
  if (!old || n !== old) startTimer()
});
</script>

<style scoped>
.photos-root { width: 100vw; height: 100vh; background: #000; overflow: hidden; }
.photo-frame { position: absolute; inset: 0; }
.photo-img {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover;
  animation: kenburns 14s ease-in-out infinite alternate;
}
@keyframes kenburns {
  0%   { transform: scale(1.05) translate(0,0); }
  100% { transform: scale(1.15) translate(-1.5%, -1%); }
}
.photo-overlay {
  position: absolute; inset: 0;
  background: linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.2) 45%, rgba(0,0,0,0) 70%);
  display: flex; align-items: flex-end; padding: 60px 80px;
}
.photo-meta h1 { font-size: 56px; margin: 0; font-weight: 700; color: #fff; text-shadow: 0 2px 12px rgba(0,0,0,.7); }
.photo-sub { font-size: 18px; opacity: .85; margin: 8px 0; }
.photo-overview { font-size: 16px; opacity: .8; max-width: 720px; line-height: 1.6; margin-top: 12px; }
.fade-enter-active, .fade-leave-active { transition: opacity 1.4s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.meta-logo { max-width: 420px; max-height: 130px; object-fit: contain; object-position: left bottom; filter: drop-shadow(0 4px 16px rgba(0,0,0,.65)); }
/* 横版 Logo：整个 meta 区拉满宽度，内容水平居中 → Logo 位于图片底部中间 */
.meta-center { left: 0 !important; right: 0 !important; width: 100% !important; max-width: none !important; text-align: center !important; align-items: center !important; }
.meta-center .meta-logo { margin: 0 auto; object-position: center bottom; }
</style>