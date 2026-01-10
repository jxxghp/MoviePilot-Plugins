from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, HttpUrl

from .generics import ResourceItem, ResourceList
from .types import VehicleType


class RuleProvider(BaseModel):
    """Rule Provider"""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    type: VehicleType = Field(..., description="Provider type")
    url: Optional[HttpUrl] = Field(default=None, description="Must be configured if the type is http")
    path: Optional[str] = Field(default=None, description="Optional, file path, must be unique.")
    interval: Optional[int] = Field(default=None, ge=0, description="The update interval for the provider, in seconds.")
    proxy: Optional[str] = Field(default=None, description="Download/update through the specified proxy.")
    behavior: Optional[Literal["domain", "ipcidr", "classical"]] = Field(None,
                                                                         description="Behavior of the rule provider")
    format: Literal["yaml", "text", "mrs"] = Field("yaml", description="Format of the rule provider file")
    size_limit: int = Field(default=0, ge=0, alias="size-limit",
                            description="The maximum size of downloadable files in bytes (0 for no limit)")
    payload: Optional[List[str]] = Field(default=None, description="Content, only effective when type is inline")

    @model_validator(mode="before")
    @classmethod
    def validate_type_relationships(cls, values):
        """Perform cross-field validation before the model is created."""
        type_ = values.get('type')
        url = values.get('url')
        path = values.get('path')
        payload = values.get('payload')
        format_ = values.get('format', 'yaml')
        behavior = values.get('behavior')

        # url check
        if type_ == "http" and url is None:
            raise ValueError("url must be configured if the type is 'http'")
        if type_ != "http" and 'url' in values:
            values['url'] = None

        # path check
        if type_ == "file" and path is None:
            raise ValueError("path must be configured if the type is 'file'")
        if type_ != "file" and 'path' in values:
            values['path'] = None

        # payload handling
        if type_ == "inline":
            if payload is None:
                raise ValueError("payload must be configured if the type is 'inline'")
            if not isinstance(payload, list):
                raise ValueError("payload must be a list of strings when type is 'inline'")
        elif 'payload' in values:
            values['payload'] = None

        # format-behavior rule
        if format_ == "mrs" and behavior not in {"domain", "ipcidr"}:
            raise ValueError("mrs format only supports 'domain' or 'ipcidr' behavior")

        return values


class RuleProviderData(ResourceItem[RuleProvider]):
    """Rule Provider Data"""
    pass


class RuleProviders(ResourceList[RuleProviderData]):
    """Rule Providers Collection"""
    pass
