from typing import List, Optional, Literal

from pydantic import BaseModel, Field, validator, HttpUrl


class RuleProvider(BaseModel):
    type: Literal["http", "file", "inline"] = Field(..., description="Provider type")
    url: Optional[HttpUrl] = Field(None, description="Must be configured if the type is http")
    path: Optional[str] = Field(None, description="Optional, file path, must be unique.")
    interval: Optional[int] = Field(None, ge=0, description="The update interval for the provider, in seconds.")
    proxy: Optional[str] = Field(None, description="Download/update through the specified proxy.")
    behavior: Optional[Literal["domain", "ipcidr", "classical"]] = Field(None,
                                                                         description="Behavior of the rule provider")
    format: Literal["yaml", "text", "mrs"] = Field("yaml", description="Format of the rule provider file")
    size_limit: int = Field(0, ge=0, description="The maximum size of downloadable files in bytes (0 for no limit)",
                            alias="size-limit")
    payload: Optional[List[str]] = Field(None, description="Content, only effective when type is inline")

    @validator("url", pre=True, always=True, allow_reuse=True)
    def check_url_for_http_type(cls, v, values):
        if values.get("type") == "http" and v is None:
            raise ValueError("url must be configured if the type is 'http'")
        elif values.get("type") != "http":
            return None
        return v

    @validator("path", pre=True, always=True, allow_reuse=True)
    def check_path_for_file_type(cls, v, values):
        if values.get("type") == "file" and v is None:
            raise ValueError("path must be configured if the type is 'file'")
        elif values.get("type") != "file":
            return None
        return v

    @validator("payload", pre=True, always=True, allow_reuse=True)
    def handle_payload_for_non_inline_type(cls, v, values):
        # If type is not inline, payload should be ignored (set to None)
        if values.get("type") != "inline" and v is not None:
            return None
        return v

    @validator("payload", allow_reuse=True)
    def check_payload_type_for_inline(cls, v, values):
        if values.get("type") == "inline" and v is not None and not isinstance(v, list):
            raise ValueError("payload must be a list of strings when type is 'inline'")
        if values.get("type") == "inline" and v is None:
            raise ValueError("payload must be configured if the type is 'inline'")
        return v

    @validator("format", allow_reuse=True)
    def check_format_with_behavior(cls, v, values):
        behavior = values.get("behavior")
        if v == "mrs" and behavior not in ["domain", "ipcidr"]:
            raise ValueError("mrs format only supports 'domain' or 'ipcidr' behavior")
        return v


class RuleProviders(BaseModel):
    __root__: dict[str, RuleProvider]
