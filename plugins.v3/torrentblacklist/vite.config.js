import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

export default defineConfig({
  plugins: [vue(), federation({
    name: 'TorrentBlacklist', filename: 'remoteEntry.js', format: 'esm',
    exposes: { './Config': './src/components/Config.vue', './Page': './src/components/Page.vue' },
    shared: {
      vue: { requiredVersion: false, generate: false, singleton: true },
      vuetify: { requiredVersion: false, generate: false, singleton: true },
      'vuetify/styles': { requiredVersion: false, generate: false, singleton: true },
    },
  })],
  build: { target: 'esnext', minify: 'esbuild', cssCodeSplit: true, rollupOptions: { input: {} } },
  css: { postcss: { plugins: [
    { postcssPlugin: 'internal:charset-removal', AtRule: { charset: rule => rule.remove() } },
    { postcssPlugin: 'vuetify-filter', Root(root) {
      const path = root.source?.input?.file?.replaceAll('\\', '/') || ''
      if (path.includes('/node_modules/vuetify/') || path.includes('/node_modules/@mdi/')) {
        root.nodes = []
        return
      }
      root.walkRules(rule => {
        if (rule.selector && !rule.selector.includes('.blacklist-') &&
            (rule.selector.includes('.v-') || rule.selector.includes('.mdi-'))) rule.remove()
      })
    } },
  ] } },
})
