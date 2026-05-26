<script setup>
import { computed } from 'vue'
import { PROVIDER_TYPE_OPTIONS } from '../provider'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  provider: {
    type: Object,
    default: () => ({}),
  },
  editorIndex: {
    type: Number,
    default: -1,
  },
})

const emit = defineEmits(['update:modelValue', 'commit'])

const dialogVisible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})

// 提交当前弹窗编辑的供应商配置。
function commitProvider() {
  emit('commit')
}
</script>

<template>
  <VDialog v-model="dialogVisible" max-width="760" max-height="85vh" scrollable>
    <VCard>
      <VCardTitle>{{ editorIndex >= 0 ? '编辑供应商' : '新增供应商' }}</VCardTitle>
      <VCardText>
        <VRow>
          <VCol cols="12" md="8">
            <VTextField v-model="provider.name" label="名称" variant="outlined" density="comfortable" />
          </VCol>
          <VCol cols="12" md="4">
            <VTextField v-model.number="provider.priority" label="优先级" type="number" variant="outlined" />
          </VCol>
          <VCol cols="12" md="6">
            <VSelect v-model="provider.provider" :items="PROVIDER_TYPE_OPTIONS" label="类型" variant="outlined" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model="provider.model" label="模型" variant="outlined" />
          </VCol>
          <VCol cols="12">
            <VTextField v-model="provider.base_url" label="API 地址" variant="outlined" />
          </VCol>
          <VCol cols="12">
            <VTextField v-model="provider.api_key" label="API Key" type="password" variant="outlined" />
          </VCol>
          <VCol cols="12">
            <VTextField v-model="provider.user_agent" label="User-Agent" variant="outlined" />
          </VCol>
          <VCol cols="12">
            <VSwitch
              v-model="provider.use_proxy"
              color="primary"
              label="使用代理服务器"
              hint="启用后，Agent 连接该供应商时会使用系统代理服务器"
              persistent-hint
            />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model.number="provider.token_limit" label="Token 额度" type="number" variant="outlined" />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField v-model.number="provider.used_tokens" label="初始已用" type="number" variant="outlined" />
          </VCol>
        </VRow>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dialogVisible = false">取消</VBtn>
        <VBtn color="primary" @click="commitProvider">确定</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
