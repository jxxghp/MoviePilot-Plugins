"""在公开资源事件中应用永久种子黑名单。"""

from app.schemas.event import ResourceDownloadEventData, ResourceSelectionEventData
from app.schemas.types import ChainEventType
from app.sdk.events import Event, eventmanager
from app.sdk.plugin import _PluginBase

from .api import BlacklistApi
from .rules import matches
from .store import RuleStore


class TorrentBlacklist(_PluginBase):
    plugin_name = "种子黑名单"
    plugin_desc = "按关键词、站点或下载历史的同站同名种子永久屏蔽下载。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.0"
    plugin_author = "cwd0204"
    author_url = "https://github.com/cwd0204"
    plugin_config_prefix = "torrentblacklist_"
    plugin_order = 20
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._enabled = False
        # 同一运行实例的锁跨 init_plugin 保留；分身由 SDK 使用各自实例 ID 存储。
        self._store = RuleStore(self)
        self._api = BlacklistApi(self._store)

    def init_plugin(self, config: dict | None = None):
        self._enabled = (config or {}).get("enabled") is True
        self._store.reload()

    def get_state(self):
        return self._enabled

    def get_api(self):
        return self._api.routes()

    def get_form(self):
        return [], {"enabled": self._enabled}

    def get_page(self):
        return []

    @staticmethod
    def get_render_mode():
        return "vue", "dist/assets"

    def stop_service(self):
        pass

    @eventmanager.register(ChainEventType.ResourceSelection)
    def on_resource_selection(self, event: Event = None):
        if not self._enabled or event is None:
            return
        data = event.event_data
        if not isinstance(data, ResourceSelectionEventData):
            return
        document, error = self._store.snapshot()
        if error:
            # 管理页显示错误，最终下载入口取消；不改写无法判断的候选结果。
            return
        contexts = data.updated_contexts if data.updated and data.updated_contexts is not None else data.contexts
        if not contexts:
            return
        kept = [context for context in contexts if not any(
            matches(rule, getattr(context, "torrent_info", None)) for rule in document.entries
        )]
        if len(kept) == len(contexts):
            return
        data.updated_contexts = kept
        data.updated = True
        data.source = self.plugin_name

    @eventmanager.register(ChainEventType.ResourceDownload)
    def on_resource_download(self, event: Event = None):
        if not self._enabled or event is None:
            return
        data = event.event_data
        if not isinstance(data, ResourceDownloadEventData) or data.cancel:
            return
        document, error = self._store.snapshot()
        rule = next((rule for rule in document.entries if matches(
            rule, getattr(data.context, "torrent_info", None),
        )), None)
        if error or rule is not None:
            data.cancel = True
            data.source = self.plugin_name
            data.reason = error or f"命中种子黑名单规则 {rule.id[:12]}"
