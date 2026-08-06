from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.event import Event, eventmanager
from app.core.plugin import PluginManager
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.event import ResourceDownloadEventData, ResourceSelectionEventData
from app.schemas.types import ChainEventType


class HRBlocker(_PluginBase):
    # 插件名称
    plugin_name = "H&R Blocker"
    # 插件描述
    plugin_desc = "屏蔽所有带H&R的种子，搜索、订阅等任何场景都不会选中H&R种子。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/ltdstudio/hrblocker/main/icons/hrblocker.png"
    # 插件版本
    plugin_version = "1.1.3"
    # 插件作者
    plugin_author = "ltdstudio"
    # 作者主页
    author_url = "https://github.com/ltdstudio/hrblocker"
    # 插件配置项ID前缀
    plugin_config_prefix = "hrblocker_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    # 屏蔽站点标记为H&R的种子（逐种子标记）
    _block_marked = True
    # 联动 H&R助手：屏蔽已激活全站H&R的站点
    _sync_assistant = True
    # 手动下载也拦截（兜底，任何场景都不放过）
    _block_manual = True
    # 拦截时发送通知
    _notify = False
    # 屏蔽记录（最新在前，上限100条）
    _records: List[Dict[str, Any]] = []
    # 记录保留条数
    MAX_RECORDS = 100

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._block_marked = config.get("block_marked", True)
            self._sync_assistant = config.get("sync_assistant", True)
            self._block_manual = config.get("block_manual", True)
            self._notify = config.get("notify", False)
            self.update_config({
                "enabled": self._enabled,
                "block_marked": self._block_marked,
                "sync_assistant": self._sync_assistant,
                "block_manual": self._block_manual,
                "notify": self._notify,
            })
        # 加载历史屏蔽记录
        self._records = self.get_data("records") or []
        if self._enabled:
            hr_sites = self.__get_hr_active_sites()
            logger.info(f"【{self.plugin_name}】已启用，逐种子H&R标记屏蔽：{'开' if self._block_marked else '关'}，"
                        f"联动H&R助手全站H&R屏蔽：{'开' if self._sync_assistant else '关'}"
                        f"（当前 {len(hr_sites)} 个全站H&R站点），"
                        f"手动下载拦截：{'开' if self._block_manual else '关'}")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "summary": "H&R Blocker状态",
                "description": "查看当前生效配置及联动解析出的全站H&R站点清单",
            },
            {
                "path": "/records",
                "endpoint": self.api_records,
                "methods": ["GET"],
                "summary": "屏蔽记录",
                "description": "查看最近屏蔽的H&R种子记录（最多100条）",
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'block_marked',
                                            'label': '屏蔽H&R标记种子',
                                            'hint': '屏蔽站点搜索结果中带有H&R标记的种子',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'sync_assistant',
                                            'label': '联动H&R助手',
                                            'hint': '屏蔽H&R助手配置中已激活全站H&R的站点（该站所有种子均视为H&R）',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'block_manual',
                                            'label': '拦截手动下载',
                                            'hint': '手动下载H&R种子时同样拦截（关闭则仅自动选择场景生效）',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '拦截通知',
                                            'hint': '拦截H&R种子时发送消息通知',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '工作方式：在「资源选择」阶段从候选列表中剔除H&R种子（订阅、搜索择优、豆瓣同步等自动场景均生效），'
                                                    '并在「实际下载」前二次兜底拦截。H&R判定来源：①站点搜索结果中的H&R标记；'
                                                    '②H&R助手配置中 hr_active 已激活的全站H&R站点（需已安装并配置H&R助手）。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "block_marked": True,
            "sync_assistant": True,
            "block_manual": True,
            "notify": False,
        }

    def get_page(self) -> List[dict]:
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """声明插件使用 Vue 联邦组件渲染详情页（屏蔽记录面板）。"""
        return "vue", "dist/assets"

    def stop_service(self):
        pass

    # region 事件处理

    @eventmanager.register(ChainEventType.ResourceSelection)
    def on_resource_selection(self, event: Event = None):
        """
        资源选择事件：从候选资源列表中剔除H&R种子
        覆盖订阅、消息搜索、豆瓣同步等所有自动择优下载场景
        """
        if not self._enabled or not event or not event.event_data:
            return
        try:
            data: ResourceSelectionEventData = event.event_data
            # 尊重前面已处理过该事件的插件结果
            if data.updated and data.updated_contexts is not None:
                contexts = data.updated_contexts
            else:
                contexts = data.contexts or []
            if not contexts:
                return
            kept, blocked = [], []
            for context in contexts:
                is_hr, reason = self.__is_hr_context(context)
                if is_hr:
                    blocked.append((context, reason))
                else:
                    kept.append(context)
            if not blocked:
                return
            data.updated = True
            data.updated_contexts = kept
            data.source = self.plugin_name
            origin = data.origin or "未知来源"
            for context, reason in blocked:
                title = getattr(context.torrent_info, "title", "") if context.torrent_info else ""
                site_name = getattr(context.torrent_info, "site_name", "") if context.torrent_info else ""
                self.__add_record(title=title, site=site_name, reason=reason,
                                  source=origin, stage="资源选择")
                logger.info(f"【{self.plugin_name}】已从候选中剔除H&R种子：{title}"
                            f"{'（站点：' + site_name + '）' if site_name else ''}，原因：{reason}，来源：{origin}")
            logger.info(f"【{self.plugin_name}】本次共剔除 {len(blocked)} 个H&R种子，剩余 {len(kept)} 个候选，来源：{origin}")
            if self._notify:
                lines = [f"来源：{origin}", f"已剔除 {len(blocked)} 个H&R种子："]
                for context, reason in blocked[:10]:
                    title = getattr(context.torrent_info, "title", "") if context.torrent_info else ""
                    lines.append(f"· {title}（{reason}）")
                if len(blocked) > 10:
                    lines.append(f"· 等共 {len(blocked)} 个")
                self.post_message(mtype=NotificationType.Subscribe,
                                  title=f"【{self.plugin_name}】拦截H&R种子",
                                  text="\n".join(lines))
        except Exception as e:
            logger.error(f"【{self.plugin_name}】资源选择事件处理异常：{e}")

    @eventmanager.register(ChainEventType.ResourceDownload)
    def on_resource_download(self, event: Event = None):
        """
        资源下载事件：实际下载前兜底拦截H&R种子（含手动下载）
        """
        if not self._enabled or not event or not event.event_data:
            return
        try:
            data: ResourceDownloadEventData = event.event_data
            origin = data.origin or ""
            # 手动下载可配置豁免
            if origin.lower() == "manual" and not self._block_manual:
                return
            context = data.context
            if not context or not context.torrent_info:
                return
            is_hr, reason = self.__is_hr_context(context)
            if not is_hr:
                return
            title = getattr(context.torrent_info, "title", "")
            site_name = getattr(context.torrent_info, "site_name", "")
            data.cancel = True
            data.source = self.plugin_name
            data.reason = f"H&R种子已屏蔽（{reason}）"
            self.__add_record(title=title, site=site_name, reason=reason,
                              source=origin or "未知来源", stage="下载拦截")
            logger.info(f"【{self.plugin_name}】已拦截H&R种子下载：{title}"
                        f"{'（站点：' + site_name + '）' if site_name else ''}，原因：{reason}，来源：{origin or '未知来源'}")
            if self._notify:
                self.post_message(mtype=NotificationType.Subscribe,
                                  title=f"【{self.plugin_name}】拦截H&R种子下载",
                                  text=f"种子：{title}\n站点：{site_name}\n原因：{reason}\n来源：{origin or '未知来源'}")
        except Exception as e:
            logger.error(f"【{self.plugin_name}】资源下载事件处理异常：{e}")

    # endregion

    # region 私有方法

    def __add_record(self, title: str, site: str, reason: str, source: str, stage: str):
        """
        追加一条屏蔽记录（最新在前，上限 MAX_RECORDS 条，持久化到插件数据）
        """
        try:
            self._records.insert(0, {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "title": title or "未知种子",
                "site": site or "",
                "reason": reason or "",
                "source": source or "",
                "stage": stage or "",
            })
            del self._records[self.MAX_RECORDS:]
            self.save_data("records", self._records)
        except Exception as e:
            logger.error(f"【{self.plugin_name}】保存屏蔽记录失败：{e}")

    def __is_hr_context(self, context) -> Tuple[bool, str]:
        """
        判定资源上下文是否为H&R种子
        :return: (是否H&R, 原因描述)
        """
        torrent = context.torrent_info if context else None
        if not torrent:
            return False, ""
        # 1. 站点搜索结果中逐种子解析出的H&R标记
        if self._block_marked and getattr(torrent, "hit_and_run", False):
            return True, "站点标记H&R"
        # 2. 联动H&R助手：站点已激活全站H&R，则该站所有种子均视为H&R
        if self._sync_assistant:
            hr_sites = self.__get_hr_active_sites()
            site_id = getattr(torrent, "site", None)
            if site_id and site_id in hr_sites:
                return True, "站点已激活全站H&R"
        return False, ""

    @staticmethod
    def __get_hr_active_sites() -> Dict[int, str]:
        """
        解析H&R助手（HitAndRun插件）配置，返回已激活全站H&R的站点 {站点ID: 站点名}
        语义与H&R助手一致：站点独立配置中的 hr_active 优先，未配置的站点回落到全局 hr_active
        """
        result: Dict[int, str] = {}
        try:
            conf = PluginManager().get_plugin_config("HitAndRun")
            if not conf:
                return result
            managed_site_ids = set(conf.get("sites") or [])
            if not managed_site_ids:
                return result
            global_active = bool(conf.get("hr_active"))
            site_configs = conf.get("site_configs") or {}
            use_site_config = bool(conf.get("enable_site_config")) and bool(site_configs)
            # 站点ID -> 站点名 映射
            id_name_map: Dict[int, str] = {}
            try:
                for site in SiteOper().list():
                    if site and site.id is not None:
                        id_name_map[site.id] = site.name
            except Exception as e:
                logger.warning(f"【HRBlocker】获取站点列表失败：{e}")
            for site_id in managed_site_ids:
                site_name = id_name_map.get(site_id)
                if not site_name:
                    continue
                active = global_active
                if use_site_config:
                    cfg = site_configs.get(site_name)
                    if cfg is not None:
                        cfg_active = cfg.get("hr_active") if isinstance(cfg, dict) else getattr(cfg, "hr_active", None)
                        # hr_active 为 None 时与H&R助手合并逻辑一致：回落全局配置
                        active = global_active if cfg_active is None else bool(cfg_active)
                if active:
                    result[site_id] = site_name
        except Exception as e:
            logger.error(f"【HRBlocker】解析H&R助手配置失败：{e}")
        return result

    def api_records(self) -> Dict[str, Any]:
        """
        返回屏蔽记录（最新在前，最多100条；直接读插件数据，保证插件重载后也不丢）
        """
        records = self.get_data("records")
        if records is None:
            records = self._records or []
        return {
            "total": len(records),
            "max_records": self.MAX_RECORDS,
            "records": records,
        }

    def api_status(self) -> Dict[str, Any]:
        """
        查看当前状态及联动解析出的全站H&R站点清单
        """
        hr_sites = self.__get_hr_active_sites() if self._sync_assistant else {}
        pm = PluginManager()
        assistant_conf = pm.get_plugin_config("HitAndRun")
        return {
            "version": self.plugin_version,
            "enabled": self._enabled,
            "block_marked": self._block_marked,
            "sync_assistant": self._sync_assistant,
            "block_manual": self._block_manual,
            "notify": self._notify,
            "assistant_installed": bool(pm.plugins.get("HitAndRun")),
            "assistant_configured": bool(assistant_conf),
            "hr_active_sites": [{"id": sid, "name": name} for sid, name in hr_sites.items()],
        }

    # endregion
