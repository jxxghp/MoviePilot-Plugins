# 17. 如何将插件页面注册到主界面左侧导航栏？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

插件进入左侧导航栏走的是 **Vue 远程组件全页入口**，不是 `get_page()` 的详情弹窗。完整链路是：插件后端声明 Vue 渲染模式和侧栏入口，MoviePilot 后端通过 `GET /api/v1/plugin/sidebar_nav` 聚合，前端把入口插入对应分组并跳转到 `#/plugin-app/<PluginID>/<nav_key>`，再加载插件暴露的 `AppPage` 组件。

## 1. 后端插件要做什么？

插件必须同时满足这些条件：

- 插件已启用，`get_state()` 返回 `True`。
- `get_render_mode()` 返回 `("vue", "dist/assets")` 或你的实际构建产物目录。
- 实现 `get_sidebar_nav()` 并返回一个列表。
- 插件目录下存在前端构建产物，至少包含 `remoteEntry.js` 和被暴露的组件文件。

示例：

```python
from typing import Any, Dict, List, Tuple


def get_render_mode(self) -> Tuple[str, str]:
    """
    声明插件使用 Vue 远程组件渲染，并指定构建产物目录。
    """
    return "vue", "dist/assets"


def get_sidebar_nav(self) -> List[Dict[str, Any]]:
    """
    声明插件在主界面左侧导航栏中的全页入口。
    """
    return [
        {
            "nav_key": "main",
            "title": "我的插件",
            "icon": "mdi-puzzle",
            "section": "system",
            "permission": "manage",
            "order": 10,
        }
    ]
```

字段说明：

| 字段 | 是否必填 | 说明 |
|------|----------|------|
| `nav_key` | 否 | 当前插件内的入口标识，默认 `main`；会进入 URL 路径段 |
| `title` | 否 | 侧栏显示标题，未填时使用插件名称 |
| `icon` | 否 | MDI 图标名，未填时使用 `mdi-puzzle` |
| `section` | 否 | 侧栏分组：`start` / `discovery` / `subscribe` / `organize` / `system`，无效值会归入 `system` |
| `permission` | 否 | 菜单权限：`subscribe` / `discovery` / `search` / `manage` / `admin`，未填则不额外限制 |
| `order` | 否 | 同组内排序，数值越小越靠前 |

注意：

- `nav_key` 不能包含 `/`、`?`、`#`、空格；建议使用 `main`、`settings`、`history`、`my_tool` 这类稳定值。
- `get_page()` 只影响插件管理里的详情弹窗；要出现在主界面左侧导航，必须实现 `get_sidebar_nav()`。
- 如果插件依赖这个新前端能力，建议在 `package.json` / `package.v2.json` 中用 `system_version` 限定最低 MoviePilot 版本。

## 2. 前端远程组件要暴露什么？

前端工程需要在模块联邦里暴露全页组件：

```typescript
federation({
  name: 'MyPlugin',
  filename: 'remoteEntry.js',
  exposes: {
    './AppPage': './src/components/AppPage.vue',
  },
})
```

`AppPage.vue` 会收到主应用传入的 `api`、`pluginId`、`navKey`：

```vue
<script setup lang="ts">
const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: '' },
  navKey: { type: String, default: 'main' },
})
</script>

<template>
  <div class="pa-4">
    {{ props.pluginId }} / {{ props.navKey }}
  </div>
</template>
```

如果页面需要调用插件后端 API，后端 `get_api()` 建议使用 `auth: "bear"`，前端通过传入的 `api` 调用：

```typescript
const rows = await props.api.get(`plugin/${props.pluginId}/history`)
```

## 3. 多个导航入口怎么做？

`get_sidebar_nav()` 可以返回多条记录：

```python
def get_sidebar_nav(self) -> List[Dict[str, Any]]:
    """
    声明同一插件的多个左侧导航入口。
    """
    return [
        {
            "nav_key": "main",
            "title": "处理面板",
            "icon": "mdi-view-dashboard",
            "section": "organize",
            "permission": "manage",
            "order": 20,
        },
        {
            "nav_key": "settings",
            "title": "处理设置",
            "icon": "mdi-cog",
            "section": "system",
            "permission": "manage",
            "order": 21,
        },
    ]
```

前端加载规则：

| `nav_key` | 依次尝试的联邦暴露名 |
|-----------|----------------------|
| `main` 或省略 | `./AppPage` -> `./Page` |
| 其它，例如 `settings` | `./AppPageSettings` -> `./AppPage` -> `./Page` |
| 其它，例如 `my_tool` | `./AppPageMyTool` -> `./AppPage` -> `./Page` |

也就是说你可以只暴露一个 `./AppPage`，在组件内根据 `navKey` 分支渲染；也可以为不同入口分别暴露 `./AppPageSettings`、`./AppPageHistory` 等组件。

## 4. 排查清单

- `GET /api/v1/plugin/sidebar_nav` 是否能看到你的插件入口。
- `GET /api/v1/plugin/remotes?token=moviepilot` 是否能看到你的插件远程组件入口。
- 插件是否启用，且 `get_render_mode()` 是否返回 `vue`。
- `dist/assets/remoteEntry.js` 是否实际安装到了插件运行目录。
- `nav_key` 是否包含非法字符，或和前端暴露名不匹配。
- 当前用户是否有 `permission` 声明的权限；超级用户默认拥有全部权限。
- 前端侧栏会缓存 `plugin/sidebar_nav` 结果，插件启停或变更入口后建议刷新页面重新加载。
