"""
Tests for helper functions extracted from legacy code.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.query_engine.helpers import (
    dedupe,
    extract_json_text,
    extract_sql_text,
    make_json_safe,
    normalize_period,
    parse_property_ref,
    quote_sql_literal,
)
from app.query_engine.errors import PlannerError, SQLValidationError


class TestDedupe:
    def test_simple_list(self):
        assert dedupe([1, 2, 3, 2, 1]) == [1, 2, 3]

    def test_dict_list(self):
        items = [{"a": 1}, {"b": 2}, {"a": 1}]
        assert len(dedupe(items)) == 2

    def test_empty_list(self):
        assert dedupe([]) == []

    def test_preserves_order(self):
        assert dedupe([3, 1, 2, 1, 3]) == [3, 1, 2]


class TestMakeJsonSafe:
    def test_decimal_integer(self):
        assert make_json_safe(Decimal("42")) == 42

    def test_decimal_float(self):
        result = make_json_safe(Decimal("3.14"))
        assert isinstance(result, float)
        assert abs(result - 3.14) < 0.001

    def test_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        assert make_json_safe(dt) == "2024-01-15T10:30:00"

    def test_date(self):
        d = date(2024, 1, 15)
        assert make_json_safe(d) == "2024-01-15"

    def test_bytes(self):
        assert make_json_safe(b"hello") == "hello"

    def test_none(self):
        assert make_json_safe(None) is None

    def test_nested_dict(self):
        data = {"amount": Decimal("99.99"), "date": date(2024, 1, 1)}
        result = make_json_safe(data)
        assert isinstance(result["amount"], float)
        assert result["date"] == "2024-01-01"

    def test_nested_list(self):
        data = [Decimal("1"), Decimal("2.5")]
        result = make_json_safe(data)
        assert result == [1, 2.5]


class TestExtractJsonText:
    def test_plain_json(self):
        text = '{"route": "simple_db", "reason": "data query"}'
        result = extract_json_text(text)
        assert result == text

    def test_markdown_wrapped_json(self):
        text = '```json\n{"route": "simple_db"}\n```'
        result = extract_json_text(text)
        assert '"route"' in result

    def test_json_with_surrounding_text(self):
        text = 'Here is the plan: {"route": "simple_db"} end.'
        result = extract_json_text(text)
        assert result == '{"route": "simple_db"}'

    def test_empty_raises(self):
        with pytest.raises(PlannerError, match="empty"):
            extract_json_text("")

    def test_no_json_raises(self):
        with pytest.raises(PlannerError, match="Could not find"):
            extract_json_text("no json here")


class TestExtractSqlText:
    def test_plain_sql(self):
        sql = "SELECT * FROM POLICY"
        assert extract_sql_text(sql) == sql

    def test_markdown_wrapped(self):
        sql = "```sql\nSELECT * FROM POLICY;\n```"
        result = extract_sql_text(sql)
        assert "SELECT * FROM POLICY" in result

    def test_strips_trailing_semicolon(self):
        sql = "SELECT * FROM POLICY;"
        assert extract_sql_text(sql) == "SELECT * FROM POLICY"

    def test_empty_raises(self):
        with pytest.raises(SQLValidationError, match="empty"):
            extract_sql_text("")


class TestParsePropertyRef:
    def test_valid_ref(self):
        entity, column = parse_property_ref("POLICY.POLICY_NUMBER")
        assert entity == "POLICY"
        assert column == "POLICY_NUMBER"

    def test_with_spaces(self):
        entity, column = parse_property_ref(" BROKER . BROKER_NAME ")
        assert entity == "BROKER"
        assert column == "BROKER_NAME"

    def test_invalid_no_dot(self):
        with pytest.raises(PlannerError, match="Invalid property_ref"):
            parse_property_ref("POLICY")

    def test_invalid_empty(self):
        with pytest.raises(PlannerError, match="Invalid property_ref"):
            parse_property_ref("")

    def test_invalid_none(self):
        with pytest.raises(PlannerError, match="Invalid property_ref"):
            parse_property_ref(None)


class TestNormalizePeriod:
    def test_valid_periods(self):
        assert normalize_period("last quarter") == "last quarter"
        assert normalize_period("this year") == "this year"
        assert normalize_period("today") == "today"
        assert normalize_period("yesterday") == "yesterday"
        assert normalize_period("ytd") == "ytd"
        assert normalize_period("mtd") == "mtd"

    def test_underscores(self):
        assert normalize_period("last_quarter") == "last quarter"

    def test_case_insensitive(self):
        assert normalize_period("LAST QUARTER") == "last quarter"

    def test_invalid(self):
        assert normalize_period("next century") is None

    def test_none(self):
        assert normalize_period(None) is None

    def test_empty(self):
        assert normalize_period("") is None


class TestQuoteSqlLiteral:
    def test_string(self):
        assert quote_sql_literal("hello") == "'hello'"

    def test_string_with_quote(self):
        assert quote_sql_literal("it's") == "'it''s'"

    def test_integer(self):
        assert quote_sql_literal(42) == "42"

    def test_float(self):
        assert quote_sql_literal(3.14) == "3.14"

    def test_none(self):
        assert quote_sql_literal(None) == "NULL"
