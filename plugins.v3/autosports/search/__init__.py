import base64
import datetime
import json
import re
import time
import traceback
from typing import Optional, List, Dict

from app.chain.search import SearchChain
from app.schemas.types import SystemConfigKey, MessageType, MediaSource
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.media import MediaInfo, TorrentInfo, MetaVideo, MetaBase, MetaInfo
from app.sdk.network import RequestUtils, SitesHelper
from app.sdk.services import DownloaderHelper
from app.sdk.utilities import StringUtils


from app.plugins.autosports.search.models import Matchinfo


class Search:

    """AutoSports search 相关方法。"""

    def _stamp_torrent_identity(self, torrent: TorrentInfo) -> None:
        """
        给本站种子写入插件数据源身份，供下载链路按体育规则识别。

        :param torrent: 待写入身份的种子信息
        """
        if not torrent or getattr(torrent, "media_source", None):
            return
        cache_key = torrent.title or ""
        cached = self._stamp_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < self._STAMP_CACHE_TTL:
            identity = cached[1]
        else:
            mediainfo = self._recognize_sports_media(MetaInfo(
                title=torrent.title or "",
                subtitle=torrent.description,
            ))
            identity = (str(mediainfo.media_source), mediainfo.media_id) if mediainfo else None
            if len(self._stamp_cache) > 500:
                self._stamp_cache.clear()
            self._stamp_cache[cache_key] = (now, identity)
        if not identity:
            return
        torrent.media_source = MediaSource(identity[0])
        torrent.media_id = identity[1]

    def filter_torrents(self, rule_groups: List[str], torrent_list: List[TorrentInfo],
                        mediainfo: MediaInfo = None) -> List[TorrentInfo]:
        """
        重载宿主的种子规则过滤，让本站种子绕开搜索过滤规则。

        只返回“本站种子里会被宿主规则排除”的那部分：宿主随后仍会对完整列表执行一次过滤，
        插件结果与宿主结果合并后本站种子全部保留、其它站点照旧过滤。这样既不改动调用方的
        列表（分页搜索会复用同一个列表），也不会产生重复结果。

        :param rule_groups: 宿主传入的过滤规则组名称
        :param torrent_list: 待过滤的种子列表，方法内不会修改
        :param mediainfo: 媒体信息，标题搜索时为空
        :return: 会被宿主规则排除的本站种子列表；没有本站种子时返回空列表
        """
        if getattr(self._filter_isolation, "active", False) or not torrent_list:
            return []

        kept = [torrent for torrent in torrent_list if self._is_sportscult_torrent(torrent)]
        if not kept:
            return []

        # 给本站种子写入插件数据源身份，下载时宿主会按该来源调用插件识别
        for torrent in kept:
            self._stamp_torrent_identity(torrent)

        # 开启该开关时不放行，本站种子和普通站点一样按宿主规则过滤
        if self._filter_builtin_search:
            return []

        # 先让宿主规则过滤一次本站种子，算出其中会被排除的部分；
        # 置位隔离标记，避免这次内部调用再次进入本方法。
        self._filter_isolation.active = True
        try:
            passed = self.chain.filter_torrents(
                rule_groups=rule_groups,
                torrent_list=list(kept),
                mediainfo=mediainfo,
            ) or []
        finally:
            self._filter_isolation.active = False

        passed_ids = {id(torrent) for torrent in passed}
        bypassed = [torrent for torrent in kept if id(torrent) not in passed_ids]
        if bypassed:
            logger.info(f"内置搜索过滤放行 {len(bypassed)} 个 Sportscult 种子（不受 MP 过滤规则限制）")
        return bypassed

    def _is_sportscult_torrent(self, torrent: TorrentInfo) -> bool:
        """
        判断种子是否来自 Sportscult 站点。

        :param torrent: 待判断的种子信息
        :return: 站点名或站点 ID 命中 Sportscult 时返回 True
        """
        if not torrent:
            return False
        site_name = (getattr(torrent, "site_name", None) or "").strip().casefold()
        if site_name == "sportscult":
            return True
        site_id = getattr(torrent, "site", None)
        return bool(site_id and self._sportscult_site_id and site_id == self._sportscult_site_id)

    def check(self):
        """
        自动下载 SportsCult 球队最新内容
        """

        if not self._teams_info:
            logger.error(f"未输入球队名，不会进行任何操作，请输入球队名再试")
            return
        # 读取历史记录
        if self._clearflag:
            history = []
        else:
            history: List[dict] = self.get_data('history') or []

        searchchain = SearchChain()

        sportscult_indexer_id = self.get_sportscult_indexer()

        if not sportscult_indexer_id:
            logger.error("Sportscult 站点配置错误，不再继续执行插件相关功能")
            return
        # 记录站点 ID，供 filter_torrents 识别本站种子
        self._sportscult_site_id = sportscult_indexer_id

        # 识别本地已入库所有比赛的信息
        exist_matches: Dict[str, Dict[int, list]] = self._exists_match(use_cache=False)
        if self._sync_all:
            # 如果启用了全量扫描，开始全量同步目录中所有体育比赛文件
            self.sync_all(exist_matches=exist_matches)
            logger.info("文件同步结束")
            if exist_matches:
                logger.info(f"文件同步后，已入库媒体信息为:")
                for competition_name in exist_matches.keys():
                    logger.info(f"{competition_name} {exist_matches[competition_name]}")

        elif self._action == "transfer":
            # 仅作整理，不下载
            logger.info(f"仅整理文件，不下载新种子")
            self.sync_all(exist_matches=exist_matches)
            logger.info("文件同步结束")
            if exist_matches:
                logger.info(f"文件同步后，已入库媒体信息为:")
                for competition_name in exist_matches.keys():
                    logger.info(f"{competition_name} {exist_matches[competition_name]}")
            self._clearflag = False
            # 保存历史记录
            self.save_data('history', history)
            return

        # 搜索模块
        results = []
        for team_info in self._teams_info.split("\n"):
            # 在 SportsCult 搜索种子
            if not team_info:
                continue
            logger.info(f"开始在 Sportscult 以关键词 {team_info} 搜索比赛...")

            # 显式传空规则组：不使用 MoviePilot 的「搜索过滤规则组」，
            # 否则影视/番剧的质量规则会在插件识别之前把 720p、无分辨率标记的比赛种子直接滤掉。
            # 是否下载交给插件自己的 include/exclude/size_range/lowest_pix 判断。
            search_results = searchchain.search_by_title(title=team_info, sites=[sportscult_indexer_id],
                                                         rule_groups=[])
            if not search_results:
                logger.error(f"未获取到该球队相关比赛种子，请更换关键词再试试：{team_info}")
                self._log_site_search_hint()
                continue
            else:
                logger.info(f"站点返回 {len(search_results)} 条结果（已跳过 MP 搜索过滤规则）")
                results.extend(search_results)
        if not results:
            logger.error(f"所有关键词 ({'/'.join(self._teams_info.split('\n'))}) 都未搜索到任何结果，请检查球队关键词设置")

        # 清空比赛元数据缓存
        if not self._cached_matches:
            self._cached_matches = {}

        # 初始化搜索到的比赛信息的储存对象
        matchesinfo = []

        # 解析数据
        for result in results:
            try:
                title = result.torrent_info.title
                logger.info(f"找到种子：{title}，开始处理......")
                description = result.torrent_info.description
                size = result.torrent_info.size
                # 检查是否处理过
                if not title or title in [h.get("torrent_title") for h in history]:
                    logger.info("已处理过该种子，请清除记录后重试")
                    continue
                # 默认排除篮球等其它比赛的关键词
                not_football = ['basketball', 'baseball', 'hockey']
                if any (x in f'{title.lower()} {description.lower()}' for x in not_football):
                    logger.info(f"该种子不是足球比赛，跳过")
                    continue
                # 检查规则
                if self._include and not any(re.search(r"%s" % include_word,
                                                    f"{title} {description}", re.IGNORECASE) for include_word in self._include.split(",")):
                    logger.info(f"该种子不符合包含规则，跳过")
                    continue
                if self._exclude and any(re.search(r"%s" % exclude_word,
                                                f"{title} {description}", re.IGNORECASE) for exclude_word in self._exclude.split(",")):
                    logger.info(f"该种子不符合排除规则，跳过")
                    continue
                if self._size_range:
                    sizes = [float(_size) * 1024 ** 3 for _size in self._size_range.split("-")]
                    size_gb = float(size or 0) / 1024 ** 3
                    if len(sizes) == 1 and float(size) < sizes[0]:
                        logger.info(f"该种子大小不符合条件：{size_gb:.2f} GB，设置下限 {self._size_range} GB")
                        continue
                    elif len(sizes) > 1 and not sizes[0] <= float(size) <= sizes[1]:
                        logger.info(f"该种子大小不在指定范围：{size_gb:.2f} GB，设置范围 {self._size_range} GB")
                        continue

                # 种子
                gotten_torrentinfo = result.torrent_info
                gotten_metainfo = result.meta_info
                # 识别体育比赛信息
                gotten_match_mediainfo = self.recognize_competition_mediainfo(gotten_torrentinfo, gotten_metainfo)
                if not gotten_match_mediainfo:
                    # 如果未识别成功，跳过
                    continue
                gotten_match_metainfo, _ = self.recognized_match_metainfo(gotten_match_mediainfo, gotten_metainfo)
                if not gotten_match_metainfo:
                    # 如果未识别成功，跳过
                    continue

                filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)

                # 过滤种子
                if self._filter:
                    # 插件自定义过滤时让重载的 filter_torrents 放行，按配置的规则组正常过滤
                    self._filter_isolation.active = True
                    try:
                        result = self.chain.filter_torrents(
                            rule_groups=filter_groups,
                            torrent_list=[gotten_torrentinfo],
                            mediainfo=gotten_match_mediainfo
                        )
                    finally:
                        self._filter_isolation.active = False
                    if not result:
                        logger.info(f"{title} 不匹配过滤规则")
                        continue

                # 判断媒体库是否已存在该场比赛
                is_in = self.is_match_in_vault(exist_matches, gotten_match_metainfo)
                if is_in:
                    logger.info(
                        f'处理搜索到的种子时，发现 '
                        f'{gotten_match_metainfo.title_year} {gotten_match_metainfo.season_episode} 己入库，不再处理')
                    continue
                else:
                    logger.info(
                        f'处理搜索到的种子时，发现 '
                        f'{gotten_match_metainfo.title_year} {gotten_match_metainfo.season_episode} 未入库，继续处理')

                # 判断新搜索到的种子是否比之前的种子更好
                gotten_matchinfo = self.Matchinfo(gotten_torrentinfo, gotten_match_mediainfo, gotten_match_metainfo)
                gotten_matchinfo.language = self.recognize_language(gotten_match_metainfo)
                if gotten_metainfo.resource_pix:
                    if gotten_metainfo.resource_pix == '4k':
                        gotten_matchinfo.pix = 2160
                    elif gotten_metainfo.resource_pix == '2k':
                        gotten_matchinfo.pix = 1440
                    else:
                        gotten_matchinfo.pix = int(gotten_metainfo.resource_pix[0:-1])
                self.find_best(force_en=self._force_en, lowest_pix=self._lowest_pix, matchesinfo=matchesinfo,
                               new_matchinfo=gotten_matchinfo)
            except Exception as err:
                logger.error(f'自动寻找种子模块出错：{str(err)} - {traceback.format_exc()}')

        # 新增处理的比赛场数计数
        processed_num = 0

        for final_matchinfo in matchesinfo:
            if self._max_download and processed_num >= self._max_download:
                logger.info(f"已处理种子数量超过最大限制 {self._max_download}，不再添加新的种子")
                break
            torrentinfo = final_matchinfo.torrentinfo
            match_mediainfo = final_matchinfo.mediainfo
            match_metainfo = final_matchinfo.metainfo
            title = torrentinfo.title
            # 下载或订阅
            if self._action == "download":
                if match_metainfo.episode == 'E00':
                    logger.warning(f"种子 {torrentinfo.title} 未识别到轮次，将以暂停状态添加该种")
                    is_existed, torrent_hash = self._download(torrentinfo, True, metainfo=match_metainfo)
                # 添加下载
                else:
                    is_existed, torrent_hash = self._download(torrentinfo, self._start_paused, metainfo=match_metainfo)
                if not torrent_hash:
                    logger.warning(f'{title} 下载失败')
                    processed_num += 1
                elif is_existed:
                    logger.info(f'{title} 已存在，种子 HASH 值为：{torrent_hash}')
                    # 存储历史记录
                    history.append({
                        "torrent_title": torrentinfo.title,
                        "competition_name": match_metainfo.title,
                        "roundinfo": match_metainfo.season_episode,
                        "round_cn_name": match_metainfo.cn_name.split(' - ')[0] + ' - ' + match_metainfo.cn_name.split(' - ')[1],
                        "matchmake": match_metainfo.subtitle,
                        "home_crest": self._match_crest_pair(match_metainfo.subtitle)[0],
                        "away_crest": self._match_crest_pair(match_metainfo.subtitle)[1],
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    processed_num += 1
                else:
                    logger.info(f'{title} 下载成功，种子 HASH 值为：{torrent_hash}')
                    # 发送消息
                    self.post_message(mtype=MessageType.Download,
                                      title=f"体育比赛种子【{title}】已开始下载",
                                      text=f"赛事：{match_mediainfo.title}\n"
                                           f"轮次: {match_metainfo.cn_name.split(' - ')[0] + ' - ' + match_metainfo.cn_name.split(' - ')[1]}\n"
                                           f"对阵: {match_metainfo.subtitle}")
                    # 存储历史记录
                    history.append({
                        "torrent_title": torrentinfo.title,
                        "competition_name": match_metainfo.title,
                        "roundinfo": match_metainfo.season_episode,
                        "round_cn_name": match_metainfo.cn_name.split(' - ')[0] + ' - ' + match_metainfo.cn_name.split(' - ')[1],
                        "matchmake": match_metainfo.subtitle,
                        "home_crest": self._match_crest_pair(match_metainfo.subtitle)[0],
                        "away_crest": self._match_crest_pair(match_metainfo.subtitle)[1],
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    processed_num += 1
            else:
                # TODO: 支持订阅功能
                # logger.error(f'暂不支持订阅功能，请等待适配')
                # # 保存历史记录
                # self.save_data('history', history)
                # # 缓存只清理一次
                # self._clearflag = False
                # return
                # # 检查是否在订阅中
                # subflag = subscribechain.exists(mediainfo=match_mediainfo, meta=match_metainfo)
                # if subflag:
                #     logger.info(f'{match_mediainfo.title_year} {metainfo.season} 正在订阅中')
                #     continue
                # # 添加订阅
                # subscribechain.add(title=match_mediainfo.title,
                #                    year=match_mediainfo.year,
                #                    mtype=match_mediainfo.type,
                #                    tmdbid=match_mediainfo.tmdb_id,
                #                    season=metainfo.begin_season,
                #                    exist_ok=True,
                #                    username="AutoSports")
                pass

        if not processed_num:
            logger.info(f"未找到任何种子或所有比赛已入库，不进行添加任何下载")
        logger.info(f"AutoSports 下载任务刷新完成")
        # 保存历史记录
        self.save_data('history', history)


        # 30 分钟后分别尝试再次整理 (已用增量监控目录服务替代)
        # logger.info(f"等待 30 分钟后再次尝试进行比赛整理")
        # transfer_scheduler = BackgroundScheduler(timezone=settings.TZ)
        # transfer_scheduler.add_job(func=self.sync_all, trigger='date',
        #                          run_date=datetime.datetime.now(
        #                              tz=pytz.timezone(settings.TZ)) + datetime.timedelta(minutes=30)
        #                          )
        # # 挂载刮削任务
        # if transfer_scheduler.get_jobs():
        #     transfer_scheduler.print_jobs()
        #     transfer_scheduler.start()

        # 缓存只清理一次
        self._clearflag = False

    def process_data(self, key: str = '', value = None):
        """
        使用系统级缓存处理事件
        @param key: 要保存到的键
        @param value: 要保存的值
        @return: 若查询到，返回查询到的值，否则返回空
        """
        # 检查缓存
        if key in self._system_cache:
            # 若有值则返回查询到的值
            return self._system_cache[key]
        # 如果对应key且未传入任何要缓存的value，则返回空
        if not value:
            return None
        # 否则，存储传入的对象
        self._system_cache[key] = value
        return value

    @staticmethod
    def get_sportscult_indexer() -> int | None:
        for indexer in SitesHelper().get_indexers():
            if indexer.get("name") == "Sportscult":
                # 检查站点索引开关
                if indexer.get("is_active"):
                    # sportscult_indexer = indexer
                    sportscult_indexer_id: int = indexer.get("id")
                    return sportscult_indexer_id
                else:
                    logger.error(f"Sportscult 站点未启用，请检查站点设置")
                    return None

        # 遍历所有站点没有找到，返回 None
        logger.error(f"Sportscult 站点未正确添加，请检查站点设置")
        return None

    @staticmethod
    def _has_indexer(domain: str) -> bool:
        """
        判断站点索引器是否已经存在，避免重复添加覆盖用户修改。

        :param domain: 站点域名
        :return: 已存在时返回 True
        """
        try:
            return bool(SitesHelper().get_indexer(domain))
        except Exception as err:
            logger.debug(f"读取站点索引器 {domain} 失败：{str(err)}")
            return False

    @staticmethod
    def is_match_in_vault(exist_matches: Dict[str, Dict[int, list]] = None, gotten_match_metainfo: MetaVideo = None) -> bool:
        logger.debug(f"开始判断该场比赛是否已入库")
        if exist_matches:
            exist_competitions = exist_matches.keys()
            for exist_competition in exist_competitions:
                if exist_competition == gotten_match_metainfo.title:
                    exist_seasons = exist_matches.get(exist_competition)
                    if exist_seasons:
                        exist_episodes = exist_seasons.get(gotten_match_metainfo.begin_season)
                        if exist_episodes and set(gotten_match_metainfo.episode_list).issubset(set(exist_episodes)):
                            return True
        return False

    @staticmethod
    def add_match_to_vault(exist_matches: Dict[str, Dict[int, list]] = None,
                          gotten_match_metainfo: MetaVideo = None) -> bool:
        logger.debug(f"开始添加已整理比赛到已入库列表中")

        if exist_matches:
            exist_competitions = exist_matches.keys()
            if gotten_match_metainfo.title not in exist_competitions:
                # 赛事不存在，添加该赛事的该赛季的该场比赛
                exist_matches.update({gotten_match_metainfo.title: {gotten_match_metainfo.begin_season: gotten_match_metainfo.episode_list}})
            elif gotten_match_metainfo.begin_season not in exist_matches.get(gotten_match_metainfo.title):
                # 赛季不存在，添加该赛季的该场比赛
                exist_matches[gotten_match_metainfo.title].update({gotten_match_metainfo.begin_season: gotten_match_metainfo.episode_list})
            else:
                # 比赛不存在，添加比赛
                exist_matches[gotten_match_metainfo.title][gotten_match_metainfo.begin_season].extend(gotten_match_metainfo.episode_list)
            return True
        else:
            return False

    @staticmethod
    def find_best(force_en: bool = False, lowest_pix: int = 0, matchesinfo: list[Matchinfo] = None,
                  new_matchinfo: Matchinfo = None):
        """
          判断传入的种子是否比现有的优先级更高
        """
        if force_en and new_matchinfo.language != "en":
            # 语言不满足约束条件，直接退出
            logger.info(f"不满足约束条件（非英语解说：{new_matchinfo.language}），跳过：{new_matchinfo.torrentinfo.title}")
            return
        if lowest_pix and new_matchinfo.pix and new_matchinfo.pix < lowest_pix:
            # 清晰度低于最低要求时退出；pix 为 0 表示标题里没有清晰度信息，不参与该约束
            logger.info(f"不满足约束条件（清晰度 {new_matchinfo.pix}p 低于 {lowest_pix}p），跳过：{new_matchinfo.torrentinfo.title}")
            return

        # 判断之前是否已搜索到该场比赛的种子
        for i, old_matchinfo in enumerate(matchesinfo):
            if new_matchinfo.metainfo.title != old_matchinfo.metainfo.title:
                # 如果赛事不匹配，直接跳过
                continue
            if new_matchinfo.metainfo.season_episode == old_matchinfo.metainfo.season_episode:
                if new_matchinfo.language == "en" and old_matchinfo.language != "en":
                    matchesinfo[i] = new_matchinfo
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title}) 的解说语言为英语，而之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) 不是，替换")
                    return
                elif new_matchinfo.pix > old_matchinfo.pix:
                    matchesinfo[i] = new_matchinfo
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title})的清晰度高于之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) ，替换")
                    return
                elif new_matchinfo.pix == old_matchinfo.pix \
                        and (new_matchinfo.torrentinfo.seeders or 0) > (old_matchinfo.torrentinfo.seeders or 0):
                    matchesinfo[i] = new_matchinfo
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title}) 与之前搜索到的种子清晰度相同但做种数更多，替换")
                    return
                else:
                    logger.info(
                        f"新种子 ({new_matchinfo.torrentinfo.title}) 不如之前搜索到的种子 ({old_matchinfo.torrentinfo.title}) ，不替换")
                    return

        # 如果已有种子列表中没有该场比赛，则添加之
        matchesinfo.append(new_matchinfo)
        return

    def _download(self, torrent: TorrentInfo, is_paused: bool,
                   metainfo: MetaBase = None) -> tuple[bool, Optional[str]]:
        """
        添加下载任务
        torrent: TorrentInfo 要添加下载的种子的信息
        is_paused: bool 是否以暂停状态添加种子
        match_title: MetaBase 识别后的比赛元数据
        """
        if not torrent.enclosure:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return False, None

        # 保存地址
        download_dir = self._save_path or None
        # 获取下载链接
        torrent_content = torrent.enclosure
        # proxies
        proxies = settings.PROXY if torrent.site_proxy else None
        # cookie
        cookies = torrent.site_cookie
        if torrent_content.startswith("["):
            torrent_content = self._get_redict_url(url=torrent_content,
                                                    proxies=proxies,
                                                    ua=torrent.site_ua,
                                                    cookie=cookies)
            # 目前馒头请求实际种子时，不能传入Cookie
            cookies = None
        if not torrent_content:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return False, None

        # TODO: 支持多下载器
        downloader = self._downloader
        if not downloader:
            return False, None

        downloader_helper = DownloaderHelper()
        if downloader_helper.is_downloader("qbittorrent", service=self._service_info):
            # 生成随机Tag
            random_tag = StringUtils.generate_random_str(10)
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            if not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=cookies,
                                        proxies=proxies,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.warning("尝试通过 MP 下载种子失败，继续尝试传递种子地址到下载器进行下载")
            if torrent_content:
                existed_torrents = downloader.get_torrents(tags=["AutoSports"])
                # 判断是否已添加该任务
                if existed_torrents:
                    for torrent_data in existed_torrents[0]:
                        torrent_name = torrent_data.get("name")
                        if torrent.title in torrent_name:
                            torrent_hash = torrent_data.get("hash")
                            return True, torrent_hash
                        else:
                            # 尝试从缓存中找替代名
                            cached_name = self.process_data(torrent_name)
                            if cached_name and metainfo.title + ' - ' + metainfo.cn_name == cached_name:
                                torrent_hash = torrent_data.get("hash")
                                return True, torrent_hash

                state = downloader.add_torrent(content=torrent_content,
                                           download_dir=download_dir,
                                           is_paused=is_paused,  # 调试用
                                           cookie=cookies,
                                           category=self._category,
                                           tag=self._tags + ["AutoSports"] + [random_tag], )

                if not state:
                    return False, None
                else:
                    # 获取种子Hash
                    torrent_hash = downloader.get_torrent_id_by_tag(tags=random_tag)
                    if not torrent_hash:
                        logger.error(f"{self._downloaders} 获取种子 Hash 失败")
                        return False, None
                    downloader.remove_torrents_tag([torrent_hash], random_tag)
                    # 关联种子名和文件名并储存到缓存中
                    torrent_files = downloader.get_files(torrent_hash)
                    if torrent_files and len(torrent_files) == 1:
                        # 单文件，直接存储种子名-文件名映射关系到缓存中
                        file_name_str = torrent_files[0].get("name")
                        if file_name_str:
                            file_name = file_name_str.split('/')[-1]
                            self.process_data(file_name, metainfo.title + ' - ' + metainfo.cn_name)
                            logger.debug(f"在缓存中成功建立映射关系：{file_name} -> {metainfo.title + ' - ' + metainfo.cn_name}")
                    if is_paused:
                        logger.info("根据设置，添加下载任务后即刻暂停")
                    else:
                        logger.info("根据设置，添加下载任务后即刻开始")
                    return False, torrent_hash
            return False, None

        elif downloader_helper.is_downloader("transmission", service=self._service_info):
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            # 生成随机Tag
            random_tag = StringUtils.generate_random_str(10)

            if not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=cookies,
                                        proxies=proxies,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error("尝试通过 MP 下载种子失败，继续尝试传递种子地址到下载器进行下载")
            if torrent_content:
                existed_torrents = downloader.get_torrents(tags=["AutoSports"])
                # 判断是否已添加该任务
                if existed_torrents:
                    for torrent_data in existed_torrents[0]:
                        torrent_name = torrent_data.get("name")
                        if torrent.title in torrent_name:
                            torrent_hash = torrent_data.get("hash")
                            return True, torrent_hash

                state = downloader.add_torrent(content=torrent_content,
                                               download_dir=download_dir,
                                               is_paused=is_paused,  # 调试用
                                               cookie=cookies,
                                               labels=self._tags + ["AutoSports"] + [random_tag],)

                if not state:
                    return False, None
                else:
                    # 获取种子Hash
                    torrent_hash = downloader.get_torrent_id_by_tag(tags=random_tag)
                    if not torrent_hash:
                        logger.error(f"{self._downloaders} 获取种子 Hash 失败")
                        return False, None
                    downloader.remove_torrents_tag([torrent_hash], random_tag)
                    if is_paused:
                        logger.info("根据设置，添加下载任务后暂停")
                    else:
                        logger.info("根据设置，添加下载任务后开始")
                    return False, torrent_hash
            return False, None
        return False, None

    def _log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message, title="AutoSports")

    def _log_site_search_hint(self):
        """
        站点搜索为空时输出可操作提示，用于区分“站点访问失败”和“确实没有结果”。
        """
        try:
            indexer = SitesHelper().get_indexer("sportscult.org") or {}
        except Exception as err:
            logger.debug(f"读取 Sportscult 站点配置失败：{str(err)}")
            return
        if not indexer:
            logger.warning("未读取到 Sportscult 站点配置，请检查站点是否已正确添加")
            return
        proxy_enabled = bool(indexer.get("proxy"))
        logger.warning(
            f"Sportscult 站点当前配置：使用代理={proxy_enabled}，超时={indexer.get('timeout')} 秒；"
            f"若请求耗时接近超时时间仍返回 0 条，说明站点直连不通而不是关键词没有结果，"
            f"请在 设置 - 站点 中为 Sportscult 打开“使用代理”后重试")

    @staticmethod
    def _get_redict_url(url: str, proxies: str = None, ua: str = None, cookie: str = None) -> Optional[str]:
        """
        获取下载链接， url格式：[base64]url
        """
        # 获取[]中的内容
        m = re.search(r"\[(.*)](.*)", url)
        if m:
            # 参数
            base64_str = m.group(1)
            # URL
            url = m.group(2)
            if not base64_str:
                return url
            # 解码参数
            req_str = base64.b64decode(base64_str.encode('utf-8')).decode('utf-8')
            req_params: Dict[str, dict] = json.loads(req_str)
            # 是否使用cookie
            if not req_params.get('cookie'):
                cookie = None
            # 请求头
            if req_params.get('header'):
                headers = req_params.get('header')
            else:
                headers = None
            if req_params.get('method') == 'get':
                # GET请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).get_res(url, params=req_params.get('params'))
            else:
                # POST请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).post_res(url, params=req_params.get('params'))
            if not res:
                return None
            if not req_params.get('result'):
                return res.text
            else:
                data = res.json()
                for key in str(req_params.get('result')).split("."):
                    data = data.get(key)
                    if not data:
                        return None
                logger.debug(f"获取到下载地址：{data}")
                return data
        return None
