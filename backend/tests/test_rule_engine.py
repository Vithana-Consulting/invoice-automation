"""Tests for the rule engine - the most critical new component."""

import json
import pytest

from app.rules.engine import evaluate_rule, apply_rules, _evaluate_condition


# ─── Simple leaf conditions ────────────────────────────────────────────────

class TestLeafConditions:
    def test_equals_string(self):
        cond = {"field": "vendor_name", "op": "equals", "value": "Google"}
        assert evaluate_rule(cond, {"vendor_name": "Google"}) is True
        assert evaluate_rule(cond, {"vendor_name": "google"}) is True  # case-insensitive
        assert evaluate_rule(cond, {"vendor_name": "Microsoft"}) is False

    def test_not_equals(self):
        cond = {"field": "vendor_name", "op": "not_equals", "value": "Google"}
        assert evaluate_rule(cond, {"vendor_name": "Microsoft"}) is True
        assert evaluate_rule(cond, {"vendor_name": "Google"}) is False

    def test_contains(self):
        cond = {"field": "vendor_name", "op": "contains", "value": "Google"}
        assert evaluate_rule(cond, {"vendor_name": "Google Private Limited"}) is True
        assert evaluate_rule(cond, {"vendor_name": "google pvt"}) is True
        assert evaluate_rule(cond, {"vendor_name": "Microsoft"}) is False

    def test_starts_with(self):
        cond = {"field": "vendor_name", "op": "starts_with", "value": "Google"}
        assert evaluate_rule(cond, {"vendor_name": "Google LLC"}) is True
        assert evaluate_rule(cond, {"vendor_name": "Not Google"}) is False

    def test_ends_with(self):
        cond = {"field": "vendor_name", "op": "ends_with", "value": "Limited"}
        assert evaluate_rule(cond, {"vendor_name": "Google Private Limited"}) is True
        assert evaluate_rule(cond, {"vendor_name": "Google LLC"}) is False

    def test_in_list(self):
        cond = {"field": "currency", "op": "in_list", "value": "USD,EUR,GBP"}
        assert evaluate_rule(cond, {"currency": "USD"}) is True
        assert evaluate_rule(cond, {"currency": "eur"}) is True
        assert evaluate_rule(cond, {"currency": "INR"}) is False

    def test_greater_than(self):
        cond = {"field": "total_amount", "op": "greater_than", "value": 10000}
        assert evaluate_rule(cond, {"total_amount": 15000}) is True
        assert evaluate_rule(cond, {"total_amount": 10000}) is False
        assert evaluate_rule(cond, {"total_amount": 5000}) is False

    def test_less_than(self):
        cond = {"field": "total_amount", "op": "less_than", "value": 1000}
        assert evaluate_rule(cond, {"total_amount": 500}) is True
        assert evaluate_rule(cond, {"total_amount": 1500}) is False

    def test_greater_than_or_equal(self):
        cond = {"field": "total_amount", "op": "greater_than_or_equal", "value": 10000}
        assert evaluate_rule(cond, {"total_amount": 10000}) is True
        assert evaluate_rule(cond, {"total_amount": 10001}) is True
        assert evaluate_rule(cond, {"total_amount": 9999}) is False

    def test_is_empty(self):
        cond = {"field": "gst_number", "op": "is_empty", "value": None}
        assert evaluate_rule(cond, {"gst_number": None}) is True
        assert evaluate_rule(cond, {"gst_number": ""}) is True
        assert evaluate_rule(cond, {"gst_number": "29ABCDE1234F1Z5"}) is False

    def test_is_not_empty(self):
        cond = {"field": "gst_number", "op": "is_not_empty", "value": None}
        assert evaluate_rule(cond, {"gst_number": "29ABCDE1234F1Z5"}) is True
        assert evaluate_rule(cond, {"gst_number": ""}) is False
        assert evaluate_rule(cond, {"gst_number": None}) is False

    def test_null_field_returns_false(self):
        cond = {"field": "vendor_name", "op": "equals", "value": "Google"}
        assert evaluate_rule(cond, {"vendor_name": None}) is False
        assert evaluate_rule(cond, {}) is False


# ─── Group conditions (AND / OR) ──────────────────────────────────────────

class TestGroupConditions:
    def test_and_all_true(self):
        cond = {
            "operator": "AND",
            "conditions": [
                {"field": "vendor_name", "op": "contains", "value": "Google"},
                {"field": "total_amount", "op": "greater_than", "value": 1000},
            ],
        }
        assert evaluate_rule(cond, {"vendor_name": "Google LLC", "total_amount": 5000}) is True

    def test_and_one_false(self):
        cond = {
            "operator": "AND",
            "conditions": [
                {"field": "vendor_name", "op": "contains", "value": "Google"},
                {"field": "total_amount", "op": "greater_than", "value": 10000},
            ],
        }
        assert evaluate_rule(cond, {"vendor_name": "Google LLC", "total_amount": 5000}) is False

    def test_or_one_true(self):
        cond = {
            "operator": "OR",
            "conditions": [
                {"field": "vendor_name", "op": "contains", "value": "Google"},
                {"field": "vendor_name", "op": "contains", "value": "Microsoft"},
            ],
        }
        assert evaluate_rule(cond, {"vendor_name": "Google LLC"}) is True
        assert evaluate_rule(cond, {"vendor_name": "Microsoft Corp"}) is True
        assert evaluate_rule(cond, {"vendor_name": "Apple Inc"}) is False

    def test_or_all_false(self):
        cond = {
            "operator": "OR",
            "conditions": [
                {"field": "vendor_name", "op": "equals", "value": "Google"},
                {"field": "vendor_name", "op": "equals", "value": "Microsoft"},
            ],
        }
        assert evaluate_rule(cond, {"vendor_name": "Apple"}) is False


# ─── Nested conditions ────────────────────────────────────────────────────

class TestNestedConditions:
    def test_nested_and_or(self):
        """IF vendor contains Google AND (amount > 10000 OR currency = USD)"""
        cond = {
            "operator": "AND",
            "conditions": [
                {"field": "vendor_name", "op": "contains", "value": "Google"},
                {
                    "operator": "OR",
                    "conditions": [
                        {"field": "total_amount", "op": "greater_than", "value": 10000},
                        {"field": "currency", "op": "equals", "value": "USD"},
                    ],
                },
            ],
        }
        # Google + high amount
        assert evaluate_rule(cond, {"vendor_name": "Google LLC", "total_amount": 15000, "currency": "INR"}) is True
        # Google + USD
        assert evaluate_rule(cond, {"vendor_name": "Google LLC", "total_amount": 500, "currency": "USD"}) is True
        # Google + low amount + INR
        assert evaluate_rule(cond, {"vendor_name": "Google LLC", "total_amount": 500, "currency": "INR"}) is False
        # Not Google
        assert evaluate_rule(cond, {"vendor_name": "Microsoft", "total_amount": 50000, "currency": "USD"}) is False

    def test_deeply_nested(self):
        cond = {
            "operator": "OR",
            "conditions": [
                {
                    "operator": "AND",
                    "conditions": [
                        {"field": "source", "op": "equals", "value": "gmail"},
                        {"field": "vendor_name", "op": "contains", "value": "AWS"},
                    ],
                },
                {
                    "operator": "AND",
                    "conditions": [
                        {"field": "source", "op": "equals", "value": "stripe"},
                        {"field": "total_amount", "op": "greater_than", "value": 5000},
                    ],
                },
            ],
        }
        # Gmail + AWS
        assert evaluate_rule(cond, {"source": "gmail", "vendor_name": "AWS Services", "total_amount": 100}) is True
        # Stripe + high amount
        assert evaluate_rule(cond, {"source": "stripe", "vendor_name": "Some Vendor", "total_amount": 10000}) is True
        # Gmail + not AWS
        assert evaluate_rule(cond, {"source": "gmail", "vendor_name": "Microsoft", "total_amount": 100}) is False


# ─── apply_rules (first-match-wins) ───────────────────────────────────────

class TestApplyRules:
    def test_first_match_wins(self):
        rules = [
            {
                "id": 1,
                "name": "Google to Zoho",
                "conditions_json": json.dumps({"field": "vendor_name", "op": "contains", "value": "Google"}),
                "action_type": "set_push_to",
                "action_value": "zoho",
            },
            {
                "id": 2,
                "name": "Everything to Tally",
                "conditions_json": json.dumps({"field": "vendor_name", "op": "is_not_empty", "value": None}),
                "action_type": "set_push_to",
                "action_value": "tally",
            },
        ]
        # Google matches rule 1
        result = apply_rules(rules, {"vendor_name": "Google LLC"})
        assert result is not None
        assert result["id"] == 1
        assert result["action_value"] == "zoho"

        # Microsoft skips rule 1, matches rule 2
        result = apply_rules(rules, {"vendor_name": "Microsoft"})
        assert result is not None
        assert result["id"] == 2
        assert result["action_value"] == "tally"

    def test_no_match(self):
        rules = [
            {
                "id": 1,
                "name": "Google only",
                "conditions_json": json.dumps({"field": "vendor_name", "op": "equals", "value": "Google"}),
                "action_type": "set_push_to",
                "action_value": "zoho",
            },
        ]
        result = apply_rules(rules, {"vendor_name": "Microsoft"})
        assert result is None

    def test_empty_rules(self):
        result = apply_rules([], {"vendor_name": "Google"})
        assert result is None

    def test_malformed_rule_skipped(self):
        rules = [
            {
                "id": 1,
                "name": "Bad rule",
                "conditions_json": "invalid json{{{",
                "action_type": "set_push_to",
                "action_value": "zoho",
            },
            {
                "id": 2,
                "name": "Good rule",
                "conditions_json": json.dumps({"field": "vendor_name", "op": "contains", "value": "Google"}),
                "action_type": "set_push_to",
                "action_value": "tally",
            },
        ]
        result = apply_rules(rules, {"vendor_name": "Google LLC"})
        assert result is not None
        assert result["id"] == 2  # Skipped bad rule, matched good one


# ─── Edge cases ───────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_conditions(self):
        assert evaluate_rule({}, {"vendor_name": "test"}) is False

    def test_empty_group(self):
        cond = {"operator": "AND", "conditions": []}
        assert evaluate_rule(cond, {"vendor_name": "test"}) is False

    def test_numeric_string_comparison(self):
        """total_amount might come as string from some sources."""
        cond = {"field": "total_amount", "op": "greater_than", "value": "5000"}
        assert evaluate_rule(cond, {"total_amount": "10000"}) is True
        assert evaluate_rule(cond, {"total_amount": 10000}) is True

    def test_conditions_json_as_string(self):
        """apply_rules should handle conditions_json as both string and dict."""
        rules = [
            {
                "id": 1,
                "name": "Test",
                "conditions_json": {"field": "vendor_name", "op": "equals", "value": "Google"},
                "action_type": "set_push_to",
                "action_value": "zoho",
            },
        ]
        result = apply_rules(rules, {"vendor_name": "Google"})
        assert result is not None
        assert result["id"] == 1
