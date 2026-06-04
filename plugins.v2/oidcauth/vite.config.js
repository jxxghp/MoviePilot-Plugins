import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: 'OidcAuth',
      filename: 'remoteEntry.js',
      exposes: {
        './AuthPage': './src/components/AuthPage.vue',
        './AppPage': './src/components/AppPage.vue',
        './Page': './src/components/AppPage.vue',
        './Config': './src/components/AppPage.vue',
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
    target: 'esnext',
    minify: false,
    cssCodeSplit: true,
  },
  css: {
    postcss: {
      plugins: [
        {
          postcssPlugin: 'internal:charset-removal',
          AtRule: {
            charset: atRule => {
              if (atRule.name === 'charset') {
                atRule.remove()
              }
            },
          },
        },
      ],
    },
  },
})
