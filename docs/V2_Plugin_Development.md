# MoviePilot V2 插件开发指南

本指南详细介绍了如何开发适用于MoviePilot V2版本的插件，并实现插件的多版本兼容性。包括服务封装类的使用示例，帮助开发者快速升级插件至V2版本。

## 1. 多版本插件开发与兼容性

### 1.1 开发V2版本的插件

要开发适用于MoviePilot V2版本的插件，并实现多版本兼容性，请按照以下步骤操作：

1. **目录结构调整**：
   - 将插件代码放置在`plugins.v2`文件夹中。
   - 将插件的定义放置在`package.v2.json`中，以实现该插件仅在MoviePilot V2版本中可见。

2. **插件定义示例**：
    ```json
    {
      "CustomSites": {
          "name": "自定义站点",
          "description": "增加自定义站点为签到和统计使用。",
          "labels": "站点",
          "version": "1.0",
          "icon": "world.png",
          "author": "lightolly",
          "level": 2
      }
    }
    ```

3. **版本判断**：
   - MoviePilot V2中 Settings 模块新增了`VERSION_FLAG`属性，V2版本值为`v2`，可通过以下代码判断当前的版本，以便在插件中兼容处理：

    ```python
    from app.core.config import settings

    if hasattr(settings, 'VERSION_FLAG'):
      version = settings.VERSION_FLAG # V2
    else:
      version = "v1"
    ```

### 1.2 实现插件多版本兼容

如果V1版本插件在V2版本中实际可用，或在插件中主动兼容了V1和V2版本，则可以在`package.json`中定义 `"v2": true`属性，以便在MoviePilot V2版本插件市场中显示。

```json
{
  "CustomSites": {
      "name": "自定义站点",
      "description": "增加自定义站点为签到和统计使用。",
      "labels": "站点",
      "version": "1.0",
      "icon": "world.png",
      "author": "lightolly",
      "level": 2,
      "v2": true
  }
}
```

- **目录结构示例**：
  ```
  plugins/
    ├── customsites/
    │   ├── __init__.py
    │   └── ...
  plugins.v2/
    ├── customsites/
    │   ├── __init__.py
    │   └── ...
  package.json
  package.v2.json
  ```

- **插件代码中实现版本兼容**：

    在插件代码中，可以根据`version`变量执行不同的逻辑，以适应不同的MoviePilot版本。

    ```python
    from app.core.config import settings

    class MyPlugin:
        def init_plugin(self, config: dict = None):
            if hasattr(settings, 'VERSION_FLAG'):
                version = settings.VERSION_FLAG  # V2
            else:
                version = "v1"

            if version == "v2":
                self.setup_v2()
            else:
                self.setup_v1()

        def setup_v2(self):
            # V2版本特有的初始化逻辑
            pass

        def setup_v1(self):
            # V1版本特有的初始化逻辑
            pass
    ```

## 2. 服务封装与使用示例

为了插件调用并共享实例，主程序针对几种服务进行了封装。以下是相关实现及如何在插件中使用这些封装的详细说明，帮助开发者快速将插件从V1升级到V2。

### 2.1 服务封装类介绍

#### `ServiceInfo`
`ServiceInfo` 是一个数据类，用于封装服务的相关信息。

```python
from dataclasses import dataclass
from typing import Optional, Any

@dataclass
class ServiceInfo:
    """
    封装服务相关信息的数据类
    """
    # 名称
    name: Optional[str] = None
    # 实例
    instance: Optional[Any] = None
    # 模块
    module: Optional[Any] = None
    # 类型
    type: Optional[str] = None
    # 配置
    config: Optional[Any] = None
```

#### `ServiceBaseHelper`
`ServiceBaseHelper` 是一个通用的服务帮助类，提供了获取配置和服务实例的通用逻辑。

```python
from typing import Dict, List, Optional, Type, TypeVar, Generic, Iterator
from app.core.module import ModuleManager
from app.helper.serviceconfig import ServiceConfigHelper
from app.schemas import ServiceInfo
from app.schemas.types import SystemConfigKey

TConf = TypeVar("TConf")

class ServiceBaseHelper(Generic[TConf]):
    """
    通用服务帮助类，抽象获取配置和服务实例的通用逻辑
    """

    def __init__(self, config_key: SystemConfigKey, conf_type: Type[TConf], modules: List[str]):
        self.modulemanager = ModuleManager()
        self.config_key = config_key
        self.conf_type = conf_type
        self.modules = modules

    def get_configs(self, include_disabled: bool = False) -> Dict[str, TConf]:
        """
        获取配置列表
        """
        configs: List[TConf] = ServiceConfigHelper.get_configs(self.config_key, self.conf_type)
        return {
            config.name: config
            for config in configs
            if (config.name and config.type and config.enabled) or include_disabled
        } if configs else {}

    def get_config(self, name: str) -> Optional[TConf]:
        """
        获取指定名称配置
        """
        if not name:
            return None
        configs = self.get_configs()
        return configs.get(name)

    def iterate_module_instances(self) -> Iterator[ServiceInfo]:
        """
        迭代所有模块的实例及其对应的配置，返回 ServiceInfo 实例
        """
        configs = self.get_configs()
        for module_name in self.modules:
            module = self.modulemanager.get_running_module(module_name)
            if not module:
                continue
            module_instances = module.get_instances()
            if not isinstance(module_instances, dict):
                continue
            for name, instance in module_instances.items():
                if not instance:
                    continue
                config = configs.get(name)
                service_info = ServiceInfo(
                    name=name,
                    instance=instance,
                    module=module,
                    type=config.type if config else None,
                    config=config
                )
                yield service_info

    def get_services(self, type_filter: Optional[str] = None) -> Dict[str, ServiceInfo]:
        """
        获取服务信息列表，并根据类型过滤
        """
        return {
            service_info.name: service_info
            for service_info in self.iterate_module_instances()
            if service_info.config and (type_filter is None or service_info.type == type_filter)
        }

    def get_service(self, name: str, type_filter: Optional[str] = None) -> Optional[ServiceInfo]:
        """
        获取指定名称的服务信息，并根据类型过滤
        """
        if not name:
            return None
        for service_info in self.iterate_module_instances():
            if service_info.name == name:
                if service_info.config and (type_filter is None or service_info.type == type_filter):
                    return service_info
        return None
```

### 2.2 特定服务的帮助类

以下是针对不同服务类型的帮助类，这些类继承自 `ServiceBaseHelper`，并预设了特定的配置。

#### `DownloaderHelper`
用于管理下载器服务。

```python
from app.helper.servicebase import ServiceBaseHelper
from app.schemas import DownloaderConf
from app.schemas.types import SystemConfigKey

class DownloaderHelper(ServiceBaseHelper[DownloaderConf]):
    """
    下载器帮助类
    """

     def init_plugin(self, config: dict = None):
        super().__init__(
            config_key=SystemConfigKey.Downloaders,
            conf_type=DownloaderConf,
            modules=["QbittorrentModule", "TransmissionModule"]
        )
```

#### `MediaServerHelper`
用于管理媒体服务器服务。

```python
from app.helper.servicebase import ServiceBaseHelper
from app.schemas import MediaServerConf
from app.schemas.types import SystemConfigKey

class MediaServerHelper(ServiceBaseHelper[MediaServerConf]):
    """
    媒体服务器帮助类
    """

     def init_plugin(self, config: dict = None):
        super().__init__(
            config_key=SystemConfigKey.MediaServers,
            conf_type=MediaServerConf,
            modules=["PlexModule", "EmbyModule", "JellyfinModule"]
        )
```

#### `NotificationHelper`
用于管理消息通知服务。

```python
from app.helper.servicebase import ServiceBaseHelper
from app.schemas import NotificationConf
from app.schemas.types import SystemConfigKey

class NotificationHelper(ServiceBaseHelper[NotificationConf]):
    """
    消息通知帮助类
    """

     def init_plugin(self, config: dict = None):
        super().__init__(
            config_key=SystemConfigKey.Notifications,
            conf_type=NotificationConf,
            modules=["WechatModule", "WebPushModule", "VoceChatModule", "TelegramModule", "SynologyChatModule", "SlackModule"]
        )
```

### 2.3 在插件中使用服务帮助类

通过这些帮助类，插件可以方便地获取和管理各种服务。以下是具体的使用示例。

#### 获取下载器选项

插件可以通过 `DownloaderHelper` 获取所有可用的下载器配置，并生成选项列表供用户选择。

```python
# 假设在插件的某个类中
from app.helper import DownloaderHelper

class MyPlugin:
     def init_plugin(self, config: dict = None):
        self.downloaderhelper = DownloaderHelper()
        self.downloader_options = [
            {"title": config.name, "value": config.name}
            for config in self.downloaderhelper.get_configs().values()
        ]
```

#### 获取特定下载器服务

根据用户选择的下载器名称，插件可以获取对应的服务实例，并执行相应的操作。

```python
from typing import Optional, Union
from app.helper import DownloaderHelper
from app.modules import Transmission, Qbittorrent  # 假设这些是具体的下载器类

class MyPlugin:
    def init_plugin(self, config: dict = None):
        self.downloaderhelper = DownloaderHelper()
        self._downloader = None

    def set_downloader(self, downloader_name: str):
        self._downloader = self.downloaderhelper.get_service(name=downloader_name)

    def __get_downloader(self) -> Optional[Union[Transmission, Qbittorrent]]:
        """
        获取下载器实例
        """
        if not self._downloader:
            return None
        return self._downloader.instance

    def __get_downloader_type(self) -> Optional[str]:
        """
        获取下载器类型
        """
        if not self._downloader:
            return None
        return self._downloader.type

    def __is_qbittorrent(self) -> bool:
        """
        判断下载器是否为 qbittorrent
        """
        if not self._downloader:
            return False
        return self._downloader.type == "qbittorrent"

    def __is_transmission(self) -> bool:
        """
        判断下载器是否为 transmission
        """
        if not self._downloader:
            return False
        return self._downloader.type == "transmission"
```

#### 获取媒体服务器服务

类似地，插件可以通过 `MediaServerHelper` 获取媒体服务器相关的服务信息。

```python
from app.helper import MediaServerHelper

class MyPlugin:
     def init_plugin(self, config: dict = None):
        self.mediaserverhelper = MediaServerHelper()
        self.mediaserver_options = [
            {"title": config.name, "value": config.name}
            for config in self.mediaserverhelper.get_configs().values()
        ]

    def get_media_server_instance(self, server_name: str):
        service_info = self.mediaserverhelper.get_service(name=server_name)
        if service_info:
            return service_info.instance
        return None
```

#### 获取消息通知服务

通过 `NotificationHelper`，插件可以发送消息通知。

```python
from app.helper import NotificationHelper

class MyPlugin:
     def init_plugin(self, config: dict = None):
        self.notificationhelper = NotificationHelper()

    def get_notify_service_instance(self, name: str, message: str):
        service_info = self.notificationhelper.get_service(name=name)
         if service_info:
            return service_info.instance
        return None
```

### 2.4 服务封装的优势

- **统一管理**：通过 `ServiceBaseHelper`，不同类型的服务配置和实例管理变得统一和简洁。
- **灵活扩展**：新增服务类型时，只需创建相应的帮助类，无需修改现有逻辑。
- **便捷调用**：插件可以轻松获取所需的服务实例，简化了服务的调用过程。

### 2.5 从V1升级到V2的注意事项

- **使用帮助类**：尝试在插件中使用了新的服务帮助类，如 `DownloaderHelper`、`MediaServerHelper`、`NotificationHelper` 等，而不是直接操作服务实例。
- **更新依赖**：检查并更新 `requirements.txt` 中的依赖，确保与V2的服务封装兼容。
- **测试插件**：在V2环境中全面测试插件，确保所有服务调用正常工作。