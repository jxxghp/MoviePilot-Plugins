"""Blue Forum check-in protocol and lifecycle, shared unchanged by V2 and V3.

Copyright (c) 2026 wzxcom. Independently implemented for Blue Forum.
"""
from __future__ import annotations

import hashlib
import random
import re
import threading
from datetime import datetime, time, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


TZ = ZoneInfo("Asia/Shanghai")
API_ROOT = "https://hdblue.cc/api/integrations/moviepilot/v1"
DEFAULTS = {
    "enabled": False,
    "api_key": "",
    "cron": "30 8 * * *",
    "jitter_minutes": 30,
    "catch_up": True,
    "notification": "failure",
    "use_proxy": False,
    "proxy_url": "",
    "run_once": False,
    "test_connection": False,
}


class CheckinError(Exception):
    """Only trusted, locally defined text can reach logs or notifications."""

    def __init__(self, message: str, *, retryable: bool = False,
                 retry_after: int = 0, uncertain: bool = False, auth: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.uncertain = uncertain
        self.auth = auth


def now_beijing() -> datetime:
    return datetime.now(TZ)


def retry_after_seconds(value: str, now: datetime) -> int:
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            return max(0, int((parsedate_to_datetime(value) - now).total_seconds()) + 1)
        except (ValueError, TypeError, OverflowError):
            return 0


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 10 ** 18


def validate_payload(payload: Any) -> dict:
    """Whitelist server fields before persisting or displaying them."""
    if not isinstance(payload, dict) or payload.get("protocolVersion") != 1:
        raise CheckinError("论坛接口版本不兼容，请更新插件")
    account = payload.get("account")
    date = payload.get("date")
    if not isinstance(account, dict) or not account.get("id") or not isinstance(date, str):
        raise CheckinError("论坛返回的数据不完整")
    try:
        if datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") != date:
            raise ValueError()
    except ValueError:
        raise CheckinError("论坛返回的签到日期无效") from None
    if payload.get("timezone") != "Asia/Shanghai" or not isinstance(payload.get("alreadyCheckedIn"), bool):
        raise CheckinError("论坛返回的签到状态无效")
    for key in ("points", "reward", "currentStreak", "maxStreak"):
        if not _number(payload.get(key)):
            raise CheckinError("论坛返回的签到数值无效")
    raw_history = payload.get("history", [])
    if not isinstance(raw_history, list):
        raise CheckinError("论坛返回的签到记录无效")
    history = []
    for item in raw_history[:30]:
        if isinstance(item, dict) and isinstance(item.get("date"), str) and _number(item.get("reward")):
            history.append({"date": item["date"][:10], "reward": item["reward"],
                            "createdAt": str(item.get("createdAt") or "")[:40]})
    return {
        "protocolVersion": 1, "timezone": "Asia/Shanghai", "date": date,
        "account": {key: str(account.get(key) or "")[:200]
                    for key in ("id", "username", "nickname", "avatarUrl")},
        "pointName": str(payload.get("pointName") or "积分")[:30],
        "points": payload["points"], "reward": payload["reward"],
        "alreadyCheckedIn": payload["alreadyCheckedIn"],
        "performedCheckIn": payload.get("performedCheckIn") is True,
        "currentStreak": payload["currentStreak"], "maxStreak": payload["maxStreak"],
        "history": history,
    }


class ForumClient:
    """Fixed HTTPS origin, no redirects, no ambient proxy or credential logging."""

    def __init__(self, key: str, proxy: str = "", session_factory=requests.Session):
        self.key = key
        self.proxy = proxy
        self.session_factory = session_factory

    def request(self, method: str, endpoint: str) -> dict:
        if method not in ("GET", "POST") or endpoint not in ("/me", "/check-in"):
            raise CheckinError("不支持的论坛请求")
        try:
            with self.session_factory() as session:
                session.trust_env = False
                if self.proxy:
                    session.proxies = {"http": self.proxy, "https": self.proxy}
                response = session.request(
                    method, API_ROOT + endpoint,
                    headers={"Authorization": "Bearer " + self.key,
                             "Accept": "application/json",
                             "User-Agent": "MoviePilot-HDBlueSignin/1"},
                    json={} if method == "POST" else None,
                    timeout=(5, 15), allow_redirects=False, verify=True,
                )
                status = response.status_code
                if not 200 <= status < 300:
                    if status == 401:
                        raise CheckinError("签到密钥已失效，请检查论坛设置", auth=True)
                    if status == 403:
                        raise CheckinError("论坛当前不允许签到，请检查签到开放状态或账号权限")
                    if status == 429:
                        raise CheckinError("论坛请求过于频繁，稍后自动重试", retryable=True,
                                           retry_after=retry_after_seconds(response.headers.get("Retry-After"), now_beijing()))
                    if status >= 500:
                        raise CheckinError("论坛服务暂时不可用", retryable=True, uncertain=method == "POST")
                    if 300 <= status < 400:
                        raise CheckinError("论坛地址发生跳转，已停止请求，请更新插件")
                    raise CheckinError("论坛拒绝请求，请检查账号状态或更新插件")
                try:
                    if len(response.content) > 262144:
                        raise CheckinError("论坛响应超出大小限制")
                    try:
                        envelope = response.json()
                    except (ValueError, TypeError):
                        raise CheckinError("论坛未返回有效的 JSON 数据") from None
                    if not isinstance(envelope, dict) or type(envelope.get("code")) is not int or envelope["code"] != 0:
                        raise CheckinError("论坛接口返回异常结果，请在网页确认签到状态")
                    return validate_payload(envelope.get("data"))
                except CheckinError as error:
                    # A 2xx POST may have committed even when its body is invalid.
                    error.uncertain = method == "POST"
                    raise
        except requests.RequestException:
            raise CheckinError("连接论坛超时或网络暂时不可用", retryable=True, uncertain=method == "POST") from None


class HDBluePlugin:
    """Host-neutral implementation; the entry point supplies the host logger."""

    def _log(self, text: str) -> None:
        self.host_logger.info("[蓝影论坛签到] " + text)

    def init_plugin(self, config: dict = None):
        if not hasattr(self, "_run_lock"):
            self._run_lock = threading.Lock()
            self._generation = 0
            self._scheduler = None
        self.stop_service()
        with self._run_lock:
            self._config = dict(DEFAULTS, **(config or {}))
            self._enabled = bool(self._config["enabled"])
            self._stopped = False
            self._test_pending = False
            self._deferred_cron = None
            self._config_error = ""
            self._trigger = None
            self._key = str(self._config["api_key"] or "").strip()
            self._fingerprint = hashlib.sha256(self._key.encode()).hexdigest() if self._key else ""
            previous = self.get_data("state") or {}
            self._state = previous if previous.get("fingerprint") == self._fingerprint else {}
            self._state["fingerprint"] = self._fingerprint
            if not self._cooldown_until(now_beijing()):
                self._state.pop("notBefore", None)
            self.save_data("state", self._state)
            self._auth_blocked = bool(self._state.get("authBlocked"))
            try:
                self._jitter = max(0, min(30, int(self._config["jitter_minutes"])))
                self._trigger = CronTrigger.from_crontab(str(self._config["cron"]), timezone=TZ)
                if self._key and not re.fullmatch(r"hdbmp_[A-Za-z0-9_-]{20,200}", self._key):
                    raise ValueError("签到密钥格式错误")
                self._proxy = ""
                if self._config["use_proxy"]:
                    self._proxy = str(self._config["proxy_url"] or "").strip()
                    parsed = urlsplit(self._proxy)
                    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.fragment or parsed.query:
                        raise ValueError("请输入有效的 HTTP/HTTPS 代理地址")
            except (ValueError, TypeError):
                self._config_error = "配置无效：请检查签到密钥、五段 Cron 和代理地址"
            run_once = bool(self._config.get("run_once"))
            test_connection = bool(self._config.get("test_connection"))
            self._config.update(run_once=False, test_connection=False)
            if run_once or test_connection:
                self.update_config(self._config)
            if not self._key or self._config_error or not (self._enabled or run_once or test_connection):
                return
            self._scheduler = BackgroundScheduler(timezone=TZ, executors={
                "default": {"type": "threadpool", "max_workers": 1}})
            self._scheduler.start()
            if test_connection:
                self._test_pending = True
                if not self._queue("test", now_beijing() + timedelta(seconds=2)):
                    self._test_pending = False
            elif run_once:
                self._queue("manual", now_beijing() + timedelta(seconds=2))
            elif self._enabled and not self._auth_blocked:
                now = now_beijing()
                if (not self._restore_retry(self._generation)
                        and not self._cooldown_until(now)
                        and self._config["catch_up"] and self._due_today(now) and not self._done_today(now)):
                    self._queue("auto", self._initial_due(now, startup=True))
            if not self._enabled and self._scheduler and not self._scheduler.get_jobs():
                self.stop_service()

    def _cooldown_until(self, now: datetime) -> datetime | None:
        """Keep server Retry-After independent of a retry's local calendar day."""
        try:
            due = datetime.fromisoformat(self._state.get("notBefore", ""))
            if due.tzinfo is not None and due > now:
                return due.astimezone(TZ)
        except (ValueError, TypeError):
            pass
        return None

    def _restore_retry(self, generation: int) -> bool:
        """Restore only an existing same-day retry, without spending an attempt."""
        if not self._active(generation) or not self._enabled or self._auth_blocked:
            return False
        pending = self._state.get("retry") or {}
        if not pending:
            return False
        now = now_beijing()
        today = now.date().isoformat()
        attempts = self._state.get("attempts") or {}
        exhausted = attempts.get("date") == today and attempts.get("count", 0) >= 3
        if pending.get("date") == today and not self._done_today(now) and not exhausted:
            try:
                due = datetime.fromisoformat(pending["dueAt"])
                if due.tzinfo is None:
                    raise ValueError()
                due = max(due.astimezone(TZ), now + timedelta(seconds=15), self._cooldown_until(now) or now)
                if due.date().isoformat() == today:
                    self._state["retry"] = {"date": today, "dueAt": due.isoformat()}
                    self.save_data("state", self._state)
                    if self._active(generation):
                        return self._queue("auto", due, today)
                    return False
            except (ValueError, TypeError, KeyError):
                pass
        self._state.pop("retry", None)
        self.save_data("state", self._state)
        return False

    def _initial_due(self, now: datetime, *, startup: bool = False) -> datetime:
        midnight = datetime.combine(now.date() + timedelta(days=1), time.min, TZ)
        # Leave a short HTTP window; late schedules must not silently disappear.
        remaining = max(0, int((midnight - now).total_seconds()) - 30)
        initial = min(15 if startup else 0, remaining)
        jitter = random.randint(0, min(self._jitter * 60, max(0, remaining - initial)))
        return now + timedelta(seconds=initial + jitter)

    def _due_today(self, now: datetime) -> bool:
        midnight = datetime.combine(now.date(), time.min, TZ)
        due = self._trigger.get_next_fire_time(None, midnight) if self._trigger else None
        return bool(due and due.date() == now.date() and due <= now)

    def _done_today(self, now: datetime) -> bool:
        payload = self._state.get("snapshot") or {}
        return payload.get("date") == now.date().isoformat() and payload.get("alreadyCheckedIn") is True

    def get_state(self) -> bool:
        return bool(getattr(self, "_enabled", False) and not getattr(self, "_config_error", ""))

    @staticmethod
    def get_command() -> list:
        return []

    def get_api(self) -> list:
        return []

    def get_service(self) -> list:
        if not self.get_state() or not self._key or not self._trigger:
            return []
        return [{"id": self.__class__.__name__ + "DailyCheckin", "name": "蓝影论坛签到（北京时间）",
                 "trigger": self._trigger, "func": self.scheduled_checkin,
                 "kwargs": {"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}}]

    def scheduled_checkin(self):
        generation = self._generation
        target_date = now_beijing().date().isoformat()
        with self._run_lock:
            now = now_beijing()
            if (not self._active(generation) or target_date != now.date().isoformat()
                    or not self._enabled or self._auth_blocked or self._done_today(now)
                    or self._cooldown_until(now)):
                return
            if self._test_pending:
                self._deferred_cron = (generation, target_date)
                return
            pending = self._state.get("retry") or {}
            if pending.get("date") == target_date:
                return
            if self._scheduler and any(job.id in ("test", "checkin") for job in self._scheduler.get_jobs()):
                # Frequent Cron ticks must not keep postponing a jittered run.
                return
            self._queue("auto", self._initial_due(now), target_date)

    def _finish_connection_test(self, generation: int, target_date: str):
        """Resume existing work, but never turn an isolated connection test into a sign-in."""
        self._test_pending = False
        deferred_cron = self._deferred_cron
        self._deferred_cron = None
        restored = self._restore_retry(generation)
        now = now_beijing()
        if (not restored and self._active(generation) and self._enabled and not self._auth_blocked
                and deferred_cron == (generation, target_date) and target_date == now.date().isoformat()
                and not self._done_today(now) and not self._cooldown_until(now)):
            self._queue("auto", self._initial_due(now), target_date)

    def _queue(self, mode: str, due: datetime, target_date: str = "") -> bool:
        if self._stopped or not self._scheduler:
            return False
        target_date = target_date or now_beijing().date().isoformat()
        if due.date().isoformat() != target_date:
            return False
        job_id = "test" if mode == "test" else "checkin"
        self._scheduler.add_job(self._run_scheduled, "date", run_date=due, id=job_id,
                                kwargs={"mode": mode, "target_date": target_date, "generation": self._generation},
                                replace_existing=True, misfire_grace_time=300, max_instances=1)
        return True

    def _active(self, generation: int) -> bool:
        return not self._stopped and generation == self._generation

    def _client(self):
        return ForumClient(self._key, self._proxy)

    def _run(self, mode: str, target_date: str, generation: int):
        """Allow a direct callback to skip when another execution owns the lock."""
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            self._execute_run(mode, target_date, generation)
        finally:
            self._run_lock.release()

    def _run_scheduled(self, mode: str, target_date: str, generation: int):
        """A dequeued date job must wait, not disappear during lock contention."""
        with self._run_lock:
            self._execute_run(mode, target_date, generation)

    def _execute_run(self, mode: str, target_date: str, generation: int):
        """Execute with the instance lock held; validate generation after waiting."""
        try:
            if not self._active(generation) or target_date != now_beijing().date().isoformat():
                return
            cooldown = self._cooldown_until(now_beijing())
            if cooldown:
                if mode == "auto":
                    self._restore_retry(generation)
                else:
                    self._record(None, "等待冷却", "论坛要求在 " + cooldown.strftime("%m-%d %H:%M:%S")
                                 + " 北京时间后再试", generation=generation, notify=False)
                return
            if mode == "auto" and (not self._enabled or self._auth_blocked or self._done_today(now_beijing())):
                return
            attempts = self._state.get("attempts") or {}
            count = attempts.get("count", 0) if attempts.get("date") == target_date else 0
            if mode == "auto" and count >= 3:
                return
            if mode != "test":
                self._state.pop("retry", None)
                if mode == "auto":
                    count += 1
                    self._state["attempts"] = {"date": target_date, "count": count}
                self.save_data("state", self._state)
            client = self._client()
            try:
                payload = client.request("GET", "/me" if mode == "test" else "/check-in")
                if not self._active(generation):
                    return
                if mode == "test":
                    self._auth_blocked = False
                    self._state["authBlocked"] = False
                    if payload["date"] == target_date and payload["alreadyCheckedIn"]:
                        self._state.pop("retry", None)
                    self._record(payload, "连接成功", "密钥有效，已更新账号与签到状态", generation=generation, notify=False)
                    return
                if payload["date"] != target_date or target_date != now_beijing().date().isoformat():
                    raise CheckinError("签到日期已变化，本次任务已结束；不会补签往日")
                was_checked = payload["alreadyCheckedIn"]
                recovered = False
                if not was_checked:
                    try:
                        payload = client.request("POST", "/check-in")
                    except CheckinError as error:
                        if not error.uncertain or not self._active(generation):
                            raise
                        try:
                            verified = client.request("GET", "/check-in")
                        except CheckinError as verification_error:
                            if verification_error.auth:
                                raise verification_error from None
                            raise error from None
                        if verified["date"] != target_date or not verified["alreadyCheckedIn"]:
                            raise error
                        payload = verified
                        recovered = True
                if not self._active(generation):
                    return
                if payload["date"] != target_date or not payload["alreadyCheckedIn"]:
                    raise CheckinError("签到结果待确认，请在论坛网页检查", uncertain=True)
                self._auth_blocked = False
                self._state["authBlocked"] = False
                result = "今日已签到" if was_checked else ("已确认签到成功" if recovered else
                         "签到成功" if payload["performedCheckIn"] else "今日已签到")
                self._record(payload, result,
                             f"今日奖励 {payload['reward']} {payload['pointName']}，余额 {payload['points']}，连续 {payload['currentStreak']} 天",
                             generation=generation)
            except CheckinError as error:
                if not self._active(generation):
                    return
                if error.auth:
                    self._auth_blocked = True
                    self._state["authBlocked"] = True
                    self._state.pop("retry", None)
                if error.retry_after:
                    now = now_beijing()
                    not_before = max(now + timedelta(seconds=error.retry_after), self._cooldown_until(now) or now)
                    self._state["notBefore"] = not_before.isoformat()
                retry = None
                if mode != "test" and self._enabled and error.retryable and count < 3 and not self._auth_blocked:
                    # Manual attempts share the day's automatic retry budget.
                    if mode == "manual":
                        count = max(1, count)
                        self._state["attempts"] = {"date": target_date, "count": count}
                    seconds = max(error.retry_after, 600 if count <= 1 else 1800)
                    due = now_beijing() + timedelta(seconds=seconds)
                    if due.date().isoformat() == target_date:
                        retry = {"date": target_date, "dueAt": due.isoformat()}
                        self._state["retry"] = retry
                        self._queue("auto", due, target_date)
                message = str(error)
                if retry:
                    message += "；计划 " + datetime.fromisoformat(retry["dueAt"]).strftime("%H:%M") + " 重试"
                self._record(None, "结果待确认" if error.uncertain else "失败", message,
                             generation=generation, notify=mode != "test", failed=True)
        finally:
            if self._active(generation):
                if mode == "test":
                    self._finish_connection_test(generation, target_date)
                if not self._enabled:
                    self.stop_service()

    def _record(self, payload: dict | None, result: str, message: str,
                *, generation: int, notify: bool = True, failed: bool = False):
        if not self._active(generation):
            return
        now = now_beijing()
        if payload:
            previous = self._state.get("snapshot") or {}
            if previous.get("account", {}).get("id") not in (None, payload["account"]["id"]):
                self._state = {"fingerprint": self._fingerprint}
            self._state["snapshot"] = payload
        cutoff = (now - timedelta(days=30)).isoformat()
        events = [event for event in self._state.get("events", []) if str(event.get("at", "")) >= cutoff]
        event = {"at": now.isoformat(), "result": result, "message": message, "failed": failed}
        self._state.update(events=([event] + events)[:120], lastResult=event, updatedAt=now.isoformat())
        self.save_data("state", self._state)
        if not self._active(generation):
            return
        self._log(result + "：" + message)
        notify_mode = self._config.get("notification")
        if self._active(generation) and notify and (notify_mode == "all" or (notify_mode == "failure" and failed)):
            try:
                self.post_message(mtype=self.notification_type, title="蓝影论坛签到 · " + result, text=message)
            except Exception:
                self._log("签到结果已保存，但 MoviePilot 通知发送失败")

    def stop_service(self):
        self._stopped = True
        self._enabled = False
        self._test_pending = False
        self._deferred_cron = None
        self._generation = getattr(self, "_generation", 0) + 1
        scheduler = getattr(self, "_scheduler", None)
        self._scheduler = None
        if scheduler:
            scheduler.remove_all_jobs()
            if scheduler.running:
                scheduler.shutdown(wait=False)

    def get_form(self):
        """Keep floating labels and hints inside spaced, responsive grid cells."""
        def cell(content, *, md=12):
            return {"component": "VCol", "props": {"cols": 12, "md": md, "class": "pa-2"},
                    "content": [content]}

        def control(component, model, label, *, md=12, **props):
            # Reserve the input details area even when it has no current hint.
            return cell({"component": component, "props": {
                "model": model, "label": label, "hide-details": component == "VSwitch", **props}}, md=md)

        def section(title):
            return cell({"component": "div", "props": {"class": "pt-2"}, "content": [
                {"component": "VDivider", "props": {"class": "mb-3"}},
                {"component": "h3", "props": {"class": "text-subtitle-1"}, "text": title},
            ]})

        return [{"component": "VForm", "content": [{"component": "VRow", "props": {"class": "ma-0"}, "content": [
            cell({"component": "VAlert", "props": {"type": "info", "variant": "tonal",
                "text": "在蓝影论坛个人设置 → MoviePilot 签到中生成专用密钥。签到以北京时间为准，奖励由论坛决定。"}}),
            control("VSwitch", "enabled", "启用自动签到"),
            control("VTextField", "api_key", "蓝影论坛签到密钥", type="password", autocomplete="off", placeholder="hdbmp_…"),
            control("VTextField", "cron", "执行周期（北京时间）", md=6, placeholder="30 8 * * *", hint="五段 Cron，默认每天 08:30", **{"persistent-hint": True}),
            control("VTextField", "jitter_minutes", "随机延迟上限（分钟）", md=6, type="number", min=0, max=30),
            control("VSwitch", "catch_up", "启动时执行当天已错过的签到"),
            control("VSelect", "notification", "结果通知", items=[{"title": "仅失败", "value": "failure"},
                {"title": "全部结果", "value": "all"}, {"title": "关闭", "value": "off"}]),
            section("代理设置"),
            control("VSwitch", "use_proxy", "使用指定代理"),
            control("VTextField", "proxy_url", "HTTP/HTTPS 代理地址", type="password", autocomplete="off",
                    hint="仅开启代理后使用，不读取系统环境代理", **{"persistent-hint": True}),
            section("手动操作"),
            control("VSwitch", "test_connection", "保存后测试连接（只查询，不签到）"),
            control("VSwitch", "run_once", "保存后立即签到（执行后自动关闭）"),
            cell({"component": "VAlert", "props": {"type": "info", "variant": "tonal",
                "text": "测试连接与立即签到同时开启时，只执行连接测试。停用插件会清理待执行任务；不会自动补签往日或消费补签卡。"}}),
        ]}]}], dict(DEFAULTS)

    def get_page(self):
        state = getattr(self, "_state", {})
        data = state.get("snapshot") or {}
        account = data.get("account") or {}
        last = state.get("lastResult") or {}
        today = now_beijing().date().isoformat()
        checked = data.get("date") == today and data.get("alreadyCheckedIn")
        error = getattr(self, "_config_error", "")
        next_run = None
        scheduler = getattr(self, "_scheduler", None)
        if scheduler:
            jobs = scheduler.get_jobs()
            next_run = min((job.next_run_time for job in jobs if job.next_run_time), default=None)
        if next_run is None and self.get_state() and getattr(self, "_trigger", None):
            next_run = self._trigger.get_next_fire_time(None, now_beijing())
        status = error or ("请先配置论坛签到密钥" if not getattr(self, "_key", "") else
                           "密钥已失效，请重新生成" if getattr(self, "_auth_blocked", False) else
                           "今日已签到" if checked else "今日尚未确认签到")
        rows = [("账号", account.get("nickname") or account.get("username") or "等待连接"),
                ("积分余额", f"{data.get('points', '—')} {data.get('pointName', '积分')}"),
                ("今日奖励", str(data.get("reward", "—")) if data.get("date") == today else "—"),
                ("连续签到", f"{data.get('currentStreak', '—')} 天 / 最长 {data.get('maxStreak', '—')} 天"),
                ("下次执行", next_run.astimezone(TZ).strftime("%m-%d %H:%M:%S") + " 北京时间（定时任务另加随机延迟）" if next_run else "未安排"),
                ("最近结果", last.get("result", "尚无记录") + " · " + last.get("message", "")),
                ("更新时间", str(state.get("updatedAt") or "尚未更新"))]
        def table(headers, items):
            return {"component": "VTable", "props": {"density": "compact"}, "content": [
                {"component": "thead", "content": [{"component": "tr", "content": [
                    {"component": "th", "text": header} for header in headers]}]},
                {"component": "tbody", "content": [{"component": "tr", "content": [
                    {"component": "td", "text": str(value)} for value in row]} for row in items]},
            ]}
        return [
            {"component": "VAlert", "props": {"type": "success" if checked else "info", "variant": "tonal", "text": status}},
            table(["项目", "状态"], rows),
            {"component": "h3", "text": "近期论坛签到"},
            table(["日期", "实际奖励"], [(item["date"], item["reward"]) for item in data.get("history", [])]),
            {"component": "h3", "text": "最近执行记录"},
            table(["北京时间", "结果", "说明"], [(item["at"][:19].replace("T", " "), item["result"], item["message"])
                  for item in state.get("events", [])[:30]]),
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal",
                "text": "本页显示缓存，不会因打开页面发起签到。可在设置中执行连接测试刷新数据，或立即签到。"}},
        ]
