"""作品目录复用整理模板，但只允许与资源版本无关的媒体事实。"""

import pytest
from app.plugins.mediadownloadfolder.naming import render_media_folder


@pytest.mark.parametrize("template", [
    "{{title}} ({{year}})/{{title}}-{{videoFormat}}{{fileExt}}",
    "{{title}} ({{year}})/Season {{season}}/{{title}} {{season_episode}}{{fileExt}}",
])
def test_versions_and_seasons_share_one_work_folder(template):
    """种子版本、季集变化不能改变作品目录。"""
    for version, season in [("1080p", 1), ("2160p", 2)]:
        assert render_media_folder(template, {
            "title": "示例", "year": "2026", "videoFormat": version, "season": season,
        }) == "示例 (2026)"


def test_last_title_directory_matches_library_work_level():
    """忽略作品目录前的分类前缀和之后的季目录。"""
    template = "{{year}}/{{title}}/{{en_title}} {tmdb-{{tmdbid}}}/Season {{season}}/file.mkv"
    assert render_media_folder(template, {
        "title": "示例", "en_title": "Example", "year": "2026", "tmdbid": 123,
    }) == "Example {tmdb-123}"


@pytest.mark.parametrize("template", [
    "{{title}}{{imdbid}}/file.mkv",
    "{{title}}{% if year %} ({{year}}){% endif %}/file.mkv",
    "{{title}}{% if year is defined %} ({{year}}){% endif %}/file.mkv",
    "{{title}}{{year | default('')}}/file.mkv",
])
def test_missing_optional_facts_keep_jinja_undefined_semantics(template):
    """缺失年份和 ID 不是字符串 None，条件与 default 仍然有效。"""
    assert render_media_folder(template, {"title": "示例", "year": None}) == "示例"


@pytest.mark.parametrize("template", [
    "{{title}}-{{videoFormat}}/file.mkv",
    "{{title}}-{{season}}/file.mkv",
    "{{title}}-{{season_year}}/file.mkv",
    "{{title}}-{{instance_name}}/file.mkv",
    "{{title}}-{{cycler('a', 'b').next()}}/file.mkv",
    "{{title.__class__}}/file.mkv",
    "{{title[0]}}/file.mkv",
    "{{title}}-{{1 % 0}}/file.mkv",
    "{% if year %}prefix/{{title}}{% endif %}/file.mkv",
    "{{title | replace('/', '-')}}/file.mkv",
    "{{title}}{{fileExt}}",
    "constant/file.mkv",
    "{{title}}{% if missing %}/file.mkv",
])
def test_ambiguous_or_resource_dependent_templates_are_rejected(template):
    """不能可靠定位、隔离和渲染作品目录时明确拒绝。"""
    with pytest.raises(ValueError, match="作品目录"):
        render_media_folder(template, {"title": "示例", "year": "2026"})


@pytest.mark.parametrize("value", [
    "", " ", ".", "..", "/a", r"a\b", "C:evil", "a\nb", "a\x00b", "a" * 256, "影" * 86,
])
def test_rendered_folder_is_one_bounded_component(value):
    """渲染结果不得逃逸根目录或被静默截断。"""
    with pytest.raises(ValueError, match="作品目录"):
        render_media_folder("{{title}}/file.mkv", {"title": value})


def test_valid_internal_spaces_are_preserved():
    """不把正常片名中的多个空格折叠为不同名称。"""
    assert render_media_folder("{{title}}/file.mkv", {"title": "示例  电影"}) == "示例  电影"


@pytest.mark.parametrize("expression", [
    "title | attr('__class__')",
    "title | random",
    "title | map(attribute='__class__')",
    "title | selectattr('__class__')",
    "title | rejectattr('__class__')",
    "title | groupby('__class__')",
    "title | sort(attribute='__class__')",
    "title | unique(attribute='__class__')",
    "title | join(attribute='__class__')",
])
def test_filters_cannot_access_objects_or_make_folder_nondeterministic(expression):
    """属性型、集合型和随机过滤器在渲染之前明确拒绝。"""
    with pytest.raises(ValueError, match="作品目录.*过滤器"):
        render_media_folder("{{" + expression + "}}/file.mkv", {"title": "ABCDEFGHIJ"})


def test_filter_block_obeys_same_deterministic_boundary():
    """过滤块不能绕过普通表达式的过滤器约束。"""
    with pytest.raises(ValueError, match="作品目录.*过滤器"):
        render_media_folder("{% filter random %}{{title}}{% endfilter %}/file.mkv", {"title": "ABCDEFGHIJ"})


@pytest.mark.parametrize("expression,expected", [
    ("title | lower | replace(' ', '-')", "example-title"),
    ("title | upper", "EXAMPLE TITLE"),
    ("title | capitalize", "Example title"),
    ("title | trim", "Example Title"),
    ("title | string", "Example Title"),
    ("title ~ (tmdbid | int)", "Example Title123"),
    ("title ~ (tmdbid | float)", "Example Title123.0"),
    ("title ~ (year | default(''))", "Example Title"),
    ("title ~ (year | d(''))", "Example Title"),
])
def test_supported_scalar_filters_keep_same_work_folder_stable(expression, expected):
    """常见确定性字符串和数值转换重复执行仍得到同一目录。"""
    template = "{{" + expression + "}}/file.mkv"
    results = {
        render_media_folder(template, {"title": "Example Title", "tmdbid": "123"})
        for _ in range(5)
    }
    assert results == {expected}


@pytest.mark.parametrize("condition", [
    "title is defined", "year is undefined", "none is none",
    "true is boolean", "false is false", "true is true",
    "tmdbid is integer", "1.5 is float", "tmdbid is number", "title is string",
    "'example' is lower", "'EXAMPLE' is upper", "tmdbid is odd", "124 is even",
    "tmdbid is divisibleby(3)", "tmdbid is eq(123)", "tmdbid is equalto(123)",
    "tmdbid is ne(124)", "tmdbid is gt(122)", "tmdbid is greaterthan(122)",
    "tmdbid is ge(123)", "tmdbid is lt(124)", "tmdbid is lessthan(124)",
    "tmdbid is le(123)", "tmdbid is in([123, 456])",
])
def test_scalar_value_tests_remain_supported(condition):
    """限定测试名称后，常见缺省、类型、数值和字符串条件仍按值判断。"""
    template = "{{title}}{% if " + condition + " %} A{% else %} B{% endif %}/file.mkv"
    assert render_media_folder(template, {"title": "Example", "tmdbid": 123}) == "Example A"
