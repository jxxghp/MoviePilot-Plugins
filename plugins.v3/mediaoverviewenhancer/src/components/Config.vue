<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const DEFAULTS = {
  enabled: false,
  servers: [],
  libraries: [],
  auto_on_transfer: true,
  post_transfer_delay: 120,
  schedule_hours: 0,
  movie_enabled: true,
  movie_mode: 'expand',
  movie_min_chars: 120,
  movie_target_chars: 320,
  episode_enabled: true,
  episode_mode: 'auto',
  episode_min_chars: 80,
  episode_target_chars: 160,
  episode_always_rewrite: false,
  skip_specials: true,
  mv_enabled: true,
  mv_libraries: ['mv'],
  mv_min_chars: 60,
  mv_target_chars: 110,
  mv_write_people: true,
  mv_people_role: '演唱',
  mv_member_enabled: true,
  mv_member_role: '成员',
  mv_member_name_mode: 'zh',
  mv_member_source: 'both',
  mv_write_nfo: true,
  mv_people_avatar: true,
  mv_split_collab: true,
  mv_self_heal: true,
  mv_nfo_root: 'movie',
  nfo_path_map: '/media/:/medias/media/',
  translate_foreign: true,
  ai_generate_when_missing: true,
  ai_when_source_short: false,
  tmdb_title_fallback: false,
  duplicate_detect: true,
  lock_overview: true,
  force_rewrite: false,
  quality_gate: true,
  quality_min_cjk_ratio: 0.25,
  llm_retries: 2,
  backup_days: 30,
  rollback_max: 200,
  concurrency: 2,
  max_items_per_run: 200,
  scan_days: 0,
  notify: true,
  notify_failure: true,
  notify_daily: false,
  notify_daily_time: '21:00',
  show_sidebar_nav: true,
}

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'MediaOverviewEnhancer' },
})

const emit = defineEmits(['save', 'close'])

const saving = ref(false)
const validationMessage = ref('')
const serverOptions = ref([])
const librariesText = ref('')
const mvLibrariesText = ref('mv')
const serversModel = ref([])
const localConfig = ref({ ...DEFAULTS })
const dailyStats = ref(null)

const base = computed(() => `plugin/${props.pluginId || 'MediaOverviewEnhancer'}`)
const movieModeItems = [
  { title: '扩写现有简介（推荐）', value: 'expand' },
  { title: '翻译英文简介', value: 'translate' },
  { title: '完全由 AI 生成', value: 'ai' },
]
const episodeModeItems = [
  { title: '智能：TMDB 优先 + 缺失时 AI', value: 'auto' },
  { title: '仅使用 TMDB 简介', value: 'tmdb' },
  { title: '全部由 AI 重写', value: 'ai' },
]
const memberNameModeItems = [
  { title: '中文译名（如 李彩琳）', value: 'zh' },
  { title: '原始名称（如 CL）', value: 'original' },
  { title: '中文 + 原名（如 李彩琳 (CL)）', value: 'both' },
]
const memberSourceItems = [
  { title: 'MusicBrainz + Wikidata（推荐）', value: 'both' },
  { title: '仅 MusicBrainz', value: 'musicbrainz' },
  { title: '仅 Wikidata（自带中文名）', value: 'wikidata' },
]

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function textValue(value) {
  return String(value ?? '').trim()
}

function asList(value) {
  if (Array.isArray(value)) return value.map(item => textValue(item)).filter(Boolean)
  if (value === null || value === undefined) return []
  return textValue(value)
    .split(/[,，\n]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function normalizeHhmm(value) {
  const match = String(value || '').trim().match(/^(\d{1,2}):(\d{1,2})/)
  if (!match) return '21:00'
  const hour = Number(match[1])
  const minute = Number(match[2])
  if (!Number.isFinite(hour) || !Number.isFinite(minute) || hour > 23 || minute > 59) return '21:00'
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data') && response.success !== undefined) {
    return response.data
  }
  return response?.data ?? response
}

function applyConfig(source) {
  const merged = { ...DEFAULTS, ...clone(source) }
  localConfig.value = merged
  serversModel.value = asList(merged.servers)
  librariesText.value = asList(merged.libraries).join(', ')
  mvLibrariesText.value = asList(merged.mv_libraries).join(', ') || 'mv'
}

async function loadServerOptions() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/servers`))
    serverOptions.value = (data?.servers || [])
      .filter(item => item.name && item.name !== '-')
      .map(item => ({
        title: `${item.name}${item.connected ? '' : `（未连接：${item.message || ''}）`}`,
        value: item.name,
      }))
  } catch (err) {
    serverOptions.value = []
  }
}

async function loadDailyStats() {
  try {
    const data = unwrap(await props.api.get(`${base.value}/status`))
    dailyStats.value = data?.daily || null
  } catch (err) {
    dailyStats.value = null
  }
}

async function loadDefaults() {
  if (Object.keys(props.initialConfig || {}).length) return
  try {
    const data = unwrap(await props.api.get(`${base.value}/config`))
    if (data && typeof data === 'object') {
      applyConfig(data)
    }
  } catch (err) {
    // 忽略：使用组件内置默认值
  }
}

function buildPayload() {
  const payload = { ...localConfig.value }
  payload.servers = serversModel.value
  payload.libraries = asList(librariesText.value)
  payload.mv_libraries = asList(mvLibrariesText.value).length ? asList(mvLibrariesText.value) : ['mv']
  payload.post_transfer_delay = Number(payload.post_transfer_delay) || 0
  payload.schedule_hours = Number(payload.schedule_hours) || 0
  payload.movie_min_chars = Number(payload.movie_min_chars) || 0
  payload.movie_target_chars = Number(payload.movie_target_chars) || 320
  payload.episode_min_chars = Number(payload.episode_min_chars) || 0
  payload.episode_target_chars = Number(payload.episode_target_chars) || 160
  payload.mv_min_chars = Number(payload.mv_min_chars) || 0
  payload.mv_target_chars = Number(payload.mv_target_chars) || 110
  payload.mv_people_role = textValue(payload.mv_people_role) || '演唱'
  payload.mv_member_role = textValue(payload.mv_member_role) || '成员'
  payload.concurrency = Number(payload.concurrency) || 2
  payload.max_items_per_run = Number(payload.max_items_per_run) || 200
  payload.notify_daily_time = normalizeHhmm(payload.notify_daily_time)
  payload.quality_min_cjk_ratio = Number(payload.quality_min_cjk_ratio) || 0.25
  payload.llm_retries = Number(payload.llm_retries) || 0
  payload.backup_days = Number(payload.backup_days) || 0
  payload.rollback_max = Number(payload.rollback_max) || 200
  payload.scan_days = Number(payload.scan_days) || 0
  return payload
}

function saveConfig() {
  const payload = buildPayload()
  if (payload.movie_target_chars < 80) {
    validationMessage.value = '电影简介目标字数建议不少于 80 字。'
    return
  }
  if (payload.episode_target_chars < 40) {
    validationMessage.value = '分集简介目标字数建议不少于 40 字。'
    return
  }
  if (payload.mv_target_chars < 40) {
    validationMessage.value = 'MV 简介目标字数建议不少于 40 字。'
    return
  }
  validationMessage.value = ''
  saving.value = true
  emit('save', payload)
  window.setTimeout(() => {
    saving.value = false
  }, 600)
}

watch(
  () => props.initialConfig,
  value => {
    if (value && Object.keys(value).length) {
      applyConfig(value)
    }
  },
  { immediate: true, deep: true },
)

onMounted(() => {
  loadDefaults()
  loadServerOptions()
  loadDailyStats()
})
</script>

<template>
  <VForm class="moe-config">
    <div class="moe-config__toolbar text-subtitle-1">影视简介增强设置</div>

    <VAlert v-if="dailyStats" type="info" variant="tonal" density="compact" class="mx-4 mb-2">
      今日处理：成功 {{ dailyStats.updated || 0 }} 条 · 跳过 {{ dailyStats.skipped || 0 }} 条 ·
      失败 {{ dailyStats.failed || 0 }} 条（共 {{ dailyStats.runs || 0 }} 轮）
    </VAlert>

    <section class="moe-config__section">
      <VSwitch v-model="localConfig.enabled" label="启用插件" color="primary" hide-details />
      <div class="text-caption text-medium-emphasis mb-2">
        启用后才会在入库后自动补简介、执行定时补漏或手动批量任务。
      </div>
      <VSwitch v-model="localConfig.auto_on_transfer" label="整理入库后自动补全该媒体" color="primary" hide-details />
      <VTextField
        v-model="localConfig.post_transfer_delay"
        type="number"
        label="入库后等待秒数（等 Emby 刮削完成，建议 60-180）"
        density="comfortable"
        class="mt-2"
      />
      <VTextField
        v-model="localConfig.schedule_hours"
        type="number"
        label="定时补漏间隔（小时，0 表示不启用）"
        density="comfortable"
      />
      <VTextField
        v-model="localConfig.scan_days"
        type="number"
        label="增量扫描天数（0 表示全库；只处理最近 N 天入库的电影/剧集）"
        density="comfortable"
        persistent-hint
        hint="用于减少重复全库扫描；MV 的 NFO / 头像自检不受此限制"
      />
    </section>

    <section class="moe-config__section">
      <div class="text-subtitle-2 mb-2">媒体服务器范围</div>
      <VSelect
        v-model="serversModel"
        :items="serverOptions"
        item-title="title"
        item-value="value"
        label="Emby 服务器（留空表示全部）"
        multiple
        chips
        clearable
        density="comfortable"
      />
      <VTextField
        v-model="librariesText"
        label="媒体库名称（逗号分隔，留空表示全部电影/剧集库）"
        density="comfortable"
        persistent-hint
        hint="例如：电影, 电视剧"
        class="mt-2"
      />
    </section>

    <section class="moe-config__section">
      <div class="text-subtitle-2 mb-2">电影简介</div>
      <VSwitch v-model="localConfig.movie_enabled" label="处理电影" color="primary" hide-details />
      <VSelect
        v-model="localConfig.movie_mode"
        :items="movieModeItems"
        label="处理方式"
        density="comfortable"
        class="mt-2"
      />
      <VRow dense class="mt-1">
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.movie_min_chars"
            type="number"
            label="低于该字数才处理"
            density="comfortable"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.movie_target_chars"
            type="number"
            label="目标字数"
            density="comfortable"
          />
        </VCol>
      </VRow>
    </section>

    <section class="moe-config__section">
      <div class="text-subtitle-2 mb-2">剧集分集简介</div>
      <VSwitch v-model="localConfig.episode_enabled" label="处理剧集分集" color="primary" hide-details />
      <VSelect
        v-model="localConfig.episode_mode"
        :items="episodeModeItems"
        label="分集处理方式"
        density="comfortable"
        class="mt-2"
      />
      <VRow dense class="mt-1">
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.episode_min_chars"
            type="number"
            label="低于该字数才处理"
            density="comfortable"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.episode_target_chars"
            type="number"
            label="目标字数"
            density="comfortable"
          />
        </VCol>
      </VRow>
      <VSwitch
        v-model="localConfig.episode_always_rewrite"
        label="已有简介也交给 AI 重写"
        color="primary"
        hide-details
        class="mt-2"
      />
      <div class="text-caption text-medium-emphasis mb-2">
        关闭时只在简介缺失、过短或同季多集重复时才处理，可显著减少大模型用量。
      </div>
      <VSwitch v-model="localConfig.skip_specials" label="跳过特别篇（第 0 季/S00）" color="primary" hide-details />
      <VSwitch
        v-model="localConfig.duplicate_detect"
        label="检测同季重复简介并重写"
        color="primary"
        hide-details
      />
    </section>

    <section class="moe-config__section">
      <div class="text-subtitle-2 mb-2">MV 简介（音乐视频）</div>
      <VSwitch v-model="localConfig.mv_enabled" label="处理 MV" color="primary" hide-details />
      <VTextField
        v-model="mvLibrariesText"
        label="MV 媒体库名称（逗号分隔）"
        density="comfortable"
        persistent-hint
        hint="默认 mv；留空时会回退为 mv"
        class="mt-2"
      />
      <VRow dense class="mt-1">
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.mv_min_chars"
            type="number"
            label="低于该字数才处理"
            density="comfortable"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.mv_target_chars"
            type="number"
            label="目标字数"
            density="comfortable"
          />
        </VCol>
      </VRow>
      <VSwitch
        v-model="localConfig.mv_write_people"
        label="把解析出的艺人写入 Emby 演员"
        color="primary"
        hide-details
        class="mt-2"
      />
      <VTextField
        v-model="localConfig.mv_people_role"
        label="演员角色名（默认「演唱」）"
        density="comfortable"
        :disabled="!localConfig.mv_write_people"
        persistent-hint
        hint="写入 Emby 的 People 字段，显示在条目「演员」区域"
        class="mt-2"
      />
      <VSwitch
        v-model="localConfig.mv_member_enabled"
        label="把团队成员也写入演员"
        color="primary"
        hide-details
        :disabled="!localConfig.mv_write_people"
        class="mt-2"
      />
      <VTextField
        v-model="localConfig.mv_member_role"
        label="成员角色名（默认「成员」）"
        density="comfortable"
        :disabled="!localConfig.mv_write_people || !localConfig.mv_member_enabled"
        persistent-hint
        hint="成员名单取自 MusicBrainz，团体与成员各占一个演员条目"
        class="mt-2"
      />
      <VSelect
        v-model="localConfig.mv_member_name_mode"
        :items="memberNameModeItems"
        label="成员名显示方式"
        density="comfortable"
        :disabled="!localConfig.mv_write_people || !localConfig.mv_member_enabled"
        class="mt-2"
      />
      <VSelect
        v-model="localConfig.mv_member_source"
        :items="memberSourceItems"
        label="成员数据源"
        density="comfortable"
        :disabled="!localConfig.mv_write_people || !localConfig.mv_member_enabled"
        persistent-hint
        hint="Wikidata 自带中文成员名，MusicBrainz 覆盖更广，两者取并集"
      />
      <VSwitch
        v-model="localConfig.mv_write_nfo"
        label="生成 NFO 元数据文件（供 Kodi / Jellyfin 等读取）"
        color="primary"
        hide-details
        :disabled="!localConfig.mv_write_people"
        class="mt-2"
      />
      <VSwitch
        v-model="localConfig.mv_people_avatar"
        label="自动补演员头像（TMDB / Wikidata 取图）"
        color="primary"
        hide-details
        :disabled="!localConfig.mv_write_people"
      />
      <VSwitch
        v-model="localConfig.mv_split_collab"
        label="拆分合作艺人（A &amp; B 各自署名并取头像）"
        color="primary"
        hide-details
        persistent-hint
        hint="合作署名不是自然人，查不到头像；拆开后每位艺人可单独补图"
        :disabled="!localConfig.mv_write_people"
      />
      <VSwitch
        v-model="localConfig.mv_self_heal"
        label="自检并补全缺失 / 过期的 NFO 与演员头像"
        color="primary"
        hide-details
        :disabled="!localConfig.mv_write_people"
        class="mt-2"
      />
      <VSelect
        v-model="localConfig.mv_nfo_root"
        :items="[
          { title: 'movie（Emby / Kodi 视频库）', value: 'movie' },
          { title: 'musicvideo（Kodi 音乐视频库）', value: 'musicvideo' },
        ]"
        label="NFO 根元素"
        density="comfortable"
        :disabled="!localConfig.mv_write_nfo"
        class="mt-2"
      />
      <VTextField
        v-model="localConfig.nfo_path_map"
        label="NFO 路径映射（服务器路径:本地路径）"
        density="comfortable"
        :disabled="!localConfig.mv_write_nfo"
        persistent-hint
        hint="默认 /media/:/medias/media/；多组用分号分隔（如 /media/:/medias/media/;/mv2/:/medias/media/MV2/）"
      />
      <div class="text-caption text-medium-emphasis mb-2">
        MV 没有 TMDB/IMDb 条目，简介只能由 AI 依据条目名与文件名线索生成。运行面板里需单独选「仅 MV」，
        「全部」不会带上 MV，避免一次性产生大量大模型调用；已达字数的条目默认跳过，勾「强制重写」才会重做。
      </div>
    </section>

    <section class="moe-config__section">
      <div class="text-subtitle-2 mb-2">数据源与写入</div>
      <div class="text-caption text-medium-emphasis mb-2">
        电影与剧集优先用 TMDB 中文简介；MV 没有 TMDB/IMDb 条目，只能由 AI 依据条目名与文件名线索生成。
      </div>
      <VSwitch
        v-model="localConfig.translate_foreign"
        label="允许把英文简介翻译成中文"
        color="primary"
        hide-details
      />
      <VSwitch
        v-model="localConfig.ai_generate_when_missing"
        label="允许在无简介时由 AI 生成"
        color="primary"
        hide-details
      />
      <div class="text-caption text-medium-emphasis mb-2">
        AI 生成只依据影片/剧集上下文，尽量不编造细节，但仍可能与真实剧情有出入，建议先试跑。
      </div>
      <VSwitch
        v-model="localConfig.ai_when_source_short"
        label="素材不足或同季重复时改用 AI 生成"
        color="primary"
        hide-details
      />
      <div class="text-caption text-medium-emphasis mb-2">
        开启后，TMDB 简介过短（翻译/扩写后仍不到上面的字数阈值）或同季多集简介雷同的条目，
        会改由 AI 依据上下文生成更完整、彼此不同的简介；素材充足的条目不受影响。
      </div>
      <VSwitch
        v-model="localConfig.tmdb_title_fallback"
        label="剧集无 TMDB 标识时按标题搜索兜底"
        color="primary"
        hide-details
      />
      <div class="text-caption text-medium-emphasis mb-2">
        仅对剧集生效：当 Emby 里的剧集没有 TMDB 标识（未刮削）时，按「标题 + 年份」严格匹配 TMDB
        （要求标题高度一致、年份相差不超过一年），匹配到的剧集与 TMDB ID 会写入插件日志便于核对。
        关闭时这类剧集会被整体跳过。
      </div>
      <VSwitch
        v-model="localConfig.lock_overview"
        label="写入后锁定 Overview 字段（防止 Emby 刷新覆盖）"
        color="primary"
        hide-details
      />
      <VSwitch
        v-model="localConfig.force_rewrite"
        label="默认强制重写（忽略字数阈值）"
        color="primary"
        hide-details
      />
      <VDivider class="my-3" />
      <div class="text-subtitle-2 mb-2">质量与安全</div>
      <VSwitch
        v-model="localConfig.quality_gate"
        label="质量闸门（中文占比 / 技术词 / 模板句）"
        color="primary"
        hide-details
      />
      <div class="text-caption text-medium-emphasis mb-2">
        开启后，未翻译的外文简介、仍在描述画质/编码的文案、过于模板化的空泛简介会被判为失败并进入失败清单，
        可一键重试，不会写进媒体库。
      </div>
      <VRow dense>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.quality_min_cjk_ratio"
            type="number"
            step="0.05"
            label="中文占比下限（0-1，默认 0.25）"
            density="comfortable"
            :disabled="!localConfig.quality_gate"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.llm_retries"
            type="number"
            label="大模型失败重试次数（0-5）"
            density="comfortable"
          />
        </VCol>
      </VRow>
      <VRow dense class="mt-1">
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.backup_days"
            type="number"
            label="旧简介备份保留天数（0 表示不过期）"
            density="comfortable"
            persistent-hint
            hint="写入前会保存旧简介，可在详情页回滚"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.rollback_max"
            type="number"
            label="最多保留备份条数"
            density="comfortable"
          />
        </VCol>
      </VRow>
    </section>

    <section class="moe-config__section">
      <div class="text-subtitle-2 mb-2">运行控制</div>
      <VRow dense>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.concurrency"
            type="number"
            label="并发数（1-8）"
            density="comfortable"
          />
        </VCol>
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.max_items_per_run"
            type="number"
            label="单次最多处理条数"
            density="comfortable"
          />
        </VCol>
      </VRow>
      <VSwitch
        v-model="localConfig.show_sidebar_nav"
        label="在主界面侧栏显示入口"
        color="primary"
        hide-details
      />
    </section>

    <section class="moe-config__section">
      <div class="text-subtitle-2 mb-2">通知推送</div>
      <VSwitch
        v-model="localConfig.notify"
        label="任务完成通知（含成功 / 跳过 / 失败统计）"
        color="primary"
        hide-details
      />
      <VSwitch
        v-model="localConfig.notify_failure"
        label="有失败条目时额外提醒"
        color="primary"
        hide-details
      />
      <VDivider class="my-2" />
      <VSwitch
        v-model="localConfig.notify_daily"
        label="每日成功汇总通知"
        color="primary"
        hide-details
      />
      <VRow dense class="mt-2">
        <VCol cols="12" md="6">
          <VTextField
            v-model="localConfig.notify_daily_time"
            type="time"
            label="每天发送时间"
            density="comfortable"
            :disabled="!localConfig.notify_daily"
            persistent-hint
            hint="例如 21:00，到点发送当天成功 / 跳过 / 失败条数"
          />
        </VCol>
      </VRow>
      <div class="text-caption text-medium-emphasis">
        通知使用 MoviePilot 已配置的消息渠道；每日汇总统计当天 0 点起的处理结果。
      </div>
    </section>

    <VAlert v-if="validationMessage" type="error" variant="tonal" density="compact" class="mx-4 mb-2">
      {{ validationMessage }}
    </VAlert>

    <div class="moe-config__actions">
      <VBtn variant="text" min-width="88" @click="emit('close')">取消</VBtn>
      <VBtn color="primary" min-width="108" :loading="saving" @click="saveConfig">保存</VBtn>
    </div>
  </VForm>
</template>

<style scoped>
.moe-config {
  min-width: 0;
  padding-bottom: 12px;
}

.moe-config__toolbar {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 12px 16px 4px;
}

.moe-config__section {
  padding: 4px 16px 12px;
}

.moe-config__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 16px;
}
</style>
