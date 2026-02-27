"""Tests for the query rewriter module."""

import json
from unittest.mock import patch, MagicMock
import pytest

from mem0_enhanced.llm import LLMClient, LLMResponse
from mem0_enhanced.query_rewriter import QueryRewriter
from mem0_enhanced.types import RewrittenQuery


@pytest.fixture
def rewriter():
    llm = MagicMock(spec=LLMClient)
    return QueryRewriter(llm=llm)


def _mock_llm_response(queries: list[str]) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(queries),
        input_tokens=50,
        output_tokens=20,
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
    )


class TestQueryRewriter:
    def test_vague_query_with_context(self, rewriter):
        """Vague query with context should produce expanded queries."""
        rewriter.llm.generate.return_value = _mock_llm_response(
            ["authentication system decisions", "auth architecture choices"]
        )
        result = rewriter.rewrite(
            "what did we decide about that?",
            session_context="We discussed authentication and decided to use JWT tokens.",
        )

        assert isinstance(result, RewrittenQuery)
        assert result.original == "what did we decide about that?"
        assert len(result.expanded) >= 2
        assert result.expanded[0] == "what did we decide about that?"
        assert result.session_context_used is True

    def test_specific_query(self, rewriter):
        """Already-specific query should still produce valid results."""
        rewriter.llm.generate.return_value = _mock_llm_response(
            ["StoreKit 2 implementation details"]
        )
        result = rewriter.rewrite("StoreKit 2 implementation")

        assert result.original == "StoreKit 2 implementation"
        assert len(result.expanded) >= 1
        assert result.session_context_used is False

    def test_llm_failure_returns_original(self, rewriter):
        """When LLM fails, should gracefully return [original_query]."""
        rewriter.llm.generate.side_effect = Exception("Connection refused")
        result = rewriter.rewrite("test query")

        assert result.expanded == ["test query"]
        assert result.session_context_used is False

    def test_malformed_llm_response(self, rewriter):
        """When LLM returns non-JSON, should return [original_query]."""
        rewriter.llm.generate.return_value = LLMResponse(
            text="not valid json at all",
            input_tokens=10, output_tokens=5,
            provider="anthropic", model="test",
        )
        result = rewriter.rewrite("test query")

        assert result.expanded == ["test query"]

    def test_empty_context(self, rewriter):
        """No context should still produce reasonable results."""
        rewriter.llm.generate.return_value = _mock_llm_response(
            ["Python debugging techniques", "debug Python code"]
        )
        result = rewriter.rewrite("how to debug Python")

        assert len(result.expanded) >= 2
        assert result.session_context_used is False

    def test_caps_at_three_expanded(self, rewriter):
        """Should never return more than original + 3 expanded queries."""
        rewriter.llm.generate.return_value = _mock_llm_response(
            ["q1", "q2", "q3", "q4", "q5"]
        )
        result = rewriter.rewrite("test")

        assert len(result.expanded) <= 4
