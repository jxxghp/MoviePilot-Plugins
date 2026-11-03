"""黑名单只匹配明确可得的资源事实。"""

from importlib import import_module
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


def rules():
    return import_module("app.plugins.torrentblacklist.rules")


@pytest.mark.parametrize("text", ["CAFE\u0301", "café", "CAFÉ"])
def test_keyword_normalizes_unicode_and_case(text):
    module = rules()
    rule = module.create_rule(module.KeywordInput(keyword=" Café "))
    assert rule.keyword == "café"
    assert module.matches(rule, SimpleNamespace(title=text))
    assert module.matches(rule, SimpleNamespace(description=f"简介 {text}"))
    assert not module.matches(rule, SimpleNamespace(title="咖啡"))


def test_literal_keyword_and_optional_site_scope():
    module = rules()
    rule = module.create_rule(module.KeywordInput(keyword="[CAM].*", site_id=7))
    assert module.matches(rule, SimpleNamespace(title="test [cam].*", site=7))
    for candidate in (
        SimpleNamespace(title="test CAM", site=7),
        SimpleNamespace(title="[CAM].*", site=8),
        SimpleNamespace(title="[CAM].*"),
    ):
        assert not module.matches(rule, candidate)


def test_site_matches_only_real_numeric_id():
    module = rules()
    rule = module.create_rule(module.SiteInput(site_id=7))
    assert module.matches(rule, SimpleNamespace(site=7))
    for value in (None, "7", True, 8):
        assert not module.matches(rule, SimpleNamespace(site=value, site_name="7"))


def test_history_rule_is_exact_same_site_and_full_title():
    module = rules()
    rule = module.history_rule(" 测试站 ", " Café.2026.1080p ")
    assert module.matches(rule, SimpleNamespace(site_name="测试站", title="Cafe\u0301.2026.1080p"))
    for site, title in (
        ("别的站", "Café.2026.1080p"),
        ("测试站", "café.2026.1080p"),
        ("测试站", "Café.2026.1080p.EXTRA"),
        ("测试站", "Café.2026.2160p"),
        ("", "Café.2026.1080p"),
    ):
        assert not module.matches(rule, SimpleNamespace(site_name=site, title=title))


def test_ids_are_stable_for_equivalent_rules_but_distinct_for_scope():
    module = rules()
    first = module.create_rule(module.KeywordInput(keyword=" Café "))
    same = module.create_rule(module.KeywordInput(keyword="CAFE\u0301"))
    other = module.create_rule(module.KeywordInput(keyword="café", site_id=1))
    assert first == same
    assert first.id != other.id
    assert len(first.id) == 64
    assert module.history_rule("站", "Film").id != module.history_rule("站", "film").id


@pytest.mark.parametrize("kwargs", [
    {"keyword": ""}, {"keyword": " \n "}, {"keyword": "a" * 257},
    {"keyword": "CAM", "site_id": 0}, {"keyword": "CAM", "site_id": True},
    {"keyword": "CAM", "site_id": "7"}, {"keyword": "CAM", "publisher": "x"},
])
def test_invalid_keyword_input_is_rejected(kwargs):
    with pytest.raises(ValidationError):
        rules().KeywordInput(**kwargs)


@pytest.mark.parametrize("site_id", [0, -1, True, "7", 1.5])
def test_invalid_site_input_is_rejected(site_id):
    with pytest.raises(ValidationError):
        rules().SiteInput(site_id=site_id)


@pytest.mark.parametrize("site,title", [("", "Film"), ("站", ""), ("站", "a" * 2049)])
def test_history_missing_or_oversized_facts_are_rejected(site, title):
    with pytest.raises(ValidationError):
        rules().history_rule(site, title)


def test_rules_are_immutable_and_persisted_identity_is_validated():
    module = rules()
    rule = module.create_rule(module.SiteInput(site_id=1))
    with pytest.raises(ValidationError):
        rule.site_id = 2
    bad = rule.model_dump()
    bad["id"] = "0" * 64
    with pytest.raises(ValidationError):
        module.Rule.model_validate(bad)
    with pytest.raises(ValidationError):
        module.Rule.model_validate({**rule.model_dump(), "keyword": "unexpected"})
