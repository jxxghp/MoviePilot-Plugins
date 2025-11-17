from enum import Enum
from typing import Optional, List, Tuple, Union

from pydantic import BaseModel, Field, ConfigDict

from .imdbapi import ImdbApiTitle, ImdbApiEpisode, ImdbApiCredit
from .imdbtypes import ImdbTitle, ImdbName, ImdbImage, ImdbVideo, AkasNode, TitleEdge


class ErrorType(Enum):
    PERSISTED_QUERY_NOT_FOUND = 'PERSISTED_QUERY_NOT_FOUND'


class StaffPickEntry(BaseModel):
    name: str
    ttconst: str
    rmconst: str
    detail: Optional[str] = ""
    description: Optional[str] = ""
    relatedconst: List[str] = Field(default_factory=list)
    viconst: Optional[str] = None


class VerticalList(BaseModel):
    titles: List[ImdbTitle] = Field(default_factory=list)
    names: List[ImdbName] = Field(default_factory=list)
    videos: List[ImdbVideo] = Field(default_factory=list)
    images: List[ImdbImage] = Field(default_factory=list)


class StaffPickApiResponse(BaseModel):
    updated_at: Optional[str]
    entries: List[StaffPickEntry] = Field(default_factory=list)
    imdb_items: VerticalList


class ImdbMediaInfo(ImdbApiTitle):
    akas: List[AkasNode] = Field(default_factory=list)
    episodes: List[ImdbApiEpisode] = Field(default_factory=list)
    credits: List[ImdbApiCredit] = Field(default_factory=list)

    @classmethod
    def from_title(
        cls,
        title: ImdbApiTitle,
        akas: Optional[List[AkasNode]] = None,
        episodes: Optional[List[ImdbApiEpisode]] = None,
        api_credits: Optional[List[ImdbApiCredit]] = None,
    ) -> "ImdbMediaInfo":
        return cls(
            **title.model_dump(exclude_none=True, by_alias=True),
            akas=akas if akas is not None else [],
            episodes=episodes if episodes is not None else [],
            credits=api_credits if api_credits is not None else []
        )


class ImdbApiHash(BaseModel):
    advanced_title_search: str = Field(alias="AdvancedTitleSearch")


class PageInfo(BaseModel):
    has_previous_page: Optional[bool] = Field(None, alias="hasPreviousPage")
    has_next_page: Optional[bool] = Field(None, alias="hasNextPage")
    start_cursor: Optional[str] = Field(None, alias="startCursor")
    end_cursor: Optional[str] = Field(None, alias="endCursor")


class FilterInfo(BaseModel):
    filter_id: Optional[str] = Field(default=None, alias='filterId')
    text: Optional[str] = Field(default=None, alias='text')
    total: Optional[int] = Field(default=None, alias='total')


class SearchState(BaseModel):
    total: int = 0
    page_info: PageInfo = Field(default_factory=PageInfo, alias="pageInfo")
    genres: List[FilterInfo] = Field(default_factory=list)
    keywords: List[FilterInfo] = Field(default_factory=list)
    title_types: List[FilterInfo] = Field(default_factory=list, alias='titleTypes')


class AdvancedTitleSearch(SearchState):
    edges: List[TitleEdge] = Field(default_factory=list)


class AdvancedTitleSearchResponse(BaseModel):
    advanced_title_search: AdvancedTitleSearch = Field(default_factory=AdvancedTitleSearch, alias="advancedTitleSearch")


class SearchParams(BaseModel):
    title_types: Optional[Tuple[str, ...]] = None
    genres: Optional[Tuple[str, ...]] = None
    sort_by: str = 'POPULARITY'
    sort_order: str = 'ASC'
    rating_min: Optional[float] = None
    rating_max: Optional[float] = None
    countries: Optional[Tuple[str, ...]] = None
    languages: Optional[Tuple[str, ...]] = None
    release_date_end: Optional[str] = None
    release_date_start: Optional[str] = None
    award_constraint: Optional[Tuple[str, ...]] = None
    ranked: Optional[Tuple[str, ...]] = None
    interests: Optional[Tuple[str, ...]] = None

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=False
    )


class ErrorExtension(BaseModel):
    code: Union[ErrorType, str]
    error_type: str = Field('CLIENT', alias='errorType')
    is_retryable: bool = Field(False, alias='isRetryable')


class ErrorValue(BaseModel):
    message: Optional[str] = Field(default=None, alias='message')
    extensions: Optional[ErrorExtension]


class ErrorResponse(BaseModel):
    errors: Optional[List[ErrorValue]] = Field(default_factory=list)
