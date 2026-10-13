import federation from '@originjs/vite-plugin-federation'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'MusicLibraryManager',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
        './AppPage': './src/components/AppPage.vue',
      },
      shared: {
        vue: { requiredVersion: false, generate: false, singleton: true },
        vuetify: { requiredVersion: false, generate: false, singleton: true },
        'vuetify/styles': { requiredVersion: false, generate: false, singleton: true },
      },
      format: 'esm',
    }),
  ],
  build: { target: 'esnext', minify: true, cssCodeSplit: true },
  css: {
    postcss: {
      plugins: [
        {
          postcssPlugin: 'internal:charset-removal',
          AtRule: { charset: atRule => atRule.name === 'charset' && atRule.remove() },
        },
        {
          postcssPlugin: 'vuetify-filter',
          Root(root) {
            const sourcePath = root.source?.input?.file?.replaceAll('\\', '/') || ''
            if (sourcePath.includes('/node_modules/vuetify/') || sourcePath.includes('/node_modules/@mdi/')) {
              root.nodes = []
              return
            }
            root.walkRules(rule => {
              if (rule.selector && (rule.selector.includes('.v-') || rule.selector.includes('.mdi-'))) rule.remove()
            })
          },
        },
      ],
    },
  },
})
