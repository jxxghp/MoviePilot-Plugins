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
  generate_nfo: false,
  config_url: 'https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json',
  source_allowlist: '',
  probe_allowed_private_ranges: '',
  hls_ad_filter_regex: '(?i)(?:adjump|redtraffic|alimama|chenggao|laomaotao|[/_.-](?:ad|ads|advert|advertisement|promo|sponsor)[/_.-])',
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
  max_concurrent_tasks: 2,
  segment_thread_count: 16,
  source_check_minutes: 60,
}
const modeItems = [
  { title: '下载到本地并整理（去广告）', value: 'download' },
  { title: '生成 STRM（原始直链，不去广告）', value: 'strm' },
]
const config = reactive({ ...defaults })

function validateIntegerRange(value, label, min, max) {
  const number = Number(value)
  if (!Number.isInteger(number) || number < min || number > max) {
    showMessage(`${label}需为 ${min} 到 ${max} 之间的整数`, 'error')
    return false
  }
  return true
}

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
  if (!validateIntegerRange(config.max_concurrent_tasks, '任务并发数', 1, 4)
    || !validateIntegerRange(config.segment_thread_count, '分片线程数', 4, 32)
    || !validateIntegerRange(config.source_check_minutes, '来源健康检查间隔', 15, 1440)) return
  if (Number(config.max_concurrent_tasks) * Number(config.segment_thread_count) > 64) {
    showMessage('任务并发数 × 分片线程数不能超过 64', 'error')
    return
  }
  saving.value = true
  try {
    const mode = config.mode === 'strm' ? 'strm' : 'download'
    const payload = {
      ...config,
      source_allowlist: String(config.source_allowlist || '').trim(),
      probe_allowed_private_ranges: String(config.probe_allowed_private_ranges || '').trim(),
      hls_ad_filter_regex: String(config.hls_ad_filter_regex || '').trim(),
      download_root: String(config.download_root || '').trim(),
      ai_enabled: true,
      tmdb_association: true,
      use_moviepilot_dirs: true,
      moviepilot_organize: true,
      native_recognize: true,
      mode,
      max_concurrent_tasks: Number(config.max_concurrent_tasks),
      segment_thread_count: Number(config.segment_thread_count),
      source_check_minutes: Number(config.source_check_minutes),
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

onMounted(() => {
  Object.assign(config, defaults, props.initialConfig || {})
  config.mode = config.mode === 'strm' ? 'strm' : 'download'
})
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
      保存后，LunaTV/苹果 CMS 将接入 MoviePilot 的原生搜索、订阅与下载入口。要去广告请选择“下载到本地并整理”；STRM 是原始直链，不经过 HLS 分片过滤。
    </VAlert>
    <VRow dense>
      <VCol cols="12"><VSwitch v-model="config.enabled" label="启用原生桥接" color="success" hide-details /></VCol>
      <VCol cols="12">
        <VSwitch
          v-model="config.generate_nfo"
          label="生成 NFO 元数据"
          hint="开启后，下载完成并由 MoviePilot 原生整理时生成 NFO。"
          persistent-hint
          color="success"
        />
      </VCol>
      <VCol cols="12">
        <VSelect
          v-model="config.mode"
          :items="modeItems"
          label="处理方式"
          hint="只有本地下载模式会执行 HLS 广告分片过滤并生成 MP4。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
      <VCol cols="12"><VTextField v-model="config.config_url" label="LunaTV 配置地址" variant="outlined" /></VCol>
      <VCol cols="12">
        <VTextField
          v-model="config.source_allowlist"
          label="启用资源站（可选）"
          placeholder="留空允许配置中的全部来源"
          hint="填写来源 key，使用逗号分隔。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
      <VCol cols="12">
        <VTextField
          v-model="config.hls_ad_filter_regex"
          label="HLS 广告分片 URL 正则（可选）"
          placeholder="例如 adjump|redtraffic|/ad/"
          hint="默认过滤常见广告路径；留空则只删除闭合 CUE-OUT/CUE-IN 标记区间。不要用单独的 DISCONTINUITY 作为删除条件。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
      <VCol cols="12">
        <VTextField
          v-model="config.probe_allowed_private_ranges"
          label="可信网络 CIDR（可选）"
          placeholder="例如 198.18.0.0/15"
          hint="默认拒绝私网配置、CMS 和媒体地址；Fake-IP 或可信内网环境才填写。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
      <VCol cols="12">
        <VTextField
          v-model="config.download_root"
          label="下载目录（可留空）"
          placeholder="留空自动选择"
          hint="填写后优先使用；留空时依次使用 MoviePilot 传入目录、订阅保存目录、按媒体类型的本地下载目录。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
      <VCol cols="12" md="6">
        <VTextField
          v-model="config.max_concurrent_tasks"
          label="最大任务并发数"
          type="number"
          min="1"
          max="4"
          step="1"
          hint="范围 1–4，默认 2。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
      <VCol cols="12" md="6">
        <VTextField
          v-model="config.source_check_minutes"
          label="来源健康检查间隔（分钟）"
          type="number"
          min="15"
          max="1440"
          step="1"
          hint="范围 15–1440，默认 60。打开插件页仅读取缓存，定时任务才会执行健康检查。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
      <VCol cols="12" md="6">
        <VTextField
          v-model="config.segment_thread_count"
          label="分片线程数"
          type="number"
          min="4"
          max="32"
          step="1"
          hint="范围 4–32，默认 16；与任务并发数相乘不能超过 64。"
          persistent-hint
          variant="outlined"
        />
      </VCol>
    </VRow>
    <VAlert type="warning" variant="tonal" density="compact" class="mt-3">
      目录、DeepSeek、TMDB、整理规则、媒体服务器和链接权限均沿用 MoviePilot 设置；订阅地址内的资源站全部读取。默认 2 个任务、每任务 16 个分片线程，总分片并发限制为 64；遇到 429、超时或磁盘繁忙时请调低。
    </VAlert>
    <div class="d-flex justify-end mt-4"><VBtn color="primary" :loading="saving" @click="saveConfig">保存配置</VBtn></div>
  </div>
</template>
