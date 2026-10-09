// 全屏海报墙 Vite 联邦配置（remote）
//
// 参考 MoviePilot-Frontend 官方 module-federation-guide.md 写法：
//   https://github.com/jxxghp/MoviePilot-Frontend/blob/main/docs/module-federation-guide.md
//
// 关键点：
//   1. 不要显式指定 rollupOptions.input——让 federation 插件自己生成
//      `__federation_expose_<Name>-<hash>.js`。MoviePilot 主框架的 federation
//      加载器是按这个命名约定的文件名查找的；用 `Page.js` / `Config.js`
//      这种平铺文件名不会被加载。
//   2. shared: vue + vuetify + vuetify/styles（均 singleton + requiredVersion: false）。
//      这些组件实例必须由 MoviePilot 主框架提供，remote 不重复打包。
//   3. minify: false（官方推荐，避免调试时定位困难）。
//   4. postcss 过滤 .v-* 与 .mdi-*——主框架已经有 Vuetify 完整 CSS，重复会冲突。
//   5. 部署时只上传 `__federation_*` / `_plugin-vue_export-helper-*` / `remoteEntry.js`。
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import federation from '@originjs/vite-plugin-federation';

export default defineConfig({
  // 用 custom 模式避免依赖 index.html（联邦 remote 不需要 HTML）。
  appType: 'custom',
  plugins: [
    vue(),
    federation({
      name: 'FullScreenPosterWall',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/Page.vue',
        './Config': './src/Config.vue',
        './Dashboard': './src/Dashboard.vue',
      },
      shared: {
        // 参考 MoviePilot-Plugins 官方 agenttokens 写法：只把 vue 设为 shared。
        // Vuetify 组件由 MoviePilot 主框架 `app.use(vuetify)` 全局注册，
        // 联邦 remote 不需要真正 import 它——运行时从全局拿就行。
        vue: { requiredVersion: false, generate: false },
      },
      format: 'esm',
    }),
  ],
  build: {
    // 联邦依赖顶层 await，target 必须 esnext。
    target: 'esnext',
    // 把 Page.vue 的样式清空——主框架已经有 Vuetify 完整样式，避免冲突。
    cssCodeSplit: true,
    sourcemap: false,
    minify: false,
    rollupOptions: {
      // 关键：不要指定 input，让 federation 插件自己决定入口。
      // 也不要改 entryFileNames，否则产物名不符合 MoviePilot 期望的
      // `__federation_expose_<Name>-<hash>.js` 命名约定。
      output: {
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  // SCSS 预处理器空配置（联邦 build 通常不带 .scss，添加一个空对象避免 vite 报错）
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: '/* vue-federation: vuetify 样式由主应用提供 */',
      },
    },
    // 关键：删除所有 .v-* 与 .mdi-* CSS——主框架 MoviePilot 已经有完整的 Vuetify 样式，
    // remote 端如果重发会出现优先级/重复规则冲突。
    postcss: {
      plugins: [
        {
          postcssPlugin: 'internal:charset-removal',
          AtRule: {
            charset: (atRule: any) => {
              if (atRule.name === 'charset') atRule.remove();
            },
          },
        },
        {
          postcssPlugin: 'vuetify-filter',
          Root(root: any) {
            root.walkRules((rule: any) => {
              if (rule.selector && (rule.selector.includes('.v-') || rule.selector.includes('.mdi-'))) {
                rule.remove();
              }
            });
          },
        },
      ],
    },
  },
});
