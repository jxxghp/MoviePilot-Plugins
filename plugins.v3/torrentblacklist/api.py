"""管理员接口；历史规则的事实只从服务端读取。"""

from typing import Annotated

from fastapi import Body, Depends, HTTPException, Path, Query
from pydantic import ValidationError

from app import schemas
from app.db.oper.downloadhistory import DownloadHistoryOper
from app.db.oper.site import SiteOper
from app.db.oper.user import UserOper
from app.schemas.query import DownloadHistoryFilter, QueryPageRequest
from app.sdk.security import verify_token

from .rules import FrozenModel, Rule, RuleId, RuleInput, create_rule, history_rule
from .store import MAX_RULES, RuleCapacityError, RuleStorageError, RuleStore

PageNumber = Annotated[int, Query(ge=1, le=2147483647)]
PageSize = Annotated[int, Query(ge=1, le=100)]


async def require_admin(token: Annotated[schemas.TokenPayload, Depends(verify_token)]) -> None:
    """不信任令牌里的 super_user，读取当前启用状态和管理员身份。"""
    if token.sub is None or token.sub <= 0:
        raise HTTPException(401, "请重新登录")
    user = await UserOper().async_get_by_id(token.sub)
    if user is None or not user.is_active:
        raise HTTPException(401, "请重新登录")
    if not user.is_superuser:
        raise HTTPException(403, "仅管理员可管理种子黑名单")


class RulePage(FrozenModel):
    rules: tuple[Rule, ...]
    total: int
    revision: int
    capacity: int = MAX_RULES


class AddedRule(FrozenModel):
    rule: Rule
    created: bool
    revision: int


class DeletedRule(FrozenModel):
    deleted: bool
    revision: int


class HistoryItem(FrozenModel):
    id: int
    title: str | None
    torrent_name: str | None
    torrent_site: str | None
    date: str | None
    can_block: bool
    blocked: bool
    unavailable_reason: str | None


class HistoryPage(FrozenModel):
    items: tuple[HistoryItem, ...]
    total: int


class SiteItem(FrozenModel):
    id: int
    name: str


class Sites(FrozenModel):
    sites: tuple[SiteItem, ...]


class EmptyBody(FrozenModel):
    """允许无正文或空对象；拒绝客户端伪造历史事实。"""


class BlacklistApi:
    def __init__(self, store: RuleStore):
        self.store = store

    def routes(self) -> list[dict]:
        endpoints = (
            ("/rules", ["GET"], self.list_rules, RulePage),
            ("/rules", ["POST"], self.add_rule, AddedRule),
            ("/rules/{rule_id}", ["DELETE"], self.delete_rule, DeletedRule),
            ("/history", ["GET"], self.list_history, HistoryPage),
            ("/history/{history_id}/block", ["POST"], self.block_history, AddedRule),
            ("/sites", ["GET"], self.list_sites, Sites),
        )
        return [{"path": path, "methods": methods, "endpoint": endpoint,
                 "auth": "bear", "dependencies": [Depends(require_admin)],
                 "response_model": schemas.Response[model]}
                for path, methods, endpoint, model in endpoints]

    def _read(self):
        try:
            return self.store.read()
        except RuleStorageError as exc:
            raise HTTPException(503, str(exc)) from exc

    def _add(self, rule: Rule) -> schemas.Response[AddedRule]:
        try:
            saved, created, revision = self.store.add(rule)
        except RuleStorageError as exc:
            raise HTTPException(503, str(exc)) from exc
        except RuleCapacityError as exc:
            raise HTTPException(409, str(exc)) from exc
        return schemas.Response(success=True, data=AddedRule(rule=saved, created=created, revision=revision))

    def list_rules(self, page: PageNumber = 1, page_size: PageSize = 20) -> schemas.Response[RulePage]:
        document = self._read()
        start = (page - 1) * page_size
        return schemas.Response(success=True, data=RulePage(
            rules=document.entries[start:start + page_size], total=len(document.entries),
            revision=document.revision,
        ))

    def add_rule(self, payload: RuleInput) -> schemas.Response[AddedRule]:
        return self._add(create_rule(payload))

    def delete_rule(self, rule_id: RuleId) -> schemas.Response[DeletedRule]:
        try:
            deleted, revision = self.store.delete(rule_id)
        except RuleStorageError as exc:
            raise HTTPException(503, str(exc)) from exc
        return schemas.Response(success=True, data=DeletedRule(deleted=deleted, revision=revision))

    def list_history(self, page: PageNumber = 1, page_size: PageSize = 20,
                     search: Annotated[str, Query(max_length=256)] = "") -> schemas.Response[HistoryPage]:
        document = self._read()
        blocked = {rule.id for rule in document.entries}
        records, total = DownloadHistoryOper().query(
            DownloadHistoryFilter(text=search or None), QueryPageRequest(page=page, count=page_size),
        )
        items = []
        for record in records:
            try:
                rule = history_rule(record.torrent_site, record.torrent_name)
            except ValidationError:
                rule = None
            items.append(HistoryItem(
                id=record.id, title=record.title, torrent_name=record.torrent_name,
                torrent_site=record.torrent_site, date=record.date,
                can_block=rule is not None, blocked=rule is not None and rule.id in blocked,
                unavailable_reason=None if rule else "站点名称或种子完整标题缺失或超长，无法添加",
            ))
        return schemas.Response(success=True, data=HistoryPage(items=tuple(items), total=total))

    def block_history(self, history_id: Annotated[int, Path(gt=0, le=2147483647)],
                      payload: Annotated[EmptyBody | None, Body()] = None) -> schemas.Response[AddedRule]:
        record = DownloadHistoryOper().get_by_id(history_id)
        if record is None:
            raise HTTPException(404, "下载历史不存在")
        try:
            rule = history_rule(record.torrent_site, record.torrent_name)
        except ValidationError as exc:
            raise HTTPException(409, "站点名称或种子完整标题缺失或超长，无法添加") from exc
        return self._add(rule)

    def list_sites(self) -> schemas.Response[Sites]:
        return schemas.Response(success=True, data=Sites(sites=tuple(
            SiteItem(id=site.id, name=site.name) for site in SiteOper().list()
        )))
