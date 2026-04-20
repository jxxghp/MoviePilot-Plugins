# MoviePilot-Plugins 仓库指南

本文档面向维护者和插件开发者，说明 `MoviePilot-Plugins` 在整个 MoviePilot 体系中的职责、目录约定、元数据规则、发布流程，以及与 `MoviePilot` / `MoviePilot-Frontend` 两个主仓库的边界。

## 1. 仓库职责

`MoviePilot-Plugins` 不是独立运行时，而是插件市场和插件源码仓库。

- `MoviePilot` 后端仓库负责：
  - 插件类加载与生命周期管理
  - 事件与链式扩展
  - 插件 API / 服务 / 仪表板注册
  - 配置、插件数据、权限控制
  - 插件安装、升级、分身、远程组件静态资源服务
- `MoviePilot-Frontend` 前端仓库负责：
  - 插件市场与插件卡片展示
  - 插件配置页、详情页、仪表板渲染
  - Vue 联邦远程组件加载
  - 插件侧栏全页入口
- `MoviePilot-Plugins` 负责：
  - 插件源码目录
  - 插件市场索引文件
  - 插件图标资源
  - 插件开发与维护文档

因此，开发插件时要避免把“宿主逻辑”误写进本仓库文档。例如：

- 某个 `get_api()` 为什么没有被挂载，应该先看 `MoviePilot/app/api/endpoints/plugin.py`
- 某个 Vue 远程页面为什么没有出现在侧栏，应该先看 `MoviePilot-Frontend` 的联邦加载与菜单逻辑
- 某个插件为什么在插件市场里没显示，才应该先看本仓库的 `package.json` / `package.v2.json`

## 2. 目录结构

本仓库当前采用如下结构：

```text
MoviePilot-Plugins/
├── plugins/                 # 默认插件目录
├── plugins.v2/              # V2 专用插件目录
├── icons/                   # 插件图标
├── docs/                    # 文档
├── package.json             # 默认插件索引
├── package.v2.json          # V2 优先插件索引
└── .github/workflows/       # 自动发布工作流
```

关键约定：

- 一个插件一个目录。
- 目录名必须是插件类名的小写，例如 `class AutoSignIn` 对应目录 `autosignin/`。
- 插件主类必须定义在该目录的 `__init__.py` 中。
- 插件目录内可附带：
  - `requirements.txt`：额外 Python 依赖
  - `README.md`：插件专属使用说明
  - `dist/assets/`：Vue 联邦构建产物
  - 其他运行时所需静态文件

## 3. 元数据文件说明

### 3.1 `package.json`

默认插件索引文件，用于：

- 旧版兼容或默认版本插件
- 对 V2 兼容但不需要单独维护代码目录的插件

如果某个默认插件也能用于 V2，需要在条目上声明：

```json
{
  "MyPlugin": {
    "version": "1.2.3",
    "v2": true
  }
}
```

### 3.2 `package.v2.json`

V2 优先插件索引文件。MoviePilot 在 V2 环境下会优先读取这里的条目；找不到时，才会回退到 `package.json` 中声明了 `"v2": true` 的兼容插件。

### 3.3 常用字段

每个索引条目通常包含：

- `name`：插件展示名
- `description`：插件简介
- `labels`：标签，多个标签使用英文逗号分隔
- `version`：插件版本
- `icon`：图标文件名或完整 HTTP URL
- `author`：作者
- `level`：用户可见级别
- `history`：更新日志
- `release`：是否使用 GitHub Release 压缩包发布
- `v2`：默认索引中的插件是否兼容 V2

这些字段是“插件市场展示元数据”，而不是运行时唯一真相。真正加载后的插件类仍然需要在代码里声明自己的 `plugin_name`、`plugin_desc`、`plugin_version` 等属性。两者必须同步。

## 4. 版本选择与加载规则

MoviePilot 当前的插件版本选择逻辑可以概括为：

1. 先确定当前宿主版本标识，例如 `v2`
2. 优先检查 `package.v2.json` 中是否存在该插件
3. 若不存在，再检查 `package.json`
4. 只有当 `package.json` 中对应条目显式声明 `"v2": true` 时，才会作为 V2 兼容插件继续使用

这意味着：

- 同一个插件若在 `package.v2.json` 中已有专用实现，就不要再依赖 `package.json` 中的兼容声明做“隐式覆盖”。
- 新写的 V2 专用插件，优先放 `plugins.v2/`，并把元数据写入 `package.v2.json`。
- 真正跨版本共用一套实现时，再使用 `package.json + "v2": true` 的方式。

## 5. 与宿主仓库的协作边界

### 5.1 与 `MoviePilot` 后端的边界

本仓库只保存插件实现，不应复制宿主的公共能力。插件应优先复用后端仓库已经提供的抽象，例如：

- `_PluginBase`
- `eventmanager`
- `DownloaderHelper` / `MediaServerHelper` / `NotificationHelper`
- `save_data()` / `get_data()` / `get_data_path()`
- 插件 API 动态注册
- 插件仪表板、服务、工作流动作、智能体工具扩展点

如果插件需要新增宿主接口，例如：

- 新的链式事件
- 新的插件 API 渲染能力
- 新的工作流动作契约
- 新的智能体工具注入点

应先在 `MoviePilot` 中补齐宿主能力，再回到本仓库落插件实现。

### 5.2 与 `MoviePilot-Frontend` 的边界

插件有两种主要 UI 方式：

- Vuetify JSON 配置
- Vue 联邦远程组件

前者的宿主渲染在 `MoviePilot-Frontend` 已经实现，插件只需要返回 JSON 结构；后者需要遵守前端仓库的联邦组件暴露规范、共享依赖规范和侧栏入口规范。

如果你在本仓库写了 Vue 模式插件，需要同时关注：

- `MoviePilot-Frontend/docs/module-federation-guide.md`
- `MoviePilot-Frontend/src/utils/federationLoader.ts`
- `MoviePilot-Frontend` 中与插件页面、侧栏导航、仪表板相关的组件

## 6. 开发一个插件时的推荐流程

### 6.1 先判断插件形态

- 只是扩展后端能力、配置项简单：优先写 Vuetify JSON 模式插件
- 需要复杂交互或完整页面：使用 Vue 联邦模式
- 只是给现有插件补 V2 兼容：优先评估能否复用 `package.json + "v2": true`
- 已经与 V1 / 默认版本差异很大：直接转为 `plugins.v2/ + package.v2.json`

### 6.2 再落目录与元数据

最小步骤通常是：

1. 在 `plugins/` 或 `plugins.v2/` 下新建目录
2. 在 `__init__.py` 中实现插件类
3. 如有依赖，增加 `requirements.txt`
4. 在 `package.json` 或 `package.v2.json` 中补齐元数据
5. 如有插件文档，在插件目录补充 `README.md`
6. 如有 Vue UI，构建后把产物放进 `dist/assets/`

### 6.3 维护版本一致性

发布前至少核对以下三处是否一致：

- 索引里的 `version`
- 插件类里的 `plugin_version`
- `history` 中最新一条变更说明

## 7. 校验建议

这个仓库没有独立的完整测试宿主，因此校验应该尽量贴近真实运行层。

### 7.1 Python 插件代码

建议在宿主环境里做最小校验：

```bash
# 对修改过的插件文件做语法检查
python3 -m py_compile plugins.v2/myplugin/__init__.py

# 或者对整个插件目录做批量编译检查
python3 -m compileall plugins.v2/myplugin

# 顺手检查 diff 中是否有空白符问题
git diff --check
```

### 7.2 Vue 远程组件

如果插件使用独立的前端工程，建议至少执行：

```bash
# 类型检查
yarn typecheck

# 构建联邦产物
yarn build
```

然后再把构建产物拷贝到插件目录中的 `dist/assets/`。

### 7.3 宿主联调

以下场景必须回到宿主仓库验证：

- `get_api()` 是否真正注册成功
- `get_service()` 是否出现在服务列表
- `get_dashboard()` / `get_dashboard_meta()` 是否正常显示
- `get_render_mode() == "vue"` 的远程组件是否能成功加载
- `get_sidebar_nav()` 是否正确出现在前端侧栏

## 8. 发布流程

本仓库的自动发布逻辑位于 `.github/workflows/release.yml`，当前规则如下：

- 只有当 `package.json` 或 `package.v2.json` 发生变更时，工作流才会触发
- 只有索引条目中声明了 `"release": true` 的插件会参与自动打包
- 工作流会尝试在 `plugins/<plugin_id_lower>` 和 `plugins.v2/<plugin_id_lower>` 中寻找插件目录
- Release Tag 格式为 `插件ID_v插件版本号`
- 压缩包文件名格式为 `插件目录小写_v插件版本号.zip`
- 若插件目录自上一个 Tag 以来没有变化，则会跳过打包
- 若同名 Release / Tag 已存在，工作流会先删除旧对象再重新创建

这意味着发布一个可下载压缩包的插件时，最少要确认：

1. 插件目录存在且名称正确
2. 索引条目中已声明 `"release": true`
3. 索引版本号与代码版本号一致
4. 目标目录自上一个同插件 Tag 以来确实有代码变化

## 9. 文档维护建议

如果一次改动同时涉及：

- 插件能力扩展点变更
- 宿主后端新增接口或新契约
- 前端新增加载规则或侧栏行为

应同步更新对应仓库文档，不要只改本仓库 README。

推荐文档分工：

- 本仓库 `README.md`：总览与主入口
- 本仓库 `docs/FAQ.md`：FAQ 索引与场景入口
- 本仓库 `docs/Repository_Guide.md`：仓库维护与发布规则
- 本仓库 `docs/V2_Plugin_Development.md`：V2 插件开发主文档
- 前端仓库 `docs/module-federation-guide.md`：Vue 联邦远程组件开发规范

## 10. 开始之前先读哪一份

- 想知道“这个仓库该怎么维护、改哪个文件、怎么发布”：看本文档
- 想直接开发一个 V2 插件：看 `docs/V2_Plugin_Development.md`
- 想做 Vue 远程组件或侧栏全页：看前端仓库模块联邦文档
- 想按功能场景抄现成模式：看 `docs/FAQ.md` 和 `docs/faq/` 下的独立 FAQ 文档
