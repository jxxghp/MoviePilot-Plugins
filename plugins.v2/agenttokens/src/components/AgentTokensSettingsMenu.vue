<script setup>
import { ref } from 'vue'

const props = defineProps({
  settings: {
    type: Object,
    default: () => ({ enabled: false, show_sidebar_nav: true }),
  },
  saving: {
    type: Boolean,
    default: false,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  saveSettings: {
    type: Function,
    default: null,
  },
})

const settingsMenu = ref(false)
const settingsDraft = ref({ enabled: false, show_sidebar_nav: true })

// 从已保存配置创建菜单草稿，取消菜单时不污染当前页面配置。
function syncSettingsDraft() {
  settingsDraft.value = {
    enabled: Boolean(props.settings?.enabled),
    show_sidebar_nav: props.settings?.show_sidebar_nav !== false,
  }
}

// 切换菜单显示状态，并在每次打开时同步最新配置。
function setMenuOpen(open) {
  if (open) syncSettingsDraft()
  settingsMenu.value = open
}

// 保存插件开关设置，失败时保留菜单以便用户调整或重试。
async function submitSettings() {
  if (typeof props.saveSettings !== 'function') return
  const saved = await props.saveSettings({
    enabled: Boolean(settingsDraft.value.enabled),
    show_sidebar_nav: Boolean(settingsDraft.value.show_sidebar_nav),
  })
  if (saved !== false) settingsMenu.value = false
}
</script>

<template>
  <VMenu
    :model-value="settingsMenu"
    :close-on-content-click="false"
    location="bottom end"
    @update:model-value="setMenuOpen"
  >
    <template #activator="{ props: menuProps }">
      <VBtn
        v-bind="menuProps"
        icon="mdi-tune-variant"
        variant="text"
        aria-label="插件设置"
        title="插件设置"
        :disabled="disabled"
      />
    </template>

    <VCard class="agenttokens-settings-menu" title="插件设置">
      <VCardText class="agenttokens-settings-menu__body">
        <VSwitch v-model="settingsDraft.enabled" color="primary" hide-details inset label="启用插件" />
        <VSwitch
          v-model="settingsDraft.show_sidebar_nav"
          color="primary"
          hide-details
          inset
          label="显示侧栏入口"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn color="primary" variant="flat" :loading="saving" @click="submitSettings">保存</VBtn>
      </VCardActions>
    </VCard>
  </VMenu>
</template>

<style scoped>
.agenttokens-settings-menu {
  inline-size: min(22rem, calc(100vw - 24px));
}

.agenttokens-settings-menu__body {
  display: grid;
  gap: 8px;
}
</style>
