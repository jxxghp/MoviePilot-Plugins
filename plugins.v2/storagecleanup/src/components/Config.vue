<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'StorageCleanup' },
})

const form = reactive({
  version: 1,
  qb_url: '',
  media_index_db: '',
  moviepilot_db: '',
  qb_backup: '',
  execution_backup: '',
  allowed_roots_text: '',
  quarantine_roots_text: '',
})
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const message = ref('')
const probe = ref(null)
const discovery = ref(null)
const discovering = ref(false)
const discoveryError = ref('')
const advancedOpen = ref(false)

const pluginBase = computed(() => `plugin/${props.pluginId || 'StorageCleanup'}`)

function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data')) {
    return response.data
  }
  return response
}

function applyConfig(config) {
  Object.assign(form, {
    ...config,
    media_index_db: config.media_index_db || config.jellyfin_db || '',
    allowed_roots_text: (config.allowed_roots || []).join('\n'),
    quarantine_roots_text: Object.entries(config.quarantine_roots || {})
      .map(([volume, target]) => `${volume}=${target}`)
      .join('\n'),
  })
}

function parseLines(value) {
  return String(value || '')
    .split('\n')
    .map(item => item.trim())
    .filter(Boolean)
}

function buildConfig() {
  const quarantine_roots = {}
  for (const line of parseLines(form.quarantine_roots_text)) {
    const separator = line.indexOf('=')
    if (separator <= 0 || separator === line.length - 1) {
      throw new Error('隔离目录格式应为：卷根目录=隔离目录。')
    }
    quarantine_roots[line.slice(0, separator).trim()] = line.slice(separator + 1).trim()
  }
  return {
    version: 1,
    qb_url: form.qb_url,
    media_index_db: form.media_index_db,
    moviepilot_db: form.moviepilot_db,
    qb_backup: form.qb_backup,
    execution_backup: form.execution_backup,
    allowed_roots: parseLines(form.allowed_roots_text),
    quarantine_roots,
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (!props.api.get) throw new Error('MoviePilot 没有提供插件 API。')
    const payload = unwrap(await props.api.get(`${pluginBase.value}/config`))
    if (!payload?.ok || !payload.config) throw new Error(payload?.error?.message || '无法读取清理台配置。')
    applyConfig(payload.config)
    probe.value = payload.probe || null
    if (!probe.value?.ok) void discover()
  } catch (err) {
    error.value = err?.message || '无法读取清理台配置。'
  } finally {
    loading.value = false
  }
}

async function discover() {
  if (discovering.value) return
  discovering.value = true
  discoveryError.value = ''
  try {
    if (!props.api.get) throw new Error('MoviePilot 没有提供插件 API。')
    const payload = unwrap(await props.api.get(`${pluginBase.value}/discover`))
    if (!payload?.ok || !payload.config) {
      throw new Error(payload?.error?.message || '自动发现失败。')
    }
    discovery.value = payload
    if ((payload.checks || []).some(item => item.ambiguous || (!item.found && !item.optional && !item.willCreate))) {
      advancedOpen.value = true
    }
  } catch (err) {
    discoveryError.value = err?.message || '自动发现失败。'
    advancedOpen.value = true
  } finally {
    discovering.value = false
  }
}

async function applyDiscovery() {
  if (!discovery.value?.config || !discovery.value?.ready || saving.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    const payload = unwrap(await props.api.post(`${pluginBase.value}/config`, {
      config: discovery.value.config,
    }))
    if (!payload?.ok || !payload.config) {
      throw new Error(payload?.error?.message || '自动配置保存失败。')
    }
    applyConfig(payload.config)
    probe.value = payload.probe || null
    message.value = probe.value?.ok
      ? '自动识别完成，路径探测通过；请刷新资源清单。'
      : '已应用自动识别结果，但仍有项目未就绪；清理操作保持锁定。'
  } catch (err) {
    const payload = err?.response?.data || err?.data
    probe.value = payload?.probe || probe.value
    error.value = err?.message || payload?.error?.message || '自动配置保存失败。'
  } finally {
    saving.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    const config = buildConfig()
    const payload = unwrap(await props.api.post(`${pluginBase.value}/config`, { config }))
    if (!payload?.ok || !payload.config) throw new Error(payload?.error?.message || '配置保存失败。')
    applyConfig(payload.config)
    probe.value = payload.probe || null
    message.value = probe.value?.ok
      ? '配置已保存，路径探测通过；请刷新资源清单。'
      : '配置已保存，但仍有路径未就绪；清理操作保持锁定。'
  } catch (err) {
    const payload = err?.response?.data || err?.data
    probe.value = payload?.probe || probe.value
    error.value = err?.message || payload?.error?.message || '配置保存失败。'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="config-page">
    <header>
      <h2>存储清理设置</h2>
      <p>一般无需填写，先点“自动识别”；识别失败再用手动配置。</p>
    </header>

    <div v-if="loading" class="notice">正在读取配置…</div>
    <section v-else class="discovery-card">
      <div class="discovery-heading">
        <div>
          <strong>自动识别</strong>
          <span>读取 MoviePilot、qB 和媒体目录；媒体库索引可留空。候选不唯一时不会自动猜。</span>
        </div>
        <div class="discovery-actions">
          <button type="button" :disabled="discovering || saving" @click="discover">
            {{ discovering ? '识别中…' : '自动识别' }}
          </button>
          <button v-if="!advancedOpen" class="secondary" type="button" :disabled="saving" @click="advancedOpen = true">
            手动配置
          </button>
        </div>
      </div>
      <div v-if="discovery" class="discovery-results">
        <div v-for="item in discovery.checks || []" :key="item.key" class="discovery-row">
          <div>
            <span>{{ item.label }}</span>
            <small v-if="item.ambiguous">候选：{{ (item.candidates || []).join('；') }}</small>
          </div>
          <b :class="item.ambiguous ? 'missing' : item.found || item.willCreate ? 'found' : item.optional ? 'optional' : 'missing'">{{ item.ambiguous ? '发现多个候选，需手动选择' : item.found ? '已找到' : item.willCreate ? '将自动创建' : item.optional ? '未配置（可选）' : '需管理员处理' }}</b>
        </div>
        <button
          class="apply-discovery"
          type="button"
          :disabled="saving || !discovery.ready"
          @click="applyDiscovery"
        >
          {{ saving ? '应用中…' : '应用识别结果并验证' }}
        </button>
      </div>
      <div v-if="discoveryError" class="discovery-error">
        <span>{{ discoveryError }} 请改用手动配置。</span>
        <button type="button" :disabled="saving" @click="advancedOpen = true">打开手动配置</button>
      </div>
    </section>
    <details v-if="!loading" class="advanced-settings" :open="advancedOpen" @toggle="advancedOpen = $event.target.open">
      <summary>手动配置（自动识别失败时使用）</summary>
      <p>从 NAS 文件管理器复制路径；必须是清理台服务能访问到的路径。媒体库索引可以留空。</p>
      <div class="form-grid">
        <label>qBittorrent 地址<input v-model="form.qb_url" autocomplete="off" placeholder="例：http://127.0.0.1:8080" /></label>
        <label>MoviePilot 数据库<input v-model="form.moviepilot_db" autocomplete="off" placeholder="MoviePilot 容器内 user.db 路径" /></label>
        <label>媒体库索引（可选）<input v-model="form.media_index_db" autocomplete="off" placeholder="Jellyfin / Emby 数据库路径，可留空" /></label>
        <label>qB 种子备份目录<input v-model="form.qb_backup" autocomplete="off" placeholder="qB 备份目录" /></label>
        <label>清理事务备份目录<input v-model="form.execution_backup" autocomplete="off" placeholder="清理台可写的备份目录" /></label>
        <label class="wide">允许扫描/清理的根目录（每行一个）<textarea v-model="form.allowed_roots_text" rows="5" placeholder="下载完成目录、电影目录、电视剧目录" /></label>
        <label class="wide">隔离目录映射（每行：卷根目录=隔离目录）<textarea v-model="form.quarantine_roots_text" rows="3" placeholder="例如：/mnt/data=/mnt/data/.storage-cleanup-quarantine" /></label>
      </div>
      <button class="save" :disabled="loading || saving" @click="save">{{ saving ? '保存中…' : '保存手动配置并探测' }}</button>
    </details>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="message" class="success">{{ message }}</div>
    <div v-if="probe" class="probe">
      <strong>{{ probe.ok ? '只读探测通过' : '只读探测未通过' }}</strong>
      <span v-if="probe.missing?.length">还有 {{ probe.missing.length }} 项路径未找到，请展开管理员配置查看。</span>
      <span v-if="probe.problems?.length">有 {{ probe.problems.length }} 项安全校验未通过，请展开管理员配置查看。</span>
      <details v-if="probe.missing?.length || probe.problems?.length" class="probe-details">
        <summary>查看管理员诊断</summary>
        <span v-for="item in probe.missing || []" :key="`missing-${item}`">未找到：{{ item }}</span>
        <span v-for="item in probe.problems || []" :key="item">{{ item }}</span>
      </details>
    </div>
  </section>
</template>

<style scoped>
.config-page { display: grid; gap: 18px; padding: 22px; max-width: 980px; }
header { display: grid; gap: 6px; }
h2 { margin: 0; }
p { margin: 0; opacity: .72; line-height: 1.6; }
.discovery-card { display: grid; gap: 12px; padding: 14px 16px; border: 1px solid rgba(var(--v-theme-primary, 59, 130, 246), .24); border-radius: 10px; background: rgba(var(--v-theme-primary, 59, 130, 246), .06); }
.discovery-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.discovery-heading > div { display: grid; gap: 4px; }
.discovery-heading span { opacity: .72; line-height: 1.5; }
.discovery-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.discovery-heading button, .apply-discovery { padding: 9px 14px; border: 1px solid rgba(var(--v-theme-primary, 59, 130, 246), .35); border-radius: 8px; cursor: pointer; background: transparent; color: inherit; font: inherit; font-weight: 700; }
.discovery-actions .secondary { opacity: .78; }
.discovery-heading button:disabled, .apply-discovery:disabled { opacity: .5; cursor: default; }
.discovery-results { display: grid; gap: 7px; }
.discovery-row { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-top: 1px solid rgba(var(--v-border-color), .16); }
.discovery-row > div { display: grid; gap: 4px; min-width: 0; }
.discovery-row small { opacity: .68; overflow-wrap: anywhere; line-height: 1.45; }
.discovery-row b { font-size: .9em; }
.discovery-row .found { color: #087443; }
.discovery-row .optional { color: #6b7280; }
.discovery-row .missing { color: #b86b11; }
.apply-discovery { justify-self: start; background: rgb(var(--v-theme-primary)); color: rgb(var(--v-theme-on-primary)); }
.discovery-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #b42318; line-height: 1.5; }
.discovery-error button { border: 0; padding: 0; cursor: pointer; background: transparent; color: inherit; font: inherit; font-weight: 700; text-decoration: underline; }
.advanced-settings { display: grid; gap: 12px; padding: 2px 0; }
.advanced-settings summary { cursor: pointer; font-weight: 700; }
.advanced-settings > p { padding-left: 2px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
label { display: grid; gap: 7px; font-weight: 600; }
input, textarea { width: 100%; box-sizing: border-box; padding: 9px 11px; border: 1px solid rgba(var(--v-border-color), .35); border-radius: 8px; background: transparent; color: inherit; font: inherit; font-weight: 400; }
textarea { resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; }
.wide { grid-column: 1 / -1; }
.notice, .error, .success, .probe { display: grid; gap: 5px; padding: 12px 14px; border-radius: 9px; }
.notice { background: rgba(128, 128, 128, .12); }
.error { color: #b42318; background: rgba(180, 35, 24, .1); }
.success { color: #087443; background: rgba(8, 116, 67, .1); }
.probe { background: rgba(32, 106, 255, .08); }
.probe-details { display: grid; gap: 5px; margin-top: 4px; }
.probe-details summary { cursor: pointer; font-weight: 700; }
.save { justify-self: start; padding: 10px 18px; border: 0; border-radius: 8px; cursor: pointer; background: rgb(var(--v-theme-primary)); color: rgb(var(--v-theme-on-primary)); }
.save:disabled { opacity: .5; cursor: default; }
@media (max-width: 760px) { .config-page { padding: 16px; } .form-grid { grid-template-columns: 1fr; } .wide { grid-column: auto; } .discovery-heading { align-items: stretch; flex-direction: column; } .discovery-actions { justify-content: flex-start; } }
</style>
