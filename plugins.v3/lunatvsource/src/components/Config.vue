<script setup>
import { onMounted, reactive, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'LunaTVSource' },
  initialConfig: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['save', 'close'])
const saving = ref(false)
const message = reactive({ text: '', type: 'info' })
const defaults = {
  enabled: false,
  config_url: 'https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json',
  source_allowlist: '',
  mode: 'download',
  source_strategy: 'first',
  download_root: '',
  use_moviepilot_dirs: true,
  ffmpeg_path: 'ffmpeg',
  queue_minutes: 1,
  ai_enabled: true,
  tmdb_association: true,
  moviepilot_organize: true,
  native_recognize: true,
  mediaserver_name: '',
}
const config = reactive({ ...defaults })

function showMessage(text, type = 'info') {
  message.text = text
  message.type = type
  if (text) setTimeout(() => { if (message.text === text) message.text = '' }, 3500)
}

async function saveConfig() {
  if (typeof props.api?.put !== 'function') {
    showMessage('当前 MoviePilot 未提供配置保存接口', 'error')
    return
  }
  saving.value = true
  try {
    const payload = {
      ...config,
      source_allowlist: '',
      source_strategy: 'first',
      download_root: '',
      ai_enabled: true,
      tmdb_association: true,
      use_moviepilot_dirs: true,
      moviepilot_organize: true,
      native_recognize: true,
      mode: 'download',
    }
    const response = await props.api.put(`plugin/${props.pluginId || 'LunaTVSource'}`, payload)
    const result = response?.data ?? response
    if (result?.success === false) throw new Error(result.message || '保存配置失败')
    emit('save', payload)
    showMessage('配置已保存', 'success')
  } catch (error) {
    showMessage(error?.message || '保存配置失败', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(() => Object.assign(config, defaults, props.initialConfig || {}))
</script>

<template>
  <div class="pa-4">
    <VToolbar density="comfortable" color="transparent" class="px-0">
      <VIcon icon="mdi-play-network" color="primary" class="me-2" />
      <div class="text-h6">LunaTV 原生桥接配置</div>
      <VSpacer />
      <VBtn icon="mdi-content-save" variant="text" color="success" :loading="saving" title="保存配置" @click="saveConfig" />
      <VBtn icon="mdi-close" variant="text" title="关闭" @click="emit('close')" />
    </VToolbar>
    <VDivider class="mb-4" />
    <VAlert v-if="message.text" :type="message.type" variant="tonal" density="compact" class="mb-4">{{ message.text }}</VAlert>
    <VAlert type="info" variant="tonal" density="compact" class="mb-4">
      保存后，LunaTV/苹果 CMS 将接入 MoviePilot 的原生搜索、订阅与下载入口。请直接使用 MoviePilot 的原生搜索、订阅和下载流程。
    </VAlert>
    <VRow dense>
      <VCol cols="12"><VSwitch v-model="config.enabled" label="启用原生桥接" color="success" hide-details /></VCol>
      <VCol cols="12"><VTextField v-model="config.config_url" label="LunaTV 配置地址" variant="outlined" /></VCol>
    </VRow>
    <VAlert type="warning" variant="tonal" density="compact" class="mt-3">
      目录、DeepSeek、TMDB、整理规则、媒体服务器和链接权限均沿用 MoviePilot 设置；订阅地址内的资源站全部读取。任务始终串行执行。
    </VAlert>
    <div class="d-flex justify-end mt-4"><VBtn color="primary" :loading="saving" @click="saveConfig">保存配置</VBtn></div>
  </div>
</template>
