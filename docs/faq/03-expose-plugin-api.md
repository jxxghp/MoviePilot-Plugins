# 如何在插件中对外暴露 API？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

V3 插件 API 可自行选择裸业务模型或 `{ success, message, data }` 响应。完整的
输出模型、业务失败、原生响应和 Vue 调用规范见
[V3 插件 API 响应适配指南](../V3_API_Response_Adaptation.md)。

- 实现 `get_api()` 方法，返回 API 列表：

  ```python
  from typing import Any, Dict, List

  from pydantic import BaseModel


  class RefreshResultData(BaseModel):
      """刷新接口的业务数据。"""

      refreshed: bool


  def refresh_by_domain(self, domain: str) -> RefreshResultData:
      """刷新指定域名并返回结果。"""
      self._refresh(domain)
      return RefreshResultData(refreshed=True)


  def get_api(self) -> List[Dict[str, Any]]:
      """注册插件 API。"""
      return [
          {
              "path": "/refresh_by_domain",
              "endpoint": self.refresh_by_domain,
              "methods": ["GET"],
              "auth": "bear",
              "summary": "刷新站点数据",
              "description": "刷新对应域名的站点数据",
              "response_model": RefreshResultData,
          }
      ]
  ```

- 上述 endpoint 的实际响应就是 `RefreshResultData`，宿主不会把它放入 `data`。
- 每个普通 JSON endpoint 都必须声明具体 `response_model`，确保输出结构可在
  `http://localhost:3001/docs` 中查询。
- 需要接入宿主普通数据页面、统一反馈或保持三段式合同时，显式返回并声明参数化的
  `schemas.Response[DataModel]`。
- SSE、文件、图片、HTML 和 204 才使用原生响应，并显式声明 `response_class`、
  `response_model=None` 与 OpenAPI content。
- `auth: "bear"` 适用于宿主前端登录态；外部自动化调用可按插件安全边界选择
  默认 API key 认证。不要自行把令牌放入响应或日志。
