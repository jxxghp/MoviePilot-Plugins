# 如何在插件中注册智能体工具？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 `v2.8.0+` 版本）**
- MoviePilot的AI智能体功能支持通过插件扩展工具能力，插件可以注册自定义工具供智能体调用，实现更丰富的功能扩展。
- 1. 实现 `get_agent_tools()` 方法，返回工具类列表：
    ```python
    def get_agent_tools(self) -> List[Type]:
        """
        获取插件智能体工具
        返回工具类列表，每个工具类必须继承自 MoviePilotTool
        """
        return [MyCustomTool, AnotherTool]
    ```

- 2. 创建工具类，必须继承自 `MoviePilotTool` 并实现相关要求：
    ```python
    from typing import Optional, Type
    from pydantic import BaseModel, Field
    from app.agent.tools.base import MoviePilotTool
    from app.chain import ToolChain
    
    class MyToolInput(BaseModel):
        """工具输入参数模型"""
        explanation: str = Field(..., description="工具使用说明")
        query: str = Field(..., description="查询内容")
        limit: Optional[int] = Field(10, description="返回结果数量限制")
    
    class MyCustomTool(MoviePilotTool):
        """自定义工具示例"""
        # 工具名称，用于智能体识别和调用
        name: str = "my_custom_tool"
        
        # 工具描述，用于智能体理解工具功能，建议详细描述工具用途和使用场景
        description: str = "This tool is used to perform custom operations. Use it when you need to query or process specific data."
        
        # 输入参数模型，定义工具接收的参数及其类型和说明
        args_schema: Type[BaseModel] = MyToolInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
          """根据订阅参数生成友好的提示消息"""
          pass
        
        async def run(self, query: str, limit: Optional[int] = None, **kwargs) -> str:
            """
            实现工具的核心逻辑（异步方法）
            :param query: 查询内容
            :param limit: 结果数量限制
            :param kwargs: 其他参数，包含 explanation（工具使用说明）
            :return: 工具执行结果，返回字符串格式
            """
            try:
                # 获取上下文信息（系统自动注入）
                session_id = self._session_id
                user_id = self._user_id
                channel = self._channel
                source = self._source
                username = self._username
                
                # 执行工具逻辑
                result = await self._perform_operation(query, limit)
                
                # 可以通过 send_tool_message 发送消息给用户
                await self.send_tool_message(f"操作完成: {result}", title="工具执行")
                
                # 返回执行结果
                return f"成功处理查询 '{query}'，返回 {len(result)} 条结果"
            except Exception as e:
                return f"执行失败: {str(e)}"
        
        async def _perform_operation(self, query: str, limit: int):
            """内部方法，执行具体操作"""
            # 实现具体业务逻辑
            pass
    ```

- 3. 工具类可用的上下文属性和方法：
    - `self._session_id`: 当前会话ID
    - `self._user_id`: 用户ID
    - `self._channel`: 消息渠道（如 Telegram、Slack 等）
    - `self._source`: 消息来源
    - `self._username`: 用户名
    - `self.send_tool_message(message: str, title: str = "")`: 发送消息给用户
    - `ToolChain()`: 访问处理链功能，可调用系统其他功能

- 4. 工具类实现要求：
    - **必须继承自 `app.agent.tools.base.MoviePilotTool`**
    - **必须实现 `run` 方法**（异步方法），接收参数并返回字符串结果
    - **必须实现 `get_tool_message` 方法**，以显示友好的工具执行提示给用户
    - **必须定义 `name` 属性**（字符串），工具的唯一标识
    - **必须定义 `description` 属性**（字符串），详细描述工具功能，帮助智能体理解何时使用该工具
    - **可选定义 `args_schema` 属性**（Pydantic模型类），用于定义输入参数的结构和验证

- 5. 注意事项：
    - 工具的描述（`description`）应该清晰明确，帮助智能体理解工具的功能和使用场景
    - 工具的参数模型（`args_schema`）应该包含详细的字段描述，帮助智能体正确构造参数
    - 工具执行结果应该返回有意义的字符串，便于智能体理解和向用户展示
    - 工具可以通过 `send_tool_message` 方法向用户发送实时消息，提升交互体验
    - 工具类在初始化时会自动注入会话和用户信息，可以通过私有属性访问
    - 如果工具需要访问插件实例，需要自行通过 `PluginManager` 获取
    - 工具执行时间应该尽量短，避免阻塞智能体的响应
    - 建议在工具执行过程中添加适当的错误处理和日志记录
