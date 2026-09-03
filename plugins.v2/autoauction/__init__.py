import json
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class AutoAuction(_PluginBase):
    plugin_name = "朱雀交易行自动上架"
    plugin_desc = "自动上架灵石或上传到交易行"
    plugin_icon = "auction.png"
    plugin_version = "1.0.1"
    plugin_author = "no_reply"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "autoauction_"
    plugin_order = 50
    auth_level = 2

    _enabled: bool = False
    _onlyonce: bool = False
    _tasks: List[Dict[str, Any]] = []
    _history: List[Dict[str, Any]] = []
    _global_cron: str = ""
    _csrf_token: str = ""
    _notify_enabled: bool = True
    _scheduler: Optional[BackgroundScheduler] = None
    _is_running: bool = False
    _running_lock: threading.Lock = threading.Lock()
    _last_run_time: float = 0
    _min_interval_seconds: int = 60

    ZHUQUE_DOMAIN = "zhuque.in"
    LIST_API = "https://zhuque.in/api/transaction/list"
    CREATE_API = "https://zhuque.in/api/transaction/create"
    CREATE_SUCCESS_CODE = "CREATE_TRANSACTION_SUCCESS"

    def init_plugin(self, config: dict = None):
        config = config or {}

        self._enabled = config.get("enabled", False)
        onlyonce = config.get("onlyonce", False)

        tasks_json = config.get("tasks_json")

        if tasks_json is None:
            self._tasks = []
        elif isinstance(tasks_json, str):
            try:
                parsed = json.loads(tasks_json) if tasks_json.strip() else []
                self._tasks = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                logger.error(f"任务配置JSON解析失败: {tasks_json}")
                self._tasks = []
        elif isinstance(tasks_json, list):
            self._tasks = tasks_json
        else:
            self._tasks = []

        self._global_cron = config.get("global_cron", "") or ""
        self._csrf_token = config.get("csrf_token", "") or ""
        self._notify_enabled = config.get("notify_enabled", True)

        self._history = self.get_data("history") or []

        if self._scheduler:
            self._scheduler.shutdown()
            self._scheduler = None

        if onlyonce and self._tasks:
            logger.info("拍卖行上架立即执行一次")
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                func=self.run_all_tasks,
                trigger='date',
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="拍卖行上架-立即执行"
            )
            self._scheduler.start()
            logger.info("调度器已启动，等待3秒后执行")

            self._onlyonce = False
            self.update_config({"onlyonce": False})
            logger.info("已重置onlyonce状态")

        self._save_config()

    def _save_config(self):
        tasks_json = json.dumps(self._tasks, ensure_ascii=False)
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify_enabled": self._notify_enabled,
            "global_cron": self._global_cron,
            "csrf_token": self._csrf_token,
            "tasks_json": tasks_json
        })
        logger.info(f"配置已保存: tasks_json={tasks_json[:100]}...")

    def get_state(self) -> bool:
        return self._enabled

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/list",
                "endpoint": self.get_listings,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取当前挂单列表",
                "description": "获取拍卖行当前挂单列表",
            },
            {
                "path": "/create",
                "endpoint": self.create_listing,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "手动上架商品",
                "description": "手动上架商品到拍卖行",
            },
            {
                "path": "/run",
                "endpoint": self.run_all_tasks,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "执行所有配置",
                "description": "执行所有上架配置",
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:

        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即执行一次",
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify_enabled",
                                            "label": "发送通知",
                                            "hide-details": True
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VCronField",
                                        "props": {
                                            "model": "global_cron",
                                            "label": "执行周期",
                                            "placeholder": "0 9 * * *"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "csrf_token",
                                            "label": "CSRF Token",
                                            "hint": "从浏览器开发者工具获取"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "props": {
                                            "class": "text-pre-wrap"
                                        },
                                        "text": "配置格式：[{\"bonus\": 146285, \"unit\": \"TiB\", \"upload\": 1, \"type\": 2}]\n\n说明：\n- bonus: 挂牌灵石数量\n- unit: 单位，可选值为 \"TiB\"、\"GiB\"\n- upload: 挂牌上传量\n- type: 1出售灵石/2出售上传"
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "tasks_json",
                                            "label": "上架配置列表 (JSON)",
                                            "rows": 8
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
            "onlyonce": False,
            "notify_enabled": True,
            "global_cron": "",
            "csrf_token": "",
            "tasks_json": "[]"
        }

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []

        services = []

        if self._global_cron and self._global_cron.strip():
            cron = self._global_cron.strip()
            if cron.count(" ") == 4:
                try:
                    services.append({
                        "id": "AutoAuction.Global",
                        "name": "拍卖行上架-全局任务",
                        "trigger": CronTrigger.from_crontab(cron),
                        "func": self.run_all_tasks,
                        "kwargs": {},
                        "misfire_grace_time": self._min_interval_seconds * 2,
                        "max_instances": 1,
                        "coalesce": True
                    })
                except Exception as e:
                    logger.error(f"全局cron配置错误: {str(e)}")

        return services

    def get_page(self) -> List[dict]:
        history_by_date = defaultdict(list)
        for record in self._history:
            date = record.get("time", "")[:10]
            history_by_date[date].append(record)

        items = []
        for date in sorted(history_by_date.keys(), reverse=True):
            records = history_by_date[date]
            if records:
                type_text = "出售上传" if records[0].get("type") == 2 else "出售灵石"
                items.append({
                    "component": "VListSubheader",
                    "props": {"class": "text-grey"},
                    "text": f"{date}  {type_text}"
                })
            for record in records:
                time_str = record.get("time", "")[11:]
                items.append({
                    "component": "VListItem",
                    "props": {
                        "title": f"上传 {record.get('upload')} {record.get('unit')} | 灵石 {record.get('bonus')} | 上架时间: {time_str}"
                    }
                })

        if not items:
            items.append({
                "component": "VListItem",
                "props": {
                    "title": "暂无上架记录",
                    "subtitle": "执行上架后将显示历史记录"
                }
            })

        return [{"component": "VList", "props": {"nav": True}, "content": items}]

    def stop_service(self):
        if self._scheduler:
            self._scheduler.shutdown()
            self._scheduler = None

    def _get_zhuque_site(self) -> Optional[Dict[str, Any]]:
        for site in SitesHelper().get_indexers():
            site_url = site.get("url", "") or ""
            if site_url and self.ZHUQUE_DOMAIN in site_url:
                return site
        return None

    def _get_zhuque_cookie(self) -> Optional[str]:
        site = self._get_zhuque_site()
        if site:
            return site.get("cookie")
        return None

    def _get_csrf_token(self) -> Optional[str]:
        if self._csrf_token:
            return self._csrf_token

        cookie = self._get_zhuque_cookie()
        if not cookie:
            return None

        try:
            req = RequestUtils(cookies=cookie, headers={"User-Agent": "Mozilla/5.0"})
            res = req.get_res(url="https://zhuque.in/bonus/transaction/upload")

            if res and res.status_code == 200:
                html = res.text
                
                patterns = [
                    r'x-csrf-token["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    r'<meta[^>]*name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)["\']',
                ]

                for pattern in patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        return match.group(1)

            return None
        except Exception as e:
            logger.error(f"获取CSRF Token异常: {str(e)}")
            return None

    def get_listings(self, page: int = 1, size: int = 20, type: int = 2) -> Dict[str, Any]:
        cookie = self._get_zhuque_cookie()

        if not cookie:
            return {"success": False, "message": "站点Cookie不存在"}

        try:
            res = RequestUtils(
                cookies=cookie,
                headers={"User-Agent": "Mozilla/5.0"}
            ).get_res(url=f"{self.LIST_API}?page={page}&size={size}&type={type}&onlyUnsold=true&onlyRelated=false")

            if res and res.status_code == 200:
                data = res.json()
                return {"success": True, "data": data}
            else:
                return {"success": False, "message": f"获取列表失败: {res.status_code if res else '无响应'}"}
        except Exception as e:
            logger.error(f"获取挂单列表失败: {str(e)}")
            return {"success": False, "message": f"获取列表异常: {str(e)}"}

    def create_listing(self, bonus: int = None, unit: str = None,
                       upload: int = None, type: int = 2) -> Dict[str, Any]:
        cookie = self._get_zhuque_cookie()
        csrf_token = self._get_csrf_token()

        if not cookie:
            logger.error("站点Cookie不存在")
            return {"success": False, "message": "站点Cookie不存在"}

        payload = {
            "type": type,
            "unit": unit or "TiB",
            "bonus": bonus or 0,
            "upload": upload or 1
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://zhuque.in",
            "Referer": "https://zhuque.in/bonus/transaction/upload",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        if csrf_token:
            headers["x-csrf-token"] = csrf_token

        try:
            req = RequestUtils(cookies=cookie, headers=headers)
            res = req.post_res(url=self.CREATE_API, json=payload)

            if not res:
                logger.error("上架请求无响应")
                return {"success": False, "message": "上架失败: 无响应"}

            if res.status_code == 200:
                result = res.json()
                logger.info(f"上架响应内容: {result}")
                if result.get("status") == 200:
                    code = result.get("data", {}).get("code")
                    if code == self.CREATE_SUCCESS_CODE:
                        transaction_id = result.get("data", {}).get("transactionId")
                        logger.info(f"上架成功: transactionId={transaction_id}")
                        return {"success": True, "data": result.get("data")}
                    else:
                        logger.error(f"上架失败: code={code}")
                        return {"success": False, "message": f"上架失败: {code}"}
                else:
                    logger.error(f"上架失败: status={result.get('status')}")
                    return {"success": False, "message": f"上架失败: status={result.get('status')}"}
            else:
                logger.error(f"上架失败: {res.status_code if res else '无响应'}")
                return {"success": False, "message": f"上架失败: {res.status_code if res else '无响应'}"}
        except Exception as e:
            logger.error(f"上架异常: {str(e)}")
            return {"success": False, "message": f"上架异常: {str(e)}"}

    def run_all_tasks(self) -> Dict[str, Any]:
        tz = pytz.timezone(settings.TZ)
        now = datetime.now(tz=tz)
        current_time = now.timestamp()

        with self._running_lock:
            if self._is_running:
                logger.warn("上架任务正在执行中，跳过本次调用")
                return {"success": False, "message": "任务正在执行中"}
            if current_time - self._last_run_time < self._min_interval_seconds:
                logger.warn(f"上架任务执行间隔太短({self._min_interval_seconds}秒)，跳过本次调用")
                return {"success": False, "message": f"执行间隔太短，请等待{self._min_interval_seconds}秒"}
            today = now.strftime('%Y-%m-%d')
            last_run_date = self.get_data("last_run_date") or ""
            if last_run_date == today:
                logger.warn(f"今日({today})已执行过上架任务，跳过本次调用")
                return {"success": False, "message": f"今日({today})已执行过上架任务"}
            self._is_running = True
            self._last_run_time = current_time

        try:
            logger.info(f"开始执行上架任务，共 {len(self._tasks)} 个配置")
            results = []
            success_records = []

            for idx, task in enumerate(self._tasks):
                result = self.create_listing(
                    bonus=task.get("bonus"),
                    unit=task.get("unit"),
                    upload=task.get("upload"),
                    type=task.get("type", 2)
                )

                if result.get("success"):
                    transaction_id = result.get("data", {}).get("transactionId")
                    record_time = now.strftime("%Y-%m-%d %H:%M:%S")
                    self._history.insert(0, {
                        "upload": task.get("upload"),
                        "bonus": task.get("bonus"),
                        "unit": task.get("unit"),
                        "type": task.get("type", 2),
                        "time": record_time,
                        "transactionId": transaction_id
                    })
                    if len(self._history) > 50:
                        self._history = self._history[:50]
                    success_records.append(f"上传 {task.get('upload')} {task.get('unit')} | 灵石 {task.get('bonus')} | 上架时间: {record_time[11:]}")
                    results.append({"index": idx + 1, "success": True})
                    logger.info(f"配置 {idx + 1} 上架成功")
                else:
                    logger.error(f"配置 {idx + 1} 上架失败: {result.get('message')}")
                    results.append({"index": idx + 1, "success": False, "error": result.get('message')})

            if self._history:
                self.save_data("history", self._history)

            self.save_data("last_run_date", today)

            if self._notify_enabled and success_records:
                try:
                    type_text = "出售上传" if self._tasks[0].get("type", 2) == 2 else "出售灵石" if self._tasks[0].get("type", 2) == 1 else ""
                    text_lines = [f"{today}  {type_text}"]
                    for record in success_records:
                        text_lines.append(record)
                    text = "\n".join(text_lines)
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="拍卖行上架",
                        text=text
                    )
                except Exception as e:
                    logger.error(f"发送通知异常: {str(e)}")

            return {"success": True, "results": results}
        finally:
            self._is_running = False
