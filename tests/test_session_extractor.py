"""Tests for the session extractor module."""

import json
from unittest.mock import patch, MagicMock
import pytest

from mem0_enhanced.llm import LLMClient, LLMResponse
from mem0_enhanced.session_extractor import SessionExtractor


@pytest.fixture
def extractor():
    llm = MagicMock(spec=LLMClient)
    return SessionExtractor(llm=llm)


def _mock_llm_response(shards: list[dict]) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(shards),
        input_tokens=200,
        output_tokens=100,
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
    )


class TestSessionExtractor:
    def test_normal_conversation(self, extractor):
        """Should extract 2-5 typed shards from a coding conversation."""
        shards = [
            {"text": "User is building a speech-to-text iOS app using SwiftUI.", "type": "durable_fact"},
            {"text": "User prefers short, direct responses.", "type": "preference"},
            {"text": "Decided to use StoreKit 2 for in-app purchases.", "type": "decision"},
        ]
        extractor.llm.generate.return_value = _mock_llm_response(shards)
        result = extractor.extract("User: I'm building an iOS app...\nAssistant: Great!")

        assert len(result) == 3
        assert all("text" in s and "type" in s for s in result)

    def test_empty_conversation(self, extractor):
        """Trivial conversation should return empty list."""
        extractor.llm.generate.return_value = _mock_llm_response([])
        result = extractor.extract("User: Hi\nAssistant: Hello!")

        assert result == []

    def test_deduplication_context(self, extractor):
        """Should pass existing memories to the prompt for dedup."""
        shards = [{"text": "New fact.", "type": "durable_fact"}]
        extractor.llm.generate.return_value = _mock_llm_response(shards)
        result = extractor.extract(
            "User: test\nAssistant: test",
            existing_memories=["Already known fact"],
        )

        call_args = extractor.llm.generate.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][0]
        assert "Already stored" in prompt
        assert "Already known fact" in prompt

    def test_all_types_validated(self, extractor):
        """Each shard type should be validated against the allowed set."""
        shards = [
            {"text": "Valid", "type": "preference"},
            {"text": "Invalid", "type": "random_type"},
            {"text": "Also valid", "type": "open_loop"},
        ]
        extractor.llm.generate.return_value = _mock_llm_response(shards)
        result = extractor.extract("test conversation")

        assert len(result) == 2
        types = [s["type"] for s in result]
        assert "random_type" not in types

    def test_llm_failure(self, extractor):
        """Should return empty list on failure."""
        extractor.llm.generate.side_effect = Exception("Connection refused")
        result = extractor.extract("test conversation")

        assert result == []

    def test_malformed_response(self, extractor):
        """Non-JSON response should return empty list."""
        extractor.llm.generate.return_value = LLMResponse(
            text="not json at all",
            input_tokens=10, output_tokens=5,
            provider="anthropic", model="test",
        )
        result = extractor.extract("test conversation")

        assert result == []
