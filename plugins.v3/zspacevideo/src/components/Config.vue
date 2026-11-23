<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: 'ZSpaceVideo' },
})
const emit = defineEmits(['save', 'close', 'switch'])

const DEFAULTS = {
  enabled: false,
  connection_mode: 'cloud',
  lan_host: '',
  path_mapping: '',
  library_dirs: '',
  zvideo_db: '/zvideo/zvideo.db',
  quiet_seconds: 60,
  max_wait_seconds: 300,
  poll_timeout_seconds: 1800,
  notify: true,
  watched_enabled: false,
  watched_auto_mode: 'none',
  watched_buffer_days: 7,
  watched_sync_minutes: 60,
  watched_auto_since: 0,
}
const form = ref({ ...DEFAULTS, ...(props.initialConfig || {}) })
watch(() => props.initialConfig, v => { form.value = { ...DEFAULTS, ...(v || {}) } })

const deleteModes = [
  { title: '不删（默认）', value: 'none' },
  { title: '只从库里移除（继续做种，不腾空间）', value: 'library' },
  { title: '真删除（库入口 + 做种文件 + qB 任务，腾出空间）', value: 'full' },
]

const modes = [
  { title: '官方云中转（默认，HTTPS）', value: 'cloud' },
  { title: '局域网 HTTP 直连', value: 'lan' },
]

function save() {
  const payload = { ...form.value }
  for (const k of ['quiet_seconds', 'max_wait_seconds', 'poll_timeout_seconds', 'watched_sync_minutes']) payload[k] = Number(payload[k]) || DEFAULTS[k]
  payload.watched_buffer_days = Number(payload.watched_buffer_days)
  if (!(payload.watched_buffer_days >= 1)) payload.watched_buffer_days = DEFAULTS.watched_buffer_days
  emit('save', payload)
}
</script>

<template>
  <VCard>
    <VCardItem>
      <VCardTitle>极空间影视 · 设置</VCardTitle>
    </VCardItem>
    <VCardText>
      <VRow>
        <VCol cols="12" md="4"><VSwitch v-model="form.enabled" label="启用" color="primary" hide-details /></VCol>
        <VCol cols="12" md="4"><VSwitch v-model="form.notify" label="刷新失败发站内消息（同类问题只提醒一次）" color="primary" hide-details /></VCol>
      </VRow>
      <VRow>
        <VCol cols="12" md="6">
          <VSelect v-model="form.connection_mode" :items="modes" label="连接方式" />
        </VCol>
        <VCol v-if="form.connection_mode === 'lan'" cols="12" md="6">
          <VTextField v-model="form.lan_host" label="极空间地址" placeholder="http://nas.example.com:5055" />
        </VCol>
      </VRow>
      <VAlert v-if="form.connection_mode === 'lan'" type="warning" variant="tonal" class="mb-4">
        局域网直连走明文 HTTP：访问令牌会以明文经过家里网络，同网段的设备能截获它，
        拿到后可以在令牌有效期内以你的极空间账号调用接口。只在你信任家里所有设备时用；
        好处是不经过极空间云端，云端故障时也能刷新。
      </VAlert>
      <VRow>
        <VCol cols="12" md="6">
          <VTextarea v-model="form.path_mapping" rows="3" auto-grow
                     label="路径映射（留空自动推断）"
                     placeholder="/downloads => /sata1/my/data/downloads"
                     hint="每行「容器里的路径 => 极空间里的路径」。留空时按 MoviePilot 容器的挂载自动推断。" persistent-hint />
        </VCol>
        <VCol cols="12" md="6">
          <VTextarea v-model="form.library_dirs" rows="3" auto-grow
                     label="分类目录（留空读极影视库）"
                     placeholder="动漫 = /sata1/my/data/downloads/anime"
                     hint="每行「分类名或ID = 极空间目录」。留空时从只读挂载的极影视库读取（需把 /zspace/zsrp/sqlite/zvideo 只读挂到 /zvideo）。" persistent-hint />
        </VCol>
      </VRow>
      <VRow>
        <VCol cols="12" md="4"><VTextField v-model="form.quiet_seconds" type="number" label="去抖：安静多少秒后提交" /></VCol>
        <VCol cols="12" md="4"><VTextField v-model="form.max_wait_seconds" type="number" label="最多攒多少秒" /></VCol>
        <VCol cols="12" md="4"><VTextField v-model="form.poll_timeout_seconds" type="number" label="等待扫描结果上限（秒）" /></VCol>
      </VRow>
      <VRow>
        <VCol cols="12"><VTextField v-model="form.zvideo_db" label="极影视库路径（只读）" /></VCol>
      </VRow>
      <VDivider class="my-4" />
      <div class="text-subtitle-1 mb-2">已看</div>
      <VRow>
        <VCol cols="12" md="4"><VSwitch v-model="form.watched_enabled" label="定时读取极影视已看" color="primary" hide-details /></VCol>
        <VCol cols="12" md="4"><VTextField v-model="form.watched_sync_minutes" type="number" label="每隔多少分钟读一次" :disabled="!form.watched_enabled" /></VCol>
      </VRow>
      <VRow>
        <VCol cols="12" md="8"><VSelect v-model="form.watched_auto_mode" :items="deleteModes" label="自动删除" :disabled="!form.watched_enabled" /></VCol>
        <VCol cols="12" md="4"><VTextField v-model="form.watched_buffer_days" type="number" min="1" label="已看满多少天后执行（缓冲期，至少 1 天）" :disabled="!form.watched_enabled || form.watched_auto_mode === 'none'" /></VCol>
      </VRow>
      <p v-if="form.watched_auto_mode !== 'none'" class="text-caption text-medium-emphasis mb-2">
        只处理打开自动删除之后才看完的；之前已经看过的留在已看列表里，要删请手动。
      </p>
      <VAlert v-if="form.watched_auto_mode === 'full'" type="error" variant="tonal" class="mb-2">
        真删除会删掉下载目录里做种的文件和 qB 任务（含辅种），删了只能重新下载。缓冲期内在极影视里取消「已看过」就不会删。
      </VAlert>
      <VAlert v-else-if="form.watched_auto_mode === 'library'" type="info" variant="tonal" class="mb-2">
        只删库里的入口，继续做种，不腾空间；极影视里这部片会消失。
      </VAlert>
    </VCardText>
    <VCardActions>
      <VBtn variant="text" @click="emit('switch')">查看状态</VBtn>
      <VSpacer />
      <VBtn variant="text" @click="emit('close')">取消</VBtn>
      <VBtn color="primary" variant="flat" @click="save">保存</VBtn>
    </VCardActions>
  </VCard>
</template>
