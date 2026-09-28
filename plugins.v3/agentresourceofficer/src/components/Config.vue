<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { CLIENT_TYPES, cloneConfig, maskSecret, unwrapResponse } from '../provider'

const props = defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'AgentResourceOfficer',
  },
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['save', 'close'])

const config = ref({})
const message = reactive({ text: '', type: 'info' })
const showCookie = ref(false)
const showFeishuSecret = ref(false)
const showHdhiveApiKey = ref(false)
const showHdhiveAccessToken = ref(false)
const showHdhiveRefreshToken = ref(false)
const showHdhiveCookie = ref(false)
const showHdhivePassword = ref(false)
const saving = ref(false)
const healthLoading = ref(false)
const health = ref(null)

const qr = reactive({
  show: false,
  loading: false,
  error: '',
  qrcode: '',
  uid: '',
  time: '',
  sign: '',
  tips: '请使用 115 客户端扫描二维码登录',
  status: '等待扫码',
  clientType: 'alipaymini',
  timer: null,
  requestId: 0,
  checking: false,
})

const pluginBase = computed(() => `plugin/${props.pluginId || 'AgentResourceOfficer'}`)
const p115ReadyText = computed(() => {
  if (!health.value) return config.value.p115_cookie ? '已配置 Cookie' : '未检测'
  if (health.value.p115_ready) return '115 可用'
  return health.value.message || '115 未就绪'
})

function enableChip(value) {
  return value
    ? { text: '已启用', color: 'success' }
    : { text: '未启用', color: 'grey' }
}

function showMessage(text, type = 'info') {
  message.text = text
  message.type = type
  if (text) {
    setTimeout(() => {
      if (message.text === text) message.text = ''
    }, 3500)
  }
}

async function persistConfig({ silent = false } = {}) {
  saving.value = true
  try {
    const response = await withTimeout(
      props.api.post(`${pluginBase.value}/config/save`, cloneConfig(config.value)),
      12000,
      '保存配置超时，请稍后重试'
    )
    const result = unwrapResponse(response)
    if (!result?.success) {
      throw new Error(result?.message || '保存配置失败')
    }
    if (result.data) {
      config.value = cloneConfig(result.data)
    }
    emit('save', cloneConfig(config.value))
    if (!silent) showMessage(result.message || '配置已保存', 'success')
    return true
  } catch (err) {
    if (!silent) showMessage(err?.message || '保存配置失败', 'error')
    return false
  } finally {
    saving.value = false
  }
}

function saveConfig() {
  persistConfig()
}

async function copyText(value, label) {
  try {
    await navigator.clipboard.writeText(String(value || ''))
    showMessage(`${label} 已复制`, 'success')
  } catch (err) {
    showMessage('复制失败，请手动复制', 'error')
  }
}

function clearQrTimer() {
  if (qr.timer) {
    clearInterval(qr.timer)
    qr.timer = null
  }
}

function applyQrData(data) {
  qr.qrcode = data?.qrcode || ''
  qr.uid = data?.uid || ''
  qr.time = data?.time || ''
  qr.sign = data?.sign || ''
  qr.tips = data?.tips || '请使用 115 客户端扫描二维码登录'
  qr.status = '等待扫码'
}

function withTimeout(promise, ms, message) {
  let timeoutId
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(message)), ms)
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId))
}

async function requestQrCode() {
  const requestId = qr.requestId + 1
  qr.requestId = requestId
  qr.loading = true
  qr.error = ''
  qr.qrcode = ''
  qr.uid = ''
  qr.time = ''
  qr.sign = ''
  clearQrTimer()
  try {
    const response = await withTimeout(
      props.api.get(`${pluginBase.value}/p115/ui/qrcode?client_type=${encodeURIComponent(qr.clientType)}`),
      12000,
      '获取二维码超时，请稍后重试'
    )
    if (requestId !== qr.requestId || !qr.show) return
    const result = unwrapResponse(response)
    if (!result?.success || !result?.data) {
      throw new Error(result?.message || '获取二维码失败')
    }
    applyQrData(result.data)
    qr.timer = setInterval(() => checkQrCode(requestId), 3000)
  } catch (err) {
    if (requestId !== qr.requestId) return
    qr.error = err?.message || '获取二维码失败'
    qr.status = '二维码获取失败'
  } finally {
    if (requestId === qr.requestId) {
      qr.loading = false
    }
  }
}

async function checkQrCode(requestId = qr.requestId) {
  if (!qr.show || !qr.uid || !qr.time || !qr.sign) return
  if (requestId !== qr.requestId || qr.checking) return
  qr.checking = true
  try {
    const query = new URLSearchParams({
      uid: qr.uid,
      time: qr.time,
      sign: qr.sign,
      client_type: qr.clientType,
    })
    const response = await withTimeout(
      props.api.get(`${pluginBase.value}/p115/ui/qrcode/check?${query.toString()}`),
      10000,
      '检查二维码状态超时'
    )
    if (requestId !== qr.requestId || !qr.show) return
    const result = unwrapResponse(response)
    const data = result?.data || {}
    if (!result?.success) {
      if (data.status === 'expired') {
        clearQrTimer()
        qr.status = '二维码已失效'
        qr.error = result?.message || '二维码已失效，请刷新'
      }
      return
    }
    if (data.status === 'waiting') qr.status = '等待扫码'
    if (data.status === 'scanned') qr.status = '已扫码，请在设备上确认'
    if (data.status === 'expired') {
      clearQrTimer()
      qr.status = '二维码已失效'
      qr.error = '二维码已失效，请刷新'
    }
    if (data.status === 'success') {
      clearQrTimer()
      qr.status = '登录成功'
      if (data.cookie_saved) {
        config.value.p115_client_type = qr.clientType
        if (data.cookie) config.value.p115_cookie = data.cookie
        await persistConfig({ silent: true })
      }
      showMessage('115 登录成功，Cookie 已自动保存。', 'success')
      setTimeout(() => {
        qr.show = false
      }, 1800)
      await loadP115Health()
    }
  } catch (err) {
    console.error('检查 115 二维码状态失败:', err)
  } finally {
    if (requestId === qr.requestId) {
      qr.checking = false
    }
  }
}

function openQrDialog() {
  qr.show = true
  qr.error = ''
  qr.status = '等待扫码'
  qr.clientType = config.value.p115_client_type || 'alipaymini'
  requestQrCode()
}

function closeQrDialog() {
  clearQrTimer()
  qr.requestId += 1
  qr.loading = false
  qr.checking = false
  qr.show = false
}

async function refreshQrCode() {
  qr.error = ''
  await requestQrCode()
}

async function changeQrClientType(value) {
  if (!value || value === qr.clientType) return
  qr.clientType = value
  qr.error = ''
  await requestQrCode()
}

async function loadP115Health() {
  if (!props.api?.get) return
  healthLoading.value = true
  try {
    const response = await props.api.get(`${pluginBase.value}/p115/ui/health`)
    const result = unwrapResponse(response)
    if (result?.success) {
      health.value = result.data || null
    }
  } catch (err) {
    health.value = { p115_ready: false, message: err?.message || '检测失败' }
  } finally {
    healthLoading.value = false
  }
}

async function loadLatestConfig() {
  if (!props.api?.get) return false
  try {
    const response = await withTimeout(
      props.api.get(`${pluginBase.value}/config/get`),
      12000,
      '加载配置超时'
    )
    const result = unwrapResponse(response)
    if (result?.success && result.data) {
      config.value = cloneConfig(result.data)
      if (!config.value.p115_client_type) config.value.p115_client_type = 'alipaymini'
      return true
    }
  } catch (err) {
    console.error('加载 Agent影视助手 配置失败:', err)
  }
  return false
}

onMounted(async () => {
  config.value = cloneConfig(props.initialConfig)
  if (!config.value.p115_client_type) config.value.p115_client_type = 'alipaymini'
  await loadLatestConfig()
  loadP115Health()
})

onBeforeUnmount(clearQrTimer)
</script>

<template>
  <div class="aro-config">
    <VToolbar density="comfortable" color="transparent" class="aro-toolbar">
      <VIcon icon="mdi-robot-outline" color="primary" class="ms-3 me-2" />
      <div class="text-h6">Agent影视助手配置</div>
      <VSpacer />
      <VBtn icon="mdi-refresh" variant="text" :loading="healthLoading" title="刷新 115 状态" @click="loadP115Health" />
      <VBtn icon="mdi-content-save" variant="text" color="success" :loading="saving" title="保存配置" @click="saveConfig" />
      <VBtn icon="mdi-close" variant="text" title="关闭" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <div class="aro-body">
      <div class="aro-inner">
      <VAlert v-if="message.text" :type="message.type" variant="tonal" density="compact" closable class="mb-3">
        {{ message.text }}
      </VAlert>

      <div class="aro-intro text-body-2 mb-3">
        <VIcon icon="mdi-rocket-launch-outline" size="small" color="primary" class="me-1" />
        <span>快速开始：先启用插件并配置 MP/PT，再按需开启影巢、盘搜与飞书入口；完整说明见</span>
        <a href="https://github.com/liuyuexi1987/MoviePilot-Plugins" target="_blank" rel="noopener" class="text-primary text-decoration-none font-weight-medium">主页文档</a>。
      </div>

      <VCard variant="outlined" class="aro-card mb-3 rounded-lg">
        <VCardItem class="aro-card-head">
          <template #prepend>
            <VIcon icon="mdi-toggle-switch" color="primary" />
          </template>
          <VCardTitle class="text-subtitle-1">基础设置</VCardTitle>
          <VCardSubtitle class="text-caption">启用插件、通知与调试开关</VCardSubtitle>
          <template #append>
            <VChip :color="enableChip(config.enabled).color" size="small" variant="tonal">{{ enableChip(config.enabled).text }}</VChip>
          </template>
        </VCardItem>
        <VCardText class="pt-2">
          <VRow dense>
            <VCol cols="12" md="4">
              <VSwitch v-model="config.enabled" label="启用插件" color="success" density="compact" hide-details />
            </VCol>
            <VCol cols="12" md="4">
              <VSwitch v-model="config.notify" label="发送通知" color="success" density="compact" hide-details />
            </VCol>
            <VCol cols="12" md="4">
              <VSwitch v-model="config.debug" label="调试日志" color="warning" density="compact" hide-details />
            </VCol>
          </VRow>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="aro-card mb-3 rounded-lg">
        <VCardItem class="aro-card-head">
          <template #prepend>
            <VIcon icon="mdi-movie-search-outline" color="primary" />
          </template>
          <VCardTitle class="text-subtitle-1">MP/PT 策略</VCardTitle>
          <VCardSubtitle class="text-caption">首选主线：原生搜索/订阅/下载；评分仅影响未保存偏好的新会话</VCardSubtitle>
          <template #append>
            <VChip :color="enableChip(config.mp_pt_enabled).color" size="small" variant="tonal">{{ enableChip(config.mp_pt_enabled).text }}</VChip>
          </template>
        </VCardItem>
        <VCardText class="pt-2">
          <VRow dense>
            <VCol cols="12" sm="6" md="3">
              <VSwitch v-model="config.mp_pt_enabled" label="启用 MP/PT" color="success" density="compact" hide-details />
            </VCol>
            <VCol cols="6" sm="3" md="3">
              <VTextField v-model="config.assistant_default_pt_min_seeders" label="最低做种数" type="number" placeholder="3" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="6" sm="3" md="3">
              <VTextField v-model="config.assistant_default_confirm_score_threshold" label="建议确认分" type="number" placeholder="70" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="6" sm="3" md="3">
              <VTextField v-model="config.assistant_default_auto_ingest_score_threshold" label="自动入库分" type="number" placeholder="90" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" sm="6" md="3">
              <VSwitch v-model="config.assistant_default_auto_ingest_enabled" label="高分自动入库" color="primary" density="compact" hide-details />
            </VCol>
            <VCol cols="12" sm="6" md="9">
              <VTextField v-model="config.mp_download_save_path" label="PT 下载保存路径（可选）" placeholder="默认留空；需要时填 local:/downloads 等" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
          </VRow>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="aro-card mb-3 rounded-lg">
        <VCardItem class="aro-card-head">
          <template #prepend>
            <VIcon icon="mdi-cloud-lock-outline" color="primary" />
          </template>
          <VCardTitle class="text-subtitle-1">115 扫码登录</VCardTitle>
          <VCardSubtitle class="text-caption">扫码写入 Cookie，手填仅作兜底</VCardSubtitle>
          <template #append>
            <VChip :color="health?.p115_ready ? 'success' : 'warning'" size="small" variant="tonal">{{ p115ReadyText }}</VChip>
          </template>
        </VCardItem>
        <VCardText class="pt-2">
          <VRow dense align="center">
            <VCol cols="12" sm="6" md="4">
              <VTextField v-model="config.p115_default_path" label="115 默认目录" placeholder="/待整理" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" sm="6" md="4">
              <VSelect v-model="config.p115_client_type" :items="CLIENT_TYPES" item-title="title" item-value="value" label="智能体扫码默认客户端" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" md="4">
              <VSwitch v-model="config.p115_prefer_direct" label="优先 115 直转" color="primary" density="compact" hide-details />
            </VCol>
            <VCol cols="12">
              <VTextField
                :model-value="maskSecret(config.p115_cookie, showCookie)"
                label="115 Cookie"
                variant="outlined"
                density="compact"
                hide-details="auto"
                readonly
                hint="点击右侧二维码图标扫码，成功后自动保存 Cookie。"
                persistent-hint
              >
                <template #append-inner>
                  <VIcon :icon="showCookie ? 'mdi-eye-off' : 'mdi-eye'" class="me-2" size="small" @click="showCookie = !showCookie" />
                  <VIcon icon="mdi-content-copy" class="me-2" size="small" :disabled="!config.p115_cookie" @click="copyText(config.p115_cookie, '115 Cookie')" />
                </template>
                <template #append>
                  <VIcon icon="mdi-qrcode-scan" :color="config.p115_cookie ? 'success' : 'primary'" title="扫码获取或更新 115 Cookie" @click="openQrDialog" />
                </template>
              </VTextField>
            </VCol>
          </VRow>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="aro-card mb-3 rounded-lg">
        <VCardItem class="aro-card-head">
          <template #prepend>
            <VIcon icon="mdi-honeycomb-outline" color="primary" />
          </template>
          <VCardTitle class="text-subtitle-1">影巢资源</VCardTitle>
          <VCardSubtitle class="text-caption">资源搜索 / 解锁 / 转存；积分上限填 0 不限制</VCardSubtitle>
          <template #append>
            <VChip :color="enableChip(config.hdhive_resource_enabled).color" size="small" variant="tonal">{{ enableChip(config.hdhive_resource_enabled).text }}</VChip>
          </template>
        </VCardItem>
        <VCardText class="pt-2">
          <VRow dense>
            <VCol cols="12" sm="6" md="3">
              <VSwitch v-model="config.hdhive_resource_enabled" label="启用搜索/解锁" color="success" density="compact" hide-details />
            </VCol>
            <VCol cols="12" sm="6" md="3">
              <VSelect
                v-model="config.hdhive_resource_mode"
                :items="[
                  { title: '网页方式', value: 'browser' },
                  { title: 'OpenAPI', value: 'openapi' },
                  { title: '自动(网页优先)', value: 'auto' },
                ]"
                item-title="title"
                item-value="value"
                label="资源方式"
                variant="outlined"
                density="compact"
                hide-details="auto"
              />
            </VCol>
            <VCol cols="6" sm="3" md="3">
              <VTextField v-model="config.hdhive_max_unlock_points" label="积分上限" type="number" placeholder="20" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="6" sm="3" md="3">
              <VTextField v-model="config.hdhive_candidate_page_size" label="候选页大小" type="number" placeholder="10" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="6" sm="3" md="3">
              <VTextField v-model="config.hdhive_timeout" label="超时(秒)" type="number" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model="config.hdhive_base_url" label="影巢地址" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model="config.hdhive_default_path" label="影巢默认转存目录" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model="config.hdhive_api_key" :type="showHdhiveApiKey ? 'text' : 'password'" label="影巢 API Key" variant="outlined" density="compact" hide-details="auto">
                <template #append-inner>
                  <VIcon :icon="showHdhiveApiKey ? 'mdi-eye-off' : 'mdi-eye'" class="me-2" size="small" @click="showHdhiveApiKey = !showHdhiveApiKey" />
                  <VIcon icon="mdi-content-copy" size="small" :disabled="!config.hdhive_api_key" @click="copyText(config.hdhive_api_key, '影巢 API Key')" />
                </template>
              </VTextField>
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model="config.hdhive_openapi_user_token" :type="showHdhiveAccessToken ? 'text' : 'password'" label="OpenAPI Access Token" variant="outlined" density="compact" hide-details="auto">
                <template #append-inner>
                  <VIcon :icon="showHdhiveAccessToken ? 'mdi-eye-off' : 'mdi-eye'" class="me-2" size="small" @click="showHdhiveAccessToken = !showHdhiveAccessToken" />
                  <VIcon icon="mdi-content-copy" size="small" :disabled="!config.hdhive_openapi_user_token" @click="copyText(config.hdhive_openapi_user_token, '影巢 Access Token')" />
                </template>
              </VTextField>
            </VCol>
            <VCol cols="12">
              <VTextField v-model="config.hdhive_openapi_refresh_token" :type="showHdhiveRefreshToken ? 'text' : 'password'" label="OpenAPI Refresh Token（可选）" variant="outlined" density="compact" hide-details="auto">
                <template #append-inner>
                  <VIcon :icon="showHdhiveRefreshToken ? 'mdi-eye-off' : 'mdi-eye'" class="me-2" size="small" @click="showHdhiveRefreshToken = !showHdhiveRefreshToken" />
                  <VIcon icon="mdi-content-copy" size="small" :disabled="!config.hdhive_openapi_refresh_token" @click="copyText(config.hdhive_openapi_refresh_token, '影巢 Refresh Token')" />
                </template>
              </VTextField>
            </VCol>
          </VRow>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="aro-card mb-3 rounded-lg">
        <VCardItem class="aro-card-head">
          <template #prepend>
            <VIcon icon="mdi-calendar-check-outline" color="primary" />
          </template>
          <VCardTitle class="text-subtitle-1">影巢签到</VCardTitle>
          <VCardSubtitle class="text-caption">OpenAPI 优先，网页 Cookie 兜底，按 Cron 自动签到</VCardSubtitle>
          <template #append>
            <VChip :color="enableChip(config.hdhive_checkin_enabled).color" size="small" variant="tonal">{{ enableChip(config.hdhive_checkin_enabled).text }}</VChip>
          </template>
        </VCardItem>
        <VCardText class="pt-2">
          <VRow dense>
            <VCol cols="6" md="3">
              <VSwitch v-model="config.hdhive_checkin_enabled" label="启用签到" color="success" density="compact" hide-details />
            </VCol>
            <VCol cols="6" md="3">
              <VSwitch v-model="config.hdhive_checkin_gambler_mode" label="默认赌狗签到" color="warning" density="compact" hide-details />
            </VCol>
            <VCol cols="6" md="3">
              <VSwitch v-model="config.hdhive_checkin_once" label="保存后立即运行" color="primary" density="compact" hide-details />
            </VCol>
            <VCol cols="6" md="3">
              <VSwitch v-model="config.hdhive_checkin_auto_login" label="自动刷新 Cookie" color="primary" density="compact" hide-details />
            </VCol>
            <VCol cols="12" sm="4" md="4">
              <VTextField v-model="config.hdhive_checkin_cron" label="签到 Cron" placeholder="0 8 * * *" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" sm="4" md="4">
              <VTextField v-model="config.hdhive_checkin_username" label="影巢用户名/邮箱" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" sm="4" md="4">
              <VTextField v-model="config.hdhive_checkin_password" :type="showHdhivePassword ? 'text' : 'password'" label="影巢密码" variant="outlined" density="compact" hide-details="auto">
                <template #append-inner>
                  <VIcon :icon="showHdhivePassword ? 'mdi-eye-off' : 'mdi-eye'" size="small" @click="showHdhivePassword = !showHdhivePassword" />
                </template>
              </VTextField>
            </VCol>
            <VCol cols="12">
              <VTextField
                v-model="config.hdhive_checkin_cookie"
                :type="showHdhiveCookie ? 'text' : 'password'"
                label="影巢网页 Cookie（非 Premium 兜底）"
                variant="outlined"
                density="compact"
                hide-details="auto"
              >
                <template #append-inner>
                  <VIcon :icon="showHdhiveCookie ? 'mdi-eye-off' : 'mdi-eye'" class="me-2" size="small" @click="showHdhiveCookie = !showHdhiveCookie" />
                  <VIcon icon="mdi-content-copy" size="small" :disabled="!config.hdhive_checkin_cookie" @click="copyText(config.hdhive_checkin_cookie, '影巢 Cookie')" />
                </template>
              </VTextField>
            </VCol>
          </VRow>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="aro-card mb-3 rounded-lg">
        <VCardItem class="aro-card-head">
          <template #prepend>
            <VIcon icon="mdi-magnify-scan" color="primary" />
          </template>
          <VCardTitle class="text-subtitle-1">盘搜</VCardTitle>
          <VCardSubtitle class="text-caption">聚合公开网盘分享，地址需容器视角可访问</VCardSubtitle>
          <template #append>
            <VChip :color="enableChip(config.pansou_enabled).color" size="small" variant="tonal">{{ enableChip(config.pansou_enabled).text }}</VChip>
          </template>
        </VCardItem>
        <VCardText class="pt-2">
          <VRow dense>
            <VCol cols="12" sm="3" md="3">
              <VSwitch v-model="config.pansou_enabled" label="启用盘搜" color="success" density="compact" hide-details />
            </VCol>
            <VCol cols="8" sm="6" md="6">
              <VTextField v-model="config.pansou_base_url" label="盘搜 API 地址" placeholder="http://host.docker.internal:805" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="4" sm="3" md="3">
              <VTextField v-model="config.pansou_timeout" label="超时(秒)" type="number" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
          </VRow>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="aro-card mb-3 rounded-lg">
        <VCardItem class="aro-card-head">
          <template #prepend>
            <VIcon icon="mdi-message-badge-outline" color="primary" />
          </template>
          <VCardTitle class="text-subtitle-1">飞书入口</VCardTitle>
          <VCardSubtitle class="text-caption">内置飞书机器人入口与会话白名单</VCardSubtitle>
          <template #append>
            <VChip :color="enableChip(config.feishu_enabled).color" size="small" variant="tonal">{{ enableChip(config.feishu_enabled).text }}</VChip>
          </template>
        </VCardItem>
        <VCardText class="pt-2">
          <VRow dense>
            <VCol cols="12" sm="4" md="4">
              <VSwitch v-model="config.feishu_enabled" label="启用飞书入口" color="success" density="compact" hide-details />
            </VCol>
            <VCol cols="6" sm="4" md="4">
              <VSwitch v-model="config.feishu_allow_all" label="允许所有会话" color="primary" density="compact" hide-details />
            </VCol>
            <VCol cols="6" sm="4" md="4">
              <VSwitch v-model="config.feishu_reply_enabled" label="发送飞书回复" color="primary" density="compact" hide-details />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField v-model="config.feishu_app_id" label="飞书 App ID" placeholder="cli_xxxxxxxxx" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField :type="showFeishuSecret ? 'text' : 'password'" v-model="config.feishu_app_secret" label="飞书 App Secret" variant="outlined" density="compact" hide-details="auto">
                <template #append-inner>
                  <VIcon :icon="showFeishuSecret ? 'mdi-eye-off' : 'mdi-eye'" size="small" @click="showFeishuSecret = !showFeishuSecret" />
                </template>
              </VTextField>
            </VCol>
            <VCol v-if="!config.feishu_allow_all" cols="12" class="py-0">
              <div class="text-caption text-medium-emphasis">未允许所有会话时，仅下列白名单中的群聊或用户可触发飞书命令。</div>
            </VCol>
            <VCol v-if="!config.feishu_allow_all" cols="12" md="6">
              <VTextarea v-model="config.feishu_allowed_chat_ids" label="允许的群聊 Chat ID" rows="2" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
            <VCol v-if="!config.feishu_allow_all" cols="12" md="6">
              <VTextarea v-model="config.feishu_allowed_user_ids" label="允许的用户 Open ID" rows="2" variant="outlined" density="compact" hide-details="auto" />
            </VCol>
          </VRow>
        </VCardText>
      </VCard>
      </div>
    </div>

    <VDialog v-model="qr.show" max-width="450" @update:model-value="value => !value && closeQrDialog()">
      <VCard>
        <VCardTitle class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5">
          <VIcon icon="mdi-qrcode" color="primary" size="small" class="me-2" />
          115网盘扫码登录
        </VCardTitle>
        <VCardText class="text-center py-4">
          <VAlert v-if="qr.error" type="error" density="compact" variant="tonal" closable class="mb-3 mx-3">
            {{ qr.error }}
          </VAlert>
          <div v-if="qr.loading" class="d-flex flex-column align-center py-3">
            <VProgressCircular indeterminate color="primary" class="mb-3" />
            <div>正在获取二维码...</div>
          </div>
          <div v-else-if="qr.qrcode" class="d-flex flex-column align-center">
            <div class="mb-2 font-weight-medium">请选择扫码方式</div>
            <VChipGroup :model-value="qr.clientType" class="mb-3" mandatory selected-class="primary" @update:model-value="changeQrClientType">
              <VChip v-for="item in CLIENT_TYPES" :key="item.value" :value="item.value" variant="outlined" color="primary" size="small">
                {{ item.label }}
              </VChip>
            </VChipGroup>
            <div class="d-flex flex-column align-center mb-3">
              <VCard flat class="border pa-2 mb-2">
                <img :src="qr.qrcode" width="220" height="220" alt="115 登录二维码" />
              </VCard>
              <div class="text-body-2 text-grey mb-1">{{ qr.tips }}</div>
              <div class="text-subtitle-2 font-weight-medium text-primary">{{ qr.status }}</div>
            </div>
            <VBtn color="primary" variant="tonal" size="small" class="mb-2" prepend-icon="mdi-refresh" :disabled="qr.loading" @click="refreshQrCode">
              刷新二维码
            </VBtn>
          </div>
          <div v-else class="d-flex flex-column align-center py-3">
            <VIcon icon="mdi-qrcode-off" size="64" color="grey" class="mb-3" />
            <div class="text-subtitle-1">二维码获取失败</div>
            <div class="text-body-2 text-grey">请点击刷新按钮重试</div>
          </div>
        </VCardText>
        <VDivider />
        <VCardActions class="px-3 py-2">
          <VBtn color="grey" variant="text" size="small" prepend-icon="mdi-close" @click="closeQrDialog">关闭</VBtn>
          <VSpacer />
          <VBtn color="primary" variant="text" size="small" prepend-icon="mdi-refresh" :disabled="qr.loading" @click="refreshQrCode">刷新二维码</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.aro-config {
  display: flex;
  flex-direction: column;
  max-height: 82vh;
}

.aro-toolbar {
  flex: 0 0 auto;
}

.aro-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 16px;
}

.aro-inner {
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
}

.aro-intro {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(var(--v-theme-primary), 0.06);
  color: rgb(var(--v-theme-on-surface));
  line-height: 1.5;
}

.aro-card-head {
  padding-bottom: 0;
}

.aro-card :deep(.v-card-item__append) {
  align-self: center;
}

.aro-card :deep(.v-card-subtitle) {
  opacity: 0.7;
  white-space: normal;
}
</style>
