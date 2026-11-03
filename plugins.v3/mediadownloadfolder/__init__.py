"""下载提交前按当前整理格式归组影视作品目录。"""

from typing import Any

from app.modules.filemanager.transhandler import TransHandler
from app.schemas.event import ResourceDownloadEventData
from app.schemas.system import TransferDirectoryConf
from app.schemas.types import ChainEventType, MediaType, SystemConfigKey
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.media import MetaInfo
from app.sdk.plugin import _PluginBase
from sqlalchemy.exc import SQLAlchemyError

from .naming import render_media_folder, validate_media_template
from .paths import (
    build_save_path,
    directory_reference,
    parse_reference,
    resolve_directory,
)


class MediaDownloadFolder(_PluginBase):
    """只修改下载前的 save_path；默认关闭且按用户显式选择的根目录生效。"""

    plugin_name = "媒体下载目录"
    plugin_desc = "按整理命名格式把同一影视作品的下载归入一个目录。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.0"
    plugin_author = "cwd0204"
    author_url = "https://github.com/cwd0204"
    plugin_config_prefix = "mediadownloadfolder_"
    plugin_order = 50
    auth_level = 1

    def __init__(self) -> None:
        """建立实例独立的配置状态，不启动后台任务。"""
        super().__init__()
        self._enabled = False
        self._roots: dict[MediaType, str | None] = {}
        self._last_error = ""

    def init_plugin(self, config: dict | None = None) -> None:
        """完整替换本实例配置，重复初始化不重复订阅事件。"""
        config = config or {}
        self._enabled = config.get("enabled") is True
        self._roots = {
            MediaType.MOVIE: config.get("movie_root"),
            MediaType.TV: config.get("tv_root"),
        }
        self._last_error = ""

    def get_state(self) -> bool:
        """返回用户设置的启用状态。"""
        return self._enabled

    def get_api(self) -> list[dict[str, Any]]:
        """配置由宿主管理，本插件不添加独立 API。"""
        return []

    def _directories(self) -> list[TransferDirectoryConf]:
        """读取当前宿主目录配置，不缓存或改写宿主设置。"""
        raw = self.systemconfig.get(SystemConfigKey.Directories) or []
        if not isinstance(raw, list):
            raise TypeError("宿主下载目录配置无法读取")
        return [TransferDirectoryConf.model_validate(item) for item in raw]

    @eventmanager.register(ChainEventType.ResourceDownload)
    def on_resource_download(self, event: Event = None) -> None:
        """在默认路径或所选根目录请求中设置完整作品目录，保留其它事件字段。"""
        if not self._enabled or not event or not event.event_data:
            return
        data: ResourceDownloadEventData = event.event_data
        if data.cancel:
            return
        context = data.context
        media = getattr(context, "media_info", None)
        roots = self._roots
        if not media or media.type not in roots or not getattr(media, "title", None):
            return
        selected = roots[media.type]
        if not selected:
            return
        try:
            reference = parse_reference(selected)
            save_path = (data.options or {}).get("save_path")
            if save_path is not None and str(save_path).strip() not in {"", reference.uri}:
                return
            directory = resolve_directory(selected, self._directories())
            naming = TransHandler.get_naming_dict(MetaInfo(""), media)
            folder = render_media_folder(self.chain.runtime_config.rename_format(media.type), naming)
            path = build_save_path(directory, media, folder)
        except ValueError as error:
            self._cancel(data, str(error))
            return
        except (RuntimeError, TypeError, OSError, SQLAlchemyError) as error:
            # 宿主通常隔离插件异常；这里明确取消，避免启用后错误被当作成功归组。
            self._cancel(data, "无法读取目录或命名配置，请检查插件设置")
            logger.error(f"【{self.plugin_name}】读取配置失败：{type(error).__name__}")
            return
        if data.options is None:
            data.options = {}
        data.options["save_path"] = path
        self._last_error = ""

    def _cancel(self, data: ResourceDownloadEventData, reason: str) -> None:
        """取消当前适用请求并保留可在插件详情页查看的错误。"""
        self._last_error = reason
        data.cancel = True
        data.source = self.plugin_name
        data.reason = reason
        logger.warning(f"【{self.plugin_name}】{reason}")

    def _status(self) -> list[str]:
        """检查引用与模板结构，返回配置错误及最近的运行错误。"""
        errors = []
        try:
            directories = self._directories()
            for media_type, selected in self._roots.items():
                if selected:
                    resolve_directory(selected, directories)
                    validate_media_template(self.chain.runtime_config.rename_format(media_type))
        except (ValueError, RuntimeError, TypeError, OSError, SQLAlchemyError) as error:
            errors.append(str(error) if isinstance(error, ValueError) else "无法读取目录或命名配置")
        if self._last_error and self._last_error not in errors:
            errors.append(self._last_error)
        return errors

    def get_form(self) -> tuple[list[dict], dict[str, Any]]:
        """提供现有根目录选择器，说明作用范围并展示失效配置。"""
        items = []
        warnings = []
        try:
            for directory in self._directories():
                if not directory.download_path:
                    continue
                try:
                    value = directory_reference(directory)
                except ValueError:
                    continue
                items.append({
                    "title": f"{directory.name or '未命名目录'} · {directory.storage or 'local'}:{directory.download_path}",
                    "value": value,
                })
        except (ValueError, RuntimeError, TypeError, OSError, SQLAlchemyError):
            warnings.append("无法读取宿主下载目录配置")
        warnings.extend(self._status())
        for selected in self._roots.values():
            if not selected or any(item["value"] == selected for item in items):
                continue
            try:
                reference = parse_reference(selected)
                label = f"{reference.name or '未命名目录'} · {reference.uri}"
            except ValueError:
                label = "目录引用无效"
            items.append({
                "title": f"{label}（已失效，请重新选择）", "value": selected,
                "props": {"disabled": True},
            })
        content = [
            {"component": "VSwitch", "props": {"model": "enabled", "label": "启用媒体下载目录"}},
            {"component": "VAlert", "props": {
                "type": "info", "variant": "tonal", "class": "mb-4",
                "text": "分别选择已有下载根目录。仅未指定保存路径或明确使用该根目录的下载会归组；其它目录、自定义子目录和目录别名保持原行为。未选择的媒体类型不处理。",
            }},
        ]
        for key, label in (("movie_root", "电影下载根目录"), ("tv_root", "电视剧下载根目录")):
            content.append({"component": "VSelect", "props": {
                "model": key, "label": label, "items": items, "clearable": True,
                "hint": "目录改名、删除或路径变化后，请重新选择。", "persistent-hint": True,
                "class": "mb-4",
            }})
        content.append({"component": "VAlert", "props": {
            "type": "info", "variant": "tonal",
            "text": "作品目录复用当前整理格式中的标题目录，保留所选根的类型、分类开关。格式必须只引用作品标题、年份或来源 ID。启用后适用请求若配置失效会取消下载；不会移动既有任务或修改历史。",
        }})
        content.extend({"component": "VAlert", "props": {
            "type": "warning", "variant": "tonal", "text": warning, "class": "mt-3",
        }} for warning in dict.fromkeys(warnings))
        return [{"component": "VForm", "content": content}], {
            "enabled": False, "movie_root": None, "tv_root": None,
        }

    def get_page(self) -> list[dict]:
        """显示启用范围和配置错误，不展示或修改下载历史。"""
        errors = self._status()
        page = [{"component": "VAlert", "props": {
            "type": "info", "variant": "tonal",
            "text": "已启用媒体下载目录" if self._enabled else "媒体下载目录已停用",
        }}]
        for media_type, selected in self._roots.items():
            if not selected:
                description = f"{media_type.value}：未选择根目录，不处理"
            else:
                try:
                    reference = parse_reference(selected)
                    description = f"{media_type.value}：{reference.name or '未命名目录'} · {reference.uri}"
                except ValueError:
                    description = f"{media_type.value}：目录引用无效，请重新选择"
            page.append({"component": "VAlert", "props": {
                "type": "info", "variant": "tonal", "class": "mt-3", "text": description,
            }})
        page.extend({"component": "VAlert", "props": {
            "type": "warning", "variant": "tonal", "text": error, "class": "mt-3",
        }} for error in errors)
        return page

    def stop_service(self) -> None:
        """停止事件处理；没有需要释放的线程、计划任务或网络连接。"""
        self._enabled = False
