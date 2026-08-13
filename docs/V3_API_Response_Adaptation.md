# MoviePilot V3 插件 API 响应适配指南

本文面向以下插件作者：

- 通过 `get_api()` 暴露普通 JSON API；
- 通过 Python HTTP 客户端调用 MoviePilot 宿主 API；
- 使用 Vue 模块联邦远程组件，并通过宿主注入的 `api` 发起请求；
- 仍在使用 `/api/v2`、裸 JSON 响应、`message_i18n` 或把业务数据放在 `message` 中。

不提供 HTTP API、也不调用宿主 HTTP API 的纯后台插件，不需要因为本次响应合同
单独建立 V3 实现。媒体身份、链职责和插件数据迁移仍请同时参阅
[V3 插件适配指南](./V3_Plugin_Adaptation.md)。

## 1. 必须遵守的合同

V3 的普通 JSON API 只允许三个顶层字段：

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

不要增加 `message_i18n`、`error`、`result` 等额外顶层字段。业务对象、分页信息、
预览结果和结构化错误详情都应放在 `data` 中，不能借用 `message` 传输。

`/api/v2` 套壳入口已经移除，HTTP 调用统一改为 `/api/v1`。这不等于删除
`plugins.v2/`：插件目录版本仍按 V3 兼容规则保留，只有依赖新合同的插件才需要
建立 `plugins.v3/` 专用实现。

## 2. 哪些响应需要套 envelope

| 调用或端点类型 | V3 行为 | 插件需要做什么 |
| --- | --- | --- |
| 宿主普通 JSON REST | 固定三段式 envelope | 从 `data` 读取业务对象 |
| `get_api()` 普通 JSON endpoint | 宿主自动包装 | endpoint 返回业务模型，不要手工套字典 |
| endpoint 返回 `schemas.Response[T]` | 保留现有 envelope，不重复包装 | 用于显式业务失败或成功文案 |
| Vue 远程组件注入的 `api` | 返回完整 envelope，并统一处理 Toast | 检查 `success`，从 `data` 读取业务对象 |
| SSE、文件、图片、HTML、204 | 保持原生协议 | 显式声明原生响应和 OpenAPI content |
| OAuth2、OpenAI、Anthropic、MCP JSON-RPC | 保持标准协议原生响应 | 不按三段式解析 |

不要通过 `response_model=None` 把普通 JSON 接口伪装成“原生协议”来保留旧响应。

## 3. 适配插件后端 API

### 3.1 每个普通 JSON endpoint 都声明业务数据模型

`get_api()` 注册的路由也会进入宿主统一路由类。推荐让 endpoint 直接返回明确的
Pydantic 业务模型，并在路由中声明同一个 `response_model`：

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
  "success": true,
  "message": "",
  "data": {
    "enabled": true,
    "pending_count": 2
  }
}
```

不要只写 `dict`、`list[dict]` 或 `Any` 作为长期输出模型。每个端点的 `data`
结构都应在 `/docs` 的 OpenAPI 中可查。

### 3.2 需要表达业务失败时返回 `schemas.Response[T]`

只有 endpoint 需要主动设置 `success` 或 `message` 时，才返回宿主响应模型：

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

不要返回手写 envelope：

```python
# 错误：普通 dict 会被宿主再次放入 data，形成双层套壳。
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

通过 `RequestUtils`、`requests` 或 `httpx` 调用 MoviePilot 时，需要同时处理 HTTP
错误与 envelope 业务失败：

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

调用 SSE、文件下载或标准协议端点时不要使用上述 JSON 解包函数，应继续按其
`Content-Type` 和原生协议消费。

## 5. 适配 Vue 远程组件

### 5.1 使用宿主注入客户端

远程组件应使用 `props.api`，无属性注入场景可使用
`window.MoviePilotAPI`。不要自行创建一个缺少认证、语言和统一反馈处理的 Axios
实例。

注入客户端的 `baseURL` 已经是 `/api/v1/`，因此传相对路径：

```javascript
const response = await props.api.get('plugin/MyPlugin/status')
if (!response.success) return

status.value = response.data
```

不要再读 Axios 外层响应，也不要重复写版本前缀：

```javascript
// 错误：注入客户端已经直接返回 envelope，不存在 response.data.success。
const response = await props.api.get('plugin/MyPlugin/status')
if (response.data.success) status.value = response.data.data

// 错误：baseURL 已含 /api/v1/。
await props.api.get('/api/v1/plugin/MyPlugin/status')
```

### 5.2 统一 Toast 与自定义反馈

默认模式下，宿主请求层会：

- 对 `success=false`、HTTP 错误和网络错误显示一次错误 Toast；
- 不为每个成功请求显示 Toast；
- 保留完整 envelope 给插件远程组件。

因此插件只需停止当前流程，不要再为同一错误弹第二次 Toast：

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

远程组件测试中的 `api` mock 应返回最终 envelope，而不是 AxiosResponse：

```javascript
const api = {
  get: vi.fn().mockResolvedValue({
    success: true,
    message: '',
    data: { enabled: true, pending_count: 2 },
  }),
}
```

失败用例应覆盖 `success=false` 和 rejected HTTP/network error 两条路径。

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

只有真实协议端点可以使用 `response_model=None`。普通 JSON endpoint 必须声明
具体业务模型并使用统一 envelope。

## 8. 发布前检查清单

- HTTP 路径已从 `/api/v2` 改为 `/api/v1`。
- 所有普通 JSON endpoint 都声明了具体 `response_model`。
- endpoint 直接返回业务模型，或返回参数化的 `schemas.Response[T]`。
- 没有手写 envelope 字典、双层 `data` 或额外顶层字段。
- 查询空结果不会误用 `success=false`。
- Python HTTP 调用同时检查 HTTP 状态与 `success`，业务数据只从 `data` 读取。
- Vue 远程组件使用注入的 `api`，读取 `response.success/message/data`，不读取
  `response.data.data`。
- 默认错误不重复弹 Toast；轮询和批量请求根据需要使用 `feedback: 'silent'`。
- 多语言请求头仍由宿主客户端发送，插件没有恢复顶层 `message_i18n`。
- SSE、文件、图片、HTML 和标准协议端点保留原生格式并显式声明 OpenAPI。
- 后端测试覆盖成功对象、数组、标量、`null`、业务失败和空查询。
- 远程组件测试 mock 的是最终 envelope，不是 AxiosResponse。

如果插件仅因本合同而与 V2 实现不兼容，应按
[V3 插件适配指南](./V3_Plugin_Adaptation.md)建立 `plugins.v3/` 副本、升级主版本、
声明 `system_version: ">=3.0.0"`，并保持原 V1/V2 实现不变。
