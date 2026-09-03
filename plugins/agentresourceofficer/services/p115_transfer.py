import importlib
import re
import sys
from base64 import b64encode
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

try:
    from app.core.config import settings
except Exception:
    settings = None
try:
    from app.core.plugin import PluginManager
except Exception:
    PluginManager = None


class P115TransferService:
    """Reusable 115 share transfer execution layer for Agent影视助手."""

    CLIENT_COOKIE_REQUIRED_KEYS = {"UID", "CID", "SEID"}
    QR_CLIENT_TYPES = {
        "web",
        "android",
        "115android",
        "ios",
        "115ios",
        "alipaymini",
        "wechatmini",
        "115ipad",
        "tv",
        "qandroid",
    }

    def __init__(
        self,
        *,
        default_target_path: str = "/待整理",
        cookie: str = "",
        prefer_direct: bool = True,
    ) -> None:
        self.default_target_path = self.normalize_pan_path(default_target_path) or "/待整理"
        self.cookie = self.normalize_text(cookie)
        self.prefer_direct = bool(prefer_direct)

    def set_cookie(self, cookie: str = "") -> None:
        self.cookie = self.normalize_text(cookie)

    @staticmethod
    def normalize_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def normalize_pan_path(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if not text.startswith("/"):
            text = f"/{text}"
        return text.rstrip("/") or "/"

    @staticmethod
    def _ensure_helper_import_paths() -> None:
        candidate_dirs = [
            "/app/app/plugins",
            "/config/plugins",
        ]
        for base in candidate_dirs:
            path = Path(base)
            if path.exists():
                text = str(path)
                if text not in sys.path:
                    sys.path.append(text)

    @staticmethod
    def is_115_share_url(url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host == "115.com" or host.endswith(".115.com") or "115cdn.com" in host

    def ensure_115_share_url(self, url: str, access_code: str = "") -> str:
        clean_url = self.normalize_text(url)
        if not clean_url:
            return ""
        access_code = self.normalize_text(access_code)
        parsed = urlparse(clean_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if access_code and "password" not in query:
            query["password"] = access_code
            clean_url = urlunparse(parsed._replace(query=urlencode(query)))
        return clean_url

    @staticmethod
    def _extract_115_payload(url: str) -> Tuple[str, str]:
        clean_url = str(url or "").strip()
        if not clean_url:
            return "", ""
        try:
            from p115client.util import share_extract_payload

            payload = share_extract_payload(clean_url) or {}
            return str(payload.get("share_code") or "").strip(), str(payload.get("receive_code") or "").strip()
        except Exception:
            parsed = urlparse(clean_url)
            share_code = ""
            match = re.search(r"/s/([^/?#]+)", parsed.path or "")
            if match:
                share_code = match.group(1).strip()
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            receive_code = str(query.get("password") or query.get("receive_code") or query.get("pwd") or "").strip()
            return share_code, receive_code

    @classmethod
    def parse_cookie_pairs(cls, cookie: str) -> Dict[str, str]:
        pairs: Dict[str, str] = {}
        for part in cls.normalize_text(cookie).strip(";").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                pairs[key] = value
        return pairs

    @classmethod
    def validate_client_cookie(cls, cookie: str) -> Tuple[bool, str]:
        if not cls.normalize_text(cookie):
            return False, "未配置独立 115 Cookie"
        pairs = cls.parse_cookie_pairs(cookie)
        missing = sorted(cls.CLIENT_COOKIE_REQUIRED_KEYS - set(pairs))
        if missing:
            return False, f"当前 115 Cookie 缺少 {'/'.join(missing)}，看起来不是扫码客户端 Cookie；不建议使用网页版 Cookie"
        return True, ""

    def cookie_state(self) -> Dict[str, Any]:
        configured = bool(self.normalize_text(self.cookie))
        pairs = self.parse_cookie_pairs(self.cookie)
        cookie_keys = sorted(pairs.keys())
        if not configured:
            return {
                "configured": False,
                "valid": False,
                "mode": "none",
                "cookie_keys": [],
                "message": "未配置独立 115 会话。新环境请先发“115登录”扫码；P115StrmHelper 仅作为旧环境兼容 fallback。",
            }
        cookie_ok, cookie_message = self.validate_client_cookie(self.cookie)
        return {
            "configured": True,
            "valid": cookie_ok,
            "mode": "client_cookie" if cookie_ok else "invalid_cookie",
            "cookie_keys": cookie_keys,
            "message": "" if cookie_ok else cookie_message,
        }

    @classmethod
    def normalize_qrcode_client_type(cls, client_type: Any) -> str:
        text = cls.normalize_text(client_type).lower()
        return text if text in cls.QR_CLIENT_TYPES else "alipaymini"

    @staticmethod
    def jsonable(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool, list, dict)):
            return value
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump()
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            return {k: v for k, v in vars(value).items() if not k.startswith("_")}
        return str(value)

    def tz_now(self) -> datetime:
        if settings is not None:
            try:
                return datetime.now(ZoneInfo(getattr(settings, "TZ", "Asia/Shanghai")))
            except Exception:
                pass
        return datetime.now()

    @staticmethod
    def _safe_int(value: Any, default: int = -1) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _response_error(resp: Any) -> str:
        if not isinstance(resp, dict):
            return str(resp or "")
        for key in ("error", "message", "msg", "errno"):
            value = resp.get(key)
            if value not in (None, ""):
                return str(value)
        return str(resp)

    @classmethod
    def _is_already_saved_message(cls, value: Any) -> bool:
        text = cls.normalize_text(value)
        return any(
            marker in text
            for marker in (
                "已经转存",
                "已转存",
                "已经保存",
                "已保存",
                "already",
                "exist",
            )
        )

    @staticmethod
    def _response_ok(resp: Any) -> bool:
        if not isinstance(resp, dict):
            return False
        if resp.get("state") is True:
            return True
        if resp.get("code") in (0, "0") and resp.get("state") not in (False, 0):
            return True
        if resp.get("errno") in (0, "0") and resp.get("state") not in (False, 0):
            return True
        return False

    @staticmethod
    def _p115_request_kwargs(*, app: bool = False) -> Dict[str, Any]:
        try:
            P115TransferService._ensure_helper_import_paths()
            from app.plugins.p115strmhelper.core.config import configer

            return configer.get_ios_ua_app(app=app) or {}
        except Exception:
            try:
                P115TransferService._ensure_helper_import_paths()
                from p115strmhelper.core.config import configer

                return configer.get_ios_ua_app(app=app) or {}
            except Exception:
                pass
            return {}

    @staticmethod
    def _resolve_servicer_from_loaded_plugin() -> Tuple[Optional[Any], Optional[str]]:
        if PluginManager is None:
            return None, "PluginManager 不可用"
        try:
            plugin = PluginManager().running_plugins.get("P115StrmHelper")
        except Exception as exc:
            return None, f"读取 P115StrmHelper 运行态失败: {exc}"
        if not plugin:
            return None, "P115StrmHelper 未加载"

        module_names = []
        plugin_module = getattr(plugin.__class__, "__module__", "") or ""
        if plugin_module:
            module_names.append(f"{plugin_module}.service")
        module_names.extend(
            [
                "app.plugins.p115strmhelper.service",
                "p115strmhelper.service",
            ]
        )

        for module_name in module_names:
            try:
                self._ensure_helper_import_paths()
                module = sys.modules.get(module_name) or importlib.import_module(module_name)
                servicer = getattr(module, "servicer", None)
                if servicer is not None:
                    return servicer, None
            except Exception:
                continue
        return None, "P115StrmHelper 运行态已加载，但未找到 service.servicer"

    def _get_loaded_p115_client(self) -> Tuple[Optional[Any], str]:
        servicer, helper_error = self._resolve_servicer_from_loaded_plugin()
        if not servicer:
            return None, helper_error or "P115StrmHelper 未加载"
        client = getattr(servicer, "client", None)
        if not client:
            return None, "P115StrmHelper 未登录 115 或客户端不可用"
        return client, "p115strmhelper_client"

    def _get_cookie_p115_client(self) -> Tuple[Optional[Any], str]:
        if not self.cookie:
            return None, "未配置独立 115 Cookie"
        cookie_ok, cookie_message = self.validate_client_cookie(self.cookie)
        if not cookie_ok:
            return None, cookie_message
        try:
            from p115client import P115Client

            return P115Client(
                self.cookie,
                check_for_relogin=False,
                ensure_cookies=False,
                console_qrcode=False,
            ), "direct_cookie"
        except Exception as exc:
            return None, f"独立 115 Cookie 初始化失败: {exc}"

    @classmethod
    def create_qrcode_login(cls, client_type: str = "alipaymini") -> Tuple[bool, Dict[str, Any], str]:
        final_client_type = cls.normalize_qrcode_client_type(client_type)
        try:
            from p115client import P115Client, check_response

            resp = P115Client.login_qrcode_token()
            check_response(resp)
            resp_info = resp.get("data", {}) if isinstance(resp, dict) else {}
            uid = str(resp_info.get("uid") or "")
            qrcode_time = str(resp_info.get("time") or "")
            sign = str(resp_info.get("sign") or "")
            qrcode = P115Client.login_qrcode(uid)
            if not isinstance(qrcode, (bytes, bytearray)):
                return False, {}, "获取二维码失败：返回内容类型异常"
            return True, {
                "uid": uid,
                "time": qrcode_time,
                "sign": sign,
                "client_type": final_client_type,
                "tips": "请使用 115 App 扫码登录",
                "qrcode": f"data:image/png;base64,{b64encode(qrcode).decode('utf-8')}",
            }, "success"
        except Exception as exc:
            return False, {}, f"获取 115 登录二维码失败: {exc}"

    @classmethod
    def check_qrcode_login(
        cls,
        *,
        uid: str,
        time_value: str,
        sign: str,
        client_type: str = "alipaymini",
    ) -> Tuple[bool, Dict[str, Any], str]:
        final_client_type = cls.normalize_qrcode_client_type(client_type)
        try:
            from p115client import P115Client, check_response

            payload = {"uid": uid, "time": time_value, "sign": sign}
            resp = P115Client.login_qrcode_scan_status(payload)
            if not isinstance(resp, dict):
                return False, {}, "检查二维码状态失败：返回内容类型异常"
            check_response(resp)
            status_code = (resp.get("data") or {}).get("status")
        except Exception as exc:
            return False, {}, f"检查二维码状态失败: {exc}"

        if status_code == 0:
            return True, {"status": "waiting", "client_type": final_client_type}, "等待扫码"
        if status_code == 1:
            return True, {"status": "scanned", "client_type": final_client_type}, "已扫码，等待确认"
        if status_code == -1 or status_code is None:
            return False, {"status": "expired", "client_type": final_client_type}, "二维码已过期"
        if status_code == -2:
            return False, {"status": "cancelled", "client_type": final_client_type}, "用户取消登录"
        if status_code != 2:
            return False, {"status": "unknown", "client_type": final_client_type}, f"未知二维码状态: {status_code}"

        try:
            from p115client import P115Client, check_response

            resp = P115Client.login_qrcode_scan_result(uid, app=final_client_type)
            if not isinstance(resp, dict):
                return False, {}, "获取登录结果失败：返回内容类型异常"
            check_response(resp)
        except Exception as exc:
            return False, {}, f"获取登录结果失败: {exc}"

        cookie_data = (resp.get("data") or {}).get("cookie") if isinstance(resp, dict) else None
        if not isinstance(cookie_data, dict):
            return False, {}, "登录成功但未返回 Cookie"
        cookie = "; ".join(f"{name}={value}" for name, value in cookie_data.items() if name and value).strip()
        cookie_ok, cookie_message = cls.validate_client_cookie(cookie)
        if not cookie_ok:
            return False, {}, cookie_message
        return True, {
            "status": "success",
            "client_type": final_client_type,
            "cookie": cookie,
            "cookie_keys": sorted(cls.parse_cookie_pairs(cookie).keys()),
        }, "登录成功"

    def get_direct_client(self) -> Tuple[Optional[Any], str, str]:
        client, source = self._get_cookie_p115_client()
        if client:
            return client, source, ""
        cookie_error = source
        client, source = self._get_loaded_p115_client()
        if client:
            return client, source, ""
        return None, "none", source or cookie_error

    @classmethod
    def _import_servicer_fallback(cls) -> Tuple[Optional[Any], Optional[str]]:
        last_error = ""
        for module_name in [
            "app.plugins.p115strmhelper.service",
            "p115strmhelper.service",
        ]:
            try:
                cls._ensure_helper_import_paths()
                service_module = importlib.import_module(module_name)
                servicer = getattr(service_module, "servicer", None)
                if servicer is not None:
                    return servicer, None
                last_error = f"{module_name} 未暴露 servicer"
            except Exception as exc:
                last_error = f"{module_name} 导入失败: {exc}"
        return None, last_error or "P115StrmHelper 未安装或无法导入"

    def get_share_helper(self) -> Tuple[Optional[Any], Optional[str]]:
        servicer, helper_error = self._resolve_servicer_from_loaded_plugin()
        if not servicer:
            servicer, helper_error = self._import_servicer_fallback()
        if not servicer:
            return None, f"P115StrmHelper 未安装或无法导入: {helper_error}"
        if not servicer:
            return None, "P115StrmHelper 未初始化"
        if not getattr(servicer, "client", None):
            return None, "P115StrmHelper 未登录 115 或客户端不可用"
        helper = getattr(servicer, "sharetransferhelper", None)
        if not helper:
            return None, "P115StrmHelper 分享转存模块不可用"
        return helper, None

    def health(self) -> Tuple[bool, Dict[str, Any], str]:
        cookie_state = self.cookie_state()
        direct_client, direct_source, direct_error = self.get_direct_client()
        direct_ready = direct_client is not None
        helper, helper_error = self.get_share_helper()
        helper_ready = bool(helper and not helper_error)
        ready = direct_ready or helper_ready
        message = "" if ready else direct_error or helper_error or "115 转存不可用"
        return ready, {
            "ready": ready,
            "direct_ready": direct_ready,
            "direct_source": direct_source if direct_ready else "",
            "direct_message": "" if direct_ready else direct_error,
            "helper_ready": helper_ready,
            "helper_message": "" if helper_ready else helper_error,
            "cookie_state": cookie_state,
            "message": message or "success",
        }, message

    def _get_or_create_path_cid(self, client: Any, path: str) -> int:
        return self._get_path_cid(client, path, create=True)

    def _get_path_cid(self, client: Any, path: str, *, create: bool = True) -> int:
        target_path = self.normalize_pan_path(path) or "/"
        if target_path == "/":
            return 0
        get_kwargs = self._p115_request_kwargs(app=False)
        mkdir_kwargs = self._p115_request_kwargs(app=True)
        try:
            resp = client.fs_dir_getid(target_path, **get_kwargs)
            pid = self._safe_int(resp.get("id") if isinstance(resp, dict) else None, -1)
            if pid > 0:
                return pid
        except Exception:
            pass

        if not create:
            return -1

        try:
            resp = client.fs_makedirs_app(target_path, pid=0, **mkdir_kwargs)
            cid = self._safe_int(resp.get("cid") if isinstance(resp, dict) else None, -1)
            if cid >= 0:
                return cid
            if self._response_ok(resp):
                cid = self._safe_int((resp.get("data") or {}).get("cid") if isinstance(resp.get("data"), dict) else None, -1)
                if cid >= 0:
                    return cid
            raise RuntimeError(self._response_error(resp))
        except Exception as exc:
            raise RuntimeError(f"无法创建或定位 115 目录 {target_path}: {exc}") from exc

    def list_directory_current_layer(self, path: str = "") -> Tuple[bool, Dict[str, Any], str]:
        target_path = self.normalize_pan_path(path) or self.default_target_path or "/待整理"
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": False,
            "path": target_path,
            "items": [],
            "file_count": 0,
            "folder_count": 0,
            "removed_count": 0,
            "message": "",
        }
        client, source, client_error = self.get_direct_client()
        if not client:
            result["message"] = client_error or "没有可用的 115 客户端"
            result["direct_source"] = source
            return False, result, result["message"]

        cid = self._get_path_cid(client, target_path, create=False)
        if cid < 0:
            result["ok"] = True
            result["direct_source"] = source
            result["message"] = "115 默认目录不存在，视为空目录"
            return True, result, result["message"]

        payload = {
            "cid": int(cid),
            "limit": 1150,
            "offset": 0,
            "show_dir": 1,
            "cur": 1,
            "count_folders": 1,
        }
        items: list[dict[str, Any]] = []
        total = 0
        try:
            while True:
                resp = client.fs_files(payload, **self._p115_request_kwargs(app=False))
                if not isinstance(resp, dict):
                    result["message"] = "读取 115 目录失败：返回内容异常"
                    result["direct_source"] = source
                    return False, result, result["message"]
                batch = resp.get("data") or []
                total = self._safe_int(resp.get("count"), total)
                for entry in batch:
                    if not isinstance(entry, dict):
                        continue
                    fid = self._safe_int(entry.get("fid"), -1)
                    item_cid = self._safe_int(entry.get("cid"), -1)
                    is_dir = fid < 0
                    item_id = item_cid if is_dir else fid
                    if item_id < 0:
                        continue
                    items.append(
                        {
                            "id": item_id,
                            "name": self.normalize_text(entry.get("n") or entry.get("fn") or entry.get("file_name")),
                            "is_dir": is_dir,
                            "type": "folder" if is_dir else "file",
                            "raw": entry,
                        }
                    )
                payload["offset"] = int(payload["offset"]) + len(batch)
                if not batch or len(batch) < int(payload["limit"]) or int(payload["offset"]) >= total:
                    break
        except Exception as exc:
            result["message"] = f"读取 115 目录失败: {exc}"
            result["direct_source"] = source
            return False, result, result["message"]

        file_count = len([item for item in items if not item.get("is_dir")])
        folder_count = len([item for item in items if item.get("is_dir")])
        result.update(
            {
                "ok": True,
                "direct_source": source,
                "cid": cid,
                "items": items,
                "file_count": file_count,
                "folder_count": folder_count,
                "message": "success",
            }
        )
        return True, result, "success"

    def delete_items(self, items: list[dict[str, Any]]) -> Tuple[bool, Dict[str, Any], str]:
        client, source, client_error = self.get_direct_client()
        result = {
            "ok": False,
            "direct_source": source,
            "removed_count": 0,
            "message": "",
        }
        if not client:
            result["message"] = client_error or "没有可用的 115 客户端"
            return False, result, result["message"]

        ids = [str(self._safe_int(item.get("id"), -1)) for item in items or [] if self._safe_int(item.get("id"), -1) >= 0]
        if not ids:
            result.update({"ok": True, "message": "115 默认目录当前层已是空目录"})
            return True, result, result["message"]

        try:
            resp = client.fs_delete(ids, **self._p115_request_kwargs(app=False))
        except Exception as exc:
            result["message"] = f"删除 115 目录内容失败: {exc}"
            return False, result, result["message"]

        if not self._response_ok(resp):
            result["message"] = self._response_error(resp) or "删除 115 目录内容失败"
            result["raw"] = self.jsonable(resp)
            return False, result, result["message"]

        result.update(
            {
                "ok": True,
                "removed_count": len(ids),
                "message": "115 默认目录已清空当前层",
                "raw": self.jsonable(resp),
            }
        )
        return True, result, result["message"]

    def clear_directory(self, path: str = "") -> Tuple[bool, Dict[str, Any], str]:
        target_path = self.normalize_pan_path(path) or self.default_target_path or "/待整理"
        listed_ok, listed_result, listed_message = self.list_directory_current_layer(target_path)
        if not listed_ok:
            return False, listed_result, listed_message

        items = listed_result.get("items") or []
        if not items:
            listed_result["message"] = "115 默认目录当前层已是空目录"
            return True, listed_result, listed_result["message"]

        delete_ok, delete_result, delete_message = self.delete_items(items)
        merged = dict(listed_result)
        merged.update(
            {
                "ok": delete_ok,
                "removed_count": delete_result.get("removed_count", 0),
                "direct_source": delete_result.get("direct_source", listed_result.get("direct_source")),
                "delete_raw": delete_result.get("raw"),
                "message": delete_message,
            }
        )
        return delete_ok, merged, delete_message

    def transfer_share_direct(
        self,
        *,
        url: str = "",
        access_code: str = "",
        path: str = "",
        trigger: str = "Agent影视助手",
    ) -> Tuple[bool, Dict[str, Any], str]:
        transfer_path = self.normalize_pan_path(path) or self.default_target_path or "/待整理"
        share_url = self.ensure_115_share_url(url or "", access_code or "")
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": False,
            "trigger": trigger,
            "strategy": "direct",
            "path": transfer_path,
            "url": share_url,
            "message": "",
            "data": {},
        }
        if not share_url:
            result["message"] = "没有可用于 115 转存的分享链接"
            return False, result, result["message"]
        if not self.is_115_share_url(share_url):
            result["message"] = "当前链接不是 115 分享链接，无法直接转存到 115"
            return False, result, result["message"]

        share_code, receive_code = self._extract_115_payload(share_url)
        if not share_code or not receive_code:
            result["message"] = "解析 115 分享链接失败，缺少分享码或提取码"
            return False, result, result["message"]

        client, source, client_error = self.get_direct_client()
        if not client:
            result["message"] = client_error or "没有可用的 115 直转客户端"
            result["data"] = {"direct_source": source}
            return False, result, result["message"]

        try:
            parent_id = self._get_or_create_path_cid(client, transfer_path)
        except Exception as exc:
            result["message"] = str(exc)
            result["data"] = {"direct_source": source}
            return False, result, result["message"]

        payload = {
            "share_code": share_code,
            "receive_code": receive_code,
            "file_id": 0,
            "cid": int(parent_id),
            "is_check": 0,
        }
        try:
            resp = client.share_receive(payload, **self._p115_request_kwargs(app=False))
        except Exception as exc:
            result["message"] = f"调用 115 直转接口失败: {exc}"
            result["data"] = {"direct_source": source, "parent_id": parent_id}
            return False, result, result["message"]

        if not self._response_ok(resp):
            result["message"] = self._response_error(resp) or "115 直转失败"
            result["data"] = {
                "direct_source": source,
                "parent_id": parent_id,
                "raw": self.jsonable(resp),
            }
            if self._is_already_saved_message(result["message"]):
                result["ok"] = True
                result["message"] = "115 直转已存在"
                return True, result, result["message"]
            return False, result, result["message"]

        result.update(
            {
                "ok": True,
                "message": "115 直转成功",
                "data": {
                    "direct_source": source,
                    "share_code": share_code,
                    "receive_code": receive_code,
                    "save_parent": transfer_path,
                    "parent_id": parent_id,
                    "raw": self.jsonable(resp),
                },
            }
        )
        return True, result, result["message"]

    def transfer_share(
        self,
        *,
        url: str = "",
        access_code: str = "",
        path: str = "",
        trigger: str = "Agent影视助手",
    ) -> Tuple[bool, Dict[str, Any], str]:
        transfer_path = self.normalize_pan_path(path) or self.default_target_path or "/待整理"
        share_url = self.ensure_115_share_url(url or "", access_code or "")
        result = {
            "time": self.tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": False,
            "trigger": trigger,
            "path": transfer_path,
            "url": share_url,
            "message": "",
            "data": {},
        }
        if not share_url:
            result["message"] = "没有可用于 115 转存的分享链接"
            return False, result, result["message"]
        if not self.is_115_share_url(share_url):
            result["message"] = "当前链接不是 115 分享链接，无法直接转存到 115"
            return False, result, result["message"]

        if self.prefer_direct:
            direct_ok, direct_result, direct_message = self.transfer_share_direct(
                url=share_url,
                access_code=access_code,
                path=transfer_path,
                trigger=trigger,
            )
            if direct_ok:
                return True, direct_result, direct_message
            result["data"]["direct_fallback"] = direct_result

        helper, helper_error = self.get_share_helper()
        if helper_error or not helper:
            direct_error = ((result.get("data") or {}).get("direct_fallback") or {}).get("message")
            result["message"] = (
                "115 转存不可用：请先发“115登录”完成扫码，或检查 115 直转依赖。"
                f" 直转状态：{direct_error or '未知'}；兼容 fallback：{helper_error or '不可用'}"
            )
            return False, result, result["message"]

        try:
            transfer_result = helper.add_share_115(
                share_url,
                notify=False,
                pan_path=transfer_path,
            )
        except Exception as exc:
            result["message"] = f"调用 P115StrmHelper 转存失败: {exc}"
            return False, result, result["message"]

        if not transfer_result or not transfer_result[0]:
            error_message = ""
            if isinstance(transfer_result, tuple):
                if len(transfer_result) > 2:
                    error_message = self.normalize_text(transfer_result[2])
                elif len(transfer_result) > 1:
                    error_message = self.normalize_text(transfer_result[1])
            if self._is_already_saved_message(error_message):
                result.update(
                    {
                        "ok": True,
                        "strategy": "p115strmhelper",
                        "message": "115 转存已存在",
                        "data": {"raw": self.jsonable(transfer_result)},
                    }
                )
                return True, result, result["message"]
            result["message"] = error_message or "115 转存失败"
            result["data"] = {"raw": self.jsonable(transfer_result)}
            return False, result, result["message"]

        media_info = transfer_result[1] if len(transfer_result) > 1 else None
        save_parent = transfer_result[2] if len(transfer_result) > 2 else transfer_path
        parent_id = transfer_result[3] if len(transfer_result) > 3 else None
        result.update(
            {
                "ok": True,
                "strategy": "p115strmhelper",
                "message": "115 转存成功",
                "data": {
                    "media_info": self.jsonable(media_info),
                    "save_parent": save_parent,
                    "parent_id": parent_id,
                },
            }
        )
        return True, result, result["message"]
