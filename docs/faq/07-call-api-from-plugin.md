# 如何在插件中调用API接口？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 `v1.8.4+` 版本）**
- 在插件的数据页面支持`GET/POST`API接口调用，可调用插件自身、主程序或其它插件的API。
- 在`get_page`中定义好元素的事件，以及相应的API参数，具体可参考插件`豆瓣想看`：
```json
{
  "component": "VDialogCloseBtn", // 触发事件的元素
  "events": {
    "click": { // 点击事件
      "api": "plugin/DoubanSync/delete_history", // API的相对路径
      "method": "get", // GET/POST
      "params": {
        // API上送参数
        "media_source": "douban",
        "media_id": "1295644"
      }
    }
  }
}
```
- 每次API调用完成后，均会自动刷新一次插件数据页。
- V3 宿主普通 JSON API 返回 `{ "success", "message", "data" }` 统一结构；插件
  `get_api()` 的 endpoint 自行决定响应结构，宿主不会隐式包装。Vue 远程组件通过
  宿主传入的 `api` 或 `window.MoviePilotAPI` 调用时会得到 endpoint 的最终 payload：
  裸数据接口直接读取业务对象，显式 envelope 接口从 `data` 读取。
- 注入客户端的 `baseURL` 已经是 `/api/v1/`，Vue 组件使用
  `plugin/MyPlugin/path` 相对路径，不要再次拼接 `/api/v1/`。默认失败 Toast 已由
  宿主统一处理；轮询或自行展示上下文错误时使用 `feedback: 'silent'`，避免重复
  弹窗。
- Python HTTP 客户端要先检查 HTTP 状态，再检查顶层 `success`；不要把
  `response.json()` 直接当作列表或业务对象。原 `/api/v2` 路径统一迁移到
  `/api/v1`。
- 完整的后端模型、Python 解包、Vue 错误处理、多语言和原生响应示例见
  [V3 插件 API 响应适配指南](../V3_API_Response_Adaptation.md)。
- 媒体相关通用接口必须成对传递 `media_source` 与 `media_id`；明确单数据源的插件
  自有 API 可以继续按该来源原生合同设计参数。完整边界见
  [V2 插件迁移到 V3](../V3_Plugin_Adaptation.md)。
