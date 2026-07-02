"""
Tests for the router module.
"""
from __future__ import annotations

import pytest

from app.query_engine.router import is_greeting_or_general, extract_candidate_terms
from app.query_engine.helpers import normalize_text


class TestNormalizeText:
    def test_basic_normalization(self):
        assert normalize_text("  Hello, World!  ") == "hello world"

    def test_special_characters(self):
        assert normalize_text("What's the count?") == "what s the count"

    def test_multiple_spaces(self):
        assert normalize_text("hello    world") == "hello world"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_none_input(self):
        assert normalize_text(None) == ""


class TestIsGreetingOrGeneral:
    def test_greeting_hi(self):
        assert is_greeting_or_general("hi") is True

    def test_greeting_hello(self):
        assert is_greeting_or_general("hello") is True

    def test_greeting_hey(self):
        assert is_greeting_or_general("hey") is True

    def test_thanks(self):
        assert is_greeting_or_general("thanks") is True

    def test_thank_you(self):
        assert is_greeting_or_general("thank you") is True

    def test_help(self):
        assert is_greeting_or_general("help") is True

    def test_greeting_with_suffix(self):
        assert is_greeting_or_general("hi there") is True

    def test_db_question_not_greeting(self):
        assert is_greeting_or_general("how many policies") is False

    def test_count_question_not_greeting(self):
        assert is_greeting_or_general("total premium last quarter") is False


class TestExtractCandidateTerms:
    def test_single_word(self):
        terms = extract_candidate_terms("policy")
        assert "policy" in terms

    def test_multi_word(self):
        terms = extract_candidate_terms("total premium amount")
        assert "total premium amount" in terms
        assert "total premium" in terms
        assert "premium amount" in terms
        assert "total" in terms
        assert "premium" in terms
        assert "amount" in terms

    def test_sorted_by_length_desc(self):
        terms = extract_candidate_terms("a b c")
        # Longer n-grams should come first
        lengths = [len(t.split()) for t in terms]
        for i in range(len(lengths) - 1):
            assert lengths[i] >= lengths[i + 1]

    def test_empty_string(self):
        terms = extract_candidate_terms("")
        assert terms == []
