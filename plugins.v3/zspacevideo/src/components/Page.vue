<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import Watched from './Watched.vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'ZSpaceVideo' },
  show_switch: { type: Boolean, default: true },
})
const emit = defineEmits(['close', 'switch'])
const base = computed(() => `plugin/${props.pluginId || 'ZSpaceVideo'}`)

const status = ref({})
const libraries = ref([])
const librarySource = ref('')
const history = ref([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const login = ref({ url: '', expires_in: 0, started: 0 })
const code = ref('')
const submitting = ref(false)
const now = ref(Date.now())
let timer = null
const tab = ref('watched')

function unwrap(res) {
  if (res && typeof res === 'object' && 'success' in res) {
    if (!res.success) throw new Error(res.message || '请求失败')
    return res.data
  }
  return res
}

const remaining = computed(() => {
  if (!login.value.url) return 0
  const left = login.value.expires_in - Math.floor((now.value - login.value.started) / 1000)
  return Math.max(0, left)
})

const expiresText = computed(() => {
  const ts = status.value.expires_at
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
})

const statusLabel = { pending: '排队', running: '扫描中', done: '完成', failed: '失败' }
const statusColor = { pending: 'grey', running: 'info', done: 'success', failed: 'error' }

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : ''
}

async function loadStatus() {
  status.value = unwrap(await props.api.get(`${base.value}/status`)) || {}
}
async function loadLibraries(force = false) {
  const data = unwrap(await props.api.get(`${base.value}/libraries`, { params: { force } })) || {}
  libraries.value = data.libraries || []
  librarySource.value = data.source || ''
}
async function loadHistory() {
  history.value = unwrap(await props.api.get(`${base.value}/history`)) || []
}

async function reload(force = false) {
  loading.value = true
  error.value = ''
  try {
    await loadStatus()
    await loadHistory()
    if (status.value.logged_in) await loadLibraries(force)
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function startLogin() {
  error.value = ''
  notice.value = ''
  code.value = ''
  try {
    const data = unwrap(await props.api.post(`${base.value}/login/start`, {}))
    login.value = { url: data.url, expires_in: data.expires_in || 180, started: Date.now() }
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function submitCode() {
  if (!code.value.trim()) return
  submitting.value = true
  error.value = ''
  try {
    const payload = { code: code.value.trim() }
    code.value = ''
    unwrap(await props.api.post(`${base.value}/login/submit`, payload))
    payload.code = ''
    login.value = { url: '', expires_in: 0, started: 0 }
    notice.value = '授权成功'
    await reload(true)
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    submitting.value = false
  }
}

async function cancelLogin() {
  await props.api.post(`${base.value}/login/cancel`, {})
  login.value = { url: '', expires_in: 0, started: 0 }
  code.value = ''
}

async function logout() {
  if (!confirm('清除本插件保存的极空间授权？')) return
  try {
    unwrap(await props.api.post(`${base.value}/logout`, {}))
    notice.value = '已清除本地授权'
    await reload()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function refreshLibrary(lib) {
  error.value = ''
  try {
    unwrap(await props.api.post(`${base.value}/refresh`, { library_id: lib.id }))
    notice.value = `已提交刷新：${lib.name}`
    setTimeout(loadHistory, 1500)
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(() => {
  reload()
  timer = setInterval(() => {
    now.value = Date.now()
    if (now.value % 10000 < 1000) loadHistory().catch(() => {})
  }, 1000)
})
onUnmounted(() => timer && clearInterval(timer))
</script>

<template>
  <div class="zsv-page">
    <VToolbar density="comfortable" class="zsv-toolbar">
      <div class="text-h6 ms-3">极空间影视</div>
      <VSpacer />
      <VBtn icon="mdi-refresh" variant="text" :loading="loading" aria-label="刷新" @click="reload(true)" />
      <VBtn v-if="props.show_switch" icon="mdi-cog-outline" variant="text" aria-label="插件设置" @click="emit('switch')" />
      <VBtn icon="mdi-close" variant="text" aria-label="关闭" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <VTabs v-model="tab" density="comfortable" class="px-2">
      <VTab value="watched">已看</VTab>
      <VTab value="refresh">授权与刷新</VTab>
    </VTabs>
    <VDivider />
    <div v-if="tab === 'watched'" class="pa-4">
      <div v-if="!status.logged_in && !loading" class="text-medium-emphasis">先在「授权与刷新」里完成极空间授权</div>
      <Watched v-else :api="props.api" :base="base" />
    </div>
    <div v-show="tab === 'refresh'" class="pa-4">
      <VAlert v-if="error" type="error" variant="tonal" class="mb-3" closable @click:close="error = ''">{{ error }}</VAlert>
      <VAlert v-if="notice" type="success" variant="tonal" class="mb-3" closable @click:close="notice = ''">{{ notice }}</VAlert>

      <VCard variant="outlined" class="mb-4">
        <VCardTitle class="text-subtitle-1">授权</VCardTitle>
        <VCardText>
          <div class="d-flex flex-wrap ga-4 align-center mb-2">
            <VChip :color="status.logged_in ? 'success' : 'warning'" variant="tonal">
              {{ status.logged_in ? '已授权' : '未授权' }}
            </VChip>
            <span v-if="status.nas_id">设备 {{ status.nas_id }}</span>
            <span v-if="status.logged_in">令牌到期 {{ expiresText }}（到期前自动续期）</span>
            <span>连接：{{ status.connection_mode === 'lan' ? '局域网直连' : '官方云中转' }}</span>
            <span v-if="status.binary">zspace-cli {{ status.binary.version }}{{ status.binary.installed ? '' : '（未下载）' }}</span>
          </div>
          <div v-if="!login.url" class="d-flex ga-2">
            <VBtn color="primary" prepend-icon="mdi-shield-key-outline" @click="startLogin">
              {{ status.logged_in ? '重新授权' : '开始授权' }}
            </VBtn>
            <VBtn v-if="status.logged_in" variant="text" color="error" @click="logout">清除授权</VBtn>
          </div>
          <div v-else>
            <p class="mb-2">
              打开下面的链接，用极空间账号登录并同意授权，然后把页面上显示的一次性授权码粘贴回来。
              剩余 <b>{{ remaining }}</b> 秒，超时请重新开始。
            </p>
            <p class="mb-3"><a :href="login.url" target="_blank" rel="noopener noreferrer">打开极空间授权页面</a></p>
            <div class="d-flex ga-2 align-center">
              <VTextField v-model="code" label="一次性授权码" type="password" autocomplete="off"
                          density="comfortable" hide-details :disabled="remaining === 0" @keyup.enter="submitCode" />
              <VBtn color="primary" :loading="submitting" :disabled="!code || remaining === 0" @click="submitCode">提交</VBtn>
              <VBtn variant="text" @click="cancelLogin">取消</VBtn>
            </div>
          </div>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="mb-4">
        <VCardTitle class="text-subtitle-1">
          分类
          <span class="text-caption ms-2">目录来源：{{ librarySource === 'zvideo.db' ? '极影视库（只读）' : librarySource === 'manual' ? '手动配置' : '无' }}</span>
        </VCardTitle>
        <VCardText>
          <div v-if="!status.logged_in" class="text-medium-emphasis">授权后显示</div>
          <VTable v-else density="compact">
            <thead><tr><th>分类</th><th>目录</th><th>状态</th><th /></tr></thead>
            <tbody>
              <tr v-for="lib in libraries" :key="lib.id">
                <td>{{ lib.name }}<span v-if="lib.is_system" class="text-caption"> · 智能</span></td>
                <td>
                  <div v-for="d in lib.dirs" :key="d" class="text-caption">{{ d }}</div>
                  <span v-if="!lib.dirs.length" class="text-caption text-warning">未知目录，不会自动刷新</span>
                </td>
                <td>{{ lib.scan_status === 0 ? '空闲' : lib.scan_status == null ? '—' : '扫描中' }}</td>
                <td><VBtn size="small" variant="tonal" :disabled="!lib.dirs.length" @click="refreshLibrary(lib)">立即刷新</VBtn></td>
              </tr>
            </tbody>
          </VTable>
        </VCardText>
      </VCard>

      <VCard variant="outlined">
        <VCardTitle class="text-subtitle-1">最近刷新</VCardTitle>
        <VCardText>
          <div v-if="!history.length" class="text-medium-emphasis">还没有记录</div>
          <VTable v-else density="compact">
            <thead><tr><th>时间</th><th>来源</th><th>分类</th><th>目录</th><th>结果</th></tr></thead>
            <tbody>
              <tr v-for="h in history.slice(0, 50)" :key="h.id">
                <td class="text-caption">{{ fmtTime(h.created_at) }}</td>
                <td class="text-caption">{{ h.trigger === 'manual' ? '手动' : (h.sources || []).join('、') || '整理' }}</td>
                <td>{{ h.library_name }}</td>
                <td><div v-for="p in h.paths" :key="p" class="text-caption">{{ p }}</div></td>
                <td>
                  <VChip size="small" :color="statusColor[h.status]" variant="tonal">{{ statusLabel[h.status] || h.status }}</VChip>
                  <div v-if="h.status === 'failed'" class="text-caption text-error">{{ h.message }}</div>
                </td>
              </tr>
            </tbody>
          </VTable>
        </VCardText>
      </VCard>
    </div>
  </div>
</template>

<style scoped>
.zsv-toolbar { position: sticky; top: 0; z-index: 10; background: rgb(var(--v-theme-surface)); }
</style>
