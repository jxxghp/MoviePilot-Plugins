from app.plugins.musiclibrarymanager.matching import (
    Work,
    collection_search_terms,
    evaluate_coverage,
    is_collection_resource,
    useful_artist_aliases,
)


def test_collection_search_terms_reject_short_latin_alias():
    aliases = useful_artist_aliases("周杰伦", ["Jay", "Jay Chou", "周杰倫"])
    assert "Jay" not in aliases
    assert collection_search_terms("周杰伦", aliases) == [
        "周杰伦",
        "Jay Chou",
        "周杰倫",
        "周杰伦 合集",
    ]


def test_collection_resource_requires_artist_and_collection_signal():
    assert is_collection_resource(
        "Taylor Swift Discography 2006-2024", "FLAC", ["Taylor Swift"]
    )
    assert not is_collection_resource(
        "Taylor Swift - Midnights", "FLAC", ["Taylor Swift"]
    )
    assert not is_collection_resource(
        "Adele Complete Collection", "FLAC", ["Taylor Swift"]
    )
    assert not is_collection_resource("Madeleine Collection", "FLAC", ["Adele"])
    assert is_collection_resource("Taylor.Swift.Pack", "FLAC", ["Taylor Swift"])


def test_coverage_only_file_path_is_confirmed():
    works = [
        Work(media_id="a", title="七里香", year=2004),
        Work(media_id="b", title="十一月的萧邦", year=2005),
        Work(media_id="c", title="惊叹号", year=2011),
    ]
    result = evaluate_coverage(
        works,
        ["周杰伦/2004 七里香/01 我的地盘.flac"],
        "周杰伦 2004-2010 专辑合集",
    )
    rows = {row["media_id"]: row for row in result["works"]}
    assert rows["a"]["state"] == "confirmed"
    assert rows["b"]["state"] == "probable"
    assert rows["c"]["state"] == "missing"
    assert result["confirmed_count"] == 1
    assert rows["a"]["title"] == "七里香"
    assert rows["a"]["album_type"] == "Album"


def test_ambiguous_same_title_needs_year_evidence():
    works = [
        Work(media_id="old", title="同名专辑", year=2001),
        Work(media_id="new", title="同名专辑", year=2020),
    ]
    result = evaluate_coverage(works, ["同名专辑/01.flac"], "合集")
    assert all(row["state"] != "confirmed" for row in result["works"])


def test_album_name_in_collection_root_or_track_is_not_album_evidence():
    work = Work(media_id="album", title="Red", year=2012)
    result = evaluate_coverage(
        [work], ["Taylor Swift Red Collection/01 Red.flac"], "Taylor Swift collection"
    )
    assert result["confirmed_count"] == 0


def test_partial_title_and_same_year_album_single_are_not_confirmed():
    works = [Work("red", "Red", 2012), Work("red-single", "Red", 2012, "Single")]
    result = evaluate_coverage(
        works, ["Taylor Swift/2012 Red/01 Red.flac"], "Taylor Swift collection"
    )
    assert result["confirmed_count"] == 0
    result = evaluate_coverage(
        [Work("a", "Love")], ["Artist/Love Story/01.flac"], "Artist Collection"
    )
    assert result["confirmed_count"] == 0
