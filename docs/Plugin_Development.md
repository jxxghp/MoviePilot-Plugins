# MoviePilot 插件开发指南（V3）

这是当前 MoviePilot V3 插件开发的主文档。无论是第一次开发插件、维护第三方插件
仓库，还是准备向官方插件仓库提交 PR，都应从这里开始。

其它文档只负责专题内容：

- [V2 插件迁移到 V3](./V3_Plugin_Adaptation.md)：旧导入兼容、数据库事务、媒体身份、
  音乐链和存量数据迁移。
- [插件 API 专题](./V3_API_Response_Adaptation.md)：后端 API、Python 调用、Vue
  远程组件和原生响应。
- [仓库与发布指南](./Repository_Guide.md)：索引文件、版本选择、CI 和 Release。
- [常见问题](./FAQ.md)：按消息、服务、工作流、缓存、Agent、存储等场景查阅。
- [V2 历史开发指南](./V2_Plugin_Development.md)：只维护仍支持 V2 的旧插件时使用，
  新插件不要从该文档开始。

## 1. 先理解插件运行在哪里

`MoviePilot-Plugins` 是插件源码、市场索引、图标和开发文档仓库，不是独立运行时。

一个插件实际涉及三个仓库：

| 仓库 | 责任 |
| --- | --- |
| `MoviePilot` | 加载插件，提供事件、服务、API、数据、工作流和 Agent 运行时 |
| `MoviePilot-Frontend` | 渲染配置页、详情页、仪表板和 Vue 联邦远程组件 |
| `MoviePilot-Plugins` | 保存插件源码、市场元数据、图标、测试和发布配置 |

插件与主程序运行在同一个 Python 进程和依赖环境中。插件不是独立微服务，也没有
独立虚拟环境，因此必须控制第三方依赖、后台线程、全局状态和导入副作用。

## 2. V3 新插件放在哪里

当前新插件使用 V3 目录和索引：

```text
MoviePilot-Plugins/
├── plugins.v3/
│   └── myplugin/
│       ├── __init__.py
│       ├── pyproject.toml      # 有额外 Python 依赖时使用
│       └── README.md           # 推荐
├── tests/
│   └── v3/
│       └── myplugin/
│           └── test_plugin.py  # 推荐
└── package.v3.json
```

必须保持以下对应关系：

- 插件主类 `MyPlugin` 对应插件 ID `MyPlugin`。
- 插件目录必须是类名的小写形式 `myplugin`。
- 主类必须定义在 `plugins.v3/myplugin/__init__.py`。
- 市场元数据写入 `package.v3.json`，键名使用插件 ID `MyPlugin`。
- 测试放在 `tests/v3/myplugin/`，不要放进插件源码目录，否则市场同步时会把测试
  一并复制到运行目录。

V3 可以回退加载部分旧实现，这是为了兼容已发布插件，不是新插件继续写入
`plugins/` 或 `plugins.v2/` 的理由。只有维护历史版本或迁移既有插件时，才需要
查看旧目录和旧索引规则。

## 3. 准备开发环境

建议把主仓库、插件仓库和前端仓库放在同一工作区：

```text
workspace/
├── MoviePilot/
├── MoviePilot-Plugins/
└── MoviePilot-Frontend/
```

后端依赖安装在 `MoviePilot/.venv`。开发和测试插件时也使用该解释器，不要另外
创建一套与宿主版本不同的依赖环境。站点资源放在主仓库的
`app/application/site/`，不要再写入已经删除的 `app/helper/`。

本地联调常用配置：

- `PLUGIN_LOCAL_REPO_PATHS`：加入本地插件仓库路径，便于宿主同步本地实现。
- `PLUGIN_AUTO_RELOAD=true`：插件源码变化后自动重新加载。
- `DEBUG=true`：显示旧导入兼容警告和更多调试信息。

插件最终必须在真实 MoviePilot V3 宿主中至少加载一次。只执行语法编译不能发现
导入路径、宿主依赖、API 注册、服务清理或前端加载问题。

## 4. 最小可运行插件

`plugins.v3/myplugin/__init__.py`：

```python
from typing import Any

from app.plugins import _PluginBase


class MyPlugin(_PluginBase):
    """演示 V3 插件的最小生命周期和页面接口。"""

    plugin_name = "我的插件"
    plugin_desc = "一个最小可运行的 MoviePilot V3 插件。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.0"
    plugin_author = "your-name"
    author_url = "https://github.com/your-name"
    plugin_config_prefix = "myplugin_"
    plugin_order = 50
    auth_level = 1

    _enabled = False
    _message = "Hello MoviePilot"

    def init_plugin(self, config: dict | None = None) -> None:
        """读取配置并建立本次运行所需状态。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._message = str(config.get("message") or "Hello MoviePilot")

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        """当前插件不注册远程命令。"""
        return []

    def get_api(self) -> list[dict[str, Any]]:
        """当前插件不注册后端 API。"""
        return []

    def get_form(self) -> tuple[list[dict], dict[str, Any]]:
        """返回配置页面和默认配置。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VSwitch",
                        "props": {
                            "model": "enabled",
                            "label": "启用插件",
                        },
                    },
                    {
                        "component": "VTextField",
                        "props": {
                            "model": "message",
                            "label": "展示文本",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "message": "Hello MoviePilot",
        }

    def get_page(self) -> list[dict]:
        """返回插件详情页。"""
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

    def stop_service(self) -> None:
        """释放插件创建的后台资源。"""
        self._enabled = False
```

对应的 `package.v3.json` 条目：

```json
{
  "MyPlugin": {
    "name": "我的插件",
    "description": "一个最小可运行的 MoviePilot V3 插件。",
    "labels": "示例",
    "version": "1.0.0",
    "icon": "Moviepilot_A.png",
    "author": "your-name",
    "level": 1,
    "system_version": ">=3.0.0",
    "history": {
      "v1.0.0": "首次发布。"
    }
  }
}
```

代码中的 `plugin_version` 与索引中的 `version` 必须一致。`history` 当前版本置顶，
并按语义版本从新到旧排列。

## 5. `_PluginBase` 生命周期

插件主类继承 `app.plugins._PluginBase`。最重要的不是实现尽可能多的方法，而是把
启用、停用和重复初始化做正确。

### 5.1 必须实现的方法

| 方法 | 责任 |
| --- | --- |
| `init_plugin(config)` | 读取配置，建立本次运行状态；必须允许重复调用 |
| `get_state()` | 返回插件是否启用 |
| `get_api()` | 返回动态 API 声明；没有则返回空列表 |
| `get_form()` | 返回配置页面和默认模型 |
| `get_page()` | 返回详情页面；没有则返回 `None` 或空列表 |
| `stop_service()` | 取消任务、关闭线程或客户端并释放资源 |

### 5.2 常用可选扩展点

| 方法 | 用途 |
| --- | --- |
| `get_command()` | 注册远程命令 |
| `get_service()` | 注册定时或周期服务 |
| `get_dashboard()` / `get_dashboard_meta()` | 注册一个或多个仪表板 |
| `get_render_mode()` | 选择 `vuetify` 或 `vue` 渲染模式 |
| `get_sidebar_nav()` | 为 Vue 插件声明侧栏全页入口 |
| `get_actions()` | 注册工作流动作 |
| `get_agent_tools()` | 注册 Agent 工具 |
| `get_auth_providers()` | 注册外部认证入口 |
| `get_module()` | 覆盖宿主模块能力；侵入性较强，谨慎使用 |

不要在模块导入期或类定义期启动任务、访问网络、连接数据库。后台资源应在
`init_plugin()` 中按配置建立，并在 `stop_service()` 中可重复、安全地释放。

## 6. 使用稳定的宿主接口

V3 已为插件整理稳定 SDK。新插件应优先从 `app.sdk` 导入，不要直接依赖
`app.application`、`app.domain`、`app.foundation`、`app.adapters` 或
`app.runtime` 的内部文件位置。

| 能力 | 推荐入口 |
| --- | --- |
| 配置 | `app.sdk.config` |
| 事件 | `app.sdk.events` |
| 日志 | `app.sdk.logging` |
| 缓存 | `app.sdk.cache` |
| 媒体上下文、名称解析和媒体身份 | `app.sdk.media` |
| HTTP、URL、站点和安全网络工具 | `app.sdk.network` |
| 浏览器自动化（Playwright 上下文管理与页面操作） | `app.sdk.browser` |
| 数据库备份、备份列表与校验 | `app.sdk.database` |
| 插件和模块管理 | `app.sdk.plugins` |
| 下载器、媒体服务器、通知、规则和存储服务 | `app.sdk.services` |
| 文本门面（`StringUtils` 文本与格式化能力） | `app.sdk.string` |
| StringUtils、加密、DOM、反射、OTP 等通用工具 | `app.sdk.utilities` |

示例：

```python
from app.sdk.config import settings
from app.sdk.events import Event, EventManager
from app.sdk.logging import logger
from app.sdk.utilities import StringUtils
```

需要浏览器自动化时，统一使用 `app.sdk.browser.launch_browser_context` 启动
浏览器上下文，不要自行实例化宿主的 Playwright 适配器：

```python
from app.sdk.browser import launch_browser_context

with launch_browser_context(cookies=..., browser_type="chromium") as ctx:
    page = ctx.pages[0]
```

以下既有公开入口仍可稳定使用：`app.schemas`、`app.schemas.types`、
`app.chain.*`、`app.plugins.*`、`app.modules.*`、`app.agent.*`、
`app.api.endpoints.plugin`、`app.scheduler`、`app.db.oper.*`。插件确需建立自有表时，
还可使用 `app.db` 公开的 `Base`、`DbOper`、四个事务装饰器以及建表所需的引擎对象。
使用具体能力前，应查看当前 V3 方法签名和对应专题文档，不要从目录名字推断合同。

`app.db.models.*` 是宿主 ORM 的内部表结构，不是插件数据访问合同。旧插件的导入目前
可能仍能解析，但新代码不得直接查询或修改这些 Model，也不得根据其字段布局实现业务
逻辑。数据库的具体边界见[数据库访问与 V3 事务规则](#73-数据库访问与-v3-事务规则)。

以下入口属于兼容桥接，新插件代码禁止使用：

- `app.sdk._legacy`：仅供存量 V2 插件的自动迁移桥接，新插件不得直接依赖。
- `app.core.*`、`app.helper.*`、`app.utils.*`：仅由宿主精确映射兼容层承接存量
  导入；新增或新发布的插件不得继续使用这些旧路径。

已发布插件中的 `app.core.*`、`app.helper.*`、`app.utils.*` 等旧导入，由精确映射
兼容层承接；`DEBUG=true` 时宿主会提示推荐迁移路径。完整说明见
[旧导入路径兼容与迁移](./V3_Plugin_Adaptation.md#2-旧导入路径兼容与迁移)。

## 7. 配置、数据和依赖

### 7.1 配置读写

配置由 `init_plugin()` 接收，保存时使用基类方法：

```python
def _save_config(self) -> bool:
    """保存插件当前配置。"""
    return self.update_config({
        "enabled": self._enabled,
        "message": self._message,
    })
```

不要直接修改宿主配置文件。V3 新建分身是“同一份源码、多个运行实例”：宿主会在
实例专属模块命名空间中重新执行源码，并把运行类名设置为实例 ID。需要定位自身插件
ID 时优先使用 `self.__class__.__name__`，不要在业务代码中硬编码原始类名。

### 7.2 结构化数据与文件

小型结构化数据使用插件数据接口：

```python
def save_runtime_state(self, state: dict) -> None:
    """保存可序列化的运行状态。"""
    self.save_data("runtime_state", state)


async def load_runtime_state(self) -> dict:
    """异步读取运行状态。"""
    return await self.async_get_data("runtime_state") or {}
```

文件写入插件独立数据目录：

```python
def write_report(self, content: str) -> None:
    """把报告写入当前插件的数据目录。"""
    report_file = self.get_data_path() / "report.txt"
    report_file.write_text(content, encoding="utf-8")
```

不要把运行数据写回插件源码目录；插件更新时源码目录可能被替换。

### 7.3 数据库访问与 V3 事务规则

先按数据责任选择入口，不要因为所有数据最终都落在同一个数据库里就直接操作宿主
ORM：

| 数据类型 | 应使用的入口 |
| --- | --- |
| 用户可编辑的插件设置 | `get_config()` / `update_config()` |
| 小型、可序列化的插件状态 | `save_data()` / `get_data()` / `del_data()` 及异步变体 |
| 报告、缓存文件、大对象 | `get_data_path()` |
| 宿主已有业务数据 | 对应的 `app.db.oper.<entity>`，或宿主已提供的 Chain / SDK |
| 需要索引、筛选或大量记录的插件自有数据 | 插件自有表 + `app.db` 公共事务装饰器 |

V3 已把宿主数据库事务收口到显式 Session、Unit of Work 和组合根。插件必须遵守以下
边界：

- 不导入或操作 `app.db.models.*` 宿主 Model；访问宿主数据使用对应 Oper 或更高层的
  Chain / SDK。
- 不导入 `SessionFactory`、`AsyncSessionFactory`、`ScopedSession` 或宿主内部会话
  模块。它们即使因兼容原因仍可导入，也不属于插件公开合同。
- 无显式 Session 的宿主 Oper 调用是保留给插件的兼容入口。一次调用拥有一次独立事务；
  不要假设连续多个 Oper 调用天然原子，也不要把一个 Oper 或 Session 保存在插件单例、
  后台线程或异步任务之间复用。
- 需要跨多个宿主写操作的原子业务流程时，优先调用宿主已有 Chain / SDK；缺少对应能力
  时应先在主仓提供明确的应用服务，不要由插件自行拼接宿主事务。
- `SystemConfig` 的宿主键必须使用 `SystemConfigKey`，插件自身配置则统一走基类方法；
  不要用原始字符串在宿主配置表中创建自定义键。
- `app.sdk.database` 只提供宿主管理的数据库备份、列表和校验能力，不是通用 SQL 或 ORM
  入口。

例如，只读宿主订阅数据时使用 Oper，不直接导入 `Subscribe` Model：

```python
from app.db.oper.subscribe import SubscribeOper


def get_subscribe(self, subscribe_id: int):
    """按订阅 ID 读取宿主订阅。"""
    return SubscribeOper().get(sid=subscribe_id)
```

只有 `save_data()` 无法满足索引、筛选或数据量要求时，才建立插件自有表。V3 自有表
使用 SQLAlchemy 2.0 的 `Mapped` / `mapped_column()` 声明；同步方法分别使用
`db_query` 和 `db_update` 管理查询会话与提交、回滚、释放：

```python
from typing import Optional

from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base, db_query, db_update


class MyPluginRecord(Base):
    """我的插件拥有的示例记录。"""

    __tablename__ = "plugin_myplugin_record"
    # V3 热重载和虚拟分身会重复执行模型声明，必须复用同一份表元数据。
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class MyPluginDatabaseMixin:
    """供插件主类复用的自有表建表与数据访问方法。"""

    @staticmethod
    def ensure_table() -> None:
        """仅创建本插件的数据表，不触发宿主全部元数据建表。"""
        from app.db import Engine

        MyPluginRecord.__table__.create(bind=Engine, checkfirst=True)

    @db_update
    def add_record(
        self,
        db: Optional[Session] = None,
        *,
        name: str,
    ) -> int:
        """新增记录，并由更新装饰器提交或回滚事务。"""
        assert db is not None
        record = MyPluginRecord(plugin_id=self.__class__.__name__, name=name)
        db.add(record)
        db.flush()
        return record.id

    @db_query
    def list_records(self, db: Optional[Session] = None) -> list[dict]:
        """在会话关闭前把记录转换为普通字典。"""
        assert db is not None
        records = db.execute(
            select(MyPluginRecord).where(
                MyPluginRecord.plugin_id == self.__class__.__name__
            )
        ).scalars().all()
        return [{"id": record.id, "name": record.name} for record in records]
```

`ensure_table()` 应在 `init_plugin()` 中按需调用，不能在模块导入期或类定义期连接数据库。
表名必须使用稳定且不会与宿主或其他插件冲突的插件前缀。`checkfirst=True` 只能创建缺失
表，不能升级已有列；自有表结构变化时，插件必须提供按版本执行、可重复运行的迁移，先
备份并验证数据，再更新插件记录的 schema 版本。不要把插件表迁移写入主仓 Alembic。
自有表不会自动获得基类存储的分身隔离能力；支持虚拟分身时，必须像示例一样保存并过滤
运行实例 ID。

异步数据库方法使用 `async_db_query` / `async_db_update` 和 `AsyncSession`，不得在事件
循环里调用同步数据库方法。查询返回前应完成 `list()`、标量提取或 DTO/字典转换，避免
会话释放后再触发 ORM 懒加载。

### 7.4 虚拟分身兼容

新分身不会复制插件目录，也不会改写 Python、JavaScript 或 CSS。配置、结构化数据、
数据目录、事件绑定、动态 API 和定时服务均按运行实例 ID 隔离；源插件更新后，引用它
的实例会一起重载。升级前已经生成的物理分身仍按旧目录继续加载，不要求迁移。

为了让插件可以安全创建虚拟分身：

- 配置和数据使用 `update_config()`、`get_config()`、`save_data()`、`get_data()`、
  `del_data()` 与 `get_data_path()`，不要显式传入写死的源插件 ID。
- 不要把可变状态放到进程级单例、宿主全局变量或源码目录；模块级状态虽然会按实例
  重新执行，插件自行导入的第三方全局单例仍然是共享的。
- 端口、外部账号、Webhook 名称、下载目录等排他资源需要由配置区分；宿主无法自动
  隔离插件控制范围之外的外部资源。
- 停止和重载必须释放线程、连接、文件句柄及监听端口，避免一个实例占用另一个实例
  需要的资源。

因此“共享源码”不等于“共享状态”。如果插件主动绕过基类存储，或依赖不可分配的
进程级排他资源，应明确说明不适合创建多个实例。

### 7.5 第三方依赖

插件有额外 Python 依赖时，在插件目录增加 `pyproject.toml`：

```toml
[project]
name = "moviepilot-plugin-myplugin"
dynamic = ["version"]
requires-python = ">=3.12"
dependencies = [
    "example-package>=1",
]
```

`dynamic = ["version"]` 只表示依赖清单不重复维护插件版本；宿主读取的是静态
`project.dependencies`，不会从清单解析插件实际版本。插件不提交 `uv.lock`，也不要在
插件代码中直接执行 pip 或 uv。V1/V2 历史实现继续使用 `requirements.txt`。

依赖安装到宿主共享环境，因此必须遵守：

- 只声明插件真正需要、宿主尚未提供的依赖。
- 不要要求降级或覆盖 MoviePilot 核心依赖。
- 尽量设置合理版本范围，避免无上限升级破坏宿主。
- 可选能力尽量延迟导入，并在缺少依赖时给出明确错误。

宿主会保护核心依赖图；存在降级或不兼容要求时，插件安装会被拒绝。

### 7.6 异步 HTTP 客户端

V3 的 `app.sdk.network.AsyncRequestUtils` 使用 HTTPX2。默认请求返回 `httpx2.Response`，传入
自管客户端时只使用 `httpx2.AsyncClient`；直接依赖响应或异常类型的插件代码应导入 `httpx2`。

网络、代理、TLS 或超时错误默认由 `AsyncRequestUtils` 拦截并返回 `None`。需要区分失败原因时传入
`raise_exception=True`，并捕获 `httpx2.RequestError` 或其具体子类：

```python
import httpx2

from app.sdk.logging import logger
from app.sdk.network import AsyncRequestUtils


try:
    response = await AsyncRequestUtils().get_res(url, raise_exception=True)
except httpx2.RequestError as error:
    logger.warning(f"请求失败：{error}")
    return None
```

HTTP 4xx/5xx 响应不会因为 `raise_exception=True` 自动抛出。插件应按业务检查 `status_code`，或调用
`response.raise_for_status()` 并处理 `httpx2.HTTPStatusError`。`httpx.RequestError` 不能捕获
HTTPX2 异常。

插件直接调用的第三方 SDK 仍使用该 SDK 声明的 HTTP 客户端版本，不需要为此替换其内部依赖。
不要调用 `httpx2.alias_httpx()` 全局改写 `httpx`，同一进程内的主程序、其它插件和第三方 SDK
共享导入状态，全局替换会越过插件边界。

## 8. 页面和仪表板

### 8.1 Vuetify JSON 模式

默认渲染模式是 `vuetify`，适合配置表单、详情页、轻量数据表和仪表板：

- `get_form()` 返回“页面 JSON + 默认配置模型”。
- `get_page()` 返回详情页面 JSON。
- `get_dashboard()` 返回“列配置 + 全局配置 + 页面 JSON”。
- `props.model` 对应表单模型字段。
- `props.show` 控制条件显示。
- 配置页支持 `{{ ... }}` 表达式和 `onxxx` 事件。

复杂组件写法优先参考官方插件中的现有 V3 实现，以及
[仪表板 FAQ](./faq/08-render-dashboard.md)。

### 8.2 Vue 联邦模式

交互复杂、需要独立状态管理或侧栏全页时，使用 Vue 联邦远程组件：

```python
@staticmethod
def get_render_mode() -> tuple[str, str]:
    """声明 Vue 联邦构建产物目录。"""
    return "vue", "dist/assets"
```

Vue 模式下，前端构建产物放入插件目录，由后端暴露静态资源。需要侧栏入口时实现
`get_sidebar_nav()`。完整暴露名、路由、权限和多入口约束见：

- [侧栏入口 FAQ](./faq/17-register-plugin-sidebar-nav.md)
- [MoviePilot-Frontend V3 模块联邦指南](https://github.com/jxxghp/MoviePilot-Frontend/blob/v3/docs/module-federation-guide.md)

虚拟分身复用源插件的同一份 `remoteEntry.js`。宿主会向配置页、数据页、仪表盘、
侧栏全页和登录组件传入当前实例的 `pluginId`、源身份 `sourcePluginId`，以及实例作用域
的 `api`。联邦组件应优先使用这些 props；不要只读取全局 `window.MoviePilotAPI`，也不要
自行根据源插件 ID 创建另一套 HTTP 客户端，否则请求会绕过实例 API 命名空间。

### 8.3 联邦组件 CSS 不得污染主程序

> **强制要求：联邦插件不得打包或发布 Vuetify、MDI 的全局基础样式。**

联邦组件与主程序运行在同一个 `document`。远程 CSS 会由联邦运行时追加到主页面
`<head>`，因此 `.v-card`、`.rounded-*`、`.elevation-*`、`html`、`body`、`:root` 等
全局规则会同时修改主程序界面，而且离开插件页面后仍可能继续生效。Vue 的
`<style scoped>` 只能约束插件自己编写的组件样式，不能修复被依赖包打入产物的全局 CSS。

插件前端构建必须满足以下约束：

1. 不要在远程组件依赖图中导入 `vuetify/styles` 或 MDI 全量样式。
2. 共享 `vuetify/styles` 时必须设置 `generate: false`，复用主程序已有样式。
3. PostCSS 必须移除来自 `node_modules/vuetify` 和 `node_modules/@mdi` 的 CSS。
4. 不得提交或发布 `__federation_shared_vuetify/styles-*.css`。
5. 可以保留 `.plugin-root .v-btn` 或 Vue `scoped`/`:deep()` 生成的插件内局部覆盖；不得直接编写 `.v-btn { ... }`。
6. 构建后必须执行 `python .github/scripts/check_federation_css.py`。PR、pre-push 和 Release 都会执行同一门禁。
7. 联邦插件在对应的 `package*.json` 中必须设置 `release: true`，确保正式发布工作流会打包其前端产物。

推荐配置：

```javascript
federation({
  name: 'MyPlugin',
  filename: 'remoteEntry.js',
  exposes: {
    './Page': './src/components/Page.vue',
    './Config': './src/components/Config.vue',
  },
  shared: {
    vue: { requiredVersion: false, generate: false, singleton: true },
    vuetify: { requiredVersion: false, generate: false, singleton: true },
    'vuetify/styles': { requiredVersion: false, generate: false, singleton: true },
  },
})

// vite.config.js
css: {
  postcss: {
    plugins: [{
      postcssPlugin: 'vuetify-filter',
      Root(root) {
        const sourcePath = root.source?.input?.file?.replaceAll('\\', '/') || ''
        if (sourcePath.includes('/node_modules/vuetify/') ||
            sourcePath.includes('/node_modules/@mdi/')) {
          root.nodes = []
          return
        }
        root.walkRules(rule => {
          if (rule.selector &&
              (rule.selector.includes('.v-') || rule.selector.includes('.mdi-'))) {
            rule.remove()
          }
        })
      },
    }],
  },
}
```

不要仅以“`remoteEntry.js` 当前没有引用”为理由保留整包 Vuetify CSS。发布流程会打包插件目录，后续构建图变化也可能使这类文件重新进入加载链路；门禁会直接拒绝该产物。

## 9. 事件、API 和后台能力

### 9.1 远程命令与事件

远程命令通常注册为 `EventType.PluginAction`，再根据 `action` 路由到当前插件：

```python
from app.schemas.types import EventType
from app.sdk.events import Event, eventmanager


@staticmethod
def get_command() -> list[dict]:
    """注册插件远程命令。"""
    return [
        {
            "cmd": "/my_plugin_run",
            "event": EventType.PluginAction,
            "desc": "执行我的插件",
            "category": "插件命令",
            "data": {"action": "my_plugin_run"},
        }
    ]


@eventmanager.register(EventType.PluginAction)
def run_command(self, event: Event) -> None:
    """只处理属于当前插件的动作。"""
    event_data = event.event_data or {}
    if event_data.get("action") != "my_plugin_run":
        return
    # 在这里执行实际业务逻辑。
```

更多消息来源、权限和回复方式见
[远程命令 FAQ](./faq/02-remote-command-handler.md) 与
[消息交互 FAQ](./faq/14-message-interaction.md)。

### 9.2 插件 API

`get_api()` 返回 FastAPI 路由声明，最终路径为：

```text
/api/v1/plugin/<PluginID>/<path>
```

```python
def get_api(self) -> list[dict]:
    """注册插件历史查询接口。"""
    return [
        {
            "path": "/history",
            "endpoint": self.get_history,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "查询插件历史",
        }
    ]
```

- 插件页面调用通常使用 `bear`。
- 外部系统调用可使用 `apikey`。
- 除非确实是公开接口，否则不要设置匿名访问。
- 文件、图片、SSE、HTML 等原生响应与普通 JSON 响应的处理方式不同。

返回模型、错误表达、Python 客户端和 Vue 客户端的完整规则见
[插件 API 专题](./V3_API_Response_Adaptation.md)；不要在多个文档中复制一套响应合同。

### 9.3 定时服务

`get_service()` 适合周期任务和定时批处理：

```python
from apscheduler.triggers.cron import CronTrigger


def get_service(self) -> list[dict]:
    """插件启用时注册周期刷新任务。"""
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

服务 ID 必须稳定且唯一。插件停用时，还要清理自行创建、不由宿主服务调度器管理的
线程、异步任务、文件句柄或网络客户端。

### 9.4 通知、工作流和 Agent

- 使用基类 `post_message()` 或 `app.sdk.services.NotificationHelper` 发送通知。
- 使用 `get_actions()` 注册工作流动作。
- 使用 `get_agent_tools()` 返回继承 `MoviePilotTool` 的工具类。
- 需要扩展认证、存储、索引站点等高级能力时，先查看对应 FAQ，不要复制宿主实现。

相关专题：

- [通知渠道](./faq/01-extend-notification-channel.md)
- [工作流动作](./faq/13-integrate-workflow.md)
- [Agent 工具](./faq/16-register-agent-tools.md)
- [统一缓存](./faq/15-use-system-cache.md)
- [媒体数据源](./faq/19-register-media-source.md)

## 10. V3 业务合同

### 10.1 媒体身份

通用媒体身份必须同时包含：

```text
media_source + media_id
```

不要在通用链路中只保存 `tmdbid`、`doubanid` 或裸 `media_id`。内置来源使用
`MediaSource`，插件来源使用稳定的扩展标识。身份比较、缓存键、历史查询和数据
迁移必须同时处理来源和 ID。

### 10.2 链职责

识别、搜索、推荐、刮削和来源能力已经按职责拆分。尤其不要重新创建已经删除的
`MusicChain` 兼容包装。涉及媒体身份、音乐链、历史数据或旧导入迁移时，必须继续
阅读 [V2 插件迁移到 V3](./V3_Plugin_Adaptation.md)。

## 11. 调试和测试

### 11.1 最小检查

插件仓依赖 MoviePilot 宿主环境。假设两个仓库位于同一级目录：

```bash
../MoviePilot/.venv/bin/python -m compileall plugins.v3/myplugin
../MoviePilot/.venv/bin/python .github/scripts/check_plugin_versions.py \
  package.json package.v2.json package.v3.json
git diff --check
```

版本检查会确认 `package.v3.json` 与插件类的 `plugin_version` 一致。

### 11.2 插件测试

测试放在 `tests/v3/<plugin_id>/`，并使用宿主虚拟环境运行：

```bash
../MoviePilot/.venv/bin/python -m pytest tests/v3/myplugin
```

提交前建议运行当前 V3 运行环境的默认回归；CI 工具、V3 专用实现和仍兼容 V3 的
V2 实现会在独立进程中运行，避免同名模块互相污染：

```bash
../MoviePilot/.venv/bin/python tests/run.py
```

插件测试使用与生产一致的 `app.plugins.<plugin_id>` 路径导入源码。不要在测试中把插件
目录作为顶层包路径使用，否则同一插件可能以两个模块名加载，重复执行注册和初始化副作用。

测试应覆盖插件最关键的纯逻辑、配置迁移和安全边界。外部网络、真实下载器、媒体
服务器或第三方账号使用 mock 或明确的集成测试，不要让普通单测依赖公网状态。

### 11.3 真实加载检查

至少在 V3 宿主中确认：

1. 插件市场能够发现并安装插件。
2. 插件启动、禁用、重载都不残留后台资源。
3. `DEBUG=true` 时没有可迁移的旧导入警告。
4. API、服务、命令和页面只注册一次。
5. Vue 插件执行过 `yarn typecheck` 和 `yarn build`，并更新构建产物。

插件访问数据库时还要覆盖成功提交、异常回滚、同步或异步会话释放，以及重复初始化时
的自有表迁移；普通测试不得连接用户的真实数据库。

## 12. 发布插件

发布前同步三处信息：

1. 插件类中的 `plugin_version`。
2. `package.v3.json` 中的 `version`。
3. `history` 顶部的当前版本记录。

常用元数据：

- `system_version`：插件要求的 MoviePilot 版本，例如 `">=3.0.0"`。
- `release: true`：使用 GitHub Release 压缩包分发。
- `level`：插件市场可见权限级别。
- `icon`、`author`、`description`：应与插件类元数据保持一致。

官方插件仓 PR 和 Release 的完整门禁、Tag、压缩包和索引规则见
[仓库与发布指南](./Repository_Guide.md)。

## 13. 发布前清单

- [ ] 新插件位于 `plugins.v3/<plugin_id_lower>/`。
- [ ] 主类位于 `__init__.py`，目录名与类名小写一致。
- [ ] `package.v3.json` 元数据完整。
- [ ] `plugin_version`、索引 `version` 和最新 `history` 一致。
- [ ] 新增类和方法具有说明职责的注释。
- [ ] 使用稳定 SDK，没有新增不必要的宿主内部路径依赖。
- [ ] 宿主数据只经 Oper、Chain 或稳定 SDK 访问；事务装饰器只用于插件自有表。
- [ ] 配置初始化可重复执行，停用和重载会释放后台资源。
- [ ] 插件运行数据不写入源码目录。
- [ ] 普通 JSON 与原生响应遵守 API 专题说明。
- [ ] V3 媒体身份使用完整的 `media_source` 与 `media_id`。
- [ ] Python 编译、版本门禁、相关单测和 `git diff --check` 已通过。
- [ ] Vue 远程组件已完成类型检查、构建和真实页面验证。

## 14. 遇到问题时看哪里

| 问题 | 文档 |
| --- | --- |
| 插件目录、索引、版本和 Release | [仓库与发布指南](./Repository_Guide.md) |
| V2 插件迁移、旧导入、数据库事务和媒体身份 | [V2 插件迁移到 V3](./V3_Plugin_Adaptation.md) |
| API 返回、调用和 Vue 客户端 | [插件 API 专题](./V3_API_Response_Adaptation.md) |
| 消息、服务、缓存、存储、Agent 等功能 | [常见问题](./FAQ.md) |
| Vue 联邦组件 | [前端 V3 模块联邦指南](https://github.com/jxxghp/MoviePilot-Frontend/blob/v3/docs/module-federation-guide.md) |
| 仍然维护 V2 实现 | [V2 历史开发指南](./V2_Plugin_Development.md) |

如果文档与运行时行为不一致，以 MoviePilot V3 当前宿主代码和测试为准，并在修复
实现时同步更新这里的主指南及对应专题，避免再次形成多个互相冲突的入口。
