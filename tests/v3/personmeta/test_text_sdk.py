from types import SimpleNamespace

from app.plugins import personmeta
from app.sdk.utilities import convert


def test_person_name_conversion_uses_host_sdk() -> None:
    """人物别名转换应复用宿主 SDK，并保持原有简体结果。"""
    person = SimpleNamespace(also_known_as=["周潤發"])

    assert personmeta.convert is convert
    assert personmeta.PersonMeta._PersonMeta__get_chinese_name(person) == "周润发"
