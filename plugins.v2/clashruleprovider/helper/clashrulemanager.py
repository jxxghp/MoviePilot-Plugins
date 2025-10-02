import time

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union, Iterator

from .clashruleparser import ClashRuleParser
from ..models.rule import Action, RoutingRuleType, MatchRule, ClashRule, LogicRule


@dataclass
class RuleItem:
    """Clash rule item"""
    rule: Union[ClashRule, LogicRule, MatchRule]
    remark: str = field(default="")
    time_modified: float = field(default=0)

class ClashRuleManager:
    """Clash rule manager"""
    def __init__(self):
        self.rules: List[RuleItem] = []

    def import_rules(self, rules_list: List[Dict[str, str]]):
        self.rules = []
        for r in rules_list:
            rule = ClashRuleParser.parse_rule_line(r['rule'])
            if rule is None:
                continue
            remark = r.get('remark', '')
            time_modified = r.get('time_modified', time.time())
            self.rules.append(RuleItem(rule=rule, remark=remark, time_modified=time_modified))

    def export_rules(self) -> List[Dict[str, str]]:
        rules_list = []
        for rule in self.rules:
            rules_list.append({'rule': str(rule.rule), 'remark': rule.remark, 'time_modified': rule.time_modified})
        return rules_list

    def append_rules(self, clash_rules: List[RuleItem]):
        self.rules.extend(clash_rules)

    def insert_rule_at_priority(self, clash_rule: RuleItem, priority: int):
        self.rules.insert(priority, clash_rule)

    def update_rule_at_priority(self, clash_rule: RuleItem, src_priority: int, dst_priority) -> bool:
        if len(self.rules) > src_priority >= 0:
            if src_priority == dst_priority:
                self.rules[src_priority] = clash_rule
            else:
                self.remove_rule_at_priority(src_priority)
                self.insert_rule_at_priority(clash_rule, dst_priority)
            return True
        return False

    def get_rule_at_priority(self, priority: int) -> Optional[RuleItem]:
        """Get rule item by priority"""
        if len(self.rules) > priority >= 0:
            return self.rules[priority]
        return None

    def remove_rule_at_priority(self, priority: int) -> Optional[RuleItem]:
        """Remove rule at specific priority"""
        if 0 <= priority < len(self.rules):
            return self.rules.pop(priority)
        return None

    def remove_rules_by_lambda(self, condition: Callable[[RuleItem], bool]):
        """Remove rules by lambda"""
        initial_count = len(self.rules)
        i = 0
        while i < len(self.rules):
            if condition(self.rules[i]):
                del self.rules[i]
            else:
                i += 1
        return initial_count - len(self.rules)

    def move_rule_priority(self, from_priority: int, to_priority: int) -> bool:
        """Move rule priority to priority"""
        clash_rule = self.remove_rule_at_priority(from_priority)
        if not clash_rule:
            return False
        self.insert_rule_at_priority(clash_rule, to_priority)
        return True

    def filter_rules_by_condition(self, condition: Callable[[RuleItem], bool]):
        """Filter rules by condition"""
        return [clash_rule for clash_rule in self.rules if condition(clash_rule)]

    def filter_rules_by_type(self, rule_type: RoutingRuleType) -> List[RuleItem]:
        """Filter rules by type"""
        return [clash_rule for clash_rule in self.rules
                if isinstance(clash_rule.rule, ClashRule) and clash_rule.rule.rule_type == rule_type]

    def filter_rules_by_action(self, action: Union[Action, str]) -> List[RuleItem]:
        """Filter rules by action"""
        return [clash_rule for clash_rule in self.rules if clash_rule.rule.action == action]

    def has_rule(self, clash_rule: Union[ClashRule, LogicRule, MatchRule]) -> bool:
        """Check if there is an identical rule"""
        return any(r.rule == clash_rule for r in self.rules)

    def has_rule_item(self, clash_rule: RuleItem) -> bool:
        return any(clash_rule.remark == r.remark and r.rule == clash_rule.rule for r in self.rules)

    def reorder_rules(self, moved_priority: int, target_priority: int) -> RuleItem:
        """Reorder the rules"""
        if not (0 <= moved_priority < len(self.rules)):
            raise IndexError("moved_priority out of range")
        if not (0 <= target_priority < len(self.rules)):
            raise IndexError("target_priority out of range")
        rule = self.rules.pop(moved_priority)
        self.rules.insert(target_priority, rule)
        return rule

    def to_list(self) -> List[Dict[str, Any]]:
        """Convert parsed rules to a list"""
        result = []
        for priority, rule_item in enumerate(self.rules):
            rule_dict = {'remark': rule_item.remark, 'time_modified': rule_item.time_modified,'priority': priority,
                         **rule_item.rule.to_dict()}
            result.append(rule_dict)
        return result

    def clear(self):
        self.rules.clear()

    def __len__(self) -> int:
        return len(self.rules)

    def __iter__(self) -> Iterator[RuleItem]:
        return iter(self.rules)
