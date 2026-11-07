import re
import threading
import time
from pathlib import Path
from typing import Any, Dict
from xml.dom import minidom

from PIL import Image
from watchdog.events import FileSystemEventHandler

from app.application.directory import DirectoryHelper
from app.schemas import TransferDirectoryConf, TmdbEpisode, TransferInfo, FileItem
from app.schemas.types import MessageType
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.media import MediaInfo, MetaVideo, MetaBase, MetaInfoPath
from app.sdk.utilities import DomUtils, SystemUtils


ffmpeg_lock = threading.Lock()

class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控响应类
    """
    def __init__(self, watching_path: str, file_change: Any, **kwargs):
        super(FileMonitorHandler, self).__init__(**kwargs)
        self._watch_path = watching_path
        self.file_change = file_change

    def on_created(self, event):
        self.file_change.event_handler(event=event, source_dir=self._watch_path, event_path=event.src_path)

    def on_moved(self, event):
        self.file_change.event_handler(event=event, source_dir=self._watch_path, event_path=event.dest_path)

class Monitor:

    """AutoSports monitor 相关方法。"""

    def event_handler(self, event, source_dir: str, event_path: str):
        """
        处理文件变化
        :param event: 事件
        :param source_dir: 监控目录
        :param event_path: 事件文件路径
        """

        # 回收站及隐藏的文件不处理（统一成 / 分隔，兼容 Windows 反斜杠路径）
        event_posix = Path(event_path).as_posix()
        if (event_posix.find("/@Recycle") != -1
            or event_posix.find("/#recycle") != -1
            or event_posix.find("/.") != -1
            or event_posix.find("/@eaDir") != -1):
            logger.info(f"{event_path} 是回收站或隐藏的文件，跳过处理")
            return

        # 命中过滤关键字不处理
        if self._exclude:
            for keyword in self._exclude.split("\n"):
                if keyword and re.findall(keyword, event_path):
                    logger.info(f"{event_path} 命中过滤关键字 {keyword}，不处理")
                    return

        # 不是媒体文件不处理
        if Path(event_path).suffix.lower() not in settings.RMT_MEDIAEXT:
            logger.debug(f"{event_path} 不是媒体文件")
            return

        # 文件发生变化
        logger.debug(f"变动类型 {event.event_type} 变动路径 {event_path}")

        exist_matches = self._exists_match()

        self._handle_file(event_path=event_path, exist_matches=exist_matches)

    def sync_all(self, exist_matches: Dict[str, Dict[int, list]] = None):
        """
        全量同步目录中所有文件
        """
        if not self._save_path:
            logger.warning("未配置下载目录，跳过全量整理")
            return
        # 如果未传入已入库比赛信息，进行已入库媒体判断
        if not exist_matches:
            exist_matches = self._exists_match(use_cache=False)

        logger.info(f"开始全量整理体育比赛监控目录 {self._save_path} ...")
        # 遍历下载目录
        for file_path in SystemUtils.list_files(Path(self._save_path), settings.RMT_MEDIAEXT):
            logger.info(f"开始处理文件 {file_path} ...")
            self._handle_file(event_path=str(file_path), exist_matches=exist_matches)
        logger.info("全量整理体育比赛监控目录完成！")

    def gen_file_thumb(self, title: str, file_path: Path, rename_conf: bool):
        """
        处理一个文件
        """
        # 单线程处理
        if rename_conf:
            with ffmpeg_lock:
                try:
                    thumb_path = file_path.with_name(f"{title}_thumb.jpg")
                    if thumb_path.exists():
                        logger.debug(f"缩略图已存在：{title}_thumb.jpg")
                        return
                    self.get_thumb(video_path=str(file_path),
                                   image_path=str(thumb_path),
                                   frames=self._timeline)
                    if Path(thumb_path).exists():
                        logger.debug(f"{file_path} 缩略图已生成：{title}_thumb.jpg")
                        return thumb_path
                except Exception as err:
                    logger.error(f"FFmpeg 处理文件 {file_path} 时发生错误：{str(err)}")
                    return None

    @staticmethod
    def get_thumb(video_path: str, image_path: str, frames: str = None):
        """
        使用ffmpeg从视频文件中截取缩略图
        """
        if not frames:
            frames = "00:00:10"
        if not video_path or not image_path:
            return False
        cmd = 'ffmpeg -y -i "{video_path}" -ss {frames} -frames 1 "{image_path}"'.format(
            video_path=video_path,
            frames=frames,
            image_path=image_path)

        result = SystemUtils.execute(cmd)

        if result:
            return True
        return False

    def _parse_file_metadata(self, filepath: str, saved: bool = False):
        """
        根据路径识别体育媒体信息
        saved: 是否要刮削已入库的文件
        """
        match_filemeta = MetaInfoPath(Path(filepath))
        if not match_filemeta.name:
            logger.warning(f"{Path(filepath).name} 无法根据文件名识别有效信息")
            return None, None, None
        # 提取文件名
        filepath_name = match_filemeta.title
        if not saved:
            # 在缓存中查找文件名到种子名的映射关系
            cache_result = self.process_data(filepath_name)
            if cache_result:
                # 如果查询到了任何值，则替换要处理的文件名
                logger.debug(
                    f"使用缓存的文件名到种子名映射关系，处理文件：{filepath_name} -> {cache_result}")
                match_filemeta.org_string = cache_result

        # 文件名常用点或下划线分隔，统一成空格后再识别赛事、日期与对阵
        if match_filemeta.org_string:
            match_filemeta.org_string = re.sub(r"[._]+", " ", match_filemeta.org_string).strip()

        match_mediainfo: MediaInfo = self.recognize_competition_mediainfo(meta_info=match_filemeta)
        if not match_mediainfo:
            # 未识别到赛事信息，返回 None
            return None, None, None
        if saved:
            match_filemeta, match_episode_info = self.recognized_saved_match_metainfo(metainfo=match_filemeta)
        else:
            match_filemeta, match_episode_info = self.recognized_match_metainfo(match_mediainfo=match_mediainfo,
                                                                              metainfo=match_filemeta)
        return match_filemeta, match_mediainfo, match_episode_info

    def _exists_match(self, use_cache: bool = True) -> Dict[str, Dict[int, list]]:
        """
        判断比赛文件是否存在于文件系统（网盘或本地文件），只支持标准媒体库结构
        :param use_cache: 是否允许复用短时缓存，目录监控高频调用时开启
        :return: 如不存在返回None，存在时返回信息，包括每季已存在所有集{type: movie/tv, seasons: {season: [episodes]}}
        """
        if not settings.LOCAL_EXISTS_SEARCH:
            logger.info("MP 全局文件扫描设置未开启，无法进行本地比赛入库检查")
            return {}
        if not self._dest_path:
            logger.warning("未配置转移目录，跳过已入库比赛扫描")
            return {}
        if use_cache:
            with self._vault_cache_lock:
                cached = self._vault_cache
                cached_at = self._vault_cache_at
            if cached is not None and time.time() - cached_at < self._VAULT_CACHE_TTL:
                logger.debug("复用已入库比赛缓存，跳过媒体库全量扫描")
                return {name: {season: list(episodes) for season, episodes in seasons.items()}
                        for name, seasons in cached.items()}

        logger.info(f"正在转移目录中查找已入库所有比赛的信息...")

        # 检索本地所有集数
        matches: Dict[str, Dict[int, list]] = dict()
        for file_path in SystemUtils.list_files(Path(self._dest_path), settings.RMT_MEDIAEXT):
            # 刮削已入库比赛的元数据
            file_meta, mediainfo, episode_info = self._parse_file_metadata(Path(file_path).as_posix(), True)

            if not file_meta or not mediainfo or not episode_info:
                # 未识别到有效信息，跳过
                continue

            competition_name = mediainfo.title
            season_index = file_meta.begin_season or 1
            episode_index = file_meta.begin_episode
            if not competition_name:
                continue
            if not episode_index:
                continue
            matches.setdefault(competition_name, {})
            matches[competition_name].setdefault(season_index, [])
            if season_index not in matches[competition_name]:
                matches[competition_name][season_index] = []
            if episode_index not in matches[competition_name][season_index]:
                matches[competition_name][season_index].append(episode_index)

        # 返回已入库比赛情况
        if matches:
            for competition_name in matches.keys():
                # 赛季排序
                matches[competition_name] = {
                    k: v for k, v in sorted(matches[competition_name].items(), key=lambda item: item[0])
                }
                # 比赛轮次排序
                for season in matches[competition_name].keys():
                    # 比赛轮次排序
                    matches[competition_name][season].sort()
                logger.info(f"{competition_name} 在转移目录中找到了这些赛季/轮次：{matches[competition_name]}")
        else:
            logger.info(f"转移目录中未找到任何比赛的任何赛季/轮次")

        # 缓存扫描结果，供目录监控的后续文件事件复用
        with self._vault_cache_lock:
            self._vault_cache = {name: {season: list(episodes) for season, episodes in seasons.items()}
                                  for name, seasons in matches.items()}
            self._vault_cache_at = time.time()
        return matches

    def _remember_vault_cache(self, gotten_match_metainfo: MetaVideo = None) -> None:
        """
        把刚转移的比赛同步进已入库缓存，避免后续文件事件重复扫描媒体库。

        :param gotten_match_metainfo: 刚转移完成的比赛元数据
        """
        if not gotten_match_metainfo:
            return
        with self._vault_cache_lock:
            if self._vault_cache is None:
                return
            self.add_match_to_vault(exist_matches=self._vault_cache,
                                    gotten_match_metainfo=gotten_match_metainfo)

    def _handle_file(self, event_path: str, exist_matches: Dict[str, Dict[int, list]] = None):
        """
        同步一个文件
        :event.is_directory
        :param event_path: 事件文件路径
        """
        try:
            # 转移路径
            dest_dir = self._dest_path
            # 是否重命名
            rename_conf = self._need_rename

            logger.info(f'检测到文件变更，开始处理文件：{Path(event_path).name}')

            file_meta, mediainfo, episode_info = self._parse_file_metadata(event_path)
            if not file_meta or not mediainfo or not episode_info:
                logger.error(f"{Path(event_path).name} 无法根据文件名识别有效信息")
                return

            # mediainfo: MediaInfo = self.chain.recognize_media(meta=file_meta)
            transfer_flag = False
            target_path_str = ''

            # 进行转移
            if mediainfo and episode_info:
                try:
                    # 查询转移目的目录
                    target_dir = DirectoryHelper().get_dir(mediainfo, dest_path=Path(dest_dir))
                    if not target_dir or not target_dir.library_path:
                        target_dir = TransferDirectoryConf()
                        target_dir.library_path = dest_dir
                        target_dir.transfer_type = self._transfer_type
                        target_dir.renaming = True
                        target_dir.notify = False
                        target_dir.overwrite_mode = 'never'
                        target_dir.library_storage = "local"
                    else:
                        target_dir.transfer_type = self._transfer_type

                    if not target_dir.library_path:
                        logger.error(f"未配置监控目录 {dest_dir} 的目的目录")
                        return

                    # 更新媒体图片
                    self.chain.obtain_images(mediainfo=mediainfo)

                    # episodes_info = self.tmdbchain.tmdb_episodes(tmdbid=mediainfo.tmdb_id,
                    #                                              season=file_meta.begin_season or 1)
                    mediainfo.category = ""
                    # 转移
                    episodes_info = [episode_info]
                    source_path = Path(event_path)
                    source_fileitem = FileItem.from_uri(event_path)
                    source_fileitem.path = source_path.as_posix()
                    source_fileitem.type = "file"
                    source_fileitem.name = source_path.name
                    source_fileitem.basename = source_path.stem
                    source_fileitem.extension = source_path.suffix[1:]

                    is_in = self.is_match_in_vault(exist_matches=exist_matches, gotten_match_metainfo=file_meta)

                    if not is_in:
                        logger.info(
                            f'在进行文件转移时，发现 '
                            f'{file_meta.title_year} {file_meta.season_episode} 未入库，继续整理')
                        transferinfo: TransferInfo = self.chain.transfer(mediainfo=mediainfo,
                                                                     fileitem=source_fileitem,
                                                                     target_directory=target_dir,
                                                                     meta=file_meta,
                                                                     episodes_info=episodes_info)
                        if not transferinfo:
                            logger.error(f"单场比赛文件整理/重命名失败：{event_path}，不进行刮削动作")
                            transfer_flag = False
                        else:
                            target_path_str = transferinfo.target_item.path
                            logger.info(f"单场比赛文件整理/重命名成功：{event_path} -> {target_path_str}")
                            # 添加新转移的媒体到已入库比赛列表中
                            self.add_match_to_vault(exist_matches=exist_matches, gotten_match_metainfo=file_meta)
                            self._remember_vault_cache(gotten_match_metainfo=file_meta)
                            transfer_flag = True
                    else:
                        # 该场比赛已入库，不进行处理
                        logger.info(
                            f'在进行文件转移时，发现 '
                            f'{file_meta.title_year} {file_meta.season_episode} 己入库，不再处理')
                        transfer_flag = False
                except Exception as err:
                    logger.error(f"{event_path} 体育比赛刮削失败：{str(err)}")
                    transfer_flag = False

            if transfer_flag:
                # 生成刮削信息
                # 生成 tvshow.nfo
                target_file = Path(target_path_str)
                target_file_name = target_file.name
                title = str.split(target_file_name, ".")[0]
                # 生成赛事的NFO文件
                if not (target_file.parent.parent / "tvshow.nfo").exists():
                    self._gen_competition_nfo_file(dir_path=target_file.parent.parent, mediainfo=mediainfo)
                # 生成单场比赛的NFO文件
                if not (target_file.parent / f"{title}.nfo").exists():
                    self._gen_match_nfo_file(dir_path=target_file.parent, title=title,
                                              file_meta=file_meta, episode_meta=episode_info)

                # 生成缩略图
                if not (target_file.parent / f"{title}_poster.jpg").exists():
                    thumb_path = self.gen_file_thumb(title=title,
                                                     rename_conf=rename_conf,
                                                     file_path=target_file)
                    if thumb_path and Path(thumb_path).exists():
                        self._save_poster(input_path=thumb_path,
                                           poster_path=target_file.parent / f"{title}_poster.jpg",
                                           cover_conf="16:9")
                        if (target_file.parent / f"{title}_poster.jpg").exists():
                            logger.debug(f"{target_file.parent} / {title}_poster.jpg 缩略图已生成")
                        thumb_path.unlink()
                    else:
                        # 检查是否有缩略图
                        thumb_files = SystemUtils.list_files(directory=target_file.parent,
                                                             extensions=[".jpg"])
                        if thumb_files:
                            # 生成poster
                            for thumb in thumb_files:
                                self._save_poster(input_path=thumb,
                                                   poster_path=target_file.parent / f"{title}_poster.jpg",
                                                   cover_conf="16:9")
                                break
                            if (target_file.parent / f"{title}_poster.jpg").exists():
                                logger.debug(f"{target_file.parent} / {title}_poster.jpg 缩略图已生成")
                            # 删除多余jpg
                            for thumb in thumb_files:
                                Path(thumb).unlink()

                if self._notify:
                    # 发送消息
                    # TODO: 发送消息添加缓存机制
                    # if title not in self._cached_messages:
                    # 发送消息
                    self.post_message(mtype=MessageType.Organize,
                                      title=f"体育比赛【{title}】已入库",
                                      text=f"赛事：{file_meta.title}\n"
                                           f"轮次: {file_meta.cn_name.split(' - ')[0] + file_meta.cn_name.split(' - ')[1]}\n"
                                           f"对阵: {file_meta.subtitle}")
                        # self._cached_messages.append(title)
        except Exception as e:
            logger.error(f"文件整理/重命名模块运行错误，详细信息: {e}")

    def _gen_competition_nfo_file(self, dir_path: Path, mediainfo: MediaInfo = None):
        """
        生成赛事的 NFO 描述文件
        @param dir_path: 目标目录
        @param mediainfo: 赛事元数据
        """
        # 开始生成XML
        logger.debug(f"正在生成赛事NFO文件：{mediainfo.title}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "tvshow")

        # 各种信息
        DomUtils.add_node(doc, root, "title", mediainfo.title)
        DomUtils.add_node(doc, root, "sorttitle", mediainfo.en_title or '')
        DomUtils.add_node(doc, root, "status", 'Continuing')
        DomUtils.add_node(doc, root, "originaltitle", mediainfo.original_name or '')
        DomUtils.add_node(doc, root, "year", mediainfo.year or '')
        DomUtils.add_node(doc, root, "plot", mediainfo.overview or '')
        DomUtils.add_node(doc, root, "genre", 'Sport')
        DomUtils.add_node(doc, root, "genre", 'Soccer')
        if mediainfo.production_companies:
            for production_company in mediainfo.production_companies:
                DomUtils.add_node(doc, root, "studio", production_company or '')
        # 保存
        self._save_nfo(doc, dir_path.joinpath(f"tvshow.nfo"))

    def _gen_match_nfo_file(self, dir_path: Path, title: str = '', file_meta: MetaBase = None,
                             episode_meta: TmdbEpisode = None):
        """
        生成单场比赛的 NFO 描述文件
        :param dir_path: 比赛根目录
        """
        # 开始生成XML
        logger.debug(f"正在生成比赛NFO文件：{title}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "episodedetails")

        # 各种信息
        DomUtils.add_node(doc, root, "title", file_meta.cn_name or '')
        DomUtils.add_node(doc, root, "originaltitle", file_meta.en_name or '')
        DomUtils.add_node(doc, root, "season", file_meta.begin_season or '')
        DomUtils.add_node(doc, root, "episode", file_meta.begin_episode or '')
        DomUtils.add_node(doc, root, "aired", str(episode_meta.air_date).split(' ')[0] or '')
        # 保存
        self._save_nfo(doc, dir_path.joinpath(f"{title}.nfo"))

    @staticmethod
    def _save_nfo(doc, file_path: Path):
        """
        保存NFO
        """
        xml_str = doc.toprettyxml(indent="  ", encoding="utf-8")
        file_path.write_bytes(xml_str)
        logger.debug(f"NFO文件已保存：{file_path}")

    @staticmethod
    def _save_poster(input_path, poster_path, cover_conf):
        """
        截取图片做封面
        """
        try:
            image = Image.open(input_path)

            # 需要截取的长宽比（比如 16:9）
            if not cover_conf:
                target_ratio = 2 / 3
            else:
                covers = cover_conf.split(":")
                target_ratio = int(covers[0]) / int(covers[1])

            # 获取原始图片的长宽比
            original_ratio = image.width / image.height

            # 计算截取后的大小
            if original_ratio > target_ratio:
                new_height = image.height
                new_width = int(new_height * target_ratio)
            else:
                new_width = image.width
                new_height = int(new_width / target_ratio)

            # 计算截取的位置
            left = (image.width - new_width) // 2
            top = (image.height - new_height) // 2
            right = left + new_width
            bottom = top + new_height

            # 截取图片
            cropped_image = image.crop((left, top, right, bottom))

            # 保存截取后的图片
            cropped_image.save(poster_path)
        except Exception as e:
            logger.error(f"生成海报失败：{str(e)}")
