import tomllib
from pathlib import Path

from app.plugins.animeupscale import AnimeUpscale
from app.plugins.animeupscale.ffmpeg import encoder_command, remux_command


def _plugin(tmp_path, enabled=False, **config):
    plugin = object.__new__(AnimeUpscale)
    plugin.get_data_path = lambda: tmp_path
    plugin.init_plugin(
        {
            "enabled": enabled,
            "model_dir": str(tmp_path / "models"),
            "input_root": str(tmp_path / "input"),
            "output_root": str(tmp_path / "output"),
            **config,
        }
    )
    return plugin


def test_v3_plugin_uses_next_major_and_response_envelope(tmp_path):
    plugin = _plugin(tmp_path)

    response = plugin.api_status()

    assert plugin.plugin_version == "2.1.2"
    assert response.success is True
    assert "ready" in response.data
    plugin.stop_service()


def test_v3_dependency_manifest_targets_python314_pytorch():
    manifest = Path(__file__).parents[3] / "plugins.v3" / "animeupscale" / "pyproject.toml"
    metadata = tomllib.loads(manifest.read_text(encoding="utf-8"))

    assert "torch==2.13.0+cu126" in metadata["project"]["dependencies"]
    assert metadata["tool"]["uv"]["sources"]["torch"]["index"] == "pytorch-cu126"


def test_v3_create_jobs_returns_failure_envelope_when_disabled(tmp_path):
    plugin = _plugin(tmp_path, enabled=False)

    response = plugin.api_create_jobs({"input_path": "episode.mkv"})

    assert response.success is False
    assert response.message == "插件未启用"
    assert response.data is None
    plugin.stop_service()


def test_v3_planning_resolves_paths_and_rejects_symlink_escape(tmp_path):
    plugin = _plugin(tmp_path)
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    outside = tmp_path / "outside.mkv"
    input_root.mkdir()
    output_root.mkdir()
    outside.write_bytes(b"video")
    (input_root / "linked.mkv").symlink_to(outside)

    try:
        plugin._plan_jobs(
            input_root,
            output_root,
            recursive=True,
            model="starsample_v2_lite",
            input_root=input_root,
            output_root=output_root,
        )
    except ValueError as error:
        assert "输入文件" in str(error)
    else:
        raise AssertionError("未拒绝指向输入根目录外的符号链接")
    finally:
        plugin.stop_service()


def test_v3_ffmpeg_commands_keep_gpu_and_convert_mov_text(tmp_path):
    encoder = encoder_command(
        tmp_path / "video.mkv", 3840, 2160, "24000/1001", "1/1", 18, 3
    )
    remux = remux_command(
        tmp_path / "video.mkv",
        tmp_path / "input.mp4",
        tmp_path / "output.mkv",
        ["mov_text", "ass"],
    )

    assert encoder[encoder.index("-gpu") + 1] == "3"
    assert remux[remux.index("-c") + 1] == "copy"
    assert remux[remux.index("-c:s:0") + 1] == "srt"
    assert "-c:s:1" not in remux
