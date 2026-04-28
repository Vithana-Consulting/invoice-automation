from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.exceptions import RuleEngineError

logger = logging.getLogger(__name__)

# Supported operators
STRING_OPS = {"equals", "not_equals", "contains", "starts_with", "ends_with", "in_list"}
NUMBER_OPS = {"equals", "not_equals", "greater_than", "less_than", "greater_than_or_equal", "less_than_or_equal"}
UNARY_OPS = {"is_empty", "is_not_empty"}
ALL_OPS = STRING_OPS | NUMBER_OPS | UNARY_OPS

# Fields that can be evaluated
EVALUABLE_FIELDS = {
    "vendor_name", "resolved_vendor_name", "invoice_number",
    "total_amount", "tax_amount", "currency", "source",
    "invoice_date", "gst_number",
}

NUMERIC_FIELDS = {"total_amount", "tax_amount"}


def evaluate_rule(conditions: dict, invoice_fields: Dict[str, Any]) -> bool:
    """Recursively evaluate a condition tree against invoice field values.

    Args:
        conditions: A condition tree node. Either a group node with 'operator'
                   and 'conditions' keys, or a leaf node with 'field', 'op', 'value'.
        invoice_fields: Dict of field name -> value from the invoice draft.

    Returns:
        True if the conditions match, False otherwise.

    Raises:
        RuleEngineError: If the condition tree is malformed.
    """
    if not conditions:
        return False

    # Group node (AND / OR)
    if "operator" in conditions:
        operator = conditions["operator"].upper()
        children = conditions.get("conditions", [])
        if not children:
            return False
        if operator == "AND":
            return all(evaluate_rule(c, invoice_fields) for c in children)
        elif operator == "OR":
            return any(evaluate_rule(c, invoice_fields) for c in children)
        else:
            raise RuleEngineError(f"Unknown group operator: {operator}")

    # Leaf node (single condition)
    field = conditions.get("field")
    op = conditions.get("op")
    expected = conditions.get("value")

    if not field or not op:
        raise RuleEngineError(f"Invalid condition: missing field or op: {conditions}")

    if field not in EVALUABLE_FIELDS:
        raise RuleEngineError(f"Unknown field: {field}")

    if op not in ALL_OPS:
        raise RuleEngineError(f"Unknown operator: {op}")

    actual = invoice_fields.get(field)
    return _evaluate_condition(actual, op, expected, field)


def _evaluate_condition(actual: Any, op: str, expected: Any, field: str) -> bool:
    """Evaluate a single condition."""
    # Unary operators
    if op == "is_empty":
        return actual is None or actual == ""
    if op == "is_not_empty":
        return actual is not None and actual != ""

    # Null handling
    if actual is None:
        return False

    # Numeric comparison
    if field in NUMERIC_FIELDS:
        try:
            actual_num = float(actual)
            expected_num = float(expected)
        except (ValueError, TypeError):
            return False

        if op == "equals":
            return actual_num == expected_num
        if op == "not_equals":
            return actual_num != expected_num
        if op == "greater_than":
            return actual_num > expected_num
        if op == "less_than":
            return actual_num < expected_num
        if op == "greater_than_or_equal":
            return actual_num >= expected_num
        if op == "less_than_or_equal":
            return actual_num <= expected_num

    # String comparison (case-insensitive)
    actual_str = str(actual).lower()
    expected_str = str(expected).lower() if expected is not None else ""

    if op == "equals":
        return actual_str == expected_str
    if op == "not_equals":
        return actual_str != expected_str
    if op == "contains":
        return expected_str in actual_str
    if op == "starts_with":
        return actual_str.startswith(expected_str)
    if op == "ends_with":
        return actual_str.endswith(expected_str)
    if op == "in_list":
        items = [i.strip().lower() for i in expected_str.split(",")]
        return actual_str in items

    return False


def apply_rules(rules: List[dict], invoice_fields: Dict[str, Any]) -> Optional[dict]:
    """Apply rules in priority order. First match wins.

    Args:
        rules: List of rule dicts with 'id', 'conditions_json', 'action_type', 'action_value'.
               Must be sorted by priority ASC.
        invoice_fields: Dict of invoice field values.

    Returns:
        The first matching rule dict, or None if no rule matches.
    """
    for rule in rules:
        try:
            conditions = rule.get("conditions_json")
            if isinstance(conditions, str):
                conditions = json.loads(conditions)
            if evaluate_rule(conditions, invoice_fields):
                logger.info("Rule '%s' (id=%s) matched", rule.get("name"), rule.get("id"))
                return rule
        except RuleEngineError as e:
            logger.warning("Error evaluating rule %s: %s", rule.get("id"), e)
            continue
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in rule %s: %s", rule.get("id"), e)
            continue
    return None
