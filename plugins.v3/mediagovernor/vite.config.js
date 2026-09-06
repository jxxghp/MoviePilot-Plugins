import federation from '@originjs/vite-plugin-federation'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'MediaGovernor',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
        './AppPage': './src/components/AppPage.vue',
      },
      shared: { vue: { requiredVersion: false, generate: false, singleton: true } },
      format: 'esm',
    }),
  ],
  // remoteEntry.js 是固定文件名；将它置于发布版目录，使宿主加载新版本时
  // 不会复用旧的联邦入口与新后端混搭。
  build: { target: 'esnext', minify: false, cssCodeSplit: true, assetsDir: 'v4.5.0/assets' },
})
