# 如何在插件中通过消息持续与用户交互？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 v2.5.7+ 版本）**
- 插件可以通过实现命令响应和消息按钮回调实现与用户的持续交互对话，支持多轮对话和菜单式操作，适用于支持按钮回调的通知渠道（如Telegram、Slack等）。

- 1. 实现远程命令响应，参考 [《如何在插件中实现远程命令响应？》](./02-remote-command-handler.md) 实现 `get_command()` 方法和 `PluginAction` 事件响应：
    ```python
    def get_command(self) -> List[Dict[str, Any]]:
        """
        注册插件远程命令
        """
        return [{
            "cmd": "/interactive_demo",
            "event": EventType.PluginAction,
            "desc": "交互演示",
            "category": "插件交互",
            "data": {
                "action": "interactive_demo"
            }
        }]

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event):
        """
        远程命令响应
        """
        event_data = event.event_data
        if not event_data or event_data.get("action") != "interactive_demo":
            return
        
        # 获取用户信息
        channel = event_data.get("channel")
        source = event_data.get("source")
        user = event_data.get("user")
        
        # 发送带有交互按钮的消息
        self._send_main_menu(channel, source, user)
    ```

- 2. 注册 `MessageAction` 事件响应，处理用户的按钮回调：
    ```python
    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        """
        处理消息按钮回调
        """
        event_data = event.event_data
        if not event_data:
            return
            
        # 检查是否为本插件的回调
        plugin_id = event_data.get("plugin_id")
        if plugin_id != self.__class__.__name__:
            return
            
        # 获取回调数据
        text = event_data.get("text", "")
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = event_data.get("userid")
        # 获取原始消息ID和聊天ID（用于直接更新原消息）
        original_message_id = event_data.get("original_message_id")
        original_chat_id = event_data.get("original_chat_id")
        
        # 根据回调内容处理不同的交互
        if text == "menu1":
            self._handle_menu1(channel, source, userid, original_message_id, original_chat_id)
        elif text == "menu2":
            self._handle_menu2(channel, source, userid, original_message_id, original_chat_id)
        elif text == "back":
            self._send_main_menu(channel, source, userid, original_message_id, original_chat_id)
        elif text.startswith("action_"):
            action_id = text.replace("action_", "")
            self._handle_action(action_id, channel, source, userid, original_message_id, original_chat_id)
    ```

- 3. 实现具体的交互处理方法，在消息中使用 `[PLUGIN]插件ID|内容` 格式的按钮：
    ```python
    def _send_main_menu(self, channel, source, userid, original_message_id=None, original_chat_id=None):
        """
        发送主菜单
        """
        buttons = [
            [
                {"text": "🎬 媒体管理", "callback_data": f"[PLUGIN]{self.__class__.__name__}|menu1"},
                {"text": "⚙️ 系统设置", "callback_data": f"[PLUGIN]{self.__class__.__name__}|menu2"}
            ],
            [
                {"text": "📊 查看状态", "callback_data": f"[PLUGIN]{self.__class__.__name__}|status"}
            ]
        ]
        
        self.post_message(
            channel=channel,
            title="🤖 插件交互演示",
            text="请选择要执行的操作：",
            userid=userid,
            buttons=buttons,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id
        )

    def _handle_menu1(self, channel, source, userid, original_message_id, original_chat_id):
        """
        处理媒体管理菜单
        """
        buttons = [
            [
                {"text": "🔍 搜索媒体", "callback_data": f"[PLUGIN]{self.__class__.__name__}|action_search"},
                {"text": "📥 下载管理", "callback_data": f"[PLUGIN]{self.__class__.__name__}|action_download"}
            ],
            [
                {"text": "🔙 返回主菜单", "callback_data": f"[PLUGIN]{self.__class__.__name__}|back"}
            ]
        ]
        
        self.post_message(
            channel=channel,
            title="🎬 媒体管理",
            text="选择媒体管理功能：",
            userid=userid,
            buttons=buttons,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id
        )

    def _handle_action(self, action_id, channel, source, userid, original_message_id, original_chat_id):
        """
        处理具体动作
        """
        if action_id == "search":
            # 执行搜索逻辑
            result = "搜索功能已执行"
        elif action_id == "download":
            # 执行下载逻辑
            result = "下载管理已开启"
        else:
            result = "未知操作"
            
        # 发送执行结果并提供返回按钮
        buttons = [
            [{"text": "🔙 返回主菜单", "callback_data": f"[PLUGIN]{self.__class__.__name__}|back"}]
        ]
        
        self.post_message(
            channel=channel,
            title="✅ 操作完成",
            text=result,
            userid=userid,
            buttons=buttons,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id
        )
    ```

- 注意事项：
  - 回调按钮的 `callback_data` 必须使用 `[PLUGIN]插件ID|内容` 格式，其中插件ID为插件类名
  - 只有支持按钮回调的通知渠道（如Telegram、Slack）才能使用此功能
  - 建议在交互中保存用户状态数据，以支持复杂的多步骤操作
  - 可以结合插件数据存储功能保存用户的交互历史和偏好设置
