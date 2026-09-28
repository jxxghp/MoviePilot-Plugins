# MoviePilot V3 插件 API 响应适配指南

本文是 API 专题，不是插件开发总入口。第一次开发 V3 插件，请先阅读
[MoviePilot 插件开发指南（V3）](./Plugin_Development.md)。

本文面向以下插件作者：

- 通过 `get_api()` 暴露普通 JSON API；
- 通过 Python HTTP 客户端调用 MoviePilot 宿主 API；
- 使用 Vue 模块联邦远程组件，并通过宿主注入的 `api` 发起请求；
- 仍在使用 `/api/v2`、旧响应字段或把业务数据放在 `message` 中。

不提供 HTTP API、也不调用宿主 HTTP API 的纯后台插件，不需要因为本次响应合同
单独建立 V3 实现。媒体身份、链职责和插件数据迁移仍请同时参阅
[V2 插件迁移到 V3](./V3_Plugin_Adaptation.md)。

## 1. 宿主 API 与插件 API 的边界

MoviePilot 宿主自身的普通 JSON API 固定使用三个顶层字段：

```json
{
  "success": true,
  "message": "",
  "data": {}
}
```

三个字段职责固定：

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `success` | `boolean` | 表示请求或业务操作是否成功 |
| `message` | `string` | 给用户展示的成功或失败原因；没有文案时为空字符串 |
| `data` | 端点专用模型或 `null` | 唯一允许随接口变化的业务数据区域 |

插件通过 `get_api()` 动态注册的路由不经过宿主统一响应路由。插件可以直接返回
业务模型、标准协议响应，也可以显式返回上述 envelope；宿主不会替插件增加或移除
顶层字段。选择 envelope 的插件不要增加 `message_i18n`、`error`、`result` 等额外
顶层字段，业务对象应放在 `data` 中，不能借用 `message` 传输。

这条边界也适用于宿主内部架构迁移：插件 API 只依赖 `get_api()` 的注册字段、路由
合同和自身返回结构，不依赖宿主内部的 API、Application、Runtime 或 Adapter 文件
位置。宿主会通过精确兼容映射保留已登记的旧导入；插件不需要为了宿主把
`PluginManager` 拆到多个模块而复制导出或改写动态路由。

`/api/v2` 套壳入口已经移除，HTTP 调用统一改为 `/api/v1`。这不等于删除
`plugins.v2/`：插件目录版本仍按 V3 兼容规则保留，只有依赖新合同的插件才需要
建立 `plugins.v3/` 专用实现。

## 2. 哪些响应需要套 envelope

| 调用或端点类型 | V3 行为 | 插件需要做什么 |
| --- | --- | --- |
| 宿主普通 JSON REST | 固定三段式 envelope | 从 `data` 读取业务对象 |
| `get_api()` 普通 JSON endpoint | 保留 endpoint 自己的响应 | 明确选择裸业务模型或 envelope，并声明匹配的 `response_model` |
| endpoint 返回 `schemas.Response[T]` | 输出显式 envelope | 适用于接入宿主普通数据页面或统一反馈的接口 |
| Vue 远程组件注入的 `api` | 非宿主 `Response` payload 原样返回；标准 envelope 仍按统一错误语义处理 | 按插件自己的 API 合同读取裸数据或 envelope |
| SSE、文件、图片、HTML、204 | 保持原生协议 | 显式声明原生响应和 OpenAPI content |
| OAuth2、OpenAI、Anthropic、MCP JSON-RPC | 保持标准协议原生响应 | 不按三段式解析 |

不要通过 `response_model=None` 隐藏普通 JSON 接口的真实结构。

## 3. 适配插件后端 API

### 3.1 直接返回业务模型

插件自有客户端可以约定直接读取业务对象。此时 endpoint 返回明确的 Pydantic
业务模型，并在路由中声明同一个 `response_model`：

```python
from typing import Any, Dict, List

from pydantic import BaseModel


class PluginStatusData(BaseModel):
    """插件状态接口的业务数据。"""

    enabled: bool
    pending_count: int


def get_status(self) -> PluginStatusData:
    """返回当前插件状态。"""
    return PluginStatusData(
        enabled=self.get_state(),
        pending_count=len(self._pending_items),
    )


def get_api(self) -> List[Dict[str, Any]]:
    """注册插件普通 JSON API。"""
    return [
        {
            "path": "/status",
            "endpoint": self.get_status,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "查询插件状态",
            "response_model": PluginStatusData,
        }
    ]
```

HTTP 实际响应为：

```json
{
  "enabled": true,
  "pending_count": 2
}
```

不要只写 `dict`、`list[dict]` 或 `Any` 作为长期输出模型。每个端点的完整响应
结构都应在 `/docs` 的 OpenAPI 中可查。

### 3.2 显式选择统一 envelope

需要接入宿主普通数据客户端、使用统一业务反馈，或保持既有三段式响应时，endpoint
应显式返回宿主响应模型：

```python
from app import schemas


def save_config(self, payload: PluginConfigData) -> schemas.Response[PluginConfigData]:
    """保存配置，并返回保存后的业务对象。"""
    if not payload.target:
        return schemas.Response(success=False, message="目标不能为空")

    self.update_config(payload.model_dump())
    return schemas.Response(
        success=True,
        message="保存成功",
        data=payload,
    )
```

对应路由应声明：

```python
{
    "path": "/config",
    "endpoint": self.save_config,
    "methods": ["POST"],
    "auth": "bear",
    "response_model": schemas.Response[PluginConfigData],
}
```

选择统一 envelope 时不要返回未声明模型的手写字典：

```python
# 不推荐：缺少响应模型校验，字段也容易随实现漂移。
return {
    "success": True,
    "message": "",
    "data": {"enabled": True},
}
```

### 3.3 “未命中”不等于接口失败

查询已正常完成，但没有找到记录时，通常仍应返回 `success=true`，由 `data`
表达空结果：

```python
return schemas.Response(
    success=True,
    data={"exists": False, "item": None},
)
```

只有请求无法完成或业务操作被拒绝时才使用 `success=false`。否则宿主前端会把
正常的空查询当作失败并显示错误 Toast。

### 3.4 HTTP 状态码与业务失败

- 参数校验、未认证、无权限、资源不存在和服务器错误，应使用合适的 HTTP
  状态码或抛出 `HTTPException`；宿主会生成统一错误 envelope。
- HTTP 200 下的 `success=false` 只用于调用已完成但业务操作被拒绝的场景。
- 不要把异常堆栈、Cookie、令牌或内部路径写入 `message`。

## 4. 适配 Python HTTP 调用

通过 `RequestUtils`、`requests` 或 `httpx` 调用 MoviePilot 宿主普通 JSON API 时，
需要同时处理 HTTP 错误与 envelope 业务失败：

```python
from typing import Any


def read_api_data(response) -> Any:
    """校验 MoviePilot 普通 JSON 响应并返回业务数据。"""
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or set(payload) != {
        "success",
        "message",
        "data",
    }:
        raise RuntimeError("MoviePilot API 返回了无效响应结构")
    if not payload["success"]:
        raise RuntimeError(payload["message"] or "MoviePilot API 调用失败")
    return payload["data"]
```

迁移时重点搜索并修改：

```text
/api/v2
response.json()["业务字段"]
response.json()["message_i18n"]
把 response.json() 直接当列表或业务对象
```

调用插件 API 时应按插件声明的响应模型解析；只有插件显式选择
`schemas.Response[T]` 时才使用上述解包方式。调用 SSE、文件下载或标准协议端点
时继续按其 `Content-Type` 和原生协议消费。

## 5. 适配 Vue 远程组件

### 5.1 使用宿主注入客户端

远程组件应使用 `props.api`，无属性注入场景可使用
`window.MoviePilotAPI`。不要自行创建一个缺少认证、语言和统一反馈处理的 Axios
实例。

注入客户端的 `baseURL` 已经是 `/api/v1/`，因此传相对路径：

```javascript
const response = await props.api.get('plugin/MyPlugin/status')
status.value = response
```

宿主公共 `pluginApi` 会先判断响应是否是严格的三字段 `Response` envelope：

- 是 envelope：继续按 `success` 和 `message` 执行统一业务反馈，并把完整 envelope
  交给插件远程组件；
- 不是 envelope：不猜测字段、不补 `success/message/data`，直接把后端 payload
  交给插件调用方；文件、流、HTML、标准协议和插件自定义 JSON 均按自身合同消费。

因此，插件可以在不修改宿主公共组件的前提下自由选择裸业务模型或自定义结构；只有
明确选择宿主 `Response[T]` 时，才应依赖统一 envelope 的 `success`、`message` 和
`data` 字段。

如果插件 endpoint 显式返回 `schemas.Response[PluginStatusData]`，则按 envelope
读取：

```javascript
const response = await props.api.get('plugin/MyPlugin/status')
if (!response.success) return
status.value = response.data
```

不要再读 Axios 外层响应，也不要重复写版本前缀：

```javascript
// 错误：把最终 payload 当成 AxiosResponse，再多读取一层 data。
const payload = await props.api.get('plugin/MyPlugin/status')
status.value = payload.data.data

// 错误：baseURL 已含 /api/v1/。
await props.api.get('/api/v1/plugin/MyPlugin/status')
```

### 5.2 统一 Toast 与自定义反馈

当插件返回合法 envelope 时，默认模式下宿主请求层会：

- 对 `success=false`、HTTP 错误和网络错误显示一次错误 Toast；
- 不为每个成功请求显示 Toast；
- 保留完整 envelope 给插件远程组件。

因此选择 envelope 的插件只需停止当前流程，不要再为同一错误弹第二次 Toast：

```javascript
try {
  const response = await props.api.post('plugin/MyPlugin/config', form.value)
  if (!response.success) return
  form.value = response.data
} catch {
  // HTTP 和网络错误已由宿主统一提示；这里只恢复组件状态。
} finally {
  saving.value = false
}
```

轮询、批量子请求或组件准备自己展示上下文错误时，使用 `feedback: 'silent'`；
明确需要展示后端成功 `message` 时使用 `feedback: 'all'`：

```javascript
await props.api.get('plugin/MyPlugin/progress', {
  feedback: 'silent',
})

await props.api.post('plugin/MyPlugin/config', form.value, {
  feedback: 'all',
})
```

### 5.3 Mock 最终运行时合同

远程组件测试中的 `api` mock 应返回 endpoint 的最终 payload，而不是
AxiosResponse。选择 envelope 的插件可使用：

```javascript
const api = {
  get: vi.fn().mockResolvedValue({
    success: true,
    message: '',
    data: { enabled: true, pending_count: 2 },
  }),
}
```

裸数据插件应直接 mock 对应业务模型。选择 envelope 的插件，失败用例应覆盖
`success=false` 和 rejected HTTP/network error 两条路径。

## 6. 多语言约束

宿主注入的客户端会自动发送 `X-MoviePilot-Locale` 和 `Accept-Language`。使用
`schemas.Response` 时，宿主会按当前请求语言处理已存在于宿主语言表中的
`message`；没有对应翻译的插件自有文案会保留原文。

插件专用界面文案和插件自定义错误文案仍由插件自己的语言资源负责。不要为了
兼容旧版在顶层增加 `message_i18n`，严格客户端会把额外顶层字段视为协议错误。
如果 `data` 内确实包含业务所需的多语言字段，可以继续保留，但它们属于端点
专用数据模型。

## 7. 原生响应端点

SSE、文件、图片、HTML 和 204 等端点必须显式声明为原生响应，并在 OpenAPI 中
写明 2xx content。下面以 SSE 为例：

```python
from starlette.responses import StreamingResponse


{
    "path": "/events",
    "endpoint": self.stream_events,
    "methods": ["GET"],
    "auth": "bear",
    "response_model": None,
    "response_class": StreamingResponse,
    "responses": {
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            }
        }
    },
}
```

只有真实协议端点可以使用 `response_model=None`。普通 JSON endpoint 应声明与
实际输出一致的具体业务模型；是否使用统一 envelope 由插件决定。

## 8. 发布前检查清单

- HTTP 路径已从 `/api/v2` 改为 `/api/v1`。
- 所有普通 JSON endpoint 都声明了与实际输出一致的具体 `response_model`。
- endpoint 已明确选择直接业务模型或参数化的 `schemas.Response[T]`。
- 选择 envelope 的接口没有手写未校验字典、双层 `data` 或额外顶层字段。
- 查询空结果不会误用 `success=false`。
- Python HTTP 调用按目标接口合同解析；宿主普通 JSON API 同时检查 HTTP 状态与
  `success`，业务数据只从 `data` 读取。
- Vue 远程组件使用注入的 `api`，直接读取最终 payload；envelope 接口读取
  `response.success/message/data`，裸数据接口读取业务模型本身。
- 默认错误不重复弹 Toast；轮询和批量请求根据需要使用 `feedback: 'silent'`。
- 多语言请求头仍由宿主客户端发送，插件没有恢复顶层 `message_i18n`。
- SSE、文件、图片、HTML 和标准协议端点保留原生格式并显式声明 OpenAPI。
- 后端测试覆盖成功对象、数组、标量、`null`、业务失败和空查询。
- 远程组件测试 mock 的是最终 payload（裸数据或 envelope），不是 AxiosResponse。

如果插件仅因本合同而与 V2 实现不兼容，应按
[V2 插件迁移到 V3](./V3_Plugin_Adaptation.md)建立 `plugins.v3/` 副本、升级主版本、
声明 `system_version: ">=3.0.0"`，并保持原 V1/V2 实现不变。
