<script setup>
import { reactive } from 'vue'
const props = defineProps({ initialConfig: { type: Object, default: () => ({}) } })
const emit = defineEmits(['save', 'close'])
const config = reactive({ enabled: false, ...props.initialConfig })
</script>
<template><main class="config-page"><h2>媒体治理设置</h2><label><input v-model="config.enabled" type="checkbox" /> 启用媒体治理</label><p>启用后才可打开治理台；检查只在你点击开始后发生。</p><aside>插件把路径只保存在插件私有账本中。只有你查看逐文件预览并最终确认后，才会让 MoviePilot 清理可归因的错误硬链接并重新整理；不会删除原始下载。</aside><footer><button @click="emit('close')">关闭</button><button class="primary" @click="emit('save', config)">保存</button></footer></main></template>
<style scoped>.config-page{padding:24px;color:rgb(var(--v-theme-on-background,232,231,241))}.config-page label{display:block;margin-top:18px;font-weight:650}.config-page p{margin:6px 0;color:rgba(var(--v-theme-on-surface,232,231,241),.65);font-size:13px}.config-page aside{margin-top:22px;padding:12px;border-radius:9px;background:rgba(33,150,243,.16);font-size:13px}.config-page footer{display:flex;justify-content:flex-end;gap:9px;margin-top:22px}.config-page button{border:0;border-radius:8px;padding:8px 13px;cursor:pointer}.config-page .primary{background:rgb(var(--v-theme-primary,139,92,246));color:white}</style>
