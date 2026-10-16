"""插件运行数据存储能力的调用侧契约。"""


class StoreInitializationError(RuntimeError):
    """PluginData 初始化或版本校验失败。"""


from .storage import PluginDataStore

__all__ = ["PluginDataStore", "StoreInitializationError"]
