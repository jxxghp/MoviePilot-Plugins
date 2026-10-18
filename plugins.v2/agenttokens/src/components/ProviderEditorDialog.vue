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
            <VTextField
              v-model="provider.name"
              label="名称"
              hint="用于在供应商列表和用量统计中识别此配置"
              persistent-hint
              variant="outlined"
              density="comfortable"
            />
          </VCol>
          <VCol cols="12" md="4">
            <VTextField
              v-model.number="provider.priority"
              label="优先级"
              hint="数值越小优先级越高，不可用时按顺序切换"
              persistent-hint
              type="number"
              variant="outlined"
            />
          </VCol>
          <VCol cols="12" md="6">
            <VSelect
              v-model="provider.provider"
              :items="PROVIDER_TYPE_OPTIONS"
              label="类型"
              hint="选择与目标 API 接口兼容的供应商协议"
              persistent-hint
              variant="outlined"
            />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField
              v-model="provider.model"
              label="模型"
              hint="填写供应商接口使用的模型标识"
              persistent-hint
              variant="outlined"
            />
          </VCol>
          <VCol cols="12">
            <VTextField
              v-model="provider.base_url"
              label="API 地址"
              hint="填写供应商兼容接口的基础地址"
              persistent-hint
              variant="outlined"
            />
          </VCol>
          <VCol cols="12">
            <VTextField
              v-model="provider.api_key"
              label="API Key"
              hint="填写访问供应商接口所需的密钥"
              persistent-hint
              type="password"
              variant="outlined"
            />
          </VCol>
          <VCol cols="12">
            <VTextField
              v-model="provider.user_agent"
              label="User-Agent"
              hint="可选；自定义请求标识，留空时使用系统默认值"
              persistent-hint
              variant="outlined"
            />
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
            <VTextField
              v-model.number="provider.token_limit"
              label="Token 额度"
              hint="填写 0 表示不限量，达到额度后自动切换供应商"
              persistent-hint
              type="number"
              variant="outlined"
            />
          </VCol>
          <VCol cols="12" md="6">
            <VTextField
              v-model.number="provider.used_tokens"
              label="初始已用"
              hint="用于录入已有消耗量，新供应商通常填写 0"
              persistent-hint
              type="number"
              variant="outlined"
            />
          </VCol>
          <VCol cols="12">
            <VSwitch
              v-model="provider.failure_cooldown_enabled"
              color="primary"
              label="连续失败自动冷却"
              hint="默认关闭；连续执行失败达到阈值后，后续 Agent 轮次按优先级使用其他可用供应商"
              persistent-hint
            />
          </VCol>
          <template v-if="provider.failure_cooldown_enabled">
            <VCol cols="12" md="6">
              <VTextField
                v-model.number="provider.failure_threshold"
                label="连续失败次数"
                hint="成功后清零；用户取消不计入失败"
                persistent-hint
                type="number"
                min="1"
                variant="outlined"
              />
            </VCol>
            <VCol cols="12" md="6">
              <VTextField
                v-model.number="provider.cooldown_seconds"
                label="初始冷却时长（秒）"
                hint="冷却到期后自动恢复参与选号"
                persistent-hint
                type="number"
                min="1"
                variant="outlined"
              />
            </VCol>
            <VCol cols="12">
              <VSwitch
                v-model="provider.cooldown_exponential"
                color="primary"
                label="指数退避"
                hint="恢复后再次达到失败阈值，冷却时长翻倍；调用成功后恢复初始时长"
                persistent-hint
              />
            </VCol>
            <VCol cols="12">
              <VTextField
                v-model.number="provider.cooldown_max_seconds"
                label="冷却时长上限（秒）"
                hint="固定冷却和指数退避均不超过此值"
                persistent-hint
                type="number"
                min="1"
                variant="outlined"
              />
            </VCol>
          </template>
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
