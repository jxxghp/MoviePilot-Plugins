import threading
from typing import List, Tuple, Dict, Any, Optional

from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ServiceInfo
from app.db.downloadhistory_oper import DownloadHistoryOper, DownloadHistory
from app.helper.downloader import DownloaderHelper

lock = threading.Lock()


class SubscribeClear(_PluginBase):
    # 插件名称
    plugin_name = "订阅种子清理"
    # 插件描述
    plugin_desc = "删除指定下载信息。"
    # 插件图标
    plugin_icon = "Moviepilot_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "k0ala"
    # 作者主页
    author_url = "https://github.com/liushaoxiong10"
    # 插件配置项ID前缀
    plugin_config_prefix = "subscribeclear_"
    # 加载顺序
    plugin_order = 8
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _titles = []
    _episodes = []

    def init_plugin(self, config: dict = None):

        if config:
            self._titles = config.get("titles") or []
            self._episodes = config.get("episodes") or []

        self.stop_service()
        self.clear_history(self._titles, self._episodes)
        config['titles'] = []
        config['episodes'] = []

    def clear_history(self, titles: List[str], episodes: List[str]):
        logger.info(f"清除下载历史记录：{titles} {episodes}")
        data = self.get_download_data()
        downloader_history = {}
        for d in data:
            if d.title in titles or d.id in episodes:
                tmp = downloader_history.get(d.downloader)
                if not tmp:
                    tmp = []
                tmp.append(d)
                downloader_history[d.downloader] = tmp
                logger.info(f"清除下载历史记录：{d.id} {d.title} {d.seasons} {d.episodes} {d.download_hash}")
        for downloader, history in downloader_history.items():
            downloader_obj = self.__get_downloader(downloader)
            # 获取所有历史记录的hash值列表
            history_hashes = [h.download_hash for h in history]
            torrents, error = downloader_obj.get_torrents(ids=history_hashes)
            if error:
                logger.error(f"获取种子信息失败： {error}")
                continue
            history_torrents = {}
            for t in torrents:
                logger.info(f"种子信息: {t}")
                history_torrents[t.hash] = t
            for h in history:
                # 判断当前历史记录的hash是否在未找到的hash列表中
                if h.download_hash not in history_torrents.keys():
                    logger.info(f"种子 {h.download_hash} 已不存在于下载器中")
                    self.delete_data(history=h)
                else:
                    # 从下载器删除种子
                    self.delete_download_history(h, history_torrents[h.download_hash])

    @staticmethod
    def delete_data(history: DownloadHistory):
        """
        从订阅记录中删除该信息
        """
        try:
            down_oper = DownloadHistoryOper()
            down_oper.delete_history(history.id)
            logger.info(
                f"删除下载历史记录：{history.id} {history.title} {history.seasons} {history.episodes} {history.download_hash}")
            return True
        except Exception as e:
            logger.error(f"删除下载历史记录失败：{str(e)}")
            return False

    def delete_download_history(self, history: DownloadHistory, torrent: Any):
        downloader_name = history.downloader
        downloader_obj = self.__get_downloader(downloader_name)
        logger.info(
            f"删除种子信息：{history.id} {history.title} {history.seasons} {history.episodes} {history.download_hash}")
        hashs = [history.download_hash]
        # 处理辅种
        torrents, error = downloader_obj.get_torrents()
        if error:
            logger.error(f"获取辅种信息失败： {error}")
        else:
            for t in torrents:
                if t.name == torrent.name and t.size == torrent.size:
                    hashs.append(t.hash)
        downloader_obj.delete_torrents(delete_file=True, ids=hashs)
        self.delete_data(history)

    def get_state(self) -> bool:
        return True

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        # 获取下载历史数据
        histories = self.get_download_data()

        # 构造标题和剧集列表
        titles = []
        episode_options = []

        for history in histories:
            # 标题列表
            if history.title not in titles:
                titles.append(history.title)

            # 剧集列表
            episode_str = history.title
            if history.seasons:
                episode_str += f" {history.seasons}"
            if history.episodes:
                episode_str += f" {history.episodes}"
            episode_options.append({"title": episode_str, "value": history.id})

        # 将列表转换为选择框选项格式
        title_options = [{"title": t, "value": t} for t in titles]

        # 标题和剧集选择框
        title_select = {
            'component': 'VRow',
            'content': [
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                    },
                    'content': [
                        {
                            'component': 'VSelect',
                            'props': {
                                'model': 'titles',
                                'label': '标题',
                                'items': title_options,
                                'multiple': True,
                                'chips': True,
                                'clearable': True
                            }
                        }
                    ]
                }
            ]
        }

        episode_select = {
            'component': 'VRow',
            'content': [
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                    },
                    'content': [
                        {
                            'component': 'VSelect',
                            'props': {
                                'model': 'episodes',
                                'label': '剧集',
                                'items': episode_options,
                                'multiple': True,
                                'chips': True,
                                'clearable': True
                            }
                        }
                    ]
                }
            ]
        }
        return [
            {
                'component': 'VForm',
                'content': [
                    title_select,
                    episode_select
                ]
            }
        ], {
            "titles": [],
            "episodes": []
        }

    @staticmethod
    def get_download_data() -> List[DownloadHistory]:
        down_oper = DownloadHistoryOper()
        downs = []
        page = 1
        while True:
            data = down_oper.list_by_page(page=page, count=100)
            downs.extend(data)
            if len(data) < 100:
                break
            page += 1
        return downs

    def get_page(self) -> List[dict]:
        items = []
        for down in self.get_download_data():
            items.append({
                'component': 'tr',
                'content': [
                    {
                        'component': 'td',
                        'text': down.id
                    },
                    {
                        'component': 'td',
                        'text': down.title
                    },
                    {
                        'component': 'td',
                        'text': down.seasons + " " + down.episodes
                    },
                    {
                        'component': 'td',
                        'text': down.torrent_name
                    }
                ]
            })

        return [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12
                        },
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [
                                            {
                                                'component': 'tr',
                                                'content': [
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': 'id'
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '名称'
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '剧集'
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-start ps-4'
                                                        },
                                                        'text': '种子名称'
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': items
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def stop_service(self):
        """
        退出插件
        """
        pass

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        services = DownloaderHelper().get_services(type_filter="qbittorrent")
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    def __get_downloader(self, name: str):
        """
        根据类型返回下载器实例
        """
        return self.service_infos.get(name).instance
