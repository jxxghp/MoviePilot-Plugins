import 'vue'
import type * as Components from 'vuetify/components'

// 运行时使用宿主注册的 Vuetify 组件，避免在远程模块重复打包组件和样式。
declare module 'vue' {
  export interface GlobalComponents {
    VAlert: typeof Components.VAlert
    VBtn: typeof Components.VBtn
    VCheckbox: typeof Components.VCheckbox
    VProgressLinear: typeof Components.VProgressLinear
    VSelect: typeof Components.VSelect
    VTab: typeof Components.VTab
    VTabs: typeof Components.VTabs
    VTextField: typeof Components.VTextField
  }
}
