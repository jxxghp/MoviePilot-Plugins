# 如何通过插件扩展支持的存储类型？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 `v2.4.4+` 版本）**
- 1. 用户在系统设定存储中新增自定义存储，并设定一个自定义类型和名称，该类型与插件绑定，用于插件判断使用。或者在插件启动时直接注册自定义存储。
```python
# 检查是否有xxx网盘选项，如没有则自动添加
storage_helper = StorageHelper()
storages = StorageHelper().get_storagies()
if not any(s.type == "xxx" for s in storages):
    # 添加存储配置
    storage_helper.add_storage("xxx", name="xxx网盘", conf={})
```
- 2. 在插件的存储操作类中，实现以下对应的文件操作（具体可参考：`app/modules/filemanager/storages/__init__.py`），不支持的可跳过
```python
class XxxApi:

    def list(self, fileitem: schemas.FileItem) -> List[schemas.FileItem]:
        """
        浏览文件
        """
        pass

    def create_folder(self, fileitem: schemas.FileItem, name: str) -> Optional[schemas.FileItem]:
        """
        创建目录
        :param fileitem: 父目录
        :param name: 目录名
        """
        pass

    def get_folder(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取目录，如目录不存在则创建
        """
        pass

    def get_item(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取文件或目录，不存在返回None
        """
        pass

    def get_parent(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取父目录
        """
        return self.get_item(Path(fileitem.path).parent)

    def delete(self, fileitem: schemas.FileItem) -> bool:
        """
        删除文件
        """
        pass

    def rename(self, fileitem: schemas.FileItem, name: str) -> bool:
        """
        重命名文件
        """
        pass

    def download(self, fileitem: schemas.FileItem, path: Path = None) -> Path:
        """
        下载文件，保存到本地，返回本地临时文件地址
        :param fileitem: 文件项
        :param path: 文件保存路径
        """
        pass

    def upload(self, fileitem: schemas.FileItem, path: Path, new_name: Optional[str] = None) -> Optional[schemas.FileItem]:
        """
        上传文件
        :param fileitem: 上传目录项
        :param path: 本地文件路径
        :param new_name: 上传后文件名
        """
        pass

    def detail(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取文件详情
        """
        pass

    def copy(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        复制文件
        :param fileitem: 文件项
        :param path: 目标目录
        :param new_name: 新文件名
        """
        pass

    def move(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        移动文件
        :param fileitem: 文件项
        :param path: 目标目录
        :param new_name: 新文件名
        """
        pass

    def link(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        硬链接文件
        """
        pass

    def softlink(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        软链接文件
        """
        pass

    def usage(self) -> Optional[schemas.StorageUsage]:
        """
        存储使用情况
        """
        pass
```
- 3. 实现 `ChainEventType.StorageOperSelection`链式事件响应，根据传入的存储对象名称判断是否为该插件支持的存储，如是则返回存储操作对象
```python
@eventmanager.register(ChainEventType.StorageOperSelection)
def storage_oper_selection(self, event: Event):
    """
    监听存储选择事件，返回当前类为操作对象
    """
    if not self._enabled:
        return
    event_data: StorageOperSelectionEventData = event.event_data
    if event_data.storage == "xxx":
        event_data.storage_oper = self.api # api为插件的存储操作对象
```

- 4. 参考 [《如何通过插件重载实现系统模块功能？》](./11-override-system-module.md) 实现 `get_module`，在插件中声明和实现以下模块方法（具体可参考：`app/modules/filemanager/__init__.py`），其实就是对上一步的方法再做一下封装：
```python
def get_module(self) -> Dict[str, Any]:
    """
    获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）
    {
        "id1": self.xxx1,
        "id2": self.xxx2,
    }
    """
    return {
        "list_files": self.list_files,
        "any_files": self.any_files,
        "download_file": self.download_file,
        "upload_file": self.upload_file,
        "delete_file": self.delete_file,
        "rename_file": self.rename_file,
        "get_file_item": self.get_file_item,
        "get_parent_item": self.get_parent_item,
        "snapshot_storage": self.snapshot_storage,
        "storage_usage": self.storage_usage,
        "support_transtype": self.support_transtype
    }

def list_files(self, fileitem: schemas.FileItem, recursion: bool = False) -> Optional[List[schemas.FileItem]]:
    """
    查询当前目录下所有目录和文件
    """
    
    if fileitem.storage != "xxx":
        return None

    def __get_files(_item: FileItem, _r: Optional[bool] = False):
        """
        递归处理
        """
        _items = self.api.list(_item)
        if _items:
            if _r:
                for t in _items:
                    if t.type == "dir":
                        __get_files(t, _r)
                    else:
                        result.append(t)
            else:
                result.extend(_items)

    # 返回结果
    result = []
    __get_files(fileitem, recursion)

    return result

def any_files(self, fileitem: schemas.FileItem, extensions: list = None) -> Optional[bool]:
    """
    查询当前目录下是否存在指定扩展名任意文件
    """
    if fileitem.storage != "xxx":
        return None
    
    def __any_file(_item: FileItem):
        """
        递归处理
        """
        _items = self.api.list(_item)
        if _items:
            if not extensions:
                return True
            for t in _items:
                if (t.type == "file"
                        and t.extension
                        and f".{t.extension.lower()}" in extensions):
                    return True
                elif t.type == "dir":
                    if __any_file(t):
                        return True
        return False

    # 返回结果
    return __any_file(fileitem)

def download_file(self, fileitem: schemas.FileItem, path: Path = None) -> Optional[Path]:
    """
    下载文件
    :param fileitem: 文件项
    :param path: 本地保存路径
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.download(fileitem, path)

def upload_file(self, fileitem: schemas.FileItem, path: Path,
                new_name: Optional[str] = None) -> Optional[schemas.FileItem]:
    """
    上传文件
    :param fileitem: 保存目录项
    :param path: 本地文件路径
    :param new_name: 新文件名
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.upload(fileitem, path, new_name)

def delete_file(self, fileitem: schemas.FileItem) -> Optional[bool]:
    """
    删除文件或目录
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.delete(fileitem)

def rename_file(self, fileitem: schemas.FileItem, name: str) -> Optional[bool]:
    """
    重命名文件或目录
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.rename(fileitem, name)

def get_file_item(self, storage: str, path: Path) -> Optional[schemas.FileItem]:
    """
    根据路径获取文件项
    """
    if storage != "xxx":
        return None
    
    return self.api.get_item(path)

def get_parent_item(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
    """
    获取上级目录项
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.get_parent(fileitem)

def snapshot_storage(self, storage: str, path: Path) -> Optional[Dict[str, float]]:
    """
    快照存储
    """
    if storage != "xxx":
        return None
    
    files_info = {}

    def __snapshot_file(_fileitm: schemas.FileItem):
        """
        递归获取文件信息
        """
        if _fileitm.type == "dir":
            for sub_file in self.api.list(_fileitm):
                __snapshot_file(sub_file)
        else:
            files_info[_fileitm.path] = _fileitm.size

    fileitem = self.api.get_item(path)
    if not fileitem:
        return {}

    __snapshot_file(fileitem)

    return files_info

def storage_usage(self, storage: str) -> Optional[schemas.StorageUsage]:
    """
    存储使用情况
    """
    return self.api.usage()

@staticmethod
def support_transtype(storage: str) -> Optional[dict]:
    """
    获取支持的整理方式
    """
    return {
        "move": "移动",
        "copy": "复制"
    }
```
