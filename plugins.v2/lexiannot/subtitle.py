from typing import Generator, Any, overload

from pysubs2 import SSAEvent

from .schemas import SubtitleSegment


class SubtitleProcessor:
    def __init__(self):
        self._events: list[SSAEvent] = []

    def append(self, event: SSAEvent):
        self._events.append(event)

    def segment_generator(self) -> Generator[SubtitleSegment, None, None]:
        for index, event in enumerate(self._events):
            yield SubtitleSegment(
                index=index,
                start_time=event.start,
                end_time=event.end,
                plaintext=event.plaintext,
            )

    @overload
    def __getitem__(self, item: int) -> SSAEvent:
        pass

    @overload
    def __getitem__(self, s: slice) -> list[SSAEvent]:
        pass

    def __getitem__(self, item: Any) -> Any:
        return self._events[item]


def style_text(style: str, text: str) -> str:
    """
    使用指定的样式包装文本。

    :param style: 样式名称
    :param text: 要包装的文本
    :return: 包含样式的文本
    """
    return f"{{\\r{style}}}{text}{{\\r}}"
