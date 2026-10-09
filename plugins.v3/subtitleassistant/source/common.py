"""第三方字幕源共用的安全 HTTP 与缓存工具。"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from anyio import Path as AsyncPath

from app.utils.http import AsyncRequestUtils

from ..schemas.source import SourceErrorCode


class SourceRequestError(RuntimeError):
    """不包含响应原文和敏感字段的字幕源请求错误。"""

    def __init__(
        self,
        message: str,
        error_code: SourceErrorCode = SourceErrorCode.REQUEST_FAILED,
        status_code: int | None = None,
    ) -> None:
        """保存可投影到候选池结果的安全错误类别。"""

        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class SourceLimitedError(SourceRequestError):
    """字幕源明确返回限流时抛出的安全错误。"""

    def __init__(self, message: str, retry_at: datetime | None = None) -> None:
        """保存可选的预计恢复时间。"""

        super().__init__(message)
        self.retry_at = retry_at


def raise_for_status(
    response: Any,
    *,
    context: str,
    limited_codes: frozenset[int] = frozenset({429}),
    retry_at: Callable[[Any], datetime] | None = None,
) -> None:
    """共享 HTTP 状态码阶梯：限流→受限、401/403→凭据无效、5xx→暂时不可用、4xx→请求无效。"""

    if response is None:
        raise SourceRequestError(f"{context}请求失败")
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code in limited_codes:
        raise SourceLimitedError(
            f"{context}暂时受限",
            retry_at=retry_at(response) if retry_at is not None else None,
        )
    if status_code in {401, 403}:
        raise SourceRequestError(f"{context}凭据无效", SourceErrorCode.INVALID_CREDENTIALS)
    if status_code >= 500:
        raise SourceRequestError(f"{context}服务暂时不可用", SourceErrorCode.TEMPORARY_UNAVAILABLE)
    if status_code >= 400:
        raise SourceRequestError(f"{context}请求无效", SourceErrorCode.INVALID_REQUEST)


def _proxy_kwargs(proxies: dict[str, str] | None) -> dict[str, Any]:
    """透传宿主实际支持、但其旧式类型注解未声明可空的代理参数。"""

    return {"proxies": proxies}


def parse_datetime(value: Any, format_string: str | None = None) -> datetime | None:
    """容错解析第三方来源时间并统一为带时区 UTC。"""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        if format_string:
            if "%z" in format_string:
                result = datetime.strptime(value.strip(), format_string).astimezone(UTC)
            else:
                result = datetime.strptime(value.strip(), format_string).replace(tzinfo=UTC)
        else:
            result = datetime.fromisoformat(value.strip())
        if result.tzinfo is None:
            result = result.replace(tzinfo=UTC)
        return result.astimezone(UTC)
    except ValueError:
        return None


def safe_file_name(value: str | None, fallback: str) -> str:
    """移除第三方文件名中的目录部分并提供安全后备名。"""

    name = Path(value or "").name.strip()
    return name or fallback


async def download_file(
    request: AsyncRequestUtils,
    url: str,
    directory: Path,
    file_name: str,
    prefer_response_name: bool = False,
) -> Path:
    """通过 AsyncRequestUtils 流式下载到排他创建的临时文件。"""

    destination: AsyncPath | None = None
    try:
        async with request.get_stream(url=url) as response:
            if response is None:
                raise SourceRequestError("字幕文件请求失败")
            if response.status_code >= 400:
                raise SourceRequestError(
                    f"字幕文件请求返回 HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            selected_name = file_name
            if prefer_response_name:
                response_url = str(getattr(response, "url", "") or "")
                selected_name = response_file_name(
                    getattr(response, "headers", {}),
                    response_url or url,
                    response_file_name({}, url, file_name),
                )
            destination = AsyncPath(directory / safe_file_name(selected_name, "subtitle.bin"))
            await destination.parent.mkdir(parents=True, exist_ok=True)
            async with await destination.open("xb") as output:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    if chunk:
                        await output.write(chunk)
    except BaseException:
        if destination is not None and await destination.exists():
            await destination.unlink()
        raise
    if destination is None:
        raise SourceRequestError("字幕文件请求未产生下载文件")
    return Path(destination)


def response_file_name(headers: Any, url: str, fallback: str) -> str:
    """优先从响应头、其次从下载地址推导安全文件名。"""

    disposition = str(headers.get("content-disposition") or "") if headers is not None else ""
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.IGNORECASE)
    if encoded:
        return safe_file_name(unquote(encoded.group(1).strip()), fallback)
    quoted = re.search(r'filename="([^"]+)"', disposition, flags=re.IGNORECASE)
    if quoted:
        return safe_file_name(unquote(quoted.group(1).strip()), fallback)
    plain = re.search(r"filename=([^;]+)", disposition, flags=re.IGNORECASE)
    if plain:
        return safe_file_name(unquote(plain.group(1).strip().strip('"')), fallback)
    parsed_path = urlparse(url).path
    url_name = "" if parsed_path.endswith("/") else unquote(Path(parsed_path).name)
    return safe_file_name(url_name, fallback)


def subtitle_format(file_name: str | None, subtype: str | None = None) -> str:
    """从文件名或来源格式名称归一出宿主扩展名。"""

    suffix = Path(file_name or "").suffix.lstrip(".").upper()
    if suffix:
        return suffix
    normalized = (subtype or "").strip().lower()
    aliases = {
        "subrip": "SRT",
        "srt": "SRT",
        "advanced substation alpha": "ASS",
        "ass": "ASS",
        "substation alpha": "SSA",
        "ssa": "SSA",
        "sup": "SUP",
        "pgs": "SUP",
    }
    return aliases.get(normalized, normalized.upper())
