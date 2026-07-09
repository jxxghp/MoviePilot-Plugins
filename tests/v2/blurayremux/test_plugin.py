import subprocess
from pathlib import Path

import blurayremux
from app.core.config import settings
from app.core.context import MediaInfo
from app.core.metainfo import MetaInfoPath
from app.modules.filemanager.storages.local import LocalStorage
from app.schemas import FileItem
from app.schemas.types import MediaType
from blurayremux import BlurayRemux


def _write_mpls(path: Path, stream_names: list[str]):
    items = b""
    for stream_name in stream_names:
        clip_name = Path(stream_name).stem.encode("ascii")[:5].ljust(5, b"\x00")
        body = (
            clip_name
            + b"M2TS"
            + b"\x00"
            + b"\x00"
            + b"\x01"
            + (0).to_bytes(4, "big")
            + (90000).to_bytes(4, "big")
        )
        items += len(body).to_bytes(2, "big") + body
    playlist = (
        len(items).to_bytes(4, "big")
        + b"\x00\x00"
        + len(stream_names).to_bytes(2, "big")
        + (0).to_bytes(2, "big")
        + items
    )
    path.write_bytes(b"MPLS0200" + (16).to_bytes(4, "big") + b"\x00" * 4 + playlist)


def _create_bluray_dir(root: Path) -> FileItem:
    stream_dir = root / "BDMV" / "STREAM"
    playlist_dir = root / "BDMV" / "PLAYLIST"
    stream_dir.mkdir(parents=True)
    playlist_dir.mkdir(parents=True)
    (stream_dir / "00000.m2ts").write_bytes(b"0" * 10)
    (stream_dir / "00001.m2ts").write_bytes(b"1" * 20)
    _write_mpls(playlist_dir / "00000.mpls", ["00000.m2ts", "00001.m2ts"])
    return FileItem(
        storage="local",
        type="dir",
        path=root.as_posix(),
        name=root.name,
        basename=root.stem,
        size=0,
    )


def _media_info(media_type: MediaType = MediaType.MOVIE) -> MediaInfo:
    mediainfo = MediaInfo()
    mediainfo.type = media_type
    mediainfo.title = "Sample Movie" if media_type == MediaType.MOVIE else "Sample Show"
    mediainfo.year = "2024"
    return mediainfo


def _plugin(enabled: bool = True) -> BlurayRemux:
    plugin = BlurayRemux()
    plugin.init_plugin({"enabled": enabled, "timeout": 60})
    return plugin


def test_disabled_plugin_returns_none(tmp_path):
    source_item = _create_bluray_dir(tmp_path / "Sample Movie Source")

    result = _plugin(enabled=False).transfer(
        fileitem=source_item,
        meta=MetaInfoPath(Path("Sample Movie (2024)")),
        mediainfo=_media_info(),
        target_path=tmp_path / "media",
        transfer_type="copy",
    )

    assert result is None


def test_non_bluray_directory_returns_none(tmp_path):
    source_dir = tmp_path / "Plain Directory"
    source_dir.mkdir()
    source_item = FileItem(
        storage="local",
        type="dir",
        path=source_dir.as_posix(),
        name=source_dir.name,
        basename=source_dir.stem,
    )

    result = _plugin().transfer(
        fileitem=source_item,
        meta=MetaInfoPath(Path("Sample Movie (2024)")),
        mediainfo=_media_info(),
        target_path=tmp_path / "media",
        transfer_type="copy",
    )

    assert result is None


def test_movie_bluray_remux_uses_playlist_concat(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings,
        "MOVIE_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/{{title}}{% if year %} ({{year}}){% endif %}{{fileExt}}",
    )
    monkeypatch.setattr(blurayremux.shutil, "which", lambda _name: "ffmpeg")
    commands = []

    def run_ffmpeg(command, *_args, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"mkv")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(blurayremux.subprocess, "run", run_ffmpeg)
    source_item = _create_bluray_dir(tmp_path / "Sample Movie Source")

    result = _plugin().transfer(
        fileitem=source_item,
        meta=MetaInfoPath(Path("Sample Movie (2024)")),
        mediainfo=_media_info(),
        target_path=tmp_path / "media",
        transfer_type="copy",
    )

    target_file = tmp_path / "media" / "Sample Movie (2024)" / "Sample Movie (2024).mkv"
    assert result.success is True
    assert result.target_item.path == target_file.as_posix()
    assert target_file.exists()
    assert "-f" in commands[0]
    assert "concat" in commands[0]


def test_tv_bluray_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(blurayremux.subprocess, "run", lambda *_args, **_kwargs: None)
    source_item = _create_bluray_dir(tmp_path / "Sample Show S01")

    result = _plugin().transfer(
        fileitem=source_item,
        meta=MetaInfoPath(Path("Sample Show S01")),
        mediainfo=_media_info(MediaType.TV),
        target_path=tmp_path / "media",
        transfer_type="copy",
    )

    assert result is None


def test_unmatched_playlist_returns_failure_without_ffmpeg(tmp_path, monkeypatch):
    called = False

    def run_ffmpeg(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(blurayremux.shutil, "which", lambda _name: "ffmpeg")
    monkeypatch.setattr(blurayremux.subprocess, "run", run_ffmpeg)
    source_root = tmp_path / "Sample Movie Source"
    source_item = _create_bluray_dir(source_root)
    _write_mpls(source_root / "BDMV" / "PLAYLIST" / "00000.mpls", ["99999.m2ts"])

    result = _plugin().transfer(
        fileitem=source_item,
        meta=MetaInfoPath(Path("Sample Movie (2024)")),
        mediainfo=_media_info(),
        target_path=tmp_path / "media",
        transfer_type="copy",
    )

    assert result.success is False
    assert "未找到可转封装的视频分片" in result.message
    assert called is False


def test_rejects_target_inside_source(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings,
        "MOVIE_RENAME_FORMAT",
        "{{title}}{% if year %} ({{year}}){% endif %}/{{title}}{% if year %} ({{year}}){% endif %}{{fileExt}}",
    )
    source_root = tmp_path / "Sample Movie Source"
    source_item = _create_bluray_dir(source_root)

    result = _plugin().transfer(
        fileitem=source_item,
        meta=MetaInfoPath(Path("Sample Movie (2024)")),
        mediainfo=_media_info(),
        target_path=source_root,
        transfer_type="copy",
    )

    assert result.success is False
    assert "目标不能位于源目录内" in result.message


def test_move_delete_failure_keeps_new_target(tmp_path, monkeypatch):
    class DeleteFailingLocalStorage(LocalStorage):
        def delete(self, fileitem):
            return False

    monkeypatch.setattr(blurayremux.shutil, "which", lambda _name: "ffmpeg")

    def run_ffmpeg(command, *_args, **_kwargs):
        Path(command[-1]).write_bytes(b"mkv")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(blurayremux.subprocess, "run", run_ffmpeg)
    source_root = tmp_path / "Sample Movie Source"
    source_item = _create_bluray_dir(source_root)

    result = _plugin().transfer(
        fileitem=source_item,
        meta=MetaInfoPath(Path("Sample Movie (2024)")),
        mediainfo=_media_info(),
        target_path=tmp_path / "media",
        transfer_type="move",
        source_oper=DeleteFailingLocalStorage(),
        target_oper=LocalStorage(),
    )

    assert result.success is False
    assert result.target_item is not None
    assert Path(result.target_item.path).exists()
    assert source_root.exists()


def test_target_lock_cache_keeps_strong_reference(tmp_path):
    target = tmp_path / "target.mkv"

    lock = BlurayRemux._BlurayRemux__get_target_lock(target)

    assert lock is BlurayRemux._BlurayRemux__get_target_lock(target)


def test_latest_mode_skips_version_delete_without_safe_identifier(tmp_path):
    media_dir = tmp_path / "media" / "Sample Movie (2024)"
    media_dir.mkdir(parents=True)
    target_file = media_dir / "Sample Movie (2024).mkv"
    old_file = media_dir / "Sample Movie (2024).old.mkv"
    target_file.write_bytes(b"new")
    old_file.write_bytes(b"old")

    deleted = BlurayRemux._BlurayRemux__delete_version_files(
        LocalStorage(),
        target_file,
        _media_info(),
    )

    assert deleted is False
    assert old_file.exists()


def test_run_remux_returns_failure_when_target_dir_cannot_be_created(tmp_path, monkeypatch):
    plugin = _plugin()
    source_file = tmp_path / "00000.m2ts"
    source_file.write_bytes(b"stream")
    target_file = tmp_path / "blocked" / "target.mkv"
    monkeypatch.setattr(blurayremux.shutil, "which", lambda _name: "ffmpeg")

    original_mkdir = Path.mkdir

    def fail_target_mkdir(self, *args, **kwargs):
        if self == target_file.parent:
            raise PermissionError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_target_mkdir)

    state, message = plugin._BlurayRemux__run_remux(
        source_files=[blurayremux._RemuxSource(source_file)],
        target_file=target_file,
        allow_target_replace=False,
        recheck_target_size=None,
    )

    assert state is False
    assert "蓝光原盘转封装失败" in message
    assert "blocked" in message
