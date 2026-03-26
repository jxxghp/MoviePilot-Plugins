import os
import subprocess
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Dict, Any

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from python_hosts import Hosts, HostsEntry
from requests import Response

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from app.utils.ip import IpUtils
from app.utils.system import SystemUtils


class CloudflareSpeedTest(_PluginBase):
    # 插件名称
    plugin_name = "Cloudflare IP优选"
    # 插件描述
    plugin_desc = "🌩 测试 Cloudflare CDN 延迟和速度，自动优选IP。"
    # 插件图标
    plugin_icon = "cloudflare.jpg"
    # 插件版本
    plugin_version = "1.5.1"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "cloudflarespeedtest_"
    # 加载顺序
    plugin_order = 12
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _customhosts = False
    _cf_ip = None
    _scheduler = None
    _cron = None
    _onlyonce = False
    _ipv4 = False
    _ipv6 = False
    _version = None
    _additional_args = None
    _re_install = False
    _notify = False
    _check = False
    _cf_path = None
    _cf_ipv4 = None
    _cf_ipv6 = None
    _result_file = None
    _release_prefix = 'https://github.com/XIU2/CloudflareSpeedTest/releases/download'
    _binary_name = 'cfst'
    _old_binary_name = 'CloudflareST'

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        # 读取配置
        if config:
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._cf_ip = config.get("cf_ip")
            self._version = config.get("version")
            self._ipv4 = config.get("ipv4")
            self._ipv6 = config.get("ipv6")
            self._re_install = config.get("re_install")
            self._additional_args = config.get("additional_args")
            self._notify = config.get("notify")
            self._check = config.get("check")

        if (self._ipv4 or self._ipv6) and self._onlyonce:
            try:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"Cloudflare CDN优选服务启动，立即运行一次")
                self._scheduler.add_job(func=self.__cloudflareSpeedTest, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="Cloudflare优选")
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()
                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()
            except Exception as err:
                logger.error(f"Cloudflare CDN优选服务出错：{str(err)}")
                self.systemmessage.put(f"Cloudflare CDN优选服务出错：{str(err)}", title="Cloudflare IP优选")
                return

    @eventmanager.register(EventType.PluginAction)
    def __cloudflareSpeedTest(self, event: Event = None):
        """
        CloudflareSpeedTest优选
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "cloudflare_speedtest":
                return

        self._cf_path = self.get_data_path()
        self._cf_ipv4 = os.path.join(self._cf_path, "ip.txt")
        self._cf_ipv6 = os.path.join(self._cf_path, "ipv6.txt")
        self._result_file = os.path.join(self._cf_path, "result_hosts.txt")

        # 获取自定义Hosts插件，若无设置则停止
        customHosts = self.get_config("CustomHosts")
        self._customhosts = customHosts and customHosts.get("enabled")
        if self._cf_ip and not customHosts or not customHosts.get("hosts"):
            logger.error(f"Cloudflare CDN优选依赖于自定义Hosts，请先维护hosts")
            return

        if not self._cf_ip:
            logger.error("CloudflareSpeedTest加载成功，首次运行，需要配置优选ip")
            return

        if event and event.event_data:
            logger.info("收到命令，开始Cloudflare IP优选 ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始Cloudflare IP优选 ...",
                              userid=event.event_data.get("user"))

        # ipv4和ipv6必须其一
        if not self._ipv4 and not self._ipv6:
            self._ipv4 = True
            self.__update_config()
            logger.warn(f"Cloudflare CDN优选未指定ip类型，默认ipv4")

        err_flag, release_version = self.__check_environment()
        if err_flag and release_version:
            # 更新版本
            self._version = release_version
            self.__update_config()

        hosts = customHosts.get("hosts")
        if isinstance(hosts, str):
            hosts = str(hosts).split('\n')
        # 校正优选ip
        if self._check:
            self.__check_cf_ip(hosts=hosts)

        # 开始优选
        if err_flag:
            logger.info("正在进行CLoudflare CDN优选，请耐心等待")
            # 执行优选命令，-dd不测速
            if SystemUtils.is_windows():
                cf_command = f'cd \"{self._cf_path}\" && {self._binary_name} {self._additional_args} -o \"{self._result_file}\"' + (
                    f' -f \"{self._cf_ipv4}\"' if self._ipv4 else '') + (
                                 f' -f \"{self._cf_ipv6}\"' if self._ipv6 else '')
                # 兼容旧版本
                if not Path(f'{self._cf_path}/{self._binary_name}.exe').exists() and \
                   Path(f'{self._cf_path}/{self._old_binary_name}.exe').exists():
                    cf_command = f'cd \"{self._cf_path}\" && {self._old_binary_name} {self._additional_args} -o \"{self._result_file}\"' + (
                        f' -f \"{self._cf_ipv4}\"' if self._ipv4 else '') + (
                                     f' -f \"{self._cf_ipv6}\"' if self._ipv6 else '')
            else:
                cf_command = f'cd {self._cf_path} && chmod a+x {self._binary_name} && ./{self._binary_name} {self._additional_args} -o {self._result_file}' + (
                    f' -f {self._cf_ipv4}' if self._ipv4 else '') + (f' -f {self._cf_ipv6}' if self._ipv6 else '')
                # 兼容旧版本
                if not Path(f'{self._cf_path}/{self._binary_name}').exists() and \
                   Path(f'{self._cf_path}/{self._old_binary_name}').exists():
                    cf_command = f'cd {self._cf_path} && chmod a+x {self._old_binary_name} && ./{self._old_binary_name} {self._additional_args} -o {self._result_file}' + (
                        f' -f {self._cf_ipv4}' if self._ipv4 else '') + (f' -f {self._cf_ipv6}' if self._ipv6 else '')
            logger.info(f'正在执行优选命令 {cf_command}')
            if SystemUtils.is_windows():
                process = subprocess.Popen(cf_command, shell=True)
                # 执行命令后无法退出 采用异步和设置超时方案
                # 设置超时时间为120秒
                if cf_command.__contains__("-dd"):
                    time.sleep(120)
                else:
                    time.sleep(600)
                # 如果没有在120秒内完成任务，那么杀死该进程
                if process.poll() is None:
                    os.system(f'taskkill /F /IM {self._binary_name}.exe')
                    # 兼容旧版本
                    if not Path(f'{self._cf_path}/{self._binary_name}.exe').exists():
                        os.system(f'taskkill /F /IM {self._old_binary_name}.exe')
            else:
                os.system(cf_command)

            # 获取优选后最优ip
            if SystemUtils.is_windows():
                powershell_command = f"powershell.exe -Command \"Get-Content \'{self._result_file}\' | Select-Object -Skip 1 -First 1 | Write-Output\""
                logger.info(f'正在执行powershell命令 {powershell_command}')
                best_ip = SystemUtils.execute(powershell_command)
                best_ip = best_ip.split(',')[0]
            else:
                best_ip = SystemUtils.execute("sed -n '2,1p' " + self._result_file + " | awk -F, '{print $1}'")
            logger.info(f"\n获取到最优ip==>[{best_ip}]")

            # 替换自定义Hosts插件数据库hosts
            if IpUtils.is_ipv4(best_ip) or IpUtils.is_ipv6(best_ip):
                if best_ip == self._cf_ip:
                    logger.info(f"CloudflareSpeedTest CDN优选ip未变，不做处理")
                else:
                    # 替换优选ip
                    err_hosts = customHosts.get("err_hosts")

                    # 处理ip
                    new_hosts = []
                    for host in hosts:
                        if host and host != '\n':
                            host_arr = str(host).split()
                            if host_arr[0] == self._cf_ip:
                                new_hosts.append(host.replace(self._cf_ip, best_ip).replace("\n", "") + "\n")
                            else:
                                new_hosts.append(host.replace("\n", "") + "\n")

                    # 更新自定义Hosts
                    self.update_config(
                        {
                            "hosts": ''.join(new_hosts),
                            "err_hosts": err_hosts,
                            "enabled": True
                        }, "CustomHosts"
                    )

                    # 更新优选ip
                    old_ip = self._cf_ip
                    self._cf_ip = best_ip
                    self.__update_config()
                    logger.info(f"Cloudflare CDN优选ip [{best_ip}] 已替换自定义Hosts插件")

                    # 解发自定义hosts插件重载
                    logger.info("通知CustomHosts插件重载 ...")
                    self.eventmanager.send_event(EventType.PluginReload,
                                                 {
                                                     "plugin_id": "CustomHosts"
                                                 })
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【Cloudflare优选任务完成】",
                            text=f"原ip：{old_ip}\n"
                                 f"新ip：{best_ip}"
                        )
        else:
            logger.error("获取到最优ip格式错误，请重试")
            self._onlyonce = False
            self.__update_config()
            self.stop_service()

    def __check_cf_ip(self, hosts):
        """
        校正cf优选ip
        防止特殊情况下cf优选ip和自定义hosts插件中ip不一致
        """
        # 统计每个IP地址出现的次数
        ip_count = {}
        for host in hosts:
            if host:
                ip = host.split()[0]
                if ip in ip_count:
                    ip_count[ip] += 1
                else:
                    ip_count[ip] = 1

        # 找出出现次数最多的IP地址
        max_ips = []  # 保存最多出现的IP地址
        max_count = 0
        for ip, count in ip_count.items():
            if count > max_count:
                max_ips = [ip]  # 更新最多的IP地址
                max_count = count
            elif count == max_count:
                max_ips.append(ip)

        # 如果出现次数最多的ip不止一个，则不做兼容处理
        if len(max_ips) != 1:
            return

        if max_ips[0] != self._cf_ip:
            self._cf_ip = max_ips[0]
            logger.info(f"获取到自定义hosts插件中ip {max_ips[0]} 出现次数最多，已自动校正优选ip")

    def __check_environment(self):
        """
        环境检查
        """
        # 是否安装标识
        install_flag = False

        # 是否重新安装
        if self._re_install:
            install_flag = True
            if SystemUtils.is_windows():
                os.system(f'rd /s /q \"{self._cf_path}\"')
            else:
                os.system(f'rm -rf {self._cf_path}')
            logger.info(f'删除CloudflareSpeedTest目录 {self._cf_path}，开始重新安装')

        # 判断目录是否存在
        cf_path = Path(self._cf_path)
        if not cf_path.exists():
            os.mkdir(self._cf_path)

        # 获取CloudflareSpeedTest最新版本
        release_version = self.__get_release_version()
        if not release_version:
            # 如果升级失败但是有可执行文件CloudflareST，则可继续运行，反之停止
            if Path(f'{self._cf_path}/{self._binary_name}').exists():
                logger.warn(f"获取CloudflareSpeedTest版本失败，存在可执行版本，继续运行")
                return True, None
            elif self._version:
                logger.error(f"获取CloudflareSpeedTest版本失败，获取上次运行版本{self._version}，开始安装")
                install_flag = True
            else:
                release_version = "v2.2.2"
                self._version = release_version
                logger.error(f"获取CloudflareSpeedTest版本失败，获取默认版本{release_version}，开始安装")
                install_flag = True

        # 有更新
        if not install_flag and release_version != self._version:
            logger.info(f"检测到CloudflareSpeedTest有版本[{release_version}]更新，开始安装")
            install_flag = True

        # 重装后数据库有版本数据，但是本地没有则重装
        if not install_flag \
                and release_version == self._version \
                and not Path(
            f'{self._cf_path}/{self._binary_name}').exists() \
                and not Path(f'{self._cf_path}/{self._old_binary_name}').exists() \
                and not Path(f'{self._cf_path}/{self._binary_name}.exe').exists():
            logger.warn(f"未检测到CloudflareSpeedTest本地版本，重新安装")
            install_flag = True

        if not install_flag:
            logger.info(f"CloudflareSpeedTest无新版本，存在可执行版本，继续运行")
            return True, None

        # 检查环境、安装
        if SystemUtils.is_windows():
            # windows
            cf_file_name = f'{self._binary_name}_windows_amd64.zip'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            return self.__os_install(download_url, cf_file_name, release_version,
                                     f"ditto -V -x -k --sequesterRsrc {self._cf_path}/{cf_file_name} {self._cf_path}")
        elif SystemUtils.is_macos():
            # mac
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'{self._binary_name}_darwin_{arch}.zip'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            return self.__os_install(download_url, cf_file_name, release_version,
                                     f"ditto -V -x -k --sequesterRsrc {self._cf_path}/{cf_file_name} {self._cf_path}")
        else:
            # docker
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'{self._binary_name}_linux_{arch}.tar.gz'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            return self.__os_install(download_url, cf_file_name, release_version,
                                     f"tar -zxf {self._cf_path}/{cf_file_name} -C {self._cf_path}")

    def __os_install(self, download_url, cf_file_name, release_version, unzip_command):
        """
        macos docker安装cloudflare
        """
        # 手动下载安装包后，无需在此下载
        if not Path(f'{self._cf_path}/{cf_file_name}').exists():
            # 首次下载或下载新版压缩包
            proxies = settings.PROXY
            https_proxy = proxies.get("https") if proxies and proxies.get("https") else None
            if https_proxy:
                if SystemUtils.is_windows():
                    self.__get_windows_cloudflarest(download_url, proxies)
                else:
                    os.system(
                        f'wget -P {self._cf_path} --no-check-certificate -e use_proxy=yes -e https_proxy={https_proxy} {download_url}')
            else:
                if SystemUtils.is_windows():
                    self.__get_windows_cloudflarest(download_url, proxies)
                else:
                    proxy_host = os.environ.get("PROXY_HOST", "https://ghfast.top")
                    os.system(f'wget -P {self._cf_path} {proxy_host}/{download_url}')

        # 判断是否下载好安装包
        if Path(f'{self._cf_path}/{cf_file_name}').exists():
            try:
                if SystemUtils.is_windows():
                    with zipfile.ZipFile(f'{self._cf_path}/{cf_file_name}', 'r') as zip_ref:
                        # 解压ZIP文件中的所有文件到指定目录
                        zip_ref.extractall(self._cf_path)
                    if Path(f'{self._cf_path}\\{self._binary_name}.exe').exists() or \
                       Path(f'{self._cf_path}\\{self._old_binary_name}.exe').exists():
                        logger.info(f"CloudflareSpeedTest安装成功，当前版本：{release_version}")
                        return True, release_version
                    else:
                        logger.error(f"CloudflareSpeedTest安装失败，请检查")
                        os.system(f'rd /s /q \"{self._cf_path}\"')
                        return False, None
                # 解压
                os.system(f'{unzip_command}')
                # 删除压缩包
                os.system(f'rm -rf {self._cf_path}/{cf_file_name}')
                if Path(f'{self._cf_path}/{self._binary_name}').exists() or \
                   Path(f'{self._cf_path}/{self._old_binary_name}').exists():
                    logger.info(f"CloudflareSpeedTest安装成功，当前版本：{release_version}")
                    return True, release_version
                else:
                    logger.error(f"CloudflareSpeedTest安装失败，请检查")
                    os.removedirs(self._cf_path)
                    return False, None
            except Exception as err:
                # 如果升级失败但是有可执行文件CloudflareST，则可继续运行，反之停止
                if Path(f'{self._cf_path}/{self._binary_name}').exists() or \
                        Path(f'{self._cf_path}\\CloudflareST.exe').exists():
                    logger.error(f"CloudflareSpeedTest安装失败：{str(err)}，继续使用现版本运行")
                    return True, None
                else:
                    logger.error(f"CloudflareSpeedTest安装失败：{str(err)}，无可用版本，停止运行")
                    if SystemUtils.is_windows():
                        os.system(f'rd /s /q \"{self._cf_path}\"')
                    else:
                        os.removedirs(self._cf_path)
                    return False, None
        else:
            # 如果升级失败但是有可执行文件CloudflareST，则可继续运行，反之停止
            if Path(f'{self._cf_path}/{self._binary_name}').exists() or \
                    Path(f'{self._cf_path}\\{self._binary_name}.exe').exists() or \
                    Path(f'{self._cf_path}/{self._old_binary_name}').exists() or \
                    Path(f'{self._cf_path}\\{self._old_binary_name}.exe').exists():
                logger.warn(f"CloudflareSpeedTest安装失败，存在可执行版本，继续运行")
                return True, None
            else:
                logger.error(f"CloudflareSpeedTest安装失败，无可用版本，停止运行")
                if SystemUtils.is_windows():
                    os.system(f'rd /s /q \"{self._cf_path}\"')
                else:
                    os.removedirs(self._cf_path)
                return False, None

    def __get_windows_cloudflarest(self, download_url, proxies):
        response = Response()
        try:
            response = requests.get(download_url, stream=True, proxies=proxies if proxies else None)
        except requests.exceptions.RequestException as e:
            logger.error(f"CloudflareSpeedTest下载失败：{str(e)}")
        if response.status_code == 200:
            with open(f'{self._cf_path}\\{self._binary_name}_windows_amd64.zip', 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

    @staticmethod
    def __get_release_version():
        """
        获取CloudflareSpeedTest最新版本
        """
        version_res = RequestUtils().get_res(
            "https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest")
        if not version_res:
            version_res = RequestUtils(proxies=settings.PROXY).get_res(
                "https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest")
        if version_res:
            ver_json = version_res.json()
            version = f"{ver_json['tag_name']}"
            return version
        else:
            return None

    def __update_config(self):
        """
        更新优选插件配置
        """
        self.update_config({
            "onlyonce": False,
            "cron": self._cron,
            "cf_ip": self._cf_ip,
            "version": self._version,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "re_install": self._re_install,
            "additional_args": self._additional_args,
            "notify": self._notify,
            "check": self._check
        })

    def get_state(self) -> bool:
        return True if self._cf_ip and self._cron and (self._ipv4 or self._ipv6) else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/cloudflare_speedtest",
            "event": EventType.PluginAction,
            "desc": "Cloudflare IP优选",
            "data": {
                "action": "cloudflare_speedtest"
            }
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/cloudflare_speedtest",
            "endpoint": self.cloudflare_speedtest,
            "methods": ["GET"],
            "summary": "Cloudflare IP优选",
            "description": "Cloudflare IP优选",
        }]

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
        if self.get_state():
            return [
                {
                    "id": "CloudflareSpeedTest",
                    "name": "Cloudflare IP优选服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.__cloudflareSpeedTest,
                    "kwargs": {}
                }
            ]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cf_ip',
                                            'label': '优选IP',
                                            'placeholder': '121.121.121.121'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '优选周期',
                                            'placeholder': '0 0 0 ? *'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'version',
                                            'readonly': True,
                                            'label': 'CloudflareSpeedTest版本',
                                            'placeholder': '暂未安装'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ipv4',
                                            'label': 'IPv4',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ipv6',
                                            'label': 'IPv6',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'check',
                                            'label': '自动校准',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 're_install',
                                            'label': '重装后运行',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '运行时通知',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'additional_args',
                                            'label': '高级参数',
                                            'placeholder': '-dd'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': 'F12看请求的Server属性，如果是cloudflare说明该站点支持Cloudflare IP优选。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "cf_ip": "",
            "cron": "",
            "version": "",
            "ipv4": True,
            "ipv6": False,
            "check": False,
            "onlyonce": False,
            "re_install": False,
            "notify": True,
            "additional_args": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def cloudflare_speedtest(self, apikey: str) -> schemas.Response:
        """
        API调用CloudflareSpeedTest IP优选
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        self.__cloudflareSpeedTest()
        return schemas.Response(success=True)

    @staticmethod
    def __read_system_hosts():
        """
        读取系统hosts对象
        """
        # 获取本机hosts路径
        if SystemUtils.is_windows():
            hosts_path = r"c:\windows\system32\drivers\etc\hosts"
        else:
            hosts_path = '/etc/hosts'
        # 读取系统hosts
        return Hosts(path=hosts_path)

    def __add_hosts_to_system(self, hosts):
        """
        添加hosts到系统
        """
        # 系统hosts对象
        system_hosts = self.__read_system_hosts()
        # 过滤掉插件添加的hosts
        orgin_entries = []
        for entry in system_hosts.entries:
            if entry.entry_type == "comment" and entry.comment == "# CustomHostsPlugin":
                break
            orgin_entries.append(entry)
        system_hosts.entries = orgin_entries
        # 新的有效hosts
        new_entrys = []
        # 新的错误的hosts
        err_hosts = []
        err_flag = False
        for host in hosts:
            if not host:
                continue
            host_arr = str(host).split()
            try:
                host_entry = HostsEntry(entry_type='ipv4' if IpUtils.is_ipv4(str(host_arr[0])) else 'ipv6',
                                        address=host_arr[0],
                                        names=host_arr[1:])
                new_entrys.append(host_entry)
            except Exception as err:
                err_hosts.append(host + "\n")
                logger.error(f"[HOST] 格式转换错误：{str(err)}")
                # 推送实时消息
                self.systemmessage.put(f"[HOST] 格式转换错误：{str(err)}", title="Cloudflare IP优选")

        # 写入系统hosts
        if new_entrys:
            try:
                # 添加分隔标识
                system_hosts.add([HostsEntry(entry_type='comment', comment="# CustomHostsPlugin")])
                # 添加新的Hosts
                system_hosts.add(new_entrys)
                system_hosts.write()
                logger.info("更新系统hosts文件成功")
            except Exception as err:
                err_flag = True
                logger.error(f"更新系统hosts文件失败：{str(err) or '请检查权限'}")
                # 推送实时消息
                self.systemmessage.put(f"更新系统hosts文件失败：{str(err) or '请检查权限'}", title="Cloudflare IP优选")
        return err_flag, err_hosts

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
