# MoviePilot-Plugins
MoviePilot官方插件市场：https://github.com/jxxghp/MoviePilot-Plugins

## 第三方插件库开发说明
> 请不要开发用于破解MoviePilot用户认证、色情、赌博等违法违规内容的插件，共同维护健康的开发环境！


### 1. 目录结构
- 插件仓库需要保持与本项目一致的目录结构（建议fork后修改），仅支持Github仓库，`plugins`存放插件代码，一个插件一个子目录，**子目名名必须为插件类名的小写**，插件主类在`__init__.py`中编写。
- `package.json`为插件仓库中所有插件概要信息，用于在MoviePilot的插件市场显示，其中版本号等需与插件代码保持一致，通过修改版本号可触发MoviePilot显示插件更新。 

### 2. 插件图标
- 插件图标可复用官方插件库中`icons`下已有图标，否则需使用完成的http格式的url图片链接（包括package.json中的icon和插件代码中的plugin_icon）。

### 3. 插件命名
- 插件命名请勿与官方库插件中的插件冲突，否则会在MoviePilot版本升级时被官方插件覆盖。

### 4. 依赖
- 可在插件目录中放置`requirement.txt`文件，用于指定插件依赖的第三方库，MoviePilot会在插件安装时自动安装依赖库。

### 5. 界面开发
- 插件支持`插件配置`及`详情展示`两个展示页面，通过配置化的方式组装，使用[Vuetify](https://vuetifyjs.com/)组件库，所有该组件库有的组件都可以通过Json配置使用。


## 常见问题

### 1. 如何扩展消息推送渠道？
- 注册 `NoticeMessage` 事件响应，`event_data` 包含消息中的所有数据，参考 `IYUU消息通知` 插件：

    注册事件：
    ```python
    @eventmanager.register(EventType.NoticeMessage)
    ```

- 事件对象：
    ```json
    {
         "channel": MessageChannel|None,
         "type": NotificationType|None,
         "title": str,
         "text": str,
         "image": str,
         "userid": str|int,
    }
    ```
  
PS：MoviePilot中的其它事件也是同样方法实现响应：
```python
class EventType(Enum):
    # 插件重载
    PluginReload = "plugin.reload"
    # 插件动作
    PluginAction = "plugin.action"
    # 执行命令
    CommandExcute = "command.excute"
    # 站点删除
    SiteDeleted = "site.deleted"
    # Webhook消息
    WebhookMessage = "webhook.message"
    # 转移完成
    TransferComplete = "transfer.complete"
    # 添加下载
    DownloadAdded = "download.added"
    # 删除历史记录
    HistoryDeleted = "history.deleted"
    # 删除下载源文件
    DownloadFileDeleted = "downloadfile.deleted"
    # 用户外来消息
    UserMessage = "user.message"
    # 通知消息
    NoticeMessage = "notice.message"
    # 名称识别请求
    NameRecognize = "name.recognize"
    # 名称识别结果
    NameRecognizeResult = "name.recognize.result"
```
  
### 2. 如何在插件中实现远程命令响应？
- 实现 `get_command()` 方法，按以下格式返回命令列表：
    ```json
    [{
        "cmd": "/douban_sync", // 动作ID，必须以/开始
        "event": EventType.PluginAction,// 事件类型，固定值
        "desc": "命令名称",
        "category": "命令菜单（微信）",
        "data": {
            "action": "douban_sync" // 动作标识
        }
    }]
    ```

- 注册 `PluginAction` 事件响应，根据 `event_data.action` 是否为插件设定的动作标识来判断是否为本插件事件：

    注册事件：
    ```python
    @eventmanager.register(EventType.PluginAction)
    ```
    
    事件判定：
    ```python
    event_data = event.event_data
    if not event_data or event_data.get("action") != "douban_sync":
        return
    ```
  
### 3. 如何在插件中对外暴露API？
- 实现 `get_api()` 方法，按以下格式返回API列表：
    ```json
    [{
        "path": "/refresh_by_domain", // API路径，必须以/开始
        "endpoint": self.refresh_by_domain, // API响应方法
        "methods": ["GET"], // 请求方式：GET/POST/PUT/DELETE
        "summary": "刷新站点数据", // API名称
        "description": "刷新对应域名的站点数据", // API描述
    }]
    ```
  
- 在对应的方法中实现API响应方法逻辑，通过 `http://localhost:3001/docs` 查看API文档和调试

### 4. 如何通过插件增强MoviePilot的识别功能？
- 注册 `NameRecognize` 事件，实现识别逻辑（参考ChatGPT插件），注意：只有主程序无法识别时才会触发该事件
    ```python
    @eventmanager.register(EventType.NameRecognize)
    ```
  
- 完成识别后发送 `NameRecognizeResult` 事件，将识别结果注入主程序
    ```python
    eventmanager.send_event(
        EventType.NameRecognizeResult,
        {
            'title': title, # 原传入标题
            'name': str, # 识别的名称
            'year': str, # 识别的年份
            'season': int, # 识别的季号
            'episode': int, # 识别的集号
        }
    )
    ```
  
- 注意：识别请求需要在15秒内响应，否则结果会被丢弃；**插件未启用或参数不完整时应立即回复空结果事件，避免主程序等待；** 多个插件开启识别功能时，以先收到的识别结果事件为准。
    ```python
    eventmanager.send_event(
        EventType.NameRecognizeResult,
        {
            'title': title # 结果只含原标题，代表空识别结果事件
        }
    )
    ```