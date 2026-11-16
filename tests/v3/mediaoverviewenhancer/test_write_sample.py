"""样张直写的降级路径测试（不依赖媒体服务器连接）。"""

from __future__ import annotations

from typing import Any, Dict

from app.plugins.mediaoverviewenhancer.enhancer import OverviewEnhancer


class FakeWriteClient:
    """只实现样张写入所需方法的假客户端。"""

    name = "fake"

    def __init__(self) -> None:
        """记录最后一次写入内容。"""
        self.written = None

    def get_full_dto(self, item_id: str) -> Dict[str, Any]:
        """返回一个最小可用的完整 DTO。"""
        return {"Id": item_id, "Overview": "旧简介", "LockedFields": [], "ProviderIds": {}}

    def update_overview(
        self,
        item_id: str,
        overview: str,
        lock: bool = True,
        **kwargs: Any,
    ):
        """记录写入并返回成功。"""
        self.written = (item_id, overview)
        return True, ""


def test_write_sample_uses_payload_when_scan_misses(tmp_path) -> None:
    """扫描找不到条目时，用前端回传的定位信息直接写入该条。"""
    engine = OverviewEnhancer(config={}, data_dir=tmp_path)
    client = FakeWriteClient()
    engine._collect_jobs = lambda **kwargs: ([], [], {})
    engine._client_by_name = lambda name: client
    result = engine.write_sample(
        {
            "key": "fake|42",
            "kind": "episode",
            "title": "嫁金钗",
            "season": 1,
            "episode": 3,
            "text": "该集围绕一封来历不明的信件展开，调查因此转向城南的旧仓库。",
        }
    )
    assert result["written"] is True
    assert client.written and client.written[0] == "42"
    assert "fake|42" in engine._state.get("records", {})
    engine.stop()


def test_write_sample_rejects_without_text(tmp_path) -> None:
    """缺少文案时直接拒绝，不触碰媒体服务器。"""
    engine = OverviewEnhancer(config={}, data_dir=tmp_path)
    assert engine.write_sample({"key": "fake|42"})["written"] is False
    engine.stop()
