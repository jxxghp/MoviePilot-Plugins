# 22. 如何通过插件提供智能助手形象？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

页面右下角的智能助手默认显示内置机器人。插件可以提供新的**助手形象**替换它，用户在智能助手面板头部点“更换形象”选择，管理员可以设置默认形象。完整链路是插件后端用 `get_agent_pets()` 声明形象，MoviePilot 后端通过 `GET /api/v1/plugin/agent_pets` 聚合，前端按用户选择加载插件暴露的联邦组件。

形象只负责角色本身。Agent 面板、会话、模型、工具调用和权限始终由主程序掌握，插件不能接管面板，也不能替用户发送消息。

完整的参考插件见 [AgentPets（助手形象）](https://github.com/InfinityPacer/MoviePilot-Plugins/tree/main/plugins.v3/agentpets)。

## 1. 后端插件要做什么？

插件需要同时满足以下条件。

- 插件已启用，`get_state()` 返回 `True`。
- `get_render_mode()` 返回 `("vue", "dist/assets")` 或你的实际构建产物目录。
- 实现 `get_agent_pets()` 并返回一个列表。
- 插件目录下存在前端构建产物，至少包含 `remoteEntry.js` 和被暴露的形象组件。

```python
from typing import Any, Dict, List, Tuple


def get_render_mode(self) -> Tuple[str, str]:
    """
    声明插件使用 Vue 远程组件渲染，并指定构建产物目录。
    """
    return "vue", "dist/assets"


def get_agent_pets(self) -> List[Dict[str, Any]]:
    """
    声明插件提供的智能助手形象。
    """
    return [
        {
            "key": "girl",
            "name": "看板娘",
            "description": "会在页面底部散步的 Q 版角色",
            "mode": "stage",
            "preview": "girl-preview.png",
            "avatar": "girl-avatar.png",
        }
    ]
```

字段说明如下。

| 字段 | 是否必填 | 说明 |
|------|----------|------|
| `key` | 是 | 插件内唯一，匹配 `[a-z0-9_-]{1,32}` |
| `name` | 是 | 形象展示名，选中后也作为助手面板标题和消息署名 |
| `description` | 否 | 一句话说明 |
| `mode` | 否 | `renderer`（默认，主程序负责入口行为，插件只画角色）或 `stage`（插件拥有角色和整个视口图层） |
| `component` | 否 | 联邦暴露名，默认 `AgentPet`，即 `./AgentPet` |
| `api_version` | 否 | 契约版本，默认 `1`，主程序不认识的版本会被忽略 |
| `preview` | 否 | 预览图，相对 `remoteEntry.js` 所在目录（即 `get_render_mode()` 返回的目录）的路径，或 `http(s)://`、`data:` URL |
| `avatar` | 否 | 方形头像，路径规则同 `preview`，用于助手面板头部、空状态和消息头像 |
| `bubbles` | 否 | 仅 `stage`，`host`（插件上报位置，主程序画气泡，默认）或 `self`（插件自己画气泡） |
| `random_actions` | 否 | 仅 `renderer`，限定主程序随机播放的动作，空列表表示不播随机动作 |

注意事项如下。

- 任一字段非法的项会整项丢弃并在日志中记录警告，同一插件内重复的 `key` 只保留第一项。
- 图片文件放在 `remoteEntry.js` 同级目录，随构建产物一起发布。上例中 `get_render_mode()` 返回 `dist/assets`，图片应位于 `dist/assets/girl-preview.png`，声明写 `girl-preview.png`。写成 `assets/girl-preview.png` 会被解析到 `dist/assets/assets/girl-preview.png` 而加载不到。
- `preview` 和 `avatar` 的相对路径不能包含 `..`、`\` 或 `:`。
- 选中形象后，面板头像依次使用 `avatar`、`preview`，都不可用时退回内置图标。
- 依赖这项能力的插件，建议按 [限定主系统版本](./18-limit-moviepilot-version.md) 声明 `system_version`。

## 2. 两种模式怎么选？

| 模式 | 适合 | 插件负责 | 主程序负责 |
|------|------|----------|------------|
| `renderer` | 只想换外观，沿用内置入口的交互 | 在入口热区里画角色，按主程序给的动作名播放动画 | 位置、拖拽、贴边、随机动作、点击开面板、气泡 |
| `stage` | 需要自由走动、物理效果或自定义交互的全屏角色 | 整个角色，包括外观、位置、拖拽和点击开面板 | 提供覆盖全视口的透明图层，按需在角色旁画气泡 |

`stage` 图层不拦截点击，插件只在自己的角色元素上设置 `pointer-events: auto`，点击角色时调用 `agent.open()` 打开面板。

## 3. 一个插件能提供多个形象吗？

可以。`get_agent_pets()` 返回多项，每项都会作为独立选项出现在“更换形象”里，各项可以使用不同的 `mode` 和 `component`。

```python
def get_agent_pets(self) -> List[Dict[str, Any]]:
    """
    同一插件提供多个形象。
    """
    return [
        {"key": "girl", "name": "看板娘", "mode": "stage", "component": "StagePet"},
        {"key": "cat", "name": "小猫", "mode": "renderer", "component": "SpritePet"},
        {"key": "dog", "name": "小狗", "mode": "renderer", "component": "SpritePet"},
    ]
```

前端工程需要暴露所有被引用的组件。

```typescript
federation({
  name: 'MyPetPlugin',
  filename: 'remoteEntry.js',
  exposes: {
    './StagePet': './src/components/StagePet.vue',
    './SpritePet': './src/components/SpritePet.vue',
  },
})
```

多项共用同一个组件时，组件内用 `pet.key` 区分当前形象。

## 4. 形象组件能拿到什么？

形象组件会收到 `agent`、`pet`、`api`、`pluginId`、`sourcePluginId`，`renderer` 模式还会收到 `action`、`intent`、`thinking`、`motionActive`。

- `agent` 用来读取助手状态（是否在思考、当前阶段、主题、视口等）、订阅 `agent.*` 事件、打开或关闭面板。`agent.open({ draft })` 只把草稿填进输入框，不会发送。
- `pet.storage` 用来按用户保存位置、偏好这类小块数据，序列化后不能超过 16KB。
- 插件自己的配置页、详情页和全页也能通过 `inject('moviepilot:agent')` 拿到同一个 `agent`，可以用 `agent.emit()` 广播自定义事件，让正在运行的形象实时预览配置。

props 的完整类型、事件表、`phase` 含义、主程序事件到 `renderer` 动作的对照、回退规则和 `stage` 最小示例见 [MoviePilot-Frontend 模块联邦指南](https://github.com/jxxghp/MoviePilot-Frontend/blob/v3/docs/module-federation-guide.md) 的“5.11 Agent 助手形象（AgentPet）”章节。

## 5. 排查清单

- `GET /api/v1/plugin/agent_pets` 是否能看到你的形象，没有时查看后端日志里的“助手形象声明无效”警告。
- 插件是否启用，且 `get_render_mode()` 是否返回 `vue`。
- `dist/assets/remoteEntry.js` 和 `component` 对应的暴露名是否都已安装到插件运行目录。
- 系统设置里是否打开了“启用智能助手”且没有打开“隐藏全局入口”，入口隐藏时不会加载任何形象。
- 选中后仍显示内置机器人，说明形象加载失败、超过 8 秒或运行时报错，在浏览器控制台查找 `[agent-pet]` 警告。
