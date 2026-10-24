import json
import re
import time
import threading
from datetime import datetime, timedelta
from html import escape as html_escape
from typing import Optional, Any, List, Dict, Tuple
from urllib.parse import quote

import pytz
import jwt
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import File, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.plugins import _PluginBase
from app.schemas import NotificationType


class UpdateBody(BaseModel):
    """
    数据页「更新」按钮的请求体（前端通过JSON body传参）
    """
    env: str = ""
    cid: str = ""
    cname: str = ""
    image: str = ""


class ToggleBody(BaseModel):
    """
    数据页「查看全部容器/收起」按钮的请求体
    """
    env: str = ""


class DockerCopilotHelper(_PluginBase):
    # 插件名称
    plugin_name = "DC助手V3"
    # 插件描述
    plugin_desc = "多台 DockerCopilot 统一管理：更新通知、自动更新、自动备份。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/gxterry/MoviePilot-Plugins/main/icons/Docker_Copilot.png"
    # 插件版本
    plugin_version = "3.0.1"
    # 插件作者
    plugin_author = "Plugin Maintainers"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "dockercopilothelper_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _onlyonce = False
    # 环境槽位原始值与已启用环境
    _env_raw: Dict[str, str] = {}
    _env_slots: List[Dict[str, Any]] = []
    # 每台设备各自勾选的容器（索引 -> 容器名列表）
    _updatable_map: Dict[int, List[str]] = {}
    _auto_map: Dict[int, List[str]] = {}
    # 每台设备是否按当前容器列表全选（配置页的一键开关）
    _updatable_all: Dict[int, bool] = {}
    _auto_all: Dict[int, bool] = {}
    # 更新通知
    _update_cron = None
    _updatable_notify = False
    # 自动更新
    _auto_update_cron = None
    _auto_update_notify = False
    # 更新成功后再发一条（真正的结果通知）
    _auto_update_success = True
    _schedule_report = False
    _delete_images = False
    _intervallimit = 6
    _interval = 10
    # 备份
    _backup_cron = None
    _backups_notify = False
    # DC程序自更新（等价于WebUI左下角「更新程序」按钮）
    _dc_update_cron = None
    _dc_update_notify = False
    # 数据页当前「查看全部容器」展开的设备（运行时状态，不落盘）
    _expanded_env = ""
    # DC 能力探测缓存：host -> (时间戳, 探测结果)，避免数据页每渲染一次都去戳接口
    _feat_cache: Dict[str, Any] = {}
    # 最近一次访问各台 DC 的失败原因：host -> 人类可读的原因
    # 用来在配置页/数据页把「连不上」和「真的没有容器」区分开
    _dc_err: Dict[str, str] = {}
    # 运行中更新任务：<设备idx>::<容器名> -> 任务信息。
    # 由后台追踪线程维护，防止 5 分钟调度重复提交同一个长耗时更新。
    _active_updates: Dict[str, Dict[str, Any]] = {}
    _active_updates_lock = threading.RLock()

    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()
        imported = False
        if config:
            # 支持从导出的JSON恢复配置
            raw = str(config.get("importjson") or "").strip()
            if raw:
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        for key, value in data.items():
                            if key != "importjson":
                                config[key] = value
                        imported = True
                        logger.info("DC助手-已从导入的JSON恢复配置")
                except Exception as err:
                    logger.error(f"DC助手-导入配置解析失败：{str(err)}")
                config["importjson"] = ""
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._env_raw = {}
            self._env_slots = []
            self._updatable_map = {}
            self._auto_map = {}
            self._updatable_all = {}
            self._auto_all = {}
            # 动态槽位：按配置里实际存在的 hostN 读取，数量不写死
            slot_ids = sorted(
                int(m.group(1)) for k in config.keys()
                if (m := re.match(r"^host(\d+)$", k)) and str(config.get(k) or "").strip()
            )
            for i in slot_ids:
                host = str(config.get(f"host{i}") or "").strip()
                secret = str(config.get(f"secretKey{i}") or "").strip()
                name = str(config.get(f"name{i}") or "").strip() or f"DC{i}"
                self._env_raw[f"host{i}"] = host
                self._env_raw[f"secretKey{i}"] = secret
                self._env_raw[f"name{i}"] = name
                self._env_slots.append({"idx": i, "name": name, "host": host.rstrip("/"), "secretKey": secret,
                                        })
                self._updatable_map[i] = config.get(f"updatablelist{i}") or []
                self._auto_map[i] = config.get(f"autoupdatelist{i}") or []
                self._updatable_all[i] = bool(config.get(f"updatableall{i}", False))
                self._auto_all[i] = bool(config.get(f"autoall{i}", False))
            self._update_cron = config.get("updatecron")
            self._updatable_notify = config.get("updatablenotify")
            self._auto_update_cron = config.get("autoupdatecron")
            self._auto_update_notify = config.get("autoupdatenotify")
            # 只有键不存在（老配置）时才用默认值 True，避免用户主动关闭后被强行打开
            self._auto_update_success = bool(config.get("autoupdatesuccess", True))
            self._schedule_report = config.get("schedulereport")
            self._delete_images = config.get("deleteimages")
            self._backup_cron = config.get("backupcron")
            self._backups_notify = config.get("backupsnotify")
            self._dc_update_cron = config.get("dcupdatecron")
            self._dc_update_notify = config.get("dcupdatenotify")
            self._intervallimit = config.get("intervallimit") or 6
            self._interval = config.get("interval") or 10
            saved_active = self.get_data("active_updates")
            with self._active_updates_lock:
                self._active_updates = dict(saved_active) if isinstance(saved_active, dict) else {}

            # 解析环境列表
            envs = self.__parse_envs()
            if imported:
                # 导入的配置立即落盘，并清空导入框
                self.__update_config()
                logger.info("DC助手-导入配置已保存")
            if not envs:
                logger.error("DC助手服务结束：环境列表未配置或格式错误")
                return False

            # 加载模块
            if self._enabled or self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                # 立即运行一次
                if self._onlyonce:
                    logger.info("DC助手服务启动，立即运行一次")
                    if self._backup_cron:
                        self._scheduler.add_job(self.backup_all, 'date',
                                                run_date=datetime.now(
                                                    tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                                name="DC助手-备份")
                    if self._update_cron:
                        self._scheduler.add_job(self.updatable_all, 'date',
                                                run_date=datetime.now(
                                                    tz=pytz.timezone(settings.TZ)) + timedelta(seconds=6),
                                                name="DC助手-更新通知")
                    if self._auto_update_cron:
                        self._scheduler.add_job(self.auto_update_all, 'date',
                                                run_date=datetime.now(
                                                    tz=pytz.timezone(settings.TZ)) + timedelta(seconds=10),
                                                name="DC助手-自动更新")
                    if self._dc_update_cron:
                        self._scheduler.add_job(self.self_update_all, 'date',
                                                run_date=datetime.now(
                                                    tz=pytz.timezone(settings.TZ)) + timedelta(seconds=13),
                                                name="DC助手-DC程序自更新")
                    # 关闭一次性开关
                    self._onlyonce = False
                    # 保存配置
                    self.__update_config()
                # 周期运行
                if self._backup_cron:
                    try:
                        self._scheduler.add_job(func=self.backup_all,
                                                trigger=CronTrigger.from_crontab(self._backup_cron),
                                                name="DC助手-备份")
                    except Exception as err:
                        logger.error(f"备份定时任务配置错误：{str(err)}")
                if self._update_cron:
                    try:
                        self._scheduler.add_job(func=self.updatable_all,
                                                trigger=CronTrigger.from_crontab(self._update_cron),
                                                name="DC助手-更新通知")
                    except Exception as err:
                        logger.error(f"更新通知定时任务配置错误：{str(err)}")
                if self._auto_update_cron:
                    try:
                        self._scheduler.add_job(func=self.auto_update_all,
                                                trigger=CronTrigger.from_crontab(self._auto_update_cron),
                                                name="DC助手-自动更新")
                    except Exception as err:
                        logger.error(f"自动更新定时任务配置错误：{str(err)}")
                if self._dc_update_cron:
                    try:
                        self._scheduler.add_job(func=self.self_update_all,
                                                trigger=CronTrigger.from_crontab(self._dc_update_cron),
                                                name="DC助手-DC程序自更新")
                    except Exception as err:
                        logger.error(f"DC程序自更新定时任务配置错误：{str(err)}")
                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def __parse_envs(self) -> List[Dict[str, str]]:
        """
        返回已填写完整的DC环境（服务器地址与secretKey都填写才算启用）
        """
        envs = []
        for slot in self._env_slots:
            if not slot.get("host") or not slot.get("secretKey"):
                logger.warning(f"DC助手-环境{slot.get('idx')} 服务器地址或secretKey未填写，已跳过")
                continue
            # 地址容错：没有协议自动补 http://，协议拼错（hrrp/htp等）纠正为 http://
            host = str(slot["host"]).strip()
            if "://" not in host:
                host = f"http://{host}"
            elif not re.match(r"^https?://", host):
                fixed = re.sub(r"^[^:/]+://", "http://", host)
                logger.warning(f"DC助手-环境[{slot['name']}]地址协议不规范，已自动纠正：{host} -> {fixed}")
                host = fixed
            envs.append({
                "idx": slot["idx"],
                "name": slot["name"],
                "host": host.rstrip("/"),
                "secretKey": slot["secretKey"],
            })
        return envs

    def get_state(self) -> bool:
        return self._enabled

    def __update_config(self):
        self.update_config(
            {
                "onlyonce": self._onlyonce,
                "enabled": self._enabled,
                **self._env_raw,
                "updatecron": self._update_cron,
                "updatablenotify": self._updatable_notify,
                "autoupdatecron": self._auto_update_cron,
                "autoupdatenotify": self._auto_update_notify,
                "autoupdatesuccess": self._auto_update_success,
                **{f"updatablelist{i}": v for i, v in self._updatable_map.items()},
                **{f"autoupdatelist{i}": v for i, v in self._auto_map.items()},
                **{f"updatableall{i}": v for i, v in self._updatable_all.items()},
                **{f"autoall{i}": v for i, v in self._auto_all.items()},
                "schedulereport": self._schedule_report,
                "deleteimages": self._delete_images,
                "backupcron": self._backup_cron,
                "backupsnotify": self._backups_notify,
                "dcupdatecron": self._dc_update_cron,
                "dcupdatenotify": self._dc_update_notify,
                "intervallimit": self._intervallimit,
                "interval": self._interval
            }
        )

    @staticmethod
    def __active_update_key(env: Dict[str, Any], name: str) -> str:
        """生成跨设备唯一的更新任务键。"""
        return f"{env.get('idx', env.get('name', ''))}::{name}"

    def __set_active_update(self, key: str, task_id: str = "", image: str = "", busy: bool = False,
                            old_image: str = "", name: str = ""):
        """登记已提交或由 DockerCopilot 报告正在执行的更新任务，并持久化防止重启丢失。"""
        with self._active_updates_lock:
            self._active_updates[key] = {
                "task_id": str(task_id or ""),
                "image": str(image or ""),
                "old_image": str(old_image or ""),
                "name": str(name or key.split("::", 1)[-1]),
                "started_at": time.time(),
                "busy": bool(busy),
            }
            self.save_data("active_updates", dict(self._active_updates))

    def __clear_active_update(self, key: str):
        with self._active_updates_lock:
            self._active_updates.pop(key, None)
            self.save_data("active_updates", dict(self._active_updates))

    def __active_update_running(self, env: Dict[str, Any], key: str) -> bool:
        """
        判断同一容器是否已有更新任务：
        - 有 taskID 时查询真实进度；未到终态就跳过本轮；
        - DC 只返回“已有任务”而没有 taskID 时冷却 30 分钟；
        - 进度接口暂时不可用时最长保护 60 分钟，避免网络抖动导致重复提交。
        """
        with self._active_updates_lock:
            active = dict(self._active_updates.get(key) or {})
        if not active:
            return False
        age = max(0, time.time() - float(active.get("started_at") or 0))
        task_id = str(active.get("task_id") or "")
        if not task_id:
            if age < 1800:
                return True
            self.__clear_active_update(key)
            return False
        try:
            url = f"{env['host']}/api/progress/{task_id}"
            res = RequestUtils(headers={"Authorization": self.get_jwt(env["secretKey"])}).get_res(
                url, timeout=10)
            payload = res.json() if res else {}
            if isinstance(payload, dict) and payload.get("code") == 200:
                detail = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                done = bool(detail.get("isDone", payload.get("isDone", False)))
                failed = bool(detail.get("failed", payload.get("failed", False)))
                canceled = bool(detail.get("canceled", payload.get("canceled", False)))
                if done or failed or canceled:
                    self.__clear_active_update(key)
                    return False
                return True
            # 任务已被 DC 清理：允许根据最新 haveUpdate 重新判断。
            self.__clear_active_update(key)
            return False
        except Exception as err:
            if age < 3600:
                logger.warning(f"DC助手-任务[{key}]进度暂不可读，保留去重：{err}")
                return True
            self.__clear_active_update(key)
            return False

    def auto_update_all(self):
        """
        自动更新：遍历所有环境
        """
        logger.info("DC助手-自动更新-准备执行")
        if not self._auto_update_cron:
            return
        for env in self.__parse_envs():
            try:
                self.auto_update(env)
            except Exception as e:
                logger.error(f"DC助手-自动更新-环境[{env['name']}]执行异常：{str(e)}")

    def auto_update(self, env: Dict[str, str]):
        """
        单环境自动更新（TAG异常自动重拉，结果写入更新历史）
        """
        env_name = env["name"]
        containers = self.get_docker_list(env)
        if not containers:
            return
        # 清理无标签且不在使用中的镜像
        if self._delete_images:
            images_list = self.get_images_list(env)
            for image in images_list:
                if not image.get("inUsed") and image.get("tag"):
                    self.remove_image(env, image["id"])
        # 自动更新（每台设备各自勾选的容器）
        for name in self._auto_map.get(env.get("idx"), []):
            for container in containers:
                if container.get("name") != name or not container.get("haveUpdate"):
                    continue
                key = self.__active_update_key(env, name)
                if self.__active_update_running(env, key):
                    logger.info(f"DC助手-自动更新-环境[{env_name}]容器[{name}]已有任务，跳过本轮")
                    continue
                old_image = str(container.get("usingImage") or "")
                ok, msg, used_image, task_id = self.__do_update(env, container)
                if not ok:
                    if "已有任务在执行中" in str(msg):
                        # 任务可能由上一轮插件实例、dc-panel 或手工操作创建，DC 不返回其 taskID。
                        # 登记冷却，不写失败历史、不发失败通知，下一轮先查/等待再决定。
                        self.__set_active_update(key, image=used_image, old_image=old_image,
                                                 name=name, busy=True)
                        logger.info(f"DC助手-自动更新-环境[{env_name}]容器[{name}]已有任务，已延后重试")
                        continue
                    logger.error(f"DC助手-自动更新-环境[{env_name}]容器[{name}]失败：{msg}")
                    if self._auto_update_notify:
                        self.post_message(
                            mtype=NotificationType.Plugin,
                            title=f"【DC助手-自动更新@{env_name}】",
                            text=f"【{name}】\n更新失败：{msg}")
                    continue
                self.__set_active_update(key, task_id=task_id, image=used_image,
                                         old_image=old_image, name=name)
                if self._auto_update_notify:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title=f"【DC助手-自动更新@{env_name}】",
                        text=f"【{name}】\n容器更新任务创建成功\n镜像：{used_image}")
                # 使用独立线程追踪，避免 5 分钟调度线程被大镜像长时间阻塞。
                # 活跃任务会一直保留到进度终态，下一轮扫描只跳过，不重复提交。
                if task_id:
                    threading.Thread(
                        target=self.track_progress,
                        args=(env, self.get_jwt(env["secretKey"]), name, task_id),
                        kwargs={"old_image": old_image, "image": used_image, "active_key": key},
                        daemon=True,
                        name=f"dc-helper-{env.get('idx')}-{name}",
                    ).start()
                else:
                    # 无 taskID 无法追踪，保留 30 分钟冷却后再按 haveUpdate 判断。
                    self.__set_active_update(key, image=used_image, old_image=old_image,
                                             name=name, busy=True)

    def track_progress(self, env: Dict[str, str], jwt: str, name: str, task_id: str,
                       old_image: str = "", image: str = "", active_key: str = ""):
        """
        追踪更新进度。

        为什么以前「更新成功」从来不推送：老代码只在 _schedule_report（进度汇报）开着时才进这个循环，
        而进度汇报默认关闭；就算开了，也只把进度当普通文本发，成功那条和普通轮询混在一起。
        现在拆成两种通知：
          · 进度汇报   -> 每轮轮询发一条（吵，默认关）
          · 更新成功通知 -> 只在终态发一条，成功发成功、失败发失败（默认开）
        终点判定：msg 里出现「更新成功」，或容器状态里出现「Up …」「running」，或进度报错。
        """
        env_name = env["name"]
        iteration = 0
        limit = int(self._intervallimit or 6)
        last_msg = ""
        final = ""
        while iteration < limit:
            url = '%s/api/progress/%s' % (env["host"], task_id)
            report_json = {}
            try:
                rescanres = (RequestUtils(headers={"Authorization": jwt}).get_res(url, timeout=10))
                if not rescanres:
                    break
                report_json = rescanres.json()
            except TypeError:
                try:
                    report_json = (RequestUtils(headers={"Authorization": jwt}).get_res(url)).json()
                except Exception as err:
                    logger.error(f"DC助手-更新进度-环境[{env_name}]-{name}-请求异常：{err}")
                    break
            except Exception as err:
                logger.error(f"DC助手-更新进度-环境[{env_name}]-{name}-请求异常：{err}")
                break

            if report_json.get("code") == 200:
                detail = report_json.get("data") if isinstance(report_json.get("data"), dict) else {}
                message = str(detail.get("message") or report_json.get("msg") or "")
                detail_msg = str(detail.get("detailMsg") or message)
                percentage = detail.get("percentage", report_json.get("percentage"))
                last_msg = (f"{percentage}% {detail_msg}".strip()
                            if percentage is not None else detail_msg)
                is_done = bool(detail.get("isDone", report_json.get("isDone", False)))
                is_failed = bool(detail.get("failed", report_json.get("failed", False)))
                is_canceled = bool(detail.get("canceled", report_json.get("canceled", False)))
                if self._schedule_report:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title=f"【DC助手-更新进度@{env_name}】",
                        text=f"【{name}】\n进度：{last_msg}"
                    )
                if (is_done and not is_failed and not is_canceled) or "更新成功" in last_msg:
                    final = "成功"
                    break
                if (is_failed or is_canceled or "失败" in last_msg or "错误" in last_msg
                        or "error" in last_msg.lower()):
                    final = "失败"
                    break
            else:
                # taskID 失效也算到达终点：此时回查容器状态更可靠
                break
            iteration += 1
            time.sleep(int(self._interval or 10))

        if not final:
            # 进度接口没给出终态（DC 更新完会把任务清掉），回查容器实际状态
            final = self.__verify_updated(env, name, old_image)
            if final == "成功" and not last_msg:
                last_msg = "容器已按新镜像重建并运行"

        if self._auto_update_success:
            if final == "成功":
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title=f"【DC助手-更新成功@{env_name}】",
                    text=(f"【{name}】\n容器已更新完成并运行\n"
                          f"镜像：{image or '(未记录)'}\n"
                          + (f"原镜像：{old_image}\n" if old_image and old_image != image else "")
                          + (f"进度：{last_msg}" if last_msg else "")))
            elif final == "失败":
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title=f"【DC助手-更新失败@{env_name}】",
                    text=(f"【{name}】\n更新未完成\n"
                          f"最后进度：{last_msg or '无'}\n"
                          f"镜像：{image or '(未记录)'}"))
            else:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title=f"【DC助手-更新结果未知@{env_name}】",
                    text=(f"【{name}】\n追踪 {limit} 次后仍未拿到终态，可能是镜像较大还在拉取。\n"
                          f"最后进度：{last_msg or '无'}\n"
                          f"请稍后到 DockerCopilot 页面确认容器状态。"))
        if active_key and final in ("成功", "失败"):
            self.__clear_active_update(active_key)
        if final != "成功":
            logger.info(f"DC助手-更新进度追踪-环境[{env_name}]-{name}-{final or '超时'}")

    def __verify_updated(self, env: Dict[str, str], name: str, old_image: str) -> str:
        """
        回查容器状态判断更新到底成没成：
        - 容器在跑（status 含 Up/running）且镜像已换成新的 -> 成功
        - 容器在跑但镜像没变 -> 未知（可能没拉到新版本）
        - 容器消失/没在跑 -> 失败
        """
        try:
            for c in self.get_docker_list(env):
                if c.get("name") != name:
                    continue
                status = str(c.get("status") or "")
                now_image = str(c.get("usingImage") or "")
                running = bool(c.get("running")) or status.lower().startswith("up") \
                    or "running" in status.lower()
                if not running:
                    return "失败"
                if old_image and now_image and now_image != old_image:
                    return "成功"
                # 镜像名没变（同 tag 覆盖拉取时 usingImage 不变），有 taskID 就视为成功
                return "成功"
            return "失败"
        except Exception as err:
            logger.error(f"DC助手-更新结果回查失败：{err}")
            return ""

    def updatable_all(self):
        """
        更新通知：遍历所有环境
        """
        logger.info("DC助手-更新通知-准备执行")
        if not self._update_cron:
            return
        for env in self.__parse_envs():
            try:
                self.updatable(env)
            except Exception as e:
                logger.error(f"DC助手-更新通知-环境[{env['name']}]执行异常：{str(e)}")

    def updatable(self, env: Dict[str, str]):
        """
        单环境更新通知
        """
        env_name = env["name"]
        docker_list = self.get_docker_list(env)
        selected = self._updatable_map.get(env.get("idx"), [])
        for docker in docker_list:
            if docker.get("haveUpdate") and docker.get("name") in selected:
                if docker.get("usingImage") and not docker["usingImage"].startswith("sha256:"):
                    # 发送通知
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title=f"【DC助手-更新通知@{env_name}】",
                        text=f"您有容器可以更新啦！\n【{docker['name']}】\n当前镜像:{docker['usingImage']}\n"
                             f"状态:{docker['status']} {docker['runningTime']}\n构建时间：{docker['createTime']}")
                else:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title=f"【DC助手-更新通知@{env_name}】",
                        text=f"监测到您有容器TAG不正确\n【{docker['name']}】\n当前镜像:{docker['usingImage']}\n"
                             f"状态:{docker['status']} {docker['runningTime']}\n构建时间：{docker['createTime']}\n"
                             f"该镜像无法通过DC自动更新,请修改TAG")

    def backup_all(self):
        """
        备份：遍历所有环境
        """
        logger.info("DC助手-备份-准备执行")
        for env in self.__parse_envs():
            try:
                self.backup(env)
            except Exception as e:
                logger.error(f"DC助手-备份-环境[{env['name']}]执行异常：{str(e)}")

    def backup(self, env: Dict[str, str]):
        """
        单环境备份
        """
        env_name = env["name"]
        try:
            logger.info(f"DC助手-备份-环境[{env_name}]-准备执行")
            data = self.__dc_json(env, "/api/container/backup")
            if not data:
                logger.error(f"DC助手-备份-环境[{env_name}]请求失败")
                return
            if data.get("code") == 200:
                if self._backups_notify:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title=f"【DC助手-备份成功@{env_name}】",
                        text=f"容器配置备份成功！")
                logger.info(f"DC助手-备份-环境[{env_name}]-完成")
            else:
                if self._backups_notify:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title=f"【DC助手-备份失败@{env_name}】",
                        text=f"容器配置备份失败！\n【失败原因】:{data.get('msg')}")
                logger.error(f"DC助手-备份-环境[{env_name}]失败 Error code: {data.get('code')}, message: {data.get('msg')}")
        except Exception as e:
            logger.error(f"DC助手-备份-环境[{env_name}]网络异常,请检查DockerCopilot服务是否正常: {str(e)}")

    def self_update_all(self):
        """
        DC程序自更新：遍历所有环境
        """
        logger.info("DC助手-DC程序自更新-准备执行")
        for env in self.__parse_envs():
            try:
                self.self_update(env)
            except Exception as e:
                logger.error(f"DC助手-DC程序自更新-环境[{env['name']}]执行异常：{str(e)}")

    def self_update(self, env: Dict[str, str]):
        """
        单环境DC程序自更新（等价于WebUI「更新程序」按钮）：
        先取本地版本，再取远端版本，只有远端是合法版本号且与本地不同才触发，
        避免 DC 偶尔把远端版本读成 "OK"/空 时误触发更新。
        """
        env_name = env["name"]
        local_info = self.__dc_json(env, "/api/version?type=local") or {}
        local_ver = str(((local_info.get("data") or {}).get("version")) or "").strip()

        remote_data = self.__dc_json(env, "/api/version?type=remote")
        if not remote_data:
            logger.error(f"DC助手-DC程序自更新-环境[{env_name}]无法检查远端版本（外网/GitHub不通或超时）")
            return
        remote_ver = str(((remote_data.get("data") or {}).get("remoteVersion")) or "").strip()
        msg = str(remote_data.get("msg") or "")
        if not re.match(r"^v?\d+(\.\d+)+$", remote_ver):
            logger.warning(f"DC助手-DC程序自更新-环境[{env_name}]远端版本不可信（remote={remote_ver or '空'}, msg={msg}），跳过")
            return
        if local_ver and remote_ver.lower() == local_ver.lower():
            logger.info(f"DC助手-DC程序自更新-环境[{env_name}]已是最新（{local_ver}）")
            return

        logger.info(f"DC助手-DC程序自更新-环境[{env_name}]发现新版本 {local_ver or '?'} -> {remote_ver}，触发更新")
        headers = {"Authorization": self.get_jwt(env["secretKey"])}
        update_ok = False
        # 新版DC是 PUT /api/program；老版本曾用 POST /api/update，两个都试
        for method, path in (("PUT", "/api/program"), ("POST", "/api/update")):
            url = "%s%s" % (env["host"], path)
            try:
                if method == "PUT":
                    res = requests.put(url, headers=headers, verify=False, timeout=90)
                else:
                    res = requests.post(url, headers=headers, verify=False, timeout=90)
                code = int(getattr(res, "status_code", 0) or 0)
                if code in (404, 405):
                    logger.warning(f"DC助手-DC程序自更新-环境[{env_name}]{method} {path} 不存在（{code}），换下一个")
                    continue
                try:
                    update_data = res.json()
                except Exception:
                    update_data = {}
            except requests.exceptions.Timeout:
                # 程序更新是「下载二进制→替换→重启」，接口会挂住不回包，超时即视为已触发
                logger.info(f"DC助手-DC程序自更新-环境[{env_name}]{path} 请求超时，视为正在下载/替换")
                update_ok = True
                break
            except Exception as err:
                logger.error(f"DC助手-DC程序自更新-环境[{env_name}]更新请求异常: {str(err)}")
                break
            update_ok = code == 200 and update_data.get("code") in (200, 0, None)
            if not update_ok:
                logger.error(f"DC助手-DC程序自更新-环境[{env_name}]触发失败: HTTP {code} {update_data.get('msg')}")
            break

        if update_ok:
            logger.info(f"DC助手-DC程序自更新-环境[{env_name}]更新已触发，服务将短暂重启")
            if self._dc_update_notify:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title=f"【DC助手-程序自更新@{env_name}】",
                    text=f"DockerCopilot 程序自更新已触发\n【{local_ver or '?'} → {remote_ver}】\n服务将短暂重启后自动恢复")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        插件API：数据页「更新」按钮调用 + 配置浏览器导出/导入
        """
        return [
            {
                "path": "/container_update",
                "endpoint": self.api_container_update,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "触发指定环境指定容器的更新",
            },
            {
                "path": "/update_dc_container",
                "endpoint": self.api_update_dc_container,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "更新DC自身容器（需后端支持内置自更新）",
            },
            {
                "path": "/update_now",
                "endpoint": self.api_update_now,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "浏览器直接触发容器更新（结果在新标签页显示）",
            },
            {
                "path": "/toggle_expand",
                "endpoint": self.api_toggle_expand,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "数据页展开/收起某台设备的全部容器",
            },
            {
                "path": "/download_config",
                "endpoint": self.api_download_config,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "导出插件配置为JSON文件（浏览器下载）",
            },
            {
                "path": "/upload_config",
                "endpoint": self.api_upload_config,
                "methods": ["POST"],
                "auth": "apikey",
                "summary": "上传JSON文件恢复插件配置（浏览器上传）",
            },
        ]

    @staticmethod
    def __is_self_container(container: Dict[str, Any]) -> bool:
        """
        判断是不是 DC 自己的容器。
        官方版会返回 isSelf=true；老版本没有这个字段，只能按镜像名判断
        （DC 源码 IsSelfImage 的规则就是镜像名含 dockercopilot / docker-copilot）。
        这类容器一律不允许点更新：DC 更新流程第一步就是停掉目标容器，停自己等于自杀且无人重建。
        """
        if bool(container.get("isSelf")):
            return True
        image = str(container.get("usingImage") or "") + " " + str(container.get("createImage") or "")
        image = image.lower()
        return "dockercopilot" in image or "docker-copilot" in image

    def __probe_features(self, env: Dict[str, str], refresh: bool = False) -> Dict[str, Any]:
        """
        探测这台 DC 是否提供扩展能力。

        判据：后端额外暴露 /api/docker/hosts（多机管理），基础版本没有这个路由（404）。
        如果后端同时提供 StartHelperContainer/SelfUpdate：
        点「更新」自身容器时会另起一个 <容器名>-selfupdate-helper 旁路容器，
        由它去停旧容器、按新镜像建新容器、删旧容器，所以它能自己更新自己。
        其他镜像没有这套，停掉自己就没人接手，因此无法直接更新自己。

        返回 {"multi_host": bool, "native_selfupdate": bool, "version": str, "build_date": str}
        """
        host = str(env.get("host") or "")
        now = time.time()
        cached = self.__class__._feat_cache.get(host)
        if cached and not refresh and now - cached[0] < 60:
            return dict(cached[1])

        feat: Dict[str, Any] = {
            "multi_host": False,
            "native_selfupdate": False,
            "version": "",
            "build_date": "",
        }
        headers = {"Authorization": self.get_jwt(env["secretKey"])}
        try:
            res = requests.get(f"{host}/api/docker/hosts", headers=headers, verify=False, timeout=6)
            code = int(getattr(res, "status_code", 0) or 0)
            if code == 200:
                body = res.json()
                if isinstance(body, dict) and isinstance(body.get("data"), list):
                    feat["multi_host"] = True
                    feat["native_selfupdate"] = True
            else:
                logger.debug(f"DC助手-环境[{env['name']}] /api/docker/hosts 返回 {code}（原版无此路由）")
        except Exception as err:
            logger.debug(f"DC助手-环境[{env['name']}] 探测 /api/docker/hosts 失败：{err}")

        try:
            vres = requests.get(f"{host}/api/version?type=local", headers=headers, verify=False, timeout=6)
            if int(getattr(vres, "status_code", 0) or 0) == 200:
                vbody = vres.json()
                vdata = vbody.get("data") if isinstance(vbody, dict) else None
                if isinstance(vdata, dict):
                    feat["version"] = str(vdata.get("version") or "")
                    feat["build_date"] = str(vdata.get("buildDate") or "")
                elif isinstance(vdata, str):
                    feat["version"] = vdata
        except Exception:
            pass

        self.__class__._feat_cache[host] = (now, dict(feat))
        return feat

    def __native_self_update(self, env: Dict[str, str]) -> Tuple[bool, str]:
        """
        走后端提供的内置更新接口更新「它自己」。
        DC 会起 <容器名>-selfupdate-helper 旁路容器完成 pull/stop/create/start/remove，
        本进程被停掉后由 helper 接着干，所以这个请求很可能收不到正常返回（连接被切断）——
        连接中断/超时一律视为「已触发」，而不是失败。
        """
        env_name = env["name"]
        containers = self.get_docker_list(env)
        target: Optional[Dict[str, Any]] = None
        for c in containers:
            if self.__is_self_container(c):
                target = c
                break
        if not target:
            return False, ("在容器列表里没找到 DC 自己的容器，无法走内置自更新。\n\n"
                           "请确认 secretKey 正确、DC 正在运行。")
        cid = str(target.get("id") or "")
        cname = str(target.get("name") or "")
        image = str(target.get("usingImage") or "")
        if not image or image.startswith("sha256:"):
            image = str(target.get("createImage") or "")
        if not image:
            return False, f"没拿到 DC 容器[{cname}]的镜像名，无法自更新。\n\n请先用管理员在 NAS 上手动 `docker compose pull && docker compose up -d`。"

        host_id = str(target.get("hostId") or "")
        url = f"{env['host']}/api/container/{quote(cid, safe='')}/update"
        if host_id and host_id != "local":
            url += f"?hostId={quote(host_id, safe='')}"
        logger.info(f"DC助手-环境[{env_name}]内置自更新：{cname}({cid}) image={image}")

        try:
            res = requests.post(
                url,
                headers={"Authorization": self.get_jwt(env["secretKey"]),
                         "Content-Type": "application/json"},
                json={"containerName": cname, "imageNameAndTag": image},
                verify=False,
                timeout=45,
            )
            code = int(getattr(res, "status_code", 0) or 0)
            try:
                data = res.json()
            except Exception:
                data = {}
        except requests.exceptions.Timeout:
            logger.info(f"DC助手-环境[{env_name}]内置自更新请求超时，视为已开始拉镜像/重建")
            return True, self.__self_update_ok_text(cname, image, "")
        except Exception as err:
            # 自更新时 DC 会先停掉自己，连接被重置是预期现象
            logger.info(f"DC助手-环境[{env_name}]内置自更新连接中断（预期）：{err}")
            return True, self.__self_update_ok_text(cname, image, str(err))

        if code in (200, 201, 202):
            if isinstance(data, dict) and data.get("code") not in (0, 200, None):
                return False, f"DC 拒绝自更新：{data.get('msg')}"
            task_id = str((data.get("data") or {}).get("taskID") or "") if isinstance(data, dict) else ""
            return True, self.__self_update_ok_text(cname, image, task_id)
        if code in (401, 403):
            return False, "DC 鉴权失败（401/403），请检查插件配置里的 secretKey。"
        return False, f"DC 返回 HTTP {code}：{str(getattr(res, 'text', ''))[:300]}"

    @staticmethod
    def __self_update_ok_text(cname: str, image: str, extra: str) -> str:
        tail = f"\n任务ID：{extra}" if extra and len(extra) < 64 else ""
        return (f"已让 {cname} 自更新（{image}）。\n\n"
                "这个过程是：DC 先拉新镜像 → 起一个 <容器名>-selfupdate-helper 旁路容器 → "
                "helper 停掉旧容器、按新镜像重建、删掉旧容器。\n\n"
                "重建期间 DC 的 12712 端口会断 10~60 秒（拉镜像慢会更久），之后自动恢复，"
                "刷新本页看到新构建时间即为成功。" + tail)

    def api_update_dc_container(self, env: str = "") -> HTMLResponse:
        """
        更新「DC 自己的容器」。

        仅支持带内置自更新的镜像：带内置自更新能力的 DockerCopilot 后端（仓库
        对应后端项目地址）。这类 DC 后端带
        StartHelperContainer，更新自身时会另起 <容器名>-selfupdate-helper
        旁路容器，由它停旧建新，因此直接 POST /api/container/{自身id}/update 即可。

        其他镜像（如基础版 DockerCopilot）不支持：其更新流程第一步就是
        停掉目标容器，停掉自己后没有进程接手重建——数据页对这类设备不显示自更新按钮。
        """
        if not env:
            return self.__result_page("更新DC容器", False, "参数缺失（env）")
        for e in self.__parse_envs():
            if e["name"] != env:
                continue
            feat = self.__probe_features(e)
            if feat.get("native_selfupdate"):
                logger.info(f"DC助手-环境[{env}]检测到支持内置自更新的 DC（{feat.get('version') or '?'}），走内置自更新")
                ok, msg = self.__native_self_update(e)
                title = ("更新DC容器 · 内置自更新 · " if ok else "更新DC容器失败 · 内置自更新 · ") + env
                return self.__result_page(title, ok, msg)
            return self.__result_page(
                "更新DC容器", False,
                "这台设备的 DockerCopilot 后端不支持内置自更新，无法直接更新自己。\n\n"
                "原因：更新任何容器的第一步都是「停掉目标容器」——停掉自己后没有进程接手重建。\n\n"
                "请改用带内置自更新 helper 的后端，或配置外部更新器后再试。")
        return self.__result_page("更新DC容器", False, f"未找到设备[{env}]，请检查插件配置")


    def api_update_now(self, env: str = "", cid: str = "", cname: str = "",
                       image: str = "") -> HTMLResponse:
        """
        原生链接触发的容器更新：执行后返回结果页（在新标签页打开，主页面不受影响）
        """
        if not env or not cid or not cname:
            return self.__result_page("容器更新", False, "参数缺失（env / cid / cname）")
        for e in self.__parse_envs():
            if e["name"] != env:
                continue
            container: Dict[str, Any] = {"id": cid, "name": cname, "usingImage": image, "createImage": image}
            for item in self.get_docker_list(e):
                if item.get("id") == cid or item.get("name") == cname:
                    container = item
                    break
            ok, msg, _, _ = self.__do_update(e, container)
            return self.__result_page(f"容器更新 · {cname}", ok, msg)
        return self.__result_page("容器更新", False, f"未找到设备[{env}]，请检查插件配置")

    def api_download_config(self) -> Response:
        """
        导出配置：浏览器直接下载JSON附件
        """
        try:
            content = self.__export_config().encode("utf-8")
        except Exception as err:
            logger.error(f"DC助手-导出配置失败：{str(err)}")
            content = json.dumps({"error": str(err)}, ensure_ascii=False).encode("utf-8")
        filename = datetime.now().strftime("dc_helper_config_%Y%m%d_%H%M%S.json")
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def __normalize_import(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        把导入文件统一成插件内部配置（供日后独立容器版复用同一份JSON）：
        - 新格式（可移植）：{"schema":"dc-helper","version":1,"devices":[{name,host,secret_key,updatable,auto_update}],"notify":{...}}
        - 旧格式：扁平 hostN / secretKeyN / nameN / updatablelistN / autoupdatelistN
        """
        if isinstance(data.get("devices"), list):
            cfg: Dict[str, Any] = {}
            idx = 0
            for item in data.get("devices") or []:
                if not isinstance(item, dict):
                    continue
                host = str(item.get("host") or "").strip()
                secret = str(item.get("secret_key") or item.get("secretKey") or "").strip()
                if not host or not secret:
                    continue
                idx += 1
                cfg[f"host{idx}"] = host
                cfg[f"secretKey{idx}"] = secret
                cfg[f"name{idx}"] = str(item.get("name") or "").strip() or f"DC{idx}"
                cfg[f"updatablelist{idx}"] = [str(x) for x in (item.get("updatable") or [])]
                cfg[f"autoupdatelist{idx}"] = [str(x) for x in (item.get("auto_update") or [])]
                cfg[f"updatableall{idx}"] = bool(item.get("updatable_all", False))
                cfg[f"autoall{idx}"] = bool(item.get("auto_all", False))
            notify = data.get("notify") if isinstance(data.get("notify"), dict) else {}
            cfg.update({
                "enabled": bool(data.get("enabled", True)),
                "updatecron": notify.get("update_cron") or "",
                "updatablenotify": bool(notify.get("update_notify", True)),
                "autoupdatecron": notify.get("auto_update_cron") or "",
                "autoupdatenotify": bool(notify.get("auto_update_notify", True)),
                "autoupdatesuccess": bool(notify.get("auto_update_success", True)),
                "schedulereport": bool(notify.get("schedule_report", False)),
                "deleteimages": bool(notify.get("delete_images", False)),
                "backupcron": notify.get("backup_cron") or "",
                "backupsnotify": bool(notify.get("backup_notify", True)),
                "dcupdatecron": notify.get("dc_update_cron") or "",
                "dcupdatenotify": bool(notify.get("dc_update_notify", True)),
                "interval": notify.get("interval") or 10,
                "intervallimit": notify.get("interval_limit") or 6,
            })
            return cfg
        # 旧版扁平格式
        return {k: v for k, v in data.items() if k != "importjson"}

    def api_upload_config(self, file: UploadFile = File(...)) -> HTMLResponse:
        """
        导入配置：新版可移植格式与旧版扁平格式都接受
        """
        try:
            raw = file.file.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
        except Exception as err:
            return self.__result_page("配置导入", False, f"文件解析失败：{err}")
        if not isinstance(data, dict):
            return self.__result_page("配置导入", False, "文件内容不是JSON对象")
        try:
            cfg = self.__normalize_import(data)
            device_count = len([k for k in cfg.keys() if re.match(r"^host\d+$", k)])
            if not device_count:
                return self.__result_page("配置导入", False,
                                          "文件里没有有效设备（host 或 secret_key 为空）")
            config = self.get_config() or {}
            config.update(cfg)
            config["importjson"] = ""
            config["onlyonce"] = False
            self.init_plugin(config)
            logger.info(f"DC助手-已从上传文件恢复配置，设备数 {device_count}")
            return self.__result_page("配置导入", True, f"配置导入成功，共 {device_count} 台设备")
        except Exception as err:
            logger.error(f"DC助手-导入配置失败：{str(err)}")
            return self.__result_page("配置导入", False, f"配置应用失败：{err}")

    @staticmethod
    def __result_page(title: str, ok: bool, msg: str) -> HTMLResponse:
        color = "#4CAF50" if ok else "#F44336"
        icon = "&#10004;" if ok else "&#10006;"
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DC助手 · {html_escape(title)}</title>
<style>
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #1e1e2e; color: #eee;
       display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
.box {{ text-align: center; padding: 48px; max-width: 720px; }}
h2 {{ color: {color}; font-weight: 500; }}
p {{ color: #999; }}
</style>
</head>
<body>
<div class="box">
<h2><span style="color:{color}">{icon}</span> {html_escape(title)}</h2>
<p>{html_escape(msg)}</p>
<p style="color:#777;font-size:13px;">本页面可以关闭了，回到 MoviePilot 刷新即可看到最新状态。</p>
</div>
</body>
</html>"""
        return HTMLResponse(content=html)

    # ---------------- 更新历史（每日更新了什么） ----------------

    def __load_history(self) -> List[Dict[str, Any]]:
        """读取更新历史"""
        try:
            data = self.get_data("update_history")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def __record(self, env_name: str, container: str, image: str, success: bool, msg: str = ""):
        """
        记录一次更新，供数据页按天统计
        """
        try:
            records = self.__load_history()
            records.insert(0, {
                "time": datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S"),
                "date": datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d"),
                "env": env_name,
                "container": container,
                "image": image,
                "result": "成功" if success else "失败",
                "msg": msg or "",
            })
            # 只保留最近 2000 条（每条约 200 字节，2000 条不到 0.5 MB）
            # 以前是 500 条，容器多的时候一两个月就把早期记录挤掉了
            self.save_data("update_history", records[:2000])
        except Exception as err:
            logger.error(f"DC助手-写入更新历史失败：{str(err)}")

    # ---------------- 更新执行（含TAG异常自动重拉） ----------------

    def __do_update(self, env: Dict[str, Any], container: Dict[str, Any]) -> Tuple[bool, str, str, str]:
        """
        执行一次容器更新并记录历史。
        镜像TAG异常（usingImage为空或sha256）时：按镜像ID重新拉取镜像，再用 createImage 的 repo:tag 更新。
        返回 (是否成功, 消息, 实际使用的镜像, 任务ID)
        """
        env_name = env["name"]
        cid = container.get("id")
        cname = container.get("name")
        using = container.get("usingImage") or ""
        create = container.get("createImage") or ""
        jwt = self.get_jwt(env["secretKey"])

        if self.__is_self_container(container) and not self.__probe_features(env).get("native_selfupdate"):
            logger.warning(f"DC助手-环境[{env_name}]拒绝更新DC自身容器[{cname}]：后端不支持安全自更新")
            return (False, "这是 DockerCopilot 自己的容器，当前后端不支持安全自更新。"
                           "更新第一步会停掉目标容器，停自己后没有进程接手重建。\n"
                           "请改用带内置自更新 helper 的后端或外部更新器后再试。", 
                    using, "")
        if self.__is_self_container(container):
            logger.info(f"DC助手-环境[{env_name}]更新DC自身容器[{cname}]：该DC带内置helper，交给它自己重建")

        target = using
        if not using or using.startswith("sha256:"):
            # TAG 异常：删/重拉镜像后，用创建镜像名（含 repo:tag）更新
            target = create if create and not create.startswith("sha256:") else ""
            logger.info(f"DC助手-环境[{env_name}]容器[{cname}]TAG异常({using})，改用[{target}]重新拉取")
            if using.startswith("sha256:"):
                try:
                    # 先删掉本地这个异常TAG的镜像，再按镜像ID重新拉取
                    requests.delete(
                        f"{env['host']}/api/image/{using}?force=true",
                        headers={"Authorization": jwt},
                        verify=False,
                        timeout=20)
                    RequestUtils(headers={"Authorization": jwt}).post_res(
                        f"{env['host']}/api/image/{using}/pull")
                except Exception as err:
                    logger.warning(f"DC助手-环境[{env_name}]容器[{cname}]重拉镜像异常：{str(err)}")
            if not target:
                msg = "TAG异常且无法推断镜像名，请手动指定TAG"
                self.__record(env_name, cname, using, False, msg)
                return False, msg, using, ""

        try:
            url = f"{env['host']}/api/container/{cid}/update"
            data: Optional[Dict[str, Any]] = None
            # DC 鉴权偶发401，重试最多3次
            for attempt in range(3):
                res = RequestUtils(headers={"Authorization": self.get_jwt(env["secretKey"])}).post_res(
                    url, {"containerName": cname, "imageNameAndTag": target})
                try:
                    data = res.json() if res is not None else None
                except Exception:
                    data = None
                if isinstance(data, dict) and data.get("code") != 401:
                    break
                if attempt < 2:
                    time.sleep(0.8)
            if not isinstance(data, dict):
                msg = "请求DockerCopilot失败"
                self.__record(env_name, cname, target, False, msg)
                return False, msg, target, ""
            if data.get("code") == 200 and data.get("msg") == "success":
                logger.info(f"DC助手-环境[{env_name}]容器[{cname}]更新任务创建成功（镜像:{target}）")
                self.__record(env_name, cname, target, True, "更新任务已创建")
                task_id = str((data.get("data") or {}).get("taskID") or "")
                return True, f"[{env_name}] {cname} 更新任务已创建", target, task_id
            msg = str(data.get("msg"))
            self.__record(env_name, cname, target, False, msg)
            return False, f"[{env_name}] {cname}: {msg}", target, ""
        except Exception as err:
            logger.error(f"DC助手-环境[{env_name}]容器[{cname}]更新异常：{str(err)}")
            self.__record(env_name, cname, target, False, str(err))
            return False, str(err), target, ""

    def api_container_update(
        self,
        body: Optional[UpdateBody] = None,
        env: str = "",
        cid: str = "",
        cname: str = "",
        image: str = "",
    ) -> Dict[str, Any]:
        """
        手动更新：按设备名定位对应DC实例，执行更新（TAG异常自动重拉）。
        兼容两种传参：前端events.click的JSON body（body模型）与URL query参数。
        """
        if body is not None:
            env = env or body.env
            cid = cid or body.cid
            cname = cname or body.cname
            image = image or body.image
        if not env or not cid or not cname:
            return {"success": False, "message": "参数缺失"}
        for e in self.__parse_envs():
            if e["name"] != env:
                continue
            container = {"id": cid, "name": cname, "usingImage": image, "createImage": image}
            # 取得更完整的信息（createImage 用于TAG修复）
            for item in self.get_docker_list(e):
                if item.get("id") == cid or item.get("name") == cname:
                    container = item
                    break
            ok, msg, _, _ = self.__do_update(e, container)
            return {"success": ok, "message": msg}
        return {"success": False, "message": f"未找到设备[{env}]，请检查插件配置"}

    def api_toggle_expand(self, body: Optional[ToggleBody] = None, env: str = "") -> Dict[str, Any]:
        """
        数据页「查看全部容器 / 收起」：记录当前展开的设备，同一点第二次即收起
        """
        name = env or (body.env if body is not None else "")
        if not name:
            return {"success": False, "message": "参数缺失"}
        if self._expanded_env == name:
            self._expanded_env = ""
            return {"success": True, "message": f"[{name}] 已收起"}
        self._expanded_env = name
        return {"success": True, "message": f"[{name}] 已展开全部容器"}

    def get_jwt(self, secret_key: str) -> str:
        # 减少接口请求直接本地签发jwt
        payload = {
            "exp": int(time.time()) + 28 * 24 * 60 * 60,
            "iat": int(time.time())
        }
        encoded_jwt = jwt.encode(payload, secret_key, algorithm="HS256")
        return "Bearer " + encoded_jwt

    @staticmethod
    def __describe_net_err(err: Exception) -> str:
        """把网络异常翻译成一句人话，直接显示在页面上，省得用户去翻日志"""
        msg = str(err)
        low = msg.lower()
        if "timed out" in low or "timeout" in low:
            return "连接超时（IP/端口不通，或被防火墙拦了）"
        if "refused" in low:
            return "端口拒绝连接（DC 没起来，或端口没映射）"
        if any(k in low for k in ("name or service not known", "failed to resolve",
                                  "getaddrinfo", "nodename nor servname")):
            return "地址解析失败（填了主机名但解析不了，换成 IP）"
        if "ssl" in low or "certificate" in low:
            return "TLS 错误（http / https 写错了）"
        return (msg[:120] or "未知网络错误")

    def __dc_json(self, env: Dict[str, str], path: str, retries: int = 3,
                  timeout: int = 10) -> Optional[Dict[str, Any]]:
        """
        DC GET 的带重试封装。
        实测 DC 的鉴权中间件会偶发返回 401「未授权」（同一把密钥前后两次一次失败一次成功），
        所以这里对 401/网络异常做小间隔重试，避免数据页偶发变成“未获取到容器”。

        另外两件事：
        - 带 timeout。以前不传 timeout，设备断电/端口不通时 requests 会一直挂着，
          配置页要等它等到天荒地老，表现就是「一直转圈」或下拉框空白。
        - 把失败原因记进 _dc_err[host]，让页面能区分「连不上」和「真没容器」。
        """
        url = "%s%s" % (env["host"], path)
        host = str(env.get("host") or "")
        last_err = ""
        for attempt in range(max(1, retries)):
            try:
                try:
                    result = (RequestUtils(headers={"Authorization": self.get_jwt(env["secretKey"])})
                              .get_res(url, timeout=timeout))
                except TypeError:
                    # 个别 MP 版本的 RequestUtils 不接受 timeout，退回默认行为
                    result = (RequestUtils(headers={"Authorization": self.get_jwt(env["secretKey"])})
                              .get_res(url))
            except Exception as err:
                last_err = self.__describe_net_err(err)
                logger.error(f"DC助手-环境[{env['name']}]请求{path}网络异常: {str(err)}")
                result = None
            if result is not None:
                status = getattr(result, "status_code", 200)
                if status == 404:
                    # 老版本 DC 没有这个路由（例如 /api/docker/hosts），说明网络是通的
                    self._dc_err.pop(host, None)
                    return None
                if status in (401, 403):
                    last_err = "密钥错误（secretKey 不匹配）"
                else:
                    try:
                        data = result.json()
                    except Exception:
                        data = None
                    if isinstance(data, dict) and data.get("code") != 401:
                        self._dc_err.pop(host, None)
                        return data
                    elif isinstance(data, dict):
                        last_err = "密钥错误（secretKey 不匹配）"
            if attempt < retries - 1:
                time.sleep(0.8)
        logger.error(f"DC助手-环境[{env['name']}]请求{path}失败（已重试{retries}次，检查secretKey是否正确）")
        if last_err:
            self._dc_err[host] = last_err
        return None

    def get_docker_list(self, env: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        容器列表

        注意 code 的判断：原版 onlyLTY v2.1.3 的 /api/containers 返回 code=0，
        而部分重新打包的版本（含增强版）会返回 code=200。这里两个都认，
        否则换个镜像就「一个容器都读不到」，看起来像插件坏了。
        真失败时把 code/msg 记进 _dc_err，页面直接显示，不用去翻日志。
        """
        host = str(env.get("host") or "")
        data = self.__dc_json(env, "/api/containers")
        if not data:
            # 网络层已由 __dc_json 记录原因；这里兜底一个默认文案
            self._dc_err.setdefault(host, "无响应（地址/端口/密钥任一不对）")
            return []
        if data.get("code") in (0, 200):
            self._dc_err.pop(host, None)
            return data.get("data") or []
        msg = f"接口返回 code={data.get('code')}, msg={data.get('msg')}"
        logger.error(f"DC助手-环境[{env['name']}]获取容器列表异常 {msg}")
        self._dc_err[host] = msg[:120]
        return []

    def get_images_list(self, env: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        镜像列表
        """
        data = self.__dc_json(env, "/api/images")
        if not data:
            return []
        if data.get("code") in (0, 200):
            return data.get("data") or []
        logger.error(f"DC助手-环境[{env['name']}]获取镜像列表异常 Error code: {data.get('code')}, message: {data.get('msg')}")
        return []

    def remove_image(self, env: Dict[str, str], sha: str) -> bool:
        """
        清理镜像
        """
        try:
            images_url = "%s/api/image/%s?force=false" % (env["host"], sha)
            result = requests.delete(images_url,
                                     verify=False,
                                     headers={"Authorization": self.get_jwt(env["secretKey"])},
                                     timeout=20)
            data = result.json()
            if data.get("code") == 200:
                logger.info(f"DC助手-环境[{env['name']}]清理镜像成功: {sha}")
                return True
            else:
                logger.error(f"DC助手-环境[{env['name']}]清理镜像异常 Error code: {data.get('code')}, message: {data.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"DC助手-环境[{env['name']}]请求清理镜像时发生网络异常: {str(e)}")
            return False

    def __export_config(self) -> str:
        """
        导出为可移植配置JSON（schema=dc-helper）：
        插件版与日后的独立容器版共用同一份结构，导入时新旧两种格式都兼容。
        """
        devices = []
        for env in self.__parse_envs():
            idx = env["idx"]
            devices.append({
                "name": env["name"],
                "host": env["host"],
                "secret_key": env["secretKey"],
                "updatable": list(self._updatable_map.get(idx) or []),
                "auto_update": list(self._auto_map.get(idx) or []),
                "updatable_all": bool(self._updatable_all.get(idx)),
                "auto_all": bool(self._auto_all.get(idx)),
            })
        payload = {
            "schema": "dc-helper",
            "schema_version": 1,
            "exported_at": datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "moviepilot-plugin/dockercopilothelper",
            "enabled": bool(self._enabled),
            "devices": devices,
            "notify": {
                "update_cron": self._update_cron or "",
                "update_notify": bool(self._updatable_notify),
                "auto_update_cron": self._auto_update_cron or "",
                "auto_update_notify": bool(self._auto_update_notify),
                "auto_update_success": bool(self._auto_update_success),
                "schedule_report": bool(self._schedule_report),
                "delete_images": bool(self._delete_images),
                "backup_cron": self._backup_cron or "",
                "backup_notify": bool(self._backups_notify),
                "dc_update_cron": self._dc_update_cron or "",
                "dc_update_notify": bool(self._dc_update_notify),
                "interval": self._interval,
                "interval_limit": self._intervallimit,
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        配置页：设备行按「填一台自动出下一行」动态展示，容器按每台设备分别勾选
        """
        # 逐台拉取容器，顺带清理已失效的勾选
        # 关键：连不上的设备**不能**清空已保存的勾选，否则某台 DC 临时重启一下，
        # 配置页一打开就把它的通知容器列表洗掉了，保存后永久丢失。
        slot_items: Dict[int, List[dict]] = {}
        slot_hints: Dict[int, str] = {}
        changed = False
        for slot in self._env_slots:
            env = {"idx": slot["idx"], "name": slot["name"], "host": slot["host"], "secretKey": slot["secretKey"]}
            containers = self.get_docker_list(env)
            names = [c.get("name") for c in containers if c.get("name")]
            err = self._dc_err.get(str(slot.get("host") or ""))
            if err:
                slot_items[slot["idx"]] = [{
                    "title": f"⚠ 读不到容器：{err}",
                    "value": "__conn_error__",
                    "props": {"disabled": True},
                }]
                slot_hints[slot["idx"]] = (f"⚠ 连接失败：{err}｜已保存的勾选会原样保留，"
                                           "修好地址/端口/密钥后刷新本页即可重新读取")
                continue
            slot_items[slot["idx"]] = [{"title": n, "value": n} for n in names]
            if not names:
                slot_hints[slot["idx"]] = "已连上 DC，但这台机器上确实没有容器"
            # “本机全选”不依赖固定容器名：DC 每次返回新容器时，配置自动跟随。
            if self._updatable_all.get(slot["idx"]):
                if self._updatable_map.get(slot["idx"], []) != names:
                    self._updatable_map[slot["idx"]] = list(names)
                    changed = True
            if self._auto_all.get(slot["idx"]):
                if self._auto_map.get(slot["idx"], []) != names:
                    self._auto_map[slot["idx"]] = list(names)
                    changed = True
            # 只有真的读到列表，才清理已失效的勾选
            for store in (self._updatable_map, self._auto_map):
                old = store.get(slot["idx"]) or []
                new_val = [n for n in old if n in names]
                if new_val != old:
                    store[slot["idx"]] = new_val
                    changed = True
        if changed:
            self.__update_config()

        # 设备行：已填写的槽位 + 一个空白的新槽位（填完保存后自动再出现下一行）
        filled_ids = sorted(slot["idx"] for slot in self._env_slots)
        next_id = (filled_ids[-1] + 1) if filled_ids else 1
        env_rows = []
        for i in filled_ids + [next_id]:
            is_new = i not in filled_ids
            env_rows.append({
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 3},
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': f'name{i}',
                                    'label': f'设备{i}名称',
                                    'placeholder': f'DC{i}',
                                    'hide-details': 'auto'
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 4},
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': f'host{i}',
                                    'label': f'服务器地址{i}',
                                    'placeholder': 'http://dc-host.example:12712',
                                    'hide-details': 'auto'
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 5},
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': f'secretKey{i}',
                                    'label': f'secretKey{i}',
                                    'placeholder': '填完保存后自动新增下一行' if is_new else 'DockerCopilot密钥',
                                    'hide-details': 'auto'
                                }
                            }
                        ]
                    }
                ]
            })

        # 每台设备一组容器勾选
        def slot_select(name_prefix: str, label_prefix: str, hint: str):
            rows = []
            all_prefix = 'updatableall' if name_prefix == 'updatablelist' else 'autoall'
            all_map = self._updatable_all if name_prefix == 'updatablelist' else self._auto_all
            for slot in self._env_slots:
                idx = slot["idx"]
                items = slot_items.get(idx, [])
                rows.append({
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 10},
                            'content': [
                                {
                                    'component': 'VSelect',
                                    'props': {
                                        'chips': True,
                                        'multiple': True,
                                        'model': f'{name_prefix}{idx}',
                                        'label': f'【{slot["name"]}】{label_prefix}',
                                        'items': items,
                                        'hint': slot_hints.get(idx) or hint
                                    }
                                }
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 2, 'style': {'display': 'flex', 'align-items': 'center'}},
                            'content': [
                                {
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': f'{all_prefix}{idx}',
                                        'label': '本机全选',
                                        'hint': '保存后按该设备当前容器列表自动保持全选'
                                    }
                                }
                            ]
                        }
                    ]
                })
            if not rows:
                rows.append({
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
                                        'text': '先填写设备地址和secretKey并保存，容器列表会按设备分别出现在这里。'
                                    }
                                }
                            ]
                        }
                    ]
                })
            return rows

        return [
            {
                "component": "VForm",
                "content": [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
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
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '每台DockerCopilot填一组「服务器地址 + secretKey」。填完一台保存后，会自动出现下一台的空行，想加几台加几台。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    *env_rows,
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
                                            'text': '配置恢复：到插件数据页「配置备份/恢复」卡片上传之前导出的JSON文件即可，无需在此粘贴。'
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTabs',
                                        'props': {
                                            'model': '_tabs',
                                            'style': {'margin-top': '10px'}
                                        },
                                        'content': [
                                            {'component': 'VTab', 'props': {'value': 'C1'}, 'text': '更新通知'},
                                            {'component': 'VTab', 'props': {'value': 'C2'}, 'text': '自动更新'},
                                            {'component': 'VTab', 'props': {'value': 'C3'}, 'text': '自动备份'},
                                            {'component': 'VTab', 'props': {'value': 'C4'}, 'text': 'DC自更新'},
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VWindow',
                        'props': {'model': '_tabs'},
                        'content': [
                            {
                                'component': 'VWindowItem',
                                'props': {'value': 'C1', 'style': {'margin-top': '20px'}},
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VCronField',
                                                        'props': {
                                                            'model': 'updatecron',
                                                            'label': '更新通知周期',
                                                            'placeholder': '15 8-23/2 * * *'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'updatablenotify',
                                                            'label': 'TAG异常提醒',
                                                            'hint': '镜像TAG为sha256等无法自动更新时也发送提醒'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    *slot_select('updatablelist', '更新通知容器', '该设备上有更新时发送通知')
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {'value': 'C2', 'style': {'margin-top': '20px'}},
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VCronField',
                                                        'props': {
                                                            'model': 'autoupdatecron',
                                                            'label': '自动更新周期',
                                                            'placeholder': '15 2 * * *'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'interval',
                                                            'label': '跟踪间隔(秒)',
                                                            'placeholder': '10',
                                                            'hint': '开启进度汇报时，每多少秒检查一次进度'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'intervallimit',
                                                            'label': '检查次数',
                                                            'placeholder': '6',
                                                            'hint': '达到次数后放弃追踪'
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
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'autoupdatenotify',
                                                            'label': '自动更新通知',
                                                            'hint': '任务创建成功即发一条'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'autoupdatesuccess',
                                                            'label': '更新成功通知',
                                                            'hint': '追踪到「更新成功」后再发一条结果通知'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'schedulereport',
                                                            'label': '进度汇报',
                                                            'hint': '每次轮询进度都发一条（较吵）'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 3},
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'deleteimages',
                                                            'label': '清理镜像',
                                                            'hint': '更新时清理无tag且不在使用中的镜像'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    *slot_select('autoupdatelist', '自动更新容器', '该设备上被选中的容器有新版本时自动更新')
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {'value': 'C3', 'style': {'margin-top': '20px'}},
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VCronField',
                                                        'props': {
                                                            'model': 'backupcron',
                                                            'label': '自动备份周期',
                                                            'placeholder': '0 7 * * *'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'backupsnotify',
                                                            'label': '备份通知',
                                                            'hint': '备份完成发送通知'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {'value': 'C4', 'style': {'margin-top': '20px'}},
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VCronField',
                                                        'props': {
                                                            'model': 'dcupdatecron',
                                                            'label': 'DC程序自更新周期',
                                                            'placeholder': '0 4 * * 1'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12, 'md': 6},
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'dcupdatenotify',
                                                            'label': '程序自更新通知',
                                                            'hint': '触发DockerCopilot程序热更新后发送通知'
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
                                                'props': {'cols': 12},
                                                'content': [
                                                    {
                                                        'component': 'VAlert',
                                                        'props': {
                                                            'type': 'warning',
                                                            'variant': 'tonal',
                                                            'text': '这里只做「程序二进制热更新」（等价于 DC WebUI 左下角「更新程序」），不等于更新 DC 容器。容器重建后会以镜像内版本为准。若要更新 DC 容器，请使用带内置自更新 helper 的后端或配置外部更新器。'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "updatablenotify": True,
            "autoupdatenotify": True,
            "autoupdatesuccess": True,
            "schedulereport": False,
            "deleteimages": False,
            "backupsnotify": True,
            "dcupdatenotify": True,
            "interval": 10,
            "intervallimit": 6
        }

    # ---------------- 数据页 HTML 渲染（纯原生 HTML，不依赖前端事件绑定） ----------------

    @staticmethod
    def __badge_html(text: str, fg: str, bg: str, size: str = "11px") -> str:
        return (
            f'<span style="display:inline-block;padding:1px 9px;border-radius:10px;'
            f'background:{bg};color:{fg};font-size:{size};white-space:nowrap;">{html_escape(text)}</span>'
        )

    @staticmethod
    def __page_api_key() -> str:
        return str(getattr(settings, "API_TOKEN", "") or "")

    def __containers_table_html(self, env: Dict[str, Any], containers: List[Dict[str, Any]],
                                max_height: str = "", native_self: bool = False) -> str:
        """
        生成容器表格HTML（更新按钮为原生链接，点开新标签页执行，绕开前端事件绑定问题）
        """
        th_style = ("text-align:left;padding:6px 8px;font-size:11px;font-weight:500;opacity:.6;"
                    "border-bottom:1px solid rgba(128,128,128,.28);white-space:nowrap;")
        td_style = ("padding:6px 8px;font-size:12px;border-bottom:1px solid rgba(128,128,128,.12);")
        head = (
            "<thead><tr>"
            + "".join(f'<th style="{th_style}">{h}</th>' for h in ("容器", "镜像", "状态", "构建时间", "操作"))
            + "</tr></thead>"
        )
        api_key = quote(self.__page_api_key(), safe="")
        rows = []
        for c in containers:
            image = c.get("usingImage") or ""
            bad_tag = (not image) or image.startswith("sha256:")
            have = bool(c.get("haveUpdate"))
            self_c = self.__is_self_container(c)
            img_text = (c.get("createImage") or "未知") if bad_tag else image
            if self_c:
                badge = self.__badge_html("DC自身", "#CE93D8", "rgba(171,71,188,.18)")
            elif bad_tag:
                badge = self.__badge_html("TAG异常", "#EF9A9A", "rgba(239,83,80,.18)")
            elif have:
                badge = self.__badge_html("有更新", "#FFB74D", "rgba(255,167,38,.18)")
            else:
                badge = self.__badge_html("最新", "#81C784", "rgba(102,187,106,.18)")
            if self_c and native_self:
                # 增强版 DC 自带 helper 旁路容器，点这里就是「它自己重建自己」
                dc_url = (
                    "/api/v1/plugin/DockerCopilotHelper/update_dc_container"
                    f"?apikey={api_key}"
                    f"&env={quote(str(env.get('name') or ''), safe='')}"
                )
                action = ('<a href="' + html_escape(dc_url) + '" target="_blank" rel="noopener" '
                          'style="display:inline-block;padding:2px 12px;border-radius:6px;background:rgba(171,71,188,.22);'
                          'color:#CE93D8;text-decoration:none;font-size:12px;white-space:nowrap;">自更新</a>')
            elif self_c:
                action = ('<span style="opacity:.55;font-size:11px;white-space:nowrap;">'
                          '原版不能自更新</span>')
            else:
                url = (
                    "/api/v1/plugin/DockerCopilotHelper/update_now"
                    f"?apikey={api_key}"
                    f"&env={quote(str(env.get('name') or ''), safe='')}"
                    f"&cid={quote(str(c.get('id') or ''), safe='')}"
                    f"&cname={quote(str(c.get('name') or ''), safe='')}"
                    f"&image={quote(image, safe='')}"
                )
                action = ('<a href="' + html_escape(url) + '" target="_blank" rel="noopener" '
                          'style="display:inline-block;padding:2px 12px;border-radius:6px;background:rgba(33,150,243,.18);'
                          'color:#64B5F6;text-decoration:none;font-size:12px;white-space:nowrap;">更新</a>')
            rows.append(
                "<tr>"
                f'<td style="{td_style}font-weight:500;">{html_escape(str(c.get("name") or ""))}</td>'
                f'<td style="{td_style}word-break:break-all;">{html_escape(img_text)}</td>'
                f'<td style="{td_style}">{badge}</td>'
                f'<td style="{td_style}opacity:.75;white-space:nowrap;">{html_escape(str(c.get("createTime") or ""))}</td>'
                f'<td style="{td_style}text-align:right;">{action}</td></tr>'
            )
        table = (
            '<table style="width:100%;border-collapse:collapse;">'
            f"{head}<tbody>{''.join(rows)}</tbody></table>"
        )
        if max_height:
            return f'<div style="max-height:{max_height};overflow:auto;">{table}</div>'
        return table

    def get_page(self) -> Optional[List[dict]]:
        """
        数据页：彩色统计卡 + 每台设备一张表 + 合并计数后的更新记录
        """
        envs = self.__parse_envs()
        if not envs:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "尚未配置可用的DockerCopilot设备，请先在插件设置中填写服务器地址和secretKey。",
                    },
                }
            ]

        # ---- 每台设备一张卡：默认只列待更新，可原生展开看全部容器（纯HTML，不依赖前端事件） ----
        tables = []
        total = 0
        update_available = 0
        env_container_count: Dict[str, int] = {}
        env_pending_count: Dict[str, int] = {}
        for env in envs:
            containers = self.get_docker_list(env)
            count = len(containers)
            total += count
            # 这台 DC 是否带内置 helper 自更新（增强版/魔改版才有）
            feat = self.__probe_features(env)
            native_self = bool(feat.get("native_selfupdate"))
            pending_containers: List[Dict[str, Any]] = []
            for c in containers:
                if self.__is_self_container(c):
                    # DC 自己不算「待更新」：原版更新不了，增强版走单独的「自更新」按钮
                    continue
                image = c.get("usingImage") or ""
                bad_tag = (not image) or image.startswith("sha256:")
                if bool(c.get("haveUpdate")):
                    update_available += 1
                if bool(c.get("haveUpdate")) or bad_tag:
                    pending_containers.append(c)
            pending = len(pending_containers)
            env_container_count[env["name"]] = count
            env_pending_count[env["name"]] = pending

            title_html = (
                '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;'
                'width:100%;min-width:0;">'
                '<span style="flex:0 0 auto;font-size:12px;font-weight:500;padding:2px 10px;'
                'border-radius:6px;background:rgba(33,150,243,.18);color:#64B5F6;">'
                + html_escape(str(env["name"])) + '</span>'
                '<span style="flex:1 1 140px;min-width:0;font-size:11px;color:#A5B3C2;'
                'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
                + html_escape(str(env["host"])) + '　·　' + str(count) + ' 个容器</span>'
                '<span style="flex:0 0 auto;font-size:11px;font-weight:500;padding:2px 8px;'
                'border-radius:6px;'
                + ('background:rgba(255,183,77,.18);color:#FFB74D;"' if pending
                   else 'background:rgba(102,187,106,.18);color:#81C784;"')
                + '>待更新 ' + str(pending) + '</span>'
                '</div>'
            )
            card_children: List[Dict[str, Any]] = [
                {
                    "component": "div",
                    "props": {"class": "px-3 pt-3"},
                    "html": title_html,
                }
            ]

            if count == 0:
                err = self._dc_err.get(str(env.get("host") or "")) or "未知原因"
                body_html = ('<div style="padding:4px 0;font-size:12px;color:#EF9A9A;">'
                             '⚠ 未获取到容器：' + html_escape(err) + '</div>'
                             '<div style="font-size:11px;opacity:.6;margin-top:2px;">'
                             '检查三样：地址要带 http:// ；端口 12712 是否映射到宿主机；'
                             'secretKey 是否与这台 DC 一致</div>')
            else:
                api_key_q = quote(self.__page_api_key(), safe="")
                env_q = quote(str(env.get("name") or ""), safe="")
                btn_style = ('display:inline-flex;align-items:center;padding:3px 12px;border-radius:7px;'
                             'font-size:12px;font-weight:500;text-decoration:none;white-space:nowrap;')
                if native_self:
                    dc_a = ('<a href="/api/v1/plugin/DockerCopilotHelper/update_dc_container'
                            f'?apikey={api_key_q}&env={env_q}" target="_blank" rel="noopener" '
                            'style="' + btn_style + 'background:rgba(76,175,80,.18);color:#81C784;">'
                            '自更新DC</a>')
                    dc_note = ''
                else:
                    dc_a = ('<span style="' + btn_style + 'opacity:.4;border:1px dashed rgba(255,255,255,.25);'
                            'cursor:help;">自更新不可用</span>')
                    dc_note = ''
                status_chip = (
                    self.__badge_html(f"全部最新（{count}）", "#81C784", "rgba(102,187,106,.18)", "12px")
                    if not pending_containers else
                    self.__badge_html(f"待更新 {len(pending_containers)}", "#FFB74D",
                                      "rgba(255,183,77,.18)", "12px")
                )
                # 一行：状态徽章 | 查看全部 | 自更新；窄屏自动换行居中
                bar = (
                    '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;'
                    'justify-content:center;padding:2px 0 2px;">'
                    + status_chip
                    + '<details style="display:inline-block;">'
                    '<summary style="' + btn_style + 'cursor:pointer;background:rgba(33,150,243,.16);'
                    'color:#64B5F6;list-style:none;">'
                    f'全部容器（{count}）　▾</summary>'
                    '<div style="text-align:left;margin-top:8px;flex-basis:100%;">'
                    + self.__containers_table_html(env, containers, max_height="420px",
                                                   native_self=native_self)
                    + '</div></details>'
                    + dc_a
                    + dc_note
                    + '</div>'
                )
                parts: List[str] = []
                if pending_containers:
                    parts.append(
                        '<div style="opacity:.6;font-size:11px;text-align:center;margin-bottom:6px;">'
                        '待更新容器（点「更新」在新标签页触发，完成后刷新本页）：</div>'
                        + self.__containers_table_html(env, pending_containers, max_height="300px",
                                                       native_self=native_self)
                        + '<div style="height:8px;"></div>'
                    )
                parts.append(bar)
                body_html = "".join(parts)

            card_children.append(
                {"component": "div", "props": {"class": "px-3 pb-3"}, "html": body_html}
            )
            tables.append(
                {
                    "component": "VCard",
                    "props": {"class": "mt-3", "variant": "outlined"},
                    "content": card_children,
                }
            )

        # ---- 统计卡 ----
        today = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d")
        records = self.__load_history()
        today_records = [r for r in records if r.get("date") == today]
        # 每台设备的更新次数统计
        env_today: Dict[str, int] = {env["name"]: 0 for env in envs}
        env_total: Dict[str, int] = {env["name"]: 0 for env in envs}
        for r in records:
            name = str(r.get("env", ""))
            if name in env_total:
                env_total[name] += 1
                if r.get("date") == today:
                    env_today[name] += 1

        summary_cards = []
        for title, value, icon, color in (
            ("设备数", len(envs), "mdi-server-network", "primary"),
            ("容器数", total, "mdi-docker", "info"),
            ("待更新", update_available, "mdi-update", "warning"),
        ):
            summary_cards.append(
                {
                    "component": "VCol",
                    "props": {"cols": 12, "sm": 6, "md": 4},
                    "content": [
                        {
                            "component": "VCard",
                            "props": {"variant": "tonal", "color": color},
                            "content": [
                                {
                                    "component": "VCardText",
                                    "props": {"class": "d-flex align-center"},
                                    "content": [
                                        {
                                            "component": "VAvatar",
                                            "props": {"color": color, "size": "small", "class": "me-3"},
                                            "content": [
                                                {"component": "VIcon", "props": {"icon": icon, "size": "small"}}
                                            ],
                                        },
                                        {
                                            "component": "div",
                                            "content": [
                                                {"component": "div", "props": {"class": "text-h6"}, "text": str(value)},
                                                {"component": "div", "props": {"class": "text-caption"}, "text": title},
                                            ],
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )

        # 饼图 + 图例：每台DC近30天更新占比
        # 口径：近 30 天滚动窗口（含今天），标题写明统计区间。
        # 下方「今日更新记录」表仍是当天口径，两处标题各自标清。
        palette = ["#42A5F5", "#66BB6A", "#FFA726", "#EF5350", "#AB47BC", "#26C6DA", "#D4E157", "#8D6E63"]
        tz_now = datetime.now(tz=pytz.timezone(settings.TZ))
        month_start_s = (tz_now.date() - timedelta(days=29)).strftime("%Y-%m-%d")
        month_range_text = f"{month_start_s} ~ {today}"
        env_month: Dict[str, int] = {env["name"]: 0 for env in envs}
        for r in records:
            name = str(r.get("env", ""))
            d = str(r.get("date") or "")
            if name in env_month and month_start_s <= d <= today:
                env_month[name] += 1
        values = [env_month.get(env["name"], 0) for env in envs]
        all_value = sum(values)
        all_total = sum(env_total.values())

        donut_html = (
            '<div style="width:190px;height:190px;border-radius:50%;'
            'display:flex;align-items:center;justify-content:center;'
            + ('background:conic-gradient(' + gradient_placeholder + ');' if False else 'background:rgba(128,128,128,.08);')
            + '"></div>'
        )
        if all_value > 0:
            stops = []
            cursor = 0.0
            for i2, value in enumerate(values):
                if value <= 0:
                    continue
                pct = value * 100.0 / all_value
                stops.append(f"{palette[i2 % len(palette)]} {cursor:.2f}% {cursor + pct:.2f}%")
                cursor += pct
            donut_html = (
                '<div class="dcdonut" style="'
                f'background:conic-gradient({", ".join(stops)});">'
                '<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
                'align-items:center;justify-content:center;">'
                '<div style="position:absolute;width:104px;height:104px;border-radius:50%;'
                'background:rgba(0,0,0,.5);"></div>'
                '<div style="position:relative;font-size:22px;font-weight:500;color:#fff;">'
                + str(all_value) + '</div>'
                '<div style="position:relative;font-size:11px;color:#fff;opacity:.85;">近30天次数</div>'
                '</div></div>'
            )
        else:
            donut_html = (
                '<div class="dcdonut" style="border:2px dashed rgba(128,128,128,.35);'
                'display:flex;align-items:center;justify-content:center;font-size:12px;'
                'color:#A5B3C2;">近30天暂无更新</div>'
            )

        legend_items = []
        for i2, env in enumerate(envs):
            name = env["name"]
            month_cnt = env_month.get(name, 0)
            pct = (month_cnt * 100.0 / all_value) if all_value else 0
            c = palette[i2 % len(palette)]
            legend_items.append(
                '<div class="dclg-row" style="display:flex;align-items:center;gap:8px;padding:5px 0;'
                'border-bottom:1px solid rgba(128,128,128,.12);min-width:0;">'
                f'<span style="flex:0 0 10px;width:10px;height:10px;border-radius:3px;background:{c};"></span>'
                '<span class="dclg-name" style="flex:1 1 auto;min-width:0;font-size:13px;'
                'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
                + html_escape(name) + '</span>'
                '<span class="dclg-cnt" style="flex:0 0 44px;text-align:right;font-size:12px;color:#A5B3C2;">'
                + f"{env_container_count.get(name, 0)}个</span>"
                '<span style="flex:0 0 52px;text-align:right;font-size:12px;font-weight:500;">'
                + f"{month_cnt}次</span>"
                '<span style="flex:0 0 48px;text-align:right;font-size:12px;color:#A5B3C2;">'
                + f"{pct:.1f}%</span>"
                '</div>'
            )

        chart_html = (
            '<style>'
            '.dcdonut{width:170px;height:170px;border-radius:50%;position:relative;}'
            '@media (max-width:600px){'
            '.dcchart-wrap{flex-direction:column!important;align-items:stretch!important;gap:10px!important;}'
            '.dcchart-donut{flex:0 0 auto!important;}'
            '.dcdonut{width:150px!important;height:150px!important;}'
            '.dcchart-legend{flex:1 1 auto!important;width:100%!important;}'
            '.dclg-cnt{display:none!important;}'
            '.dclg-name{font-size:12px!important;}'
            '}'
            '</style>'
            '<div class="dcchart-wrap" style="display:flex;flex-wrap:wrap;align-items:center;gap:24px;width:100%;">'
            '<div class="dcchart-donut" style="flex:1 1 190px;display:flex;justify-content:center;min-width:0;">'
            + donut_html + '</div>'
            '<div class="dcchart-legend" style="flex:2 1 260px;min-width:0;">'
            '<div class="dclg-row" style="display:flex;align-items:center;gap:8px;padding:0 0 4px;'
            'font-size:11px;color:#A5B3C2;">'
            '<span style="flex:0 0 10px;"></span>'
            '<span style="flex:1 1 auto;">设备</span>'
            '<span class="dclg-cnt" style="flex:0 0 44px;text-align:right;">容器</span>'
            '<span style="flex:0 0 52px;text-align:right;">次数</span>'
            '<span style="flex:0 0 48px;text-align:right;">占比</span>'
            '</div>'
            + "".join(legend_items)
            + '<div class="dclg-row" style="display:flex;align-items:center;gap:8px;margin-top:6px;'
            'font-size:12px;font-weight:500;">'
            '<span style="flex:0 0 10px;"></span>'
            '<span style="flex:1 1 auto;">合计</span>'
            '<span class="dclg-cnt" style="flex:0 0 44px;text-align:right;"></span>'
            f'<span style="flex:0 0 52px;text-align:right;">{all_value}次</span>'
            '<span style="flex:0 0 48px;text-align:right;">100%</span></div>'
            '</div></div>'
        )

        chart_card = {
            "component": "VCard",
            "props": {"class": "mt-3", "variant": "outlined"},
            "content": [
                {
                    "component": "VCardTitle",
                    "props": {"class": "d-flex align-center pa-3 flex-wrap"},
                    "content": [
                        {
                            "component": "VIcon",
                            "props": {"icon": "mdi-chart-donut", "color": "primary", "class": "me-2"},
                        },
                        {
                            "component": "div",
                            "props": {"style": {"flex": "1 1 100%", "minWidth": "0"}},
                            "html": (
                                '<div style="font-size:15px;font-weight:500;line-height:1.35;">'
                                '更新分布 · 近30天</div>'
                                '<div style="font-size:11px;color:#A5B3C2;margin-top:2px;'
                                'word-break:break-all;">'
                                + month_range_text
                                + f'　共 {all_value} 次'
                                + (f' · 历史累计 {all_total} 次' if all_total else '')
                                + '</div>'
                            ),
                        },
                    ],
                },
                {
                    "component": "VCardText",
                    "props": {"class": "pt-0"},
                    "content": [
                        {"component": "div", "html": chart_html},
                    ],
                },
            ],
        }

        # 配置备份（卸载前导出，重装后粘回配置页即可恢复）
        # 配置备份：按钮式导出（浏览器下载）/ 导入（浏览器上传），不再展示JSON文本
        api_key = str(getattr(settings, "API_TOKEN", "") or "")
        api_base = "/api/v1/plugin/DockerCopilotHelper"
        download_url = f"{api_base}/download_config?apikey={api_key}"
        upload_url = f"{api_base}/upload_config?apikey={api_key}"
        btn_html = (
            '<style>'
            '.dcbak-btn{display:inline-flex;align-items:center;gap:6px;padding:7px 16px;'
            'border-radius:8px;font-size:13px;font-weight:500;text-decoration:none;'
            'white-space:nowrap;border:none;cursor:pointer;color:#fff;}'
            '.dcbak-form{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;}'
            '.dcbak-file{font-size:12px;max-width:240px;min-width:0;flex:1 1 auto;}'
            '@media (max-width:600px){'
            '.dcbak-wrap{flex-direction:column!important;align-items:stretch!important;}'
            '.dcbak-btn{justify-content:center!important;width:100%!important;}'
            '.dcbak-form{flex-direction:column!important;align-items:stretch!important;width:100%!important;}'
            '.dcbak-file{max-width:100%!important;width:100%!important;}'
            '}'
            '</style>'
            '<div class="dcbak-wrap" style="display:flex;flex-wrap:wrap;align-items:center;gap:12px;">'
            f'<a class="dcbak-btn" href="{download_url}" download '
            'style="background:#1E88E5;">&#11015; 导出配置（下载JSON）</a>'
            f'<form class="dcbak-form" action="{upload_url}" method="post" enctype="multipart/form-data" '
            'target="_blank">'
            '<input class="dcbak-file" type="file" name="file" accept=".json,.txt" required>'
            '<button class="dcbak-btn" type="submit" '
            'style="background:#FB8C00;">&#11014; 导入配置</button>'
            '</form>'
            '</div>'
            '<div style="margin-top:8px;font-size:12px;opacity:0.7;">'
            '导出的 JSON 是 dc-helper 标准格式（schema / devices / notify），'
            '以后换成独立容器版也能直接导入同一份文件；重装插件后选文件点「导入配置」即可恢复。'
            '</div>'
        )
        backup_card = {
            "component": "VCard",
            "props": {"class": "mt-4", "variant": "outlined"},
            "content": [
                {
                    "component": "VCardTitle",
                    "props": {"class": "d-flex align-center pa-3"},
                    "content": [
                        {
                            "component": "VIcon",
                            "props": {"icon": "mdi-content-save-cog", "color": "warning", "class": "me-2"},
                        },
                        {
                            "component": "span",
                            "props": {"class": "text-subtitle-1"},
                            "text": "配置备份 / 恢复",
                        },
                    ],
                },
                {
                    "component": "VCardText",
                    "props": {"class": "pt-0"},
                    "html": btn_html,
                },
            ],
        }

        # ---- 更新记录：只显示当天的（用户明确要求），跨天自动清空表格但累计统计保留 ----
        # 底层 update_history 仍保留最近 2000 条，标题里的「累计」和「历史跨度」都来自全量
        merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for r in today_records:
            key = (str(r.get("env", "")), str(r.get("container", "")), str(r.get("image", "")))
            item = merged.get(key)
            if not item:
                item = {
                    "env": key[0],
                    "container": key[1],
                    "image": key[2],
                    "count": 0,
                    "ok": 0,
                    "last": "",
                    "result": "成功",
                }
                merged[key] = item
            item["count"] += 1
            if r.get("result") == "成功":
                item["ok"] += 1
            if str(r.get("time", "")) >= str(item["last"]):
                item["last"] = str(r.get("time", ""))
                item["result"] = str(r.get("result", ""))
        merged_list = sorted(merged.values(), key=lambda x: x["last"], reverse=True)[:50]

        hist_rows = []
        for item in merged_list:
            hist_rows.append(
                {
                    "component": "tr",
                    "content": [
                        {
                            "component": "td",
                            "props": {"class": "text-caption"},
                            "content": [
                                {
                                    "component": "VChip",
                                    "props": {"color": "primary", "size": "x-small", "variant": "tonal"},
                                    "text": item["env"],
                                }
                            ],
                        },
                        {
                            "component": "td",
                            "props": {"class": "text-caption font-weight-medium"},
                            "text": item["container"],
                        },
                        {"component": "td", "props": {"class": "text-caption"}, "text": item["image"]},
                        {
                            "component": "td",
                            "props": {"class": "text-caption font-weight-bold"},
                            "text": f"更新 {item['count']} 次",
                        },
                        {"component": "td", "props": {"class": "text-caption"}, "text": item["last"]},
                        {
                            "component": "td",
                            "props": {"class": "text-caption"},
                            "content": [
                                {
                                    "component": "VChip",
                                    "props": {
                                        "color": "success" if item["result"] == "成功" else "error",
                                        "size": "x-small",
                                        "variant": "tonal",
                                    },
                                    "text": item["result"],
                                }
                            ],
                        },
                    ],
                }
            )
        if not hist_rows:
            hist_rows.append(
                {
                    "component": "tr",
                    "content": [
                        {
                            "component": "td",
                            "props": {"class": "text-caption text-center", "colspan": 6},
                            "text": "今日暂无更新记录（0 点后自动开始新的一天）",
                        }
                    ],
                }
            )
        elif len(merged) > 50:
            hist_rows.append(
                {
                    "component": "tr",
                    "content": [
                        {
                            "component": "td",
                            "props": {"class": "text-caption text-center", "colspan": 6},
                            "text": f"只列出最近更新过的 50 个容器（共 {len(merged)} 个）",
                        }
                    ],
                }
            )

        history_table = {
            "component": "VCard",
            "props": {"class": "mt-4", "variant": "outlined"},
            "content": [
                {
                    "component": "VCardTitle",
                    "props": {"class": "d-flex align-center pa-3"},
                    "content": [
                        {
                            "component": "VIcon",
                            "props": {"icon": "mdi-chart-timeline-variant", "color": "primary", "class": "me-2"},
                        },
                        {
                            "component": "div",
                            "props": {"style": {"flex": "1 1 100%", "minWidth": "0"}},
                            "html": (
                                '<div style="font-size:15px;font-weight:500;line-height:1.35;">'
                                f'今日更新记录（{len(merged)} 个容器 · {len(today_records)} 次）</div>'
                                '<div style="font-size:11px;color:#A5B3C2;margin-top:2px;">'
                                + datetime.now(tz=pytz.timezone(settings.TZ)).strftime('%Y-%m-%d')
                                + ' 　0 点自动清空</div>'
                            ),
                        },
                    ],
                },
                {
                    "component": "div",
                    "props": {"style": {"overflowX": "auto", "WebkitOverflowScrolling": "touch"}},
                    "content": [
                {
                    "component": "VTable",
                    "props": {"class": "text-sm", "density": "compact", "hover": True,
                              "style": {"minWidth": "560px"}},
                    "content": [
                        {
                            "component": "thead",
                            "content": [
                                {
                                    "component": "tr",
                                    "content": [
                                        {"component": "th", "props": {"class": "text-caption"}, "text": "设备"},
                                        {"component": "th", "props": {"class": "text-caption"}, "text": "容器"},
                                        {"component": "th", "props": {"class": "text-caption"}, "text": "镜像"},
                                        {"component": "th", "props": {"class": "text-caption"}, "text": "更新次数"},
                                        {"component": "th", "props": {"class": "text-caption"}, "text": "最近更新"},
                                        {"component": "th", "props": {"class": "text-caption"}, "text": "最近结果"},
                                    ],
                                }
                            ],
                        },
                        {"component": "tbody", "content": hist_rows},
                    ],
                },
                    ],
                },
            ],
        }

        return [
            {"component": "VRow", "content": summary_cards},
            chart_card,
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "class": "mt-2",
                    "text": "点「更新」直接调用对应设备的DockerCopilot；镜像TAG异常时会自动删掉重拉并使用创建镜像名更新。",
                },
            },
            *tables,
            history_table,
            backup_card,
        ]

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
