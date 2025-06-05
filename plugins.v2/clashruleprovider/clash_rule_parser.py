import re
from typing import List, Dict, Any, Optional, Union, Callable
from dataclasses import dataclass
from enum import Enum


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
    additional_params: Optional[List[str]] = None
    raw_rule: str = ""
    priority: int = 0

    def __post_init__(self):
        if self.additional_params is None:
            self.additional_params = []

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
            print(f"Error parsing rule '{line}': {e}")
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
            return ClashRuleParser._parse_logic_rule(raw_rule)
        elif clash_rule.get("type") == 'MATCH':
            raw_rule = f"{clash_rule.get('type')},{clash_rule.get('action')}"
            return ClashRuleParser._parse_match_rule(raw_rule)
        else:
            raw_rule = f"{clash_rule.get('type')},{clash_rule.get('payload')},{clash_rule.get('action')}"
            return ClashRuleParser._parse_regular_rule(raw_rule)

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

        if len(parts) < 3:
            raise ValueError(f"Invalid rule format: {line}")

        rule_type_str = parts[0].upper()
        payload = parts[1]
        action = parts[2]

        if not payload or not rule_type_str:
            raise ValueError(f"Invalid rule format: {line}")

        additional_params = parts[3:] if len(parts) > 3 else []

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
                print(f"Unknown rule type in logic condition: {rule_type_str}")

        return conditions

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

    def to_string(self) -> List[str]:
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
        for index, existing_rule in enumerate(self.rules):
            if existing_rule.priority == priority:
                self.rules[index] = clash_rule
                self.rules[index].priority = priority
                return True
        return False

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

    def filter_rules_by_type(self, rule_type: RuleType) -> List[ClashRule]:
        """Filter rules by type"""
        return [rule for rule in self.rules
                if isinstance(rule, ClashRule) and rule.rule_type == rule_type]

    def filter_rules_by_action(self, action: Union[Action, str]) -> List[Union[ClashRule, LogicRule, MatchRule]]:
        """Filter rules by action"""
        return [rule for rule in self.rules if rule.action == action]

    def has_rule(self, clash_rule: Union[ClashRule, LogicRule, MatchRule]) -> bool:
        for rule in self.rules:
            if rule.rule_type == clash_rule.rule_type and rule.action == clash_rule.action \
                    and rule.payload == clash_rule.payload:
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
