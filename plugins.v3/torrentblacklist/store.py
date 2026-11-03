"""单实例进程内串行持久化，成功保存后才发布不可变快照。"""

from threading import RLock
from typing import Any, Literal, Protocol, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from .rules import FrozenModel, Rule

MAX_RULES = 1000
READ_ERROR = "规则数据无法读取，请检查插件数据或停用插件"


class RuleStorageError(RuntimeError):
    """插件数据读取或保存失败；消息不包含底层私密路径。"""


class RuleCapacityError(ValueError):
    """达到显式容量上限，不淘汰旧规则。"""


class PluginData(Protocol):
    def get_data(self) -> list[Any]: ...

    def save_data(self, key: str, value: Any) -> None: ...


class RuleDocument(FrozenModel):
    version: Literal[1]
    revision: StrictInt = Field(ge=0)
    entries: tuple[Rule, ...] = Field(max_length=MAX_RULES)

    @field_validator("version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("无效规则版本")
        return value

    @model_validator(mode="after")
    def unique_entries(self) -> Self:
        if len({entry.id for entry in self.entries}) != len(self.entries):
            raise ValueError("规则重复")
        return self


class RuleStore:
    def __init__(self, owner: PluginData):
        self._owner = owner
        self._lock = RLock()
        self._document = RuleDocument(version=1, revision=0, entries=())
        self._error: str | None = None

    def _load(self) -> RuleDocument:
        try:
            # 不传 key 才能区分缺键和已持久化 JSON null；SDK 隔离当前实例。
            rows = self._owner.get_data()
            if not isinstance(rows, list):
                raise ValueError("无效插件数据")
            documents = [row.value for row in rows if row.key == "rules"]
            if not documents:
                return RuleDocument(version=1, revision=0, entries=())
            if len(documents) != 1:
                raise ValueError("规则文档重复")
            return RuleDocument.model_validate(documents[0])
        except Exception as error:
            self._error = READ_ERROR
            raise RuleStorageError(READ_ERROR) from error

    def _publish(self, document: RuleDocument) -> None:
        self._document = document
        self._error = None

    def _save(self, document: RuleDocument) -> None:
        try:
            # SDK 保存成功返回 None；不能把该返回值当作失败。
            self._owner.save_data("rules", document.model_dump(mode="json"))
        except Exception as error:
            raise RuleStorageError("规则保存失败，请稍后重试") from error
        self._publish(document)

    def snapshot(self) -> tuple[RuleDocument, str | None]:
        with self._lock:
            return self._document, self._error

    def read(self) -> RuleDocument:
        with self._lock:
            document = self._load()
            self._publish(document)
            return document

    def reload(self) -> None:
        try:
            self.read()
        except RuleStorageError:
            # 保留原始数据及可见错误，生命周期不覆盖为默认空规则。
            pass

    def add(self, rule: Rule) -> tuple[Rule, bool, int]:
        with self._lock:
            current = self._load()
            existing = next((entry for entry in current.entries if entry.id == rule.id), None)
            if existing is not None:
                self._publish(current)
                return existing, False, current.revision
            if len(current.entries) >= MAX_RULES:
                raise RuleCapacityError(f"规则已达到 {MAX_RULES} 条，请先删除不再需要的规则")
            document = RuleDocument(version=1, revision=current.revision + 1, entries=(*current.entries, rule))
            self._save(document)
            return rule, True, document.revision

    def delete(self, rule_id: str) -> tuple[bool, int]:
        with self._lock:
            current = self._load()
            entries = tuple(entry for entry in current.entries if entry.id != rule_id)
            if len(entries) == len(current.entries):
                self._publish(current)
                return False, current.revision
            document = RuleDocument(version=1, revision=current.revision + 1, entries=entries)
            self._save(document)
            return True, document.revision
