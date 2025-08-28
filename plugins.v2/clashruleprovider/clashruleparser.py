import base64
import binascii
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional, Union, Callable, Literal
from urllib.parse import urlparse, parse_qs, unquote, parse_qsl

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
    size_limit: int = Field(0, ge=0, description="The maximum size of downloadable files in bytes (0 for no limit)")
    payload: Optional[List[str]] = Field(None, description="Content, only effective when type is inline")

    @validator("url", pre=True, always=True, allow_reuse=True)
    def check_url_for_http_type(cls, v, values):
        if values.get("type") == "http" and v is None:
            raise ValueError("url must be configured if the type is 'http'")
        return v

    @validator("path", pre=True, always=True, allow_reuse=True)
    def check_path_for_file_type(cls, v, values):
        if values.get("type") == "file" and v is None:
            raise ValueError("path must be configured if the type is 'file'")
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


class ProxyGroupBase(BaseModel):
    """
    包含所有代理组类型共有的通用字段。
    """
    # Required field
    name: str = Field(..., description="The name of the proxy group.")

    # Proxy and provider references
    proxies: Optional[List[str]] = Field(None, description="References to outbound proxies or other proxy groups.")
    use: Optional[List[str]] = Field(None, description="References to proxy provider sets.")

    # Health check fields
    url: Optional[str] = Field(None, description="Health check test address.")
    interval: Optional[int] = Field(None, description="Health check interval in seconds.")
    lazy: bool = Field(True, description="If not selected, no health checks are performed.")
    timeout: Optional[int] = Field(5000, description="Health check timeout in milliseconds.")
    max_failed_times: Optional[int] = Field(5, description="Maximum number of failures before a forced health check.")
    expected_status: Optional[str] = Field(None, description="Expected HTTP response status code for health checks.")

    # Network and routing fields
    disable_udp: Optional[bool] = Field(False, description="Disables UDP for this proxy group.")
    interface_name: Optional[str] = Field(None, description="DEPRECATED. Specifies the outbound interface.")
    routing_mark: Optional[int] = Field(None, description="DEPRECATED. The routing mark for outbound connections.")

    # Dynamic proxy inclusion
    include_all: Optional[bool] = Field(False, description="Includes all outbound proxies and proxy sets.")
    include_all_proxies: Optional[bool] = Field(False, description="Includes all outbound proxies.")
    include_all_providers: Optional[bool] = Field(False, description="Includes all proxy provider sets.")

    # Filtering
    filter: Optional[str] = Field(None, description="Regex to filter nodes from providers.")
    exclude_filter: Optional[str] = Field(None, description="Regex to exclude nodes.")
    exclude_type: Optional[str] = Field(None, description="Exclude nodes by adapter type, separated by '|'.")

    # UI fields
    hidden: Optional[bool] = Field(False, description="Hides the proxy group in the API.")
    icon: Optional[str] = Field(None, description="Icon string for the proxy group, for UI use.")

    @validator('expected_status', allow_reuse=True)
    def validate_expected_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == '*':
            return v
        pattern = re.compile(r'^\d{3}([-/]\d{3})*$')
        if not pattern.match(v):
            raise ValueError("Invalid format for expected-status.")
        parts = re.split(r'[/]', v)
        for part in parts:
            if '-' in part:
                start, end = part.split('-')
                if not (start.isdigit() and end.isdigit() and 100 <= int(start) < 600 and 100 <= int(end) < 600 and int(
                        start) <= int(end)):
                    raise ValueError(f"Invalid status code range: {part}")
            elif not (part.isdigit() and 100 <= int(part) < 600):
                raise ValueError(f"Invalid status code: {part}")
        return v


class SelectGroup(ProxyGroupBase):
    type: Literal['select']


class RelayGroup(ProxyGroupBase):
    type: Literal['relay']


class FallbackGroup(ProxyGroupBase):
    type: Literal['fallback']


class UrlTestGroup(ProxyGroupBase):
    type: Literal['url-test']
    tolerance: Optional[int] = Field(None, description="proxies switch tolerance, measured in milliseconds (ms).")


class LoadBalanceGroup(ProxyGroupBase):
    type: Literal['load-balance']
    strategy: Optional[Literal['round-robin', 'consistent-hashing', 'sticky-sessions']] = Field(
        'round-robin',
        description="Load balancing strategy."
    )


# --- Discriminated Union ---
ProxyGroupUnion = Union[SelectGroup, RelayGroup, FallbackGroup, UrlTestGroup, LoadBalanceGroup]


class ProxyGroup(BaseModel):
    __root__: ProxyGroupUnion


class AdditionalParam(Enum):
    NO_RESOLVE = 'no-resolve'
    SRC = 'src'


class RuleType(Enum):
    """Enumeration of all supported Clash rule types"""
    DOMAIN = "DOMAIN"
    DOMAIN_SUFFIX = "DOMAIN-SUFFIX"
    DOMAIN_KEYWORD = "DOMAIN-KEYWORD"
    DOMAIN_REGEX = "DOMAIN-REGEX"
    GEOSITE = "GEOSITE"

    IP_CIDR = "IP-CIDR"
    IP_CIDR6 = "IP-CIDR6"
    IP_SUFFIX = "IP-SUFFIX"
    IP_ASN = "IP-ASN"
    GEOIP = "GEOIP"

    SRC_GEOIP = "SRC-GEOIP"
    SRC_IP_ASN = "SRC-IP-ASN"
    SRC_IP_CIDR = "SRC-IP-CIDR"
    SRC_IP_SUFFIX = "SRC-IP-SUFFIX"

    DST_PORT = "DST-PORT"
    SRC_PORT = "SRC-PORT"

    IN_PORT = "IN-PORT"
    IN_TYPE = "IN-TYPE"
    IN_USER = "IN-USER"
    IN_NAME = "IN-NAME"

    PROCESS_PATH = "PROCESS-PATH"
    PROCESS_PATH_REGEX = "PROCESS-PATH-REGEX"
    PROCESS_NAME = "PROCESS-NAME"
    PROCESS_NAME_REGEX = "PROCESS-NAME-REGEX"

    UID = "UID"
    NETWORK = "NETWORK"
    DSCP = "DSCP"

    RULE_SET = "RULE-SET"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    SUB_RULE = "SUB-RULE"

    MATCH = "MATCH"


class Action(Enum):
    """Enumeration of rule actions"""
    DIRECT = "DIRECT"
    REJECT = "REJECT"
    REJECT_DROP = "REJECT-DROP"
    PASS = "PASS"
    COMPATIBLE = "COMPATIBLE"


@dataclass
class ClashRule:
    """Represents a parsed Clash routing rule"""
    rule_type: RuleType
    payload: str
    action: Union[Action, str]  # Can be Action enum or custom proxy group name
    additional_params: Optional[AdditionalParam] = None
    raw_rule: str = ""
    priority: int = 0

    def condition_string(self) -> str:
        return f"{self.rule_type.value},{self.payload}"


@dataclass
class LogicRule:
    """Represents a logic rule (AND, OR, NOT)"""
    logic_type: RuleType
    conditions: List[Union[ClashRule, 'LogicRule']]
    action: Union[Action, str]
    raw_rule: str = ""
    priority: int = 0

    def condition_string(self) -> str:
        conditions_str = ','.join([f"({c.condition_string()})" for c in self.conditions])
        return f"{self.logic_type.value},({conditions_str})"


@dataclass
class MatchRule:
    """Represents a match rule"""
    action: Union[Action, str]
    raw_rule: str = ""
    priority: int = 0
    rule_type: RuleType = RuleType.MATCH

    @staticmethod
    def condition_string() -> str:
        return "MATCH"


class ClashRuleParser:
    """Parser for Clash routing rules"""

    def __init__(self):
        self.rules: List[Union[ClashRule, LogicRule, MatchRule]] = []

    @staticmethod
    def parse_rule_line(line: str) -> Optional[Union[ClashRule, LogicRule, MatchRule]]:
        """Parse a single rule line"""
        line = line.strip()
        try:
            # Handle logic rules (AND, OR, NOT)

            if line.startswith(('AND,', 'OR,', 'NOT,')):
                return ClashRuleParser._parse_logic_rule(line)
            elif line.startswith('MATCH'):
                return ClashRuleParser._parse_match_rule(line)
            # Handle regular rules
            return ClashRuleParser._parse_regular_rule(line)

        except Exception as e:
            return None

    @staticmethod
    def parse_rule_dict(clash_rule: Dict[str, Any]) -> Optional[Union[ClashRule, LogicRule, MatchRule]]:
        if not clash_rule:
            return None
        if clash_rule.get("type") in ('AND', 'OR', 'NOT'):
            conditions = clash_rule.get("conditions")
            if not conditions:
                return None
            conditions_str = ''
            for condition in conditions:
                conditions_str += f'({condition.get("type")},{condition.get("payload")})'
            conditions_str = f"({conditions_str})"
            raw_rule = f"{clash_rule.get('type')},{conditions_str},{clash_rule.get('action')}"
            rule = ClashRuleParser._parse_logic_rule(raw_rule)
        elif clash_rule.get("type") == 'MATCH':
            raw_rule = f"{clash_rule.get('type')},{clash_rule.get('action')}"
            rule = ClashRuleParser._parse_match_rule(raw_rule)
        else:
            raw_rule = f"{clash_rule.get('type')},{clash_rule.get('payload')},{clash_rule.get('action')}"
            if clash_rule.get('additional_params'):
                raw_rule += f",{clash_rule.get('additional_params')}"
            rule = ClashRuleParser._parse_regular_rule(raw_rule)
        if rule and 'priority' in clash_rule:
            rule.priority = clash_rule['priority']
        return rule

    @staticmethod
    def _parse_match_rule(line: str) -> MatchRule:
        parts = line.split(',')
        if len(parts) < 2:
            raise ValueError(f"Invalid rule format: {line}")
        action = parts[1]
        # Validate rule type
        try:
            action_enum = Action(action.upper())
            final_action = action_enum
        except ValueError:
            final_action = action

        return MatchRule(
            action=final_action,
            raw_rule=line
        )

    @staticmethod
    def _parse_regular_rule(line: str) -> ClashRule:
        """Parse a regular (non-logic) rule"""
        parts = line.split(',')

        if len(parts) < 3 or len(parts) > 4:
            raise ValueError(f"Invalid rule format: {line}")

        rule_type_str = parts[0].upper()
        payload = parts[1]
        action = parts[2]

        if not payload or not rule_type_str:
            raise ValueError(f"Invalid rule format: {line}")

        additional_params = parts[3] if len(parts) > 3 else None

        # Validate rule type
        try:
            rule_type = RuleType(rule_type_str)
        except ValueError:
            raise ValueError(f"Unknown rule type: {rule_type_str}")

        # Try to convert action to enum, otherwise keep as string (custom proxy group)
        try:
            action_enum = Action(action.upper())
            final_action = action_enum
        except ValueError:
            final_action = action

        return ClashRule(
            rule_type=rule_type,
            payload=payload,
            action=final_action,
            additional_params=additional_params,
            raw_rule=line
        )

    @staticmethod
    def _parse_logic_rule(line: str) -> LogicRule:
        """Parse a logic rule (AND, OR, NOT)"""
        # Extract logic type
        logic_rule_match = re.match(r'^(AND|OR|NOT),\((.+)\),([^,]+)$', line)
        if not logic_rule_match:
            raise ValueError(f"Cannot extract action from logic rule: {line}")
        logic_type_str = logic_rule_match.group(1).upper()
        logic_type = RuleType(logic_type_str)
        action = logic_rule_match.group(3)
        # Try to convert action to enum
        try:
            action_enum = Action(action.upper())
            final_action = action_enum
        except ValueError:
            final_action = action
        conditions_str = logic_rule_match.group(2)
        conditions = ClashRuleParser._parse_logic_conditions(conditions_str)

        return LogicRule(
            logic_type=logic_type,
            conditions=conditions,
            action=final_action,
            raw_rule=line
        )

    @staticmethod
    def _parse_logic_conditions(conditions_str: str) -> List[ClashRule]:
        """Parse conditions within logic rules"""
        conditions = []

        # Simple parser for conditions like (DOMAIN,baidu.com),(NETWORK,UDP)
        # This is a basic implementation - more complex nested logic would need a proper parser
        condition_pattern = r'\(([^,]+),([^)]+)\)'
        matches = re.findall(condition_pattern, conditions_str)

        for rule_type_str, payload in matches:
            try:
                rule_type = RuleType(rule_type_str.upper())
                condition = ClashRule(
                    rule_type=rule_type,
                    payload=payload,
                    action="",  # Logic conditions don't have actions
                    raw_rule=f"{rule_type_str},{payload}"
                )
                conditions.append(condition)
            except ValueError:
                continue

        return conditions

    @staticmethod
    def action_string(action: Union[Action, str]) -> str:
        return action.value if isinstance(action, Action) else action

    def parse_rules(self, rules_text: str) -> List[Union[ClashRule, LogicRule, MatchRule]]:
        """Parse multiple rules from text, preserving order and priority"""
        self.rules = []
        lines = rules_text.strip().split('\n')
        priority = 0

        for line in lines:
            rule = self.parse_rule_line(line)
            if rule:
                rule.priority = priority  # Assign priority based on position
                self.rules.append(rule)
                priority += 1

        return self.rules

    def parse_rules_from_list(self, rules_list: List[str]) -> List[Union[ClashRule, LogicRule, MatchRule]]:
        """Parse rules from a list of rule strings, preserving order and priority"""
        self.rules = []

        for priority, rule_str in enumerate(rules_list):
            rule = self.parse_rule_line(rule_str)
            if rule:
                rule.priority = priority  # Assign priority based on list position
                self.rules.append(rule)

        return self.rules

    def validate_rule(self, rule: ClashRule) -> bool:
        """Validate a parsed rule"""
        try:
            # Basic validation based on rule type
            if rule.rule_type in [RuleType.IP_CIDR, RuleType.IP_CIDR6]:
                # Validate CIDR format
                return '/' in rule.payload

            elif rule.rule_type == RuleType.DST_PORT or rule.rule_type == RuleType.SRC_PORT:
                # Validate port number/range
                return rule.payload.isdigit() or '-' in rule.payload

            elif rule.rule_type == RuleType.NETWORK:
                # Validate network type
                return rule.payload.lower() in ['tcp', 'udp']

            elif rule.rule_type == RuleType.DOMAIN_REGEX or rule.rule_type == RuleType.PROCESS_PATH_REGEX:
                # Try to compile regex
                re.compile(rule.payload)
                return True

            return True

        except Exception:
            return False

    def to_list(self) -> List[str]:
        result = []
        for rule in self.rules:
            result.append(rule.raw_rule)
        return result

    def to_dict(self) -> List[Dict[str, Any]]:
        """Convert parsed rules to dictionary format"""
        result = []

        for rule in self.rules:
            if isinstance(rule, ClashRule):
                rule_dict = {
                    'type': rule.rule_type.value,
                    'payload': rule.payload,
                    'action': rule.action.value if isinstance(rule.action, Action) else rule.action,
                    'additional_params': rule.additional_params,
                    'priority': rule.priority,
                    'raw': rule.raw_rule
                }
                result.append(rule_dict)

            elif isinstance(rule, LogicRule):
                conditions_dict = []
                for condition in rule.conditions:
                    if isinstance(condition, ClashRule):
                        conditions_dict.append({
                            'type': condition.rule_type.value,
                            'payload': condition.payload
                        })

                rule_dict = {
                    'type': rule.logic_type.value,
                    'conditions': conditions_dict,
                    'action': rule.action.value if isinstance(rule.action, Action) else rule.action,
                    'priority': rule.priority,
                    'raw': rule.raw_rule
                }
                result.append(rule_dict)
            elif isinstance(rule, MatchRule):
                rule_dict = {
                    'type': 'MATCH',
                    'action': rule.action.value if isinstance(rule.action, Action) else rule.action,
                    'priority': rule.priority,
                    'raw': rule.raw_rule
                }
                result.append(rule_dict)
        return result

    def get_rules_by_priority(self) -> List[Union[ClashRule, LogicRule, MatchRule]]:
        """Get rules sorted by priority (highest priority first)"""
        return sorted(self.rules, key=lambda rule: rule.priority)

    def append_rule(self, rule: Union[ClashRule, LogicRule, MatchRule]) -> None:
        max_priority = max(rule.priority for rule in self.rules) if len(self.rules) else 0
        rule.priority = max_priority + 1
        self.rules.append(rule)
        # Re-sort rules to maintain order
        self.rules.sort(key=lambda r: r.priority)

    def append_rules(self, rules: List[Union[ClashRule, LogicRule, MatchRule]]) -> None:
        max_priority = max(rule.priority for rule in self.rules) if len(self.rules) else 0
        priority = max_priority + 1
        for rule in rules:
            rule.priority = priority
            self.rules.append(rule)
            priority += 1
        self.rules.sort(key=lambda r: r.priority)

    def insert_rule_at_priority(self, rule: Union[ClashRule, LogicRule, MatchRule], priority: int):
        """Insert a rule at a specific priority position, adjusting other rules"""
        # Adjust priorities of existing rules
        for existing_rule in self.rules:
            if existing_rule.priority >= priority:
                existing_rule.priority += 1
        rule.priority = priority
        self.rules.append(rule)

        # Re-sort rules to maintain order
        self.rules.sort(key=lambda r: r.priority)

    def update_rule_at_priority(self, clash_rule: Union[ClashRule, LogicRule], priority: int) -> bool:
        if clash_rule.priority == priority:
            for index, existing_rule in enumerate(self.rules):
                if existing_rule.priority == priority:
                    self.rules[index] = clash_rule
                    self.rules[index].priority = priority
                    return True
            return False
        else:
            removed = self.remove_rule_at_priority(priority)
            if not removed:
                return False
            self.insert_rule_at_priority(clash_rule, clash_rule.priority)
            return True

    def get_rule_at_priority(self, priority: int) -> Optional[Union[ClashRule, LogicRule, MatchRule]]:
        for rule in self.rules:
            if rule.priority == priority:
                return rule
        return None

    def remove_rule_at_priority(self, priority: int) -> Optional[Union[ClashRule, LogicRule, MatchRule]]:
        """Remove rule at specific priority and adjust remaining priorities"""
        rule_to_remove = None
        for rule in self.rules:
            if rule.priority == priority:
                rule_to_remove = rule
                break

        if rule_to_remove:
            self.rules.remove(rule_to_remove)

            # Adjust priorities of remaining rules
            for rule in self.rules:
                if rule.priority > priority:
                    rule.priority -= 1

            return rule_to_remove
        return None

    def remove_rules(self, condition: Callable[[Union[ClashRule, LogicRule, MatchRule]], bool]):
        """Remove rules by lambda"""
        i = 0
        while i < len(self.rules):
            if condition(self.rules[i]):
                priority = self.rules[i].priority
                for rule in self.rules:
                    if rule.priority > priority:
                        rule.priority -= 1
                del self.rules[i]
            else:
                i += 1

    def move_rule_priority(self, from_priority: int, to_priority: int) -> bool:
        """Move a rule from one priority position to another"""
        rule_to_move = None
        for rule in self.rules:
            if rule.priority == from_priority:
                rule_to_move = rule
                break

        if not rule_to_move:
            return False

        # Remove rule temporarily
        self.remove_rule_at_priority(from_priority)

        # Insert at new priority
        self.insert_rule_at_priority(rule_to_move, to_priority)

        return True

    def filter_rules_by_lambda(self, condition: Callable[[Union[ClashRule, LogicRule, MatchRule]], bool]):
        """Filter rules by lambda"""
        return [rule for rule in self.rules if condition(rule)]

    def filter_rules_by_type(self, rule_type: RuleType) -> List[ClashRule]:
        """Filter rules by type"""
        return [rule for rule in self.rules
                if isinstance(rule, ClashRule) and rule.rule_type == rule_type]

    def filter_rules_by_action(self, action: Union[Action, str]) -> List[Union[ClashRule, LogicRule, MatchRule]]:
        """Filter rules by action"""
        return [rule for rule in self.rules if rule.action == action]

    def has_rule(self, clash_rule: Union[ClashRule, LogicRule, MatchRule]) -> bool:
        for rule in self.rules:
            if rule.rule_type != RuleType.MATCH:
                if rule.rule_type == clash_rule.rule_type and rule.action == clash_rule.action \
                        and rule.payload == clash_rule.payload:
                    return True
            else:
                if rule.rule_type == clash_rule.rule_type and rule.action == clash_rule.action:
                    return True
        return False

    def reorder_rules(
            self,
            moved_rule_priority: int,
            target_priority: int,
    ):
        """
        Reorder rules

        :param moved_rule_priority: 被移动规则的原始优先级
        :param target_priority: 目标位置的优先级
        """
        moved_index = next(i for i, r in enumerate(self.rules) if r.priority == moved_rule_priority)
        target_index = next(
            (i for i, r in enumerate(self.rules) if r.priority == target_priority),
            len(self.rules)
        )
        # 直接修改被移动规则的优先级
        moved_rule = self.rules[moved_index]
        moved_rule.priority = target_priority

        if moved_index < target_index:
            # 向后移动：原位置到目标位置之间的规则优先级 -1
            for i in range(moved_index + 1, target_index + 1):
                self.rules[i].priority -= 1
        elif moved_index > target_index:
            # 向前移动：目标位置到原位置之间的规则优先级 +1
            for i in range(target_index, moved_index):
                self.rules[i].priority += 1
        self.rules.sort(key=lambda x: x.priority)


class Converter:
    """
    Converter for V2Ray Subscription

    Reference:
    https://github.com/MetaCubeX/mihomo/blob/Alpha/common/convert/converter.go
    https://github.com/SubConv/SubConv/blob/main/modules/convert/converter.py
    """
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome'

    @staticmethod
    def decode_base64(data):
        # 添加适配不同 padding 的容错机制
        data = data.strip()
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.b64decode(data)

    @staticmethod
    def try_decode_base64_json(data):
        try:
            return json.loads(Converter.decode_base64(data).decode('utf-8'))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def unique_name(name_map, name):
        index = name_map.get(name, 0)
        name_map[name] = index + 1
        if index > 0:
            return f"{name}-{index:02d}"
        return name

    @staticmethod
    def strtobool(val):
        val = val.lower()
        if val in ("y", "yes", "t", "true", "on", "1"):
            return True
        elif val in ("n", "no", "f", "false", "off", "0"):
            return False
        else:
            raise ValueError(f"invalid truth value {val!r}")

    @staticmethod
    def convert_v2ray(v2ray_link: Union[list, bytes], skip_exception: bool = True) -> List[Dict[str, Any]]:
        if isinstance(v2ray_link, bytes):
            decoded = Converter.decode_base64(v2ray_link).decode("utf-8")
            lines = decoded.strip().splitlines()
        else:
            lines = v2ray_link
        proxies = []
        names = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue

            if "://" not in line:
                continue

            scheme, body = line.split("://", 1)
            scheme = scheme.lower()

            if scheme == "vmess":
                try:
                    vmess_data = Converter.try_decode_base64_json(body)
                    name = Converter.unique_name(names, vmess_data.get("ps", "vmess"))
                    net = str(vmess_data.get("net", "")).lower()
                    fake_type = str(vmess_data.get("type", "")).lower()
                    tls_mode = str(vmess_data.get("tls", "")).lower()
                    cipher = vmess_data.get("scy", "auto") or "auto"
                    alter_id = vmess_data.get("aid", 0)

                    # 调整 network 类型
                    if fake_type == "http":
                        net = "http"
                    elif net == "http":
                        net = "h2"

                    proxy = {
                        "name": name,
                        "type": "vmess",
                        "server": vmess_data.get("add"),
                        "port": vmess_data.get("port"),
                        "uuid": vmess_data.get("id"),
                        "alterId": alter_id,
                        "cipher": cipher,
                        "tls": tls_mode.endswith("tls") or tls_mode == "reality",
                        "udp": True,
                        "xudp": True,
                        "skip-cert-verify": False,
                        "network": net
                    }

                    # TLS Reality 扩展
                    if proxy["tls"]:
                        proxy["client-fingerprint"] = vmess_data.get("fp", "chrome") or "chrome"
                        alpn = vmess_data.get("alpn")
                        if alpn:
                            proxy["alpn"] = alpn.split(",") if isinstance(alpn, str) else alpn
                        sni = vmess_data.get("sni")
                        if sni:
                            proxy["servername"] = sni

                        if tls_mode == "reality":
                            proxy["reality-opts"] = {
                                "public-key": vmess_data.get("pbk", ""),
                                "short-id": vmess_data.get("sid", "")
                            }

                    path = vmess_data.get("path", "/")
                    host = vmess_data.get("host")

                    # 不同 network 的扩展字段处理
                    if net == "tcp":
                        if fake_type == "http":
                            proxy["http-opts"] = {
                                "path": path,
                                "headers": {"Host": host} if host else {}
                            }
                    elif net == "http":
                        proxy["network"] = "http"
                        proxy["http-opts"] = {
                            "path": path,
                            "headers": {"Host": host} if host else {}
                        }
                    elif net == "h2":
                        proxy["h2-opts"] = {
                            "path": path,
                            "host": [host] if host else []
                        }

                    elif net == "ws":
                        ws_headers = {"Host": host} if host else {}
                        ws_headers["User-Agent"] = Converter.user_agent
                        ws_opts = {
                            "path": path,
                            "headers": ws_headers
                        }
                        # 补充 early-data 配置
                        early_data = vmess_data.get("ed")
                        if early_data:
                            try:
                                ws_opts["max-early-data"] = int(early_data)
                            except ValueError:
                                pass
                        early_data_header = vmess_data.get("edh")
                        if early_data_header:
                            ws_opts["early-data-header-name"] = early_data_header
                        proxy["ws-opts"] = ws_opts

                    elif net == "grpc":
                        proxy["grpc-opts"] = {
                            "grpc-service-name": path
                        }
                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"VMESS parse error: {e}") from e

            elif scheme == "vless":
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))
                    uuid = parsed.username or ""
                    server = parsed.hostname or ""
                    port = parsed.port or 443
                    tls_mode = query.get("security", "").lower()
                    tls = tls_mode == "tls" or tls_mode == "reality"
                    sni = query.get("sni", "")
                    flow = query.get("flow", "")
                    network = query.get("type", "tcp")
                    path = query.get("path", "")
                    host = query.get("host", "")
                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
                    proxy: Dict[str, Any] = {
                        "name": name,
                        "type": "vless",
                        "server": server,
                        "port": port,
                        "uuid": uuid,
                        "tls": tls,
                        "udp": True
                    }

                    if sni:
                        proxy["servername"] = sni
                    if flow:
                        proxy["flow"] = flow
                    if tls:
                        proxy["skip-cert-verify"] = Converter.strtobool(query.get("allowInsecure", "0"))
                    if network:
                        proxy["network"] = network
                        if network in ["ws", "httpupgrade"]:
                            headers = {"User-Agent": Converter.user_agent}
                            if host:
                                headers["Host"] = host
                            ws_opts: Dict[str, Any] = {"path": path, "headers": headers}
                            try:
                                parsed_path = urlparse(path)
                                q = dict(parse_qsl(parsed_path.query))
                                if "ed" in q:
                                    med = int(q["ed"])
                                    if network == "ws":
                                        ws_opts["max-early-data"] = med
                                        ws_opts["early-data-header-name"] = q.get("eh", "Sec-WebSocket-Protocol")
                                elif network == "httpupgrade":
                                    ws_opts["v2ray-http-upgrade-fast-open"] = True
                                if "eh" in q and q["eh"]:
                                    ws_opts["early-data-header-name"] = q["eh"]
                            except Exception:
                                pass
                            proxy["ws-opts"] = ws_opts

                        elif network == "grpc":
                            proxy["grpc-opts"] = {
                                "grpc-service-name": query.get("serviceName", "")

                            }

                    if tls_mode == "reality":
                        proxy["reality-opts"] = {
                            "public-key": query.get("pbk", "")
                        }
                        if query.get("sid"):
                            proxy["reality-opts"]["short-id"] = query.get("sid", "")
                        proxy["client-fingerprint"] = query.get("fp", "chrome")
                        alpn = query.get("alpn", "")
                        if alpn:
                            proxy["alpn"] = alpn.split(",")
                    if tls_mode.endswith("tls"):
                        proxy["client-fingerprint"] = query.get("fp", "chrome")
                        alpn = query.get("alpn", "")
                        if alpn:
                            proxy["alpn"] = alpn.split(",")
                    proxies.append(proxy)

                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"VLESS parse error: {e}") from e

            elif scheme == "trojan":
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{parsed.hostname}:{parsed.port}"))

                    trojan = {
                        "name": name,
                        "type": "trojan",
                        "server": parsed.hostname,
                        "port": parsed.port or 443,
                        "password": parsed.username or "",
                        "udp": True,
                    }

                    # skip-cert-verify
                    try:
                        trojan["skip-cert-verify"] = Converter.strtobool(query.get("allowInsecure", "0"))
                    except ValueError:
                        trojan["skip-cert-verify"] = False

                    # optional fields
                    if "sni" in query:
                        trojan["sni"] = query["sni"]

                    alpn = query.get("alpn", "")
                    if alpn:
                        trojan["alpn"] = alpn.split(",")

                    network = query.get("type", "").lower()
                    if network:
                        trojan["network"] = network

                    if network == "ws":
                        headers = {"User-Agent": Converter.user_agent}
                        trojan["ws-opts"] = {
                            "path": query.get("path", "/"),
                            "headers": headers
                        }

                    elif network == "grpc":
                        trojan["grpc-opts"] = {
                            "grpc-service-name": query.get("serviceName", "")
                        }

                    fp = query.get("fp", "")
                    trojan["client-fingerprint"] = fp if fp else "chrome"

                    proxies.append(trojan)

                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"Trojan parse error: {e}") from e

            elif scheme == "hysteria":
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{parsed.hostname}:{parsed.port}"))
                    hysteria = {
                        "name": name,
                        "type": "hysteria",
                        "server": parsed.hostname,
                        "port": parsed.port,
                        "auth_str": parsed.username or query.get("auth", ""),
                        "obfs": query.get("obfs", ""),
                        "sni": query.get("peer", ""),
                        "protocol": query.get("protocol", "")
                    }

                    up = query.get("up", "")
                    down = query.get("down", "")
                    if not up:
                        up = query.get("upmbps", "")
                    if not down:
                        down = query.get("downmbps", "")
                    hysteria["up"] = up
                    hysteria["down"] = down

                    # alpn split
                    alpn = query.get("alpn", "")
                    if alpn:
                        hysteria["alpn"] = alpn.split(",")

                    # skip-cert-verify
                    try:
                        hysteria["skip-cert-verify"] = Converter.strtobool(query.get("insecure", "false"))
                    except ValueError:
                        hysteria["skip-cert-verify"] = False

                    proxies.append(hysteria)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"Hysteria parse error: {e}") from e

            elif scheme in ("socks", "socks5", "socks5h"):
                try:
                    parsed = urlparse(line)
                    server = parsed.hostname
                    port = parsed.port
                    username = parsed.username or ""
                    password = parsed.password or ""
                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))

                    proxy = {
                        "name": name,
                        "type": "socks5",
                        "server": server,
                        "port": port,
                        "username": username,
                        "password": password,
                        "udp": True
                    }
                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"SOCKS5 parse error: {e}") from e

            elif scheme == "ss":
                try:
                    parsed = urlparse(line)
                    # 兼容 ss://base64 或 ss://base64#name
                    if parsed.fragment:
                        name = Converter.unique_name(names, unquote(parsed.fragment))
                    else:
                        name = Converter.unique_name(names, "ss")
                    if parsed.port is None:
                        base64_body = body.split("#")[0]
                        parsed = urlparse(f"ss://{Converter.decode_base64(base64_body).decode('utf-8')}")
                    cipher_raw = parsed.username
                    cipher = cipher_raw
                    password = parsed.password
                    if not password:
                        dc_buf = Converter.decode_base64(cipher_raw).decode('utf-8')
                        if dc_buf.startswith("ss://"):
                            dc_buf = dc_buf[len("ss://"):]
                            dc_buf = Converter.decode_base64(dc_buf).decode('utf-8')
                        cipher, password = dc_buf.split(":", 1)
                    server = parsed.hostname
                    port = parsed.port
                    query = dict(parse_qsl(parsed.query))
                    proxy = {
                        "name": name,
                        "type": "ss",
                        "server": server,
                        "port": port,
                        "cipher": cipher,
                        "password": password,
                        "udp": True
                    }
                    plugin = query.get("plugin")
                    if plugin and ";" in plugin:
                        query_string = "pluginName=" + plugin.replace(";", "&")
                        plugin_info = parse_qs(query_string)
                        plugin_name = plugin_info.get("pluginName", [""])[0]

                        if "obfs" in plugin_name:
                            proxy["plugin"] = "obfs"
                            proxy["plugin-opts"] = {
                                "mode": plugin_info.get("obfs", [""])[0],
                                "host": plugin_info.get("obfs-host", [""])[0],
                            }
                        elif "v2ray-plugin" in plugin_name:
                            proxy["plugin"] = "v2ray-plugin"
                            proxy["plugin-opts"] = {
                                "mode": plugin_info.get("mode", [""])[0],
                                "host": plugin_info.get("host", [""])[0],
                                "path": plugin_info.get("path", [""])[0],
                                "tls": "tls" in plugin,
                            }
                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"SS parse error: {e}") from e

            elif scheme == "ssr":
                try:
                    decoded = Converter.decode_base64(body).decode()
                    parts, _, params_str = decoded.partition("/?")
                    host, port, protocol, method, obfs, password_enc = parts.split(":")

                    password = Converter.decode_base64(password_enc).decode()
                    params = parse_qs(params_str)

                    remarks = Converter.decode_base64(params.get("remarks", [""])[0]).decode()
                    obfsparam = Converter.decode_base64(params.get("obfsparam", [""])[0]).decode()
                    protoparam = Converter.decode_base64(params.get("protoparam", [""])[0]).decode()

                    name = Converter.unique_name(names, remarks or f"{host}:{port}")

                    proxy = {
                        "name": name,
                        "type": "ssr",
                        "server": host,
                        "port": port,
                        "cipher": method,
                        "password": password,
                        "obfs": obfs,
                        "protocol": protocol,
                        "udp": True
                    }

                    if obfsparam:
                        proxy["obfs-param"] = obfsparam
                    if protoparam:
                        proxy["protocol-param"] = protoparam

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"SSR parse error: {e}") from e

            elif scheme == "tuic":
                try:
                    parsed = urlparse(line)
                    query = parse_qs(parsed.query)

                    user = parsed.username or ""
                    password = parsed.password or ""
                    server = parsed.hostname
                    port = parsed.port or 443

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
                    proxy = {
                        "name": name,
                        "type": "tuic",
                        "server": server,
                        "port": port,
                        "udp": True
                    }

                    if password:
                        proxy["uuid"] = user
                        proxy["password"] = password
                    else:
                        proxy["token"] = user

                    if "congestion_control" in query:
                        proxy["congestion-controller"] = query["congestion_control"][0]
                    if "alpn" in query:
                        proxy["alpn"] = query["alpn"][0].split(",")
                    if "sni" in query:
                        proxy["sni"] = query["sni"][0]
                    if query.get("disable_sni", ["0"])[0] == "1":
                        proxy["disable-sni"] = True
                    if "udp_relay_mode" in query:
                        proxy["udp-relay-mode"] = query["udp_relay_mode"][0]

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"TUIC parse error: {e}") from e

            elif scheme == "anytls":
                try:
                    parsed = urlparse(line)
                    query = parse_qs(parsed.query)

                    username = parsed.username or ""
                    password = parsed.password or username
                    server = parsed.hostname
                    port = parsed.port
                    insecure = query.get("insecure", ["0"])[0] == "1"
                    sni = query.get("sni", [""])[0]
                    fingerprint = query.get("hpkp", [""])[0]

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
                    proxy = {
                        "name": name,
                        "type": "anytls",
                        "server": server,
                        "port": port,
                        "username": username,
                        "password": password,
                        "sni": sni,
                        "fingerprint": fingerprint,
                        "skip-cert-verify": insecure,
                        "udp": True
                    }

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"AnyTLS parse error: {e}") from e

            elif scheme in ("hysteria2", "hy2"):
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))
                    password = parsed.username or ""
                    server = parsed.hostname
                    port = parsed.port or 443
                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
                    proxy = {
                        "name": name,
                        "type": "hysteria2",
                        "server": server,
                        "port": port,
                        "password": password,
                        "obfs": query.get("obfs", ""),
                        "obfs-password": query.get("obfs-password", ""),
                        "sni": query.get("sni", ""),
                        "skip-cert-verify": Converter.strtobool(query.get("insecure", "false")),
                        "down": query.get("down", ""),
                        "up": query.get("up", ""),
                    }
                    if "pinSHA256" in query:
                        proxy["fingerprint"] = query.get("pinSHA256", "")
                    if "alpn" in query:
                        proxy["alpn"] = query["alpn"].split(",")

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"Hysteria2 parse error: {e}") from e

        if not proxies:
            if not skip_exception:
                raise ValueError("convert v2ray subscribe error: format invalid")

        return proxies
