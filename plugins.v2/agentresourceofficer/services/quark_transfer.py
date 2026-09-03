import json
import random
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlparse, urlencode
from urllib.request import Request as UrlRequest, urlopen

from app.log import logger

try:
    from app.core.config import settings
except Exception:
    settings = None


class QuarkTransferService:
    """
    Reusable execution layer migrated out of QuarkShareSaver.

    This service intentionally focuses on transfer execution and directory
    resolution. UI, plugin form logic, and entry adapters stay outside.
    """

    def __init__(
        self,
        *,
        cookie: str = "",
        timeout: int = 30,
        default_target_path: str = "/飞书",
        auto_import_cookiecloud: bool = True,
        cookie_refresh_callback: Optional[Callable[[], str]] = None,
    ) -> None:
        self.cookie = self.clean_text(cookie)
        self.timeout = max(10, self.safe_int(timeout, 30))
        self.default_target_path = self.normalize_path(default_target_path or "/飞书")
        self.auto_import_cookiecloud = auto_import_cookiecloud
        self.cookie_refresh_callback = cookie_refresh_callback
        self.path_cache: Dict[str, str] = {"/": "0"}

    @staticmethod
    def clean_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def normalize_path(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return "/"
        if not text.startswith("/"):
            text = f"/{text}"
        text = re.sub(r"/+", "/", text)
        return text.rstrip("/") or "/"

    @staticmethod
    def extract_url(raw_text: str) -> str:
        match = re.search(r"https?://[^\s<>\"']+", raw_text)
        if match:
            return match.group(0).rstrip(".,);]")
        return ""

    @classmethod
    def extract_share_info(cls, share_text: str, access_code: str = "") -> Tuple[str, str, str]:
        raw = cls.clean_text(share_text)
        share_url = cls.extract_url(raw) or raw
        parsed = urlparse(share_url)
        pwd_id_match = re.search(r"/s/([^/?#]+)", parsed.path)
        pwd_id = pwd_id_match.group(1).strip() if pwd_id_match else ""

        code = cls.clean_text(access_code)
        if not code:
            query = dict(parse_qsl(parsed.query))
            code = cls.clean_text(query.get("pwd") or query.get("passcode") or query.get("code"))
        if not code and raw:
            for token in raw.replace(share_url, " ").split():
                text = token.strip()
                if not text:
                    continue
                if "=" in text:
                    key, value = text.split("=", 1)
                    if key.strip().lower() in {"pwd", "passcode", "code", "提取码"}:
                        code = cls.clean_text(value)
                        break
                elif len(text) <= 8 and not text.startswith("/"):
                    code = text
                    break

        return share_url, pwd_id, code

    @staticmethod
    def is_quark_share_url(share_url: str) -> bool:
        hostname = urlparse(share_url).hostname or ""
        hostname = hostname.lower().strip(".")
        return hostname.endswith("quark.cn")

    @classmethod
    def validate_share_url(cls, share_url: str) -> Tuple[bool, str]:
        if not share_url:
            return False, "未识别到有效夸克分享链接"
        if cls.is_quark_share_url(share_url):
            return True, ""
        hostname = urlparse(share_url).hostname or "未知域名"
        return False, f"当前链接域名为 {hostname}，这不是夸克分享链接，请换成 pan.quark.cn 的分享链接"

    def set_cookie(self, cookie: str) -> None:
        self.cookie = self.clean_text(cookie)

    def _tz_now(self) -> datetime:
        if settings is not None:
            try:
                from zoneinfo import ZoneInfo

                return datetime.now(ZoneInfo(getattr(settings, "TZ", "Asia/Shanghai")))
            except Exception:
                pass
        return datetime.now()

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Cookie": self.cookie,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://pan.quark.cn",
            "Referer": "https://pan.quark.cn/",
            "Content-Type": "application/json;charset=UTF-8",
        }

    @staticmethod
    def _common_params() -> Dict[str, Any]:
        now = int(time.time() * 1000)
        return {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
            "__dt": random.randint(100, 9999),
            "__t": now,
        }

    def _refresh_cookie(self) -> bool:
        if not self.auto_import_cookiecloud or not self.cookie_refresh_callback:
            return False
        try:
            cookie = self.clean_text(self.cookie_refresh_callback())
        except Exception as exc:
            logger.warning(f"[Agent影视助手] 刷新夸克 Cookie 失败: {exc}")
            return False
        if not cookie:
            return False
        self.cookie = cookie
        return True

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        allow_cookie_retry: bool = True,
    ) -> Tuple[bool, Dict[str, Any], str]:
        final_url = url
        if params:
            query = urlencode([(key, "" if value is None else value) for key, value in params.items()])
            final_url = f"{url}?{query}" if query else url

        payload = None
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")

        try:
            request = UrlRequest(
                url=final_url,
                data=payload,
                headers=self._build_headers(),
                method=method.upper(),
            )
            with urlopen(request, timeout=self.timeout) as response:
                status_code = getattr(response, "status", 200)
                raw_body = response.read()
        except HTTPError as exc:
            status_code = exc.code
            raw_body = exc.read() if hasattr(exc, "read") else b""
        except URLError as exc:
            return False, {}, f"请求失败: {exc.reason}"
        except Exception as exc:
            return False, {}, f"请求失败: {exc}"

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            text = raw_body.decode("utf-8", errors="ignore")[:300]
            return False, {}, f"接口返回非 JSON: HTTP {status_code} {text}"

        if status_code in {401, 403} and allow_cookie_retry and self._refresh_cookie():
            return self._request(
                method,
                url,
                params=params,
                json_body=json_body,
                allow_cookie_retry=False,
            )

        if status_code != 200:
            if isinstance(data, dict):
                code = self.clean_text(data.get("code"))
                detail = self.clean_text(data.get("message") or data.get("msg"))
                if detail:
                    if code:
                        return False, data, f"HTTP {status_code} [{code}]: {detail}"
                    return False, data, f"HTTP {status_code}: {detail}"
            return False, data if isinstance(data, dict) else {}, f"HTTP {status_code}"

        if isinstance(data, dict):
            message = str(data.get("message") or data.get("msg") or "").strip()
            ok = data.get("status") == 200 or data.get("code") == 0 or message == "ok"
            if ok:
                return True, data, ""
            return False, data, message or "接口返回失败"

        return False, {}, "接口返回格式错误"

    def get_stoken(self, pwd_id: str, access_code: str = "") -> Tuple[bool, str, str]:
        ok, data, message = self._request(
            "POST",
            "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token",
            params=self._common_params(),
            json_body={"pwd_id": pwd_id, "passcode": access_code or ""},
        )
        if not ok:
            return False, "", message

        stoken = self.clean_text((data.get("data") or {}).get("stoken"))
        if not stoken:
            return False, "", "未获取到 stoken，可能是提取码错误或 Cookie 失效"
        return True, stoken, ""

    def get_share_items(self, pwd_id: str, stoken: str) -> Tuple[bool, List[Dict[str, Any]], str]:
        items: List[Dict[str, Any]] = []
        page = 1
        while True:
            params = self._common_params()
            params.update(
                {
                    "pwd_id": pwd_id,
                    "stoken": stoken,
                    "pdir_fid": "0",
                    "force": "0",
                    "_page": str(page),
                    "_size": "50",
                    "_sort": "file_type:asc,updated_at:desc",
                }
            )
            ok, data, message = self._request(
                "GET",
                "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/detail",
                params=params,
            )
            if not ok:
                return False, [], message

            payload = data.get("data") or {}
            meta = data.get("metadata") or {}
            current = payload.get("list") or []
            for item in current:
                items.append(
                    {
                        "fid": str(item.get("fid") or ""),
                        "file_name": str(item.get("file_name") or ""),
                        "dir": bool(item.get("dir")),
                        "file_type": item.get("file_type"),
                        "pdir_fid": str(item.get("pdir_fid") or ""),
                        "share_fid_token": str(item.get("share_fid_token") or ""),
                    }
                )

            total = self.safe_int(meta.get("_total"), 0)
            count = self.safe_int(meta.get("_count"), len(current))
            size = max(1, self.safe_int(meta.get("_size"), 50))
            if total <= len(items) or count < size:
                break
            page += 1

        if not items:
            return False, [], "分享链接为空，或当前账号无权查看内容"
        return True, items, ""

    def list_children(self, parent_fid: str) -> Tuple[bool, List[Dict[str, Any]], str]:
        page = 1
        result: List[Dict[str, Any]] = []
        while True:
            params = {
                "pr": "ucpro",
                "fr": "pc",
                "uc_param_str": "",
                "pdir_fid": parent_fid,
                "_page": page,
                "_size": 100,
                "_fetch_total": 1,
                "_fetch_sub_dirs": 0,
                "_sort": "file_type:asc,updated_at:desc",
            }
            ok, data, message = self._request(
                "GET",
                "https://drive-pc.quark.cn/1/clouddrive/file/sort",
                params=params,
            )
            if not ok:
                return False, [], message

            current = ((data.get("data") or {}).get("list")) or []
            for item in current:
                result.append(
                    {
                        "fid": str(item.get("fid") or ""),
                        "name": str(item.get("file_name") or ""),
                        "dir": int(item.get("file_type") or 0) == 0,
                        "size": item.get("size") or 0,
                        "updated_at": item.get("updated_at") or 0,
                        "raw": item,
                    }
                )
            if len(current) < 100:
                break
            page += 1

        return True, result, ""

    def delete_items(self, items: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any], str]:
        source_items = [item for item in (items or []) if isinstance(item, dict)]

        def build_fids(candidates: List[Dict[str, Any]]) -> List[str]:
            result: List[str] = []
            for item in candidates:
                fid = self.clean_text(item.get("fid"))
                if fid:
                    result.append(fid)
            return result

        def item_label(item: Dict[str, Any]) -> str:
            return self.clean_text(item.get("name") or item.get("file_name") or item.get("fid"))

        def call_delete(candidates: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any], str]:
            fids = build_fids(candidates)
            if not fids:
                return False, {}, "默认目录当前层没有可删除项目"
            payloads = [
                {
                    "action_type": 2,
                    "exclude_fids": [],
                    "filelist": [{"fid": fid} for fid in fids],
                },
                {
                    "action_type": 2,
                    "exclude_fids": [],
                    "filelist": fids,
                },
                {
                    # Some web scripts historically used this misspelled key.
                    "actoin_type": 2,
                    "exclude_fids": [],
                    "filelist": fids,
                },
            ]
            last_data: Dict[str, Any] = {}
            last_message = ""
            for index, payload in enumerate(payloads, start=1):
                ok, data, message = self._request(
                    "POST",
                    "https://drive-pc.quark.cn/1/clouddrive/file/delete",
                    params={
                        "pr": "ucpro",
                        "fr": "pc",
                        "uc_param_str": "",
                    },
                    json_body=payload,
                )
                if ok:
                    if isinstance(data, dict):
                        data["delete_payload_variant"] = index
                    return True, data, ""
                last_data = data if isinstance(data, dict) else {}
                last_message = message or last_message
            return False, last_data, last_message or "夸克删除失败"

        filelist: List[Dict[str, Any]] = []
        for item in source_items:
            fid = self.clean_text((item or {}).get("fid")) if isinstance(item, dict) else ""
            if fid:
                filelist.append({"fid": fid})
        if not filelist:
            return False, {}, "默认目录当前层没有可删除项目"

        ok, data, message = call_delete(source_items)
        if ok:
            data["deleted_count"] = len(filelist)
            data["delete_mode"] = "batch"
            return True, data, ""

        if len(source_items) <= 1:
            return False, data, message or "夸克删除失败"

        deleted_count = 0
        failed_items: List[Dict[str, Any]] = []
        for item in source_items:
            single_ok, single_data, single_message = call_delete([item])
            if single_ok:
                deleted_count += 1
                continue
            failed_items.append({
                "fid": self.clean_text(item.get("fid")),
                "name": item_label(item),
                "message": single_message or "删除失败",
                "result": single_data,
            })

        result = {
            "deleted_count": deleted_count,
            "failed_count": len(failed_items),
            "failed_items": failed_items[:20],
            "delete_mode": "single_fallback",
            "batch_error": message or "夸克批量删除失败",
            "batch_result": data,
        }
        if failed_items:
            return False, result, f"夸克逐项删除后仍有 {len(failed_items)} 项失败"
        return True, result, ""

    def clear_directory(self, path: str = "") -> Tuple[bool, Dict[str, Any], str]:
        ok, target_fid, normalized_path = self.ensure_target_dir(path or self.default_target_path)
        if not ok:
            return False, {}, target_fid or "定位夸克目录失败"

        ok, children, message = self.list_children(target_fid)
        if not ok:
            return False, {}, message or "读取夸克目录失败"

        files = [item for item in children if not bool(item.get("dir"))]
        folders = [item for item in children if bool(item.get("dir"))]
        if not children:
            return True, {
                "target_path": normalized_path,
                "target_fid": target_fid,
                "removed_count": 0,
                "file_count": 0,
                "folder_count": 0,
                "items": [],
                "time": self._tz_now().strftime("%Y-%m-%d %H:%M:%S"),
            }, "默认目录当前层为空"

        ok, delete_result, message = self.delete_items(children)
        removed_count = self.safe_int((delete_result or {}).get("deleted_count"), len(children) if ok else 0)
        if not ok:
            return False, {
                "target_path": normalized_path,
                "target_fid": target_fid,
                "file_count": len(files),
                "folder_count": len(folders),
                "removed_count": removed_count,
                "items": [self.clean_text(item.get("name")) for item in children[:20]],
                "failed_items": (delete_result or {}).get("failed_items") or [],
                "delete_result": delete_result,
            }, message or "夸克清空默认目录失败"

        return True, {
            "target_path": normalized_path,
            "target_fid": target_fid,
            "removed_count": removed_count,
            "file_count": len(files),
            "folder_count": len(folders),
            "items": [self.clean_text(item.get("name")) for item in children[:20]],
            "delete_result": delete_result,
            "time": self._tz_now().strftime("%Y-%m-%d %H:%M:%S"),
        }, "success"

    def find_child_dir(self, parent_fid: str, name: str) -> Tuple[bool, str, str]:
        ok, items, message = self.list_children(parent_fid)
        if not ok:
            return False, "", message
        for item in items:
            if item.get("dir") and item.get("name") == name:
                return True, str(item.get("fid") or ""), ""
        return True, "", ""

    def create_folder(self, parent_fid: str, name: str) -> Tuple[bool, str, str]:
        ok, data, message = self._request(
            "POST",
            "https://pan.quark.cn/1/clouddrive/file/create",
            json_body={
                "pdir_fid": parent_fid,
                "file_name": name,
                "dir_path": "",
                "dir_init_lock": False,
            },
        )
        if not ok:
            return False, "", message

        folder = data.get("data") or {}
        folder_id = self.clean_text(folder.get("fid") or folder.get("file_id"))
        if not folder_id:
            return False, "", "创建目录成功但未返回 fid"
        return True, folder_id, ""

    def ensure_target_dir(self, path: str) -> Tuple[bool, str, str]:
        normalized = self.normalize_path(path or self.default_target_path)
        if normalized == "/":
            return True, "0", normalized
        cached = self.path_cache.get(normalized)
        if cached:
            return True, cached, normalized

        current_fid = "0"
        built = ""
        for part in [segment for segment in normalized.split("/") if segment]:
            built = f"{built}/{part}" if built else f"/{part}"
            cached = self.path_cache.get(built)
            if cached:
                current_fid = cached
                continue

            ok, found_fid, message = self.find_child_dir(current_fid, part)
            if not ok:
                return False, "", message
            if not found_fid:
                ok, found_fid, message = self.create_folder(current_fid, part)
                if not ok:
                    return False, "", f"创建目录失败 {built}: {message}"
            self.path_cache[built] = found_fid
            current_fid = found_fid
        return True, current_fid, normalized

    def create_save_task(
        self,
        pwd_id: str,
        stoken: str,
        items: List[Dict[str, Any]],
        to_pdir_fid: str,
    ) -> Tuple[bool, str, str]:
        fid_list = [str(item.get("fid") or "") for item in items if item.get("fid")]
        fid_token_list = [
            str(item.get("share_fid_token") or "")
            for item in items
            if item.get("fid") and item.get("share_fid_token")
        ]
        if not fid_list or len(fid_list) != len(fid_token_list):
            return False, "", "分享内容缺少 fid 或 share_fid_token，无法转存"

        params = self._common_params()
        ok, data, message = self._request(
            "POST",
            "https://drive.quark.cn/1/clouddrive/share/sharepage/save",
            params=params,
            json_body={
                "fid_list": fid_list,
                "fid_token_list": fid_token_list,
                "to_pdir_fid": to_pdir_fid,
                "pwd_id": pwd_id,
                "stoken": stoken,
                "pdir_fid": "0",
                "scene": "link",
            },
        )
        if not ok:
            return False, "", message

        task_id = self.clean_text((data.get("data") or {}).get("task_id"))
        if not task_id:
            return False, "", "未获取到转存任务 ID"
        return True, task_id, ""

    def wait_task(self, task_id: str, retry: int = 20) -> Tuple[bool, Dict[str, Any], str]:
        for index in range(retry):
            time.sleep(1.0 if index == 0 else 1.5)
            params = {
                "pr": "ucpro",
                "fr": "pc",
                "uc_param_str": "",
                "task_id": task_id,
                "retry_index": index,
                "__dt": 21192,
                "__t": int(time.time() * 1000),
            }
            ok, data, message = self._request(
                "GET",
                "https://drive-pc.quark.cn/1/clouddrive/task",
                params=params,
            )
            if not ok:
                return False, {}, message

            task = data.get("data") or {}
            status = self.safe_int(task.get("status"), -1)
            if status == 2:
                return True, task, ""
            if status in {3, 4, 5, 6, 7}:
                return False, task, self.clean_text(task.get("message")) or "夸克任务执行失败"

        return False, {}, "等待夸克转存任务超时"

    def check_cookie(self) -> Tuple[bool, str]:
        ok, _, message = self.list_children("0")
        if ok:
            return True, ""
        return False, message or "Cookie 校验失败"

    def transfer_share(
        self,
        share_text: str,
        access_code: str = "",
        target_path: str = "",
        *,
        trigger: str = "Agent影视助手",
    ) -> Tuple[bool, Dict[str, Any], str]:
        share_url, pwd_id, final_code = self.extract_share_info(share_text, access_code)
        ok, message = self.validate_share_url(share_url)
        if not ok:
            return False, {}, message
        if not pwd_id:
            return False, {}, "未识别到有效夸克分享链接"
        if not self.cookie:
            self._refresh_cookie()
        if not self.cookie:
            return False, {}, "未配置夸克 Cookie"

        ok, stoken, message = self.get_stoken(pwd_id, final_code)
        if not ok:
            return False, {}, message

        ok, share_items, message = self.get_share_items(pwd_id, stoken)
        if not ok:
            return False, {}, message

        ok, target_fid, normalized_path = self.ensure_target_dir(target_path or self.default_target_path)
        if not ok:
            return False, {}, target_fid

        ok, task_id, message = self.create_save_task(pwd_id, stoken, share_items, target_fid)
        if not ok:
            return False, {}, message

        ok, task, message = self.wait_task(task_id)
        if not ok:
            return False, {"task_id": task_id}, message

        item_names = [str(item.get("file_name") or "") for item in share_items if item.get("file_name")]
        result = {
            "share_url": share_url,
            "pwd_id": pwd_id,
            "access_code": final_code,
            "target_path": normalized_path,
            "target_fid": target_fid,
            "task_id": task_id,
            "saved_count": len(share_items),
            "items": item_names[:20],
            "task": task,
            "trigger": trigger,
            "time": self._tz_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return True, result, "success"
