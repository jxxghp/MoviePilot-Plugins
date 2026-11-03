<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(defineProps<{ initialConfig?: { enabled?: boolean } }>(), { initialConfig: () => ({}) })
const emit = defineEmits<{ save: [config: { enabled: boolean }]; close: [] }>()
const enabled = ref(false)
watch(() => props.initialConfig, config => { enabled.value = config.enabled === true }, { immediate: true })
</script>

<template>
  <section class="blacklist-config">
    <h3>种子黑名单</h3>
    <VCheckbox v-model="enabled" label="启用种子黑名单" hide-details />
    <VAlert type="info" variant="tonal" :icon="false">
      启用后，在资源选择与实际下载前屏蔽命中的种子，包含手动下载。
      请在插件详情页管理规则；停用不删除已有规则。
    </VAlert>
    <div class="blacklist-config-actions">
      <VBtn variant="text" @click="emit('close')">取消</VBtn>
      <VBtn color="primary" @click="emit('save', { enabled })">保存</VBtn>
    </div>
  </section>
</template>

<style scoped>
.blacklist-config { display: grid; gap: 1rem; padding: 1rem; }
.blacklist-config h3 { margin: 0; }
.blacklist-config-actions { display: flex; justify-content: flex-end; gap: .5rem; }
</style>
