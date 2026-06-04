<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'OidcAuth',
  },
})

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const binding = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const status = ref({
  public: {},
  binding: {},
  config: null,
  is_superuser: false,
})
const config = ref({
  enabled: false,
  provider_name: 'OIDC 登录',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  redirect_uri: '',
  username_claim: 'preferred_username',
  email_claim: 'email',
  allow_auto_bind_by_username: false,
})
let bindPopupTimer = null

const pluginBase = computed(() => `plugin/${props.pluginId || 'OidcAuth'}`)
const isAdmin = computed(() => Boolean(status.value.is_superuser))
const isBound = computed(() => Boolean(status.value.binding?.bound))

/** 从 API 响应中解出 data 字段。 */
function unwrap(response) {
  if (response && Object.prototype.hasOwnProperty.call(response, 'data')) {
    return response.data
  }
  return response
}

/** 清理提示信息。 */
function clearMessages() {
  errorMessage.value = ''
  successMessage.value = ''
}

/** 从服务端加载插件状态、配置和绑定信息。 */
async function loadStatus() {
  loading.value = true
  clearMessages()
  try {
    const response = await props.api.get(`${pluginBase.value}/status`)
    status.value = unwrap(response) || status.value
    if (status.value.config) {
      config.value = { ...config.value, ...status.value.config }
    }
  } catch (error) {
    errorMessage.value = error?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

/** 保存管理员配置。 */
async function saveConfig() {
  saving.value = true
  clearMessages()
  try {
    const response = await props.api.post(`${pluginBase.value}/config`, config.value)
    const data = unwrap(response) || {}
    if (data.config) {
      config.value = { ...config.value, ...data.config }
    }
    successMessage.value = '配置已保存'
    await loadStatus()
  } catch (error) {
    errorMessage.value = error?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

/** 测试 OIDC Provider 发现文档。 */
async function testConnection() {
  testing.value = true
  clearMessages()
  try {
    const response = await props.api.post(`${pluginBase.value}/test`, config.value)
    if (response?.success) {
      successMessage.value = response.message || '连接正常'
    } else {
      errorMessage.value = response?.message || '连接失败'
    }
  } catch (error) {
    errorMessage.value = error?.message || '连接失败'
  } finally {
    testing.value = false
  }
}

/** 清理绑定弹窗轮询。 */
function clearBindPopupTimer() {
  if (bindPopupTimer) {
    clearInterval(bindPopupTimer)
    bindPopupTimer = null
  }
}

/** 处理绑定回调消息。 */
function handleBindMessage(event) {
  if (event.origin !== window.location.origin) return
  if (event.data?.type !== 'oidcauth_bind_callback') return
  window.removeEventListener('message', handleBindMessage)
  clearBindPopupTimer()
  binding.value = false
  if (event.data.success) {
    successMessage.value = 'OIDC 账号已绑定'
    loadStatus()
    return
  }
  errorMessage.value = event.data?.message || '绑定失败'
}

/** 发起账号绑定。 */
async function bindAccount() {
  binding.value = true
  clearMessages()
  try {
    const response = await props.api.post(`${pluginBase.value}/bind/start`, {})
    const authorizeUrl = response?.data?.authorize_url
    if (!response?.success || !authorizeUrl) {
      throw new Error(response?.message || '无法发起绑定')
    }
    window.addEventListener('message', handleBindMessage)
    const popup = window.open(authorizeUrl, 'moviepilot_oidc_bind', 'width=600,height=720,left=200,top=80')
    if (!popup) {
      window.removeEventListener('message', handleBindMessage)
      throw new Error('浏览器阻止了认证弹窗')
    }
    bindPopupTimer = setInterval(() => {
      if (!popup.closed) return
      clearBindPopupTimer()
      window.removeEventListener('message', handleBindMessage)
      if (binding.value) {
        binding.value = false
        loadStatus()
      }
    }, 500)
  } catch (error) {
    binding.value = false
    errorMessage.value = error?.message || '绑定失败'
  }
}

/** 解绑当前账号。 */
async function unbindAccount() {
  binding.value = true
  clearMessages()
  try {
    const response = await props.api.post(`${pluginBase.value}/unbind`, {})
    if (response?.success) {
      successMessage.value = 'OIDC 账号已解绑'
      await loadStatus()
    } else {
      errorMessage.value = response?.message || '解绑失败'
    }
  } catch (error) {
    errorMessage.value = error?.message || '解绑失败'
  } finally {
    binding.value = false
  }
}

/** 组件挂载时加载状态。 */
onMounted(loadStatus)

/** 组件卸载时清理绑定监听器。 */
onUnmounted(() => {
  clearBindPopupTimer()
  window.removeEventListener('message', handleBindMessage)
})
</script>

<template>
  <div class="oidc-auth-admin pa-4">
    <VAlert v-if="errorMessage" type="error" variant="tonal" class="mb-4">{{ errorMessage }}</VAlert>
    <VAlert v-if="successMessage" type="success" variant="tonal" class="mb-4">{{ successMessage }}</VAlert>

    <VCard :loading="loading" class="mb-4">
      <VCardItem>
        <VCardTitle>OIDC 账号绑定</VCardTitle>
        <VCardSubtitle v-if="isBound">已绑定 {{ status.binding?.masked_sub }}</VCardSubtitle>
        <VCardSubtitle v-else>当前账号尚未绑定 OIDC</VCardSubtitle>
      </VCardItem>
      <VCardText>
        <VBtn v-if="!isBound" color="primary" prepend-icon="mdi-openid" :loading="binding" @click="bindAccount">
          绑定 OIDC 账号
        </VBtn>
        <VBtn v-else color="error" variant="tonal" prepend-icon="mdi-link-off" :loading="binding" @click="unbindAccount">
          解绑 OIDC 账号
        </VBtn>
      </VCardText>
    </VCard>

    <VCard v-if="isAdmin">
      <VCardItem>
        <VCardTitle>OIDC Provider 配置</VCardTitle>
        <VCardSubtitle>{{ status.public?.redirect_uri }}</VCardSubtitle>
      </VCardItem>
      <VCardText>
        <VRow>
          <VCol cols="12" md="6">
            <VSwitch v-model="config.enabled" label="启用 OIDC 登录" color="primary" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="config.provider_name" label="入口名称" prepend-inner-icon="mdi-openid" />
          </VCol>
          <VCol cols="12">
            <VTextField v-model="config.issuer" label="Issuer" placeholder="https://idp.example.com" prepend-inner-icon="mdi-web" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="config.client_id" label="Client ID" prepend-inner-icon="mdi-identifier" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="config.client_secret" label="Client Secret" type="password" prepend-inner-icon="mdi-key" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="config.scopes" label="Scopes" placeholder="openid profile email" prepend-inner-icon="mdi-format-list-checks" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="config.redirect_uri" label="回调地址覆盖" placeholder="留空自动生成" prepend-inner-icon="mdi-call-made" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="config.username_claim" label="用户名 Claim" prepend-inner-icon="mdi-account" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="config.email_claim" label="邮箱 Claim" prepend-inner-icon="mdi-email" />
          </VCol>
          <VCol cols="12">
            <VSwitch v-model="config.allow_auto_bind_by_username" label="允许按用户名 Claim 自动绑定已有用户" color="primary" />
          </VCol>
        </VRow>
        <div class="d-flex flex-wrap gap-3 mt-2">
          <VBtn color="primary" prepend-icon="mdi-content-save" :loading="saving" @click="saveConfig">保存</VBtn>
          <VBtn color="info" variant="tonal" prepend-icon="mdi-connection" :loading="testing" @click="testConnection">测试连接</VBtn>
        </div>
      </VCardText>
    </VCard>
  </div>
</template>
