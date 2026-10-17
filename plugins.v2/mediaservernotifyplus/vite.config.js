import federation from '@originjs/vite-plugin-federation'
import vue from '@vitejs/plugin-vue'
import { rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const projectRoot = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'MediaServerNotifyPlus',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
      },
      shared: {
        vue: { requiredVersion: false, generate: false, singleton: true },
        vuetify: { requiredVersion: false, generate: false, singleton: true },
        'vuetify/styles': { requiredVersion: false, generate: false, singleton: true },
      },
      format: 'esm',
    }),
    {
      name: 'clean-federation-output',
      generateBundle(_options, bundle) {
        for (const fileName of Object.keys(bundle)) {
          if (
            fileName.includes('__federation_shared_vuetify/styles-')
            || fileName === 'index.html'
            || /^assets\/index-/.test(fileName)
            || fileName.includes('materialdesignicons-webfont-')
          ) delete bundle[fileName]
        }
      },
      closeBundle() {
        rmSync(`${projectRoot}dist/index.html`, { force: true })
      },
    },
  ],
  build: {
    target: 'esnext',
    minify: false,
    cssCodeSplit: true,
    assetsInlineLimit: 300_000,
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: ['terminal.local'],
  },
})
