import hashlib

import animeupscale
from animeupscale import AnimeUpscale


def _plugin(tmp_path, **config):
    plugin = object.__new__(AnimeUpscale)
    plugin.get_data_path = lambda: tmp_path
    plugin.init_plugin({"enabled": True, "model_dir": str(tmp_path / "models"), **config})
    return plugin


def test_config_normalizes_url_and_bounds_cq(tmp_path):
    plugin = _plugin(
        tmp_path,
        service_url="https://upscale.example/base/?secret=yes",
        cq=99,
        model="unknown",
    )

    assert plugin._service_url == "https://upscale.example/base"
    assert plugin._cq == 51
    assert plugin._model == "starsample_v2_lite"


def test_reinitialization_preserves_download_runtime_state(tmp_path):
    plugin = _plugin(tmp_path)
    lock = plugin._download_lock
    plugin._download_state["starsample_v2_lite"] = {
        "state": "downloading",
        "message": "正在下载",
    }

    plugin.init_plugin({"enabled": True, "model_dir": str(tmp_path / "models")})

    assert plugin._download_lock is lock
    assert plugin._download_state["starsample_v2_lite"]["state"] == "downloading"


def test_auto_download_only_schedules_missing_models_with_urls(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    existing = model_dir / plugin.MODELS["animesr_v2"]["filename"]
    existing.write_bytes(b"existing")
    submitted = []

    class Threads:
        def submit(self, func, model_ids, lock_acquired):
            submitted.append((func, model_ids, lock_acquired))

    monkeypatch.setattr(animeupscale, "ThreadHelper", Threads)
    plugin.init_plugin(
        {
            "enabled": True,
            "auto_download": True,
            "model_dir": str(model_dir),
            "starsample_url": "https://models.example/star",
            "animesr_url": "https://models.example/animesr",
        }
    )

    assert submitted[0][1:] == (["starsample_v2_lite"], True)
    plugin._download_lock.release()


def test_manual_model_is_verified_and_hash_is_cached(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    model = plugin.MODELS["starsample_v2_lite"]
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    path = model_dir / model["filename"]
    path.write_bytes(b"model-data")
    monkeypatch.setitem(model, "sha256", hashlib.sha256(b"model-data").hexdigest())

    calls = 0
    original = AnimeUpscale._file_sha256

    def counted(instance, model_path, force=False):
        nonlocal calls
        calls += 1
        return original(instance, model_path, force)

    monkeypatch.setattr(AnimeUpscale, "_file_sha256", counted)
    assert plugin._model_status("starsample_v2_lite")["state"] == "valid"
    assert plugin._model_status("starsample_v2_lite")["state"] == "valid"
    assert calls == 2
    assert len(plugin._hash_cache) == 1


def test_invalid_manual_model_is_rejected(tmp_path):
    plugin = _plugin(tmp_path)
    model = plugin.MODELS["animesr_v2"]
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / model["filename"]).write_bytes(b"wrong")

    status = plugin._model_status("animesr_v2")

    assert status["state"] == "invalid"
    assert status["message"] == "SHA256 不匹配"


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
            self._sent = False
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            assert chunk_size == plugin._CHUNK_SIZE
            yield content

        def close(self):
            return None

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


def test_bad_download_does_not_replace_existing_model(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
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

        def close(self):
            return None

    class Request:
        def __init__(self, **_kwargs):
            pass

        def get_stream(self, _url):
            return Response()

    monkeypatch.setattr(animeupscale, "RequestUtils", Request)

    plugin._starsample_url = "https://models.example/star"
    plugin._download_models(["starsample_v2_lite"])

    assert target.read_bytes() == b"existing"
    assert plugin._download_state["starsample_v2_lite"]["state"] == "failed"


def test_service_request_serializes_json(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, service_url="http://upscale:8787")
    captured = {}

    class Response:
        status_code = 201
        content = b'{"created": 1}'

        def close(self):
            captured["closed"] = True

    class Request:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs["timeout"]

        def post_res(self, url, json):
            captured["url"] = url
            captured["method"] = "POST"
            captured["payload"] = json
            return Response()

    monkeypatch.setattr(animeupscale, "RequestUtils", Request)

    status, result = plugin._service_request("/api/jobs", "POST", {"input_path": "show"})

    assert status == 201
    assert result == {"created": 1}
    assert captured == {
        "url": "http://upscale:8787/api/jobs",
        "method": "POST",
        "payload": {"input_path": "show"},
        "timeout": 15,
        "closed": True,
    }


def test_service_request_converts_connection_error(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)

    class Request:
        def __init__(self, **_kwargs):
            pass

        def get_res(self, _url):
            return None

    monkeypatch.setattr(animeupscale, "RequestUtils", Request)

    status, result = plugin._service_request("/api/status")

    assert status == 502
    assert "无法连接" in result["detail"]
