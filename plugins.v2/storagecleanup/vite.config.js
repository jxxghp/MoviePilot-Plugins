import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

const pluginVersion = '1.0.15'

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'StorageCleanup',
      filename: 'remoteEntry.js',
      exposes: {
        './AppPage': './src/components/AppPage.vue',
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
      },
      shared: {
        vue: {
          requiredVersion: false,
          generate: false,
        },
      },
      format: 'esm',
    }),
  ],
  build: {
    outDir: `dist/v${pluginVersion}`,
    target: 'esnext',
    minify: false,
    cssCodeSplit: true,
  },
})
