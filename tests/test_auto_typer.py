"""Tests for the auto typer module."""

from unittest.mock import MagicMock
import pytest

from mem0_enhanced.llm import LLMClient, LLMResponse
from mem0_enhanced.auto_typer import AutoTyper, VALID_TYPES


@pytest.fixture
def typer():
    llm = MagicMock(spec=LLMClient)
    return AutoTyper(llm=llm)


def _mock_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=30,
        output_tokens=5,
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
    )


class TestAutoTyper:
    def test_clear_preference(self, typer):
        """'User prefers dark mode' -> preference."""
        typer.llm.generate.return_value = _mock_llm_response("preference")
        result = typer.classify("User prefers dark mode in all IDEs")
        assert result == "preference"

    def test_clear_fact(self, typer):
        """'User is an iOS developer' -> durable_fact."""
        typer.llm.generate.return_value = _mock_llm_response("durable_fact")
        result = typer.classify("User is an iOS developer using SwiftUI")
        assert result == "durable_fact"

    def test_clear_decision(self, typer):
        """'Decided to use PostgreSQL' -> decision."""
        typer.llm.generate.return_value = _mock_llm_response("decision")
        result = typer.classify("Decided to use PostgreSQL instead of SQLite")
        assert result == "decision"

    def test_open_loop(self, typer):
        """'Still needs to set up CI/CD' -> open_loop."""
        typer.llm.generate.return_value = _mock_llm_response("open_loop")
        result = typer.classify("Still needs to set up CI/CD pipeline")
        assert result == "open_loop"

    def test_correction(self, typer):
        """Timezone correction -> correction."""
        typer.llm.generate.return_value = _mock_llm_response("correction")
        result = typer.classify("User's timezone is actually PST, not EST as previously stored")
        assert result == "correction"

    def test_batch_classification(self, typer):
        """5 mixed memories -> all classified correctly, same length."""
        texts = [
            "User prefers tabs over spaces",
            "User is a Python developer",
            "Decided to use FastAPI",
            "Need to finish the docs",
            "Email was wrong, corrected to replacement@example.com",
        ]
        typer.llm.generate.return_value = _mock_llm_response(
            '["preference", "durable_fact", "decision", "open_loop", "correction"]'
        )
        results = typer.classify_batch(texts)

        assert len(results) == 5
        assert results == ["preference", "durable_fact", "decision", "open_loop", "correction"]

    def test_llm_failure(self, typer):
        """Should return 'durable_fact' on failure."""
        typer.llm.generate.side_effect = Exception("Connection refused")
        result = typer.classify("test memory")
        assert result == "durable_fact"

    def test_ambiguous_text(self, typer):
        """Should return a valid type for ambiguous input."""
        typer.llm.generate.return_value = _mock_llm_response("durable_fact")
        result = typer.classify("Something about the project")
        assert result in VALID_TYPES
