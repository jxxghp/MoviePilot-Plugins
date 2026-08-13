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
- V3 的普通 JSON API 返回 `{ "success", "message", "data" }` 统一结构。插件
  `get_api()` 的 endpoint 直接返回业务对象即可，宿主会自动包装；不要手工再套一层
  同名字典。Vue 远程组件通过宿主传入的 `api` 或 `window.MoviePilotAPI` 调用时会
  保留完整结构，业务对象从返回值的 `data` 字段读取。
- 媒体相关通用接口必须成对传递 `media_source` 与 `media_id`；明确单数据源的插件
  自有 API 可以继续按该来源原生合同设计参数。完整边界见
  [V3 插件适配指南](../V3_Plugin_Adaptation.md)。
