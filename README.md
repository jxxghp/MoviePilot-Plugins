# MoviePilot-Plugins

MoviePilot 官方插件仓库，也是 MoviePilot 插件市场默认读取的插件索引与源码仓库：
<https://github.com/jxxghp/MoviePilot-Plugins>

这个仓库本身并不是独立运行时，插件真正的运行宿主在后端仓库 `MoviePilot`，插件 UI 的渲染宿主在前端仓库 `MoviePilot-Frontend`。因此，开发插件时需要同时理解这三个仓库的分工。

## 文档导航

- [仓库指南](./docs/Repository_Guide.md)：先看这份，了解本仓库的目录、元数据、发布链路，以及和主仓库/前端仓库的边界。
- [V2 插件开发指南](./docs/V2_Plugin_Development.md)：开发或迁移 V2 插件时的主文档，覆盖生命周期、渲染模式、接口能力和校验建议。
- [MoviePilot 前端模块联邦开发指南](https://github.com/jxxghp/MoviePilot-Frontend/blob/v2/docs/module-federation-guide.md)：当插件需要使用 Vue 远程组件时必读。
- [常见问题索引](./docs/FAQ.md)：FAQ 已拆分为独立文档，适合按场景查阅。

## 仓库定位

- `MoviePilot` 负责插件加载、事件分发、API 注册、公共服务、数据持久化和权限控制。
- `MoviePilot-Frontend` 负责插件市场、插件配置/详情弹窗、仪表板渲染，以及 Vue 联邦远程组件的加载。
- `MoviePilot-Plugins` 负责插件源码、插件市场索引、插件图标与插件开发文档。

如果你要判断某个问题该在哪个仓库处理，可以按下面这条经验规则：

- 插件类、事件、链式扩展、服务、API、数据保存问题，先看 `MoviePilot`。
- 插件页面渲染、模块联邦、侧栏全页入口、前端交互问题，先看 `MoviePilot-Frontend`。
- 插件元数据、版本号、图标、插件市场展示、Release 打包问题，先看本仓库。

## 仓库结构

```text
MoviePilot-Plugins/
├── plugins/                 # 默认插件目录，通常也是兼容旧版本或通用版本的入口
├── plugins.v2/              # V2 专用插件目录
├── icons/                   # 插件图标资源
├── package.json             # 默认插件索引；可通过 "v2": true 声明兼容 V2
├── package.v2.json          # V2 优先插件索引
├── docs/                    # 开发与维护文档
└── .github/workflows/       # 发布工作流
```

## 版本与加载规则

- MoviePilot 会优先读取 `package.v2.json` 中与当前版本标识匹配的插件定义。
- 如果某个插件不在 `package.v2.json` 中，但其 `package.json` 条目声明了 `"v2": true`，则会作为“兼容 V2 的默认插件”继续显示和安装。
- `package.v2.json` 中的插件代码通常放在 `plugins.v2/<plugin_id_lower>/`；`package.json` 中的插件代码通常放在 `plugins/<plugin_id_lower>/`。
- 插件目录名必须是插件类名的小写形式，插件主类必须定义在对应目录的 `__init__.py` 中。
- 插件市场里看到的版本、图标、作者、权限级别，都来自 `package.json` / `package.v2.json`；运行时真正生效的类属性来自插件代码中的 `plugin_*` 字段，两者必须保持同步。

## 第三方插件库开发说明
> 请不要开发用于破解 MoviePilot 用户认证、色情、赌博等违法违规内容的插件，共同维护健康的开发环境。


### 1. 目录结构
- 插件仓库建议直接 fork 本项目并保持同样的目录布局，仅支持 GitHub 仓库。
- `plugins` 和 `plugins.v2` 都是“一个插件一个目录”的结构，**目录名必须为插件类名的小写**，插件主类放在对应目录的 `__init__.py` 中。
- `package.json` / `package.v2.json` 是插件市场的索引文件。MoviePilot 会按版本选择合适的索引读取插件信息，因此这两个文件中的元数据需要和插件代码保持一致。
- 如果插件带有独立文档、示例或远程组件产物，建议放在插件目录下并在插件目录内提供 `README.md` 说明。

### 2. 插件图标
- 优先复用官方插件库 `icons/` 下已有图标；如需自定义图标，也可以在元数据中使用完整的 HTTP 图片 URL。
- `package.json` / `package.v2.json` 里的 `icon` 与插件类中的 `plugin_icon` 应保持一致。
- 插件卡片背景色会自动提取图标主色调，因此图标尽量避免透明度过高或主体过小。

### 3. 插件命名
- 插件 ID 以插件类名为准，例如 `class MyPlugin(_PluginBase)` 对应目录名 `myplugin`、插件 ID `MyPlugin`。
- 插件命名请勿与官方库中的现有插件冲突，否则在用户升级 MoviePilot 或同步插件市场时，可能被官方同名插件覆盖。
- 如果插件未来需要支持“插件分身”，请不要在代码中硬编码原始插件 ID，尽量使用 `self.__class__.__name__` 作为配置和数据命名空间。

### 4. 依赖
- 可在插件目录中放置 `requirements.txt` 文件声明额外依赖，MoviePilot 安装插件时会自动安装。
- 依赖尽量保持最小化，优先复用主程序已提供的公共能力，例如下载器、媒体服务器、通知渠道、缓存、链式处理等封装。
- 如果插件还依赖 Vue 远程组件，请将前端依赖放在独立的前端工程中构建后再产出到插件目录，不要把前端源码直接混入主插件包。

### 5. 界面开发
- 插件支持 `插件配置`、`详情展示`、`仪表板 Widget` 三类界面，V2 下还可以通过 Vue 联邦远程组件扩展侧栏全页入口。
- 推荐先判断你的界面属于哪一类：
  1. 纯配置表单、简单详情展示、轻量数据表，优先使用 Vuetify JSON 配置方式。
  2. 交互复杂、状态较多、需要独立全页或自定义布局时，使用 Vue 联邦远程组件。
- Vuetify JSON 模式说明：
  - `props.model` 等效于 `v-model`，`props.show` 等效于 `v-show`。
  - 插件配置页面的 `props` 支持表达式，使用 `{{ ... }}` 包裹。
  - 事件以 `on` 开头，例如 `onclick`、`onchange`。
  - 详情页面和仪表板可通过 `events` 发起 API 调用。
- Vue 联邦模式说明：
  - 插件后端需要实现 `get_render_mode()` 并返回 `("vue", "dist/assets")`。
  - 如果需要在主界面左侧导航新增入口，还需要实现 `get_sidebar_nav()`。
  - 远程组件的构建、暴露名约定、侧栏多入口、静态资源打包方式，请参考 [模块联邦开发指南](https://github.com/jxxghp/MoviePilot-Frontend/blob/v2/docs/module-federation-guide.md)。

### 6. 开发与校验建议
- 这个仓库只提供插件源码与索引，不提供完整宿主环境。开发后应至少在 `MoviePilot` 宿主里完成一次真实加载验证。
- 对 Python 插件代码，建议在宿主仓库环境中执行最小校验，例如：
  - `python3 -m py_compile <touched_files>`
  - `python3 -m compileall <touched_plugin_dirs>`
  - `git diff --check`
- 如果插件带有 Vue 远程组件，建议在对应前端工程中执行：
  - `yarn typecheck`
  - `yarn build`
- 如果插件接口依赖 MoviePilot 新增的后端能力或前端入口，请同步更新对应主仓库文档，避免文档和运行时行为脱节。

### 7. 元数据同步要求
- `package.json` / `package.v2.json` 中的 `version` 必须与插件类中的 `plugin_version` 保持一致，否则用户会看到错误的升级提示。
- `name`、`description`、`icon`、`author`、`level` 建议与插件类属性保持一致，避免插件市场展示与实际运行信息不一致。
- `history` 用于展示插件更新日志，建议每次发布都补齐一条可读变更说明。
- 需要走 GitHub Release 压缩包分发的插件，请在对应索引条目中增加 `"release": true`，并确保仓库中的发布工作流能够定位到对应目录。


## 常见问题

主文档只保留 FAQ 标题索引，具体内容请进入对应文档查看。

- [1. 如何扩展消息推送渠道？](./docs/faq/01-extend-notification-channel.md)
- [2. 如何在插件中实现远程命令响应？](./docs/faq/02-remote-command-handler.md)
- [3. 如何在插件中对外暴露API？](./docs/faq/03-expose-plugin-api.md)
- [4. 如何在插件中注册公共定时服务？](./docs/faq/04-register-service.md)
- [5. 如何通过插件增强MoviePilot的识别功能？](./docs/faq/05-enhance-recognition.md)
- [6. 如何扩展内建索引器的索引站点？](./docs/faq/06-extend-indexer-sites.md)
- [7. 如何在插件中调用API接口？](./docs/faq/07-call-api-from-plugin.md)
- [8. 如何将插件内容显示到仪表板？](./docs/faq/08-render-dashboard.md)
- [9. 如何扩展探索功能的媒体数据源？](./docs/faq/09-extend-discovery-source.md)
- [10. 如何扩展推荐功能的媒体数据源？](./docs/faq/10-extend-recommend-source.md)
- [11. 如何通过插件重载实现系统模块功能？](./docs/faq/11-override-system-module.md)
- [12. 如何通过插件扩展支持的存储类型？](./docs/faq/12-extend-storage-type.md)
- [13. 如何将插件功能集成到工作流？](./docs/faq/13-integrate-workflow.md)
- [14. 如何在插件中通过消息持续与用户交互？](./docs/faq/14-message-interaction.md)
- [15. 如何在插件中使用系统级统一缓存？](./docs/faq/15-use-system-cache.md)
- [16. 如何在插件中注册智能体工具？](./docs/faq/16-register-agent-tools.md)

## 版本发布

### 1. 如何发布插件版本？
- 修改插件代码后，需要同步更新对应索引文件中的 `version`，MoviePilot 才会提示用户有更新。这里的版本号需要与插件类中的 `plugin_version` 保持一致。
- 默认插件改 `package.json`，V2 专用插件改 `package.v2.json`；如果一个插件同时在两个索引文件中维护，需要分别确认目标版本与兼容策略。
- 索引中的 `level` 用于定义插件用户可见权限：
  - `1`：所有用户可见
  - `2`：站点认证用户可见
  - `3`：站点与密钥认证后可见
  - 插件类中的 `auth_level` 还可以使用更高的运行时限制，例如特殊密钥场景
- `history` 用于展示插件更新日志，建议每次发布都补齐一条可读的变更说明，格式如下：
```json
{
  "history": {
    "v1.8": "修复空目录删除逻辑",
    "v1.7": "增加定时清理空目录功能"
  }
}
```
- 新增加的插件建议追加在索引文件末尾，便于在插件市场中作为较新的条目出现。
- 如果插件目录文件较多，或你希望用户直接下载压缩包安装，可以在对应索引条目中增加 `"release": true`。
- 当前仓库的 GitHub Actions 发布工作流只会在 `package.json` 或 `package.v2.json` 发生变更时触发，并且只处理声明了 `"release": true` 的插件。
- 发布工作流会按下面的规则打包与创建 Release：
  - 插件目录优先在 `plugins/<plugin_id_lower>` 和 `plugins.v2/<plugin_id_lower>` 中查找
  - Tag 格式为 `插件ID_v插件版本号`
  - 资产文件名格式为 `插件目录小写_v插件版本号.zip`
  - 如果自上一个同插件 Tag 以来目录没有变化，则会跳过打包
  - 如果同名 Tag / Release 已存在，工作流会先删除旧版本再创建新版本
- 示例：
```json
{
  "release": true
}
```

### 2. 如何开发V2版本的插件以及实现插件多版本兼容？

- 请参阅 [V2 版本插件开发指南](./docs/V2_Plugin_Development.md)。
- 如果你要先理解本仓库与 `MoviePilot` / `MoviePilot-Frontend` 的分工，以及元数据和发布链路，再开始写代码，建议先看 [仓库指南](./docs/Repository_Guide.md)。
