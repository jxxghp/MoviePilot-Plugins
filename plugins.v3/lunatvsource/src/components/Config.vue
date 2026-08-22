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
  ai_enabled: false,
  tmdb_association: true,
  moviepilot_organize: false,
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
    const response = await props.api.put(`plugin/${props.pluginId || 'LunaTVSource'}`, { ...config })
    const result = response?.data ?? response
    if (result?.success === false) throw new Error(result.message || '保存配置失败')
    emit('save', { ...config })
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
      保存后，LunaTV/苹果 CMS 会作为 MoviePilot 的原生探索与媒体源出现；请从 MoviePilot 的搜索、订阅和下载流程操作。此处不另起一套订阅。
    </VAlert>
    <VRow dense>
      <VCol cols="12" md="6"><VSwitch v-model="config.enabled" label="启用原生桥接" color="success" hide-details /></VCol>
      <VCol cols="12" md="6"><VSwitch v-model="config.ai_enabled" label="启用系统智能助手（DeepSeek）" color="primary" hide-details /></VCol>
      <VCol cols="12" md="6"><VSwitch v-model="config.tmdb_association" label="搜索后自动关联 TMDB" color="primary" hide-details /></VCol>
      <VCol cols="12" md="6"><VSwitch v-model="config.use_moviepilot_dirs" label="复用 MoviePilot 目录设置" color="primary" hide-details /></VCol>
      <VCol cols="12" md="6"><VSwitch v-model="config.moviepilot_organize" label="完成后调用原生整理链" color="primary" hide-details /></VCol>
      <VCol cols="12" md="6"><VSwitch v-model="config.native_recognize" label="允许原生媒体识别" color="primary" hide-details /></VCol>
      <VCol cols="12" md="6"><VSelect v-model="config.mode" :items="[{ title: '下载到本地并整理', value: 'download' }, { title: '生成 STRM', value: 'strm' }]" label="媒体落盘方式" variant="outlined" density="comfortable" hide-details="auto" /></VCol>
      <VCol cols="12" md="6"><VSelect v-model="config.source_strategy" :items="[{ title: '按配置顺序选一个（推荐）', value: 'first' }, { title: '所有匹配源都排队', value: 'all' }]" label="资源站策略" variant="outlined" density="comfortable" hide-details="auto" /></VCol>
      <VCol cols="12"><VTextField v-model="config.download_root" label="下载目录（可留空，自动复用 MoviePilot）" placeholder="/media/incoming/lunatv" hint="留空按电影/电视剧读取 MoviePilot 的本地目录。" persistent-hint variant="outlined" /></VCol>
      <VCol cols="12"><VTextField v-model="config.mediaserver_name" label="完成后刷新媒体服务器（可选）" placeholder="Emby" hint="留空刷新所有已启用媒体服务器。" persistent-hint variant="outlined" /></VCol>
      <VCol cols="12"><VTextField v-model="config.config_url" label="LunaTV 配置地址" variant="outlined" /></VCol>
      <VCol cols="12"><VTextarea v-model="config.source_allowlist" label="启用资源站（逗号分隔）" rows="2" variant="outlined" hide-details="auto" /></VCol>
    </VRow>
    <VAlert type="warning" variant="tonal" density="compact" class="mt-3">
      任务始终串行执行；目录内没有正在下载的缓存文件后，媒体库才会显示完整文件夹。播放仍交给已有 Emby/Jellyfin。
    </VAlert>
    <div class="d-flex justify-end mt-4"><VBtn color="primary" :loading="saving" @click="saveConfig">保存配置</VBtn></div>
  </div>
</template>
