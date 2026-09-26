"""
目录新增监控刮削 (MediaDirWatcher)

轮询监控指定媒体目录，发现新增电影/剧集/动画片后：
  1. 解析文件名/目录名，识别媒体条目（剧集目录/电影目录/单文件）；
  2. 使用 MoviePilot 原生识别链获取元数据（跟随系统 / 豆瓣 / TMDB 可选）；
  3. 通过 MoviePilot 消息通道发送通知（海报、年份、评分、简介）；
  4. 可选：调用 ScrapingChain 将元数据刮削写入 NFO 与图片。

设计要点：
- 首次扫描只建立基线（记录存量条目，不识别不通知），避免存量媒体刷屏；
- 目录树 mtime 指纹预检：目录无变化时跳过全量扫描，几乎零磁盘 I/O；
- 每处理一条即落盘进度，插件重启不重复通知；
- 条目类型标注优先取路径中的目录分类（如 动画片/纪录片），更贴合库结构。
"""
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, Dict, List, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app import schemas
from app.chain.scraping import ScrapingChain
from app.plugins import _PluginBase
from app.runtime.settings import get_runtime_setting, update_runtime_setting
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.media import MetaInfoPath
from app.sdk.utilities import SystemUtils
from app.schemas import FileItem, MediaType, MessageType

# 文件修改后至少稳定该秒数才视为“已完成”，避免对正在写入/下载的文件误报
STABLE_SECONDS = 180

# 监控目录下常见的分类子目录名：条目路径中出现这些名称时，通知/历史的类型标注
# 直接采用该分类（如 动画片/动漫/纪录片），比识别结果的电影/电视剧更贴合目录分类
CATEGORY_DIRS = {
    "电影", "电视剧", "动画片", "动漫", "动画", "番剧", "纪录片", "综艺",
    "短剧", "剧集", "国产剧", "欧美剧", "日剧", "韩剧", "日番", "国漫",
}

# processed 去重记录的最大条数，超出后按时间淘汰最旧记录，控制数据体积
PROCESSED_LIMIT = 50000

# 插件页面历史记录最大条数
HISTORY_LIMIT = 50


class MediaDirWatcher(_PluginBase):
    """监控目录新增媒体并通知/刮削的插件主类。"""

    # 插件名称
    plugin_name = "目录新增监控刮削"
    # 插件描述
    plugin_desc = "轮询监控指定目录，发现新增电影/剧集/动画片后发送 MP 通知并可选刮削 NFO；支持目录分类标注、首扫建基线防刷屏、指纹预检省磁盘。"
    # 插件图标（仓库 icons/ 目录下）
    plugin_icon = "mediadirwatcher.png"
    # 插件版本（需与 package.v3.json 的 version 及 history 最新版本一致）
    plugin_version = "1.0.2"
    # 插件作者
    plugin_author = "LCQ"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "mediadirwatcher_"
    # 加载顺序
    plugin_order = 20
    # 可使用的用户级别
    user_level = 1

    # 私有属性
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _monitor_paths = ""
    _media_type = ""
    _scrape_source = "system"
    _notify = True
    _write_nfo = False
    _scan_interval = 5
    _notify_user = ""
    # 退出事件
    _event = Event()

    def init_plugin(self, config: dict = None):
        """读取配置并（重）启动后台扫描任务。"""
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._monitor_paths = config.get("monitor_paths") or ""
            self._media_type = config.get("media_type") or ""
            self._scrape_source = config.get("scrape_source") or "system"
            self._notify = config.get("notify", True)
            self._write_nfo = config.get("write_nfo", False)
            self._scan_interval = int(config.get("scan_interval") or 5)
            self._notify_user = config.get("notify_user") or ""

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if self._onlyonce:
                logger.info("目录新增监控，立即运行一次")
                self._scheduler.add_job(
                    func=self.__scan_all,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="目录新增监控",
                )
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "enabled": self._enabled,
                    "onlyonce": False,
                    "monitor_paths": self._monitor_paths,
                    "media_type": self._media_type,
                    "scrape_source": self._scrape_source,
                    "notify": self._notify,
                    "write_nfo": self._write_nfo,
                    "scan_interval": self._scan_interval,
                    "notify_user": self._notify_user,
                })
            else:
                logger.info(f"目录新增监控启动，扫描间隔 {self._scan_interval} 分钟")
                self._scheduler.add_job(
                    func=self.__scan_all,
                    trigger='interval',
                    minutes=self._scan_interval,
                    id="MediaDirWatcher",
                    name="目录新增监控",
                )
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        """插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """远程命令，无。"""
        return None

    def get_api(self) -> List[Dict[str, Any]]:
        """插件自定义 API。"""
        return [{
            "path": "/scan_now",
            "endpoint": self.scan_now,
            "methods": ["POST"],
            "auth": "apikey",
            "summary": "立即扫描一次",
            "description": "立即扫描监控目录，发现并处理新增媒体",
        }]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册系统服务，无（扫描任务由插件自身调度器管理）。"""
        return []

    def get_form(self) -> tuple:
        """插件配置表单（VForm 组件描述）。"""
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {'model': 'enabled', 'label': '启用插件'},
                                }],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {'model': 'onlyonce', 'label': '立即运行一次'},
                                }],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'media_type',
                                        'label': '媒体类型(辅助识别)',
                                        'items': [
                                            {'title': '自动识别', 'value': ''},
                                            {'title': '电影', 'value': '电影'},
                                            {'title': '电视剧', 'value': '电视剧'},
                                        ],
                                    },
                                }],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'scrape_source',
                                        'label': '识别数据源',
                                        'items': [
                                            {'title': '跟随系统设置', 'value': 'system'},
                                            {'title': '豆瓣', 'value': 'douban'},
                                            {'title': 'TMDB', 'value': 'themoviedb'},
                                        ],
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {'model': 'notify', 'label': '新增时MP通知'},
                                }],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {'model': 'write_nfo', 'label': '写入NFO刮削(生成元数据文件)'},
                                }],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'scan_interval',
                                        'label': '扫描间隔(分钟)',
                                        'type': 'number',
                                        'placeholder': '5',
                                    },
                                }],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'notify_user',
                                        'label': '通知接收用户ID(留空=默认)',
                                        'placeholder': '选填',
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [{
                                    'component': 'VTextarea',
                                    'props': {
                                        'model': 'monitor_paths',
                                        'label': '监控目录(每行一个，容器内能访问到的路径)',
                                        'rows': 5,
                                        'placeholder': '/media/磁盘/电影\n/media/磁盘/电视剧',
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [{
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': '路径需为 MoviePilot 容器内能访问到的路径（即已挂载进容器的目录）。'
                                                '首次扫描只建立基线、不会对存量媒体发送通知；之后每轮扫描只处理新增条目。'
                                                '剧集按“剧集文件夹/季文件夹/剧集文件”结构可正确识别为单部剧（不会每集重复通知）。',
                                    },
                                }],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "monitor_paths": "",
            "media_type": "",
            "scrape_source": "system",
            "notify": True,
            "write_nfo": False,
            "scan_interval": 5,
            "notify_user": "",
        }

    def get_page(self) -> List[dict]:
        """插件页面：展示最近发现的历史记录表格。"""
        history = self.get_data("history") or []
        # MP v3 渲染器不支持 VTable 的 headers/items 属性(那是v2 VDataTable风格)，
        # 需手动构建 thead/tbody 结构
        headers = ["标题", "类型", "年份", "是否已识别", "路径", "发现时间"]
        ths = [{'component': 'th', 'text': h} for h in headers]
        rows = []
        for h in history:
            cells = [
                h.get("title") or "-",
                h.get("type") or "-",
                str(h.get("year") or "-"),
                "是" if h.get("recognized") else "未识别",
                h.get("path") or "-",
                h.get("time") or "-",
            ]
            rows.append({
                'component': 'tr',
                'content': [{'component': 'td', 'text': c} for c in cells],
            })
        if not rows:
            rows = [{
                'component': 'tr',
                'content': [{'component': 'td', 'text': '暂无记录，等待发现新增媒体…'}],
            }]
        return [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'density': 'comfortable',
                                    'hover': True,
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [{'component': 'tr', 'content': ths}],
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': rows,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

    # ====================== 后台扫描 ======================
    def __scan_all(self):
        """扫描所有监控目录，发现并处理新增媒体。"""
        if self._event.is_set():
            return
        if not self._monitor_paths:
            logger.info("目录新增监控：未配置监控目录")
            return

        paths = [p.strip() for p in self._monitor_paths.split("\n") if p.strip()]
        processed = self.get_data("processed") or {}
        baselines = self.get_data("baselines") or {}
        # v1.0.2: 键升级为 dirprints_v2, 使 v1.0.1 遗留的错误指纹全部失效
        dirprints = self.get_data("dirprints_v2") or {}
        now = datetime.now().timestamp()

        for base in paths:
            base_path = Path(base)
            if not base_path.exists():
                logger.warning(f"目录新增监控：监控目录不存在 {base}")
                continue

            # mtime 预检：目录树指纹未变化则跳过全量扫描，几乎零 I/O
            sig = self.__dir_signature(base_path)
            if sig and baselines.get(base) and dirprints.get(base) == sig:
                logger.debug(f"目录新增监控：{base} 目录无变化，跳过扫描")
                continue

            logger.info(f"目录新增监控：开始扫描 {base}")
            try:
                files = SystemUtils.list_files(base_path, settings.RMT_MEDIAEXT)
            except Exception as e:
                logger.error(f"目录新增监控：列举文件失败 {base}: {e}")
                continue

            # v1.0.2 修复：本轮若存在"尚未处理的过新文件"，则不固化目录指纹。
            # 否则下轮指纹无变化会跳过扫描，这些文件将被永久遗漏。
            pending_new = False

            # 首次扫描该目录：只建立基线（记录存量，不识别不通知），避免存量媒体刷屏
            if not baselines.get(base):
                baseline_keys = set()
                for file_path in files:
                    if self._event.is_set():
                        logger.info("目录新增监控：服务停止")
                        return
                    try:
                        if now - file_path.stat().st_mtime < STABLE_SECONDS:
                            pending_new = True
                            continue
                    except Exception:
                        continue
                    item_path = self.__item_path(file_path, base_path)
                    if item_path:
                        key = str(item_path)
                        if key not in processed:
                            processed[key] = datetime.now().isoformat()
                            baseline_keys.add(key)
                baselines[base] = datetime.now().isoformat()
                self.save_data("processed", processed)
                self.save_data("baselines", baselines)
                logger.info(
                    f"目录新增监控：首次扫描已建立基线，记录 {len(baseline_keys)} 个存量条目（不发送通知）"
                )
            else:
                for file_path in files:
                    if self._event.is_set():
                        logger.info("目录新增监控：服务停止")
                        return
                    try:
                        # 跳过仍在写入/下载的文件
                        mtime = file_path.stat().st_mtime
                        if now - mtime < STABLE_SECONDS:
                            item_path = self.__item_path(file_path, base_path)
                            if item_path and str(item_path) not in processed:
                                pending_new = True
                            continue
                    except Exception:
                        continue

                    item_path = self.__item_path(file_path, base_path)
                    if not item_path:
                        continue
                    key = str(item_path)
                    if key in processed:
                        continue

                    # 新条目
                    try:
                        self.__handle_new(item_path, file_path)
                    except Exception as e:
                        logger.error(f"目录新增监控：处理失败 {item_path}: {e}")
                    processed[key] = datetime.now().isoformat()
                    # 每处理一条就落盘，中断/重启不丢进度
                    self.save_data("processed", processed)

            # 全量扫描完成：仅在无"待稳定新文件"时固化当前目录树指纹
            if sig and not pending_new:
                dirprints[base] = sig
                self.save_data("dirprints_v2", dirprints)

        # 控制 processed 体积（大库场景，保留最近的记录）
        if len(processed) > PROCESSED_LIMIT:
            processed = dict(
                sorted(processed.items(), key=lambda kv: kv[1])[-PROCESSED_LIMIT:]
            )
        self.save_data("processed", processed)

    @staticmethod
    def __dir_signature(base_path: Path) -> Optional[str]:
        """
        生成目录树指纹：收集所有目录(不含文件)的路径与修改时间。
        目录内新增/删除/改名文件都会更新该目录的 mtime，
        故指纹不变即可断定媒体文件无增减，可跳过全量扫描。
        只 stat 目录不 stat 文件，I/O 开销极小。
        """
        parts = []
        try:
            stack = [str(base_path)]
            while stack:
                d = stack.pop()
                try:
                    st = os.stat(d, follow_symlinks=False)
                    parts.append(f"{d}:{int(st.st_mtime)}")
                    with os.scandir(d) as it:
                        for e in it:
                            try:
                                if e.is_dir(follow_symlinks=False):
                                    stack.append(e.path)
                            except OSError:
                                continue
                except OSError:
                    continue
        except Exception:
            return None
        parts.sort()
        return "|".join(parts)

    @staticmethod
    def __item_path(file_path: Path, base_path: Path) -> Optional[Path]:
        """
        根据媒体文件推断它所属的“媒体条目”路径，用于去重与识别：
        - 若父目录是季目录(Season/S01/第1季)，则条目为剧集目录(再上一层)
        - 否则条目为文件所在目录(电影目录)
        - 若条目就在监控根目录或其直接子级(扁平结构)，则条目为该文件本身
        """
        parent_name = file_path.parent.name.lower()
        if re.search(r'(season|s\d+|第\d+季|season\s*\d+)', parent_name):
            item = file_path.parent.parent
        else:
            item = file_path.parent
        if item == base_path or item == file_path.parent and item.parent == base_path:
            # 扁平结构（文件直接在监控根或其直接子目录下）
            item = file_path
        return item

    @staticmethod
    def __category_label(item_path: Path) -> str:
        """从条目路径中提取目录分类（如 动画片/电影/电视剧），没有则返回空串。"""
        for part in item_path.parts:
            if part in CATEGORY_DIRS:
                return part
        return ""

    def __handle_new(self, item_path: Path, sample_file: Path):
        """处理一个新增条目：识别 -> (可选)刮削 -> 记录 -> 通知。"""
        meta = MetaInfoPath(item_path)
        if not meta or not getattr(meta, "name", None):
            logger.info(f"目录新增监控：无法解析媒体名 {item_path}")
            return

        mtype = None
        if self._media_type == "电影":
            mtype = MediaType.MOVIE
        elif self._media_type == "电视剧":
            mtype = MediaType.TV

        mediainfo = self.__recognize(meta, mtype)

        if not mediainfo:
            logger.warning(f"目录新增监控：未识别到媒体信息 {item_path}")
            self.__record(item_path, meta.name if meta else str(item_path), None,
                          recognized=False, category=self.__category_label(item_path))
            if self._notify:
                self.__notify_raw(item_path, meta.name if meta else str(item_path),
                                  category=self.__category_label(item_path))
            return

        # 获取图片（海报等）
        try:
            self.chain.obtain_images(mediainfo)
        except Exception as e:
            logger.warning(f"目录新增监控：获取图片失败 {e}")

        # 写入 NFO 刮削
        if self._write_nfo:
            self.__scrape(item_path, mediainfo)

        # 记录历史
        self.__record(
            item_path,
            mediainfo.title or getattr(meta, "name", str(item_path)),
            mediainfo,
            recognized=True,
            category=self.__category_label(item_path),
        )

        # 发送通知
        if self._notify:
            self.__notify(mediainfo, item_path, category=self.__category_label(item_path))

    def __recognize(self, meta, mtype):
        """识别媒体，按配置临时切换识别数据源(TMDB/豆瓣)，结束后恢复原设置。"""
        source = self._scrape_source
        prev = None
        restore = False
        if source in ("douban", "themoviedb"):
            try:
                prev = get_runtime_setting("RECOGNIZE_SOURCE")
                if prev != source:
                    update_runtime_setting("RECOGNIZE_SOURCE", source)
                    restore = True
            except Exception as e:
                logger.warning(f"目录新增监控：切换识别源失败 {e}")
        try:
            if mtype:
                meta.type = mtype
            return self.chain.recognize_media(meta=meta)
        finally:
            if restore and prev is not None:
                try:
                    update_runtime_setting("RECOGNIZE_SOURCE", prev)
                except Exception:
                    pass

    def __scrape(self, item_path: Path, mediainfo):
        """将元数据刮削写入媒体目录（NFO + 图片），与媒体库刮削一致。"""
        try:
            target_type = "dir" if item_path.is_dir() else "file"
            item_path_str = str(item_path).replace("\\", "/")
            if target_type == "dir":
                item_path_str += "/"
            fileitem = FileItem(
                storage="local",
                type=target_type,
                path=item_path_str,
                name=item_path.name,
                basename=item_path.stem,
                extension=item_path.suffix[1:] if target_type == "file" else None,
                modify_time=item_path.stat().st_mtime,
            )
            ScrapingChain().scrape_metadata(
                fileitem=fileitem,
                mediainfo=mediainfo,
                overwrite=True,
            )
            logger.info(f"目录新增监控：{item_path} 刮削完成")
        except Exception as e:
            logger.error(f"目录新增监控：刮削失败 {item_path}: {e}")

    # ====================== 通知与记录 ======================
    @staticmethod
    def __poster_url(mediainfo) -> Optional[str]:
        """从媒体信息中取海报地址，拼接 TMDB 图片 URL。"""
        pp = getattr(mediainfo, "poster_path", None)
        if not pp:
            return None
        pp = str(pp)
        if pp.startswith("http"):
            return pp
        if pp.startswith("/"):
            return f"https://image.tmdb.org/t/p/w500{pp}"
        return None

    @staticmethod
    def __type_label(mediainfo) -> str:
        """把 MediaInfo.type 规范化为 电影/电视剧 显示文本（兼容枚举/字符串）。"""
        t = getattr(mediainfo, "type", None)
        val = getattr(t, "value", None)
        if not isinstance(val, str):
            val = t if isinstance(t, str) else str(t or "")
        v = str(val).strip().lower()
        if v in ("电影", "movie", "mediatype.movie"):
            return "电影"
        if v in ("电视剧", "tv", "mediatype.tv"):
            return "电视剧"
        return "媒体"

    def __notify(self, mediainfo, item_path: Path, category: str = ""):
        """已识别条目的通知：目录分类优先（如 动画片），否则用识别结果。"""
        mtype_label = category or self.__type_label(mediainfo)

        lines = [f"类型：{mtype_label}"]
        if getattr(mediainfo, "year", None):
            lines.append(f"年份：{mediainfo.year}")
        if getattr(mediainfo, "vote_average", None):
            lines.append(f"评分：{mediainfo.vote_average}")
        if getattr(mediainfo, "detail_link", None):
            lines.append(f"详情：{mediainfo.detail_link}")
        if getattr(mediainfo, "overview", None):
            ov = mediainfo.overview
            if len(ov) > 200:
                ov = ov[:200] + "…"
            lines.append(f"简介：{ov}")
        lines.append(f"路径：{item_path}")
        text = "\n".join(lines)

        self.post_message(
            mtype=MessageType.Plugin,
            title=f"🎬 新增{mtype_label}：{mediainfo.title or ''}",
            text=text,
            image=self.__poster_url(mediainfo),
            userid=self._notify_user or None,
        )

    def __notify_raw(self, item_path: Path, name: str, category: str = ""):
        """未识别条目的兜底通知。"""
        text = f"路径：{item_path}\n（未能自动识别，可在MP中手动刮削）"
        if category:
            text = f"类型：{category}\n{text}"
        self.post_message(
            mtype=MessageType.Plugin,
            title=f"📁 发现新增目录/文件：{name}",
            text=text,
            userid=self._notify_user or None,
        )

    def __record(self, item_path: Path, title: str, mediainfo, recognized: bool,
                 category: str = ""):
        """记录发现历史（供插件页面展示），目录分类优先于识别结果。"""
        history = self.get_data("history") or []
        mt = ""
        year = ""
        if mediainfo:
            mt = self.__type_label(mediainfo)
            year = getattr(mediainfo, "year", "") or ""
        # 目录分类优先（如 动画片），否则用识别结果
        if category:
            mt = category
        history.insert(0, {
            "title": title,
            "type": mt,
            "year": year,
            "path": str(item_path),
            "recognized": recognized,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        if len(history) > HISTORY_LIMIT:
            history = history[:HISTORY_LIMIT]
        self.save_data("history", history)

    # ====================== 手动触发 ======================
    def scan_now(self, request: dict, apikey: str = None) -> dict:
        """API 入口：立即执行一次扫描。"""
        try:
            self.__scan_all()
            return {"code": 0, "message": "扫描完成"}
        except Exception as e:
            logger.error(f"目录新增监控：手动扫描失败 {e}")
            return {"code": 1, "message": str(e)}

    def stop_service(self):
        """退出插件，停止后台调度任务。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.error(str(e))
