from app.plugins.lunatvsource.naming import media_path, normalize_media_title, normalize_search_title, safe_component


def test_safe_component_removes_path_separators():
    assert safe_component("A/B:C") == "A B C"


def test_normalize_titles_removes_bundle_metadata_but_keeps_year():
    assert normalize_media_title("海底小纵队中文版 (1-8季)") == "海底小纵队"
    assert normalize_media_title("小猪佩奇 第一季 第52集") == "小猪佩奇"
    assert normalize_media_title("小猪佩奇 第八季 第45集") == "小猪佩奇"
    assert normalize_media_title("小猪佩奇 第十季 中文版") == "小猪佩奇"
    assert normalize_media_title("小猪佩奇 第12季 国语版") == "小猪佩奇"
    assert normalize_media_title("小猪佩奇过大年(粤语版)") == "小猪佩奇过大年"
    assert normalize_media_title("英语老师 第一季") == "英语老师"
    assert normalize_media_title("粤语版的故事") == "粤语版的故事"
    assert normalize_media_title("示例剧 S02E03") == "示例剧"
    assert normalize_search_title("示例剧 [1080P 中文字幕]") == "示例剧"


def test_movie_path_uses_year():
    directory, filename = media_path("/media/incoming", "示例电影", "2025", "movie", 1, 1, "x.m3u8")
    assert directory == "示例电影 (2025)"
    assert filename == "示例电影 (2025).mp4"


def test_tv_path_contains_season_and_episode():
    directory, filename = media_path("/media/incoming", "示例剧", "2024", "tv", 8, 3, "x.m3u8")
    assert directory == "示例剧 (2024)/Season 08"
    assert filename == "示例剧 (2024) - S08E03.mp4"


def test_strm_path_keeps_url_as_file_content_later():
    directory, filename = media_path("/media/incoming", "示例剧", "2024", "tv", 1, 1, "x.m3u8", mode="strm")
    assert directory.endswith("Season 01")
    assert filename.endswith(".strm")
