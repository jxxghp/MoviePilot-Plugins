"""规则的原子发布、持久化失败和实例锁。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace

import pytest


class MemoryData:
    def __init__(self):
        self.values = {}
        self.fail_read = False
        self.fail_write = False
        self.writes = 0
        self.before_write = None

    def get_data(self):
        if self.fail_read:
            raise OSError("private database path")
        return [SimpleNamespace(key=key, value=deepcopy(value)) for key, value in self.values.items()]

    def save_data(self, key, value):
        if self.before_write:
            self.before_write()
        if self.fail_write:
            raise OSError("private database path")
        self.values[key] = deepcopy(value)
        self.writes += 1


def setup_store():
    module = import_module("app.plugins.torrentblacklist.store")
    rules = import_module("app.plugins.torrentblacklist.rules")
    data = MemoryData()
    store = module.RuleStore(data)
    return module, rules, data, store


def test_absent_rules_are_empty_without_writing_defaults():
    _, _, data, store = setup_store()
    store.reload()
    document, error = store.snapshot()
    assert document.entries == ()
    assert document.revision == 0 and error is None
    assert data.values == {} and data.writes == 0


def test_duplicate_add_and_missing_delete_are_idempotent():
    _, rules, data, store = setup_store()
    rule = rules.create_rule(rules.KeywordInput(keyword="CAM"))
    actual, created, revision = store.add(rule)
    assert (actual, created, revision) == (rule, True, 1)
    assert store.add(rules.create_rule(rules.KeywordInput(keyword="cam"))) == (rule, False, 1)
    assert store.delete("0" * 64) == (False, 1)
    assert data.writes == 1
    assert store.delete(rule.id) == (True, 2)
    assert store.delete(rule.id) == (False, 2)
    assert data.writes == 2


def test_concurrent_additions_read_latest_under_one_lock():
    _, rules, data, store = setup_store()
    barrier = Barrier(12)

    def add(index):
        barrier.wait()
        return store.add(rules.create_rule(rules.SiteInput(site_id=index + 1)))

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(add, range(12)))
    assert all(created for _, created, _ in results)
    assert len(store.read().entries) == 12
    assert store.read().revision == 12
    assert len(data.values["rules"]["entries"]) == 12


def test_concurrent_duplicate_additions_and_deletions_write_once():
    _, rules, data, store = setup_store()
    rule = rules.create_rule(rules.SiteInput(site_id=1))
    with ThreadPoolExecutor(max_workers=8) as pool:
        additions = list(pool.map(lambda _: store.add(rule), range(16)))
    assert sum(created for _, created, _ in additions) == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        deletions = list(pool.map(lambda _: store.delete(rule.id), range(16)))
    assert sum(deleted for deleted, _ in deletions) == 1
    assert data.writes == 2 and store.read().revision == 2


def test_failed_save_keeps_previous_memory_and_persistent_document():
    module, rules, data, store = setup_store()
    first = rules.create_rule(rules.SiteInput(site_id=1))
    store.add(first)
    previous = store.snapshot()
    durable = deepcopy(data.values)
    data.fail_write = True
    with pytest.raises(module.RuleStorageError, match="规则保存失败"):
        store.add(rules.create_rule(rules.SiteInput(site_id=2)))
    assert store.snapshot() == previous
    assert data.values == durable
    with pytest.raises(module.RuleStorageError):
        store.delete(first.id)
    assert store.snapshot() == previous and data.values == durable


def test_snapshot_is_not_published_before_save_finishes():
    _, rules, data, store = setup_store()
    first = rules.create_rule(rules.SiteInput(site_id=1))
    store.add(first)
    observed = []
    data.before_write = lambda: observed.append(store.snapshot()[0].entries)
    second = rules.create_rule(rules.SiteInput(site_id=2))
    store.add(second)
    assert observed == [(first,)]
    assert store.snapshot()[0].entries == (first, second)


@pytest.mark.parametrize("bad", [None, [], {}, {"version": 2, "revision": 0, "entries": []},
                                {"version": 1, "revision": True, "entries": []}])
def test_corrupt_data_is_preserved_and_never_treated_as_empty(bad):
    module, rules, data, store = setup_store()
    data.values["rules"] = deepcopy(bad)
    store.reload()
    assert store.snapshot()[1] == "规则数据无法读取，请检查插件数据或停用插件"
    with pytest.raises(module.RuleStorageError):
        store.read()
    with pytest.raises(module.RuleStorageError):
        store.add(rules.create_rule(rules.SiteInput(site_id=1)))
    assert data.values["rules"] == bad and data.writes == 0


def test_read_failure_sets_visible_error_and_reload_can_recover():
    module, rules, data, store = setup_store()
    store.add(rules.create_rule(rules.SiteInput(site_id=1)))
    data.fail_read = True
    store.reload()
    assert store.snapshot()[1] and "private" not in store.snapshot()[1]
    with pytest.raises(module.RuleStorageError):
        store.delete("0" * 64)
    data.fail_read = False
    store.reload()
    assert store.snapshot()[1] is None and len(store.snapshot()[0].entries) == 1


def test_capacity_rejects_new_rule_without_eviction_but_allows_duplicate():
    module, rules, data, store = setup_store()
    entries = [rules.create_rule(rules.SiteInput(site_id=i + 1)) for i in range(1000)]
    data.values["rules"] = {"version": 1, "revision": 1000,
                            "entries": [entry.model_dump(mode="json") for entry in entries]}
    assert store.add(entries[0]) == (entries[0], False, 1000)
    with pytest.raises(module.RuleCapacityError, match="1000"):
        store.add(rules.create_rule(rules.SiteInput(site_id=1001)))
    assert data.writes == 0 and len(store.read().entries) == 1000


def test_new_store_reloads_durable_rules_and_has_independent_snapshot():
    module, rules, data, store = setup_store()
    first = rules.create_rule(rules.SiteInput(site_id=1))
    store.add(first)
    other = module.RuleStore(data)
    other.reload()
    assert other.snapshot() == store.snapshot()
    store.add(rules.create_rule(rules.SiteInput(site_id=2)))
    assert other.snapshot()[0].entries == (first,)
    other.reload()
    assert len(other.snapshot()[0].entries) == 2
