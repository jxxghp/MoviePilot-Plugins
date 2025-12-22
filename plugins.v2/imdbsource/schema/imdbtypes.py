from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


class ImdbType(Enum):
    TV_SERIES = "tvSeries"
    TV_MINI_SERIES = "tvMiniSeries"
    MOVIE = "movie"
    TV_MOVIE = "tvMovie"
    MUSIC_VIDEO = "musicVideo"
    TV_SHORT = "tvShort"
    SHORT = "short"
    TV_EPISODE = "tvEpisode"
    TV_SPECIAL = "tvSpecial"
    VIDEO_GAME = "videoGame"
    VIDEO = "video"
    PODCAST_SERIES = "podcastSeries"
    PODCAST_EPISODE = "podcastEpisode"


class TitleType(BaseModel):
    id: ImdbType


class ReleaseYear(BaseModel):
    year: Optional[int] = None


class Country(BaseModel):
    id: str
    text: str


class TextField(BaseModel):
    text: Optional[str] = ''


class ValueField(BaseModel):
    value: Optional[str] = None


class SecondsField(BaseModel):
    seconds: Optional[int] = None


class AkasNode(BaseModel):
    text: Optional[str] = ''
    country: Optional[Country] = None
    language: Optional[TextField] = None


class AkasEdge(BaseModel):
    node: AkasNode


class Akas(BaseModel):
    edges: List[AkasEdge] = Field(default_factory=list)


class PlotText(BaseModel):
    plain_text: Optional[str] = Field(default='', alias='plainText')


class Plot(BaseModel):
    plot_text: Optional[PlotText] = Field(None, alias='plotText')


class ImdbImage(BaseModel):
    id: str
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

    def poster_path(self):
        if self.url:
            return self.url.replace('@._V1', '@._V1_QL75_UY414_CR6,0,280,414_')
        return None


class RankChange(BaseModel):
    change_direction: Optional[str] = Field(default=None, alias='changeDirection')
    difference: Optional[int] = None


class MeterRanking(BaseModel):
    current_rank: Optional[int] = Field(default=None, alias='currentRank')
    meter_type: Optional[str] = Field(default=None, alias='meterType')
    rank_change: Optional[RankChange] = Field(default=None, alias='rankChange')


class RatingsSummary(BaseModel):
    aggregate_rating: Optional[float] = Field(default=None, alias='aggregateRating')
    vote_count: Optional[int] = Field(None, alias='voteCount')


class ImdbName(BaseModel):
    id: str
    name_text: TextField = Field(alias='nameText')
    primary_image: Optional[ImdbImage] = Field(default=None, alias='primaryImage')


class ContentType(BaseModel):
    display_name: ValueField = Field(alias='displayName')
    id: str


class VideoUrl(BaseModel):
    display_name: ValueField = Field(alias='displayName')
    url: str
    video_definition: str = Field(alias='videoDefinition')
    video_mime_type: str = Field(alias='videoMimeType')


class ImdbDate(BaseModel):
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None


class Genre(BaseModel):
    genre: Optional[TextField] = None


class TitleGenre(BaseModel):
    genres: List[Genre] = Field(default_factory=list)


class Certificate(BaseModel):
    rating: Optional[str] = None


class ImdbTitle(BaseModel):
    id: str
    title_text: TextField = Field(alias='titleText')
    title_type: TitleType = Field(alias='titleType')
    release_year: Optional[ReleaseYear] = Field(None, alias='releaseYear')
    akas: Optional[Akas] = None
    plot: Optional[Plot] = None
    primary_image: Optional[ImdbImage] = Field(default=None, alias='primaryImage')
    meter_ranking: Optional[MeterRanking] = Field(default=None, alias='meterRanking')
    ratings_summary: Optional[RatingsSummary] = Field(default=None, alias='ratingsSummary')
    release_date: Optional[ImdbDate] = Field(None, alias='releaseDate')
    title_genres: Optional[TitleGenre] = Field(default=None, alias='titleGenres')
    certificate: Optional[Certificate] = None
    original_title_text: Optional[TextField] = Field(default=None, alias='originalTitleText')
    runtime: Optional[SecondsField] = Field(default=None, alias='runtime')

    @property
    def plot_text(self) -> str:
        return self.plot.plot_text.plain_text if self.plot and self.plot.plot_text else ''

    @property
    def rating_text(self) -> str:
        if self.ratings_summary and self.ratings_summary.aggregate_rating:
            return f"{self.ratings_summary.aggregate_rating:.1f}"
        return "-"

class Thumbnail(BaseModel):
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class ImdbVideo(BaseModel):
    id: str
    name: ValueField
    content_type: ContentType = Field(alias='contentType')
    preview_urls: List[VideoUrl] = Field(default_factory=list, alias='previewURLs')
    playback_urls: List[VideoUrl] = Field(default_factory=list, alias='playbackURLs')
    thumbnails: Optional[Thumbnail] = None


class TitleNode(BaseModel):
    title: ImdbTitle


class TitleEdge(BaseModel):
    node: TitleNode
