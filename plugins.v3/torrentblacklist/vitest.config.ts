import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

const tests = fileURLToPath(new URL('../../tests/v3/torrentblacklist/frontend/', import.meta.url))
const require = createRequire(import.meta.url)
export default defineConfig({
  resolve: { alias: ['vue', 'vuetify', 'vuetify/components', 'vuetify/styles', '@testing-library/vue', '@testing-library/user-event'].map(name => ({
    find: new RegExp(`^${name}$`), replacement: require.resolve(name),
  })) },
  plugins: [vue()],
  server: { fs: { allow: [fileURLToPath(new URL('../..', import.meta.url))] } },
  test: {
    environment: 'jsdom', include: [`${tests}*.test.ts`],
    setupFiles: [`${tests}setup.ts`], maxWorkers: 1,
    server: { deps: { inline: ['vuetify'] } },
  },
})
