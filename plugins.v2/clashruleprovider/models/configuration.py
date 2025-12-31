from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator, field_validator, field_serializer, PrivateAttr

from app.log import logger

from .proxy import Proxy
from .proxygroups import ProxyGroup
from .proxyproviders import ProxyProvider
from .proxy.tlsmixin import ClientFingerprint
from .ruleproviders import RuleProvider
from .rule import RuleType, Action, RoutingRuleType
from ..helper.clashruleparser import ClashRuleParser


class ExternalControllerCors(BaseModel):
    allow_origins: list[str] = Field(default_factory=lambda: ["*"], alias="allow-origins")
    allow_credentials: bool = Field(default=True, alias="allow-credentials")


class Profile(BaseModel):
    store_selected: bool = Field(default=False, alias="store-selected")
    store_fake_ip: bool = Field(default=False, alias="store-fake-ip")


class NTP(BaseModel):
    enable: bool = Field(default=False)
    Server: str = Field(default="time.apple.com")
    port: int = Field(default=123)
    write_to_system: bool = Field(default=False, alias="write-to-system")


class Experimental(BaseModel):
    quic_go_disable_gso: bool = Field(default=False, alias="quic-go-disable-gso")
    quic_go_disable_ecn: bool = Field(default=True, alias="quic-go-disable-ecn")
    dialer_ip4p_convert: bool = Field(default=False, alias="dialer-ip4p-convert")


class ClashConfig(BaseModel):
    _raw_proxies: dict[str, str] = PrivateAttr(default_factory=dict)

    dns: dict[str, Any] | None = Field(default=None)
    hosts: dict[str, list[str] | str] | None = Field(default=None)
    allow_lan: bool | None = Field(default=None, alias="allow-lan")
    bind_address: str = Field(default="*", alias="bind-address")
    lan_allowed_ips: list[str] = Field(default_factory=lambda: ["0.0.0.0/0", "::/0"], alias="lan-allowed-ips")
    lan_disallowed_ips: list[str] = Field(default_factory=list, alias="lan-disallowed-ips")
    authentication: list[str] = Field(default_factory=list)
    skip_auth_prefixes: list[str] = Field(default_factory=list, alias="skip-auth-prefixes")
    mode: Literal["rule", "global", "direct"] = Field(default="rule")
    log_level: Literal["silent", "error", "warning", "info", "debug"] = Field(default="info", alias="log-level")
    ipv6: bool = Field(default=True)
    keep_alive_interval: int = Field(default=0, alias="keep-alive-interval")
    keep_alive_idle: int = Field(default=0, alias="keep-alive-idle")
    disable_keep_alive: bool = Field(default=False, alias="disable-keep-alive")
    find_process_mode: Literal["strict", "always", "off"] = Field(default="strict", alias="find-process-mode")
    external_controller: str | None = Field(default=None, alias="external-controller")
    external_controller_cors: ExternalControllerCors = Field(default_factory=ExternalControllerCors,
                                                             alias="external-controller-cors")
    external_controller_unix: str | None = Field(default=None, alias="external-controller-unix")
    external_controller_pipe: str | None = Field(default=None, alias="external-controller-pipe")
    external_controller_tls: str | None = Field(default=None, alias="external-controller-tls")
    secret: str | None = Field(default=None)
    external_ui: str | None = Field(default=None, alias="external-ui")
    external_ui_name: str | None = Field(default=None, alias="external-ui-name")
    external_ui_url: str | None = Field(default=None, alias="external-ui-url")
    profile: Profile = Field(default_factory=Profile)
    unified_delay: bool = Field(default=True, alias="unified-delay")
    tcp_concurrent: bool = Field(default=True, alias="tcp-concurrent")
    interface_name: str | None = Field(default=None, alias="interface-name")
    routing_mark: int | None = Field(default=None, alias="routing-mark")
    tls: dict[str, Any] | None = Field(default=None, alias="tls")
    global_client_fingerprint: ClientFingerprint | None = Field(default=ClientFingerprint.chrome,
                                                                alias="global-client-fingerprint")
    geodata_mode: bool | None = Field(default=None, alias="geodata-mode")
    geodata_loader: Literal["memconservative", "standard"] = Field(default="memconservative", alias="geodata-loader")
    geo_auto_update: bool = Field(default=False, alias="geo-auto-update")
    geo_update_interval: int = Field(default=24, alias="geo-update-interval")
    global_ua: str = Field(default="clash.meta", alias="global-ua")
    etag_support: bool = Field(default=True, alias="etag-support")
    sniffer: dict[str, Any] | None = None
    listeners: list[dict[str, Any]] | None = Field(default=None)
    port: int = Field(default=0, description="HTTP(S) proxy port")
    socks_port: int = Field(default=0, alias="socks-port")
    mixed_port: int = Field(default=0, alias="mixed-port")
    redir_port: int = Field(default=0, alias="redir-port")
    tproxy_port: int = Field(default=0, alias="tproxy-port")
    tun: dict[str, Any] | None = Field(default=None)
    sub_rules: dict[str, Any] | None = Field(default=None, alias="sub-rules")
    tunnels: list[dict[str, Any] | str] | None = Field(default=None)
    ntp: NTP | None = Field(default=None)
    experimental: Experimental | None = Field(default=None)
    proxies: list[Proxy] = Field(default_factory=list)
    proxy_providers: dict[str, ProxyProvider] = Field(default_factory=dict, alias="proxy-providers")
    proxy_groups: list[ProxyGroup] = Field(default_factory=list, alias="proxy-groups")
    rules: list[RuleType] = Field(default_factory=list)
    rule_providers: dict[str, RuleProvider] = Field(default_factory=dict, alias="rule-providers")

    @model_validator(mode="before")
    @classmethod
    def fill_none_with_default(cls, values: dict):
        fill_none_fields = {"proxies", "proxy_providers", "proxy_groups", "rules", "rule_providers"}
        for field_name in fill_none_fields:
            field = cls.model_fields[field_name]
            factory = field.default_factory
            if not factory:
                continue
            keys = {field_name}
            if field.alias:
                keys.add(field.alias)

            for key in keys:
                if key in values and values[key] is None:
                    values[key] = factory()
        return values

    @field_serializer("proxies")
    def serialize_proxies(self, v: list[Proxy], _info):
        serialized_proxies = []
        seen_names = set()
        for proxy in v:
            if proxy.name in seen_names:
                logger.warning(f"Skipping duplicate proxy: {proxy.name}")
                continue
            seen_names.add(proxy.name)
            serialized_proxies.append(proxy.model_dump(by_alias=True, exclude_none=True, mode="json"))
        return serialized_proxies

    @field_serializer("proxy_groups")
    def serialize_proxy_groups(self, v: list[ProxyGroup], _info):
        valid_outbounds = {a.value for a in Action}
        valid_outbounds.add("GLOBAL")
        if self.proxies:
            valid_outbounds.update(p.name for p in self.proxies)
        if v:
            valid_outbounds.update(pg.name for pg in v)

        serialized_groups = []
        seen_names = set()
        for group in v:
            if group.name in seen_names:
                logger.warning(f"Skipping duplicate proxy group: {group.name}")
                continue
            seen_names.add(group.name)

            group_data = group.model_dump(by_alias=True, exclude_none=True, mode="json")
            if "proxies" in group_data and group_data["proxies"]:
                original_proxies = group_data["proxies"]
                group_data["proxies"] = [
                    p for p in original_proxies if p in valid_outbounds
                ]
                removed = set(original_proxies) - set(group_data["proxies"])
                if removed:
                    logger.warning(f"Proxy group {group.name} removed missing proxies: {removed}")
            serialized_groups.append(group_data)

        return serialized_groups

    @field_validator("rules", mode="before")
    @classmethod
    def validate_rules(cls, v):
        if isinstance(v, list):
            rules = []
            for item in v:
                if isinstance(item, str):
                    rules.append(ClashRuleParser.parse(item))
                else:
                    rules.append(item)
            return rules
        return v

    @field_serializer("rules")
    def serialize_rules(self, v: list[RuleType], _info):
        valid_rules = []
        valid_outbounds = set(self.outbounds)
        valid_actions = {a.value for a in Action}

        for rule in v:
            if rule.rule_type == RoutingRuleType.SUB_RULE:
                if self.sub_rules and rule.action in self.sub_rules:
                    valid_rules.append(rule)
                else:
                    logger.warning(f"Skipping rule with missing sub-rule action: {rule}")
                continue

            if rule.rule_type == RoutingRuleType.RULE_SET:
                if rule.payload not in self.rule_providers:
                    logger.warning(f"Skipping rule with missing rule-provider: {rule}")
                    continue

            action_str = str(rule.action)
            if action_str in valid_actions or action_str in valid_outbounds:
                valid_rules.append(rule)
            else:
                logger.warning(f"Skipping rule with invalid outbound: {rule}")

        return [str(rule) for rule in valid_rules]

    @property
    def outbounds(self) -> list[str]:
        outbounds = []
        if self.proxies:
            outbounds.extend(p.name for p in self.proxies)
        if self.proxy_groups:
            outbounds.extend(pg.name for pg in self.proxy_groups)
        return outbounds

    @property
    def node_num(self) -> int:
        return len(self.proxies)

    @property
    def raw_proxies(self) -> dict[str, str]:
        return self._raw_proxies

    @raw_proxies.setter
    def raw_proxies(self, value: dict[str, str]):
        self._raw_proxies = value

    def merge(self, other: 'ClashConfig') -> 'ClashConfig':
        self.proxies += other.proxies
        self.proxy_groups += other.proxy_groups
        self.rules += other.rules
        self.rule_providers |= other.rule_providers
        self.proxy_providers |= other.proxy_providers
        return self
