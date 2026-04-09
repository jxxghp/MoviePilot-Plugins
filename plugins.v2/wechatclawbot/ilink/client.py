import base64
import hashlib
import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from app.log import logger
from app.utils.http import RequestUtils


@dataclass
class ILinkIncomingMessage:
    """iLink 归一化入站文本消息。"""

    user_id: str
    text: str
    username: Optional[str] = None
    message_id: Optional[str] = None
    chat_id: Optional[str] = None
    context_token: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class ILinkClient:
    """iLink HTTP 客户端（MVP：二维码登录、文本发送、长轮询收消息）。"""

    def __init__(
        self,
        base_url: str,
        bot_token: Optional[str] = None,
        account_id: Optional[str] = None,
        sync_buf: Optional[str] = None,
        timeout: int = 20,
        log_func: Optional[Callable[[str, str], None]] = None,
    ):
        self.base_url = (base_url or "https://ilinkai.weixin.qq.com").rstrip("/")
        self.bot_token = bot_token
        self.account_id = account_id
        self.sync_buf = sync_buf
        self.timeout = timeout
        self._log_func = log_func
        self.channel_version = "1.0.2"
        self.cdn_base_url = "https://novac2c.cdn.weixin.qq.com/c2c"

    def _log(self, level: str, message: str):
        """输出客户端日志，优先写入插件日志缓冲。"""
        if self._log_func:
            try:
                self._log_func(level, f"[ILinkClient] {message}")
                return
            except Exception:
                pass

        lv = (level or "info").lower()
        if lv == "debug":
            logger.debug(f"[WechatClawBot][ILinkClient] {message}")
        elif lv == "warning":
            logger.warning(f"[WechatClawBot][ILinkClient] {message}")
        elif lv == "error":
            logger.error(f"[WechatClawBot][ILinkClient] {message}")
        else:
            logger.info(f"[WechatClawBot][ILinkClient] {message}")

    def set_credentials(
        self,
        bot_token: Optional[str],
        account_id: Optional[str] = None,
        sync_buf: Optional[str] = None,
    ) -> None:
        self.bot_token = bot_token
        self.account_id = account_id
        if sync_buf is not None:
            self.sync_buf = sync_buf

    def _headers(self, auth_required: bool = True) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "MoviePilot-WechatClawBot/0.1",
        }
        if auth_required and self.bot_token:
            headers["AuthorizationType"] = "ilink_bot_token"
            headers["Authorization"] = f"Bearer {self.bot_token}"
            headers["X-WECHAT-UIN"] = self._build_wechat_uin()
        return headers

    @staticmethod
    def _build_wechat_uin() -> str:
        """生成 iLink 要求的 X-WECHAT-UIN（base64(random_uint32_decimal_string)）。"""
        random_u32 = random.getrandbits(32)
        return base64.b64encode(str(random_u32).encode("utf-8")).decode("ascii")

    def _with_base_info(self, body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = dict(body or {})
        base_info = payload.get("base_info")
        if not isinstance(base_info, dict):
            base_info = {}
        base_info.setdefault("channel_version", self.channel_version)
        payload["base_info"] = base_info
        return payload

    @staticmethod
    def _json(resp) -> Dict[str, Any]:
        if not resp:
            return {}
        try:
            return resp.json() or {}
        except Exception:
            text = (getattr(resp, "text", "") or "").strip()
            if not text:
                return {}
            try:
                return json.loads(text)
            except Exception:
                return {}

    @staticmethod
    def _ok(payload: Dict[str, Any]) -> bool:
        if not payload:
            return False
        code = payload.get("errcode")
        if code is None:
            code = payload.get("code")
        if code is None:
            code = payload.get("ret")
        if code is None:
            err = payload.get("errmsg") or payload.get("error") or payload.get("error_msg")
            if err and str(err).strip().lower() not in {"ok", "success", "succeed"}:
                return False
            state = payload.get("status") or payload.get("state")
            if isinstance(state, str) and state.strip().lower() in {"error", "failed", "fail"}:
                return False
            return True
        try:
            return int(str(code)) == 0
        except Exception:
            return str(code).strip().lower() in {"0", "ok", "success", "succeed"}

    @staticmethod
    def _short_text(value: Any, max_len: int = 240) -> str:
        """将任意响应内容缩短为单行日志，避免日志过长。"""
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            try:
                text = json.dumps(value, ensure_ascii=False)
            except Exception:
                text = str(value)
        else:
            text = str(value)
        text = text.replace("\n", " ").replace("\r", " ").strip()
        if len(text) > max_len:
            return f"{text[:max_len]}..."
        return text

    def _is_send_success(self, payload: Dict[str, Any]) -> bool:
        """发送接口成功判定，兼容不同返回格式。"""
        if not payload:
            return False

        # 优先使用显式状态码判断。
        code = self._find_first_value(payload, ["errcode", "code", "ret", "result_code", "status_code"])
        if code is not None:
            try:
                return int(str(code)) == 0
            except Exception:
                return str(code).strip().lower() in {"0", "ok", "success", "succeed"}

        # 兼容布尔成功标记。
        success_flag = self._find_first_value(payload, ["success", "ok", "is_success", "sent"])
        if isinstance(success_flag, bool):
            return success_flag
        if success_flag is not None:
            if str(success_flag).strip().lower() in {"1", "true", "ok", "success", "succeed", "sent"}:
                return True

        # 兼容状态字段。
        state = self._find_first_value(payload, ["status", "state", "send_status"])
        if state is not None:
            if str(state).strip().lower() in {"ok", "success", "succeed", "sent", "done"}:
                return True
            if str(state).strip().lower() in {"failed", "error", "denied"}:
                return False

        # 兜底：明确错误信息判定失败。
        err_text = self._find_first_value(payload, ["errmsg", "error", "error_msg", "detail"])
        if err_text is not None and str(err_text).strip():
            err_s = str(err_text).strip().lower()
            if err_s not in {"ok", "success", "succeed", "sent"}:
                return False

        return False

    def _is_send_explicit_failure(self, payload: Dict[str, Any]) -> bool:
        """判断返回是否明确表示失败。"""
        if not payload:
            return False

        code = self._find_first_value(payload, ["errcode", "code", "ret", "result_code", "status_code"])
        if code is not None:
            try:
                return int(str(code)) != 0
            except Exception:
                return str(code).strip().lower() not in {"0", "ok", "success", "succeed"}

        success_flag = self._find_first_value(payload, ["success", "ok", "is_success", "sent"])
        if isinstance(success_flag, bool):
            return not success_flag
        if success_flag is not None:
            val = str(success_flag).strip().lower()
            if val in {"0", "false", "fail", "failed", "error", "denied"}:
                return True

        state = self._find_first_value(payload, ["status", "state", "send_status"])
        if state is not None:
            val = str(state).strip().lower()
            if val in {"failed", "error", "denied", "forbidden", "blocked"}:
                return True

        err_text = self._find_first_value(payload, ["errmsg", "error", "error_msg", "detail"])
        if err_text is not None and str(err_text).strip():
            val = str(err_text).strip().lower()
            if val not in {"ok", "success", "succeed", "sent"}:
                return True

        return False

    def _is_send_http_success(self, resp: Any, payload: Dict[str, Any]) -> bool:
        """官方实现以 HTTP 成功为准；仅在返回明确失败时判为失败。"""
        if resp is None:
            return False
        status_code = getattr(resp, "status_code", None)
        if status_code is None:
            return False
        try:
            status_ok = 200 <= int(status_code) < 300
        except Exception:
            status_ok = False
        if not status_ok:
            return False
        if not payload:
            return True
        return not self._is_send_explicit_failure(payload)

    @staticmethod
    def _build_user_candidates(to_user: str) -> List[str]:
        """构造多种收件人ID格式，兼容 iLink 接口差异。"""
        raw = str(to_user or "").strip()
        if not raw:
            return []

        candidates: List[str] = [raw]
        if "@" in raw:
            candidates.append(raw.split("@", 1)[0])
        if raw.endswith("@im.wechat"):
            candidates.append(raw[:-len("@im.wechat")])
        else:
            candidates.append(f"{raw}@im.wechat")

        uniq: List[str] = []
        for item in candidates:
            value = str(item or "").strip()
            if value and value not in uniq:
                uniq.append(value)
        return uniq

    @staticmethod
    def _build_text_payloads(user_id: str, text: str) -> List[Dict[str, Any]]:
        """构造多种发送请求体，提升 sendmessage 协议兼容性。"""
        return [
            {
                "to_user": user_id,
                "msg_type": "text",
                "text": {"content": text},
            },
            {
                "to_user": user_id,
                "msg_type": "text",
                "text": text,
            },
            {
                "touser": user_id,
                "msgtype": "text",
                "text": {"content": text},
            },
            {
                "touser": user_id,
                "msgtype": "text",
                "text": text,
            },
            {
                "to": user_id,
                "type": "text",
                "content": text,
            },
            {
                "to_user_id": user_id,
                "msg_type": "text",
                "content": text,
            },
            {
                "receiver": user_id,
                "msg_type": "text",
                "text": {"content": text},
            },
            {
                "to_user": user_id,
                "message_type": "text",
                "content": text,
            },
            {
                "to_user": user_id,
                "msg_type": 1,
                "text": {"content": text},
            },
        ]

    @staticmethod
    def _aes_ecb_padded_size(plaintext_size: int) -> int:
        return ((int(plaintext_size) + 1 + 15) // 16) * 16

    @staticmethod
    def _encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
        cipher = AES.new(key, AES.MODE_ECB)
        return cipher.encrypt(pad(plaintext, AES.block_size))

    @staticmethod
    def _encode_media_aes_key(aeskey: bytes) -> str:
        """与官方 openclaw-weixin 保持一致：base64(hex_string)。"""
        return base64.b64encode(aeskey.hex().encode("ascii")).decode("ascii")

    def _build_protocol_msg_payload(self, user_id: str, text: str, context_token: Optional[str]) -> Dict[str, Any]:
        msg = {
            "from_user_id": str(self.account_id or ""),
            "to_user_id": user_id,
            "client_id": f"mp-{uuid.uuid4()}",
            "message_type": 2,
            "message_state": 2,
            "item_list": [
                {
                    "type": 1,
                    "text_item": {
                        "text": text,
                    },
                }
            ],
        }
        if context_token:
            msg["context_token"] = context_token
        return {"msg": msg}

    def _build_protocol_image_payload(
        self,
        user_id: str,
        context_token: Optional[str],
        download_param: str,
        aeskey_b64: str,
        cipher_size: int,
    ) -> Dict[str, Any]:
        msg: Dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": f"mp-{uuid.uuid4()}",
            "message_type": 2,
            "message_state": 2,
            "item_list": [
                {
                    "type": 2,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": download_param,
                            "aes_key": aeskey_b64,
                            "encrypt_type": 1,
                        },
                        "mid_size": int(cipher_size),
                    },
                }
            ],
        }
        if context_token:
            msg["context_token"] = context_token
        return {"msg": msg}

    def _request_upload_param(
        self,
        to_user: str,
        plaintext: bytes,
    ) -> Tuple[Optional[str], Optional[str], Optional[bytes], Optional[int], Optional[str]]:
        rawsize = len(plaintext)
        rawfilemd5 = hashlib.md5(plaintext).hexdigest()
        filesize = self._aes_ecb_padded_size(rawsize)
        filekey = os.urandom(16).hex()
        aeskey = os.urandom(16)

        body = self._with_base_info(
            {
                "filekey": filekey,
                "media_type": 1,
                "to_user_id": to_user,
                "rawsize": rawsize,
                "rawfilemd5": rawfilemd5,
                "filesize": filesize,
                "no_need_thumb": True,
                "aeskey": aeskey.hex(),
            }
        )

        url = f"{self.base_url}/ilink/bot/getuploadurl"
        resp = RequestUtils(headers=self._headers(auth_required=True), timeout=self.timeout).post(url, json=body)
        payload = self._json(resp)
        upload_param = (
            self._find_first_value(payload, ["upload_param", "uploadParam"])
            if payload
            else None
        )
        upload_full_url = (
            self._find_first_value(payload, ["upload_full_url", "uploadFullUrl", "full_url"])
            if payload
            else None
        )
        if not upload_param and not upload_full_url:
            self._log(
                "warning",
                f"getuploadurl 失败: http={getattr(resp, 'status_code', None)}, resp={self._short_text(payload or getattr(resp, 'text', ''))}",
            )
            return None, None, None, None, None

        return (
            str(upload_param) if upload_param else None,
            str(upload_full_url) if upload_full_url else None,
            aeskey,
            filesize,
            filekey,
        )

    def _upload_encrypted_to_cdn(
        self,
        upload_param: Optional[str],
        upload_full_url: Optional[str],
        filekey: str,
        plaintext: bytes,
        aeskey: bytes,
    ) -> Tuple[Optional[str], Optional[int]]:
        ciphertext = self._encrypt_aes_ecb(plaintext, aeskey)
        if upload_full_url:
            upload_url = str(upload_full_url).strip()
        elif upload_param:
            upload_url = (
                f"{self.cdn_base_url}/upload?encrypted_query_param={quote(str(upload_param), safe='')}&"
                f"filekey={quote(filekey, safe='')}"
            )
        else:
            self._log("warning", "CDN 上传失败: 缺少 upload_url 参数")
            return None, None

        resp = RequestUtils(
            headers={"Content-Type": "application/octet-stream"},
            timeout=self.timeout,
        ).post(upload_url, data=ciphertext)

        status_code = getattr(resp, "status_code", None)
        if status_code != 200:
            self._log(
                "warning",
                f"CDN 上传失败: http={status_code}, err={self._short_text(getattr(resp, 'text', ''))}",
            )
            return None, None

        download_param = None
        if resp is not None and getattr(resp, "headers", None):
            download_param = resp.headers.get("x-encrypted-param")
        if not download_param:
            self._log("warning", "CDN 上传成功但缺少 x-encrypted-param")
            return None, None

        return str(download_param), len(ciphertext)

    def get_qrcode(self) -> Dict[str, Any]:
        url = f"{self.base_url}/ilink/bot/get_bot_qrcode?bot_type=3"
        self._log("debug", f"请求二维码: {url}")
        resp = RequestUtils(headers=self._headers(auth_required=False), timeout=self.timeout).get_res(url)
        payload = self._json(resp)
        if not payload:
            self._log("warning", "二维码接口返回空响应")
            return {"success": False, "message": "获取二维码失败"}

        data = payload.get("data") or payload.get("result") or payload
        qrcode = (
            data.get("qrcode")
            or data.get("qr_code")
            or data.get("qrcode_id")
            or data.get("ticket")
        )
        qrcode_url = (
            data.get("qrcode_url")
            or data.get("url")
            or data.get("qrcodeUrl")
            or data.get("qr_url")
            or data.get("qrcode_img_content")
            or data.get("qrcode_img_url")
            or data.get("qr_img")
        )

        # 某些返回仅给出 qrcode id，补一个已知可扫码链接兜底。
        if not qrcode_url and qrcode:
            qrcode_url = f"https://liteapp.weixin.qq.com/q/7GiQu1?qrcode={qrcode}&bot_type=3"

        result = {
            "success": self._ok(payload) and bool(qrcode or qrcode_url),
            "qrcode": qrcode,
            "qrcode_url": qrcode_url,
            "raw": payload,
            "message": payload.get("errmsg") or payload.get("message"),
        }
        self._log(
            "info" if result.get("success") else "warning",
            f"二维码解析结果: success={result.get('success')}, qrcode={result.get('qrcode')}, has_url={bool(result.get('qrcode_url'))}",
        )
        return result

    def get_qrcode_status(self, qrcode: str) -> Dict[str, Any]:
        url = f"{self.base_url}/ilink/bot/get_qrcode_status"
        self._log("debug", f"查询二维码状态: qrcode={qrcode}")
        resp = RequestUtils(headers=self._headers(auth_required=False), timeout=self.timeout).get_res(
            url, params={"qrcode": qrcode}
        )
        payload = self._json(resp)
        if not payload:
            # 某些代理场景下 params 透传异常，补一次显式 query 兜底。
            retry_resp = RequestUtils(headers=self._headers(auth_required=False), timeout=self.timeout).get_res(
                f"{url}?qrcode={qrcode}"
            )
            payload = self._json(retry_resp)
        if not payload:
            self._log("warning", "二维码状态接口返回空响应")
            return {
                "success": False,
                "status": "waiting",
                "token": None,
                "account_id": None,
                "raw": {},
                "message": "二维码状态接口返回空响应",
            }

        data = payload.get("data") or payload.get("result") or payload

        token = (
            data.get("bot_token")
            or data.get("token")
            or data.get("access_token")
            or self._find_first_value(data, ["bot_token", "access_token", "token", "jwt", "auth_token"])
        )
        account_id = (
            data.get("account_id")
            or data.get("ilink_bot_id")
            or data.get("wxid")
            or data.get("uid")
            or data.get("user_id")
            or self._find_first_value(data, ["account_id", "ilink_bot_id", "wxid", "uid", "user_id", "from_user", "from_uid"])
        )
        base_url = (
            data.get("baseurl")
            or data.get("base_url")
            or payload.get("baseurl")
            or payload.get("base_url")
        )

        if token:
            self.bot_token = token
        if account_id:
            self.account_id = str(account_id)

        state = (
            data.get("status")
            or data.get("state")
            or payload.get("status")
            or payload.get("state")
            or self._find_first_value(data, ["status", "state", "scan_status"])
            or "waiting"
        )

        result = {
            "success": self._ok(payload),
            "status": str(state).lower(),
            "token": token,
            "account_id": account_id,
            "base_url": base_url,
            "raw": payload,
            "message": payload.get("errmsg") or payload.get("message"),
        }
        self._log(
            "debug",
            f"二维码状态结果: success={result.get('success')}, status={result.get('status')}, has_token={bool(result.get('token'))}",
        )
        return result

    def send_text(self, to_user: str, text: str, context_token: Optional[str] = None) -> bool:
        if not self.bot_token:
            self._log("warning", "发送消息失败：bot token 未配置")
            return False
        if not to_user or not text:
            self._log("warning", "发送消息失败：to_user 或 text 为空")
            return False

        url_candidates = [
            f"{self.base_url}/ilink/bot/sendmessage",
            f"{self.base_url}/ilink/bot/sendmessage?bot_type=3",
        ]
        user_candidates = self._build_user_candidates(to_user)

        last_error = ""
        for user_id in user_candidates:
            payload_candidates = [
                self._build_protocol_msg_payload(user_id=user_id, text=text, context_token=context_token),
                *self._build_text_payloads(user_id=user_id, text=text),
            ]
            for url in url_candidates:
                for idx, body in enumerate(payload_candidates, start=1):
                    request_body = self._with_base_info(body)
                    resp = RequestUtils(headers=self._headers(auth_required=True), timeout=self.timeout).post(
                        url,
                        json=request_body,
                    )
                    payload = self._json(resp)
                    if self._is_send_success(payload) or self._is_send_http_success(resp, payload):
                        self._log("info", f"发送消息成功: to_user={user_id}, variant={idx}")
                        return True

                    http_code = getattr(resp, "status_code", None)
                    err_msg = (
                        self._find_first_value(payload, ["errmsg", "message", "error", "detail"])
                        if payload
                        else None
                    )
                    if not err_msg and resp is not None:
                        err_msg = self._short_text(getattr(resp, "text", ""))

                    last_error = f"http={http_code}, err={self._short_text(err_msg)}"
                    self._log(
                        "debug",
                        f"发送候选失败: to_user={user_id}, variant={idx}, {last_error}, req={self._short_text(request_body)}, resp={self._short_text(payload)}",
                    )

        self._log("warning", f"发送消息失败: to_user={to_user}, {last_error}")
        return False

    def send_image_text_png(
        self,
        to_user: str,
        image_bytes: bytes,
        text: str,
        context_token: Optional[str] = None,
    ) -> bool:
        """发送图文消息（兼容模式：文本与图片分两条发送）。"""
        if not self.bot_token:
            self._log("warning", "发送图文失败：bot token 未配置")
            return False
        if not to_user or not image_bytes or not text:
            self._log("warning", "发送图文失败：to_user 或 image_bytes 或 text 为空")
            return False

        url_candidates = [
            f"{self.base_url}/ilink/bot/sendmessage",
            f"{self.base_url}/ilink/bot/sendmessage?bot_type=3",
        ]

        last_error = ""
        for user_id in self._build_user_candidates(to_user):
            upload_param, upload_full_url, aeskey, _, filekey = self._request_upload_param(user_id, image_bytes)
            if (not upload_param and not upload_full_url) or not aeskey or not filekey:
                continue

            download_param, cipher_size = self._upload_encrypted_to_cdn(
                upload_param=upload_param,
                upload_full_url=upload_full_url,
                filekey=filekey,
                plaintext=image_bytes,
                aeskey=aeskey,
            )
            if not download_param or not cipher_size:
                continue

            aeskey_b64 = self._encode_media_aes_key(aeskey)
            message_items: List[Dict[str, Any]] = [
                {
                    "type": 1,
                    "text_item": {
                        "text": text,
                    },
                },
                {
                    "type": 2,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": download_param,
                            "aes_key": aeskey_b64,
                            "encrypt_type": 1,
                        },
                        "mid_size": int(cipher_size),
                    },
                },
            ]

            sent_all = True
            for item in message_items:
                item_sent = False
                item_type = item.get("type")
                for url in url_candidates:
                    msg: Dict[str, Any] = {
                        "from_user_id": "",
                        "to_user_id": user_id,
                        "client_id": f"mp-{uuid.uuid4()}",
                        "message_type": 2,
                        "message_state": 2,
                        "item_list": [item],
                    }
                    if context_token:
                        msg["context_token"] = context_token

                    body = {"msg": msg}
                    request_body = self._with_base_info(body)
                    resp = RequestUtils(headers=self._headers(auth_required=True), timeout=self.timeout).post(
                        url,
                        json=request_body,
                    )
                    payload = self._json(resp)
                    if self._is_send_success(payload) or self._is_send_http_success(resp, payload):
                        item_sent = True
                        break

                    http_code = getattr(resp, "status_code", None)
                    err_msg = (
                        self._find_first_value(payload, ["errmsg", "message", "error", "detail"])
                        if payload
                        else None
                    )
                    if not err_msg and resp is not None:
                        err_msg = self._short_text(getattr(resp, "text", ""))
                    last_error = f"http={http_code}, err={self._short_text(err_msg)}"
                    self._log(
                        "debug",
                        f"发送图文子消息失败: to_user={user_id}, item_type={item_type}, {last_error}, req={self._short_text(request_body)}, resp={self._short_text(payload)}",
                    )

                if not item_sent:
                    sent_all = False
                    break

            if sent_all:
                self._log("info", f"发送图文成功: to_user={user_id}, mode=split_items")
                return True

        self._log("warning", f"发送图文失败: to_user={to_user}, {last_error}")
        return False

    def send_image_png(self, to_user: str, image_bytes: bytes, context_token: Optional[str] = None) -> bool:
        if not self.bot_token:
            self._log("warning", "发送图片失败：bot token 未配置")
            return False
        if not to_user or not image_bytes:
            self._log("warning", "发送图片失败：to_user 或 image_bytes 为空")
            return False

        url_candidates = [
            f"{self.base_url}/ilink/bot/sendmessage",
            f"{self.base_url}/ilink/bot/sendmessage?bot_type=3",
        ]

        last_error = ""
        for user_id in self._build_user_candidates(to_user):
            upload_param, upload_full_url, aeskey, _, filekey = self._request_upload_param(user_id, image_bytes)
            if (not upload_param and not upload_full_url) or not aeskey or not filekey:
                continue

            download_param, cipher_size = self._upload_encrypted_to_cdn(
                upload_param=upload_param,
                upload_full_url=upload_full_url,
                filekey=filekey,
                plaintext=image_bytes,
                aeskey=aeskey,
            )
            if not download_param or not cipher_size:
                continue

            aeskey_b64 = self._encode_media_aes_key(aeskey)
            body = self._build_protocol_image_payload(
                user_id=user_id,
                context_token=context_token,
                download_param=download_param,
                aeskey_b64=aeskey_b64,
                cipher_size=cipher_size,
            )

            for url in url_candidates:
                request_body = self._with_base_info(body)
                resp = RequestUtils(headers=self._headers(auth_required=True), timeout=self.timeout).post(
                    url,
                    json=request_body,
                )
                payload = self._json(resp)
                if self._is_send_success(payload) or self._is_send_http_success(resp, payload):
                    self._log("info", f"发送图片成功: to_user={user_id}")
                    return True

                http_code = getattr(resp, "status_code", None)
                err_msg = (
                    self._find_first_value(payload, ["errmsg", "message", "error", "detail"])
                    if payload
                    else None
                )
                if not err_msg and resp is not None:
                    err_msg = self._short_text(getattr(resp, "text", ""))
                last_error = f"http={http_code}, err={self._short_text(err_msg)}"
                self._log(
                    "debug",
                    f"发送图片失败: to_user={user_id}, {last_error}, req={self._short_text(request_body)}, resp={self._short_text(payload)}",
                )

        self._log("warning", f"发送图片失败: to_user={to_user}, {last_error}")
        return False

    def _extract_updates(self, payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        data = payload.get("data") or payload.get("result") or payload
        sync_buf = (
            data.get("get_updates_buf")
            or payload.get("get_updates_buf")
            or data.get("sync_buf")
            or data.get("syncBuf")
            or payload.get("sync_buf")
            or payload.get("syncBuf")
            or self._find_first_value(data, ["get_updates_buf", "sync_buf", "syncBuf", "cursor", "offset", "next_sync_buf"])
        )

        list_keys = [
            "msgs",
            "updates",
            "messages",
            "items",
            "events",
            "msg_list",
            "msgList",
            "msgs",
            "add_msgs",
            "addMsgs",
            "records",
            "list",
        ]

        candidates = [
            data.get("msgs"),
            data.get("updates"),
            data.get("messages"),
            data.get("items"),
            data.get("events"),
            data.get("msg_list"),
            data.get("msgList"),
            data.get("msgs"),
            data.get("add_msgs"),
            data.get("addMsgs"),
            payload.get("msgs"),
            payload.get("updates"),
            payload.get("messages"),
            payload.get("events"),
            payload.get("msg_list"),
            payload.get("msgList"),
            payload.get("msgs"),
            payload.get("add_msgs"),
            payload.get("addMsgs"),
        ]
        for item in candidates:
            if isinstance(item, list):
                return item, sync_buf

        nested = self._find_first_list(data, prefer_keys=list_keys)
        if isinstance(nested, list):
            return nested, sync_buf

        if isinstance(data, list):
            return data, sync_buf

        # 少数接口返回单条消息对象。
        if isinstance(data, dict):
            for key in ["message", "msg", "event", "item"]:
                item = data.get(key)
                if isinstance(item, dict):
                    return [item], sync_buf
        return [], sync_buf

    @staticmethod
    def _pick_value(obj: Dict[str, Any], keys: List[str]) -> Optional[Any]:
        for key in keys:
            if key in obj and obj.get(key) not in (None, ""):
                return obj.get(key)
        return None

    @classmethod
    def _find_first_value(cls, data: Any, keys: List[str], max_depth: int = 5) -> Optional[Any]:
        if max_depth < 0 or data is None:
            return None
        if isinstance(data, dict):
            direct = cls._pick_value(data, keys)
            if direct not in (None, ""):
                return direct
            for value in data.values():
                found = cls._find_first_value(value, keys, max_depth - 1)
                if found not in (None, ""):
                    return found
        elif isinstance(data, list):
            for value in data:
                found = cls._find_first_value(value, keys, max_depth - 1)
                if found not in (None, ""):
                    return found
        return None

    @classmethod
    def _find_first_list(cls, data: Any, prefer_keys: List[str], max_depth: int = 5) -> Optional[List[Any]]:
        if max_depth < 0 or data is None:
            return None
        if isinstance(data, dict):
            for key in prefer_keys:
                value = data.get(key)
                if isinstance(value, list):
                    return value
            for value in data.values():
                found = cls._find_first_list(value, prefer_keys, max_depth - 1)
                if found is not None:
                    return found
        elif isinstance(data, list):
            if data and all(isinstance(item, dict) for item in data):
                return data
            for value in data:
                found = cls._find_first_list(value, prefer_keys, max_depth - 1)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _as_scalar(value: Any) -> Optional[Any]:
        if value in (None, ""):
            return None
        if isinstance(value, (dict, list, tuple, set)):
            return None
        return value

    def _parse_incoming(self, item: Dict[str, Any]) -> Optional[ILinkIncomingMessage]:
        if not isinstance(item, dict):
            return None

        message = item
        for key in ["message", "msg", "event", "payload", "data"]:
            child = item.get(key)
            if isinstance(child, dict):
                message = child
                break

        sender = (
            message.get("from")
            if isinstance(message.get("from"), dict)
            else message.get("sender")
            if isinstance(message.get("sender"), dict)
            else message.get("user")
            if isinstance(message.get("user"), dict)
            else message.get("from_user")
            if isinstance(message.get("from_user"), dict)
            else {}
        )

        user_id = (
            self._pick_value(sender, ["user_id", "id", "wxid", "uid"])
            or self._pick_value(message, [
                "from_user",
                "from_user_id",
                "user_id",
                "uid",
                "wxid",
                "from_uid",
                "fromUser",
                "fromUserId",
                "openid",
            ])
            or self._pick_value(item, [
                "from_user",
                "from_user_id",
                "user_id",
                "uid",
                "wxid",
                "from_uid",
                "fromUser",
                "fromUserId",
                "openid",
            ])
            or self._find_first_value(message, [
                "from_user",
                "from_user_id",
                "user_id",
                "sender_id",
                "uid",
                "wxid",
                "from_uid",
                "fromUserId",
                "openid",
            ])
        )
        user_id = self._as_scalar(user_id)
        if not user_id:
            return None

        text = None
        item_list = message.get("item_list") if isinstance(message.get("item_list"), list) else []
        for one in item_list:
            if not isinstance(one, dict):
                continue
            item_type = one.get("type")
            if item_type == 1 and isinstance(one.get("text_item"), dict):
                text = self._pick_value(one.get("text_item") or {}, ["text", "content"])
                if text:
                    break

        if isinstance(message.get("text"), dict):
            text = self._pick_value(message.get("text") or {}, ["content", "text", "value", "msg"])
        if not text:
            text = self._pick_value(message, ["content", "message", "msg", "text", "body", "msg_content", "msgContent"])
        if not text:
            text = self._pick_value(item, ["content", "message", "msg", "text", "body", "msg_content", "msgContent"])
        if not text:
            text = self._find_first_value(message, ["content", "text", "message", "msg", "body", "cmd"]) 

        if not text:
            return None

        if isinstance(text, dict):
            text = self._pick_value(text, ["content", "text", "value", "message"])
        if not isinstance(text, str):
            text = str(text)

        username = (
            self._pick_value(sender, ["name", "nickname", "username", "remark"])
            or self._pick_value(message, ["username", "nickname", "from_name", "fromNick", "sender_name"])
            or str(user_id)
        )
        message_id = (
            self._pick_value(message, ["message_id", "msg_id", "id", "client_msg_id", "msgId"])
            or self._pick_value(item, ["message_id", "msg_id", "id", "client_msg_id", "msgId"])
        )
        chat_id = (
            self._pick_value(message, ["chat_id", "conversation_id", "room_id", "chatId", "conversationId", "roomId"])
            or self._pick_value(item, ["chat_id", "conversation_id", "room_id", "chatId", "conversationId", "roomId"])
        )
        context_token = (
            self._pick_value(message, ["context_token", "contextToken"])
            or self._pick_value(item, ["context_token", "contextToken"])
        )

        return ILinkIncomingMessage(
            user_id=str(user_id),
            text=str(text),
            username=str(username) if username else None,
            message_id=str(message_id) if message_id else None,
            chat_id=str(chat_id) if chat_id else None,
            context_token=str(context_token) if context_token else None,
            raw=item,
        )

    def poll_updates(self, timeout_seconds: int = 25) -> Tuple[List[ILinkIncomingMessage], Optional[str], Dict[str, Any]]:
        if not self.bot_token:
            self._log("warning", "轮询失败：bot token 未配置")
            return [], self.sync_buf, {"success": False, "message": "bot token 未配置"}

        url = f"{self.base_url}/ilink/bot/getupdates"
        payload = {}
        body_candidates = [
            {
                "get_updates_buf": self.sync_buf or "",
            },
            {
                "sync_buf": self.sync_buf,
                "timeout": timeout_seconds,
            },
            {
                "syncBuf": self.sync_buf,
                "timeout": timeout_seconds,
            },
            {
                "sync_buf": self.sync_buf,
                "wait": timeout_seconds,
            },
        ]

        for body in body_candidates:
            request_body = self._with_base_info(body)
            resp = RequestUtils(headers=self._headers(auth_required=True), timeout=timeout_seconds + 10).post(
                url,
                json=request_body,
            )
            payload = self._json(resp)
            if payload and self._ok(payload):
                break
            if payload and self._find_first_list(payload, prefer_keys=["updates", "messages", "items", "events", "add_msgs", "msgs"]):
                break

        if not payload:
            self._log("warning", "轮询接口返回空响应")
            return [], self.sync_buf, {"success": False, "message": "轮询返回空响应"}

        items, sync_buf = self._extract_updates(payload)
        parsed: List[ILinkIncomingMessage] = []
        for item in items:
            msg = self._parse_incoming(item)
            if msg:
                parsed.append(msg)

        if sync_buf is not None:
            self.sync_buf = str(sync_buf)

        result = {
            "success": self._ok(payload),
            "raw": payload,
            "message": payload.get("errmsg") or payload.get("message"),
            "item_count": len(items),
            "parsed_count": len(parsed),
        }
        if items and not parsed:
            sample = items[0] if items else {}
            sample_keys = []
            if isinstance(sample, dict):
                sample_keys = list(sample.keys())[:12]
            self._log(
                "warning",
                f"轮询收到原始消息但未解析到文本: raw_items={len(items)}, sample_keys={sample_keys}",
            )
        elif parsed:
            self._log("info", f"轮询收到文本消息: count={len(parsed)}")
        else:
            self._log("debug", "轮询结果: 无新消息")
        return parsed, self.sync_buf, result

    def test_connection(self) -> Tuple[bool, str]:
        if not self.bot_token:
            self._log("warning", "连接测试失败：未登录")
            return False, "未登录，缺少 bot token"

        url = f"{self.base_url}/ilink/bot/getconfig"
        resp = RequestUtils(headers=self._headers(auth_required=True), timeout=self.timeout).post(url, json={})
        payload = self._json(resp)
        if self._ok(payload):
            self._log("info", "连接测试通过")
            return True, "连接正常"
        message = payload.get("errmsg") or payload.get("message") or "连接失败"
        self._log("warning", f"连接测试失败: {message}")
        return False, message
