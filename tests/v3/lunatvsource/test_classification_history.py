import hashlib
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import CmsResult
from app.plugins.lunatvsource.downloader import DownloadTask


def _task(tmp_path: Path, **overrides) -> DownloadTask:
    """Build one persisted LunaTV task with a stable host media identity."""

    values = {
        "task_id": "classification-task",
        "source_key": "cms-demo",
        "media_id": "cms-demo:42",
        "title": "分类电影",
        "year": "2026",
        "media_type": "movie",
        "season": 1,
        "episode": 1,
        "url": "https://example.test/movie.m3u8",
        "root": str(tmp_path),
        "host_media_source": "themoviedb",
        "host_media_id": "123",
    }
    values.update(overrides)
    return DownloadTask(**values)


def _install_history_modules(monkeypatch, histories, files, *, c3_model: bool) -> None:
    """Install the minimal host DownloadHistory ABI used by direct writes."""

    download_oper_module = ModuleType("app.db.oper.downloadhistory")

    class FakeDownloadHistoryOper:
        """Capture history and file rows without a real database."""

        def get_by_hash(self, download_hash):
            return next(
                (item for item in histories if item["download_hash"] == download_hash),
                None,
            )

        def get_files_by_hash(self, download_hash, state=None):
            return [
                item
                for item in files
                if item["download_hash"] == download_hash
                and (state is None or item["state"] == state)
            ]

        def get_file_by_fullpath(self, fullpath):
            return next(
                (item for item in reversed(files) if item["fullpath"] == fullpath),
                None,
            )

        def add(self, **kwargs):
            histories.append(kwargs)

        def add_files(self, items):
            files.extend(items)

    download_oper_module.DownloadHistoryOper = FakeDownloadHistoryOper
    download_model_module = ModuleType("app.db.models.downloadhistory")

    class DownloadHistory:
        """Expose C3 columns only when the simulated host supports them."""

    if c3_model:
        for field in (
            "media_category_id",
            "media_category",
            "classification_rule_id",
            "classification_policy_revision",
            "classification_source",
        ):
            setattr(DownloadHistory, field, None)
    download_model_module.DownloadHistory = DownloadHistory

    app_module = ModuleType("app")
    app_module.__path__ = []
    db_module = ModuleType("app.db")
    db_module.__path__ = []
    oper_module = ModuleType("app.db.oper")
    oper_module.__path__ = []
    models_module = ModuleType("app.db.models")
    models_module.__path__ = []
    app_module.db = db_module
    db_module.oper = oper_module
    db_module.models = models_module
    oper_module.downloadhistory = download_oper_module
    models_module.downloadhistory = download_model_module

    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.db", db_module)
    monkeypatch.setitem(sys.modules, "app.db.oper", oper_module)
    monkeypatch.setitem(
        sys.modules, "app.db.oper.downloadhistory", download_oper_module
    )
    monkeypatch.setitem(sys.modules, "app.db.models", models_module)
    monkeypatch.setitem(
        sys.modules, "app.db.models.downloadhistory", download_model_module
    )


def test_media_snapshot_uses_effective_classification_not_metadata_category():
    media = SimpleNamespace(
        media_source="themoviedb",
        media_id="123",
        library_category="旧兼容/路径",
        metadata_category="来源分类/不得使用",
        classification=SimpleNamespace(
            policy_revision=17,
            effective=SimpleNamespace(
                category_id="movie.animation",
                category_path=["电影", "动画"],
                rule_id="rule-animation",
                source="rule",
            ),
            recommended=SimpleNamespace(category_path=["错误推荐"]),
        ),
    )

    assert LunaTVSource._media_classification_snapshot(media) == {
        "media_source": "themoviedb",
        "media_id": "123",
        "media_category_id": "movie.animation",
        "media_category": "电影/动画",
        "classification_rule_id": "rule-animation",
        "classification_policy_revision": 17,
        "classification_source": "rule",
    }


def test_media_snapshot_ignores_source_extension_facts():
    """Keep E1 source facts out of the C3 persisted classification snapshot."""

    media = SimpleNamespace(
        media_source="lunatv",
        media_id="cms-demo:42",
        classification_facts={
            "extensions.lunatv.cms_source_key": "cms-demo",
        },
        classification=SimpleNamespace(
            policy_revision=18,
            effective=SimpleNamespace(
                category_id="movie.cms",
                category_path=["电影", "CMS"],
                rule_id="rule-cms",
                source="rule",
            ),
        ),
    )

    assert LunaTVSource._media_classification_snapshot(media) == {
        "media_source": "lunatv",
        "media_id": "cms-demo:42",
        "media_category_id": "movie.cms",
        "media_category": "电影/CMS",
        "classification_rule_id": "rule-cms",
        "classification_policy_revision": 18,
        "classification_source": "rule",
    }


def test_existing_host_association_freezes_media_info_classification(monkeypatch):
    calls = []
    media = SimpleNamespace(
        media_source="themoviedb",
        media_id="123",
        tmdb_id=123,
        title="分类电影",
        year="2026",
        seasons={},
        classification=SimpleNamespace(
            policy_revision=17,
            effective=SimpleNamespace(
                category_id="movie.animation",
                category_path=["电影", "动画"],
                rule_id="rule-animation",
                source="rule",
            ),
        ),
    )

    class MediaChain:
        """Return the already-finalized host MediaInfo for the existing lookup."""

        def recognize_media(self, **kwargs):
            calls.append(kwargs)
            return media

    class MetaInfo:
        """Expose the minimal public MetaInfo constructor used by the plugin."""

        def __init__(self, title):
            self.title = title

    class HostTypes:
        TMDB = "themoviedb"
        MOVIE = "movie"
        TV = "tv"

    monkeypatch.setattr(plugin_module, "_HostMediaChain", MediaChain)
    monkeypatch.setattr(plugin_module, "_HostMetaInfo", MetaInfo)
    monkeypatch.setattr(plugin_module, "_HostMediaSource", HostTypes)
    monkeypatch.setattr(plugin_module, "_HostMediaType", HostTypes)
    plugin = object.__new__(LunaTVSource)
    plugin._tmdb_cache_lock = threading.Lock()
    plugin._tmdb_cache = {}
    monkeypatch.setattr(plugin, "_store_tmdb_cache_entry", lambda *_args: None)

    association = plugin._associate_tmdb(
        CmsResult(
            source_key="cms-demo",
            source_name="演示源",
            vod_id="42",
            title="分类电影",
            year="2026",
            media_type="movie",
            remark="",
        ),
        include_candidates=False,
    )

    assert len(calls) == 1
    assert calls[0]["media_source"] == "themoviedb"
    assert calls[0]["cache"] is True
    assert association["media_source"] == "themoviedb"
    assert association["media_id"] == "123"
    assert association["classification"]["media_category_id"] == (
        "movie.animation"
    )
    assert association["classification"]["classification_policy_revision"] == 17


def test_media_snapshot_uses_only_library_category_for_legacy_hosts():
    legacy_media = SimpleNamespace(
        media_source="themoviedb",
        media_id="123",
        library_category="电影/纪录片",
        metadata_category="来源分类/不得使用",
        classification=None,
    )
    metadata_only = SimpleNamespace(
        media_source="themoviedb",
        media_id="123",
        library_category="",
        category="",
        metadata_category="来源分类/不得使用",
        classification=None,
    )

    assert LunaTVSource._media_classification_snapshot(legacy_media) == {
        "media_source": "themoviedb",
        "media_id": "123",
        "media_category_id": None,
        "media_category": "电影/纪录片",
        "classification_rule_id": None,
        "classification_policy_revision": None,
        "classification_source": "legacy",
    }
    assert LunaTVSource._media_classification_snapshot(metadata_only) == {}


def test_task_persists_only_same_identity_classification(tmp_path: Path):
    plugin = object.__new__(LunaTVSource)
    task = _task(tmp_path)
    snapshot = {
        "media_source": "themoviedb",
        "media_id": "other-id",
        "media_category_id": "movie.animation",
        "media_category": "电影/动画",
        "classification_rule_id": "rule-animation",
        "classification_policy_revision": 17,
        "classification_source": "rule",
    }

    plugin._apply_task_classification(task, snapshot)
    assert task.media_category_id is None

    snapshot["media_id"] = "123"
    plugin._apply_task_classification(task, snapshot)
    restored = DownloadTask(**task.to_dict())

    assert (restored.host_media_source, restored.host_media_id) == (
        "themoviedb",
        "123",
    )
    assert restored.media_category_id == "movie.animation"
    assert restored.media_category == "电影/动画"
    assert restored.classification_rule_id == "rule-animation"
    assert restored.classification_policy_revision == 17
    assert restored.classification_source == "rule"


def test_record_native_history_writes_c3_classification_without_recognition(
    monkeypatch, tmp_path: Path
):
    histories = []
    files = []
    _install_history_modules(monkeypatch, histories, files, c3_model=True)

    class UnexpectedMediaChain:
        """Fail if completion attempts a new host recognition request."""

        def __init__(self):
            raise AssertionError("history completion must not recognize media again")

    monkeypatch.setattr(plugin_module, "_HostMediaChain", UnexpectedMediaChain)
    plugin = object.__new__(LunaTVSource)
    plugin._logger = plugin_module.LOGGER
    task = _task(
        tmp_path,
        media_category_id="movie.animation",
        media_category="电影/动画",
        classification_rule_id="rule-animation",
        classification_policy_revision=17,
        classification_source="rule",
    )
    output = str(tmp_path / "movie.mp4")

    plugin._record_native_history(task, output)

    expected_hash = hashlib.sha1(f"{task.task_id}|{output}".encode()).hexdigest()
    assert histories == [
        {
            "path": output,
            "type": "电影",
            "title": "分类电影",
            "year": "2026",
            "media_source": "themoviedb",
            "media_id": "123",
            "seasons": None,
            "episodes": None,
            "downloader": "LunaTVSource",
            "download_hash": expected_hash,
            "torrent_name": "分类电影",
            "torrent_description": "LunaTV m3u8 下载",
            "torrent_site": "cms-demo",
            "date": histories[0]["date"],
            "media_category_id": "movie.animation",
            "media_category": "电影/动画",
            "classification_rule_id": "rule-animation",
            "classification_policy_revision": 17,
            "classification_source": "rule",
        }
    ]
    assert "metadata_category" not in histories[0]
    assert files[0]["download_hash"] == expected_hash


def test_record_native_history_omits_c3_fields_on_legacy_host(
    monkeypatch, tmp_path: Path
):
    histories = []
    files = []
    _install_history_modules(monkeypatch, histories, files, c3_model=False)
    plugin = object.__new__(LunaTVSource)
    plugin._logger = plugin_module.LOGGER
    task = _task(
        tmp_path,
        media_category_id="movie.animation",
        media_category="电影/动画",
        classification_rule_id="rule-animation",
        classification_policy_revision=17,
        classification_source="rule",
    )

    plugin._record_native_history(task, str(tmp_path / "movie.mp4"))

    assert len(histories) == 1
    assert not {
        "media_category_id",
        "media_category",
        "classification_rule_id",
        "classification_policy_revision",
        "classification_source",
    }.intersection(histories[0])
