<script setup>
import { reactive } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save', 'close'])
const config = reactive({
  enabled: props.initialConfig.enabled ?? false,
  show_sidebar_nav: props.initialConfig.show_sidebar_nav ?? true,
  source_root: props.initialConfig.source_root ?? '',
  classify_source: props.initialConfig.classify_source ?? true,
})
</script>

<template>
  <div class="pa-5">
    <div class="text-h6 mb-4">音乐资源管理</div>
    <VSwitch v-model="config.enabled" label="启用插件" color="primary" />
    <VSwitch v-model="config.show_sidebar_nav" label="显示侧栏入口" color="primary" />
    <VTextField
      v-model="config.source_root"
      label="下载资源根目录（可选）"
      placeholder="/volume1/UT/Musics"
      hint="留空时跟随 MoviePilot 下载目录；艺术家合集可归入 Artist Collection/艺人。"
      persistent-hint
    />
    <VSwitch v-model="config.classify_source" label="合集下载时按 Artist Collection/艺人 分类" color="primary" />
    <VAlert type="info" variant="tonal" class="my-4">
      站点凭据只保留在后端短时内存中，不会发送到浏览器或写入插件数据。
    </VAlert>
    <div class="d-flex justify-end ga-2">
      <VBtn variant="text" @click="emit('close')">关闭</VBtn>
      <VBtn color="primary" @click="emit('save', { ...config })">保存</VBtn>
    </div>
  </div>
</template>
