import re
from typing import List, Dict, Any, Optional, Union

from pydantic import ValidationError

from ..models.rule import RuleType, Action, RoutingRuleType, MatchRule, ClashRule, LogicRule, SubRule


class ClashRuleParser:
    """Parser for Clash routing rules"""

    @staticmethod
    def parse_rule_line(line: str) -> Optional[RuleType]:
        """Parse a single rule line"""
        line = line.strip()
        try:
            # Handle logic rules (AND, OR, NOT)
            if line.startswith(('AND,', 'OR,', 'NOT,')):
                return ClashRuleParser._parse_logic_rule(line)
            elif line.startswith('MATCH'):
                return ClashRuleParser._parse_match_rule(line)
            elif line.startswith('SUB-RULE'):
                return ClashRuleParser._parse_sub_rule(line)
            # Handle regular rules
            return ClashRuleParser._parse_regular_rule(line)

        except (ValidationError, TypeError, ValueError, RecursionError):
            return None

    @staticmethod
    def parse_rule_dict(clash_rule: Dict[str, Any]) -> Optional[RuleType]:
        if not clash_rule:
            return None
        try:
            if clash_rule.get("type") in ('AND', 'OR', 'NOT'):
                conditions = clash_rule.get("conditions")
                if not conditions:
                    return None
                conditions = [ClashRuleParser._remove_parenthesis(f"({c})") for c in conditions]
                conditions_str = ','.join(conditions)
                conditions_str = f"({conditions_str})"
                raw_rule = f"{clash_rule.get('type')},{conditions_str},{clash_rule.get('action')}"
                rule = ClashRuleParser._parse_logic_rule(raw_rule)
            elif clash_rule.get("type") == 'MATCH':
                raw_rule = f"{clash_rule.get('type')},{clash_rule.get('action')}"
                rule = ClashRuleParser._parse_match_rule(raw_rule)
            elif clash_rule.get("type") == 'SUB-RULE':
                condition = clash_rule.get("condition")
                if not condition:
                    return None
                condition_str = f"({condition})"
                condition_str = ClashRuleParser._remove_parenthesis(condition_str)
                raw_rule = f"{clash_rule.get('type')},{condition_str},{clash_rule.get('action')}"
                rule = ClashRuleParser._parse_sub_rule(raw_rule)
            else:
                raw_rule = f"{clash_rule.get('type')},{clash_rule.get('payload')},{clash_rule.get('action')}"
                if clash_rule.get('additional_params'):
                    raw_rule += f',{clash_rule.get('additional_params')}'
                rule = ClashRuleParser._parse_regular_rule(raw_rule)

        except (ValidationError, TypeError, ValueError):
            return None

        return rule

    @staticmethod
    def _parse_match_rule(line: str) -> MatchRule:
        parts = line.split(',')
        if len(parts) < 2:
            raise ValueError(f"Invalid rule format: {line}")
        action = parts[1].strip()
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

        rule_type_str = parts[0].upper().strip()
        payload = parts[1].strip()
        action = parts[2].strip()

        if not payload or not rule_type_str:
            raise ValueError(f"Invalid rule format: {line}")

        additional_params = parts[3].strip() if len(parts) > 3 else None

        # Validate rule type
        try:
            rule_type = RoutingRuleType(rule_type_str)
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
    def _parenthesis_balance(s: str) -> Optional[int]:
        """Calculate balance of parenthesis"""
        balance = 0
        for i, char in enumerate(s):
            if char == '(':
                balance += 1
            elif char == ')':
                balance -= 1
            if balance < 0:
                return None
        return balance

    @staticmethod
    def _parse_logic_rule(line: str) -> LogicRule:
        """Parse a logic rule (AND, OR, NOT)"""
        # Extract logic type
        logic_type_str, rest = line.split(',', 1)
        logic_type = RoutingRuleType(logic_type_str.upper().strip())
        last_comma_index = rest.rfind(',')
        if last_comma_index == -1:
            raise ValueError(f"Invalid logic rule format: {line}")
        action_str = rest[last_comma_index + 1:]
        conditions_str = rest[:last_comma_index]

        # Find the matching parenthesis for the conditions block to separate conditions from action
        balance = ClashRuleParser._parenthesis_balance(conditions_str)
        if balance != 0:
            raise ValueError(f"Mismatched parentheses in logic rule: {line}")

        action = action_str.strip()
        # Try to convert action to enum
        try:
            action_enum = Action(action.upper())
            final_action = action_enum
        except ValueError:
            final_action = action

        conditions = ClashRuleParser._parse_logic_conditions(conditions_str)

        return LogicRule(
            rule_type=logic_type,
            conditions=conditions,
            action=final_action,
            raw_rule=line
        )

    @staticmethod
    def _parse_sub_rule(line: str) -> SubRule:
        """Parse a sub-rule"""
        rule_type_str, rest = line.split(',', 1)
        rule_type = RoutingRuleType(rule_type_str.upper().strip())
        if rule_type != RoutingRuleType.SUB_RULE:
            raise ValueError(f"{rule_type.value} is not a sub-rule")
        last_comma_index = rest.rfind(',')
        if last_comma_index == -1:
            raise ValueError(f"Invalid sub-rule format: {line}")
        condition_str = rest[:last_comma_index]
        action_str = rest[last_comma_index + 1:]

        balance = ClashRuleParser._parenthesis_balance(condition_str)
        if balance != 0:
            raise ValueError(f"Mismatched parentheses in sub-rule: {line}")

        conditions = ClashRuleParser._parse_logic_conditions(condition_str)
        if len(conditions) != 1:
            raise ValueError(f"Invalid sub-rule condition: {condition_str}")

        return SubRule(
            condition=conditions[0],
            action=action_str,
            raw_rule=line
        )

    @staticmethod
    def _remove_parenthesis(_con_str: str):
        balance = 0
        filed_list = []
        field = ''
        for i, char in enumerate(_con_str):
            if char == '(':
                balance += 1
            elif char == ')':
                balance -= 1
            elif char == ',':
                if balance == 1:
                    filed_list.append(field)
            else:
                if balance == 1 and char:
                    field = field + char
        if not any(filed_list):
            return ClashRuleParser._remove_parenthesis(_con_str[1:-1])
        else:
            return _con_str

    @staticmethod
    def _parse_logic_conditions(conditions_str: str) -> List[Union[ClashRule, LogicRule]]:
        """
        Parse conditions within logic rules, supporting nested logic.
        examples of conditions_str:
            (DOMAIN,baidu.com)
            (AND,(DOMAIN,baidu.com),(NETWORK,TCP))
        """

        def __extract_condition_strings(_con_str: str) -> List[str]:
            # Split conditions string by top-level commas
            _con_str = _con_str.replace(' ', '')
            _con_str = ClashRuleParser._remove_parenthesis(_con_str)
            _condition_strings = []
            balance = 0
            start = 0

            for i, char in enumerate(_con_str):
                if char == '(':
                    if balance == 0:
                        start = i
                    balance += 1
                elif char == ')':
                    balance -= 1
                    if balance == 0:
                        _condition_strings.append(_con_str[start:i + 1])
            return _condition_strings

        conditions = []

        if not conditions_str:
            return conditions
        condition_strings = __extract_condition_strings(conditions_str)
        for cond_str in condition_strings:
            cond_str = cond_str.strip()
            if not cond_str.startswith('(') or not cond_str.endswith(')'):
                raise ValueError(f"Invalid nested logic rule format: {cond_str}")
            content = cond_str[1:-1]  # remove parentheses
            if content.upper().startswith(('AND,', 'OR,', 'NOT,')):
                # This is a nested logic rule.
                parts = content.split(',', 1)
                logic_type_str = parts[0].strip().upper()
                logic_type = RoutingRuleType(logic_type_str)

                nested_conditions_str = parts[1]
                nested_conditions = ClashRuleParser._parse_logic_conditions(f'({nested_conditions_str})')

                condition = LogicRule(
                    rule_type=logic_type,
                    conditions=nested_conditions,
                    action=Action.COMPATIBLE,  # No action for conditions
                    raw_rule=content
                )
                conditions.append(condition)
            else:
                # Simple rule
                parts = content.split(',', 1)
                if len(parts) == 2:
                    rule_type_str, payload = parts
                    try:
                        rule_type = RoutingRuleType(rule_type_str.upper().strip())
                        condition = ClashRule(
                            rule_type=rule_type,
                            payload=payload.strip(),
                            action=Action.COMPATIBLE,  # Logic conditions don't have actions
                            raw_rule=content
                        )
                        conditions.append(condition)
                    except ValueError:
                        raise ValueError(f"Invalid rule format: {content}")
        return conditions


    @staticmethod
    def action_string(action: Union[Action, str]) -> str:
        return action.value if isinstance(action, Action) else action

    @staticmethod
    def parse_rules(rules_text: str) -> List[Union[ClashRule, LogicRule, MatchRule]]:
        """Parse multiple rules from text, preserving order and priority"""
        rules = []
        lines = rules_text.strip().split('\n')

        for line in lines:
            rule = ClashRuleParser.parse_rule_line(line)
            if rule:
                rules.append(rule)

        return rules

    @staticmethod
    def validate_rule(rule: ClashRule) -> bool:
        """Validate a parsed rule"""
        try:
            # Basic validation based on rule type
            if rule.rule_type in [RoutingRuleType.IP_CIDR, RoutingRuleType.IP_CIDR6]:
                # Validate CIDR format
                return '/' in rule.payload

            elif rule.rule_type == RoutingRuleType.DST_PORT or rule.rule_type == RoutingRuleType.SRC_PORT:
                # Validate port number/range
                return rule.payload.isdigit() or '-' in rule.payload

            elif rule.rule_type == RoutingRuleType.NETWORK:
                # Validate network type
                return rule.payload.lower() in ['tcp', 'udp']

            elif rule.rule_type == RoutingRuleType.DOMAIN_REGEX or rule.rule_type == RoutingRuleType.PROCESS_PATH_REGEX:
                # Try to compile regex
                re.compile(rule.payload)
                return True

            return True

        except Exception:
            return False
