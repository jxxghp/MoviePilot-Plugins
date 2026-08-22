<script setup>
defineProps({ initialConfig: { type: Object, default: () => ({}) } })
</script>

<template>
  <div class="pa-4">
    <p>配置项请在 MoviePilot 插件设置中保存。启用后返回侧栏的“LunaTV 订阅”工作台。</p>
  </div>
</template>
