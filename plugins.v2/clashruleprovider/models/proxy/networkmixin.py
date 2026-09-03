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


class XhttpReuseSettings(BaseModel):
    max_concurrency: Optional[str] = Field(None, alias='max-concurrency')
    max_connections: Optional[str] = Field(None, alias='max-connections')
    c_max_reuse_times: Optional[str] = Field(None, alias='c-max-reuse-times')
    h_max_request_times: Optional[str] = Field(None, alias='h-max-request-times')
    h_max_reusable_secs: Optional[str] = Field(None, alias='h-max-reusable-secs')
    h_keep_alive_period: Optional[int] = Field(None, alias='h-keep-alive-period')


class XhttpDownloadSettings(BaseModel):
    # xhttp part
    path: Optional[str] = None
    host: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    no_grpc_header: Optional[bool] = Field(None, alias='no-grpc-header')
    x_padding_bytes: Optional[str] = Field(None, alias='x-padding-bytes')
    x_padding_obfs_mode: Optional[bool] = Field(None, alias='x-padding-obfs-mode')
    x_padding_key: Optional[str] = Field(None, alias='x-padding-key')
    x_padding_header: Optional[str] = Field(None, alias='x-padding-header')
    x_padding_placement: Optional[str] = Field(None, alias='x-padding-placement')
    x_padding_method: Optional[str] = Field(None, alias='x-padding-method')
    uplink_http_method: Optional[str] = Field(None, alias='uplink-http-method')
    session_placement: Optional[str] = Field(None, alias='session-placement')
    session_key: Optional[str] = Field(None, alias='session-key')
    seq_placement: Optional[str] = Field(None, alias='seq-placement')
    seq_key: Optional[str] = Field(None, alias='seq-key')
    uplink_data_placement: Optional[str] = Field(None, alias='uplink-data-placement')
    uplink_data_key: Optional[str] = Field(None, alias='uplink-data-key')
    uplink_chunk_size: Optional[int] = Field(None, alias='uplink-chunk-size')
    sc_max_each_post_bytes: Optional[int] = Field(None, alias='sc-max-each-post-bytes')
    sc_min_posts_interval_ms: Optional[int] = Field(None, alias='sc-min-posts-interval-ms')
    reuse_settings: Optional[XhttpReuseSettings] = Field(None, alias='reuse-settings')

    # proxy part
    server: Optional[str] = None
    port: Optional[int] = None
    tls: Optional[bool] = None
    alpn: Optional[List[str]] = None
    skip_cert_verify: Optional[bool] = Field(None, alias='skip-cert-verify')
    fingerprint: Optional[str] = None
    certificate: Optional[str] = None
    private_key: Optional[str] = Field(None, alias='private-key')
    servername: Optional[str] = None
    client_fingerprint: Optional[str] = Field(None, alias='client-fingerprint')


class XhttpOpts(BaseModel):
    host: Optional[str] = None
    path: str = '/'
    mode: Literal["auto", "stream-one", "stream-up", "packet-up"] | None = None
    headers: Optional[Dict[str, str]] = None
    no_grpc_header: Optional[bool] = Field(None, alias='no-grpc-header')
    x_padding_bytes: Optional[str] = Field(None, alias='x-padding-bytes')
    x_padding_obfs_mode: Optional[bool] = Field(None, alias='x-padding-obfs-mode')
    x_padding_key: Optional[str] = Field(None, alias='x-padding-key')
    x_padding_header: Optional[str] = Field(None, alias='x-padding-header')
    x_padding_placement: Optional[str] = Field(None, alias='x-padding-placement')
    x_padding_method: Optional[str] = Field(None, alias='x-padding-method')
    uplink_http_method: Optional[str] = Field(None, alias='uplink-http-method')
    session_placement: Optional[str] = Field(None, alias='session-placement')
    session_key: Optional[str] = Field(None, alias='session-key')
    seq_placement: Optional[str] = Field(None, alias='seq-placement')
    seq_key: Optional[str] = Field(None, alias='seq-key')
    uplink_data_placement: Optional[str] = Field(None, alias='uplink-data-placement')
    uplink_data_key: Optional[str] = Field(None, alias='uplink-data-key')
    uplink_chunk_size: Optional[int] = Field(None, alias='uplink-chunk-size')
    sc_max_each_post_bytes: Optional[int] = Field(None, alias='sc-max-each-post-bytes')
    sc_min_posts_interval_ms: Optional[int] = Field(None, alias='sc-min-posts-interval-ms')
    reuse_settings: Optional[XhttpReuseSettings] = Field(None, alias='reuse-settings')
    download_settings: Optional[XhttpDownloadSettings] = Field(None, alias='download-settings')


class NetworkMixin(BaseModel):
    # Transport settings
    network: Optional[Literal['tcp', 'http', 'h2', 'grpc', 'ws', 'kcp', 'xhttp']] = None
    http_opts: Optional[HttpOpts] = Field(None, alias='http-opts')
    h2_opts: Optional[H2Opts] = Field(None, alias='h2-opts')
    grpc_opts: Optional[GrpcOpts] = Field(None, alias='grpc-opts')
    ws_opts: Optional[WsOpts] = Field(None, alias='ws-opts')
    xhttp_opts: Optional[XhttpOpts] = Field(None, alias='xhttp-opts')
