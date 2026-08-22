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
  source_allowlist: 'suonizy.net,suoniapi.com,kuaichezy.com,caiji.kuaichezy.org,www.hongniuzy.com,www.hongniuzy2.com,wujinzy.net,wujinzy.me,api.wujinapi.me,wujinapi.me,guangsuzy.com,api.guangsuapi.com,ukuzy0.com,api.ukuapi88.com,www.xinlangzy.com,xinlangapi.com,okzyw.cc',
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
    // 这些能力由 MoviePilot 原生设置统一管理；旧版保存过的 false 值也不能关闭宿主桥接。
    const payload = {
      ...config,
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
      保存后，LunaTV/苹果 CMS 会作为 MoviePilot 的原生探索与媒体源出现；请直接使用 MoviePilot 的搜索、订阅和下载流程。
    </VAlert>
    <VRow dense>
      <VCol cols="12" md="6"><VSwitch v-model="config.enabled" label="启用原生桥接" color="success" hide-details /></VCol>
      <VCol cols="12" md="6"><VSelect v-model="config.source_strategy" :items="[{ title: '按配置顺序选一个（推荐）', value: 'first' }, { title: '所有匹配源都排队', value: 'all' }]" label="资源站策略" variant="outlined" density="comfortable" hide-details="auto" /></VCol>
      <VCol cols="12"><VTextField v-model="config.download_root" label="下载目录（可留空，自动复用 MoviePilot）" placeholder="/media/incoming/lunatv" hint="留空按电影/电视剧读取 MoviePilot 的本地目录。" persistent-hint variant="outlined" /></VCol>
      <VCol cols="12"><VTextField v-model="config.config_url" label="LunaTV 配置地址" variant="outlined" /></VCol>
      <VCol cols="12"><VTextarea v-model="config.source_allowlist" label="启用资源站（逗号分隔）" rows="2" variant="outlined" hide-details="auto" /></VCol>
    </VRow>
    <VAlert type="warning" variant="tonal" density="compact" class="mt-3">
      目录、DeepSeek、TMDB、整理规则和媒体服务器均沿用 MoviePilot 设置；这里仅保留 LunaTV 源地址、资源站策略和可选目录覆盖。任务始终串行执行。
    </VAlert>
    <div class="d-flex justify-end mt-4"><VBtn color="primary" :loading="saving" @click="saveConfig">保存配置</VBtn></div>
  </div>
</template>
