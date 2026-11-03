"""从现有整理格式中安全选取只依赖作品信息的目录。"""

import re
from collections.abc import Mapping

from jinja2 import Environment, TemplateError, nodes

TITLE_FIELDS = frozenset({"title", "en_title", "original_title", "title_year"})
MEDIA_FIELDS = TITLE_FIELDS | {
    "year", "tmdbid", "imdbid", "doubanid", "bangumiid", "anilistid",
}
SCALAR_FILTERS = frozenset({
    "abs", "capitalize", "count", "d", "default", "float", "format", "int",
    "length", "lower", "replace", "round", "string", "title", "trim", "upper",
})
SCALAR_TESTS = frozenset({
    "boolean", "defined", "divisibleby", "eq", "equalto", "even", "false", "float",
    "ge", "greaterthan", "gt", "in", "integer", "le", "lessthan", "lower", "lt",
    "ne", "none", "number", "odd", "string", "true", "undefined", "upper",
})
MAX_COMPONENT_BYTES = 255


def _template_parts(template: str, environment: Environment) -> list[str]:
    """只在普通文本中的斜杠处分段，拒绝表达式斜杠与跨目录控制块。"""
    parts = [""]
    for _, kind, value in environment.lex(template):
        if kind == "data":
            fragments = value.split("/")
            parts[-1] += fragments[0]
            parts.extend(fragments[1:])
        else:
            if "/" in value:
                raise ValueError("作品目录不支持表达式内的斜杠")
            parts[-1] += value
    # 单独解析每段，使跨目录 if/for 等模板不能被截成另一种含义。
    for part in parts:
        environment.parse(part)
    return parts


def validate_component(value: str) -> str:
    """校验单层目录名称，不截断或改变合法空格。"""
    if (
        not value.strip()
        or value in {".", ".."}
        or any(character in value for character in "/\\")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or re.match(r"^[A-Za-z]:", value)
        or len(value.encode("utf-8")) > MAX_COMPONENT_BYTES
    ):
        raise ValueError("作品目录名称必须是有效的单层目录，且不超过 255 字节")
    return value


def validate_media_template(template: str) -> str:
    """验证模板结构并返回作品目录段；不使用虚构媒体事实执行渲染。"""
    if not isinstance(template, str) or not template or len(template) > 16384:
        raise ValueError("作品目录的整理格式为空或过长")
    environment = Environment()
    try:
        parts = _template_parts(template, environment)
        candidates = []
        for part in parts[:-1]:
            parsed = environment.parse(part)
            names = {node.name for node in parsed.find_all(nodes.Name)}
            if names & TITLE_FIELDS:
                candidates.append((part, parsed, names))
        if not candidates:
            raise ValueError("整理格式没有可用的作品目录，请在文件名之前配置标题目录")
        part, parsed, names = candidates[-1]
        if names - MEDIA_FIELDS:
            raise ValueError("作品目录只能引用标题、年份和媒体来源 ID，不能引用季集或资源版本")
        forbidden = (
            nodes.Call, nodes.Getattr, nodes.Getitem, nodes.For, nodes.Assign,
            nodes.Import, nodes.FromImport, nodes.Include, nodes.Extends, nodes.Macro,
        )
        if any(isinstance(node, forbidden) for node in parsed.find_all(nodes.Node)):
            raise ValueError("作品目录不支持对象访问、函数调用或循环")
        if any(node.name not in SCALAR_FILTERS for node in parsed.find_all(nodes.Filter)):
            raise ValueError("作品目录只支持确定性的标量和字符串过滤器")
        if any(node.name not in SCALAR_TESTS for node in parsed.find_all(nodes.Test)):
            raise ValueError("作品目录只支持确定性的值判断，不支持 sameas 等对象身份测试")
        # 编译检查过滤器、测试和模板语法，不传入或伪造任何媒体值。
        environment.from_string(part)
        return part
    except TemplateError as error:
        raise ValueError("作品目录的整理格式结构无效") from error


def render_media_folder(template: str, context: Mapping[str, object]) -> str:
    """用宿主真实命名事实渲染已验证目录段，最后检查单层路径和长度。"""
    part = validate_media_template(template)
    try:
        values = {
            key: value for key, value in context.items()
            if key in MEDIA_FIELDS and isinstance(value, (str, int, float)) and value is not None
        }
        return validate_component(Environment().from_string(part).render(values))
    except (TemplateError, ArithmeticError, TypeError, UnicodeError) as error:
        raise ValueError("作品目录的整理格式无法安全渲染") from error
