<template>
  <div class="fspw-config-root pa-4">
    <v-card variant="outlined" class="pa-4 mb-3">
      <div class="d-flex align-center mb-3">
        <h3 class="ma-0">全屏海报墙 — 插件设置</h3>
        <v-spacer />
        <v-btn
          icon="mdi-close"
          variant="text"
          size="small"
          title="关闭"
          @click="emit('close')"
        />
      </div>

      <v-switch
        v-model="local.enabled"
        label="启用插件"
        color="primary"
        hide-details
        class="mb-3"
      />

      <v-alert type="info" variant="tonal" class="mb-4" density="compact">
        启用后，插件详情页（Page）会提供全屏海报墙入口。
      </v-alert>

      <div class="mb-3">
        <div class="d-flex align-center mb-1">
          <span class="text-subtitle-2">推荐数据源</span>
          <v-progress-circular
            v-if="sourcesLoading"
            indeterminate size="16" width="2" class="ml-2"
          />
        </div>
        <v-alert
          v-if="sourcesError"
          type="warning" variant="tonal" density="compact" class="mb-2"
        >
          {{ sourcesError }}
        </v-alert>
        <v-select
          v-model="selectedPaths"
          :items="sourceList"
          item-title="name"
          item-value="api_path"
          label="勾选数据源（可多选）"
          multiple chips closable-chips
          density="comfortable"
          :menu-props="{ maxHeight: 400 }"
        >
          <template v-slot:item="{ props: itemProps, item }">
            <v-list-item v-bind="itemProps">
              <template v-slot:append>
                <v-chip
                  size="x-small" variant="tonal" class="ml-1"
                  :color="item.raw.builtin ? undefined : 'purple'"
                >{{ item.raw.builtin ? '' : '第三方·' }}{{ natLabel(item.raw.nat) }}</v-chip>
              </template>
            </v-list-item>
          </template>
        </v-select>
        <!-- 只有「混合源」才需要分电影/电视剧；电影源/剧集源天然单类型，不占行 -->
        <div
          v-for="s in enabledMixedSources"
          :key="s.api_path"
          class="d-flex align-center mixed-row"
        >
          <span class="source-name text-caption">{{ s.name }}（混合源）</span>
          <v-spacer />
          <v-checkbox
            label="电影"
            :model-value="hasType(s.api_path, 'movie')"
            hide-details density="compact" class="type-check"
            @update:model-value="v => toggleType(s.api_path, 'movie', v)"
          />
          <v-checkbox
            label="电视剧"
            :model-value="hasType(s.api_path, 'tv')"
            hide-details density="compact" class="type-check"
            @update:model-value="v => toggleType(s.api_path, 'tv', v)"
          />
        </div>
        <div v-if="!sourcesLoading && !sourceList.length && !sourcesError" class="text-grey text-caption">
          未发现可用数据源
        </div>
      </div>

      <v-select
        v-model="local.effect"
        :items="effectOptions"
        label="播放方式"
        density="comfortable"
        class="mb-3"
      />

      <v-select
        v-model="local.image_type"
        :items="imageTypeOptions"
        label="图片来源"
        density="comfortable"
        class="mb-3"
      />

      <v-select
        v-model.number="local.poster_count"
        :items="posterCountOptions"
        label="海报数量（每次拉取）"
        density="comfortable"
        class="mb-3"
      />

      <v-text-field
        v-model.number="local.interval"
        label="切换间隔（秒）"
        type="number"
        :min="3" :max="30"
        density="comfortable"
        class="mb-3"
      />

      <v-text-field
        v-model.number="local.refresh_minutes"
        label="数据刷新间隔（分钟）"
        type="number"
        :min="5" :max="1440"
        density="comfortable"
        class="mb-3"
      />

      <v-switch
        v-model="local.autoplay"
        label="进入页面后自动播放"
        color="primary"
        hide-details
        density="comfortable"
        class="mb-3"
      />

      <v-switch
        v-model="local.show_dashboard"
        label="在首页仪表板显示此小窗格"
        color="primary"
        hide-details
        density="comfortable"
        class="mb-3"
      />

      <v-switch
        v-model="local.shuffle"
        label="随机乱序（每次全屏顺序不同）"
        color="primary"
        hide-details
        density="comfortable"
        class="mb-3"
      />

      <v-switch
        v-model="local.hide_text"
        label="隐藏文字（只看海报不看标题/年份）"
        color="primary"
        hide-details
        density="comfortable"
        class="mb-4"
      />

      <v-divider class="my-3" />

      <div class="d-flex justify-end gap-2">
        <v-btn variant="text" @click="onReset">重置默认</v-btn>
        <v-btn color="primary" @click="onSave">保存</v-btn>
      </div>
    </v-card>

    <v-card variant="outlined" class="pa-4">
      <h4 class="mb-2">使用说明</h4>
      <ol style="line-height:1.8; padding-left: 20px;">
        <li>在此开启插件并选择推荐数据源 + 播放方式。</li>
        <li>回到插件详情页，点击「进入全屏播放」按钮（或按 F 键）。</li>
        <li>全屏状态下按 Esc 或点击右上角 ✕ 退出。</li>
      </ol>
    </v-card>
  </div>
</template>

<script setup>
// 参考 MoviePilot-Plugins 官方 agenttokens 的 Config.vue 写法：
// 保存完全交给宿主前端（emit('save', cfg)），宿主会用 api.put('plugin/{id}', cfg)
// 持久化。在 baseURL='api/v1/' 的 axios 下，绝对不能在组件里写 'api/v1/plugin/...'，
// 否则会变成 'api/v1/api/v1/plugin/...'（404 双前缀）。
import { reactive, ref, computed, onMounted } from 'vue'

const props = defineProps({
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['save', 'close'])

// 与 Page.vue 相同：宿主把主框架 axios 挂在 window.MoviePilotAPI 上，
// baseURL 已是 api/v1/，插件内路径用 'plugin/FullScreenPosterWall/...'。
const API_BASE = 'plugin/FullScreenPosterWall'
function getApi() {
  return (typeof window !== 'undefined' ? window.MoviePilotAPI : null)
}

const defaultSourceConfig = {
  'recommend/tmdb_trending': ['movie', 'tv'],
  'recommend/tmdb_movies': ['movie', 'tv'],
  'recommend/tmdb_tvs': ['movie', 'tv'],
}
const effectOptions = [
  { title: '照片 (Photos) — 幻灯片', value: 'photos' },
  { title: '流动拼贴 (Shifting Tiles)', value: 'shiftingtiles' },
  { title: '环形画廊 (Ring Gallery) — 3D 环廊', value: 'ring3d' },
  { title: '纵深穿梭 (Depth Tunnel)', value: 'depthtunnel' },
  { title: '滑动面板 (Sliding Panels)', value: 'slidingpanels' },
  { title: '浮动 (Floating) — 漂移', value: 'floating' },
  { title: '怀旧冲印 (Vintage Prints)', value: 'vintage' },
  { title: '光舞 (Light Dance)', value: 'lightdance' },
]
const posterCountOptions = [30, 60, 120, 180, 240]

const imageTypeOptions = [
  { title: '背景大图 (backdrop)', value: 'backdrop' },
  { title: '带Logo的背景大图 (logo)', value: 'logo' },
  { title: '海报 (poster)', value: 'poster' },
]

const defaults = {
  enabled: false,
  source_config: { ...defaultSourceConfig },
  effect: 'photos',
  image_type: 'backdrop',
  interval: 8,
  poster_count: 60,
  refresh_minutes: 60,
  autoplay: true,
  show_dashboard: true,
  shuffle: false,
  hide_text: false,
}

const local = reactive({ ...defaults })

// ─── 动态数据源列表 ───────────────────────────────────────
const sourceList = ref([])
const sourcesLoading = ref(false)
const sourcesError = ref('')

function natLabel(nat) {
  return nat === 'movie' ? '电影源' : nat === 'tv' ? '剧集源' : '混合源'
}
function hasType(apiPath, type) {
  const t = local.source_config?.[apiPath]
  return Array.isArray(t) && t.includes(type)
}
// 下拉选中集 ↔ source_config 双向映射：
// 勾选时按天然类型给默认（混合源全开，单类型源只开对应侧）
const selectedPaths = computed({
  get: () => Object.entries(local.source_config || {})
    .filter(([, t]) => Array.isArray(t) && t.length)
    .map(([k]) => k),
  set: (paths) => {
    const cfg = {}
    for (const p of paths) {
      const s = sourceList.value.find(x => x.api_path === p)
      const prev = (local.source_config || {})[p]
      if (Array.isArray(prev) && prev.length) { cfg[p] = prev; continue }
      cfg[p] = !s ? ['movie', 'tv'] : s.nat === 'movie' ? ['movie'] : s.nat === 'tv' ? ['tv'] : ['movie', 'tv']
    }
    local.source_config = cfg
  },
})
// 只有已勾选的混合源才展开电影/电视剧行
const enabledMixedSources = computed(() =>
  sourceList.value.filter(s => s.nat === 'mixed' && selectedPaths.value.includes(s.api_path))
)
function toggleType(apiPath, type, on) {
  const cfg = { ...(local.source_config || {}) }
  const cur = new Set(Array.isArray(cfg[apiPath]) ? cfg[apiPath] : [])
  if (on) cur.add(type)
  else cur.delete(type)
  const arr = ['movie', 'tv'].filter(t => cur.has(t))
  if (arr.length) cfg[apiPath] = arr
  else delete cfg[apiPath] // 两侧都取消 = 停用该源
  local.source_config = cfg
}

async function loadSources() {
  const api = getApi()
  if (!api) {
    sourcesError.value = '宿主 API 未就绪，数据源列表加载失败（保存不受影响）'
    return
  }
  sourcesLoading.value = true
  sourcesError.value = ''
  try {
    const raw = await api.get(`${API_BASE}/sources`)
    // 主框架 axios 拦截器已解包：raw 通常就是后端 body {success, data}；
    // 少数版本可能仍套一层 axios response（raw.data 才是 body），两种都兼容。
    const payload = (raw && typeof raw === 'object' && 'success' in raw) ? raw : (raw?.data ?? raw)
    if (payload?.success) {
      sourceList.value = payload.data?.sources || []
      // 后端返回的当前选择优先于 initialConfig（权威状态）
      const sel = payload.data?.selected
      if (sel && Object.keys(sel).length) {
        local.source_config = sel
      }
    } else {
      sourcesError.value = payload?.message || '数据源列表加载失败（保存不受影响）'
    }
  } catch (e) {
    sourcesError.value = '数据源列表加载失败（保存不受影响）'
  } finally {
    sourcesLoading.value = false
  }
}

onMounted(() => {
  // 用宿主传入的 initialConfig 覆盖默认值
  const ic = props.initialConfig
  if (ic && typeof ic === 'object') {
    Object.keys(defaults).forEach(k => {
      if (ic[k] !== undefined) local[k] = ic[k]
    })
  }
  loadSources()
})

function onSave() {
  // 通知宿主前端保存：MoviePilot 监听 @save 然后用 api.put('plugin/{id}', cfg) 持久化
  emit('save', JSON.parse(JSON.stringify(local)))
}

function onReset() {
  Object.assign(local, defaults)
}
</script>

<style scoped>
.fspw-config-root { width: 100%; }
.gap-2 > * + * { margin-left: 8px; }
.mixed-row { min-height: 32px; }
.source-name { font-size: 0.8rem; }
.type-check { flex: 0 0 auto; margin-left: 8px; }
</style>
