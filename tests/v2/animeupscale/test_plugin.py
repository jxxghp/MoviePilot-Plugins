import hashlib
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

import animeupscale
from animeupscale import AnimeUpscale
from animeupscale.database import Database
from animeupscale.ffmpeg import encoder_command, remux_command


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


def test_config_bounds_numeric_values_and_defaults_model(tmp_path):
    plugin = _plugin(
        tmp_path,
        cq=99,
        gpu_index=-4,
        tile=8,
        context=9999,
        model="unknown",
    )

    assert plugin._cq == 51
    assert plugin._gpu_index == 0
    assert plugin._tile == 64
    assert plugin._context == 512
    assert plugin._model == "starsample_v2_lite"


def test_inside_rejects_absolute_and_parent_paths(tmp_path):
    root = tmp_path / "media"
    root.mkdir()

    assert AnimeUpscale._inside(root, "show/episode.mkv") == root / "show/episode.mkv"

    for value in ("/etc/passwd", "../outside.mkv"):
        try:
            AnimeUpscale._inside(root, value)
        except ValueError as error:
            assert "路径" in str(error)
        else:
            raise AssertionError(f"未拒绝越界路径：{value}")


def test_plan_jobs_keeps_recursive_relative_directories(tmp_path):
    plugin = _plugin(tmp_path)
    source = tmp_path / "input" / "Series" / "Season 01"
    source.mkdir(parents=True)
    (source / "Episode 01.mkv").write_bytes(b"video")
    (source / "cover.jpg").write_bytes(b"image")
    output = tmp_path / "output"
    output.mkdir()

    planned = plugin._plan_jobs(
        tmp_path / "input",
        output,
        recursive=True,
        model="starsample_v2_lite",
        input_root=tmp_path / "input",
        output_root=output,
    )

    assert planned == [
        (
            source / "Episode 01.mkv",
            output / "Series" / "Season 01" / "Episode 01.starsample-2x.mkv",
        )
    ]


def test_plan_jobs_rejects_input_symlink_outside_root(tmp_path):
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


def test_plan_jobs_rejects_output_symlink_outside_root(tmp_path):
    plugin = _plugin(tmp_path)
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    outside = tmp_path / "outside"
    (input_root / "Series").mkdir(parents=True)
    output_root.mkdir()
    outside.mkdir()
    (input_root / "Series" / "episode.mkv").write_bytes(b"video")
    (output_root / "Series").symlink_to(outside, target_is_directory=True)

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
        assert "输出目标" in str(error)
    else:
        raise AssertionError("未拒绝指向输出根目录外的符号链接")


def test_encoder_command_uses_configured_gpu(tmp_path):
    command = encoder_command(
        tmp_path / "video.mkv", 3840, 2160, "24000/1001", "1/1", 18, 2
    )

    assert command[command.index("-gpu") + 1] == "2"
    assert command[command.index("-c:v") + 1] == "hevc_nvenc"


def test_remux_command_only_transcodes_mov_text_subtitles(tmp_path):
    command = remux_command(
        tmp_path / "video.mkv",
        tmp_path / "input.mp4",
        tmp_path / "output.mkv",
        ["mov_text", "ass", "mov_text"],
    )

    assert command[command.index("-c") + 1] == "copy"
    assert [command[command.index(option) + 1] for option in ("-c:s:0", "-c:s:2")] == [
        "srt",
        "srt",
    ]
    assert "-c:s:1" not in command


def test_database_queue_cancel_retry_and_recovery(tmp_path):
    database = Database(tmp_path / "jobs.sqlite3")
    source = tmp_path / "input.mkv"
    target = tmp_path / "output.mkv"
    job = database.create_many(
        [(source, target)], 18, "starsample_v2_lite"
    )[0]

    assert database.has_queued()
    running = database.claim_next()
    assert running["id"] == job["id"]
    assert running["status"] == "running"
    assert database.request_cancel(job["id"])

    database.finish(job["id"], "cancelled")
    assert database.retry(job["id"])
    assert database.get(job["id"])["status"] == "queued"

    database.claim_next()
    database.recover_interrupted()
    recovered = database.get(job["id"])
    assert recovered["status"] == "failed"
    assert "MoviePilot" in recovered["error"]


def test_worker_drains_queue_serially(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, enabled=True)
    plugin._database.create_many(
        [
            (tmp_path / "a.mkv", tmp_path / "a.out.mkv"),
            (tmp_path / "b.mkv", tmp_path / "b.out.mkv"),
        ],
        18,
        "starsample_v2_lite",
    )
    observed = []

    def run_job(job):
        observed.append(job["input_path"])
        plugin._database.finish(job["id"], "completed")

    monkeypatch.setattr(plugin, "_run_job", run_job)

    plugin._drain_queue()

    assert observed == [str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv")]
    assert {job["status"] for job in plugin._database.list()} == {"completed"}
    plugin.stop_service()


def test_cancel_running_job_sets_worker_event_and_terminates_processes(
    tmp_path, monkeypatch
):
    plugin = _plugin(tmp_path, enabled=True)
    job = plugin._database.create_many(
        [(tmp_path / "a.mkv", tmp_path / "a.out.mkv")],
        18,
        "starsample_v2_lite",
    )[0]
    plugin._database.claim_next()
    plugin._current_job_id = job["id"]
    plugin._current_cancel = threading.Event()
    process = object()
    plugin._active_processes.add(process)
    terminated = []
    fake_pipeline = types.ModuleType("animeupscale.pipeline")
    fake_pipeline.terminate = terminated.append
    monkeypatch.setitem(sys.modules, "animeupscale.pipeline", fake_pipeline)

    response = plugin.api_cancel_job({"job_id": job["id"]})

    assert response.status_code == 200
    assert plugin._current_cancel.is_set()
    assert terminated == [process]
    plugin._active_processes.clear()
    plugin.stop_service()


def test_cancelled_pipeline_marks_job_cancelled(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, enabled=True)
    job = plugin._database.create_many(
        [(tmp_path / "a.mkv", tmp_path / "a.out.mkv")],
        18,
        "starsample_v2_lite",
    )[0]
    job = plugin._database.claim_next()
    fake_pipeline = types.ModuleType("animeupscale.pipeline")

    def run_pipeline(*args, **kwargs):
        del args, kwargs
        plugin._current_cancel.set()
        raise animeupscale.Cancelled()

    fake_pipeline.run_pipeline = run_pipeline
    monkeypatch.setitem(sys.modules, "animeupscale.pipeline", fake_pipeline)
    monkeypatch.setattr(plugin, "_get_runtime", lambda *_args: object())

    plugin._run_job(job)

    assert plugin._database.get(job["id"])["status"] == "cancelled"
    plugin.stop_service()


def test_cancel_between_claim_and_run_is_not_lost(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, enabled=True)
    job = plugin._database.create_many(
        [(tmp_path / "a.mkv", tmp_path / "a.out.mkv")],
        18,
        "starsample_v2_lite",
    )[0]
    job = plugin._database.claim_next()
    assert plugin._database.request_cancel(job["id"])
    model_loaded = []
    monkeypatch.setattr(plugin, "_get_runtime", lambda *_args: model_loaded.append(True))

    plugin._run_job(job)

    assert model_loaded == []
    assert plugin._database.get(job["id"])["status"] == "cancelled"
    plugin.stop_service()


def test_manual_model_is_verified_and_cached(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    model = plugin.MODELS["starsample_v2_lite"]
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    path = model_dir / model["filename"]
    path.write_bytes(b"model-data")
    monkeypatch.setitem(model, "sha256", hashlib.sha256(b"model-data").hexdigest())

    assert plugin._model_status("starsample_v2_lite")["state"] == "valid"
    assert plugin._model_status("starsample_v2_lite")["state"] == "valid"
    assert len(plugin._hash_cache) == 1


def test_download_is_atomic_and_verified(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, starsample_url="https://models.example/star")
    content = b"downloaded-model"
    monkeypatch.setitem(
        plugin.MODELS["starsample_v2_lite"],
        "sha256",
        hashlib.sha256(content).hexdigest(),
    )

    class Response:
        headers = {"Content-Length": str(len(content))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            assert chunk_size == plugin._CHUNK_SIZE
            yield content

    class Request:
        def __init__(self, **_kwargs):
            pass

        def get_stream(self, url):
            assert url == plugin._starsample_url
            return Response()

    monkeypatch.setattr(animeupscale, "RequestUtils", Request)

    plugin._download_models(["starsample_v2_lite"])

    target = tmp_path / "models" / "2x-StarSample-V2-Lite.safetensors"
    assert target.read_bytes() == content
    assert not (target.parent / f".{target.name}.part").exists()
    assert plugin._download_state["starsample_v2_lite"]["state"] == "valid"


def test_bad_download_keeps_existing_model(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, starsample_url="https://models.example/star")
    model = plugin.MODELS["starsample_v2_lite"]
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    target = model_dir / model["filename"]
    target.write_bytes(b"existing")

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"invalid"

    class Request:
        def __init__(self, **_kwargs):
            pass

        def get_stream(self, _url):
            return Response()

    monkeypatch.setattr(animeupscale, "RequestUtils", Request)

    plugin._download_models(["starsample_v2_lite"])

    assert target.read_bytes() == b"existing"
    assert plugin._download_state["starsample_v2_lite"]["state"] == "failed"


def test_download_handles_empty_response(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, starsample_url="https://models.example/star")

    class Request:
        def __init__(self, **_kwargs):
            pass

        def get_stream(self, _url):
            class EmptyResponse:
                def __enter__(self):
                    return None

                def __exit__(self, *_args):
                    return None

            return EmptyResponse()

    monkeypatch.setattr(animeupscale, "RequestUtils", Request)

    plugin._download_models(["starsample_v2_lite"])

    state = plugin._download_state["starsample_v2_lite"]
    assert state["state"] == "failed"
    assert state["message"] == "无法连接模型下载地址"


def test_status_reports_local_gpu_and_ffmpeg(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, enabled=True, gpu_index=2)
    fake_cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 4,
        get_device_name=lambda index: f"Tesla T4 #{index}",
        empty_cache=lambda: None,
    )
    fake_torch = SimpleNamespace(cuda=fake_cuda)
    monkeypatch.setattr(animeupscale.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        animeupscale.importlib.util,
        "find_spec",
        lambda name: object() if name in {"torch", "cv2", "spandrel", "spandrel_extra_arches"} else None,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        animeupscale.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=" V..... hevc_nvenc NVIDIA NVENC hevc encoder",
        ),
    )

    status = plugin._status()

    assert status["ready"] is True
    assert status["gpu"] == "Tesla T4 #2"
    assert status["ffmpeg_ready"] is True
    assert status["nvenc_ready"] is True
    plugin.stop_service()


def test_create_jobs_rejects_unavailable_embedded_runtime(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, enabled=True)
    monkeypatch.setattr(
        plugin,
        "_runtime_diagnostics",
        lambda: {"errors": ["CUDA GPU 0 不可用"]},
    )

    response = plugin.api_create_jobs({"input_path": "episode.mkv"})

    assert response.status_code == 503
    assert "CUDA GPU 0 不可用" in response.body.decode("utf-8")
    assert plugin._database.list() == []
    plugin.stop_service()
