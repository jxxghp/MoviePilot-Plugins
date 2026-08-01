<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'StorageCleanup' },
})

const form = reactive({
  version: 1,
  ssh_host: '',
  qb_url: '',
  jellyfin_db: '',
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
    ssh_host: form.ssh_host,
    qb_url: form.qb_url,
    jellyfin_db: form.jellyfin_db,
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
  } catch (err) {
    error.value = err?.message || '无法读取清理台配置。'
  } finally {
    loading.value = false
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
      <p>这里只保存 NAS 拓扑和路径，不会写入 Cookie、passkey 或控制令牌。保存后先做只读探测，未通过探测时清理操作保持锁定。</p>
    </header>

    <div v-if="loading" class="notice">正在读取配置…</div>
    <div v-else class="form-grid">
      <label>SSH 目标<input v-model="form.ssh_host" autocomplete="off" /></label>
      <label>qBittorrent 地址<input v-model="form.qb_url" autocomplete="off" /></label>
      <label>Jellyfin 数据库<input v-model="form.jellyfin_db" autocomplete="off" /></label>
      <label>MoviePilot 数据库<input v-model="form.moviepilot_db" autocomplete="off" /></label>
      <label>qB 种子备份目录<input v-model="form.qb_backup" autocomplete="off" /></label>
      <label>清理事务备份目录<input v-model="form.execution_backup" autocomplete="off" /></label>
      <label class="wide">允许扫描/清理的根目录（每行一个）<textarea v-model="form.allowed_roots_text" rows="6" /></label>
      <label class="wide">隔离目录映射（每行：卷根目录=隔离目录）<textarea v-model="form.quarantine_roots_text" rows="4" /></label>
    </div>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="message" class="success">{{ message }}</div>
    <div v-if="probe" class="probe">
      <strong>{{ probe.ok ? '只读探测通过' : '只读探测未通过' }}</strong>
      <span v-if="probe.missing?.length">未找到：{{ probe.missing.join('、') }}</span>
      <span v-for="item in probe.problems || []" :key="item">{{ item }}</span>
    </div>
    <button class="save" :disabled="loading || saving" @click="save">{{ saving ? '保存中…' : '保存并探测' }}</button>
  </section>
</template>

<style scoped>
.config-page { display: grid; gap: 18px; padding: 22px; max-width: 980px; }
header { display: grid; gap: 6px; }
h2 { margin: 0; }
p { margin: 0; opacity: .72; line-height: 1.6; }
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
.save { justify-self: start; padding: 10px 18px; border: 0; border-radius: 8px; cursor: pointer; background: rgb(var(--v-theme-primary)); color: rgb(var(--v-theme-on-primary)); }
.save:disabled { opacity: .5; cursor: default; }
@media (max-width: 760px) { .config-page { padding: 16px; } .form-grid { grid-template-columns: 1fr; } .wide { grid-column: auto; } }
</style>
