# MoviePilot-Plugins
MoviePilot官方插件市场：https://github.com/jxxghp/MoviePilot-Plugins

## 第三方插件库开发说明
> 请不要开发用于破解MoviePilot用户认证、色情、赌博等违法违规内容的插件，共同维护健康的开发环境！


### 1. 目录结构
- 插件仓库需要保持与本项目一致的目录结构（建议fork后修改），仅支持Github仓库，`plugins`存放插件代码，一个插件一个子目录，**子目录名必须为插件类名的小写**，插件主类在`__init__.py`中编写。
- `package.json`为插件仓库中所有插件概要信息，用于在MoviePilot的插件市场显示，其中版本号等需与插件代码保持一致，通过修改版本号可触发MoviePilot显示插件更新。 

### 2. 插件图标
- 插件图标可复用官方插件库中`icons`下已有图标，否则需使用完整的http格式的url图片链接（包括package.json中的icon和插件代码中的plugin_icon）。
- 插件的背景颜色会自动提取使用图标的主色调。

### 3. 插件命名
- 插件命名请勿与官方库插件中的插件冲突，否则会在MoviePilot版本升级时被官方插件覆盖。

### 4. 依赖
- 可在插件目录中放置`requirements.txt`文件，用于指定插件依赖的第三方库，MoviePilot会在插件安装时自动安装依赖库。

### 5. 界面开发
- 插件支持`插件配置`、`详情展示`、`仪表板Widget`三个展示页面，通过配置化的方式组装，使用 [Vuetify](https://vuetifyjs.com/) 组件库，所有该组件库有的组件都可以通过Json配置使用，详情参考已有插件。
  - `props`中`model`属性等效于v-model，`show`等效于v-show，其它属于会直接绑定到元素上。
  - 插件配置页面props属性支持表达式，使用`{{}}`概起来；支持事件，以`on`开头，比如：onclick。
  - 详情展示页面支持API调用,在`events`属性中定义。


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
  
- MoviePilot中所有事件清单（V2版本），可以通过实现这些事情来扩展功能，同时插件之前也可以通过发送和监听事件实现联动（V1、V2事件清单有差异，且可能会变化，最新请参考源代码）。
```python
# 异步广播事件
class EventType(Enum):
    # 插件需要重载
    PluginReload = "plugin.reload"
    # 触发插件动作
    PluginAction = "plugin.action"
    # 插件触发事件
    PluginTriggered = "plugin.triggered"
    # 执行命令
    CommandExcute = "command.excute"
    # 站点已删除
    SiteDeleted = "site.deleted"
    # 站点已更新
    SiteUpdated = "site.updated"
    # 站点已刷新
    SiteRefreshed = "site.refreshed"
    # 转移完成
    TransferComplete = "transfer.complete"
    # 下载已添加
    DownloadAdded = "download.added"
    # 删除历史记录
    HistoryDeleted = "history.deleted"
    # 删除下载源文件
    DownloadFileDeleted = "downloadfile.deleted"
    # 删除下载任务
    DownloadDeleted = "download.deleted"
    # 收到用户外来消息
    UserMessage = "user.message"
    # 收到Webhook消息
    WebhookMessage = "webhook.message"
    # 发送消息通知
    NoticeMessage = "notice.message"
    # 订阅已添加
    SubscribeAdded = "subscribe.added"
    # 订阅已调整
    SubscribeModified = "subscribe.modified"
    # 订阅已删除
    SubscribeDeleted = "subscribe.deleted"
    # 订阅已完成
    SubscribeComplete = "subscribe.complete"
    # 系统错误
    SystemError = "system.error"
    # 刮削元数据
    MetadataScrape = "metadata.scrape"
    # 模块需要重载
    ModuleReload = "module.reload"


# 同步链式事件
class ChainEventType(Enum):
    # 名称识别
    NameRecognize = "name.recognize"
    # 认证验证
    AuthVerification = "auth.verification"
    # 认证拦截
    AuthIntercept = "auth.intercept"
    # 命令注册
    CommandRegister = "command.register"
    # 整理重命名
    TransferRename = "transfer.rename"
    # 整理拦截
    TransferIntercept = "transfer.intercept"
    # 资源选择
    ResourceSelection = "resource.selection"
    # 资源下载
    ResourceDownload = "resource.download"
    # 发现数据源
    DiscoverSource = "discover.source"
    # 媒体识别转换
    MediaRecognizeConvert = "media.recognize.convert"
    # 推荐数据源
    RecommendSource = "recommend.source"
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
  注意：在插件中暴露API接口时注意安全控制，推荐使用`settings.API_TOKEN`进行身份验证。
  
- 在对应的方法中实现API响应方法逻辑，通过 `http://localhost:3001/docs` 查看API文档和调试

### 4. 如何在插件中注册公共定时服务？
- 注册公共定时服务后，可以在`设定-服务`中查看运行状态和手动启动，更加便捷。
- 实现 `get_service()` 方法，按以下格式返回服务注册信息：
    ```json
    [{
        "id": "服务ID", // 不能与其它服务ID重复
        "name": "服务名称", // 显示在服务列表中的名称
        "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
        "func": self.xxx, // 服务方法
        "kwargs": {} // 定时器参数，参考APScheduler
    }]
    ```

### 5. 如何通过插件增强MoviePilot的识别功能？
- V1按如下步骤实现，V2版本直接实现对应链式事件即可，参考ChatGPT插件。注意：只有主程序无法识别时才会触发。
- 注册 `NameRecognize` 事件，实现识别逻辑。
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
  
### 6. 如何扩展内建索引器的索引站点？
- 通过调用 `SitesHelper().add_indexer(domain: str, indexer: dict)` 方法，新增或修改内建索引器的支持范围，其中`indexer`为站点配置Json，格式示例如下：

  示例一：
  ```json
  {
    "id": "nyaa",
    "name": "Nyaa",
    "domain": "https://nyaa.si/",
    "encoding": "UTF-8",
    "public": true,
    "proxy": true,
    "result_num": 100,
    "timeout": 30,
    "search": {
      "paths": [
        {
          "path": "?f=0&c=0_0&q={keyword}",
          "method": "get"
        }
      ]
    },
    "browse": {
      "path": "?p={page}",
      "start": 1
    },
    "torrents": {
      "list": {
        "selector": "table.torrent-list > tbody > tr"
      },
      "fields": {
        "id": {
          "selector": "a[href*=\"/view/\"]",
          "attribute": "href",
          "filters": [
            {
              "name": "re_search",
              "args": [
                "\\d+",
                0
              ]
            }
          ]
        },
        "title": {
          "selector": "td:nth-child(2) > a"
        },
        "details": {
          "selector": "td:nth-child(2) > a",
          "attribute": "href"
        },
        "download": {
          "selector": "td:nth-child(3) > a[href*=\"/download/\"]",
          "attribute": "href"
        },
        "date_added": {
          "selector": "td:nth-child(5)"
        },
        "size": {
          "selector": "td:nth-child(4)"
        },
        "seeders": {
          "selector": "td:nth-child(6)"
        },
        "leechers": {
          "selector": "td:nth-child(7)"
        },
        "grabs": {
          "selector": "td:nth-child(8)"
        },
        "downloadvolumefactor": {
          "case": {
            "*": 0
          }
        },
        "uploadvolumefactor": {
          "case": {
            "*": 1
          }
        }
      }
    }
  }
  ```

  示例二：
  ```json
  {
      "id": "xxx",
      "name": "站点名称",
      "domain": "https://www.xxx.com/",
      "ext_domains": [
        "https://www.xxx1.com/",
        "https://www.xxx2.com/"
      ],
      "encoding": "UTF-8",
      "public": false,
      "search": {
        "paths": [
          {
            "path": "torrents.php",
            "method": "get"
          }
        ],
        "params": {
          "search": "{keyword}",
          "search_area": 4
        },
        "batch": {
          "delimiter": " ",
          "space_replace": "_"
        }
      },
      "category": {
        "movie": [
          {
            "id": 401,
            "cat": "Movies",
            "desc": "Movies电影"
          },
          {
            "id": 405,
            "cat": "Anime",
            "desc": "Animations动漫"
          },
          {
            "id": 404,
            "cat": "Documentary",
            "desc": "Documentaries纪录片"
          }
        ],
        "tv": [
          {
            "id": 402,
            "cat": "TV",
            "desc": "TV Series电视剧"
          },
          {
            "id": 403,
            "cat": "TV",
            "desc": "TV Shows综艺"
          },
          {
            "id": 404,
            "cat": "Documentary",
            "desc": "Documentaries纪录片"
          },
          {
            "id": 405,
            "cat": "Anime",
            "desc": "Animations动漫"
          }
        ]
      },
      "torrents": {
        "list": {
          "selector": "table.torrents > tr:has(\"table.torrentname\")"
        },
        "fields": {
          "id": {
            "selector": "a[href*=\"details.php?id=\"]",
            "attribute": "href",
            "filters": [
              {
                "name": "re_search",
                "args": [
                  "\\d+",
                  0
                ]
              }
            ]
          },
          "title_default": {
            "selector": "a[href*=\"details.php?id=\"]"
          },
          "title_optional": {
            "optional": true,
            "selector": "a[title][href*=\"details.php?id=\"]",
            "attribute": "title"
          },
          "title": {
            "text": "{% if fields['title_optional'] %}{{ fields['title_optional'] }}{% else %}{{ fields['title_default'] }}{% endif %}"
          },
          "details": {
            "selector": "a[href*=\"details.php?id=\"]",
            "attribute": "href"
          },
          "download": {
            "selector": "a[href*=\"download.php?id=\"]",
            "attribute": "href"
          },
          "imdbid": {
            "selector": "div.imdb_100 > a",
            "attribute": "href",
            "filters": [
              {
                "name": "re_search",
                "args": [
                  "tt\\d+",
                  0
                ]
              }
            ]
          },
          "date_elapsed": {
            "selector": "td:nth-child(4) > span",
            "optional": true
          },
          "date_added": {
            "selector": "td:nth-child(4) > span",
            "attribute": "title",
            "optional": true
          },
          "size": {
            "selector": "td:nth-child(5)"
          },
          "seeders": {
            "selector": "td:nth-child(6)"
          },
          "leechers": {
            "selector": "td:nth-child(7)"
          },
          "grabs": {
            "selector": "td:nth-child(8)"
          },
          "downloadvolumefactor": {
            "case": {
              "img.pro_free": 0,
              "img.pro_free2up": 0,
              "img.pro_50pctdown": 0.5,
              "img.pro_50pctdown2up": 0.5,
              "img.pro_30pctdown": 0.3,
              "*": 1
            }
          },
          "uploadvolumefactor": {
            "case": {
              "img.pro_50pctdown2up": 2,
              "img.pro_free2up": 2,
              "img.pro_2up": 2,
              "*": 1
            }
          },
          "description": {
            "selector": "td:nth-child(2) > table > tr > td.embedded > span[style]",
            "contents": -1
          },
          "labels": {
            "selector": "td:nth-child(2) > table > tr > td.embedded > span.tags"
          }
        }
      }
    }
  ```
- 需要注意的是，如果你没有完成用户认证，通过插件配置进去的索引站点也是无法正常使用的。
- **请不要添加对黄赌毒站点的支持，否则随时封闭接口。** 

### 7. 如何在插件中调用API接口？
- `v1.8.4+` 在插件的数据页面支持`GET/POST`API接口调用，可调用插件自身、主程序或其它插件的API。
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
        "doubanid": ""
      }
    }
  }
}
```
- 每次API调用完成后，均会自动刷新一次插件数据页。

### 8. 如何将插件内容显示到仪表板？
- `v1.8.7+` 支持将插件的内容显示到仪表盘，并支持定义占据的单元格大小，插件产生的仪表板仅管理员可见。
- 1. 根据插件需要展示的Widget内容规划展示内容的样式和规格，也可设计多个规格样式并提供配置项供用户选择。
- 2. 实现 `get_dashboard_meta` 方法，定义仪表板key及名称，支持一个插件有多个仪表板：
```python
def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
    """
    获取插件仪表盘元信息
    返回示例：
        [{
            "key": "dashboard1", // 仪表盘的key，在当前插件范围唯一
            "name": "仪表盘1" // 仪表盘的名称
        }, {
            "key": "dashboard2",
            "name": "仪表盘2"
        }]
    """
    pass
```
- 3. 实现 `get_dashboard` 方法，根据key返回仪表盘的详细配置信息，包括仪表盘的cols列配置（适配不同屏幕），以及仪表盘的页面配置json，具体可参考插件`站点数据统计`：
```python
def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
    """
    获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
    1、col配置参考：
    {
        "cols": 12, "md": 6
    }
    2、全局配置参考：
    {
        "refresh": 10, // 自动刷新时间，单位秒
        "border": True, // 是否显示边框，默认True，为False时取消组件边框和边距，由插件自行控制
        "title": "组件标题", // 组件标题，如有将显示该标题，否则显示插件名称
        "subtitle": "组件子标题", // 组件子标题，缺省时不展示子标题
    }
    3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/

    kwargs参数可获取的值：1、user_agent：浏览器UA

    :param key: 仪表盘key，根据指定的key返回相应的仪表盘数据，缺省时返回一个固定的仪表盘数据（兼容旧版）
    """
    pass
```

### 9. 如何扩展探索功能的媒体数据源？
- （仅V2版本）探索功能仅内置`TheMovieDb`、`豆瓣`和`Bangumi`数据源，`v2.2.7+`版本可通过插件扩展探索功能的数据源范围，按以下方法开发插件（参考`TheTVDB探索`插件）：
- 1. 实现`ChainEventType.DiscoverSource`链式事件响应，将额外的媒体数据源塞入事件数据`extra_sources`数组中（注意：如果事件中已经有其它数据源，需要叠加而不是替换，避免影响其它插件塞入的数据）
  
  - `name`：数据源名称
  - `mediaid_prefix`：数据源的唯一ID
  - `api_path`：数据获取API相对路径，需要在插件中实现API接口功能，GET模式接收过滤参数（注意：page参数默认需要有），返回`List[schemas.MediaInfo])`格式数据（注意：mediaid_prefix和media_id需要赋值，用于唯一索引媒体详细信息和转换媒体数据）。
  - `filter_params`：数据源过滤参数名的字典，相关参数会传入插件API的GET请求中
  - `filter_ui`：数据过滤选项的UI配置json，与插件配置表单方式一致
  - `depends`: UI依赖关系字典Dict[str, list]，关过滤条件存在依赖关系时需要设置，以便上级条件变化时清空下级条件值

```python
class DiscoverMediaSource(BaseModel):
    """
    探索媒体数据源的基类
    """
    name: str = Field(..., description="数据源名称")
    mediaid_prefix: str = Field(..., description="媒体ID的前缀，不含:")
    api_path: str = Field(..., description="媒体数据源API地址")
    filter_params: Optional[Dict[str, Any]] = Field(default=None, description="过滤参数")
    filter_ui: Optional[List[dict]] = Field(default=[], description="过滤参数UI配置")

class DiscoverSourceEventData(ChainEventData):
    """
    DiscoverSource 事件的数据模型
    Attributes:
        # 输出参数
        extra_sources (List[DiscoverMediaSource]): 额外媒体数据源
    """
    # 输出参数
    extra_sources: List[DiscoverMediaSource] = Field(default_factory=list, description="额外媒体数据源")
```

- 2. 实现`ChainEventType.MediaRecognizeConvert`链式事件响应（**可选**，如不实现则默认按标题重新识别媒体信息），根据媒体ID和转换类型，返回TheMovieDb或豆瓣的媒体数据，将转换后的数据注入事件数据`media_dict`中，可参考`app/chain/media.py`中的`get_tmdbinfo_by_bangumiid`。

  - `mediaid`：媒体ID，格式为`mediaid_prefix:media_id`，如 tmdb:12345、douban:1234567
  - `convert_type`：转换类型，仅支持：themoviedb/douban，需要转换为对应的媒体数据并返回
  - `media_dict`：转换后的媒体数据，格式为`TheMovieDb/豆瓣`的媒体数据

```python
class MediaRecognizeConvertEventData(ChainEventData):
    """
    MediaRecognizeConvert 事件的数据模型
    Attributes:
        # 输入参数
        mediaid (str): 媒体ID，格式为`前缀:ID值`，如 tmdb:12345、douban:1234567
        convert_type (str): 转换类型 仅支持：themoviedb/douban，需要转换为对应的媒体数据并返回
        # 输出参数
        media_dict (dict): TheMovieDb/豆瓣的媒体数据
    """
    # 输入参数
    mediaid: str = Field(..., description="媒体ID")
    convert_type: str = Field(..., description="转换类型（themoviedb/douban）")
    # 输出参数
    media_dict: dict = Field(default=dict, description="转换后的媒体信息（TheMovieDb/豆瓣）")
```
- 3. 启用插件后，点击探索功能将自动生成额外的数据源标签及页面，页面中选择不同的过滤条件时会重新触发API请求。

### 10. 如何扩展推荐功能的媒体数据源？
- （仅V2版本）推荐功能`v2.2.8+`版本可通过插件扩展数据源范围，按以下方法开发插件：
- 1. 实现`ChainEventType.RecommendSource`链式事件响应，将额外的媒体数据源塞入事件数据`extra_sources`数组中（注意：如果事件中已经有其它数据源，需要叠加而不是替换，避免影响其它插件塞入的数据）

  - `name`：数据源名称
  - `api_path`：数据获取API相对路径，需要在插件中实现API接口功能，GET模式接收过滤参数（注意：page参数默认需要有），返回`List[schemas.MediaInfo])`格式数据，参考`app/api/endpoints/recommend.py` 中的 `tmdb_trending`。

```python
class RecommendMediaSource(BaseModel):
    """
    推荐媒体数据源的基类
    """
    name: str = Field(..., description="数据源名称")
    api_path: str = Field(..., description="媒体数据源API地址")

class RecommendSourceEventData(ChainEventData):
    """
    RecommendSource 事件的数据模型
    Attributes:
        # 输出参数
        extra_sources (List[RecommendMediaSource]): 额外媒体数据源
    """
    # 输出参数
    extra_sources: List[RecommendMediaSource] = Field(default_factory=list, description="额外媒体数据源")
```

### 11. 如何发布插件版本？
- 修改插件代码后，需要修改`package.json`中的`version`版本号，MoviePilot才会提示用户有更新，注意版本号需要与`__init__.py`文件中的`plugin_version`保持一致。
- `package.json`中的`level`用于定义插件用户可见权限，`1`为所有用户可见，`2`为仅认证用户可见，`3`为需要密钥才可见（一般用于测试）。如果插件功能需要使用到站点则应该为2，否则即使插件对用户可见但因为用户未认证相关功能也无法正常使用。
- `package.json`中的`history`用于记录插件更新日志，格式如下：
```json
{
  "history": {
    "v1.8": "修复空目录删除逻辑",
    "v1.7": "增加定时清理空目录功能"
  }
}
```
- 新增加的插件请配置在`package.json`中的末尾，这样可被识别为最新增加，可用于用户排序。

### 12. 如何开发V2版本的插件以及实现插件多版本兼容？

- 请参阅 [V2版本插件开发指南](./docs/V2_Plugin_Development.md)
