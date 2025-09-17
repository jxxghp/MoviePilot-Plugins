from typing import List, Optional, Dict, Literal

from pydantic import BaseModel, Field


class HttpOpts(BaseModel):
    method: Optional[str] = None
    path: List[str] = ['/']
    headers: Optional[Dict[str, List[str]]] = None


class H2Opts(BaseModel):
    host: List[str]
    path: str = '/'


class GrpcOpts(BaseModel):
    grpc_service_name: str = Field(..., alias='grpc-service-name')


class WsOpts(BaseModel):
    path: str = '/'
    headers: Optional[Dict[str, str]] = None
    max_early_data: Optional[int] = Field(None, alias='max-early-data')
    early_data_header_name: Optional[str] = Field(None, alias='early-data-header-name')
    v2ray_http_upgrade: Optional[bool] = Field(None, alias='v2ray-http-upgrade')
    v2ray_http_upgrade_fast_open: Optional[bool] = Field(None, alias='v2ray-http-upgrade-fast-open')


class NetworkMixin(BaseModel):
    # Transport settings
    network: Optional[Literal['tcp', 'http', 'h2', 'grpc', 'ws', 'kcp']] = None
    http_opts: Optional[HttpOpts] = Field(None, alias='http-opts')
    h2_opts: Optional[H2Opts] = Field(None, alias='h2-opts')
    grpc_opts: Optional[GrpcOpts] = Field(None, alias='grpc-opts')
    ws_opts: Optional[WsOpts] = Field(None, alias='ws-opts')
