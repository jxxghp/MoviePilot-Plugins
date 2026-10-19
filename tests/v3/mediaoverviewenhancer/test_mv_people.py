"""MediaOverviewEnhancer 的 MV 演员、成员与 NFO 输出单测。

覆盖：成员数据源合并与名字模式、People 写入去重与 Cast 锁定、按角色清理历史成员、
NFO 生成与路径映射、演员头像写入调用、成员相关配置规整。
外部数据源与 LLM 均以替身注入，测试期间不发起真实网络请求。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from app.plugins.mediaoverviewenhancer.enhancer import (
    MV,
    EmbyClient,
    OverviewEnhancer,
    normalize_config,
)


class FakeResponse:
    """模拟 Emby 写入响应。"""

    status_code = 200
    text = ""


def make_engine(tmp_path: Path, **overrides) -> OverviewEnhancer:
    """构造使用临时目录的引擎，并把外部依赖替换为替身。"""
    config = {
        "enabled": True,
        "mv_write_people": True,
        "mv_member_enabled": True,
        "mv_member_source": "both",
        "mv_member_name_mode": "zh",
        "mv_member_role": "成员",
    }
    config.update(overrides)
    engine = OverviewEnhancer(config=config, data_dir=tmp_path)
    engine._mb = Mock()
    engine._mb.members = Mock(return_value=[])
    engine._wd = Mock()
    engine._wd.members = Mock(return_value=[])
    engine._llm = Mock()
    engine._llm.translate_names = Mock(side_effect=lambda names: list(names))
    return engine


def make_client() -> EmbyClient:
    """构造不接触真实服务器的 Emby 客户端。"""
    client = EmbyClient("emby", "http://emby.invalid", "test-key")
    client._request = Mock()
    return client


class TestMemberEntries:
    """成员数据源合并与名字模式。"""

    def test_sources_merge_and_fill_chinese(self, tmp_path):
        """MusicBrainz 与 Wikidata 取并集，中文名互补，缺失项用 AI 翻译补齐。"""
        engine = make_engine(tmp_path)
        engine._mb.members = Mock(return_value=["CL", "Park Bom", "Minzy"])
        engine._wd.members = Mock(
            return_value=[
                {"original": "CL", "zh": "李彩琳"},
                {"original": "Park Bom", "zh": "朴春"},
                {"original": "Sandara Park", "zh": "朴山多拉"},
            ]
        )
        engine._llm.translate_names = Mock(return_value=["孔敏智"])
        entries = engine._fetch_member_entries("2NE1")
        assert [item["original"] for item in entries] == [
            "CL",
            "Park Bom",
            "Minzy",
            "Sandara Park",
        ]
        assert [item["zh"] for item in entries] == ["李彩琳", "朴春", "孔敏智", "朴山多拉"]
        engine._llm.translate_names.assert_called_once_with(["Minzy"])

    def test_name_modes(self, tmp_path):
        """成员名显示模式：中文 / 原名 / 中文+原名。"""
        engine = make_engine(tmp_path)
        entries = [{"original": "CL", "zh": "李彩琳"}, {"original": "Minzy", "zh": ""}]
        engine._config["mv_member_name_mode"] = "zh"
        assert engine._member_display_names(entries) == ["李彩琳", "Minzy"]
        engine._config["mv_member_name_mode"] = "original"
        assert engine._member_display_names(entries) == ["CL", "Minzy"]
        engine._config["mv_member_name_mode"] = "both"
        assert engine._member_display_names(entries) == ["李彩琳 (CL)", "Minzy"]

    def test_wikidata_only_skips_musicbrainz(self, tmp_path):
        """只选 Wikidata 时不请求 MusicBrainz。"""
        engine = make_engine(tmp_path, mv_member_source="wikidata")
        engine._wd.members = Mock(return_value=[{"original": "CL", "zh": "李彩琳"}])
        entries = engine._fetch_member_entries("2NE1")
        assert entries == [{"original": "CL", "zh": "李彩琳"}]
        engine._mb.members.assert_not_called()

    def test_original_mode_skips_translation(self, tmp_path):
        """名字模式为原名时不调用 AI 翻译。"""
        engine = make_engine(tmp_path, mv_member_name_mode="original")
        engine._mb.members = Mock(return_value=["CL"])
        assert [item["original"] for item in engine._fetch_member_entries("2NE1")] == ["CL"]
        engine._llm.translate_names.assert_not_called()

    def test_config_normalization(self):
        """成员与 NFO 相关配置的默认值与非法值回退。"""
        default = normalize_config(None)
        assert default["mv_member_enabled"] is True
        assert default["mv_member_name_mode"] == "zh"
        assert default["mv_member_source"] == "both"
        assert default["mv_write_nfo"] is True
        assert default["mv_people_avatar"] is True
        assert normalize_config({"mv_member_name_mode": "x"})["mv_member_name_mode"] == "zh"
        assert normalize_config({"mv_member_source": "x"})["mv_member_source"] == "both"
        assert len(normalize_config({"mv_member_role": "y" * 50})["mv_member_role"]) == 20


class TestPeopleWrite:
    """People 写入：合并去重、Cast 锁定与按角色清理。"""

    def _prepare(self, base: dict) -> tuple:
        """准备可写入的客户端与负载记录。"""
        client = make_client()
        captured: dict = {}

        def fake_post(**kwargs):
            """记录写入负载并返回成功。"""
            captured.update(kwargs["json"])
            return FakeResponse()

        client.get_full_dto = lambda item_id: json.loads(json.dumps(base))
        client._request.post_res = fake_post
        client.get_item_detail = lambda item_id, fields=None: {
            "Overview": "新的简介内容",
            "Name": base.get("Name"),
            "People": captured.get("People") or [],
        }
        return client, captured

    def test_merge_dedupe_and_lock(self):
        """同名（大小写不同）演员只保留一条，并锁定 Cast。"""
        base = {
            "Id": "1",
            "Name": "MV",
            "Overview": "旧",
            "People": [{"Name": "4minute", "Type": "Actor"}, {"Name": "4Minute", "Type": "Actor"}],
            "ProviderIds": {},
            "LockedFields": [],
        }
        client, captured = self._prepare(base)
        ok, message = client.update_overview(
            "1",
            "新的简介内容",
            lock=True,
            people=[{"Name": "4minute", "Type": "Actor", "Role": "演唱"}],
            lock_people=True,
        )
        assert ok, message
        assert len(captured["People"]) == 1
        assert "Overview" in captured["LockedFields"]
        assert "Cast" in captured["LockedFields"]

    def test_prune_stale_members(self):
        """移除「成员」角色中不在期望名单里的历史写入，保留其他角色。"""
        base = {
            "Id": "1",
            "Name": "MV",
            "Overview": "旧",
            "People": [
                {"Name": "2NE1", "Role": "演唱", "Type": "Actor"},
                {"Name": "朴山多拉", "Role": "成员", "Type": "Actor"},
                {"Name": "副导演", "Role": "Director", "Type": "Director"},
            ],
            "ProviderIds": {},
            "LockedFields": [],
        }
        client, captured = self._prepare(base)
        ok, message = client.update_overview(
            "1",
            "新的简介内容",
            lock=True,
            people=[
                {"Name": "2NE1", "Role": "演唱", "Type": "Actor"},
                {"Name": "朴珊德拉", "Role": "成员", "Type": "Actor"},
            ],
            lock_people=True,
            prune_role="成员",
        )
        assert ok, message
        assert [item["Name"] for item in captured["People"]] == ["2NE1", "副导演", "朴珊德拉"]


class TestNfoOutput:
    """NFO 生成与路径映射。"""

    def test_write_nfo_with_thumb(self, tmp_path):
        """NFO 写入路径映射位置，包含简介、演员、顺序与本地头像路径。"""
        engine = make_engine(tmp_path, nfo_path_map=f"/media/:{tmp_path}/")
        media = tmp_path / "MV" / "2NE1" / "2NE1 - X.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"video")
        media.with_suffix(".jpg").write_bytes(b"poster")
        engine._person_image = lambda name: (
            str(tmp_path / "MV" / ".actors" / f"{name}.jpg") if name == "李彩琳" else ""
        )
        engine._write_nfo(
            {"title": "2NE1 - X", "year": "2010", "path": "/media/MV/2NE1/2NE1 - X.mp4"},
            "简介内容",
            [
                {"Name": "2NE1", "Role": "演唱", "Type": "Actor"},
                {"Name": "李彩琳", "Role": "成员", "Type": "Actor"},
            ],
        )
        text = media.with_suffix(".nfo").read_text(encoding="utf-8")
        assert "<plot>简介内容</plot>" in text
        assert "<order>1</order>" in text
        assert "李彩琳.jpg" in text
        assert media.read_bytes() == b"video"

    def test_write_nfo_skips_when_mapping_mismatch(self, tmp_path):
        """路径不匹配时不写 NFO。"""
        engine = make_engine(tmp_path, nfo_path_map="/media/:/medias/media/")
        media = tmp_path / "MV" / "X.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"video")
        engine._write_nfo({"title": "X", "path": f"{media}"}, "简介", [])
        assert not media.with_suffix(".nfo").exists()


class TestPeopleAvatar:
    """演员头像写入调用。"""

    def test_ensure_avatars_calls_remote_image(self, tmp_path):
        """自动补头像会对人物调用 Emby 远程图片接口。"""
        engine = make_engine(tmp_path, mv_people_avatar=True)
        engine._person_image = lambda name: "https://example.invalid/x.jpg"
        client = Mock()
        client.get_full_dto = Mock(
            return_value={"People": [{"Name": "李彩琳", "Id": "42884", "Type": "Actor"}]}
        )
        client.set_remote_image = Mock(return_value=(True, ""))
        engine._ensure_avatars(client, {"item_id": "1"}, [{"Name": "李彩琳", "Type": "Actor"}])
        client.set_remote_image.assert_called_once_with("42884", "https://example.invalid/x.jpg")

    def test_ensure_avatars_disabled(self, tmp_path):
        """关闭开关后不写入头像。"""
        engine = make_engine(tmp_path, mv_people_avatar=False)
        client = Mock()
        engine._ensure_avatars(client, {"item_id": "1"}, [{"Name": "某人", "Type": "Actor"}])
        client.set_remote_image.assert_not_called()
        client.get_full_dto.assert_not_called()

    def test_mv_people_includes_members(self, tmp_path):
        """MV 演员列表包含团体与成员，角色分别为演唱与成员。"""
        engine = make_engine(tmp_path)
        engine._mb.members = Mock(return_value=["CL", "Minzy"])
        engine._wd.members = Mock(return_value=[])
        engine._llm.translate_names = Mock(return_value=["李彩琳", "孔敏智"])
        people = engine._mv_people({"kind": MV, "artist": "2NE1"})
        assert [item["Name"] for item in people] == ["2NE1", "李彩琳", "孔敏智"]
        assert people[0]["Role"] == "演唱"
        assert people[1]["Role"] == "成员"
