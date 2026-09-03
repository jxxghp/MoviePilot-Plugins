from typing import Optional, List

from pydantic import BaseModel, Field

from .imdbtypes import ImdbType, RatingsSummary, AkasNode, ImdbDate


class ImdbapiImage(BaseModel):
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    type: Optional[str] = None


class ImdbApiMetacritic(BaseModel):
    url: Optional[str] = None
    score: Optional[int] = None
    review_count: Optional[int] = Field(None, alias='reviewCount')


class ImdbApiMeterRanking(BaseModel):
    current_rank: Optional[int] = Field(None, alias='currentRank')
    change_direction: Optional[str] = Field(None, alias='changeDirection')
    difference: Optional[int] = None


class ImdbApiPerson(BaseModel):
    id: Optional[str] = None
    display_name: Optional[str] = Field(None, alias='displayName')
    alternative_names: Optional[List[str]] = Field(None, alias='alternativeNames')
    primary_image: Optional[ImdbapiImage] = Field(None, alias='primaryImage')
    primary_professions: Optional[List[str]] = Field(None, alias='primaryProfessions')
    biography: Optional[str] = None
    height_cm: Optional[float] = Field(None, alias='heightCm')
    birth_name: Optional[str] = Field(None, alias='birthName')
    birth_date: Optional[ImdbDate] = Field(None, alias='birthDate')
    birth_location: Optional[str] = Field(None, alias='birthLocation')
    death_date: Optional[ImdbDate] = Field(None, alias='deathDate')
    death_location: Optional[str] = Field(None, alias='deathLocation')
    death_reason: Optional[str] = Field(None, alias='deathReason')
    meter_ranking: Optional[ImdbApiMeterRanking] = Field(None, alias='meterRanking')


class ImdbApiCountry(BaseModel):
    # The ISO 3166-1 alpha-2 country code for the title, (e.g. "US" for the United States, "JP" for Japan)
    code: Optional[str] = None
    # The name of the country in English.
    name: Optional[str] = None


class ImdbApiLanguage(BaseModel):
    # The ISO 639-3 language code for the title, (e.g. "eng" for English, "jpn" for Japanese)
    code: Optional[str] = None
    # The name of the language in English.
    name: Optional[str] = None


class ImdbapiPrecisionDate(BaseModel):
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None


class ImdbApiInterest(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    primary_image: Optional[ImdbapiImage] = Field(None, alias='primaryImage')
    description: Optional[str] = None
    is_subgenre: Optional[bool] = Field(None, alias='isSubgenre')
    similar_interests: Optional[List['ImdbApiInterest']] = Field(None, alias='similarInterests')


class ImdbApiTitle(BaseModel):
    id: str
    type: ImdbType
    is_adult: Optional[bool] = Field(None, alias='isAdult')
    primary_title: Optional[str] = Field(None, alias='primaryTitle')
    original_title: Optional[str] = Field(None, alias='originalTitle')
    primary_image: Optional[ImdbapiImage] = Field(None, alias='primaryImage')
    start_year: Optional[int] = Field(None, alias='startYear')
    end_year: Optional[int] = Field(None, alias='endYear')
    runtime_seconds: Optional[int] = Field(None, alias='runtimeSeconds')
    genres: Optional[List[str]] = None
    rating: Optional[RatingsSummary] = None
    metacritic: Optional[ImdbApiMetacritic] = None
    plot: Optional[str] = None
    directors: Optional[List[ImdbApiPerson]] = Field(default_factory=list)
    writers: Optional[List[ImdbApiPerson]] = Field(default_factory=list)
    stars: Optional[List[ImdbApiPerson]] = Field(default_factory=list)
    origin_countries: Optional[List[ImdbApiCountry]] = Field(default_factory=list, alias='originCountries')
    spoken_languages: Optional[List[ImdbApiLanguage]] = Field(default_factory=list, alias='spokenLanguages')
    interests: Optional[List[ImdbApiInterest]] = None


class ImdbApiSearchTitlesResponse(BaseModel):
    titles: List[ImdbApiTitle]


class ImdbApiListTitlesResponse(BaseModel):
    titles: List[ImdbApiTitle] = Field(default_factory=list)
    total_count: int = Field(alias='totalCount')
    next_page_token: Optional[str] = Field(None, alias='nextPageToken')


class ImdbApiEpisode(BaseModel):
    id: str
    title: Optional[str] = None
    primary_image: Optional[ImdbapiImage] = Field(None, alias='primaryImage')
    season: Optional[str] = Field(None, alias='season')
    episode_number: Optional[int] = Field(None, alias='episodeNumber')
    runtime_seconds: Optional[int] = Field(None, alias='runtimeSeconds')
    plot: Optional[str] = Field(None, alias='plot')
    rating: Optional[RatingsSummary] = Field(None, alias='rating')
    release_date: Optional[ImdbapiPrecisionDate] = Field(None, alias='releaseDate')


class PagedResponse(BaseModel):
    total_count: int = Field(alias='totalCount')
    next_page_token: Optional[str] = Field(None, alias='nextPageToken')


class ImdbApiListTitleEpisodesResponse(PagedResponse):
    episodes: List[ImdbApiEpisode] = Field(default_factory=list)


class ImdbApiSeason(BaseModel):
    season: Optional[str] = None
    episode_count: Optional[int] = Field(None, alias='episodeCount')


class ImdbApiListTitleSeasonsResponse(BaseModel):
    seasons: List[ImdbApiSeason] = Field(default_factory=list)


class ImdbApiCredit(BaseModel):
    title: Optional[ImdbApiTitle] = None
    name: Optional[ImdbApiPerson] = None
    category: Optional[str] = None
    characters: Optional[List[str]] = None
    episode_count: Optional[int] = Field(None, alias='episodeCount')


class ImdbApiListTitleCreditsResponse(PagedResponse):
    credits: List[ImdbApiCredit] = Field(default_factory=list)


class ImdbapiAka(AkasNode):
    attributes: List[str] = Field(default_factory=list)


class ImdbapiListTitleAKAsResponse(BaseModel):
    akas: List[ImdbapiAka]


class ImdbApiTitleImagesResponse(PagedResponse):
    images: List[ImdbapiImage] = Field(default_factory=list)


class ImdbapiCompany(BaseModel):
    id: str
    name: str


class ImdbapiCompanyCredit(BaseModel):
    company: ImdbapiCompany
    category: Optional[str] = Field(
        default=None,
        description="Category of the company credit, such as production, sales, distribution, etc."
    )


class ImdbapiCompanyCreditResponse(PagedResponse):
    company_credits: List[ImdbapiCompanyCredit] = Field(default_factory=list, alias='companyCredits')
