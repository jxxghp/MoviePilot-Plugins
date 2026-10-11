import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.plugins.musiclibrarymanager import MusicLibraryManager, require_manage_user
from app.plugins.musiclibrarymanager.schemas import (
    CompletionDownloadItem,
    NormalizationPreviewRequest,
)
from app.plugins.musiclibrarymanager.service import (
    MusicLibraryService,
    _candidate_key,
    _library_state,
    _public_torrent,
)
from app.schemas.mediaserver import MediaServerItem
from app.schemas.types import MediaSource
from app.sdk.media import Context, MusicInfo, TorrentInfo
from fastapi import HTTPException

ARTIST_ID = "e5d8c705-8ea4-4820-b11d-fbf580d85ce4"


def plugin():
    owner = MusicLibraryManager.__new__(MusicLibraryManager)
    owner.init_plugin({"enabled": True})
    owner.get_data = Mock(return_value=[])
    owner.save_data = Mock()
    return owner


def context():
    return Context(
        torrent_info=TorrentInfo(
            title="Taylor Swift Discography",
            site_name="Example",
            enclosure="https://private.invalid/download?passkey=secret",
            site_cookie="secret",
            site_ua="secret-agent",
            site_proxy=True,
        )
    )


def service(owner=None):
    instance = MusicLibraryService.__new__(MusicLibraryService)
    instance.owner = owner or plugin()
    instance.download = Mock()
    return instance


def cache(owner, key="candidate", kind="collection", media=None):
    owner.cache_candidate(
        key,
        context(),
        artist={"media_id": ARTIST_ID, "name": "Taylor Swift"},
        kind=kind,
        media=media,
    )


def test_public_torrent_never_exposes_credentials_or_download_ticket():
    public = _public_torrent(context().torrent_info)
    assert set(public) == {"title", "description", "site_name", "size", "seeders"}
    assert "secret" not in str(public)


def test_candidate_key_is_scoped_to_mode_and_work():
    assert _candidate_key(context(), "collection:a") != _candidate_key(
        context(), "completion:a"
    )
    assert _candidate_key(context(), "completion:a") != _candidate_key(
        context(), "completion:b"
    )


@pytest.mark.parametrize(
    "artist,kind,media_id",
    [
        ("other", "collection", None),
        (ARTIST_ID, "completion", None),
        (ARTIST_ID, "collection", "other"),
    ],
)
def test_candidates_cannot_change_artist_mode_or_work(artist, kind, media_id):
    owner = plugin()
    cache(owner)
    with pytest.raises(HTTPException) as error:
        owner.take_candidate(
            "candidate", artist_id=artist, kind=kind, media_id=media_id
        )
    assert error.value.status_code == 422
    assert owner.take_candidate("candidate", artist_id=ARTIST_ID, kind="collection")


def test_candidate_consumed_once_and_cleared_on_stop_and_reinit():
    owner = plugin()
    cache(owner)
    owner.take_candidate("candidate", artist_id=ARTIST_ID, kind="collection")
    with pytest.raises(HTTPException):
        owner.take_candidate("candidate", artist_id=ARTIST_ID, kind="collection")
    cache(owner)
    owner.stop_service()
    cache(owner)  # a late search must not restore credentials after stop
    assert owner._candidate_cache == {}
    owner.init_plugin({"enabled": True})
    assert owner._candidate_cache == {}


def test_expired_and_bounded_cache():
    owner = plugin()
    owner._MAX_CANDIDATES = 2
    for key in ("one", "two", "three"):
        cache(owner, key)
    assert set(owner._candidate_cache) == {"two", "three"}
    owner._CANDIDATE_TTL = 0
    with pytest.raises(HTTPException):
        owner.take_candidate("three", artist_id=ARTIST_ID, kind="collection")


def test_collection_submits_only_one_and_uses_server_artist_identity():
    owner = plugin()
    cache(owner)
    instance = service(owner)
    instance.download.download_single.return_value = ("hash", None)
    job = instance.download_collection(
        ARTIST_ID, "A different artist", "candidate", None, None
    )
    assert job["submitted"] == 1
    instance.download.download_single.assert_called_once()
    submitted = instance.download.download_single.call_args.kwargs["context"].media_info
    assert submitted.artists == ["Taylor Swift"]
    assert submitted.album_type == "Artist Collection"
    assert "secret" not in str(owner.save_data.call_args)


def test_invalid_batch_rejected_before_any_download():
    owner = plugin()
    media = MusicInfo(
        media_source=MediaSource.MusicBrainz,
        media_id="work",
        title="Album",
        artists=["Taylor Swift"],
        music_type="album",
    ).to_dict()
    cache(owner, kind="completion", media=media)
    instance = service(owner)
    instance.library_inventory = Mock(return_value=([], True))
    with pytest.raises(HTTPException):
        instance.download_completion(
            ARTIST_ID,
            "Taylor Swift",
            [
                CompletionDownloadItem(media_id="work", candidate_key="candidate"),
                CompletionDownloadItem(media_id="wrong", candidate_key="invalid"),
            ],
            None,
            None,
        )
    instance.download.download_single.assert_not_called()


def test_completion_rechecks_library_and_refuses_unknown():
    owner = plugin()
    media = MusicInfo(
        media_source=MediaSource.MusicBrainz,
        media_id="work",
        title="Album",
        artists=["Taylor Swift"],
        music_type="album",
    ).to_dict()
    cache(owner, kind="completion", media=media)
    instance = service(owner)
    instance.library_inventory = Mock(return_value=([], False))
    job = instance.download_completion(
        ARTIST_ID,
        "Taylor Swift",
        [
            CompletionDownloadItem(media_id="work", candidate_key="candidate"),
        ],
        None,
        None,
    )
    assert job["submitted"] == 0
    assert job["failed"] == 1
    instance.download.download_single.assert_not_called()


def test_unknown_is_not_missing_and_existing_is_not_selected():
    media = MusicInfo(title="Midnights", artists=["Taylor Swift"], music_type="album")
    item = MediaServerItem(
        title="Midnights", note={"artist": "Taylor Swift", "song_count": 13}
    )
    assert _library_state(media, [], False) == "unknown"
    assert _library_state(media, [], True) == "missing"
    assert _library_state(media, [item], False) == "present"


@pytest.mark.parametrize(
    "count,items,complete", [(0, [], True), (1, [], False), (None, [], False)]
)
def test_inventory_requires_successful_full_scan(count, items, complete):
    instance = service()
    instance.server_configs = Mock()
    instance.server_configs.get_configs.return_value = {"server": object()}
    instance.servers = Mock()
    instance.servers.librarys.return_value = [SimpleNamespace(type="音乐", id="music")]
    instance.servers.items_count.return_value = count
    instance.servers.items.return_value = iter(items)
    assert instance.library_inventory()[1] is complete


def test_no_music_library_or_provider_failure_is_unknown():
    instance = service()
    instance.server_configs = Mock()
    instance.server_configs.get_configs.return_value = {}
    assert instance.library_inventory() == ([], False)
    instance.server_configs.get_configs.return_value = {"server": object()}
    instance.servers = Mock()
    instance.servers.librarys.side_effect = RuntimeError("offline")
    assert instance.library_inventory() == ([], False)


def plan_request(**kwargs):
    return NormalizationPreviewRequest(
        hash="abc",
        downloader="qb",
        category="Album",
        artist="Eagles",
        title="Hotel California",
        **kwargs,
    )


def test_normalization_is_strictly_preview_only_even_with_rename_api():
    instance = service()
    request = plan_request(
        execute=True,
        expected_save_path="/downloads",
        expected_content_path="/downloads/old",
    )
    with pytest.raises(HTTPException) as error:
        instance.normalization_plan(request)
    assert error.value.status_code == 409
    assert instance.download.mock_calls == []


def test_preview_keeps_location_without_archive_root_and_preserves_single_file_extension():
    instance = service()
    instance.download.list_torrents.return_value = [
        SimpleNamespace(
            save_path="/music/Single/Eagles",
            content_path="/music/Single/Eagles/ugly.flac",
        )
    ]
    instance.download.torrent_files.return_value = [SimpleNamespace(name="ugly.flac")]
    plan = instance.normalization_plan(plan_request())
    assert (
        plan["target_content_path"]
        == "/music/Single/Eagles/Eagles - Hotel California.flac"
    )
    assert not plan["executable"] and not plan["executed"]


@pytest.mark.parametrize(
    "path", ["relative", "/downloads/../outside", "//server/share", "/bad\x00"]
)
def test_reject_invalid_archive_paths(path):
    owner = plugin()
    with pytest.raises(HTTPException):
        owner.collection_save_path("artist", path)


def test_collection_artist_path_component_cannot_escape_root():
    owner = plugin()
    owner._source_root = "/music"
    assert (
        owner.collection_save_path("../../A/B", None) == "/music/Artist Collection/A B"
    )


def test_permission_guard_checks_live_account(monkeypatch):
    from app.plugins.musiclibrarymanager import UserOper
    from app.schemas.token import TokenPayload

    monkeypatch.setattr(
        UserOper,
        "async_get_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                is_active=True,
                is_superuser=False,
                permissions={"manage": False},
            )
        ),
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_manage_user(TokenPayload(sub=1)))
    assert error.value.status_code == 403


def test_completion_skips_present_unknown_and_caches_only_exact_target():
    owner = plugin()
    instance = service(owner)
    media = MusicInfo(
        media_source=MediaSource.MusicBrainz,
        media_id="work",
        title="Album",
        artists=["Taylor Swift"],
        music_type="album",
    )
    artist = {"media_id": ARTIST_ID, "name": "Taylor Swift"}
    instance.catalog = AsyncMock(
        return_value=(
            artist,
            [
                {"media": media.to_dict(), "library_state": "missing"},
                {"media": {"media_id": "present"}, "library_state": "present"},
                {"media": {"media_id": "unknown"}, "library_state": "unknown"},
            ],
            False,
        )
    )
    exact = context()
    exact.match_status = "exact"
    exact.media_info = media
    uncertain = context()
    uncertain.match_status = None
    instance.search = SimpleNamespace(
        async_search_by_id=AsyncMock(return_value=[exact, uncertain])
    )
    result = asyncio.run(instance.completion(ARTIST_ID, None))
    instance.search.async_search_by_id.assert_awaited_once()
    assert len(result["items"]) == 1
    assert result["present_count"] == 1 and result["unknown_count"] == 1
    assert [item["exact"] for item in result["items"][0]["resources"]] == [True, False]
    assert len(owner._candidate_cache) == 1


def test_collection_search_uses_verified_artist_and_probes_without_download():
    owner = plugin()
    instance = service(owner)
    artist = {"media_id": ARTIST_ID, "name": "Taylor Swift", "aliases": []}
    instance.catalog = AsyncMock(return_value=(artist, [], False))
    instance.search = SimpleNamespace(
        async_search_by_title=AsyncMock(return_value=[context()])
    )
    instance.download.download_torrent.return_value = (b"metadata", "Taylor Swift", [])
    items, terms = asyncio.run(instance.collections(ARTIST_ID, "Adele", None, 8))
    assert "Taylor Swift" in terms and not any("Adele" in term for term in terms)
    assert len(items) == 1
    instance.download.download_single.assert_not_called()
    assert len(owner._candidate_cache) == 1
