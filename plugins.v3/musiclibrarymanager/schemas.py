"""音乐资源管理插件 API 模型。"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ApiStatus(BaseModel):
    success: bool = True
    message: str = ""


class PluginStatus(BaseModel):
    enabled: bool
    source: str = "MusicBrainz"
    capabilities: dict[str, bool] = Field(default_factory=dict)
    jobs: list[dict[str, Any]] = Field(default_factory=list)


class ArtistSummary(BaseModel):
    media_source: str
    media_id: str
    name: str
    sort_name: str | None = None
    disambiguation: str | None = None
    artist_type: str | None = None
    country: str | None = None
    aliases: list[str] = Field(default_factory=list)
    image_url: str | None = None


class ArtistSearchResponse(BaseModel):
    items: list[ArtistSummary] = Field(default_factory=list)


class CatalogWork(BaseModel):
    media: dict[str, Any]
    library_state: Literal["present", "missing", "unknown"] = "unknown"


class ArtistCatalogResponse(BaseModel):
    artist: ArtistSummary
    works: list[CatalogWork] = Field(default_factory=list)
    library_status_complete: bool = False


class CoverageRow(BaseModel):
    media_id: str
    title: str
    year: int | None = None
    album_type: str = "Album"
    state: Literal["confirmed", "probable", "missing"]
    evidence: str = ""


class Coverage(BaseModel):
    folder_name: str = ""
    file_count: int = 0
    confirmed_count: int = 0
    probable_count: int = 0
    missing_count: int = 0
    works: list[CoverageRow] = Field(default_factory=list)


class CollectionCandidate(BaseModel):
    key: str
    title: str
    description: str = ""
    site_name: str = ""
    size: float = 0
    seeders: int = 0
    page_url: str | None = None
    coverage: Coverage


class CollectionSearchResponse(BaseModel):
    items: list[CollectionCandidate] = Field(default_factory=list)
    searched_terms: list[str] = Field(default_factory=list)


class ResourceCandidate(BaseModel):
    key: str
    title: str
    description: str = ""
    site_name: str = ""
    size: float = 0
    seeders: int = 0
    exact: bool = False


class CompletionWork(BaseModel):
    media: dict[str, Any]
    library_state: Literal["present", "missing", "unknown"] = "unknown"
    resources: list[ResourceCandidate] = Field(default_factory=list)


class CompletionResponse(BaseModel):
    items: list[CompletionWork] = Field(default_factory=list)
    present_count: int = 0
    unknown_count: int = 0
    library_status_complete: bool = False


class CollectionDownloadRequest(BaseModel):
    artist_id: str = Field(min_length=1)
    artist_name: str = Field(min_length=1)
    candidate_key: str = Field(min_length=1)
    downloader: str | None = None
    save_path: str | None = None


class CompletionDownloadItem(BaseModel):
    media_id: str = Field(min_length=1)
    candidate_key: str = Field(min_length=1)


class CompletionDownloadRequest(BaseModel):
    artist_id: str = Field(min_length=1)
    artist_name: str = Field(min_length=1)
    items: list[CompletionDownloadItem] = Field(min_length=1, max_length=100)
    downloader: str | None = None
    save_path: str | None = None


class DownloadJob(BaseModel):
    job_id: str
    kind: Literal["collection", "completion"]
    state: Literal["submitted", "partial", "failed"]
    artist_id: str
    artist_name: str
    total: int
    submitted: int
    failed: int
    results: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


class TorrentTask(BaseModel):
    hash: str
    downloader: str
    title: str
    save_path: str
    content_path: str
    state: str = ""
    progress: float = 0


class NormalizationPreviewRequest(BaseModel):
    hash: str = Field(min_length=1)
    downloader: str = Field(min_length=1)
    category: Literal["Album", "EP", "Single", "Artist Collection"]
    artist: str = Field(min_length=1)
    title: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1000, le=2999)
    archive_root: str | None = None
    execute: bool = False
    expected_save_path: str | None = None
    expected_content_path: str | None = None

    @model_validator(mode="after")
    def validate_execute(self) -> "NormalizationPreviewRequest":
        if self.execute and (
            not self.expected_save_path or not self.expected_content_path
        ):
            raise ValueError("执行前必须带回预览中的路径快照")
        return self


class NormalizationPlan(BaseModel):
    hash: str
    downloader: str
    current_save_path: str
    current_content_path: str
    target_save_path: str
    proposed_root_name: str
    target_content_path: str
    move_required: bool
    rename_required: bool
    rename_supported: bool
    executable: bool
    executed: bool = False
    message: str = ""
