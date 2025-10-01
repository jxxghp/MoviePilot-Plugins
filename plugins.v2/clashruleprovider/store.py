from typing import Any, Optional

from app.db.plugindata_oper import PluginDataOper


class PluginStore:
    """数据持久化"""
    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.plugin_data = PluginDataOper()

    def get_data(self, key: Optional[str] = None) -> Any:
        return self.plugin_data.get_data(self.plugin_id, key)

    def save_data(self, key: str, value: Any):
        self.plugin_data.save(self.plugin_id, key, value)

    def del_data(self, key: str) -> Any:
        self.plugin_data.del_data(self.plugin_id, key)
