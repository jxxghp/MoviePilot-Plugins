<script setup>
import { computed, onUnmounted, ref } from 'vue'

const props = defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  provider: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'OidcAuth',
  },
})

const emit = defineEmits(['authenticated', 'error', 'close'])

const loading = ref(false)
const errorMessage = ref('')
let popupTimer = null

const pluginBase = computed(() => `plugin/${props.pluginId || 'OidcAuth'}`)
const providerName = computed(() => props.provider?.name || 'OIDC 登录')

/** 拼接 API 路径为可用于 window.open 的 URL。 */
function buildApiUrl(path) {
  const base = props.api?.defaults?.baseURL || '/api/v1/'
  const normalizedBase = base.endsWith('/') ? base : `${base}/`
  const normalizedPath = String(path || '').replace(/^\/+/, '')
  return `${normalizedBase}${normalizedPath}`
}

/** 关闭弹窗轮询并清理状态。 */
function clearPopupTimer() {
  if (popupTimer) {
    clearInterval(popupTimer)
    popupTimer = null
  }
}

/** 处理 OIDC 回调窗口发回的认证消息。 */
function handleOidcMessage(event) {
  if (event.origin !== window.location.origin) return
  if (event.data?.type !== 'oidcauth_callback') return
  window.removeEventListener('message', handleOidcMessage)
  clearPopupTimer()
  loading.value = false
  if (event.data.success && event.data.data?.ticket) {
    emit('authenticated', { ticket: event.data.data.ticket })
    return
  }
  const message = event.data?.message || 'OIDC 认证失败'
  errorMessage.value = message
  emit('error', { message })
}

/** 发起 OIDC 登录授权弹窗。 */
function startLogin() {
  errorMessage.value = ''
  loading.value = true
  window.addEventListener('message', handleOidcMessage)
  const popup = window.open(
    buildApiUrl(`${pluginBase.value}/authorize`),
    'moviepilot_oidc_login',
    'width=600,height=720,left=200,top=80',
  )
  if (!popup) {
    loading.value = false
    window.removeEventListener('message', handleOidcMessage)
    errorMessage.value = '浏览器阻止了认证弹窗'
    emit('error', { message: errorMessage.value })
    return
  }
  popupTimer = setInterval(() => {
    if (!popup.closed) return
    clearPopupTimer()
    window.removeEventListener('message', handleOidcMessage)
    if (loading.value) {
      loading.value = false
      errorMessage.value = '认证窗口已关闭'
      emit('error', { message: errorMessage.value })
    }
  }, 500)
}

/** 组件卸载时清理监听器和定时器。 */
onUnmounted(() => {
  clearPopupTimer()
  window.removeEventListener('message', handleOidcMessage)
})
</script>

<template>
  <div class="oidc-auth-page">
    <VAlert v-if="errorMessage" type="error" variant="tonal" class="mb-4">
      {{ errorMessage }}
    </VAlert>
    <VBtn block color="primary" prepend-icon="mdi-openid" :loading="loading" @click="startLogin">
      {{ providerName }}
    </VBtn>
    <VBtn block variant="text" class="mt-2" @click="emit('close')">取消</VBtn>
  </div>
</template>
