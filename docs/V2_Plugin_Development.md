# MoviePilot V2 插件开发指南

本文档说明如何开发适用于 MoviePilot V2 的插件，并尽量以当前 `MoviePilot` 与 `MoviePilot-Frontend` 主仓库的真实实现为准，而不是停留在早期兼容阶段的概念说明。

关联阅读：

- [仓库指南](./Repository_Guide.md)
- [FAQ 索引](./FAQ.md)
- [MoviePilot 前端模块联邦开发指南](https://github.com/jxxghp/MoviePilot-Frontend/blob/v2/docs/module-federation-guide.md)

## 1. 先理解 V2 插件的运行模型

V2 插件始终运行在 `MoviePilot` 后端宿主内，当前插件仓库只提供：

- 插件源码
- 插件市场索引
- 插件图标
- 插件文档

V2 插件的 UI 则有两种模式：

- `vuetify`：插件返回 JSON 配置，由 `MoviePilot-Frontend` 负责渲染
- `vue`：插件提供联邦远程组件，由前端动态加载

因此，开发一个 V2 插件通常至少会涉及三个部分：

1. 本仓库中的插件实现与元数据
2. `MoviePilot` 中的插件宿主能力
3. `MoviePilot-Frontend` 中的渲染与加载逻辑

## 2. V2 的版本选择规则

MoviePilot 处理插件版本时，当前逻辑可以总结为：

1. 宿主先根据当前版本标识优先读取 `package.v2.json`
2. 若目标插件不在 `package.v2.json` 中，再检查 `package.json`
3. `package.json` 中只有显式声明了 `"v2": true` 的插件，才会被视为 V2 兼容插件

建议按下列方式选型：

- **V2 专用实现**：放在 `plugins.v2/<plugin_id_lower>/`，元数据写入 `package.v2.json`
- **单实现跨版本兼容**：代码继续放在 `plugins/<plugin_id_lower>/`，在 `package.json` 中声明 `"v2": true`
- **V1/V2 差异已经很大**：不要继续强行共用目录，直接拆到 `plugins.v2/`

## 3. 最小 V2 插件骨架

一个最小可运行的 V2 插件通常如下：

```text
plugins.v2/
└── myplugin/
    ├── __init__.py
    ├── requirements.txt          # 可选，只有插件有额外依赖时才需要
    └── README.md                 # 可选，插件自己的说明文档
```

`__init__.py` 示例：

```python
from typing import Any, Dict, List, Tuple

from app.plugins import _PluginBase


class MyPlugin(_PluginBase):
    # 插件在界面中的展示名称
    plugin_name = "我的插件"
    # 插件描述
    plugin_desc = "一个最小可运行的 V2 插件示例。"
    # 插件图标
    plugin_icon = "Moviepilot_A.png"
    # 插件版本，必须和 package.v2.json 中保持一致
    plugin_version = "1.0.0"
    # 作者信息
    plugin_author = "your-name"
    author_url = "https://github.com/your-name"
    # 配置项前缀，建议保持唯一，避免与其他插件冲突
    plugin_config_prefix = "myplugin_"
    # 插件加载顺序，数值越小越早
    plugin_order = 50
    # 插件可见权限级别
    auth_level = 1

    # 运行时状态字段
    _enabled = False
    _message = "插件尚未初始化"

    def init_plugin(self, config: dict = None):
        """根据当前配置初始化插件。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._message = config.get("message") or "Hello MoviePilot"

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """没有远程命令时直接返回空列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """没有插件 API 时直接返回空列表。"""
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回配置页 JSON 和默认配置模型。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "message",
                                            "label": "展示文本",
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ], {
            "enabled": False,
            "message": "Hello MoviePilot",
        }

    def get_page(self) -> List[dict]:
        """返回详情页 JSON。"""
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": self._message,
                },
            }
        ]

    def stop_service(self):
        """没有后台任务时可以留空。"""
        pass
```

对应的 `package.v2.json` 条目至少应包含：

```json
{
  "MyPlugin": {
    "name": "我的插件",
    "description": "一个最小可运行的 V2 插件示例。",
    "labels": "示例",
    "version": "1.0.0",
    "icon": "Moviepilot_A.png",
    "author": "your-name",
    "level": 1
  }
}
```

## 4. `_PluginBase` 的核心能力

V2 插件的核心宿主基类是 `MoviePilot/app/plugins/__init__.py` 中的 `_PluginBase`。开发时需要优先理解它暴露出来的扩展点。

### 4.1 必选方法

以下方法通常必须实现：

- `init_plugin(self, config: dict = None)`：读取配置并生效
- `get_state(self) -> bool`：返回当前运行状态
- `get_api(self) -> List[dict]`：声明插件 API
- `get_form(self) -> Tuple[page_json, model]`：声明配置页
- `get_page(self) -> List[dict] | None`：声明详情页
- `stop_service(self)`：停用插件时清理后台任务、线程、调度器等

### 4.2 常用可选方法

- `get_command()`：注册远程命令
- `get_service()`：注册公共服务
- `get_dashboard()`：声明仪表板内容
- `get_dashboard_meta()`：声明多仪表板元信息
- `get_render_mode()`：选择 `vuetify` / `vue`
- `get_module()`：重载系统模块
- `get_actions()`：注册工作流动作
- `get_agent_tools()`：注册智能体工具
- `get_sidebar_nav()`：Vue 全页插件向主界面侧栏声明入口

### 4.3 基类自带的辅助能力

基类已经提供了一些很关键的工具方法，通常不需要自行重复造轮子：

- `get_config()` / `update_config()`：读取与保存插件配置
- `get_data_path()`：获取插件自己的数据目录
- `save_data()` / `get_data()` / `del_data()`：读写插件持久化数据
- `post_message()`：通过系统通知渠道发消息
- `self.chain`：插件链式能力入口
- `self.systemconfig` / `self.plugindata`：宿主已有的配置与数据操作封装

## 5. 配置、数据与分身兼容

### 5.1 配置读写

最常见的模式是：

```python
def init_plugin(self, config: dict = None):
    config = config or {}
    self._enabled = bool(config.get("enabled"))


def _save_current_config(self):
    # 这里保存的是插件自己的配置快照
    self.update_config({
        "enabled": self._enabled,
    })
```

### 5.2 数据保存

如果插件要保存运行结果、缓存文件或状态快照，优先使用基类提供的数据目录和数据表：

```python
from pathlib import Path


def write_report(self, content: str):
    # 每个插件都有自己的独立数据目录
    report_path: Path = self.get_data_path() / "report.txt"
    report_path.write_text(content, encoding="utf-8")


def save_runtime_state(self, state: dict):
    # 结构化小数据优先放 plugindata
    self.save_data("runtime_state", state)
```

### 5.3 分身友好写法

MoviePilot 支持插件分身，因此建议遵守这些规则：

- 不要把插件 ID 写死到字符串里到处拼接
- 优先使用 `self.__class__.__name__`
- `plugin_config_prefix` 必须唯一
- 如果你需要通过宿主 API 反向查找自己，优先从当前类名或运行时实例出发

这样插件被分身后，配置前缀、类名替换和数据隔离更容易保持正确。

## 6. V2 常见能力面

### 6.1 远程命令 `get_command()`

用于注册 `/xx` 形式的远程命令。最常见的方式是：

1. `get_command()` 暴露命令元数据
2. 监听 `EventType.PluginAction`
3. 根据 `event_data["action"]` 判断是否是自己的动作

示例：

```python
from typing import Any, Dict, List

from app.core.event import eventmanager, Event
from app.schemas.types import EventType


@staticmethod
def get_command() -> List[Dict[str, Any]]:
    return [
        {
            "cmd": "/my_plugin_run",
            "event": EventType.PluginAction,
            "desc": "执行我的插件",
            "category": "插件命令",
            "data": {
                # 用 action 做路由最稳妥
                "action": "my_plugin_run",
            },
        }
    ]


@eventmanager.register(EventType.PluginAction)
def run_command(self, event: Event):
    event_data = event.event_data or {}
    if event_data.get("action") != "my_plugin_run":
        return
    # 这里写实际业务逻辑
```

### 6.2 插件 API `get_api()`

插件 API 会被动态注册到：

```text
/api/v1/plugin/<PluginID>/<path>
```

示例：

```python
def get_api(self) -> List[Dict[str, Any]]:
    return [
        {
            "path": "/history",
            "endpoint": self.get_history,
            "methods": ["GET"],
            # 前端插件页面通过 api 模块调用时，通常使用 bear
            "auth": "bear",
            "summary": "查询插件历史",
            "description": "返回插件最近的处理历史",
        }
    ]
```

说明：

- `auth` 支持 `apikey` 和 `bear`
- 面向插件前端页面的接口，通常使用 `bear`
- 面向外部系统调用的接口，可使用 `apikey`
- 如无特殊原因，不要默认匿名开放

### 6.3 公共服务 `get_service()`

服务注册后会出现在 MoviePilot 的服务管理中，适合定时任务、周期刷新、批处理工作。

示例：

```python
from apscheduler.triggers.cron import CronTrigger


def get_service(self) -> List[Dict[str, Any]]:
    if not self.get_state():
        return []
    return [
        {
            "id": "MyPlugin.Refresh",
            "name": "我的插件定时刷新",
            "trigger": CronTrigger.from_crontab("0 */6 * * *"),
            "func": self.refresh,
            "kwargs": {},
        }
    ]
```

注意：

- `id` 必须稳定且唯一
- 禁用插件时要在 `stop_service()` 中清理自己的后台资源
- 如果服务需要“启用后立刻跑一次”，可配合 `date` 触发器单独注册一条即时任务

### 6.4 仪表板 `get_dashboard()` / `get_dashboard_meta()`

单仪表板插件可只实现 `get_dashboard()`；多仪表板插件建议额外实现 `get_dashboard_meta()`。

示例：

```python
from typing import Any, Dict, List, Optional, Tuple


def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
    return [
        {"key": "summary", "name": "摘要"},
        {"key": "trend", "name": "趋势"},
    ]


def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
    col_config = {"cols": 12, "md": 6}
    global_config = {
        "title": "我的插件",
        "refresh": 30,
        "border": True,
    }
    page = [
        {
            "component": "VAlert",
            "props": {
                "type": "info",
                "text": f"当前仪表板 key: {key}",
            },
        }
    ]
    return col_config, global_config, page
```

### 6.5 工作流动作 `get_actions()`

工作流动作适合把插件能力暴露给系统工作流调用。动作函数的第一个参数固定为 `ActionContent`，返回值需要遵循宿主约定。

```python
def get_actions(self) -> List[Dict[str, Any]]:
    return [
        {
            "id": "my_plugin_action",
            "name": "执行我的插件动作",
            "func": self.run_action,
            "kwargs": {
                # 这里可以预置额外参数
                "mode": "fast",
            },
        }
    ]
```

### 6.6 系统模块重载 `get_module()`

当插件要接管某个系统模块能力时，可通过 `get_module()` 映射方法实现。所有可重载的方法名，需要以 `MoviePilot/app/chain/` 中实际调用的模块名为准。

```python
def get_module(self) -> Dict[str, Any]:
    return {
        # 键名必须与宿主链式调用的模块名一致
        "my_custom_handler": self.handle_custom_logic,
    }
```

这种能力侵入性较强，只有在插件确实要扩展宿主链路时才建议使用。

### 6.7 智能体工具 `get_agent_tools()`

插件可以为 MoviePilot 的 AI 智能体扩展工具。每个工具类必须继承 `MoviePilotTool`。

示例：

```python
from typing import List, Optional, Type

from pydantic import BaseModel, Field
from app.agent.tools.base import MoviePilotTool


class QueryInput(BaseModel):
    """工具入参模型。"""

    keyword: str = Field(..., description="要查询的关键字")


class MyQueryTool(MoviePilotTool):
    """最小智能体工具示例。"""

    name: str = "my_query_tool"
    description: str = "Query plugin data by keyword."
    args_schema: Type[BaseModel] = QueryInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        # 这里返回给用户的提示语
        return f"正在查询关键字：{kwargs.get('keyword', '')}"

    async def run(self, keyword: str, **kwargs) -> str:
        # 这里实现工具实际逻辑
        return f"查询完成：{keyword}"


def get_agent_tools(self) -> List[type]:
    return [MyQueryTool]
```

如果需要真实案例，可以参考本仓库 `plugins.v2/lexiannot/agenttool.py`。

## 7. 渲染模式

### 7.1 Vuetify JSON 模式

这是默认模式，`get_render_mode()` 不需要额外实现，宿主默认按 `vuetify` 处理。

适用场景：

- 普通配置表单
- 详情页
- 轻量数据列表
- 仪表板卡片

规则：

- `get_form()` 返回“页面 JSON + 默认模型”
- `get_page()` 返回页面 JSON
- `get_dashboard()` 返回“列配置 + 全局配置 + 页面 JSON”
- `props.model` 等效于 `v-model`
- `props.show` 等效于 `v-show`
- 配置页支持 `{{ ... }}` 表达式与 `onxxx` 事件

### 7.2 Vue 联邦模式

如果插件要完全使用 Vue 组件渲染，需要实现：

```python
from typing import Tuple


def get_render_mode(self) -> Tuple[str, str]:
    # 第二个返回值是远程组件构建产物所在目录
    return "vue", "dist/assets"
```

此时：

- `get_form()` / `get_page()` 可返回 `([], {})`、`[]` 或 `None`
- 前端会通过 `/api/v1/plugin/remotes` 获取远程组件列表
- 静态资源由 `MoviePilot` 后端负责对外提供

若需要独立侧栏页面，还要实现 `get_sidebar_nav()`。

### 7.3 侧栏全页入口 `get_sidebar_nav()`

只有 Vue 模式插件才会被主界面侧栏聚合。

示例：

```python
from typing import Any, Dict, List


def get_sidebar_nav(self) -> List[Dict[str, Any]]:
    return [
        {
            "nav_key": "main",
            "title": "我的插件首页",
            "icon": "mdi-puzzle",
            "section": "system",
            "permission": "manage",
            "order": 10,
        },
        {
            "nav_key": "settings",
            "title": "我的插件设置",
            "icon": "mdi-cog",
            "section": "system",
            "permission": "manage",
            "order": 11,
        },
    ]
```

当前宿主约束：

- `section` 只接受：`start`、`discovery`、`subscribe`、`organize`、`system`
- `permission` 只接受：`subscribe`、`discovery`、`search`、`manage`、`admin`
- `nav_key` 不能包含 `/`、`?`、`#`、空格

多入口全页插件的联邦暴露名规则，详见前端仓库的模块联邦开发指南。

## 8. 公共服务封装建议

V2 下很多插件都依赖下载器、媒体服务器、通知渠道等宿主服务。不要自行重复读取系统配置，优先使用宿主帮助类。

常见帮助类包括：

- `DownloaderHelper`
- `MediaServerHelper`
- `NotificationHelper`

典型写法：

```python
from app.helper.downloader import DownloaderHelper


def run_with_downloader(self, name: str):
    # 通过帮助类获取已启用的下载器实例和配置
    service = DownloaderHelper().get_service(name=name)
    if not service:
        return False
    downloader = service.instance
    # 这里调用实际下载器能力
    return downloader is not None
```

这样做的好处是：

- 自动复用宿主对系统配置的解析
- 自动获取“启用中的实例”
- 降低插件和底层模块的耦合

## 9. 调试与校验

### 9.1 Python 层

推荐最小校验：

```bash
python3 -m py_compile plugins.v2/myplugin/__init__.py
python3 -m compileall plugins.v2/myplugin
git diff --check
```

### 9.2 API 层

如果插件定义了 `get_api()`：

- 启动宿主后检查 `/docs`
- 确认路由实际注册在 `/api/v1/plugin/<PluginID>/...`
- 区分 `apikey` 与 `bear` 的认证方式是否符合调用场景

### 9.3 前端层

如果插件使用 Vue 远程组件：

- 在前端工程中先执行 `yarn typecheck`
- 再执行 `yarn build`
- 确认最终上传的是联邦所需产物，而不是整个前端源码目录

## 10. 发布清单

发布前建议至少逐项确认：

1. 插件目录在 `plugins/` 或 `plugins.v2/` 下位置正确
2. 目录名与类名小写一致
3. 元数据已写入正确的索引文件
4. 索引里的 `version` 与代码里的 `plugin_version` 一致
5. `history` 已补齐本次变更说明
6. 若使用 Release 分发，条目已声明 `"release": true`
7. Python 代码完成最小语法校验
8. 若有 Vue 远程组件，构建产物已更新

## 11. 什么时候还要回去看宿主源码

下面这些问题，不建议只看本仓库文档判断：

- 插件为什么没有显示在插件市场
- 插件 API 为什么没有注册成功
- 服务为什么没有进入服务管理
- 插件仪表板为什么没有加载
- Vue 联邦页面为什么没有出现在侧栏
- 某个 `permission` / `section` / `nav_key` 为什么不生效

这类问题本质上都与宿主实现有关，应回到：

- `MoviePilot/app/core/plugin.py`
- `MoviePilot/app/api/endpoints/plugin.py`
- `MoviePilot/app/plugins/__init__.py`
- `MoviePilot-Frontend/docs/module-federation-guide.md`
- `MoviePilot-Frontend/src/utils/federationLoader.ts`

## 12. 结论

开发 V2 插件时，最重要的不是“把代码放进 `plugins.v2/`”，而是同时把下面三件事做对：

1. 运行时契约对齐宿主 `_PluginBase`
2. 索引元数据与插件代码保持一致
3. 渲染模式与前端加载方式匹配

做到这三点，插件的开发、升级、迁移、分身和发布都会明显顺很多。
