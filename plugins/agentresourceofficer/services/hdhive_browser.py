"""
影巢（HDHive）网页方式资源搜索/解锁服务。

通过 MoviePilot 官方 app.helper.browser.PlaywrightHelper（cloakbrowser 后端，
内置反检测与 FlareSolverr），用账号 cookie 在影巢网页上搜索资源、解锁拿 115 链接，
不依赖影巢 OpenAPI。仅在 MoviePilot docker 容器内 headless 运行。

本模块的页面抓取/解锁 JavaScript 与流程改编自 GPL v3 项目
DDSRem-Dev/MoviePilot-Plugins (plugins.v2/p115strmhelper/helper/hdhive/browser.py)。
原仓库: https://github.com/DDSRem-Dev/MoviePilot-Plugins
本仓库同为 GPL v3。
"""
from __future__ import annotations

import concurrent.futures
import re
import time
from typing import Any, Callable, Dict, List, Optional

from app.helper.browser import PlaywrightHelper
from app.log import logger

# 改编自 DDSRem-Dev p115strmhelper browser.py::_scrape_resource_cards_js (GPL v3)
_SCRAPE_CARDS_JS = r"""
() => {
    const sizeRe = /(\d+\.?\d*)\s*(TB|GB|MB|G(?!B)|M(?!B))\b/i;
    const dateRe = /发布于\s*([\d/\-]+)/;
    const resRe = /\b(4K|8K|2K|1080[piP]?|720[piP]?|480[piP]?)\b/;
    const pointsRe = /(\d+)\s*积分/;
    const candidates = [];
    for (const el of document.querySelectorAll('a,div,article,li,section')) {
        const t = el.innerText || '';
        if (!t.includes('发布于') || !sizeRe.test(t)) continue;
        if ((t.match(/发布于/g) || []).length !== 1) continue;
        if (t.length < 30 || t.length > 5000) continue;
        candidates.push(el);
    }
    const minimal = candidates.filter(
        el => !candidates.some(other => other !== el && el.contains(other))
    );
    const metaTerms = new Set([
        '4K','8K','2K','免费','官组','管理员','WEB-DL','WEBRip','BDRip','REMUX','HDTV',
        '简中','繁中','简英','繁英','内封','外挂','内嵌','简日','繁日','简韩','繁韩',
        '1080P','1080p','720P','720p','480P','480p','蓝光原盘','ISO'
    ]);
    return minimal.map(card => {
        const text = card.innerText || '';
        const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
        const dateMatch = text.match(dateRe);
        const sizeMatch = text.match(sizeRe);
        const resMatch = text.match(resRe);
        const pointsMatch = text.match(pointsRe);
        const isFree = text.includes('免费');
        const tags = [];
        if (text.includes('官组') || text.includes('管理员')) tags.push('官组');
        if (isFree) tags.push('免费');
        if (pointsMatch) tags.push(pointsMatch[0].trim());
        const dateLineIdx = lines.findIndex(l => /发布于/.test(l));
        const user = dateLineIdx > 0 ? lines[dateLineIdx - 1] : (lines[0] || '');
        const titleLines = lines.filter(l => {
            if (l.length < 3) return false;
            if (metaTerms.has(l)) return false;
            if (/^发布于/.test(l)) return false;
            if (/^\d+\s*积分$/.test(l)) return false;
            if (/^\d+\.?\d*\s*(T?B|G[Bi]?|M[Bi]?)$/i.test(l)) return false;
            if (l === user) return false;
            return true;
        });
        let title = titleLines
            .map(l => l.replace(/^\d+\s*积分\s*/, '').trim())
            .filter(Boolean).join(' ').trim();
        let hrefEl = card;
        while (hrefEl && hrefEl.tagName !== 'A') { hrefEl = hrefEl.parentElement; }
        const href = hrefEl ? (hrefEl.getAttribute('href') || '') : '';
        return {
            user, posted_at: dateMatch ? dateMatch[1] : '', tags, title,
            resolution: resMatch ? resMatch[1] : '',
            size: sizeMatch ? (sizeMatch[1] + ' ' + sizeMatch[2].toUpperCase()) : '',
            is_free: isFree,
            unlock_points: isFree ? 0 : (pointsMatch ? parseInt(pointsMatch[1]) : null),
            href,
        };
    });
}
"""

# 改编自 DDSRem-Dev p115strmhelper browser.py::unlock_resource 内 _EXTRACT_URL_JS (GPL v3)
_EXTRACT_115_URL_JS = r"""
() => {
    const urlPrefixRe = /^https?:\/\/(115cdn|115)\.com\//;
    for (const el of document.querySelectorAll('input')) {
        const v = (el.value || '').trim();
        if (urlPrefixRe.test(v)) return v;
    }
    for (const el of document.querySelectorAll('div, span, p, a, code')) {
        if (el.children.length > 0) continue;
        const t = (el.textContent || '').trim();
        if (urlPrefixRe.test(t)) return t;
    }
    const m = (document.body?.innerText || '').match(/https?:\/\/(115cdn|115)\.com\/\S+/);
    return m ? m[0].replace(/\s+$/, '') : null;
}
"""


class HDHiveBrowserService:
    def __init__(
        self,
        base_url: str = "https://hdhive.com",
        cookie: str = "",
        timeout: int = 30,
        cookie_refresh_callback: Optional[Callable[[], str]] = None,
    ) -> None:
        self.base_url = (base_url or "https://hdhive.com").rstrip("/")
        self.cookie = (cookie or "").strip()
        self.timeout = int(timeout or 30)
        self.cookie_refresh_callback = cookie_refresh_callback

    def is_ready(self) -> bool:
        return bool(self.cookie)

    @staticmethod
    def _cookie_expired_result() -> Dict[str, str]:
        return {"__hdhive_browser_error__": "cookie_expired"}

    @staticmethod
    def _is_cookie_expired_result(value: Any) -> bool:
        return isinstance(value, dict) and value.get("__hdhive_browser_error__") == "cookie_expired"

    def _refresh_cookie(self) -> str:
        if not self.cookie_refresh_callback:
            return ""
        try:
            cookie = self.cookie_refresh_callback()
        except Exception as exc:
            logger.warning(f"[HDHiveBrowser] 自动刷新 Cookie 失败: {exc}")
            return ""
        cookie = str(cookie or "").strip()
        if cookie:
            self.cookie = cookie
        return cookie

    def _context_cookies(self) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        for part in str(self.cookie or "").split(";"):
            if "=" not in part:
                continue
            name, value = part.strip().split("=", 1)
            name = name.strip()
            value = value.strip()
            if name and value:
                items.append({"name": name, "value": value, "url": f"{self.base_url}/"})
        return items

    def _detail_url(self, media_type: Any, tmdb_id: Any) -> str:
        mt = "movie" if str(media_type).lower() in ("movie", "电影") else "tv"
        return f"{self.base_url}/tmdb/{mt}/{tmdb_id}"

    @staticmethod
    def _normalize(card: Dict[str, Any]) -> Dict[str, Any]:
        href = (card.get("href") or "").strip()
        slug = href.rstrip("/").split("/")[-1] if href else ""
        return {
            "slug": slug,
            "href": href,
            "title": card.get("title", ""),
            "resolution": card.get("resolution", ""),
            "size": card.get("size", ""),
            "is_free": bool(card.get("is_free")),
            "unlock_points": card.get("unlock_points"),
            "user": card.get("user", ""),
            "posted_at": card.get("posted_at", ""),
            "tags": card.get("tags", []),
        }

    def _run_browser_action(self, url: str, callback: Any) -> Any:
        """Run MoviePilot's sync Playwright helper outside the active async request loop."""
        helper_timeout = max(60, self.timeout)

        def _callback_with_context_cookies(page: Any) -> Any:
            context_cookies = self._context_cookies()
            if context_cookies:
                page.context.add_cookies(context_cookies)
                page.goto(url)
                page.wait_for_load_state("networkidle", timeout=helper_timeout * 1000)
            return callback(page)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hdhive-browser")
        future = executor.submit(
            lambda: PlaywrightHelper().action(
                url,
                callback=_callback_with_context_cookies,
                timeout=helper_timeout,
            )
        )
        try:
            return future.result(timeout=helper_timeout + 30)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise RuntimeError(f"影巢网页操作超时（{helper_timeout} 秒）") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def search(self, media_type: Any, tmdb_id: Any) -> List[Dict[str, Any]]:
        """打开影巢详情页抓资源卡片。失败返回 []。"""
        url = self._detail_url(media_type, tmdb_id)

        def _callback(page: Any) -> List[Dict[str, Any]]:
            cards: List[Dict[str, Any]] = []
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    if "/login" in (page.url or ""):
                        return self._cookie_expired_result()
                    cards = page.evaluate(_SCRAPE_CARDS_JS) or []
                except RuntimeError:
                    raise
                except Exception:
                    cards = []
                if cards:
                    break
                page.wait_for_timeout(500)
            return cards

        try:
            cards = self._run_browser_action(url, _callback)
        except Exception as exc:
            logger.warning(f"[HDHiveBrowser] 搜索失败({url}): {exc}")
            return []
        if self._is_cookie_expired_result(cards):
            raise RuntimeError("cookie 失效，被重定向到登录页")
        return [self._normalize(c) for c in (cards or []) if c.get("href")]

    def unlock(self, slug: str) -> Dict[str, Any]:
        """解锁资源，返回 {'url','already_owned'}。失败抛 RuntimeError。"""
        if not slug:
            raise RuntimeError("缺少资源 slug")
        url = f"{self.base_url}/resource/115/{slug}"

        def _callback(page: Any) -> Dict[str, Any]:
            captured: Dict[str, Optional[str]] = {"url": None}

            def _on_response(response: Any) -> None:
                try:
                    if response.status != 200:
                        return
                    if "json" not in response.headers.get("content-type", ""):
                        return
                    body = response.json()
                    if not isinstance(body, dict):
                        return
                    data = body.get("data") or {}
                    if not isinstance(data, dict):
                        return
                    for key in ("full_url", "url", "link", "resource_url"):
                        val = data.get(key)
                        if val and re.search(r"(115cdn|115)\.com", str(val)):
                            captured["url"] = str(val).strip()
                            break
                except Exception:
                    pass

            page.on("response", _on_response)

            if "/login" in (page.url or ""):
                return self._cookie_expired_result()

            confirm = page.get_by_text("确定解锁", exact=True)
            existing: Optional[str] = None
            has_confirm = False
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    existing = page.evaluate(_EXTRACT_115_URL_JS)
                except Exception:
                    existing = None
                if existing:
                    break
                try:
                    if confirm.first.is_visible():
                        has_confirm = True
                        break
                except Exception:
                    pass
                page.wait_for_timeout(500)

            if existing:
                return {"url": existing, "already_owned": True}
            if not has_confirm:
                raise RuntimeError(f"未找到「确定解锁」按钮或链接（URL: {page.url}）")

            confirm.first.click()
            deadline = time.time() + 20
            while time.time() < deadline:
                if captured["url"]:
                    return {"url": captured["url"], "already_owned": False}
                if re.search(r"(115cdn|115)\.com", page.url or ""):
                    return {"url": page.url, "already_owned": False}
                try:
                    extracted = page.evaluate(_EXTRACT_115_URL_JS)
                except Exception:
                    extracted = None
                if extracted:
                    return {"url": extracted, "already_owned": False}
                page.wait_for_timeout(500)
            raise RuntimeError(f"解锁后未获取 115 链接（URL: {page.url}）")

        result = self._run_browser_action(url, _callback)
        if self._is_cookie_expired_result(result):
            raise RuntimeError("cookie 失效，被重定向到登录页")
        return result

    # ----- 与 HDHiveOpenApiService 对齐的兼容接口（返回 (ok, result, message) 三元组) -----

    @staticmethod
    def _norm_media_type(media_type: Any) -> str:
        mt = str(media_type or "").strip().lower()
        if mt in ("movie", "电影"):
            return "movie"
        if mt in ("tv", "电视剧"):
            return "tv"
        return mt

    def search_resources(self, media_type: Any, tmdb_id: Any) -> tuple:
        """与 HDHiveOpenApiService.search_resources 同签名/同返回结构（网页方式）。"""
        mt = self._norm_media_type(media_type)
        tid = str(tmdb_id or "").strip()
        query = {"media_type": mt, "tmdb_id": tid}
        if mt not in ("movie", "tv"):
            return False, {"ok": False, "message": "媒体类型必须是 movie 或 tv", "query": query, "data": []}, "媒体类型必须是 movie 或 tv"
        if not tid:
            return False, {"ok": False, "message": "TMDB ID 不能为空", "query": query, "data": []}, "TMDB ID 不能为空"
        if not self.is_ready() and not self._refresh_cookie():
            return False, {"ok": False, "message": "影巢网页 Cookie 未配置", "query": query, "data": []}, "影巢网页 Cookie 未配置"
        try:
            items = self.search(mt, tid)
        except Exception as exc:
            message = str(exc)
            if "cookie 失效" in message and self._refresh_cookie():
                try:
                    items = self.search(mt, tid)
                except Exception as retry_exc:
                    message = str(retry_exc)
                    return False, {"ok": False, "message": message, "query": query, "data": []}, f"影巢网页搜索失败: {message}"
            else:
                return False, {"ok": False, "message": message, "query": query, "data": []}, f"影巢网页搜索失败: {message}"
        data = [
            {
                "slug": it.get("slug", ""),
                "title": it.get("title", ""),
                "name": it.get("title", ""),
                "unlock_points": it.get("unlock_points"),
                "size": it.get("size", ""),
                "resolution": it.get("resolution", ""),
                "is_free": it.get("is_free", False),
                "user": it.get("user", ""),
                "posted_at": it.get("posted_at", ""),
                "tags": it.get("tags", []),
                "source": "hdhive_browser",
            }
            for it in items
        ]
        msg = "success" if data else "影巢网页方式未找到资源"
        result = {
            "ok": bool(data),
            "message": msg,
            "query": query,
            "data": data,
            "meta": {"total": len(data)},
            "source": "hdhive_browser",
        }
        return bool(data), result, msg

    def unlock_resource(self, slug: str) -> tuple:
        """与 HDHiveOpenApiService.unlock_resource 同签名/同返回结构（网页方式）。"""
        slug = (slug or "").strip()
        if not slug:
            return False, {"ok": False, "message": "slug 不能为空", "slug": "", "data": {}}, "slug 不能为空"
        if not self.is_ready() and not self._refresh_cookie():
            return False, {"ok": False, "message": "影巢网页 Cookie 未配置", "slug": slug, "data": {}}, "影巢网页 Cookie 未配置"
        try:
            res = self.unlock(slug)
        except Exception as exc:
            message = str(exc)
            if "cookie 失效" in message and self._refresh_cookie():
                try:
                    res = self.unlock(slug)
                except Exception as retry_exc:
                    message = str(retry_exc)
                    return False, {"ok": False, "message": message, "slug": slug, "data": {}}, f"影巢网页解锁失败: {message}"
            else:
                return False, {"ok": False, "message": message, "slug": slug, "data": {}}, f"影巢网页解锁失败: {message}"
        link = (res.get("url") or "").strip()
        data = {"full_url": link, "url": link, "pan_type": "115"}
        msg = "success" if link else "影巢网页方式解锁失败"
        return bool(link), {"ok": bool(link), "message": msg, "slug": slug, "data": data, "source": "hdhive_browser"}, msg
